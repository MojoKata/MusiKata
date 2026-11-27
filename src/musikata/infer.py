"""Infer from path in the running app (R3, T01-infer-from-path): the Infer tags from path dialog
over the songs it was opened on, each read against its own path under the root.

It opens on a folder of songs (R2.9.7's strip, `open_folder`), a selection of folders and files
or of songs (the selection bars and right-click menus, R2.9.6, `openSelection`, `openRow`), an
album's page (`openAlbum`), the Edit tags panel's ⋯ menu (R4.5.5, `open_songs`) and Needs
attention's Tags that differ from the path (R2.8, `open`). Its songs are read off the GUI thread;
then every pattern (the user's own, then the presets, R3.3) is tried on every file and the one
that fits the most is chosen (R3.4, patterns.detect), the picker beside the field saying how many
it fits and listing the others with theirs. The field can be edited, the preview following as the
user types, and a token below it inserts itself (R3.4.1); the radio buttons choose Only fill empty
tags or Correct tags that differ (R3.5), the checkboxes R3.6's tidying. The preview is R3.7's
(preview.Preview), the files the pattern doesn't fit last with "Doesn't fit the pattern"; Save N
files writes the files checked through the batch, with its progress, Cancel and Retry, as one
entry in the change history whose Undo puts the old values back (R3.8, R4.7, R4.9).

What the dialog says is decided here as plain data and text (`picker_text`, `tidy_text`, …),
tested without a window; what a pattern reads and the change it makes are
musikata_core.patterns'."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import attention, patterns, scanner
from musikata_core import folders as index_folders
from musikata_core.attention import Entry
from musikata_core.patterns import Fit, Options, Pattern
from musikata_core.tags import Batch, Failed, Job, Outcome, Tags, Written
from musikata_core.tags.tools import Planned, Song

from .history import INFER, ChangeHistory
from .models import Searcher, plural
from .preview import Preview, failed_text, footer_text, labels_text, progress_text, save_text

log = logging.getLogger(__name__)

TITLE = "Infer tags from path"
NOT_THERE = "Saving waits until the music folder is back"  # R2.10
NO_SONGS = "No songs to read"
# R3.6's checkboxes, in T01's order, each its option and label
CHECKS = (("tidy_case", "Tidy case"), ("year_from_folder", "Year from folder"),
          ("underscores", "Underscores as spaces"), ("track_total", "Track total"))  # fmt: skip
MODES = (("fill", "Only fill empty tags"), ("correct", "Correct tags that differ"))  # R3.5

# a song as the dialog plans from it: its id, path under the root, and the tags a path gives
Found = tuple[int, str, Tags]


# ---------- what it says ----------


def about_text(root: str, home: str = "") -> str:
    """What the dialog does (T01): Read each file's path under ~/Music, and fill or correct its
    tags from it. Nothing is written until you save."""
    shown = root
    if home and (root == home or root.startswith(home.rstrip(os.sep) + os.sep)):
        shown = "~" + root[len(home.rstrip(os.sep)) :]
    return (
        f"Read each file's path under {shown}, and fill or correct its tags from it. Nothing is"
        " written until you save."
    )


def fits_text(fits: int, files: int) -> str:
    """How many of the files a pattern fits: 9 of 9 fit."""
    return f"{fits:,} of {files:,} fit"


def picker_text(fits: int, files: int, detected: bool, problem: str = "") -> str:
    """The picker beside the pattern (R3.4): Detected · 9 of 9 fit, for the pattern detection
    chose; the count alone for another; why a pattern typed can't be used."""
    if problem:
        return problem
    return f"Detected · {fits_text(fits, files)}" if detected else fits_text(fits, files)


def choices_of(fits: Sequence[Fit], files: int, chosen: str) -> list[dict[str, Any]]:
    """The picker's list (R3.4): every pattern tried, the most fitting first, with its count, and
    the one in the field."""
    return [
        {
            "text": f.pattern.text,
            "label": fits_text(f.fits, files),
            "chosen": f.pattern.text == chosen,
        }
        for f in fits
    ]


def parts_of(pattern: Pattern) -> list[dict[str, str]]:
    """The pattern as its field shows it (R3.4.1, T01): each token a chip, the text between them
    as written; none for a pattern that can't be used, which shows as typed."""
    if pattern.problem:
        return []
    return [
        {"kind": kind, "text": "{" + value + "}" if kind == "token" else value}
        for kind, value in pattern.parts
    ]


def tokens_of() -> list[str]:
    """The tokens below the field (T01), each inserted by a click (R3.4.1)."""
    return ["{" + t + "}" for t in patterns.TOKENS] + ["{" + patterns.SKIP + "}"]


def tidy_text(planned: Planned) -> str:
    """Tidy case's checkbox (T01): with an example of what it changes, a value it changes only in
    case first (lumen drift → Lumen Drift)."""
    for i, song in enumerate(planned.songs):
        for field in patterns.TEXT_FIELDS:
            old, new = getattr(song.tags, field), getattr(planned.new[i], field)
            if old and new and old != new and old.casefold() == new.casefold():
                return f"Tidy case ({old} → {new})"
    return "Tidy case"


def year_text(years: Sequence[int | None]) -> str:
    """Year from folder's checkbox (T01): with the year the folders name most (2022)."""
    found = Counter(y for y in years if y is not None)
    if not found:
        return "Year from folder"
    return f"Year from folder ({found.most_common(1)[0][0]})"


def checks_of(
    options: Options, planned: Planned, years: Sequence[int | None], underscores: bool = True
) -> list[dict[str, Any]]:
    """R3.6's checkboxes, each its option, label and whether it is on; Underscores as spaces only
    when a path has one (`underscores`), as it changes nothing otherwise."""
    labels = {"tidy_case": tidy_text(planned), "year_from_folder": year_text(years)}
    return [
        {"name": name, "label": labels.get(name, label), "on": bool(getattr(options, name))}
        for name, label in CHECKS
        if name != "underscores" or underscores
    ]


def modes_of(options: Options) -> list[dict[str, Any]]:
    """R3.5's radio buttons, each its name, label and whether it is chosen."""
    return [
        {"name": name, "label": label, "chosen": options.fill_only == (name == "fill")}
        for name, label in MODES
    ]


def description_of(fields: Sequence[str], songs: int) -> str:
    """What the save was, for the change history (R4.9): Infer from path: Artist and Year on 4
    songs."""
    return f"Infer from path: {labels_text(fields)} on {plural(songs, 'song')}"


# ---------- the dialog ----------


class InferFromPath(QObject):
    """The Infer tags from path dialog (R3, T01) over the songs of the index on `read`, saved by
    `write` (ratings.Writing, as every save) as one entry in `history`, the rows of the files
    written handed to `saved`. `undoable` says
    whether the history keeps its saves (R13.3); `available` whether the root is there (R2.10);
    `home` shortens the root in what it says."""

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
        home: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._read, self._write, self._home = root, read, write, home
        self._history, self._saved, self._available = history, saved, available
        self._undoable = undoable and history is not None
        self._executor = executor
        self._searcher = Searcher(self)
        self._preview = Preview(root, parent=self)
        self._open = self._loading = self._closed = False
        self._ticket = 0
        self._songs: list[Found] = []
        self._counts: dict[str, int] = {}
        self._tried: list[Pattern] = []
        self._fits: list[Fit] = []
        self._detected = ""
        self._text = ""
        self._pattern = patterns.parse("")
        self._options = patterns.DEFAULTS
        self._planned = Planned((), (), ())
        self._batch: Batch[Written] | None = None
        self._progress = (0, 0)
        self._failed: list[Failed] = []
        self._problem = ""
        self._description = ""
        self._progressed.connect(self._on_progress)
        self._done.connect(self._on_done)
        self._preview.changed.connect(self.changed)

    # ---------- opening (R3.1) ----------

    def open_songs(self, ids: Sequence[int]) -> None:
        """Opens on the songs of `ids`, in that order."""
        ids = [int(i) for i in ids]
        self._load(lambda c: ids)

    def open_folder(self, folder: str) -> None:
        """Opens on a folder's own songs, by name (R2.9.7)."""
        self._load(lambda c: [int(i) for (i,) in c.execute(
            "SELECT id FROM song WHERE folder = ? ORDER BY name_key, path", (folder,)
        )])  # fmt: skip

    def open(self, entry: Entry) -> None:
        """Infer from path on a Needs attention entry of Tags that differ from the path (R2.8):
        its folder's songs."""
        if entry.kind == attention.PATH:
            self.open_folder(attention.folder_of(entry.about))

    @Slot(str)
    def openFolder(self, folder: str) -> None:  # noqa: N802
        self.open_folder(folder)

    @Slot(int)
    def openAlbum(self, album_id: int) -> None:  # noqa: N802
        """An album's page (R3.1): its songs, in its order."""
        self._load(lambda c: [int(i) for (i,) in c.execute(
            f"SELECT id FROM song WHERE album_id = ? ORDER BY {attention.SONG_ORDER}", (album_id,)
        )])  # fmt: skip

    @Slot(QObject)
    def openSelection(self, model: QObject) -> None:  # noqa: N802
        """A selection bar's Infer from path (R2.9.6, L03): the songs `model` has selected, a
        folder's every song beneath it."""
        self.open_songs(model.selected_songs())  # type: ignore[attr-defined]

    @Slot(QObject, int)
    def openRow(self, model: QObject, row: int) -> None:  # noqa: N802
        """A right-click menu's Infer from path: the selection when the row is in it, else the
        row's song or the songs beneath its folder (R2.9.6)."""
        if model.is_selected(row):  # type: ignore[attr-defined]
            self.openSelection(model)
        else:
            self.open_songs(model.songs_at(row))  # type: ignore[attr-defined]

    def _load(self, ids_of: Callable[[sqlite3.Connection], list[int]]) -> None:
        if self._batch is not None or self._closed:
            return
        self._open, self._loading = True, True
        self._songs, self._fits, self._failed, self._problem = [], [], [], ""
        self._text, self._pattern, self._options = "", patterns.parse(""), patterns.DEFAULTS
        self._ticket += 1
        ticket, read = self._ticket, self._read
        self._plan()

        def work() -> tuple[list[Found], dict[str, int], list[str]]:
            c = read()
            found = index_folders.tags_of(c, ids_of(c))
            folders = [p.rpartition("/")[0] for _, p, _ in found]
            return found, index_folders.counts_of(c, folders), index_folders.user_patterns(c)

        def then(result: tuple[list[Found], dict[str, int], list[str]] | None) -> None:
            if ticket != self._ticket or self._closed:
                return
            self._loading = False
            found, counts, user = result if result is not None else ([], {}, [])
            self._songs, self._counts = found, counts
            self._tried = patterns.patterns_of(user)
            self._detect()
            self._text = self._detected
            self._pattern = patterns.parse(self._text)
            self._plan()

        self._searcher.submit(("infer", id(self)), work, then)

    def _detect(self) -> None:
        """R3.4: every pattern tried on every file, the most fitting first."""
        paths = [p for _, p, _ in self._songs]
        self._fits = patterns.detect(self._tried, paths, self._options.underscores)
        self._detected = self._fits[0].pattern.text if self._fits else ""

    def _fit_count(self, pattern: Pattern) -> int:
        under = self._options.underscores
        return sum(patterns.match(pattern, p, under) is not None for _, p, _ in self._songs)

    def _plan(self) -> None:
        if not self._songs:
            self._planned = Planned((), (), ())
        else:
            songs = [Song(scanner.full_path(self._root, p), t) for _, p, t in self._songs]
            paths = [p for _, p, _ in self._songs]
            self._planned = patterns.plan(songs, paths, self._pattern, self._options,
                                          self._counts)  # fmt: skip
        self._preview.show(self._planned, self._undoable)
        self.changed.emit()

    # ---------- the pattern and the options (R3.4.1, R3.5, R3.6) ----------

    @Slot(str)
    def setPattern(self, text: str) -> None:  # noqa: N802
        """The pattern as typed: the preview follows (R3.4.1)."""
        if self._batch is not None or text == self._text:
            return
        self._text, self._pattern = text, patterns.parse(text)
        self._plan()

    @Slot(int)
    def choosePattern(self, i: int) -> None:  # noqa: N802
        """A pattern of the picker's list put in the field."""
        if 0 <= i < len(self._fits):
            self.setPattern(self._fits[i].pattern.text)

    @Slot(str, "QVariant")
    def setOption(self, name: str, value: Any) -> None:  # noqa: N802
        """R3.5's mode ("mode": "fill" or "correct") or one of R3.6's checkboxes (by its option's
        name), the preview following."""
        if self._batch is not None:
            return
        if name == "mode":
            self._options = replace(self._options, fill_only=value == "fill")
        elif name in dict(CHECKS):
            self._options = replace(self._options, **{name: bool(value)})
            if name == "underscores":
                self._detect()
        else:
            raise ValueError(f"no such option: {name}")
        self._plan()

    @Slot(str)
    def toggle(self, name: str) -> None:
        """One of R3.6's checkboxes clicked."""
        if name in dict(CHECKS):
            self.setOption(name, not getattr(self._options, name))

    @Slot()
    def close(self) -> None:
        """Cancel, ×, or Esc: nothing saved; while a save goes on, it stops before its next
        file."""
        if self._batch is not None:
            self._batch.cancel()
            return
        if self._open:
            self._open, self._songs, self._fits, self._failed = False, [], [], []
            self._problem, self._text = "", ""
            self._pattern = patterns.parse("")
            self._options = patterns.DEFAULTS
            self._ticket += 1
            self._plan()

    # ---------- saving (R3.8, R4.7) ----------

    @Slot()
    def save(self) -> None:
        """Save N files: the files checked written, one entry in the change history; Retry when
        files failed: those written again."""
        if self._batch is not None or not self._available() or self._write is None:
            return
        if self._failed:
            jobs = [f.job for f in self._failed]
        else:
            jobs = self._preview.jobs()
            if not jobs:
                return
            self._description = description_of(self._preview.fields(), len(jobs))
        record = self._history.recording() if self._history is not None else None
        batch: Batch[Written] = Batch(jobs, self._write, self._progressed.emit, record=record,
                                      action=INFER, description=self._description)  # fmt: skip
        self._batch, self._progress, self._failed = batch, (0, len(jobs)), []
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="infer")
        self.changed.emit()
        self._executor.submit(self._run, batch, jobs)

    def _run(self, batch: Batch[Written], jobs: list[Job]) -> None:
        try:
            out = batch.run()
        except Exception as e:  # noqa: BLE001  (the batch fails its files, never itself; logged)
            log.exception("saving tags from paths failed")
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
        self._songs, self._fits = [], []
        self._plan()

    # ---------- the tour, and closing ----------

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"infer": True} opens the dialog on the folder the step shows
        ("folder"); without it the dialog is closed."""
        if not step.get("infer"):
            if self._open:
                self.close()
            return
        self.open_folder(str(step.get("folder", "")))

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

    def _fits_of(self, text: str) -> int:
        return next((f.fits for f in self._fits if f.pattern.text == text),
                    self._fit_count(self._pattern))  # fmt: skip

    def _get_picker(self) -> str:
        if self._loading or not self._songs:
            return ""
        return picker_text(self._fits_of(self._text), len(self._songs),
                           self._text == self._detected, self._pattern.problem)  # fmt: skip

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
        if self._batch is not None:
            return "A save is going on"
        if not self._available():
            return NOT_THERE
        if self._failed:
            return ""
        if not self._loading and not self._songs:
            return NO_SONGS
        return "" if self._preview.chosen() else "Nothing to save"

    def _get_checks(self) -> list[dict[str, Any]]:
        years = [patterns.folder_year(p) for _, p, _ in self._songs]
        underscores = any("_" in p for _, p, _ in self._songs)
        return checks_of(self._options, self._planned, years, underscores)

    opened = QtProperty(bool, lambda self: self._open, notify=changed)
    loading = QtProperty(bool, lambda self: self._loading, notify=changed)
    title = QtProperty(str, lambda self: TITLE, constant=True)
    about = QtProperty(str, lambda self: about_text(self._root, self._home), constant=True)
    pattern = QtProperty(str, lambda self: self._text, notify=changed)
    parts = QtProperty(list, lambda self: parts_of(self._pattern), notify=changed)
    tokens = QtProperty(list, lambda self: tokens_of(), constant=True)
    picker = QtProperty(str, _get_picker, notify=changed)
    detected = QtProperty(bool, lambda self: bool(self._songs) and self._text == self._detected
                          and not self._pattern.problem, notify=changed)  # fmt: skip
    choices = QtProperty(list, lambda self: choices_of(self._fits, len(self._songs), self._text),
                         notify=changed)  # fmt: skip
    modes = QtProperty(list, lambda self: modes_of(self._options), notify=changed)
    checks = QtProperty(list, _get_checks, notify=changed)
    preview = QtProperty(QObject, lambda self: self._preview, constant=True)
    footer = QtProperty(str, _get_footer, notify=changed)
    saveLabel = QtProperty(str, _get_save_label, notify=changed)
    saveLater = QtProperty(str, _get_save_later, notify=changed)
    saving = QtProperty(bool, lambda self: self._batch is not None, notify=changed)
    problem = QtProperty(str, lambda self: self._problem, notify=changed)


def _gone() -> bool:
    return False
