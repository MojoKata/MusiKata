"""The system's media controls on Windows (R7.8, A4.5): the System Media Transport Controls of
MusiKata's window, through PyWinRT (`winrt-Windows.Media`), so the media keys and the volume
overlay show the song and its cover and work it. A desktop app's controls are its window's,
reached through `ISystemMediaTransportControlsInterop.GetForWindow` (`for_window`).

`Smtc` maps what controls.py says onto the controls and their buttons onto Commands; it is given
the controls and the WinRT names it uses (`Names`), so a test hands it fakes on any platform. The
buttons are heard on a thread of WinRT's: the Commands go out through `send`, which takes them to
the GUI thread (MediaControls.commanded). What only Windows can show, the overlay itself, is tier
3's."""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from PySide6.QtGui import QWindow

from .controls import (
    NEXT,
    PAUSE,
    PAUSED,
    PLAY,
    PLAYING,
    PREVIOUS,
    SET_POSITION,
    STOP,
    STOPPED,
    Command,
    Song,
    State,
)

log = logging.getLogger(__name__)

# the buttons heard, by their SystemMediaTransportControlsButton name; the rest are never enabled
BUTTONS = {"PLAY": PLAY, "PAUSE": PAUSE, "STOP": STOP, "NEXT": NEXT, "PREVIOUS": PREVIOUS}
# MediaPlaybackStatus's name for each status
STATUSES = {PLAYING: "PLAYING", PAUSED: "PAUSED", STOPPED: "STOPPED"}

# ISystemMediaTransportControlsInterop (systemmediatransportcontrolsinterop.h), and the interface
# its GetForWindow is asked for, ISystemMediaTransportControls (windows.media.h)
INTEROP_IID = uuid.UUID("ddb0472d-c911-4a1f-86d9-dc3d71a95f5a")
CONTROLS_IID = uuid.UUID("99fa3ff4-1742-42a6-902e-087d41f965ec")
GET_FOR_WINDOW = 6  # its place in the interface's table, after IUnknown's 3 and IInspectable's 3
CAPSULE = b"winrt.interface"  # the name PyWinRT gives a capsule holding an interface


@dataclass(frozen=True)
class Names:
    """The WinRT types Smtc uses: winrt.windows.media's MediaPlaybackStatus, MediaPlaybackType and
    SystemMediaTransportControlsTimelineProperties, winrt.windows.foundation's Uri and
    winrt.windows.storage.streams' RandomAccessStreamReference."""

    status: Any
    kind: Any
    timeline: Any
    uri: Any
    stream: Any


class Smtc:
    """The System Media Transport Controls `controls` (a Backend, controls.py)."""

    def __init__(
        self,
        controls: Any,
        names: Names,
        send: Callable[[Command], None],
        position: Callable[[], float],
    ) -> None:
        self._controls, self._names, self._send, self._position = controls, names, send, position
        self._song: Song | None = None
        self._seekable = False
        controls.is_enabled = True
        for name in ("play", "pause", "stop", "next", "previous"):
            setattr(controls, f"is_{name}_enabled", False)
        self._tokens = [
            (controls.remove_button_pressed, controls.add_button_pressed(self._pressed)),
        ]
        # The position moved in the overlay is ISystemMediaTransportControls2's, which an older or
        # partial implementation (Wine's) lacks: the rest of the controls work without it, and the
        # timeline is never offered as seekable.
        self._can_seek = True
        try:
            self._tokens.append(
                (
                    controls.remove_playback_position_change_requested,
                    controls.add_playback_position_change_requested(self._position_asked),
                )
            )
        except (AttributeError, OSError) as error:
            self._can_seek = False
            log.warning("the system's media controls can't seek (%s); the rest of them work", error)

    def _pressed(self, sender: Any, args: Any) -> None:
        """A button pressed, on WinRT's thread."""
        name = BUTTONS.get(getattr(args.button, "name", ""))
        if name is not None:
            self._send(Command(name))

    def _position_asked(self, sender: Any, args: Any) -> None:
        """The position moved in the overlay, on WinRT's thread."""
        track = self._song.track if self._song is not None else ""
        self._send(Command(SET_POSITION, args.requested_playback_position.total_seconds(), track))

    def now_playing(self, song: Song | None) -> None:
        self._song = song
        updater = self._controls.display_updater
        if song is None:
            updater.clear_all()
            updater.update()
            return
        updater.type = self._names.kind.MUSIC
        music = updater.music_properties
        music.title, music.artist, music.album_title = song.title, song.artist, song.album
        if song.art:
            updater.thumbnail = self._names.stream.create_from_uri(self._names.uri(song.art))
        updater.update()
        self._timeline(self._position())

    def state(self, state: State, position: float) -> None:
        c = self._controls
        c.playback_status = getattr(self._names.status, STATUSES[state.status])
        c.is_play_enabled, c.is_pause_enabled = state.can_play, state.can_pause
        c.is_stop_enabled = state.status != STOPPED
        c.is_next_enabled, c.is_previous_enabled = state.can_go_next, state.can_go_previous
        self._seekable = state.can_seek and self._can_seek
        self._timeline(position)

    def seeked(self, position: float) -> None:
        self._timeline(position)

    def _timeline(self, position: float) -> None:
        """The song's length and the position, and where it can be sought to."""
        length = self._song.length if self._song is not None else 0.0
        timeline = self._names.timeline()
        timeline.start_time = timeline.min_seek_time = timedelta(0)
        timeline.end_time = timedelta(seconds=length)
        timeline.max_seek_time = timedelta(seconds=length if self._seekable else 0.0)
        timeline.position = timedelta(seconds=min(max(0.0, position), length))
        self._controls.update_timeline_properties(timeline)

    def close(self) -> None:
        for remove, token in self._tokens:
            remove(token)
        self._controls.display_updater.clear_all()
        self._controls.is_enabled = False


if sys.platform == "win32":  # pragma: no cover - Windows': measured in the Windows run
    import ctypes

    def _table(this: Any) -> Any:
        """An interface's table of functions."""
        return ctypes.cast(this, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

    def for_window(hwnd: int, controls_type: Any, interop: Any) -> Any:
        """The System Media Transport Controls of the window `hwnd`, by its interop interface's
        GetForWindow, which PyWinRT doesn't project: called through the interface's table with
        ctypes, its result handed to PyWinRT in a capsule as PyWinRT's own (`CAPSULE`), and the
        reference GetForWindow gave let go once PyWinRT holds its own. The capsule has no
        destructor: one called from Python (ctypes) brings the capsule back to life as it goes,
        and goes again, without end."""
        pointer_of = ctypes.PYFUNCTYPE(ctypes.c_void_p, ctypes.py_object, ctypes.c_char_p)(
            ("PyCapsule_GetPointer", ctypes.pythonapi)
        )
        this = pointer_of(interop.get_activation_factory(controls_type, INTEROP_IID), CAPSULE)
        get_for_window = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_void_p),
        )(_table(this)[GET_FOR_WINDOW])  # fmt: skip
        found = ctypes.c_void_p()
        get_for_window(this, hwnd, CONTROLS_IID.bytes_le, ctypes.byref(found))  # raises on failure
        capsule_new = ctypes.PYFUNCTYPE(
            ctypes.py_object, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p
        )(("PyCapsule_New", ctypes.pythonapi))
        release = ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(_table(found.value)[2])
        try:
            return interop.wrap_interface(capsule_new(found.value, CAPSULE, None), controls_type)
        finally:
            release(found.value)  # IUnknown::Release: PyWinRT's object holds its own

    def open_window(
        send: Callable[[Command], None], position: Callable[[], float], window: QWindow | None
    ) -> Smtc:
        """The window's System Media Transport Controls (controls.Opener)."""
        from winrt.runtime import interop
        from winrt.windows.foundation import Uri
        from winrt.windows.media import (
            MediaPlaybackStatus,
            MediaPlaybackType,
            SystemMediaTransportControls,
            SystemMediaTransportControlsTimelineProperties,
        )
        from winrt.windows.storage.streams import RandomAccessStreamReference

        if window is None:
            raise RuntimeError("there is no window for them")
        controls = for_window(int(window.winId()), SystemMediaTransportControls, interop)
        names = Names(
            MediaPlaybackStatus,
            MediaPlaybackType,
            SystemMediaTransportControlsTimelineProperties,
            Uri,
            RandomAccessStreamReference,
        )
        return Smtc(controls, names, send, position)
