"""Gain (A4.4): ReplayGain (R7.5), a multiplication limited by the peak so it never clips; the
ramp that changes it at the join between two songs without a click (R7.6.1, A4.2); and the volume,
applied last, ramped the same way. Plain functions over numbers and arrays, with no Qt, device or
clock in them (docs/process/coding.md), shown on generated blocks.

Which gain a song gets is decided as it is put in the stream: Album when the album is played in
order (`in_album_order`), the track's otherwise, and R7.5's pre-amp for a song without ReplayGain
tags. Where it plays in the stream, from its first frame, is a `Step`; `gains` gives each frame's
gain from the steps, ramping from the song before's over RAMP_SECONDS. The equalizer (R19) comes
after ReplayGain and before the volume (A4.4)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .stream import Block

RAMP_SECONDS = 0.05  # a change of gain at a join, or of the volume, is ramped over this (A4.2)
MODES = ("album", "track", "off")  # R7.5's ReplayGain, as settings.Playback names them
UNTAGGED_DB = -6.0  # R7.5's pre-amp for songs without ReplayGain tags


@dataclass(frozen=True)
class Loudness:
    """A song's ReplayGain tags as the index has them (A3.2): gains in dB, peaks as a fraction of
    full scale; None where the file has none."""

    track_gain: float | None = None
    track_peak: float | None = None
    album_gain: float | None = None
    album_peak: float | None = None


@dataclass(frozen=True)
class AlbumPlace:
    """A song's album, by its id, and its place in the album's order (disc, then track)."""

    album: int
    index: int


def in_album_order(
    before: AlbumPlace | None, song: AlbumPlace | None, after: AlbumPlace | None
) -> bool:
    """Whether `song` is played as part of its album in order (R7.5): the song before it in the
    stream is the album's song before it, or the song after it in the queue is the album's song
    after it. So an album played from any of its songs on is in order from the first; a song
    alone, shuffled, or among other albums' songs isn't."""
    if song is None:
        return False
    return (before is not None and before == AlbumPlace(song.album, song.index - 1)) or (
        after is not None and after == AlbumPlace(song.album, song.index + 1)
    )


def factor(db: float) -> float:
    """A gain in dB as the multiplier of the samples: 10^(dB/20)."""
    return float(10 ** (db / 20))


def _usable(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def replaygain(
    loudness: Loudness, mode: str, in_order: bool, untagged_db: float = UNTAGGED_DB
) -> float:
    """The multiplier ReplayGain gives a song (R7.5, A4.4): with `mode` "album" and the album
    played in order (`in_order`), its album gain, else its track gain, either standing in for
    the other when the file has only one; `untagged_db` for a song with neither; 1 with "off".
    It is held to 1 / the peak, so a peak of the song never goes past full scale, and to 1 when
    the peak isn't known (an Opus file's R128_* gains carry none)."""
    if mode not in MODES:
        raise ValueError(f"no such ReplayGain mode: {mode!r}")
    if mode == "off":
        return 1.0
    album = (loudness.album_gain, loudness.album_peak or loudness.track_peak)
    track = (loudness.track_gain, loudness.track_peak or loudness.album_peak)
    for gain, peak in (album, track) if mode == "album" and in_order else (track, album):
        if gain is not None and _usable(gain):
            limit = 1 / peak if peak is not None and _usable(peak) and peak > 0 else 1.0
            return min(factor(gain), limit)
    return min(factor(untagged_db), 1.0)


@dataclass(frozen=True)
class Step:
    """A song's gain in the stream: from the place of its first frame on, `gain`; when `start` is
    given, ramped there from `start` over the ramp's frames (the gain of the song before)."""

    place: int
    gain: float
    start: float | None = None


def ramped(start: float, end: float, offset: int, frames: int, ramp: int) -> NDArray[np.float32]:
    """The gains of `frames` frames from `offset` frames into a ramp of `ramp` frames from `start`
    to `end`: a straight line, so no frame's gain differs from the one before by more than
    |end - start| / ramp; `end` past it."""
    k = np.arange(offset, offset + frames, dtype=np.float64)
    t = np.clip((k + 1) / max(1, ramp), 0.0, 1.0)  # its first frame is a step in already
    return (start + (end - start) * t).astype(np.float32)


def gains(place: int, frames: int, steps: Sequence[Step], ramp: int) -> NDArray[np.float32]:
    """The gain of each of `frames` frames of the stream from place `place`, from `steps` in the
    order of their places: each step's from its place until the next one's, the first's before
    it too; ramped over `ramp` frames where a step says what it starts from."""
    out = np.ones(frames, np.float32)
    for i, step in enumerate(steps):
        lo = 0 if i == 0 else min(frames, max(0, step.place - place))
        hi = frames if i + 1 == len(steps) else min(frames, max(0, steps[i + 1].place - place))
        if lo >= hi:
            continue
        offset = place + lo - step.place
        if step.start is None or step.start == step.gain or offset >= ramp:
            out[lo:hi] = step.gain
        else:
            out[lo:hi] = ramped(step.start, step.gain, max(0, offset), hi - lo, ramp)
    return out


def gain_at(place: int, steps: Sequence[Step], ramp: int) -> float:
    """The gain of the frame at `place`: where a ramp from it starts."""
    return float(gains(place, 1, steps, ramp)[0])


def apply(block: Block, by: NDArray[np.float32] | float) -> Block:
    """`block` with each frame multiplied by its gain (one for all, or one per frame)."""
    if isinstance(by, float):
        return block if by == 1.0 else (block * np.float32(by)).astype(np.float32)
    if np.all(by == 1.0):
        return block
    return (block * by[:, None]).astype(np.float32)


class Volume:
    """The volume (A4.4), applied last to what the device takes: a level from 0 to 1, multiplied
    in; a new level is ramped to over `ramp` frames from the level reached, so moving it makes no
    zipper noise.

    `set` runs on the playback thread and `apply` on the device's: `set` only stores the level
    asked for, in one assignment, and `apply` starts the ramp to it, so no state is changed from
    two threads (docs/process/coding.md)."""

    def __init__(self, level: float = 1.0, ramp: int = 1) -> None:
        self.ramp = max(1, ramp)
        self._from = self._to = self._asked = level
        self._at = self.ramp  # frames into the ramp

    @property
    def level(self) -> float:
        """The level it goes to."""
        return self._asked

    @property
    def now(self) -> float:
        """The level of the next frame's gain's start: where a new ramp starts from."""
        if self._at >= self.ramp:
            return self._to
        return self._from + (self._to - self._from) * self._at / self.ramp

    def set(self, level: float) -> None:
        """Moves to `level`, ramped from where it is when the next frames are taken."""
        self._asked = level

    def apply(self, block: Block) -> Block:
        """The next frames, each multiplied by its level."""
        asked = self._asked
        if asked != self._to:
            self._from, self._to, self._at = self.now, asked, 0
        n = len(block)
        if self._at >= self.ramp:
            return apply(block, float(self._to))
        by = ramped(self._from, self._to, self._at, n, self.ramp)
        self._at = min(self.ramp, self._at + n)
        return apply(block, by)
