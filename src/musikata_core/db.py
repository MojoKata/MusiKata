"""The index (A2.1): musikata.db, SQLite in WAL mode, one per root on this computer. Everything in
it is rebuilt from the root's files (R1.5.1). One writer thread owns the one writing connection;
each other thread reads through a connection of its own (A1.3), so a long write never stalls a
list scrolling.

The schema has a version (PRAGMA user_version), and MIGRATIONS run in order at open, each in one
transaction. A slice that needs a table adds a migration at the end; a migration is never changed
once released (A2.10's state snapshots read every older index)."""

from __future__ import annotations

import queue
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import TypeVar

T = TypeVar("T")

# R4.1's fields as the song table's columns, in Tags' order
FIELDS = (
    "title", "artist", "album", "albumartist", "track", "tracktotal", "disc", "disctotal",
    "year", "date", "composer", "comment", "compilation", "rating", "artistsort",
    "albumartistsort", "albumsort", "rg_track_gain", "rg_track_peak", "rg_album_gain",
    "rg_album_peak", "has_cover",
)  # fmt: skip


def _v1(c: sqlite3.Connection) -> None:
    """Songs and their genres (A2.1's song and song_genre)."""
    c.execute(
        "CREATE TABLE song (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,"
        " size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, kind TEXT, length REAL,"
        " bitrate INTEGER, sample_rate INTEGER, channels INTEGER, audio_hash TEXT, error TEXT, "
        + ", ".join(FIELDS)
        + ")"
    )
    c.execute("CREATE INDEX song_audio_hash ON song (audio_hash)")
    c.execute(
        "CREATE TABLE song_genre (song_id INTEGER NOT NULL REFERENCES song (id) ON DELETE CASCADE,"
        " position INTEGER NOT NULL, genre TEXT NOT NULL, PRIMARY KEY (song_id, position))"
    )
    c.execute("CREATE INDEX song_genre_genre ON song_genre (genre)")


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [_v1]


def connect(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = 5000")
    return c


def migrate(c: sqlite3.Connection) -> int:
    """Runs the migrations this index hasn't had, each in one transaction; returns the version.
    An index of a newer MusiKata (a version past the last migration) is refused, never
    written: it is rebuilt instead (R1.5.1)."""
    version = int(c.execute("PRAGMA user_version").fetchone()[0])
    if version > len(MIGRATIONS):
        raise NewerIndexError(
            f"the index is version {version}; this MusiKata knows {len(MIGRATIONS)}"
        )
    for n, step in enumerate(MIGRATIONS[version:], version + 1):
        c.execute("BEGIN IMMEDIATE")
        try:
            step(c)
            c.execute(f"PRAGMA user_version = {n}")
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
    return len(MIGRATIONS)


class NewerIndexError(Exception):
    """An index a newer MusiKata made."""


class Index:
    """One root's musikata.db: its writer thread and a reading connection per thread."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._jobs: queue.Queue[
            tuple[Callable[[sqlite3.Connection], object], Future[object]] | None
        ]
        self._jobs = queue.Queue()
        self._local = threading.local()
        writer = connect(path)
        migrate(writer)
        self._thread = threading.Thread(
            target=self._run, args=(writer,), name="index writer", daemon=True
        )
        self._thread.start()

    def _run(self, c: sqlite3.Connection) -> None:
        while (job := self._jobs.get()) is not None:
            fn, done = job
            if not done.set_running_or_notify_cancel():
                continue
            try:
                c.execute("BEGIN IMMEDIATE")
                result = fn(c)
                c.execute("COMMIT")
                done.set_result(result)
            except BaseException as e:
                if c.in_transaction:
                    c.execute("ROLLBACK")
                done.set_exception(e)
        c.close()

    def write(self, fn: Callable[[sqlite3.Connection], T]) -> Future[T]:
        """Runs fn on the writer thread in one transaction; its result, or its error, in the
        future."""
        done: Future[T] = Future()
        self._jobs.put((fn, done))  # type: ignore[arg-type]
        return done

    def read(self) -> sqlite3.Connection:
        """This thread's reading connection."""
        c: sqlite3.Connection | None = getattr(self._local, "c", None)
        if c is None:
            c = connect(self.path)
            self._local.c = c
        return c

    def close(self) -> None:
        self._jobs.put(None)
        self._thread.join()
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None
