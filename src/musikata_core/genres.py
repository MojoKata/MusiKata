"""Genres (R9): what the Genres view's tiles say, the genres that look like one, and renaming and
merging a genre in every song that has it.

- **Several genres per song** (R9.2) are read and written by `tags` (`parse.genres`), and kept in
  the index's `song_genre`, a row per genre (A2.1); a song counts towards each of its genres.
- **A tile** (R9.1) is a genre's name, how many songs and albums have it, and three of its covers,
  those of the albums with the most of its songs (`tiles`, from the rows `read_tiles` reads).
- **Near duplicates** (R9.5) are names whose `key` is the same: case, accents, spacing and
  punctuation set aside, "&" and a lone "n" ("Rock 'n' Roll") read as "and", and a number of
  ID3's list ("(13)", "13") as the genre it numbers (R9.3). Names the user has said are the same
  (the root's `tags.same_genres`, R13.3) join them, whatever their spelling: "Electronica" is a
  genre of its own to many, so it joins "Electronic" only when the user says so (`near_duplicates`).
- **Renaming and merging** (R9.4) are plain plans (`merge`, `rename`), a tools.Planned the
  preview of R3.7 shows and the batch saves, as the Edit tags panel's bulk tools are.
- **The genre list** (R9.6): the names suggested while typing are the library's and a short
  built-in list (`BUILT_IN`), which the root's `tags.genres` replaces once set (R13.3).

Nothing here reads or writes a file; `read_tiles`, `counts`, `songs_of` and `files_of` read the
index."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from .tags import parse
from .tags.fields import Tags
from .tags.tools import Planned, Song

# R9.6's built-in list: the broad genres of ID3's numbered list (ID3v1's 0 to 79 and Winamp's
# extensions to it, as Mutagen's TCON.GENRES holds them, parse.numbered_genre), so a name typed
# from it is one that players everywhere know
BUILT_IN = (
    "Alternative", "Ambient", "Blues", "Classical", "Country", "Dance", "Electronic", "Folk",
    "Funk", "Gospel", "Hard Rock", "Hip-Hop", "House", "Indie", "Indie Rock", "Jazz", "Latin",
    "Metal", "New Age", "Pop", "Punk", "R&B", "Rap", "Reggae", "Rock", "Soul", "Soundtrack",
    "Techno", "Trance", "World Music",
)  # fmt: skip
COVERS = 3  # the covers a tile shows (G01-genres)
SORTS = ("songs", "name")  # R9.1: by number of songs, or by name
_WORD = re.compile(r"[^\W_]+")  # a run of letters and digits, in any script


# ---------- names ----------


def key(name: str) -> str:
    """What two names that differ only in case, accents, spacing or punctuation share (R9.5):
    letters and digits only, in lower case without accents, "&" and a lone "n" read as "and", a
    numbered ID3 genre as its name. "Hip-Hop", "Hip Hop" and "hiphop" are "hiphop"; "Drum & Bass"
    and "Drum 'n' Bass" are "drumandbass". A name of marks alone is its own key, its case aside."""
    named = parse.numbered_genre(name)
    plain = "".join(
        ch for ch in unicodedata.normalize("NFKD", named) if not unicodedata.combining(ch)
    ).casefold()
    words = ["and" if w == "n" else w for w in _WORD.findall(plain.replace("&", " and "))]
    return "".join(words) or named.strip().casefold()


class GenreNameError(ValueError):
    """A genre's new name that can't be written, and why, in words."""


def checked(name: str) -> str:
    """A genre's new name as it is written: without the spaces around it. Raises GenreNameError
    for none, or one holding ";" or a NUL, which part one genre from the next (R9.2)."""
    name = name.strip()
    if not name:
        raise GenreNameError("Type the genre's new name")
    if ";" in name or "\x00" in name:
        raise GenreNameError("A genre's name can't hold ;, which parts one genre from the next")
    return name


# ---------- near duplicates (R9.5) ----------


@dataclass(frozen=True)
class Group:
    """Genres that look like one: their names, the most used first (the one a merge keeps,
    R9.5), and how many songs have each."""

    names: tuple[str, ...]
    counts: tuple[int, ...]

    @property
    def chosen(self) -> str:
        return self.names[0]

    @property
    def others(self) -> tuple[str, ...]:
        return self.names[1:]


def _order(counts: Mapping[str, int]) -> list[str]:
    """Names, the most used first; of those used as often, by name, a capital first."""
    return sorted(counts, key=lambda n: (-counts[n], n.casefold(), n))


def near_duplicates(counts: Mapping[str, int], same: Iterable[Iterable[str]] = ()) -> list[Group]:
    """The genres of the library (`counts`: each name and how many songs have it) that look like
    one (R9.5): those of one `key`, and those the user has said are the same (`same`, groups of
    names, R13.3), joined with any name of the same key as theirs. Each group has two names or
    more; the groups with the most songs come first."""
    parent: dict[str, str] = {}

    def find(k: str) -> str:
        while parent.get(k, k) != k:
            k = parent[k]
        return k

    for names in same:
        keys = [key(n) for n in names if n.strip()]
        for k in keys[1:]:
            a, b = find(keys[0]), find(k)
            if a != b:
                parent[b] = a
    found: dict[str, dict[str, int]] = {}
    for name, n in counts.items():
        found.setdefault(find(key(name)), {})[name] = n
    groups = []
    for members in found.values():
        if len(members) > 1:
            names = _order(members)
            groups.append(Group(tuple(names), tuple(members[n] for n in names)))
    return sorted(groups, key=lambda g: (-sum(g.counts), g.chosen.casefold(), g.chosen))


# ---------- renaming and merging (R9.4) ----------


def _merged(tags: Tags, gone: Collection[str], into: str) -> Tags:
    if not any(g in gone for g in tags.genres):
        return tags
    folded = into.casefold()
    # a genre that is the new name in another case takes the new name too: one spelling (R9.5)
    new = parse.genres(into if g in gone or g.casefold() == folded else g for g in tags.genres)
    return tags if new == tags.genres else replace(tags, genres=new)


def merge(songs: Sequence[Song], names: Collection[str], into: str) -> Planned:
    """R9.4's Merge into…: in each song, every genre of `names` becomes `into`, in its place,
    each genre kept once. The songs that change come first, then the rest, each in the order
    given, so the preview lists the files that change and counts the others (R3.7). Raises
    GenreNameError for an `into` that can't be written (`checked`)."""
    into = checked(into)
    gone = set(names)
    pairs = [(s, _merged(s.tags, gone, into)) for s in songs]
    pairs.sort(key=lambda p: p[1] is p[0].tags)  # stable: the changed first, in their order
    return Planned(("genres",), tuple(s for s, _ in pairs), tuple(t for _, t in pairs))


def rename(songs: Sequence[Song], old: str, new: str) -> Planned:
    """R9.4's Rename…: genre `old` called `new` in each song; a new name another genre has
    already merges them. Raises GenreNameError as `merge` does."""
    return merge(songs, (old,), new)


# ---------- the tiles (R9.1) ----------


@dataclass(frozen=True)
class Tile:
    """A genre's tile: its name, how many songs and albums have it, and up to COVERS covers (by
    their thumbnails' names), those of the albums with the most of its songs first."""

    name: str
    songs: int
    albums: int
    covers: tuple[str, ...] = ()


def tiles(
    counts: Iterable[tuple[str, int, int]],
    covers: Iterable[tuple[str, str, int]] = (),
    sort: str = "songs",
) -> list[Tile]:
    """The tiles of genres from `counts` (each name, its songs and its albums) and `covers` (each
    genre, a cover of an album with its songs, and how many of them), by number of songs, the most
    first, or by name (R9.1); of genres with as many songs, by name. Raises ValueError for another
    order."""
    if sort not in SORTS:
        raise ValueError(f"no such order of genres: {sort}")
    shown: dict[str, list[tuple[int, int, str]]] = {}
    for n, (genre, thumb, songs) in enumerate(covers):
        shown.setdefault(genre, []).append((-songs, n, thumb))
    out = []
    for name, songs, albums in counts:
        best = [thumb for _, _, thumb in sorted(shown.get(name, []))]
        out.append(Tile(name, songs, albums, tuple(dict.fromkeys(best))[:COVERS]))
    if sort == "name":
        return sorted(out, key=lambda t: (t.name.casefold(), t.name))
    return sorted(out, key=lambda t: (-t.songs, t.name.casefold(), t.name))


def read_tiles(
    c: sqlite3.Connection, sort: str = "songs", songs: str = "", params: Sequence[object] = ()
) -> tuple[list[Tile], int]:
    """The tiles (`tiles`) of the index's genres, or of those of the songs a condition on `song`
    picks (a search's, R2.7), and how many genres there are in all."""
    within = (
        f" HAVING genre IN (SELECT genre FROM song_genre JOIN song ON song.id = song_id"
        f" WHERE {songs})"
        if songs
        else ""
    )
    counts = c.execute(
        "SELECT genre, COUNT(*), COUNT(DISTINCT song.album_id) FROM song_genre"
        f" JOIN song ON song.id = song_id GROUP BY genre{within}",
        tuple(params),
    ).fetchall()
    covers = c.execute(
        "SELECT song_genre.genre, album.thumb, COUNT(*) FROM song_genre"
        " JOIN song ON song.id = song_id JOIN album ON album.id = song.album_id"
        " WHERE album.thumb IS NOT NULL GROUP BY song_genre.genre, album.id ORDER BY album.id"
    ).fetchall()
    total = c.execute("SELECT COUNT(DISTINCT genre) FROM song_genre").fetchone()[0]
    return tiles(counts, covers, sort), int(total)


# ---------- the songs of genres ----------


def counts(c: sqlite3.Connection) -> dict[str, int]:
    """Each genre of the index and how many songs have it."""
    return {
        str(g): int(n)
        for g, n in c.execute("SELECT genre, COUNT(*) FROM song_genre GROUP BY genre")
    }


def _within(names: Collection[str]) -> tuple[str, tuple[str, ...]]:
    values = tuple(names)
    return f"genre IN ({', '.join('?' * len(values))})", values


def songs_of(c: sqlite3.Connection, names: Collection[str]) -> list[int]:
    """The songs with any of the genres `names`, by id, in the order of their paths."""
    if not names:
        return []
    where, values = _within(names)
    return [
        int(i)
        for (i,) in c.execute(
            f"SELECT id FROM song WHERE id IN (SELECT song_id FROM song_genre WHERE {where})"
            " ORDER BY path",
            values,
        )
    ]


def files_of(c: sqlite3.Connection, names: Collection[str]) -> int:
    """How many songs have any of the genres `names`: the files merging them away rewrites."""
    if not names:
        return 0
    where, values = _within(names)
    return int(
        c.execute(
            f"SELECT COUNT(DISTINCT song_id) FROM song_genre WHERE {where}", values
        ).fetchone()[0]
    )
