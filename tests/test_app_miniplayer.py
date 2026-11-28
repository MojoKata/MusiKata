"""The mini player (src/musikata/miniplayer.py, MiniPlayer.qml; R15, A1.8): its layouts and their
limits, where it opens, snaps and comes back onto a screen, what it says of the song, the wheel's
volume, its menu; in the app, opening it from the bar's pop-out button, ⋮ and Ctrl+Shift+M with
the main window minimized, closing it from ×, Show MusiKata, its icon and the keys with the main
window brought back as it was and playback never stopped, each layout drawn with no QML warning and
its text in its boxes, a layout chosen, Stay on top, the place kept, the keys and the wheel, songs
dropped on it, the last song shown when none plays, and its visuals stopped when it can't be seen.

Why: the mini player is what the user leaves on screen while MusiKata is out of the way. One that
opens off every screen, loses its place or layout, stops the music, can't bring the main window
back, or draws its spectrum to nobody would each be noticed every day."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock, FakeEngine
from PySide6.QtCore import QBuffer, QEvent, QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QWheelEvent, QWindow
from PySide6.QtTest import QTest

from musikata import app, layout, miniplayer, tour
from musikata.miniplayer import LAYOUTS, MARGIN, layout_named
from musikata_core import art, scanner, settings
from musikata_core.tags import AudioInfo, Tags

WAIT = 5_000
SCREEN = (0, 0, 1920, 1040)  # a screen's area, its panel left out
SECOND = (1920, 0, 1280, 1024)  # a second screen, to its right


# ---------- the layouts (R15.3) ----------


def test_the_seven_layouts_in_r15_3s_order_at_their_default_sizes():
    assert [(lay.number, lay.title, lay.size) for lay in LAYOUTS] == [
        (1, "Strip", (496, 76)), (2, "Cover", (300, 300)), (3, "Card", (300, 582)),
        (4, "Analyzer", (496, 170)), (5, "Disc", (240, 320)), (6, "Details", (300, 240)),
        (7, "Remote", (246, 76)),
    ]  # fmt: skip
    assert [lay.name for lay in LAYOUTS] == list(settings.MINI_LAYOUTS)
    for lay in LAYOUTS:
        assert lay.least[0] <= lay.size[0] <= lay.most[0]
        assert lay.least[1] <= lay.size[1] <= lay.most[1]
    # the MusiKata icon on all but Strip and Remote; Cover's controls under the pointer (R15.4)
    assert [lay.name for lay in LAYOUTS if not lay.logo] == ["strip", "remote"]
    assert [lay.name for lay in LAYOUTS if lay.hover] == ["cover"]
    assert layout_named("nonesuch").name == "card" and layout_named("disc").number == 5


def test_a_size_is_held_within_its_layouts_limits():
    strip = layout_named("strip")
    assert miniplayer.fitted(strip, 2000, 300) == (strip.most[0], 76)
    assert miniplayer.fitted(strip, 10, 10) == (strip.least[0], 76)
    assert miniplayer.fitted(layout_named("cover"), 420, 420) == (420, 420)


def test_the_window_is_the_card_with_its_shadows_margin_around_it():
    assert miniplayer.window_of((100, 200, 300, 76)) == (
        100 - MARGIN, 200 - MARGIN, 300 + 2 * MARGIN, 76 + 2 * MARGIN
    )  # fmt: skip
    assert miniplayer.card_of(miniplayer.window_of((5, 6, 7, 8))) == (5, 6, 7, 8)


# ---------- where it goes (R15.2) ----------


def test_a_layout_with_no_place_kept_opens_in_the_primary_screens_bottom_right_corner():
    card = miniplayer.place_for(layout_named("remote"), {}, [SCREEN, SECOND])
    gap = miniplayer.GAP
    assert card == (1920 - gap - 246, 1040 - gap - 76, 246, 76)
    assert miniplayer.place_for(layout_named("remote"), {}, []) == (0, 0, 246, 76)


def test_a_kept_place_opens_where_it_was_its_size_held_within_its_limits():
    kept = {"card": (2000, 100, 330, 9000)}  # on the second screen; a hand edit's height
    assert miniplayer.place_for(layout_named("card"), kept, [SCREEN, SECOND]) == (
        2000, 100, 330, layout_named("card").most[1]
    )  # fmt: skip


@pytest.mark.parametrize(
    "card, back",
    [
        ((5000, 100, 300, 300), True),  # a screen unplugged
        ((-290, 100, 300, 300), True),  # 10 pixels show: too few to take hold of
        ((-250, 100, 300, 300), False),  # 50 show
        ((1900, 1030, 300, 76), True),  # off the bottom between the screens, a corner showing
        ((100, 1000, 300, 76), False),  # 40 pixels of its height show
        ((2500, 900, 246, 76), False),  # on the second screen
    ],
)
def test_a_place_off_every_screen_comes_back_on_the_primary_one(card, back):
    found = miniplayer.on_screen(card, [SCREEN, SECOND])
    if back:
        gap = miniplayer.GAP
        assert found == (1920 - gap - card[2], 1040 - gap - card[3], card[2], card[3])
    else:
        assert found == card
    assert miniplayer.on_screen(card, []) == card


@pytest.mark.parametrize(
    "card, snapped",
    [
        ((10, 10, 300, 76), (0, 0, 300, 76)),  # near the top left: onto both edges
        ((1920 - 300 - 12, 500, 300, 76), (1620, 500, 300, 76)),  # near the right edge
        ((500, 1040 - 76 - 16, 300, 76), (500, 964, 300, 76)),  # within 16 of the bottom
        ((500, 1040 - 76 - 17, 300, 76), (500, 947, 300, 76)),  # 17 away: left
        ((-8, 500, 300, 76), (0, 500, 300, 76)),  # a little past the left edge
        ((1930, 5, 300, 76), (1920, 0, 300, 76)),  # on the second screen, near its corner
        ((400, 400, 300, 76), (400, 400, 300, 76)),  # nowhere near an edge
    ],
)
def test_the_card_snaps_to_the_edges_of_the_screen_it_is_on(card, snapped):
    assert miniplayer.snapped(card, [SCREEN, SECOND]) == snapped
    assert miniplayer.snapped(card, []) == card


def test_the_screen_a_card_is_on_is_the_one_showing_most_of_it_else_the_nearest():
    assert miniplayer.area_of((1900, 10, 300, 76), [SCREEN, SECOND]) == SECOND  # 280 of 300
    assert miniplayer.area_of((1700, 10, 300, 76), [SCREEN, SECOND]) == SCREEN  # 220 of 300
    assert miniplayer.area_of((4000, 10, 300, 76), [SCREEN, SECOND]) == SECOND  # off both
    assert miniplayer.area_of((-900, 10, 300, 76), [SCREEN, SECOND]) == SCREEN
    assert miniplayer.area_of((1, 2, 3, 4), []) == (1, 2, 3, 4)


def test_a_layout_chosen_keeps_the_corner_nearest_its_screens_and_stays_on_it():
    gap = miniplayer.GAP
    remote = (1920 - gap - 246, 1040 - gap - 76, 246, 76)  # in the bottom right corner
    card = miniplayer.switched(remote, (300, 582), [SCREEN])
    assert card == (1920 - gap - 300, 1040 - gap - 582, 300, 582)  # it grew up and to the left
    assert miniplayer.switched((40, 30, 246, 76), (300, 582), [SCREEN]) == (40, 30, 300, 582)
    # grown past the screen's top: moved down onto it
    assert miniplayer.switched((40, 30, 246, 1000), (300, 1040), [SCREEN])[1] == 0
    assert miniplayer.switched((40, 30, 246, 76), (300, 582), []) == (40, 30, 300, 582)
    assert miniplayer.inside((-50, 2000, 10, 10), SCREEN) == (0, 1030, 10, 10)


# ---------- what it says and does (R15.3, R15.4) ----------


def test_what_it_says_of_the_song():
    assert miniplayer.song_line("Lumen Drift", "Glass Harbor") == "Lumen Drift · Glass Harbor"
    assert miniplayer.song_line("Lumen Drift", "") == "Lumen Drift"
    assert miniplayer.tooltip_text("Signal Fires", "Lumen Drift") == "Signal Fires — Lumen Drift"
    assert miniplayer.tooltip_text("Signal Fires", "") == "Signal Fires"
    assert miniplayer.kicker_text(4, 10, "Glass Harbor") == "Track 4 of 10 · Glass Harbor"
    assert miniplayer.kicker_text(4, None, "") == "Track 4"
    assert miniplayer.kicker_text(None, 10, "Glass Harbor") == "Glass Harbor"
    line = miniplayer.details_line
    assert line("Lumen Drift", 2019, ["Electronic"]) == "Lumen Drift · 2019 · Electronic"
    assert line("Lumen Drift", None, ["Soul", "Jazz"]) == "Lumen Drift · Soul, Jazz"
    assert miniplayer.up_next_words(None) == {}


def test_the_wheel_turns_the_volume_a_step_a_notch_held_from_0_to_1():
    after = miniplayer.volume_after
    assert after(0.5, 120) == pytest.approx(0.55) and after(0.5, -240) == pytest.approx(0.4)
    assert after(0.98, 360) == 1.0 and after(0.02, -120) == 0.0
    assert after(0.5, 60) == pytest.approx(0.525)  # half a notch: a touchpad's


def test_the_menu_lists_the_layouts_by_name_and_number_the_current_one_checked():
    items = miniplayer.menu_layouts("remote")
    assert [(i["title"], i["number"]) for i in items][:2] == [("Strip", 1), ("Cover", 2)]
    assert [i["name"] for i in items if i["checked"]] == ["remote"]
    assert miniplayer.shortcut_text("linux") == "Ctrl+Shift+M"
    assert miniplayer.shortcut_text("darwin") == "⇧⌘M"


def test_the_progress_line_runs_along_the_foot_inside_its_rounded_corners():
    path = miniplayer.progress_path(300, 76, 14, 3, 1.0)
    points = [tuple(float(v) for v in p.split()) for p in path[1:-1].split("L")]
    assert points[0][1] == 73 and points[1] == (points[1][0], 73)
    inset = 14 - (14**2 - 11**2) ** 0.5
    assert points[0][0] == pytest.approx(inset, abs=0.01)
    assert points[1][0] == pytest.approx(300 - inset, abs=0.01)
    assert all(0 <= x <= 300 and 73 <= y <= 76 for x, y in points)
    assert max(y for _, y in points) == 76  # the foot, between the corners
    half = miniplayer.progress_path(300, 76, 14, 3, 0.5)
    assert "150.00 73.00" in half and "150.00 76.00" in half
    assert miniplayer.progress_path(300, 76, 14, 3, 0) == ""
    assert miniplayer.progress_path(300, 76, 14, 3, 0.01) == ""  # inside the corner's curve
    assert miniplayer.progress_path(300, 76, 0, 2, 1).startswith("M0.00 74.00L300.00 74.00")


# ---------- in the app ----------


def png(colour):
    image = QImage(300, 300, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def songs(index, root):
    folder = root / "Lumen Drift" / "Glass Harbor"
    folder.mkdir(parents=True)
    (folder / "cover.png").write_bytes(png("#2255cc"))
    images = {"Lumen Drift/Glass Harbor": [art.Image("cover.png", 1, 1)]}
    rows = []
    for t in range(1, 4):
        tags = Tags(title=f"Song {t}", artist="Lumen Drift", album="Glass Harbor", track=t,
                    tracktotal=3, year=2019, genres=("Electronic",), rating=t)  # fmt: skip
        info = AudioInfo("flac", 200.0 + t, 912_000, 44_100, 2, 16)
        path = f"Lumen Drift/Glass Harbor/{t:02d}.flac"
        rows.append(scanner.Read(scanner.Seen(path, 10, 1), tags, info, path))
    index.write(lambda c: scanner.write_batch(c, rows, {}, images)).result()


@pytest.fixture
def shell(tmp_path, qapp):
    root = tmp_path / "Music"
    root.mkdir()
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(root), env, FakeClock(), lambda: ThreadPoolExecutor(1), FakeEngine)
    songs(s.index, root)
    s.library.reload()
    s.window.show()
    s.env = env
    s.music = str(root)
    s.kept = []
    s.mini._keep = lambda **f: s.kept.append(f)
    yield s
    s.close()


def items(window):
    found = []

    def walk(item):
        found.append(item)
        for child in item.childItems():
            walk(child)

    walk(window.contentItem())
    return found


def find(window, name):
    found = [i for i in items(window) if i.objectName() == name]
    picked = [i for i in found if i.isVisible()] or found
    assert len(picked) == 1, (name, found)
    return picked[0]


def click(window, item):
    at = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


def settle(window, qtbot):
    window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(window.contentItem()), timeout=WAIT)


def mini_window(shell):
    return shell.mini.window


@pytest.mark.slow
def test_the_bars_pop_out_button_opens_it_and_minimizes_the_main_window(shell, qtbot):
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    settle(shell.window, qtbot)
    button = find(shell.window, "miniPlayerButton")
    assert button.property("name") == "Mini player"
    click(shell.window, button)
    qtbot.waitUntil(lambda: mini_window(shell).isVisible(), timeout=WAIT)
    assert shell.mini.property("opened")
    assert shell.window.visibility() == QWindow.Visibility.Minimized
    # just left of the Now Playing button (R6.5)
    now = find(shell.window, "nowPlayingButton")
    gap = now.mapToScene(QPointF(0, 0)).x() - button.mapToScene(QPointF(button.width(), 0)).x()
    assert 0 <= gap <= 24
    shell.mini.close()
    assert (
        shell.window.visibility() == QWindow.Visibility.Windowed
        and not mini_window(shell).isVisible()
    )


@pytest.mark.slow
def test_the_more_menus_mini_player_and_ctrl_shift_m_open_it(shell, qtbot):
    settle(shell.window, qtbot)
    # R6.6's order: Mini player after Change history. Read from the source: the menu itself (a
    # Popup) isn't touched from Python, whose wrapper of it outlives what Qt deletes under it
    with open(os.path.join(os.path.dirname(app.QML), "ViewHeader.qml"), encoding="utf-8") as f:
        source = f.read()
    menu = source[source.index('objectName: "moreMenu"') :]
    assert 0 < menu.index('"changeHistory"') < menu.index('"miniPlayerItem"')
    item = shell.window.findChild(QObject, "miniPlayerItem")
    assert item.property("text") == "Mini player"
    item.triggered.emit()
    qtbot.waitUntil(lambda: shell.mini.property("opened"), timeout=WAIT)
    shell.mini.close()
    shell.window.requestActivate()
    qtbot.waitUntil(lambda: QGuiApplication.focusWindow() is shell.window, timeout=WAIT)
    QTest.keyClick(shell.window, Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier
                   | Qt.KeyboardModifier.ShiftModifier)  # fmt: skip
    qtbot.waitUntil(lambda: shell.mini.property("opened"), timeout=WAIT)
    window = mini_window(shell)
    window.requestActivate()
    qtbot.waitUntil(lambda: QGuiApplication.focusWindow() is window, timeout=WAIT)
    QTest.keyClick(window, Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier
                   | Qt.KeyboardModifier.ShiftModifier)  # fmt: skip
    qtbot.waitUntil(lambda: not shell.mini.property("opened"), timeout=WAIT)
    assert shell.window.visibility() == QWindow.Visibility.Windowed


@pytest.mark.slow
def test_its_x_icon_and_menu_close_it_and_bring_the_main_window_back_as_it_was(shell, qtbot):
    p = shell.player
    p.go({"queue": "Glass Harbor", "at": 1})
    p.toggle()
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    shell.window.setVisibility(QWindow.Visibility.Maximized)
    for close in ("miniClose", "miniLogo", "miniShowMain", "miniCloseEntry"):
        shell.mini.open()
        assert shell.window.visibility() == QWindow.Visibility.Minimized
        window = mini_window(shell)
        settle(window, qtbot)
        if close in ("miniClose", "miniLogo"):  # its × and its MusiKata icon
            click(window, find(window, close))
        else:  # its menu's Show MusiKata and Close mini player
            window.findChild(QObject, close).triggered.emit()
        qtbot.waitUntil(lambda: not shell.mini.property("opened"), timeout=WAIT)
        assert not window.isVisible(), close
        assert shell.window.visibility() == QWindow.Visibility.Maximized, close
        assert p.property("playing"), close  # playback never stops (R15.1)
    assert window.findChild(QObject, "miniShowMain").property("note") == "Ctrl+Shift+M"
    shell.mini.close()  # closed already: nothing
    shell.mini.toggle()
    assert shell.mini.property("opened")
    shell.mini.toggle()
    assert not shell.mini.property("opened")


@pytest.mark.slow
def test_with_minimize_off_the_main_window_stays_and_hidden_by_the_system_it_closes(shell, qtbot):
    shell.mini._minimize = False
    shell.mini.open()
    assert shell.window.visibility() == QWindow.Visibility.Windowed
    mini_window(shell).hide()  # Alt+F4, the window manager
    assert not shell.mini.property("opened")
    shell.window.showMinimized()  # minimized by the user before it opened
    shell.mini.open()
    shell.mini.close()
    assert shell.window.visibility() == QWindow.Visibility.Windowed  # brought back all the same
    shell.mini.open()
    shell.window.close()  # the main window closed from the taskbar: it goes too, so MusiKata quits
    assert not shell.mini.property("opened") and not mini_window(shell).isVisible()


@pytest.mark.slow
@pytest.mark.parametrize("name", [lay.name for lay in LAYOUTS])
def test_each_layout_loads_with_no_warning_and_its_text_in_its_boxes(shell, qtbot, qtlog, name):
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    shell.mini.go({"mini": name, "miniHover": True})
    window = mini_window(shell)
    assert shell.mini.property("layout") == name
    lay = layout_named(name)
    assert (window.width(), window.height()) == (lay.size[0] + 2 * MARGIN, lay.size[1] + 2 * MARGIN)
    settle(window, qtbot)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(window) == []
    assert find(window, "miniLayout").property("item").objectName() != ""
    titles = [i for i in items(window) if i.objectName() == "miniTitle" and i.isVisible()]
    assert [t.property("text") for t in titles] in ([], ["Song 2"])
    assert find(window, "miniPin").isVisible() and find(window, "miniClose").isVisible()
    logos = [i for i in items(window) if i.objectName() == "miniLogo" and i.isVisible()]
    assert len(logos) == (1 if lay.logo else 0)
    assert window.minimumWidth() == lay.least[0] + 2 * MARGIN
    assert window.maximumHeight() == lay.most[1] + 2 * MARGIN
    shell.mini.go({})
    assert not shell.mini.property("opened")


@pytest.mark.slow
def test_the_card_says_the_track_its_details_and_the_next_song(shell, qtbot):
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    shell.mini.go({"mini": "card"})
    words = shell.mini.property("words")
    assert words["title"] == "Song 2" and words["line"] == "Lumen Drift · Glass Harbor"
    assert words["kicker"] == "Track 2 of 3 · Glass Harbor"
    assert words["details"] == "Lumen Drift · 2019 · Electronic"
    assert words["tooltip"] == "Song 2 — Lumen Drift"
    assert shell.mini.property("upNext")["line"] == "Song 3 · Lumen Drift"
    assert shell.mini.property("upNext")["length"] == "3:23"
    window = mini_window(shell)
    settle(window, qtbot)
    assert find(window, "miniKicker").property("text") == "Track 2 of 3 · Glass Harbor"
    assert find(window, "miniRating").property("rating") == 2
    shell.player.next()
    qtbot.waitUntil(lambda: shell.mini.property("words")["title"] == "Song 3", timeout=WAIT)
    assert shell.mini.property("upNext") == {}


@pytest.mark.slow
def test_the_cards_waveform_seeks_and_its_buttons_play_shuffle_and_repeat(shell, qtbot):
    """R15.3's Card: its waveform as the seek bar (R11.2), its full controls, its stars settable."""
    p = shell.player
    p.go({"queue": "Glass Harbor", "at": 0})
    shell.mini.go({"mini": "card"})
    window = mini_window(shell)
    settle(window, qtbot)
    click(window, find(window, "miniPlayPause"))
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    seek = find(window, "miniSeek")
    qtbot.waitUntil(lambda: seek.property("enabled"), timeout=WAIT)
    click(window, seek)  # half way: the fake's 0:42
    qtbot.waitUntil(lambda: p.property("position") == pytest.approx(21.0, abs=0.3), timeout=WAIT)
    click(window, find(window, "miniShuffle"))
    qtbot.waitUntil(lambda: p.property("shuffle"), timeout=WAIT)
    click(window, find(window, "miniRepeat"))
    qtbot.waitUntil(lambda: p.property("repeat") == "all", timeout=WAIT)
    click(window, find(window, "miniNext"))
    qtbot.waitUntil(lambda: p.property("title") != "Song 1", timeout=WAIT)
    click(window, find(window, "miniPrevious"))
    assert find(window, "miniRating").property("settable")
    click(window, find(window, "miniPlayPause"))
    qtbot.waitUntil(lambda: not p.property("playing"), timeout=WAIT)


@pytest.mark.slow
def test_with_no_song_playing_it_shows_the_last_one_paused_and_play_plays_it(shell, qtbot):
    p = shell.player
    shell.mini.open()
    assert not shell.mini.property("hasSong")  # nothing played yet
    p.go({"queue": "Glass Harbor", "at": 2})
    p.toggle()
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    p.next()  # past the last song: the queue has played out
    qtbot.waitUntil(lambda: p.property("path") == "", timeout=WAIT)
    assert shell.mini.property("hasSong") and shell.mini.property("words")["title"] == "Song 3"
    assert not p.property("playing")
    shell.mini.playPause()
    qtbot.waitUntil(lambda: p.property("title") == "Song 3", timeout=WAIT)
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    shell.mini.playPause()  # a song shown: the player's play/pause
    qtbot.waitUntil(lambda: not p.property("playing"), timeout=WAIT)


@pytest.mark.slow
def test_a_layout_chosen_from_the_menu_or_its_number_is_shown_at_its_kept_size_and_kept(
    shell, qtbot
):
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    shell.mini._places["card"] = (100, 100, 320, 600)
    shell.mini.open()
    window = mini_window(shell)
    settle(window, qtbot)
    entry = window.findChild(QObject, "miniLayout_strip")
    assert entry.property("text") == "Strip"
    entry.triggered.emit()
    assert shell.mini.property("layout") == "strip"
    assert (window.width(), window.height()) == (496 + 2 * MARGIN, 76 + 2 * MARGIN)
    assert {"layout": "strip"} in shell.kept
    checked = [i["name"] for i in shell.mini.property("layouts") if i["checked"]]
    assert checked == ["strip"]
    shell.mini.setLayoutNumber(3)  # the key 3 while it has focus
    assert shell.mini.property("layout") == "card"
    assert (window.width(), window.height()) == (320 + 2 * MARGIN, 600 + 2 * MARGIN)
    shell.mini.setLayoutNumber(9)  # no such layout: nothing
    shell.mini.setLayout("card")  # the current one: nothing
    shell.mini.setLayout("nonesuch")
    assert shell.mini.property("layout") == "card"
    window.requestActivate()
    qtbot.waitUntil(lambda: QGuiApplication.focusWindow() is window, timeout=WAIT)
    QTest.keyClick(window, Qt.Key.Key_7)
    qtbot.waitUntil(lambda: shell.mini.property("layout") == "remote", timeout=WAIT)


@pytest.mark.slow
def test_stay_on_top_is_the_pin_and_the_menus_on_by_default_and_kept(shell, qtbot):
    shell.mini.open()
    window = mini_window(shell)
    settle(window, qtbot)
    assert shell.mini.property("stayOnTop")
    assert window.flags() & Qt.WindowType.WindowStaysOnTopHint
    assert window.flags() & Qt.WindowType.FramelessWindowHint
    click(window, find(window, "miniPin"))
    qtbot.waitUntil(lambda: not shell.mini.property("stayOnTop"), timeout=WAIT)
    assert not window.flags() & Qt.WindowType.WindowStaysOnTopHint
    assert shell.kept[-1] == {"stay_on_top": False}
    window.findChild(QObject, "miniStayOnTop").triggered.emit()
    assert shell.mini.property("stayOnTop") and shell.kept[-1] == {"stay_on_top": True}


@pytest.mark.slow
def test_moved_near_an_edge_it_snaps_there_and_its_place_is_kept(shell, qtbot):
    shell.mini._timer.setInterval(10)
    shell.mini.open()
    window = mini_window(shell)
    area = QGuiApplication.primaryScreen().availableGeometry()
    with qtbot.waitSignal(shell.mini.placeKept, timeout=WAIT):
        window.setPosition(QPoint(area.x() + 9 - MARGIN, area.y() + 120 - MARGIN))
    assert miniplayer.card_of((window.x(), window.y(), window.width(), window.height()))[:2] == (
        area.x(), area.y() + 120,
    )  # fmt: skip
    kept = shell.kept[-1]["places"]["card"]
    assert (kept["x"], kept["y"]) == (area.x(), area.y() + 120)
    assert shell.mini._places["card"][:2] == (area.x(), area.y() + 120)
    shell.mini.close()
    shell.mini.open()  # where it was left
    assert (window.x() + MARGIN, window.y() + MARGIN) == (area.x(), area.y() + 120)


@pytest.mark.slow
def test_its_layout_stay_on_top_and_places_are_kept_in_the_shared_settings(tmp_path, qapp, qtbot):
    root = tmp_path / "Music"
    root.mkdir()
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    path = settings.shared_path(env)
    settings.set_mini_player(path, str(tmp_path), "PC", layout="disc", stay_on_top=False,
                             places={"disc": {"x": 40, "y": 50, "w": 240, "h": 320}})  # fmt: skip
    settings.set_appearance(path, str(tmp_path), "PC", minimize_for_mini=False)
    s = app.load(str(root), env, FakeClock(), lambda: ThreadPoolExecutor(1), FakeEngine, keep=True)
    try:
        s.window.show()
        mini = s.mini
        assert mini.property("layout") == "disc" and not mini.property("stayOnTop")
        mini.open()
        assert s.window.visibility() != QWindow.Visibility.Minimized  # R13.8's setting off
        assert (mini.window.x() + MARGIN, mini.window.y() + MARGIN) == (40, 50)
        mini.setLayout("remote")
        mini.toggleStayOnTop()
        qtbot.waitUntil(
            lambda: (
                settings.load(path, str(tmp_path)).mini_player.layout == "remote"
                and settings.load(path, str(tmp_path)).mini_player.stay_on_top
            ),
            timeout=WAIT,
        )
        kept = settings.load(path, str(tmp_path)).mini_player.places
        assert kept["disc"] == (40, 50, 240, 320) and "remote" in kept
    finally:
        s.close()


@pytest.mark.slow
def test_the_wheel_changes_the_volume_and_its_keys_work_while_it_has_focus(shell, qtbot):
    p = shell.player
    p.go({"queue": "Glass Harbor", "at": 1})
    p.setVolume(0.5)
    shell.mini.go({"mini": "strip"})
    window = mini_window(shell)
    settle(window, qtbot)
    at = QPointF(window.width() / 2, window.height() / 2)
    wheel = QWheelEvent(at, window.mapToGlobal(at), QPoint(0, 0), QPoint(0, 240),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)  # fmt: skip
    QGuiApplication.sendEvent(window, wheel)
    assert p.property("volume") == pytest.approx(0.6)
    window.requestActivate()
    qtbot.waitUntil(lambda: QGuiApplication.focusWindow() is window, timeout=WAIT)
    QTest.keyClick(window, Qt.Key.Key_Space)
    qtbot.waitUntil(lambda: p.property("playing"), timeout=WAIT)
    QTest.keyClick(window, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: p.property("title") == "Song 3", timeout=WAIT)
    QTest.keyClick(window, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: p.property("title") == "Song 2", timeout=WAIT)
    QTest.keyClick(window, Qt.Key.Key_Space)
    qtbot.waitUntil(lambda: not p.property("playing"), timeout=WAIT)


@pytest.mark.slow
def test_songs_dropped_on_it_are_added_to_the_queue_to_play_next(shell, qtbot):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    from musikata import dragging as dnd
    from musikata.dragging import Carried

    p = shell.player
    p.go({"queue": "Glass Harbor", "at": 0})
    third = p.queue.order[2].song
    shell.mini.go({"mini": "remote"})
    window = mini_window(shell)
    settle(window, qtbot)
    data = QMimeData()
    data.setData(dnd.MIME, dnd.encode(Carried((third,)), shell.music).encode())
    at = QPointF(window.width() / 2, window.height() / 2)
    copy, left = Qt.DropAction.CopyAction, Qt.MouseButton.LeftButton
    enter = QDragEnterEvent(at, copy, data, left, Qt.KeyboardModifier.NoModifier)
    QGuiApplication.sendEvent(window, enter)
    assert enter.isAccepted() and shell.dragging.property("target") == "queue:1"
    QGuiApplication.sendEvent(window, QDropEvent(at, copy, data, left,
                                                 Qt.KeyboardModifier.NoModifier))  # fmt: skip
    assert [e.song for e in p.queue.upcoming][0] == third


@pytest.mark.slow
def test_its_visuals_draw_only_while_it_is_exposed_and_playing(shell, qtbot):
    p = shell.player
    p.go({"queue": "Glass Harbor", "at": 1})
    shell.mini.go({"mini": "strip"})
    window = mini_window(shell)
    settle(window, qtbot)
    qtbot.waitUntil(lambda: shell.mini.property("exposed"), timeout=WAIT)
    bars = find(window, "miniSpectrum")
    assert bars.property("bars") == 10 and not bars.property("running")  # paused
    p.toggle()
    qtbot.waitUntil(lambda: bars.property("running"), timeout=WAIT)
    window.showMinimized()
    qtbot.waitUntil(lambda: not shell.mini.property("exposed"), timeout=WAIT)
    qtbot.waitUntil(lambda: not bars.property("running"), timeout=WAIT)
    window.showNormal()
    qtbot.waitUntil(lambda: bars.property("running"), timeout=WAIT)
    shell.mini.close()  # hidden
    qtbot.waitUntil(lambda: not bars.property("running"), timeout=WAIT)
    assert p.property("playing")


def test_an_expose_event_is_followed_and_others_pass_through(qapp):
    class Bridge(QObject):  # the Player bridge's signals, and nothing playing
        changed = Signal()
        queueChanged = Signal()

    mini = miniplayer.MiniPlayer(Bridge(), areas=lambda: [SCREEN])
    window, main = QWindow(), QWindow()
    mini.attach(main, window)
    assert not mini.eventFilter(window, QEvent(QEvent.Type.Expose))
    assert not mini.eventFilter(main, QEvent(QEvent.Type.Expose))
    assert not mini.property("exposed")  # never shown
    mini.open()  # no song, nothing read: shown all the same
    assert mini.property("opened") and mini.property("words") == {}
    mini.detach()
    assert not mini.property("opened") and mini.window is None
    mini.open()  # no window: nothing
    mini.setLayout("strip")  # chosen while closed: kept, nothing placed
    assert mini.property("layout") == "strip"
