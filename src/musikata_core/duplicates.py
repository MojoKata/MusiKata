"""The same song more than once (R2.12, A2.6): exact copies, the same audio by its hash (A2.3), and
likely ones, the same artist and title once case, accents and punctuation are set aside, with
lengths within 2 seconds; the copy MusiKata proposes to keep; and what moving the others to the
trash gives it.

- **Finding them** (`found`) is two indexed queries over the index, never a pass over the files:
  the songs whose `audio_hash` another song has (the index of A2.1), and those whose `copy_key`,
  the normalised pair of artist and title (`song_key`, kept by the scan), another song has (its
  index, with the length). Only those songs are read, with their plays (R7.9, every computer's)
  and rating (R10); `group` makes them groups: songs joined by a hash or by a key with lengths
  within WITHIN seconds of the group's shortest, a song in one group at most. A group whose copies
  all share one hash is exact, any other likely.
- **The copy to keep** (`keep`): lossless over lossy, then the higher bit rate (copies of one
  audio hash count as one: their bit rates differ only by their tags), then the one whose path
  matches its tags (R3.9: `path_matches`, from the state the index keeps for it, a parameter of
  `keep`). Then the most played, the higher rated, the first by path.
- **The choice** (`initial`, `rechoose`): the copy kept, and those checked for the trash, exact
  copies of the kept one checked at first, likely ones not (R2.12).
- **The plan** (`plan`): the copies checked go, the kept one takes their plays and their highest
  rating when it is higher than its own (R2.12).

Plain functions over plain data (`song_key`, `group`, `keep`, `initial`, `rechoose`, `plan`) are
tested without an index; `found` reads one."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass

from . import rootfiles
from .patterns import MATCH

WITHIN = 2.0  # R2.12: likely copies' lengths are within 2 seconds
LOSSLESS = frozenset({"flac", "alac", "wav", "aiff"})  # R2.2's kinds that lose nothing
CHUNK = 500  # songs read at a time
_WORD = re.compile(r"[^\W_]+")  # a run of letters and digits, in any script

# why the copy kept is kept (`keep`), by the first rule it wins on
LOSSLESS_WINS = "lossless"
BITRATE_WINS = "bitrate"
PATH_WINS = "path"
PLAYS_WINS = "plays"
RATING_WINS = "rating"
FIRST = "first"  # every rule ties: the first by path


# ---------- the key likely copies share (A2.6) ----------


def plain(text: str | None) -> str:
    """`text` with case, accents and punctuation set aside: its letters and digits only, in any
    script, case folded, each letter without its marks. "Signal Fires!" and "signal-fires" are
    "signalfires"; "Beyoncé" is "beyonce"."""
    letters = "".join(
        ch for ch in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(ch)
    ).casefold()
    return "".join(_WORD.findall(letters))


def song_key(artist: str | None, title: str | None) -> str | None:
    """The normalised pair likely copies share (A2.6): the artist's and the title's `plain`
    text; None when either is empty, as a song without them can't be said to be another."""
    a, t = plain(artist), plain(title)
    return f"{a}\0{t}" if a and t else None


# ---------- copies and their groups ----------


@dataclass(frozen=True)
class Copy:
    """A song as a group of copies shows it (R2.12): its id and path under the root, its kind
    (R2.2), bit rate (bits a second), sample rate and length, its audio hash and `song_key`, its
    title, artist and album, its plays on every computer and its rating, its file's modification
    time in seconds, its album's id and cover thumbnail, and whether its tags match its path
    (R3.9's state, patterns.MATCH, FIX or BARE; None when no pattern fits it)."""

    song: int
    path: str
    kind: str | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    length: float | None = None
    hash: str | None = None
    key: str | None = None
    title: str = ""
    artist: str = ""
    album: str = ""
    plays: int = 0
    rating: int = 0
    modified: float | None = None
    album_id: int | None = None
    thumb: str | None = None
    path_state: int | None = None


@dataclass(frozen=True)
class Group:
    """Copies of one song (R2.12): the copy proposed to keep first, the rest by path; whether
    they are likely copies (not all of one audio hash), and why the first is kept (`keep`)."""

    copies: tuple[Copy, ...]
    likely: bool
    why: str = FIRST

    @property
    def kept(self) -> Copy:
        return self.copies[0]


def lossless(kind: str | None) -> bool:
    """Whether a kind of R2.2 loses nothing (FLAC, ALAC, WAV, AIFF)."""
    return kind in LOSSLESS


def path_matches(copy: Copy) -> int:
    """R3.9 as the keep rule weighs it: 1 when the copy's tags match its path under the pattern
    detected for its folder, else 0."""
    return int(copy.path_state == MATCH)


def _rates(copies: Sequence[Copy]) -> dict[int, int]:
    """Each copy's bit rate as the keep rule compares it: copies of one audio hash are one audio,
    their bit rates the highest of them (a tag's size changes a file's bit rate, not its sound)."""
    best: dict[str, int] = {}
    for c in copies:
        if c.hash is not None:
            best[c.hash] = max(best.get(c.hash, 0), c.bitrate or 0)
    return {c.song: best[c.hash] if c.hash is not None else c.bitrate or 0 for c in copies}


def keep(copies: Sequence[Copy], matches: Callable[[Copy], int] = path_matches) -> tuple[Copy, str]:
    """The copy to keep (R2.12) and why: lossless over lossy, then the higher bit rate, then the
    one whose path matches its tags (`matches`, R3.9's), then
    the most played, the higher rated, and the first by path. Why: the first of those rules it
    wins on against the next best (LOSSLESS_WINS, …, FIRST)."""
    if not copies:
        raise ValueError("no copies to keep one of")
    rates = _rates(copies)

    def rank(c: Copy) -> tuple[int, ...]:
        return (lossless(c.kind), rates[c.song], matches(c), c.plays, c.rating)

    ordered = sorted(copies, key=lambda c: (tuple(-r for r in rank(c)), c.path))
    best = ordered[0]
    if len(ordered) == 1:
        return best, FIRST
    ours, theirs = rank(best), rank(ordered[1])
    rules = (LOSSLESS_WINS, BITRATE_WINS, PATH_WINS, PLAYS_WINS, RATING_WINS)
    why = next((rule for rule, a, b in zip(rules, ours, theirs, strict=True) if a != b), FIRST)
    return best, why


def _components(copies: Sequence[Copy], within: float) -> list[list[Copy]]:
    """The copies joined by a shared hash, or a shared key with lengths within `within` seconds
    of the shortest of a run, each copy in one of them."""
    parent = list(range(len(copies)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i: int, j: int) -> None:
        parent[root(i)] = root(j)

    by_hash: dict[str, int] = {}
    by_key: dict[str, list[int]] = {}
    for i, c in enumerate(copies):
        if c.hash is not None:
            if c.hash in by_hash:
                join(i, by_hash[c.hash])
            else:
                by_hash[c.hash] = i
        if c.key is not None and c.length is not None:
            by_key.setdefault(c.key, []).append(i)
    for found in by_key.values():
        found.sort(key=lambda i: (copies[i].length or 0.0, copies[i].path))
        start = found[0]
        for i in found[1:]:
            if (copies[i].length or 0.0) - (copies[start].length or 0.0) <= within:
                join(i, start)
            else:
                start = i
    out: dict[int, list[Copy]] = {}
    for i, c in enumerate(copies):
        out.setdefault(root(i), []).append(c)
    return [g for g in out.values() if len(g) > 1]


def group(
    copies: Iterable[Copy],
    matches: Callable[[Copy], int] = path_matches,
    within: float = WITHIN,
) -> list[Group]:
    """The groups of copies among `copies` (R2.12): songs that share an audio hash, or a
    `song_key` with lengths within `within` seconds of the shortest of their run, joined however
    they are linked, so a song is in one group; each with the copy to keep first (`keep`), the rest
    by path. In the order of their kept copy's title, artist and path."""
    listed = sorted(copies, key=lambda c: c.path)
    out = []
    for found in _components(listed, within):
        kept, why = keep(found, matches)
        rest = tuple(c for c in found if c is not kept)
        hashes = {c.hash for c in found}
        out.append(Group((kept, *rest), len(hashes) > 1 or None in hashes, why))
    out.sort(key=lambda g: (g.kept.title.casefold(), g.kept.artist.casefold(), g.kept.path))
    return out


# ---------- the choice and the plan ----------


def exact(a: Copy, b: Copy) -> bool:
    """Whether two copies are exact copies: the same audio, by its hash (A2.3)."""
    return a.hash is not None and a.hash == b.hash


def initial(g: Group) -> tuple[int, frozenset[int]]:
    """The choice a group comes with (R2.12): its proposed copy kept, and the exact copies of it
    checked for the trash; likely ones come unchecked. By song id."""
    return g.kept.song, frozenset(c.song for c in g.copies[1:] if exact(c, g.kept))


def rechoose(g: Group, kept: int, checked: Collection[int], new: int) -> tuple[int, frozenset[int]]:
    """The choice once the user keeps the copy `new` instead of `kept`: `new` unchecked, and the
    copy kept until now checked when it is an exact copy of `new`, else left unchecked; the rest
    as they were. A song not of the group changes nothing."""
    by_id = {c.song: c for c in g.copies}
    if new not in by_id or kept not in by_id or new == kept:
        return kept, frozenset(checked)
    now = set(checked) - {new}
    if exact(by_id[kept], by_id[new]):
        now.add(kept)
    else:
        now.discard(kept)
    return new, frozenset(now)


@dataclass(frozen=True)
class Plan:
    """What Move the others to the trash does for a group (R2.12): the copy kept, those that go,
    the rating the kept copy takes (None: it keeps its own) and its plays once it has theirs."""

    kept: Copy
    gone: tuple[Copy, ...]
    stars: int | None
    plays: int


def plan(g: Group, kept: int, checked: Collection[int]) -> Plan:
    """The plan for a group's choice: the copies checked go (the kept one never), the kept one
    takes their plays, added to its own, and their highest rating when it is higher than its own
    (R2.12). Raises ValueError for a kept copy not of the group."""
    by_id = {c.song: c for c in g.copies}
    if kept not in by_id:
        raise ValueError(f"song {kept} isn't a copy of this group")
    keeper = by_id[kept]
    gone = tuple(c for c in g.copies if c.song in checked and c.song != kept)
    best = max((c.rating for c in gone), default=0)
    stars = best if best > keeper.rating else None
    return Plan(keeper, gone, stars, keeper.plays + sum(c.plays for c in gone))


# ---------- in the index (A2.6) ----------

COLUMNS = (
    "song.id, song.path, song.kind, song.bitrate, song.sample_rate, song.length,"
    " song.audio_hash, song.copy_key, song.title, coalesce(song.artist, song.albumartist),"
    " song.album, song.rating, song.mtime_ns, song.album_id, album.thumb, song.path_state"
)


def candidates(c: sqlite3.Connection) -> list[int]:
    """The songs another song shares an audio hash or a `copy_key` with, by id: through the
    indexes on each (A2.6), never a pass over every song's row."""
    return [
        int(i)
        for (i,) in c.execute(
            "SELECT id FROM song WHERE audio_hash IN (SELECT audio_hash FROM song"
            " WHERE audio_hash IS NOT NULL GROUP BY audio_hash HAVING COUNT(*) > 1)"
            " UNION SELECT id FROM song WHERE copy_key IN (SELECT copy_key FROM song"
            " WHERE copy_key IS NOT NULL GROUP BY copy_key HAVING COUNT(*) > 1)"
        )
    ]


def read(c: sqlite3.Connection, songs: Sequence[int]) -> list[Copy]:
    """The songs of `songs` (by id) as copies, with their plays on every computer (R7.9)."""
    out: list[Copy] = []
    for i in range(0, len(songs), CHUNK):
        chunk = list(songs[i : i + CHUNK])
        marks = ", ".join("?" * len(chunk))
        rows = c.execute(
            f"SELECT {COLUMNS} FROM song LEFT JOIN album ON album.id = song.album_id"
            f" WHERE song.id IN ({marks})",
            chunk,
        ).fetchall()
        plays = rootfiles.totals(c, chunk)
        for (song, path, kind, bitrate, rate, length, h, key, title, artist, album, rating,
             mtime, album_id, thumb, state) in rows:  # fmt: skip
            out.append(Copy(
                int(song), str(path), kind, bitrate, rate, length, h, key, title or "",
                artist or "", album or "", plays.get(song, 0), int(rating or 0),
                mtime / 1e9 if mtime is not None and mtime >= 0 else None, album_id, thumb,
                state,
            ))  # fmt: skip
    return out


def found(c: sqlite3.Connection, matches: Callable[[Copy], int] = path_matches) -> list[Group]:
    """Every group of copies the index holds (R2.12, A2.6): the `candidates` read and grouped."""
    return group(read(c, candidates(c)), matches)
