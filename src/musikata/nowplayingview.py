"""Now Playing (R11.4), as QML sees it: whether it is open (`open`, `close`, `toggle`: the bar's
Now Playing button, its cover, ‹ Library and Esc, R11.4.4), the visualization chosen in its picker
and kept (R11.4.5), and what it says of the song playing: "Now playing · Track 4 of 10", the album
line, the chips of its format, bit depth and sample rate, bit rate and ReplayGain (R11.4.1), the
format N03 shows under its cover (R11.4.3), Up next's first songs (R11.4.1), and the waveform's
minute marks.

Now Playing is drawn over everything above the now-playing bar, the sidebar and the header
included; the view it was opened from stays as it was underneath, so closing it goes back there.
The song's words are read from the index by its id when the song shown changes, a row and its
genres; the queue is the Player bridge's (bridges.py). What every text says is decided here
(docs/process/coding.md: QML only lays out and binds).

The choice of visualization is kept in the shared settings' `appearance` (A2.10): it belongs to
this computer and this person, as Appearance does (R13.9), not to the root; so are the 3D
analyzer's bands and speed, set from its gear (R11.3.1), and what its gear and its labels say is
decided here too. The Lyrics switch (R17.3) is lyrics.py's; the Equalizer button (R19.2) is
there, faded, saying it comes later."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core.analysis.landscape import SECONDS
from musikata_core.settings import ANALYZER_BANDS, ANALYZER_SPEEDS, VISUALIZATIONS

from .models import KINDS, LOSSLESS, artist_text, cover_url, time_text
from .nowplaying import read_songs

# each choice of the picker (R11.4.5): its setting, its name and its icon (Icons.js)
MODES = {"waveform": ("Waveform", "wave"), "analyzer": ("3D analyzer", "cube"),
         "none": ("No visualization", "nowave")}  # fmt: skip
EQUALIZER_LATER = "The equalizer comes in a later version"  # R19.2: slice 9 (#26)
UP_NEXT_SHOWN = 5  # Up next's songs beside the cover with Waveform (N01)
MARKS_AT_MOST = 12  # the waveform's minute marks, at most: longer songs mark every few minutes
NOTHING = "Nothing is playing. Play a song, or press play on what's queued."
MINUS = "−"  # the minus the mockups set before a negative gain


def kicker_text(track: int | None, total: int | None) -> str:
    """The line over the title (N01): Now playing · Track 4 of 10; the track alone without its
    total; Now playing without either."""
    if not track:
        return "Now playing"
    return f"Now playing · Track {track} of {total}" if total else f"Now playing · Track {track}"


def album_line(album: str, year: int | None, genres: list[str]) -> str:
    """The line under the artist: Glass Harbor · 2019 · Electronic, each part when known."""
    return " · ".join(p for p in (album, str(year) if year else "", ", ".join(genres)) if p)


def rate_text(bits: int | None, rate: int | None) -> str:
    """The bit depth and sample rate: 16-bit / 44.1 kHz; the rate alone for a lossy song."""
    hz = f"{rate / 1000:g} kHz" if rate else ""
    if bits and hz:
        return f"{bits}-bit / {hz}"
    return f"{bits}-bit" if bits else hz


def bitrate_text(bitrate: int | None) -> str:
    """The bit rate: 912 kbps; "" when unknown."""
    kbps = round((bitrate or 0) / 1000)
    return f"{kbps} kbps" if kbps else ""


def gain_shown(mode: str, track_gain: float | None, album_gain: float | None) -> float | None:
    """The ReplayGain the song's chip shows (R7.5's mode): the album's with Album (the track's
    when it has none), the track's with Track, none when Off or untagged."""
    if mode == "album":
        return album_gain if album_gain is not None else track_gain
    return track_gain if mode == "track" else None


def gain_text(gain: float | None) -> str:
    """The ReplayGain chip: ReplayGain −6.2 dB; "" for none."""
    if gain is None:
        return ""
    sign = MINUS if gain < 0 else "+" if gain > 0 else ""
    return f"ReplayGain {sign}{abs(gain):.1f} dB"


def chips_of(
    kind: str | None, bits: int | None, rate: int | None, bitrate: int | None, gain: float | None
) -> list[str]:
    """The chips under the rating (N01): the format, bit depth and sample rate, bit rate and
    ReplayGain, each when known."""
    lossless = kind in LOSSLESS
    parts = [
        KINDS.get(kind or "", kind or ""),
        rate_text(bits if lossless else None, rate),
        bitrate_text(bitrate),
        gain_text(gain),
    ]
    return [p for p in parts if p]


def format_line(kind: str | None, bits: int | None, rate: int | None, bitrate: int | None) -> str:
    """The format N03 shows under its cover: FLAC 16-bit / 44.1 kHz; MP3 320 kbps."""
    name = KINDS.get(kind or "", kind or "")
    detail = rate_text(bits, rate) if kind in LOSSLESS else bitrate_text(bitrate)
    return " ".join(p for p in (name, detail) if p)


def speed_text(seconds: float) -> str:
    """The analyzer's speed (R11.3.1) as its gear says it: 1× for the SECONDS N02 holds, 2× for
    half of them, 0.5× for twice as many."""
    return f"{round(SECONDS / seconds, 2):g}×"


def analyzer_text(bands: int, seconds: float) -> str:
    """What the analyzer's gear says (N02): Bands: 96 · Speed: 1×."""
    return f"Bands: {bands} · Speed: {speed_text(seconds)}"


def ago_text(seconds: float) -> str:
    """What the back of the landscape is labelled (N02): ← 3 seconds ago."""
    unit = "second" if seconds == 1 else "seconds"
    return f"← {seconds:g} {unit} ago"


def minute_marks(length: float) -> list[dict[str, Any]]:
    """The waveform's marks (N01): one a minute from the start, each its place (0 to 1) and its
    time; every few minutes when a minute each would be more than MARKS_AT_MOST."""
    if length <= 0:
        return []
    step = 60
    while length / step >= MARKS_AT_MOST:
        step *= 5 if step == 60 else 2
    count = int(length // step) + 1
    return [{"at": i * step / length, "text": time_text(i * step)} for i in range(count)]


def details_of(c: sqlite3.Connection, song: int, mode: str) -> dict[str, Any]:
    """What Now Playing says of the song with id `song` (R11.4.1, R11.4.3), under ReplayGain's
    `mode` (R7.5); {} when the index no longer has it."""
    row = c.execute(
        "SELECT song.title, song.artist, song.album, song.year, song.track, song.tracktotal,"
        " song.kind, song.bits, song.sample_rate, song.bitrate, song.rg_track_gain,"
        " song.rg_album_gain, album.thumb, song.path"
        " FROM song LEFT JOIN album ON album.id = song.album_id WHERE song.id = ?",
        (song,),
    ).fetchone()
    if row is None:
        return {}
    title, artist, album, year, track, total, kind, bits, rate, bitrate, tg, ag, thumb, path = row
    genres = [g for (g,) in c.execute(
        "SELECT genre FROM song_genre WHERE song_id = ? ORDER BY position", (song,)
    )]  # fmt: skip
    gain = gain_shown(mode, tg, ag)
    return {
        "kicker": kicker_text(track, total),
        "title": title or path.rpartition("/")[2],
        "artist": artist_text(artist),
        "line": album_line(album or "", year, genres),
        "chips": chips_of(kind, bits, rate, bitrate, gain),
        "format": format_line(kind, bits, rate, bitrate),
        "cover": cover_url(thumb),
    }


def up_next_rows(c: sqlite3.Connection, songs: list[int]) -> list[dict[str, str]]:
    """Up next beside the cover (N01): each song's title, its artist and length, and its cover;
    one gone from the index is left out."""
    found = read_songs(c, songs)
    rows = []
    for song in songs:
        info = found.get(song)
        if info is not None:
            line = " · ".join(p for p in (artist_text(info.artist), time_text(info.length)) if p)
            rows.append({"title": info.title, "line": line, "cover": info.cover})
    return rows


class NowPlayingView(QObject):
    """Now Playing over the window (R11.4): open or not, its visualization, and the words of the
    song `player` (the Player bridge) shows, read through `read` with ReplayGain's `replaygain`
    mode (R7.5). `visualization` is the one kept (settings.Appearance), with the analyzer's `bands`
    and `seconds` (R11.3.1); `keep` keeps a new one, given as the appearance group's fields
    (Player.remember_appearance: on its thread)."""

    changed = Signal()  # open, the visualization
    songChanged = Signal()  # the song's words, its chips, Up next, the minute marks
    analyzerChanged = Signal()  # the analyzer's bands or speed

    def __init__(
        self,
        player: QObject,
        read: Callable[[], sqlite3.Connection] | None,
        replaygain: str = "album",
        visualization: str = "waveform",
        keep: Callable[..., object] | None = None,
        bands: int = 96,
        seconds: float = SECONDS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._player, self._read, self._replaygain, self._keep = player, read, replaygain, keep
        self._mode = visualization if visualization in VISUALIZATIONS else VISUALIZATIONS[0]
        self._bands = bands if bands in ANALYZER_BANDS else 96
        self._seconds = seconds if seconds > 0 else SECONDS
        self._opened = False
        self._song: int | None = None
        self._details: dict[str, Any] = {}
        self._up_next: list[dict[str, str]] = []
        self._marks: list[dict[str, Any]] = []
        self._length = 0.0
        player.changed.connect(self._song_changed)  # type: ignore[attr-defined]
        player.queueChanged.connect(self._queue_changed)  # type: ignore[attr-defined]

    # ---------- open and closed (R11.4, R11.4.4) ----------

    @Slot()
    def open(self) -> None:
        if not self._opened:
            self._opened = True
            self._song_changed()
            self._queue_changed()
            self.changed.emit()

    @Slot()
    def close(self) -> None:
        """‹ Library, Esc or the button again: back to the view it was opened from, which stayed
        as it was underneath."""
        if self._opened:
            self._opened = False
            self.changed.emit()

    @Slot()
    def toggle(self) -> None:
        """The bar's Now Playing button: opens it, or closes it again."""
        if self._opened:
            self.close()
        else:
            self.open()

    # ---------- the picker (R11.4.5) ----------

    @Slot(str)
    def setMode(self, mode: str) -> None:  # noqa: N802
        """A choice of the picker: shown, and kept (R11.4.5)."""
        if mode in VISUALIZATIONS and mode != self._mode:
            self._mode = mode
            self.changed.emit()
            if self._keep is not None:
                self._keep(visualization=mode)

    # ---------- the analyzer's gear (R11.3.1) ----------

    @Slot(int)
    def setBands(self, bands: int) -> None:  # noqa: N802
        """A band count chosen from the gear: shown, and kept."""
        if bands in ANALYZER_BANDS and bands != self._bands:
            self._bands = bands
            self.analyzerChanged.emit()
            if self._keep is not None:
                self._keep(analyzer_bands=bands)

    @Slot(float)
    def setSeconds(self, seconds: float) -> None:  # noqa: N802
        """A speed chosen from the gear, as the seconds it holds: shown, and kept."""
        if seconds in ANALYZER_SPEEDS and seconds != self._seconds:
            self._seconds = seconds
            self.analyzerChanged.emit()
            if self._keep is not None:
                self._keep(analyzer_seconds=seconds)

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"nowPlaying": "none"} opens Now Playing with that visualization
        (not kept: the tour keeps nothing); closed otherwise."""
        mode = step.get("nowPlaying")
        if mode in VISUALIZATIONS:
            keep, self._keep = self._keep, None
            self.setMode(mode)
            self._keep = keep
            self.open()
        else:
            self.close()

    # ---------- the song ----------

    def _song_changed(self) -> None:
        """The song shown, or its words, changed: read again while open (closed, when opened)."""
        if not self._opened:
            return
        song = getattr(self._player, "song_id", lambda: None)()
        length = float(self._player.property("length") or 0.0)
        details: dict[str, Any] = {}
        if song is not None and self._read is not None:
            details = details_of(self._read(), song, self._replaygain)
        if length != self._length:
            self._marks = minute_marks(length)
        self._song, self._details, self._length = song, details, length
        self.songChanged.emit()

    def _queue_changed(self) -> None:
        if not self._opened:
            return
        queue = getattr(self._player, "queue", None)
        songs = [e.song for e in queue.upcoming[:UP_NEXT_SHOWN]] if queue is not None else []
        rows = up_next_rows(self._read(), songs) if songs and self._read is not None else []
        if rows != self._up_next:
            self._up_next = rows
            self.songChanged.emit()

    # ---------- what QML reads ----------

    def _get_opened(self) -> bool:
        return self._opened

    def _get_mode(self) -> str:
        return self._mode

    def _get_modes(self) -> list[dict[str, Any]]:
        return [
            {"mode": m, "name": name, "icon": icon, "checked": m == self._mode}
            for m, (name, icon) in MODES.items()
        ]

    def _get_mode_name(self) -> str:
        return MODES[self._mode][0]

    def _get_mode_icon(self) -> str:
        return MODES[self._mode][1]

    def _get_band_choices(self) -> list[dict[str, Any]]:
        return [
            {"value": n, "text": f"{n} bands", "checked": n == self._bands} for n in ANALYZER_BANDS
        ]

    def _get_speed_choices(self) -> list[dict[str, Any]]:
        return [
            {"value": s, "text": f"{speed_text(s)} · {s:g} s", "checked": s == self._seconds}
            for s in ANALYZER_SPEEDS
        ]

    def _get_details(self) -> dict[str, Any]:
        return self._details

    def _get_up_next(self) -> list[dict[str, str]]:
        return self._up_next

    def _get_marks(self) -> list[dict[str, Any]]:
        return self._marks

    def _get_empty_text(self) -> str:
        return "" if self._details or self._player.property("path") else NOTHING

    opened = QtProperty(bool, _get_opened, notify=changed)
    mode = QtProperty(str, _get_mode, notify=changed)  # waveform, analyzer, none
    modes = QtProperty(list, _get_modes, notify=changed)  # the picker's menu
    modeName = QtProperty(str, _get_mode_name, notify=changed)  # Waveform
    modeIcon = QtProperty(str, _get_mode_icon, notify=changed)  # wave
    details = QtProperty(dict, _get_details, notify=songChanged)
    upNext = QtProperty(list, _get_up_next, notify=songChanged)
    marks = QtProperty(list, _get_marks, notify=songChanged)  # [{at: 0.23, text: "1:00"}]
    emptyText = QtProperty(str, _get_empty_text, notify=songChanged)
    analyzerBands = QtProperty(int, lambda self: self._bands, notify=analyzerChanged)
    analyzerSeconds = QtProperty(float, lambda self: self._seconds, notify=analyzerChanged)
    analyzerText = QtProperty(
        str, lambda self: analyzer_text(self._bands, self._seconds), notify=analyzerChanged
    )  # Bands: 96 · Speed: 1×
    analyzerAgo = QtProperty(str, lambda self: ago_text(self._seconds), notify=analyzerChanged)
    bandChoices = QtProperty(list, _get_band_choices, notify=analyzerChanged)  # the gear's menu
    speedChoices = QtProperty(list, _get_speed_choices, notify=analyzerChanged)
    equalizerLater = QtProperty(str, lambda self: EQUALIZER_LATER, constant=True)
