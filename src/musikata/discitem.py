"""The mini player's Disc (R15.3, M01): around the cover drawn as a round disc, a ring whose arc in
the `progress` colour shows how much of the song has played, and the spectrum of what is heard as
short rays around the ring, low to high clockwise from the top, each in its colour along the
design tokens' gradient (R6.2).

The spectrum is the cover's (spectrumitem.CoverSpectrum, which this item is): the bands of R11.3
gathered into RAYS, drawn at 30 frames a second on the GUI thread while shown, its window not
minimized, and playing; paused, the rays settle to their stubs and drawing stops (R15.5, A5.5).

Its geometry is plain functions of its size, the levels and the progress (`rays`, `ring`, `arc`,
`thick_lines`, `band`), drawn for the scene graph as one geometry node of triangles coloured per
vertex (A5.3); Qt Quick's software renderer draws no custom geometry, so there the same rays and
ring are painted into an image shown by one image node, as the analyzer's are (analyzeritem.py).
Every length is the mockup's at DESIGN pixels across, scaled to the item's size."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import (
    QQuickItem,
    QQuickWindow,
    QSGGeometry,
    QSGGeometryNode,
    QSGImageNode,
    QSGNode,
    QSGRendererInterface,
    QSGVertexColorMaterial,
)

from .spectrumitem import CoverSpectrum, bar_colours
from .waveitem import VERTEX, attributes, fill, premultiplied

RAYS = 72  # the spectrum's rays around the ring (M01)
DESIGN = 212.0  # the mockup's width of what the item draws: the rays' reach on either side
COVER = 74.0  # the disc's radius, at DESIGN
RING = 80.0  # the ring's radius
RING_WIDTH = 3.0
RAY_FROM = 87.0  # where a ray starts, out from the centre
RAY_STUB = 3.0  # a ray's length with nothing heard
RAY_REACH = 16.0  # what a full band adds to it
RAY_WIDTH = 2.2
STEPS = 96  # the steps round a whole circle of the ring


def scale(side: float) -> float:
    """The mockup's pixels to the item's, for an item `side` pixels across."""
    return max(0.0, side) / DESIGN


def rays(levels: NDArray[np.float32], side: float) -> NDArray[np.float32]:
    """Each ray's line (x0, y0, x1, y1) in an item `side` pixels square: the first at the top,
    the rest clockwise, each RAY_STUB long and a level's share of RAY_REACH more."""
    count = len(levels)
    if not count or side <= 0:
        return np.zeros((0, 4), np.float32)
    k, centre = scale(side), side / 2
    angles = -math.pi / 2 + np.arange(count) * (2 * math.pi / count)
    inner = RAY_FROM * k
    outer = inner + (RAY_STUB + np.clip(np.asarray(levels, np.float32), 0.0, 1.0) * RAY_REACH) * k
    cos, sin = np.cos(angles), np.sin(angles)
    return np.stack(
        [centre + inner * cos, centre + inner * sin, centre + outer * cos, centre + outer * sin],
        axis=1,
    ).astype(np.float32)


def thick_lines(lines: NDArray[np.float32], width: float) -> NDArray[np.float32]:
    """Lines `width` wide as triangles: six points a line, (x, y) rows; a line of no length has
    none."""
    if not len(lines):
        return np.zeros((0, 2), np.float32)
    d = lines[:, 2:4] - lines[:, 0:2]
    length = np.hypot(d[:, 0], d[:, 1])
    lines, d, length = lines[length > 0], d[length > 0], length[length > 0]
    normal = np.stack([-d[:, 1], d[:, 0]], axis=1) / length[:, None] * (width / 2)
    a, b = lines[:, 0:2] - normal, lines[:, 0:2] + normal
    c, e = lines[:, 2:4] - normal, lines[:, 2:4] + normal
    return np.stack([a, b, c, b, e, c], axis=1).reshape(-1, 2).astype(np.float32)


def band(
    centre: float, radius: float, width: float, start: float, sweep: float
) -> NDArray[np.float32]:
    """A ring's band `width` wide about `radius` round the centre (`centre`, `centre`), from the
    angle `start` through `sweep` (radians, clockwise from the right, as the screen's y grows
    down) as triangles: six points a step, STEPS steps a whole circle."""
    if sweep <= 0 or radius <= 0 or width <= 0:
        return np.zeros((0, 2), np.float32)
    steps = max(1, math.ceil(STEPS * sweep / (2 * math.pi)))
    angles = start + np.linspace(0.0, sweep, steps + 1)
    inner, outer = radius - width / 2, radius + width / 2
    cos, sin = np.cos(angles), np.sin(angles)
    inside = np.stack([centre + inner * cos, centre + inner * sin], axis=1)
    out = np.stack([centre + outer * cos, centre + outer * sin], axis=1)
    quads = np.stack([inside[:-1], out[:-1], inside[1:], out[:-1], out[1:], inside[1:]], axis=1)
    return quads.reshape(-1, 2).astype(np.float32)


def ring(side: float) -> NDArray[np.float32]:
    """The whole ring's band, the track the progress runs along."""
    k = scale(side)
    return band(side / 2, RING * k, RING_WIDTH * k, -math.pi / 2, 2 * math.pi)


def arc(side: float, progress: float) -> NDArray[np.float32]:
    """The ring's arc from the top clockwise, `progress` (0 to 1) of the way round."""
    k = scale(side)
    sweep = 2 * math.pi * max(0.0, min(1.0, progress))
    return band(side / 2, RING * k, RING_WIDTH * k, -math.pi / 2, sweep)


def disc_vertices(
    levels: NDArray[np.float32],
    progress: float,
    side: float,
    ray_colours: NDArray[np.uint8],
    track: QColor,
    done: QColor,
) -> NDArray[np.void]:
    """Everything the item draws as triangles (VERTEX rows, premultiplied): the ring's track in
    `track`, the arc played in `done` over it, and the rays, each in its own of `ray_colours`."""
    k = scale(side)
    parts = [
        (ring(side), np.array([[track.red(), track.green(), track.blue(), track.alpha()]])),
        (arc(side, progress), np.array([[done.red(), done.green(), done.blue(), done.alpha()]])),
    ]
    lines = rays(levels, side)
    ray_points = thick_lines(lines, RAY_WIDTH * k)
    shown = np.hypot(lines[:, 2] - lines[:, 0], lines[:, 3] - lines[:, 1]) > 0
    ray_rgba = np.repeat(ray_colours[: len(lines)][shown], 6, axis=0)
    count = sum(len(p) for p, _ in parts) + len(ray_points)
    out = np.zeros(count, VERTEX)
    at = 0
    for points, rgba in parts:
        out["x"][at : at + len(points)] = points[:, 0]
        out["y"][at : at + len(points)] = points[:, 1]
        out["rgba"][at : at + len(points)] = premultiplied(rgba.astype(np.uint8))
        at += len(points)
    out["x"][at:], out["y"][at:] = ray_points[:, 0], ray_points[:, 1]
    if len(ray_points):
        out["rgba"][at:] = premultiplied(ray_rgba)
    return out


def painted(
    levels: NDArray[np.float32],
    progress: float,
    size: int,
    ray_colours: NDArray[np.uint8],
    track: QColor,
    done: QColor,
    ratio: float,
) -> QImage:
    """The same, painted into an image `size` pixels square at the display's pixel `ratio`, for
    Qt Quick's software renderer: the ring, its arc and the rays with round ends, as M01 draws
    them."""
    pixels = max(1, math.ceil(size * ratio))
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    k, centre = scale(size), size / 2
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    radius = RING * k
    box = QRectF(centre - radius, centre - radius, 2 * radius, 2 * radius)
    painter.setPen(QPen(track, RING_WIDTH * k))
    painter.drawEllipse(box)
    if progress > 0:
        pen = QPen(done, RING_WIDTH * k)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(box, 90 * 16, -round(max(0.0, min(1.0, progress)) * 360 * 16))
    for (x0, y0, x1, y1), (r, g, b, a) in zip(rays(levels, size), ray_colours, strict=False):
        pen = QPen(QColor(int(r), int(g), int(b), int(a)), RAY_WIDTH * k)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(float(x0), float(y0)), QPointF(float(x1), float(y1)))
    painter.end()
    return image


class Disc(CoverSpectrum):
    """The Disc's ring and rays as QML places them (`Disc` of `import MusiKata`), a square item
    centred on the cover: the spectrum of what `player` plays while `playing` and shown (as
    CoverSpectrum's), RAYS rays coloured along `colours`, and the ring's `track` with the
    `progress` (0 to 1) played in `done`."""

    progressChanged = Signal()
    lookChanged = Signal()

    BARS = RAYS

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self._progress = 0.0
        self._track, self._done = QColor("#323744"), QColor("#4ade80")
        self._disc = np.zeros(0, VERTEX)

    def _set_progress(self, progress: float) -> None:
        if progress != self._progress:
            self._progress = progress
            self.progressChanged.emit()
            self._reshape()

    def _set_track(self, colour: QColor) -> None:
        if QColor(colour) != self._track:
            self._track = QColor(colour)
            self.lookChanged.emit()
            self._reshape()

    def _set_done(self, colour: QColor) -> None:
        if QColor(colour) != self._done:
            self._done = QColor(colour)
            self.lookChanged.emit()
            self._reshape()

    progress = QtProperty(float, lambda self: self._progress, _set_progress, notify=progressChanged)
    track = QtProperty(QColor, lambda self: self._track, _set_track, notify=lookChanged)
    done = QtProperty(QColor, lambda self: self._done, _set_done, notify=lookChanged)

    def _side(self) -> float:
        return min(self.width(), self.height())

    def _ray_colours(self) -> NDArray[np.uint8]:
        count = len(self._spectrum.levels)
        if self._colours:
            return bar_colours(count, self._colours)
        return np.full((count, 4), 255, np.uint8)

    def _reshape(self) -> None:
        """The rays, ring and arc at the item's size, and their vertices."""
        if not hasattr(self, "_disc"):  # CoverSpectrum's own making, before this one's
            return
        self._disc = disc_vertices(
            self._spectrum.levels, self._progress, self._side(), self._ray_colours(),
            self._track, self._done,
        )  # fmt: skip
        self.update()

    def updatePaintNode(self, old: QSGNode | None, data: object) -> QSGNode:  # noqa: N802
        window = self.window()
        if window is None:
            return old if old is not None else QSGNode()
        if window.rendererInterface().graphicsApi() == QSGRendererInterface.GraphicsApi.Software:
            return self._image_node(old, window)
        return self._disc_node(old)

    def _disc_node(self, old: QSGNode | None) -> QSGNode:
        """One geometry node: the triangles, coloured per vertex."""
        node = old if isinstance(old, QSGGeometryNode) else None
        if node is None:
            node = QSGGeometryNode()
            geometry = QSGGeometry(attributes(), 0)
            geometry.setDrawingMode(QSGGeometry.DrawingMode.DrawTriangles)
            node.setGeometry(geometry)
            node.setFlag(QSGNode.Flag.OwnsGeometry, True)
            node.setMaterial(QSGVertexColorMaterial())
            node.setFlag(QSGNode.Flag.OwnsMaterial, True)
        fill(node, self._disc)
        return node

    def _image_node(self, old: QSGNode | None, window: QQuickWindow) -> QSGNode:
        """The software renderer's: one image node, made at the first render, showing it painted;
        each new image's texture replaces the last, which the node deletes."""
        node = old if isinstance(old, QSGImageNode) else window.createImageNode()
        side = max(1, math.ceil(self._side()))
        image = painted(self._spectrum.levels, self._progress, side, self._ray_colours(),
                        self._track, self._done, window.effectiveDevicePixelRatio())  # fmt: skip
        node.setTexture(window.createTextureFromImage(image))
        node.setOwnsTexture(True)
        node.setRect(QRectF(0, 0, side, side))
        return node

    def releaseResources(self) -> None:  # noqa: N802
        pass  # Qt deletes the node


_registered: list[bool] = []


def register() -> None:
    """Makes the item QML's `Disc` (`import MusiKata`), once a run."""
    if not _registered:
        # PySide's stub asks for the name as bytes; it takes str, and refuses bytes
        qmlRegisterType(Disc, "MusiKata", 1, 0, "Disc")  # type: ignore[call-overload]
        _registered.append(True)
