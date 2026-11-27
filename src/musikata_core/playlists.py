"""Playlists (R8, A2.1): M3U and M3U8 files, read in the shapes other programs write them and
written as R8.1 says, and kept in the index's `playlist` and `playlist_entry` tables.

- **Reading** (R8.1.2): `parse` takes any bytes and never fails: UTF-8 first (its byte order
  mark, and UTF-16's, read as such), then the system's legacy encoding for an `.m3u` that isn't
  valid UTF-8 (`legacy_encoding`); lines ended by LF, CRLF or CR; `#EXTM3U` optional, `#EXTINF`
  before an entry or not, other comments and blank lines passed by, the comments before the first
  entry kept (`Playlist.header`: `#PLAYLIST:`, and a smart playlist's `#MUSIKATA-RULE:`, R8.9,
  whose rule smart.py reads).
- **Where an entry is** (`resolve`): relative to the playlist's own folder, or absolute; with `/`
  or `\\` between folders; a `file://` URL; a Windows path with its drive. An entry under the root
  is its path under the root (with `/`), as the index holds a song; one elsewhere, or an address on
  the web, is None: not in the library, shown as missing (R8.7).
- **Writing** (R8.1, R8.1.1): `compose` writes `#EXTM3U`, then `#EXTINF:<seconds>,<artist> -
  <title>` and the path of each entry, and `normal` puts a playlist in that form: each entry
  under the root named relative to the playlist's folder with `/`, its `#EXTINF` from its song.
  A file is written whole through a temporary file beside it and `os.replace` (`write_file`,
  A2.8), never half. A playlist read from elsewhere is rewritten only when it changes in MusiKata
  (`Store`); an `.m3u` keeps the legacy encoding it was read in when its text fits it.
- **The plans** (`added`, `removed`, `fixed`, `repointed`; R8.5's `already_in`, `taken_back`,
  `move_order` and `nudge_order`), the names (`file_name`, `unique`, `copy_name`), Find's
  matching (`candidates`), Export's plan (`export_plan`) and the files a file manager dropped
  (`dropped`) are plain functions over plain data, tested without a file.
- **The index** (`index_file`, `refresh`): the scan finds `.m3u` and `.m3u8` files anywhere under
  the root (scanner.walk) and reads those whose size or modification time changed, so one another
  program changes is read again when the watcher sees it (R8.1.3, R2.4).
- **MusiKata's own changes** (`Store`): making, renaming, duplicating and removing a playlist
  (R8.3, R8.4), adding entries and taking an addition back out (R8.5's Undo), moving them by
  dragging or by keys (R8.5, R18.2), removing them (R8.6), fixing a missing one (R8.7), each the
  file read again first, changed, written and indexed, one at a time; and `Store.repoint`, which
  points every playlist naming a file moved at its new path: what R2.12's Move the others to the
  trash calls for the copies it removed, and what Organize files (R12.4) calls when it moves
  files. A smart playlist (R8.9) is made with its rule and its songs (`create_smart`), its rule
  edited (`set_rule`) and its songs kept current (`refill`, written only when they differ); a
  change by hand to one is refused, its rule choosing its songs."""

from __future__ import annotations

import codecs
import contextlib
import locale
import logging
import math
import os
import posixpath
import re
import shutil
import sqlite3
import threading
import unicodedata
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from urllib.parse import unquote, urlsplit

from . import db, duplicates, folders, smart, sortnames
from .tags.safe import tmp_path

log = logging.getLogger(__name__)

KINDS = {".m3u8": "m3u8", ".m3u": "m3u"}  # a playlist's extension, and its kind
FOLDER = "Playlists"  # the playlists folder under the root, by default (R8.1, R13.6)
NEW_NAME = "New playlist"  # R8.3
HEADER = "#EXTM3U"
EXTINF = "#EXTINF:"
RULE = smart.RULE  # a smart playlist's rule (R8.9)
UNKNOWN = -1  # #EXTINF's seconds when the length isn't known
ABSOLUTE = "absolute"  # Export's two ways (R8.8): an .m3u8 naming the songs where they are,
COPIES = "copies"  # or the songs copied, numbered, beside an .m3u8 naming them
# what a file's name can't hold on any system a playlist or a USB stick goes to (FAT, NTFS)
NOT_IN_NAMES = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+://")
DRIVE = re.compile(r"^[A-Za-z]:(/|$)")
TRACK = re.compile(r"^\s*\d+(\s*[-._)]\s*|\s+)")  # a track number before a file's title: "04 - "
CHUNK = 500


# ---------- reading and writing the file (R8.1, R8.1.2) ----------


@dataclass(frozen=True)
class Entry:
    """An entry as a playlist names it: where (`location`, as written), and its `#EXTINF`'s
    seconds (None: none, or not known) and text ("Artist - Title")."""

    location: str
    seconds: int | None = None
    title: str = ""


@dataclass(frozen=True)
class Playlist:
    """A playlist's entries in order, the comment lines before the first of them (but #EXTM3U),
    kept when it is written again, and the encoding it was read in ("utf-8", or the legacy one)."""

    entries: tuple[Entry, ...] = ()
    header: tuple[str, ...] = ()
    encoding: str = "utf-8"


def kind_of(name: str) -> str | None:
    """A file's playlist kind by its extension, in any case: "m3u8", "m3u", or None."""
    return KINDS.get(os.path.splitext(name)[1].lower())


def name_of(path: str) -> str:
    """A playlist's name: its file's, without the extension."""
    return os.path.splitext(path.rpartition("/")[2])[0]


def legacy_encoding() -> str:
    """The system's legacy encoding (R8.1.2), for an `.m3u` that isn't UTF-8: the locale's, or,
    where the locale is UTF-8 itself (Linux, macOS), Windows' Western one, which is what such a
    file most likely is."""
    preferred = locale.getpreferredencoding(False)
    try:
        name = codecs.lookup(preferred).name
    except LookupError:
        return "cp1252"
    return "cp1252" if name in ("utf-8", "ascii") else name


def decode(data: bytes, kind: str = "m3u8", legacy: str = "cp1252") -> tuple[str, str]:
    """A playlist's text and the encoding it was read in (R8.1.2): by its byte order mark (UTF-8's
    or UTF-16's, read as "utf-8"); else UTF-8; else, for an `.m3u`, `legacy`; what neither reads,
    as UTF-8 with the bytes it can't read replaced."""
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8", "replace"), "utf-8"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace"), "utf-8"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    if kind == "m3u":
        try:
            codecs.lookup(legacy)
        except LookupError:
            legacy = "cp1252"
        return data.decode(legacy, "replace"), legacy
    return data.decode("utf-8", "replace"), "utf-8"


def _extinf(text: str) -> tuple[int | None, str]:
    """#EXTINF's seconds and text: `-1`, `253`, `253.4`, or with attributes after them (`-1
    tvg-id="x"`); a length that isn't one, or is negative, is None."""
    secs, _, title = text.partition(",")
    words = secs.split()
    seconds: int | None = None
    if words:
        try:
            value = float(words[0])
        except ValueError:
            value = -1.0
        if math.isfinite(value) and value >= 0:
            seconds = round(value)
    return seconds, title.strip()


def parse(data: bytes, kind: str = "m3u8", legacy: str = "cp1252") -> Playlist:
    """A playlist from its file's bytes, whatever they are (R8.1.2): its entries, each with the
    `#EXTINF` before it, if any; its header comments; the encoding it was read in. Never raises."""
    text, encoding = decode(data, kind, legacy)
    entries: list[Entry] = []
    header: list[str] = []
    pending: tuple[int | None, str] | None = None
    for raw in re.split(r"\r\n|\r|\n", text.replace("\x00", "")):
        line = raw.strip().lstrip("\ufeff").strip()
        if not line:
            continue
        if line.startswith("#"):
            upper = line.upper()
            if upper.startswith(HEADER):
                continue
            if upper.startswith(EXTINF):
                pending = _extinf(line[len(EXTINF) :])
            elif not entries:
                header.append(line)
            continue
        seconds, title = pending if pending is not None else (None, "")
        entries.append(Entry(line, seconds, title))
        pending = None
    return Playlist(tuple(entries), tuple(header), encoding)


def _one_line(text: str) -> str:
    return " ".join(re.split(r"[\r\n]+", text)).strip()


def compose(p: Playlist, encoding: str = "utf-8") -> bytes:
    """A playlist's file as R8.1 writes it: `#EXTM3U`, its header, then each entry's
    `#EXTINF:<seconds>,<text>` (-1 for a length not known) and its location, a line each, in
    `encoding` (UTF-8 when its text doesn't fit it)."""
    lines = [HEADER, *(_one_line(h) for h in p.header)]
    for e in p.entries:
        seconds = e.seconds if e.seconds is not None else UNKNOWN
        lines.append(f"{EXTINF}{seconds},{_one_line(e.title)}")
        lines.append(_one_line(e.location))
    text = "\n".join(lines) + "\n"
    try:
        return text.encode(encoding)
    except UnicodeEncodeError, LookupError:
        return text.encode("utf-8")


def write_file(path: str, data: bytes) -> os.stat_result:
    """`data` written as the file at `path`, whole: to a hidden copy beside it, then moved over
    it (A2.8), so a crash or a sync never leaves half a playlist; the file's stat. Raises OSError,
    the file as it was, when it can't be."""
    tmp = tmp_path(path)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    return os.stat(path)


# ---------- where an entry is (R8.1, R8.1.2) ----------


def location_path(location: str) -> str:
    """An entry's location as a path with `/`: a `file://` URL's path, its escapes read (a host
    but localhost a share's, `//host/…`; `/C:/…` a Windows drive's); `\\` taken for `/`."""
    if location[:5].lower() == "file:":
        parts = urlsplit(location)
        path = unquote(parts.path)
        if parts.netloc and parts.netloc.lower() != "localhost":
            path = f"//{parts.netloc}{path}"
        elif re.match(r"^/[A-Za-z]:[/\\]", path):
            path = path[1:]
        return path.replace("\\", "/")
    return location.replace("\\", "/")


def _absolute(path: str) -> bool:
    return path.startswith("/") or DRIVE.match(path) is not None


def root_form(root: str) -> str:
    """The root as `resolve` compares paths with it: with `/`, no `/` at its end."""
    return root.replace("\\", "/").rstrip("/")


def resolve(location: str, folder: str, root: str) -> str | None:
    """Where an entry is (R8.1.2): its path under the root with `/` (as the index holds a song),
    the playlist being in `folder` (under the root, "" for the root itself); None when it is
    outside the root, an address on the web, or names nothing. A path relative to the folder, an
    absolute path, a Windows path (its drive and its case aside, as Windows has it) and a
    `file://` URL are each read."""
    path = location_path(location.strip())
    if not path or (URL.match(location.strip()) and location.strip()[:5].lower() != "file:"):
        return None
    if _absolute(path):
        base = root_form(root)
        windows = DRIVE.match(base) is not None or base.startswith("//")
        under, inside = (path.casefold(), base.casefold()) if windows else (path, base)
        if not under.startswith(inside + "/"):
            return None
        rel = path[len(base) + 1 :]
    else:
        rel = f"{folder}/{path}" if folder else path
    norm = posixpath.normpath(rel)
    if norm in (".", "..") or norm.startswith(("../", "/")):
        return None
    return norm


def relative_to(path: str, folder: str) -> str:
    """A path under the root as an entry of a playlist in `folder` names it (R8.1): relative to
    that folder, with `/`."""
    to, start = path.split("/"), folder.split("/") if folder else []
    common = 0
    while common < min(len(to), len(start)) and to[common] == start[common]:
        common += 1
    return "/".join([".."] * (len(start) - common) + to[common:])


def is_relative(location: str) -> bool:
    """Whether an entry names its file relative to the playlist (R8.1), as the view says."""
    path = location_path(location.strip())
    return not (_absolute(path) or URL.match(location.strip()))


# ---------- the names (R8.3, R8.4) ----------


def file_name(name: str) -> str:
    """A name as a file can be named on every system (a playlist's, or a song's copied by
    Export): what a name can't hold made `_`, the spaces and dots at its ends taken off; "" for a
    name of nothing."""
    cleaned = NOT_IN_NAMES.sub("_", unicodedata.normalize("NFC", name))
    return cleaned.strip().rstrip(".").strip()


def unique(name: str, taken: Iterable[str]) -> str:
    """`name`, or with the first number from 2 that makes it a name not `taken` (case aside, as
    Windows and macOS compare names): "New playlist 2"."""
    used = {t.casefold() for t in taken}
    if name.casefold() not in used:
        return name
    n = 2
    while f"{name} {n}".casefold() in used:
        n += 1
    return f"{name} {n}"


def copy_name(name: str, taken: Iterable[str]) -> str:
    """A duplicate's name (R8.4): "Road Trip copy", numbered when that is taken."""
    return unique(f"{name} copy", taken)


# ---------- the plans: what a change makes of a playlist ----------


@dataclass(frozen=True)
class Song:
    """A song as an entry names it: its path under the root, length, artist and title."""

    path: str
    seconds: float | None = None
    artist: str | None = None
    title: str | None = None


def stem(location: str) -> str:
    """The name of the file an entry names, without its extension."""
    return os.path.splitext(location_path(location).rstrip("/").rpartition("/")[2])[0]


def extinf_of(song: Song) -> tuple[int | None, str]:
    """A song's `#EXTINF` (R8.1.1): its length in whole seconds, and "Artist - Title" (the title
    alone without an artist; the file's name without a title)."""
    title = song.title or stem(song.path)
    text = f"{song.artist} - {title}" if song.artist else title
    seconds = round(song.seconds) if song.seconds is not None and song.seconds >= 0 else None
    return seconds, text


def normal(p: Playlist, folder: str, root: str, known: Mapping[str, Song]) -> Playlist:
    """A playlist in R8.1's form, as MusiKata writes one: each entry under the root named relative
    to `folder` with `/`, its `#EXTINF` from its song (`known`, by path), else the one it had,
    else its file's name; an entry outside the root as it was written."""
    out = []
    for e in p.entries:
        path = resolve(e.location, folder, root)
        location = relative_to(path, folder) if path is not None else e.location.strip()
        song = known.get(path) if path is not None else None
        if song is not None:
            seconds, title = extinf_of(song)
        else:
            seconds, title = e.seconds, e.title or stem(e.location)
        out.append(Entry(location, seconds, title))
    return replace(p, entries=tuple(out))


def added(p: Playlist, paths: Sequence[str], folder: str) -> Playlist:
    """`paths` (under the root) added at the end of the playlist, in order, named relative to its
    folder; a song already there is added again (R8.5)."""
    return replace(p, entries=p.entries + tuple(Entry(relative_to(x, folder)) for x in paths))


def removed(p: Playlist, positions: Collection[int]) -> Playlist:
    """The entries at `positions` (from 0) taken out (R8.6)."""
    return replace(p, entries=tuple(e for i, e in enumerate(p.entries) if i not in positions))


def fixed(p: Playlist, location: str, path: str, folder: str) -> Playlist:
    """Each entry naming `location` (as written) made to name `path` (under the root) instead:
    a missing entry Find found (R8.7)."""
    new = relative_to(path, folder)
    return replace(p, entries=tuple(
        Entry(new) if e.location.strip() == location.strip() else e for e in p.entries
    ))  # fmt: skip


def repointed(p: Playlist, folder: str, root: str, moves: Mapping[str, str]) -> Playlist | None:
    """Each entry naming a path of `moves` (under the root: old -> new) made to name its new
    path; None when none names one (R8.7, R12.4, R2.12)."""
    out, changed = [], False
    for e in p.entries:
        path = resolve(e.location, folder, root)
        if path is not None and path in moves:
            out.append(Entry(relative_to(moves[path], folder)))
            changed = True
        else:
            out.append(e)
    return replace(p, entries=tuple(out)) if changed else None


def already_in(p: Playlist, paths: Sequence[str], folder: str, root: str) -> int:
    """How many of `paths` (under the root) the playlist in `folder` names already: what R8.5's
    message says of songs added again."""
    there = {resolve(e.location, folder, root) for e in p.entries}
    return sum(1 for x in paths if x in there)


def taken_back(
    p: Playlist, positions: Sequence[int], paths: Sequence[str], folder: str, root: str
) -> tuple[Playlist, int]:
    """R8.5's Undo of an addition: the entries it put at `positions` taken out again, each only
    while it is still there naming its song (`paths`, the same order); the playlist, and how many
    were taken out. One moved or changed since stays."""
    gone = {
        n for n, path in zip(positions, paths, strict=False)
        if 0 <= n < len(p.entries) and resolve(p.entries[n].location, folder, root) == path
    }  # fmt: skip
    return removed(p, gone), len(gone)


def move_order(count: int, positions: Collection[int], before: int) -> list[int]:
    """A reorder by dragging (R8.5): the entries at `positions` (from 0, of `count`) moved, in
    their order, to land above the entry at `before` (`count`: at the end), where the insertion
    line is. The new order, as the old places in it."""
    moving = sorted(n for n in set(positions) if 0 <= n < count)
    kept = [n for n in range(count) if n not in set(moving)]
    at = sum(1 for n in kept if n < before)
    return kept[:at] + moving + kept[at:]


def nudge_order(count: int, positions: Collection[int], by: int) -> list[int]:
    """Ctrl+Shift+↑ / ↓ (R6.9, R18.2): each entry at `positions` moved one place up (`by` -1) or
    down (1), past the entry beside it that isn't moving; a run of them moves together, and one
    at the end it moves towards stays, holding back those behind it. The new order, as the old
    places in it."""
    order = list(range(count))
    chosen = set(positions)
    step = -1 if by < 0 else 1
    for i in range(count) if step < 0 else range(count - 1, -1, -1):
        j = i + step
        if order[i] in chosen and 0 <= j < count and order[j] not in chosen:
            order[i], order[j] = order[j], order[i]
    return order


def reordered(p: Playlist, order: Sequence[int]) -> Playlist:
    """The playlist's entries in `order` (their old places, from 0)."""
    return replace(p, entries=tuple(p.entries[n] for n in order))


def places_of(order: Sequence[int], positions: Collection[int]) -> tuple[int, ...]:
    """Where the entries at `positions` are in `order` (a reorder's): their new places."""
    wanted = set(positions)
    return tuple(n for n, old in enumerate(order) if old in wanted)


# ---------- files dropped from outside (R8.5, R6.10) ----------


def dropped(paths: Iterable[str], root: str) -> tuple[list[str], list[str]]:
    """Files and folders a file manager dropped, by their whole paths: those under the root, as
    their paths under it (with `/`), and those outside it, which R12.5 adds (later), as given."""
    inside, outside = [], []
    for path in paths:
        under = resolve(path, "", root) if path else None
        if under is None:
            outside.append(path)
        else:
            inside.append(under)
    return inside, outside


def songs_dropped(c: sqlite3.Connection, paths: Sequence[str]) -> list[int]:
    """The songs files and folders dropped stand for (their paths under the root), in the order
    dropped: a file's song, a folder's songs beneath it as Folders lists them (R2.9.6); each once,
    and what isn't a song of the index (a cover, a file not scanned yet) passed by."""
    out: dict[int, None] = {}
    for path in paths:
        r = c.execute("SELECT id FROM song WHERE path = ?", (path,)).fetchone()
        if r is not None:
            out[int(r[0])] = None
        elif c.execute("SELECT 1 FROM folder WHERE path = ?", (path,)).fetchone() is not None:
            out.update(dict.fromkeys(folders.songs_beneath(c, path)))
    return list(out)


# ---------- Find (R8.7) ----------


@dataclass(frozen=True)
class Candidate:
    """A song Find offers for a missing entry: its id, path, title, artist and length, and
    whether its file's name is the entry's (`by_name`), its artist and title the entry's
    `#EXTINF` (or its title the file's name's) (`by_tags`)."""

    song: int
    path: str
    title: str
    artist: str
    length: float | None
    by_name: bool
    by_tags: bool


def wanted(location: str, title: str) -> tuple[str, str | None, str | None]:
    """What Find looks for (R8.7): the file's name without its extension, case aside; the
    artist and title of the entry's `#EXTINF` ("Artist - Title"), as likely copies share them
    (duplicates.song_key), when it names both; and a title alone, from the `#EXTINF` or the
    file's name without its track number ("10 - Slack Tide": "Slack Tide")."""
    name = stem(location)
    artist, _, song_title = title.partition(" - ")
    key = duplicates.song_key(artist, song_title) if song_title else None
    alone = song_title or title or TRACK.sub("", name) or name
    return name.casefold(), key, alone.strip().casefold() or None


def candidates(
    location: str,
    title: str,
    seconds: int | None,
    songs: Iterable[tuple[int, str, str | None, str | None, float | None, str | None]],
    limit: int = 20,
) -> list[Candidate]:
    """The songs of `songs` (id, path, title, artist, length, likely copies' key) Find offers for
    the entry at `location` with `#EXTINF` text `title` and length `seconds`: those of the same
    file name, and those of its artist and title (or its title alone), both first, then by name,
    then by tags; each kind by how near its length is, then by path."""
    name, key, alone = wanted(location, title)
    found: dict[int, Candidate] = {}
    for song, path, song_title, artist, length, copy_key in songs:
        by_name = stem(path).casefold() == name
        by_tags = (key is not None and copy_key == key) or (
            alone is not None and (song_title or "").strip().casefold() == alone
        )
        if by_name or by_tags:
            found[song] = Candidate(song, path, song_title or stem(path), artist or "", length,
                                    by_name, by_tags)  # fmt: skip

    def order(c: Candidate) -> tuple[int, float, str]:
        rank = 0 if c.by_name and c.by_tags else 1 if c.by_name else 2
        off = abs((c.length or 0) - seconds) if seconds is not None and c.length else 0.0
        return rank, off, c.path

    return sorted(found.values(), key=order)[:limit]


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find(c: sqlite3.Connection, location: str, title: str, seconds: int | None) -> list[Candidate]:
    """Find (R8.7) in the index: the songs `candidates` offers for a missing entry, looked up by
    the file's name, by likely copies' key and by title."""
    name, key, alone = wanted(location, title)
    cols = "SELECT id, path, title, artist, length, copy_key FROM song"
    rows = list(c.execute(f"{cols} WHERE path LIKE ? ESCAPE '\\'", (f"%{_like(name)}%",)))
    if key is not None:
        rows += c.execute(f"{cols} WHERE copy_key = ?", (key,))
    if alone is not None:
        rows += c.execute(f"{cols} WHERE title = ? COLLATE NOCASE", (alone,))
    return candidates(location, title, seconds, rows)


# ---------- Export (R8.8) ----------


@dataclass(frozen=True)
class Exported:
    """A song as Export writes it: its whole path, artist, title and length."""

    path: str
    artist: str | None
    title: str | None
    seconds: float | None


@dataclass(frozen=True)
class ExportPlan:
    """What Export writes (R8.8): the songs copied (whole path, the copy's file name), the
    playlist's file name and bytes, and how many entries it leaves out (missing)."""

    copies: tuple[tuple[str, str], ...]
    name: str
    playlist: bytes
    skipped: int


def export_plan(name: str, songs: Sequence[Exported | None], how: str) -> ExportPlan:
    """Export's plan of the playlist `name` (R8.8): with ABSOLUTE, an `.m3u8` naming each song by
    its whole path; with COPIES, each song copied numbered in order (`01 - Artist - Title.mp3`,
    three digits past 99) beside an `.m3u8` naming the copies. An entry with no song (None) is
    left out."""
    there = [s for s in songs if s is not None]
    width = max(2, len(str(len(there))))
    entries, copies = [], []
    for n, s in enumerate(there, 1):
        seconds, text = extinf_of(Song(s.path, s.seconds, s.artist, s.title))
        if how == COPIES:
            ext = os.path.splitext(s.path)[1]
            copy = file_name(f"{n:0{width}d} - {text}") + ext
            copies.append((s.path, copy))
            entries.append(Entry(copy, seconds, text))
        else:
            entries.append(Entry(s.path, seconds, text))
    playlist = compose(Playlist(tuple(entries)))
    return ExportPlan(tuple(copies), (file_name(name) or NEW_NAME) + ".m3u8", playlist,
                      len(songs) - len(there))  # fmt: skip


@dataclass
class ExportDone:
    """How an Export went: the songs copied, those already there (the same size), those that
    failed (file name, why), whether it was stopped, and the playlist written (its path; "" when
    it wasn't)."""

    copied: int = 0
    there: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    stopped: bool = False
    playlist: str = ""


def export(
    plan: ExportPlan,
    folder: str,
    progress: Callable[[int, int], object] = lambda done, of: None,
    stop: Callable[[], bool] = lambda: False,
) -> ExportDone:
    """Export's plan carried out into `folder` (R8.8), on the calling thread: each copy made as a
    hidden file and moved into place, so one stopped leaves no half song; a file already there of
    the same size kept, one of another size never written over (it fails, saying so); then the
    playlist, unless `stop` said to stop. `progress(done, of)` after each song."""
    out = ExportDone()
    for n, (source, name) in enumerate(plan.copies):
        if stop():
            out.stopped = True
            return out
        dest = os.path.join(folder, name)
        try:
            if os.path.exists(dest):
                if os.path.getsize(dest) == os.path.getsize(source):
                    out.there += 1
                else:
                    out.failed.append((name, "is there already, another file"))
                continue
            tmp = tmp_path(dest)
            try:
                shutil.copyfile(source, tmp)
                os.replace(tmp, dest)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.remove(tmp)
                raise
            out.copied += 1
        except (OSError, ValueError) as e:
            log.warning("couldn't copy %s to %s: %s", source, dest, e)
            out.failed.append((name, f"couldn't be copied: {getattr(e, 'strerror', None) or e}"))
        finally:
            progress(n + 1, len(plan.copies))
    if stop():
        out.stopped = True
        return out
    path = os.path.join(folder, plan.name)
    try:
        write_file(path, plan.playlist)
        out.playlist = path
    except OSError as e:
        log.warning("couldn't write %s: %s", path, e)
        out.failed.append((plan.name, f"couldn't be written: {e.strerror or e}"))
    return out


# ---------- the index (A2.1) ----------


def index_file(
    c: sqlite3.Connection,
    root: str,
    path: str,
    data: bytes,
    size: int,
    mtime_ns: int,
    legacy: str = "cp1252",
) -> int:
    """In the writer's transaction: the playlist at `path` (under the root) and its entries, from
    its file's `data`, each entry with where it is (`resolve`; None outside the root); its row
    keeps its id when it had one. The playlist's id."""
    kind = kind_of(path) or "m3u8"
    p = parse(data, kind, legacy)
    folder = path.rpartition("/")[0]
    name = name_of(path)
    absolute = sum(not is_relative(e.location) for e in p.entries)
    values = (path, name, sortnames.key_of(name), kind, size, mtime_ns, p.encoding, absolute,
              smart.rule_text_of(p.header))  # fmt: skip
    row = c.execute("SELECT id FROM playlist WHERE path = ?", (path,)).fetchone()
    if row is None:
        c.execute(
            "INSERT INTO playlist (path, name, name_key, kind, size, mtime_ns, encoding, absolute,"
            " rule) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        playlist = int(c.execute("SELECT last_insert_rowid()").fetchone()[0])
    else:
        playlist = int(row[0])
        c.execute(
            "UPDATE playlist SET path = ?, name = ?, name_key = ?, kind = ?, size = ?,"
            " mtime_ns = ?, encoding = ?, absolute = ?, rule = ? WHERE id = ?",
            (*values, playlist),
        )
        c.execute("DELETE FROM playlist_entry WHERE playlist_id = ?", (playlist,))
    c.executemany(
        "INSERT INTO playlist_entry (playlist_id, position, written, path, seconds, title)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [(playlist, n, e.location, resolve(e.location, folder, root), e.seconds, e.title)
         for n, e in enumerate(p.entries)],
    )  # fmt: skip
    return playlist


def forget(c: sqlite3.Connection, paths: Iterable[str]) -> None:
    """In the writer's transaction: the playlists at `paths` (under the root) out of the index,
    with their entries."""
    c.executemany("DELETE FROM playlist WHERE path = ?", [(p,) for p in paths])


@dataclass(frozen=True)
class Found:
    """A playlist file the walk found: its name, size and modification time."""

    name: str
    size: int
    mtime_ns: int


def changes(
    found: Mapping[str, Found], indexed: Mapping[str, tuple[int, int]], answered: Collection[str]
) -> tuple[list[str], list[str]]:
    """What a scan does with the playlists (R8.1.2, R8.1.3): those `found` (by path under the
    root) whose size or modification time differ from their row, or that have none, read; the
    rows of those not found in a folder the scan `answered` for taken out. (read, gone)."""
    read = sorted(p for p, f in found.items() if indexed.get(p) != (f.size, f.mtime_ns))
    gone = sorted(p for p in indexed if p not in found and p.rpartition("/")[0] in answered)
    return read, gone


def full_path(root: str, path: str) -> str:
    """A path under the root (with /) as the system's path."""
    return os.path.join(root, *path.split("/")) if path else root


def refresh(
    root: str,
    index: db.Index,
    found: Mapping[str, Sequence[Found]],
    answered: Callable[[str], bool],
    legacy: str | None = None,
) -> tuple[int, int]:
    """A scan's playlists (R8.1.2): `found`, each folder walked with the playlists in it, read
    into the index when new or changed (`changes`), the files read on the calling thread and
    written in one transaction; those gone from a folder the scan answers for (`answered`)
    taken out. (read, gone)."""
    legacy = legacy or legacy_encoding()
    files = {f"{folder}/{f.name}" if folder else f.name: f for folder, fs in found.items()
             for f in fs}  # fmt: skip
    c = index.read()
    indexed = {str(p): (int(s), int(m)) for p, s, m in
               c.execute("SELECT path, size, mtime_ns FROM playlist")}  # fmt: skip
    folders = {p.rpartition("/")[0] for p in indexed}
    read, gone = changes(files, indexed, {f for f in folders if answered(f)})
    datas: list[tuple[str, bytes, int, int]] = []
    for path in read:
        try:
            with open(full_path(root, path), "rb") as fh:
                data = fh.read()
            st = os.stat(full_path(root, path))
        except OSError as e:
            log.warning("couldn't read the playlist %s: %s", path, e)
            continue
        datas.append((path, data, st.st_size, st.st_mtime_ns))

    def write(c: sqlite3.Connection) -> None:
        forget(c, gone)
        for path, data, size, mtime in datas:
            index_file(c, root, path, data, size, mtime, legacy)

    if datas or gone:
        index.write(write).result()
        log.info("read %d playlists, took out %d", len(datas), len(gone))
    return len(datas), len(gone)


# ---------- MusiKata's own changes (R8.3, R8.4, R8.6, R8.7) ----------


class PlaylistError(Exception):
    """A change to a playlist that couldn't be made, saying why, as the message says it."""


@dataclass(frozen=True)
class Changed:
    """A change made: the playlist's id and name (None and the old name for one removed), and
    how many entries it added, removed, fixed or moved. An addition says where its entries went
    (`positions`), the songs they name (`paths`, under the root), and how many of those the
    playlist named already (`already`, R8.5); a reorder where the entries moved now
    (`positions`)."""

    playlist: int | None
    name: str
    count: int = 0
    positions: tuple[int, ...] = ()
    paths: tuple[str, ...] = ()
    already: int = 0


class Store:
    """The playlists of one root as MusiKata changes them (R8.3 to R8.7): each change reads the
    file again first (so another program's change since isn't lost), makes its plan, writes it in
    R8.1's form whole (`write_file`) and indexes it, one change at a time whichever thread asks.
    New playlists go in `folder` (under the root, R13.6's setting). Raises PlaylistError, saying
    why, when a change can't be made."""

    def __init__(
        self,
        root: str,
        index: db.Index,
        folder: str = FOLDER,
        legacy: str | None = None,
    ) -> None:
        self.root, self.index, self.folder = root, index, folder
        self.legacy = legacy or legacy_encoding()
        self._lock = threading.Lock()

    # ---------- reading ----------

    def _row(self, playlist: int) -> tuple[str, str]:
        r = (
            self.index.read()
            .execute("SELECT path, kind FROM playlist WHERE id = ?", (playlist,))
            .fetchone()
        )
        if r is None:
            raise PlaylistError("That playlist isn't there any more")
        return str(r[0]), str(r[1])

    def _read(self, path: str) -> Playlist:
        try:
            with open(full_path(self.root, path), "rb") as f:
                data = f.read()
        except OSError as e:
            raise PlaylistError(f"{name_of(path)} couldn't be read: {e.strerror or e}") from e
        return parse(data, kind_of(path) or "m3u8", self.legacy)

    def _songs(self, paths: Iterable[str]) -> dict[str, Song]:
        c = self.index.read()
        wanted = sorted({p for p in paths if p})
        out: dict[str, Song] = {}
        for n in range(0, len(wanted), CHUNK):
            part = wanted[n : n + CHUNK]
            marks = ", ".join("?" * len(part))
            for path, length, artist, title in c.execute(
                f"SELECT path, length, artist, title FROM song WHERE path IN ({marks})", part
            ):
                out[path] = Song(path, length, artist, title)
        return out

    def paths_of(self, songs: Sequence[int]) -> list[str]:
        """The paths of `songs` (by id) in their order, those not in the index left out."""
        c = self.index.read()
        found: dict[int, str] = {}
        for n in range(0, len(songs), CHUNK):
            part = list(songs[n : n + CHUNK])
            marks = ", ".join("?" * len(part))
            found.update(
                (int(i), str(p))
                for i, p in c.execute(f"SELECT id, path FROM song WHERE id IN ({marks})", part)
            )
        return [found[s] for s in songs if s in found]

    def _taken(self, folder: str) -> list[str]:
        """The names of the playlists in `folder`, and of the files there by those names."""
        try:
            names = os.listdir(full_path(self.root, folder))
        except OSError:
            names = []
        return [os.path.splitext(n)[0] for n in names]

    # ---------- writing ----------

    def _write(self, path: str, p: Playlist, kind: str) -> int:
        """`p` written as the playlist at `path` in R8.1's form and indexed: its id."""
        folder = path.rpartition("/")[0]
        known = self._songs(filter(None, (resolve(e.location, folder, self.root)
                                          for e in p.entries)))  # fmt: skip
        data = compose(normal(p, folder, self.root, known),
                       p.encoding if kind == "m3u" else "utf-8")  # fmt: skip
        full = full_path(self.root, path)
        try:
            st = write_file(full, data)
        except OSError as e:
            raise PlaylistError(f"{name_of(path)} couldn't be written: {e.strerror or e}") from e
        root, legacy = self.root, self.legacy
        return self.index.write(
            lambda c: index_file(c, root, path, data, st.st_size, st.st_mtime_ns, legacy)
        ).result()

    @staticmethod
    def _plain(path: str, p: Playlist) -> None:
        """Refuses a change by hand to a smart playlist (R8.9): its rule chooses its songs."""
        reading = smart.reading_of(smart.rule_text_of(p.header))
        if reading is not None and reading.smart:
            raise PlaylistError(f"{name_of(path)} is a smart playlist: its rule chooses its songs")

    def _change(self, playlist: int, plan: Callable[[Playlist, str], Playlist]) -> int:
        with self._lock:
            path, kind = self._row(playlist)
            p = self._read(path)
            self._plain(path, p)
            return self._write(path, plan(p, path.rpartition("/")[0]), kind)

    def _new_path(self, name: str, folder: str) -> str:
        made = file_name(name) or NEW_NAME
        made = unique(made, self._taken(folder))
        return f"{folder}/{made}.m3u8" if folder else f"{made}.m3u8"

    def create(self, songs: Sequence[int] = (), name: str = NEW_NAME) -> Changed:
        """A new playlist (R8.3) in the playlists folder, made when it isn't there: `name`, or
        numbered when taken ("New playlist 2"), holding `songs` (by id) in order."""
        with self._lock:
            try:
                os.makedirs(full_path(self.root, self.folder), exist_ok=True)
            except OSError as e:
                why = f"The playlists folder couldn't be made: {e.strerror or e}"
                raise PlaylistError(why) from e
            path = self._new_path(name, self.folder)
            paths = self.paths_of(songs)
            playlist = self._write(path, added(Playlist(), paths, self.folder), "m3u8")
            return Changed(playlist, name_of(path), len(paths))

    def create_smart(self, rule: smart.Rule, paths: Sequence[str], name: str) -> Changed:
        """A new smart playlist (R8.9) in the playlists folder: `name`, numbered when taken, its
        rule in its `#MUSIKATA-RULE:` line, holding `paths` (under the root: the rule's songs)."""
        with self._lock:
            try:
                os.makedirs(full_path(self.root, self.folder), exist_ok=True)
            except OSError as e:
                why = f"The playlists folder couldn't be made: {e.strerror or e}"
                raise PlaylistError(why) from e
            path = self._new_path(name, self.folder)
            made = added(Playlist(header=(smart.rule_line(rule),)), paths, self.folder)
            playlist = self._write(path, made, "m3u8")
            return Changed(playlist, name_of(path), len(paths))

    def set_rule(self, playlist: int, rule: smart.Rule, paths: Sequence[str]) -> Changed:
        """Edit rule (R8.9): the playlist's rule made `rule`, and its songs `paths` (the rule's);
        a plain playlist given a rule becomes a smart one. A newer MusiKata's rule is refused."""
        with self._lock:
            path, kind = self._row(playlist)
            p = self._read(path)
            reading = smart.reading_of(smart.rule_text_of(p.header))
            if reading is not None and reading.kind == smart.NEWER:
                raise PlaylistError(f"{name_of(path)}'s rule is a newer MusiKata's: update to"
                                    " change it")  # fmt: skip
            folder = path.rpartition("/")[0]
            made = added(replace(p, entries=(), header=smart.with_rule(p.header, rule)), paths,
                         folder)  # fmt: skip
            written = self._write(path, made, kind)
            return Changed(written, name_of(path), len(paths))

    def refill(self, playlist: int, text: str, paths: Sequence[str]) -> bool:
        """A smart playlist kept current (R8.9): its entries made `paths` (under the root), when
        its file still holds the rule `text` (one changed since is the scan's to read again) and
        its entries name other songs, or the same in another order; never written when they
        don't. Whether it was written."""
        with self._lock:
            path, kind = self._row(playlist)
            p = self._read(path)
            if smart.rule_text_of(p.header) != text.strip():
                return False
            folder = path.rpartition("/")[0]
            there = [resolve(e.location, folder, self.root) for e in p.entries]
            if not smart.changed(there, paths):
                return False
            self._write(path, added(replace(p, entries=()), paths, folder), kind)
            log.info("kept the smart playlist %s current: %d songs", path, len(paths))
            return True

    def add(self, playlist: int, songs: Sequence[int]) -> Changed:
        """`songs` (by id) added at the playlist's end (R8.5: Add to playlist, and songs dropped
        on it), those it names already added again; where they went and how many were there
        already, for the message and its Undo (`take_back`)."""
        paths = self.paths_of(songs)
        seen: dict[str, int] = {}

        def plan(p: Playlist, folder: str) -> Playlist:
            seen["start"] = len(p.entries)
            seen["already"] = already_in(p, paths, folder, self.root)
            return added(p, paths, folder)

        written = self._change(playlist, plan)
        start = seen["start"]
        return Changed(written, self.name(written), len(paths),
                       tuple(range(start, start + len(paths))), tuple(paths),
                       seen["already"])  # fmt: skip

    def take_back(self, playlist: int, positions: Sequence[int], paths: Sequence[str]) -> Changed:
        """R8.5's Undo of an addition (`add`'s `positions` and `paths`): those entries taken out
        again, each while it is still where it went naming its song; how many were."""
        taken: dict[str, int] = {}

        def plan(p: Playlist, folder: str) -> Playlist:
            out, taken["n"] = taken_back(p, positions, paths, folder, self.root)
            return out

        written = self._change(playlist, plan)
        return Changed(written, self.name(written), taken["n"])

    def _places(self, playlist: int, entries: Collection[int]) -> dict[int, str]:
        """The entries `entries` (ids in the index) by their place, with what each names as
        written: what a change matches the file against again."""
        if not entries:
            return {}
        c = self.index.read()
        return {int(p): str(w) for p, w in c.execute(
            "SELECT position, written FROM playlist_entry WHERE playlist_id = ? AND id IN"
            f" ({', '.join('?' * len(entries))})", (playlist, *entries)
        )}  # fmt: skip

    @staticmethod
    def _still(p: Playlist, rows: Mapping[int, str]) -> set[int]:
        return {n for n, w in rows.items() if n < len(p.entries) and p.entries[n].location == w}

    def remove(self, playlist: int, entries: Collection[int]) -> Changed:
        """The entries `entries` (their ids in the index) taken out (R8.6); each is matched to the
        file again by its place and what it names, so one another program moved since stays."""
        rows = self._places(playlist, entries)
        written = self._change(playlist, lambda p, _folder: removed(p, self._still(p, rows)))
        return Changed(written, self.name(written), len(rows))

    def _reorder(
        self, playlist: int, entries: Collection[int], order: Callable[[int, set[int]], list[int]]
    ) -> Changed:
        """The entries `entries` put in the order `order` makes of the playlist's length and their
        places (those still there, as `remove` matches them); a playlist that order leaves as it
        is isn't written (R8.1.2: one read from elsewhere keeps its form)."""
        rows = self._places(playlist, entries)
        with self._lock:
            path, kind = self._row(playlist)
            p = self._read(path)
            self._plain(path, p)
            there = self._still(p, rows)
            new = order(len(p.entries), there)
            places = places_of(new, there)
            if new != list(range(len(p.entries))):
                playlist = self._write(path, reordered(p, new), kind)
        return Changed(playlist, self.name(playlist), len(places), places)

    def move(self, playlist: int, entries: Collection[int], before: int) -> Changed:
        """The entries `entries` (ids in the index) moved, in their order, above the entry at
        place `before` (from 0; past the last: to the end), where the insertion line was (R8.5);
        each matched to the file again as `remove` does. Where they are now."""
        return self._reorder(playlist, entries, lambda n, there: move_order(n, there, before))

    def nudge(self, playlist: int, entries: Collection[int], by: int) -> Changed:
        """The entries `entries` moved one place up (`by` -1) or down (1): Ctrl+Shift+↑ / ↓
        (R6.9, R18.2). Where they are now."""
        return self._reorder(playlist, entries, lambda n, there: nudge_order(n, there, by))

    def fix(self, playlist: int, location: str, song: int) -> Changed:
        """Each entry naming `location` made to name `song` (by id) instead (R8.7's Find)."""
        paths = self.paths_of([song])
        if not paths:
            raise PlaylistError("That song isn't in the library any more")
        written = self._change(playlist, lambda p, folder: fixed(p, location, paths[0], folder))
        return Changed(written, self.name(written), 1)

    def rename(self, playlist: int, name: str) -> Changed:
        """The playlist renamed, its file with it (R8.4): in its folder, by a name a file can
        have; a name another playlist there has is refused."""
        with self._lock:
            path, kind = self._row(playlist)
            folder = path.rpartition("/")[0]
            made = file_name(name)
            if not made:
                raise PlaylistError("A playlist needs a name")
            if made == name_of(path):
                return Changed(playlist, made)
            others = [t for t in self._taken(folder) if t.casefold() != name_of(path).casefold()]
            if made.casefold() in {t.casefold() for t in others}:
                raise PlaylistError(f"There is a playlist called {made} already")
            ext = os.path.splitext(path)[1]
            new = f"{folder}/{made}{ext}" if folder else f"{made}{ext}"
            try:
                os.rename(full_path(self.root, path), full_path(self.root, new))
                st = os.stat(full_path(self.root, new))
            except OSError as e:
                why = f"{name_of(path)} couldn't be renamed: {e.strerror or e}"
                raise PlaylistError(why) from e
            self.index.write(lambda c: c.execute(
                "UPDATE playlist SET path = ?, name = ?, name_key = ?, size = ?, mtime_ns = ?"
                " WHERE id = ?",
                (new, made, sortnames.key_of(made), st.st_size, st.st_mtime_ns, playlist),
            )).result()  # fmt: skip
            log.info("renamed the playlist %s to %s", path, new)
            return Changed(playlist, made)

    def duplicate(self, playlist: int) -> Changed:
        """A copy of the playlist beside it, as it is (R8.4): "Road Trip copy"."""
        with self._lock:
            path, _kind = self._row(playlist)
            folder = path.rpartition("/")[0]
            made = copy_name(name_of(path), self._taken(folder))
            ext = os.path.splitext(path)[1]
            new = f"{folder}/{made}{ext}" if folder else f"{made}{ext}"
            try:
                with open(full_path(self.root, path), "rb") as f:
                    data = f.read()
                st = write_file(full_path(self.root, new), data)
            except OSError as e:
                why = f"{name_of(path)} couldn't be copied: {e.strerror or e}"
                raise PlaylistError(why) from e
            root, legacy = self.root, self.legacy
            copy = self.index.write(
                lambda c: index_file(c, root, new, data, st.st_size, st.st_mtime_ns, legacy)
            ).result()
            return Changed(copy, made)

    def delete(self, playlist: int, trash: Callable[[str], bool]) -> Changed:
        """The playlist's file moved to the system's trash (R8.4; asked first, R6.8), and taken
        out of the index; the songs it named are untouched."""
        with self._lock:
            path, _kind = self._row(playlist)
            full = full_path(self.root, path)
            if os.path.exists(full) and not trash(full):
                raise PlaylistError(f"{name_of(path)} couldn't be moved to the trash")
            self.index.write(lambda c: forget(c, [path])).result()
            log.info("moved the playlist %s to the trash", path)
            return Changed(None, name_of(path))

    def name(self, playlist: int) -> str:
        r = (
            self.index.read()
            .execute("SELECT name FROM playlist WHERE id = ?", (playlist,))
            .fetchone()
        )
        return str(r[0]) if r else ""

    def repoint(self, moves: Mapping[str, str]) -> list[str]:
        """Every playlist naming a path of `moves` (under the root: old -> new) made to name the
        new one, written and indexed, in one step with the move that calls it: Organize files'
        moves (R12.4, R8.7) and R2.12's copies moved to the trash, pointed at the copy kept. The
        paths of the playlists written; one that can't be is logged and passed by."""
        if not moves:
            return []
        c = self.index.read()
        olds = sorted(moves)
        ids: set[int] = set()
        for n in range(0, len(olds), CHUNK):
            part = olds[n : n + CHUNK]
            marks = ", ".join("?" * len(part))
            ids.update(int(i) for (i,) in c.execute(
                f"SELECT DISTINCT playlist_id FROM playlist_entry WHERE path IN ({marks})", part
            ))  # fmt: skip
        done = []
        for playlist in sorted(ids):
            with self._lock:
                try:
                    path, kind = self._row(playlist)
                    p = repointed(self._read(path), path.rpartition("/")[0], self.root, moves)
                    if p is not None:
                        self._write(path, p, kind)
                        done.append(path)
                except PlaylistError as e:
                    log.warning("a playlist naming a moved file wasn't changed: %s", e)
        if done:
            log.info("pointed %d playlists at the files moved", len(done))
        return done
