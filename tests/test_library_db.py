"""The index (src/musikata_core/db.py; A2.1, A1.3): its migrations, one writer thread whose jobs
are each one transaction, and a reading connection per thread.

Why: an index left half-migrated, or a write that fails halfway and keeps its first half, would
make the index say something the files don't (A1.4); and an index a newer MusiKata made must be
rebuilt, not written by an older one."""

import sqlite3
import threading
import weakref

import pytest

from musikata_core import db


def test_a_new_index_is_migrated_to_the_last_version(tmp_path):
    index = db.Index(str(tmp_path / "musikata.db"))
    c = index.read()
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    cols = {r[1] for r in c.execute("PRAGMA table_info(song)")}
    assert set(db.FIELDS) <= cols and {"path", "audio_hash", "error"} <= cols
    index.close()


def test_an_index_a_newer_musikata_made_is_refused(tmp_path):
    path = str(tmp_path / "musikata.db")
    c = sqlite3.connect(path)
    c.execute(f"PRAGMA user_version = {len(db.MIGRATIONS) + 1}")
    c.close()
    with pytest.raises(db.NewerIndexError):
        db.Index(path)


def test_a_failed_migration_leaves_the_index_as_it_was(tmp_path, monkeypatch):
    def broken(c):
        c.execute("CREATE TABLE half (x)")
        raise RuntimeError("halfway")

    monkeypatch.setattr(db, "MIGRATIONS", [*db.MIGRATIONS, broken])
    c = db.connect(str(tmp_path / "musikata.db"))
    with pytest.raises(RuntimeError):
        db.migrate(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS) - 1
    assert not c.execute("SELECT name FROM sqlite_master WHERE name = 'half'").fetchall()


def test_a_migration_does_what_it_did_when_it_was_released(tmp_path, monkeypatch):
    """A migration is SQL of its own, so a field added to today's code later (a migration of its
    own) changes nothing an older migration makes."""
    monkeypatch.setattr(db, "FIELDS", (*db.FIELDS, "bpm"))
    c = db.connect(str(tmp_path / "musikata.db"))
    db.MIGRATIONS[0](c)
    cols = [r[1] for r in c.execute("PRAGMA table_info(song)")]
    assert "bpm" not in cols and cols[11:] == list(db.FIELDS[:-1])
    c.close()


def test_a_write_is_one_transaction_kept_whole_or_not_at_all(tmp_path):
    index = db.Index(str(tmp_path / "musikata.db"))

    def add(c, path):
        c.execute("INSERT INTO song (path, size, mtime_ns) VALUES (?, 1, 1)", (path,))

    def add_then_fail(c):
        add(c, "b.mp3")
        raise ValueError("no")

    index.write(lambda c: add(c, "a.mp3")).result()
    with pytest.raises(ValueError):
        index.write(add_then_fail).result()
    assert [r[0] for r in index.read().execute("SELECT path FROM song")] == ["a.mp3"]
    index.close()


def test_a_failed_write_and_what_it_holds_go_once_let_go_without_a_collection(tmp_path):
    """A1.3: the writer's frame, which a failed job's traceback holds, lets go of the job's
    future, which would otherwise keep itself, and what the job and its callbacks refer to (a
    window's Library), in a cycle that only a garbage collection, on any thread, would free."""
    index = db.Index(str(tmp_path / "musikata.db"))
    held = threading.Event()  # what a job refers to

    def fail(c, held=held):
        raise ValueError("no")

    done = index.write(fail)
    done.add_done_callback(lambda f, held=held: None)
    assert isinstance(done.exception(), ValueError)
    index.close()
    gone = weakref.ref(held)
    del held, done, fail
    assert gone() is None


def test_each_thread_reads_through_a_connection_of_its_own(tmp_path):
    index = db.Index(str(tmp_path / "musikata.db"))
    mine = index.read()
    theirs = []
    t = threading.Thread(target=lambda: theirs.append(index.read()))
    t.start()
    t.join()
    assert mine is index.read() and theirs[0] is not mine
    index.close()


def test_closing_the_index_closes_every_threads_reading_connection(tmp_path):
    """QML's image threads read covers through the index (covers.py) and outlive no index: each
    one's connection is closed with it, not left open until the thread ends."""
    index = db.Index(str(tmp_path / "musikata.db"))
    opened, go_on = [], threading.Event()

    def reader():
        opened.append(index.read())
        go_on.wait()

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    try:
        while len(opened) < 3:
            threading.Event().wait(0.001)
        opened.append(index.read())
        index.close()
        for c in opened:
            with pytest.raises(sqlite3.ProgrammingError):
                c.execute("SELECT 1")
    finally:
        go_on.set()
        for t in threads:
            t.join()


def test_a_thread_that_ends_lets_go_of_its_reading_connection(tmp_path):
    index = db.Index(str(tmp_path / "musikata.db"))
    opened = []
    for _ in range(3):
        t = threading.Thread(target=lambda: opened.append(index.read()))
        t.start()
        t.join()
    for c in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")
    index.close()


def test_an_index_of_slice_2_gains_albums_and_artists_and_its_songs_are_read_again(tmp_path):
    """Version 2 (R2.5, R2.13): albums and artists are worked out from the tags by the scan, so
    the migration marks every song changed and the next scan reads them all."""
    path = str(tmp_path / "musikata.db")
    c = db.connect(path)
    db.MIGRATIONS[0](c)
    c.execute("PRAGMA user_version = 1")
    c.execute("INSERT INTO song (path, size, mtime_ns, album) VALUES ('a.flac', 10, 5, 'X')")
    assert db.migrate(c) == len(db.MIGRATIONS)
    assert c.execute("SELECT path, size, mtime_ns, album_id FROM song").fetchall() == [
        ("a.flac", 10, -1, None)
    ]
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"album", "artist"} <= tables
    c.close()
