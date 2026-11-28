"""A waveform's peaks (src/musikata_core/analysis/peaks.py; A5.1, R11.1): generated audio reduced
to 2,000 pairs whatever its length, the bars a view draws from them, and the 16-bit blob the index
keeps.

Why: the waveform is the seek bar; a reduction that drops the end of a song, misplaces a click, or
fails on a song shorter than its slices draws a bar the user seeks by and can't trust."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from musikata_core.analysis import peaks

RATE = 44_100


def sine(seconds, rate=RATE, amplitude=0.5, tone=440.0):
    t = np.arange(round(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * tone * t)).astype(np.float32)


def test_a_sine_is_2000_pairs_at_its_amplitude_either_way():
    got = peaks.peaks(sine(3.0, tone=RATE / 20))  # a period of 20 samples, its crests on samples
    assert got.shape == (peaks.N, 2) and got.dtype == np.float32
    assert np.allclose(got[:, 0], 0.5, atol=1e-3) and np.allclose(got[:, 1], -0.5, atol=1e-3)


def test_silence_is_a_flat_line():
    got = peaks.peaks(np.zeros(RATE * 2, np.float32))
    assert not got.any()
    assert not peaks.bars(got, 100).any()


def test_a_click_lands_in_the_slice_it_is_in_and_no_other():
    x = np.zeros(RATE * 10, np.float32)
    x[RATE * 7] = 0.9  # 7 s into 10: slice 1400
    got = peaks.peaks(x)
    assert got[1400, 0] == pytest.approx(0.9)
    assert np.count_nonzero(got[:, 0]) == 1 and not got[:, 1].any()


def test_a_song_of_one_sample_is_that_sample_all_the_way():
    got = peaks.peaks(np.array([0.25], np.float32))
    assert got.shape == (peaks.N, 2) and np.all(got == 0.25)


def test_a_song_shorter_than_its_slices_repeats_each_sample_in_its_own_slices():
    got = peaks.peaks(np.array([0.1, -0.2, 0.3, -0.4], np.float32), n=8)
    assert got[:, 0].tolist() == pytest.approx([0.1, 0.1, -0.2, -0.2, 0.3, 0.3, -0.4, -0.4])


def test_no_samples_is_a_flat_line_and_no_slices_is_nothing():
    assert not peaks.peaks(np.zeros(0, np.float32)).any()
    assert peaks.peaks(sine(0.1), n=0).shape == (0, 2)


def test_a_song_of_three_hours_is_2000_pairs_its_end_included():
    rate = 1000  # three hours at a low rate: the reduction is the same at any
    n = rate * 3 * 3600
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)  # louder to its very last sample
    got = peaks.peaks(ramp)
    assert got.shape == (peaks.N, 2)
    assert got[-1, 0] == 1.0 and got[0, 1] == 0.0
    assert np.all(np.diff(got[:, 0]) > 0)


def test_pairs_gather_each_hop_and_the_shorter_last():
    x = np.array([0.1, -0.5, 0.3, 0.2, -0.1, 0.9, -0.7], np.float32)
    top, bottom = peaks.pairs(x, 3)
    assert top.tolist() == pytest.approx([0.3, 0.9, -0.7])
    assert bottom.tolist() == pytest.approx([-0.5, -0.1, -0.7])
    assert [len(a) for a in peaks.pairs(np.zeros(0, np.float32), 3)] == [0, 0]


def test_pairs_reduced_are_the_peaks_of_the_samples_when_slices_fall_on_hops():
    x = sine(2.0, rate=8000, tone=3.0) * np.linspace(0, 1, 16000, dtype=np.float32)
    top, bottom = peaks.pairs(x, 8)
    assert np.array_equal(peaks.reduce(top, bottom, 1000), peaks.peaks(x, 1000))


def test_each_bar_is_the_largest_peak_of_its_slices_as_a_share_of_the_loudest():
    waveform = np.zeros((8, 2), np.float32)
    waveform[:, 0] = [0.1, 0.2, 0.05, 0.0, 0.4, 0.1, 0.0, 0.0]
    waveform[:, 1] = [0.0, 0.0, -0.3, 0.0, 0.0, 0.0, -0.8, 0.0]
    assert peaks.bars(waveform, 4).tolist() == pytest.approx([0.25, 0.375, 0.5, 1.0])
    assert peaks.bars(waveform, 0).shape == (0,)
    assert not peaks.bars(np.zeros((0, 2), np.float32), 3).any()


def test_more_bars_than_slices_repeat_them():
    waveform = np.array([[0.5, -0.5], [1.0, 0.0]], np.float32)
    assert peaks.bars(waveform, 4).tolist() == pytest.approx([0.5, 0.5, 1.0, 1.0])


def test_the_blob_is_8_kb_and_reads_back_within_its_step():
    got = peaks.peaks(sine(1.0, amplitude=0.73))
    blob = peaks.to_blob(got)
    assert len(blob) == 8000
    assert np.allclose(peaks.from_blob(blob), got, atol=1 / peaks.FULL)


def test_the_blob_clips_past_full_scale_and_refuses_half_pairs():
    assert peaks.from_blob(peaks.to_blob(np.array([[1.5, -2.0]], np.float32))).tolist() == [
        [1.0, -1.0]
    ]
    with pytest.raises(ValueError, match="not whole pairs"):
        peaks.from_blob(b"\x00\x01\x02")


@pytest.mark.slow
@given(
    hnp.arrays(
        np.float32,
        st.integers(0, 1500),
        elements=st.floats(-1, 1, width=32, allow_nan=False),
    ),
    st.integers(1, 300),
)
def test_every_song_is_n_pairs_each_within_its_samples(samples, n):
    got = peaks.peaks(samples, n)
    assert got.shape == (n, 2)
    if len(samples):
        assert np.all(got[:, 0] >= got[:, 1])
        assert got[:, 0].max() == samples.max() and got[:, 1].min() == samples.min()
    else:
        assert not got.any()
