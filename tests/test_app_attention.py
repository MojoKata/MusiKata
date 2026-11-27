"""Needs attention in the running app (src/musikata/attention.py; R2.8, L09-needs-attention): the
chips and groups, the count in the sidebar, each entry's action (Edit tags, Album art, Merge, Show
in folder) and Ignore kept in the root's ignored.json; and the Merge of an artist's or an album's
names through the preview, the batch and the change history.

Why: the view is where MusiKata says what it can help fix; its count must be what is there now, an
action must reach the tool that fixes its entry, a dismissal must hold until the file changes (on
every computer sharing the root), and a merge must show the files it changes before it writes
them, as one entry Undo puts back."""

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeClock, fill, wav
from PySide6.QtCore import QObject, QPointF, Qt, Slot
from PySide6.QtTest import QTest

from musikata import app, bridges, layout, tour
from musikata import attention as attention_app
from musikata.attention import (
    GROUPS,
    Attention,
    AttentionModel,
    NameMerge,
    chips_of,
    count_text,
    entry_row,
    group_row,
    matches,
    reveal_command,
    rows_of,
    short_of,
    spellings_text,
    summary_text,
    words_of,
)
from musikata.history import ChangeHistory
from musikata_core import attention, db, rootfiles, scanner, settings, tags
from musikata_core.attention import Entry
from musikata_core.clock import SystemClock

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
NOW = datetime(2026, 11, 26, 21, 0, tzinfo=UTC)
H1 = "1" * 64
BY = {g.key: g for g in GROUPS}


def history_of(music, index):
    return ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop",
                         settings.RootTags(), executor=ThreadPoolExecutor(1), watching=False,
                         message_ms=60_000)  # fmt: skip


# ---------- what an entry, a group and a chip say ----------


def test_each_entry_says_what_it_is_and_has_the_action_that_fixes_it_then_ignore():
    """R2.8's list, in L09's words."""
    none = entry_row(Entry("cover-none", "MO/K", "Kindling", "Mara Okafor", 3))
    assert (none["title"], none["detail"], none["icon"]) == ("Kindling", "Mara Okafor · No cover",
                                                              "album")  # fmt: skip
    assert [a["name"] for a in none["actions"]] == ["art", "ignore"] and none["group"] == "covers"
    small = entry_row(Entry("cover-small", "MO/SE", "Salt & Ember", "", 4, thumb="t", width=300,
                            height=300))  # fmt: skip
    assert small["detail"] == "Unknown artist · Cover 300 × 300"
    assert small["cover"] == "image://covers/t"
    artist = entry_row(Entry("names-artist", "Lumen Drift", "Lumen Drift",
                             names=("Lumen Drift", "lumen drift"), counts=(12, 3)))  # fmt: skip
    assert artist["detail"] == "Artist · Lumen Drift (12), lumen drift (3)"
    assert [a["label"] for a in artist["actions"]] == ["Merge…", "Ignore"]
    album = entry_row(Entry("names-album", "Glass Harbor", "Glass Harbor", "Lumen Drift",
                            names=("Glass Harbor", "glass harbor"), counts=(9, 1)))  # fmt: skip
    assert album["detail"] == "Album by Lumen Drift · Glass Harbor (9), glass harbor (1)"
    genre = entry_row(Entry("names-genre", "Electronic", "Electronic",
                            names=("Electronic", "electronic"), counts=(1214, 6)))  # fmt: skip
    assert genre["detail"] == "Genre · Electronic (1,214), electronic (6)"
    assert genre["icon"] == "genre" and genre["group"] == "names"
    differs = entry_row(Entry("album-differs", "LD/TT", "Tide Tables", "Lumen Drift", 5,
                              fields=("albumartist", "year", "genre")))  # fmt: skip
    assert differs["detail"] == "Lumen Drift · Its songs' album artist, year and genre differ"
    assert [a["name"] for a in differs["actions"]] == ["edit", "art", "ignore"]
    live = entry_row(Entry("album-in-one-file", "MO/Live/Live.mp3", "Live at the Lantern",
                           "Mara Okafor", cue="Live.cue", length=3725.0))  # fmt: skip
    assert live["detail"] == "Mara Okafor · 1:02:05 in one file, with Live.cue"
    assert [a["name"] for a in live["actions"]] == ["ignore"]  # its note, no action (#3)
    broken = entry_row(Entry("unreadable", "MO/broken.mp3", "MO/broken.mp3", error="can't sync"))
    assert (broken["detail"], broken["tone"], broken["cover"]) == ("can't sync", "err", "")
    assert [a["name"] for a in broken["actions"]] == ["folder", "ignore"]


def test_a_groups_line_counts_it_and_names_its_first_entries():
    """L09-needs-attention: "1 album · Live at the Lantern (Mara Okafor), with a .cue"."""
    live = Entry("album-in-one-file", "MO/Live/Live.mp3", "Live at the Lantern", "Mara Okafor")
    assert summary_text(BY["one-file"], [live]) == (
        "1 album · Live at the Lantern (Mara Okafor), with a .cue"
    )
    assert short_of(Entry("album-in-one-file", "x/Live.mp3")) == "Live.mp3, with a .cue"
    assert short_of(Entry("unreadable", "MO/broken.mp3", "MO/broken.mp3")) == "broken.mp3"
    albums = [Entry("cover-none", f"A/{n}", f"Album {n}") for n in range(5)]
    assert summary_text(BY["covers"], albums) == "5 albums · Album 0, Album 1, Album 2, 2 more"
    row = group_row(BY["covers"], albums, False)
    assert (row["title"], row["count"], row["open"]) == ("Covers", 5, False)
    assert row["detail"] == "NO COVER, OR A SMALL ONE" and row["note"]
    assert row["actions"] == [{"name": "online", "label": "Find covers online",
                               "later": attention_app.ONLINE_LATER}]  # fmt: skip
    assert group_row(BY["names"], albums, True)["actions"] == []


def test_the_chips_count_their_groups_and_other_holds_those_with_no_chip_of_their_own():
    chips = chips_of({"covers": 4, "names": 2, "albums": 1, "unreadable": 2}, "names")
    assert [(c["name"], c["label"], c["chosen"]) for c in chips] == [
        ("all", "All  9", False), ("covers", "Covers  4", False), ("names", "Names  2", True),
        ("other", "Other  3", False),
    ]  # fmt: skip
    assert [c["name"] for c in chips_of({}, "covers")] == ["all", "covers"]  # chosen: kept


def test_the_count_says_how_many_to_look_at():
    assert count_text(23, 23, False) == "23 to look at"
    assert count_text(3, 1023, True) == "3 of 1,023 to look at"
    assert count_text(0, 0, False) == "Nothing to look at"
    assert spellings_text(["A", "a"], [1200, 1]) == "A (1,200), a (1)"


def test_all_folds_every_group_and_a_chip_opens_its_groups_first():
    """L09: the chip chosen open at the top, the others folded after it; a group's line the other
    way."""
    entries = [
        Entry("cover-none", "a"),
        Entry("names-genre", "G", names=("G", "g")),
        Entry("album-in-one-file", "b"),
        Entry("unreadable", "c"),
        Entry("cover-small", "d"),
    ]
    assert rows_of(entries, "all", ()) == [("group", "covers", -1), ("group", "names", -1),
                                           ("group", "one-file", -1),
                                           ("group", "unreadable", -1)]  # fmt: skip
    assert rows_of(entries, "names", ()) == [
        ("group", "names", -1), ("entry", "names", 1), ("group", "covers", -1),
        ("group", "one-file", -1), ("group", "unreadable", -1),
    ]  # fmt: skip
    assert rows_of(entries, "other", {"covers", "unreadable"})[:4] == [
        ("group", "unreadable", -1), ("group", "covers", -1), ("entry", "covers", 0),
        ("entry", "covers", 4),
    ]  # fmt: skip
    assert rows_of([], "all", ()) == []


def test_a_search_keeps_the_entries_it_finds_case_and_accents_aside():
    e = Entry("names-artist", "Beyoncé", "Beyoncé", names=("Beyoncé", "beyoncé"), counts=(1, 1))
    assert matches(e, words_of("BEYONCE")) and matches(e, words_of("artist beyonce"))
    assert not matches(e, words_of("beyonce jazz")) and matches(e, [])


def test_show_in_folder_asks_each_platforms_file_manager_to_select_the_file():
    """R2.8: Explorer's /select, Finder's reveal, the desktop's file manager over D-Bus; with none,
    the folder is opened."""
    assert reveal_command("C:\\M\\a.mp3", "win32", bool) == ["explorer", "/select,C:\\M\\a.mp3"]
    assert reveal_command("/M/a.mp3", "darwin", bool) == ["open", "-R", "/M/a.mp3"]
    linux = reveal_command("/M/a b.mp3", "linux", lambda name: name == "dbus-send")
    assert linux[0] == "dbus-send" and "array:string:file:///M/a b.mp3" in linux
    assert "org.freedesktop.FileManager1.ShowItems" in linux
    assert reveal_command("/M/a.mp3", "linux", lambda name: None) is None


def test_a_file_manager_that_fails_or_cant_start_is_logged_and_the_folder_opened_instead(
    monkeypatch, caplog
):
    """R2.8's Show in folder runs its command to the end: one that can't be started, or that says
    it failed, is logged and its folder is opened instead; Explorer says 1 when it worked."""
    ran = []

    def answering(code=0, error=None):
        def run(command, **_kw):
            ran.append(command)
            if error is not None:
                raise error
            return subprocess.CompletedProcess(command, code, b"", b"no FileManager1")

        return run

    monkeypatch.setattr(attention_app.subprocess, "run", answering(0))
    assert attention_app._run(["dbus-send", "--session"]) is True
    monkeypatch.setattr(attention_app.subprocess, "run", answering(1))
    assert attention_app._run(["explorer", "/select,a"]) is (sys.platform in ("win32", "darwin"))
    monkeypatch.setattr(attention_app.subprocess, "run", answering(error=OSError("not found")))
    assert attention_app._run(["dbus-send"]) is False
    assert "couldn't show the file in its folder: not found" in caplog.text
    assert len(ran) == 3


# ---------- the list in the library ----------

SONGS = [
    {"path": "LD/GH/01.flac", "title": "Tidewater", "artist": "Lumen Drift",
     "album": "Glass Harbor", "albumartist": "Lumen Drift", "genres": ("Electronic",),
     "year": 2019},
    {"path": "LD/GH/02.flac", "title": "Glass", "artist": "lumen drift", "album": "Glass Harbor",
     "albumartist": "Lumen Drift", "genres": ("Electronic",), "year": 2020},
    {"path": "MO/K/01.flac", "title": "Kindling", "artist": "Mara Okafor", "album": "Kindling",
     "genres": ("Soul",)},
]  # fmt: skip


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


@pytest.fixture
def lib(index, tmp_path, qapp, qtbot):
    fill(index, SONGS)
    library = bridges.Library(str(tmp_path / "Music"), index, str(tmp_path), ThreadPoolExecutor)
    yield library
    library.close()


def titles(model):
    return [(model.row(i)["type"], model.row(i)["title"]) for i in range(model.rowCount())]


def test_needs_attention_opens_from_the_sidebar_with_its_count_and_chips(lib, qtbot):
    """R2.8: the view and its count in the sidebar; its header says how many to look at."""
    model = lib.property("attention")
    assert lib.property("attentionCount") == "4"  # 2 covers, a name, Glass Harbor's year
    lib.show("attention")
    assert lib.property("title") == "Needs attention" and lib.property("section") == "attention"
    assert lib.property("viewCount") == "4 to look at"
    assert lib.property("searchHint") == "Search these" and lib.property("sorts") == []
    assert titles(model) == [("group", "Covers"), ("group", "Names"),
                             ("group", "Albums that differ")]  # fmt: skip
    assert [c["label"] for c in model.property("chips")] == ["All  4", "Covers  2", "Names  1",
                                                             "Other  1"]  # fmt: skip
    model.choose("covers")
    assert titles(model)[:3] == [("group", "Covers"), ("entry", "Glass Harbor"),
                                 ("entry", "Kindling")]  # fmt: skip
    assert model.property("chip") == "covers" and model.row(0)["open"]
    model.toggle("covers")
    assert len(titles(model)) == 3
    model.toggle("names")
    assert titles(model)[1:3] == [("group", "Names"), ("entry", "Lumen Drift")]
    roles = {bytes(v).decode(): k for k, v in model.roleNames().items()}
    assert model.data(model.index(2), roles["detail"]).startswith("Artist · Lumen Drift (2)")
    assert (
        model.data(model.index(99), roles["title"]) is None
        and model.data(model.index(0), 0) is None
    )
    assert model.entry_at(0) is None and model.entry_at(2).kind == "names-artist"
    with pytest.raises(ValueError, match="no such chip"):
        model.choose("dupes")


def test_a_search_keeps_the_entries_whose_words_it_finds(lib):
    """R2.7 in Needs attention: "1 of 4 to look at"; one that finds none says so."""
    lib.show("attention")
    model = lib.property("attention")
    model.choose("all")
    lib.setSearch("kindling")
    assert lib.property("viewCount") == "1 of 4 to look at"
    assert (
        titles(model) == [("group", "Covers")] and model.row(0)["summary"] == "1 album · Kindling"
    )
    lib.setSearch("zebra")
    assert lib.property("emptyText") == "No entries match “zebra”"
    lib.show("attention")  # anew: its search gone
    assert lib.property("viewCount") == "4 to look at"


def test_with_nothing_to_look_at_the_view_says_so_and_the_sidebar_shows_no_count(
    index, tmp_path, qapp
):
    fill(index, [{"path": "A/1.flac", "title": "One", "album": "A", "artist": "X",
                  "has_cover": True}])  # fmt: skip
    library = bridges.Library(str(tmp_path / "Music"), index, str(tmp_path), ThreadPoolExecutor)
    try:
        index.write(lambda c: c.execute("UPDATE album SET cover = 'A/1.flac'")).result()
        library.reload()
        library.show("attention")
        assert library.property("attentionCount") == ""
        assert library.property("emptyText") == "Nothing needs attention"
        assert library.property("viewCount") == "Nothing to look at"
    finally:
        library.close()


def test_a_large_librarys_entries_come_from_the_search_thread(index, qapp, qtbot, monkeypatch):
    """A1.3: found off the GUI thread; until they come, the list shows what it had."""
    fill(index, SONGS)
    monkeypatch.setattr(attention_app, "SHORT", 1)
    model = AttentionModel(index.read)
    assert model.property("loading") and model.rowCount() == 0
    model.refresh()
    assert model.pending()
    qtbot.waitUntil(lambda: not model.pending(), timeout=WAIT)
    assert model.total() == 4 and not model.property("loading")
    model.refresh()
    model.refresh()  # the first's result, superseded, is passed by
    qtbot.waitUntil(lambda: not model.pending(), timeout=WAIT)
    assert model.total() == 4 and not model.filtered() and model.shown_search() == ""
    model.show_ratings({})
    model.wait()


# ---------- the actions ----------


class Tools(QObject):
    """The Edit tags panel, Album art, the genres' merge and the names' merge, as the actions
    call them: what each was asked, in order."""

    def __init__(self):
        super().__init__()
        self.asked = []

    @Slot(int, QObject)
    def editAlbum(self, album, model):  # noqa: N802
        self.asked.append(("edit", album, model))

    @Slot(int)
    def openAlbum(self, album):  # noqa: N802
        self.asked.append(("art", album))

    def merge_names(self, names):
        self.asked.append(("genres", names))

    def open(self, entry):
        self.asked.append(("names", entry.names))


@pytest.fixture
def root(tmp_path, index):
    """A root with a song that couldn't be read and one album with no cover, scanned."""
    music = tmp_path / "Music"
    (music / ".musikata").mkdir(parents=True)
    (music / "MO").mkdir()
    (music / "MO" / "broken.mp3").write_bytes(b"not an mp3")
    wav(music / "MO" / "K" / "01.wav", 1, "Kindling")
    with ThreadPoolExecutor(1) as pool:
        scanner.scan(str(music), index, pool, hold=False)
    fill(index, SONGS[:2])
    return str(music)


def make(root, index, clock=None, **kw):
    model = AttentionModel(index.read)
    tools = Tools()
    runs, folders = [], []
    defaults = dict(edit=tools, art=tools, genres=tools, names=tools, watching=False,
                    executor=ThreadPoolExecutor(1), reveal=lambda p: ["show", p],
                    run=lambda c: runs.append(c) or c[1].endswith(".mp3"),
                    open_folder=folders.append)  # fmt: skip
    needs = Attention(root, index, model, clock or FakeClock(NOW), **{**defaults, **kw})
    needs.tools_, needs.runs_, needs.folders_ = tools, runs, folders
    model.refresh()
    return needs, model


def row_of(model, kind):
    model.choose("all")
    for g in GROUPS:
        model.toggle(g.key)
    return next(i for i in range(model.rowCount())
                if model.entry_at(i) is not None and model.entry_at(i).kind == kind)  # fmt: skip


def test_each_action_reaches_the_tool_that_fixes_its_entry(root, index, qtbot):
    """R2.8: Edit tags and Album art on the album, Merge on the genres' or the names' merge, Show
    in folder through the file manager, its folder opened when that fails."""
    needs, model = make(root, index)
    try:
        differs = row_of(model, "album-differs")
        album = model.entry_at(differs).album
        needs.act(differs, "edit")
        needs.act(differs, "art")
        needs.act(row_of(model, "names-artist"), "merge")
        needs.act(row_of(model, "unreadable"), "folder")
        needs.act(-1, "edit")  # no entry there: nothing
        assert needs.tools_.asked == [("edit", album, None), ("art", album),
                                      ("names", ("Lumen Drift", "lumen drift"))]  # fmt: skip
        qtbot.waitUntil(lambda: needs.runs_ != [], timeout=WAIT)
        assert needs.runs_ == [["show", os.path.join(root, "MO", "broken.mp3")]]
        needs.show_in_folder(os.path.join(root, "MO", "K", "01.wav"))  # the run fails: its folder
        qtbot.waitUntil(lambda: needs.folders_ != [], timeout=WAIT)
        assert needs.folders_ == [os.path.join(root, "MO", "K")]
        with pytest.raises(ValueError, match="no such action"):
            needs.act(differs, "trash")
        fill(index, [{"path": "X/1.flac", "title": "x", "genres": ("soul",)},
                     {"path": "X/2.flac", "title": "y", "genres": ("Soul",)},
                     {"path": "X/3.flac", "title": "z", "genres": ("Soul",)}])  # fmt: skip
        model.refresh()
        needs.act(row_of(model, "names-genre"), "merge")
        assert needs.tools_.asked[-1] == ("genres", ["Soul", "soul"])
    finally:
        needs.close()


def test_ignore_keeps_the_entry_dismissed_in_ignored_json_until_its_file_changes(
    root, index, qtbot
):
    """R2.8, A2.8: the dismissal is written into the root's ignored.json and the index; the entry
    goes; a change to the file brings it back."""
    needs, model = make(root, index)
    try:
        before = model.total()
        row = row_of(model, "unreadable")
        with qtbot.waitSignal(model.countChanged, timeout=WAIT):
            needs.act(row, "ignore")
        assert model.total() == before - 1
        assert not any(model.entry_at(i) and model.entry_at(i).kind == "unreadable"
                       for i in range(model.rowCount()))  # fmt: skip
        with open(rootfiles.ignored_of(root), encoding="utf-8") as f:
            doc = json.load(f)
        assert [(e["kind"], e["about"], e["changed"]) for e in doc["entries"]] == [
            ("unreadable", "MO/broken.mp3", "2026-11-26T21:00:00Z")
        ]
        # the file changed (a scan reads its new modification time): the entry comes back
        index.write(lambda c: c.execute(
            "UPDATE song SET mtime_ns = mtime_ns + 1000000000 WHERE path = 'MO/broken.mp3'"
        )).result()  # fmt: skip
        model.refresh()
        assert model.total() == before
    finally:
        needs.close()


def test_a_dismissal_where_musikata_cant_be_written_is_kept_in_the_index(root, index, qtbot):
    """R1.5.2: the index only, the log says so."""
    shutil.rmtree(os.path.join(root, ".musikata"))
    needs, model = make(root, index)
    try:
        before = model.total()
        row = row_of(model, "cover-none")
        with qtbot.waitSignal(model.countChanged, timeout=WAIT):
            needs.act(row, "ignore")
        assert model.total() == before - 1 and rootfiles.dismissals(index.read())
    finally:
        needs.close()


def test_a_dismissal_that_cant_be_kept_says_why(root, index, qtbot):
    """A2.10: a newer MusiKata's ignored.json is never written: the entry stays, and why shows."""
    with open(rootfiles.ignored_of(root), "w", encoding="utf-8") as f:
        json.dump({"format": 2, "entries": []}, f)
    h = history_of(root, index)
    needs, model = make(root, index, history=h)
    try:
        before = model.total()
        row = row_of(model, "cover-none")
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            needs.act(row, "ignore")
        assert h.property("message")["text"].startswith("It wasn't ignored: the music folder's")
        assert model.total() == before
    finally:
        needs.close()
        h.close()


@pytest.mark.slow
def test_ignored_json_is_read_at_start_and_again_when_another_computer_changes_it(
    root, index, qtbot
):
    """A2.8: another computer's dismissals are read into the index at start, and again once the
    watcher sees the file change."""

    def another(entries):
        with open(rootfiles.ignored_of(root), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "entries": entries}, f)

    another([{"kind": "cover-none", "about": "LD/GH", "changed": "2026-11-26T10:00:00Z"}])
    needs, model = make(root, index, watching=True, clock=SystemClock())
    try:
        before = model.total()
        needs.start()
        qtbot.waitUntil(lambda: model.total() == before - 1, timeout=WAIT)
        qtbot.waitUntil(lambda: "" in needs._watcher.known(), timeout=WAIT)
        another([{"kind": "cover-none", "about": "LD/GH", "changed": "2026-11-26T10:00:00Z"},
                 {"kind": "unreadable", "about": "MO/broken.mp3", "changed": T2}])  # fmt: skip
        qtbot.waitUntil(lambda: model.total() == before - 2, timeout=WAIT)
    finally:
        needs.close()


T2 = "2026-11-26T11:00:00Z"


def test_the_tour_chooses_a_chip(root, index):
    needs, model = make(root, index)
    try:
        needs.go({"view": "attention", "attention": "names"})
        assert model.property("chip") == "names"
        needs.go({"view": "albums"})
        assert model.property("chip") == "names"
    finally:
        needs.close()


# ---------- Merge for an artist's or an album's names ----------


@pytest.fixture
def named(tmp_path):
    """Three WAVs of Glass Harbor, one with its artist and album spelled in lower case, scanned:
    (root, index, paths)."""
    import mutagen.id3
    import mutagen.wave

    music = tmp_path / "Music"
    (music / ".musikata").mkdir(parents=True)
    paths = []
    for n, (artist, album) in enumerate((("Lumen Drift", "Glass Harbor"),
                                         ("lumen drift", "glass harbor"),
                                         ("Lumen Drift", "Glass Harbor")), 1):  # fmt: skip
        path = music / "LD" / f"{n:02d}.wav"
        wav(path, n, f"Song {n}")
        f = mutagen.wave.WAVE(str(path))
        f.tags.add(mutagen.id3.TPE1(encoding=3, text=artist))
        f.tags.add(mutagen.id3.TALB(encoding=3, text=album))
        f.save()
        paths.append(str(path))
    index = db.Index(str(tmp_path / "musikata.db"))
    with ThreadPoolExecutor(1) as pool:
        scanner.scan(str(music), index, pool, hold=False)
    yield str(music), index, paths
    index.close()


def merger(music, index, write=None, available=lambda: True):
    h = history_of(music, index)

    def save_rows(written):
        index.write(lambda c: scanner.wrote(c, music, list(written))).result()

    def write_file(job):
        return tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)

    m = NameMerge(music, index.read, write or write_file, h, saved=save_rows,
                  executor=ThreadPoolExecutor(1), available=available)  # fmt: skip
    m.history_ = h
    return m


def entry(index, kind):
    return next(e for e in attention.find(index.read()) if e.kind == kind)


def read_artists(paths):
    return [tags.read(p)[0].artist for p in paths]


def test_merge_shows_the_names_preview_saves_it_as_one_entry_and_undo_puts_back(named, qtbot):
    """R2.8's Merge for an artist's names: the most used chosen, the files that change previewed,
    saved through the batch, one entry in the change history, Undo putting them back (R4.9)."""
    music, index, paths = named
    m = merger(music, index)
    try:
        m.open(entry(index, "names-artist"))
        qtbot.waitUntil(lambda: m.property("footer") != "Reading the songs…", timeout=WAIT)
        assert m.property("opened") and m.property("tool") == "merge"
        assert m.property("title") == "Merge into one artist"
        assert "artist and album artist is Lumen Drift or lumen drift" in m.property("about")
        assert [(f["name"], f["chosen"]) for f in m.property("options")["fields"]] == [
            ("Lumen Drift", True), ("lumen drift", False)
        ]  # fmt: skip
        assert m.property("count") == 3 and m.property("saveLabel") == "Save 1 file"
        assert m.property("saveLater") == "" and m.property("problem") == ""
        h = m.history_
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            m.save()
        assert not m.property("opened")
        assert read_artists(paths) == ["Lumen Drift"] * 3
        sql = "SELECT action, description FROM change"
        qtbot.waitUntil(lambda: index.read().execute(sql).fetchall() != [], timeout=WAIT)
        assert index.read().execute(sql).fetchall() == [
            ("names", "Artist lumen drift merged into Lumen Drift on 1 song")
        ]
        assert not any(e.kind == "names-artist" for e in attention.find(index.read()))
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            h.undoMessage()
        qtbot.waitUntil(lambda: read_artists(paths)[1] == "lumen drift", timeout=WAIT)
    finally:
        m.shut()
        m.history_.close()


def test_the_name_kept_can_be_another_spelling_and_an_album_merges_as_an_album(named, qtbot):
    music, index, paths = named
    m = merger(music, index)
    try:
        album = entry(index, "names-album")
        m.open(album)
        qtbot.waitUntil(lambda: m.property("footer") != "Reading the songs…", timeout=WAIT)
        assert m.property("title") == "Merge into one album"
        m.toggleField("glass harbor")
        m.setOption("into", "Not one of them")  # only a spelling of the entry's
        assert [f["chosen"] for f in m.property("options")["fields"]] == [False, True]
        assert m.property("saveLabel") == "Save 2 files"
        assert m.description_of(2) == "Album Glass Harbor merged into glass harbor on 2 songs"
        with pytest.raises(ValueError, match="no such option"):
            m.setOption("field", "x")
        m.close()
        assert not m.property("opened") and m.property("options") == {}
        assert m.property("title") == "" and m.property("about") == ""
        m.open(Entry("names-genre", "x"))
        assert not m.property("opened")  # a genre's names are the genres' merge
    finally:
        m.shut()
        m.history_.close()


def test_files_that_fail_are_named_with_why_and_retry_saves_them(named, qtbot):
    music, index, paths = named
    failing = {"on": True}

    def write(job):
        if failing["on"]:
            raise tags.WriteError(job.path, "it's read-only")
        return tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)

    m = merger(music, index, write=write)
    try:
        m.open(entry(index, "names-artist"))
        qtbot.waitUntil(lambda: m.property("footer") != "Reading the songs…", timeout=WAIT)
        with qtbot.waitSignal(m.changed, timeout=WAIT, check_params_cb=lambda: not m.property(
                "saving")):  # fmt: skip
            m.save()
        qtbot.waitUntil(lambda: m.property("problem") != "", timeout=WAIT)
        assert m.property("problem") == "1 file wasn't saved: 02.wav it's read-only"
        assert m.property("saveLabel") == "Retry 1 file" and m.property("saveLater") == ""
        failing["on"] = False
        m.save()
        qtbot.waitUntil(lambda: not m.property("opened"), timeout=WAIT)
        assert read_artists(paths) == ["Lumen Drift"] * 3
    finally:
        m.shut()
        m.history_.close()


def test_a_save_shows_its_progress_and_waits_for_the_root(named, qtbot):
    music, index, _paths = named
    there = {"on": False}
    m = merger(music, index, available=lambda: there["on"])
    try:
        m.open(entry(index, "names-artist"))
        qtbot.waitUntil(lambda: m.property("footer") != "Reading the songs…", timeout=WAIT)
        m.save()  # the root isn't there: nothing starts
        assert not m.property("saving")
        m._on_progress(1, 3, "")
        assert "Saving" not in m.property("footer")  # no save going on: what it would save
        there["on"] = True
        m.save()
        assert m.property("saving") and m.property("saveLater") == "A save is going on"
        assert m.property("footer").startswith("Saving")
        m.close()  # while saving: the save stops before its next file
        qtbot.waitUntil(lambda: not m.property("saving"), timeout=WAIT)
    finally:
        m.shut()
        m.history_.close()


# ---------- in the window ----------


@pytest.fixture
def shell(named, tmp_path, qapp, qtbot):
    """MusiKata over the three songs and a file that can't be read, scanned."""
    music, index, _paths = named
    index.close()
    (tmp_path / "Music" / "broken.mp3").write_bytes(b"not an mp3")
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
def test_needs_attention_loads_from_the_sidebar_and_its_merge_opens_with_no_qml_warning(
    shell, qtbot, qtlog
):
    """L09 in the window: the sidebar's Needs attention with its count, the chips, a group
    opened, an entry's Merge… opening the preview over the window; every text in its box."""
    lib = shell.library
    qtbot.waitUntil(lambda: lib.property("attentionCount") != "", timeout=WAIT)
    side = find(shell, "side-attention")
    assert len(side) == 1 and find(shell, "sideBadge")
    click(shell, side[0])
    assert lib.property("view") == "attention"
    shell.attention.go({"view": "attention", "attention": "names"})
    settled(shell, qtbot)
    assert find(shell, "attentionChip-names") and find(shell, "attentionAction-merge")
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "attentionAction-merge")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "toolDialog")), timeout=WAIT)
    qtbot.waitUntil(lambda: shell.names.property("saveLater") == "", timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    shell.names.close()
    shell.attention.go({"view": "attention", "attention": "other"})
    settled(shell, qtbot)
    assert find(shell, "attentionAction-folder")
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []


def test_a_folder_whose_tags_differ_from_its_paths_says_where_how_many_and_what():
    """R2.8, R3.9: "Tags that differ from the path", its chip Tags differ from path (L09), an
    entry a folder with Infer from path and Ignore."""
    e = Entry(attention.PATH, "Lumen Drift/Tide Tables", "Tide Tables", "Lumen Drift", 3, 7,
              fields=("artist", "year"), counts=(2, 9))  # fmt: skip
    row = entry_row(e)
    assert (row["title"], row["detail"], row["icon"], row["group"]) == (
        "Tide Tables",
        "Lumen Drift · 2 of 9 files · Artist and Year",
        "folder",
        "paths",
    )
    assert [a["name"] for a in row["actions"]] == ["infer", "ignore"]
    assert row["actions"][0]["label"] == "Infer from path"
    loose = entry_row(Entry(attention.PATH, ".", "", fields=("title",), counts=(1, 3)))
    assert loose["title"] == "." and loose["detail"] == "1 of 3 files · Title"
    assert attention_app.path_detail(Entry(attention.PATH, "A")) == ""
    group = group_row(attention_app.BY_KEY["paths"], [Entry(attention.PATH, ".", ""), e], False)
    assert group["title"] == "Tags differ from path"
    assert group["summary"] == "2 folders · Your music folder, Tide Tables"
    chips = chips_of({"paths": 6, "copies": 3}, "all")
    assert [c["label"] for c in chips[:3]] == ["All  9", "Tags differ from path  6",
                                               "Same song twice  3"]  # fmt: skip
