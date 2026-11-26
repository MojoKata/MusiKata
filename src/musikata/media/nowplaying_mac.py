"""The system's media controls on macOS (R7.8, A4.5): Now Playing in Control Centre and the media
keys, through PyObjC's MediaPlayer (`pyobjc-framework-MediaPlayer`): `MPNowPlayingInfoCenter`
shows the song, its cover and where it is, and `MPRemoteCommandCenter`'s commands work it.

`NowPlayingMac` maps what controls.py says onto the two and their commands onto Commands; it is
given the centres and the framework's names it uses (`Names`), so a test hands it fakes on any
platform. macOS moves the time shown on by itself from the elapsed time and the rate given, so the
position is given when the state changes or the song is sought. What only a Mac can show, Control
Centre itself, is tier 3's."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from PySide6.QtGui import QWindow

from .controls import (
    NEXT,
    PAUSE,
    PAUSED,
    PLAY,
    PLAY_PAUSE,
    PLAYING,
    PREVIOUS,
    SET_POSITION,
    STOP,
    STOPPED,
    Command,
    Song,
    State,
)

# MPRemoteCommandCenter's commands, by the Command each sends
COMMANDS = {
    PLAY: "playCommand",
    PAUSE: "pauseCommand",
    PLAY_PAUSE: "togglePlayPauseCommand",
    STOP: "stopCommand",
    NEXT: "nextTrackCommand",
    PREVIOUS: "previousTrackCommand",
    SET_POSITION: "changePlaybackPositionCommand",
}


@dataclass(frozen=True)
class Names:
    """MediaPlayer's names: the now-playing info's keys (title, artist, album, duration, elapsed,
    rate, artwork), the playback state for each status, a handler's success, and `artwork`, which
    makes an MPMediaItemArtwork of an image file, or None when it can't be read."""

    title: str
    artist: str
    album: str
    duration: str
    elapsed: str
    rate: str
    artwork_key: str
    states: dict[str, int]
    success: int
    artwork: Callable[[str], Any]


def path_of(url: str) -> str:
    """The file a file URL names."""
    return url2pathname(urlparse(url).path)


class NowPlayingMac:
    """Now Playing through `center` (MPNowPlayingInfoCenter) and `commands`
    (MPRemoteCommandCenter): a Backend (controls.py)."""

    def __init__(
        self,
        center: Any,
        commands: Any,
        names: Names,
        send: Callable[[Command], None],
        position: Callable[[], float],
    ) -> None:
        self._center, self._commands, self._names = center, commands, names
        self._send, self._position = send, position
        self._song: Song | None = None
        self._playing = False
        self._art: tuple[str, Any] = ("", None)  # the artwork made last, and its URL
        self._targets: list[tuple[Any, Any]] = []
        for name, command in COMMANDS.items():
            handler = self._moved if name == SET_POSITION else self._handler(name)
            target = getattr(commands, command)()
            self._targets.append((target, target.addTargetWithHandler_(handler)))

    def _handler(self, name: str) -> Callable[[Any], int]:
        def handle(event: Any) -> int:
            self._send(Command(name))
            return self._names.success

        return handle

    def _moved(self, event: Any) -> int:
        """The position moved in Control Centre (MPChangePlaybackPositionCommandEvent)."""
        track = self._song.track if self._song is not None else ""
        self._send(Command(SET_POSITION, float(event.positionTime()), track))
        return self._names.success

    def _enable(self, name: str, on: bool) -> None:
        getattr(self._commands, COMMANDS[name])().setEnabled_(on)

    def now_playing(self, song: Song | None) -> None:
        self._song = song
        self._publish(self._position())

    def state(self, state: State, position: float) -> None:
        self._center.setPlaybackState_(self._names.states[state.status])
        self._playing = state.status == PLAYING
        for name, on in (
            (PLAY, state.can_play), (PAUSE, state.can_pause), (PLAY_PAUSE, state.can_play),
            (STOP, state.status != STOPPED), (NEXT, state.can_go_next),
            (PREVIOUS, state.can_go_previous), (SET_POSITION, state.can_seek),
        ):  # fmt: skip
            self._enable(name, on)
        self._publish(position)

    def seeked(self, position: float) -> None:
        self._publish(position)

    def _artwork(self, url: str) -> Any:
        if url != self._art[0]:
            self._art = (url, self._names.artwork(path_of(url)) if url else None)
        return self._art[1]

    def _publish(self, position: float) -> None:
        """The now-playing info: the song's words, length, cover and the position, moving on at
        the rate it plays."""
        song, n = self._song, self._names
        if song is None:
            self._center.setNowPlayingInfo_(None)
            return
        info: dict[str, Any] = {
            n.title: song.title, n.artist: song.artist, n.album: song.album,
            n.duration: song.length, n.elapsed: max(0.0, position),
            n.rate: 1.0 if self._playing else 0.0,
        }  # fmt: skip
        artwork = self._artwork(song.art)
        if artwork is not None:
            info[n.artwork_key] = artwork
        self._center.setNowPlayingInfo_(info)

    def close(self) -> None:
        for target, token in self._targets:
            target.removeTarget_(token)
        self._center.setNowPlayingInfo_(None)
        self._center.setPlaybackState_(self._names.states[STOPPED])


if sys.platform == "darwin":  # pragma: no cover - macOS's: measured in the macOS run

    def open_center(
        send: Callable[[Command], None], position: Callable[[], float], window: QWindow | None
    ) -> NowPlayingMac:
        """Now Playing for this app (controls.Opener)."""
        import AppKit
        import MediaPlayer as mp

        def artwork(path: str) -> Any:
            image = AppKit.NSImage.alloc().initWithContentsOfFile_(path)
            if image is None:
                return None
            return mp.MPMediaItemArtwork.alloc().initWithBoundsSize_requestHandler_(
                image.size(), lambda size: image
            )

        names = Names(
            mp.MPMediaItemPropertyTitle,
            mp.MPMediaItemPropertyArtist,
            mp.MPMediaItemPropertyAlbumTitle,
            mp.MPMediaItemPropertyPlaybackDuration,
            mp.MPNowPlayingInfoPropertyElapsedPlaybackTime,
            mp.MPNowPlayingInfoPropertyPlaybackRate,
            mp.MPMediaItemPropertyArtwork,
            {
                PLAYING: mp.MPNowPlayingPlaybackStatePlaying,
                PAUSED: mp.MPNowPlayingPlaybackStatePaused,
                STOPPED: mp.MPNowPlayingPlaybackStateStopped,
            },
            mp.MPRemoteCommandHandlerStatusSuccess,
            artwork,
        )
        center = mp.MPNowPlayingInfoCenter.defaultCenter()
        commands = mp.MPRemoteCommandCenter.sharedCommandCenter()
        return NowPlayingMac(center, commands, names, send, position)
