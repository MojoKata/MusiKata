"""The folder table (A2.7, A2.1): one row per folder under the root with audio beneath it, which the
Folders view (R2.9) lists, so opening a folder is one indexed query on `parent`, not a walk of the
disk. The scan keeps it in the same transactions as the songs it writes (A2.2): each folder a write
touched is summarized again, then each of its ancestors, bottom up, from its own songs' rows and its
children's rows, never a file.

A row holds the folder's counts (subfolders and songs, its own and beneath it), its songs' total
length, the artist, album and year they share (or none), its own cover (R5.8, step 1: an image in
the folder, else the front cover embedded in its songs when they share one) and, without one, the
sources of its mosaic (step 2: one picture from each of up to four subfolders, those with the most
songs, in name order, a subfolder that is a mosaic giving its first; or a folder of loose songs'
differing covers). The worst path-match state beneath it (R2.9.5) joins with tags from paths
(R3.9, slice 7).

Which picture a folder shows and what its songs share are plain functions (`picture`, `shared`),
tested without an index; `refresh` reads and writes the rows. Names sort as people read them
(R2.9.2, sortnames.key_of); a search finds a folder by its name (`condition`)."""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from . import art, search, sortnames

MOSAIC = 4  # pictures a mosaic holds at most (R5.8)
# where each of a mosaic's pictures sits (R5.8's table), as fractions of the tile: x, y, w, h
LAYOUTS: dict[int, tuple[tuple[float, float, float, float], ...]] = {
    0: (),
    1: ((0, 0, 1, 1),),
    2: ((0, 0, 0.5, 1), (0.5, 0, 0.5, 1)),
    3: ((0, 0, 0.5, 1), (0.5, 0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)),
    4: ((0, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5), (0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)),
}


def layout(n: int) -> tuple[tuple[float, float, float, float], ...]:
    """Where each of n pictures (up to four) sits in a mosaic (R5.8): one whole, two halves side
    by side, a half on the left and two quarters on the right, a 2 x 2 grid. Each is (x, y, w, h)
    as fractions of the tile; the gap between them is the drawer's."""
    return LAYOUTS[min(max(n, 0), MOSAIC)]


def parent_of(path: str) -> str | None:
    """The folder a folder is in ("" for the root's own), None for the root itself."""
    if not path:
        return None
    return path.rpartition("/")[0]


def name_of(path: str) -> str:
    """A folder's or file's own name: the last part of its path under the root."""
    return path.rpartition("/")[2]


def ancestors(path: str) -> list[str]:
    """The folders a folder is in, nearest first, the root ("") last."""
    out = []
    while (up := parent_of(path)) is not None:
        out.append(up)
        path = up
    return out


def folded(text: str) -> str:
    """A name as a search reads it (R2.7): case and accents aside, so "beyonce" finds
    "Beyoncé"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


# ---------- what a row says ----------


@dataclass(frozen=True)
class Child:
    """A subfolder's row, as its parent's picture reads it: its path, name key, songs beneath it,
    its own cover's thumbnail and its mosaic's."""

    path: str
    name_key: str
    songs: int
    thumb: str | None
    mosaic: tuple[str, ...] = ()

    @property
    def first(self) -> str | None:
        """The picture it gives a mosaic: its own cover, else its mosaic's first (R5.8)."""
        return self.thumb or (self.mosaic[0] if self.mosaic else None)


@dataclass(frozen=True)
class Picture:
    """What a folder shows (R5.8): its own cover (`kind` "file", an image in the folder at
    `cover`; or "embedded", the front cover of the song at `cover`) by its thumbnail's name, or
    the thumbnails of its mosaic; neither for no picture at all."""

    kind: str | None = None
    cover: str | None = None
    thumb: str | None = None
    mosaic: tuple[str, ...] = ()


def picture(
    image: tuple[str, int, int] | None,
    embedded: Sequence[tuple[str, str]],
    children: Sequence[Child],
) -> Picture:
    """A folder's picture (R5.8) from its own cover image (path, size, modification time) if it
    has one, the embedded covers of its own songs (thumbnail, song), each album's once, in name
    order, and its subfolders' rows: its image; else the embedded cover its songs share; else a
    mosaic of its subfolders' pictures, up to four, from those with the most songs, in name order;
    else, for a folder of loose songs whose covers differ, a mosaic of up to four of them."""
    if image is not None:
        return Picture("file", image[0], art.thumb_id(*image))
    if len(embedded) == 1:
        thumb, song = embedded[0]
        return Picture("embedded", song, thumb)
    pictured = [c for c in children if c.first]
    most = sorted(pictured, key=lambda c: (-c.songs, c.name_key, c.path))[:MOSAIC]
    mosaic = tuple(str(c.first) for c in sorted(most, key=lambda c: (c.name_key, c.path)))
    if not mosaic:
        mosaic = tuple(thumb for thumb, _song in embedded[:MOSAIC])
    return Picture(mosaic=mosaic)


def shared(values: Iterable[object]) -> object:
    """The value every one of `values` has, or None when they differ, any is missing, or there
    are none: a folder's artist, album or year in List (R2.9.4)."""
    found: set[object] = set()
    for v in values:
        if v is None or v == "":
            return None
        found.add(v)
        if len(found) > 1:
            return None
    return found.pop() if found else None


# ---------- the rows ----------

COLUMNS = (
    "parent", "name", "name_key", "fold", "folders", "songs", "folders_beneath", "songs_beneath",
    "length", "artist", "album", "year", "image", "image_size", "image_mtime", "cover_kind",
    "cover", "thumb", "mosaic",
)  # fmt: skip


def _image(
    c: sqlite3.Connection, path: str, images: Mapping[str, Sequence[art.Image]] | None
) -> tuple[str, int, int] | None:
    """The folder's cover image as the walk found it; a folder it didn't walk keeps its row's."""
    if images is None or path not in images:
        row = c.execute(
            "SELECT image, image_size, image_mtime FROM folder WHERE path = ?", (path,)
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0]), int(row[1]), int(row[2])
    found = art.folder_cover(images[path])
    if found is None:
        return None
    return (f"{path}/{found.name}" if path else found.name, found.size, found.mtime_ns)


def embedded_covers(c: sqlite3.Connection, path: str) -> list[tuple[str, str]]:
    """The front covers embedded in a folder's own songs (R5.8), each by its thumbnail's name and
    the song it is in, in name order: an album's cover once for its songs here (its row's, which
    the songs of an album share), and each of the songs on no album its own."""
    found = [
        (str(key), str(song), str(thumb))
        for thumb, song, key in c.execute(
            "SELECT album.thumb, min(song.path), min(song.name_key) FROM song"
            " JOIN album ON album.id = song.album_id WHERE song.folder = ? AND song.has_cover"
            " AND album.cover_kind = 'embedded' AND album.thumb IS NOT NULL GROUP BY album.thumb",
            (path,),
        )
    ]
    found += [
        (str(key), str(song), art.thumb_id(song, size, mtime_ns))
        for song, size, mtime_ns, key in c.execute(
            "SELECT path, size, mtime_ns, name_key FROM song"
            " WHERE folder = ? AND has_cover AND album_id IS NULL",
            (path,),
        )
    ]
    return [(thumb, song) for _key, song, thumb in sorted(found)]


def loose_cover(c: sqlite3.Connection, thumb: str) -> str | None:
    """The song on no album whose embedded cover has the thumbnail `thumb`, found through the
    folders whose mosaics hold it (`embedded_covers`); None when none has."""
    for song, size, mtime_ns in c.execute(
        "SELECT song.path, song.size, song.mtime_ns FROM folder JOIN song ON song.folder ="
        " folder.path WHERE instr(folder.mosaic, ?) AND song.has_cover AND song.album_id IS NULL",
        (thumb,),
    ):
        if art.thumb_id(song, size, mtime_ns) == thumb:
            return str(song)
    return None


def refresh_one(
    c: sqlite3.Connection, path: str, images: Mapping[str, Sequence[art.Image]] | None = None
) -> None:
    """Summarizes one folder's row again from its own songs and its subfolders' rows (which must
    be current), or removes it when nothing with audio is left beneath it."""
    songs = c.execute(
        "SELECT artist, album, year, coalesce(length, 0) FROM song WHERE folder = ?", (path,)
    ).fetchall()
    children = c.execute(
        "SELECT path, name_key, songs_beneath, folders_beneath, length, artist, album, year,"
        " thumb, mosaic FROM folder WHERE parent = ?",
        (path,),
    ).fetchall()
    if not songs and not children:
        c.execute("DELETE FROM folder WHERE path = ?", (path,))
        return
    image = _image(c, path, images)
    shown = picture(
        image,
        embedded_covers(c, path),
        [Child(r[0], r[1], r[2], r[8], tuple((r[9] or "").split())) for r in children],
    )
    row = {
        "path": path,
        "parent": parent_of(path),
        "name": name_of(path),
        "name_key": sortnames.key_of(name_of(path)),
        "fold": folded(name_of(path)),
        "folders": len(children),
        "songs": len(songs),
        "folders_beneath": len(children) + sum(r[3] for r in children),
        "songs_beneath": len(songs) + sum(r[2] for r in children),
        "length": sum(s[3] for s in songs) + sum(r[4] for r in children),
        "artist": shared([s[0] for s in songs] + [r[5] for r in children]),
        "album": shared([s[1] for s in songs] + [r[6] for r in children]),
        "year": shared([s[2] for s in songs] + [r[7] for r in children]),
        "image": image[0] if image else None,
        "image_size": image[1] if image else None,
        "image_mtime": image[2] if image else None,
        "cover_kind": shown.kind,
        "cover": shown.cover,
        "thumb": shown.thumb,
        "mosaic": " ".join(shown.mosaic) or None,
    }
    sets = ", ".join(f"{k} = excluded.{k}" for k in COLUMNS)
    c.execute(
        f"INSERT INTO folder (path, {', '.join(COLUMNS)})"
        f" VALUES (:path, {', '.join(':' + k for k in COLUMNS)})"
        f" ON CONFLICT (path) DO UPDATE SET {sets}",
        row,
    )


def refresh(
    c: sqlite3.Connection,
    touched: Iterable[str],
    images: Mapping[str, Sequence[art.Image]] | None = None,
) -> None:
    """Summarizes again each folder in `touched` (paths under the root, "" for the root) and each
    of its ancestors, the deepest first, so every folder is summarized from current subfolders
    (A2.7). `images`: each folder's images as the walk found them; a folder it has no key for keeps
    its row's cover image."""
    every: set[str] = set()
    for path in touched:
        every.add(path)
        every.update(ancestors(path))
    for path in sorted(every, key=lambda p: (-(p.count("/") + bool(p)), p)):
        refresh_one(c, path, images)


def stale_images(c: sqlite3.Connection, images: Mapping[str, Sequence[art.Image]]) -> list[str]:
    """The folders walked whose cover image isn't what their row has (an image added, removed or
    changed with no song touched)."""
    return [
        path
        for path, image, size, mtime in c.execute(
            "SELECT path, image, image_size, image_mtime FROM folder"
        ).fetchall()
        if path in images
        and _image(c, path, images) != ((image, size, mtime) if image is not None else None)
    ]


# ---------- reading ----------


def condition(query: search.Query) -> tuple[str, tuple[object, ...]]:
    """The SQL a folder's row (table `folder`) must meet to match a search (R2.9.2, R2.7): its
    name holds every word, case and accents aside. A search with a `field:` term or a comparison
    asks about songs, not names, so no folder matches it ("0")."""
    if not query.terms or query.compares or any(t.columns for t in query.terms):
        return "0", ()
    parts, params = [], []
    for t in query.terms:
        word = folded(t.text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        parts.append("folder.fold LIKE ? ESCAPE '\\'")
        params.append(f"%{word}%")
    return " AND ".join(parts), tuple(params)


def beneath(column: str, path: str) -> tuple[str, tuple[str, ...]]:
    """SQL for the paths in `column` beneath the folder `path` ("" for the root: every path but
    the root's own ""), by the paths' index: from path/ up to path0, "0" following "/"."""
    if not path:
        return f"{column} > ''", ()
    return f"({column} >= ? AND {column} < ?)", (path + "/", path + "0")


def first_song(c: sqlite3.Connection, path: str) -> str | None:
    """The first song beneath a folder in the order Folders lists it (R2.9.2): its subfolders by
    name, each first, then its own files by name; None when it holds none."""
    for (child,) in c.execute(
        "SELECT path FROM folder WHERE parent = ? ORDER BY name_key, path", (path,)
    ).fetchall():
        found = first_song(c, child)
        if found is not None:
            return found
    row = c.execute(
        "SELECT path FROM song WHERE folder = ? ORDER BY name_key, path LIMIT 1", (path,)
    ).fetchone()
    return str(row[0]) if row else None


def count_songs(c: sqlite3.Connection, folders: Sequence[str], files: Sequence[str]) -> int:
    """How many songs a selection stands for (R2.9.6): those beneath its folders and its files,
    each once however the folders and files overlap."""
    parts: list[str] = []
    params: list[str] = []
    for f in folders:
        sql, p = beneath("path", f)
        parts.append(sql)
        params += p
    for i in range(0, len(files), 500):
        chunk = files[i : i + 500]
        parts.append(f"path IN ({', '.join('?' * len(chunk))})")
        params += chunk
    if not parts:
        return 0
    return int(
        c.execute(f"SELECT COUNT(*) FROM song WHERE {' OR '.join(parts)}", params).fetchone()[0]
    )
