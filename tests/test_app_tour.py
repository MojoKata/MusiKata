"""The tour (src/musikata/tour.py; A1.6): every screen saved at the mockups' size and checked at
both sizes, after the scan ends, and what runs past its box failing it."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock, fill
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickItem

from musikata import app, tour


@pytest.fixture
def shell(tmp_path):
    root = tmp_path / "Music"
    root.mkdir()
    s = app.load(str(root), {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)},
                 FakeClock(), lambda: ThreadPoolExecutor(1))  # fmt: skip
    yield s
    s.close()


def run(shell, out, qtbot, only="", start=None):
    codes = []
    t = tour.Tour(shell.window, shell.library, str(out), only, codes.append)
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
    assert [os.path.basename(p) for p in t.saved] == [f"{n}.png" for n, _ in tour.STEPS]
    assert os.path.getsize(t.saved[0]) > 1000
    assert (tmp_path / "tour" / "layout.txt").read_text() == ""
    assert (shell.window.width(), shell.window.height()) == tour.DESIGN


def test_it_waits_for_the_scan_and_fails_on_a_text_past_its_box(shell, tmp_path, qtbot):
    card = shell.window.findChild(QQuickItem, "rootCard")
    c = QQmlComponent(shell.engine)
    c.setData(b'import QtQuick\nText { text: "a root whose name runs out of its card" }', QUrl())
    text = c.create()
    text.setParentItem(card)
    fill(shell.index, [{"path": "a.flac", "title": "Signal Fires"}])
    with qtbot.waitSignal(shell.library.scanningChanged):
        shell.library.rescan()  # an empty root: the scan removes the row before the shot
    t, code = run(shell, tmp_path / "tour", qtbot, only="L03-songs")
    assert code == 1
    assert any("runs past rootCard" in f for f in t.faults)
    assert shell.library.property("songs").rowCount() == 0
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
