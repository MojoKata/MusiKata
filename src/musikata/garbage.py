"""Garbage is collected on the GUI thread only (A1.3). Python's cyclic collector otherwise runs on
whichever thread allocates when a collection is due: a scan's, a search's, the index writer's, the
playback thread, a pool's. When what it frees holds QObjects made in Python (a closed window's
bridges and models, a watcher's socket notifier), they are destroyed on that thread while the GUI
thread may be delivering an event to one of them, and MusiKata crashes. So the collector is turned
off as MusiKata starts, before any thread does, and a timer on the GUI thread collects instead:
the youngest generation when the counts say it is due, the older ones now and then, and the whole
heap when a window closes (app.Session). A closed window's objects are freed at its close, not
left to a collection (app.Shell.close); what this collects is what else made cycles.

`due` is the rule, from the counts and the time since the last whole collection; `Collector`
keeps that time and does what `due` says; `start` turns the collector off and looks every LOOK
seconds. The tests collect by the same Collector, between tests (tests/conftest.py)."""

from __future__ import annotations

import gc
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from musikata_core.clock import Clock

LOOK = 1.0  # seconds between looks at the counts: what can pile up between two is little
# the least time between two whole collections the counts ask for: a whole collection holds the
# GIL for tens of milliseconds, so it isn't let come every hundred looks; a window's close asks
# for one whenever it comes (`Collector.full`)
WHOLE_EVERY = 600.0

Counts = tuple[int, int, int]


def due(count: Counts, threshold: Counts, since_whole: float) -> int | None:
    """The generation to collect now (0, 1 or 2, each with those younger), or None: Python's own
    rule, from `count` (gc.get_count) and `threshold` (gc.get_threshold). Nothing until the
    youngest generation's allocations pass its threshold; then the oldest generation whose own
    count passed its threshold, the oldest of all (a whole collection) only once `since_whole`
    seconds since the last reach WHOLE_EVERY."""
    if count[0] <= threshold[0]:
        return None
    if count[2] > threshold[2] and since_whole >= WHOLE_EVERY:
        return 2
    if count[1] > threshold[1]:
        return 1
    return 0


class Collector:
    """Collects as `due` says each time it is asked to look, and the whole heap when asked
    (`full`), on the thread that asks: the GUI thread's timer (`start`) and app.Session, never
    another. `count`, `threshold` and `collect` are the gc module's, a test's stand-ins in tests."""

    def __init__(
        self,
        clock: Clock,
        count: Callable[[], Counts] = gc.get_count,
        threshold: Callable[[], tuple[int, ...]] = gc.get_threshold,
        collect: Callable[[int], object] = gc.collect,
    ) -> None:
        self._clock, self._count, self._threshold, self._collect = clock, count, threshold, collect
        self._whole = clock.monotonic()  # as MusiKata starts, nothing has piled up yet

    def look(self) -> int | None:
        """Collects what is due now; the generation collected, or None."""
        t = self._threshold()
        generation = due(self._count(), (t[0], t[1], t[2]), self._clock.monotonic() - self._whole)
        if generation is not None:
            self._collect(generation)
            if generation == 2:
                self._whole = self._clock.monotonic()
        return generation

    def full(self) -> None:
        """Collects the whole heap: a window closed, and what it left in cycles goes now."""
        self._collect(2)
        self._whole = self._clock.monotonic()


def start(parent: QObject, clock: Clock, every: float = LOOK) -> Collector:
    """Turns Python's own collections off and collects from a timer on `parent`'s thread, the GUI
    thread, every `every` seconds: called as MusiKata starts, before any thread does. The caller
    keeps the Collector for as long as it runs (the timer holds it weakly)."""
    gc.disable()
    collector = Collector(clock)
    timer = QTimer(parent)
    timer.setInterval(round(every * 1000))
    timer.timeout.connect(collector.look)
    timer.start()
    return collector
