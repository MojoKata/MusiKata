"""Starting MusiKata: the options, the root's index (A2.9), the window, the first scan; `--tour DIR`
drives it through the screens instead (A1.6), and `--play FILE` plays one file to its end and quits,
which is how each build is started once to test it (build-and-release.md, "The builds"). One
MusiKata at a time and opening files (R1.6, R1.7) come with the slices that need them
(DEVELOP.md)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from shiboken6 import Shiboken

from musikata_core import __version__, db, roots, workers
from musikata_core.audio.decode import DecodeError
from musikata_core.clock import Clock, SystemClock

from .bridges import Library, Player
from .covers import Covers
from .player import FALLBACK_RATE, NO_DEVICE, DecodedSong, Engine, Opener

QML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml", "Main.qml")


@dataclass(frozen=True)
class Options:
    root: str
    tour: str | None = None
    tour_only: str = ""
    play: str | None = None


def home_of(env: Mapping[str, str]) -> str:
    return env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")


def options(argv: Sequence[str], env: Mapping[str, str]) -> Options:
    """The command line. The root is --root, else the home's Music folder: choosing one at the
    first start (R2.1) comes with slice 3."""
    ap = argparse.ArgumentParser(prog="musikata", description="A music player and organizer")
    ap.add_argument("--root", help="the music root (~/Music)")
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
    root = os.path.expanduser(a.root) if a.root else os.path.join(home_of(env), "Music")
    play = os.path.abspath(os.path.expanduser(a.play)) if a.play else None
    return Options(os.path.abspath(root), a.tour, a.tour_only, play)


def cache_of(index: db.Index, env: Mapping[str, str]) -> str:
    """Where the root's cover thumbnails are kept: its caches (R1.5), under its index's key."""
    key = os.path.basename(os.path.dirname(index.path))
    return os.path.join(roots.caches_dir(env), key, "covers")


def open_index(root: str, env: Mapping[str, str], clock: Clock) -> db.Index:
    """The root's index, found or made where A2.9 says."""
    found = roots.find_index(root, roots.roots_dir(env), clock)
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
        playback thread, the scan's thread and the index."""
        self.window.close()
        Shiboken.delete(self.engine)
        self.player.close()
        self.library.wait()
        self.index.close()


def load(
    root: str,
    env: Mapping[str, str],
    clock: Clock,
    pool: Callable[[], Executor] = workers.pool,
    playback: Callable[[], Engine] = Engine,
) -> Shell:
    """The window over the root's index, not yet shown. `playback` makes the playback thread's
    engine (a test's plays generated audio on a device it chooses)."""
    index = open_index(root, env, clock)
    library = Library(root, index, home_of(env), pool)
    player = Player(root, playback())
    player.nowPlaying.connect(library.show_playing)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("covers", Covers(root, index.read, cache_of(index, env)))
    engine.setInitialProperties({"library": library, "player": player})
    engine.load(QUrl.fromLocalFile(QML))
    objects = engine.rootObjects()
    if not objects or not isinstance(objects[0], QQuickWindow):
        raise RuntimeError(f"{QML} didn't load")
    return Shell(engine, objects[0], library, player, index)


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
    shell = load(opts.root, os.environ, SystemClock())
    shell.library.rescan()
    once = None
    if opts.tour:
        from .tour import Tour

        Tour(shell.window, shell.library, opts.tour, opts.tour_only).start()
    else:
        shell.window.show()
        if opts.play:
            once = PlayOnce(shell.player, opts.play, app.quit)
    code = app.exec()
    shell.close()
    if once is not None:
        code, why = outcome(once.last, once.error, shell.library.last, once.decoded)
        print(f"{opts.play}: {why}", flush=True)
    return code
