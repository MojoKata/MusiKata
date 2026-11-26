"""The list models the QML views bind to (A1.5): rows paged from the index as they scroll into
view, so QML never holds the whole library; sorting and filtering are SQL, not proxy models.

What a row shows is decided here, as text (`docs/process/coding.md`: QML only lays out and binds):
the title, or the file's name when the song has none; the genres joined; the length as m:ss; an
album's artist and year as one line; a cover as the address the cover provider serves it at; and
whether it is the song or album playing."""

from __future__ import annotations

import os
import sqlite3
from collections import OrderedDict
from collections.abc import Callable, Sequence
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

from musikata_core import albums

PAGE = 200  # rows read at a time
KEEP = 16  # pages held; the one read longest ago goes first
COVERS = "image://covers/"  # where the cover provider serves a thumbnail, by its name (covers.py)
UNKNOWN_ARTIST = "Unknown artist"

# what a row of a list of songs holds, in the roles' order
COLUMNS = ("title", "artist", "album", "genre", "year", "track", "rating", "time", "path")
ROLES = {int(Qt.ItemDataRole.UserRole) + i: name for i, name in enumerate(COLUMNS)}
PLAYING = int(Qt.ItemDataRole.UserRole) + len(COLUMNS)  # the role: whether it's the song playing

# the orders of a list of songs: the Songs list's (R2.6) by album artist, then album, disc and
# track, so an album's songs stay together, by their sort names (R2.13); by title; an album's page
# by disc and track; an artist's other songs by album. A missing value sorts last.
SORTS = {
    "artist": ("artist_key IS NULL, artist_key, album_key IS NULL, album_key, disc, track, path"),
    "title": "title IS NULL, title COLLATE NOCASE, path",
    "album": albums.ALBUM_ORDER,
    "others": "album_key IS NULL, album_key, disc, track, path",
}

# what a list of songs selects, in row_of's order
SONG_COLUMNS = (
    "path, title, artist, album,"
    " (SELECT group_concat(genre, '; ' ORDER BY position) FROM song_genre WHERE song_id = song.id),"
    " year, track, rating, length"
)


def time_text(seconds: float | None) -> str:
    """A song's length as the lists show it: 4:18, 1:02:05; empty when unknown."""
    if seconds is None or seconds < 0:
        return ""
    s = round(seconds)
    h, rest = divmod(s, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{s // 60}:{s % 60:02d}"


def length_text(seconds: float | None) -> str:
    """An album's length as its page gives it: 44 min, 1 h 12 min; under a minute, 1 min."""
    minutes = max(1, round((seconds or 0) / 60))
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def title_of(title: str | None, path: str) -> str:
    """The title, or the file's name without its extension when the song has none."""
    return title or os.path.splitext(os.path.basename(path))[0]


def artist_text(name: str | None) -> str:
    return name or UNKNOWN_ARTIST


def cover_url(thumb: str | None) -> str:
    """The address QML shows a cover from, by its thumbnail's name; "" for none (R5.7)."""
    return COVERS + thumb if thumb else ""


def mosaic(n: int) -> list[dict[str, float]]:
    """Where each of n covers (up to four) sits in a mosaic (R5.8's table), as fractions of the
    tile and its gap: x and y place a piece at x * (size + gap), and w and h size it at
    w * (size + gap) - gap, so the pieces meet with the gap between them."""
    layouts: dict[int, list[tuple[float, float, float, float]]] = {
        0: [],
        1: [(0, 0, 1, 1)],
        2: [(0, 0, 0.5, 1), (0.5, 0, 0.5, 1)],
        3: [(0, 0, 0.5, 1), (0.5, 0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)],
        4: [(0, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5), (0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)],
    }
    return [dict(zip("xywh", r, strict=True)) for r in layouts[min(max(n, 0), 4)]]


def tiles(thumbs: Sequence[str]) -> list[dict[str, Any]]:
    """A mosaic of up to four covers, each piece with its source."""
    return [
        {"source": cover_url(t), **piece}
        for t, piece in zip(thumbs, mosaic(len(thumbs)), strict=False)
    ]


def row_of(r: tuple[Any, ...]) -> dict[str, Any]:
    """A row of SONG_COLUMNS as the roles give it."""
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


class PagedModel(QAbstractListModel):
    """Rows of a query, a page read when a row of it is first asked for. A subclass gives the
    query (`_query`: its FROM and WHERE, its parameters and its order), the columns it selects
    and how a row of them reads (`_row`), and the roles."""

    countChanged = Signal()
    roles: tuple[str, ...] = ()

    def __init__(self, read: Callable[[], sqlite3.Connection], parent: QObject | None = None):
        super().__init__(parent)
        self._read = read
        self._count = 0
        self._pages: OrderedDict[int, list[dict[str, Any]]] = OrderedDict()
        self.pages_read = 0  # how many times a page was read: what the paging saves, for tests

    def _query(self) -> tuple[str, str, tuple[Any, ...], str]:
        """The columns selected, the FROM (and WHERE), its parameters and the order."""
        raise NotImplementedError

    def _row(self, r: tuple[Any, ...]) -> dict[str, Any]:
        raise NotImplementedError

    def reload(self) -> None:
        """Reads the count afresh and drops the pages held: after a scan, or a new order."""
        self.beginResetModel()
        self._pages.clear()
        _cols, source, params, _order = self._query()
        self._count = int(
            self._read().execute(f"SELECT COUNT(*) FROM {source}", params).fetchone()[0]
        )
        self.endResetModel()
        self.countChanged.emit()

    def row(self, n: int) -> dict[str, Any] | None:
        """Row n, reading its page when it isn't held."""
        if not 0 <= n < self._count:
            return None
        p = n // PAGE
        page = self._pages.get(p)
        if page is None:
            cols, source, params, order = self._query()
            sql = f"SELECT {cols} FROM {source} ORDER BY {order} LIMIT ? OFFSET ?"
            page = [self._row(r) for r in self._read().execute(sql, (*params, PAGE, p * PAGE))]
            self.pages_read += 1
            self._pages[p] = page
            while len(self._pages) > KEEP:
                self._pages.popitem(last=False)
        else:
            self._pages.move_to_end(p)
        i = n % PAGE
        return page[i] if i < len(page) else None

    def _changed(self, role: str) -> None:
        if self._count:
            self.dataChanged.emit(self.index(0), self.index(self._count - 1), [self._role(role)])

    def _role(self, name: str) -> int:
        return int(Qt.ItemDataRole.UserRole) + self.roles.index(name)

    def _value(self, row: dict[str, Any], name: str) -> Any:
        return row[name]

    # ---------- QAbstractListModel ----------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else self._count

    def roleNames(self) -> dict[int, QByteArray]:
        return {self._role(n): QByteArray(n.encode()) for n in self.roles}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        i = role - int(Qt.ItemDataRole.UserRole)
        if not 0 <= i < len(self.roles):
            return None
        row = self.row(index.row())
        return None if row is None else self._value(row, self.roles[i])

    def _get_count(self) -> int:
        return self._count

    count = QtProperty(int, _get_count, notify=countChanged)


class SongsModel(PagedModel):
    """Songs of the index: every one (the Songs list), or those a WHERE picks (an album's, an
    artist's on others' albums), in one of SORTS' orders."""

    roles = (*COLUMNS, "playing")

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        sort: str = "artist",
        parent: QObject | None = None,
        where: str = "",
        params: tuple[Any, ...] = (),
    ) -> None:
        super().__init__(read, parent)
        self._sort = sort
        self._where, self._params = where, params
        self._playing = ""  # the path of the song playing

    def _query(self) -> tuple[str, str, tuple[Any, ...], str]:
        source = "song" + (f" WHERE {self._where}" if self._where else "")
        return SONG_COLUMNS, source, self._params, SORTS[self._sort]

    def _row(self, r: tuple[Any, ...]) -> dict[str, Any]:
        return row_of(r)

    def _value(self, row: dict[str, Any], name: str) -> Any:
        return row["path"] == self._playing if name == "playing" else row[name]

    def select(self, where: str, params: tuple[Any, ...]) -> None:
        """Lists the songs `where` picks instead, and reads them."""
        self._where, self._params = where, params
        self.reload()

    def sort_by(self, sort: str) -> None:
        if sort not in SORTS:
            raise ValueError(f"no such order: {sort}")
        self._sort = sort
        self.reload()

    def set_playing(self, path: str) -> None:
        """Marks the song at `path` as the one playing ("": none), for the rows that show it."""
        if path != self._playing:
            self._playing = path
            self._changed("playing")


class AlbumsModel(PagedModel):
    """Albums (R2.6): every one by album artist and title, by their sort names (R2.13), or those
    of one genre; or one artist's, by year. Each row: its id (albumId), title, artist, year, the
    line under its cover ("Lumen Drift · 2019"), genre, songs, length and cover, and whether it is
    playing."""

    roles = (
        "albumId", "title", "artist", "year", "line", "genre", "songs", "time", "cover", "playing"
    )  # fmt: skip

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        parent: QObject | None = None,
        artist_id: int | None = None,
    ) -> None:
        super().__init__(read, parent)
        self._artist_id = artist_id
        self._genre = ""
        self._playing = -1  # the id of the album playing

    def _query(self) -> tuple[str, str, tuple[Any, ...], str]:
        cols = "id, title, artist, year, genre, songs, length, thumb"
        if self._artist_id is not None:
            return (
                cols,
                "album WHERE artist_id = ?",
                (self._artist_id,),
                "year IS NULL, year, title_key, id",
            )
        if self._genre:
            return cols, "album WHERE genre = ?", (self._genre,), "artist_key, title_key, id"
        return cols, "album", (), "artist_key, title_key, id"

    def _row(self, r: tuple[Any, ...]) -> dict[str, Any]:
        album_id, title, artist, year, genre, songs, length, thumb = r
        shown = artist_text(artist)
        return {
            "albumId": album_id,
            "title": title,
            "artist": shown,
            "year": str(year) if year else "",
            "line": f"{shown} · {year}" if year else shown,
            "genre": genre or "",
            "songs": plural(songs, "song"),
            "time": time_text(length),
            "cover": cover_url(thumb),
        }

    def _value(self, row: dict[str, Any], name: str) -> Any:
        return row["albumId"] == self._playing if name == "playing" else row[name]

    def for_artist(self, artist_id: int) -> None:
        """Lists that artist's albums instead, and reads them."""
        self._artist_id = artist_id
        self.reload()

    def filter_genre(self, genre: str) -> None:
        """Only the albums whose genre is `genre` ("": every album)."""
        self._genre = genre
        self.reload()

    def set_playing(self, album_id: int) -> None:
        """Marks the album with that id as playing (-1: none)."""
        if album_id != self._playing:
            self._playing = album_id
            self._changed("playing")


def artist_thumbs(artist: str) -> str:
    """SQL for an artist's mosaic (R2.6): the covers of up to four of their albums, those with the
    most songs first; for an artist with no album of their own (one on compilations), the covers
    of the albums their songs are on. `artist` is the SQL of their id."""
    return (
        "coalesce((SELECT group_concat(thumb, ' ') FROM (SELECT thumb FROM album"
        f" WHERE artist_id = {artist} AND thumb IS NOT NULL ORDER BY songs DESC, id LIMIT 4)),"
        " (SELECT group_concat(thumb, ' ') FROM (SELECT DISTINCT album.thumb FROM song"
        f" JOIN album ON album.id = song.album_id WHERE song.artist_id = {artist}"
        " AND album.thumb IS NOT NULL ORDER BY album.songs DESC, album.id LIMIT 4)))"
    )


class ArtistsModel(PagedModel):
    """Artists (R2.6), by their sort names (R2.13): each row its id (artistId), name, the line
    under it ("3 albums · 41 songs") and its mosaic (artist_thumbs)."""

    roles = ("artistId", "name", "line", "tiles")

    def _query(self) -> tuple[str, str, tuple[Any, ...], str]:
        cols = f"id, name, albums, songs, {artist_thumbs('artist.id')}"
        return cols, "artist", (), "sort_key, id"

    def _row(self, r: tuple[Any, ...]) -> dict[str, Any]:
        artist_id, name, albums, songs, thumbs = r
        return {
            "artistId": artist_id,
            "name": name,
            "line": artist_line(albums, songs),
            "tiles": tiles((thumbs or "").split()),
        }


def artist_line(albums: int, songs: int) -> str:
    """What an artist's tile says under the name: 3 albums · 41 songs; 12 songs with no album."""
    return " · ".join(([plural(albums, "album")] if albums else []) + [plural(songs, "song")])
