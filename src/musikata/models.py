"""The list models the QML views bind to (A1.5): rows paged from the index as they scroll into
view, so QML never holds the whole library; sorting and filtering are SQL, not proxy models.

A list's rows are found off the GUI thread (A1.3): a model sends its query, with its search (R2.7)
when one filters it, to the search thread (`Searcher`), which finds the ids of its rows in the
list's order, and the model takes them when they come back, by a signal queued to the GUI thread,
dropping what a newer search or reload has made stale. Its pages are then read by id, each a
lookup of 200 rows by their keys whatever the order, so typing never waits on a query, and
scrolling, however deep, never sorts the list again: a page is a few milliseconds at any depth.

What a row shows is decided here, as text (`docs/process/coding.md`: QML only lays out and binds):
the title, or the file's name when the song has none; the genres joined; the plays of every
computer added up (R7.9); the length as m:ss; an album's artist and year as one line; a cover as the
address the cover provider serves it at; and whether it is the song or album playing."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable, Mapping, Sequence
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
    Slot,
)

from musikata_core import albums, folders, search

from .selection import NOT_MINE, Selection, selection_text

log = logging.getLogger(__name__)

PAGE = 200  # rows read at a time
SHORT = 2000  # rows a list without a search may have to be found at once, not on the search thread
KEEP = 16  # pages held; the one read longest ago goes first
COVERS = "image://covers/"  # where the cover provider serves a thumbnail, by its name (covers.py)
UNKNOWN_ARTIST = "Unknown artist"

# what a row of a list of songs holds, in the roles' order
COLUMNS = ("title", "artist", "album", "genre", "year", "track", "rating", "plays", "time", "path")
ROLES = {int(Qt.ItemDataRole.UserRole) + i: name for i, name in enumerate(COLUMNS)}
PLAYING = int(Qt.ItemDataRole.UserRole) + len(COLUMNS)  # the role: whether it's the song playing

# the Songs list's orders (R2.6), one for each column it sorts by: what it sorts by, how text is
# compared, and what orders songs that tie. A missing value sorts last either way. By artist is
# by album artist, then album, disc and track, so an album's songs stay together, by their sort
# names (R2.13); so are the ties of genre, year, rating, plays and time.
BY_ARTIST = (
    "artist_key IS NULL, artist_key, album_key IS NULL, album_key, album_id, disc, track, path"
)
NOCASE = " COLLATE NOCASE"
COLUMN_SORTS: dict[str, tuple[str, str, str]] = {
    "title": ("title", NOCASE, "path"),
    "artist": ("artist_key", "", "album_key IS NULL, album_key, album_id, disc, track, path"),
    "album": ("album_key", "", "album_id, disc, track, path"),
    "genre": ("(SELECT genre FROM song_genre WHERE song_id = song.id AND position = 0)", NOCASE,
              BY_ARTIST),
    "year": ("year", "", BY_ARTIST),
    "rating": ("coalesce(rating, 0)", "", BY_ARTIST),
    "plays": ("coalesce((SELECT SUM(count) FROM play WHERE song_id = song.id), 0)", "", BY_ARTIST),
    "time": ("length", "", BY_ARTIST),
}  # fmt: skip
# the orders of the pages' lists: an album's by disc and track, an artist's other songs by album
ORDERS = {
    "tracks": albums.ALBUM_ORDER,
    "others": "album_key IS NULL, album_key, disc, track, path",
}
# the Songs list's columns as its header shows them, and the order each sorts by ("": none)
SONG_HEADERS = (
    ("#", ""), ("TITLE", "title"), ("ARTIST", "artist"), ("ALBUM", "album"), ("GENRE", "genre"),
    ("YEAR", "year"), ("RATING", "rating"), ("PLAYS", "plays"), ("TIME", "time"),
)  # fmt: skip


def song_order(sort: str, descending: bool = False) -> str:
    """The ORDER BY of a list of songs: one of ORDERS, or a column of COLUMN_SORTS either way."""
    if sort in ORDERS:
        return ORDERS[sort]
    if sort not in COLUMN_SORTS:
        raise ValueError(f"no such order: {sort}")
    value, collate, ties = COLUMN_SORTS[sort]
    return f"{value} IS NULL, {value}{collate} {'DESC' if descending else 'ASC'}, {ties}"


def song_headers(sort: str, descending: bool) -> list[dict[str, str]]:
    """The Songs list's column headers (R2.6): each its label, the order a click on it asks for
    ("" for one that doesn't sort) and which way it sorts now ("up", "down", "" when it doesn't)."""
    return [
        {
            "label": label,
            "sort": key,
            "order": ("down" if descending else "up") if key and key == sort else "",
        }
        for label, key in SONG_HEADERS
    ]


# Albums' orders (R2.6, R2.13): by album artist, title or year, each by sort names, as the header's
# sort offers them; the label each has there
ALBUM_SORTS = {
    "artist": "artist_key, title_key, id",
    "title": "title_key, artist_key, id",
    "year": "year IS NULL, year, artist_key, title_key, id",
}
ALBUM_SORT_LABELS = {"artist": "Artist", "title": "Title", "year": "Year"}

# what a list of songs selects, in row_of's order
SONG_COLUMNS = (
    "path, title, artist, album,"
    " (SELECT group_concat(genre, '; ' ORDER BY position) FROM song_genre WHERE song_id = song.id),"
    " year, track, rating, (SELECT SUM(count) FROM play WHERE song_id = song.id), length"
)


# the selection bar's actions after Play next (L03-songs-bulk-edit): Edit tags (R4.2, by its
# `action`), and those that come with later slices, with what their tooltips say
SONG_LATER = [
    {"label": "Add to playlist", "icon": "plus", "later": "Playlists come in a later version"},
    {"label": "Edit tags", "icon": "genre", "later": "", "action": "edit"},
    {
        "label": "Infer from path",
        "icon": "wand",
        "later": "Tags from paths come in a later version",
    },
]

# the keys a list selects with (R6.9, R18.2), by the names selection.press knows them by
KEY_NAMES = {
    int(Qt.Key.Key_Up): "up", int(Qt.Key.Key_Down): "down", int(Qt.Key.Key_PageUp): "pageup",
    int(Qt.Key.Key_PageDown): "pagedown", int(Qt.Key.Key_Home): "home",
    int(Qt.Key.Key_End): "end", int(Qt.Key.Key_Escape): "clear",
}  # fmt: skip
SHIFT = int(Qt.KeyboardModifier.ShiftModifier.value)
CTRL = int(Qt.KeyboardModifier.ControlModifier.value)  # ⌘ on macOS, as Qt maps it
OTHER = int(Qt.KeyboardModifier.AltModifier.value) | int(Qt.KeyboardModifier.MetaModifier.value)


def key_name(key: int, modifiers: int) -> tuple[str, bool]:
    """A key a list was given, as selection.press names it, and whether Shift was held: Ctrl+A
    (⌘A) is "all"; with Ctrl, Alt or Meta otherwise, a key isn't the list's ("": Alt+↑ goes up a
    folder, Ctrl+Shift+↑ moves songs in a playlist, R6.9), nor is one it doesn't know."""
    shift = bool(modifiers & SHIFT)
    if modifiers & OTHER:
        return "", shift
    if modifiers & CTRL:
        return ("all" if key == int(Qt.Key.Key_A) else ""), shift
    return KEY_NAMES.get(key, ""), shift


def size_text(n: int) -> str:
    """Bytes as the root's card gives them: 9.8 GB, 412 MB, 3 KB (powers of 1000, as the systems'
    file managers mostly do)."""
    for unit, size in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= size:
            v = n / size
            return f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}"
    return f"{n} bytes"


KINDS = {
    "mp3": "MP3", "flac": "FLAC", "aac": "AAC", "alac": "ALAC", "vorbis": "Ogg Vorbis",
    "opus": "Opus", "wav": "WAV", "aiff": "AIFF",
}  # fmt: skip
LOSSLESS = {"flac", "alac", "wav", "aiff"}


def format_text(groups: list[tuple[str | None, int | None, int | None, int]]) -> str:
    """An album's format (R2.6) from its songs' (kind, sample rate, bit rate, songs): FLAC 44.1
    kHz; MP3 320 kbps; several kinds, most songs first: FLAC, MP3. Empty when unknown."""
    by_kind: dict[str, list[tuple[int | None, int | None, int]]] = {}
    for kind, rate, bitrate, n in groups:
        if kind:
            by_kind.setdefault(kind, []).append((rate, bitrate, n))
    if not by_kind:
        return ""
    if len(by_kind) > 1:
        order = sorted(by_kind, key=lambda k: (-sum(g[2] for g in by_kind[k]), k))
        return ", ".join(KINDS.get(k, k) for k in order)
    kind, found = next(iter(by_kind.items()))
    name = KINDS.get(kind, kind)
    if kind in LOSSLESS:
        rate = max(found, key=lambda g: g[2])[0]
        return f"{name} {rate / 1000:g} kHz" if rate else name
    songs = sum(g[2] for g in found)
    kbps = round(sum((g[1] or 0) * g[2] for g in found) / songs / 1000)
    return f"{name} {kbps} kbps" if kbps else name


def time_text(seconds: float | None) -> str:
    """A song's length as the lists show it: 4:18, 1:02:05; empty when unknown."""
    if seconds is None or seconds < 0:
        return ""
    s = round(seconds)
    h, rest = divmod(s, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{s // 60}:{s % 60:02d}"


def plays_text(plays: int | None) -> str:
    """A song's plays on every computer, added up (R7.9), as the lists show them: 1,204; empty
    for a song never played."""
    return f"{plays:,}" if plays else ""


def length_text(seconds: float | None) -> str:
    """An album's length as its page gives it: 44 min, 1 h 12 min; under a minute, 1 min."""
    minutes = max(1, round((seconds or 0) / 60))
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def count_text(shown: int, total: int, one: str, searching: bool) -> str:
    """A view's count beside its title (R6.4): 128 albums; while a search filters it (R2.7), what
    it shows of how many: 12 of 1,412 songs."""
    return f"{shown:,} of {plural(total, one)}" if searching else plural(total, one)


def no_match_text(text: str, many: str) -> str:
    """What a list says when a search finds nothing in it (R2.7)."""
    return f"No {many} match \u201c{text.strip()}\u201d"


def title_of(title: str | None, path: str) -> str:
    """The title, or the file's name without its extension when the song has none."""
    return title or os.path.splitext(os.path.basename(path))[0]


def artist_text(name: str | None) -> str:
    return name or UNKNOWN_ARTIST


def cover_url(thumb: str | None) -> str:
    """The address QML shows a cover from, by its thumbnail's name; "" for none (R5.7)."""
    return COVERS + thumb if thumb else ""


def mosaic(n: int) -> list[dict[str, float]]:
    """Where each of n covers (up to four) sits in a mosaic (R5.8's table, folders.layout), as
    fractions of the tile and its gap: x and y place a piece at x * (size + gap), and w and h size
    it at w * (size + gap) - gap, so the pieces meet with the gap between them."""
    return [dict(zip("xywh", r, strict=True)) for r in folders.layout(n)]


def tiles(thumbs: Sequence[str]) -> list[dict[str, Any]]:
    """A mosaic of up to four covers, each piece with its source."""
    return [
        {"source": cover_url(t), **piece}
        for t, piece in zip(thumbs, mosaic(len(thumbs)), strict=False)
    ]


def row_of(r: tuple[Any, ...]) -> dict[str, Any]:
    """A row of SONG_COLUMNS as the roles give it."""
    path, title, artist, album, genre, year, track, rating, plays, length = r
    return {
        "title": title_of(title, path),
        "artist": artist or "",
        "album": album or "",
        "genre": genre or "",
        "year": str(year) if year else "",
        "track": str(track) if track else "",
        "rating": rating or 0,
        "plays": plays_text(plays),
        "time": time_text(length),
        "path": path,
    }


def average_of(total: int | None, rated: int) -> dict[str, object]:
    """The average of an album's or artist's rated songs (R10.1), for its page: its stars,
    rounded half up, and in words ("4.3 average of 9 rated songs"); {} when none is rated."""
    if not rated or not total:
        return {}
    mean = total / rated
    return {
        "stars": max(1, min(5, int(mean + 0.5))),
        "text": f"{mean:.1f} average of {plural(rated, 'rated song')}",
    }


def average_in(c: sqlite3.Connection, where: str, params: tuple[object, ...]) -> dict[str, object]:
    """`average_of` the songs `where` picks."""
    total, rated = c.execute(
        f"SELECT SUM(rating), COUNT(*) FROM song WHERE rating > 0 AND ({where})", params
    ).fetchone()
    return average_of(total, rated)


class Searcher(QObject):
    """The search thread (R2.7, A1.3): runs the newest piece of work each list sent it, on a
    thread of its own with its own reading connection, and hands each result back on the GUI
    thread (None for work that failed, which the log tells of). Work sent while a list's earlier
    work waits replaces it, so typing fast queues nothing; the thread ends when nothing waits, and
    starts again with the next."""

    _found = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._waiting: dict[Hashable, tuple[Callable[[], Any], Callable[[Any], None]]] = {}
        self._thread: threading.Thread | None = None
        self._found.connect(self._deliver)

    def submit(self, key: Hashable, work: Callable[[], Any], then: Callable[[Any], None]) -> None:
        """Runs work() on the search thread, then then(its result) on the GUI thread; replaces
        work sent under the same key that hasn't started."""
        with self._lock:
            self._waiting[key] = (work, then)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="search", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._waiting:
                    self._thread = None
                    return
                work, then = self._waiting.pop(next(iter(self._waiting)))
            try:
                result = work()
            except Exception:  # a search that fails finds nothing, and the log says why
                log.exception("a search failed")
                result = None
            self._found.emit((then, result))

    @Slot(object)
    def _deliver(self, found: tuple[Callable[[Any], None], Any]) -> None:
        then, result = found
        then(result)

    def wait(self) -> None:
        """Until the search thread has ended (its results still to be delivered): for closing."""
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join()


class PagedModel(QAbstractListModel):
    """Rows of a query, a page read when a row of it is first asked for. A subclass gives the
    query (`_query`: the columns it selects, its table, WHERE and parameters, and its order), how a
    row of those columns reads (`_row`), the roles, its table's key, and which of its rows a
    search's songs pick (`_narrow`).

    The ids of its rows in its order, of those a search (R2.7) picks while one filters it, are
    found on the search thread, so no query that sorts the whole list runs on the GUI thread, and
    each page is read by them; `count` is how many it shows and `total` how many there are without
    the search."""

    countChanged = Signal()
    roles: tuple[str, ...] = ()
    key = "id"  # the column a row is found by

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        parent: QObject | None = None,
        searcher: Searcher | None = None,
    ):
        super().__init__(parent)
        self._read = read
        self._count = self._total = 0
        self._pages: OrderedDict[int, list[dict[str, Any] | None]] = OrderedDict()
        self.pages_read = 0  # how many times a page was read: what the paging saves, for tests
        self._searcher = searcher if searcher is not None else Searcher(self)
        self._search = ""
        self._query_of_search = search.Query()
        self._ids: list[int] | None = None  # the rows found, in order; None: none yet
        self._generation = 0  # which reload a search's result belongs to
        self._shown = ""  # the search whose rows the list shows
        self._pending = False  # a search sent to the search thread, its rows still to come
        self._ratings: Mapping[int, int] = {}  # ratings being saved, shown at once (R10.2)

    def _query(self) -> tuple[str, str, str, tuple[Any, ...], str]:
        """The columns selected, the table, the WHERE ("" for none), its parameters, the order."""
        raise NotImplementedError

    def _row(self, r: tuple[Any, ...]) -> dict[str, Any]:
        raise NotImplementedError

    def _narrow(self, songs: str, params: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
        """The WHERE that picks this list's rows from the songs a condition on `song` picks."""
        return songs, params

    def set_search(self, text: str) -> None:
        """Filters the list by what the user typed (R2.7), or shows it whole for a search that
        asks nothing; the rows come when the search thread has found them."""
        self.search_next(text)
        self.reload()

    def search_next(self, text: str) -> None:
        """The search the list's next reading filters by, without reading it now: a page opened
        at another album with its search reads its songs once, not twice."""
        self._search = text
        self._query_of_search = search.parse(text)

    def reload(self) -> None:
        """Reads the list afresh from its start: after a new order, a new search or another
        selection. Its rows, in order, are found on the search thread, and come with
        countChanged."""
        self._generation += 1
        self._find(keep=False)

    def refresh(self) -> None:
        """Reads the rows afresh where they are, after a scan: once the search thread has found
        them, rows added or taken away at the end and every row read again, never a reset, so a
        view keeps its scroll position (A2.4). Until then the rows shown stay."""
        self._generation += 1
        self._find(keep=True)

    def _find(self, keep: bool) -> None:
        """Finds the ids of the list's rows in its order: those its search picks, or every one
        without a search. A search's, and those of a list longer than SHORT, are found on the
        search thread and come with countChanged; a short list's, a matter of a millisecond or two,
        at once, so an album's page or a small folder opens whole."""
        cols, table, where, params, order = self._query()
        if self._query_of_search:
            songs, song_params = search.condition(self._query_of_search)
            narrow, narrow_params = self._narrow(songs, song_params)
            found = f"({where}) AND {narrow}" if where else narrow
            text = self._search
        else:
            found, narrow_params, text = where, (), ""
        read, key, generation = self._read, self.key, self._generation
        source = f"{table} WHERE {where}" if where else table

        def work() -> tuple[int, list[int]]:
            c = read()
            sql = f"SELECT {key} FROM {table}{' WHERE ' + found if found else ''} ORDER BY {order}"
            ids = [r[0] for r in c.execute(sql, (*params, *narrow_params))]
            if not text:
                return len(ids), ids
            total = int(c.execute(f"SELECT COUNT(*) FROM {source}", params).fetchone()[0])
            return total, ids

        if not text:
            count = int(read().execute(f"SELECT COUNT(*) FROM {source}", params).fetchone()[0])
            if count <= SHORT:
                self._found(generation, text, work(), keep)
                return
        self._pending = True
        self._searcher.submit(
            self, work, lambda result: self._found(generation, text, result, keep)
        )

    def _found(
        self, generation: int, text: str, result: tuple[int, list[int]] | None, keep: bool = False
    ) -> None:
        if generation != self._generation:
            return  # a newer search or reload has been asked for since
        if keep and text == self._shown and result is not None:  # the same search, found again
            self._resize(len(result[1]), result[0], result[1], text)
            return
        self.beginResetModel()
        self._pages.clear()
        self._total, self._ids = result if result is not None else (self._total, [])
        self._count = len(self._ids)
        self._shown, self._pending = text, False
        self._rows_found()
        self.endResetModel()
        self.countChanged.emit()

    def _resize(self, count: int, total: int, ids: list[int] | None, shown: str) -> None:
        """The rows now `count`, without a reset: those past the old count added, or those past
        the new one taken away, and every row read again."""
        old = self._count
        self._pages.clear()
        self._total, self._ids, self._shown, self._pending = total, ids, shown, False
        self._rows_found()
        if count > old:
            self.beginInsertRows(QModelIndex(), old, count - 1)
            self._count = count
            self.endInsertRows()
        elif count < old:
            self.beginRemoveRows(QModelIndex(), count, old - 1)
            self._count = count
            self.endRemoveRows()
        if count:
            self.dataChanged.emit(self.index(0), self.index(count - 1))
        self.countChanged.emit()

    def _rows_found(self) -> None:
        """The rows were found afresh (`_ids`), before the view hears of it."""

    def row(self, n: int) -> dict[str, Any] | None:
        """Row n, reading its page when it isn't held."""
        if not 0 <= n < self._count:
            return None
        p = n // PAGE
        page = self._pages.get(p)
        if page is None:
            page = self._read_page(p)
            self.pages_read += 1
            self._pages[p] = page
            while len(self._pages) > KEEP:
                self._pages.popitem(last=False)
        else:
            self._pages.move_to_end(p)
        i = n % PAGE
        return page[i] if i < len(page) else None

    def _read_page(self, p: int) -> list[dict[str, Any] | None]:
        """Page p of the rows found (`_find`), each looked up by its key, whatever the order: a
        few milliseconds at any depth."""
        cols, table, _where, _params, _order = self._query()
        ids = (self._ids or [])[p * PAGE : (p + 1) * PAGE]
        marks = ", ".join("?" * len(ids))
        sql = f"SELECT {self.key}, {cols} FROM {table} WHERE {self.key} IN ({marks})"
        rows = {r[0]: self._row(r[1:]) for r in self._read().execute(sql, ids)}
        return [rows.get(i) for i in ids]  # None for a row gone since they were found

    def song_at(self, n: int) -> int | None:
        """The song row n stands for, by id; None for a row of no one song (a folder)."""
        return None

    def rating_at(self, n: int) -> int:
        """Row n's rating as the list shows it, one being saved included (R10.2); 0 for none."""
        song = self.song_at(n)
        if song is not None and song in self._ratings:
            return self._ratings[song]
        row = self.row(n)
        return int(row.get("rating") or 0) if row is not None else 0

    def show_ratings(self, ratings: Mapping[int, int]) -> None:
        """The ratings being saved, by song id, shown at once in place of the index's until
        they are saved (R10.2: the list shows a new rating at once, and goes back when it
        fails)."""
        if not ratings and not self._ratings:
            return
        self._ratings = dict(ratings)
        if "rating" in self.roles:
            self._changed("rating")

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
        if self._ratings and self.roles[i] == "rating":
            song = self.song_at(index.row())
            if song is not None and song in self._ratings:
                return self._ratings[song]
        row = self.row(index.row())
        return None if row is None else self._value(row, self.roles[i])

    def _get_count(self) -> int:
        return self._count

    def total(self) -> int:
        """How many rows the list has without its search."""
        return self._total

    def searching(self) -> bool:
        """Whether a search filters the list, or will once its rows come."""
        return bool(self._query_of_search)

    def filtered(self) -> bool:
        """Whether the rows the list shows are a search's."""
        return bool(self._shown)

    def shown_search(self) -> str:
        """The search whose rows the list shows ("" when it shows them all)."""
        return self._shown

    def pending(self) -> bool:
        """Whether the rows found are still to come (`_find`)."""
        return self._pending

    def wait(self) -> None:
        """Until the search thread has ended: for closing."""
        self._searcher.wait()

    count = QtProperty(int, _get_count, notify=countChanged)


class SongsModel(PagedModel):
    """Songs of the index: every one (the Songs list), or those a WHERE picks (an album's, an
    artist's on others' albums), in one of ORDERS, or by a column either way (COLUMN_SORTS).

    It holds the list's selection (R2.6), by song id (selection.Selection), so it stays with its
    songs however the list is scrolled, paged, sorted or read again after a scan, and a song that
    leaves the list leaves it; each row says whether it is selected and whether it is the current
    row the arrow keys move. `selection` is the songs selected, in the list's order: what Enter
    plays (R7.1), the right-click menu queues (R7.2) and the Edit tags panel and ratings act on
    (R4.2, R10)."""

    roles = (*COLUMNS, "playing", "selected", "current")
    key = "song.id"
    selectionChanged = Signal()
    revealRow = Signal(int)  # a selection the tour made: its first row, for the view to show

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        sort: str = "artist",
        parent: QObject | None = None,
        where: str = "",
        params: tuple[Any, ...] = (),
        searcher: Searcher | None = None,
    ) -> None:
        super().__init__(read, parent, searcher)
        song_order(sort)  # one that exists
        self._sort, self._descending = sort, False
        self._where, self._params = where, params
        self._playing = ""  # the path of the song playing
        self._selection: Selection[int] = Selection()
        self._wanted: list[int] | None = None  # songs to select once the rows come (select_songs)
        self.source = ""  # the list's name, where the queue says it plays from (R7.2)

    def _query(self) -> tuple[str, str, str, tuple[Any, ...], str]:
        order = song_order(self._sort, self._descending)
        return SONG_COLUMNS, "song", self._where, self._params, order

    def _row(self, r: tuple[Any, ...]) -> dict[str, Any]:
        return row_of(r)

    def _value(self, row: dict[str, Any], name: str) -> Any:
        return row["path"] == self._playing if name == "playing" else row[name]

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        i = role - int(Qt.ItemDataRole.UserRole)
        if 0 <= i < len(self.roles) and self.roles[i] in ("selected", "current"):
            song = self._id_at(index.row())
            if song is None:
                return None
            if self.roles[i] == "selected":
                return song in self._selection
            return song == self._selection.current
        return super().data(index, role)

    def _id_at(self, row: int) -> int | None:
        ids = self._ids or []
        return ids[row] if 0 <= row < min(self._count, len(ids)) else None

    def song_at(self, n: int) -> int | None:
        return self._id_at(n)

    def select(self, where: str, params: tuple[Any, ...]) -> None:
        """Lists the songs `where` picks instead, and reads them."""
        self._where, self._params = where, params
        self.reload()

    def sort_by(self, sort: str, descending: bool = False) -> None:
        """Lists the songs in another order: one of ORDERS, or a column's either way."""
        song_order(sort, descending)
        self._sort, self._descending = sort, descending
        self.reload()

    def order(self) -> tuple[str, bool]:
        """The order the songs are in: its name, and whether it runs the other way."""
        return self._sort, self._descending

    def set_playing(self, path: str) -> None:
        """Marks the song at `path` as the one playing ("": none), for the rows that show it."""
        if path != self._playing:
            self._playing = path
            self._changed("playing")

    def queue_from(self, row: int) -> tuple[list[int], str]:
        """Row `row`'s song and the rest of the list after it, in the list's order, as a search
        leaves it (R7.1), and the list's name; none past the rows."""
        ids = self._ids or []
        return (ids[row:] if 0 <= row < self._count else []), self.source

    def songs_at(self, row: int) -> list[int]:
        """The songs a right click on row `row` stands for (R7.2): the whole selection, in the
        list's order, when the row is in it; the row's song alone when it isn't."""
        song = self._id_at(row)
        if song is None:
            return []
        return self.selected_songs() if song in self._selection else [song]

    # ---------- the selection (R2.6) ----------

    def selected_songs(self) -> list[int]:
        """The songs selected, by id, in the list's order."""
        return self._selection.chosen(self._ids or [])

    def queue_from_selection(self) -> tuple[list[int], str]:
        """What Enter on the selection plays (R7.1, R6.9): its first song in the list's order, and
        the rest of the list after it, so every song selected plays, in the list's order; none
        when nothing is selected."""
        first = self._selection.first(self._ids or [])
        return self.queue_from(first) if first >= 0 else ([], self.source)

    def select_songs(self, songs: Sequence[int]) -> None:
        """Exactly those of `songs` in the list selected, as the tour shows a selection: once
        its rows have come, when a search's are still to come."""
        if self._pending:
            self._wanted = list(songs)
            return
        self._selection.select(self._ids or [], songs)
        self._selection_changed()
        self.revealRow.emit(self._selection.first(self._ids or []))

    def _rows_found(self) -> None:
        if self._wanted is not None:
            self._selection.select(self._ids or [], self._wanted)
            self._wanted = None
            self.selectionChanged.emit()
            self.revealRow.emit(self._selection.first(self._ids or []))
        elif self._selection.keep(self._ids or []):
            self.selectionChanged.emit()

    def _selection_changed(self) -> None:
        self._changed("selected")
        self._changed("current")
        self.selectionChanged.emit()

    @Slot(int, bool, bool)
    def click(self, row: int, ctrl: bool, shift: bool) -> None:
        """A click on row `row`: it alone selected; with Ctrl (⌘) it added or taken away; with
        Shift the rows from the anchor to it."""
        if self._selection.click(self._ids or [], row, ctrl, shift):
            self._selection_changed()

    @Slot(int)
    def toggle(self, row: int) -> None:
        """Row `row`'s checkbox: it added to the selection or taken away."""
        if self._selection.toggle(self._ids or [], row):
            self._selection_changed()

    @Slot(int, int, int, result=int)
    def press(self, key: int, modifiers: int, page: int) -> int:
        """A key pressed while the list has the focus (R6.9, R18.2), as Qt gives it: ↑ and ↓,
        Page Up and Page Down (`page` rows), Home and End move the current row, selecting it, and
        with Shift the range from the anchor; Ctrl+A (⌘A) selects the whole list; Esc clears the
        selection. Returns the row to bring into view, -1 for none, or selection.NOT_MINE for a
        key the list doesn't use, which goes on to the window."""
        name, shift = key_name(key, modifiers)
        row = self._selection.press(self._ids or [], name, shift, page)
        if row != NOT_MINE:
            self._selection_changed()
        return row

    @Slot()
    def selectAll(self) -> None:  # noqa: N802
        self._selection.select_all(self._ids or [])
        self._selection_changed()

    @Slot()
    def toggleAll(self) -> None:  # noqa: N802
        """The header's checkbox: every song selected when none is, none when any is."""
        self._selection.toggle_all(self._ids or [])
        self._selection_changed()

    @Slot()
    def clearSelection(self) -> None:  # noqa: N802
        self._selection.clear()
        self._selection_changed()

    def _get_selection(self) -> list[int]:
        return self.selected_songs()

    def _get_selection_count(self) -> int:
        return len(self._selection)

    def _get_selection_text(self) -> str:
        return selection_text(len(self._selection))

    def _get_selection_state(self) -> str:
        return self._selection.state(self._ids or [])

    selection = QtProperty(list, _get_selection, notify=selectionChanged)  # ids, in list order
    selectionCount = QtProperty(int, _get_selection_count, notify=selectionChanged)
    selectionText = QtProperty(str, _get_selection_text, notify=selectionChanged)  # 4 selected
    selectionState = QtProperty(str, _get_selection_state, notify=selectionChanged)  # the header's
    laterActions = QtProperty(list, lambda self: SONG_LATER, constant=True)


# the albums with a song of a genre (R9.1's page), its parameter the genre
GENRE_ALBUMS = (
    "id IN (SELECT song.album_id FROM song_genre JOIN song ON song.id = song_genre.song_id"
    " WHERE song_genre.genre = ?)"
)


class AlbumsModel(PagedModel):
    """Albums (R2.6): every one by album artist and title, by their sort names (R2.13), or those
    whose genre is one (Albums' chips); or one artist's, by year; or those with a song of a genre
    (a genre's page, R9.1), by album artist and title. Each row: its id (albumId), title, artist,
    year, the line under its cover ("Lumen Drift · 2019"), genre, songs, length and cover, and
    whether it is playing."""

    roles = (
        "albumId", "title", "artist", "year", "line", "genre", "songs", "time", "cover", "playing"
    )  # fmt: skip

    key = "album.id"

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        parent: QObject | None = None,
        artist_id: int | None = None,
        searcher: Searcher | None = None,
    ) -> None:
        super().__init__(read, parent, searcher)
        self._artist_id = artist_id
        self._genre = ""
        self._of_genre: str | None = None  # a genre's page's: the genre of their songs
        self._sort = "artist"
        self._playing = -1  # the id of the album playing

    def _query(self) -> tuple[str, str, str, tuple[Any, ...], str]:
        cols = "id, title, artist, year, genre, songs, length, thumb"
        if self._artist_id is not None:
            return (
                cols,
                "album",
                "artist_id = ?",
                (self._artist_id,),
                "year IS NULL, year, title_key, id",
            )
        order = ALBUM_SORTS[self._sort]
        if self._of_genre is not None:
            return cols, "album", GENRE_ALBUMS, (self._of_genre,), ALBUM_SORTS["artist"]
        if self._genre:
            return cols, "album", "genre = ?", (self._genre,), order
        return cols, "album", "", (), order

    def _narrow(self, songs: str, params: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
        """An album a song the search finds is on (R2.7)."""
        return f"album.id IN (SELECT song.album_id FROM song WHERE {songs})", params

    def sort_by(self, sort: str) -> None:
        """Lists the albums by album artist, title or year (ALBUM_SORTS)."""
        if sort not in ALBUM_SORTS:
            raise ValueError(f"no such order: {sort}")
        self._sort = sort
        self.reload()

    def order(self) -> str:
        return self._sort

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

    def for_genre(self, genre: str) -> None:
        """Lists the albums with a song of `genre` instead (a genre's page, R9.1), and reads
        them."""
        self._of_genre = genre
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
    key = "artist.id"

    def _query(self) -> tuple[str, str, str, tuple[Any, ...], str]:
        cols = f"id, name, albums, songs, {artist_thumbs('artist.id')}"
        return cols, "artist", "", (), "sort_key, id"

    def _narrow(self, songs: str, params: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
        """An artist of a song the search finds, or of the album it is on (R2.5.4, R2.7)."""
        return (
            f"artist.id IN (SELECT song.artist_id FROM song WHERE {songs}"
            " UNION SELECT album.artist_id FROM song JOIN album ON album.id = song.album_id"
            f" WHERE {songs})",
            (*params, *params),
        )

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
