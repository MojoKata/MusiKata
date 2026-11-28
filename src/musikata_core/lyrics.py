"""Lyrics (R17, A7.6): LRC read in every shape it is written in, the lyrics a song shows chosen from
where they come from, and what saving them writes. Plain logic over text and bytes; the only files
it touches are a song's `.lrc` beside it (`find_lrc`, `read_lrc`). It sits below `tags`, which
reads and writes the lyrics a song's tags hold through it (tags.parse, tags.compose), so it imports
nothing of MusiKata's.

- **Where they come from** (R17.1), in this order: an `.lrc` beside the song with its name (`04 -
  Signal Fires.lrc`, its extension in any case), then the song's tags (ID3 `SYLT` or `USLT`,
  Vorbis `LYRICS`, MP4 `©lyr`: tags.read gives them as `Tags.lyrics`). Lyrics in LRC form inside a
  plain tag count as timed. An `.lrc` or a tag holding nothing but blanks and LRC's own tags is
  none (`choose`).
- **LRC** (`parse`): `[mm:ss]`, `[mm:ss.xx]`, `[mm:ss.xxx]` and `[mm:ss:xx]` times, several on one
  line (the line sung at each); `[offset:±ms]` (a positive offset shows the lines sooner);
  LRC's own tags (`[ar:]`, `[ti:]`, `[al:]`, `[by:]`, `[length:]`, …) kept as `meta` and never
  shown; enhanced LRC's word times (`<mm:ss.xx>`) read and taken out of the line, its text shown
  whole: the lines are followed, not the words; lines out of order sorted by their times; a line
  with no time in timed lyrics (a credit, a heading) left out; a time with no text a pause
  between verses; blank lines, CRLF and CR, a BOM. Lyrics whose lines are all "Instrumental" (in
  brackets, stars or music notes) or music notes alone are `instrumental`.
- **The bytes of an `.lrc`** (`decode`): a BOM of UTF-8, UTF-16 or UTF-32; UTF-16 without one (a
  NUL beside every other byte); UTF-8; else the system's legacy encoding (cp1252 where the system
  is UTF-8 itself), as an `.m3u`'s are read (R8.1.2).
- **Saving** (`saving`, R17.4, R17.5): where R13.11's setting says (`lrc`, the default; `tags`;
  `both`), and always into an `.lrc` the lyrics were read from, which would otherwise hide what was
  saved; text left empty removes the lyrics from where they are. An `.lrc` is written as UTF-8
  with LF line ends (A7.6)."""

from __future__ import annotations

import bisect
import codecs
import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

log = logging.getLogger(__name__)

LRC = ".lrc"  # a song's lyrics beside it, named as it is (R17.1)
SAVE = ("lrc", "tags", "both")  # R13.11's setting: where saved lyrics go, `lrc` the default
FILE = "file"  # a Found's source: the `.lrc` beside the song
TAGS = "tags"  # or the song's tags

# a time tag: minutes (any number of digits), seconds, and hundredths or thousandths after . or :
_TIME = re.compile(r"\[\s*(\d{1,4})\s*:\s*(\d{1,2})(?:\s*[.:,]\s*(\d{1,3}))?\s*\]")
_WORD = re.compile(r"<\s*\d{1,4}\s*:\s*\d{1,2}(?:\s*[.:,]\s*\d{1,3})?\s*>")  # enhanced LRC's
_TAG = re.compile(r"\[\s*([A-Za-z#][A-Za-z]*)\s*:([^\]]*)\]")
# LRC's own tags: the only bracketed words read as tags, so a plain heading ("[Verse 1: Ana]") stays
META = frozenset({"ar", "al", "ti", "au", "by", "length", "offset", "re", "ve", "tool", "la",
                  "lang", "id", "hash", "sign", "qq", "total", "kana", "#"})  # fmt: skip
_MARKS = "[](){}<>*~-_.!♪♫♬♩🎵🎶 \t"  # what an instrumental mark is set in


@dataclass(frozen=True)
class Line:
    """A line of lyrics: its text, and the seconds into the song it is sung at (None: plain
    lyrics, which have no times). A timed line with no text is a pause between verses."""

    text: str
    time: float | None = None


@dataclass(frozen=True)
class Lyrics:
    """Lyrics as read (`parse`): their lines (timed ones in the order of their times), whether
    they are timed, whether they mark the song instrumental, and LRC's own tags, by name in lower
    case, as written."""

    lines: tuple[Line, ...] = ()
    timed: bool = False
    instrumental: bool = False
    meta: tuple[tuple[str, str], ...] = ()

    @property
    def empty(self) -> bool:
        """Whether they hold no line with text: no lyrics at all."""
        return not any(line.text for line in self.lines)

    def times(self) -> list[float]:
        """The times of timed lyrics' lines, in order; none for plain ones."""
        return [line.time for line in self.lines if line.time is not None]


def _seconds(minutes: str, seconds: str, fraction: str | None) -> float:
    frac = int(fraction) / 10 ** len(fraction) if fraction else 0.0
    return int(minutes) * 60 + int(seconds) + frac


def _offset(value: str) -> float | None:
    """`[offset:]`'s milliseconds as seconds; None when it isn't a whole number."""
    found = re.fullmatch(r"\s*([+-]?)\s*(\d{1,9})\s*", value)
    if found is None:
        return None
    ms = int(found.group(2))
    return (-ms if found.group(1) == "-" else ms) / 1000


def _words_out(text: str) -> str:
    """A line's text with enhanced LRC's word times taken out, its spaces made single."""
    return " ".join(_WORD.sub(" ", text).split())


def is_mark(text: str) -> bool:
    """Whether a line of lyrics only says the song is instrumental: "Instrumental",
    "[Instrumental]", "♪ instrumental ♪", or music notes alone."""
    bare = text.strip(_MARKS).lower()
    if bare == "instrumental":
        return True
    return bool(text.strip()) and not text.strip(_MARKS) and any(c in text for c in "♪♫♬♩🎵🎶")


def parse(text: str) -> Lyrics:
    """The lyrics in `text`, LRC or plain, in any shape listed in this module's docstring. Never
    raises: text that holds no lyrics gives empty Lyrics."""
    timed: list[tuple[float, int, str]] = []  # time, place, text
    plain: list[str] = []
    meta: list[tuple[str, str]] = []
    offset = 0.0
    for n, raw in enumerate(re.split(r"\r\n|\r|\n", text.removeprefix("﻿"))):
        rest = raw.strip()
        times: list[float] = []
        tags: list[tuple[str, str]] = []
        while rest.startswith("["):
            found = _TIME.match(rest)
            if found is not None:
                times.append(_seconds(*found.groups()))
                rest = rest[found.end() :].lstrip()
                continue
            tag = _TAG.match(rest)
            if tag is None or times or tag.group(1).lower() not in META:
                break
            tags.append((tag.group(1).lower(), tag.group(2).strip()))
            rest = rest[tag.end() :].lstrip()
        if times:
            words = _words_out(rest)
            timed += [(t, n, words) for t in times]
            continue
        if tags and not rest:
            for key, value in tags:
                meta.append((key, value))
                if key == "offset":
                    shift = _offset(value)
                    if shift is not None:
                        offset = shift
            continue
        plain.append(raw.rstrip())
    if timed:
        timed.sort(key=lambda t: (t[0], t[1]))
        lines = tuple(Line(words, max(0.0, round(t - offset, 3))) for t, _n, words in timed)
    else:
        lines = tuple(Line(t) for t in _paragraphs(plain))
    texts = [line.text for line in lines if line.text]
    instrumental = bool(texts) and all(is_mark(t) for t in texts)
    return Lyrics(lines, bool(timed), instrumental, tuple(meta))


def _paragraphs(lines: Sequence[str]) -> list[str]:
    """Plain lines with the blank ones at either end taken off and each run of blank ones made
    one, the gap between verses."""
    out: list[str] = []
    for line in lines:
        if line.strip():
            out.append(line)
        elif out and out[-1]:
            out.append("")
    while out and not out[-1]:
        out.pop()
    return out


def current(times: Sequence[float], position: float) -> int:
    """The line sung at `position` seconds, by its place among timed lyrics' `times` (in order):
    the last one started; -1 before the first."""
    return bisect.bisect_right(times, position) - 1


def time_tag(seconds: float) -> str:
    """A time as LRC writes it: [01:45.20], to the hundredth."""
    hundredths = max(0, round(seconds * 100))
    minutes, rest = divmod(hundredths, 6000)
    return f"[{minutes:02d}:{rest // 100:02d}.{rest % 100:02d}]"


def lrc_of(entries: Sequence[tuple[float, str]]) -> str:
    """Timed lines, each (seconds, text), as LRC text: a line each, its time first, in order of
    their times (how ID3's `SYLT` is shown and edited)."""
    ordered = sorted(entries, key=lambda e: e[0])
    return "\n".join(f"{time_tag(t)}{' '.join(text.split())}" for t, text in ordered)


def sylt_of(text: str | None) -> list[tuple[str, int]] | None:
    """The lines of LRC text as ID3's `SYLT` holds them, each (text, milliseconds); None for plain
    lyrics or none."""
    if not text:
        return None
    found = parse(text)
    if not found.timed:
        return None
    return [(line.text, round((line.time or 0.0) * 1000)) for line in found.lines]


def tag_text(value: object) -> str | None:
    """Lyrics as a tag holds them and a save writes them: line ends made LF, NULs taken out, the
    blanks at either end taken off; None for none (not text, or nothing but blanks)."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\r\n|\r", "\n", value).replace("\x00", "").strip()
    return text or None


def chosen_tag(values: Sequence[str]) -> str | None:
    """The lyrics of a song's tags, given each lyrics tag's text in the order the kind prefers
    them: the first that is timed, else the first that holds any (R17.1: LRC in a plain tag counts
    as timed)."""
    texts = [t for t in (tag_text(v) for v in values) if t is not None]
    return next((t for t in texts if parse(t).timed), texts[0] if texts else None)


# ---------- an .lrc's bytes ----------


def decode(data: bytes, legacy: str = "cp1252") -> str:
    """An `.lrc`'s text from its bytes: by its BOM (UTF-8, UTF-16, UTF-32), as UTF-16 when a NUL
    stands beside every other byte, as UTF-8, else in `legacy` (the system's, as R8.1.2 reads an
    `.m3u`), Latin-1 for what that can't read. Never raises."""
    for bom, codec in ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
                       (codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"),
                       (codecs.BOM_UTF16_BE, "utf-16")):  # fmt: skip
        if data.startswith(bom):
            return data.decode(codec, "replace")
    head = data[:200]
    if len(head) >= 4 and head.count(0) * 3 >= len(head):
        evens, odds = head[0::2].count(0), head[1::2].count(0)
        return data.decode("utf-16-be" if evens > odds else "utf-16-le", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode(legacy)
    except UnicodeDecodeError, LookupError:
        return data.decode("latin-1")


def lrc_bytes(text: str) -> bytes:
    """Lyrics as an `.lrc` is written (A7.6): UTF-8 without a BOM, LF line ends, ending with one."""
    return ((tag_text(text) or "") + "\n").encode("utf-8")


# ---------- where they come from (R17.1) ----------


def lrc_path(song: str) -> str:
    """The `.lrc` a song's lyrics are saved as, beside it with its name: `04 - Signal Fires.lrc`."""
    return os.path.splitext(song)[0] + LRC


def find_lrc(song: str) -> str | None:
    """The `.lrc` beside the song at `song` with its name, its extension in any case (`.LRC`);
    None when there is none, or the folder can't be listed (logged)."""
    exact = lrc_path(song)
    if os.path.isfile(exact):
        return exact
    folder, name = os.path.split(song)
    stem = os.path.splitext(name)[0]
    try:
        names = os.listdir(folder or ".")
    except OSError as e:
        log.warning("couldn't list %s for the lyrics of %s: %s", folder, name, e)
        return None
    for other in sorted(names):
        base, ext = os.path.splitext(other)
        if base == stem and ext.lower() == LRC and os.path.isfile(os.path.join(folder, other)):
            return os.path.join(folder, other)
    return None


def read_lrc(path: str) -> bytes | None:
    """An `.lrc`'s bytes; None when it can't be read (logged)."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        log.warning("couldn't read the lyrics in %s: %s", path, e)
        return None


@dataclass(frozen=True)
class Found:
    """The lyrics a song shows: as read, their text (as Edit… opens it, line ends LF), where they
    come from (FILE or TAGS), and the `.lrc`'s path when from one."""

    lyrics: Lyrics
    text: str
    source: str
    path: str | None = None

    @property
    def name(self) -> str:
        """The `.lrc`'s file name; "" from tags."""
        return os.path.basename(self.path) if self.path else ""


def choose(lrc: tuple[str, bytes] | None, tag: str | None, legacy: str = "cp1252") -> Found | None:
    """The lyrics a song shows (R17.1): those of its `.lrc` (path, bytes), else those its tags
    hold (`tag`, tags.read's Tags.lyrics); None when neither holds any."""
    if lrc is not None:
        path, data = lrc
        text = tag_text(decode(data, legacy))
        if text is not None:
            found = parse(text)
            if not found.empty:
                return Found(found, text, FILE, path)
    text = tag_text(tag)
    if text is not None:
        found = parse(text)
        if not found.empty:
            return Found(found, text, TAGS)
    return None


def source_text(found: Found) -> str:
    """Where the lyrics shown come from (N04): Timed · from 04 - Signal Fires.lrc; Plain · from
    the song's tags."""
    kind = "Timed" if found.lyrics.timed else "Plain"
    where = found.name if found.source == FILE else "the song's tags"
    return f"{kind} · from {where}"


# ---------- saving (R17.4, R17.5) ----------


@dataclass(frozen=True)
class Saving:
    """What saving lyrics writes: the `.lrc` (`file`: its bytes, `data`, or moved to the trash
    when None) and the song's tags (`tags`: its lyrics, `text`, or removed when None)."""

    file: bool
    tags: bool
    data: bytes | None
    text: str | None


def saving(setting: str, text: str, had_file: bool, had_tags: bool) -> Saving:
    """What saving `text` as a song's lyrics writes, R13.11's `setting` saying where (SAVE), the
    song having an `.lrc` (`had_file`) or lyrics in its tags (`had_tags`): the places the setting
    names, and the `.lrc` it has, which would hide lyrics saved in its tags alone; text left empty
    removes the lyrics from where they are."""
    words = tag_text(text)
    if words is None:
        return Saving(had_file, had_tags, None, None)
    file = setting in ("lrc", "both") or had_file or setting not in SAVE
    tags = setting in ("tags", "both")
    return Saving(file, tags, lrc_bytes(words), words)
