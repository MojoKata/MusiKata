"""The spectrum of what is playing (src/musikata_core/analysis/spectrum.py; A5.2, R11.3.1,
R11.4.3): bands spaced logarithmically from 32 Hz to 16 kHz, a tone landing in its band, silence
the floor, each band rising at once and falling at a set rate, and the cover's 32 bars gathered
from the bands; and its cost, well under a millisecond a frame.

Why: the spectrum is drawn 30 to 60 times a second on the GUI thread (A5.2, A5.6); a tone in the
wrong band, bars that never settle, or a frame that costs more than its share of 16 ms would show
music that isn't there, or make the window stutter."""

import time

import numpy as np
import pytest

from musikata_core.analysis import spectrum

RATE = 48_000


def tone(hz, seconds=0.2, amplitude=0.5, channels=2, rate=RATE):
    t = np.arange(round(seconds * rate)) / rate
    wave = (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return np.stack([wave] * channels, axis=1)


def band_of(hz, edges, rate=RATE, size=spectrum.SIZE):
    """The band whose bins hold `hz`."""
    b = int(hz * size / rate)
    return int(np.searchsorted(edges, b, side="right") - 1)


def test_the_bands_are_spaced_logarithmically_from_32_hz_to_16_khz_each_a_bin_at_least():
    edges = spectrum.band_edges(96, RATE)
    assert len(edges) == 97 and np.all(np.diff(edges) >= 1)
    assert edges[0] == int(32 * 4096 / RATE) and edges[-1] == int(16_000 * 4096 / RATE)
    hz = edges * RATE / 4096
    upper = hz[60:] / hz[59:-1]  # where the bands are wider than a bin, each a like step up
    assert upper.min() > 1.04 and upper.max() < 1.10
    low = spectrum.band_edges(48, 8_000)  # a low rate: up to its Nyquist, never past it
    assert low[-1] <= 4096 // 2 + 1
    with pytest.raises(ValueError):
        spectrum.band_edges(0, RATE)


@pytest.mark.parametrize("hz", [60.0, 440.0, 1_000.0, 5_000.0, 12_000.0])
def test_a_tone_lands_in_its_band_and_bands_far_from_it_stay_low(hz):
    edges = spectrum.band_edges(96, RATE)
    got = spectrum.frame_levels(tone(hz), edges)
    loudest = int(np.argmax(got))
    assert abs(loudest - band_of(hz, edges)) <= 1
    assert got[loudest] == pytest.approx(1 + 20 * np.log10(0.5) / spectrum.RANGE_DB, abs=0.05)
    far = [i for i in range(96) if abs(i - loudest) > 12]
    assert got[far].max() < 0.25


def test_silence_is_the_floor_and_full_scale_the_top():
    edges = spectrum.band_edges(96, RATE)
    assert not spectrum.frame_levels(np.zeros((4096, 2), np.float32), edges).any()
    assert spectrum.frame_levels(tone(1_000, amplitude=1.0), edges).max() == pytest.approx(
        1.0, abs=0.02
    )
    quiet = spectrum.frame_levels(tone(1_000, amplitude=10 ** (-70 / 20)), edges)
    assert not quiet.any()  # 70 dB down: under the 60 dB shown


def test_a_frame_of_fewer_samples_than_it_takes_is_silence_before_them():
    edges = spectrum.band_edges(32, RATE)
    short = spectrum.frame_levels(tone(1_000, seconds=0.02), edges)
    assert int(np.argmax(short)) == band_of(1_000, edges)
    assert spectrum.mono(np.array([0.5, -0.5], np.float32)).tolist() == [0.5, -0.5]


def test_each_band_rises_at_once_and_falls_at_its_set_rate():
    s = spectrum.Spectrum(96, RATE)
    assert s.settled
    up = s.frame(tone(1_000), 1 / 60)
    top = up.max()
    assert top > 0.85 and not s.settled
    step = spectrum.FALL_DB / spectrum.RANGE_DB / 60
    down = s.frame(None, 1 / 60)
    assert down.max() == pytest.approx(top - step, abs=1e-5)
    s.frame(np.zeros((0, 2), np.float32), 0.25)  # nothing held: silence too
    assert s.levels.max() == pytest.approx(top - step - 0.25 * spectrum.FALL_DB / 60, abs=1e-5)
    frames = 0
    while not s.settled:
        s.frame(None, 1 / 30)
        frames += 1
    assert frames <= 30 * spectrum.RANGE_DB / spectrum.FALL_DB  # settled in under a second
    assert s.frame(tone(1_000), 0).max() == pytest.approx(top)  # back up at once


def test_the_covers_32_bars_are_the_bands_gathered_each_the_loudest_of_its_group():
    gathered = spectrum.gather(np.arange(96, dtype=np.float32) / 96, 32)
    assert len(gathered) == 32 and gathered[0] == pytest.approx(2 / 96)
    assert gathered[-1] == pytest.approx(95 / 96)
    assert spectrum.gather(np.ones(3, np.float32), 4).tolist() == [1.0, 1.0, 1.0, 0.0]
    cover = spectrum.Spectrum(96, RATE, bars=spectrum.COVER_BARS)
    got = cover.frame(tone(1_000), 1 / 30)
    assert (
        len(got) == 32 and int(np.argmax(got)) == band_of(1_000, spectrum.band_edges(96, RATE)) // 3
    )


def test_a_new_rate_moves_the_bands_edges():
    s = spectrum.Spectrum(48, 44_100)
    s.set_rate(96_000)
    assert s.rate == 96_000
    got = s.frame(tone(5_000, rate=96_000), 1 / 60)
    assert abs(int(np.argmax(got)) - band_of(5_000, spectrum.band_edges(48, 96_000), 96_000)) <= 1


def test_more_bands_than_bins_leave_the_empty_ones_at_the_floor():
    edges = np.array([0, 2, 2, 5], np.intp)
    got = spectrum.bands(np.arange(8, dtype=np.float32), edges)
    assert got.tolist() == [1.0, 0.0, 4.0]


def test_a_frame_costs_well_under_a_millisecond():
    """A5.2's promise, measured: the best of three runs of 50 frames, a 96-band frame of stereo
    samples; generous, so a busy machine passes, yet far over what NumPy takes."""
    s = spectrum.Spectrum(96, RATE)
    block = tone(1_000, seconds=4096 / RATE)
    best = min(_timed(s, block) for _ in range(3))
    assert best < 1e-3, f"{best * 1e3:.3f} ms a frame"


def _timed(s, block, n=50):
    start = time.perf_counter()
    for _ in range(n):
        s.frame(block, 1 / 60)
    return (time.perf_counter() - start) / n
