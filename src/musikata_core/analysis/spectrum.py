"""The spectrum of what is playing (A5.2): each frame, the newest 4,096 samples mixed to mono, a
Hann window, NumPy's `rfft`, and the magnitudes gathered into bands spaced logarithmically from
32 Hz to 16 kHz, each band the largest magnitude in its range (which keeps the low bands, a few
bins wide, from looking empty), in dB, clamped to a 60 dB range and given as a level from 0 (the
floor) to 1 (full scale). Each band rises at once and falls at a set rate (`Spectrum`), so what is
drawn doesn't flicker. The cover's 32 bars (R11.4.3, A5.6) are the bands gathered (`gather`).

Plain NumPy, no Qt: the samples come from the analyzer's ring buffer (A4.3,
musikata_core.audio.stream.Recent), and the time between frames from the view that draws them."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

SIZE = 4096  # samples a frame takes (A5.2)
LOW, HIGH = 32.0, 16_000.0  # the bands' range, in Hz (R11.3.1)
RANGE_DB = 60.0  # what is shown below full scale (A5.2)
FALL_DB = 90.0  # how fast a band falls, in dB a second: a full bar in two thirds of a second
BANDS = 96  # the analyzer's bands by default (R11.3.1, R13.8)
COVER_BARS = 32  # the cover's bars (R11.4.3)

Levels = NDArray[np.float32]


def band_edges(count: int, rate: int, size: int = SIZE) -> NDArray[np.intp]:
    """The `count` bands' edges as FFT bins at `rate` Hz: `count + 1` of them, spaced
    logarithmically from LOW to HIGH (HIGH kept under the rate's Nyquist), each band at least one
    bin wide, so a low band a fraction of a bin wide still holds the bin its frequencies fall in."""
    if count < 1 or rate <= 0:
        raise ValueError(f"{count} bands at {rate} Hz")
    bins = size // 2 + 1
    high = min(HIGH, rate / 2)
    hz = np.geomspace(LOW, high, count + 1)
    edges = np.floor(hz * size / rate).astype(np.intp)
    for i in range(1, count + 1):  # at least a bin each, from the lowest up
        edges[i] = max(edges[i], edges[i - 1] + 1)
    return np.minimum(edges, bins)


def mono(block: NDArray[np.float32]) -> NDArray[np.float32]:
    """Frames × channels mixed to one channel, each frame the mean of its channels."""
    if block.ndim == 1:
        return block.astype(np.float32, copy=False)
    return block.mean(axis=1, dtype=np.float32)


_windows: dict[int, NDArray[np.float32]] = {}


def _window(size: int) -> NDArray[np.float32]:
    """The Hann window of `size` points, made once a size."""
    if size not in _windows:
        _windows[size] = np.hanning(size).astype(np.float32)
    return _windows[size]


def magnitudes(samples: NDArray[np.float32]) -> NDArray[np.float32]:
    """The magnitude of each FFT bin of `samples` (one channel) under a Hann window, as a share
    of full scale: a full-scale sine's bin is 1."""
    size = len(samples)
    spectrum = np.fft.rfft(samples * _window(size))
    return (np.abs(spectrum) * (4.0 / size)).astype(np.float32)


def bands(mags: NDArray[np.float32], edges: NDArray[np.intp]) -> NDArray[np.float32]:
    """Each band's largest magnitude: band i holds bins `edges[i]` up to `edges[i + 1]`."""
    if len(edges) > 1 and bool(np.all(np.diff(edges) > 0)) and edges[-1] <= len(mags):
        return np.maximum.reduceat(mags[: edges[-1]], edges[:-1]).astype(np.float32)
    out = np.zeros(max(0, len(edges) - 1), np.float32)  # bands of no bins: more bands than bins
    for i in range(len(out)):
        lo, hi = int(edges[i]), min(int(edges[i + 1]), len(mags))
        if hi > lo:
            out[i] = mags[lo:hi].max()
    return out


def levels(band_mags: NDArray[np.float32]) -> Levels:
    """Magnitudes as levels: in dB below full scale, the RANGE_DB under it mapped to 0 to 1, and
    what is quieter the floor (0)."""
    db = 20.0 * np.log10(np.maximum(band_mags, 1e-12))
    return np.clip((db + RANGE_DB) / RANGE_DB, 0.0, 1.0).astype(np.float32)


def gather(values: Levels, count: int) -> Levels:
    """`values` gathered into `count` groups from low to high, each the largest of its group
    (R11.4.3's 32 bars from R11.3.1's bands)."""
    groups = np.array_split(np.asarray(values, np.float32), count)
    return np.array([g.max() if len(g) else 0.0 for g in groups], np.float32)


def frame_levels(block: NDArray[np.float32], edges: NDArray[np.intp], size: int = SIZE) -> Levels:
    """One frame's levels from `block` (frames × channels, or one channel): its newest `size`
    frames, mixed to mono, with silence before them when it holds fewer."""
    samples = mono(block)[-size:]
    if len(samples) < size:
        samples = np.concatenate([np.zeros(size - len(samples), np.float32), samples])
    return levels(bands(magnitudes(samples), edges))


class Spectrum:
    """The levels a view draws, frame by frame: `count` bands at `rate` Hz, each rising at once to
    what a frame finds and falling at `fall_db` dB a second (A5.2); gathered into `bars` when
    given (the cover's 32)."""

    def __init__(
        self, count: int = BANDS, rate: int = 48_000, fall_db: float = FALL_DB, bars: int = 0
    ) -> None:
        self.count, self.bars, self.fall = count, bars, fall_db / RANGE_DB
        self.rate = 0
        self._edges = np.zeros(0, np.intp)
        self.set_rate(rate)
        self._levels = np.zeros(bars or count, np.float32)

    def set_rate(self, rate: int) -> None:
        """The samples' rate from now on (the device's: a song moved to another device)."""
        if rate != self.rate:
            self.rate = rate
            self._edges = band_edges(self.count, rate)

    @property
    def levels(self) -> Levels:
        """What the view draws now, 0 to 1 a band."""
        return self._levels.copy()

    @property
    def settled(self) -> bool:
        """Every band has fallen to the floor."""
        return not self._levels.any()

    def frame(self, block: NDArray[np.float32] | None, seconds: float) -> Levels:
        """The levels after a frame `seconds` after the last: `block` the samples heard (frames ×
        channels), or None for silence (paused: the bars settle)."""
        if block is None or not len(block):
            found = np.zeros(self.count, np.float32)
        else:
            found = frame_levels(block, self._edges)
        if self.bars:
            found = gather(found, self.bars)
        fallen = self._levels - self.fall * max(0.0, seconds)
        self._levels = np.maximum(found, np.maximum(fallen, 0.0)).astype(np.float32)
        return self.levels
