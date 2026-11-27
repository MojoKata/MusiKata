"""Playlists in the running app (R8, R6.3, P01-playlist-drag): the sidebar's list, a playlist's
page, and what changes them.

- **The sidebar's Playlists** (`PlaylistList`, R6.3): each playlist by name with its count of
  entries; **+** makes "New playlist", opens it and selects its name for editing (R8.3); a
  playlist's right-click menu renames it (its name edited in place), duplicates it, or deletes it
  after asking (R8.4, R6.8).
- **A playlist's page** (`PlaylistPage`, `EntriesModel`, R8.2): a mosaic of four of its covers,
  its name, its count, length, file and whether it names its songs by relative paths; Play,
  Shuffle and Export…; then its entries, each with its number, cover, title and artist, album,
  genre, rating and length, a drag handle for reordering (R8.5). An entry no song is at shows
  dimmed with "Missing" and the path it names, and Find (R8.7). Its rows are selected as a list of
  songs' are (R2.6); Delete, or Remove from playlist, takes the entries selected out without
  asking (R8.6). A smart playlist's page (R8.9) says so over its name and shows its rule in words
  (musikata.smart); its entries aren't moved or removed by hand, saying why, and Remove from
  playlist isn't offered.
- **What changes them** (`Playlists`): + and New playlist from selection (R8.3), Add to playlist
  in the selection bars and menus and songs dropped on one (R8.5), its message saying those there
  already and offering Undo, which takes them back out (`offer`: the playlist's own undo, its
  change being no save of the change history, R4.9); a file manager's files dropped on one (those
  outside the root brought into the library first, R12.5); renaming, duplicating and deleting
  (R8.4); moving entries, dragged within the page or by Ctrl+Shift+↑ / ↓ (R8.5, R6.9, R18.2),
  and removing them (R8.6);
  Find and its choice (R8.7, from the page or Needs attention), and Export… (R8.8), each run on a
  thread of its own through musikata_core.playlists.Store, the views read again after, and a
  message saying what was done (R6.7).

What each says is decided here as text (`detail_text`, `why_text`, …), tested without a window;
what a change does to a playlist is musikata_core.playlists'."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QUrl,
    Signal,
    Slot,
)

from musikata_core import art
from musikata_core import attention as core_attention
from musikata_core import playlists as core
from musikata_core import smart as core_smart
from musikata_core.playlists import Candidate, ExportDone, PlaylistError, Store

from .models import (
    COLUMNS,
    Searcher,
    SongsModel,
    cover_url,
    length_text,
    plural,
    tiles,
    time_text,
    title_of,
)
from .smart import NEWER_LATER, reading_text

if TYPE_CHECKING:
    from .bridges import Library

log = logging.getLogger(__name__)

NOT_THERE = "Playlists can't be changed while the music folder isn't available"  # R2.10
# files dropped from outside the root are R12.5's: copied or moved into the library through
# Organize files' dialog (`Playlists.outside`); without it, they aren't added
OUTSIDE_NOT_ADDED = "Files from outside the music folder can't be added here"
MISSING = "Missing"
OUTSIDE = "Not in your music folder"
REMOVE = {"label": "Remove from playlist", "icon": "close", "later": "", "action": "remove"}
ADD = {"label": "Add to playlist", "icon": "plus", "later": "", "action": "playlist"}
# a playlist's selection bar (R8.6): Play next first, then these by their `action`
ACTIONS = [
    REMOVE,
    ADD,
    {"label": "Edit tags", "icon": "genre", "later": "", "action": "edit"},
    {"label": "Infer from path", "icon": "wand", "later": "", "action": "infer"},
]
SMART_ACTIONS = ACTIONS[1:]  # a smart playlist's: its rule chooses its songs (R8.9)
EXPORT_MODES = (
    (core.ABSOLUTE, "A playlist naming the songs where they are",
     "An .m3u8 with each song's whole path, for players on this computer"),
    (core.COPIES, "The songs, numbered, with a playlist",
     "Each song copied as 01 - Artist - Title, beside an .m3u8 naming them: for a car's USB"
     " stick or a phone"),
)  # fmt: skip


# ---------- what the page and the dialogs say ----------


def paths_text(entries: int, absolute: int) -> str:
    """How a playlist names its songs (P01): relative paths, absolute paths, or both."""
    if not entries:
        return ""
    if not absolute:
        return "relative paths"
    return "absolute paths" if absolute == entries else "relative and absolute paths"


def detail_text(entries: int, seconds: float, path: str, absolute: int, missing: int = 0) -> str:
    """The line under a playlist's name (P01): 42 songs · 2 h 51 min · Playlists/Road Trip.m3u8
    · relative paths, and how many are missing."""
    parts = [plural(entries, "song") if entries else "No songs"]
    if seconds > 0:
        parts.append(length_text(seconds))
    parts.append(path)
    parts.append(paths_text(entries, absolute))
    if missing:
        parts.append(f"{missing:,} missing")
    return " · ".join(p for p in parts if p)


def kicker_text(kind: str, smart: bool = False) -> str:
    """Over a playlist's name (P01): Playlist · M3U8, or Smart playlist · M3U8 (R8.9)."""
    return f"{'Smart playlist' if smart else 'Playlist'} · {kind.upper()}"


def smart_text(name: str) -> str:
    """Why a smart playlist's songs aren't changed by hand (R8.9)."""
    return f"{name} is a smart playlist: its rule chooses its songs"


def note_of(path: str | None) -> str:
    """What a missing entry says before the path it names (R8.7): Missing, or, for a file
    outside the root, which can't be played from where it is (R12.5), Not in your music
    folder."""
    return MISSING if path is not None else OUTSIDE


def songs_text(n: int) -> str:
    return plural(n, "song")


def added_text(n: int, name: str, already: int = 0) -> str:
    """The message after songs are added to a playlist (R8.5): how many, and how many of them it
    held already, added again all the same."""
    if not n:
        return f"Nothing was added to {name}"
    said = f"Added {songs_text(n)} to {name}"
    if already and n == 1:
        return f"{said} (it was there already)"
    if already:
        return f"{said} ({already:,} {'was' if already == 1 else 'were'} there already)"
    return said


def took_back_text(n: int, wanted: int, name: str) -> str:
    """The message after R8.5's Undo took an addition back out: how many, and those that had
    moved since and stay."""
    if not n:
        return f"Nothing was taken out of {name}: it had changed since"
    said = f"Took {songs_text(n)} back out of {name}"
    if n < wanted:
        said += f"; {wanted - n:,} had moved since and stay"
    return said


def dropped_text(outside: int, found: int) -> str:
    """What a drop of files says when it adds none of them, or not all: those from outside the
    music folder when there is no way to bring them in (R12.5), and those under it that aren't
    songs."""
    if outside:
        return OUTSIDE_NOT_ADDED
    return "" if found else "Nothing dropped is a song in your library"


def made_text(name: str, n: int) -> str:
    return f"Made {name} with {songs_text(n)}" if n else f"Made {name}"


def removed_text(n: int, name: str) -> str:
    """R8.6's message: the files stay, so nothing was asked."""
    return f"Removed {songs_text(n)} from {name}; the files are untouched"


def why_text(c: Candidate) -> str:
    """Why Find offers a song (R8.7): its file's name, its title and artist, or both."""
    if c.by_name and c.by_tags:
        return "Same name and tags"
    return "Same name" if c.by_name else "Same title and artist"


def find_rows(found: Sequence[Candidate]) -> list[dict[str, Any]]:
    """Find's offers as its dialog lists them: title, artist, where, why and length."""
    return [
        {"title": c.title, "artist": c.artist, "path": c.path.replace("/", " › "),
         "why": why_text(c), "time": time_text(c.length)}
        for c in found
    ]  # fmt: skip


def find_text(searching: bool, found: int, root: str) -> str:
    """Find's line over what it found (R8.7)."""
    if searching:
        return "Looking under your music folder…"
    if not found:
        return f"Nothing under {root} has its name, or its title and artist"
    return f"Found {plural(found, 'song')} by its name or its tags: choose the one it is"


def question_of(name: str, path: str) -> dict[str, str]:
    """R8.4's question before a playlist goes to the trash (R6.8)."""
    return {
        "title": f"Move the playlist {name} to the trash?",
        "detail": f"Its file, {path}, goes to the system's trash. The songs it names stay where"
        " they are.",
        "yes": "Move to trash",
    }


def export_text(done: ExportDone, mode: str, skipped: int, folder: str) -> str:
    """The message after Export (R8.8): what was written where, what failed, what was left out."""
    if done.stopped:
        return f"Export stopped after {songs_text(done.copied + done.there)}; no playlist written"
    if mode == core.COPIES:
        what = f"Copied {songs_text(done.copied)} and a playlist to {folder}"
        if done.there:
            what += f" ({done.there:,} there already)"
    else:
        what = f"Wrote a playlist to {folder}" if done.playlist else "No playlist was written"
    if done.failed:
        name, why = done.failed[0]
        more = f", and {len(done.failed) - 1:,} more" if len(done.failed) > 1 else ""
        what += f"; {name} {why}{more}"
    if skipped:
        what += f"; {plural(skipped, 'missing song')} left out"
    return what


def export_progress_text(done: int, of: int) -> str:
    return f"Copying {done:,} of {songs_text(of)}…"


def local_path(url: str) -> str:
    """A folder chosen in the platform's dialog, a file: URL or a path, as a whole path."""
    path = QUrl(url).toLocalFile() if url.startswith("file:") else url
    return os.path.abspath(os.path.expanduser(path)) if path else ""


def move_key(key: int, modifiers: int) -> int:
    """Ctrl+Shift+↑ / ↓ (R6.9, R18.2; ⇧⌘ on macOS, which Qt gives as Ctrl): -1 or 1, the way the
    entries selected move; 0 for any other key."""
    mods = Qt.KeyboardModifier(modifiers)
    both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    others = Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
    if (mods & both) != both or mods & others:
        return 0
    return {int(Qt.Key.Key_Up): -1, int(Qt.Key.Key_Down): 1}.get(int(key), 0)


# ---------- the sidebar's list (R6.3) ----------


def is_smart(rule: str | None) -> bool:
    """Whether a playlist of the rule text `rule` (the index's) is a smart one, its songs not
    changed by hand (R8.9): a rule kept current or a newer MusiKata's; a broken one is a plain
    list."""
    reading = core_smart.reading_of(rule)
    return reading is not None and reading.smart


class PlaylistList(QAbstractListModel):
    """The sidebar's Playlists (R6.3): every playlist by name (R2.13's sort key), each with its id
    (playlistId), name, count of entries and whether it is a smart one (R8.9: nothing is added to
    it by hand). Read whole: a library has tens of playlists, not thousands."""

    roles = ("playlistId", "name", "count", "smart")
    countChanged = Signal()

    def __init__(self, read: Callable[[], sqlite3.Connection], parent: QObject | None = None):
        super().__init__(parent)
        self._read = read
        self._rows: list[dict[str, Any]] = []

    def refresh(self) -> None:
        """The playlists read again (after a scan or a change)."""
        rows = [
            {"playlistId": int(i), "name": str(n), "count": f"{int(k):,}", "smart": is_smart(r)}
            for i, n, k, r in self._read().execute(
                "SELECT id, name, (SELECT COUNT(*) FROM playlist_entry WHERE playlist_id ="
                " playlist.id), rule FROM playlist ORDER BY name_key, path"
            )
        ]
        if rows == self._rows:
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countChanged.emit()

    def items(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        base = int(Qt.ItemDataRole.UserRole)
        return {base + i: QByteArray(n.encode()) for i, n in enumerate(self.roles)}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        i = role - int(Qt.ItemDataRole.UserRole)
        if not 0 <= index.row() < len(self._rows) or not 0 <= i < len(self.roles):
            return None
        return self._rows[index.row()][self.roles[i]]

    count = QtProperty(int, lambda self: len(self._rows), notify=countChanged)


# ---------- a playlist's songs (R8.2, R8.6, R8.7) ----------

ENTRY_COLUMNS = (
    "playlist_entry.written, playlist_entry.path, playlist_entry.title, playlist_entry.position,"
    " song.id, (SELECT thumb FROM album WHERE album.id = song.album_id), song.path, song.title,"
    " song.artist, song.album, (SELECT group_concat(genre, '; ' ORDER BY position) FROM song_genre"
    " WHERE song_id = song.id), song.year, song.track, song.rating, (SELECT SUM(count) FROM play"
    " WHERE song_id = song.id), song.length"
)
ENTRY_TABLE = "playlist_entry LEFT JOIN song ON song.path = playlist_entry.path"


def entry_row(r: Sequence[Any]) -> dict[str, Any]:
    """A row of ENTRY_COLUMNS as the page shows it: a song's, or a missing entry's, dimmed, with
    "Missing" and the path it names (R8.7)."""
    written, path, extinf, position, song, thumb = r[:6]
    rest = r[6:]
    number = str(int(position) + 1)
    if song is None:
        name = core.stem(str(written))
        artist, _, title = str(extinf).partition(" - ")
        return {
            "title": title or str(extinf) or name, "artist": artist if title else "",
            "album": "", "genre": "", "year": "", "track": number, "rating": 0, "plays": "",
            "time": "", "path": str(written), "number": number, "cover": "", "missing": True,
            "note": note_of(path), "where": str(written),
        }  # fmt: skip
    s_path, title, artist, album, genre, year, track, rating, plays, length = rest
    return {
        "title": title_of(title, s_path), "artist": artist or "", "album": album or "",
        "genre": genre or "", "year": str(year) if year else "", "track": number,
        "rating": rating or 0, "plays": f"{plays:,}" if plays else "", "time": time_text(length),
        "path": s_path, "number": number, "cover": cover_url(thumb), "missing": False,
        "note": "", "where": "",
    }  # fmt: skip


class EntriesModel(SongsModel):
    """A playlist's entries (R8.2), in its order, paged as a list of songs is; selected by entry
    (a song can be in a playlist twice, R8.5), each standing for its song where it has one:
    what Play next, Edit tags, a rating or Add to playlist act on. A missing entry (R8.7) has no
    song: it doesn't play, and is passed by in the queue (R7.1)."""

    roles = (*COLUMNS, "playing", "selected", "current", "number", "cover", "missing", "note",
             "where")  # fmt: skip
    key = "playlist_entry.id"

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        parent: QObject | None = None,
        searcher: Searcher | None = None,
    ) -> None:
        super().__init__(read, "artist", parent, "playlist_entry.playlist_id = ?", (-1,), searcher)
        self._songs: dict[int, int] = {}  # entry id -> its song's id
        self.smart = False  # a smart playlist's (R8.9): its entries aren't moved or removed

    def _query(self) -> tuple[str, str, str, tuple[Any, ...], str]:
        return ENTRY_COLUMNS, ENTRY_TABLE, self._where, self._params, "playlist_entry.position"

    def _narrow(self, songs: str, params: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
        return f"song.id IN (SELECT song.id FROM song WHERE {songs})", params

    def _row(self, r: tuple[Any, ...]) -> dict[str, Any]:
        return entry_row(r)

    def _value(self, row: dict[str, Any], name: str) -> Any:
        if name == "playing":
            return not row["missing"] and row["path"] == self._playing
        return row[name]

    def _rows_found(self) -> None:
        self._songs = {
            int(e): int(s)
            for e, s in self._read().execute(
                "SELECT playlist_entry.id, song.id FROM playlist_entry JOIN song ON song.path ="
                f" playlist_entry.path WHERE {self._where}",
                self._params,
            )
        }
        super()._rows_found()

    def for_playlist(self, playlist: int) -> None:
        """Lists the entries of `playlist` (its id) instead, and reads them."""
        self.select("playlist_entry.playlist_id = ?", (playlist,))

    def playlist(self) -> int:
        return int(self._params[0]) if self._params else -1

    def song_at(self, n: int) -> int | None:
        entry = self._id_at(n)
        return self._songs.get(entry) if entry is not None else None

    def _songs_of(self, entries: Sequence[int]) -> list[int]:
        return [self._songs[e] for e in entries if e in self._songs]

    def selected_entries(self) -> list[int]:
        """The entries selected, by id, in the playlist's order."""
        return self._selection.chosen(self._ids or [])

    def selected_songs(self) -> list[int]:
        return self._songs_of(self.selected_entries())

    def entries_at(self, row: int) -> list[int]:
        """The entries a right click on row `row` stands for: the selection when the row is in
        it, else the row's alone."""
        entry = self._id_at(row)
        if entry is None:
            return []
        return self.selected_entries() if entry in self._selection else [entry]

    def songs_at(self, row: int) -> list[int]:
        return self._songs_of(self.entries_at(row))

    def queue_from(self, row: int) -> tuple[list[int], str]:
        """Row `row`'s song and those of the entries after it (R7.1), missing ones passed by;
        none when the row's entry is missing."""
        if self.song_at(row) is None:
            return [], self.source
        return self._songs_of((self._ids or [])[row:]), self.source

    def position_at(self, row: int) -> int:
        """The place in the playlist of row `row`'s entry (from 0); past the rows, the end."""
        r = self.row(row) if 0 <= row < self.rowCount() else None
        if r is None:
            return self.entry_count()
        return int(r["number"]) - 1

    def entry_count(self) -> int:
        """How many entries the playlist has, whatever a search leaves."""
        r = (
            self._read()
            .execute(
                "SELECT COUNT(*) FROM playlist_entry WHERE playlist_id = ?", (self.playlist(),)
            )
            .fetchone()
        )
        return int(r[0])

    def select_positions(self, positions: Sequence[int]) -> None:
        """The entries at `positions` (places, from 0) selected, once the rows read again have
        come: those a reorder moved, where they are now."""
        wanted = list(positions)
        found = [
            int(i)
            for (i,) in self._read().execute(
                "SELECT id FROM playlist_entry WHERE playlist_id = ? AND position IN"
                f" ({', '.join('?' * len(wanted))}) ORDER BY position",
                (self.playlist(), *wanted),
            )
        ] if wanted else []  # fmt: skip
        self.select_songs(found)

    def select_rows(self, rows: Sequence[int]) -> None:
        """The entries of rows `rows` selected: as the tour shows a drag of them (P01)."""
        ids = self._ids or []
        self.select_songs([ids[r] for r in rows if 0 <= r < len(ids)])

    def missing_at(self, row: int) -> bool:
        return self._id_at(row) is not None and self.song_at(row) is None

    def entry_of(self, row: int) -> tuple[str, str, int | None] | None:
        """Row `row`'s entry as Find looks for it: the place it names, its #EXTINF text and
        seconds."""
        entry = self._id_at(row)
        if entry is None:
            return None
        r = (
            self._read()
            .execute("SELECT written, title, seconds FROM playlist_entry WHERE id = ?", (entry,))
            .fetchone()
        )
        return (str(r[0]), str(r[1]), r[2]) if r else None


class PlaylistPage(QObject):
    """A playlist's page (R8.2, P01-playlist-drag): its mosaic of four covers, kicker, name and
    the line under it (`detail_text`), a smart playlist's rule in words (R8.9; `ruleLater` why a
    newer MusiKata's isn't edited), and its entries (`EntriesModel`). Its id is the playlist's."""

    changed = Signal()

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        parent: QObject | None = None,
        searcher: Searcher | None = None,
    ) -> None:
        super().__init__(parent)
        self._read = read
        self._id = -1
        self._values: dict[str, Any] = {}
        self._songs = EntriesModel(read, self, searcher)
        self._songs.countChanged.connect(self.changed)

    def load(self, playlist: int, search: str | None = None) -> bool:
        """Shows the playlist `playlist`; False when there is none of that id."""
        c = self._read()
        r = c.execute(
            "SELECT name, path, kind, absolute, (SELECT COUNT(*) FROM playlist_entry WHERE"
            " playlist_id = playlist.id), rule FROM playlist WHERE id = ?",
            (playlist,),
        ).fetchone()
        if r is None:
            return False
        name, path, kind, absolute, entries, rule = r
        reading = core_smart.reading_of(rule)
        smart = reading is not None and reading.smart
        seconds, missing = c.execute(
            "SELECT coalesce(SUM(song.length), 0), SUM(song.id IS NULL) FROM playlist_entry LEFT"
            " JOIN song ON song.path = playlist_entry.path WHERE playlist_id = ?",
            (playlist,),
        ).fetchone()
        thumbs = [
            str(t)
            for (t,) in c.execute(
                "SELECT album.thumb FROM playlist_entry JOIN song ON song.path ="
                " playlist_entry.path JOIN album ON album.id = song.album_id WHERE playlist_id = ?"
                " AND album.thumb IS NOT NULL GROUP BY album.id ORDER BY MIN(position) LIMIT 4",
                (playlist,),
            )
        ]
        again = playlist == self._id
        self._id = playlist
        self._songs.source = str(name)
        self._songs.smart = smart
        empty = (
            "No song matches its rule yet"
            if smart
            else "No songs yet: add some with Add to playlist"
        )
        self._values = {
            "name": str(name),
            "path": str(path),
            "kicker": kicker_text(str(kind), smart),
            "smart": smart,
            "rule": reading_text(reading) if reading is not None else "",
            "ruleLater": NEWER_LATER
            if reading is not None and reading.kind == core_smart.NEWER
            else "",
            "detail": detail_text(
                int(entries), float(seconds or 0), str(path), int(absolute), int(missing or 0)
            ),  # fmt: skip
            "tiles": tiles(thumbs),
            "empty": "" if entries else empty,
            "playable": int(entries) > int(missing or 0),
        }
        # the header first, then the rows: a smart playlist's rule line makes the header taller
        # (R8.9), and rows laid out under the old one would be left where they were
        self.changed.emit()
        if search is not None:
            self._songs.search_next(search)
        if again:
            self._songs.refresh()
        else:
            self._songs.clearSelection()
            self._songs.for_playlist(playlist)
        return True

    def set_search(self, text: str) -> None:
        self._songs.set_search(text)

    def lists(self) -> list[tuple[EntriesModel, str]]:
        return [(self._songs, "song")]

    def value(self, name: str) -> Any:
        return self._values.get(name, "")

    id = QtProperty(int, lambda self: self._id, notify=changed)
    name = QtProperty(str, lambda self: self._values.get("name", ""), notify=changed)
    path = QtProperty(str, lambda self: self._values.get("path", ""), notify=changed)
    kicker = QtProperty(str, lambda self: self._values.get("kicker", ""), notify=changed)
    detail = QtProperty(str, lambda self: self._values.get("detail", ""), notify=changed)
    tiles = QtProperty(list, lambda self: self._values.get("tiles", []), notify=changed)
    emptyText = QtProperty(str, lambda self: self._values.get("empty", ""), notify=changed)
    playable = QtProperty(bool, lambda self: bool(self._values.get("playable")), notify=changed)
    smart = QtProperty(bool, lambda self: bool(self._values.get("smart")), notify=changed)
    rule = QtProperty(str, lambda self: self._values.get("rule", ""), notify=changed)  # R8.9
    ruleLater = QtProperty(str, lambda self: self._values.get("ruleLater", ""), notify=changed)
    songs = QtProperty(QObject, lambda self: self._songs, constant=True)
    actions = QtProperty(
        list, lambda self: SMART_ACTIONS if self._values.get("smart") else ACTIONS, notify=changed
    )


# ---------- what changes them (R8.3, R8.4, R8.6 to R8.8) ----------


def songs_of(model: QObject | None, row: int = -1) -> list[int]:
    """The songs a list's selection (row -1), or a right click on row `row`, stands for."""
    from .edittags import target_at, target_of

    if model is None:
        return []
    return (target_of(model) if row < 0 else target_at(model, row))[0]


class Playlists(QObject):
    """What changes playlists (R8.3, R8.4, R8.6 to R8.8), each change run through `store`
    (playlists.Store) on a thread of its own (`executor`, made when first needed), then the
    library's views read again (`library`: Library.reload) and a message said (`say`, the change
    history's). `available` says whether the root is there (R2.10); `trash` moves a deleted
    playlist to the system's trash; `home` shows paths as ~/…"""

    changed = Signal()  # the name edited, the question, Find, Export
    _done = Signal(object)
    _progressed = Signal(int, int)

    def __init__(
        self,
        store: Store,
        library: Library,
        read: Callable[[], sqlite3.Connection],
        say: Callable[[str], object] | None = None,
        offer: Callable[[str, Callable[[], object]], object] | None = None,
        trash: art.Trash = art.to_trash,
        available: Callable[[], bool] = lambda: True,
        home: str = "",
        executor: Executor | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store, self._read, self._say_to, self._offer_to = store, read, say, offer
        self._library: Library | None = library
        # files from outside the root dropped on a playlist, brought into the library and added
        # to it (R12.5, R8.5: OrganizeFiles.add_files); None: they aren't
        self.outside: Callable[[Sequence[str], int], object] | None = None
        self._trash, self._available, self._home = trash, available, home
        self._executor = executor
        self._closed = False
        self._editing = -1  # the playlist whose name is being edited in the sidebar
        self._asked = -1  # the playlist the question asks about
        self._find: dict[str, Any] = {}  # Find's entry, while its dialog is open
        self._found: list[Candidate] = []
        self._finding = False
        self._export: dict[str, Any] = {}  # Export…'s playlist, way and folder, while open
        self._last_folder = ""  # the folder exported to last, offered again
        self._exporting = False
        self._progress = (0, 0)
        self._stop = threading.Event()
        self._done.connect(self._on_done)
        self._progressed.connect(self._on_progressed)

    # ---------- running a change ----------

    def _say(self, text: str) -> None:
        if self._say_to is not None:
            self._say_to(text)

    def _offer(self, text: str, undo: Callable[[], object]) -> None:
        """A message with Undo (R8.5); said without it when there is none to offer it."""
        if self._offer_to is not None:
            self._offer_to(text, undo)
        else:
            self._say(text)

    def _run(self, job: Callable[[], Any], then: Callable[[Any], None]) -> None:
        """job() on the playlists' thread; then(its result, or the PlaylistError or error it
        raised) here."""
        if self._closed:
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="playlists")

        def guarded() -> None:
            try:
                result: Any = job()
            except PlaylistError as e:
                result = e
            except Exception as e:  # noqa: BLE001  (logged; the message says it failed)
                log.exception("a change to a playlist failed")
                result = PlaylistError(f"It couldn't be done: {e}")
            self._done.emit((then, result))

        self._executor.submit(guarded)

    @Slot(object)
    def _on_done(self, done: tuple[Callable[[Any], None], Any]) -> None:
        then, result = done
        if self._closed:
            return
        if isinstance(result, PlaylistError):
            self._say(str(result))
            self._reload()
            return
        then(result)

    def _reload(self) -> None:
        if self._library is not None:
            self._library.reload()

    def _can(self) -> bool:
        if not self._available():
            self._say(NOT_THERE)
            return False
        return True

    # ---------- making, renaming, duplicating, deleting (R8.3, R8.4) ----------

    @Slot()
    def create(self) -> None:
        """+ beside Playlists (R8.3): "New playlist", opened, its name selected for editing."""
        if not self._can():
            return
        store = self._store

        def then(made: core.Changed) -> None:
            self._reload()
            if made.playlist is not None:
                if self._library is not None:
                    self._library.openPlaylist(made.playlist)
                self._edit(made.playlist)

        self._run(lambda: store.create(()), then)

    @Slot(QObject, int)
    def createFrom(self, model: QObject, row: int = -1) -> None:  # noqa: N802
        """New playlist from selection (R8.3), and Add to playlist's New playlist…: one holding
        the songs the selection (row -1), or the row right-clicked, stands for; its name selected
        for editing."""
        songs = songs_of(model, row)
        if not songs or not self._can():
            return
        store = self._store

        def then(made: core.Changed) -> None:
            self._reload()
            self._say(made_text(made.name, made.count))
            if made.playlist is not None:
                self._edit(made.playlist)

        self._run(lambda: store.create(songs), then)

    @Slot(int, QObject, int)
    def addTo(self, playlist: int, model: QObject, row: int = -1) -> None:  # noqa: N802
        """Add to playlist (R2.9.6, L03): the songs of the selection (row -1), or of the row
        right-clicked, added at the playlist's end."""
        self.add_songs(playlist, songs_of(model, row))

    def add_songs(self, playlist: int, songs: Sequence[int], note: str = "") -> None:
        """`songs` (by id) added at the playlist's end (R8.5): from Add to playlist, or dropped on
        it. The message says how many, and how many it held already, added again all the same,
        then `note`; its Undo takes them back out (`take_back`)."""
        if not songs or not self._can():
            return
        store = self._store

        def then(done: core.Changed) -> None:
            self._reload()
            text = added_text(done.count, done.name, done.already)
            text = f"{text}; {note}" if note else text
            if done.count and done.playlist is not None:
                self._offer(text, lambda: self._take_back(playlist, done))
            else:
                self._say(text)

        self._run(lambda: store.add(playlist, songs), then)

    def _take_back(self, playlist: int, done: core.Changed) -> None:
        """R8.5's Undo: the songs an addition (`done`) put at the playlist's end taken back out."""
        if not self._can():
            return
        store = self._store

        def then(back: core.Changed) -> None:
            self._reload()
            self._say(took_back_text(back.count, len(done.positions), back.name))

        self._run(lambda: store.take_back(playlist, done.positions, done.paths), then)

    def add_files(self, playlist: int, paths: Sequence[str]) -> None:
        """Files and folders a file manager dropped on the playlist (R8.5), by their whole paths:
        the songs of those under the root added; those outside it brought into the library first
        (R12.5, `outside`: Organize files' dialog, which adds them to the playlist once they are
        in)."""
        if not self._can():
            return
        inside, outside = core.dropped(paths, self._store.root)
        if outside and self.outside is not None:
            self.outside(outside, playlist)
            if not inside:
                return
            outside = []
        songs = core.songs_dropped(self._read(), inside)
        note = dropped_text(len(outside), len(songs))
        if songs:
            self.add_songs(playlist, songs, note if outside else "")
        elif note:
            self._say(note)

    # ---------- reordering (R8.5, R6.9, R18.2) ----------

    def _reorder(self, model: EntriesModel, job: Callable[[], core.Changed]) -> None:
        """A reorder run on the playlists' thread; then its entries, where they are now, stay
        selected, so Ctrl+Shift+↑ / ↓ goes on moving them."""
        if not self._can():
            return
        playlist = model.playlist()

        def then(done: core.Changed) -> None:
            self._reload()
            if model.playlist() == playlist and done.positions:
                model.select_positions(done.positions)

        self._run(job, then)

    def move_entries(self, model: QObject, entries: Sequence[int], before: int) -> None:
        """Entries of a playlist's page dragged within it (R8.5): moved, in their order, above
        the entry at place `before` (past the last: to the end), where the insertion line was."""
        if not isinstance(model, EntriesModel) or not entries or self._refused(model):
            return
        store, playlist = self._store, model.playlist()
        self._reorder(model, lambda: store.move(playlist, entries, before))

    @Slot(QObject, int, int, result=bool)
    def pressMove(self, model: QObject, key: int, modifiers: int) -> bool:  # noqa: N802
        """A key on a playlist's page: Ctrl+Shift+↑ / ↓ (⇧⌘ on macOS) moves the entries selected
        one place up or down (R6.9, R18.2); False for any other key, which goes on to the list."""
        by = move_key(key, modifiers)
        if not by or not isinstance(model, EntriesModel):
            return False
        entries = model.selected_entries()
        if entries and not self._refused(model):
            store, playlist = self._store, model.playlist()
            self._reorder(model, lambda: store.nudge(playlist, entries, by))
        return True

    def _edit(self, playlist: int) -> None:
        self._editing = playlist
        self.changed.emit()

    @Slot(int)
    def startRename(self, playlist: int) -> None:  # noqa: N802
        """Rename (R8.4): the playlist's name edited in the sidebar."""
        if self._can():
            self._edit(playlist)

    @Slot()
    def cancelRename(self) -> None:  # noqa: N802
        """Esc, or the focus gone: the name stays."""
        self._edit(-1)

    @Slot(int, str)
    def rename(self, playlist: int, name: str) -> None:
        """The name typed (R8.4): the playlist and its file renamed; the same name, or none,
        changes nothing."""
        self._edit(-1)
        if not name.strip() or name.strip() == self._store.name(playlist) or not self._can():
            return
        store, wanted = self._store, name.strip()

        def then(done: core.Changed) -> None:
            self._reload()

        self._run(lambda: store.rename(playlist, wanted), then)

    @Slot(int)
    def duplicate(self, playlist: int) -> None:
        """Duplicate (R8.4): a copy beside it, "Road Trip copy"."""
        if not self._can():
            return
        store = self._store

        def then(done: core.Changed) -> None:
            self._reload()
            self._say(f"Made {done.name}")

        self._run(lambda: store.duplicate(playlist), then)

    @Slot(int)
    def askDelete(self, playlist: int) -> None:  # noqa: N802
        """Delete playlist (R8.4): asks first (R6.8)."""
        if self._store.name(playlist) and self._can():
            self._asked = playlist
            self.changed.emit()

    @Slot(bool)
    def answer(self, yes: bool) -> None:
        """The question's answer: Move to trash, or Cancel."""
        playlist, self._asked = self._asked, -1
        self.changed.emit()
        if not yes or playlist < 0:
            return
        store, trash = self._store, self._trash

        def then(done: core.Changed) -> None:
            self._reload()
            self._say(f"Moved {done.name} to the trash; the songs it named are untouched")

        self._run(lambda: store.delete(playlist, trash), then)

    # ---------- removing entries (R8.6) ----------

    def _refused(self, model: EntriesModel) -> bool:
        """A smart playlist's entries aren't moved or removed by hand (R8.9): said why."""
        if model.smart:
            self._say(smart_text(model.source))
        return model.smart

    def _remove(self, model: QObject, entries: list[int]) -> None:
        if not isinstance(model, EntriesModel) or not entries or self._refused(model):
            return
        if not self._can():
            return
        store, playlist = self._store, model.playlist()
        model.clearSelection()

        def then(done: core.Changed) -> None:
            self._reload()
            self._say(removed_text(done.count, done.name))

        self._run(lambda: store.remove(playlist, entries), then)

    @Slot(QObject)
    def removeSelected(self, model: QObject) -> None:  # noqa: N802
        """Delete, or the selection bar's Remove from playlist (R8.6): the entries selected taken
        out, without asking (R6.8: the files stay)."""
        if isinstance(model, EntriesModel):
            self._remove(model, model.selected_entries())

    @Slot(QObject, int)
    def removeRow(self, model: QObject, row: int) -> None:  # noqa: N802
        """Remove from playlist in a row's menu: the selection when the row is in it, else the
        row's entry."""
        if isinstance(model, EntriesModel):
            self._remove(model, model.entries_at(row))

    # ---------- Find (R8.7) ----------

    def _open_find(self, playlist: int, written: str, title: str, seconds: int | None) -> None:
        c = self._read()
        r = c.execute("SELECT name FROM playlist WHERE id = ?", (playlist,)).fetchone()
        if r is None:
            return
        self._find = {"playlist": playlist, "name": str(r[0]), "written": written,
                      "title": title, "seconds": seconds}  # fmt: skip
        self._found, self._finding = [], True
        self.changed.emit()
        read = self._read

        def then(found: list[Candidate]) -> None:
            if self._find.get("written") == written:
                self._found, self._finding = found, False
                self.changed.emit()

        self._run(lambda: core.find(read(), written, title, seconds), then)

    @Slot(QObject, int)
    def findRow(self, model: QObject, row: int) -> None:  # noqa: N802
        """Find on a missing entry of the page (R8.7)."""
        if not isinstance(model, EntriesModel):
            return
        entry = model.entry_of(row)
        if entry is not None:
            self._open_find(model.playlist(), *entry)

    def find_entry(self, e: core_attention.Entry) -> None:
        """Needs attention's Find (R2.8): the missing entry `e` in its dialog."""
        path, written = core_attention.missing_of(e.about)
        r = (
            self._read()
            .execute(
                "SELECT playlist.id, e.title, e.seconds FROM playlist_entry AS e JOIN playlist ON"
                " playlist.id = e.playlist_id WHERE playlist.path = ? AND e.written = ?"
                " ORDER BY e.position LIMIT 1",
                (path, written),
            )
            .fetchone()
        )
        if r is not None:
            self._open_find(int(r[0]), written, str(r[1]), r[2])

    @Slot(int)
    def choose(self, n: int) -> None:
        """A song Find offered chosen: each entry of the playlist naming that place made to name
        it (R8.7)."""
        if not 0 <= n < len(self._found) or not self._find or not self._can():
            return
        song, playlist, written = self._found[n], self._find["playlist"], self._find["written"]
        self.closeFind()
        store = self._store

        def then(done: core.Changed) -> None:
            self._reload()
            self._say(f"{done.name} now names {song.path}")

        self._run(lambda: store.fix(playlist, written, song.song), then)

    @Slot()
    def closeFind(self) -> None:  # noqa: N802
        self._find, self._found, self._finding = {}, [], False
        self.changed.emit()

    # ---------- Export… (R8.8) ----------

    @Slot(int)
    def openExport(self, playlist: int) -> None:  # noqa: N802
        """Export… on a playlist's page (R8.8): its dialog, the first way chosen, the folder
        exported to last offered again."""
        name = self._store.name(playlist)
        if not name:
            return
        self._export = {"playlist": playlist, "name": name, "mode": core.ABSOLUTE,
                        "folder": self._last_folder}  # fmt: skip
        self.changed.emit()

    @Slot(str)
    def setExportMode(self, mode: str) -> None:  # noqa: N802
        if self._export and mode in (core.ABSOLUTE, core.COPIES) and not self._exporting:
            self._export["mode"] = mode
            self.changed.emit()

    @Slot(str)
    def setExportFolder(self, folder: str) -> None:  # noqa: N802
        """The folder chosen in the platform's dialog (a file: URL) or typed."""
        if self._export and not self._exporting:
            self._export["folder"] = self._last_folder = local_path(folder)
            self.changed.emit()

    def _exported_songs(self, playlist: int) -> list[core.Exported | None]:
        root = self._store.root
        return [
            core.Exported(core.full_path(root, str(p)), a, t, n) if p is not None else None
            for p, a, t, n in self._read().execute(
                "SELECT song.path, song.artist, song.title, song.length FROM playlist_entry LEFT"
                " JOIN song ON song.path = playlist_entry.path WHERE playlist_id = ?"
                " ORDER BY position",
                (playlist,),
            )
        ]

    @Slot()
    def export(self) -> None:
        """Export (R8.8): the playlist written to the folder chosen, as the way chosen says; the
        songs copied off the GUI thread, with progress, until Cancel."""
        if not self._export or self._exporting or self._export_later():
            return
        mode, folder, name = self._export["mode"], self._export["folder"], self._export["name"]
        plan = core.export_plan(name, self._exported_songs(self._export["playlist"]), mode)
        self._exporting, self._progress = True, (0, len(plan.copies))
        self._stop.clear()
        self.changed.emit()
        stop, progressed = self._stop, self._progressed

        def then(done: ExportDone) -> None:
            self._exporting = False
            self._export = {} if not done.stopped else self._export
            self.changed.emit()
            self._say(export_text(done, mode, plan.skipped, self._shown(folder)))

        self._run(lambda: core.export(plan, folder, progressed.emit, stop.is_set), then)

    @Slot(int, int)
    def _on_progressed(self, done: int, of: int) -> None:
        self._progress = (done, of)
        self.changed.emit()

    @Slot()
    def cancelExport(self) -> None:  # noqa: N802
        """Cancel: while copying, the copying stops after the song it is on; else the dialog
        closes."""
        if self._exporting:
            self._stop.set()
            return
        self._export = {}
        self.changed.emit()

    def _export_later(self) -> str:
        if not self._export:
            return ""
        if not self._export.get("folder"):
            return "Choose the folder to export to"
        if not os.path.isdir(self._export["folder"]):
            return "That folder isn't there"
        return ""

    def _shown(self, path: str) -> str:
        if self._home and (path == self._home or path.startswith(self._home + os.sep)):
            return "~" + path[len(self._home) :]
        return path

    # ---------- the tour, and closing ----------

    def go(self, step: Mapping[str, Any]) -> None:
        """A tour's step (A1.6): {"export": True} opens Export… on the playlist shown;
        {"find": "<title>"} Find on that missing entry of it."""
        if self._library is None:
            return
        page = self._library.property("playlistPage")
        if step.get("export") and page.property("id") >= 0:
            self.openExport(int(page.property("id")))
        title = step.get("find")
        if title:
            model = page.property("songs")
            for row in range(model.rowCount()):
                r = model.row(row)
                if r is not None and r["missing"] and r["title"] == title:
                    self.findRow(model, row)

    def shut(self) -> None:
        """For closing the window: a change going on finishes, Export is stopped; nothing starts
        after. What the threads held is let go (A1.3)."""
        self._closed = True
        self._stop.set()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._say_to = self._library = None
        self._available = _gone

    # ---------- what QML reads ----------

    def _get_question(self) -> dict[str, str]:
        if self._asked < 0:
            return {}
        r = (
            self._read()
            .execute("SELECT name, path FROM playlist WHERE id = ?", (self._asked,))
            .fetchone()
        )
        return question_of(str(r[0]), str(r[1])) if r else {}

    def _get_find_title(self) -> str:
        if not self._find:
            return ""
        title = str(self._find["title"])
        return f"Find {title.partition(' - ')[2] or title or core.stem(self._find['written'])}"

    def _get_find_about(self) -> str:
        if not self._find:
            return ""
        return f"Missing from {self._find['name']}: {self._find['written']}"

    def _get_export_modes(self) -> list[dict[str, Any]]:
        chosen = self._export.get("mode", core.ABSOLUTE)
        return [{"mode": m, "label": label, "detail": detail, "chosen": m == chosen}
                for m, label, detail in EXPORT_MODES]  # fmt: skip

    def _get_export_text(self) -> str:
        if self._exporting and self._export.get("mode") == core.COPIES:
            return export_progress_text(*self._progress)
        if self._exporting:
            return "Writing the playlist…"
        return self._export_later()

    question = QtProperty(dict, _get_question, notify=changed)  # {} when none
    editing = QtProperty(int, lambda self: self._editing, notify=changed)  # -1: none
    findOpen = QtProperty(bool, lambda self: bool(self._find), notify=changed)
    findTitle = QtProperty(str, _get_find_title, notify=changed)
    findAbout = QtProperty(str, _get_find_about, notify=changed)
    findRows = QtProperty(list, lambda self: find_rows(self._found), notify=changed)
    findText = QtProperty(
        str,
        lambda self: find_text(self._finding, len(self._found), self._shown(self._store.root)),
        notify=changed,
    )
    finding = QtProperty(bool, lambda self: self._finding, notify=changed)
    exportOpen = QtProperty(bool, lambda self: bool(self._export), notify=changed)
    exportTitle = QtProperty(
        str, lambda self: f"Export {self._export.get('name', '')}", notify=changed
    )
    exportModes = QtProperty(list, _get_export_modes, notify=changed)
    exportFolder = QtProperty(
        str, lambda self: self._shown(self._export.get("folder", "")), notify=changed
    )
    exportLater = QtProperty(str, lambda self: self._export_later(), notify=changed)
    exportText = QtProperty(str, _get_export_text, notify=changed)
    exporting = QtProperty(bool, lambda self: self._exporting, notify=changed)
    exportProgress = QtProperty(
        float, lambda self: self._progress[0] / self._progress[1] if self._progress[1] else 0.0,
        notify=changed,
    )  # fmt: skip
    opened = QtProperty(
        bool, lambda self: bool(self._find) or bool(self._export) or self._asked >= 0,
        notify=changed,
    )  # fmt: skip


def _gone() -> bool:
    return False
