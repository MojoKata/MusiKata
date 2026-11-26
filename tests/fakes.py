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


def fill(index, songs):
    """Rows in `index` as a scan would write them, without files: each song a dict of its path, its
    size and length if given, and Tags' fields (genres a tuple)."""
    from musikata_core import scanner
    from musikata_core.tags import AudioInfo, Tags

    batch = []
    for s in songs:
        s = dict(s)
        path, size, length = s.pop("path"), s.pop("size", 1000), s.pop("length", 60.0)
        info = AudioInfo("flac", length, 900, 44100, 2)
        batch.append(scanner.Read(scanner.Seen(path, size, 1), Tags(**s), info, path))
    index.write(lambda c: scanner.write_batch(c, batch, {})).result()
