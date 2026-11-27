"""The same song more than once in the running app (R2.12, L09-needs-attention): what a group of
copies says in Needs attention, the Review… dialog over one group, and Move the others to the
trash.

- **A group** (`copy_rows`, `heading_text`, `badge_text`): its kept copy's title and artist, its
  lengths, "Exact copies" or "Likely", and a row per copy with its format and bit rate, its path,
  its plays and rating, the copy kept (a radio button, changeable) and those checked for the trash
  (exact copies checked at first, likely ones not; duplicates.initial), and why the copy proposed
  is kept ("Keep: lossless"). The choice of each group is the Needs attention list's
  (attention.AttentionModel), shared by its rows, its selection bar and the dialog.
- **Review…** (`Duplicates.open`): the group in a dialog of its own, drawn after T01's preview: a
  row per copy with its details (format, bit rate and sample rate, length, folder and file, album,
  plays and rating), the copy kept and those to the trash changeable, and the footer with what
  goes and Move the others to the trash.
- **Move the others to the trash** (`Duplicates.move`, or the selection bar's Move N to the trash,
  `move_checked`) asks first, naming what goes (R2.11, R6.8: "Move 2 songs to the trash?"); then,
  on a thread of its own: each copy checked moved to the system's trash (art.to_trash, `trash`),
  this computer's plays of those moved given to the copy kept (rootfiles.take_plays, through the
  play counts' keeping, `plays`), their rows taken out of the index, and the kept copy given their
  highest rating when higher than its own (written as a rating is, ratings.Writing, `write`), all
  one entry in the change history (history.Recording: the rating as a file written, the plays
  and the files moved noted), whose message offers Undo and says that Undo can't take files out
  of the trash (R2.11). Playlists naming a copy moved are slice 7's (R8, #24).

What each says is decided here as plain data and text, tested without a window; what a group holds
and the plan of a move are musikata_core.duplicates'."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import art, db, duplicates, history, rootfiles, scanner
from musikata_core.attention import Entry
from musikata_core.duplicates import Copy, Plan
from musikata_core.history import FileChange
from musikata_core.tags import Batch, Job, Outcome, Written

from .history import COPIES, IN_TRASH, ChangeHistory
from .models import plural, time_text

if TYPE_CHECKING:
    import sqlite3

    from .attention import AttentionModel

log = logging.getLogger(__name__)

KIND_NAMES = {"mp3": "MP3", "flac": "FLAC", "aac": "AAC", "alac": "ALAC", "vorbis": "Ogg Vorbis",
              "opus": "Opus", "wav": "WAV", "aiff": "AIFF"}  # fmt: skip
WHY = {
    duplicates.LOSSLESS_WINS: "Keep: lossless",
    duplicates.BITRATE_WINS: "Keep: higher bit rate",
    duplicates.PATH_WINS: "Keep: path matches tags",
    duplicates.PLAYS_WINS: "Keep: most played",
    duplicates.RATING_WINS: "Keep: higher rating",
}
NOT_THERE = "Nothing can be moved to the trash while the music folder isn't available"  # R2.10


# runs `fn` on this computer's plays (rootfiles.Keeping.change): its rows' key given
PlaysChange = Callable[[Callable[["sqlite3.Connection", str], object]], "Future[object]"]


# ---------- what a group and its copies say ----------


def format_text(c: Copy) -> str:
    """A copy's format as L09 shows it: FLAC · 44.1 kHz for a lossless one, MP3 · 320 kbps for
    the rest; what isn't known left out."""
    kind = KIND_NAMES.get(c.kind or "", (c.kind or "").upper())
    if duplicates.lossless(c.kind):
        rate = f"{c.sample_rate / 1000:g} kHz" if c.sample_rate else ""
    else:
        rate = f"{round(c.bitrate / 1000)} kbps" if c.bitrate else ""
    return " · ".join(p for p in (kind, rate) if p)


def details_text(c: Copy) -> str:
    """A copy's details in the Review… dialog: its bit rate and sample rate, its length."""
    parts = [
        f"{round(c.bitrate / 1000):,} kbps" if c.bitrate else "",
        f"{c.sample_rate / 1000:g} kHz" if c.sample_rate else "",
        time_text(c.length),
    ]
    return " · ".join(p for p in parts if p)


def lengths_text(copies: Sequence[Copy]) -> str:
    """The copies' lengths, each once, shortest first: 4:18; 4:44 and 4:45."""
    shown = sorted({time_text(c.length) for c in copies if c.length is not None},
                   key=lambda t: [int(x) for x in t.split(":")])  # fmt: skip
    if len(shown) <= 1:
        return "".join(shown)
    return ", ".join(shown[:-1]) + " and " + shown[-1]


def heading_text(e: Entry) -> str:
    """A group's line under its title: Lumen Drift · 4:44 and 4:45."""
    return " · ".join(p for p in (e.artist or "Unknown artist", lengths_text(e.copies)) if p)


def badge_text(e: Entry) -> str:
    """Exact copies (the same audio, A2.3), or Likely."""
    return "Likely" if e.likely else "Exact copies"


def copy_rows(e: Entry, kept: int, checked: frozenset[int]) -> list[dict[str, Any]]:
    """A group's copies as its rows show them (L09): the copy kept first, the rest in the group's
    order; each its song, whether it is kept or checked for the trash and an exact copy of the
    kept one, its format, path (folder and name), plays, rating and details, and on the copy
    MusiKata proposes, while it is kept, why."""
    by_id = {c.song: c for c in e.copies}
    keeper = by_id.get(kept, e.copies[0])
    out = []
    for c in sorted(e.copies, key=lambda c: c.song != keeper.song):
        folder, _, name = c.path.rpartition("/")
        out.append({
            "song": c.song, "kept": c.song == keeper.song,
            "checked": c.song in checked and c.song != keeper.song,
            "exact": duplicates.exact(c, keeper), "format": format_text(c), "path": c.path,
            "folder": folder, "name": name, "plays": plural(c.plays, "play"), "rating": c.rating,
            "details": details_text(c), "album": c.album,
            "why": WHY.get(e.why, "") if c.song == keeper.song == e.copies[0].song else "",
        })  # fmt: skip
    return out


def footer_text(p: Plan) -> str:
    """The Review… dialog's footer: what goes, what the copy kept will have, and what Undo can't
    do: 1 copy to the trash · the kept copy will have 55 plays and 4 stars · Undo can't take
    files out of the trash."""
    stars = p.stars if p.stars is not None else p.kept.rating
    rating = f" and {plural(stars, 'star')}" if stars else ""
    return (f"{bar_text(len(p.gone))} · the kept copy will have {plural(p.plays, 'play')}"
            f"{rating} · {IN_TRASH}")  # fmt: skip


def bar_text(n: int) -> str:
    """The selection bar (L09): 1 copy to the trash."""
    return f"{plural(n, 'copy', 'copies')} to the trash"


def move_label(n: int) -> str:
    """The bar's and the dialog's button: Move 1 to the trash."""
    return f"Move {n:,} to the trash"


def names_text(names: Sequence[str]) -> str:
    """Files named in a sentence: a.mp3; a.mp3 and b.m4a; a.mp3, b.m4a and 3 more."""
    if len(names) > 3:
        return ", ".join(names[:2]) + f" and {len(names) - 2:,} more"
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def question_of(plans: Sequence[Plan]) -> dict[str, Any]:
    """R2.11's question before a move (R6.8): Move 2 songs to the trash?, naming the files, what
    the kept copies take, and what Undo can't do."""
    gone = [c for p in plans for c in p.gone]
    names = [c.path.rpartition("/")[2] for c in gone]
    takes = "the copy kept takes" if len(plans) == 1 else "the copies kept take"
    return {
        "title": f"Move {plural(len(gone), 'song')} to the trash?",
        "detail": f"{names_text(names)} {'goes' if len(gone) == 1 else 'go'} to the system's"
        f" trash; {takes} their plays and highest rating. Undo can put those back, but can't"
        " take files out of the trash.",
        "yes": "Move to trash",
    }


def description_of(plans: Sequence[Plan], moved: int) -> str:
    """The move's entry in the change history (R4.9): Signal Fires: 1 copy to the trash; 3 copies
    of 2 songs to the trash."""
    if len(plans) == 1:
        return f"{plans[0].kept.title or plans[0].kept.path}: {bar_text(moved)}"
    return f"{plural(moved, 'copy', 'copies')} of {plural(len(plans), 'song')} to the trash"


def moved_text(moved: int, failed: Sequence[tuple[str, str]]) -> str:
    """The message after a move (R6.7, R2.11): what went, the first that didn't with why, and
    that Undo can't take files out of the trash."""
    if not moved and not failed:
        return "Nothing was moved to the trash"
    whole = moved + len(failed)
    what = (f"Moved {plural(moved, 'song')} to the trash" if not failed
            else f"Moved {moved:,} of {plural(whole, 'song')} to the trash")  # fmt: skip
    if failed:
        name, why = failed[0]
        more = f", and {len(failed) - 1:,} more" if len(failed) > 1 else ""
        what += f": {name} {why}{more}"
    if not moved:
        return what
    return f"{what}. The copies kept have their plays and rating; {IN_TRASH}"


# ---------- moving the others to the trash (R2.12, R2.11) ----------


@dataclass
class Moved:
    """How a move went: the copies moved to the trash, those that weren't (name and why), the
    rating's save and the number of plays moved."""

    trashed: list[Copy] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    outcome: Outcome[Written] = field(default_factory=Outcome)
    plays: int = 0


def move(
    root: str,
    plans: Sequence[Plan],
    trash: art.Trash,
    remove: Callable[[Sequence[str]], object],
    write: Callable[[Job], Written],
    record: history.Recording | None,
    plays: PlaysChange | None = None,
) -> Moved:
    """R2.12's Move the others to the trash, on the calling thread (never the GUI's): each copy
    of `plans` that goes moved to the trash (`trash`); this computer's plays of those moved given
    to the copy kept (`plays`, rootfiles.Keeping.change; None: none are counted); their rows taken
    out of the index (`remove`, scanner.remove); the kept copy given their highest rating
    (`write`, ratings.Writing); all one entry (`record`; None: the history is off), the rating a
    file of it and the plays and the files moved noted."""
    out = Moved()
    done: list[tuple[Plan, list[Copy]]] = []
    for p in plans:
        went = []
        for c in p.gone:
            name = c.path.rpartition("/")[2]
            path = scanner.full_path(root, c.path)
            if not os.path.exists(path):
                out.failed.append((name, "isn't there any more"))
            elif trash(path):
                log.info("moved %s, a copy of %s, to the trash", c.path, p.kept.path)
                went.append(c)
            else:
                out.failed.append((name, "couldn't be moved to the trash"))
        out.trashed += went
        if went:
            done.append((p, went))
    taken: dict[int, list[rootfiles.Entry]] = {}
    if done and plays is not None:

        def take(c: sqlite3.Connection, me: str) -> dict[int, list[rootfiles.Entry]]:
            return {p.kept.song: rootfiles.take_plays(c, me, p.kept.song,
                                                      [g.song for g in went],
                                                      [g.path for g in went])
                    for p, went in done}  # fmt: skip

        found = plays(take).result()
        taken = found if isinstance(found, dict) else {}
        out.plays = sum(e.count for moved in taken.values() for e in moved)
    if out.trashed:
        remove([c.path for c in out.trashed])
    jobs = []
    for p, went in done:
        best = duplicates.plan(duplicates.Group((p.kept, *went), False), p.kept.song,
                               {c.song for c in went})  # fmt: skip
        if record is not None:
            if taken.get(p.kept.song):
                record.note(FileChange(p.kept.path, p.kept.hash, {},
                                       plays_from=tuple(taken[p.kept.song])))  # fmt: skip
            for c in went:
                record.note(FileChange(c.path, c.hash, {}, trashed=True))
        if best.stars is not None:
            jobs.append(Job(scanner.full_path(root, p.kept.path), {"rating": best.stars}))
    batch: Batch[Written] = Batch(jobs, write, record=record, action=COPIES,
                                  description=description_of([p for p, _ in done],
                                                             len(out.trashed)))  # fmt: skip
    out.outcome = batch.run() if done else Outcome()
    for f in out.outcome.failed:
        log.warning("the rating of %s, the copy kept, wasn't written: %s", f.job.path, f.why)
    return out


def remover(root: str, index: db.Index) -> Callable[[Sequence[str]], object]:
    """The copies moved taken out of the index (scanner.remove: those whose file is gone)."""
    return lambda paths: scanner.remove(root, index, paths)


def plays_back(change: PlaysChange | None, own: Callable[[], str | None]) -> history.PlaysBack:
    """Undo's way to give back the plays a move took (history.PlaysBack): on this computer's rows
    through `change` (rootfiles.Keeping.change), when the entry is this computer's (`own`, its
    id); another computer's plays are its own file's, so its entry's are left as they are."""

    def back(computer: str, files: Sequence[history.FileUndo]) -> list[FileChange]:
        if change is None or computer != own():
            log.info("the plays moved on %s aren't this computer's to give back", computer)
            return []
        found = change(lambda c, _me: history.plays_back(c, _me, files)).result()
        return found if isinstance(found, list) else []

    return back


# ---------- the bridge ----------


class Duplicates(QObject):
    """Review… and Move the others to the trash (R2.12) over the groups of `model` (Needs
    attention's list, which keeps each group's choice): the dialog over one group, the question
    first (R2.11), then the move on `executor` (its own thread when None), written by `write`
    (ratings.Writing), kept in `changes` (None: no entry, no message), the files moved to the
    trash by `trash`, the plays given through `plays` (rootfiles.Keeping.change; None: none), the
    rows taken out by `remove`; then `done` is told (Library.reload) on this thread. `available`
    says whether the root is there (R2.10)."""

    changed = Signal()
    _moved = Signal(object)

    def __init__(
        self,
        root: str,
        model: AttentionModel,
        write: Callable[[Job], Written] | None,
        remove: Callable[[Sequence[str]], object],
        changes: ChangeHistory | None = None,
        plays: PlaysChange | None = None,
        trash: art.Trash = art.to_trash,
        done: Callable[[], object] | None = None,
        saved: Callable[[Sequence[Written]], object] | None = None,
        available: Callable[[], bool] = lambda: True,
        executor: Executor | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._model, self._write, self._remove = root, model, write, remove
        self._changes, self._plays, self._trash = changes, plays, trash
        self._done, self._saved, self._available = done, saved, available
        self._executor = executor
        self._about: str | None = None  # the group the dialog shows
        self._asked: list[str] | None = None  # the groups the question is about
        self._moving = False
        self._closed = False
        self._moved.connect(self._on_moved)
        model.choicesChanged.connect(self.changed)

    # ---------- the dialog ----------

    def entry(self) -> Entry | None:
        return self._model.entry_of(self._about) if self._about is not None else None

    def open(self, e: Entry) -> None:
        """Review… (R2.8): the group of copies `e` in its dialog."""
        self._about = e.about
        self.changed.emit()

    @Slot()
    def close(self) -> None:
        """Cancel, ×, or Esc: the dialog closes, the choice kept; while the question is open it
        closes first."""
        if self._asked is not None:
            self._asked = None
        else:
            self._about = None
        self.changed.emit()

    @Slot(int)
    def keep(self, song: int) -> None:
        """The copy `song` kept instead (its radio button)."""
        if self._about is not None:
            self._model.keep_copy(self._about, song)

    @Slot(int)
    def toggle(self, song: int) -> None:
        """The copy `song` checked for the trash, or not."""
        if self._about is not None:
            self._model.toggle_copy(self._about, song)

    # ---------- asking, then moving ----------

    @Slot()
    def move(self) -> None:
        """The dialog's Move the others to the trash: asks first (R2.11)."""
        if self._about is not None:
            self._ask([self._about])

    @Slot()
    def moveChecked(self) -> None:  # noqa: N802
        """The selection bar's Move N to the trash: every group's copies checked, asked first."""
        self._ask([about for about, _ in self._model.checked_plans()])

    def _ask(self, groups: list[str]) -> None:
        if self._moving or not self._plans(groups):
            return
        if not self._available():
            if self._changes is not None:
                self._changes.say(NOT_THERE)
            return
        self._asked = groups
        self.changed.emit()

    def _plans(self, groups: Sequence[str]) -> list[Plan]:
        plans = dict(self._model.checked_plans())
        return [plans[g] for g in groups if g in plans and plans[g].gone]

    @Slot(bool)
    def answer(self, yes: bool) -> None:
        """The question's answer: Move to trash, or Cancel (nothing moves)."""
        groups, self._asked = self._asked, None
        plans = self._plans(groups or [])
        if not yes or not plans or self._write is None:
            self.changed.emit()
            return
        self._moving = True
        self.changed.emit()
        record = self._changes.recording() if self._changes is not None else None
        root, trash, remove, write, plays = (self._root, self._trash, self._remove, self._write,
                                             self._plays)  # fmt: skip

        def job() -> None:
            try:
                out = move(root, plans, trash, remove, write, record, plays)
            except Exception as e:  # noqa: BLE001  (logged; the message says it failed)
                log.exception("moving copies to the trash failed")
                out = Moved(failed=[("the copies", f"weren't moved: {e}")])
            self._moved.emit(out)

        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="copies")
        self._executor.submit(job)

    @Slot(object)
    def _on_moved(self, out: Moved) -> None:
        self._moving = False
        if self._closed:
            return
        if out.trashed:
            self._about = None
        self.changed.emit()
        if out.outcome.saved and self._saved is not None:
            self._saved(out.outcome.saved)  # the kept copies' ratings, their rows read again
        elif self._done is not None:
            self._done()
        if self._changes is not None:
            self._changes.after_save(out.outcome, moved_text(len(out.trashed), out.failed))

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"review": "<title>"} opens the group of copies of that title in
        Review…; with "ask", its question too."""
        title = step.get("review")
        if not title:
            if self._about is not None or self._asked is not None:
                self._about = self._asked = None
                self.changed.emit()
            return
        found = self._model.entry_titled(str(title))
        if found is not None:
            self.open(found)
            if step.get("ask"):
                self.move()

    def shut(self) -> None:
        """For closing the window: a move going on is waited for; nothing starts after. What the
        threads held is let go (A1.3)."""
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._changes = self._saved = self._done = self._write = self._plays = None
        self._available = _gone

    # ---------- what QML reads ----------

    def _get_rows(self) -> list[dict[str, Any]]:
        e = self.entry()
        if e is None:
            return []
        kept, checked = self._model.choice_of(e)
        return copy_rows(e, kept, checked)

    def _get_title(self) -> str:
        e = self.entry()
        return f"Copies of {e.title}" if e is not None else ""

    def _get_about(self) -> str:
        e = self.entry()
        if e is None:
            return ""
        same = ("They share artist and title, with lengths within 2 seconds" if e.likely
                else "They are the same audio")  # fmt: skip
        return (f"{heading_text(e)}. {same}. The copy kept takes the others' plays and"
                " highest rating.")  # fmt: skip

    def _count(self) -> int:
        e = self.entry()
        if e is None:
            return 0
        kept, checked = self._model.choice_of(e)
        return len(checked - {kept})

    def _get_footer(self) -> str:
        if self._moving:
            return "Moving to the trash…"
        e = self.entry()
        if e is None or not self._count():
            return "Check the copies to move to the trash"
        kept, checked = self._model.choice_of(e)
        p = duplicates.plan(duplicates.Group(e.copies, e.likely, e.why), kept, checked)
        return footer_text(p)

    def _get_move_later(self) -> str:
        if self._moving:
            return "A move is going on"
        return "" if self._count() else "Nothing checked to move"

    def _get_question(self) -> dict[str, Any]:
        return question_of(self._plans(self._asked)) if self._asked else {}

    opened = QtProperty(bool, lambda self: self.entry() is not None, notify=changed)
    rows = QtProperty(list, _get_rows, notify=changed)
    title = QtProperty(str, _get_title, notify=changed)
    about = QtProperty(str, _get_about, notify=changed)
    badge = QtProperty(str, lambda self: badge_text(e) if (e := self.entry()) else "",
                       notify=changed)  # fmt: skip
    likely = QtProperty(bool, lambda self: bool((e := self.entry()) and e.likely), notify=changed)
    footer = QtProperty(str, _get_footer, notify=changed)
    moveLabel = QtProperty(str, lambda self: move_label(self._count()), notify=changed)
    moveLater = QtProperty(str, _get_move_later, notify=changed)
    question = QtProperty(dict, _get_question, notify=changed)  # {} when none
    moving = QtProperty(bool, lambda self: self._moving, notify=changed)


def _gone() -> bool:
    return False
