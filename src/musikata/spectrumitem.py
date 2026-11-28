"""The cover's spectrum (R11.4.3, A5.6): over the lower part of Now Playing's cover, with No
visualization, the spectrum of what is heard (A5.2, musikata_core.analysis.spectrum) as 32
translucent white bars, rising and falling with the music, 30 frames a second. The mini player
(R15.3) draws it smaller: over its Cover layout's art as it is, and as the Strip's and the
Remote's ten bars (`bars`, `pad`, `gap`, `least`), each in its colour along the gradient of the
design tokens (`colours`), a quiet one a dot.

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

from .waveitem import VERTEX, attributes, fill, gradient, premultiplied

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


def bar_rects(
    levels: NDArray[np.float32],
    width: float,
    height: float,
    pad: float = PAD,
    gap: float = GAP,
    least: float = 0.0,
) -> NDArray[np.float32]:
    """Each bar's rectangle (x, y, width, height) over an item `width` × `height`: the bars side
    by side, `pad` in from either side and `gap` apart, standing on its foot, each `levels` (0 to
    1) of its height tall, and `least` tall at least (the mini player's dots, R15.3)."""
    count = len(levels)
    if not count or width <= 2 * pad:
        return np.zeros((0, 4), np.float32)
    bar = max(1.0, (width - 2 * pad - (count - 1) * gap) / count)
    out = np.empty((count, 4), np.float32)
    out[:, 0] = pad + np.arange(count) * (bar + gap)
    out[:, 3] = np.maximum(np.clip(np.asarray(levels, np.float32), 0.0, 1.0) * height, least)
    out[:, 1] = height - out[:, 3]
    out[:, 2] = bar
    return out


def bar_colours(count: int, colours: list[QColor]) -> NDArray[np.uint8]:
    """Each of `count` bars' colour (RGBA bytes), from low to high along the gradient of
    `colours`, evenly spaced (the design tokens' cyan, violet and pink, R6.2)."""
    if not colours or not count:
        return np.zeros((count, 4), np.uint8)
    stops = [(i / max(1, len(colours) - 1), QColor(c)) for i, c in enumerate(colours)]
    return gradient(np.linspace(0.0, 1.0, count, dtype=np.float32), stops)


def bar_vertices(
    rects: NDArray[np.float32], height: float, colours: NDArray[np.uint8] | None = None
) -> NDArray[np.void]:
    """The bars as triangles, six vertices a bar, coloured white at TOP_ALPHA at the item's top
    to FOOT_ALPHA at its foot, or each its own of `colours` (RGBA rows, a bar each), premultiplied
    as the scene graph takes vertex colours; a bar of no height has none."""
    shown = rects[:, 3] > 0
    rects = rects[shown]
    count = len(rects)
    vertices = np.zeros(count * 6, VERTEX)
    if not count:
        return vertices
    x0, y0 = rects[:, 0], rects[:, 1]
    x1, y1 = x0 + rects[:, 2], y0 + rects[:, 3]
    xs = np.stack([x0, x1, x0, x1, x1, x0], axis=1).reshape(-1)
    ys = np.stack([y0, y0, y1, y0, y1, y1], axis=1).reshape(-1)
    vertices["x"], vertices["y"] = xs, ys
    if colours is not None:
        vertices["rgba"] = premultiplied(np.repeat(colours[shown], 6, axis=0))
        return vertices
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
    draws frames. `bars` (32), `pad`, `gap` and `least` shape the bars, set before it is first
    drawn; with `colours` each bar is its colour along their gradient, without them translucent
    white."""

    playerChanged = Signal()
    playingChanged = Signal()
    framed = Signal()  # a frame was drawn: `levels` moved
    runningChanged = Signal()
    shapeChanged = Signal()  # bars, pad, gap, least, colours

    BARS = spectrum.COVER_BARS  # the bars until `bars` sets them

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self.setFlag(QQuickItem.Flag.ItemHasContents, True)
        # weakly: a QML item of a Python type outlives its window as a husk (PySide keeps its
        # wrapper), which must hold nothing of the window's bridges (A1.3)
        self._player_ref: Callable[[], QObject | None] = _none
        self._playing = False
        self._running = False
        self._wanted = False
        self._spectrum = spectrum.Spectrum(spectrum.BANDS, bars=self.BARS)
        self._pad, self._gap, self._least = float(PAD), float(GAP), 0.0
        self._colours: list[QColor] = []
        self._vertices = np.zeros(0, VERTEX)
        self._rects = [QRectF() for _ in range(self.BARS)]
        self._bar_colours: list[QColor] = []
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

    def _get_bars(self) -> int:
        return len(self._rects)

    def _set_bars(self, bars: int) -> None:
        """The bars' count: the spectrum's bands gathered into that many (R15.3's ten)."""
        if bars > 0 and bars != len(self._rects):
            self._spectrum = spectrum.Spectrum(spectrum.BANDS, self._spectrum.rate, bars=bars)
            self._rects = [QRectF() for _ in range(bars)]
            self._shaped()

    def _set_pad(self, pad: float) -> None:
        if pad != self._pad:
            self._pad = pad
            self._shaped()

    def _set_gap(self, gap: float) -> None:
        if gap != self._gap:
            self._gap = gap
            self._shaped()

    def _set_least(self, least: float) -> None:
        if least != self._least:
            self._least = least
            self._shaped()

    def _set_colours(self, colours: list[object]) -> None:
        found = [QColor(c) for c in colours or []]
        if [c.rgba() for c in found] != [c.rgba() for c in self._colours]:
            self._colours = found
            self._shaped()

    def _shaped(self) -> None:
        self.shapeChanged.emit()
        self._reshape()

    player = QtProperty(QObject, _get_player, _set_player, notify=playerChanged)
    playing = QtProperty(bool, _get_playing, _set_playing, notify=playingChanged)
    levels = QtProperty(list, _get_levels, notify=framed)
    running = QtProperty(bool, _get_running, notify=runningChanged)
    bars = QtProperty(int, _get_bars, _set_bars, notify=shapeChanged)
    pad = QtProperty(float, lambda self: self._pad, _set_pad, notify=shapeChanged)
    gap = QtProperty(float, lambda self: self._gap, _set_gap, notify=shapeChanged)
    least = QtProperty(float, lambda self: self._least, _set_least, notify=shapeChanged)
    colours = QtProperty(list, lambda self: self._colours, _set_colours, notify=shapeChanged)

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
        levels = self._spectrum.levels
        rects = bar_rects(levels, self.width(), self.height(), self._pad, self._gap, self._least)
        colours = bar_colours(len(rects), self._colours) if self._colours else None
        self._vertices = bar_vertices(rects, self.height(), colours)
        # every bar a rectangle, those of no height too: the software renderer places the nodes
        # added to a node it has drawn already without the item's place, so none is added later
        self._rects = [QRectF(*(float(v) for v in r)) for r in rects] or [QRectF() for _ in levels]
        self._bar_colours = (
            [QColor(int(r), int(g), int(b), int(a)) for r, g, b, a in colours]
            if colours is not None
            else []
        )
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
        white = QColor(255, 255, 255, round(SOFTWARE_ALPHA * 255))
        tints = self._bar_colours if len(self._bar_colours) == len(self._rects) else []
        while len(self._software) < len(self._rects):
            rect = window.createRectangleNode()
            root.appendChildNode(rect)
            self._software.append(rect)
        while len(self._software) > len(self._rects):
            rect = self._software.pop()
            root.removeChildNode(rect)
            Shiboken.delete(rect)
        for i, (node, shape) in enumerate(zip(self._software, self._rects, strict=True)):
            node.setRect(shape)
            node.setColor(tints[i] if tints else white)
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
