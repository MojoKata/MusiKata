"""Fix encoding… in the running app (R4.10, T06-fix-encoding): a song's tags its ID3 tag holds as
Latin-1, read each likely way side by side, the most likely first, as musikata_core.encodings
reads and ranks them; the user picks the reading that is right, for the song or for every song of
its album at once, and the choice is R3.7's preview (preview.Preview, shown when asked for) and
R3.8's save: a batch on a thread of its own, its progress in the footer, Cancel, the files that
failed named with Retry, written as Unicode in the root's ID3 version (R4.7.2), one entry in the
change history whose Undo puts the old bytes back (R4.9, history.FileChange.latin1).

It opens from Needs attention (an entry of Tags in the wrong text encoding, or its group's Fix
encoding…: `open`) and from the Edit tags panel's ⋯ menu when the songs it edits have such text
(`open_songs`). What it says is decided here as plain data and text (`reading_rows`,
`footer_text`, …), tested without a window."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import attention, encodings, scanner
from musikata_core.attention import Entry
from musikata_core.encodings import Reading
from musikata_core.tags import Batch, Failed, Job, Outcome, Tags, Written
from musikata_core.tags.tools import Planned, Song

from .history import ENCODING, LABELS, ChangeHistory
from .models import Searcher, plural
from .preview import Preview, failed_text, labels_text, progress_text, save_text

if TYPE_CHECKING:
    from .attention import AttentionModel

log = logging.getLogger(__name__)

ABOUT = (
    "These tags were saved as Latin-1 but read better another way. Choose the reading that is"
    " right."
)
CANT = "Can't be read this way"
LIKELY = "Most likely"
NOTHING = "Nothing to fix"  # the songs opened hold no text as Latin-1 beyond ASCII
NOT_THERE = "Saving waits until the music folder is back"  # R2.10

# a song as the dialog plans from it: its id, path under the root, and tags (Tags.latin1 said)
Found = tuple[int, str, Tags]


# ---------- what it says ----------


def title_text(path: str) -> str:
    """The dialog's title (T06): Fix encoding · 08 - Ìàÿê.mp3, the file's name."""
    return f"Fix encoding · {path.rpartition('/')[2]}" if path else "Fix encoding"


def reading_rows(readings: Sequence[Reading], chosen: int, flagged: bool) -> list[dict[str, Any]]:
    """The readings as T06 lists them: each its label, "Most likely" on the first when it reads
    far better than as it is (`flagged`), its text for each field or, when it can't read them,
    why, and whether it is the one chosen."""
    return [
        {
            "label": r.label,
            "badge": LIKELY if n == 0 and flagged else "",
            "texts": list(r.texts),
            "readable": r.readable,
            "note": "" if r.readable else CANT,
            "chosen": n == chosen,
        }
        for n, r in enumerate(readings)
    ]


def columns_of(names: Sequence[str]) -> list[dict[str, str]]:
    """The fields read, as T06's columns: Artist, Album, Title."""
    return [{"name": n, "label": LABELS.get(n, n)} for n in names]


def whole_text(songs: int, album: bool) -> str:
    """The checkbox that makes the choice every song's (R4.10): The same for every song of the
    album (9 songs); of the songs edited, opened from the Edit tags panel on several."""
    which = "of the album" if album else "edited"
    return f"The same for every song {which} ({plural(songs, 'song')})"


def footer_text(files: int, fields: Sequence[str], undoable: bool = True) -> str:
    """T06's footer (R3.8): 9 files · artist, album and title · written as Unicode; Undo puts the
    old bytes back."""
    if not files:
        return "Nothing will change"
    which = labels_text(fields).lower()
    then = (
        "Undo puts the old bytes back"
        if undoable
        else "the change history is off, so Undo can't put the old bytes back"
    )
    return f"{plural(files, 'file')} · {which} · written as Unicode; {then}"


def description_of(label: str, songs: int) -> str:
    """The save's entry in the change history (R4.9): Fix encoding: Cyrillic (Windows-1251) on
    9 songs."""
    return f"Fix encoding: {label} on {plural(songs, 'song')}"


def first_flagged(songs: Sequence[Found]) -> Found | None:
    """The song the dialog shows of those opened: the first with text held as Latin-1."""
    return next((s for s in songs if encodings.values_of(s[2])[0]), None)


# ---------- the dialog ----------


class FixEncoding(QObject):
    """Fix encoding… (R4.10, T06): over the songs of the index on `read`, one shown with its
    readings, saved by `write` (ratings.Writing, as every save) as one entry in `history`, the
    rows of the files written handed to `saved`; `model`, Needs attention's list, for the tour's
    entry. `undoable` says whether the history keeps its saves (R13.3); `available` whether the
    root is there (R2.10)."""

    changed = Signal()
    _progressed = Signal(int, int, str)
    _done = Signal(object)

    def __init__(
        self,
        root: str,
        read: Callable[[], sqlite3.Connection],
        write: Callable[[Job], Written] | None,
        history: ChangeHistory | None = None,
        saved: Callable[[Sequence[Written]], object] | None = None,
        undoable: bool = True,
        executor: Executor | None = None,
        available: Callable[[], bool] = lambda: True,
        model: AttentionModel | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._read, self._write = root, read, write
        self._history, self._saved, self._available = history, saved, available
        self._undoable = undoable and history is not None
        self._executor, self._model = executor, model
        self._searcher = Searcher(self)
        self._preview = Preview(root, parent=self)
        self._open = False
        self._loading = False
        self._ticket = 0
        self._song: Found | None = None
        self._scope: list[Found] = []
        self._album = True
        self._names: tuple[str, ...] = ()
        self._readings: list[Reading] = []
        self._flagged = False
        self._chosen = 0
        self._whole = True
        self._files = False
        self._batch: Batch[Written] | None = None
        self._progress = (0, 0)
        self._failed: list[Failed] = []
        self._problem = ""
        self._description = ""
        self._closed = False
        self._progressed.connect(self._on_progress)
        self._done.connect(self._on_done)
        self._preview.changed.connect(self.changed)

    # ---------- opening ----------

    def open(self, entry: Entry) -> None:
        """Fix encoding… on a Needs attention entry (R2.8): its song, and its album's songs."""
        if entry.kind == attention.ENCODING and entry.song is not None:
            self._load([entry.song], album=True)

    def open_songs(self, ids: Sequence[int]) -> None:
        """Fix encoding… from the Edit tags panel (R4.10): the first of the songs edited with
        text held as Latin-1; with it, its album's songs when it edits one song, else the songs
        it edits."""
        if ids:
            self._load(list(ids), album=len(ids) == 1)

    def _load(self, ids: list[int], album: bool) -> None:
        if self._batch is not None or self._closed:
            return
        self._open, self._loading, self._album = True, True, album
        self._song, self._scope, self._readings, self._names = None, [], [], ()
        self._failed, self._problem, self._files = [], "", False
        self._ticket += 1
        ticket, read = self._ticket, self._read
        self._plan()

        def work() -> tuple[Found | None, list[Found]]:
            c = read()
            found = attention.encoded_songs(c, ids)
            song = first_flagged(found)
            if song is None:
                return None, []
            scope = (
                attention.encoded_songs(c, attention.album_songs(c, song[0])) if album else found
            )
            return song, scope

        def then(result: tuple[Found | None, list[Found]] | None) -> None:
            if ticket != self._ticket or self._closed:
                return
            self._loading = False
            song, scope = result if result is not None else (None, [])
            self._song, self._scope = song, scope or ([song] if song is not None else [])
            if song is not None:
                self._names, values = encodings.values_of(song[2])
                self._readings = encodings.readings(values)
                self._flagged = encodings.likely(values) is not None
            self._chosen = 0
            self._whole = len(self._scope) > 1
            self._plan()

        self._searcher.submit(("encoding", id(self)), work, then)

    def _plan(self) -> None:
        reading = self._reading()
        if self._song is None or reading is None or reading.codec is None:
            planned = Planned((), (), ())
        else:
            chosen = self._scope if self._whole else [self._song]
            songs = [Song(scanner.full_path(self._root, p), t) for _i, p, t in chosen]
            planned = encodings.plan(songs, reading.codec)
        self._preview.show(planned, self._undoable)
        self.changed.emit()

    def _reading(self) -> Reading | None:
        return self._readings[self._chosen] if 0 <= self._chosen < len(self._readings) else None

    # ---------- the choices ----------

    @Slot(int)
    def choose(self, row: int) -> None:
        """A reading's radio button: that reading chosen, unless it can't read the tags."""
        if self._batch is not None or not 0 <= row < len(self._readings):
            return
        if self._readings[row].readable and row != self._chosen:
            self._chosen = row
            self._plan()

    @Slot()
    def toggleWhole(self) -> None:  # noqa: N802
        """The same for every song of the album: on, or this song alone."""
        if self._batch is None and len(self._scope) > 1:
            self._whole = not self._whole
            self._plan()

    @Slot()
    def toggleFiles(self) -> None:  # noqa: N802
        """The files the choice writes (R3.7's preview), shown in the readings' place, or not."""
        self._files = not self._files
        self.changed.emit()

    @Slot()
    def close(self) -> None:
        """Cancel, ×, or Esc: nothing saved; while a save goes on, it stops before its next
        file."""
        if self._batch is not None:
            self._batch.cancel()
            return
        if self._open:
            self._open, self._song, self._scope, self._readings = False, None, [], []
            self._failed, self._problem = [], ""
            self._ticket += 1
            self._preview.show(Planned((), (), ()))
            self.changed.emit()

    # ---------- saving (R3.8, R4.7) ----------

    @Slot()
    def save(self) -> None:
        """Save N files: the files checked written as Unicode, one entry in the change history;
        Retry when files failed: those written again."""
        if self._batch is not None or not self._available() or self._write is None:
            return
        if self._failed:
            jobs = [f.job for f in self._failed]
        else:
            jobs = self._preview.jobs()
            reading = self._reading()
            if not jobs or reading is None:
                return
            self._description = description_of(reading.label, len(jobs))
        record = self._history.recording() if self._history is not None else None
        batch: Batch[Written] = Batch(jobs, self._write, self._progressed.emit, record=record,
                                      action=ENCODING, description=self._description)  # fmt: skip
        self._batch, self._progress, self._failed = batch, (0, len(jobs)), []
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="encoding")
        self.changed.emit()
        self._executor.submit(self._run, batch, jobs)

    def _run(self, batch: Batch[Written], jobs: list[Job]) -> None:
        try:
            out = batch.run()
        except Exception as e:  # noqa: BLE001  (the batch fails its files, never itself; logged)
            log.exception("fixing the encoding failed")
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
            self._saved(out.saved)
        if self._history is not None:
            self._history.after_save(out)
        self._failed = list(out.failed)
        if self._failed:
            first = self._failed[0]
            name = first.job.path.replace("\\", "/").rpartition("/")[2]
            self._problem = f"{failed_text(len(self._failed))}: {name} {first.why}"
            self.changed.emit()
            return
        self._open = False
        self._song, self._scope, self._readings = None, [], []
        self._preview.show(Planned((), (), ()))
        self.changed.emit()

    # ---------- the tour, and closing ----------

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"fix": title} opens the dialog on the Needs attention entry of
        that title (as read the likely way); without it the dialog is closed."""
        title = step.get("fix")
        if title is None or self._model is None:
            if self._open:
                self.close()
            return
        found = self._model.entry_of_kind(attention.ENCODING, str(title))
        if found is not None:
            self.open(found)

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
        self._model = None
        self._available = _gone

    # ---------- what QML reads ----------

    def _get_footer(self) -> str:
        if self._batch is not None:
            return progress_text(*self._progress)
        if self._loading:
            return "Reading the songs…"
        return footer_text(self._preview.counts()[0], self._preview.fields(), self._undoable)

    def _get_save_label(self) -> str:
        if self._failed:
            return f"Retry {plural(len(self._failed), 'file')}"
        return save_text(self._preview.counts()[0])

    def _get_save_later(self) -> str:
        if self._batch is not None:
            return "A save is going on"
        if not self._available():
            return NOT_THERE
        if self._failed:
            return ""
        if not self._loading and self._song is None:
            return NOTHING
        return "" if self._preview.chosen() else "Nothing to save"

    def _get_readings(self) -> list[dict[str, Any]]:
        return reading_rows(self._readings, self._chosen, self._flagged)

    def _get_whole_text(self) -> str:
        return whole_text(len(self._scope), self._album) if len(self._scope) > 1 else ""

    opened = QtProperty(bool, lambda self: self._open, notify=changed)
    loading = QtProperty(bool, lambda self: self._loading, notify=changed)
    title = QtProperty(str, lambda self: title_text(self._song[1] if self._song else ""),
                       notify=changed)  # fmt: skip
    about = QtProperty(str, lambda self: ABOUT if self._song or self._loading else NOTHING,
                       notify=changed)  # fmt: skip
    columns = QtProperty(list, lambda self: columns_of(self._names), notify=changed)
    readings = QtProperty(list, _get_readings, notify=changed)
    whole = QtProperty(bool, lambda self: self._whole, notify=changed)
    wholeText = QtProperty(str, _get_whole_text, notify=changed)
    showFiles = QtProperty(bool, lambda self: self._files, notify=changed)
    preview = QtProperty(QObject, lambda self: self._preview, constant=True)
    footer = QtProperty(str, _get_footer, notify=changed)
    saveLabel = QtProperty(str, _get_save_label, notify=changed)
    saveLater = QtProperty(str, _get_save_later, notify=changed)
    saving = QtProperty(bool, lambda self: self._batch is not None, notify=changed)
    problem = QtProperty(str, lambda self: self._problem, notify=changed)


def _gone() -> bool:
    return False
