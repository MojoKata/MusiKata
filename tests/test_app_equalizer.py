"""The equalizer in the running app (the Player bridge, src/musikata/bridges.py; R19.1, R19.4,
R19.5): each song asked of the engine told its tone first, picked by its genres when Choose by
genre is on, told again when the equalizer changes while it plays, and what the Equalizer panel
will bind: on or off, the preset playing and why, choosing one, bands set, the headroom.

The engine is a stand-in that plays nothing (`FakeEngine`, tests/fakes.py) and keeps the tones it
was told; one test plays through the real engine into the null output, as test_app_player.py's do.

Why: what the equalizer plays is decided on the GUI thread and heard on the playback thread; a
song told no tone, or the old one after a change, plays the wrong sound with nothing on screen to
say so."""

import threading

import numpy as np
import pytest
from fakes import FakeClock, FakeEngine, fill

from musikata import bridges, player
from musikata_core import db, nowplaying, settings
from musikata_core.audio import presets

SONGS = [
    {"path": "a.flac", "title": "A", "genres": ("Ambient", "Classical")},
    {"path": "b.flac", "title": "B", "genres": ("Electronic",)},
    {"path": "c.flac", "title": "C", "genres": ()},
]
WAIT = 10_000


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, SONGS)
    yield i
    i.close()


def ids(index):
    return [r[0] for r in index.read().execute("SELECT id FROM song ORDER BY path")]


class Recorder:
    def __init__(self):
        self.calls, self.threads = [], []

    def __call__(self, **fields):
        self.calls.append(fields)
        self.threads.append(threading.current_thread().name)
        return True


@pytest.fixture
def make(tmp_path, index, qapp):
    """Players over the index with a fake engine, each closed after the test:
    make(**equalizer) gives (player, engine, kept), `kept` what the shared settings were told."""
    made = []

    def make_(**group):
        engine = FakeEngine()
        p = bridges.Player(
            str(tmp_path), engine, read=index.read, equalizer=settings.Equalizer(**group)
        )
        (tmp_path / "Music" / ".musikata").mkdir(parents=True, exist_ok=True)
        where = nowplaying.places(str(tmp_path / "Music"), str(tmp_path / "index"), "b2c4")
        kept = Recorder()
        p.keep(nowplaying.Keeping(where, index.read, FakeClock(), set_equalizer=kept))
        made.append(p)
        return p, engine, kept

    yield make_
    for p in made:
        p.close()


def tone_of(name):
    return presets.tone(presets.find(name, ()))


def started(p, engine, qtbot, songs):
    """`songs` played, once the engine has the first and was told the one to follow it."""
    p.play_songs(songs, "")
    qtbot.waitUntil(lambda: bool(engine.ticket and engine.follower[0]), timeout=WAIT)
    return engine.ticket, engine.follower[0]


def told(engine, qtbot, n):
    """The tones the engine was told, once it has `n` of them."""
    qtbot.waitUntil(lambda: len(engine.tones) >= n, timeout=WAIT)
    return list(engine.tones)


def test_each_song_is_told_its_tone_before_it_is_asked_for_none_while_off(make, index, qtbot):
    p, engine, _ = make()
    playing, following = started(p, engine, qtbot, ids(index))
    assert told(engine, qtbot, 2) == [(playing, None), (following, None)]  # off by default
    p2, engine2, _ = make(on=True, preset="Rock")
    playing, following = started(p2, engine2, qtbot, ids(index))
    assert told(engine2, qtbot, 2) == [(playing, tone_of("Rock")), (following, tone_of("Rock"))]
    assert p2.property("equalizerOn") and p2.property("equalizerPreset") == "Rock"
    assert p2.property("equalizerChosenBy") == "chosen" and p2.property("headroom") == 0.0


def test_by_genre_each_song_takes_its_first_genres_preset_else_the_one_chosen(make, index, qtbot):
    """R19.4: a's genres are Ambient then Classical; b's Electronic; c has none."""
    p, engine, _ = make(on=True, preset="Pop", by_genre=True)
    playing, following = started(p, engine, qtbot, ids(index))
    assert told(engine, qtbot, 2) == [
        (playing, tone_of("Classical")), (following, tone_of("Electronic"))
    ]  # fmt: skip
    assert (p.property("equalizerPreset"), p.property("equalizerChosenBy")) == (
        "Classical",
        "genre",
    )
    engine.join()
    qtbot.waitUntil(lambda: p.property("equalizerPreset") == "Electronic", timeout=WAIT)
    assert told(engine, qtbot, 3)[-1] == (engine.follower[0], tone_of("Pop"))  # c: the chosen


def test_a_preset_chosen_by_hand_while_by_genre_plays_for_this_song_alone(make, index, qtbot):
    p, engine, kept = make(on=True, preset="Pop", by_genre=True)
    playing, following = started(p, engine, qtbot, ids(index))
    told(engine, qtbot, 2)
    p.choosePreset("Rock")
    # this song plays it; the next keeps its genre's (Electronic)
    assert told(engine, qtbot, 3)[2:] == [(playing, tone_of("Rock"))]
    assert (p.property("equalizerPreset"), p.property("equalizerChosenBy")) == ("Rock", "song")
    engine.join()  # b: its genre's again
    qtbot.waitUntil(lambda: p.property("equalizerPreset") == "Electronic", timeout=WAIT)
    assert p.property("equalizerChosenBy") == "genre"
    assert told(engine, qtbot, 4)[-1] == (engine.follower[0], tone_of("Rock"))  # c: the chosen
    p.choosePreset("No such preset")
    assert p.property("equalizerPreset") == "Electronic"
    qtbot.waitUntil(lambda: kept.calls == [{"preset": "Rock"}], timeout=WAIT)


def test_switched_on_and_off_while_playing_the_engine_is_told_at_once_and_it_is_kept(
    make, index, qtbot
):
    p, engine, kept = make(preset="Jazz")
    playing, following = started(p, engine, qtbot, ids(index))
    told(engine, qtbot, 2)
    changes = []
    p.equalizerChanged.connect(lambda: changes.append(p.property("equalizerOn")))
    p.setEqualizerOn(True)
    assert told(engine, qtbot, 4)[2:] == [(playing, tone_of("Jazz")), (following, tone_of("Jazz"))]
    p.setEqualizerOn(True)  # no change: nothing told
    assert changes == [True]
    p.setEqualizerOn(False)
    assert told(engine, qtbot, 6)[4:] == [(playing, None), (following, None)]
    qtbot.waitUntil(lambda: kept.calls == [{"on": True}, {"on": False}], timeout=WAIT)
    assert all(t.startswith("now playing") for t in kept.threads)


def test_bands_set_are_heard_at_once_not_kept_and_the_headroom_follows(make, index, qtbot):
    """R19.1: "−2.7 dB more, to keep from clipping"."""
    p, engine, kept = make(on=True, preset="Flat")
    playing, _ = started(p, engine, qtbot, ids(index))
    told(engine, qtbot, 2)
    p.setBands(-5.3, [{"type": "bell", "freq": 1000, "gain": 8, "q": 1}])
    ticket, tone = told(engine, qtbot, 4)[2]  # the song playing, then the next (Flat too)
    assert ticket == playing and tone.bands[0].gain == 8 and tone.preamp == -5.3
    assert p.property("headroom") == pytest.approx(2.7)
    p.setBands(-2, [1.0] * 10)  # ten sliders: graphic
    assert len(told(engine, qtbot, 6)[4][1].bands) == 10
    assert p.property("headroom") == pytest.approx(0)
    p.setBands(0, ["nonsense"])  # not bands: nothing changes
    p.choosePreset("Flat")  # chosen again: as saved
    assert told(engine, qtbot, 8)[6:] == [(playing, tone_of("Flat"))] * 1 + [
        (engine.follower[0], tone_of("Flat"))
    ]
    qtbot.waitUntil(lambda: kept.calls == [{"preset": "Flat"}], timeout=WAIT)


def test_a_file_outside_the_index_plays_the_preset_chosen(make, tmp_path, qtbot):
    p, engine, _ = make(on=True, preset="Loudness", by_genre=True)
    p.play_file(str(tmp_path / "loose.flac"))
    assert told(engine, qtbot, 1) == [(1, tone_of("Loudness"))]


# ---------- through the real engine ----------


@pytest.fixture
def null_output(qapp):
    from PySide6.QtMultimedia import QMediaDevices

    for device in QMediaDevices.audioOutputs():
        if bytes(device.id().data()) == b"musikata_null":
            return lambda: device
    pytest.skip("no null output (musikata_null): tier 1's container starts one")


def sine(path, rate, channels):
    class Song:
        seconds = 4.0

        def __init__(self):
            self.rate, self.start = rate, 0

        def seek(self, sample):
            self.start = sample

        def blocks(self, frames):
            n = int(self.seconds * rate)
            t = np.arange(n) / rate
            x = (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
            for at in range(self.start, n, frames):
                yield np.repeat(x[at : at + frames, None], channels, axis=1)

        def close(self):
            pass

    return Song()


def test_the_engine_plays_the_tone_told_and_a_change_while_it_plays_is_built_and_heard(
    tmp_path, null_output, qtbot
):
    engine = player.Engine(sine, null_output)
    p = bridges.Player(str(tmp_path), engine, equalizer=settings.Equalizer(on=True, preset="Rock"))
    try:
        with qtbot.waitSignal(p.changed, timeout=WAIT, check_params_cb=lambda *a: p.playing):
            p.play_file(str(tmp_path / "a.flac"))

        def playing_tone():
            feed = engine._feed
            design = feed.equalizer.design if feed is not None else None
            return design.tone if design is not None else None

        qtbot.waitUntil(lambda: playing_tone() == tone_of("Rock"), timeout=WAIT)
        p.choosePreset("Loudness")
        qtbot.waitUntil(lambda: playing_tone() == tone_of("Loudness"), timeout=WAIT)
        assert engine.designs.built == 2
        p.setEqualizerOn(False)
        qtbot.waitUntil(lambda: engine._feed is not None and playing_tone() is None, timeout=WAIT)
    finally:
        p.close()
