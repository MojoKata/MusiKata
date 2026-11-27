"""Genres in the running app (R9, G01-genres): the Genres view's tiles, a genre's page, and the
genre's ⋯ menu's Rename… and Merge into…, and the banner of near duplicates with Review… and Not
now, each through R3.7's preview, saved through the batch as one entry in the change history.

- **The Genres view** (`GenresModel`, R9.1): a tile per genre with its name, its songs and albums,
  three of its covers and a tint, by number of songs or by name; worked out on the search thread
  (models.Searcher, A1.3) but for a small library's, every genre at once (a library has hundreds,
  not thousands), and filtered by the header's search to the genres of the songs it finds (R2.7).
- **A genre's page** (`GenrePage`): like an artist's, its covers, name and counts, the albums with
  a song of it, then its songs, both filtered by the header's search.
- **Renaming and merging** (`Genres`, R9.4): the dialog of the Edit tags panel's bulk tools
  (ToolDialog.qml) over the genre's songs, the new name typed or the genre chosen, the preview
  of the files that change (preview.Preview), and its save: a batch on a thread of its own with
  its progress in the dialog's footer, Cancel, the files that failed named with Retry, one entry
  in the change history and the message with Undo (R4.7, R4.9, R6.7).
- **Near duplicates** (R9.5): the banner offers the group of genres that look like one with the
  most songs (genres.near_duplicates, the user's own sames from the root's settings among them);
  Review… opens the merge's preview with the most used name chosen. Not now hides that group's
  banner for this run (the next group shows, if there is one): a nudge, not a dismissal, which is
  Needs attention's Ignore, kept in ignored.json (R2.8, A2.8).

What a tile, the banner and the dialog say is decided here as plain data and text, tested without a
window; which songs change, and how, is musikata_core.genres'."""

from __future__ import annotations

import logging
import sqlite3
import zlib
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
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

from musikata_core import genres, scanner, search
from musikata_core.genres import GenreNameError, Group, Tile
from musikata_core.tags import Batch, Failed, Job, Outcome, Tags, Written
from musikata_core.tags.tools import Planned, Song

from .history import GENRE, ChangeHistory
from .models import (
    SHORT,
    AlbumsModel,
    PagedModel,
    Searcher,
    SongsModel,
    artist_line,
    average_in,
    count_text,
    cover_url,
    plural,
    tiles,
)
from .preview import Preview, failed_text, footer_text, progress_text, save_text

log = logging.getLogger(__name__)

TONES = 8  # the tints a tile takes, Theme's palette in GenresView.qml
SORT_LABELS = {"songs": "Songs", "name": "Name"}  # R9.1's orders, as the header's sort names them
CHOICES = 24  # the genres Merge into… offers, the most used first, after the near duplicates
GENRE_SONGS = "id IN (SELECT song_id FROM song_genre WHERE genre = ?)"  # a genre's page's songs
NO_OTHER = "There's no other genre to merge it into"
ROLES = ("name", "line", "covers", "tone", "songs")


# ---------- what a tile and the banner say ----------


def tile_line(songs: int, albums: int) -> str:
    """What a tile says under the genre's name (G01-genres): 214 songs · 18 albums."""
    return " · ".join([plural(songs, "song")] + ([plural(albums, "album")] if albums else []))


def tone_of(name: str) -> int:
    """A tile's tint, one of TONES, the same for a genre wherever its tile is."""
    return zlib.crc32(name.casefold().encode()) % TONES


def tile_row(tile: Tile) -> dict[str, Any]:
    """A tile as QML shows it: the name, the line, its covers' addresses and its tint."""
    return {
        "name": tile.name,
        "line": tile_line(tile.songs, tile.albums),
        "covers": [cover_url(t) for t in tile.covers],
        "tone": tone_of(tile.name),
        "songs": tile.songs,
    }


def names_text(names: Sequence[str]) -> str:
    """Names in a sentence: Electronica; Electronica and electronic; A, B and C."""
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def banner_of(group: Group | None, files: int, undoable: bool = True) -> dict[str, str]:
    """R9.5's banner: "These look like one genre: Electronic (214), Electronica (17), electronic
    (6)", and what merging them would do; {} for no group."""
    if group is None:
        return {}
    counted = ", ".join(f"{n} ({c:,})" for n, c in zip(group.names, group.counts, strict=True))
    then = " Undo puts them back." if undoable else ""
    return {
        "title": f"These look like one genre: {counted}",
        "detail": f"Merging rewrites the genre tag in {plural(files, 'file')}.{then}",
    }


def rename_description(old: str, new: str, songs: int) -> str:
    """A rename's entry in the change history (R4.9): Genre Electronica renamed Electronic on 17
    songs."""
    return f"Genre {old} renamed {new} on {plural(songs, 'song')}"


def merge_description(names: Sequence[str], into: str, songs: int) -> str:
    """A merge's entry in the change history: Electronica and electronic merged into Electronic
    on 23 songs."""
    gone = [n for n in names if n != into]
    return f"{names_text(gone)} merged into {into} on {plural(songs, 'song')}"


def choices_of(
    name: str, counts: dict[str, int], groups: Sequence[Group], n: int = CHOICES
) -> list[str]:
    """The genres Merge into… offers for `name` (R9.4): those that look like it (R9.5) first, the
    most used of them first, then the others, the most used first, up to `n`; never itself."""
    near = next((g.names for g in groups if name in g.names), ())
    rest = sorted(counts, key=lambda g: (-counts[g], g.casefold(), g))
    return [g for g in dict.fromkeys([*near, *rest]) if g != name][:n]


def read_songs(c: sqlite3.Connection, root: str, names: Sequence[str]) -> list[Song]:
    """The songs with any of the genres `names`, in the order of their paths, each by its whole
    path with its genres as the index has them: what a rename or merge plans from."""
    ids = genres.songs_of(c, names)
    out: list[Song] = []
    for i in range(0, len(ids), 500):
        part = ids[i : i + 500]
        marks = ", ".join("?" * len(part))
        held: dict[int, list[str]] = {}
        for song, genre in c.execute(
            f"SELECT song_id, genre FROM song_genre WHERE song_id IN ({marks})"
            " ORDER BY song_id, position",
            part,
        ):
            held.setdefault(song, []).append(genre)
        paths = dict(c.execute(f"SELECT id, path FROM song WHERE id IN ({marks})", part))
        out += [
            Song(scanner.full_path(root, paths[s]), Tags(genres=tuple(held.get(s, ()))))
            for s in part
            if s in paths
        ]
    return out


# ---------- the Genres view (R9.1) ----------


class GenresModel(QAbstractListModel):
    """The Genres view's tiles (R9.1), worked out on the search thread (but a small library's):
    every genre, or those of the songs the header's search finds (R2.7), by number of songs or
    by name. It answers what
    Library asks of a list (models.PagedModel): its count and total, its search, whether its rows
    are still to come."""

    countChanged = Signal()

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        parent: QObject | None = None,
        searcher: Searcher | None = None,
    ) -> None:
        super().__init__(parent)
        self._read = read
        self._searcher = searcher if searcher is not None else Searcher(self)
        self._rows: list[dict[str, Any]] = []
        self._total = 0
        self._sort = "songs"
        self._search = ""
        self._query = search.Query()
        self._shown = ""
        self._pending = False
        self._generation = 0

    def set_search(self, text: str) -> None:
        """Only the genres of the songs that what the user typed finds (R2.7)."""
        self.search_next(text)
        self.reload()

    def search_next(self, text: str) -> None:
        self._search = text
        self._query = search.parse(text)

    def sort_by(self, sort: str) -> None:
        """By number of songs, the most first, or by name (R9.1)."""
        if sort not in genres.SORTS:
            raise ValueError(f"no such order of genres: {sort}")
        self._sort = sort
        self.reload()

    def order(self) -> str:
        return self._sort

    def reload(self) -> None:
        self._find()

    def refresh(self) -> None:
        """Read again where it is, after a scan or a save."""
        self._find()

    def _find(self) -> None:
        """The tiles, worked out on the search thread; those of a small library without a
        search, a matter of a millisecond or two, at once, as a short list's rows are
        (models.PagedModel)."""
        self._generation += 1
        generation, read, sort, text = self._generation, self._read, self._sort, self._search
        songs, params = search.condition(self._query) if self._query else ("", ())

        def work() -> tuple[list[Tile], int]:
            return genres.read_tiles(read(), sort, songs, params)

        if not text and int(read().execute("SELECT COUNT(*) FROM song").fetchone()[0]) <= SHORT:
            self._found(generation, text, work())
            return
        self._pending = True
        self._searcher.submit(
            ("genres", id(self)), work, lambda found: self._found(generation, text, found)
        )

    def _found(self, generation: int, text: str, found: tuple[list[Tile], int] | None) -> None:
        if generation != self._generation:
            return  # a newer search or order has been asked for since
        rows = [tile_row(t) for t in found[0]] if found is not None else []
        names = [r["name"] for r in rows]
        self._pending, self._shown = False, text
        self._total = found[1] if found is not None else self._total
        if names == [r["name"] for r in self._rows]:  # the same tiles: read again in place
            self._rows = rows
            if rows:
                self.dataChanged.emit(self.index(0), self.index(len(rows) - 1))
        else:
            self.beginResetModel()
            self._rows = rows
            self.endResetModel()
        self.countChanged.emit()

    def name_at(self, row: int) -> str:
        return str(self._rows[row]["name"]) if 0 <= row < len(self._rows) else ""

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        base = int(Qt.ItemDataRole.UserRole)
        return {base + i: QByteArray(n.encode()) for i, n in enumerate(ROLES)}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        i = role - int(Qt.ItemDataRole.UserRole)
        if not 0 <= i < len(ROLES) or not 0 <= index.row() < len(self._rows):
            return None
        return self._rows[index.row()][ROLES[i]]

    def total(self) -> int:
        return self._total

    def searching(self) -> bool:
        return bool(self._query)

    def filtered(self) -> bool:
        return bool(self._shown)

    def shown_search(self) -> str:
        return self._shown

    def pending(self) -> bool:
        return self._pending

    def wait(self) -> None:
        self._searcher.wait()

    def show_ratings(self, ratings: object) -> None:
        """A tile shows no ratings."""

    count = QtProperty(int, lambda self: len(self._rows), notify=countChanged)


def count_of(model: GenresModel) -> str:
    """The Genres view's count in the header: 24 genres; 3 of 24 genres while a search filters
    it."""
    return count_text(model.rowCount(), model.total(), "genre", model.filtered())


# ---------- a genre's page ----------


def _field(name: str, default: object = "") -> Callable[[GenrePage], object]:
    return lambda page: page._values.get(name, default)


class GenrePage(QObject):
    """A genre's page (R9.1), like an artist's: a mosaic of its covers, its name and counts, the
    albums with a song of it, then its songs, by album artist, album, disc and track; the
    header's search filters both (R2.7). Its id is the genre's name."""

    changed = Signal()

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        parent: QObject | None = None,
        searcher: Searcher | None = None,
    ):
        super().__init__(parent)
        self._read = read
        self._name = ""
        self._values: dict[str, object] = {}
        self._albums = AlbumsModel(read, self, searcher=searcher)
        self._songs = SongsModel(read, "artist", self, GENRE_SONGS, ("",), searcher)
        self._songs.countChanged.connect(self.changed)  # Songs' title: shown with rows

    def load(self, name: str, search: str | None = None) -> bool:
        """Shows the genre `name`, its albums and songs filtered by `search` (R2.7; None: the
        search they have); False when no song has it."""
        c = self._read()
        songs, albums = c.execute(
            "SELECT COUNT(*), COUNT(DISTINCT song.album_id) FROM song_genre"
            " JOIN song ON song.id = song_id WHERE genre = ?",
            (name,),
        ).fetchone()
        if not songs:
            return False
        thumbs = [
            t
            for (t,) in c.execute(
                "SELECT album.thumb FROM song_genre JOIN song ON song.id = song_id"
                " JOIN album ON album.id = song.album_id WHERE song_genre.genre = ?"
                " AND album.thumb IS NOT NULL GROUP BY album.id ORDER BY COUNT(*) DESC, album.id"
                " LIMIT 4",
                (name,),
            )
        ]
        if search is not None:
            self._albums.search_next(search)
            self._songs.search_next(search)
        if name == self._name:  # read again where it is: after a scan or a save
            self._albums.refresh()
            self._songs.refresh()
        else:
            self._name = name
            self._albums.for_genre(name)
            self._songs.select(GENRE_SONGS, (name,))
        self._songs.source = name
        self._values = {
            "name": name,
            "detail": artist_line(albums, songs),
            "tiles": tiles(thumbs),
            "average": average_in(c, GENRE_SONGS, (name,)),
        }
        self.changed.emit()
        return True

    def set_search(self, text: str) -> None:
        """Filters the genre's albums, those with a song the search finds, and its songs (R2.7)."""
        self._albums.set_search(text)
        self._songs.set_search(text)

    def lists(self) -> list[tuple[PagedModel, str]]:
        """The lists a search filters, each with what it counts (bridges.page_count_text)."""
        return [(self._albums, "album"), (self._songs, "song")]

    def select_all(self) -> None:
        """Select its songs (R9.4): every song of the list, once its rows have come."""
        c = self._read()
        ids = [
            int(i)
            for (i,) in c.execute("SELECT song_id FROM song_genre WHERE genre = ?", (self._name,))
        ]
        self._songs.select_songs(ids)

    def _get_songs_title(self) -> str:
        return "Songs" if self._songs.rowCount() else ""

    id = QtProperty(str, lambda self: self._name, notify=changed)
    name = QtProperty(str, _field("name"), notify=changed)
    detail = QtProperty(str, _field("detail"), notify=changed)  # 18 albums · 214 songs
    tiles = QtProperty(list, _field("tiles", []), notify=changed)
    average = QtProperty(dict, _field("average", {}), notify=changed)  # R10.1; {}: none rated
    songsTitle = QtProperty(str, _get_songs_title, notify=changed)  # "" when it shows none
    albums = QtProperty(QObject, lambda self: self._albums, constant=True)
    songs = QtProperty(QObject, lambda self: self._songs, constant=True)


# ---------- renaming, merging and near duplicates (R9.4, R9.5) ----------


class Genres(QObject):
    """The Genres view's banner of near duplicates (R9.5), and the dialog of a genre's Rename…
    and Merge into… (R9.4) and of the banner's Review…, as ToolDialog.qml shows a tool: its title
    and what it does, its options (the new name, or the genre to merge into), the preview of the
    files that change, and its save.

    `read` gives this thread's reading connection to the index; `write` writes one file (the
    app's writer: safe.save with the root's settings); `history` keeps each save as one entry and
    says its message (R4.9, R6.7), and `saved` is told of the files written (Library.saved).
    `same`: the genres the user has said are the same (the root's settings, R9.5); `undoable`:
    whether the change history keeps a save (R13.3). A save runs on `executor` (its own thread
    when None); `available` says whether the root is there (R2.10): saving waits until it is."""

    changed = Signal()  # the dialog: open or not, its options, the preview, the save
    bannerChanged = Signal()
    menuForChanged = Signal()
    _progressed = Signal(int, int, str)
    _done = Signal(object)

    def __init__(
        self,
        root: str,
        read: Callable[[], sqlite3.Connection],
        write: Callable[[Job], Written] | None,
        history: ChangeHistory | None = None,
        saved: Callable[[Sequence[Written]], object] | None = None,
        same: Iterable[Iterable[str]] = (),
        undoable: bool = True,
        executor: Executor | None = None,
        available: Callable[[], bool] = lambda: True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._read, self._write = root, read, write
        self._history, self._saved, self._available = history, saved, available
        self._same = [tuple(g) for g in same]
        self._undoable = undoable and history is not None
        self._executor = executor
        self._searcher = Searcher(self)
        self._preview = Preview(root, parent=self)
        self._counts: dict[str, int] = {}
        self._groups: list[Group] = []
        self._later: set[tuple[str, ...]] = set()  # Not now's groups, for this run
        self._group: Group | None = None
        self._files = 0
        self._reading = False  # the banner is being worked out
        self._tool = ""  # "rename", "merge", or "" when the dialog is closed
        self._names: tuple[str, ...] = ()  # the genres renamed or merged
        self._into = ""  # the new name, or the genre merged into
        self._choices: list[str] = []
        self._songs: list[Song] = []
        self._problem = ""
        self._ticket = 0
        self._loading = False
        self._batch: Batch[Written] | None = None
        self._progress = (0, 0)
        self._failed: list[Failed] = []
        self._description = ""
        self._menu_for = ""
        self._closed = False
        self._progressed.connect(self._on_progress)
        self._done.connect(self._on_done)
        self._preview.changed.connect(self.changed)  # a file checked or not: the footer

    # ---------- the banner (R9.5) ----------

    def refresh(self) -> None:
        """Reads the genres again, on the search thread (after a scan or a save): the near
        duplicates, and the files merging the first would rewrite."""
        read, same = self._read, self._same

        def work() -> tuple[dict[str, int], list[Group]]:
            counts = genres.counts(read())
            return counts, genres.near_duplicates(counts, same)

        self._reading = True
        self.bannerChanged.emit()
        self._searcher.submit("groups", work, self._on_groups)

    def _on_groups(self, found: tuple[dict[str, int], list[Group]] | None) -> None:
        if self._closed:
            return
        if found is not None:
            self._counts, self._groups = found
        self._show_group()

    def _show_group(self) -> None:
        group = next((g for g in self._groups if g.names not in self._later), None)
        if group is None:
            self._group, self._files, self._reading = None, 0, False
            self.bannerChanged.emit()
            return
        read = self._read

        def then(files: int | None) -> None:
            if not self._closed:
                self._group, self._files, self._reading = group, files or 0, False
                self.bannerChanged.emit()

        self._searcher.submit("files", lambda: genres.files_of(read(), group.others), then)

    @Slot()
    def notNow(self) -> None:  # noqa: N802
        """Not now: this group's banner hidden for this run, until its names or their songs
        change; the next group's shows."""
        if self._group is not None:
            self._later.add(self._group.names)
            self._show_group()

    @Slot()
    def review(self) -> None:
        """Review…: the merge of the banner's group, the most used name chosen (R9.5)."""
        if self._group is not None:
            g = self._group
            self._open("merge", g.names, g.chosen, list(g.names))

    # ---------- the ⋯ menu (R9.4) ----------

    @Slot(str)
    def rename(self, name: str) -> None:
        """Rename…: the new name typed, the genre's own at first."""
        self._open("rename", (name,), name, [])

    @Slot(str)
    def mergeInto(self, name: str) -> None:  # noqa: N802
        """Merge into…: the genre to merge it into chosen, the first of those offered at first:
        one that looks like it, else the most used."""
        choices = choices_of(name, self._counts, self._groups)
        self._open("merge", (name,), choices[0] if choices else "", choices)

    def _open(self, tool: str, names: Sequence[str], into: str, choices: list[str]) -> None:
        if self._batch is not None:
            return
        self._tool, self._names, self._into, self._choices = tool, tuple(names), into, choices
        self._songs, self._problem, self._failed = [], "", []
        self._ticket += 1
        ticket, read, root, held = self._ticket, self._read, self._root, self._names
        self._loading = True
        self._plan()

        def then(songs: list[Song] | None) -> None:
            if ticket == self._ticket and not self._closed:
                self._loading = False
                self._songs = songs or []
                self._plan()

        self._searcher.submit("songs", lambda: read_songs(read(), root, held), then)

    def _plan(self) -> None:
        self._problem = ""
        planned = Planned(("genres",), tuple(self._songs), tuple(s.tags for s in self._songs))
        try:
            if self._tool == "merge" and not self._into:
                raise GenreNameError(NO_OTHER)
            if self._tool == "rename":
                planned = genres.rename(self._songs, self._names[0], self._into)
            elif self._tool == "merge":
                planned = genres.merge(self._songs, self._names, self._into)
        except GenreNameError as e:
            self._problem = str(e)
        self._preview.show(planned, self._undoable)
        self.changed.emit()

    @Slot(str, "QVariant")
    def setOption(self, name: str, value: Any) -> None:  # noqa: N802
        """The dialog's option: Rename…'s "name" as typed, Merge into…'s "into" chosen."""
        if not self._tool or self._batch is not None:
            return
        if name not in ("name", "into"):
            raise ValueError(f"no such option: {name}")
        if name == "into" and str(value) not in self._choices:
            return
        self._into = str(value)
        self._plan()

    @Slot(str)
    def toggleField(self, name: str) -> None:  # noqa: N802
        """A genre's chip in Merge into…: the one merged into."""
        self.setOption("into", name)

    @Slot()
    def close(self) -> None:
        """Cancel, ×, or Esc: nothing saved; while a save goes on, it stops before its next
        file."""
        if self._batch is not None:
            self._batch.cancel()
            return
        if self._tool:
            self._tool, self._songs, self._failed = "", [], []
            self._ticket += 1
            self._preview.show(Planned((), (), ()))
            self.changed.emit()

    # ---------- saving (R4.7, R4.9) ----------

    def _description_of(self, songs: int) -> str:
        if self._tool == "rename":
            return rename_description(self._names[0], self._into.strip(), songs)
        return merge_description(self._names, self._into, songs)

    @Slot()
    def save(self) -> None:
        """Save N files: the files checked written, one entry in the change history; Retry
        when files failed: those written again."""
        if self._batch is not None or not self._available():
            return
        if self._failed:
            jobs = [f.job for f in self._failed]
        else:
            jobs = self._preview.jobs()
            if not jobs or self._problem:
                return
            self._description = self._description_of(len(jobs))
        self._start(jobs)

    def _start(self, jobs: list[Job]) -> None:
        if self._write is None:
            return
        record = self._history.recording() if self._history is not None else None
        batch: Batch[Written] = Batch(
            jobs, self._write, self._progressed.emit, record=record, action=GENRE,
            description=self._description,
        )  # fmt: skip
        self._batch, self._progress, self._failed = batch, (0, len(jobs)), []
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="genres")
        self.changed.emit()
        self._executor.submit(self._run, batch, jobs)

    def _run(self, batch: Batch[Written], jobs: list[Job]) -> None:
        try:
            out = batch.run()
        except Exception as e:  # noqa: BLE001  (the batch fails its files, never itself; logged)
            log.exception("the genres' save failed")
            out = Outcome(failed=[Failed(j, f"it wasn't saved: {e}") for j in jobs])
        self._done.emit(out)

    @Slot(int, int, str)
    def _on_progress(self, done: int, total: int, _path: str) -> None:
        self._progress = (done, total)
        self.changed.emit()

    @Slot(object)
    def _on_done(self, out: Outcome[Written]) -> None:
        self._batch = None
        if out.saved and self._saved is not None:
            self._saved(out.saved)  # their rows (Library.saved), then the views read again
        if self._history is not None:
            self._history.after_save(out)
        self._failed = list(out.failed)
        if self._failed:
            first = self._failed[0]
            name = first.job.path.replace("\\", "/").rpartition("/")[2]
            self._problem = f"{failed_text(len(self._failed))}: {name} {first.why}"
            self.changed.emit()
            return
        self._tool = ""
        self._preview.show(Planned((), (), ()))
        self.changed.emit()

    # ---------- the tour, and closing ----------

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"genreMenu": "Electronic"} opens that genre's ⋯ menu in the
        Genres view (G01-genres); {"genreTool": {"tool": "merge", "genre": …}} opens a dialog;
        without either, both are closed."""
        menu = str(step.get("genreMenu", ""))
        if menu != self._menu_for:
            self._menu_for = menu
            self.menuForChanged.emit()
        tool = step.get("genreTool")
        if tool is None:
            self.close()
        elif tool["tool"] == "rename":
            self.rename(tool["genre"])
        elif tool["tool"] == "review":
            self.review()
        else:
            self.mergeInto(tool["genre"])

    @Slot()
    def menuClosed(self) -> None:  # noqa: N802
        """The ⋯ menu the tour opened was closed."""
        if self._menu_for:
            self._menu_for = ""
            self.menuForChanged.emit()

    def shut(self) -> None:
        """For closing the window: a save going on stops before its next file and is waited for;
        nothing starts after. What the threads held is let go (A1.3)."""
        self._closed = True
        if self._batch is not None:
            self._batch.cancel()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._batch = None
        self._searcher.wait()
        self._saved = self._history = self._write = None
        self._available = _gone

    # ---------- what QML reads ----------

    def _get_options(self) -> dict[str, Any]:
        if self._tool == "rename":
            return {"name": self._into}
        if self._tool == "merge":
            return {
                "fields": [
                    {
                        "name": g,
                        "label": f"{g} ({self._counts.get(g, 0):,})",
                        "chosen": g == self._into,
                    }
                    for g in self._choices
                ],  # fmt: skip
                "single": True,
                "choose": "into",
            }
        return {}

    def _get_title(self) -> str:
        if self._tool == "rename":
            return f"Rename {self._names[0]}"
        if self._tool == "merge" and len(self._names) > 1:
            return "Merge into one genre"
        return f"Merge {self._names[0]} into…" if self._tool == "merge" else ""

    def _get_about(self) -> str:
        names = names_text(list(self._names))
        if self._tool == "rename":
            return (
                f"Every song with {names} gets the new name instead. A name another genre "
                "has already merges the two."
            )
        if self._tool == "merge" and len(self._names) > 1:
            either = ", ".join(self._names[:-1]) + " or " + self._names[-1]
            return f"Every song with {either} gets the name chosen; the most used at first."
        return f"Every song with {names} gets the genre chosen instead." if self._tool else ""

    def _get_footer(self) -> str:
        if self._batch is not None:
            return progress_text(*self._progress)
        if self._loading:
            return "Reading the songs…"
        return footer_text(*self._preview.counts(), undoable=self._undoable)

    def _get_save_label(self) -> str:
        if self._failed:
            return f"Retry {plural(len(self._failed), 'file')}"
        return save_text(self._preview.counts()[0])

    def _get_save_later(self) -> str:
        """Why Save can't be pressed now ("" when it can)."""
        if self._batch is not None:
            return "A save is going on"
        if self._failed:
            return ""
        if self._problem or not self._preview.chosen():
            return "Nothing to save"
        return ""

    opened = QtProperty(bool, lambda self: bool(self._tool), notify=changed)
    tool = QtProperty(str, lambda self: self._tool, notify=changed)
    title = QtProperty(str, _get_title, notify=changed)
    about = QtProperty(str, _get_about, notify=changed)
    count = QtProperty(int, lambda self: len(self._songs), notify=changed)
    options = QtProperty(dict, _get_options, notify=changed)
    problem = QtProperty(str, lambda self: self._problem, notify=changed)
    preview = QtProperty(QObject, lambda self: self._preview, constant=True)
    footer = QtProperty(str, _get_footer, notify=changed)
    saveLabel = QtProperty(str, _get_save_label, notify=changed)
    saveLater = QtProperty(str, _get_save_later, notify=changed)
    saving = QtProperty(bool, lambda self: self._batch is not None, notify=changed)
    banner = QtProperty(dict, lambda self: banner_of(self._group, self._files, self._undoable),
                        notify=bannerChanged)  # fmt: skip
    menuFor = QtProperty(str, lambda self: self._menu_for, notify=menuForChanged)
    reading = QtProperty(bool, lambda self: self._reading, notify=bannerChanged)


def _gone() -> bool:
    return False
