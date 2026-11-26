"""The queue (A4.2, R7.1 to R7.3): a list of song ids with a cursor and a shuffle order, plain data
with no Qt, device or clock in it, so every rule of playing one song after another is tested on its
own (docs/process/coding.md).

The queue holds entries, each a song id with a key of its own (a song can be in the queue twice)
and whether the user added it (**Play next**, **Add to queue**, R7.2), in the order they play:
those before the cursor have played, the one at it is the current song, the rest are to come. A
cursor past the end means the queue has played out (repeat Off). While shuffling (R7.3) it also
keeps the order the songs had before, to go back to when shuffle is turned off.

What plays after the current song is asked of `following` before it is needed, so the gapless join
of A4.2 can open the next song ahead of the end without moving the queue; `ended` then moves it."""

from __future__ import annotations

import itertools
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace

OFF, ALL, ONE = "off", "all", "one"
REPEATS = (OFF, ALL, ONE)  # the order the repeat button cycles through (R7.3)


@dataclass(frozen=True)
class Entry:
    """A song in the queue: its id in the index, a key that tells it from the same song queued
    twice, and whether the user added it (R7.2)."""

    key: int
    song: int
    added: bool = False


class Queue:
    """The queue of R7.2, shuffled and repeated as R7.3 says. `rng` draws the shuffle orders, so a
    test gives a seeded one and gets the same order every run."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng if rng is not None else random.Random()
        self._order: list[Entry] = []  # the play order
        self._natural: list[Entry] = []  # the same entries in the order shuffle off returns to
        self._cursor = 0
        self._keys = itertools.count(1)
        self._lap_order: list[Entry] | None = None  # the next lap's order, once asked for
        self._shuffle = False
        self._repeat = OFF
        self.source = ""  # where the queue comes from: an album's title, "Songs", a folder's name

    # ---------- what it holds ----------

    @property
    def current(self) -> Entry | None:
        """The song playing, or cued to play; None when the queue is empty or has played out."""
        return self._order[self._cursor] if self._cursor < len(self._order) else None

    @property
    def played(self) -> list[Entry]:
        """The songs before the current one, in the order they played."""
        return self._order[: self._cursor]

    @property
    def upcoming(self) -> list[Entry]:
        """The songs to come after the current one, in the order they will play."""
        return self._order[self._cursor + 1 :]

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @property
    def repeat(self) -> str:
        """OFF, ALL or ONE (R7.3)."""
        return self._repeat

    def __len__(self) -> int:
        return len(self._order)

    def find(self, key: int) -> Entry | None:
        """The entry with that key, wherever it is; None when there is none."""
        return next((e for e in self._order if e.key == key), None)

    # ---------- playing ----------

    def play(
        self, songs: Sequence[int], start: int | None = None, source: str = ""
    ) -> Entry | None:
        """The queue becomes `songs` from `start` on (R7.1: the song played and the rest of its
        list after it), from `source`, and its first song is the current one. With `start` None
        (Play on an album, R7.1) the list plays from its first song, or, while shuffling, from one
        chosen at random; while shuffling, the rest follow in a random order (R7.3). Gives the
        current song, None for an empty list."""
        chosen = list(songs) if start is None else list(songs[start:])
        entries = [Entry(next(self._keys), song) for song in chosen]
        self._natural = list(entries)
        if self._shuffle and entries:
            first = 0 if start is not None else self._rng.randrange(len(entries))
            rest = entries[:first] + entries[first + 1 :]
            self._rng.shuffle(rest)
            entries = [entries[first], *rest]
        self._order = entries
        self._cursor = 0
        self._lap_order = None
        self.source = source
        return self.current

    def next(self) -> Entry | None:
        """Next (R6.5): the song after the current one, the queue's first again past its end with
        repeat All or One, else None (the queue has played out)."""
        if not self._order:
            return None
        if self._cursor < len(self._order) - 1:
            self._cursor += 1
        elif self._repeat != OFF:
            self._lap()
        else:
            self._cursor = len(self._order)
        return self.current

    def ended(self) -> Entry | None:
        """The current song played to its end: with repeat One it plays again, else as `next`."""
        if self._repeat == ONE and self.current is not None:
            return self.current
        return self.next()

    def following(self) -> Entry | None:
        """What `ended` would give, without moving: the song to open ahead of the current one's
        end (A4.2's join). None when nothing follows."""
        if self.current is None:
            return None
        if self._repeat == ONE:
            return self.current
        if self._cursor < len(self._order) - 1:
            return self._order[self._cursor + 1]
        return self._next_lap()[0] if self._repeat == ALL else None

    def after_following(self) -> Entry | None:
        """The song `ended` would give after the one `following` gives, without moving: what
        follows the song to be joined, so ReplayGain can tell whether its album plays in order
        (R7.5). None when nothing would. While shuffling with repeat All, a lap after the next one
        isn't drawn yet: for a queue of one song, it is that song again."""
        if self.current is None:
            return None
        if self._repeat == ONE:
            return self.current
        rest = self._order[self._cursor + 1 : self._cursor + 3]
        while self._repeat == ALL and len(rest) < 2:  # a queue of one song laps twice
            rest += self._next_lap()[: 2 - len(rest)]
        return rest[1] if len(rest) > 1 else None

    def previous(self) -> Entry | None:
        """Previous (R6.5): the song before the current one; the first stays the first. A queue
        that has played out goes back to its last song."""
        if self._order and self._cursor > 0:
            self._cursor = min(self._cursor, len(self._order)) - 1
        return self.current

    def jump(self, key: int) -> Entry | None:
        """The entry with that key becomes the current song (a song chosen in Up next): those
        before it count as played. Nothing changes for a key not in the queue."""
        at = self._index(key)
        if at is not None:
            self._cursor = at
        return self.current

    # ---------- changing it (R7.2) ----------

    def play_next(self, songs: Sequence[int]) -> list[Entry]:
        """Play next: the songs right after the current one, ahead of those added before."""
        return self._insert(self._cursor + 1, songs)

    def add(self, songs: Sequence[int]) -> list[Entry]:
        """Add to queue: the songs after the current one and those the user added before it, ahead
        of the rest of the list the queue plays from."""
        upcoming = self.upcoming
        added = next((i for i, e in enumerate(upcoming) if not e.added), len(upcoming))
        return self._insert(self._cursor + 1 + added, songs)

    def _insert(self, at: int, songs: Sequence[int]) -> list[Entry]:
        """Puts the songs at `at` of the play order, as added by the user; into an empty or
        played-out queue they go at its end, the first of them the current song (cued, not
        started). The order shuffle off returns to takes them after the entry they follow."""
        entries = [Entry(next(self._keys), song, True) for song in songs]
        if not entries:
            return []
        if self.current is None:
            at = self._cursor = len(self._order)
        before = self._order[at - 1] if at > 0 else None
        self._order[at:at] = entries
        n = self._natural_index(before.key) + 1 if before is not None else 0
        self._natural[n:n] = entries
        self._lap_order = None
        return entries

    def move(self, key: int, to: int) -> bool:
        """Moves a song to come to place `to` among the songs to come (Up next's drag, R7.2);
        False for a key that isn't to come. While shuffling, the order shuffle off returns to stays
        as it was."""
        at = self._index(key)
        if at is None or at <= self._cursor:
            return False
        entry = self._order.pop(at)
        to = max(0, min(to, len(self._order) - self._cursor - 1))
        self._order.insert(self._cursor + 1 + to, entry)
        if not self._shuffle:
            self._natural = list(self._order)
        self._lap_order = None
        return True

    def remove(self, key: int) -> bool:
        """Takes a song to come, or one played, out of the queue (Up next's ×, R7.2); the current
        song stays. False when there is no such entry, or it is the current one."""
        at = self._index(key)
        if at is None or at == self._cursor:
            return False
        entry = self._order.pop(at)
        del self._natural[self._natural_index(entry.key)]
        if at < self._cursor:
            self._cursor -= 1
        self._lap_order = None
        return True

    def clear(self) -> None:
        """Empties the queue; shuffle and repeat stay as they are."""
        self._order, self._natural, self._cursor = [], [], 0
        self._lap_order = None
        self.source = ""

    # ---------- shuffle and repeat (R7.3) ----------

    def set_shuffle(self, on: bool) -> None:
        """Shuffle on: the songs to come play in a random order, those the user added still first;
        each song once, until all have played. Off: the songs to come go back to the order they
        had in their list."""
        if on == self._shuffle:
            return
        self._shuffle = on
        head, upcoming = self._order[: self._cursor + 1], self.upcoming
        if on:
            self._natural = list(self._order)
            added = [e for e in upcoming if e.added]
            rest = [e for e in upcoming if not e.added]
            self._rng.shuffle(rest)
            self._order = head + added + rest
        else:
            rank = {e.key: i for i, e in enumerate(self._natural)}
            self._order = head + sorted(upcoming, key=lambda e: rank[e.key])
            self._natural = list(self._order)
        self._lap_order = None

    def set_repeat(self, repeat: str) -> None:
        if repeat not in REPEATS:
            raise ValueError(f"no such repeat: {repeat}")
        self._repeat = repeat

    def cycle_repeat(self) -> str:
        """The repeat button: Off, All, One, and Off again (R7.3); gives the new one."""
        self._repeat = REPEATS[(REPEATS.index(self._repeat) + 1) % len(REPEATS)]
        return self._repeat

    def _next_lap(self) -> list[Entry]:
        """The order the queue plays in once more, with repeat All: as it was, or while shuffling
        a new random order whose first song isn't the one that just played. The same until the
        queue changes, so `following` and `ended` agree."""
        if self._lap_order is None:
            entries = [replace(e, added=False) for e in self._order]
            if self._shuffle:
                last = entries[-1] if entries else None
                self._rng.shuffle(entries)
                if len(entries) > 1 and entries[0] == last:
                    swap = self._rng.randrange(1, len(entries))
                    entries[0], entries[swap] = entries[swap], entries[0]
            self._lap_order = entries
        return self._lap_order

    def _lap(self) -> None:
        self._order = self._next_lap()
        if self._shuffle:
            lapped = {e.key: e for e in self._order}
            self._natural = [lapped[e.key] for e in self._natural]
        else:
            self._natural = list(self._order)
        self._cursor = 0
        self._lap_order = None

    def _index(self, key: int) -> int | None:
        return next((i for i, e in enumerate(self._order) if e.key == key), None)

    def _natural_index(self, key: int) -> int:
        return next(i for i, e in enumerate(self._natural) if e.key == key)
