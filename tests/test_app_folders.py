"""The Folders view's model and open folder (src/musikata/folders.py; R2.9, A2.7): the open folder's
subfolders then its files, by name; the title, crumbs and count of where you are; going up and back;
a search beneath the open folder with where each match is; the selection by click, Ctrl, Shift,
checkbox and drag box, its count, and Play; a folder of songs' strip; the mode and the open folder
remembered.

Why: what Folders shows and what a click does are decided here (QML only lays out); a row in the
wrong order, a count that miscounts a folder and the file inside it, or Play starting the wrong
song, would show in every mode."""

import os

import pytest
from fakes import fill

from musikata import bridges, folders
from musikata_core import db
from musikata_core import folders as index_folders

LIBRARY = [
    {"path": "Lumen Drift/2019 - Glass Harbor/01.flac", "title": "Tidewater", "track": 1,
     "artist": "Lumen Drift", "album": "Glass Harbor", "year": 2019, "length": 200.0},
    {"path": "Lumen Drift/2019 - Glass Harbor/02.flac", "title": "Glass Harbor", "track": 2,
     "artist": "Lumen Drift", "album": "Glass Harbor", "year": 2019, "length": 100.0},
    {"path": "Lumen Drift/Remixes/Glass/01.flac", "title": "Glass Remix", "artist": "Lumen Drift"},
    {"path": "Lumen Drift/Tide Tables/01 - Neap Tide.flac", "title": "Neap Tide", "track": 1,
     "artist": "Lumen Drift", "genres": ("Electronic",), "year": 2022, "size": 2_000_000},
    {"path": "Lumen Drift/Tide Tables/02 - Spring Tide.flac", "title": "Spring Tide", "track": 2,
     "artist": "Lumen Drift", "genres": ("electronic",), "year": 2022, "size": 1_000_000},
    {"path": "Lumen Drift/Tide Tables/03 - Slack Water.flac", "title": "Slack Water", "track": 3,
     "artist": "lumen drift", "genres": ("Electronic",), "size": 1_000_000},
    {"path": "Lumen Drift/Lumen Drift - Harbor Lights.flac", "title": "Harbor Lights",
     "artist": "Lumen Drift", "rating": 4},
    {"path": "Lumen Drift/ebb & flow.mp3"},
    {"path": "_Incoming/new rips/track01.mp3"},
    {"path": "Mara Okafor/Kindling/01.mp3", "title": "Kindling", "artist": "Mara Okafor"},
]  # fmt: skip


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, LIBRARY)
    yield i
    i.close()


@pytest.fixture
def view(index, qapp):
    v = folders.FolderView(index.read)
    yield v
    v.property("model").wait()


def rows(view, *names):
    m = view.property("model")
    return [tuple(m.row(n)[k] for k in names or ("kind", "name")) for n in range(m.rowCount())]


# ---------- plain functions ----------


def test_the_counts_and_the_selections_texts():
    assert folders.folder_line(3, 37) == "3 folders · 37 songs"
    assert folders.folder_line(1, 1) == "1 folder · 1 song"
    assert folders.folder_line(0, 10) == "10 songs"
    assert folders.found_line(2, 5) == "2 folders · 5 songs found"
    assert folders.found_line(0, 1) == "1 song found" and folders.found_line(1, 0) == (
        "1 folder found"
    )  # fmt: skip
    assert folders.selection_text(2, 0, 21) == "2 folders · 21 songs selected"
    assert folders.selection_text(1, 1, 11) == "1 folder · 1 file · 11 songs selected"
    assert folders.selection_text(0, 2, 2) == "2 songs selected"


def test_where_a_match_is_under_the_open_folder():
    assert folders.where_text("A/Remixes/Glass/1.flac", "A") == "Remixes › Glass"
    assert folders.where_text("A/1.flac", "A") == ""
    assert folders.where_text("A/B", "") == "A" and folders.where_text("A", "") == ""


def test_a_folders_picture_is_its_cover_one_picture_whole_a_mosaic_or_none():
    assert folders.picture_url("t", "a b") == "image://covers/t"
    assert folders.picture_url(None, "a") == "image://covers/a"
    assert folders.picture_url(None, "a b c") == "image://covers/mosaic/a+b+c"
    assert folders.picture_url(None, None) == ""


@pytest.mark.parametrize(
    "widths, room, hidden",
    [
        ([100, 100], 205, 0),  # they fit
        ([100, 100, 100, 100], 500, 0),
        ([100, 100, 100, 100], 400, 1),  # first, …, the last two
        ([100, 100, 100, 100], 300, 2),  # first, …, the last
        ([100, 100, 100, 100], 50, 2),  # never the last nor the first
        ([400, 400], 300, 0),  # two: nothing to fold
    ],
)
def test_long_paths_fold_their_middle_crumbs_into_an_ellipsis(widths, room, hidden):
    assert folders.fold_crumbs(widths, room, 20, 10) == hidden


def test_values_that_differ_from_the_rest_of_a_folder_are_marked():
    assert folders.odd_ones(["A", "A", "a", None]) == [False, False, True, False]
    assert folders.odd_ones([2022, None, 2022]) == [False, False, False]
    assert folders.odd_ones([]) == []


def test_a_folder_of_songs_art_line_and_chip():
    assert folders.art_line("T/folder.jpg", 0, 9) == "Cover from folder.jpg, not embedded"
    assert folders.art_line("T/folder.jpg", 9, 9) == "Cover from folder.jpg, embedded in 9 of 9"
    assert folders.art_line(None, 3, 9) == "Cover embedded in 3 of 9"
    assert folders.art_line(None, 0, 9) == "No cover"
    assert folders.art_chip("T/f.jpg", 0, 9) == {
        "text": "Folder", "tone": "info", "tip": "Art in f.jpg only, not embedded"}  # fmt: skip
    assert folders.art_chip(None, 9, 9) == {
        "text": "Embedded", "tone": "ok", "tip": "Art embedded in 9 of 9 files"}  # fmt: skip
    assert folders.art_chip("T/f.jpg", 1, 9) == {
        "text": "Partial", "tone": "warn", "tip": "Art embedded in 1 of 9 files"}  # fmt: skip
    assert folders.art_chip(None, 0, 9) == {
        "text": "Missing", "tone": "warn", "tip": "No art, embedded or in the folder"}  # fmt: skip


# ---------- where you are ----------


def test_the_root_lists_its_folders_by_name_titled_your_music_folders(view):
    assert view.property("title") == "Your music folders" and view.property("crumbs") == []
    assert rows(view) == [("folder", "_Incoming"), ("folder", "Lumen Drift"),
                          ("folder", "Mara Okafor")]  # fmt: skip
    assert view.property("count") == "3 folders · 10 songs"
    assert rows(view, "line")[1] == ("3 folders · 8 songs",)


def test_a_folder_lists_its_folders_then_its_files_with_their_crumbs_and_count(view):
    view.open("Lumen Drift")
    assert view.property("title") == "Lumen Drift"
    assert view.property("crumbs") == [{"name": "Lumen Drift", "path": "Lumen Drift"}]
    assert rows(view) == [
        ("folder", "2019 - Glass Harbor"), ("folder", "Remixes"), ("folder", "Tide Tables"),
        ("file", "ebb & flow.mp3"), ("file", "Lumen Drift - Harbor Lights.flac"),
    ]  # fmt: skip
    assert view.property("count") == "3 folders · 8 songs"
    assert view.property("folderRows") == 3
    assert view.property("filesTitle") == "2 songs in this folder"
    assert rows(view, "title", "rating")[-1] == ("Harbor Lights", 4)
    assert not view.property("songsMode")
    view.open("Lumen Drift/Remixes/Glass")
    assert [c["name"] for c in view.property("crumbs")] == ["Lumen Drift", "Remixes", "Glass"]
    assert view.property("crumbs")[1]["path"] == "Lumen Drift/Remixes"


def test_a_folders_list_row_shows_what_its_songs_share_and_their_total_time(view):
    view.open("Lumen Drift")
    glass = view.property("model").row(0)
    assert (glass["artist"], glass["album"], glass["year"], glass["time"]) == (
        "Lumen Drift", "Glass Harbor", "2019", "5:00"
    )  # fmt: skip
    assert view.property("model").row(2)["year"] == ""  # Tide Tables: one has no year


def test_going_up_and_back(view):
    view.open("Lumen Drift")
    view.open("Lumen Drift/Remixes")
    view.up()
    assert view.property("path") == "Lumen Drift"
    view.back()
    assert view.property("path") == "Lumen Drift/Remixes"
    view.back()
    view.back()
    assert view.property("path") == "" and not view.property("canBack")
    view.up()  # at the root: nothing
    view.back()
    assert view.property("path") == ""


def test_a_folder_that_isnt_there_opens_the_nearest_above_it(view, index):
    view.open("Lumen Drift/Nope/Deeper")
    assert view.property("path") == "Lumen Drift"
    view.open("Mara Okafor/Kindling")
    index.write(lambda c: c.execute("DELETE FROM song WHERE folder = 'Mara Okafor/Kindling'"))
    index.write(lambda c: index_folders.refresh(c, ["Mara Okafor/Kindling"])).result()
    view.reload()
    assert view.property("path") == ""


def test_going_up_is_alt_up_or_cmd_up_on_macos_and_backspace(index, qapp):
    assert folders.FolderView(index.read, platform="linux").property("upKeys") == [
        "Alt+Up", "Backspace"
    ]  # fmt: skip
    assert folders.FolderView(index.read, platform="darwin").property("upKeys")[0] == "Ctrl+Up"


def test_the_open_folder_and_the_mode_are_remembered_for_next_time(index, qapp):
    remembered = folders.Remembered()
    v = folders.FolderView(index.read, remembered)
    v.open("Lumen Drift/Tide Tables")
    v.setMode("cards")
    assert remembered == folders.Remembered("Lumen Drift/Tide Tables", "cards")
    again = folders.FolderView(index.read, remembered)
    assert again.property("path") == "Lumen Drift/Tide Tables"
    assert again.property("mode") == "cards"
    with pytest.raises(ValueError):
        again.setMode("huge")
    assert folders.FolderView(index.read, folders.Remembered("Gone", "huge")).property("mode") == (
        "small"
    )  # fmt: skip


# ---------- a folder of songs (R2.9.7) ----------


def test_a_folder_of_songs_has_its_strip_and_marks_the_values_that_differ(view):
    view.open("Lumen Drift/Tide Tables")
    assert view.property("songsMode")
    assert view.property("kicker") == "Folder · 3 songs · 4.0 MB · FLAC 44.1 kHz"
    assert view.property("artLine") == "No cover"
    assert view.property("chips") == [  # R3.9: no album or album artist where the path has them
        {"text": "Missing", "tone": "warn", "tip": "No art, embedded or in the folder"},
        {"text": "Fixable", "tone": "warn", "tip": "Tags match path for 0 of 3 files"},
    ]  # fmt: skip
    assert rows(view, "numbered", "odd") == [
        ("1 · Neap Tide", []), ("2 · Spring Tide", ["genre"]), ("3 · Slack Water", ["artist"])
    ]  # fmt: skip
    assert len(view.property("stripButtons")) == 3
    view.setMode("cards")  # the switch stays, and applies again on leaving the folder
    assert view.property("songsMode") and view.property("mode") == "cards"
    view.up()
    assert not view.property("songsMode") and view.property("mode") == "cards"


# ---------- searching beneath the open folder (R2.9.2) ----------


def test_a_search_lists_the_folders_and_files_beneath_that_match_with_where_they_are(view, qtbot):
    m = view.property("model")
    view.open("Lumen Drift")
    with qtbot.waitSignal(m.countChanged):
        m.set_search("glass")
    assert rows(view, "kind", "name", "where") == [
        ("folder", "2019 - Glass Harbor", ""),
        ("folder", "Glass", "Remixes"),
        ("file", "01.flac", "2019 - Glass Harbor"),  # its title and album; by name, then path
        ("file", "01.flac", "Remixes › Glass"),
        ("file", "02.flac", "2019 - Glass Harbor"),
    ]
    assert rows(view, "line")[1] == ("Remixes · 1 song",)
    assert view.property("count") == "2 folders · 3 songs found"
    assert view.property("filesTitle") == "3 songs" and view.property("thirdLabel") == "FOLDER"
    assert view.property("folderRows") == 2 and not view.property("songsMode")
    with qtbot.waitSignal(m.countChanged):
        m.set_search("rating:>=4")  # asks about songs: no folder's name matches it
    assert rows(view) == [("file", "Lumen Drift - Harbor Lights.flac")]
    view.open("Lumen Drift/Remixes")  # opening a folder ends the search
    assert not m.searching() and rows(view) == [("folder", "Glass")]


# ---------- the selection (R2.9.6) ----------


def test_click_ctrl_click_shift_click_and_the_checkbox_select_folders_and_files(view):
    m = view.property("model")
    view.open("Lumen Drift")
    texts = []
    view.selectionChanged.connect(lambda: texts.append(view.property("selectionText")))
    m.click(0, False, False)
    assert view.property("selectionText") == "1 folder · 2 songs selected"
    m.click(2, True, False)  # Ctrl: added
    assert view.property("selectionText") == "2 folders · 5 songs selected"
    m.click(4, False, True)  # Shift: from the last clicked to it
    assert [m.row(n)["key"] in m._selected for n in range(5)] == [False, False, True, True, True]
    assert view.property("selectionText") == "1 folder · 2 files · 5 songs selected"
    m.toggle(3)
    assert view.property("selectionCount") == 2 and view.property("selectionState") == "some"
    m.click(2, True, False)  # Ctrl on a selected one: taken away
    assert view.property("selectionText") == "1 song selected"
    m.selectAll()
    assert view.property("selectionState") == "all"
    assert view.property("selectionText") == "3 folders · 2 files · 8 songs selected"
    m.clearSelection()
    assert view.property("selectionText") == "" and view.property("selectionState") == "none"
    assert texts[-1] == ""
    m.click(99, False, False)  # no such row: nothing
    assert view.property("selectionCount") == 0


def test_a_drag_box_selects_its_rows_and_a_selection_survives_a_mode_change(view):
    m = view.property("model")
    view.open("Lumen Drift")
    m.selectRows([0, 1], False)
    m.selectRows([3], True)
    view.setMode("list")
    assert [m.data(m.index(n), m._role("selected")) for n in range(5)] == [
        True, True, False, True, False
    ]  # fmt: skip
    assert view.property("selectionText") == "2 folders · 1 file · 4 songs selected"


def test_a_folder_and_a_file_inside_it_count_its_songs_once(view, qtbot):
    m = view.property("model")
    with qtbot.waitSignal(m.countChanged):
        m.set_search("glass")
    m.selectAll()  # Glass Harbor, Glass, and their songs found too
    assert view.property("selectionText") == "2 folders · 3 files · 3 songs selected"


def test_play_plays_the_selections_first_song_and_activate_opens_or_plays(view, index):
    paths = dict(index.read().execute("SELECT id, path FROM song"))
    played = []
    view.play.connect(lambda songs, source: played.append(([paths[i] for i in songs], source)))
    m = view.property("model")
    view.open("Lumen Drift")
    m.click(4, False, False)
    m.click(1, True, False)
    view.playSelection()  # Remixes comes first in the list, then the file: all of them queued
    both = ["Lumen Drift/Remixes/Glass/01.flac", "Lumen Drift/Lumen Drift - Harbor Lights.flac"]
    assert played == [(both, "Lumen Drift")]
    m.clearSelection()
    m.click(4, False, False)
    view.playSelection()
    view.playRow(0)  # a folder's play button: its songs, from its first
    view.playRow(3)  # a file's: it and the files after it
    view.playRow(99)
    assert played[1:] == [
        (["Lumen Drift/Lumen Drift - Harbor Lights.flac"], "Lumen Drift"),
        (["Lumen Drift/2019 - Glass Harbor/01.flac", "Lumen Drift/2019 - Glass Harbor/02.flac"],
         "2019 - Glass Harbor"),
        (["Lumen Drift/ebb & flow.mp3", "Lumen Drift/Lumen Drift - Harbor Lights.flac"],
         "Lumen Drift"),
    ]  # fmt: skip
    view.activate(4)
    assert played[-1] == (["Lumen Drift/Lumen Drift - Harbor Lights.flac"], "Lumen Drift")
    view.activate(1)
    assert view.property("path") == "Lumen Drift/Remixes"
    view.activate(99)
    m.clearSelection()
    view.playSelection()  # nothing selected: nothing
    assert len(played) == 5


def test_a_rows_songs_are_what_its_menu_queues_and_the_roots_name_is_its_title(view, index):
    paths = dict(index.read().execute("SELECT id, path FROM song"))
    m = view.property("model")
    assert m.source() == folders.ROOT_TITLE and m.queue_from(99) == ([], "")
    view.open("Lumen Drift")
    assert [paths[i] for i in m.songs_at(2)] == [
        "Lumen Drift/Tide Tables/01 - Neap Tide.flac",
        "Lumen Drift/Tide Tables/02 - Spring Tide.flac",
        "Lumen Drift/Tide Tables/03 - Slack Water.flac",
    ]
    assert [paths[i] for i in m.songs_at(3)] == ["Lumen Drift/ebb & flow.mp3"]
    assert paths[m.song_at(3)] == "Lumen Drift/ebb & flow.mp3" and m.song_at(2) is None  # R10.2
    assert m.songs_at(99) == []
    # Show in file manager's (R2.9.6): a row's folder or file, by its path under the root
    assert (
        m.path_at(2) == "Lumen Drift/Tide Tables" and m.path_at(3) == "Lumen Drift/ebb & flow.mp3"
    )
    assert m.path_at(99) is None
    queued, source = m.queue_from(3)
    assert [paths[i] for i in queued][0] == "Lumen Drift/ebb & flow.mp3" and source == "Lumen Drift"
    m.selectRows([2, 1], False)  # a folder and the folder beside it, in the list's order
    assert [paths[i] for i in m.selected_songs()][0] == "Lumen Drift/Remixes/Glass/01.flac"


def test_album_art_is_offered_for_a_selection_or_a_row_whose_songs_are_one_album(view, index):
    """R2.9.6: the selection bar has Album art, before Organize…, when the songs selected are one
    album, and so does a row's menu, for the selection when the row is in it."""
    (album,) = index.read().execute("SELECT id FROM album WHERE title = 'Glass Harbor'").fetchone()
    m = view.property("model")
    view.open("Lumen Drift")
    names = [name for _kind, name in rows(view)]
    glass, tide = names.index("2019 - Glass Harbor"), names.index("Tide Tables")
    assert view.property("selectedAlbum") == -1
    assert view.property("laterActions") == folders.LATER
    m.click(glass, False, False)
    assert view.property("selectedAlbum") == album
    assert [a["label"] for a in view.property("laterActions")] == [
        "Add to playlist", "Edit tags", "Infer from path", "Album art", "Organize…"
    ]  # fmt: skip
    assert m.albumAt(glass) == album and m.albumAt(tide) == -1  # songs on no album
    m.click(tide, True, False)  # and a folder of songs on none
    assert view.property("selectedAlbum") == -1 and m.albumAt(glass) == -1
    assert "Album art" not in [a["label"] for a in view.property("laterActions")]
    assert m.albumAt(99) == -1
    view.open("Lumen Drift/2019 - Glass Harbor")
    assert m.albumAt(0) == album  # a file's own
    assert folders.ART in view.property("stripButtons")


def test_the_folder_holding_the_song_playing_is_marked(view):
    m = view.property("model")
    view.open("Lumen Drift")
    m.set_playing("Lumen Drift/Remixes/Glass/01.flac")
    playing = [m.data(m.index(n), m._role("playing")) for n in range(5)]
    assert playing == [False, True, False, False, False]
    m.set_playing("Lumen Drift/ebb & flow.mp3")
    assert m.data(m.index(3), m._role("playing")) is True


# ---------- in the library (R2.6, R6.3, R6.4) ----------


@pytest.fixture
def lib(index, tmp_path, qapp):
    library = bridges.Library(os.path.join(str(tmp_path), "Music"), index, str(tmp_path))
    yield library
    library.wait()


def test_folders_in_the_header_its_crumbs_count_modes_sort_and_search_hint(lib, qtbot):
    lib.show("folders")
    assert lib.property("title") == "Your music folders" and lib.property("crumbs") == []
    assert lib.property("viewCount") == "3 folders · 10 songs"
    assert [m["mode"] for m in lib.property("modes")] == ["large", "small", "cards", "list"]
    assert lib.property("mode") == "small" and lib.property("sortText") == "Sort: Name"
    assert lib.property("searchHint") == "Search folders"
    lib.setSort("name")
    lib.setMode("large")
    assert lib.property("mode") == "large"
    lib.property("folders").open("Lumen Drift")
    assert lib.property("crumbs") == [{"name": "Lumen Drift", "path": "Lumen Drift"}]
    with qtbot.waitSignal(lib.property("folders").property("model").countChanged):
        lib.setSearch("zebra")
    assert lib.property("emptyText") == "No folders or songs match “zebra”"
    lib.property("folders").up()  # another folder: its search is gone
    assert lib.property("search") == "" and lib.property("view") == "folders"
    lib.show("songs")
    assert lib.property("crumbs") == [] and lib.property("searchHint") == "Search the library"
    lib.setMode("list")
    assert lib.property("albumsMode") == "list"


def test_the_sidebars_folders_opens_where_it_was_left_and_again_returns_to_the_root(lib):
    lib.show("folders")
    lib.property("folders").open("Lumen Drift")
    lib.show("albums")
    lib.show("folders")
    assert lib.property("folders").property("path") == "Lumen Drift"
    lib.show("folders")
    assert lib.property("folders").property("path") == ""


def test_the_tour_opens_folders_at_a_folder_in_a_mode_with_rows_selected(lib):
    lib.go({"view": "folders", "folder": "Lumen Drift", "mode": "cards",
            "select": ["Lumen Drift/Remixes", "Lumen Drift/ebb & flow.mp3"]})  # fmt: skip
    f = lib.property("folders")
    assert f.property("path") == "Lumen Drift" and f.property("mode") == "cards"
    assert f.property("selectionText") == "1 folder · 1 file · 2 songs selected"


def test_the_song_playing_marks_its_folder_in_the_library(lib):
    lib.show("folders")
    lib.show_playing("Mara Okafor/Kindling/01.mp3")
    m = lib.property("folders").property("model")
    assert m.data(m.index(2), m._role("playing")) is True


# ---------- tags match path (R3.9, R2.9.5, R2.9.7) ----------


def test_a_files_chip_says_in_a_word_whether_its_tags_match_its_path_and_its_tooltip_how():
    """R3.9, L05, L08: Match, Fixable or Untagged; the tooltip a line for each tag that differs,
    what the path says and what the tags do (that part left out where the index doesn't know
    it); none when no pattern fits."""
    from musikata_core.patterns import BARE, FIX, MATCH, Difference

    year = Difference("year", "missing", "2022")
    artist = Difference("artist", "case", "Lumen Drift", "lumen drift")
    genre = Difference("genres", "differs", "Ambient", "Electronic")
    assert folders.file_chip(MATCH, ()) == {
        "text": "Match", "tone": "ok", "tip": "Its tags match its path"}  # fmt: skip
    assert folders.file_chip(FIX, (genre,)) == {
        "text": "Fixable", "tone": "warn",
        "tip": "Genre differs: the path says Ambient, the tags Electronic"}  # fmt: skip
    assert folders.file_chip(FIX, (artist, year))["tip"] == (
        "Artist case differs: the path says Lumen Drift, the tags lumen drift\n"
        "Year missing: the path says 2022"
    )
    assert folders.difference_tip(Difference("album", "differs", "Tide Tables")) == (
        "Album differs: the path says Tide Tables")  # fmt: skip
    assert folders.file_chip(BARE, (year,)) == {
        "text": "Untagged", "tone": "err",
        "tip": "No tags at all\nYear missing: the path says 2022"}  # fmt: skip
    assert folders.file_chip(BARE, ())["tip"] == "No tags at all"
    assert folders.file_chip(None, ()) == {}


CHIPS = """
import QtQuick
import QtQuick.Controls.Basic
import "."
Window {
    width: 300; height: 120
    property bool shown: chip.ToolTip.visible
    property string shows: chip.ToolTip.text
    property string described: chip.Accessible.description
    property bool plainShown: plain.ToolTip.visible
    Chip {
        id: chip; objectName: "chip"; x: 20; y: 20; label: "Fixable"; tone: "warn"
        tip: "Year missing"
    }
    Chip { id: plain; x: 20; y: 70; label: "Match"; tone: "ok" }
}
"""


@pytest.mark.slow
def test_a_chips_tooltip_shows_on_hover_and_with_the_focus_and_a_screen_reader_reads_it(qtbot):
    """R3.9, R2.9.5, R2.9.7: a state's chip says one word and its tooltip the detail, as the app's
    other controls do theirs: on hover, and while it has the focus (R18.2); its accessible
    description is the tooltip (R18.1); a chip with no tip has none."""
    from PySide6.QtCore import QPoint, QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem

    engine = QQmlEngine()
    qml = os.path.join(os.path.dirname(folders.__file__), "qml", "ChipsTest.qml")
    component = QQmlComponent(engine)
    component.setData(CHIPS.encode(), QUrl.fromLocalFile(qml))
    w = component.create()
    assert w is not None, component.errorString()
    try:
        w.show()
        qtbot.waitExposed(w)
        chip = w.findChild(QQuickItem, "chip")
        assert not w.property("shown") and w.property("shows") == "Year missing"
        assert w.property("described") == "Year missing"
        qtbot.mouseMove(w, QPoint(250, 10))  # into the window, then onto the chip
        qtbot.mouseMove(w, QPoint(30, 30))
        qtbot.waitUntil(lambda: w.property("shown"))  # after the app's tooltips' delay
        qtbot.mouseMove(w, QPoint(30, 80))  # over the chip with no tip
        qtbot.waitUntil(lambda: not w.property("shown"))
        assert not w.property("plainShown")
        chip.forceActiveFocus()
        qtbot.waitUntil(lambda: w.property("shown"))
        chip.setProperty("tip", "")
        assert not w.property("shown")
    finally:
        w.close()
        w.deleteLater()
        engine.deleteLater()


def test_a_folders_state_is_a_dot_and_a_chip_and_a_folder_of_songs_says_how_many_match():
    """R2.9.5 (L04, L06): a dot amber or red, a chip Fixable or Untagged with how many files in
    its tooltip, none when all match; R2.9.7, L02 (L08): Match, Fixable or Untagged, how many
    match in its tooltip."""
    assert folders.folder_chip(1, 3) == {
        "text": "Fixable", "tone": "warn", "tip": "3 files can be fixed from the path"}  # fmt: skip
    assert folders.folder_chip(1, 1)["tip"] == "1 file can be fixed from the path"
    assert folders.folder_chip(2, 3) == {"text": "Untagged", "tone": "err",
                                         "tip": "Some files have no tags; 3 files to fix from"
                                                " the path in all"}  # fmt: skip
    assert folders.folder_chip(0, 0) == {} and folders.folder_chip(None, 0) == {}
    assert folders.folder_chip(1, 0) == {}
    assert folders.TONES == {1: "warn", 2: "err"}
    assert folders.match_chip([0, 0, None]) == {
        "text": "Fixable", "tone": "warn", "tip": "Tags match path for 2 of 3 files"}  # fmt: skip
    assert folders.match_chip([0, 0]) == {
        "text": "Match", "tone": "ok", "tip": "Tags match path for 2 of 2 files"}  # fmt: skip
    assert folders.match_chip([0, 2]) == {
        "text": "Untagged", "tone": "err", "tip": "Tags match path for 1 of 2 files; 1 has no"
                                                  " tags"}  # fmt: skip
    assert folders.match_chip([2, 2, 1])["tip"].endswith("for 0 of 3 files; 2 have no tags")
    assert folders.match_chip([None]) == {} and folders.match_chip([]) == {}


def test_the_strip_says_what_the_path_says_and_how_the_files_differ_as_l08_does():
    """R2.9.7: "The path says the album is from 2022, but 1 file has no year and 1 spells the
    artist in lower case."; files that differ in what varies file by file are counted alone."""
    from musikata_core.patterns import Difference

    year = Difference("year", "missing", "2022")
    artist = Difference("artist", "case", "Lumen Drift")
    assert folders.path_line([((year,), {"year": ""}), ((artist,), {"artist": "lumen drift"})]) \
        == ("The path says the album is from 2022, but 1 file has no year and 1 spells the"
            " artist in lower case.")  # fmt: skip
    assert folders.path_line([((artist,), {"artist": "lumen drift"})]) == (
        "The path says the artist is Lumen Drift, but 1 file spells it in lower case."
    )
    upper = [((artist,), {"artist": "LUMEN DRIFT"}), ((artist,), {"artist": "LUMEN DRIFT"})]
    assert folders.path_line(upper).endswith("but 2 files spell it in capitals.")
    odd = Difference("albumartist", "case", "Lumen Drift")
    assert folders.path_line([((odd,), {"albumartist": "lUMEN dRIFT"})]).endswith(
        "spells it in another case.")  # fmt: skip
    titles = [((Difference("title", "differs", "Ebb"),), {"title": "Eb"}),
              ((Difference("title", "missing", "Bore"), Difference("genres", "differs", "Pop")),
               {"title": "", "genres": "Rock"})]  # fmt: skip
    assert folders.path_line(titles) == (
        "The tags differ from the path: 1 file has another title, 1 has no title and 1 has"
        " another genre."
    )
    assert folders.path_line([]) == ""
    assert folders.and_text(["a"]) == "a" and folders.and_text([]) == ""


def test_folders_and_files_carry_their_path_match_and_the_strip_its_chip_and_line(tmp_path, qapp):
    """R2.9.5: each folder's dot and chip; R3.9: each file's chip; R2.9.7: the strip's chip and
    line; R2.9.6, R2.9.7: Infer from path on the selection bar and the strip."""
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, [{"path": f"Lumen Drift/Tide Tables/0{n} - T{n}.flac", "title": f"T{n}", "track": n,
              "albumartist": a, "album": "Tide Tables"}
             for n, a in ((1, "Lumen Drift"), (2, "lumen drift"))])  # fmt: skip
    v = folders.FolderView(i.read)
    try:
        assert rows(v, "name", "dot", "pathChip") == [
            ("Lumen Drift", "warn", {"text": "Fixable", "tone": "warn",
                                     "tip": "1 file can be fixed from the path"})]  # fmt: skip
        v.open("Lumen Drift/Tide Tables")
        assert rows(v, "pathChip") == [
            ({"text": "Match", "tone": "ok", "tip": "Its tags match its path"},),
            (
                {
                    "text": "Fixable",
                    "tone": "warn",
                    "tip": "Album artist case differs: the path"
                    " says Lumen Drift, the tags lumen drift",
                },
            ),
        ]
        assert v.property("chips")[-1] == {"text": "Fixable", "tone": "warn",
                                           "tip": "Tags match path for 1 of 2 files"}  # fmt: skip
        assert v.property("pathLine") == (
            "The path says the album artist is Lumen Drift, but 1 file spells it in lower case."
        )
        assert v.property("stripButtons")[0]["action"] == "infer"
        assert folders.INFER in folders.selection_actions(False)
        assert folders.INFER["later"] == ""
    finally:
        v.property("model").wait()
        i.close()
