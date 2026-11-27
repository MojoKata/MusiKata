"""Organize files in the running app (src/musikata/organize.py, OrganizeDialog.qml, and where it
opens: the header's ⋮ menu in Folders and on an album's page, the selection bars and the
right-click menus; and files dropped from outside the root; R12, T03-organize-files): what the
dialog says, the moves listed with their checkboxes and conflicts, the moves made as one entry of
the change history whose Undo puts every file and playlist back, and files brought in from
outside (R12.5).

Why: the dialog is where a whole library is renamed at once; a checkbox that doesn't reach the
plan, a playlist banner that names the wrong lists, or files from outside copied over the
library's, would move or lose the user's music unasked."""

import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes import FakeClock, wav
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, layout, tour
from musikata.history import ChangeHistory
from musikata.organize import (
    COPY,
    MOVE,
    OrganizeFiles,
    about_text,
    action_label,
    description_of,
    done_text,
    footer_text,
    inferred,
    layout_label,
    missing,
    more_text,
    notes_text,
    playlists_text,
    progress_text,
    with_fields,
)
from musikata_core import db, organize, playlists, scanner, settings
from musikata_core import tags as tags_core
from musikata_core.organize import Followed, Outside
from musikata_core.tags import Failed, Job, Outcome, Tags

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import demo_library as demo  # noqa: E402

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
NOW = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
LD = "Lumen Drift"
ALBUM = "Lumen Drift/2022 - Tide Tables"


# ---------- what it says ----------


def test_the_dialog_says_what_it_does_as_t03_does():
    assert about_text(False, "/home/me/Music", "/home/me") == (
        "Rename and move files to match their tags. Every move is listed first, and Undo puts"
        " them back."
    )
    assert about_text(True, "/home/me/Music", "/home/me").startswith("Place these files in ~/Music")
    assert layout_label("/home/me/Music", "/home/me") == "Layout under ~/Music"
    assert layout_label("/srv/Music", "/home/me") == "Layout under /srv/Music"


def test_the_line_under_the_list_counts_the_moves_past_those_shown_and_the_folders_emptied():
    """T03: + 10 more moves · 2 empty folders will be removed (R12.3)."""
    assert more_text(14, 4, 2) == "+ 10 more moves · 2 empty folders will be removed"
    assert more_text(5, 4, 0) == "+ 1 more move"
    assert more_text(4, 4, 1) == "1 empty folder will be removed"
    assert more_text(2, 4, 0) == ""


def test_the_banner_footer_and_button_say_what_the_moves_do():
    """T03, R12.4: the playlists updated, the total and the conflicts, Move N files."""
    assert playlists_text(["Road Trip", "Workout Mix"]) == (
        "Playlists that list these files are updated too: Road Trip, Workout Mix."
    )
    assert playlists_text([]) == ""
    assert footer_text(14, 0) == "14 files · no name conflicts"
    assert footer_text(1, 1) == "1 file · 1 name conflict: uncheck one of each, or change its tags"
    assert footer_text(0, 3).startswith("0 files · 3 name conflicts")
    assert action_label(14, False) == "Move 14 files"
    assert action_label(1, True, COPY) == "Copy 1 file" and action_label(2, True, MOVE) == (
        "Move 2 files"
    )
    assert progress_text(3, 14, False) == "Moving 3 of 14 files…"
    assert progress_text(1, 2, True, COPY) == "Copying 1 of 2 files…"
    assert description_of(14) == "Organize files: 14 files"


def test_what_isnt_moved_is_said_with_why():
    """R12.3: songs already where they belong; songs with no tags (Infer from path first); R12.5:
    files the library has already, and those that couldn't be read."""
    assert notes_text(0, 0) == ""
    assert notes_text(1, 0) == "1 song is where it belongs already"
    assert notes_text(3, 2) == (
        "3 songs are where they belong already · 2 songs have no tags to place by: Infer from"
        " path first"
    )
    assert notes_text(0, 1) == "1 song has no tags to place by: Infer from path first"
    assert notes_text(0, 0, ["a.mp3"], 1) == (
        "In your library already, so not added: a.mp3 · 1 file couldn't be read"
    )
    assert notes_text(0, 0, ["a", "b", "c", "d"]).endswith("a, b and 2 more")


def test_the_message_says_what_moved_what_didnt_and_the_playlists_updated():
    """R12.4, R6.7: a move that fails midway says what didn't."""
    job = Job("/m/Old/b.wav", {})
    ok = Outcome(saved=[1, 2])
    assert done_text(ok, Followed()) == "Moved 2 files"
    assert done_text(ok, Followed(playlists=["P/a.m3u8"])) == "Moved 2 files · 1 playlist updated"
    failed = Outcome(saved=[1], failed=[Failed(job, "it can't be written"), Failed(job, "x")])
    assert done_text(failed, Followed()) == (
        "Moved 1 of 3 files: b.wav it can't be written, and 1 more"
    )
    cancelled = Outcome(saved=[1], cancelled=True, left=[job])
    assert done_text(cancelled, Followed()) == "Moved 1 of 2 files: cancelled before the rest"
    assert done_text(ok, Followed(failed=["the library"])) == (
        "Moved 2 files; the library will follow at the next scan"
    )
    assert done_text(ok, Followed(), True, COPY) == "Copied 2 files into your library"
    assert done_text(ok, Followed(), True, MOVE) == "Moved 2 files into your library"


def test_infer_from_path_fills_only_the_tags_missing_from_files_from_outside():
    """R12.5, R3.5: the pattern that fits most of the files missing tags, only the empty ones
    filled; a file whose tags are whole, or that no pattern fits, is left as it is."""
    found = [
        Outside("/d/K/2022 - Low Orbit/01 - Low Orbit.mp3", "K/2022 - Low Orbit/01 - Low Orbit.mp3",
                Tags(title="Low Orbit (edit)")),
        Outside("/d/K/2022 - Low Orbit/02 - Perihelion.mp3",
                "K/2022 - Low Orbit/02 - Perihelion.mp3"),
        Outside("/d/whole.mp3", "whole.mp3", Tags(title="T", artist="A", album="B")),
        Outside("/d/x.mp3", "x.mp3"),
    ]  # fmt: skip
    got = inferred(found)
    assert got["/d/K/2022 - Low Orbit/01 - Low Orbit.mp3"] == {
        "albumartist": "K", "album": "Low Orbit", "track": 1, "year": 2022}  # fmt: skip
    assert got["/d/K/2022 - Low Orbit/02 - Perihelion.mp3"]["title"] == "Perihelion"
    assert set(got) == {found[0].path, found[1].path}
    assert inferred([found[2]]) == {} and inferred([]) == {}
    assert missing(Tags(title="T", artist="A")) and not missing(found[2].tags)
    assert with_fields(Tags(), {"genres": ["Soul"], "year": 2015}) == Tags(genres=("Soul",),
                                                                          year=2015)  # fmt: skip


# ---------- the dialog over a root ----------


def tagged(path, seed, **changes):
    wav(path, seed)
    tags_core.save(str(path), changes, audio_hash=scanner.audio_hash)
    return str(path)


@pytest.fixture
def root(tmp_path):
    """An album of two songs in a folder named otherwise, its cover beside them; a song already
    where it belongs; one with no tags; two songs that would take one path; a playlist naming one
    of them. (root, index)."""
    music = tmp_path / "Music"
    common = {"artist": LD, "album": "Tide Tables", "year": 2022}
    tagged(music / "Old" / "a.wav", 1, title="Neap Tide", track=1, **common)
    tagged(music / "Old" / "b.wav", 2, title="Spring Tide", track=2, **common)
    (music / "Old" / "cover.jpg").write_bytes(demo.cover_jpeg(11, 32))
    tagged(music / ALBUM / "03 - Slack Water.wav", 3, title="Slack Water", track=3, **common)
    wav(music / "_Incoming" / "track01.wav", 4)
    tagged(music / "x" / "one.wav", 5, title="Same", artist="A", album="B")
    tagged(music / "y" / "two.wav", 6, title="Same", artist="A", album="B")
    (music / "Playlists").mkdir()
    (music / "Playlists" / "Road Trip.m3u8").write_text("#EXTM3U\n../Old/a.wav\n")
    index = db.Index(str(tmp_path / "musikata.db"))
    with ThreadPoolExecutor(1) as pool:
        scanner.scan(str(music), index, pool, hold=False)
    yield str(music), index
    index.close()


class Lib(QObject):
    """What the dialog tells the library: reload, and songsMoved."""

    from PySide6.QtCore import Signal

    songsMoved = Signal()

    def __init__(self):
        super().__init__()
        self.reloads = 0
        self.moved = 0
        self.songsMoved.connect(self._moved)

    def reload(self):
        self.reloads += 1

    def _moved(self):
        self.moved += 1


def make(music, index, **kw):
    h = ChangeHistory(
        music, index, FakeClock(NOW), lambda: ME, ME, "Laptop", settings.RootTags(),
        executor=ThreadPoolExecutor(1), watching=False, message_ms=60_000,
    )  # fmt: skip
    store = playlists.Store(music, index, "Playlists", "cp1252")

    def write(fn):
        return index.write(fn).result()

    follow = organize.Follower(music, write, store.repoint)
    h.follow = follow
    lib = Lib()
    added = []

    def save(job):
        return tags_core.save(job.path, job.changes, audio_hash=scanner.audio_hash)

    o = OrganizeFiles(music, index.read, follow, h, lib, write, save,
                      lambda p, ids: added.append((p, list(ids))),
                      executor=ThreadPoolExecutor(1), clock=FakeClock(NOW), **kw)  # fmt: skip
    o.history_, o.lib_, o.added_ = h, lib, added
    return o


def opened(o, qtbot, open_):
    with qtbot.waitSignal(o.changed, timeout=WAIT,
                          check_params_cb=lambda: not o.property("loading")):  # fmt: skip
        open_()


def rows(o):
    m = o.property("moves")
    return [m.row(i) for i in range(m.rowCount())]


def test_organize_files_lists_each_move_and_moves_them_in_one_entry_that_undo_puts_back(
    root, qtbot
):
    """R12.2 to R12.4 through the bridge, on the whole root (Folders' ⋮ at the root): every move,
    old path above new, each with its checkbox; two files to one path both a conflict, moved once
    one is unchecked; the cover with its album; the folder left empty removed; the playlist
    naming a file moved, named in the banner, updated; one entry, whose Undo puts every file and
    the playlist back."""
    music, index = root
    o = make(music, index)
    h = o.history_
    try:
        assert not o.property("opened") and o.property("title") == "Organize files"
        o.close()  # nothing open: nothing to close
        opened(o, qtbot, lambda: o.openFolder(""))
        assert o.property("opened") and not o.property("adding")
        assert o.property("layout") == "{albumartist}/{year} - {album}/{disc-}{track:02} - {title}"
        listed = {r["old"]: r for r in rows(o)}
        assert listed["Old/a.wav"]["target"] == f"{ALBUM}/01 - Neap Tide.wav"
        assert listed["Old/cover.jpg"]["target"] == f"{ALBUM}/cover.jpg"
        assert listed["Old/cover.jpg"]["sidecar"] and not listed["Old/a.wav"]["sidecar"]
        assert listed["x/one.wav"]["note"] == "Another file would get this name"
        assert not listed["x/one.wav"]["moving"] and listed["x/one.wav"]["checked"]
        assert (
            o.property("footer")
            == "3 files · 2 name conflicts: uncheck one of each, or change its tags"
        )
        assert o.property("notes") == (
            "1 song is where it belongs already · 1 song has no tags to place by: Infer from"
            " path first"
        )
        assert o.property("playlists") == (
            "Playlists that list these files are updated too: Road Trip."
        )
        o.setShown(2)
        assert o.property("more") == "+ 3 more moves · 1 empty folder will be removed"
        o.setShown(4)
        assert o.property("actionLabel") == "Move 3 files" and o.property("actionLater") == ""
        n = [r["old"] for r in rows(o)].index("y/two.wav")
        o.toggle(n)  # one of the two unchecked: the other moves
        listed = {r["old"]: r for r in rows(o)}
        assert listed["x/one.wav"]["moving"] and not listed["y/two.wav"]["checked"]
        assert o.property("footer") == "4 files · no name conflicts"
        o.toggle(99)  # no such row: nothing
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            o.run()
            assert o.property("moving") and o.property("footer").startswith("Moving")
            assert o.property("actionLater") == "Files are being moved"
            o.toggle(0)  # nothing changes while it moves
        assert not o.property("opened") and not o.property("moving")
        assert h.property("message")["text"] == "Moved 4 files · 1 playlist updated"
        assert sorted(os.listdir(os.path.join(music, ALBUM))) == [
            "01 - Neap Tide.wav",
            "02 - Spring Tide.wav",
            "03 - Slack Water.wav",
            "cover.jpg",
        ]
        assert not os.path.exists(os.path.join(music, "Old"))
        assert os.path.exists(os.path.join(music, "A", "B", "Same.wav"))
        assert os.path.exists(os.path.join(music, "y", "two.wav"))
        road = (Path(music) / "Playlists" / "Road Trip.m3u8").read_text(encoding="utf-8")
        assert f"../{ALBUM}/01 - Neap Tide.wav" in road
        assert o.lib_.reloads >= 1 and o.lib_.moved == 1
        c = index.read()
        qtbot.waitUntil(lambda: c.execute("SELECT COUNT(*) FROM change").fetchone()[0] == 1,
                        timeout=WAIT)  # fmt: skip
        assert c.execute("SELECT action, description FROM change").fetchone() == (
            "organize",
            "Organize files: 4 files",
        )
        moved = []
        h.moved = lambda: moved.append(1)
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            h.undoMessage()
        qtbot.waitUntil(lambda: "Undone" in h.property("message").get("text", ""), timeout=WAIT)
        assert sorted(os.listdir(os.path.join(music, "Old"))) == ["a.wav", "b.wav", "cover.jpg"]
        assert os.listdir(os.path.join(music, ALBUM)) == ["03 - Slack Water.wav"]
        road = (Path(music) / "Playlists" / "Road Trip.m3u8").read_text(encoding="utf-8")
        assert "../Old/a.wav" in road and moved == [1]
        assert index.read().execute("SELECT 1 FROM song WHERE path = 'Old/a.wav'").fetchone()
    finally:
        o.shut()
        h.close()


class Picked(QObject):
    """A list's model, as the selection bars and menus give it."""

    def __init__(self, ids, selected=True):
        super().__init__()
        self.ids, self.selected = ids, selected

    def selected_songs(self):
        return self.ids

    def songs_at(self, row):
        return self.ids[:1]

    def is_selected(self, row):
        return self.selected


class View(QObject):
    """The library as the header's ⋮ menu gives it."""

    def __init__(self, view, folder="", album=-1):
        super().__init__()
        self._view = view
        self._folders = QObject()
        self._folders.setProperty("path", folder)
        self._album = QObject()
        self._album.setProperty("id", album)

    def property(self, name):
        return {"view": self._view, "folders": self._folders, "album": self._album}[name]


def test_it_opens_on_an_album_a_selection_a_row_and_the_header_of_folders_or_an_album(root, qtbot):
    """R12.2, R2.9.6: the ⋮ menu of Folders (the open folder's songs) and of an album's page, a
    selection (a folder's every song beneath it), a right-click menu's row."""
    music, index = root
    o = make(music, index)
    try:
        c = index.read()
        album = c.execute("SELECT album_id FROM song WHERE path = 'Old/a.wav'").fetchone()[0]
        a = c.execute("SELECT id FROM song WHERE path = 'Old/a.wav'").fetchone()[0]
        opened(o, qtbot, lambda: o.openAlbum(album))
        assert {r["old"] for r in rows(o)} == {"Old/a.wav", "Old/b.wav", "Old/cover.jpg"}
        opened(o, qtbot, lambda: o.openSelection(Picked([a])))
        assert [r["old"] for r in rows(o)] == ["Old/a.wav"]  # the cover stays with b.wav
        opened(o, qtbot, lambda: o.openRow(Picked([a], selected=False), 0))
        assert [r["old"] for r in rows(o)] == ["Old/a.wav"]
        opened(o, qtbot, lambda: o.openRow(Picked([a]), 0))
        opened(o, qtbot, lambda: o.openView(View("folders", "Old")))
        assert len(rows(o)) == 3
        opened(o, qtbot, lambda: o.openView(View("album", album=album)))
        assert len(rows(o)) == 3
        o.openView(View("songs"))  # not offered there: nothing
        o.close()
        assert not o.property("opened")
        o.go({"view": "folders", "organize": "Old"})
        qtbot.waitUntil(lambda: o.property("opened") and not o.property("loading"), timeout=WAIT)
        o.go({"view": "albums"})
        assert not o.property("opened")
        o.go({"view": "albums"})
    finally:
        o.shut()
        o.history_.close()


def test_nothing_moves_while_the_root_isnt_there_and_a_layout_that_cant_be_used_is_passed_by(
    root, qtbot, caplog
):
    """R2.10: no change to files while the root isn't there, and the message says why; R12.1: a
    layout in the root's settings that can't be used gives way to the default, and the log says
    so."""
    music, index = root
    there = [True]
    o = make(music, index, available=lambda: there[0], layout="{*}/{title}")
    try:
        assert "can't be used" in caplog.text and o.property("layout") == organize.patterns.LAYOUT
        opened(o, qtbot, lambda: o.openFolder("Old"))
        there[0] = False
        assert o.property("actionLater") == organize_not_there()
        o.run()
        assert not o.property("moving")
        o.close()
        o.openFolder("Old")
        assert not o.property("opened")
        assert o.history_.property("message")["text"] == organize_not_there()
        there[0] = True
        opened(o, qtbot, lambda: o.openFolder("nowhere"))
        assert o.property("actionLater") == "Nothing to move"
        o.run()  # nothing to move: nothing runs
        assert not o.property("moving")
    finally:
        o.shut()
        o.history_.close()


def organize_not_there():
    from musikata.organize import NOT_THERE

    return NOT_THERE


def test_cancel_stops_the_moves_before_the_next_file(root, qtbot, monkeypatch):
    """R12.4: Cancel between files; what moved stays recorded and undoable."""
    music, index = root
    o = make(music, index)
    real = organize.move_file
    gate = []

    def slow(job):
        gate.append(job.path)
        if len(gate) == 1:
            o.close()  # Cancel while the first moves
        return real(job)

    monkeypatch.setattr(organize, "move_file", slow)
    try:
        opened(o, qtbot, lambda: o.openFolder("Old"))
        with qtbot.waitSignal(o.history_.messageChanged, timeout=WAIT):
            o.run()
        assert len(gate) == 1
        assert "cancelled before the rest" in o.history_.property("message")["text"]
    finally:
        o.shut()
        o.history_.close()


@pytest.fixture
def outside(tmp_path, root):
    """Files from outside the root: an album's folder whose files have no tags, its cover beside
    them, and a copy of a song the library has (the same audio, retagged)."""
    music, _index = root
    rips = tmp_path / "Downloads" / "Kestrel Union" / "2022 - Low Orbit"
    wav(rips / "01 - Low Orbit.wav", 11)
    wav(rips / "02 - Perihelion.wav", 12)
    (rips / "cover.jpg").write_bytes(b"jpeg")
    copy = tmp_path / "Downloads" / "copy.wav"
    shutil.copyfile(os.path.join(music, "Old", "a.wav"), copy)
    tags_core.save(str(copy), {"title": "Retagged"}, audio_hash=scanner.audio_hash)
    return str(tmp_path / "Downloads" / "Kestrel Union"), str(copy)


def test_files_from_outside_are_placed_by_the_layout_copied_in_and_added_to_their_playlist(
    root, outside, qtbot
):
    """R12.5: Copy into the library (the default), their tags read, Infer from path where they are
    missing, placed by the layout with the same preview; a file the library has reported and not
    added twice; copied off the GUI thread, indexed, and added to the playlist dropped on."""
    music, index = root
    folder, copy = outside
    o = make(music, index)
    try:
        opened(o, qtbot, lambda: o.add_files([folder, copy], playlist=7))
        assert o.property("adding") and o.property("title") == "Add to your library"
        assert o.property("ways") == [
            {"name": "copy", "label": "Copy into the library", "chosen": True},
            {"name": "move", "label": "Move into the library", "chosen": False},
        ]
        assert o.property("inferLabel") == "Infer from path for 2 files whose tags are missing"
        assert o.property("notes") == "In your library already, so not added: copy.wav"
        listed = [(r["old"].rpartition(os.sep)[2], r["target"]) for r in rows(o)]
        assert listed == [
            ("01 - Low Orbit.wav", "Kestrel Union/2022 - Low Orbit/01 - Low Orbit.wav"),
            ("02 - Perihelion.wav", "Kestrel Union/2022 - Low Orbit/02 - Perihelion.wav"),
            ("cover.jpg", "Kestrel Union/2022 - Low Orbit/cover.jpg"),
        ]
        o.toggleInfer()
        assert rows(o) == [] and o.property("notes").startswith("2 songs have no tags")
        o.toggleInfer()
        assert o.property("actionLabel") == "Copy 3 files" and o.property("playlists") == ""
        with qtbot.waitSignal(o.changed, timeout=WAIT,
                              check_params_cb=lambda: not o.property("opened")):  # fmt: skip
            o.run()
        placed = os.path.join(music, "Kestrel Union", "2022 - Low Orbit")
        assert sorted(os.listdir(placed)) == ["01 - Low Orbit.wav", "02 - Perihelion.wav",
                                              "cover.jpg"]  # fmt: skip
        assert os.path.exists(os.path.join(folder, "2022 - Low Orbit", "01 - Low Orbit.wav"))
        t = tags_core.read(os.path.join(placed, "02 - Perihelion.wav"))[0]
        assert (t.albumartist, t.album, t.year, t.track, t.title) == (
            "Kestrel Union", "Low Orbit", 2022, 2, "Perihelion")  # fmt: skip
        c = index.read()
        ids = [c.execute("SELECT id FROM song WHERE path = ?", (f"Kestrel Union/2022 - Low Orbit/"
                                                                f"{n}",)).fetchone()[0]
               for n in ("01 - Low Orbit.wav", "02 - Perihelion.wav")]  # fmt: skip
        assert o.added_ == [(7, ids)]
        assert c.execute("SELECT COUNT(*) FROM change").fetchone() == (0,)  # no save of tags kept
    finally:
        o.shut()
        o.history_.close()


def test_move_into_the_library_takes_the_files_and_says_so(root, outside, qtbot):
    music, index = root
    folder, _copy = outside
    o = make(music, index)
    try:
        opened(o, qtbot, lambda: o.add_files([folder]))
        o.setWay("move")
        o.setWay("nowhere")  # no such way: nothing
        assert o.property("actionLabel") == "Move 3 files"
        with qtbot.waitSignal(o.history_.messageChanged, timeout=WAIT):
            o.run()
        assert o.history_.property("message")["text"] == "Moved 3 files into your library"
        assert not os.path.exists(os.path.join(folder, "2022 - Low Orbit", "01 - Low Orbit.wav"))
        assert o.added_ == []
    finally:
        o.shut()
        o.history_.close()


# ---------- in the window ----------


@pytest.fixture
def shell(root, tmp_path, qapp, qtbot):
    music, index = root
    index.close()
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(music, env, FakeClock(datetime.now(UTC) - timedelta(minutes=1)),
                 lambda: ThreadPoolExecutor(1))  # fmt: skip
    s.library.rescan()
    qtbot.waitUntil(lambda: not s.library.scanning, timeout=WAIT * 3)
    s.window.show()
    yield s
    s.close()


def find(shell, name):
    found = []

    def walk(item):
        if item.objectName() == name and item.isVisible():
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    return found


def click(shell, item):
    at = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


def settled(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.window.grabWindow()


@pytest.mark.slow
def test_organize_files_opens_from_folders_menu_with_no_qml_warning_and_its_text_in_its_boxes(
    shell, qtbot, qtlog
):
    """T03 in the window: ⋮ › Organize files… in Folders opens the dialog over the open folder,
    its moves listed with their checkboxes, the line under them, the banner and the footer whole;
    a checkbox clicked unchecks its move; Cancel closes it. The selection bar's and the right-click
    menu's Organize name it (R2.9.6)."""
    lib = shell.library
    lib.show("folders")
    settled(shell, qtbot)
    assert lib.property("canOrganize")
    click(shell, find(shell, "more")[0])
    qtbot.waitUntil(lambda: find(shell, "organizeView") != [], timeout=WAIT)
    QTest.keyClick(shell.window, Qt.Key.Key_Escape)
    o = shell.organize
    o.openView(lib)  # what ⋮ › Organize files… does
    qtbot.waitUntil(lambda: o.property("opened") and not o.property("loading"), timeout=WAIT)
    settled(shell, qtbot)
    assert find(shell, "organizeDialog") and find(shell, "organizePlaylists")
    assert find(shell, "organizeMore") and find(shell, "organizeLayout")
    assert layout.faults(shell.window) == []
    before = o.property("footer")
    click(shell, find(shell, "organizeCheck")[0])
    assert o.property("footer") != before
    click(shell, find(shell, "cancelOrganize")[0])
    qtbot.waitUntil(lambda: not o.property("opened"), timeout=WAIT)
    lib.show("songs")
    settled(shell, qtbot)
    assert not lib.property("canOrganize")
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


def test_the_selection_bars_and_menus_name_organize():
    """R12.2, R2.9.6: Organize… on Folders' and Songs' selection bars, no later a later
    version's."""
    from musikata import folders, models

    organize_action = {"label": "Organize…", "icon": "arrow", "later": "", "action": "organize"}
    assert organize_action in models.SONG_LATER and organize_action in folders.LATER
    assert folders.selection_actions(True)[-1] == organize_action
