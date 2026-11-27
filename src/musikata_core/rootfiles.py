"""The root's own files (A2.8, A2.10): for now its play counts (R7.9), a file per computer,
`<root>/.musikata/<computer id>/plays.json`, which only that computer writes.

The counts live in the index's `play` table (A2.1), a row per song each computer has played: this
computer's rows are the counts it keeps, each play added on the writer thread (`count`); another
computer's are read from its file, at start and whenever the watcher sees it change, and replace
what was read of it before (`replace`). The count shown is the sum of every computer's rows for a
song (`totals`). This computer's file is written whole from its rows, to a temporary file moved
over the old one, at most once a minute while playing and at quit (`Due`, `Keeping`); a crash
loses nothing, the index has the counts, and the file is written at the next start. At start the
file is read back into the index too, each entry taking the larger count (`merge_own`), so an
index deleted or made anew (R1.5.1) gets back every play. When `.musikata` can't be written
(R1.5.2), the counts are kept in the index only, and the log says so.

Each entry names its song by its path under the root and its audio hash (A2.3); it is matched to
the index by path, and by hash when no song has that path (`match`), so a song moved in a file
manager keeps its plays on every computer. A row whose song isn't in the index yet stays, waiting
for a scan to find it (`link`), and a song moved by a scan takes its rows' paths with it
(`moved`), so this computer's file names it where it is now.

A file is data from outside (another computer, another version, a sync in progress): one cut
short, not JSON, or of the wrong shape is logged and skipped; an entry it can't use is logged and
left out, the rest kept; a newer format is read for what it can and never written (A2.10); the
fields it doesn't know are kept when this computer writes its own again.

Needs attention's dismissals (Ignore, R2.8) are the root's `.musikata/ignored.json`, which any
computer writes: read again before writing and merged entry by entry, the newest `changed`
winning (`save_ignored`, A2.8), and kept in the index's `ignored` (`load_ignored`), at start and
whenever the watcher sees the file change. Each names what it is about as A2.10 says, a song by its
path and audio hash; attention.dismissed matches them."""

from __future__ import annotations

import functools
import json
import logging
import math
import os
import re
import sqlite3
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from . import db, settings
from .clock import Clock

log = logging.getLogger(__name__)
FORMAT = 1  # plays.json's format (A2.10)
NAME = "plays.json"
MUSIKATA = ".musikata"  # the root's own folder (R1.5)
EVERY = 60.0  # seconds between writes of this computer's file, at most (A2.8)
CHUNK = 500  # entries looked up in the index at a time
HASH = re.compile(r"[0-9a-f]{64}")
UNKNOWN = "1970-01-01T00:00:00Z"  # a last-played time a file broke: the oldest there is
KNOWN = frozenset({"format", "computer", "songs"})
KNOWN_SONG = frozenset({"path", "hash", "count", "last"})


@dataclass(frozen=True)
class Entry:
    """A song a computer has played: its path under the root, its audio hash (None: not known),
    how many times it was played and when last, a UTC time as A2.10 writes it."""

    path: str
    hash: str | None
    count: int
    last: str


@dataclass(frozen=True)
class Plays:
    """A plays.json as read: the computer it names (its id and name, None when it names none),
    its entries, its fields this version doesn't know (`extras`, and each entry's by path) to keep
    when it is written again; `newer`, a newer MusiKata's format, never written; `broken`, a file
    that couldn't be used at all; `problems`, what couldn't be used, for the log."""

    computer: str | None = None
    name: str | None = None
    entries: tuple[Entry, ...] = ()
    extras: Mapping[str, object] = field(default_factory=dict)
    song_extras: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    newer: bool = False
    broken: bool = False
    problems: tuple[str, ...] = ()


def _broken(why: str) -> Plays:
    return Plays(broken=True, problems=(f"{why}: its plays aren't counted",))


def time_text(when: datetime) -> str:
    """`when` as A2.10 writes a time: UTC, ISO 8601, to the second."""
    return when.astimezone(UTC).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def parse_time(value: object) -> str | None:
    """A time as A2.10 writes it, from `value`; None when it isn't a time with its zone."""
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    return time_text(when) if when.tzinfo is not None else None


def _count(value: object) -> int | None:
    """A play count from `value`: a whole number of 1 or more, also as 12.0 or "12"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and value >= 1 else None


def _entry(value: object, problems: list[str]) -> tuple[Entry, dict[str, object]] | None:
    """An entry of `songs` and its fields this version doesn't know; None, with the problem,
    when it can't be used."""
    if not isinstance(value, dict):
        problems.append(f"a song isn't an object: {value!r}; left out")
        return None
    path = value.get("path")
    if not isinstance(path, str) or not path:
        problems.append(f"a song's path isn't a path under the root: {path!r}; left out")
        return None
    count = _count(value.get("count"))
    if count is None:
        problems.append(f"{path}: its count isn't a number of plays: {value.get('count')!r}")
        return None
    hash_ = value.get("hash")
    if isinstance(hash_, str) and HASH.fullmatch(hash_.lower()):
        hash_ = hash_.lower()
    else:
        problems.append(f"{path}: its hash isn't an audio hash: {hash_!r}; found by its path only")
        hash_ = None
    last = parse_time(value.get("last"))
    if last is None:
        problems.append(f"{path}: last isn't a UTC time: {value.get('last')!r}; not known")
        last = UNKNOWN
    extras = {k: v for k, v in value.items() if k not in KNOWN_SONG}
    return Entry(path, hash_, count, last), extras


def parse(text: str) -> Plays:
    """The plays in `text`, a plays.json's content, whatever was written there: a file that
    can't be used whole gives none, and an entry that can't be used is left out, each named in
    `problems`. An entry named twice is one, its counts added up."""
    try:
        data = json.loads(text.removeprefix("﻿"))
    except ValueError as e:
        return _broken(f"it isn't JSON ({e})")
    if not isinstance(data, dict):
        return _broken("it isn't a JSON object")
    problems: list[str] = []
    fmt = data.get("format")
    newer = False
    if isinstance(fmt, int) and not isinstance(fmt, bool):
        newer = fmt > FORMAT
        if newer:
            problems.append(f"it is format {fmt}, from a newer MusiKata: it is read, not written")
    elif fmt is not None:
        problems.append(f"format isn't a number: {fmt!r}; read as format {FORMAT}")
    computer = data.get("computer")
    cid = name = None
    if isinstance(computer, dict):
        cid = computer.get("id") if isinstance(computer.get("id"), str) else None
        name = computer.get("name") if isinstance(computer.get("name"), str) else None
    if not cid:
        problems.append(f"computer doesn't name its id: {computer!r}")
        cid = None
    listed = data.get("songs", [])
    if not isinstance(listed, list):
        return _broken(f"songs isn't a list: {listed!r}")
    entries: dict[str, Entry] = {}
    song_extras: dict[str, Mapping[str, object]] = {}
    for value in listed:
        read = _entry(value, problems)
        if read is None:
            continue
        entry, extras = read
        twice = entries.get(entry.path)
        if twice is not None:
            problems.append(f"{entry.path} is named twice: its counts are added up")
            entry = Entry(
                entry.path,
                entry.hash or twice.hash,
                entry.count + twice.count,
                max(entry.last, twice.last),
            )
        entries[entry.path] = entry
        if extras:
            song_extras[entry.path] = extras
    return Plays(
        computer=cid,
        name=name,
        entries=tuple(entries.values()),
        extras={k: v for k, v in data.items() if k not in KNOWN},
        song_extras=song_extras,
        newer=newer,
        problems=tuple(problems),
    )


# ---------- where they are ----------


def folder_of(root: str) -> str:
    """The root's own folder, `.musikata` (R1.5)."""
    return os.path.join(root, MUSIKATA)


def file_of(musikata: str, computer: str) -> str:
    """The plays file of `computer` in the root's own folder `musikata`."""
    return os.path.join(musikata, computer, NAME)


def writable(musikata: str) -> bool:
    """Whether the root's own folder can be written (R1.5.2)."""
    return os.path.isdir(musikata) and os.access(musikata, os.W_OK)


def read(path: str) -> Plays | None:
    """The plays file at `path`, each problem logged; None when there is none."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        found = _broken(f"it couldn't be read ({e})")
    else:
        found = parse(text)
    for problem in found.problems:
        log.warning("%s: %s", path, problem)
    return found


def folders(musikata: str) -> list[str]:
    """The computers' folders in the root's own folder, by name (their id); none when it can't
    be listed (logged)."""
    try:
        return sorted(e.name for e in os.scandir(musikata) if e.is_dir())
    except OSError as e:
        log.warning("couldn't list %s: %s", musikata, e)
        return []


def read_other(musikata: str, computer: str) -> Plays | None:
    """Another computer's plays file, read for what it can give; None when there is none. One
    that can't be used is `broken`, and so is one that names another computer than its folder
    does (a sync tool's copy of the folder, "… (conflicted copy)"), which the log says."""
    path = file_of(musikata, computer)
    found = read(path)
    if found is not None and found.computer is not None and found.computer != computer:
        log.warning(
            "%s names computer %s, not %s: a copy of its folder, not read",
            path,
            found.computer,
            computer,
        )
        return _broken("a copy of another computer's folder")
    return found


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


# ---------- matching entries to the index ----------


class Named(Protocol):
    """What names a song in a root's own file (A2.8): its path under the root and its audio hash
    (None: not known)."""

    @property
    def path(self) -> str: ...

    @property
    def hash(self) -> str | None: ...


def match(
    entries: Sequence[Named], by_path: Mapping[str, int], by_hash: Mapping[str, int]
) -> list[int | None]:
    """The song each entry stands for (A2.8): the song with its path, else the one with its
    audio hash; None when neither is in the index."""
    return [
        by_path.get(e.path, by_hash.get(e.hash) if e.hash is not None else None) for e in entries
    ]


def _lookup(c: sqlite3.Connection, column: str, values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    wanted = list(dict.fromkeys(values))
    for i in range(0, len(wanted), CHUNK):
        chunk = wanted[i : i + CHUNK]
        marks = ", ".join("?" * len(chunk))
        for value, song in c.execute(
            f"SELECT {column}, id FROM song WHERE {column} IN ({marks}) ORDER BY path DESC", chunk
        ):
            out[value] = song  # the first by path wins: it comes last
    return out


def find(c: sqlite3.Connection, entries: Sequence[Named]) -> list[int | None]:
    """The song in the index on `c` each entry stands for (`match`)."""
    by_path = _lookup(c, "path", (e.path for e in entries))
    hashes = [e.hash for e in entries if e.hash is not None and e.path not in by_path]
    return match(entries, by_path, _lookup(c, "audio_hash", hashes) if hashes else {})


# ---------- in the index: each function runs in the writer's transaction ----------


def _merge_twins(c: sqlite3.Connection, songs: Collection[int]) -> None:
    """Rows of one computer standing for one song (a song moved onto another's path, a copy
    gone that its twin stands in for) become one, their counts added up."""
    wanted = list(songs)
    for i in range(0, len(wanted), CHUNK):
        chunk = wanted[i : i + CHUNK]
        marks = ", ".join("?" * len(chunk))
        twins = c.execute(
            f"SELECT computer, song_id FROM play WHERE song_id IN ({marks})"
            " GROUP BY computer, song_id HAVING COUNT(*) > 1",
            chunk,
        ).fetchall()
        for computer, song in twins:
            rows = c.execute(
                "SELECT id, count, last FROM play WHERE computer = ? AND song_id = ? ORDER BY id",
                (computer, song),
            ).fetchall()
            c.execute(
                "UPDATE play SET count = ?, last = ? WHERE id = ?",
                (sum(r[1] for r in rows), max(r[2] for r in rows), rows[0][0]),
            )
            c.executemany("DELETE FROM play WHERE id = ?", [(r[0],) for r in rows[1:]])


def link(c: sqlite3.Connection, songs: Iterable[int] = ()) -> None:
    """Rows matched to the songs the index has now: those naming the path of one of `songs`
    (just written by a scan) stand for it, as a path wins over a hash (A2.8); those standing for
    no song are matched again (`find`), as a scan may have brought theirs."""
    linked: set[int] = set()
    for song in songs:
        found = c.execute("SELECT path FROM song WHERE id = ?", (song,)).fetchone()
        if (
            found is not None
            and c.execute(
                "UPDATE play SET song_id = ? WHERE path = ? AND song_id IS NOT ?",
                (song, found[0], song),
            ).rowcount
        ):
            linked.add(song)
    orphans = c.execute("SELECT id, path, hash, count, last FROM play WHERE song_id IS NULL")
    rows = orphans.fetchall()
    if rows:
        entries = [Entry(p, h, n, t) for _i, p, h, n, t in rows]
        found_songs = find(c, entries)
        updates = [(s, r[0]) for s, r in zip(found_songs, rows, strict=True) if s is not None]
        c.executemany("UPDATE play SET song_id = ? WHERE id = ?", updates)
        linked.update(s for s, _ in updates)
    if linked:
        _merge_twins(c, linked)


def moved(c: sqlite3.Connection, song: int) -> None:
    """The song `song` was moved, or took over another's row (A2.2): its rows name it where it is
    now, so this computer's file is written with its new path (A2.8)."""
    c.execute(
        "UPDATE play SET path = (SELECT path FROM song WHERE id = :song),"
        " hash = coalesce((SELECT audio_hash FROM song WHERE id = :song), hash)"
        " WHERE song_id = :song",
        {"song": song},
    )


def count(c: sqlite3.Connection, computer: str, song: int, when: datetime) -> bool:
    """One more play of `song` by `computer`, last played `when`; False, logged, when the song
    has gone from the index since."""
    row = c.execute(
        "SELECT id FROM play WHERE computer = ? AND song_id = ? ORDER BY id LIMIT 1",
        (computer, song),
    ).fetchone()
    if row is not None:
        c.execute(
            "UPDATE play SET count = count + 1, last = max(last, ?) WHERE id = ?",
            (time_text(when), row[0]),
        )
        return True
    found = c.execute("SELECT path, audio_hash FROM song WHERE id = ?", (song,)).fetchone()
    if found is None:
        log.warning("didn't count a play of song %d: it is no longer in the index", song)
        return False
    c.execute(
        "INSERT INTO play (computer, song_id, path, hash, count, last) VALUES (?, ?, ?, ?, 1, ?)",
        (computer, song, found[0], found[1], time_text(when)),
    )
    return True


def _insert(c: sqlite3.Connection, computer: str, entries: Sequence[Entry]) -> None:
    songs = find(c, entries)
    c.executemany(
        "INSERT INTO play (computer, song_id, path, hash, count, last) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (computer, s, e.path, e.hash, e.count, e.last)
            for s, e in zip(songs, entries, strict=True)
        ],
    )
    _merge_twins(c, {s for s in songs if s is not None})


def replace(c: sqlite3.Connection, computer: str, entries: Sequence[Entry]) -> None:
    """Another computer's plays, as its file has them now, in place of what was read of it."""
    c.execute("DELETE FROM play WHERE computer = ?", (computer,))
    _insert(c, computer, entries)


def _replace(computer: str, entries: Sequence[Entry], c: sqlite3.Connection) -> None:
    replace(c, computer, entries)


def forget(c: sqlite3.Connection, keep: Collection[str]) -> None:
    """The rows of every computer but those in `keep`: those whose file has gone."""
    marks = ", ".join("?" * len(keep))
    c.execute(f"DELETE FROM play WHERE computer NOT IN ({marks})", tuple(keep))


def merge_own(c: sqlite3.Connection, computer: str, entries: Sequence[Entry]) -> int:
    """This computer's own file read back into its rows (at start): an entry the index has, by
    its path, else its hash, takes the larger count and the later time; one it hasn't is added.
    So an index made anew gets back every play, and one ahead of its file (a crash before the
    write) loses none. Rows kept under no id ("", while this computer had none) become its own.
    The number of rows changed or added."""
    if (
        computer
        and c.execute("UPDATE play SET computer = ? WHERE computer = ''", (computer,)).rowcount
    ):
        _merge_twins(c, [s for (s,) in c.execute(
            "SELECT song_id FROM play WHERE computer = ? AND song_id IS NOT NULL", (computer,)
        )])  # fmt: skip
    rows = c.execute(
        "SELECT id, path, hash, count, last FROM play WHERE computer = ?", (computer,)
    ).fetchall()
    by_path = {r[1]: r for r in rows}
    by_hash = {r[2]: r for r in rows if r[2] is not None}
    changed = 0
    new: list[Entry] = []
    for e in entries:
        row = by_path.get(e.path) or (by_hash.get(e.hash) if e.hash is not None else None)
        if row is None:
            new.append(e)
        elif e.count > row[3] or e.last > row[4]:
            c.execute(
                "UPDATE play SET count = ?, last = ? WHERE id = ?",
                (max(e.count, row[3]), max(e.last, row[4]), row[0]),
            )
            changed += 1
    _insert(c, computer, new)
    return changed + len(new)


def own(c: sqlite3.Connection, computer: str) -> list[Entry]:
    """This computer's plays, as its file is written: each song once, where it is now (its path
    and hash in the index), and those the index doesn't have now as they were named."""
    rows = c.execute(
        "SELECT coalesce(song.path, play.path), coalesce(song.audio_hash, play.hash),"
        " SUM(play.count), MAX(play.last) FROM play LEFT JOIN song ON song.id = play.song_id"
        " WHERE play.computer = ? GROUP BY coalesce(play.song_id, -play.id)"
        " ORDER BY 1",
        (computer,),
    )
    return [Entry(p, h, n, t) for p, h, n, t in rows]


def totals(c: sqlite3.Connection, songs: Iterable[int]) -> dict[int, int]:
    """Each song's plays on every computer, added up (R7.9), by id; a song never played has
    none."""
    out: dict[int, int] = {}
    wanted = list(dict.fromkeys(songs))
    for i in range(0, len(wanted), CHUNK):
        chunk = wanted[i : i + CHUNK]
        marks = ", ".join("?" * len(chunk))
        out.update(
            c.execute(
                f"SELECT song_id, SUM(count) FROM play WHERE song_id IN ({marks}) GROUP BY song_id",
                chunk,
            ).fetchall()
        )
    return out


def document(
    computer: str, name: str | None, entries: Iterable[Entry], kept: Plays | None = None
) -> dict[str, object]:
    """This computer's plays file for `entries`; the fields `kept`, the file as read, had that
    this version doesn't know are kept (A2.10). An entry whose song has no audio hash (one that
    couldn't be read) is left out of the file, as A2.10 names each song by both, and kept in the
    index."""
    extras = kept.extras if kept is not None else {}
    song_extras = kept.song_extras if kept is not None else {}
    songs: list[dict[str, object]] = []
    for e in entries:
        if e.hash is None or not HASH.fullmatch(e.hash):
            log.info("%s has no audio hash: its plays are kept in the index only", e.path)
            continue
        songs.append(
            {**song_extras.get(e.path, {}), "path": e.path, "hash": e.hash, "count": e.count,
             "last": e.last}
        )  # fmt: skip
    who: dict[str, object] = {"id": computer}
    if name:
        who["name"] = name
    return {**extras, "format": FORMAT, "computer": who, "songs": songs}


# ---------- when this computer's file is written ----------


class Due:
    """When this computer's file is written (A2.8): once its plays have changed, at most once a
    minute (`every` seconds on `clock`), and at quit whatever the minute says."""

    def __init__(self, clock: Clock, every: float = EVERY) -> None:
        self._clock, self._every = clock, every
        self._at: float | None = None  # when it was last written; None: not yet
        self.changed = False

    def change(self) -> None:
        """Its plays changed: it is to be written."""
        self.changed = True

    def take(self, at_quit: bool = False) -> bool:
        """Whether it is written now; when it is, it is taken as written."""
        now = self._clock.monotonic()
        if not self.changed:
            return False
        if not at_quit and self._at is not None and now - self._at < self._every:
            return False
        self.changed, self._at = False, now
        return True


class Keeping:
    """Keeps the root's play counts (R7.9) on a thread of its own, the jobs in the order asked,
    so the GUI thread never waits on a file or the index: the index on `index`, written on its
    writer thread, and the files in `musikata`, the root's own folder. `computer` is this
    computer's id (None: not known), `make` makes and keeps one (settings.computer_id) when its
    file is first written and it has none, so a root opened for one run (R2.1.2) that plays
    nothing writes nothing, and `name` is its name for display. `on_change` is told, on the
    thread, when the counts shown, or the computers' folders listed (`seen`), may have
    changed."""

    def __init__(
        self,
        index: db.Index,
        musikata: str,
        clock: Clock,
        computer: str | None = None,
        make: Callable[[], str | None] | None = None,
        name: str | None = None,
        on_change: Callable[[], object] | None = None,
        executor: Executor | None = None,
    ) -> None:
        self._index, self._musikata, self._clock = index, musikata, clock
        self._computer, self._make, self._name = computer, make, name
        self.on_change = on_change
        self._executor = executor
        self._closed = False
        self.due = Due(clock)
        self._kept: Plays | None = None  # this computer's file as read at start
        self._writing = False  # its file is written: `.musikata` can, and it isn't a newer one's
        self.me = computer or ""  # this computer's rows' key: its id, "" while it has none
        self.seen: tuple[str, ...] = ()  # the computers' folders in `.musikata`, as last listed

    def _submit(self, job: Callable[[], object]) -> Future[object]:
        if self._closed:  # what comes after quitting began: nothing more is kept
            log.warning("the play counts were closed: a late job is passed by")
            done: Future[object] = Future()
            done.set_result(None)
            return done
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="plays")
        return self._executor.submit(self._run, job)

    @staticmethod
    def _run(job: Callable[[], object]) -> object:
        try:
            return job()
        except Exception:  # a job that breaks is logged; the next one tries again
            log.exception("keeping the play counts failed")
            return None

    def _tell(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def start(self, others: bool = True) -> Future[object]:
        """Reads this computer's file back into the index and, with `others`, every other
        computer's in place of what was read of it; then writes this computer's when the index
        has more than it. Off this thread; the future's result is True once done."""
        return self._submit(lambda: self._start(others))

    def _start(self, others: bool) -> bool:
        can_write = writable(self._musikata)
        me = self.me
        if not can_write:
            log.warning(
                "%s can't be written: the play counts are kept in this computer's index only",
                self._musikata,
            )
        kept = read(file_of(self._musikata, me)) if me else None
        if kept is not None and kept.broken:
            kept = None
        self._kept = kept
        self._writing = can_write and not (kept is not None and kept.newer)
        if kept is not None and kept.newer:
            log.warning("%s is a newer MusiKata's: it isn't written", file_of(self._musikata, me))
        entries = kept.entries if kept is not None else ()
        self._index.write(lambda c: merge_own(c, me, entries)).result()
        if others and os.path.isdir(self._musikata):
            self._read_others(None)
        written = self._index.write(lambda c: own(c, me)).result()
        if set(written) != set(kept.entries if kept is not None else ()):
            self._write()  # the index has plays its file hasn't: a crash before the write
        self._tell()
        return True

    def _read_others(self, names: Iterable[str] | None) -> None:
        """Each of the other computers' files named read in place of what was read of it, and
        forgotten when it has gone; one that can't be used (a sync in progress) leaves what was
        read of it before. None: every computer's in `.musikata`, listed again (`seen`), and
        those whose folder has gone forgotten too."""
        whole = names is None
        if names is None:
            self.seen = tuple(folders(self._musikata))
            names = self.seen
        read_now: list[str] = []
        for computer in names:
            if computer == self.me:
                continue
            found = read_other(self._musikata, computer)
            if found is not None and found.broken:  # a sync in progress: what was read stays
                read_now.append(computer)
                continue
            entries = found.entries if found is not None else ()
            self._index.write(functools.partial(_replace, computer, entries)).result()
            if found is not None:
                read_now.append(computer)
        if whole:
            keep = {self.me, *read_now}
            self._index.write(lambda c: forget(c, keep)).result()

    def reread(self, names: Iterable[str] | None = None) -> Future[object]:
        """Other computers' files changed (the watcher): each read again, off this thread; None,
        every one, `.musikata` listed again (`_read_others`)."""
        wanted = list(names) if names is not None else None

        def job() -> bool:
            self._read_others(wanted)
            self._tell()
            return True

        return self._submit(job)

    def played(self, song: int, when: datetime) -> Future[object]:
        """A play of `song` counted at `when` (R7.9): added in the index, then the file written
        when it is due (`Due`), off this thread. The future's result is whether it was added."""

        def job() -> bool:
            added = self._index.write(lambda c: count(c, self.me, song, when)).result()
            self._tell()
            return added

        done = self._submit(job)
        self.due.change()
        self.tick()
        return done

    def tick(self) -> Future[object] | None:
        """While playing: the file written when it is due; None when it isn't."""
        if not self.due.take():
            return None
        return self._submit(self._write)

    def moved(self) -> Future[object] | None:
        """A scan moved songs: this computer's file names them where they are now, when due."""
        self.due.change()
        return self.tick()

    def _write(self) -> str | None:
        """This computer's file written from its rows; the path written, None when it isn't
        (`.musikata` can't be written, a newer MusiKata's file, no id, or it failed: logged)."""
        if not self._writing or not self._own_id():
            return None
        entries = self._index.write(lambda c: own(c, self.me)).result()
        path = file_of(self._musikata, self.me)
        data = document(self.me, self._name, entries, self._kept)
        return path if settings.save(path, data) else None

    def _own_id(self) -> bool:
        """Whether this computer has an id for its file, made now (`make`) when it has none yet,
        the plays kept until then becoming its own."""
        if self.me:
            return True
        made = self._make() if self._make is not None else None
        if not made:
            return False
        self._index.write(lambda c: merge_own(c, made, ())).result()
        self._computer = self.me = made
        return True

    def close(self) -> None:
        """Writes the file if anything changed since it was last (at quit), then waits for the
        jobs asked for and ends the thread."""
        if self.due.take(at_quit=True):
            self._submit(self._write)
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(wait=True)


# ---------- ignored.json: Needs attention's dismissals (R2.8, A2.8, A2.10) ----------

IGNORED = "ignored.json"
IGNORED_FORMAT = 1
IGNORED_KNOWN = frozenset({"format", "entries"})
IGNORED_KNOWN_ENTRY = frozenset({"kind", "about", "hash", "modified", "changed"})


@dataclass(frozen=True)
class Dismissal:
    """A Needs attention entry the user dismissed (Ignore, R2.8), as ignored.json keeps it: its
    kind, what it is about (a path under the root, or for names, the name), the song's audio hash
    (None: not a song, or not known), the file's modification time in seconds when it was
    dismissed (None: none kept), and when it was dismissed, a UTC time as A2.10 writes it."""

    kind: str
    about: str
    hash: str | None
    modified: float | None
    changed: str


@dataclass(frozen=True)
class Dismissals:
    """An ignored.json as read: its entries, the fields this version doesn't know (`extras`, and
    each entry's by kind and about) to keep when it is written again; `newer`, a newer MusiKata's
    format, never written; `broken`, a file that couldn't be used at all; `problems`, what
    couldn't be used, for the log."""

    entries: tuple[Dismissal, ...] = ()
    extras: Mapping[str, object] = field(default_factory=dict)
    entry_extras: Mapping[tuple[str, str], Mapping[str, object]] = field(default_factory=dict)
    newer: bool = False
    broken: bool = False
    problems: tuple[str, ...] = ()


class IgnoredError(Exception):
    """ignored.json couldn't be written, and why, in words a person can act on."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def _modified(value: object) -> float | None:
    """A modification time in seconds from `value`: a number, also as text; None for anything
    else (NaN, a bool, a negative time)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, int | float) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def _dismissal(value: object, problems: list[str]) -> tuple[Dismissal, dict[str, object]] | None:
    """An entry of `entries` and its fields this version doesn't know; None, with the problem,
    when it can't be used."""
    if not isinstance(value, dict):
        problems.append(f"an entry isn't an object: {value!r}; left out")
        return None
    kind, about = value.get("kind"), value.get("about")
    if not isinstance(kind, str) or not kind.strip():
        problems.append(f"an entry's kind isn't text: {kind!r}; left out")
        return None
    if not isinstance(about, str) or not about:
        problems.append(f"an entry's about isn't text: {about!r}; left out")
        return None
    hash_ = value.get("hash")
    if isinstance(hash_, str) and HASH.fullmatch(hash_.lower()):
        hash_ = hash_.lower()
    else:
        if hash_ is not None:
            problems.append(f"{about}: its hash isn't an audio hash: {hash_!r}; found by its path")
        hash_ = None
    modified = _modified(value.get("modified"))
    if modified is None and value.get("modified") is not None:
        problems.append(f"{about}: modified isn't a time: {value.get('modified')!r}; left out")
        return None
    changed = parse_time(value.get("changed"))
    if changed is None:
        problems.append(
            f"{about}: changed isn't a UTC time: {value.get('changed')!r}; the oldest there is"
        )
        changed = UNKNOWN
    extras = {k: v for k, v in value.items() if k not in IGNORED_KNOWN_ENTRY}
    return Dismissal(kind.strip(), about, hash_, modified, changed), extras


def _broken_ignored(why: str) -> Dismissals:
    return Dismissals(broken=True, problems=(f"{why}: its dismissals aren't read",))


def parse_ignored(text: str) -> Dismissals:
    """The dismissals in `text`, an ignored.json's content, whatever was written there: a file
    that can't be used whole gives none, and an entry that can't be used is left out, each named
    in `problems`. An entry named twice (its kind and about) is one, the newest `changed`
    winning."""
    try:
        data = json.loads(text.removeprefix("﻿"))
    except ValueError as e:
        return _broken_ignored(f"it isn't JSON ({e})")
    if not isinstance(data, dict):
        return _broken_ignored("it isn't a JSON object")
    problems: list[str] = []
    fmt = data.get("format")
    newer = False
    if isinstance(fmt, int) and not isinstance(fmt, bool):
        newer = fmt > IGNORED_FORMAT
        if newer:
            problems.append(f"it is format {fmt}, from a newer MusiKata: it is read, not written")
    elif fmt is not None:
        problems.append(f"format isn't a number: {fmt!r}; read as format {IGNORED_FORMAT}")
    listed = data.get("entries", [])
    if not isinstance(listed, list):
        return _broken_ignored(f"entries isn't a list: {listed!r}")
    entries: dict[tuple[str, str], Dismissal] = {}
    entry_extras: dict[tuple[str, str], Mapping[str, object]] = {}
    for value in listed:
        read_ = _dismissal(value, problems)
        if read_ is None:
            continue
        d, extras = read_
        twice = entries.get((d.kind, d.about))
        if twice is not None:
            problems.append(f"{d.kind} {d.about} is named twice: the newest is kept")
            if twice.changed > d.changed:
                continue
        entries[(d.kind, d.about)] = d
        if extras:
            entry_extras[(d.kind, d.about)] = extras
    return Dismissals(
        entries=tuple(entries.values()),
        extras={k: v for k, v in data.items() if k not in IGNORED_KNOWN},
        entry_extras=entry_extras,
        newer=newer,
        problems=tuple(problems),
    )


def merge_ignored(kept: Iterable[Dismissal], mine: Iterable[Dismissal]) -> list[Dismissal]:
    """The dismissals of `kept` (the file as read again) with `mine` (this computer's new ones),
    entry by entry (kind and about), the newest `changed` winning and, at the same time, `mine`
    (A2.8); by kind and about, in order."""
    out = {(d.kind, d.about): d for d in kept}
    for d in mine:
        there = out.get((d.kind, d.about))
        if there is None or d.changed >= there.changed:
            out[(d.kind, d.about)] = d
    return [out[k] for k in sorted(out)]


def ignored_document(
    entries: Iterable[Dismissal], kept: Dismissals | None = None
) -> dict[str, object]:
    """ignored.json for `entries`; the fields `kept`, the file as read, had that this version
    doesn't know are kept (A2.10)."""
    extras = kept.extras if kept is not None else {}
    entry_extras = kept.entry_extras if kept is not None else {}
    out: list[dict[str, object]] = []
    for d in entries:
        entry: dict[str, object] = {**entry_extras.get((d.kind, d.about), {}), "kind": d.kind,
                                    "about": d.about}  # fmt: skip
        if d.hash is not None:
            entry["hash"] = d.hash
        if d.modified is not None:
            entry["modified"] = d.modified
        entry["changed"] = d.changed
        out.append(entry)
    return {**extras, "format": IGNORED_FORMAT, "entries": out}


def ignored_of(root: str) -> str:
    """The root's ignored.json, in its `.musikata` (R1.5)."""
    return os.path.join(folder_of(root), IGNORED)


def read_ignored(path: str) -> Dismissals | None:
    """The ignored.json at `path`, each problem logged; None when there is none."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        found = _broken_ignored(f"it couldn't be read ({e.strerror or e})")
    else:
        found = parse_ignored(text)
    for problem in found.problems:
        log.warning("%s: %s", path, problem)
    return found


def save_ignored(path: str, mine: Sequence[Dismissal]) -> list[Dismissal]:
    """`mine` written into the ignored.json at `path`, read again first and merged
    (`merge_ignored`); the entries written. Raises IgnoredError, the file as it was, when it is
    a newer MusiKata's, can't be read (it isn't written over: a sync may be bringing it), or
    can't be written."""
    found = read_ignored(path)
    if found is not None and found.newer:
        raise IgnoredError(
            "the music folder's ignored.json was changed by a newer MusiKata: update MusiKata to"
            " dismiss entries there"
        )
    if found is not None and found.broken:
        why = found.problems[0] if found.problems else "it can't be read"
        raise IgnoredError(
            f"the music folder's ignored.json can't be read, so it isn't written over ({why})"
        )
    entries = merge_ignored(found.entries if found is not None else (), mine)
    if not settings.save(path, ignored_document(entries, found)):
        raise IgnoredError("the music folder's ignored.json couldn't be written")
    return entries


# in the index: each function runs in the writer's transaction


def load_ignored(c: sqlite3.Connection, entries: Iterable[Dismissal]) -> int:
    """Dismissals (as read, or made on this computer) merged into the index's `ignored`, entry
    by entry, the newest `changed` winning; how many changed it."""
    changed = 0
    for d in entries:
        there = c.execute(
            "SELECT changed FROM ignored WHERE kind = ? AND about = ?", (d.kind, d.about)
        ).fetchone()
        if there is not None and d.changed < there[0]:
            continue
        c.execute(
            "INSERT INTO ignored (kind, about, hash, modified, changed) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (kind, about) DO UPDATE SET hash = excluded.hash,"
            " modified = excluded.modified, changed = excluded.changed",
            (d.kind, d.about, d.hash, d.modified, d.changed),
        )
        changed += 1
    return changed


def dismissals(c: sqlite3.Connection) -> list[Dismissal]:
    """The dismissals the index holds, by kind and about."""
    rows = c.execute(
        "SELECT kind, about, hash, modified, changed FROM ignored ORDER BY kind, about"
    )
    return [Dismissal(*r) for r in rows]
