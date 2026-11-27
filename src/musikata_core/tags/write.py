"""Writing a song's tags with Mutagen (A3.1, A3.2): compose.py says what changes, as plain data, and
this applies it to the file as Mutagen holds it, touching nothing else (R4.1.1). It writes in
place, so safe.py hands it the copy beside the original (A3.4), never the song itself.

MP3s are written as ID3v2.4, or ID3v2.3 (R4.7.2); an ID3v1 tag already there is updated to match,
none added. What Mutagen would drop going from one version to the other is kept: the frames it
doesn't know, made the other version's (compose.id3_frame_to), and in ID3v2.3 the ID3v2.4 frames
other programs write there too (TSOP, TSOA, RVA2: iTunes, Picard). A WAV's RIFF INFO chunk, which
Mutagen doesn't write, is kept in step as the copy is made (`copy`)."""

from __future__ import annotations

import base64
import binascii
import logging
import os
import shutil
import struct
from typing import Any, BinaryIO, cast

import mutagen
import mutagen.flac
import mutagen.id3
import mutagen.mp4

from . import compose, parse
from .fields import Picture, Tags
from .read import open_song

log = logging.getLogger(__name__)

ID3_VERSIONS = {"2.4": 4, "2.3": 3}  # R4.7.2, R13.3's setting
V23_SEP = None  # several values of a frame NUL-separated in ID3v2.3 too, so none is lost; TCON's
# genres are joined with "; " instead (R9.2, compose.id3v23_genres)
CHUNK = 1 << 20  # bytes copied at a time


def apply(
    path: str,
    change: compose.Change,
    before: Tags,
    id3_version: str = "2.4",
    name: str = "",
    rating_scale: str = "windows-media",
) -> None:
    """Writes `change` (compose.effective's) into the file at `path`, in place, whose tags read
    as `before`: MP3s in `id3_version` ("2.4" or "2.3"), their rating's POPM in `rating_scale`
    (R10.4's "windows-media", or "musikata", R10.4.1). `name` is the song's own, whose extension
    says its kind, for its copy (read.open_song). Raises Mutagen's and the system's errors as
    they come: safe.py says what they mean."""
    kind, f = open_song(path, name or None)
    tags = _tags(f)
    if kind in ("mp3", "wav", "aiff"):
        version = ID3_VERSIONS[id3_version]
        _id3(tags, change, before, version, rating_scale)
        if kind == "mp3":
            f.save(v1=1, v2_version=version, v23_sep=V23_SEP)  # v1=1: updated, never added
            _v1_comment(path, tags)
        else:
            f.save(v2_version=version, v23_sep=V23_SEP)
    elif kind in ("aac", "alac"):
        _mp4(tags, change, before)
        f.save()
    else:
        _vorbis(f, change, before, kind)
        f.save()


def _tags(f: Any) -> Any:
    """The file's tags, added when it has none."""
    if f.tags is None:
        f.add_tags()
    return f.tags


# ---------- ID3 ----------


def _id3(
    tags: mutagen.id3.ID3,
    change: compose.Change,
    before: Tags,
    version: int,
    rating_scale: str = "windows-media",
) -> None:
    for fid, texts in compose.id3(change, before).items():
        tags.delall(fid)
        if texts:
            tags.add(getattr(mutagen.id3, fid)(encoding=3, text=texts))
    if "comment" in change:
        for frame in tags.getall("COMM"):
            if parse.is_comment(frame.desc):
                del tags[frame.HashKey]
        if change["comment"]:
            tags.add(mutagen.id3.COMM(encoding=3, lang="eng", desc="", text=[change["comment"]]))
    if "rating" in change:
        stars = int(change["rating"])  # type: ignore[call-overload]
        if rating_scale == compose.MUSIKATA_SCALE:
            _musikata_popm(tags, stars)
        else:
            _popm(tags, stars)
    if "cover" in change:
        _apic(tags, change["cover"])  # type: ignore[arg-type]
    _versions(tags, version)


def _popm(tags: mutagen.id3.ID3, stars: int) -> None:
    """R10.4's POPM, user Windows Media Player 9 Series, its play count kept. Cleared, it is taken
    out, unless another program's POPM would then read in its place (R10.4.1), or it counts
    plays: then it says 0."""
    key = f"POPM:{parse.WMP}"
    count = int(getattr(tags[key], "count", 0) or 0) if key in tags else 0
    tags.delall(key)
    if stars or count or tags.getall("POPM"):
        tags.add(mutagen.id3.POPM(email=parse.WMP, rating=compose.popm(stars), count=count))


def _musikata_popm(tags: mutagen.id3.ID3, stars: int) -> None:
    """R10.4.1's setting: the rating in MusiKata's own scale, under the user MusiKata, its play
    count kept, cleared as `_popm` clears; Windows Media Player's POPM, which a reader prefers
    (R10.4.1), kept in step when the file has one, so the rating reads back as written."""
    key = f"POPM:{parse.MUSIKATA}"
    count = int(getattr(tags[key], "count", 0) or 0) if key in tags else 0
    tags.delall(key)
    wmp = f"POPM:{parse.WMP}"
    if wmp in tags:
        frame = tags[wmp]
        frame.rating = compose.popm(stars)
    if stars or count or tags.getall("POPM"):
        tags.add(
            mutagen.id3.POPM(email=parse.MUSIKATA, rating=compose.musikata_popm(stars), count=count)
        )


def _apic(tags: mutagen.id3.ID3, cover: Picture | None) -> None:
    """The front cover (APIC type 3) replaced by `cover`, or taken out (None), the other pictures
    kept, after it (compose.pictures_after)."""
    kept = [f for f in tags.getall("APIC") if f.type != compose.FRONT]
    tags.delall("APIC")
    if cover is not None:
        desc = "" if all(f.desc for f in kept) else "Front cover"  # APICs are kept by description
        tags.add(
            mutagen.id3.APIC(
                encoding=3, mime=cover.mime, type=compose.FRONT, desc=desc, data=cover.data
            )
        )
    for f in kept:
        tags.add(f)


def _versions(tags: mutagen.id3.ID3, version: int) -> None:
    """Ready to save as ID3v2.`version`: Mutagen's own frames made that version's, and the frames
    it doesn't know converted to it, those that can't be logged."""
    source = int(getattr(tags, "_unknown_v2_version", version))
    if tags.unknown_frames and source != version:
        kept = []
        for raw in tags.unknown_frames:
            made = compose.id3_frame_to(raw, source, version)
            if made is None:
                log.warning(
                    "an ID3v2.%d frame %r can't be written as ID3v2.%d: left out",
                    source,
                    bytes(raw[: 3 if source == 2 else 4]).decode("latin-1"),
                    version,
                )
            else:
                kept.append(made)
        tags.unknown_frames = kept
        # Mutagen writes its unknown frames only in the version they were read in
        tags._unknown_v2_version = version
    if version == 3:
        # the ID3v2.4 frames other programs write in ID3v2.3 too, which update_to_v23 would drop
        extra = [
            f
            for f in tags.values()
            if f.FrameID in V24_ONLY and f.FrameID not in compose.V24_ONLY_CONVERTED
        ]
        tags.update_to_v23()  # numbered genres made names on the way (R9.3), as in loading
        for f in extra:
            tags.add(f)
    if "TCON" in tags:  # R9.2: a value per genre in ID3v2.4, joined with "; " in ID3v2.3
        genres = parse.genres(str(g) for g in tags["TCON"].genres)
        text = compose.id3v23_genres(genres) if version == 3 else list(genres)
        if text:
            tags["TCON"].text = text
        else:
            del tags["TCON"]


V24_ONLY = ("ASPI", "EQU2", "RVA2", "SEEK", "SIGN", "TDEN", "TDOR", "TDRC", "TDRL", "TDTG", "TIPL",
            "TMCL", "TMOO", "TPRO", "TSOA", "TSOP", "TSOT", "TSST")  # fmt: skip


def _v1_comment(path: str, tags: mutagen.id3.ID3) -> None:
    """An ID3v1 tag kept in step (R4.7.2) with the comment too: Mutagen's own leaves it out."""
    comment = next((f for f in tags.getall("COMM") if parse.is_comment(f.desc) and f.text), None)
    with open(path, "r+b") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() < 128:
            return
        f.seek(-128, os.SEEK_END)
        if f.read(3) != b"TAG" or comment is None:
            return
        frames: dict[str, Any] = {k: tags[k] for k in ("TIT2", "TPE1", "TALB", "TRCK", "TCON",
                                                        "TDRC", "TYER") if k in tags}  # fmt: skip
        frames["COMM"] = comment
        f.seek(-128, os.SEEK_END)
        f.write(mutagen.id3.MakeID3v1(frames))


# ---------- MP4 ----------


def _mp4(tags: mutagen.mp4.MP4Tags, change: compose.Change, before: Tags) -> None:
    for atom, value in compose.mp4(change, before).items():
        if atom == compose.MP4_RATING:  # a freeform name, in whatever case the file has it
            for key in [k for k in tags if k.lower() == atom.lower()]:
                del tags[key]
            if value:
                tags[atom] = [mutagen.mp4.MP4FreeForm(v) for v in cast(list[bytes], value)]
        elif value is None:
            tags.pop(atom, None)
        else:
            tags[atom] = value
    if "rating" in change:  # another player's FMPS_Rating, which reads where RATING is none
        stars = int(change["rating"])  # type: ignore[call-overload]
        for key in [k for k in tags if k.lower() == compose.MP4_FMPS.lower()]:
            if stars:
                tags[key] = [mutagen.mp4.MP4FreeForm(f"{stars / 5:.1f}".encode())]
            else:
                del tags[key]
    if "cover" in change:
        cover: Picture | None = change["cover"]  # type: ignore[assignment]
        before_covers: list[Any] = list(tags.get("covr") or [])
        covers = before_covers[1:]
        if cover is not None:
            png = cover.mime.lower() == "image/png" or cover.data[:4] == b"\x89PNG"
            form = mutagen.mp4.MP4Cover.FORMAT_PNG if png else mutagen.mp4.MP4Cover.FORMAT_JPEG
            covers.insert(0, mutagen.mp4.MP4Cover(cover.data, imageformat=form))
        if covers:
            tags["covr"] = covers
        else:
            tags.pop("covr", None)


# ---------- Vorbis comments ----------


def _vorbis(f: Any, change: compose.Change, before: Tags, kind: str) -> None:
    """Each key the change rewrites replaced where it first was, in whatever case the file has it;
    every other comment kept as it was, in its order (R4.1.1)."""
    edit = compose.vorbis(change, before)
    if "cover" in change:
        cover: Picture | None = change["cover"]  # type: ignore[assignment]
        if kind == "flac":
            _flac_pictures(f, cover)
            edit["METADATA_BLOCK_PICTURE"] = _comment_pictures(f.tags, None)
        else:
            edit["METADATA_BLOCK_PICTURE"] = _comment_pictures(f.tags, cover)
    out: list[tuple[str, str]] = []
    placed: set[str] = set()
    key: str
    value: str
    for key, value in list(f.tags):
        name = key.upper()
        if name not in edit:
            out.append((key, value))
        elif name not in placed:
            placed.add(name)
            out += [(name, v) for v in edit[name]]
    for name, values in edit.items():
        if name not in placed:
            out += [(name, v) for v in values]
    f.tags[:] = out


def _flac_pictures(f: Any, cover: Picture | None) -> None:
    kept = [p for p in f.pictures if p.type != compose.FRONT]
    f.clear_pictures()
    for p in ([_flac_picture(cover)] if cover is not None else []) + kept:
        f.add_picture(p)


def _flac_picture(cover: Picture) -> mutagen.flac.Picture:
    p = mutagen.flac.Picture()
    p.type, p.mime, p.data = compose.FRONT, cover.mime, cover.data
    p.width, p.height, p.depth = compose.image_size(cover.data)
    return p


def _comment_pictures(tags: Any, cover: Picture | None) -> list[str]:
    """The METADATA_BLOCK_PICTURE comments once the cover is `cover`: the new one first, then
    each that isn't a front cover, or can't be read, as it was."""
    out = [base64.b64encode(_flac_picture(cover).write()).decode()] if cover is not None else []
    value: str
    for key, value in tags:
        if key.upper() != "METADATA_BLOCK_PICTURE":
            continue
        try:
            front = mutagen.flac.Picture(base64.b64decode(value)).type == compose.FRONT
        except binascii.Error, ValueError, struct.error, mutagen.MutagenError:
            front = False
        if not front:
            out.append(value)
    return out


# ---------- the copy, with a WAV's INFO chunk kept in step ----------


def copy(source: str, dest: str, change: compose.Change) -> None:
    """The file at `source` copied to `dest`, byte for byte, but for a WAV whose INFO chunk holds
    fields the change rewrites (compose.info): that chunk rewritten, the RIFF size made to
    match."""
    values = compose.info(change) if source.lower().endswith(".wav") else {}
    if not values:
        shutil.copyfile(source, dest)
        return
    with open(source, "rb") as src, open(dest, "wb") as out:
        head = src.read(12)
        out.write(head)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            shutil.copyfileobj(src, out, CHUNK)
            return
        while True:
            header = src.read(8)
            if len(header) < 8:
                out.write(header)
                break
            size = int.from_bytes(header[4:], "little")
            if header[:4] == b"LIST":
                body = src.read(size + (size & 1))
                if body[:4] == b"INFO":
                    new = compose.riff_info_edit(body[:size], values)
                    out.write(b"LIST" + len(new).to_bytes(4, "little") + new)
                    out.write(b"\x00" * (len(new) & 1))
                else:
                    out.write(header + body)
            else:
                out.write(header)
                _copy_bytes(src, out, size + (size & 1))
        end = out.tell()
        out.seek(4)
        out.write((end - 8).to_bytes(4, "little"))


def _copy_bytes(src: BinaryIO, out: BinaryIO, n: int) -> None:
    while n > 0:
        block = src.read(min(n, CHUNK))
        if not block:
            return
        out.write(block)
        n -= len(block)
