"""Search (R2.7, A2.5): what the user types into the header's search box, turned into an FTS5 query
over the index's `song_fts` and filters on the song table's columns, and the index kept current.

- Words match title, artist, album, album artist, genre, year and file name, case and accents
  aside (FTS5's `unicode61` with `remove_diacritics 2`): "beyonce" finds "Beyoncé". Every word must
  match; the last one matches as a prefix while the user is still typing it (no space after it).
- `artist:`, `album:`, `genre:` and `year:` narrow a word, or a quoted phrase, to that field
  (`artist:` reads the album artist too: R2.5.4's artist is anyone named as either). `year:` and
  `rating:` take a comparison: `rating:>=4`, `year:<2000`, `rating:0` (not rated, R10.1).
- `"two words"` is a phrase. FTS5's own syntax (`AND`, `OR`, `NOT`, `NEAR`, `*`, `^`, `-`, `:`,
  brackets) is read as text, an unknown `field:` as the words it holds, and what has no letter or
  digit in it (a lone `-`) as nothing, so no input makes a query that fails.

`parse` and `match` are plain functions, tested on what users type (docs/process/testing.md,
"Shapes"); `condition` is the SQL a list adds to its WHERE; `index_songs` and `forget` keep
`song_fts` in step with `song`, in the scan's transactions (A2.2). `suggestions` gives the values
already in the library the Edit tags panel suggests as the user types (R4.6), ranked by `rank`."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# song_fts's columns (A2.1, R2.7); the row's rowid is the song's id
COLUMNS = ("title", "artist", "album", "albumartist", "genre", "year", "filename")
# what each field narrows a word to: song_fts's columns
TEXT_FIELDS = {
    "artist": ("artist", "albumartist"),
    "album": ("album",),
    "genre": ("genre",),
    "year": ("year",),
}
# what a comparison reads: the song table's columns (a song not rated is 0, R10.1)
NUMBER_FIELDS = {"year": "song.year", "rating": "coalesce(song.rating, 0)"}
FIELDS = set(TEXT_FIELDS) | set(NUMBER_FIELDS)
OPERATORS = {">=": ">=", "=>": ">=", "≥": ">=", "<=": "<=", "=<": "<=", "≤": "<=", ">": ">",
             "<": "<", "=": "=", "==": "="}  # fmt: skip
_COMPARISON = re.compile(r"^(>=|=>|≥|<=|=<|≤|==|>|<|=)?\s*([0-9]+(?:[.,][0-9]+)?)$")
_OPERATOR_ONLY = re.compile(r"^(>=|=>|≥|<=|=<|≤|==|>|<|=)$")
_FIELD = re.compile(r"([A-Za-z]+):")


@dataclass(frozen=True)
class Term:
    """A word or phrase every song shown must have: in `columns` of song_fts (all when empty),
    and as a prefix when `prefix`."""

    text: str
    columns: tuple[str, ...] = ()
    prefix: bool = False


@dataclass(frozen=True)
class Compare:
    """A field compared with a number: `rating:>=4` is Compare("rating", ">=", 4)."""

    field: str
    op: str
    value: float


@dataclass(frozen=True)
class Query:
    """What a search asks for: its terms and comparisons, all of which a song must meet."""

    terms: tuple[Term, ...] = ()
    compares: tuple[Compare, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.terms or self.compares)


def _words(text: str) -> list[tuple[str | None, str, bool, bool]]:
    """What was typed, as (field or None, value, quoted, closed): a value runs to the next space,
    or, opened by a quote, to the next quote or the end. `field` is a known field's name, lower
    case; an unknown one stays in the value ("foo:bar")."""
    out: list[tuple[str | None, str, bool, bool]] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        field = None
        m = _FIELD.match(text, i)
        if m and m.group(1).lower() in FIELDS:
            field, i = m.group(1).lower(), m.end()
        if i < n and text[i] == '"':
            end = text.find('"', i + 1)
            closed = end >= 0
            value = text[i + 1 : end] if closed else text[i + 1 :]
            i = end + 1 if closed else n
            out.append((field, value, True, closed))
            continue
        start = i
        while i < n and not text[i].isspace():
            i += 1
        value = text[start:i]
        if field and _OPERATOR_ONLY.match(value):  # "rating:>= 4": the number after a space
            j = i
            while j < n and text[j].isspace():
                j += 1
            k = j
            while k < n and not text[k].isspace():
                k += 1
            if j < n and _COMPARISON.match(text[j:k]):
                value, i = value + text[j:k], k
        out.append((field, value, False, True))
    return out


def _has_word(text: str) -> bool:
    """Whether FTS5's tokenizer finds a word in `text`: a letter or digit."""
    return any(ch.isalnum() for ch in text)


def parse(text: str) -> Query:
    """What the user typed (R2.7), as the terms and comparisons a song must meet. The last word
    matches as a prefix unless a space or a closing quote ends it. What has no letter or digit,
    a field with no value (`artist:` as it is typed) and a comparison with no number are left
    out, so a search half typed never empties the view."""
    words = _words(text.replace("\x00", " "))  # NUL ends FTS5's string: read as a space
    typing = bool(text) and not text[-1].isspace()
    terms: list[Term] = []
    compares: list[Compare] = []
    for n, (field, value, quoted, closed) in enumerate(words):
        last = n == len(words) - 1
        if field in NUMBER_FIELDS:
            m = _COMPARISON.match(value)
            if m:
                op = OPERATORS[m.group(1) or "="]
                if field == "rating" or m.group(1):
                    compares.append(Compare(field, op, float(m.group(2).replace(",", "."))))
                    continue
        if field == "rating" or not _has_word(value):
            continue  # a rating with no number, or nothing a word could match
        columns = TEXT_FIELDS.get(field, ()) if field else ()
        terms.append(Term(value, columns, last and typing and (not quoted or not closed)))
    return Query(tuple(terms), tuple(compares))


def _quoted(text: str) -> str:
    """An FTS5 string: in double quotes, its own doubled, so FTS5 reads none of it as syntax."""
    return '"' + text.replace('"', '""') + '"'


def match(query: Query) -> str:
    """The FTS5 expression of a query's terms: each a string, in its columns, a prefix when it is
    one, all of them required; "" when it has none."""
    out = []
    for t in query.terms:
        expr = _quoted(t.text) + ("*" if t.prefix else "")
        if t.columns:
            expr = "{" + " ".join(t.columns) + "} : " + expr
        out.append(expr)
    return " AND ".join(out)


def condition(query: Query) -> tuple[str, tuple[object, ...]]:
    """The SQL a list of songs adds to its WHERE for a query, on the table `song`, and its
    parameters: ("", ()) for a query that asks nothing."""
    parts: list[str] = []
    params: list[object] = []
    expr = match(query)
    if expr:
        parts.append("song.id IN (SELECT rowid FROM song_fts WHERE song_fts MATCH ?)")
        params.append(expr)
    for c in query.compares:
        parts.append(f"{NUMBER_FIELDS[c.field]} {c.op} ?")
        params.append(c.value)
    return " AND ".join(parts), tuple(params)


# ---------- the index ----------

# a song's row of song_fts from its row of song: its genres joined, its path's file name
_ROW = (
    "SELECT id, title, artist, album, albumartist,"
    " (SELECT group_concat(genre, ' ') FROM song_genre WHERE song_id = song.id), year,"
    " substr(path, length(rtrim(path, replace(path, '/', ''))) + 1) FROM song"
)


def index_songs(c: sqlite3.Connection, song_ids: Sequence[int]) -> None:
    """Writes the songs' rows of song_fts afresh from their rows of song and song_genre, in the
    caller's transaction."""
    for i in range(0, len(song_ids), 500):
        ids = tuple(song_ids[i : i + 500])
        marks = ", ".join("?" * len(ids))
        c.execute(f"DELETE FROM song_fts WHERE rowid IN ({marks})", ids)
        c.execute(
            f"INSERT INTO song_fts (rowid, {', '.join(COLUMNS)}) {_ROW} WHERE id IN ({marks})",
            ids,
        )


def forget(c: sqlite3.Connection, paths: Iterable[str]) -> None:
    """Removes the rows of song_fts of the songs at `paths`, before their rows of song go."""
    c.executemany(
        "DELETE FROM song_fts WHERE rowid = (SELECT id FROM song WHERE path = ?)",
        [(p,) for p in paths],
    )


# ---------- the values in use, suggested as the user types (R4.6) ----------

# what each field suggests from: an artist is anyone named as artist or album artist (R2.5.4)
_NAMES = (
    "SELECT name, COUNT(*) FROM (SELECT artist AS name FROM song UNION ALL"
    " SELECT albumartist FROM song) WHERE name IS NOT NULL GROUP BY name"
)
SUGGESTED = {
    "artist": _NAMES,
    "albumartist": _NAMES,
    "album": "SELECT album, COUNT(*) FROM song WHERE album IS NOT NULL GROUP BY album",
    "genres": "SELECT genre, COUNT(*) FROM song_genre GROUP BY genre",
}
SUGGESTIONS = 8  # the most a field suggests at once


def fold(text: str) -> str:
    """Text with case and accents set aside, as what is typed is matched: "Beyoncé" as
    "beyonce"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def rank(values: Iterable[tuple[str, int]], typed: str, limit: int = SUGGESTIONS) -> list[str]:
    """The values (each with how many songs have it) that what was `typed` could be the start
    of, case and accents aside: those that start with it first, then those with a word that does
    ("drift" finds "Lumen Drift"), each by how many songs have it, most first. The value typed
    exactly is left out, and nothing is suggested for nothing typed."""
    want = fold(typed.strip())
    if not want:
        return []
    starts: list[tuple[int, str]] = []
    words: list[tuple[int, str]] = []
    for value, n in values:
        name = fold(value)
        if name == want and value.strip() == typed.strip():
            continue
        if name.startswith(want):
            starts.append((-n, value))
        elif any(w.startswith(want) for w in re.split(r"[\s\-/&(,.]+", name)[1:]):
            words.append((-n, value))
    ordered = sorted(starts, key=lambda x: (x[0], fold(x[1]))) + sorted(
        words, key=lambda x: (x[0], fold(x[1]))
    )
    return [v for _, v in ordered[:limit]]


def suggestions(
    c: sqlite3.Connection, field: str, typed: str, limit: int = SUGGESTIONS
) -> list[str]:
    """The values of the library's songs that the Edit tags panel suggests for `field` (artist,
    albumartist, album, genres; R4.6) as `typed` is typed (`rank`); none for another field."""
    query = SUGGESTED.get(field)
    if query is None or not typed.strip():
        return []
    return rank(c.execute(query), typed, limit)
