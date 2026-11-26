"""One song running into the next in one stream, and seeking within one (src/musikata_core/audio/
join.py; A4.2, A4.6, R7.4, R7.6): generated songs fed through the stream, a device read out of it
a few frames at a time, and every frame checked.

The songs are numbered frames (frame i of a song holds base + i in its first channel, -(base + i)
in its second) at a small rate, so a frame lost, doubled or out of place shows by its number, and
sines at real rates for the resampling. No device, no clock and no thread: the device is a loop
that reads and says where it has got to.

Why: a gapless join is only gapless if no frame goes missing or comes twice where one song meets
the next, whatever changes in the queue as it nears; and the bar must change when the next song is
heard, not when it was decoded two seconds before."""

import logging

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core.audio import decode, gain, join, seam, stream
from musikata_core.audio.decode import DecodeError

RATE = 100  # the device's and the numbered songs' rate: a frame a hundredth of a second


def numbered(base, start, n):
    i = np.arange(base + start, base + start + n, dtype=np.float32)
    return np.stack([i, -i], axis=1)


class Tune:
    """A song of `n` numbered frames from `base` at `rate`; its file says its length unless
    `known` is False. It raises `error` once it reaches frame `fails_at`."""

    def __init__(self, base, n, rate=RATE, known=True, error=None, fails_at=0):
        self.base, self.n, self.rate, self.known = base, n, rate, known
        self.error, self.fails_at = error, fails_at
        self.start, self.closed, self.sought = 0, False, []

    @property
    def seconds(self):
        return self.n / self.rate if self.known else None

    def seek(self, sample):
        self.start = sample
        self.sought.append(sample)

    def blocks(self, frames):
        for at in range(self.start, self.n, frames):
            if self.error is not None and at >= self.fails_at:
                raise self.error
            yield numbered(self.base, at, min(frames, self.n - at))

    def close(self):
        self.closed = True


class Wave:
    """A song of given samples (frames × channels) at `rate`."""

    def __init__(self, samples, rate):
        self.samples, self.rate, self.start = samples.astype(np.float32), rate, 0
        self.closed = False

    @property
    def seconds(self):
        return len(self.samples) / self.rate

    def seek(self, sample):
        self.start = sample

    def blocks(self, frames):
        for at in range(self.start, len(self.samples), frames):
            yield self.samples[at : at + frames]

    def close(self):
        self.closed = True


class Device:
    """A feed over a stream at `rate`, its songs opened from `songs` (a path to a song, or to a
    function making one), and a device reading it: `run` reads `step` frames at a time, filling
    before each read and hearing after it, `lag` frames behind what it has read (its own buffer),
    and keeps what it read and the songs it heard begin. `opened` lists each song opened, with
    the frame the song before it had reached."""

    def __init__(self, songs, rate=RATE, step=7, lag=0):
        self.songs, self.step, self.lag = songs, step, lag
        self.stream = stream.Stream(rate, 2)
        self.feed = join.Feed(self.stream, self.open)
        self.read, self.began, self.opened, self.made = [], [], [], {}

    def open(self, path):
        made = self.songs[path]
        song = made() if callable(made) else made
        if isinstance(song, Exception):
            raise song
        last = self.feed.flight[-1]
        self.opened.append((path, last.reached))
        self.made.setdefault(path, []).append(song)
        return song

    def start(self, path, ticket=1, gain=1.0):
        song = self.songs[path]
        song = song() if callable(song) else song
        self.made.setdefault(path, []).append(song)
        self.feed.start(ticket, path, song, gain)
        return self

    def fill(self):
        failure = self.feed.fill(10_000)
        assert failure is None, failure
        return self

    def take(self, frames):
        """The device reads `frames` (filling first), and hears up to what it has read."""
        self.fill()
        self.read.append(self.stream.take(frames))
        self.began += [p.path for p in self.feed.hear(max(0, self.stream.taken - self.lag))]
        return self

    def run(self, until=None, then=None):
        """Reads until the stream is drained, or until `until()` holds."""
        for _ in range(100_000):
            if self.stream.drained or (until is not None and until()):
                return self
            self.take(self.step)
        raise AssertionError("never drained")

    def out(self):
        return np.concatenate(self.read) if self.read else np.zeros((0, 2), np.float32)


def played(*parts):
    return np.concatenate([numbered(*p) for p in parts])


def follow(device, after, ticket, path, gain=1.0):
    return device.feed.follow(after, ticket, path, gain)


# ---------- the join ----------


def test_a_song_runs_into_the_next_with_no_frame_lost_or_added():
    d = Device({"a": Tune(0, 1500), "b": Tune(100_000, 300)}).start("a")
    follow(d, 1, 2, "b")
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 1500), (100_000, 0, 300)))
    assert d.stream.short == 0  # the device never found the ring empty
    assert d.began == ["b"]


def test_the_next_song_is_opened_ten_seconds_before_the_end_and_not_before():
    d = Device({"a": Tune(0, 1500), "b": Tune(100_000, 300)}).start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.opened)
    ((path, reached),) = d.opened
    assert path == "b" and 500 <= reached <= 502  # 15 s long: opened at 5 s, a block's grain
    assert len(d.feed._ahead.primed) == join.PRIME_BLOCKS  # its first blocks decoded already


def test_a_song_of_unknown_length_opens_the_next_at_its_end():
    d = Device({"a": Tune(0, 1500, known=False), "b": Tune(100_000, 300)}).start("a")
    follow(d, 1, 2, "b")
    d.run()
    assert d.opened == [("b", 1500)]
    assert np.array_equal(d.out(), played((0, 0, 1500), (100_000, 0, 300)))


def test_the_next_song_is_heard_at_its_first_frame_not_when_it_was_decoded():
    a, b = Tune(0, 150), Tune(100_000, 300)
    d = Device({"a": a, "b": b}).start("a")
    follow(d, 1, 2, "b")
    d.fill()
    assert d.feed.flight[1].mark == 150 and d.stream.written > 150  # b decoded already
    assert d.feed.hear(149) == [] and d.feed.position(149) == 1.49 and not a.closed
    assert [p.ticket for p in d.feed.hear(150)] == [2] and a.closed
    assert d.feed.position(150) == 0 and d.feed.position(200) == 0.5


@given(st.lists(st.integers(1, 250), min_size=1, max_size=3), st.integers(3, 60))
def test_any_songs_join_frame_for_frame_whatever_the_device_reads(lengths, step):
    songs = {str(i): Tune(i * 100_000, n) for i, n in enumerate(lengths)}
    d = Device(songs, step=step).start("0", ticket=0)
    follow(d, 0, 1, "1") if len(lengths) > 1 else None
    while not d.stream.drained:
        d.take(step)
        heard = d.feed.heard.ticket
        if heard + 1 < len(lengths):
            follow(d, heard, heard + 1, str(heard + 1))  # as the GUI tells it, on hearing a song
    assert np.array_equal(d.out(), played(*[(i * 100_000, 0, n) for i, n in enumerate(lengths)]))
    assert d.began == [str(i) for i in range(1, len(lengths))]


def test_a_song_can_follow_itself():
    d = Device({"a": lambda: Tune(0, 300)}).start("a")
    follow(d, 1, 2, "a")
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 300), (0, 0, 300)))
    assert [s.closed for s in d.made["a"]] == [True, False]


# ---------- what follows, changed ----------


def test_a_next_song_changed_before_the_device_reached_it_is_replaced_with_no_gap():
    d = Device({"a": Tune(0, 300), "b": Tune(100_000, 300), "c": Tune(200_000, 300)})
    d.start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.stream.taken >= 150)
    assert d.stream.written > 300  # b's first frames are in the ring
    assert follow(d, 1, 3, "c")
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 300), (200_000, 0, 300)))
    assert d.stream.short == 0 and d.made["b"][0].closed and d.began == ["c"]


def test_a_next_song_the_device_has_started_on_stays():
    d = Device({"a": Tune(0, 300), "b": Tune(100_000, 300), "c": Tune(200_000, 300)}, lag=25)
    d.start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.stream.taken > 300)
    assert d.began == []  # the device has taken b's first frame but not yet played it
    assert not follow(d, 1, 3, "c")  # too late: the GUI hears b begin
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 300), (100_000, 0, 300)))


def test_nothing_to_follow_any_more_ends_the_stream_after_the_song():
    d = Device({"a": Tune(0, 300), "b": Tune(100_000, 300)}).start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.stream.taken >= 200)
    assert follow(d, 1, 0, "")
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 300))) and d.made["b"][0].closed


def test_a_next_song_told_once_the_last_frame_went_in_still_joins_with_no_gap():
    d = Device({"a": Tune(0, 100), "b": Tune(100_000, 300)}).start("a")
    d.fill()
    assert d.stream.finished  # all of a in the ring, nothing after it
    d.take(40)
    assert follow(d, 1, 2, "b") and not d.stream.finished
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 100), (100_000, 0, 300)))
    assert d.stream.short == 0


def test_a_next_song_changed_before_it_was_opened_is_opened_in_its_place():
    d = Device({"a": Tune(0, 1500), "b": Tune(100_000, 30), "c": Tune(200_000, 30)}).start("a")
    follow(d, 1, 2, "b")
    d.take(10)
    assert follow(d, 1, 2, "b")  # the same again: nothing changes
    assert follow(d, 1, 3, "c")
    d.run()
    assert [p for p, _ in d.opened] == ["c"]
    assert np.array_equal(d.out(), played((0, 0, 1500), (200_000, 0, 30)))


def test_a_next_song_changed_once_opened_is_closed_and_the_new_one_opened():
    d = Device({"a": Tune(0, 1500), "b": Tune(100_000, 30), "c": Tune(200_000, 30)}).start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.opened)
    assert follow(d, 1, 3, "c")
    assert d.made["b"][0].closed
    d.run()
    assert [p for p, _ in d.opened] == ["b", "c"]
    assert np.array_equal(d.out(), played((0, 0, 1500), (200_000, 0, 30)))


def test_a_change_after_a_song_no_longer_playing_is_passed_over():
    d = Device({"a": Tune(0, 30)}).start("a")
    assert not follow(d, 7, 8, "b")


# ---------- songs that fail ----------


def test_a_next_song_that_cant_be_opened_lets_the_song_end_there(caplog):
    d = Device({"a": Tune(0, 300), "b": DecodeError("couldn't open b: gone")}).start("a")
    follow(d, 1, 2, "b")
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 300)))
    assert "couldn't open b to follow a: couldn't open b: gone" in caplog.text


def test_a_next_song_that_fails_before_the_device_reaches_it_is_cut_out(caplog):
    bad = Tune(100_000, 300, error=DecodeError("nothing in b decodes"), fails_at=20)
    d = Device({"a": Tune(0, 300), "b": bad}).start("a")
    follow(d, 1, 2, "b")
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 300)))  # b plays in its turn, and says why
    assert bad.closed and "couldn't play b after a: nothing in b decodes" in caplog.text


def test_a_next_song_that_fails_once_the_device_has_some_of_it_fails_the_playing():
    # the device has taken b's first frames, and has yet to play them: they can't be taken back
    bad = Tune(100_000, 600, error=DecodeError("nothing in b decodes"), fails_at=210)
    d = Device({"a": Tune(0, 300), "b": bad}, lag=100).start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.stream.taken > 300)
    failure = None
    while failure is None:
        d.stream.take(7)
        failure = d.feed.fill(10_000)
    assert failure == join.Failure(2, "nothing in b decodes")
    assert d.feed.flight[1].mark < d.stream.taken - 7 and d.began == []


def test_a_song_that_fails_while_heard_fails_the_playing():
    d = Device({"a": Tune(0, 900, error=DecodeError("damaged"), fails_at=400)}).start("a")
    d.take(10)
    failures = [d.feed.fill(10_000) for _ in range(300) if d.stream.take(7) is not None]
    assert join.Failure(1, "damaged") in failures


def test_a_decoders_own_fault_is_logged_and_said_by_its_kind(caplog):
    caplog.set_level(logging.ERROR)
    d = Device({"a": Tune(0, 300, error=RuntimeError("a bug"))}).start("a")
    assert d.feed.fill() == join.Failure(1, "decoding failed (RuntimeError)")
    assert "decoding a failed" in caplog.text and "a bug" in caplog.text
    assert join.why_of(DecodeError("damaged")) == "damaged"


def test_a_next_songs_own_fault_on_opening_is_logged_and_the_song_ends(caplog):
    d = Device({"a": Tune(0, 300), "b": RuntimeError("a bug")}).start("a")
    follow(d, 1, 2, "b")
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 300)))
    assert "opening b failed" in caplog.text and "a bug" in caplog.text


def test_a_next_song_failing_in_its_first_blocks_isnt_joined(caplog):
    bad = Tune(100_000, 300, error=DecodeError("nothing in b decodes"), fails_at=0)
    d = Device({"a": Tune(0, 300), "b": bad}).start("a")
    follow(d, 1, 2, "b")
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 300))) and bad.closed
    assert "couldn't open b to follow a: nothing in b decodes" in caplog.text


# ---------- seeking (A4.6) ----------


def test_a_seek_replaces_what_the_ring_holds_with_the_song_from_there():
    d = Device({"a": Tune(0, 1500)}).start("a")
    d.take(100)
    assert d.feed.seek(1, 700)
    assert d.feed.position(50) == 7.0  # the place sought, until the device gets there
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 100), (0, 700, 800)))
    assert d.feed.position(d.stream.taken) == 15.0


def test_a_seek_back_plays_again_what_was_played():
    d = Device({"a": Tune(0, 500)}).start("a")
    d.run(until=lambda: d.stream.taken >= 400)
    assert d.feed.seek(1, 0)
    d.run()
    assert np.array_equal(d.out(), played((0, 0, d.stream.taken - 500), (0, 0, 500)))


def test_a_seek_into_the_last_ten_seconds_opens_the_next_song_and_joins_it():
    d = Device({"a": Tune(0, 1500), "b": Tune(100_000, 300)}).start("a")
    follow(d, 1, 2, "b")
    d.take(20)
    assert d.opened == []
    d.feed.seek(1, 1450)
    d.run()
    assert d.opened == [("b", 1450 + 2)] or d.opened[0][0] == "b"
    assert np.array_equal(d.out(), played((0, 0, 20), (0, 1450, 50), (100_000, 0, 300)))
    assert d.stream.short == 0


def test_a_seek_once_the_next_song_has_gone_in_takes_it_out_and_joins_it_again():
    d = Device({"a": Tune(0, 300), "b": lambda: Tune(100_000, 300)}).start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.stream.taken >= 150)
    assert len(d.feed.flight) == 2  # b is in the ring after a
    assert d.feed.seek(1, 100)
    d.run()
    taken = 150 + (-150 % 7)
    assert np.array_equal(d.out(), played((0, 0, taken), (0, 100, 200), (100_000, 0, 300)))
    assert [s.closed for s in d.made["b"]] == [True, False]


def test_a_seek_past_the_end_goes_on_to_the_next_song():
    d = Device({"a": Tune(0, 1500), "b": Tune(100_000, 30)}).start("a")
    follow(d, 1, 2, "b")
    d.take(10)
    d.feed.seek(1, 5000)
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 10), (100_000, 0, 30)))


def test_a_seek_for_a_song_the_device_doesnt_play_does_nothing():
    d = Device({"a": Tune(0, 300)}).start("a")
    assert not d.feed.seek(2, 100)
    d.run()
    assert np.array_equal(d.out(), played((0, 0, 300)))
    assert not join.Feed(stream.Stream(RATE, 2), d.open).seek(1, 0)  # nothing playing
    assert join.Feed(stream.Stream(RATE, 2), d.open).fill() is None
    assert join.Feed(stream.Stream(RATE, 2), d.open).position(10) == 0


def test_closing_lets_go_of_every_song():
    d = Device({"a": Tune(0, 300), "b": Tune(100_000, 300), "c": Tune(200_000, 30)}).start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.stream.taken >= 150)
    follow(d, 2, 3, "c")
    d.fill()
    d.feed.close()
    assert all(s.closed for made in d.made.values() for s in made)
    assert d.feed.heard is None


# ---------- rates (A4.2, R7.6) ----------


def sine(rate, n, start=0, hz=440, level=0.5):
    """`n` samples of a sine at `rate`, from its sample `start`, in stereo."""
    x = level * np.sin(2 * np.pi * hz * np.arange(start, start + n) / rate)
    return np.stack([x, x], axis=1).astype(np.float32)


def alone(samples, rate, device):
    """What `samples` at `rate` give through one resampler of their own."""
    r = decode.Resampler(rate, device, 2)
    return np.concatenate([r.resample(samples), r.flush()])


def test_device_frames_fall_after_samples_as_the_resampler_places_them():
    assert join.frames_until(44100, 44100, 48000) == 48000
    assert join.frames_until(12345, 44100, 48000) == 13437  # 13436.7: the next frame is b's
    assert join.frames_until(147, 44100, 48000) == 160  # an instant both fall on
    assert join.frames_until(0, 44100, 48000) == 0
    r = decode.Resampler(44100, 48000, 2)
    assert len(alone(sine(44100, 12345), 44100, 48000)) == 13437 and r.flush().shape == (0, 2)


def test_songs_of_one_rate_join_as_if_they_were_one_song():
    # an album at 44.1 kHz on a 48 kHz device: the join is what resampling the two as one gives,
    # with none of the ringing a resampler of each song's own makes at its ends
    a, b = sine(44100, 30_001), sine(44100, 20_000, start=30_001)
    d = Device({"a": Wave(a, 44100), "b": Wave(b, 44100)}, rate=48000, step=480).start("a")
    follow(d, 1, 2, "b")
    d.run()
    whole = alone(np.concatenate([a, b]), 44100, 48000)
    assert np.abs(d.out() - whole).max() < 1e-6
    assert d.began == ["b"] and len(d.out()) == join.frames_until(50_001, 44100, 48000)
    seam = join.frames_until(30_001, 44100, 48000)
    ideal = 0.5 * np.sin(2 * np.pi * 440 * np.arange(seam - 50, seam + 50) / 48000)
    assert np.abs(d.out()[seam - 50 : seam + 50, 0] - ideal).max() < 1e-4  # no click


def test_songs_of_other_rates_and_channels_join_each_at_its_exact_length():
    # a mono song at 44.1 kHz, a stereo one at 96 kHz, one at the device's 48 kHz: each in the
    # stream as it plays alone, starting where the one before ended, so nothing drifts; only
    # their edges at the seams differ, primed there (seam.py)
    mono = sine(44100, 12_345)[:, :1].repeat(2, axis=1)  # folded to the device's two channels
    songs = {"a": Wave(mono, 44100), "b": Wave(sine(96000, 7_777), 96000),
             "c": Wave(sine(48000, 4_800), 48000)}  # fmt: skip
    d = Device(songs, rate=48000, step=480).start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.began == ["b"])
    follow(d, 2, 3, "c")
    d.run()
    parts = [alone(mono, 44100, 48000), alone(songs["b"].samples, 96000, 48000),
             songs["c"].samples]  # fmt: skip
    assert [len(p) for p in parts] == [13_437, 3_889, 4_800]
    out, whole = d.out(), np.concatenate(parts)
    assert len(out) == len(whole) and d.began == ["b", "c"] and d.stream.short == 0
    away = np.ones(len(whole), bool)
    for seam_at in (13_437, 13_437 + 3_889):
        away[seam_at - 40 : seam_at + 40] = False
    assert np.array_equal(out[away], whole[away])
    assert np.abs(out - whole).max() < 0.5  # at the seams: what the resamplers made up, changed


def chord(times):
    """Two tones, 1 and 7 kHz, at the instants `times` (seconds), in stereo."""
    x = 0.25 * np.sin(2 * np.pi * 1000 * times) + 0.25 * np.sin(2 * np.pi * 7000 * times)
    return np.stack([x, x], axis=1).astype(np.float32)


def tone(hz):
    def at(times):
        x = 0.5 * np.sin(2 * np.pi * hz * times)
        return np.stack([x, x], axis=1).astype(np.float32)

    return at


@pytest.mark.parametrize("signal", [tone(440), tone(5000), chord], ids=["440", "5k", "chord"])
@pytest.mark.parametrize(
    "rate_a, rate_b",
    [(44100, 96000), (96000, 44100), (44100, 48000), (48000, 44100), (22050, 48000)],
)
def test_a_tone_going_on_across_songs_of_other_rates_doesnt_click_at_the_seam(
    signal, rate_a, rate_b
):
    """The tone the two songs make together, each at its own rate (b's first sample where the
    stream puts it), heard through the seam with no more error than resampling makes anywhere:
    a resampler of each song's own, unprimed, was off by up to a quarter of full scale there."""
    n = rate_a * 3 // 10
    seam_at = join.frames_until(n, rate_a, 48000)
    a = signal(np.arange(n) / rate_a)
    b = signal(seam_at / 48000 + np.arange(rate_b // 5) / rate_b)
    d = Device({"a": Wave(a, rate_a), "b": Wave(b, rate_b)}, rate=48000, step=480).start("a")
    follow(d, 1, 2, "b")
    d.run()
    out = d.out()
    near = slice(seam_at - 300, seam_at + 300)
    heard = signal(np.arange(len(out)) / 48000)
    assert np.abs(out[near] - heard[near]).max() < 1e-4
    assert d.began == ["b"] and d.feed.flight[0].mark == seam_at


def test_a_seam_after_silence_or_a_song_too_short_to_predict_is_primed_with_silence():
    quiet = np.zeros((441, 2), np.float32)
    d = Device({"a": Wave(quiet, 44100), "b": Wave(sine(96000, 9600), 96000)}, rate=48000,
               step=480).start("a")  # fmt: skip
    follow(d, 1, 2, "b")
    d.run()
    out = d.out()
    assert np.abs(out[:400]).max() < 1e-6 and len(out) == 480 + 4800
    assert np.abs(seam.continued(np.zeros((0, 2), np.float32), 4)).max() == 0
    assert seam.continued(np.ones((3, 1), np.float32), 0).shape == (0, 1)
    assert len(seam.predictor(np.array([0.5]))) == 1  # one sample: nothing to fit
    assert np.allclose(seam.continued(np.full((64, 1), 0.5, np.float32), 8), 0.5, atol=1e-3)


def test_a_prediction_never_goes_past_full_scale():
    rising = np.linspace(0.0, 0.99, 64, dtype=np.float32)[:, None]
    assert np.abs(seam.continued(rising, 200)).max() <= 1.0
    assert np.abs(seam.preceding(rising[::-1].copy(), 200)).max() <= 1.0


# ---------- gain (R7.5, R7.6.1, A4.4) ----------


def level(rate, n, value=0.5):
    """A song holding one level, as a step shows its gain plainly."""
    return Wave(np.full((n, 2), value, np.float32), rate)


def test_each_song_plays_at_its_gain_and_a_change_ramps_over_50_ms_from_the_join():
    d = Device({"a": level(48000, 4800), "b": level(48000, 9600)}, rate=48000, step=480)
    d.start("a", gain=1.0)
    follow(d, 1, 2, "b", 0.5)
    d.run()
    out, ramp = d.out()[:, 0], join.frames_of(gain.RAMP_SECONDS, 48000)
    assert ramp == 2400 and len(out) == 14_400
    assert np.all(out[:4800] == 0.5) and np.all(out[4800 + ramp :] == 0.25)
    steps = np.diff(out[4799 : 4800 + ramp + 1])
    assert np.all(steps <= 0) and np.abs(steps).max() <= 0.25 / ramp * 1.001  # no click
    assert out[4800] < 0.5 and out[4800 + ramp - 1] == 0.25


def test_a_join_with_no_change_of_gain_isnt_ramped_and_a_song_alone_has_its_gain():
    d = Device({"a": level(100, 300), "b": level(100, 300)}).start("a", gain=0.5)
    follow(d, 1, 2, "b", 0.5)
    d.run()
    assert np.all(d.out() == 0.25) and d.feed.heard.ramp_from is None


def test_a_change_of_gain_across_rates_ramps_from_the_seam_too():
    d = Device({"a": level(44100, 4410), "b": level(96000, 9600)}, rate=48000, step=480)
    d.start("a", gain=0.5)
    follow(d, 1, 2, "b", 1.0)
    d.run()
    out = d.out()[:, 0]
    assert (
        np.abs(out[200:4600] - 0.25).max() < 1e-3 and np.abs(out[4800 + 2600 :] - 0.5).max() < 1e-3
    )
    assert np.abs(np.diff(out[4700:7300])).max() < 0.25 / 2400 * 1.5


def test_a_song_shorter_than_the_ramp_hands_on_the_gain_it_reached():
    d = Device({"a": level(100, 300), "b": level(100, 2), "c": level(100, 300)}).start("a")
    follow(d, 1, 2, "b", 0.0)
    d.run(until=lambda: d.began == ["b"])
    follow(d, 2, 3, "c", 0.0)
    d.run()
    out = d.out()[:, 0]  # the ramp is 5 frames at 100 Hz: b's two take it 2/5 of the way down
    assert np.allclose(out[300:302], [0.4, 0.3]) and np.allclose(
        out[302:307], [0.24, 0.18, 0.12, 0.06, 0.0]
    )


def test_a_next_song_told_again_with_another_gain_goes_in_with_that_one():
    d = Device({"a": level(100, 200), "b": level(100, 100)}).start("a")
    follow(d, 1, 2, "b", 1.0)
    d.fill()
    assert follow(d, 1, 2, "b", 0.5)
    d.run()
    assert np.all(d.out()[210:, 0] == 0.25)


def test_a_seek_plays_the_song_on_at_its_gain_with_no_ramp():
    d = Device({"a": level(100, 300), "b": level(100, 3000)}).start("a")
    follow(d, 1, 2, "b", 0.5)
    d.run(until=lambda: d.stream.taken >= 302)
    assert d.feed.heard.ramp_from == 1.0
    assert d.feed.seek(2, 1000)
    assert d.feed.heard.ramp_from is None
    d.run()
    assert np.all(d.out()[310:, 0] == 0.25)


# ---------- the device changing (A4.6, R7.7) ----------


def test_a_new_device_goes_on_from_the_frame_the_old_one_had_played():
    d = Device({"a": Tune(0, 900), "b": Tune(100_000, 100)}).start("a")
    follow(d, 1, 2, "b")
    d.run(until=lambda: d.stream.taken >= 300)
    old = d.made["a"][0]
    new = stream.Stream(RATE, 2)
    assert d.feed.move(new, d.open, 250) is None  # the device had played 250 of the 300 taken
    assert old.closed and d.feed.stream is new and d.feed.heard.mark == 0
    assert d.feed.position(0) == 2.5
    d.stream, d.read = new, []
    d.run()
    assert np.array_equal(d.out(), played((0, 250, 650), (100_000, 0, 100)))
    assert d.began == ["b"]


def test_a_new_device_of_another_rate_hears_the_song_on_from_the_same_instant():
    a = sine(44100, 44100)
    d = Device({"a": Wave(a, 44100)}, rate=48000, step=480).start("a")
    d.run(until=lambda: d.stream.taken >= 9600)
    d.songs["a"] = Wave(a[:, :1], 44100)  # opened again for a device of one channel
    new = stream.Stream(96000, 1)
    assert d.feed.move(new, d.open, 4800) is None  # 0.1 s in
    assert d.feed.position(0) == 0.1
    d.stream, d.read = new, []
    d.run()
    out = d.out()
    assert len(out) == 96000 - 9600
    on = 0.5 * np.sin(2 * np.pi * 440 * (0.1 + np.arange(2000) / 96000))
    assert np.abs(out[:2000, 0] - on).max() < 1e-3  # resampled from there, no click at its start


def test_a_song_that_cant_be_opened_for_the_new_device_fails():
    d = Device({"a": Tune(0, 900)}).start("a")
    d.run(until=lambda: d.stream.taken >= 100)
    d.songs["a"] = DecodeError("couldn't open a: gone")
    failure = d.feed.move(stream.Stream(RATE, 2), d.open, 50)
    assert failure == join.Failure(1, "couldn't open a: gone") and d.feed.heard is None
    assert join.Feed(stream.Stream(RATE, 2), d.open).move(stream.Stream(RATE, 1), d.open, 0) is None


def test_a_song_whose_opener_breaks_for_the_new_device_is_logged(caplog):
    d = Device({"a": Tune(0, 900)}).start("a")
    d.run(until=lambda: d.stream.taken >= 100)
    d.songs["a"] = RuntimeError("a bug")
    failure = d.feed.move(stream.Stream(RATE, 2), d.open, 50)
    assert failure.why == "decoding failed (RuntimeError)" and "a bug" in caplog.text


# ---------- the stream's own steps ----------


def test_the_stream_takes_back_what_the_device_hasnt_taken_and_never_what_it_has():
    s = stream.Stream(100, 2, ahead=1.0)
    s.feed(numbered(0, 0, 50))
    s.take(20)
    assert s.cut(30) == 20 and s.written == 30 and s.ring.held == 10
    s.feed(numbered(1000, 0, 5))
    assert np.array_equal(s.take(15), np.concatenate([numbered(0, 20, 10), numbered(1000, 0, 5)]))
    with pytest.raises(ValueError, match="the device has taken 35"):
        s.cut(34)
    s.finish()
    s.reopen()
    assert not s.finished and s.ring.drop(5) == 0
