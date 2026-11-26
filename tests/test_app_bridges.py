"""The Library bridge (src/musikata/bridges.py; A1.2): the root's card, the Songs list's texts, and
the scan on a thread of its own, its progress and end reaching QML's thread as signals."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import fill

from musikata import bridges
from musikata_core import db


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def threads():
    return ThreadPoolExecutor(2)


def test_paths_under_home_are_shown_from_tilde(tmp_path):
    home = os.path.join(os.sep, "home", "ana")
    music = os.path.join(home, "Music")
    assert bridges.shown_path(music, home) == os.path.join("~", "Music")
    assert bridges.shown_path(music, home + os.sep) == os.path.join("~", "Music")
    assert bridges.shown_path(home, home) == "~"
    assert bridges.shown_path(home + "2" + os.sep + "Music", home).startswith(home + "2")
    assert bridges.shown_path(music, "") == music


def test_sizes_counts_and_the_cards_line():
    assert [bridges.size_text(n) for n in (0, 999, 3_000, 412_000_000, 9_840_000_000,
                                           123_000_000_000)] == [
        "0 bytes", "999 bytes", "3.0 KB", "412 MB", "9.8 GB", "123 GB"
    ]  # fmt: skip
    assert bridges.summary(0, 0, 0) == "No songs yet"
    assert bridges.summary(1, 1, 5_000_000) == "1 song · 1 album · 5.0 MB"
    assert bridges.summary(1412, 128, 9_840_000_000) == "1,412 songs · 128 albums · 9.8 GB"
    assert bridges.scanning_text(0, 0) == "Scanning…"
    assert bridges.scanning_text(200, 1412) == "Scanning… 200 of 1,412"


def test_albums_count_by_album_artist_or_artist_and_name_case_aside(index):
    fill(index, [
        {"path": "1", "artist": "A", "album": "X", "size": 10},
        {"path": "2", "artist": "a", "album": "x", "size": 10},     # the same album
        {"path": "3", "artist": "B", "album": "X", "size": 10},     # another's X
        {"path": "4", "artist": "C", "albumartist": "Various", "album": "Hits", "size": 10},
        {"path": "5", "artist": "D", "albumartist": "Various", "album": "Hits", "size": 10},
        {"path": "6", "artist": "E", "size": 10},                   # no album
    ])  # fmt: skip
    assert bridges.counts(index.read()) == (6, 3, 60)


def test_the_library_as_qml_reads_it(index, tmp_path):
    fill(index, [{"path": "a.flac", "size": 2_000_000}, {"path": "b.flac", "size": 1_000_000}])
    home = str(tmp_path)
    lib = bridges.Library(os.path.join(home, "Music"), index, home, threads)
    assert lib.property("root") == os.path.join("~", "Music")
    assert lib.property("line") == "2 songs · 0 albums · 3.0 MB"
    assert lib.property("countText") == "2 songs" and lib.property("emptyText") == ""
    assert lib.property("songs").rowCount() == 2 and lib.property("scanning") is False


def test_a_scan_reports_progress_then_fills_the_list_and_the_card(index, tmp_path, qtbot):
    root = tmp_path / "Music"
    root.mkdir()
    for name in ("Signal Fires.flac", "Undertow.mp3"):
        (root / name).write_bytes(b"not audio")  # read as unreadable: rows with their reason
    lib = bridges.Library(str(root), index, str(tmp_path), threads)
    assert lib.property("emptyText") == "No songs in " + os.path.join("~", "Music")
    lines = []
    lib.changed.connect(lambda: lines.append(lib.property("line")))
    with qtbot.waitSignal(lib.scanningChanged) as started:
        lib.rescan()
    assert started.signal_triggered and lib.property("scanning") is True
    assert lib.property("emptyText") == "Reading your music…"
    lib.rescan()  # one at a time: a second while one runs does nothing
    with qtbot.waitSignal(lib.scanningChanged, timeout=10_000):
        pass
    lib.wait()
    assert lib.property("scanning") is False
    assert lib.last.added == 2 and lib.last.unreadable == 2
    assert "Scanning… 2 of 2" in lines and lines[-1].startswith("2 songs · 0 albums")
    assert lib.property("songs").row(0)["title"] == "Signal Fires"


def test_a_scan_that_fails_is_kept_and_logged_and_the_library_goes_on(
    index, tmp_path, qtbot, caplog
):
    def broken():
        raise OSError("no worker processes today")

    lib = bridges.Library(str(tmp_path / "Music"), index, str(tmp_path), broken)
    with qtbot.waitSignal(lib.scanningChanged):
        lib.rescan()
    with qtbot.waitSignal(lib.scanningChanged, timeout=10_000):
        pass
    lib.wait()
    assert isinstance(lib.last, OSError) and "the scan of" in caplog.text
    assert lib.property("scanning") is False and lib.property("line") == "No songs yet"


def test_waiting_with_no_scan_started_returns_at_once(index, tmp_path):
    bridges.Library(str(tmp_path), index, str(tmp_path), threads).wait()
