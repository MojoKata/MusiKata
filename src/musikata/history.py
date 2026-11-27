"""The change history in the running app (R4.9, R4.9.1, R6.7): the root's entries read into the
index at start (the old ones removed first, A3.5) and again when the watcher sees the history
folder change, another computer's included; ⋮ › **Change history**, a panel docked on the right
(as L03's Edit tags panel) listing the entries by day, each with the files it touched and the
computer that saved it, undoing any entry, or any file of it; Ctrl+Z / ⌘Z undoing the most recent
entry still in effect; and the message that follows a save or an undo, with **Undo** (R6.7).

Undo reads the entry and plans it on a thread of its own (history.plan): a file changed since
(R4.9.1) stops it for the question, which says what undoing would lose, file by file, and takes
the answer (overwrite them, skip them, or cancel); then the old values are written as another save
(history.undo), recorded as an entry when the history is on, the rows of the files written updated
in the index (`saved`, Library.saved), and the message says what was undone. One undo at a time.

What the panel, the question and the message say is decided here as plain data and text
(`view_rows`, `question_of`, `saved_text`, `undone_text`), tested without a window; the QML lays
it out. Nothing here reads a file or waits on the GUI thread."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import datetime, timedelta, tzinfo

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from musikata_core import art, db, history, rootfiles, scanner, settings, watch
from musikata_core.clock import Clock
from musikata_core.history import Lost, Plan, Recording, Row
from musikata_core.tags import Job, Outcome, Written
from musikata_core.tags import save as save_tags

log = logging.getLogger(__name__)

LISTED = 300  # the most recent entries the panel lists
FILES = 3  # the files an entry shows until it is opened whole
NOT_THERE = "Nothing can be undone while the music folder isn't available"  # R2.10
MESSAGE_MS = 8_000  # how long a message stays (R6.7: short-lived)
IN_TRASH = "Undo can't take files out of the trash"  # R2.11
LABELS = {
    "title": "Title", "artist": "Artist", "album": "Album", "albumartist": "Album artist",
    "track": "Track", "tracktotal": "Track total", "disc": "Disc", "disctotal": "Disc total",
    "year": "Year", "genres": "Genre", "composer": "Composer", "comment": "Comment",
    "compilation": "Compilation", "rating": "Rating", "artistsort": "Artist sort",
    "albumartistsort": "Album artist sort", "albumsort": "Album sort", "cover": "Cover",
    "others": "Other pictures", "plays": "Plays", "trashed": "Moved to the trash",
}  # fmt: skip
RATE = "rate"  # a save of ratings (R10.2)
ART = "album-art"  # a save of the Album art dialog, or Save cover to folder (R5.3, R5.5)
GENRE = "genres"  # a genre renamed or merged (R9.4, R9.5)
NAMES = "names"  # an artist's or an album's names merged, from Needs attention (R2.8)
COPIES = "copies"  # a song's other copies moved to the trash (R2.12)
ACTIONS = {history.ACTION: "Edited tags", history.UNDO: "Undo", RATE: "Rated songs",
           ART: "Album art", GENRE: "Genres", NAMES: "Names merged",
           COPIES: "Copies moved to the trash"}  # fmt: skip  # an entry
# with no description, by its action


# ---------- what the panel, the question and the message say ----------


def day_text(day: datetime, today: datetime) -> str:
    """A day's heading: Today, Yesterday, else its date in full (Tuesday, November 24, 2026)."""
    if day.date() == today.date():
        return "Today"
    if day.date() == (today - timedelta(days=1)).date():
        return "Yesterday"
    return f"{day:%A}, {day:%B} {day.day}, {day.year}"


def clock_text(when: datetime) -> str:
    """A time of day as the lists show it: 8:45 PM."""
    hour = when.hour % 12 or 12
    return f"{hour}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}"


def computer_text(computer: str, own: str | None, own_name: str, names: Mapping[str, str]) -> str:
    """The computer that saved an entry (R4.9): this computer's name, another's as its play file
    names it (A2.8), else "another computer" and the start of its id."""
    if computer == own:
        return own_name
    return names.get(computer) or f"another computer ({computer[:8]})"


def files_text(n: int) -> str:
    return f"{n:,} file" if n == 1 else f"{n:,} files"


def title_of(row: Row) -> str:
    """What an entry was, for its heading: its description, else what its action was."""
    return row.description or ACTIONS.get(row.action, row.action)


def view_rows(
    rows: Sequence[Row],
    undone: Collection[str],
    now: datetime,
    own: str | None,
    own_name: str,
    names: Mapping[str, str],
    zone: tzinfo | None = None,
) -> list[dict[str, object]]:
    """The panel's list (R4.9), newest first, by day in the local zone (`zone`; None: the
    system's): a heading per day ("day"), each entry ("entry": its name, what it was, when, on
    which computer and how many files, whether it is undone and whether it is an undo), its files
    ("file": the file's name, its folder, the fields it changed, its place in the entry) and, when
    some aren't listed, how many more ("more")."""
    out: list[dict[str, object]] = []
    today = now.astimezone(zone)
    day = None
    for r in rows:
        local = r.time.astimezone(zone)
        if local.date() != day:
            day = local.date()
            out.append({"kind": "day", "text": day_text(local, today)})
        line = " · ".join(
            (clock_text(local), computer_text(r.computer, own, own_name, names),
             files_text(r.file_count))
        )  # fmt: skip
        out.append({
            "kind": "entry", "name": r.name, "text": title_of(r), "line": line,
            "undone": r.name in undone, "isUndo": r.action == history.UNDO,
        })  # fmt: skip
        for n, (path, fields) in enumerate(r.files):
            folder, name = path.rpartition("/")[::2]
            out.append({
                "kind": "file", "name": r.name, "position": n, "text": name, "folder": folder,
                "fields": ", ".join(LABELS.get(f, f) for f in fields),
            })  # fmt: skip
        more = r.file_count - len(r.files)
        if more > 0:
            noun = "file" if more == 1 else "files"
            out.append({"kind": "more", "name": r.name, "text": f"{more:,} more {noun}"})
    return out


def value_text(field: str, value: object) -> str:
    """A field's value as the question shows it: — for none, genres joined, stars, Yes or No."""
    if field == "cover":
        return "a cover" if value else "no cover"
    if field == "others":  # the other pictures' hashes (R5.3)
        n = len(value) if isinstance(value, tuple | list) else 0
        return (
            "no other pictures" if not n else "1 other picture" if n == 1 else f"{n} other pictures"
        )
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field == "rating":
        return f"{value} stars" if value != 1 else "1 star"
    if isinstance(value, list):
        return "; ".join(str(v) for v in value) or "—"
    return str(value)


def lost_text(lost: Lost) -> str:
    """What undoing would lose of one field (R4.9.1): Title: Spring Tide (edit) → Neap Tide."""
    label = LABELS.get(lost.field, lost.field)
    return f"{label}: {value_text(lost.field, lost.now)} → {value_text(lost.field, lost.back)}"


def question_of(plan: Plan) -> dict[str, object]:
    """R4.9.1's question, for the files changed since the entry: its heading, a line per file
    with what undoing it would lose, and whether skipping them leaves files to undo."""
    changed = plan.changed
    lines = []
    for f in changed:
        name = (f.path or f.change.path).rpartition("/")[2]
        lines.append({"file": name, "lost": "; ".join(lost_text(x) for x in f.lost)})
    rest = [f for f in plan.files if not f.why and not f.lost]
    n = len(changed)
    return {
        "title": f"{files_text(n)} changed since this save" if n != 1
        else "1 file has changed since this save",
        "detail": "Undoing puts back the old values over what is there now:",
        "lines": lines,
        "skip": bool(rest),
        "skipText": f"Undo the other {files_text(len(rest))}" if rest else "",
    }  # fmt: skip


def saved_text(outcome: Outcome[Written]) -> str:
    """The message after a save (R6.7): how many files were saved, and those that weren't, or
    that a cancel left (R4.7)."""
    done, failed = len(outcome.saved), len(outcome.failed)
    if outcome.cancelled:
        whole = done + failed + len(outcome.left)
        return f"Saved {done:,} of {files_text(whole)}: cancelled before the rest"
    if not failed:
        return f"Saved {files_text(done)}"
    first = outcome.failed[0]
    return (
        f"Saved {done:,} of {files_text(done + failed)}: "
        f"{os.path.basename(first.job.path)} {first.why}"
        + (f", and {failed - 1:,} more" if failed > 1 else "")
    )


def undone_text(outcome: Outcome[Written], what: str, skipped: int = 0, in_trash: int = 0) -> str:
    """The message after an undo: what was undone, and the files that couldn't be or were left
    (R4.9.1), or that stay in the trash (R2.11)."""
    done, failed = len(outcome.saved), len(outcome.failed)
    text = f"Undone: {what}"
    if failed:
        first = outcome.failed[0]
        text = (
            f"Undid {done:,} of {files_text(done + failed)}: "
            f"{os.path.basename(first.job.path)} {first.why}"
            + (f", and {failed - 1:,} more" if failed > 1 else "")
        )
    if skipped:
        left = "it is" if skipped == 1 else "they are"
        text += f" ({files_text(skipped)} changed since left as {left})"
    if in_trash:
        stays = "stays" if in_trash == 1 else "stay"
        text += f"; {files_text(in_trash)} moved to the trash {stays} there"
    return text


# ---------- the bridge ----------


class ChangeHistory(QObject):
    """The root's change history as the window sees it: the panel's rows, whether it is open, the
    question (R4.9.1) and the message (R6.7). `computer` gives this computer's id, made when it has
    none (app.Once), for the entries it writes; `own` and `own_name` are its id, None when it
    has none yet, and name. `tags_settings` are the root's (settings.root_tags): the history on or
    off and its days, the ID3 version and modification times an undo writes with. `saved` is told
    of the files an undo wrote (Library.saved), on this thread. The work runs on `executor`, one
    job at a time (its own thread when None); `watching` watches the history folder; `zone` is
    the local zone the days are in (None: the system's). `write` writes a file of an undo
    (ratings.Writing, so a rating goes back where it is kept; safe.save with the root's settings
    when None) and `look` reads a file as it is now for R4.9.1 (history.looking; history.current
    when None). `plays` gives back the plays an entry moved (R2.12; duplicates.plays_back; None:
    they aren't)."""

    changed = Signal()  # the rows, or whether the panel is open
    messageChanged = Signal()
    questionChanged = Signal()
    _read = Signal(object)  # from the thread: the computers' names, after a read
    _planned = Signal(object)  # a Plan, or why there is none
    # an undo's outcome, what it undid, the files skipped, this computer's id, made by then, and
    # the files it left in the trash
    _undone = Signal(object, str, int, object, int)

    def __init__(
        self,
        root: str,
        index: db.Index,
        clock: Clock,
        computer: Callable[[], str | None],
        own: str | None,
        own_name: str,
        tags_settings: settings.RootTags,
        saved: Callable[[Sequence[Written]], object] | None = None,
        executor: Executor | None = None,
        watching: bool = True,
        zone: tzinfo | None = None,
        message_ms: int = MESSAGE_MS,
        parent: QObject | None = None,
        write: Callable[[Job], Written] | None = None,
        look: Callable[[str, bool], history.Current] | None = None,
        available: Callable[[], bool] = lambda: True,
        plays: history.PlaysBack | None = None,
    ) -> None:
        """`available` says whether the root is there: while it isn't, undo changes no file and
        says why (R2.10)."""
        super().__init__(parent)
        self._writer, self._look, self._available = write, look, available
        self.plays = plays
        self._root, self._index, self._clock = root, index, clock
        self._computer, self._own, self._own_name = computer, own, own_name
        self._settings, self._saved, self._zone = tags_settings, saved, zone
        self._executor = executor
        self._watching = watching
        self._musikata = rootfiles.folder_of(root)
        self._folder = history.folder_of(root)
        self._watcher: watch.Watcher | None = None
        self._names: dict[str, str] = {}
        self._expanded: set[str] = set()
        self._rows: list[dict[str, object]] = []
        self._open = False
        self._loading = False  # reading or undoing: the tour waits for it
        self._busy = False  # an undo is planned or written
        self._plan: Plan | None = None  # waiting on the question's answer
        self._question: dict[str, object] = {}
        self._message: dict[str, object] = {}
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(message_ms)
        self._timer.timeout.connect(self.dismiss)
        self._read.connect(self._on_read)
        self._planned.connect(self._on_planned)
        self._undone.connect(self._on_undone)

    # ---------- reading the entries ----------

    def _submit(self, job: Callable[[], object]) -> None:
        if self._closed:
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="history")
        self._executor.submit(self._run, job)

    @staticmethod
    def _run(job: Callable[[], object]) -> None:
        try:
            job()
        except Exception:  # noqa: BLE001  (a job that breaks is logged; MusiKata goes on)
            log.exception("the change history failed")

    def start(self) -> None:
        """At start (A3.5): the entries past their age removed, the folder read into the index,
        off this thread; then the history folder watched."""
        self._loading = True
        if self._watching and os.path.isdir(self._musikata):
            self._watcher = watch.Watcher(self._musikata, watch.Gatherer(self._clock), parent=self)
            self._watcher.ready.connect(self._on_ready)
        days = self._settings.history_days
        self._submit(lambda: self._after_read(
            history.start(self._index, self._folder, self._clock.now(), days)
        ))  # fmt: skip

    def refresh(self) -> None:
        """The folder read into the index again (the watcher saw it change, an undo wrote)."""
        self._submit(lambda: self._after_read(history.refresh(self._index, self._folder)))

    def _after_read(self, _done: object) -> None:
        """On the thread, after a read: the computers' names, for the panel."""
        computers = [
            c for (c,) in self._index.read().execute("SELECT DISTINCT computer FROM change")
        ]
        others = [c for c in computers if c != self._own]
        self._read.emit(history.computer_names(self._musikata, others))

    @Slot(object)
    def _on_read(self, names: dict[str, str]) -> None:
        self._names = names
        self._loading = self._busy
        if self._watcher is not None:
            self._watcher.watch({"": self._musikata, history.FOLDER: self._folder})
        self.reload()

    @Slot()
    def _on_ready(self) -> None:
        assert self._watcher is not None
        if self._watcher.take():
            self.refresh()

    def reload(self) -> None:
        """The panel's rows read again from the index."""
        c = self._index.read()
        listed = history.rows(c, LISTED, FILES, self._expanded)
        self._rows = view_rows(
            listed, history.undone(c), self._clock.now(), self._own, self._own_name, self._names,
            self._zone,
        )  # fmt: skip
        self.changed.emit()

    # ---------- the panel ----------

    @Slot()
    def show(self) -> None:
        """⋮ › Change history (R4.9, R6.6): the panel opens, its list read again."""
        self._open = True
        self.reload()

    @Slot()
    def hide(self) -> None:
        self._open = False
        self.changed.emit()

    def go(self, step: Mapping[str, object]) -> None:
        """A tour's step (A1.6): the panel open when it says {"history": True}, else closed."""
        if step.get("history"):
            self.show()
        elif self._open:
            self.hide()

    @Slot(str)
    def expand(self, name: str) -> None:
        """An entry's files listed whole."""
        self._expanded.add(name)
        self.reload()

    # ---------- undoing ----------

    def recording(self, undoes: str | None = None) -> Recording | None:
        """What a save's batch is given to keep it in the history (tags.Batch's `record`); None
        when the root's settings turn the history off (R13.3)."""
        if not self._settings.history:
            return None
        return Recording(self._root, self._computer, self._clock, undoes)

    @Slot()
    def undoLast(self) -> None:  # noqa: N802
        """Ctrl+Z / ⌘Z (R4.9, R6.9): the most recent entry still in effect undone."""
        name = history.last(self._index.read())
        if name is None:
            self.say("Nothing to undo")
            return
        self.undo(name)

    @Slot(str)
    def undo(self, name: str) -> None:
        """Undo on an entry (the panel, the message): all its files."""
        self._plan_undo(name, None)

    @Slot(str, int)
    def undoFile(self, name: str, position: int) -> None:  # noqa: N802
        """Undo on one file of an entry (R4.9: file by file)."""
        self._plan_undo(name, {position})

    def _plan_undo(self, name: str, which: Collection[int] | None) -> None:
        if not self._available():  # R2.10: no change to files while the root isn't there
            self.say(NOT_THERE)
            return
        if self._busy:
            log.info("an undo is still going on: %s waits for another try", name)
            return
        self._busy = self._loading = True
        self.changed.emit()
        root, folder, look = self._root, self._folder, self._look

        def job() -> None:
            entry = history.read(folder, name)
            if isinstance(entry, history.Broken):
                self._planned.emit(f"This change can't be undone: {entry.why}")
                return
            find = history.finder(self._index.read())
            self._planned.emit(history.plan(entry, root, find, which, look or history.current))

        self._submit(job)

    @Slot(object)
    def _on_planned(self, planned: Plan | str) -> None:
        if (not isinstance(planned, str) and planned.in_trash
                and len(planned.in_trash) == len(planned.files)):  # fmt: skip
            planned = IN_TRASH  # a file moved to the trash alone (R2.11): nothing to undo
        if isinstance(planned, str):
            self._busy = self._loading = False
            self.say(planned)
            self.changed.emit()
            return
        if planned.changed:  # R4.9.1: asked first
            self._plan = planned
            self._question = question_of(planned)
            self._open = True
            self.questionChanged.emit()
            self.changed.emit()
            return
        self._write(planned, overwrite=False)

    @Slot(str)
    def answer(self, choice: str) -> None:
        """R4.9.1's answer: "overwrite" undoes the files changed since too, "skip" only the
        others, "cancel" nothing."""
        planned, self._plan = self._plan, None
        self._question = {}
        self.questionChanged.emit()
        if planned is None:
            return
        if choice == "cancel" or (choice == "skip" and not question_of(planned)["skip"]):
            self._busy = self._loading = False
            self.changed.emit()
            return
        self._write(planned, overwrite=choice == "overwrite")

    def _write(self, planned: Plan, overwrite: bool) -> None:
        root = self._root
        record = self.recording(planned.entry.name)
        tags_settings = self._settings
        skipped = 0 if overwrite else len(planned.changed)
        what = planned.entry.description or ACTIONS.get(planned.entry.action, "the change")

        def save_one(job: Job) -> Written:
            return save_tags(
                job.path, job.changes, audio_hash=scanner.audio_hash,
                id3_version=tags_settings.id3_version,
                keep_mtime=tags_settings.keep_modified_times,
                rating_scale=tags_settings.rating_scale,
            )  # fmt: skip

        write = self._writer or save_one

        plays = self.plays
        in_trash = len(planned.in_trash)

        def job() -> None:
            out = history.undo(planned, root, overwrite, write, record, plays=plays)
            history.refresh(self._index, self._folder)
            self._undone.emit(out, what, skipped, self._computer() if out.entry else None,
                              in_trash)  # fmt: skip

        self._submit(job)

    @Slot(object, str, int, object, int)
    def _on_undone(
        self, out: Outcome[Written], what: str, skipped: int, own: str | None, in_trash: int
    ) -> None:
        self._busy = False
        self._own = self._own or own  # its entries named as this computer's from now on
        if out.saved and self._saved is not None:  # their rows, on this thread (Library.saved)
            self._saved(art.written_songs(out.saved))  # a cover.jpg's folder is rescanned
        self._message = {"text": undone_text(out, what, skipped, in_trash),
                         "undo": out.entry or ""}  # fmt: skip
        self._timer.start()
        self.messageChanged.emit()
        self._on_read(self._names)

    # ---------- the message (R6.7) ----------

    def after_save(self, outcome: Outcome[Written], text: str = "") -> None:
        """A save finished (the panel's, R3's, …): its message (`text`, else `saved_text`), with
        Undo when it made an entry."""
        self._message = {"text": text or saved_text(outcome), "undo": outcome.entry or ""}
        self._timer.start()
        self.messageChanged.emit()
        self.refresh()

    def say(self, text: str) -> None:
        """A short-lived message (R6.7) with no Undo: why something can't be done now."""
        self._message = {"text": text, "undo": ""}
        self._timer.start()
        self.messageChanged.emit()

    @Slot()
    def undoMessage(self) -> None:  # noqa: N802
        """Undo in the message: the entry the save, or the undo, it follows made."""
        name = str(self._message.get("undo") or "")
        self.dismiss()
        if name:
            self.undo(name)

    @Slot()
    def dismiss(self) -> None:
        self._timer.stop()
        if self._message:
            self._message = {}
            self.messageChanged.emit()

    def close(self) -> None:
        """Stops watching and waits for the job running; nothing starts after. What the threads
        held is let go, so this object goes with its window (A1.3)."""
        self._closed = True
        self._timer.stop()
        if self._watcher is not None:
            self._watcher.close()
            self._watcher = None
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._plan = None
        self._saved = self._writer = self._look = self.plays = None

    # ---------- what QML reads ----------

    def _get_rows(self) -> list[dict[str, object]]:
        return self._rows

    def _get_opened(self) -> bool:
        return self._open

    def _get_loading(self) -> bool:
        return self._loading

    def _get_busy(self) -> bool:
        return self._busy

    def _get_question(self) -> dict[str, object]:
        return self._question

    def _get_message(self) -> dict[str, object]:
        return self._message

    def _get_count_text(self) -> str:
        n = sum(1 for r in self._rows if r["kind"] == "entry")
        return f"{n:,} save" if n == 1 else f"{n:,} saves"

    def _get_empty_text(self) -> str:
        if self._rows or self._loading:
            return ""
        if not self._settings.history:
            return "The history of tag changes is off for this music folder"
        return f"No changes yet. Each save is kept here for {self._settings.history_days} days."

    rows = QtProperty(list, _get_rows, notify=changed)
    opened = QtProperty(bool, _get_opened, notify=changed)
    loading = QtProperty(bool, _get_loading, notify=changed)
    busy = QtProperty(bool, _get_busy, notify=changed)
    countText = QtProperty(str, _get_count_text, notify=changed)
    emptyText = QtProperty(str, _get_empty_text, notify=changed)
    question = QtProperty(dict, _get_question, notify=questionChanged)  # {} when none
    message = QtProperty(dict, _get_message, notify=messageChanged)  # {} when none
