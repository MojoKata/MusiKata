"""Smart playlists (R8.9): a rule instead of a list, kept as a playlist file like any other, its
rule in a `#MUSIKATA-RULE:` comment line that other players pass by.

- **The rule** (`Rule`): any of rating at least N stars, genre is, artist is, year between, added
  in the last N days, played at least N times, each there or not; every condition there must hold
  (they are joined by AND: "Jazz rated four stars and up" is two conditions narrowing one list);
  then a limit (the first N songs, or all) and an order. A rule with no condition is every song.
- **Its text** (`format_rule`, `read_rule`), what follows `#MUSIKATA-RULE:` (A2.10): one line of
  JSON, `{"format": 1, "rating": 4, "order": "rating"}`, the conditions there only when set, its
  fields it doesn't know kept when it is written again. It is read in the shapes another version
  or a hand edit gives it, never raising: a newer `format` is read for what it can and never
  written; text that isn't a rule, or a condition, limit or order it can't use, makes the rule
  broken, and the playlist is then a plain list, kept as its file has it.
- **Its songs** (`query`, `songs`, `count`): one query over the index, the plays of every computer
  summed (R7.9), ordered with ties broken by the library's artist order and the path, so the same
  library gives the same list.
- **Kept current** (`changed`, `wait_for`, `Keeper`): the file is rewritten when its songs, in
  order, are no longer the rule's, never when they are; and at most every QUICK seconds for a
  change the library made (a scan, a save, a rating) and every SLOW seconds for one plays alone
  made, so a root kept in sync isn't uploaded at every song played (A2.8)."""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .albums import artist_identity

log = logging.getLogger(__name__)

RULE = "#MUSIKATA-RULE:"  # the comment line a smart playlist's rule is in (R8.9)
FORMAT = 1  # the rule's text's version (A2.10)
DAY = 86_400.0
STARS = 5
# the orders: by name, what it says and its ORDER BY; ties by the library's artist order
BY_ARTIST = (
    "song.artist_key IS NULL, song.artist_key, song.album_key IS NULL, song.album_key,"
    " song.album_id, song.disc, song.track, song.path"
)
ORDERS: dict[str, tuple[str, str]] = {
    "artist": ("by artist and album", BY_ARTIST),
    "title": ("by title", f"song.title IS NULL, song.title COLLATE NOCASE, {BY_ARTIST}"),
    "rating": ("highest rated first", f"coalesce(song.rating, 0) DESC, {BY_ARTIST}"),
    "plays": ("most played first", f"coalesce(p.plays, 0) DESC, {BY_ARTIST}"),
    "played": ("last played first", f"p.last IS NULL, p.last DESC, {BY_ARTIST}"),
    "added": ("newest added first", f"song.added IS NULL, song.added DESC, {BY_ARTIST}"),
    "year": ("newest year first", f"song.year IS NULL, song.year DESC, {BY_ARTIST}"),
}
DEFAULT_ORDER = "artist"
PLAYS = (
    "LEFT JOIN (SELECT song_id, SUM(count) AS plays, MAX(last) AS last FROM play"
    " WHERE song_id IS NOT NULL GROUP BY song_id) AS p ON p.song_id = song.id"
)
# what kept it current: the library (a scan, a save, a rating), plays alone, or the rule edited
LIBRARY, PLAYED, EDITED = "library", "played", "edited"
QUICK = 60.0  # seconds at least between two writes of one smart playlist the library changed
SLOW = 600.0  # and the same for one plays alone changed: a synced root uploads it seldom


# ---------- the rule ----------


@dataclass(frozen=True)
class Rule:
    """A smart playlist's rule (R8.9): each condition None when it isn't one; `years` from and to,
    either open (None); `limit` None for every song; `order` one of ORDERS; `format` the version
    it was read in (newer: never written); `extra` the fields it doesn't know, each as its JSON,
    kept when it is written again."""

    rating: int | None = None
    genre: str | None = None
    artist: str | None = None
    years: tuple[int | None, int | None] | None = None
    added: int | None = None
    plays: int | None = None
    limit: int | None = None
    order: str = DEFAULT_ORDER
    format: int = FORMAT
    extra: tuple[tuple[str, str], ...] = ()

    def conditions(self) -> int:
        """How many conditions it holds."""
        values = (self.rating, self.genre, self.artist, self.years, self.added, self.plays)
        return sum(v is not None for v in values)


# its kinds, as read: kept current, newer (read, never written), broken (a plain list)
SMART, NEWER, BROKEN = "smart", "newer", "broken"


@dataclass(frozen=True)
class Reading:
    """A rule's text as read: the rule (what could be read of it), its kind (SMART, NEWER or
    BROKEN) and, when it isn't SMART, why, as the playlist's page says it."""

    rule: Rule
    kind: str = SMART
    why: str = ""

    @property
    def kept(self) -> bool:
        """Whether its songs are kept current from the index."""
        return self.kind == SMART

    @property
    def smart(self) -> bool:
        """Whether it is a smart playlist, its songs not changed by hand: kept current, or a
        newer MusiKata's."""
        return self.kind in (SMART, NEWER)


KNOWN = ("format", "rating", "genre", "artist", "years", "added", "plays", "limit", "order")


def _whole(value: object) -> int | None:
    """A whole number as a rule holds one: `4`, `4.0` or `"4"`; None for anything else (a bool,
    a fraction, text that isn't a number)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in "+-":
            sign, text = text[0], text[1:]
        else:
            sign = ""
        return int(sign + text) if text.isascii() and text.isdigit() else None
    return None


def _at_least(value: object, low: int, high: int | None = None) -> int | None:
    n = _whole(value)
    if n is None or n < low or (high is not None and n > high):
        return None
    return n


class _Unusable(Exception):
    """A field of a rule with a value it can't use: its name and what it holds."""


def _text(name: str, value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _Unusable(name)
    return value if value.strip() else None


def _years(value: object) -> tuple[int | None, int | None] | None:
    if value is None:
        return None
    one = _whole(value)
    if one is not None:  # a year alone: that year
        return one, one
    if not isinstance(value, list) or len(value) != 2:
        raise _Unusable("years")
    ends = []
    for v in value:
        n = _whole(v)
        if v is not None and n is None:
            raise _Unusable("years")
        ends.append(n)
    low, high = ends
    if low is None and high is None:
        return None
    if low is not None and high is not None and low > high:  # written the other way round
        low, high = high, low
    return low, high


def _field(name: str, value: object) -> object:
    """A known field's value as the rule holds it; None for none. Raises _Unusable."""
    if name in ("genre", "artist"):
        return _text(name, value)
    if name == "years":
        return _years(value)
    if value is None:
        return None
    if name == "rating":
        n = _at_least(value, 1, STARS)
    elif name in ("added", "plays", "limit"):
        n = _at_least(value, 1)
    else:  # order
        n = None
        if isinstance(value, str) and value.strip().lower() in ORDERS:
            return value.strip().lower()
    if n is None:
        raise _Unusable(name)
    return n


WHY = {
    "rating": "its rating isn't 1 to 5 stars",
    "genre": "its genre isn't text",
    "artist": "its artist isn't text",
    "years": "its years aren't a year or two",
    "added": "its days added aren't a number of days",
    "plays": "its plays aren't a number of times",
    "limit": "its limit isn't a number of songs",
    "order": "its order isn't one this MusiKata knows",
}


def read_rule(text: str) -> Reading:
    """The rule in `text`, what follows `#MUSIKATA-RULE:`, whatever it holds (A2.10); never
    raises. A newer format is read for what it can (NEWER); text that isn't a rule's, or a field
    it knows holding what it can't use, is BROKEN, saying why, with what could be read."""
    try:
        value = json.loads(text)
    except ValueError, RecursionError:
        return Reading(Rule(), BROKEN, "its rule isn't one MusiKata can read")
    if not isinstance(value, dict):
        return Reading(Rule(), BROKEN, "its rule isn't one MusiKata can read")
    version = _at_least(value.get("format"), 1) or FORMAT  # missing or unreadable: the first
    newer = version > FORMAT
    fields: dict[str, Any] = {}
    unusable: list[str] = []
    for name in KNOWN[1:]:
        try:
            fields[name] = _field(name, value.get(name))
        except _Unusable:
            unusable.append(name)
            fields[name] = None
    fields["order"] = fields["order"] or DEFAULT_ORDER
    extra = tuple(sorted((str(k), json.dumps(v, ensure_ascii=False))
                         for k, v in value.items() if k not in KNOWN))  # fmt: skip
    rule = Rule(**fields, format=version, extra=extra)
    if newer:
        return Reading(rule, NEWER, "its rule is a newer MusiKata's: kept as it is")
    if unusable:
        return Reading(rule, BROKEN, WHY[unusable[0]])
    return Reading(rule)


def parse_rule(text: str) -> Rule | None:
    """The rule in `text` when it is one this MusiKata keeps current (`read_rule`); else None."""
    reading = read_rule(text)
    return reading.rule if reading.kept else None


def format_rule(rule: Rule) -> str:
    """A rule's text, as `#MUSIKATA-RULE:` holds it: JSON on one line, the conditions set, the
    limit when there is one, the order, then the fields it didn't know as they were."""
    out: dict[str, Any] = {"format": FORMAT}
    for name in ("rating", "genre", "artist"):
        if getattr(rule, name) is not None:
            out[name] = getattr(rule, name)
    if rule.years is not None:
        out["years"] = list(rule.years)
    for name in ("added", "plays", "limit"):
        if getattr(rule, name) is not None:
            out[name] = getattr(rule, name)
    out["order"] = rule.order
    for key, value in rule.extra:
        if key not in out:
            out[key] = json.loads(value)
    return json.dumps(out, ensure_ascii=False, separators=(", ", ": "))


def rule_line(rule: Rule) -> str:
    """The comment line a smart playlist's file holds its rule in."""
    return RULE + format_rule(rule)


def rule_text_of(header: Iterable[str]) -> str | None:
    """The rule's text in a playlist's header (its first `#MUSIKATA-RULE:` line, in any case);
    None when there is none."""
    return next((h[len(RULE) :].strip() for h in header if h.upper().startswith(RULE)), None)


def reading_of(text: str | None) -> Reading | None:
    """A playlist's rule as read from its text (the index's `playlist.rule`); None: no rule, a
    plain playlist."""
    return None if text is None else read_rule(text)


def with_rule(header: Sequence[str], rule: Rule) -> tuple[str, ...]:
    """A playlist's header with `rule` in it: in place of the rule line it had, or first."""
    line = rule_line(rule)
    if rule_text_of(header) is None:
        return (line, *header)
    out, done = [], False
    for h in header:
        if h.upper().startswith(RULE):
            if not done:
                out.append(line)
                done = True
            continue
        out.append(h)
    return tuple(out)


def suggested_name(rule: Rule) -> str:
    """A new smart playlist's name, from its rule (R8.9's sidebar: "Four stars and up")."""
    words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
    parts = []
    if rule.genre is not None:
        parts.append(rule.genre.strip())
    if rule.artist is not None:
        parts.append(rule.artist.strip())
    if rule.rating is not None:
        stars = f"{words[rule.rating]} star{'s' if rule.rating > 1 else ''}"
        parts.append(stars if rule.rating == STARS else f"{stars} and up")
    if rule.years is not None:
        low, high = rule.years
        parts.append(f"{low}" if low == high else f"{low or ''}–{high or ''}")
    if rule.added is not None:
        parts.append(f"Added in {rule.added} days")
    if rule.plays is not None:
        parts.append(f"Played {rule.plays}+")
    name = ", ".join(parts)
    return (name[:1].upper() + name[1:]) if name else "New smart playlist"


# ---------- its songs ----------


def query(rule: Rule, now: float, counting: bool = False) -> tuple[str, list[object]]:
    """The query of the songs `rule` picks at `now` (seconds since the epoch, for the days
    added): their paths in its order, up to its limit; or, `counting`, how many match, the limit
    aside. Every condition holds; a song that couldn't be read is never picked."""
    where = ["song.error IS NULL"]
    params: list[object] = []
    if rule.rating is not None:
        where.append("coalesce(song.rating, 0) >= ?")
        params.append(rule.rating)
    if rule.genre is not None:
        where.append("song.id IN (SELECT song_id FROM song_genre WHERE genre = ? COLLATE NOCASE)")
        params.append(rule.genre.strip())
    if rule.artist is not None:
        # the artist's songs and its albums', names that differ only in case as one (R2.5.4)
        where.append(
            "(song.artist_id IN (SELECT id FROM artist WHERE identity = ?) OR song.album_id IN"
            " (SELECT album.id FROM album JOIN artist ON artist.id = album.artist_id"
            " WHERE artist.identity = ?))"
        )
        who = artist_identity(rule.artist)
        params += [who, who]
    if rule.years is not None:
        low, high = rule.years
        if low is not None:
            where.append("song.year >= ?")
            params.append(low)
        if high is not None:
            where.append("song.year <= ?")
            params.append(high)
    if rule.added is not None:
        where.append("song.added >= ?")
        params.append(now - rule.added * DAY)
    if rule.plays is not None:
        where.append("coalesce(p.plays, 0) >= ?")
        params.append(rule.plays)
    joined = rule.plays is not None or rule.order in ("plays", "played")
    table = f"song {PLAYS}" if joined else "song"
    conditions = " AND ".join(where)
    if counting:
        return f"SELECT COUNT(*) FROM {table} WHERE {conditions}", params
    sql = f"SELECT song.path FROM {table} WHERE {conditions} ORDER BY {ORDERS[rule.order][1]}"
    if rule.limit is not None:
        sql += " LIMIT ?"
        params.append(rule.limit)
    return sql, params


def songs(c: sqlite3.Connection, rule: Rule, now: float) -> list[str]:
    """The paths (under the root) of the songs `rule` picks at `now`, in its order."""
    sql, params = query(rule, now)
    return [str(p) for (p,) in c.execute(sql, params)]


def count(c: sqlite3.Connection, rule: Rule, now: float) -> int:
    """How many songs `rule`'s conditions pick at `now`, its limit aside."""
    sql, params = query(rule, now, counting=True)
    return int(c.execute(sql, params).fetchone()[0])


# ---------- kept current ----------


def changed(file: Sequence[str | None], wanted: Sequence[str]) -> bool:
    """Whether a smart playlist's file must be written again: the songs its entries name (by
    path under the root, None for one outside it), in order, aren't the rule's."""
    return list(file) != list(wanted)


def quickest(a: str | None, b: str | None) -> str | None:
    """Of two causes, the one written soonest after (EDITED, then LIBRARY, then PLAYED)."""
    rank = {EDITED: 0, LIBRARY: 1, PLAYED: 2}
    given = [x for x in (a, b) if x is not None]
    return min(given, key=lambda x: rank.get(x, 3)) if given else None


def wait_for(last: float | None, now: float, cause: str) -> float:
    """Seconds before a smart playlist whose songs changed may be written, it having been last
    written at `last` (None: not since MusiKata started): none for a rule just edited or one not
    written yet; else what is left of QUICK after a change the library made (a scan, a save, a
    rating), or of SLOW after one plays alone made (A2.8: a synced root isn't uploaded at every
    song played)."""
    if last is None or cause == EDITED:
        return 0.0
    gap = SLOW if cause == PLAYED else QUICK
    return max(0.0, last + gap - now)


class Clock(Protocol):
    def now(self) -> Any: ...

    def monotonic(self) -> float: ...


class Refiller(Protocol):
    """What writes a smart playlist's songs: playlists.Store.refill."""

    def refill(self, playlist: int, text: str, paths: Sequence[str]) -> bool: ...


@dataclass
class Checked:
    """What a check did: the playlists written (their ids), and in how many seconds the next
    check is due (None: none waits)."""

    written: list[int] = field(default_factory=list)
    due: float | None = None


class Keeper:
    """Keeps every smart playlist of the index current (R8.9), each check on the caller's thread
    (never the GUI's): each one's songs worked out from the index, compared with its file's
    (`changed`), and written through `store` when they differ and its pace allows
    (`wait_for`); otherwise when the next check is due. `read` gives this thread's connection;
    `clock` the time."""

    def __init__(
        self, store: Refiller, read: Callable[[], sqlite3.Connection], clock: Clock
    ) -> None:
        self._store, self._read, self._clock = store, read, clock
        self._last: dict[int, float] = {}  # playlist -> when it was last written (monotonic)
        self._waiting: str | None = None  # the cause of a change waiting on its pace

    def smart(self) -> list[tuple[int, str, Rule]]:
        """The smart playlists kept current: id, its rule's text, the rule."""
        out = []
        for playlist, text in self._read().execute(
            "SELECT id, rule FROM playlist WHERE rule IS NOT NULL ORDER BY id"
        ):
            rule = parse_rule(str(text))
            if rule is not None:
                out.append((int(playlist), str(text), rule))
        return out

    def file_songs(self, playlist: int) -> list[str | None]:
        """The songs a playlist's entries name, as the index holds them, in order."""
        return [
            None if p is None else str(p)
            for (p,) in self._read().execute(
                "SELECT path FROM playlist_entry WHERE playlist_id = ? ORDER BY position",
                (playlist,),
            )
        ]

    def check(self, cause: str = LIBRARY, only: int | None = None) -> Checked:
        """Each smart playlist (or `only` that one) whose songs are no longer its rule's written,
        when its pace allows; the others' next check when due. A playlist that can't be written
        waits its pace before it is tried again (logged)."""
        cause = quickest(cause, self._waiting) or cause
        now, mono = self._clock.now().timestamp(), self._clock.monotonic()
        out = Checked()
        waiting = False
        for playlist, text, rule in self.smart():
            if only is not None and playlist != only:
                continue
            wanted = songs(self._read(), rule, now)
            if not changed(self.file_songs(playlist), wanted):
                continue
            wait = wait_for(self._last.get(playlist), mono, cause)
            if wait > 0:
                waiting = True
                out.due = wait if out.due is None else min(out.due, wait)
                continue
            self._last[playlist] = mono
            try:
                if self._store.refill(playlist, text, wanted):
                    out.written.append(playlist)
            except Exception as e:  # noqa: BLE001  (logged; tried again after its pace)
                log.warning("the smart playlist %d couldn't be kept current: %s", playlist, e)
        self._waiting = cause if waiting else None
        return out

    def forget(self, playlists: Iterable[int]) -> None:
        """Playlists gone: their pace forgotten."""
        for p in playlists:
            self._last.pop(p, None)
