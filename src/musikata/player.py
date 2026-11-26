"""The playback thread and the sound device (A4.1, A4.2, A4.6). `Engine` lives on a thread of its
own, which runs its own event loop: it decodes songs a block at a time into the ring buffer
(musikata_core.audio.stream) until two seconds are held, and a `QAudioSink` in pull mode, living
on the same thread, reads the ring through `RingDevice` on the device's schedule. So a busy GUI
thread or a slow disk never starves the device, and the device's pull only copies samples out
(docs/process/coding.md, "Threads and processes").

One song runs into the next in the same stream, the sink never stopped (A4.2): the GUI tells the
engine what follows the song playing (`follow`), and the engine's `Feed`
(musikata_core.audio.join) opens it ten seconds before the end and feeds its samples after the
last ones. The engine says the next song began (`joined`) when the device has played up to its
first sample, so the GUI changes then, not when it was decoded. A seek (A4.6) replaces what the
ring holds with the song from the place sought.

The GUI thread talks to the engine by queued signals only (the `Player` bridge, bridges.py), and
hears back the same way; each song asked for carries a ticket of the bridge's, which comes back
with what the engine says of it. What opens a song and which device it plays on are given to the
engine, so a test can hand in generated audio and Qt's device of its choice. Gain, the equalizer
and devices that come and go are the rest of slice 4's (A4.4 to A4.6)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import (
    QCoreApplication,
    QIODevice,
    QMetaObject,
    QObject,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSink, QMediaDevices, QtAudio
from shiboken6 import Shiboken

from musikata_core.audio import stream
from musikata_core.audio.decode import DecodeError, Decoder
from musikata_core.audio.join import Feed, Playing, Song
from musikata_core.audio.stream import Stream

log = logging.getLogger(__name__)

FALLBACK_RATE = 48_000  # when a device doesn't say which rate it prefers
NO_DEVICE = "there is no sound device"  # why a song failed when no device was there to play it
MOVED_STEP = 0.1  # the position is reported when it moves by this much (seconds)


class DecodedSong(Decoder):
    """A song's file through PyAV (musikata_core.audio.decode), opened as the engine opens a song:
    in the device's channels, at the file's own rate, which the engine's feed resamples to the
    device's."""

    def __init__(self, path: str, rate: int, channels: int) -> None:
        super().__init__(path, channels)


Opener = Callable[[str, int, int], Song]  # (path, rate, channels): raises DecodeError


def channels_for(most: int) -> int:
    """The channels MusiKata plays on a device that takes at most `most`: stereo, or mono on a
    device that has only one."""
    return 2 if most >= 2 else 1


def gain_of(level: float) -> float:
    """The sink's linear gain for the volume slider's `level` (0 to 1), which follows the ear:
    half way is half as loud, not a quarter (Qt's logarithmic scale)."""
    level = min(1.0, max(0.0, level))
    return QtAudio.convertVolume(
        level, QtAudio.VolumeScale.LogarithmicVolumeScale, QtAudio.VolumeScale.LinearVolumeScale
    )


def output_format(device: QAudioDevice) -> QAudioFormat:
    """Float samples at the device's own rate (A4.1), in the channels `channels_for` chooses."""
    fmt = QAudioFormat()
    fmt.setSampleRate(device.preferredFormat().sampleRate() or FALLBACK_RATE)
    fmt.setChannelCount(channels_for(device.maximumChannelCount()))
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
    return fmt


class RingDevice(QIODevice):
    """What the sink reads: the stream's samples as bytes. Only copies them out. Open as it is
    made, unbuffered: QIODevice's own buffer would take from the ring ahead of the device."""

    def __init__(self, source: Stream) -> None:
        super().__init__()
        self._stream = source
        self._frame = 4 * source.channels
        self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)

    def readData(self, maxlen: int) -> bytes:
        return stream.to_bytes(self._stream.take(maxlen // self._frame))

    def writeData(self, data: bytes | bytearray | memoryview, size: int) -> int:
        return -1

    def bytesAvailable(self) -> int:
        return self._stream.ring.held * self._frame

    def isSequential(self) -> bool:
        return True


class Engine(QObject):
    """The songs playing, on the playback thread: its slots are called there, by queued signals,
    and what it says goes back the same way, each song named by the ticket it was asked for
    with."""

    began = Signal(int, str, float)  # the ticket, the path, its length in seconds (-1: unknown)
    joined = Signal(int, str, float)  # the next song began, the one before played to its end
    moved = Signal(float)  # where the song is, in what the device has played
    sought = Signal(int)  # a seek asked for with this ticket was done, or couldn't be
    pausedChanged = Signal(bool)
    ended = Signal(int)  # the ticket, played to its end with nothing after it
    stopped = Signal(int)  # the ticket, stopped before its end
    failed = Signal(int, str)  # the ticket, and why it couldn't play

    def __init__(
        self,
        opener: Opener = DecodedSong,
        output: Callable[[], QAudioDevice] = QMediaDevices.defaultAudioOutput,
    ) -> None:
        super().__init__()
        self._opener, self._output = opener, output
        self._timer: QTimer | None = None
        self._sink: QAudioSink | None = None
        self._io: RingDevice | None = None
        self._feed: Feed | None = None
        self._paused = False
        self._reported = -1.0
        self._gain = 1.0  # the volume, as the sink's linear gain (R6.5)

    @Slot()
    def setup(self) -> None:
        """On the playback thread, as it starts: the timer that keeps the ring full."""
        self._timer = QTimer(self)
        self._timer.setInterval(round(stream.BLOCK_SECONDS * 1000))
        self._timer.timeout.connect(self._tick)

    # ---------- what the GUI asks ----------

    @Slot(str, int)
    def play(self, path: str, ticket: int) -> None:
        """Plays the file at `path` from its start, in place of what was playing."""
        self._halt()
        device = self._output()
        if device.isNull():
            self._failed(ticket, path, NO_DEVICE)
            return
        fmt = output_format(device)
        rate, channels = fmt.sampleRate(), fmt.channelCount()
        try:
            song = self._opener(path, rate, channels)
        except DecodeError as e:
            self._failed(ticket, path, str(e))
            return
        ring = Stream(rate, channels)
        self._feed = Feed(ring, lambda p: self._opener(p, rate, channels))
        self._feed.start(ticket, path, song)
        if not self._fill(ring.ring.capacity):  # the whole ring before the first pull
            return
        self._sink = QAudioSink(device, fmt)
        self._sink.setVolume(self._gain)
        self._sink.setBufferSize(stream.frames_of(stream.DEVICE_SECONDS, rate) * 4 * channels)
        self._io = RingDevice(ring)
        self._sink.start(self._io)
        if self._sink.error() != QtAudio.Error.NoError:
            self._fail(f"the sound device didn't open ({self._sink.error().name})")
            return
        self.began.emit(ticket, path, self._length(song))
        assert self._timer is not None  # setup ran as the thread started
        self._timer.start()

    @Slot(int, int, str)
    def follow(self, after: int, ticket: int, path: str) -> None:
        """The song asked for with `after` is to be followed by `path`, asked for with `ticket`
        (0: by nothing), joined to it with no gap (A4.2)."""
        if self._feed is not None:
            self._feed.follow(after, ticket, path)

    @Slot(int, float)
    def seek(self, ticket: int, seconds: float) -> None:
        """The song asked for with `ticket`, if the device plays it, goes on from `seconds`
        (A4.6); says `sought` either way."""
        if self._feed is not None:
            frame = round(max(0.0, seconds) * self._feed.stream.rate)
            if self._feed.seek(ticket, frame):
                self._reported = -1.0
                self._fill()
        self.sought.emit(ticket)

    @Slot()
    def pause(self) -> None:
        if self._sink is not None and not self._paused:
            self._sink.suspend()
            self._paused = True
            self.pausedChanged.emit(True)

    @Slot()
    def resume(self) -> None:
        if self._sink is not None and self._paused:
            self._sink.resume()
            self._paused = False
            self.pausedChanged.emit(False)

    @Slot(float)
    def set_volume(self, gain: float) -> None:
        """The volume, a linear gain from 0 to 1 (`gain_of`): the sink applies it last, after
        everything else (A4.4), at once and to every song after."""
        self._gain = gain
        if self._sink is not None:
            self._sink.setVolume(gain)

    @Slot()
    def stop(self) -> None:
        heard = self._feed.heard if self._feed is not None else None
        if self._halt() and heard is not None:
            self.stopped.emit(heard.ticket)

    @Slot()
    def shutdown(self) -> None:
        """Before the thread ends: the songs closed, the sink gone, and this object handed back
        to the GUI thread, so it is deleted there."""
        self._halt()
        if self._timer is not None:
            Shiboken.delete(self._timer)
            self._timer = None
        app = QCoreApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())

    # ---------- the playback thread's own work ----------

    @staticmethod
    def _length(song: Song) -> float:
        seconds = song.seconds
        return -1.0 if seconds is None else seconds

    def _fill(self, step: int = stream.STEP_BLOCKS) -> bool:
        """Decodes as many blocks as the ring has room for, `step` at most. False when the song
        playing failed (and has been stopped)."""
        assert self._feed is not None
        failure = self._feed.fill(step)
        if failure is not None:
            self._fail(failure.why, failure.ticket)
            return False
        return True

    def _heard(self) -> int:
        """The place in the stream the device has played up to."""
        assert self._sink is not None and self._feed is not None
        ring = self._feed.stream
        played = self._sink.processedUSecs() * ring.rate // 1_000_000
        return min(played, ring.taken)

    @Slot()
    def _tick(self) -> None:
        if self._sink is None or self._feed is None:
            return
        if not self._fill():
            return
        error = self._sink.error()
        if error not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            self._fail(f"the sound device stopped ({error.name})")
            return
        ring = self._feed.stream
        # the end: every frame taken, and the device has played what it held (it goes idle when
        # it finds nothing more; suspended, it is only paused)
        end = ring.drained and self._sink.state() == QtAudio.State.IdleState
        self._report(ring.taken if end else self._heard())
        if end:
            heard = self._feed.heard
            assert heard is not None
            self._halt()
            self.ended.emit(heard.ticket)

    def _report(self, frame: int) -> None:
        """Says each song the device has reached by place `frame`, and where it is."""
        assert self._feed is not None
        reached: list[Playing] = self._feed.hear(frame)
        for playing in reached:
            self.joined.emit(playing.ticket, playing.path, self._length(playing.song))
        position = self._feed.position(frame)
        if reached or abs(position - self._reported) >= MOVED_STEP:
            self._reported = position
            self.moved.emit(position)

    def _fail(self, why: str, ticket: int | None = None) -> None:
        heard = self._feed.heard if self._feed is not None else None
        path = heard.path if heard is not None else ""
        if ticket is None:
            ticket = heard.ticket if heard is not None else 0
        elif self._feed is not None:
            path = next((p.path for p in self._feed.flight if p.ticket == ticket), path)
        self._halt()
        self._failed(ticket, path, why)

    def _failed(self, ticket: int, path: str, why: str) -> None:
        """Says why a song couldn't play: in the log, and to the GUI (R14)."""
        log.warning("couldn't play %s: %s; nothing plays now", path, why)
        self.failed.emit(ticket, why)

    def _halt(self) -> bool:
        """Stops what plays, if anything, and lets go of it; whether something was playing."""
        if self._timer is not None:
            self._timer.stop()
        was = self._feed is not None
        if self._sink is not None:
            self._sink.stop()
            Shiboken.delete(self._sink)
            self._sink = None
        if self._io is not None:
            self._io.close()
            Shiboken.delete(self._io)
            self._io = None
        if self._feed is not None:
            self._feed.close()
            self._feed = None
        self._reported = -1.0
        if self._paused:
            self._paused = False
            self.pausedChanged.emit(False)
        return was


class PlaybackThread:
    """The playback thread (A1.3, A4.1) and the engine living on it."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._thread = QThread()
        self._thread.setObjectName("playback")
        engine.moveToThread(self._thread)
        self._thread.started.connect(engine.setup)

    def start(self) -> None:
        self._thread.start(QThread.Priority.TimeCriticalPriority)  # where the system allows it

    def close(self) -> None:
        """Stops the song and the thread, and waits for it to end: for closing."""
        if self._thread.isRunning():
            QMetaObject.invokeMethod(
                self.engine, "shutdown", Qt.ConnectionType.BlockingQueuedConnection
            )
            self._thread.quit()
            self._thread.wait()
