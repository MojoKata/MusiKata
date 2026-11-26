"""Writing tags as plain data: R4.1's fields, as a save changes them, into each kind's frames,
comments and atoms (A3.2), through the tables parse.py reads with, so what is written reads back as
written. No file is opened here (docs/process/coding.md, "Built to be tested in isolation"):
write.py hands these what Mutagen holds and applies what they give.

A change names only the fields it sets; a field set empty (None, "", no genres, 0) is removed, and
whatever a change doesn't name is left as the file holds it, in the file's own form (R4.1.1): a
track written as `04` stays `04` while only the title changes."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from . import parse
from .fields import Picture, Tags

# R4.1's fields a save can set, by the names Tags gives them (ReplayGain is read only)
TEXT = ("title", "artist", "album", "albumartist", "composer", "comment", "artistsort",
        "albumartistsort", "albumsort")  # fmt: skip
NUMBERS = ("track", "tracktotal", "disc", "disctotal")
FIELDS = (*TEXT, *NUMBERS, "year", "genres", "compilation", "rating", "cover")

# R10.4: the POPM value (user Windows Media Player 9 Series) for 0 to 5 stars
POPM_VALUES = (0, 1, 64, 128, 196, 255)
MP4_RATING = "----:com.apple.iTunes:RATING"
FRONT = 3  # the front cover's picture type, as ID3 and FLAC number them
UNRATED = ("wav", "aiff")  # R10.4: kinds whose ratings the root's ratings.json keeps, not the file

# a change, normalized: each field it names with its value as `normalize` gives it
Change = Mapping[str, object]


def normalize(changes: Mapping[str, object]) -> dict[str, object]:
    """A save's changes, by R4.1 field (`FIELDS`), as the writers take them: text stripped, and
    None when empty; numbers above 0, else None; the year, an int or a date ("2003-05-01"), as
    a pair (year, full date or None); genres each once, as parse.genres reads them; the rating
    0 to 5, 0 cleared; the cover a Picture, or None to remove it. Raises ValueError for a field
    that isn't one, or a value of the wrong kind: a caller's mistake, not the file's."""
    out: dict[str, object] = {}
    for name, value in changes.items():
        if name in TEXT:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} is text, not {value!r}")
            out[name] = parse.text([value or ""])
        elif name in NUMBERS:
            out[name] = _number(name, value)
        elif name == "year":
            out[name] = _year(value)
        elif name == "genres":
            if isinstance(value, str) or not isinstance(value, Sequence):
                raise ValueError(f"genres are a list of names, not {value!r}")
            if not all(isinstance(g, str) for g in value):
                raise ValueError(f"genres are names, not {value!r}")
            out[name] = parse.genres(value)
        elif name == "compilation":
            if not isinstance(value, bool):
                raise ValueError(f"compilation is yes or no, not {value!r}")
            out[name] = value
        elif name == "rating":
            stars = _number(name, value) or 0
            if stars > 5:
                raise ValueError(f"a rating is 0 to 5 stars, not {value!r}")
            out[name] = stars
        elif name == "cover":
            if value is not None and not isinstance(value, Picture):
                raise ValueError(f"a cover is a Picture, not {value!r}")
            out[name] = value if value is None or value.data else None
        else:
            raise ValueError(f"{name!r} isn't a field MusiKata writes")
    return out


def _number(name: str, value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} is a whole number, not {value!r}")
    return value or None


def _year(value: object) -> tuple[int | None, str | None]:
    if value is None or value == "":
        return None, None
    if isinstance(value, int) and not isinstance(value, bool):
        year, date = parse.year_and_date(f"{value:04d}") if value >= 0 else (None, None)
    elif isinstance(value, str):
        year, date = parse.year_and_date(value)
    else:
        year, date = None, None
    if year is None:
        raise ValueError(f"a year is four digits or a date, not {value!r}")
    return year, date


def effective(change: Change, before: Tags) -> dict[str, object]:
    """What of a normalized change differs from the file as read (`before`): only that is
    written, so a field already as asked keeps its form. A year the file's full date already has
    keeps the date (R4.1). The cover is always written: Tags doesn't hold its bytes."""
    out: dict[str, object] = {}
    for name, value in change.items():
        if name == "year":
            year, date = _year_of(value)
            if (year, date) == (before.year, before.date) or (date is None and year == before.year):
                continue
        elif name == "rating":
            if value == (before.rating or 0):
                continue
        elif name != "cover" and value == getattr(before, name):
            continue
        out[name] = value
    return out


def expected(before: Tags, change: Change) -> Tags:
    """The tags the file should read back as once `change` (`effective`) is written. Whether it
    has a cover is left as it was: write.py checks the pictures themselves."""
    fields: dict[str, object] = {}
    for name, value in change.items():
        if name == "year":
            fields["year"], fields["date"] = _year_of(value)
        elif name == "rating":
            fields["rating"] = value or None
        elif name != "cover":
            fields[name] = value
    return replace(before, **fields)  # type: ignore[arg-type]


def differences(want: Tags, got: Tags, cover: bool = False) -> list[str]:
    """The fields that read back otherwise than written, by name; a rating cleared reads back as
    0 or none. `cover`: the cover changed, so whether there is one isn't compared here."""
    out = []
    for name in Tags.__dataclass_fields__:
        a, b = getattr(want, name), getattr(got, name)
        if name == "rating":
            a, b = a or None, b or None
        elif name == "has_cover" and cover:
            continue
        if a != b:
            out.append(name)
    return out


def _year_of(value: object) -> tuple[int | None, str | None]:
    """A normalized change's year: (year, full date or None)."""
    return cast(tuple[int | None, str | None], value)


def _date_text(value: object) -> str | None:
    year, date = _year_of(value)
    return date or (f"{year:04d}" if year else None)


def _pair(change: Change, before: Tags, number: str, total: str) -> tuple[int | None, int | None]:
    n = change[number] if number in change else getattr(before, number)
    t = change[total] if total in change else getattr(before, total)
    return n, t  # type: ignore[return-value]


def _values(value: object) -> list[str]:
    return [value] if isinstance(value, str) else []


# ---------- Vorbis comments (FLAC, Ogg, Opus) ----------


def vorbis(change: Change, before: Tags) -> dict[str, list[str]]:
    """The Vorbis comments a change rewrites: each key (upper-cased) with its new values, none to
    remove it, in whatever case the file has it. Track and disc are written as TRACKNUMBER and
    TRACKTOTAL (DISCNUMBER, DISCTOTAL), the older TOTALTRACKS and TOTALDISCS removed; a field's
    older keys (ALBUM ARTIST, YEAR, and DESCRIPTION when the comment goes) go with it, so they
    can't read back in its place. The rating is RATING and FMPS_RATING (R10.4)."""
    out: dict[str, list[str]] = {}
    for name, key in parse.VORBIS.items():
        if name in change:
            out[key] = _values(change[name])
    if "albumartist" in change:
        out["ALBUM ARTIST"] = []
    if "comment" in change and change["comment"] is None:
        out["DESCRIPTION"] = []
    for number, total, keys in (
        ("track", "tracktotal", ("TRACKNUMBER", "TRACKTOTAL", "TOTALTRACKS")),
        ("disc", "disctotal", ("DISCNUMBER", "DISCTOTAL", "TOTALDISCS")),
    ):
        if number in change or total in change:
            n, t = _pair(change, before, number, total)
            out[keys[0]] = [str(n)] if n else []
            out[keys[1]] = [str(t)] if t else []
            out[keys[2]] = []
    if "year" in change:
        out["DATE"] = _values(_date_text(change["year"]))
        out["YEAR"] = []
    if "genres" in change:
        out["GENRE"] = list(change["genres"])  # type: ignore[call-overload]
    if "compilation" in change:
        out["COMPILATION"] = ["1"] if change["compilation"] else []
    if "rating" in change:
        stars = int(change["rating"])  # type: ignore[call-overload]
        out["RATING"] = [str(stars * 20)] if stars else []
        out["FMPS_RATING"] = [f"{stars / 5:.1f}"] if stars else []
    return out


# ---------- ID3v2 (MP3, WAV, AIFF) ----------


def id3(change: Change, before: Tags) -> dict[str, list[str]]:
    """The ID3v2 text frames a change rewrites: each frame id with its new texts, none to remove
    it. Track and disc are TRCK and TPOS as "4/10" ("4" without a total, "0/10" without a number);
    the year is TDRC, a full date when there is one, and Mutagen writes it as TYER and TDAT in
    ID3v2.3; the older TYER, TDAT and TIME go when it changes. The comment (COMM), the rating
    (POPM) and the cover (APIC) are write.py's, as frames of their own kind."""
    out: dict[str, list[str]] = {}
    for name, frame in parse.ID3.items():
        if name in change:
            out[frame] = _values(change[name])
    for number, total, frame in (("track", "tracktotal", "TRCK"), ("disc", "disctotal", "TPOS")):
        if number in change or total in change:
            n, t = _pair(change, before, number, total)
            out[frame] = [f"{n or 0}/{t}" if t else f"{n}"] if n or t else []
    if "year" in change:
        out["TDRC"] = _values(_date_text(change["year"]))
        out.update(TYER=[], TDAT=[], TIME=[])
    if "genres" in change:
        out["TCON"] = list(change["genres"])  # type: ignore[call-overload]
    if "compilation" in change:
        out["TCMP"] = ["1"] if change["compilation"] else []
    return out


def popm(stars: int) -> int:
    """R10.4's POPM value for 0 to 5 stars."""
    return POPM_VALUES[stars]


def id3v23_genres(genres: Sequence[str]) -> list[str]:
    """TCON's text in ID3v2.3, which holds one value: the genres joined with "; " (R9.2)."""
    return ["; ".join(genres)] if genres else []


V24_ONLY_CONVERTED = ("TDRC", "TDOR", "TIPL", "TMCL")  # Mutagen turns these into ID3v2.3's own


def id3_frame_to(frame: bytes, source: int, target: int) -> bytes | None:
    """An ID3v2 frame Mutagen doesn't know, as its raw bytes in ID3v2.`source`, made a frame of
    ID3v2.`target` (3 or 4), so a file written in the other version keeps it (R4.1.1): its size
    as that version writes sizes, its status flags moved to where that version keeps them. None
    when it can't be: a v2.2 frame (three-letter ids no later version has), or one compressed,
    encrypted or grouped, whose layout the two versions don't share."""
    if source == target:
        return frame
    if source not in (3, 4) or target not in (3, 4) or len(frame) < 10:
        return None
    fid, size, status, fmt = frame[:4], frame[4:8], frame[8], frame[9]
    if fmt or not re.fullmatch(rb"[A-Z0-9]{4}", fid):
        return None
    n = _synchsafe(size) if source == 4 else int.from_bytes(size, "big")
    if n != len(frame) - 10:
        return None
    if target == 4:
        size_out = bytes((n >> s) & 0x7F for s in (21, 14, 7, 0))
        status_out = (status >> 1) & 0x70  # 2.3's 0x80, 0x40, 0x20 are 2.4's 0x40, 0x20, 0x10
    else:
        size_out = n.to_bytes(4, "big")
        status_out = (status << 1) & 0xE0
    return fid + size_out + bytes([status_out, 0]) + frame[10:]


def _synchsafe(b: bytes) -> int:
    return (b[0] & 127) << 21 | (b[1] & 127) << 14 | (b[2] & 127) << 7 | (b[3] & 127)


# ---------- MP4 ----------


def mp4(change: Change, before: Tags) -> dict[str, object]:
    """The MP4 atoms a change rewrites, each with its new value as Mutagen takes it, None to
    remove it: text atoms a list of strings, trkn and disk a list of one (number, total) pair, 0
    for either missing, cpil True, ©gen one value per genre, the rating the freeform atom
    `MP4_RATING` as a list of bytes (20 to 100, R10.4)."""
    out: dict[str, object] = {}
    for name, atom in parse.MP4.items():
        if name in change:
            out[atom] = _values(change[name]) or None
    for number, total, atom in (("track", "tracktotal", "trkn"), ("disc", "disctotal", "disk")):
        if number in change or total in change:
            n, t = _pair(change, before, number, total)
            out[atom] = [(n or 0, t or 0)] if n or t else None
    if "year" in change:
        out["\xa9day"] = _values(_date_text(change["year"])) or None
    if "genres" in change:
        out["\xa9gen"] = list(change["genres"]) or None  # type: ignore[call-overload]
    if "compilation" in change:
        out["cpil"] = True if change["compilation"] else None
    if "rating" in change:
        stars = int(change["rating"])  # type: ignore[call-overload]
        out[MP4_RATING] = [str(stars * 20).encode()] if stars else None
    return out


# ---------- pictures ----------


def pictures_after(before: Sequence[Picture], cover: Picture | None, typed: bool) -> list[Picture]:
    """A song's pictures once its cover is set (`cover`) or removed (None): the new cover first,
    as the front cover, and the others as they were. `typed`: the kind numbers its pictures (ID3,
    FLAC, Vorbis comments), so each front cover gives way; MP4's covr doesn't, so its first, the
    one shown as the cover (R5.1), does."""
    rest = [p for p in before if p.type != FRONT] if typed else list(before[1:])
    return ([cover] if cover is not None else []) + rest


def cover_of(pictures: Sequence[Picture], typed: bool) -> Picture | None:
    """The picture a cover set or removed replaces (`pictures_after`): where the kind numbers its
    pictures (`typed`), its first front cover; in MP4's covr, its first picture. None: none."""
    if typed:
        return next((p for p in pictures if p.type == FRONT), None)
    return pictures[0] if pictures else None


def image_mime(data: bytes) -> str:
    """A cover's MIME type from its bytes, for a cover kept without one (the change history keeps
    only the bytes, A3.5): PNG, GIF and WebP by their marks, else JPEG."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def image_size(data: bytes) -> tuple[int, int, int]:
    """A PNG's or a JPEG's width, height and bits per pixel, as FLAC's picture block records
    them; zeros for another kind of image, or one that can't be read."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 26:
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(data[25], 0)
        w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        return w, h, data[24] * channels
    if data[:2] == b"\xff\xd8":
        pos = 2
        while pos + 4 <= len(data) and data[pos] == 0xFF:
            marker, n = data[pos + 1], int.from_bytes(data[pos + 2 : pos + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                if pos + 10 > len(data):
                    break
                h = int.from_bytes(data[pos + 5 : pos + 7], "big")
                w = int.from_bytes(data[pos + 7 : pos + 9], "big")
                return w, h, data[pos + 4] * data[pos + 9]
            pos += 2 + n
    return 0, 0, 0


# ---------- a WAV's RIFF INFO ----------

# R4.1's fields as RIFF INFO ids (parse._INFO, the other way)
INFO = {"title": ("INAM",), "artist": ("IART",), "album": ("IPRD",), "genres": ("IGNR",),
        "year": ("ICRD",), "track": ("ITRK", "IPRT"), "comment": ("ICMT",),
        "composer": ("ICMP",)}  # fmt: skip


def info(change: Change) -> dict[str, str | None]:
    """The RIFF INFO values a change rewrites in a WAV that has an INFO chunk, by id: None
    removes one. As for an ID3v1 tag (R4.7.2), an INFO chunk already there is kept in step with
    the ID3 tag, so neither reads back in the other's place; none is added."""
    out: dict[str, str | None] = {}
    for name, ids in INFO.items():
        if name not in change:
            continue
        value = change[name]
        if name == "genres":
            text = "; ".join(cast(Sequence[str], value)) or None
        elif name == "year":
            text = _date_text(value)
        elif name == "track":
            text = str(value) if value else None
        else:
            text = value if isinstance(value, str) else None
        out.update(dict.fromkeys(ids, text))
    return out


def riff_info_edit(body: bytes, values: Mapping[str, str | None]) -> bytes:
    """A LIST chunk's body ("INFO" and its sub-chunks) with each sub-chunk `values` names given
    its new text (UTF-8, NUL-ended, padded to even) or, for None, taken out; the others, and
    whatever follows a sub-chunk cut short, kept as they were. None is added."""
    out = bytearray(body[:4])
    pos = 4
    while pos + 8 <= len(body):
        sid = body[pos : pos + 4].decode("latin-1")
        n = int.from_bytes(body[pos + 4 : pos + 8], "little")
        end = pos + 8 + n + (n & 1)
        if end > len(body):
            break
        if sid in values:
            text = values[sid]
            if text is not None:
                data = text.encode("utf-8") + b"\x00"
                out += body[pos : pos + 4] + len(data).to_bytes(4, "little") + data
                out += b"\x00" * (len(data) & 1)
        else:
            out += body[pos:end]
        pos = end
    out += body[pos:]
    return bytes(out)
