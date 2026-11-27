"""Ratings where they are kept (src/musikata_core/ratings.py; R10.1, R10.3, R10.4, A2.8, A2.10):
where each song's rating goes, the root's `ratings.json` read in whatever shape another computer,
a person or a sync left it, merged entry by entry and written again, the rating each song shows
worked out in the index, and a save's writer that puts each rating where it goes.

Why: ratings.json is data from outside (testing.md, "Shapes": `ratings`), written by any computer
sharing the root; a rating set on one computer must never be lost to another's write, a broken
file must never be written over, and a song moved in a file manager must keep its rating."""

import json
import os
import sqlite3
from datetime import UTC, datetime

import jsonschema
import pytest
from fakes import FakeClock, wav
from hypothesis import given
from hypothesis import strategies as st

from musikata_core import db, ratings, rootfiles, scanner, search
from musikata_core.ratings import Entry, RatingsError, Writing
from musikata_core.tags import AudioInfo, Job, Tags, WriteError, Written

SCHEMA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "musikata_core", "schemas",
    "ratings.v1.schema.json",
)  # fmt: skip
H1, H2, H3 = "1" * 64, "2" * 64, "3" * 64
T1, T2, T3 = "2026-11-24T18:02:13Z", "2026-11-25T09:00:00Z", "2026-11-26T12:00:00Z"
EXAMPLE = {
    "format": 1,
    "songs": [{"path": "LD/GH/04 Signal Fires.wav", "hash": H1, "stars": 5, "changed": T1}],
}


def valid(doc):
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))


def parse(doc):
    return ratings.parse(json.dumps(doc))


# ---------- where a rating goes (R10.3, R10.4) ----------


def test_a_rating_goes_into_the_file_unless_its_kind_cant_hold_one_or_the_setting_says_not():
    """R10.3, R10.4: MP3, FLAC, Ogg, Opus and M4A hold their rating; WAV and AIFF can't; the
    setting keeps every one in ratings.json."""
    for kind in ("mp3", "flac", "ogg", "opus", "aac", "alac"):
        assert ratings.in_file(kind, True) and not ratings.in_file(kind, False)
    for kind in ("wav", "aiff", None):
        assert not ratings.in_file(kind, True) or kind is None
    assert not ratings.in_file("wav", True) and not ratings.in_file("aiff", True)


# ---------- the file, as plain data ----------


def test_a2_10s_example_reads_as_written_and_writes_back_the_same():
    got = parse(EXAMPLE)
    assert got.entries == (Entry("LD/GH/04 Signal Fires.wav", H1, 5, T1),)
    assert not got.problems and not got.newer and not got.broken
    assert ratings.document(got.entries, got) == EXAMPLE
    valid(ratings.document(got.entries, got))


def test_a_file_that_cant_be_used_whole_gives_no_ratings_and_says_why():
    """Shapes: empty, cut short by a sync, not JSON, not an object, songs not a list."""
    for text in ("", '{"format": 1, "songs": [{"path": "a.wav"', "nope", "[]", "12",
                 '{"songs": {"a": 1}}'):  # fmt: skip
        got = ratings.parse(text)
        assert got.broken and got.entries == () and got.problems, text


def test_shapes_of_a_ratings_fields_each_read_for_what_can_be_used():
    """Shapes: stars as text or 4.0, out of range, a bool, null; a hash in upper case, missing or
    not a hash (found by path only); changed missing, without its zone, in another zone, not a
    time (the oldest there is); a path missing or empty; a song not an object."""
    got = parse({"format": 1, "songs": [
        {"path": "a.wav", "hash": H1.upper(), "stars": "4", "changed": "2026-11-24T19:02:13+01:00"},
        {"path": "b.wav", "hash": "nope", "stars": 3.0, "changed": "2026-11-24T18:02:13"},
        {"path": "c.wav", "stars": 0},
        {"path": "d.wav", "hash": H2, "stars": 6, "changed": T1},
        {"path": "e.wav", "hash": H2, "stars": True, "changed": T1},
        {"path": "f.wav", "hash": H2, "stars": None, "changed": T1},
        {"path": "g.wav", "hash": H2, "stars": -1, "changed": T1},
        {"path": "", "hash": H2, "stars": 1, "changed": T1},
        {"hash": H2, "stars": 1, "changed": T1},
        "h.wav",
    ]})  # fmt: skip
    assert got.entries == (
        Entry("a.wav", H1, 4, T1),
        Entry("b.wav", None, 3, rootfiles.UNKNOWN),
        Entry("c.wav", None, 0, rootfiles.UNKNOWN),
    )
    assert len(got.problems) == 11 and not got.broken


def test_a_song_named_twice_is_one_the_newest_winning():
    got = parse({"format": 1, "songs": [
        {"path": "a.wav", "hash": H1, "stars": 2, "changed": T2},
        {"path": "a.wav", "hash": H1, "stars": 5, "changed": T1},
        {"path": "b.wav", "hash": H2, "stars": 1, "changed": T1},
        {"path": "b.wav", "hash": H2, "stars": 4, "changed": T2},
    ]})  # fmt: skip
    assert got.entries == (Entry("a.wav", H1, 2, T2), Entry("b.wav", H2, 4, T2))


def test_fields_in_another_order_or_unknown_are_kept_and_a_bom_is_read():
    doc = {"songs": [{"changed": T1, "stars": 5, "rated_by": "Ana", "hash": H1, "path": "a.wav"}],
           "format": 1, "note": "from a newer MusiKata"}  # fmt: skip
    got = ratings.parse("﻿" + json.dumps(doc))
    assert got.entries == (Entry("a.wav", H1, 5, T1),) and not got.problems
    written = ratings.document(got.entries, got)
    assert written["note"] == "from a newer MusiKata"
    assert written["songs"] == [{"rated_by": "Ana", "path": "a.wav", "hash": H1, "stars": 5,
                                 "changed": T1}]  # fmt: skip
    valid(written)


def test_a_newer_format_is_read_and_flagged_and_a_format_of_another_type_read_as_1():
    assert parse({**EXAMPLE, "format": 2}).newer
    got = parse({**EXAMPLE, "format": "1"})
    assert not got.newer and got.entries and got.problems
    assert parse({"songs": EXAMPLE["songs"]}).entries  # format missing: read as 1


def test_a_song_without_an_audio_hash_is_kept_out_of_the_file():
    assert ratings.document([Entry("a.wav", None, 3, T1)])["songs"] == []


@given(st.text(max_size=300))
def test_any_text_at_all_gives_ratings_or_none_never_an_error(text):
    got = ratings.parse(text)
    assert all(0 <= e.stars <= 5 and e.path for e in got.entries)


entries = st.lists(
    st.builds(Entry, st.sampled_from(["a.wav", "b.wav", "c.aiff"]), st.just(H1),
              st.integers(0, 5), st.sampled_from([T1, T2, T3])),
    max_size=3,
    unique_by=lambda e: e.path,  # a file names a song once (parse)
)  # fmt: skip


@given(entries, entries)
def test_merging_keeps_each_songs_newest_rating_whichever_file_it_came_from(kept, mine):
    """A2.8: entry by entry, the newest `changed` winning, a tie going to this computer's."""
    merged = {e.path: e for e in ratings.merge(kept, mine)}
    for path in {e.path for e in kept + mine}:
        newest = max(e.changed for e in kept + mine if e.path == path)
        assert merged[path].changed == newest
        own = [e for e in mine if e.path == path and e.changed == newest]
        if own:
            assert merged[path] == own[-1]


# ---------- the file on disk ----------


def test_saving_reads_the_file_again_so_another_computers_rating_is_kept(tmp_path):
    """A2.8: two computers rating at once lose nothing: each reads the file again before writing,
    and the newest rating of a song wins."""
    path = str(tmp_path / "ratings.json")
    ratings.save(path, [Entry("a.wav", H1, 3, T1)], lambda p: False)
    with open(path, encoding="utf-8") as f:  # meanwhile, another computer rated two songs
        doc = json.load(f)
    doc["songs"] += [{"path": "b.wav", "hash": H2, "stars": 4, "changed": T2},
                     {"path": "a.wav", "hash": H1, "stars": 1, "changed": T3}]  # fmt: skip
    doc["songs"] = doc["songs"][1:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    written = ratings.save(path, [Entry("c.wav", H3, 0, T2)], lambda p: False)
    assert written == [Entry("a.wav", H1, 1, T3), Entry("b.wav", H2, 4, T2),
                       Entry("c.wav", H3, 0, T2)]  # fmt: skip
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    valid(doc)
    assert ratings.parse(json.dumps(doc)).entries == tuple(written)
    assert not os.path.exists(path + ".tmp")


def test_an_entry_for_a_song_moved_since_goes_when_it_is_rated_where_it_is(tmp_path):
    """A2.8: the old path's entry, its audio's, is dropped once the song is rated again at its new
    path; an exact copy still at its own path keeps its own."""
    path = str(tmp_path / "ratings.json")
    ratings.save(path, [Entry("old/a.wav", H1, 3, T1), Entry("copy/a.wav", H1, 2, T1)], bool)
    written = ratings.save(path, [Entry("new/a.wav", H1, 5, T2)], lambda p: p == "old/a.wav")
    assert written == [Entry("copy/a.wav", H1, 2, T1), Entry("new/a.wav", H1, 5, T2)]


def test_a_newer_or_broken_file_isnt_written_over_and_says_why(tmp_path):
    """A2.10: a newer MusiKata's file is read, never written; one that can't be read (a sync
    bringing it) isn't written over: the rating fails, saying why."""
    path = str(tmp_path / "ratings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**EXAMPLE, "format": 2}, f)
    with pytest.raises(RatingsError, match="newer MusiKata"):
        ratings.save(path, [Entry("a.wav", H1, 3, T1)], bool)
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"format": 1, "songs": [')
    with pytest.raises(RatingsError, match="can't be read, so it isn't written over"):
        ratings.save(path, [Entry("a.wav", H1, 3, T1)], bool)
    with open(path, encoding="utf-8") as f:
        assert f.read() == '{"format": 1, "songs": ['


def test_a_file_that_cant_be_written_says_why(tmp_path):
    with pytest.raises(RatingsError, match="couldn't be written"):
        ratings.save(str(tmp_path / "gone" / "ratings.json"), [Entry("a.wav", H1, 3, T1)], bool)
    assert ratings.read(str(tmp_path / "none.json")) is None
    (tmp_path / "dir.json").mkdir()
    assert ratings.read(str(tmp_path / "dir.json")).broken


# ---------- in the index ----------


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def scanned(index, songs):
    """Rows as a scan writes them: each (path, kind, audio hash, the file's rating)."""
    batch = [
        scanner.Read(scanner.Seen(p, 1000, 1), Tags(title=p, rating=r),
                     AudioInfo(kind, 60.0, 900, 44100, 2), h)
        for p, kind, h, r in songs
    ]  # fmt: skip
    index.write(lambda c: scanner.write_batch(c, batch, {})).result()


def shown(index):
    return dict(index.read().execute("SELECT path, rating FROM song ORDER BY path"))


def test_a_wavs_entry_is_the_rating_it_shows_and_a_flac_shows_its_files(index):
    """R10.3, R10.4: a WAV's rating is read from ratings.json, over what another player put in
    its file; a FLAC's from its file, ratings.json's entry for it aside, until the setting keeps
    every rating there."""
    scanned(index, [("a.wav", "wav", H1, 2), ("b.flac", "flac", H2, 4), ("c.aiff", "aiff", H3,
                                                                      None)])  # fmt: skip
    index.write(lambda c: ratings.load(c, [
        Entry("a.wav", H1, 5, T1), Entry("b.flac", H2, 1, T1)
    ])).result()  # fmt: skip
    assert shown(index) == {"a.wav": 5, "b.flac": 4, "c.aiff": None}
    index.write(lambda c: ratings.set_everything(c, True)).result()
    assert shown(index) == {"a.wav": 5, "b.flac": 1, "c.aiff": None}
    index.write(lambda c: ratings.set_everything(c, True)).result()  # the same: nothing to do
    index.write(lambda c: ratings.set_everything(c, False)).result()
    assert shown(index) == {"a.wav": 5, "b.flac": 4, "c.aiff": None}


def test_a_rating_cleared_wins_over_the_files_and_the_newest_entry_wins(index):
    scanned(index, [("a.wav", "wav", H1, 3)])
    index.write(lambda c: ratings.load(c, [Entry("a.wav", H1, 0, T2)])).result()
    assert shown(index) == {"a.wav": 0}
    index.write(lambda c: ratings.load(c, [Entry("a.wav", H1, 4, T1)])).result()  # older
    assert shown(index) == {"a.wav": 0}
    index.write(lambda c: ratings.load(c, [Entry("a.wav", H1, 4, T3)])).result()
    assert shown(index) == {"a.wav": 4}
    assert ratings.entries_of(index.read()) == [Entry("a.wav", H1, 4, T3)]


def test_a_song_moved_keeps_its_rating_found_by_its_hash(index):
    """A2.8: an entry is matched by path, else by hash when no song has its path; a song rescanned
    keeps it; an entry whose song isn't scanned yet waits for it."""
    scanned(index, [("new/a.wav", "wav", H1, None)])
    index.write(lambda c: ratings.load(c, [
        Entry("old/a.wav", H1, 4, T1), Entry("later/b.wav", H2, 2, T1)
    ])).result()  # fmt: skip
    assert shown(index) == {"new/a.wav": 4}
    scanned(index, [("new/a.wav", "wav", H1, None), ("later/b.wav", "wav", H2, 5)])
    assert shown(index) == {"later/b.wav": 2, "new/a.wav": 4}
    scanned(index, [("old/a.wav", "wav", H1, None)])  # an exact copy back at the old path
    index.write(lambda c: ratings.load(c, [Entry("new/a.wav", H1, 1, T2)])).result()
    assert shown(index) == {"later/b.wav": 2, "new/a.wav": 1, "old/a.wav": 4}


def test_a_song_written_by_musikata_keeps_its_files_rating_apart(index, tmp_path):
    """A save's rows (scanner.wrote): a WAV whose rating ratings.json keeps reads as that, its
    file's rating left as the file has it; a FLAC's file rating is what was written."""
    root = str(tmp_path)
    scanned(index, [("a.wav", "wav", H1, 2), ("b.flac", "flac", H2, 4)])
    index.write(lambda c: ratings.load(c, [Entry("a.wav", H1, 5, T1)])).result()
    info = AudioInfo("wav", 60.0, 900, 44100, 2)
    rows = [Written(os.path.join(root, "a.wav"), Tags(title="A", rating=5), info, H1, 1000, 2),
            Written(os.path.join(root, "b.flac"), Tags(title="B", rating=1),
                    AudioInfo("flac", 60.0, 900, 44100, 2), H2, 1000, 2)]  # fmt: skip
    index.write(lambda c: scanner.wrote(c, root, rows)).result()
    got = index.read().execute("SELECT path, title, rating, file_rating FROM song ORDER BY path")
    assert got.fetchall() == [("a.wav", "A", 5, 2), ("b.flac", "B", 1, 1)]


@pytest.mark.slow
def test_an_older_index_takes_its_files_ratings_as_they_were(tmp_path):
    """db's version 7: the rating each song showed was its file's."""
    path = str(tmp_path / "old.db")
    c = db.connect(path)
    for step in db.MIGRATIONS[:6]:
        step(c)
    c.execute("PRAGMA user_version = 6")
    c.execute("INSERT INTO song (path, size, mtime_ns, rating) VALUES ('a.flac', 1, 1, 3)")
    db.migrate(c)
    assert c.execute("SELECT rating, file_rating FROM song").fetchone() == (3, 3)
    assert c.execute("SELECT everything FROM rating_rule").fetchone() == (0,)
    c.close()


# ---------- writing a save's ratings ----------


@pytest.fixture
def root(tmp_path, index):
    """A root of a WAV and an AIFF-less FLAC row, scanned, with its .musikata: (root, index)."""
    music = tmp_path / "Music"
    (music / ".musikata").mkdir(parents=True)
    wav(music / "LD" / "a.wav", 1, "Tidewater")
    h = scanner.audio_hash(str(music / "LD" / "a.wav"), "wav")
    scanned(index, [("LD/a.wav", "wav", h, None), ("LD/b.flac", "flac", H2, 3)])
    return str(music), index, h


class Files:
    """A writer of files that writes nothing: what safe.save was asked, and what it says."""

    def __init__(self):
        self.asked = []

    def __call__(self, job):
        self.asked.append(job)
        if "fail" in job.changes:
            raise WriteError(job.path, "it is read-only")
        tags = Tags(**{k: v for k, v in job.changes.items() if k in ("title", "rating")})
        return Written(job.path, tags, AudioInfo("flac", 60.0, 900, 44100, 2), H2, 7, 8,
                       Tags(title="Old"), tuple(job.changes))  # fmt: skip


def writing(root, files, write_ratings=True):
    music, index, _h = root
    return Writing(
        music, index, files, write_ratings, FakeClock(datetime(2026, 11, 26, tzinfo=UTC))
    )


def kept_file(music):
    with open(ratings.file_of(music), encoding="utf-8") as f:
        doc = json.load(f)
    valid(doc)
    return doc["songs"]


def test_a_wavs_rating_goes_to_ratings_json_and_the_index_and_reads_as_written(root):
    """R10.3, R10.4: a WAV's rating is kept in the root's ratings.json, never its file; the song
    reads as rated, for the change history (R4.9), and its row shows it at once."""
    music, index, h = root
    files = Files()
    w = writing(root, files)
    path = os.path.join(music, "LD", "a.wav")
    got = w(Job(path, {"rating": 4}))
    assert files.asked == []
    assert (got.tags.rating, got.before.rating, got.changed, got.audio_hash) == (4, 0, ("rating",),
                                                                                  h)  # fmt: skip
    assert got.tags.title == "LD/a.wav" and got.info.kind == "wav"  # its other tags as indexed
    assert kept_file(music) == [{"path": "LD/a.wav", "hash": h, "stars": 4,
                                 "changed": "2026-11-26T00:00:00Z"}]  # fmt: skip
    assert shown(index)["LD/a.wav"] == 4 and w.kept(path) == 4
    again = w(Job(path, {"rating": 4}))  # as it is already: nothing written
    assert again.changed == () and len(kept_file(music)) == 1
    assert w(Job(path, {"rating": 0})).changed == ("rating",)
    assert kept_file(music)[0]["stars"] == 0 and shown(index)["LD/a.wav"] == 0


def test_a_flacs_rating_goes_into_its_file_unless_the_setting_keeps_them_all_beside(root):
    music, index, _h = root
    files = Files()
    path = os.path.join(music, "LD", "b.flac")
    assert writing(root, files)(Job(path, {"rating": 5})).tags.rating == 5
    assert files.asked == [Job(path, {"rating": 5})]
    assert writing(root, files).kept(path) is None
    assert writing(root, files)(Job(path, {"title": "B"})).tags.title == "B"
    index.write(lambda c: ratings.set_everything(c, True)).result()
    w = writing(root, files, write_ratings=False)
    got = w(Job(path, {"rating": 2, "title": "Bee"}))
    assert files.asked[-1] == Job(path, {"title": "Bee"})  # the rest to its file
    assert (got.tags.title, got.tags.rating, got.changed) == ("Bee", 2, ("title", "rating"))
    assert [s["path"] for s in kept_file(music)] == ["LD/b.flac"]
    assert shown(index)["LD/b.flac"] == 2 and w.kept(path) == 2


def test_a_rating_that_cant_be_kept_fails_its_file_saying_why(root, tmp_path):
    """R10.2: the rating goes back and says why: ratings.json that can't be read, a song not in
    the library yet, a file whose other changes fail."""
    music, index, _h = root
    w = writing(root, Files())
    with open(ratings.file_of(music), "w", encoding="utf-8") as f:
        f.write("{")
    path = os.path.join(music, "LD", "a.wav")
    with pytest.raises(WriteError, match="ratings.json can't be read"):
        w(Job(path, {"rating": 3}))
    assert shown(index)["LD/a.wav"] is None
    with pytest.raises(WriteError, match="isn't in the library yet"):
        w(Job(os.path.join(music, "LD", "new.wav"), {"rating": 3}))
    with pytest.raises(WriteError, match="read-only"):
        w(Job(path, {"rating": 3, "fail": True}))
    index.write(lambda c: c.execute("UPDATE song SET audio_hash = NULL")).result()
    os.remove(ratings.file_of(music))
    with pytest.raises(WriteError, match="its audio couldn't be read"):
        w(Job(path, {"rating": 3}))
    assert w.kept(os.path.join(music, "LD", "new.wav")) == 0


def test_a_musikata_folder_that_cant_be_written_keeps_the_rating_in_the_index(root, caplog):
    """R1.5.2, A2.8: the rating is kept in this computer's index only, and the log says so."""
    music, index, _h = root
    os.rmdir(os.path.join(music, ".musikata"))
    w = writing(root, Files())
    w(Job(os.path.join(music, "LD", "a.wav"), {"rating": 2}))
    assert shown(index)["LD/a.wav"] == 2
    assert not os.path.exists(ratings.file_of(music))
    assert "kept in this computer's index only" in caplog.text


def test_reading_the_file_merges_it_into_the_index(root):
    music, index, h = root
    assert ratings.reread(index, music) == 0  # none yet
    with open(ratings.file_of(music), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "songs": [{"path": "LD/a.wav", "hash": h, "stars": 5,
                                           "changed": T1}]}, f)  # fmt: skip
    assert ratings.reread(index, music) == 1
    assert shown(index)["LD/a.wav"] == 5
    with open(ratings.file_of(music), "w", encoding="utf-8") as f:
        f.write("[")  # a sync in the middle: what was read stays
    assert ratings.reread(index, music) == 0 and shown(index)["LD/a.wav"] == 5


def test_a_song_of_the_index_reads_as_its_row_says(index):
    scanned(index, [("a.wav", "wav", H1, 2)])
    song = ratings.song_of(index.read(), "a.wav")
    assert (song.kind, song.hash, song.rating, song.tags.title, song.size) == (
        "wav",
        H1,
        2,
        "a.wav",
        1000,
    )
    assert ratings.song_of(index.read(), "none.wav") is None
    assert isinstance(index.read(), sqlite3.Connection)


def test_search_and_the_rating_order_take_the_ratings_kept_beside_the_files(index):
    """R10.5: `rating:>=4` and sorting by rating (slice 3's) see a WAV's ratings.json rating as
    they see a FLAC's file rating, and a rating cleared there as none."""
    scanned(index, [("a.wav", "wav", H1, None), ("b.flac", "flac", H2, 4), ("c.wav", "wav", H3, 5)])
    index.write(lambda c: ratings.load(c, [
        Entry("a.wav", H1, 5, T1), Entry("c.wav", H3, 0, T1)
    ])).result()  # fmt: skip
    where, params = search.condition(search.parse("rating:>=4"))
    c = index.read()
    found = [p for (p,) in c.execute(f"SELECT path FROM song WHERE {where} ORDER BY path", params)]
    assert found == ["a.wav", "b.flac"]
    where, params = search.condition(search.parse("rating:0"))
    assert [p for (p,) in c.execute(f"SELECT path FROM song WHERE {where}", params)] == ["c.wav"]
    order = c.execute("SELECT path FROM song ORDER BY coalesce(rating, 0) DESC, path")
    assert [p for (p,) in order] == ["a.wav", "b.flac", "c.wav"]
