"""The root's play files (src/musikata_core/rootfiles.py; R7.9, A2.1, A2.8, A2.10): a
`plays.json` per computer read in whatever shape a sync tool, a person or another version left it,
its entries matched to the index by path, else hash; the counts kept in the index's `play` table,
summed over every computer; this computer's file written whole from them, on its rhythm, off the
caller's thread.

Why: the files are data from outside (testing.md, "Shapes": `rootfiles`): another computer writes
them, a sync can cut them short, another version can add to them, and the songs they name can move
between two starts. A play counted must never be lost, nor counted twice, and a broken file must
never stop MusiKata starting."""

import json
import logging
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import jsonschema
import pytest
from fakes import FakeClock, fill, played
from hypothesis import given
from hypothesis import strategies as st

from musikata_core import db, rootfiles, scanner
from musikata_core.rootfiles import Due, Entry, Keeping

SCHEMA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "musikata_core", "schemas",
    "plays.v1.schema.json",
)  # fmt: skip
H1, H2, H3, H4 = "1" * 64, "2" * 64, "3" * 64, "4" * 64
WHEN = "2026-11-25T20:41:00Z"
EXAMPLE = {
    "format": 1,
    "computer": {"id": "b2c4", "name": "Studio-PC"},
    "songs": [{"path": "LD/GH/04.flac", "hash": H1, "count": 12, "last": WHEN}],
}
SONGS = {"LD/GH/01.flac": H2, "LD/GH/04.flac": H1, "MO/Kindling.mp3": H3, "Copy/A.flac": H4,
         "Copy/B.flac": H4}  # fmt: skip


def parse(doc):
    return rootfiles.parse(doc if isinstance(doc, str) else json.dumps(doc))


def valid(doc):
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def plays_file(musikata, computer, doc):
    os.makedirs(os.path.join(musikata, computer), exist_ok=True)
    path = rootfiles.file_of(str(musikata), computer)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc if isinstance(doc, str) else json.dumps(doc))
    return path


def entry(path, count=1, hash_=None, last=WHEN):
    return Entry(path, hash_, count, last)


def make_index(folder):
    """An index over SONGS, each with its audio hash."""
    folder.mkdir(parents=True, exist_ok=True)
    i = db.Index(str(folder / "musikata.db"))
    fill(i, [{"path": p} for p in SONGS])
    i.write(
        lambda c: c.executemany(
            "UPDATE song SET audio_hash = ? WHERE path = ?", [(h, p) for p, h in SONGS.items()]
        )
    ).result()
    return i


@pytest.fixture
def index(tmp_path):
    i = make_index(tmp_path / "index")
    yield i
    i.close()


def ids(index):
    return dict(index.read().execute("SELECT path, id FROM song"))


def shown(index):
    """Each song's count as shown, every computer's added up, by path."""
    found = ids(index)
    totals = rootfiles.totals(index.read(), found.values())
    return {p: totals[s] for p, s in found.items() if s in totals}


def rows(index, computer=None):
    sql = "SELECT computer, path, count FROM play"
    if computer is not None:
        return (
            index.read().execute(sql + " WHERE computer = ? ORDER BY path", (computer,)).fetchall()
        )
    return index.read().execute(sql + " ORDER BY computer, path").fetchall()


# ---------- reading a file: its shapes ----------


def test_a2_10s_example_gives_its_computer_and_its_songs():
    got = parse(EXAMPLE)
    assert (got.computer, got.name) == ("b2c4", "Studio-PC")
    assert got.entries == (Entry("LD/GH/04.flac", H1, 12, WHEN),)
    assert not got.broken and not got.newer and got.problems == ()


@pytest.mark.parametrize(
    "text",
    ['{"format": 1, "computer": {"id": "b2c4"}, "songs": [{"path": "a", "co',  # a sync cut it
     "", "not json", "[1, 2]", '"text"', '{"format": 1, "songs": {"path": "a"}}'],
)  # fmt: skip
def test_a_file_cut_short_not_json_or_of_the_wrong_shape_gives_no_plays(text):
    got = rootfiles.parse(text)
    assert got.broken and got.entries == () and got.problems


def test_a_bom_and_fields_in_another_order_are_read():
    song = f'{{"last": "{WHEN}", "count": 3, "hash": "{H1}", "path": "a.flac"}}'
    text = f'\ufeff{{"songs": [{song}],'
    got = rootfiles.parse(text + ' "computer": {"name": "x", "id": "c1"}, "format": 1}')
    assert got.entries == (Entry("a.flac", H1, 3, WHEN),) and got.computer == "c1"


@pytest.mark.parametrize(
    ("fmt", "newer", "problem"),
    [(None, False, False), ("1", False, True), (True, False, True), (2, True, True)],
)
def test_a_format_missing_or_not_a_number_is_read_as_this_one_and_a_newer_one_marked(
    fmt, newer, problem
):
    doc = {k: v for k, v in EXAMPLE.items() if k != "format"}
    if fmt is not None:
        doc["format"] = fmt
    got = parse(doc)
    assert got.newer is newer and bool(got.problems) is problem
    assert got.entries == parse(EXAMPLE).entries


@pytest.mark.parametrize(
    "computer", [None, "b2c4", [], {"name": "x"}, {"id": ""}, {"id": 7}]
)  # fmt: skip
def test_a_computer_missing_not_a_group_or_without_an_id_names_none(computer):
    doc = {**EXAMPLE, "computer": computer}
    if computer is None:
        del doc["computer"]
    got = parse(doc)
    assert got.computer is None and got.problems and got.entries == parse(EXAMPLE).entries


@pytest.mark.parametrize(
    ("song", "want"),
    [
        ({"hash": H1.upper()}, Entry("a", H1, 2, WHEN)),
        ({"hash": None}, Entry("a", None, 2, WHEN)),
        ({"hash": "abc"}, Entry("a", None, 2, WHEN)),
        ({"hash": 7}, Entry("a", None, 2, WHEN)),
        ({"count": "2"}, Entry("a", H1, 2, WHEN)),
        ({"count": 2.0}, Entry("a", H1, 2, WHEN)),
        ({"last": "2026-11-25T14:41:00-06:00"}, Entry("a", H1, 2, WHEN)),
        ({"last": "2026-11-25T20:41:00.250+00:00"}, Entry("a", H1, 2, WHEN)),
        ({"last": "2026-11-25T20:41:00"}, Entry("a", H1, 2, rootfiles.UNKNOWN)),
        ({"last": "yesterday"}, Entry("a", H1, 2, rootfiles.UNKNOWN)),
        ({"last": None}, Entry("a", H1, 2, rootfiles.UNKNOWN)),
        ({"count": 0}, None),
        ({"count": -3}, None),
        ({"count": 1.5}, None),
        ({"count": True}, None),
        ({"count": "many"}, None),
        ({"count": None}, None),
        ({"path": ""}, None),
        ({"path": 7}, None),
        ({"path": None}, None),
    ],
)
def test_an_entrys_fields_broken_or_in_another_form(song, want):
    base = {"path": "a", "hash": H1, "count": 2, "last": WHEN}
    doc = {**EXAMPLE, "songs": [{k: v for k, v in {**base, **song}.items() if v is not None}]}
    got = parse(doc)
    assert got.entries == ((want,) if want is not None else ())
    if want != Entry("a", H1, 2, WHEN):
        assert got.problems
    assert not got.broken


def test_an_entry_that_isnt_an_object_is_left_out_and_the_rest_kept():
    doc = {**EXAMPLE, "songs": [7, "a.flac", None, *EXAMPLE["songs"]]}
    got = parse(doc)
    assert got.entries == parse(EXAMPLE).entries and len(got.problems) == 3


def test_an_entry_named_twice_is_one_its_counts_added_up():
    later = "2026-11-26T08:00:00Z"
    doc = {**EXAMPLE, "songs": [{"path": "a", "hash": H1, "count": 2, "last": later},
                                {"path": "a", "count": 3, "last": WHEN}]}  # fmt: skip
    got = parse(doc)
    assert got.entries == (Entry("a", H1, 5, later),) and got.problems


def test_no_songs_and_very_many_are_read():
    assert parse({"format": 1, "computer": {"id": "x"}, "songs": []}).entries == ()
    assert parse({"format": 1, "computer": {"id": "x"}}).entries == ()
    many = [{"path": f"s/{i}.flac", "hash": H1, "count": i + 1, "last": WHEN} for i in range(5000)]
    assert len(parse({**EXAMPLE, "songs": many}).entries) == 5000


def test_fields_it_doesnt_know_are_kept_when_written_again():
    doc = {**EXAMPLE, "added": {"by": "a later version"},
           "songs": [{**EXAMPLE["songs"][0], "skips": 4}]}  # fmt: skip
    kept = parse(doc)
    written = rootfiles.document("b2c4", "Studio-PC", kept.entries, kept)
    assert written["added"] == {"by": "a later version"}
    assert written["songs"] == [{**EXAMPLE["songs"][0], "skips": 4}]
    valid(written)


@given(st.text(max_size=300))
def test_any_text_at_all_gives_plays_or_none_never_an_error(text):
    got = rootfiles.parse(text)
    assert all(e.count >= 1 and e.path for e in got.entries)


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner,
                                                                 max_size=4),
    max_leaves=6,
)  # fmt: skip
song_shapes = st.fixed_dictionaries(
    {}, optional={"path": json_values | st.text(min_size=1, max_size=8), "hash": json_values,
                  "count": json_values | st.integers(-2, 5), "last": json_values},
)  # fmt: skip


@pytest.mark.slow
@given(
    st.fixed_dictionaries(
        {}, optional={"format": json_values, "computer": json_values,
                      "songs": st.lists(song_shapes, max_size=5) | json_values}
    )
)  # fmt: skip
def test_any_shape_of_its_fields_gives_plays_or_none_never_an_error(doc):
    got = parse(doc)
    assert all(e.count >= 1 and e.path and e.last for e in got.entries)
    valid(rootfiles.document("x", None, [e for e in got.entries if e.hash], got))


# ---------- which files ----------


def test_the_other_computers_are_the_folders_and_a_folder_copied_by_a_sync_is_not_read(tmp_path):
    musikata = tmp_path / ".musikata"
    plays_file(musikata, "b2c4", EXAMPLE)
    plays_file(musikata, "b2c4 (conflicted copy)", EXAMPLE)  # its file still names b2c4
    (musikata / "history").mkdir()
    (musikata / "settings.json").write_text("{}")
    assert rootfiles.folders(str(musikata)) == ["b2c4", "b2c4 (conflicted copy)", "history"]
    assert rootfiles.read_other(str(musikata), "b2c4").entries == parse(EXAMPLE).entries
    assert rootfiles.read_other(str(musikata), "b2c4 (conflicted copy)").broken
    assert rootfiles.read_other(str(musikata), "history") is None
    assert rootfiles.folders(str(tmp_path / "none")) == []


def test_a_sync_tools_conflicted_copy_beside_a_file_is_not_read(tmp_path):
    musikata = tmp_path / ".musikata"
    plays_file(musikata, "b2c4", EXAMPLE)
    copy = musikata / "b2c4" / "plays (Ana's conflicted copy 2026-11-25).json"
    copy.write_text(json.dumps({**EXAMPLE, "songs": []}))
    assert rootfiles.read_other(str(musikata), "b2c4").entries == parse(EXAMPLE).entries


def test_a_file_that_cant_be_read_is_broken_and_logged(tmp_path, caplog):
    folder = tmp_path / ".musikata" / "b2c4" / rootfiles.NAME
    folder.mkdir(parents=True)  # a folder where the file should be
    with caplog.at_level(logging.WARNING):
        assert rootfiles.read(str(folder)).broken
    assert "couldn't be read" in caplog.text


# ---------- matching to the index ----------


def test_entries_are_matched_by_path_else_by_hash_else_not(index):
    found = ids(index)
    entries = [entry("LD/GH/01.flac", hash_=H1), entry("Moved/04.flac", hash_=H1),
               entry("Gone.flac", hash_="9" * 64), entry("Gone.flac"),
               entry("Moved/Copy.flac", hash_=H4)]  # fmt: skip
    assert rootfiles.find(index.read(), entries) == [
        found["LD/GH/01.flac"], found["LD/GH/04.flac"], None, None, found["Copy/A.flac"]
    ]  # fmt: skip
    assert rootfiles.match([entry("a", hash_=H1)], {"a": 1}, {H1: 2}) == [1]
    assert rootfiles.match([entry("b", hash_=H1)], {"a": 1}, {H1: 2}) == [2]


# ---------- in the index ----------


def test_a_play_is_counted_in_the_index_and_each_computers_add_up(index, caplog):
    found = ids(index)
    played(index, {"LD/GH/01.flac": 2, "MO/Kindling.mp3": 1}, computer="me")
    index.write(lambda c: rootfiles.replace(c, "b2c4", [entry("LD/GH/01.flac", 5, H2)])).result()
    assert shown(index) == {"LD/GH/01.flac": 7, "MO/Kindling.mp3": 1}
    assert rows(index, "me") == [("me", "LD/GH/01.flac", 2), ("me", "MO/Kindling.mp3", 1)]
    when = datetime(2026, 11, 26, 9, 30, 15, 500, tzinfo=UTC)
    index.write(lambda c: rootfiles.count(c, "me", found["LD/GH/01.flac"], when)).result()
    last = (
        index.read()
        .execute("SELECT last FROM play WHERE computer = 'me' AND path = 'LD/GH/01.flac'")
        .fetchone()
    )
    assert last == ("2026-11-26T09:30:15Z",)
    with caplog.at_level(logging.WARNING):
        assert not index.write(lambda c: rootfiles.count(c, "me", 9999, when)).result()
    assert "no longer in the index" in caplog.text


@given(st.permutations(range(4)))
def test_play_files_read_in_any_order_sum_the_same(order):
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    db.migrate(c)
    batch = [scanner.Read(scanner.Seen(p, 1, 1), None, None, h) for p, h in SONGS.items()]
    scanner.write_batch(c, batch, {})
    files = [
        ("a", [entry("LD/GH/01.flac", 3, H2), entry("Copy/B.flac", 1, H4)]),
        ("b", [entry("Old/01.flac", 2, H2), entry("Gone.flac", 9, "9" * 64)]),
        ("c", [entry("LD/GH/01.flac", 1), entry("Elsewhere/04.flac", 4, H1)]),
        ("d", [entry("Copy/A.flac", 2, H4), entry("Moved/A.flac", 1, H4)]),
    ]
    for i in order:
        rootfiles.replace(c, *files[i])
    found = dict(c.execute("SELECT path, id FROM song"))
    totals = rootfiles.totals(c, found.values())
    assert {p: totals.get(s, 0) for p, s in found.items()} == {
        "LD/GH/01.flac": 6, "LD/GH/04.flac": 4, "MO/Kindling.mp3": 0, "Copy/A.flac": 3,
        "Copy/B.flac": 1,
    }  # fmt: skip


def test_a_computers_file_read_again_replaces_what_was_read_of_it(index):
    index.write(lambda c: rootfiles.replace(c, "b2c4", [entry("LD/GH/01.flac", 5, H2)])).result()
    index.write(lambda c: rootfiles.replace(c, "b2c4", [entry("LD/GH/01.flac", 6, H2)])).result()
    assert shown(index) == {"LD/GH/01.flac": 6}
    index.write(lambda c: rootfiles.forget(c, {"me"})).result()
    assert shown(index) == {}


def test_plays_of_a_song_the_index_hasnt_yet_wait_for_a_scan_to_find_it(index):
    index.write(
        lambda c: rootfiles.replace(c, "b2c4", [entry("New/05.flac", 3, "5" * 64)])
    ).result()
    assert shown(index) == {}
    fill(index, [{"path": "New/05.flac"}])
    assert shown(index) == {"New/05.flac": 3}


def test_a_song_named_by_its_path_wins_over_a_copy_matched_by_hash(index):
    # read before the scan found its own song: matched by hash to a copy; the path wins after
    index.write(lambda c: rootfiles.replace(c, "b2c4", [entry("New/A.flac", 3, H4)])).result()
    assert shown(index) == {"Copy/A.flac": 3}
    fill(index, [{"path": "New/A.flac"}])
    assert shown(index) == {"New/A.flac": 3}


def test_a_song_moved_keeps_its_plays_and_its_rows_name_it_where_it_is_now(index):
    played(index, {"LD/GH/04.flac": 2}, computer="me")
    index.write(lambda c: rootfiles.replace(c, "b2c4", [entry("LD/GH/04.flac", 5, H1)])).result()
    moved = scanner.Read(scanner.Seen("Moved/04.flac", 1, 2), None, None, H1)
    index.write(lambda c: scanner.write_batch(c, [moved], {H1: "LD/GH/04.flac"})).result()
    assert shown(index) == {"Moved/04.flac": 7}
    assert rows(index) == [("b2c4", "Moved/04.flac", 5), ("me", "Moved/04.flac", 2)]
    assert index.write(lambda c: rootfiles.own(c, "me")).result() == [
        Entry("Moved/04.flac", H1, 2, WHEN)
    ]


def test_another_computers_entry_for_the_old_path_finds_the_moved_song_by_hash(index):
    moved = scanner.Read(scanner.Seen("Moved/04.flac", 1, 2), None, None, H1)
    index.write(lambda c: scanner.write_batch(c, [moved], {H1: "LD/GH/04.flac"})).result()
    index.write(lambda c: rootfiles.replace(c, "b2c4", [entry("LD/GH/04.flac", 5, H1)])).result()
    assert shown(index) == {"Moved/04.flac": 5}


def test_the_plays_of_a_song_gone_go_to_its_exact_copy(tmp_path, index):
    played(index, {"Copy/A.flac": 2, "Copy/B.flac": 1}, computer="me")
    (tmp_path / "Music").mkdir()
    assert scanner.remove(str(tmp_path / "Music"), index, ["Copy/A.flac"]) == 1
    assert shown(index) == {"Copy/B.flac": 3}
    assert rows(index, "me") == [("me", "Copy/A.flac", 3)]  # one row, its counts added up
    own = index.write(lambda c: rootfiles.own(c, "me")).result()
    assert own == [Entry("Copy/B.flac", H4, 3, WHEN)]


def test_a_song_gone_with_no_copy_keeps_its_plays_in_this_computers_file(tmp_path, index):
    played(index, {"MO/Kindling.mp3": 4}, computer="me")
    (tmp_path / "Music").mkdir()
    scanner.remove(str(tmp_path / "Music"), index, ["MO/Kindling.mp3"])
    assert shown(index) == {}
    own = index.write(lambda c: rootfiles.own(c, "me")).result()
    assert own == [Entry("MO/Kindling.mp3", H3, 4, WHEN)]


def test_its_own_file_read_back_takes_the_larger_count_and_adds_what_the_index_lacks(index):
    played(index, {"LD/GH/01.flac": 5, "LD/GH/04.flac": 1}, computer="me")
    later = "2026-11-26T08:00:00Z"
    entries = [entry("LD/GH/01.flac", 3, H2), entry("Moved/04.flac", 4, H1, later),
               entry("MO/Kindling.mp3", 2, H3), entry("Gone.flac", 1, "9" * 64)]  # fmt: skip
    changed = index.write(lambda c: rootfiles.merge_own(c, "me", entries)).result()
    assert changed == 3
    assert shown(index) == {"LD/GH/01.flac": 5, "LD/GH/04.flac": 4, "MO/Kindling.mp3": 2}
    own = index.write(lambda c: rootfiles.own(c, "me")).result()
    assert Entry("LD/GH/04.flac", H1, 4, later) in own
    assert Entry("Gone.flac", "9" * 64, 1, WHEN) in own
    # read back again, it changes nothing
    assert index.write(lambda c: rootfiles.merge_own(c, "me", own)).result() == 0


def test_plays_counted_while_this_computer_had_no_id_become_its_own(index):
    played(index, {"LD/GH/01.flac": 2}, computer="")
    played(index, {"LD/GH/01.flac": 1}, computer="me")
    index.write(lambda c: rootfiles.merge_own(c, "me", ())).result()
    assert rows(index) == [("me", "LD/GH/01.flac", 3)]


def test_its_file_is_valid_and_a_song_without_an_audio_hash_is_left_out_and_logged(caplog):
    entries = [Entry("a.flac", H1, 3, WHEN), Entry("b.flac", None, 2, WHEN),
               Entry("c.flac", "path-as-hash", 1, WHEN)]  # fmt: skip
    with caplog.at_level(logging.INFO):
        doc = rootfiles.document("b2c4", "Studio-PC", entries)
    valid(doc)
    assert doc == {"format": 1, "computer": {"id": "b2c4", "name": "Studio-PC"},
                   "songs": [{"path": "a.flac", "hash": H1, "count": 3, "last": WHEN}]}  # fmt: skip
    assert "b.flac has no audio hash" in caplog.text
    assert rootfiles.document("b2c4", None, ())["computer"] == {"id": "b2c4"}


def test_a_time_is_written_in_utc_to_the_second():
    when = datetime(2026, 11, 25, 14, 41, 0, 999, tzinfo=UTC) + timedelta(hours=6)
    assert rootfiles.time_text(when) == WHEN


# ---------- when it is written ----------


def test_its_file_is_due_once_its_plays_change_at_most_once_a_minute_and_at_quit():
    clock = FakeClock()
    due = Due(clock)
    assert not due.take() and not due.take(at_quit=True)  # nothing changed
    due.change()
    assert due.take() and not due.take()
    due.change()
    clock.advance(seconds=59)
    assert not due.take()
    clock.advance(seconds=1)
    assert due.take()
    due.change()
    assert due.take(at_quit=True)


# ---------- keeping them ----------


def keeping_for(tmp_path, index, computer="me", **kw):
    musikata = tmp_path / "Music" / ".musikata"
    musikata.mkdir(parents=True, exist_ok=True)
    return Keeping(index, str(musikata), FakeClock(), computer, **kw), str(musikata)


def test_at_start_every_computers_file_is_read_and_a_folder_gone_forgotten(tmp_path, index):
    keeping, musikata = keeping_for(tmp_path, index)
    plays_file(musikata, "b2c4", EXAMPLE)
    plays_file(musikata, "c3d5", {**EXAMPLE, "computer": {"id": "c3d5"}})
    plays_file(musikata, "me", {**EXAMPLE, "computer": {"id": "me"}, "songs": [
        {"path": "MO/Kindling.mp3", "hash": H3, "count": 2, "last": WHEN}]})  # fmt: skip
    index.write(lambda c: rootfiles.replace(c, "gone", [entry("LD/GH/01.flac", 9)])).result()
    told = []
    keeping.on_change = lambda: told.append(threading.current_thread().name)
    assert keeping.start().result() is True
    assert shown(index) == {"LD/GH/04.flac": 24, "MO/Kindling.mp3": 2}
    assert keeping.seen == ("b2c4", "c3d5", "me")
    assert told and all(t.startswith("plays") for t in told)
    keeping.close()


def test_a_crash_loses_nothing_the_file_is_written_at_the_next_start(tmp_path, index):
    played(index, {"LD/GH/01.flac": 3}, computer="me")  # counted, the file never written
    keeping, musikata = keeping_for(tmp_path, index, name="Studio-PC")
    keeping.start().result()
    keeping.close()
    doc = read_json(rootfiles.file_of(musikata, "me"))
    valid(doc)
    assert doc["computer"] == {"id": "me", "name": "Studio-PC"}
    assert doc["songs"] == [{"path": "LD/GH/01.flac", "hash": H2, "count": 3, "last": WHEN}]


def test_an_index_made_anew_gets_back_every_play_from_its_file(tmp_path, index):
    keeping, musikata = keeping_for(tmp_path, index)
    path = plays_file(musikata, "me", {**EXAMPLE, "computer": {"id": "me"}})
    before = os.stat(path).st_mtime_ns
    keeping.start().result()
    keeping.close()
    assert shown(index) == {"LD/GH/04.flac": 12}
    assert os.stat(path).st_mtime_ns == before  # the same plays: not written again


def test_a_play_is_counted_off_the_callers_thread_and_the_file_written_when_due(tmp_path, index):
    keeping, musikata = keeping_for(tmp_path, index)
    keeping.start().result()
    found = ids(index)
    when = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
    assert keeping.played(found["LD/GH/01.flac"], when).result() is True
    path = rootfiles.file_of(musikata, "me")
    keeping._executor.submit(lambda: None).result()  # the write after it
    assert [s["count"] for s in read_json(path)["songs"]] == [1]
    keeping.played(found["LD/GH/01.flac"], when).result()
    assert keeping.tick() is None  # within the minute: not yet
    assert read_json(path)["songs"][0]["count"] == 1
    keeping.due._at -= 60
    keeping.tick().result()
    assert read_json(path)["songs"][0]["count"] == 2
    keeping.played(found["MO/Kindling.mp3"], when).result()
    keeping.close()  # at quit, whatever the minute says
    assert [s["count"] for s in read_json(path)["songs"]] == [2, 1]


def test_a_scan_that_moved_songs_has_the_file_name_them_where_they_are(tmp_path, index):
    keeping, musikata = keeping_for(tmp_path, index)
    played(index, {"LD/GH/04.flac": 2}, computer="me")
    keeping.start().result()
    moved = scanner.Read(scanner.Seen("Moved/04.flac", 1, 2), None, None, H1)
    index.write(lambda c: scanner.write_batch(c, [moved], {H1: "LD/GH/04.flac"})).result()
    keeping.moved().result()
    keeping.close()
    assert [s["path"] for s in read_json(rootfiles.file_of(musikata, "me"))["songs"]] == [
        "Moved/04.flac"
    ]


def test_another_computers_file_read_again_and_a_broken_one_keeps_what_was_read(tmp_path, index):
    keeping, musikata = keeping_for(tmp_path, index)
    plays_file(musikata, "b2c4", EXAMPLE)
    keeping.start().result()
    plays_file(musikata, "b2c4", {**EXAMPLE, "songs": [{**EXAMPLE["songs"][0], "count": 13}]})
    keeping.reread(["b2c4", "me"]).result()
    assert shown(index) == {"LD/GH/04.flac": 13}
    plays_file(musikata, "b2c4", '{"format": 1, "songs": [{"pa')  # a sync in progress
    keeping.reread(["b2c4"]).result()
    assert shown(index) == {"LD/GH/04.flac": 13}
    os.remove(rootfiles.file_of(musikata, "b2c4"))
    keeping.reread(["b2c4"]).result()
    assert shown(index) == {}
    keeping.close()


def test_a_musikata_that_cant_be_written_keeps_the_plays_in_the_index_only(tmp_path, index, caplog):
    root = tmp_path / "Music"
    root.mkdir()  # no .musikata, and none can be made: as a read-only share
    keeping = Keeping(index, str(root / ".musikata"), FakeClock(), "me")
    with caplog.at_level(logging.WARNING):
        keeping.start().result()
    assert "kept in this computer's index only" in caplog.text
    keeping.played(ids(index)["LD/GH/01.flac"], datetime(2026, 11, 26, tzinfo=UTC)).result()
    keeping.close()
    assert shown(index) == {"LD/GH/01.flac": 1}
    assert not os.path.exists(root / ".musikata")


def test_a_newer_formats_own_file_is_read_and_never_written(tmp_path, index, caplog):
    keeping, musikata = keeping_for(tmp_path, index)
    path = plays_file(musikata, "me", {**EXAMPLE, "format": 2, "computer": {"id": "me"}})
    with caplog.at_level(logging.WARNING):
        keeping.start().result()
    keeping.played(ids(index)["LD/GH/01.flac"], datetime(2026, 11, 26, tzinfo=UTC)).result()
    keeping.close()
    assert read_json(path)["format"] == 2 and shown(index)["LD/GH/04.flac"] == 12
    assert "newer MusiKata's" in caplog.text


def test_this_computers_id_is_made_only_when_its_file_is_first_written(tmp_path, index):
    made = []
    keeping, musikata = keeping_for(tmp_path, index, None,
                                    make=lambda: made.append(1) or "made")  # fmt: skip
    keeping.start().result()
    assert made == [] and keeping.me == ""  # nothing played: nothing written, no id made
    keeping.played(ids(index)["LD/GH/01.flac"], datetime(2026, 11, 26, tzinfo=UTC)).result()
    keeping.close()
    assert made == [1] and rows(index) == [("made", "LD/GH/01.flac", 1)]
    assert read_json(rootfiles.file_of(musikata, "made"))["computer"] == {"id": "made"}


def test_without_an_id_to_be_had_the_plays_stay_in_the_index(tmp_path, index):
    keeping, musikata = keeping_for(tmp_path, index, None, make=lambda: None)
    keeping.start().result()
    keeping.played(ids(index)["LD/GH/01.flac"], datetime(2026, 11, 26, tzinfo=UTC)).result()
    keeping.close()
    assert rows(index) == [("", "LD/GH/01.flac", 1)] and rootfiles.folders(musikata) == []


def test_after_close_nothing_more_is_kept_and_the_log_says_so(tmp_path, index, caplog):
    keeping, _ = keeping_for(tmp_path, index)
    keeping.close()
    with caplog.at_level(logging.WARNING):
        assert keeping.played(ids(index)["LD/GH/01.flac"], datetime(2026, 11, 26)).result() is None
    assert "a late job is passed by" in caplog.text and shown(index) == {}


def test_a_job_that_breaks_is_logged_and_the_next_one_goes_on(tmp_path, index, caplog):
    keeping, _ = keeping_for(tmp_path, index, executor=ThreadPoolExecutor(1))
    with caplog.at_level(logging.ERROR):
        assert keeping.reread(["b2c4", None]).result() is None
    assert "keeping the play counts failed" in caplog.text
    assert keeping.start().result() is True
    keeping.close()


def test_two_computers_playing_at_once_each_write_their_own_and_the_sums_add_up(tmp_path):
    musikata = tmp_path / "Music" / ".musikata"
    musikata.mkdir(parents=True)
    computers = {"studio": 3, "laptop": 2}
    indexes = {name: make_index(tmp_path / name) for name in computers}
    keepings = {name: Keeping(indexes[name], str(musikata), FakeClock(), name)
                for name in computers}  # fmt: skip
    for k in keepings.values():
        k.start().result()
    when = datetime(2026, 11, 26, tzinfo=UTC)
    for _ in range(3):  # turn and turn about, as two computers playing at once
        for name, n in computers.items():
            if n:
                computers[name] -= 1
                keepings[name].played(ids(indexes[name])["LD/GH/01.flac"], when)
                keepings[name].due._at = None
    for name, k in keepings.items():
        k.close()
        assert read_json(rootfiles.file_of(str(musikata), name))["computer"]["id"] == name
    for name, i in indexes.items():  # each reads the other's file at its next start
        k = Keeping(i, str(musikata), FakeClock(), name)
        k.start().result()
        k.close()
        assert shown(i) == {"LD/GH/01.flac": 5}
        i.close()
