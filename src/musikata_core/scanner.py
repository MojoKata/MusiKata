"""The scan (A2.2, R2.3): walk the root, compare each audio file's size and modification time with
its row, read the changed and new ones on the worker processes in batches, write each batch in one
transaction, and remove what's gone, unless it reappears elsewhere with the same audio hash, which
is a move: its row keeps its id and the plays that hang on it."""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import stat
from collections.abc import Callable, Iterable, Iterator, Mapping
from concurrent.futures import Executor
from dataclasses import dataclass, field
from typing import BinaryIO, Literal

from . import db
from .tags import EXTENSIONS, AudioInfo, TagReadError, Tags
from .tags import read as read_tags

log = logging.getLogger(__name__)
BATCH = 200  # files read and written at a time (A2.2)
HASHED = 64 * 1024  # bytes of audio at each end the audio hash reads (A2.3)
IGNORE = ".musikataignore"  # a folder holding one is skipped (R2.3.1)


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


@dataclass
class Result:
    added: int = 0
    changed: int = 0
    moved: int = 0
    removed: int = 0
    unreadable: int = 0
    unchanged: int = 0


# ---------- walking ----------


def _hidden(entry: os.DirEntry[str]) -> bool:
    """Hidden: a leading "." on Linux and macOS, the hidden attribute on Windows (R2.3.1)."""
    if entry.name.startswith("."):
        return True
    attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0))


def walk(root: str, skip: Iterable[str] = ()) -> Iterator[Seen]:
    """Every audio file under root (R2.2's kinds), skipping hidden files and folders, folders
    holding .musikataignore, the folders the settings skip (paths under the root), and the root's
    .musikata (R2.3.1). Links are followed like folders; one leading back to a folder already
    walked is skipped, and the log says so (R2.3.2)."""
    skipped = {s.strip("/") for s in skip}
    walked: set[str] = set()

    def go(folder: str, rel: str) -> Iterator[Seen]:
        real = os.path.realpath(folder)
        if real in walked:
            log.info("skipped %s: it leads back to %s, already walked", rel or ".", real)
            return
        walked.add(real)
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError as e:
            log.warning("couldn't read %s: %s", rel or ".", e)
            return
        if any(entry.name == IGNORE for entry in entries):
            return
        for entry in entries:
            path = f"{rel}/{entry.name}" if rel else entry.name
            if _hidden(entry) or path in skipped:
                continue
            try:
                if entry.is_dir():  # follows links (R2.3.2)
                    yield from go(entry.path, path)
                elif os.path.splitext(entry.name)[1].lower() in EXTENSIONS:
                    st = entry.stat()
                    yield Seen(path, st.st_size, st.st_mtime_ns)
            except OSError as err:
                log.warning("couldn't read %s: %s", path, err)

    yield from go(root, "")


def plan(seen: Iterable[Seen], indexed: Mapping[str, tuple[int, int]]) -> Plan:
    """The files whose size or modification time differ from their row, or that have none, and
    the rows no file was seen for (R2.3: an unchanged file costs one stat)."""
    p = Plan()
    found: set[str] = set()
    for s in seen:
        found.add(s.path)
        if indexed.get(s.path) != (s.size, s.mtime_ns):
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


def _values(r: Read) -> dict[str, object]:
    t = r.tags or Tags()
    i = r.info
    row: dict[str, object] = {
        "path": r.seen.path, "size": r.seen.size, "mtime_ns": r.seen.mtime_ns,
        "kind": i.kind if i else None, "length": i.length if i else None,
        "bitrate": i.bitrate if i else None, "sample_rate": i.sample_rate if i else None,
        "channels": i.channels if i else None, "audio_hash": r.audio_hash, "error": r.error,
    }  # fmt: skip
    row.update({name: getattr(t, name) for name in db.FIELDS})
    return row


def write_batch(c: sqlite3.Connection, batch: list[Read], moves: dict[str, str]) -> Result:
    """One batch into the index, in the writer's transaction: each file's row added or replaced,
    or, for a new path whose audio hash a gone row has (`moves`: hash -> old path), that row moved
    here (A2.2, step 4)."""
    res = Result()
    for r in batch:
        values = _values(r)
        old = moves.pop(r.audio_hash, None) if r.audio_hash else None
        row = c.execute("SELECT id FROM song WHERE path = ?", (old or r.seen.path,)).fetchone()
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
    return res


def scan(
    root: str,
    index: db.Index,
    workers: Executor,
    skip: Iterable[str] = (),
    progress: Callable[[int, int], None] | None = None,
) -> Result:
    """One scan of the root into its index (A2.2). progress(done, of) after each batch, for the
    root's card (R2.3)."""
    c = index.read()
    indexed = {p: (s, m) for p, s, m in c.execute("SELECT path, size, mtime_ns FROM song")}
    hashes = dict(c.execute("SELECT path, audio_hash FROM song WHERE audio_hash IS NOT NULL"))
    work = plan(walk(root, skip), indexed)
    moves = {hashes[p]: p for p in work.gone if p in hashes}
    total = Result(
        unchanged=len(indexed) - len(work.gone) - sum(s.path in indexed for s in work.read)
    )
    for i in range(0, len(work.read), BATCH):
        batch = list(
            workers.map(read_one, [root] * len(work.read[i : i + BATCH]), work.read[i : i + BATCH])
        )

        def write(c: sqlite3.Connection, b: list[Read] = batch) -> Result:
            return write_batch(c, b, moves)

        res = index.write(write).result()
        for k in ("added", "changed", "moved", "unreadable"):
            setattr(total, k, getattr(total, k) + getattr(res, k))
        if progress:
            progress(min(i + BATCH, len(work.read)), len(work.read))
    moved_from = set(work.gone) - set(moves.values())
    remove = [p for p in work.gone if p not in moved_from]

    def delete(c: sqlite3.Connection) -> int:
        c.executemany("DELETE FROM song WHERE path = ?", [(p,) for p in remove])
        return len(remove)

    total.removed = index.write(delete).result()
    log.info("scanned %s: %s", root, total)
    return total
