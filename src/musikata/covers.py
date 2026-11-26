"""Covers as the views show them (R5.1, A2.1): the image provider QML loads `image://covers/<name>`
from, on QML's image threads (each view's Image is asynchronous), never the GUI thread (A1.3).

A thumbnail is made once, from the cover the album's row names (a picture embedded in a song, or an
image in its folder), scaled so its shorter side is one of SIZES, and kept in the root's cache
folder (R1.5) under its name, a hash of the cover's path, size and modification time
(musikata_core.art.thumb_id): a changed cover is a new name. A cover that can't be read, or isn't
an image Qt can decode, gives an empty image, which the views show as no cover (R5.7), and the App
log says which."""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from musikata_core import art, tags

log = logging.getLogger(__name__)

SIZES = (256, 512)  # a thumbnail's shorter side, in pixels: the grids', the album page's


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
        """The thumbnail `name` at `side`: the cached one, else made from the cover and kept."""
        for ext in (".jpg", ".png"):
            path = os.path.join(self._cache, f"{name}-{side}{ext}")
            if os.path.exists(path):
                cached = QImage(path)
                if not cached.isNull():
                    return cached
        row = (
            self._read()
            .execute("SELECT cover_kind, cover FROM album WHERE thumb = ? LIMIT 1", (name,))
            .fetchone()
        )
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
