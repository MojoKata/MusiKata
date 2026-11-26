"""Reading a song's file: Mutagen opens it, and parse.py makes R4.1's fields of what it found
(A3.1, A3.2). This is the edge: everything here hands plain strings and numbers on."""

from __future__ import annotations

import base64
import binascii
import logging
import os
import struct
from collections import defaultdict
from typing import Any

import mutagen
import mutagen.aiff
import mutagen.apev2
import mutagen.flac
import mutagen.id3
import mutagen.mp3
import mutagen.mp4
import mutagen.oggopus
import mutagen.oggvorbis
import mutagen.wave

from . import parse
from .fields import AudioInfo, Picture, Tags

log = logging.getLogger(__name__)

# the file kinds of R2.2, by extension
EXTENSIONS = {
    ".mp3": "mp3", ".flac": "flac", ".m4a": "m4a", ".ogg": "vorbis", ".oga": "vorbis",
    ".opus": "opus", ".wav": "wav", ".aif": "aiff", ".aiff": "aiff",
}  # fmt: skip


class TagReadError(Exception):
    """A file MusiKata couldn't read: Needs attention lists it with this reason (R2.8)."""


def open_song(path: str, name: str | None = None) -> tuple[str, mutagen.FileType]:
    """The file's kind (R2.2) and Mutagen's view of it; TagReadError when it can't be opened.
    `name`, when given, is the name whose extension says the kind: a song's, for the copy a safe
    write makes of it (A3.4)."""
    ext = os.path.splitext(name or path)[1].lower()
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
    return kind, f


def read(path: str, name: str | None = None) -> tuple[Tags, AudioInfo]:
    """A song's tags and what its audio is (`name`: as for `open_song`). Raises TagReadError for
    a file that isn't one of R2.2's kinds or can't be read, saying why."""
    kind, f = open_song(path, name)
    if kind in ("mp3", "wav", "aiff"):
        tags = _id3(f.tags)
        if kind == "mp3" and (tags.rg_track_gain is None or tags.rg_album_gain is None):
            tags = parse.with_replaygain(tags, _ape_replaygain(path))
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


def pictures(path: str, name: str | None = None) -> list[Picture]:
    """The pictures embedded in a song, in the order its file holds them (R5.1): ID3's APIC, FLAC's
    picture blocks, Vorbis comments' METADATA_BLOCK_PICTURE and the older COVERART, MP4's covr.
    A picture that can't be decoded is skipped and logged. Raises TagReadError for a file it
    can't open. `name`: as for `open_song`."""
    kind, f = open_song(path, name)
    tags = f.tags
    if kind in ("mp3", "wav", "aiff"):
        apic: list[Any] = tags.getall("APIC") if tags is not None else []
        return [Picture(int(p.type), str(p.mime), bytes(p.data)) for p in apic]
    if kind in ("aac", "alac"):
        formats: dict[object, str] = {
            mutagen.mp4.MP4Cover.FORMAT_JPEG: "image/jpeg",
            mutagen.mp4.MP4Cover.FORMAT_PNG: "image/png",
        }
        covr: list[Any] = (tags.get("covr") if tags is not None else None) or []
        return [
            Picture(None, formats.get(getattr(c, "imageformat", None), ""), bytes(c)) for c in covr
        ]
    out = [Picture(int(p.type), str(p.mime), bytes(p.data)) for p in getattr(f, "pictures", [])]
    key: str
    value: str
    for key, value in tags or ():
        upper: str = key.upper()
        if upper not in ("METADATA_BLOCK_PICTURE", "COVERART"):
            continue
        try:
            data = base64.b64decode(value, validate=False)
            if upper == "COVERART":
                out.append(Picture(None, "", data))
            else:
                p = mutagen.flac.Picture(data)
                out.append(Picture(int(p.type), str(p.mime), bytes(p.data)))
        except (binascii.Error, ValueError, struct.error, mutagen.MutagenError) as e:
            log.warning("skipped a picture in %s that couldn't be read: %s", path, e)
    return out


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
    rva2 = [
        (str(f.desc), float(f.gain), float(f.peak))
        for f in tags.getall("RVA2")
        if f.channel == 1  # the master volume: the only one ReplayGain writes
    ]
    return parse.from_id3(raw, popms, comments, has_cover=bool(tags.getall("APIC")), rva2=rva2)


def _ape_replaygain(path: str) -> dict[str, float | None]:
    """ReplayGain from an MP3's APEv2 tag, where mp3gain and foobar2000 write it; nothing when it
    has none, or it can't be read (logged)."""
    try:
        ape = mutagen.apev2.APEv2(path)
    except mutagen.apev2.APENoHeaderError:
        return {}
    except (mutagen.MutagenError, OSError, struct.error, ValueError) as e:
        log.warning("couldn't read the APEv2 tag of %s: %s", path, e)
        return {}
    return parse.replaygain_of({k: [str(v)] for k, v in ape.items()})


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
        elif isinstance(values, list) and values and isinstance(values[0], str):
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
