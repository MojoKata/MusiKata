"""The stream the sound device pulls from (src/musikata_core/audio/stream.py; A4.1): the ring buffer
of about two seconds, filled in blocks of about 20 ms and read on the device's schedule.

Why: the device reads whatever it finds there, in whatever sizes it asks for. A frame lost, doubled
or reordered at the ring's seam is a click on every lap; a ring that says it has room it hasn't
loses the song's samples; and a song whose end is missed never stops."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core.audio import stream


def frames(start, n, channels=2):
    """n frames numbered from start: frame i holds i in its first channel, -i in its second."""
    i = np.arange(start, start + n, dtype=np.float32)
    return np.stack([i, -i][:channels], axis=1)


def test_seconds_become_frames_at_the_rate_and_never_none():
    assert stream.frames_of(0.02, 44100) == 882
    assert stream.frames_of(0.02, 48000) == 960
    assert stream.frames_of(2.0, 96000) == 192_000
    assert stream.frames_of(0.0, 44100) == 1


def test_a_block_goes_to_the_device_as_little_endian_floats_interleaved():
    block = np.array([[0.5, -0.5], [1.0, 0.25]], np.float32)
    assert stream.to_bytes(block) == np.array([0.5, -0.5, 1.0, 0.25], "<f4").tobytes()
    assert stream.to_bytes(stream.silence(3, 2)) == bytes(24)


def test_the_ring_gives_back_what_was_written_in_order_across_its_seam():
    ring = stream.Ring(10, 2)
    assert ring.capacity == 10 and ring.channels == 2 and ring.free == 10 and ring.held == 0
    assert ring.write(frames(0, 7)) == 7
    assert np.array_equal(ring.read(5), frames(0, 5))
    assert ring.write(frames(7, 8)) == 8  # wraps: 3 at the end, 5 at the start
    assert ring.held == 10 and ring.free == 0
    assert np.array_equal(ring.read(10), frames(5, 10))
    assert ring.held == 0 and ring.read(4).shape == (0, 2)


def test_a_full_ring_takes_only_what_fits_and_a_read_only_what_is_held():
    ring = stream.Ring(4, 1)
    assert ring.write(frames(0, 6, 1)) == 4
    assert np.array_equal(ring.read(9), frames(0, 4, 1))
    ring.write(frames(0, 3, 1))
    ring.clear()
    assert ring.held == 0 and ring.free == 4


def test_a_ring_refuses_blocks_of_the_wrong_shape_and_sizes_that_cant_hold_any():
    ring = stream.Ring(4, 2)
    with pytest.raises(ValueError, match="for 2 channels"):
        ring.write(frames(0, 2, 1))
    with pytest.raises(ValueError, match="for 2 channels"):
        ring.write(np.zeros(4, np.float32))
    with pytest.raises(ValueError):
        stream.Ring(0, 2)
    with pytest.raises(ValueError):
        stream.Ring(4, 0)


@given(st.lists(st.tuples(st.integers(0, 40), st.integers(0, 40)), max_size=30))
def test_whatever_the_sizes_written_and_read_every_frame_comes_out_once_in_order(steps):
    ring = stream.Ring(32, 2)
    written = taken = 0
    for write, read in steps:
        written += ring.write(frames(written, write))
        out = ring.read(read)
        assert np.array_equal(out, frames(taken, len(out)))
        taken += len(out)
        assert ring.held == written - taken and ring.held + ring.free == 32


def test_the_stream_decodes_only_what_the_ring_has_room_for_a_few_blocks_at_a_time():
    s = stream.Stream(1000, 2, ahead=0.1)  # 100 frames, blocks of 20
    assert s.block == 20 and s.ring.capacity == 100
    assert s.wants() == stream.STEP_BLOCKS and s.wants(step=99) == 5
    for n in range(4):
        s.feed(frames(n * 20, 20))
    assert s.wants() == 1
    s.feed(frames(80, 20))
    assert s.wants() == 0
    with pytest.raises(OverflowError):
        s.feed(frames(100, 1))


def test_the_device_takes_what_is_there_and_a_short_ring_before_the_end_is_counted():
    s = stream.Stream(1000, 2, ahead=0.1)
    s.feed(frames(0, 30))
    assert np.array_equal(s.take(25), frames(0, 25))
    assert len(s.take(25)) == 5 and s.short == 1 and s.taken == 30
    assert not s.drained


def test_the_song_is_drained_once_the_decoder_finished_and_the_device_took_the_last_frame():
    s = stream.Stream(1000, 1, ahead=0.1)
    s.feed(frames(0, 10, 1))
    s.finish()
    assert s.wants() == 0 and not s.drained
    assert len(s.take(64)) == 10 and s.short == 0  # short at the end is the end, not a shortfall
    assert s.drained and s.taken == 10


# ---------- the analyzer's ring (A4.3) ----------


def test_the_analyzer_ring_gives_what_the_device_played_last_by_its_place():
    recent = stream.Recent(seconds=0.01)  # 10 frames at 1 kHz
    recent.start(1000, 2)
    assert recent.rate == 1000 and recent.newest(4) is None  # nothing held
    recent.add(frames(0, 6), 0)
    assert recent.newest(4) is None  # wanted by no view: nothing copied (A5.5)
    view = object()
    recent.want(view, True)
    assert recent.on
    recent.add(frames(0, 6), 0)
    recent.add(frames(6, 6), 6)  # past its ten frames: the oldest two gone
    recent.hear(9)  # the device has played up to frame 9
    assert recent.newest(4)[:, 0].tolist() == [5, 6, 7, 8]
    assert recent.newest(12)[:, 0].tolist() == [0] * 5 + [2, 3, 4, 5, 6, 7, 8]  # silence before
    recent.hear(50)  # past what was copied: up to the newest held
    assert recent.newest(2)[:, 0].tolist() == [10, 11]
    recent.add(frames(0, 3, channels=1), 12)  # another stream's: not taken
    recent.add(frames(0, 0), 12)
    assert recent.newest(1)[:, 0].tolist() == [11]
    recent.want(view, False)
    assert not recent.on


def test_after_a_gap_the_analyzer_ring_holds_only_what_came_after_it():
    recent = stream.Recent(seconds=0.01)
    recent.start(1000, 2)
    recent.want("cover", True)
    recent.add(frames(0, 8), 0)
    recent.add(frames(20, 4), 20)  # nothing copied from 8 to 20 (no view wanted it)
    recent.hear(24)
    assert recent.newest(6)[:, 0].tolist() == [0, 0, 20, 21, 22, 23]
    recent.hear(10)  # a place it no longer holds
    assert recent.newest(2) is None
    recent.start(1000, 2)  # a new song: nothing held, still wanted
    assert recent.on and recent.newest(2) is None
