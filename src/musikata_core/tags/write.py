"""Writing a song's tags with Mutagen (A3.1, A3.2): compose.py says what changes, as plain data, and
this applies it to the file as Mutagen holds it, touching nothing else (R4.1.1). It writes in
place, so safe.py hands it the copy beside the original (A3.4), never the song itself.

MP3s are written as ID3v2.4, or ID3v2.3 (R4.7.2); an ID3v1 tag already there is updated to match,
none added. Text is written as Unicode (UTF-8, or UTF-16 in ID3v2.3), but what a change asks to
hold as Latin-1 (compose.latin1_of: Undo's, A3.6). What Mutagen would drop going from one version
to the other is kept: the frames it doesn't know, made the other version's (compose.id3_frame_to),
and in ID3v2.3 the ID3v2.4 frames other programs write there too (TSOP, TSOA, RVA2: iTunes,
Picard). A WAV's RIFF INFO chunk, which Mutagen doesn't write, is kept in step as the copy is made
(`copy`)."""

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
ID3_FIELDS = {frame: name for name, frame in parse.ID3.items()}  # a text frame's R4.1 field
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
    latin1 = compose.latin1_of(change)  # Undo's: the bytes a save of R4.10 took (A3.6)
    for fid, texts in compose.id3(change, before).items():
        tags.delall(fid)
        if texts:
            encoding = 0 if ID3_FIELDS.get(fid) in latin1 else 3
            tags.add(getattr(mutagen.id3, fid)(encoding=encoding, text=texts))
    if "comment" in change:
        for frame in tags.getall("COMM"):
            if parse.is_comment(frame.desc):
                del tags[frame.HashKey]
        if change["comment"]:
            encoding = 0 if "comment" in latin1 else 3
            tags.add(
                mutagen.id3.COMM(encoding=encoding, lang="eng", desc="", text=[change["comment"]])
            )
    if "rating" in change:
        stars = int(change["rating"])  # type: ignore[call-overload]
        if rating_scale == compose.MUSIKATA_SCALE:
            _musikata_popm(tags, stars)
        else:
            _popm(tags, stars)
    if any(name in change for name in compose.PICTURES):
        _apic(tags, change)
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


def _apic(tags: mutagen.id3.ID3, change: compose.Change) -> None:
    """The front cover (APIC type 3) replaced by the change's `cover`, or taken out (None), and
    the other pictures replaced by its `others`; what it doesn't name kept, the front cover first
    (compose.pictures_after). ID3 keeps APICs by their descriptions, so each is made unique."""
    frames = tags.getall("APIC")
    fronts: list[Any] = [f for f in frames if f.type == compose.FRONT]
    rest: list[Any] = [f for f in frames if f.type != compose.FRONT]
    if "cover" in change:
        cover = cast(Picture | None, change["cover"])
        fronts = [_apic_frame(cover, compose.FRONT, "")] if cover is not None else []
    if "others" in change:
        rest = [_apic_frame(p, p.type or 0, p.desc) for p in cast(list[Picture], change["others"])]
    tags.delall("APIC")
    used: set[str] = set()
    for f in rest + fronts:  # the others keep their own; a front cover named "" gives way
        desc, n = f.desc, 1
        while desc in used:
            n += 1
            base = "Front cover" if f.type == compose.FRONT else (f.desc or "Picture")
            desc = base if n == 2 and f.type == compose.FRONT else f"{base} {n}"
        used.add(desc)
        f.desc = desc
    for f in fronts + rest:
        tags.add(f)


def _apic_frame(picture: Picture, kind: int, desc: str) -> mutagen.id3.APIC:
    mime = picture.mime or compose.image_mime(picture.data)
    return mutagen.id3.APIC(encoding=3, mime=mime, type=kind, desc=desc, data=picture.data)


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
        genres = parse.genres((str(g) for g in tags["TCON"].genres), numbered=True)
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
    if any(name in change for name in compose.PICTURES):
        before_covers: list[Any] = list(tags.get("covr") or [])
        fronts, covers = before_covers[:1], before_covers[1:]
        if "cover" in change:
            cover = cast(Picture | None, change["cover"])
            fronts = [_mp4_cover(cover)] if cover is not None else []
        if "others" in change:
            covers = [_mp4_cover(p) for p in cast(list[Picture], change["others"])]
        covers = fronts + covers
        if covers:
            tags["covr"] = covers
        else:
            tags.pop("covr", None)


def _mp4_cover(picture: Picture) -> mutagen.mp4.MP4Cover:
    png = picture.mime.lower() == "image/png" or picture.data[:4] == b"\x89PNG"
    form = mutagen.mp4.MP4Cover.FORMAT_PNG if png else mutagen.mp4.MP4Cover.FORMAT_JPEG
    return mutagen.mp4.MP4Cover(picture.data, imageformat=form)


# ---------- Vorbis comments ----------


def _vorbis(f: Any, change: compose.Change, before: Tags, kind: str) -> None:
    """Each key the change rewrites replaced where it first was, in whatever case the file has it;
    every other comment kept as it was, in its order (R4.1.1)."""
    edit = compose.vorbis(change, before)
    if any(name in change for name in compose.PICTURES):
        edit.update(_vorbis_pictures(f, change, kind == "flac"))
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


def _vorbis_pictures(f: Any, change: compose.Change, flac: bool) -> dict[str, list[str]]:
    """The pictures of a FLAC or Ogg file once the change's `cover` and `others` are written, the
    FLAC's picture blocks set here, and the comments that hold pictures returned, as `_vorbis`
    takes them: METADATA_BLOCK_PICTURE, front covers first, and, when the others change, the
    older COVERART, which holds a picture with no type. A new cover is a picture block in a FLAC
    (its front covers in comments go), a comment in an Ogg file; a comment that can't be read
    counts as another picture."""
    comments: list[tuple[str, bool]] = []
    value: str
    for key, value in f.tags:
        if key.upper() == "METADATA_BLOCK_PICTURE":
            comments.append((value, _comment_type(value) == compose.FRONT))
    front_comments = [v for v, front in comments if front]
    rest_comments = [v for v, front in comments if not front]
    out: dict[str, list[str]] = {}
    blocks = list(getattr(f, "pictures", []) if flac else [])
    front_blocks = [b for b in blocks if b.type == compose.FRONT]
    rest_blocks = [b for b in blocks if b.type != compose.FRONT]
    if "cover" in change:
        cover = cast(Picture | None, change["cover"])
        made = [_flac_picture(cover, compose.FRONT)] if cover is not None else []
        if flac:
            front_blocks, front_comments = made, []
        else:
            front_comments = [base64.b64encode(p.write()).decode() for p in made]
    if "others" in change:
        others = cast(list[Picture], change["others"])
        typed = [_flac_picture(p, p.type or 0) for p in others if p.type is not None]
        if flac:
            rest_blocks, rest_comments = typed, []
        else:
            rest_comments = [base64.b64encode(p.write()).decode() for p in typed]
        out["COVERART"] = [base64.b64encode(p.data).decode() for p in others if p.type is None]
    if flac:
        f.clear_pictures()
        for b in front_blocks + rest_blocks:
            f.add_picture(b)
    out["METADATA_BLOCK_PICTURE"] = front_comments + rest_comments
    return out


def _comment_type(value: str) -> int | None:
    """A METADATA_BLOCK_PICTURE comment's picture type; None when it can't be read."""
    try:
        return int(mutagen.flac.Picture(base64.b64decode(value)).type)
    except binascii.Error, ValueError, struct.error, mutagen.MutagenError:
        return None


def _flac_picture(picture: Picture, kind: int) -> mutagen.flac.Picture:
    p = mutagen.flac.Picture()
    p.type, p.mime, p.data, p.desc = kind, picture.mime, picture.data, picture.desc
    p.mime = p.mime or compose.image_mime(picture.data)
    p.width, p.height, p.depth = compose.image_size(picture.data)
    return p


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
