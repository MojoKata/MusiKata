"""Garbage collected on the GUI thread only (src/musikata/garbage.py, A1.3): the rule, from the
counts and the time since the last whole collection, and the timer that asks it."""

import gc

from fakes import FakeClock
from PySide6.QtCore import QObject

from musikata import garbage

T = (2000, 10, 10)  # Python's own thresholds


def test_nothing_is_collected_until_the_youngest_generation_passes_its_threshold():
    assert garbage.due((0, 0, 0), T, 0.0) is None
    assert garbage.due((2000, 10, 10), T, 1e9) is None  # at it is not past it
    assert garbage.due((2001, 0, 0), T, 0.0) == 0


def test_the_oldest_generation_past_its_threshold_is_collected_with_those_younger():
    assert garbage.due((2001, 10, 0), T, 0.0) == 0
    assert garbage.due((2001, 11, 0), T, 0.0) == 1
    whole = garbage.WHOLE_EVERY
    assert garbage.due((2001, 0, 11), T, whole) == 2
    assert garbage.due((2001, 11, 11), T, whole) == 2


def test_a_whole_collection_waits_its_time_the_one_younger_going_meanwhile():
    whole = garbage.WHOLE_EVERY
    assert garbage.due((2001, 11, 11), T, whole - 1) == 1
    assert garbage.due((2001, 0, 11), T, whole - 1) == 0


class FakeGc:
    """The gc module's counts and collections, as a test sets and sees them."""

    def __init__(self):
        self.count, self.collected = (0, 0, 0), []

    def collect(self, generation):
        self.collected.append(generation)


def collector(clock):
    fake = FakeGc()
    return garbage.Collector(clock, lambda: fake.count, lambda: T, fake.collect), fake


def test_the_collector_collects_what_is_due_and_keeps_the_time_of_the_whole_collection():
    clock = FakeClock()
    c, fake = collector(clock)
    assert c.look() is None and fake.collected == []
    fake.count = (2001, 11, 11)
    assert c.look() == 1  # MusiKata just started: a whole collection waits
    clock.advance(seconds=garbage.WHOLE_EVERY)
    assert c.look() == 2
    assert c.look() == 1  # the counts are the fake's: they say the same, but the time doesn't
    assert fake.collected == [1, 2, 1]


def test_a_window_closed_collects_the_whole_heap_at_once_and_the_next_one_waits_its_time():
    clock = FakeClock()
    c, fake = collector(clock)
    clock.advance(seconds=garbage.WHOLE_EVERY)
    c.full()
    fake.count = (2001, 11, 11)
    assert c.look() == 1 and fake.collected == [2, 1]
    clock.advance(seconds=garbage.WHOLE_EVERY)
    assert c.look() == 2


def test_started_python_collects_no_more_on_its_own_and_the_timer_looks(qtbot, monkeypatch):
    looked = []
    monkeypatch.setattr(garbage.Collector, "look", lambda self: looked.append(self))
    gc.enable()
    parent = QObject()
    try:
        c = garbage.start(parent, FakeClock(), every=0.001)
        assert not gc.isenabled()
        qtbot.waitUntil(lambda: len(looked) >= 2, timeout=5_000)
        assert looked[0] is c
    finally:
        gc.disable()  # as the suite runs (tests/conftest.py)
        del parent
