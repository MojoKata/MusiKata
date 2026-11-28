"""A song's waveform worked out of its file (A5.1, R11.1.1): decoded to mono floats by PyAV (A4.1)
on the worker processes (A1.3), a part at a time, and kept in the index's `waveform` table by the
song's audio hash (A2.3), so a retag, a move or a copy keeps it.

A song is cut into parts of `PART_SECONDS` of audio, each a job of its own (`decode_part`, a plain
function of picklable arguments), so the app hears how far the decoding has got after each one and
draws what is decoded so far, the rest a flat line (`Assembly.peaks`): a partial waveform every 30
seconds of the song, which a worker decodes in well under a second. Each part is gathered into fine
pairs of `hop` samples, the hop chosen from the length the file says so a song is about `FINE`
pairs whatever its length; once every part is in, the pairs are reduced to the waveform's
`peaks.N`. The last part decodes to the file's real end, so a length the file gets wrong (a VBR MP3
with no header saying it) moves only where the partial waveforms put what they draw."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol

import numpy as np

from ..audio.decode import Decoder
from ..audio.stream import Block
from . import peaks as peak_pairs
from .peaks import Peaks, Samples

PART_SECONDS = 30.0  # the audio each job decodes: how often the waveform fills in
FINE = 16_000  # fine pairs a song is gathered into before its N pairs: 8 a slice
GUESS_SECONDS = 600.0  # the length a file that doesn't say its own is taken to have
BLOCK = 8192  # frames decoded at a time


class Source(Protocol):
    """What a part decodes from: a song's file open in mono (audio.decode.Decoder)."""

    @property
    def rate(self) -> int: ...

    @property
    def seconds(self) -> float | None: ...

    def seek(self, sample: int) -> None: ...

    def blocks(self, frames: int) -> Iterator[Block]: ...

    def __enter__(self) -> Source: ...

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None: ...


Opener = Callable[[str, int], Source]  # (path, channels): raises audio.decode.DecodeError


@dataclass(frozen=True)
class Plan:
    """How a song is cut: fine pairs of `hop` samples, parts of `step` samples (a whole number of
    hops), `parts` of them, the last to the song's end."""

    hop: int
    step: int
    parts: int


def plan(expected: int | None, rate: int) -> Plan:
    """The cut of a song of `expected` samples at `rate` (None: the file doesn't say, and it is
    decoded as one part, its hop that of a song of `GUESS_SECONDS`)."""
    if not expected or expected < 0:
        return Plan(max(1, round(GUESS_SECONDS * rate) // FINE), 0, 1)
    hop = max(1, expected // FINE)
    step = hop * max(1, math.ceil(PART_SECONDS * rate / hop))
    return Plan(hop, step, max(1, math.ceil(expected / step)))


@dataclass(frozen=True)
class Part:
    """One part of a song decoded: its place (`index` of `parts`), the cut's `hop`, the length the
    file says (`expected` samples, 0 when it doesn't), the part's fine pairs, and the samples it
    held (`frames`)."""

    index: int
    parts: int
    hop: int
    expected: int
    maxima: Samples
    minima: Samples
    frames: int


class Gathering:
    """Fine pairs gathered as blocks come, `hop` samples a pair; what is left over waits for the
    next block, and `done` makes it a pair of its own."""

    def __init__(self, hop: int) -> None:
        self.hop = max(1, hop)
        self._held = np.zeros(0, np.float32)
        self._maxima: list[Samples] = []
        self._minima: list[Samples] = []

    def add(self, samples: Samples) -> None:
        data = np.concatenate([self._held, np.asarray(samples, np.float32)])
        whole = len(data) - len(data) % self.hop
        if whole:
            grouped = data[:whole].reshape(-1, self.hop)
            self._maxima.append(grouped.max(axis=1))
            self._minima.append(grouped.min(axis=1))
        self._held = data[whole:]

    def done(self) -> tuple[Samples, Samples]:
        """Every pair gathered, the leftover samples the last."""
        if len(self._held):
            self._maxima.append(self._held.max(keepdims=True))
            self._minima.append(self._held.min(keepdims=True))
            self._held = np.zeros(0, np.float32)
        if not self._maxima:
            empty = np.zeros(0, np.float32)
            return empty, empty.copy()
        return np.concatenate(self._maxima), np.concatenate(self._minima)


def decode_part(path: str, index: int, opener: Opener = Decoder) -> Part:
    """Part `index` of the song at `path` (a job for the worker processes, A1.3): the file opened
    in mono, sought to the part's first sample, and its samples gathered into fine pairs. Every
    part cuts the song the same way, from the length the file says. Raises
    audio.decode.DecodeError when the file can't be opened, or nothing in it decodes."""
    with opener(path, 1) as source:
        rate = source.rate
        seconds = source.seconds
        expected = round(seconds * rate) if seconds else None
        cut = plan(expected, rate)
        last = index >= cut.parts - 1
        source.seek(index * cut.step)
        gathering = Gathering(cut.hop)
        taken = 0
        for block in source.blocks(BLOCK):
            mono = block[:, 0]
            if not last:
                mono = mono[: cut.step - taken]
            gathering.add(mono)
            taken += len(mono)
            if not last and taken >= cut.step:
                break
        maxima, minima = gathering.done()
    return Part(index, cut.parts, cut.hop, expected or 0, maxima, minima, taken)


class Assembly:
    """A song's parts as they come, in order: the waveform so far, and whether it is whole."""

    def __init__(self) -> None:
        self._parts: list[Part] = []

    def add(self, part: Part) -> None:
        """Part `part.index`, the next in order."""
        self._parts.append(part)

    @property
    def next(self) -> int:
        """The part to decode next."""
        return len(self._parts)

    @property
    def complete(self) -> bool:
        return bool(self._parts) and len(self._parts) >= self._parts[0].parts

    def peaks(self, n: int = peak_pairs.N) -> Peaks:
        """The waveform: whole once every part is in; before, what is decoded placed where the
        file's length puts it, the rest 0 (a flat line)."""
        if not self._parts:
            return np.zeros((n, 2), np.float32)
        maxima = np.concatenate([p.maxima for p in self._parts])
        minima = np.concatenate([p.minima for p in self._parts])
        first = self._parts[0]
        if not self.complete and first.expected:
            slots = math.ceil(first.expected / first.hop)
            if slots > len(maxima):
                padding = np.zeros(slots - len(maxima), np.float32)
                maxima = np.concatenate([maxima, padding])
                minima = np.concatenate([minima, padding])
        return peak_pairs.reduce(maxima, minima, n)


# ---------- kept in the index (A2.1's waveform) ----------


def hash_of(c: sqlite3.Connection, path: str) -> str | None:
    """The audio hash of the song at `path` under the root; None when the index has no such song,
    or no hash for it (a file it couldn't read)."""
    row = c.execute("SELECT audio_hash FROM song WHERE path = ?", (path,)).fetchone()
    return str(row[0]) if row is not None and row[0] else None


def stored(c: sqlite3.Connection, audio_hash: str) -> Peaks | None:
    """The waveform kept for audio of `audio_hash`; None when none is, or what is kept isn't
    `peaks.N` whole pairs (it is worked out again)."""
    row = c.execute("SELECT peaks FROM waveform WHERE hash = ?", (audio_hash,)).fetchone()
    if row is None:
        return None
    try:
        found = peak_pairs.from_blob(bytes(row[0]))
    except TypeError, ValueError:
        return None
    return found if len(found) == peak_pairs.N else None


def keep(c: sqlite3.Connection, audio_hash: str, waveform: Peaks) -> None:
    """Keeps `waveform` for audio of `audio_hash`, in place of what was kept."""
    c.execute(
        "INSERT OR REPLACE INTO waveform (hash, peaks) VALUES (?, ?)",
        (audio_hash, peak_pairs.to_blob(waveform)),
    )
