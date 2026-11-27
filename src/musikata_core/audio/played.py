"""When a song counts as played (R7.9): once 50 % of it, or 4 minutes, has been heard, whichever
comes first, and once for each time it is played.

What is heard is the place the device reports moving on while the song plays, step by step, each
step no longer than the time that passed on the clock (and a little slack, as reports come in
bursts), so a seek, or anything else that jumps the place, adds nothing:

- a seek forward passes over what it skips: a song sought past its middle counts only once as much
  has been heard as the rule asks;
- a seek back hears again what it goes back over, and that counts: what is measured is time spent
  listening, as a play counted by time is;
- a pause adds nothing while it lasts, and keeps what was heard before it;
- a new play starts from nothing heard: a song started again (Previous past its first seconds, a
  click on it), the next song reached by a gapless join (R7.6), and the same song again with repeat
  One. A song counted isn't counted again until it is played again; one stopped or left before the
  mark isn't counted at all.

`Listening` holds this for the song playing; the Player bridge tells it what the engine reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..clock import Clock

MOST = 240.0  # seconds heard that count any song, however long (R7.9's 4 minutes)
SLACK = 0.5  # seconds a step of the place may run ahead of the clock: reports come in bursts


def mark(length: float) -> float:
    """The seconds of a song `length` seconds long that must be heard for it to count: half of
    it, and never more than 4 minutes; 4 minutes when its length isn't known (0 or less)."""
    return min(length / 2, MOST) if length > 0 else MOST


@dataclass(frozen=True)
class Play:
    """A play counted: the song's id and when it was counted (UTC)."""

    song: int
    when: datetime


class Listening:
    """What has been heard of the song playing, on `clock`, and whether it has counted yet."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._song: int | None = None
        self._mark = MOST
        self._place = 0.0
        self._at = 0.0  # the clock when the place was last told
        self.heard = 0.0
        self.counted = False

    def begin(self, song: int | None, length: float, at: float = 0.0) -> None:
        """A new play of `song` (None: one that isn't counted, a file outside the library, R1.7),
        `length` seconds long, from `at` seconds into it: nothing heard of it yet."""
        self._song, self._mark = song, mark(length)
        self._place, self._at = at, self._clock.monotonic()
        self.heard, self.counted = 0.0, False

    def moved(self, place: float) -> Play | None:
        """The device has played up to `place` seconds into the song: what it moved on is heard,
        up to the time that passed. The play, the once it reaches the mark; None otherwise."""
        now = self._clock.monotonic()
        step = place - self._place
        if step > 0:
            self.heard += min(step, max(0.0, now - self._at) + SLACK)
        self._place, self._at = place, now
        if self._song is None or self.counted or self.heard < self._mark:
            return None
        self.counted = True
        return Play(self._song, self._clock.now())

    def sought(self, place: float) -> None:
        """A seek to `place` seconds: what it passes over isn't heard."""
        self._place, self._at = place, self._clock.monotonic()

    def stop(self) -> None:
        """The song stopped, or nothing plays: nothing more of it is heard, nor counted."""
        self._song = None
