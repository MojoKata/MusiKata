"""The 3D analyzer's Qt Quick item (R11.3 to R11.3.2, A5.2 to A5.5): the spectrum of the last few
seconds as a perspective landscape (musikata_core.analysis.landscape), fed by the analyzer's ring
(A4.3, musikata_core.audio.stream.Recent) through the spectrum's arithmetic (A5.2), at R11.3.1's
band count and speed.

It builds its geometry for the scene graph (`updatePaintNode`) rather than painting: one geometry
node, a triangle strip of every slice, back to front, each its fill in the background colour under
its line in its colour, the colours per vertex (`QSGVertexColorMaterial`, whose blending draws the
strip in order, so a nearer slice hides the ones behind it). One node, as the waveform's
(waveitem.py): a node made in Python and added under another stays Python's to delete. Qt Quick's
software renderer (offscreen, and where there is no GPU) draws no custom geometry, so there the same
slices are painted with `QPainter` into an image, shown by one image node made at the first render:
nothing is added to a node the software renderer has drawn already, which it places without the
item's place.

Each frame runs on the GUI thread, as the cover's spectrum's does (spectrumitem.py): the newest
4,096 samples heard, their levels, the landscape moved on by the frame's time and projected, then
the vertices, about half a millisecond at 128 bands over 6 seconds (measured in
tests/test_analysis_landscape.py).

R11.3.2's frame rate (`Pace`): a timer at the display's refresh rate, at most 60 a second. Each
frame's time since the last is kept; when the last WINDOW frames together took more than LATE
times what they should (at 60 a second, the last second's 60 frames over 1.25 s: fewer than 48 a
second), the computer isn't keeping up, and it drops to 30. It tries the full rate again each time
drawing starts, and after RETRY seconds at 30.

Drawing stops (R11.3.2, A5.5) when the item isn't shown (Now Playing closed, another visualization
chosen), the window is minimized, or playback is paused: the last landscape stays, and its time
stands still until frames go on. While it draws it tells the analyzer's ring it wants its samples
(`Recent.want`); otherwise the playback thread copies none for it."""

from __future__ import annotations

import math
import time
import weakref
from collections import deque
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPolygonF, QWindow
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

from musikata_core.analysis import landscape, spectrum
from musikata_core.audio.stream import Recent

from .waveitem import VERTEX, attributes, fill, premultiplied

FPS = 60  # R11.3.2: at most
SLOW_FPS = 30  # when the computer can't keep up
WINDOW = 60  # the frames whose times are looked at together
LATE = 1.25  # those frames taking this many times what they should: it can't keep up
RETRY = 30.0  # seconds at SLOW_FPS before the full rate is tried again
LONGEST = 0.1  # a frame's time counted at most, in seconds: a stall doesn't jump the landscape


def frame_rate(refresh: float) -> int:
    """The frames a second a display refreshing `refresh` times a second is drawn at (R11.3.2):
    its own rate, at most FPS; FPS when it doesn't say."""
    if not refresh or not math.isfinite(refresh) or refresh <= 0:
        return FPS
    return max(1, min(FPS, round(refresh)))


class Pace:
    """The analyzer's frame rate (R11.3.2): `full` frames a second (`frame_rate`), dropping to
    SLOW_FPS when the last WINDOW frames took more than LATE times what they should, and trying
    `full` again after RETRY seconds; a new one is made each time drawing starts. `tick` is given
    each frame's time (a clock's seconds) and says how long the frame was."""

    def __init__(self, full: int = FPS) -> None:
        self.full = full
        self.fps = full
        self._times: deque[float] = deque(maxlen=WINDOW + 1)
        self._slow_since = 0.0

    def tick(self, now: float) -> float:
        """A frame at `now`: its time since the last (one frame's at this rate when it is the
        first, LONGEST at most), the rate changed when it should be."""
        last = self._times[-1] if self._times else None
        self._times.append(now)
        seconds = 1 / self.fps if last is None else min(LONGEST, max(0.0, now - last))
        if self.fps > SLOW_FPS and len(self._times) == WINDOW + 1:
            took = self._times[-1] - self._times[0]
            if took > LATE * WINDOW / self.fps:
                self.fps = SLOW_FPS
                self._slow_since = now
                self._times.clear()
                self._times.append(now)
        elif self.fps < self.full and now - self._slow_since >= RETRY:
            self.fps = self.full
            self._times.clear()
            self._times.append(now)
        return seconds


def drawing(shown: bool, minimized: bool, playing: bool) -> bool:
    """Whether the analyzer draws frames now, and wants the device's samples (R11.3.2, A5.5):
    shown, its window not minimized, and a song playing; paused, the last landscape stays."""
    return shown and not minimized and playing


def labels() -> list[dict[str, Any]]:
    """The octave labels along the front (R11.3.1): each one's place across it (0 to 1) and its
    text."""
    return [{"at": at, "text": text} for at, text in landscape.octave_places()]


def rgb(colour: QColor) -> landscape.Rgb:
    return colour.red(), colour.green(), colour.blue()


def vertices(
    places: landscape.Places,
    depths: NDArray[np.float32],
    front: QColor,
    back: QColor,
    background: QColor,
) -> NDArray[np.void]:
    """The slices at `places` as the geometry node's vertices (VERTEX rows), coloured from
    `front` to `back` over `background` (landscape.colours)."""
    line, fill_ = landscape.colours(depths, rgb(front), rgb(back), rgb(background))
    xy, rgba = landscape.strip(places, landscape.line_widths(depths), line, fill_)
    out = np.zeros(len(xy), VERTEX)
    out["x"], out["y"] = xy[:, 0], xy[:, 1]
    out["rgba"] = premultiplied(rgba)
    return out


def painted(
    places: landscape.Places,
    depths: NDArray[np.float32],
    front: QColor,
    back: QColor,
    background: QColor,
    size: tuple[int, int],
    ratio: float,
) -> QImage:
    """The slices at `places` painted into an image of `size` (in the item's pixels) at the
    display's pixel `ratio`, for Qt Quick's software renderer: each slice's fill then its line,
    back to front, in the colours of `vertices`."""
    width, height = (max(1, math.ceil(v * ratio)) for v in size)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    line, fill_ = landscape.colours(depths, rgb(front), rgb(back), rgb(background))
    widths = landscape.line_widths(depths)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for i, points in enumerate(places.points):
        along = [QPointF(float(x), float(y)) for x, y in points]
        foot = float(places.feet[i])
        outline = QPolygonF([QPointF(along[0].x(), foot), *along, QPointF(along[-1].x(), foot)])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(*(int(v) for v in fill_[i]))))
        painter.drawPolygon(outline)
        painter.setPen(QPen(QColor(*(int(v) for v in line[i])), float(widths[i])))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(along))
    painter.end()
    return image


def generated(bands: int, seconds: float) -> landscape.Landscape:
    """A landscape of generated spectra, as the mockup N02 draws one (docs/mockups/src/render.py,
    `n02_now_3d`): a strong low hump, a softer middle and a faint high one, pulsing slice by slice,
    with a little noise. The tour shows it (A1.6): its screens are paused, so nothing is heard."""
    made = landscape.Landscape(bands, seconds)
    noise = np.random.default_rng(5)
    f = np.linspace(0.0, 1.0, bands, dtype=np.float32)
    hump = (
        np.exp(-((f - 0.12) ** 2) / 0.006) * 0.95
        + np.exp(-((f - 0.35) ** 2) / 0.01) * 0.6
        + np.exp(-((f - 0.62) ** 2) / 0.02) * 0.35
        + 0.08
    )
    for i in range(math.ceil(seconds / made.every) + 1):
        pulse = 0.65 + 0.35 * np.sin(i * 0.55 + f * 9)
        levels = hump * pulse * (0.75 + 0.25 * noise.random(bands)) * (1 - 0.15 * f)
        made.advance(np.clip(levels, 0.0, 1.0).astype(np.float32), made.every)
    return made


def _colour(name: str, notify: Signal) -> Any:
    """A colour property of the item, by its name; a change recolours the landscape."""

    def get(self: Analyzer) -> QColor:
        return self._colours[name]

    def set_(self: Analyzer, colour: QColor) -> None:
        if QColor(colour) != self._colours[name]:
            self._colours[name] = QColor(colour)
            self.lookChanged.emit()
            self._reshape()

    return QtProperty(QColor, get, set_, notify=notify)


class Analyzer(QQuickItem):
    """The 3D analyzer as QML places it (`Analyzer` of `import MusiKata`): the spectrum of what
    `player` (the Player bridge, whose `analyzer` is the analyzer's ring) plays, drawn while
    `playing` and shown, `bands` bands over the last `seconds` (R11.3.1), its slices from `front`
    to `back` over `background`. `running` is whether it draws frames, `fps` how many a second;
    `labels` are the octaves along its front, `horizon` the back slice's foot (y)."""

    playerChanged = Signal()
    playingChanged = Signal()
    shapeChanged = Signal()  # bands, seconds
    lookChanged = Signal()
    framed = Signal()  # a frame was drawn: the landscape moved
    runningChanged = Signal()
    horizonChanged = Signal()

    clock: Callable[[], float] = time.monotonic

    def __init__(self, parent: QQuickItem | None = None) -> None:
        super().__init__(parent)
        self.setFlag(QQuickItem.Flag.ItemHasContents, True)
        # weakly: a QML item of a Python type outlives its window as a husk (PySide keeps its
        # wrapper), which must hold nothing of the window's bridges (A1.3)
        self._player_ref: Callable[[], QObject | None] = _none
        self._playing = False
        self._running = False
        self._wanted = False
        self._bands, self._seconds = spectrum.BANDS, landscape.SECONDS
        self._spectrum = spectrum.Spectrum(self._bands)
        self._landscape = landscape.Landscape(self._bands, self._seconds)
        self._colours = {
            "front": QColor("#22d3ee"),
            "back": QColor("#a78bfa"),
            "background": QColor("#0e0d18"),
        }
        nothing = np.zeros(0, np.float32)
        self._places = landscape.project(np.zeros((0, self._bands), np.float32), nothing, 1, 1)
        self._depths = np.zeros(0, np.float32)
        self._vertices = np.zeros(0, VERTEX)
        self._pace = Pace()
        self._window_ref: Callable[[], QQuickWindow | None] = _none
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(round(1000 / FPS))
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

    def _get_bands(self) -> int:
        return self._bands

    def _set_bands(self, bands: int) -> None:
        if bands != self._bands and bands > 0:
            self._bands = bands
            self._spectrum = spectrum.Spectrum(bands, self._spectrum.rate or 48_000)
            self._renew()

    def _get_seconds(self) -> float:
        return self._seconds

    def _set_seconds(self, seconds: float) -> None:
        if seconds != self._seconds and seconds > 0:
            self._seconds = seconds
            self._renew()

    def _renew(self) -> None:
        """A new landscape, of the bands and seconds now: the old one's slices don't fit it."""
        self._landscape = landscape.Landscape(self._bands, self._seconds)
        self.shapeChanged.emit()
        self._reshape()

    def _get_running(self) -> bool:
        return self._running

    def _get_fps(self) -> int:
        return self._pace.fps

    def _get_horizon(self) -> float:
        return float(landscape.feet(np.ones(1, np.float32), self.height())[0])

    player = QtProperty(QObject, _get_player, _set_player, notify=playerChanged)
    playing = QtProperty(bool, _get_playing, _set_playing, notify=playingChanged)
    bands = QtProperty(int, _get_bands, _set_bands, notify=shapeChanged)
    seconds = QtProperty(float, _get_seconds, _set_seconds, notify=shapeChanged)
    front = _colour("front", lookChanged)
    back = _colour("back", lookChanged)
    background = _colour("background", lookChanged)
    running = QtProperty(bool, _get_running, notify=runningChanged)
    fps = QtProperty(int, _get_fps, notify=runningChanged)
    labels = QtProperty(list, lambda self: labels(), constant=True)
    horizon = QtProperty(float, _get_horizon, notify=horizonChanged)

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
        running = drawing(shown, minimized, self._playing)
        self._want(running and self._recent() is not None)
        if running != self._running:
            self._running = running
            if running:
                window = self._window_ref()
                screen = window.screen() if window is not None else None
                self._pace = Pace(frame_rate(screen.refreshRate() if screen is not None else 0))
                self._timer.setInterval(round(1000 / self._pace.fps))
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
        """One frame: the samples heard, their levels, the landscape moved on and projected; the
        frame rate changed when it should be (`Pace`)."""
        fps = self._pace.fps
        seconds = self._pace.tick(type(self).clock())
        if self._pace.fps != fps:
            self._timer.setInterval(round(1000 / self._pace.fps))
            self.runningChanged.emit()
        recent = self._recent()
        block = None
        if recent is not None:
            if recent.rate:
                self._spectrum.set_rate(recent.rate)
            block = recent.newest(spectrum.SIZE)
        self._landscape.advance(self._spectrum.frame(block, seconds), seconds)
        self._reshape()
        self.framed.emit()

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"landscape": True} shows a landscape of generated spectra
        (`generated`), still, as a paused one stays."""
        if step.get("landscape"):
            self._landscape = generated(self._bands, self._seconds)
            self._reshape()

    def geometryChange(self, new: QRectF | QRect, old: QRectF | QRect) -> None:  # noqa: N802
        super().geometryChange(new, old)
        if new.size() != old.size():
            self._reshape()
            self.horizonChanged.emit()

    def _reshape(self) -> None:
        """The landscape's slices placed at the item's size, and their vertices."""
        levels, self._depths = self._landscape.slices()
        self._places = landscape.project(levels, self._depths, self.width(), self.height())
        c = self._colours
        self._vertices = vertices(self._places, self._depths, c["front"], c["back"],
                                  c["background"])  # fmt: skip
        self.update()

    # ---------- the scene graph's sync (the render thread, the GUI thread waiting) ----------

    def updatePaintNode(self, old: QSGNode | None, data: object) -> QSGNode:  # noqa: N802
        window = self.window()
        if window is None:
            return old if old is not None else QSGNode()
        api = window.rendererInterface().graphicsApi()
        if api == QSGRendererInterface.GraphicsApi.Software:
            return self._image_node(old, window)
        return self._geometry_node(old)

    def _geometry_node(self, old: QSGNode | None) -> QSGNode:
        """One geometry node: the slices' triangle strip, coloured per vertex."""
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

    def _image_node(self, old: QSGNode | None, window: QQuickWindow) -> QSGNode:
        """The software renderer's: one image node, made at the first render, showing the slices
        painted (`painted`); each new image's texture replaces the last, which the node deletes."""
        node = old if isinstance(old, QSGImageNode) else window.createImageNode()
        size = (max(1, math.ceil(self.width())), max(1, math.ceil(self.height())))
        c = self._colours
        image = painted(self._places, self._depths, c["front"], c["back"], c["background"],
                        size, window.effectiveDevicePixelRatio())  # fmt: skip
        node.setTexture(window.createTextureFromImage(image))
        node.setOwnsTexture(True)
        node.setRect(QRectF(0, 0, size[0], size[1]))
        return node


def _none() -> None:
    return None


_registered: list[bool] = []


def register() -> None:
    """Makes the item QML's `Analyzer` (`import MusiKata`), once a run."""
    if not _registered:
        # PySide's stub asks for the name as bytes; it takes str, and refuses bytes
        qmlRegisterType(Analyzer, "MusiKata", 1, 0, "Analyzer")  # type: ignore[call-overload]
        _registered.append(True)
