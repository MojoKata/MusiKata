"""What's playing kept across restarts (src/musikata_core/nowplaying.py; R1.8, R7.2, R7.3, A2.8,
A2.10): `now-playing.json` read in whatever shape a sync tool, a person or another version left
it, its songs found in the index by path or hash, written whole on its rhythm (`Keeper`) off the
caller's thread (`Keeping`), in the root's `.musikata` or beside the index.

Why: the file is data from outside (testing.md, "Shapes": `nowplaying`): a sync can cut it short,
another version can add to it, and the songs it names can move or go between two starts. A queue
that can't be read must start empty, never stop MusiKata starting; one that can must come back as
it was, in the same order, at the same place."""

import dataclasses
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import jsonschema
import pytest
from fakes import FakeClock, fill
from hypothesis import given
from hypothesis import strategies as st

from musikata_core import db, nowplaying
from musikata_core.audio.queue import Queue
from musikata_core.nowplaying import PAUSE, QUEUE, QUIT, TICK, Kept, Places, Song, State

SCHEMA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "musikata_core", "schemas",
    "now-playing.v1.schema.json",
)  # fmt: skip
H1, H2, H3 = "1" * 64, "2" * 64, "3" * 64
EXAMPLE = {
    "format": 1, "saved": "2026-11-26T17:30:00Z", "source": "Glass Harbor", "current": 1,
    "position": 83.4,
    "songs": [
        {"path": "LD/GH/03.flac", "hash": H3, "added": False, "unshuffled": 2},
        {"path": "LD/GH/04.flac", "hash": H1, "added": False, "unshuffled": 3},
        {"path": "MO/Kindling.mp3", "added": True, "unshuffled": 0},
        {"path": "LD/GH/01.flac", "hash": H2, "added": False, "unshuffled": 1},
    ],
}  # fmt: skip


def parse(doc):
    return nowplaying.parse(doc if isinstance(doc, str) else json.dumps(doc))


def valid(doc):
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def kept_file(folder, doc):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, nowplaying.NAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc if isinstance(doc, str) else json.dumps(doc))
    return path


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, [{"path": p} for p in ("LD/GH/01.flac", "LD/GH/03.flac", "MO/Kindling.mp3",
                                   "Moved/Signal.flac", "Copy/A.flac", "Copy/B.flac")])  # fmt: skip
    hashes = {"LD/GH/01.flac": H2, "LD/GH/03.flac": H3, "Moved/Signal.flac": "4" * 64,
              "Copy/A.flac": "5" * 64, "Copy/B.flac": "5" * 64}  # fmt: skip
    i.write(
        lambda c: c.executemany(
            "UPDATE song SET audio_hash = ? WHERE path = ?", [(h, p) for p, h in hashes.items()]
        )
    ).result()
    yield i
    i.close()


def ids(index):
    return dict(index.read().execute("SELECT path, id FROM song"))


# ---------- reading it: its shapes ----------


def test_a2_10s_example_gives_its_songs_places_current_song_and_place():
    got = parse(EXAMPLE)
    assert got.songs == (Song("LD/GH/03.flac", H3), Song("LD/GH/04.flac", H1),
                         Song("MO/Kindling.mp3", None, True),
                         Song("LD/GH/01.flac", H2))  # fmt: skip
    assert (got.unshuffled, got.current, got.position, got.source) == (
        (2, 3, 0, 1), 1, 83.4, "Glass Harbor"
    )  # fmt: skip
    assert got.saved == datetime(2026, 11, 26, 17, 30, tzinfo=UTC)
    assert got.problems == () and not got.newer and not got.broken
    valid(EXAMPLE)


@pytest.mark.parametrize(
    "text",
    ["", "{", '{"format": 1, "songs": [{"path": "LD/GH/0', "\x00\x00", "[]", "3", "null",
     '"songs"', '{"songs": 3}', '{"songs": {"path": "a"}}', '{"songs": [3]}', '{"songs": [null]}',
     '{"songs": [{"hash": "' + H1 + '"}]}', '{"songs": [{"path": ""}]}',
     '{"songs": [{"path": 7}]}', '{"songs": [{"path": ["a"]}]}'],
)  # fmt: skip
def test_a_file_cut_short_not_json_or_of_the_wrong_shape_is_an_empty_queue(text):
    got = nowplaying.parse(text)
    assert got.broken and got.songs == () and got.current is None
    assert len(got.problems) == 1 and "the queue starts empty" in got.problems[0]


def test_a_bom_and_fields_in_another_order_are_read():
    text = "﻿" + json.dumps(dict(reversed(list(EXAMPLE.items()))))
    assert nowplaying.parse(text).songs == parse(EXAMPLE).songs


@pytest.mark.parametrize("fmt, newer, problems", [(1, False, 0), (None, False, 0), (2, True, 1),
                                                  ("1", False, 1), (True, False, 1)])  # fmt: skip
def test_a_format_missing_or_not_a_number_is_read_as_this_one_and_a_newer_one_marked(
    fmt, newer, problems
):
    doc = {k: v for k, v in EXAMPLE.items() if k != "format"}
    if fmt is not None:
        doc["format"] = fmt
    got = parse(doc)
    assert got.newer is newer and len(got.problems) == problems and len(got.songs) == 4


def with_song(**fields):
    return {"format": 1, "current": 0, "songs": [{"path": "a.flac", **fields}]}


@pytest.mark.parametrize(
    "fields, want, problem",
    [
        ({"hash": H1.upper()}, Song("a.flac", H1), ""),
        ({}, Song("a.flac"), ""),
        ({"hash": None}, Song("a.flac"), ""),
        ({"hash": "abc"}, Song("a.flac"), "isn't an audio hash"),
        ({"hash": 7}, Song("a.flac"), "isn't an audio hash"),
        ({"added": True}, Song("a.flac", added=True), ""),
        ({"added": "yes"}, Song("a.flac"), "added isn't true or false"),
        ({"added": 1}, Song("a.flac"), "added isn't true or false"),
    ],
)
def test_a_songs_hash_and_added_broken_or_in_another_case(fields, want, problem):
    got = parse(with_song(**fields))
    assert got.songs == (want,) and not got.broken
    assert (problem in got.problems[0]) if problem else got.problems == ()


@pytest.mark.parametrize(
    "places", [[0, 0, 1], [0, 1, None], [1, 2, 3], [0, True, 2], [0, "1", 2], [0, -1, 1]], ids=str
)
def test_unshuffled_places_that_arent_one_each_are_the_order_it_plays_in(places):
    songs = [{"path": f"{i}.flac"} for i in range(3)]
    for song, place in zip(songs, places, strict=True):
        if place is not None:
            song["unshuffled"] = place
    got = parse({"format": 1, "songs": songs})
    assert got.unshuffled == (0, 1, 2) and "unshuffled places" in got.problems[0]


@pytest.mark.parametrize(
    "current, want, problem",
    [(2, 2, ""), (None, None, ""), ("missing", 0, ""), (3, 0, "current isn't"),
     (-1, 0, "current isn't"), ("1", 0, "current isn't"), (True, 0, "current isn't"),
     (1.5, 0, "current isn't")],
)  # fmt: skip
def test_current_played_out_missing_or_broken(current, want, problem):
    doc = {"format": 1, "position": 12.0, "songs": [{"path": f"{i}.flac"} for i in range(3)]}
    if current != "missing":
        doc["current"] = current
    got = parse(doc)
    assert got.current == want and got.position == (0.0 if want is None else 12.0)
    assert (problem in got.problems[0]) if problem else got.problems == ()


@pytest.mark.parametrize("position, want, problems", [(83, 83.0, 0), ("missing", 0.0, 0),
                                                      ("83", 0.0, 1), (-5, 0.0, 1),
                                                      (None, 0.0, 1), (True, 0.0, 1)])  # fmt: skip
def test_a_place_missing_negative_or_not_a_number_is_the_songs_start(position, want, problems):
    doc = with_song()
    if position != "missing":
        doc["position"] = position
    got = parse(doc)
    assert got.position == want and len(got.problems) == problems


def test_a_place_that_isnt_finite_is_the_songs_start():
    got = nowplaying.parse('{"format": 1, "current": 0, "position": NaN, "songs": [{"path": "a"}]}')
    assert got.position == 0.0 and "position isn't seconds" in got.problems[0]


@pytest.mark.parametrize("saved", ["yesterday", "2026-11-26T17:30:00", 1795600000, None])
def test_a_saved_time_that_isnt_a_utc_time_is_not_known(saved):
    got = parse({**EXAMPLE, "saved": saved})
    assert got.saved is None and "saved isn't a time" in got.problems[0]


def test_a_source_that_isnt_text_is_none_and_none_is_an_empty_queue():
    got = parse({**EXAMPLE, "source": ["GH"]})
    assert got.source == "" and "source isn't text" in got.problems[0]
    empty = parse({"format": 1})
    assert empty.songs == () and empty.current is None and empty.problems == ()


@given(st.text(max_size=300))
def test_any_text_at_all_gives_a_queue_or_an_empty_one_never_an_error(text):
    got = nowplaying.parse(text)
    assert got.current is None or 0 <= got.current < len(got.songs)
    assert sorted(got.unshuffled) == list(range(len(got.songs)))


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner,
                                                                 max_size=4),
    max_leaves=6,
)  # fmt: skip
song_shapes = st.fixed_dictionaries(
    {}, optional={"path": json_values | st.text(min_size=1, max_size=8), "hash": json_values,
                  "added": json_values, "unshuffled": json_values | st.integers(0, 4)},
)  # fmt: skip


@pytest.mark.slow
@given(
    st.fixed_dictionaries(
        {}, optional={"format": json_values, "current": json_values, "position": json_values,
                      "source": json_values, "saved": json_values,
                      "songs": st.lists(song_shapes, max_size=5) | json_values}
    )
)  # fmt: skip
def test_any_shape_of_its_fields_gives_a_queue_or_an_empty_one_never_an_error(doc):
    got = parse(doc)
    assert got.current is None or 0 <= got.current < len(got.songs)
    assert sorted(got.unshuffled) == list(range(len(got.songs))) and got.position >= 0


# ---------- where it is, and which copy ----------


def test_the_file_is_in_the_roots_musikata_under_this_computers_id(tmp_path):
    root = tmp_path / "Music"
    (root / ".musikata").mkdir(parents=True)
    where = nowplaying.places(str(root), str(tmp_path / "index"), "b2c4")
    assert where.root_file() == str(root / ".musikata" / "b2c4" / "now-playing.json")
    assert where.local == str(tmp_path / "index" / "now-playing.json")
    assert nowplaying.places(str(root), "i", None).root_file() is None  # no id yet
    assert where.root_file("other") == str(root / ".musikata" / "other" / "now-playing.json")


def test_a_root_whose_musikata_cant_be_written_keeps_it_beside_the_index(tmp_path):
    (tmp_path / "none").mkdir()  # no .musikata: R1.5.2's root, with no id of its own
    assert nowplaying.places(str(tmp_path / "none"), "i", "b2c4").musikata is None
    (tmp_path / "file").mkdir()
    (tmp_path / "file" / ".musikata").write_text("")  # not a folder
    assert nowplaying.places(str(tmp_path / "file"), "i", "b2c4").root_file() is None
    assert nowplaying.places(str(tmp_path / "gone"), "i", "b2c4").musikata is None  # R2.10


def where_in(tmp_path):
    (tmp_path / "Music" / ".musikata").mkdir(parents=True)
    return nowplaying.places(str(tmp_path / "Music"), str(tmp_path / "index"), "b2c4")


def test_nothing_kept_is_an_empty_queue(tmp_path):
    assert nowplaying.load(where_in(tmp_path)) == Kept()


def test_the_roots_copy_or_the_one_beside_the_index_whichever_is_there(tmp_path):
    where = where_in(tmp_path)
    kept_file(os.path.dirname(where.local), {**EXAMPLE, "source": "local"})
    assert nowplaying.load(where).source == "local"
    kept_file(os.path.dirname(where.root_file()), {**EXAMPLE, "source": "root"})
    os.remove(where.local)
    assert nowplaying.load(where).source == "root"


@pytest.mark.parametrize(
    "root_saved, local_saved, want",
    [("2026-11-26T18:00:00Z", "2026-11-26T17:00:00Z", "root"),
     ("2026-11-26T17:00:00Z", "2026-11-26T18:00:00Z", "local"),
     ("2026-11-26T17:00:00Z", "2026-11-26T17:00:00Z", "local"),
     ("broken", "2026-11-26T17:00:00Z", "local"),
     ("2026-11-26T17:00:00Z", "broken", "root")],
)  # fmt: skip
def test_with_both_copies_the_roots_is_read_when_it_is_the_newer(
    tmp_path, root_saved, local_saved, want
):
    where = where_in(tmp_path)
    kept_file(
        os.path.dirname(where.root_file()), {**EXAMPLE, "source": "root", "saved": root_saved}
    )
    kept_file(os.path.dirname(where.local), {**EXAMPLE, "source": "local", "saved": local_saved})
    assert nowplaying.load(where).source == want


def test_a_copy_that_cant_be_used_gives_way_to_the_other_and_is_logged(tmp_path, caplog):
    where = where_in(tmp_path)
    kept_file(os.path.dirname(where.root_file()), '{"format": 1, "songs": [{"pa')
    kept_file(os.path.dirname(where.local), {**EXAMPLE, "saved": "2020-01-01T00:00:00Z"})
    with caplog.at_level(logging.WARNING):
        assert nowplaying.load(where).source == "Glass Harbor"
    assert "isn't JSON" in caplog.text and where.root_file() in caplog.text


def test_both_copies_broken_or_unreadable_are_an_empty_queue(tmp_path, caplog):
    where = where_in(tmp_path)
    kept_file(os.path.dirname(where.root_file()), "[]")
    os.makedirs(where.local)  # a folder where the file should be: it can't be read
    with caplog.at_level(logging.WARNING):
        assert nowplaying.load(where) == Kept()
    assert "isn't a JSON object" in caplog.text and "couldn't be read" in caplog.text


def test_a_sync_tools_conflicted_copy_beside_it_is_not_read(tmp_path):
    where = where_in(tmp_path)
    folder = os.path.dirname(where.root_file())
    kept_file(folder, EXAMPLE)
    with open(os.path.join(folder, "now-playing (Studio-PC's conflicted copy).json"), "w") as f:
        json.dump({**EXAMPLE, "source": "conflicted", "saved": "2030-01-01T00:00:00Z"}, f)
    assert nowplaying.load(where).source == "Glass Harbor"


# ---------- finding its songs ----------


def test_songs_are_found_by_path_else_by_hash_else_not(index):
    found = ids(index)
    find = nowplaying.finder(index.read())
    got = find(
        [
            Song("LD/GH/01.flac", "9" * 64),
            Song("Old/Signal.flac", "4" * 64),
            Song("Gone.flac", "8" * 64),
            Song("Gone.flac"),
            Song("Copies.flac", "5" * 64),
        ]
    )
    assert got == [found["LD/GH/01.flac"], found["Moved/Signal.flac"], None, None,
                   found["Copy/A.flac"]]  # fmt: skip
    assert find([]) == []


def test_a_queue_restored_is_the_one_kept(index):
    found = ids(index)
    state, dropped = nowplaying.restore(parse(EXAMPLE), nowplaying.finder(index.read()))
    assert dropped == 1  # LD/GH/04.flac isn't in the index, by path or by hash
    want = [found["LD/GH/03.flac"], found["MO/Kindling.mp3"], found["LD/GH/01.flac"]]
    assert [s for s, _ in state.songs] == want and [a for _, a in state.songs] == [0, 1, 0]
    # the current song (04) gone: the next one still there is current, from its start
    assert (state.unshuffled, state.cursor, state.position) == ((2, 0, 1), 1, 0.0)
    assert state.source == "Glass Harbor"


def test_songs_moved_are_found_by_hash_and_the_place_is_kept(index):
    found = ids(index)
    doc = {"format": 1, "current": 1, "position": 30.5,
           "songs": [{"path": "LD/GH/01.flac", "hash": H2},
                     {"path": "Old/Signal.flac", "hash": "4" * 64}]}  # fmt: skip
    state, dropped = nowplaying.restore(parse(doc), nowplaying.finder(index.read()))
    assert dropped == 0 and state.cursor == 1 and state.position == 30.5
    assert state.songs[1] == (found["Moved/Signal.flac"], False)


@pytest.mark.parametrize(
    "current, gone, cursor, position",
    [(1, {0}, 0, 30.0), (1, {2}, 1, 30.0), (1, {1}, 1, 0.0), (2, {1, 2}, 1, 0.0),
     (None, {0}, 2, 0.0), (0, {0, 1, 2}, 0, 0.0)],
)  # fmt: skip
def test_songs_gone_leave_the_queue_and_a_current_one_gone_gives_way_to_the_next(
    current, gone, cursor, position
):
    doc = {"format": 1, "current": current, "position": 30.0,
           "songs": [{"path": f"{i}.flac", "unshuffled": 2 - i} for i in range(3)]}  # fmt: skip
    state, dropped = nowplaying.restore(
        parse(doc), lambda songs: [None if int(s.path[0]) in gone else 10 + int(s.path[0])
                                   for s in songs]
    )  # fmt: skip
    assert dropped == len(gone) and (state.cursor, state.position) == (cursor, position)
    assert [s for s, _ in state.songs] == [10 + i for i in range(3) if i not in gone]
    assert sorted(state.unshuffled) == list(range(3 - len(gone)))
    assert list(state.unshuffled) == sorted(state.unshuffled, reverse=True)  # still reversed


# ---------- writing it ----------


def test_what_is_written_is_valid_and_reads_back_as_the_same_queue(index):
    q = Queue()
    found = ids(index)
    q.play([found[p] for p in ("LD/GH/01.flac", "LD/GH/03.flac", "Moved/Signal.flac")], 0, "GH")
    q.set_shuffle(True)
    q.next()
    q.add([found["MO/Kindling.mp3"]])
    state = nowplaying.state_of(q, 42.25)
    rows = nowplaying.rows_of(index.read(), [s for s, _ in state.songs])
    doc = nowplaying.document(state, rows, datetime(2026, 11, 26, 17, 30, tzinfo=UTC))
    valid(doc)
    assert doc["saved"] == "2026-11-26T17:30:00Z" and doc["current"] == 1
    assert doc["position"] == 42.25 and doc["source"] == "GH"
    kindling = next(s for s in doc["songs"] if s["path"] == "MO/Kindling.mp3")
    assert "hash" not in kindling and kindling["added"]  # its hash here isn't an audio hash
    again, dropped = nowplaying.restore(parse(doc), nowplaying.finder(index.read()))
    assert again == state and dropped == 0


def test_a_played_out_queue_is_written_with_no_current_song():
    q = Queue()
    q.play([1, 2])
    q.next()
    q.next()
    state = nowplaying.state_of(q, 12.0)
    assert state.cursor == 2 and state.position == 0.0
    doc = nowplaying.document(state, {1: ("a", None), 2: ("b", None)}, datetime.now(UTC))
    valid(doc)
    assert doc["current"] is None and doc["position"] == 0.0 and "hash" not in doc["songs"][0]


def test_a_song_gone_from_the_index_since_is_left_out_when_written():
    state = State(((1, False), (2, True), (3, False)), (2, 1, 0), 1, 50.0, "GH")
    doc = nowplaying.document(state, {1: ("a", None), 3: ("c", H3)}, datetime.now(UTC))
    assert [s["path"] for s in doc["songs"]] == ["a", "c"]
    assert [s["unshuffled"] for s in doc["songs"]] == [1, 0]
    assert (doc["current"], doc["position"]) == (1, 0.0)  # the next one, from its start


def test_fields_it_doesnt_know_are_kept_when_written_again():
    doc = {**EXAMPLE, "later": {"x": 1},
           "songs": [{**EXAMPLE["songs"][0], "rating_then": 4}, EXAMPLE["songs"][2]]}  # fmt: skip
    kept = parse(doc)
    state = State(((7, False), (8, True)), (0, 1), 0, 1.0, "GH")
    out = nowplaying.document(
        state, {7: ("LD/GH/03.flac", H3), 8: ("MO/Kindling.mp3", None)}, datetime.now(UTC), kept
    )
    assert out["later"] == {"x": 1} and out["songs"][0]["rating_then"] == 4
    assert "rating_then" not in out["songs"][1]
    valid(out)


def test_it_is_written_whole_in_the_root_else_beside_the_index(tmp_path):
    where = where_in(tmp_path)
    written = nowplaying.write(where, {"format": 1}, "b2c4")
    assert written == where.root_file() and read_json(written) == {"format": 1}
    assert os.listdir(os.path.dirname(written)) == ["now-playing.json"]  # no temporary file
    no_id = dataclasses.replace(where, computer=None)
    assert nowplaying.write(no_id, {"format": 1}, None) == where.local  # no id: beside the index
    blocked = Places(str(tmp_path / "Music" / ".musikata"), str(tmp_path / "local.json"), "x")
    (tmp_path / "Music" / ".musikata" / "x").write_text("a file where its folder goes")
    assert nowplaying.write(blocked, {"format": 1}, "x") == str(tmp_path / "local.json")
    nowhere = Places(None, str(tmp_path / "Music" / ".musikata" / "x" / "n.json"), "x")
    assert nowplaying.write(nowhere, {"format": 1}, "x") is None


# ---------- when it is written ----------


def state(songs=(1, 2, 3), cursor=0, position=0.0, source="GH"):
    return State(tuple((s, False) for s in songs), tuple(range(len(songs))), cursor, position,
                 source)  # fmt: skip


def test_a_change_of_the_queue_is_written_and_the_same_never_twice():
    keeper = nowplaying.Keeper(FakeClock())
    assert keeper.due(state(), QUEUE) and not keeper.due(state(), QUEUE)
    assert keeper.due(state(songs=(1, 2)), QUEUE)
    assert keeper.due(state(songs=(1, 2), source="Songs"), QUEUE)
    order = State(((1, False), (2, False)), (1, 0), 0, 0.0, "Songs")
    assert keeper.due(order, QUEUE)  # shuffled: the order shuffle off returns to changed
    assert not keeper.due(State(order.songs, order.unshuffled, 1, 0.0, "Songs"), QUEUE)


def test_the_current_song_and_its_place_are_written_on_pause_and_at_quit():
    keeper = nowplaying.Keeper(FakeClock())
    keeper.settle(state())
    assert not keeper.due(state(cursor=1, position=3.0), QUEUE)  # a song ending: not yet
    assert keeper.due(state(cursor=1, position=3.0), PAUSE)
    assert not keeper.due(state(cursor=1, position=3.0), PAUSE)
    assert not keeper.due(state(cursor=1, position=3.0), QUIT)
    assert keeper.due(state(cursor=1, position=9.0), QUIT)


def test_while_playing_the_place_is_written_at_most_once_a_minute():
    clock = FakeClock()
    keeper = nowplaying.Keeper(clock)
    keeper.settle(state())
    clock.advance(seconds=59)
    assert not keeper.ticks() and not keeper.due(state(position=59.0), TICK)
    clock.advance(seconds=1)
    assert keeper.ticks() and keeper.due(state(position=60.0), TICK)
    assert not keeper.ticks()
    clock.advance(seconds=30)
    assert keeper.due(state(songs=(4,)), QUEUE)  # a change of the queue starts the minute again
    clock.advance(seconds=45)
    assert not keeper.due(state(songs=(4,), position=75.0), TICK)


class Recorder:
    def __init__(self):
        self.calls, self.threads = [], []

    def __call__(self, **fields):
        self.calls.append(fields)
        self.threads.append(threading.current_thread().name)
        return True


def test_keeping_writes_off_the_callers_thread_making_this_computers_id_once(tmp_path, index):
    (tmp_path / "Music" / ".musikata").mkdir(parents=True)
    where = nowplaying.places(str(tmp_path / "Music"), str(tmp_path / "index"), None)
    made, threads = [], []

    def read():
        threads.append(threading.current_thread().name)
        return index.read()

    keeping = nowplaying.Keeping(where, read, FakeClock(), None,
                                 computer=lambda: made.append(1) or "b2c4")  # fmt: skip
    found = ids(index)
    first = keeping.changed(state(songs=(found["LD/GH/01.flac"],)), QUEUE)
    assert keeping.changed(state(songs=(found["LD/GH/01.flac"],)), QUEUE) is None
    second = keeping.changed(state(songs=(found["LD/GH/03.flac"],)), QUEUE)
    assert first.result() == second.result() == where.root_file("b2c4") and made == [1]
    keeping.close()
    doc = read_json(where.root_file("b2c4"))
    assert [s["path"] for s in doc["songs"]] == ["LD/GH/03.flac"]
    assert doc["saved"] == "2026-11-25T12:00:00Z"
    assert threads and all(t.startswith("now playing") for t in threads)


def test_keeping_beside_the_index_needs_no_computer_id(tmp_path, index):
    where = nowplaying.places(str(tmp_path / "Music"), str(tmp_path / "index"), None)
    keeping = nowplaying.Keeping(where, index.read, FakeClock(), computer=lambda: 1 / 0)
    assert keeping.changed(state(songs=()), QUEUE).result() == where.local
    keeping.close()


def test_a_newer_formats_file_is_never_written(tmp_path, index, caplog):
    where = where_in(tmp_path)
    path = kept_file(os.path.dirname(where.root_file()), {**EXAMPLE, "format": 2})
    kept = nowplaying.load(where)
    with caplog.at_level(logging.WARNING):
        keeping = nowplaying.Keeping(where, index.read, FakeClock(), kept)
    assert keeping.changed(state(), QUEUE) is None and not keeping.ticks()
    keeping.close()
    assert read_json(path)["format"] == 2
    assert "newer MusiKata's" in caplog.text


def test_shuffle_and_repeat_are_kept_on_its_thread_in_the_order_asked(tmp_path, index):
    recorder = Recorder()
    where = where_in(tmp_path)
    keeping = nowplaying.Keeping(where, index.read, FakeClock(), set_playback=recorder)
    keeping.playback(shuffle=True)
    assert keeping.playback(repeat="all").result() is True
    keeping.close()
    assert recorder.calls == [{"shuffle": True}, {"repeat": "all"}]
    assert all(t.startswith("now playing") for t in recorder.threads)
    assert nowplaying.Keeping(where, index.read, FakeClock()).playback(shuffle=True) is None


def test_the_visualization_is_kept_on_the_same_thread_after_the_writes_before_it(tmp_path, index):
    """R11.4.5: one thread writes the shared settings, so the visualization's write never
    overlaps shuffle's."""
    recorder = Recorder()
    where = where_in(tmp_path)
    keeping = nowplaying.Keeping(
        where, index.read, FakeClock(), set_playback=recorder, set_appearance=recorder
    )
    keeping.playback(shuffle=True)
    assert keeping.appearance(visualization="none").result() is True
    keeping.close()
    assert recorder.calls == [{"shuffle": True}, {"visualization": "none"}]
    assert len(set(recorder.threads)) == 1
    assert (
        nowplaying.Keeping(where, index.read, FakeClock()).appearance(visualization="none") is None
    )


def test_the_mini_players_layout_and_places_are_kept_on_the_same_thread(tmp_path, index):
    """R15.2, R15.3: its writes of the shared settings never overlap the others'."""
    recorder = Recorder()
    where = where_in(tmp_path)
    keeping = nowplaying.Keeping(
        where, index.read, FakeClock(), set_appearance=recorder, set_mini_player=recorder
    )
    keeping.appearance(visualization="none")
    assert keeping.mini_player(layout="disc").result() is True
    keeping.close()
    assert recorder.calls == [{"visualization": "none"}, {"layout": "disc"}]
    assert len(set(recorder.threads)) == 1
    assert nowplaying.Keeping(where, index.read, FakeClock()).mini_player(layout="disc") is None


def test_the_equalizer_is_kept_on_the_same_thread(tmp_path, index):
    """R19.5: its writes of the shared settings never overlap the others'."""
    recorder = Recorder()
    where = where_in(tmp_path)
    keeping = nowplaying.Keeping(
        where, index.read, FakeClock(), set_playback=recorder, set_equalizer=recorder
    )
    keeping.playback(shuffle=True)
    assert keeping.equalizer(on=True).result() is True
    keeping.close()
    assert recorder.calls == [{"shuffle": True}, {"on": True}]
    assert len(set(recorder.threads)) == 1
    assert nowplaying.Keeping(where, index.read, FakeClock()).equalizer(on=True) is None


def test_a_write_that_breaks_is_logged_and_the_next_one_tries_again(tmp_path, caplog):
    where = where_in(tmp_path)
    keeping = nowplaying.Keeping(where, lambda: 1 / 0, FakeClock(), executor=ThreadPoolExecutor(1))
    with caplog.at_level(logging.ERROR):
        assert keeping.changed(state(), QUEUE).result() is None
    assert "keeping what's playing failed" in caplog.text
    keeping.close()
