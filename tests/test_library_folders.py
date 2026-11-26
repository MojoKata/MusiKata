"""The folder table (src/musikata_core/folders.py; A2.7, R2.9, R5.8): a row per folder with audio
beneath it, kept current by every write of the scan up through the ancestors, moves and removals
included; each folder's own cover or the mosaic chosen from its subfolders' rows for trees of every
shape; names in the order people read them; a search finding folders by name; a selection of
folders resolving to the songs beneath them.

Why: Folders lists what this table says without walking the disk, so a row left stale by a write
(the last song of a folder removed, a cover added) shows a folder that isn't there, a wrong count,
or the wrong picture, until the index is rebuilt."""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import fill, wav

from musikata_core import art, db, folders, scanner, search


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def row(index, path, cols="folders, songs, folders_beneath, songs_beneath"):
    r = index.read().execute(f"SELECT {cols} FROM folder WHERE path = ?", (path,)).fetchone()
    return tuple(r) if r else None


def paths(index):
    return [p for (p,) in index.read().execute("SELECT path FROM folder ORDER BY path")]


def listed(index, parent):
    return [n for (n,) in index.read().execute(
        "SELECT name FROM folder WHERE parent = ? ORDER BY name_key, path", (parent,)
    )]  # fmt: skip


# ---------- plain functions ----------


def test_a_paths_parent_name_and_ancestors():
    assert folders.parent_of("A/B/C") == "A/B" and folders.parent_of("A") == ""
    assert folders.parent_of("") is None
    assert folders.name_of("A/B/c.flac") == "c.flac" and folders.name_of("A") == "A"
    assert folders.ancestors("A/B/C") == ["A/B", "A", ""] and folders.ancestors("") == []


def test_a_mosaics_layouts_are_r5_8s_table():
    assert folders.layout(0) == ()
    assert folders.layout(1) == ((0, 0, 1, 1),)
    assert folders.layout(2) == ((0, 0, 0.5, 1), (0.5, 0, 0.5, 1))
    assert folders.layout(3)[0] == (0, 0, 0.5, 1) and len(folders.layout(3)) == 3
    assert len(folders.layout(4)) == 4 and folders.layout(9) == folders.layout(4)


def child(name, songs, thumb=None, mosaic=()):
    return folders.Child(name, name.casefold(), songs, thumb, tuple(mosaic))


def test_a_folders_own_image_comes_first_then_the_embedded_cover_its_songs_share():
    image = ("A/folder.jpg", 10, 5)
    found = folders.picture(image, [("t1", "A/1.flac")], [child("B", 3, "tb")])
    assert found == folders.Picture("file", "A/folder.jpg", art.thumb_id(*image))
    shared = folders.picture(None, [("t1", "A/1.flac")], [child("B", 3, "tb")])
    assert shared == folders.Picture("embedded", "A/1.flac", "t1")


@pytest.mark.parametrize(
    "n, shown",
    [
        (1, ("c0",)),
        (2, ("c0", "c1")),
        (3, ("c0", "c1", "c2")),
        (4, ("c0", "c1", "c2", "c3")),
        (5, ("c1", "c2", "c3", "c4")),  # c0 has the fewest songs
    ],
)
def test_a_mosaic_takes_up_to_four_subfolders_with_the_most_songs_in_name_order(n, shown):
    children = [child(f"S{i}", 5 + i, f"c{i}") for i in range(n)]
    assert folders.picture(None, [], list(reversed(children))).mosaic == shown


def test_a_subfolder_that_is_a_mosaic_gives_its_first_cover_and_one_with_none_is_passed_by():
    children = [child("A", 9, mosaic=("a1", "a2")), child("B", 99), child("C", 1, "c")]
    assert folders.picture(None, [], children) == folders.Picture(mosaic=("a1", "c"))


def test_loose_songs_whose_covers_differ_make_a_mosaic_and_no_art_anywhere_makes_none():
    embedded = [(f"t{i}", f"{i}.mp3") for i in range(6)]
    assert folders.picture(None, embedded, []).mosaic == ("t0", "t1", "t2", "t3")
    assert folders.picture(None, embedded, [child("A", 1, "a")]).mosaic == ("a",)
    assert folders.picture(None, [], [child("A", 1), child("B", 2)]) == folders.Picture()


def test_what_a_folders_songs_share():
    assert folders.shared(["X", "X"]) == "X" and folders.shared([2019, 2019]) == 2019
    assert folders.shared(["X", "Y"]) is None and folders.shared(["X", None]) is None
    assert folders.shared(["X", ""]) is None and folders.shared([]) is None


def test_names_fold_case_and_accents_for_a_search():
    assert folders.folded("Beyoncé") == "beyonce" and folders.folded("MOTLEY") == "motley"


# ---------- the rows, kept by the scan ----------


def test_a_write_makes_a_row_for_each_folder_and_its_ancestors_with_their_counts(index):
    fill(index, [
        {"path": "Lumen Drift/2019 - Glass Harbor/01.flac", "length": 100.0},
        {"path": "Lumen Drift/2019 - Glass Harbor/02.flac", "length": 50.0},
        {"path": "Lumen Drift/Remixes/Glass/01.flac"},
        {"path": "Lumen Drift/Remixes/Tide/01.flac"},
        {"path": "Lumen Drift/loose.mp3"},
        {"path": "root.mp3"},
    ])  # fmt: skip
    assert paths(index) == ["", "Lumen Drift", "Lumen Drift/2019 - Glass Harbor",
                            "Lumen Drift/Remixes", "Lumen Drift/Remixes/Glass",
                            "Lumen Drift/Remixes/Tide"]  # fmt: skip
    assert row(index, "") == (1, 1, 5, 6)
    assert row(index, "Lumen Drift") == (2, 1, 4, 5)
    assert row(index, "Lumen Drift/Remixes") == (2, 0, 2, 2)
    assert row(index, "Lumen Drift/2019 - Glass Harbor", "length, parent, name") == (
        150.0, "Lumen Drift", "2019 - Glass Harbor"
    )  # fmt: skip
    assert row(index, "", "parent, name") == (None, "")


def test_names_sort_as_people_read_them(index):
    fill(index, [{"path": f"{name}/1.mp3"} for name in
                 ("Disc 10", "disc 9", "_Incoming", "Hollow Coast", "Juniper Sixes")])  # fmt: skip
    assert listed(index, "") == ["disc 9", "Disc 10", "Hollow Coast", "_Incoming", "Juniper Sixes"]
    songs = (
        index.read()
        .execute("SELECT path FROM song WHERE folder = 'Disc 10' ORDER BY name_key")
        .fetchall()
    )
    assert songs == [("Disc 10/1.mp3",)]


def test_a_folders_shared_artist_album_and_year_and_none_where_they_differ(index):
    fill(index, [
        {"path": "M/Kindling/1.mp3", "artist": "Mara Okafor", "album": "Kindling", "year": 2015},
        {"path": "M/Kindling/2.mp3", "artist": "Mara Okafor", "album": "Kindling", "year": 2015},
        {"path": "M/Salt/1.mp3", "artist": "Mara Okafor", "album": "Salt", "year": 2018},
    ])  # fmt: skip
    assert row(index, "M/Kindling", "artist, album, year") == ("Mara Okafor", "Kindling", 2015)
    assert row(index, "M", "artist, album, year") == ("Mara Okafor", None, None)


def scan(music, index, scope=None):
    """A scan taking out what went unasked: the folder rows, not R2.10.1's question, are the
    subject."""
    with ThreadPoolExecutor(1) as pool:
        return scanner.scan(str(music), index, pool, scope=scope, hold=False)


def test_scans_keep_the_rows_after_moves_and_deletes_up_through_the_ancestors(index, tmp_path):
    music = tmp_path / "Music"
    wav(music / "A" / "B" / "C" / "1.wav", 1)
    wav(music / "A" / "B" / "2.wav", 2)
    wav(music / "D" / "3.wav", 3)
    (music / "Scans").mkdir()  # no audio anywhere beneath it: not listed (R2.9.2)
    (music / "Scans" / "page.jpg").write_bytes(b"jpeg")
    scan(music, index)
    assert row(index, "A") == (1, 0, 2, 2) and row(index, "") == (2, 0, 4, 3)
    assert row(index, "Scans") is None
    os.makedirs(music / "D" / "E")
    os.rename(music / "A" / "B" / "C" / "1.wav", music / "D" / "E" / "1.wav")  # a move by hash
    scan(music, index)
    assert row(index, "A/B/C") is None and row(index, "A") == (1, 0, 1, 1)
    assert row(index, "D") == (1, 1, 1, 2) and row(index, "") == (2, 0, 4, 3)
    shutil.rmtree(music / "A")
    known = scan(music, index).folders
    assert paths(index) == ["", "D", "D/E"] and row(index, "") == (1, 0, 2, 2)
    os.remove(music / "D" / "3.wav")
    scan(music, index, scanner.Scope(frozenset({"D"}), known))  # a partial scan too (A2.4)
    assert row(index, "D") == (1, 0, 1, 1) and row(index, "") == (1, 0, 2, 1)


def test_a_cover_added_beside_unchanged_songs_becomes_the_folders_and_its_parents_mosaic(
    index, tmp_path
):
    music = tmp_path / "Music"
    wav(music / "Artist" / "One" / "1.wav", 1)
    wav(music / "Artist" / "Two" / "2.wav", 2)
    scan(music, index)
    assert row(index, "Artist/One", "thumb") == (None,)
    assert row(index, "Artist", "thumb, mosaic") == (None, None)
    (music / "Artist" / "One" / "cover.jpg").write_bytes(b"jpeg")
    st = os.stat(music / "Artist" / "One" / "cover.jpg")
    scan(music, index)
    thumb = art.thumb_id("Artist/One/cover.jpg", st.st_size, st.st_mtime_ns)
    assert row(index, "Artist/One", "cover_kind, cover, thumb") == (
        "file", "Artist/One/cover.jpg", thumb
    )  # fmt: skip
    assert row(index, "Artist", "thumb, mosaic") == (None, thumb)
    os.remove(music / "Artist" / "One" / "cover.jpg")
    scan(music, index)
    assert row(index, "Artist", "mosaic") == (None,)


def test_a_folders_songs_sharing_an_embedded_cover_give_it_theirs(index):
    fill(index, [
        {"path": "J/Velvet/1.m4a", "album": "Velvet Hours", "albumartist": "J", "has_cover": True},
        {"path": "J/Velvet/2.m4a", "album": "Velvet Hours", "albumartist": "J", "has_cover": True},
        {"path": "S/a.mp3", "album": "One", "has_cover": True},
        {"path": "S/b.mp3", "album": "Two", "has_cover": True},
        {"path": "S/c.mp3", "album": "Three"},
    ])  # fmt: skip
    c = index.read()
    thumb = c.execute("SELECT thumb FROM album WHERE title = 'Velvet Hours'").fetchone()[0]
    assert row(index, "J/Velvet", "cover_kind, cover, thumb") == ("embedded", "J/Velvet/1.m4a",
                                                                  thumb)  # fmt: skip
    singles = [t for (t,) in c.execute(
        "SELECT thumb FROM album WHERE title IN ('One', 'Two') ORDER BY title"
    )]  # fmt: skip
    assert row(index, "S", "thumb, mosaic") == (None, " ".join(singles))  # a.mp3's first


def test_an_index_of_slice_3_3_gains_folders_filled_from_its_rows(tmp_path):
    """Version 4 (A2.7): the folders and each song's place come from the rows there, the songs
    not read again; a folder's cover image is the one its album's row names."""
    c = db.connect(str(tmp_path / "musikata.db"))
    for step in db.MIGRATIONS[:3]:
        step(c)
    c.execute("PRAGMA user_version = 3")
    c.execute(
        "INSERT INTO song (id, path, size, mtime_ns) VALUES (1, 'A/Disc 2/x.flac', 10, 5),"
        " (2, 'A/y.mp3', 10, 5)"
    )
    c.execute(
        "INSERT INTO album (identity, artist, title, artist_key, title_key, folder, folder_image,"
        " folder_image_size, folder_image_mtime) VALUES ('a', '', '', '', '', 'A/Disc 2',"
        " 'A/Disc 2/cover.jpg', 3, 4)"
    )
    assert db.migrate(c) == len(db.MIGRATIONS)
    assert c.execute("SELECT mtime_ns, folder FROM song ORDER BY id").fetchall() == [
        (5, "A/Disc 2"), (5, "A")
    ]  # fmt: skip
    assert c.execute("SELECT path, songs_beneath, thumb FROM folder ORDER BY path").fetchall() == [
        ("", 2, None),
        ("A", 2, None),
        ("A/Disc 2", 1, art.thumb_id("A/Disc 2/cover.jpg", 3, 4)),
    ]
    c.close()


# ---------- reading ----------


def test_a_search_finds_folders_whose_names_hold_every_word_case_and_accents_aside(index):
    fill(index, [{"path": f"{n}/1.mp3"} for n in ("Beyoncé Live", "100%_Pure", "A-B")])
    c = index.read()

    def found(text):
        where, params = folders.condition(search.parse(text))
        return [p for (p,) in c.execute(f"SELECT path FROM folder WHERE {where}", params)]

    assert found("beyonce li") == ["Beyoncé Live"]
    assert found("0%_p") == ["100%_Pure"] and found("a_b") == []  # % and _ are text
    assert found("artist:beyonce") == [] and found("rating:>=4") == []


def test_a_selection_of_folders_resolves_to_the_songs_beneath_them(index):
    fill(index, [{"path": p} for p in ("A/B/2.mp3", "A/B/1.mp3", "A/z.mp3", "AB/x.mp3", "c.mp3")])
    c = index.read()
    assert folders.count_songs(c, ["A"], []) == 3  # not AB's
    assert folders.count_songs(c, ["A", "A/B"], ["A/z.mp3", "c.mp3"]) == 4  # each once
    assert folders.count_songs(c, [], []) == 0
    assert folders.first_song(c, "A") == "A/B/1.mp3"  # subfolders first, then files, by name
    assert folders.first_song(c, "") == "A/B/1.mp3" and folders.first_song(c, "Nope") is None
    where, params = folders.beneath("path", "")
    assert c.execute(f"SELECT COUNT(*) FROM song WHERE {where}", params).fetchone()[0] == 5
