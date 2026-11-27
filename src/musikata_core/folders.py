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
differing covers); and the worst path-match state beneath it with how many files beneath it can be
fixed or have no tags (R2.9.5).

Tags match path (R3.9) is kept here too: when a folder is summarized again, its own songs' states
are worked out again first (`match_folder`, patterns.states over their paths and tags, with the
user's own patterns of the root's settings, kept in `user_pattern`), as a folder's pattern is
detected from all its songs, so one song changed may change the state of the rest.

Which picture a folder shows and what its songs share are plain functions (`picture`, `shared`),
tested without an index; `refresh` reads and writes the rows. Names sort as people read them
(R2.9.2, sortnames.key_of); a search finds a folder by its name (`condition`)."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from . import art, patterns, search, sortnames
from .tags.fields import Tags

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
    "cover", "thumb", "mosaic", "path_state", "path_fix",
)  # fmt: skip


# ---------- tags match path (R3.9) ----------

# a song's fields its path can give, as the song table holds them, and its genres
MATCH_COLUMNS = ("title", "artist", "album", "albumartist", "track", "tracktotal", "disc",
                 "year", "date")  # fmt: skip


def diff_text(diffs: Sequence[patterns.Difference]) -> str | None:
    """How a song's tags differ from its path, as `song.path_diff` keeps it: JSON, a [field,
    how, value] each; None for no difference."""
    if not diffs:
        return None
    return json.dumps([[d.field, d.how, d.value] for d in diffs], ensure_ascii=False)


def diffs_of(text: object) -> tuple[patterns.Difference, ...]:
    """`song.path_diff` read back (`diff_text`); none for NULL or what isn't one."""
    try:
        found = json.loads(str(text)) if text else []
    except ValueError:
        return ()
    if not isinstance(found, list):
        return ()
    return tuple(
        patterns.Difference(str(d[0]), str(d[1]), str(d[2]))
        for d in found
        if isinstance(d, list) and len(d) == 3
    )


def user_patterns(c: sqlite3.Connection) -> list[str]:
    """The user's own patterns (R3.3, R13.4) as the index keeps them, in order."""
    return [str(t) for (t,) in c.execute("SELECT text FROM user_pattern ORDER BY position")]


def set_user_patterns(c: sqlite3.Connection, texts: Sequence[str]) -> bool:
    """Keeps the user's own patterns (the root's settings', R13.4) in the index; when they are
    other than it had, every folder's states are worked out again (R3.9). Whether they were."""
    texts = [str(t) for t in texts]
    if user_patterns(c) == texts:
        return False
    c.execute("DELETE FROM user_pattern")
    c.executemany("INSERT INTO user_pattern VALUES (?, ?)", list(enumerate(texts)))
    refresh(c, [str(f) for (f,) in c.execute("SELECT DISTINCT folder FROM song")])
    return True


def _tags_where(
    c: sqlite3.Connection, where: str, params: Sequence[object]
) -> list[tuple[int, str, Tags]]:
    """The songs `where` names (id, path under the root, and the tags a path can give), by
    path."""
    genres: dict[int, list[str]] = {}
    for song, genre in c.execute(
        "SELECT song_id, genre FROM song_genre JOIN song ON song.id = song_genre.song_id"
        f" WHERE {where} ORDER BY song_id, position",
        params,
    ):
        genres.setdefault(int(song), []).append(str(genre))
    out = []
    for row in c.execute(
        f"SELECT id, path, {', '.join(MATCH_COLUMNS)} FROM song WHERE {where} ORDER BY path",
        params,
    ):
        values = dict(zip(MATCH_COLUMNS, row[2:], strict=True))
        tags = Tags(**values, genres=tuple(genres.get(int(row[0]), ())))
        out.append((int(row[0]), str(row[1]), tags))
    return out


def tags_in(c: sqlite3.Connection, folder: str) -> list[tuple[int, str, Tags]]:
    """A folder's own songs (id, path under the root, and the tags a path can give), by path."""
    return _tags_where(c, "song.folder = ?", (folder,))


def tags_of(c: sqlite3.Connection, ids: Sequence[int]) -> list[tuple[int, str, Tags]]:
    """The songs of `ids` the index has, in that order (id, path under the root, and the tags a
    path can give): what Infer from path plans from (R3)."""
    found: dict[int, tuple[int, str, Tags]] = {}
    for i in range(0, len(ids), 500):
        chunk = [int(x) for x in ids[i : i + 500]]
        marks = ", ".join("?" * len(chunk))
        found.update((s[0], s) for s in _tags_where(c, f"song.id IN ({marks})", chunk))
    return [found[i] for i in ids if i in found]


def counts_of(c: sqlite3.Connection, folders: Iterable[str]) -> dict[str, int]:
    """How many songs each of `folders` holds of its own (R3.6.4's every track)."""
    out: dict[str, int] = {}
    for folder in set(folders):
        out[folder] = int(
            c.execute("SELECT COUNT(*) FROM song WHERE folder = ?", (folder,)).fetchone()[0]
        )
    return out


def match_folder(
    c: sqlite3.Connection, folder: str, tried: Sequence[patterns.Pattern] | None = None
) -> None:
    """Works out again whether each of a folder's own songs' tags match its path (R3.9), under
    the pattern detected for the folder (`tried`: the patterns, the user's own first; else those
    the index keeps and the presets)."""
    songs = tags_in(c, folder)
    if not songs:
        return
    tried = patterns.patterns_of(user_patterns(c)) if tried is None else tried
    found = patterns.states([(p, t) for _, p, t in songs], tried)
    c.executemany(
        "UPDATE song SET path_state = ?, path_diff = ? WHERE id = ?",
        [(state, diff_text(diffs), song) for (song, _, _), (state, diffs) in zip(songs, found,
                                                                                    strict=True)],
    )  # fmt: skip


def worst(states: Iterable[int | None]) -> int | None:
    """The worst of path-match states (R2.9.5): no tags, then can be fixed, then match; None when
    none is known."""
    known = [s for s in states if s is not None]
    return max(known) if known else None


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
        "SELECT artist, album, year, coalesce(length, 0), path_state FROM song WHERE folder = ?",
        (path,),
    ).fetchall()
    children = c.execute(
        "SELECT path, name_key, songs_beneath, folders_beneath, length, artist, album, year,"
        " thumb, mosaic, path_state, path_fix FROM folder WHERE parent = ?",
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
        "path_state": worst([s[4] for s in songs] + [r[10] for r in children]),
        "path_fix": sum(1 for s in songs if (s[4] or 0) > 0) + sum(r[11] for r in children),
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
    tried = patterns.patterns_of(user_patterns(c))
    for path in set(touched):
        match_folder(c, path, tried)  # R3.9: its songs' states, before it is summarized
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


def songs_beneath(c: sqlite3.Connection, path: str) -> list[int]:
    """The ids of the songs beneath a folder ("" for the root) in the order Folders lists them
    (R2.9.2): its subfolders by name, each with what it holds, then its own files by name. Two
    queries, whatever the depth: what Play on a folder queues (R7.1)."""
    where, params = beneath("path", path)
    children: dict[str, list[tuple[str, str]]] = {}
    for child, parent, key in c.execute(
        f"SELECT path, parent, name_key FROM folder WHERE {where}", params
    ):
        children.setdefault(parent or "", []).append((key, child))
    files: dict[str, list[tuple[str, str, int]]] = {}
    song_where, song_params = ("1", ()) if not path else beneath("path", path)
    for song_id, song_path, folder, key in c.execute(
        f"SELECT id, path, folder, name_key FROM song WHERE {song_where}", song_params
    ):
        files.setdefault(folder or "", []).append((key or "", song_path, song_id))
    out: list[int] = []

    def walk(folder: str) -> None:
        for _key, child in sorted(children.get(folder, [])):
            walk(child)
        out.extend(song_id for _key, _path, song_id in sorted(files.get(folder, [])))

    walk(path)
    return out


def _selection(folders: Sequence[str], files: Sequence[str]) -> tuple[str, list[str]]:
    """SQL for the songs beneath `folders` and at `files`, each once ("" for none)."""
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
    return " OR ".join(parts), params


def count_songs(c: sqlite3.Connection, folders: Sequence[str], files: Sequence[str]) -> int:
    """How many songs a selection stands for (R2.9.6): those beneath its folders and its files,
    each once however the folders and files overlap."""
    where, params = _selection(folders, files)
    if not where:
        return 0
    return int(c.execute(f"SELECT COUNT(*) FROM song WHERE {where}", params).fetchone()[0])


def album_of(c: sqlite3.Connection, folders: Sequence[str], files: Sequence[str]) -> int | None:
    """The album every song a selection stands for is on (R2.9.6's Album art), by id; None when
    they are on more than one, one of them is on none, or there are none."""
    where, params = _selection(folders, files)
    if not where:
        return None
    low, high, songs, on_one = c.execute(
        f"SELECT MIN(album_id), MAX(album_id), COUNT(*), COUNT(album_id) FROM song WHERE {where}",
        params,
    ).fetchone()
    return int(low) if songs and on_one == songs and low == high else None
