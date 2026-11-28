"""A waveform's peaks (A5.1, R11.1): a song's samples reduced to `N` pairs, the largest and the
smallest sample of each of `N` equal slices, whatever the song's length; the bars a view draws
from them, each the largest peak of the slices under it; and the pairs as the index keeps them, a
16-bit blob (8 KB a song).

Plain NumPy over plain arrays: decoding a file only feeds it (waveform.py)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

N = 2000  # pairs a song's waveform holds: a 1920-pixel view at two bars a pixel or fewer (A5.1)
FULL = 32767  # the blob's full scale

Samples = NDArray[np.float32]
Peaks = NDArray[np.float32]  # N rows of (largest, smallest)


def reduce(maxima: Samples, minima: Samples, n: int = N) -> Peaks:
    """`n` pairs from pairs already reduced (or samples, given as both): pair i the largest of
    `maxima` and the smallest of `minima` over the i-th of `n` equal slices. With fewer than `n`
    given, a slice too short to hold one holds the one it starts in, so a song of one sample is
    `n` copies of it; with none, every pair is 0 (a flat line)."""
    length = min(len(maxima), len(minima))
    out = np.zeros((max(0, n), 2), np.float32)
    if not length or n <= 0:
        return out
    starts = (np.arange(n, dtype=np.int64) * length) // n
    out[:, 0] = np.maximum.reduceat(np.asarray(maxima[:length], np.float32), starts)
    out[:, 1] = np.minimum.reduceat(np.asarray(minima[:length], np.float32), starts)
    return out


def peaks(samples: Samples, n: int = N) -> Peaks:
    """A song's mono samples as `n` peak pairs: the largest and smallest sample of each of `n`
    equal slices (A5.1)."""
    return reduce(samples, samples, n)


def pairs(samples: Samples, hop: int) -> tuple[Samples, Samples]:
    """The largest and smallest sample of each `hop` samples, the last group shorter when they
    don't divide evenly: the fine pairs a long song is gathered into as it decodes."""
    if not len(samples):
        empty = np.zeros(0, np.float32)
        return empty, empty.copy()
    starts = np.arange(0, len(samples), max(1, hop))
    data = np.asarray(samples, np.float32)
    return np.maximum.reduceat(data, starts), np.minimum.reduceat(data, starts)


def bars(waveform: Peaks, count: int) -> Samples:
    """The heights, 0 to 1, of the `count` bars a view draws (A5.1): each the largest peak, above
    or below the centre line, of the slices under it, as a share of the song's largest, so a
    quietly mastered song fills the view as a loud one does. A flat waveform's bars are 0."""
    if count <= 0:
        return np.zeros(0, np.float32)
    if not len(waveform):
        return np.zeros(count, np.float32)
    loudness = np.clip(np.maximum(waveform[:, 0], -waveform[:, 1]), 0.0, 1.0)
    starts = (np.arange(count, dtype=np.int64) * len(loudness)) // count
    heights = np.maximum.reduceat(loudness, starts).astype(np.float32)
    top = float(heights.max())
    return heights / top if top > 0 else heights


def to_blob(waveform: Peaks) -> bytes:
    """The pairs as the index keeps them: little-endian 16-bit, largest then smallest, at full
    scale 1.0 (what is past it clipped)."""
    scaled = np.round(np.clip(waveform, -1.0, 1.0) * FULL)
    return scaled.astype("<i2").tobytes()


def from_blob(blob: bytes) -> Peaks:
    """The pairs `to_blob` gave. Raises ValueError on bytes that aren't whole pairs."""
    if len(blob) % 4:
        raise ValueError(f"a waveform of {len(blob)} bytes: not whole pairs")
    values = np.frombuffer(blob, "<i2").astype(np.float32) / np.float32(FULL)
    return values.astype(np.float32).reshape(-1, 2)
