"""The Folders view (R2.9, A2.7), as QML sees it: `FolderModel`, the one list every mode binds to
(the open folder's subfolders, then its own audio files; or, while a search filters it, the
folders and files beneath it that match, R2.9.2), with the selection (R2.9.6); and `FolderView`,
the open folder: where it is (the crumbs, the title, the count, R2.9.1), going up and back, the view
mode (R2.9.4), a folder of songs' strip (R2.9.7), and Play. The mode is the QML delegate, not
another model, so switching modes keeps the selection and the place (A2.7).

Where Folders was left (the open folder and the mode) is a `Remembered`: kept for the run here; the
Settings store that keeps it between runs comes with slice 9 (R13), and is given in its place.

What every text says, and what a click does, is decided here (docs/process/coding.md: QML only lays
out and binds); a song to play goes out by the `play` signal, which the app connects to the
Player."""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import folders as index_folders
from musikata_core import patterns
from musikata_core.tags.tools import text_of

from .covers import mosaic_id
from .history import LABELS
from .models import (
    COVERS,
    PAGE,
    PagedModel,
    Searcher,
    cover_url,
    format_text,
    plural,
    size_text,
    time_text,
    title_of,
)

ROOT_TITLE = "Your music folders"  # the title at the root, whose own name is never shown (R2.9.1)
SEARCH_HINT = "Search folders"
CRUMB = " › "  # between the folders of a path shown under the open folder
# the view modes (R2.9.4), in the header's switch: its name, label and icon
MODES = [
    {"mode": "large", "label": "Large images", "icon": "large"},
    {"mode": "small", "label": "Small images", "icon": "small"},
    {"mode": "cards", "label": "Cards", "icon": "cards"},
    {"mode": "list", "label": "List", "icon": "list"},
]
DEFAULT_MODE = "small"
# the selection bar's actions (R2.9.6) after Play: Add to playlist (R8), Edit tags (R4.2), Infer
# from path (R3.1) and Album art (R5.2), by their `action`, Album art only when the songs are one
# album (`selection_actions`), and Organize… (R12.2); the right-click menu holds Play next, Add to
# queue (R7.2), Add to playlist, Edit tags, Infer from path, Album art (when the row's songs are one
# album), Organize files… and Show in file manager, and dragging (R6.10) comes whole with its own
EDIT = {"label": "Edit tags", "icon": "genre", "later": "", "action": "edit"}
ART = {"label": "Album art", "icon": "image", "later": "", "action": "art"}
INFER = {"label": "Infer from path", "icon": "wand", "later": "", "action": "infer"}
LATER = [
    {"label": "Add to playlist", "icon": "plus", "later": "", "action": "playlist"},
    EDIT,
    INFER,
    {"label": "Organize…", "icon": "arrow", "later": "", "action": "organize"},
]
# a folder of songs' buttons (R2.9.7, L08): Infer from path (R3.1, the first), Edit tags (R4.2)
# and Album art (R5.2)
STRIP = [{**INFER, "primary": True}, EDIT, ART]
# R3.9's states as Folders shows them: a folder's dot on its cover (R2.9.5) and a chip's tone
TONES = {patterns.FIX: "warn", patterns.BARE: "err"}
# how a song's tag differs from its path, said of the field (a chip, R3.9) and of files (the
# strip's line, R2.9.7)
CHIP_HOW = {"missing": "{} missing", "case": "{} case differs", "differs": "{} differs"}


@dataclass
class Remembered:
    """Where Folders was left (R2.9.1): the open folder (its path under the root) and the view
    mode, which it opens with next time. This one lasts the run; the Settings store of slice 9
    keeps them between runs."""

    folder: str = ""
    mode: str = DEFAULT_MODE


# ---------- what the texts say ----------


def folder_line(folders: int, songs: int) -> str:
    """A folder's counts (R2.9.1, R2.9.4): 2 folders · 21 songs; 10 songs when it holds no
    folder."""
    return " · ".join(([plural(folders, "folder")] if folders else []) + [plural(songs, "song")])


def found_line(folders: int, files: int) -> str:
    """What a search found beneath the open folder (R2.9.2): 2 folders · 5 songs found."""
    parts = ([plural(folders, "folder")] if folders else []) + (
        [plural(files, "song")] if files or not folders else []
    )
    return " · ".join(parts) + " found"


def selection_text(folders: int, files: int, songs: int) -> str:
    """The selection bar's count (R2.9.6): 2 folders · 21 songs selected; a folder and a file
    selected together: 1 folder · 1 file · 11 songs selected; files alone: 2 songs selected."""
    if not folders:
        return f"{plural(songs, 'song')} selected"
    parts = [plural(folders, "folder")] + ([plural(files, "file")] if files else [])
    return " · ".join([*parts, plural(songs, "song")]) + " selected"


def selection_actions(one_album: bool) -> list[dict[str, str]]:
    """The selection bar's actions after Play (R2.9.6), in its order: Album art among them when
    the songs selected are one album."""
    if not one_album:
        return LATER
    return [*LATER[:-1], ART, LATER[-1]]


def where_text(path: str, folder: str) -> str:
    """Where a match is under the open folder (R2.9.2): the folders between, as Remixes › Glass
    Harbor; "" for one in the open folder itself."""
    parent = path.rpartition("/")[0]
    under = parent[len(folder) + 1 :] if folder else parent
    return CRUMB.join(under.split("/")) if under else ""


def picture_url(thumb: str | None, mosaic: str | None) -> str:
    """What a folder's cover shows (R5.8): its own cover; else one picture whole, or the mosaic
    the cover provider draws; "" for none (the dashed No art tile)."""
    if thumb:
        return cover_url(thumb)
    pieces = (mosaic or "").split()
    if len(pieces) == 1:
        return cover_url(pieces[0])
    return COVERS + mosaic_id(pieces) if pieces else ""


def fold_crumbs(widths: Sequence[float], room: float, ellipsis: float, gap: float) -> int:
    """How many crumbs after the first become … so the crumbs fit `room` (R2.9.1): none when all
    fit, else the fewest from the second on; at most all but the first and last. `widths` are the
    crumbs', `ellipsis` the …'s, `gap` what each separator takes."""
    n = len(widths)
    if sum(widths) + gap * max(0, n - 1) <= room or n <= 2:
        return 0
    for hidden in range(1, n - 1):
        if widths[0] + ellipsis + sum(widths[1 + hidden :]) + gap * (n - hidden) <= room:
            return hidden
    return n - 2


def odd_ones(values: Sequence[object]) -> list[bool]:
    """Which values differ from the rest of a folder's (R2.9.7): those present that aren't its
    most common value, when they don't all agree."""
    counted = Counter(v for v in values if v not in (None, ""))
    if len(counted) < 2:
        return [False] * len(values)
    top = max(counted.values())
    common = next(v for v in values if v not in (None, "") and counted[v] == top)
    return [v not in (None, "") and v != common for v in values]


def art_line(image: str | None, embedded: int, songs: int) -> str:
    """Where a folder of songs' art comes from (R2.9.7): Cover from folder.jpg, not embedded."""
    name = image.rpartition("/")[2] if image else ""
    if name and not embedded:
        return f"Cover from {name}, not embedded"
    if name:
        return f"Cover from {name}, embedded in {embedded} of {songs}"
    if embedded:
        return f"Cover embedded in {embedded} of {songs}"
    return "No cover"


def art_chip(image: str | None, embedded: int, songs: int) -> dict[str, str]:
    """A folder of songs' art chip (R2.9.7), its text and tone."""
    if embedded and embedded == songs:
        return {"text": f"Art embedded in {embedded} of {songs}", "tone": "ok"}
    if embedded:
        return {"text": f"Art embedded in {embedded} of {songs}", "tone": "warn"}
    if image:
        return {"text": "Art in folder only", "tone": "info"}
    return {"text": "No art", "tone": "warn"}


# ---------- tags match path (R3.9) ----------


def field_label(field: str) -> str:
    """A field as a chip names it: Artist, Album artist, Track, Genre."""
    return LABELS.get(field, field)


def file_chip(state: int | None, diffs: Sequence[patterns.Difference]) -> dict[str, str]:
    """A file's path-match chip (R3.9, L05, L08): Match; Year missing, Artist case differs, Genre
    differs for one field; for more, Case differs when they differ only in case, else 3 tags
    differ, 3 tags missing; No tags; none ({}) when no pattern fits it."""
    if state is None:
        return {}
    if state == patterns.BARE:
        return {"text": "No tags", "tone": "err"}
    if state == patterns.MATCH or not diffs:
        return {"text": "Match", "tone": "ok"}
    if len(diffs) == 1:
        d = diffs[0]
        return {"text": CHIP_HOW.get(d.how, "{} differs").format(field_label(d.field)),
                "tone": "warn"}  # fmt: skip
    hows = {d.how for d in diffs}
    if hows == {"case"}:
        return {"text": "Case differs", "tone": "warn"}
    how = "missing" if hows == {"missing"} else "differ"
    return {"text": f"{len(diffs)} tags {how}", "tone": "warn"}


def folder_chip(state: int | None, fix: int) -> dict[str, str]:
    """A folder's state chip on cards and in List (R2.9.5, L06): No tags, 3 to fix; none ({})
    when its files all match."""
    if state == patterns.BARE:
        return {"text": "No tags", "tone": "err"}
    if state == patterns.FIX and fix:
        return {"text": f"{fix:,} to fix", "tone": "warn"}
    return {}


def match_chip(states: Sequence[int | None]) -> dict[str, str]:
    """A folder of songs' or an album's chip (R2.9.7, L02, L08): Tags match path, or how many of
    its files do (Tags match path: 7 of 9), amber when some can be fixed, red when one has no
    tags; none ({}) when no pattern fits any."""
    known = [s for s in states if s is not None]
    if not known:
        return {}
    matched = sum(s == patterns.MATCH for s in known)
    if matched == len(states):
        return {"text": "Tags match path", "tone": "ok"}
    tone = "err" if patterns.BARE in known else "warn"
    return {"text": f"Tags match path: {matched} of {len(states)}", "tone": tone}


def _files(n: int) -> str:
    return plural(n, "file")


def _says(field: str, value: str) -> str:
    """What the path says of a field, in words: the album is from 2022; the artist is Lumen
    Drift."""
    if field == "year":
        return f"the album is from {value}"
    noun = {"genres": "genre", "albumartist": "album artist"}.get(field, field)
    return f"the {noun} is {value}"


def _how_text(field: str, how: str, values: Sequence[str], n: int, said: bool = False) -> str:
    """What n files do with a field: have no year; spell the artist in lower case; have another
    genre. `said`: the field the sentence has named already, spelled "it"."""
    noun = {"genres": "genre", "albumartist": "album artist", "track": "track number",
            "disc": "disc number", "tracktotal": "track total"}.get(field, field)  # fmt: skip
    has = "has" if n == 1 else "have"
    if how == "missing":
        return f"{has} no {noun}"
    if how == "case":
        spells = "spells" if n == 1 else "spell"
        it = "it" if said else f"the {noun}"
        if all(v.islower() for v in values):
            return f"{spells} {it} in lower case"
        if all(v.isupper() for v in values):
            return f"{spells} {it} in capitals"
        return f"{spells} {it} in another case"
    return f"{has} another {noun}"


def path_line(rows: Sequence[tuple[Sequence[patterns.Difference], dict[str, str]]]) -> str:
    """The strip's line when files differ from their path (R2.9.7, L08): what the path says, then
    how many files differ and how: "The path says the album is from 2022, but 1 file has no year
    and 1 spells the artist in lower case." Each row is a file's differences and its tags'
    values (as the preview shows them), by field; "" when none differs."""
    groups: dict[tuple[str, str], list[str]] = {}
    said: dict[str, set[str]] = {}
    for diffs, tagged in rows:
        for d in diffs:
            groups.setdefault((d.field, d.how), []).append(tagged.get(d.field, ""))
            said.setdefault(d.field, set()).add(d.value)
    if not groups:
        return ""
    first = next(iter(groups))[0]
    claimed = len(said[first]) == 1 and first not in ("title", "track", "disc")
    parts = []
    for n, ((field, how), olds) in enumerate(groups.items()):
        count = _files(len(olds)) if n == 0 else f"{len(olds):,}"
        it = claimed and field == first
        parts.append(f"{count} {_how_text(field, how, olds, len(olds), it)}")
    claim = (
        f"The path says {_says(first, next(iter(said[first])))}, but "
        if claimed
        else "The tags differ from the path: "
    )
    return claim + and_text(parts) + "."


def and_text(parts: Sequence[str]) -> str:
    """Parts in a sentence: A; A and B; A, B and C."""
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# ---------- the model ----------

# a folder's row and a song's, as one list's columns: the kind (0 folder, 1 file), its id, its key
# in the list (even for a folder, odd for a file), its name's sort key and path, then what it shows
FOLDER_COLUMNS = (
    "0 AS kind, id AS rid, id * 2 AS k, name_key AS nk, path, name, folders,"
    " songs_beneath AS songs, length, artist, album, year, thumb, mosaic, NULL AS title,"
    " NULL AS track, NULL AS rating, NULL AS genre, path_state AS state, path_fix AS fix"
)
FILE_COLUMNS = (
    "1, id, id * 2 + 1, name_key, path, NULL, NULL, NULL, length, artist, album, year, NULL,"
    " NULL, title, track, rating,"
    " (SELECT group_concat(genre, '; ' ORDER BY position) FROM song_genre WHERE song_id = song.id),"
    " path_state, path_diff"
)
ORDER = "kind, nk, path"  # folders, then files, each by name (R2.9.2)


class FolderModel(PagedModel):
    """The open folder's subfolders, then its files (R2.9.2); while a search filters it, the
    folders and files beneath it that match (R2.7), each with where it is. Each row's key is even
    for a folder and odd for a file. It holds the selection (R2.9.6), by key, so every mode shows
    the same one."""

    roles = (
        "key", "kind", "path", "name", "line", "cover", "title", "numbered", "artist", "album",
        "genre", "year", "rating", "time", "third", "where", "odd", "playing", "selected",
        "dot", "pathChip",
    )  # fmt: skip
    key = "k"
    selectionChanged = Signal()

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        parent: QObject | None = None,
        searcher: Searcher | None = None,
    ) -> None:
        super().__init__(read, parent, searcher)
        self._folder = ""
        self._playing = ""
        self._selected: set[int] = set()
        self._anchor = -1
        self._common: dict[str, list[object]] = {}

    def _query(self) -> tuple[str, str, str, tuple[Any, ...], str]:
        if self._query_of_search:
            fw, fp = index_folders.beneath("path", self._folder)
            sw, sp = index_folders.beneath("path", self._folder)
            table = (
                f"(SELECT {FOLDER_COLUMNS} FROM folder WHERE {fw}"
                f" UNION ALL SELECT {FILE_COLUMNS} FROM song WHERE {sw})"
            )
            return "*", table, "", (*fp, *sp), ORDER
        table = (
            f"(SELECT {FOLDER_COLUMNS} FROM folder WHERE parent = ?"
            f" UNION ALL SELECT {FILE_COLUMNS} FROM song WHERE folder = ?)"
        )
        return "*", table, "", (self._folder, self._folder), ORDER

    def _narrow(self, songs: str, params: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
        """A file the search finds, or a folder whose name holds its words (R2.9.2)."""
        named, named_params = index_folders.condition(self._query_of_search)
        return (
            f"((kind = 1 AND rid IN (SELECT song.id FROM song WHERE {songs}))"
            f" OR (kind = 0 AND rid IN (SELECT folder.id FROM folder WHERE {named})))",
            (*params, *named_params),
        )

    def _read_page(self, p: int) -> list[dict[str, Any] | None]:
        ids = (self._ids or [])[p * PAGE : (p + 1) * PAGE]
        c = self._read()
        rows: dict[int, dict[str, Any]] = {}
        for kind, table, cols in ((0, "folder", FOLDER_COLUMNS), (1, "song", FILE_COLUMNS)):
            wanted = [k // 2 for k in ids if k % 2 == kind]
            for i in range(0, len(wanted), 500):
                chunk = wanted[i : i + 500]
                marks = ", ".join("?" * len(chunk))
                for r in c.execute(f"SELECT {cols} FROM {table} WHERE id IN ({marks})", chunk):
                    rows[r[2]] = self._row(r)
        return [rows.get(k) for k in ids]  # None for a row gone since the search

    def _row(self, r: tuple[Any, ...]) -> dict[str, Any]:
        kind, _rid, k, _nk, path, name, folders, songs, length, artist, album, year = r[:12]
        thumb, mosaic, title, track, rating, genre, state, more = r[12:]
        where = where_text(path, self._folder) if self._query_of_search else ""
        if kind == 0:
            line = folder_line(folders, songs)
            return {
                "key": k, "kind": "folder", "path": path, "name": name,
                "line": f"{where} · {line}" if where else line,
                "cover": picture_url(thumb, mosaic), "title": name, "numbered": name,
                "artist": artist or "", "album": album or "", "genre": "",
                "year": str(year) if year else "", "rating": 0, "time": time_text(length),
                "third": where if self._query_of_search else album or "", "where": where,
                "odd": [], "dot": TONES.get(state, ""), "pathChip": folder_chip(state, more or 0),
            }  # fmt: skip
        shown = title_of(title, path)
        values = {"artist": artist, "genre": genre, "year": year}
        return {
            "key": k, "kind": "file", "path": path, "name": index_folders.name_of(path),
            "line": where, "cover": "", "title": shown,
            "numbered": f"{track} · {shown}" if track else shown, "artist": artist or "",
            "album": album or "", "genre": genre or "", "year": str(year) if year else "",
            "rating": rating or 0, "time": time_text(length),
            "third": where if self._query_of_search else album or "", "where": where,
            "odd": [] if self._query_of_search
            else [f for f, v in values.items() if v in self._common.get(f, [])],
            "dot": "", "pathChip": file_chip(state, index_folders.diffs_of(more)),
        }  # fmt: skip

    def _value(self, row: dict[str, Any], name: str) -> Any:
        if name == "playing":
            if row["kind"] == "folder":
                return self._playing.startswith(row["path"] + "/")
            return row["path"] == self._playing
        if name == "selected":
            return row["key"] in self._selected
        return row[name]

    # ---------- what it lists ----------

    def open(self, folder: str) -> None:
        """Lists `folder` (a path under the root, "" for the root) instead, with no search and
        nothing selected."""
        self._folder = folder
        self._selected.clear()
        self._anchor = -1
        self._find_odd()
        if self.searching():
            self.set_search("")
        else:
            self.reload()
        self.selectionChanged.emit()

    def folder(self) -> str:
        return self._folder

    def set_search(self, text: str) -> None:
        self._selected.clear()
        self._anchor = -1
        super().set_search(text)
        self.selectionChanged.emit()

    def refresh(self) -> None:
        self._find_odd()
        super().refresh()
        self.selectionChanged.emit()  # what the selection stands for may have changed

    def _find_odd(self) -> None:
        """The values that differ from the rest among the open folder's own files (R2.9.7)."""
        rows = (
            self._read()
            .execute(
                "SELECT artist, (SELECT group_concat(genre, '; ' ORDER BY position) FROM song_genre"
                " WHERE song_id = song.id), year FROM song WHERE folder = ?",
                (self._folder,),
            )
            .fetchall()
        )
        self._common = {}
        for i, name in enumerate(("artist", "genre", "year")):
            values = [r[i] for r in rows]
            self._common[name] = [v for v, odd in zip(values, odd_ones(values), strict=True) if odd]

    def folder_rows(self) -> int:
        """How many of its rows are folders: they come first."""
        ids = self._ids or []  # none before its rows are first found
        return next((i for i, k in enumerate(ids) if k % 2), len(ids))

    def set_playing(self, path: str) -> None:
        """Marks the song at `path` and the folders holding it as playing ("": none)."""
        if path != self._playing:
            self._playing = path
            self._changed("playing")

    def source(self) -> str:
        """The open folder's name, where the queue says it plays from (R7.2)."""
        return index_folders.name_of(self._folder) if self._folder else ROOT_TITLE

    def queue_from(self, row: int) -> tuple[list[int], str]:
        """What a double click or a cover's play button on row `row` plays (R7.1): a file and the
        files after it in the list, or a folder's songs, from its first; and their name."""
        row_ = self.row(row)
        if row_ is None:
            return [], ""
        if row_["kind"] == "folder":
            return index_folders.songs_beneath(self._read(), row_["path"]), row_["name"]
        files = [k // 2 for k in (self._ids or []) if k % 2]
        song = int(row_["key"]) // 2
        return files[files.index(song) :] if song in files else [song], self.source()

    def songs_at(self, row: int) -> list[int]:
        """The songs row `row` stands for (R7.2): a file's own, or those beneath a folder."""
        row_ = self.row(row)
        if row_ is None:
            return []
        if row_["kind"] == "folder":
            return index_folders.songs_beneath(self._read(), row_["path"])
        return [int(row_["key"]) // 2]

    def path_at(self, n: int) -> str | None:
        """Row n's folder or file, by its path under the root; None past the rows."""
        row_ = self.row(n)
        return None if row_ is None else str(row_["path"])

    def song_at(self, n: int) -> int | None:
        """A file's song, by id (its key is odd); None for a folder's row."""
        k = self._key_at(n)
        return k // 2 if k is not None and k % 2 else None

    def is_selected(self, n: int) -> bool:
        """Whether row n is selected."""
        return self._key_at(n) in self._selected

    def selected_songs(self) -> list[int]:
        """The songs the selection stands for, in the list's order, each once (R2.9.6): a
        folder's from its first, then the next row's."""
        c = self._read()
        out: dict[int, None] = {}
        for k in self._ids or []:
            if k not in self._selected:
                continue
            if k % 2:
                out[k // 2] = None
                continue
            r = c.execute("SELECT path FROM folder WHERE id = ?", (k // 2,)).fetchone()
            if r is not None:
                out.update(dict.fromkeys(index_folders.songs_beneath(c, r[0])))
        return list(out)

    # ---------- the selection (R2.9.6) ----------

    def _key_at(self, n: int) -> int | None:
        row = self.row(n)
        return None if row is None else int(row["key"])

    @Slot(int, bool, bool)
    def click(self, n: int, ctrl: bool, shift: bool) -> None:
        """A click on row n: it alone selected; with Ctrl (⌘), it added or taken away; with Shift,
        the rows from the last clicked to it."""
        k = self._key_at(n)
        if k is None:
            return
        if shift and self._anchor >= 0:
            low, high = sorted((self._anchor, n))
            keys = {self._key_at(i) for i in range(low, high + 1)}
            self._selected = (self._selected if ctrl else set()) | {
                x for x in keys if x is not None
            }
        elif ctrl:
            self._selected ^= {k}
            self._anchor = n
        else:
            self._selected = {k}
            self._anchor = n
        self._selection_changed()

    @Slot(int)
    def toggle(self, n: int) -> None:
        """Row n's checkbox: it added to the selection or taken away."""
        self.click(n, True, False)

    @Slot(list, bool)
    def selectRows(self, rows: list[int], add: bool) -> None:  # noqa: N802
        """The rows a drag box covers selected, added to those selected before when `add`."""
        keys = {self._key_at(int(n)) for n in rows}
        self._selected = (self._selected if add else set()) | {x for x in keys if x is not None}
        self._selection_changed()

    @Slot()
    def selectAll(self) -> None:  # noqa: N802
        self.selectRows(list(range(self.rowCount())), False)

    @Slot()
    def clearSelection(self) -> None:  # noqa: N802
        self._selected.clear()
        self._anchor = -1
        self._selection_changed()

    def _selection_changed(self) -> None:
        self._changed("selected")
        self.selectionChanged.emit()

    @Slot(int, result=int)
    def albumAt(self, n: int) -> int:  # noqa: N802
        """The album the songs row `n` stands for are on, as its right-click menu's Album art opens
        it (R2.9.6): the selection's when the row is in it; -1 when they aren't one album."""
        if self.is_selected(n):
            return self.selected_album()
        row = self.row(n)
        if row is None:
            return -1
        folders, files = ([row["path"]], []) if row["kind"] == "folder" else ([], [row["path"]])
        found = index_folders.album_of(self._read(), folders, files)
        return -1 if found is None else found

    def selected_album(self) -> int:
        """The album the songs selected are all on (R2.9.6), by id; -1 when they aren't one."""
        folders, files = self.selected()
        found = index_folders.album_of(self._read(), folders, files)
        return -1 if found is None else found

    def selected(self) -> tuple[list[str], list[str]]:
        """The folders and files selected that are still there, each by its path, in the list's
        order."""
        c = self._read()
        out: tuple[list[str], list[str]] = ([], [])
        for kind, table in ((0, "folder"), (1, "song")):
            ids = [k // 2 for k in self._selected if k % 2 == kind]
            if ids:
                marks = ", ".join("?" * len(ids))
                found = c.execute(
                    f"SELECT path FROM {table} WHERE id IN ({marks}) ORDER BY name_key, path", ids
                )
                out[kind].extend(p for (p,) in found)
        return out

    def selection_state(self) -> str:
        """The List header's checkbox: "none", "some" or "all" selected."""
        if not self._selected:
            return "none"
        return "all" if len(self._selected) >= self.rowCount() else "some"


# ---------- the open folder ----------


def _value(name: str, default: Any = "") -> Callable[[FolderView], Any]:
    """A property getter: the open folder's value of `name`, `default` when it has none."""
    return lambda view: view._values.get(name, default)


class FolderView(QObject):
    """The open folder (R2.9): where it is, its count, the mode, going up and back, a folder of
    songs' strip, the selection's count, and Play. `play` asks for songs to be played, by their
    ids, with the name of where they're from (R7.1)."""

    changed = Signal()  # the folder, its counts and strip
    modeChanged = Signal()
    selectionChanged = Signal()
    opened = Signal()  # another folder opened: its search is gone
    play = Signal(object, str)  # songs to play, by id, the first first, and where they're from

    def __init__(
        self,
        read: Callable[[], sqlite3.Connection],
        remembered: Remembered | None = None,
        parent: QObject | None = None,
        searcher: Searcher | None = None,
        platform: str = sys.platform,
    ) -> None:
        super().__init__(parent)
        self._read = read
        self._remembered = remembered if remembered is not None else Remembered()
        self._model = FolderModel(read, self, searcher)
        self._model.countChanged.connect(self.changed)
        self._model.selectionChanged.connect(self.selectionChanged)
        self._platform = platform
        self._history: list[str] = []
        self._values: dict[str, Any] = {}
        self._mode = (
            self._remembered.mode
            if self._remembered.mode in {m["mode"] for m in MODES}
            else DEFAULT_MODE
        )
        self._model.open(self._there(self._remembered.folder))
        self._load()

    def _there(self, folder: str) -> str:
        """`folder` if it has a row, else the nearest folder above it that does ("" at last)."""
        c = self._read()
        for path in [folder, *index_folders.ancestors(folder)]:
            if not path or c.execute("SELECT 1 FROM folder WHERE path = ?", (path,)).fetchone():
                return path
        return ""

    def _load(self) -> None:
        """Reads the open folder's row and, for a folder of songs, its strip."""
        c = self._read()
        path = self._model.folder()
        r = c.execute(
            "SELECT folders, songs, songs_beneath, image, thumb, mosaic FROM folder WHERE path = ?",
            (path,),
        ).fetchone()
        folders, songs, beneath, image, thumb, mosaic = r if r else (0, 0, 0, None, None, None)
        values: dict[str, Any] = {
            "count": folder_line(folders, beneath) if r else "",
            "folders": folders,
            "songs": songs,
            "cover": picture_url(thumb, mosaic),
        }
        if songs and not folders:
            size, embedded = c.execute(
                "SELECT coalesce(SUM(size), 0), coalesce(SUM(has_cover), 0) FROM song"
                " WHERE folder = ?",
                (path,),
            ).fetchone()
            groups = c.execute(
                "SELECT kind, sample_rate, CAST(avg(bitrate) AS INTEGER), COUNT(*) FROM song"
                " WHERE folder = ? GROUP BY kind, sample_rate",
                (path,),
            ).fetchall()
            values["kicker"] = " · ".join(
                p
                for p in ("Folder", plural(songs, "song"), size_text(size), format_text(groups))
                if p
            )
            values["artLine"] = art_line(image, embedded, songs)
            states = c.execute("SELECT path_state FROM song WHERE folder = ?", (path,)).fetchall()
            matched = match_chip([r[0] for r in states])
            values["chips"] = [art_chip(image, embedded, songs)] + ([matched] if matched else [])
            values["pathLine"] = path_line(self._differing(c, path))
        self._values = values
        self.changed.emit()

    def _differing(
        self, c: sqlite3.Connection, folder: str
    ) -> list[tuple[tuple[patterns.Difference, ...], dict[str, str]]]:
        """A folder's songs that differ from their path (R3.9): how, and their tags' values."""
        out = []
        diffs = {
            str(p): index_folders.diffs_of(d)
            for p, d in c.execute(
                "SELECT path, path_diff FROM song WHERE folder = ? AND path_diff IS NOT NULL",
                (folder,),
            )
        }
        for _id, path, tags in index_folders.tags_in(c, folder):
            if diffs.get(path):
                out.append((diffs[path], {d.field: text_of(d.field, tags) for d in diffs[path]}))
        return out

    # ---------- going between folders (R2.9.1) ----------

    @Slot(str)
    def open(self, path: str) -> None:
        """Opens a folder (a path under the root, "" for the root), remembering the one it came
        from for back."""
        path = self._there(path)
        if path != self._model.folder():
            self._history.append(self._model.folder())
        self._show(path)

    def _show(self, path: str) -> None:
        self._model.open(path)
        self._remembered.folder = path
        self._load()
        self.opened.emit()

    @Slot()
    def up(self) -> None:
        """The folder above the open one; nothing at the root."""
        above = index_folders.parent_of(self._model.folder())
        if above is not None:
            self.open(above)

    @Slot()
    def back(self) -> None:
        """The folder opened before this one; nothing when there was none."""
        if self._history:
            self._show(self._there(self._history.pop()))

    def reload(self) -> None:
        """After a scan: the rows read again where they are; a folder gone shows the nearest one
        above it still there."""
        there = self._there(self._model.folder())
        if there != self._model.folder():
            self._show(there)
            return
        self._model.refresh()
        self._load()

    # ---------- acting on rows (R2.9.2, R2.9.6) ----------

    @Slot(int)
    def activate(self, n: int) -> None:
        """Double-click or Enter on row n: a folder opens, a file plays, the files after it in
        the list its queue (R7.1)."""
        row = self._model.row(n)
        if row is None:
            return
        if row["kind"] == "folder":
            self.open(row["path"])
        else:
            self._play(*self._model.queue_from(n))

    @Slot(int)
    def playRow(self, n: int) -> None:  # noqa: N802
        """A cover's play button: a folder's songs from its first, or the file and those after
        it (R7.1)."""
        self._play(*self._model.queue_from(n))

    @Slot()
    def playSelection(self) -> None:  # noqa: N802
        """The selection bar's Play: the songs it stands for, in the list's order, from the first
        (R2.9.6, R7.1)."""
        self._play(self._model.selected_songs(), self._model.source())

    def _play(self, songs: list[int], source: str) -> None:
        if songs:
            self.play.emit(songs, source)

    @Slot(str)
    def setMode(self, mode: str) -> None:  # noqa: N802
        """One of the four modes (R2.9.4), the same for every folder."""
        if mode not in {m["mode"] for m in MODES}:
            raise ValueError(f"no such mode: {mode}")
        self._mode = self._remembered.mode = mode
        self.modeChanged.emit()

    @Slot(list, float, float, float, result=int)
    def foldCrumbs(self, widths: list[float], room: float, ellipsis: float, gap: float) -> int:  # noqa: N802
        return fold_crumbs([float(w) for w in widths], room, ellipsis, gap)

    def select_paths(self, paths: Sequence[str]) -> None:
        """Selects the rows at these paths (the tour's steps)."""
        wanted = set(paths)
        rows = [n for n in range(self._model.rowCount()) if (self._model.row(n) or {}).get(
            "path") in wanted]  # fmt: skip
        self._model.selectRows(rows, False)

    # ---------- what QML reads ----------

    def _get_model(self) -> FolderModel:
        return self._model

    def _get_path(self) -> str:
        return self._model.folder()

    def _get_title(self) -> str:
        path = self._model.folder()
        return index_folders.name_of(path) if path else ROOT_TITLE

    def _get_crumbs(self) -> list[dict[str, str]]:
        """The open folder's path under the root, a crumb per folder (R2.9.1); none at the root,
        whose name is never shown."""
        path = self._model.folder()
        if not path:
            return []
        parts = path.split("/")
        return [{"name": p, "path": "/".join(parts[: i + 1])} for i, p in enumerate(parts)]

    def _get_count(self) -> str:
        m = self._model
        if m.filtered():
            rows = m.folder_rows()
            return found_line(rows, m.rowCount() - rows)
        return str(self._values.get("count", ""))

    def _get_songs_mode(self) -> bool:
        """A folder of songs (R2.9.7): audio files and no subfolders, and no search."""
        return (
            bool(self._values.get("songs"))
            and not self._values.get("folders")
            and not (self._model.searching())
        )

    def _get_files_title(self) -> str:
        """The heading over the files in the image modes (R2.9.4): 4 songs in this folder."""
        m = self._model
        files = m.rowCount() - m.folder_rows()
        if not files:
            return ""
        if m.filtered():
            return plural(files, "song")
        return f"{plural(files, 'song')} in this folder"

    def _get_third_label(self) -> str:
        return "FOLDER" if self._model.searching() else "ALBUM"

    def _get_selection_text(self) -> str:
        folders, files = self._model.selected()
        if not folders and not files:
            return ""
        songs = index_folders.count_songs(self._read(), folders, files)
        return selection_text(len(folders), len(files), songs)

    def _get_selection_count(self) -> int:
        return len(self._model._selected)

    def _get_selection_state(self) -> str:
        return self._model.selection_state()

    def _get_mode(self) -> str:
        return self._mode

    def _get_up_keys(self) -> list[str]:
        """Going up (R2.9.1): Alt+↑, ⌘↑ on macOS (Qt's Ctrl), and Backspace."""
        return ["Ctrl+Up" if self._platform == "darwin" else "Alt+Up", "Backspace"]

    def _get_can_back(self) -> bool:
        return bool(self._history)

    def _get_folder_rows(self) -> int:
        return self._model.folder_rows()

    model = QtProperty(QObject, _get_model, constant=True)
    path = QtProperty(str, _get_path, notify=changed)
    title = QtProperty(str, _get_title, notify=changed)
    crumbs = QtProperty(list, _get_crumbs, notify=changed)
    count = QtProperty(str, _get_count, notify=changed)  # 3 folders · 34 songs
    songsMode = QtProperty(bool, _get_songs_mode, notify=changed)
    filesTitle = QtProperty(str, _get_files_title, notify=changed)
    thirdLabel = QtProperty(str, _get_third_label, notify=changed)
    folderRows = QtProperty(int, _get_folder_rows, notify=changed)
    cover = QtProperty(str, _value("cover"), notify=changed)
    kicker = QtProperty(str, _value("kicker"), notify=changed)  # Folder · 9 songs · 312 MB · FLAC
    artLine = QtProperty(str, _value("artLine"), notify=changed)
    chips = QtProperty(list, _value("chips", []), notify=changed)
    pathLine = QtProperty(str, _value("pathLine"), notify=changed)  # R2.9.7: how files differ
    stripButtons = QtProperty(list, lambda self: STRIP, constant=True)
    laterActions = QtProperty(
        list,
        lambda self: selection_actions(self._model.selected_album() >= 0),
        notify=selectionChanged,
    )
    selectedAlbum = QtProperty(
        int, lambda self: self._model.selected_album(), notify=selectionChanged
    )  # -1: none
    selectionText = QtProperty(str, _get_selection_text, notify=selectionChanged)
    selectionCount = QtProperty(int, _get_selection_count, notify=selectionChanged)
    selectionState = QtProperty(str, _get_selection_state, notify=selectionChanged)
    mode = QtProperty(str, _get_mode, notify=modeChanged)
    upKeys = QtProperty(list, _get_up_keys, constant=True)
    canBack = QtProperty(bool, _get_can_back, notify=changed)
