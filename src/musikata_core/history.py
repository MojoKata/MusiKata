"""The change history and Undo (R4.9, R4.9.1, A3.5): every save is one entry, a JSON file in the
root's `.musikata/history/` named by its time and the computer that saved it
(`20261125T204512123Z-<computer id>.json`), so entries from several computers never collide; it
is written once, to a temporary file moved into place (A2.8), and never rewritten. For each file
written it holds the file's path under the root and its audio hash (A2.3, as A2.8 names songs),
the old value of each field that changed (`fields`) and the value written (`new`), and, when the
cover changed, the old cover by hash (`cover`, null: there was none) and the new one's
(`new_cover`), and, when its other pictures changed (R5.3), each of those it had, with its type and
description (`pictures`), and the hashes of those written (`new_pictures`). An image file a save
wrote beside the songs (cover.jpg, R5.3) is a file of the entry too, with its old bytes' hash
(`image`, null: there was none) and its new one's (`new_image`). An old cover, picture or image is
kept once in `history/images/<sha256>`, however many entries name it
(`history-entry.v1.schema.json`, A2.10). Moving the others of a song's copies to the trash (R2.12,
R2.11) names each file moved (`trashed`), which Undo can't take out of the trash, and the plays
the copy kept took from them, on the computer that saved the entry (`plays_from`, each as
plays.json names a song; an Undo of it names them `plays_to`, given back), which Undo gives
back (`plays`). Text an ID3 tag held as Latin-1 (A3.6) that a save wrote as Unicode (R4.10's Fix
encoding…) is named in `latin1`: its old value is that text's bytes exactly, a character a byte,
and Undo writes it as Latin-1 again, so the old bytes are back. A file Organize files moved (R12)
names the path it had (`from`); Undo moves it back there (organize.move_file), never over a file
that has taken its place since, and the moves are followed in the index and the playlists by the
caller (organize.Follower).

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

from . import art, db, organize, rootfiles, scanner
from .art import ImageWritten
from .clock import Clock
from .organize import Moved, Trashed
from .rootfiles import Entry as Plays
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
ENTRY_NAMES = {
    f: "genre" if f == "genres" else f for f in compose.FIELDS if f not in compose.PICTURES
}
FIELD_OF = {v: k for k, v in ENTRY_NAMES.items()}


# ---------- an entry, as plain data ----------


@dataclass(frozen=True)
class KeptPicture:
    """A picture a save took out of a song (R5.3's other embedded images): its type (None: the
    kind has none), MIME type and description, and its bytes' hash in history/images."""

    type: int | None
    mime: str
    desc: str
    hash: str


@dataclass(frozen=True)
class FileChange:
    """A file a save wrote: its path under the root (with /), its audio hash (None: not known),
    the old value of each field that changed and the value written (`old`, `new`, by
    compose.FIELDS' names, as `value_of` gives them; a field `new` lacks is one an older entry
    didn't say), and whether the cover changed (`cover`), with the old cover's hash and the new
    one's (None: none); when its other pictures changed, those it had (`others`) and the hashes of
    those written (`new_others`). An image file the save wrote (`image`: cover.jpg, R5.3) has
    only its old and new bytes' hashes, as `old_cover` and `new_cover`. `latin1`: the text fields
    of `old` its ID3 tag held as Latin-1 (A3.6), which Undo writes so again, its old bytes back
    (R4.10). `moved_from`: the path it had before a move (R12's `from`; None: it didn't move),
    where Undo moves it back."""

    path: str
    hash: str | None
    old: Mapping[str, object]
    new: Mapping[str, object] = field(default_factory=dict)
    cover: bool = False
    old_cover: str | None = None
    new_cover: str | None = None
    others: tuple[KeptPicture, ...] | None = None
    new_others: tuple[str, ...] = ()
    image: bool = False
    trashed: bool = False
    plays_from: tuple[Plays, ...] = ()
    plays_to: tuple[Plays, ...] = ()
    latin1: tuple[str, ...] = ()
    moved_from: str | None = None

    def fields(self) -> list[str]:
        """The fields it changed, in compose.FIELDS' order, the cover and the other pictures
        among them, then its plays (R2.12) and whether it went to the trash; an image file's is
        its cover."""
        if self.image:
            return ["cover"]
        return (  # a move (R12) is its path
            [
                f
                for f in compose.FIELDS
                if f in self.old
                or (f == "cover" and self.cover)
                or (f == "others" and self.others is not None)
            ]
            + (["plays"] if self.plays else [])
            + (["trashed"] if self.trashed else [])
            + (["path"] if self.moved_from is not None else [])
        )

    @property
    def plays(self) -> bool:
        """Whether it moved plays (R2.12): from other copies into this file, or back."""
        return bool(self.plays_from or self.plays_to)

    @property
    def tags(self) -> bool:
        """Whether it changed the file itself: a field, the cover or the other pictures."""
        return bool(self.old) or self.cover or self.others is not None

    def kept(self) -> list[str]:
        """The hashes of what it keeps in history/images: the old cover or image, and the old
        other pictures."""
        out = [self.old_cover] if self.old_cover is not None else []
        return out + [p.hash for p in self.others or ()]


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
        if f.moved_from is not None:
            out["from"] = f.moved_from
        if f.image:
            out["image"], out["new_image"] = f.old_cover, f.new_cover
            files.append(out)
            continue
        if f.hash is not None:
            out["hash"] = f.hash
        out["fields"] = {ENTRY_NAMES[k]: v for k, v in f.old.items()}
        out["new"] = {ENTRY_NAMES[k]: v for k, v in f.new.items()}
        if f.cover:
            out["cover"], out["new_cover"] = f.old_cover, f.new_cover
        if f.others is not None:
            out["pictures"] = [
                {"type": p.type, "mime": p.mime, "desc": p.desc, "image": p.hash} for p in f.others
            ]
            out["new_pictures"] = list(f.new_others)
        if f.plays_from:
            out["plays_from"] = [rootfiles.entry_document(e) for e in f.plays_from]
        if f.plays_to:
            out["plays_to"] = [rootfiles.entry_document(e) for e in f.plays_to]
        if f.trashed:
            out["trashed"] = True
        if f.latin1:
            out["latin1"] = [ENTRY_NAMES[k] for k in f.latin1]
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


def _pictures(
    value: object, new: object, where: str, problems: list[str]
) -> tuple[tuple[KeptPicture, ...], tuple[str, ...]] | None:
    """An entry's `pictures` and `new_pictures` (the other pictures it took out, and those it
    wrote); None, with the problem, when they can't be used: none of them is put back then."""
    if not isinstance(value, list) or not isinstance(new, list | type(None)):
        problems.append(f"{where}: pictures isn't a list: {value!r}; left out")
        return None
    out = []
    for p in value:
        kind = p.get("type") if isinstance(p, dict) else None
        digest = p.get("image") if isinstance(p, dict) else None
        if (
            not isinstance(p, dict)
            or not (kind is None or (isinstance(kind, int) and not isinstance(kind, bool)))
            or not isinstance(digest, str)
            or not HASH.fullmatch(digest.lower())
        ):
            problems.append(f"{where}: a picture isn't one it can put back: {p!r}; left out")
            return None
        mime, desc = p.get("mime"), p.get("desc")
        out.append(KeptPicture(kind, mime if isinstance(mime, str) else "",
                               desc if isinstance(desc, str) else "", digest.lower()))  # fmt: skip
    written = tuple(
        h.lower() for h in new or () if isinstance(h, str) and HASH.fullmatch(h.lower())
    )
    return tuple(out), written


def _plays(value: object, where: str, problems: list[str]) -> tuple[Plays, ...]:
    """An entry's `plays_from` or `plays_to` (R2.12): each song's plays as plays.json names them,
    one it can't use left out; none when it isn't a list."""
    if value is None:
        return ()
    if not isinstance(value, list):
        problems.append(f"{where} isn't a list: {value!r}; left out")
        return ()
    out = []
    for item in value:
        found = rootfiles.entry_of(item, problems)
        if found is not None and under_root(found.path) is not None:
            out.append(found)
        elif found is not None:
            problems.append(f"{where}: {found.path!r} isn't a path under the root; left out")
    return tuple(out)


def _image(path: str, value: dict[str, object], problems: list[str]) -> FileChange | None:
    """An image file of `files` (cover.jpg, R5.3): its old and new bytes' hashes."""
    usable, old = _cover(value["image"], f"{path}: image", problems)
    if not usable:
        return None
    new = None
    if "new_image" in value:
        fine, new = _cover(value["new_image"], f"{path}: new_image", problems)
        new = new if fine else None
    return FileChange(path, None, {}, {}, False, old, new, image=True)


def _file(value: object, problems: list[str]) -> FileChange | None:
    """A file of `files`; None, with the problem, when it can't be used."""
    if not isinstance(value, dict):
        problems.append(f"a file isn't an object: {value!r}; left out")
        return None
    path = under_root(value.get("path"))
    if path is None:
        problems.append(f"a file's path isn't a path under the root: {value.get('path')!r}")
        return None
    if "image" in value:
        return _image(path, value, problems)
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
    others = new_others = None
    if "pictures" in value:
        found = _pictures(value["pictures"], value.get("new_pictures"), path, problems)
        if found is not None:
            others, new_others = found
    plays_from = _plays(value.get("plays_from"), f"{path}: plays_from", problems)
    plays_to = _plays(value.get("plays_to"), f"{path}: plays_to", problems)
    trashed = value.get("trashed") is True
    if "trashed" in value and not isinstance(value["trashed"], bool):
        problems.append(f"{path}: trashed isn't true or false: {value['trashed']!r}; false")
    latin1 = _latin1(value.get("latin1"), old, f"{path}: latin1", problems)
    moved_from = None
    if "from" in value:
        moved_from = under_root(value["from"])
        if moved_from is None:
            problems.append(f"{path}: from isn't a path under the root: {value['from']!r}; the"
                            " move left out")  # fmt: skip
    if (not old and not cover and others is None and not plays_from and not plays_to
            and not trashed and moved_from is None):  # fmt: skip
        problems.append(f"{path}: no field it can put back; left out")
        return None
    return FileChange(path, hash_, old, new, cover, old_cover, new_cover, others,
                      new_others or (), False, trashed, plays_from, plays_to, latin1,
                      moved_from)  # fmt: skip


def _latin1(
    value: object, old: Mapping[str, object], where: str, problems: list[str]
) -> tuple[str, ...]:
    """An entry's `latin1`: the text fields of its old values held as Latin-1 (A3.6), by
    compose.FIELDS' names; a name that isn't one of them left out (its value is put back as
    Unicode)."""
    if value is None:
        return ()
    if not isinstance(value, list):
        problems.append(f"{where} isn't a list: {value!r}; left out")
        return ()
    names = {FIELD_OF.get(v) for v in value if isinstance(v, str)}
    out = tuple(f for f in compose.TEXT if f in names and f in old)
    if len(out) != len(value):
        problems.append(f"{where}: a name isn't a text field it changed: {value!r}; left out")
    return out


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

    def saved(self, written: Written | ImageWritten | Moved | Trashed) -> None:
        """A file written (safe.Written, or art.ImageWritten for cover.jpg): what it changed kept,
        its old cover, other pictures or image in images/; a file moved (organize.Moved, R12):
        the path it had; or a file or folder moved to the trash (organize.Trashed, R2.11): each
        song that went, or the file itself."""
        if isinstance(written, ImageWritten):
            self._image(written)
            return
        if isinstance(written, Moved):
            self._moved(written)
            return
        if isinstance(written, Trashed):
            self._trashed(written)
            return
        if not written.changed or written.before is None:
            return
        path = scanner.path_under(self._root, written.path)
        if path is None:
            log.warning(
                "%s isn't under %s: the change history passes it by", written.path, self._root
            )
            return
        fields = [f for f in written.changed if f not in compose.PICTURES]
        old = {f: value_of(written.before, f) for f in fields}
        latin1 = tuple(f for f in fields if f in written.before.latin1)
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
        others = None
        if written.others_before is not None:
            others = tuple(
                KeptPicture(p.type, p.mime, p.desc, self._keep(p.data, path))
                for p in written.others_before
            )
        new_others = tuple(image_hash(p.data) for p in written.others_after or ())
        self.files.append(FileChange(path, written.audio_hash, old, new, cover, old_cover,
                                     new_cover, others, new_others, latin1=latin1))  # fmt: skip

    def _moved(self, moved: Moved) -> None:
        path = scanner.path_under(self._root, moved.path)
        old = scanner.path_under(self._root, moved.old)
        if path is None or old is None:
            log.warning("%s isn't under %s: the change history passes it by", moved.path,
                        self._root)  # fmt: skip
            return
        self.files.append(FileChange(path, moved.hash, {}, moved_from=old))

    def _trashed(self, trashed: Trashed) -> None:
        path = scanner.path_under(self._root, trashed.path)
        if path is None:
            log.warning("%s isn't under %s: the change history passes it by", trashed.path,
                        self._root)  # fmt: skip
            return
        went = trashed.songs or ((path, trashed.hash),)
        self.files += [FileChange(p, h, {}, trashed=True) for p, h in went]

    def _keep(self, data: bytes, path: str) -> str:
        try:
            return keep_image(self._history, data)
        except OSError as e:
            log.warning("couldn't keep an old picture of %s: %s", path, e)
            return image_hash(data)

    def _image(self, written: ImageWritten) -> None:
        if written.before == written.after:
            return
        path = scanner.path_under(self._root, written.path)
        if path is None:
            log.warning(
                "%s isn't under %s: the change history passes it by", written.path, self._root
            )
            return
        old = self._keep(written.before, path) if written.before is not None else None
        new = image_hash(written.after) if written.after is not None else None
        self.files.append(FileChange(path, None, {}, {}, False, old, new, image=True))

    def note(self, change: FileChange) -> None:
        """A change that isn't a file written (R2.12: a file moved to the trash, the plays the
        copy kept took), kept in the entry with the files saved; one of a file saved too is one
        file of the entry (`combined`)."""
        self.files.append(change)

    def done(self, action: str, description: str) -> str | None:
        """The entry written for the files saved; its name, None when none was."""
        self.files = combined(self.files)
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


def combined(files: Sequence[FileChange]) -> list[FileChange]:
    """`files` with the changes of one path made one, in the order each path came first: a file
    saved (its fields) and what was noted of it (its plays, R2.12), so an entry names it once."""
    out: dict[str, FileChange] = {}
    for f in files:
        had = out.get(f.path)
        if had is None:
            out[f.path] = f
            continue
        pictured = had if had.cover else f
        others = had if had.others is not None else f
        out[f.path] = dataclasses.replace(
            had, hash=had.hash or f.hash, old={**f.old, **had.old}, new={**f.new, **had.new},
            cover=had.cover or f.cover, old_cover=pictured.old_cover,
            new_cover=pictured.new_cover, others=others.others, new_others=others.new_others,
            trashed=had.trashed or f.trashed, plays_from=had.plays_from + f.plays_from,
            plays_to=had.plays_to + f.plays_to,
            latin1=tuple(n for n in compose.TEXT if n in had.latin1 or n in f.latin1),
            moved_from=had.moved_from or f.moved_from,
        )  # fmt: skip
    return list(out.values())


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
    taken: bool = False  # a move's old place holds another file now (R12.4): it stays


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

    @property
    def taken(self) -> list[FileUndo]:
        """The files moved (R12) whose old place another file has taken since: Undo leaves them
        where they are, never writing over that file (R12.4)."""
        return [f for f in self.files if f.taken]

    @property
    def in_trash(self) -> list[FileUndo]:
        """The files the entry moved to the trash (R2.11, R2.12): Undo can't take them out."""
        return [f for f in self.files if f.change.trashed]


@dataclass(frozen=True)
class Current:
    """A file as it is now: its tags, and, when asked for, its cover's hash (None: none) and its
    other pictures' hashes, sorted."""

    tags: Tags
    cover: str | None = None
    others: tuple[str, ...] = ()


def current(path: str, cover: bool) -> Current:
    """The file at `path` as it is now (tags.read, and its pictures' hashes when `cover`). Raises
    TagReadError or OSError when it can't be read."""
    tags, info = read_tags(path)
    if not cover:
        return Current(tags)
    typed = info.kind not in ("aac", "alac")
    had = read_pictures(path)
    picture = compose.cover_of(had, typed)
    others = tuple(sorted(image_hash(p.data) for p in compose.others_of(had, typed)))
    return Current(tags, image_hash(picture.data) if picture is not None else None, others)


def image_now(path: str) -> str | None:
    """The hash of the image file at `path` (cover.jpg) as it is now; None when it isn't there.
    Raises OSError when it can't be read."""
    try:
        with open(path, "rb") as f:
            return image_hash(f.read())
    except FileNotFoundError:
        return None


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
        return dataclasses.replace(found, tags=dataclasses.replace(found.tags, rating=rating))

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
    if change.others is not None:
        back = tuple(sorted(p.hash for p in change.others))
        if now.others not in (back, tuple(sorted(change.new_others))):
            out.append(Lost("others", now.others, back))
    return tuple(out)


def lost_image(change: FileChange, now: str | None) -> tuple[Lost, ...]:
    """What undoing an image file's change would lose (R4.9.1): the image there now, when it is
    neither what the entry wrote nor what undoing puts back."""
    if now in (change.old_cover, change.new_cover):
        return ()
    return (Lost("cover", now, change.old_cover),)


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
        if change.image:
            try:
                now_image = image_now(scanner.full_path(root, change.path))
            except OSError as e:
                log.warning("couldn't read %s to undo it: %s", change.path, e)
                out.append(FileUndo(change, change.path, why=f"it can't be read: {e}"))
                continue
            out.append(FileUndo(change, change.path, lost_image(change, now_image)))
            continue
        if change.trashed and not change.tags and not change.plays:
            out.append(FileUndo(change, None))  # in the trash: nothing Undo can do (R2.11)
            continue
        if change.moved_from is not None and not change.tags:
            out.append(_unmove(change, root, find))
            continue
        path: str | None = change.path
        if not os.path.exists(scanner.full_path(root, change.path)):
            found = find(change.hash) if change.hash is not None else ()
            path = next((p for p in found if os.path.exists(scanner.full_path(root, p))), None)
        if path is None:
            out.append(FileUndo(change, None, why="it isn't there any more"))
            continue
        if not change.tags:  # its plays alone (R2.12): nothing of the file to read
            out.append(FileUndo(change, path))
            continue
        try:
            pictures = change.cover or change.others is not None
            now = look(scanner.full_path(root, path), pictures)
        except Exception as e:  # noqa: BLE001  (a file that can't be read is listed, not undone)
            log.warning("couldn't read %s to undo it: %s", path, e)
            out.append(FileUndo(change, path, why=f"it can't be read: {e}"))
            continue
        out.append(FileUndo(change, path, lost(change, now)))
    return Plan(entry, tuple(out))


TAKEN = "its old place, {}, holds another file now"  # a move's (R12.4), never written over


def _unmove(change: FileChange, root: str, find: Callable[[str], Sequence[str]]) -> FileUndo:
    """Undoing a move (R12): the file where it is now (its path, else by its audio hash: moved
    again since, which undoing would lose, R4.9.1), put back at its old path unless another file
    has taken that since (R12.4)."""
    assert change.moved_from is not None
    path: str | None = change.path
    if not os.path.lexists(scanner.full_path(root, change.path)):
        found = find(change.hash) if change.hash is not None else ()
        path = next((p for p in found if os.path.exists(scanner.full_path(root, p))), None)
    if path is None:
        return FileUndo(change, None, why="it isn't there any more")
    if organize.same_path(path, change.moved_from):  # back already, or but for its case
        return FileUndo(change, path)
    if _other_file(scanner.full_path(root, path), scanner.full_path(root, change.moved_from)):
        return FileUndo(change, path, why=TAKEN.format(change.moved_from), taken=True)
    lost = () if path == change.path else (Lost("path", path, change.moved_from),)
    return FileUndo(change, path, lost)


def _other_file(path: str, other: str) -> bool:
    """Whether a file other than the one at `path` is at `other`."""
    if not os.path.lexists(other):
        return False
    try:
        return not os.path.samefile(path, other)
    except OSError:
        return True


@dataclass(frozen=True)
class KeptCover:
    """A cover to put back, by its hash in history/images, loaded only as its file is written."""

    hash: str


def jobs(plan_: Plan, root: str, overwrite: bool) -> list[Job]:
    """The files to write to undo `plan_`: each that can be, with its old values; those changed
    since (R4.9.1) only when `overwrite`, the user's answer."""
    out = []
    doing = [f for f in plan_.files if not f.why and f.path is not None
             and (not f.lost or overwrite)]  # fmt: skip
    # the moves (R12) back, a .cue sheet's FILE lines with them (organize.move_jobs)
    moves = [
        organize.Move(f.path, f.change.moved_from, hash=f.change.hash)
        for f in doing
        if f.path is not None and f.change.moved_from is not None and not f.change.tags
    ]
    back = {m.old: job for m, job in zip(moves, organize.move_jobs(root, moves), strict=True)}
    for f in doing:
        assert f.path is not None
        if f.change.moved_from is not None and not f.change.tags:  # a move (R12): back
            out.append(back[f.path])
            continue
        if not f.change.image and not f.change.tags:
            continue  # its plays alone (R2.12): `undo` gives them back
        old = f.change.old_cover
        if f.change.image:
            image = KeptCover(old) if old is not None else None
            out.append(Job(scanner.full_path(root, f.path), {"image": image}))
            continue
        changes: dict[str, object] = dict(f.change.old)
        if f.change.cover:
            changes["cover"] = KeptCover(old) if old is not None else None
        if f.change.others is not None:
            changes["others"] = f.change.others
        if f.change.latin1:  # its old bytes back (R4.10), not their text as Unicode
            changes[compose.LATIN1] = f.change.latin1
        out.append(Job(scanner.full_path(root, f.path), changes))
    return out


Writer = Callable[[Job], Written | ImageWritten | Moved]  # a save's writer: art.writer's


def with_covers(write: Writer, history: str) -> Writer:
    """`write` (art.writer, as a batch's writer), with the covers, pictures and images kept in
    history/images loaded as their file is written; one no longer kept fails that file, with
    why."""

    def load(job: Job, digest: str) -> bytes:
        data = load_image(history, digest)
        if data is None:
            raise WriteError(job.path, "its old cover isn't in the change history any more")
        return data

    def writer(job: Job) -> Written | ImageWritten | Moved:
        if organize.MOVE in job.changes:  # a move undone (R12): no file written, a rename
            return organize.move_file(job)
        changes = dict(job.changes)
        cover = changes.get("cover")
        if isinstance(cover, KeptCover):
            data = load(job, cover.hash)
            changes["cover"] = Picture(compose.FRONT, compose.image_mime(data), data)
        image = changes.get("image")
        if isinstance(image, KeptCover):
            changes["image"] = load(job, image.hash)
        others = changes.get("others")
        if isinstance(others, tuple) and any(isinstance(p, KeptPicture) for p in others):
            pictures = []
            for p in others:
                if isinstance(p, KeptPicture):
                    data = load(job, p.hash)
                    mime = p.mime or compose.image_mime(data)
                    pictures.append(Picture(p.type, mime, data, p.desc))
            changes["others"] = tuple(pictures)
        return write(Job(job.path, changes))

    return writer


def description_of(entry: Entry, files: int) -> str:
    """What undoing `entry` is, for the list: "Undo: <what it was>"."""
    what = entry.description or ("a save" if entry.action != UNDO else "an undo")
    whole = sum(1 for f in entry.files if f.image or f.tags or f.plays or f.moved_from is not None)
    # not those in the trash
    some = "" if files == whole else f" ({files} of {whole} files)"
    return f"Undo: {what}{some}"


# gives back the plays of the files of an entry saved on a computer (its id): R2.12's, each where
# it is now; what was given back, as the undo's entry keeps it
PlaysBack = Callable[[str, Sequence["FileUndo"]], list[FileChange]]


def plays_undone(f: FileUndo, moved: Sequence[Plays]) -> FileChange:
    """What undoing a file's plays (R2.12) did, as the undo's entry keeps it, so it can be undone
    in turn: plays it had taken given back (`plays_to`), or plays given back taken again
    (`plays_from`), `moved` being those."""
    path = f.path or f.change.path
    if f.change.plays_from:
        return FileChange(path, f.change.hash, {}, plays_to=tuple(moved))
    return FileChange(path, f.change.hash, {}, plays_from=tuple(moved))


def plays_back(c: sqlite3.Connection, computer: str, files: Sequence[FileUndo]) -> list[FileChange]:
    """In the writer's transaction: the plays each file of an entry moved (R2.12) moved back, on
    `computer`'s rows (this computer's key): plays the file took from other copies given back to
    them (rootfiles.give_plays), plays given back taken again (rootfiles.take_back). What was
    done, as the undo's entry keeps it (`plays_undone`); a file the index hasn't is passed by."""
    out = []
    for f in files:
        song = c.execute("SELECT id FROM song WHERE path = ?", (f.path,)).fetchone()
        if song is None:
            log.warning("%s isn't in the library: its plays weren't moved back", f.path)
            continue
        if f.change.plays_from:
            moved = rootfiles.give_plays(c, computer, song[0], f.change.plays_from)
        else:
            moved = rootfiles.take_back(c, computer, song[0], f.change.plays_to)
        if moved:
            out.append(plays_undone(f, moved))
    return out


def undo(
    plan_: Plan,
    root: str,
    overwrite: bool,
    write: Callable[[Job], Written],
    record: Recording | None,
    progress: Progress | None = None,
    trash: art.Trash = art.to_trash,
    plays: PlaysBack | None = None,
) -> Outcome[Written | ImageWritten | Moved]:
    """Undoes `plan_` (R4.9): the old values written with `write` (safe.save, A3.4) in a batch of
    its own, recorded by `record` (a Recording that `undoes` the entry; None: the history is off)
    as an entry, so it can be undone in turn. Files changed since are written only when
    `overwrite` (R4.9.1), else passed by; those that can't be undone are listed as failed, with
    why, as a save's are (R4.7). An image file (cover.jpg) is put back, or moved to the trash
    when there was none, by art.save_image, the one there now going to the trash (`trash`).
    The plays an entry moved (R2.12) are given back by `plays` (None: they aren't), kept in the
    undo's entry with its files; the files it moved to the trash stay there (R2.11)."""
    todo = jobs(plan_, root, overwrite)
    moving = [f for f in plan_.files if f.change.plays and not f.why and f.path is not None
              and (not f.lost or overwrite)]  # fmt: skip
    if moving and plays is not None:
        for change in plays(plan_.entry.computer, moving):
            if record is not None:
                record.note(change)
    undone = len(todo) + sum(1 for f in moving if not f.change.tags)
    batch: Batch[Written | ImageWritten | Moved] = Batch(
        todo,
        with_covers(art.writer(write, trash), folder_of(root)),
        progress,
        record=record,
        action=UNDO,
        description=description_of(plan_.entry, undone),
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
                (cur.lastrowid, n, f.path, f.hash, ",".join(f.fields()), " ".join(f.kept()) or None)
                for n, f in enumerate(e.files)
            ],
        )
    return len(gone) + added


def covers(c: sqlite3.Connection) -> set[str]:
    """The old covers, pictures and images the index's entries name, by hash (each file's,
    space-separated in its row)."""
    return {h for (kept,) in c.execute("SELECT DISTINCT cover FROM change_file") if kept
            for h in str(kept).split()}  # fmt: skip


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
