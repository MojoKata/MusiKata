"""What MusiKata reads from a song's file: R4.1's fields under one name for every kind, and what
the audio is (A3.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tags:
    """R4.1's fields as read. A field the file doesn't hold is None (or empty, for genres)."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    albumartist: str | None = None
    track: int | None = None
    tracktotal: int | None = None
    disc: int | None = None
    disctotal: int | None = None
    year: int | None = None
    date: str | None = None  # the full date, when the file has more than a year ("2003-05-01")
    genres: tuple[str, ...] = ()
    composer: str | None = None
    comment: str | None = None
    compilation: bool = False
    rating: int | None = None  # 0 to 5 stars (R10); None: none in the file
    artistsort: str | None = None
    albumartistsort: str | None = None
    albumsort: str | None = None
    rg_track_gain: float | None = None  # ReplayGain, dB and peak (R7.5)
    rg_track_peak: float | None = None
    rg_album_gain: float | None = None
    rg_album_peak: float | None = None
    has_cover: bool = False


@dataclass(frozen=True)
class AudioInfo:
    """What the audio is: its kind (R2.2), length, bit rate, sample rate and channels."""

    kind: str
    length: float
    bitrate: int
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class Picture:
    """A picture embedded in a song (R5.1): its type as ID3 and FLAC number them (3 is the front
    cover; None when the format has no types, as MP4's covr), its MIME type as the file gives it
    (it may be wrong or empty), and its bytes."""

    type: int | None
    mime: str
    data: bytes
