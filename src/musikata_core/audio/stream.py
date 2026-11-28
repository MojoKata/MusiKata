"""The stream the sound device pulls from (A4.1): a ring buffer of about two seconds of samples,
filled by the playback thread in blocks of about 20 ms and read by the device on its own
schedule, so a busy GUI or a slow disk doesn't stop the sound.

Plain NumPy, no Qt: samples are float32 frames, one row a frame and one column a channel (so a
block's bytes are interleaved), at the device's rate."""

from __future__ import annotations

import threading

import numpy as np
from numpy.typing import NDArray

Block = NDArray[np.float32]  # frames × channels

BLOCK_SECONDS = 0.02  # what the playback thread decodes at a time (A4.1)
AHEAD_SECONDS = 2.0  # what the ring buffer holds (A4.1)
DEVICE_SECONDS = 0.25  # the sound device's own buffer (A4.1)
STEP_BLOCKS = 5  # blocks decoded at most per turn of the playback thread's loop, so the device's
# pulls are served between them


def frames_of(seconds: float, rate: int) -> int:
    """How many frames `seconds` is at `rate`, at least one."""
    return max(1, round(seconds * rate))


def to_bytes(block: Block) -> bytes:
    """A block as the device takes it: little-endian float32, channels interleaved."""
    return np.ascontiguousarray(block, dtype="<f4").tobytes()


def silence(frames: int, channels: int) -> Block:
    """`frames` frames of nothing."""
    return np.zeros((frames, channels), np.float32)


class Ring:
    """A ring buffer of `capacity` frames of `channels` channels. One thread writes and another
    may read; a lock keeps each step whole."""

    def __init__(self, capacity: int, channels: int) -> None:
        if capacity < 1 or channels < 1:
            raise ValueError(f"a ring of {capacity} frames of {channels} channels")
        self._data = silence(capacity, channels)
        self._start = 0  # the oldest frame held
        self._held = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return len(self._data)

    @property
    def channels(self) -> int:
        return int(self._data.shape[1])

    @property
    def held(self) -> int:
        """Frames written and not yet read."""
        return self._held

    @property
    def free(self) -> int:
        """Frames that can be written."""
        return self.capacity - self._held

    def write(self, block: Block) -> int:
        """Writes as much of `block` as fits; gives how many frames that was."""
        if block.ndim != 2 or block.shape[1] != self.channels:
            raise ValueError(f"a block of {block.shape}, for {self.channels} channels")
        with self._lock:
            n = min(len(block), self.capacity - self._held)
            end = (self._start + self._held) % self.capacity
            first = min(n, self.capacity - end)
            self._data[end : end + first] = block[:first]
            self._data[: n - first] = block[first:n]
            self._held += n
            return n

    def read(self, frames: int) -> Block:
        """Up to `frames` of the oldest frames held, taken out of the ring."""
        with self._lock:
            n = max(0, min(frames, self._held))
            first = min(n, self.capacity - self._start)
            out = np.concatenate(
                (self._data[self._start : self._start + first], self._data[: n - first])
            )
            self._start = (self._start + n) % self.capacity
            self._held -= n
            return out

    def clear(self) -> None:
        with self._lock:
            self._start = self._held = 0

    def drop(self, frames: int) -> int:
        """Takes back up to `frames` of the newest frames held, as if never written; gives how
        many that was."""
        with self._lock:
            n = max(0, min(frames, self._held))
            self._held -= n
            return n


class Stream:
    """The samples on their way to the device, one song's after another's (A4.2): the ring they
    wait in, whether the decoders have given their last, and how many frames have been fed and
    taken. A frame's place in the stream is the count of frames fed before it, so `taken` is the
    place of the next frame the device reads."""

    def __init__(self, rate: int, channels: int, ahead: float = AHEAD_SECONDS) -> None:
        self.rate, self.channels = rate, channels
        self.block = frames_of(BLOCK_SECONDS, rate)
        self.ring = Ring(frames_of(ahead, rate), channels)
        self.finished = False  # the decoder has given its last block
        self.written = 0  # frames fed
        self.taken = 0  # frames the device has read out
        self.short = 0  # times the device asked and the ring was empty before the end

    def wants(self, step: int = STEP_BLOCKS) -> int:
        """How many blocks to decode now: as many as fit, `step` at most; none once finished."""
        return 0 if self.finished else min(step, self.ring.free // self.block)

    def feed(self, block: Block) -> None:
        """A decoded block into the ring; `wants` said there was room for it."""
        if self.ring.write(block) < len(block):
            raise OverflowError(f"no room for {len(block)} frames ({self.ring.free} free)")
        self.written += len(block)

    def finish(self) -> None:
        """The decoder has nothing more: what the ring holds is the song's end."""
        self.finished = True

    def reopen(self) -> None:
        """More is coming after all (a song to follow, or a seek): `wants` asks for it again."""
        self.finished = False

    def cut(self, at: int) -> int:
        """Takes back every frame fed from place `at` on, so what is fed next follows the frame
        before it; gives how many frames that was. The device has taken what is before `taken`, so
        `at` is never before it."""
        if not self.taken <= at <= self.written:
            raise ValueError(
                f"cutting at {at}: the device has taken {self.taken}, {self.written} fed"
            )
        n = self.ring.drop(self.written - at)
        self.written -= n
        return n

    def take(self, frames: int) -> Block:
        """What the device reads: up to `frames` frames, fewer when the ring runs short."""
        out = self.ring.read(frames)
        self.taken += len(out)
        if len(out) < frames and not self.finished:
            self.short += 1
        return out

    @property
    def drained(self) -> bool:
        """The decoder has finished and the device has taken every frame."""
        return self.finished and self.ring.held == 0


RECENT_SECONDS = 1.0  # what the analyzer's ring holds (A4.3): the device's buffer and a frame's
# 4,096 samples behind what it has played, with room to spare


class Recent:
    """The analyzer's ring buffer (A4.3, A5.2): the last second of samples the device took, each
    at its place in the stream, written by the playback thread as the device takes them (`add`)
    and read by the GUI thread as a view draws (`newest`), up to the place the device has played
    (`hear`), so what is drawn is what is heard. A lock keeps each step whole.

    It is written only while a view that draws the spectrum is shown and playing (A5.5): each
    view says so (`want`), and while none does the playback thread copies nothing."""

    def __init__(self, seconds: float = RECENT_SECONDS) -> None:
        self._seconds = seconds
        self._lock = threading.Lock()
        self._data = silence(1, 1)
        self.rate = 0
        self._start = self._end = 0  # the places of the oldest frame held and after the newest
        self._heard = 0  # the place the device has played up to
        self._wanting: set[object] = set()
        self.on = False  # a view wants it: the playback thread copies into it

    def start(self, rate: int, channels: int) -> None:
        """A new stream (a song asked for, or the device changed): nothing held, at `rate`."""
        with self._lock:
            self.rate = rate
            self._data = silence(frames_of(self._seconds, rate), channels)
            self._start = self._end = self._heard = 0

    def want(self, view: object, wanted: bool) -> None:
        """`view` draws the spectrum now (`wanted`), or no longer does: copying runs while any
        view does (A5.5)."""
        with self._lock:
            if wanted:
                self._wanting.add(view)
            else:
                self._wanting.discard(view)
            self.on = bool(self._wanting)

    def add(self, block: Block, place: int) -> None:
        """The frames the device took, the first at `place` in the stream; skipped while no view
        wants them, or when they aren't of the stream this was started for."""
        if not self.on or not len(block):
            return
        with self._lock:
            data = self._data
            if block.ndim != 2 or block.shape[1] != data.shape[1]:
                return
            if place != self._end:  # after a gap (nothing copied for a while): what was is stale
                self._start = place
            end = place + len(block)
            block = block[-len(data) :]
            data[np.arange(end - len(block), end) % len(data)] = block
            self._end = end

    def hear(self, place: int) -> None:
        """The device has played up to `place` in the stream."""
        with self._lock:
            self._heard = place

    def newest(self, frames: int) -> Block | None:
        """The `frames` frames the device played last, silence where none is held; None when
        nothing is."""
        with self._lock:
            data = self._data
            capacity = len(data)
            oldest = max(self._start, self._end - capacity)
            end = min(self._heard, self._end)
            if end <= oldest:
                return None
            start = end - frames
            out = silence(frames, data.shape[1])
            held_from = max(start, oldest)
            out[held_from - start :] = data[np.arange(held_from, end) % capacity]
            return out
