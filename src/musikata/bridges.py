"""The objects QML sees (A1.2). `Library`: the root, its card's line, the views and going between
them (R2.6, R6.3), the header (R6.4: the view's title and count, the search, the view mode and the
sort), Albums with its genre chips and Artists, an album's and an artist's pages, Folders (its open
folder and list are folders.py's, R2.9), and the scans,
run one at a time on a thread of their own with the worker processes reading the files (A1.3,
A2.2): the root's, and the partial ones of the folders the watcher names (A2.4, R2.4); the root's
card, and a root that isn't there (R2.1.1, R2.10).
`Player`: the song playing and the queue (R7.1 to R7.3), the now-playing bar (R6.5) and Up next
(R7.2), the songs played on the playback thread (player.py, A4.1).

What the root's card and the pages say is decided here, as text (`docs/process/coding.md`: QML only
lays out and binds)."""

from __future__ import annotations

import itertools
import logging
import os
import random
import sqlite3
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import BrokenExecutor, Executor
from typing import Any, Protocol

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, QUrl, Signal, Slot

from musikata_core import albums, db, scanner, watch, workers
from musikata_core.audio.queue import Entry, Queue
from musikata_core.clock import Clock, SystemClock

from .folders import MODES as folders_modes
from .folders import SEARCH_HINT as FOLDERS_SEARCH_HINT
from .folders import FolderView, Remembered
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
    format_text,
    length_text,
    no_match_text,
    plural,
    size_text,
    song_headers,
    tiles,
    time_text,
    title_of,
)
from .nowplaying import (
    REPEAT_NAMES,
    RESTART_AFTER,
    SEEK_STEP,
    SongInfo,
    UpNextModel,
    bar_line,
    read_songs,
    song_of_path,
)
from .player import Engine, PlaybackThread, gain_of

log = logging.getLogger(__name__)


def local_folder(folder: str) -> str | None:
    """A folder chosen or dropped (R2.1), as a path or a file: URL, as a whole path; None when it
    isn't a folder."""
    path = QUrl(folder).toLocalFile() if folder.startswith("file:") else folder
    path = os.path.abspath(os.path.expanduser(path)) if path else ""
    return path if path and os.path.isdir(path) else None


def shown_path(path: str, home: str) -> str:
    """A path as MusiKata shows it: under the home folder as ~/…, with the system's separator."""
    home = home.rstrip("/\\")
    if home and (path == home or path.startswith(home + os.sep)):
        return "~" + path[len(home) :]
    return path


def summary(songs: int, albums: int, size: int) -> str:
    """The root card's line (R2.1.1): 1,412 songs · 128 albums · 9.8 GB."""
    if not songs:
        return "No songs yet"
    return " · ".join((plural(songs, "song"), plural(albums, "album"), size_text(size)))


def scanning_text(done: int, of: int) -> str:
    """The root card's line while a scan runs (R2.3)."""
    return f"Scanning… {done:,} of {of:,}" if of else "Scanning…"


APP = "MusiKata"


def window_title(root: str, given: bool) -> str:
    """The window's title: the app's name, and the root's when it was given for this run only, so
    a library that isn't the usual one is never mistaken for it (R2.1.2):
    MusiKata — /media/usb/Music."""
    return f"{APP} — {root}" if given else APP


def banner(root: str, missing: bool, links: list[str]) -> dict[str, object]:
    """The banner across the view (R2.10, X02-root-unavailable): the root that isn't there (shown
    as `root`), or else the linked folders that can't be reached (R2.3.2), each shown as its whole
    path, named; {} when all is there. `choose` says whether it offers Choose another folder…,
    which is for the root."""
    if missing:
        return {
            "title": f"{root} isn't available. Its drive may be unplugged or its share not"
            " mounted.",
            "detail": "Your library is kept. Playing and changes to files wait until it's back.",
            "choose": True,
        }
    if not links:
        return {}
    if len(links) == 1:
        return {
            "title": f"{links[0]} isn't available. Its drive may be unplugged or its share not"
            " mounted.",
            "detail": "Its songs are kept. Playing them waits until it's back.",
            "choose": False,
        }
    others = plural(len(links) - 1, "other linked folder")
    return {
        "title": f"{links[0]} and {others} aren't available. Their drives may be unplugged or their"
        " shares not mounted.",
        "detail": "Their songs are kept. Playing them waits until they're back.",
        "choose": False,
    }


def question(root: str, gone: int) -> dict[str, str]:
    """Asking before taking out the songs a scan found gone (R2.10.1): its text and its two
    answers; {} when there is nothing to ask."""
    if not gone:
        return {}
    if gone == 1:
        return {
            "text": f"1 song is missing from {root}. Remove it from the library?",
            "keep": "Keep it",
            "remove": "Remove",
        }
    return {
        "text": f"{gone:,} songs are missing from {root}. Remove them from the library?",
        "keep": "Keep them",
        "remove": "Remove",
    }


SHOWN_UNREADABLE = 3  # files the dot's tooltip names before "and n more"


def dot(missing: bool, scanning: bool, unreadable: int, links: int) -> str:
    """The root card's dot (R2.1.1): "missing" (red, R2.10), "scanning" (turning), "warn" (amber:
    files that couldn't be read, or linked folders that can't be reached) or "ok" (green: up to
    date)."""
    if missing:
        return "missing"
    if scanning:
        return "scanning"
    return "warn" if unreadable or links else "ok"


def dot_tip(
    state: str, root: str, unreadable: int, names: list[tuple[str, str]], links: list[str]
) -> str:
    """What the dot's tooltip says (R2.1.1): the state, and when amber, what couldn't be read
    (`names`: the first files' paths and why) and the linked folders that can't be reached."""
    if state == "missing":
        return f"{root} isn't available"
    if state == "scanning":
        return f"Scanning {root}"
    if state == "ok":
        return "Up to date"
    lines = []
    if unreadable:
        lines.append(f"{plural(unreadable, 'file')} couldn't be read:")
        lines += [f"{path}: {why}" for path, why in names[:SHOWN_UNREADABLE]]
        if unreadable > SHOWN_UNREADABLE:
            lines.append(f"and {unreadable - SHOWN_UNREADABLE:,} more")
    lines += [f"{link} can't be reached" for link in links]
    return "\n".join(lines)


def counts(c: sqlite3.Connection) -> tuple[int, int, int]:
    """Songs, albums (R2.5.2) and bytes."""
    r = c.execute(
        "SELECT COUNT(*), (SELECT COUNT(*) FROM album), coalesce(SUM(size), 0) FROM song"
    ).fetchone()
    return int(r[0]), int(r[1]), int(r[2])


CHIPS = 8  # genre chips shown before More… (R2.6)


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
        self._songs.source = title
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
        self._others.source = name
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


VIEWS = ("albums", "artists", "songs", "folders")  # the sidebar's views built so far (R6.3)
TITLES = {"albums": "Albums", "artists": "Artists", "songs": "Songs", "folders": "Folders"}
NOUNS = {"albums": "album", "artists": "artist", "songs": "song"}  # what each view counts
SEARCH_HINT = "Search the library"
# the view modes each view has (R6.4; Albums' grid and list, R2.6; Folders' four, R2.9.4): its
# name, label and icon
MODES = {"albums": [{"mode": "grid", "label": "Grid", "icon": "grid"},
                    {"mode": "list", "label": "List", "icon": "list"}],
         "folders": folders_modes}  # fmt: skip


def sort_text(label: str) -> str:
    """The header's sort button (R6.4): Sort: Artist."""
    return f"Sort: {label}" if label else ""


class Library(QObject):
    """One root and its index, as the sidebar and the views see them: which view is open and the
    way back from a page (R6.3), Albums and its genre chips, Artists, Songs, and the pages; and
    its scans. With `watching`, a scan of the root starts watching it (A2.4): a change the watcher
    reports is rescanned, its folders only, and the views read again where they are. `remembered`:
    where Folders was left, which it opens at (R2.9.1; folders.Remembered).

    The root's card (R2.1.1) and a root that isn't there (R2.10): `missing` when it isn't, at
    start or found gone by a scan or a look; then the library stays as it was, the banner says so,
    playing waits (`unplayable`), and the root is looked for every few seconds (watch.Presence,
    `looking` a test's stand-in for the look) and rescanned when it comes back. Linked folders
    that can't be reached are the same for their own songs. Songs a scan found gone, more than a
    quarter of the library, wait on the question of R2.10.1. `given`: the root is for this run
    only (R2.1.2), and the window's title names it. Choose another folder… says which with
    `rootChosen`, for app.Session to open it. `pool` makes the worker processes (A1.3), once,
    when a scan first needs them; they end with `close`, or are made anew when one has died."""

    changed = Signal()  # the card's line, the counts, the genre chips, the empty texts
    scanningChanged = Signal()
    viewChanged = Signal()  # the view, and its header's title, modes and sorts
    searchChanged = Signal()
    rootChosen = Signal(str)  # Choose another folder… (R2.10): the folder chosen, a whole path
    _progress = Signal(int, int)
    _finished = Signal(object)
    _reached = Signal(str, str, object)  # a folder a scan's walk listed (scanner.Reached)

    def __init__(
        self,
        root: str,
        index: db.Index,
        home: str,
        pool: Callable[[], Executor] = workers.pool,
        parent: QObject | None = None,
        clock: Clock | None = None,
        watching: bool = False,
        remembered: Remembered | None = None,
        missing: bool = False,
        given: bool = False,
        looking: Callable[[str, frozenset[str]], tuple[bool, frozenset[str]]] = watch.there,
        look_every: float = watch.LOOK,
    ) -> None:
        super().__init__(parent)
        self._root, self._index, self._home, self._pool = root, index, home, pool
        self._workers: Executor | None = None  # the worker processes, once a scan needs them
        self._clock = clock if clock is not None else SystemClock()
        self._watching = watching
        self._watcher: watch.Watcher | None = None
        self._own = watch.OwnWrites(self._clock)
        self._copied: dict[str, str] = {}  # copies made while watching (scanner.scan)
        self._searcher = Searcher(self)
        self._songs = SongsModel(index.read, parent=self, searcher=self._searcher)
        self._songs.source = "Songs"
        self._albums = AlbumsModel(index.read, self, searcher=self._searcher)
        self._artists = ArtistsModel(index.read, self, self._searcher)
        self._folders = FolderView(index.read, remembered, self, self._searcher)
        self._folders.opened.connect(self._on_folder_opened)
        self._folders.modeChanged.connect(self.viewChanged)
        self._lists: dict[str, PagedModel] = {
            "albums": self._albums, "artists": self._artists, "songs": self._songs,
            "folders": self._folders.property("model"),
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
        self._reached.connect(self._on_reached)
        self._counts = (0, 0, 0)
        self._given = given
        self._missing = missing  # the root isn't there (R2.10)
        self._links: frozenset[str] = frozenset()  # linked folders that can't be reached
        self._held: list[str] = []  # songs gone, waiting on the user's answer (R2.10.1)
        self._kept: set[str] = set()  # songs gone the user said to keep, not asked about again
        self._removing: list[str] = []  # songs gone the user said to remove, waiting their turn
        self._taking: set[str] = set()  # those being taken out now
        self._unreadable: tuple[int, list[tuple[str, str]]] = (0, [])
        self._presence = watch.Presence(root, looking, look_every, self)
        self._presence.found.connect(self._on_found)
        if missing:
            self._presence.start()
        self.reload()

    def reload(self) -> None:
        """Reads the lists, the counts and the chips afresh (after a scan), and the open page,
        each list where it is, with its search, so the user keeps their place; a page whose album
        or artist went shows the view it was opened from."""
        self._songs.refresh()
        self._albums.refresh()
        self._artists.refresh()
        self._folders.reload()
        c = self._index.read()
        self._counts = counts(c)
        self._unreadable = (
            c.execute("SELECT COUNT(*) FROM song WHERE error IS NOT NULL").fetchone()[0],
            c.execute(
                "SELECT path, error FROM song WHERE error IS NOT NULL ORDER BY path LIMIT ?",
                (SHOWN_UNREADABLE,),
            ).fetchall(),
        )
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
        every search: the view opens whole. Folders opens at the folder left open; asked for again
        while it shows, it returns to the root (R2.9.1)."""
        if view not in VIEWS:
            raise ValueError(f"no such view: {view}")
        again = view == self._view == "folders"
        self._history.clear()
        for model in self._lists.values():
            if model.searching():
                model.set_search("")
        if again:
            self._folders.open("")
        self._go(view, "")

    def _on_folder_opened(self) -> None:
        """Another folder opened: its search is gone (the model's went with it)."""
        if self._view == "folders" and self._search:
            self._search = ""
            self.searchChanged.emit()
        self.viewChanged.emit()
        self.changed.emit()

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
        elif self._view not in ("artists", "folders") or sort != "name":
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
        "album": "Glass Harbor"}, {"view": "artist", "artist": "Lumen Drift"}; or Folders at a
        folder, in a mode, with rows selected: {"view": "folders", "folder": "Lumen Drift",
        "mode": "large", "select": ["Lumen Drift/Remixes"]}."""
        view = step["view"]
        c = self._index.read()
        if view == "folders":
            self.show("folders")
            self._folders.open(step.get("folder", ""))
            self._folders.setMode(step.get("mode", self._folders.property("mode")))
            self.setSearch(step.get("search", ""))
            self._folders.select_paths(step.get("select", []))
        elif view == "album":
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
    def setMode(self, mode: str) -> None:  # noqa: N802
        """The header's view switch (R6.4): Albums' grid or list, Folders' four modes (R2.9.4)."""
        if self._view == "folders":
            self._folders.setMode(mode)
        else:
            self.setAlbumsMode(mode)

    @Slot(str)
    def setAlbumsMode(self, mode: str) -> None:  # noqa: N802
        """Albums as a grid of covers or a list (R2.6, the header's view switch, R6.4)."""
        if mode not in ("grid", "list"):
            raise ValueError(f"no such mode: {mode}")
        self._albums_mode = mode
        self.viewChanged.emit()

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
        expected, copied, keep = self._own.expected(), dict(self._copied), set(self._kept)
        self._thread = threading.Thread(
            target=self._scan, args=(scope, expected, copied, keep), name="scan", daemon=True
        )
        self._thread.start()

    def _scan(
        self,
        scope: scanner.Scope | None,
        expected: dict[str, tuple[int, int]],
        copied: dict[str, str],
        keep: set[str],
    ) -> None:
        result: scanner.Result | BaseException
        try:
            if self._workers is None:  # started when first needed, kept for the run (A1.3)
                self._workers = self._pool()
            result = scanner.scan(
                self._root,
                self._index,
                self._workers,
                progress=self._progress.emit if scope is None else None,
                scope=scope,
                expected=expected,
                copied=copied,
                keep=keep,
                reached=self._reached.emit if self._watching else None,
            )
        except Exception as e:  # noqa: BLE001  (the scan's failure is shown, and MusiKata goes on)
            log.exception("the scan of %s failed", self._root)
            if isinstance(e, BrokenExecutor) and self._workers is not None:
                # a worker process died: the next scan starts them anew
                self._workers.shutdown(wait=False)
                self._workers = None
            result = e
        self.last = result
        self._finished.emit((scope is None, result))

    @Slot(int, int)
    def _on_progress(self, done: int, of: int) -> None:
        """A batch of a scan of the root written: the views fill as it goes (R2.3)."""
        self._done, self._of = done, of
        self.reload()

    @Slot(object)
    def _on_finished(self, finished: tuple[bool | None, scanner.Result | BaseException]) -> None:
        """A scan ended (whole: the root's, or a partial one), or a removal (whole None)."""
        whole, result = finished
        self._busy = False
        if whole is None:
            self._taking = set()
            if isinstance(result, scanner.Result) and result.missing and not self._closed:
                self._went()
            self.reload()
            self._next()
            return
        if isinstance(result, scanner.Result) and not self._closed:
            if result.missing:
                self._went()
            else:
                self._copied = result.copied
                self._watch(whole, result)
                self._found_there(whole, result)
        if whole:
            self._scanning = False
        self.reload()
        if whole:
            self.scanningChanged.emit()
        self._next()

    def _next(self) -> None:
        """The next scan, once one has ended: the songs the user said to remove (R2.10.1), the
        root's, if asked for meanwhile, else the folders gathered and due."""
        if self._busy or self._closed:
            return
        if self._removing:
            self._start_removal()
        elif self._scanning:
            self._start(None)
        elif self._watcher is not None and self._watcher.due():
            folders = self._watcher.take()
            if folders:
                self._start(scanner.Scope(folders, self._watcher.known()))

    # ---------- a root that isn't there (R2.10, R2.10.1) ----------

    def _went(self) -> None:
        """The root isn't there: the library stays as it was, its watches went with it, and it is
        looked for until it comes back."""
        if not self._missing:
            log.warning("%s isn't there: its library is kept as it was", self._root)
        self._missing = True
        if self._watcher is not None:  # its watches went with it: the next scan watches anew
            self._watcher.close()
            self._watcher.deleteLater()
            self._watcher = None
        self._presence.start()
        self.changed.emit()

    def _found_there(self, whole: bool, result: scanner.Result) -> None:
        """After a scan that found the root: the linked folders out of reach (a scan of the root
        says which; a partial one, those it met, and those it walked are back), and the songs gone
        that wait on the user's answer."""
        self._missing = False
        walked = set(result.folders)
        answered = set(self._removing) | self._taking
        if whole:
            self._set_links(frozenset(result.unreachable))
            self._held = [p for p in result.held if p not in answered]
        else:
            self._set_links(frozenset((self._links - walked) | result.unreachable))
            self._held = sorted((set(self._held) | set(result.held)) - answered)
        if self._links:
            self._presence.start()
        else:
            self._presence.stop()

    def _set_links(self, links: frozenset[str]) -> None:
        self._links = self._presence.links = links

    @Slot(bool, object)
    def _on_found(self, there: bool, links: frozenset[str]) -> None:
        """A look's answer: a root gone is the library kept; a root, or a linked folder, back is
        rescanned, and its banner goes."""
        if self._closed:
            return
        if not there:
            if not self._missing:
                self._went()
            return
        back = self._missing or bool(self._links - links)
        if back:
            log.info("%s is there again: rescanning it", self._root)
            self._missing = False
            self._set_links(frozenset(links))
            self.rescan()
        if not self._links:
            self._presence.stop()
        self.changed.emit()

    @Slot()
    def retry(self) -> None:
        """Try again (R2.10): looks for the root, and the linked folders out of reach, now."""
        self._presence.look()

    @Slot(str)
    def chooseRoot(self, folder: str) -> None:  # noqa: N802
        """Choose another folder… (R2.10, R2.1): the folder chosen, a path or a file: URL, said
        with `rootChosen` when it is a folder."""
        path = local_folder(folder)
        if path is None:
            log.warning("didn't open %s as the music root: it isn't a folder", folder)
            return
        self.rootChosen.emit(path)

    @Slot()
    def keepMissing(self) -> None:  # noqa: N802
        """Keep them (R2.10.1): the songs gone stay, and aren't asked about again while MusiKata
        runs."""
        self._kept |= set(self._held)
        self._held = []
        self.changed.emit()

    @Slot()
    def removeMissing(self) -> None:  # noqa: N802
        """Remove (R2.10.1): the songs gone are taken out of the library, on the scan's thread
        when no scan runs."""
        self._removing += self._held
        self._held = []
        self.changed.emit()
        self._next()

    def _start_removal(self) -> None:
        self._busy = True
        paths, self._removing = self._removing, []
        self._taking = set(paths)
        self._thread = threading.Thread(
            target=self._remove, args=(paths,), name="scan", daemon=True
        )
        self._thread.start()

    def _remove(self, paths: list[str]) -> None:
        result = scanner.Result(missing=not os.path.isdir(self._root))
        try:
            result.removed = scanner.remove(self._root, self._index, paths)
        except Exception:  # noqa: BLE001  (logged, and MusiKata goes on with the songs kept)
            log.exception("taking the missing songs out of %s failed", self._root)
        self._finished.emit((None, result))

    def unplayable(self, path: str) -> str:
        """Why the song at `path` (under the root) can't play now: its root or its linked folder
        isn't there (R2.10); "" when it can."""
        if self._missing:
            return self._get_play_note()
        link = next((f for f in sorted(self._links) if scanner.under(path, {f})), None)
        if link is not None:
            return f"{self._shown(link)} isn't available, so its songs can't play"
        return ""

    def _shown(self, folder: str) -> str:
        """A folder under the root (a path with /) as MusiKata shows it, whole."""
        return shown_path(scanner.full_path(self._root, folder), self._home)

    # ---------- watching (A2.4, R2.4) ----------

    def _watcher_now(self) -> watch.Watcher:
        """The root's watcher, made when first needed."""
        if self._watcher is None:
            self._watcher = watch.Watcher(self._root, watch.Gatherer(self._clock), parent=self)
            self._watcher.ready.connect(self._next)
        return self._watcher

    @Slot(str, str, object)
    def _on_reached(self, folder: str, real: str, listed: int) -> None:
        """A folder a scan's walk listed: watched from then on, so what changes while the scan
        goes on is rescanned after it (A2.4)."""
        if self._watching and not self._closed and not self._missing:
            self._watcher_now().reached(folder, real, listed)

    def _watch(self, whole: bool, result: scanner.Result) -> None:
        """After a scan: the folders it walked watched, those it found gone not."""
        if not self._watching:
            return
        self._watcher = self._watcher_now()
        if whole:
            self._watcher.watch(result.folders)
        else:
            self._watcher.update(result.folders, result.gone_folders)
        self._watcher.scanned(result.read)

    @property
    def watcher(self) -> watch.Watcher | None:
        """The root's watcher, once a scan's walk has started it (None before, or without
        watching)."""
        return self._watcher

    @Slot(bool)
    def window_active(self, active: bool) -> None:
        """The window gained (or lost) focus: where watching stopped, gaining it rescans the root
        (R2.4); and it looks for the root, which may have gone or come back meanwhile (R2.10)."""
        if not active:
            return
        self._presence.look()
        if self._watcher is not None and self._watcher.why and not self._missing:
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
        self._folders.property("model").set_playing(self._playing)
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
        """Stops watching, waits for the threads and ends the worker processes: for closing. No
        scan starts after."""
        self._closed = True
        self._presence.close()
        if self._watcher is not None:
            self._watcher.close()
        self.wait()
        if self._workers is not None:
            self._workers.shutdown()
            self._workers = None

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

    def _get_folders(self) -> FolderView:
        return self._folders

    def _get_scanning(self) -> bool:
        return self._scanning

    def _get_line(self) -> str:
        if self._missing:
            return "Not available"
        return scanning_text(self._done, self._of) if self._scanning else summary(*self._counts)

    def _get_available(self) -> bool:
        return not self._missing

    def _get_dot(self) -> str:
        return dot(self._missing, self._scanning, self._unreadable[0], len(self._links))

    def _get_dot_tip(self) -> str:
        links = [self._shown(f) for f in sorted(self._links)]
        return dot_tip(self._get_dot(), self._get_root(), *self._unreadable, links)

    def _get_banner(self) -> dict[str, object]:
        links = [self._shown(f) for f in sorted(self._links)]
        return banner(self._get_root(), self._missing, links)

    def _get_question(self) -> dict[str, str]:
        return question(self._get_root(), len(self._held))

    def _get_play_note(self) -> str:
        """Why nothing plays (R2.10): the root isn't there; "" when it is."""
        return f"Playing waits until {self._get_root()} is back" if self._missing else ""

    def _get_window_title(self) -> str:
        return window_title(self._get_root(), self._given)

    def _count_of(self, view: str) -> str:
        if view == "folders":
            return str(self._folders.property("count"))
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
        many = NOUNS[self._view] + "s" if self._view in NOUNS else "folders or songs"
        return no_match_text(model.shown_search(), many)

    def _get_search(self) -> str:
        return self._search

    def _get_searchable(self) -> bool:
        return self._view in VIEWS

    def _get_search_hint(self) -> str:
        return FOLDERS_SEARCH_HINT if self._view == "folders" else SEARCH_HINT

    def _get_searching(self) -> bool:
        """Whether the view open waits on the search thread's rows: the tour waits on it."""
        model = self._lists.get(self._view)
        return model is not None and model.pending()

    def _get_title(self) -> str:
        if self._view == "folders":
            return str(self._folders.property("title"))
        return TITLES.get(self._view, "")

    def _get_crumbs(self) -> list[dict[str, str]]:
        """Folders' title as the open folder's path, a crumb per folder (R2.9.1); none at the
        root or in another view."""
        return list(self._folders.property("crumbs")) if self._view == "folders" else []

    def _get_modes(self) -> list[dict[str, str]]:
        return MODES.get(self._view, [])

    def _get_mode(self) -> str:
        if self._view == "folders":
            return str(self._folders.property("mode"))
        return self._albums_mode if self._view == "albums" else ""

    def _get_sorts(self) -> list[dict[str, str]]:
        if self._view == "albums":
            return [{"sort": k, "label": v} for k, v in ALBUM_SORT_LABELS.items()]
        if self._view in ("artists", "folders"):
            return [{"sort": "name", "label": "Name"}]
        return []  # Songs sorts by its columns' headers

    def _get_sort(self) -> str:
        if self._view == "albums":
            return self._albums.order()
        return "name" if self._view in ("artists", "folders") else ""

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
    windowTitle = QtProperty(str, _get_window_title, constant=True)  # MusiKata — ~/Music (R2.1.2)
    available = QtProperty(bool, _get_available, notify=changed)  # the root is there (R2.10)
    dot = QtProperty(str, _get_dot, notify=changed)  # the card's dot: ok, scanning, warn, missing
    dotTip = QtProperty(str, _get_dot_tip, notify=changed)
    banner = QtProperty(dict, _get_banner, notify=changed)  # {} when there is none (R2.10)
    question = QtProperty(dict, _get_question, notify=changed)  # {} when none (R2.10.1)
    playNote = QtProperty(str, _get_play_note, notify=changed)  # why Play waits; "" when it can
    songs = QtProperty(QObject, _get_songs, constant=True)
    albums = QtProperty(QObject, _get_albums, constant=True)
    artists = QtProperty(QObject, _get_artists, constant=True)
    album = QtProperty(QObject, _get_album, constant=True)  # the album page's
    artist = QtProperty(QObject, _get_artist, constant=True)  # the artist page's
    folders = QtProperty(QObject, _get_folders, constant=True)  # Folders' open folder (R2.9)
    scanning = QtProperty(bool, _get_scanning, notify=scanningChanged)
    line = QtProperty(str, _get_line, notify=changed)
    countText = QtProperty(str, _get_count_text, notify=changed)  # 1,412 songs; 12 of 1,412 songs
    albumCountText = QtProperty(str, _get_album_count_text, notify=changed)
    artistCountText = QtProperty(str, _get_artist_count_text, notify=changed)
    emptyText = QtProperty(str, _get_empty_text, notify=changed)  # what an empty view says
    # the header (R6.4): the view's title and count, the search box, the view modes and the sort
    title = QtProperty(str, _get_title, notify=viewChanged)
    crumbs = QtProperty(list, _get_crumbs, notify=viewChanged)
    viewCount = QtProperty(str, _get_view_count, notify=changed)
    search = QtProperty(str, _get_search, notify=searchChanged)
    searchable = QtProperty(bool, _get_searchable, notify=viewChanged)  # the header is shown
    searchHint = QtProperty(str, _get_search_hint, notify=viewChanged)
    searching = QtProperty(bool, _get_searching, notify=changed)
    modes = QtProperty(list, _get_modes, notify=viewChanged)  # [] where the view has one mode
    mode = QtProperty(str, _get_mode, notify=viewChanged)
    sorts = QtProperty(list, _get_sorts, notify=viewChanged)  # [] where columns sort (Songs)
    sort = QtProperty(str, _get_sort, notify=viewChanged)
    sortText = QtProperty(str, _get_sort_text, notify=viewChanged)  # Sort: Artist
    songHeaders = QtProperty(list, _get_song_headers, notify=viewChanged)
    view = QtProperty(str, _get_view, notify=viewChanged)  # albums, …, songs, folders
    section = QtProperty(str, _get_section, notify=viewChanged)
    backText = QtProperty(str, _get_back_text, notify=viewChanged)
    genres = QtProperty(list, _get_genres, notify=changed)  # the chips after All
    moreGenres = QtProperty(list, _get_more_genres, notify=changed)  # More…'s
    genre = QtProperty(str, _get_genre, notify=changed)  # the chip chosen; "" for All
    moreText = QtProperty(str, _get_more_text, notify=changed)  # More…, or its genre chosen
    moreChosen = QtProperty(bool, _get_more_chosen, notify=changed)  # a genre of More…'s chosen
    albumsMode = QtProperty(str, _get_albums_mode, notify=viewChanged)  # Albums': grid or list


class Queueable(Protocol):
    """A list of songs QML plays from (R7.1) or queues from (R7.2): the Songs list, an album's or
    an artist's songs, Folders."""

    def queue_from(self, row: int) -> tuple[list[int], str]:
        """The songs a double click on row `row` plays (it and the rest of the list after it),
        and the list's name."""
        ...

    def songs_at(self, row: int) -> list[int]:
        """The songs row `row` stands for: its own, or those beneath a folder."""
        ...


class Player(QObject):
    """The song playing and the queue (R7.1 to R7.3), as QML sees them: the now-playing bar (R6.5)
    and Up next (R7.2). The engine does the playing on the playback thread (player.py); the two
    hear each other only by queued signals, so nothing here waits on it. The thread starts with
    the first song.

    The queue's current song is shown whether or not it plays: cued, it waits paused at its start
    for play (the tour's, and R1.8's restored queue). The engine is told what follows the song
    playing, and again whenever that changes, and joins it with no gap (A4.2); the bar, the playing
    row and Up next move on when the engine hears the next song begin. A song that ends with
    nothing joined to it starts the one after it (R7.1), until the queue has played out; a song
    that can't play stops there and says why. Each song asked of the engine carries a ticket, and
    what the engine says of a ticket no longer asked for is passed over.
    `read` reads the index, where a song's id becomes its path and its words; without it (a test
    of the engine alone) a path plays on its own, outside any queue."""

    changed = Signal()  # the song: its path, words, playing, paused, the length, the error
    positionChanged = Signal()
    queueChanged = Signal()  # shuffle, repeat, Up next open
    volumeChanged = Signal()
    nowPlaying = Signal(str)  # the path of the song playing or cued now, "" when none
    _play = Signal(str, int)
    _follow = Signal(int, int, str)
    _seek = Signal(int, float)
    _pause = Signal()
    _resume = Signal()
    _stop = Signal()
    _set_gain = Signal(float)

    def __init__(
        self,
        root: str,
        engine: Engine | None = None,
        parent: QObject | None = None,
        refuse: Callable[[str], str] | None = None,
        read: Callable[[], sqlite3.Connection] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(parent)
        self._root = root
        self._refuse = refuse  # why a song can't play now (Library.unplayable, R2.10)
        self._read = read
        self._engine = engine if engine is not None else Engine()
        self._thread = PlaybackThread(self._engine)
        self._started = False
        self.queue = Queue(rng)
        self._up_next = UpNextModel(read, self.queue, self)
        self._up_next_open = False
        self._info: SongInfo | None = None  # the shown song's words, when the index has it
        self._path = ""  # the shown song's path under the root
        self._tickets = itertools.count(1)
        self._requested = 0  # the ticket of the song the engine was last asked to play
        self._playing_key: int | None = None  # the queue's entry it plays; None: outside the queue
        self._followed: tuple[int, int | None] | None = None  # the ticket and entry last told to
        # follow it (0 and None: nothing); None when nothing was told yet
        self._follows: set[int] = set()  # every ticket told to follow it
        self._seeking = 0  # seeks asked for and not yet done: the position is the place sought
        self._on = False  # the engine has a song, playing or paused
        self._paused = False
        self._position = self._length = 0.0
        self._error = ""
        self._volume = 1.0
        self.last = ""  # how the last song stopped: "ended", "stopped" or "failed"
        self._play.connect(self._engine.play)
        self._follow.connect(self._engine.follow)
        self._seek.connect(self._engine.seek)
        self._pause.connect(self._engine.pause)
        self._resume.connect(self._engine.resume)
        self._stop.connect(self._engine.stop)
        self._set_gain.connect(self._engine.set_volume)
        self._engine.began.connect(self._on_began)
        self._engine.joined.connect(self._on_joined)
        self._engine.sought.connect(self._on_sought)
        self._engine.moved.connect(self._on_moved)
        self._engine.pausedChanged.connect(self._on_paused)
        self._engine.ended.connect(self._on_ended)
        self._engine.stopped.connect(self._on_stopped)
        self._engine.failed.connect(self._on_failed)

    def _under_root(self, path: str) -> str:
        return os.path.relpath(path, self._root).replace(os.sep, "/")

    def _whole(self, path: str) -> str:
        return os.path.join(self._root, *path.split("/"))

    # ---------- what QML asks: playing from a list (R7.1) ----------

    @Slot(str)
    def play(self, path: str) -> None:
        """Plays the song at `path` under the root (the index's path) from its start, as a queue
        of its own; "" (an album with no songs) does nothing. A song whose root, or linked folder,
        isn't there doesn't play, and `error` says why (R2.10); the song playing goes on."""
        if not path:
            return
        song = song_of_path(self._read(), path) if self._read is not None else None
        if song is None:
            why = self._refuse(path) if self._refuse is not None else ""
            if why:
                self._error = why
                self.changed.emit()
                return
            self.play_file(self._whole(path))
            return
        self.play_songs([song], "")

    def play_songs(self, songs: Sequence[int], source: str, start: int | None = 0) -> None:
        """The queue becomes `songs` from `source` (R7.1), and its first song plays; `start` None
        plays from a random one while shuffling (Play on an album)."""
        entry = self.queue.play(songs, start, source)
        if entry is not None:
            self._start(entry)
        else:
            self._queue_changed()

    @Slot(QObject, int)
    def playFrom(self, songs: Queueable, row: int) -> None:  # noqa: N802
        """A double click on a song of a list: it plays, and the rest of the list after it is the
        queue (R7.1)."""
        ids, source = songs.queue_from(row)
        self.play_songs(ids, source)

    @Slot(int)
    def playAlbum(self, album_id: int) -> None:  # noqa: N802
        """Play on an album: its songs by disc and track, from its first (R7.1)."""
        self.play_songs(*self._album(album_id), start=None)

    @Slot(int)
    def shuffleAlbum(self, album_id: int) -> None:  # noqa: N802
        """An album's Shuffle (R2.6): shuffle on, and the album from a song chosen at random."""
        self.queue.set_shuffle(True)
        self.play_songs(*self._album(album_id), start=None)

    def _album(self, album_id: int) -> tuple[list[int], str]:
        if self._read is None:
            return [], ""
        c = self._read()
        ids = [
            r[0]
            for r in c.execute(
                f"SELECT id FROM song WHERE album_id = ? ORDER BY {albums.ALBUM_ORDER}",
                (album_id,),
            )
        ]
        r = c.execute("SELECT title FROM album WHERE id = ?", (album_id,)).fetchone()
        return ids, r[0] if r else ""

    def cue(self, songs: Sequence[int], source: str, at: int = 0) -> None:
        """The queue becomes `songs` from `source`, cued at its song `at` (those before it played)
        and paused there, nothing playing: as R1.8 restores it, and as the tour shows it."""
        self.queue.play(songs, 0, source)
        if 0 < at < len(self.queue):
            self.queue.jump(self.queue.upcoming[at - 1].key)
        self._cue()

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"queue": "Glass Harbor"} cues that album at its first song,
        paused, nothing playing; with "at": 3, at its fourth, the three before it played; "added":
        the titles of songs then added with Add to queue; "upNext": True opens Up next, which is
        closed otherwise."""
        if "queue" in step and self._read is not None:
            c = self._read()
            r = c.execute("SELECT id FROM album WHERE title = ?", (step["queue"],)).fetchone()
            songs, source = self._album(r[0] if r else -1)
            self.cue(songs, source, int(step.get("at", 0)))
            for title in step.get("added", []):
                found = c.execute("SELECT id FROM song WHERE title = ?", (title,)).fetchone()
                if found is not None:
                    self.queue.add([found[0]])
            self._queue_changed()
        self.set_up_next(bool(step.get("upNext")))

    # ---------- what QML asks: changing the queue (R7.2) ----------

    @Slot(QObject, int)
    def playNext(self, songs: Queueable, row: int) -> None:  # noqa: N802
        """A song list's Play next: the row's songs right after the current one."""
        self._added(self.queue.play_next(songs.songs_at(row)))

    @Slot(QObject, int)
    def addToQueue(self, songs: Queueable, row: int) -> None:  # noqa: N802
        """A song list's Add to queue: the row's songs after those added before."""
        self._added(self.queue.add(songs.songs_at(row)))

    def _added(self, entries: list[Entry]) -> None:
        """Songs went into the queue: shown at once when nothing was there (cued, not started)."""
        if entries and self.queue.current is entries[0]:
            self._cue()
        else:
            self._queue_changed()

    @Slot(int)
    def playRow(self, row: int) -> None:  # noqa: N802
        """A double click on a row of Up next: that song plays."""
        found = self._up_next.entry(row)
        if found is not None:
            entry = self.queue.jump(found[0].key)
            if entry is not None:
                self._start(entry)

    @Slot(int)
    def removeRow(self, row: int) -> None:  # noqa: N802
        """Up next's ×: the song out of the queue; the song playing stays."""
        found = self._up_next.entry(row)
        if found is not None and self.queue.remove(found[0].key):
            self._queue_changed()

    @Slot(int, int)
    def moveRow(self, row: int, to: int) -> None:  # noqa: N802
        """Up next's drag: a song to come dropped above row `to` (the line drawn there), where it
        then plays; below the songs to come, it goes last among them."""
        found = self._up_next.entry(row)
        if found is None or found[1] != "next":
            return
        first = 1 if self.queue.current is not None else 0  # the songs to come follow it
        place = to - first - (1 if to > row else 0)  # its own row leaves the list first
        if self.queue.move(found[0].key, place):
            self._queue_changed()

    @Slot()
    def toggleUpNext(self) -> None:  # noqa: N802
        """The bar's queue button: Up next opens, or closes again."""
        self.set_up_next(not self._up_next_open)

    @Slot()
    def closeUpNext(self) -> None:  # noqa: N802
        self.set_up_next(False)

    def set_up_next(self, open_: bool) -> None:
        if open_ != self._up_next_open:
            self._up_next_open = open_
            self.queueChanged.emit()

    # ---------- what QML asks: the bar's buttons (R6.5, R7.3) ----------

    @Slot()
    def toggle(self) -> None:
        """Play/pause and the space bar (R6.9): a song playing pauses, a paused one resumes, a
        cued one starts."""
        if self._on and not self._paused:
            self._pause.emit()
        elif self._on:
            self._resume.emit()
        elif self.queue.current is not None:
            self._start(self.queue.current)

    @Slot()
    def next(self) -> None:
        """Next: the song after this one plays, or a paused or cued one is cued there; past the
        end with repeat Off, the queue has played out and nothing plays."""
        if self.queue.current is None:
            return
        playing = self._on and not self._paused
        entry = self.queue.next()
        self._go(entry, playing)

    @Slot()
    def previous(self) -> None:
        """Previous: a song past its first few seconds starts again; else the song before it."""
        playing = self._on and not self._paused
        if self.queue.current is not None and self._on and self._position > RESTART_AFTER:
            entry: Entry | None = self.queue.current
        else:
            entry = self.queue.previous()
        self._go(entry, playing)

    def _go(self, entry: Entry | None, playing: bool) -> None:
        if entry is None:
            self._stop_engine()
            self._finish("stopped")
        elif playing:
            self._start(entry)
        else:
            self._cue()

    @Slot()
    def toggleShuffle(self) -> None:  # noqa: N802
        self.queue.set_shuffle(not self.queue.shuffle)
        self._queue_changed()

    @Slot()
    def cycleRepeat(self) -> None:  # noqa: N802
        self.queue.cycle_repeat()
        self._queue_changed()

    @Slot(float)
    def setVolume(self, level: float) -> None:  # noqa: N802
        """The bar's volume (R6.5), from 0 to 1."""
        level = min(1.0, max(0.0, level))
        if level != self._volume:
            self._volume = level
            self._set_gain.emit(gain_of(level))
            self.volumeChanged.emit()

    @Slot(float)
    def seek(self, seconds: float) -> None:
        """Seeks the song playing, or paused, to `seconds` from its start (R7.4, A4.6); past its
        length, to its end. The bar shows the place at once; a cued song doesn't move."""
        if not self._on or not self._requested:
            return
        seconds = max(0.0, seconds)
        if self._length:
            seconds = min(seconds, self._length)
        self._position = seconds
        self._seeking += 1
        self._seek.emit(self._requested, seconds)
        self.positionChanged.emit()

    @Slot(float)
    def seekTo(self, fraction: float) -> None:  # noqa: N802
        """The seek bar dragged or clicked: to that fraction of the song's length (R7.4)."""
        if self._length:
            self.seek(min(1.0, max(0.0, fraction)) * self._length)

    @Slot()
    def seekBack(self) -> None:  # noqa: N802
        """←: five seconds back (R7.4, R6.9)."""
        self.seek(self._position - SEEK_STEP)

    @Slot()
    def seekAhead(self) -> None:  # noqa: N802
        """→: five seconds on (R7.4, R6.9)."""
        self.seek(self._position + SEEK_STEP)

    @Slot()
    def pause(self) -> None:
        self._pause.emit()

    @Slot()
    def resume(self) -> None:
        self._resume.emit()

    @Slot()
    def stop(self) -> None:
        self._stop.emit()

    def play_file(self, path: str) -> None:
        """Plays the file at `path`, a whole path, from its start, outside the queue (--play)."""
        self._info = None
        self._start_engine(path)

    def close(self) -> None:
        """Stops the song and ends the playback thread: for closing."""
        self._thread.close()

    # ---------- playing the queue's songs ----------

    def _start(self, entry: Entry) -> None:
        """The queue's current song plays from its start; one gone from the index, or whose root
        isn't there, is cued instead, `error` saying why."""
        info = self._song(entry.song)
        if info is None:
            self._stop_engine()
            self._show(None, "")
            self._error = "That song is no longer in the library"
            log.warning("couldn't play song %d: it is no longer in the index", entry.song)
            self._queue_changed()
            return
        why = self._refuse(info.path) if self._refuse is not None else ""
        if why:
            self._stop_engine()
            self._show(info, info.path)
            self._error = why
            self._queue_changed()
            return
        self._error = ""
        self._show(info, info.path)
        self._start_engine(self._whole(info.path), entry.key)
        self._queue_changed()

    def _cue(self) -> None:
        """The queue's current song shown, paused at its start, nothing playing."""
        self._stop_engine()
        entry = self.queue.current
        info = self._song(entry.song) if entry is not None else None
        self._error = ""
        self._show(info, info.path if info is not None else "")
        self._queue_changed()

    def _song(self, song: int) -> SongInfo | None:
        if self._read is None:
            return None
        return read_songs(self._read(), [song]).get(song)

    def _show(self, info: SongInfo | None, path: str) -> None:
        """The song the bar shows, before the engine has it: its words, its length as the index
        has it, at its start."""
        self._info = info
        self._length = (info.length or 0.0) if info is not None else 0.0
        self._position = 0.0
        self._set_path(path)
        self.changed.emit()
        self.positionChanged.emit()

    def _set_path(self, path: str) -> None:
        if path != self._path:
            self._path = path
            self.nowPlaying.emit(path)

    def _start_engine(self, path: str, key: int | None = None) -> None:
        """The engine plays `path`, the queue's entry `key` (None: outside the queue), under a new
        ticket; what follows it is told after."""
        if not self._started:
            self._thread.start()
            self._started = True
        self._requested = next(self._tickets)
        self._playing(key)
        self._play.emit(path, self._requested)

    def _playing(self, key: int | None) -> None:
        self._playing_key = key
        self._followed, self._follows = None, set()

    def _stop_engine(self) -> None:
        """Stops what the engine plays, if anything; what it says of it is then nothing to act
        on (`_requested` no longer names it)."""
        self._requested = 0
        self._playing(None)
        if self._on or self._started:
            self._stop.emit()
        self._on = self._paused = False

    def _finish(self, how: str, error: str = "") -> None:
        """Nothing plays now: the queue's current song stays cued, if it has one (after a song
        that failed, or Stop), else the bar is empty (the queue played out)."""
        self.last, self._error = how, error
        self._on = self._paused = False
        self._position = 0.0
        if self.queue.current is None or self._info is None:
            self._info = None
            self._length = 0.0
            self._path = ""
            self.nowPlaying.emit("")  # even when nothing was shown: it says playing has stopped
        self.changed.emit()
        self.positionChanged.emit()
        self._queue_changed()

    def _queue_changed(self) -> None:
        self._up_next.refresh()
        self.queueChanged.emit()
        self._tell_following()

    def _tell_following(self) -> None:
        """Tells the engine what follows the song playing, when that changed (A4.2): the queue's
        next song, which it opens ahead and joins with no gap; nothing for a song outside the
        queue, or when the next one is gone from the index or its root isn't there (its turn
        then says why)."""
        if not self._requested or self._playing_key is None:
            return
        current = self.queue.current
        entry = None
        if current is not None and current.key == self._playing_key:
            entry = self.queue.following()
        key = entry.key if entry is not None else None
        if self._followed is not None and self._followed[1] == key:
            return
        path = ""
        info = self._song(entry.song) if entry is not None else None
        if info is not None and not (self._refuse is not None and self._refuse(info.path)):
            path = self._whole(info.path)
        ticket = next(self._tickets) if path else 0
        if ticket:
            self._follows.add(ticket)
        self._followed = (ticket, key)
        self._follow.emit(self._requested, ticket, path)

    # ---------- what the engine says ----------

    @Slot(int, str, float)
    def _on_began(self, ticket: int, path: str, length: float) -> None:
        if ticket != self._requested:
            return  # one asked for before the last request: another follows
        self._on, self._paused = True, False
        if self._info is None:
            self._set_path(self._under_root(path))
        self._length, self._position = max(0.0, length), 0.0
        self.changed.emit()
        self.positionChanged.emit()

    @Slot(int, str, float)
    def _on_joined(self, ticket: int, path: str, length: float) -> None:
        """The device reached the first sample of the song told to follow (A4.2): the queue
        moves on to it, and the bar, the playing row and Up next with it. One the queue no longer
        has next (it changed once the device had the song) gives way to what the queue says."""
        if ticket not in self._follows:
            return  # told to follow a song no longer playing
        told = self._followed
        self._requested = ticket
        entry = self.queue.ended()
        if entry is None or told is None or told[0] != ticket or entry.key != told[1]:
            if entry is None:
                self._stop_engine()
                self._finish("ended")
            else:
                self._start(entry)
            return
        info = self._song(entry.song)
        if info is None:
            self._start(entry)  # gone from the index since: it says so
            return
        self._playing(entry.key)
        self._error = ""
        self._show(info, info.path)
        self._on, self._paused = True, False
        self._length = max(0.0, length)
        self.changed.emit()
        self._queue_changed()

    @Slot(float)
    def _on_moved(self, seconds: float) -> None:
        if self._on and not self._seeking:
            self._position = seconds
            self.positionChanged.emit()

    @Slot(int)
    def _on_sought(self, ticket: int) -> None:
        self._seeking = max(0, self._seeking - 1)

    @Slot(bool)
    def _on_paused(self, paused: bool) -> None:
        if self._on:
            self._paused = paused
            self.changed.emit()

    @Slot(int)
    def _on_ended(self, ticket: int) -> None:
        if ticket != self._requested:
            return  # a song stopped for another
        self._requested = 0
        self._playing(None)
        self._on = False
        entry = self.queue.ended() if self._info is not None else None
        if entry is not None:
            self._start(entry)
        else:
            self._finish("ended")

    @Slot(int)
    def _on_stopped(self, ticket: int) -> None:
        if ticket == self._requested:  # Stop, asked for
            self._requested = 0
            self._playing(None)
            self._finish("stopped")

    @Slot(int, str)
    def _on_failed(self, ticket: int, why: str) -> None:
        if ticket in self._follows:  # the next song, failing as the device reached it
            entry = self.queue.ended()
            info = self._song(entry.song) if entry is not None else None
            self._show(info, info.path if info is not None else "")
        elif ticket != self._requested:
            return
        self._requested = 0
        self._playing(None)
        self._finish("failed", why)

    # ---------- what QML reads ----------

    def _get_path(self) -> str:
        return self._path

    def _get_playing(self) -> bool:
        return self._on and not self._paused

    def _get_paused(self) -> bool:
        return self._paused

    def _get_position(self) -> float:
        return self._position

    def _get_length(self) -> float:
        return self._length

    def _get_error(self) -> str:
        return self._error

    def _get_title(self) -> str:
        if self._info is not None:
            return self._info.title
        return title_of(None, self._path) if self._path else ""

    def _get_line(self) -> str:
        if self._error:
            return self._error
        return bar_line(self._info) if self._info is not None else ""

    def _get_failed(self) -> bool:
        return bool(self._error)

    def _get_time_name(self) -> str:
        if not self._path:
            return ""
        played = time_text(self._position)
        return f"{played} of {self._get_length_text()}" if self._length else played

    def _get_cover(self) -> str:
        return self._info.cover if self._info is not None else ""

    def _get_rating(self) -> int:
        return self._info.rating if self._info is not None else 0

    def _get_position_text(self) -> str:
        return time_text(self._position) if self._path else ""

    def _get_length_text(self) -> str:
        return time_text(self._length) if self._path and self._length else ""

    def _get_seekable(self) -> bool:
        return self._on and self._length > 0

    def _get_progress(self) -> float:
        return min(1.0, self._position / self._length) if self._length else 0.0

    def _get_shuffle(self) -> bool:
        return self.queue.shuffle

    def _get_repeat(self) -> str:
        return self.queue.repeat

    def _get_repeat_name(self) -> str:
        return REPEAT_NAMES[self.queue.repeat]

    def _get_shuffle_name(self) -> str:
        return "Shuffle on" if self.queue.shuffle else "Shuffle off"

    def _get_volume(self) -> float:
        return self._volume

    def _get_up_next(self) -> UpNextModel:
        return self._up_next

    def _get_up_next_open(self) -> bool:
        return self._up_next_open

    path = QtProperty(str, _get_path, notify=changed)  # the song's path under the root; "": none
    playing = QtProperty(bool, _get_playing, notify=changed)  # a song plays, not paused
    paused = QtProperty(bool, _get_paused, notify=changed)
    position = QtProperty(float, _get_position, notify=positionChanged)  # seconds
    length = QtProperty(float, _get_length, notify=changed)  # seconds; 0 when unknown
    error = QtProperty(str, _get_error, notify=changed)  # why the last song couldn't play
    title = QtProperty(str, _get_title, notify=changed)
    line = QtProperty(str, _get_line, notify=changed)  # Lumen Drift — Glass Harbor; or the error
    failed = QtProperty(bool, _get_failed, notify=changed)  # the line is why it couldn't play
    timeName = QtProperty(str, _get_time_name, notify=positionChanged)  # 1:38 of 4:18
    cover = QtProperty(str, _get_cover, notify=changed)
    rating = QtProperty(int, _get_rating, notify=changed)
    positionText = QtProperty(str, _get_position_text, notify=positionChanged)  # 1:38
    lengthText = QtProperty(str, _get_length_text, notify=changed)  # 4:18; "" when unknown
    progress = QtProperty(float, _get_progress, notify=positionChanged)  # 0 to 1
    seekable = QtProperty(bool, _get_seekable, notify=changed)  # a song plays or is paused
    shuffle = QtProperty(bool, _get_shuffle, notify=queueChanged)
    repeat = QtProperty(str, _get_repeat, notify=queueChanged)  # off, all, one
    repeatName = QtProperty(str, _get_repeat_name, notify=queueChanged)  # Repeat all
    shuffleName = QtProperty(str, _get_shuffle_name, notify=queueChanged)  # Shuffle on
    volume = QtProperty(float, _get_volume, notify=volumeChanged)  # 0 to 1
    upNext = QtProperty(QObject, _get_up_next, constant=True)
    upNextOpen = QtProperty(bool, _get_up_next_open, notify=queueChanged)
