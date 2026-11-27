"""The system's media controls (R7.8, A4.5; src/musikata/media/): what the system is told of the
song playing and what its commands do (controls.py, plain functions), `MediaControls` following the
Player bridge and obeying a backend's commands, and the Windows and macOS backends mapping both onto
their platform's API, faked here (smtc.py, nowplaying_mac.py). MPRIS on a real bus is
tests/test_app_mpris.py's; the platforms' own overlays are tier 3's.

Why: the system's controls are a second way to play, pause and seek; a command that does the wrong
thing when nothing plays, a track id that doesn't change with the song, a seek the desktop isn't
told of, or a platform that won't start its controls and takes playback down with it, is only
seen on that platform's desktop."""

import logging
import os
import random
import weakref
from datetime import timedelta
from enum import IntEnum
from types import SimpleNamespace

import pytest
from fakes import FakeClock, FakeEngine, fill
from PySide6.QtGui import QWindow

from musikata import bridges, media
from musikata.media import controls, mpris, nowplaying_mac, smtc
from musikata.media.controls import (
    NEXT,
    NO_TRACK,
    PAUSE,
    PAUSED,
    PLAY,
    PLAY_PAUSE,
    PLAYING,
    PREVIOUS,
    QUIT,
    RAISE,
    SEEK,
    SET_POSITION,
    STOP,
    STOPPED,
    VOLUME,
    Command,
    Now,
    Song,
    State,
)
from musikata_core import db

WAIT = 5_000
SONGS = [
    {"path": "LD/GH/01.flac", "title": "Tidewater", "artist": "Lumen Drift",
     "album": "Glass Harbor", "track": 1, "length": 200.0},
    {"path": "LD/GH/02.flac", "title": "Glass Harbor", "artist": "Lumen Drift",
     "album": "Glass Harbor", "track": 2, "length": 100.0},
]  # fmt: skip

PLAYING_NOW = Now("a.flac", "Tidewater", "Lumen Drift", "Glass Harbor", 200.0, "image://covers/T",
                  on=True, playing=True, queued=True, seekable=True, position=50.0)  # fmt: skip


# ---------- what the system is told (plain functions) ----------


def test_each_platform_has_its_backend_and_others_none():
    assert controls.backend_for("linux") == "mpris"
    assert controls.backend_for("win32") == "smtc"
    assert controls.backend_for("darwin") == "nowplaying_mac"
    assert controls.backend_for("freebsd14") is None
    assert media.opener_for("linux") is mpris.open_session
    assert media.opener_for("sunos5") is None


def test_the_status_is_playing_paused_for_a_song_paused_or_cued_and_stopped_for_none():
    assert controls.status_of(PLAYING_NOW) == PLAYING
    paused = Now("a.flac", on=True, playing=False)
    cued = Now("a.flac")  # shown, waiting for play
    assert controls.status_of(paused) == controls.status_of(cued) == PAUSED
    assert controls.status_of(Now()) == STOPPED


def test_the_buttons_that_do_something_follow_the_song_the_queue_and_the_seek_bar():
    assert controls.state_of(PLAYING_NOW) == State(PLAYING, True, True, True, True, True, 1.0)
    alone = Now("x.flac", on=True, playing=True, volume=0.5)  # outside the queue, length unknown
    assert controls.state_of(alone) == State(PLAYING, True, True, False, False, False, 0.5)
    assert controls.state_of(Now()) == State()


def test_a_covers_thumbnail_is_named_by_its_address_and_a_mosaic_has_none():
    assert controls.thumb_of("image://covers/3fa9") == "3fa9"
    assert controls.thumb_of("image://covers/mosaic/a+b") == ""
    assert controls.thumb_of("") == ""


def test_the_song_shown_carries_its_track_words_length_and_cover():
    song = controls.song_of(PLAYING_NOW, "/t/1", "file:///c/T-256.jpg")
    assert song == Song("/t/1", "Tidewater", "Lumen Drift", "Glass Harbor", 200.0,
                        "file:///c/T-256.jpg")  # fmt: skip
    assert controls.song_of(Now(), "/t/1") is None


def test_mpris_metadata_has_each_key_the_song_has_and_lengths_in_microseconds():
    song = Song("/t/7", "Tidewater", "Lumen Drift", "Glass Harbor", 200.5, "file:///c/T.jpg")
    assert controls.metadata(song) == {
        "mpris:trackid": "/t/7", "xesam:title": "Tidewater", "mpris:length": 200_500_000,
        "mpris:artUrl": "file:///c/T.jpg", "xesam:artist": ["Lumen Drift"],
        "xesam:album": "Glass Harbor",
    }  # fmt: skip
    assert controls.metadata(Song("/t/8", "b")) == {"mpris:trackid": "/t/8", "xesam:title": "b"}
    assert controls.metadata(None) == {"mpris:trackid": NO_TRACK}
    assert controls.microseconds(0.0000015) == 2


def test_the_player_properties_follow_the_state_and_only_those_that_changed_are_sent():
    before = controls.player_properties(State())
    after = controls.player_properties(State(PLAYING, True, True, False, False, True, 0.8))
    assert after["PlaybackStatus"] == PLAYING and after["Volume"] == 0.8
    assert controls.changed(before, after) == {
        "PlaybackStatus": PLAYING, "CanPlay": True, "CanPause": True, "CanSeek": True,
        "Volume": 0.8,
    }  # fmt: skip
    assert controls.changed(after, after) == {}
    assert controls.changed({}, {"CanPlay": False}) == {"CanPlay": False}


@pytest.mark.parametrize(
    ("command", "now", "does"),
    [
        (Command(PLAY), Now("a.flac"), [("toggle", None)]),  # a cued song starts
        (Command(PLAY), Now("a.flac", on=True), [("toggle", None)]),  # a paused one resumes
        (Command(PLAY), PLAYING_NOW, []),  # playing already
        (Command(PLAY), Now(), []),  # nothing to play
        (Command(PAUSE), PLAYING_NOW, [("toggle", None)]),
        (Command(PAUSE), Now("a.flac", on=True), []),  # paused already
        (Command(PLAY_PAUSE), Now("a.flac"), [("toggle", None)]),
        (Command(PLAY_PAUSE), Now(), []),
        (Command(STOP), PLAYING_NOW, [("stop", None)]),
        (Command(STOP), Now("a.flac"), []),  # cued: nothing to stop
        (Command(NEXT), PLAYING_NOW, [("next", None)]),
        (Command(NEXT), Now("x.flac", on=True, playing=True), []),  # outside the queue
        (Command(PREVIOUS), PLAYING_NOW, [("previous", None)]),
        (Command(SEEK, 10.0), PLAYING_NOW, [("seek", 60.0)]),
        (Command(SEEK, -80.0), PLAYING_NOW, [("seek", 0.0)]),  # to its start, not before
        (Command(SEEK, 151.0), PLAYING_NOW, [("next", None)]),  # past its end: the next
        (Command(SEEK, 151.0), Now("x", length=10, on=True, seekable=True), []),  # no next
        (Command(SEEK, 5.0), Now("a.flac"), []),  # a cued song doesn't move
        (Command(SET_POSITION, 12.5, "/t/1"), PLAYING_NOW, [("seek", 12.5)]),
        (Command(SET_POSITION, 12.5, "/t/0"), PLAYING_NOW, []),  # meant for another song
        (Command(SET_POSITION, 201.0, "/t/1"), PLAYING_NOW, []),  # past its end
        (Command(SET_POSITION, -1.0, "/t/1"), PLAYING_NOW, []),
        (Command(VOLUME, 0.25), Now(), [("setVolume", 0.25)]),
        (Command(VOLUME, 3.0), Now(), [("setVolume", 1.0)]),
        (Command(RAISE), Now(), [("raise", None)]),
        (Command(QUIT), Now(), [("quit", None)]),
        (Command("record"), PLAYING_NOW, []),
    ],
)
def test_each_command_does_what_it_says_when_it_can(command, now, does):
    assert controls.actions(command, now, "/t/1") == does


def test_each_song_shown_is_a_new_track_and_none_is_no_track():
    w = controls.Watch()
    assert w.look(Now(), 0.0) == controls.Seen(NO_TRACK)
    first = w.look(Now("a.flac", on=True, playing=True), 1.0)
    assert first == controls.Seen(controls.TRACKS + "1", True)
    assert w.look(Now("a.flac", on=True, playing=True, position=0.1), 1.1).new is False
    assert w.look(Now("b.flac"), 2.0) == controls.Seen(controls.TRACKS + "2", True)
    assert w.look(Now("a.flac"), 3.0).track == controls.TRACKS + "3"  # played again: a new one
    assert w.look(Now(), 4.0) == controls.Seen(NO_TRACK, True)
    assert w.look(Now(), 5.0) == controls.Seen(NO_TRACK)


def test_a_position_that_isnt_where_playing_on_would_put_it_is_a_seek():
    w = controls.Watch()
    playing = dict(path="a.flac", on=True, playing=True)
    w.look(Now(**playing, position=10.0), 100.0)
    assert w.look(Now(**playing, position=10.5), 100.5).seeked is None  # playing on
    assert w.look(Now(**playing, position=11.4), 101.0).seeked is None  # a little late: not one
    assert w.look(Now(**playing, position=60.0), 101.1).seeked == 60.0  # sought ahead
    assert w.look(Now(**playing, position=0.0), 101.2).seeked == 0.0  # Previous started it again
    paused = dict(path="a.flac", on=True, playing=False)
    w.look(Now(**paused, position=0.1), 101.3)
    assert w.look(Now(**paused, position=0.1), 500.0).seeked is None  # paused: it stays
    assert w.look(Now(**paused, position=30.0), 501.0).seeked == 30.0  # sought while paused


# ---------- MediaControls over the Player bridge ----------


class FakeBackend:
    """A backend that keeps what it was told, in order; `send` and `position` are what it was
    given."""

    def __init__(self, send, position, window):
        self.send, self.position, self.window = send, position, window
        self.told = []
        self.closed = False

    def now_playing(self, song):
        self.told.append(("song", song))

    def state(self, state, position):
        self.told.append(("state", state.status))

    def seeked(self, position):
        self.told.append(("seeked", round(position, 3)))

    def close(self):
        self.closed = True

    def songs(self):
        return [s for kind, s in self.told if kind == "song"]

    def states(self):
        return [s for kind, s in self.told if kind == "state"]


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, SONGS)
    yield i
    i.close()


@pytest.fixture
def made(tmp_path, index, qapp):
    """A player over the index with a fake engine, and its media controls with a fake backend and
    a cover finder that finds every cover in tmp_path/cache: (player, engine, controls,
    backend, left), `left` counting MPRIS's Quit."""
    engine = FakeEngine()
    p = bridges.Player(str(tmp_path), engine, read=index.read, rng=random.Random(5))
    backends = []

    def opener(send, position, window):
        backends.append(FakeBackend(send, position, window))
        return backends[-1]

    def art(thumb):
        return str(tmp_path / "cache" / f"{thumb}-256.jpg")

    left = []
    window = QWindow()
    clock = FakeClock()
    mc = media.MediaControls(p, opener, art, window, lambda: left.append(1), clock)
    mc.clock = clock
    yield p, engine, mc, backends[0], left
    mc.close()
    p.close()


def song_ids(index):
    return [r[0] for r in index.read().execute("SELECT id FROM song ORDER BY path")]


def test_nothing_is_shown_until_a_song_is_and_then_its_words_and_playing(made, index, qtbot):
    p, engine, mc, backend, _ = made
    assert backend.told == [("state", STOPPED)]
    p.play_songs(song_ids(index), "Glass Harbor")
    qtbot.waitUntil(lambda: PLAYING in backend.states(), timeout=WAIT)
    song = backend.songs()[1]
    assert (song.track, song.title, song.artist, song.album) == (
        controls.TRACKS + "1", "Tidewater", "Lumen Drift", "Glass Harbor"
    )  # fmt: skip
    assert song.length in (200.0, 42.0)  # the index's, then the engine's (the fake's 0:42)
    assert backend.songs()[-1].length == 42.0


def test_the_cover_is_found_off_the_gui_thread_and_the_song_shown_again_with_it(
    made, index, tmp_path, qtbot
):
    p, engine, mc, backend, _ = made
    index.write(lambda c: c.execute("UPDATE album SET thumb = 'T'")).result()
    p.play_songs(song_ids(index), "Glass Harbor")
    qtbot.waitUntil(lambda: bool(backend.songs() and backend.songs()[-1].art), timeout=WAIT)
    assert backend.songs()[-1].art == (tmp_path / "cache" / "T-256.jpg").as_uri()


def test_a_cover_that_cant_be_found_leaves_the_song_without_one(tmp_path, index, qtbot, caplog):
    def art(thumb):
        raise OSError("the cache can't be read")

    told = []
    p = bridges.Player(str(tmp_path), FakeEngine(), read=index.read)

    def opener(send, position, window):
        told.append(FakeBackend(send, position, window))
        return told[0]

    mc = media.MediaControls(p, opener, art)
    index.write(lambda c: c.execute("UPDATE album SET thumb = 'T'")).result()
    with qtbot.waitSignal(mc._art_found, timeout=WAIT):
        p.play_songs(song_ids(index), "")
    assert all(s is None or s.art == "" for s in told[0].songs())
    assert "the cache can't be read" in caplog.text
    mc.close()
    p.close()
    # the failure asked of the future, not raised again: nothing holds the controls in a cycle
    gone = weakref.ref(mc)
    told.clear()  # the backend, which the controls let go of at close
    del mc
    assert gone() is None


def test_pause_and_a_seek_are_told_and_a_restart_is_a_seek(made, index, qtbot):
    p, engine, mc, backend, _ = made
    p.play_songs(song_ids(index), "Glass Harbor")
    qtbot.waitUntil(lambda: PLAYING in backend.states(), timeout=WAIT)
    p.toggle()
    qtbot.waitUntil(lambda: backend.states()[-1] == PAUSED, timeout=WAIT)
    p.seek(30.0)
    assert backend.told[-1] == ("seeked", 30.0)
    mc.clock.advance(seconds=10)
    p.previous()  # past its first seconds: it starts again
    qtbot.waitUntil(lambda: backend.told[-1] == ("seeked", 0.0), timeout=WAIT)


def test_the_systems_commands_work_the_player_the_window_and_quit(made, index, qtbot):
    p, engine, mc, backend, left = made
    p.cue(song_ids(index), "Glass Harbor")
    backend.send(Command(PLAY))
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    backend.send(Command(PAUSE))
    qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    backend.send(Command(NEXT))
    assert p.property("title") == "Glass Harbor"
    backend.send(Command(PLAY_PAUSE))
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    backend.send(Command(SEEK, 12.0))
    backend.send(Command(SET_POSITION, 3.0, controls.TRACKS + "2"))
    backend.send(Command(SET_POSITION, 9.0, controls.TRACKS + "1"))  # the song before: not this
    qtbot.waitUntil(lambda: engine.seeks() == [12.0, 3.0], timeout=WAIT)
    backend.send(Command(VOLUME, 0.5))
    assert p.property("volume") == 0.5
    backend.send(Command(RAISE))
    assert mc._window.isVisible()
    backend.send(Command(QUIT))
    assert left == [1]
    backend.send(Command(STOP))
    qtbot.waitUntil(lambda: ("stop",) in engine.asked and not p.property("playing"), timeout=WAIT)
    assert backend.window is mc._window


def test_a_command_sent_from_another_thread_is_obeyed_on_the_gui_thread(made, index, qtbot):
    import threading

    p, engine, mc, backend, _ = made
    p.cue(song_ids(index), "Glass Harbor")
    sender = threading.Thread(target=backend.send, args=(Command(PLAY),))
    sender.start()
    sender.join()
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)


def test_closed_it_tells_the_backend_nothing_more(made, index, qtbot):
    p, engine, mc, backend, _ = made
    mc.close()
    assert backend.closed and mc.backend is None
    told = list(backend.told)
    p.play_songs(song_ids(index), "")
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    assert backend.told == told
    mc.close()  # again: nothing


def test_a_backend_that_cant_start_leaves_playback_as_it_was_and_says_so_once(
    tmp_path, index, qtbot, caplog
):
    def opener(send, position, window):
        raise RuntimeError("no session bus (not connected)")

    p = bridges.Player(str(tmp_path), FakeEngine(), read=index.read)
    with caplog.at_level(logging.INFO):
        mc = media.MediaControls(p, opener)
        p.play_songs(song_ids(index), "")
        qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
        p.toggle()
        qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
        mc.obey(Command(PLAY))  # the commands still work, though no backend sends them
        qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    said = [r.getMessage() for r in caplog.records if r.name == "musikata.media"]
    assert said == [
        "the system's media controls didn't start (RuntimeError: no session bus (not "
        "connected)); MusiKata plays without them"
    ]
    assert mc.backend is None and p.property("playing")
    mc.close()
    p.close()


class Breaking:
    """A backend that started, then raises on what it is told (as Wine's SMTC did at start)."""

    def __init__(self):
        self.closed = False

    def now_playing(self, song):
        raise OSError(-2147221164, "Class not registered")

    def state(self, state, position):
        raise OSError(-2147221164, "Class not registered")

    def seeked(self, position):
        raise OSError(-2147221164, "Class not registered")

    def close(self):
        self.closed = True


def test_a_backend_that_breaks_after_it_started_leaves_playback_and_says_so_once(
    tmp_path, index, qtbot, caplog
):
    """A4.5: a platform whose controls fail still plays: what the backend raises once it has
    started stops the controls, never the app."""
    backend = Breaking()
    p = bridges.Player(str(tmp_path), FakeEngine(), read=index.read)
    with caplog.at_level(logging.INFO):
        mc = media.MediaControls(p, lambda send, position, window: backend)
        p.play_songs(song_ids(index), "")
        qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
        p.toggle()
        qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    said = [r.getMessage() for r in caplog.records if r.name == "musikata.media"]
    assert said == [
        "the system's media controls stopped (OSError: [Errno -2147221164] Class not "
        "registered); MusiKata plays without them"
    ]
    assert mc.backend is None and backend.closed and p.property("paused")
    mc.close()
    p.close()


def test_a_platform_without_controls_plays_and_says_so(tmp_path, qapp, caplog):
    p = bridges.Player(str(tmp_path), FakeEngine())
    with caplog.at_level(logging.INFO):
        mc = media.MediaControls(p, media.opener_for("sunos5"))
    assert mc.backend is None
    assert "the system's media controls: there are none on this platform" in caplog.text
    mc.close()
    p.close()


# ---------- Windows: the System Media Transport Controls, faked ----------


class Button(IntEnum):
    PLAY = 0
    PAUSE = 1
    STOP = 2
    RECORD = 3
    NEXT = 6
    PREVIOUS = 7


class FakeSmtc:
    """SystemMediaTransportControls' members smtc.py uses: its flags, its display updater, its
    timeline as last updated, and the handlers added and removed."""

    def __init__(self):
        self.handlers = {}
        self.removed = []
        self.timeline = None
        self.updated = 0
        self.cleared = 0
        music = SimpleNamespace(title="", artist="", album_title="")
        self.display_updater = SimpleNamespace(
            music_properties=music, type=None, thumbnail=None,
            update=self._update, clear_all=self._clear,
        )  # fmt: skip

    def _update(self):
        self.updated += 1

    def _clear(self):
        self.cleared += 1

    def add_button_pressed(self, handler):
        self.handlers["button"] = handler
        return "button-token"

    def remove_button_pressed(self, token):
        self.removed.append(token)

    def add_playback_position_change_requested(self, handler):
        self.handlers["position"] = handler
        return "position-token"

    def remove_playback_position_change_requested(self, token):
        self.removed.append(token)

    def update_timeline_properties(self, timeline):
        self.timeline = timeline


WINDOWS_NAMES = smtc.Names(
    status=SimpleNamespace(PLAYING=3, PAUSED=4, STOPPED=2),
    kind=SimpleNamespace(MUSIC=1),
    timeline=SimpleNamespace,
    uri=lambda text: ("uri", text),
    stream=SimpleNamespace(create_from_uri=lambda uri: ("stream", uri)),
)


@pytest.fixture
def windows():
    sent = []
    fake = FakeSmtc()
    backend = smtc.Smtc(fake, WINDOWS_NAMES, sent.append, lambda: 12.0)
    return fake, backend, sent


def test_windows_controls_are_on_with_every_button_off_until_a_song_is_shown(windows):
    fake, backend, sent = windows
    assert fake.is_enabled is True
    assert not any(getattr(fake, f"is_{n}_enabled") for n in ("play", "pause", "next"))


def test_windows_shows_the_songs_words_cover_and_timeline(windows):
    fake, backend, sent = windows
    backend.state(State(PLAYING, True, True, True, False, True), 12.0)
    song = Song("/t/1", "Tidewater", "Lumen Drift", "Glass Harbor", 200.0, "file:///c/T-256.jpg")
    backend.now_playing(song)
    updater = fake.display_updater
    music = updater.music_properties
    assert (music.title, music.artist, music.album_title) == (
        "Tidewater", "Lumen Drift", "Glass Harbor"
    )  # fmt: skip
    assert updater.type == 1 and fake.updated == 1
    assert updater.thumbnail == ("stream", ("uri", "file:///c/T-256.jpg"))
    assert fake.playback_status == 3
    assert (fake.is_play_enabled, fake.is_pause_enabled, fake.is_stop_enabled) == (True,) * 3
    assert (fake.is_next_enabled, fake.is_previous_enabled) == (True, False)
    t = fake.timeline
    assert (t.start_time, t.end_time, t.position) == (
        timedelta(0), timedelta(seconds=200), timedelta(seconds=12)
    )  # fmt: skip
    assert t.max_seek_time == timedelta(seconds=200)
    backend.seeked(250.0)
    assert fake.timeline.position == timedelta(seconds=200)  # never past the end
    backend.state(State(STOPPED), 0.0)
    assert fake.playback_status == 2 and fake.is_stop_enabled is False
    assert fake.timeline.max_seek_time == timedelta(0)
    backend.now_playing(None)
    assert fake.cleared == 1 and fake.updated == 2


def test_windows_buttons_and_the_position_moved_are_commands(windows):
    fake, backend, sent = windows
    for button in Button:
        fake.handlers["button"](fake, SimpleNamespace(button=button))
    asked = SimpleNamespace(requested_playback_position=timedelta(seconds=42.5))
    fake.handlers["position"](fake, asked)
    backend.now_playing(Song("/t/3", "a"))
    fake.handlers["position"](fake, asked)
    assert sent == [Command(PLAY), Command(PAUSE), Command(STOP), Command(NEXT),
                    Command(PREVIOUS), Command(SET_POSITION, 42.5, ""),
                    Command(SET_POSITION, 42.5, "/t/3")]  # fmt: skip


def test_windows_controls_let_go_when_closed(windows):
    fake, backend, sent = windows
    backend.close()
    assert fake.removed == ["button-token", "position-token"]
    assert fake.is_enabled is False and fake.cleared == 1


class FakeSmtcWithoutSeek(FakeSmtc):
    """Controls without ISystemMediaTransportControls2 (Wine's): asking for the position moved
    fails as PyWinRT fails it."""

    def add_playback_position_change_requested(self, handler):
        raise AttributeError(
            "method 'add_PlaybackPositionChangeRequested' requires "
            "'Windows.Media.ISystemMediaTransportControls2'"
        )


class FakeWineSmtc(FakeSmtcWithoutSeek):
    """Wine's controls as the Windows build's start test met them: no seek, and the timeline's
    update refused too (ISystemMediaTransportControls2's), as an OSError."""

    def update_timeline_properties(self, timeline):
        raise OSError(-2147221164, "Class not registered")


def test_windows_controls_whose_timeline_is_refused_keep_the_rest_and_never_raise(caplog):
    """CI's Windows start test: the app died at start when the timeline's update raised. The
    controls go on without a timeline, saying so once."""
    fake, sent = FakeWineSmtc(), []
    with caplog.at_level(logging.INFO):
        backend = smtc.Smtc(fake, WINDOWS_NAMES, sent.append, lambda: 12.0)
        backend.now_playing(Song("/t/1", "Tidewater", length=200.0))
        backend.state(State(PLAYING, True, True, True, False, True), 12.0)
        backend.seeked(30.0)
        backend.now_playing(Song("/t/2", "Glass Harbor", length=100.0))
    said = [r.getMessage() for r in caplog.records if r.name == "musikata.media.smtc"]
    assert len(said) == 2 and "seek" in said[0] and "timeline" in said[1]
    assert fake.is_enabled is True and fake.playback_status == 3
    fake.handlers["button"](fake, SimpleNamespace(button=Button.PAUSE))
    assert sent == [Command(PAUSE)]
    backend.close()


def test_windows_controls_without_seek_keep_the_rest_and_say_so_once(caplog):
    fake, sent = FakeSmtcWithoutSeek(), []
    with caplog.at_level(logging.INFO):
        backend = smtc.Smtc(fake, WINDOWS_NAMES, sent.append, lambda: 12.0)
        backend.now_playing(Song("/t/1", "Tidewater", length=200.0))
        backend.state(State(PLAYING, True, True, True, False, True), 12.0)
        backend.seeked(30.0)
    said = [r.getMessage() for r in caplog.records if r.name == "musikata.media.smtc"]
    assert len(said) == 1 and "seek" in said[0] and "ISystemMediaTransportControls2" in said[0]
    assert fake.is_enabled is True and fake.playback_status == 3
    t = fake.timeline
    assert (t.end_time, t.position) == (timedelta(seconds=200), timedelta(seconds=30))
    assert t.max_seek_time == timedelta(0)  # the timeline isn't offered as seekable
    fake.handlers["button"](fake, SimpleNamespace(button=Button.PAUSE))
    assert sent == [Command(PAUSE)]
    backend.close()
    assert fake.removed == ["button-token"] and fake.is_enabled is False


# ---------- macOS: Now Playing, faked ----------


class FakeCommand:
    """An MPRemoteCommand: its handlers, whether it is enabled."""

    def __init__(self):
        self.handlers = []
        self.enabled = None

    def addTargetWithHandler_(self, handler):  # noqa: N802
        self.handlers.append(handler)
        return len(self.handlers)

    def removeTarget_(self, token):  # noqa: N802
        self.handlers[token - 1] = None

    def setEnabled_(self, on):  # noqa: N802
        self.enabled = on


class FakeCommandCenter:
    def __init__(self):
        self.commands = {name: FakeCommand() for name in nowplaying_mac.COMMANDS.values()}

    def __getattr__(self, name):
        if name in nowplaying_mac.COMMANDS.values():
            return lambda: self.commands[name]
        raise AttributeError(name)


class FakeInfoCenter:
    def __init__(self):
        self.info = "never set"
        self.state = None

    def setNowPlayingInfo_(self, info):  # noqa: N802
        self.info = info

    def setPlaybackState_(self, state):  # noqa: N802
        self.state = state


@pytest.fixture
def mac():
    sent, made = [], []

    def artwork(path):
        made.append(path)
        return ("artwork", path) if path.endswith(".jpg") else None

    names = nowplaying_mac.Names(
        "title", "artist", "albumTitle", "playbackDuration", "elapsed", "rate", "artwork",
        {PLAYING: 1, PAUSED: 2, STOPPED: 3}, 0, artwork,
    )  # fmt: skip
    center, commands = FakeInfoCenter(), FakeCommandCenter()
    backend = nowplaying_mac.NowPlayingMac(center, commands, names, sent.append, lambda: 7.0)
    return center, commands, backend, sent, made


def test_macos_shows_the_song_its_cover_and_where_it_is_moving_on_while_it_plays(mac):
    center, commands, backend, sent, made = mac
    song = Song("/t/1", "Tidewater", "Lumen Drift", "Glass Harbor", 200.0, "file:///c/T%20256.jpg")
    backend.now_playing(song)
    assert center.info == {
        "title": "Tidewater", "artist": "Lumen Drift", "albumTitle": "Glass Harbor",
        "playbackDuration": 200.0, "elapsed": 7.0, "rate": 0.0,
        "artwork": ("artwork", "/c/T 256.jpg"),
    }  # fmt: skip
    backend.state(State(PLAYING, True, True, False, True, True), 9.0)
    assert center.state == 1 and center.info["elapsed"] == 9.0 and center.info["rate"] == 1.0
    enabled = {name: c.enabled for name, c in commands.commands.items()}
    assert enabled == {
        "playCommand": True, "pauseCommand": True, "togglePlayPauseCommand": True,
        "stopCommand": True, "nextTrackCommand": False, "previousTrackCommand": True,
        "changePlaybackPositionCommand": True,
    }  # fmt: skip
    backend.seeked(30.0)
    assert center.info["elapsed"] == 30.0
    assert made == ["/c/T 256.jpg"]  # made once, not at each change
    backend.now_playing(Song("/t/2", "b", art="file:///c/broken.png"))
    assert "artwork" not in center.info
    backend.now_playing(None)
    assert center.info is None


def test_macos_commands_and_the_position_moved_are_commands(mac):
    center, commands, backend, sent, made = mac
    backend.now_playing(Song("/t/4", "a"))
    for command in nowplaying_mac.COMMANDS.values():
        handler = commands.commands[command].handlers[0]
        event = SimpleNamespace(positionTime=lambda: 61.5)
        assert handler(event) == 0
    assert sent == [Command(n) for n in (PLAY, PAUSE, PLAY_PAUSE, STOP, NEXT, PREVIOUS)] + [
        Command(SET_POSITION, 61.5, "/t/4")
    ]


def test_macos_lets_go_of_the_commands_and_clears_now_playing_when_closed(mac):
    center, commands, backend, sent, made = mac
    backend.close()
    assert all(c.handlers == [None] for c in commands.commands.values())
    assert center.info is None and center.state == 3


def test_a_file_urls_path_is_the_file_it_names():
    assert nowplaying_mac.path_of("file:///Users/a/Library/Caches/T%2B1-256.jpg") == (
        "/Users/a/Library/Caches/T+1-256.jpg"
    )
    assert os.path.basename(nowplaying_mac.path_of("file:///c/x.png")) == "x.png"
