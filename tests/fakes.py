"""Fakes for the edges the core is given (docs/process/coding.md, "Thin edges, passed in")."""

from datetime import UTC, datetime, timedelta


class FakeClock:
    """A clock a test moves: now() starts at `start` and moves only by advance()."""

    def __init__(self, start=datetime(2026, 11, 25, 12, 0, tzinfo=UTC)):
        self._now = start
        self._mono = 1000.0

    def now(self):
        return self._now

    def monotonic(self):
        return self._mono

    def advance(self, **delta):
        step = timedelta(**delta)
        self._now += step
        self._mono += step.total_seconds()
