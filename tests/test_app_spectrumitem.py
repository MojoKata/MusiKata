"""The cover's spectrum (src/musikata/spectrumitem.py; R11.4.3, A5.5, A5.6): 32 translucent white
bars over Now Playing's cover, drawn from the analyzer's ring 30 times a second while a song plays;
paused, settling to nothing, then still; hidden or minimized, not drawn, and the playback thread
copying no samples for it.

The arithmetic (where the bars stand, their vertices) is plain NumPy, tested without a window; the
item is drawn offscreen, where Qt Quick renders in software and the item gives rectangle nodes, and
its geometry node is built and read back directly, as the GPU's renderers would take it.

Why: the spectrum is the only thing on Now Playing that moves with the music; bars that never
settle when paused, or a spectrum still worked out while nothing shows it (R11.3.2), cost the
battery for nothing, and bars out of their place over the cover show what isn't heard."""

import ctypes

import numpy as np
import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView, QSGGeometryNode

from musikata import spectrumitem
from musikata_core.analysis import spectrum
from musikata_core.audio.stream import Recent

WAIT = 5_000


@pytest.mark.parametrize(
    "shown, minimized, playing, settled, draws",
    [
        (True, False, True, False, True),
        (True, False, True, True, True),  # playing silence: frames go on
        (True, False, False, False, True),  # paused: the bars settle
        (True, False, False, True, False),  # settled: still
        (False, False, True, False, False),  # Now Playing hidden, or another visualization
        (True, True, True, False, False),  # the window minimized
    ],
)
def test_it_draws_while_shown_and_playing_or_settling_and_never_minimized(
    shown, minimized, playing, settled, draws
):
    assert spectrumitem.drawing(shown, minimized, playing, settled) is draws
    assert spectrumitem.wanting(shown, minimized, playing) is (shown and not minimized and playing)


def test_the_bars_stand_side_by_side_on_the_foot_each_its_share_of_the_height():
    rects = spectrumitem.bar_rects(np.array([0.0, 0.5, 1.0, 2.0], np.float32), 120, 50)
    gap, pad = spectrumitem.GAP, spectrumitem.PAD
    bar = (120 - 2 * pad - 3 * gap) / 4
    assert rects[:, 0].tolist() == pytest.approx([pad + i * (bar + gap) for i in range(4)])
    assert rects[:, 2].tolist() == pytest.approx([bar] * 4)
    assert rects[:, 3].tolist() == [0.0, 25.0, 50.0, 50.0]  # clipped to the height
    assert (rects[:, 1] + rects[:, 3]).tolist() == [50.0] * 4  # on the foot
    assert spectrumitem.bar_rects(np.ones(4, np.float32), 20, 50).shape == (0, 4)  # too narrow
    assert spectrumitem.bar_rects(np.zeros(0, np.float32), 120, 50).shape == (0, 4)


def test_each_bar_is_two_triangles_fading_from_faint_at_the_top_to_stronger_at_the_foot():
    rects = spectrumitem.bar_rects(np.array([0.0, 1.0], np.float32), 100, 40)
    v = spectrumitem.bar_vertices(rects, 40)
    assert len(v) == 6  # the bar of no height has none
    x0, x1 = rects[1, 0], rects[1, 0] + rects[1, 2]
    assert sorted(set(v["x"].tolist())) == pytest.approx([x0, x1])
    assert sorted(set(v["y"].tolist())) == [0.0, 40.0]
    top = v[v["y"] == 0.0]["rgba"][0].tolist()
    foot = v[v["y"] == 40.0]["rgba"][0].tolist()
    assert top[3] == round(spectrumitem.TOP_ALPHA * 255) and top[0] == top[3]  # premultiplied
    assert foot[3] == round(spectrumitem.FOOT_ALPHA * 255)


# ---------- the item in a window ----------


class Playing(QObject):
    """The Player bridge as the item sees it: its analyzer's ring, holding a tone heard."""

    def __init__(self, hz=1_000.0):
        super().__init__()
        self.analyzer = Recent()
        self.analyzer.start(48_000, 2)
        self.hz = hz

    def sound(self):
        """A tenth of a second more heard, if the ring is wanted (as the device's copies are)."""
        recent = self.analyzer
        start = recent._end
        t = (start + np.arange(4_800)) / 48_000
        wave = (0.5 * np.sin(2 * np.pi * self.hz * t)).astype(np.float32)
        recent.add(np.stack([wave, wave], axis=1), start)
        recent.hear(start + 4_800)


@pytest.fixture
def view(qapp, qtbot):
    spectrumitem.register()
    v = QQuickView()
    v.setColor(QColor("#0b0d11"))
    v.setSource(QUrl("data:text/plain,"))
    yield v
    v.close()


def shown(view, qtbot, player):
    view.engine().rootContext().setContextProperty("thePlayer", player)
    qml = (
        "import QtQuick\nimport MusiKata\nRectangle { width: 360; height: 160; color: '#204060'\n"
        "  property bool on: false\n"
        "  CoverSpectrum { objectName: 's'; x: 10; y: 10; width: 340; height: 140;"
        " player: thePlayer; playing: parent.on } }"
    )
    view.setSource(QUrl("data:text/plain," + qml))
    view.show()
    qtbot.waitExposed(view)
    return view.rootObject().findChild(spectrumitem.CoverSpectrum, "s")


def test_playing_it_draws_the_tone_heard_and_paused_it_settles_then_stops(view, qtbot):
    player = Playing()
    item = shown(view, qtbot, player)
    assert item.property("player") is player and not item.property("running")
    assert not player.analyzer.on  # nothing draws: nothing copied (A5.5)
    view.rootObject().setProperty("on", True)
    assert item.property("playing") and item.property("running") and player.analyzer.on
    player.sound()
    edges = spectrum.band_edges(spectrum.BANDS, 48_000)
    band = int(np.searchsorted(edges, int(1_000 * 4096 / 48_000), side="right") - 1)
    loud = band // 3

    def risen():
        levels = item.property("levels")
        return len(levels) == 32 and levels[loud] > 0.8

    qtbot.waitUntil(risen, timeout=WAIT)
    assert max(item.property("levels")[: loud - 4]) < 0.3  # far below it, low
    image = view.grabWindow()
    assert len(item._software) == 32  # a rectangle a bar, those of no height empty
    tallest = max(item._rects, key=lambda r: r.height())
    x = int(10 + tallest.x() + 1)
    assert image.pixelColor(x, 150 - 2) != QColor("#204060")  # a bar over the cover, translucent
    view.rootObject().setProperty("on", False)  # paused
    assert not player.analyzer.on and item.property("running")  # settling
    qtbot.waitUntil(lambda: not item.property("running"), timeout=WAIT)
    assert not any(item.property("levels"))
    view.grabWindow()
    assert all(node.rect().height() == 0 for node in item._software)  # nothing left standing


def test_hidden_it_neither_draws_nor_wants_samples(view, qtbot):
    player = Playing()
    item = shown(view, qtbot, player)
    view.rootObject().setProperty("on", True)
    assert item.property("running")
    item.setVisible(False)  # Now Playing closed, or another visualization chosen
    assert not item.property("running") and not player.analyzer.on
    item.setVisible(True)
    assert item.property("running") and player.analyzer.on
    other = Playing()
    item.setProperty("player", other)  # another player: the first one's ring let go
    assert not player.analyzer.on and other.analyzer.on
    item.setProperty("player", None)
    assert not other.analyzer.on and item.property("running")  # silence: it settles
    item.setProperty("player", None)


def test_the_spectrums_vertices_are_copied_into_its_geometry_node_as_the_scene_graph_reads_them(
    view, qtbot
):
    item = shown(view, qtbot, Playing())
    item._spectrum._levels = np.linspace(0.1, 1.0, 32).astype(np.float32)
    item._reshape()
    view.grabWindow()
    assert len(item._software) == 32  # offscreen: the software renderer's rectangles
    node = item._geometry_node(None)  # the GPU's: one node, built directly
    assert isinstance(node, QSGGeometryNode)
    geometry = node.geometry()
    assert geometry.vertexCount() == 32 * 6
    raw = ctypes.string_at(int(geometry.vertexData()), item._vertices.nbytes)
    assert raw == item._vertices.tobytes()
    assert item._geometry_node(node) is node
