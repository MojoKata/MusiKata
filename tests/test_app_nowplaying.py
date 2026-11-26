"""The queue as the app plays it (the Player bridge of src/musikata/bridges.py, and
src/musikata/nowplaying.py; R7.1 to R7.3, R6.5): a double click queuing the rest of its list, a
song that ends starting the next, the bar's buttons, Play next and Add to queue, Up next's rows,
reorder and ×, and what the bar says; then the bar and Up next in the window.

The engine is a stand-in that plays nothing (`FakeEngine`): it says a song began when asked, and a
test says when it ended, so every rule is shown without a device or a wait on real audio. The real
engine playing into a null output is tests/test_app_player.py's.

Why: what plays next is decided here every time a song ends; a queue that skips a song when Next
and an end cross, a Previous that never goes back, or a bar that names another song than the one
heard are each only noticed by listening."""

import os
import random
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock, fill
from PySide6.QtCore import QCoreApplication, QObject, QPointF, Qt, Signal, Slot
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from musikata import app, bridges, layout, models, nowplaying, player, tour
from musikata_core import db
from musikata_core.audio.queue import ALL, ONE

WAIT = 5_000

SONGS = [
    {"path": "LD/GH/01.flac", "title": "Tidewater", "artist": "Lumen Drift",
     "album": "Glass Harbor", "track": 1, "length": 200.0},
    {"path": "LD/GH/02.flac", "title": "Glass Harbor", "artist": "Lumen Drift",
     "album": "Glass Harbor", "track": 2, "length": 100.0, "rating": 4},
    {"path": "LD/GH/03.flac", "title": None, "artist": "Lumen Drift", "album": "Glass Harbor",
     "track": 3, "length": 60.0},
    {"path": "MO/Kindling.mp3", "title": "Kindling", "artist": None, "length": 90.0},
]  # fmt: skip


class FakeEngine(QObject):
    """The engine's signals and slots, playing nothing: a song begins as soon as it is asked
    for, and ends, fails or moves when a test says so (`end`, `fail`, `move`)."""

    began = Signal(str, float)
    moved = Signal(float)
    pausedChanged = Signal(bool)
    ended = Signal(str)
    stopped = Signal(str)
    failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.asked = []  # what it was asked, in order: ("play", path), ("pause",), …
        self.path = ""

    @Slot()
    def setup(self):
        pass

    @Slot(str)
    def play(self, path):
        self.asked.append(("play", path))
        self.path = path
        self.began.emit(path, 42.0)

    @Slot()
    def pause(self):
        self.asked.append(("pause",))
        self.pausedChanged.emit(True)

    @Slot()
    def resume(self):
        self.asked.append(("resume",))
        self.pausedChanged.emit(False)

    @Slot()
    def stop(self):
        self.asked.append(("stop",))
        if self.path:
            path, self.path = self.path, ""
            self.stopped.emit(path)

    @Slot(float)
    def set_volume(self, gain):
        self.asked.append(("volume", round(gain, 3)))

    @Slot()
    def shutdown(self):
        self.moveToThread(QCoreApplication.instance().thread())

    def played(self):
        return [os.path.basename(a[1]) for a in self.asked if a[0] == "play"]


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, SONGS)
    yield i
    i.close()


@pytest.fixture
def made(tmp_path, index, qapp):
    """A player over the index with a fake engine, and the Songs list by track: (player,
    engine, songs)."""
    engine = FakeEngine()
    refused = {}
    p = bridges.Player(str(tmp_path), engine, refuse=lambda path: refused.get(path, ""),
                       read=index.read, rng=random.Random(5))  # fmt: skip
    p.refused = refused
    songs = models.SongsModel(index.read, "tracks")
    songs.source = "Songs"
    songs.reload()
    yield p, engine, songs
    p.close()


def ids(index, *paths):
    found = dict(index.read().execute("SELECT path, id FROM song"))
    return [found[p] for p in paths]


def wait_playing(qtbot, p, engine, n):
    """Until the engine was asked for its nth song and the player heard it begin (the fake's
    length, 0:42, in place of the index's)."""
    qtbot.waitUntil(
        lambda: len(engine.played()) >= n and p.property("playing") and p.property("length") == 42,
        timeout=WAIT,
    )


# ---------- the words (plain functions) ----------


def test_the_bars_line_and_up_nexts_name_the_artist_and_album():
    info = nowplaying.SongInfo("a.flac", "Signal Fires", "Lumen Drift", "Glass Harbor", 258.0, 5,
                               "")  # fmt: skip
    assert nowplaying.bar_line(info) == "Lumen Drift — Glass Harbor"
    assert nowplaying.row_line(info) == "Lumen Drift · Glass Harbor"
    alone = nowplaying.SongInfo("b.flac", "b", "", "", None, 0, "")
    assert nowplaying.bar_line(alone) == nowplaying.row_line(alone) == "Unknown artist"


def test_up_nexts_line_says_where_from_how_many_and_how_long():
    assert nowplaying.queue_line("Glass Harbor", 7, 33 * 60) == (
        "Playing from Glass Harbor · 7 up next · 33 min"
    )
    assert nowplaying.queue_line("", 1, 20) == "1 up next · 1 min"
    assert nowplaying.queue_line("Songs", 0, 0) == "Playing from Songs · Nothing up next"


def test_the_volume_follows_the_ear_and_stays_between_nothing_and_full(qapp):
    assert player.gain_of(0.0) == 0.0 and player.gain_of(1.0) == pytest.approx(1.0)
    assert 0.0 < player.gain_of(0.5) < 0.5  # half as loud is less than half the gain
    assert player.gain_of(-1) == 0.0 and player.gain_of(7) == pytest.approx(1.0)


# ---------- playing from a list (R7.1) ----------


def test_a_double_click_plays_the_song_and_queues_the_rest_of_its_list(made, index, qtbot):
    p, engine, songs = made
    now = []
    p.nowPlaying.connect(now.append)
    p.playFrom(songs, 1)
    wait_playing(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    assert engine.played() == ["02.flac"] and now == ["LD/GH/02.flac"]
    assert [e.song for e in p.queue.upcoming] == ids(index, "LD/GH/03.flac", "MO/Kindling.mp3")
    assert p.queue.source == "Songs"
    assert [p.property(n) for n in ("title", "line", "rating", "lengthText", "positionText")] == [
        "Glass Harbor", "Lumen Drift — Glass Harbor", 4, "0:42", "0:00"
    ]  # fmt: skip
    assert p.property("timeName") == "0:00 of 0:42" and p.property("failed") is False


def test_a_song_that_ends_starts_the_next_until_the_queue_has_played_out(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 2)
    wait_playing(qtbot, p, engine, 1)
    engine.ended.emit(engine.path)
    wait_playing(qtbot, p, engine, 2)
    assert engine.played() == ["03.flac", "Kindling.mp3"]
    assert p.property("title") == "Kindling" and p.property("line") == "Unknown artist"
    engine.ended.emit(engine.path)
    qtbot.waitUntil(lambda: p.last == "ended", timeout=WAIT)
    assert p.property("path") == "" and p.property("title") == "" and p.queue.current is None
    assert p.property("timeName") == "" and p.property("lengthText") == ""


def test_an_end_heard_after_another_song_was_asked_for_moves_nothing(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    first = engine.path
    p.next()
    wait_playing(qtbot, p, engine, 2)
    engine.ended.emit(first)  # the first song's end, crossing the Next
    engine.stopped.emit(first)
    engine.failed.emit(first, "late")
    qtbot.wait(50)  # the one fixed wait: nothing moves
    assert p.property("path") == "LD/GH/02.flac" and p.property("error") == ""
    assert engine.played() == ["01.flac", "02.flac"]


def test_play_on_an_album_plays_it_from_its_first_song_and_shuffle_from_any(made, index, qtbot):
    p, engine, _ = made
    album = index.read().execute("SELECT album_id FROM song WHERE path = 'LD/GH/02.flac'")
    album_id = album.fetchone()[0]
    p.playAlbum(album_id)
    wait_playing(qtbot, p, engine, 1)
    assert engine.played() == ["01.flac"] and p.queue.source == "Glass Harbor"
    p.shuffleAlbum(album_id)
    wait_playing(qtbot, p, engine, 2)
    assert p.property("shuffle") is True and len(p.queue) == 3
    p.playAlbum(-1)  # no such album: an empty queue, nothing new plays
    assert p.queue.current is None and len(engine.played()) == 2


def test_play_by_path_queues_the_song_alone_and_a_path_the_index_lacks_plays_as_a_file(made, qtbot):
    p, engine, _ = made
    p.play("LD/GH/03.flac")
    wait_playing(qtbot, p, engine, 1)
    assert p.property("title") == "03" and len(p.queue) == 1  # no title: the file's name
    p.play("elsewhere/x.flac")
    wait_playing(qtbot, p, engine, 2)
    qtbot.waitUntil(lambda: p.property("path") == "elsewhere/x.flac", timeout=WAIT)
    assert p.property("title") == "x" and p.property("line") == ""
    p.play("")
    assert len(engine.played()) == 2


# ---------- the bar's buttons (R6.5, R7.3) ----------


def test_play_pause_pauses_resumes_and_starts_a_cued_song(made, index, qtbot):
    p, engine, _ = made
    p.cue(ids(index, "LD/GH/01.flac", "LD/GH/02.flac"), "Glass Harbor")
    assert p.property("path") == "LD/GH/01.flac" and p.property("playing") is False
    assert p.property("lengthText") == "3:20" and engine.played() == []  # the index's length
    p.toggle()
    wait_playing(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    p.toggle()
    qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    p.toggle()
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    assert [a[0] for a in engine.asked][-3:] == ["play", "pause", "resume"]


def test_next_and_previous_play_on_while_playing_and_cue_while_paused(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    p.next()
    wait_playing(qtbot, p, engine, 2)
    engine.moved.emit(1.0)
    qtbot.waitUntil(lambda: p.property("position") == 1.0, timeout=WAIT)
    p.previous()  # in its first seconds: the song before
    wait_playing(qtbot, p, engine, 3)
    assert engine.played() == ["01.flac", "02.flac", "01.flac"]
    engine.moved.emit(10.0)
    qtbot.waitUntil(lambda: p.property("progress") > 0, timeout=WAIT)
    p.previous()  # further in: it starts again
    wait_playing(qtbot, p, engine, 4)
    assert engine.played()[-1] == "01.flac"
    p.toggle()
    qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    p.next()  # paused: the next song is cued, not started
    qtbot.waitUntil(lambda: p.property("path") == "LD/GH/02.flac", timeout=WAIT)
    assert len(engine.played()) == 4 and p.property("playing") is False


def test_next_past_the_end_stops_and_an_empty_queue_ignores_the_buttons(made, qtbot):
    p, engine, songs = made
    p.next()
    p.previous()
    p.toggle()
    assert engine.played() == [] and p.property("path") == ""
    p.playFrom(songs, 3)
    wait_playing(qtbot, p, engine, 1)
    p.next()
    qtbot.waitUntil(lambda: p.property("path") == "", timeout=WAIT)
    assert p.last == "stopped" and p.queue.current is None
    p.previous()  # back to the last song, cued
    assert p.property("path") == "MO/Kindling.mp3"


def test_shuffle_and_repeat_buttons_say_their_state(made, qtbot):
    p, engine, songs = made
    changed = []
    p.queueChanged.connect(lambda: changed.append(1))
    assert (p.property("shuffleName"), p.property("repeatName")) == ("Shuffle off", "Repeat off")
    p.toggleShuffle()
    p.cycleRepeat()
    assert p.property("shuffle") is True and p.property("shuffleName") == "Shuffle on"
    assert p.property("repeat") == ALL and p.property("repeatName") == "Repeat all"
    p.cycleRepeat()
    assert p.property("repeat") == ONE and len(changed) == 3
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    engine.ended.emit(engine.path)  # repeat One: the same song again
    wait_playing(qtbot, p, engine, 2)
    assert engine.played() == ["01.flac", "01.flac"]


def test_the_volume_is_kept_between_nothing_and_full_and_sent_to_the_engine(made, qtbot):
    p, engine, songs = made
    assert p.property("volume") == 1.0
    p.playFrom(songs, 0)  # the playback thread runs
    wait_playing(qtbot, p, engine, 1)
    p.setVolume(1.5)  # already full: nothing
    p.setVolume(-2)
    qtbot.waitUntil(lambda: ("volume", 0.0) in engine.asked, timeout=WAIT)
    assert p.property("volume") == 0.0


# ---------- songs that can't play ----------


def test_a_song_whose_root_isnt_there_is_cued_and_says_why(made, qtbot):
    p, engine, songs = made
    p.refused["LD/GH/01.flac"] = "~/Music isn't available, so its songs can't play"
    p.playFrom(songs, 0)
    assert p.property("path") == "LD/GH/01.flac" and p.property("failed") is True
    assert p.property("line") == "~/Music isn't available, so its songs can't play"
    assert engine.played() == []


def test_a_song_gone_from_the_library_says_so(made, index, qtbot, caplog):
    p, engine, _ = made
    p.play_songs([123456], "Songs")
    assert p.property("error") == "That song is no longer in the library"
    assert "no longer in the index" in caplog.text and engine.played() == []


def test_a_song_that_fails_stays_cued_with_why(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    engine.failed.emit(engine.path, "nothing in 01.flac decodes")
    qtbot.waitUntil(lambda: p.last == "failed", timeout=WAIT)
    assert p.property("path") == "LD/GH/01.flac" and p.property("playing") is False
    assert p.property("line") == "nothing in 01.flac decodes"


def test_stop_leaves_the_queues_song_cued(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    p.stop()
    qtbot.waitUntil(lambda: p.last == "stopped", timeout=WAIT)
    assert p.property("path") == "LD/GH/01.flac" and p.property("playing") is False


# ---------- Play next, Add to queue and Up next (R7.2) ----------


def test_play_next_and_add_to_queue_put_a_rows_songs_where_they_say(made, index, qtbot):
    p, engine, songs = made
    p.addToQueue(songs, 3)  # into an empty queue: cued
    assert p.property("path") == "MO/Kindling.mp3" and engine.played() == []
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    p.addToQueue(songs, 3)
    p.playNext(songs, 2)
    p.addToQueue(songs, 99)  # past the rows: nothing
    up = p.property("upNext")
    rows = [up.row_of(i) for i in range(up.rowCount())]
    assert [(r["kind"], r["section"], r["first"], r["title"]) for r in rows] == [
        ("now", "Now playing", True, "Tidewater"),
        ("next", "Next · added by you", True, "03"),
        ("next", "Next · added by you", False, "Kindling"),
        ("next", "Next from Songs", True, "Glass Harbor"),
        ("next", "Next from Songs", False, "03"),
        ("next", "Next from Songs", False, "Kindling"),
    ]
    assert rows[0]["line"] == "Lumen Drift · Glass Harbor" and rows[0]["time"] == "3:20"
    assert up.property("line") == "Playing from Songs · 5 up next · 7 min"
    assert up.property("emptyText") == "" and up.row_of(99) is None


def test_up_next_lists_the_songs_played_last_the_latest_first(made, index, qtbot):
    p, engine, songs = made
    p.cue(ids(index, "LD/GH/01.flac", "LD/GH/02.flac", "LD/GH/03.flac"), "Glass Harbor", at=2)
    up = p.property("upNext")
    assert [(up.row_of(i)["kind"], up.row_of(i)["title"]) for i in range(3)] == [
        ("now", "03"), ("played", "Glass Harbor"), ("played", "Tidewater")
    ]  # fmt: skip
    assert up.row_of(1)["section"] == "Played" and up.row_of(1)["first"] is True
    assert up.property("line") == "Playing from Glass Harbor · Nothing up next"
    role = {v.data().decode(): k for k, v in up.roleNames().items()}
    assert up.data(up.index(0), role["title"]) == "03" and up.data(up.index(0), 0) is None
    assert up.data(up.index(9), role["title"]) is None


def test_a_row_of_up_next_plays_moves_or_goes_at_a_click(made, index, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    up = p.property("upNext")

    def titles():
        return [up.row_of(i)["title"] for i in range(up.rowCount())]

    assert titles() == ["Tidewater", "Glass Harbor", "03", "Kindling"]
    p.moveRow(3, 1)  # Kindling dropped above Glass Harbor
    assert titles() == ["Tidewater", "Kindling", "Glass Harbor", "03"]
    p.moveRow(1, 4)  # dropped below the last: last
    assert titles() == ["Tidewater", "Glass Harbor", "03", "Kindling"]
    p.moveRow(0, 2)  # the song playing doesn't move
    p.moveRow(99, 0)
    assert titles() == ["Tidewater", "Glass Harbor", "03", "Kindling"]
    p.removeRow(2)
    p.removeRow(0)  # the song playing stays
    p.removeRow(99)
    assert titles() == ["Tidewater", "Glass Harbor", "Kindling"]
    p.playRow(2)
    wait_playing(qtbot, p, engine, 2)
    assert engine.played()[-1] == "Kindling.mp3"
    assert titles() == ["Kindling", "Glass Harbor", "Tidewater"]  # those skipped count as played
    p.playRow(99)
    assert len(engine.played()) == 2


def test_an_empty_up_next_says_so_and_a_song_gone_says_that(made, index):
    p, engine, _ = made
    up = p.property("upNext")
    up.refresh()
    assert up.rowCount() == 0 and up.property("emptyText") == nowplaying.EMPTY
    assert up.property("line") == ""
    p.cue([123456], "Songs")
    assert up.row_of(0)["title"] == "A song no longer in the library" and up.row_of(0)["line"] == ""


def test_the_queue_button_opens_up_next_and_closes_it_again(made):
    p, _, _ = made
    p.toggleUpNext()
    assert p.property("upNextOpen") is True
    p.toggleUpNext()
    p.closeUpNext()
    assert p.property("upNextOpen") is False


def test_a_tours_step_cues_an_album_adds_songs_and_opens_up_next(made, index):
    p, engine, _ = made
    p.go({"queue": "Glass Harbor", "at": 1, "added": ["Kindling", "No such song"],
          "upNext": True})  # fmt: skip
    assert p.property("path") == "LD/GH/02.flac" and p.property("upNextOpen") is True
    assert [e.song for e in p.queue.upcoming] == ids(index, "MO/Kindling.mp3", "LD/GH/03.flac")
    assert [e.song for e in p.queue.played] == ids(index, "LD/GH/01.flac") and engine.played() == []
    p.go({"view": "albums"})
    assert p.property("upNextOpen") is False and p.property("path") == "LD/GH/02.flac"


def test_a_player_without_an_index_has_no_albums_and_no_songs(tmp_path, qapp):
    p = bridges.Player(str(tmp_path), FakeEngine())
    p.playAlbum(1)
    p.go({"queue": "Glass Harbor"})
    assert p.queue.current is None and p.property("path") == ""
    assert p._song(1) is None
    p.close()


# ---------- in the window ----------


@pytest.fixture
def shell(tmp_path, qapp):
    root = tmp_path / "Music"
    root.mkdir()
    engines = []

    def playback():
        engines.append(FakeEngine())
        return engines[-1]

    s = app.load(str(root), {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)},
                 FakeClock(), lambda: ThreadPoolExecutor(1), playback)  # fmt: skip
    fill(s.index, SONGS)
    s.library.reload()
    s.window.show()
    s.engine_ = engines[0]
    yield s
    s.close()


def find(shell, name):
    found = []

    def walk(item):
        if item.objectName() == name:
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    assert len(found) == 1, (name, found)
    return found[0]


def click(shell, item, button=Qt.MouseButton.LeftButton):
    at = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(shell.window, button, Qt.KeyboardModifier(0), at)


@pytest.mark.slow
def test_the_bar_shows_the_song_and_its_buttons_play_it(shell, qtbot, qtlog):
    p = shell.player
    p.go({"queue": "Glass Harbor"})
    qtbot.waitExposed(shell.window)
    shell.window.grabWindow()
    assert find(shell, "barTitle").property("text") == "Tidewater"
    assert find(shell, "barLine").property("text") == "Lumen Drift — Glass Harbor"
    assert find(shell, "barLength").property("text") == "3:20"
    click(shell, find(shell, "playPause"))
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    click(shell, find(shell, "next"))
    qtbot.waitUntil(lambda: p.property("title") == "Glass Harbor", timeout=WAIT)
    click(shell, find(shell, "shuffle"))
    click(shell, find(shell, "repeat"))
    qtbot.waitUntil(lambda: p.property("repeat") == ALL, timeout=WAIT)
    assert p.property("shuffle") is True
    QTest.keyClick(shell.window, Qt.Key.Key_Space)
    qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    QTest.keyClick(shell.window, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(shell.window, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    click(shell, find(shell, "previous"))
    click(shell, find(shell, "queueButton"))
    qtbot.waitUntil(lambda: find(shell, "upNext").isVisible(), timeout=WAIT)
    shell.window.grabWindow()
    assert find(shell, "upNextLine").property("text").startswith("Playing from Glass Harbor")
    rows = find(shell, "upNextRows")
    qtbot.waitUntil(lambda: rows.property("count") == 3, timeout=WAIT)
    click(shell, find(shell, "closeUpNext"))
    qtbot.waitUntil(lambda: not find(shell, "upNext").isVisible(), timeout=WAIT)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []


@pytest.mark.slow
def test_a_right_click_on_a_song_offers_play_next_and_add_to_queue(shell, qtbot):
    p = shell.player
    shell.library.show("songs")
    qtbot.waitExposed(shell.window)
    rows = find(shell, "songs")

    def row(title):
        return next((r for r in rows.property("contentItem").childItems()
                     if r.property("title") == title), None)  # fmt: skip

    qtbot.waitUntil(lambda: row("Kindling") is not None, timeout=WAIT)
    click(shell, row("Kindling"), Qt.MouseButton.RightButton)
    menu = shell.window.findChild(QObject, "addToQueue")
    qtbot.waitUntil(lambda: menu.property("visible") is True, timeout=WAIT)
    menu.triggered.emit()
    qtbot.waitUntil(lambda: p.property("path") == "MO/Kindling.mp3", timeout=WAIT)
    QTest.mouseDClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0),
                      row("Tidewater").mapToScene(QPointF(200, 18)).toPoint())  # fmt: skip
    qtbot.waitUntil(lambda: p.property("title") == "Tidewater", timeout=WAIT)
    assert len(p.queue.upcoming) == len(SONGS) - 1


@pytest.mark.slow
def test_the_bar_and_up_next_keep_their_text_in_their_boxes_at_both_sizes(shell, qtbot):
    long = "A title long enough to run past any box the bar or Up next gives it " * 3
    fill(shell.index, [{"path": "Z/long.flac", "title": long, "artist": long, "album": long}])
    shell.library.reload()
    shell.player.go({"queue": long, "upNext": True})
    shell.player.cue(ids(shell.index, "Z/long.flac", "LD/GH/01.flac"), long)
    for w, h in tour.SIZES:
        shell.window.setWidth(w)
        shell.window.setHeight(h)
        qtbot.waitUntil(lambda w=w: shell.window.width() == w, timeout=WAIT)
        shell.window.grabWindow()
        assert layout.faults(shell.window) == []
    assert isinstance(find(shell, "nowPlayingBar"), QQuickItem)
