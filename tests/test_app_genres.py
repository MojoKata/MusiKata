"""Genres in the running app (src/musikata/genres.py; R9, G01-genres): the Genres view's tiles and a
genre's page, the ⋯ menu's Rename…, Merge into…, Play all and Select its songs, and the banner of
genres that look like one, with Review… and Not now, saving through the preview, the batch and the
change history.

Why: a rename or a merge rewrites every file that has the genre; it must show which files change
before it does, save them as one entry Undo puts back, and leave the views showing the genres as
they now are. And the view's counts and covers come off the GUI thread, so a test of them waits for
them as the view does."""

import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeClock, FakeEngine, fill
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, bridges, layout, tour
from musikata import genres as genres_app
from musikata.genres import (
    Genres,
    GenresModel,
    banner_of,
    choices_of,
    count_of,
    merge_description,
    names_text,
    rename_description,
    tile_line,
    tile_row,
    tone_of,
)
from musikata.history import ChangeHistory
from musikata_core import db, scanner, settings, tags
from musikata_core.genres import Group, Tile
from musikata_core.tags import Failed, Job, Outcome

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
NOW = datetime(2026, 11, 26, 21, 0, tzinfo=UTC)


# ---------- what a tile and the banner say ----------


def test_a_tile_says_its_songs_and_albums_and_keeps_its_tint_wherever_it_is():
    """G01-genres: "214 songs · 18 albums" under the name, three covers, a tint of its own."""
    assert tile_line(214, 18) == "214 songs · 18 albums"
    assert tile_line(1, 1) == "1 song · 1 album" and tile_line(3, 0) == "3 songs"
    row = tile_row(Tile("Electronic", 1214, 18, ("a", "b")))
    assert row == {"name": "Electronic", "line": "1,214 songs · 18 albums",
                   "covers": ["image://covers/a", "image://covers/b"],
                   "tone": tone_of("Electronic"), "songs": 1214}  # fmt: skip
    assert tone_of("Jazz") == tone_of("jazz") and 0 <= tone_of("Jazz") < 8
    assert len({tone_of(g) for g in ("Electronic", "Jazz", "Folk", "Soul", "Pop", "Rock")}) > 2


def test_the_banner_says_the_names_their_songs_and_how_many_files_merging_rewrites():
    """R9.5 and G01-genres' own words."""
    group = Group(("Electronic", "Electronica", "electronic"), (214, 17, 6))
    assert banner_of(group, 23) == {
        "title": "These look like one genre: Electronic (214), Electronica (17), electronic (6)",
        "detail": "Merging rewrites the genre tag in 23 files. Undo puts them back.",
    }
    assert banner_of(Group(("Hip-Hop", "hip hop"), (1200, 1)), 1, undoable=False) == {
        "title": "These look like one genre: Hip-Hop (1,200), hip hop (1)",
        "detail": "Merging rewrites the genre tag in 1 file.",
    }
    assert banner_of(None, 0) == {}


def test_a_rename_and_a_merge_are_named_in_the_change_history():
    """R4.9: each save one entry, said in words."""
    assert names_text(["A"]) == "A" and names_text(["A", "B"]) == "A and B"
    assert names_text(["A", "B", "C"]) == "A, B and C" and names_text([]) == ""
    assert rename_description("Electronica", "Electronic", 17) == (
        "Genre Electronica renamed Electronic on 17 songs"
    )
    assert merge_description(["Electronic", "Electronica", "electronic"], "Electronic", 23) == (
        "Electronica and electronic merged into Electronic on 23 songs"
    )
    assert merge_description(["Jazz"], "Soul", 1) == "Jazz merged into Soul on 1 song"


def test_merge_into_offers_the_genres_that_look_like_it_first_then_the_most_used():
    counts = {"Electronic": 214, "Electronica": 17, "electronic": 6, "Jazz": 140, "Folk": 96}
    groups = [Group(("Electronic", "electronic"), (214, 6))]
    assert choices_of("electronic", counts, groups) == ["Electronic", "Jazz", "Folk",
                                                        "Electronica"]  # fmt: skip
    assert choices_of("Folk", counts, groups, 2) == ["Electronic", "Jazz"]
    assert choices_of("Folk", {"Folk": 1}, []) == []


# ---------- the view and a genre's page ----------


SONGS = [
    {"path": "A/One/01.flac", "title": "Neap Tide", "artist": "A", "album": "One",
     "albumartist": "A", "genres": ("Electronic", "Ambient"), "has_cover": True, "track": 1,
     "rating": 4},
    {"path": "A/One/02.flac", "title": "Spring Tide", "artist": "A", "album": "One",
     "albumartist": "A", "genres": ("Electronic",), "has_cover": True, "track": 2, "rating": 2},
    {"path": "A/Two/01.flac", "title": "Slack Water", "artist": "A", "album": "Two",
     "albumartist": "A", "genres": ("electronic",)},
    {"path": "B/Three/01.flac", "title": "Blue Hour", "artist": "B", "album": "Three",
     "albumartist": "B", "genres": ("Jazz",)},
    {"path": "Loose/single.flac", "title": "Moonpull", "artist": "C", "genres": ("Electronic",)},
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


def came(model, qtbot):
    qtbot.waitUntil(lambda: not model.pending(), timeout=WAIT)


def names(model):
    return [model.name_at(i) for i in range(model.rowCount())]


def test_the_genres_view_has_a_tile_per_genre_by_songs_or_by_name(lib, qtbot):
    """R9.1: the sidebar's Genres opens it; its tiles, sorted as the header's sort says."""
    lib.show("genres")
    model = lib.property("genreList")
    came(model, qtbot)
    assert names(model) == ["Electronic", "Ambient", "electronic", "Jazz"]
    first = {r: model.data(model.index(0), 256 + i) for i, r in enumerate(("name", "line"))}
    assert first == {"name": "Electronic", "line": "3 songs · 1 album"}
    assert lib.property("title") == "Genres" and lib.property("viewCount") == "4 genres"
    assert lib.property("sortText") == "Sort: Songs" and lib.property("section") == "genres"
    assert [s["sort"] for s in lib.property("sorts")] == ["songs", "name"]
    lib.setSort("name")
    came(model, qtbot)
    assert names(model) == ["Ambient", "Electronic", "electronic", "Jazz"]
    assert lib.property("sortText") == "Sort: Name"
    with pytest.raises(ValueError, match="no such order"):
        lib.setSort("year")


def test_a_search_leaves_the_genres_of_the_songs_it_finds(lib, qtbot):
    """R2.7 in the Genres view: "2 of 4 genres"; a search that finds none says so."""
    lib.show("genres")
    model = lib.property("genreList")
    came(model, qtbot)
    lib.setSearch("neap")
    came(model, qtbot)
    assert names(model) == ["Electronic", "Ambient"]
    assert lib.property("viewCount") == "2 of 4 genres" and count_of(model) == "2 of 4 genres"
    lib.setSearch("zebra")
    came(model, qtbot)
    assert names(model) == [] and lib.property("emptyText") == "No genres match “zebra”"


def test_a_tile_opens_the_genres_page_of_its_albums_and_songs_and_back_returns(lib, qtbot):
    """R9.1: a page like an artist's, its search filtering it (R2.7)."""
    lib.show("genres")
    lib.openGenre("Electronic")
    page = lib.property("genrePage")
    assert lib.property("view") == "genre" and lib.property("backText") == "Genres"
    assert page.property("name") == "Electronic"
    assert page.property("detail") == "1 album · 3 songs"
    assert len(page.property("tiles")) == 1 and page.property("average")["stars"] == 3
    albums, songs = page.property("albums"), page.property("songs")
    assert [albums.row(i)["title"] for i in range(albums.rowCount())] == ["One"]
    assert [songs.row(i)["title"] for i in range(songs.rowCount())] == [
        "Neap Tide", "Spring Tide", "Moonpull"
    ]  # fmt: skip
    assert page.property("songsTitle") == "Songs" and lib.property("searchHint") == (
        "Search this genre"
    )
    lib.setSearch("moon")
    came(songs, qtbot)
    came(albums, qtbot)
    assert songs.rowCount() == 1 and albums.rowCount() == 0
    assert lib.property("viewCount") == "0 of 1 album · 1 of 3 songs"
    lib.openAlbum(albums.row(0)["albumId"] if albums.rowCount() else 1)
    assert lib.property("view") == "album" and lib.property("backText") == "Electronic"
    lib.back()
    assert lib.property("view") == "genre" and lib.property("search") == "moon"
    lib.back()
    assert lib.property("view") == "genres"
    assert not page.load("Nothing")


def test_select_its_songs_selects_every_song_of_the_genre_on_its_page(lib, qtbot):
    """R9.4: Select its songs; Ctrl+E then edits them, a rating rates them (R4.2, R10.2)."""
    lib.show("genres")
    lib.setSearch("neap")
    lib.selectGenre("Electronic")
    songs = lib.property("genrePage").property("songs")
    came(songs, qtbot)
    assert lib.property("view") == "genre" and lib.property("search") == ""
    assert songs.property("selectionCount") == 3
    lib.openGenre("Electronic")  # already open: stays as it is
    assert songs.property("selectionCount") == 3


def test_a_genre_gone_after_a_save_sends_its_page_back_to_genres(lib, index, qtbot):
    lib.show("genres")
    lib.openGenre("Jazz")
    index.write(lambda c: c.execute("DELETE FROM song_genre WHERE genre = 'Jazz'")).result()
    lib.reload()
    assert lib.property("view") == "genres"


def test_the_tour_opens_a_genres_page_by_its_name(lib):
    lib.go({"view": "genre", "genre": "Jazz", "search": "blue"})
    assert lib.property("view") == "genre" and lib.property("search") == "blue"
    assert lib.property("genrePage").property("name") == "Jazz"


def test_play_all_plays_the_genres_songs_in_its_pages_order(lib, index, qtbot):
    """R9.4's Play all, R7.1: from its first song."""
    player = bridges.Player(str(lib.property("root")), FakeEngine(), read=index.read)
    player.playGenre("Electronic")
    c = index.read()
    titles = [c.execute("SELECT title FROM song WHERE id = ?", (e.song,)).fetchone()[0]
              for e in player.queue.order]  # fmt: skip
    assert titles == ["Neap Tide", "Spring Tide", "Moonpull"]
    player.close()


def test_a_genres_model_shows_nothing_until_its_rows_come_and_keeps_its_tiles_read_again(
    index, qapp, qtbot, monkeypatch
):
    """A large library's tiles come from the search thread (A1.3); a small one's at once."""
    fill(index, SONGS)
    model = GenresModel(index.read)
    model.reload()
    assert not model.pending() and model.rowCount() == 4  # five songs: at once
    monkeypatch.setattr(genres_app, "SHORT", 3)  # a library past it
    model = GenresModel(index.read)
    assert model.rowCount() == 0 and model.total() == 0 and not model.searching()
    model.reload()
    assert model.pending() and model.rowCount() == 0
    came(model, qtbot)
    with qtbot.assertNotEmitted(model.modelReset):
        model.refresh()
        came(model, qtbot)
    assert model.rowCount() == 4 and model.name_at(9) == "" and not model.filtered()
    assert model.data(model.index(0), 0) is None and model.shown_search() == ""
    with pytest.raises(ValueError, match="no such order"):
        model.sort_by("albums")
    model.show_ratings({})
    model.wait()


# ---------- renaming and merging, through the preview and the history ----------


TIDE = [  # title, genres
    ("Neap Tide", ["Electronica"]),
    ("Spring Tide", ["electronic"]),
    ("Slack Water", ["Electronic", "Ambient"]),
    ("Moonpull", ["Electronic"]),
]


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """Four songs of Tide Tables as FLAC, their genres as the demo library's are."""
    d = tmp_path_factory.mktemp("made")
    out = []
    for n, (title, genre) in enumerate(TIDE, 1):
        path = str(d / f"{n:02d}.flac")
        demo.encode(path, "flac", 0.2, 330 + 110 * n)
        t = {"title": title, "artist": "Lumen Drift", "album": "Tide Tables", "track": n,
             "genre": genre}  # fmt: skip
        demo.tag(path, demo.Song(path, "flac", t))
        out.append(path)
    return out


@pytest.fixture
def root(made, tmp_path):
    """A root of the four songs with an index that has them: (root, index, paths)."""
    music = tmp_path / "Music"
    (music / "TT").mkdir(parents=True)
    (music / ".musikata").mkdir()
    batch, paths = [], []
    for n, src in enumerate(made, 1):
        rel = f"TT/{n:02d}.flac"
        full = scanner.full_path(str(music), rel)
        shutil.copyfile(src, full)
        t, info = tags.read(full)
        st = os.stat(full)
        batch.append(scanner.Read(scanner.Seen(rel, st.st_size, st.st_mtime_ns), t, info, rel))
        paths.append(full)
    index = db.Index(str(tmp_path / "musikata.db"))
    index.write(lambda c: scanner.write_batch(c, batch, {})).result()
    yield str(music), index, paths
    index.close()


def write(job):
    return tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)


def make(root, write=write, same=(), available=lambda: True, history_on=True):
    music, index, _paths = root
    h = ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop",
                      settings.RootTags(), executor=ThreadPoolExecutor(1), watching=False,
                      message_ms=60_000)  # fmt: skip
    saved = []

    def save_rows(written):
        saved.extend(written)
        index.write(lambda c: scanner.wrote(c, music, list(written))).result()

    g = Genres(music, index.read, write, h if history_on else None, saved=save_rows, same=same,
               executor=ThreadPoolExecutor(1), available=available)  # fmt: skip
    g.history_, g.saved_ = h, saved
    return g


@pytest.fixture
def genres_(root, qapp):
    g = make(root)
    yield g
    g.shut()
    g.history_.close()


def read_banner(g, qtbot):
    g.refresh()
    qtbot.waitUntil(lambda: not g.property("reading"), timeout=WAIT)
    return g.property("banner")


def opened(g, qtbot):
    qtbot.waitUntil(lambda: g.property("footer") != "Reading the songs…", timeout=WAIT)


def entries(index, qtbot):
    """The change history's entries, once the index has them (ChangeHistory reads them)."""
    sql = "SELECT action, description FROM change WHERE action != 'undo' ORDER BY time"
    qtbot.waitUntil(lambda: index.read().execute(sql).fetchall() != [], timeout=WAIT)
    return index.read().execute(sql).fetchall()


def genres_of(paths):
    return [tags.read(p)[0].genres for p in paths]


def test_the_banner_offers_the_group_with_the_most_songs_and_not_now_the_next(genres_, qtbot):
    """R9.5: Electronic and electronic look like one; Electronica only once the user says so."""
    assert read_banner(genres_, qtbot) == {
        "title": "These look like one genre: Electronic (2), electronic (1)",
        "detail": "Merging rewrites the genre tag in 1 file. Undo puts them back.",
    }
    genres_.notNow()
    qtbot.waitUntil(lambda: not genres_.property("reading"), timeout=WAIT)
    assert genres_.property("banner") == {}
    genres_.review()  # no group: nothing to review
    assert not genres_.property("opened")
    genres_.refresh()  # read again in this run: Not now holds
    qtbot.waitUntil(lambda: not genres_.property("reading"), timeout=WAIT)
    assert genres_.property("banner") == {}


def test_genres_the_user_said_are_the_same_are_offered_together(root, qapp, qtbot):
    g = make(root, same=[["Electronic", "Electronica"]])
    try:
        assert read_banner(g, qtbot)["title"] == (
            "These look like one genre: Electronic (2), electronic (1), Electronica (1)"
        )
        assert read_banner(g, qtbot)["detail"].startswith(
            "Merging rewrites the genre tag in 2 files"
        )
    finally:
        g.shut()
        g.history_.close()


def test_review_shows_the_merges_preview_and_saves_it_as_one_entry_undo_puts_back(
    root, qapp, qtbot
):
    """R9.5's Review…: the merge's preview with the most used name chosen; R9.4: the files that
    change saved through the batch, one entry in the change history, Undo putting them back."""
    music, index, paths = root
    g = make(root, same=[["Electronic", "Electronica"]])
    try:
        read_banner(g, qtbot)
        g.review()
        opened(g, qtbot)
        assert g.property("opened") and g.property("tool") == "merge"
        assert g.property("title") == "Merge into one genre"
        assert "with Electronic, electronic or Electronica gets" in g.property("about")
        options = g.property("options")
        assert [(f["name"], f["chosen"]) for f in options["fields"]] == [
            ("Electronic", True), ("electronic", False), ("Electronica", False)
        ]  # fmt: skip
        assert options["single"] and options["choose"] == "into"
        preview = g.property("preview")
        assert preview.property("total") == 4
        assert g.property("footer").startswith("2 files · 2 changes")
        assert g.property("saveLabel") == "Save 2 files" and g.property("saveLater") == ""
        h = g.history_
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            g.save()
        assert not g.property("opened")
        assert genres_of(paths) == [("Electronic",), ("Electronic",), ("Electronic", "Ambient"),
                                    ("Electronic",)]  # fmt: skip
        assert h.property("message")["text"] == "Saved 2 files" and h.property("message")["undo"]
        assert sorted(os.path.basename(w.path) for w in g.saved_) == ["01.flac", "02.flac"]
        assert entries(index, qtbot) == [
            ("genres", "electronic and Electronica merged into Electronic on 2 songs")
        ]
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            h.undoMessage()
        # Undo writes the files one at a time: waited for until both are back
        qtbot.waitUntil(
            lambda: genres_of(paths)[:2] == [("Electronica",), ("electronic",)], timeout=WAIT
        )
    finally:
        g.shut()
        g.history_.close()


def test_choosing_another_name_merges_into_it_and_unchecking_a_file_leaves_it(genres_, qtbot):
    genres_.refresh()
    qtbot.waitUntil(lambda: not genres_.property("reading"), timeout=WAIT)
    genres_.mergeInto("Electronic")
    opened(genres_, qtbot)
    fields = genres_.property("options")["fields"]
    assert [f["name"] for f in fields] == ["electronic", "Ambient", "Electronica"]
    assert genres_.property("title") == "Merge Electronic into…"
    genres_.toggleField("Electronica")
    assert genres_.property("footer").startswith("2 files · 2 changes")
    genres_.setOption("into", "Not offered")  # only a genre offered can be chosen
    assert [f["chosen"] for f in genres_.property("options")["fields"]] == [False, False, True]
    preview = genres_.property("preview")
    first = next(i for i in range(4) if preview.row(i)["changed"])
    preview.toggle(first)
    assert genres_.property("saveLabel") == "Save 1 file"
    with pytest.raises(ValueError, match="no such option"):
        genres_.setOption("field", "x")
    genres_.close()
    assert not genres_.property("opened") and genres_.property("options") == {}


def test_rename_takes_the_new_name_as_typed_and_says_why_one_cant_be_written(root, qapp, qtbot):
    """R9.4's Rename…: every song with the genre gets the new name."""
    music, index, paths = root
    g = make(root)
    try:
        g.rename("Electronica")
        opened(g, qtbot)
        assert g.property("title") == "Rename Electronica"
        assert g.property("options") == {"name": "Electronica"}
        assert g.property("saveLater") == "Nothing to save"  # the name it has: no change
        g.setOption("name", "Rock; Pop")
        assert "can't hold ;" in g.property("problem") and g.property("saveLater")
        g.save()  # nothing saved while the name can't be written
        assert g.property("opened")
        g.setOption("name", " Electronic Dance ")
        assert g.property("problem") == "" and g.property("saveLabel") == "Save 1 file"
        with qtbot.waitSignal(g.history_.messageChanged, timeout=WAIT):
            g.save()
        assert genres_of(paths)[0] == ("Electronic Dance",)
        assert entries(index, qtbot) == [
            ("genres", "Genre Electronica renamed Electronic Dance on 1 song")
        ]
    finally:
        g.shut()
        g.history_.close()


def test_merge_into_with_no_other_genre_says_so(root, qapp, qtbot):
    music, index, _paths = root
    g = make(root)
    try:
        g.mergeInto("Electronica")  # its counts not read yet: nothing offered
        opened(g, qtbot)
        assert g.property("problem") == "There's no other genre to merge it into"
        assert g.property("saveLater") == "Nothing to save"
    finally:
        g.shut()
        g.history_.close()


def test_files_that_fail_are_named_with_why_and_retry_saves_them(root, qapp, qtbot):
    """R4.7: the others saved; the dialog stays open on the failure, with Retry."""
    music, index, paths = root
    failing = {"on": True}

    def flaky(job):
        if failing["on"] and job.path.endswith("02.flac"):
            raise tags.WriteError(job.path, "it is read-only")
        return write(job)

    g = make(root, write=flaky, same=[["Electronic", "Electronica"]])
    try:
        read_banner(g, qtbot)
        g.review()
        opened(g, qtbot)
        with qtbot.waitSignal(g.history_.messageChanged, timeout=WAIT):
            g.save()
        assert g.property("opened")
        assert g.property("problem") == "1 file wasn't saved: 02.flac it is read-only"
        assert g.property("saveLabel") == "Retry 1 file" and g.property("saveLater") == ""
        failing["on"] = False
        with qtbot.waitSignal(g.history_.messageChanged, timeout=WAIT):
            g.save()
        assert not g.property("opened") and genres_of(paths)[1] == ("Electronic",)
    finally:
        g.shut()
        g.history_.close()


def test_a_save_waits_for_the_root_and_shows_its_progress_and_cancel_stops_it(root, qapp, qtbot):
    """R2.10: nothing is saved while the root isn't there; R4.7: progress, and Cancel between
    files."""
    music, index, paths = root
    there = {"yes": False}
    started = []

    def slow(job):
        started.append(job)
        if len(started) == 1:
            g.close()  # Cancel while the first file is written: it is finished, the rest not
            assert g.property("saving") and g.property("saveLater") == "A save is going on"
        return write(job)

    g = make(root, write=slow, same=[["Electronic", "Electronica"]],
             available=lambda: there["yes"], history_on=False)  # fmt: skip
    try:
        read_banner(g, qtbot)
        g.review()
        opened(g, qtbot)
        assert "Undo can't put them back" in g.property("footer")
        g.save()
        assert not g.property("saving") and not started
        there["yes"] = True
        with qtbot.waitSignal(g.changed, timeout=WAIT, check_params_cb=lambda: True):
            g.save()
        qtbot.waitUntil(lambda: not g.property("saving"), timeout=WAIT)
        assert len(started) == 1 and not g.property("opened")
    finally:
        g.shut()
        g.history_.close()


def test_the_progress_of_a_save_is_said_in_the_footer(root, qapp, qtbot):
    g = make(root)
    try:
        g._progress = (2, 40)
        g._batch = object()
        assert g.property("footer") == "Saving 2 of 40 files…"
        g._batch = None
        g._on_progress(3, 4, "x")
        assert g._progress == (3, 4)
    finally:
        g.shut()
        g.history_.close()


def test_a_batch_that_fails_itself_fails_each_file_and_says_why(root, qapp, qtbot):
    g = make(root)
    try:

        class Broken:
            def run(self):
                raise RuntimeError("broken")

        outcomes = []
        g._done.disconnect(g._on_done)
        g._done.connect(outcomes.append)
        g._run(Broken(), [Job("/m/a.flac", {})])
        assert isinstance(outcomes[0], Outcome)
        assert outcomes[0].failed == [Failed(Job("/m/a.flac", {}), "it wasn't saved: broken")]
    finally:
        g.shut()
        g.history_.close()


def test_the_tour_opens_the_menu_and_the_dialogs_and_closes_them(genres_, qtbot):
    genres_.refresh()
    qtbot.waitUntil(lambda: not genres_.property("reading"), timeout=WAIT)
    genres_.go({"view": "genres", "genreMenu": "Electronic"})
    assert genres_.property("menuFor") == "Electronic"
    genres_.menuClosed()
    assert genres_.property("menuFor") == ""
    genres_.go({"view": "genres", "genreTool": {"tool": "rename", "genre": "Electronica"}})
    assert genres_.property("tool") == "rename"
    genres_.go({"view": "genres", "genreTool": {"tool": "merge", "genre": "Electronica"}})
    assert genres_.property("tool") == "merge"
    genres_.go({"view": "genres", "genreTool": {"tool": "review"}})
    assert genres_.property("title") == "Merge into one genre"
    genres_.go({"view": "genres"})
    assert not genres_.property("opened")


# ---------- in the window ----------


@pytest.fixture
def shell(made, tmp_path, qapp, qtbot):
    """MusiKata over the four songs, scanned, with the root's settings saying Electronica is
    Electronic (R9.5, R13.3)."""
    music = tmp_path / "Music"
    (music / "Lumen Drift" / "Tide Tables").mkdir(parents=True)
    for n, src in enumerate(made, 1):
        shutil.copyfile(src, music / "Lumen Drift" / "Tide Tables" / f"{n:02d}.flac")
    demo.root_settings(str(music))
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(music), env, FakeClock(datetime.now(UTC) - timedelta(minutes=1)),
                 lambda: ThreadPoolExecutor(1))  # fmt: skip
    s.library.rescan()
    qtbot.waitUntil(lambda: not s.library.scanning, timeout=WAIT * 3)
    s.music_ = str(music)
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
def test_the_genres_view_loads_with_its_banner_tiles_and_menu_and_no_qml_warning(
    shell, qtbot, qtlog
):
    """G01-genres in the window: the sidebar's Genres, the banner, a tile per genre with its
    covers, Electronic's ⋯ menu open; every text in its box. Review… opens the merge's preview
    over the window, and its save writes the files and offers Undo."""
    side = find(shell, "side-genres")
    assert len(side) == 1
    click(shell, side[0])
    assert shell.library.property("view") == "genres"
    shell.genres.go({"view": "genres", "genreMenu": "Electronic"})
    settled(shell, qtbot)
    qtbot.waitUntil(lambda: bool(find(shell, "genreBanner")), timeout=WAIT)
    assert find(shell, "genrePlayAll") and find(shell, "genreMerge")
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []
    shell.genres.go({"view": "genres"})
    click(shell, find(shell, "genreReview")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "toolDialog")), timeout=WAIT)
    qtbot.waitUntil(lambda: shell.genres.property("saveLater") == "", timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    with qtbot.waitSignal(shell.changes.messageChanged, timeout=WAIT):
        click(shell, find(shell, "saveTool")[0])
    qtbot.waitUntil(lambda: not find(shell, "toolDialog"), timeout=WAIT)
    music = shell.music_
    got = [tags.read(os.path.join(music, "Lumen Drift", "Tide Tables", f"0{n}.flac"))[0].genres
           for n in range(1, 5)]  # fmt: skip
    assert got == [("Electronic",), ("Electronic",), ("Electronic", "Ambient"), ("Electronic",)]
    qtbot.waitUntil(lambda: shell.genres.property("banner") == {}, timeout=WAIT)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


@pytest.mark.slow
def test_a_genres_page_loads_and_its_menu_selects_its_songs_with_no_qml_warning(
    shell, qtbot, qtlog
):
    """R9.1's page in the window, and Select its songs (R9.4): Ctrl+E then edits them."""
    lib = shell.library
    lib.show("genres")
    settled(shell, qtbot)
    lib.selectGenre("Electronic")
    settled(shell, qtbot)
    songs = lib.property("genrePage").property("songs")
    qtbot.waitUntil(lambda: songs.property("selectionCount") == 2, timeout=WAIT)
    assert find(shell, "genreSongs") and find(shell, "genrePlay")
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []
    shell.edit.editCurrent(lib)
    qtbot.waitUntil(lambda: not shell.edit.property("loading"), timeout=WAIT)
    assert shell.edit.property("opened") and shell.edit.property("count") == 2
    assert sorted(shell.edit.property("ids")) == sorted(songs.property("selection"))
    shell.edit.setText("genres", "Electronic; Ambient")  # R9.2: several genres, as chips
    settled(shell, qtbot)
    assert len(find(shell, "chips-genres")) == 1
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []
