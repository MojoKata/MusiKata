"""A song's waveform worked out of its file, a part at a time, and kept by its audio hash
(src/musikata_core/analysis/waveform.py; A5.1, R11.1.1): generated WAV files decoded by PyAV, and a
stand-in file of three hours that yields generated blocks; the parts joined against the whole; the
partial waveforms; the index's `waveform` table.

The shapes (docs/process/testing.md, `audio`'s row): a sine, a silence, a click, a song of one
sample and of three hours, stereo, a length the file doesn't say or gets wrong either way, a file
missing or not audio.

Why: a waveform drawn from parts that overlap, leave a gap or misplace the song's end is a seek bar
whose peaks aren't where the sound is; and one kept by path would be lost by a retag or a move."""

import wave

import numpy as np
import pytest

from musikata_core import db
from musikata_core.analysis import peaks, waveform
from musikata_core.audio.decode import DecodeError

RATE = 8000


def write_wav(path, samples, rate=RATE, channels=1):
    """`samples` (-1 to 1; frames × channels when `channels` > 1) as 16-bit WAV at `path`."""
    data = np.round(np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())
    return str(path)


def song(seconds, rate=RATE):
    """A tone whose loudness climbs from nothing to 0.8 over the song."""
    n = round(seconds * rate)
    t = np.arange(n) / rate
    return (np.linspace(0, 0.8, n) * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)


def whole(path):
    """Every part of the file, in order, as the app's thread takes them."""
    assembly = waveform.Assembly()
    while not assembly.complete:
        assembly.add(waveform.decode_part(path, assembly.next))
    return assembly


class Stand:
    """A file of `n` samples at `rate` saying it lasts `said` seconds (None: it doesn't say), its
    sample i being `level(i)`; it gives blocks of a million samples, whatever is asked."""

    opened = 0

    def __init__(self, n, rate, said, level):
        self.n, self.rate, self.seconds, self.level = n, rate, said, level
        self.at = 0

    def seek(self, sample):
        self.at = sample

    def blocks(self, frames):
        for start in range(self.at, self.n, 1_000_000):
            i = np.arange(start, min(self.n, start + 1_000_000))
            yield self.level(i).astype(np.float32)[:, None]

    def __enter__(self):
        Stand.opened += 1
        return self

    def __exit__(self, *exc):
        return None


def opener(n, rate, said, level=lambda i: (i % 7 == 0) * (i / 1e9)):
    return lambda path, channels: Stand(n, rate, said, level)


# ---------- the cut ----------


def test_a_song_is_cut_in_parts_of_30_seconds_each_a_whole_number_of_hops():
    cut = waveform.plan(44_100 * 240, 44_100)
    assert cut.hop == 44_100 * 240 // waveform.FINE
    assert cut.step % cut.hop == 0 and cut.step >= 30 * 44_100
    assert cut.parts == 8


def test_a_song_whose_length_the_file_doesnt_say_is_one_part():
    cut = waveform.plan(None, 44_100)
    assert cut.parts == 1 and cut.hop == round(600 * 44_100) // waveform.FINE


def test_a_short_song_is_one_part_of_single_samples():
    assert waveform.plan(10, 44_100) == waveform.Plan(1, 1323000, 1)


# ---------- decoded ----------


def test_a_sine_decoded_in_parts_is_the_waveform_of_the_whole(tmp_path):
    x = song(70.0)  # three parts: 30 s, 30 s, and the last 10
    path = write_wav(tmp_path / "a.wav", x)
    parts = [waveform.decode_part(path, i) for i in range(3)]
    assert [p.parts for p in parts] == [3, 3, 3] and parts[0].expected == len(x)
    assert sum(p.frames for p in parts) == len(x)
    assembly = waveform.Assembly()
    for p in parts:
        assembly.add(p)
    assert assembly.complete
    hop = parts[0].hop
    top, bottom = peaks.pairs(np.round(x * 32767) / 32767, hop)
    assert np.allclose(assembly.peaks(), peaks.reduce(top, bottom), atol=1e-4)


def test_silence_decodes_to_a_flat_line(tmp_path):
    path = write_wav(tmp_path / "quiet.wav", np.zeros(RATE * 3, np.float32))
    assert not whole(path).peaks().any()


def test_a_click_stands_where_it_is_in_the_song(tmp_path):
    x = np.zeros(RATE * 40, np.float32)
    x[RATE * 35] = 0.5  # in the second part, seven eighths of the way
    got = whole(write_wav(tmp_path / "click.wav", x)).peaks()
    assert np.flatnonzero(got[:, 0]).tolist() == [1750]
    assert got[1750, 0] == pytest.approx(0.5, abs=1e-4)


def test_a_song_of_one_sample_is_that_sample_throughout(tmp_path):
    got = whole(write_wav(tmp_path / "one.wav", np.array([0.5], np.float32))).peaks()
    assert np.allclose(got, 0.5, atol=1e-4)


def test_stereo_is_folded_to_mono(tmp_path):
    x = song(2.0)
    path = write_wav(tmp_path / "two.wav", np.stack([x, x], axis=1), channels=2)
    mono = write_wav(tmp_path / "one.wav", x)
    assert np.allclose(whole(path).peaks(), whole(mono).peaks(), atol=1e-4)


def test_a_file_missing_or_not_audio_cant_be_decoded(tmp_path):
    with pytest.raises(DecodeError):
        waveform.decode_part(str(tmp_path / "gone.wav"), 0)
    (tmp_path / "notes.wav").write_text("not a song")
    with pytest.raises(DecodeError):
        waveform.decode_part(str(tmp_path / "notes.wav"), 0)


@pytest.mark.slow
def test_a_song_of_three_hours_fills_in_every_30_seconds_and_ends_where_it_ends():
    rate, n = 1000, 1000 * 3 * 3600
    level = lambda i: i / n  # noqa: E731  (louder to the very end)
    Stand.opened = 0
    assembly = waveform.Assembly()
    halfway = None
    while not assembly.complete:
        assembly.add(
            waveform.decode_part("long.mp3", assembly.next, opener(n, rate, 10800.0, level))
        )
        if assembly.next == 178:
            halfway = assembly.peaks()
    # a part, and a partial waveform, every 30 seconds (a whole number of hops: 30.375)
    assert Stand.opened == 356
    assert np.all(halfway[1002:] == 0) and halfway[999, 0] > 0.49  # the rest a flat line
    got = assembly.peaks()
    assert got[-1, 0] == pytest.approx(1.0, abs=1e-6) and np.all(np.diff(got[:, 0]) > 0)


def test_a_file_that_says_it_is_longer_than_it_is_ends_its_waveform_at_its_end():
    n = 1000 * 60
    assembly = waveform.Assembly()
    while not assembly.complete:  # it says 120 s: the parts past its end hold nothing
        assembly.add(waveform.decode_part("a", assembly.next, opener(n, 1000, 120.0, np.ones_like)))
    assert assembly.next == 4
    assert np.all(assembly.peaks()[:, 0] == 1.0)


def test_a_file_that_says_it_is_shorter_than_it_is_keeps_its_end_in_the_last_part():
    n = 1000 * 90
    level = lambda i: (i >= 80_000).astype(float)  # noqa: E731  (only its last 10 s)
    assembly = waveform.Assembly()
    while not assembly.complete:  # it says 40 s: two parts, the second to the real end
        assembly.add(waveform.decode_part("a", assembly.next, opener(n, 1000, 40.0, level)))
    assert assembly.next == 2
    got = assembly.peaks()
    assert got[-1, 0] == 1.0 and got[0, 0] == 0.0


def test_a_file_that_doesnt_say_its_length_is_one_part_and_whole():
    n = 1000 * 20
    part = waveform.decode_part("a", 0, opener(n, 1000, None, np.ones_like))
    assert (part.parts, part.expected, part.frames) == (1, 0, n)
    assembly = waveform.Assembly()
    assembly.add(part)
    assert assembly.complete and np.all(assembly.peaks()[:, 0] == 1.0)


def test_nothing_decoded_yet_is_a_flat_line():
    assembly = waveform.Assembly()
    assert not assembly.complete and assembly.next == 0
    assert not assembly.peaks().any() and assembly.peaks().shape == (peaks.N, 2)


def test_gathering_keeps_whats_left_over_for_the_next_block():
    g = waveform.Gathering(4)
    g.add(np.array([0.1, 0.2, 0.3], np.float32))
    g.add(np.array([0.9, -0.5, 0.0, 0.0, 0.0, 0.4], np.float32))
    top, bottom = g.done()
    assert top.tolist() == pytest.approx([0.9, 0.0, 0.4])
    assert bottom.tolist() == pytest.approx([0.1, -0.5, 0.4])
    assert [len(a) for a in waveform.Gathering(4).done()] == [0, 0]


# ---------- kept in the index ----------


@pytest.fixture
def c(tmp_path):
    conn = db.connect(str(tmp_path / "musikata.db"))
    db.migrate(conn)
    yield conn
    conn.close()


@pytest.mark.slow
def test_version_14_adds_the_waveform_table_and_reads_nothing_again(tmp_path):
    conn = db.connect(str(tmp_path / "musikata.db"))
    for step in db.MIGRATIONS[:13]:
        step(conn)
    conn.execute("PRAGMA user_version = 13")
    conn.execute("INSERT INTO song (path, size, mtime_ns) VALUES ('a.flac', 10, 5)")
    db.MIGRATIONS[13](conn)  # version 14 alone
    assert conn.execute("SELECT mtime_ns FROM song").fetchall() == [(5,)]
    assert conn.execute("SELECT count(*) FROM waveform").fetchone() == (0,)
    conn.close()


def test_a_waveform_is_kept_by_its_audio_hash_so_a_moved_song_finds_it(c):
    c.execute("INSERT INTO song (path, size, mtime_ns, audio_hash) VALUES ('a.flac', 1, 1, 'h1')")
    got = peaks.peaks(song(1.0))
    waveform.keep(c, waveform.hash_of(c, "a.flac"), got)
    c.execute("UPDATE song SET path = 'moved/a.flac'")  # moved, or retagged: the same audio
    found = waveform.stored(c, waveform.hash_of(c, "moved/a.flac"))
    assert np.allclose(found, got, atol=1 / peaks.FULL)
    waveform.keep(c, "h1", np.zeros((peaks.N, 2), np.float32))  # worked out again: replaced
    assert not waveform.stored(c, "h1").any()


def test_a_song_without_a_hash_or_a_waveform_kept_finds_none(c):
    c.execute("INSERT INTO song (path, size, mtime_ns) VALUES ('unread.flac', 1, 1)")
    assert waveform.hash_of(c, "unread.flac") is None
    assert waveform.hash_of(c, "not there.flac") is None
    assert waveform.stored(c, "h9") is None


def test_a_waveform_kept_broken_or_of_another_size_is_worked_out_again(c):
    c.execute("INSERT INTO waveform VALUES ('odd', x'000102')")
    c.execute("INSERT INTO waveform VALUES ('short', ?)", (peaks.to_blob(np.zeros((10, 2))),))
    c.execute("INSERT INTO waveform VALUES ('text', 'not bytes')")
    assert waveform.stored(c, "odd") is None
    assert waveform.stored(c, "short") is None
    assert waveform.stored(c, "text") is None
