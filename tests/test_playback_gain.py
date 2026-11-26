"""Gain (src/musikata_core/audio/gain.py; R7.5, R7.6.1, A4.2, A4.4): which ReplayGain a song gets,
held under its peak, the ramps a gain and the volume change by, and the album played in order.
Plain numbers and generated blocks; joins carrying the gain are tests/test_playback_join.py's.

Why: a gain that clips, a level that jumps between two songs of one album, or a volume that steps
are each heard as damage to the music, and only by listening for it."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core.audio import gain

TAGGED = gain.Loudness(track_gain=-7.5, track_peak=0.8, album_gain=-6.0, album_peak=0.95)


def db(x):
    return 20 * np.log10(x)


def test_album_is_the_album_gain_in_order_and_the_track_gain_otherwise():
    assert db(gain.replaygain(TAGGED, "album", True)) == pytest.approx(-6.0)
    assert db(gain.replaygain(TAGGED, "album", False)) == pytest.approx(-7.5)
    assert db(gain.replaygain(TAGGED, "track", True)) == pytest.approx(-7.5)
    assert gain.replaygain(TAGGED, "off", True) == 1.0


def test_a_song_with_one_gain_uses_it_whichever_is_asked_for():
    only_track = gain.Loudness(track_gain=-3.0, track_peak=0.5)
    only_album = gain.Loudness(album_gain=-4.0, album_peak=0.5)
    assert db(gain.replaygain(only_track, "album", True)) == pytest.approx(-3.0)
    assert db(gain.replaygain(only_album, "track", False)) == pytest.approx(-4.0)


def test_a_song_without_replaygain_plays_at_the_pre_amp():
    assert db(gain.replaygain(gain.Loudness(), "album", True)) == pytest.approx(-6.0)
    assert db(gain.replaygain(gain.Loudness(), "track", False, -9.0)) == pytest.approx(-9.0)
    assert gain.replaygain(gain.Loudness(), "track", False, 4.0) == 1.0  # never above full scale
    assert gain.replaygain(gain.Loudness(), "off", False) == 1.0


def test_a_gain_is_held_under_the_peak_so_it_never_clips():
    loud = gain.Loudness(track_gain=+8.0, track_peak=0.6, album_gain=+8.0, album_peak=0.9)
    assert gain.replaygain(loud, "track", False) == pytest.approx(1 / 0.6)
    assert gain.replaygain(loud, "album", True) == pytest.approx(1 / 0.9)
    no_album_peak = gain.Loudness(track_gain=0.0, track_peak=0.5, album_gain=9.0)
    assert gain.replaygain(no_album_peak, "album", True) == pytest.approx(2.0)  # the track's
    no_peak = gain.Loudness(track_gain=+3.0)  # an Opus file's R128_TRACK_GAIN
    assert gain.replaygain(no_peak, "track", False) == 1.0
    assert db(gain.replaygain(gain.Loudness(track_gain=-3.0), "track", False)) == pytest.approx(-3)
    broken = gain.Loudness(track_gain=-2.0, track_peak=float("nan"))
    assert db(gain.replaygain(broken, "track", False)) == pytest.approx(-2.0)


def test_a_gain_that_isnt_a_number_is_passed_over():
    odd = gain.Loudness(track_gain=float("inf"), album_gain=-5.0, album_peak=0.5)
    assert db(gain.replaygain(odd, "track", False)) == pytest.approx(-5.0)
    with pytest.raises(ValueError, match="no such ReplayGain mode"):
        gain.replaygain(TAGGED, "smart", True)


@given(
    st.floats(-30, 30),
    st.one_of(st.none(), st.floats(0.01, 2.0)),
    st.sampled_from(gain.MODES),
    st.booleans(),
)
def test_no_gain_takes_a_peak_past_full_scale(db_, peak, mode, in_order):
    loudness = gain.Loudness(db_, peak, db_, peak)
    g = gain.replaygain(loudness, mode, in_order)
    assert g * (peak if peak is not None else 1.0) <= 1.0 + 1e-9 or mode == "off"


# ---------- the album in order ----------


def test_an_album_is_in_order_from_any_of_its_songs_on_and_a_song_alone_isnt():
    first, second, third = (gain.AlbumPlace(7, i) for i in range(3))
    assert gain.in_album_order(None, first, second)  # Play on the album
    assert gain.in_album_order(first, second, third) and gain.in_album_order(second, third, None)
    assert gain.in_album_order(None, second, third)  # played from its second song on
    assert not gain.in_album_order(None, second, None)  # alone
    assert not gain.in_album_order(third, first, gain.AlbumPlace(9, 1))  # shuffled
    assert not gain.in_album_order(gain.AlbumPlace(8, 0), second, gain.AlbumPlace(8, 2))
    assert not gain.in_album_order(second, second, second)  # repeat One
    assert not gain.in_album_order(first, None, second)  # not in an album


# ---------- ramps ----------


def test_a_ramp_runs_straight_from_one_gain_to_the_other_over_its_frames():
    r = gain.ramped(1.0, 0.5, 0, 6, 4)
    assert np.allclose(r, [0.875, 0.75, 0.625, 0.5, 0.5, 0.5])
    assert np.allclose(gain.ramped(1.0, 0.5, 2, 2, 4), [0.625, 0.5])


def test_each_frame_takes_its_steps_gain_and_a_step_ramps_from_the_one_before():
    steps = [gain.Step(0, 1.0), gain.Step(10, 0.5, 1.0), gain.Step(20, 2.0, 0.5)]
    g = gain.gains(5, 20, steps, ramp=4)
    assert np.allclose(g[:5], 1.0) and np.allclose(g[5:9], [0.875, 0.75, 0.625, 0.5])
    assert np.allclose(g[9:15], 0.5) and np.allclose(g[15:19], [0.875, 1.25, 1.625, 2.0])
    assert gain.gain_at(-3, steps, 4) == 1.0 and gain.gain_at(100, steps, 4) == 2.0
    assert np.allclose(gain.gains(0, 3, [gain.Step(5, 0.25)], 4), 0.25)  # the first, before it
    assert np.allclose(gain.gains(12, 3, steps, 4), [0.625, 0.5, 0.5])  # from inside a ramp


@given(
    st.floats(0.0, 4.0),
    st.floats(0.0, 4.0),
    st.integers(1, 3000),
    st.integers(0, 200),
    st.integers(1, 500),
)
def test_no_frame_of_a_ramp_steps_more_than_its_slope_allows(start, end, ramp, place, frames):
    steps = [gain.Step(0, start), gain.Step(100, end, start)]
    g = gain.gains(place, frames, steps, ramp).astype(np.float64)
    whole = np.concatenate([[start], gain.gains(0, place + frames, steps, ramp)])
    slope = abs(end - start) / ramp
    assert np.abs(np.diff(whole)).max(initial=0) <= slope * (1 + 1e-5) + 1e-6
    assert np.allclose(g, whole[1 + place :], atol=1e-6)


def test_applying_a_gain_multiplies_each_frame_by_its_own():
    block = np.ones((3, 2), np.float32)
    assert gain.apply(block, 1.0) is block
    assert np.allclose(gain.apply(block, 0.5), 0.5)
    assert gain.apply(block, np.ones(3, np.float32)) is block
    out = gain.apply(block, np.array([1.0, 0.5, 0.0], np.float32))
    assert out.dtype == np.float32 and np.allclose(out[:, 1], [1.0, 0.5, 0.0])


# ---------- the volume ----------


def test_the_volume_ramps_to_a_new_level_and_holds_it():
    v = gain.Volume(1.0, ramp=4)
    block = np.ones((3, 2), np.float32)
    assert v.apply(block) is block and v.now == 1.0
    v.set(0.0)
    assert v.level == 0.0 and v.now == 1.0  # asked for; the ramp starts as the device takes
    assert np.allclose(v.apply(block)[:, 0], [0.75, 0.5, 0.25]) and v.now == pytest.approx(0.25)
    assert np.allclose(v.apply(block)[:, 0], [0.0, 0.0, 0.0]) and v.level == 0.0
    v.set(0.0)  # the same: nothing
    assert np.allclose(v.apply(block), 0.0)


def test_a_volume_moved_again_mid_ramp_ramps_on_from_where_it_had_got_to():
    v = gain.Volume(0.0, ramp=4)
    block = np.ones((2, 1), np.float32)
    v.set(1.0)
    assert np.allclose(v.apply(block)[:, 0], [0.25, 0.5])
    v.set(0.0)
    assert np.allclose(v.apply(np.ones((4, 1), np.float32))[:, 0], [0.375, 0.25, 0.125, 0.0])
    assert gain.Volume(0.5, ramp=0).ramp == 1


@given(st.lists(st.tuples(st.floats(0.0, 1.0), st.integers(1, 300)), min_size=1, max_size=8))
def test_a_volume_dragged_about_never_steps_more_than_its_ramp_allows(moves):
    ramp = 100
    v = gain.Volume(1.0, ramp=ramp)
    heard = [np.ones(1)]
    for level, frames in moves:
        v.set(level)
        heard.append(v.apply(np.ones((frames, 1), np.float32))[:, 0])
    assert np.abs(np.diff(np.concatenate(heard))).max() <= 1.0 / ramp + 1e-6
