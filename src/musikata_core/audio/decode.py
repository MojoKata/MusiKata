"""Decoding a song's file (A4.1): PyAV, FFmpeg's binding, opens it and decodes it to float32 at
the file's own rate, and `mix` folds it to the device's channels; it comes out in blocks of a set
number of frames, one row a frame and one column a channel (stream.py). `Resampler`, FFmpeg's,
brings it to the device's rate: the joins of A4.2 (join.py) run one song into the next through the
same one, and `played` plays a song alone.

The silence encoders add (A4.2, R7.6) is FFmpeg's to trim, and it does, so nothing here trims it
again: an MP3's start delay and end padding from its LAME or Xing header, an AAC file's from its
MP4 edit list or its `iTunSMPB` tag, an Opus file's pre-skip and the end its last page gives
(tests/test_playback_decode.py shows each on files of a known number of samples).

A seek (A4.6) asks FFmpeg for the packet a little before the sample, decodes forward from there
and drops what comes before it, so the song from that sample is the same, sample for sample, as
the song decoded through. Resampled, it starts from a sample where the file's samples and the
device's frames fall at the same instant (`seek_plan`), so the frames are the same too.

`Decoder` and `Resampler` are the edge: PyAV's objects go no further than them, and everything
they hand on is arrays and numbers. What a damaged file does is decided here: a packet that
doesn't decode is skipped and counted, a file that ends early ends there, and one with no audio
that decodes at all is a DecodeError."""

from __future__ import annotations

import logging
import math
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
LAYOUTS = {1: "mono", 2: "stereo"}  # the device's channels, as FFmpeg names their layouts

PREROLL = 0.2  # seconds decoded before a seek's place and dropped: what a decoder needs to settle
# after a seek (an AAC frame overlaps the one before; Opus asks for 80 ms), and more
END_GUARD = 1.5  # seconds before its end a seek lands no later than: FFmpeg times what is on the
# last page of an Ogg file from that page's position, which an encoder can get wrong (its own
# Vorbis encoder does), and what comes before it from the pages before
SEEK_BACK = (0.0, 5.0, 30.0)  # seconds further back a seek tries when FFmpeg can't seek there
LEAD = 64  # frames the resampler is given before a seek's place and dropped, so its filter has
# what came before (A4.6)


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


def seek_plan(frame: int, rate: int, device: int, lead: int = LEAD) -> tuple[int, int]:
    """Where to start for a seek to the device's frame `frame` of a song at `rate` (A4.6): the
    file's sample to resample from, and how many of the device's frames to drop after it. The
    sample is one where the file's samples and the device's frames fall at the same instant, at
    least `lead` frames before, so the resampler then makes the very frames it makes playing the
    song through. At the device's own rate it is the sample itself, with nothing to drop."""
    if rate == device:
        return frame, 0
    common = math.gcd(rate, device)
    step_in, step_out = rate // common, device // common  # the instants both fall on
    k = max(0, frame - lead) // step_out
    return k * step_in, frame - k * step_out


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


def dropped(chunks: Iterable[Block], frames: int) -> Iterator[Block]:
    """`chunks` without their first `frames` frames."""
    for chunk in chunks:
        if frames >= len(chunk):
            frames -= len(chunk)
            continue
        yield chunk[frames:]
        frames = 0


class Resampler:
    """FFmpeg's resampler, from `rate` to `device` in `channels` (1 or 2): what it is given, at
    `rate`, comes out at `device`, frame k of what comes out falling at the instant k / `device`
    from the first sample given. It holds back a few frames, which `flush` gives at the end. At
    the same rate it gives back what it is given."""

    def __init__(self, rate: int, device: int, channels: int) -> None:
        self.rate, self.device, self.channels = rate, device, channels
        self._swr = None
        if rate != device:
            self._swr = av.AudioResampler(format="flt", layout=LAYOUTS[channels], rate=device)

    def resample(self, block: Block) -> Block:
        if self._swr is None:
            return block
        given = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(block, np.float32).reshape(1, -1),
            format="flt",
            layout=LAYOUTS[self.channels],
        )
        given.sample_rate = self.rate
        return self._out(self._swr.resample(given))

    def flush(self) -> Block:
        """The frames held back: the end of what was given."""
        if self._swr is None:
            return np.zeros((0, self.channels), np.float32)
        return self._out(self._swr.resample(None))

    def _out(self, frames: list[av.AudioFrame]) -> Block:
        out = [
            f.to_ndarray().astype(np.float32, copy=False).reshape(-1, self.channels) for f in frames
        ]
        return np.concatenate(out) if out else np.zeros((0, self.channels), np.float32)


class Decoder:
    """A song's file, open for decoding into `channels` (the device's) at its own rate (`rate`).
    Raises DecodeError when it isn't there or isn't audio. Close it, or use it in a `with`."""

    def __init__(self, path: str, channels: int) -> None:
        self.path, self.channels = path, channels
        self.skipped = 0  # packets that didn't decode
        self.decoded = 0  # frames given
        self._from = 0  # the sample the next `blocks` start at
        self._open()
        self._read = False  # whether the file has been read from since it was opened
        audio = self._stream
        if self._file.duration:
            seconds: float | None = self._file.duration / 1_000_000
        elif audio.duration and audio.time_base:
            seconds = float(audio.duration * audio.time_base)
        else:
            seconds = None
        ctx = audio.codec_context
        self.info = Info(seconds, int(ctx.sample_rate or 0), int(ctx.channels or 0), str(ctx.name))

    def _open(self) -> None:
        try:
            self._file = av.open(self.path)
        except (av.FFmpegError, OSError, ValueError, UnicodeDecodeError) as e:
            raise DecodeError(f"couldn't open {self.path}: {e}") from e
        audio = self._file.streams.audio
        if not audio:
            self._file.close()
            raise DecodeError(f"no audio in {self.path}")
        self._stream = audio[0]
        self._origin = self._stream.start_time or 0  # the first sample's time, in the stream's
        self._base = self._stream.time_base  # units

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

    @property
    def rate(self) -> int:
        """The file's sample rate, which `blocks` give."""
        return self.info.rate

    @property
    def seconds(self) -> float | None:
        """The song's length, as the file says it (None when it doesn't)."""
        return self.info.seconds

    def seek(self, sample: int) -> None:
        """The next `blocks` start at the song's sample `sample` (A4.6), its first being 0; past
        its end they give nothing."""
        self._from = max(0, sample)

    def _rewind(self) -> None:
        """The file back at its start, opened again if it has been read: FFmpeg's seek to the
        start can pass over what its trims count from."""
        if self._read:
            self._file.close()
            self._open()
        self._read = True

    def _frames(self) -> Iterator[av.AudioFrame]:
        """The file's audio as FFmpeg decodes it, from where the file is; a packet that doesn't
        decode is skipped and counted."""
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
            yield from frames

    def _chunks(self, first: int) -> Iterator[Block]:
        """The file's audio in the device's channels from its sample `first`, as FFmpeg hands it
        out."""
        rate = self.info.rate
        at: int | None = 0  # the sample the next decoded frame starts at
        if first and first / rate > PREROLL:
            self._read = True
            seconds = first / rate - PREROLL
            length = self._length()
            if length is not None:  # not into the last page: see END_GUARD
                seconds = max(0.0, min(seconds, length / rate - END_GUARD))
            if not self._seek(seconds):
                yield from self._chunks_from_start(first)
                return
            at = None  # read from the first frame's time
        else:
            self._rewind()
        # after a seek FFmpeg can leave untrimmed the end of a file it trims played through (Vorbis
        # written by its own encoder): no further than the length its stream gives
        end = self._length() if at is None else None
        to_float = av.AudioResampler(format="flt")  # its own rate and channels: every sample kept
        matrices: dict[tuple[str, ...], NDArray[np.float32]] = {}
        for decoded in self._frames():
            if at is None:
                if decoded.pts is None:  # no time to place it by: from the start instead
                    yield from self._chunks_from_start(first)
                    return
                at = round((decoded.pts - self._origin) * self._base * rate)
                if at > first:  # FFmpeg's seek went past the sample
                    log.debug(
                        "a seek in %s landed past sample %d; from the start", self.path, first
                    )
                    yield from self._chunks_from_start(first)
                    return
            for f in to_float.resample(decoded):
                names = tuple(str(c.name) for c in f.layout.channels)
                if names not in matrices:
                    matrices[names] = mix_matrix(names, self.channels)
                samples = f.to_ndarray().astype(np.float32, copy=False)  # "flt" already
                samples = mix(samples.reshape(-1, len(names)), matrices[names])
                if end is not None:
                    samples = samples[: max(0, end - at)]
                kept = samples[max(0, first - at) :]
                at += len(samples)
                if len(kept):
                    yield kept

    def _length(self) -> int | None:
        """The song's samples, as its stream gives them; None when it doesn't."""
        if not self._stream.duration:
            return None
        return round(self._stream.duration * self._base * self.info.rate)

    def _seek(self, seconds: float) -> bool:
        """The file at the packet before `seconds` (FFmpeg's seek flushes the decoder), or one
        further back when FFmpeg can't seek there (past the end, or near it in some FLAC files);
        False when it can't seek at all."""
        for back in SEEK_BACK:
            when = self._origin + int((seconds - back) / self._base)
            try:
                self._file.seek(max(when, self._origin), stream=self._stream, backward=True)
                return True
            except av.FFmpegError as e:
                log.debug("couldn't seek to %.3f s in %s: %s", seconds - back, self.path, e)
        return False

    def _chunks_from_start(self, first: int) -> Iterator[Block]:
        """As `_chunks`, decoding from the file's start and dropping what comes before `first`."""
        self._read = True  # so `_chunks` opens the file again
        yield from dropped(self._chunks(0), first)

    def blocks(self, frames: int) -> Iterator[Block]:
        """The song from where `seek` put it (its start, unless it was sought), at its own rate,
        `frames` frames a block, the last one shorter. Raises DecodeError when nothing in the file
        decodes; logs the packets skipped."""
        given = 0
        for block in reblock(self._chunks(self._from), frames):
            given += len(block)
            self.decoded += len(block)
            yield block
        if self.skipped:
            log.warning("skipped %d damaged packets of %s", self.skipped, self.path)
        if not given and not self._from:
            raise DecodeError(f"nothing in {self.path} decodes")


def played(decoder: Decoder, device: int, frames: int, start: int = 0) -> Iterator[Block]:
    """The song at the device's rate from its frame `start` (its first being 0), `frames` frames a
    block, the last one shorter: as one song alone plays."""
    first, drop = seek_plan(start, decoder.rate, device)
    decoder.seek(first)
    resampler = Resampler(decoder.rate, device, decoder.channels)

    def chunks() -> Iterator[Block]:
        for block in decoder.blocks(max(1, decoder.rate // 50)):
            yield resampler.resample(block)
        yield resampler.flush()

    return reblock(dropped(chunks(), drop), frames)
