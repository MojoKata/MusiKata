"""The system's media controls (R7.8, A4.5), the part every platform shares, without Qt, a bus or a
platform's API: what the system is told of the song playing (`Song`, `State`), what each of its
commands does to the Player bridge (`actions`), MPRIS's property maps (`metadata`,
`player_properties`), positions in microseconds, the songs' track ids and seeks seen in the
positions the Player reports (`Watch`).

A backend (mpris.py, smtc.py, nowplaying_mac.py) is told `now_playing(song)`, `state(state,
position)` and `seeked(position)`, and sends the commands it hears as `Command`s; the package's
`MediaControls` (__init__.py) feeds it from the Player bridge and acts on what it sends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# MPRIS's statuses, which the other platforms' are mapped from
PLAYING, PAUSED, STOPPED = "Playing", "Paused", "Stopped"
NO_TRACK = "/org/mpris/MediaPlayer2/TrackList/NoTrack"  # MPRIS's track id when nothing is shown
TRACKS = "/org/musikata/MusiKata/track/"  # a song's track id: this and a number
JUMP = 1.0  # seconds the position may stray from where it should have got to before it is a seek

# the commands a system sends (Command.name)
PLAY, PAUSE, PLAY_PAUSE, STOP = "play", "pause", "play_pause", "stop"
NEXT, PREVIOUS = "next", "previous"
SEEK = "seek"  # by `value` seconds, either way
SET_POSITION = "set_position"  # to `value` seconds into the song `track`
VOLUME = "volume"  # to `value`, from 0 to 1
RAISE, QUIT = "raise", "quit"  # the window to the front; MusiKata to quit


@dataclass(frozen=True)
class Now:
    """What the Player bridge shows at a moment: the song's path under the root ("" for none), its
    words, its length in seconds (0 when unknown), its cover's address in QML (image://covers/…,
    "" for none); whether the engine has it (playing or paused), whether it plays; whether the
    queue has a current song (Next and Previous have somewhere to go); whether it can be sought;
    the position in seconds; the volume, from 0 to 1."""

    path: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    length: float = 0.0
    cover: str = ""
    on: bool = False
    playing: bool = False
    queued: bool = False
    seekable: bool = False
    position: float = 0.0
    volume: float = 1.0


@dataclass(frozen=True)
class Song:
    """What the system shows of the song: its track id, title, artist and album ("" when
    unknown), length in seconds (0 when unknown) and cover as a file URL ("" for none)."""

    track: str
    title: str
    artist: str = ""
    album: str = ""
    length: float = 0.0
    art: str = ""


@dataclass(frozen=True)
class State:
    """Whether a song plays (PLAYING, PAUSED or STOPPED), which of the system's buttons do
    something now, and the volume."""

    status: str = STOPPED
    can_play: bool = False
    can_pause: bool = False
    can_go_next: bool = False
    can_go_previous: bool = False
    can_seek: bool = False
    volume: float = 1.0


@dataclass(frozen=True)
class Command:
    """A command from the system: its name (PLAY, SEEK, …), the seconds or volume it carries, and
    for SET_POSITION the track id it was meant for."""

    name: str
    value: float = 0.0
    track: str = ""


class Backend(Protocol):
    """A platform's media controls (A4.5): told what plays, it sends what the system asks."""

    def now_playing(self, song: Song | None) -> None:
        """The song shown now, or None when nothing is."""
        ...

    def state(self, state: State, position: float) -> None:
        """Whether it plays, the buttons that do something, at `position` seconds."""
        ...

    def seeked(self, position: float) -> None:
        """The song moved to `position` seconds other than by playing on."""
        ...

    def close(self) -> None: ...


def backend_for(platform: str) -> str | None:
    """The backend's module for a platform (sys.platform): mpris on Linux, smtc on Windows,
    nowplaying_mac on macOS; None elsewhere, where MusiKata plays without one."""
    if platform.startswith("linux"):
        return "mpris"
    return {"win32": "smtc", "darwin": "nowplaying_mac"}.get(platform)


def status_of(now: Now) -> str:
    """PLAYING when a song plays; PAUSED when one is paused, or cued and waiting for play (the
    bar shows it, and play starts it); STOPPED when none is shown."""
    if now.on and now.playing:
        return PLAYING
    return PAUSED if now.path else STOPPED


def state_of(now: Now) -> State:
    """The State the system is told: play and pause with a song shown, next and previous with a
    queue, seeking where the bar seeks."""
    shown = bool(now.path)
    return State(
        status_of(now), shown, shown, now.queued, now.queued, now.seekable, now.volume
    )  # fmt: skip


def thumb_of(cover: str) -> str:
    """A cover's thumbnail name from its address in QML (image://covers/<name>); "" for none, or
    for a mosaic, which no song has."""
    _, _, name = cover.partition("://covers/")
    return "" if "/" in name else name


def song_of(now: Now, track: str, art: str = "") -> Song | None:
    """The Song shown for `now` under `track`, with its cover at the file URL `art`; None when no
    song is shown."""
    if not now.path:
        return None
    return Song(track, now.title, now.artist, now.album, max(0.0, now.length), art)


def microseconds(seconds: float) -> int:
    """Seconds as MPRIS's whole microseconds."""
    return round(seconds * 1_000_000)


def metadata(song: Song | None) -> dict[str, object]:
    """MPRIS's Metadata for the song: its track id, and each of mpris:length (microseconds),
    mpris:artUrl, xesam:title, xesam:artist (a list) and xesam:album that it has; only the track id
    NoTrack when there is none."""
    if song is None:
        return {"mpris:trackid": NO_TRACK}
    out: dict[str, object] = {"mpris:trackid": song.track, "xesam:title": song.title}
    if song.length > 0:
        out["mpris:length"] = microseconds(song.length)
    if song.art:
        out["mpris:artUrl"] = song.art
    if song.artist:
        out["xesam:artist"] = [song.artist]
    if song.album:
        out["xesam:album"] = song.album
    return out


def player_properties(state: State) -> dict[str, object]:
    """The properties of MPRIS's Player interface that follow the State."""
    return {
        "PlaybackStatus": state.status,
        "CanPlay": state.can_play,
        "CanPause": state.can_pause,
        "CanGoNext": state.can_go_next,
        "CanGoPrevious": state.can_go_previous,
        "CanSeek": state.can_seek,
        "Volume": state.volume,
    }


def changed(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    """The entries of `after` that `before` lacks or holds otherwise."""
    return {k: v for k, v in after.items() if k not in before or before[k] != v}


def actions(command: Command, now: Now, track: str) -> list[tuple[str, float | None]]:
    """What a command does, as the Player bridge's methods to call, each with its argument or
    None: play starts or resumes a song shown and not playing, pause pauses one playing, stop
    stops one the engine has; a seek past the song's end goes to the next (MPRIS's Seek), one
    before its start to its start; a position is set only in the song `track` it was meant for
    and inside its length. RAISE and QUIT are the window's and the app's ("raise", "quit")."""
    shown, playing = bool(now.path), now.on and now.playing
    match command.name:
        case "play" if shown and not playing:
            return [("toggle", None)]
        case "pause" if playing:
            return [("toggle", None)]
        case "play_pause" if shown:
            return [("toggle", None)]
        case "stop" if now.on:
            return [("stop", None)]
        case "next" if now.queued:
            return [("next", None)]
        case "previous" if now.queued:
            return [("previous", None)]
        case "seek" if now.seekable:
            to = now.position + command.value
            if now.length and to > now.length:
                return [("next", None)] if now.queued else []
            return [("seek", max(0.0, to))]
        case "set_position" if now.seekable and command.track == track:
            inside = 0.0 <= command.value <= (now.length or command.value)
            return [("seek", command.value)] if inside else []
        case "volume":
            return [("setVolume", min(1.0, max(0.0, command.value)))]
        case "raise" | "quit":
            return [(command.name, None)]
    return []


@dataclass(frozen=True)
class Seen:
    """What changed as the Player moved on: the song's track id (a new one when the song shown
    changed), whether it changed, and the position it was sought to, else None."""

    track: str
    new: bool = False
    seeked: float | None = None


class Watch:
    """Follows the Player bridge for the system: a new track id each time another song is shown
    (a number that counts up, so the same song played again is a new track), and a seek wherever
    the position isn't where playing on from the last one would have got it, by more than JUMP
    seconds, by the clock's monotonic seconds given with each look: a seek asked for in the bar, by
    the keys or the system, and Previous starting the song again, alike."""

    def __init__(self) -> None:
        self._count = 0
        self._path = ""
        self.track = NO_TRACK
        self._last: tuple[float, float, bool] | None = None  # position, when, playing

    def look(self, now: Now, at: float) -> Seen:
        """What changed since the last look, `now` being the Player at `at` seconds."""
        if now.path != self._path:
            self._path = now.path
            if now.path:
                self._count += 1
                self.track = f"{TRACKS}{self._count}"
            else:
                self.track = NO_TRACK
            self._last = (now.position, at, now.on and now.playing)
            return Seen(self.track, True)
        last, self._last = self._last, (now.position, at, now.on and now.playing)
        if last is None or not now.path:
            return Seen(self.track)
        position, when, playing = last
        expected = position + (at - when if playing else 0.0)
        if abs(now.position - expected) > JUMP:
            return Seen(self.track, seeked=now.position)
        return Seen(self.track)
