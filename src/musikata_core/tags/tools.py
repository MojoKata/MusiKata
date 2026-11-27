"""The Edit tags panel's bulk tools (R4.5), as plain functions from the songs' tags and the tool's
options to what each song would become: Number tracks (R4.5.1), Replace in field (R4.5.2), Tidy
case (R4.5.3, case.tidy_case) and Copy from… (R4.5.4). Each gives a `Planned`: every song, in
the order given, its tags as they are and as they would be, and the fields the tool fills, which
its preview shows as columns (R3.7); `jobs` makes the save of the songs chosen in the preview.
Nothing here reads or writes a file.

A song's fields are R4.1's under fields.Tags' names: Track and Track total apart, Year with the
full date it may have, Genre as a list (R9.2)."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace

from . import parse
from .batch import Job
from .case import tidy_case
from .fields import Tags

# the text fields a tool changes as text, and Genre, changed genre by genre (R9.2)
TEXT = ("title", "artist", "album", "albumartist", "composer", "comment", "artistsort",
        "albumartistsort", "albumsort")  # fmt: skip
WORDS = (*TEXT, "genres")  # what Replace in field and Tidy case work on
TIDIED = ("title", "artist", "album", "albumartist", "genres")  # Tidy case's fields at first
# what Copy from… copies: what an album's songs share, as a bonus track ripped apart needs
COPIED = ("artist", "album", "albumartist", "year", "genres", "disc", "disctotal", "tracktotal",
          "composer", "comment", "artistsort", "albumartistsort", "albumsort",
          "compilation")  # fmt: skip
COPIED_FIRST = ("album", "albumartist", "year", "genres")  # Copy from…'s fields at first


@dataclass(frozen=True)
class Song:
    """A song a tool works on: its path (as the save's job takes it) and its tags."""

    path: str
    tags: Tags


@dataclass(frozen=True)
class Planned:
    """What a tool would do: `columns`, the fields it fills, in the order its preview shows them;
    `songs` (their tags as they are) and `new` (as they would be), in the order given."""

    columns: tuple[str, ...]
    songs: tuple[Song, ...]
    new: tuple[Tags, ...]

    def changed(self, i: int) -> tuple[str, ...]:
        """The columns whose value song `i` would change."""
        old, new = self.songs[i].tags, self.new[i]
        return tuple(c for c in self.columns if value_of(c, old) != value_of(c, new))

    def jobs(self, chosen: Collection[int]) -> list[Job]:
        """The save of the songs at `chosen` (their places in `songs`) that would change: a job
        each, setting the fields that change, as safe.save takes them."""
        out = []
        for i, s in enumerate(self.songs):
            if i in chosen and (names := self.changed(i)):
                out.append(Job(s.path, changes_of(names, self.new[i])))
        return out


def value_of(name: str, tags: Tags) -> object:
    """A field's value as a tool compares it: Year with its full date."""
    if name == "year":
        return (tags.year, tags.date)
    return getattr(tags, name)


def text_of(name: str, tags: Tags) -> str:
    """A field's value as the preview shows it: Genre joined with "; ", Year as its four digits
    (or its full date), Compilation as Yes or No, a number as digits; "" for none."""
    if name == "genres":
        return "; ".join(tags.genres)
    if name == "year":
        return tags.date or (f"{tags.year:04d}" if tags.year else "")
    if name == "compilation":
        return "Yes" if tags.compilation else "No"
    value = getattr(tags, name)
    return "" if value is None else str(value)


def changes_of(names: Sequence[str], tags: Tags) -> dict[str, object]:
    """Fields `names` of `tags` as a save's changes (compose.normalize's): Year as its full date
    when it has one, Genre as a list."""
    out: dict[str, object] = {}
    for name in names:
        if name == "year":
            out[name] = tags.date or tags.year
        elif name == "genres":
            out[name] = list(tags.genres)
        else:
            out[name] = getattr(tags, name)
    return out


def _planned(
    columns: Sequence[str], songs: Sequence[Song], change: Callable[[int, Tags], Tags]
) -> Planned:
    return Planned(
        tuple(columns), tuple(songs), tuple(change(i, s.tags) for i, s in enumerate(songs))
    )


# ---------- R4.5.1 Number tracks ----------


def number_tracks(songs: Sequence[Song]) -> Planned:
    """R4.5.1: the songs numbered 1, 2, 3 … in the order given (the list's), and Track total
    set to how many there are."""
    n = len(songs)
    return _planned(("track", "tracktotal"), songs,
                    lambda i, t: replace(t, track=i + 1, tracktotal=n))  # fmt: skip


# ---------- R4.5.2 Replace in field ----------


class ReplaceError(ValueError):
    """What to find, or what to put in its place, can't be used: why, in words."""


def replacer(
    find: str, by: str, regex: bool = False, match_case: bool = False
) -> Callable[[str], str]:
    """What Replace in field does to one value: every `find` replaced by `by`, as text, or as a
    regular expression whose `by` may name its groups (`\\1`, `\\g<name>`). Raises ReplaceError
    for an expression, or a `by`, that isn't valid, saying why."""
    if not find:
        raise ReplaceError("Type what to find")
    flags = 0 if match_case else re.IGNORECASE
    try:
        pattern = re.compile(find if regex else re.escape(find), flags)
    except re.error as e:
        raise ReplaceError(f"The regular expression isn't valid: {e.msg} (at {e.pos})") from e
    if not regex:
        return lambda value: pattern.sub(lambda _m: by, value)
    try:
        pattern.sub(by, "")  # Python reads the replacement before it looks for a match
    except (re.error, IndexError) as e:
        why = e.msg if isinstance(e, re.error) else str(e.args[0] if e.args else e)
        raise ReplaceError(f"The replacement isn't valid: {why}") from e
    return lambda value: pattern.sub(by, value)


def replace_in_field(
    songs: Sequence[Song], name: str, find: str, by: str, regex: bool = False,
    match_case: bool = False,
) -> Planned:  # fmt: skip
    """R4.5.2: `find` replaced by `by` in field `name` (a text field, or Genre) of each song.
    Genre is replaced genre by genre, so `^` and `$` hold each one; a genre replaced by nothing is
    removed, and one replaced by text with ";" becomes several (R9.2). A text field replaced by
    nothing is removed. Raises ReplaceError as `replacer` does, ValueError for a field it doesn't
    work on."""
    if name not in WORDS:
        raise ValueError(f"Replace in field doesn't work on {name!r}")
    sub = replacer(find, by, regex, match_case)
    return _planned((name,), songs, lambda _i, t: _words(t, name, sub))


def _words(tags: Tags, name: str, change: Callable[[str], str]) -> Tags:
    """`tags` with each word field value of `name` changed by `change`; a value that comes out
    the same is kept as it was, untouched by tidying of spaces."""
    if name == "genres":
        genres = [change(g) for g in tags.genres]
        if genres == list(tags.genres):
            return tags
        return replace(tags, genres=parse.genres(genres))
    value = getattr(tags, name)
    if value is None:
        return tags
    changed = change(value)
    if changed == value:
        return tags
    new: dict[str, object] = {name: parse.text([changed])}
    return replace(tags, **new)  # type: ignore[arg-type]  # `name` is one of TEXT: text or None


# ---------- R4.5.3 Tidy case ----------


def tidy(songs: Sequence[Song], names: Sequence[str]) -> Planned:
    """R4.5.3: R3.6.1's Tidy case (case.tidy_case) on fields `names` of each song, Genre genre by
    genre. Raises ValueError for a field it doesn't work on."""
    for name in names:
        if name not in WORDS:
            raise ValueError(f"Tidy case doesn't work on {name!r}")

    def change(_i: int, tags: Tags) -> Tags:
        for name in names:
            tags = _words(tags, name, tidy_case)
        return tags

    return _planned([n for n in WORDS if n in names], songs, change)


# ---------- R4.5.4 Copy from… ----------


def copy_from(songs: Sequence[Song], source: int, names: Sequence[str]) -> Planned:
    """R4.5.4: fields `names` copied from song `source` (its place in `songs`) to the others, as
    for a bonus track ripped apart from its album; Year with its full date. The source is listed,
    unchanged. Raises ValueError for a field it doesn't copy or a source that isn't one."""
    for name in names:
        if name not in COPIED:
            raise ValueError(f"Copy from… doesn't copy {name!r}")
    if not 0 <= source < len(songs):
        raise ValueError(f"no song {source} of {len(songs)} to copy from")
    columns = [n for n in COPIED if n in names]
    parts = [("year", "date") if n == "year" else (n,) for n in columns]
    model = songs[source].tags
    values = {p: getattr(model, p) for ps in parts for p in ps}
    return _planned(columns, songs, lambda _i, t: replace(t, **values))
