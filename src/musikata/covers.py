"""Covers as the views show them (R5.1, A2.1): the image provider QML loads `image://covers/<name>`
from, on QML's image threads (each view's Image is asynchronous), never the GUI thread (A1.3).

A thumbnail is made once, from the cover the album's row names (a picture embedded in a song, or an
image in its folder), scaled so its shorter side is one of SIZES, and kept in the root's cache
folder (R1.5) under its name, a hash of the cover's path, size and modification time
(musikata_core.art.thumb_id): a changed cover is a new name. A cover that can't be read, or isn't
an image Qt can decode, gives an empty image, which the views show as no cover (R5.7), and the App
log says which. A thumbnail's cover is found by its name in the album rows, else in the folder rows
(a folder's own cover, R5.8), else among the songs on no album whose covers make a folder's mosaic
(folders.loose_cover).

A folder's mosaic (R5.8, A2.7) is `image://covers/mosaic/<name>+<name>…`, its pieces' thumbnails by
name: drawn with QPainter from those thumbnails at the size asked for, each a centre crop in R5.8's
layout with a gap between, and kept in the cache under a hash of its pieces' names, which are
hashes of their covers' paths, sizes and modification times; so a changed cover makes a new
mosaic, drawn when next shown.

After each scan the cache is trimmed (A2.7, `trim`): a thumbnail or mosaic that no album or folder
row points at any more is removed, on the scan's thread; a file of any other name is left."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable, Collection

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider

from musikata_core import art, folders, tags

log = logging.getLogger(__name__)

SIZES = (256, 512)  # a thumbnail's shorter side, in pixels: the grids', the album page's
MOSAIC = "mosaic/"  # a mosaic's address under the provider, before its pieces' names
# a cached thumbnail's or mosaic's file: its name (art.thumb_id, mosaic_name), its side, its kind
CACHED = re.compile(r"(m?[0-9a-f]{32})-[0-9]+\.(?:jpg|png)")


def mosaic_id(thumbs: list[str]) -> str:
    """The provider's name for a mosaic of these thumbnails (R5.8), in order."""
    return MOSAIC + "+".join(thumbs)


def mosaic_name(thumbs: list[str]) -> str:
    """The name a mosaic is cached under: a hash of its pieces' names (A2.7)."""
    return "m" + hashlib.sha256("+".join(thumbs).encode()).hexdigest()[:32]


def cached_name(file: str) -> str | None:
    """The name of the thumbnail or mosaic a file of the cache holds, from the file's name; None
    for a file that isn't one (a thumbnail still being saved, or anything else)."""
    found = CACHED.fullmatch(file)
    return found.group(1) if found else None


def live(c: sqlite3.Connection) -> set[str]:
    """The thumbnails and mosaics the index's rows point at (R5.1, R5.8): each album's and each
    folder's own cover's, each piece of a folder's mosaic, and the mosaic, by their names."""
    names = {str(t) for (t,) in c.execute("SELECT thumb FROM album WHERE thumb IS NOT NULL")}
    names |= {str(t) for (t,) in c.execute("SELECT thumb FROM folder WHERE thumb IS NOT NULL")}
    for (mosaic,) in c.execute("SELECT mosaic FROM folder WHERE mosaic IS NOT NULL"):
        pieces = str(mosaic).split()
        names.update(pieces)
        if len(pieces) > 1:  # one piece shows whole, as itself (folders.picture_url)
            names.add(mosaic_name(pieces))
    return names


def trim(cache: str, kept: Collection[str]) -> list[str]:
    """Removes from the cache folder `cache` each thumbnail and mosaic whose name isn't in `kept`
    (A2.7); every other file stays. The files removed, by name; a cache that isn't there, or a file
    that can't be removed, costs only room, and the log says which."""
    try:
        files = sorted(os.listdir(cache))
    except FileNotFoundError:
        return []
    except OSError as e:
        log.warning("the cover cache %s couldn't be trimmed: %s", cache, e)
        return []
    removed = []
    for file in files:
        name = cached_name(file)
        if name is None or name in kept:
            continue
        try:
            os.remove(os.path.join(cache, file))
        except FileNotFoundError:
            continue
        except OSError as e:
            log.warning("the stale thumbnail %s couldn't be removed from %s: %s", file, cache, e)
            continue
        removed.append(file)
    if removed:
        log.info("removed %d stale thumbnails and mosaics from %s", len(removed), cache)
    return removed


def trim_cache(cache: str, c: sqlite3.Connection) -> list[str]:
    """After a scan (A2.7): the thumbnails and mosaics no row of the index at `c` points at any
    more, removed from `cache` (`trim`)."""
    return trim(cache, live(c))


def gap_for(side: int) -> int:
    """The gap between a mosaic's pieces at `side` pixels: R5.8's 2 px where a tile is drawn,
    about 160 px wide from a 256 px image."""
    return max(2, round(side * 2 / 160))


def draw_mosaic(pieces: list[QImage], side: int) -> QImage:
    """A square mosaic `side` pixels wide of up to four pictures in R5.8's layout, each a centre
    crop with a transparent gap between them; a piece that is empty leaves its place empty, and
    with none to draw the image is empty."""
    if not any(not p.isNull() for p in pieces):
        return QImage()
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    gap = gap_for(side)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for piece, (fx, fy, fw, fh) in zip(pieces, folders.layout(len(pieces)), strict=False):
        x, y = round(fx * (side + gap)), round(fy * (side + gap))
        w, h = round(fw * (side + gap)) - gap, round(fh * (side + gap)) - gap
        if piece.isNull() or w <= 0 or h <= 0:
            continue
        scaled = piece.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        crop = QRect((scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h)
        painter.drawImage(QRect(x, y, w, h), scaled, crop)
    painter.end()
    return image


def side_for(requested: QSize) -> int:
    """The thumbnail size for an Image asking for `requested` (its sourceSize): the smallest of
    SIZES at least as large, else the largest."""
    want = max(requested.width(), requested.height(), 0)
    return next((s for s in SIZES if s >= want), SIZES[-1])


def thumbnail(data: bytes, side: int) -> QImage:
    """`data`, an image in any format Qt reads, scaled so its shorter side is `side` (never up);
    an empty image when it can't be decoded."""
    image = QImage.fromData(data)
    if image.isNull():
        return QImage()
    if min(image.width(), image.height()) > side:
        image = image.scaled(
            side,
            side,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
    return image


class Covers(QQuickImageProvider):
    """`image://covers/<name>`: an album's cover's thumbnail, from the cache or made and kept
    there. `read` is this thread's connection to the index (db.Index.read), `pictures` reads a
    song's embedded pictures (tags.pictures; a test's fake)."""

    def __init__(
        self,
        root: str,
        read: Callable[[], sqlite3.Connection],
        cache: str,
        pictures: Callable[[str], list[tags.Picture]] = tags.pictures,
    ) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._root, self._read, self._cache, self._pictures = root, read, cache, pictures

    def requestImage(self, id: str, size: QSize, requestedSize: QSize) -> QImage:  # noqa: A002, N803
        return self.image(id, side_for(requestedSize))

    def image(self, name: str, side: int) -> QImage:
        """The thumbnail `name` at `side`, or a mosaic's (`mosaic_id`): the cached one, else made
        from the cover, or drawn from its pieces, and kept."""
        if name.startswith(MOSAIC):
            return self.mosaic(name[len(MOSAIC) :].split("+"), side)
        cached = self._cached(name, side)
        if cached is not None:
            return cached
        c = self._read()
        row = (
            c.execute(
                "SELECT cover_kind, cover FROM album WHERE thumb = ? LIMIT 1", (name,)
            ).fetchone()
            or c.execute(
                "SELECT cover_kind, cover FROM folder WHERE thumb = ? LIMIT 1", (name,)
            ).fetchone()
        )
        if row is None and (song := folders.loose_cover(c, name)) is not None:
            row = ("embedded", song)  # a mosaic's piece from a song on no album (R5.8)
        if row is None:
            return QImage()
        data = self._source(*row)
        image = thumbnail(data, side) if data else QImage()
        if image.isNull():
            if data:
                log.warning("the cover %s couldn't be shown: not an image Qt reads", row[1])
            return image
        self._keep(image, name, side)
        return image

    def mosaic(self, thumbs: list[str], side: int) -> QImage:
        """The mosaic of these thumbnails at `side`: the cached one, else drawn from them (each
        from the cache, or made) and kept; empty when none of them can be shown."""
        name = mosaic_name(thumbs)
        cached = self._cached(name, side)
        if cached is not None:
            return cached
        image = draw_mosaic([self.image(t, side) for t in thumbs[: folders.MOSAIC]], side)
        if not image.isNull():
            self._keep(image, name, side)
        return image

    def file(self, name: str, side: int = SIZES[0]) -> str | None:
        """The file of the thumbnail `name` at `side` in the cache, made first when it isn't there
        (the system's media controls show it, A4.5); None when the cover can't be shown. Called off
        the GUI thread."""
        if self.image(name, side).isNull():
            return None
        return self._cached_path(name, side)

    def _cached_path(self, name: str, side: int) -> str | None:
        for ext in (".jpg", ".png"):
            path = os.path.join(self._cache, f"{name}-{side}{ext}")
            if os.path.exists(path):
                return path
        return None

    def _cached(self, name: str, side: int) -> QImage | None:
        for ext in (".jpg", ".png"):
            path = os.path.join(self._cache, f"{name}-{side}{ext}")
            if os.path.exists(path):
                cached = QImage(path)
                if not cached.isNull():
                    return cached
        return None

    def _source(self, kind: str, path: str) -> bytes | None:
        """The cover's bytes: the front picture embedded in the song at `path`, or the image file
        at `path`, under the root; None, logged, when it can't be read."""
        full = os.path.join(self._root, *path.split("/"))
        try:
            if kind == "embedded":
                picture = art.front(self._pictures(full))
                return picture.data if picture else None
            with open(full, "rb") as f:
                return f.read()
        except (OSError, tags.TagReadError) as e:
            log.warning("the cover in %s couldn't be read: %s", path, e)
            return None

    def _keep(self, image: QImage, name: str, side: int) -> None:
        """Saves a thumbnail into the cache, whole or not at all; a failure costs only time."""
        ext, fmt = (".png", "PNG") if image.hasAlphaChannel() else (".jpg", "JPEG")
        try:
            os.makedirs(self._cache, exist_ok=True)
            fd, tmp = tempfile.mkstemp(suffix=ext, dir=self._cache)
            os.close(fd)
            # PySide6 takes the format as str, though its stubs say bytes (bytes raise ValueError)
            if image.save(tmp, fmt, 88):  # type: ignore[call-overload]
                os.replace(tmp, os.path.join(self._cache, f"{name}-{side}{ext}"))
            else:
                os.remove(tmp)
                log.warning("the thumbnail %s couldn't be saved in %s", name, self._cache)
        except OSError as e:
            log.warning("the thumbnail %s couldn't be saved in %s: %s", name, self._cache, e)
