"""What's playing, kept across restarts (R1.8, R7.2, A2.8): the queue, which of its songs is
current and the place in it, in `<root>/.musikata/<computer id>/now-playing.json`, a file of this
computer's alone, as its play counts are (A2.8). When the root's `.musikata` can't be written
(R1.5.2), the same file is kept beside the root's index instead; reading prefers the root's copy
when both are there and it is the newer.

Each song is named by its path under the root and its audio hash (A2.3), as in the root's other
files, so a song moved or renamed (R2.3) is found again by its hash; one found by neither is
dropped, and when that is the current one, the queue starts at the next one still there, from its
start. A file broken in any way (cut short by a sync, not JSON, the wrong shapes) is logged and an
empty queue used (R13.9's way); a value it can't use takes its default; a newer format is read for
what it can and never written (A2.10). The fields it doesn't know are kept when it is written.

The file is written whole (A2.8: a temporary file moved over it) when the queue changes, on
pause, at quit, and at most once a minute while playing (`Keeper`), so a crash loses at most a
minute of the place; `Keeping` writes it on a thread of its own, never the GUI's, and the shared
settings' shuffle and repeat (R7.3) with it."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import settings
from .audio.queue import Queue
from .clock import Clock

log = logging.getLogger(__name__)
FORMAT = 1  # now-playing.json's format (A2.10)
NAME = "now-playing.json"
EVERY = 60.0  # seconds between writes while playing, at most (A2.8's rhythm)
CHUNK = 500  # songs looked up in the index at a time
HASH = re.compile(r"[0-9a-f]{64}")
KNOWN = frozenset({"format", "saved", "source", "current", "position", "songs"})
KNOWN_SONG = frozenset({"path", "hash", "added", "unshuffled"})
QUEUE, PAUSE, TICK, QUIT = "queue", "pause", "tick", "quit"  # why it may be written (`Keeper`)


@dataclass(frozen=True)
class Song:
    """A song of the queue as the file names it: its path under the root, its audio hash (None:
    not known) and whether the user added it (Play next, Add to queue, R7.2)."""

    path: str
    hash: str | None = None
    added: bool = False


@dataclass(frozen=True)
class Kept:
    """The file as read: its songs in the order they play, each one's place in the order shuffle
    off returns to (R7.3), the current one's place among them (None: the queue has played out,
    or is empty) and the seconds into it, and where the queue comes from (Up next's "Playing
    from"). `saved` is when it was written (None: not known), `extras` its fields this version
    doesn't know and `song_extras` each song's, by path, which a rewrite keeps (A2.10); `newer`, a
    newer MusiKata's format, never written; `broken`, a file that couldn't be used at all;
    `problems`, what couldn't be used, for the log."""

    songs: tuple[Song, ...] = ()
    unshuffled: tuple[int, ...] = ()
    current: int | None = None
    position: float = 0.0
    source: str = ""
    saved: datetime | None = None
    extras: Mapping[str, object] = field(default_factory=dict)
    song_extras: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    newer: bool = False
    broken: bool = False
    problems: tuple[str, ...] = ()


def _broken(why: str) -> Kept:
    return Kept(broken=True, problems=(f"{why}: the queue starts empty",))


def _song(value: object, problems: list[str]) -> tuple[Song, int | None, dict[str, object]] | None:
    """An entry of `songs`, its place unshuffled (None: none that can be used) and its fields
    this version doesn't know; None when it isn't one."""
    if not isinstance(value, dict):
        return None
    path = value.get("path")
    if not isinstance(path, str) or not path:
        return None
    hash_ = value.get("hash")
    if isinstance(hash_, str) and HASH.fullmatch(hash_.lower()):
        hash_ = hash_.lower()
    elif hash_ is not None:
        problems.append(f"{path}: its hash isn't an audio hash: {hash_!r}; found by its path only")
        hash_ = None
    added = value.get("added", False)
    if not isinstance(added, bool):
        problems.append(f"{path}: added isn't true or false: {added!r}; not added")
        added = False
    place = value.get("unshuffled")
    if not (isinstance(place, int) and not isinstance(place, bool)):
        place = None
    extras = {k: v for k, v in value.items() if k not in KNOWN_SONG}
    return Song(path, hash_, added), place, extras


def _number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def parse(text: str) -> Kept:
    """What's playing in `text`, now-playing.json's content, whatever was written there: a file
    that can't be used whole gives an empty queue, and a value that can't be used its default,
    each named in `problems` (R13.9)."""
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
    listed = data.get("songs", [])
    if not isinstance(listed, list):
        return _broken(f"songs isn't a list: {listed!r}")
    songs: list[Song] = []
    places: list[int | None] = []
    song_extras: dict[str, Mapping[str, object]] = {}
    for value in listed:
        read = _song(value, problems)
        if read is None:
            return _broken(f"a song isn't a path under the root: {value!r}")
        songs.append(read[0])
        places.append(read[1])
        if read[2]:
            song_extras[read[0].path] = read[2]
    if sorted(p if p is not None else -1 for p in places) == list(range(len(songs))):
        unshuffled = tuple(p for p in places if p is not None)
    else:  # none given is the order they play in, as a person might write it
        if any(p is not None for p in places) or any("unshuffled" in v for v in listed):
            problems.append("the songs' unshuffled places aren't one each: in the order they play")
        unshuffled = tuple(range(len(songs)))
    current: int | None = 0 if songs else None
    if "current" in data:
        value = data["current"]
        if value is None:
            current = None
        elif isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(songs):
            current = value
        else:
            problems.append(f"current isn't one of its songs: {value!r}; the first")
    position = _number(data.get("position", 0.0))
    if position is None or position < 0:
        problems.append(f"position isn't seconds: {data.get('position')!r}; the start")
        position = 0.0
    source = data.get("source", "")
    if not isinstance(source, str):
        problems.append(f"source isn't text: {source!r}")
        source = ""
    saved: datetime | None = None
    if isinstance(data.get("saved"), str):
        try:
            saved = datetime.fromisoformat(data["saved"])
        except ValueError:
            saved = None
        if saved is not None and saved.tzinfo is None:
            saved = None  # A2.10's times are UTC, and say so
    if saved is None and "saved" in data:
        problems.append(f"saved isn't a time: {data['saved']!r}")
    return Kept(
        songs=tuple(songs),
        unshuffled=unshuffled,
        current=current,
        position=position if current is not None else 0.0,
        source=source,
        saved=saved,
        extras={k: v for k, v in data.items() if k not in KNOWN},
        song_extras=song_extras,
        newer=newer,
        problems=tuple(problems),
    )


# ---------- where it is ----------


@dataclass(frozen=True)
class Places:
    """Where the file is kept: `musikata`, the root's `.musikata` folder, None when it can't be
    written (R1.5.2); `local`, the file beside the root's index, used then; and this computer's
    id (A2.8), which names its folder in `.musikata`, None until it has one."""

    musikata: str | None
    local: str
    computer: str | None = None

    def root_file(self, computer: str | None = None) -> str | None:
        """The file in the root's `.musikata`, under this computer's id; None when there is no
        id, or `.musikata` can't be written."""
        computer = computer or self.computer
        if self.musikata is None or computer is None:
            return None
        return os.path.join(self.musikata, computer, NAME)


def places(root: str, index_folder: str, computer: str | None) -> Places:
    """Where the root's file is kept on this computer: in its `.musikata` when that can be
    written, else beside its index in `index_folder` (A2.9)."""
    musikata = os.path.join(root, ".musikata")
    writable = os.path.isdir(musikata) and os.access(musikata, os.W_OK)
    return Places(musikata if writable else None, os.path.join(index_folder, NAME), computer)


def _read(path: str) -> Kept | None:
    """The file at `path`, each problem logged; None when there is none."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        kept = _broken(f"it couldn't be read ({e})")
    else:
        kept = parse(text)
    for problem in kept.problems:
        log.warning("%s: %s", path, problem)
    return kept


def load(where: Places) -> Kept:
    """What's playing as last kept: the root's file, or the one beside the index when only it is
    there or it is the newer (a root that couldn't be written for a while, R1.5.2); a file that
    can't be used gives way to the other. Nothing kept: an empty queue."""
    found: list[Kept] = []
    for path in (where.root_file(), where.local):
        kept = _read(path) if path is not None else None
        if kept is not None and not kept.broken:
            found.append(kept)
    if not found:
        return Kept()
    if len(found) == 2:
        root, local = found
        oldest = datetime.min.replace(tzinfo=UTC)
        return root if (root.saved or oldest) > (local.saved or oldest) else local
    return found[0]


# ---------- matching it to the index ----------


Finder = Callable[[Sequence[Song]], list[int | None]]


def finder(c: sqlite3.Connection) -> Finder:
    """Finds songs in the index on `c`: each by its path, else by its audio hash (moved or
    renamed, A2.8, R2.3), the first by path when several have that hash; None when neither."""

    def find(songs: Sequence[Song]) -> list[int | None]:
        by_path = _lookup(c, "path", [s.path for s in songs])
        hashes = [s.hash for s in songs if s.path not in by_path and s.hash is not None]
        by_hash = _lookup(c, "audio_hash", hashes) if hashes else {}
        return [
            by_path.get(s.path, by_hash.get(s.hash) if s.hash is not None else None) for s in songs
        ]

    return find


def _lookup(c: sqlite3.Connection, column: str, values: Sequence[str]) -> dict[str, int]:
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


@dataclass(frozen=True)
class State:
    """The queue as kept: its songs by id in the order they play, each with whether the user
    added it; each one's place unshuffled; the current one's place (len(songs): played out); the
    seconds into it; and where the queue comes from."""

    songs: tuple[tuple[int, bool], ...] = ()
    unshuffled: tuple[int, ...] = ()
    cursor: int = 0
    position: float = 0.0
    source: str = ""

    def same_queue(self, other: State) -> bool:
        """The same songs in the same orders, from the same place: only the current song or the
        place in it differ."""
        return (self.songs, self.unshuffled, self.source) == (
            other.songs,
            other.unshuffled,
            other.source,
        )


def state_of(queue: Queue, position: float) -> State:
    """The queue's state to keep, `position` seconds into its current song."""
    order = queue.order
    return State(
        tuple((e.song, e.added) for e in order),
        tuple(queue.unshuffled),
        queue.cursor,
        position if queue.current is not None else 0.0,
        queue.source,
    )


def _present(state: State, there: Sequence[bool]) -> State:
    """`state` with only the songs `there` says are: their unshuffled places closed up, and, when
    the current song is gone, the next one still there current from its start (none: played
    out)."""
    keep = [i for i, here in enumerate(there) if here]
    if len(keep) == len(state.songs):
        return state
    rank = {i: r for r, i in enumerate(sorted(keep, key=lambda i: state.unshuffled[i]))}
    cursor = sum(1 for i in keep if i < state.cursor)
    gone = state.cursor < len(state.songs) and not there[state.cursor]
    return State(
        tuple(state.songs[i] for i in keep),
        tuple(rank[i] for i in keep),
        cursor,
        0.0 if gone or cursor >= len(keep) else state.position,
        state.source,
    )


def restore(kept: Kept, find: Finder) -> tuple[State, int]:
    """The queue to rebuild from `kept` (R1.8), its songs found in the index by `find`, and how
    many were dropped, found by neither path nor hash."""
    ids = find(kept.songs) if kept.songs else []
    whole = State(
        tuple((song or 0, s.added) for song, s in zip(ids, kept.songs, strict=True)),
        kept.unshuffled,
        len(kept.songs) if kept.current is None else kept.current,
        kept.position,
        kept.source,
    )
    there = [song is not None for song in ids]
    for s, here in zip(kept.songs, there, strict=True):
        if not here:
            log.info("%s is no longer in the library: it leaves the queue", s.path)
    return _present(whole, there), there.count(False)


# ---------- writing it ----------


def rows_of(c: sqlite3.Connection, ids: Sequence[int]) -> dict[int, tuple[str, str | None]]:
    """The path and audio hash of each song of `ids` the index has, by id."""
    out: dict[int, tuple[str, str | None]] = {}
    wanted = list(dict.fromkeys(ids))
    for i in range(0, len(wanted), CHUNK):
        chunk = wanted[i : i + CHUNK]
        marks = ", ".join("?" * len(chunk))
        for song, path, hash_ in c.execute(
            f"SELECT id, path, audio_hash FROM song WHERE id IN ({marks})", chunk
        ):
            out[song] = (path, hash_)
    return out


def document(
    state: State,
    rows: Mapping[int, tuple[str, str | None]],
    saved: datetime,
    kept: Kept | None = None,
) -> dict[str, object]:
    """The file's content for `state`, each song named by its path and hash in `rows` (one gone
    from the index since is left out), written at `saved`; the fields `kept`, the file as read,
    had that this version doesn't know are kept (A2.10)."""
    state = _present(state, [song in rows for song, _ in state.songs])
    extras = kept.extras if kept is not None else {}
    song_extras = kept.song_extras if kept is not None else {}
    songs: list[dict[str, object]] = []
    for (song, added), place in zip(state.songs, state.unshuffled, strict=True):
        path, hash_ = rows[song]
        entry: dict[str, object] = {**song_extras.get(path, {}), "path": path}
        if hash_ and HASH.fullmatch(hash_):
            entry["hash"] = hash_
        entry.update(added=added, unshuffled=place)
        songs.append(entry)
    playing = state.cursor < len(state.songs)
    return {
        **extras,
        "format": FORMAT,
        "saved": saved.isoformat().replace("+00:00", "Z"),
        "source": state.source,
        "current": state.cursor if playing else None,
        "position": round(state.position, 3) if playing else 0.0,
        "songs": songs,
    }


def write(where: Places, data: Mapping[str, object], computer: str | None) -> str | None:
    """Writes `data` to the root's file under `computer`, or, when `.musikata` can't be written
    (R1.5.2) or there is no id, to the one beside the index; the path written, None when neither
    could be (logged)."""
    for path in (where.root_file(computer), where.local):
        if path is not None and settings.save(path, data):
            return path
    return None


class Keeper:
    """When the file is written (A2.8's rhythm): when the queue changes (its songs, their orders
    or where it comes from), on pause and at quit when anything changed, and while playing at most
    once a minute, on `clock`; never what was written last again."""

    def __init__(self, clock: Clock, every: float = EVERY) -> None:
        self._clock, self._every = clock, every
        self._last: State | None = None
        self._at = clock.monotonic()

    def settle(self, state: State) -> None:
        """`state` is what the file holds now (as restored at start): nothing to write for it."""
        self._last, self._at = state, self._clock.monotonic()

    def ticks(self) -> bool:
        """A minute has gone since the last write: while playing, the place is due."""
        return self._clock.monotonic() - self._at >= self._every

    def due(self, state: State, why: str) -> bool:
        """Whether `state`, changed for `why` (QUEUE, PAUSE, TICK or QUIT), is written now; when
        it is, it is taken as written."""
        last = self._last
        if last is not None and state == last:
            return False
        if why == QUEUE:
            due = last is None or not state.same_queue(last)
        elif why == TICK:
            due = self.ticks()
        else:
            due = True
        if due:
            self.settle(state)
        return due


class Keeping:
    """Keeps what's playing in the root's file (`Places`), and the shuffle and repeat (R7.3) and
    Now Playing's visualization (R11.4.5) in the shared settings, each write a job on one thread
    of its own, in the order asked, so no two writes of the shared settings overlap: the GUI
    thread never waits on a file. `read` gives that thread its connection to the index, where a
    song's id becomes its path and hash; `computer` gives this computer's id, made and kept in the
    shared settings the first time it is needed (`settings.computer_id`); `set_playback` and
    `set_appearance` write the shared settings' playback and appearance fields,
    `set_mini_player` the mini player's (R15.2, R15.3), and `set_equalizer` the equalizer's
    (R19.5). `kept` is the
    file as read at start: a newer format is never written, and the fields it doesn't know are
    kept."""

    def __init__(
        self,
        where: Places,
        read: Callable[[], sqlite3.Connection],
        clock: Clock,
        kept: Kept | None = None,
        computer: Callable[[], str | None] | None = None,
        set_playback: Callable[..., bool] | None = None,
        executor: Executor | None = None,
        set_appearance: Callable[..., bool] | None = None,
        set_mini_player: Callable[..., bool] | None = None,
        set_equalizer: Callable[..., bool] | None = None,
    ) -> None:
        self._where, self._read, self._clock = where, read, clock
        self._set_mini_player, self._set_equalizer = set_mini_player, set_equalizer
        self._kept = kept
        self._computer, self._made_computer = where.computer, computer
        self._set_playback, self._set_appearance = set_playback, set_appearance
        self._executor = executor
        self.keeper = Keeper(clock)
        self._newer = kept is not None and kept.newer
        if self._newer:
            log.warning("now-playing.json is a newer MusiKata's: the queue isn't kept from now on")

    def _submit(self, job: Callable[[], object]) -> Future[object]:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="now playing")
        return self._executor.submit(self._run, job)

    @staticmethod
    def _run(job: Callable[[], object]) -> object:
        try:
            return job()
        except Exception:  # a write that breaks is logged; the next one tries again
            log.exception("keeping what's playing failed")
            return None

    def settle(self, state: State) -> None:
        """`state` is what's kept already (as restored at start)."""
        self.keeper.settle(state)

    def ticks(self) -> bool:
        """The minute's write is due, while playing (`Keeper.ticks`)."""
        return not self._newer and self.keeper.ticks()

    def changed(self, state: State, why: str) -> Future[object] | None:
        """The queue's `state`, changed for `why` (`Keeper.due`): written when due, off this
        thread. The future of the write, None when none is due."""
        if self._newer or not self.keeper.due(state, why):
            return None
        return self._submit(lambda: self._write(state))

    def _write(self, state: State) -> str | None:
        rows = rows_of(self._read(), [song for song, _ in state.songs])
        data = document(state, rows, self._clock.now(), self._kept)
        if self._computer is None and self._where.musikata is not None and self._made_computer:
            self._computer = self._made_computer()
        return write(self._where, data, self._computer)

    def playback(self, **fields: object) -> Future[object] | None:
        """Keeps `fields` (shuffle, repeat) in the shared settings, off this thread; None when
        there is nowhere to."""
        if self._set_playback is None:
            return None
        set_playback = self._set_playback
        return self._submit(lambda: set_playback(**fields))

    def appearance(self, **fields: object) -> Future[object] | None:
        """Keeps `fields` (the visualization, R11.4.5) in the shared settings, off this thread;
        None when there is nowhere to."""
        if self._set_appearance is None:
            return None
        set_appearance = self._set_appearance
        return self._submit(lambda: set_appearance(**fields))

    def mini_player(self, **fields: object) -> Future[object] | None:
        """Keeps `fields` (the mini player's layout, Stay on top, places: R15.2, R15.3) in the
        shared settings, off this thread; None when there is nowhere to."""
        if self._set_mini_player is None:
            return None
        set_mini_player = self._set_mini_player
        return self._submit(lambda: set_mini_player(**fields))

    def equalizer(self, **fields: object) -> Future[object] | None:
        """Keeps `fields` (the equalizer's on, preset, by_genre, presets, genres: R19.5) in the
        shared settings, off this thread; None when there is nowhere to."""
        if self._set_equalizer is None:
            return None
        set_equalizer = self._set_equalizer
        return self._submit(lambda: set_equalizer(**fields))

    def close(self) -> None:
        """Waits for the writes asked for, then ends the thread: for quitting."""
        if self._executor is not None:
            self._executor.shutdown(wait=True)
