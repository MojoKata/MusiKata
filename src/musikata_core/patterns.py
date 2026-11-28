"""Path patterns (R3, A3.3): reading tags from a file's path under the root.

- **The pattern language** (R3.2): a path with `/` between folders on every platform and tokens in
  braces (TOKENS, and `{*}`, which fills nothing). `parse` reads any text, never failing: a pattern
  that can't be used says why (`Pattern.problem`) and fits nothing.
- **The engine** (A3.3): a pattern compiled into a regular expression, anchored at both ends, each
  token a lazy group (digits for `{track}` and `{disc}`, four for `{year}`), its text escaped with
  R3.2.1's equivalences (a run of spaces matches any run, ` - `, ` – ` and `_-_` match one
  another). It is matched against as many of the path's last parts as the pattern has, the
  extension removed, so a preset fits an album however deep its folder lies under the root (the
  folders above it are the path's, not the pattern's). A token can't take a `/`.
- **Presets and detection** (R3.3, R3.4): PRESETS in R3.3's order, the user's own tried before
  them; `detect` counts the files each fits, the most first, a tie going to more tokens.
- **Filling and correcting** (R3.5, R3.6): `infer` gives a song's tags as the path would make
  them: only the empty tags filled, or the path winning wherever it gives a value, with Tidy case
  (case.tidy_case), Year from folder (`folder_year`) and Underscores as spaces; `plan` makes the
  preview's planned change (tags.tools.Planned) of many songs, Track total among it.
- **Tags match path** (R3.9): `states` says, for a folder's songs, whether each one's tags agree
  with its path under the pattern detected for the folder, as Infer from path's defaults would
  read it: MATCH, FIX (and how: `Difference`), or BARE (no tags at all); None when no pattern fits
  it. It judges less than Infer from path writes (`judged`): an album, album artist or artist the
  path shortens agrees (`shortens`: the tag starts with it, or is it with a part in brackets), and
  a folder that groups albums (`grouping`: two or more album folders beneath it, none of whose
  songs carries its name as album artist or artist) gives no album artist or artist.
- **The layout** (R12.1, R12.1.1, A3.3): the same language run the other way, a path made from a
  song's tags for Organize files. `parse(text, naming=True)` takes R12.1's naming forms too
  (`{track:02}`, `{disc-}`, the sort names) and refuses `{*}`, which names nothing; `values_for`
  gives a song's value for every token, `render` the path under the root, each part cleaned
  (`clean_part`) so a layout gives the same path on every platform.

A value the path gives keeps the tag's own spelling where the path couldn't spell it otherwise: a
tag that holds what a file's name can't (`\\ / : * ? " < > |`) and is the path's text once those
and underscores are spaces ("AC/DC" against `AC_DC`, "What?" against `What`), or one already in
mixed case that differs from the value only in case (R3.6.1: "McCartney" against `MCCARTNEY`), is
kept. A tag spelled as the path spells it, all in lower case, is tidied as the path's value is
(L05-folders-large: "ebb & flow" is Title case differs).

Plain functions over strings and tags.Tags: no file, index or Qt."""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from collections import Counter
from collections.abc import Container, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from . import sortnames
from .tags import parse as tag_parse
from .tags.case import has_mixed_case, tidy_case
from .tags.fields import Tags
from .tags.tools import Planned, Song, text_of

# R3.2's tokens, by name, and the field of tags.Tags each fills
TOKENS = {
    "artist": "artist",
    "albumartist": "albumartist",
    "album": "album",
    "year": "year",
    "disc": "disc",
    "track": "track",
    "title": "title",
    "genre": "genres",
}
SKIP = "*"  # {*}: matches anything, fills nothing
TEXT_FIELDS = ("artist", "albumartist", "album", "title")
# the order of the preview's columns (T01-infer-from-path): what the pattern fills, then Year
# (from the folder) and Track total, in R4.1's order but Track before Title
COLUMNS = ("artist", "albumartist", "album", "disc", "track", "tracktotal", "title", "year",
           "genres")  # fmt: skip
PRESETS = (
    "{albumartist}/{year} - {album}/{track} - {title}",
    "{albumartist}/{album} ({year})/{track} - {title}",
    "{albumartist}/{album}/{disc}-{track} - {title}",
    "{albumartist}/{album}/{track} - {artist} - {title}",
    "{albumartist}/{album}/{track} - {title}",
    "{albumartist}/{album}/{track} {title}",
    "{artist} - {title}",
)  # R3.3, in its order
DOESNT_FIT = "Doesn't fit the pattern"  # R3.4
# R3.9's states, worst last
MATCH, FIX, BARE = 0, 1, 2
# R3.9: the fields a path's shorter name of the tag agrees with, and the tokens a folder that
# groups albums doesn't give
SHORTENED = ("album", "albumartist", "artist")
ARTIST_TOKENS = ("albumartist", "artist")
_BRACKETED = re.compile(r"[(\[][^()\[\]]*[)\]]")
_ENDS = " ,;:-–—"  # what a shorter name drops at its end ("Glass Harbor:" is "Glass Harbor")
_TOKEN = re.compile(r"\{([^{}]*)\}")
# R12.1's naming forms, which only a layout (parse's `naming`) takes: a number padded with zeros
# ({track:02}), the disc and "-" when the album has more than one ({disc-}), the sort names
SORT_TOKENS = {"artistsort": "artist", "albumartistsort": "albumartist", "albumsort": "album"}
DISC_DASH = "disc-"
_PADDED = re.compile(r"(track|disc):0([1-9])")
# R3.2.1: a run of spaces, and the three separators that match one another
_SEPARATOR = r"(?: +[-–] +|_-_)"
_LITERAL = re.compile(r"( +[-–] +|_-_| +)")
_UNSPELLABLE = re.compile(r'[\\/:*?"<>|_]')  # what a file's name can't hold, and underscores
_DISC_FOLDER = re.compile(r"(?:disc|disk|cd)\s*\d+(?:\s.*)?", re.I)
# R3.6.2: a year at the start of a folder's name, in brackets, or at its end after a mark
_FOLDER_YEARS = (
    re.compile(r"^(\d{4})(?=\s*(?:[-–_.]|\s)\s*\S)"),
    re.compile(r"[(\[](\d{4})[)\]]"),
    re.compile(r"(?<=[\s\-–_,])(\d{4})$"),
)
_YEAR_RANGE = range(1000, 3000)


# ---------- the pattern (R3.2) ----------


@dataclass(frozen=True)
class Pattern:
    """A pattern as written (`text`), its parts in order (("text", literal) or ("token", name),
    `{*}` as the token "*"), and why it can't be used ("" when it can: it then has `regex`)."""

    text: str
    parts: tuple[tuple[str, str], ...]
    problem: str = ""
    regex: re.Pattern[str] | None = None

    @property
    def tokens(self) -> tuple[str, ...]:
        """The tokens that fill a field, in order, each once."""
        out: list[str] = []
        for kind, value in self.parts:
            if kind == "token" and value in TOKENS and value not in out:
                out.append(value)
        return tuple(out)

    @property
    def depth(self) -> int:
        """How many of a path's parts it describes: its folders and the file's name."""
        return 1 + sum(value.count("/") for kind, value in self.parts if kind == "text")

    @property
    def fields(self) -> tuple[str, ...]:
        """The fields of tags.Tags it fills, in its tokens' order."""
        return tuple(TOKENS[t] for t in self.tokens)

    def place(self, token: str) -> int | None:
        """Which of its parts (0: the first folder it describes; depth - 1: the file's name) the
        first `token` of that name is in; None when it has none."""
        at = 0
        for kind, value in self.parts:
            if kind == "text":
                at += value.count("/")
            elif value == token:
                return at
        return None


def _naming_form(name: str) -> bool:
    """Whether `name` (a token's, lower case) is one of R12.1's naming forms."""
    return name in SORT_TOKENS or name == DISC_DASH or _PADDED.fullmatch(name) is not None


def parse(text: str, naming: bool = False) -> Pattern:
    """`text` as a pattern (R3.2); never fails: a pattern that can't be used says why in its
    `problem` (no text, a brace not closed, a token R3.2 hasn't, no token that fills a field).
    With `naming`, it is a layout (R12.1): R12.1's naming forms are tokens too, `{*}` is refused,
    and it has no regular expression, as it only makes paths (`render`)."""
    stripped = text.strip().strip("/")
    parts: list[tuple[str, str]] = []
    at = 0
    problem = "" if stripped else "Type a pattern, such as {artist} - {title}"
    for m in _TOKEN.finditer(stripped):
        if m.start() > at:
            parts.append(("text", stripped[at : m.start()]))
        name = m.group(1).strip().lower()
        if not problem and naming and name == SKIP:
            problem = "{*} names nothing: a layout can't use it"
        elif (
            not problem
            and name != SKIP
            and name not in TOKENS
            and not (naming and _naming_form(name))
        ):
            problem = f"{{{m.group(1)}}} isn't a token"
        parts.append(("token", name))
        at = m.end()
    if at < len(stripped):
        parts.append(("text", stripped[at:]))
    if not problem and any("{" in v or "}" in v for k, v in parts if k == "text"):
        problem = "A brace isn't closed"
    pattern = Pattern(text, tuple(parts), problem)
    named = pattern.tokens or (naming and any(k == "token" for k, _ in parts))
    if not problem and not named:
        problem = "Put at least one token in it, such as {title}"
    if problem or naming:
        return Pattern(text, tuple(parts), problem)
    return replace(pattern, regex=re.compile(_compiled(pattern.parts)))


def _compiled(parts: Sequence[tuple[str, str]]) -> str:
    """The regular expression of a pattern's parts (A3.3), anchored at both ends."""
    out = ["^"]
    for n, (kind, value) in enumerate(parts):
        if kind == "text":
            for piece in _LITERAL.split(value):
                if not piece:
                    continue
                if piece.strip(" ") in ("-", "–") and piece.startswith(" ") or piece == "_-_":
                    out.append(_SEPARATOR)
                elif not piece.strip(" "):
                    out.append(" +")
                else:  # an underscore matches a space, as the path's underscores read (R3.6.3)
                    out.append(re.escape(piece).replace("_", "[_ ]"))
        elif value == SKIP:
            out.append("[^/]*?")
        elif value == "year":
            out.append(rf"(?P<g{n}>\d{{4}})")
        elif value in ("track", "disc"):
            out.append(rf"(?P<g{n}>\d+?)")
        else:
            out.append(rf"(?P<g{n}>[^/]+?)")
    out.append("$")
    return "".join(out)


def path_parts(path: str, underscores: bool = False) -> list[str]:
    """A path under the root as a pattern reads it: its parts, `/` or `\\` between them, the
    file's name without its extension, composed (NFC, as macOS names files decomposed); with
    `underscores`, each `_` a space (R3.6.3)."""
    text = unicodedata.normalize("NFC", path.replace("\\", "/"))
    parts = [p for p in text.split("/") if p]
    if parts:
        stem, dot, ext = parts[-1].rpartition(".")
        if dot and stem and ext and " " not in ext and len(ext) <= 5:
            parts[-1] = stem
    if underscores:
        parts = [p.replace("_", " ") for p in parts]
    return parts


def match(pattern: Pattern, path: str, underscores: bool = False) -> dict[str, str] | None:
    """What each token of `pattern` reads in `path` (a path under the root), as text, the first
    of a token named twice; None when the pattern doesn't fit it."""
    if pattern.regex is None:
        return None
    parts = path_parts(path, underscores)
    if len(parts) < pattern.depth:
        return None
    m = pattern.regex.fullmatch("/".join(parts[len(parts) - pattern.depth :]))
    if m is None:
        return None
    out: dict[str, str] = {}
    for n, (kind, value) in enumerate(pattern.parts):
        if kind == "token" and value != SKIP and value not in out:
            out[value] = m.group(f"g{n}")
    return out


def values_of(found: Mapping[str, str]) -> dict[str, object]:
    """A match's text as tags.Tags' fields: text with its spaces made single and trimmed (none
    when nothing is left), track and disc as numbers without their leading zeros (none for 0), the
    year as a number, the genre as one genre."""
    out: dict[str, object] = {}
    for token, text in found.items():
        field = TOKENS[token]
        value = " ".join(text.split())
        if not value:
            continue
        if token in ("track", "disc"):
            if int(value):
                out[field] = int(value)
        elif token == "year":
            out[field] = int(value)
        elif token == "genre":
            out[field] = tag_parse.genres([value])
        else:
            out[field] = value
    return out


def read(pattern: Pattern, path: str, underscores: bool = True) -> dict[str, object] | None:
    """The fields `path` gives under `pattern` (`match`, then `values_of`); None when it
    doesn't fit."""
    found = match(pattern, path, underscores)
    return None if found is None else values_of(found)


def folder_year(path: str) -> int | None:
    """R3.6.2: the year the album's folder names, as `2019 - Glass Harbor`, `Glass Harbor (2019)`
    or `Glass Harbor [2019]`: the folder holding the file, or the one above it when that is a disc's
    (`Disc 1`, `CD2`); None when it names none."""
    parts = path_parts(path)[:-1]
    if parts and _DISC_FOLDER.fullmatch(parts[-1]) and len(parts) > 1:
        parts = parts[:-1]
    if not parts:
        return None
    name = parts[-1].strip()
    for found in _FOLDER_YEARS:
        m = found.search(name)
        if m and int(m.group(1)) in _YEAR_RANGE:
            return int(m.group(1))
    return None


# ---------- presets and detection (R3.3, R3.4) ----------


def patterns_of(user: Iterable[str] = ()) -> list[Pattern]:
    """Every pattern detection tries, in order: the user's own (Settings, R13.4) that can be used,
    each once, then PRESETS."""
    out: list[Pattern] = []
    seen: set[str] = set()
    for text in [*user, *PRESETS]:
        p = parse(text)
        key = p.text.strip().strip("/")
        if p.regex is not None and key not in seen:
            seen.add(key)
            out.append(p)
    return out


@dataclass(frozen=True)
class Fit:
    """A pattern and how many of the files it fits."""

    pattern: Pattern
    fits: int


def detect(
    patterns: Sequence[Pattern], paths: Sequence[str], underscores: bool = True
) -> list[Fit]:
    """R3.4: each pattern with the number of `paths` it fits, the one that fits the most first; a
    tie goes to the more specific (more tokens), then to the one tried first."""
    fits = [Fit(p, sum(match(p, path, underscores) is not None for path in paths))
            for p in patterns]  # fmt: skip
    order = sorted(range(len(fits)), key=lambda i: (-fits[i].fits,
                                                    -len(fits[i].pattern.tokens), i))  # fmt: skip
    return [fits[i] for i in order]


def detected(fits: Sequence[Fit]) -> Pattern | None:
    """The pattern detection chooses: the first of `fits` when it fits a file; None when none
    does."""
    return fits[0].pattern if fits and fits[0].fits else None


# ---------- filling and correcting (R3.5, R3.6) ----------


@dataclass(frozen=True)
class Options:
    """R3.5's mode (`fill_only`: Only fill empty tags; else Correct tags that differ, the
    default) and R3.6's tidying, each as its checkbox starts."""

    fill_only: bool = False
    tidy_case: bool = True
    year_from_folder: bool = True
    underscores: bool = True
    track_total: bool = False


DEFAULTS = Options()


def spelled(text: str) -> str:
    """`text` as a file's name could spell it: composed, the marks a name can't hold and
    underscores as spaces, its spaces single and trimmed, and no dots at its end (Windows drops
    them)."""
    plain = _UNSPELLABLE.sub(" ", unicodedata.normalize("NFC", text))
    return " ".join(plain.split()).rstrip(". ")


def _kept(old: str, raw: str, new: str) -> bool:
    """Whether a tag `old` stands as it is against the path's `raw` text, tidied as `new`: the
    same once spelled as a file's name could; spelled with what a name can't hold; or in mixed
    case, the same but for case."""
    if spelled(old) == spelled(new):
        return True
    if unicodedata.normalize("NFC", old) != raw and spelled(old) == spelled(raw):
        return True
    return has_mixed_case(old) and spelled(old).casefold() == spelled(new).casefold()


def _text(old: str | None, raw: str, options: Options) -> str | None:
    """A text field's new value, or None to keep it."""
    new = tidy_case(raw) if options.tidy_case else raw
    if not old:
        return new
    if options.fill_only or _kept(old, raw, new):
        return None
    return new


def given(pattern: Pattern, path: str, options: Options = DEFAULTS) -> dict[str, object] | None:
    """What `path` gives under `pattern`, Year from the folder among it when the pattern has no
    `{year}` (R3.6.2); None when the pattern doesn't fit it."""
    values = read(pattern, path, options.underscores)
    if values is None:
        return None
    if options.year_from_folder and "year" not in values:
        year = folder_year(path)
        if year is not None:
            values["year"] = year
    return values


def infer(tags: Tags, values: Mapping[str, object], options: Options = DEFAULTS) -> Tags:
    """A song's tags with the fields `values` gives (`given`) filled or corrected as `options`
    say (R3.5, R3.6): text Tidy cased; Year set without its full date; Genre one genre, kept when
    the song has it among its own."""
    new: dict[str, object] = {}
    for field, value in values.items():
        old = getattr(tags, field)
        if field in TEXT_FIELDS:
            text = _text(old, str(value), options)
            if text is not None and text != old:
                new[field] = text
        elif field == "genres":
            raw = value[0] if isinstance(value, tuple) and value else ""
            if not raw:
                continue
            genre = tidy_case(raw) if options.tidy_case else raw
            if not old or not (options.fill_only or any(_kept(g, raw, genre) for g in old)):
                new[field] = (genre,)
        elif old is None or (not options.fill_only and old != value):
            new[field] = value
            if field == "year":
                new["date"] = None
    return replace(tags, **new) if new else tags  # type: ignore[arg-type]  # fields of Tags


def _folder(path: str) -> str:
    return path.replace("\\", "/").rpartition("/")[0]


def track_totals(
    songs: Sequence[tuple[str, Tags]], counts: Mapping[str, int] | None = None
) -> dict[int, int]:
    """R3.6.4: for each song (its path under the root and tags, as they would be) of a folder
    whose every track is there, the count, by its place in `songs`: every file the folder holds
    (`counts`, by folder; else those given) among `songs`, and those of each disc numbered 1 to
    n."""
    groups: dict[tuple[str, int | None], list[int]] = {}
    for i, (path, tags) in enumerate(songs):
        groups.setdefault((_folder(path), tags.disc), []).append(i)
    given_ = Counter(_folder(p) for p, _ in songs)
    out: dict[int, int] = {}
    for (folder, _disc), places in groups.items():
        if (counts or {}).get(folder, given_[folder]) != given_[folder]:
            continue  # some of the folder's files aren't among them
        if sorted(songs[i][1].track or 0 for i in places) == list(range(1, len(places) + 1)):
            out.update(dict.fromkeys(places, len(places)))
    return out


def plan(
    songs: Sequence[Song],
    paths: Sequence[str],
    pattern: Pattern,
    options: Options = DEFAULTS,
    counts: Mapping[str, int] | None = None,
) -> Planned:
    """Infer from path's change (R3.5 to R3.7) of `songs` (each its file as a save takes it, and
    its tags), whose paths under the root are `paths`: those the pattern fits first, in the order
    given, each with the tags its path gives; then those it doesn't, unchanged, noted as such
    (R3.4). The columns are the fields the pattern fills, Year when the folder gives one, and
    Track total when asked for; `counts`, each folder's files, says when a folder's every track
    is there (R3.6.4)."""
    fitting: list[tuple[int, dict[str, object]]] = []
    rest: list[int] = []
    for i, path in enumerate(paths[: len(songs)]):
        values = given(pattern, path, options)
        if values is None:
            rest.append(i)
        else:
            fitting.append((i, values))
    new = {i: infer(songs[i].tags, values, options) for i, values in fitting}
    names = set(pattern.fields) | {f for _, values in fitting for f in values}
    if options.track_total and "track" in names:
        names.add("tracktotal")
        totals = track_totals([(paths[i], new[i]) for i, _ in fitting], counts)
        for n, total in totals.items():
            i = fitting[n][0]
            had = new[i].tracktotal
            if had is None or (not options.fill_only and had != total):
                new[i] = replace(new[i], tracktotal=total)
    order = [i for i, _ in fitting] + rest
    return Planned(
        tuple(c for c in COLUMNS if c in names),
        tuple(songs[i] for i in order),
        tuple(new.get(i, songs[i].tags) for i in order),
        notes=tuple("" if i in new else DOESNT_FIT for i in order),
    )


# ---------- tags match path (R3.9) ----------


@dataclass(frozen=True)
class Difference:
    """How a song's tag differs from its path (R3.9): the field, how ("missing", "case": only in
    case, "differs"), and the path's value as the preview shows it; and the tag's own (`old`, ""
    for none, or unknown), which says how but not whether they differ, so is left out of `==`."""

    field: str
    how: str
    value: str
    old: str = dataclasses.field(default="", compare=False)


def has_tags(tags: Tags) -> bool:
    """Whether a song holds any of the tags a path can give (R3.9's red: none)."""
    return any(getattr(tags, f) for f in (*TEXT_FIELDS, "track", "disc", "year", "genres"))


def differences(old: Tags, new: Tags) -> tuple[Difference, ...]:
    """The fields `new` (as the path makes them) changes of `old`, in COLUMNS' order."""
    out = []
    for field in COLUMNS:
        before, after = text_of(field, old), text_of(field, new)
        if field == "year" and old.year == new.year:
            continue
        if before == after:
            continue
        how = "missing" if not before else "case" if before.casefold() == after.casefold() else (
            "differs")  # fmt: skip
        out.append(Difference(field, how, after, before))
    return tuple(out)


State = tuple[int | None, tuple[Difference, ...]]


def short_forms(tag: str) -> list[str]:
    """The shorter names a tag goes by (R3.9): each start of it that ends before a space, without
    the marks it ends with ("Night Ferry" of "Night Ferry (Original Soundtrack)", "Glass Harbor"
    of "Glass Harbor: Remixed"), and the tag with its parts in brackets taken out ("Glass Harbor
    Live" of "Glass Harbor (Deluxe) Live"), with that one's starts."""
    out: list[str] = []
    bare = " ".join(_BRACKETED.sub(" ", tag).split())
    for text in dict.fromkeys((tag, bare)):
        if text != tag and text:
            out.append(text)
        for i in range(1, len(text)):
            if text[i].isspace() and not text[i - 1].isspace():
                start = text[:i].rstrip(_ENDS)
                if start:
                    out.append(start)
    return list(dict.fromkeys(out))


def shortens(tag: str, raw: str) -> bool:
    """Whether the path's `raw` text, tidied as Infer from path's defaults tidy it, is a shorter
    name of `tag` (`short_forms`), compared as the rest of R3.9 compares (spaces, the marks a
    file's name can't hold, and case when the tag already has mixed case)."""
    new = tidy_case(raw)
    return any(_kept(form, raw, new) for form in short_forms(tag))


def carries(tag: str, name: str) -> bool:
    """Whether a song's album artist or artist `tag` carries a folder's `name` (R3.9's grouping
    folder), case aside: the same once spelled as a file's name could, or a shorter name of it."""
    want = spelled(name).casefold()
    return bool(want) and any(spelled(form).casefold() == want for form in (tag, *short_forms(tag)))


def grouping(name: str, albums: int, names: Iterable[str | None]) -> bool:
    """R3.9: whether a folder named `name` groups albums rather than naming their artist: it holds
    two or more album folders (`albums`, the folders beneath it holding songs of their own) and
    none of the songs beneath it carries its name as album artist or artist (`names`, theirs)."""
    return albums >= 2 and not any(n and carries(n, name) for n in names)


def token_folder(pattern: Pattern, path: str, token: str) -> str | None:
    """The folder (its path under the root, with `/`) that `token` of `pattern` reads in `path`;
    None when the token is in the file's name, or the pattern has none."""
    place = pattern.place(token)
    if place is None or place >= pattern.depth - 1:
        return None
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return "/".join(parts[: len(parts) - pattern.depth + place + 1])


def judged(
    pattern: Pattern,
    path: str,
    tags: Tags,
    values: Mapping[str, object],
    groups: Container[str] = frozenset(),
) -> dict[str, object]:
    """The values (`given`'s) R3.9 judges a song's `tags` by: all but the album artist or artist
    read from a folder of `groups` (those that group albums, `grouping`), and an album, album
    artist or artist the path's text shortens (`shortens`)."""
    out = dict(values)
    for token in ARTIST_TOKENS:
        if TOKENS[token] in out and token_folder(pattern, path, token) in groups:
            del out[TOKENS[token]]
    for field in SHORTENED:
        old, raw = getattr(tags, field), out.get(field)
        if old and isinstance(raw, str) and shortens(old, raw):
            del out[field]
    return out


def states(
    songs: Sequence[tuple[str, Tags]],
    patterns: Sequence[Pattern],
    groups: Container[str] = frozenset(),
) -> list[State]:
    """R3.9 for a folder's songs (each its path under the root and tags), in their order: under
    the pattern detected for them (`detect`, as Infer from path reads it by default), and judged
    as `judged` says (`groups`: the folders that group albums), MATCH and no differences, or FIX
    and how the tags differ; BARE for a song with no tags at all (and how, when a pattern fits
    it); (None, ()) when no pattern fits a song that has tags."""
    chosen = detected(detect(patterns, [p for p, _ in songs])) if songs else None
    out: list[State] = []
    for path, tags in songs:
        values = given(chosen, path) if chosen is not None else None
        if chosen is not None and values is not None:
            values = judged(chosen, path, tags, values, groups)
        diffs = differences(tags, infer(tags, values)) if values is not None else ()
        if not has_tags(tags):
            out.append((BARE, diffs))
        elif values is None:
            out.append((None, ()))
        else:
            out.append((FIX if diffs else MATCH, diffs))
    return out


# ---------- the layout: paths made from tags (R12.1, R12.1.1) ----------

LAYOUT = "{albumartist}/{year} - {album}/{disc-}{track:02} - {title}"  # R12.1's default
UNKNOWN_ARTIST = "Unknown artist"  # a song naming no artist or album artist
UNKNOWN_ALBUM = "Unknown album"  # a song naming no album
VARIOUS = "Various Artists"  # a compilation naming no album artist (R2.5.3, albums.VARIOUS)
PART_MAX = 120  # R12.1.1: each part of a path, in characters
BYTES_MAX = 255  # and in UTF-8 bytes, the most Linux's and macOS's file systems take in a name
# R12.1.1: what a file system refuses in a name, on some platform: Windows' marks, and control
# characters
_REFUSED = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f]')
# the names Windows keeps for its devices, whatever follows them after a dot ("CON.flac")
RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{d}{n}" for d in ("COM", "LPT") for n in [*"123456789", "¹", "²", "³"]}
)


def _cut(text: str, chars: int, size: int) -> str:
    """`text` cut to at most `chars` characters and `size` bytes of UTF-8, whole characters."""
    text = text[:chars]
    while len(text.encode("utf-8")) > size:
        text = text[:-1]
    return text


def clean_part(text: str, ext: str = "") -> str:
    """One part of a path (a folder's name, or a file's without its extension `ext`) as every
    platform takes it (R12.1.1): composed (NFC, as macOS may hand names decomposed), what a file
    system refuses (`/ \\ : * ? " < > |` and control characters) replaced with `_`, trimmed of
    spaces and dots at its ends, cut to PART_MAX characters and BYTES_MAX bytes with `ext`, and a
    name Windows keeps for a device (CON, NUL, COM1, …) given a `_` after it ("CON_"). "" when
    nothing is left."""
    plain = _REFUSED.sub("_", unicodedata.normalize("NFC", text)).strip(" .")
    plain = _cut(plain, PART_MAX - len(ext), BYTES_MAX - len(ext.encode("utf-8"))).rstrip(" .")
    head, dot, rest = plain.partition(".")
    if head.rstrip(" ").upper() in RESERVED:
        plain = _cut(f"{head.rstrip(' ')}_{head[len(head.rstrip(' ')) :]}{dot}{rest}",
                     PART_MAX - len(ext), BYTES_MAX - len(ext.encode("utf-8")))  # fmt: skip
    return plain


def values_for(
    tags: Tags, discs: int = 1, articles: Sequence[str] = sortnames.ARTICLES
) -> dict[str, str]:
    """A song's value for each token a layout can hold (R12.1), "" where it has none: the album
    artist, else "Various Artists" for a compilation naming none, else the artist, else "Unknown
    artist" (and the artist likewise); the album, else "Unknown album"; the title as tagged (the
    caller's file name stands in for none); numbers as written, `{track:02}` padded, `{disc-}`
    the disc and "-" only when the album has more than one (`discs`); the first genre; the sort
    names as tagged (the album artist's the artist's when it is the artist's name, as albums.place
    sorts it), else the name with its leading article moved to its end (R2.13)."""
    artist = (tags.artist or "").strip()
    albumartist = (tags.albumartist or "").strip()
    if not albumartist:
        albumartist = VARIOUS if tags.compilation else artist or UNKNOWN_ARTIST
    artist = artist or albumartist
    album = (tags.album or "").strip() or UNKNOWN_ALBUM
    out = {
        "artist": artist,
        "albumartist": albumartist,
        "album": album,
        "title": (tags.title or "").strip(),
        "year": str(tags.year) if tags.year else "",
        "track": str(tags.track) if tags.track else "",
        "disc": str(tags.disc) if tags.disc else "",
        "genre": tags.genres[0].strip() if tags.genres else "",
        DISC_DASH: f"{tags.disc}-" if tags.disc and max(discs, tags.disctotal or 0) > 1 else "",
        "artistsort": (tags.artistsort or "").strip() or sortnames.article_last(artist, articles),
        "albumartistsort": (tags.albumartistsort or "").strip()
        or ("" if (tags.albumartist or "").strip() else (tags.artistsort or "").strip())
        or sortnames.article_last(albumartist, articles),
        "albumsort": (tags.albumsort or "").strip() or sortnames.article_last(album, articles),
    }
    for field in ("track", "disc"):
        number = getattr(tags, field)
        for width in range(1, 10):
            out[f"{field}:0{width}"] = f"{number:0{width}d}" if number else ""
    return out


def _filled(items: list[tuple[str, str]]) -> str:
    """A part's text and its tokens' values: a token with no value left out with the text that
    joins it to the next token (or, for the last, to the one before), so "{year} - {album}" with
    no year is the album alone."""
    items = list(items)
    while True:
        empty = next((i for i, (k, v) in enumerate(items) if k == "token" and not v), None)
        if empty is None:
            return "".join(v for _, v in items)
        later = any(k == "token" for k, _ in items[empty + 1 :])
        earlier = any(k == "token" for k, _ in items[:empty])
        if later and empty + 1 < len(items) and items[empty + 1][0] == "text":
            del items[empty : empty + 2]
        elif earlier and not later and items[empty - 1][0] == "text":
            del items[empty - 1 : empty + 1]
        else:
            del items[empty]


def render(layout: Pattern, values: Mapping[str, str], name: str, ext: str) -> str:
    """The path under the root, with `/`, that `layout` (parse's, `naming`) makes of a song's
    `values` (`values_for`), its file's extension `ext` (".flac") after it: each part filled
    (a token with no value left out with what joins it; no title is the file's own `name`,
    without its extension), then cleaned (`clean_part`); a folder that comes out empty is left
    out, and a file's name that does is the file's own."""
    values = {**values, "title": values.get("title") or name}
    parts: list[list[tuple[str, str]]] = [[]]
    for kind, value in layout.parts:
        if kind == "token":
            parts[-1].append(("token", values.get(value, "")))
            continue
        pieces = value.split("/")
        parts[-1].append(("text", pieces[0]))
        for piece in pieces[1:]:
            parts.append([("text", piece)])
    folders = [clean_part(_filled(p)) for p in parts[:-1]]
    file = clean_part(_filled(parts[-1]), ext) or clean_part(name, ext) or "_"
    return "/".join([*(f for f in folders if f), file + ext])
