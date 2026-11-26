"""The playback thread and the sound device (A4.1). `Engine` lives on a thread of its own, which
runs its own event loop: it decodes a song a block at a time into the ring buffer
(musikata_core.audio.stream) until two seconds are held, and a `QAudioSink` in pull mode, living
on the same thread, reads the ring through `RingDevice` on the device's schedule. So a busy GUI
thread or a slow disk never starves the device, and the device's pull only copies samples out
(docs/process/coding.md, "Threads and processes").

The GUI thread talks to the engine by queued signals only (the `Player` bridge, bridges.py), and
hears back the same way. What opens a song and which device it plays on are given to the engine,
so a test can hand in generated audio and Qt's device of its choice. The engine plays one song at a
time; the queue (musikata_core.audio.queue) is the Player bridge's, which hands it the next song
when one ends. Gapless joins, seeking, gain, the equalizer and devices that come and go are the
rest of slice 4's (A4.2 to A4.6)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Protocol

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
from musikata_core.audio.stream import Block, Stream

log = logging.getLogger(__name__)

FALLBACK_RATE = 48_000  # when a device doesn't say which rate it prefers
NO_DEVICE = "there is no sound device"  # why a song failed when no device was there to play it
MOVED_STEP = 0.1  # the position is reported when it moves by this much (seconds)


class Song(Protocol):
    """A song open for playing, as `Decoder` is: its length, and its blocks at the device's rate
    and channels."""

    @property
    def seconds(self) -> float | None: ...

    def blocks(self, frames: int) -> Iterator[Block]: ...

    def close(self) -> None: ...


class DecodedSong:
    """A song's file through PyAV (musikata_core.audio.decode)."""

    def __init__(self, path: str, rate: int, channels: int) -> None:
        self._decoder = Decoder(path, rate, channels)

    @property
    def seconds(self) -> float | None:
        return self._decoder.info.seconds

    def blocks(self, frames: int) -> Iterator[Block]:
        return self._decoder.blocks(frames)

    def close(self) -> None:
        self._decoder.close()


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
    """One song at a time, on the playback thread: its slots are called there, by queued
    signals, and what it says goes back the same way."""

    began = Signal(str, float)  # the path, its length in seconds (-1: unknown)
    moved = Signal(float)  # where the song is, in what the device has played
    pausedChanged = Signal(bool)
    ended = Signal(str)  # the path, played to its end
    stopped = Signal(str)  # the path, stopped before its end
    failed = Signal(str, str)  # the path, and why it couldn't play

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
        self._stream: Stream | None = None
        self._song: Song | None = None
        self._blocks: Iterator[Block] | None = None
        self._path = ""
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

    @Slot(str)
    def play(self, path: str) -> None:
        """Plays the file at `path` from its start, in place of what was playing."""
        self._halt()
        device = self._output()
        if device.isNull():
            self._failed(path, NO_DEVICE)
            return
        fmt = output_format(device)
        rate, channels = fmt.sampleRate(), fmt.channelCount()
        try:
            self._song = self._opener(path, rate, channels)
        except DecodeError as e:
            self._failed(path, str(e))
            return
        self._path = path
        self._stream = Stream(rate, channels)
        self._blocks = self._song.blocks(self._stream.block)
        if not self._fill(self._stream.ring.capacity):  # the whole ring before the first pull
            return
        self._sink = QAudioSink(device, fmt)
        self._sink.setVolume(self._gain)
        self._sink.setBufferSize(stream.frames_of(stream.DEVICE_SECONDS, rate) * 4 * channels)
        self._io = RingDevice(self._stream)
        self._sink.start(self._io)
        if self._sink.error() != QtAudio.Error.NoError:
            self._fail(f"the sound device didn't open ({self._sink.error().name})")
            return
        seconds = self._song.seconds
        self.began.emit(path, -1.0 if seconds is None else seconds)
        assert self._timer is not None  # setup ran as the thread started
        self._timer.start()

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
        path = self._path
        if self._halt():
            self.stopped.emit(path)

    @Slot()
    def shutdown(self) -> None:
        """Before the thread ends: the song closed, the sink gone, and this object handed back
        to the GUI thread, so it is deleted there."""
        self._halt()
        if self._timer is not None:
            Shiboken.delete(self._timer)
            self._timer = None
        app = QCoreApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())

    # ---------- the playback thread's own work ----------

    def _fill(self, step: int = stream.STEP_BLOCKS) -> bool:
        """Decodes as many blocks as the ring has room for, `step` at most. False when the song
        failed (and has been stopped)."""
        assert self._stream is not None and self._blocks is not None
        for _ in range(self._stream.wants(step)):
            try:
                block = next(self._blocks)
            except StopIteration:
                self._stream.finish()
                break
            except DecodeError as e:
                self._fail(str(e))
                return False
            except Exception as e:  # noqa: BLE001  (a decoder's own fault stops the song, not the thread)
                log.exception("decoding %s failed", self._path)
                self._fail(f"decoding failed ({type(e).__name__})")
                return False
            self._stream.feed(block)
        return True

    @Slot()
    def _tick(self) -> None:
        if self._sink is None or self._stream is None:
            return
        if not self._fill():
            return
        error = self._sink.error()
        if error not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            self._fail(f"the sound device stopped ({error.name})")
            return
        position = self._sink.processedUSecs() / 1_000_000  # what the device has played
        if abs(position - self._reported) >= MOVED_STEP:
            self._reported = position
            self.moved.emit(position)
        # the end: every frame taken, and the device has played what it held (it goes idle when
        # it finds nothing more; suspended, it is only paused)
        if self._stream.drained and self._sink.state() == QtAudio.State.IdleState:
            path = self._path
            self._halt()
            self.ended.emit(path)

    def _fail(self, why: str) -> None:
        path = self._path
        self._halt()
        self._failed(path, why)

    def _failed(self, path: str, why: str) -> None:
        """Says why a song couldn't play: in the log, and to the GUI (R14)."""
        log.warning("couldn't play %s: %s; nothing plays now", path, why)
        self.failed.emit(path, why)

    def _halt(self) -> bool:
        """Stops what plays, if anything, and lets go of it; whether something was playing."""
        if self._timer is not None:
            self._timer.stop()
        was = bool(self._path)
        if self._sink is not None:
            self._sink.stop()
            Shiboken.delete(self._sink)
            self._sink = None
        if self._io is not None:
            self._io.close()
            Shiboken.delete(self._io)
            self._io = None
        if self._song is not None:
            self._song.close()
            self._song = None
        self._blocks = self._stream = None
        self._path = ""
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
