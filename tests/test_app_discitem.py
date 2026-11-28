"""The mini player's Disc (src/musikata/discitem.py; R15.3, R15.5, A5.3): the spectrum's rays round
the ring, clockwise from the top, each its level's length; the ring and the arc played; their
triangles for the scene graph and their picture for the software renderer; drawn while it plays.

Why: the Disc's ring is its progress bar and its rays its spectrum; an arc that starts elsewhere
than the top, runs the wrong way or misses what has played, or rays that don't follow the music,
would each say something false about the song."""

import ctypes
import math

import numpy as np
import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView, QSGGeometryNode

from musikata import discitem
from musikata_core.audio.stream import Recent

WAIT = 5_000
SIDE = discitem.DESIGN  # the mockup's size: its lengths as they are


def test_the_rays_start_at_the_top_and_go_clockwise_each_its_levels_length():
    lines = discitem.rays(np.array([0.0, 1.0, 0.5, 0.0], np.float32), SIDE)
    centre = SIDE / 2
    x0, y0, x1, y1 = lines[0]
    assert x0 == pytest.approx(centre) and y0 == pytest.approx(centre - discitem.RAY_FROM)
    assert centre - y1 == pytest.approx(discitem.RAY_FROM + discitem.RAY_STUB)  # quiet: its stub
    x0, y0, x1, y1 = lines[1]  # a quarter of the way round, clockwise: on the right
    assert y0 == pytest.approx(centre) and x0 > centre
    assert x1 - x0 == pytest.approx(discitem.RAY_STUB + discitem.RAY_REACH)  # a full band
    assert lines[2][3] - lines[2][1] == pytest.approx(discitem.RAY_STUB + discitem.RAY_REACH / 2)
    half = discitem.rays(np.ones(4, np.float32), SIDE / 2)  # at half the size, half the lengths
    assert half[0][1] == pytest.approx(SIDE / 4 - discitem.RAY_FROM / 2)
    assert discitem.rays(np.zeros(0, np.float32), SIDE).shape == (0, 4)
    assert discitem.rays(np.ones(3, np.float32), 0).shape == (0, 4)


def test_a_line_is_two_triangles_its_width_wide_and_one_of_no_length_none():
    lines = np.array([[0, 0, 10, 0], [5, 5, 5, 5]], np.float32)
    points = discitem.thick_lines(lines, 2.0)
    assert points.shape == (6, 2)
    assert set(map(float, points[:, 1])) == {-1.0, 1.0}
    assert set(map(float, points[:, 0])) == {0.0, 10.0}
    assert discitem.thick_lines(np.zeros((0, 4), np.float32), 2).shape == (0, 2)


def test_the_ring_goes_all_round_and_the_arc_from_the_top_clockwise_as_far_as_played():
    ring = discitem.ring(SIDE)
    assert len(ring) == discitem.STEPS * 6
    radii = np.hypot(ring[:, 0] - SIDE / 2, ring[:, 1] - SIDE / 2)
    assert radii.min() == pytest.approx(discitem.RING - discitem.RING_WIDTH / 2, abs=1e-3)
    assert radii.max() == pytest.approx(discitem.RING + discitem.RING_WIDTH / 2, abs=1e-3)
    quarter = discitem.arc(SIDE, 0.25)
    assert len(quarter) == discitem.STEPS // 4 * 6
    angles = np.degrees(np.arctan2(quarter[:, 1] - SIDE / 2, quarter[:, 0] - SIDE / 2))
    assert angles.min() == pytest.approx(-90, abs=0.1) and angles.max() == pytest.approx(0, abs=0.1)
    assert len(discitem.arc(SIDE, 0)) == 0 and len(discitem.arc(SIDE, 2)) == len(ring)
    assert len(discitem.band(10, 0, 1, 0, math.pi)) == 0


def test_its_vertices_are_the_ring_the_arc_then_the_rays_each_in_its_colour():
    levels = np.array([1.0, 0.0, 0.5], np.float32)
    colours = np.array([[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 128]], np.uint8)
    track, done = QColor("#323744"), QColor("#4ade80")
    v = discitem.disc_vertices(levels, 0.5, SIDE, colours, track, done)
    ring, arc = discitem.STEPS * 6, discitem.STEPS // 2 * 6
    assert len(v) == ring + arc + 3 * 6
    assert tuple(v["rgba"][0]) == (0x32, 0x37, 0x44, 255)
    assert tuple(v["rgba"][ring]) == (0x4A, 0xDE, 0x80, 255)
    assert tuple(v["rgba"][ring + arc]) == (255, 0, 0, 255)
    assert tuple(v["rgba"][-1]) == (0, 0, 128, 128)  # premultiplied
    nothing = discitem.disc_vertices(np.zeros(0, np.float32), 0, SIDE, colours[:0], track, done)
    assert len(nothing) == ring


def test_painted_for_the_software_renderer_the_arc_shows_what_has_played():
    levels = np.zeros(discitem.RAYS, np.float32)
    colours = np.full((discitem.RAYS, 4), 255, np.uint8)
    image = discitem.painted(levels, 0.25, 212, colours, QColor("#323744"), QColor("#4ade80"), 1)
    assert image.width() == 212
    right = image.pixelColor(106 + 80, 106)  # a quarter of the way round: played
    left = image.pixelColor(106 - 80, 106)  # three quarters: not yet
    assert right.green() > 200 and left.name() == "#323744"
    assert image.pixelColor(106, 106 - 88).alpha() > 0  # the top ray
    assert image.pixelColor(106, 106).alpha() == 0  # the cover's place, left for it


# ---------- the item ----------


class Playing(QObject):
    def __init__(self):
        super().__init__()
        self.analyzer = Recent()
        self.analyzer.start(48_000, 2)


@pytest.fixture
def view(qapp, qtbot):
    discitem.register()
    v = QQuickView()
    v.setColor(QColor("#12151b"))
    v.setSource(QUrl("data:text/plain,"))
    yield v
    v.close()


def shown(view, qtbot, player):
    view.engine().rootContext().setContextProperty("thePlayer", player)
    qml = (
        "import QtQuick\nimport MusiKata\nRectangle { width: 240; height: 240; color: '#12151b'\n"
        "  property bool on: false\n"
        "  Disc { objectName: 'd'; x: 14; y: 14; width: 212; height: 212; player: thePlayer;"
        " playing: parent.on; progress: 0.25; colours: ['#22d3ee', '#a78bfa', '#f472b6'];"
        " track: '#323744'; done: '#4ade80' } }"
    )
    view.setSource(QUrl("data:text/plain," + qml))
    view.show()
    qtbot.waitExposed(view)
    return view.rootObject().findChild(discitem.Disc, "d")


def test_it_draws_its_ring_and_rays_and_plays_only_while_shown_and_playing(view, qtbot):
    player = Playing()
    item = shown(view, qtbot, player)
    assert item.property("progress") == 0.25 and len(item.property("levels")) == discitem.RAYS
    assert item.property("track") == QColor("#323744") and item.property("done") == QColor(
        "#4ade80"
    )
    image = view.grabWindow()
    assert image.pixelColor(14 + 106 + 80, 14 + 106).green() > 200  # the arc played
    assert not item.property("running") and not player.analyzer.on  # paused: nothing drawn
    view.rootObject().setProperty("on", True)
    assert item.property("running") and player.analyzer.on
    item.setProperty("progress", 0.5)
    item.setProperty("track", QColor("#000000"))
    item.setProperty("done", QColor("#ff0000"))
    image = view.grabWindow()
    assert image.pixelColor(14 + 106, 14 + 106 + 80).red() > 200  # half way: the bottom
    view.rootObject().setProperty("on", False)
    qtbot.waitUntil(lambda: not item.property("running"), timeout=WAIT)


def test_its_vertices_are_copied_into_one_geometry_node(view, qtbot):
    item = shown(view, qtbot, Playing())
    item._spectrum._levels = np.linspace(0.0, 1.0, discitem.RAYS).astype(np.float32)
    item._reshape()
    node = item._disc_node(None)  # the GPU's: one node, built directly
    assert isinstance(node, QSGGeometryNode)
    assert node.geometry().vertexCount() == len(item._disc)
    raw = ctypes.string_at(int(node.geometry().vertexData()), item._disc.nbytes)
    assert raw == item._disc.tobytes() and item._disc_node(node) is node
    item.setProperty("colours", [])  # none: white rays
    assert tuple(item._ray_colours()[0]) == (255, 255, 255, 255)
