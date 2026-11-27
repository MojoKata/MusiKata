"""The Songs list's model (src/musikata/models.py; A1.5): rows paged from the index, ordered by
SQL, and what each row shows decided in Python, not in QML; its selection (R2.6), kept by song id
through paging, sorting, searches and scans, and what Enter and the right-click menu take from it
(R7.1, R7.2)."""

import os
import threading

import pytest
from fakes import fill, played
from PySide6.QtCore import QModelIndex, Qt

from musikata import models
from musikata_core import db


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def test_time_and_title_texts():
    assert [models.time_text(s) for s in (None, -1, 0, 59.6, 258, 3725)] == [
        "", "", "0:00", "1:00", "4:18", "1:02:05"
    ]  # fmt: skip
    assert models.title_of(None, "a/b/04 Signal Fires.flac") == "04 Signal Fires"
    assert models.title_of("", "x.mp3") == "x" and models.title_of("Tide", "x.mp3") == "Tide"


def test_a_songs_plays_are_every_computers_added_up_and_none_shows_nothing(index):
    fill(index, [{"path": p} for p in ("a.flac", "b.flac", "c.flac")])
    played(index, {"a.flac": 3, "b.flac": 1})
    played(index, {"a.flac": 2}, computer="studio-pc")
    m = models.SongsModel(index.read, "title")
    m.reload()
    assert [m.row(i)["plays"] for i in range(3)] == ["5", "1", ""]
    assert [models.plays_text(n) for n in (None, 0, 1, 1204)] == ["", "", "1", "1,204"]


def test_a_row_with_nothing_but_its_path_shows_its_file_name_and_blanks():
    row = models.row_of(("a/Untitled.wav", *[None] * 9))
    assert row == {"title": "Untitled", "artist": "", "album": "", "genre": "", "year": "",
                   "track": "", "rating": 0, "plays": "", "time": "", "path": "a/Untitled.wav"
                   }  # fmt: skip


def test_rows_by_album_artist_then_album_disc_and_track_missing_last_case_aside(index):
    b = {"album": "B", "disc": 1}
    fill(index, [
        {"path": "z.flac", "title": "No artist"},
        {"path": "b2.flac", "title": "B two", "artist": "beta", "track": 2, **b},
        {"path": "b1.flac", "title": "B one", "artist": "Beta", "track": 1, **b},
        {"path": "c.flac", "title": "Comp", "artist": "Zed", "albumartist": "Alpha", "album": "C"},
        {"path": "d.flac", "title": "Disc 2", "artist": "beta", "track": 1, **b, "disc": 2},
        {"path": "s.flac", "title": "Sorted", "artist": "The Zebras", "artistsort": "Aardvark"},
    ])  # fmt: skip
    m = models.SongsModel(index.read)
    m.reload()
    assert [m.row(i)["title"] for i in range(m.rowCount())] == [
        "Sorted", "Comp", "B one", "B two", "Disc 2", "No artist"
    ]  # fmt: skip
    m.sort_by("title")
    assert m.row(0)["title"] == "B one" and m.row(5)["title"] == "Sorted"
    with pytest.raises(ValueError):
        m.sort_by("bpm")


def test_the_roles_give_each_field_as_text_genres_joined_in_their_order(index):
    fill(index, [{"path": "a.flac", "title": "Neap Tide", "artist": "Lumen Drift",
                  "album": "Tide Tables", "genres": ("Electronic", "Ambient"), "year": 2022,
                  "track": 7, "rating": 4, "length": 258.4}])  # fmt: skip
    m = models.SongsModel(index.read)
    m.reload()
    names = {bytes(v).decode(): k for k, v in m.roleNames().items()}
    at = m.index(0, 0)
    got = {n: m.data(at, r) for n, r in names.items()}
    assert got == {"title": "Neap Tide", "artist": "Lumen Drift", "album": "Tide Tables",
                   "genre": "Electronic; Ambient", "year": "2022", "track": "7", "rating": 4,
                   "plays": "", "time": "4:18", "path": "a.flac", "playing": False,
                   "selected": False, "current": False}  # fmt: skip
    assert m.data(at, int(Qt.ItemDataRole.DisplayRole)) is None
    assert m.data(m.index(5, 0), names["title"]) is None
    assert m.rowCount(at) == 0 and m.row(-1) is None


def test_rows_are_read_a_page_at_a_time_and_only_so_many_pages_are_held(index, monkeypatch):
    monkeypatch.setattr(models, "PAGE", 10)
    monkeypatch.setattr(models, "KEEP", 2)
    fill(index, [{"path": f"{n:03}.flac", "title": f"{n:03}"} for n in range(35)])
    m = models.SongsModel(index.read, sort="title")
    m.reload()
    assert m.count == 35 and m.pages_read == 0
    assert [m.row(n)["title"] for n in (0, 9, 3)] == ["000", "009", "003"]
    assert m.pages_read == 1
    assert m.row(34)["title"] == "034" and m.pages_read == 2
    m.row(0)  # held still: the page read longest ago is the last page's
    m.row(15)  # a third page: the last page's goes
    assert m.pages_read == 3
    m.row(34)
    assert m.pages_read == 4
    m.row(15)
    assert m.pages_read == 4


def test_a_reload_after_a_scan_drops_the_pages_and_tells_the_view(index, qtbot):
    m = models.SongsModel(index.read)
    m.reload()
    assert m.rowCount(QModelIndex()) == 0
    fill(index, [{"path": "a.flac"}])
    with qtbot.waitSignals([m.countChanged, m.modelReset]):
        m.reload()
    assert m.count == 1 and m.row(0)["title"] == os.path.splitext("a.flac")[0]


def _signals(m):
    seen = []
    m.modelReset.connect(lambda: seen.append("reset"))
    m.rowsInserted.connect(lambda _p, first, last: seen.append(("inserted", first, last)))
    m.rowsRemoved.connect(lambda _p, first, last: seen.append(("removed", first, last)))
    m.dataChanged.connect(lambda a, b, _r: seen.append(("changed", a.row(), b.row())))
    return seen


def test_a_refresh_after_a_watched_change_reads_the_rows_again_where_they_are(index, qtbot):
    """A scan's rows (R2.4) come into a list without a reset: a view keeps its scroll position,
    with rows added or taken away at the end and every row read again."""
    fill(index, [{"path": f"{n}.flac", "title": f"Song {n}"} for n in range(3)])
    m = models.SongsModel(index.read, "title")
    m.reload()
    assert m.row(0)["title"] == "Song 0"
    seen = _signals(m)
    fill(index, [{"path": "a.flac", "title": "A first"}])
    m.refresh()
    assert seen == [("inserted", 3, 3), ("changed", 0, 3)]
    assert m.count == 4 and m.row(0)["title"] == "A first"  # the pages read again
    index.write(lambda c: c.execute("DELETE FROM song WHERE path IN ('0.flac', '1.flac')")).result()
    seen.clear()
    m.refresh()
    assert seen == [("removed", 2, 3), ("changed", 0, 1)] and m.count == 2
    index.write(lambda c: c.execute("DELETE FROM song")).result()
    seen.clear()
    m.refresh()
    assert seen == [("removed", 0, 1)] and m.count == 0


def test_a_refresh_keeps_the_search_and_its_rows_come_in_place(index, qtbot):
    fill(index, [{"path": f"{n}.flac", "title": f"Tide {n}"} for n in range(3)])
    m = models.SongsModel(index.read, "title")
    with qtbot.waitSignal(m.countChanged, timeout=5000):
        m.set_search("tide")
    seen = _signals(m)
    fill(index, [{"path": "x.flac", "title": "Tide 9"}, {"path": "y.flac", "title": "Other"}])
    with qtbot.waitSignal(m.countChanged, timeout=5000):
        m.refresh()
    assert seen == [("inserted", 3, 3), ("changed", 0, 3)]
    assert m.count == 4 and m.total() == 5 and m.shown_search() == "tide"
    with qtbot.waitSignal(m.countChanged, timeout=5000):  # a new search shows its rows anew
        m.set_search("other")
        m.refresh()
    assert "reset" in seen and m.count == 1
    m.wait()


# ---------- Albums and Artists ----------


def roles(model, n):
    names = {bytes(v).decode(): k for k, v in model.roleNames().items()}
    return {name: model.data(model.index(n, 0), role) for name, role in names.items()}


def test_lengths_and_lines_as_the_pages_give_them():
    assert [models.length_text(s) for s in (None, 0, 61, 44 * 60 + 20, 72 * 60)] == [
        "1 min", "1 min", "1 min", "44 min", "1 h 12 min"
    ]  # fmt: skip
    assert models.artist_line(3, 41) == "3 albums · 41 songs"
    assert models.artist_line(0, 1) == "1 song" and models.artist_line(1, 1) == "1 album · 1 song"
    assert models.cover_url(None) == "" and models.cover_url("ab") == "image://covers/ab"


def test_a_mosaic_lays_out_one_to_four_covers_as_r5_8s_table():
    def boxes(n):
        return [(m["x"], m["y"], m["w"], m["h"]) for m in models.mosaic(n)]

    assert boxes(0) == [] and boxes(1) == [(0, 0, 1, 1)]
    assert boxes(2) == [(0, 0, 0.5, 1), (0.5, 0, 0.5, 1)]
    assert boxes(3) == [(0, 0, 0.5, 1), (0.5, 0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)]
    assert boxes(4) == boxes(9) and len(boxes(4)) == 4
    assert models.tiles(["a", "b"]) == [
        {"source": "image://covers/a", "x": 0, "y": 0, "w": 0.5, "h": 1},
        {"source": "image://covers/b", "x": 0.5, "y": 0, "w": 0.5, "h": 1},
    ]


LIBRARY = [
    {"path": "PL/1.mp3", "artist": "The Paper Lanterns", "album": "Northbound Static",
     "year": 2021, "genres": ("Indie Rock",), "length": 200.0},
    {"path": "MO/1.mp3", "artist": "Mara Okafor", "album": "Salt & Ember", "year": 2018,
     "genres": ("Soul",)},
    {"path": "MO/2.mp3", "artist": "Mara Okafor", "album": "Kindling", "genres": ("Soul",)},
    {"path": "MO/3.mp3", "artist": "Mara Okafor", "album": "Kindling"},
    {"path": "V/1.ogg", "artist": "Amber Orbit", "album": "Night Ferry", "compilation": True},
    {"path": "V/2.ogg", "artist": "Iron Arc", "album": "Night Ferry", "compilation": True},
]  # fmt: skip


def test_albums_by_album_artist_then_title_by_their_sort_names(index):
    fill(index, LIBRARY)
    m = models.AlbumsModel(index.read)
    m.reload()
    assert [m.row(i)["title"] for i in range(m.count)] == [
        "Kindling", "Salt & Ember", "Northbound Static", "Night Ferry"
    ]  # fmt: skip
    first = roles(m, 2)
    assert first == {"albumId": first["albumId"], "title": "Northbound Static",
                     "artist": "The Paper Lanterns", "year": "2021",
                     "line": "The Paper Lanterns · 2021", "genre": "Indie Rock", "songs": "1 song",
                     "time": "3:20", "cover": "", "playing": False}  # fmt: skip
    assert roles(m, 0)["line"] == "Mara Okafor" and roles(m, 0)["songs"] == "2 songs"
    assert m.data(m.index(0, 0), 0) is None and m.data(m.index(9, 0), m._role("title")) is None


def test_albums_of_one_genre_and_of_one_artist_by_year(index):
    fill(index, LIBRARY)
    m = models.AlbumsModel(index.read)
    m.filter_genre("Soul")
    assert [m.row(i)["title"] for i in range(m.count)] == ["Kindling", "Salt & Ember"]
    mara = index.read().execute("SELECT id FROM artist WHERE name = 'Mara Okafor'").fetchone()[0]
    m.for_artist(mara)
    assert [m.row(i)["title"] for i in range(m.count)] == [
        "Salt & Ember",
        "Kindling",
    ]  # no year last


def test_the_album_playing_is_marked(index, qtbot):
    fill(index, LIBRARY)
    m = models.AlbumsModel(index.read)
    m.reload()
    target = m.row(1)["albumId"]
    with qtbot.waitSignal(m.dataChanged):
        m.set_playing(target)
    m.set_playing(target)  # again: nothing
    assert [roles(m, i)["playing"] for i in range(m.count)] == [False, True, False, False]


def test_artists_by_sort_name_with_their_counts_and_mosaic(index):
    fill(index, LIBRARY)

    def cover(c):
        c.execute("UPDATE album SET thumb = 'k' WHERE title = 'Kindling'")
        c.execute("UPDATE album SET thumb = 's' WHERE title = 'Salt & Ember'")
        c.execute("UPDATE album SET thumb = 'n' WHERE title = 'Night Ferry'")

    index.write(cover).result()
    m = models.ArtistsModel(index.read)
    m.reload()
    got = [(r["name"], r["line"], [t["source"][-1] for t in r["tiles"]])
           for r in (m.row(i) for i in range(m.count))]  # fmt: skip
    assert got == [
        ("Amber Orbit", "1 song", ["n"]),  # on a compilation only: its cover
        ("Iron Arc", "1 song", ["n"]),
        ("Mara Okafor", "2 albums · 3 songs", ["k", "s"]),  # the album with the most songs first
        ("The Paper Lanterns", "1 album · 1 song", []),
        ("Various Artists", "1 album · 2 songs", ["n"]),
    ]
    assert isinstance(roles(m, 0)["artistId"], int)


def test_a_list_of_songs_picks_and_orders_what_its_page_asks_for(index):
    fill(index, [{"path": "b.flac", "album": "X", "track": 2}, {"path": "a.flac", "album": "X"},
                 {"path": "c.flac", "album": "X", "track": 1},
                 {"path": "d.flac", "album": "Y"}])  # fmt: skip
    m = models.SongsModel(index.read, "tracks", where="album = ?", params=("X",))
    m.reload()
    assert [m.row(i)["path"] for i in range(m.count)] == ["c.flac", "b.flac", "a.flac"]
    m.select("album = ?", ("Y",))
    assert m.count == 1 and m.row(0)["path"] == "d.flac"


def test_the_songs_list_sorts_artists_by_their_sort_names(index):
    """R2.13 in the Songs list: the same keys Albums and Artists sort by."""
    fill(index, [
        {"path": "1.flac", "title": "Under T", "artist": "The Zebras"},
        {"path": "2.flac", "title": "Under B", "artist": "The Beatles"},
        {"path": "3.flac", "title": "Under B too", "artist": "David Bowie",
         "artistsort": "Bowie, David"},
        {"path": "4.flac", "title": "Disc 10", "artist": "Disc 10"},
        {"path": "5.flac", "title": "Disc 9", "artist": "disc 9"},
    ])  # fmt: skip
    m = models.SongsModel(index.read)
    m.reload()
    assert [m.row(i)["title"] for i in range(m.count)] == [
        "Under B", "Under B too", "Disc 9", "Disc 10", "Under T"
    ]  # fmt: skip


# ---------- sorts (R2.6, R2.13) ----------


def test_the_songs_list_sorts_by_each_column_either_way_with_missing_values_last(index):
    fill(index, [
        {"path": "a.flac", "title": "b", "artist": "Zed", "album": "Q", "year": 2001, "rating": 3,
         "genres": ("Soul",), "length": 30.0},
        {"path": "b.flac", "title": "A", "artist": "Amy", "album": "R", "year": 1999, "rating": 5,
         "genres": ("jazz",), "length": 10.0},
        {"path": "c.flac", "title": "c", "artist": "Mo", "album": "P", "genres": ("Folk",),
         "length": 20.0},
    ])  # fmt: skip
    played(index, {"a.flac": 1, "b.flac": 5})
    played(index, {"a.flac": 1}, computer="other")  # plays add up across computers (R7.9)
    m = models.SongsModel(index.read)
    expected = {
        "title": ["A", "b", "c"], "artist": ["A", "c", "b"], "album": ["c", "b", "A"],
        "genre": ["c", "A", "b"], "year": ["A", "b", "c"], "rating": ["c", "b", "A"],
        "plays": ["c", "b", "A"], "time": ["A", "c", "b"],
    }  # fmt: skip
    for column, titles in expected.items():
        m.sort_by(column)
        assert [m.row(i)["title"] for i in range(3)] == titles, column
        m.sort_by(column, descending=True)
        down = [m.row(i)["title"] for i in range(3)]
        assert down == (titles[1::-1] + ["c"] if column == "year" else titles[::-1]), column
        assert m.order() == (column, True)
    with pytest.raises(ValueError):
        models.SongsModel(index.read, "bpm")


def test_the_songs_headers_say_which_column_sorts_and_which_way():
    headers = models.song_headers("year", True)
    assert [h["label"] for h in headers] == [
        "#", "TITLE", "ARTIST", "ALBUM", "GENRE", "YEAR", "RATING", "PLAYS", "TIME"
    ]  # fmt: skip
    assert headers[0] == {"label": "#", "sort": "", "order": ""}
    assert [h["order"] for h in headers] == ["", "", "", "", "", "down", "", "", ""]
    assert models.song_headers("title", False)[1]["order"] == "up"
    assert {h["order"] for h in models.song_headers("tracks", False)} == {""}


def test_albums_sort_by_album_artist_title_or_year(index):
    fill(index, LIBRARY)
    m = models.AlbumsModel(index.read)
    m.sort_by("title")
    assert [m.row(i)["title"] for i in range(m.count)] == [
        "Kindling", "Night Ferry", "Northbound Static", "Salt & Ember"
    ]  # fmt: skip
    m.sort_by("year")
    assert [m.row(i)["year"] for i in range(m.count)] == ["2018", "2021", "", ""]
    assert m.order() == "year"
    with pytest.raises(ValueError):
        m.sort_by("plays")


# ---------- search (R2.7) ----------


def test_a_views_count_says_how_many_a_search_shows_of_how_many():
    assert models.count_text(1412, 1412, "song", False) == "1,412 songs"
    assert models.count_text(12, 1412, "song", True) == "12 of 1,412 songs"
    assert models.count_text(1, 1, "album", True) == "1 of 1 album"
    assert models.no_match_text(" zebra ", "albums") == "No albums match “zebra”"


def searched(model, qtbot, text):
    """Sets the model's search and waits for its rows (never a set time)."""
    with qtbot.waitSignal(model.countChanged, timeout=5000):
        model.set_search(text)


def test_a_search_finds_its_rows_off_the_gui_thread_and_they_come_with_count_changed(index, qtbot):
    fill(index, LIBRARY)
    threads = []

    def read():
        threads.append(threading.current_thread())
        return index.read()

    m = models.SongsModel(read)
    m.reload()
    threads.clear()
    with qtbot.waitSignal(m.countChanged, timeout=5000):
        m.set_search("mara")
        assert m.count == 6 and m.pending()  # nothing read here: the rows are still to come
        assert m.searching() and not m.filtered()
    assert threads and threading.main_thread() not in threads
    assert m.count == 3 and m.total() == 6 and m.filtered() and not m.pending()
    assert m.shown_search() == "mara"
    assert {m.row(i)["artist"] for i in range(3)} == {"Mara Okafor"}
    m.set_search("")  # nothing asked: the whole list, at once
    assert m.count == 6 and not m.searching() and not m.filtered() and m.shown_search() == ""
    m.wait()


def test_a_long_lists_rows_are_found_off_the_gui_thread_and_each_page_read_by_id(
    index, qtbot, monkeypatch
):
    """A1.3, A1.5: sorting a long list (the Songs list of 50,000) is the search thread's, and a
    page is a lookup by id at any depth, never a sort on the GUI thread; a short one is found at
    once."""
    monkeypatch.setattr(models, "PAGE", 2)
    fill(index, [{"path": f"{n}.flac", "title": f"Song {n}"} for n in range(5)])
    m = models.SongsModel(index.read, "title")
    monkeypatch.setattr(models, "SHORT", 4, raising=False)
    with qtbot.waitSignal(m.countChanged, timeout=5000):
        m.reload()
        assert m.count == 0 and m.pending() and not m.searching()
    assert m.count == m.total() == 5 and not m.pending() and not m.filtered()
    asked = []
    index.read().set_trace_callback(asked.append)
    try:
        assert [m.row(n)["title"] for n in (4, 0, 2)] == ["Song 4", "Song 0", "Song 2"]
    finally:
        index.read().set_trace_callback(None)
    assert len(asked) == 3 and all(q.endswith(")") and "OFFSET" not in q for q in asked)
    seen = _signals(m)
    fill(index, [{"path": "a.flac", "title": "A first"}])
    with qtbot.waitSignal(m.countChanged, timeout=5000):
        m.refresh()
        assert m.count == 5 and m.row(0)["title"] == "Song 0"  # the rows shown stay till then
    assert seen == [("inserted", 5, 5), ("changed", 0, 5)] and m.row(0)["title"] == "A first"
    monkeypatch.setattr(models, "SHORT", 6, raising=False)
    m.reload()  # short: at once
    assert m.count == 6 and not m.pending()
    m.wait()


def test_a_newer_search_replaces_one_still_running_and_its_rows_win(index, qtbot):
    fill(index, LIBRARY)
    started, release = threading.Event(), threading.Event()

    def read():
        if threading.current_thread() is not threading.main_thread() and not started.is_set():
            started.set()
            release.wait(5)
        return index.read()

    m = models.SongsModel(read)
    m.reload()
    counts = []
    m.countChanged.connect(lambda: counts.append(m.count))
    m.set_search("mara")
    assert started.wait(5)  # the first search runs, held
    m.set_search("ferr")
    m.set_search("ferry")  # replaces "ferr", which never runs
    with qtbot.waitSignal(m.countChanged, timeout=5000):
        release.set()
    m.wait()
    qtbot.wait(20)  # nothing more comes: the first search's rows were dropped
    assert counts == [2] and m.shown_search() == "ferry"
    assert [m.row(i)["album"] for i in range(2)] == ["Night Ferry", "Night Ferry"]


def test_a_searchs_rows_are_paged_by_id_in_the_lists_order(index, qtbot, monkeypatch):
    monkeypatch.setattr(models, "PAGE", 10)
    fill(index, [{"path": f"{n:03}.flac", "title": f"Song {n:03}", "artist": "Lumen Drift"}
                 for n in range(35)] + [{"path": "x.flac", "title": "Other"}])  # fmt: skip
    m = models.SongsModel(index.read, sort="title")
    searched(m, qtbot, "lumen")
    assert m.count == 35 and m.total() == 36
    assert [m.row(n)["title"] for n in (0, 9, 10, 34)] == [
        "Song 000", "Song 009", "Song 010", "Song 034"
    ]  # fmt: skip
    assert m.pages_read == 3 and m.row(35) is None
    with qtbot.waitSignal(m.countChanged, timeout=5000):
        m.sort_by("title", descending=True)  # a new order: the search runs again
    assert m.row(0)["title"] == "Song 034"


def test_albums_and_artists_a_search_finds_are_those_of_the_songs_it_finds(index, qtbot):
    fill(index, LIBRARY)
    albums = models.AlbumsModel(index.read)
    searched(albums, qtbot, "iron")  # a song's artist on a compilation
    assert [albums.row(i)["title"] for i in range(albums.count)] == ["Night Ferry"]
    albums.filter_genre("Soul")
    qtbot.waitUntil(lambda: not albums.pending(), timeout=5000)
    assert albums.count == 0 and albums.total() == 2
    artists = models.ArtistsModel(index.read)
    searched(artists, qtbot, "ferry")  # the album's artist, and its songs' artists
    assert [artists.row(i)["name"] for i in range(artists.count)] == [
        "Amber Orbit", "Iron Arc", "Various Artists"
    ]  # fmt: skip
    searched(artists, qtbot, "rating:>=1")
    assert artists.count == 0 and artists.total() == 5


def test_a_search_that_fails_finds_nothing_and_says_why_in_the_log(
    index, qtbot, monkeypatch, caplog
):
    fill(index, LIBRARY)
    m = models.SongsModel(index.read)
    monkeypatch.setattr(models.search, "condition", lambda q: ("no such column", ()))
    searched(m, qtbot, "x")
    assert m.count == 0 and m.total() == 0 and "a search failed" in caplog.text


# ---------- the selection (R2.6) ----------


def by_title(m):
    return [m.row(i)["title"] for i in range(m.rowCount())]


def chosen_titles(m, index):
    found = dict(index.read().execute("SELECT id, title FROM song"))
    return [found[i] for i in m.property("selection")]


def test_a_rows_roles_say_whether_it_is_selected_and_the_current_row(index, qtbot):
    fill(index, [{"path": f"{n}.flac", "title": f"Song {n}"} for n in range(3)])
    m = models.SongsModel(index.read, "title")
    m.reload()
    with qtbot.waitSignal(m.selectionChanged):
        m.click(1, False, False)
    m.click(2, True, False)
    assert [(roles(m, n)["selected"], roles(m, n)["current"]) for n in range(3)] == [
        (False, False), (True, False), (True, True)
    ]  # fmt: skip
    assert roles(m, 5)["selected"] is None and roles(m, 5)["current"] is None
    assert m.property("selectionCount") == 2 and m.property("selectionText") == "2 selected"
    assert m.property("selectionState") == "some"
    m.toggle(1)  # its checkbox: taken away
    m.click(0, False, True)  # Shift: from the anchor, Song 1, to it
    assert chosen_titles(m, index) == ["Song 0", "Song 1"]
    m.toggleAll()
    assert m.property("selectionState") == "none"
    m.toggleAll()
    assert m.property("selectionState") == "all" and m.property("selectionCount") == 3
    m.clearSelection()
    m.selectAll()
    assert m.property("selectionCount") == 3
    m.click(9, False, False)  # past the rows: nothing
    assert m.property("selectionCount") == 3


def test_keys_move_select_and_clear_and_a_key_the_list_doesnt_use_goes_on(index):
    fill(index, [{"path": f"{n}.flac", "title": f"Song {n}"} for n in range(5)])
    m = models.SongsModel(index.read, "title")
    m.reload()
    k, mod = Qt.Key, Qt.KeyboardModifier
    shift, ctrl = int(mod.ShiftModifier.value), int(mod.ControlModifier.value)
    assert m.press(int(k.Key_Down.value), 0, 3) == 0
    assert m.press(int(k.Key_Down.value), shift, 3) == 1
    assert chosen_titles(m, index) == ["Song 0", "Song 1"]
    assert m.press(int(k.Key_PageDown.value), 0, 3) == 4 and chosen_titles(m, index) == ["Song 4"]
    assert m.press(int(k.Key_Home.value), shift, 3) == 0 and m.property("selectionCount") == 5
    assert m.press(int(k.Key_Escape.value), 0, 3) == -1 and m.property("selectionCount") == 0
    assert m.press(int(k.Key_Escape.value), 0, 3) == models.NOT_MINE  # nothing left to clear
    assert m.press(int(k.Key_A.value), ctrl, 3) == -1 and m.property("selectionCount") == 5
    assert m.press(int(k.Key_Space.value), 0, 3) == models.NOT_MINE


def test_which_keys_are_the_lists_and_with_which_modifiers():
    k, mod = Qt.Key, Qt.KeyboardModifier
    shift, ctrl = int(mod.ShiftModifier.value), int(mod.ControlModifier.value)
    alt, keypad = int(mod.AltModifier.value), int(mod.KeypadModifier.value)
    up, a = int(k.Key_Up.value), int(k.Key_A.value)
    assert models.key_name(up, 0) == ("up", False)
    assert models.key_name(up, shift | keypad) == ("up", True)  # macOS's arrows are the keypad's
    assert models.key_name(up, alt) == ("", False)  # Alt+↑: up a folder (R2.9.1)
    assert models.key_name(up, ctrl | shift) == ("", True)  # Ctrl+Shift+↑: a playlist's (R6.9)
    assert models.key_name(a, ctrl) == ("all", False) and models.key_name(a, 0) == ("", False)
    assert models.key_name(int(k.Key_End.value), 0) == ("end", False)


def test_the_selection_stays_with_its_songs_through_paging_sorting_and_a_rescan(
    index, qtbot, monkeypatch
):
    """Long lists are paged by id (A1.5): the selection is kept by song id, so it is the same songs
    on whatever page they are, in another order, and after a scan that keeps them."""
    monkeypatch.setattr(models, "PAGE", 4)
    monkeypatch.setattr(models, "KEEP", 1)
    fill(index, [{"path": f"{n:02}.flac", "title": f"Song {n:02}"} for n in range(20)])
    m = models.SongsModel(index.read, "title")
    m.reload()
    m.click(2, False, False)
    m.click(17, True, False)  # on another page
    m.row(10)  # the first page dropped
    assert roles(m, 2)["selected"] and roles(m, 17)["selected"] and not roles(m, 10)["selected"]
    m.sort_by("title", descending=True)
    assert chosen_titles(m, index) == ["Song 17", "Song 02"]
    assert roles(m, 2)["selected"] and roles(m, 17)["selected"]  # 17 and 2, the other way round
    assert roles(m, 2)["current"]  # the current row moved with its song
    fill(index, [{"path": "aa.flac", "title": "Song 99"}])  # a scan adds a song at the top
    m.refresh()
    assert chosen_titles(m, index) == ["Song 17", "Song 02"] and roles(m, 3)["selected"]
    with qtbot.waitSignal(m.selectionChanged):  # a scan takes a selected song away
        index.write(lambda c: c.execute("DELETE FROM song WHERE path = '17.flac'")).result()
        m.refresh()
    assert chosen_titles(m, index) == ["Song 02"] and m.property("selectionCount") == 1


def test_a_search_keeps_the_songs_it_leaves_selected_and_select_all_takes_what_it_shows(
    index, qtbot
):
    fill(index, [{"path": f"{n}.flac", "title": f"Tide {n}"} for n in range(3)]
         + [{"path": "x.flac", "title": "Other"}])  # fmt: skip
    m = models.SongsModel(index.read, "title")
    m.reload()
    m.click(0, False, False)
    m.click(3, False, True)  # all four
    searched(m, qtbot, "tide")
    assert chosen_titles(m, index) == ["Tide 0", "Tide 1", "Tide 2"]  # Other left the list
    m.clearSelection()
    m.selectAll()  # the filtered list's songs
    assert m.property("selectionCount") == 3 and m.property("selectionState") == "all"
    searched(m, qtbot, "")
    assert m.property("selectionCount") == 3 and m.property("selectionState") == "some"
    m.wait()


def test_enter_plays_from_the_first_song_selected_and_the_menu_takes_the_whole_selection(index):
    fill(index, [{"path": f"{n}.flac", "title": f"Song {n}"} for n in range(5)])
    m = models.SongsModel(index.read, "title")
    m.source = "Songs"
    m.reload()
    ids = m.queue_from(0)[0]  # the songs, in the list's order
    assert m.queue_from_selection() == ([], "Songs")  # nothing selected: nothing plays
    m.click(3, False, False)
    m.click(1, True, False)  # the first in the list's order, though clicked last
    assert m.property("selection") == [ids[1], ids[3]]
    assert m.queue_from_selection() == (ids[1:], "Songs")
    assert m.songs_at(3) == [ids[1], ids[3]]  # a row in the selection: all of it
    assert m.songs_at(0) == [ids[0]]  # one outside it: its own
    assert m.songs_at(9) == []


def test_songs_chosen_to_show_selected_wait_for_a_searchs_rows(index, qtbot):
    fill(index, [{"path": f"{n}.flac", "title": f"Tide {n}"} for n in range(3)]
         + [{"path": "x.flac", "title": "Other"}])  # fmt: skip
    m = models.SongsModel(index.read, "title")
    m.reload()
    wanted = [i for (i,) in index.read().execute("SELECT id FROM song WHERE title != 'Tide 1'")]
    with qtbot.waitSignal(m.countChanged, timeout=5000):
        m.set_search("tide")
        m.select_songs(wanted)
        assert m.property("selectionCount") == 0  # not yet: the rows are still to come
    assert chosen_titles(m, index) == ["Tide 0", "Tide 2"]
    m.select_songs(wanted[:1])  # rows there: at once
    assert chosen_titles(m, index) == ["Tide 0"]
    m.wait()
