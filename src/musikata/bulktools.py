"""The Edit tags panel's bulk tools in the running app (R4.5): the ⋯ menu's items, and the dialog a
tool opens, its options above R3.7's preview of what it would do (preview.Preview), saved through
the panel (R4.7, R4.9). Number tracks (R4.5.1) has no options; Replace in field (R4.5.2) takes the
field, what to find, what to put in its place, and whether it is a regular expression or matches
case, an invalid expression saying why; Tidy case (R4.5.3) the fields to tidy; Copy from… (R4.5.4)
the song to copy from and the fields to copy. Infer from path (R4.5.5) is R3's, in a later
version: its item shows, disabled, saying so.

What each tool does is tags.tools', a plain function from the songs' tags and the options to what
they would become, planned again as an option changes; what the menu and the dialog say is
decided here as plain data and text, tested without a window."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core.tags import tools
from musikata_core.tags.tools import Planned, ReplaceError

from .history import LABELS
from .models import plural, title_of
from .preview import Preview, file_of, footer_text, labels_text, save_text

log = logging.getLogger(__name__)

INFER_LATER = "Tags from paths come in a later version"  # R4.5.5: R3's, slice 7
UNSAVED = "Save or revert your changes first"
SAVING = "A save is going on"
TWO = "Select two or more songs to copy between"
# the ⋯ menu (R4.5), in R4.5's order: each tool's name, its label and what its dialog says it does
TOOLS = (
    ("number", "Number tracks", "Numbers the songs 1, 2, 3 … in the list's order, and sets Track "
                                "total to how many there are."),
    ("replace", "Replace in field", "Finds text, or a regular expression, in one field and "
                                    "replaces it. Genre is matched one genre at a time."),
    ("tidy", "Tidy case", "Values all in lower or upper case become Title Case, with a, an, and, "
                          "of, the … kept lower inside; mixed case is left as it is."),
    ("copy", "Copy from…", "Copies the fields chosen from one song to the others, as for a bonus "
                           "track ripped apart from its album."),
    ("infer", "Infer from path", ""),
)  # fmt: skip
LABEL = {name: label for name, label, _ in TOOLS}
ABOUT = {name: about for name, _, about in TOOLS}
SOURCE_LIST = 500  # the songs Copy from… offers to copy from, in the list's order


def menu_of(songs: int, unsaved: bool, saving: bool) -> list[dict[str, str]]:
    """The ⋯ menu's items (R4.5): each tool's name and label, and why it can't be used now ("" when
    it can): a save going on, changes typed and not saved (a tool plans from the files' tags),
    fewer than two songs to copy between; Infer from path comes in a later version (R3)."""
    out = []
    for name, label, _ in TOOLS:
        later = (
            INFER_LATER
            if name == "infer"
            else SAVING
            if saving
            else UNSAVED
            if unsaved
            else TWO
            if name == "copy" and songs < 2
            else ""
        )
        out.append({"name": name, "label": label, "later": later})
    return out


def description_of(tool: str, fields: Sequence[str], songs: int) -> str:
    """What a tool's save was, for the change history (R4.9): Tidy case: Artist and Genre on
    3 songs."""
    return f"{LABEL[tool]}: {labels_text(fields)} on {plural(songs, 'song')}"


def field_choices(names: Sequence[str], chosen: Sequence[str]) -> list[dict[str, Any]]:
    """Fields to choose among, each its name, R4.1's label and whether it is chosen."""
    return [{"name": n, "label": LABELS.get(n, n), "chosen": n in chosen} for n in names]


def source_choices(
    songs: Sequence[tools.Song], titles: Sequence[str | None], root: str
) -> list[str]:
    """The songs Copy from… can copy from, as its list names them: title, and file name."""
    out = []
    for s, title in zip(songs[:SOURCE_LIST], titles, strict=False):
        name = file_of(s.path, root)[0]
        out.append(f"{title_of(title, name)} · {name}")
    return out


class BulkTool(QObject):
    """The dialog of the bulk tool open, over the songs the panel edits: its options and its
    preview. Its Save sends `saved` the jobs of the files checked and the save's description,
    which the panel saves as it saves its own changes (EditTags)."""

    changed = Signal()  # open or not, which tool, the options, why they can't be used
    saved = Signal(object, str)  # a list of Job, and the save's description

    def __init__(self, root: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._root = root
        self._undoable = True
        self._preview = Preview(root, parent=self)
        self._tool = ""
        self._songs: list[tools.Song] = []
        self._field = "title"
        self._find = self._by = ""
        self._regex = self._match_case = False
        self._tidied: list[str] = list(tools.TIDIED)
        self._copied: list[str] = list(tools.COPIED_FIRST)
        self._source = 0
        self._problem = ""
        self._preview.changed.connect(self.changed)  # a file checked or not: the footer

    def open(
        self,
        tool: str,
        songs: Sequence[tools.Song],
        options: dict[str, Any] | None = None,
        undoable: bool = True,
    ) -> None:
        """Opens tool `tool` over `songs` (in the list's order), with `options` set as the user
        would set them (the tour's); its preview shows what it would do. `undoable` says whether
        the change history keeps its save (R4.9)."""
        if tool not in LABEL or tool == "infer":
            raise ValueError(f"no such bulk tool: {tool}")
        self._tool, self._songs, self._undoable = tool, list(songs), undoable
        self._source = 0
        for name, value in (options or {}).items():
            self._set(name, value)
        self._plan()

    @Slot()
    def close(self) -> None:
        """Cancel, ×, or Esc: nothing saved."""
        if self._tool:
            self._tool, self._songs = "", []
            self._preview.show(Planned((), (), ()))
            self.changed.emit()

    def _set(self, name: str, value: Any) -> None:
        if name == "field":
            if value not in tools.WORDS:
                raise ValueError(f"Replace in field doesn't work on {value!r}")
            self._field = value
        elif name in ("find", "by"):
            setattr(self, f"_{name}", str(value))
        elif name in ("regex", "match_case"):
            setattr(self, f"_{name}", bool(value))
        elif name == "source":
            self._source = max(0, min(int(value), len(self._songs) - 1))
        elif name in ("tidied", "copied"):
            setattr(self, f"_{name}", list(value))
        else:
            raise ValueError(f"no such option: {name}")

    def _planned(self) -> Planned:
        songs = self._songs
        if self._tool == "number":
            return tools.number_tracks(songs)
        if self._tool == "replace":
            return tools.replace_in_field(songs, self._field, self._find, self._by, self._regex,
                                          self._match_case)  # fmt: skip
        if self._tool == "tidy":
            return tools.tidy(songs, self._tidied)
        return tools.copy_from(songs, self._source, self._copied)

    def _plan(self) -> None:
        self._problem = ""
        try:
            if self._tool == "replace" and not self._find:
                raise ReplaceError("")  # nothing to find yet: nothing changes, and nothing is wrong
            planned = self._planned()
        except ReplaceError as e:
            self._problem = str(e)
            planned = Planned(
                (self._field,), tuple(self._songs), tuple(s.tags for s in self._songs)
            )
        self._preview.show(planned, self._undoable)
        self.changed.emit()

    # ---------- the options, as the dialog sets them ----------

    @Slot(str, "QVariant")
    def setOption(self, name: str, value: Any) -> None:  # noqa: N802
        """An option set in the dialog: Replace's "field", "find", "by", "regex", "match_case";
        Copy from…'s "source"; the planned change follows."""
        if not self._tool:
            return
        self._set(name, value)
        self._plan()

    @Slot(str)
    def toggleField(self, name: str) -> None:  # noqa: N802
        """A field's checkbox in Tidy case or Copy from…: chosen, or not."""
        attr, names = (
            ("_tidied", tools.WORDS) if self._tool == "tidy" else ("_copied", tools.COPIED)
        )
        if self._tool not in ("tidy", "copy") or name not in names:
            return
        chosen: list[str] = getattr(self, attr)
        setattr(self, attr, [n for n in chosen if n != name] if name in chosen else [*chosen, name])
        self._plan()

    @Slot()
    def save(self) -> None:
        """Save N files (R3.8): the files checked sent to be saved as the panel saves (R4.7), as
        one entry in the change history named for the tool (R4.9); the panel closes the dialog
        once the save has started."""
        jobs = self._preview.jobs()
        if not self._tool or not jobs or self._problem:
            return
        description = description_of(self._tool, self._preview.fields(), len(jobs))
        self.saved.emit(jobs, description)

    # ---------- what QML reads ----------

    def _get_options(self) -> dict[str, Any]:
        if self._tool == "replace":
            return {"field": self._field, "find": self._find, "by": self._by,
                    "regex": self._regex, "matchCase": self._match_case,
                    "fields": field_choices(tools.WORDS, [self._field])}  # fmt: skip
        if self._tool == "tidy":
            return {"fields": field_choices(tools.WORDS, self._tidied)}
        if self._tool == "copy":
            titles = [s.tags.title for s in self._songs[:SOURCE_LIST]]
            return {"source": self._source,
                    "sources": source_choices(self._songs, titles, self._root),
                    "fields": field_choices(tools.COPIED, self._copied)}  # fmt: skip
        return {}

    def _get_footer(self) -> str:
        return footer_text(*self._preview.counts(), undoable=self._undoable)

    def _get_save_later(self) -> str:
        """Why Save can't be pressed now ("" when it can)."""
        return "" if self._preview.chosen() and not self._problem else "Nothing to save"

    opened = QtProperty(bool, lambda self: bool(self._tool), notify=changed)
    tool = QtProperty(str, lambda self: self._tool, notify=changed)
    title = QtProperty(str, lambda self: LABEL.get(self._tool, ""), notify=changed)
    about = QtProperty(str, lambda self: ABOUT.get(self._tool, ""), notify=changed)
    count = QtProperty(int, lambda self: len(self._songs), notify=changed)
    options = QtProperty(dict, _get_options, notify=changed)
    problem = QtProperty(str, lambda self: self._problem, notify=changed)
    preview = QtProperty(QObject, lambda self: self._preview, constant=True)
    footer = QtProperty(str, _get_footer, notify=changed)  # R3.8: what will be saved
    saveLabel = QtProperty(str, lambda self: save_text(self._preview.counts()[0]), notify=changed)
    saveLater = QtProperty(str, _get_save_later, notify=changed)
