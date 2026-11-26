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

from . import art, folders, sortnames

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


def _v2(c: sqlite3.Connection) -> None:
    """Albums and artists (A2.1's album, R2.5) and the sort keys of R2.13 on each song. They are
    worked out from the songs' tags by the scan (albums.py), so every song is read again by the
    next one: its size and modification time no longer match its row."""
    c.execute(
        "CREATE TABLE artist (id INTEGER PRIMARY KEY, identity TEXT NOT NULL UNIQUE,"
        " name TEXT NOT NULL, sort_key TEXT NOT NULL, albums INTEGER NOT NULL DEFAULT 0,"
        " songs INTEGER NOT NULL DEFAULT 0)"
    )
    c.execute("CREATE INDEX artist_order ON artist (sort_key, id)")
    c.execute(
        "CREATE TABLE album (id INTEGER PRIMARY KEY, identity TEXT NOT NULL UNIQUE,"
        " artist TEXT NOT NULL, title TEXT NOT NULL, artist_key TEXT NOT NULL,"
        " title_key TEXT NOT NULL, artist_id INTEGER REFERENCES artist (id) ON DELETE SET NULL,"
        " compilation INTEGER NOT NULL DEFAULT 0, year INTEGER, genre TEXT,"
        " songs INTEGER NOT NULL DEFAULT 0, length REAL NOT NULL DEFAULT 0,"
        " size INTEGER NOT NULL DEFAULT 0, embedded INTEGER NOT NULL DEFAULT 0,"
        " folder TEXT NOT NULL, folder_image TEXT, folder_image_size INTEGER,"
        " folder_image_mtime INTEGER, cover_kind TEXT, cover TEXT, thumb TEXT)"
    )
    c.execute("CREATE INDEX album_order ON album (artist_key, title_key, id)")
    c.execute("CREATE INDEX album_artist ON album (artist_id)")
    c.execute("CREATE INDEX album_thumb ON album (thumb)")
    for column in (
        "album_id INTEGER REFERENCES album (id) ON DELETE SET NULL",
        "artist_id INTEGER REFERENCES artist (id) ON DELETE SET NULL",
        "artist_key TEXT",
        "album_key TEXT",
    ):
        c.execute(f"ALTER TABLE song ADD COLUMN {column}")
    c.execute("CREATE INDEX song_album ON song (album_id, disc, track, path)")
    c.execute("CREATE INDEX song_artist ON song (artist_id)")
    c.execute("UPDATE song SET mtime_ns = -1")


def _v3(c: sqlite3.Connection) -> None:
    """Search (A2.5, R2.7): song_fts, FTS5 over each song's title, artist, album, album artist,
    genres, year and file name, its rowid the song's id, case and accents aside. It is filled
    from the rows there, so no song needs reading again; the scan keeps it from then on
    (search.py)."""
    c.execute(
        "CREATE VIRTUAL TABLE song_fts USING fts5(title, artist, album, albumartist, genre, year,"
        " filename, tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3')"
    )
    c.execute(
        "INSERT INTO song_fts (rowid, title, artist, album, albumartist, genre, year, filename)"
        " SELECT id, title, artist, album, albumartist,"
        " (SELECT group_concat(genre, ' ') FROM song_genre WHERE song_id = song.id), year,"
        " substr(path, length(rtrim(path, replace(path, '/', ''))) + 1) FROM song"
    )


def _v4(c: sqlite3.Connection) -> None:
    """Folders (A2.7, R2.9): each song's folder and its file name's sort key (R2.9.2), and the
    folder table, filled from the rows there, so no song needs reading again; each folder's cover
    image is the one its albums' rows name, until the next scan walks it. The scan keeps them from
    then on (folders.py)."""
    c.execute("ALTER TABLE song ADD COLUMN folder TEXT")
    c.execute("ALTER TABLE song ADD COLUMN name_key TEXT")
    c.executemany(
        "UPDATE song SET folder = ?, name_key = ? WHERE id = ?",
        [
            (path.rpartition("/")[0], sortnames.key_of(path.rpartition("/")[2]), song_id)
            for song_id, path in c.execute("SELECT id, path FROM song").fetchall()
        ],
    )
    c.execute("CREATE INDEX song_folder ON song (folder, name_key, path)")
    c.execute(
        "CREATE TABLE folder (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, parent TEXT,"
        " name TEXT NOT NULL, name_key TEXT NOT NULL, fold TEXT NOT NULL,"
        " folders INTEGER NOT NULL DEFAULT 0, songs INTEGER NOT NULL DEFAULT 0,"
        " folders_beneath INTEGER NOT NULL DEFAULT 0, songs_beneath INTEGER NOT NULL DEFAULT 0,"
        " length REAL NOT NULL DEFAULT 0, artist TEXT, album TEXT, year INTEGER, image TEXT,"
        " image_size INTEGER, image_mtime INTEGER, cover_kind TEXT, cover TEXT, thumb TEXT,"
        " mosaic TEXT)"
    )
    c.execute("CREATE INDEX folder_parent ON folder (parent, name_key, path)")
    c.execute("CREATE INDEX folder_thumb ON folder (thumb)")
    images: dict[str, list[art.Image]] = {}
    for folder, image, size, mtime in c.execute(
        "SELECT folder, folder_image, folder_image_size, folder_image_mtime FROM album"
        " WHERE folder_image IS NOT NULL"
    ):
        images.setdefault(folder, []).append(art.Image(image.rpartition("/")[2], size, mtime))
    folders.rebuild(c, images)


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [_v1, _v2, _v3, _v4]


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
