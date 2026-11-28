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

Each song comes with its ReplayGain (R7.5), which the feed multiplies in on the way into the ring,
ramped at a join (A4.4). The volume is applied last, as the device takes the samples (A4.4): after
the ring, so a change is heard at once rather than two seconds on, and ramped over 50 ms, so moving
it makes no zipper noise; the sink's own volume stays whole.

The output is the device chosen in Settings, else the system's default (R7.7). When the device in
use goes away (`QMediaDevices.audioOutputsChanged`), playback pauses, a new sink opens on the
default device at its own rate, and the stream goes on from the sample the old device had played
when the user presses play (A4.6).

Each sink is made on the GUI thread and handed to the playback thread (`Sinks`): making one takes
Qt's connection locks, which the GUI thread may hold while it waits on the GIL, so made on the
playback thread, which holds the GIL, it could freeze the app (docs/process/coding.md, "Threads
and processes"). The devices watched are made and connected as the engine is, on the GUI thread,
for the same reason: connecting to them takes those locks with the GIL held.

The GUI thread talks to the engine by queued signals only (the `Player` bridge, bridges.py), and
hears back the same way; each song asked for carries a ticket of the bridge's, which comes back
with what the engine says of it. What opens a song and which device it plays on are given to the
engine, so a test can hand in generated audio and Qt's device of its choice.

Each song comes with the tone the equalizer plays for it (R19, A4.4; `equalize`, told before the
song is asked for), which the feed filters in after ReplayGain, on the way into the ring, here on
the playback thread where the samples are made. A tone changed while its song plays is heard at
once: at the next turn of the loop (so a slider dragged builds one filter a turn, the latest), the
filter is built, 3 to 7 ms of NumPy's FFTs at 44.1 and 48 kHz, and the feed filters again what
the ring held from where the device has got to, the first blocks at once and the rest as the
loop goes round, while the device plays from its own buffer of 250 ms. Each filter built is kept
for the songs after (`eq.Designs`)."""

from __future__ import annotations

import logging
import threading
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

from musikata_core.audio import gain, stream
from musikata_core.audio.decode import DecodeError, Decoder
from musikata_core.audio.eq import Designs, Tone
from musikata_core.audio.join import Feed, Playing, Song
from musikata_core.audio.stream import Recent, Stream

log = logging.getLogger(__name__)

FALLBACK_RATE = 48_000  # when a device doesn't say which rate it prefers
NO_DEVICE = "there is no sound device"  # why a song failed when no device was there to play it
CLOSING = "MusiKata is closing"  # why a song asked for as the window closes didn't play
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


def device_id(device: QAudioDevice) -> str:
    """A device's id as text, as Settings keeps it (R13.7)."""
    return bytes(device.id().data()).decode("utf-8", "replace")


def chosen_output(
    chosen: str, outputs: Callable[[], list[QAudioDevice]] = QMediaDevices.audioOutputs
) -> QAudioDevice:
    """The device chosen in Settings, by its id, when it is there; else the system's default
    (R7.7), which is a null device when there is none."""
    if chosen:
        found = next((d for d in outputs() if device_id(d) == chosen), None)
        if found is not None:
            return found
        log.info("the sound device chosen in Settings (%s) isn't there: the default plays", chosen)
    return QMediaDevices.defaultAudioOutput()


def output_format(device: QAudioDevice) -> QAudioFormat:
    """Float samples at the device's own rate (A4.1), in the channels `channels_for` chooses."""
    fmt = QAudioFormat()
    fmt.setSampleRate(device.preferredFormat().sampleRate() or FALLBACK_RATE)
    fmt.setChannelCount(channels_for(device.maximumChannelCount()))
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
    return fmt


class RingDevice(QIODevice):
    """What the sink reads: the stream's samples as bytes, at the volume (A4.4: last, ramped).
    Only copies them out, multiplied, and, while a view draws the spectrum, into the analyzer's
    ring (`recent`, A4.3), before the volume: the spectrum is the music's, whatever the volume.
    Open as it is made, unbuffered: QIODevice's own buffer would take from the ring ahead of the
    device."""

    def __init__(
        self, source: Stream, volume: gain.Volume | None = None, recent: Recent | None = None
    ) -> None:
        super().__init__()
        self._stream = source
        self._volume = volume if volume is not None else gain.Volume()
        self._recent = recent
        self._frame = 4 * source.channels
        self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)

    def readData(self, maxlen: int) -> bytes:
        place = self._stream.taken
        block = self._stream.take(maxlen // self._frame)
        if self._recent is not None:
            self._recent.add(block, place)
        return stream.to_bytes(self._volume.apply(block))

    def writeData(self, data: bytes | bytearray | memoryview, size: int) -> int:
        return -1

    def bytesAvailable(self) -> int:
        return self._stream.ring.held * self._frame

    def isSequential(self) -> bool:
        return True


SinkMaker = Callable[[QAudioDevice, QAudioFormat], QAudioSink | None]


class Sinks(QObject):
    """Makes the playback thread's sinks on the GUI thread, where this lives, and moves each to
    the thread that asked (A1.3, A4.1): a QAudioSink made holds Qt's connection locks while
    PySide holds the GIL, so made on the playback thread it could wait on a lock the GUI thread
    holds while that waits on the GIL, and neither would run again (docs/process/coding.md). The
    playback thread waits for it, the GIL let go, only as a song opens or moves to another device,
    when no sink plays; once closed, none is made and the wait ends."""

    _asked = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._wanted: tuple[QAudioDevice, QAudioFormat, QThread] | None = None
        self._made: QAudioSink | None = None
        self._ready = threading.Event()
        self._closed = False
        self._asked.connect(self._make, Qt.ConnectionType.QueuedConnection)

    def make(self, device: QAudioDevice, fmt: QAudioFormat) -> QAudioSink | None:
        """A sink on `device` in `fmt`, living on the calling thread: made here when this is the
        GUI thread, else made there and moved; None once closed."""
        here = Shiboken.getCppPointer(QThread.currentThread())
        if here == Shiboken.getCppPointer(self.thread()):
            return None if self._closed else QAudioSink(device, fmt)
        self._ready.clear()
        self._wanted = (device, fmt, QThread.currentThread())
        self._asked.emit()
        self._ready.wait()
        made, self._made = self._made, None
        return made

    @Slot()
    def _make(self) -> None:
        wanted, self._wanted = self._wanted, None
        if wanted is not None and not self._closed:
            device, fmt, thread = wanted
            sink = QAudioSink(device, fmt)
            sink.moveToThread(thread)
            self._made = sink
        self._ready.set()

    def close(self) -> None:
        """No sink is made from now on; a thread waiting for one is answered with none."""
        self._closed = True
        self._ready.set()


class Engine(QObject):
    """The songs playing, on the playback thread: its slots are called there, by queued signals,
    and what it says goes back the same way, each song named by the ticket it was asked for
    with."""

    began = Signal(int, str, float)  # the ticket, the path, its length in seconds (-1: unknown)
    outputChanged = Signal(str)  # the device in use went away: playing moved to this one, paused
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
        output: Callable[[], QAudioDevice] | None = None,
        fallback: Callable[[], QAudioDevice] = QMediaDevices.defaultAudioOutput,
        outputs: Callable[[], list[QAudioDevice]] = QMediaDevices.audioOutputs,
    ) -> None:
        """`output` gives the device to play on (by default the one chosen, `choose_device`, else
        the system's default); `fallback` the one to move to when it goes away (R7.7), and
        `outputs` the devices there are, looked at when Qt says they changed."""
        super().__init__()
        self._opener, self._output, self._fallback = opener, output, fallback
        self._outputs = outputs
        self._chosen = ""  # the device chosen in Settings, by its id; "" for the default
        self._timer: QTimer | None = None
        # the devices watched (A4.6), here where the engine is made, on the GUI thread, and moved
        # with it: connecting to them connects them inside Qt with the GIL held (`setup`)
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self._outputs_changed)
        self._device: QAudioDevice | None = None  # the one in use
        self._sink: QAudioSink | None = None
        self._started = False  # the sink was started (a sink opened by a move waits for play)
        self._io: RingDevice | None = None
        self._feed: Feed | None = None
        self._paused = False
        self._reported = -1.0
        self._level = 1.0  # the volume, as a linear gain (R6.5)
        self._volume: gain.Volume | None = None  # applied to what the device takes (A4.4)
        # what makes a sink: on the GUI thread, once on the playback thread (Sinks.make)
        self.make_sink: SinkMaker = QAudioSink
        # the analyzer's ring (A4.3): what the device took, for the spectrum's views (A5.2)
        self.analyzer = Recent()
        self.designs = Designs()  # the equalizer's filters built (A4.4), kept for the next songs
        self._tones: dict[int, Tone | None] = {}  # each song's tone as told, by ticket (R19)
        self._retones: dict[int, Tone | None] = {}  # tones changed for songs in the stream

    @Slot()
    def setup(self) -> None:
        """On the playback thread, as it starts: the timer that keeps the ring full. The devices
        are watched from the engine's making, on the GUI thread: PySide calls a sender's
        `connectNotify` with the GIL held, and QMediaDevices' connects it to Qt's own list of
        devices, under Qt's connection locks, so connected here it could wait on a lock the GUI
        thread holds while that waits on the GIL (docs/process/coding.md, "Threads and
        processes")."""
        self._timer = QTimer(self)
        self._timer.setInterval(round(stream.BLOCK_SECONDS * 1000))
        self._timer.timeout.connect(self._tick)

    # ---------- what the GUI asks ----------

    @Slot(str)
    def choose_device(self, chosen: str) -> None:
        """The device chosen in Settings, by its id ("" for the system's default, R7.7): the next
        song plays on it."""
        self._chosen = chosen

    @Slot(int, object)
    def equalize(self, ticket: int, tone: Tone | None) -> None:
        """The song asked for, or to be asked for, with `ticket` plays `tone` (None: the
        equalizer off, R19.1). One in the stream changes at the next turn of the loop, heard at
        once; the latest asked by then is the one built."""
        self._tones[ticket] = tone
        if self._feed is None:
            return
        if any(p.ticket == ticket for p in self._feed.flight):
            self._retones[ticket] = tone
        else:
            self._feed.retone(ticket, tone)  # a song to follow: it plays it when it joins

    @Slot(str, int, float, float)
    def play(self, path: str, ticket: int, level: float = 1.0, at: float = 0.0) -> None:
        """Plays the file at `path` from `at` seconds into it (0: its start; R1.8's restored
        place), in place of what was playing, its samples multiplied by `level` (its ReplayGain,
        R7.5)."""
        self._halt()
        device = self._output() if self._output is not None else chosen_output(self._chosen)
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
        self.analyzer.start(rate, channels)
        self._tones = {t: v for t, v in self._tones.items() if t >= ticket}
        self._feed = Feed(ring, lambda p: self._opener(p, rate, channels), designs=self.designs)
        tone = self._tones.get(ticket)
        self._feed.start(ticket, path, song, level, round(max(0.0, at) * rate), tone)
        if not self._fill(ring.ring.capacity):  # the whole ring before the first pull
            return
        if not self._open_sink(device, fmt, ring, start=True):
            return
        self.began.emit(ticket, path, self._length(song))
        assert self._timer is not None  # setup ran as the thread started
        self._timer.start()

    def _open_sink(
        self, device: QAudioDevice, fmt: QAudioFormat, ring: Stream, start: bool
    ) -> bool:
        """A sink on `device` reading `ring` at the volume, started or (after a move) waiting for
        play; False when it didn't open (and playing has stopped)."""
        rate, channels = fmt.sampleRate(), fmt.channelCount()
        made = self.make_sink(device, fmt)
        if made is None:
            self._fail(CLOSING)
            return False
        self._device = device
        self._sink = made
        self._sink.setBufferSize(stream.frames_of(stream.DEVICE_SECONDS, rate) * 4 * channels)
        self._volume = gain.Volume(self._level, stream.frames_of(gain.RAMP_SECONDS, rate))
        self._io = RingDevice(ring, self._volume, self.analyzer)
        self._started = start
        if start:
            self._sink.start(self._io)
        if self._sink.error() != QtAudio.Error.NoError:
            self._fail(f"the sound device didn't open ({self._sink.error().name})")
            return False
        return True

    @Slot(int, int, str, float)
    def follow(self, after: int, ticket: int, path: str, level: float = 1.0) -> None:
        """The song asked for with `after` is to be followed by `path`, asked for with `ticket`
        (0: by nothing), joined to it with no gap (A4.2), its samples multiplied by `level`."""
        if self._feed is not None:
            self._tones = {t: v for t, v in self._tones.items() if t >= after}
            self._feed.retone(ticket, self._tones.get(ticket))
            self._feed.follow(after, ticket, path, level)

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
        """Plays on; after a move to another device (A4.6), starts its sink from the sample the
        old one had played."""
        if self._sink is not None and self._paused:
            if self._started:
                self._sink.resume()
            else:
                assert self._io is not None
                self._started = True
                self._sink.start(self._io)
            self._paused = False
            self.pausedChanged.emit(False)

    @Slot(float)
    def set_volume(self, level: float) -> None:
        """The volume, a linear gain from 0 to 1 (`gain_of`), applied last as the device takes
        the samples (A4.4), ramped to from where it is; and to every song after."""
        self._level = level
        if self._volume is not None:
            self._volume.set(level)

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
        retones, self._retones = self._retones, {}
        for ticket, tone in retones.items():
            self._feed.retone(ticket, tone)
        if not self._fill():
            return
        error = self._sink.error()
        if error not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            if self._gone():  # the device went: playing moves, as when the list says so
                self._move()
                return
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
        self.analyzer.hear(frame)
        reached: list[Playing] = self._feed.hear(frame)
        for playing in reached:
            self.joined.emit(playing.ticket, playing.path, self._length(playing.song))
        position = self._feed.position(frame)
        if reached or abs(position - self._reported) >= MOVED_STEP:
            self._reported = position
            self.moved.emit(position)

    def _drop_sink(self) -> None:
        """The sink stopped and let go of, and what it read."""
        if self._sink is not None:
            self._sink.stop()
            Shiboken.delete(self._sink)
            self._sink = None
        if self._io is not None:
            self._io.close()
            Shiboken.delete(self._io)
            self._io = None
        self._device, self._volume, self._started = None, None, False

    # ---------- the device going away (A4.6, R7.7) ----------

    def _gone(self) -> bool:
        """Whether the device in use is no longer among the system's outputs."""
        if self._device is None:
            return False
        ours = device_id(self._device)
        return all(device_id(d) != ours for d in self._outputs())

    @Slot()
    def _outputs_changed(self) -> None:
        if self._sink is not None and self._gone():
            self._move()

    def _move(self) -> None:
        """The device in use went away: playing pauses, and goes on into a new sink on the
        default device, at its rate, from the sample the old device had played; it starts when
        the user presses play (A4.6)."""
        assert self._sink is not None and self._feed is not None and self._device is not None
        place = self._heard()
        self._report(place)
        was = self._device.description()
        self._drop_sink()
        device = self._fallback()
        if device.isNull():
            self._fail(NO_DEVICE)
            return
        fmt = output_format(device)
        rate, channels = fmt.sampleRate(), fmt.channelCount()
        ring = Stream(rate, channels)
        self.analyzer.start(rate, channels)
        failure = self._feed.move(ring, lambda p: self._opener(p, rate, channels), place)
        if failure is not None:
            self._fail(failure.why, failure.ticket)
            return
        if not self._fill(ring.ring.capacity) or not self._open_sink(device, fmt, ring, False):
            return
        log.warning(
            "the sound device %s went away: paused, and moved to %s at %d Hz",
            was, device.description(), rate,
        )  # fmt: skip
        self._reported = -1.0
        self._report(0)
        if not self._paused:
            self._paused = True
            self.pausedChanged.emit(True)
        self.outputChanged.emit(device.description())

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
        self._drop_sink()
        if self._feed is not None:
            self._feed.close()
            self._feed = None
        self._retones = {}
        self._reported = -1.0
        if self._paused:
            self._paused = False
            self.pausedChanged.emit(False)
        return was


class PlaybackThread:
    """The playback thread (A1.3, A4.1) and the engine living on it."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sinks: Sinks | None = Sinks()  # the engine's sinks, made on this, the GUI thread
        engine.make_sink = self._sinks.make
        self._thread: QThread | None = QThread()
        self._thread.setObjectName("playback")
        engine.moveToThread(self._thread)
        self._thread.started.connect(engine.setup)

    def start(self) -> None:
        if self._thread is not None:  # never once closed
            self._thread.start(QThread.Priority.TimeCriticalPriority)  # where the system allows

    def close(self) -> None:
        """Stops the song and the thread, waits for it to end, and deletes the thread and the
        engine: for closing. Deleted here, on the GUI thread, at once, never by a garbage
        collection on another thread (A1.3); not later (deleteLater), which needs the engine's
        thread running, as it isn't once ended or when no song played."""
        if self._thread is None:
            return
        if self._sinks is not None:  # a sink waited for is answered with none
            self._sinks.close()
        if self._thread.isRunning():
            QMetaObject.invokeMethod(
                self.engine, "shutdown", Qt.ConnectionType.BlockingQueuedConnection
            )
            self._thread.quit()
            self._thread.wait()
        self.engine.make_sink = QAudioSink
        Shiboken.delete(self.engine)
        Shiboken.delete(self._thread)
        if self._sinks is not None:
            Shiboken.delete(self._sinks)
        self._thread = self._sinks = None
