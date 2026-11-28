"""The now-playing bar's words and Up next's list (R6.5, R7.2), as QML sees them: a song's row read
from the index by its id (`SongInfo`, `read_songs`), what the bar says of it, and `UpNextModel`,
the panel the bar's queue button opens: the song playing, the songs to come (those the user added
first, then the rest of the list the queue plays from), then the songs played, the latest first.

What every text says is decided here (docs/process/coding.md: QML only lays out and binds); the
queue itself is musikata_core.audio.queue's, and the Player bridge (bridges.py) changes it."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
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

from musikata_core.albums import ALBUM_ORDER
from musikata_core.audio.gain import AlbumPlace, Loudness
from musikata_core.audio.queue import ALL, ONE, Entry, Queue

from .models import artist_text, cover_url, key_name, length_text, time_text, title_of
from .selection import NOT_MINE, Selection

CHUNK = 500  # ids looked up at a time
PAGE = 200  # Up next's rows read at a time
RESTART_AFTER = 3.0  # seconds into a song past which Previous starts it again (R6.5)
SEEK_STEP = 5.0  # seconds ← and → seek (R7.4, R6.9)
EMPTY = "Nothing is queued. Play a song, or add songs with Add to queue."
REPEAT_NAMES = {"off": "Repeat off", ALL: "Repeat all", ONE: "Repeat one"}


@dataclass(frozen=True)
class SongInfo:
    """What the bar and Up next show of a song: its path under the root, title (the file's name
    when it has none), artist, album, length in seconds (None: unknown), rating and cover."""

    path: str
    title: str
    artist: str
    album: str
    length: float | None
    rating: int
    cover: str


def read_songs(c: sqlite3.Connection, ids: Iterable[int]) -> dict[int, SongInfo]:
    """The songs with these ids, by id; one that is gone (a scan took it out) is left out."""
    wanted = list(dict.fromkeys(ids))
    out: dict[int, SongInfo] = {}
    for i in range(0, len(wanted), CHUNK):
        chunk = wanted[i : i + CHUNK]
        marks = ", ".join("?" * len(chunk))
        for song_id, path, title, artist, album, length, rating, thumb in c.execute(
            "SELECT song.id, song.path, song.title, song.artist, song.album, song.length,"
            " song.rating, album.thumb FROM song LEFT JOIN album ON album.id = song.album_id"
            f" WHERE song.id IN ({marks})",
            chunk,
        ):
            out[song_id] = SongInfo(
                path, title_of(title, path), artist or "", album or "", length,
                rating or 0, cover_url(thumb),
            )  # fmt: skip
    return out


def read_loudness(
    c: sqlite3.Connection, ids: Iterable[int]
) -> dict[int, tuple[Loudness, AlbumPlace | None]]:
    """The ReplayGain tags of the songs with these ids, and each one's album and place in its
    order (R7.5), by id; a song gone from the index is left out, one in no album has no place."""
    wanted = list(dict.fromkeys(ids))
    out: dict[int, tuple[Loudness, AlbumPlace | None]] = {}
    marks = ", ".join("?" * len(wanted))
    rows = c.execute(
        "SELECT id, rg_track_gain, rg_track_peak, rg_album_gain, rg_album_peak, album_id"
        f" FROM song WHERE id IN ({marks})",
        wanted,
    ).fetchall()
    places: dict[int, AlbumPlace] = {}
    for album in {r[5] for r in rows if r[5] is not None}:
        order = c.execute(
            f"SELECT id FROM song WHERE album_id = ? ORDER BY {ALBUM_ORDER}", (album,)
        )
        places.update((song, AlbumPlace(album, i)) for i, (song,) in enumerate(order))
    for song, track_gain, track_peak, album_gain, album_peak, _ in rows:
        out[song] = (Loudness(track_gain, track_peak, album_gain, album_peak), places.get(song))
    return out


def song_of_path(c: sqlite3.Connection, path: str) -> int | None:
    """The id of the song at `path` under the root; None when the index has none."""
    r = c.execute("SELECT id FROM song WHERE path = ?", (path,)).fetchone()
    return int(r[0]) if r else None


def bar_line(info: SongInfo) -> str:
    """The line under the title in the bar (L01-albums): Lumen Drift — Glass Harbor; the artist
    alone without an album, and Unknown artist without one."""
    artist = artist_text(info.artist)
    return f"{artist} — {info.album}" if info.album else artist


def row_line(info: SongInfo) -> str:
    """The line under a title in Up next (N03-now-playing-queue): Lumen Drift · Glass Harbor."""
    artist = artist_text(info.artist)
    return f"{artist} · {info.album}" if info.album else artist


def queue_line(source: str, upcoming: int, seconds: float) -> str:
    """Up next's line under its title: where the queue comes from, how many songs are left and
    how long they take: Playing from Glass Harbor · 7 up next · 33 min."""
    parts = [f"Playing from {source}"] if source else []
    parts.append(f"{upcoming:,} up next" if upcoming else "Nothing up next")
    if upcoming:
        parts.append(length_text(seconds))
    return " · ".join(parts)


def section_of(entry: Entry, kind: str, source: str) -> str:
    """The heading a row of Up next falls under: Now playing, Next · added by you, Next from
    Glass Harbor (Next, when the queue's list has no name), Played."""
    if kind == "now":
        return "Now playing"
    if kind == "played":
        return "Played"
    if entry.added:
        return "Next · added by you"
    return f"Next from {source}" if source else "Next"


ROLES = (
    "key", "kind", "section", "first", "title", "line", "time", "cover", "path", "selected",
    "current",
)  # fmt: skip


class UpNextModel(QAbstractListModel):
    """Up next (R7.2): a row per song of the queue, the song playing first, then those to come,
    then those played, the latest first. Each row: its entry's key, its kind ("now", "next",
    "played"), the heading it falls under and whether it is the first under it, its title, the
    line under it, its length and cover, and whether it is selected and the current row. The
    songs' rows are read from the index a page at a time, as they are shown.

    Its rows are selected as every song list's are (R2.6, selection.Selection), by their entries'
    keys, so the selection stays with its songs as the queue changes: Enter plays the first song
    selected, Delete takes them out of the queue (the Player bridge's `playSelected` and
    `removeSelected`).

    Now Playing's queue at full size (R11.4.3, `played_shown`) puts the songs played last, that
    many of them, above the song playing, in the order they played, and leaves the rest out."""

    changed = Signal()  # the line over the list

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection] | None,
        queue: Queue,
        parent: QObject | None,
        played_shown: int = 0,
    ) -> None:
        super().__init__(parent)
        self._read, self._queue = read, queue
        self._played_shown = played_shown
        self._rows: list[tuple[Entry, str]] = []
        self._info: dict[int, SongInfo] = {}
        self._lengths: dict[int, float] = {}  # every queued song's length, for the line
        self._line = ""
        self._note = ""  # why the songs up next can't play now (R2.10)
        self._selection: Selection[int] = Selection()

    def set_note(self, note: str) -> None:
        """Why the song after the current one can't play now ("" when it can), shown in place of
        the line from the next `refresh`."""
        self._note = note

    def refresh(self) -> None:
        """The rows afresh, after the queue changed."""
        q = self._queue
        current = q.current
        self.beginResetModel()
        now = [(current, "now")] if current is not None else []
        coming = [(e, "next") for e in q.upcoming]
        if self._played_shown:
            last = q.played[-self._played_shown :]
            self._rows = [(e, "played") for e in last] + now + coming
        else:
            self._rows = now + coming + [(e, "played") for e in reversed(q.played)]
        self._info.clear()
        self._selection.keep(self._keys())
        self.endResetModel()
        upcoming = q.upcoming
        missing = [e.song for e in upcoming if e.song not in self._lengths]
        if missing and self._read is not None:
            for song_id, info in read_songs(self._read(), missing).items():
                self._lengths[song_id] = info.length or 0.0
        seconds = sum(self._lengths.get(e.song, 0.0) for e in upcoming)
        self._line = queue_line(q.source, len(upcoming), seconds) if current is not None else ""
        self.changed.emit()

    def first_next(self) -> int:
        """The row of the first song to come; the rows' count when none is to come."""
        return next(
            (i for i, (_, kind) in enumerate(self._rows) if kind == "next"), len(self._rows)
        )

    def entry(self, row: int) -> tuple[Entry, str] | None:
        """Row `row`'s entry and kind; None past the rows."""
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def row_of(self, row: int) -> dict[str, Any] | None:
        found = self.entry(row)
        if found is None:
            return None
        entry, kind = found
        info = self._info.get(entry.song)
        if info is None and self._read is not None:
            start = row - row % PAGE
            page = [e.song for e, _ in self._rows[start : start + PAGE]]
            self._info.update(read_songs(self._read(), page))
            info = self._info.get(entry.song)
        section = section_of(entry, kind, self._queue.source)
        before = self.entry(row - 1)
        first = before is None or section_of(before[0], before[1], self._queue.source) != section
        shown = info or SongInfo("", "A song no longer in the library", "", "", None, 0, "")
        return {
            "key": entry.key, "kind": kind, "section": section, "first": first,
            "title": shown.title, "line": row_line(shown) if info else "",
            "time": time_text(shown.length), "cover": shown.cover, "path": shown.path,
            "selected": entry.key in self._selection,
            "current": entry.key == self._selection.current,
        }  # fmt: skip

    # ---------- the selection (R2.6) ----------

    def _keys(self) -> list[int]:
        return [e.key for e, _ in self._rows]

    def selected(self) -> list[tuple[Entry, str]]:
        """The rows selected, each its entry and kind, in Up next's order."""
        return [r for r in self._rows if r[0].key in self._selection]

    def first_selected(self) -> int:
        """The first row selected; -1 for none."""
        return self._selection.first(self._keys())

    def _selection_changed(self) -> None:
        if self._rows:
            changed = [self._role("selected"), self._role("current")]
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1), changed)

    def _role(self, name: str) -> int:
        return int(Qt.ItemDataRole.UserRole) + ROLES.index(name)

    @Slot(int, bool, bool)
    def click(self, row: int, ctrl: bool, shift: bool) -> None:
        """A click on row `row`, as on any song list's (SongsModel.click)."""
        if self._selection.click(self._keys(), row, ctrl, shift):
            self._selection_changed()

    @Slot(int, int, int, result=int)
    def press(self, key: int, modifiers: int, page: int) -> int:
        """A key pressed while Up next has the focus, as on any song list's (SongsModel.press)."""
        name, shift = key_name(key, modifiers)
        row = self._selection.press(self._keys(), name, shift, page)
        if row != NOT_MINE:
            self._selection_changed()
        return row

    # ---------- QAbstractListModel ----------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self) -> dict[int, QByteArray]:
        base = int(Qt.ItemDataRole.UserRole)
        return {base + i: QByteArray(n.encode()) for i, n in enumerate(ROLES)}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        i = role - int(Qt.ItemDataRole.UserRole)
        if not 0 <= i < len(ROLES):
            return None
        row = self.row_of(index.row())
        return None if row is None else row[ROLES[i]]

    def _get_line(self) -> str:
        return self._line

    def _get_empty_text(self) -> str:
        return "" if self._rows else EMPTY

    def _get_note(self) -> str:
        return self._note

    line = QtProperty(str, _get_line, notify=changed)  # Playing from … · 7 up next · 33 min
    emptyText = QtProperty(str, _get_empty_text, notify=changed)  # what an empty Up next says
    note = QtProperty(str, _get_note, notify=changed)  # why they can't play now; "" when they can
