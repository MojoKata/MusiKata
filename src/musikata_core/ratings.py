"""Ratings (R10) where they are kept: written into the songs as R10.4's table says (tags.compose,
tags.write), or into the root's `.musikata/ratings.json` (R10.3, A2.8, A2.10) for the songs
whose files can't hold one (WAV and AIFF, compose.UNRATED) and, with R10.3's setting (the root's
`tags.write_ratings` off), for every song (`in_file`).

A rating is read from where it is written: the index's `song.rating`, which every list shows,
sorts and searches by (R10.5), is the song's ratings.json entry when its ratings are kept there
and it has one, else its file's (`song.file_rating`), so a WAV another player rated in its own
tag shows that until it is rated here (`apply`). The setting is kept in the index too
(`set_everything`), so a scan works it out the same way (`link`).

ratings.json is any computer's to write (A2.10): before writing, it is read again and merged entry
by entry, the newest `changed` winning (`merge`), so two computers rating at once lose nothing; a
rating cleared is kept as `stars` 0, so it wins over an older rating from another. An entry names
its song by its path under the root and its audio hash, matched by path, else by hash when no song
has its path (A2.8), so a song moved in a file manager keeps its rating; an entry for a song moved
since is dropped when the song is rated again where it is now. The index holds the file's entries
(`rating`), merged in as they are read, at start and whenever the watcher sees the file change
(`load`). A file of a newer MusiKata is read, never written; one that can't be read (cut short by a
sync in progress, not JSON) isn't written over, and a rating that would go there fails, saying
why (`save`). When `.musikata` can't be written (R1.5.2), a rating is kept in the index only, as
plays are.

Writing is `Writing`, a save's writer (tags.Batch): each file's rating goes where its song's
ratings are kept, the rest of its changes to the file (safe.save), and it says what the song reads
as now, so the change history (R4.9) keeps a rating as it keeps any field, and Undo puts it back
where it is kept."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import sqlite3
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from . import db, rootfiles
from .clock import Clock
from .tags import EXTENSIONS, AudioInfo, Job, Tags, WriteError, Written, compose

log = logging.getLogger(__name__)

FORMAT = 1  # ratings.json's format (A2.10)
NAME = "ratings.json"
KNOWN = frozenset({"format", "songs"})
KNOWN_SONG = frozenset({"path", "hash", "stars", "changed"})
CHUNK = 500  # songs worked out at a time


@dataclass(frozen=True)
class Entry:
    """A song's rating as ratings.json keeps it: its path under the root, its audio hash (None:
    not known), its stars (0: cleared) and when it was set, a UTC time as A2.10 writes it."""

    path: str
    hash: str | None
    stars: int
    changed: str


@dataclass(frozen=True)
class Ratings:
    """A ratings.json as read: its entries, its fields this version doesn't know (`extras`, and
    each entry's by path) to keep when it is written again; `newer`, a newer MusiKata's format,
    never written; `broken`, a file that couldn't be used at all; `problems`, what couldn't be
    used, for the log."""

    entries: tuple[Entry, ...] = ()
    extras: Mapping[str, object] = field(default_factory=dict)
    song_extras: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    newer: bool = False
    broken: bool = False
    problems: tuple[str, ...] = ()


class RatingsError(Exception):
    """ratings.json couldn't be written, and why, in words a person can act on (R10.2)."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


# ---------- where a rating goes (R10.3, R10.4) ----------


def in_file(kind: str | None, write_ratings: bool) -> bool:
    """Whether a song of `kind` (R2.2's, as tags.read names it) has its rating written into its
    file: unless its kind can't hold one (R10.4) or `write_ratings`, R10.3's setting, is off."""
    return write_ratings and kind not in compose.UNRATED


# ---------- the file, as plain data ----------


def _stars(value: object) -> int | None:
    """A number of stars from `value`: a whole number 0 to 5, also as 4.0 or "4"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and 0 <= value <= 5 else None


def _entry(value: object, problems: list[str]) -> tuple[Entry, dict[str, object]] | None:
    """An entry of `songs` and its fields this version doesn't know; None, with the problem,
    when it can't be used."""
    if not isinstance(value, dict):
        problems.append(f"a song isn't an object: {value!r}; left out")
        return None
    path = value.get("path")
    if not isinstance(path, str) or not path:
        problems.append(f"a song's path isn't a path under the root: {path!r}; left out")
        return None
    stars = _stars(value.get("stars"))
    if stars is None:
        problems.append(f"{path}: its stars aren't 0 to 5: {value.get('stars')!r}; left out")
        return None
    hash_ = value.get("hash")
    if isinstance(hash_, str) and rootfiles.HASH.fullmatch(hash_.lower()):
        hash_ = hash_.lower()
    else:
        problems.append(f"{path}: its hash isn't an audio hash: {hash_!r}; found by its path only")
        hash_ = None
    changed = rootfiles.parse_time(value.get("changed"))
    if changed is None:
        problems.append(
            f"{path}: changed isn't a UTC time: {value.get('changed')!r}; the oldest there is"
        )
        changed = rootfiles.UNKNOWN
    extras = {k: v for k, v in value.items() if k not in KNOWN_SONG}
    return Entry(path, hash_, stars, changed), extras


def _broken(why: str) -> Ratings:
    return Ratings(broken=True, problems=(f"{why}: its ratings aren't read",))


def parse(text: str) -> Ratings:
    """The ratings in `text`, a ratings.json's content, whatever was written there: a file that
    can't be used whole gives none, and an entry that can't be used is left out, each named in
    `problems`. A song named twice is one, the newest `changed` winning."""
    try:
        data = json.loads(text.removeprefix("﻿"))
    except ValueError as e:
        return _broken(f"it isn't JSON ({e})")
    if not isinstance(data, dict):
        return _broken("it isn't a JSON object")
    problems: list[str] = []
    fmt = data.get("format")
    newer = False
    if isinstance(fmt, int) and not isinstance(fmt, bool):
        newer = fmt > FORMAT
        if newer:
            problems.append(f"it is format {fmt}, from a newer MusiKata: it is read, not written")
    elif fmt is not None:
        problems.append(f"format isn't a number: {fmt!r}; read as format {FORMAT}")
    listed = data.get("songs", [])
    if not isinstance(listed, list):
        return _broken(f"songs isn't a list: {listed!r}")
    entries: dict[str, Entry] = {}
    song_extras: dict[str, Mapping[str, object]] = {}
    for value in listed:
        read_ = _entry(value, problems)
        if read_ is None:
            continue
        entry, extras = read_
        twice = entries.get(entry.path)
        if twice is not None:
            problems.append(f"{entry.path} is named twice: the newest is kept")
            if twice.changed > entry.changed:
                continue
        entries[entry.path] = entry
        if extras:
            song_extras[entry.path] = extras
    return Ratings(
        entries=tuple(entries.values()),
        extras={k: v for k, v in data.items() if k not in KNOWN},
        song_extras=song_extras,
        newer=newer,
        problems=tuple(problems),
    )


def merge(kept: Iterable[Entry], mine: Iterable[Entry]) -> list[Entry]:
    """The entries of `kept` (the file as read again) with `mine` (this computer's new ones),
    entry by entry, the newest `changed` winning and, at the same time, `mine` (A2.8); by
    path, in path order."""
    out = {e.path: e for e in kept}
    for e in mine:
        there = out.get(e.path)
        if there is None or e.changed >= there.changed:
            out[e.path] = e
    return [out[p] for p in sorted(out)]


def document(entries: Iterable[Entry], kept: Ratings | None = None) -> dict[str, object]:
    """ratings.json for `entries`; the fields `kept`, the file as read, had that this version
    doesn't know are kept (A2.10). An entry without an audio hash is left out, as A2.10 names
    each song by both (it is kept in the index)."""
    extras = kept.extras if kept is not None else {}
    song_extras = kept.song_extras if kept is not None else {}
    songs: list[dict[str, object]] = []
    for e in entries:
        if e.hash is None:
            log.info("%s has no audio hash: its rating is kept in the index only", e.path)
            continue
        songs.append(
            {**song_extras.get(e.path, {}), "path": e.path, "hash": e.hash, "stars": e.stars,
             "changed": e.changed}
        )  # fmt: skip
    return {**extras, "format": FORMAT, "songs": songs}


# ---------- the file on disk ----------


def file_of(root: str) -> str:
    """The root's ratings.json, in its `.musikata` (R1.5)."""
    return os.path.join(rootfiles.folder_of(root), NAME)


def read(path: str) -> Ratings | None:
    """The ratings.json at `path`, each problem logged; None when there is none."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        found = _broken(f"it couldn't be read ({e.strerror or e})")
    else:
        found = parse(text)
    for problem in found.problems:
        log.warning("%s: %s", path, problem)
    return found


def _write(path: str, data: Mapping[str, object]) -> None:
    """`data` written to `path` through a temporary file moved over it (A2.8). Raises OSError."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def save(path: str, mine: Sequence[Entry], gone: Callable[[str], bool]) -> list[Entry]:
    """`mine` written into the ratings.json at `path`, read again first and merged (`merge`); an
    entry for the same audio at a path `gone` says is gone (a song moved since) is dropped. The
    entries written. Raises RatingsError, the file as it was, when it is a newer MusiKata's,
    can't be read (it isn't written over: a sync may be bringing it), or can't be written."""
    found = read(path)
    if found is not None and found.newer:
        raise RatingsError(
            "the music folder's ratings.json was changed by a newer MusiKata: update MusiKata to"
            " change the ratings kept there"
        )
    if found is not None and found.broken:
        why = found.problems[0] if found.problems else "it can't be read"
        raise RatingsError(
            f"the music folder's ratings.json can't be read, so it isn't written over ({why})"
        )
    moved = {(e.hash, e.path) for e in mine if e.hash is not None}
    hashes = {h for h, _ in moved}
    kept = [
        e
        for e in (found.entries if found is not None else ())
        if not (e.hash in hashes and (e.hash, e.path) not in moved and gone(e.path))
    ]
    entries = merge(kept, mine)
    try:
        _write(path, document(entries, found))
    except OSError as e:
        log.warning("couldn't write %s: %s", path, e)
        raise RatingsError(
            f"the music folder's ratings.json couldn't be written: {e.strerror or e}"
        ) from e
    return entries


# ---------- in the index: each function runs in the writer's transaction ----------


def set_everything(c: sqlite3.Connection, everything: bool) -> None:
    """R10.3's setting as the index works ratings out: every song's rating kept in ratings.json
    (`everything`), or only those whose files can't hold one; every song's rating worked out
    again when it changed."""
    row = c.execute("SELECT everything FROM rating_rule").fetchone()
    if row is not None and bool(row[0]) == everything:
        return
    c.execute("DELETE FROM rating_rule")
    c.execute("INSERT INTO rating_rule VALUES (?)", (int(everything),))
    apply(c, None)


def _chunks(ids: Collection[int]) -> Iterable[list[int]]:
    wanted = sorted(ids)
    for i in range(0, len(wanted), CHUNK):
        yield wanted[i : i + CHUNK]


def apply(c: sqlite3.Connection, songs: Collection[int] | None) -> None:
    """The rating shown (`song.rating`) of `songs` (None: every song) worked out again: its
    ratings.json entry when its ratings are kept there and it has one (the one naming its path
    first, then the newest), else its file's."""
    row = c.execute("SELECT everything FROM rating_rule").fetchone()
    everything = int(bool(row and row[0]))
    unrated = ", ".join(f"'{k}'" for k in compose.UNRATED)
    # The outer song is named only in WHERE clauses: Windows' SQLite (PyInstaller's Python) has
    # no outer column in a subquery's ORDER BY ("no such column: song.path").
    sql = (
        "UPDATE song SET rating = CASE WHEN (? OR kind IN (" + unrated + "))"
        " AND EXISTS (SELECT 1 FROM rating WHERE song_id = song.id)"
        " THEN COALESCE("
        "(SELECT stars FROM rating WHERE song_id = song.id AND rating.path = song.path"
        " ORDER BY changed DESC LIMIT 1),"
        " (SELECT stars FROM rating WHERE song_id = song.id ORDER BY changed DESC LIMIT 1))"
        " ELSE file_rating END"
    )
    if songs is None:
        c.execute(sql, (everything,))
        return
    for chunk in _chunks(songs):
        marks = ", ".join("?" * len(chunk))
        c.execute(f"{sql} WHERE id IN ({marks})", (everything, *chunk))


def _relink(c: sqlite3.Connection) -> set[int]:
    """The entries standing for no song matched again, by path, else by hash (A2.8); the songs
    they now stand for."""
    rows = c.execute("SELECT id, path, hash, stars, changed FROM rating WHERE song_id IS NULL")
    found = [(r[0], Entry(r[1], r[2], r[3], r[4])) for r in rows.fetchall()]
    if not found:
        return set()
    songs = rootfiles.find(c, [e for _, e in found])
    updates = [(s, i) for s, (i, _) in zip(songs, found, strict=True) if s is not None]
    c.executemany("UPDATE rating SET song_id = ? WHERE id = ?", updates)
    return {s for s, _ in updates}


def link(c: sqlite3.Connection, songs: Iterable[int]) -> None:
    """The songs of `songs`, just written by a scan or a save, matched to the entries naming
    their paths (a path wins over a hash, A2.8), entries standing for no song matched again (a
    scan may have brought theirs), and the rating each shows worked out (`apply`)."""
    touched: set[int] = set()
    for song in songs:
        touched.add(song)
        found = c.execute("SELECT path FROM song WHERE id = ?", (song,)).fetchone()
        if found is None:
            continue
        for (before,) in c.execute(
            "SELECT song_id FROM rating WHERE path = ? AND song_id IS NOT ?", (found[0], song)
        ).fetchall():
            if before is not None:
                touched.add(before)
        c.execute("UPDATE rating SET song_id = ? WHERE path = ?", (song, found[0]))
    touched |= _relink(c)
    apply(c, touched)


def load(c: sqlite3.Connection, entries: Iterable[Entry]) -> None:
    """Entries of ratings.json (as read, or written by this computer) merged into the index's,
    entry by entry, the newest `changed` winning; each matched to its song again, and the
    ratings of the songs they stood for and stand for now worked out."""
    touched: set[int] = set()
    for e in entries:
        row = c.execute("SELECT id, changed, song_id FROM rating WHERE path = ?", (e.path,))
        there = row.fetchone()
        if there is None:
            c.execute(
                "INSERT INTO rating (path, hash, stars, changed) VALUES (?, ?, ?, ?)",
                (e.path, e.hash, e.stars, e.changed),
            )
            continue
        if e.changed < there[1]:
            continue
        if there[2] is not None:
            touched.add(there[2])
        c.execute(
            "UPDATE rating SET hash = ?, stars = ?, changed = ?, song_id = NULL WHERE id = ?",
            (e.hash, e.stars, e.changed, there[0]),
        )
    touched |= _relink(c)
    apply(c, touched)


def entries_of(c: sqlite3.Connection) -> list[Entry]:
    """The entries the index holds, by path."""
    rows = c.execute("SELECT path, hash, stars, changed FROM rating ORDER BY path")
    return [Entry(*r) for r in rows]


# ---------- writing a save's ratings ----------


@dataclass(frozen=True)
class Song:
    """A song as the index has it, for a rating kept beside it: its kind, audio hash, the rating
    it shows, its tags and audio, and the size and modification time its file was read at."""

    kind: str | None
    hash: str | None
    rating: int
    tags: Tags
    info: AudioInfo
    size: int
    mtime_ns: int


ROW = ("kind", "audio_hash", "length", "bitrate", "sample_rate", "channels", "size", "mtime_ns",
       *db.FIELDS)  # fmt: skip


def song_of(c: sqlite3.Connection, path: str) -> Song | None:
    """The song at `path` under the root, as the index has it; None when it hasn't."""
    r = c.execute(f"SELECT id, {', '.join(ROW)} FROM song WHERE path = ?", (path,)).fetchone()
    if r is None:
        return None
    values = dict(zip(ROW, r[1:], strict=True))
    genres = tuple(g for (g,) in c.execute(
        "SELECT genre FROM song_genre WHERE song_id = ? ORDER BY position", (r[0],)
    ))  # fmt: skip
    fields = {f: values[f] for f in db.FIELDS}
    fields["compilation"] = bool(fields["compilation"])
    fields["has_cover"] = bool(fields["has_cover"])
    tags = Tags(**fields, genres=genres)
    info = AudioInfo(
        values["kind"] or "", values["length"] or 0.0, values["bitrate"] or 0,
        values["sample_rate"] or 0, values["channels"] or 0,
    )  # fmt: skip
    return Song(
        values["kind"], values["audio_hash"], tags.rating or 0, tags, info, values["size"],
        values["mtime_ns"],
    )  # fmt: skip


class Writing:
    """A save's writer (tags.Batch's `write`) for the root `root`, whose index is `index`: a
    file's changes written by `write_file` (safe.save, with the root's settings), but its rating
    where its song's ratings are kept (`in_file`, `write_ratings` R10.3's setting): ratings.json,
    read again and merged first (`save`), and the index (`load`), at `clock`'s time. It says what
    the song reads as now, as safe.save does, the rating as kept. On whichever thread runs the
    batch, never the GUI thread (A1.3)."""

    def __init__(
        self,
        root: str,
        index: db.Index,
        write_file: Callable[[Job], Written],
        write_ratings: bool,
        clock: Clock,
    ) -> None:
        self._root, self._index, self._write_file = root, index, write_file
        self._write_ratings, self._clock = write_ratings, clock
        self._musikata = rootfiles.folder_of(root)

    def kept(self, path: str) -> int | None:
        """The rating of the song at `path` (a whole path) as ratings.json keeps it, 0 when it
        has none there; None when its file keeps it (its tags say it)."""
        rel = rootfiles.path_under(self._root, path)
        song = song_of(self._index.read(), rel) if rel is not None else None
        kind = song.kind if song is not None else EXTENSIONS.get(os.path.splitext(path)[1].lower())
        if in_file(kind, self._write_ratings):
            return None
        return song.rating if song is not None else 0

    def __call__(self, job: Job) -> Written:
        if "rating" not in job.changes:
            return self._write_file(job)
        rel = rootfiles.path_under(self._root, job.path)
        song = song_of(self._index.read(), rel) if rel is not None else None
        kind = (
            song.kind if song is not None else EXTENSIONS.get(os.path.splitext(job.path)[1].lower())
        )
        if in_file(kind, self._write_ratings):
            return self._write_file(job)
        if song is None or rel is None:
            raise WriteError(job.path, "it isn't in the library yet, so its rating can't be kept")
        stars = compose.normalize({"rating": job.changes["rating"]})["rating"]
        assert isinstance(stars, int)
        rest = {k: v for k, v in job.changes.items() if k != "rating"}
        written = self._write_file(Job(job.path, rest)) if rest else None
        if stars != song.rating:
            self._keep(job.path, Entry(rel, song.hash, stars, self._now()))
        before = replace(written.before if written and written.before else song.tags,
                         rating=song.rating)  # fmt: skip
        after = replace(written.tags if written else song.tags, rating=stars)
        changed = set(written.changed if written else ()) | ({"rating"} if stars != song.rating
                                                               else set())  # fmt: skip
        return Written(
            job.path, after, written.info if written else song.info,
            written.audio_hash if written else song.hash or "",
            written.size if written else song.size, written.mtime_ns if written else song.mtime_ns,
            before, tuple(f for f in compose.FIELDS if f in changed),
            written.cover_before if written else None, written.cover_after if written else None,
            written.others_before if written else None, written.others_after if written else None,
        )  # fmt: skip

    def _now(self) -> str:
        return rootfiles.time_text(self._clock.now())

    def _keep(self, path: str, entry: Entry) -> None:
        """The rating `entry` kept: in ratings.json when `.musikata` can be written (R1.5.2: else
        in the index only, logged), then in the index. Raises WriteError, saying why, when it
        can't be."""
        if entry.hash is None:
            raise WriteError(path, "its audio couldn't be read, so its rating can't be kept")
        if rootfiles.writable(self._musikata):
            try:
                save(file_of(self._root), [entry], self._gone)
            except RatingsError as e:
                raise WriteError(path, e.why) from e
        else:
            log.warning(
                "%s can't be written: the rating of %s is kept in this computer's index only",
                self._musikata,
                entry.path,
            )
        self._index.write(lambda c: load(c, [entry])).result()

    def _gone(self, rel: str) -> bool:
        return not os.path.exists(os.path.join(self._root, *rel.split("/")))


def reread(index: db.Index, root: str) -> int:
    """The root's ratings.json read into the index (at start; when the watcher sees it change),
    merged with what it holds; how many entries it has. One that can't be used leaves what was
    read before."""
    found = read(file_of(root))
    if found is None or found.broken:
        return 0
    entries = found.entries
    index.write(lambda c: load(c, entries)).result()
    return len(entries)
