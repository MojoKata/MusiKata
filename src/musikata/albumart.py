"""The Album art dialog in the running app (R5.2 to R5.5, T02-album-art): opened from an album's
page, the Edit tags panel's cover, or an image dropped on an album's cover in any view (R5.4); the
current cover large with where it is, beside it the covers found (musikata_core.art.gather), each
with its thumbnail, where it is, its size and a note, one chosen with its radio button; the drop
zone, Choose file…, pasting (Ctrl+V / ⌘V) and Find online… (R16.4, a later version); R5.3's four
checkboxes, and the footer saying what saving will change, or "No change". Saving is a batch
(tags.Batch, R4.7) on a thread of its own, the songs' covers and cover.jpg in one entry of the
change history (R4.9), with progress for more than a few files, Cancel, the files that failed
listed with why and Retry; then the message that follows a save, with Undo (R6.7). The album
page's ⋯ › Save cover to folder (R5.5) writes the embedded cover as cover.jpg the same way,
without the dialog.

What an image from outside is (`sniff`, `problem`) and what saving writes (`plan`) are the core's,
plain and tested apart; here Qt decodes each image (`decode`), and makes what is written of it
(`forms_of`): a CMYK JPEG made RGB, a WebP made a JPEG or, with transparency, a PNG to embed; a
larger image shrunk to 1200 × 1200 and saved as JPEG at quality 90 before it is embedded (R5.3);
cover.jpg a JPEG at full size, transparency laid on white. The songs' pictures and the folders'
images are read, and every image decoded, off the GUI thread (models.Searcher's thread), and the
thumbnails handed to QML through `ArtImages` (`image://albumart/<key>`)."""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QObject, QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider

from musikata_core import art, scanner
from musikata_core.art import Added, Album, Candidate, Forms, ImageInfo, ImageWritten, Options
from musikata_core.tags import Batch, Failed, Job, Outcome, TagReadError, Written
from musikata_core.tags import pictures as read_pictures
from musikata_core.tags.read import EXTENSIONS

from .edittags import FEW, failed_rows, failed_text, progress_text
from .history import ChangeHistory
from .models import Searcher

log = logging.getLogger(__name__)

ABOUT = (
    "Choose one cover for the album. It is embedded in every song and saved beside them as "
    "cover.jpg."
)
ONLINE_LATER = "Finding covers online comes in a later version"  # R16.4: slice 10
NOTHING_PASTED = "There's no image on the clipboard to paste"
NOT_A_FILE = "{} isn't a file on this computer: save the image to a file first, then drop that"
THUMB = 112  # a candidate's thumbnail, in pixels (T02's 56, at twice the density)
LARGE = 512  # the current cover's
WHITE = QColor(255, 255, 255)  # what transparency is laid on in a JPEG
RAW = ("image/jpeg", "image/png", "image/webp")  # an image on the clipboard as its own bytes


class ArtError(Exception):
    """An image that can't be used, and why, in words a person can act on."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


# ---------- an image, decoded and written (Qt's) ----------


def decode(data: bytes) -> QImage:
    """`data` decoded; ArtError when Qt can't, the bytes damaged or cut short. From the bytes
    with QImage.fromData, never a QImageReader on a QBuffer made here: Qt's reader holds a mutex
    while it finds the handler, and calls on a Python-made device take the GIL, which a cover
    decoding on QML's pixmap reader (covers.thumbnail) holds while it waits on that mutex: a
    deadlock (coding.md, "Threads and processes")."""
    image = QImage.fromData(data)
    if image.isNull():
        raise ArtError("it can't be decoded: the file is damaged")
    return image


def encoded(image: QImage, kind: str, quality: int = art.QUALITY) -> bytes:
    """`image` saved as a JPEG ("JPEG", at `quality`, transparency laid on white, CMYK made RGB)
    or a PNG ("PNG")."""
    if kind == "JPEG":
        flat = QImage(image.size(), QImage.Format.Format_RGB32)
        flat.fill(WHITE)
        painter = QPainter(flat)
        painter.drawImage(0, 0, image.convertToFormat(QImage.Format.Format_ARGB32))
        painter.end()
        image = flat
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    # PySide6 takes the format as str, though its stubs say bytes (bytes raise ValueError)
    if not image.save(buffer, kind, quality):  # type: ignore[call-overload]
        raise ArtError(f"it couldn't be made a {kind}")
    return bytes(buffer.data().data())


def forms_of(data: bytes, info: ImageInfo, image: QImage, side: int = art.SHRINK) -> Forms:
    """What the image `data` (decoded as `image`) is written as (art.Forms): embedded as it is,
    unless a CMYK JPEG or a WebP (made a JPEG, or a PNG when it has transparency); shrunk to
    `side` as a JPEG when larger (R5.3); cover.jpg as it is when an RGB JPEG, else made one."""
    embed = data
    if art.needs_converting(info, jpeg=False):
        embed = encoded(image, "PNG" if info.alpha else "JPEG")
    shrunk = None
    if art.needs_shrinking(info, side):
        small = image.scaled(
            side,
            side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        shrunk = encoded(small, "JPEG")
    folder = encoded(image, "JPEG") if art.needs_converting(info, jpeg=True) else data
    return Forms(embed, shrunk, folder)


def thumbnail(image: QImage, side: int) -> QImage:
    """`image` scaled so its shorter side is `side` (never up), for the dialog to show."""
    if min(image.width(), image.height()) <= side:
        return image
    return image.scaled(
        side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )  # fmt: skip


@dataclass(frozen=True)
class Prepared:
    """An image made ready: what it is written as, and its thumbnail, or why it can't be used."""

    forms: Forms | None
    thumb: QImage
    problem: str = ""


def prepare(data: bytes, side: int = art.SHRINK, thumb: int = THUMB) -> Prepared:
    """An image from anywhere checked (art.problem), decoded and made ready; never raises."""
    info = art.sniff(data)
    why = art.problem(data, info)
    if why or info is None:
        return Prepared(None, QImage(), why)
    try:
        image = decode(data)
        return Prepared(forms_of(data, info, image, side), thumbnail(image, thumb))
    except ArtError as e:
        return Prepared(None, QImage(), e.why)


# ---------- what is read for an album: off the GUI thread ----------


@dataclass(frozen=True)
class Target:
    """What the dialog is open on: its title (the album's), its songs' paths under the root, in
    their order, the album's id (-1: songs on no album), and its folder: the one most of its songs
    are in (the album's row's, A2.1), whose images are its candidates and where cover.jpg goes; a
    song of it elsewhere (a single beside the artist's albums) leaves that folder alone."""

    title: str
    paths: tuple[str, ...]
    album_id: int = -1
    folder: str = ""

    @property
    def folders(self) -> tuple[str, ...]:
        return (self.folder,)


def target_of_album(c: sqlite3.Connection, album_id: int) -> Target | None:
    """The album with that id, its songs in disc and track order; None when there is none."""
    r = c.execute("SELECT title, folder FROM album WHERE id = ?", (album_id,)).fetchone()
    if r is None:
        return None
    paths = [str(p) for (p,) in c.execute(
        "SELECT path FROM song WHERE album_id = ? ORDER BY disc, track, path", (album_id,)
    )]  # fmt: skip
    return Target(str(r[0] or ""), tuple(paths), album_id, str(r[1] or "")) if paths else None


def target_of_songs(c: sqlite3.Connection, ids: Sequence[int], title: str) -> Target | None:
    """For the Edit tags panel's cover: the album most of the songs `ids` are on, else the songs
    themselves (named `title`); None when the index has none of them."""
    rows = []
    for i in range(0, len(ids), 500):
        part = tuple(ids[i : i + 500])
        marks = ", ".join("?" * len(part))
        rows += c.execute(f"SELECT path, album_id FROM song WHERE id IN ({marks})", part).fetchall()
    if not rows:
        return None
    albums = Counter(a for _, a in rows if a is not None)
    if albums:
        found = target_of_album(c, albums.most_common(1)[0][0])
        if found is not None:
            return found
    paths = sorted(str(p) for p, _ in rows)
    folder = Counter(p.rpartition("/")[0] for p in paths).most_common(1)[0][0]
    return Target(title, tuple(paths), folder=folder)


def read_songs(
    root: str, paths: Sequence[str], pictures: Callable[[str], list[Any]] = read_pictures
) -> list[art.SongArt]:
    """Each song's pictures as its file holds them (R5.1), or why they couldn't be read."""
    out = []
    for path in paths:
        typed = EXTENSIONS.get(os.path.splitext(path)[1].lower()) != "m4a"  # MP4's covr: no types
        try:
            out.append(art.SongArt(path, tuple(pictures(scanner.full_path(root, path))), typed))
        except (OSError, TagReadError) as e:
            log.warning("the pictures of %s couldn't be read: %s", path, e)
            out.append(art.SongArt(path, (), typed, str(e)))
    return out


def read_images(root: str, folders: Sequence[str]) -> list[art.FolderImage]:
    """The images in each folder (R5.1's kinds, hidden files left out), with their bytes; one too
    large or that can't be read has why instead."""
    out = []
    for folder in folders:
        full = scanner.full_path(root, folder)
        try:
            names = sorted(e.name for e in os.scandir(full) if e.is_file() and art.is_image(e.name))
        except OSError as e:
            log.warning("the folder %s couldn't be listed: %s", full, e)
            continue
        for name in names:
            path = os.path.join(full, name)
            try:
                if os.path.getsize(path) > art.MAX_BYTES:
                    out.append(art.FolderImage(folder, name, None, "it is too large"))
                    continue
                with open(path, "rb") as f:
                    out.append(art.FolderImage(folder, name, f.read()))
            except OSError as e:
                out.append(art.FolderImage(folder, name, None, str(e)))
    return out


def read_file(path: str) -> tuple[str, bytes | None, str]:
    """An image file from outside (dropped or chosen): its name, its bytes, or why not."""
    name = os.path.basename(path)
    try:
        size = os.path.getsize(path)
        if size > art.MAX_BYTES:
            return (
                name,
                None,
                (f"it is {art.size_text(size)}, too large for a cover: save a smaller copy first"),
            )
        with open(path, "rb") as f:
            return name, f.read(), ""
    except IsADirectoryError:
        return name, None, "it is a folder, not an image"
    except FileNotFoundError:
        return name, None, "it isn't there any more"
    except OSError as e:
        return name, None, f"it can't be read: {e.strerror or e}"


@dataclass(frozen=True)
class Loaded:
    """An album read: its art, each image made ready (by key), the current cover's large
    thumbnail."""

    target: Target
    album: Album
    ready: dict[str, Prepared]
    large: QImage


def load(root: str, target: Target, side: int = art.SHRINK) -> Loaded:
    """On the search thread: the album's songs' pictures and folders' images read, gathered
    (art.gather), and every candidate decoded and made ready."""
    songs = read_songs(root, target.paths)
    images = read_images(root, target.folders)
    album = art.gather(songs, images, folders=target.folders)
    ready = {c.key: prepare(c.data, side) for c in album.candidates if not c.problem}
    large = QImage()
    if album.current.data is not None:
        with contextlib.suppress(ArtError):  # the current cover then shows as none
            large = thumbnail(decode(album.current.data), LARGE)
    return Loaded(target, album, ready, large)


def with_problems(album: Album, ready: dict[str, Prepared]) -> Album:
    """The album's candidates, each that couldn't be decoded with why."""
    out = []
    for c in album.candidates:
        found = ready.get(c.key)
        out.append(replace(c, problem=found.problem) if found and found.problem else c)
    return replace(album, candidates=tuple(out))


# ---------- the thumbnails, as QML loads them ----------


class ArtImages(QQuickImageProvider):
    """`image://albumart/<key>`: the dialog's thumbnails, by their image's key (art.key_of; the
    current cover's large one as "large-<key>"), kept while the dialog shows them."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._lock = threading.Lock()
        self._images: dict[str, QImage] = {}

    def put(self, key: str, image: QImage) -> None:
        with self._lock:
            self._images[key] = image

    def clear(self) -> None:
        with self._lock:
            self._images = {}

    def requestImage(self, id: str, size: QSize, requestedSize: QSize) -> QImage:  # noqa: A002, N803
        with self._lock:
            return self._images.get(id.partition("?")[0], QImage())


# ---------- the dialog ----------


def options_of(options: Options) -> dict[str, Any]:
    """R5.3's checkboxes as QML shows them."""
    side = f"{options.side} × {options.side}"
    return {"embed": options.embed, "folder": options.folder, "shrink": options.shrink,
            "removeOthers": options.remove_others,
            "shrinkLabel": f"Shrink to {side} before embedding"}  # fmt: skip


OPTION_NAMES = {"embed": "embed", "folder": "folder", "shrink": "shrink",
                "removeOthers": "remove_others"}  # fmt: skip


class AlbumArt(QObject):
    """The Album art dialog as the window sees it. `read` gives this thread's reading connection
    to the root's index; `history` keeps each save and says its message (R4.9, R6.7); `saved` is
    told of the songs written (Library.saved). `write` writes one song (ratings.Writing, or
    safe.save, unless a test's); `trash` moves a file to the system's trash (art.to_trash). A save
    runs on `executor` (its own thread when None). `available` says whether the root is there
    (R2.10): nothing is saved while it isn't."""

    changed = Signal()  # open or not, what it shows, the choice, the options
    savingChanged = Signal()  # the progress, the files that failed
    _progressed = Signal(int, int, str)
    _done = Signal(object)

    def __init__(
        self,
        root: str,
        read: Callable[[], sqlite3.Connection],
        write: Callable[[Job], Written],
        history: ChangeHistory | None = None,
        saved: Callable[[Sequence[Written]], object] | None = None,
        trash: art.Trash = art.to_trash,
        executor: Executor | None = None,
        images: ArtImages | None = None,
        available: Callable[[], bool] = lambda: True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._read, self._write, self._trash = root, read, write, trash
        self._history, self._saved, self._available = history, saved, available
        self._executor = executor
        self.images = images or ArtImages()
        self._searcher = Searcher(self)
        self._open = self._loading = False
        self._ticket = self._generation = 0
        self._target: Target | None = None
        self._album: Album | None = None
        self._ready: dict[str, Prepared] = {}
        self._added: list[Added] = []
        self._chosen: str | None = None
        self._options = Options()
        self._message = ""
        self._then_urls: list[str] = []
        self._then_choose: str = ""
        self._batch: Batch[Written | ImageWritten] | None = None
        self._jobs: list[Job] = []
        self._description = ""
        self._close_after = False
        self._progress = (0, 0)
        self._failed: list[Failed] = []
        self._closed = False
        self._progressed.connect(self._on_progress)
        self._done.connect(self._on_done)

    # ---------- opening it (R5.2, R5.4) ----------

    @Slot(int)
    def openAlbum(self, album_id: int) -> None:  # noqa: N802
        """Album art on an album's page: the dialog on that album."""
        self._open_on(lambda c: target_of_album(c, album_id))

    @Slot("QVariantList", str)
    def openSongs(self, ids: list[Any], title: str) -> None:  # noqa: N802
        """The Edit tags panel's cover: the album most of the songs edited are on, else them."""
        wanted = [int(i) for i in ids]
        self._open_on(lambda c: target_of_songs(c, wanted, title))

    @Slot(int, "QVariantList")
    def dropOnAlbum(self, album_id: int, urls: list[Any]) -> None:  # noqa: N802
        """R5.4: an image dropped on an album's cover in any view opens the dialog with it
        chosen."""
        self._then_urls = [str(u.toString() if isinstance(u, QUrl) else u) for u in urls]
        self.openAlbum(album_id)

    @Slot("QVariantList", str, "QVariantList")
    def dropOnSongs(self, ids: list[Any], title: str, urls: list[Any]) -> None:  # noqa: N802
        """R5.4 on the Edit tags panel's cover: the dialog on its songs' album, the image chosen."""
        self._then_urls = [str(u.toString() if isinstance(u, QUrl) else u) for u in urls]
        self.openSongs(ids, title)

    def _open_on(self, find: Callable[[sqlite3.Connection], Target | None]) -> None:
        if self._batch is not None:
            log.info("the album art dialog waits: a save goes on")
            return
        self._reset()
        self._open, self._loading = True, True
        self._ticket += 1
        ticket, root, read, side = self._ticket, self._root, self._read, self._options.side

        def work() -> Loaded | None:
            target = find(read())
            return load(root, target, side) if target is not None else None

        self._searcher.submit("load", work, lambda found: self._on_loaded(ticket, found))
        self.changed.emit()

    def _reset(self) -> None:
        self._target, self._album, self._ready, self._added = None, None, {}, []
        self._chosen, self._message, self._failed = None, "", []
        self._options = Options()
        self.images.clear()

    def _on_loaded(self, ticket: int, found: Loaded | None) -> None:
        if ticket != self._ticket or not self._open:
            return
        self._loading = False
        if found is None:
            self._message = "This album's songs aren't in the library any more"
            self.changed.emit()
            return
        self._target, self._ready = found.target, dict(found.ready)
        self._album = with_problems(found.album, self._ready)
        self._generation += 1
        for key, ready in self._ready.items():
            self.images.put(key, ready.thumb)
        if found.album.current.key is not None:
            self.images.put(f"large-{found.album.current.key}", found.large)
        self._chosen = art.chosen_first(self._album)
        if self._then_choose and self._album.candidate(self._then_choose) is not None:
            self._chosen = self._then_choose
        self._then_choose = ""
        self.changed.emit()
        urls, self._then_urls = self._then_urls, []
        if urls:
            self.addUrls(urls)

    # ---------- images from outside (R5.2.1) ----------

    @Slot("QVariantList")
    def addUrls(self, urls: list[Any]) -> None:  # noqa: N802
        """Images dropped on the dialog: each read and checked off the GUI thread; the last that
        can be used is chosen, and one that can't says why."""
        self._add_urls(urls, "dropped")

    @Slot("QVariantList")
    def chooseFiles(self, urls: list[Any]) -> None:  # noqa: N802
        """Choose file…'s answer, as a drop's."""
        self._add_urls(urls, "chosen")

    def _add_urls(self, urls: Sequence[Any], origin: str) -> None:
        files, refused = [], []
        for u in urls:
            url = u if isinstance(u, QUrl) else QUrl(str(u))
            if url.isLocalFile():
                files.append((origin, url.toLocalFile()))
            elif not url.scheme() and url.path():
                files.append((origin, url.path()))  # a plain path
            else:
                refused.append(NOT_A_FILE.format(url.fileName() or url.toString()))
        self._add(files, refused)

    @Slot()
    def paste(self) -> None:
        """Ctrl+V / ⌘V: the image on the clipboard, as its own bytes when it holds a JPEG, PNG or
        WebP, else as Qt's image (kept as a PNG), else the image files it names."""
        clipboard = QGuiApplication.clipboard()
        self.paste_from(clipboard.mimeData(), clipboard.image())

    def paste_from(self, mime: QMimeData | None, image: QImage) -> None:
        if mime is not None:
            for kind in RAW:
                if mime.hasFormat(kind):
                    self._add_bytes([("pasted", "", bytes(mime.data(kind).data()))])
                    return
            if mime.hasUrls():
                self._add_urls(list(mime.urls()), "chosen")
                return
        if not image.isNull():
            self._add_bytes([("pasted", "", image)])  # made a PNG off the GUI thread
            return
        self._say(NOTHING_PASTED)

    @Slot()
    def findOnline(self) -> None:  # noqa: N802
        """Find online… (R16.4): a later version's."""
        self._say(ONLINE_LATER)

    def _add(self, files: list[tuple[str, str]], refused: list[str]) -> None:
        if refused:
            self._say(refused[-1])
        if not files or self._album is None:
            return
        side = self._options.side

        def work() -> list[tuple[Added | None, Prepared | None, str]]:
            out: list[tuple[Added | None, Prepared | None, str]] = []
            for origin, path in files:
                name, data, why = read_file(path)
                if data is None:
                    out.append((None, None, f"{name}: {why}"))
                    continue
                ready = prepare(data, side)
                out.append((Added(origin, name, data), ready, f"{name}: {ready.problem}"))
            return out

        self._searcher.submit(("add", self._ticket), work, self._on_added(self._ticket))

    def _add_bytes(self, items: list[tuple[str, str, bytes | QImage]]) -> None:
        if self._album is None:
            return
        side = self._options.side

        def work() -> list[tuple[Added | None, Prepared | None, str]]:
            out: list[tuple[Added | None, Prepared | None, str]] = []
            for origin, name, item in items:
                try:
                    data = encoded(item, "PNG") if isinstance(item, QImage) else item
                except ArtError as e:
                    out.append((None, None, f"The pasted image: {e.why}"))
                    continue
                ready = prepare(data, side)
                what = name or "The pasted image"
                out.append((Added(origin, name, data), ready, f"{what}: {ready.problem}"))
            return out

        self._searcher.submit(("add", self._ticket), work, self._on_added(self._ticket))

    def _on_added(
        self, ticket: int
    ) -> Callable[[list[tuple[Added | None, Prepared | None, str]] | None], None]:
        def then(found: list[tuple[Added | None, Prepared | None, str]] | None) -> None:
            if ticket != self._ticket or self._album is None or not found:
                return
            why = ""
            chosen = None
            for added, ready, problem in found:
                if added is None or ready is None or ready.problem:
                    why = problem
                    continue
                key = art.key_of(added.data)
                self._added = [a for a in self._added if art.key_of(a.data) != key] + [added]
                self._ready[key] = ready
                self.images.put(key, ready.thumb)
                chosen = key
            album = self._album
            self._album = with_problems(
                art.gather(album.songs, album.images, self._added, album.folders), self._ready
            )
            if chosen is not None:
                self._chosen = chosen
            self._message = why
            self.changed.emit()

        return then

    def _say(self, text: str) -> None:
        self._message = text
        self.changed.emit()

    # ---------- the choice and the options (R5.2, R5.3) ----------

    @Slot(str)
    def choose(self, key: str) -> None:
        """A candidate's radio button."""
        found = self._album.candidate(key) if self._album is not None else None
        if found is None or found.problem:
            return
        self._chosen = key
        self.changed.emit()

    @Slot(str, bool)
    def setOption(self, name: str, on: bool) -> None:  # noqa: N802
        """One of R5.3's checkboxes: "embed", "folder", "shrink", "removeOthers"."""
        if name not in OPTION_NAMES:
            raise ValueError(f"no such option: {name}")
        self._options = replace(self._options, **{OPTION_NAMES[name]: bool(on)})
        self.changed.emit()

    def plan(self) -> art.Plan:
        """What saving would write now (art.plan)."""
        chosen = self._chosen_candidate()
        ready = self._ready.get(chosen.key) if chosen is not None else None
        if self._album is None or ready is None or ready.forms is None:
            return art.Plan()
        return art.plan(self._album, ready.forms, self._options, self._root)

    def _chosen_candidate(self) -> Candidate | None:
        if self._album is None or self._chosen is None:
            return None
        return self._album.candidate(self._chosen)

    # ---------- saving (R5.3, R4.7) ----------

    @Slot()
    def save(self) -> None:
        """Save N files, or Done when nothing changes: the chosen cover written as the options
        say, as one entry in the change history; the dialog closes once it is saved."""
        if self._batch is not None or self._album is None:
            return
        chosen = self._chosen_candidate()
        if chosen is None or chosen.problem:
            return
        planned = self.plan()
        if not planned.jobs:
            self.close()
            return
        if not self._available():
            self._say("Nothing can be saved while the music folder isn't available")
            return
        title = self._target.title if self._target is not None else ""
        self._start(list(planned.jobs), art.description_of(title, planned), close_after=True)

    @Slot(int)
    def saveToFolder(self, album_id: int) -> None:  # noqa: N802
        """R5.5: ⋯ › Save cover to folder on an album's page: its embedded cover written as
        cover.jpg in its folders, without the dialog; the message says what was done, or why
        not."""
        if not self._available():
            self._tell("Nothing can be saved while the music folder isn't available")
            return
        if self._batch is not None:
            self._tell("A save is going on: try again once it is done")
            return
        root, read = self._root, self._read

        def work() -> tuple[Target, art.Plan] | str:
            target = target_of_album(read(), album_id)
            if target is None:
                return "This album's songs aren't in the library any more"
            album = art.gather(read_songs(root, target.paths), read_images(root, target.folders),
                               folders=target.folders)  # fmt: skip
            cover = art.extract(album)
            if cover is None:
                return f"{target.title or 'This album'} has no embedded cover to save"
            ready = prepare(cover.data)
            if ready.forms is None:
                return f"The embedded cover can't be saved: {ready.problem}"
            options = Options(embed=False, folder=True, shrink=False, remove_others=False)
            planned = art.plan(album, ready.forms, options, root)
            if not planned.jobs:
                return f"{art.COVER_JPG} is already the embedded cover"
            return target, planned

        def then(found: tuple[Target, art.Plan] | str | None) -> None:
            if isinstance(found, tuple) and self._batch is None and not self._closed:
                target, planned = found
                self._start(list(planned.jobs), f"Save cover to folder: {target.title}", False)
            elif isinstance(found, str):
                self._tell(found)

        self._searcher.submit("extract", work, then)

    def _tell(self, text: str) -> None:
        if self._history is not None:
            self._history.say(text)
        else:
            log.info("%s", text)

    @Slot()
    def retry(self) -> None:
        """R4.7's Retry: the files that failed, written again."""
        if self._batch is not None or not self._failed:
            return
        self._start([f.job for f in self._failed], self._description, self._close_after)

    def _start(self, jobs: list[Job], description: str, close_after: bool) -> None:
        record = self._history.recording() if self._history is not None else None
        write = art.writer(self._write, self._trash)
        batch: Batch[Written | ImageWritten] = Batch(
            jobs, write, self._progressed.emit, record=record, action="album-art",
            description=description,
        )  # fmt: skip
        self._batch, self._jobs, self._progress, self._failed = batch, jobs, (0, len(jobs)), []
        self._description, self._close_after = description, close_after
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="album art")
        self.savingChanged.emit()
        self.changed.emit()
        self._executor.submit(self._run, batch, jobs)

    def _run(self, batch: Batch[Written | ImageWritten], jobs: list[Job]) -> None:
        try:
            out = batch.run()
        except Exception as e:  # noqa: BLE001  (the batch fails its files, never itself; logged)
            log.exception("the album art's save failed")
            out = Outcome(failed=[Failed(j, f"it wasn't saved: {e}") for j in jobs])
        self._done.emit(out)

    @Slot()
    def cancel(self) -> None:
        """Cancel (R4.7) while saving: the save stops before its next file. Otherwise the
        dialog closes."""
        if self._batch is not None:
            self._batch.cancel()
        else:
            self.close()

    @Slot(int, int, str)
    def _on_progress(self, done: int, total: int, _path: str) -> None:
        self._progress = (done, total)
        self.savingChanged.emit()

    @Slot(object)
    def _on_done(self, out: Outcome[Written | ImageWritten]) -> None:
        self._batch = None
        self._failed = list(out.failed)
        songs = art.written_songs(out.saved)
        if songs and self._saved is not None:
            self._saved(songs)  # their rows (Library.saved); cover.jpg's folder is rescanned
        if self._history is not None:
            self._history.after_save(out)  # type: ignore[arg-type]
        if self._close_after and not self._failed and not out.cancelled:
            self.close()
        self.savingChanged.emit()
        self.changed.emit()

    @Slot()
    def dismissFailed(self) -> None:  # noqa: N802
        self._failed = []
        self.savingChanged.emit()

    @Slot()
    def close(self) -> None:
        """×, Esc, Done: the dialog closes, saving nothing; a save going on goes on."""
        if not self._open:
            return
        self._open = self._loading = False
        self._ticket += 1
        self._then_urls = []
        if self._batch is None:
            self._reset()
        self.changed.emit()

    def go(self, step: dict[str, Any], library: QObject) -> None:
        """A tour's step (A1.6): {"art": True} opens the dialog on the album the step shows."""
        if not step.get("art"):
            if self._open:
                self.close()
            return
        album = library.property("album")
        album_id = int(album.property("id")) if album is not None else -1
        self.openAlbum(album_id)

    def shut(self) -> None:
        """For closing the window: a save going on stops before its next file and is waited for;
        nothing starts after; what the threads held is let go (A1.3)."""
        self._closed = True
        if self._batch is not None:
            self._batch.cancel()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._batch = None
        self._searcher.wait()
        self._saved = self._history = None
        self._available = _gone
        self.images.clear()

    # ---------- what QML reads ----------

    def _get_current(self) -> dict[str, Any]:
        current = self._album.current if self._album is not None else art.Current()
        source = f"image://albumart/large-{current.key}?{self._generation}" if current.key else ""
        return {"source": source, "line": current.line if self._album is not None else "",
                "where": current.where, "tone": current.tone}  # fmt: skip

    def _get_candidates(self) -> list[dict[str, Any]]:
        if self._album is None:
            return []
        return [
            {"key": c.key, "source": f"image://albumart/{c.key}?{self._generation}",
             "title": c.title, "detail": c.detail, "chosen": c.key == self._chosen,
             "usable": not c.problem}
            for c in self._album.candidates
        ]  # fmt: skip

    def _get_footer(self) -> str:
        if self._album is None:
            return ""
        return art.footer(self.plan(), self._options, self._chosen_candidate())

    def _get_save_label(self) -> str:
        return art.save_label(self.plan())

    def _get_can_save(self) -> bool:
        chosen = self._chosen_candidate()
        return self._batch is None and chosen is not None and not chosen.problem

    def _get_progress(self) -> dict[str, Any]:
        done, total = self._progress
        if self._batch is None or total <= FEW:
            return {}
        return {"text": progress_text(done, total), "fraction": done / total}

    def _get_failed(self) -> dict[str, Any]:
        if not self._failed:
            return {}
        return {"title": failed_text(len(self._failed)),
                "rows": failed_rows(self._failed, self._root)}  # fmt: skip

    def _get_title(self) -> str:
        title = self._target.title if self._target is not None else ""
        return f"Album art · {title}" if title else "Album art"

    opened = QtProperty(bool, lambda self: self._open, notify=changed)
    loading = QtProperty(bool, lambda self: self._loading, notify=changed)
    saving = QtProperty(bool, lambda self: self._batch is not None, notify=savingChanged)
    title = QtProperty(str, _get_title, notify=changed)
    about = QtProperty(str, lambda self: ABOUT, constant=True)
    onlineNote = QtProperty(str, lambda self: ONLINE_LATER, constant=True)
    current = QtProperty(dict, _get_current, notify=changed)
    candidates = QtProperty(list, _get_candidates, notify=changed)
    options = QtProperty(dict, lambda self: options_of(self._options), notify=changed)
    footer = QtProperty(str, _get_footer, notify=changed)
    saveLabel = QtProperty(str, _get_save_label, notify=changed)
    canSave = QtProperty(bool, _get_can_save, notify=changed)
    message = QtProperty(str, lambda self: self._message, notify=changed)
    progress = QtProperty(dict, _get_progress, notify=savingChanged)
    failed = QtProperty(dict, _get_failed, notify=savingChanged)


def _gone() -> bool:
    return False
