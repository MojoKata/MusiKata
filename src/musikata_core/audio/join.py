"""One song running into the next in one stream (A4.2), and moving within a song (A4.6): plain
logic over the stream of stream.py and songs that give blocks, with no Qt, device or clock in it,
so every join and seek is shown sample for sample on generated songs (docs/process/coding.md).

`Feed` holds the songs on their way to the device. The song the device plays is the first; once
the last song being decoded is ten seconds from its end, the song told to follow it is opened and
its first blocks decoded, and when the last sample of the one has gone in, the next one's first
follows it, so the device never finds a gap. Songs come at their own rates and are resampled to
the device's here, on their way into the ring: songs of the same rate go through one resampler
one after the other, so the join is exactly what resampling them as one would give, and a song of
another rate starts a resampler of its own after the last one's end. A song's place in the stream
is kept: the device is heard to reach the next song at its first frame (`hear`), not when it was
decoded.

The songs are told by tickets, given by the caller: the same file can be in the queue twice, or
follow itself with repeat One. What follows a song can change until the device has taken the next
song's first frame: what the device hasn't taken is then decoded again from where it has got to,
with the new song after it."""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from .decode import DecodeError, Resampler, seek_plan
from .stream import BLOCK_SECONDS, STEP_BLOCKS, Block, Stream, frames_of

log = logging.getLogger(__name__)

OPEN_AHEAD = 10.0  # seconds before a song's end that the next one is opened (A4.2)
PRIME_BLOCKS = 5  # the next song's blocks decoded as it is opened, before they are needed


class Song(Protocol):
    """A song open for playing, as decode.Decoder is: its rate and length, its blocks at its rate
    in the device's channels from the sample `seek` put it at, and closing it."""

    @property
    def rate(self) -> int: ...

    @property
    def seconds(self) -> float | None: ...

    def seek(self, sample: int) -> None: ...

    def blocks(self, frames: int) -> Iterator[Block]: ...

    def close(self) -> None: ...


Opener = Callable[[str], Song]  # a song's path to it, open; raises DecodeError
Resampling = Callable[[int, int, int], Resampler]  # (rate, device, channels) to a resampler


@dataclass
class Playing:
    """A song on its way to the device: its ticket and path, the song, the place in the stream
    of its frame `offset` (its first frame there: 0 from its start, a seek's frame after one), the
    sample it decodes next, and what is still to decode (None once all of it has gone in)."""

    ticket: int
    path: str
    song: Song
    mark: int = 0
    offset: int = 0
    reached: int = 0
    blocks: Iterator[Block] | None = None
    primed: list[Block] = field(default_factory=list)


@dataclass(frozen=True)
class Failure:
    """A song that couldn't go on playing, and why."""

    ticket: int
    why: str


def why_of(error: Exception) -> str:
    """What a decoder's error says to the user: a DecodeError its own words, anything else its
    kind (logged with its trace, as a fault of MusiKata's)."""
    if isinstance(error, DecodeError):
        return str(error)
    return f"decoding failed ({type(error).__name__})"


def frames_until(samples: int, rate: int, device: int) -> int:
    """The device's frames that fall before `samples` samples at `rate` have passed: frame k falls
    at k / `device`, so the first frame of what follows them is this one."""
    return -(-samples * device // rate)


class Feed:
    """The songs on their way through one stream to the device (A4.2): the one it plays first,
    then those decoded after it, and the one opened to follow the last of them. `fill` decodes
    into the stream, `hear` says where the device has got to, `follow` and `seek` change what
    comes. Everything here runs on one thread, the device's pulls included."""

    def __init__(self, stream: Stream, opener: Opener, resampling: Resampling = Resampler) -> None:
        self.stream = stream
        self._opener, self._resampling = opener, resampling
        self.flight: list[Playing] = []  # the first is heard; the last is being decoded
        self._ahead: Playing | None = None  # opened to follow the last, not yet gone in
        self._followers: dict[int, tuple[int, str]] = {}  # a ticket to the ticket and path told
        # to follow it
        self._pending: list[Block] = []  # resampled, waiting for room in the ring
        self._done = False  # the last song has all gone in, and nothing follows it
        # the resampler the songs go through, from the place of the first frame it gives
        self._resampler: Resampler | None = None
        self._base = 0  # the place of the first frame it gives
        self._given = 0  # the samples given it
        self._drop = 0  # the frames it gives still to drop (a seek's)

    @property
    def heard(self) -> Playing | None:
        """The song the device plays."""
        return self.flight[0] if self.flight else None

    def start(self, ticket: int, path: str, song: Song) -> None:
        """`song` plays from its start, first in an empty stream."""
        playing = Playing(ticket, path, song, mark=self.stream.written)
        self.flight = [playing]
        self._decode(playing, 0)

    def close(self) -> None:
        """Every song let go of."""
        for playing in self.flight:
            playing.song.close()
        self.flight = []
        self._drop_ahead()

    # ---------- decoding ----------

    def _run(self, rate: int, base: int, drop: int = 0) -> None:
        """A resampler of its own from `rate`, its first frame at place `base`."""
        self._resampler = self._resampling(rate, self.stream.rate, self.stream.channels)
        self._base, self._given, self._drop = base, 0, drop

    def _decode(self, playing: Playing, frame: int) -> None:
        """`playing` decoded from its frame `frame` at the device's rate, which goes to place
        `playing.mark - playing.offset + frame` of the stream: from a sample a little before it
        where the resampler starts as it would have going through (decode.seek_plan)."""
        song = playing.song
        sample, drop = seek_plan(frame, song.rate, self.stream.rate)
        song.seek(sample)
        playing.blocks = song.blocks(frames_of(BLOCK_SECONDS, song.rate))
        playing.primed, playing.reached = [], sample
        self._run(song.rate, playing.mark - playing.offset + frame - drop, drop)

    def fill(self, step: int = STEP_BLOCKS) -> Failure | None:
        """Decodes up to `step` blocks, as the ring has room for them, running from each song into
        the next; opens the next song when it is due. A Failure when the song the device plays,
        or has started to take, can't go on; a song that fails before then is cut out, and the one
        before it ends there."""
        if not self.flight:
            return None
        self._open_due()
        steps = 0
        while True:
            self._feed_pending()
            if self._pending or steps >= step or self.stream.ring.free < self.stream.block:
                break
            if self._done:
                self.stream.finish()
                break
            last = self.flight[-1]
            try:
                block = self._next_block(last)
            except Exception as e:  # noqa: BLE001  (a song's fault stops the song, not the thread)
                failure = self._failed(last, e)
                if failure is not None:
                    return failure
                continue
            if block is None:
                last.blocks = None
                self._join()
                continue
            steps += 1
            last.reached += len(block)
            self._resample(block)
            self._open_due()
        return None

    def _resample(self, block: Block) -> None:
        assert self._resampler is not None
        self._given += len(block)
        self._out(self._resampler.resample(block))

    def _out(self, frames: Block) -> None:
        if self._drop:
            cut = min(self._drop, len(frames))
            frames, self._drop = frames[cut:], self._drop - cut
        if len(frames):
            self._pending.append(frames)

    def _feed_pending(self) -> None:
        while self._pending and self.stream.ring.free:
            frames = self._pending[0]
            n = min(len(frames), self.stream.ring.free)
            self.stream.feed(frames[:n])
            if n == len(frames):
                self._pending.pop(0)
            else:
                self._pending[0] = frames[n:]

    def _next_block(self, playing: Playing) -> Block | None:
        """The song's next block; None at its end."""
        if playing.blocks is None:
            return None
        if playing.primed:
            return playing.primed.pop(0)
        return next(playing.blocks, None)

    def _failed(self, playing: Playing, error: Exception) -> Failure | None:
        if not isinstance(error, DecodeError):
            log.error("decoding %s failed", playing.path, exc_info=error)
        why = why_of(error)
        at = self.flight.index(playing)
        if at == 0 or playing.mark < self.stream.taken:
            return Failure(playing.ticket, why)
        # not yet reached: the song before it ends where it ends, and the caller plays this one in
        # its turn, where it fails again and says why
        log.warning("couldn't play %s after %s: %s", playing.path, self.flight[at - 1].path, why)
        self._followers.pop(self.flight[at - 1].ticket, None)
        self._again()
        return None

    def _again(self) -> None:
        """What the device hasn't taken, decoded again from where it has got to: from the song it
        has started to take, those after it closed, to be opened again as they are due."""
        taken = self.stream.taken
        at = max([0] + [i for i, p in enumerate(self.flight) if p.mark < taken])
        for later in self.flight[at + 1 :]:
            later.song.close()
        del self.flight[at + 1 :]
        self._drop_ahead()
        self._pending, self._done = [], False
        self.stream.cut(taken)
        self.stream.reopen()
        playing = self.flight[at]
        self._decode(playing, taken - playing.mark + playing.offset)

    def _drop_ahead(self) -> None:
        if self._ahead is not None:
            self._ahead.song.close()
            self._ahead = None

    def _due(self, playing: Playing) -> bool:
        """Whether the song after `playing` should be opened now: ten seconds before its end, or
        at its end when its length isn't known."""
        if playing.blocks is None:
            return True
        seconds = playing.song.seconds
        if seconds is None:
            return False
        return (seconds - OPEN_AHEAD) * playing.song.rate <= playing.reached

    def _open_due(self) -> None:
        last = self.flight[-1]
        if self._ahead is None and last.ticket in self._followers and self._due(last):
            self._open(last)

    def _open(self, last: Playing) -> None:
        """Opens the song to follow `last` and decodes its first blocks (A4.2); one that can't
        be opened isn't joined, and `last` ends there."""
        ticket, path = self._followers[last.ticket]
        try:
            song = self._opener(path)
        except Exception as e:  # noqa: BLE001  (a song that won't open isn't played, here)
            self._unjoinable(last, path, e)
            return
        blocks = song.blocks(frames_of(BLOCK_SECONDS, song.rate))
        playing = Playing(ticket, path, song, blocks=blocks)
        try:
            playing.primed = list(itertools.islice(blocks, PRIME_BLOCKS))
        except Exception as e:  # noqa: BLE001
            song.close()
            self._unjoinable(last, path, e)
            return
        self._ahead = playing

    def _unjoinable(self, last: Playing, path: str, error: Exception) -> None:
        if not isinstance(error, DecodeError):
            log.error("opening %s failed", path, exc_info=error)
        log.warning("couldn't open %s to follow %s: %s", path, last.path, why_of(error))
        del self._followers[last.ticket]

    def _join(self) -> None:
        """The last song has all gone in: the song opened to follow it goes in after it, through
        the same resampler at the same rate, else after its end; with none, the stream ends."""
        last = self.flight[-1]
        if self._ahead is None and last.ticket in self._followers:
            self._open(last)
        assert self._resampler is not None
        following = self._ahead
        if following is not None and following.song.rate == self._resampler.rate:
            following.mark = self._base + frames_until(
                self._given, following.song.rate, self.stream.rate
            )
        else:
            self._out(self._resampler.flush())
            if following is None:
                self._done = True
                return
            following.mark = self.stream.written + sum(len(f) for f in self._pending)
            self._run(following.song.rate, following.mark)
        self.flight.append(following)
        self._ahead = None

    # ---------- what the device has played ----------

    def hear(self, frame: int) -> list[Playing]:
        """The device has played the stream up to place `frame`: the songs it has reached since,
        in order, each the one it plays now in place of the one before (which is closed)."""
        reached = []
        while len(self.flight) > 1 and self.flight[1].mark <= frame:
            gone = self.flight.pop(0)
            gone.song.close()
            self._followers.pop(gone.ticket, None)
            reached.append(self.flight[0])
        return reached

    def position(self, frame: int) -> float:
        """Where the song the device plays is, in seconds, with the device at place `frame`.
        After a seek, the place sought until the device gets there."""
        playing = self.heard
        if playing is None:
            return 0.0
        return (max(0, frame - playing.mark) + playing.offset) / self.stream.rate

    # ---------- changes ----------

    def follow(self, after: int, ticket: int, path: str) -> bool:
        """The song with ticket `after` is to be followed by `path` with `ticket` (0: by
        nothing). What is in the stream after it is taken back and decoded again while the
        device has taken none of the song that followed it; once it has, nothing changes and this
        is False."""
        at = next((i for i, p in enumerate(self.flight) if p.ticket == after), None)
        if at is None:
            return False
        want = (ticket, path) if ticket else None
        if self._followers.get(after) == want:
            return True
        if at + 1 < len(self.flight) and self.flight[at + 1].mark < self.stream.taken:
            return False  # the device has it: the caller hears it begin
        if want is None:
            del self._followers[after]
        else:
            self._followers[after] = want
        last = self.flight[at]
        if at + 1 == len(self.flight) and last.blocks is not None:
            self._drop_ahead()  # opened again as it is due
        else:  # the change is in what has gone in
            self._again()
        return True

    def seek(self, ticket: int, frame: int) -> bool:
        """The song the device plays, if its ticket is `ticket`, goes on from its frame `frame`
        (A4.6): what the ring holds is taken back and that song decoded from there in its place,
        the songs after it closed (the next one is opened again when it is due). False for
        another ticket."""
        playing = self.heard
        if playing is None or playing.ticket != ticket:
            return False
        for later in self.flight[1:]:
            later.song.close()
        del self.flight[1:]
        playing.mark, playing.offset = self.stream.taken, max(0, frame)
        self._again()
        return True
