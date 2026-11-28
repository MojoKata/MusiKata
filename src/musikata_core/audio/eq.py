"""The equalizer's sound (A4.4, R19.1): the bands' responses, the one filter they make, and that
filter applied to the stream with its crossfades, its headroom and its limiter. Plain NumPy, no
Qt, device or clock (docs/process/coding.md), shown on generated blocks; the presets it plays are
presets.py's.

- **The bands** (`Band`): each one's response is the Audio EQ Cookbook's biquad of its type
  (`response_db`), and a preset's curve is their sum, in dB (`curve_db`).
- **The filter** (`design`): the curve, with the preamp and the level held down by the headroom,
  on a fine grid (four times the filter's length), made one minimum-phase FIR by its cepstrum, so
  it adds no delay: 16,384 taps at 44.1 and 48 kHz, twice that up to 96 kHz, and so on.
- **Never clipping** (R19.1): when the preamp plus the curve's largest boost is above 0 dB, the
  level is held down by the difference (`headroom`), built into the filter, so a change of it is
  crossfaded with the filter. A look-ahead peak limiter of 5 ms then catches what the filter's
  phase still pushes past full scale.
- **Applying it** (`Equalizer`): block by block with NumPy's FFT, the filter cut into sixteen
  parts and each block's spectrum kept for the parts after it (uniformly partitioned overlap-save,
  the overlap-add of A4.4 done a part at a time), so a block costs two short FFTs, whatever its
  length. What it is given is kept for a while, so a change can be heard at once: the stream is
  taken back to where the device has got to and what was given from there is filtered again
  (`retune`), the old filter crossfaded into the new over 50 ms; a change at a song's join is
  crossfaded there (`schedule`, R7.6.1).
- **Off** passes the samples untouched and holds nothing back. On, the limiter's look-ahead holds
  the last 5 ms given until what follows them is known, or until the stream ends (`flush`): the
  stream's places don't move, so the analyzer, which copies what the device takes (A4.3), shows
  what is heard either way."""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .stream import Block, frames_of

Floats = NDArray[np.float64]

TYPES = ("bell", "low-shelf", "high-shelf", "low-cut", "high-cut")  # R19.1, as A2.10 names them
CUTS = ("low-cut", "high-cut")  # the types with no gain
FREQS = (20.0, 20_000.0)  # R19.1's ranges: a band's frequency, in Hz
GAINS = (-12.0, 12.0)  # a band's gain, and the preamp, in dB
QS = (0.1, 10.0)  # a band's Q

TAPS = 16_384  # the filter's length at 44.1 and 48 kHz (A4.4): the lowest, narrowest band right
PARTS = 16  # the parts it is cut into for applying it, each a block's FFT
DESIGN_GRID = 4  # the curve is laid on a grid of this many times the filter's length
FLOOR_DB = -120.0  # how far down the curve is followed (a cut's response falls without end)
FADE = 16  # the filter's last 1/FADE is faded out, so cutting it off adds no ripple
RAMP_SECONDS = 0.05  # a change of filter, or of the level held down, is crossfaded over this
LOOK_AHEAD = 0.005  # the limiter's look-ahead, in seconds (A4.4)
HOLD = 0.005  # and how long it holds its gain down after a peak before letting it back up
CEILING = 1.0  # full scale: the limiter keeps every sample at or under it
KEEP_SECONDS = 2.5  # what is given is kept this long, so a change can take the stream back to
# what the device has got to (the ring's two seconds, A4.1) and filter it again
PROBE_STEPS = 48  # the largest boost is looked for every 1/48 of an octave, and at each band
DESIGNS_KEPT = 8  # the filters built, kept by their bands and rate: songs by genre take turns


@dataclass(frozen=True)
class Band:
    """One band of a preset (R19.1): its type (one of TYPES), frequency in Hz, gain in dB (none
    for the cuts) and Q."""

    type: str
    freq: float
    gain: float = 0.0
    q: float = 0.7


@dataclass(frozen=True)
class Tone:
    """What the equalizer plays: the bands and the preamp, in dB. A graphic preset's is its ten
    bells (presets.py)."""

    bands: tuple[Band, ...]
    preamp: float = 0.0


def taps_for(rate: int) -> int:
    """The filter's length at `rate`: 16,384 up to 48 kHz, doubled for each doubling above it, so
    it lasts as long whatever the rate (A4.4)."""
    if rate <= 48_000:
        return TAPS
    return TAPS << math.ceil(math.log2(rate / 48_000))


def _coefficients(band: Band, rate: int) -> tuple[float, float, float, float, float, float]:
    """The Audio EQ Cookbook's biquad for `band` at `rate` (R. Bristow-Johnson): b0, b1, b2, a0,
    a1, a2. Its frequency is held under the Nyquist frequency, where a band can't be."""
    f0 = min(band.freq, 0.49 * rate)
    w0 = 2 * math.pi * f0 / rate
    cos, alpha = math.cos(w0), math.sin(w0) / (2 * band.q)
    if band.type == "high-cut":  # a low-pass filter
        b = (1 - cos) / 2
        return b, 1 - cos, b, 1 + alpha, -2 * cos, 1 - alpha
    if band.type == "low-cut":  # a high-pass filter
        b = (1 + cos) / 2
        return b, -(1 + cos), b, 1 + alpha, -2 * cos, 1 - alpha
    a = 10 ** (band.gain / 40)
    if band.type == "bell":
        return 1 + alpha * a, -2 * cos, 1 - alpha * a, 1 + alpha / a, -2 * cos, 1 - alpha / a
    root = 2 * math.sqrt(a) * alpha
    if band.type == "low-shelf":
        return (
            a * ((a + 1) - (a - 1) * cos + root),
            2 * a * ((a - 1) - (a + 1) * cos),
            a * ((a + 1) - (a - 1) * cos - root),
            (a + 1) + (a - 1) * cos + root,
            -2 * ((a - 1) + (a + 1) * cos),
            (a + 1) + (a - 1) * cos - root,
        )
    if band.type == "high-shelf":
        return (
            a * ((a + 1) + (a - 1) * cos + root),
            -2 * a * ((a - 1) + (a + 1) * cos),
            a * ((a + 1) + (a - 1) * cos - root),
            (a + 1) - (a - 1) * cos + root,
            2 * ((a - 1) - (a + 1) * cos),
            (a + 1) - (a - 1) * cos - root,
        )
    raise ValueError(f"no such band type: {band.type!r}")


def response_db(band: Band, freqs: Floats, rate: int) -> Floats:
    """`band`'s response in dB at each of `freqs` (Hz), at `rate`: the magnitude of its biquad,
    |B(e^jw)|² / |A(e^jw)|². For b0 + b1 z⁻¹ + b2 z⁻² that is (b0 + b1 + b2)² − 4φ (b0 b1 + b1 b2
    + 4 b0 b2) + 16 b0 b2 φ², φ = sin²(w/2): the Cookbook's own form, which keeps its precision at
    low frequencies, where cos w is all but 1. Followed down to FLOOR_DB."""
    b0, b1, b2, a0, a1, a2 = _coefficients(band, rate)
    phi: Floats = np.sin(np.pi * np.asarray(freqs, np.float64) / rate) ** 2

    def power(c0: float, c1: float, c2: float) -> Floats:
        out: Floats = (c0 + c1 + c2) ** 2 - 4 * phi * (c0 * c1 + c1 * c2 + 4 * c0 * c2)
        out += 16 * c0 * c2 * phi * phi
        return out

    num, den = power(b0, b1, b2), power(a0, a1, a2)
    floor = 10 ** (FLOOR_DB / 10)
    out: Floats = 10 * np.log10(np.maximum(num, floor * den) / den)
    return out


def curve_db(bands: Sequence[Band], freqs: Floats, rate: int) -> Floats:
    """The bands' responses summed, in dB, at each of `freqs`: the preset's curve, without its
    preamp."""
    out = np.zeros(np.shape(freqs), np.float64)
    for band in bands:
        out += response_db(band, freqs, rate)
    return out


def largest_boost(bands: Sequence[Band], rate: int) -> float:
    """The highest the bands' curve goes, in dB (negative when it only cuts): looked for every
    1/48 of an octave from 10 Hz to the Nyquist frequency, and at each band's own frequency,
    where a bell's peak is."""
    if not bands:
        return 0.0
    top = rate / 2
    steps = math.ceil(PROBE_STEPS * math.log2(top / 10))
    grid = 10 * 2 ** (np.arange(steps + 1) / PROBE_STEPS)
    centres = [min(b.freq, 0.49 * rate) for b in bands]
    probe = np.concatenate([[0.0], np.minimum(grid, top), centres])
    return float(curve_db(bands, probe, rate).max())


def headroom(tone: Tone, rate: int) -> float:
    """How far the level is held down to keep from clipping (R19.1), in dB, 0 or more: the preamp
    plus the curve's largest boost, when that is above 0 dB; to a millionth of a dB, so a preset
    whose preamp just meets its boost (R19.3.1's) holds nothing down."""
    return max(0.0, round(tone.preamp + largest_boost(tone.bands, rate), 6))


@dataclass(frozen=True, eq=False)
class Design:
    """A filter built for `tone` at `rate`: its taps (the level held down included), each part's
    spectrum for applying it (`parts`, PARTS × the block's FFT), and the dB it is held down by
    (`headroom`). Told apart by identity: a song's filter is the same one as the last song's when
    its bands are."""

    tone: Tone
    rate: int
    taps: Floats
    parts: NDArray[np.complex128]
    headroom: float

    @property
    def block(self) -> int:
        """The frames of each part, and of each block it is applied to."""
        return len(self.taps) // PARTS


def design(tone: Tone, rate: int) -> Design:
    """The minimum-phase filter for `tone` at `rate` (A4.4): the curve, plus the preamp and less
    the headroom, laid on a grid four times the filter's length; its log turned into the real
    cepstrum, folded onto its causal half (the minimum-phase one, which adds no delay) and made a
    spectrum again; that spectrum's impulse response cut to `taps_for(rate)` with its end faded.
    Each part's spectrum is taken for applying it."""
    taps = taps_for(rate)
    n = taps * DESIGN_GRID
    held = headroom(tone, rate)
    level = tone.preamp - held
    db = curve_db(tone.bands, np.fft.rfftfreq(n, 1 / rate), rate) + level
    log_magnitude = np.maximum(db, FLOOR_DB) * (math.log(10) / 20)
    cepstrum = np.fft.irfft(log_magnitude, n)
    cepstrum[1 : n // 2] *= 2
    cepstrum[n // 2 + 1 :] = 0
    h = np.fft.irfft(np.exp(np.fft.rfft(cepstrum)), n)[:taps]
    fade = taps // FADE
    h[taps - fade :] *= 0.5 + 0.5 * np.cos(np.pi * (np.arange(fade) + 1) / fade)
    block = taps // PARTS
    parts = np.fft.rfft(h.reshape(PARTS, block), n=2 * block, axis=1)
    return Design(tone, rate, h, parts, held)


class Designs:
    """The filters built, by their tone and rate, the last DESIGNS_KEPT of them: songs chosen by
    genre (R19.4) take turns with a few presets, and each is built once. One thread's own."""

    def __init__(self, kept: int = DESIGNS_KEPT) -> None:
        self._kept = kept
        self._made: OrderedDict[tuple[Tone, int], Design] = OrderedDict()
        self.built = 0  # how many were built, for the tests

    def __call__(self, tone: Tone, rate: int) -> Design:
        key = (tone, rate)
        found = self._made.get(key)
        if found is None:
            found = self._made[key] = design(tone, rate)
            self.built += 1
            while len(self._made) > self._kept:
                self._made.popitem(last=False)
        self._made.move_to_end(key)
        return found


# ---------- applying it ----------


class _Kept:
    """The last `capacity` frames given, each by its place in the stream; silence before the
    first and after the last."""

    def __init__(self, capacity: int, channels: int, place: int) -> None:
        self._data: Floats = np.zeros((capacity, channels), np.float64)
        self.first = self.end = place  # the places of the first frame kept and after the last

    def write(self, place: int, frames: NDArray[np.floating]) -> None:
        """`frames` from `place`, which is where the last write ended, or before it (what was
        kept from there on is written again)."""
        cap = len(self._data)
        n = len(frames)
        if n > cap:
            frames, place, n = frames[n - cap :], place + n - cap, cap
        at = place % cap
        first = min(n, cap - at)
        self._data[at : at + first] = frames[:first]
        self._data[: n - first] = frames[first:]
        self.end = place + n
        self.first = max(self.first, self.end - cap)

    def back(self, place: int) -> None:
        """What was kept from `place` on is forgotten."""
        self.end = max(self.first, min(self.end, place))

    def read(self, start: int, end: int) -> Floats:
        """The frames from `start` to `end`, silence where none is kept."""
        out = np.zeros((max(0, end - start), self._data.shape[1]), np.float64)
        lo, hi = max(start, self.first), min(end, self.end)
        if lo < hi:
            cap = len(self._data)
            at, n = lo % cap, hi - lo
            first = min(n, cap - at)
            out[lo - start : lo - start + first] = self._data[at : at + first]
            out[lo - start + first : hi - start] = self._data[: n - first]
        return out


@dataclass(frozen=True)
class _Step:
    """The filter from `place` on (None: none, the samples as given), crossfaded there from what
    played before it when `ramped`."""

    place: int
    design: Design | None
    ramped: bool = True


class Equalizer:
    """The equalizer on one stream at `rate` in `channels` (A4.4): what is given, from place
    `place`, comes out filtered, frame for frame and in order, under full scale. The filter in
    use changes at a place (`schedule`, `retune`), crossfaded from the one before over 50 ms;
    None is no filter at all. While none is in use, `push` gives back what it is given, untouched,
    and holds nothing; while one is, it holds back the limiter's look-ahead.

    A change heard at once (`retune`) takes the stream back to a place already given: what was
    given from there is filtered again, as `redo` asks for it, before anything new is given. A
    stream taken back to be decoded again from a place (a seek, a song to follow changed) is
    `rewind`'s. What is given is kept `keep` frames (KEEP_SECONDS by default) for both, and the
    filter takes up from a place as if it had run through to it."""

    def __init__(self, rate: int, channels: int, place: int = 0, keep: int | None = None) -> None:
        self.rate, self.channels = rate, channels
        taps = taps_for(rate)
        self._block = taps // PARTS
        self._ramp = frames_of(RAMP_SECONDS, rate)
        self._look = frames_of(LOOK_AHEAD, rate)
        self._hold = frames_of(HOLD, rate)
        self._keep = frames_of(KEEP_SECONDS, rate) if keep is None else keep
        self._given = _Kept(self._keep + taps + 2 * self._block, channels, place)
        self._wet = _Kept(self._keep + 4 * (self._look + self._hold), channels, place)
        self._steps: list[_Step] = []
        self.given = place  # the place after the last frame given
        self._done = place  # the place after the last frame filtered
        self._out = place  # the place after the last frame given out
        self._redo = np.zeros((0, channels), np.float32)  # given, to be filtered again
        self._active = False  # a filter is in use: blocks are filtered, the look-ahead held
        self._grid = place  # where the block being filtered starts
        self._spectra = np.zeros((PARTS - 1, channels, self._block + 1), np.complex128)
        self._tails: dict[Design, NDArray[np.complex128]] = {}
        self._spectrum: NDArray[np.complex128] | None = None

    # ---------- what the feed asks ----------

    @property
    def held(self) -> int:
        """Frames given and not yet given out."""
        return self.given - self._out

    @property
    def redoing(self) -> bool:
        """Frames given are to be filtered again (`redo`) before more are given."""
        return len(self._redo) > 0

    @property
    def design(self) -> Design | None:
        """The filter in use at the last place given."""
        return self._steps[-1].design if self._steps else None

    def push(self, block: Block) -> Block:
        """`block`, given at place `given`: what comes out of it now, from where the last came
        out (fewer frames while the look-ahead is held, more when it is let go)."""
        if self.redoing:
            raise RuntimeError("frames to filter again come first (redo)")
        place = self.given
        self._given.write(place, block)
        self.given += len(block)
        return self._run(place, block)

    def redo(self, frames: int) -> Block:
        """Up to `frames` of the frames to filter again, filtered: what comes out of them now."""
        part, self._redo = self._redo[:frames], self._redo[frames:]
        place = self._done
        self._given.write(place, part)
        return self._run(place, part)

    def flush(self) -> Block:
        """The stream ends: every frame held, given out (the look-ahead sees silence after)."""
        out = self._emit(final=True) if self._active else self._empty()
        return self._join(out, self._passing())

    def schedule(self, place: int, design: Design | None, ramped: bool = True) -> None:
        """`design` from `place` on, `given` or later (a song's join, R7.6.1), crossfaded there
        from the one before when `ramped`; nothing changes when it is the one in use."""
        place = max(place, self._done)
        self._steps = [s for s in self._steps if s.place < place]
        if self._steps and self._steps[-1].design is design:
            return
        if not self._steps and design is None:
            return
        self._steps.append(_Step(place, design, ramped))
        self._prune()

    def retune(self, at: int, place: int, design: Design | None, until: int | None = None) -> None:
        """`design` from `place` to `until` (None: on), crossfaded there, heard at once: the frames
        given from `at` (where the device has got to, at or before `place`) are to be filtered
        again (`redo`), the filter taken up at `at` as it was. The filters from `until` on stay."""
        redo = np.concatenate([self._given.read(at, self._done), self._redo]).astype(np.float32)
        kept = [
            s for s in self._steps if s.place < place or (until is not None and s.place >= until)
        ]
        self._steps = sorted([*kept, _Step(place, design)], key=lambda s: s.place)
        self._back(at)
        self._redo = redo
        self._prune()

    def rewind(self, at: int) -> None:
        """The stream from `at` on is taken back, to be given again (decoded again: a seek, a song
        to follow changed): the filters scheduled after it are let go, and the filter takes up at
        `at` as it was."""
        self._steps = [s for s in self._steps if s.place <= at]
        self._redo = self._redo[:0]
        self._back(at)
        self.given = at

    # ---------- the filtering ----------

    def _empty(self) -> Block:
        return np.zeros((0, self.channels), np.float32)

    @staticmethod
    def _join(*parts: Block) -> Block:
        kept = [p for p in parts if len(p)]
        if len(kept) == 1:
            return kept[0]
        return np.concatenate(kept) if kept else parts[0]

    def _run(self, place: int, block: Block) -> Block:
        """The frames `block`, at `place` (which follows the last filtered), through the filter
        in use: untouched while none is, or until the first place one is."""
        end = place + len(block)
        if not self._active:
            start = self._first_wet(place, end)
            if start is None:
                self._wet.write(place, block)
                self._done = self._out = end
                return block
            head = block[: start - place]
            self._wet.write(place, head)
            self._done = self._out = start
            self._start(start)
            place = start
        else:
            head = self._empty()
        self._filter(place, end)
        return self._join(head, self._emit(final=False), self._passing())

    def _mix(self, start: int, end: int) -> list[_Step]:
        """The steps that make the frames from `start` to `end`: the last whose crossfade is over
        by `start`, and those after it that begin before `end`. A first step of none stands for
        the samples as given, before any filter."""
        steps = [_Step(-(1 << 62), None, False), *self._steps]
        base = 0
        for i, step in enumerate(steps):
            if step.place >= end:
                break
            if not step.ramped and step.place <= start or step.place + self._ramp - 1 <= start:
                base = i
        return [s for s in steps[base:] if s.place < end]

    def _first_wet(self, start: int, end: int) -> int | None:
        """The first place from `start` to `end` a filter is heard at; None if none is."""
        mix = self._mix(start, end)
        wet = [s.place for s in mix if s.design is not None]
        return None if not wet else max(start, min(wet))

    def _start(self, at: int) -> None:
        """A filter comes in at `at`: blocks are filtered from there, the spectra of the blocks
        before it taken from what was given, as if it had run through."""
        self._active = True
        self._grid = at
        self._tails, self._spectrum = {}, None
        b = self._block
        before = self._given.read(at - PARTS * b, at)
        for k in range(PARTS - 1):  # k: the block k + 1 before the one at `at`
            end = len(before) - k * b
            self._spectra[k] = np.fft.rfft(before[end - 2 * b : end].T, axis=1)

    def _back(self, at: int) -> None:
        """The filter as it was at `at`, for the stream given from there again."""
        self._given.back(at)
        self._wet.back(at)
        self._done = self._out = at
        lookback = at - self._hold - self._look
        self._active = False
        if self._first_wet(lookback, at + 1) is not None:
            self._start(at)

    def _filter(self, start: int, end: int) -> None:
        """The frames from `start` (the next to filter) to `end`, filtered, a block at a time."""
        b = self._block
        while start < end:
            stop = min(end, self._grid + b)
            self._wet.write(start, self._filtered(start, stop))
            if stop == self._grid + b:  # the block is whole: its spectrum goes to the parts after
                assert self._spectrum is not None
                self._spectra = np.roll(self._spectra, 1, axis=0)
                self._spectra[0] = self._spectrum
                self._grid += b
                self._tails = {}
            start = stop
        self._done = end

    def _filtered(self, start: int, end: int) -> Floats:
        """The frames from `start` to `end` of the block at `_grid`, each filter of the mix
        applied and crossfaded: the block and the one before it, through the FFT, the first part
        of each filter multiplied in and the rest of it from the blocks before (overlap-save; the
        part of the block not given yet is silence, which no frame before it hears)."""
        b, g = self._block, self._grid
        segment = self._given.read(g - b, end)
        spectrum = np.fft.rfft(segment.T, n=2 * b, axis=1)
        self._spectrum = spectrum
        dry = segment[start - g + b :]
        mixed: Floats | None = None
        for step in self._mix(start, end):
            if step.design is None:
                made = dry
            else:
                design = step.design
                out = np.fft.irfft(spectrum * design.parts[0] + self._tail(design), 2 * b, axis=1)
                made = out[:, start - g + b : end - g + b].T
            if mixed is None:
                mixed = made
            elif not step.ramped:
                mixed = np.where((np.arange(start, end) >= step.place)[:, None], made, mixed)
            else:
                t = np.clip((np.arange(start, end) - step.place + 1) / self._ramp, 0.0, 1.0)
                mixed = mixed + t[:, None] * (made - mixed)
        assert mixed is not None
        return mixed

    def _tail(self, design: Design) -> NDArray[np.complex128]:
        """What the blocks before this one give through the rest of `design`'s parts."""
        tail = self._tails.get(design)
        if tail is None:
            tail = self._tails[design] = np.einsum("kcf,kf->cf", self._spectra, design.parts[1:])
        return tail

    def _emit(self, final: bool) -> Block:
        """The frames filtered whose look-ahead is known (all of them, `final`), through the
        limiter: each frame's gain at most what keeps it under full scale, taken as the least of
        the next 5 ms's and the last 5 ms's (`_gains`) and smoothed over 5 ms, so it comes down
        before a peak and goes back up after it without a step."""
        look, hold = self._look, self._hold
        end = self._done if final else self._done - look + 1
        start = self._out
        if end <= start:
            return self._empty()
        wet = self._wet.read(start - look + 1 - hold, end + look - 1)
        y = wet[look - 1 + hold : look - 1 + hold + end - start]
        peak = np.abs(wet).max(axis=1)
        self._out = end
        if peak.max() <= CEILING:
            return y.astype(np.float32)
        out = y * self._gains(peak, end - start)[:, None]
        return np.clip(out, -CEILING, CEILING).astype(np.float32)

    def _gains(self, peak: Floats, n: int) -> Floats:
        """The limiter's gain for `n` frames from the peaks of the frames around them (the hold
        and the look-ahead before, the look-ahead after): no frame's gain is more than its own
        limit, as each is the mean of minima taken over windows that all hold that frame."""
        look, hold = self._look, self._hold
        limit = np.minimum(1.0, CEILING / np.maximum(peak, 1e-30))
        lows = np.lib.stride_tricks.sliding_window_view(limit, hold + look).min(axis=1)
        sums = np.concatenate([[0.0], np.cumsum(lows)])
        gains: Floats = (sums[look:] - sums[:-look])[:n] / look
        return gains

    def _passing(self) -> Block:
        """Once no filter is heard any more, nor the limiter's look back, the frames held are
        given out as they were given, and from then on each block as it comes."""
        if not self._active:
            return self._empty()
        lookback = self._out - self._hold - self._look
        if self._first_wet(lookback, max(self._done, lookback + 1)) is not None:
            return self._empty()
        later = [s for s in self._steps if s.place >= self._done and s.design is not None]
        if later:
            return self._empty()
        out = self._given.read(self._out, self._done)
        self._out = self._done
        self._active = False
        return out.astype(np.float32)

    def _prune(self) -> None:
        """Steps whose filters can no longer be heard, nor reached by a change taken back to
        what is kept, are let go: all but the last whose crossfade is over by then."""
        oldest = self._out - self._keep
        over = [
            i
            for i, s in enumerate(self._steps)
            if (s.place + self._ramp - 1 <= oldest or (not s.ramped and s.place <= oldest))
        ]
        if over:
            del self._steps[: over[-1]]
