"""Reading tags as plain data: each kind's fields, given as the strings its file holds, into R4.1's
fields (A3.2). No file is opened here (docs/process/coding.md, "Built to be tested in isolation");
read.py hands these what Mutagen found. Each function takes what other programs write, not only
what MusiKata writes (docs/process/testing.md, "Shapes", `tags`)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from .fields import Tags

# a file's fields, by its own key: an ID3 frame id, an upper-cased Vorbis key, an MP4 atom
Raw = Mapping[str, Sequence[str]]

WMP = "Windows Media Player 9 Series"  # R10.4's POPM user
MUSIKATA = "MusiKata"  # R10.4.1's, with MusiKata's own scale


def text(values: Sequence[str] | None) -> str | None:
    """The first value that isn't blank, stripped; None when there is none."""
    for v in values or ():
        v = v.replace("\x00", "").strip()
        if v:
            return v
    return None


def number_pair(value: str | None) -> tuple[int | None, int | None]:
    """A track or disc number and its total: "4", "04", "4/10", " 4 / 10 ", "4 of 10"; whatever
    isn't a number is None."""
    if not value:
        return None, None
    m = re.match(r"\s*(\d+)?\s*(?:(?:/|of)\s*(\d+))?", value, re.I)
    if not m:
        return None, None
    n = int(m.group(1)) if m.group(1) else None
    total = int(m.group(2)) if m.group(2) else None
    return (n or None), (total or None)


def number(value: str | None) -> int | None:
    """A number alone ("10", "010"), as a total is written by itself."""
    return number_pair(value)[0]


def year_and_date(value: str | None) -> tuple[int | None, str | None]:
    """The year, and the full date when there is more than a year: "2003", "2003-05-01",
    "2003-05", "2003-05-01T10:00:00", "20030501", "2003/05/01". A year outside 1000-2999 is
    none."""
    if not value:
        return None, None
    v = value.strip()
    m = re.match(r"(\d{4})(?:[-/.]?(\d{2})(?:[-/.]?(\d{2}))?)?", v)
    if not m or not 1000 <= int(m.group(1)) <= 2999:
        return None, None
    year = int(m.group(1))
    if m.group(2) and m.group(3):
        return year, f"{year:04d}-{m.group(2)}-{m.group(3)}"
    if m.group(2):
        return year, f"{year:04d}-{m.group(2)}"
    return year, None


def id3v23_date(tyer: str | None, tdat: str | None) -> tuple[int | None, str | None]:
    """ID3v2.3 splits the date: TYER the year, TDAT the day and month as DDMM."""
    year, _ = year_and_date(tyer)
    if year and tdat and re.fullmatch(r"\d{4}", tdat.strip()):
        day, month = tdat.strip()[:2], tdat.strip()[2:]
        if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
            return year, f"{year:04d}-{month}-{day}"
    return year, None


def genres(values: Iterable[str]) -> tuple[str, ...]:
    """Each genre once, in order, from values that may each hold several joined with ";" (R9.2's
    ID3v2.3 form, and what other programs write) or NUL. "/" is left alone: it is part of names
    such as "R&B/Soul" more often than a separator."""
    out: list[str] = []
    for v in values:
        for g in re.split(r"[;\x00]", v):
            g = g.strip()
            if g and g.casefold() not in (o.casefold() for o in out):
                out.append(g)
    return tuple(out)


def flag(value: str | None) -> bool:
    """A yes-or-no field (Compilation): "1", "true", "yes"."""
    return (value or "").strip().lower() in ("1", "true", "yes")


def popm_stars(value: int) -> int:
    """A POPM value, 0 to 255, as stars by the ranges the common players use (R10.4.1)."""
    if value <= 0:
        return 0
    for top, stars in ((31, 1), (95, 2), (159, 3), (223, 4)):
        if value <= top:
            return stars
    return 5


def musikata_popm_stars(value: int) -> int:
    """MusiKata's own POPM scale (R10.4.1): stars times 51."""
    return max(0, min(5, round(value / 51)))


def popm_rating(popms: Sequence[tuple[str, int]]) -> int | None:
    """The stars of a file's POPM frames, any user's, preferring Windows Media Player's, then
    MusiKata's (R10.4.1)."""
    if not popms:
        return None
    by_user = dict(popms)
    if WMP in by_user:
        return popm_stars(by_user[WMP])
    if MUSIKATA in by_user:
        return musikata_popm_stars(by_user[MUSIKATA])
    return popm_stars(popms[0][1])


def vorbis_rating(rating: str | None, fmps: str | None) -> int | None:
    """RATING as stars when 5 or less and as hundredths when more; FMPS_RATING as 0.0 to 1.0;
    RATING wins when both are there (R10.4.2)."""
    for value, scale in ((rating, None), (fmps, 5.0)):
        try:
            x = float((value or "").strip().replace(",", "."))
        except ValueError:
            continue
        if x < 0:
            continue
        stars = (x if x <= 5 else x / 20) if scale is None else min(x, 1.0) * scale
        return max(0, min(5, round(stars)))
    return None


def replaygain(value: str | None) -> float | None:
    """A ReplayGain value: "-6.20 dB", "+1.5 dB", "0.988547"; None when it isn't a number."""
    if not value:
        return None
    m = re.match(r"\s*([+-]?\d+(?:[.,]\d+)?)", value)
    return float(m.group(1).replace(",", ".")) if m else None


R128_OFFSET = 5.0  # dB from EBU R 128's -23 LUFS, which Opus's R128_* gains are to, to ReplayGain's
# 89 dB (-18 LUFS), as foobar2000, rsgain and opusgain take it


def r128(value: str | None) -> float | None:
    """An Opus R128_TRACK_GAIN or R128_ALBUM_GAIN (RFC 7845): a whole number of 1/256 dB to
    -23 LUFS, as a ReplayGain gain in dB; None when it isn't a whole number that fits 16 bits."""
    m = re.fullmatch(r"\s*([+-]?\d{1,6})\s*", value or "")
    if not m or not -32768 <= int(m.group(1)) <= 32767:
        return None
    return int(m.group(1)) / 256 + R128_OFFSET


RG_FIELDS = ("rg_track_gain", "rg_track_peak", "rg_album_gain", "rg_album_peak")


def replaygain_of(raw: Raw) -> dict[str, float | None]:
    """The four ReplayGain fields from REPLAYGAIN_* keys, in any case, as Vorbis comments and
    APEv2 tags (mp3gain's, foobar2000's on MP3) hold them."""
    by_key = {k.upper(): v for k, v in raw.items()}
    return {
        f: replaygain(text(by_key.get(f.replace("rg", "REPLAYGAIN").upper()))) for f in RG_FIELDS
    }


def rva2_replaygain(rva2: Sequence[tuple[str, float, float]]) -> dict[str, float | None]:
    """The ReplayGain fields from ID3v2.4's RVA2 frames, (identification, master volume's gain in
    dB, its peak), as Quod Libet and Mutagen's EasyID3 write them: "track" and "album"."""
    out: dict[str, float | None] = dict.fromkeys(RG_FIELDS)
    for desc, gain, peak in rva2:
        which = desc.strip().lower()
        if which in ("track", "album"):
            out[f"rg_{which}_gain"] = gain
            out[f"rg_{which}_peak"] = peak if peak > 0 else None
    return out


def with_replaygain(tags: Tags, more: Mapping[str, float | None]) -> Tags:
    """`tags` with ReplayGain from another of the file's tags where its own has none (RVA2 beside
    TXXX, an MP3's APEv2 tag beside its ID3): gain and peak go together, from one or the other."""
    fields = dict(tags.__dict__)
    for which in ("track", "album"):
        gain, peak = f"rg_{which}_gain", f"rg_{which}_peak"
        if fields[gain] is None and more.get(gain) is not None:
            fields[gain], fields[peak] = more[gain], more.get(peak)
    return Tags(**fields)


# ---------- each kind's fields ----------

# Vorbis comments (FLAC, Ogg, Opus): keys upper-cased; several values are several fields
_VORBIS = {
    "title": "TITLE", "artist": "ARTIST", "album": "ALBUM", "albumartist": "ALBUMARTIST",
    "composer": "COMPOSER", "comment": "COMMENT", "artistsort": "ARTISTSORT",
    "albumartistsort": "ALBUMARTISTSORT", "albumsort": "ALBUMSORT",
}  # fmt: skip


def from_vorbis(raw: Raw, has_cover: bool = False) -> Tags:
    """Vorbis comments, keys in any case (read.py upper-cases them): A3.2's middle column. An
    album artist under "ALBUM ARTIST" (foobar2000's older form) is read too; DESCRIPTION is the
    comment when COMMENT isn't there; an Opus file's R128_TRACK_GAIN and R128_ALBUM_GAIN are its
    ReplayGain gains (`r128`)."""
    get = raw.get
    track, track_total = number_pair(text(get("TRACKNUMBER")))
    disc, disc_total = number_pair(text(get("DISCNUMBER")))
    year, date = year_and_date(text(get("DATE")) or text(get("YEAR")))
    fields = {k: text(get(v)) for k, v in _VORBIS.items()}
    fields["albumartist"] = fields["albumartist"] or text(get("ALBUM ARTIST"))
    fields["comment"] = fields["comment"] or text(get("DESCRIPTION"))
    gains = replaygain_of(raw)
    # Opus's own gains (RFC 7845) win over REPLAYGAIN_* there; they carry no peak
    for which in ("track", "album"):
        opus = r128(text(get(f"R128_{which.upper()}_GAIN")))
        if opus is not None:
            gains[f"rg_{which}_gain"] = opus
    return Tags(
        **fields,
        track=track,
        tracktotal=number(text(get("TRACKTOTAL")) or text(get("TOTALTRACKS"))) or track_total,
        disc=disc,
        disctotal=number(text(get("DISCTOTAL")) or text(get("TOTALDISCS"))) or disc_total,
        year=year,
        date=date,
        genres=genres(get("GENRE") or ()),
        compilation=flag(text(get("COMPILATION"))),
        rating=vorbis_rating(text(get("RATING")), text(get("FMPS_RATING"))),
        rg_track_gain=gains["rg_track_gain"],
        rg_track_peak=gains["rg_track_peak"],
        rg_album_gain=gains["rg_album_gain"],
        rg_album_peak=gains["rg_album_peak"],
        has_cover=has_cover,
    )


_ID3 = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2",
    "composer": "TCOM", "artistsort": "TSOP", "albumartistsort": "TSO2", "albumsort": "TSOA",
}  # fmt: skip


def from_id3(
    raw: Raw,
    popms: Sequence[tuple[str, int]] = (),
    comments: Sequence[tuple[str, str]] = (),
    has_cover: bool = False,
    rva2: Sequence[tuple[str, float, float]] = (),
) -> Tags:
    """ID3v2 frames by id (TCON already as genre names: read.py takes them from Mutagen, which
    turns ID3v1's numbers, "(17)", into names, R9.3), TXXX frames as "TXXX:<description>", each
    user's POPM, COMM frames as (description, text), and RVA2 frames as `rva2_replaygain` takes
    them. The comment is the COMM without a description (A3.2), else the first. ReplayGain is
    TXXX's, else RVA2's."""
    get = raw.get
    track, track_total = number_pair(text(get("TRCK")))
    disc, disc_total = number_pair(text(get("TPOS")))
    if get("TDRC"):
        year, date = year_and_date(text(get("TDRC")))
    else:
        year, date = id3v23_date(text(get("TYER")), text(get("TDAT")))
    comment = next((t for d, t in comments if not d and t.strip()), None) or next(
        (t for _, t in comments if t.strip()), None
    )

    def txxx(name: str) -> str | None:
        for key, values in raw.items():
            if key.upper() == f"TXXX:{name}".upper():
                return text(values)
        return None

    tags = Tags(
        **{k: text(get(v)) for k, v in _ID3.items()},
        track=track,
        tracktotal=track_total,
        disc=disc,
        disctotal=disc_total,
        year=year,
        date=date,
        genres=genres(get("TCON") or ()),
        comment=comment.strip() if comment else None,
        compilation=flag(text(get("TCMP"))),
        rating=popm_rating(popms),
        rg_track_gain=replaygain(txxx("REPLAYGAIN_TRACK_GAIN")),
        rg_track_peak=replaygain(txxx("REPLAYGAIN_TRACK_PEAK")),
        rg_album_gain=replaygain(txxx("REPLAYGAIN_ALBUM_GAIN")),
        rg_album_peak=replaygain(txxx("REPLAYGAIN_ALBUM_PEAK")),
        has_cover=has_cover,
    )
    return with_replaygain(tags, rva2_replaygain(rva2))


_MP4 = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "albumartist": "aART",
    "composer": "\xa9wrt", "comment": "\xa9cmt", "artistsort": "soar", "albumartistsort": "soaa",
    "albumsort": "soal",
}  # fmt: skip


def from_mp4(
    raw: Raw,
    track: tuple[int, int] | None = None,
    disc: tuple[int, int] | None = None,
    compilation: bool = False,
    has_cover: bool = False,
) -> Tags:
    """MP4 atoms (A3.2's last column), with trkn and disk as the number pairs Mutagen reads and
    the freeform `----:com.apple.iTunes:<name>` atoms as text, their names in any case."""
    get = raw.get
    year, date = year_and_date(text(get("\xa9day")))

    def freeform(name: str) -> str | None:
        for key, values in raw.items():
            if key.lower() == f"----:com.apple.itunes:{name}".lower():
                return text(values)
        return None

    t = track or (0, 0)
    d = disc or (0, 0)
    return Tags(
        **{k: text(get(v)) for k, v in _MP4.items()},
        track=t[0] or None,
        tracktotal=t[1] or None,
        disc=d[0] or None,
        disctotal=d[1] or None,
        year=year,
        date=date,
        genres=genres(get("\xa9gen") or ()),
        compilation=compilation,
        rating=vorbis_rating(freeform("RATING"), None),
        rg_track_gain=replaygain(freeform("replaygain_track_gain")),
        rg_track_peak=replaygain(freeform("replaygain_track_peak")),
        rg_album_gain=replaygain(freeform("replaygain_album_gain")),
        rg_album_peak=replaygain(freeform("replaygain_album_peak")),
        has_cover=has_cover,
    )


# RIFF INFO, the tags a WAV file holds beside an ID3 chunk (R2.2)
_INFO = {"INAM": "title", "IART": "artist", "IPRD": "album", "IGNR": "genre", "ICRD": "date",
         "ITRK": "track", "IPRT": "track", "ICMT": "comment", "ICMP": "composer"}  # fmt: skip


def riff_info(data: bytes) -> dict[str, str]:
    """The LIST/INFO chunk of a RIFF (WAV) file's bytes, by INFO id: what Mutagen doesn't read.
    Text is UTF-8 when it decodes so, Latin-1 otherwise; a chunk cut short ends the reading."""
    out: dict[str, str] = {}
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return out
    pos = 12
    while pos + 8 <= len(data):
        cid, size = data[pos : pos + 4], int.from_bytes(data[pos + 4 : pos + 8], "little")
        body = data[pos + 8 : pos + 8 + size]
        if cid == b"LIST" and body[:4] == b"INFO":
            sub = 4
            while sub + 8 <= len(body):
                sid = body[sub : sub + 4].decode("latin-1")
                n = int.from_bytes(body[sub + 4 : sub + 8], "little")
                raw = body[sub + 8 : sub + 8 + n].split(b"\x00", 1)[0]
                try:
                    value = raw.decode("utf-8")
                except UnicodeDecodeError:
                    value = raw.decode("latin-1")
                if value.strip():
                    out[sid] = value.strip()
                sub += 8 + n + (n & 1)
        pos += 8 + size + (size & 1)
    return out


def merge_info(tags: Tags, info: Mapping[str, str]) -> Tags:
    """A WAV file's ID3 tags with what its INFO chunk adds where ID3 has nothing."""
    fields = {_INFO[k]: v for k, v in info.items() if k in _INFO}
    track, _ = number_pair(fields.get("track"))
    year, date = year_and_date(fields.get("date"))
    return Tags(
        **{
            **tags.__dict__,
            "title": tags.title or fields.get("title"),
            "artist": tags.artist or fields.get("artist"),
            "album": tags.album or fields.get("album"),
            "composer": tags.composer or fields.get("composer"),
            "comment": tags.comment or fields.get("comment"),
            "genres": tags.genres or genres([fields.get("genre") or ""]),
            "track": tags.track or track,
            "year": tags.year or year,
            "date": tags.date or (date if not tags.year else None),
        }
    )
