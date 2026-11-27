"""Needs attention in the running app (R2.8, L09-needs-attention): the view's groups and their
entries, each with the action that fixes it, and Ignore.

- **The view** (`AttentionModel`): the chips across the top (All, then a chip per group with its
  count, CHIPS), and a list of groups, each a line folded with its count and the first of its
  entries, or open with its section's heading and note and an entry per row. All shows every group
  folded; a chip opens its groups first, the others folded after it, as L09 draws them, and a
  group's line opens or folds it. The entries are found off the GUI thread (the search thread,
  models.Searcher, A1.3) by musikata_core.attention's queries, after every scan or save, so the
  count in the sidebar is always current; a row is made only when the list shows it, as a long
  list's are. The header's search (R2.7) keeps the entries whose words it finds.
- **The same song more than once** (R2.12): a group of copies is an entry drawn as L09 draws it,
  a row per copy with the copy kept and those checked for the trash (`AttentionModel`'s choice of
  each group, duplicates.initial at first, changed by its radio buttons and checkboxes), and the
  selection bar's Move N to the trash over every group's; Review… opens the group in its dialog
  (musikata.duplicates).
- **Tags in the wrong text encoding** (R4.10): an entry per song, named as the likely encoding
  reads it, whose Fix encoding…, or its group's, opens musikata.encodings' dialog.
- **Tags that differ from the path** (R3.9): an entry per folder, saying how many of its files
  differ and in what, whose Infer from path opens musikata.infer's dialog on its songs.
- **The actions** (`Attention`): Edit tags (the Edit tags panel on the album's songs, R4.2), Album
  art (its dialog, R5.2), Review… (musikata.duplicates' dialog, R2.12), Fix encoding…
  (musikata.encodings' dialog, R4.10), Infer from path (musikata.infer's, R3), Merge (a genre's
  merge of R9.4; for an artist's or an album's names, `NameMerge`: the same preview, saved through
  the batch as one entry in the change history that Undo reverses), Show in folder (the system's
  file manager, the file selected where the platform can, `reveal_command`), and Ignore: the entry
  kept in the root's `.musikata/ignored.json` (rootfiles.save_ignored, read again and merged
  first) and in the index, until its file changes. Another computer's dismissals are read again
  whenever the watcher sees `.musikata` change.

What a chip, a group's line and an entry say, and which actions an entry has, are decided here as
plain data and text (`entry_row`, `group_row`, `chips_of`, …), tested without a window; what each
group holds is musikata_core.attention's."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices

from musikata_core import attention, db, duplicates, encodings, rootfiles, scanner, watch
from musikata_core.attention import Entry
from musikata_core.clock import Clock
from musikata_core.duplicates import Plan
from musikata_core.tags import Batch, Failed, Job, Outcome, Written
from musikata_core.tags.tools import Planned, Song

from .duplicates import Duplicates, badge_text, bar_text, copy_rows, heading_text, move_label
from .encodings import FixEncoding
from .history import LABELS, NAMES, ChangeHistory
from .infer import InferFromPath
from .models import SHORT, Searcher, cover_url, plural, time_text
from .playlists import Playlists
from .preview import Preview, failed_text, footer_text, progress_text, save_text

log = logging.getLogger(__name__)

ONLINE_LATER = "Finding covers online comes in a later version"  # R16.4.1: #27
SHOWN = 3  # the entries a folded group's line names
ROLES = ("type", "group", "kind", "title", "detail", "cover", "icon", "actions", "open",
         "summary", "note", "count", "tone", "badge", "copies")  # fmt: skip


@dataclass(frozen=True)
class Group:
    """A group of the view: its key, its chip's label, its section's heading and note, the kinds
    it holds (musikata_core.attention's) and what it counts, and its own action (the group's
    line's button, `later` when it is a later version's)."""

    key: str
    label: str
    heading: str
    note: str
    kinds: tuple[str, ...]
    noun: str
    action: dict[str, str] | None = None


GROUPS = (
    Group("paths", "Tags differ from path", "TAGS THAT DIFFER FROM THE PATH",
          "Infer from path fills or corrects the tags from each file's path; Undo puts them"
          " back.", (attention.PATH,), "folder"),
    Group("copies", "Same song twice", "SAME SONG MORE THAN ONCE",
          "The kept copy takes the others' plays and highest rating.", (attention.COPIES,),
          "song"),
    Group("covers", "Covers", "NO COVER, OR A SMALL ONE",
          "Album art finds the covers there are, embeds one and saves it as cover.jpg; a cover"
          " under 500 × 500 looks blurred.",
          (attention.COVER_NONE, attention.COVER_SMALL), "album",
          {"name": "online", "label": "Find covers online", "later": ONLINE_LATER}),
    Group("names", "Names", "NAMES THAT DIFFER ONLY IN CASE OR SPACING",
          "Merge writes the name chosen into every song with another spelling; Undo puts them"
          " back.", attention.NAMES, "name"),
    Group("encoding", "Wrong encoding", "TAGS IN THE WRONG TEXT ENCODING",
          "Saved as Latin-1 but read better another way: Fix encoding… writes the reading chosen"
          " as Unicode, and Undo puts the old bytes back.", (attention.ENCODING,), "song",
          {"name": "fix", "label": "Fix encoding…", "later": ""}),
    Group("one-file", "Album in one file", "ALBUM IN ONE FILE",
          "It plays as one song; splitting it into its tracks comes in a later version.",
          (attention.ONE_FILE,), "album"),
    Group("albums", "Albums that differ", "AN ALBUM WHOSE SONGS DIFFER",
          "Edit tags gives its songs one value; Album art gives them one cover.",
          (attention.ALBUM_DIFFERS,), "album"),
    Group("playlists", "Missing from playlists", "PLAYLIST ENTRIES WHOSE FILE IS MISSING",
          "Find looks under your music folder for the file by its name and its tags; choosing"
          " one fixes the entry.", (attention.MISSING,), "song"),
    Group("unreadable", "Files that couldn't be read", "FILES THAT COULDN'T BE READ",
          "Each with why; Show in folder opens it where it is.", (attention.UNREADABLE,), "file"),
)  # fmt: skip
BY_KEY = {g.key: g for g in GROUPS}
GROUP_OF = {kind: g.key for g in GROUPS for kind in g.kinds}
# the chips (L09-needs-attention): All, then a chip each, the groups no chip of their own has in
# Other
CHIPS = (
    ("all", "All", tuple(g.key for g in GROUPS)),
    ("paths", "Tags differ from path", ("paths",)),
    ("copies", "Same song twice", ("copies",)),
    ("covers", "Covers", ("covers",)),
    ("names", "Names", ("names",)),
    ("encoding", "Wrong encoding", ("encoding",)),
    ("one-file", "Album in one file", ("one-file",)),
    ("other", "Other", ("albums", "playlists", "unreadable")),
)
FIELD_LABELS = {"album": "Album", "albumartist": "Album artist", "year": "Year", "genre": "Genre",
                "cover": "Cover", "track": "Track"}  # fmt: skip
NAME_KINDS = {attention.NAMES_ARTIST: "Artist", attention.NAMES_ALBUM: "Album",
              attention.NAMES_GENRE: "Genre"}  # fmt: skip


# ---------- what an entry, a group and a chip say ----------


def and_text(parts: Sequence[str]) -> str:
    """Parts in a sentence: A; A and B; A, B and C."""
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def spellings_text(names: Sequence[str], counts: Sequence[int]) -> str:
    """A name's spellings with their songs: Lumen Drift (12), lumen drift (3)."""
    return ", ".join(f"{n} ({c:,})" for n, c in zip(names, counts, strict=True))


def size_text(width: int | None, height: int | None) -> str:
    return f"{width:,} × {height:,}" if width is not None and height is not None else ""


def _action(name: str, label: str) -> dict[str, str]:
    return {"name": name, "label": label, "later": ""}


IGNORE = _action("ignore", "Ignore")


def entry_row(e: Entry, choice: tuple[int, frozenset[int]] | None = None) -> dict[str, Any]:
    """An entry as the view shows it (L09-needs-attention): its title, the line under it, its
    cover (an album's) or icon, and its actions, the one that fixes it first and Ignore last; a
    group of copies (R2.12) its badge and a row per copy, as `choice` (the copy kept, those
    checked; duplicates.initial when None) has them."""
    who = e.artist or "Unknown artist"
    badge, copies = "", []
    if e.kind == attention.COPIES:
        group = duplicates.Group(e.copies, e.likely, e.why)
        kept, checked = choice if choice is not None else duplicates.initial(group)
        detail, badge, copies = heading_text(e), badge_text(e), copy_rows(e, kept, checked)
        actions = [_action("review", "Review…")]
        icon = "album"
    elif e.kind in (attention.COVER_NONE, attention.COVER_SMALL):
        detail = (f"{who} · No cover" if e.kind == attention.COVER_NONE
                  else f"{who} · Cover {size_text(e.width, e.height)}")  # fmt: skip
        actions = [_action("art", "Album art…")]
        icon = "album"
    elif e.kind in attention.NAMES:
        detail = f"{NAME_KINDS[e.kind]} · {spellings_text(e.names, e.counts)}"
        if e.kind == attention.NAMES_ALBUM and e.artist:
            detail = f"Album by {e.artist} · {spellings_text(e.names, e.counts)}"
        actions = [_action("merge", "Merge…")]
        icon = {attention.NAMES_ARTIST: "artist", attention.NAMES_ALBUM: "album"}.get(
            e.kind, "genre"
        )
    elif e.kind == attention.ALBUM_DIFFERS:
        fields = and_text([FIELD_LABELS.get(f, f).lower() for f in e.fields])
        detail = f"{who} · Its songs' {fields} differ" if fields else who
        actions = [_action("edit", "Edit tags"), _action("art", "Album art…")]
        icon = "album"
    elif e.kind == attention.ENCODING:
        parts = [e.artist, e.album_title, f"Reads as {encodings.label_of(e.key)}"]
        detail = " · ".join(p for p in parts if p)
        actions = [_action("fix", "Fix encoding…")]
        icon = "album" if e.album is not None else "file"
    elif e.kind == attention.PATH:
        detail = path_detail(e)
        actions = [_action("infer", "Infer from path")]
        icon = "folder"
    elif e.kind == attention.ONE_FILE:
        detail = f"{who} · {time_text(e.length)} in one file, with {e.cue}"
        actions = []
        icon = "file"
    elif e.kind == attention.MISSING:
        detail = missing_detail(e)
        actions = [_action("find", "Find…")]
        icon = "playlist"
    else:
        detail = e.error
        actions = [_action("folder", "Show in folder")]
        icon = "file"
    title = e.title or os.path.basename(e.about) or e.about
    return {
        "type": "entry", "group": GROUP_OF[e.kind], "kind": e.kind, "title": title,
        "detail": detail, "cover": cover_url(e.thumb) if e.album is not None else "",
        "icon": icon, "actions": [*actions, IGNORE], "open": True, "summary": "", "note": "",
        "count": 0, "tone": "err" if e.kind == attention.UNREADABLE else "", "badge": badge,
        "copies": copies,
    }  # fmt: skip


def path_detail(e: Entry) -> str:
    """What a folder whose tags differ from its paths says (R2.8, R3.9): where it is, how many of
    its files differ and in what: Lumen Drift · 2 of 9 files · Artist and Year."""
    differing, files = (*e.counts, 0, 0)[:2]
    where = attention.folder_of(e.about).rpartition("/")[0].replace("/", " › ")
    fields = and_text([FIELD_LABELS.get(f, LABELS.get(f, f)) for f in e.fields])
    parts = [where, f"{differing:,} of {plural(files, 'file')}" if files else "", fields]
    return " · ".join(p for p in parts if p)


def missing_detail(e: Entry) -> str:
    """What a playlist's missing entry says (R8.7): the playlist, and the place it names: In Road
    Trip · ../Lumen Drift/Tide Tables/10 - Slack Tide.flac; twice when it names it twice."""
    times = f" ({e.counts[0]:,} times)" if e.counts and e.counts[0] > 1 else ""
    return f"In {e.artist}{times} · {e.key}"


def short_of(e: Entry) -> str:
    """An entry as a folded group's line names it: Kindling; Live at the Lantern (Mara Okafor),
    with a .cue; a file by its name."""
    if e.kind == attention.ONE_FILE:
        return (
            f"{e.title or os.path.basename(e.about)} ({e.artist}), with a .cue"
            if e.artist
            else (f"{e.title or os.path.basename(e.about)}, with a .cue")
        )
    if e.kind == attention.UNREADABLE:
        return os.path.basename(e.about)
    if e.kind == attention.PATH and e.about == attention.ROOT_FOLDER:
        return "Your music folder"
    return e.title or e.about


def summary_text(group: Group, entries: Sequence[Entry]) -> str:
    """A folded group's line (L09-needs-attention): 2 albums · Kindling, Salt & Ember; the first
    SHOWN named, then how many more."""
    named = [short_of(e) for e in entries[:SHOWN]]
    more = len(entries) - len(named)
    if more > 0:
        named.append(f"{more:,} more")
    return " · ".join([plural(len(entries), group.noun), ", ".join(named)])


def group_row(group: Group, entries: Sequence[Entry], opened: bool) -> dict[str, Any]:
    """A group's line: its label, count and first entries, or, open, its section's heading and
    note; with its own action."""
    return {
        "type": "group", "group": group.key, "kind": "", "title": group.label,
        "detail": group.heading, "cover": "", "icon": "", "open": opened,
        "actions": [group.action] if group.action else [], "summary": summary_text(group, entries),
        "note": group.note, "count": len(entries), "tone": "", "badge": "", "copies": [],
    }  # fmt: skip


def chips_of(counts: dict[str, int], chosen: str) -> list[dict[str, Any]]:
    """The chips (L09-needs-attention): All and its count, then each chip with something in it,
    and the one chosen."""
    out = []
    for key, label, groups in CHIPS:
        n = sum(counts.get(g, 0) for g in groups)
        if key == "all" or n or key == chosen:
            out.append({"name": key, "label": f"{label}  {n:,}", "chosen": key == chosen})
    return out


def count_text(shown: int, total: int, searching: bool) -> str:
    """The view's count beside its title: 23 to look at; 3 of 23 to look at while a search
    filters it; nothing to look at."""
    if not total:
        return "Nothing to look at"
    return f"{shown:,} of {total:,} to look at" if searching else f"{total:,} to look at"


def _plain(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    ).casefold()


def matches(e: Entry, words: Sequence[str]) -> bool:
    """Whether every word of a search (R2.7: case and accents aside) is in what the entry says."""
    row = entry_row(e)
    said = _plain(" ".join((row["title"], row["detail"], e.about, " ".join(e.names))))
    return all(w in said for w in words)


def words_of(text: str) -> list[str]:
    return [_plain(w) for w in text.split()]


def rows_of(
    entries: Sequence[Entry], chip: str, toggled: Iterable[str]
) -> list[tuple[str, str, int]]:
    """The view's rows: ("group", key, -1) for each group with entries, followed, when open, by
    ("entry", key, i) for each of its entries (their places in `entries`). With All every group
    folded; with a chip, its groups open first and the others folded after; a group `toggled` is
    the other way."""
    by_group: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        by_group.setdefault(GROUP_OF[e.kind], []).append(i)
    mine = next(groups for key, _, groups in CHIPS if key == chip) if chip != "all" else ()
    order = [g.key for g in GROUPS if g.key in mine] + [g.key for g in GROUPS if g.key not in mine]
    flipped = set(toggled)
    out: list[tuple[str, str, int]] = []
    for key in order:
        if key not in by_group:
            continue
        out.append(("group", key, -1))
        if (key in mine) != (key in flipped):
            out += [("entry", key, i) for i in by_group[key]]
    return out


# ---------- Show in folder ----------


def reveal_command(path: str, platform: str, have: Callable[[str], object]) -> list[str] | None:
    """How the system's file manager shows the file at `path` selected (R2.8's Show in folder):
    Explorer's /select on Windows, Finder's reveal on macOS, the desktop's file manager over D-Bus
    elsewhere when `dbus-send` is there (`have`); None when there is no way: its folder is opened
    instead."""
    if platform == "win32":
        return ["explorer", f"/select,{path}"]
    if platform == "darwin":
        return ["open", "-R", path]
    if have("dbus-send"):
        return [
            "dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
            "--type=method_call", "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1.ShowItems",
            f"array:string:{QUrl.fromLocalFile(path).toString()}", "string:",
        ]  # fmt: skip
    return None


def _run(command: list[str]) -> bool:
    """`command` run to its end (a few seconds at most); whether it did what it was asked."""
    try:
        done = subprocess.run(command, capture_output=True, timeout=10, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("couldn't show the file in its folder: %s", e)
        return False
    if done.returncode and sys.platform not in (
        "win32",
        "darwin",
    ):  # Explorer says 1 when it worked
        log.info("the file manager didn't show the file: %s", done.stderr.decode(errors="replace"))
        return False
    return True


# ---------- the view's list ----------


class AttentionModel(QAbstractListModel):
    """Needs attention's list (L09-needs-attention): its groups' lines and their entries, found
    off the GUI thread (`refresh`) after a scan or a save, or a dismissal; the chips, the group
    open, and the header's search (R2.7). It answers what Library asks of a list
    (models.PagedModel): its count and total, its search, whether its rows are still to come.
    `same`: the genres the user has said are the same (R9.5); `min_side`: R5.6's."""

    countChanged = Signal()
    chipsChanged = Signal()
    choicesChanged = Signal()  # a group of copies' choice changed (R2.12)

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        parent: QObject | None = None,
        searcher: Searcher | None = None,
    ) -> None:
        super().__init__(parent)
        self._read = read
        self._searcher = searcher if searcher is not None else Searcher(self)
        self.same: list[tuple[str, ...]] = []
        self.min_side = attention.MIN_SIDE
        self._all: list[Entry] = []  # every entry, not dismissed
        self._entries: list[Entry] = []  # those the search keeps
        self._rows: list[tuple[str, str, int]] = []
        self._made: dict[int, dict[str, Any]] = {}
        self._chip = "all"
        self._toggled: set[str] = set()
        self._search = ""
        self._shown = ""
        self._pending = False
        self._generation = 0
        self._found_once = False
        self._choices: dict[str, tuple[int, frozenset[int]]] = {}  # each group of copies'

    # ---------- what Library asks of a list ----------

    def set_search(self, text: str) -> None:
        """Only the entries whose words the search finds (R2.7)."""
        self.search_next(text)
        self._shape()

    def search_next(self, text: str) -> None:
        self._search = text

    def reload(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Finds every group's entries again, on the search thread: after a scan, a save or a
        dismissal; a small library's, a matter of a millisecond or two, at once, as a short
        list's rows are (models.PagedModel)."""
        self._generation += 1
        generation, read = self._generation, self._read
        same, min_side = list(self.same), self.min_side

        def work() -> list[Entry]:
            c = read()
            return attention.find(c, rootfiles.dismissals(c), same, min_side)

        if int(read().execute("SELECT COUNT(*) FROM song").fetchone()[0]) <= SHORT:
            self._found(generation, work())
            return
        self._pending = True
        self._searcher.submit(("attention", id(self)), work,
                              lambda found: self._found(generation, found))  # fmt: skip

    def _found(self, generation: int, found: list[Entry] | None) -> None:
        if generation != self._generation:
            return  # a newer refresh has been asked for since
        self._pending = False
        self._found_once = True
        if found is not None:
            self._all = found
            self._keep_choices()
        self._shape()

    def _shape(self) -> None:
        """The rows again from the entries found, the search, the chip and the groups open."""
        words = words_of(self._search)
        entries = [e for e in self._all if matches(e, words)] if words else list(self._all)
        rows = rows_of(entries, self._chip, self._toggled)
        self.beginResetModel()
        self._entries, self._rows, self._made = entries, rows, {}
        self._shown = self._search if words else ""
        self.endResetModel()
        self.countChanged.emit()
        self.chipsChanged.emit()

    # ---------- the groups of copies' choices (R2.12) ----------

    def _keep_choices(self) -> None:
        """The choices of the groups found again: each kept while its copies are, a group new or
        changed starting from duplicates.initial."""
        kept: dict[str, tuple[int, frozenset[int]]] = {}
        for e in self._all:
            if e.kind != attention.COPIES:
                continue
            had = self._choices.get(e.about)
            songs = {c.song for c in e.copies}
            if had is not None and had[0] in songs and had[1] <= songs:
                kept[e.about] = had
        self._choices = kept
        self.choicesChanged.emit()

    def entry_of(self, about: str) -> Entry | None:
        """The group of copies about `about` (its first copy), as last found."""
        return next((e for e in self._all if e.kind == attention.COPIES and e.about == about),
                    None)  # fmt: skip

    def entry_titled(self, title: str) -> Entry | None:
        """The first group of copies of the title `title` (the tour's)."""
        return next((e for e in self._all if e.kind == attention.COPIES and e.title == title),
                    None)  # fmt: skip

    def choice_of(self, e: Entry) -> tuple[int, frozenset[int]]:
        """A group's choice: the copy kept and those checked for the trash, by song id."""
        found = self._choices.get(e.about)
        return (
            found
            if found is not None
            else duplicates.initial(duplicates.Group(e.copies, e.likely, e.why))
        )

    def _choose(self, about: str, choice: tuple[int, frozenset[int]]) -> None:
        self._choices[about] = choice
        for n, (kind, _key, i) in enumerate(self._rows):
            if kind == "entry" and self._entries[i].about == about:
                self._made.pop(n, None)
                self.dataChanged.emit(self.index(n), self.index(n))
        self.choicesChanged.emit()

    def keep_copy(self, about: str, song: int) -> None:
        """The copy `song` of the group about `about` kept instead (duplicates.rechoose)."""
        e = self.entry_of(about)
        if e is None:
            return
        kept, checked = self.choice_of(e)
        group = duplicates.Group(e.copies, e.likely, e.why)
        self._choose(about, duplicates.rechoose(group, kept, checked, song))

    def toggle_copy(self, about: str, song: int) -> None:
        """The copy `song` of the group about `about` checked for the trash, or not; never the
        copy kept."""
        e = self.entry_of(about)
        if e is None or song not in {c.song for c in e.copies}:
            return
        kept, checked = self.choice_of(e)
        if song != kept:
            self._choose(about, (kept, checked ^ {song}))

    @Slot(int, int)
    def keepCopy(self, row: int, song: int) -> None:  # noqa: N802
        """A copy's radio button (L09) on row `row`."""
        e = self.entry_at(row)
        if e is not None:
            self.keep_copy(e.about, song)

    @Slot(int, int)
    def toggleCopy(self, row: int, song: int) -> None:  # noqa: N802
        """A copy's checkbox (L09) on row `row`."""
        e = self.entry_at(row)
        if e is not None:
            self.toggle_copy(e.about, song)

    @Slot()
    def clearChecked(self) -> None:  # noqa: N802
        """The selection bar's ✕ (L09): every group's copies unchecked, the copy kept kept."""
        for e in self._all:
            if e.kind == attention.COPIES:
                kept, checked = self.choice_of(e)
                if checked:
                    self._choose(e.about, (kept, frozenset()))

    def checked_plans(self) -> list[tuple[str, Plan]]:
        """The plans of the groups the search keeps with copies checked (duplicates.plan), by
        what each is about: what the selection bar's Move N to the trash moves."""
        out = []
        for e in self._entries:
            if e.kind != attention.COPIES:
                continue
            kept, checked = self.choice_of(e)
            p = duplicates.plan(duplicates.Group(e.copies, e.likely, e.why), kept, checked)
            if p.gone:
                out.append((e.about, p))
        return out

    def checked(self) -> int:
        """The copies checked for the trash, in every group the search keeps (L09's bar)."""
        return sum(len(p.gone) for _, p in self.checked_plans())

    def searching(self) -> bool:
        return bool(words_of(self._search))

    def filtered(self) -> bool:
        return bool(self._shown)

    def shown_search(self) -> str:
        return self._shown

    def pending(self) -> bool:
        return self._pending

    def total(self) -> int:
        """Every entry needing attention (the sidebar's count), the search aside."""
        return len(self._all)

    def shown(self) -> int:
        return len(self._entries)

    def wait(self) -> None:
        self._searcher.wait()

    def show_ratings(self, ratings: object) -> None:
        """An entry shows no ratings."""

    def count_text(self) -> str:
        return count_text(self.shown(), self.total(), self.filtered())

    # ---------- the chips and the groups ----------

    @Slot(str)
    def choose(self, chip: str) -> None:
        """A chip: its groups open first, the others folded (All: every group folded)."""
        if chip not in {k for k, _, _ in CHIPS}:
            raise ValueError(f"no such chip: {chip}")
        self._chip, self._toggled = chip, set()
        self._shape()

    @Slot(str)
    def toggle(self, group: str) -> None:
        """A group's line: open it, or fold it."""
        self._toggled ^= {group}
        self._shape()

    def counts(self) -> dict[str, int]:
        """Each group's entries the search keeps, by group."""
        out: dict[str, int] = {}
        for e in self._entries:
            out[GROUP_OF[e.kind]] = out.get(GROUP_OF[e.kind], 0) + 1
        return out

    def entry_at(self, row: int) -> Entry | None:
        if not 0 <= row < len(self._rows) or self._rows[row][0] != "entry":
            return None
        return self._entries[self._rows[row][2]]

    def first_of(self, row: int) -> Entry | None:
        """The first entry of the group whose line is row `row` (the search's), for the group's
        own action; None for an entry's row."""
        if not 0 <= row < len(self._rows) or self._rows[row][0] != "group":
            return None
        key = self._rows[row][1]
        return next((e for e in self._entries if GROUP_OF[e.kind] == key), None)

    def entry_of_kind(self, kind: str, title: str) -> Entry | None:
        """The first entry of `kind` titled `title`, as last found (the tour's)."""
        return next((e for e in self._all if e.kind == kind and e.title == title), None)

    def row(self, n: int) -> dict[str, Any] | None:
        """Row n as the view shows it, made when first asked for."""
        if not 0 <= n < len(self._rows):
            return None
        made = self._made.get(n)
        if made is None:
            kind, key, i = self._rows[n]
            if kind == "entry":
                e = self._entries[i]
                made = entry_row(e, self.choice_of(e) if e.kind == attention.COPIES else None)
            else:
                group = BY_KEY[key]
                mine = [e for e in self._entries if GROUP_OF[e.kind] == key]
                made = group_row(group, mine, n + 1 < len(self._rows)
                                 and self._rows[n + 1][0] == "entry")  # fmt: skip
            self._made[n] = made
        return made

    # ---------- QAbstractListModel ----------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        base = int(Qt.ItemDataRole.UserRole)
        return {base + i: QByteArray(n.encode()) for i, n in enumerate(ROLES)}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        i = role - int(Qt.ItemDataRole.UserRole)
        made = self.row(index.row())
        if not 0 <= i < len(ROLES) or made is None:
            return None
        return made[ROLES[i]]

    count = QtProperty(int, lambda self: len(self._rows), notify=countChanged)
    chips = QtProperty(list, lambda self: chips_of(self.counts(), self._chip), notify=chipsChanged)
    chip = QtProperty(str, lambda self: self._chip, notify=chipsChanged)
    loading = QtProperty(bool, lambda self: self._pending or not self._found_once,
                         notify=countChanged)  # fmt: skip
    checkedCount = QtProperty(int, checked, notify=choicesChanged)  # L09's selection bar
    barText = QtProperty(str, lambda self: bar_text(self.checked()), notify=choicesChanged)
    moveLabel = QtProperty(str, lambda self: move_label(self.checked()), notify=choicesChanged)


# ---------- Merge for an artist's or an album's names ----------


class NameMerge(QObject):
    """Merge for an artist's or an album's names (R2.8): the dialog of the Edit tags panel's bulk
    tools (ToolDialog.qml) over the songs with any of the names, the name to keep chosen among
    them (the most used at first), the preview of the files that change (preview.Preview), and its
    save: a batch on a thread of its own with its progress in the footer, Cancel, the files that
    failed named with Retry, one entry in the change history and the message with Undo (R4.7,
    R4.9). As musikata.genres' Genres does for a genre; `write`, `history`, `saved`, `undoable`,
    `executor` and `available` as there."""

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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._read, self._write = root, read, write
        self._history, self._saved, self._available = history, saved, available
        self._undoable = undoable and history is not None
        self._executor = executor
        self._searcher = Searcher(self)
        self._preview = Preview(root, parent=self)
        self._entry: Entry | None = None
        self._into = ""
        self._songs: list[Song] = []
        self._loading = False
        self._ticket = 0
        self._batch: Batch[Written] | None = None
        self._progress = (0, 0)
        self._failed: list[Failed] = []
        self._problem = ""
        self._description = ""
        self._closed = False
        self._progressed.connect(self._on_progress)
        self._done.connect(self._on_done)
        self._preview.changed.connect(self.changed)

    def open(self, entry: Entry) -> None:
        """The merge of a names entry's spellings (NAMES_ARTIST or NAMES_ALBUM), the most used
        chosen; its songs read off the GUI thread."""
        if self._batch is not None or entry.kind not in (attention.NAMES_ARTIST,
                                                         attention.NAMES_ALBUM):  # fmt: skip
            return
        self._entry, self._into, self._songs = entry, entry.names[0], []
        self._failed, self._problem = [], ""
        self._ticket += 1
        ticket, read, root = self._ticket, self._read, self._root
        self._loading = True
        self._plan()

        def work() -> list[Song]:
            found = attention.songs_of(read(), entry.kind, entry.key)
            return [Song(scanner.full_path(root, p), t) for p, t in found]

        def then(songs: list[Song] | None) -> None:
            if ticket == self._ticket and not self._closed:
                self._loading, self._songs = False, songs or []
                self._plan()

        self._searcher.submit("songs", work, then)

    def _plan(self) -> None:
        e = self._entry
        if e is None:
            planned = Planned((), (), ())
        else:
            planned = attention.merge_names(self._songs, e.kind, e.names, self._into)
        self._preview.show(planned, self._undoable)
        self.changed.emit()

    @Slot(str, "QVariant")
    def setOption(self, name: str, value: Any) -> None:  # noqa: N802
        """The spelling to keep ("into"), one of the entry's."""
        if self._entry is None or self._batch is not None:
            return
        if name != "into":
            raise ValueError(f"no such option: {name}")
        if str(value) in self._entry.names:
            self._into = str(value)
            self._plan()

    @Slot(str)
    def toggleField(self, name: str) -> None:  # noqa: N802
        self.setOption("into", name)

    @Slot()
    def close(self) -> None:
        """Cancel, ×, or Esc: nothing saved; while a save goes on, it stops before its next
        file."""
        if self._batch is not None:
            self._batch.cancel()
            return
        if self._entry is not None:
            self._entry, self._songs, self._failed = None, [], []
            self._ticket += 1
            self._preview.show(Planned((), (), ()))
            self.changed.emit()

    def description_of(self, songs: int) -> str:
        """The save's entry in the change history (R4.9): Artist lumen drift merged into Lumen
        Drift on 3 songs."""
        e = self._entry
        if e is None:
            return ""
        what = "Artist" if e.kind == attention.NAMES_ARTIST else "Album"
        gone = and_text([n for n in e.names if n != self._into])
        return f"{what} {gone} merged into {self._into} on {plural(songs, 'song')}"

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
            self._description = self.description_of(len(jobs))
        record = self._history.recording() if self._history is not None else None
        batch: Batch[Written] = Batch(jobs, self._write, self._progressed.emit, record=record,
                                      action=NAMES, description=self._description)  # fmt: skip
        self._batch, self._progress, self._failed = batch, (0, len(jobs)), []
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="names")
        self.changed.emit()
        self._executor.submit(self._run, batch, jobs)

    def _run(self, batch: Batch[Written], jobs: list[Job]) -> None:
        try:
            out = batch.run()
        except Exception as e:  # noqa: BLE001  (the batch fails its files, never itself; logged)
            log.exception("merging names failed")
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
        self._entry = None
        self._preview.show(Planned((), (), ()))
        self.changed.emit()

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

    def _get_options(self) -> dict[str, Any]:
        e = self._entry
        if e is None:
            return {}
        fields = [{"name": n, "label": f"{n} ({c:,})", "chosen": n == self._into}
                  for n, c in zip(e.names, e.counts, strict=True)]  # fmt: skip
        return {"fields": fields, "single": True, "choose": "into"}

    def _get_title(self) -> str:
        e = self._entry
        if e is None:
            return ""
        return (
            "Merge into one artist"
            if e.kind == attention.NAMES_ARTIST
            else ("Merge into one album")
        )

    def _get_about(self) -> str:
        e = self._entry
        if e is None:
            return ""
        fields = "artist and album artist" if e.kind == attention.NAMES_ARTIST else "album"
        return (f"Every song whose {fields} is {and_text(list(e.names)).replace(' and ', ' or ')}"
                " gets the name chosen; the most used at first.")  # fmt: skip

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
        if self._failed:
            return ""
        return "" if self._preview.chosen() else "Nothing to save"

    opened = QtProperty(bool, lambda self: self._entry is not None, notify=changed)
    tool = QtProperty(str, lambda self: "merge" if self._entry is not None else "", notify=changed)
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


def _gone() -> bool:
    return False


# ---------- the actions and Ignore ----------


class Attention(QObject):
    """Needs attention's actions (R2.8) on the entries of `model`: Edit tags on `edit` (the Edit
    tags panel, musikata.edittags), Album art on `art` (musikata.albumart), Merge on `genres`
    (musikata.genres) or `names` (`NameMerge`), Review… on `copies` (musikata.duplicates' dialog,
    R2.12), Fix encoding… on `encoding` (musikata.encodings' dialog, R4.10), Infer from path on
    `infer` (musikata.infer's, R3), Find on `playlists` (musikata.playlists' dialog, R8.7), Show
    in folder through `reveal` (a command, or the folder
    opened by `open_folder`), and Ignore. A dismissal is written into the root's
    ignored.json (read again and merged first) and the index on `executor` (its own thread when
    None) at `clock`'s time, or the index only when `.musikata` can't be written (R1.5.2); the
    list is found again then. With `watching`, `.musikata` is watched for another computer's
    dismissals. `history` says why a dismissal couldn't be kept."""

    _kept = Signal(str)  # a dismissal kept (""), or why not
    _reread = Signal()
    _fallback = Signal(str)  # Show in folder had no way to select the file: its folder opened

    def __init__(
        self,
        root: str,
        index: db.Index,
        model: AttentionModel,
        clock: Clock,
        edit: QObject | None = None,
        art: QObject | None = None,
        genres: QObject | None = None,
        names: NameMerge | None = None,
        history: ChangeHistory | None = None,
        copies: Duplicates | None = None,
        encoding: FixEncoding | None = None,
        infer: InferFromPath | None = None,
        playlists: Playlists | None = None,
        watching: bool = True,
        executor: Executor | None = None,
        reveal: Callable[[str], list[str] | None] | None = None,
        run: Callable[[list[str]], bool] = _run,
        open_folder: Callable[[str], object] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._index, self._model, self._clock = root, index, model, clock
        self._edit, self._art, self._genres, self._names = edit, art, genres, names
        self._history, self._copies, self._encoding = history, copies, encoding
        self._infer, self._playlists = infer, playlists
        self._watching = watching
        self._executor = executor
        self._reveal = reveal or (lambda p: reveal_command(p, sys.platform, shutil.which))
        self._run_command, self._open_folder = run, open_folder or _open_folder
        self._musikata = rootfiles.folder_of(root)
        self._watcher: watch.Watcher | None = None
        self._closed = False
        self._kept.connect(self._on_kept)
        self._reread.connect(self._on_reread)
        self._fallback.connect(self._on_fallback)

    def _submit(self, job: Callable[[], object]) -> None:
        if self._closed:
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="attention")
        self._executor.submit(self._guarded, job)

    @staticmethod
    def _guarded(job: Callable[[], object]) -> None:
        try:
            job()
        except Exception:  # noqa: BLE001  (a job that breaks is logged; MusiKata goes on)
            log.exception("a Needs attention job failed")

    # ---------- ignored.json read and watched (A2.8) ----------

    def start(self) -> None:
        """Reads the root's ignored.json into the index, off this thread; then watches
        `.musikata` for another computer's dismissals."""
        if self._watching and os.path.isdir(self._musikata):
            self._watcher = watch.Watcher(self._musikata, watch.Gatherer(self._clock), parent=self)
            self._watcher.ready.connect(self._on_ready)
        self.reread()

    def reread(self) -> None:
        """ignored.json read into the index again, off this thread; the list found again."""
        index, root = self._index, self._root

        def job() -> None:
            found = rootfiles.read_ignored(rootfiles.ignored_of(root))
            if found is not None and not found.broken:
                entries = found.entries
                index.write(lambda c: rootfiles.load_ignored(c, entries)).result()
            self._reread.emit()

        self._submit(job)

    @Slot()
    def _on_reread(self) -> None:
        if self._closed:
            return
        if self._watcher is not None:
            self._watcher.watch({"": self._musikata})
        self._model.refresh()

    @Slot()
    def _on_ready(self) -> None:
        assert self._watcher is not None
        if "" in self._watcher.take():
            self.reread()

    # ---------- the actions ----------

    @Slot(int, str)
    def act(self, row: int, action: str) -> None:
        """An entry's action (row `row` of the list): "edit", "art", "merge", "review", "fix",
        "infer", "find", "folder" or "ignore"; or a group's (its line's row): "fix", on its first
        entry."""
        e = self._model.entry_at(row)
        if e is None:
            first = self._model.first_of(row)
            if action == "fix" and first is not None and self._encoding is not None:
                self._encoding.open(first)
            return
        if action == "ignore":
            self.ignore(e)
        elif action == "edit" and self._edit is not None and e.album is not None:
            self._edit.editAlbum(e.album, None)  # type: ignore[attr-defined]
        elif action == "art" and self._art is not None and e.album is not None:
            self._art.openAlbum(e.album)  # type: ignore[attr-defined]
        elif action == "merge" and e.kind == attention.NAMES_GENRE and self._genres is not None:
            self._genres.merge_names(list(e.names))  # type: ignore[attr-defined]
        elif action == "merge" and self._names is not None:
            self._names.open(e)
        elif action == "review" and self._copies is not None:
            self._copies.open(e)
        elif action == "fix" and self._encoding is not None:
            self._encoding.open(e)
        elif action == "infer" and self._infer is not None:
            self._infer.open(e)
        elif action == "find" and self._playlists is not None:
            self._playlists.find_entry(e)
        elif action == "folder":
            self.show_in_folder(scanner.full_path(self._root, e.about))
        elif action not in ("edit", "art", "merge", "review", "fix", "infer", "find"):
            raise ValueError(f"no such action: {action}")

    def show_in_folder(self, path: str) -> None:
        """Show in folder (R2.8): the system's file manager, the file selected where it can be,
        else its folder opened; off this thread, as a file manager may take a moment."""
        command = self._reveal(path)
        folder = os.path.dirname(path)
        run = self._run_command

        def job() -> None:
            if command is None or not run(command):
                self._fallback.emit(folder)

        self._submit(job)

    @Slot(str)
    def _on_fallback(self, folder: str) -> None:
        self._open_folder(folder)

    def ignore(self, e: Entry) -> None:
        """Ignore (R2.8): the entry dismissed until its file changes, kept in ignored.json and
        the index; the list found again."""
        d = attention.dismissal_of(e, rootfiles.time_text(self._clock.now()))
        index, musikata, root = self._index, self._musikata, self._root

        def job() -> None:
            why = ""
            if rootfiles.writable(musikata):
                try:
                    rootfiles.save_ignored(rootfiles.ignored_of(root), [d])
                except rootfiles.IgnoredError as err:
                    why = err.why
            else:
                log.warning("%s can't be written: the dismissal of %s is kept in this computer's"
                            " index only", musikata, d.about)  # fmt: skip
            if not why:
                index.write(lambda c: rootfiles.load_ignored(c, [d])).result()
            self._kept.emit(why)

        self._submit(job)

    @Slot(str)
    def _on_kept(self, why: str) -> None:
        if self._closed:
            return
        if why and self._history is not None:
            self._history.say(f"It wasn't ignored: {why}")
        self._model.refresh()

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"attention": "names"} chooses that chip in Needs attention."""
        if step.get("view") == "attention":
            self._model.choose(str(step.get("attention", "all")))

    def close(self) -> None:
        """Stops watching and waits for a job going on; nothing starts after. What the threads
        held is let go (A1.3)."""
        self._closed = True
        if self._watcher is not None:
            self._watcher.close()
            self._watcher = None
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._edit = self._art = self._genres = self._names = self._history = None
        self._copies = self._encoding = self._infer = None


def _open_folder(folder: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
