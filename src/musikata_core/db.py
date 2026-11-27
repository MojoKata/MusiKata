"""The index (A2.1): musikata.db, SQLite in WAL mode, one per root on this computer. Everything in
it is rebuilt from the root's files (R1.5.1). One writer thread owns the one writing connection;
each other thread reads through a connection of its own (A1.3), so a long write never stalls a
list scrolling.

The schema has a version (PRAGMA user_version), and MIGRATIONS run in order at open, each in one
transaction. A slice that needs a table adds a migration at the end; a migration is never changed
once released (A2.10's state snapshots read every older index). So that what a migration does stays
fixed in time, it is SQL of its own and calls no other module: rows only code can work out (sort
keys, albums, folders) are left to the next scan, by marking every song to be read again (R1.5.1:
the index is rebuilt from the files, losing only time)."""

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
    """Songs and their genres (A2.1's song and song_genre), with R4.1's fields as they were then
    (a field added to FIELDS later is a migration of its own)."""
    c.execute(
        "CREATE TABLE song (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,"
        " size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, kind TEXT, length REAL,"
        " bitrate INTEGER, sample_rate INTEGER, channels INTEGER, audio_hash TEXT, error TEXT,"
        " title, artist, album, albumartist, track, tracktotal, disc, disctotal, year, date,"
        " composer, comment, compilation, rating, artistsort, albumartistsort, albumsort,"
        " rg_track_gain, rg_track_peak, rg_album_gain, rg_album_peak, has_cover)"
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
    folder table. They are worked out by the scan (folders.py, sortnames.py), whose code may change
    after this migration is released, so every song is read again by the next one, as for version
    2, and the scan fills them; the table is empty until it does."""
    c.execute("ALTER TABLE song ADD COLUMN folder TEXT")
    c.execute("ALTER TABLE song ADD COLUMN name_key TEXT")
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
    c.execute("UPDATE song SET mtime_ns = -1")


def _v5(c: sqlite3.Connection) -> None:
    """Play counts (A2.1's play, R7.9): a row for each song a computer has played, with its count
    and when it was last played, as that computer's `.musikata/<computer id>/plays.json` names it
    (A2.8): by the computer's id, the song's path and audio hash, and the song in the index it
    stands for, found by that path, else that hash (None until one is). This computer's rows are
    the counts it keeps; another's are read from its file. Filled from the files and by playing,
    so nothing needs reading again."""
    c.execute(
        "CREATE TABLE play (id INTEGER PRIMARY KEY, computer TEXT NOT NULL,"
        " song_id INTEGER REFERENCES song (id) ON DELETE SET NULL, path TEXT NOT NULL, hash TEXT,"
        " count INTEGER NOT NULL, last TEXT NOT NULL)"
    )
    c.execute("CREATE INDEX play_song ON play (song_id)")
    c.execute("CREATE INDEX play_path ON play (path)")
    c.execute("CREATE INDEX play_computer ON play (computer)")


def _v6(c: sqlite3.Connection) -> None:
    """The change history (A2.1's change and change_file, R4.9, A3.5): a row per entry of the
    root's `.musikata/history/`, by its file's name, with when and on which computer it was saved,
    what the save was and the entry it undoes, if any; and a row per file it touched, in its
    order, with the file's path and audio hash, the fields it changed (by name, comma-separated)
    and the old covers it keeps (history/images/<hash>, space-separated: the cover, or
    image, and the other pictures, R5.3). Filled from the entries' files, so nothing
    needs reading again."""
    c.execute(
        "CREATE TABLE change (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,"
        " time TEXT NOT NULL, computer TEXT NOT NULL, action TEXT NOT NULL,"
        " description TEXT NOT NULL, undoes TEXT)"
    )
    c.execute("CREATE INDEX change_time ON change (time, name)")
    c.execute("CREATE INDEX change_undoes ON change (undoes)")
    c.execute(
        "CREATE TABLE change_file (change_id INTEGER NOT NULL REFERENCES change (id)"
        " ON DELETE CASCADE, position INTEGER NOT NULL, path TEXT NOT NULL, hash TEXT,"
        " fields TEXT NOT NULL, cover TEXT, PRIMARY KEY (change_id, position))"
    )
    c.execute("CREATE INDEX change_file_cover ON change_file (cover)")


def _v7(c: sqlite3.Connection) -> None:
    """Ratings kept beside the files (R10.3, A2.8): the rating each song's file holds, apart
    (`song.file_rating`), as `song.rating` becomes the rating shown, which is the song's
    `.musikata/ratings.json` entry when its ratings are kept there; the entries of that file
    (`rating`), each by its path and audio hash as the file names it, with its stars and when
    it was set, and the song it stands for (by that path, else that hash; None until one is); and
    whether the root keeps every song's rating there (`rating_rule`, R10.3's setting), one row.
    The ratings shown so far were the files', so nothing needs reading again."""
    c.execute("ALTER TABLE song ADD COLUMN file_rating")
    c.execute("UPDATE song SET file_rating = rating")
    c.execute(
        "CREATE TABLE rating (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, hash TEXT,"
        " stars INTEGER NOT NULL, changed TEXT NOT NULL,"
        " song_id INTEGER REFERENCES song (id) ON DELETE SET NULL)"
    )
    c.execute("CREATE INDEX rating_song ON rating (song_id)")
    c.execute("CREATE TABLE rating_rule (everything INTEGER NOT NULL)")
    c.execute("INSERT INTO rating_rule VALUES (0)")


def _v8(c: sqlite3.Connection) -> None:
    """Needs attention (A2.6, R2.8): what its groups are found from, each kept by the scan so the
    count is always current without a full pass (attention.py). On each song, its names with case
    and spacing set aside, indexed with the name for the names that differ only so (`artist_nk`,
    `albumartist_nk`; `album_nk`, the album artist's and the album's: the normalised pair), its
    embedded front cover (its hash and size in pixels, R5.6) and the `.cue` sheet beside it that
    names it (an album in one file). On each album, the fields its songs differ in (`differs`),
    the size of its cover and of its folder's image. And the entries the user dismissed, from
    `.musikata/ignored.json` (A2.8, `ignored`). The keys and covers are worked out from the files,
    so every song is read again by the next scan, as for version 2."""
    for column in (
        "artist_nk TEXT", "albumartist_nk TEXT", "album_nk TEXT", "cover_key TEXT",
        "cover_width INTEGER", "cover_height INTEGER", "cue TEXT",
    ):  # fmt: skip
        c.execute(f"ALTER TABLE song ADD COLUMN {column}")
    c.execute("CREATE INDEX song_artist_nk ON song (artist_nk, artist)")
    c.execute("CREATE INDEX song_albumartist_nk ON song (albumartist_nk, albumartist)")
    c.execute("CREATE INDEX song_album_nk ON song (album_nk, album)")
    c.execute("CREATE INDEX song_cue ON song (cue) WHERE cue IS NOT NULL")
    c.execute("CREATE INDEX song_error ON song (path) WHERE error IS NOT NULL")
    for column in (
        "differs TEXT", "cover_width INTEGER", "cover_height INTEGER",
        "folder_image_width INTEGER", "folder_image_height INTEGER",
    ):  # fmt: skip
        c.execute(f"ALTER TABLE album ADD COLUMN {column}")
    c.execute(
        "CREATE INDEX album_differs ON album (artist_key, title_key) WHERE differs IS NOT NULL"
    )
    c.execute(
        "CREATE TABLE ignored (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, about TEXT NOT NULL,"
        " hash TEXT, modified REAL, changed TEXT NOT NULL, UNIQUE (kind, about))"
    )
    c.execute("UPDATE song SET mtime_ns = -1")


def _v9(c: sqlite3.Connection) -> None:
    """The same song more than once (R2.12, A2.6): each song's artist and title with case, accents
    and punctuation set aside, the normalised pair likely copies share (`copy_key`), indexed with
    the length they are compared by; exact copies are found by the `audio_hash` index of version
    1. The key is worked out from the tags (duplicates.song_key), so every song is read again by
    the next scan, as for version 2."""
    c.execute("ALTER TABLE song ADD COLUMN copy_key TEXT")
    c.execute("CREATE INDEX song_copy_key ON song (copy_key, length) WHERE copy_key IS NOT NULL")
    c.execute("UPDATE song SET mtime_ns = -1")


def _v10(c: sqlite3.Connection) -> None:
    """Text in the wrong encoding (R4.10, A3.6, A2.6): on each song, the text fields its ID3 tag
    holds as Latin-1 beyond ASCII (`latin1`, by name, comma-separated; none: NULL) and the encoding
    that reads them far better than as they are (`encoding`, a codec's name; none: NULL), indexed
    for Needs attention's group. Both are worked out as the file is read (encodings.flag), so every
    song is read again by the next scan, as for version 2."""
    c.execute("ALTER TABLE song ADD COLUMN latin1 TEXT")
    c.execute("ALTER TABLE song ADD COLUMN encoding TEXT")
    c.execute("CREATE INDEX song_encoding ON song (path) WHERE encoding IS NOT NULL")
    c.execute("UPDATE song SET mtime_ns = -1")


def _v11(c: sqlite3.Connection) -> None:
    """Tags match path (R3.9, A2.6, A2.7): on each song, whether its tags agree with its path under
    the pattern detected for its folder (`path_state`: 0 they match, 1 they can be fixed, 2 it has
    no tags; NULL: no pattern fits it) and how they differ (`path_diff`, JSON: [field, how, the
    path's value] each; NULL: they don't), indexed by folder for Needs attention's group; on each
    folder, the worst state beneath it and how many files beneath it can be fixed or have no tags
    (`path_state`, `path_fix`, R2.9.5); and the user's own patterns (R3.3, R13.4), tried before the
    presets, as the root's settings name them (`user_pattern`). The states are worked out from the
    tags and the paths (folders.match_folder), so every song is read again by the next scan, as for
    version 2."""
    c.execute("ALTER TABLE song ADD COLUMN path_state INTEGER")
    c.execute("ALTER TABLE song ADD COLUMN path_diff TEXT")
    c.execute("CREATE INDEX song_path_diff ON song (folder) WHERE path_diff IS NOT NULL")
    c.execute("ALTER TABLE folder ADD COLUMN path_state INTEGER")
    c.execute("ALTER TABLE folder ADD COLUMN path_fix INTEGER NOT NULL DEFAULT 0")
    c.execute("CREATE TABLE user_pattern (position INTEGER PRIMARY KEY, text TEXT NOT NULL)")
    c.execute("UPDATE song SET mtime_ns = -1")


def _v12(c: sqlite3.Connection) -> None:
    """Playlists (A2.1's playlist and playlist_entry, R8): a row per `.m3u` or `.m3u8` file under
    the root, by its path, with its name and its sort key, its kind, the size and modification
    time it was read at, the encoding it was read in, how many of its entries name their file by
    an absolute path, and a smart playlist's rule (R8.9; NULL: none); and a row per entry, in
    order, with its path as written, the path under the root it resolves to (NULL: outside the
    root), and its #EXTINF's seconds and text. A song is an entry's by that path, so an entry whose
    path no song has is missing (R8.7). Filled by the next scan, so nothing needs reading again."""
    c.execute(
        "CREATE TABLE playlist (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,"
        " name TEXT NOT NULL, name_key TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER NOT NULL,"
        " mtime_ns INTEGER NOT NULL, encoding TEXT NOT NULL, absolute INTEGER NOT NULL DEFAULT 0,"
        " rule TEXT)"
    )
    c.execute("CREATE INDEX playlist_order ON playlist (name_key, path)")
    c.execute(
        "CREATE TABLE playlist_entry (id INTEGER PRIMARY KEY, playlist_id INTEGER NOT NULL"
        " REFERENCES playlist (id) ON DELETE CASCADE, position INTEGER NOT NULL,"
        " written TEXT NOT NULL, path TEXT, seconds INTEGER, title TEXT NOT NULL DEFAULT '')"
    )
    c.execute("CREATE INDEX playlist_entry_order ON playlist_entry (playlist_id, position)")
    c.execute("CREATE INDEX playlist_entry_path ON playlist_entry (path)")


def _v13(c: sqlite3.Connection) -> None:
    """When each song came into the library (`song.added`, seconds since the epoch, UTC), for a
    smart playlist's "added in the last N days" (R8.9), indexed. A song the index has already
    gets its file's modification time, the nearest the index knows; one marked to be read again
    (its modification time unknown) gets it when it is (scanner.write_batch). From then on a song
    a scan finds new is added at the scan's time, or at its file's modification time on the
    library's first scan, so a new library doesn't hold every song as added today."""
    c.execute("ALTER TABLE song ADD COLUMN added REAL")
    c.execute("UPDATE song SET added = mtime_ns / 1e9 WHERE mtime_ns > 0")
    c.execute("CREATE INDEX song_added ON song (added)")


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _v1, _v2, _v3, _v4, _v5, _v6, _v7, _v8, _v9, _v10, _v11, _v12, _v13,
]  # fmt: skip


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


class _Reading:
    """A thread's reading connection, held in the thread's own storage: when the thread ends (or
    the index closes) the connection is closed and the index lets go of it."""

    def __init__(
        self, c: sqlite3.Connection, held: dict[int, sqlite3.Connection], lock: threading.RLock
    ) -> None:
        self.c, self._held, self._lock = c, held, lock
        with lock:
            held[id(self)] = c

    def __del__(self) -> None:
        with self._lock:
            self._held.pop(id(self), None)
        self.c.close()


class Index:
    """One root's musikata.db: its writer thread and a reading connection per thread, each closed
    when its thread ends or the index closes, whichever comes first (QML's image threads read
    through it, covers.py, and outlive no index)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._jobs: queue.Queue[
            tuple[Callable[[sqlite3.Connection], object], Future[object]] | None
        ]
        self._jobs = queue.Queue()
        self._local = threading.local()
        self._reading: dict[int, sqlite3.Connection] = {}  # each thread's, by its holder
        self._reading_lock = threading.RLock()  # a holder may go (__del__) while it is held
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
            # let go of the job: a failed one's traceback holds this frame, which would hold its
            # future, and what the job and its callbacks refer to, in a cycle once it ends
            del job, fn, done
        c.close()

    def write(self, fn: Callable[[sqlite3.Connection], T]) -> Future[T]:
        """Runs fn on the writer thread in one transaction; its result, or its error, in the
        future."""
        done: Future[T] = Future()
        self._jobs.put((fn, done))  # type: ignore[arg-type]
        return done

    def read(self) -> sqlite3.Connection:
        """This thread's reading connection."""
        held: _Reading | None = getattr(self._local, "reading", None)
        if held is None:
            held = self._local.reading = _Reading(
                connect(self.path), self._reading, self._reading_lock
            )
        return held.c

    def close(self) -> None:
        """Ends the writer thread, after the writes asked for, and closes every thread's reading
        connection."""
        self._jobs.put(None)
        self._thread.join()
        self._local.reading = None
        with self._reading_lock:
            reading = list(self._reading.values())
            self._reading.clear()
        for c in reading:
            c.close()
