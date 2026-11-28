"""The tour (src/musikata/tour.py; A1.6): every screen saved at the mockups' size and checked at
both sizes, after the scan ends, and what runs past its box failing it; a run takes the screens of
the state it started in: the library, the first start (X01) or a root that isn't there (X02)."""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock, fill
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickItem

from musikata import app, tour
from musikata.miniplayer import MARGIN


@pytest.fixture
def shell(tmp_path):
    root = tmp_path / "Music"
    root.mkdir()
    s = app.load(str(root), {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)},
                 FakeClock(), lambda: ThreadPoolExecutor(1))  # fmt: skip
    yield s
    s.close()


def run(shell, out, qtbot, only="", start=None, mini=None):
    codes = []
    t = tour.Tour(shell.window, shell.library, str(out), only, codes.append, mini=mini)
    (start or t.start)()
    qtbot.waitUntil(lambda: bool(codes), timeout=20_000)
    return t, codes[0]


def test_the_tour_saves_each_screen_and_passes_when_nothing_runs_past_its_box(
    shell, tmp_path, qtbot
):
    fill(shell.index, [{"path": "a.flac", "title": "Signal Fires", "artist": "Lumen Drift"}])
    shell.library.songs.reload()
    t, code = run(shell, tmp_path / "tour", qtbot)
    assert code == 0 and t.faults == []
    assert [os.path.basename(p) for p in t.saved] == [f"{n}.png" for n in tour.screens("library")]
    assert os.path.getsize(t.saved[0]) > 1000
    assert (tmp_path / "tour" / "layout.txt").read_text() == ""
    assert (shell.window.width(), shell.window.height()) == tour.DESIGN


@pytest.mark.slow
def test_the_mini_players_screens_are_its_own_window_and_its_menu_on_a_desktop(
    shell, tmp_path, qtbot
):
    """M01, M02 (R15): taken of the mini player's window at its layout's size, the menu's window
    beside it, and their texts checked against their boxes too."""
    fill(shell.index, [{"path": "a.flac", "title": "Signal Fires", "artist": "Lumen Drift"}])
    t, code = run(shell, tmp_path / "tour", qtbot, only="M01-mini-1-strip,M02-mini-player-menu",
                  mini=shell.mini)  # fmt: skip
    assert code == 0 and t.faults == []
    strip, menu = (QImage(p) for p in t.saved)
    room = 2 * tour.ROOM
    assert (strip.width(), strip.height()) == (496 + 2 * MARGIN + room, 76 + 2 * MARGIN + room)
    assert strip.pixelColor(2, 2) == tour.DESKTOP
    assert menu.height() > 246 + room  # the Remote, with its menu over it
    assert tour.desktop([]).isNull()


def test_it_waits_for_the_scan_and_fails_on_a_text_past_its_box(shell, tmp_path, qtbot):
    card = shell.window.findChild(QQuickItem, "rootCard")
    c = QQmlComponent(shell.engine)
    c.setData(b'import QtQuick\nText { text: "a root whose name runs out of its card" }', QUrl())
    text = c.create()
    text.setParentItem(card)
    (tmp_path / "Music" / "Undertow.flac").write_bytes(b"not audio")
    with qtbot.waitSignal(shell.library.scanningChanged):
        shell.library.rescan()  # the scan adds its row (unreadable) before the shot
    t, code = run(shell, tmp_path / "tour", qtbot, only="L03-songs")
    assert code == 1
    assert any("runs past rootCard" in f for f in t.faults)
    assert shell.library.property("songs").total() == 1  # its search aside
    written = (tmp_path / "tour" / "layout.txt").read_text()
    assert "L03-songs at 1280 x 800" in written and "L03-songs at 1920 x 1040" in written


def test_a_failed_scan_fails_the_tour(shell, tmp_path, qtbot):
    shell.library.last = OSError("no worker processes today")
    t, code = run(shell, tmp_path / "tour", qtbot)
    assert code == 1 and t.faults[-1].startswith("the scan failed")


def test_only_names_screens_that_exist(shell, tmp_path):
    with pytest.raises(ValueError, match="no such screen: Z99"):
        tour.Tour(shell.window, shell.library, str(tmp_path), "L03-songs,Z99")


def test_a_screen_whose_covers_never_load_is_taken_anyway_and_fails(
    shell, tmp_path, qtbot, monkeypatch
):
    monkeypatch.setattr(tour, "loading", lambda item: True)
    monkeypatch.setattr(tour, "PATIENCE", 60)
    t, code = run(shell, tmp_path / "tour", qtbot, only="L01-albums")
    assert code == 1 and t.faults == [
        "L01-albums: covers still loading after 0 s", "L01-albums: covers still loading after 0 s"
    ]  # fmt: skip
    assert [os.path.basename(p) for p in t.saved] == ["L01-albums.png"]


def test_what_is_loading_is_what_a_visible_item_says(shell):
    root = shell.window.contentItem()
    assert tour.loading(root) is False
    root.setProperty("loading", True)
    assert tour.loading(root) is True
    root.setVisible(False)
    assert tour.loading(root) is False
    root.setVisible(True)


def test_each_screen_is_of_one_state_and_a_run_takes_those_of_its_own():
    states = {step.get("state", "library") for _, step in tour.STEPS}
    assert states == {"library", "first-run", "unavailable"}
    assert tour.screens("first-run") == ["X01-first-run"]
    assert tour.screens("unavailable") == ["X02-root-unavailable"]
    assert tour.state_of(None) == "first-run"


def test_a_first_start_tours_its_window_alone(tmp_path, qtbot, qapp):
    first = app.first_start({"HOME": str(tmp_path), "MUSIKATA_DATA": str(tmp_path / "d")})
    codes = []
    t = tour.Tour(first.window, None, str(tmp_path / "tour"), "", codes.append)
    t.start()
    qtbot.waitUntil(lambda: bool(codes), timeout=20_000)
    assert codes == [0] and t.faults == []
    assert [os.path.basename(p) for p in t.saved] == ["X01-first-run.png"]
    first.close()


def test_a_root_that_isnt_there_tours_its_library_as_it_was(tmp_path, qtbot, qapp):
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    root = tmp_path / "Music"
    root.mkdir()
    s = app.load(str(root), env, FakeClock(), lambda: ThreadPoolExecutor(1))
    fill(s.index, [{"path": "a.flac", "title": "Signal Fires", "album": "Glass Harbor"}])
    s.close()
    shutil.rmtree(root)  # its drive unplugged (R2.10)
    s = app.load(str(root), env, FakeClock(), lambda: ThreadPoolExecutor(1), given=True)
    assert not root.exists() and s.library.property("available") is False
    t, code = run(s, tmp_path / "tour", qtbot, only="X02-root-unavailable,L01-albums")
    assert code == 0 and [os.path.basename(p) for p in t.saved] == ["X02-root-unavailable.png"]
    assert s.library.property("albumCountText") == "1 album"
    s.close()
