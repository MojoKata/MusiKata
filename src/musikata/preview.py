"""The preview of a change to many files' tags before it is saved (R3.7, R3.8): built for the Edit
tags panel's bulk tools (R4.5), and the preview Infer from path will show (R3, slice 7). It lists
each file with the columns the change fills; a value that will change shows the old value struck
through in red above the new one in green, "(empty)" standing for no value; each changed file has
a checkbox, on at first, and unchecking it leaves the file alone; files with no change are listed
dimmed and unchecked, the run of them after the last change ending in "+ 3 more files,
unchanged" (T01-infer-from-path). The footer counts the files and changes that will be saved, and
**Save N files** hands their jobs on to be saved (R4.7).

What a row, a cell and the footer say is decided here as plain data and text (`row_of`,
`listed`, `footer_text`, …), tested without a window; which files change, and how, is the change's
own (a tags.tools.Planned). The QML (PreviewTable.qml) lays it out."""

from __future__ import annotations

from collections.abc import Sequence
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

from musikata_core import scanner
from musikata_core.tags import Job
from musikata_core.tags.tools import Planned, text_of

from .history import LABELS
from .models import plural

EMPTY = "(empty)"  # R3.7: no value, before or after
TAIL = 1  # the unchanged files listed after the last change, before "+ N more files, unchanged"
NARROW = ("track", "tracktotal", "disc", "disctotal", "year", "compilation")  # the narrow columns
COLUMN_LABELS = {**LABELS, "track": "#"}
ROLES = ("file", "folder", "changed", "checked", "cells")


def label_of(name: str) -> str:
    """A column's heading: T01-infer-from-path's "#" for Track; R4.1's names for the rest."""
    return COLUMN_LABELS.get(name, name)


def labels_text(names: Sequence[str]) -> str:
    """Fields named in a sentence, R4.1's names: Artist; Artist and Year; Artist, Genre and
    Year."""
    labels = [LABELS.get(n, n) for n in names]
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def columns_of(planned: Planned) -> list[dict[str, Any]]:
    """The columns after the file's: each field the change fills, its heading, and whether it is
    a narrow one (a number, a year)."""
    return [{"name": c, "label": label_of(c), "narrow": c in NARROW} for c in planned.columns]


def file_of(path: str, root: str) -> tuple[str, str]:
    """A file's name and its folder under the root, as a row shows them."""
    rel = scanner.path_under(root, path) or path
    folder, _, name = rel.replace("\\", "/").rpartition("/")
    return name, folder


def row_of(planned: Planned, i: int, checked: bool, root: str) -> dict[str, Any]:
    """Song `i`'s row: its file and folder, whether it changes and is checked, and a cell per
    column: the old text and the new, each "(empty)" for none (and whether it is), and whether it
    changes."""
    song, new = planned.songs[i], planned.new[i]
    changed = planned.changed(i)
    name, folder = file_of(song.path, root)
    cells = []
    for c in planned.columns:
        old_text, new_text = text_of(c, song.tags), text_of(c, new)
        cells.append({"old": old_text or EMPTY, "new": new_text or EMPTY, "changed": c in changed,
                      "oldEmpty": not old_text, "newEmpty": not new_text})  # fmt: skip
    return {"file": name, "folder": folder, "changed": bool(changed),
            "checked": checked and bool(changed), "cells": cells}  # fmt: skip


def listed(changed: Sequence[bool], tail: int = TAIL) -> int:
    """How many files are listed: every one up to the last that changes, then `tail` of those
    after it, which don't (T01-infer-from-path); the rest are counted below the list, unless they
    are one file, which is listed in place of the line that would count it."""
    last = max((i for i, c in enumerate(changed) if c), default=-1)
    shown = last + 1 + tail
    return len(changed) if len(changed) - shown < 2 else shown


def more_text(unlisted: int) -> str:
    """The files not listed, none of which change: + 3 more files, unchanged."""
    return (
        f"+ {unlisted:,} more {'file' if unlisted == 1 else 'files'}, unchanged" if unlisted else ""
    )


def footer_text(files: int, changes: int, undoable: bool = True) -> str:
    """R3.8's footer: 4 files · 4 changes, and what Undo can do; what nothing will change says."""
    if not files:
        return "Nothing will change"
    then = (
        "the old tags are kept, and Undo puts them back"
        if undoable
        else "the change history is off, so Undo can't put them back"
    )
    return f"{plural(files, 'file')} · {plural(changes, 'change')} · {then}"


def progress_text(done: int, total: int) -> str:
    """A save's progress (R4.7): Saving 12 of 40 files…"""
    return f"Saving {done:,} of {plural(total, 'file')}…"


def failed_text(failed: int) -> str:
    """The heading of the files a save couldn't write (R4.7)."""
    return "1 file wasn't saved" if failed == 1 else f"{failed:,} files weren't saved"


def save_text(files: int) -> str:
    """R3.8's button: Save 4 files; Save when nothing will."""
    return f"Save {plural(files, 'file')}" if files else "Save"


class PreviewRows(QAbstractListModel):
    """The rows the preview lists, each as `row_of` makes it, made as they are shown."""

    def __init__(self, preview: Preview) -> None:
        super().__init__(preview)
        self._preview = preview

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else self._preview.listed_count()

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        base = int(Qt.ItemDataRole.UserRole)
        return {base + i: QByteArray(n.encode()) for i, n in enumerate(ROLES)}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        i = role - int(Qt.ItemDataRole.UserRole)
        if not 0 <= i < len(ROLES) or not 0 <= index.row() < self.rowCount():
            return None
        return self._preview.row(index.row())[ROLES[i]]

    def reset(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def changed_row(self, row: int) -> None:
        at = self.index(row, 0)
        self.dataChanged.emit(at, at)


class Preview(QObject):
    """R3.7's preview of a planned change (tags.tools.Planned) of the files under `root`: its
    rows, their checkboxes, the footer and Save."""

    changed = Signal()  # the columns, the rows, the footer

    def __init__(self, root: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._root, self._undoable = root, True
        self._planned = Planned((), (), ())
        self._changes: list[tuple[str, ...]] = []
        self._checked: set[int] = set()
        self._listed = 0
        self._rows = PreviewRows(self)

    def show(self, planned: Planned, undoable: bool = True) -> None:
        """Shows `planned`: every file that changes checked (R3.7). `undoable` says whether the
        change history will keep its save (R4.9; off in the root's settings, R13.3)."""
        self._planned, self._undoable = planned, undoable
        self._changes = [planned.changed(i) for i in range(len(planned.songs))]
        self._checked = {i for i, c in enumerate(self._changes) if c}
        self._listed = listed([bool(c) for c in self._changes])
        self._rows.reset()
        self.changed.emit()

    def listed_count(self) -> int:
        return self._listed

    def row(self, i: int) -> dict[str, Any]:
        """Row `i` as QML shows it."""
        return row_of(self._planned, i, i in self._checked, self._root)

    @Slot(int)
    def toggle(self, i: int) -> None:
        """A row's checkbox: a changed file left alone, or saved again; a file with no change
        has none."""
        if not 0 <= i < len(self._changes) or not self._changes[i]:
            return
        self._checked ^= {i}
        self._rows.changed_row(i)
        self.changed.emit()

    def chosen(self) -> list[int]:
        """The files checked, by their places in the planned change."""
        return sorted(self._checked)

    def jobs(self) -> list[Job]:
        """The save of the files checked."""
        return self._planned.jobs(self._checked)

    def fields(self) -> list[str]:
        """The columns that change on a file checked, in the columns' order."""
        names = {c for i in self._checked for c in self._changes[i]}
        return [c for c in self._planned.columns if c in names]

    def counts(self) -> tuple[int, int]:
        """The files checked, and the values they change (R3.8)."""
        return len(self._checked), sum(len(self._changes[i]) for i in self._checked)

    def _get_footer(self) -> str:
        return footer_text(*self.counts(), undoable=self._undoable)

    columns = QtProperty(list, lambda self: columns_of(self._planned), notify=changed)
    rows = QtProperty(QObject, lambda self: self._rows, constant=True)
    total = QtProperty(int, lambda self: len(self._planned.songs), notify=changed)
    more = QtProperty(str, lambda self: more_text(len(self._changes) - self._listed),
                      notify=changed)  # fmt: skip
    footer = QtProperty(str, _get_footer, notify=changed)
    saveLabel = QtProperty(str, lambda self: save_text(self.counts()[0]), notify=changed)
    canSave = QtProperty(bool, lambda self: bool(self._checked), notify=changed)
