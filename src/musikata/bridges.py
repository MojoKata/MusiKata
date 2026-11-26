"""The objects QML sees (A1.2). `Library`: the root, its card's line, the Songs list, and the scan,
run on a thread of its own with the worker processes reading the files (A1.3, A2.2). `Player` comes
with playback (A4).

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
