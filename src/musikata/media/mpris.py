"""The system's media controls on Linux (R7.8, A4.5): MPRIS 2, as `org.mpris.MediaPlayer2.musikata`
on the session bus, with QtDBus, so the desktop's media keys and sound menu show the song and work
it. The object `/org/mpris/MediaPlayer2` has the `org.mpris.MediaPlayer2` interface (Raise, Quit,
the player's name) and `org.mpris.MediaPlayer2.Player` (the status, the song's Metadata, the
Position, what can be done, the methods that do it, and the PropertiesChanged and Seeked signals);
what each holds is controls.py's.

The types are D-Bus's own, as desktops read them (a GLib client looks the length up as an int64 and
finds nothing in an int32). A property or a signal of an adaptor goes as its declared type
(Position, Seeked), but PySide6 turns a Python int into the smallest type that holds it, and its
QDBusArgument writes no int64 either. So an int64 inside a map (the Metadata's `mpris:length`) is
made by D-Bus itself: an adaptor of MusiKata's own, `/org/musikata/MusiKata/int64`, has the value
as a property declared int64, and a call to MusiKata itself for its properties (GetAll), which
QtDBus answers without the bus, gives it back as D-Bus wrote it; read down to that value, the
answer is sent on as it is (`int64`)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import ClassInfo, Property, QMetaType, QObject, Signal, Slot
from PySide6.QtDBus import (
    QDBusAbstractAdaptor,
    QDBusArgument,
    QDBusConnection,
    QDBusMessage,
    QDBusObjectPath,
)
from PySide6.QtGui import QWindow

from .controls import (
    NEXT,
    PAUSE,
    PLAY,
    PLAY_PAUSE,
    PREVIOUS,
    QUIT,
    RAISE,
    SEEK,
    SET_POSITION,
    STOP,
    VOLUME,
    Command,
    Song,
    State,
    changed,
    metadata,
    microseconds,
    player_properties,
)

log = logging.getLogger(__name__)

SERVICE = "org.mpris.MediaPlayer2.musikata"
PATH = "/org/mpris/MediaPlayer2"
ROOT = "org.mpris.MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
PROPERTIES = "org.freedesktop.DBus.Properties"
IDENTITY = "MusiKata"
DESKTOP_ENTRY = "musikata"  # the AppImage's musikata.desktop (A6.3)

# C++ types, which PySide6 takes by name where a Python type has none (its stubs want a type)
QLONGLONG: Any = "qlonglong"
QSTRINGLIST: Any = "QStringList"
QVARIANTMAP: Any = "QVariantMap"
INT64 = "org.musikata.MusiKata.Int64"  # the interface that makes an int64 (`int64`)
INT64_PATH = "/org/musikata/MusiKata/int64"


def seconds(microseconds: int) -> float:
    return microseconds / 1_000_000


def interface[T](name: str) -> Callable[[T], T]:
    """The decorator that names an adaptor's D-Bus interface."""
    # PySide6 takes the name in a dict, and the result decorates; its stubs say neither
    return ClassInfo({"D-Bus Interface": name})  # type: ignore[call-arg,return-value]


@interface(ROOT)
class RootAdaptor(QDBusAbstractAdaptor):
    """org.mpris.MediaPlayer2: what MusiKata is, and Raise and Quit."""

    def __init__(self, parent: QObject, mpris: Mpris) -> None:
        super().__init__(parent)
        self._mpris = mpris

    @Slot()
    def Raise(self) -> None:  # noqa: N802
        self._mpris.send(Command(RAISE))

    @Slot()
    def Quit(self) -> None:  # noqa: N802
        self._mpris.send(Command(QUIT))

    def _true(self) -> bool:
        return True

    def _false(self) -> bool:
        return False

    def _identity(self) -> str:
        return IDENTITY

    def _desktop_entry(self) -> str:
        return DESKTOP_ENTRY

    def _none(self) -> list[str]:
        return []

    CanQuit = Property(bool, _true)
    CanRaise = Property(bool, _true)
    HasTrackList = Property(bool, _false)
    Identity = Property(str, _identity)
    DesktopEntry = Property(str, _desktop_entry)
    SupportedUriSchemes = Property(QSTRINGLIST, _none)
    SupportedMimeTypes = Property(QSTRINGLIST, _none)


def flag(name: str) -> Callable[[PlayerAdaptor], bool]:
    """The getter of one of the Player's Can… properties."""
    return lambda adaptor: bool(adaptor._get(name))


@interface(PLAYER)
class PlayerAdaptor(QDBusAbstractAdaptor):
    """org.mpris.MediaPlayer2.Player: the song, its state and the commands."""

    Seeked = Signal(QLONGLONG)

    def __init__(self, parent: QObject, mpris: Mpris) -> None:
        super().__init__(parent)
        self._mpris = mpris
        self.setAutoRelaySignals(True)

    @Slot()
    def Next(self) -> None:  # noqa: N802
        self._mpris.send(Command(NEXT))

    @Slot()
    def Previous(self) -> None:  # noqa: N802
        self._mpris.send(Command(PREVIOUS))

    @Slot()
    def Pause(self) -> None:  # noqa: N802
        self._mpris.send(Command(PAUSE))

    @Slot()
    def PlayPause(self) -> None:  # noqa: N802
        self._mpris.send(Command(PLAY_PAUSE))

    @Slot()
    def Stop(self) -> None:  # noqa: N802
        self._mpris.send(Command(STOP))

    @Slot()
    def Play(self) -> None:  # noqa: N802
        self._mpris.send(Command(PLAY))

    @Slot(QLONGLONG)
    def Seek(self, offset: int) -> None:  # noqa: N802
        self._mpris.send(Command(SEEK, seconds(offset)))

    @Slot(QDBusObjectPath, QLONGLONG)
    def SetPosition(self, track: QDBusObjectPath, position: int) -> None:  # noqa: N802
        self._mpris.send(Command(SET_POSITION, seconds(position), track.path()))

    @Slot(str)
    def OpenUri(self, uri: str) -> None:  # noqa: N802
        """MusiKata names no URI schemes it opens (SupportedUriSchemes), so this does nothing."""
        log.info("MPRIS asked MusiKata to open %s, which it doesn't do", uri)

    def _get(self, name: str) -> Any:
        return self._mpris.properties[name]

    def _status(self) -> str:
        return str(self._get("PlaybackStatus"))

    def _metadata(self) -> dict[str, object]:
        return self._mpris.typed_metadata()

    def _volume(self) -> float:
        return float(self._get("Volume"))

    def _set_volume(self, level: float) -> None:
        self._mpris.send(Command(VOLUME, level))

    def _position(self) -> int:
        return microseconds(self._mpris.position())

    def _rate(self) -> float:
        return 1.0

    def _set_rate(self, rate: float) -> None:
        """MusiKata plays at one rate only (MinimumRate and MaximumRate), so this changes
        nothing."""

    def _true(self) -> bool:
        return True

    PlaybackStatus = Property(str, _status)
    Rate = Property(float, _rate, _set_rate)
    Metadata = Property(QVARIANTMAP, _metadata)
    Volume = Property(float, _volume, _set_volume)
    Position = Property(QLONGLONG, _position)
    MinimumRate = Property(float, _rate)
    MaximumRate = Property(float, _rate)
    CanGoNext = Property(bool, flag("CanGoNext"))
    CanGoPrevious = Property(bool, flag("CanGoPrevious"))
    CanPlay = Property(bool, flag("CanPlay"))
    CanPause = Property(bool, flag("CanPause"))
    CanSeek = Property(bool, flag("CanSeek"))
    CanControl = Property(bool, _true)


@interface(INT64)
class Int64Adaptor(QDBusAbstractAdaptor):
    """The int64 `int64` makes, as a property declared int64."""

    value = 0

    def _value(self) -> int:
        return self.value

    Value = Property(QLONGLONG, _value)


def no_strings() -> QDBusArgument:
    """An empty array of strings, as D-Bus's `as` (an empty Python list goes as `av`)."""
    empty = QDBusArgument()
    empty.beginArray(QMetaType(QMetaType.Type.QString))
    empty.endArray()
    return empty


class Mpris:
    """MPRIS 2 on `connection` (a Backend, controls.py): MusiKata's object and name on the bus,
    the commands sent to `send`, the position read from `position`. Raises RuntimeError when the
    bus can't be used."""

    def __init__(
        self,
        connection: QDBusConnection,
        send: Callable[[Command], None],
        position: Callable[[], float],
    ) -> None:
        if not connection.isConnected():
            raise RuntimeError(f"no session bus ({connection.lastError().message() or 'none'})")
        self._bus, self.send, self.position = connection, send, position
        self.properties = player_properties(State())
        self.metadata = metadata(None)
        self._int64_host = QObject()
        self._int64 = Int64Adaptor(self._int64_host)
        self._host = QObject()
        self._root = RootAdaptor(self._host, self)
        self._player = PlayerAdaptor(self._host, self)
        if not connection.registerObject(INT64_PATH, self._int64_host):
            raise RuntimeError(f"{INT64_PATH} is taken on this connection")
        if not connection.registerObject(PATH, self._host):
            connection.unregisterObject(INT64_PATH)
            raise RuntimeError(f"{PATH} is taken on this connection")
        # a second MusiKata takes a name of its own, as MPRIS has it
        self.service = SERVICE
        if not connection.registerService(SERVICE):
            self.service = f"{SERVICE}.instance{os.getpid()}"
            if not connection.registerService(self.service):
                self.close()
                raise RuntimeError(
                    f"{SERVICE} couldn't be taken: {connection.lastError().message()}"
                )
        log.info("the system's media controls: MPRIS, as %s", self.service)

    def int64(self, value: int) -> QDBusArgument:
        """`value` as D-Bus's int64, to send inside a map or as an argument (the module's
        docstring): MusiKata's own Int64 adaptor asked for its properties, and its answer read
        down to the value."""
        self._int64.value = value
        ask = QDBusMessage.createMethodCall(
            self._bus.baseService(), INT64_PATH, PROPERTIES, "GetAll"
        )
        ask.setArguments([INT64])
        reply = self._bus.call(ask)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            raise RuntimeError(f"no int64 from QtDBus: {reply.errorMessage()}")
        typed: QDBusArgument = reply.arguments()[0]  # a{sv}: {"Value": <int64>}
        typed.beginArray()  # into the map, at its one entry
        typed.beginArray()  # into the entry, at its key
        typed.asVariant()  # past the key, at the value's variant
        typed.beginArray()  # into the variant, at the int64
        return typed

    def typed_metadata(self) -> dict[str, object]:
        """The Metadata, each value of its D-Bus type: the track id an object path, the length an
        int64, the artists a list of strings."""
        out = dict(self.metadata)
        out["mpris:trackid"] = QDBusObjectPath(str(out["mpris:trackid"]))
        if "mpris:length" in out:
            out["mpris:length"] = self.int64(int(str(out["mpris:length"])))
        return out

    def _changed(self, properties: dict[str, object]) -> None:
        """PropertiesChanged, for the Player interface's properties given."""
        signal = QDBusMessage.createSignal(PATH, PROPERTIES, "PropertiesChanged")
        signal.setArguments([PLAYER, properties, no_strings()])
        self._bus.send(signal)

    def now_playing(self, song: Song | None) -> None:
        self.metadata = metadata(song)
        self._changed({"Metadata": self.typed_metadata()})

    def state(self, state: State, position: float) -> None:
        now = player_properties(state)
        news = changed(self.properties, now)
        self.properties = now
        if news:
            self._changed(news)

    def seeked(self, position: float) -> None:
        self._player.Seeked.emit(microseconds(position))

    def close(self) -> None:
        """Gives up the name and the objects."""
        self._bus.unregisterService(self.service)
        self._bus.unregisterObject(PATH)
        self._bus.unregisterObject(INT64_PATH)


def open_session(
    send: Callable[[Command], None], position: Callable[[], float], window: QWindow | None
) -> Mpris:
    """MPRIS on the session bus (controls.Opener)."""
    return Mpris(QDBusConnection.sessionBus(), send, position)
