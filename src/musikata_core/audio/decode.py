"""Decoding a song's file (A4.1): PyAV, FFmpeg's binding, opens it and decodes it, FFmpeg's
resampler brings it to the device's rate as float32, and `mix` to the device's channels; it comes
out in blocks of a set number of frames, one row a frame and one column a channel (stream.py).

`Decoder` is the edge: PyAV's objects go no further than it, and everything it hands on is
arrays and numbers. What a damaged file does is decided here: a packet that doesn't decode is
skipped and counted, a file that ends early ends there, and one with no audio that decodes at all
is a DecodeError."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from types import TracebackType

import av
import numpy as np
from numpy.typing import NDArray

from .stream import Block

log = logging.getLogger(__name__)

# a channel's share of each side when folding to stereo: fronts whole, the centre and the rest at
# -3 dB (ITU-R BS.775's downmix); the LFE is left out, as a downmix leaves it
LEFT = {"FL": 1.0, "FLC": 1.0, "BL": 0.7071, "SL": 0.7071, "TFL": 0.7071, "TBL": 0.7071}
RIGHT = {"FR": 1.0, "FRC": 1.0, "BR": 0.7071, "SR": 0.7071, "TFR": 0.7071, "TBR": 0.7071}
CENTRE = {"FC": 0.7071, "BC": 0.7071, "TC": 0.7071, "TFC": 0.7071, "TBC": 0.7071}
LFE = {"LFE", "LFE2"}


class DecodeError(Exception):
    """A file MusiKata couldn't play: not there, not audio, or nothing in it decodes."""


@dataclass(frozen=True)
class Info:
    """What a file's audio is: its length in seconds (None when the file doesn't say), and the
    rate, channels and codec it was encoded with."""

    seconds: float | None
    rate: int
    channels: int
    codec: str


def mix_matrix(names: Sequence[str], channels: int) -> NDArray[np.float32]:
    """The matrix (the file's channels × `channels`, 1 or 2) that folds a frame of channels named
    as FFmpeg names them (FL, FR, FC, LFE, ...) into the device's. Mono goes whole to each side;
    to mono, every channel but the LFE is averaged; to stereo, each goes to its side, the centre
    to both, and a channel of no known name to the left or right by its place. A side whose
    shares add up past 1 is scaled down, so the fold never clips what didn't."""
    if channels not in (1, 2):
        raise ValueError(f"folding to {channels} channels: 1 or 2 only")
    n = len(names)
    m = np.zeros((n, channels), np.float32)
    if n == channels:
        m[:] = np.eye(n, dtype=np.float32)
    elif n == 1:
        m[0, :] = 1.0
    elif channels == 1:
        heard = [i for i, name in enumerate(names) if name not in LFE] or list(range(n))
        m[heard, 0] = 1.0 / len(heard)
    else:
        for i, name in enumerate(names):
            if name in LFE:
                continue
            if name in LEFT:
                m[i, 0] = LEFT[name]
            elif name in RIGHT:
                m[i, 1] = RIGHT[name]
            elif name in CENTRE:
                m[i, :] = CENTRE[name]
            else:
                m[i, i % 2] = 1.0
    sums = m.sum(axis=0)
    return (m / np.maximum(sums, 1.0)).astype(np.float32)


def mix(block: Block, matrix: NDArray[np.float32]) -> Block:
    """A block of the file's channels folded into the device's by `mix_matrix`'s matrix."""
    if matrix.shape[0] == matrix.shape[1] and np.array_equal(matrix, np.eye(len(matrix))):
        return block
    return (block @ matrix).astype(np.float32)


def reblock(chunks: Iterable[Block], frames: int) -> Iterator[Block]:
    """The frames of `chunks`, of any lengths, in blocks of exactly `frames`, the last one
    shorter when the frames don't divide evenly."""
    held: list[Block] = []
    n = 0
    for chunk in chunks:
        if not len(chunk):
            continue
        held.append(chunk)
        n += len(chunk)
        if n >= frames:
            whole = np.concatenate(held)
            cut = n - n % frames
            for i in range(0, cut, frames):
                yield whole[i : i + frames]
            held = [whole[cut:]] if cut < n else []
            n -= cut
    if n:
        yield np.concatenate(held)


class Decoder:
    """A song's file, open for decoding at `rate` and `channels` (the device's). Raises
    DecodeError when it isn't there or isn't audio. Close it, or use it in a `with`."""

    def __init__(self, path: str, rate: int, channels: int) -> None:
        self.path, self.rate, self.channels = path, rate, channels
        self.skipped = 0  # packets that didn't decode
        self.decoded = 0  # frames given, at `rate`
        try:
            self._file = av.open(path)
        except (av.FFmpegError, OSError, ValueError, UnicodeDecodeError) as e:
            raise DecodeError(f"couldn't open {path}: {e}") from e
        audio = self._file.streams.audio
        if not audio:
            self._file.close()
            raise DecodeError(f"no audio in {path}")
        self._stream = audio[0]
        if self._file.duration:
            seconds: float | None = self._file.duration / 1_000_000
        elif self._stream.duration and self._stream.time_base:
            seconds = float(self._stream.duration * self._stream.time_base)
        else:
            seconds = None
        ctx = self._stream.codec_context
        self.info = Info(seconds, int(ctx.sample_rate or 0), int(ctx.channels or 0), str(ctx.name))

    def __enter__(self) -> Decoder:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._file.close()

    def _chunks(self) -> Iterator[Block]:
        """The file's audio at the device's rate and channels, as FFmpeg hands it out."""
        resampler = av.AudioResampler(format="flt", rate=self.rate)
        matrices: dict[tuple[str, ...], NDArray[np.float32]] = {}

        def out(frame: av.AudioFrame | None) -> Iterator[Block]:
            for f in resampler.resample(frame):
                names = tuple(str(c.name) for c in f.layout.channels)
                if names not in matrices:
                    matrices[names] = mix_matrix(names, self.channels)
                samples = f.to_ndarray().astype(np.float32, copy=False)  # "flt" already
                yield mix(samples.reshape(-1, len(names)), matrices[names])

        packets = self._file.demux(self._stream)
        while True:
            try:
                packet = next(packets)
            except StopIteration:
                break
            except av.FFmpegError as e:  # the file ends early, or its container is cut
                log.warning("%s ends early: %s", self.path, e)
                break
            try:
                frames = packet.decode()
            except av.FFmpegError:
                self.skipped += 1
                continue
            for frame in frames:
                yield from out(frame)
        yield from out(None)

    def blocks(self, frames: int) -> Iterator[Block]:
        """The song, `frames` frames a block, the last one shorter. Raises DecodeError when
        nothing in the file decodes; logs the packets skipped."""
        for block in reblock(self._chunks(), frames):
            self.decoded += len(block)
            yield block
        if self.skipped:
            log.warning("skipped %d damaged packets of %s", self.skipped, self.path)
        if not self.decoded:
            raise DecodeError(f"nothing in {self.path} decodes")
