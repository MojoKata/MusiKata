"""The queue as the app plays it (the Player bridge of src/musikata/bridges.py, and
src/musikata/nowplaying.py; R7.1 to R7.3, R6.5): a double click queuing the rest of its list, a
song that ends starting the next, the bar's buttons, Play next and Add to queue, Up next's rows,
reorder and ×, and what the bar says; then the bar and Up next in the window; and what's playing,
shuffle and repeat kept across a restart (R1.8), when each is written and how a root opens with
them.

The engine is a stand-in that plays nothing (`FakeEngine`, tests/fakes.py): it says a song began
when asked, and a test says when it ended, so every rule is shown without a device or a wait on
real audio. The real engine playing into a null output is tests/test_app_player.py's.

Why: what plays next is decided here every time a song ends; a queue that skips a song when Next
and an end cross, a Previous that never goes back, or a bar that names another song than the one
heard are each only noticed by listening."""

import json
import logging
import os
import random
import shutil
from concurrent.futures import Executor, Future, ThreadPoolExecutor

import pytest
from fakes import FakeClock, FakeEngine, fill
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from musikata import app, bridges, layout, models, nowplaying, player, tour
from musikata_core import db, settings
from musikata_core import nowplaying as nowplaying_core
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


def test_the_song_playing_moved_by_organize_files_is_marked_where_it_is_now(made, index, qtbot):
    """R12.4, A2.8: the queue holds songs by id, so a song moved while it plays stays the one
    playing; the lists mark it at its new path once the index's rows are read again."""
    p, engine, songs = made
    now = []
    p.nowPlaying.connect(now.append)
    p.playFrom(songs, 1)
    wait_playing(qtbot, p, engine, 1)
    index.write(lambda c: c.execute(
        "UPDATE song SET path = 'LD/2019 - GH/02 - Glass Harbor.flac' WHERE path = 'LD/GH/02.flac'"
    )).result()  # fmt: skip
    p.reread()
    assert now == ["LD/GH/02.flac", "LD/2019 - GH/02 - Glass Harbor.flac"]
    assert p.property("path") == "LD/2019 - GH/02 - Glass Harbor.flac"
    p.reread()  # nothing changed since: nothing said
    assert len(now) == 2


def test_enter_on_a_selection_plays_its_first_song_and_queues_the_rest_of_its_list(
    made, index, qtbot
):
    p, engine, songs = made
    p.playSelection(songs)  # nothing selected: nothing plays
    assert p.queue.current is None and engine.played() == []
    songs.click(3, False, False)
    songs.click(1, True, False)
    p.playSelection(songs)
    wait_playing(qtbot, p, engine, 1)
    assert engine.played() == ["02.flac"] and p.queue.source == "Songs"
    assert [e.song for e in p.queue.upcoming] == ids(index, "LD/GH/03.flac", "MO/Kindling.mp3")


def test_the_menu_and_the_selection_bar_queue_the_whole_selection(made, index, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    songs.click(1, False, False)
    songs.click(3, True, False)
    p.playNext(songs, 3)  # a right click on a row in the selection: all of it
    assert [e.song for e in p.queue.upcoming][:2] == ids(index, "LD/GH/02.flac", "MO/Kindling.mp3")
    p.addToQueue(songs, 2)  # one outside it: its own
    assert [e.song for e in p.queue.upcoming if e.added] == ids(
        index, "LD/GH/02.flac", "MO/Kindling.mp3", "LD/GH/03.flac"
    )
    songs.click(2, False, False)
    p.playNextSelection(songs)  # the selection bar's Play next
    assert p.queue.upcoming[0].song == ids(index, "LD/GH/03.flac")[0]


def test_up_nexts_rows_are_selected_and_enter_plays_and_delete_removes_them(made, index, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    up = p.property("upNext")

    def titles():
        return [up.row_of(i)["title"] for i in range(up.rowCount())]

    def marks():
        return [(up.row_of(i)["selected"], up.row_of(i)["current"]) for i in range(up.rowCount())]

    down = int(Qt.Key.Key_Down.value)
    shift = int(Qt.KeyboardModifier.ShiftModifier.value)
    p.playSelected()  # nothing selected: nothing
    assert len(engine.played()) == 1
    changed = []
    up.dataChanged.connect(lambda *a: changed.append(a))
    up.click(1, False, False)
    assert changed and up.press(down, shift, 5) == 2
    assert marks() == [(False, False), (True, False), (True, True), (False, False)]
    assert up.press(int(Qt.Key.Key_Space.value), 0, 5) == -2
    up.click(0, True, False)  # the song playing too: Delete leaves it
    p.removeSelected()
    assert titles() == ["Tidewater", "Kindling"]
    assert marks() == [(True, True), (False, False)]  # what is left of the selection stays
    p.removeSelected()  # only the song playing: nothing goes
    assert titles() == ["Tidewater", "Kindling"]
    up.click(1, False, False)
    p.playSelected()
    wait_playing(qtbot, p, engine, 2)
    assert engine.played()[-1] == "Kindling.mp3"
    assert marks()[0] == (True, True)  # its entry, now playing, still selected


def test_a_song_that_ends_starts_the_next_until_the_queue_has_played_out(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 2)
    wait_playing(qtbot, p, engine, 1)
    engine.ended.emit(engine.ticket)
    wait_playing(qtbot, p, engine, 2)
    assert engine.played() == ["03.flac", "Kindling.mp3"]
    assert p.property("title") == "Kindling" and p.property("line") == "Unknown artist"
    engine.ended.emit(engine.ticket)
    qtbot.waitUntil(lambda: p.last == "ended", timeout=WAIT)
    assert p.property("path") == "" and p.property("title") == "" and p.queue.current is None
    assert p.property("timeName") == "" and p.property("lengthText") == ""


def test_an_end_heard_after_another_song_was_asked_for_moves_nothing(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    first = engine.ticket
    p.next()
    wait_playing(qtbot, p, engine, 2)
    engine.ended.emit(first)  # the first song's end, crossing the Next
    engine.stopped.emit(first)
    engine.failed.emit(first, "late")
    qtbot.wait(50)  # the one fixed wait: nothing moves
    assert p.property("path") == "LD/GH/02.flac" and p.property("error") == ""
    assert engine.played() == ["01.flac", "02.flac"]


# ---------- one song into the next (A4.2) and seeking (R7.4) ----------


def test_the_engine_is_told_what_follows_and_told_again_when_the_queue_changes(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: engine.told == ["02.flac"], timeout=WAIT)
    p.cycleRepeat()  # All: the same song follows, so nothing is told
    p.playNext(songs, 3)
    qtbot.waitUntil(lambda: engine.told[-1] == "Kindling.mp3", timeout=WAIT)
    p.toggleShuffle()  # the song added stays first
    p.removeRow(1)  # Up next's ×, on the song added
    qtbot.waitUntil(lambda: engine.told[-1] == "02.flac", timeout=WAIT)
    p.cycleRepeat()  # One: the song follows itself
    qtbot.waitUntil(lambda: engine.told[-1] == "01.flac", timeout=WAIT)
    p.toggleUpNext()  # nothing that changes what follows
    assert engine.told == ["02.flac", "Kindling.mp3", "02.flac", "01.flac"]
    assert engine.follower[1].endswith("01.flac")


def test_a_next_song_gone_or_out_of_reach_is_told_as_nothing_and_says_why_in_its_turn(made, qtbot):
    p, engine, songs = made
    p.refused["LD/GH/02.flac"] = "Its music folder isn't there"
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: engine.told == [""], timeout=WAIT)
    engine.ended.emit(engine.ticket)
    qtbot.waitUntil(lambda: p.property("error") == "Its music folder isn't there", timeout=WAIT)
    assert p.property("path") == "LD/GH/02.flac" and engine.played() == ["01.flac"]


WAITS = "Playing waits until ~/Music is back"


def test_a_root_gone_while_a_song_plays_lets_it_end_and_opens_nothing_after_it(made, qtbot):
    """R2.10: the song playing goes on to its end, as what the engine has can, and nothing is
    opened after it; Next and Up next say why, and Next leaves the song playing."""
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: engine.told == ["02.flac"], timeout=WAIT)
    assert p.property("nextNote") == "" and p.property("upNext").property("note") == ""
    for song in SONGS:
        p.refused[song["path"]] = WAITS
    p.reach_changed()  # the root went
    qtbot.waitUntil(lambda: engine.told == ["02.flac", ""], timeout=WAIT)  # told: nothing
    assert p.property("nextNote") == WAITS and p.property("upNext").property("note") == WAITS
    assert p.property("playing") and p.property("error") == "" and ("stop",) not in engine.asked
    p.reach_changed()  # nothing changed since: nothing told
    p.next()  # says why, and does nothing
    assert p.property("path") == "LD/GH/01.flac" and p.property("playing")
    engine.ended.emit(engine.ticket)  # the song played to its end
    qtbot.waitUntil(lambda: p.property("error") == WAITS, timeout=WAIT)
    assert p.property("path") == "LD/GH/02.flac" and not p.property("playing")
    assert engine.played() == ["01.flac"] and engine.told == ["02.flac", ""]
    p.refused.clear()
    p.reach_changed()  # back
    assert p.property("nextNote") == "" and p.property("upNext").property("note") == ""
    p.toggle()
    wait_playing(qtbot, p, engine, 2)
    assert engine.played() == ["01.flac", "02.flac"]
    qtbot.waitUntil(lambda: engine.told[-1] == "03.flac", timeout=WAIT)


# ---------- ReplayGain (R7.5) ----------

GAINED = [
    {"path": f"LD/GH/0{n}.flac", "title": f"Track {n}", "artist": "Lumen Drift",
     "album": "Glass Harbor", "track": n, "rg_track_gain": gain_, "rg_track_peak": 0.5,
     "rg_album_gain": -6.0, "rg_album_peak": 0.6}
    for n, gain_ in ((1, -7.0), (2, -5.0), (3, -9.0))
] + [{"path": "MO/Kindling.mp3", "title": "Kindling", "album": "Embers", "track": 1}]  # fmt: skip
ALBUM, UNTAGGED = 0.5012, 0.5012  # -6 dB: the album's gain, and R7.5's pre-amp
TRACK = {"01.flac": 0.4467, "02.flac": 0.5623, "03.flac": 0.3548}  # -7, -5, -9 dB


@pytest.fixture
def gained(tmp_path, qapp):
    """Players over an index of GAINED, each with a fake engine, closed after the test:
    gained(playback=None) gives the player, the engine and the songs' ids by file name."""
    index = db.Index(str(tmp_path / "gained.db"))
    fill(index, GAINED)
    by_name = {os.path.basename(p): i for p, i in index.read().execute("SELECT path, id FROM song")}
    made = []

    def make(playback=None):
        engine = FakeEngine()
        p = bridges.Player(str(tmp_path), engine, read=index.read, rng=random.Random(5),
                           playback=playback)  # fmt: skip
        made.append(p)
        return p, engine, by_name

    yield make
    for p in made:
        p.close()
    index.close()


def test_an_album_played_in_order_plays_at_its_album_gain_song_after_song(gained, qtbot):
    p, engine, ids_ = gained()
    p.playAlbum(_album_id(p, "Glass Harbor"))
    qtbot.waitUntil(lambda: ("02.flac", ALBUM) in engine.levels, timeout=WAIT)
    engine.join()
    qtbot.waitUntil(lambda: len(engine.levels) == 3, timeout=WAIT)
    assert engine.levels == [("01.flac", ALBUM), ("02.flac", ALBUM), ("03.flac", ALBUM)]


def test_an_album_from_its_second_song_on_is_in_order_and_one_song_alone_isnt(gained, qtbot):
    p, engine, ids_ = gained()
    p.play_songs([ids_["02.flac"], ids_["03.flac"]], "Glass Harbor")
    qtbot.waitUntil(lambda: len(engine.levels) == 2, timeout=WAIT)
    assert engine.levels == [("02.flac", ALBUM), ("03.flac", ALBUM)]
    p.play("LD/GH/03.flac")  # alone: its own gain
    qtbot.waitUntil(lambda: len(engine.levels) == 3, timeout=WAIT)
    assert engine.levels[2] == ("03.flac", TRACK["03.flac"])


def test_songs_out_of_their_albums_order_play_at_their_track_gains(gained, qtbot):
    p, engine, ids_ = gained()
    p.play_songs([ids_["03.flac"], ids_["01.flac"], ids_["Kindling.mp3"]], "Shuffled")
    qtbot.waitUntil(lambda: len(engine.levels) == 2, timeout=WAIT)
    engine.join()
    qtbot.waitUntil(lambda: len(engine.levels) == 3, timeout=WAIT)
    assert engine.levels == [("03.flac", TRACK["03.flac"]), ("01.flac", TRACK["01.flac"]),
                             ("Kindling.mp3", UNTAGGED)]  # fmt: skip


def test_track_off_and_the_pre_amp_are_the_settings(gained, qtbot):
    p, engine, ids_ = gained(settings.Playback(replaygain="track", replaygain_default=-12.0))
    p.play_songs([ids_["01.flac"], ids_["02.flac"]], "Glass Harbor")
    qtbot.waitUntil(lambda: len(engine.levels) == 2, timeout=WAIT)
    assert engine.levels == [("01.flac", TRACK["01.flac"]), ("02.flac", TRACK["02.flac"])]
    p.play_songs([ids_["Kindling.mp3"]], "Embers")
    qtbot.waitUntil(lambda: len(engine.levels) == 3, timeout=WAIT)
    assert engine.levels[2] == ("Kindling.mp3", 0.2512)  # -12 dB
    off, engine, _ = gained(settings.Playback(replaygain="off"))
    off.play_songs([ids_["01.flac"], ids_["Kindling.mp3"]], "")
    qtbot.waitUntil(lambda: len(engine.levels) == 2, timeout=WAIT)
    assert engine.levels == [("01.flac", 1.0), ("Kindling.mp3", 1.0)]


def test_a_song_repeated_keeps_its_gain_and_a_file_outside_the_index_has_the_pre_amp(gained, qtbot):
    p, engine, ids_ = gained()
    p.queue.set_repeat(ONE)
    p.play_songs([ids_["01.flac"], ids_["02.flac"]], "Glass Harbor")
    qtbot.waitUntil(lambda: len(engine.levels) == 2, timeout=WAIT)
    one = TRACK["01.flac"]  # repeat One plays a song, not its album, in order
    assert engine.levels == [("01.flac", one), ("01.flac", one)]
    p.play_file("/elsewhere/a.flac")
    qtbot.waitUntil(lambda: engine.levels[-1][0] == "a.flac", timeout=WAIT)
    assert engine.levels[-1] == ("a.flac", UNTAGGED)


def test_the_device_chosen_in_settings_is_told_to_the_engine(gained, qtbot):
    p, engine, ids_ = gained(settings.Playback(device="alsa_output.usb-DAC"))
    p.play_songs([ids_["01.flac"]], "")
    qtbot.waitUntil(lambda: engine.device == "alsa_output.usb-DAC", timeout=WAIT)


def _album_id(p, title):
    return p._read().execute("SELECT id FROM album WHERE title = ?", (title,)).fetchone()[0]


def test_a_song_outside_the_queue_has_nothing_told_to_follow_it(made, tmp_path, qtbot):
    p, engine, _ = made
    p.play("elsewhere.flac")  # not in the index: played as a file
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    assert engine.told == []


def test_a_join_heard_moves_the_queue_the_bar_and_the_playing_row_not_a_new_play(
    made, index, qtbot
):
    p, engine, songs = made
    now = []
    p.nowPlaying.connect(now.append)
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    engine.moved.emit(199.5)
    qtbot.waitUntil(lambda: engine.told == ["02.flac"], timeout=WAIT)
    engine.join()
    assert p.property("path") == "LD/GH/02.flac" and p.property("title") == "Glass Harbor"
    assert p.property("playing") and p.property("position") == 0 and p.property("length") == 42
    assert [e.song for e in p.queue.played] == ids(index, "LD/GH/01.flac")
    assert now == ["LD/GH/01.flac", "LD/GH/02.flac"] and engine.played() == ["01.flac"]
    qtbot.waitUntil(lambda: engine.told == ["02.flac", "03.flac"], timeout=WAIT)
    engine.ended.emit(engine.ticket)  # what was joined ends as any song does
    wait_playing(qtbot, p, engine, 2)
    assert engine.played() == ["01.flac", "03.flac"]


def test_a_join_the_queue_changed_after_gives_way_to_what_the_queue_says(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: engine.told == ["02.flac"], timeout=WAIT)
    told_first = engine.follower
    p.playNext(songs, 3)  # too late: the device has the first song told already
    qtbot.waitUntil(lambda: engine.told[-1] == "Kindling.mp3", timeout=WAIT)
    engine.joined.emit(told_first[0], told_first[1], 42.0)
    wait_playing(qtbot, p, engine, 2)
    assert engine.played() == ["01.flac", "Kindling.mp3"]
    assert p.property("path") == "MO/Kindling.mp3"
    engine.joined.emit(told_first[0], told_first[1], 42.0)  # again, and one never told: nothing
    engine.joined.emit(999, "elsewhere.flac", 1.0)
    qtbot.wait(50)  # the one fixed wait: nothing moves
    assert p.property("path") == "MO/Kindling.mp3" and len(engine.played()) == 2


def test_a_join_with_nothing_left_in_the_queue_stops(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 2)
    wait_playing(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: engine.told == ["Kindling.mp3"], timeout=WAIT)
    told = engine.follower
    p.removeRow(1)  # Kindling out of the queue, once the device had it
    qtbot.waitUntil(lambda: engine.told[-1] == "", timeout=WAIT)
    engine.joined.emit(told[0], told[1], 42.0)
    qtbot.waitUntil(lambda: p.last == "ended" and ("stop",) in engine.asked, timeout=WAIT)
    assert p.property("path") == ""


def test_a_next_song_failing_as_the_device_reaches_it_is_shown_with_why(made, qtbot):
    p, engine, songs = made
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    qtbot.waitUntil(lambda: engine.told == ["02.flac"], timeout=WAIT)
    engine.failed.emit(engine.follower[0], "nothing in 02.flac decodes")
    qtbot.waitUntil(lambda: p.last == "failed", timeout=WAIT)
    assert p.property("path") == "LD/GH/02.flac" and p.property("playing") is False
    assert p.property("error") == "nothing in 02.flac decodes"


def test_a_seek_shows_the_place_at_once_and_holds_it_until_the_engine_is_there(made, qtbot):
    p, engine, songs = made
    p.seekTo(0.5)  # nothing to seek: nothing moves
    p.cue([songs.queue_from(0)[0][0]], "Songs")
    p.seek(10.0)  # a cued song doesn't move
    assert engine.seeks() == [] and p.property("seekable") is False
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    assert p.property("seekable") is True
    engine.holding = True
    p.seek(10.0)
    assert p.property("position") == 10.0 and p.property("positionText") == "0:10"
    engine.moved.emit(1.0)  # from before the seek was done: passed over
    qtbot.waitUntil(lambda: engine.seeks() == [10.0], timeout=WAIT)
    assert p.property("position") == 10.0
    engine.sought.emit(engine.ticket)
    engine.moved.emit(10.1)
    qtbot.waitUntil(lambda: p.property("position") == 10.1, timeout=WAIT)
    engine.holding = False
    p.seekAhead()
    p.seekBack()
    p.seekBack()
    p.seekBack()
    p.seekBack()  # not before the start
    p.seekTo(0.5)
    p.seekTo(3.0)  # not past the end
    qtbot.waitUntil(lambda: len(engine.seeks()) == 8, timeout=WAIT)
    assert engine.seeks() == [10.0, 15.1, 10.1, 5.1, 0.1, 0.0, 21.0, 42.0]


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
    engine.ended.emit(engine.ticket)  # repeat One: the same song again
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
    engine.failed.emit(engine.ticket, "nothing in 01.flac decodes")
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


def find_all(shell, name):
    found = []

    def walk(item):
        if item.objectName() == name:
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    return found


def type_of(item):
    return item.metaObject().className() if item is not None else ""


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
def test_a_root_gone_while_a_song_plays_greys_next_and_up_next_says_why(
    shell, tmp_path, qtbot, qtlog
):
    p, engine, lib = shell.player, shell.engine_, shell.library
    p.go({"queue": "Glass Harbor"})
    qtbot.waitExposed(shell.window)
    click(shell, find(shell, "playPause"))
    qtbot.waitUntil(lambda: p.property("playing") and engine.told == ["02.flac"], timeout=WAIT)
    nxt = find(shell, "next")
    assert nxt.property("active") is True and nxt.property("note") == ""
    shutil.rmtree(tmp_path / "Music")  # its drive unplugged
    with qtbot.waitSignal(lib.reachChanged, timeout=WAIT):
        lib.retry()
    why = f"Playing waits until {os.path.join('~', 'Music')} is back"
    qtbot.waitUntil(lambda: engine.told == ["02.flac", ""], timeout=WAIT)
    assert nxt.property("active") is False and nxt.property("note") == why
    click(shell, nxt)
    assert p.property("title") == "Tidewater" and p.property("playing")
    click(shell, find(shell, "queueButton"))
    qtbot.waitUntil(lambda: find(shell, "upNext").isVisible(), timeout=WAIT)
    assert find(shell, "upNextLine").property("text") == why
    shell.window.grabWindow()
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []


@pytest.mark.slow
def test_the_seek_bar_seeks_where_it_is_clicked_and_dragged(shell, qtbot):
    p, engine = shell.player, shell.engine_
    p.go({"queue": "Glass Harbor"})
    qtbot.waitExposed(shell.window)
    bar = find(shell, "seekBar")
    assert bar.property("enabled") is False  # cued: nothing to seek in
    click(shell, find(shell, "playPause"))
    qtbot.waitUntil(lambda: bar.property("enabled"), timeout=WAIT)
    width = bar.width()

    def at(fraction):
        return bar.mapToScene(QPointF(fraction * width, bar.height() / 2)).toPoint()

    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at(0.25))
    qtbot.waitUntil(lambda: len(engine.seeks()) >= 1, timeout=WAIT)
    assert engine.seeks()[-1] == pytest.approx(0.25 * 42, abs=1)
    QTest.mousePress(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at(0.3))
    for f in (0.4, 0.5, 0.6, 0.75):
        QTest.mouseMove(shell.window, at(f))
    QTest.mouseRelease(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at(0.75))
    qtbot.waitUntil(lambda: engine.seeks()[-1] == pytest.approx(0.75 * 42, abs=1), timeout=WAIT)
    assert p.property("progress") == pytest.approx(0.75, abs=0.03)
    assert shell.window.activeFocusItem() is not bar  # it never takes the focus


@pytest.mark.slow
def test_left_and_right_seek_five_seconds_unless_a_list_or_box_uses_them(shell, qtbot):
    p, engine = shell.player, shell.engine_
    p.go({"queue": "Glass Harbor"})
    shell.library.show("songs")
    qtbot.waitExposed(shell.window)
    click(shell, find(shell, "playPause"))
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    QTest.keyClick(shell.window, Qt.Key.Key_Right)
    QTest.keyClick(shell.window, Qt.Key.Key_Right)
    QTest.keyClick(shell.window, Qt.Key.Key_Left)
    qtbot.waitUntil(lambda: engine.seeks() == [5.0, 10.0, 5.0], timeout=WAIT)
    QTest.keyClick(shell.window, Qt.Key.Key_Slash)  # the search box, typed in
    qtbot.waitUntil(lambda: "TextField" in type_of(shell.window.activeFocusItem()), timeout=WAIT)
    QTest.keyClick(shell.window, Qt.Key.Key_Left)
    QTest.keyClick(shell.window, Qt.Key.Key_Escape)
    shell.library.show("folders")  # a grid that moves its selection with them
    qtbot.waitUntil(lambda: bool(find_all(shell, "foldersView")), timeout=WAIT)
    find_all(shell, "foldersView")[0].forceActiveFocus()
    QTest.keyClick(shell.window, Qt.Key.Key_Right)
    volume = find(shell, "volume")
    volume.forceActiveFocus()
    QTest.keyClick(shell.window, Qt.Key.Key_Left)  # the volume, down
    qtbot.waitUntil(lambda: p.property("volume") < 1.0, timeout=WAIT)
    assert engine.seeks() == [5.0, 10.0, 5.0]


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


# ---------- kept across restarts (R1.8, R7.2, R7.3) ----------


class Inline(Executor):
    """Runs each job as it is submitted, so what is kept is there when the call returns."""

    def submit(self, fn, /, *args, **kwargs):
        done = Future()
        done.set_result(fn(*args, **kwargs))
        return done


class Recording(nowplaying_core.Keeping):
    """Keeping that writes nothing: each state it would write, with why, in `written`, and each
    settings change in `fields`."""

    def __init__(self, clock):
        record = self.fields = []
        super().__init__(nowplaying_core.Places(None, ""), lambda: None, clock,
                         set_playback=lambda **f: record.append(f), executor=Inline())  # fmt: skip
        self.written, self.why = [], ""

    def changed(self, state, why):
        self.why = why
        return super().changed(state, why)

    def _write(self, state):
        self.written.append((self.why, state))


def test_a_restored_queue_is_cued_at_its_place_and_play_goes_on_from_there(made, index, qtbot):
    p, engine, _ = made
    songs = ids(index, "LD/GH/01.flac", "LD/GH/02.flac", "MO/Kindling.mp3")
    p.restore(nowplaying_core.State(((songs[0], False), (songs[1], False), (songs[2], True)),
                                    (0, 1, 2), 1, 30.0, "Glass Harbor"))  # fmt: skip
    assert p.property("path") == "LD/GH/02.flac" and p.property("playing") is False
    assert p.property("positionText") == "0:30" and p.property("progress") == 0.3
    assert engine.played() == [] and p.queue.source == "Glass Harbor"
    assert [e.added for e in p.queue.upcoming] == [True]
    p.toggle()
    wait_playing(qtbot, p, engine, 1)
    assert engine.at == 30.0 and p.property("position") == 30.0  # from its place, not its start
    p.next()
    wait_playing(qtbot, p, engine, 2)
    assert engine.at == 0.0  # the next song from its start


def test_a_restored_queue_played_out_or_empty_cues_nothing(made, index):
    p, engine, _ = made
    songs = ids(index, "LD/GH/01.flac")
    p.restore(nowplaying_core.State(((songs[0], False),), (0,), 1, 0.0, "Glass Harbor"))
    assert p.property("path") == "" and p.queue.current is None and len(p.queue) == 1
    p.restore(nowplaying_core.State())
    assert p.property("path") == "" and len(p.queue) == 0 and engine.played() == []


def test_shuffle_and_repeat_start_as_the_settings_have_them_and_changes_are_kept(index, qtbot):
    playback = settings.Playback(shuffle=True, repeat=ALL)
    p = bridges.Player("/m", FakeEngine(), read=index.read, playback=playback)
    assert p.property("shuffle") is True and p.property("repeat") == ALL
    kept = Recording(FakeClock())
    p.keep(kept)
    p.shuffleAlbum(1)  # already on: nothing to keep
    p.toggleShuffle()
    p.cycleRepeat()
    assert kept.fields == [{"shuffle": False}, {"repeat": ONE}]
    p.close()


def test_what_plays_is_kept_when_the_queue_changes_on_pause_once_a_minute_and_at_close(
    made, index, qtbot
):
    p, engine, songs = made
    clock = FakeClock()
    kept = Recording(clock)
    p.keep(kept)
    assert kept.written == []  # what it holds at start is kept already
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    assert [w for w, _ in kept.written] == ["queue"]
    p.playNext(songs, 3)  # the queue changed
    assert [w for w, _ in kept.written] == ["queue", "queue"]
    engine.moved.emit(20.0)
    qtbot.waitUntil(lambda: p.property("position") == 20.0, timeout=WAIT)
    clock.advance(seconds=59)
    engine.moved.emit(59.0)
    qtbot.waitUntil(lambda: p.property("position") == 59.0, timeout=WAIT)
    assert len(kept.written) == 2  # not a minute yet
    clock.advance(seconds=1)
    engine.moved.emit(60.0)
    qtbot.waitUntil(lambda: len(kept.written) == 3, timeout=WAIT)
    assert kept.written[-1][0] == "tick" and kept.written[-1][1].position == 60.0
    p.next()  # the next song: the queue is the same, the place comes with the next write
    wait_playing(qtbot, p, engine, 2)
    assert len(kept.written) == 3
    engine.moved.emit(12.5)
    qtbot.waitUntil(lambda: p.property("position") == 12.5, timeout=WAIT)
    p.toggle()
    qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    assert kept.written[-1][0] == "pause"
    assert (kept.written[-1][1].cursor, kept.written[-1][1].position) == (1, 12.5)
    p.close()
    assert len(kept.written) == 4  # nothing changed since the pause
    assert p._keeping is None


def test_at_close_what_changed_since_the_last_write_is_kept(made, index, qtbot):
    p, engine, songs = made
    kept = Recording(FakeClock())
    p.keep(kept)
    p.playFrom(songs, 0)
    wait_playing(qtbot, p, engine, 1)
    engine.moved.emit(7.0)
    qtbot.waitUntil(lambda: p.property("position") == 7.0, timeout=WAIT)
    p.close()
    assert kept.written[-1][0] == "quit" and kept.written[-1][1].position == 7.0


def set_hashes(shell):
    """Audio hashes as a scan gives them (A2.3), in place of fill's paths."""
    shell.index.write(
        lambda c: c.execute("UPDATE song SET audio_hash = printf('%064d', id)")
    ).result()


def reload(tmp_path, root, songs=None):
    """The window over `root` again, as a new start opens it; with `songs`, the index filled
    first."""
    engines = []

    def playback():
        engines.append(FakeEngine())
        return engines[-1]

    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    root.mkdir(exist_ok=True)
    s = app.load(str(root), env, FakeClock(), lambda: ThreadPoolExecutor(1), playback)
    s.engine_ = engines[0]
    if songs is not None:
        fill(s.index, songs)
        set_hashes(s)
        s.library.reload()
    return s


@pytest.mark.slow
def test_a_root_opens_with_what_was_playing_when_it_closed_paused_at_its_place(tmp_path, qtbot):
    shell = reload(tmp_path, tmp_path / "Music", SONGS)
    p, engine = shell.player, shell.engine_
    p.toggleShuffle()
    p.cycleRepeat()
    p.go({"queue": "Glass Harbor", "added": ["Kindling"]})
    before = [(e.song, e.added) for e in p.queue.order]
    p.toggle()
    wait_playing(qtbot, p, engine, 1)
    engine.moved.emit(37.5)
    qtbot.waitUntil(lambda: p.property("position") == 37.5, timeout=WAIT)
    p.toggle()
    qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    playing = p.property("path")
    shell.close()  # its Player deleted with its window (A1.3)
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    shared = settings.load(settings.shared_path(env), str(tmp_path))
    assert (shared.playback.shuffle, shared.playback.repeat) == (True, ALL)
    path = tmp_path / "Music" / ".musikata" / shared.computer_id / "now-playing.json"
    assert json.loads(path.read_text())["position"] == 37.5
    again = reload(tmp_path, tmp_path / "Music")
    try:
        q = again.player
        assert [(e.song, e.added) for e in q.queue.order] == before and q.queue.shuffle
        assert q.queue.repeat == ALL and any(added for _, added in before)
        assert q.property("path") == playing and q.property("position") == 37.5
        assert q.property("playing") is False and again.engine_.played() == []
    finally:
        again.close()


@pytest.mark.slow
def test_a_song_moved_is_found_by_its_hash_and_one_gone_leaves_the_queue(tmp_path, qtbot):
    shell = reload(tmp_path, tmp_path / "Music", SONGS)
    p = shell.player
    p.go({"queue": "Glass Harbor", "at": 1})
    p.queue.add(ids(shell.index, "MO/Kindling.mp3"))
    p._queue_changed()
    shell.close()
    index = db.Index(shell.index.path)
    index.write(lambda c: c.execute("UPDATE song SET path = 'LD/GH/Two.flac' WHERE path = ?",
                                    ("LD/GH/02.flac",))).result()  # fmt: skip
    index.write(lambda c: c.execute("DELETE FROM song WHERE path = 'LD/GH/03.flac'")).result()
    index.close()
    again = reload(tmp_path, tmp_path / "Music")
    try:
        q = again.player
        found = dict(again.index.read().execute("SELECT id, path FROM song"))
        assert [found[e.song] for e in q.queue.order] == [
            "LD/GH/01.flac", "LD/GH/Two.flac", "MO/Kindling.mp3"
        ]  # fmt: skip
        assert q.property("path") == "LD/GH/Two.flac"
    finally:
        again.close()


@pytest.mark.slow
def test_a_kept_file_broken_by_a_sync_starts_an_empty_queue_and_says_so(tmp_path, caplog):
    shell = reload(tmp_path, tmp_path / "Music", SONGS)
    shell.player.go({"queue": "Glass Harbor"})
    shell.close()
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    cid = settings.load(settings.shared_path(env), str(tmp_path)).computer_id
    path = tmp_path / "Music" / ".musikata" / cid / "now-playing.json"
    path.write_text(path.read_text()[:40])
    with caplog.at_level(logging.WARNING):
        again = reload(tmp_path, tmp_path / "Music")
    try:
        assert len(again.player.queue) == 0 and again.player.property("path") == ""
        assert "the queue starts empty" in caplog.text
    finally:
        again.close()
