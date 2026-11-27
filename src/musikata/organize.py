"""Organize files in the running app (R12, T03-organize-files), and files brought in from outside
the root (R12.5).

- **Organize files** (R12.2) opens from the header's ⋮ menu in Folders (the open folder's every
  song) and on an album's page (its songs), from the selection bars and the right-click menus (a
  selected folder bringing every song beneath it, R2.9.6). Its songs, the folders they are in
  and the files beside them are read off the GUI thread; the plan is musikata_core.organize's,
  under the root's layout (R12.1; patterns.LAYOUT until its settings name one, R13). The dialog
  lists every move, the old path dimmed above the new, each with its checkbox (`MovesModel`);
  "+ 10 more moves · 2 empty folders will be removed" under the list, the playlists that will be
  updated (R12.4), and the total and the conflicts in the footer. **Move N files** runs the moves
  as one batch on a thread of its own, with its progress and Cancel between files, recorded as
  one entry in the change history; the index, the playlists and the folders left empty then
  follow (organize.Follower), and the message says what moved and offers Undo (R4.9).
- **Adding from outside** (R12.5): files and folders dropped from outside the root (on the window,
  the queue or a playlist; dragging.py, playlists.py) open the same dialog to place them by the
  layout: **Copy into the library** (the default) or **Move into the library**; their tags read,
  and **Infer from path** offered to fill those missing (R3, only the empty ones); a file whose
  audio the library has already reported and left out. The copies run on the thread, with
  progress and Cancel, then are read into the index; dropped on a playlist, they are added to it.

What the dialog says is decided here as plain data and text (`more_text`, `footer_text`, …),
tested without a window; the plan and the moves are musikata_core.organize's. QML
(OrganizeDialog.qml) lays it out."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

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

from musikata_core import attention, organize, patterns, scanner
from musikata_core import folders as index_folders
from musikata_core.clock import Clock, SystemClock
from musikata_core.organize import Followed, Move, Moved, Outside, Plan, Source
from musikata_core.tags import Batch, Failed, Job, Outcome, Tags, Written

from .bridges import shown_path
from .history import ChangeHistory
from .models import Searcher, plural

if TYPE_CHECKING:
    from .bridges import Library

log = logging.getLogger(__name__)

TITLE = "Organize files"
ADD_TITLE = "Add to your library"
ORGANIZE = "organize"  # Organize files' entry in the change history (R4.9)
NOT_THERE = "Files can't be moved while the music folder isn't available"  # R2.10
CONFLICTS = {
    organize.TWICE: "Another file would get this name",
    organize.TAKEN: "A file has this name already",
}  # R12.4
STAYS = "Stays: a song of its folder stays there"  # a file beside songs that don't all move
COPY, MOVE = "copy", "move"  # R12.5's two ways
WAYS = ((COPY, "Copy into the library"), (MOVE, "Move into the library"))
ROLES = ("old", "target", "checked", "moving", "note", "sidecar")


# ---------- what it says ----------


def about_text(adding: bool, root: str, home: str = "") -> str:
    """What the dialog does (T03)."""
    if adding:
        return (f"Place these files in {shown_path(root, home)} by its layout. Nothing is copied"
                " or moved until you say so.")  # fmt: skip
    return (
        "Rename and move files to match their tags. Every move is listed first, and Undo puts"
        " them back."
    )


def layout_label(root: str, home: str = "") -> str:
    """The layout's heading (T03): Layout under ~/Music."""
    return f"Layout under {shown_path(root, home)}"


def more_text(moves: int, shown: int, emptied: int) -> str:
    """The line under the list (T03): + 10 more moves · 2 empty folders will be removed; the
    moves past those the list shows without scrolling, and the folders left empty (R12.3)."""
    parts = []
    if moves > shown:
        parts.append(f"+ {moves - shown:,} more {'move' if moves - shown == 1 else 'moves'}")
    if emptied:
        parts.append(f"{plural(emptied, 'empty folder')} will be removed")
    return " · ".join(parts)


def playlists_text(names: Sequence[str]) -> str:
    """The banner (T03, R12.4): Playlists that list these files are updated too: Road Trip,
    Workout Mix."""
    if not names:
        return ""
    return f"Playlists that list these files are updated too: {', '.join(names)}."


def footer_text(files: int, conflicts: int) -> str:
    """The footer (T03): 14 files · no name conflicts; or how many wait on a conflict (R12.4)."""
    if not conflicts:
        return f"{plural(files, 'file')} · no name conflicts"
    noun = "name conflict" if conflicts == 1 else "name conflicts"
    return (f"{plural(files, 'file')} · {conflicts:,} {noun}: uncheck one of each, or change its"
            " tags")  # fmt: skip


def notes_text(in_place: int, untagged: int, known: Sequence[str] = (), unread: int = 0) -> str:
    """What isn't moved and why: songs already where they belong, songs with no tags to place
    them by, and, brought from outside, files the library has (R12.5) or that couldn't be read."""
    parts = []
    if in_place:
        parts.append(f"{plural(in_place, 'song')} {'is' if in_place == 1 else 'are'} where"
                     f" {'it belongs' if in_place == 1 else 'they belong'} already")  # fmt: skip
    if untagged:
        parts.append(f"{plural(untagged, 'song')} {'has' if untagged == 1 else 'have'} no tags to"
                     " place by: Infer from path first")  # fmt: skip
    if known:
        names = ", ".join(known[:2]) + (f" and {len(known) - 2:,} more" if len(known) > 2 else "")
        parts.append(f"in your library already, so not added: {names}")
    if unread:
        parts.append(f"{plural(unread, 'file')} couldn't be read")
    text = " · ".join(parts)
    return text[:1].upper() + text[1:]


def action_label(n: int, adding: bool, way: str = COPY) -> str:
    """The button: Move 14 files; brought from outside, Copy 3 files (or Move)."""
    verb = ("Copy" if way == COPY else "Move") if adding else "Move"
    return f"{verb} {plural(n, 'file')}"


def progress_text(done: int, total: int, adding: bool, way: str = COPY) -> str:
    verb = "Copying" if adding and way == COPY else "Moving"
    return f"{verb} {done:,} of {plural(total, 'file')}…"


def description_of(n: int) -> str:
    """The move's entry in the change history (R4.9): Organize files: 14 files."""
    return f"{TITLE}: {plural(n, 'file')}"


def done_text(outcome: Outcome[Any], followed: Followed, adding: bool = False,
              way: str = COPY) -> str:  # fmt: skip
    """The message after the moves (R6.7): how many moved (or were copied in), the first that
    didn't with why, the playlists updated, and what didn't follow."""
    done, failed = len(outcome.saved), len(outcome.failed)
    verb = ("Copied" if way == COPY else "Moved") if adding else "Moved"
    if outcome.cancelled:
        whole = done + failed + len(outcome.left)
        text = f"{verb} {done:,} of {plural(whole, 'file')}: cancelled before the rest"
    elif failed:
        first = outcome.failed[0]
        text = (f"{verb} {done:,} of {plural(done + failed, 'file')}:"
                f" {os.path.basename(first.job.path)} {first.why}"
                + (f", and {failed - 1:,} more" if failed > 1 else ""))  # fmt: skip
    else:
        text = f"{verb} {plural(done, 'file')}" + (" into your library" if adding else "")
    if followed.playlists:
        text += f" · {plural(len(followed.playlists), 'playlist')} updated"
    if followed.failed:
        text += f"; {' and '.join(followed.failed)} will follow at the next scan"
    return text


# ---------- R12.5: tags from the paths of files from outside ----------


LAYOUT_FIELDS = ("title", "artist", "album")  # what a song needs for the layout to place it well


def missing(tags: Tags) -> bool:
    """Whether a file from outside lacks tags the layout places it by (R12.5)."""
    return any(not getattr(tags, f) for f in LAYOUT_FIELDS)


def inferred(found: Sequence[Outside], user: Sequence[str] = ()) -> dict[str, dict[str, object]]:
    """R12.5's Infer from path: for each file whose tags are missing, the tags its path (from the
    folder dropped) gives under the pattern that fits the most of them (R3.4), only the empty ones
    filled (R3.5), by its whole path; those it gives none left out."""
    wanting = [f for f in found if missing(f.tags)]
    chosen = patterns.detected(
        patterns.detect(patterns.patterns_of(user), [f.named for f in wanting])
    )
    if chosen is None:
        return {}
    fill = patterns.Options(fill_only=True)
    out: dict[str, dict[str, object]] = {}
    for f in wanting:
        values = patterns.given(chosen, f.named, fill)
        if values is None:
            continue
        new = patterns.infer(f.tags, values, fill)
        changes = {k: list(v) if k == "genres" else v for k in patterns.COLUMNS
                   if (v := getattr(new, k)) != getattr(f.tags, k)}  # fmt: skip
        if changes:
            out[f.path] = changes
    return out


def with_fields(tags: Tags, changes: Mapping[str, object]) -> Tags:
    """`tags` with the fields Infer from path fills (`inferred`'s)."""
    values = {k: tuple(v) if k == "genres" and isinstance(v, list) else v
              for k, v in changes.items()}  # fmt: skip
    return replace(tags, **values)  # type: ignore[arg-type]  # Tags' own fields


# ---------- what the dialog is planned from ----------


@dataclass
class Loaded:
    """What the thread read for the dialog: the songs to place, the folders' entries beside them,
    the paths a file has taken already (among the new paths any move could take), the playlists
    naming each song; brought from outside, the files read, those the library has, and the tags
    their paths give."""

    sources: list[Source] = field(default_factory=list)
    beside: dict[str, list[str]] = field(default_factory=dict)
    taken: set[str] = field(default_factory=set)
    naming: dict[str, list[str]] = field(default_factory=dict)
    outside: list[Outside] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    inferred: dict[str, dict[str, object]] = field(default_factory=dict)


def load_songs(c: sqlite3.Connection, root: str, ids: Sequence[int], layout: patterns.Pattern
               ) -> Loaded:  # fmt: skip
    """On the thread: Organize files' songs (`ids`), the folders beside them and what is taken."""
    sources = organize.sources_of(c, ids)
    beside = organize.listing(root, [s.path for s in sources])
    whole = organize.plan(sources, layout, beside, lambda _p: False)
    taken = organize.taken_in(root)
    return Loaded(sources, beside, {m.new for m in whole.moves if taken(m.new)},
                  organize.playlists_naming(c, [s.path for s in sources]))  # fmt: skip


def slashed(path: str) -> str:
    return path.replace(os.sep, "/") if os.sep != "/" else path


def load_outside(c: sqlite3.Connection, root: str, paths: Sequence[str], layout: patterns.Pattern,
                 user: Sequence[str] = ()) -> Loaded:  # fmt: skip
    """On the thread: files dropped from outside the root (R12.5), read, those the library has
    found by their audio, the tags their paths give, and what is taken."""
    found = [organize.read_outside(p, n) for p, n in organize.outside_songs(paths)]
    readable = [f for f in found if not f.error]
    have = organize.known(c, [f.hash for f in readable if f.hash])
    fresh = [f for f in readable if f.hash not in have]
    out = Loaded(outside=found, known=[os.path.basename(f.path) for f in readable
                                       if f.hash in have])  # fmt: skip
    out.inferred = {slashed(k): v for k, v in inferred(fresh, user).items()}
    out.sources = [Source(0, slashed(f.path), f.tags, 1, f.hash) for f in fresh]
    out.beside = {}
    for folder in {organize.folder_of(s.path) for s in out.sources}:
        try:
            with os.scandir(folder or "/") as it:
                out.beside[folder] = sorted(e.name + "/" if e.is_dir() else e.name for e in it)
        except OSError:
            out.beside[folder] = []
    taken = organize.taken_in(root)
    for filled in (False, True):
        sources = [replace(s, tags=with_fields(s.tags, out.inferred.get(s.path, {})))
                   if filled else s for s in out.sources]  # fmt: skip
        whole = organize.plan(sources, layout, out.beside, lambda _p: False, prune=False)
        out.taken |= {m.new for m in whole.moves if taken(m.new)}
    return out


# ---------- the list of moves ----------


class MovesModel(QAbstractListModel):
    """The dialog's list (T03): every move the plan could make, each its old path, its new path,
    whether it is checked, whether it moves, and why not ("" when it does, a conflict, or a file
    beside songs that stay); its rows stay as they are when a checkbox changes, so the list keeps
    its place."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[Move] = []
        self._now: dict[str, Move] = {}
        self._shown: Callable[[str], str] = str

    def show(self, rows: Sequence[Move], now: Plan, shown: Callable[[str], str] = str) -> None:
        """`rows` (the plan with every move checked) as `now` (the plan as checked) makes them,
        their paths as `shown` gives them."""
        same = [m.old for m in rows] == [m.old for m in self._rows]
        self._now = {m.old: m for m in now.moves}
        self._shown = shown
        if same and rows:
            self._rows = list(rows)
            self.dataChanged.emit(self.index(0), self.index(len(rows) - 1))
            return
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row(self, n: int) -> dict[str, Any]:
        base = self._rows[n]
        now = self._now.get(base.old)
        note = ""
        if now is None:
            note = STAYS
        elif now.conflict:
            note = CONFLICTS[now.conflict]
        return {
            "old": self._shown(base.old),
            "target": base.new,
            "checked": now.checked if now is not None else False,
            "moving": now is not None and now.ready,
            "note": note,
            "sidecar": base.song is None,
        }

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:  # noqa: N802
        return len(self._rows)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        name = ROLES[role - Qt.ItemDataRole.UserRole - 1] if role > Qt.ItemDataRole.UserRole else ""
        return self.row(index.row()).get(name)

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return {
            Qt.ItemDataRole.UserRole + 1 + i: QByteArray(n.encode()) for i, n in enumerate(ROLES)
        }

    def count(self) -> int:
        return len(self._rows)

    def old_at(self, n: int) -> str | None:
        return self._rows[n].old if 0 <= n < len(self._rows) else None


# ---------- the dialog ----------


class OrganizeFiles(QObject):
    """Organize files (R12, T03) over the songs of the index on `read`, its moves followed by
    `follow` (organize.Follower: the index through the writer thread, the playlists through the
    store) and kept in `history` as one entry; and files brought from outside (R12.5), their tags
    filled by `write` (safe.save, the root's settings), read into the index through `index`'s
    writer (`index_write`), and added to the playlist they were dropped on by `add_songs`
    (Playlists.add_songs). `library` is told when the rows changed (Library.reload) and when songs
    moved (songsMoved: this computer's plays file names them anew). `available` says whether the
    root is there (R2.10); `home` shortens paths in what it says; `layout` is the root's (R12.1);
    `user` the user's own patterns (R3.3)."""

    changed = Signal()
    moreChanged = Signal()  # the line under the list: the plan, or how many rows show
    _progressed = Signal(int, int, str)
    _done = Signal(object, object, object)  # the outcome, what followed, the songs added

    def __init__(
        self,
        root: str,
        read: Callable[[], sqlite3.Connection],
        follow: organize.Follower | None = None,
        history: ChangeHistory | None = None,
        library: Library | None = None,
        index_write: Callable[[Callable[[sqlite3.Connection], object]], object] | None = None,
        write: Callable[[Job], Written] | None = None,
        add_songs: Callable[[int, Sequence[int]], object] | None = None,
        available: Callable[[], bool] = lambda: True,
        home: str = "",
        layout: str = patterns.LAYOUT,
        user: Sequence[str] = (),
        clock: Clock | None = None,
        executor: Executor | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._read, self._follow, self._history = root, read, follow, history
        self._library, self._index_write, self._write = library, index_write, write
        self._add_songs, self._available, self._home = add_songs, available, home
        self._layout_text, self._user = layout, list(user)
        self._layout = patterns.parse(layout, naming=True)
        if self._layout.problem:
            log.warning("the root's layout %r can't be used (%s): the default is",
                        layout, self._layout.problem)  # fmt: skip
            self._layout_text = patterns.LAYOUT
            self._layout = patterns.parse(patterns.LAYOUT, naming=True)
        self._clock = clock or SystemClock()
        self._executor = executor
        self._searcher = Searcher(self)
        self._moves = MovesModel(self)
        self._open = self._loading = self._closed = False
        self._adding = False
        self._way = COPY
        self._infer = True
        self._playlist = -1
        self._ticket = 0
        self._loaded = Loaded()
        self._unchecked: set[str] = set()
        self._plan = Plan()
        self._batch: Batch[Any] | None = None
        self._progress = (0, 0)
        self._shown = 4  # the rows the list shows without scrolling (T03)
        self._progressed.connect(self._on_progress)
        self._done.connect(self._on_done)

    # ---------- opening (R12.2, R12.5) ----------

    def open_songs(self, ids: Sequence[int]) -> None:
        """Organize files on the songs of `ids`, in that order."""
        ids = [int(i) for i in ids]
        self._start(False, lambda c: load_songs(c, self._root, ids, self._layout))

    @Slot(str)
    def openFolder(self, folder: str) -> None:  # noqa: N802
        """A folder's every song beneath it (R12.2, R2.9.6): Folders' ⋮ menu on the open
        folder."""
        root, layout = self._root, self._layout
        self._start(False, lambda c: load_songs(c, root, index_folders.songs_beneath(c, folder),
                                                 layout))  # fmt: skip

    @Slot(int)
    def openAlbum(self, album_id: int) -> None:  # noqa: N802
        """An album's page's ⋮ menu (R12.2): its songs."""
        root, layout = self._root, self._layout

        def ids(c: sqlite3.Connection) -> list[int]:
            return [int(i) for (i,) in c.execute(
                f"SELECT id FROM song WHERE album_id = ? ORDER BY {attention.SONG_ORDER}",
                (album_id,),
            )]  # fmt: skip

        self._start(False, lambda c: load_songs(c, root, ids(c), layout))

    @Slot(QObject)
    def openView(self, library: QObject) -> None:  # noqa: N802
        """The header's ⋮ menu (R12.2): in Folders the open folder's songs, on an album's page
        the album's."""
        view = library.property("view")
        if view == "folders":
            self.openFolder(str(library.property("folders").property("path")))
        elif view == "album":
            self.openAlbum(int(library.property("album").property("id")))

    @Slot(QObject)
    def openSelection(self, model: QObject) -> None:  # noqa: N802
        """A selection bar's Organize… (R2.9.6): the songs selected, a folder's every song beneath
        it."""
        self.open_songs(model.selected_songs())  # type: ignore[attr-defined]

    @Slot(QObject, int)
    def openRow(self, model: QObject, row: int) -> None:  # noqa: N802
        """A right-click menu's Organize files…: the selection when the row is in it, else the
        row's song or the songs beneath its folder (R2.9.6)."""
        if model.is_selected(row):  # type: ignore[attr-defined]
            self.openSelection(model)
        else:
            self.open_songs(model.songs_at(row))  # type: ignore[attr-defined]

    def add_files(self, paths: Sequence[str], playlist: int = -1) -> None:
        """Files and folders from outside the root, dropped (R12.5), by their whole paths: placed
        by the layout, copied or moved in; added to `playlist` too when they were dropped on one
        (R8.5)."""
        paths = list(paths)
        root, layout, user = self._root, self._layout, list(self._user)
        self._start(True, lambda c: load_outside(c, root, paths, layout, user))
        self._playlist = playlist

    def _start(self, adding: bool, work: Callable[[sqlite3.Connection], Loaded]) -> None:
        if self._batch is not None or self._closed:
            return
        if not self._available():
            if self._history is not None:
                self._history.say(NOT_THERE)
            return
        self._open, self._loading, self._adding = True, True, adding
        self._way, self._infer, self._playlist = COPY, True, -1
        self._loaded, self._unchecked = Loaded(), set()
        self._ticket += 1
        ticket, read = self._ticket, self._read
        self._replan()

        def then(found: Loaded | None) -> None:
            if ticket != self._ticket or self._closed:
                return
            self._loading = False
            self._loaded = found if found is not None else Loaded()
            self._replan()

        self._searcher.submit(("organize", id(self)), lambda: work(read()), then)

    # ---------- the plan ----------

    def _sources(self) -> list[Source]:
        if not self._adding or not self._infer:
            return self._loaded.sources
        fills = self._loaded.inferred
        return [replace(s, tags=with_fields(s.tags, fills[s.path])) if s.path in fills else s
                for s in self._loaded.sources]  # fmt: skip

    def _plan_of(self, unchecked: Collection[str]) -> Plan:
        taken = self._loaded.taken
        return organize.plan(self._sources(), self._layout, self._loaded.beside,
                             lambda p: p in taken, unchecked, prune=not self._adding)  # fmt: skip

    def _replan(self) -> None:
        self._plan = self._plan_of(self._unchecked)
        rows = self._plan_of(()).moves
        self._moves.show(rows, self._plan, self._shown_path)
        self.changed.emit()
        self.moreChanged.emit()

    def _shown_path(self, path: str) -> str:
        return shown_path(path.replace("/", os.sep), self._home) if self._adding else path

    @Slot(int)
    def toggle(self, row: int) -> None:
        """A move's checkbox (R12.2): unchecked, it isn't made; a conflict it was in may clear
        (R12.4)."""
        old = self._moves.old_at(row)
        if old is None or self._batch is not None:
            return
        self._unchecked ^= {old}
        self._replan()

    @Slot(str)
    def setWay(self, way: str) -> None:  # noqa: N802
        """R12.5: Copy into the library, or Move into the library."""
        if way in (COPY, MOVE) and self._batch is None:
            self._way = way
            self.changed.emit()

    @Slot()
    def toggleInfer(self) -> None:  # noqa: N802
        """R12.5's Infer from path, for the files whose tags are missing: on or off."""
        if self._batch is None:
            self._infer = not self._infer
            self._replan()

    @Slot(int)
    def setShown(self, rows: int) -> None:  # noqa: N802
        """How many rows the list shows without scrolling, for the line under it (T03)."""
        if rows != self._shown and rows >= 0:
            self._shown = rows
            self.moreChanged.emit()

    # ---------- moving (R12.4, R12.5) ----------

    @Slot()
    def run(self) -> None:
        """Move N files (or Copy): the moves checked with no conflict, in one batch off this
        thread; Organize files' kept as one entry in the change history."""
        chosen = self._plan.chosen
        if self._batch is not None or not chosen or not self._available():
            return
        root = self._root
        if self._adding:
            fills = self._loaded.inferred if self._infer else {}
            jobs = [organize.add_job(root, m, fills.get(m.old)) for m in chosen]
            copy, write = self._way == COPY, self._write

            def writer(job: Job) -> Moved:
                return organize.add_file(job, copy, write)

            batch: Batch[Any] = Batch(jobs, writer, self._progressed.emit)
        else:
            jobs = [organize.move_job(root, m) for m in chosen]
            record = self._history.recording() if self._history is not None else None
            batch = Batch(jobs, organize.move_file, self._progressed.emit, record=record,
                          action=ORGANIZE, description=description_of(len(jobs)))  # fmt: skip
        self._batch, self._progress = batch, (0, len(jobs))
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="organize")
        self.changed.emit()
        self._executor.submit(self._work, batch, jobs, self._adding)

    def _work(self, batch: Batch[Any], jobs: list[Job], adding: bool) -> None:
        followed, added = Followed(), []
        try:
            out = batch.run()
        except Exception as e:  # noqa: BLE001  (the batch fails its files, never itself; logged)
            log.exception("organizing files failed")
            out = Outcome(failed=[Failed(j, f"it wasn't moved: {e}") for j in jobs])
        try:
            if adding:
                added = self._index_added(out.saved)
            elif self._follow is not None:
                followed = self._follow(organize.pairs_of(self._root, out.saved))
        except Exception:  # noqa: BLE001  (logged; the next scan finds the files)
            log.exception("the files moved weren't followed in the library")
            followed.failed.append("the library")
        self._done.emit(out, followed, added)

    def _index_added(self, saved: Sequence[object]) -> list[int]:
        """The files brought in read and indexed (R12.5); their songs' ids."""
        reads = []
        for m in saved:
            if not isinstance(m, Moved) or not organize._audio(m.path):
                continue
            rel = scanner.path_under(self._root, m.path)
            if rel is None:
                continue
            st = os.stat(m.path)
            reads.append(scanner.read_one(self._root, scanner.Seen(rel, st.st_size,
                                                                   st.st_mtime_ns)))  # fmt: skip
        if not reads or self._index_write is None:
            return []
        places = {organize.folder_of(r.seen.path) for r in reads}
        images = organize.images_in(self._root, places)
        now = self._clock.now().timestamp()
        found = self._index_write(lambda c: organize.index_added(c, reads, now, images))
        return list(found) if isinstance(found, list) else []

    @Slot(int, int, str)
    def _on_progress(self, done: int, total: int, _path: str) -> None:
        self._progress = (done, total)
        self.changed.emit()

    @Slot(object, object, object)
    def _on_done(self, out: Outcome[Any], followed: Followed, added: list[int]) -> None:
        self._batch = None
        if self._closed:
            return
        adding, way, playlist = self._adding, self._way, self._playlist
        self._open = False
        self._loaded, self._unchecked = Loaded(), set()
        self._replan()
        if self._library is not None:
            self._library.reload()
            if out.saved and not adding:
                self._library.songsMoved.emit()  # this computer's plays name them anew (A2.8)
        text = done_text(out, followed, adding, way)
        if adding and added and playlist >= 0 and self._add_songs is not None:
            self._add_songs(playlist, added)
        elif self._history is not None:
            if adding:
                self._history.say(text)
            else:
                self._history.after_save(out, text)

    @Slot()
    def close(self) -> None:
        """Cancel, ×, or Esc: nothing moved; while the moves go on, they stop before the next
        file."""
        if self._batch is not None:
            self._batch.cancel()
            return
        if self._open:
            self._open = False
            self._ticket += 1
            self._loaded, self._unchecked = Loaded(), set()
            self._replan()

    # ---------- the tour, and closing ----------

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"organize": "<folder>"} opens the dialog on that folder's songs
        ("" the whole root); without it the dialog is closed."""
        if "organize" not in step:
            if self._open:
                self.close()
            return
        self.openFolder(str(step["organize"]))

    def shut(self) -> None:
        """For closing the window: the moves going on stop before their next file and are waited
        for; nothing starts after. What the threads held is let go (A1.3)."""
        self._closed = True
        if self._batch is not None:
            self._batch.cancel()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._batch = None
        self._searcher.wait()
        self._history = self._library = self._follow = None
        self._write = self._index_write = self._add_songs = None
        self._available = _gone

    # ---------- what QML reads ----------

    def _get_footer(self) -> str:
        if self._batch is not None:
            return progress_text(*self._progress, self._adding, self._way)
        if self._loading:
            return "Reading the files…" if self._adding else "Reading the songs…"
        return footer_text(len(self._plan.chosen), len(self._plan.conflicts))

    def _get_action_later(self) -> str:
        if self._batch is not None:
            return "Files are being moved"
        if not self._available():
            return NOT_THERE
        if self._loading:
            return ""
        return "" if self._plan.chosen else "Nothing to move"

    def _get_playlists(self) -> str:
        naming = self._loaded.naming
        names: dict[str, None] = {}
        for m in self._plan.chosen:
            names.update(dict.fromkeys(naming.get(m.old, ())))
        return playlists_text(sorted(names, key=str.casefold))

    def _get_notes(self) -> str:
        if self._loading:
            return ""
        unread = sum(1 for f in self._loaded.outside if f.error)
        return notes_text(self._plan.in_place, len(self._plan.untagged), self._loaded.known, unread)

    def _get_infer_label(self) -> str:
        n = len(self._loaded.inferred)
        if not self._adding or not n:
            return ""
        return f"Infer from path for {plural(n, 'file')} whose tags are missing"

    opened = QtProperty(bool, lambda self: self._open, notify=changed)
    loading = QtProperty(bool, lambda self: self._loading, notify=changed)
    adding = QtProperty(bool, lambda self: self._adding, notify=changed)
    title = QtProperty(str, lambda self: ADD_TITLE if self._adding else TITLE, notify=changed)
    about = QtProperty(str, lambda self: about_text(self._adding, self._root, self._home),
                       notify=changed)  # fmt: skip
    layoutLabel = QtProperty(str, lambda self: layout_label(self._root, self._home),
                             constant=True)  # fmt: skip
    layout = QtProperty(str, lambda self: self._layout_text, constant=True)
    moves = QtProperty(QObject, lambda self: self._moves, constant=True)
    more = QtProperty(
        str,
        lambda self: more_text(self._moves.count(), self._shown, len(self._plan.emptied)),
        notify=moreChanged,
    )
    playlists = QtProperty(str, _get_playlists, notify=changed)
    notes = QtProperty(str, _get_notes, notify=changed)
    footer = QtProperty(str, _get_footer, notify=changed)
    actionLabel = QtProperty(str, lambda self: action_label(len(self._plan.chosen), self._adding,
                                                            self._way), notify=changed)  # fmt: skip
    actionLater = QtProperty(str, _get_action_later, notify=changed)
    moving = QtProperty(bool, lambda self: self._batch is not None, notify=changed)
    ways = QtProperty(list, lambda self: [{"name": n, "label": label, "chosen": n == self._way}
                                          for n, label in WAYS], notify=changed)  # fmt: skip
    inferLabel = QtProperty(str, _get_infer_label, notify=changed)
    inferOn = QtProperty(bool, lambda self: self._infer, notify=changed)


def _gone() -> bool:
    return False
