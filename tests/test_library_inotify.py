"""Watching folders with inotify on Linux (src/musikata_core/inotify.py; A2.4, R2.4): the event
records read from bytes, the folders each watch stands for, and the watch itself on real folders,
a file rewritten in place among what it reports.

Why: Qt's watcher on Linux leaves out of a folder's watch the events a file rewritten in place
gives, so a song a tag editor (Picard, kid3, puddletag) retagged was never read again while
MusiKata ran, and the library showed its old tags until the next start."""

import errno
import os
import struct
import sys

import pytest
from fakes import FakeClock

from musikata_core import inotify, watch

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="inotify is Linux's")
pytestmark = linux


def record(wd, mask, name=b"", cookie=0):
    """One event as the system writes it: its header, then its name, NUL-ended and padded with
    NULs to a multiple of 16 bytes; none for an event on the folder itself."""
    padded = name + b"\0" * (16 - len(name) % 16) if name else b""
    return struct.pack("=iIII", wd, mask, cookie, len(padded)) + padded


# ---------- the records (plain logic) ----------


def test_event_records_are_read_from_bytes_with_their_names():
    data = (
        record(1, inotify.IN_CLOSE_WRITE, b"01 Tidewater.flac")
        + record(2, inotify.IN_DELETE_SELF)  # the folder itself: no name
        + record(1, inotify.IN_MOVED_TO, "Café.flac".encode(), cookie=7)
    )
    events, rest = inotify.parse(data)
    assert events == [
        inotify.Event(1, inotify.IN_CLOSE_WRITE, 0, "01 Tidewater.flac"),
        inotify.Event(2, inotify.IN_DELETE_SELF, 0, ""),
        inotify.Event(1, inotify.IN_MOVED_TO, 7, "Café.flac"),
    ]
    assert rest == b""


def test_a_record_cut_short_is_kept_for_the_next_read():
    whole = record(3, inotify.IN_CREATE, b"New Album")
    for cut in (1, 15, 16, len(whole) - 1):
        events, rest = inotify.parse(record(1, inotify.IN_ATTRIB, b"a.mp3") + whole[:cut])
        assert [e.name for e in events] == ["a.mp3"] and rest == whole[:cut]
        events, rest = inotify.parse(rest + whole[cut:])
        assert events == [inotify.Event(3, inotify.IN_CREATE, 0, "New Album")] and rest == b""
    assert inotify.parse(b"") == ([], b"")


def test_a_name_that_isnt_utf8_is_read_as_the_system_reads_it():
    (event,), _ = inotify.parse(record(1, inotify.IN_CREATE, b"caf\xe9.mp3"))
    assert event.name == os.fsdecode(b"caf\xe9.mp3")


def test_the_watch_asks_for_what_qts_did_and_a_file_written_and_closed():
    asked = inotify.FOLDER
    for mask in (inotify.IN_ATTRIB, inotify.IN_MOVED_FROM, inotify.IN_MOVED_TO,
                 inotify.IN_CREATE, inotify.IN_DELETE, inotify.IN_DELETE_SELF,
                 inotify.IN_CLOSE_WRITE, inotify.IN_ONLYDIR):  # fmt: skip
        assert asked & mask == mask
    assert asked & inotify.IN_MODIFY == 0  # each write of a copy in progress: a close is enough


def test_each_watch_stands_for_the_paths_it_was_added_under():
    w = inotify.Watches()
    w.add("/m/A", 1)
    w.add("/m/B", 2)
    w.add("/m/Link to A", 1)  # the system's watch on the same folder: shared
    w.add("/m/B", 2)  # again: nothing new
    assert w.paths(1) == ["/m/A", "/m/Link to A"] and w.paths(9) == []
    assert w.remove("/m/A") is None  # the link still has it
    assert w.remove("/m/Link to A") == 1  # the last: the system's watch goes
    assert w.remove("/m/never") is None and w.paths(1) == []
    w.add("/m/B", 5)  # added again after its folder was renamed back: the new watch
    assert w.paths(2) == [] and w.paths(5) == ["/m/B"]


def test_the_folders_events_name_are_each_given_once_and_an_overflow_said():
    w = inotify.Watches()
    w.add("/m/A", 1)
    w.add("/m/B", 2)
    events = [
        inotify.Event(1, inotify.IN_CLOSE_WRITE, 0, "1.flac"),
        inotify.Event(2, inotify.IN_CREATE, 0, "2.flac"),
        inotify.Event(1, inotify.IN_ATTRIB, 0, "1.flac"),
        inotify.Event(7, inotify.IN_CREATE, 0, "x"),  # a watch let go of: nothing
    ]
    assert w.changed(events) == (["/m/A", "/m/B"], False)
    overflow = [inotify.Event(-1, inotify.IN_Q_OVERFLOW, 0, "")]
    assert w.changed(overflow) == ([], True)


def test_a_watch_the_system_ended_gives_its_folder_and_is_forgotten():
    """A folder removed or unmounted (an unplugged drive, R2.10) ends its watch: IN_IGNORED
    follows IN_DELETE_SELF or IN_UNMOUNT."""
    w = inotify.Watches()
    w.add("/m", 1)
    events = [
        inotify.Event(1, inotify.IN_UNMOUNT, 0, ""),
        inotify.Event(1, inotify.IN_IGNORED, 0, ""),
    ]
    assert w.changed(events) == (["/m"], False)
    assert w.paths(1) == [] and w.remove("/m") is None


# ---------- the watch, over the system's calls ----------


class FakeSystem:
    """The system's calls, by a test: watches it refuses by path and errno, events it gives."""

    def __init__(self, refuse=None):
        self.refuse = refuse or {}
        self.watches, self.removed, self.waiting, self.closed = {}, [], [], False
        self.fail_reading = None
        self._r, self._w = os.pipe()

    def init(self):
        return self._r

    def add_watch(self, fd, path, mask):
        if path in self.refuse:
            raise OSError(self.refuse[path], os.strerror(self.refuse[path]), path)
        return self.watches.setdefault(path, len(self.watches) + 1)

    def rm_watch(self, fd, wd):
        if wd == 99:
            raise OSError(errno.EINVAL, "Invalid argument")
        self.removed.append(wd)

    def read(self, fd):
        if self.fail_reading is not None:
            raise self.fail_reading
        return self.waiting.pop(0) if self.waiting else b""

    def close(self, fd):
        self.closed = True
        os.close(self._r)
        os.close(self._w)


def test_the_folders_the_system_refuses_are_given_back_and_the_rest_watched(qapp, caplog):
    system = FakeSystem({"/m/Full": errno.ENOSPC, "/m/Gone": errno.ENOENT})
    n = inotify.Inotify(system=system)
    assert n.add(["/m", "/m/Full", "/m/A", "/m/Gone"]) == ["/m/Full", "/m/Gone"]
    assert set(system.watches) == {"/m", "/m/A"}
    n.remove(["/m/A", "/m/Full"])
    assert system.removed == [system.watches["/m/A"]]
    n.close()
    n.close()  # once only
    assert system.closed


def test_what_the_system_wrote_is_read_whole_and_each_folder_said(qapp, qtbot):
    system = FakeSystem()
    n = inotify.Inotify(system=system)
    n.add(["/m/A", "/m/B"])
    a, b = system.watches["/m/A"], system.watches["/m/B"]
    second = record(b, inotify.IN_CREATE, b"2.flac")
    system.waiting = [record(a, inotify.IN_CLOSE_WRITE, b"1.flac") + second[:5], second[5:]]
    changed, overflowed = [], []
    n.changed.connect(changed.append)
    n.overflowed.connect(lambda: overflowed.append(True))
    n.read()
    assert changed == ["/m/A", "/m/B"] and overflowed == []
    system.waiting = [record(-1, inotify.IN_Q_OVERFLOW)]
    n.read()
    assert overflowed == [True]
    n.close()


def test_a_read_that_fails_is_logged_and_what_was_read_said(qapp, caplog):
    system = FakeSystem()
    n = inotify.Inotify(system=system)
    n.add(["/m"])
    system.waiting = [record(1, inotify.IN_CREATE, b"1.flac")]
    changed = []
    n.changed.connect(changed.append)
    system.fail_reading = OSError(errno.EIO, "Input/output error")
    n.read()
    assert changed == [] and "couldn't read" in caplog.text
    system.fail_reading = None
    n.read()
    assert changed == ["/m"]
    n.remove(["/m"])
    system.watches["/m"] = 99  # its folder went, and its watch with it
    n.add(["/m"])
    n.remove(["/m"])  # the system's error is no failure
    n.close()


def test_an_instance_not_closed_is_let_go_of_when_it_goes(qapp):
    import gc

    system = FakeSystem()
    n = inotify.Inotify(system=system)
    n.add(["/m"])
    del n
    gc.collect()
    assert system.closed


# ---------- on real folders ----------


@pytest.fixture
def folders(tmp_path, qapp):
    root = tmp_path / "Music"
    (root / "A").mkdir(parents=True)
    song = root / "A" / "1.flac"
    song.write_bytes(b"fLaC" + b"\0" * 60)
    n = inotify.Inotify()
    changed = []
    n.changed.connect(changed.append)
    yield root, song, n, changed
    n.close()


def test_a_file_rewritten_in_place_is_reported(folders, qtbot):
    """What Picard, kid3 or puddletag do to a song when its tags fit: the file opened for
    writing, written over and closed, its folder's list of files unchanged."""
    root, song, n, changed = folders
    assert n.add([str(root), str(root / "A")]) == []
    with open(song, "r+b") as f:
        f.seek(4)
        f.write(b"retagged")
    qtbot.waitUntil(lambda: str(root / "A") in changed, timeout=5000)
    assert str(root) not in changed


def test_a_file_added_renamed_or_removed_and_a_folder_gone_are_reported(folders, qtbot):
    root, song, n, changed = folders
    n.add([str(root), str(root / "A")])
    os.rename(song, root / "A" / "2.flac")
    qtbot.waitUntil(lambda: str(root / "A") in changed, timeout=5000)
    assert str(root) not in changed
    os.remove(root / "A" / "2.flac")
    os.rmdir(root / "A")
    qtbot.waitUntil(lambda: str(root) in changed, timeout=5000)  # its parent's list changed
    assert changed.count(str(root / "A")) >= 2  # and the folder itself went
    assert n.add([str(root / "A"), str(root / "missing")]) == [
        str(root / "A"),
        str(root / "missing"),
    ]


def test_a_path_that_isnt_a_folder_is_refused(folders):
    root, song, n, _ = folders
    assert n.add([str(song)]) == [str(song)]


def test_the_watcher_on_linux_watches_with_inotify_and_hears_a_rewrite(tmp_path, qtbot):
    root = tmp_path / "Music"
    (root / "A").mkdir(parents=True)
    song = root / "A" / "1.flac"
    song.write_bytes(b"fLaC" + b"\0" * 60)
    w = watch.Watcher(str(root), watch.Gatherer(FakeClock(), wait=0))
    assert isinstance(w._folders, inotify.Inotify)
    w.watch({"": str(root), "A": str(root / "A")})
    with qtbot.waitSignal(w.ready, timeout=5000), open(song, "r+b") as f:
        f.write(b"fLaC retagged")
    assert w.take() == {"A"}
    w.close()
