"""The system's media controls (R7.8, A4.5): MusiKata shows the song playing and its cover to the
system, and takes play, pause, next, previous and seek from it, by MPRIS on Linux (mpris.py), the
System Media Transport Controls on Windows (smtc.py) and Now Playing on macOS (nowplaying_mac.py).

`MediaControls` is the one interface the rest of the app sees: it follows the Player bridge and
tells the platform's backend what plays (`now_playing`, `state`, `seeked`), and does what the
backend's commands ask of the Player, the window or the app. What it tells and what each command
does is controls.py's, without Qt; the backends only translate. A platform without a backend, or
one whose backend can't start (no session bus, a module that won't import), still plays: the App
log says why, once, and nothing else changes.

The cover is the cover cache's thumbnail (covers.py) as a file URL, found, or made, off the GUI
thread (A1.3): the song is shown at once and again with its cover when the file is there."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot
from PySide6.QtGui import QWindow

from musikata_core.clock import Clock, SystemClock

from .controls import (
    Backend,
    Command,
    Now,
    Song,
    State,
    Watch,
    actions,
    backend_for,
    song_of,
    state_of,
    thumb_of,
)

if TYPE_CHECKING:
    from ..bridges import Player

log = logging.getLogger(__name__)

# a backend's opener: given where to send the commands it hears (from any thread), what reads the
# position now, and the window, the backend started; raises when it can't start
Opener = Callable[[Callable[[Command], None], Callable[[], float], QWindow | None], Backend]
# the cover's thumbnail file by its name, found or made (covers.Covers.file); None when it can't be
Art = Callable[[str], str | None]


def opener_for(platform: str) -> Opener | None:
    """The opener of the platform's backend (controls.backend_for), imported only there; None
    where there is none."""
    name = backend_for(platform)
    if name == "mpris":
        from . import mpris

        return mpris.open_session
    if sys.platform == "win32" and name == "smtc":  # pragma: no cover - measured on Windows
        from . import smtc

        return smtc.open_window
    if sys.platform == "darwin" and name == "nowplaying_mac":  # pragma: no cover - on macOS
        from . import nowplaying_mac

        return nowplaying_mac.open_center
    return None


def now_of(player: Player) -> Now:
    """The Player bridge as the system is told of it."""
    info = player.shown()
    return Now(
        path=player.property("path"),
        title=player.property("title"),
        artist=info.artist if info is not None else "",
        album=info.album if info is not None else "",
        length=player.property("length"),
        cover=player.property("cover"),
        on=player.property("playing") or player.property("paused"),
        playing=player.property("playing"),
        queued=player.queue.current is not None,
        seekable=player.property("seekable"),
        position=player.property("position"),
        volume=player.property("volume"),
    )


class MediaControls(QObject):
    """Follows `player` for the system's media controls through the backend `opener` starts
    (None: there is none), and obeys its commands. `art` finds a cover's file; `window` is raised
    by the system's Raise and given to the backend (Windows' controls are the window's); `leave`
    ends MusiKata (MPRIS's Quit). `backend` is None when none started."""

    commanded = Signal(object)  # a Command: sent from any thread, obeyed on the GUI thread
    _art_found = Signal(str, str)  # a cover's thumbnail name and its file ("" when none)

    def __init__(
        self,
        player: Player,
        opener: Opener | None,
        art: Art | None = None,
        window: QWindow | None = None,
        leave: Callable[[], None] = QCoreApplication.quit,
        clock: Clock | None = None,
    ) -> None:
        super().__init__()
        self._player, self._art, self._window, self._leave = player, art, window, leave
        self._clock = clock or SystemClock()
        self._watch = Watch()
        self._song: Song | None = None
        self._state: State | None = None
        self._files: dict[str, str] = {}  # each thumbnail's file found, by name ("" for none)
        self._finding: ThreadPoolExecutor | None = None
        self.backend: Backend | None = None
        self.commanded.connect(self.obey)
        self._art_found.connect(self._on_art_found)
        if opener is None:
            log.info("the system's media controls: there are none on this platform; MusiKata "
                     "plays without them")  # fmt: skip
            return
        try:
            self.backend = opener(self.commanded.emit, self._position, window)
        except Exception as e:  # anything a platform's module raises: it plays without them
            # its words, not the error: a log record kept (a test's) would keep its traceback,
            # and with it the frames that made this window and what they held (A1.3)
            log.warning("the system's media controls didn't start (%s: %s); MusiKata plays "
                        "without them", type(e).__name__, str(e))  # fmt: skip
            return
        for signal in self._signals():
            signal.connect(self._follow)
        self._follow()

    def _signals(self) -> tuple[Any, ...]:
        p = self._player
        return (p.changed, p.positionChanged, p.volumeChanged, p.queueChanged)

    def _position(self) -> float:
        return float(self._player.property("position"))

    @Slot()
    def _follow(self) -> None:
        """Tells the backend what changed in the Player: the song, its state, a seek."""
        if self.backend is None:
            return
        now = now_of(self._player)
        seen = self._watch.look(now, self._clock.monotonic())
        song = song_of(now, seen.track, self._art_of(thumb_of(now.cover)))
        if song != self._song or seen.new:
            self._song = song
            self.backend.now_playing(song)
        state = state_of(now)
        if state != self._state:
            self._state = state
            self.backend.state(state, now.position)
        if seen.seeked is not None:
            self.backend.seeked(seen.seeked)

    def _art_of(self, thumb: str) -> str:
        """The file URL of the cover `thumb`, when its file was found; else "", and it is looked
        for off the GUI thread, the song shown again when it is found."""
        if not thumb or self._art is None:
            return ""
        if thumb in self._files:
            found = self._files[thumb]
            return Path(found).as_uri() if found else ""
        self._files[thumb] = ""  # looked for once
        if self._finding is None:
            self._finding = ThreadPoolExecutor(1, thread_name_prefix="media cover")
        art = self._art
        future = self._finding.submit(art, thumb)
        future.add_done_callback(lambda f: self._found(thumb, f))
        return ""

    def _found(self, thumb: str, future: Future[str | None]) -> None:
        """On the finding thread: says what was found, to the GUI thread. Its failure is asked
        for, not raised again here, where its traceback would take this frame, and this object
        with it, into a cycle with the future (A1.3)."""
        error = future.exception()
        if error is not None:  # the cover cache's, read off the GUI thread
            log.warning("the cover %s for the system's media controls: %s", thumb, error)
        self._art_found.emit(thumb, "" if error is not None else future.result() or "")

    @Slot(str, str)
    def _on_art_found(self, thumb: str, path: str) -> None:
        self._files[thumb] = path
        if path:
            self._follow()

    @Slot(object)
    def obey(self, command: Command) -> None:
        """Does what the system asked (controls.actions)."""
        now = now_of(self._player)
        for name, value in actions(command, now, self._watch.track):
            log.debug(
                "the system's media controls: %s %s", name, value if value is not None else ""
            )
            if name == "raise":
                if self._window is not None:
                    self._window.show()
                    self._window.raise_()
                    self._window.requestActivate()
            elif name == "quit":
                self._leave()
            elif value is None:
                getattr(self._player, name)()
            else:
                getattr(self._player, name)(value)

    def close(self) -> None:
        """Lets go of the system's controls, and waits for a cover being found: for closing,
        before the index closes."""
        if self.backend is not None:
            for signal in self._signals():
                signal.disconnect(self._follow)
            self.backend.close()
            self.backend = None
        if self._finding is not None:
            self._finding.shutdown(wait=True)
            self._finding = None


def start(player: Player, window: QWindow | None, art: Art | None) -> MediaControls:
    """The system's media controls for this platform, following `player`."""
    return MediaControls(player, opener_for(sys.platform), art, window)
