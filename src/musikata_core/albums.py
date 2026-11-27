"""Albums, compilations and artists (R2.5), kept in the index's `album` and `artist` tables (A2.1)
by the scan, in the same transaction as the songs it touches (A2.2).

- An **album** is the songs that share an album artist and an album title, case aside; a song
  without an album artist uses its artist (R2.5.2).
- A **compilation** is an album whose songs have different artists and the compilation flag, or
  whose album artist is "Various Artists". Songs flagged as a compilation that name no album
  artist are grouped by their title and folder, as they have no album artist to match (R2.5.2),
  and listed under "Various Artists", so a compilation is listed once (R2.5.3).
- An **artist** is anyone named as a song's artist or an album's artist; names that differ only in
  case are one artist, shown in their most common spelling (R2.5.4).

What an album or artist row says (its shown names, sort keys, year, genre, counts and cover) is
worked out by plain functions over its songs (`summarize`, `name_of`), tested without an index; the
rest reads and writes the rows."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from . import art, attention, sortnames

VARIOUS = "Various Artists"  # a compilation's album artist when its songs name none (R2.5.3)
FLAGGED = "\x01"  # before the folder, the album-artist part of the identity of such a compilation


def album_identity(
    album: str | None,
    albumartist: str | None,
    artist: str | None,
    compilation: bool,
    folder: str,
) -> str | None:
    """Which album a song in `folder` is on (R2.5.2, R2.5.3): its album artist (or else its
    artist) and album title, case aside, or for a song flagged as a compilation that names no
    album artist, its folder and album title; None for a song with no album title."""
    title = (album or "").strip()
    if not title:
        return None
    if (albumartist or "").strip():
        who = (albumartist or "").strip().casefold()
    elif compilation:
        who = FLAGGED + folder
    else:
        who = (artist or "").strip().casefold()
    return f"{who}\0{title.casefold()}"


def artist_identity(name: str | None) -> str | None:
    """Which artist a name is (R2.5.4): the name, case aside; None for no name."""
    name = (name or "").strip()
    return name.casefold() if name else None


def most_common(values: Iterable[str | None]) -> str | None:
    """The value given most often, the first of those given as often; None when there is none."""
    counted = Counter(v for v in values if v)
    if not counted:
        return None
    top = max(counted.values())
    return next(v for v in counted if counted[v] == top)


@dataclass(frozen=True)
class Song:
    """What an album's row is made from, for one of its songs, in the album's order."""

    path: str
    artist: str | None
    albumartist: str | None
    album: str
    compilation: bool
    year: int | None
    length: float | None
    size: int
    mtime_ns: int
    has_cover: bool
    albumartistsort: str | None = None
    artistsort: str | None = None
    albumsort: str | None = None
    cover_key: str | None = None  # its embedded cover's hash and size (attention.cover_of)
    cover_width: int | None = None
    cover_height: int | None = None


@dataclass(frozen=True)
class Album:
    """An album's row (A2.1): its names as shown and their sort keys (R2.13), whether it is a
    compilation, the year and genre most of its songs have, its counts, the folder most of its
    songs are in and that folder's cover image, and the cover shown (R5.1: embedded, else the
    folder's) with the name of its thumbnail."""

    artist: str
    title: str
    artist_key: str
    title_key: str
    compilation: bool
    year: int | None
    genre: str | None
    songs: int
    length: float
    size: int
    embedded: int  # songs with a picture embedded
    folder: str
    folder_image: str | None  # its path under the root
    folder_image_size: int | None
    folder_image_mtime: int | None
    cover_kind: str | None  # "embedded" (in the song at `cover`), "file" or None
    cover: str | None
    thumb: str | None


def folder_of(path: str) -> str:
    """The folder of a path under the root ("" for the root itself)."""
    return path.rpartition("/")[0]


def summarize(
    songs: Sequence[Song],
    genres: Iterable[str],
    folder_image: tuple[str, int, int] | None,
    articles: Sequence[str] = sortnames.ARTICLES,
) -> Album:
    """An album's row from its songs (in the album's order, at least one), all its songs' genres,
    and its folder's cover image (path, size, modification time) if it has one."""
    artists = {a.casefold() for s in songs if (a := (s.artist or "").strip())}
    named = most_common((s.albumartist or "").strip() for s in songs)
    flagged = any(s.compilation for s in songs)
    if named:
        shown = named
    elif flagged and len(artists) > 1:
        shown = VARIOUS
    else:
        shown = most_common((s.artist or "").strip() for s in songs) or ""
    compilation = (flagged and len(artists) > 1) or shown.casefold() == VARIOUS.casefold()
    title = most_common(s.album.strip() for s in songs) or ""
    artist_sort = most_common(s.albumartistsort for s in songs)
    if not named and not compilation:
        artist_sort = artist_sort or most_common(s.artistsort for s in songs)
    years = Counter(s.year for s in songs if s.year)
    folder = most_common(folder_of(s.path) for s in songs) or ""
    cover_song = next((s for s in songs if s.has_cover), None)
    kind: str | None
    cover: str | None
    thumb: str | None
    if cover_song is not None:
        kind, cover = "embedded", cover_song.path
        thumb = art.thumb_id(cover, cover_song.size, cover_song.mtime_ns)
    elif folder_image is not None:
        kind, cover = "file", folder_image[0]
        thumb = art.thumb_id(cover, folder_image[1], folder_image[2])
    else:
        kind = cover = thumb = None
    return Album(
        artist=shown,
        title=title,
        artist_key=sortnames.sort_key(shown, artist_sort, articles) or "",
        title_key=sortnames.sort_key(title, most_common(s.albumsort for s in songs), articles)
        or "",
        compilation=compilation,
        year=min(years, key=lambda y: (-years[y], y)) if years else None,
        genre=most_common(genres),
        songs=len(songs),
        length=sum(s.length or 0.0 for s in songs),
        size=sum(s.size for s in songs),
        embedded=sum(s.has_cover for s in songs),
        folder=folder,
        folder_image=folder_image[0] if folder_image else None,
        folder_image_size=folder_image[1] if folder_image else None,
        folder_image_mtime=folder_image[2] if folder_image else None,
        cover_kind=kind,
        cover=cover,
        thumb=thumb,
    )


def name_of(spellings: Mapping[str, int]) -> str:
    """An artist's name as shown (R2.5.4): the spelling used most (by songs), the first of those
    used as often in sorted order, so the choice doesn't depend on the order songs were read."""
    top = max(spellings.values())
    return min(s for s, n in spellings.items() if n == top)


# ---------- the rows ----------

# an album's songs in order: by disc and track, those without either last
ALBUM_ORDER = "disc IS NULL, disc, track IS NULL, track, path"
SONG_COLUMNS = (
    "path, artist, albumartist, album, compilation, year, length, size, mtime_ns, has_cover,"
    " albumartistsort, artistsort, albumsort, cover_key, cover_width, cover_height"
)


def _get_or_add(c: sqlite3.Connection, table: str, identity: str) -> int:
    row = c.execute(f"SELECT id FROM {table} WHERE identity = ?", (identity,)).fetchone()
    if row:
        return int(row[0])
    if table == "album":
        c.execute(
            "INSERT INTO album (identity, artist, title, artist_key, title_key, folder)"
            " VALUES (?, '', '', '', '', '')",
            (identity,),
        )
    else:
        c.execute("INSERT INTO artist (identity, name, sort_key) VALUES (?, '', '')", (identity,))
    return int(c.execute("SELECT last_insert_rowid()").fetchone()[0])


class Touched:
    """The albums and artists a write changed, to be summarized again before it commits."""

    def __init__(self) -> None:
        self.albums: set[int] = set()
        self.artists: set[int] = set()

    def add(self, album: int | None, artist: int | None) -> None:
        if album is not None:
            self.albums.add(album)
        if artist is not None:
            self.artists.add(artist)


def place(c: sqlite3.Connection, song_id: int, touched: Touched) -> None:
    """Puts a song just written on its album and under its artist (R2.5), and its sort keys
    (R2.13) on its row for the Songs list; the albums and artists it left or joined go in
    `touched`."""
    r = c.execute(
        "SELECT album, albumartist, artist, compilation, albumartistsort, artistsort, albumsort,"
        " album_id, artist_id, path FROM song WHERE id = ?",
        (song_id,),
    ).fetchone()
    album, albumartist, artist, compilation, aasort, asort, albumsort, old_album, old_artist = r[:9]
    touched.add(old_album, old_artist)
    a_identity = album_identity(album, albumartist, artist, bool(compilation), folder_of(r[9]))
    album_id = _get_or_add(c, "album", a_identity) if a_identity else None
    who = artist_identity(artist)
    artist_id = _get_or_add(c, "artist", who) if who else None
    touched.add(album_id, artist_id)
    shown_artist = albumartist or artist
    c.execute(
        "UPDATE song SET album_id = ?, artist_id = ?, artist_key = ?, album_key = ? WHERE id = ?",
        (
            album_id,
            artist_id,
            sortnames.sort_key(shown_artist, aasort if albumartist else (aasort or asort)),
            sortnames.sort_key(album, albumsort),
            song_id,
        ),
    )


def folders_of(c: sqlite3.Connection, album_ids: Iterable[int]) -> set[str]:
    """The folders the songs of these albums are in: what an album's row shows (its cover) is
    shown by each of them (A2.7)."""
    ids = sorted(album_ids)
    found: set[str] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        marks = ", ".join("?" * len(chunk))
        sql = f"SELECT DISTINCT folder FROM song WHERE album_id IN ({marks})"
        found.update(str(f) for (f,) in c.execute(sql, chunk))
    return found


def forget(c: sqlite3.Connection, paths: Iterable[str], touched: Touched) -> None:
    """Notes the albums and artists of songs about to be removed, in `touched`."""
    for p in paths:
        r = c.execute("SELECT album_id, artist_id FROM song WHERE path = ?", (p,)).fetchone()
        if r:
            touched.add(*r)


def _folder_image(
    folder: str, images: Mapping[str, Sequence[art.Image]] | None, stored: tuple[object, ...]
) -> tuple[str, int, int] | None:
    if images is None or folder not in images:  # not walked: what the row had
        path, size, mtime = stored
        return (str(path), int(size), int(mtime)) if path is not None else None  # type: ignore[call-overload]
    found = art.folder_cover(images.get(folder, ()))
    if found is None:
        return None
    return (f"{folder}/{found.name}" if folder else found.name, found.size, found.mtime_ns)


def _image_size(
    folder: str,
    images: Mapping[str, Sequence[art.Image]] | None,
    image: tuple[str, int, int] | None,
    stored: tuple[object, ...],
) -> tuple[int | None, int | None]:
    """The size in pixels of the folder's cover image `image` (R5.6): as the walk measured it
    (attention.measure), else as the row has it when it is the same image; (None, None) when it
    isn't known."""
    if image is None:
        return None, None
    if images is not None and folder in images:
        name = image[0].rpartition("/")[2]
        found = next((i for i in images[folder] if i.name == name), None)
        if found is not None and found.width is not None:
            return found.width, found.height
    if tuple(stored[:3]) == image:
        w, h = stored[3], stored[4]
        return (w, h) if isinstance(w, int) and isinstance(h, int) else (None, None)
    return None, None


def refresh_album(
    c: sqlite3.Connection,
    album_id: int,
    images: Mapping[str, Sequence[art.Image]] | None = None,
) -> set[int]:
    """Summarizes an album's row again from its songs, or removes it when it has none left; the
    artists it was or is now under. `images`: each folder's images, as the walk found them; a
    folder it has no key for (None: any folder) keeps the folder image the row has, as a partial
    scan (A2.4) walks only some."""
    old = c.execute(
        "SELECT artist_id, folder_image, folder_image_size, folder_image_mtime,"
        " folder_image_width, folder_image_height FROM album WHERE id = ?",
        (album_id,),
    ).fetchone()
    if old is None:
        return set()
    artists = {int(old[0])} if old[0] is not None else set()
    rows = c.execute(
        f"SELECT {SONG_COLUMNS} FROM song WHERE album_id = ? ORDER BY {ALBUM_ORDER}",
        (album_id,),
    ).fetchall()
    if not rows:
        c.execute("DELETE FROM album WHERE id = ?", (album_id,))
        return artists
    songs = [
        Song(r[0], r[1], r[2], r[3], bool(r[4]), r[5], r[6], r[7], r[8], bool(r[9]), *r[10:])
        for r in rows
    ]
    genres: list[str] = []
    by_song: dict[str, list[str]] = {}
    for path, g in c.execute(
        "SELECT path, genre FROM song_genre JOIN song ON song.id = song_id WHERE album_id = ?"
        f" ORDER BY {ALBUM_ORDER}, position",  # a tie goes to the first song's first genre
        (album_id,),
    ):
        genres.append(g)
        by_song.setdefault(path, []).append(g)
    folder = most_common(folder_of(s.path) for s in songs) or ""
    image = _folder_image(folder, images, tuple(old[1:4]))
    image_size = _image_size(folder, images, image, tuple(old[1:]))
    a = summarize(songs, genres, image)
    # Needs attention's (R2.8, R5.6): what its songs differ in, and its cover's size
    differs = attention.differs([
        attention.AlbumSong(s.album, s.albumartist, s.year, tuple(by_song.get(s.path, ())),
                            s.has_cover, s.cover_key)
        for s in songs
    ])  # fmt: skip
    cover_song = next((s for s in songs if s.path == a.cover), None)
    if a.cover_kind == "embedded" and cover_song is not None:
        cover_size = (cover_song.cover_width, cover_song.cover_height)
    else:
        cover_size = image_size if a.cover_kind == "file" else (None, None)
    who = artist_identity(a.artist)
    artist_id = _get_or_add(c, "artist", who) if who else None
    if artist_id is not None:
        artists.add(artist_id)
    c.execute(
        "UPDATE album SET artist = ?, title = ?, artist_key = ?, title_key = ?, artist_id = ?,"
        " compilation = ?, year = ?, genre = ?, songs = ?, length = ?, size = ?, embedded = ?,"
        " folder = ?, folder_image = ?, folder_image_size = ?, folder_image_mtime = ?,"
        " cover_kind = ?, cover = ?, thumb = ?, differs = ?, cover_width = ?, cover_height = ?,"
        " folder_image_width = ?, folder_image_height = ? WHERE id = ?",
        (
            a.artist, a.title, a.artist_key, a.title_key, artist_id, int(a.compilation), a.year,
            a.genre, a.songs, a.length, a.size, a.embedded, a.folder, a.folder_image,
            a.folder_image_size, a.folder_image_mtime, a.cover_kind, a.cover, a.thumb,
            ",".join(differs) or None, *cover_size, *image_size, album_id,
        ),
    )  # fmt: skip
    return artists


def refresh_artist(c: sqlite3.Connection, artist_id: int) -> None:
    """Summarizes an artist's row again: the name, its sort key, the albums under it and the songs
    on them or naming it; removed when nothing names it any more."""
    spellings: Counter[str] = Counter()
    sorts: list[str | None] = []
    for name, sort in c.execute(
        "SELECT artist, artistsort FROM song WHERE artist_id = ?", (artist_id,)
    ):
        spellings[name.strip()] += 1
        sorts.append(sort)
    albums = c.execute(
        "SELECT id, artist, songs FROM album WHERE artist_id = ?", (artist_id,)
    ).fetchall()
    for _id, name, n in albums:
        spellings[name.strip()] += n
    if not spellings:
        c.execute("DELETE FROM artist WHERE id = ?", (artist_id,))
        return
    for (sort,) in c.execute(
        "SELECT albumartistsort FROM song WHERE album_id IN"
        " (SELECT id FROM album WHERE artist_id = ?)",
        (artist_id,),
    ):
        sorts.append(sort)
    name = name_of(spellings)
    songs = c.execute(
        "SELECT COUNT(*) FROM song WHERE artist_id = ? OR album_id IN"
        " (SELECT id FROM album WHERE artist_id = ?)",
        (artist_id, artist_id),
    ).fetchone()[0]
    c.execute(
        "UPDATE artist SET name = ?, sort_key = ?, albums = ?, songs = ? WHERE id = ?",
        (name, sortnames.sort_key(name, most_common(sorts)), len(albums), songs, artist_id),
    )


def refresh(
    c: sqlite3.Connection,
    touched: Touched,
    images: Mapping[str, Sequence[art.Image]] | None = None,
) -> None:
    """Summarizes again every album and artist in `touched`, albums first (an album can move to
    another artist)."""
    artists = set(touched.artists)
    for album_id in sorted(touched.albums):
        artists |= refresh_album(c, album_id, images)
    for artist_id in sorted(artists):
        refresh_artist(c, artist_id)


def refresh_folders(c: sqlite3.Connection, images: Mapping[str, Sequence[art.Image]]) -> int:
    """Summarizes again each album whose folder, walked, has a cover image that isn't what its row
    has (an image added, removed or changed with no song touched); how many."""
    stale = [
        album_id
        for album_id, folder, path, size, mtime in c.execute(
            "SELECT id, folder, folder_image, folder_image_size, folder_image_mtime FROM album"
        ).fetchall()
        if folder in images
        and _folder_image(folder, images, ()) != ((path, size, mtime) if path else None)
    ]
    touched = Touched()
    touched.albums.update(stale)
    refresh(c, touched, images)
    return len(stale)
