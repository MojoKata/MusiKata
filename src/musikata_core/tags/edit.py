"""The Edit tags panel's logic (R4.2 to R4.4), as plain functions over the songs' tags: what each
field shows for a set of songs (a value they share, or "mixed" with the values in use and how many
songs have each), what the user's typing changes on which songs, and the save it makes (a
batch's jobs, R4.7). No Qt, file or index here: the panel (musikata.edittags) hands these the tags
the index holds and shows what they give.

The panel edits text, so a field's value is the text it shows: genres joined with "; ", a year as
four digits, a number and its total as "4 / 10" (Track, Disc), compilation as "Yes" or "No". What
the user typed into a field is an edit; a field not edited changes nothing. An edit of a field
whose values differ (mixed) sets the typed value on every song, and an empty one keeps each song's
own (R4.3); of a field the songs share, it sets the value, an empty one removing it. The rating
is its stars as a digit, "0" to clear it (R10.2), set by its stars, never typed. Track and
Disc go part by part: a part (the number, the total) the songs don't share keeps each song's own
unless one is typed for it, so "/ 12" sets the total of an album's songs and keeps their
numbers."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from . import parse
from .batch import Job
from .fields import Tags

# the panel's fields, in its order (L03-songs-bulk-edit), then those under More fields (R4.2)
MAIN = ("artist", "album", "genres", "year", "albumartist", "disc", "title", "track", "rating")
MORE = ("composer", "comment", "artistsort", "albumartistsort", "albumsort", "compilation")
FIELDS = (*MAIN, *MORE)
TEXT = ("title", "artist", "album", "albumartist", "composer", "comment", "artistsort",
        "albumartistsort", "albumsort")  # fmt: skip
PAIRS = {"track": ("track", "tracktotal"), "disc": ("disc", "disctotal")}  # a field of two parts
YES, NO = "Yes", "No"
STARS = tuple("012345")  # the rating's text: its stars (R10.1)
_PAIR = re.compile(r"\s*(\d+)?\s*(?:(?:/|of)\s*(\d+)?)?\s*", re.I)
_YEAR = re.compile(r"\s*\d{4}(?:[-/.]?\d{2}(?:[-/.]?\d{2})?)?\s*")


@dataclass(frozen=True)
class Field:
    """What a field shows for a set of songs: `text`, the value they share ("" when none, or
    when it is mixed); whether it is `mixed`; and the values in use, as text, each with how many
    songs have it, most first (the mixed field's ▾, R4.3; a song without one isn't listed). For
    Track and Disc, `parts_mixed` says which of the number and the total the songs don't share,
    and `text` shows the parts they do ("/ 10")."""

    name: str
    text: str
    mixed: bool
    values: tuple[tuple[str, int], ...] = ()
    parts_mixed: tuple[bool, bool] = (False, False)


def pair_text(number: int | None, total: int | None) -> str:
    """A number and its total as the field shows them: "4 / 10", "4", "/ 10", ""."""
    if total:
        return f"{number} / {total}" if number else f"/ {total}"
    return str(number) if number else ""


def text_of(name: str, tags: Tags) -> str:
    """A song's value of field `name` as the panel shows it."""
    if name in PAIRS:
        number, total = PAIRS[name]
        return pair_text(getattr(tags, number), getattr(tags, total))
    if name == "genres":
        return "; ".join(tags.genres)
    if name == "year":
        return f"{tags.year:04d}" if tags.year else ""
    if name == "compilation":
        return YES if tags.compilation else NO
    if name == "rating":
        return str(tags.rating or 0)
    value = getattr(tags, name)
    return value or ""


def field_of(name: str, songs: Sequence[Tags]) -> Field:
    """What field `name` shows for `songs`."""
    counts = Counter(text_of(name, t) for t in songs)
    values = tuple(
        sorted(((v, n) for v, n in counts.items() if v), key=lambda vn: (-vn[1], vn[0].casefold()))
    )
    if len(counts) <= 1:
        return Field(name, next(iter(counts), ""), False, values)
    if name not in PAIRS:
        return Field(name, "", True, values)
    number, total = PAIRS[name]
    parts = [{getattr(t, p) for t in songs} for p in (number, total)]
    shared = [next(iter(s)) if len(s) == 1 else None for s in parts]
    mixed = (len(parts[0]) > 1, len(parts[1]) > 1)
    return Field(name, pair_text(shared[0], shared[1]), True, values, mixed)


def fields_of(songs: Sequence[Tags]) -> dict[str, Field]:
    """Every field of the panel for `songs`, by name."""
    return {name: field_of(name, songs) for name in FIELDS}


def problem(name: str, typed: str) -> str | None:
    """Why what was typed into field `name` can't be written, in words; None when it can."""
    if not typed.strip():
        return None
    if name in PAIRS and not _PAIR.fullmatch(typed):
        return f"“{typed.strip()}” isn't a number, or a number and its total"
    if name == "year" and not (_YEAR.fullmatch(typed) and parse.year_and_date(typed)[0]):
        return f"“{typed.strip()}” isn't a year"
    if name == "compilation" and typed not in (YES, NO):
        return f"“{typed}” isn't {YES} or {NO}"
    if name == "rating" and typed.strip() not in STARS:
        return f"“{typed.strip()}” isn't 0 to 5 stars"
    return None


def _pair(typed: str) -> tuple[int | None, int | None]:
    m = _PAIR.fullmatch(typed)  # `problem` has said it matches
    number, total = (int(g) if g else 0 for g in (m.groups() if m else (None, None)))
    return number or None, total or None


def change_of(name: str, typed: str, field: Field, tags: Tags) -> dict[str, object]:
    """What an edit of field `name` (`typed`, the field as `field` showed it before) changes on
    one song whose tags are `tags`: R4.1's fields as compose.normalize takes them, only those that
    differ; nothing for an edit that can't be written (`problem`)."""
    if problem(name, typed) is not None:
        return {}
    blank = not typed.strip()
    if name in PAIRS:
        return _pair_change(name, typed, field, tags)
    if blank and field.mixed:
        return {}  # R4.3: leaving a mixed field alone keeps each song's own
    if name == "rating":
        if blank:
            return {}
        stars = int(typed.strip())
        return {name: stars} if (tags.rating or 0) != stars else {}
    if name in TEXT:
        new = parse.text([typed])
        return {name: new} if getattr(tags, name) != new else {}
    if name == "genres":
        genres = parse.genres([typed])
        return {name: list(genres)} if tags.genres != genres else {}
    if name == "year":
        if blank:
            return {"year": None} if tags.year is not None else {}
        year, date = parse.year_and_date(typed.strip())
        if year == tags.year and (date is None or date == tags.date):
            return {}
        return {"year": date or year}
    flag = typed == YES  # compilation
    return {name: flag} if tags.compilation != flag else {}


def _pair_change(name: str, typed: str, field: Field, tags: Tags) -> dict[str, object]:
    out: dict[str, object] = {}
    for part, value, mixed in zip(PAIRS[name], _pair(typed), field.parts_mixed, strict=True):
        if value is None and mixed:
            continue  # a part the songs don't share, left alone: each song's own
        if getattr(tags, part) != value:
            out[part] = value
    return out


@dataclass(frozen=True)
class Plan:
    """A save (R4.4, R4.7): a job per song that changes, and the panel's fields that change on at
    least one song, in the panel's order."""

    jobs: tuple[Job, ...]
    fields: tuple[str, ...]


def plan(
    songs: Sequence[tuple[str, Tags]], edits: Mapping[str, str], shown: Mapping[str, Field]
) -> Plan:
    """The save the edits make of `songs` (each its path and tags), with the fields as `shown`
    showed them before."""
    jobs: list[Job] = []
    changed: set[str] = set()
    for path, tags in songs:
        change: dict[str, object] = {}
        for name, typed in edits.items():
            one = change_of(name, typed, shown[name], tags)
            if one:
                changed.add(name)
                change.update(one)
        if change:
            jobs.append(Job(path, change))
    return Plan(tuple(jobs), tuple(f for f in FIELDS if f in changed))


def problems(edits: Mapping[str, str]) -> dict[str, str]:
    """The edits that can't be written, by field, each with why."""
    return {n: why for n, t in edits.items() if (why := problem(n, t)) is not None}
