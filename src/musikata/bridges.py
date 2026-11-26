"""The objects QML sees (A1.2). `Library`: the root, its card's line, the Songs list, and the scan,
run on a thread of its own with the worker processes reading the files (A1.3, A2.2). `Player`: the
song playing, played on the playback thread (player.py, A4.1).

What the root's card says is decided here, as text (`docs/process/coding.md`: QML only lays out and
binds)."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Executor

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import db, scanner, workers

from .models import SongsModel
from .player import Engine, PlaybackThread

log = logging.getLogger(__name__)


def shown_path(path: str, home: str) -> str:
    """A path as MusiKata shows it: under the home folder as ~/…, with the system's separator."""
    home = home.rstrip("/\\")
    if home and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home) :]
    return path


def size_text(n: int) -> str:
    """Bytes as the root's card gives them: 9.8 GB, 412 MB, 3 KB (powers of 1000, as the systems'
    file managers mostly do)."""
    for unit, size in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= size:
            v = n / size
            return f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}"
    return f"{n} bytes"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def summary(songs: int, albums: int, size: int) -> str:
    """The root card's line (R2.1.1): 1,412 songs · 128 albums · 9.8 GB."""
    if not songs:
        return "No songs yet"
    return " · ".join((plural(songs, "song"), plural(albums, "album"), size_text(size)))


def scanning_text(done: int, of: int) -> str:
    """The root card's line while a scan runs (R2.3)."""
    return f"Scanning… {done:,} of {of:,}" if of else "Scanning…"


def counts(c: sqlite3.Connection) -> tuple[int, int, int]:
    """Songs, albums (an album artist's, or else an artist's, album name, case aside) and bytes."""
    r = c.execute(
        "SELECT COUNT(*), COUNT(DISTINCT lower(coalesce(albumartist, artist, '')) || char(0)"
        " || lower(album)), coalesce(SUM(size), 0) FROM song"
    ).fetchone()
    return int(r[0]), int(r[1]), int(r[2])


class Library(QObject):
    """One root and its index, as the sidebar and the views see them."""

    changed = Signal()  # the card's line, the counts
    scanningChanged = Signal()
    _progress = Signal(int, int)
    _finished = Signal()

    def __init__(
        self,
        root: str,
        index: db.Index,
        home: str,
        pool: Callable[[], Executor] = workers.pool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._index, self._home, self._pool = root, index, home, pool
        self._songs = SongsModel(index.read, parent=self)
        self._scanning = False
        self._done = self._of = 0
        self._thread: threading.Thread | None = None
        self.last: scanner.Result | BaseException | None = None  # the last scan's outcome
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)
        self._songs.reload()
        self._counts = counts(index.read())

    # ---------- the scan ----------

    @Slot()
    def rescan(self) -> None:
        """Scans the root on a thread of its own; nothing if one is running (R2.3)."""
        if self._scanning:
            return
        self._scanning = True
        self._done = self._of = 0
        self.scanningChanged.emit()
        self.changed.emit()
        self._thread = threading.Thread(target=self._scan, name="scan", daemon=True)
        self._thread.start()

    def _scan(self) -> None:
        try:
            with self._pool() as pool:
                self.last = scanner.scan(
                    self._root, self._index, pool, progress=self._progress.emit
                )
        except Exception as e:  # noqa: BLE001  (the scan's failure is shown, and MusiKata goes on)
            log.exception("the scan of %s failed", self._root)
            self.last = e
        self._finished.emit()

    @Slot(int, int)
    def _on_progress(self, done: int, of: int) -> None:
        self._done, self._of = done, of
        self.changed.emit()

    @Slot()
    def _on_finished(self) -> None:
        self._scanning = False
        self._songs.reload()
        self._counts = counts(self._index.read())
        self.scanningChanged.emit()
        self.changed.emit()

    @Slot(str)
    def show_playing(self, path: str) -> None:
        """Marks the song at `path` as playing in the Songs list ("": none)."""
        self._songs.set_playing(path)

    def wait(self) -> None:
        """Until the scan's thread has ended (its result still to be delivered): for closing."""
        if self._thread is not None:
            self._thread.join()

    # ---------- what QML reads ----------

    def _get_root(self) -> str:
        return shown_path(self._root, self._home)

    def _get_songs(self) -> SongsModel:
        return self._songs

    def _get_scanning(self) -> bool:
        return self._scanning

    def _get_line(self) -> str:
        return scanning_text(self._done, self._of) if self._scanning else summary(*self._counts)

    def _get_count_text(self) -> str:
        return plural(self._counts[0], "song")

    def _get_empty_text(self) -> str:
        if self._counts[0]:
            return ""
        if self._scanning:
            return "Reading your music…"
        return f"No songs in {self._get_root()}"

    root = QtProperty(str, _get_root, constant=True)
    songs = QtProperty(QObject, _get_songs, constant=True)
    scanning = QtProperty(bool, _get_scanning, notify=scanningChanged)
    line = QtProperty(str, _get_line, notify=changed)
    countText = QtProperty(str, _get_count_text, notify=changed)
    emptyText = QtProperty(str, _get_empty_text, notify=changed)  # what the Songs list says


class Player(QObject):
    """The song playing, as QML sees it: its path under the root, whether it plays or is paused,
    where it is and how long it is, and why the last one couldn't play. The engine does the work
    on the playback thread (player.py); the two hear each other only by queued signals, so
    nothing here waits on it. The thread starts with the first song."""

    changed = Signal()  # the path, playing, paused, the length, the error
    positionChanged = Signal()
    nowPlaying = Signal(str)  # the path of the song playing now, "" when none
    _play = Signal(str)
    _pause = Signal()
    _resume = Signal()
    _stop = Signal()

    def __init__(
        self, root: str, engine: Engine | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._engine = engine if engine is not None else Engine()
        self._thread = PlaybackThread(self._engine)
        self._started = False
        self._path = ""
        self._paused = False
        self._position = self._length = 0.0
        self._error = ""
        self.last = ""  # how the last song stopped: "ended", "stopped" or "failed"
        self._play.connect(self._engine.play)
        self._pause.connect(self._engine.pause)
        self._resume.connect(self._engine.resume)
        self._stop.connect(self._engine.stop)
        self._engine.began.connect(self._on_began)
        self._engine.moved.connect(self._on_moved)
        self._engine.pausedChanged.connect(self._on_paused)
        self._engine.ended.connect(self._on_ended)
        self._engine.stopped.connect(self._on_stopped)
        self._engine.failed.connect(self._on_failed)

    def _under_root(self, path: str) -> str:
        return os.path.relpath(path, self._root).replace(os.sep, "/")

    # ---------- what QML asks ----------

    @Slot(str)
    def play(self, path: str) -> None:
        """Plays the song at `path` under the root (the index's path) from its start (R7.1)."""
        if not self._started:
            self._thread.start()
            self._started = True
        self._play.emit(os.path.join(self._root, *path.split("/")))

    @Slot()
    def pause(self) -> None:
        self._pause.emit()

    @Slot()
    def resume(self) -> None:
        self._resume.emit()

    @Slot()
    def stop(self) -> None:
        self._stop.emit()

    def close(self) -> None:
        """Stops the song and ends the playback thread: for closing."""
        self._thread.close()

    # ---------- what the engine says ----------

    @Slot(str, float)
    def _on_began(self, path: str, length: float) -> None:
        self._path, self._paused, self._error = self._under_root(path), False, ""
        self._length, self._position = max(0.0, length), 0.0
        self.changed.emit()
        self.positionChanged.emit()
        self.nowPlaying.emit(self._path)

    @Slot(float)
    def _on_moved(self, seconds: float) -> None:
        self._position = seconds
        self.positionChanged.emit()

    @Slot(bool)
    def _on_paused(self, paused: bool) -> None:
        self._paused = paused
        self.changed.emit()

    def _done(self, how: str, error: str = "") -> None:
        self.last, self._error = how, error
        self._path, self._paused = "", False
        self._position = self._length = 0.0
        self.changed.emit()
        self.positionChanged.emit()
        self.nowPlaying.emit("")

    @Slot(str)
    def _on_ended(self, path: str) -> None:
        self._done("ended")

    @Slot(str)
    def _on_stopped(self, path: str) -> None:
        self._done("stopped")

    @Slot(str, str)
    def _on_failed(self, path: str, why: str) -> None:
        self._done("failed", why)

    # ---------- what QML reads ----------

    def _get_path(self) -> str:
        return self._path

    def _get_playing(self) -> bool:
        return bool(self._path) and not self._paused

    def _get_paused(self) -> bool:
        return self._paused

    def _get_position(self) -> float:
        return self._position

    def _get_length(self) -> float:
        return self._length

    def _get_error(self) -> str:
        return self._error

    path = QtProperty(str, _get_path, notify=changed)  # the song's path under the root; "": none
    playing = QtProperty(bool, _get_playing, notify=changed)  # a song plays, not paused
    paused = QtProperty(bool, _get_paused, notify=changed)
    position = QtProperty(float, _get_position, notify=positionChanged)  # seconds
    length = QtProperty(float, _get_length, notify=changed)  # seconds; 0 when unknown
    error = QtProperty(str, _get_error, notify=changed)  # why the last song couldn't play
