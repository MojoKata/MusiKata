"""The clock every timed piece is given (docs/process/coding.md, "No test waits on real time"):
the 180-day cleanup of A2.9, the services' pace, the sleep timer. A test hands in one it moves."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The time, in UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds that only go forward, for measuring how long something takes."""
        ...


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()
