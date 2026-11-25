"""Reading a song's file: Mutagen opens it, and parse.py makes R4.1's fields of what it found
(A3.1, A3.2). This is the edge: everything here hands plain strings and numbers on."""

from __future__ import annotations

import os
import struct
from collections import defaultdict

import mutagen
import mutagen.aiff
import mutagen.flac
import mutagen.id3
import mutagen.mp3
import mutagen.mp4
import mutagen.oggopus
import mutagen.oggvorbis
import mutagen.wave

from . import parse
from .fields import AudioInfo, Tags

# the file kinds of R2.2, by extension
EXTENSIONS = {
    ".mp3": "mp3", ".flac": "flac", ".m4a": "m4a", ".ogg": "vorbis", ".oga": "vorbis",
    ".opus": "opus", ".wav": "wav", ".aif": "aiff", ".aiff": "aiff",
}  # fmt: skip


class TagReadError(Exception):
    """A file MusiKata couldn't read: Needs attention lists it with this reason (R2.8)."""


def read(path: str) -> tuple[Tags, AudioInfo]:
    """A song's tags and what its audio is. Raises TagReadError for a file that isn't one of
    R2.2's kinds or can't be read, saying why."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXTENSIONS:
        raise TagReadError(f"not a kind MusiKata plays ({ext or 'no extension'})")
    opener = {
        "mp3": mutagen.mp3.MP3, "flac": mutagen.flac.FLAC, "m4a": mutagen.mp4.MP4,
        "vorbis": mutagen.oggvorbis.OggVorbis, "opus": mutagen.oggopus.OggOpus,
        "wav": mutagen.wave.WAVE, "aiff": mutagen.aiff.AIFF,
    }[EXTENSIONS[ext]]  # fmt: skip
    try:
        f = opener(path)
    except (mutagen.MutagenError, OSError, struct.error, ValueError, EOFError) as e:
        raise TagReadError(str(e) or type(e).__name__) from e
    kind = EXTENSIONS[ext]
    if kind == "m4a":
        codec = str(getattr(f.info, "codec", ""))
        kind = "alac" if codec.startswith("alac") else "aac"
    if kind in ("mp3", "wav", "aiff"):
        tags = _id3(f.tags)
        if kind == "wav":
            tags = parse.merge_info(tags, parse.riff_info(_riff_info_bytes(path)))
    elif kind == "aac" or kind == "alac":
        tags = _mp4(f.tags)
    else:
        tags = _vorbis(f)
    info = f.info
    return tags, AudioInfo(
        kind=kind,
        length=float(getattr(info, "length", 0.0) or 0.0),
        bitrate=int(getattr(info, "bitrate", 0) or 0),
        sample_rate=int(getattr(info, "sample_rate", 0) or 0),
        channels=int(getattr(info, "channels", 0) or 0),
    )


def _id3(tags: mutagen.id3.ID3 | None) -> Tags:
    if tags is None:
        return Tags()
    raw: dict[str, list[str]] = defaultdict(list)
    for frame in tags.values():
        fid = frame.FrameID
        if fid == "TCON":
            raw[fid] += [str(g) for g in frame.genres]
        elif fid == "TXXX":
            raw[f"TXXX:{frame.desc}"] += [str(t) for t in frame.text]
        elif fid.startswith("T") and hasattr(frame, "text"):
            raw[fid] += [str(t) for t in frame.text]
    popms = [(f.email, int(f.rating)) for f in tags.getall("POPM")]
    comments = [(f.desc, str(f.text[0]) if f.text else "") for f in tags.getall("COMM")]
    return parse.from_id3(raw, popms, comments, has_cover=bool(tags.getall("APIC")))


def _vorbis(f: mutagen.FileType) -> Tags:
    raw: dict[str, list[str]] = defaultdict(list)
    key: str
    value: str
    for key, value in f.tags or ():
        raw[key.upper()].append(value)
    pictures = getattr(f, "pictures", None)
    cover = bool(pictures) or bool(raw.get("METADATA_BLOCK_PICTURE")) or bool(raw.get("COVERART"))
    return parse.from_vorbis(raw, has_cover=cover)


def _mp4(tags: mutagen.mp4.MP4Tags | None) -> Tags:
    if tags is None:
        return Tags()
    raw: dict[str, list[str]] = {}
    for key, values in tags.items():
        if key.startswith("----:"):
            raw[key] = [bytes(v).decode("utf-8", "replace") for v in values]
        elif values and isinstance(values[0], str):
            raw[key] = list(values)
    trkn, disk = tags.get("trkn"), tags.get("disk")
    track = (int(trkn[0][0]), int(trkn[0][1])) if trkn else None
    disc = (int(disk[0][0]), int(disk[0][1])) if disk else None
    return parse.from_mp4(
        raw,
        track=track,
        disc=disc,
        compilation=bool(tags.get("cpil")),
        has_cover=bool(tags.get("covr")),
    )


def _riff_info_bytes(path: str) -> bytes:
    """A WAV file's RIFF header and its LIST chunks only, without reading the audio between."""
    out = bytearray()
    with open(path, "rb") as f:
        head = f.read(12)
        if len(head) < 12:
            return b""
        out += head
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            size = int.from_bytes(hdr[4:], "little")
            if hdr[:4] == b"LIST":
                out += hdr + f.read(size + (size & 1))
            else:
                f.seek(size + (size & 1), os.SEEK_CUR)
    return bytes(out)
