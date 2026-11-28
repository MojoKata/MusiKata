"""The waveform's Qt Quick item (R11.1, A5.3): thin rounded bars mirrored about a centre line,
the part played in the gradient (cyan to violet to pink, over the played width, as the mockups draw
it) and the rest grey; as many bars as fit, each the largest peak of the slices under it (A5.1,
`peaks.bars`).

It builds its geometry for the scene graph (`updatePaintNode`) rather than painting, so the GPU
draws it: one triangle strip, each bar a capsule of 16 vertices joined to the next by two repeated
ones, coloured per vertex (`QSGVertexColorMaterial`), the played bars in the gradient and the rest
in grey. A5.3's two strips, one per colour, are one here: a node made in Python and added under
another stays Python's to delete (PySide's `appendChildNode` doesn't hand it over), so the only
node made is the one `updatePaintNode` returns, which Qt owns. The vertices are worked out on the
GUI thread, only when the size, the waveform or the play head's bar changes (A5.3), and copied
into the node as it syncs; the render thread runs no more Python than that copy.

Qt Quick's software renderer (offscreen, as the tests and the tour draw, and where there is no
GPU) draws no custom geometry, so there each bar is a rectangle node (`createRectangleNode`) in
its colour: the same bars, square-ended.

The arithmetic (`slots`, `capsules`, `gradient`) is plain NumPy, tested without a window."""

from __future__ import annotations

import ctypes
import math
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, QRect, QRectF, Signal
from PySide6.QtGui import QColor
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import (
    QQuickItem,
    QSGGeometry,
    QSGGeometryNode,
    QSGNode,
    QSGRectangleNode,
    QSGRendererInterface,
    QSGVertexColorMaterial,
)
from shiboken6 import Shiboken

from musikata_core.analysis import peaks as peak_pairs

SEGMENTS = 3  # steps round each quarter of a bar's rounded ends
VERTEX = np.dtype([("x", "<f4"), ("y", "<f4"), ("rgba", "u1", (4,))])  # ColoredPoint2D's layout

_attributes: list[QSGGeometry.AttributeSet] = []  # the vertex layout, which a geometry refers to
# for as long as it lives: made once, kept for the run


def attributes() -> QSGGeometry.AttributeSet:
    """The scene graph's coloured-point layout (x, y, then RGBA bytes), made at its first use."""
    if not _attributes:
        _attributes.append(QSGGeometry.defaultAttributes_ColoredPoint2D())
    return _attributes[0]


def slots(width: float, bar: float, gap: float) -> tuple[int, float]:
    """How many bars of `bar` pixels, `gap` apart, fit in `width`, and the left edge of the first,
    which centres them."""
    if width < bar or bar <= 0:
        return 0, 0.0
    count = int((width + gap) // (bar + gap))
    used = count * bar + (count - 1) * gap
    return count, (width - used) / 2


def capsules(
    lefts: NDArray[np.float32], heights: NDArray[np.float32], centre: float, bar: float
) -> NDArray[np.float32]:
    """The triangle strip of bars `bar` wide at `lefts`, each `heights` tall (at least `bar`, so
    a flat line is a row of dots) and centred on the line at `centre`: each a capsule, its ends
    rounded in `SEGMENTS` steps, joined to the next by its last vertex and the next's first
    repeated (triangles of no area). Points as rows of (x, y), `vertices_per_bar()` a bar."""
    count = len(lefts)
    if not count:
        return np.zeros((0, 2), np.float32)
    r = bar / 2
    half = np.maximum(np.asarray(heights, np.float32), bar) / 2
    angles = np.linspace(math.pi / 2, 0.0, SEGMENTS + 1)  # from an end's tip to its full width
    reach = r * np.cos(angles)  # each row's half width
    rise = r * (1 - np.sin(angles))  # each row's distance in from the end's tip
    # the rows from the top tip down: the top end's, then the bottom end's
    ys = np.concatenate(
        [(centre - half)[:, None] + rise[None, :], (centre + half)[:, None] - rise[None, ::-1]],
        axis=1,
    )
    widths = np.concatenate([reach, reach[::-1]])
    middle = (np.asarray(lefts, np.float32) + r)[:, None]
    left_side, right_side = middle - widths[None, :], middle + widths[None, :]
    rows = ys.shape[1]
    points = np.empty((count, rows * 2, 2), np.float32)
    points[:, 0::2, 0], points[:, 1::2, 0] = left_side, right_side
    points[:, 0::2, 1], points[:, 1::2, 1] = ys, ys
    joined = np.concatenate([points[:, :1], points, points[:, -1:]], axis=1)
    return joined.reshape(-1, 2)


def vertices_per_bar() -> int:
    """The strip's vertices for one bar, its two joining ones included."""
    return 4 * (SEGMENTS + 1) + 2


def gradient(at: NDArray[np.float32], stops: list[tuple[float, QColor]]) -> NDArray[np.uint8]:
    """RGBA bytes at each place `at` (0 to 1, clipped) along a gradient of `stops`, each a place
    and its colour, in order."""
    places = np.array([p for p, _ in stops], np.float32)
    channels = np.array([[c.red(), c.green(), c.blue(), c.alpha()] for _, c in stops], np.float32)
    where = np.clip(np.asarray(at, np.float32), 0.0, 1.0)
    out = np.stack([np.interp(where, places, channels[:, i]) for i in range(4)], axis=1)
    return np.round(out).astype(np.uint8)


def premultiplied(rgba: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Colours with their alpha multiplied in, as the scene graph's vertex colours are."""
    alpha = rgba[:, 3:4].astype(np.float32) / 255
    out = rgba.astype(np.float32)
    out[:, :3] *= alpha
    return np.round(out).astype(np.uint8)


def _colour(name: str, notify: Signal) -> Any:
    """A colour property of the item, by its name; a change recolours the bars."""

    def get(self: Waveform) -> QColor:
        return self._colours[name]

    def set_(self: Waveform, colour: QColor) -> None:
        if QColor(colour) != self._colours[name]:
            self._colours[name] = QColor(colour)
            self.lookChanged.emit()
            self._recolour(force=True)

    return QtProperty(QColor, get, set_, notify=notify)


class Waveform(QQuickItem):
    """The waveform as QML places it (`Waveform` of `import MusiKata`): the waveform of `source`
    (an object with a `changed` signal and `peaks`, waveforms.Waveforms), `progress` of it played,
    bars `barWidth` wide and `gap` apart, the played ones from `playedFrom` through `playedMid` to
    `playedTo`, the rest `rest`."""

    sourceChanged = Signal()
    progressChanged = Signal()
    lookChanged = Signal()
    barsChanged = Signal()

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self.setFlag(QQuickItem.Flag.ItemHasContents, True)
        self._source: QObject | None = None
        self._progress = 0.0
        self._bar, self._gap = 2.0, 1.3
        self._colours = {
            "playedFrom": QColor("#22d3ee"),
            "playedMid": QColor("#a78bfa"),
            "playedTo": QColor("#f472b6"),
            "rest": QColor("#323744"),
        }
        self._heights = np.zeros(0, np.float32)  # each bar's, 0 to 1
        self._lefts = np.zeros(0, np.float32)
        self._points = np.zeros((0, 2), np.float32)
        self._played = 0  # bars played: the play head's bar
        self._vertices = np.zeros(0, VERTEX)
        self._rects: list[tuple[QRectF, QColor]] = []
        self._software: list[QSGRectangleNode] = []  # the rectangle nodes made, while Qt has them

    # ---------- what QML sets ----------

    def _get_source(self) -> QObject | None:
        return self._source

    def _set_source(self, source: QObject | None) -> None:
        if source is self._source:
            return
        if self._source is not None and Shiboken.isValid(self._source):
            self._source.changed.disconnect(self._reshape)  # type: ignore[attr-defined]
        self._source = source
        if source is not None:
            source.changed.connect(self._reshape)  # type: ignore[attr-defined]
        self._reshape()
        self.sourceChanged.emit()

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, progress: float) -> None:
        progress = min(1.0, max(0.0, progress))
        if progress != self._progress:
            self._progress = progress
            self.progressChanged.emit()
            self._recolour(force=False)

    def _get_bar(self) -> float:
        return self._bar

    def _set_bar(self, bar: float) -> None:
        if bar != self._bar:
            self._bar = bar
            self.lookChanged.emit()
            self._reshape()

    def _get_gap(self) -> float:
        return self._gap

    def _set_gap(self, gap: float) -> None:
        if gap != self._gap:
            self._gap = gap
            self.lookChanged.emit()
            self._reshape()

    def _get_bars(self) -> int:
        return len(self._heights)

    def _get_played(self) -> int:
        return self._played

    source = QtProperty(QObject, _get_source, _set_source, notify=sourceChanged)
    progress = QtProperty(float, _get_progress, _set_progress, notify=progressChanged)
    barWidth = QtProperty(float, _get_bar, _set_bar, notify=lookChanged)
    gap = QtProperty(float, _get_gap, _set_gap, notify=lookChanged)
    playedFrom = _colour("playedFrom", lookChanged)
    playedMid = _colour("playedMid", lookChanged)
    playedTo = _colour("playedTo", lookChanged)
    rest = _colour("rest", lookChanged)
    bars = QtProperty(int, _get_bars, notify=barsChanged)  # how many are drawn
    played = QtProperty(int, _get_played, notify=progressChanged)  # how many in the gradient

    # ---------- the bars, worked out on the GUI thread ----------

    def geometryChange(self, new: QRectF | QRect, old: QRectF | QRect) -> None:  # noqa: N802
        super().geometryChange(new, old)
        if new.size() != old.size():
            self._reshape()

    def _reshape(self) -> None:
        """The bars anew: how many fit, and each one's height."""
        count, first = slots(self.width(), self._bar, self._gap)
        waveform = getattr(self._source, "peaks", None)
        if waveform is None:
            waveform = np.zeros((0, 2), np.float32)
        self._heights = peak_pairs.bars(waveform, count) * float(self.height())
        # on whole pixels, so every bar is as sharp and as wide as the next
        steps = first + np.arange(count, dtype=np.float32) * (self._bar + self._gap)
        self._lefts = np.round(steps).astype(np.float32)
        self._points = capsules(self._lefts, self._heights, self.height() / 2, self._bar)
        self.barsChanged.emit()
        self._recolour(force=True)

    def _played_bars(self) -> int:
        """Bars whose middle the play head has passed."""
        head = self._progress * self.width()
        return int(np.count_nonzero(self._lefts + self._bar / 2 < head))

    def _recolour(self, force: bool) -> None:
        """The bars' colours, when the play head moved to another bar (or `force`)."""
        played = self._played_bars()
        if played == self._played and not force:
            return
        self._played = played
        self.progressChanged.emit()
        width = max(1e-6, self._progress * self.width())
        stops = [
            (0.0, self._colours["playedFrom"]),
            (0.6, self._colours["playedMid"]),
            (1.0, self._colours["playedTo"]),
        ]
        rest = self._colours["rest"]
        rest_rgba = np.array([rest.red(), rest.green(), rest.blue(), rest.alpha()], np.uint8)
        per = vertices_per_bar()
        vertices = np.zeros(len(self._points), VERTEX)
        vertices["x"], vertices["y"] = self._points[:, 0], self._points[:, 1]
        rgba = np.repeat(rest_rgba[None, :], len(self._points), axis=0)
        if played:
            lit = played * per
            rgba[:lit] = gradient(self._points[:lit, 0] / width, stops)
        vertices["rgba"] = premultiplied(rgba)
        self._vertices = vertices
        middles = self._lefts + self._bar / 2
        shades = gradient(middles / width, stops)
        tall = np.maximum(self._heights, self._bar)
        self._rects = [
            (
                QRectF(float(left), float(self.height() - h) / 2, self._bar, float(h)),
                QColor(*(int(v) for v in shades[i])) if i < played else QColor(rest),
            )
            for i, (left, h) in enumerate(zip(self._lefts, tall, strict=True))
        ]
        self.update()

    # ---------- the scene graph's sync (the render thread, the GUI thread waiting) ----------

    def updatePaintNode(self, old: QSGNode | None, data: object) -> QSGNode:  # noqa: N802
        window = self.window()
        if window is None:  # not shown: nothing to draw
            return old if old is not None else QSGNode()
        software = (
            window.rendererInterface().graphicsApi() == QSGRendererInterface.GraphicsApi.Software
        )
        if software:
            return self._software_node(old)
        return self._strip_node(old)

    def _strip_node(self, old: QSGNode | None) -> QSGNode:
        """One geometry node: the bars' triangle strip, coloured per vertex."""
        node = old if isinstance(old, QSGGeometryNode) else None
        if node is None:
            node = QSGGeometryNode()
            geometry = QSGGeometry(attributes(), 0)
            geometry.setDrawingMode(QSGGeometry.DrawingMode.DrawTriangleStrip)
            node.setGeometry(geometry)
            node.setFlag(QSGNode.Flag.OwnsGeometry, True)
            node.setMaterial(QSGVertexColorMaterial())
            node.setFlag(QSGNode.Flag.OwnsMaterial, True)
        fill(node, self._vertices)
        return node

    def _software_node(self, old: QSGNode | None) -> QSGNode:
        """A node holding a rectangle node per bar (the software renderer's)."""
        window = self.window()
        root = old
        if root is None:
            root = QSGNode()
            self._software = []  # what was made before went with the old node
        while len(self._software) < len(self._rects):
            rect = window.createRectangleNode()
            root.appendChildNode(rect)
            self._software.append(rect)
        while len(self._software) > len(self._rects):
            rect = self._software.pop()
            root.removeChildNode(rect)
            Shiboken.delete(rect)
        for node, (shape, colour) in zip(self._software, self._rects, strict=True):
            node.setRect(shape)
            node.setColor(colour)
        return root

    def releaseResources(self) -> None:  # noqa: N802
        self._software = []  # Qt deletes the nodes


def fill(node: QSGGeometryNode, vertices: NDArray[np.void]) -> None:
    """The node's geometry made `vertices` (VERTEX rows) and marked to be uploaded."""
    geometry = node.geometry()
    geometry.allocate(len(vertices))
    if len(vertices):
        data = np.ascontiguousarray(vertices)
        ctypes.memmove(int(geometry.vertexData()), data.ctypes.data, data.nbytes)
    node.markDirty(QSGNode.DirtyStateBit.DirtyGeometry)


_registered: list[bool] = []


def register() -> None:
    """Makes the item QML's `Waveform` (`import MusiKata`), once a run."""
    if not _registered:
        # PySide's stub asks for the name as bytes; it takes str, and refuses bytes
        qmlRegisterType(Waveform, "MusiKata", 1, 0, "Waveform")  # type: ignore[call-overload]
        _registered.append(True)
