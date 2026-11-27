"""The change history in the running app (src/musikata/history.py, ChangeHistoryPanel.qml,
MessageBar.qml, app.keep_history; R4.9, R4.9.1, R6.7): the root's entries read into the index at
start, old ones removed, another computer's read when the watcher sees them; ⋮ › Change history
listing them by day with their files and computers; Ctrl+Z, the message's Undo and the panel's
undoing an entry or one file, asking first when a file changed since.

Entries are made by the batch every save goes through (history.Recording), on generated files;
nothing saves through the UI until the Edit tags panel (5.4). Tests wait on the signal or state
that says the work is done.

Why: the history is shown and undone from the GUI thread while the reading and writing happen on
a thread of their own; a message that offers an Undo that does nothing, a question that never
comes, or a list that never shows another computer's save leaves the user without their way back."""

import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fakes import FakeClock, fill
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, layout, tour
from musikata import history as history_bridge
from musikata.history import (
    ChangeHistory,
    clock_text,
    computer_text,
    day_text,
    lost_text,
    question_of,
    saved_text,
    undone_text,
    value_text,
    view_rows,
)
from musikata_core import db, scanner, settings, tags
from musikata_core.history import Entry, FileChange, FileUndo, Lost, Plan, Recording, Row
from musikata_core.tags import Batch, Failed, Job, Outcome

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
OTHER = "6f1c0a5e-2b7d-4c1e-9a43-0f2d8e5b7c11"
NOW = datetime(2026, 11, 25, 21, 0, tzinfo=UTC)


# ---------- what the panel, the question and the message say ----------


def row(name, when, computer=ME, action="edit-tags", description="Genre on 2 songs",
        files=(("LD/GH/01.flac", ("genres",)),), count=None, undoes=None):  # fmt: skip
    return Row(name, when, computer, action, description, undoes, files, count or len(files))


def test_days_are_today_yesterday_or_the_date_and_times_are_the_clocks():
    today = datetime(2026, 11, 25, 9, tzinfo=UTC)
    assert day_text(today, today) == "Today"
    assert day_text(today - timedelta(days=1), today) == "Yesterday"
    assert day_text(today - timedelta(days=2), today) == "Monday, November 23, 2026"
    assert clock_text(datetime(2026, 1, 1, 0, 5)) == "12:05 AM"
    assert clock_text(datetime(2026, 1, 1, 12, 0)) == "12:00 PM"
    assert clock_text(datetime(2026, 1, 1, 20, 45)) == "8:45 PM"


def test_each_entry_names_the_computer_that_saved_it():
    """R4.9: each with the computer that saved it, by name where its play file gives one."""
    names = {OTHER: "Studio-PC"}
    assert computer_text(ME, ME, "Laptop", names) == "Laptop"
    assert computer_text(OTHER, ME, "Laptop", names) == "Studio-PC"
    assert computer_text("0123456789", ME, "Laptop", names) == "another computer (01234567)"


def test_the_list_is_by_day_newest_first_with_each_entrys_files_and_computer():
    """R4.9: lists the entries by day, each with the files it touched and its computer."""
    rows = [
        row("c", NOW - timedelta(minutes=15), action="undo", description="", undoes="b"),
        row("b", NOW - timedelta(hours=2), OTHER, files=(("LD/GH/01.flac", ("year", "cover")),
                                                         ("LD/GH/02.flac", ("year",))), count=7),
        row("a", NOW - timedelta(days=1), description=""),
    ]  # fmt: skip
    found = view_rows(rows, {"b"}, NOW, ME, "Laptop", {OTHER: "Studio-PC"}, UTC)
    assert [(r["kind"], r.get("text")) for r in found] == [
        ("day", "Today"), ("entry", "Undo"), ("file", "01.flac"),
        ("entry", "Genre on 2 songs"), ("file", "01.flac"), ("file", "02.flac"),
        ("more", "5 more files"),
        ("day", "Yesterday"), ("entry", "Edited tags"), ("file", "01.flac"),
    ]  # fmt: skip
    assert found[1]["line"] == "8:45 PM · Laptop · 1 file" and found[1]["isUndo"]
    assert found[3]["line"] == "7:00 PM · Studio-PC · 7 files" and found[3]["undone"]
    assert (found[4]["folder"], found[4]["fields"], found[4]["position"]) == (
        "LD/GH",
        "Year, Cover",
        0,
    )
    # in another zone the day turns at its own midnight
    evening = [row("d", NOW - timedelta(hours=3))]
    assert view_rows(evening, set(), NOW, ME, "L", {}, UTC)[0]["text"] == "Today"
    east = view_rows(evening, set(), NOW, ME, "L", {}, timezone(timedelta(hours=5)))
    assert east[0]["text"] == "Yesterday" and east[1]["line"].startswith("11:00 PM")


def test_what_undoing_would_lose_is_said_field_by_field_file_by_file():
    """R4.9.1: shows what would be lost."""
    assert lost_text(Lost("title", "Spring Tide (edit)", "Neap Tide")) == (
        "Title: Spring Tide (edit) → Neap Tide"
    )
    assert lost_text(Lost("genres", ["Ambient", "Dub"], [])) == "Genre: Ambient; Dub → —"
    assert lost_text(Lost("cover", "a" * 64, None)) == "Cover: a cover → no cover"
    assert value_text("rating", 1) == "1 star" and value_text("rating", 4) == "4 stars"
    assert value_text("compilation", True) == "Yes" and value_text("year", None) == "—"
    assert lost_text(Lost("others", ("a" * 64, "b" * 64), ("c" * 64,))) == (
        "Other pictures: 2 other pictures → 1 other picture"
    )
    assert value_text("others", ()) == "no other pictures"
    e = Entry("n", NOW, ME, "edit-tags", "", (
        FileChange("LD/a.flac", None, {"title": "A"}),
        FileChange("LD/b.flac", None, {"title": "B"}),
    ))  # fmt: skip
    changed = FileUndo(e.files[0], "Moved/a.flac", (Lost("title", "X", "A"),))
    q = question_of(Plan(e, (changed, FileUndo(e.files[1], "LD/b.flac"))))
    assert q["title"] == "1 file has changed since this save" and q["skip"]
    assert q["lines"] == [{"file": "a.flac", "lost": "Title: X → A"}]
    assert q["skipText"] == "Undo the other 1 file"
    two = question_of(Plan(e, (changed, FileUndo(e.files[1], "LD/b.flac", changed.lost))))
    assert two["title"] == "2 files changed since this save" and not two["skip"]


def test_the_message_says_what_was_saved_or_undone_and_what_wasnt():
    """R6.7: finished actions are shown in a short-lived message."""
    ok = Outcome(saved=[1, 2, 3, 4])
    assert saved_text(ok) == "Saved 4 files"
    failed = Outcome(
        saved=[1],
        failed=[
            Failed(Job("/m/LD/a.flac", {}), "it is read-only"),
            Failed(Job("/m/b.flac", {}), "it isn't there"),
        ],
    )
    assert saved_text(failed) == "Saved 1 of 3 files: a.flac it is read-only, and 1 more"
    assert undone_text(ok, "Genre on 4 songs") == "Undone: Genre on 4 songs"
    assert undone_text(failed, "x") == "Undid 1 of 3 files: a.flac it is read-only, and 1 more"
    assert undone_text(ok, "x", 1) == "Undone: x (1 file changed since left as it is)"
    assert undone_text(ok, "x", 2).endswith("(2 files changed since left as they are)")


# ---------- the bridge, over real files ----------


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    d = tmp_path_factory.mktemp("made")
    out = []
    for tone in (440, 550):
        path = str(d / f"{tone}.flac")
        demo.encode(path, "flac", 0.2, tone)
        demo.tag(path, demo.Song(path, "flac", {"title": "Neap Tide", "genre": ["Electronica"]}))
        out.append(path)
    return out


@pytest.fixture
def root(made, tmp_path):
    """A root of two songs with an index that has them: (root, index, their paths)."""
    music = tmp_path / "Music"
    (music / "LD").mkdir(parents=True)
    (music / ".musikata").mkdir()
    paths = []
    for n, src in enumerate(made, 1):
        paths.append(str(music / "LD" / f"0{n}.flac"))
        shutil.copyfile(src, paths[-1])
    index = db.Index(str(tmp_path / "musikata.db"))
    fill(index, [{"path": f"LD/0{n}.flac"} for n in (1, 2)])
    yield str(music), index, paths
    index.close()


def save(music, clock, paths, changes, description="Genre on 2 songs", computer=ME):
    rec = Recording(music, lambda: computer, clock)
    write = lambda job: tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)  # noqa: E731
    out = Batch([Job(p, changes) for p in paths], write, record=rec, description=description).run()
    clock.advance(seconds=1)
    return out


@pytest.fixture
def changes(root, qapp, qtbot):
    music, index, paths = root
    clock = FakeClock(NOW)
    saved = []
    h = ChangeHistory(music, index, clock, lambda: ME, ME, "Laptop", settings.RootTags(),
                      saved=saved.append, executor=ThreadPoolExecutor(1), zone=UTC,
                      message_ms=60_000)  # fmt: skip
    h.clock_, h.saved_ = clock, saved
    yield h
    h.close()


def started(h, qtbot):
    with qtbot.waitSignal(h.changed, timeout=WAIT):
        h.start()
    qtbot.waitUntil(lambda: not h.property("loading"), timeout=WAIT)


def entries(h):
    return [(r["text"], r["undone"]) for r in h.property("rows") if r["kind"] == "entry"]


@pytest.mark.slow
def test_at_start_the_entries_are_listed_other_computers_by_name_and_new_ones_when_seen(
    root, changes, qtbot
):
    """R4.9: a save made on one computer can be undone on another; the watcher reads new entries."""
    music, index, paths = root
    h = changes
    os.makedirs(os.path.join(music, ".musikata", OTHER))
    with open(os.path.join(music, ".musikata", OTHER, "plays.json"), "w") as f:
        json.dump({"format": 1, "computer": {"id": OTHER, "name": "Studio-PC"}, "songs": []}, f)
    save(music, h.clock_, paths[:1], {"title": "Spring Tide"}, "Title on 1 song", OTHER)
    started(h, qtbot)
    assert entries(h) == [("Title on 1 song", False)]
    assert "Studio-PC" in h.property("rows")[1]["line"]
    assert h.property("countText") == "1 save"
    save(music, h.clock_, paths, {"genres": ["Ambient"]})  # another save lands: the watch sees it
    # the watch gathers for a second (A2.4) of the clock it is given, moved on as the test waits
    qtbot.waitUntil(lambda: h.clock_.advance(seconds=1) or len(entries(h)) == 2, timeout=WAIT)
    assert entries(h)[0] == ("Genre on 2 songs", False)


def test_ctrl_z_undoes_the_most_recent_save_and_the_messages_undo_redoes_it(root, changes, qtbot):
    """R4.9: Ctrl+Z puts back the most recent entry; Undo in the message that follows does too."""
    music, index, paths = root
    h = changes
    save(music, h.clock_, paths, {"genres": ["Ambient"]})
    started(h, qtbot)
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        h.undoLast()
    assert all(tags.read(p)[0].genres == ("Electronica",) for p in paths)
    assert h.property("message")["text"] == "Undone: Genre on 2 songs"
    assert [os.path.basename(w.path) for w in h.saved_[0]] == ["01.flac", "02.flac"]
    assert entries(h) == [("Undo: Genre on 2 songs", False), ("Genre on 2 songs", True)]
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT, check_params_cb=lambda: True):
        h.undoMessage()  # the undo undone: a redo
    qtbot.waitUntil(lambda: h.property("message").get("text", "").startswith("Undone: Undo"),
                    timeout=WAIT)  # fmt: skip
    assert all(tags.read(p)[0].genres == ("Ambient",) for p in paths)
    h.dismiss()
    assert h.property("message") == {}
    h.undoLast()  # the save is in effect again: Ctrl+Z goes back to it
    qtbot.waitUntil(lambda: tags.read(paths[0])[0].genres == ("Electronica",), timeout=WAIT)


def test_an_entrys_files_past_the_first_are_counted_until_it_is_opened_whole(
    root, changes, qtbot, monkeypatch
):
    """R4.9's Change history: an entry lists its first files and how many more; opened, all of
    them. A tour's step opens the panel and the next closes it."""
    monkeypatch.setattr(history_bridge, "FILES", 1)
    music, index, paths = root
    h = changes
    save(music, h.clock_, paths, {"genres": ["Ambient"]})
    started(h, qtbot)

    def listed():
        return [(r["kind"], r["text"]) for r in h.property("rows") if r["kind"] in ("file", "more")]

    assert listed() == [("file", "01.flac"), ("more", "1 more file")]
    (name,) = [r["name"] for r in h.property("rows") if r["kind"] == "more"]
    h.expand(name)
    assert listed() == [("file", "01.flac"), ("file", "02.flac")]
    h.go({"history": True})
    assert h.property("opened")
    h.go({"view": "albums"})
    assert not h.property("opened")


def test_nothing_to_undo_says_so(changes, qtbot):
    started(changes, qtbot)
    changes.undoLast()
    assert changes.property("message")["text"] == "Nothing to undo"
    changes.undoMessage()  # no entry: nothing happens
    assert not changes.property("busy")


def test_while_the_root_isnt_there_undo_changes_no_file_and_says_why(root, qapp, qtbot):
    """R2.10: while the root can't be reached, every change to files is unavailable, saying why:
    Undo too, from Ctrl+Z, the panel or a file's own undo."""
    music, index, paths = root
    clock = FakeClock(NOW)
    there = [True]
    h = ChangeHistory(music, index, clock, lambda: ME, ME, "Laptop", settings.RootTags(),
                      executor=ThreadPoolExecutor(1), zone=UTC, message_ms=60_000,
                      available=lambda: there[0])  # fmt: skip
    try:
        name = save(music, clock, paths, {"genres": ["Ambient"]}).entry
        started(h, qtbot)
        there[0] = False
        for undo in (h.undoLast, lambda: h.undo(name), lambda: h.undoFile(name, 0)):
            h.dismiss()
            undo()
            assert h.property("message")["text"] == history_bridge.NOT_THERE
            assert not h.property("busy")
        assert all(tags.read(p)[0].genres == ("Ambient",) for p in paths)
    finally:
        h.close()


def test_a_file_changed_since_asks_first_and_the_answer_decides(root, changes, qtbot):
    """R4.9.1: undoing a file that has changed since asks first, and shows what would be lost."""
    music, index, paths = root
    h = changes
    out = save(music, h.clock_, paths, {"title": "Spring Tide"})
    tags.save(paths[1], {"title": "Slack Water"}, audio_hash=scanner.audio_hash)
    started(h, qtbot)

    def ask():
        with qtbot.waitSignal(h.questionChanged, timeout=WAIT):
            h.undo(out.entry)
        return h.property("question")

    q = ask()
    assert q["lines"] == [{"file": "02.flac", "lost": "Title: Slack Water → Neap Tide"}]
    assert h.property("opened") and h.property("busy")
    h.answer("cancel")
    assert not h.property("busy") and h.property("question") == {}
    assert tags.read(paths[0])[0].title == "Spring Tide"
    ask()
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        h.answer("skip")
    assert [tags.read(p)[0].title for p in paths] == ["Neap Tide", "Slack Water"]
    assert "1 file changed since left as it is" in h.property("message")["text"]
    ask()
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        h.answer("overwrite")
    assert [tags.read(p)[0].title for p in paths] == ["Neap Tide", "Neap Tide"]
    h.answer("overwrite")  # no question open: nothing


def test_one_file_of_an_entry_is_undone_alone(root, changes, qtbot):
    """R4.9: undoes any entry file by file."""
    music, index, paths = root
    h = changes
    out = save(music, h.clock_, paths, {"title": "Spring Tide"})
    started(h, qtbot)
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        h.undoFile(out.entry, 1)
    assert [tags.read(p)[0].title for p in paths] == ["Spring Tide", "Neap Tide"]
    assert entries(h)[0][0] == "Undo: Genre on 2 songs (1 of 2 files)"
    h.undo(out.entry)
    h.undo(out.entry)  # one undo at a time: the second waits for another try
    qtbot.waitUntil(lambda: not h.property("busy"), timeout=WAIT)


def test_an_entry_that_cant_be_read_says_so(root, changes, qtbot):
    music, index, paths = root
    started(changes, qtbot)
    with qtbot.waitSignal(changes.messageChanged, timeout=WAIT):
        changes.undo(f"20261125T204512000Z-{ME}.json")
    assert changes.property("message")["text"].startswith("This change can't be undone")


def test_with_the_history_off_saves_record_nothing_and_the_panel_says_so(root, qtbot, qapp):
    """R13.3: Keep a history of tag changes, off."""
    music, index, paths = root
    off = settings.RootTags(history=False)
    h = ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop", off,
                      executor=ThreadPoolExecutor(1), watching=False)  # fmt: skip
    try:
        assert h.recording() is None
        started(h, qtbot)
        assert h.property("emptyText") == "The history of tag changes is off for this music folder"
        assert isinstance(ChangeHistory(music, index, FakeClock(), lambda: ME, ME, "L",
                                        settings.RootTags()).recording(), Recording)  # fmt: skip
    finally:
        h.close()


def test_a_saves_message_offers_undo_when_it_made_an_entry_and_goes_on_its_own(root, qtbot, qapp):
    """R6.7: a short-lived message; one about a save carries Undo (R4.9)."""
    music, index, paths = root
    h = ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop",
                      settings.RootTags(), executor=ThreadPoolExecutor(1), watching=False,
                      message_ms=10)  # fmt: skip
    try:
        h.after_save(Outcome(saved=[1, 2], entry="n.json"))
        assert h.property("message") == {"text": "Saved 2 files", "undo": "n.json"}
        qtbot.waitUntil(lambda: h.property("message") == {}, timeout=WAIT)
        h.after_save(Outcome(saved=[1]))
        assert h.property("message")["undo"] == ""
    finally:
        h.close()


# ---------- the window ----------


@pytest.fixture
def shell(made, tmp_path, qapp):
    """MusiKata over a root of two songs with two saves in its history, one another computer's."""
    music = tmp_path / "Music"
    (music / "LD").mkdir(parents=True)
    paths = []
    for n, src in enumerate(made, 1):
        paths.append(str(music / "LD" / f"0{n}.flac"))
        shutil.copyfile(src, paths[-1])
    clock = FakeClock(datetime.now(UTC) - timedelta(minutes=5))
    save(str(music), clock, paths, {"genres": ["Ambient"]}, "Genre on 2 songs", OTHER)
    save(str(music), clock, paths[:1], {"title": "Spring Tide"}, "Title on 1 song", ME)
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(music), env, FakeClock(datetime.now(UTC)), lambda: ThreadPoolExecutor(1))
    s.paths_ = paths
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


@pytest.mark.slow
def test_the_change_history_panel_lists_the_saves_and_undoes_one_with_no_qml_warning(
    shell, qtbot, qtlog
):
    """R4.9: ⋮ › Change history lists the entries by day, each with its files and computer, and
    undoes any of them file by file; Ctrl+Z undoes the most recent; the message carries Undo."""
    h = shell.changes
    qtbot.waitUntil(lambda: len(entries(h)) == 2 and not h.property("loading"), timeout=WAIT)
    shell.library.show("songs")
    menu = find(shell, "more")[0]
    click(shell, menu)
    qtbot.waitUntil(lambda: bool(find(shell, "changeHistory")), timeout=WAIT)
    click(shell, find(shell, "changeHistory")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "historyPanel")), timeout=WAIT)
    qtbot.waitUntil(lambda: len(find(shell, "undoEntry")) == 2, timeout=WAIT)
    shell.window.grabWindow()
    assert len(find(shell, "undoFile")) == 3
    assert layout.faults(shell.window) == []
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        click(shell, find(shell, "undoFile")[0])  # the newest save's one file
    assert tags.read(shell.paths_[0])[0].title == "Neap Tide"
    qtbot.waitUntil(lambda: bool(find(shell, "messageUndo")), timeout=WAIT)
    shell.window.grabWindow()
    assert layout.faults(shell.window) == []
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        click(shell, find(shell, "messageUndo")[0])  # redone
    qtbot.waitUntil(lambda: tags.read(shell.paths_[0])[0].title == "Spring Tide", timeout=WAIT)
    qtbot.waitUntil(lambda: not h.property("busy"), timeout=WAIT)
    shell.window.requestActivate()
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        QTest.keyClick(shell.window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: tags.read(shell.paths_[0])[0].title == "Neap Tide", timeout=WAIT)
    click(shell, find(shell, "closeHistory")[0])
    assert not h.property("opened")
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert not tour.loading(shell.window.contentItem())
