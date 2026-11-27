"""Playlists in the running app (R8, R6.3, P01-playlist-drag): the sidebar's list, a playlist's
page, and what changes them.

- **The sidebar's Playlists** (`PlaylistList`, R6.3): each playlist by name with its count of
  entries; **+** makes "New playlist", opens it and selects its name for editing (R8.3); a
  playlist's right-click menu renames it (its name edited in place), duplicates it, or deletes it
  after asking (R8.4, R6.8).
- **A playlist's page** (`PlaylistPage`, `EntriesModel`, R8.2): a mosaic of four of its covers,
  its name, its count, length, file and whether it names its songs by relative paths; Play,
  Shuffle and Export…; then its entries, each with its number, cover, title and artist, album,
  genre, rating and length, a drag handle for reordering (R8.5's, the next piece's). An entry no
  song is at shows dimmed with "Missing" and the path it names, and Find (R8.7). Its rows are
  selected as a list of songs' are (R2.6); Delete, or Remove from playlist, takes the entries
  selected out without asking (R8.6).
- **What changes them** (`Playlists`): + and New playlist from selection (R8.3), Add to playlist
  in the selection bars and menus, renaming, duplicating and deleting (R8.4), removing entries
  (R8.6), Find and its choice (R8.7, from the page or Needs attention), and Export… (R8.8), each
  run on a thread of its own through musikata_core.playlists.Store, the views read again after,
  and a message saying what was done (R6.7).

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

if TYPE_CHECKING:
    from .bridges import Library

log = logging.getLogger(__name__)

NOT_THERE = "Playlists can't be changed while the music folder isn't available"  # R2.10
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


def kicker_text(kind: str) -> str:
    """Over a playlist's name (P01): Playlist · M3U8."""
    return f"Playlist · {kind.upper()}"


def note_of(path: str | None) -> str:
    """What a missing entry says before the path it names (R8.7): Missing, or, for a file
    outside the root, which can't be played from where it is (R12.5), Not in your music
    folder."""
    return MISSING if path is not None else OUTSIDE


def songs_text(n: int) -> str:
    return plural(n, "song")


def added_text(n: int, name: str) -> str:
    return f"Added {songs_text(n)} to {name}" if n else f"Nothing was added to {name}"


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


# ---------- the sidebar's list (R6.3) ----------


class PlaylistList(QAbstractListModel):
    """The sidebar's Playlists (R6.3): every playlist by name (R2.13's sort key), each with its id
    (playlistId), name and count of entries. Read whole: a library has tens of playlists, not
    thousands."""

    roles = ("playlistId", "name", "count")
    countChanged = Signal()

    def __init__(self, read: Callable[[], sqlite3.Connection], parent: QObject | None = None):
        super().__init__(parent)
        self._read = read
        self._rows: list[dict[str, Any]] = []

    def refresh(self) -> None:
        """The playlists read again (after a scan or a change)."""
        rows = [
            {"playlistId": int(i), "name": str(n), "count": f"{int(k):,}"}
            for i, n, k in self._read().execute(
                "SELECT id, name, (SELECT COUNT(*) FROM playlist_entry WHERE playlist_id ="
                " playlist.id) FROM playlist ORDER BY name_key, path"
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
    the line under it (`detail_text`), and its entries (`EntriesModel`). Its id is the
    playlist's."""

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
            " playlist_id = playlist.id) FROM playlist WHERE id = ?",
            (playlist,),
        ).fetchone()
        if r is None:
            return False
        name, path, kind, absolute, entries = r
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
        if search is not None:
            self._songs.search_next(search)
        if playlist == self._id:
            self._songs.refresh()
        else:
            self._id = playlist
            self._songs.clearSelection()
            self._songs.for_playlist(playlist)
        self._songs.source = str(name)
        self._values = {
            "name": str(name),
            "path": str(path),
            "kicker": kicker_text(str(kind)),
            "detail": detail_text(
                int(entries), float(seconds or 0), str(path), int(absolute), int(missing or 0)
            ),  # fmt: skip
            "tiles": tiles(thumbs),
            "empty": "" if entries else "No songs yet: add some with Add to playlist",
            "playable": int(entries) > int(missing or 0),
        }
        self.changed.emit()
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
    songs = QtProperty(QObject, lambda self: self._songs, constant=True)
    actions = QtProperty(list, lambda self: ACTIONS, constant=True)


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
        trash: art.Trash = art.to_trash,
        available: Callable[[], bool] = lambda: True,
        home: str = "",
        executor: Executor | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store, self._read, self._say_to = store, read, say
        self._library: Library | None = library
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
        songs = songs_of(model, row)
        if not songs or not self._can():
            return
        store = self._store

        def then(done: core.Changed) -> None:
            self._reload()
            self._say(added_text(done.count, done.name))

        self._run(lambda: store.add(playlist, songs), then)

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

    def _remove(self, model: QObject, entries: list[int]) -> None:
        if not isinstance(model, EntriesModel) or not entries or not self._can():
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
