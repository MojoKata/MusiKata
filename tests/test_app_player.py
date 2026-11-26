"""Playing a song (src/musikata/player.py, and the Player bridge of bridges.py; A4.1, R7.1): the
playback thread decoding into the ring buffer, a QAudioSink in pull mode on that thread reading
it, and what QML sees of it; and a double click in the Songs list playing the song.

They play generated audio into a null output: PulseAudio's null sink, which scripts/test-tier1.sh
starts in tier 1's container, as there is no sound card (docs/process/testing.md). A run by hand
without it skips them rather than play tones through the speakers. Each waits for the signal or
state that says the song began, moved or ended; the one fixed wait shows a paused song staying
where it is.

Why: the device pulls on its own schedule, on another thread. A sink starved at the start, a song
whose end is never noticed, a pause that doesn't hold, or a thread left running at close are each
only seen with a real sink pulling."""

import logging
import os
import sys

import numpy as np
import pytest
from fakes import FakeClock, fill
from PySide6.QtCore import QPointF, Qt
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QMediaDevices
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from musikata import app, bridges, models, player
from musikata_core.audio import stream
from musikata_core.audio.decode import DecodeError

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

NULL = b"musikata_null"  # the null sink scripts/test-tier1.sh starts
WAIT = 10_000  # ms: only a failure reaches it


@pytest.fixture
def null_output(qapp):
    """The null sink, as the engine's output."""
    for device in QMediaDevices.audioOutputs():
        if bytes(device.id().data()) == NULL:
            return lambda: device
    pytest.skip("no null output (musikata_null): tier 1's container starts one")


class Tone:
    """Opens every path as a generated song: a sine `seconds` long, which raises `error` after
    `good` blocks when given one. Remembers what it opened and closed."""

    def __init__(self, seconds=0.3, error=None, good=0, length=True):
        self.seconds_, self.error, self.good, self.length = seconds, error, good, length
        self.opened, self.closed = [], []

    def __call__(self, path, rate, channels):
        if os.path.basename(path).startswith("missing"):
            raise DecodeError(f"couldn't open {path}: gone")
        tone = self

        class Song:
            seconds = tone.seconds_ if tone.length else None

            def blocks(self, frames):
                n = int(tone.seconds_ * rate)
                t = np.arange(n) / rate
                x = (0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
                for i, at in enumerate(range(0, n, frames)):
                    if tone.error is not None and i >= tone.good:
                        raise tone.error
                    yield np.repeat(x[at : at + frames, None], channels, axis=1)

            def close(self):
                tone.closed.append(path)

        tone.opened.append(path)
        return Song()


@pytest.fixture
def make(tmp_path, null_output):
    """Players over tmp_path, each closed after the test: make(opener=None, output=None)."""
    made = []

    def make_(opener=None, output=None):
        engine = player.Engine(opener or player.DecodedSong, output or null_output)
        p = bridges.Player(str(tmp_path), engine)
        made.append(p)
        return p

    yield make_
    for p in made:
        p.close()


def heard(p):
    """What a player said, in order: the songs playing and the positions."""
    log = {"now": [], "positions": []}
    p.nowPlaying.connect(log["now"].append)
    p.positionChanged.connect(lambda: log["positions"].append(p.property("position")))
    return log


# ---------- plain pieces, no device ----------


def test_stereo_is_played_on_any_device_that_takes_it_and_mono_on_one_that_doesnt():
    assert [player.channels_for(n) for n in (0, 1, 2, 6)] == [1, 1, 2, 2]


def test_a_device_that_says_nothing_gets_float_samples_at_the_fallback_rate(qapp):
    fmt = player.output_format(QAudioDevice())
    assert fmt.sampleRate() == player.FALLBACK_RATE and fmt.channelCount() == 1
    assert fmt.sampleFormat() == QAudioFormat.SampleFormat.Float


def test_the_device_reads_the_ring_as_bytes_and_writes_nothing():
    s = stream.Stream(1000, 2, ahead=0.1)
    s.feed(np.full((10, 2), 0.5, np.float32))
    io = player.RingDevice(s)
    assert io.isSequential() and io.bytesAvailable() == 80
    assert io.read(24).data() == np.full(6, 0.5, "<f4").tobytes()  # whole frames only
    assert s.taken == 3 and io.bytesAvailable() == 56
    assert io.writeData(b"abc", 3) == -1


def test_asking_an_engine_with_nothing_playing_to_pause_resume_or_stop_does_nothing(qtbot):
    engine = player.Engine(Tone())
    said = []
    engine.pausedChanged.connect(said.append)
    engine.stopped.connect(said.append)
    engine.pause()
    engine.resume()
    engine.stop()
    assert said == []


def test_a_player_that_never_played_closes_at_once(tmp_path, qapp):
    p = bridges.Player(str(tmp_path), player.Engine(Tone()))
    p.close()
    assert p.property("path") == "" and p.property("playing") is False


# ---------- into the null output ----------


@pytest.mark.slow
def test_a_song_plays_to_its_end_and_its_position_moves_with_it(make, tmp_path, qtbot):
    demo.encode(str(tmp_path / "Signal Fires.flac"), "flac", 0.4, 440)
    p = make()
    log = heard(p)
    p.play("Signal Fires.flac")
    qtbot.waitUntil(lambda: p.property("path") == "Signal Fires.flac", timeout=WAIT)
    assert p.property("playing") is True and p.property("paused") is False
    assert p.property("length") == pytest.approx(0.4, abs=0.01)
    qtbot.waitUntil(lambda: p.last == "ended", timeout=WAIT)
    assert log["now"] == ["Signal Fires.flac", ""]
    moved = [x for x in log["positions"] if x > 0]
    assert moved and moved == sorted(moved) and max(moved) > 0.2
    assert p.property("path") == "" and p.property("playing") is False
    assert p.property("position") == 0 and p.property("error") == ""


@pytest.mark.slow
def test_a_song_in_a_folder_is_played_by_its_path_under_the_root(make, tmp_path, qtbot):
    tone = Tone(0.2, length=False)
    p = make(tone)
    p.play("Lumen Drift/Glass Harbor/04 Signal Fires.flac")
    qtbot.waitUntil(lambda: p.property("path") != "", timeout=WAIT)
    assert p.property("path") == "Lumen Drift/Glass Harbor/04 Signal Fires.flac"
    assert tone.opened == [os.path.join(str(tmp_path), "Lumen Drift", "Glass Harbor",
                                        "04 Signal Fires.flac")]  # fmt: skip
    assert p.property("length") == 0  # unknown
    qtbot.waitUntil(lambda: p.last == "ended", timeout=WAIT)
    assert tone.closed == tone.opened


@pytest.mark.slow
def test_a_paused_song_stays_where_it_is_until_it_resumes(make, qtbot):
    p = make(Tone(1.0))
    p.play("a.flac")
    qtbot.waitUntil(lambda: p.property("position") > 0.1, timeout=WAIT)
    p.pause()
    qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    assert p.property("playing") is False and p.property("path") == "a.flac"
    at = p.property("position")
    qtbot.wait(300)  # the one fixed wait: nothing moves while paused
    assert p.property("position") == at and p.last == ""
    p.pause()  # again: nothing more
    p.resume()
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    qtbot.waitUntil(lambda: p.property("position") > at, timeout=WAIT)
    qtbot.waitUntil(lambda: p.last == "ended", timeout=WAIT)


@pytest.mark.slow
def test_stop_stops_the_song_and_lets_go_of_it(make, qtbot):
    tone = Tone(5.0)
    p = make(tone)
    p.play("a.flac")
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    p.pause()
    qtbot.waitUntil(lambda: p.property("paused"), timeout=WAIT)
    p.stop()
    qtbot.waitUntil(lambda: p.last == "stopped", timeout=WAIT)
    assert p.property("path") == "" and p.property("paused") is False
    assert tone.closed == tone.opened


@pytest.mark.slow
def test_playing_another_song_puts_it_in_place_of_the_one_playing(make, qtbot):
    tone = Tone(5.0)
    p = make(tone)
    log = heard(p)
    p.play("a.flac")
    qtbot.waitUntil(lambda: p.property("path") == "a.flac", timeout=WAIT)
    tone.seconds_ = 0.2
    p.play("b.flac")
    qtbot.waitUntil(lambda: p.last == "ended", timeout=WAIT)
    assert log["now"] == ["a.flac", "b.flac", ""]
    assert [os.path.basename(x) for x in tone.closed] == ["a.flac", "b.flac"]


@pytest.mark.slow
def test_a_file_that_cant_be_played_says_why_and_nothing_plays(make, tmp_path, qtbot, caplog):
    (tmp_path / "Undertow.mp3").write_bytes(b"not audio")
    p = make()
    p.play("Undertow.mp3")
    qtbot.waitUntil(lambda: p.last == "failed", timeout=WAIT)
    assert "couldn't open" in p.property("error") and p.property("path") == ""
    assert "couldn't play" in caplog.text and "nothing plays now" in caplog.text


@pytest.mark.slow
def test_a_song_that_fails_halfway_stops_there_and_says_why(make, qtbot):
    tone = Tone(5.0, error=DecodeError("nothing in a.flac decodes"), good=150)
    p = make(tone)
    p.play("a.flac")
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    qtbot.waitUntil(lambda: p.last == "failed", timeout=WAIT)
    assert p.property("error") == "nothing in a.flac decodes" and tone.closed == tone.opened


@pytest.mark.slow
def test_a_decoder_that_breaks_stops_its_song_not_the_thread(make, qtbot, caplog):
    tone = Tone(0.3, error=RuntimeError("a bug"), good=0)
    p = make(tone)
    caplog.set_level(logging.WARNING)
    p.play("a.flac")
    qtbot.waitUntil(lambda: p.last == "failed", timeout=WAIT)
    assert p.property("error") == "decoding failed (RuntimeError)"
    assert "decoding" in caplog.text and "a bug" in caplog.text
    tone.error = None
    p.play("b.flac")  # the thread plays on
    qtbot.waitUntil(lambda: p.last == "ended", timeout=WAIT)


@pytest.mark.slow
def test_with_no_sound_device_nothing_plays_and_it_says_so(make, qtbot):
    p = make(Tone(), output=QAudioDevice)
    p.play("a.flac")
    qtbot.waitUntil(lambda: p.last == "failed", timeout=WAIT)
    assert p.property("error") == "there is no sound device"


@pytest.mark.slow
def test_closing_while_a_song_plays_stops_it_and_ends_the_thread(make, qtbot):
    tone = Tone(5.0)
    p = make(tone)
    p.play("a.flac")
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    p.close()
    assert tone.closed == tone.opened and not p._thread._thread.isRunning()


# ---------- the Songs list ----------


def test_the_song_playing_is_marked_in_the_songs_list(tmp_path, qtbot):
    from musikata_core import db

    index = db.Index(str(tmp_path / "musikata.db"))
    fill(index, [{"path": "a.flac", "title": "A"}, {"path": "b.flac", "title": "B"}])
    songs = models.SongsModel(index.read)
    songs.reload()
    role = models.PLAYING
    assert songs.roleNames()[role].data() == b"playing"
    marked = []
    songs.dataChanged.connect(lambda a, b, roles: marked.append((a.row(), b.row(), list(roles))))
    songs.set_playing("b.flac")
    songs.set_playing("b.flac")  # the same again: nothing
    assert marked == [(0, 1, [role])]
    assert [songs.data(songs.index(i), role) for i in (0, 1)] == [False, True]
    assert songs.data(songs.index(5), role) is None
    index.close()


@pytest.mark.slow
def test_double_clicking_a_song_plays_it_and_marks_its_row(tmp_path, qtbot, null_output):
    root = tmp_path / "Music"
    root.mkdir()
    tone = Tone(5.0)
    shell = app.load(str(root), {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)},
                     FakeClock(), playback=lambda: player.Engine(tone, null_output))  # fmt: skip
    try:
        fill(shell.index, [{"path": "a.flac", "title": "A"}, {"path": "b.flac", "title": "B"}])
        shell.library.songs.reload()
        shell.window.show()
        qtbot.waitExposed(shell.window)
        rows = shell.window.findChild(QQuickItem, "songs")

        def drawn():  # the rows' delegates, made as the list is laid out
            return [r.property("path") for r in rows.property("contentItem").childItems()]

        def title_colour(path):
            row = next(r for r in rows.property("contentItem").childItems()
                       if r.property("path") == path)  # fmt: skip
            title = row.property("title")
            return next(t.property("color").name() for t in row.childItems()
                        if t.property("text") == title)  # fmt: skip

        qtbot.waitUntil(lambda: "b.flac" in drawn(), timeout=WAIT)
        at = rows.mapToScene(QPointF(200, 36 + 18)).toPoint()  # the second row's middle
        QTest.mouseDClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)
        qtbot.waitUntil(lambda: shell.player.property("path") == "b.flac", timeout=WAIT)
        assert tone.opened == [os.path.join(str(root), "b.flac")]
        songs = shell.library.songs
        assert [songs.data(songs.index(i), models.PLAYING) for i in (0, 1)] == [False, True]
        qtbot.waitUntil(lambda: title_colour("b.flac") == "#c4b5fd", timeout=WAIT)  # accentHi
        assert title_colour("a.flac") == "#eceef4"  # text
    finally:
        shell.close()
    assert tone.closed == tone.opened
