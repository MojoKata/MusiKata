"""The Songs list's model (src/musikata/models.py; A1.5): rows paged from the index, ordered by
SQL, and what each row shows decided in Python, not in QML."""

import os

import pytest
from fakes import fill
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


def test_a_row_with_nothing_but_its_path_shows_its_file_name_and_blanks():
    row = models.row_of(("a/Untitled.wav", None, None, None, None, None, None, None, None))
    assert row == {"title": "Untitled", "artist": "", "album": "", "genre": "", "year": "",
                   "track": "", "rating": 0, "time": "", "path": "a/Untitled.wav"}  # fmt: skip


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
                   "time": "4:18", "path": "a.flac", "playing": False}  # fmt: skip
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
    m = models.SongsModel(index.read, "album", where="album = ?", params=("X",))
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
