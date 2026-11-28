"""The waveform's Qt Quick item and the now-playing bar's seek bar (src/musikata/waveitem.py,
NowPlayingBar.qml; R11.1, R11.2, A5.3): the bars that fit and their capsules, the gradient, the
vertices copied into a scene-graph node; the item in a window, its bars following the play head;
and the bar's waveform in the app, the time under the pointer.

The arithmetic is plain NumPy, tested without a window; the item is drawn offscreen, where Qt Quick
renders in software and the item gives rectangle nodes, and its geometry node is built and read
back directly, as the GPU's renderers would take it.

Why: the seek bar is where the user looks to find a place in a song; bars that miss the play head,
a gradient on the wrong side of it, or vertices out of the layout the scene graph reads draw a
waveform that misleads, or none."""

import ctypes
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from fakes import FakeClock, FakeEngine, fill
from PySide6.QtCore import QObject, QPointF, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView, QSGGeometryNode
from PySide6.QtTest import QTest

from musikata import app, waveitem
from musikata_core.analysis import peaks

WAIT = 5_000


# ---------- the arithmetic ----------


def test_as_many_bars_fit_as_their_width_and_gaps_allow_centred():
    assert waveitem.slots(460, 2, 1.3) == (139, pytest.approx(1.3))
    assert waveitem.slots(2, 2, 1.3) == (1, 0.0)
    assert waveitem.slots(1, 2, 1.3) == (0, 0.0) and waveitem.slots(100, 0, 1) == (0, 0.0)


def test_each_bar_is_a_capsule_mirrored_about_the_centre_line():
    points = waveitem.capsules(np.array([10.0, 20.0], np.float32), np.array([8.0, 0.0]), 5.0, 2.0)
    per = waveitem.vertices_per_bar()
    assert points.shape == (2 * per, 2) and per == 18
    bar = points[1 : per - 1]  # without its joining vertices
    assert bar[:, 0].min() == 10.0 and bar[:, 0].max() == 12.0
    assert bar[:, 1].min() == pytest.approx(1.0) and bar[:, 1].max() == pytest.approx(9.0)
    assert np.allclose(bar[:, 1] - 5.0, -(bar[::-1, 1] - 5.0), atol=1e-5)  # mirrored
    assert tuple(bar[0]) == tuple(bar[1]) == (11.0, 1.0)  # a rounded tip
    flat = points[per + 1 : 2 * per - 1]  # a flat line: a dot as wide as the bar
    assert flat[:, 1].min() == pytest.approx(4.0) and flat[:, 1].max() == pytest.approx(6.0)
    assert tuple(points[per - 1]) == tuple(points[per - 2])  # joined: repeated
    assert tuple(points[per]) == tuple(points[per + 1])
    assert waveitem.capsules(np.zeros(0, np.float32), np.zeros(0), 5, 2).shape == (0, 2)


def test_the_gradient_runs_from_cyan_through_violet_to_pink():
    stops = [(0.0, QColor("#22d3ee")), (0.6, QColor("#a78bfa")), (1.0, QColor("#f472b6"))]
    got = waveitem.gradient(np.array([-1.0, 0.0, 0.6, 1.0, 2.0, 0.3]), stops)
    assert got[:5].tolist() == [
        [0x22, 0xD3, 0xEE, 255], [0x22, 0xD3, 0xEE, 255], [0xA7, 0x8B, 0xFA, 255],
        [0xF4, 0x72, 0xB6, 255], [0xF4, 0x72, 0xB6, 255],
    ]  # fmt: skip
    assert got[5].tolist() == [100, 175, 244, 255]  # half way from cyan to violet


def test_vertex_colours_have_their_alpha_multiplied_in():
    got = waveitem.premultiplied(np.array([[200, 100, 50, 128], [10, 20, 30, 255]], np.uint8))
    assert got.tolist() == [[100, 50, 25, 128], [10, 20, 30, 255]]


def test_the_vertices_are_copied_into_the_geometry_node_as_the_scene_graph_reads_them(qapp):
    item = waveitem.Waveform()
    vertices = np.zeros(3, waveitem.VERTEX)
    vertices["x"], vertices["y"] = [1.5, 2.5, 3.5], [4.0, 5.0, 6.0]
    vertices["rgba"] = [[1, 2, 3, 255], [4, 5, 6, 255], [7, 8, 9, 255]]
    item._vertices = vertices
    node = item._strip_node(None)
    assert isinstance(node, QSGGeometryNode)
    geometry = node.geometry()
    assert geometry.vertexCount() == 3 and geometry.sizeOfVertex() == vertices.itemsize == 12
    raw = ctypes.string_at(int(geometry.vertexData()), vertices.nbytes)
    assert raw == vertices.tobytes()
    item._vertices = vertices[:1]
    assert item._strip_node(node) is node and node.geometry().vertexCount() == 1


# ---------- the item in a window ----------


class Source(QObject):
    changed = Signal()

    def __init__(self, peaks_):
        super().__init__()
        self.peaks = peaks_


@pytest.fixture
def view(qapp, qtbot):
    waveitem.register()
    v = QQuickView()
    v.setColor(QColor("#0b0d11"))
    v.setSource(QUrl("data:text/plain,"))  # a window with nothing in it yet
    yield v
    v.close()


def shown(view, qtbot, source, progress):
    level = np.linspace(0.1, 1.0, peaks.N, dtype=np.float32)
    source.peaks = np.stack([level, -level], axis=1)
    view.engine().rootContext().setContextProperty("waves", source)
    qml = (
        "import QtQuick\nimport MusiKata\nRectangle { width: 340; height: 40; color: '#0b0d11'\n"
        f"  property real p: {progress}\n"
        "  Waveform { objectName: 'w'; x: 10; y: 10; width: 320; height: 20; source: waves;"
        " progress: parent.p; rest: '#323744' } }"
    )
    view.setSource(QUrl("data:text/plain," + qml))
    view.show()
    qtbot.waitExposed(view)
    return view.rootObject().findChild(waveitem.Waveform, "w")


def test_the_bars_follow_the_play_head_and_draw_in_their_colours(view, qtbot):
    source = Source(np.zeros((0, 2), np.float32))
    item = shown(view, qtbot, source, 0.5)
    count = item.property("bars")
    assert count == waveitem.slots(320, 2, 1.3)[0]
    assert item.property("played") == count // 2 or item.property("played") == count // 2 + 1
    image = view.grabWindow()
    assert len(item._software) == count  # the software renderer's rectangles
    played = QColor(image.pixel(12, 20))
    last = int(10 + item._lefts[-1] + 1)
    rest = QColor(image.pixel(last, 20))
    assert played.blue() > 200 and played.green() > 150  # cyan, at the start
    assert rest.name() == "#323744"
    view.rootObject().setProperty("p", 1.0)
    qtbot.waitUntil(lambda: item.property("played") == count, timeout=WAIT)
    image = view.grabWindow()
    assert QColor(image.pixel(last, 20)).red() > 200  # pink, at the end
    view.rootObject().setProperty("p", 0.0)
    qtbot.waitUntil(lambda: item.property("played") == 0, timeout=WAIT)


def test_the_bars_are_drawn_anew_when_the_waveform_or_the_size_changes(view, qtbot):
    source = Source(np.zeros((0, 2), np.float32))
    item = shown(view, qtbot, source, 0.0)
    before = item._heights.copy()
    assert before.max() == pytest.approx(20.0) and before[0] < before[-1]
    source.peaks = np.full((peaks.N, 2), 0.0, np.float32)  # flat: worked out anew
    source.changed.emit()
    assert not item._heights.any()
    item.setWidth(100)
    assert item.property("bars") == waveitem.slots(100, 2, 1.3)[0]
    view.grabWindow()
    assert len(item._software) == item.property("bars")  # the extra rectangles let go
    item.setProperty("barWidth", 3.0)
    item.setProperty("gap", 2.0)
    item.setProperty("playedFrom", QColor("red"))
    assert item.property("bars") == waveitem.slots(100, 3, 2)[0]
    assert item.property("playedFrom") == QColor("red")
    item.setProperty("source", None)  # none: nothing to draw from
    assert not item._heights.any()


def test_bars_more_than_the_first_render_had_are_drawn_in_the_items_place(view, qtbot):
    """Qt Quick's software renderer places a node added under one it has drawn already without
    the item's place: the wider waveform's bars all made anew, in a new node, land where the item
    is, none above it or left of it."""
    source = Source(np.zeros((0, 2), np.float32))
    item = shown(view, qtbot, source, 0.0)  # at x 10, y 10, 320 wide
    item.setWidth(100)
    view.grabWindow()  # drawn with the few bars 100 pixels hold
    item.setWidth(320)
    image = view.grabWindow()
    assert len(item._software) == item.property("bars")
    lit = [x for x in range(340) if QColor(image.pixel(x, 20)).lightness() > 40]
    assert lit[0] >= 10 and lit[-1] > 300  # the bars across the item, from its left edge
    above = [x for x in range(340) if QColor(image.pixel(x, 5)).lightness() > 40]
    assert above == []  # none drawn at the window's top, as if the item were there


# ---------- the bar's seek bar in the app ----------

SONGS = [{"path": "LD/GH/01.flac", "title": "Tidewater", "album": "Glass Harbor", "length": 200.0}]


@pytest.fixture
def shell(tmp_path, qapp):
    root = tmp_path / "Music"
    root.mkdir()
    engines = []

    def playback():
        engines.append(FakeEngine())
        return engines[-1]

    s = app.load(str(root), {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)},
                 FakeClock(), lambda: ThreadPoolExecutor(1), playback)  # fmt: skip
    fill(s.index, SONGS)
    s.library.reload()
    s.window.show()
    yield s
    s.close()


def find(shell, name):
    def walk(item):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            got = walk(child)
            if got is not None:
                return got
        return None

    return walk(shell.window.contentItem())


@pytest.mark.slow
def test_the_seek_bar_is_the_songs_waveform_and_shows_the_time_under_the_pointer(shell, qtbot):
    p = shell.player
    p.go({"queue": "Glass Harbor"})
    qtbot.waitExposed(shell.window)
    seek, hover = find(shell, "seekBar"), find(shell, "hoverTime")
    wave = find(shell, "waveform")
    assert wave.property("source") is shell.waveforms
    # its file isn't there: a flat line, once the decoding has failed
    qtbot.waitUntil(lambda: seek.property("loading") is False, timeout=WAIT)
    assert wave.property("bars") > 100 and not wave._heights.any()
    assert p.timeAt(0.25) == "0:50"  # cued: a quarter of its 3:20 in the index
    p.toggle()
    qtbot.waitUntil(lambda: seek.property("enabled"), timeout=WAIT)
    at = seek.mapToScene(QPointF(seek.width() / 4, seek.height() / 2)).toPoint()
    QTest.mouseMove(shell.window, at)
    qtbot.waitUntil(lambda: hover.property("visible"), timeout=WAIT)
    assert hover.childItems()[0].property("text") == "0:10"  # a quarter of the fake's 0:42
    assert p.timeAt(2.0) == "0:42" and p.timeAt(-1) == "0:00"
    QTest.mouseMove(shell.window, seek.mapToScene(QPointF(0, -40)).toPoint())
    qtbot.waitUntil(lambda: not hover.property("visible"), timeout=WAIT)
