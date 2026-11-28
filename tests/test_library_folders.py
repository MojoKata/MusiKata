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


def test_an_album_changed_through_another_folder_brings_each_of_its_folders_up_to_date(index):
    """A folder shows its album's cover, which can come from a song in another folder (an album
    over Disc 1 and Disc 2): a change there changes what this folder shows (A2.7)."""
    disc = [{"path": f"X/Disc {n}/1.m4a", "album": "Velvet Hours", "albumartist": "J",
             "disc": n, "has_cover": True} for n in (1, 2)]  # fmt: skip
    fill(index, disc)
    c = index.read()

    def album_thumb():
        return c.execute("SELECT thumb FROM album").fetchone()[0]

    assert row(index, "X/Disc 2", "thumb") == (album_thumb(),)
    fill(index, [{**disc[0], "size": 2000}])  # its cover's song, changed
    assert album_thumb() == art.thumb_id("X/Disc 1/1.m4a", 2000, 1)
    assert row(index, "X/Disc 2", "thumb") == (album_thumb(),)


def test_loose_songs_on_no_album_give_their_folder_their_embedded_covers(index):
    """R5.8: a folder's cover is the front cover embedded in its songs when they share one, and
    loose songs whose covers differ make a mosaic, whether or not they name an album."""
    fill(index, [
        {"path": "S/b.mp3", "has_cover": True}, {"path": "S/a.mp3", "has_cover": True},
        {"path": "S/c.mp3"}, {"path": "S/d.mp3", "album": "One", "has_cover": True},
        {"path": "T/x.mp3", "has_cover": True},
    ])  # fmt: skip
    one = index.read().execute("SELECT thumb FROM album").fetchone()[0]
    loose = [art.thumb_id(f"S/{n}.mp3", 1000, 1) for n in "ab"]
    assert row(index, "S", "thumb, mosaic") == (None, " ".join([*loose, one]))
    assert row(index, "T", "cover_kind, cover, thumb") == (
        "embedded", "T/x.mp3", art.thumb_id("T/x.mp3", 1000, 1)
    )  # fmt: skip


def test_an_index_of_slice_3_3_gains_folders_and_its_songs_are_read_again(tmp_path):
    """Version 4 (A2.7): each song's place and the folder rows are the scan's to work out
    (folders.py, sortnames.py), and that code changes after the migration is released, so the
    migration, fixed in time, marks every song changed: the next scan reads them all and fills the
    folders, a cover image beside them included."""
    music = tmp_path / "Music"
    wav(music / "A" / "Disc 2" / "x.wav", 1)
    wav(music / "A" / "y.wav", 2)
    (music / "A" / "Disc 2" / "cover.jpg").write_bytes(b"jpeg")
    path = str(tmp_path / "musikata.db")
    c = db.connect(path)
    for step in db.MIGRATIONS[:3]:
        step(c)
    c.execute("PRAGMA user_version = 3")
    for n, rel in enumerate(("A/Disc 2/x.wav", "A/y.wav"), 1):
        st = os.stat(music / rel)
        c.execute(
            "INSERT INTO song (id, path, size, mtime_ns) VALUES (?, ?, ?, ?)",
            (n, rel, st.st_size, st.st_mtime_ns),
        )
    assert db.migrate(c) == len(db.MIGRATIONS)
    assert c.execute("SELECT mtime_ns, folder FROM song ORDER BY id").fetchall() == [
        (-1, None), (-1, None)
    ]  # fmt: skip
    assert c.execute("SELECT COUNT(*) FROM folder").fetchone() == (0,)
    c.close()
    index = db.Index(path)
    assert scan(music, index).changed == 2
    st = os.stat(music / "A" / "Disc 2" / "cover.jpg")
    assert index.read().execute(
        "SELECT path, songs_beneath, thumb FROM folder ORDER BY path"
    ).fetchall() == [
        ("", 2, None),
        ("A", 2, None),
        ("A/Disc 2", 1, art.thumb_id("A/Disc 2/cover.jpg", st.st_size, st.st_mtime_ns)),
    ]
    index.close()


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
    paths = dict(c.execute("SELECT id, path FROM song"))
    # subfolders first, each whole, then files, by name: what Play on a folder queues (R7.1)
    in_a = ["A/B/1.mp3", "A/B/2.mp3", "A/z.mp3"]
    assert [paths[i] for i in folders.songs_beneath(c, "A")] == in_a
    assert [paths[i] for i in folders.songs_beneath(c, "")] == [*in_a, "AB/x.mp3", "c.mp3"]
    assert folders.songs_beneath(c, "Nope") == []
    where, params = folders.beneath("path", "")
    assert c.execute(f"SELECT COUNT(*) FROM song WHERE {where}", params).fetchone()[0] == 5


def test_a_selection_is_one_album_only_when_every_song_it_stands_for_is_on_it(index):
    """R2.9.6: Album art is offered for a selection when its songs are one album."""
    fill(index, [
        {"path": "LD/GH/01.flac", "album": "Glass Harbor", "artist": "Lumen Drift"},
        {"path": "LD/GH/02.flac", "album": "Glass Harbor", "artist": "Lumen Drift"},
        {"path": "LD/TT/01.flac", "album": "Tide Tables", "artist": "Lumen Drift"},
        {"path": "LD/loose.mp3"},
    ])  # fmt: skip
    c = index.read()
    (glass,) = c.execute("SELECT id FROM album WHERE title = 'Glass Harbor'").fetchone()
    assert folders.album_of(c, ["LD/GH"], []) == glass
    assert folders.album_of(c, ["LD/GH"], ["LD/GH/01.flac"]) == glass  # a file inside it, once
    assert folders.album_of(c, [], ["LD/GH/02.flac"]) == glass
    assert folders.album_of(c, ["LD/GH", "LD/TT"], []) is None  # two albums
    assert folders.album_of(c, ["LD/GH"], ["LD/loose.mp3"]) is None  # a song on none
    assert folders.album_of(c, [], ["LD/loose.mp3"]) is None
    assert folders.album_of(c, ["Nope"], []) is None and folders.album_of(c, [], []) is None


# ---------- tags match path (R3.9, R2.9.5) ----------

LD = "Lumen Drift"
TIDE = [
    {"path": f"Lumen Drift/Tide Tables/0{n} - {t}.flac", "title": t, "track": n,
     "albumartist": a, "album": "Tide Tables"}
    for n, t, a in ((1, "Neap Tide", LD), (2, "Spring Tide", LD), (3, "Slack Water", "lumen drift"))
] + [
    {"path": "Lumen Drift/Glass Harbor/01 - Tidewater.flac", "title": "Tidewater", "track": 1,
     "albumartist": LD, "album": "Glass Harbor"},
    {"path": "_Incoming/new rips/track01.mp3"},
    {"path": "_Incoming/new rips/Signal Fires.flac", "title": "Signal Fires"},
]  # fmt: skip


def states(index):
    return {p: (s, d) for p, s, d in index.read().execute(
        "SELECT path, path_state, path_diff FROM song")}  # fmt: skip


def test_a_write_keeps_each_songs_path_match_and_each_folders_worst_beneath(index):
    """R3.9, A2.6: each song's state under its folder's pattern, and how it differs; A2.7, R2.9.5:
    each folder the worst state beneath it and how many files beneath it can be fixed or have no
    tags, up through its ancestors."""
    fill(index, TIDE)
    got = states(index)
    assert got["Lumen Drift/Tide Tables/01 - Neap Tide.flac"] == (0, None)
    assert got["Lumen Drift/Tide Tables/03 - Slack Water.flac"] == (
        1, '[["albumartist", "case", "Lumen Drift", "lumen drift"]]')  # fmt: skip
    assert got["_Incoming/new rips/track01.mp3"] == (2, None)  # no tags, no pattern fits
    assert got["_Incoming/new rips/Signal Fires.flac"] == (None, None)
    by = {p: (s, n) for p, s, n in index.read().execute(
        "SELECT path, path_state, path_fix FROM folder")}  # fmt: skip
    assert by["Lumen Drift/Tide Tables"] == (1, 1) and by["Lumen Drift/Glass Harbor"] == (0, 0)
    assert by["Lumen Drift"] == (1, 1) and by["_Incoming/new rips"] == (2, 1)
    assert by["_Incoming"] == (2, 1) and by[""] == (2, 2)


def test_one_song_written_again_brings_its_folders_states_up_to_date(index):
    """A song fixed is a match, and the folder above it with it; a folder's pattern is its whole
    folder's, so its other songs are worked out again."""
    fill(index, TIDE)
    fill(index, [dict(TIDE[2], albumartist=LD)])
    assert states(index)["Lumen Drift/Tide Tables/03 - Slack Water.flac"] == (0, None)
    assert row(index, "Lumen Drift", "path_state, path_fix") == (0, 0)
    gone = [p for p in states(index) if p.startswith("_Incoming")]
    index.write(lambda c: scanner._remove(c, gone, {}, None)).result()
    assert row(index, "", "path_state, path_fix") == (0, 0)


def test_the_users_own_patterns_are_kept_and_every_folder_worked_out_again_when_they_change(index):
    """R3.3, R13.4: the root's settings' patterns, kept in the index; a change works out every
    folder again, the same ones none."""
    fill(index, [{"path": "Lumen Drift/Tide Tables/04 - Moonpull.flac", "title": "Moonpull",
                  "artist": "lumen drift", "album": "Tide Tables", "track": 4}])  # fmt: skip
    moon = "Lumen Drift/Tide Tables/04 - Moonpull.flac"
    assert states(index)[moon][0] == 1  # no album artist, which the preset reads
    user = ["{artist}/{album}/{track} - {title}"]
    assert index.write(lambda c: folders.set_user_patterns(c, user)).result()
    assert folders.user_patterns(index.read()) == user
    assert states(index)[moon] == (1, '[["artist", "case", "Lumen Drift", "lumen drift"]]')
    assert not index.write(lambda c: folders.set_user_patterns(c, user)).result()
    assert index.write(lambda c: folders.set_user_patterns(c, [])).result()
    assert folders.user_patterns(index.read()) == []


OST = " (Original Soundtrack)"
MOJIBAKE = "Ñåâåðíûé Âåòåð"  # a name in the wrong encoding (R4.10), as the folder spells it too
SHAPES = [
    {"path": "Lumen Drift/2019 - Glass Harbor/01 - Tidewater.flac", "albumartist": LD,
     "artist": LD, "album": "Glass Harbor", "year": 2019, "track": 1, "title": "Tidewater"},
    {"path": "Lumen Drift/Remixes/Glass Harbor/01 - Atlas Copper.flac", "albumartist": LD,
     "artist": LD, "album": "Glass Harbor Remixed", "track": 1, "title": "Atlas Copper"},
    {"path": "Lumen Drift/Remixes/Tide Tables/01 - Silver Signal.mp3", "albumartist": LD,
     "artist": LD, "album": "Tide Tables Remixed", "track": 1, "title": "Silver Signal"},
    {"path": "Soundtracks/Night Ferry/01 - Tide Lantern.ogg", "artist": "Cinder Fern",
     "album": "Night Ferry" + OST, "compilation": True, "track": 1, "title": "Tide Lantern"},
    {"path": "Soundtracks/Paper Satellites/01 - Static Orbit.m4a", "albumartist":
     "Various Artists", "artist": "Wire Glass", "album": "Paper Satellites" + OST, "track": 1,
     "title": "Static Orbit"},
    {"path": "Soundtracks/The Long Signal/01 - Iron Meridian.flac", "albumartist": "Ada Kerr",
     "artist": "Moon Ember", "album": "The Long Signal" + OST, "track": 1,
     "title": "Iron Meridian"},
    {"path": f"{MOJIBAKE}/Òèõàÿ Ãàâàíü/01 - Òóìàí.mp3", "artist": MOJIBAKE,
     "album": "Òèõàÿ Ãàâàíü", "track": 1, "title": "Òóìàí"},
    {"path": "Mara Okafor/Kindling/01 - Embers.flac", "artist": "Mara Okafor",
     "album": "Kindling", "track": 1, "title": "Embers"},
    {"path": "Mara Okafor/Salt & Ember/01 - Brine.flac", "artist": "Mara Okafor",
     "album": "Salt & Ember", "track": 1, "title": "Brine"},
]  # fmt: skip


def test_a_library_of_nested_and_grouped_folders_is_judged_as_people_file_it(index):
    """R3.9: a folder above an album that isn't its artist (Remixes, Soundtracks) gives no album
    artist, and a folder's shorter name of the album agrees; a folder in the wrong encoding whose
    songs have no album artist, and an artist's folder whose songs all lack the album artist tag,
    are still flagged."""
    fill(index, SHAPES)
    got = states(index)
    flagged = {p: d for p, (s, d) in got.items() if s}
    assert flagged == {
        f"{MOJIBAKE}/Òèõàÿ Ãàâàíü/01 - Òóìàí.mp3": f'[["albumartist", "missing", "{MOJIBAKE}"]]',
        "Mara Okafor/Kindling/01 - Embers.flac":
            '[["albumartist", "missing", "Mara Okafor"]]',
        "Mara Okafor/Salt & Ember/01 - Brine.flac":
            '[["albumartist", "missing", "Mara Okafor"]]',
    }  # fmt: skip
    assert set(got) == {s["path"] for s in SHAPES}
    assert row(index, "Soundtracks", "path_state, path_fix, grouping") == (0, 0, 1)
    assert row(index, "Lumen Drift", "path_state, path_fix, grouping") == (0, 0, 0)
    assert row(index, "Lumen Drift/Remixes", "grouping") == (1,)
    assert row(index, "", "path_state, path_fix, grouping") == (1, 3, 0)


def test_whether_a_folder_groups_albums_is_read_from_the_songs_beneath_it(index):
    """R3.9: two or more folders of songs beneath it, none of whose songs carries its name as
    album artist or artist; never the root, nor a folder the index hasn't."""
    fill(index, SHAPES)
    c = index.read()
    grouping = {p: folders.grouping(c, p) for p in (
        "Soundtracks", "Lumen Drift/Remixes", "Lumen Drift", "Mara Okafor", MOJIBAKE,
        "Soundtracks/Night Ferry", "", "Nope")}  # fmt: skip
    assert [p for p, g in grouping.items() if g] == ["Soundtracks", "Lumen Drift/Remixes"]
    asked = folders.Groupings(c)
    assert asked.around("Soundtracks/Night Ferry") == {"Soundtracks"}
    assert asked.around("Lumen Drift/Remixes/Tide Tables") == {"Lumen Drift/Remixes"}
    assert asked.known == {"Soundtracks/Night Ferry": False, "Soundtracks": True,
                           "Lumen Drift/Remixes/Tide Tables": False,
                           "Lumen Drift/Remixes": True, "Lumen Drift": False}  # fmt: skip


def test_a_write_that_turns_whether_a_folder_groups_albums_works_out_its_songs_again(index):
    """R3.9: a second album folder makes Soundtracks group albums, so the first's songs lose the
    album artist it gave them; a song beneath it tagged with its name makes it an artist's again;
    the second album gone, it is one artist's album folder."""
    ferry = "Soundtracks/Night Ferry/01 - Tide Lantern.ogg"
    fill(index, [SHAPES[3]])
    assert states(index)[ferry] == (1, '[["albumartist", "missing", "Soundtracks"]]')
    assert row(index, "Soundtracks", "grouping") == (0,)
    fill(index, [SHAPES[4]])
    assert states(index)[ferry] == (0, None)
    assert row(index, "Soundtracks", "path_state, path_fix, grouping") == (0, 0, 1)
    fill(index, [dict(SHAPES[4], albumartist="Soundtracks")])
    assert states(index)[ferry] == (1, '[["albumartist", "missing", "Soundtracks"]]')
    assert row(index, "Soundtracks", "path_state, path_fix, grouping") == (1, 1, 0)
    fill(index, [SHAPES[4]])
    assert states(index)[ferry] == (0, None)
    index.write(lambda c: scanner._remove(c, [SHAPES[4]["path"]], {}, None)).result()
    assert states(index)[ferry] == (1, '[["albumartist", "missing", "Soundtracks"]]')
    assert row(index, "Soundtracks", "path_state, path_fix, grouping") == (1, 1, 0)


def tagged(path, seed, **frames):
    """A WAV (`wav`) with ID3 frames: TPE1, TPE2, TALB, TRCK, TIT2, each text."""
    import mutagen.id3
    import mutagen.wave

    wav(path, seed)
    f = mutagen.wave.WAVE(str(path))
    f.add_tags()
    for name, text in frames.items():
        f.tags.add(getattr(mutagen.id3, name)(encoding=3, text=text))
    f.save()


@pytest.mark.slow
def test_an_index_of_slice_8_loses_its_false_flags_as_its_songs_are_read_again(tmp_path):
    """Version 16 (R3.9): an index whose states were worked out by the eager matching keeps them
    until its songs are read again; the migration marks every song to be, so the next scan works
    out every folder's states again, and whether each folder groups albums."""
    music = tmp_path / "Music"
    songs = [
        ("Soundtracks/Night Ferry/01 - Tide Lantern.wav", "Night Ferry" + OST),
        ("Soundtracks/Paper Satellites/01 - Static Orbit.wav", "Paper Satellites" + OST),
    ]
    for n, (rel, album) in enumerate(songs, 1):
        title = rel.rpartition(" - ")[2][:-4]
        tagged(music / rel, n, TPE1="Cinder Fern", TPE2="Various Artists", TALB=album,
               TRCK="1", TIT2=title)  # fmt: skip
    path = str(tmp_path / "musikata.db")
    c = db.connect(path)
    for step in db.MIGRATIONS[:15]:
        step(c)
    c.execute("PRAGMA user_version = 15")
    eager = '[["albumartist", "differs", "Soundtracks"]]'
    for n, (rel, _album) in enumerate(songs, 1):
        st = os.stat(music / rel)
        c.execute(
            "INSERT INTO song (id, path, folder, size, mtime_ns, path_state, path_diff)"
            " VALUES (?, ?, ?, ?, ?, 1, ?)",
            (n, rel, rel.rpartition("/")[0], st.st_size, st.st_mtime_ns, eager),
        )
    assert db.migrate(c) == len(db.MIGRATIONS)
    assert c.execute("SELECT DISTINCT mtime_ns FROM song").fetchall() == [(-1,)]
    c.close()
    index = db.Index(path)
    assert scan(music, index).changed == 2
    assert set(states(index).values()) == {(0, None)}
    assert row(index, "Soundtracks", "path_state, path_fix, grouping") == (0, 0, 1)
    index.close()


def test_how_a_song_differs_is_kept_as_json_and_read_back_whatever_the_column_holds():
    from musikata_core.patterns import Difference

    diffs = (Difference("year", "missing", "2022"), Difference("artist", "case", "Ünïcode", "ü"))
    text = folders.diff_text(diffs)
    assert folders.diffs_of(text) == diffs and "Ünïcode" in text
    assert [d.old for d in folders.diffs_of(text)] == ["", "ü"]  # the tag's value, when it has one
    assert folders.diffs_of('[["year", "missing", "2022"]]') == diffs[:1]  # kept without it
    assert folders.diff_text(()) is None
    for broken in (None, "", "not json", "{}", '[["a", "b"], 3]', "[[1, 2, 3]]"):
        got = folders.diffs_of(broken)
        assert got == () or got == (Difference("1", "2", "3"),)
    assert folders.worst([None, 0, 1, None]) == 1 and folders.worst([None]) is None


def test_the_songs_infer_from_path_plans_from_are_read_in_the_order_asked_with_their_folders(
    index,
):
    fill(index, TIDE)
    c = index.read()
    ids = dict(c.execute("SELECT path, id FROM song"))
    asked = [ids[TIDE[2]["path"]], 99_999, ids[TIDE[0]["path"]]]
    got = folders.tags_of(c, asked)
    assert [(i, p) for i, p, _ in got] == [(asked[0], TIDE[2]["path"]), (asked[2], TIDE[0]["path"])]
    assert got[0][2].albumartist == "lumen drift" and got[0][2].track == 3
    assert folders.counts_of(c, ["Lumen Drift/Tide Tables", "nowhere"]) == {
        "Lumen Drift/Tide Tables": 3, "nowhere": 0}  # fmt: skip
