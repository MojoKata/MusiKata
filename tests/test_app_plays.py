"""Play counts in the running app (src/musikata/plays.py, the Player bridge's counting, the lists'
Plays column, app.count_plays; R7.9, A2.8): what the engine reports heard and counted, kept in
the index and the root's `.musikata/<computer id>/plays.json`, the other computers' files watched,
and the counts shown in the song lists and sorted by.

The engine is a stand-in that plays nothing (`FakeEngine`, tests/fakes.py); the places it reports
are sent by the test. Tests wait on the signal or state that says the work is done.

Why: counting hangs on what the engine says, in the order it says it, across joins, seeks and
repeat One; a count that never reaches the index or the file, or a file another computer wrote
that is never read again, is a count lost."""

import json
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock, FakeEngine, fill, played
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, bridges
from musikata.plays import PlayCounts
from musikata_core import db, rootfiles
from musikata_core.audio.played import Play
from musikata_core.audio.queue import ONE
from musikata_core.clock import SystemClock

WAIT = 5_000
H1, H2 = "1" * 64, "2" * 64
SONGS = [
    {"path": "LD/GH/01.flac", "title": "Tidewater", "album": "Glass Harbor", "track": 1},
    {"path": "LD/GH/02.flac", "title": "Glass Harbor", "album": "Glass Harbor", "track": 2},
]  # fmt: skip


class Counts:
    """What the player hands its plays to, recorded."""

    def __init__(self):
        self.plays, self.ticks = [], 0

    def played(self, play):
        self.plays.append(play.song)

    def tick(self):
        self.ticks += 1


def hashed(index):
    """Each song given an audio hash, as a scan gives it."""
    index.write(lambda c: c.executemany(
        "UPDATE song SET audio_hash = ? WHERE path = ?",
        [(H1, "LD/GH/01.flac"), (H2, "LD/GH/02.flac")],
    )).result()  # fmt: skip


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, SONGS)
    hashed(i)
    yield i
    i.close()


@pytest.fixture
def counted(tmp_path, index, qapp):
    """A player over the index with a fake engine, counting into a recorder: (player, engine,
    counts, the songs' ids by file name)."""
    engine = FakeEngine()
    clock = FakeClock()
    p = bridges.Player(str(tmp_path), engine, read=index.read, rng=random.Random(5), clock=clock)
    counts = Counts()
    p.count(counts)
    by_name = {os.path.basename(path): i for path, i in index.read().execute(
        "SELECT path, id FROM song")}  # fmt: skip
    p.clock_, p.engine_ = clock, engine
    yield p, engine, counts, by_name
    p.close()


def heard(p, start, end, step=0.25):
    """The engine reports the song playing from `start` to `end` seconds, the clock moving on."""
    place = start
    while place < end:
        place = min(end, place + step)
        p.clock_.advance(seconds=step)
        p.engine_.moved.emit(place)


def began(qtbot, p, engine, n):
    qtbot.waitUntil(lambda: len(engine.played()) >= n and p.property("playing"), timeout=WAIT)


def test_a_song_of_the_queue_heard_to_half_its_length_is_counted_once(counted, qtbot):
    p, engine, counts, by_name = counted
    p.play_songs([by_name["01.flac"], by_name["02.flac"]], "Glass Harbor")
    began(qtbot, p, engine, 1)
    heard(p, 0.0, 20.75)
    assert counts.plays == [] and counts.ticks > 0
    heard(p, 20.75, 42.0)  # the fake's songs are 0:42: counted at 0:21
    assert counts.plays == [by_name["01.flac"]]


def test_a_seek_forward_past_the_middle_isnt_counted(counted, qtbot):
    p, engine, counts, by_name = counted
    p.play_songs([by_name["01.flac"]], "Glass Harbor")
    began(qtbot, p, engine, 1)
    heard(p, 0.0, 5.0)
    p.seek(30.0)
    qtbot.waitUntil(lambda: p._seeking == 0, timeout=WAIT)
    heard(p, 30.0, 42.0)
    assert counts.plays == []


def test_the_next_song_joined_and_repeat_one_are_new_plays_each_counted(counted, qtbot):
    p, engine, counts, by_name = counted
    p.play_songs([by_name["01.flac"], by_name["02.flac"]], "Glass Harbor")
    began(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: engine.follower[1].endswith("02.flac"), timeout=WAIT)
    heard(p, 0.0, 42.0)
    engine.join()
    qtbot.waitUntil(lambda: p.property("title") == "Glass Harbor", timeout=WAIT)
    p.cycleRepeat()
    p.cycleRepeat()
    assert p.property("repeat") == ONE
    qtbot.waitUntil(lambda: engine.follower[1].endswith("02.flac"), timeout=WAIT)
    heard(p, 0.0, 42.0)
    engine.join()  # repeat One: the song joined to itself
    qtbot.waitUntil(lambda: p.property("position") == 0.0, timeout=WAIT)
    heard(p, 0.0, 42.0)
    assert counts.plays == [by_name["01.flac"], by_name["02.flac"], by_name["02.flac"]]


def test_a_paused_song_ticks_nothing_and_a_stopped_one_is_never_counted(counted, qtbot):
    p, engine, counts, by_name = counted
    p.play_songs([by_name["01.flac"]], "Glass Harbor")
    began(qtbot, p, engine, 1)
    heard(p, 0.0, 10.0)
    p.pause()
    qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    ticks = counts.ticks
    engine.moved.emit(10.0)
    assert counts.ticks == ticks
    p.stop()
    qtbot.waitUntil(lambda: p.last == "stopped", timeout=WAIT)
    engine.moved.emit(30.0)
    assert counts.plays == []


def test_a_file_played_outside_the_library_isnt_counted(counted, tmp_path, qtbot):
    p, engine, counts, _ = counted
    p.play_file(str(tmp_path / "elsewhere.flac"))
    began(qtbot, p, engine, 1)
    heard(p, 0.0, 42.0)
    assert counts.plays == []


# ---------- the counts kept, and the other computers' files watched ----------


def musikata_of(tmp_path):
    musikata = tmp_path / "Music" / ".musikata"
    musikata.mkdir(parents=True, exist_ok=True)
    return str(musikata)


def other_file(musikata, computer, count):
    os.makedirs(os.path.join(musikata, computer), exist_ok=True)
    with open(rootfiles.file_of(musikata, computer), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "computer": {"id": computer}, "songs": [
            {"path": "LD/GH/01.flac", "hash": H1, "count": count,
             "last": "2026-11-25T20:41:00Z"}]}, f)  # fmt: skip


def totals(index):
    return rootfiles.totals(
        index.read(), [i for (i,) in index.read().execute("SELECT id FROM song")]
    )


@pytest.mark.slow
def test_another_computers_file_is_read_at_start_and_again_when_it_changes(tmp_path, index, qtbot):
    musikata = musikata_of(tmp_path)
    other_file(musikata, "b2c4", 3)
    keeping = rootfiles.Keeping(index, musikata, FakeClock(), "me")
    counts = PlayCounts(keeping, musikata, SystemClock())  # the watch gathers for a real second
    told = []
    counts.changed.connect(
        lambda: told.append(threading.current_thread() is threading.main_thread())
    )
    with qtbot.waitSignal(counts.changed, timeout=WAIT):
        counts.start()
    assert list(totals(index).values()) == [3] and told == [True]
    qtbot.waitUntil(lambda: "b2c4" in counts._watcher.known(), timeout=WAIT)
    with qtbot.waitSignal(counts.changed, timeout=WAIT):
        other_file(musikata, "b2c4", 5)
    assert list(totals(index).values()) == [5]
    with qtbot.waitSignal(counts.changed, timeout=WAIT):  # a new computer's folder
        other_file(musikata, "c3d5", 2)
    qtbot.waitUntil(lambda: list(totals(index).values()) == [7], timeout=WAIT)
    counts.close()


def test_plays_counted_reach_the_index_and_the_file_written_at_close(tmp_path, index, qtbot):
    musikata = musikata_of(tmp_path)
    keeping = rootfiles.Keeping(index, musikata, FakeClock(), "me")
    counts = PlayCounts(keeping, musikata, FakeClock(), watching=False)
    with qtbot.waitSignal(counts.changed, timeout=WAIT):
        counts.start()
    song = index.read().execute("SELECT id FROM song ORDER BY path").fetchone()[0]
    with qtbot.waitSignal(counts.changed, timeout=WAIT):
        counts.played(Play(song, FakeClock().now()))
    counts.played(Play(song, FakeClock().now()))
    counts.tick()
    counts.moved()
    counts.close()
    with open(rootfiles.file_of(musikata, "me"), encoding="utf-8") as f:
        assert [s["count"] for s in json.load(f)["songs"]] == [2]


def test_this_computers_id_is_made_once_whichever_thread_asks_first():
    made = []
    once = app.Once(lambda: made.append(1) or "b2c4")
    with ThreadPoolExecutor(4) as pool:
        assert set(pool.map(lambda _: once(), range(8))) == {"b2c4"}
    assert made == [1]
    nothing = app.Once(lambda: made.append(2))
    assert nothing() is None and nothing() is None and made == [1, 2, 2]


# ---------- shown and sorted ----------


@pytest.fixture
def shell(tmp_path, qapp):
    root = tmp_path / "Music"
    root.mkdir()
    engines = []

    def playback():
        engines.append(FakeEngine())
        return engines[-1]

    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(root), env, FakeClock(), lambda: ThreadPoolExecutor(1), playback)
    fill(s.index, SONGS)
    hashed(s.index)
    s.library.reload()
    s.window.show()
    s.engine_ = engines[0]
    yield s
    s.close()


def find_all(shell, name):
    found = []

    def walk(item):
        if item.objectName() == name:
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    return found


def rows_plays(item, row="SongRow"):
    """The plays each row of a list of songs shows (SongRow's, or TrackRow's), top to bottom."""
    out = []

    def walk(i):
        if i.metaObject().className().startswith(row):
            out.append((i.y(), i.property("plays")))
        for child in i.childItems():
            walk(child)

    walk(item)
    return [plays for _, plays in sorted(out)]


@pytest.mark.slow
def test_a_song_played_shows_its_plays_the_songs_view_sorts_by_them_and_quitting_keeps_them(
    shell, tmp_path, qtbot
):
    """R7.9: counted once heard to its middle, the count shows in the Songs view and on the
    album's page, Songs sorts by it, and the root's plays.json has it once MusiKata closes."""
    p, lib = shell.player, shell.library
    played(shell.index, {"LD/GH/01.flac": 1}, computer="laptop")  # another computer's, read
    lib.show("songs")
    lib.sortSongs("title")
    ids = dict(shell.index.read().execute("SELECT path, id FROM song"))
    p.play_songs([ids["LD/GH/02.flac"]], "Songs")
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    for i in range(1, 100):
        shell.engine_.moved.emit(i * 0.25)
    qtbot.waitUntil(lambda: lib.property("songs").row(0)["plays"] == "1", timeout=WAIT)
    assert [lib.property("songs").row(i)["plays"] for i in range(2)] == ["1", "1"]
    qtbot.waitExposed(shell.window)
    qtbot.waitUntil(lambda: len(find_all(shell, "songs")) == 1, timeout=WAIT)
    head = find_all(shell, "head-plays")
    assert len(head) == 1
    at = head[0].mapToScene(QPointF(head[0].width() / 2, 16)).toPoint()
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)
    assert lib.property("songs").order() == ("plays", False)
    assert "PLAYS" in [h["label"] for h in lib.property("songHeaders")]
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: rows_plays(find_all(shell, "songs")[0]) == ["1", "1"], timeout=WAIT)
    lib.openAlbum(shell.index.read().execute("SELECT id FROM album").fetchone()[0])
    qtbot.waitUntil(lambda: len(find_all(shell, "albumSongs")) == 1, timeout=WAIT)
    shell.window.grabWindow()
    tracks = find_all(shell, "albumSongs")[0]
    qtbot.waitUntil(lambda: rows_plays(tracks, "TrackRow") == ["1", "1"], timeout=WAIT)
    root = str(tmp_path / "Music")
    shell.close()
    shell.close = lambda: None
    musikata = rootfiles.folder_of(root)
    mine = [
        n for n in rootfiles.folders(musikata) if os.path.isfile(rootfiles.file_of(musikata, n))
    ]
    assert len(mine) == 1
    with open(rootfiles.file_of(musikata, mine[0]), encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["computer"]["id"] == mine[0]
    assert [(s["path"], s["hash"], s["count"]) for s in doc["songs"]] == [("LD/GH/02.flac", H2, 1)]
