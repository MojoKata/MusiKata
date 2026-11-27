"""The change history and Undo (R4.9, R4.9.1, A3.5): every save is one entry, a JSON file in the
root's `.musikata/history/` named by its time and the computer that saved it
(`20261125T204512123Z-<computer id>.json`), so entries from several computers never collide; it
is written once, to a temporary file moved into place (A2.8), and never rewritten. For each file
written it holds the file's path under the root and its audio hash (A2.3, as A2.8 names songs),
the old value of each field that changed (`fields`) and the value written (`new`), and, when the
cover changed, the old cover by hash (`cover`, null: there was none) and the new one's
(`new_cover`). An old cover is kept once in `history/images/<sha256>`, however many entries name
it (`history-entry.v1.schema.json`, A2.10).

Recording is `Recording`, the tags.Recorder every save's batch is given (tags.batch): it is told
each file as it is written, keeping its old cover then, and writes the entry at the end.

Undo is another save: `plan` finds each file the entry touched where it is now (by its path, else
by its audio hash: a file moved, A2.8) and what undoing it would lose: a field whose value now is
neither what the entry wrote nor what it puts back has changed since, by MusiKata or anything else
(R4.9.1). The caller asks the user about those (`Plan.changed`), and `undo` writes the old values
through A3.4 in a batch of its own, recorded as an entry that `undoes` the first, so it can be
undone in turn (redone). A file gone, or one that can't be read, is listed with why, as a save's
failures are (R4.7).

The index lists the entries (A2.1's change and change_file) for the Change history view:
`changes` lists the folder and reads the entries it doesn't have yet, another computer's
included, and `sync` puts them in the index and takes out those whose file has gone. An entry is
data from outside (another computer, another version, a sync tool in the middle of copying it):
one cut short, not JSON, of the wrong shapes or of a newer format is logged and skipped
(`Broken`), and read again the next time the folder changes; a field it can't use is left out.

Entries past their age (R4.9's 90 days, R13.3's `history_days`) are removed at start by whichever
computer starts first (`expire`), and the old covers no entry names any more with them
(`prune`), once untouched for a day: an entry being written on another computer names its covers
only when it is done."""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import logging
import os
import re
import sqlite3
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from . import db, rootfiles, scanner
from .clock import Clock
from .tags import Batch, Failed, Job, Outcome, Picture, Tags, WriteError, Written, compose
from .tags import pictures as read_pictures
from .tags import read as read_tags
from .tags.batch import Progress

log = logging.getLogger(__name__)

FORMAT = 1  # an entry's format (A2.10)
FOLDER = "history"  # in the root's .musikata (A3.5)
IMAGES = "images"  # the old covers, in the history folder, by hash
DAYS = 90  # R4.9: how long an entry is kept, unless the root's settings say otherwise (R13.3)
GRACE = 86400.0  # seconds an old cover no entry names is kept: an entry names it at its end
ACTION = "edit-tags"  # a save of the Edit tags panel (R4.2), the default
UNDO = "undo"
HASH = re.compile(r"[0-9a-f]{64}")
NAME = re.compile(r"(\d{8}T\d{9}Z)-([^/\\]+)\.json")
TMP = ".tmp"
# compose.FIELDS by the names an entry gives them, R4.1's ("genre"), and back
ENTRY_NAMES = {f: "genre" if f == "genres" else f for f in compose.FIELDS if f != "cover"}
FIELD_OF = {v: k for k, v in ENTRY_NAMES.items()}


# ---------- an entry, as plain data ----------


@dataclass(frozen=True)
class FileChange:
    """A file a save wrote: its path under the root (with /), its audio hash (None: not known),
    the old value of each field that changed and the value written (`old`, `new`, by
    compose.FIELDS' names, as `value_of` gives them; a field `new` lacks is one an older entry
    didn't say), and whether the cover changed (`cover`), with the old cover's hash and the new
    one's (None: none)."""

    path: str
    hash: str | None
    old: Mapping[str, object]
    new: Mapping[str, object] = field(default_factory=dict)
    cover: bool = False
    old_cover: str | None = None
    new_cover: str | None = None

    def fields(self) -> list[str]:
        """The fields it changed, in compose.FIELDS' order, the cover among them."""
        return [f for f in compose.FIELDS if f in self.old or (f == "cover" and self.cover)]


@dataclass(frozen=True)
class Entry:
    """One save (R4.9): its file's name, when and on which computer (its id) it was saved, what
    it was (`action`, and `description` in words), the entry it undoes (by name; None), the files
    it wrote, and what of its file couldn't be used (`problems`, for the log)."""

    name: str
    time: datetime
    computer: str
    action: str
    description: str
    files: tuple[FileChange, ...]
    undoes: str | None = None
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class Broken:
    """An entry's file that couldn't be used at all, and why."""

    name: str
    why: str


def value_of(tags: Tags, name: str) -> object:
    """Field `name` (compose.FIELDS') of a file's tags as an entry keeps it: text or None, a number
    or None, the year as its full date when the file has one, else its year (None: none), genres
    a list, compilation true or false, the rating 0 to 5 (0: none)."""
    if name == "year":
        return tags.date or tags.year
    if name == "genres":
        return list(tags.genres)
    if name == "rating":
        return tags.rating or 0
    return getattr(tags, name)


def same(name: str, a: object, b: object) -> bool:
    """Whether two values of field `name` are one as a file holds it: `2003` and `"2003"`, a
    text and the same text with spaces around it, no genres and none."""
    if a == b:
        return True
    try:
        return compose.normalize({name: a}) == compose.normalize({name: b})
    except ValueError:
        return False


def image_hash(data: bytes) -> str:
    """The name an old cover is kept under in history/images: the SHA-256 of its bytes."""
    return hashlib.sha256(data).hexdigest()


def name_for(when: datetime, computer: str) -> str:
    """An entry's file name: its time, UTC to the millisecond, and its computer's id (A3.5)."""
    t = when.astimezone(UTC)
    return f"{t:%Y%m%dT%H%M%S}{t.microsecond // 1000:03d}Z-{computer}.json"


def time_of_name(name: str) -> datetime | None:
    """When the entry named `name` was saved, from its name; None when it isn't an entry's."""
    found = NAME.fullmatch(name)
    if found is None:
        return None
    stamp = found.group(1)
    try:
        when = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    return when + timedelta(milliseconds=int(stamp[15:18]))


def time_text(when: datetime) -> str:
    """`when` as A2.10 writes a time: UTC, ISO 8601, to the second."""
    return rootfiles.time_text(when)


def _utc(value: object) -> datetime | None:
    """A time as A2.10 writes it, in UTC; None when `value` isn't a time with its zone."""
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    return when.astimezone(UTC) if when.tzinfo is not None else None


def under_root(path: object) -> str | None:
    """`path`, as an entry names a file, when it is a path under the root (with /, none of its
    parts empty, `.` or `..`, not whole); None when it isn't, so an entry can never name a file
    outside the root."""
    if not isinstance(path, str) or not path or "\\" in path or "\0" in path:
        return None
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts) or re.match(r"[A-Za-z]:", path):
        return None
    return path


def document(entry: Entry) -> dict[str, object]:
    """An entry as its file holds it (`history-entry.v1.schema.json`)."""
    files: list[dict[str, object]] = []
    for f in entry.files:
        out: dict[str, object] = {"path": f.path}
        if f.hash is not None:
            out["hash"] = f.hash
        out["fields"] = {ENTRY_NAMES[k]: v for k, v in f.old.items()}
        out["new"] = {ENTRY_NAMES[k]: v for k, v in f.new.items()}
        if f.cover:
            out["cover"], out["new_cover"] = f.old_cover, f.new_cover
        files.append(out)
    doc: dict[str, object] = {
        "format": FORMAT,
        "time": time_text(entry.time),
        "computer": entry.computer,
        "action": entry.action,
        "description": entry.description,
    }
    if entry.undoes is not None:
        doc["undoes"] = entry.undoes
    doc["files"] = files
    return doc


def _values(value: object, where: str, problems: list[str]) -> dict[str, object] | None:
    """An entry's `fields` or `new`: each field it knows with a value it can use, by
    compose.FIELDS' names; None when it isn't a group."""
    if value is None:
        return None
    if not isinstance(value, dict):
        problems.append(f"{where} isn't a group: {value!r}; left out")
        return None
    out: dict[str, object] = {}
    for key, v in value.items():
        name = FIELD_OF.get(key) if isinstance(key, str) else None
        if name is None:
            problems.append(f"{where}: {key!r} isn't a field this MusiKata knows; left out")
            continue
        try:
            compose.normalize({name: v})
        except ValueError:
            problems.append(f"{where}: {key} isn't a value it can hold: {v!r}; left out")
            continue
        out[name] = v
    return out


def _cover(value: object, where: str, problems: list[str]) -> tuple[bool, str | None]:
    """A cover's hash (lower case), or None for none: (whether it can be used, the hash)."""
    if value is None:
        return True, None
    if isinstance(value, str) and HASH.fullmatch(value.lower()):
        return True, value.lower()
    problems.append(f"{where} isn't a cover's hash: {value!r}; the cover left out")
    return False, None


def _file(value: object, problems: list[str]) -> FileChange | None:
    """A file of `files`; None, with the problem, when it can't be used."""
    if not isinstance(value, dict):
        problems.append(f"a file isn't an object: {value!r}; left out")
        return None
    path = under_root(value.get("path"))
    if path is None:
        problems.append(f"a file's path isn't a path under the root: {value.get('path')!r}")
        return None
    hash_ = value.get("hash")
    if isinstance(hash_, str) and HASH.fullmatch(hash_.lower()):
        hash_ = hash_.lower()
    else:
        if hash_ is not None:
            problems.append(f"{path}: its hash isn't an audio hash: {hash_!r}; found by path only")
        hash_ = None
    old = _values(value.get("fields"), f"{path}: fields", problems) or {}
    new = _values(value.get("new"), f"{path}: new", problems) or {}
    new = {k: v for k, v in new.items() if k in old}
    cover = "cover" in value
    old_cover = new_cover = None
    if cover:
        cover, old_cover = _cover(value["cover"], f"{path}: cover", problems)
        if cover and "new_cover" in value:
            usable, new_cover = _cover(value["new_cover"], f"{path}: new_cover", problems)
            if not usable:
                new_cover = None
    if not old and not cover:
        problems.append(f"{path}: no field it can put back; left out")
        return None
    return FileChange(path, hash_, old, new, cover, old_cover, new_cover)


def parse(name: str, text: str) -> Entry | Broken:
    """The entry in `text`, the content of the entry file `name`, whatever was written there: one
    that can't be used at all is Broken, with why; a file or a field of it that can't be used is
    left out, named in `problems`. Its time and computer, when it doesn't say them, are its
    name's."""
    named = NAME.fullmatch(name)
    if named is None:
        return Broken(name, "it isn't named as an entry is (<time>-<computer id>.json)")
    try:
        data = json.loads(text.removeprefix("﻿"))
    except ValueError as e:
        return Broken(name, f"it isn't JSON ({e}): cut short by a sync in progress, or damaged")
    if not isinstance(data, dict):
        return Broken(name, "it isn't a JSON object")
    problems: list[str] = []
    fmt = data.get("format")
    if isinstance(fmt, int) and not isinstance(fmt, bool):
        if fmt > FORMAT:
            return Broken(name, f"it is format {fmt}, from a newer MusiKata: update to read it")
    else:
        problems.append(f"format isn't a number: {fmt!r}; read as format {FORMAT}")
    when = _utc(data.get("time"))
    at = when if when is not None else time_of_name(name)
    if at is None:
        return Broken(name, f"time isn't a time: {data.get('time')!r}, nor is its name's")
    if when is None:
        problems.append(f"time isn't a UTC time: {data.get('time')!r}; its name's")
    computer = data.get("computer")
    if not isinstance(computer, str) or not computer:
        problems.append(f"computer isn't an id: {computer!r}; its name's")
        computer = named.group(2)
    action = data.get("action")
    if not isinstance(action, str) or not action:
        problems.append(f"action isn't text: {action!r}; {ACTION}")
        action = ACTION
    description = data.get("description", "")
    if not isinstance(description, str):
        problems.append(f"description isn't text: {description!r}; none")
        description = ""
    undoes = data.get("undoes")
    if undoes is not None and not (isinstance(undoes, str) and NAME.fullmatch(undoes)):
        problems.append(f"undoes isn't an entry's name: {undoes!r}; left out")
        undoes = None
    listed = data.get("files")
    if not isinstance(listed, list):
        return Broken(name, f"files isn't a list: {listed!r}")
    files: list[FileChange] = []
    seen: set[str] = set()
    for value in listed:
        f = _file(value, problems)
        if f is None:
            continue
        if f.path in seen:
            problems.append(f"{f.path} is named twice: the first kept")
            continue
        seen.add(f.path)
        files.append(f)
    if not files:
        return Broken(name, "it names no file it can put back")
    return Entry(name, at, computer, action, description, tuple(files), undoes, tuple(problems))


# ---------- the history folder ----------


def folder_of(root: str) -> str:
    """The root's history folder, `.musikata/history` (A3.5)."""
    return os.path.join(rootfiles.folder_of(root), FOLDER)


def image_path(history: str, digest: str) -> str:
    """Where the old cover `digest` is kept."""
    return os.path.join(history, IMAGES, digest)


def _write(path: str, data: bytes) -> None:
    """`data` at `path`, through a temporary file beside it moved into place (A2.8)."""
    tmp = path + TMP
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def keep_image(history: str, data: bytes) -> str:
    """An old cover kept in history/images, once however many entries name it (touched again
    when it is there, so `prune` doesn't take it); its hash. Raises OSError when it can't be."""
    digest = image_hash(data)
    path = image_path(history, digest)
    if os.path.exists(path):
        os.utime(path)
        return digest
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _write(path, data)
    return digest


def load_image(history: str, digest: str) -> bytes | None:
    """The old cover `digest`; None when it isn't kept any more, or isn't the cover it names."""
    try:
        with open(image_path(history, digest), "rb") as f:
            data = f.read()
    except OSError as e:
        log.warning("the old cover %s couldn't be read: %s", digest, e)
        return None
    if image_hash(data) != digest:
        log.warning("the old cover %s isn't the cover it is named for: not used", digest)
        return None
    return data


def save_entry(history: str, entry: Entry) -> Entry:
    """Writes `entry` into the history folder, once (A3.5); the entry as written, its name moved
    a millisecond on while one of this computer's has its name. Raises OSError when it can't."""
    os.makedirs(history, exist_ok=True)
    when = entry.time
    while os.path.exists(os.path.join(history, name_for(when, entry.computer))):
        when += timedelta(milliseconds=1)
    written = Entry(
        name_for(when, entry.computer), when, entry.computer, entry.action, entry.description,
        entry.files, entry.undoes,
    )  # fmt: skip
    text = json.dumps(document(written), indent=2, ensure_ascii=False) + "\n"
    _write(os.path.join(history, written.name), text.encode("utf-8"))
    return written


def names(history: str) -> list[str]:
    """The entries' file names in the history folder, in their order (oldest first); a name not
    an entry's (a sync tool's copy, a temporary file) is passed by. None there: none."""
    try:
        found = [e.name for e in os.scandir(history) if e.is_file()]
    except FileNotFoundError:
        return []
    except OSError as e:
        log.warning("couldn't list %s: %s", history, e)
        return []
    return sorted(n for n in found if NAME.fullmatch(n))


def read(history: str, name: str) -> Entry | Broken:
    """The entry `name` in the history folder (`parse`), each problem logged."""
    path = os.path.join(history, name)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        found: Entry | Broken = Broken(name, f"it couldn't be read ({e})")
    else:
        found = parse(name, text)
    if isinstance(found, Broken):
        log.warning("%s: %s; skipped", path, found.why)
    else:
        for problem in found.problems:
            log.warning("%s: %s", path, problem)
    return found


def changes(history: str, known: Collection[str]) -> tuple[list[str], list[Entry]]:
    """The entries in the history folder: every name there, and those of them not `known` (the
    index's), read; one that can't be used is logged and left out, to be read again next time."""
    present = names(history)
    read_now = [read(history, n) for n in present if n not in known]
    return present, [e for e in read_now if isinstance(e, Entry)]


def expire(history: str, now: datetime, days: int) -> list[str]:
    """Removes the entries saved more than `days` days before `now` (R4.9), by their names'
    times; the names removed. One that can't be removed is logged and kept."""
    cutoff = now - timedelta(days=days)
    gone = []
    for name in names(history):
        when = time_of_name(name)
        if when is None or when >= cutoff:
            continue
        try:
            os.remove(os.path.join(history, name))
        except FileNotFoundError:  # another computer took it first
            continue
        except OSError as e:
            log.warning("couldn't remove %s, an entry past its age: %s", name, e)
            continue
        gone.append(name)
    if gone:
        log.info("removed %d entries of the change history older than %d days", len(gone), days)
    return gone


def prune(history: str, named: Collection[str], now: float, grace: float = GRACE) -> list[str]:
    """Removes the old covers in history/images no entry names any more (`named`, their hashes),
    once untouched for `grace` seconds before `now`, a time (A3.5); their hashes."""
    folder = os.path.join(history, IMAGES)
    try:
        found = list(os.scandir(folder))
    except OSError:
        return []
    gone = []
    for e in found:
        if e.name in named or not HASH.fullmatch(e.name):
            continue
        try:
            if e.stat().st_mtime >= now - grace:
                continue
            os.remove(e.path)
        except OSError as err:
            log.warning("couldn't remove %s, a cover no entry names: %s", e.path, err)
            continue
        gone.append(e.name)
    if gone:
        log.info("removed %d old covers no entry of the change history names", len(gone))
    return gone


# ---------- recording a save ----------


class Recording:
    """Keeps one save in the change history (tags.Recorder): each file written, as it is
    (`saved`), its old cover kept at once, and the entry written at the end (`done`), once, by
    `computer` (its id, made when it has none: settings.computer_id), at `clock`'s time. `undoes`:
    the entry this save undoes. Nothing is written when no file changed, or the computer has no
    id; a failure to write is logged, and the save stands without its entry."""

    def __init__(
        self,
        root: str,
        computer: Callable[[], str | None],
        clock: Clock,
        undoes: str | None = None,
    ) -> None:
        self._root, self._computer, self._clock, self._undoes = root, computer, clock, undoes
        self._history = folder_of(root)
        self.files: list[FileChange] = []

    def saved(self, written: Written) -> None:
        """A file written (safe.Written): what it changed kept, its old cover in images/."""
        if not written.changed or written.before is None:
            return
        path = scanner.path_under(self._root, written.path)
        if path is None:
            log.warning(
                "%s isn't under %s: the change history passes it by", written.path, self._root
            )
            return
        fields = [f for f in written.changed if f != "cover"]
        old = {f: value_of(written.before, f) for f in fields}
        new = {f: value_of(written.tags, f) for f in fields}
        cover = "cover" in written.changed
        old_cover = new_cover = None
        if cover:
            if written.cover_before is not None:
                try:
                    old_cover = keep_image(self._history, written.cover_before.data)
                except OSError as e:
                    old_cover = image_hash(written.cover_before.data)
                    log.warning("couldn't keep the old cover of %s: %s", path, e)
            if written.cover_after is not None:
                new_cover = image_hash(written.cover_after.data)
        self.files.append(
            FileChange(path, written.audio_hash, old, new, cover, old_cover, new_cover)
        )

    def done(self, action: str, description: str) -> str | None:
        """The entry written for the files saved; its name, None when none was."""
        if not self.files:
            return None
        computer = self._computer()
        if not computer:
            log.warning("this computer has no id: the save isn't kept in the change history")
            return None
        entry = Entry(
            "", self._clock.now(), computer, action, description, tuple(self.files), self._undoes
        )
        try:
            written = save_entry(self._history, entry)
        except OSError as e:
            log.warning("couldn't keep the save in the change history (%s): %s", self._history, e)
            return None
        log.info("kept %s in the change history: %d files", written.name, len(self.files))
        return written.name


# ---------- Undo ----------


@dataclass(frozen=True)
class Lost:
    """A field of a file that changed since the entry (R4.9.1): its value now, which undoing would
    lose, and the value undoing puts back."""

    field: str
    now: object
    back: object


@dataclass(frozen=True)
class FileUndo:
    """A file of an entry to undo: what the entry changed in it, where it is now (under the root;
    None: gone), what undoing would lose (R4.9.1), and why it can't be undone ("": it can)."""

    change: FileChange
    path: str | None
    lost: tuple[Lost, ...] = ()
    why: str = ""


@dataclass(frozen=True)
class Plan:
    """An entry to undo, or the files of it chosen, each where it is now (`FileUndo`)."""

    entry: Entry
    files: tuple[FileUndo, ...]

    @property
    def changed(self) -> list[FileUndo]:
        """The files changed since the entry, which undoing would overwrite (R4.9.1)."""
        return [f for f in self.files if f.lost and not f.why]

    @property
    def failed(self) -> list[FileUndo]:
        """The files that can't be undone, each with why."""
        return [f for f in self.files if f.why]


@dataclass(frozen=True)
class Current:
    """A file as it is now: its tags, and its cover's hash when asked for (None: none)."""

    tags: Tags
    cover: str | None = None


def current(path: str, cover: bool) -> Current:
    """The file at `path` as it is now (tags.read, and its cover's hash when `cover`). Raises
    TagReadError or OSError when it can't be read."""
    tags, info = read_tags(path)
    if not cover:
        return Current(tags)
    picture = compose.cover_of(read_pictures(path), info.kind not in ("aac", "alac"))
    return Current(tags, image_hash(picture.data) if picture is not None else None)


def looking(
    kept: Callable[[str], int | None], look: Callable[[str, bool], Current] = current
) -> Callable[[str, bool], Current]:
    """`look` for a root whose songs' ratings may be kept beside them (R10.3): a file as it is
    now, its rating the one `kept` says ratings.json keeps for it (ratings.Writing.kept; None:
    its file keeps it)."""

    def now(path: str, cover: bool) -> Current:
        found = look(path, cover)
        rating = kept(path)
        if rating is None:
            return found
        return Current(dataclasses.replace(found.tags, rating=rating), found.cover)

    return now


def lost(change: FileChange, now: Current) -> tuple[Lost, ...]:
    """What undoing `change` would lose of the file as it is `now` (R4.9.1): each field whose
    value now is neither what the entry wrote nor what undoing puts back (a field an older entry
    didn't say it wrote: any value but the old one), and the cover likewise."""
    out: list[Lost] = []
    for name, back in change.old.items():
        value = value_of(now.tags, name)
        if same(name, value, back):
            continue
        if name in change.new and same(name, value, change.new[name]):
            continue
        out.append(Lost(name, value, back))
    if change.cover and now.cover not in (change.old_cover, change.new_cover):
        out.append(Lost("cover", now.cover, change.old_cover))
    return tuple(out)


def plan(
    entry: Entry,
    root: str,
    find: Callable[[str], Sequence[str]],
    which: Collection[int] | None = None,
    look: Callable[[str, bool], Current] = current,
) -> Plan:
    """What undoing `entry` would do (R4.9, R4.9.1): its files, or those at the places `which`
    names, each found by its path, else by its audio hash (`find`, the index's songs with that
    hash, the first still there: a file moved, A2.8), with what undoing it would lose (`lost`,
    read by `look`); a file found by neither, or that can't be read, has why."""
    out = []
    for n, change in enumerate(entry.files):
        if which is not None and n not in which:
            continue
        path: str | None = change.path
        if not os.path.exists(scanner.full_path(root, change.path)):
            found = find(change.hash) if change.hash is not None else ()
            path = next((p for p in found if os.path.exists(scanner.full_path(root, p))), None)
        if path is None:
            out.append(FileUndo(change, None, why="it isn't there any more"))
            continue
        try:
            now = look(scanner.full_path(root, path), change.cover)
        except Exception as e:  # noqa: BLE001  (a file that can't be read is listed, not undone)
            log.warning("couldn't read %s to undo it: %s", path, e)
            out.append(FileUndo(change, path, why=f"it can't be read: {e}"))
            continue
        out.append(FileUndo(change, path, lost(change, now)))
    return Plan(entry, tuple(out))


@dataclass(frozen=True)
class KeptCover:
    """A cover to put back, by its hash in history/images, loaded only as its file is written."""

    hash: str


def jobs(plan_: Plan, root: str, overwrite: bool) -> list[Job]:
    """The files to write to undo `plan_`: each that can be, with its old values; those changed
    since (R4.9.1) only when `overwrite`, the user's answer."""
    out = []
    for f in plan_.files:
        if f.why or f.path is None or (f.lost and not overwrite):
            continue
        changes: dict[str, object] = dict(f.change.old)
        if f.change.cover:
            old = f.change.old_cover
            changes["cover"] = KeptCover(old) if old is not None else None
        out.append(Job(scanner.full_path(root, f.path), changes))
    return out


def with_covers(write: Callable[[Job], Written], history: str) -> Callable[[Job], Written]:
    """`write` (safe.save, as a batch's writer), with a cover kept in history/images loaded as
    its file is written; a cover no longer kept fails that file, with why."""

    def writer(job: Job) -> Written:
        cover = job.changes.get("cover")
        if isinstance(cover, KeptCover):
            data = load_image(history, cover.hash)
            if data is None:
                raise WriteError(job.path, "its old cover isn't in the change history any more")
            picture = Picture(compose.FRONT, compose.image_mime(data), data)
            job = Job(job.path, {**job.changes, "cover": picture})
        return write(job)

    return writer


def description_of(entry: Entry, files: int) -> str:
    """What undoing `entry` is, for the list: "Undo: <what it was>"."""
    what = entry.description or ("a save" if entry.action != UNDO else "an undo")
    some = "" if files == len(entry.files) else f" ({files} of {len(entry.files)} files)"
    return f"Undo: {what}{some}"


def undo(
    plan_: Plan,
    root: str,
    overwrite: bool,
    write: Callable[[Job], Written],
    record: Recording | None,
    progress: Progress | None = None,
) -> Outcome[Written]:
    """Undoes `plan_` (R4.9): the old values written with `write` (safe.save, A3.4) in a batch of
    its own, recorded by `record` (a Recording that `undoes` the entry; None: the history is off)
    as an entry, so it can be undone in turn. Files changed since are written only when
    `overwrite` (R4.9.1), else passed by; those that can't be undone are listed as failed, with
    why, as a save's are (R4.7)."""
    todo = jobs(plan_, root, overwrite)
    batch = Batch(
        todo,
        with_covers(write, folder_of(root)),
        progress,
        record=record,
        action=UNDO,
        description=description_of(plan_.entry, len(todo)),
    )
    out = batch.run()
    for f in plan_.failed:
        out.failed.append(Failed(Job(scanner.full_path(root, f.path or f.change.path), {}), f.why))
    return out


# ---------- in the index (A2.1): each function runs in the writer's transaction ----------


def known(c: sqlite3.Connection) -> set[str]:
    """The entries the index lists, by name."""
    return {n for (n,) in c.execute("SELECT name FROM change")}


def sync(c: sqlite3.Connection, present: Iterable[str], entries: Sequence[Entry]) -> int:
    """The index's entries made the history folder's: those whose file has gone (`present`: the
    names there now) taken out, `entries` (those read anew) put in. The number of rows changed."""
    there = set(present)
    gone = [n for n in known(c) if n not in there]
    c.executemany("DELETE FROM change WHERE name = ?", [(n,) for n in gone])
    added = 0
    for e in entries:
        cur = c.execute(
            "INSERT OR IGNORE INTO change (name, time, computer, action, description, undoes)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (e.name, time_text(e.time), e.computer, e.action, e.description, e.undoes),
        )
        if not cur.rowcount:
            continue
        added += 1
        c.executemany(
            "INSERT INTO change_file (change_id, position, path, hash, fields, cover)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (cur.lastrowid, n, f.path, f.hash, ",".join(f.fields()), f.old_cover)
                for n, f in enumerate(e.files)
            ],
        )
    return len(gone) + added


def covers(c: sqlite3.Connection) -> set[str]:
    """The old covers the index's entries name, by hash."""
    return {h for (h,) in c.execute("SELECT DISTINCT cover FROM change_file") if h}


def finder(c: sqlite3.Connection) -> Callable[[str], list[str]]:
    """The songs' paths in the index on `c` with an audio hash, by path, for `plan`."""

    def find(digest: str) -> list[str]:
        found = c.execute("SELECT path FROM song WHERE audio_hash = ? ORDER BY path", (digest,))
        return [str(p) for (p,) in found]

    return find


@dataclass(frozen=True)
class Row:
    """An entry as the index lists it, for the Change history view: its name, time, computer's
    id, what it was, the entry it undoes, and its files (path and the fields it changed)."""

    name: str
    time: datetime
    computer: str
    action: str
    description: str
    undoes: str | None
    files: tuple[tuple[str, tuple[str, ...]], ...]
    file_count: int


def rows(c: sqlite3.Connection, limit: int, files: int, whole: Collection[str] = ()) -> list[Row]:
    """The `limit` most recent entries the index lists, newest first, each with its first `files`
    files (all of them for the entries named in `whole`) and how many it has."""
    out = []
    listed = c.execute(
        "SELECT id, name, time, computer, action, description, undoes,"
        " (SELECT COUNT(*) FROM change_file WHERE change_id = change.id)"
        " FROM change ORDER BY time DESC, name DESC LIMIT ?",
        (limit,),
    ).fetchall()
    for cid, name, time, computer, action, description, undoes, count in listed:
        cap = -1 if name in whole else files
        found = c.execute(
            "SELECT path, fields FROM change_file WHERE change_id = ? ORDER BY position LIMIT ?",
            (cid, cap),
        ).fetchall()
        out.append(
            Row(
                name,
                datetime.fromisoformat(time),
                computer,
                action,
                description,
                undoes,
                tuple((p, tuple(x for x in f.split(",") if x)) for p, f in found),
                count,
            )
        )
    return out


def undone(c: sqlite3.Connection) -> set[str]:
    """The entries undone, by name: those an undo in effect names, an undo being in effect while
    no undo in effect names it in turn (a redo); undoing some of an entry's files counts."""
    undoes = dict(c.execute("SELECT name, undoes FROM change WHERE undoes IS NOT NULL"))
    return in_effect_undone(undoes)


def in_effect_undone(undoes: Mapping[str, str]) -> set[str]:
    """`undone`, from each undo's name and the entry it undoes: an undo undoes its entry while it
    is itself not undone, newest first, since an undo is always newer than what it undoes."""
    out: set[str] = set()
    for name in sorted(undoes, reverse=True):
        if name not in out:
            out.add(undoes[name])
    return out


def last(c: sqlite3.Connection) -> str | None:
    """The entry Ctrl+Z undoes (R4.9): the most recent one still in effect that isn't itself an
    undo, so Ctrl+Z again goes further back; None when there is none. (An undo is undone, a
    redo, from the Change history view or the message that follows it.)"""
    gone = undone(c)
    for (name,) in c.execute(
        "SELECT name FROM change WHERE action != ? ORDER BY time DESC, name DESC", (UNDO,)
    ):
        if name not in gone:
            return str(name)
    return None


def computer_names(musikata: str, computers: Iterable[str]) -> dict[str, str]:
    """The names of the computers `computers` (their ids) as their own play files give them
    (A2.8: `<id>/plays.json`'s computer name); those without one are left out."""
    out = {}
    for computer in set(computers):
        if under_root(computer) is None or "/" in computer:
            continue
        found = rootfiles.read_other(musikata, computer)
        if found is not None and found.name:
            out[computer] = found.name
    return out


# ---------- reading the folder into the index: off the GUI thread ----------


def refresh(index: db.Index, history: str) -> int:
    """The index's entries made the history folder's (`changes`, `sync`), every computer's: at
    start, and when the watcher sees the folder change. On the calling thread, never the GUI's;
    the number of rows changed."""
    have = known(index.read())
    present, entries = changes(history, have)
    return index.write(lambda c: sync(c, present, entries)).result()


@dataclass
class Started:
    """What the history's start did: the entries removed past their age, the old covers
    removed, and the rows the index changed."""

    expired: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    changed: int = 0


def start(index: db.Index, history: str, now: datetime, days: int) -> Started:
    """At start (A3.5): the entries past their age (`days`) removed, the index made the folder's,
    then the old covers no entry names removed. On the calling thread, never the GUI's."""
    expired = expire(history, now, days)
    changed = refresh(index, history)
    pruned = prune(history, covers(index.read()), now.timestamp())
    return Started(expired, pruned, changed)
