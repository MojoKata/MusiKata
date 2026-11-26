"""Watching the root (src/musikata_core/watch.py; A2.4, R2.4): changes gathered for a second
before their rescan, files still being written looked at again, MusiKata's own writes recognised by
path and time, and the watcher over QFileSystemWatcher, which stops and says why when the system
refuses a folder.

Why: a rescan for every change reported would scan an album copied in once per file; one that
never looked again at a file still being written would keep it half read; one that read
MusiKata's own writes would read every file it saves twice. A watcher that went on after the
system refused it a folder would miss every change in it without a word."""

import logging
import os
from datetime import timedelta

import pytest
from fakes import FakeClock

from musikata_core import scanner, watch


def test_changes_are_gathered_for_a_second_from_the_first_then_due_together():
    clock = FakeClock()
    g = watch.Gatherer(clock)
    assert g.due_in() is None and g.take() == frozenset()
    g.changed("A")
    assert g.due_in() == 1.0
    clock.advance(seconds=0.6)
    g.changed("B")  # joins the gathering: not a second of its own
    g.changed("A")
    assert g.due_in() == pytest.approx(0.4) and g.take() == frozenset()
    clock.advance(seconds=0.4)
    assert g.due_in() == 0.0 and g.take() == {"A", "B"}
    assert g.due_in() is None  # a new gathering starts with the next change
    g.changed("")
    clock.advance(seconds=5)
    assert g.take() == {""}
    g.changed("C")
    g.clear()
    assert g.due_in() is None


def test_a_file_read_while_it_may_still_be_written_has_its_folder_looked_at_again():
    """A folder's watch doesn't report a file written in place (Linux), so a copy still being
    written when its rescan reads it is read again once its modification time settles."""
    clock = FakeClock()
    g = watch.Gatherer(clock)
    now = int(clock.now().timestamp() * 1e9)

    def seen(path, ago):
        return scanner.Seen(path, 1, now - int(ago * 1e9))

    g.scanned([seen("A/1.flac", 0.5), seen("B/2.flac", 3), seen("3.flac", 1.9),
               seen("C/4.flac", -1000), seen("D/5.flac", -0.2)])  # fmt: skip
    clock.advance(seconds=1)
    assert g.take() == {"A", "", "D"}
    g.scanned([seen("A/1.flac", 2.5)])  # settled
    assert g.due_in() is None


def test_a_write_musikata_made_is_expected_by_its_path_size_and_time_for_a_while():
    clock = FakeClock()
    own = watch.OwnWrites(clock)
    assert own.expected() == {}
    own.wrote("A/1.flac", 10, 111)
    clock.advance(seconds=20)
    own.wrote("A/2.flac", 20, 222)
    own.wrote("A/1.flac", 11, 112)  # written again: the newest counts
    assert own.expected() == {"A/1.flac": (11, 112), "A/2.flac": (20, 222)}
    clock.advance(seconds=watch.OWN)
    assert own.expected() == {}


def test_why_watching_stopped_names_linuxs_limit_where_it_has_one(tmp_path):
    assert watch.refused_text(9000, "linux", 8192) == (
        "the system lets a user watch 8,192 folders (fs.inotify.max_user_watches),"
        " and the root has 9,000"
    )
    assert watch.refused_text(9000, "linux", None) == (
        "the system refused to watch all 9,000 of the root's folders"
    )
    assert watch.refused_text(70, "win32", 8192).startswith("the system refused")
    limit = tmp_path / "max_user_watches"
    limit.write_text("65536\n")
    assert watch.inotify_limit(str(limit)) == 65536
    limit.write_text("lots")
    assert watch.inotify_limit(str(limit)) is None
    assert watch.inotify_limit(str(tmp_path / "none")) is None


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "Music"
    for f in ("A", "B/Deep"):
        (root / f).mkdir(parents=True)
    return root, {f: str(root / f) if f else str(root) for f in ("", "A", "B", "B/Deep")}


def test_a_change_in_a_watched_folder_is_gathered_and_ready_when_due(tree, qtbot):
    root, folders = tree
    w = watch.Watcher(str(root), watch.Gatherer(FakeClock(), wait=0))
    w.watch(folders)
    assert w.known() == folders and w.why == ""
    with qtbot.waitSignal(w.ready, timeout=5000):
        (root / "B" / "Deep" / "1.flac").write_bytes(b"x")
    assert w.due() and w.take() == {"B/Deep"}
    (root / "B" / "Deep" / "New").mkdir()
    w.update({"B/Deep/New": str(root / "B" / "Deep" / "New")}, {"A", "never watched"})
    assert set(w.known()) == {"", "B", "B/Deep", "B/Deep/New"}
    w.watch({"": str(root)})  # after a scan of the root: exactly what it walked
    assert w.known() == {"": str(root)}
    w._on_changed(str(root / "A"))  # a folder no longer watched: nothing
    assert w._gatherer.due_in() is None
    w.close()
    assert w.known() == {}


def test_a_ready_that_comes_early_waits_on_until_the_clock_says_so(tree, qtbot):
    root, folders = tree
    clock = FakeClock()
    w = watch.Watcher(str(root), watch.Gatherer(clock))
    ready = []
    w.ready.connect(lambda: ready.append(True))
    w._on_timer()  # nothing gathered
    w.changed("A")
    w._on_timer()  # the timer fired, but the clock says a second hasn't passed
    assert ready == [] and w._timer.isActive()
    clock.advance(seconds=1)
    w._on_timer()
    assert ready == [True]
    w.scanned([scanner.Seen("B/1.flac", 1, int(clock.now().timestamp() * 1e9))])
    assert w._timer.isActive()
    w.close()


def test_a_folder_the_system_refuses_stops_watching_and_the_log_says_why(tree, qtbot, caplog):
    root, folders = tree
    w = watch.Watcher(str(root), watch.Gatherer(FakeClock(), wait=0), add=lambda paths: paths[-1:])
    with qtbot.waitSignal(w.stopped) as stopped:
        w.watch(folders)
    assert w.why and stopped.args == [w.why] and w.known() == {}
    assert "stopped watching" in caplog.text and "window gains focus" in caplog.text
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    w.update({"C": str(root / "C")}, ())  # stopped for good
    w.changed("A")
    w.scanned([scanner.Seen("A/1.flac", 1, 0)])
    assert w.known() == {} and not w.due()


def test_a_folder_gone_before_its_watch_is_no_refusal(tree):
    root, folders = tree
    refused = os.path.join(str(root), "Gone")
    w = watch.Watcher(str(root), watch.Gatherer(FakeClock()), add=lambda paths: [refused])
    w.watch({**folders, "Gone": refused})
    assert w.why == "" and set(w.known()) == set(folders)
    w.close()


def test_the_clock_the_gatherer_reads_is_the_one_it_was_given():
    clock = FakeClock()
    g = watch.Gatherer(clock, wait=2.5)
    g.changed("A")
    clock.advance(seconds=2)
    assert g.due_in() == pytest.approx(0.5)
    clock._now -= timedelta(days=1)  # the wall clock set back: the gathering runs on its own
    assert g.due_in() == pytest.approx(0.5)
