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


class Stream:
    """One song's samples on their way to the device: the ring they wait in, whether the decoder
    has given its last, and how many frames the device has taken."""

    def __init__(self, rate: int, channels: int, ahead: float = AHEAD_SECONDS) -> None:
        self.rate, self.channels = rate, channels
        self.block = frames_of(BLOCK_SECONDS, rate)
        self.ring = Ring(frames_of(ahead, rate), channels)
        self.finished = False  # the decoder has given its last block
        self.taken = 0  # frames the device has read out
        self.short = 0  # times the device asked and the ring was empty before the end

    def wants(self, step: int = STEP_BLOCKS) -> int:
        """How many blocks to decode now: as many as fit, `step` at most; none once finished."""
        return 0 if self.finished else min(step, self.ring.free // self.block)

    def feed(self, block: Block) -> None:
        """A decoded block into the ring; `wants` said there was room for it."""
        if self.ring.write(block) < len(block):
            raise OverflowError(f"no room for {len(block)} frames ({self.ring.free} free)")

    def finish(self) -> None:
        """The decoder has nothing more: what the ring holds is the song's end."""
        self.finished = True

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
