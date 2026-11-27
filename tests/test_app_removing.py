"""Removing songs in the running app (src/musikata/removing.py, and where it opens: the right-click
menus, an album's ⋯ menu, Folders' ⋮ menu and Delete in the library views; R2.11, R2.11.1): what
the question and the message say, the files moved to the trash with those beside them, the rows
gone at once, one entry in the change history that Undo can't take back out of the trash, the
playlists left naming them, plays kept for a song put back by hand; and Ignore this folder.

Why: Move to trash is the one action that takes music away from the user. A question that names
the wrong files, a cover left behind or taken from an album that stays, rows left listed for
files gone, or a song put back from the trash that lost its plays, would each cost them music or
what they kept about it."""

import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeClock, played, wav
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, bridges, layout, tour
from musikata.history import IN_TRASH, ChangeHistory
from musikata.removing import (
    NOT_IGNORED,
    NOT_THERE,
    NOTHING,
    Removing,
    description_of,
    done_text,
    ignored_text,
    names_text,
    question_of,
    what_text,
)
from musikata_core import db, history, organize, rootfiles, scanner, settings, tags
from musikata_core.organize import Going, Removal
from musikata_core.tags import Failed, Job, Outcome

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import demo_library as demo  # noqa: E402

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
NOW = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)


# ---------- what it says ----------


def folder(path, n):
    return Going(path, None, True, tuple((f"{path}/{i}.flac", None) for i in range(n)))


def songs(*paths):
    return tuple(Going(p, None, False, ((p, None),)) for p in paths)


def test_the_question_names_what_goes_as_r2_11_does():
    """R2.11, R6.8: "Move 3 songs to the trash?", "Move the folder Kindling and its 10 songs to
    the trash?", naming the files, those beside them that go too, what playlists keep and what
    Undo can't do."""
    three = Removal(songs("A/a.flac", "A/b.flac", "B/c.mp3"))
    assert question_of(three)["title"] == "Move 3 songs to the trash?"
    kindling = Removal((folder("Mid/Kindling", 10),))
    assert (
        question_of(kindling)["title"] == "Move the folder Kindling and its 10 songs to the trash?"
    )
    assert question_of(kindling)["yes"] == "Move to trash"
    beside = Removal((*songs("R/01.flac"), Going("R/cover.jpg"), Going("R/album.cue")))
    detail = question_of(beside)["detail"]
    assert detail.startswith("01.flac goes to the system's trash. cover.jpg and album.cue beside")
    assert "Playlists keep their entries, shown as missing" in detail
    assert "Undo can't take files out of the trash" in detail
    assert question_of(Removal((*songs("a", "b"), Going("c.jpg"))))["detail"].startswith(
        "a and b go to the system's trash. c.jpg beside them goes too.")  # fmt: skip
    assert what_text(Removal((folder("A", 2), folder("B", 3)))) == "2 folders and their 5 songs"
    assert what_text(Removal((folder("A", 2), *songs("x.mp3")))) == (
        "the folder A with its 2 songs, and 1 other song")  # fmt: skip
    assert what_text(Removal(songs("x.mp3"))) == "1 song"
    assert description_of(kindling) == "The folder Kindling and its 10 songs to the trash"
    assert names_text(["a", "b", "c", "d"]) == "a, b and 2 more"
    assert names_text([]) == "" and names_text(["a"]) == "a"


def test_the_message_says_what_went_what_didnt_and_that_undo_cant_take_them_back():
    """R2.11, R6.7: the message says Undo can't take files out of the trash."""
    removal = Removal(songs("A/a.flac", "A/b.flac"))
    ok = Outcome(saved=[1, 2])
    assert done_text(removal, ok) == f"Moved 2 songs to the trash; {IN_TRASH}"
    job = Job("/m/A/b.flac", {})
    some = Outcome(saved=[1], failed=[Failed(job, "couldn't be moved"), Failed(job, "x")])
    assert done_text(removal, some) == (
        f"Moved 1 of 3 files to the trash: b.flac couldn't be moved, and 1 more; {IN_TRASH}"
    )
    none = Outcome(failed=[Failed(job, "isn't there any more")])
    assert done_text(removal, none) == "Moved 0 of 1 file to the trash: b.flac isn't there any more"
    assert done_text(removal, Outcome()) == NOTHING
    assert done_text(removal, ok, listed=True) == (
        f"Moved 2 songs to the trash. They stay listed until the library's next scan; {IN_TRASH}"
    )
    assert ignored_text("Mid/Kindling", 10).startswith(
        "Kindling is ignored: its 10 songs left the library.")  # fmt: skip
    assert ignored_text("Empty", 0).startswith("Empty is ignored: it held no songs.")


# ---------- over a root ----------


@pytest.fixture
def root(tmp_path):
    """Kindling, an album of two songs with its cover, cue sheet and one song's lyrics, a note
    that isn't R12.3's; Ember, a song alone beside another; a playlist naming one of Kindling's
    songs. (root, index)."""
    music = tmp_path / "Music"
    for n, title in ((1, "Spark"), (2, "Flame")):
        path = music / "Kindling" / f"0{n} {title}.wav"
        wav(path, n)
        tags.save(str(path), {"title": title, "album": "Kindling", "artist": "Ash", "track": n},
                  audio_hash=scanner.audio_hash)  # fmt: skip
    (music / "Kindling" / "cover.jpg").write_bytes(demo.cover_jpeg(11, 32))
    (music / "Kindling" / "Kindling.cue").write_text('FILE "01 Spark.wav" WAVE\n')
    (music / "Kindling" / "02 Flame.lrc").write_text("[00:01.00]la\n")
    (music / "Kindling" / "notes.nfo").write_text("ripped")
    wav(music / "Ember" / "a.wav", 3, "Ash")
    wav(music / "Ember" / "b.wav", 4, "Coal")
    (music / "Ember" / "cover.jpg").write_bytes(demo.cover_jpeg(12, 32))
    (music / "Playlists").mkdir()
    (music / "Playlists" / "Road Trip.m3u8").write_text("#EXTM3U\n../Kindling/01 Spark.wav\n")
    index = db.Index(str(tmp_path / "musikata.db"))
    with ThreadPoolExecutor(1) as pool:
        scanner.scan(str(music), index, pool, hold=False)
    yield str(music), index
    index.close()


class Trash:
    """The system's trash, as a folder of the test's: what it was given, moved there."""

    def __init__(self, where, refuse=()):
        self.where, self.refuse, self.given = where, set(refuse), []
        os.makedirs(where, exist_ok=True)

    def __call__(self, path):
        self.given.append(path)
        if os.path.basename(path) in self.refuse:
            return False
        shutil.move(path, os.path.join(self.where, os.path.basename(path)))
        return True


def make(music, index, tmp_path, **kw):
    lib = bridges.Library(music, index, str(tmp_path), lambda: ThreadPoolExecutor(1))
    h = ChangeHistory(
        music, index, FakeClock(NOW), lambda: ME, ME, "Laptop", settings.RootTags(),
        executor=ThreadPoolExecutor(1), watching=False, message_ms=60_000,
    )  # fmt: skip
    trash = kw.pop("trash", None) or Trash(str(tmp_path / "Trash"))
    r = Removing(music, index, lib, h, trash, **kw)
    r.lib_, r.history_, r.trash_ = lib, h, trash
    return r


def close(r):
    r.shut()
    r.lib_.close()
    r.history_.close()


def asked(r, qtbot, ask):
    with qtbot.waitSignal(r.changed, timeout=WAIT,
                          check_params_cb=lambda: not r.property("busy")):  # fmt: skip
        ask()
    return r.property("question")


def answered(r, qtbot, yes=True):
    with qtbot.waitSignal(r.history_.messageChanged, timeout=WAIT):
        r.answer(yes)
    return r.history_.property("message")["text"]


def paths(index):
    return sorted(p for (p,) in index.read().execute("SELECT path FROM song"))


def test_an_albums_songs_go_to_the_trash_with_the_files_beside_them_after_asking(
    root, tmp_path, qtbot
):
    """R2.11 from an album's ⋯ menu: asked first, naming the songs; then the songs, their cover,
    cue sheet and lyrics go to the trash, the note that isn't R12.3's stays (so the folder
    does), the rows go at once, and the playlist still names the song, shown missing (R8.7)."""
    music, index = root
    r = make(music, index, tmp_path)
    try:
        (album,) = (
            index.read()
            .execute("SELECT album_id FROM song WHERE path = 'Kindling/01 Spark.wav'")
            .fetchone()
        )
        q = asked(r, qtbot, lambda: r.askAlbum(album))
        assert q["title"] == "Move 2 songs to the trash?"
        assert "02 Flame.lrc, Kindling.cue and cover.jpg beside them go too" in q["detail"]
        text = answered(r, qtbot)
        assert text == f"Moved 2 songs to the trash; {IN_TRASH}"
        assert sorted(os.listdir(r.trash_.where)) == [
            "01 Spark.wav",
            "02 Flame.lrc",
            "02 Flame.wav",
            "Kindling.cue",
            "cover.jpg",
        ]
        assert os.listdir(os.path.join(music, "Kindling")) == ["notes.nfo"]
        assert paths(index) == ["Ember/a.wav", "Ember/b.wav"]
        c = index.read()
        assert c.execute("SELECT 1 FROM folder WHERE path = 'Kindling'").fetchone() is None
        entries = c.execute("SELECT path FROM playlist_entry").fetchall()
        assert entries == [("Kindling/01 Spark.wav",)]
        assert r.property("question") == {}
    finally:
        close(r)


def test_a_folder_goes_whole_and_its_entry_is_kept_but_undo_cant_take_it_back(
    root, tmp_path, qtbot
):
    """R2.11 from Folders' ⋮ menu: "Move the folder Kindling and its 2 songs to the trash?"; the
    folder goes to the trash whole, its songs leave the index at once, the change history keeps
    one entry naming each song, and Undo says it can't take files out of the trash."""
    music, index = root
    r = make(music, index, tmp_path)
    try:
        q = asked(r, qtbot, lambda: r.askFolder("Kindling"))
        assert q["title"] == "Move the folder Kindling and its 2 songs to the trash?"
        answered(r, qtbot)
        assert os.listdir(r.trash_.where) == ["Kindling"]
        assert not os.path.exists(os.path.join(music, "Kindling"))
        assert paths(index) == ["Ember/a.wav", "Ember/b.wav"]
        qtbot.waitUntil(lambda: history.last(index.read()) is not None, timeout=WAIT)
        name = history.last(index.read())
        entry = history.read(history.folder_of(music), name)
        assert entry.action == "trash" and entry.description == (
            "The folder Kindling and its 2 songs to the trash")  # fmt: skip
        assert [(f.path, f.trashed) for f in entry.files] == [
            ("Kindling/01 Spark.wav", True), ("Kindling/02 Flame.wav", True)]  # fmt: skip
        h = r.history_
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            h.undo(name)
        assert h.property("message")["text"] == IN_TRASH
        r.askFolder("")  # the root is never moved to the trash
        assert not r.property("busy")
    finally:
        close(r)


def test_a_song_put_back_from_the_trash_by_hand_has_its_plays_again(root, tmp_path, qtbot):
    """R2.11, A2.8: the plays stay in the root's files keyed by hash, so a song put back by hand
    gets them again at the next scan; the songs beside it stay, and so does their cover."""
    music, index = root
    played(index, {"Ember/a.wav": 3})
    r = make(music, index, tmp_path)
    try:
        lib = r.lib_
        model = lib.property("songs")
        qtbot.waitUntil(lambda: model.rowCount() == 4, timeout=WAIT)
        row = next(i for i in range(model.rowCount()) if model.row(i)["path"] == "Ember/a.wav")
        q = asked(r, qtbot, lambda: r.askRow(model, row))
        assert q["title"] == "Move 1 song to the trash?" and "beside" not in q["detail"]
        answered(r, qtbot)
        assert sorted(os.listdir(os.path.join(music, "Ember"))) == ["b.wav", "cover.jpg"]
        assert "Ember/a.wav" not in paths(index)
        shutil.move(os.path.join(r.trash_.where, "a.wav"), os.path.join(music, "Ember", "a.wav"))
        with ThreadPoolExecutor(1) as pool:
            scanner.scan(music, index, pool, hold=False)
        c = index.read()
        (song,) = c.execute("SELECT id FROM song WHERE path = 'Ember/a.wav'").fetchone()
        assert rootfiles.totals(c, [song]) == {song: 3}
    finally:
        close(r)


def test_delete_in_folders_takes_the_selection_and_cancel_moves_nothing(root, tmp_path, qtbot):
    """R2.11, R6.9: the selection in Folders, a folder whole and a file; Cancel moves nothing.
    A file the trash refuses stays, listed, and the message says which."""
    music, index = root
    r = make(music, index, tmp_path, trash=Trash(str(tmp_path / "Trash"), refuse={"b.wav"}))
    try:
        r.lib_.show("folders")
        view = r.lib_.property("folders")
        model = view.property("model")
        qtbot.waitUntil(lambda: model.rowCount() == 2, timeout=WAIT)
        rows = {model.row(i)["path"]: i for i in range(model.rowCount())}
        model.click(rows["Kindling"], False, False)
        model.click(rows["Ember"], True, False)
        q = asked(r, qtbot, lambda: r.askSelection(model))
        assert q["title"] == "Move 2 folders and their 4 songs to the trash?"
        r.answer(False)
        assert r.property("question") == {} and len(paths(index)) == 4
        view.open("Ember")
        qtbot.waitUntil(lambda: model.rowCount() == 2, timeout=WAIT)
        b = next(i for i in range(model.rowCount()) if model.row(i)["path"] == "Ember/b.wav")
        q = asked(r, qtbot, lambda: r.askRow(model, b))
        assert q["title"] == "Move 1 song to the trash?"
        text = answered(r, qtbot)
        assert text == "Moved 0 of 1 file to the trash: b.wav it couldn't be moved to the trash"
        assert "Ember/b.wav" in paths(index)
    finally:
        close(r)


def test_nothing_moves_while_the_root_isnt_there_or_nothing_is_chosen(root, tmp_path, qtbot):
    """R2.10: nothing goes to the trash, and no folder is ignored, while the root isn't there;
    a question about nothing isn't asked."""
    music, index = root
    there = [False]
    r = make(music, index, tmp_path, available=lambda: there[0])
    try:
        h = r.history_
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            r.askFolder("Kindling")
        assert h.property("message")["text"] == NOT_THERE
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            r.ignoreFolder("Kindling")
        assert h.property("message")["text"] == NOT_IGNORED
        there[0] = True
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            r.askFolder("Nowhere")
        assert h.property("message")["text"] == NOTHING and r.property("question") == {}
    finally:
        close(r)


def test_ignore_this_folder_writes_its_ignore_file_and_its_songs_leave_at_once(
    root, tmp_path, qtbot
):
    """R2.11.1: Ignore this folder, from Folders' ⋮ menu or a folder's right-click menu, writes
    its .musikataignore; the folder and its songs leave the library at once, nothing removed
    from the disk; a rescan leaves them out."""
    music, index = root
    r = make(music, index, tmp_path)
    try:
        h = r.history_
        r.lib_.show("folders")
        model = r.lib_.property("folders").property("model")
        qtbot.waitUntil(lambda: model.rowCount() == 2, timeout=WAIT)
        rows = {model.row(i)["path"]: i for i in range(model.rowCount())}
        assert r.folderAt(model, rows["Kindling"]) == "Kindling"
        assert r.folderAt(r.lib_.property("songs"), 0) == ""
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            r.ignoreRow(model, rows["Kindling"])
        assert h.property("message")["text"] == ignored_text("Kindling", 2)
        assert os.path.exists(os.path.join(music, "Kindling", scanner.IGNORE))
        assert os.path.exists(os.path.join(music, "Kindling", "01 Spark.wav"))
        assert paths(index) == ["Ember/a.wav", "Ember/b.wav"]
        with ThreadPoolExecutor(1) as pool:
            assert scanner.scan(music, index, pool).added == 0
        os.chmod(os.path.join(music, "Ember"), 0o555)
        try:
            with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
                r.ignoreFolder("Ember")
            assert h.property("message")["text"].startswith("Ember couldn't be ignored:")
            assert len(paths(index)) == 2
        finally:
            os.chmod(os.path.join(music, "Ember"), 0o755)
    finally:
        close(r)


def test_a_removal_waits_for_a_scan_that_runs_and_the_scan_finds_nothing_gone(
    root, tmp_path, qtbot
):
    """R2.11, R2.10.1: the removal runs between scans, so a rescan never finds its files half gone
    and asks about them."""
    music, index = root
    r = make(music, index, tmp_path)
    try:
        lib = r.lib_
        asked(r, qtbot, lambda: r.askFolder("Kindling"))
        lib.rescan()
        answered(r, qtbot)
        qtbot.waitUntil(lambda: not lib.property("scanning"), timeout=WAIT)
        assert lib.property("question") == {} and paths(index) == ["Ember/a.wav", "Ember/b.wav"]
    finally:
        close(r)


def test_a_removal_whose_rows_cant_be_taken_out_says_they_stay_listed(tmp_path):
    """R2.11: the files went; when the index can't take them out, the message says the next scan
    will, and the folders left empty are still removed."""
    music = tmp_path / "Music"
    wav(music / "Solo" / "a.wav", 1)
    removal = organize.removal([("Solo/a.wav", None)], {}, {"Solo": ["a.wav"]})

    def broken(_paths):
        raise OSError("the index is locked")

    trash = Trash(str(tmp_path / "Trash"))
    from musikata.removing import remove

    out = remove(str(music), removal, organize.trasher(trash), None, broken)
    assert out.listed and len(out.outcome.saved) == 1
    assert not (music / "Solo").exists()
    assert done_text(removal, out.outcome, out.listed).startswith(
        "Moved 1 song to the trash. They stay listed")  # fmt: skip


def test_the_tour_asks_about_moving_a_folder_to_the_trash_and_closes_the_question(root, tmp_path):
    """A1.6: L14's step asks about Kindling at once, for the shot; a step without it closes the
    question, nothing moved."""
    music, index = root
    r = make(music, index, tmp_path)
    try:
        r.go({"view": "folders", "trash": "Kindling"})
        assert r.property("question")["title"].startswith("Move the folder Kindling and its 2")
        r.go({"view": "songs"})
        assert r.property("question") == {} and len(paths(index)) == 4
        r.go({"view": "folders", "trash": "Nowhere"})
        assert r.property("question") == {}
    finally:
        close(r)


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


def settled(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.window.grabWindow()


def click(shell, item, button=Qt.MouseButton.LeftButton):
    at = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(shell.window, button, Qt.KeyboardModifier(0), at)


@pytest.mark.slow
def test_delete_and_the_menus_ask_in_the_window_with_no_qml_warning(shell, qtbot, qtlog):
    """R2.11 in the window: Delete on the Songs list asks about the selection, its question over
    the window with its text in its boxes, Esc cancelling; a song's right-click menu has Move to
    trash, a folder's in Folders Ignore this folder too, and Folders' ⋮ menu both, in a folder;
    Delete on a playlist's page is still R8.6's."""
    lib, r = shell.library, shell.removing
    lib.show("songs")
    settled(shell, qtbot)
    model = lib.property("songs")
    qtbot.waitUntil(lambda: model.rowCount() == 4, timeout=WAIT)
    model.click(0, False, False)
    view = find(shell, "songs")[0].parentItem().parentItem()
    view.forceActiveFocus()
    with qtbot.waitSignal(r.changed, timeout=WAIT,
                          check_params_cb=lambda: r.property("question") != {}):  # fmt: skip
        QTest.keyClick(shell.window, Qt.Key.Key_Delete)
    settled(shell, qtbot)
    assert find(shell, "copiesQuestion") and r.property("question")["title"] == (
        "Move 1 song to the trash?")  # fmt: skip
    assert layout.faults(shell.window) == []
    QTest.keyClick(shell.window, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: r.property("question") == {}, timeout=WAIT)
    rows = [c for c in find(shell, "songs")[0].property("contentItem").childItems()
            if c.isVisible()]  # fmt: skip
    click(shell, rows[0], Qt.MouseButton.RightButton)
    qtbot.waitUntil(lambda: find(shell, "trashRow") != [], timeout=WAIT)
    assert find(shell, "ignoreFolderRow") == []
    QTest.keyClick(shell.window, Qt.Key.Key_Escape)
    lib.show("folders")
    lib.property("folders").setMode("list")
    settled(shell, qtbot)
    click(shell, find(shell, "folderListRow")[0], Qt.MouseButton.RightButton)
    qtbot.waitUntil(lambda: find(shell, "ignoreFolderRow") != [], timeout=WAIT)
    assert find(shell, "trashRow")
    QTest.keyClick(shell.window, Qt.Key.Key_Escape)
    lib.property("folders").open("Kindling")
    settled(shell, qtbot)
    click(shell, find(shell, "more")[0])
    qtbot.waitUntil(lambda: find(shell, "ignoreFolder") != [], timeout=WAIT)
    assert find(shell, "trashFolder")
    QTest.keyClick(shell.window, Qt.Key.Key_Escape)
    assert [m.message for m in qtlog.records if "qml" in m.message.lower()] == []
