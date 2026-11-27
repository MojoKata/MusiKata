"""Drag and drop in the running app (R6.10, R8.5, R7.2, P01-playlist-drag).

- **What a drag carries** (`Carried`): the songs a row, a tile or a selection stands for, in their
  order, from every list and grid: songs, an album, an artist, a genre, folders and files (R2.9.6)
  and a playlist's entries; the card the drag shows ("3 songs", the names after it, the first
  one's cover: `DragCard.qml`, grabbed as the drag's picture); and the files themselves, for a
  file manager or another app (R6.10: copied there, never moved, so nothing leaves the root).
  Within MusiKata it is read back from its own format (`MIME`, `encode`, `decode`), the root's
  path in it, so one another MusiKata of another root drags reads as its files.
- **Where it lands** (`drop_of`): onto a playlist in the sidebar, its songs added at the end (R8.5,
  through `Playlists.add_songs`, whose message offers Undo); within a playlist's page, its own
  entries moved to the insertion line (R8.5, `Playlists.move_entries`); onto Up next or the queue
  button, played next (R7.2); files from a file manager onto a playlist, added when under the
  root (`Playlists.add_files`), and onto the window, which R12.5 (a later version) will add to
  the library. A smart playlist refuses what is dropped on it, its rule choosing its songs, and
  its own page moves none of its entries (R8.9). Each target, while a drag is over it, is
  highlighted and named (`target_text`: "Add to Evening Focus", or why a smart playlist refuses),
  and a reorder draws its insertion line (`line`).
- **The bridge** (`Dragging`): what QML calls as a drag starts (`carry…`, `start`) and as one
  moves over a target, leaves it or is dropped (`enter`, `over`, `leave`, `drop`), and what it
  binds to (`card`, `target`, `targetText`, `line`, `busy`). The platform's drag (QDrag) runs here,
  with the card as its picture; the tour holds one still instead (`go`).

What a drag carries and what a drop does are decided here as plain data, tested without a
window; the QML only binds (DragSource.qml, the views' DropAreas)."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QMimeData, QObject, QPoint, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDrag, QGuiApplication, QImage, QPixmap
from PySide6.QtQuick import QQuickItem

from musikata_core import playlists as core

from .edittags import target_at
from .folders import FolderModel
from .models import SongsModel, plural, song_order
from .nowplaying import read_songs
from .playlists import OUTSIDE_LATER, EntriesModel, is_smart, smart_text

if TYPE_CHECKING:
    from .bridges import Library, Player
    from .playlists import Playlists

log = logging.getLogger(__name__)

MIME = "application/x-musikata-songs"  # a drag's songs within MusiKata (Cover.qml refuses it)
NAMES = 6  # the names the card lists at most; its line elides what doesn't fit
HOT_SPOT = QPoint(28, 22)  # where the pointer holds the card: on its cover, as P01 draws it
COVER_LOOK, COVER_WAITS = 10, 20  # ms between looks at whether the card's cover has come, and how
# many: a drag starts with no cover rather than wait longer
IN_LIBRARY = "Those files are in your library already"
# the targets: a playlist in the sidebar, the open playlist's page, Up next or the queue button,
# and the window anywhere else
PLAYLIST, PAGE, QUEUE, WINDOW = "playlist", "page", "queue", "window"
# what a drop does; REFUSE: onto a smart playlist, whose rule chooses its songs (R8.9)
ADD, MOVE, PLAY_NEXT, FILES, NONE = "add", "move", "play-next", "files", "none"
REFUSE = "refuse"


# ---------- what a drag carries ----------


@dataclass(frozen=True)
class Carried:
    """What a drag carries (R6.10): its songs by id in their order; the files a file manager is
    given (whole paths); the card's head ("3 songs") and names; its cover; and, from a playlist's
    page, the playlist and its entries (ids), which a drop within it moves (R8.5)."""

    songs: tuple[int, ...]
    files: tuple[str, ...] = ()
    head: str = ""
    names: str = ""
    cover: str = ""
    playlist: int = -1
    entries: tuple[int, ...] = ()


def head_text(songs: int) -> str:
    """The card's head (P01): "3 songs"."""
    return plural(songs, "song")


def names_text(names: Sequence[str]) -> str:
    """The card's line (P01): the first names, as many as NAMES, the line eliding the rest:
    "Breakwater, Low Orbit, Afterlight"."""
    shown = [n for n in names[:NAMES] if n]
    more = ", …" if len(names) > NAMES else ""
    return ", ".join(shown) + more


def encode(carried: Carried, root: str) -> str:
    """A drag's songs in MusiKata's own format (MIME), with the root they are of."""
    return json.dumps(
        {
            "root": root,
            "songs": list(carried.songs),
            "playlist": carried.playlist,
            "entries": list(carried.entries),
        }  # fmt: skip
    )


def _ids(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, list) or not all(
        isinstance(v, int) and not isinstance(v, bool) for v in value
    ):
        return None
    return tuple(value)


def decode(text: str, root: str) -> Carried | None:
    """A drag's songs read back (`encode`): None when it isn't MusiKata's own, is broken, or is
    another root's (another MusiKata's), whose ids mean nothing here: its files are read instead."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("root") != root:
        return None
    songs, entries = _ids(data.get("songs")), _ids(data.get("entries", []))
    playlist = data.get("playlist", -1)
    if songs is None or entries is None or not isinstance(playlist, int):
        return None
    return Carried(songs, playlist=playlist, entries=entries)


def mime_of(carried: Carried, root: str) -> QMimeData:
    """The drag's data: MusiKata's own (MIME), and the files as URLs, which a file manager copies
    and another app opens (R6.10)."""
    data = QMimeData()
    data.setData(MIME, encode(carried, root).encode())
    data.setUrls([QUrl.fromLocalFile(f) for f in carried.files])
    return data


def local_paths(urls: Sequence[Any]) -> list[str]:
    """The files a drop names (QUrls or text): those on this computer, by their whole paths."""
    out = []
    for u in urls:
        url = u if isinstance(u, QUrl) else QUrl(str(u))
        if url.isLocalFile():
            out.append(url.toLocalFile())
    return out


# ---------- where it lands ----------


@dataclass(frozen=True)
class Drop:
    """What a drop does: ADD the songs to a playlist, MOVE a playlist's entries within it,
    PLAY_NEXT the songs, take FILES from outside, REFUSE them (a smart playlist), or NONE (not
    taken)."""

    what: str
    songs: tuple[int, ...] = ()
    entries: tuple[int, ...] = ()
    paths: tuple[str, ...] = ()


def drop_of(
    kind: str, key: int, carried: Carried | None, paths: Sequence[str], smart: bool = False
) -> Drop:
    """What a drop on the target `kind` (`key`: its playlist, `smart` when it is a smart one)
    does, of what MusiKata dragged (`carried`) or of the files another app did (`paths`):
    MusiKata's songs onto a playlist are added (R8.5), a playlist's own entries within its page
    moved (R8.5), songs onto the queue played next (R7.2); files from outside onto any target are
    taken as files (R8.5, R12.5). Songs or files onto a smart playlist are refused, saying why
    (R8.9), and its own entries within its page aren't moved. MusiKata's songs dropped elsewhere
    on the window do nothing."""
    if smart and kind in (PLAYLIST, PAGE):
        if carried is not None and carried.playlist == key and kind == PAGE:
            return Drop(NONE)
        return Drop(REFUSE) if (carried is not None and carried.songs) or paths else Drop(NONE)
    if carried is not None:
        if kind == PAGE and carried.playlist == key and carried.entries:
            return Drop(MOVE, carried.songs, carried.entries)
        if kind in (PLAYLIST, PAGE) and carried.songs:
            return Drop(ADD, carried.songs)
        if kind == QUEUE and carried.songs:
            return Drop(PLAY_NEXT, carried.songs)
        return Drop(NONE)
    if paths and kind in (PLAYLIST, PAGE, QUEUE, WINDOW):
        return Drop(FILES, paths=tuple(paths))
    return Drop(NONE)


def target_text(what: str, kind: str, name: str) -> str:
    """What a target says while a drag is over it (P01): "Add to Evening Focus" for songs or files
    onto a playlist, "Play next" onto the queue; nothing for a reorder, whose line says it, or the
    window."""
    if kind in (PLAYLIST, PAGE) and what in (ADD, FILES):
        return f"Add to {name}"
    if kind in (PLAYLIST, PAGE) and what == REFUSE:
        return smart_text(name)
    if kind == QUEUE and what in (PLAY_NEXT, FILES):
        return "Play next"
    return ""


def window_text(outside: int) -> str:
    """Files dropped onto the window: those from outside the music folder wait for R12.5 (a later
    version); those under it are in the library already."""
    return OUTSIDE_LATER if outside else IN_LIBRARY


# ---------- the songs of an album, an artist, a genre ----------


def album_songs(c: sqlite3.Connection, album: int) -> tuple[list[int], str]:
    """An album's songs by disc and track (as Play plays them), and its title and artist."""
    ids = [int(i) for (i,) in c.execute(
        f"SELECT id FROM song WHERE album_id = ? ORDER BY {song_order('tracks')}", (album,)
    )]  # fmt: skip
    r = c.execute("SELECT title, artist FROM album WHERE id = ?", (album,)).fetchone()
    name = (f"{r[0]} · {r[1]}" if r[1] else str(r[0])) if r else ""
    return ids, name


def artist_songs(c: sqlite3.Connection, artist: int) -> tuple[list[int], str]:
    """An artist's songs, on their albums and others', by album, disc and track; and the name."""
    ids = [int(i) for (i,) in c.execute(
        "SELECT id FROM song WHERE artist_id = ? OR album_id IN (SELECT id FROM album WHERE"
        f" artist_id = ?) ORDER BY {song_order('artist')}", (artist, artist)
    )]  # fmt: skip
    r = c.execute("SELECT name FROM artist WHERE id = ?", (artist,)).fetchone()
    return ids, str(r[0]) if r else ""


def genre_songs(c: sqlite3.Connection, genre: str) -> tuple[list[int], str]:
    """A genre's songs in its page's order (as Play all plays them), and its name."""
    ids = [int(i) for (i,) in c.execute(
        "SELECT id FROM song WHERE id IN (SELECT song_id FROM song_genre WHERE genre = ?)"
        f" ORDER BY {song_order('artist')}", (genre,)
    )]  # fmt: skip
    return ids, genre


# ---------- the bridge ----------


def _exec(drag: QDrag) -> object:
    """The platform's drag, until it is dropped: copied, never moved (R6.10), so a file manager
    leaves the files where they are."""
    return drag.exec(Qt.DropAction.CopyAction)


class Dragging(QObject):
    """Drag and drop (R6.10, R8.5) as QML sees it. `root` and `read` are the library's; songs and
    files dropped on a playlist go to `playlists`, onto the queue to `player`; `say` shows a
    message (R6.7); `run` runs the platform's drag (QDrag.exec; a test's records it)."""

    changed = Signal()

    def __init__(
        self,
        root: str,
        read: Callable[[], sqlite3.Connection],
        library: Library | None = None,
        playlists: Playlists | None = None,
        player: Player | None = None,
        say: Callable[[str], object] | None = None,
        run: Callable[[QDrag], object] = _exec,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._read, self._run = root, read, run
        self._library, self._playlists, self._player, self._say_to = library, playlists, player, say
        self._carried: Carried | None = None
        self._card: QQuickItem | None = None  # DragCard.qml, grabbed as the drag's picture
        # the card's picture being made (QQuickItemGrabResult, behind a shared pointer)
        self._grab: Any = None
        self._busy = False  # the platform's drag runs: the pointer is its
        self._held = False  # the tour holds a drag still
        self._target = ""  # "<kind>:<key>" of the target under the drag
        self._what = NONE
        self._text = ""
        self._line = -1  # the row of the page the insertion line is above

    def _say(self, text: str) -> None:
        if self._say_to is not None and text:
            self._say_to(text)

    # ---------- what a drag carries ----------

    def _carry(
        self,
        songs: Sequence[int],
        names: Sequence[str] | None = None,
        files: Sequence[str] | None = None,
        playlist: int = -1,
        entries: Sequence[int] = (),
    ) -> None:
        """The drag carries `songs`; the card names `names` (else the songs' titles); a file
        manager gets `files` (whole paths; else the songs' files)."""
        found = read_songs(self._read(), songs)
        there = [found[s] for s in songs if s in found]
        shown = names if names is not None else [s.title for s in there[: NAMES + 1]]
        if files is None:
            files = [core.full_path(self._root, s.path) for s in there]
        cover = next((s.cover for s in there if s.cover), "")
        self._carried = Carried(tuple(songs), tuple(files), head_text(len(songs)),
                                names_text(shown), cover, playlist, tuple(entries))  # fmt: skip
        self.changed.emit()

    @Slot(QObject, int)
    def carry(self, model: QObject, row: int) -> None:
        """A row of a list dragged: the selection when the row is in it, else the row's own (a
        song, a folder's songs beneath it, a playlist's entry), as its right-click menu takes it
        (R2.9.6, R7.2)."""
        if isinstance(model, EntriesModel):
            entries = model.entries_at(row)
            self._carry(model.songs_at(row), playlist=model.playlist(), entries=entries)
        elif isinstance(model, FolderModel):
            songs, _what = target_at(model, row)
            r = model.row(row)
            if model.is_selected(row):
                folders, files = model.selected()
                paths = folders + files
            else:
                paths = [str(r["path"])] if r is not None else []
            names = [p.rpartition("/")[2] for p in paths]
            whole = [core.full_path(self._root, p) for p in paths]
            self._carry(songs, names, whole)
        elif isinstance(model, SongsModel):
            self._carry(model.songs_at(row))

    @Slot(int)
    def carryAlbum(self, album: int) -> None:  # noqa: N802
        """An album dragged from the Albums grid or list, or an artist's or a genre's page."""
        songs, name = album_songs(self._read(), album)
        self._carry(songs, [name])

    @Slot(int)
    def carryArtist(self, artist: int) -> None:  # noqa: N802
        songs, name = artist_songs(self._read(), artist)
        self._carry(songs, [name])

    @Slot(str)
    def carryGenre(self, genre: str) -> None:  # noqa: N802
        songs, name = genre_songs(self._read(), genre)
        self._carry(songs, [name])

    # ---------- the platform's drag ----------

    @Slot(QQuickItem)
    def setCard(self, card: QQuickItem) -> None:  # noqa: N802
        """The card (DragCard.qml) whose picture the drag shows."""
        self._card = card

    @Slot(QQuickItem)
    def start(self, source: QQuickItem) -> None:
        """The drag starts from `source` (a row or a tile), carrying what `carry` said: once the
        card's picture is made, the platform's drag runs until it is dropped, here or in another
        app."""
        if self._carried is None or self._busy:
            return
        self._when_drawn(lambda: self._grab_card(source), COVER_WAITS)

    def _when_drawn(self, then: Callable[[], None], waits: int) -> None:
        """`then` once the card has its cover (a thumbnail loads off the GUI thread), or after
        `waits` looks, without it."""
        card = self._card
        if waits > 0 and card is not None and card.property("loading") is True:
            QTimer.singleShot(COVER_LOOK, lambda: self._when_drawn(then, waits - 1))
            return
        then()

    def _grab_card(self, source: QQuickItem) -> None:
        card = self._card
        grab: Any = None
        if card is not None and card.width() > 0 and card.height() > 0:
            ratio = card.window().devicePixelRatio() if card.window() is not None else 1.0
            size = QSize(round(card.width() * ratio), round(card.height() * ratio))
            grab = card.grabToImage(size)
        if grab is None:
            self._drag(source, QImage())
            return
        self._grab = grab
        grab.ready.connect(lambda: self._grabbed(source, grab))

    def _grabbed(self, source: QQuickItem, grab: Any) -> None:
        self._grab = None
        if QGuiApplication.mouseButtons() == Qt.MouseButton.NoButton:
            self._carried = None  # let go before the picture was made: no drag
            self.changed.emit()
            return
        image = grab.image()
        if self._card is not None and self._card.window() is not None:
            image.setDevicePixelRatio(self._card.window().devicePixelRatio())
        self._drag(source, image)

    def _drag(self, source: QQuickItem, image: QImage) -> None:
        carried = self._carried
        if carried is None:
            return
        drag = QDrag(source)
        drag.setMimeData(mime_of(carried, self._root))
        if not image.isNull():
            drag.setPixmap(QPixmap.fromImage(image))
            drag.setHotSpot(HOT_SPOT)
        self._busy = True
        self.changed.emit()
        try:
            self._run(drag)
        finally:
            self._busy = False
            self._carried = None
            self._clear()

    # ---------- the targets ----------

    def _name(self, playlist: int) -> str:
        r = self._read().execute("SELECT name FROM playlist WHERE id = ?", (playlist,)).fetchone()
        return str(r[0]) if r else ""

    def _smart(self, kind: str, playlist: int) -> bool:
        if kind not in (PLAYLIST, PAGE):
            return False
        r = self._read().execute("SELECT rule FROM playlist WHERE id = ?", (playlist,)).fetchone()
        return r is not None and is_smart(r[0])

    def _drop_of(self, kind: str, key: int, text: str, urls: Sequence[Any]) -> Drop:
        carried = decode(text, self._root) if text else None
        paths = local_paths(urls) if carried is None else []
        return drop_of(kind, key, carried, paths, self._smart(kind, key))

    @Slot(str, int, str, list, result=bool)
    def enter(self, kind: str, key: int, text: str, urls: list[Any]) -> bool:
        """A drag came over the target `kind` (`key`: its playlist), carrying MusiKata's songs
        (`text`, in MIME) or files (`urls`): whether it takes them; if so it is highlighted and
        named (P01)."""
        d = self._drop_of(kind, key, text, urls)
        if d.what == NONE:
            return False
        name = self._name(key) if kind in (PLAYLIST, PAGE) else ""
        self._target, self._what = f"{kind}:{key}", d.what
        self._text, self._line = target_text(d.what, kind, name), -1
        self.changed.emit()
        return True

    @Slot(int)
    def over(self, row: int) -> None:
        """The drag over a playlist's page, above row `row` (the row count: below the last): where
        a reorder's insertion line is (R8.5)."""
        line = row if self._what == MOVE else -1
        if line != self._line:
            self._line = line
            self.changed.emit()

    @Slot(str, int)
    def leave(self, kind: str, key: int) -> None:
        """The drag left the target: no longer highlighted."""
        if self._target == f"{kind}:{key}" and not self._held:
            self._clear()

    def _clear(self) -> None:
        self._target, self._what, self._text, self._line = "", NONE, "", -1
        self._held = False
        self.changed.emit()

    @Slot(str, int, str, list, result=bool)
    def drop(self, kind: str, key: int, text: str, urls: list[Any]) -> bool:
        """Dropped on the target `kind`: what `drop_of` says done. Whether it was taken."""
        d = self._drop_of(kind, key, text, urls)
        line = self._line
        self._clear()
        if d.what == REFUSE:
            self._say(smart_text(self._name(key)))
            return False
        if d.what == ADD and self._playlists is not None:
            self._playlists.add_songs(key, d.songs)
        elif d.what == MOVE and self._playlists is not None:
            self._move(d.entries, line)
        elif d.what == PLAY_NEXT and self._player is not None:
            self._player.play_next(d.songs)
        elif d.what == FILES:
            self._files(kind, key, d.paths)
        else:
            return False
        return True

    def _page(self) -> EntriesModel | None:
        if self._library is None:
            return None
        model = self._library.property("playlistPage").property("songs")
        return model if isinstance(model, EntriesModel) else None

    def _move(self, entries: Sequence[int], line: int) -> None:
        model = self._page()
        if model is None or line < 0 or self._playlists is None:
            return
        self._playlists.move_entries(model, entries, model.position_at(line))

    def _files(self, kind: str, key: int, paths: Sequence[str]) -> None:
        if kind in (PLAYLIST, PAGE) and self._playlists is not None:
            self._playlists.add_files(key, paths)
            return
        inside, outside = core.dropped(paths, self._root)
        if kind == QUEUE and self._player is not None and inside:
            songs = core.songs_dropped(self._read(), inside)
            if songs:
                self._player.play_next(songs)
            if outside or not songs:
                self._say(OUTSIDE_LATER if outside else "Nothing dropped is a song in your library")
            return
        self._say(window_text(len(outside)))

    # ---------- the tour ----------

    def go(self, step: Mapping[str, Any]) -> None:
        """A tour's step (A1.6): {"drag": {"rows": [1, 2, 3], "onto": "Evening Focus", "line":
        5}} holds a drag still over the playlist page shown, as P01 draws it: those rows
        selected and carried, the playlist `onto` highlighted and named, the card under it, and
        the insertion line above row `line`. Any other step lets it go."""
        drag = step.get("drag")
        if not drag:
            if self._held:
                self._carried = None
                self._clear()
            return
        model = self._page()
        r = (
            self._read()
            .execute("SELECT id FROM playlist WHERE name = ?", (str(drag.get("onto", "")),))
            .fetchone()
        )
        if model is None or r is None:
            return
        rows = [int(n) for n in drag.get("rows", [])]
        model.select_rows(rows)
        if rows:
            self.carry(model, rows[0])
        self._held = True
        self._target, self._what = f"{PLAYLIST}:{int(r[0])}", ADD
        self._text = target_text(ADD, PLAYLIST, self._name(int(r[0])))
        self._line = int(drag.get("line", -1))
        self.changed.emit()

    def close(self) -> None:
        """For closing the window: what it refers to let go (A1.3)."""
        self._library = self._playlists = self._player = None
        self._say_to = None
        self._card = None
        self._grab = None

    # ---------- what QML reads ----------

    def _get_card(self) -> dict[str, str]:
        c = self._carried
        return {"head": c.head, "names": c.names, "cover": c.cover} if c else {}

    mime = QtProperty(str, lambda self: MIME, constant=True)
    busy = QtProperty(bool, lambda self: self._busy, notify=changed)
    held = QtProperty(bool, lambda self: self._held, notify=changed)
    card = QtProperty(dict, _get_card, notify=changed)  # head, names, cover; {} when none
    target = QtProperty(str, lambda self: self._target, notify=changed)  # "playlist:12"
    refused = QtProperty(bool, lambda self: self._what == REFUSE, notify=changed)  # R8.9
    targetText = QtProperty(str, lambda self: self._text, notify=changed)
    line = QtProperty(int, lambda self: self._line, notify=changed)  # -1: none
