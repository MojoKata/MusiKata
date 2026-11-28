"""Reading tags as plain data: each kind's fields, given as the strings its file holds, into R4.1's
fields (A3.2). No file is opened here (docs/process/coding.md, "Built to be tested in isolation");
read.py hands these what Mutagen found. Each function takes what other programs write, not only
what MusiKata writes (docs/process/testing.md, "Shapes", `tags`)."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence

from mutagen.id3 import TCON

from .. import lyrics as lrc
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


_NUMBERED = re.compile(r"\(?\s*(\d{1,3})\s*\)?")  # ID3's numbered genres: "(13)", "13"


def numbered_genre(name: str) -> str:
    """A genre as ID3's numbered list names it, for a number of that list ("(13)" and "13" are
    "Pop", R9.3); any other name as it is."""
    m = _NUMBERED.fullmatch(name.strip())
    if m and int(m.group(1)) < len(TCON.GENRES):
        return str(TCON.GENRES[int(m.group(1))])
    return name


def genres(values: Iterable[str], numbered: bool = False) -> tuple[str, ...]:
    """Each genre once, in order, from values that may each hold several joined with ";" (R9.2's
    ID3v2.3 form, and what other programs write) or NUL. "/" is left alone: it is part of names
    such as "R&B/Soul" more often than a separator. `numbered`: an ID3 tag's, whose numbered
    genres are names (R9.3; Mutagen names those its own reading finds, not those after a ";")."""
    out: list[str] = []
    for v in values:
        for g in re.split(r"[;\x00]", v):
            g = numbered_genre(g).strip() if numbered else g.strip()
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
    RATING wins when both are there (R10.4.2). A half star (MusicBee's 10, 30 … 90, or 0.5 …
    4.5) rounds up. What float reads that isn't a number of stars ("inf", "nan") is no
    rating."""
    for value, scale in ((rating, None), (fmps, 5.0)):
        try:
            x = float((value or "").strip().replace(",", "."))
        except ValueError:
            continue
        if not math.isfinite(x) or x < 0:
            continue
        stars = (x if x <= 5 else x / 20) if scale is None else min(x, 1.0) * scale
        return max(0, min(5, math.floor(stars + 0.5)))
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

# A3.2's mapping, the text fields' half (the rest is each kind's function's): R4.1's field to its
# Vorbis comment (FLAC, Ogg, Opus; keys upper-cased; several values are several fields), its ID3v2
# frame and its MP4 atom. compose.py writes through the same tables.
VORBIS = {
    "title": "TITLE", "artist": "ARTIST", "album": "ALBUM", "albumartist": "ALBUMARTIST",
    "composer": "COMPOSER", "comment": "COMMENT", "artistsort": "ARTISTSORT",
    "albumartistsort": "ALBUMARTISTSORT", "albumsort": "ALBUMSORT",
}  # fmt: skip


def from_vorbis(raw: Raw, has_cover: bool = False) -> Tags:
    """Vorbis comments, keys in any case (read.py upper-cases them): A3.2's middle column. An
    album artist under "ALBUM ARTIST" (foobar2000's older form) is read too; DESCRIPTION is the
    comment when COMMENT isn't there; an Opus file's R128_TRACK_GAIN and R128_ALBUM_GAIN are its
    ReplayGain gains (`r128`). The lyrics are LYRICS's, else SYNCEDLYRICS' or UNSYNCEDLYRICS'
    (foobar2000's, Mp3tag's), a timed one first (R17.1)."""
    get = raw.get
    track, track_total = number_pair(text(get("TRACKNUMBER")))
    disc, disc_total = number_pair(text(get("DISCNUMBER")))
    year, date = year_and_date(text(get("DATE")) or text(get("YEAR")))
    fields = {k: text(get(v)) for k, v in VORBIS.items()}
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
        lyrics=lrc.chosen_tag(
            [*(get("LYRICS") or ()), *(get("SYNCEDLYRICS") or ()), *(get("UNSYNCEDLYRICS") or ())]
        ),
        latin1=(),  # read.py's to say (A3.6)
    )


V1_COMMENT = "ID3v1 Comment"  # the description Mutagen gives an ID3v1 tag's comment


def is_comment(description: str) -> bool:
    """Whether a COMM frame with this description is the song's comment (A3.2): one without a
    description, or an ID3v1 tag's. The others are other programs' own data, kept as they are
    (R4.1.1): iTunes' iTunNORM and iTunSMPB, MediaMonkey's Songs-DB_Custom1, MusicMatch's."""
    return not description or description == V1_COMMENT


ID3 = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2",
    "composer": "TCOM", "artistsort": "TSOP", "albumartistsort": "TSO2", "albumsort": "TSOA",
}  # fmt: skip


def from_id3(
    raw: Raw,
    popms: Sequence[tuple[str, int]] = (),
    comments: Sequence[tuple[str, str]] = (),
    has_cover: bool = False,
    rva2: Sequence[tuple[str, float, float]] = (),
    lyrics: str | None = None,
) -> Tags:
    """ID3v2 frames by id (TCON already as genre names: read.py takes them from Mutagen, which
    turns ID3v1's numbers, "(17)", into names, R9.3), TXXX frames as "TXXX:<description>", each
    user's POPM, COMM frames as (description, text), and RVA2 frames as `rva2_replaygain` takes
    them. The comment is the first COMM that `is_comment`: without a description (A3.2), or the
    ID3v1 tag's. ReplayGain is TXXX's, else RVA2's. `lyrics` are `id3_lyrics`'."""
    get = raw.get
    track, track_total = number_pair(text(get("TRCK")))
    disc, disc_total = number_pair(text(get("TPOS")))
    if get("TDRC"):
        year, date = year_and_date(text(get("TDRC")))
    else:
        year, date = id3v23_date(text(get("TYER")), text(get("TDAT")))
    comment = next((t for d, t in comments if is_comment(d) and t.strip()), None)

    def txxx(name: str) -> str | None:
        for key, values in raw.items():
            if key.upper() == f"TXXX:{name}".upper():
                return text(values)
        return None

    tags = Tags(
        **{k: text(get(v)) for k, v in ID3.items()},
        track=track,
        tracktotal=track_total,
        disc=disc,
        disctotal=disc_total,
        year=year,
        date=date,
        genres=genres(get("TCON") or (), numbered=True),
        comment=comment.strip() if comment else None,
        compilation=flag(text(get("TCMP"))),
        rating=popm_rating(popms),
        rg_track_gain=replaygain(txxx("REPLAYGAIN_TRACK_GAIN")),
        rg_track_peak=replaygain(txxx("REPLAYGAIN_TRACK_PEAK")),
        rg_album_gain=replaygain(txxx("REPLAYGAIN_ALBUM_GAIN")),
        rg_album_peak=replaygain(txxx("REPLAYGAIN_ALBUM_PEAK")),
        has_cover=has_cover,
        lyrics=lyrics,
        latin1=(),  # read.py's to say (A3.6)
    )
    return with_replaygain(tags, rva2_replaygain(rva2))


SYLT_MS = 2  # SYLT's time stamps in milliseconds; 1 is MPEG frames, which have no time to read


def id3_lyrics(
    uslt: Sequence[str], sylt: Sequence[tuple[int, Sequence[tuple[str, int]]]] = ()
) -> str | None:
    """An ID3 tag's lyrics (R17.1): a USLT holding timed (LRC) text, else a SYLT's lines as LRC
    text (each SYLT a (time stamp format, [(text, time)]) pair; one timed in MPEG frames passed
    by), else the first USLT that holds any."""
    texts = [t for t in (lrc.tag_text(u) for u in uslt) if t is not None]
    timed = next((t for t in texts if lrc.parse(t).timed), None)
    if timed is not None:
        return timed
    for stamp, entries in sylt:
        lines = [(ms / 1000, text) for text, ms in entries if text.strip()]
        if stamp == SYLT_MS and lines:
            return lrc.tag_text(lrc.lrc_of(lines))
    return texts[0] if texts else None


MP4 = {
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
    the freeform `----:com.apple.iTunes:<name>` atoms as text, their names in any case; the lyrics
    are ©lyr's."""
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
        **{k: text(get(v)) for k, v in MP4.items()},
        track=t[0] or None,
        tracktotal=t[1] or None,
        disc=d[0] or None,
        disctotal=d[1] or None,
        year=year,
        date=date,
        genres=genres(get("\xa9gen") or ()),
        compilation=compilation,
        rating=vorbis_rating(freeform("RATING"), freeform("FMPS_RATING")),
        rg_track_gain=replaygain(freeform("replaygain_track_gain")),
        rg_track_peak=replaygain(freeform("replaygain_track_peak")),
        rg_album_gain=replaygain(freeform("replaygain_album_gain")),
        rg_album_peak=replaygain(freeform("replaygain_album_peak")),
        has_cover=has_cover,
        lyrics=lrc.chosen_tag(get("\xa9lyr") or ()),
        latin1=(),  # read.py's to say (A3.6)
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


# ---------- the tags kept without showing (R4.1.1, R4.8) ----------

# what R4.1's fields are read from, by each kind's own key (A3.2): everything else a file holds is
# kept untouched when it is written, and listed read only for one song (R4.8)
KNOWN = {
    "id3": {*ID3.values(), "TRCK", "TPOS", "TDRC", "TYER", "TDAT", "TCON", "TCMP", "POPM", "RVA2",
            "APIC:3"},
    "vorbis": {*VORBIS.values(), "ALBUM ARTIST", "DESCRIPTION", "TRACKNUMBER", "TRACKTOTAL",
               "TOTALTRACKS", "DISCNUMBER", "DISCTOTAL", "TOTALDISCS", "DATE", "YEAR", "GENRE",
               "COMPILATION", "RATING", "FMPS_RATING", "METADATA_BLOCK_PICTURE", "COVERART",
               "R128_TRACK_GAIN", "R128_ALBUM_GAIN"},
    "mp4": {*MP4.values(), "trkn", "disk", "\xa9day", "\xa9gen", "cpil", "covr",
            "----:com.apple.itunes:rating", "----:com.apple.itunes:fmps_rating"},
}  # fmt: skip
# what the common keys of other programs are, in words
KEPT_NAMES = {
    "USLT": "Lyrics", "SYLT": "Synced lyrics", "LYRICS": "Lyrics", "UNSYNCEDLYRICS": "Lyrics",
    "\xa9lyr": "Lyrics", "TSSE": "Encoder settings", "ENCODER": "Encoder", "\xa9too": "Encoder",
    "TENC": "Encoded by", "ENCODEDBY": "Encoded by", "UFID": "File id", "PRIV": "Private data",
    "PCNT": "Play count", "TBPM": "BPM", "BPM": "BPM", "tmpo": "BPM", "pgap": "Gapless",
    "APIC": "Picture", "TCOP": "Copyright", "COPYRIGHT": "Copyright", "cprt": "Copyright",
    "TPUB": "Publisher", "TSRC": "ISRC", "ISRC": "ISRC", "TLAN": "Language", "TMED": "Media",
    "TORY": "Original year", "TDOR": "Original date",
}  # fmt: skip
KEPT_WIDTH = 80  # characters of a kept value shown, the rest elided


def _replaygain_key(key: str) -> bool:
    k = key.upper()
    return k.startswith(("REPLAYGAIN_", "TXXX:REPLAYGAIN_")) or k.startswith(
        "----:COM.APPLE.ITUNES:REPLAYGAIN_"
    )


def kept(family: str, items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """The tags of a file MusiKata keeps without showing (R4.1.1), in its order, each as a name
    and its value in words, for R4.8's read-only list. `family` is "id3", "vorbis" or "mp4";
    `items` the file's tags as read.kept gives them: (its key, its value as text), an ID3 frame
    with a description keyed "<id>:<description>" (a picture "APIC:<type>"), Vorbis keys
    upper-cased. What R4.1's fields are read from (`KNOWN`, the comment, ReplayGain) isn't
    listed."""
    known = KNOWN[family]
    out: list[tuple[str, str]] = []
    for key, value in items:
        if key in known or key.lower() in known or _replaygain_key(key):
            continue
        fid, _, desc = key.partition(":")
        if fid == "COMM" and is_comment(desc):
            continue
        if family == "mp4" and key.startswith("----:"):
            name = key.rsplit(":", 1)[-1]
        elif fid in ("TXXX", "WXXX") and desc:
            name = desc
        elif fid == "APIC":
            name = KEPT_NAMES[fid]
        elif desc and fid in KEPT_NAMES:
            name = f"{KEPT_NAMES[fid]} ({desc})"
        elif fid == "COMM":
            name = f"Comment ({desc})"
        else:
            name = KEPT_NAMES.get(key, key)
        value = " ".join(value.split())
        if len(value) > KEPT_WIDTH:
            value = value[: KEPT_WIDTH - 1].rstrip() + "…"
        out.append((name, value))
    return out
