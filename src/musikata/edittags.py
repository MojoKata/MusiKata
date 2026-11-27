"""The Edit tags panel in the running app (R4.2 to R4.4, R4.6 to R4.8; L03-songs-bulk-edit): a
panel docked on the right that edits the songs of an album, a song, a selection or the folders
selected (R2.9.6), and follows the selection of the list it was opened from, asking first when
changes aren't saved. It shows the cover and what is edited, a field for each tag (each shared,
or mixed with the values in use, tags.edit), the fields changed, "3 fields will change on 4
songs", Revert and Save; for one song, the file and the tags kept without showing (R4.8).

The songs' tags are read from the index, and one song's kept tags from its file, off the GUI
thread (the search thread, models.Searcher), as are the values Artist, Album artist, Album and
Genre suggest (R4.6, search.suggestions). A save is a batch (tags.Batch, R4.7) on a thread of
its own: each file in turn, progress for more than a few, cancellable between files, the files
that failed listed with why and a Retry, the others saved; it is kept in the change history and
followed by its message with Undo (history.ChangeHistory, R4.9, R6.7), and the rows of the files
written updated in the index (Library.saved). MP3s are written in the root's ID3 version and
modification times kept as its settings say (settings.root_tags, R4.7.1, R4.7.2).

What the panel says is decided here as plain data and text, tested without a window; which
songs change, and how, is tags.edit's. The bulk tools of R4.5 are its ⋯ menu (`tools`): a tool
opens its dialog (bulktools.BulkTool, `tool`) over the songs edited, in the list's order, and its
save is saved here as the panel's own are, named for the tool in the change history."""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import albums, scanner, search, settings
from musikata_core.tags import Batch, Failed, Job, Outcome, TagReadError, Tags, Written, edit, tools
from musikata_core.tags import kept as kept_tags
from musikata_core.tags import save as save_tags

from .bridges import shown_path
from .bulktools import BulkTool, menu_of
from .folders import FolderModel
from .history import LABELS, ChangeHistory
from .models import KINDS, Searcher, SongsModel, cover_url, plural, size_text, time_text, title_of

log = logging.getLogger(__name__)

MIXED = "Mixed: keep each song's own"  # R4.3
SORTS = ("artistsort", "albumartistsort", "albumsort")
SORT_HINT = "Empty: the name, without The, A or An"  # R2.13's rule for an empty sort name
FEW = 5  # a save of more files than this shows its progress (R4.7)
SUGGESTS = ("artist", "albumartist", "album", "genres")  # R4.6
FIELD_LABELS = {**LABELS, "track": "Track", "disc": "Disc"}
CHUNK = 500  # ids read at a time
VALUES = 30  # the values in use a mixed field's ▾ lists, most used first
NO_SONGS = "Select songs to edit their tags"


# ---------- what is edited ----------


@dataclass(frozen=True)
class Song:
    """A song the panel edits, as the index has it: its id, path under the root, tags, and what
    R4.8 shows of its file."""

    id: int
    path: str
    tags: Tags
    kind: str | None = None
    length: float | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    size: int | None = None
    album_id: int | None = None
    folder: str | None = None


TAG_COLUMNS = ("title", "artist", "album", "albumartist", "track", "tracktotal", "disc",
               "disctotal", "year", "date", "composer", "comment", "compilation", "rating",
               "artistsort", "albumartistsort", "albumsort", "has_cover")  # fmt: skip
SONG_COLUMNS = ("id", "path", "kind", "length", "bitrate", "sample_rate", "size", "album_id",
                "folder", *TAG_COLUMNS)  # fmt: skip


def read_songs(c: sqlite3.Connection, ids: Sequence[int]) -> list[Song]:
    """The songs of `ids` that the index has, in that order, with their genres."""
    found: dict[int, Song] = {}
    for i in range(0, len(ids), CHUNK):
        part = tuple(ids[i : i + CHUNK])
        marks = ", ".join("?" * len(part))
        genres: dict[int, list[str]] = {}
        for song, genre in c.execute(
            f"SELECT song_id, genre FROM song_genre WHERE song_id IN ({marks})"
            " ORDER BY song_id, position",
            part,
        ):
            genres.setdefault(song, []).append(genre)
        for r in c.execute(
            f"SELECT {', '.join(SONG_COLUMNS)} FROM song WHERE id IN ({marks})", part
        ):
            row = dict(zip(SONG_COLUMNS, r, strict=True))
            values = {k: row[k] for k in TAG_COLUMNS}
            values["compilation"] = bool(values["compilation"])
            values["has_cover"] = bool(values["has_cover"])
            tags = Tags(**values, genres=tuple(genres.get(row["id"], ())))
            found[row["id"]] = Song(
                row["id"], row["path"], tags, row["kind"], row["length"], row["bitrate"],
                row["sample_rate"], row["size"], row["album_id"], row["folder"],
            )  # fmt: skip
    return [found[i] for i in ids if i in found]


def art_of(c: sqlite3.Connection, songs: Sequence[Song]) -> dict[str, Any]:
    """The cover the panel shows (the album most of the songs are on, else the first song's
    folder) and its chip: the songs' own art, embedded in all, some or none of them, or only in
    their folder (R5.1)."""
    n = len(songs)
    if not n:
        return {"cover": "", "chip": {}}
    albums = Counter(s.album_id for s in songs if s.album_id is not None)
    thumb = image = None
    if albums:
        r = c.execute(
            "SELECT thumb, folder_image FROM album WHERE id = ?", (albums.most_common(1)[0][0],)
        ).fetchone()
        thumb, image = r if r else (None, None)
    if thumb is None and songs[0].folder is not None:
        r = c.execute(
            "SELECT thumb, image FROM folder WHERE path = ?", (songs[0].folder,)
        ).fetchone()
        thumb, image = r if r else (None, None)
    embedded = sum(1 for s in songs if s.tags.has_cover)
    return {"cover": cover_url(thumb), "chip": art_chip(embedded, n, image is not None)}


def art_chip(embedded: int, songs: int, in_folder: bool) -> dict[str, str]:
    """The cover's chip: "Art in all 4" when every song has its art embedded; else, as a
    warning, how many have it, "Art in folder only", or "No cover yet"."""
    if embedded and embedded == songs:
        return {"text": "Art in this song" if songs == 1 else f"Art in all {songs:,}", "tone": "ok"}
    if embedded:
        return {"text": f"Art in {embedded:,} of {songs:,}", "tone": "warn"}
    return {"text": "Art in folder only" if in_folder else "No cover yet", "tone": "warn"}


def load(
    c: sqlite3.Connection, ids: Sequence[int], root: str
) -> tuple[list[Song], dict[str, Any], list[tuple[str, str]] | str]:
    """On the search thread: the songs of `ids`, their cover and chip, and for one song the tags
    its file keeps without showing (R4.8), or why they couldn't be read."""
    songs = read_songs(c, ids)
    kept: list[tuple[str, str]] | str = []
    if len(songs) == 1:
        try:
            kept = kept_tags(scanner.full_path(root, songs[0].path))
        except TagReadError as e:
            kept = f"Its file couldn't be read: {e}"
    return songs, art_of(c, songs), kept


# ---------- what the panel says ----------


def songs_text(n: int) -> str:
    return plural(n, "song")


def what_text(folders: int, files: int) -> str:
    """What the Folders view's selection is, as the panel's heading says it (L07-folders-list):
    1 folder, 1 file; 2 folders; 3 files."""
    parts = ([plural(folders, "folder")] if folders else []) + (
        [plural(files, "file")] if files or not folders else []
    )
    return ", ".join(parts)


def _most(values: Sequence[str | None], n: int) -> str | None:
    """The value at least half of `n` songs share; None when none does."""
    counts = Counter(v for v in values if v)
    if not counts:
        return None
    value, count = counts.most_common(1)[0]
    return value if count * 2 >= n else None


def heading_of(songs: Sequence[Song], what: str) -> tuple[str, str]:
    """The panel's title and the line under it (R4.2): for one song its title, and its artist and
    album; for several, the album most of them are on and the artist, with what is edited
    ("Tide Tables", "Lumen Drift · 4 songs"); with no album they share, what is edited."""
    if not songs:
        return "", ""
    n = len(songs)
    if n == 1:
        t = songs[0].tags
        line = " · ".join(v for v in (t.artist, t.album) if v)
        return title_of(t.title, songs[0].path), line
    album = _most([s.tags.album for s in songs], n)
    artist = _most([s.tags.albumartist or s.tags.artist for s in songs], n)
    if album is None:
        return what, artist or ""
    return album, " · ".join(v for v in (artist, what) if v)


def change_line(fields: int, songs: int) -> str:
    """R4.4's line: 3 fields will change on 4 songs; "" when nothing will."""
    if not fields or not songs:
        return ""
    return f"{plural(fields, 'field')} will change on {songs_text(songs)}"


def save_label(files: int) -> str:
    """R4.4's button: Save to 4 files; Save when nothing will change."""
    return f"Save to {plural(files, 'file')}" if files else "Save"


def labels_text(names: Sequence[str]) -> str:
    """Fields named in a sentence: Artist; Artist and Year; Artist, Genre and Year."""
    labels = [FIELD_LABELS.get(n, n) for n in names]
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def description_of(fields: Sequence[str], songs: int) -> str:
    """What a save was, for the Change history (R4.9): Artist, Genre and Year on 4 songs."""
    return f"{labels_text(fields)} on {songs_text(songs)}"


def problem_line(problems: Mapping[str, str]) -> str:
    """Why the edits can't be saved: the first field whose text can't be written, and why."""
    for name in edit.FIELDS:
        if name in problems:
            return f"{FIELD_LABELS.get(name, name)}: {problems[name]}"
    return ""


def unsaved_text(fields: int, songs: int) -> str:
    """R4.2's question, when the selection changes or the panel closes with changes not saved."""
    return f"Your changes to {plural(fields, 'field')} on {songs_text(songs)} aren't saved"


def progress_text(done: int, total: int) -> str:
    """A save's progress (R4.7): Saving 12 of 40 files…"""
    return f"Saving {done:,} of {plural(total, 'file')}…"


def failed_text(failed: int) -> str:
    """The heading of the files a save couldn't write (R4.7)."""
    return "1 file wasn't saved" if failed == 1 else f"{failed:,} files weren't saved"


def failed_rows(failed: Sequence[Failed], root: str) -> list[dict[str, str]]:
    """The files a save couldn't write, each with why (R4.7): its name, its folder under the root,
    and the reason."""
    out = []
    for f in failed:
        rel = scanner.path_under(root, f.job.path) or f.job.path
        folder, _, name = rel.rpartition("/")
        out.append({"file": name, "folder": folder, "why": f.why})
    return out


def rate_text(hz: int | None) -> str:
    return f"{hz / 1000:g} kHz" if hz else "—"


def details_of(song: Song, root: str, home: str) -> list[dict[str, str]]:
    """R4.8: one song's file, read only: its path, kind, length, bit rate, sample rate and
    size."""
    rows = [
        ("Path", shown_path(scanner.full_path(root, song.path), home)),
        ("Kind", KINDS.get(song.kind or "", song.kind or "—")),
        ("Length", time_text(song.length) or "—"),
        ("Bit rate", f"{round(song.bitrate / 1000):,} kbps" if song.bitrate else "—"),
        ("Sample rate", rate_text(song.sample_rate)),
        ("Size", size_text(song.size) if song.size is not None else "—"),
    ]
    return [{"label": k, "value": v} for k, v in rows]


def view_field(
    field: edit.Field, typed: str | None, changed: bool, problem: str | None
) -> dict[str, Any]:
    """A field as QML lays it out: its label, the text it holds (what was typed, else what the
    songs share), the grey "Mixed" placeholder (R4.3), whether it is changed (R4.4: outlined, a
    dot) or can't be written, the values in use for its ▾, and whether it suggests (R4.6)."""
    text = field.text if typed is None else typed
    return {
        "name": field.name,
        "label": FIELD_LABELS.get(field.name, field.name),
        "text": text,
        "placeholder": MIXED if field.mixed else SORT_HINT if field.name in SORTS else "",
        "mixed": field.mixed,
        "changed": changed,
        "problem": problem or "",
        "values": [
            {"text": v, "count": n, "line": f"{v} · {songs_text(n)}"}
            for v, n in field.values[:VALUES]
        ],
        "suggests": field.name in SUGGESTS,
    }


def rating_of(field: Mapping[str, Any] | None, typed: str | None) -> dict[str, Any]:
    """The rating as the panel shows it (R10.1, R10.2): its stars, "Mixed: keep each song's own"
    while the songs' differ and no star was clicked (R4.3), and whether it will change (R4.4)."""
    if not field:
        return {"stars": 0, "mixed": False, "changed": False}
    text = typed if typed is not None else str(field["text"])
    return {
        "stars": int(text) if text.isdigit() else 0,
        "mixed": bool(field["mixed"]) and typed is None,
        "changed": bool(field["changed"]),
    }


def is_edit(field: edit.Field, typed: str) -> bool:
    """Whether what is typed into a field is an edit: not what it showed, and for a mixed field,
    not left empty (R4.3)."""
    if field.mixed and not typed.strip():
        return False
    return typed != field.text


def with_suggestion(name: str, typed: str, value: str) -> str:
    """A field's text once a suggestion is picked: the value, or for genres, the genre being
    typed after the last ";" replaced by it."""
    if name != "genres" or ";" not in typed:
        return value
    return typed.rsplit(";", 1)[0] + "; " + value


def being_typed(name: str, typed: str) -> str:
    """What a field suggests for: its text, or for genres the one after the last ";"."""
    return typed.rsplit(";", 1)[-1] if name == "genres" else typed


# ---------- the bridge ----------


class EditTags(QObject):
    """The Edit tags panel as the window sees it. `read` gives this thread's reading connection to
    the root's index; `tags_settings` are the root's (settings.root_tags): the ID3 version and
    modification times a save writes with (R4.7.1, R4.7.2). `history` keeps each save and says
    its message (R4.9, R6.7); `saved` is told of the files written (Library.saved), on this
    thread. `write` writes one file (safe.save with those settings, unless a test's); a save runs
    on `executor` (its own thread when None), the reading on `searcher`'s thread. `available`
    says whether the root is there (R2.10): saving waits until it is."""

    changed = Signal()  # what is edited: the songs, the heading, the cover, open or not
    fieldsChanged = Signal()  # the fields, the line, Save
    savingChanged = Signal()  # the progress, the files that failed
    questionChanged = Signal()
    suggestionsChanged = Signal()
    _progressed = Signal(int, int, str)  # from the save's thread
    _done = Signal(object)  # an Outcome, from the save's thread

    def __init__(
        self,
        root: str,
        read: Callable[[], sqlite3.Connection],
        tags_settings: settings.RootTags,
        history: ChangeHistory | None = None,
        saved: Callable[[Sequence[Written]], object] | None = None,
        write: Callable[[Job], Written] | None = None,
        executor: Executor | None = None,
        home: str = "",
        available: Callable[[], bool] = lambda: True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._read, self._settings, self._home = root, read, tags_settings, home
        self._history, self._saved, self._available = history, saved, available
        self._write = write  # None: _save_one (never stored bound: a cycle, A1.3)
        self._executor = executor
        self._searcher = Searcher(self)
        self._open = False
        self._source: QObject | None = None  # the list whose selection it follows
        self._ids: list[int] = []
        self._what = ""
        self._ticket = 0
        self._loading = False
        self._songs: list[Song] = []
        self._art: dict[str, Any] = {"cover": "", "chip": {}}
        self._kept: list[tuple[str, str]] | str = []
        self._shown: dict[str, edit.Field] = edit.fields_of([])
        self._edits: dict[str, str] = {}
        self._then_edits: dict[str, str] = {}  # the tour's, once its songs are read
        self._plan = edit.Plan((), ())
        self._problems: dict[str, str] = {}
        self._fields: dict[str, Any] = {}  # what QML shows of each field, made once a change
        self._more = False  # More fields, open once opened (R4.2)
        self._pending: tuple[list[int], str] | None = None  # what to edit once asked or saved
        self._closing = False  # close once asked or saved
        self._question: dict[str, Any] = {}
        self._batch: Batch[Written] | None = None
        self._progress = (0, 0)
        self._failed: list[Failed] = []
        self._suggest_for = ""
        self._suggestions: list[str] = []
        self._closed = False
        self._bulk = BulkTool(root, self)  # R4.5's tool open, if one is
        self._then_tool: dict[str, Any] | None = None  # the tour's, once its songs are read
        self._progressed.connect(self._on_progress)
        self._done.connect(self._on_done)
        self._bulk.saved.connect(self._on_tool_saved)

    # ---------- what it edits (R4.2) ----------

    def edit_songs(self, ids: Sequence[int], what: str = "", source: QObject | None = None) -> None:
        """Opens the panel on the songs of `ids` (`what` they are, "4 songs" when not said),
        following from now on the selection of `source`, a list of songs or Folders' model."""
        self._follow(source)
        self._open = True
        if self._history is not None:
            self._history.hide()  # the panel shows under Change history: closed, so it shows
        self.changed.emit()
        self._retarget(list(ids), what or songs_text(len(ids)))

    @Slot(QObject)
    def editSelection(self, model: QObject) -> None:  # noqa: N802
        """Edit tags on a selection (the selection bar, Ctrl+E): what `model` has selected."""
        ids, what = target_of(model)
        self.edit_songs(ids, what, model)

    @Slot(QObject, int)
    def editRow(self, model: QObject, row: int) -> None:  # noqa: N802
        """Edit tags in a row's right-click menu: the selection when the row is in it, else the
        row's song, or the songs beneath its folder (R2.9.6)."""
        ids, what = target_at(model, row)
        self.edit_songs(ids, what, model)

    @Slot(int, QObject)
    def editAlbum(self, album_id: int, model: QObject) -> None:  # noqa: N802
        """An album's Edit tags (L02-album): its songs, in its order; then the selection of its
        page's list."""
        c = self._read()
        ids = [r[0] for r in c.execute(
            f"SELECT id FROM song WHERE album_id = ? ORDER BY {albums.ALBUM_ORDER}", (album_id,)
        )]  # fmt: skip
        self.edit_songs(ids, songs_text(len(ids)), model)

    @Slot(QObject)
    def editFolder(self, folders: QObject) -> None:  # noqa: N802
        """A folder of songs' Edit tags (R2.9.7): every song in it, in its list's order (by name);
        then the selection in it."""
        model = folders.property("model")
        c = self._read()
        path = str(folders.property("path"))
        ids = [r[0] for r in c.execute(
            "SELECT id FROM song WHERE folder = ? ORDER BY name_key, path", (path,)
        )]  # fmt: skip
        self.edit_songs(ids, songs_text(len(ids)), model)

    @Slot(QObject)
    def editCurrent(self, library: QObject) -> None:  # noqa: N802
        """Ctrl+E / ⌘E (R4.2, R6.9): the open view's selection; on an album's page with nothing
        selected the album, and in a folder of songs the folder (R2.9.7). A view with no songs
        listed opens the panel saying to select some."""
        view = library.property("view")
        if view == "album":
            page = library.property("album")
            model = page.property("songs")
            if not model.property("selectionCount"):
                self.editAlbum(int(page.property("id")), model)
                return
        elif view == "folders":
            folders = library.property("folders")
            model = folders.property("model")
            if not folders.property("selectionCount") and folders.property("songsMode"):
                self.editFolder(folders)
                return
        else:
            model = {"songs": library.property("songs"),
                     "artist": library.property("artist").property("others")}.get(view)  # fmt: skip
        if model is None:
            self.edit_songs([], "")
            return
        self.editSelection(model)

    @Slot(str)
    def runTool(self, name: str) -> None:  # noqa: N802
        """A bulk tool of the ⋯ menu (R4.5), by name: its dialog opens over the songs edited, in
        the list's order, showing what it would do; one that can't be used now does nothing."""
        self.open_tool(name)

    def open_tool(self, name: str, options: dict[str, Any] | None = None) -> None:
        """Tool `name` opened with `options` set (BulkTool.open), unless it can't be used now."""
        item = next((t for t in self._menu() if t["name"] == name), None)
        if item is None or item["later"] or not self._songs:
            log.info("bulk tool %r not opened: %s", name, item["later"] if item else "no such tool")
            return
        songs = [tools.Song(scanner.full_path(self._root, s.path), s.tags) for s in self._songs]
        undoable = self._history is not None and self._settings.history
        self._bulk.open(name, songs, options, undoable)

    def _menu(self) -> list[dict[str, str]]:
        menu = menu_of(len(self._songs), self.unsaved(), self._batch is not None)
        if not self._available():
            for t in menu:
                t["later"] = t["later"] or "Saving waits until the music folder is back"
        return menu

    @Slot(object, str)
    def _on_tool_saved(self, jobs: list[Job], description: str) -> None:
        """A bulk tool's Save (R3.8): its files saved as the panel saves (R4.7), one entry in the
        change history named for the tool (R4.9), and its dialog closed; while the root isn't
        there (R2.10) it stays open, saving nothing."""
        if self._batch is not None or not self._available():
            log.warning("a bulk tool's save wasn't started: a save goes on, or the root is gone")
            return
        self._bulk.close()
        self._start(jobs, description)

    def _follow(self, source: QObject | None) -> None:
        if source is self._source:
            return
        if self._source is not None:
            self._source.selectionChanged.disconnect(self._on_selection)  # type: ignore[attr-defined]
        self._source = source
        if source is not None:
            source.selectionChanged.connect(self._on_selection)  # type: ignore[attr-defined]

    @Slot()
    def _on_selection(self) -> None:
        """The list beside it was selected anew: the panel edits that (R4.2), asking first when
        changes aren't saved; an empty selection leaves it as it is."""
        if not self._open or self._source is None:
            return
        ids, what = target_of(self._source)
        if ids:
            self._retarget(ids, what)

    def _retarget(self, ids: list[int], what: str) -> None:
        if ids == self._ids and what == self._what and not self._loading:
            return
        if self._batch is not None:
            self._pending = (ids, what)
            return
        if self.unsaved():
            self._pending = (ids, what)
            self._ask()
            return
        self._load(ids, what)

    def _load(self, ids: list[int], what: str) -> None:
        self._ids, self._what = ids, what
        self._edits = {}
        self._bulk.close()  # a tool's songs were those edited until now
        self._ticket += 1
        ticket, root, read = self._ticket, self._root, self._read
        self._loading = True
        self.changed.emit()
        if not ids:
            self._on_loaded((ticket, ([], {"cover": "", "chip": {}}, [])))
            return
        self._searcher.submit("load", lambda: (ticket, load(read(), ids, root)), self._on_loaded)

    def _on_loaded(self, result: tuple[int, tuple[Any, ...]] | None) -> None:
        if result is None:  # the read failed; the log says why
            self._loading = False
            self.changed.emit()
            return
        ticket, (songs, art, kept) = result
        if ticket != self._ticket or self._closed:
            return
        self._songs, self._art, self._kept = songs, art, kept
        self._shown = edit.fields_of([s.tags for s in songs])
        self._edits = {}
        self._loading = False
        self._then()

    def _then(self) -> None:
        """The tour's typing and tool, once the songs it shows are read."""
        if self._songs:
            for name, text in self._then_edits.items():
                self._set(name, text)
            self._then_edits = {}
        self._replan()
        self.changed.emit()
        if self._songs and self._then_tool is not None:
            then, self._then_tool = self._then_tool, None
            self.open_tool(then.pop("name"), then)

    @Slot()
    def refresh(self) -> None:
        """The index's rows changed (a scan, a save, an undo; Library.reloaded): the songs it
        edits read again, unless there are changes not saved, which it keeps as they are."""
        busy = self._loading or self._batch is not None or self.unsaved() or self._question
        if self._open and self._ids and not busy:
            self._load(self._ids, self._what)

    # ---------- editing (R4.3, R4.4) ----------

    def unsaved(self) -> bool:
        """Whether there are edits not saved: changes, or text that can't be written."""
        return bool(self._plan.jobs or self._problems)

    def _set(self, name: str, text: str) -> None:
        field = self._shown.get(name)
        if field is None:
            raise ValueError(f"no such field: {name}")
        if is_edit(field, text):
            self._edits[name] = text
        else:
            self._edits.pop(name, None)

    @Slot(str, str)
    def setText(self, name: str, text: str) -> None:  # noqa: N802
        """What is typed into field `name`: on a mixed field, the value for every song (R4.3)."""
        self._set(name, text)
        self._replan()

    @Slot(int)
    def rate(self, star: int) -> None:
        """A star of the rating clicked (R10.2): the songs' rating set to it, or cleared when it
        is the rating shown already; saved with the rest."""
        field = self._shown["rating"]
        shown = self._edits.get("rating", "" if field.mixed else field.text)
        self.setText("rating", "0" if shown == str(star) else str(star))

    @Slot(str, str)
    def pick(self, name: str, value: str) -> None:
        """A value picked from a mixed field's ▾ (R4.3), set on every song."""
        self.setText(name, value)

    @Slot(str, str)
    def pickSuggestion(self, name: str, value: str) -> None:  # noqa: N802
        """A suggestion picked (R4.6): the field holds it (genres: in place of the one typed)."""
        typed = self._edits.get(name, self._shown[name].text)
        self.setText(name, with_suggestion(name, typed, value))
        self.clearSuggestions()

    @Slot()
    def revert(self) -> None:
        """R4.4's Revert: every change cleared."""
        self._edits = {}
        self._replan()

    @Slot()
    def openMore(self) -> None:  # noqa: N802
        """More fields opened (R4.2): it stays open from now on."""
        if not self._more:
            self._more = True
            self.fieldsChanged.emit()

    def _replan(self) -> None:
        self._problems = edit.problems(self._edits)
        songs = [(scanner.full_path(self._root, s.path), s.tags) for s in self._songs]
        self._plan = edit.plan(songs, self._edits, self._shown)
        changed = set(self._plan.fields) | set(self._problems)
        self._fields = {
            name: view_field(field, self._edits.get(name), name in changed,
                             self._problems.get(name))
            for name, field in self._shown.items()
        }  # fmt: skip
        self.fieldsChanged.emit()

    # ---------- suggesting (R4.6) ----------

    @Slot(str, str)
    def suggest(self, name: str, typed: str) -> None:
        """What field `name` suggests as `typed` is typed: the library's values, read on the
        search thread; the newest typing wins."""
        if name not in SUGGESTS:
            return
        self._suggest_for = name
        read, word = self._read, being_typed(name, typed)

        def then(found: list[str] | None) -> None:
            if self._suggest_for == name and not self._closed:
                self._suggestions = found or []
                self.suggestionsChanged.emit()

        self._searcher.submit("suggest", lambda: search.suggestions(read(), name, word), then)

    @Slot()
    def clearSuggestions(self) -> None:  # noqa: N802
        self._suggest_for = ""
        if self._suggestions:
            self._suggestions = []
            self.suggestionsChanged.emit()

    # ---------- saving (R4.7) ----------

    def _save_one(self, job: Job) -> Written:
        s = self._settings
        return save_tags(
            job.path, job.changes, audio_hash=scanner.audio_hash, id3_version=s.id3_version,
            keep_mtime=s.keep_modified_times, rating_scale=s.rating_scale,
        )  # fmt: skip

    @Slot()
    def save(self) -> None:
        """Save to N files (R4.4, R4.7): the changes written, file by file, as one entry in the
        change history."""
        if self._batch is not None or not self._plan.jobs or self._problems:
            return
        if not self._available():
            return
        jobs = list(self._plan.jobs)
        self._start(jobs, description_of(self._plan.fields, len(jobs)))

    @Slot()
    def retry(self) -> None:
        """R4.7's Retry: the files that failed, written again."""
        if self._batch is not None or not self._failed:
            return
        jobs = [f.job for f in self._failed]
        self._start(jobs, description_of(sorted_fields(jobs), len(jobs)))

    def _start(self, jobs: list[Job], description: str) -> None:
        record = self._history.recording() if self._history is not None else None
        write = self._write or self._save_one
        batch: Batch[Written] = Batch(
            jobs, write, self._progressed.emit, record=record, description=description
        )
        self._batch, self._progress, self._failed = batch, (0, len(jobs)), []
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="edit tags")
        self.savingChanged.emit()
        self.fieldsChanged.emit()
        self._executor.submit(self._run, batch, jobs)

    def _run(self, batch: Batch[Written], jobs: list[Job]) -> None:
        try:
            out = batch.run()
        except Exception as e:  # noqa: BLE001  (the batch fails its files, never itself; logged)
            log.exception("the save failed")
            out = Outcome(failed=[Failed(j, f"it wasn't saved: {e}") for j in jobs])
        self._done.emit(out)

    @Slot()
    def cancel(self) -> None:
        """Cancel (R4.7): the save stops before its next file."""
        if self._batch is not None:
            self._batch.cancel()

    @Slot(int, int, str)
    def _on_progress(self, done: int, total: int, _path: str) -> None:
        self._progress = (done, total)
        self.savingChanged.emit()

    @Slot(object)
    def _on_done(self, out: Outcome[Written]) -> None:
        self._batch = None
        self._failed = list(out.failed)
        if out.saved and self._saved is not None:
            self._saved(out.saved)  # their rows (Library.saved)
        written = {w.path: w.tags for w in out.saved}
        if written:  # the songs as they now read: the edits that changed them done with
            self._songs = [
                replace(s, tags=written.get(scanner.full_path(self._root, s.path), s.tags))
                for s in self._songs
            ]
            self._shown = edit.fields_of([s.tags for s in self._songs])
            for name, typed in list(self._edits.items()):
                self._set(name, typed)
        self._replan()
        if self._history is not None:
            self._history.after_save(out)
        self.savingChanged.emit()
        self.changed.emit()
        self._after()

    def _after(self) -> None:
        """What waited on the save or the question: closing, or other songs to edit."""
        if self._closing:
            self._closing = False
            self._pending = None
            self._shut()
        elif self._pending is not None:
            ids, what = self._pending
            self._pending = None
            self._load(ids, what)

    @Slot()
    def dismissFailed(self) -> None:  # noqa: N802
        self._failed = []
        self.savingChanged.emit()

    # ---------- asking (R4.2) and closing ----------

    def _ask(self) -> None:
        fields = len(self._plan.fields) or len(self._problems)
        self._question = {"text": unsaved_text(fields, len(self._plan.jobs) or len(self._songs))}
        self.questionChanged.emit()

    @Slot(str)
    def answer(self, choice: str) -> None:
        """The question's answer: "save" the changes first, or "discard" them; then the panel
        edits the new selection, or closes."""
        if not self._question:
            return
        self._question = {}
        self.questionChanged.emit()
        if choice == "save" and self._plan.jobs and not self._problems:
            self.save()
            return
        self._edits = {}
        self._replan()
        self._after()

    @Slot()
    def hide(self) -> None:
        """× or Esc: the panel closes, asking first when changes aren't saved."""
        if not self._open:
            return
        if self._batch is not None:
            self._closing = True
            return
        if self.unsaved():
            self._closing = True
            self._ask()
            return
        self._shut()

    def _shut(self) -> None:
        self._open = False
        self._bulk.close()
        self._ids, self._what = [], ""
        self._follow(None)
        self._edits, self._failed, self._question = {}, [], {}
        self._replan()
        self.clearSuggestions()
        self.changed.emit()
        self.questionChanged.emit()
        self.savingChanged.emit()

    def go(self, step: Mapping[str, Any], library: QObject) -> None:
        """A tour's step (A1.6): {"edit": {field: text}} opens the panel as Ctrl+E does on the
        view the step shows, with those fields typed once its songs are read, and {"tool":
        {"name": …, option: value}} a bulk tool over them (R4.5); without "edit" the panel is
        closed."""
        edits = step.get("edit")
        self._bulk.close()
        if edits is None:
            if self._open:
                self._shut()
            return
        self._edits = {}  # an earlier step's typing, never asked about
        self._replan()
        self._then_edits = dict(edits)
        tool = step.get("tool")
        self._then_tool = dict(tool) if tool is not None else None
        self.editCurrent(library)
        if not self._loading:  # the songs it edits already: nothing to read first
            self._then()

    def close(self) -> None:
        """For closing the window: a save going on stops before its next file and is waited for;
        nothing starts after. What the threads held is let go (A1.3)."""
        self._closed = True
        self._bulk.close()
        if self._batch is not None:
            self._batch.cancel()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._batch = None
        self._searcher.wait()
        self._follow(None)
        self._saved = self._history = self._write = None
        self._available = _gone

    # ---------- what QML reads ----------

    def _get_fields(self) -> dict[str, Any]:
        return self._fields

    def _get_heading(self) -> str:
        return f"Edit tags · {songs_text(len(self._songs))}" if self._songs else "Edit tags"

    def _get_title(self) -> str:
        return heading_of(self._songs, self._what)[0]

    def _get_line(self) -> str:
        return heading_of(self._songs, self._what)[1]

    def _get_rating(self) -> dict[str, Any]:
        return rating_of(self._fields.get("rating"), self._edits.get("rating"))

    def _get_change_line(self) -> str:
        return problem_line(self._problems) or change_line(
            len(self._plan.fields), len(self._plan.jobs)
        )

    def _get_save_note(self) -> str:
        if not self._available():
            return "Saving waits until the music folder is back"
        return "A save is going on" if self._batch is not None else ""

    def _get_details(self) -> list[dict[str, str]]:
        if len(self._songs) != 1:
            return []
        return details_of(self._songs[0], self._root, self._home)

    def _get_kept(self) -> list[dict[str, str]]:
        if len(self._songs) != 1 or isinstance(self._kept, str):
            return []
        return [{"label": k, "value": v} for k, v in self._kept]

    def _get_kept_note(self) -> str:
        if len(self._songs) != 1:
            return ""
        if isinstance(self._kept, str):
            return self._kept
        return "" if self._kept else "None"

    def _get_progress(self) -> dict[str, Any]:
        done, total = self._progress
        if self._batch is None or total <= FEW:
            return {}
        return {"text": progress_text(done, total), "fraction": done / total}

    def _get_failed(self) -> dict[str, Any]:
        if not self._failed:
            return {}
        return {"title": failed_text(len(self._failed)),
                "rows": failed_rows(self._failed, self._root)}  # fmt: skip

    def _get_empty_text(self) -> str:
        return NO_SONGS if not self._songs and not self._loading else ""

    opened = QtProperty(bool, lambda self: self._open, notify=changed)
    loading = QtProperty(bool, lambda self: self._loading, notify=changed)
    count = QtProperty(int, lambda self: len(self._songs), notify=changed)
    heading = QtProperty(str, _get_heading, notify=changed)  # Edit tags · 4 songs
    title = QtProperty(str, _get_title, notify=changed)  # Tide Tables
    line = QtProperty(str, _get_line, notify=changed)  # Lumen Drift · 4 songs
    cover = QtProperty(str, lambda self: self._art["cover"], notify=changed)
    artChip = QtProperty(dict, lambda self: self._art["chip"], notify=changed)
    emptyText = QtProperty(str, _get_empty_text, notify=changed)
    rating = QtProperty(dict, _get_rating, notify=fieldsChanged)  # R10.2: set by its stars
    details = QtProperty(list, _get_details, notify=changed)  # one song's file (R4.8)
    kept = QtProperty(list, _get_kept, notify=changed)
    keptNote = QtProperty(str, _get_kept_note, notify=changed)
    fields = QtProperty(dict, _get_fields, notify=fieldsChanged)
    more = QtProperty(bool, lambda self: self._more, notify=fieldsChanged)
    changeLine = QtProperty(str, _get_change_line, notify=fieldsChanged)
    canSave = QtProperty(bool, lambda self: bool(self._plan.jobs) and not self._problems
                         and self._batch is None and self._available(),
                         notify=fieldsChanged)  # fmt: skip
    canRevert = QtProperty(bool, lambda self: bool(self._edits) and self._batch is None,
                           notify=fieldsChanged)  # fmt: skip
    saveLabel = QtProperty(str, lambda self: save_label(len(self._plan.jobs)), notify=fieldsChanged)
    saveNote = QtProperty(str, _get_save_note, notify=fieldsChanged)
    saving = QtProperty(bool, lambda self: self._batch is not None, notify=savingChanged)
    progress = QtProperty(dict, _get_progress, notify=savingChanged)  # {} for a few files
    failed = QtProperty(dict, _get_failed, notify=savingChanged)  # {} when none failed
    question = QtProperty(dict, lambda self: self._question, notify=questionChanged)
    suggestions = QtProperty(list, lambda self: self._suggestions, notify=suggestionsChanged)
    suggestFor = QtProperty(str, lambda self: self._suggest_for, notify=suggestionsChanged)
    tools = QtProperty(list, _menu, notify=fieldsChanged)  # R4.5's bulk tools, the ⋯ menu
    tool = QtProperty(QObject, lambda self: self._bulk, constant=True)  # the tool open
    ids = QtProperty(list, lambda self: list(self._ids), notify=changed)  # the songs edited


def _gone() -> bool:
    """A closed panel's root: never there to save to."""
    return False


def sorted_fields(jobs: Sequence[Job]) -> list[str]:
    """The panel's fields a retry's jobs change, in its order."""
    names = {n for j in jobs for n in j.changes}
    out = []
    for f in edit.FIELDS:
        parts = edit.PAIRS.get(f, (f,))
        if any(p in names for p in parts):
            out.append(f)
    return out


def target_of(model: QObject) -> tuple[list[int], str]:
    """What a list's selection stands for: its songs, and what they are ("4 songs"; Folders'
    "1 folder, 1 file", R2.9.6)."""
    if isinstance(model, FolderModel):
        folders, files = model.selected()
        return model.selected_songs(), what_text(len(folders), len(files))
    if isinstance(model, SongsModel):
        ids = model.selected_songs()
        return ids, songs_text(len(ids))
    return [], ""


def target_at(model: QObject, row: int) -> tuple[list[int], str]:
    """What a right click on row `row` stands for (R2.9.6, R7.2): the selection when the row is
    in it, else the row's song, or the songs beneath its folder."""
    if isinstance(model, FolderModel):
        if model.is_selected(row):
            return target_of(model)
        r = model.row(row)
        if r is None:
            return [], ""
        folder = int(r["kind"] == "folder")
        return model.songs_at(row), what_text(folder, 1 - folder)
    if isinstance(model, SongsModel):
        ids = model.songs_at(row)
        return ids, songs_text(len(ids))
    return [], ""
