"""Starting MusiKata: the options, the root (R2.1: given for the run, or the configured one, or
chosen at the first start), its index (A2.9), the window, the first scan; `--tour DIR` drives it
through the screens instead (A1.6), and `--play FILE` plays one file to its end and quits, which is
how each build is started once to test it (build-and-release.md, "The builds"). One MusiKata at a
time and opening files (R1.6, R1.7) come with the slices that need them (DEVELOP.md).

A run is a `Session`: the first start's window (firstrun.py) until a root is chosen, then the
window over the root; a root chosen again (Choose another folder…, R2.10) opens in its place."""

from __future__ import annotations

import argparse
import logging
import os
import platform
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from shiboken6 import Shiboken

from musikata_core import __version__, db, roots, settings, workers
from musikata_core.audio.decode import DecodeError
from musikata_core.clock import Clock, SystemClock

from .bridges import Library, Player
from .covers import Covers
from .firstrun import FirstRun, music_folder
from .player import FALLBACK_RATE, NO_DEVICE, DecodedSong, Engine, Opener

QML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml", "Main.qml")
FIRST_QML = os.path.join(os.path.dirname(QML), "FirstRun.qml")


@dataclass(frozen=True)
class Options:
    root: str | None = None  # --root: the root for this run only (R2.1.2)
    tour: str | None = None
    tour_only: str = ""
    play: str | None = None


def home_of(env: Mapping[str, str]) -> str:
    return env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")


def options(argv: Sequence[str], env: Mapping[str, str]) -> Options:
    """The command line: --root, the music root for this run only (R2.1.2), else None, the
    configured root (`root_for`)."""
    ap = argparse.ArgumentParser(prog="musikata", description="A music player and organizer")
    ap.add_argument(
        "--root", help="the music root for this run only, the one configured left as it is"
    )
    ap.add_argument("--tour", metavar="DIR", help="save each screen to DIR and check its layout")
    ap.add_argument("--tour-only", metavar="NAMES", default="", help="those screens, by name")
    ap.add_argument(
        "--play",
        metavar="FILE",
        help="play FILE to its end and quit: 0 when it played and the scan went well, 3 when"
        " there was no sound device and it decoded instead",
    )
    ap.add_argument("--version", action="version", version=f"MusiKata {__version__}")
    a = ap.parse_args(list(argv))
    root = os.path.abspath(os.path.expanduser(a.root)) if a.root else None
    play = os.path.abspath(os.path.expanduser(a.play)) if a.play else None
    return Options(root, a.tour, a.tour_only, play)


def root_for(opts: Options, configured: str | None) -> tuple[str | None, bool]:
    """The root a run opens, and whether it is for this run only (R2.1.2): --root, else the
    configured root (R2.1), else for --play the file's own folder (a build's start test needs no
    first start), else None: the first start asks for one."""
    if opts.root is not None:
        return opts.root, True
    if configured is not None:
        return configured, False
    if opts.play is not None:
        return os.path.dirname(opts.play), True
    return None, False


def cache_of(index: db.Index, env: Mapping[str, str]) -> str:
    """Where the root's cover thumbnails are kept: its caches (R1.5), under its index's key."""
    key = os.path.basename(os.path.dirname(index.path))
    return os.path.join(roots.caches_dir(env), key, "covers")


def open_index(root: str, env: Mapping[str, str], clock: Clock) -> db.Index:
    """The root's index, found or made where A2.9 says. A root that isn't there (R2.10) is shown
    from the index that last opened it, found by its path, and nothing is made in its place; one
    never opened gets an empty index under a hash of its path."""
    base = roots.roots_dir(env)
    if os.path.isdir(root):
        found = roots.find_index(root, base, clock)
    else:
        found = roots.recorded(root, base) or roots.Found(
            os.path.join(base, roots.path_key(root)), roots.path_key(root), False
        )
        os.makedirs(found.folder, exist_ok=True)
    return db.Index(os.path.join(found.folder, "musikata.db"))


@dataclass
class Shell:
    """What a running MusiKata holds: the engine, its window and the bridges."""

    engine: QQmlApplicationEngine
    window: QQuickWindow
    library: Library
    player: Player
    index: db.Index

    def close(self) -> None:
        """The window and its engine first, while what they bind to is still there; then the
        playback thread, the watcher, the scan's thread and the worker processes, and the
        index."""
        self.window.close()
        Shiboken.delete(self.engine)
        self.player.close()
        self.library.close()
        self.index.close()


def load(
    root: str,
    env: Mapping[str, str],
    clock: Clock,
    pool: Callable[[], Executor] = workers.pool,
    playback: Callable[[], Engine] = Engine,
    given: bool = False,
) -> Shell:
    """The window over the root's index, not yet shown, the root watched once scanned (A2.4).
    `playback` makes the playback thread's engine (a test's plays generated audio on a device it
    chooses). `given`: the root is for this run only, and the window's title names it (R2.1.2).
    A root that isn't there opens with its library as it was (R2.10)."""
    index = open_index(root, env, clock)
    missing = not os.path.isdir(root)
    library = Library(
        root, index, home_of(env), pool, clock=clock, watching=True, missing=missing, given=given
    )
    player = Player(root, playback(), refuse=library.unplayable)
    player.nowPlaying.connect(library.show_playing)
    library.property("folders").play.connect(player.play)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("covers", Covers(root, index.read, cache_of(index, env)))
    engine.setInitialProperties({"library": library, "player": player})
    engine.load(QUrl.fromLocalFile(QML))
    objects = engine.rootObjects()
    if not objects or not isinstance(objects[0], QQuickWindow):
        raise RuntimeError(f"{QML} didn't load")
    window = objects[0]
    # where the root can't be watched, gaining focus rescans it (R2.4)
    window.activeChanged.connect(lambda: library.window_active(window.isActive()))
    return Shell(engine, window, library, player, index)


@dataclass
class FirstStart:
    """The first start's window (X01-first-run) and what it binds to."""

    engine: QQmlApplicationEngine
    window: QQuickWindow
    first: FirstRun

    def close(self) -> None:
        self.window.close()
        Shiboken.delete(self.engine)


def first_start(env: Mapping[str, str]) -> FirstStart:
    """The first start's window, not yet shown: it asks for the root (R2.1)."""
    first = FirstRun(music_folder(home_of(env)), home_of(env))
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"first": first})
    engine.load(QUrl.fromLocalFile(FIRST_QML))
    objects = engine.rootObjects()
    if not objects or not isinstance(objects[0], QQuickWindow):
        raise RuntimeError(f"{FIRST_QML} didn't load")
    return FirstStart(engine, objects[0], first)


def place_like(window: QQuickWindow, old: QQuickWindow) -> None:
    """Gives `window` the place, size and state (maximized, full screen) of `old`, which it takes
    the place of, and shows it if `old` showed."""
    window.setGeometry(old.geometry())
    if old.isVisible():
        window.setVisibility(old.visibility())


class Session(QObject):
    """A run (R2.1): the first start's window while no root is configured, then the window over
    the root. A root chosen there, or chosen again with Choose another folder… (R2.10), becomes the
    configured root, unless the run's root was given for it only (R2.1.2), and opens in the
    window's place, its library scanned; the one before closes. `opened` says a root opened."""

    opened = Signal()

    def __init__(
        self,
        env: Mapping[str, str],
        clock: Clock,
        given: bool = False,
        pool: Callable[[], Executor] = workers.pool,
        playback: Callable[[], Engine] = Engine,
    ) -> None:
        super().__init__()
        self._env, self._clock, self.given = env, clock, given
        self._pool, self._playback = pool, playback
        self.shell: Shell | None = None
        self.first: FirstStart | None = None

    @property
    def window(self) -> QQuickWindow:
        """The window this run shows now."""
        if self.shell is not None:
            return self.shell.window
        assert self.first is not None, "the session hasn't started"
        return self.first.window

    @property
    def library(self) -> Library | None:
        """The open root's library; None at the first start, before one is chosen."""
        return self.shell.library if self.shell is not None else None

    def start(self, root: str | None) -> None:
        """Opens `root` and scans it, or, with None, asks for one (the first start)."""
        if root is None:
            self.first = first_start(self._env)
            self.first.first.chosen.connect(self.choose, Qt.ConnectionType.QueuedConnection)
            return
        self._open(root)

    def _open(self, root: str) -> Shell:
        shell = load(root, self._env, self._clock, self._pool, self._playback, self.given)
        shell.library.rootChosen.connect(self.choose, Qt.ConnectionType.QueuedConnection)
        self.shell = shell
        shell.library.rescan()
        return shell

    def choose(self, root: str) -> None:
        """A root chosen (R2.1, R2.10): kept as the configured root, unless the run's was given
        for it only, and opened in the window's place."""
        if not self.given:
            path, home = settings.shared_path(self._env), home_of(self._env)
            settings.choose_root(path, home, root, platform.node() or "this computer")
        old_window = self.window
        old: Shell | FirstStart | None = self.shell or self.first
        self.first = None
        shell = self._open(root)
        place_like(shell.window, old_window)
        if old is not None:
            old.close()
        self.opened.emit()

    def close(self) -> None:
        if self.shell is not None:
            self.shell.close()
        if self.first is not None:
            self.first.close()


NO_DEVICE_STATUS = 3  # --play's status when the file decoded to its end with no device to play on


def outcome(last: str, error: str, scan: object, decoded: float | None = None) -> tuple[int, str]:
    """What `--play` ends with: its exit status and the line saying why, from how the song stopped
    (the Player bridge's `last`: "ended", "stopped", "failed" or "" when it never began), why it
    failed, the seconds it decoded when there was no sound device (None when it didn't try), and
    the scan's outcome (a Result, the exception it raised, or None). 0 only when the song played to
    its end and the scan went well; NO_DEVICE_STATUS when, with no sound device, it decoded to its
    end instead, as on a machine with no sound card that a build's start test runs on."""
    if isinstance(scan, BaseException):
        return 1, f"the scan failed: {type(scan).__name__}: {scan}"
    if last == "ended":
        return 0, "played to its end"
    if last == "failed" and error == NO_DEVICE and decoded is not None:
        return NO_DEVICE_STATUS, f"decoded to its end ({decoded:.1f} s); {NO_DEVICE} to play it on"
    if last == "failed":
        return 1, f"couldn't play: {error}"
    return 1, "closed before the song ended"


def decode_through(path: str, opener: Opener = DecodedSong) -> float:
    """Decodes the file at `path` to its end, as playing it would, at the fallback rate in stereo;
    the seconds it held. Raises DecodeError when it can't."""
    song = opener(path, FALLBACK_RATE, 2)
    try:
        return sum(len(block) for block in song.blocks(4096)) / FALLBACK_RATE
    finally:
        song.close()


class PlayOnce:
    """`--play FILE`: plays the file and calls `done` when it has stopped, played to its end or
    not. `last` and `error` then say how. With no sound device it decodes the file instead, and
    `decoded` holds the seconds it held."""

    def __init__(
        self, player: Player, path: str, done: Callable[[], None], opener: Opener = DecodedSong
    ) -> None:
        self._player, self._path, self._done, self._opener = player, path, done, opener
        self.last = self.error = ""
        self.decoded: float | None = None
        player.nowPlaying.connect(self._on_now_playing)
        player.play_file(path)

    def _on_now_playing(self, path: str) -> None:
        if path:  # it began
            return
        self.last, self.error = self._player.last, self._player.property("error")
        if self.last == "failed" and self.error == NO_DEVICE:
            try:
                self.decoded = decode_through(self._path, self._opener)
            except DecodeError as e:
                self.error = f"{NO_DEVICE}, and {e}"
        self._done()


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("MUSIKATA_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    opts = options(sys.argv[1:] if argv is None else argv, os.environ)
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("MusiKata")
    app.setApplicationVersion(__version__)
    configured = settings.load(settings.shared_path(os.environ), home_of(os.environ)).root
    root, given = root_for(opts, configured)
    session = Session(os.environ, SystemClock(), given)
    session.start(root)
    once = None
    if opts.tour:
        from .tour import Tour

        Tour(session.window, session.library, opts.tour, opts.tour_only).start()
    else:
        session.window.show()
        if opts.play and session.shell is not None:
            once = PlayOnce(session.shell.player, opts.play, app.quit)
    code = app.exec()
    last = session.library.last if session.library is not None else None
    session.close()
    if once is not None:
        code, why = outcome(once.last, once.error, last, once.decoded)
        print(f"{opts.play}: {why}", flush=True)
    return code
