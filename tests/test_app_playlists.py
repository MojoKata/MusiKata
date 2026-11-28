"""Playlists in the running app (src/musikata/playlists.py; R8.1 to R8.4, R8.6 to R8.8, R6.3,
P01-playlist-drag): the sidebar's list, a playlist's page and its entries, Play and Shuffle,
+ and New playlist from selection, Add to playlist from the selection bars and menus, renaming,
duplicating and deleting (asked first), removing entries (not asked), a missing entry's Find from
the page and Needs attention, and Export….

Why: a playlist's page lists entries, not songs: a song twice, a file missing, an entry outside
the root. What Play, Edit tags or a rating act on must be the songs they stand for, and what
Remove takes out the entries chosen; every change goes through the file, off the GUI thread, and
the views must show the file as it now is."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeClock, FakeEngine, fill
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, bridges, layout, tour
from musikata import playlists as lists_app
from musikata.attention import entry_row
from musikata.playlists import (
    Playlists,
    added_text,
    detail_text,
    export_text,
    find_rows,
    find_text,
    kicker_text,
    local_path,
    made_text,
    note_of,
    paths_text,
    question_of,
    removed_text,
    why_text,
)
from musikata_core import attention, playlists
from musikata_core.playlists import Candidate, ExportDone, Store

WAIT = 10_000

SONGS = [
    {"path": "A/01 Alpha.flac", "title": "Alpha", "artist": "Lumen Drift", "album": "Glass",
     "track": 1, "length": 200.0, "rating": 4},
    {"path": "A/02 Beta.flac", "title": "Beta", "artist": "Lumen Drift", "album": "Glass",
     "track": 2, "length": 100.0},
    {"path": "B/Gamma.mp3", "title": "Gamma", "artist": "Other", "album": "Tide", "track": 1,
     "genres": ("Jazz",), "length": 61.0},
]  # fmt: skip
ROAD = "#EXTM3U\n../A/01 Alpha.flac\n../B/Gamma.mp3\n../A/gone.flac\n../A/01 Alpha.flac\n"


# ---------- what the page and the dialogs say ----------


def test_the_line_under_a_playlists_name_says_its_songs_length_file_paths_and_missing():
    """P01: 42 songs · 2 h 51 min · Playlists/Road Trip.m3u8 · relative paths."""
    assert detail_text(42, 171 * 60, "Playlists/Road Trip.m3u8", 0) == (
        "42 songs · 2 h 51 min · Playlists/Road Trip.m3u8 · relative paths"
    )
    assert detail_text(0, 0, "P/x.m3u", 0) == "No songs · P/x.m3u"
    assert (
        detail_text(3, 61, "x.m3u", 3, 1) == "3 songs · 1 min · x.m3u · absolute paths · 1 missing"
    )
    assert paths_text(3, 1) == "relative and absolute paths" and paths_text(0, 0) == ""
    assert kicker_text("m3u8") == "Playlist · M3U8"


def test_the_messages_and_the_question_say_what_was_done():
    assert added_text(3, "Road Trip") == "Added 3 songs to Road Trip"
    assert added_text(0, "Road Trip") == "Nothing was added to Road Trip"
    assert made_text("New playlist", 1) == "Made New playlist with 1 song"
    assert made_text("New playlist", 0) == "Made New playlist"
    assert removed_text(2, "Road Trip").startswith("Removed 2 songs from Road Trip")
    assert note_of("A/x.mp3") == "Missing" and note_of(None) == "Not in your music folder"
    q = question_of("Road Trip", "Playlists/Road Trip.m3u8")
    assert q["title"] == "Move the playlist Road Trip to the trash?" and q["yes"] == "Move to trash"
    assert "Playlists/Road Trip.m3u8" in q["detail"]
    assert local_path("file:///tmp/x") == "/tmp/x" and local_path("") == ""


def test_finds_offers_say_why_each_is_offered():
    both = Candidate(1, "A/b.mp3", "B", "A", 61.0, True, True)
    assert why_text(both) == "Same name and tags"
    assert why_text(Candidate(1, "x", "B", "", None, True, False)) == "Same name"
    assert why_text(Candidate(1, "x", "B", "", None, False, True)) == "Same title and artist"
    assert find_rows([both]) == [{"title": "B", "artist": "A", "path": "A › b.mp3",
                                  "why": "Same name and tags", "time": "1:01"}]  # fmt: skip
    assert find_text(True, 0, "~/Music").startswith("Looking")
    assert find_text(False, 0, "~/Music").startswith("Nothing under ~/Music")
    assert find_text(False, 2, "~/Music").startswith("Found 2 songs")


def test_the_message_after_export_says_what_was_written_and_what_failed_or_was_left_out():
    done = ExportDone(copied=3, there=1, failed=[("04 - x.mp3", "couldn't be copied: gone"),
                                                 ("05 - y.mp3", "is there already")])  # fmt: skip
    done.playlist = "/usb/Road Trip.m3u8"
    said = export_text(done, playlists.COPIES, 2, "/usb")
    assert said == ("Copied 3 songs and a playlist to /usb (1 there already); 04 - x.mp3 couldn't"
                    " be copied: gone, and 1 more; 2 missing songs left out")  # fmt: skip
    assert export_text(ExportDone(playlist="x"), playlists.ABSOLUTE, 0, "/d") == (
        "Wrote a playlist to /d"
    )
    assert export_text(ExportDone(), playlists.ABSOLUTE, 0, "/d") == "No playlist was written"
    assert export_text(ExportDone(copied=2, stopped=True), playlists.COPIES, 0, "/d").startswith(
        "Export stopped after 2 songs"
    )


def test_the_selection_bars_and_menus_offer_add_to_playlist():
    """R2.9.6, L03, L06, L07: Add to playlist on Songs' and Folders' selection bars, no longer
    faded; a playlist's own bar has Remove from playlist first (R8.6); the right-click menus have
    Add to playlist and New playlist from selection (SongMenu.qml), and a playlist's Remove from
    playlist."""
    from musikata import folders, models

    add = {"label": "Add to playlist", "icon": "plus", "later": "", "action": "playlist"}
    assert add in models.SONG_LATER and add in folders.LATER
    assert add in folders.selection_actions(True)
    assert [a["action"] for a in lists_app.ACTIONS] == ["remove", "playlist", "edit", "infer"]
    qml = os.path.join(os.path.dirname(lists_app.__file__), "qml")
    with open(os.path.join(qml, "SongMenu.qml"), encoding="utf-8") as f:
        menu = f.read()
    for name in ("addToPlaylist", "newFromSelection", "removeFromPlaylist"):
        assert f'objectName: "{name}"' in menu


# ---------- the sidebar, the page and its entries ----------


@pytest.fixture
def root(tmp_path, qapp, qtbot):
    from musikata_core import db

    music = tmp_path / "Music"
    (music / "Playlists").mkdir(parents=True)
    (music / "Playlists" / "Road Trip.m3u8").write_text(ROAD)
    (music / "Playlists" / "Evening.m3u").write_bytes(b"..\\B\\Gamma.mp3\r\n")
    index = db.Index(str(tmp_path / "musikata.db"))
    fill(index, SONGS)
    found = {"Playlists": [playlists.Found("Road Trip.m3u8", 1, 1),
                           playlists.Found("Evening.m3u", 1, 1)]}  # fmt: skip
    playlists.refresh(str(music), index, found, lambda f: True)
    library = bridges.Library(str(music), index, str(tmp_path), ThreadPoolExecutor)
    yield str(music), index, library
    library.close()
    index.close()


def ids_of(index, name):
    return index.read().execute("SELECT id FROM playlist WHERE name = ?", (name,)).fetchone()[0]


def page_rows(page):
    model = page.property("songs")
    return [model.row(i) for i in range(model.rowCount())]


def test_the_sidebar_lists_each_playlist_by_name_with_its_count(root):
    """R6.3, P01: Playlists, each with its count."""
    _music, _index, library = root
    model = library.property("playlists")
    assert [m["name"] for m in model.items()] == ["Evening", "Road Trip"]
    assert [m["count"] for m in model.items()] == ["1", "4"]
    role = {bytes(v).decode(): k for k, v in model.roleNames().items()}
    assert model.data(model.index(1), role["name"]) == "Road Trip"
    assert model.data(model.index(9), role["name"]) is None and model.property("count") == 2


def test_a_playlists_page_shows_its_entries_a_song_twice_and_one_missing_dimmed(root):
    """R8.2, R8.7, P01: the mosaic, name, kicker and line; each entry its number, title, artist,
    album, genre, rating and length; one missing says so with the path it names."""
    _music, index, library = root
    library.openPlaylist(ids_of(index, "Road Trip"))
    assert library.property("view") == "playlist" and library.property("section") == "playlist"
    assert not library.property("searchable")  # P01: no header over it
    page = library.property("playlistPage")
    assert page.property("name") == "Road Trip" and page.property("kicker") == "Playlist · M3U8"
    assert page.property("detail") == (
        "4 songs · 8 min · Playlists/Road Trip.m3u8 · relative paths · 1 missing"
    )
    assert page.property("playable") and page.property("emptyText") == ""
    rows = page_rows(page)
    assert [(r["number"], r["title"], r["missing"]) for r in rows] == [
        ("1", "Alpha", False), ("2", "Gamma", False), ("3", "gone", True), ("4", "Alpha", False)
    ]  # fmt: skip
    assert rows[1]["genre"] == "Jazz" and rows[0]["rating"] == 4 and rows[0]["time"] == "3:20"
    assert (rows[2]["note"], rows[2]["where"]) == ("Missing", "../A/gone.flac")
    model = page.property("songs")
    assert [model.song_at(i) is None for i in range(4)] == [False, False, True, False]
    assert model.missing_at(2) and not model.missing_at(0) and not model.missing_at(9)
    assert model.entry_of(2) == ("../A/gone.flac", "", None) and model.entry_of(9) is None


def test_the_entries_stand_for_their_songs_and_a_missing_one_is_passed_by(root, qtbot):
    """R7.1, R8.2: a double click plays the rest of the playlist from it, missing entries passed
    by; the selection is of entries, each standing for its song."""
    _music, index, library = root
    library.openPlaylist(ids_of(index, "Road Trip"))
    model = library.property("playlistPage").property("songs")
    alpha, gamma = model.song_at(0), model.song_at(1)
    assert model.queue_from(1) == ([gamma, alpha], "Road Trip")
    assert model.queue_from(2) == ([], "Road Trip")
    model.click(0, False, False)
    model.click(2, False, True)
    assert model.selected_songs() == [alpha, gamma] and len(model.selected_entries()) == 3
    assert model.songs_at(1) == [alpha, gamma] and model.songs_at(3) == [alpha]
    assert model.entries_at(9) == [] and model.playlist() == ids_of(index, "Road Trip")
    model.set_playing("A/01 Alpha.flac")
    role = {bytes(v).decode(): k for k, v in model.roleNames().items()}
    assert [model.data(model.index(i), role["playing"]) for i in range(4)] == [
        True, False, False, True
    ]  # fmt: skip


def test_a_playlist_gone_takes_its_page_back_and_an_empty_one_says_so(root, tmp_path):
    _music, index, library = root
    library.openPlaylist(999)
    assert library.property("view") == "albums"
    road = ids_of(index, "Road Trip")
    library.openPlaylist(road)
    index.write(lambda c: playlists.forget(c, ["Playlists/Road Trip.m3u8"])).result()
    library.reload()
    assert library.property("view") == "albums"
    store = Store(str(tmp_path / "Music"), index)
    made = store.create()
    library.reload()
    library.openPlaylist(made.playlist)
    page = library.property("playlistPage")
    assert page.property("emptyText").startswith("No songs yet")
    assert not page.property("playable") and page.property("tiles") == []


def test_the_tour_opens_a_playlist_by_its_name(root):
    _music, _index, library = root
    library.go({"view": "playlist", "playlist": "Evening"})
    assert library.property("playlistPage").property("name") == "Evening"
    assert library.property("playlistPage").property("detail").endswith("relative paths")


def test_play_and_shuffle_play_the_playlists_songs_in_its_order_missing_ones_passed_by(root):
    """R7.1, R8.2: Play from its first song; Shuffle turns shuffle on."""
    music, index, _library = root
    player = bridges.Player(music, FakeEngine(), read=index.read)
    player.playPlaylist(ids_of(index, "Road Trip"))
    c = index.read()
    titles = [c.execute("SELECT title FROM song WHERE id = ?", (e.song,)).fetchone()[0]
              for e in player.queue.order]  # fmt: skip
    assert titles == ["Alpha", "Gamma", "Alpha"]
    assert not player.queue.shuffle
    player.shufflePlaylist(ids_of(index, "Evening"))
    assert player.queue.shuffle and len(player.queue.order) == 1
    player.playPlaylist(999)
    player.close()


# ---------- what changes them ----------


class Said(list):
    def __call__(self, text):
        self.append(text)


@pytest.fixture
def lists(root, tmp_path):
    music, index, library = root
    said = Said()
    trashed = []

    def trash(path):
        trashed.append(path)
        os.remove(path)
        return True

    p = Playlists(Store(music, index), library, index.read, say=said, trash=trash,
                  home=str(tmp_path))  # fmt: skip
    p.said, p.trashed = said, trashed
    yield p
    p.shut()


def done(p, qtbot, said_before=None):
    """Waits for the change running to be done: its message said."""
    n = len(p.said) if said_before is None else said_before
    qtbot.waitUntil(lambda: len(p.said) > n, timeout=WAIT)
    return p.said[-1]


def test_plus_makes_new_playlist_opens_it_and_selects_its_name_for_editing(lists, root, qtbot):
    """R8.3: + beside Playlists."""
    music, _index, library = root
    with qtbot.waitSignal(lists.changed, timeout=WAIT):
        lists.create()
    made = lists.property("editing")
    assert made >= 0 and library.property("view") == "playlist"
    assert library.property("playlistPage").property("name") == "New playlist"
    assert os.path.isfile(os.path.join(music, "Playlists", "New playlist.m3u8"))
    lists.rename(made, "Long Drive")
    assert lists.property("editing") == -1
    qtbot.waitUntil(lambda: library.property("playlistPage").property("name") == "Long Drive",
                    timeout=WAIT)  # fmt: skip
    assert os.path.isfile(os.path.join(music, "Playlists", "Long Drive.m3u8"))
    lists.startRename(made)
    assert lists.property("editing") == made
    lists.cancelRename()
    lists.rename(made, "Long Drive")  # the same name: nothing to do
    lists.rename(made, "  ")
    assert lists.property("editing") == -1


def test_new_playlist_from_selection_holds_the_selection_and_add_to_playlist_adds_it(
    lists, root, qtbot
):
    """R8.3's New playlist from selection, and Add to playlist (R2.9.6, L03): the songs of the
    selection, or of the row right-clicked, in the list's order."""
    music, index, library = root
    songs = library.property("songs")
    songs.selectAll()
    lists.createFrom(songs, -1)
    assert done(lists, qtbot, 0) == "Made New playlist with 3 songs"
    assert lists.property("editing") >= 0
    road = ids_of(index, "Road Trip")
    lists.addTo(road, songs, 2)  # the row is in the selection: all of it
    assert done(lists, qtbot) == "Added 3 songs to Road Trip (2 were there already)"  # R8.5
    songs.clearSelection()
    lists.addTo(road, songs, 0)
    assert done(lists, qtbot) == "Added 1 song to Road Trip (it was there already)"
    with open(os.path.join(music, "Playlists", "Road Trip.m3u8"), encoding="utf-8") as f:
        text = f.read()
    assert text.count("#EXTINF:") == 8 and text.startswith("#EXTM3U\n#EXTINF:200,Lumen Drift")
    n = len(lists.said)
    lists.addTo(road, songs, -1)  # nothing selected: nothing to add
    lists.createFrom(None, -1)
    assert len(lists.said) == n
    assert [m["count"] for m in library.property("playlists").items()] == ["1", "3", "8"]


class Queued(QObject):
    """A player's queue, as Save as playlist… reads it."""

    def __init__(self, songs, source):
        super().__init__()
        self.songs, self.queue = songs, type("Q", (), {"source": source})()

    def queue_songs(self):
        return list(self.songs)


def test_save_as_playlist_holds_the_queue_named_for_its_source_and_opens_it(lists, root, qtbot):
    """R11.4.3's Save as playlist… (R8.3): the queue's songs in the order they play, named for
    where the queue comes from (else New playlist), opened, its name selected for editing."""
    music, index, library = root
    songs = [r[0] for r in index.read().execute("SELECT id FROM song ORDER BY id DESC")]
    lists.saveQueue(Queued(songs, "Glass Harbor"))
    assert done(lists, qtbot, 0) == f"Made Glass Harbor with {len(songs)} songs"
    assert lists.property("editing") >= 0 and library.property("view") == "playlist"
    assert library.property("playlistPage").property("name") == "Glass Harbor"
    with open(os.path.join(music, "Playlists", "Glass Harbor.m3u8"), encoding="utf-8") as f:
        assert f.read().count("#EXTINF:") == len(songs)
    lists.saveQueue(Queued(songs[:1], " "))
    assert done(lists, qtbot) == "Made New playlist with 1 song"
    n = len(lists.said)
    lists.saveQueue(Queued([], "Glass Harbor"))  # an empty queue: nothing to save
    lists.saveQueue(QObject())
    assert len(lists.said) == n


def test_duplicate_and_delete_asked_first_and_its_file_to_the_trash(lists, root, qtbot):
    """R8.4, R6.8: Duplicate copies it; Delete playlist asks, then moves its file to the trash."""
    music, index, library = root
    road = ids_of(index, "Road Trip")
    lists.duplicate(road)
    assert done(lists, qtbot, 0) == "Made Road Trip copy"
    library.openPlaylist(road)
    lists.askDelete(road)
    assert lists.property("question")["title"] == "Move the playlist Road Trip to the trash?"
    assert lists.property("opened")
    lists.answer(False)
    assert lists.property("question") == {} and not lists.trashed
    lists.askDelete(road)
    lists.answer(True)
    assert done(lists, qtbot).startswith("Moved Road Trip to the trash")
    assert lists.trashed == [os.path.join(music, "Playlists", "Road Trip.m3u8")]
    assert library.property("view") == "albums"
    assert [m["name"] for m in library.property("playlists").items()] == [
        "Evening", "Road Trip copy"
    ]  # fmt: skip
    lists.askDelete(999)
    assert lists.property("question") == {}


def test_delete_and_remove_from_playlist_take_entries_out_without_asking(lists, root, qtbot):
    """R8.6: the entries selected, or the row's, out; the files untouched."""
    music, index, library = root
    library.openPlaylist(ids_of(index, "Road Trip"))
    model = library.property("playlistPage").property("songs")
    model.click(0, False, False)
    model.click(2, True, False)
    lists.removeSelected(model)
    assert done(lists, qtbot, 0).startswith("Removed 2 songs from Road Trip")
    assert lists.property("question") == {}
    qtbot.waitUntil(lambda: model.rowCount() == 2, timeout=WAIT)
    assert [model.row(i)["title"] for i in range(2)] == ["Gamma", "Alpha"]
    lists.removeRow(model, 1)
    assert done(lists, qtbot).startswith("Removed 1 song")
    lists.removeRow(library.property("songs"), 0)  # not a playlist's list: nothing
    lists.removeSelected(library.property("songs"))
    with open(os.path.join(music, "Playlists", "Road Trip.m3u8"), encoding="utf-8") as f:
        text = f.read()
    assert text == "#EXTM3U\n#EXTINF:61,Other - Gamma\n../B/Gamma.mp3\n"


def test_find_from_the_page_offers_matches_and_choosing_one_fixes_the_entry(lists, root, qtbot):
    """R8.7: a missing entry's Find looks by name and by tags; choosing one fixes it."""
    music, index, library = root
    with open(os.path.join(music, "Playlists", "Road Trip.m3u8"), "a", encoding="utf-8") as f:
        f.write("#EXTINF:-1,Lumen Drift - Beta\n../old/02 Beta.flac\n")
    playlists.refresh(music, index, {"Playlists": [playlists.Found("Road Trip.m3u8", 2, 2)]},
                      lambda f: True)  # fmt: skip
    library.reload()
    library.openPlaylist(ids_of(index, "Road Trip"))
    model = library.property("playlistPage").property("songs")
    lists.findRow(model, 4)
    assert lists.property("findOpen") and lists.property("finding")
    assert lists.property("findTitle") == "Find Beta"
    assert lists.property("findAbout") == "Missing from Road Trip: ../old/02 Beta.flac"
    qtbot.waitUntil(lambda: not lists.property("finding"), timeout=WAIT)
    rows = lists.property("findRows")
    assert [(r["title"], r["why"]) for r in rows] == [("Beta", "Same name and tags")]
    assert lists.property("findText").startswith("Found 1 song")
    lists.choose(0)
    assert not lists.property("findOpen")
    assert done(lists, qtbot, 0) == "Road Trip now names A/02 Beta.flac"
    qtbot.waitUntil(lambda: not model.missing_at(4), timeout=WAIT)
    lists.findRow(library.property("songs"), 0)  # not a playlist's: nothing
    lists.findRow(model, 99)
    assert not lists.property("findOpen")
    lists.choose(0)  # nothing open: nothing chosen


def test_needs_attention_lists_each_missing_entry_and_its_find_opens_the_same_dialog(
    lists, root, qtbot
):
    """R2.8, R8.7: "Playlist entries whose file is missing", with Find."""
    music, index, library = root
    found = [e for e in attention.found(index.read()) if e.kind == attention.MISSING]
    assert [(e.title, e.artist) for e in found] == [("gone", "Road Trip")]
    row = entry_row(found[0])
    assert row["group"] == "playlists" and row["icon"] == "playlist"
    assert row["detail"] == "In Road Trip · ../A/gone.flac"
    assert [a["name"] for a in row["actions"]] == ["find", "ignore"]
    lists.find_entry(found[0])
    assert lists.property("findTitle") == "Find gone"
    qtbot.waitUntil(lambda: not lists.property("finding"), timeout=WAIT)
    assert lists.property("findRows") == []
    assert lists.property("findText").startswith("Nothing under")
    lists.closeFind()
    assert not lists.property("findOpen") and lists.property("findTitle") == ""
    twice = attention.Entry(attention.MISSING, "Playlists/X.m3u8\tx", "x", "X", key="x",
                            counts=(2,))  # fmt: skip
    assert entry_row(twice)["detail"] == "In X (2 times) · x"
    lists.find_entry(twice)  # no such playlist: nothing opens
    assert not lists.property("findOpen")


def test_export_writes_absolute_paths_or_numbered_copies_to_the_folder_chosen(
    lists, root, qtbot, tmp_path
):
    """R8.8: Export… with its two ways, the folder chosen, the copies off the GUI thread."""
    music, index, _library = root
    for s in SONGS:
        os.makedirs(os.path.dirname(os.path.join(music, s["path"])), exist_ok=True)
        with open(os.path.join(music, s["path"]), "wb") as f:
            f.write(s["path"].encode())
    road = ids_of(index, "Road Trip")
    lists.openExport(road)
    assert lists.property("exportOpen") and lists.property("exportTitle") == "Export Road Trip"
    assert [m["chosen"] for m in lists.property("exportModes")] == [True, False]
    assert lists.property("exportLater") == "Choose the folder to export to"
    lists.export()  # no folder: nothing
    lists.setExportFolder(str(tmp_path / "nowhere"))
    assert lists.property("exportLater") == "That folder isn't there"
    usb = tmp_path / "usb"
    usb.mkdir()
    lists.setExportFolder(usb.as_uri())
    assert lists.property("exportFolder") == "~/usb" and lists.property("exportLater") == ""
    lists.export()
    assert done(lists, qtbot, 0) == "Wrote a playlist to ~/usb; 1 missing song left out"
    assert not lists.property("exportOpen")
    text = (usb / "Road Trip.m3u8").read_text()
    assert f"\n{os.path.join(music, 'A', '01 Alpha.flac')}\n" in text
    lists.openExport(road)
    lists.setExportMode(playlists.COPIES)
    lists.setExportMode("nonsense")
    assert [m["chosen"] for m in lists.property("exportModes")] == [False, True]
    assert lists.property("exportFolder") == "~/usb"  # kept from the last time
    os.remove(usb / "Road Trip.m3u8")
    lists.export()
    assert lists.property("exporting")
    assert lists.property("exportText").startswith("Copying") or lists.property("exportText")
    assert done(lists, qtbot).startswith("Copied 3 songs and a playlist to ~/usb")
    assert sorted(os.listdir(usb)) == [
        "01 - Lumen Drift - Alpha.flac", "02 - Other - Gamma.mp3", "03 - Lumen Drift - Alpha.flac",
        "Road Trip.m3u8",
    ]  # fmt: skip
    assert lists.property("exportProgress") == 1.0
    lists.openExport(road)
    lists.cancelExport()
    assert not lists.property("exportOpen")
    lists.openExport(999)
    assert not lists.property("exportOpen")


def test_export_cancelled_stops_the_copying(lists, root, qtbot, tmp_path, monkeypatch):
    music, index, _library = root
    for s in SONGS:
        os.makedirs(os.path.dirname(os.path.join(music, s["path"])), exist_ok=True)
        open(os.path.join(music, s["path"]), "wb").close()
    lists.openExport(ids_of(index, "Road Trip"))
    lists.setExportMode(playlists.COPIES)
    lists.setExportFolder(str(tmp_path))
    lists._stop.set()  # as Cancel would, before the first song
    monkeypatch.setattr(lists._stop, "clear", lambda: None)
    lists.export()
    lists.cancelExport()  # while copying: stops, the dialog stays
    assert done(lists, qtbot, 0).startswith("Export stopped")
    assert lists.property("exportOpen") and not lists.property("exporting")


def test_nothing_changes_while_the_music_folder_isnt_there_and_a_failure_says_why(
    root, qtbot, tmp_path
):
    music, index, library = root
    said = Said()
    p = Playlists(Store(music, index), library, index.read, say=said, available=lambda: False)
    p.create()
    p.startRename(1)
    p.askDelete(ids_of(index, "Road Trip"))
    assert said == [lists_app.NOT_THERE] * 3 and p.property("editing") == -1
    p.shut()
    q = Playlists(Store(music, index), library, index.read, say=said)
    q.said = said
    q.duplicate(999)
    assert done(q, qtbot, 3) == "That playlist isn't there any more"
    q.shut()
    q.create()  # shut: nothing runs
    q.go({"export": True})


def test_a_change_that_breaks_says_it_couldnt_be_done(root, qtbot):
    music, index, library = root
    said = Said()

    class Broken(Store):
        def duplicate(self, playlist):
            raise RuntimeError("boom")

    p = Playlists(Broken(music, index), library, index.read, say=said)
    p.said = said
    p.duplicate(1)
    assert done(p, qtbot, 0) == "It couldn't be done: boom"
    p.shut()


def test_needs_attentions_find_action_opens_find_on_its_entry(lists, root, qtbot):
    """R2.8: the entry's Find… (attention.Attention.act)."""
    from musikata.attention import Attention

    music, index, library = root
    model = library.property("attention")
    model.refresh()
    qtbot.waitUntil(lambda: not model.pending(), timeout=WAIT)
    model.choose("other")
    needs = Attention(music, index, model, FakeClock(), playlists=lists, watching=False)
    row = next(r for r in range(model.rowCount())
               if (e := model.entry_at(r)) is not None and e.kind == attention.MISSING)  # fmt: skip
    needs.act(row, "find")
    assert lists.property("findTitle") == "Find gone"
    qtbot.waitUntil(lambda: not lists.property("finding"), timeout=WAIT)
    needs.close()


def test_opening_a_playlist_forgets_the_searches_of_the_lists(root, qtbot):
    _music, index, library = root
    library.show("songs")
    library.setSearch("alpha")
    library.openPlaylist(ids_of(index, "Road Trip"))
    assert library.property("search") == "" and not library.property("songs").searching()


def test_the_tour_opens_export_or_find_on_the_playlist_shown(lists, root, qtbot):
    _music, index, library = root
    library.openPlaylist(ids_of(index, "Road Trip"))
    lists.go({"find": "gone"})
    assert lists.property("findTitle") == "Find gone"
    lists.closeFind()
    lists.go({"export": True})
    assert lists.property("exportOpen")


# ---------- adding with Undo, files dropped, reordering (R8.5, R18.2) ----------


def test_the_messages_of_r8_5_say_what_was_there_already_what_was_taken_back_and_what_waits():
    assert (
        added_text(3, "Evening Focus", 1) == "Added 3 songs to Evening Focus (1 was there already)"
    )
    assert added_text(3, "Evening Focus", 2).endswith("(2 were there already)")
    assert added_text(1, "Evening Focus", 1).endswith("(it was there already)")
    assert lists_app.took_back_text(3, 3, "Road Trip") == "Took 3 songs back out of Road Trip"
    assert lists_app.took_back_text(1, 3, "Road Trip").endswith("; 2 had moved since and stay")
    assert lists_app.took_back_text(0, 3, "Road Trip").startswith("Nothing was taken out")
    assert lists_app.dropped_text(2, 0) == lists_app.OUTSIDE_NOT_ADDED
    assert lists_app.dropped_text(0, 0) == "Nothing dropped is a song in your library"
    assert lists_app.dropped_text(0, 4) == ""


def test_ctrl_shift_up_and_down_are_the_keys_that_move_songs_in_a_playlist():
    """R6.9, R18.2 (⇧⌘ on macOS, which Qt gives as Ctrl)."""
    ctrl, shift = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier
    up, down = int(Qt.Key.Key_Up), int(Qt.Key.Key_Down)
    assert lists_app.move_key(up, (ctrl | shift).value) == -1
    assert lists_app.move_key(down, (ctrl | shift).value) == 1
    assert lists_app.move_key(down, shift.value) == 0  # Shift+↓ extends the selection
    assert lists_app.move_key(down, (ctrl | shift | Qt.KeyboardModifier.AltModifier).value) == 0
    assert lists_app.move_key(int(Qt.Key.Key_Left), (ctrl | shift).value) == 0


@pytest.fixture
def offering(root):
    """Playlists whose messages may offer Undo (R8.5), each kept with it."""
    music, index, library = root
    said = Said()
    offered = []

    def offer(text, undo):
        offered.append(undo)
        said.append(text)

    p = Playlists(Store(music, index), library, index.read, say=said, offer=offer)
    p.said, p.offered = said, offered
    yield p
    p.shut()


def test_songs_added_say_those_there_already_and_undo_takes_the_addition_back_out(
    offering, root, qtbot
):
    """R8.5: added at its end anyway, the message says so, and Undo takes them back out."""
    music, index, library = root
    road = ids_of(index, "Road Trip")
    alpha, beta = (index.read().execute("SELECT id FROM song WHERE title = ?", (t,)).fetchone()[0]
                   for t in ("Alpha", "Beta"))  # fmt: skip
    offering.add_songs(road, [beta, alpha])
    assert done(offering, qtbot, 0) == "Added 2 songs to Road Trip (1 was there already)"
    assert library.property("playlists").items()[1]["count"] == "6"
    offering.offered[-1]()  # the message's Undo
    assert done(offering, qtbot) == "Took 2 songs back out of Road Trip"
    with open(os.path.join(music, "Playlists", "Road Trip.m3u8"), encoding="utf-8") as f:
        assert f.read().count("#EXTINF") == 4
    n = len(offering.said)
    offering.add_songs(road, [])  # nothing: nothing said
    assert len(offering.said) == n


def test_a_file_managers_files_dropped_on_a_playlist_are_added_and_those_outside_brought_in(
    offering, root, qtbot, tmp_path
):
    """R8.5: files and folders under the root added, their songs; those outside it brought into
    the library first (R12.5: Organize files' dialog, which adds them to the playlist), or, with
    no way to, said not added."""
    music, index, library = root
    evening = ids_of(index, "Evening")
    offering.add_files(evening, [os.path.join(music, "A"), "/elsewhere/x.mp3"])
    said = done(offering, qtbot, 0)
    assert said == f"Added 2 songs to Evening; {lists_app.OUTSIDE_NOT_ADDED}"
    offering.add_files(evening, ["/elsewhere/x.mp3"])
    assert offering.said[-1] == lists_app.OUTSIDE_NOT_ADDED
    brought = []
    offering.outside = lambda paths, playlist: brought.append((list(paths), playlist))
    n = len(offering.said)
    offering.add_files(evening, ["/elsewhere/x.mp3"])
    assert brought == [(["/elsewhere/x.mp3"], evening)] and len(offering.said) == n
    offering.add_files(evening, [os.path.join(music, "A", "cover.jpg")])
    assert offering.said[-1] == "Nothing dropped is a song in your library"
    offering.add_files(evening, [os.path.join(music, "B", "Gamma.mp3")])
    assert done(offering, qtbot, len(offering.said)) == (
        "Added 1 song to Evening (it was there already)"
    )


def test_a_playlists_songs_are_moved_by_dragging_and_by_keys_and_stay_selected(lists, root, qtbot):
    """R8.5, R6.9, R18.2: dragged above the line, or Ctrl+Shift+↑ / ↓; the songs moved stay
    selected where they now are, so the keys go on moving them."""
    music, index, library = root
    library.openPlaylist(ids_of(index, "Road Trip"))
    model = library.property("playlistPage").property("songs")

    def titles():
        return [model.row(i)["title"] for i in range(model.rowCount())]

    assert titles() == ["Alpha", "Gamma", "gone", "Alpha"]
    assert model.position_at(1) == 1 and model.position_at(9) == 4
    lists.move_entries(model, model.entries_at(0), model.position_at(3))  # above the 4th row
    qtbot.waitUntil(lambda: titles() == ["Gamma", "gone", "Alpha", "Alpha"], timeout=WAIT)

    def selected(row):
        return len(model.selected_entries()) == 1 and model.selected_entries() == model.entries_at(
            row
        )

    qtbot.waitUntil(lambda: selected(2), timeout=WAIT)
    ctrl_shift = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier).value
    assert lists.pressMove(model, int(Qt.Key.Key_Up), ctrl_shift)
    qtbot.waitUntil(lambda: titles() == ["Gamma", "Alpha", "gone", "Alpha"], timeout=WAIT)
    qtbot.waitUntil(lambda: selected(1), timeout=WAIT)
    assert not lists.pressMove(model, int(Qt.Key.Key_Up), 0)  # the list's own key
    model.clearSelection()
    assert lists.pressMove(model, int(Qt.Key.Key_Down), ctrl_shift)  # nothing selected: taken
    assert not lists.pressMove(library.property("songs"), int(Qt.Key.Key_Up), ctrl_shift)
    lists.move_entries(library.property("songs"), [1], 0)  # not a playlist's: nothing
    with open(os.path.join(music, "Playlists", "Road Trip.m3u8"), encoding="utf-8") as f:
        assert [x for x in f.read().splitlines() if not x.startswith("#")] == [
            "../B/Gamma.mp3", "../A/01 Alpha.flac", "../A/gone.flac", "../A/01 Alpha.flac"
        ]  # fmt: skip


# ---------- in the window ----------


@pytest.fixture
def shell(tmp_path, qapp, qtbot):
    music = tmp_path / "Music"
    (music / "Playlists").mkdir(parents=True)
    (music / "Playlists" / "Road Trip.m3u8").write_text(ROAD)
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(music), env, FakeClock(datetime.now(UTC) - timedelta(minutes=1)),
                 lambda: ThreadPoolExecutor(1))  # fmt: skip
    fill(s.index, SONGS)
    found = {"Playlists": [playlists.Found("Road Trip.m3u8", 1, 1)]}
    playlists.refresh(str(music), s.index, found, lambda f: True)
    s.library.reload()
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
def test_p01_a_playlists_page_loads_from_the_sidebar_with_no_qml_warning_and_its_text_in_its_boxes(
    shell, qtbot, qtlog
):
    """P01-playlist-drag: the sidebar's Road Trip opens its page; Delete takes the entry selected
    out (R8.6); Find… on the missing one opens its dialog, Export… its own; each whole."""
    settled(shell, qtbot)
    side = find(shell, "side-playlist")
    assert len(side) == 1
    click(shell, side[0])
    qtbot.waitUntil(lambda: shell.library.property("view") == "playlist", timeout=WAIT)
    settled(shell, qtbot)
    assert find(shell, "playlistTitle") and find(shell, "playlistMosaic")
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "findMissing")[0])
    qtbot.waitUntil(lambda: find(shell, "findDialog") != [], timeout=WAIT)
    qtbot.waitUntil(lambda: not shell.playlists.property("finding"), timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "cancelFind")[0])
    click(shell, find(shell, "playlistExport")[0])
    qtbot.waitUntil(lambda: find(shell, "exportDialog") != [], timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "exportMode-copies")[0])
    assert shell.playlists.property("exportModes")[1]["chosen"]
    click(shell, find(shell, "cancelExport")[0])
    qtbot.waitUntil(lambda: not shell.playlists.property("opened"), timeout=WAIT)
    model = shell.library.property("playlistPage").property("songs")
    page = find(shell, "playlistPage")[0]
    page.forceActiveFocus()
    model.click(0, False, False)
    settled(shell, qtbot)
    assert find(shell, "playlistSelectionBar")
    shell.edit.editCurrent(shell.library)  # Ctrl+E: the songs the entries selected stand for
    qtbot.waitUntil(lambda: shell.edit.property("count") == 1, timeout=WAIT)
    shell.edit.hide()
    page.forceActiveFocus()
    QTest.keyClick(shell.window, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: model.rowCount() == 3, timeout=WAIT)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


@pytest.mark.slow
def test_plus_in_the_sidebar_edits_the_new_playlists_name_and_enter_keeps_it(shell, qtbot, qtlog):
    """R8.3: + makes New playlist, its name selected in a text box; Enter renames it."""
    settled(shell, qtbot)
    click(shell, find(shell, "newPlaylist")[0])
    qtbot.waitUntil(lambda: find(shell, "playlistName") != [], timeout=WAIT)
    field = find(shell, "playlistName")[0]
    assert field.property("selectedText") == "New playlist"
    field.setProperty("text", "Drive")
    QTest.keyClick(shell.window, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: [m["name"] for m in shell.library.property("playlists").items()]
                    == ["Drive", "Road Trip"], timeout=WAIT)  # fmt: skip
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


@pytest.mark.slow
def test_add_to_playlist_from_songs_selection_bar_and_the_menu_with_no_qml_warning(
    shell, qtbot, qtlog
):
    """L03, R2.9.6: Add to playlist on the selection bar opens the menu of the playlists; its
    playlist adds the selection; a row's menu has Add to playlist and New playlist from
    selection."""
    shell.library.show("songs")
    songs = shell.library.property("songs")
    settled(shell, qtbot)
    songs.selectAll()
    settled(shell, qtbot)
    click(shell, find(shell, "playlistSelection")[0])
    qtbot.waitUntil(lambda: find(shell, "addTo-Road Trip") != [], timeout=WAIT)
    click(shell, find(shell, "addTo-Road Trip")[0])
    qtbot.waitUntil(lambda: shell.library.property("playlists").items()[0]["count"] == "7",
                    timeout=WAIT)  # fmt: skip
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
