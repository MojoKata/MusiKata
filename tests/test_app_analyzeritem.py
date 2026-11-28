"""The 3D analyzer's item (src/musikata/analyzeritem.py; R11.3 to R11.3.2, A5.3, A5.5): its frame
rate, at the display's up to 60 and down to 30 when frames come late; when it draws and wants the
device's samples; the landscape as the geometry node's vertices and, for the software renderer,
painted; and the item in a window, drawing the tone heard, stopping when paused with the last
landscape kept, and stopping when hidden.

The arithmetic is plain, tested without a window; the item is drawn offscreen, where Qt Quick
renders in software and the item gives an image node, and its geometry node is built and read back
directly, as the GPU's renderers would take it.

Why: the analyzer is the one view that draws 60 times a second; one that never stops when nothing
shows it, or never drops its rate on a slow computer, costs the battery and the rest of the app
for nothing (R11.3.2), and one that loses its landscape when paused shows nothing to look at."""

import ctypes

import numpy as np
import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView, QSGGeometryNode

from musikata import analyzeritem
from musikata_core.analysis import landscape, spectrum
from musikata_core.audio.stream import Recent

WAIT = 5_000
GROUND = QColor("#0e0d18")


# ---------- the frame rate (R11.3.2) ----------


@pytest.mark.parametrize(
    "refresh, fps",
    [(60.0, 60), (59.94, 60), (144.0, 60), (50.0, 50), (0.0, 60), (float("nan"), 60)],
)
def test_it_draws_at_the_displays_refresh_rate_up_to_60(refresh, fps):
    assert analyzeritem.frame_rate(refresh) == fps


def test_frames_on_time_keep_60_and_each_frames_time_is_given():
    pace = analyzeritem.Pace()
    assert pace.tick(10.0) == pytest.approx(1 / 60)  # the first: a frame's at this rate
    now = 10.0
    for _ in range(300):  # five seconds on time, a little ragged
        now += 1 / 60 + 0.002
        assert pace.tick(now) == pytest.approx(1 / 60 + 0.002)
    assert pace.fps == 60


def test_a_second_of_late_frames_drops_it_to_30_and_60_is_tried_again_after_a_while():
    pace = analyzeritem.Pace()
    now = 0.0
    for _ in range(analyzeritem.WINDOW):
        now += 1 / 40  # the computer can't keep up: 40 a second
        pace.tick(now)
    assert pace.fps == 60  # not yet a whole window of them
    now += 1 / 40
    pace.tick(now)
    assert pace.fps == analyzeritem.SLOW_FPS
    slowed = now
    while now < slowed + analyzeritem.RETRY - 0.1:
        now += 1 / 30
        pace.tick(now)
        assert pace.fps == 30
    now += 0.2
    pace.tick(now)
    assert pace.fps == 60  # tried again


def test_a_stall_counts_as_a_tenth_of_a_second_at_most():
    pace = analyzeritem.Pace(50)
    pace.tick(1.0)
    assert pace.tick(4.0) == analyzeritem.LONGEST
    assert pace.tick(3.0) == 0.0  # a clock that went back: no time
    assert pace.fps == 50


@pytest.mark.parametrize(
    "shown, minimized, playing, draws",
    [
        (True, False, True, True),
        (True, False, False, False),  # paused: the last landscape stays
        (False, False, True, False),  # Now Playing hidden, or another visualization
        (True, True, True, False),  # the window minimized
    ],
)
def test_it_draws_and_wants_samples_only_while_shown_and_playing(shown, minimized, playing, draws):
    assert analyzeritem.drawing(shown, minimized, playing) is draws


def test_the_labels_are_the_octaves_along_the_front():
    labels = analyzeritem.labels()
    assert [label["text"] for label in labels][::5] == ["32 Hz", "16 kHz"]
    assert labels[0]["at"] == 0.0


# ---------- the landscape drawn ----------


def places_of(levels, depths, width=200.0, height=100.0):
    return landscape.project(np.asarray(levels, np.float32), np.asarray(depths, np.float32),
                             width, height)  # fmt: skip


def test_the_vertices_are_the_strip_in_its_colours_premultiplied():
    depths = np.array([1.0, 0.0], np.float32)
    places = places_of(np.full((2, 4), 0.5), depths)
    v = analyzeritem.vertices(places, depths, QColor("#22d3ee"), QColor("#a78bfa"), GROUND)
    assert len(v) == 2 * landscape.vertices_per_slice(4)
    xy, rgba = landscape.strip(places, landscape.line_widths(depths), *landscape.colours(depths))
    assert v["x"].tolist() == xy[:, 0].tolist() and v["y"].tolist() == xy[:, 1].tolist()
    assert v["rgba"].tolist() == rgba.tolist()  # opaque: premultiplied is as it was


def test_painted_the_front_hides_the_back_its_fill_under_its_line():
    depths = np.array([1.0, 0.0], np.float32)
    levels = [[1.0] * 8, [0.5] * 8]
    places = places_of(levels, depths)
    front, back = QColor("#22d3ee"), QColor("#a78bfa")
    image = analyzeritem.painted(places, depths, front, back, GROUND, (200, 100), 1.0)
    assert (image.width(), image.height()) == (200, 100)
    line, fill = landscape.colours(depths, (0x22, 0xD3, 0xEE), (0xA7, 0x8B, 0xFA), (14, 13, 24))
    foot, top = places.feet[1], places.points[1, 0, 1]  # the front: 100 down to ...
    inside = QColor(image.pixel(100, int((foot + top) / 2)))
    assert [inside.red(), inside.green(), inside.blue()] == fill[1, :3].tolist()  # front's fill
    on_line = max(QColor(image.pixel(100, y)).green() for y in range(int(top) - 1, int(top) + 2))
    assert on_line > 180  # its line, cyan
    assert image.pixelColor(10, 2).alpha() == 0  # beside the back slice, high up: nothing
    back_top = places.points[0, 0, 1]  # the back slice rises above the front's line
    assert image.pixelColor(100, int(back_top) + 1).alpha() == 255
    retina = analyzeritem.painted(places, depths, front, back, GROUND, (200, 100), 2.0)
    assert (retina.width(), retina.height(), retina.devicePixelRatio()) == (400, 200, 2.0)


def test_the_tours_landscape_is_generated_the_same_each_time_and_not_flat():
    one = analyzeritem.generated(96, 3.0)
    levels, depths = one.slices()
    assert len(depths) >= 3.0 / landscape.SLICE and depths[0] == pytest.approx(1.0)
    assert levels.max() > 0.6 and levels.min() >= 0.0
    low, high = levels[:, :20].mean(), levels[:, -20:].mean()
    assert low > 2 * high  # the low hump the mockup draws
    again = analyzeritem.generated(96, 3.0).slices()[0]
    assert np.array_equal(levels, again)


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
    analyzeritem.register()
    v = QQuickView()
    v.setColor(QColor("#0b0d11"))
    v.setSource(QUrl("data:text/plain,"))
    yield v
    v.close()


def shown(view, qtbot, player):
    view.engine().rootContext().setContextProperty("thePlayer", player)
    qml = (
        "import QtQuick\nimport MusiKata\nRectangle { width: 420; height: 240; color: '#0e0d18'\n"
        "  property bool on: false\n"
        "  Analyzer { objectName: 'a'; x: 10; y: 20; width: 400; height: 200;"
        " player: thePlayer; playing: parent.on; bands: 48; seconds: 1.5 } }"
    )
    view.setSource(QUrl("data:text/plain," + qml))
    view.show()
    qtbot.waitExposed(view)
    return view.rootObject().findChild(analyzeritem.Analyzer, "a")


def band_of(hz, bands):
    edges = spectrum.band_edges(bands, 48_000)
    return int(np.searchsorted(edges, int(hz * 4096 / 48_000), side="right") - 1)


@pytest.mark.slow
def test_playing_it_draws_the_tone_heard_and_paused_it_stops_its_landscape_kept(view, qtbot):
    player = Playing()
    item = shown(view, qtbot, player)
    assert item.property("bands") == 48 and item.property("seconds") == 1.5
    assert not item.property("running") and not player.analyzer.on  # paused: nothing copied
    view.rootObject().setProperty("on", True)
    assert item.property("running") and player.analyzer.on and item.property("fps") == 60
    player.sound()
    loud = band_of(1_000, 48)

    def risen():
        return item._landscape.front[loud] > 0.8

    qtbot.waitUntil(risen, timeout=WAIT)
    assert item._landscape.front[: loud - 4].max() < 0.3  # far below it, low
    qtbot.waitUntil(lambda: len(item._landscape.slices()[1]) > 2, timeout=WAIT)  # receding
    image = view.grabWindow()
    # the front's peak, in the item's place: its line at the tone's band, above its foot
    places = item._places
    x, y = places.points[-1, loud]
    assert image.pixelColor(int(10 + x), int(20 + y) + 3) != QColor("#0e0d18")
    view.rootObject().setProperty("on", False)  # paused
    assert not item.property("running") and not player.analyzer.on
    kept = item._vertices.copy()
    with qtbot.assertNotEmitted(item.framed, wait=100):  # still: no frame comes
        pass
    assert np.array_equal(item._vertices, kept)  # the last landscape stays
    view.rootObject().setProperty("on", True)  # on again, from where it stood
    with qtbot.waitSignal(item.framed, timeout=WAIT):
        pass
    view.rootObject().setProperty("on", False)


def test_hidden_it_neither_draws_nor_wants_samples_and_a_new_player_is_wanted_instead(view, qtbot):
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
    assert not other.analyzer.on and item.property("running")
    with qtbot.waitSignal(item.framed, timeout=WAIT):  # no ring: silence, the front flat
        pass
    assert not item._landscape.front.any()
    item.setVisible(False)


def test_bands_and_seconds_make_a_new_landscape_and_its_vertices_reach_the_geometry_node(
    view, qtbot
):
    item = shown(view, qtbot, Playing())
    with qtbot.waitSignal(item.shapeChanged):
        item.setProperty("bands", 128)
    assert item._landscape.bands == 128 and item._spectrum.count == 128
    item.setProperty("seconds", 6.0)
    assert item._landscape.seconds == 6.0
    item.setProperty("bands", 0)  # none: kept as it was
    assert item.property("bands") == 128
    item.go({"landscape": True})  # the tour's (A1.6)
    levels, depths = item._landscape.slices()
    assert levels.shape[1] == 128 and levels.max() > 0.6
    item.go({})  # another step: left as it is
    assert np.array_equal(item._landscape.slices()[0], levels)
    item.setProperty("front", QColor("red"))
    assert item.property("front") == QColor("red")
    assert item.property("horizon") == pytest.approx(landscape.HORIZON * 200)
    assert len(item.property("labels")) == len(landscape.OCTAVES)
    image = view.grabWindow()  # offscreen: the software renderer's image of it
    assert image.pixelColor(15, 25) == QColor("#0e0d18")  # the item's corner: nothing drawn
    assert image.pixelColor(10 + 200, 20 + 198) != QColor("#0e0d18")  # the front's fill
    node = item._geometry_node(None)  # the GPU's: one node, built directly
    assert isinstance(node, QSGGeometryNode)
    geometry = node.geometry()
    assert geometry.vertexCount() == len(depths) * landscape.vertices_per_slice(128)
    raw = ctypes.string_at(int(geometry.vertexData()), item._vertices.nbytes)
    assert raw == item._vertices.tobytes()
    assert item._geometry_node(node) is node
