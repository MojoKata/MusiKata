"""Genres (src/musikata_core/genres.py; R9): the names that look like one genre, renaming and
merging a genre in every song that has it, a genre's tile, and the genre list suggested while
typing.

Why: genre names come from every program that ever tagged a file, each with its own spelling
("Hip-Hop", "hip hop", "HipHop", "Drum 'n' Bass", "(13)"), and a merge rewrites every file that has
one: a rule that groups too much rewrites genres the user meant apart, one that groups too little
leaves the near duplicates R9.5 promises to find. The shapes of genre names are listed in
docs/process/testing.md, "Shapes"."""

import pytest
from fakes import fill
from hypothesis import given
from hypothesis import strategies as st
from mutagen.id3 import TCON

from musikata_core import db, genres, search
from musikata_core.genres import GenreNameError, Group, Tile
from musikata_core.tags import Tags, parse
from musikata_core.tags.tools import Song


def same_key(*names):
    return len({genres.key(n) for n in names}) == 1


# ---------- the shapes of a genre's name ----------


def test_case_spacing_and_punctuation_are_set_aside():
    """R9.5's own examples, and the spellings other programs leave."""
    assert same_key("Hip-Hop", "Hip Hop", "hiphop", "HIP-HOP", "Hip  hop", " hip_hop ", "Hip.Hop")
    assert same_key("Post-Rock", "Post Rock", "postrock", "POST-ROCK")
    assert same_key("Lo-Fi", "Lo Fi", "lofi", "LO-FI")
    assert same_key("Electronic", "electronic", "ELECTRONIC", "Electronic ", "Electronic!")


def test_accents_composed_or_as_a_letter_and_its_mark_are_set_aside():
    composed, decomposed = "Musique électronique", "Musique électronique"
    assert same_key(composed, decomposed, "musique electronique", "MUSIQUE ÉLECTRONIQUE")
    assert same_key("Straße", "STRASSE", "strasse")  # ß, in any case
    assert same_key("Шансон", "шансон")  # a script with case, but no Latin letters


def test_and_is_and_whether_written_as_a_word_an_ampersand_or_a_lone_n():
    assert same_key("Drum & Bass", "Drum and Bass", "Drum'n'Bass", "Drum 'n' Bass", "drum n bass")
    assert same_key("Rock & Roll", "Rock and Roll", "Rock 'n' Roll", "rock-n-roll")
    assert same_key("R&B", "R and B", "R'n'B", "r & b")
    assert not same_key("RnB", "R&B")  # "rnb" is a word of its own, not "r", "n", "b"


def test_slashes_part_two_names_like_any_mark_and_their_order_matters():
    assert same_key("Rock/Pop", "Rock / Pop", "Rock-Pop", "rock pop", "Rock\\Pop")
    assert not same_key("Rock/Pop", "Pop/Rock")  # two names in another order: another genre


def test_a_numbered_id3_genre_is_the_genre_it_numbers():
    """R9.3: ID3v1's numbers, as other kinds of file can hold them, as text."""
    assert same_key("(13)", "13", " ( 13 ) ", "Pop", "pop")
    assert same_key("(17)", "Rock") and same_key("(52)", "Electronic")
    assert parse.numbered_genre("(80)") == "Folk" and parse.numbered_genre("191") == "Psybient"
    assert parse.numbered_genre("(255)") == "(255)" and parse.numbered_genre("1999") == "1999"
    assert not same_key("(255)", "Pop") and same_key("(255)", "255")
    assert parse.numbered_genre("Pop (13)") == "Pop (13)"


def test_names_that_differ_by_more_than_spelling_are_apart():
    """Electronica is a genre of its own to many: it joins Electronic only when the user says so
    (`test_genres_the_user_has_said_are_the_same_join_whatever_their_spelling`)."""
    assert not same_key("Electronic", "Electronica")
    assert not same_key("Rock", "Rocks")
    assert not same_key("Indie", "Indie Rock")


def test_a_name_of_marks_alone_is_its_own_key():
    assert genres.key("?") != genres.key("!!") and genres.key("?") == "?"
    assert genres.key("") == "" and genres.key("   ") == ""


@given(st.text())
def test_any_text_has_a_key_its_case_and_spaces_around_it_aside(text):
    found = genres.key(text)
    assert isinstance(found, str) and found == genres.key(f"  {text}\t")


# ---------- near duplicates (R9.5) ----------


def test_genres_that_look_like_one_are_a_group_the_most_used_first():
    """R9.5's banner: the group with the most songs first, the most used name first in each."""
    counts = {"Hip-Hop": 12, "Hip Hop": 3, "hiphop": 40, "Jazz": 9, "Post-Rock": 4,
              "post rock": 7, "Electronic": 214, "Electronica": 17, "electronic": 6}  # fmt: skip
    found = genres.near_duplicates(counts)
    assert found == [
        Group(("Electronic", "electronic"), (214, 6)),
        Group(("hiphop", "Hip-Hop", "Hip Hop"), (40, 12, 3)),
        Group(("post rock", "Post-Rock"), (7, 4)),
    ]
    assert found[1].chosen == "hiphop" and found[1].others == ("Hip-Hop", "Hip Hop")


def test_of_names_used_as_often_the_one_with_a_capital_is_chosen():
    assert genres.near_duplicates({"electronic": 5, "Electronic": 5})[0].chosen == "Electronic"
    assert genres.near_duplicates({"b": 1, "B": 1})[0].names == ("B", "b")


def test_genres_the_user_has_said_are_the_same_join_whatever_their_spelling():
    """R9.5: the root's same_genres (R13.3); a name of the same key as one the user named joins
    too, and groups that share a name are one."""
    counts = {"Electronic": 214, "Electronica": 17, "electronic": 6, "electronica ": 1,
              "Synthwave": 64, "Retrowave": 3, "Outrun": 2, "Jazz": 9}  # fmt: skip
    same = [["Electronic", "Electronica"], ["Synthwave", "Retrowave"], ["retrowave", "Outrun"]]
    found = genres.near_duplicates(counts, same)
    assert found == [
        Group(("Electronic", "Electronica", "electronic", "electronica "), (214, 17, 6, 1)),
        Group(("Synthwave", "Retrowave", "Outrun"), (64, 3, 2)),
    ]


def test_names_the_user_said_are_the_same_that_the_library_hasnt_offer_nothing():
    counts = {"Electronic": 10, "Jazz": 3}
    assert genres.near_duplicates(counts, [["Electronic", "Electronica"], ["", "Jazz"]]) == []
    assert genres.near_duplicates({}) == [] and genres.near_duplicates({"Pop": 1}) == []


@given(st.dictionaries(st.text(max_size=8), st.integers(1, 50), max_size=12))
def test_every_genre_is_in_one_group_at_most_and_each_group_is_one_key(counts):
    found = genres.near_duplicates(counts)
    names = [n for g in found for n in g.names]
    assert len(names) == len(set(names)) and set(names) <= set(counts)
    for g in found:
        assert len(g.names) > 1 and len({genres.key(n) for n in g.names}) == 1
        assert g.counts == tuple(counts[n] for n in g.names)
        assert g.counts[0] == max(g.counts)


# ---------- renaming and merging (R9.4) ----------


def songs(*held):
    return [Song(f"/m/{i:02d}.flac", Tags(title=f"Song {i}", genres=g)) for i, g in enumerate(held)]


def test_a_merge_puts_the_genre_in_each_songs_genres_where_the_old_one_was():
    given_songs = songs(("Electronica",), ("Ambient", "Electronica", "Jazz"), ("Jazz",), ())
    planned = genres.merge(given_songs, ["Electronica"], "Electronic")
    assert [t.genres for t in planned.new] == [
        ("Electronic",),
        ("Ambient", "Electronic", "Jazz"),
        ("Jazz",),
        (),
    ]
    assert [planned.changed(i) for i in range(4)] == [("genres",), ("genres",), (), ()]
    assert planned.columns == ("genres",)
    jobs = planned.jobs({0, 1, 2, 3})
    assert [(j.path, dict(j.changes)) for j in jobs] == [
        ("/m/00.flac", {"genres": ["Electronic"]}),
        ("/m/01.flac", {"genres": ["Ambient", "Electronic", "Jazz"]}),
    ]


def test_a_song_with_both_names_keeps_one_and_the_new_name_in_another_case_is_made_one():
    """R9.2: each genre once; a merge leaves one spelling (R9.5)."""
    given_songs = songs(("Electronic", "Electronica"), ("Electronica", "electronic"),
                        ("electronic", "Ambient"))  # fmt: skip
    planned = genres.merge(given_songs, ["Electronica", "electronic"], "Electronic")
    assert [t.genres for t in planned.new] == [
        ("Electronic",),
        ("Electronic",),
        ("Electronic", "Ambient"),
    ]
    one = genres.merge(songs(("electronic", "Electronica")), ["Electronica"], "Electronic")
    assert one.new[0].genres == ("Electronic",)  # not "electronic": the name merged into


def test_a_rename_renames_and_a_name_another_genre_has_merges_them():
    given_songs = songs(("Electronica",), ("Electronic", "Ambient"), ("Electronica", "Ambient"))
    renamed = genres.rename(given_songs, "Electronica", "  Electronic Dance ")
    assert [t.genres for t in renamed.new] == [
        ("Electronic Dance",),
        ("Electronic Dance", "Ambient"),
        ("Electronic", "Ambient"),
    ]  # the songs that change first, so the preview lists them and counts the rest (R3.7)
    assert [s.path for s in renamed.songs] == ["/m/00.flac", "/m/02.flac", "/m/01.flac"]
    merged = genres.rename(given_songs, "Electronica", "Electronic")
    assert [t.genres for t in merged.new] == [
        ("Electronic",),
        ("Electronic", "Ambient"),
        ("Electronic", "Ambient"),
    ]
    same = genres.rename(given_songs, "Electronica", "Electronica")
    assert not any(same.changed(i) for i in range(3))
    recased = genres.rename(songs(("hip hop",)), "hip hop", "Hip Hop")
    assert recased.new[0].genres == ("Hip Hop",)


@pytest.mark.parametrize(
    "name, why",
    [("", "Type the genre's new name"), ("   ", "Type the genre's new name"),
     ("Rock; Pop", "can't hold ;"), ("Rock\x00Pop", "can't hold ;")],
)  # fmt: skip
def test_a_new_name_that_cant_be_written_says_why(name, why):
    with pytest.raises(GenreNameError, match=why):
        genres.rename(songs(("Rock",)), "Rock", name)
    with pytest.raises(GenreNameError, match=why):
        genres.merge(songs(("Rock",)), ["Rock"], name)


# ---------- the tiles (R9.1) ----------


def test_a_tile_is_a_genres_songs_albums_and_three_covers_of_its_albums_with_the_most_songs():
    counts = [("Jazz", 9, 2), ("Electronic", 214, 18), ("ambient", 9, 1), ("Folk", 96, 9)]
    covers = [("Electronic", "a", 3), ("Electronic", "b", 10), ("Electronic", "c", 1),
              ("Electronic", "d", 10), ("Jazz", "j", 4)]  # fmt: skip
    found = genres.tiles(counts, covers)
    assert found == [
        Tile("Electronic", 214, 18, ("b", "d", "a")),
        Tile("Folk", 96, 9, ()),
        Tile("ambient", 9, 1, ()),
        Tile("Jazz", 9, 2, ("j",)),
    ]
    by_name = genres.tiles(counts, covers, "name")
    assert [t.name for t in by_name] == ["ambient", "Electronic", "Folk", "Jazz"]
    with pytest.raises(ValueError, match="no such order"):
        genres.tiles(counts, covers, "albums")


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


LIBRARY = [
    {"path": "A/One/01.flac", "artist": "A", "album": "One", "albumartist": "A",
     "genres": ("Electronic", "Ambient"), "has_cover": True},
    {"path": "A/One/02.flac", "artist": "A", "album": "One", "albumartist": "A",
     "genres": ("Electronic",), "has_cover": True},
    {"path": "A/Two/01.flac", "artist": "A", "album": "Two", "albumartist": "A",
     "genres": ("electronic",)},
    {"path": "B/Three/01.flac", "artist": "B", "album": "Three", "albumartist": "B",
     "genres": ("Electronica", "Jazz"), "title": "Blue Hour"},
    {"path": "Loose/single.flac", "artist": "C", "genres": ("Electronic",)},
    {"path": "Loose/none.flac", "artist": "C"},
]  # fmt: skip


def test_the_indexs_tiles_count_a_song_towards_each_of_its_genres(index):
    """R9.2: a song counts towards each of its genres; albums are counted once, a song on none
    in none; covers are those of albums with a cover."""
    fill(index, LIBRARY)
    found, total = genres.read_tiles(index.read())
    assert total == 5
    by_name = {t.name: t for t in found}
    assert [t.name for t in found] == ["Electronic", "Ambient", "electronic", "Electronica", "Jazz"]
    assert (by_name["Electronic"].songs, by_name["Electronic"].albums) == (3, 1)
    assert (by_name["Ambient"].songs, by_name["Jazz"].songs) == (1, 1)
    assert len(by_name["Electronic"].covers) == 1 and by_name["Ambient"].covers
    assert by_name["Jazz"].covers == ()
    assert genres.counts(index.read()) == {
        "Electronic": 3, "Ambient": 1, "electronic": 1, "Electronica": 1, "Jazz": 1
    }  # fmt: skip


def test_a_search_leaves_the_genres_of_the_songs_it_finds(index):
    """R2.7: the Genres view filtered by the header's search."""
    fill(index, LIBRARY)
    where, params = search.condition(search.parse("blue hour"))
    found, total = genres.read_tiles(index.read(), "name", where, params)
    assert [t.name for t in found] == ["Electronica", "Jazz"] and total == 5
    assert found[0].songs == 1


def test_the_songs_of_genres_are_found_and_counted_once_each(index):
    fill(index, LIBRARY)
    c = index.read()
    ids = genres.songs_of(c, ["Electronic", "Ambient"])
    paths = [c.execute("SELECT path FROM song WHERE id = ?", (i,)).fetchone()[0] for i in ids]
    assert paths == ["A/One/01.flac", "A/One/02.flac", "Loose/single.flac"]
    assert genres.files_of(c, ["Electronic", "Ambient", "electronic"]) == 4
    assert genres.songs_of(c, []) == [] and genres.files_of(c, []) == 0


# ---------- the genre list (R9.6) ----------


def test_the_built_in_list_is_short_and_each_of_its_names_is_id3s():
    """R9.6's built-in list: ID3's numbered genres' broad ones (Mutagen's TCON.GENRES)."""
    assert 20 <= len(genres.BUILT_IN) <= 40
    assert set(genres.BUILT_IN) <= set(TCON.GENRES)
    assert len(set(genres.BUILT_IN)) == len(genres.BUILT_IN)


def test_the_library_suggests_its_own_genres_first_then_the_built_in_list(index):
    """R9.6: the names suggested while typing are those in the library plus the built-in list,
    one spelling of each, the library's first."""
    fill(index, LIBRARY)
    c = index.read()
    assert search.suggestions(c, "genres", "elec", extra=genres.BUILT_IN) == [
        "Electronic",
        "electronic",
        "Electronica",
    ]  # the built-in "Electronic" is the library's already
    assert search.suggestions(c, "genres", "ja", extra=genres.BUILT_IN) == ["Jazz"]
    assert search.suggestions(c, "genres", "reg", extra=genres.BUILT_IN) == ["Reggae"]
    assert search.suggestions(c, "genres", "reg") == []
    assert search.suggestions(c, "genres", "rock", extra=genres.BUILT_IN) == [
        "Rock", "Hard Rock", "Indie Rock"
    ]  # fmt: skip
