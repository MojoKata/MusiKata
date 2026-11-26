"""The objects QML sees (A1.2). `Library`: the root, its card's line, the views and going between
them (R2.6, R6.3), the header (R6.4: the view's title and count, the search, the view mode and the
sort), Albums with its genre chips and Artists, an album's and an artist's pages, and the scans,
run one at a time on a thread of their own with the worker processes reading the files (A1.3,
A2.2): the root's, and the partial ones of the folders the watcher names (A2.4, R2.4).
`Player`: the song playing, played on the playback thread (player.py, A4.1).

What the root's card and the pages say is decided here, as text (`docs/process/coding.md`: QML only
lays out and binds)."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Executor

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import albums, db, scanner, watch, workers
from musikata_core.clock import Clock, SystemClock

from .models import (
    ALBUM_SORT_LABELS,
    AlbumsModel,
    ArtistsModel,
    PagedModel,
    Searcher,
    SongsModel,
    artist_line,
    artist_text,
    artist_thumbs,
    count_text,
    cover_url,
    length_text,
    no_match_text,
    plural,
    song_headers,
    tiles,
)
from .player import Engine, PlaybackThread

log = logging.getLogger(__name__)


def shown_path(path: str, home: str) -> str:
    """A path as MusiKata shows it: under the home folder as ~/…, with the system's separator."""
    home = home.rstrip("/\\")
    if home and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home) :]
    return path


def size_text(n: int) -> str:
    """Bytes as the root's card gives them: 9.8 GB, 412 MB, 3 KB (powers of 1000, as the systems'
    file managers mostly do)."""
    for unit, size in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= size:
            v = n / size
            return f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}"
    return f"{n} bytes"


def summary(songs: int, albums: int, size: int) -> str:
    """The root card's line (R2.1.1): 1,412 songs · 128 albums · 9.8 GB."""
    if not songs:
        return "No songs yet"
    return " · ".join((plural(songs, "song"), plural(albums, "album"), size_text(size)))


def scanning_text(done: int, of: int) -> str:
    """The root card's line while a scan runs (R2.3)."""
    return f"Scanning… {done:,} of {of:,}" if of else "Scanning…"


def counts(c: sqlite3.Connection) -> tuple[int, int, int]:
    """Songs, albums (R2.5.2) and bytes."""
    r = c.execute(
        "SELECT COUNT(*), (SELECT COUNT(*) FROM album), coalesce(SUM(size), 0) FROM song"
    ).fetchone()
    return int(r[0]), int(r[1]), int(r[2])


CHIPS = 8  # genre chips shown before More… (R2.6)
KINDS = {
    "mp3": "MP3", "flac": "FLAC", "aac": "AAC", "alac": "ALAC", "vorbis": "Ogg Vorbis",
    "opus": "Opus", "wav": "WAV", "aiff": "AIFF",
}  # fmt: skip
LOSSLESS = {"flac", "alac", "wav", "aiff"}


def genre_chips(c: sqlite3.Connection, n: int = CHIPS) -> tuple[list[str], list[str]]:
    """Albums' genre chips (R2.6): the n genres most albums have, most first, and the rest, by
    name, for More…."""
    found = [
        g
        for (g,) in c.execute(
            "SELECT genre FROM album WHERE genre IS NOT NULL GROUP BY genre"
            " ORDER BY COUNT(*) DESC, genre COLLATE NOCASE"
        )
    ]
    return found[:n], sorted(found[n:], key=str.casefold)


def format_text(groups: list[tuple[str | None, int | None, int | None, int]]) -> str:
    """An album's format (R2.6) from its songs' (kind, sample rate, bit rate, songs): FLAC 44.1
    kHz; MP3 320 kbps; several kinds, most songs first: FLAC, MP3. Empty when unknown."""
    by_kind: dict[str, list[tuple[int | None, int | None, int]]] = {}
    for kind, rate, bitrate, n in groups:
        if kind:
            by_kind.setdefault(kind, []).append((rate, bitrate, n))
    if not by_kind:
        return ""
    if len(by_kind) > 1:
        order = sorted(by_kind, key=lambda k: (-sum(g[2] for g in by_kind[k]), k))
        return ", ".join(KINDS.get(k, k) for k in order)
    kind, found = next(iter(by_kind.items()))
    name = KINDS.get(kind, kind)
    if kind in LOSSLESS:
        rate = max(found, key=lambda g: g[2])[0]
        return f"{name} {rate / 1000:g} kHz" if rate else name
    songs = sum(g[2] for g in found)
    kbps = round(sum((g[1] or 0) * g[2] for g in found) / songs / 1000)
    return f"{name} {kbps} kbps" if kbps else name


def kicker(compilation: bool, year: int | None, genre: str | None) -> str:
    """The line over an album's title (R2.6): Album · 2019 · Electronic."""
    parts = ("Compilation" if compilation else "Album", str(year) if year else "", genre or "")
    return " · ".join(p for p in parts if p)


def state_chips(songs: int, embedded: int, folder_image: str | None) -> list[dict[str, str]]:
    """An album's state chips (R2.6), each its text and tone ("ok", "warn", "info"): the art
    embedded in its songs, and its folder's cover image. Whether its tags match the path (R3.9)
    comes with tags from paths (slice 7)."""
    if embedded == songs:
        out = [{"text": f"Art embedded in {embedded} of {songs}", "tone": "ok"}]
    elif embedded:
        out = [{"text": f"Art embedded in {embedded} of {songs}", "tone": "warn"}]
    else:
        out = [{"text": "No art embedded", "tone": "info"}]
    if folder_image:
        out.append({"text": f"{folder_image.rpartition('/')[2]} in folder", "tone": "info"})
    return out


def _field(name: str, default: object = "") -> Callable[[AlbumPage | ArtistPage], object]:
    """A page's property getter: its value of `name`, `default` before it shows anything."""
    return lambda page: page._values.get(name, default)


class AlbumPage(QObject):
    """An album's page (R2.6, L02-album): its cover, title, artist, the line over the title, the
    songs, length and format, its state chips, and its songs."""

    changed = Signal()

    def __init__(self, read: Callable[[], sqlite3.Connection], parent: QObject | None = None):
        super().__init__(parent)
        self._read = read
        self._id = -1
        self._values: dict[str, object] = {}
        self._songs = SongsModel(read, "tracks", self, "album_id = ?", (-1,))

    def load(self, album_id: int) -> bool:
        """Shows the album with that id; False when there is none."""
        c = self._read()
        r = c.execute(
            "SELECT title, artist, artist_id, compilation, year, genre, songs, length, embedded,"
            " folder_image, thumb FROM album WHERE id = ?",
            (album_id,),
        ).fetchone()
        if r is None:
            return False
        (
            title,
            artist,
            artist_id,
            compilation,
            year,
            genre,
            songs,
            length,
            embedded,
            image,
            thumb,
        ) = r
        groups = c.execute(
            "SELECT kind, sample_rate, CAST(avg(bitrate) AS INTEGER), COUNT(*) FROM song"
            " WHERE album_id = ? GROUP BY kind, sample_rate",
            (album_id,),
        ).fetchall()
        same, self._id = album_id == self._id, album_id
        self._values = {
            "title": title,
            "artist": artist_text(artist),
            "artistId": artist_id if artist_id is not None else -1,
            "kicker": kicker(bool(compilation), year, genre),
            "detail": " · ".join(
                p for p in (plural(songs, "song"), length_text(length), format_text(groups)) if p
            ),
            "cover": cover_url(thumb),
            "chips": state_chips(songs, embedded, image),
        }
        if same:  # read again where it is: after a scan, the list keeps its place
            self._songs.refresh()
        else:
            self._songs.select("album_id = ?", (album_id,))
        self.changed.emit()
        return True

    def first_song(self) -> str:
        """The path of the album's first song ("" when it has none)."""
        row = self._songs.row(0)
        return row["path"] if row else ""

    def _get_id(self) -> int:
        return self._id

    def _get_songs(self) -> SongsModel:
        return self._songs

    id = QtProperty(int, _get_id, notify=changed)
    title = QtProperty(str, _field("title"), notify=changed)
    artist = QtProperty(str, _field("artist"), notify=changed)
    artistId = QtProperty(int, _field("artistId", -1), notify=changed)
    kicker = QtProperty(str, _field("kicker"), notify=changed)  # Album · 2019 · Electronic
    detail = QtProperty(str, _field("detail"), notify=changed)  # 10 songs · 44 min · FLAC 44.1 kHz
    cover = QtProperty(str, _field("cover"), notify=changed)
    chips = QtProperty(list, _field("chips", []), notify=changed)
    songs = QtProperty(QObject, _get_songs, constant=True)


class ArtistPage(QObject):
    """An artist's page (R2.6): their name, counts and mosaic, their albums, then their songs on
    others' albums and on none."""

    changed = Signal()

    def __init__(self, read: Callable[[], sqlite3.Connection], parent: QObject | None = None):
        super().__init__(parent)
        self._read = read
        self._id = -1
        self._values: dict[str, object] = {}
        self._albums = AlbumsModel(read, self, artist_id=-1)
        self._others = SongsModel(read, "others", self, "artist_id = ?", (-1,))

    def load(self, artist_id: int) -> bool:
        """Shows the artist with that id; False when there is none."""
        c = self._read()
        r = c.execute(
            "SELECT name, albums, songs FROM artist WHERE id = ?", (artist_id,)
        ).fetchone()
        if r is None:
            return False
        name, albums, songs = r
        thumbs = c.execute(f"SELECT {artist_thumbs('?')}", (artist_id, artist_id)).fetchone()[0]
        if artist_id == self._id:  # read again where they are: after a scan
            self._albums.refresh()
            self._others.refresh()
        else:
            self._id = artist_id
            self._albums.for_artist(artist_id)
            self._others.select(
                "artist_id = ? AND (album_id IS NULL OR album_id NOT IN"
                " (SELECT id FROM album WHERE artist_id = ?))",
                (artist_id, artist_id),
            )
        self._values = {
            "name": name,
            "detail": artist_line(albums, songs),
            "tiles": tiles((thumbs or "").split()),
            "othersTitle": "Other songs" if self._others.rowCount() else "",
        }
        self.changed.emit()
        return True

    def _get_id(self) -> int:
        return self._id

    def _get_albums(self) -> AlbumsModel:
        return self._albums

    def _get_others(self) -> SongsModel:
        return self._others

    id = QtProperty(int, _get_id, notify=changed)
    name = QtProperty(str, _field("name"), notify=changed)
    detail = QtProperty(str, _field("detail"), notify=changed)  # 3 albums · 41 songs
    tiles = QtProperty(list, _field("tiles", []), notify=changed)
    othersTitle = QtProperty(str, _field("othersTitle"), notify=changed)  # "" when there are none
    albums = QtProperty(QObject, _get_albums, constant=True)
    others = QtProperty(QObject, _get_others, constant=True)


VIEWS = ("albums", "artists", "songs")  # the sidebar's views built so far (R6.3)
TITLES = {"albums": "Albums", "artists": "Artists", "songs": "Songs"}
NOUNS = {"albums": "album", "artists": "artist", "songs": "song"}  # what each view counts
SEARCH_HINT = "Search the library"
# the view modes each view has (R6.4; Albums' grid and list, R2.6): its name, label and icon
MODES = {"albums": [{"mode": "grid", "label": "Grid", "icon": "grid"},
                    {"mode": "list", "label": "List", "icon": "list"}]}  # fmt: skip


def sort_text(label: str) -> str:
    """The header's sort button (R6.4): Sort: Artist."""
    return f"Sort: {label}" if label else ""


class Library(QObject):
    """One root and its index, as the sidebar and the views see them: which view is open and the
    way back from a page (R6.3), Albums and its genre chips, Artists, Songs, and the pages; and
    its scans. With `watching`, a scan of the root starts watching it (A2.4): a change the watcher
    reports is rescanned, its folders only, and the views read again where they are."""

    changed = Signal()  # the card's line, the counts, the genre chips, the empty texts
    scanningChanged = Signal()
    viewChanged = Signal()  # the view, and its header's title, modes and sorts
    searchChanged = Signal()
    _progress = Signal(int, int)
    _finished = Signal(object)

    def __init__(
        self,
        root: str,
        index: db.Index,
        home: str,
        pool: Callable[[], Executor] = workers.pool,
        parent: QObject | None = None,
        clock: Clock | None = None,
        watching: bool = False,
    ) -> None:
        super().__init__(parent)
        self._root, self._index, self._home, self._pool = root, index, home, pool
        self._clock = clock if clock is not None else SystemClock()
        self._watching = watching
        self._watcher: watch.Watcher | None = None
        self._own = watch.OwnWrites(self._clock)
        self._copied: dict[str, str] = {}  # copies made while watching (scanner.scan)
        self._searcher = Searcher(self)
        self._songs = SongsModel(index.read, parent=self, searcher=self._searcher)
        self._albums = AlbumsModel(index.read, self, searcher=self._searcher)
        self._artists = ArtistsModel(index.read, self, self._searcher)
        self._lists: dict[str, PagedModel] = {
            "albums": self._albums, "artists": self._artists, "songs": self._songs
        }  # fmt: skip
        for model in self._lists.values():
            model.countChanged.connect(self.changed)
        self._album = AlbumPage(index.read, self)
        self._artist = ArtistPage(index.read, self)
        self._view = "albums"
        self._search = ""  # what the header's search box holds (R2.7)
        # the views a page was opened from, each with its search
        self._history: list[tuple[str, int, str]] = []
        self._genre = ""
        self._albums_mode = "grid"
        self._chips: tuple[list[str], list[str]] = ([], [])
        self._playing = ""
        self._scanning = False  # a scan of the root runs, or waits on a partial one to end
        self._busy = False  # a scan runs, of the root or partial
        self._closed = False
        self._done = self._of = 0
        self._thread: threading.Thread | None = None
        self.last: scanner.Result | BaseException | None = None  # the last scan's outcome
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)
        self._counts = (0, 0, 0)
        self.reload()

    def reload(self) -> None:
        """Reads the lists, the counts and the chips afresh (after a scan), and the open page,
        each list where it is, with its search, so the user keeps their place; a page whose album
        or artist went shows the view it was opened from."""
        self._songs.refresh()
        self._albums.refresh()
        self._artists.refresh()
        c = self._index.read()
        self._counts = counts(c)
        self._chips = genre_chips(c)
        if self._genre and self._genre not in self._chips[0] + self._chips[1]:
            self.set_genre("")
        pages: dict[str, AlbumPage | ArtistPage] = {"album": self._album, "artist": self._artist}
        page = pages.get(self._view)
        if page is not None and not page.load(page.property("id")):
            self.back()
        self._mark_playing()
        self.changed.emit()

    # ---------- going between the views ----------

    @Slot(str)
    def show(self, view: str) -> None:
        """Opens one of the sidebar's views (R6.3), forgetting the pages opened on the way and
        every search: the view opens whole."""
        if view not in VIEWS:
            raise ValueError(f"no such view: {view}")
        self._history.clear()
        for model in self._lists.values():
            if model.searching():
                model.set_search("")
        self._go(view, "")

    @Slot(int)
    def openAlbum(self, album_id: int) -> None:  # noqa: N802
        """Opens an album's page (L02-album) from the view open now."""
        current = (
            self._view,
            self._artist.property("id") if self._view == "artist" else -1,
            self._search,
        )
        if self._album.load(album_id):
            self._history.append(current)
            self._go("album", "")

    @Slot(int)
    def openArtist(self, artist_id: int) -> None:  # noqa: N802
        """Opens an artist's page from the view open now."""
        current = (
            self._view,
            self._album.property("id") if self._view == "album" else -1,
            self._search,
        )
        if artist_id >= 0 and self._artist.load(artist_id):
            self._history.append(current)
            self._go("artist", "")

    @Slot()
    def back(self) -> None:
        """Back to the view or page this one was opened from (Albums when none), filtered by the
        search it had."""
        view, page, text = self._history.pop() if self._history else ("albums", -1, "")
        if view == "album" and not self._album.load(page):
            view = "albums"
        if view == "artist" and not self._artist.load(page):
            view = "artists"
        self._go(view, text if view in VIEWS else "")

    def _go(self, view: str, search: str) -> None:
        self._view = view
        self._search = search
        self.viewChanged.emit()
        self.searchChanged.emit()
        self.changed.emit()

    # ---------- the header (R6.4) ----------

    @Slot(str)
    def setSearch(self, text: str) -> None:  # noqa: N802
        """Filters the view open by what the user typed (R2.7), as they type; a page has no
        search box (L02-album), so a search there does nothing. The view's rows come from the
        search thread, with its model's countChanged."""
        model = self._lists.get(self._view)
        if model is None or text == self._search:
            return
        self._search = text
        model.set_search(text)
        self.searchChanged.emit()
        self.changed.emit()

    @Slot(str)
    def setSort(self, sort: str) -> None:  # noqa: N802
        """Orders the view open by one of the header's sorts (R6.4): Albums by artist, title or
        year (R2.6, R2.13); Artists by name, the one order they have."""
        if self._view == "albums":
            self._albums.sort_by(sort)
        elif self._view != "artists" or sort != "name":
            raise ValueError(f"no such order in {self._view}: {sort}")
        self.viewChanged.emit()
        self.changed.emit()

    @Slot(str)
    def sortSongs(self, column: str) -> None:  # noqa: N802
        """Orders Songs by a column (R2.6): a click on the column it is sorted by turns it the
        other way, on another sorts by that one from the start."""
        sort, descending = self._songs.order()
        self._songs.sort_by(column, not descending if column == sort else False)
        self.viewChanged.emit()
        self.changed.emit()

    def go(self, step: dict[str, str]) -> None:
        """A tour's step (A1.6): {"view": "albums"}, a view with a search typed into it:
        {"view": "songs", "search": "electronic"}, or a page by its name: {"view": "album",
        "album": "Glass Harbor"}, {"view": "artist", "artist": "Lumen Drift"}."""
        view = step["view"]
        c = self._index.read()
        if view == "album":
            r = c.execute("SELECT id FROM album WHERE title = ?", (step["album"],)).fetchone()
            self.show("albums")
            self.openAlbum(r[0] if r else -1)
        elif view == "artist":
            r = c.execute("SELECT id FROM artist WHERE name = ?", (step["artist"],)).fetchone()
            self.show("artists")
            self.openArtist(r[0] if r else -1)
        else:
            self.show(view)
            self.setSearch(step.get("search", ""))

    # ---------- Albums' genre chips ----------

    @Slot(str)
    def setGenre(self, genre: str) -> None:  # noqa: N802
        """Shows only the albums of that genre ("": every album), R2.6's chips."""
        self.set_genre(genre)

    def set_genre(self, genre: str) -> None:
        self._genre = genre
        self._albums.filter_genre(genre)
        self.changed.emit()

    @Slot(str)
    def setAlbumsMode(self, mode: str) -> None:  # noqa: N802
        """Albums as a grid of covers or a list (R2.6, the header's view switch, R6.4)."""
        if mode not in ("grid", "list"):
            raise ValueError(f"no such mode: {mode}")
        self._albums_mode = mode
        self.viewChanged.emit()

    @Slot(int, result=str)
    def firstSong(self, album_id: int) -> str:  # noqa: N802
        """The path of an album's first song, by disc and track ("" when it has none): Play."""
        r = (
            self._index.read()
            .execute(
                f"SELECT path FROM song WHERE album_id = ? ORDER BY {albums.ALBUM_ORDER} LIMIT 1",
                (album_id,),
            )
            .fetchone()
        )
        return r[0] if r else ""

    # ---------- the scans ----------

    @Slot()
    def rescan(self) -> None:
        """Scans the root on the scan's thread (R2.3): at once, or when the partial scan running
        ends; nothing if a scan of the root runs or waits already."""
        if self._scanning:
            return
        self._scanning = True
        self._done = self._of = 0
        self.scanningChanged.emit()
        self.changed.emit()
        if not self._busy:
            self._start(None)

    def _start(self, scope: scanner.Scope | None) -> None:
        """One scan at a time (A2.4): the root's (scope None), or the folders a scope names."""
        self._busy = True
        if scope is None and self._watcher is not None:
            self._watcher.forget()  # what it gathered, this scan covers
        expected, copied = self._own.expected(), dict(self._copied)
        self._thread = threading.Thread(
            target=self._scan, args=(scope, expected, copied), name="scan", daemon=True
        )
        self._thread.start()

    def _scan(
        self,
        scope: scanner.Scope | None,
        expected: dict[str, tuple[int, int]],
        copied: dict[str, str],
    ) -> None:
        result: scanner.Result | BaseException
        try:
            with self._pool() as pool:
                result = scanner.scan(
                    self._root,
                    self._index,
                    pool,
                    progress=self._progress.emit if scope is None else None,
                    scope=scope,
                    expected=expected,
                    copied=copied,
                )
        except Exception as e:  # noqa: BLE001  (the scan's failure is shown, and MusiKata goes on)
            log.exception("the scan of %s failed", self._root)
            result = e
        self.last = result
        self._finished.emit((scope is None, result))

    @Slot(int, int)
    def _on_progress(self, done: int, of: int) -> None:
        """A batch of a scan of the root written: the views fill as it goes (R2.3)."""
        self._done, self._of = done, of
        self.reload()

    @Slot(object)
    def _on_finished(self, finished: tuple[bool, scanner.Result | BaseException]) -> None:
        whole, result = finished
        self._busy = False
        if isinstance(result, scanner.Result) and not self._closed:
            self._copied = result.copied
            self._watch(whole, result)
        if whole:
            self._scanning = False
        self.reload()
        if whole:
            self.scanningChanged.emit()
        self._next()

    def _next(self) -> None:
        """The next scan, once one has ended: the root's, if asked for meanwhile, else the
        folders gathered and due."""
        if self._busy or self._closed:
            return
        if self._scanning:
            self._start(None)
        elif self._watcher is not None and self._watcher.due():
            folders = self._watcher.take()
            if folders:
                self._start(scanner.Scope(folders, self._watcher.known()))

    # ---------- watching (A2.4, R2.4) ----------

    def _watch(self, whole: bool, result: scanner.Result) -> None:
        """After a scan: the folders it walked watched, those it found gone not."""
        if not self._watching:
            return
        if self._watcher is None:
            self._watcher = watch.Watcher(self._root, watch.Gatherer(self._clock), parent=self)
            self._watcher.ready.connect(self._next)
        if whole:
            self._watcher.watch(result.folders)
        else:
            self._watcher.update(result.folders, result.gone_folders)
        self._watcher.scanned(result.read)

    @property
    def watcher(self) -> watch.Watcher | None:
        """The root's watcher, once a scan of the root has started it (None before, or without
        watching)."""
        return self._watcher

    @Slot(bool)
    def window_active(self, active: bool) -> None:
        """The window gained (or lost) focus: where watching stopped, gaining it rescans the root
        (R2.4)."""
        if active and self._watcher is not None and self._watcher.why:
            self.rescan()

    def wrote(self, path: str, size: int, mtime_ns: int) -> None:
        """MusiKata wrote the file at `path` (under the root), leaving it `size` bytes modified at
        `mtime_ns`: a watched rescan doesn't read it again (A2.4, watch.OwnWrites)."""
        self._own.wrote(path, size, mtime_ns)

    @Slot(str)
    def show_playing(self, path: str) -> None:
        """Marks the song at `path`, and its album, as playing in the lists ("": none)."""
        self._playing = path
        self._mark_playing()

    def _mark_playing(self) -> None:
        r = (
            self._index.read()
            .execute("SELECT album_id FROM song WHERE path = ?", (self._playing,))
            .fetchone()
        )
        album = r[0] if r and r[0] is not None else -1
        self._songs.set_playing(self._playing)
        self._album.property("songs").set_playing(self._playing)
        self._artist.property("others").set_playing(self._playing)
        self._albums.set_playing(album)
        self._artist.property("albums").set_playing(album)

    def wait(self) -> None:
        """Until the scan's thread and the search thread have ended (their results still to be
        delivered)."""
        if self._thread is not None:
            self._thread.join()
        self._searcher.wait()

    def close(self) -> None:
        """Stops watching and waits for the threads: for closing. No scan starts after."""
        self._closed = True
        if self._watcher is not None:
            self._watcher.close()
        self.wait()

    # ---------- what QML reads ----------

    def _get_root(self) -> str:
        return shown_path(self._root, self._home)

    def _get_songs(self) -> SongsModel:
        return self._songs

    def _get_albums(self) -> AlbumsModel:
        return self._albums

    def _get_artists(self) -> ArtistsModel:
        return self._artists

    def _get_album(self) -> AlbumPage:
        return self._album

    def _get_artist(self) -> ArtistPage:
        return self._artist

    def _get_scanning(self) -> bool:
        return self._scanning

    def _get_line(self) -> str:
        return scanning_text(self._done, self._of) if self._scanning else summary(*self._counts)

    def _count_of(self, view: str) -> str:
        model = self._lists[view]
        return count_text(model.rowCount(), model.total(), NOUNS[view], model.filtered())

    def _get_count_text(self) -> str:
        return self._count_of("songs")

    def _get_album_count_text(self) -> str:
        return self._count_of("albums")

    def _get_artist_count_text(self) -> str:
        return self._count_of("artists")

    def _get_view_count(self) -> str:
        return self._count_of(self._view) if self._view in VIEWS else ""

    def _get_empty_text(self) -> str:
        """What the view open says when it lists nothing: the library empty, or a search that
        found nothing in it (R2.7)."""
        if not self._counts[0]:
            if self._scanning:
                return "Reading your music…"
            return f"No songs in {self._get_root()}"
        model = self._lists.get(self._view)
        if model is None or model.rowCount() or not model.shown_search().strip():
            return ""
        return no_match_text(model.shown_search(), NOUNS[self._view] + "s")

    def _get_search(self) -> str:
        return self._search

    def _get_searchable(self) -> bool:
        return self._view in VIEWS

    def _get_search_hint(self) -> str:
        return SEARCH_HINT

    def _get_searching(self) -> bool:
        """Whether the view open waits on the search thread's rows: the tour waits on it."""
        model = self._lists.get(self._view)
        return model is not None and model.pending()

    def _get_title(self) -> str:
        return TITLES.get(self._view, "")

    def _get_modes(self) -> list[dict[str, str]]:
        return MODES.get(self._view, [])

    def _get_mode(self) -> str:
        return self._albums_mode if self._view == "albums" else ""

    def _get_sorts(self) -> list[dict[str, str]]:
        if self._view == "albums":
            return [{"sort": k, "label": v} for k, v in ALBUM_SORT_LABELS.items()]
        if self._view == "artists":
            return [{"sort": "name", "label": "Name"}]
        return []  # Songs sorts by its columns' headers

    def _get_sort(self) -> str:
        if self._view == "albums":
            return self._albums.order()
        return "name" if self._view == "artists" else ""

    def _get_sort_text(self) -> str:
        labels = {s["sort"]: s["label"] for s in self._get_sorts()}
        return sort_text(labels.get(self._get_sort(), ""))

    def _get_song_headers(self) -> list[dict[str, str]]:
        return song_headers(*self._songs.order())

    def _get_view(self) -> str:
        return self._view

    def _get_section(self) -> str:
        """The sidebar's item highlighted: the view open, or the one a page was opened from."""
        if self._view in VIEWS:
            return self._view
        return next((v for v, _, _ in self._history if v in VIEWS), "albums")

    def _get_back_text(self) -> str:
        """Where the page's back link goes: the view or page it was opened from."""
        view = self._history[-1][0] if self._history else "albums"
        if view == "album":
            return str(self._album.property("title"))
        if view == "artist":
            return str(self._artist.property("name"))
        return TITLES[view]

    def _get_genres(self) -> list[str]:
        return self._chips[0]

    def _get_more_genres(self) -> list[str]:
        return self._chips[1]

    def _get_genre(self) -> str:
        return self._genre

    def _get_more_chosen(self) -> bool:
        return bool(self._genre) and self._genre in self._chips[1]

    def _get_more_text(self) -> str:
        return self._genre if self._get_more_chosen() else "More…"

    def _get_albums_mode(self) -> str:
        return self._albums_mode

    root = QtProperty(str, _get_root, constant=True)
    songs = QtProperty(QObject, _get_songs, constant=True)
    albums = QtProperty(QObject, _get_albums, constant=True)
    artists = QtProperty(QObject, _get_artists, constant=True)
    album = QtProperty(QObject, _get_album, constant=True)  # the album page's
    artist = QtProperty(QObject, _get_artist, constant=True)  # the artist page's
    scanning = QtProperty(bool, _get_scanning, notify=scanningChanged)
    line = QtProperty(str, _get_line, notify=changed)
    countText = QtProperty(str, _get_count_text, notify=changed)  # 1,412 songs; 12 of 1,412 songs
    albumCountText = QtProperty(str, _get_album_count_text, notify=changed)
    artistCountText = QtProperty(str, _get_artist_count_text, notify=changed)
    emptyText = QtProperty(str, _get_empty_text, notify=changed)  # what an empty view says
    # the header (R6.4): the view's title and count, the search box, the view modes and the sort
    title = QtProperty(str, _get_title, notify=viewChanged)
    viewCount = QtProperty(str, _get_view_count, notify=changed)
    search = QtProperty(str, _get_search, notify=searchChanged)
    searchable = QtProperty(bool, _get_searchable, notify=viewChanged)  # the header is shown
    searchHint = QtProperty(str, _get_search_hint, constant=True)
    searching = QtProperty(bool, _get_searching, notify=changed)
    modes = QtProperty(list, _get_modes, notify=viewChanged)  # [] where the view has one mode
    mode = QtProperty(str, _get_mode, notify=viewChanged)
    sorts = QtProperty(list, _get_sorts, notify=viewChanged)  # [] where columns sort (Songs)
    sort = QtProperty(str, _get_sort, notify=viewChanged)
    sortText = QtProperty(str, _get_sort_text, notify=viewChanged)  # Sort: Artist
    songHeaders = QtProperty(list, _get_song_headers, notify=viewChanged)
    view = QtProperty(str, _get_view, notify=viewChanged)  # albums, album, artists, artist, songs
    section = QtProperty(str, _get_section, notify=viewChanged)
    backText = QtProperty(str, _get_back_text, notify=viewChanged)
    genres = QtProperty(list, _get_genres, notify=changed)  # the chips after All
    moreGenres = QtProperty(list, _get_more_genres, notify=changed)  # More…'s
    genre = QtProperty(str, _get_genre, notify=changed)  # the chip chosen; "" for All
    moreText = QtProperty(str, _get_more_text, notify=changed)  # More…, or its genre chosen
    moreChosen = QtProperty(bool, _get_more_chosen, notify=changed)  # a genre of More…'s chosen
    albumsMode = QtProperty(str, _get_albums_mode, notify=viewChanged)  # Albums': grid or list


class Player(QObject):
    """The song playing, as QML sees it: its path under the root, whether it plays or is paused,
    where it is and how long it is, and why the last one couldn't play. The engine does the work
    on the playback thread (player.py); the two hear each other only by queued signals, so
    nothing here waits on it. The thread starts with the first song."""

    changed = Signal()  # the path, playing, paused, the length, the error
    positionChanged = Signal()
    nowPlaying = Signal(str)  # the path of the song playing now, "" when none
    _play = Signal(str)
    _pause = Signal()
    _resume = Signal()
    _stop = Signal()

    def __init__(
        self, root: str, engine: Engine | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._engine = engine if engine is not None else Engine()
        self._thread = PlaybackThread(self._engine)
        self._started = False
        self._path = ""
        self._paused = False
        self._position = self._length = 0.0
        self._error = ""
        self.last = ""  # how the last song stopped: "ended", "stopped" or "failed"
        self._play.connect(self._engine.play)
        self._pause.connect(self._engine.pause)
        self._resume.connect(self._engine.resume)
        self._stop.connect(self._engine.stop)
        self._engine.began.connect(self._on_began)
        self._engine.moved.connect(self._on_moved)
        self._engine.pausedChanged.connect(self._on_paused)
        self._engine.ended.connect(self._on_ended)
        self._engine.stopped.connect(self._on_stopped)
        self._engine.failed.connect(self._on_failed)

    def _under_root(self, path: str) -> str:
        return os.path.relpath(path, self._root).replace(os.sep, "/")

    # ---------- what QML asks ----------

    @Slot(str)
    def play(self, path: str) -> None:
        """Plays the song at `path` under the root (the index's path) from its start (R7.1); ""
        (an album with no songs) does nothing."""
        if not path:
            return
        self.play_file(os.path.join(self._root, *path.split("/")))

    def play_file(self, path: str) -> None:
        """Plays the file at `path`, a whole path, from its start."""
        if not self._started:
            self._thread.start()
            self._started = True
        self._play.emit(path)

    @Slot()
    def pause(self) -> None:
        self._pause.emit()

    @Slot()
    def resume(self) -> None:
        self._resume.emit()

    @Slot()
    def stop(self) -> None:
        self._stop.emit()

    def close(self) -> None:
        """Stops the song and ends the playback thread: for closing."""
        self._thread.close()

    # ---------- what the engine says ----------

    @Slot(str, float)
    def _on_began(self, path: str, length: float) -> None:
        self._path, self._paused, self._error = self._under_root(path), False, ""
        self._length, self._position = max(0.0, length), 0.0
        self.changed.emit()
        self.positionChanged.emit()
        self.nowPlaying.emit(self._path)

    @Slot(float)
    def _on_moved(self, seconds: float) -> None:
        self._position = seconds
        self.positionChanged.emit()

    @Slot(bool)
    def _on_paused(self, paused: bool) -> None:
        self._paused = paused
        self.changed.emit()

    def _done(self, how: str, error: str = "") -> None:
        self.last, self._error = how, error
        self._path, self._paused = "", False
        self._position = self._length = 0.0
        self.changed.emit()
        self.positionChanged.emit()
        self.nowPlaying.emit("")

    @Slot(str)
    def _on_ended(self, path: str) -> None:
        self._done("ended")

    @Slot(str)
    def _on_stopped(self, path: str) -> None:
        self._done("stopped")

    @Slot(str, str)
    def _on_failed(self, path: str, why: str) -> None:
        self._done("failed", why)

    # ---------- what QML reads ----------

    def _get_path(self) -> str:
        return self._path

    def _get_playing(self) -> bool:
        return bool(self._path) and not self._paused

    def _get_paused(self) -> bool:
        return self._paused

    def _get_position(self) -> float:
        return self._position

    def _get_length(self) -> float:
        return self._length

    def _get_error(self) -> str:
        return self._error

    path = QtProperty(str, _get_path, notify=changed)  # the song's path under the root; "": none
    playing = QtProperty(bool, _get_playing, notify=changed)  # a song plays, not paused
    paused = QtProperty(bool, _get_paused, notify=changed)
    position = QtProperty(float, _get_position, notify=positionChanged)  # seconds
    length = QtProperty(float, _get_length, notify=changed)  # seconds; 0 when unknown
    error = QtProperty(str, _get_error, notify=changed)  # why the last song couldn't play
