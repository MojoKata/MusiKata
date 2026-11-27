"""Text in the wrong encoding (R4.10, A3.6), as plain functions over text: an ID3 frame marked
Latin-1 holds its bytes as Mutagen decodes them, one character a byte, so the text Tags holds is
those bytes exactly (`raw`). They are read under each candidate of R4.10 (`CANDIDATES`) and each
reading scored (`score`) by how much of it is letters of one script, in the pairs that script's
languages use; a song whose Latin-1 text another candidate reads far better than as it is
(`likely`) is flagged, its candidate kept in the index (`flag`) for Needs attention (A2.6).
Fix encoding… shows the readings side by side, the most likely first (`readings`), and the choice,
for a song or every song of its album, is a plan the preview shows (`plan`), saved as Unicode.

How a reading scores. Its letters are taken word by word: a word is plausible when its letters
are of one script and

- Latin: its letters beyond ASCII all belong to one language's alphabet (`LATIN`), no three of
  Latin-1's stand together, and none is a capital after a small letter: accented letters in
  runs, or in pairs no language has (`ÌàÿÊ`, `Ñåâåðíûé`), are what Cyrillic read as Latin-1
  makes, and real French, German or Icelandic doesn't;
- Cyrillic and Greek: its letters beyond the common ones belong to one language's alphabet, it
  has a vowel when it is three letters or more (but in capitals: ДДТ) and no five consonants
  together, no capital follows a small letter, Cyrillic's ь, ъ and ы follow a consonant, and
  Greek's final sigma ends it;
- Chinese and Japanese: each character on its own, one of the common ones of the encoding it was
  read with (GB2312's first level for GBK, Big5's first for Big5, JIS's first and the kana for
  Shift-JIS), and counting twice: it is two bytes.

Punctuation parts words; beyond ASCII, only at the edges of what spaces part, but for apostrophes
and Chinese's and Japanese's own. Any other character (a control character, `³`, `¶`, `‰`, a
quote between two letters) spoils the word it is in, and counts as three letters read wrong. The
score is the letters of plausible words less the rest, over them all (`Tally`): 1 when all of it
reads as some language writes, -1 when none does; text with no letters (numbers, punctuation) has
none. A reading flags the song (`likely`) when it scores READS_WELL or more, FAR_BETTER more than
as it is, on EVIDENCE letters at least (twice that when as it is has none: `“”` is Shift-JIS's
灯). Readings that score the same are told apart by the bytes they read well, then by how many of
their letters are their script's most used (`FREQUENT`), then by R4.10's order.

Nothing here reads a file or the index: read.py says which fields a file holds as Latin-1
(`Tags.latin1`), the scan keeps the flag, and musikata.encodings shows the dialog."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace

from .tags.fields import Tags
from .tags.tools import Planned, Song

# ---------- the candidates (R4.10) ----------


@dataclass(frozen=True)
class Candidate:
    """A way to read Latin-1 text: its key, its label as Fix encoding… names it (T06), and the
    codecs it reads with, the first that reads best being the one used."""

    key: str
    label: str
    codecs: tuple[str, ...]


AS_IS = "as-is"
CP1252 = "cp1252"  # what "as it is" reads with: Windows' Western, Latin-1 where it has nothing
# R4.10's, in its order: Windows' own code pages, Shift-JIS as Windows has it (cp932), Big5 as
# Windows has it (cp950)
CANDIDATES = (
    Candidate("cyrillic", "Cyrillic (Windows-1251)", ("cp1251",)),
    Candidate("japanese", "Japanese (Shift-JIS)", ("cp932",)),
    Candidate("chinese", "Chinese (GBK, Big5)", ("gbk", "cp950")),
    Candidate("greek", "Greek (Windows-1253)", ("cp1253",)),
    Candidate("central", "Central European (Windows-1250)", ("cp1250",)),
    Candidate(AS_IS, "As it is (Latin-1)", (CP1252,)),
)
BY_KEY = {c.key: c for c in CANDIDATES}
CODEC_LABELS = {"gbk": "Chinese (GBK)", "cp950": "Chinese (Big5)"}  # one of the two, read
WIDE_CODECS = ("cp932", "gbk", "cp950")  # two bytes a character, or one
FAR_BETTER = 0.5  # how much better than as it is another reading must score to flag it
READS_WELL = 0.5  # and how well it must read itself
EVIDENCE = 2  # the letters it must read well to be flagged: one (`1º` as `1є`) says nothing
# the fields checked, in the order Fix encoding… shows them (T06: artist, album, title)
FIELDS = ("artist", "album", "title", "albumartist", "composer", "comment", "artistsort",
          "albumartistsort", "albumsort")  # fmt: skip


def label_of(codec: str) -> str:
    """The label of the candidate that reads with `codec` (Chinese: naming GBK or Big5); the codec
    itself for one no candidate has."""
    if codec in CODEC_LABELS:
        return CODEC_LABELS[codec]
    return next((c.label for c in CANDIDATES if codec in c.codecs), codec)


def raw(text: str) -> bytes:
    """The bytes a Latin-1 frame holds, from its text as Mutagen decoded it (one character a
    byte). Raises UnicodeEncodeError for text that isn't Latin-1's."""
    return text.encode("latin-1")


def as_is(data: bytes) -> str:
    """Latin-1 bytes as they are: Windows' Western (cp1252), whose quotes and dashes (0x80 to
    0x9F) other programs write in a Latin-1 frame, and Latin-1 for the five bytes it has nothing
    for."""
    return "".join(
        bytes([b]).decode(CP1252, errors="strict") if b not in _CP1252_HOLES else chr(b)
        for b in data
    )


_CP1252_HOLES = frozenset((0x81, 0x8D, 0x8F, 0x90, 0x9D))


def decode(data: bytes, codec: str) -> str | None:
    """`data` read with `codec` (as it is, for CP1252); None when it can't be."""
    if codec == CP1252:
        return as_is(data)
    try:
        return data.decode(codec)
    except UnicodeDecodeError:
        return None


# ---------- scoring ----------

# the letters beyond ASCII of the languages written in Latin letters that Latin-1 and Windows-1250
# hold, each language's alphabet (small letters)
LATIN = (
    "àâæçéèêëîïôœùûüÿ",  # French
    "äöüß",  # German
    "áéíóúñü",  # Spanish
    "áâãàçéêíóôõú",  # Portuguese
    "àèéìíîòóùú",  # Italian
    "àçèéíïòóúü",  # Catalan
    "áéíóúàèëïöü",  # Dutch
    "æøåéóô",  # Danish and Norwegian
    "åäöé",  # Swedish
    "åäöšž",  # Finnish
    "áéíóúýþæöð",  # Icelandic
    "áéíóú",  # Irish
    "àèìòù",  # Scottish Gaelic
    "çë",  # Albanian
    "ąćęłńóśźż",  # Polish
    "áčďéěíňóřšťúůýž",  # Czech
    "áäčďéíĺľňóôŕšťúýž",  # Slovak
    "áéíóöőúüű",  # Hungarian
    "ăâîșțşţ",  # Romanian
    "čćđšž",  # Croatian, Bosnian, Serbian and Slovene
    "çğıöşüâîû",  # Turkish
    "äõöüšž",  # Estonian
    "āčēģīķļņšūž",  # Latvian
    "ąčęėįšųūž",  # Lithuanian
)
# Cyrillic's letters beyond those every Cyrillic language has, each language's
CYRILLIC_COMMON = frozenset("абвгдежзклмнопрстуфхцчш")
CYRILLIC = (
    "ийщъыьэюяё",  # Russian
    "ийщьюяіїєґ",  # Ukrainian
    "йыьэюяёіў",  # Belarusian
    "ийщъьюя",  # Bulgarian
    "иђјљњћџ",  # Serbian
    "иѓѕјљњќџ",  # Macedonian
)
CYRILLIC_VOWELS = frozenset("аеёиоуыэюяіїєў")
CYRILLIC_AFTER_CONSONANT = frozenset("ьъы")  # never after a vowel, nor first in a word
GREEK_VOWELS = frozenset("αεηιουωάέήίόύώϊϋΐΰ")
GREEK_RARE = frozenset("ΐΰ")  # what Windows-1253 makes of Cyrillic's а and Р, all but unused
# each script's most used letters (Russian's and Ukrainian's; Greek's, its accents aside), by
# which two readings that score the same are told apart: another script misread is made of
# letters its words seldom use (Greek's vowels read as Windows-1251 are б з й п х щ)
FREQUENT = {"cyrillic": frozenset("оеаинтсрвлі"), "greek": frozenset("αοειτσνηυρ")}
ODD = frozenset("µ§¶‰†‡‹›•¦¨¯¸")  # Latin-1's and Windows' marks that aren't text
ODD_WEIGHT = 3  # an odd character counts as three letters read wrong: no real text has one
INWORD = frozenset("’‘´")  # punctuation beyond ASCII that stands inside words: apostrophes
MIDDLE_DOT = "·"  # inside a word only as Catalan's l·l; beside a letter otherwise, a byte misread
SYMBOLS = frozenset("´°©®№™€ªº")  # symbols beside text, as punctuation is (nº 9, 1ª)


def _wide_marks() -> frozenset[str]:
    """Chinese's and Japanese's own punctuation (、。「」・ and the full width forms), which stands
    between their characters."""
    ranges = ((0x3000, 0x30FF), (0xFF00, 0xFFEF))
    return frozenset(
        chr(c)
        for lo, hi in ranges
        for c in range(lo, hi + 1)
        if unicodedata.category(chr(c))[0] in "PSZ"
    )


WIDE_MARKS = _wide_marks()


def _masks(alphabets: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for n, letters in enumerate(alphabets):
        for ch in letters:
            out[ch] = out.get(ch, 0) | 1 << n
    return out


_LATIN = _masks(LATIN)
_WESTERN = frozenset(as_is(bytes(range(0x80, 0x100))).lower())  # Windows' Western's letters
_CYRILLIC = _masks(CYRILLIC)
_ALL = (1 << 32) - 1
WIDE = ("han", "kana", "halfwidth")  # Chinese's and Japanese's: a character two bytes, or one


def script_of(ch: str) -> str:
    """A letter's script, as scoring tells them apart: latin, cyrillic, greek, han, kana,
    halfwidth (Japanese's halfwidth katakana), or other."""
    name = unicodedata.name(ch, "")
    for prefix, script in (
        ("LATIN", "latin"), ("FULLWIDTH LATIN", "latin"), ("CYRILLIC", "cyrillic"),
        ("GREEK", "greek"), ("CJK", "han"), ("HIRAGANA", "kana"), ("KATAKANA", "kana"),
        ("HALFWIDTH KATAKANA", "halfwidth"),
    ):  # fmt: skip
        if name.startswith(prefix):
            return script
    return "other"


def _kind(ch: str, at_edge: bool, beside: bool = False) -> str:
    """What a character is to scoring: "letter" (a letter or its mark), "space" (what parts
    words: spaces, digits, punctuation) or "odd" (neither: it spoils its word). Punctuation
    beyond ASCII parts words only at the edges of what spaces part (`at_edge`), but for
    apostrophes and Chinese's and Japanese's own: between two letters it is a byte misread (`‚`
    is Shift-JIS's hiragana, read as Windows' Western). A middle dot `beside` a letter is one too,
    but in Catalan's l·l."""
    if ch in ODD:
        return "odd"
    if ch == MIDDLE_DOT:
        return "odd" if beside else "space"
    cat = unicodedata.category(ch)
    if cat[0] in "LM":
        return "letter"
    if ch.isascii() or cat in ("Nd", "Zs") or ch in WIDE_MARKS:
        return "space"
    if cat[0] == "P" or ch in SYMBOLS:
        return "space" if at_edge or ch in INWORD else "odd"
    return "odd"


def _edges(text: str) -> list[bool]:
    """For each character of `text`, whether it is at an edge of what spaces part: no letter
    before it there, or none after it."""
    letter = [unicodedata.category(ch)[0] in "LM" for ch in text]
    out = [True] * len(text)
    start = 0
    for end in [*(n for n, ch in enumerate(text) if ch.isspace()), len(text)]:
        before = False
        after = [False] * (end - start + 1)
        for n in range(end - 1, start - 1, -1):
            after[n - start] = after[n - start + 1] or letter[n]
        for n in range(start, end):
            out[n] = not (before and after[n - start + 1])
            before = before or letter[n]
        start = end + 1
    return out


def _words(text: str) -> list[tuple[str, bool]]:
    """`text`'s words, each with whether it holds an odd character; a Chinese or Japanese
    character is a word of its own."""
    out: list[tuple[str, bool]] = []
    word: list[str] = []
    odd = False

    def end() -> None:
        nonlocal odd
        if word:
            out.append(("".join(word), odd))
        word.clear()
        odd = False

    for n, (ch, at_edge) in enumerate(zip(text, _edges(text), strict=True)):
        before = text[n - 1] if n else " "
        after = text[n + 1] if n + 1 < len(text) else " "
        catalan = before.lower() == "l" and after.lower() == "l"
        beside = not catalan and (before.isalpha() or after.isalpha())
        kind = _kind(ch, at_edge, beside)
        if kind == "space":
            end()
        elif kind == "letter" and script_of(ch) in WIDE:
            end()
            out.append((ch, False))
        else:
            word.append(ch)
            odd = odd or kind == "odd"
    end()
    return out


def _camel(word: str) -> bool:
    """A capital after a small letter, beyond ASCII (iPhone and McCartney are someone's)."""
    return any(
        a.islower() and b.isupper() and not (a.isascii() and b.isascii())
        for a, b in zip(word, word[1:], strict=False)
    )


def _latin(word: str) -> bool:
    beyond = [ch.lower() for ch in word if not ch.isascii() and ch.isalpha()]
    if not beyond:
        return True
    mask = _ALL
    for ch in beyond:
        mask &= _LATIN.get(ch, 0)
    run = longest = 0
    for ch in word:
        run = run + 1 if not ch.isascii() and ch.isalpha() else 0
        longest = max(longest, run)
    # a run of three is what Windows' Western letters make of another script (œèâà is њива);
    # Polish's own (żółć) aren't
    western = all(ch in _WESTERN for ch in beyond)
    return bool(mask) and (longest < 3 or not western) and not _camel(word)


def _sounds(letters: Sequence[str], vowels: frozenset[str]) -> bool:
    """Whether a word's letters sound as words do: a vowel in a word of three letters or more,
    and no five consonants together (`взгляд` and `всплеск` start with four). A word all in
    capitals may be letters said one by one (ДДТ)."""
    if len(letters) < 3:
        return True
    if all(ch.isupper() for ch in letters):
        return True
    lower = [ch.lower() for ch in letters]
    if not any(ch in vowels for ch in lower):
        return False
    run = 0
    for ch in lower:
        run = 0 if ch in vowels else run + 1
        if run >= 5:
            return False
    return True


def _cyrillic(word: str) -> bool:
    letters = [ch for ch in word if ch.isalpha()]
    lower = [ch.lower() for ch in letters]
    mask = _ALL
    for ch in lower:
        if ch not in CYRILLIC_COMMON:
            mask &= _CYRILLIC.get(ch, 0)
    # ь, ъ and ы follow a consonant: never a vowel, й or one another, and never start a word
    misplaced = any(
        ch in CYRILLIC_AFTER_CONSONANT
        and (n == 0 or lower[n - 1] in CYRILLIC_VOWELS or lower[n - 1] in "йьъ")
        for n, ch in enumerate(lower)
    )
    return bool(mask) and not misplaced and _sounds(letters, CYRILLIC_VOWELS) and not _camel(word)


def _greek(word: str) -> bool:
    letters = [ch for ch in word if ch.isalpha()]
    lower = [ch.lower() for ch in letters]
    sigma = "ς" not in lower[:-1] and not (len(lower) > 1 and lower[-1] == "σ")
    rare = any(ch in GREEK_RARE for ch in lower)
    return sigma and not rare and _sounds(letters, GREEK_VOWELS) and not _camel(word)


def _common(ch: str, codec: str) -> bool:
    """Whether a Chinese or Japanese character read with `codec` is one of the common ones of
    that encoding: its bytes in GB2312's first level (GBK), Big5's first (Big5), JIS's first or
    the kana (Shift-JIS)."""
    script = script_of(ch)
    try:
        data = ch.encode(codec)
    except UnicodeEncodeError, LookupError:
        return False
    if len(data) != 2:
        return False
    lead, trail = data
    if codec == "gbk":
        return script == "han" and 0xB0 <= lead <= 0xD7 and trail >= 0xA1
    if codec == "cp950":
        return script == "han" and 0xA4 <= lead <= 0xC6
    if codec == "cp932":
        return script == "kana" or (script == "han" and 0x88 <= lead <= 0x98)
    return False


JUDGES = {"latin": _latin, "cyrillic": _cyrillic, "greek": _greek}


@dataclass(frozen=True)
class Tally:
    """What a reading's letters come to: those in plausible words (`good`), the rest with the odd
    characters (`bad`), and of the good, those among their script's most used (`frequent`); a
    Chinese or Japanese character, two bytes, counts twice."""

    good: int = 0
    bad: int = 0
    frequent: int = 0


def _frequent(word: str, script: str) -> int:
    if script in WIDE or script == "latin":
        return sum(1 for ch in word if unicodedata.category(ch)[0] == "L")
    common = FREQUENT.get(script, frozenset())
    plain = unicodedata.normalize("NFD", word.lower().replace("ς", "σ"))
    return sum(1 for ch in plain if ch in common)


def tally(text: str, codec: str) -> Tally:
    """`text`'s letters, read with `codec`, as `score` weighs them (`Tally`)."""
    good = bad = frequent = 0
    for word, odd in _words(text):
        letters = sum(1 for ch in word if unicodedata.category(ch)[0] == "L")
        if odd:
            bad += letters + ODD_WEIGHT * sum(1 for ch in word if _kind(ch, False) == "odd")
            continue
        scripts = {script_of(ch) for ch in word if unicodedata.category(ch)[0] == "L"}
        if not scripts:
            continue
        script = scripts.pop() if len(scripts) == 1 else "mixed"
        if script in WIDE:
            letters, fine = 2, _common(word, codec)
        elif script in JUDGES:
            fine = JUDGES[script](word)
        else:
            fine = script == "other"  # a script no candidate makes: as it is
        if fine:
            good += letters
            frequent += 2 if script in WIDE else _frequent(word, script)
        else:
            bad += letters
    return Tally(good, bad, frequent)


def score(text: str, codec: str) -> float | None:
    """How well `text`, read with `codec`, reads as some language writes: from -1 (none of it)
    to 1 (all of it); None when it has no letters to judge by."""
    t = tally(text, codec)
    if not t.good + t.bad:
        return None
    return (t.good - t.bad) / (t.good + t.bad)


# ---------- the readings ----------


@dataclass(frozen=True)
class Reading:
    """A candidate's reading of a song's Latin-1 text: its candidate, the codec it read with
    (None: it can't read it), the text of each field, in the order given, its score (None: no
    letters, or it can't read it), and its letters' Tally."""

    candidate: Candidate
    codec: str | None
    texts: tuple[str, ...]
    score: float | None
    tally: Tally = Tally()

    @property
    def readable(self) -> bool:
        return self.codec is not None

    @property
    def label(self) -> str:
        """The candidate's label, naming which of its codecs read it (Chinese: GBK or Big5)."""
        if self.codec is not None and len(self.candidate.codecs) > 1:
            return CODEC_LABELS.get(self.codec, self.candidate.label)
        return self.candidate.label


JOIN = "\n"  # the fields are scored together: a song's tags were saved by one program


def read_with(values: Sequence[str], codec: str) -> tuple[str, ...] | None:
    """Each of `values` (Latin-1 text as Mutagen decoded it) read with `codec`; None when one of
    them can't be."""
    out = []
    for v in values:
        try:
            data = raw(v)
        except UnicodeEncodeError:
            return None
        text = decode(data, codec)
        if text is None:
            return None
        out.append(text)
    return tuple(out)


def reading_of(values: Sequence[str], candidate: Candidate) -> Reading:
    """`candidate`'s reading of `values`: with the one of its codecs that reads them best."""
    best: Reading | None = None
    for codec in candidate.codecs:
        texts = read_with(values, codec)
        if texts is None:
            continue
        joined = JOIN.join(texts)
        found = Reading(candidate, codec, texts, score(joined, codec), tally(joined, codec))
        if best is None or _rank(found) < _rank(best):
            best = found
    return best or Reading(candidate, None, (), None)


def _value(r: Reading) -> float:
    return -2.0 if r.score is None else r.score


def _rank(r: Reading) -> tuple[float, int, float]:
    """How readings are ranked, best first: by score; of those that score the same, the one
    that reads more of the bytes well (Chinese's and Japanese's two to a character), then the
    one whose letters are more of its script's most used."""
    t = r.tally
    return -_value(r), -t.good, -(t.frequent / t.good if t.good else 0.0)


def readings(values: Sequence[str]) -> list[Reading]:
    """Every candidate's reading of a song's Latin-1 `values`, as Fix encoding… lists them (T06):
    the most likely first, then as it is, then the others that can read them, best first, then
    those that can't, the code pages of a byte a letter first, each in R4.10's order. Of
    readings that score the same, `_rank` tells them apart, then R4.10's order."""
    found = [reading_of(values, c) for c in CANDIDATES]
    order = {c.key: n for n, c in enumerate(CANDIDATES)}
    readable = sorted(
        (r for r in found if r.readable), key=lambda r: (*_rank(r), order[r.candidate.key])
    )
    # those that can't, as T06 lists them: the code pages of a byte a letter first
    unreadable = sorted(
        (r for r in found if not r.readable),
        key=lambda r: (any(c in WIDE_CODECS for c in r.candidate.codecs), order[r.candidate.key]),
    )
    if not readable or readable[0].candidate.key == AS_IS or not _flags(readable[0], found):
        mine = next(r for r in found if r.candidate.key == AS_IS)
        readable = [mine, *(r for r in readable if r is not mine)]
    else:
        mine = next(r for r in readable if r.candidate.key == AS_IS)
        readable = [readable[0], mine, *(r for r in readable[1:] if r is not mine)]
    return readable + unreadable


def _flags(best: Reading, found: Sequence[Reading]) -> bool:
    """Whether `best` reads far better than as it is (A3.6)."""
    mine = next(r for r in found if r.candidate.key == AS_IS)
    if best.score is None or best.candidate.key == AS_IS:
        return False
    # text with no letters as it is (“” is Shift-JIS's 灯) needs twice the evidence
    needed = EVIDENCE if mine.score is not None else 2 * EVIDENCE
    return (
        best.score >= READS_WELL
        and best.tally.good >= needed
        and best.score - _value(mine) >= FAR_BETTER
    )


def likely(values: Sequence[str]) -> Reading | None:
    """The reading another candidate gives `values` when it reads them far better than as they
    are (A3.6); None when none does."""
    ranked = readings(values)
    return ranked[0] if ranked and ranked[0].candidate.key != AS_IS else None


def values_of(tags: Tags) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The fields of `tags` its file holds as Latin-1 beyond ASCII (Tags.latin1), in FIELDS'
    order, and their values."""
    names = tuple(f for f in FIELDS if f in tags.latin1 and getattr(tags, f))
    return names, tuple(str(getattr(tags, f)) for f in names)


def flag(tags: Tags) -> str | None:
    """What the index keeps of a song's text (A2.6): the codec that reads its Latin-1 text far
    better than as it is (A3.6), None when none does or it has none."""
    _names, values = values_of(tags)
    if not values:
        return None
    # as it is reading well, no other can read far better: real Latin-1 is read once (A2.2)
    mine = score(JOIN.join(as_is(raw(v)) for v in values), CP1252)
    if mine is not None and mine > 1 - FAR_BETTER:
        return None
    found = likely(values)
    return found.codec if found is not None else None


# ---------- fixing it ----------


def fixed(tags: Tags, codec: str) -> tuple[Tags, tuple[str, ...]]:
    """`tags` with each field its file holds as Latin-1 read with `codec` (CP1252: as it is),
    and those fields: each written as Unicode (R4.10), its text changed or not. A field `codec`
    can't read is left as it is, and isn't among them."""
    names, values = values_of(tags)
    new: dict[str, object] = {}
    for name, value in zip(names, values, strict=True):
        texts = read_with([value], codec)
        if texts is not None:
            new[name] = texts[0]
    return replace(tags, **new), tuple(new)  # type: ignore[arg-type]


def plan(songs: Sequence[Song], codec: str) -> Planned:
    """Fix encoding…'s change (R4.10): each song's Latin-1 text read with `codec`, and written as
    Unicode, the fields whose text stays the same too, so it no longer needs attention; the
    columns the fields any song has so, in FIELDS' order. The songs that change come first, in
    the order given, so the preview lists them (R3.7)."""
    made = [(s, *fixed(s.tags, codec)) for s in songs]
    made.sort(key=lambda m: not m[2])  # stable: the songs it writes first
    columns = tuple(f for f in FIELDS if any(f in names for _s, _t, names in made))
    return Planned(
        columns,
        tuple(s for s, _t, _n in made),
        tuple(t for _s, t, _n in made),
        tuple(names for _s, _t, names in made),
    )
