"""The scan (A2.2, R2.3): walk the root, compare each audio file's size and modification time with
its row, read the changed and new ones on the worker processes in batches, write each batch in one
transaction, with its rows of the search index (A2.5), and remove what's gone, unless it reappears
elsewhere with the same audio hash, which is a move: its row keeps its id and the plays that hang
on it.

A partial scan (A2.4) does the same for the folders a watched change named (`Scope`): each named
folder's own files, and the folders new under it, walked whole; the folders already known (walked
before, and watched) are passed by, as their own watches report their changes. A move still has
two ends when only one is in the scope: a new file takes the row of a song with its hash whose file
is gone from wherever it was, and a song whose file went takes the row of a copy of it made while
watching (a move by copying, then removing: `copied`).

What a scan doesn't do (R2.10): take a root that isn't there for a root whose songs were all
removed, or a folder joined by a link that leads nowhere (R2.3.2) for one whose songs were; their
rows stay as they were, and the result says so. And a scan that finds more than a quarter of the
library's songs gone, and more than 20, holds their removal (`Result.held`) until the user answers
(R2.10.1), since a folder renamed or a share half mounted looks the same as songs deleted; `remove`
takes them out then. Fewer are taken out without asking."""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import stat
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from concurrent.futures import Executor
from dataclasses import dataclass, field
from typing import BinaryIO, Literal

from . import albums, art, db, folders, search, sortnames
from .clock import Clock, SystemClock
from .tags import EXTENSIONS, AudioInfo, TagReadError, Tags, Written, is_leftover
from .tags import read as read_tags
from .tags.safe import remove_stale

log = logging.getLogger(__name__)
BATCH = 200  # files read and written at a time (A2.2)
HASHED = 64 * 1024  # bytes of audio at each end the audio hash reads (A2.3)
IGNORE = ".musikataignore"  # a folder holding one is skipped (R2.3.1)
ASK_OVER = 20  # more songs gone than this, and over a quarter, wait on the user (R2.10.1)
# told of each folder a walk lists: its path under the root, its real path, its modification time
Reached = Callable[[str, str, int], None]


@dataclass(frozen=True)
class Seen:
    """A file the walk found: its path under the root (with /), size and modification time."""

    path: str
    size: int
    mtime_ns: int


@dataclass
class Plan:
    """What a scan does: the files to read, and the rows whose file wasn't seen."""

    read: list[Seen] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Read:
    """A file read on a worker: its tags and audio, or why it couldn't be."""

    seen: Seen
    tags: Tags | None = None
    info: AudioInfo | None = None
    audio_hash: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class Scope:
    """A partial scan's folders (A2.4): those named (paths under the root, "" for the root), and
    the folders known, walked before and watched, each with its real path. A known folder under a
    named one is passed by unless it is named too; one that isn't there any more is gone."""

    folders: frozenset[str]
    known: Mapping[str, str] = field(default_factory=dict)


@dataclass
class Tree:
    """What a walk went through: each folder it walked (its path under the root, and its real
    path), the known folders it passed by, the real paths walked, so that a link leading back
    to one is skipped (R2.3.2), and the links to folders that can't be reached (R2.10)."""

    folders: dict[str, str] = field(default_factory=dict)
    passed: set[str] = field(default_factory=set)
    reals: set[str] = field(default_factory=set)
    unreachable: set[str] = field(default_factory=set)  # links leading nowhere (R2.10)


@dataclass
class Result:
    """What a scan did, in counts, and for watching (A2.4): the folders it walked (path under the
    root -> real path), the known ones it found gone, the files it read, and the copies made while
    watching that a later scan may find were moves (audio hash -> path). And what it left alone
    (R2.10): `missing`, the root wasn't there, so nothing changed; `unreachable`, the links (paths
    under the root) to folders that couldn't be reached, whose songs stay; `held`, the songs gone
    whose removal waits on the user (R2.10.1), of the `songs` the library had."""

    added: int = 0
    changed: int = 0
    moved: int = 0
    removed: int = 0
    unreadable: int = 0
    unchanged: int = 0
    folders: dict[str, str] = field(default_factory=dict, repr=False)
    gone_folders: set[str] = field(default_factory=set, repr=False)
    read: list[Seen] = field(default_factory=list, repr=False)
    copied: dict[str, str] = field(default_factory=dict, repr=False)
    missing: bool = False
    unreachable: set[str] = field(default_factory=set)
    held: list[str] = field(default_factory=list, repr=False)
    songs: int = 0


# ---------- walking ----------


def _hidden(entry: os.DirEntry[str]) -> bool:
    """Hidden: a leading "." on Linux and macOS, the hidden attribute on Windows (R2.3.1)."""
    if entry.name.startswith("."):
        return True
    return _hidden_attribute(entry.stat(follow_symlinks=False))


def _hidden_attribute(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0))


def _link(path: str) -> bool:
    """A symbolic link, or a Windows junction (R2.3.2)."""
    return os.path.islink(path) or bool(getattr(os.path, "isjunction", bool)(path))


def full_path(root: str, rel: str) -> str:
    """A path under the root (with /, "" for the root itself) as the system's path."""
    return os.path.join(root, *rel.split("/")) if rel else root


def walk(
    root: str,
    skip: Iterable[str] = (),
    images: dict[str, list[art.Image]] | None = None,
    *,
    start: str = "",
    known: Collection[str] = (),
    tree: Tree | None = None,
    reached: Reached | None = None,
    now: float | None = None,
) -> Iterator[Seen]:
    """Every audio file under root (R2.2's kinds), skipping hidden files and folders, folders
    holding .musikataignore, the folders the settings skip (paths under the root), and the root's
    .musikata (R2.3.1). The copies a safe write left behind (A3.4; tags.is_leftover), hidden too,
    are removed when they were last touched long enough before `now`, a time (none: kept). Links
    are followed like folders; one leading back to a folder already walked is skipped, and the
    log says so (R2.3.2). `images`, when given, gets each folder walked (with no images: an empty
    list) and its images (R5.1's kinds), for its albums' covers.

    A partial scan (A2.4) walks from `start`, a folder under the root, and passes by the folders
    `known` under it; `tree`, when given, gets the folders walked and passed, and its real paths
    count as walked already. `reached`, when given, is told of each folder as it is listed: its
    path under the root, its real path, and its modification time just before (for watching it,
    A2.4)."""
    skipped = {s.strip("/") for s in skip}
    tree = tree if tree is not None else Tree()

    def go(folder: str, rel: str) -> Iterator[Seen]:
        real = os.path.realpath(folder)
        if real in tree.reals:
            log.info("skipped %s: it leads back to %s, already walked", rel or ".", real)
            return
        tree.reals.add(real)
        try:
            listed = os.stat(folder).st_mtime_ns
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError as e:
            if rel and _link(folder):  # a share behind a link, gone to sleep (R2.10)
                tree.unreachable.add(rel)
                log.warning("the linked folder %s can't be reached: %s; its songs are kept", rel, e)
            else:
                log.warning("couldn't read %s: %s", rel or ".", e)
            return
        if any(entry.name == IGNORE for entry in entries):
            return
        tree.folders[rel] = real
        if reached is not None:
            reached(rel, real, listed)
        if images is not None:
            images.setdefault(rel, [])
        for entry in entries:
            path = f"{rel}/{entry.name}" if rel else entry.name
            if now is not None and is_leftover(entry.name) and not entry.is_dir():
                remove_stale(entry.path, now)
                continue
            if _hidden(entry) or path in skipped:
                continue
            try:
                if entry.is_dir():  # follows links (R2.3.2)
                    if path in known:
                        tree.passed.add(path)
                    else:
                        yield from go(entry.path, path)
                elif os.path.splitext(entry.name)[1].lower() in EXTENSIONS:
                    st = entry.stat()
                    yield Seen(path, st.st_size, st.st_mtime_ns)
                elif art.is_image(entry.name):
                    if images is not None:
                        st = entry.stat()
                        images[rel].append(art.Image(entry.name, st.st_size, st.st_mtime_ns))
                elif _link(entry.path) and not os.path.exists(entry.path):
                    # a link to a folder whose drive isn't there: its songs are kept (R2.10)
                    tree.unreachable.add(path)
                    log.warning("the linked folder %s can't be reached; its songs are kept", path)
            except OSError as err:
                log.warning("couldn't read %s: %s", path, err)

    yield from go(full_path(root, start), start)


def outside(root: str, folder: str, skip: Iterable[str] = ()) -> bool:
    """Whether a folder under the root is out of the library now: not there, or it or a folder
    above it hidden, skipped by the settings or holding .musikataignore (R2.3.1)."""
    skipped = {s.strip("/") for s in skip}
    if not os.path.isdir(root) or os.path.exists(os.path.join(root, IGNORE)):
        return True
    parts = folder.split("/") if folder else []
    for n, name in enumerate(parts):
        path = full_path(root, "/".join(parts[: n + 1]))
        if name.startswith(".") or "/".join(parts[: n + 1]) in skipped:
            return True
        try:
            if _hidden_attribute(os.stat(path, follow_symlinks=False)):
                return True  # pragma: no cover - Windows' hidden attribute: tier 3 (R2.3.1)
        except OSError:
            return True  # not there
        if not os.path.isdir(path) or os.path.exists(os.path.join(path, IGNORE)):
            return True
    return False


def unreachable_link(root: str, folder: str) -> str | None:
    """The link at or above `folder` (a path under the root) that leads nowhere, if there is one
    (R2.10): the folder it joins (R2.3.2) can't be reached."""
    parts = folder.split("/") if folder else []
    for n in range(len(parts)):
        path = "/".join(parts[: n + 1])
        full = full_path(root, path)
        if _link(full) and not os.path.exists(full):
            return path
    return None


def under(path: str, folders: Collection[str]) -> bool:
    """Whether `path` (under the root) is in one of `folders` or beneath it."""
    return any(path == f or path.startswith(f + "/") for f in folders)


def walk_scope(
    root: str,
    scope: Scope,
    skip: Iterable[str] = (),
    images: dict[str, list[art.Image]] | None = None,
    tree: Tree | None = None,
    reached: Reached | None = None,
    now: float | None = None,
) -> Iterator[Seen]:
    """The audio files a partial scan sees (A2.4): each named folder's own files and those of the
    folders new under it, each named folder walked once, whether named or found new under another.
    A named folder out of the library now (`outside`) is walked not at all. `reached` and `now`:
    as for `walk`."""
    tree = tree if tree is not None else Tree()
    named = sorted(scope.folders)
    # the known folders count as walked (R2.3.2), but for the named ones, walked again here
    tree.reals |= set(scope.known.values()) - {os.path.realpath(full_path(root, f)) for f in named}
    for folder in named:
        link = unreachable_link(root, folder)
        if link is not None:  # behind a link that leads nowhere now: its songs are kept (R2.10)
            tree.unreachable.add(link)
            continue
        if folder in tree.folders or outside(root, folder, skip):
            continue
        yield from walk(
            root, skip, images, start=folder, known=scope.known, tree=tree, reached=reached, now=now
        )
    tree.passed -= set(tree.folders)


def in_scope(folder: str, scope: Scope, tree: Tree) -> bool:
    """Whether a partial scan answers for what is in `folder`: a folder it walked, or one under a
    named folder that no known folder it passed by holds (a folder gone, or out of the library)."""
    if folder in tree.folders:
        return True
    while True:
        if folder in scope.folders:
            return True
        if folder in tree.passed or not folder:
            return False
        folder = folder.rpartition("/")[0]


def plan(
    seen: Iterable[Seen],
    indexed: Mapping[str, tuple[int, int]],
    expected: Mapping[str, tuple[int, int]] | None = None,
) -> Plan:
    """The files whose size or modification time differ from their row, or that have none, and
    the rows no file was seen for (R2.3: an unchanged file costs one stat). A file `expected` with
    that size and modification time (MusiKata's own write, A2.4) isn't read: the write updates its
    row itself."""
    p = Plan()
    found: set[str] = set()
    expected = expected or {}
    for s in seen:
        found.add(s.path)
        now = (s.size, s.mtime_ns)
        if indexed.get(s.path) != now and expected.get(s.path) != now:
            p.read.append(s)
    p.gone = sorted(set(indexed) - found)
    return p


# ---------- the audio hash (A2.3) ----------


def audio_range(f: BinaryIO, size: int, kind: str) -> tuple[int, int]:
    """Where a file's audio is, without its tag blocks: (start, end) in bytes. Retagging a file
    doesn't move what's between them, so the hash of A2.3 stays the same."""
    head = f.read(min(size, 1 << 16))
    start, end = 0, size
    if kind == "mp3":
        if head[:3] == b"ID3" and len(head) >= 10:
            start = 10 + _synchsafe(head[6:10]) + (10 if head[5] & 0x10 else 0)
        f.seek(max(0, size - 128))
        if f.read(3) == b"TAG":
            end = size - 128
        f.seek(max(0, end - 32))
        footer = f.read(32)
        if footer[:8] == b"APETAGEX":
            end -= int.from_bytes(footer[12:16], "little") + (32 if footer[23] & 0x80 else 0)
    elif kind == "flac":
        start = _flac_audio(f)
    elif kind in ("aac", "alac", "m4a"):
        start, end = _chunk(f, size, b"mdat", "mp4", at=0)
    elif kind == "wav":
        start, end = _chunk(f, size, b"data", "riff", at=12)
    elif kind == "aiff":
        start, end = _chunk(f, size, b"SSND", "iff", at=12)
    elif kind in ("vorbis", "opus"):
        start = _ogg_audio(f, size)
    return min(start, size), max(min(end, size), min(start, size))


def _synchsafe(b: bytes) -> int:
    return (b[0] & 127) << 21 | (b[1] & 127) << 14 | (b[2] & 127) << 7 | (b[3] & 127)


def _flac_audio(f: BinaryIO) -> int:
    f.seek(4)
    pos = 4
    while True:
        h = f.read(4)
        if len(h) < 4:
            return pos
        pos += 4 + int.from_bytes(h[1:4], "big")
        if h[0] & 0x80:  # the last metadata block
            return pos
        f.seek(pos)


def _chunk(f: BinaryIO, size: int, cid: bytes, layout: str, at: int) -> tuple[int, int]:
    """The body of the first top-level chunk named cid, from byte `at`. `layout` is "mp4" (a
    big-endian size counting its header, then the name; 1 means a 64-bit size follows), "riff"
    (the name, then a little-endian size of the body, padded to even) or "iff" (the same,
    big-endian: AIFF)."""
    pos = at
    while pos + 8 <= size:
        f.seek(pos)
        h = f.read(8)
        if len(h) < 8:
            break
        if layout == "mp4":
            name, n, head = h[4:8], int.from_bytes(h[:4], "big"), 8
            if n == 1:
                n, head = int.from_bytes(f.read(8), "big"), 16
            if name == cid:
                return pos + head, min(size, pos + n)
            if n < head:
                break
            pos += n
        else:
            order: Literal["big", "little"] = "little" if layout == "riff" else "big"
            name, n = h[:4], int.from_bytes(h[4:8], order)
            if name == cid:
                return pos + 8, min(size, pos + 8 + n)
            pos += 8 + n + (n & 1)
    return 0, size


def _ogg_audio(f: BinaryIO, size: int) -> int:
    """The first Ogg page whose granule position isn't 0: the header pages, where the comments
    are, all have 0."""
    pos = 0
    while pos + 27 <= size:
        f.seek(pos)
        h = f.read(27)
        if h[:4] != b"OggS" or len(h) < 27:
            break
        segments = f.read(h[26])
        if int.from_bytes(h[6:14], "little") not in (0, (1 << 64) - 1):
            return pos
        pos += 27 + h[26] + sum(segments)
    return 0


def audio_hash(path: str, kind: str) -> str:
    """A2.3's hash: the first and last 64 KB of the audio, and its length, so retagging a file
    doesn't change it and two copies of a song match."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        start, end = audio_range(f, size, kind)
        h = hashlib.sha256((end - start).to_bytes(8, "little"))
        f.seek(start)
        h.update(f.read(min(HASHED, end - start)))
        if end - start > HASHED:
            f.seek(max(start + HASHED, end - HASHED))
            h.update(f.read(end - max(start + HASHED, end - HASHED)))
    return h.hexdigest()


# ---------- reading and writing ----------


def read_one(root: str, seen: Seen) -> Read:
    """A worker's job (docs/process/coding.md, "Jobs are plain functions"): one file's tags and
    audio hash, or why they couldn't be read."""
    path = os.path.join(root, *seen.path.split("/"))
    try:
        t, info = read_tags(path)
        return Read(seen, t, info, audio_hash(path, info.kind))
    except TagReadError as e:
        return Read(seen, error=str(e))
    except OSError as e:
        return Read(seen, error=e.strerror or str(e))
    except Exception as e:  # noqa: BLE001  (a file no reader expected: listed, and the scan goes on)
        log.exception("reading %s", path)
        return Read(seen, error=f"{type(e).__name__}: {e}")


def _place(path: str) -> dict[str, object]:
    """A song's folder and its file name's sort key (R2.9.2), for the Folders view (A2.7)."""
    folder, _, name = path.rpartition("/")
    return {"folder": folder, "name_key": sortnames.key_of(name)}


def _values(r: Read) -> dict[str, object]:
    t = r.tags or Tags()
    i = r.info
    row: dict[str, object] = {
        "path": r.seen.path, "size": r.seen.size, "mtime_ns": r.seen.mtime_ns,
        "kind": i.kind if i else None, "length": i.length if i else None,
        "bitrate": i.bitrate if i else None, "sample_rate": i.sample_rate if i else None,
        "channels": i.channels if i else None, "audio_hash": r.audio_hash, "error": r.error,
        **_place(r.seen.path),
    }  # fmt: skip
    row.update({name: getattr(t, name) for name in db.FIELDS})
    return row


def write_batch(
    c: sqlite3.Connection,
    batch: list[Read],
    moves: dict[str, str],
    images: Mapping[str, list[art.Image]] | None = None,
) -> Result:
    """One batch into the index, in the writer's transaction: each file's row added or replaced,
    or, for a new path whose audio hash a gone row has (`moves`: hash -> old path), that row moved
    here (A2.2, step 4); and the albums and artists those songs left or joined summarized again
    (R2.5), with `images`, each folder's images, for their covers, then the folders they left or
    joined and those above them (A2.7)."""
    res = Result()
    touched = albums.Touched()
    places: set[str] = set()
    written: list[int] = []
    for r in batch:
        values = _values(r)
        old = moves.pop(r.audio_hash, None) if r.audio_hash else None
        row = c.execute("SELECT id FROM song WHERE path = ?", (old or r.seen.path,)).fetchone()
        places.update(albums.folder_of(p) for p in (old or r.seen.path, r.seen.path))
        if row:
            sets = ", ".join(f"{k} = :{k}" for k in values)
            c.execute(f"UPDATE song SET {sets} WHERE id = :id", {**values, "id": row[0]})
            song_id = row[0]
            if old:
                res.moved += 1
            else:
                res.changed += 1
        else:
            cols = ", ".join(values)
            c.execute(
                f"INSERT INTO song ({cols}) VALUES ({', '.join(':' + k for k in values)})", values
            )
            song_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            res.added += 1
        res.unreadable += r.error is not None
        c.execute("DELETE FROM song_genre WHERE song_id = ?", (song_id,))
        for n, g in enumerate(r.tags.genres if r.tags else ()):
            c.execute("INSERT INTO song_genre VALUES (?, ?, ?)", (song_id, n, g))
        albums.place(c, song_id, touched)
        written.append(song_id)
    search.index_songs(c, written)
    albums.refresh(c, touched, images)
    places |= albums.folders_of(c, touched.albums)  # an album's cover changed through another
    folders.refresh(c, places, images)
    return res


def wrote(c: sqlite3.Connection, root: str, written: Iterable[Written]) -> Result:
    """In the writer's transaction: the rows of the songs MusiKata wrote itself (A2.4; tags.save),
    each updated from what its file was read back as, with the size and modification time the
    write left it with, so no scan reads it again (`plan`). A file outside the root is passed
    by, and the log says so."""
    batch = []
    for w in written:
        rel = path_under(root, w.path)
        if rel is None:
            log.warning("didn't index %s: it isn't under %s", w.path, root)
            continue
        batch.append(Read(Seen(rel, w.size, w.mtime_ns), w.tags, w.info, w.audio_hash))
    return write_batch(c, batch, {})


def path_under(root: str, path: str) -> str | None:
    """A file's path under the root, with /, as the index holds it; None when it isn't under it
    (on another drive, on Windows, included)."""
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return None
    if rel == os.curdir or rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return rel.replace(os.sep, "/")


# a song's row but its id and path: what a take-over (`take_over`) copies from the copy's row
ROW = ("size", "mtime_ns", "kind", "length", "bitrate", "sample_rate", "channels", "audio_hash",
       "error", *db.FIELDS)  # fmt: skip


def take_over(c: sqlite3.Connection, old: str, new: str, touched: albums.Touched) -> bool:
    """A move by copying, then removing (A2.2, A2.4): the row of the song at `old`, whose file
    went, becomes the song at `new`, a copy of it made while watching, which loses its own row; so
    the song keeps its id, and what hangs on it. False when either row isn't there."""
    keep = c.execute("SELECT id FROM song WHERE path = ?", (old,)).fetchone()
    copy = c.execute("SELECT id FROM song WHERE path = ?", (new,)).fetchone()
    if keep is None or copy is None:
        return False
    values = c.execute(f"SELECT {', '.join(ROW)} FROM song WHERE id = ?", copy).fetchone()
    genres = [g for (g,) in c.execute(
        "SELECT genre FROM song_genre WHERE song_id = ? ORDER BY position", copy
    )]  # fmt: skip
    albums.forget(c, [new], touched)
    c.execute("DELETE FROM song_fts WHERE rowid = ?", copy)
    c.execute("DELETE FROM song WHERE id = ?", copy)
    sets = ", ".join(f"{k} = ?" for k in ROW)
    place = _place(new)
    c.execute(
        f"UPDATE song SET path = ?, folder = ?, name_key = ?, {sets} WHERE id = ?",
        (new, place["folder"], place["name_key"], *values, keep[0]),
    )
    c.execute("DELETE FROM song_genre WHERE song_id = ?", keep)
    c.executemany(
        "INSERT INTO song_genre VALUES (?, ?, ?)", [(keep[0], n, g) for n, g in enumerate(genres)]
    )
    albums.place(c, keep[0], touched)
    search.index_songs(c, [keep[0]])
    return True


def _rows(
    c: sqlite3.Connection, scope: Scope | None, tree: Tree
) -> list[tuple[str, int, int, str]]:
    """(path, size, modification time, audio hash) of the rows a scan answers for: all of them,
    or a partial scan's (`in_scope`)."""
    cols = "SELECT path, size, mtime_ns, audio_hash FROM song"
    if scope is None or "" in scope.folders:
        rows = c.execute(cols).fetchall()
    else:
        rows = []
        for f in sorted(scope.folders):  # by the path's index: f/ up to f0, "0" following "/"
            rows += c.execute(f"{cols} WHERE path >= ? AND path < ?", (f + "/", f + "0"))
    if scope is None:
        return rows
    return [r for r in rows if in_scope(r[0].rpartition("/")[0], scope, tree)]


def _elsewhere(
    c: sqlite3.Connection,
    root: str,
    batch: list[Read],
    indexed: Mapping[str, object],
    moves: dict[str, str],
) -> dict[str, str]:
    """For a partial scan's new files, the other end of a move outside its scope (A2.4): a song
    with the file's audio hash whose file is gone is a move, put in `moves`; one whose file is
    still there makes the new file a copy (audio hash -> its path), which this returns."""
    copies: dict[str, str] = {}
    for r in batch:
        h = r.audio_hash
        if not h or r.seen.path in indexed or h in moves:
            continue
        others = [p for (p,) in c.execute("SELECT path FROM song WHERE audio_hash = ?", (h,))]
        gone = next((p for p in others if not os.path.exists(full_path(root, p))), None)
        if gone is not None:
            moves[h] = gone
        elif others:
            copies[h] = r.seen.path
    return copies


def _remove(
    c: sqlite3.Connection,
    remove: list[str],
    taken: Mapping[str, str],
    images: Mapping[str, list[art.Image]] | None,
) -> int:
    """In the writer's transaction: the songs at `remove` taken out of the index, and those at
    `taken`'s keys taken over by the copies its values name (`take_over`); their albums, artists
    and folders summarized again (A2.7). The number taken out."""
    touched = albums.Touched()
    moved = sum(take_over(c, old, new, touched) for old, new in taken.items())
    albums.forget(c, remove, touched)
    search.forget(c, remove)
    c.executemany("DELETE FROM song WHERE path = ?", [(p,) for p in remove])
    albums.refresh(c, touched, images)
    places = {albums.folder_of(p) for p in [*remove, *taken, *taken.values()]}
    places |= albums.folders_of(c, touched.albums)
    if images is not None:
        albums.refresh_folders(c, images)  # covers added or changed beside unchanged songs
        places |= set(folders.stale_images(c, images))
    folders.refresh(c, places, images)
    return moved


def remove(root: str, index: db.Index, paths: Collection[str]) -> int:
    """Takes the songs at `paths` out of the index, those whose file still isn't there: the songs
    a scan held (R2.10.1), once the user says Remove. A song whose file came back meanwhile stays,
    and with the root gone again, every one does. The number taken out."""
    if not os.path.isdir(root):
        log.warning("didn't take out the songs missing from %s: it isn't there", root)
        return 0
    gone = [p for p in paths if not os.path.exists(full_path(root, p))]

    def write(c: sqlite3.Connection) -> int:
        known = [p for p in gone if c.execute("SELECT 1 FROM song WHERE path = ?", (p,)).fetchone()]
        _remove(c, known, {}, None)
        return len(known)

    removed: int = index.write(write).result()
    log.info("took %d songs missing from %s out of the library", removed, root)
    return removed


def asks_first(gone: int, songs: int) -> bool:
    """Whether taking out `gone` songs of a library of `songs` waits on the user's answer
    (R2.10.1): when they are more than a quarter of it and more than ASK_OVER."""
    return gone > ASK_OVER and gone * 4 > songs


def scan(
    root: str,
    index: db.Index,
    workers: Executor,
    skip: Iterable[str] = (),
    progress: Callable[[int, int], None] | None = None,
    scope: Scope | None = None,
    expected: Mapping[str, tuple[int, int]] | None = None,
    copied: Mapping[str, str] | None = None,
    keep: Collection[str] = (),
    hold: bool = True,
    reached: Reached | None = None,
    clock: Clock | None = None,
) -> Result:
    """One scan of the root into its index (A2.2), or, given a `scope`, of the folders it names
    (A2.4). progress(done, of) after each batch, for the root's card (R2.3). `expected`: files
    MusiKata wrote itself, not read again (`plan`). `copied`: copies made while watching, by audio
    hash, which a song whose file went takes over (`take_over`); the result's are those still
    standing, with the new ones. `reached`: each folder as the walk lists it (`walk`), so that
    watching it starts then, not once the scan has ended (A2.4). The copies safe writes left
    behind (A3.4) are removed as the walk meets them, when last touched tags.safe.LEFTOVER
    seconds before `clock`'s time (the system's, unless given).

    A root that isn't there changes nothing (`Result.missing`), and the songs beneath a link that
    leads nowhere stay (`Result.unreachable`) (R2.10). When the songs gone are more than a quarter
    of the library's and more than ASK_OVER (`asks_first`), whichever scan finds them, a partial
    one included, none is taken out: they are `Result.held` for the user's answer (R2.10.1);
    `keep`, the songs the user said to keep, stay without being asked about again. `hold` False
    takes them out unasked: for a test whose subject is the removal itself."""
    c = index.read()
    images: dict[str, list[art.Image]] = {}
    tree = Tree()
    if not os.path.isdir(root):  # gone with its drive (R2.10): nothing is taken for removed
        log.warning("didn't scan %s: it isn't there", root)
        return Result(missing=True)
    now = (clock or SystemClock()).now().timestamp()
    if scope is None:
        seen = list(walk(root, skip, images, tree=tree, reached=reached, now=now))
    else:
        seen = list(walk_scope(root, scope, skip, images, tree, reached, now))
    rows = _rows(c, scope, tree)
    indexed = {p: (s, m) for p, s, m, _h in rows}
    hashes = {p: h for p, _s, _m, h in rows if h is not None}
    work = plan(seen, indexed, expected)
    kept = {p for p in work.gone if p in keep or under(p, tree.unreachable)}
    work.gone = [p for p in work.gone if p not in kept]
    moves = {hashes[p]: p for p in work.gone if p in hashes}
    total = Result(
        unchanged=len(indexed) - len(work.gone) - sum(s.path in indexed for s in work.read),
        folders=dict(tree.folders),
        read=list(work.read),
        unreachable=set(tree.unreachable),
    )
    copies = dict(copied or {})
    for i in range(0, len(work.read), BATCH):
        batch = list(
            workers.map(read_one, [root] * len(work.read[i : i + BATCH]), work.read[i : i + BATCH])
        )
        if scope is not None:
            copies.update(_elsewhere(c, root, batch, indexed, moves))

        def write(c: sqlite3.Connection, b: list[Read] = batch) -> Result:
            return write_batch(c, b, moves, images)

        res = index.write(write).result()
        for k in ("added", "changed", "moved", "unreadable"):
            setattr(total, k, getattr(total, k) + getattr(res, k))
        if progress:
            progress(min(i + BATCH, len(work.read)), len(work.read))
    # a gone row with a hash that a new file took is a move; every other gone row goes, those with
    # no hash (a file that couldn't be read) included, unless a copy made while watching takes it
    moved_from = {p for p in work.gone if p in hashes} - set(moves.values())
    left = [p for p in work.gone if p not in moved_from]
    gone = set(work.gone)
    taken = {
        p: copies[hashes[p]]
        for p in left
        if hashes.get(p) in copies
        and copies[hashes[p]] not in gone
        and os.path.exists(full_path(root, copies[hashes[p]]))
    }
    removing = [p for p in left if p not in taken]
    total.songs = c.execute("SELECT COUNT(*) FROM song").fetchone()[0]
    if not os.path.isdir(root):  # gone while it was walked: what wasn't seen isn't taken out
        log.warning("%s went while it was scanned: nothing is taken out", root)
        total.missing, removing, taken = True, [], {}
    elif hold and asks_first(len(removing), total.songs):
        log.warning(
            "%d of the %d songs in %s are gone: the user is asked before they are taken out",
            len(removing),
            total.songs,
            root,
        )
        total.held, removing = removing, []

    def delete(c: sqlite3.Connection) -> int:
        total.moved += _remove(c, removing, taken, images)
        return len(removing)

    total.removed = index.write(delete).result()
    used = {hashes[p] for p in taken}
    total.copied = {h: p for h, p in copies.items() if h not in used and p not in gone}
    if scope is None:
        log.info("scanned %s: %s", root, total)
    else:
        total.gone_folders = {
            f for f in scope.known if f not in tree.folders and in_scope(f, scope, tree)
        }
        named = ", ".join(f or "." for f in sorted(scope.folders))
        log.info("rescanned %s in %s: %s", named, root, total)
    return total
