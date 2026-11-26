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
                   "time": "4:18", "path": "a.flac"}  # fmt: skip
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
