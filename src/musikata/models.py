"""The list models the QML views bind to (A1.5): rows paged from the index as they scroll into
view, so QML never holds the whole library; sorting is SQL, not a proxy model.

What a row shows is decided here, as text (`docs/process/coding.md`: QML only lays out and binds):
the title, or the file's name when the song has none; the genres joined; the length as m:ss."""

from __future__ import annotations

import os
import sqlite3
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)

PAGE = 200  # rows read at a time
KEEP = 16  # pages held; the one read longest ago goes first

# what a row of the Songs list holds, in the roles' order
COLUMNS = ("title", "artist", "album", "genre", "year", "track", "rating", "time", "path")
ROLES = {int(Qt.ItemDataRole.UserRole) + i: name for i, name in enumerate(COLUMNS)}

# the Songs list's orders (R2.6): by album artist, then album, disc and track, so an album's songs
# stay together; by title. A missing value sorts last, and case doesn't count.
SORTS = {
    "artist": (
        "coalesce(albumartistsort, albumartist, artistsort, artist) IS NULL,"
        " coalesce(albumartistsort, albumartist, artistsort, artist) COLLATE NOCASE,"
        " coalesce(albumsort, album) IS NULL, coalesce(albumsort, album) COLLATE NOCASE,"
        " disc, track, path"
    ),
    "title": "title IS NULL, title COLLATE NOCASE, path",
}

SELECT = (
    "SELECT path, title, artist, album,"
    " (SELECT group_concat(genre, '; ' ORDER BY position) FROM song_genre WHERE song_id = song.id),"
    " year, track, rating, length FROM song ORDER BY {order} LIMIT ? OFFSET ?"
)


def time_text(seconds: float | None) -> str:
    """A song's length as the lists show it: 4:18, 1:02:05; empty when unknown."""
    if seconds is None or seconds < 0:
        return ""
    s = round(seconds)
    h, rest = divmod(s, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{s // 60}:{s % 60:02d}"


def title_of(title: str | None, path: str) -> str:
    """The title, or the file's name without its extension when the song has none."""
    return title or os.path.splitext(os.path.basename(path))[0]


def row_of(r: tuple[Any, ...]) -> dict[str, Any]:
    """A row of SELECT as the roles give it."""
    path, title, artist, album, genre, year, track, rating, length = r
    return {
        "title": title_of(title, path),
        "artist": artist or "",
        "album": album or "",
        "genre": genre or "",
        "year": str(year) if year else "",
        "track": str(track) if track else "",
        "rating": rating or 0,
        "time": time_text(length),
        "path": path,
    }


class SongsModel(QAbstractListModel):
    """Every song of the index, a page of rows read when a row of it is first asked for."""

    countChanged = Signal()

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        sort: str = "artist",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._read = read
        self._sort = sort
        self._count = 0
        self._pages: OrderedDict[int, list[dict[str, Any]]] = OrderedDict()
        self.pages_read = 0  # how many times a page was read: what the paging saves, for tests

    def reload(self) -> None:
        """Reads the count afresh and drops the pages held: after a scan, or a new order."""
        self.beginResetModel()
        self._pages.clear()
        self._count = int(self._read().execute("SELECT COUNT(*) FROM song").fetchone()[0])
        self.endResetModel()
        self.countChanged.emit()

    def sort_by(self, sort: str) -> None:
        if sort not in SORTS:
            raise ValueError(f"no such order: {sort}")
        self._sort = sort
        self.reload()

    def row(self, n: int) -> dict[str, Any] | None:
        """Row n, reading its page when it isn't held."""
        if not 0 <= n < self._count:
            return None
        p = n // PAGE
        page = self._pages.get(p)
        if page is None:
            sql = SELECT.format(order=SORTS[self._sort])
            page = [row_of(r) for r in self._read().execute(sql, (PAGE, p * PAGE))]
            self.pages_read += 1
            self._pages[p] = page
            while len(self._pages) > KEEP:
                self._pages.popitem(last=False)
        else:
            self._pages.move_to_end(p)
        i = n % PAGE
        return page[i] if i < len(page) else None

    # ---------- QAbstractListModel ----------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else self._count

    def roleNames(self) -> dict[int, QByteArray]:
        return {k: QByteArray(v.encode()) for k, v in ROLES.items()}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        name = ROLES.get(role)
        row = self.row(index.row()) if name else None
        return None if row is None or name is None else row[name]

    def _get_count(self) -> int:
        return self._count

    count = QtProperty(int, _get_count, notify=countChanged)
