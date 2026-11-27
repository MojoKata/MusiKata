"""Fakes for the edges the core is given (docs/process/coding.md, "Thin edges, passed in")."""

import os
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot


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


def played(index, plays, computer="this-computer", when=datetime(2026, 11, 25, 20, 41, tzinfo=UTC)):
    """Plays counted in `index` as playing them would count them (rootfiles.count): `plays` the
    times each song, by path, was played on `computer`."""
    from musikata_core import rootfiles

    def write(c):
        for path, n in plays.items():
            (song,) = c.execute("SELECT id FROM song WHERE path = ?", (path,)).fetchone()
            for _ in range(n):
                rootfiles.count(c, computer, song, when)

    index.write(write).result()


def wav(path, seed, title=None):
    """A tenth of a second of WAV at `path` (folders made), its audio, and so its hash (A2.3), made
    from `seed`, and its title tagged when given: a file the scan reads in a millisecond."""
    import os
    import wave

    import mutagen.id3
    import mutagen.wave

    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(bytes((seed * 7 + i) % 256 for i in range(800)))
    if title:
        f = mutagen.wave.WAVE(str(path))
        f.add_tags()
        f.tags.add(mutagen.id3.TIT2(encoding=3, text=title))
        f.save()


class FakeEngine(QObject):
    """The engine's signals and slots, playing nothing: a song begins as soon as it is asked
    for, and ends, fails, moves or joins the song told to follow when a test says so (`join`).
    `ticket` is the song playing's, `follower` the ticket and path told to follow it (`told`, each
    in turn); `levels` each song's ReplayGain as asked, by file name, in order."""

    began = Signal(int, str, float)
    joined = Signal(int, str, float)
    moved = Signal(float)
    sought = Signal(int)
    pausedChanged = Signal(bool)
    ended = Signal(int)
    stopped = Signal(int)
    failed = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.asked = []  # what it was asked, in order: ("play", path), ("pause",), …
        self.path = ""
        self.ticket = 0
        self.follower = (0, "")
        self.told = []  # the songs told to follow, by file name ("" for nothing), in order
        self.levels = []  # (file name, ReplayGain) of each song asked to play or follow
        self.device = None  # the device chosen, as told
        self.holding = False
        self.at = 0.0

    @Slot()
    def setup(self):
        pass

    @Slot(str)
    def choose_device(self, chosen):
        self.device = chosen

    @Slot(str, int, float, float)
    def play(self, path, ticket, level, at=0.0):
        self.asked.append(("play", path))
        self.at = at  # where the song was asked to start, in seconds
        self.levels.append((os.path.basename(path), round(level, 4)))
        self.path, self.ticket, self.follower = path, ticket, (0, "")
        self.began.emit(ticket, path, 42.0)

    @Slot(int, int, str, float)
    def follow(self, after, ticket, path, level):
        self.told.append(os.path.basename(path))
        if path:
            self.levels.append((os.path.basename(path), round(level, 4)))
        if after == self.ticket:
            self.follower = (ticket, path)

    def join(self):
        """The device reaches the song told to follow."""
        ticket, path = self.follower
        self.path, self.ticket, self.follower = path, ticket, (0, "")
        self.joined.emit(ticket, path, 42.0)

    @Slot(int, float)
    def seek(self, ticket, seconds):
        """Says it is done at once, unless `holding`: then when the test says (`sought`)."""
        self.asked.append(("seek", round(seconds, 3)))
        if not self.holding:
            self.sought.emit(ticket)

    def seeks(self):
        return [a[1] for a in self.asked if a[0] == "seek"]

    @Slot()
    def pause(self):
        self.asked.append(("pause",))
        self.pausedChanged.emit(True)

    @Slot()
    def resume(self):
        self.asked.append(("resume",))
        self.pausedChanged.emit(False)

    @Slot()
    def stop(self):
        self.asked.append(("stop",))
        if self.path:
            self.path = ""
            self.stopped.emit(self.ticket)

    @Slot(float)
    def set_volume(self, gain):
        self.asked.append(("volume", round(gain, 3)))

    @Slot()
    def shutdown(self):
        self.moveToThread(QCoreApplication.instance().thread())

    def played(self):
        return [os.path.basename(a[1]) for a in self.asked if a[0] == "play"]
