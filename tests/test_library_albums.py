"""Albums, compilations and artists (src/musikata_core/albums.py; R2.5, A2.1): which songs are
one album, a compilation listed once, artists whose names differ only in case shown as one, and
the rows kept current by every write of the scan, moves and removals included.

Why: the album and artist rows are what Albums, Artists and the root's card read; one left stale
by a write (a song retagged onto another album, the last song of an album removed) shows an album
that isn't there, or loses one that is, until the index is rebuilt."""

import pytest
from fakes import fill

from musikata_core import albums, art, db, scanner
from musikata_core.tags import AudioInfo, Tags


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def rows(index, sql):
    return index.read().execute(sql).fetchall()


def album_rows(index):
    return rows(index, "SELECT artist, title, songs, compilation FROM album ORDER BY artist_key,"
                       " title_key")  # fmt: skip


def song(path, **kw):
    fields = {
        "artist": None,
        "albumartist": None,
        "album": "A",
        "compilation": False,
        "year": None,
        "length": 60.0,
        "size": 10,
        "mtime_ns": 1,
        "has_cover": False,
    }
    return albums.Song(path, **{**fields, **kw})


# ---------- which album a song is on ----------


def test_an_album_is_its_album_artist_or_else_artist_and_title_case_aside():
    assert albums.album_identity("Glass Harbor", "Lumen Drift", "Someone", False) == (
        "lumen drift\0glass harbor"
    )
    assert albums.album_identity("glass harbor ", None, "LUMEN DRIFT", False) == (
        "lumen drift\0glass harbor"
    )
    assert albums.album_identity("Hits", "", "Zed", True) == "\x01\0hits"
    assert albums.album_identity("", "A", "B", False) is None
    assert albums.album_identity(None, "A", "B", False) is None
    assert albums.artist_identity(" Lumen Drift ") == "lumen drift"
    assert albums.artist_identity("  ") is None and albums.artist_identity(None) is None


def test_the_most_common_value_and_name_choose_the_same_whatever_the_order():
    assert albums.most_common(["b", None, "a", "b", ""]) == "b"
    assert albums.most_common(["a", "b"]) == "a" and albums.most_common([None, ""]) is None
    assert albums.name_of({"lumen drift": 1, "Lumen Drift": 1}) == "Lumen Drift"
    assert albums.name_of({"lumen drift": 3, "Lumen Drift": 1}) == "lumen drift"


# ---------- what an album's row says ----------


def test_an_albums_row_summarizes_its_songs():
    a = albums.summarize(
        [song("A/1.flac", artist="The Paper Lanterns", album="Northbound Static", year=2021,
              length=100.0, size=5),
         song("A/2.flac", artist="The Paper Lanterns", album="northbound static", year=2021,
              length=50.5, size=6),
         song("B/3.flac", artist="The Paper Lanterns", album="Northbound Static", year=2020)],
        ["Indie Rock", "Indie Rock", "Folk"], None,
    )  # fmt: skip
    assert (a.artist, a.title, a.artist_key, a.title_key) == (
        "The Paper Lanterns", "Northbound Static", "paper lanterns", "northbound static"
    )  # fmt: skip
    assert (a.year, a.genre, a.songs, a.length, a.size, a.folder) == (
        2021, "Indie Rock", 3, 210.5, 21, "A"
    )  # fmt: skip
    assert not a.compilation and a.cover is None and a.thumb is None and a.embedded == 0


def test_a_tie_in_years_takes_the_earliest_and_no_year_is_none():
    two = [song("1", year=2020), song("2", year=2019)]
    assert albums.summarize(two, [], None).year == 2019
    assert albums.summarize([song("1")], [], None).year is None


def test_sort_tags_win_for_the_album_artist_and_the_title():
    a = albums.summarize(
        [song("1", artist="David Bowie", albumartistsort="Bowie, David", albumsort="Heroes 1977",
              album="\"Heroes\"")], [], None,
    )  # fmt: skip
    assert (a.artist_key, a.title_key) == ("bowie, david", "heroes 041977")
    b = albums.summarize([song("1", artist="David Bowie", artistsort="Bowie, David")], [], None)
    assert b.artist_key == "bowie, david"  # no album artist: the artist's sort tag
    c = albums.summarize(
        [song("1", artist="X", albumartist="The Band", artistsort="Ignored")], [], None
    )
    assert c.artist_key == "band"  # an album artist of its own: the artist's tag isn't its


def test_a_compilation_is_flagged_songs_of_several_artists_or_various_artists():
    flagged = [song("1", artist="Amber Orbit", compilation=True),
               song("2", artist="Cinder Fern", compilation=True)]  # fmt: skip
    a = albums.summarize(flagged, [], None)
    assert (a.artist, a.compilation) == ("Various Artists", True)
    one = [song("1", artist="Mara Okafor", compilation=True)] * 2  # flagged, one artist: not one
    single = albums.summarize(one, [], None)
    assert (single.artist, single.compilation) == ("Mara Okafor", False)
    named = [song("1", artist="A", albumartist="various artists"), song("2", artist="A",
             albumartist="various artists")]  # fmt: skip
    assert albums.summarize(named, [], None).compilation
    unflagged = [song("1", artist="A", albumartist="DJ Set"), song("2", artist="B",
                 albumartist="DJ Set")]  # fmt: skip
    assert not albums.summarize(unflagged, [], None).compilation


def test_the_cover_is_the_first_embedded_one_else_the_folders_image():
    embedded = albums.summarize(
        [song("A/1.mp3"), song("A/2.mp3", has_cover=True, size=7, mtime_ns=9),
         song("A/3.mp3", has_cover=True)], [], ("A/cover.jpg", 50, 2),
    )  # fmt: skip
    assert (embedded.cover_kind, embedded.cover, embedded.embedded) == ("embedded", "A/2.mp3", 2)
    assert embedded.thumb == art.thumb_id("A/2.mp3", 7, 9)
    assert embedded.folder_image == "A/cover.jpg"  # its folder's image, kept for its chip
    folder = albums.summarize([song("A/1.mp3")], [], ("A/cover.jpg", 50, 2))
    assert (folder.cover_kind, folder.cover, folder.thumb) == (
        "file", "A/cover.jpg", art.thumb_id("A/cover.jpg", 50, 2)
    )  # fmt: skip


# ---------- the rows, kept by the scan's writes ----------


def test_songs_sharing_an_album_artist_and_title_are_one_album_wherever_they_are(index):
    fill(index, [
        {"path": "Lumen Drift/Glass Harbor/01.flac", "artist": "Lumen Drift",
         "album": "Glass Harbor", "albumartist": "Lumen Drift", "track": 1},
        {"path": "Lumen Drift/Lowlight (Radio Edit).mp3", "artist": "Lumen Drift",
         "album": "glass harbor"},  # elsewhere, no album artist: its artist is the same
        {"path": "Other/Glass Harbor/01.flac", "artist": "Hollow Coast", "album": "Glass Harbor"},
        {"path": "Loose.mp3", "artist": "Hollow Coast"},  # no album
    ])  # fmt: skip
    assert album_rows(index) == [("Hollow Coast", "Glass Harbor", 1, 0),
                                 ("Lumen Drift", "Glass Harbor", 2, 0)]  # fmt: skip
    assert rows(index, "SELECT COUNT(*) FROM song WHERE album_id IS NULL") == [(1,)]


def test_a_compilation_is_listed_once_under_its_album_artist(index):
    fill(index, [
        {"path": f"Night Ferry/{n}.ogg", "artist": a, "album": "Night Ferry", "compilation": True}
        for n, a in enumerate(("Amber Orbit", "Cinder Fern", "Iron Arc"))
    ] + [
        {"path": f"Low Tide/{n}.mp3", "artist": a, "albumartist": "Various Artists",
         "album": "Low Tide Diaries"} for n, a in enumerate(("Amber Orbit", "Blue Fern"))
    ])  # fmt: skip
    assert album_rows(index) == [("Various Artists", "Low Tide Diaries", 2, 1),
                                 ("Various Artists", "Night Ferry", 3, 1)]  # fmt: skip
    various = rows(index, "SELECT albums, songs FROM artist WHERE name = 'Various Artists'")
    assert various == [(2, 5)]


def test_artists_named_in_another_case_are_one_shown_as_most_songs_name_them(index):
    fill(index, [
        {"path": "1.flac", "artist": "Lumen Drift", "album": "Tide Tables"},
        {"path": "2.flac", "artist": "Lumen Drift", "album": "Tide Tables"},
        {"path": "3.flac", "artist": "lumen drift", "album": "Tide Tables",
         "albumartist": "Lumen Drift"},
        {"path": "4.mp3", "artist": "LUMEN DRIFT"},
        {"path": "5.mp3", "artist": "The Paper Lanterns", "albumartist": "Lumen Drift",
         "album": "Remixes"},
    ])  # fmt: skip
    found = rows(index, "SELECT name, sort_key, albums, songs FROM artist ORDER BY sort_key")
    assert found == [
        ("Lumen Drift", "lumen drift", 2, 5),
        ("The Paper Lanterns", "paper lanterns", 0, 1),
    ]


def test_a_retagged_song_moves_its_album_and_the_empty_album_and_artist_go(index):
    fill(index, [{"path": "a.flac", "artist": "A", "album": "One"},
                 {"path": "b.flac", "artist": "A", "album": "One"}])  # fmt: skip
    fill(index, [{"path": "b.flac", "artist": "B", "album": "Two"}])
    assert album_rows(index) == [("A", "One", 1, 0), ("B", "Two", 1, 0)]
    fill(index, [{"path": "a.flac", "artist": "B", "album": "Two"}])
    assert album_rows(index) == [("B", "Two", 2, 0)]
    assert rows(index, "SELECT name, albums, songs FROM artist") == [("B", 1, 2)]


def test_a_song_removed_by_the_scan_updates_its_album_and_artist(index):
    fill(index, [{"path": "a.flac", "artist": "A", "album": "One"},
                 {"path": "b.flac", "artist": "A", "album": "One"}])  # fmt: skip
    touched = albums.Touched()

    def remove(c, paths):
        albums.forget(c, paths, touched)
        c.executemany("DELETE FROM song WHERE path = ?", [(p,) for p in paths])
        albums.refresh(c, touched)

    index.write(lambda c: remove(c, ["a.flac", "missing.flac"])).result()
    assert album_rows(index) == [("A", "One", 1, 0)]
    index.write(lambda c: remove(c, ["b.flac"])).result()
    assert album_rows(index) == [] and rows(index, "SELECT * FROM artist") == []


def test_the_songs_sort_keys_are_the_album_artists_and_the_albums(index):
    fill(index, [{"path": "a.flac", "artist": "X", "albumartist": "The Band", "album": "An Album",
                  "albumsort": "Album, An"},
                 {"path": "b.flac", "artist": "The Who", "artistsort": "Who, The"}])  # fmt: skip
    assert rows(index, "SELECT artist_key, album_key FROM song ORDER BY path") == [
        ("band", "album, an"), ("who, the", None)
    ]  # fmt: skip


def _write(index, songs, images):
    info = AudioInfo("flac", 1.0, 900, 44100, 2)
    batch = [scanner.Read(scanner.Seen(p, 10, 1), Tags(album="A", artist="X", has_cover=cover),
                          info, p) for p, cover in songs]  # fmt: skip
    index.write(lambda c: scanner.write_batch(c, batch, {}, images)).result()


def cover_of(index):
    return rows(index, "SELECT cover_kind, cover, folder_image FROM album")


def test_a_folders_image_is_the_cover_until_a_song_has_one_embedded(index):
    images = {"A": [art.Image("back.jpg", 900, 1), art.Image("Cover.JPG", 100, 1)]}
    _write(index, [("A/1.flac", False), ("A/2.flac", False)], images)
    assert cover_of(index) == [("file", "A/Cover.JPG", "A/Cover.JPG")]
    _write(index, [("A/2.flac", True)], None)  # a write that didn't walk keeps the folder's image
    assert cover_of(index) == [("embedded", "A/2.flac", "A/Cover.JPG")]


def test_a_folder_image_added_or_removed_beside_unchanged_songs_is_found_at_the_scans_end(index):
    _write(index, [("A/1.flac", False)], {})
    assert cover_of(index) == [(None, None, None)]
    found = index.write(lambda c: albums.refresh_folders(c, {"A": [art.Image("folder.png", 5, 3)]}))
    assert found.result() == 1
    assert cover_of(index) == [("file", "A/folder.png", "A/folder.png")]
    same = index.write(lambda c: albums.refresh_folders(c, {"A": [art.Image("folder.png", 5, 3)]}))
    assert same.result() == 0  # unchanged: nothing summarized again
    gone = index.write(lambda c: albums.refresh_folders(c, {}))
    assert gone.result() == 1 and cover_of(index) == [(None, None, None)]


def test_songs_at_the_root_have_their_folder_as_the_root(index):
    _write(index, [("1.flac", False)], {"": [art.Image("cover.jpg", 5, 3)]})
    assert cover_of(index) == [("file", "cover.jpg", "cover.jpg")]


def test_refreshing_an_album_that_isnt_there_does_nothing(index):
    assert index.write(lambda c: albums.refresh_album(c, 99)).result() == set()
