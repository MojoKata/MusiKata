"""Removing songs in the running app (R2.11), and keeping a folder out of the library (R2.11.1).

- **Move to trash** (R2.11) is in the right-click menus of songs and folders, an album's ⋯ menu,
  Folders' ⋮ menu (the open folder), and Delete in the library views (a playlist's Delete is
  R8.6's: out of the playlist). What it takes is read off the GUI thread: a folder goes whole, with
  every song beneath it; a song goes with its own lyrics, and with the images and sidecar files
  beside it when every song of its folder goes (R12.3; organize.removal). It asks first, naming what
  goes (R6.8: "Move 3 songs to the trash?", "Move the folder Kindling and its 10 songs to the
  trash?"); then the files go to the system's trash in one batch, on the scan's thread when no
  scan runs (Library.between), so no scan finds them half gone and asks about them (R2.10.1); their
  rows leave the index at once, and the folders left empty are removed. The change history keeps
  the removal as one entry, each song moved to the trash named by its path and audio hash; Undo
  can't take files out of the trash, and the message says so. Playlists keep their entries, which
  show as missing (R8.7); plays and ratings stay in the root's files, keyed by hash (A2.8), so a
  song put back from the trash by hand has them again at the next scan.
- **Ignore this folder** (R2.11.1), in Folders' ⋮ menu and a folder's right-click menu, writes the
  folder's `.musikataignore` (R2.3.1) and takes its songs out of the index at once, on the scan's
  thread in the same way; nothing is removed from the disk, so it doesn't ask.

What each says is decided here as plain data and text, tested without a window; the plan is
musikata_core.organize's (`removal`, `trasher`), the ignoring musikata_core.scanner's."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import art, db, history, organize, scanner
from musikata_core.organize import Removal, Trashed
from musikata_core.tags import Batch, Job, Outcome

from .folders import FolderModel
from .history import IN_TRASH, TRASH, ChangeHistory
from .models import Searcher, plural

if TYPE_CHECKING:
    from .bridges import Library

log = logging.getLogger(__name__)

NOT_THERE = "Nothing can be moved to the trash while the music folder isn't available"  # R2.10
NOT_IGNORED = "No folder can be ignored while the music folder isn't available"  # R2.10
NOTHING = "Nothing to move to the trash"


# ---------- what it says ----------


def names_text(names: Sequence[str]) -> str:
    """Names in a sentence: a.mp3; a.mp3 and b.m4a; a.mp3, b.m4a and 3 more."""
    if len(names) > 3:
        return ", ".join(names[:2]) + f" and {len(names) - 2:,} more"
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def what_text(removal: Removal) -> str:
    """What a removal takes, as the question and the message name it (R2.11): 3 songs; the folder
    Kindling and its 10 songs; 2 folders and their 25 songs; the folder Kindling with its 10
    songs, and 3 other songs."""
    folders = removal.folders
    inside = sum(len(f.songs) for f in folders)
    loose = len(removal.songs) - inside
    if not folders:
        return plural(loose, "song")
    if len(folders) == 1:
        named, its = f"the folder {organize.name_of(folders[0].path)}", "its"
    else:
        named, its = f"{len(folders):,} folders", "their"
    if not loose:
        return f"{named} and {its} {plural(inside, 'song')}"
    return f"{named} with {its} {plural(inside, 'song')}, and {plural(loose, 'other song')}"


def question_of(removal: Removal) -> dict[str, Any]:
    """R2.11's question before files go to the trash (R6.8): Move 3 songs to the trash?, naming
    them, the files beside them that go too, what playlists keep and what Undo can't do."""
    named = [organize.name_of(g.path) for g in removal.going if g.folder or g.songs]
    beside = [organize.name_of(g.path) for g in removal.beside]
    goes = "goes" if len(named) == 1 else "go"
    detail = f"{names_text(named)} {goes} to the system's trash."
    if beside:
        detail += f" {names_text(beside)} beside them {'goes' if len(beside) == 1 else 'go'} too."
    detail += (" Playlists keep their entries, shown as missing. Undo can't take files out of the"
               " trash; they can be put back from it by hand.")  # fmt: skip
    return {"title": f"Move {what_text(removal)} to the trash?", "detail": detail,
            "yes": "Move to trash"}  # fmt: skip


def description_of(removal: Removal) -> str:
    """The removal's entry in the change history (R4.9): 3 songs to the trash."""
    what = what_text(removal)
    return f"{what[:1].upper()}{what[1:]} to the trash"


def done_text(removal: Removal, out: Outcome[Any], listed: bool = False) -> str:
    """The message after a removal (R6.7, R2.11): what went, or how many of the files and folders
    did and the first that didn't with why; whether those gone stay listed until the next scan
    (`listed`: taking them out of the index failed); and that Undo can't take them out of the
    trash."""
    done, failed = len(out.saved), len(out.failed)
    if not done and not failed:
        return NOTHING
    if not failed:
        text = f"Moved {what_text(removal)} to the trash"
    else:
        first = out.failed[0]
        text = (f"Moved {done:,} of {plural(done + failed, 'file')} to the trash:"
                f" {os.path.basename(first.job.path)} {first.why}"
                + (f", and {failed - 1:,} more" if failed > 1 else ""))  # fmt: skip
    if not done:
        return text
    if listed:
        text += ". They stay listed until the library's next scan"
    return f"{text}; {IN_TRASH}"


def ignored_text(folder: str, songs: int) -> str:
    """The message after Ignore this folder (R2.11.1): Kindling is ignored: its 10 songs left the
    library."""
    name = organize.name_of(folder)
    went = f"its {plural(songs, 'song')} left the library" if songs else "it held no songs"
    return (f"{name} is ignored: {went}. Its .musikataignore file keeps it out; remove that file"
            " to bring it back")  # fmt: skip


# ---------- what is read for the question, off the GUI thread ----------


def load(
    c: sqlite3.Connection,
    root: str,
    folders: Sequence[str] = (),
    songs: Sequence[int] = (),
    files: Sequence[str] = (),
    album: int | None = None,
) -> Removal:
    """On the thread: what Move to trash takes of `folders` (paths under the root, each with every
    song beneath it), `songs` (by id), `files` (songs by their paths) and `album`'s songs (by its
    id), and the files beside them (R12.3)."""
    beneath: dict[str, list[tuple[str, str | None]]] = {}
    for f in folders:
        if f:
            beneath[f] = c.execute(
                "SELECT path, audio_hash FROM song WHERE path >= ? AND path < ? ORDER BY path",
                (f + "/", f + "0"),
            ).fetchall()
    chosen: list[tuple[str, str | None]] = []
    if album is not None:
        songs = [*songs, *(i for (i,) in c.execute("SELECT id FROM song WHERE album_id = ?",
                                                   (album,)))]  # fmt: skip
    ids = list(dict.fromkeys(int(i) for i in songs))
    for n in range(0, len(ids), organize.CHUNK):
        part = ids[n : n + organize.CHUNK]
        marks = ", ".join("?" * len(part))
        found = {int(i): (str(p), h) for i, p, h in c.execute(
            f"SELECT id, path, audio_hash FROM song WHERE id IN ({marks})", part)}  # fmt: skip
        chosen += [found[i] for i in part if i in found]
    for path in files:
        row = c.execute("SELECT audio_hash FROM song WHERE path = ?", (path,)).fetchone()
        if row is not None:
            chosen.append((path, row[0]))
    beside = organize.listing(root, [p for p, _ in chosen])
    return organize.removal(chosen, beneath, beside)


# ---------- the removal, on the scan's thread ----------


@dataclass
class Removed:
    """How a removal went: the batch's outcome (each file or folder moved, organize.Trashed, and
    those that weren't, with why) and whether the songs moved are still `listed` (taking them out
    of the index failed: the next scan does)."""

    outcome: Outcome[Any] = field(default_factory=Outcome)
    listed: bool = False


def remove(
    root: str,
    removal: Removal,
    write: Callable[[Job], Trashed],
    record: history.Recording | None,
    forget: Callable[[Sequence[str]], object],
) -> Removed:
    """R2.11's Move to trash, on the calling thread (never the GUI's): each file and folder of
    `removal` moved to the trash by `write` (organize.trasher) in one batch, kept as one entry by
    `record` (None: the history is off); the songs that went taken out of the index by `forget`
    (scanner.remove: those whose file is gone), and the folders left empty removed
    (organize.prune). A step after the files went that fails is logged, and the rest still run."""
    jobs = [organize.trash_job(root, g) for g in removal.going]
    batch: Batch[Trashed] = Batch(jobs, write, record=record, action=TRASH,
                                  description=description_of(removal))  # fmt: skip
    out = Removed(batch.run())
    trashed = [t for t in out.outcome.saved if isinstance(t, Trashed)]
    gone = [p for t in trashed for p, _ in t.songs]
    if gone:
        try:
            forget(gone)
        except Exception:  # noqa: BLE001  (logged; the message says they stay listed)
            log.exception("the songs moved to the trash couldn't be taken out of the library")
            out.listed = True
    organize.prune(root, organize.folders_left(root, trashed))
    return out


def ignore(root: str, index: db.Index, folder: str) -> int:
    """R2.11.1, on the calling thread (never the GUI's): `folder`'s `.musikataignore` written and
    its songs taken out of the index; how many. Raises OSError when the file can't be written,
    nothing taken out."""
    scanner.ignore(root, folder)
    return scanner.forget(index, folder)


# ---------- the bridge ----------


class Removing(QObject):
    """Move to trash and Ignore this folder (R2.11, R2.11.1) over the index on `read` and the
    root's `index`: what goes read off the GUI thread, the question (R6.8), then the files moved to
    the trash by `trash` (art.to_trash) on the scan's thread between scans (`library`,
    Library.between, which reads the lists again after), kept in `history` as one entry and said
    there. `available` says whether the root is there (R2.10)."""

    changed = Signal()

    def __init__(
        self,
        root: str,
        index: db.Index,
        library: Library | None = None,
        history: ChangeHistory | None = None,
        trash: art.Trash = art.to_trash,
        available: Callable[[], bool] = lambda: True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._index, self._library, self._history = root, index, library, history
        self._trash, self._available = trash, available
        self._searcher = Searcher(self)
        self._asked: Removal | None = None  # what the question is about
        self._busy = False  # reading what goes, or moving it
        self._closed = False

    # ---------- Move to trash (R2.11) ----------

    @Slot(QObject, int)
    def askRow(self, model: QObject, row: int) -> None:  # noqa: N802
        """A right-click menu's Move to trash: the selection when the row is in it, else the
        row's song, or its folder whole."""
        if not isinstance(model, FolderModel):  # a list of songs: its songs_at says which
            self._ask(songs=model.songs_at(row))  # type: ignore[attr-defined]
            return
        if model.is_selected(row):
            self.askSelection(model)
            return
        found = model.row(row)
        if found is not None:
            path = str(found["path"])
            folder = found["kind"] == "folder"
            self._ask(folders=[path] if folder else [], files=[] if folder else [path])

    @Slot(QObject)
    def askSelection(self, model: QObject) -> None:  # noqa: N802
        """Delete in a library view (R6.9), or the menu on a row selected: what is selected, a
        folder whole."""
        if isinstance(model, FolderModel):  # Folders: its folders and files
            folders, files = model.selected()
            self._ask(folders=folders, files=files)
        else:
            self._ask(songs=model.selected_songs())  # type: ignore[attr-defined]

    @Slot(int)
    def askAlbum(self, album_id: int) -> None:  # noqa: N802
        """An album's ⋯ menu: its songs, and the files beside them when they are all its folder
        holds (R12.3)."""
        self._ask(album=album_id)

    @Slot(str)
    def askFolder(self, folder: str) -> None:  # noqa: N802
        """Folders' ⋮ menu: the open folder, whole; never the root."""
        if folder:
            self._ask(folders=[folder])

    def _ask(self, folders: Sequence[str] = (), songs: Sequence[int] = (),
             files: Sequence[str] = (), album: int | None = None) -> None:  # fmt: skip
        if self._busy or self._closed:
            return
        if not self._available():
            self._say(NOT_THERE)
            return
        self._busy = True
        self.changed.emit()
        root, read = self._root, self._index.read
        folders, songs, files = list(folders), [int(s) for s in songs], list(files)

        def then(found: Removal | None) -> None:
            if self._closed:
                return
            self._busy = False
            if found is None or not found.going:
                self._say(NOTHING)
            else:
                self._asked = found
            self.changed.emit()

        self._searcher.submit("removal", lambda: load(read(), root, folders, songs, files, album),
                              then)  # fmt: skip

    @Slot(bool)
    def answer(self, yes: bool) -> None:
        """The question's answer: Move to trash, or Cancel (nothing moves)."""
        asked, self._asked = self._asked, None
        if not yes or asked is None or self._library is None or not self._available():
            self.changed.emit()
            return
        self._busy = True
        self.changed.emit()
        root, index, write = self._root, self._index, organize.trasher(self._trash)
        record = self._history.recording() if self._history is not None else None

        def job() -> Removed:
            return remove(root, asked, write, record,
                          lambda paths: scanner.remove(root, index, paths))  # fmt: skip

        self._library.between(job, lambda out: self._removed(asked, out))

    def _removed(self, asked: Removal, out: object) -> None:
        self._busy = False
        self.changed.emit()
        if not isinstance(out, Removed):
            self._say(f"Nothing was moved to the trash: {out}")
            return
        if self._history is not None:
            self._history.say(done_text(asked, out.outcome, out.listed))
            self._history.refresh()

    # ---------- Ignore this folder (R2.11.1) ----------

    @Slot(str)
    def ignoreFolder(self, folder: str) -> None:  # noqa: N802
        """Folders' ⋮ menu, or a folder's right-click menu: its `.musikataignore` written, and it
        and its songs out of the library at once; never the root."""
        if not folder or self._closed or self._library is None:
            return
        if not self._available():
            self._say(NOT_IGNORED)
            return
        root, index = self._root, self._index
        self._library.between(lambda: ignore(root, index, folder),
                              lambda out: self._ignored(folder, out))  # fmt: skip

    @Slot(QObject, int)
    def ignoreRow(self, model: QObject, row: int) -> None:  # noqa: N802
        """A folder's right-click menu in Folders: that folder ignored."""
        self.ignoreFolder(self.folderAt(model, row))

    @Slot(QObject, int, result=str)
    def folderAt(self, model: QObject, row: int) -> str:  # noqa: N802
        """The folder row `row` of Folders' list is, by its path under the root; "" for a file's
        row or another list's, whose menu has no Ignore this folder."""
        r = model.row(row) if isinstance(model, FolderModel) else None
        return str(r["path"]) if r is not None and r["kind"] == "folder" else ""

    def _ignored(self, folder: str, out: object) -> None:
        if isinstance(out, int):
            self._say(ignored_text(folder, out))
        else:
            self._say(f"{organize.name_of(folder)} couldn't be ignored: {out}")

    # ---------- the rest ----------

    def _say(self, text: str) -> None:
        if self._history is not None:
            self._history.say(text)

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"trash": "<folder>"} asks about moving that folder to the trash,
        what goes read at once, so the shot finds the question there; without it the question is
        closed."""
        if "trash" not in step:
            if self._asked is not None:
                self.answer(False)
            return
        found = load(self._index.read(), self._root, folders=[str(step["trash"])])
        self._asked = found if found.going else None
        self.changed.emit()

    def shut(self) -> None:
        """For closing the window: nothing starts after; a removal going on is the scan thread's,
        which the library waits for. What the threads held is let go (A1.3)."""
        self._closed = True
        self._searcher.wait()
        self._asked = None
        self._history = self._library = None
        self._available = _gone

    def _get_question(self) -> dict[str, Any]:
        return question_of(self._asked) if self._asked is not None else {}

    question = QtProperty(dict, _get_question, notify=changed)  # {} when none
    busy = QtProperty(bool, lambda self: self._busy, notify=changed)


def _gone() -> bool:
    return False
