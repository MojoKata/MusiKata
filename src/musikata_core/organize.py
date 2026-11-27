"""Organizing files (R12): moving and renaming songs so their paths match their tags, by the
layout of R12.1 (patterns.render), and bringing files from outside the root into it (R12.5).

- **The plan** (`plan`, R12.2 to R12.4): each song's new path under the layout (`target`); a song
  already there left alone, one with no tags at all left too (Infer from path comes first); the
  files beside an album's songs (`SIDECARS`: images, `.cue`, `.lrc`, `.log`) moved into the album's
  new folder once every song of their folder leaves it, and a song's own `.lrc` with the song,
  renamed as it is; the folders the moves leave empty (`Plan.emptied`). Two files to one path are
  both a conflict (TWICE), and so is a file already at the new path (TAKEN): neither moves until
  one changes or is unchecked. Paths are compared as every platform's file systems may: composed
  and case aside, so a plan made on Linux holds on Windows and macOS.
- **The move** (`move_file`, a tags.Batch's writer): a rename within the root's file system,
  `os.replace` with the folder made first, never over a file (a case-only rename of the file
  itself excepted); so Organize files is a batch like any save, its progress, Cancel between files,
  each failure with why, and its change-history entry (history.Recording, the moves' `from`).
  `prune` removes the folders left empty.
- **Following a move** (`index_moves`): the songs' rows keep their ids and take their new paths,
  so their plays, ratings, history and place in the queue follow (A2.8); albums and folders are
  summarized again (A2.7). The playlists naming a file moved are pointed at its new path by
  playlists.Store.repoint (R8.7).
- **Adding from outside** (R12.5): `outside_songs` lists the audio files of the files and folders
  dropped, `read_outside` reads each one's tags and audio hash, `known` finds those whose audio the
  library has already (A2.3), and `add_file` copies or moves one into its place, its tags filled
  from its path when asked (Infer from path); `index_added` puts them in the index.

The plan and the paths are plain functions over plain data; what touches the disk takes the root
and works on the calling thread, never the GUI's."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sqlite3
import unicodedata
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from . import albums, art, folders, patterns, rootfiles, scanner, search, sortnames
from .patterns import Pattern
from .tags import EXTENSIONS, Job, Tags, WriteError, Written
from .tags import read as read_tags
from .tags.safe import reason, tmp_path

log = logging.getLogger(__name__)

# R12.3: what moves with an album's songs into its new folder
SIDECARS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".cue", ".lrc", ".log")
LYRICS = ".lrc"  # a song's own lyrics, named as it is (R17.1), follow it renamed
# what a system leaves in a folder of its own accord: a folder holding nothing else is empty
CLUTTER = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
TWICE = "twice"  # R12.4: another file of the plan gets the same path
TAKEN = "taken"  # R12.4: a file is at the new path already
MOVE = "move"  # a move's Job: its changes name the whole path it goes to
HASH = "hash"  # and the file's audio hash, for the change history (A3.5)
FIELDS = "fields"  # an added file's tags filled from its path (R12.5), written once it is placed
CHUNK = 500


# ---------- the plan (R12.2 to R12.4) ----------


@dataclass(frozen=True)
class Source:
    """A song to place: its id (0 for a file not in the library yet, R12.5), its path (under the
    root with `/`, or a whole path outside it), its tags, how many discs its album has (R12.1's
    `{disc-}`) and its audio hash (A2.3; None: not known)."""

    song: int
    path: str
    tags: Tags
    discs: int = 1
    hash: str | None = None


@dataclass(frozen=True)
class Move:
    """A file to move: from `old` to `new` (paths as Source's), its song (None: a file beside the
    songs, R12.3), its audio hash, whether it is checked, and its conflict ("": none; TWICE or
    TAKEN, R12.4); one unchecked has none, as it doesn't move."""

    old: str
    new: str
    song: int | None = None
    hash: str | None = None
    checked: bool = True
    conflict: str = ""

    @property
    def ready(self) -> bool:
        """Whether it moves: checked, with no conflict."""
        return self.checked and not self.conflict


@dataclass(frozen=True)
class Plan:
    """What Organize files would do: the moves, songs first in the order given and then the
    files beside them; how many songs are already where they belong (`in_place`); the songs left
    where they are for having no tags at all (`untagged`); and the folders the moves leave empty,
    the deepest first (`emptied`)."""

    moves: tuple[Move, ...] = ()
    in_place: int = 0
    untagged: tuple[str, ...] = ()
    emptied: tuple[str, ...] = ()

    @property
    def chosen(self) -> list[Move]:
        """The moves that will be made: checked, with no conflict."""
        return [m for m in self.moves if m.ready]

    @property
    def conflicts(self) -> list[Move]:
        """The checked moves that wait on a conflict (R12.4)."""
        return [m for m in self.moves if m.checked and m.conflict]


def folder_of(path: str) -> str:
    """The folder a path (with `/`) is in; "" for the root's own files."""
    return path.rpartition("/")[0]


def name_of(path: str) -> str:
    return path.rpartition("/")[2]


def same_path(a: str, b: str) -> bool:
    """Whether two paths name one file on every platform: composed (NFC) and case aside, as
    Windows' and macOS's file systems compare names."""
    return unicodedata.normalize("NFC", a).casefold() == unicodedata.normalize("NFC", b).casefold()


def _key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def target(
    layout: Pattern, source: Source, articles: Sequence[str] = sortnames.ARTICLES
) -> str | None:
    """Where `source` belongs under `layout` (R12.1): its path under the root; None for a song
    with no tags at all, which no layout can place (Infer from path comes first, R3)."""
    if not patterns.has_tags(source.tags):
        return None
    stem, ext = os.path.splitext(name_of(source.path))
    values = patterns.values_for(source.tags, source.discs, articles)
    return patterns.render(layout, values, stem, ext.lower() if ext.lower() in EXTENSIONS else ext)


def _sidecar(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in SIDECARS


def _audio(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in EXTENSIONS


def plan(
    sources: Sequence[Source],
    layout: Pattern,
    beside: Mapping[str, Collection[str]],
    exists: Callable[[str], bool],
    unchecked: Collection[str] = frozenset(),
    articles: Sequence[str] = sortnames.ARTICLES,
    prune: bool = True,
) -> Plan:
    """Organize files' plan (R12.2 to R12.4) of `sources` under `layout`: each song's move, those
    already where they belong (`same_path`) left alone, those with no tags left too; the files
    beside the songs (R12.3) of each folder in `beside` (each folder's entries by name, a
    subfolder's with "/" after it, for the folders the songs are in and those above them under the
    root) moved into the album's new folder (where most of its songs go) when every song of the
    folder leaves it, a song's own `.lrc` with the song, renamed as it is; the moves whose old
    path is in `unchecked` not made. Two moves to one path are both TWICE, a move to a path
    `exists` says is taken TAKEN (the file itself excepted, renamed in case alone). The folders
    left empty, but the root, when `prune` (never outside the root, R12.5)."""
    songs: list[Move] = []
    in_place = 0
    untagged: list[str] = []
    for s in sources:
        new = target(layout, s, articles)
        if new is None:
            untagged.append(s.path)
        elif unicodedata.normalize("NFC", new) == unicodedata.normalize("NFC", s.path):
            in_place += 1
        else:
            songs.append(Move(s.path, new, s.song, s.hash, s.path not in unchecked))
    moves = songs + _sidecars(songs, beside, unchecked)
    moves = _conflicts(moves, exists)
    emptied = _emptied([m for m in moves if m.ready], beside) if prune else ()
    return Plan(tuple(moves), in_place, tuple(untagged), emptied)


def _sidecars(
    songs: Sequence[Move], beside: Mapping[str, Collection[str]], unchecked: Collection[str]
) -> list[Move]:
    """R12.3: the files beside the songs that move with them."""
    leaving: dict[str, list[Move]] = {}
    for m in songs:
        if m.checked:
            leaving.setdefault(folder_of(m.old), []).append(m)
    out: list[Move] = []
    for folder, gone in leaving.items():
        names = beside.get(folder, ())
        by_stem = {os.path.splitext(name_of(m.old))[0]: m for m in gone}
        moving = {name_of(m.old) for m in gone}
        whole = not any(_audio(n) and not n.endswith("/") and n not in moving for n in names)
        dest = Counter(folder_of(m.new) for m in gone).most_common(1)[0][0]
        for n in sorted(names):
            if n.endswith("/") or not _sidecar(n):
                continue
            stem, ext = os.path.splitext(n)
            old = f"{folder}/{n}" if folder else n
            song = by_stem.get(stem) if ext.lower() == LYRICS else None
            if song is not None:  # the song's own lyrics, named as it is now
                new = f"{os.path.splitext(song.new)[0]}{ext}"
            elif whole:
                new = f"{dest}/{n}" if dest else n
            else:
                continue
            if new != old:
                out.append(Move(old, new, None, None, old not in unchecked))
    return out


def _conflicts(moves: Sequence[Move], exists: Callable[[str], bool]) -> list[Move]:
    """R12.4: the checked moves to one path TWICE, and those to a path taken TAKEN."""
    counts = Counter(_key(m.new) for m in moves if m.checked)
    out = []
    for m in moves:
        conflict = ""
        if m.checked and counts[_key(m.new)] > 1:
            conflict = TWICE
        elif m.checked and not same_path(m.old, m.new) and exists(m.new):
            conflict = TAKEN
        out.append(replace(m, conflict=conflict))
    return out


def _emptied(moves: Sequence[Move], beside: Mapping[str, Collection[str]]) -> tuple[str, ...]:
    """The folders of `beside` the moves leave with nothing in them but a system's clutter, the
    deepest first; never the root, nor a folder a move goes into."""
    leaving: dict[str, set[str]] = {}
    arriving: set[str] = set()
    for m in moves:
        leaving.setdefault(folder_of(m.old), set()).add(name_of(m.old))
        folder = folder_of(m.new)
        while folder:
            arriving.add(_key(folder))
            folder = folder_of(folder)
    out: list[str] = []
    gone: set[str] = set()
    for f in sorted(beside, key=lambda p: (-p.count("/"), p)):
        if not f or _key(f) in arriving:
            continue
        left = [
            n for n in beside[f]
            if n not in leaving.get(f, ()) and n.casefold() not in CLUTTER
            and not (n.endswith("/") and f"{f}/{n[:-1]}" in gone)
        ]  # fmt: skip
        if not left:
            gone.add(f)
            out.append(f)
    return tuple(out)


# ---------- the move (R12.4) ----------


@dataclass(frozen=True)
class Moved:
    """A file moved (or placed, R12.5): its whole path now and before, its audio hash (None: not
    known, or a file beside the songs), and, for a file brought in from outside whose tags were
    filled from its path, the save that wrote them (`written`)."""

    path: str
    old: str
    hash: str | None = None
    written: Written | None = None


def move_job(root: str, m: Move) -> Job:
    """The batch's job of one move under `root`."""
    return Job(scanner.full_path(root, m.old), {MOVE: scanner.full_path(root, m.new), HASH: m.hash})


def _taken(old: str, new: str) -> bool:
    """Whether a file other than the one at `old` is at `new` (a case-only rename on a file
    system that sets case aside finds the file itself there)."""
    if not os.path.lexists(new):
        return False
    try:
        return not os.path.samefile(old, new)
    except OSError:
        return True


def move_file(job: Job) -> Moved:
    """A move (R12.4): the file at `job.path` renamed to the whole path its changes name (MOVE),
    within its file system, the folder made first, never over another file. Raises WriteError,
    the file left where it was, when it can't be."""
    new = str(job.changes[MOVE])
    digest = job.changes.get(HASH)
    if not os.path.lexists(job.path):
        raise WriteError(job.path, "it isn't there any more")
    if _taken(job.path, new):
        raise WriteError(job.path, f"a file is at {name_of(new.replace(os.sep, '/'))} already")
    try:
        os.makedirs(os.path.dirname(new), exist_ok=True)
        os.replace(job.path, new)
    except OSError as e:
        raise WriteError(job.path, _why(e)) from e
    log.info("moved %s to %s", job.path, new)
    return Moved(new, job.path, digest if isinstance(digest, str) else None)


def _why(e: OSError) -> str:
    """Why a move or a copy failed, in words a person can act on."""
    if e.errno == 18:  # EXDEV: a folder joined by a link, on another drive (R2.3.2)
        return "its new folder is on another drive: move it by hand"
    return reason(e, "replacing")


def prune(root: str, left: Iterable[str]) -> list[str]:
    """The folders under `root` that files left (`left`, paths under it) and those above them,
    each removed when nothing is in it but a system's clutter (CLUTTER, removed with it), the
    deepest first; never the root. An empty folder holds nothing to get back, and Undo makes it
    again as it moves a file into it, so it is removed, not moved to the trash. The folders
    removed; one that can't be is logged and stays."""
    every: set[str] = set()
    for f in left:
        while f:
            every.add(f)
            f = folder_of(f)
    removed = []
    for f in sorted(every, key=lambda p: (-p.count("/"), p)):
        path = scanner.full_path(root, f)
        try:
            names = os.listdir(path)
        except OSError:
            continue
        if any(n.casefold() not in CLUTTER for n in names):
            continue
        try:
            for n in names:
                os.remove(os.path.join(path, n))
            os.rmdir(path)
        except OSError as e:
            log.warning("couldn't remove the empty folder %s: %s", path, e)
            continue
        removed.append(f)
    if removed:
        log.info("removed %d folders left empty: %s", len(removed), ", ".join(removed))
    return removed


# ---------- following a move: the index (A2.8) ----------


def images_in(root: str, places: Iterable[str]) -> dict[str, list[art.Image]]:
    """Each folder's images (art.Image), as a scan's walk notes them, for its cover (A2.7); a
    folder that isn't there has none."""
    out: dict[str, list[art.Image]] = {}
    for f in set(places):
        found: list[art.Image] = []
        try:
            with os.scandir(scanner.full_path(root, f)) as it:
                for e in it:
                    if e.is_file() and art.is_image(e.name):
                        st = e.stat()
                        found.append(art.Image(e.name, st.st_size, st.st_mtime_ns))
        except OSError:
            pass
        out[f] = found
    return out


def index_moves(
    c: sqlite3.Connection,
    moves: Sequence[tuple[str, str]],
    images: Mapping[str, Sequence[art.Image]] | None = None,
) -> int:
    """In the writer's transaction: the songs at each old path (under the root) of `moves` given
    their new one, each keeping its row and id, so what hangs on it follows (A2.8): this computer's
    plays name it anew (rootfiles.moved), its rating, waveform and place in the queue stay with
    its id, and the history and the other computers find it by its audio hash. A row left at a new
    path (a file gone since the last scan) is taken out first. Their albums, artists, search rows
    and folders (`images`, each folder's) summarized again. How many songs it moved."""
    touched = albums.Touched()
    places: set[str] = set()
    moved: list[int] = []
    for old, new in moves:
        row = c.execute("SELECT id FROM song WHERE path = ?", (old,)).fetchone()
        if row is None:
            continue  # a file beside the songs, or one the index hasn't
        if c.execute("SELECT 1 FROM song WHERE path = ?", (new,)).fetchone():
            albums.forget(c, [new], touched)
            search.forget(c, [new])
            c.execute("DELETE FROM song WHERE path = ?", (new,))
        c.execute(
            "UPDATE song SET path = ?, folder = ?, name_key = ? WHERE id = ?",
            (new, folder_of(new), sortnames.key_of(name_of(new)), row[0]),
        )
        albums.place(c, row[0], touched)
        rootfiles.moved(c, row[0])
        moved.append(int(row[0]))
        places.update((folder_of(old), folder_of(new)))
    search.index_songs(c, moved)
    albums.refresh(c, touched, images)
    places |= albums.folders_of(c, touched.albums)
    folders.refresh(c, places, images)
    return len(moved)


def pairs_of(root: str, saved: Iterable[object]) -> list[tuple[str, str]]:
    """The moves a batch made (its Moved), as (old, new) paths under `root`; a file outside it
    left out."""
    out = []
    for m in saved:
        if not isinstance(m, Moved):
            continue
        old, new = scanner.path_under(root, m.old), scanner.path_under(root, m.path)
        if old is not None and new is not None:
            out.append((old, new))
    return out


@dataclass
class Followed:
    """What following a batch's moves did: the songs whose rows moved, the playlists pointed at
    the new paths, the folders removed left empty, and what failed (each step's failure logged,
    the steps after it still run)."""

    songs: int = 0
    playlists: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


class Follower:
    """What follows files MusiKata moved (R12.4): the index (`index_moves`, through `write`, the
    writer thread's), the playlists naming them (`repoint`, playlists.Store.repoint; None: none
    are changed), and the folders they left removed when empty (`prune`). Organize files and the
    Undo of one call it once their batch has run, on their own thread."""

    def __init__(
        self,
        root: str,
        write: Callable[[Callable[[sqlite3.Connection], object]], object],
        repoint: Callable[[Mapping[str, str]], list[str]] | None = None,
    ) -> None:
        self.root, self._write, self._repoint = root, write, repoint

    def __call__(self, moves: Sequence[tuple[str, str]], prune_left: bool = True) -> Followed:
        out = Followed()
        if not moves:
            return out
        places = {folder_of(p) for pair in moves for p in pair}
        images = images_in(self.root, places)
        try:
            done = self._write(lambda c: index_moves(c, moves, images))
            out.songs = done if isinstance(done, int) else 0
        except Exception:  # noqa: BLE001  (logged: the next scan finds the moves by their hash)
            log.exception("the index didn't follow the files moved in %s", self.root)
            out.failed.append("the library")
        if self._repoint is not None:
            try:
                out.playlists = self._repoint(dict(moves))
            except Exception:  # noqa: BLE001  (logged: the playlists show the entries missing)
                log.exception("the playlists naming the files moved weren't changed")
                out.failed.append("the playlists")
        if prune_left:
            out.removed = prune(self.root, {folder_of(old) for old, _ in moves})
        return out


# ---------- what the plan is made from: the index and the disk ----------


def sources_of(c: sqlite3.Connection, ids: Sequence[int]) -> list[Source]:
    """The songs of `ids` the index has, in that order, as Organize files places them: their
    paths, tags (those a layout reads, R12.1), their albums' disc counts and audio hashes."""
    wanted = list(dict.fromkeys(int(i) for i in ids))
    found: dict[int, Source] = {}
    columns = ("title", "artist", "album", "albumartist", "track", "tracktotal", "disc",
               "disctotal", "year", "compilation", "artistsort", "albumartistsort",
               "albumsort")  # fmt: skip
    for n in range(0, len(wanted), CHUNK):
        part = wanted[n : n + CHUNK]
        marks = ", ".join("?" * len(part))
        genres: dict[int, list[str]] = {}
        for song, genre in c.execute(
            f"SELECT song_id, genre FROM song_genre WHERE song_id IN ({marks})"
            " ORDER BY song_id, position",
            part,
        ):
            genres.setdefault(int(song), []).append(str(genre))
        for row in c.execute(
            f"SELECT id, path, audio_hash, {', '.join(columns)},"
            " (SELECT max(coalesce(max(o.disc), 1), coalesce(max(o.disctotal), 1)) FROM song"
            " AS o WHERE o.album_id = song.album_id)"
            f" FROM song WHERE id IN ({marks})",
            part,
        ):
            values = dict(zip(columns, row[3:-1], strict=True))
            values["compilation"] = bool(values["compilation"])
            tags = Tags(**values, genres=tuple(genres.get(int(row[0]), ())))
            found[int(row[0])] = Source(int(row[0]), str(row[1]), tags, int(row[-1] or 1), row[2])
    return [found[i] for i in wanted if i in found]


def listing(root: str, paths: Iterable[str]) -> dict[str, list[str]]:
    """What `plan` takes as `beside`: the entries of the folders the files at `paths` (under the
    root) are in, and of each folder above them under the root, by name, a subfolder's with "/"
    after it; a folder that can't be listed holds what it can't say, so it is never taken for
    empty."""
    every: set[str] = set()
    for p in paths:
        f = folder_of(p)
        while f:
            every.add(f)
            f = folder_of(f)
        every.add("")
    out: dict[str, list[str]] = {}
    for f in every:
        try:
            with os.scandir(scanner.full_path(root, f)) as it:
                out[f] = [e.name + "/" if e.is_dir() else e.name for e in it]
        except OSError as e:
            log.warning("couldn't list %s: %s", f, e)
            out[f] = ["?"]
    return out


def taken_in(root: str) -> Callable[[str], bool]:
    """Whether a file is at a path under `root` (R12.4's TAKEN)."""
    return lambda path: os.path.lexists(scanner.full_path(root, path))


def playlists_naming(c: sqlite3.Connection, paths: Iterable[str]) -> dict[str, list[str]]:
    """Of `paths` (under the root), each that a playlist names, with the names of the playlists
    naming it: those a move of it updates (R12.4, R8.7), which the dialog says."""
    wanted = sorted(set(paths))
    out: dict[str, list[str]] = {}
    for n in range(0, len(wanted), CHUNK):
        part = wanted[n : n + CHUNK]
        marks = ", ".join("?" * len(part))
        for path, name in c.execute(
            "SELECT DISTINCT playlist_entry.path, playlist.name FROM playlist JOIN playlist_entry"
            " ON playlist_entry.playlist_id = playlist.id WHERE playlist_entry.path IN"
            f" ({marks}) ORDER BY playlist.name_key",
            part,
        ):
            out.setdefault(str(path), []).append(str(name))
    return out


# ---------- adding files from outside the root (R12.5) ----------


def outside_songs(paths: Iterable[str], walk: Callable[[str], Iterable[str]] | None = None
                  ) -> list[tuple[str, str]]:  # fmt: skip
    """The audio files of the files and folders dropped (whole paths), each once, in the order
    dropped, a folder's beneath it by path: each with its path from the folder dropped (the
    folder's own name first), as Infer from path reads it (R3)."""
    walk = walk or _walk
    out: dict[str, str] = {}
    for p in paths:
        p = p.rstrip("/\\") or p
        if os.path.isdir(p):
            base = os.path.dirname(p)
            for f in sorted(walk(p)):
                if _audio(f):
                    out.setdefault(f, os.path.relpath(f, base).replace(os.sep, "/"))
        elif _audio(p):
            out.setdefault(p, os.path.basename(p))
    return list(out.items())


def _walk(folder: str) -> Iterable[str]:
    for top, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        yield from (os.path.join(top, f) for f in files if not f.startswith("."))


@dataclass(frozen=True)
class Outside:
    """A file from outside the root: its whole path, its path from the folder dropped (Infer from
    path's), its tags, size and audio hash; or why it couldn't be read (`error`)."""

    path: str
    named: str
    tags: Tags = field(default_factory=Tags)
    size: int = 0
    hash: str | None = None
    error: str = ""


def read_outside(path: str, named: str) -> Outside:
    """A file from outside the root, read: its tags, size and audio hash (A2.3); why not when it
    can't be."""
    try:
        tags, info = read_tags(path)
        digest = scanner.audio_hash(path, info.kind)
        return Outside(path, named, tags, os.path.getsize(path), digest)
    except Exception as e:  # noqa: BLE001  (a file no reader expected: reported, the rest added)
        log.warning("couldn't read %s, dropped from outside: %s", path, e)
        return Outside(path, named, error=str(e) or type(e).__name__)


def known(c: sqlite3.Connection, hashes: Iterable[str]) -> dict[str, str]:
    """Of `hashes` (A2.3), those whose audio a song of the library has: the hash and that song's
    path (R12.5: not added twice)."""
    wanted = sorted({h for h in hashes if h})
    out: dict[str, str] = {}
    for n in range(0, len(wanted), CHUNK):
        part = wanted[n : n + CHUNK]
        marks = ", ".join("?" * len(part))
        for h, p in c.execute(
            f"SELECT audio_hash, min(path) FROM song WHERE audio_hash IN ({marks})"
            " GROUP BY audio_hash",
            part,
        ):
            out[str(h)] = str(p)
    return out


def add_job(root: str, m: Move, fields: Mapping[str, object] | None = None) -> Job:
    """The batch's job of placing a file from outside (`m.old`, a whole path) at `m.new` (under
    `root`), with the tags to fill (`fields`, R12.5's Infer from path; None: none)."""
    changes: dict[str, object] = {MOVE: scanner.full_path(root, m.new), HASH: m.hash}
    if fields:
        changes[FIELDS] = dict(fields)
    return Job(m.old, changes)


def add_file(job: Job, copy: bool, write: Callable[[Job], Written] | None = None) -> Moved:
    """A file from outside placed in the library (R12.5): copied (`copy`) to a copy beside its
    place and renamed into it, so no half a file is ever there, or moved (renamed, or copied and
    the original removed when it is on another drive); never over a file. Its tags filled from
    its path (FIELDS) are written then with `write` (safe.save). Raises WriteError, nothing left
    in the library, when it can't be placed; a file placed whose tags couldn't be written stays,
    its tags as they were, and the log says so."""
    new = str(job.changes[MOVE])
    digest = job.changes.get(HASH)
    if not os.path.exists(job.path):
        raise WriteError(job.path, "it isn't there any more")
    if os.path.lexists(new):
        raise WriteError(job.path, f"a file is at {os.path.basename(new)} already")
    try:
        os.makedirs(os.path.dirname(new), exist_ok=True)
        if not copy:
            try:
                os.rename(job.path, new)
            except OSError as e:
                if e.errno != 18:  # EXDEV: another drive, copied below
                    raise
                copy = True
                _copy(job.path, new)
                os.remove(job.path)
        else:
            _copy(job.path, new)
    except OSError as e:
        raise WriteError(job.path, _why(e)) from e
    log.info("%s %s into the library as %s", "copied" if copy else "moved", job.path, new)
    written = None
    fields = job.changes.get(FIELDS)
    if isinstance(fields, Mapping) and fields and write is not None:
        try:
            written = write(Job(new, fields))
        except Exception as e:  # noqa: BLE001  (the file is in; its tags stay as they were)
            log.warning("the tags of %s, added to the library, weren't filled: %s", new, e)
    return Moved(new, job.path, digest if isinstance(digest, str) else None, written)


def _copy(src: str, dst: str) -> None:
    """`src` copied to `dst` through a copy beside it, renamed into place once whole."""
    tmp = tmp_path(dst)
    try:
        shutil.copy2(src, tmp)
        if os.path.lexists(dst):
            raise FileExistsError(dst)
        os.replace(tmp, dst)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def index_added(c: sqlite3.Connection, reads: list[scanner.Read], added: float,
                images: Mapping[str, list[art.Image]] | None = None) -> list[int]:  # fmt: skip
    """In the writer's transaction: the files brought into the library (R12.5), as read
    (scanner.read_one), indexed as a scan's batch would (added at `added`); their ids, in order."""
    scanner.write_batch(c, reads, {}, images, added)
    out = []
    for r in reads:
        row = c.execute("SELECT id FROM song WHERE path = ?", (r.seen.path,)).fetchone()
        if row is not None:
            out.append(int(row[0]))
    return out
