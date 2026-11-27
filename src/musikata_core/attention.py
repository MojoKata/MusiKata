"""Needs attention (R2.8, A2.6): what MusiKata can help fix, each kind a group, found by queries
over `song` and `album` (the views of A2.6) whose columns the scan keeps as it writes the folders it
touched, so the count is always current without a full pass over the files.

What each group holds:

- **An album whose songs differ** (`ALBUM_DIFFERS`) in album, album artist, year, genre or cover
  (R2.8, R5.6): `album.differs`, the fields, worked out by `differs` whenever the album is
  summarized (albums.refresh_album). An album's songs can differ in its title only in case (A2.1:
  an album is its title, case aside); a song with no cover differs from one with one.
- **No cover, or a small one** (`COVER_NONE`, `COVER_SMALL`, R5.6): an album with no cover, or one
  whose cover is under MIN_SIDE pixels a side; the cover's size is read from its header, once per
  cover: an embedded one's as the song is read (`cover_of`), a folder's image's as the walk finds
  it (`measure`).
- **Names that differ only in case or spacing** (`NAMES_ARTIST`, `NAMES_ALBUM`, `NAMES_GENRE`,
  R2.8, R9.5): an artist's (as artist or album artist) and an album's names whose `name_key` is the
  same, each indexed with the name (`song.artist_nk`, `albumartist_nk`, and the normalised pair of
  album artist and album, `album_nk`); genres as R9.5 groups them (genres.near_duplicates: its key
  sets punctuation and "&"/"and" aside too, and the user's own sames join).
- **An album in one file** (`ONE_FILE`, A2.6): a single audio file of 20 minutes or more with a
  `.cue` sheet beside it that names it (`cued`); it plays as one song, splitting it is #3.
- **The same song more than once** (`COPIES`, R2.12): a group of exact or likely copies
  (duplicates.found), an entry each, about its first copy by path.
- **Tags in the wrong text encoding** (`ENCODING`, R4.10): a song whose text its ID3 tag holds as
  Latin-1 another encoding reads far better (`song.encoding`, kept as it is read, A3.6), an entry
  each, its title and artist as that encoding reads them.
- **Files that couldn't be read** (`UNREADABLE`): `song.error`.

The groups owned by later pieces (tags that differ from the path, R3; playlist entries whose file
is missing, R8.7; files whose tags say nothing, R16.6) join `KINDS` with their own finders.

**Ignore** (R2.8): an entry the user dismisses is kept in the root's `ignored.json`
(rootfiles.Dismissal, A2.8) by its kind and what it is about (a song by its path and audio hash, an
album by its folder, a name by itself, a group of copies by its first copy) with the file's
modification time (the newest of an album's songs or of a group's copies); it stays dismissed until
that time changes (`dismissed`).

Plain functions over plain data (the keys, `differs`, the `.cue` sheet, `dismissed`,
`merge_names`) are tested without an index; the rest reads the index, or, for the covers' sizes and
the `.cue` sheets, the files the walk found."""

from __future__ import annotations

import logging
import os
import sqlite3
import unicodedata
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from . import art, duplicates, encodings, genres
from .rootfiles import Dismissal
from .tags import Picture, Tags
from .tags.tools import Planned, Song

log = logging.getLogger(__name__)

ALBUM_DIFFERS = "album-differs"
COVER_NONE = "cover-none"
COVER_SMALL = "cover-small"
NAMES_ARTIST = "names-artist"
NAMES_ALBUM = "names-album"
NAMES_GENRE = "names-genre"
ONE_FILE = "album-in-one-file"
UNREADABLE = "unreadable"
COPIES = "same-song"  # R2.12
ENCODING = "wrong-encoding"  # R4.10
# every kind this piece finds, in the order the view lists them
KINDS = (COPIES, COVER_NONE, COVER_SMALL, NAMES_ARTIST, NAMES_ALBUM, NAMES_GENRE, ENCODING,
         ALBUM_DIFFERS, ONE_FILE, UNREADABLE)  # fmt: skip
NAMES = (NAMES_ARTIST, NAMES_ALBUM, NAMES_GENRE)
# kinds about a song (a group of copies: its first by path): dismissed by its path and audio hash
BY_SONG = (ONE_FILE, UNREADABLE, COPIES, ENCODING)
BY_ALBUM = (ALBUM_DIFFERS, COVER_NONE, COVER_SMALL)  # kinds about an album: by its folder
FIELDS = ("album", "albumartist", "year", "genre", "cover")  # what an album's songs differ in
MIN_SIDE = 500  # R5.6: a cover smaller than this a side needs attention
ONE_FILE_LENGTH = 20 * 60.0  # A2.6: an album in one file is 20 minutes or more
CUE = ".cue"
HEAD = 256 * 1024  # bytes of an image read for its size: a JPEG's frame header comes after EXIF
SAME_TIME = 1e-6  # seconds within which two modification times are the same (a float's rounding)
CHUNK = 500


# ---------- names (R2.8, R9.5) ----------


def name_key(name: str | None) -> str | None:
    """What two names that differ only in case or spacing share (R2.8): the name composed (NFC,
    so a letter and its mark as macOS names files is the letter), its case folded and every space
    taken out; None for no name. "Lumen Drift", "lumen drift" and "LumenDrift" share one; accents
    and punctuation are kept ("Beyoncé" isn't "Beyonce"; genres set more aside, genres.key)."""
    folded = unicodedata.normalize("NFC", name or "").casefold()
    return "".join(folded.split()) or None


def album_pair(album: str | None, albumartist: str | None, artist: str | None) -> str | None:
    """An album's name as names that differ only in case or spacing share it: its album artist's
    (else its artist's) key and its title's, the normalised pair (A2.6); None for a song on no
    album. Two artists' albums of one title are apart."""
    title = name_key(album)
    if title is None:
        return None
    return f"{name_key(albumartist) or name_key(artist) or ''}\0{title}"


def _order(counts: Mapping[str, int]) -> list[str]:
    """Spellings, the most used first; of those used as often, by name, a capital first (as
    genres' are, R9.5)."""
    return sorted(counts, key=lambda n: (-counts[n], n.casefold(), n))


# ---------- an album's songs (R2.8, R5.6) ----------


@dataclass(frozen=True)
class AlbumSong:
    """What an album's songs differ in, for one of them: its album, album artist, year, genres,
    whether it has a cover embedded and that cover's hash (None: not known)."""

    album: str | None
    albumartist: str | None
    year: int | None
    genres: tuple[str, ...] = ()
    has_cover: bool = False
    cover_key: str | None = None


def differs(songs: Sequence[AlbumSong]) -> tuple[str, ...]:
    """The fields of FIELDS an album's songs don't all share (R2.8): their album title, album
    artist (none counting as one), year, genres (as a whole) or embedded cover (none counting as
    one, a cover not yet known as the same as any other); none for an album of one song."""
    if len(songs) < 2:
        return ()
    values: dict[str, set[object]] = {
        "album": {(s.album or "").strip() for s in songs},
        "albumartist": {(s.albumartist or "").strip() for s in songs},
        "year": {s.year for s in songs},
        "genre": {s.genres for s in songs},
        "cover": {(s.has_cover, s.cover_key) for s in songs},
    }
    return tuple(f for f in FIELDS if len(values[f]) > 1)


def small(width: int | None, height: int | None, min_side: int = MIN_SIDE) -> bool:
    """Whether a cover of that size in pixels is smaller than `min_side` a side (R5.6); a cover
    whose size isn't known isn't."""
    return width is not None and height is not None and min(width, height) < min_side


def cover_of(pictures: Sequence[Picture]) -> tuple[str, int | None, int | None] | None:
    """A song's embedded cover (R5.1's front, art.front) as the index keeps it: its hash and its
    size in pixels from its header (None when it isn't an image it can read); None for no
    cover."""
    front = art.front(pictures)
    if front is None:
        return None
    info = art.sniff(front.data)
    return art.key_of(front.data), info.width if info else None, info.height if info else None


def _read_head(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read(HEAD)


def measure(
    root: str,
    images: dict[str, list[art.Image]],
    known: Mapping[tuple[str, int, int], tuple[int | None, int | None]],
    read_head: Callable[[str], bytes] = _read_head,
) -> int:
    """Each walked folder's cover image (art.folder_cover) given its size in pixels, in `images`:
    as `known` has it for that path, size and modification time (the index's), else read from its
    header (`read_head`, a file under the root by its path); one that can't be read is logged and
    left without. How many were read."""
    read = 0
    for folder, found in images.items():
        cover = art.folder_cover(found)
        if cover is None or cover.width is not None:
            continue
        path = f"{folder}/{cover.name}" if folder else cover.name
        dims = known.get((path, cover.size, cover.mtime_ns))
        if dims is None:
            read += 1
            try:
                info = art.sniff(read_head(os.path.join(root, *path.split("/"))))
            except OSError as e:
                log.warning("couldn't read the size of %s: %s", path, e)
                info = None
            dims = (info.width, info.height) if info else (None, None)
        found[found.index(cover)] = replace(cover, width=dims[0], height=dims[1])
    return read


def known_sizes(c: sqlite3.Connection) -> dict[tuple[str, int, int], tuple[int | None, int | None]]:
    """The sizes in pixels of the folders' cover images the index has read, by path, size and
    modification time: what `measure` needn't read again."""
    return {
        (str(p), int(s), int(m)): (w, h)
        for p, s, m, w, h in c.execute(
            "SELECT folder_image, folder_image_size, folder_image_mtime, folder_image_width,"
            " folder_image_height FROM album WHERE folder_image IS NOT NULL"
            " AND folder_image_width IS NOT NULL"
        )
    }


# ---------- an album in one file (A2.6) ----------


def decode_cue(data: bytes) -> str:
    """A `.cue` sheet's text: UTF-8 (with or without its BOM), else the system's 8-bit encoding
    as Windows' rippers write it (cp1252, Latin-1 where it has no character)."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def cue_files(text: str) -> list[str]:
    """The files a `.cue` sheet names (its `FILE` lines, in order, each once), by their names
    without the folders a ripper may have written before them: `FILE "Live.wav" WAVE`, or
    unquoted, `FILE Live.wav WAVE`. `REM` lines and the rest are passed by."""
    out: list[str] = []
    for line in text.splitlines():
        words = line.strip()
        if words[:5].upper() != "FILE " and words.upper() != "FILE":
            continue
        rest = words[4:].strip()
        if rest.startswith('"'):
            name = rest[1:].split('"', 1)[0]
        else:
            parts = rest.rsplit(None, 1)
            name = parts[0] if len(parts) == 2 else rest
        name = name.replace("\\", "/").rpartition("/")[2].strip()
        if name and name not in out:
            out.append(name)
    return out


def _stem(name: str) -> str:
    return os.path.splitext(name)[0].casefold()


def cued(cues: Mapping[str, str], audio: Iterable[str]) -> dict[str, str]:
    """Which audio files of a folder a `.cue` sheet beside them names, as an album in one file
    (A2.6): {audio file's name: the sheet's name}. A sheet names one file (one naming several
    is of tracks already apart), found by its name, in any case, else by its name without the
    extension (a sheet written for the WAV a FLAC was made from); a sheet naming none stands for
    the file of its own name. `cues`: each sheet's name and its text."""
    names = sorted(audio)
    out: dict[str, str] = {}
    for cue in sorted(cues):
        files = cue_files(cues[cue])
        if len(files) > 1:
            continue
        wanted = files[0] if files else cue
        found = next((n for n in names if n == wanted), None)
        found = found or next((n for n in names if n.casefold() == wanted.casefold()), None)
        found = found or next((n for n in names if _stem(n) == _stem(wanted)), None)
        if found is not None and found not in out:
            out[found] = cue
    return out


def _read_cue(path: str) -> str:
    with open(path, "rb") as f:
        return decode_cue(f.read(1024 * 1024))


def cued_in(
    root: str,
    cues: Mapping[str, Sequence[art.Image]],
    audio: Iterable[str],
    read: Callable[[str], str] = _read_cue,
) -> dict[str, str]:
    """For the walked folders' `.cue` sheets (`cues`: each folder's), the songs (paths under the
    root, of `audio`) a sheet beside them names (`cued`): {song's path: the sheet's name}. A sheet
    that can't be read is logged and passed by."""
    by_folder: dict[str, list[str]] = {}
    for path in audio:
        folder, _, name = path.rpartition("/")
        if cues.get(folder):
            by_folder.setdefault(folder, []).append(name)
    out: dict[str, str] = {}
    for folder, names in by_folder.items():
        texts: dict[str, str] = {}
        for cue in cues[folder]:
            rel = f"{folder}/{cue.name}" if folder else cue.name
            try:
                texts[cue.name] = read(os.path.join(root, *rel.split("/")))
            except OSError as e:
                log.warning("couldn't read %s: %s", rel, e)
        for name, sheet in cued(texts, names).items():
            out[f"{folder}/{name}" if folder else name] = sheet
    return out


def set_cues(c: sqlite3.Connection, folders: Collection[str], found: Mapping[str, str]) -> int:
    """In the writer's transaction: each song in the walked `folders` named by the sheet `found`
    gives it (`cued_in`), the rest by none; how many songs changed."""
    changed = 0
    for path, cue in c.execute("SELECT path, cue FROM song WHERE cue IS NOT NULL").fetchall():
        if path.rpartition("/")[0] in folders and found.get(path) != cue:
            changed += c.execute(
                "UPDATE song SET cue = ? WHERE path = ?", (found.get(path), path)
            ).rowcount
    for path, cue in found.items():
        changed += c.execute(
            "UPDATE song SET cue = ? WHERE path = ? AND cue IS NOT ?", (cue, path, cue)
        ).rowcount
    return changed


# ---------- the entries ----------


@dataclass(frozen=True)
class Entry:
    """Something that needs attention (R2.8): its kind (KINDS) and what it is about, as Ignore
    keeps it (a song's path, an album's folder, a name), and what the view says of it: an album's
    title, artist and cover (its thumbnail's name), and the fields its songs differ in or its
    cover's size; a name's spellings, the most used first, with how many songs have each, and the
    key they share; a song's path, its error or `.cue` sheet and length; a group of copies (R2.12),
    its copies, the one proposed to keep first, whether they are likely ones and why the first is
    kept (duplicates.Group); a song's text in the wrong encoding (R4.10), its title, artist and
    album as the encoding `key` names reads them, the fields it holds so (`fields`) and its
    album's title as read (`album_title`). `hash` and `modified` (the audio hash; the file's
    modification time,
    in seconds, the newest of an album's songs or a group's copies) are what Ignore keeps, so a
    change brings it back."""

    kind: str
    about: str
    title: str = ""
    artist: str = ""
    album: int | None = None
    song: int | None = None
    thumb: str | None = None
    fields: tuple[str, ...] = ()
    width: int | None = None
    height: int | None = None
    names: tuple[str, ...] = ()
    counts: tuple[int, ...] = ()
    key: str = ""
    error: str = ""
    cue: str = ""
    length: float | None = None
    hash: str | None = None
    modified: float | None = None
    copies: tuple[duplicates.Copy, ...] = ()
    likely: bool = False
    why: str = ""
    album_title: str = ""


def _seconds(mtime_ns: int | None) -> float | None:
    return mtime_ns / 1e9 if mtime_ns is not None and mtime_ns >= 0 else None


ALBUM_COLUMNS = (
    "id, title, artist, folder, thumb, (SELECT MAX(mtime_ns) FROM song WHERE album_id = album.id)"
)


def _albums_differ(c: sqlite3.Connection) -> list[Entry]:
    return [
        Entry(ALBUM_DIFFERS, folder, title, artist, i, thumb=thumb,
              fields=tuple(differs_.split(",")), modified=_seconds(m))
        for i, title, artist, folder, thumb, m, differs_ in c.execute(
            f"SELECT {ALBUM_COLUMNS}, differs FROM album WHERE differs IS NOT NULL"
            " ORDER BY artist_key, title_key, id"
        )
    ]  # fmt: skip


def _covers(c: sqlite3.Connection, min_side: int) -> list[Entry]:
    out = []
    for i, title, artist, folder, thumb, m, cover, w, h in c.execute(
        f"SELECT {ALBUM_COLUMNS}, cover, cover_width, cover_height FROM album"
        " WHERE cover IS NULL OR cover_width < ? OR cover_height < ?"
        " ORDER BY artist_key, title_key, id",
        (min_side, min_side),
    ):
        kind = COVER_NONE if cover is None else COVER_SMALL
        out.append(Entry(kind, folder, title, artist, i, thumb=thumb, width=w, height=h,
                         modified=_seconds(m)))  # fmt: skip
    return out


def _chunks(values: Sequence[str]) -> Iterable[tuple[str, ...]]:
    for i in range(0, len(values), CHUNK):
        yield tuple(values[i : i + CHUNK])


def _artist_names(c: sqlite3.Connection) -> list[Entry]:
    """Artists' names (as artist or album artist, R2.5.4) that differ only in case or spacing."""
    keys = [
        str(k)
        for (k,) in c.execute(
            "SELECT nk FROM (SELECT artist_nk AS nk, MIN(artist) AS lo, MAX(artist) AS hi"
            " FROM song WHERE artist_nk IS NOT NULL GROUP BY artist_nk UNION ALL"
            " SELECT albumartist_nk, MIN(albumartist), MAX(albumartist) FROM song"
            " WHERE albumartist_nk IS NOT NULL GROUP BY albumartist_nk)"
            " GROUP BY nk HAVING MIN(lo) <> MAX(hi) ORDER BY nk"
        )
    ]
    spellings: dict[str, dict[str, int]] = {}
    for part in _chunks(keys):
        marks = ", ".join("?" * len(part))
        for k, name, n in c.execute(
            "SELECT nk, name, COUNT(DISTINCT id) FROM (SELECT id, artist_nk AS nk, artist AS name"
            f" FROM song WHERE artist_nk IN ({marks}) UNION ALL SELECT id, albumartist_nk,"
            f" albumartist FROM song WHERE albumartist_nk IN ({marks})) GROUP BY nk, name",
            part + part,
        ):
            spellings.setdefault(str(k), {})[str(name)] = int(n)
    return [_names_entry(NAMES_ARTIST, k, spellings[k]) for k in keys if len(spellings[k]) > 1]


def _album_names(c: sqlite3.Connection) -> list[Entry]:
    """Albums' names (of one album artist) that differ only in case or spacing."""
    keys = [
        str(k)
        for (k,) in c.execute(
            "SELECT album_nk FROM song WHERE album_nk IS NOT NULL GROUP BY album_nk"
            " HAVING MIN(album) <> MAX(album) ORDER BY album_nk"
        )
    ]
    spellings: dict[str, dict[str, int]] = {}
    artists: dict[str, dict[str, int]] = {}
    for part in _chunks(keys):
        marks = ", ".join("?" * len(part))
        for k, name, who, n in c.execute(
            "SELECT album_nk, album, coalesce(albumartist, artist), COUNT(*) FROM song"
            f" WHERE album_nk IN ({marks}) GROUP BY album_nk, album, coalesce(albumartist, artist)",
            part,
        ):
            spellings.setdefault(str(k), {}).setdefault(str(name), 0)
            spellings[str(k)][str(name)] += int(n)
            if who:
                artists.setdefault(str(k), {}).setdefault(str(who), 0)
                artists[str(k)][str(who)] += int(n)
    out = []
    for k in keys:
        if len(spellings[k]) > 1:
            who = _order(artists[k])[0] if artists.get(k) else ""
            out.append(replace(_names_entry(NAMES_ALBUM, k, spellings[k]), artist=who))
    return out


def _names_entry(kind: str, key: str, counts: Mapping[str, int]) -> Entry:
    names = _order(counts)
    return Entry(kind, names[0], names[0], names=tuple(names),
                 counts=tuple(counts[n] for n in names), key=key)  # fmt: skip


def _genre_names(c: sqlite3.Connection, same: Iterable[Iterable[str]]) -> list[Entry]:
    """Genres that look like one (R9.5): genres.near_duplicates, the user's own sames among them."""
    return [
        Entry(NAMES_GENRE, g.chosen, g.chosen, names=g.names, counts=g.counts,
              key=genres.key(g.chosen))
        for g in genres.near_duplicates(genres.counts(c), same)
    ]  # fmt: skip


def _one_file(c: sqlite3.Connection) -> list[Entry]:
    return [
        Entry(ONE_FILE, path, title or "", artist or "", album_id, i, cue=cue, length=length,
              hash=h, modified=_seconds(m))
        for i, path, title, artist, album_id, length, cue, h, m in c.execute(
            "SELECT id, path, album, coalesce(albumartist, artist), album_id, length, cue,"
            " audio_hash, mtime_ns FROM song WHERE cue IS NOT NULL AND length >= ? ORDER BY path",
            (ONE_FILE_LENGTH,),
        )
    ]  # fmt: skip


def copies_entry(g: duplicates.Group) -> Entry:
    """A group of copies (R2.12) as an entry: about its first copy by path (its hash and, of its
    copies, the newest modification time are what Ignore keeps), titled as its kept copy."""
    first = min(g.copies, key=lambda c: c.path)
    times = [c.modified for c in g.copies if c.modified is not None]
    k = g.kept
    return Entry(COPIES, first.path, k.title or k.path.rpartition("/")[2], k.artist, k.album_id,
                 k.song, k.thumb, length=k.length, key=k.key or "", hash=first.hash,
                 modified=max(times) if times else None, copies=g.copies, likely=g.likely,
                 why=g.why)  # fmt: skip


def _copies(c: sqlite3.Connection) -> list[Entry]:
    return [copies_entry(g) for g in duplicates.found(c)]


SONG_ORDER = (
    "disc IS NULL, disc, track IS NULL, track, path"  # albums.ALBUM_ORDER (it imports this)
)
TEXT_COLUMNS = ("title", "artist", "album", "albumartist", "composer", "comment", "artistsort",
                "albumartistsort", "albumsort")  # fmt: skip


def _encoding(c: sqlite3.Connection) -> list[Entry]:
    """Songs whose Latin-1 text another encoding reads far better (R4.10, A3.6), by path: each
    named as that encoding reads it."""
    out = []
    for i, path, title, artist, album, album_id, latin1, codec, h, m, thumb in c.execute(
        "SELECT song.id, song.path, song.title, song.artist, song.album, song.album_id,"
        " song.latin1, song.encoding, song.audio_hash, song.mtime_ns, album.thumb FROM song"
        " LEFT JOIN album ON album.id = song.album_id WHERE song.encoding IS NOT NULL"
        " ORDER BY song.path"
    ):
        names = latin1_of(latin1)
        t, _ = encodings.fixed(Tags(title=title, artist=artist, album=album, latin1=names), codec)
        out.append(
            Entry(
                ENCODING,
                path,
                t.title or path.rpartition("/")[2],
                t.artist or "",
                album_id,
                i,
                thumb,
                fields=names,
                key=str(codec),
                hash=h,
                modified=_seconds(m),
                album_title=t.album or "",
            )  # fmt: skip
        )
    return out


def latin1_of(column: object) -> tuple[str, ...]:
    """A song's `latin1` column as Tags.latin1: the fields by name, NULL none."""
    return tuple(f for f in str(column or "").split(",") if f in TEXT_COLUMNS)


def encoded_songs(c: sqlite3.Connection, ids: Sequence[int]) -> list[tuple[int, str, Tags]]:
    """The songs of `ids` the index has, in that order, each its id, path under the root and
    text fields with those its ID3 tag holds as Latin-1 (Tags.latin1): what Fix encoding… plans
    from (R4.10)."""
    found: dict[int, tuple[int, str, Tags]] = {}
    cols = ", ".join(TEXT_COLUMNS)
    for part in _chunks([str(i) for i in ids]):
        marks = ", ".join("?" * len(part))
        for row in c.execute(
            f"SELECT id, path, latin1, {cols} FROM song WHERE id IN ({marks})", part
        ):
            values = dict(zip(TEXT_COLUMNS, row[3:], strict=True))
            tags = Tags(**values, latin1=latin1_of(row[2]))
            found[int(row[0])] = (int(row[0]), str(row[1]), tags)
    return [found[i] for i in ids if i in found]


def album_songs(c: sqlite3.Connection, song: int) -> list[int]:
    """The songs of the album song `song` is on, in the album's order (it alone when it is on
    none): every song of the album at once (R4.10)."""
    row = c.execute("SELECT album_id FROM song WHERE id = ?", (song,)).fetchone()
    if row is None or row[0] is None:
        return [song]
    return [
        int(i)
        for (i,) in c.execute(
            f"SELECT id FROM song WHERE album_id = ? ORDER BY {SONG_ORDER}", (row[0],)
        )
    ]


def _unreadable(c: sqlite3.Connection) -> list[Entry]:
    return [
        Entry(UNREADABLE, path, path, song=i, error=error, hash=h, modified=_seconds(m))
        for i, path, error, h, m in c.execute(
            "SELECT id, path, error, audio_hash, mtime_ns FROM song WHERE error IS NOT NULL"
            " ORDER BY path"
        )
    ]


def found(
    c: sqlite3.Connection, same: Iterable[Iterable[str]] = (), min_side: int = MIN_SIDE
) -> list[Entry]:
    """Every entry of every group the index holds, in KINDS' order, the dismissed among them:
    the queries of A2.6 over the columns the scan keeps. `same`: the genres the user has said are
    the same (R9.5); `min_side`: a cover smaller than this a side needs attention (R5.6)."""
    covers = _covers(c, min_side)
    by_kind: dict[str, list[Entry]] = {
        COPIES: _copies(c),
        COVER_NONE: [e for e in covers if e.kind == COVER_NONE],
        COVER_SMALL: [e for e in covers if e.kind == COVER_SMALL],
        NAMES_ARTIST: _artist_names(c),
        NAMES_ALBUM: _album_names(c),
        NAMES_GENRE: _genre_names(c, same),
        ENCODING: _encoding(c),
        ALBUM_DIFFERS: _albums_differ(c),
        ONE_FILE: _one_file(c),
        UNREADABLE: _unreadable(c),
    }
    return [e for kind in KINDS for e in by_kind[kind]]


# ---------- Ignore (R2.8, A2.8) ----------


def dismissal_of(entry: Entry, changed: str) -> Dismissal:
    """What Ignore keeps of `entry` (rootfiles.Dismissal), dismissed at `changed`: its kind, what
    it is about, and for a song or an album, its audio hash and the file's modification time."""
    keeps_file = entry.kind in BY_SONG or entry.kind in BY_ALBUM
    return Dismissal(
        entry.kind, entry.about, entry.hash if entry.kind in BY_SONG else None,
        entry.modified if keeps_file else None, changed,
    )  # fmt: skip


def _same_time(a: float | None, b: float | None) -> bool:
    return a is None or (b is not None and abs(a - b) < SAME_TIME)


def dismissed(
    entries: Iterable[Entry], dismissals: Iterable[Dismissal], present: Collection[str] = ()
) -> list[Entry]:
    """The entries the user hasn't dismissed (R2.8): one is dismissed by a dismissal of its kind
    about the same thing (a name by its `name_key`), while its file's modification time is the
    one dismissed; a song's dismissal names it by its path, else by its audio hash when no song
    has that path any more (`present`: the paths of songs there are, of those dismissals name),
    so a song moved keeps its dismissal (A2.8)."""
    by_about: dict[tuple[str, str], Dismissal] = {}
    by_hash: dict[tuple[str, str], Dismissal] = {}
    by_name: dict[tuple[str, str | None], Dismissal] = {}
    for d in dismissals:
        by_about[(d.kind, d.about)] = d
        if d.kind in NAMES:
            by_name[(d.kind, name_key(d.about))] = d
        elif d.hash is not None and d.about not in present:
            by_hash[(d.kind, d.hash)] = d
    out = []
    for e in entries:
        if e.kind in NAMES:
            hit = next((by_name[(e.kind, name_key(n))] for n in e.names
                        if (e.kind, name_key(n)) in by_name), None)  # fmt: skip
        else:
            hit = by_about.get((e.kind, e.about))
            if hit is None and e.hash is not None:
                hit = by_hash.get((e.kind, e.hash))
        if hit is None or not _same_time(hit.modified, e.modified):
            out.append(e)
    return out


def present_of(c: sqlite3.Connection, dismissals: Sequence[Dismissal]) -> set[str]:
    """Of the paths songs' dismissals name, those a song has (`dismissed`)."""
    paths = sorted({d.about for d in dismissals if d.kind in BY_SONG})
    out: set[str] = set()
    for part in _chunks(paths):
        marks = ", ".join("?" * len(part))
        out.update(str(p) for (p,) in c.execute(f"SELECT path FROM song WHERE path IN ({marks})",
                                               part))  # fmt: skip
    return out


def find(
    c: sqlite3.Connection,
    dismissals: Sequence[Dismissal] = (),
    same: Iterable[Iterable[str]] = (),
    min_side: int = MIN_SIDE,
) -> list[Entry]:
    """What needs attention now (R2.8): every group's entries (`found`) but those dismissed
    (`dismissed`)."""
    return dismissed(found(c, same, min_side), dismissals, present_of(c, dismissals))


# ---------- Merge (R2.8): names of artists and albums ----------


def songs_of(c: sqlite3.Connection, kind: str, key: str) -> list[tuple[str, Tags]]:
    """The songs a names entry of `kind` (NAMES_ARTIST or NAMES_ALBUM) with `key` names, by path
    under the root, in path order, with their artist, album artist and album: what a merge plans
    from."""
    params: tuple[str, ...]
    if kind == NAMES_ARTIST:
        where, params = "artist_nk = ? OR albumartist_nk = ?", (key, key)
    elif kind == NAMES_ALBUM:
        where, params = "album_nk = ?", (key,)
    else:
        raise ValueError(f"no merge of names of this kind: {kind}")
    return [
        (str(p), Tags(artist=a, albumartist=aa, album=al))
        for p, a, aa, al in c.execute(
            f"SELECT path, artist, albumartist, album FROM song WHERE {where} ORDER BY path", params
        )
    ]


def merge_names(songs: Sequence[Song], kind: str, names: Collection[str], into: str) -> Planned:
    """R2.8's Merge for an artist's or an album's names: in each song, every one of `names` (as
    artist and album artist, or as album) becomes `into`. The songs that change come first, then
    the rest, each in the order given, so the preview lists the files that change (R3.7)."""
    columns = ("artist", "albumartist") if kind == NAMES_ARTIST else ("album",)
    if kind not in (NAMES_ARTIST, NAMES_ALBUM):
        raise ValueError(f"no merge of names of this kind: {kind}")
    gone = set(names)

    def merged(t: Tags) -> Tags:
        new = {f: into for f in columns if getattr(t, f) in gone and getattr(t, f) != into}
        return replace(t, **new) if new else t  # type: ignore[arg-type]

    pairs = [(s, merged(s.tags)) for s in songs]
    pairs.sort(key=lambda p: p[1] is p[0].tags)  # stable: the changed first, in their order
    return Planned(columns, tuple(s for s, _ in pairs), tuple(t for _, t in pairs))
