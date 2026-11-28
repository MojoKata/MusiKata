"""The cover's spectrum (R11.4.3, A5.6): over the lower part of Now Playing's cover, with No
visualization, the spectrum of what is heard (A5.2, musikata_core.analysis.spectrum) as 32
translucent white bars, rising and falling with the music, 30 frames a second.

It builds its geometry for the scene graph (`updatePaintNode`) rather than painting: one geometry
node, each bar two triangles whose vertices fade from a faint white at the top to a stronger one at
the foot (`bar_vertices`), as the mockup draws it. One node, as the waveform's (waveitem.py): a node
made in Python and added under another stays Python's to delete. Qt Quick's software renderer
(offscreen, and where there is no GPU) draws no custom geometry, so there each bar is a rectangle
node in one translucent white.

Each frame runs on the GUI thread, at frame time, as A5.2 has it: the newest 4,096 samples the
device has played, from the analyzer's ring (A4.3, musikata_core.audio.stream.Recent), through the
spectrum's arithmetic, then the bars' vertices. All of it is well under a millisecond (A5.2's
promise, measured in tests/test_analysis_spectrum.py), so a thread handing frames over would only
add a queue and a frame's delay; and the vertices are worked out where the item lives, as the
waveform's are, the render thread copying them as it syncs.

Drawing stops (R11.3.2, A5.5) when the item isn't shown (Now Playing closed, another visualization
chosen), the window is minimized, or nothing plays: paused, the bars settle to nothing at the
spectrum's fall rate (R11.4.3), then the timer stops. While the item draws and a song plays it
tells the analyzer's ring it wants its samples (`Recent.want`); otherwise the playback thread
copies none. When to draw and when to want samples are plain functions (`drawing`, `wanting`)."""

from __future__ import annotations

import weakref
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, QRect, QRectF, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QWindow
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import (
    QQuickItem,
    QQuickWindow,
    QSGGeometry,
    QSGGeometryNode,
    QSGNode,
    QSGRectangleNode,
    QSGRendererInterface,
    QSGVertexColorMaterial,
)
from shiboken6 import Shiboken

from musikata_core.analysis import spectrum
from musikata_core.audio.stream import Recent

from .waveitem import VERTEX, attributes, fill, premultiplied

FPS = 30  # A5.6: plenty for bars this size
FRAME = 1 / FPS
PAD = 14  # the bars' inset from the cover's sides, at the mockup's 340-pixel cover
GAP = 3
TOP_ALPHA, FOOT_ALPHA = 0.16, 0.42  # the bars' white, faint at the top and stronger at the foot
SOFTWARE_ALPHA = 0.3  # the software renderer's one shade of it


def drawing(shown: bool, minimized: bool, playing: bool, settled: bool) -> bool:
    """Whether the cover's spectrum draws frames now (R11.3.2, A5.5): shown, its window not
    minimized, and a song playing, or paused with bars still settling (R11.4.3)."""
    return shown and not minimized and (playing or not settled)


def wanting(shown: bool, minimized: bool, playing: bool) -> bool:
    """Whether it wants the device's samples copied into the analyzer's ring (A5.5): only while
    it draws a song playing."""
    return shown and not minimized and playing


def bar_rects(levels: NDArray[np.float32], width: float, height: float) -> NDArray[np.float32]:
    """Each bar's rectangle (x, y, width, height) over an item `width` × `height`: the bars side
    by side, PAD in from either side and GAP apart, standing on its foot, each `levels` (0 to 1)
    of its height tall."""
    count = len(levels)
    if not count or width <= 2 * PAD:
        return np.zeros((0, 4), np.float32)
    bar = max(1.0, (width - 2 * PAD - (count - 1) * GAP) / count)
    out = np.empty((count, 4), np.float32)
    out[:, 0] = PAD + np.arange(count) * (bar + GAP)
    out[:, 3] = np.clip(np.asarray(levels, np.float32), 0.0, 1.0) * height
    out[:, 1] = height - out[:, 3]
    out[:, 2] = bar
    return out


def bar_vertices(rects: NDArray[np.float32], height: float) -> NDArray[np.void]:
    """The bars as triangles, six vertices a bar, coloured white at TOP_ALPHA at the item's top
    to FOOT_ALPHA at its foot (premultiplied, as the scene graph takes vertex colours); a bar of
    no height has none."""
    rects = rects[rects[:, 3] > 0]
    count = len(rects)
    vertices = np.zeros(count * 6, VERTEX)
    if not count:
        return vertices
    x0, y0 = rects[:, 0], rects[:, 1]
    x1, y1 = x0 + rects[:, 2], y0 + rects[:, 3]
    xs = np.stack([x0, x1, x0, x1, x1, x0], axis=1).reshape(-1)
    ys = np.stack([y0, y0, y1, y0, y1, y1], axis=1).reshape(-1)
    vertices["x"], vertices["y"] = xs, ys
    share = np.clip(ys / max(height, 1e-6), 0.0, 1.0)
    alpha = np.round((TOP_ALPHA + (FOOT_ALPHA - TOP_ALPHA) * share) * 255).astype(np.uint8)
    rgba = np.empty((len(xs), 4), np.uint8)
    rgba[:, :3], rgba[:, 3] = 255, alpha
    vertices["rgba"] = premultiplied(rgba)
    return vertices


class CoverSpectrum(QQuickItem):
    """The cover's spectrum as QML places it (`CoverSpectrum` of `import MusiKata`): the spectrum
    of what `player` (the Player bridge, whose `analyzer` is the analyzer's ring) plays, drawn
    while `playing` and shown; `levels` are the bars' heights now (0 to 1), `running` whether it
    draws frames."""

    playerChanged = Signal()
    playingChanged = Signal()
    framed = Signal()  # a frame was drawn: `levels` moved
    runningChanged = Signal()

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self.setFlag(QQuickItem.Flag.ItemHasContents, True)
        # weakly: a QML item of a Python type outlives its window as a husk (PySide keeps its
        # wrapper), which must hold nothing of the window's bridges (A1.3)
        self._player_ref: Callable[[], QObject | None] = _none
        self._playing = False
        self._running = False
        self._wanted = False
        self._spectrum = spectrum.Spectrum(spectrum.BANDS, bars=spectrum.COVER_BARS)
        self._vertices = np.zeros(0, VERTEX)
        self._rects = [QRectF() for _ in range(spectrum.COVER_BARS)]
        self._software: list[QSGRectangleNode] = []
        self._window_ref: Callable[[], QQuickWindow | None] = _none
        self._timer = QTimer(self)
        self._timer.setInterval(round(FRAME * 1000))
        self._timer.timeout.connect(self._frame)
        self.visibleChanged.connect(self._update)
        self.windowChanged.connect(self._on_window)

    # ---------- what QML sets ----------

    def _get_player(self) -> QObject | None:
        return self._player_ref()

    def _set_player(self, player: QObject | None) -> None:
        if player is not self._player_ref():
            self._want(False)
            self._player_ref = weakref.ref(player) if player is not None else _none
            self.playerChanged.emit()
            self._update()

    def _get_playing(self) -> bool:
        return self._playing

    def _set_playing(self, playing: bool) -> None:
        if playing != self._playing:
            self._playing = playing
            self.playingChanged.emit()
            self._update()

    def _get_levels(self) -> list[float]:
        return [float(v) for v in self._spectrum.levels]

    def _get_running(self) -> bool:
        return self._running

    player = QtProperty(QObject, _get_player, _set_player, notify=playerChanged)
    playing = QtProperty(bool, _get_playing, _set_playing, notify=playingChanged)
    levels = QtProperty(list, _get_levels, notify=framed)
    running = QtProperty(bool, _get_running, notify=runningChanged)

    # ---------- when it draws (R11.3.2, A5.5) ----------

    def _recent(self) -> Recent | None:
        player = self._player_ref()
        found = getattr(player, "analyzer", None) if player is not None else None
        return found if isinstance(found, Recent) else None

    @Slot(QQuickWindow)
    def _on_window(self, window: QQuickWindow | None) -> None:
        """The item's window: watched for being minimized. Qt lets go of the connection when
        either goes (an item never moves to another window of MusiKata's)."""
        if window is not None and window is not self._window_ref():
            window.visibilityChanged.connect(self._update)
        self._window_ref = weakref.ref(window) if window is not None else _none
        self._update()

    def _state(self) -> tuple[bool, bool]:
        """Whether it is shown, and whether its window is minimized."""
        window = self._window_ref()
        shown = self.isVisible() and window is not None and window.isVisible()
        minimized = window is not None and window.visibility() == QWindow.Visibility.Minimized
        return shown, minimized

    @Slot()
    def _update(self) -> None:
        """The timer and the ring's copying started or stopped as the rules say."""
        shown, minimized = self._state()
        self._want(wanting(shown, minimized, self._playing) and self._recent() is not None)
        running = drawing(shown, minimized, self._playing, self._spectrum.settled)
        if running != self._running:
            self._running = running
            if running:
                self._timer.start()
            else:
                self._timer.stop()
            self.runningChanged.emit()

    def _want(self, wanted: bool) -> None:
        recent = self._recent()
        if recent is not None and wanted != self._wanted:
            recent.want(id(self), wanted)  # by its id: the ring holds nothing of the item
        self._wanted = wanted and recent is not None

    # ---------- a frame ----------

    @Slot()
    def _frame(self) -> None:
        """One frame: the samples heard, the levels, the bars' vertices; then whether to go on."""
        recent = self._recent()
        block = None
        if recent is not None and self._playing:
            if recent.rate:
                self._spectrum.set_rate(recent.rate)
            block = recent.newest(spectrum.SIZE)
        self._spectrum.frame(block, FRAME)
        self._reshape()
        self.framed.emit()
        if not self._playing and self._spectrum.settled:
            self._update()

    def geometryChange(self, new: QRectF | QRect, old: QRectF | QRect) -> None:  # noqa: N802
        super().geometryChange(new, old)
        if new.size() != old.size():
            self._reshape()

    def _reshape(self) -> None:
        rects = bar_rects(self._spectrum.levels, self.width(), self.height())
        self._vertices = bar_vertices(rects, self.height())
        # every bar a rectangle, those of no height too: the software renderer places the nodes
        # added to a node it has drawn already without the item's place, so none is added later
        self._rects = [QRectF(*(float(v) for v in r)) for r in rects]
        self.update()

    # ---------- the scene graph's sync (the render thread, the GUI thread waiting) ----------

    def updatePaintNode(self, old: QSGNode | None, data: object) -> QSGNode:  # noqa: N802
        window = self.window()
        if window is None:
            return old if old is not None else QSGNode()
        api = window.rendererInterface().graphicsApi()
        if api == QSGRendererInterface.GraphicsApi.Software:
            return self._software_node(old)
        return self._geometry_node(old)

    def _geometry_node(self, old: QSGNode | None) -> QSGNode:
        """One geometry node: the bars' triangles, coloured per vertex."""
        node = old if isinstance(old, QSGGeometryNode) else None
        if node is None:
            node = QSGGeometryNode()
            geometry = QSGGeometry(attributes(), 0)
            geometry.setDrawingMode(QSGGeometry.DrawingMode.DrawTriangles)
            node.setGeometry(geometry)
            node.setFlag(QSGNode.Flag.OwnsGeometry, True)
            node.setMaterial(QSGVertexColorMaterial())
            node.setFlag(QSGNode.Flag.OwnsMaterial, True)
        fill(node, self._vertices)
        return node

    def _software_node(self, old: QSGNode | None) -> QSGNode:
        """A node holding a rectangle node per bar (the software renderer's), made with it."""
        window = self.window()
        root = old
        if root is None:
            root = QSGNode()
            self._software = []
        colour = QColor(255, 255, 255, round(SOFTWARE_ALPHA * 255))
        while len(self._software) < len(self._rects):
            rect = window.createRectangleNode()
            root.appendChildNode(rect)
            self._software.append(rect)
        while len(self._software) > len(self._rects):
            rect = self._software.pop()
            root.removeChildNode(rect)
            Shiboken.delete(rect)
        for node, shape in zip(self._software, self._rects, strict=True):
            node.setRect(shape)
            node.setColor(colour)
        return root

    def releaseResources(self) -> None:  # noqa: N802
        self._software = []  # Qt deletes the nodes


def _none() -> None:
    return None


_registered: list[bool] = []


def register() -> None:
    """Makes the item QML's `CoverSpectrum` (`import MusiKata`), once a run."""
    if not _registered:
        # PySide's stub asks for the name as bytes; it takes str, and refuses bytes
        qmlRegisterType(CoverSpectrum, "MusiKata", 1, 0, "CoverSpectrum")  # type: ignore[call-overload]
        _registered.append(True)
