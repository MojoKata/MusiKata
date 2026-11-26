"""Search (src/musikata_core/search.py; R2.7, A2.5): what the user types, as an FTS5 query and
column filters, and the index's song_fts kept in step with its songs by the scan.

Why: the search box takes anything a user types, as they type it: half a word, accents, quotes
left open, FTS5's own operators, a `field:` MusiKata doesn't know. A query FTS5 can't read raises
in the middle of typing, and one that matches the wrong column, or misses a song a scan changed,
shows a view that isn't the library. The shapes are listed in docs/process/testing.md, "Shapes"."""

import functools
import sqlite3

import pytest
from fakes import fill
from hypothesis import example, given
from hypothesis import strategies as st

from musikata_core import db, scanner, search
from musikata_core.search import Compare, Query, Term


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


SONGS = [
    {"path": "Beyoncé/Lemonade/01 Pray You Catch Me.flac", "title": "Pray You Catch Me",
     "artist": "Beyoncé", "album": "Lemonade", "year": 2016, "genres": ("R&B", "Pop"),
     "rating": 5},
    {"path": "Lumen Drift/2019 - Glass Harbor/04 - Signal Fires.flac", "title": "Signal Fires",
     "artist": "Lumen Drift", "album": "Glass Harbor", "year": 2019, "genres": ("Electronic",),
     "rating": 4},
    {"path": "Comps/Night Ferry/02.ogg", "title": "Harbor Lights", "artist": "Iron Arc",
     "albumartist": "Lumen Drift", "album": "Night Ferry", "year": 2024, "rating": 2},
    {"path": "Mötley Crüe/Dr. Feelgood/03 Kickstart My Heart.mp3", "title": "Kickstart My Heart",
     "artist": "Mötley Crüe", "album": "Dr. Feelgood", "year": 1989, "genres": ("Rock",)},
    {"path": "_Incoming/untitled track.wav"},
]  # fmt: skip


def found(index, text):
    """The paths of the songs a search finds, in path order."""
    where, params = search.condition(search.parse(text))
    sql = "SELECT path FROM song" + (f" WHERE {where}" if where else "") + " ORDER BY path"
    return [r[0] for r in index.read().execute(sql, params)]


def short(paths):
    return [p.split("/")[0] for p in paths]


# ---------- what the user typed ----------


def test_plain_words_must_all_match_and_the_last_is_a_prefix_while_typed():
    assert search.parse("glass harb") == Query((Term("glass"), Term("harb", prefix=True)), ())
    assert search.parse("glass harb ") == Query((Term("glass"), Term("harb")), ())
    assert search.match(search.parse("glass harb")) == '"glass" AND "harb"*'


def test_a_quoted_phrase_is_one_term_a_prefix_only_while_its_quote_is_open():
    assert search.parse('"glass harbor"') == Query((Term("glass harbor"),), ())
    assert search.parse('"glass har') == Query((Term("glass har", prefix=True),), ())
    assert search.parse('x "a b" y') == Query((Term("x"), Term("a b"), Term("y", prefix=True)))


def test_a_field_narrows_its_word_or_phrase_to_its_columns_any_case():
    q = search.parse('artist:lumen ALBUM:"glass harbor" Genre:elec')
    assert q.terms == (
        Term("lumen", ("artist", "albumartist")),
        Term("glass harbor", ("album",)),
        Term("elec", ("genre",), prefix=True),
    )
    assert search.match(q) == (
        '{artist albumartist} : "lumen" AND {album} : "glass harbor" AND {genre} : "elec"*'
    )


def test_ratings_and_years_compare_as_numbers():
    assert search.parse("rating:>=4").compares == (Compare("rating", ">=", 4),)
    assert search.parse("rating:4").compares == (Compare("rating", "=", 4),)
    assert search.parse("rating:=>3 rating:<5").compares == (
        Compare("rating", ">=", 3), Compare("rating", "<", 5)
    )  # fmt: skip
    assert search.parse("rating:>= 4").compares == (Compare("rating", ">=", 4),)
    assert search.parse("rating:≥3.5").compares == (Compare("rating", ">=", 3.5),)
    assert search.parse("year:<2000").compares == (Compare("year", "<", 2000),)
    # a year with no comparison is a word in the year, matched as typed: 201 finds 2019
    assert search.parse("year:201") == Query((Term("201", ("year",), prefix=True),), ())


def test_a_field_half_typed_or_with_no_number_asks_nothing():
    for text in ("artist:", "rating:", "rating:>=", "rating:high", "year:", "rating:>= x"):
        q = search.parse(text)
        assert q.compares == () and all(t.columns != ("rating",) for t in q.terms), text
    assert search.parse("rating:>= x").terms == (Term("x", prefix=True),)
    assert not search.parse("artist:")


def test_an_unknown_field_is_plain_text():
    assert search.parse("bpm:120").terms == (Term("bpm:120", prefix=True),)
    assert search.match(search.parse("bpm:120 ")) == '"bpm:120"'


def test_fts5s_own_syntax_is_read_as_text():
    q = search.parse('rock OR jazz NOT "x" NEAR(a b) ^start *star -minus col:x {a}')
    assert [t.text for t in q.terms] == [
        "rock", "OR", "jazz", "NOT", "x", "NEAR(a", "b)", "^start", "*star", "-minus", "col:x",
        "{a}",
    ]  # fmt: skip
    assert search.match(Query((Term('12" "mix'),))) == '"12"" ""mix"'


def test_what_has_no_letter_or_digit_asks_nothing():
    for text in ("", "   ", "-", '"', '""', "* ^ :", "--- ...", "  -  "):
        assert search.parse(text) == Query(), repr(text)
        assert search.condition(search.parse(text)) == ("", ())


def test_the_condition_joins_the_text_and_the_comparisons():
    where, params = search.condition(search.parse("lumen rating:>=4 year:<=2020"))
    assert where == (
        "song.id IN (SELECT rowid FROM song_fts WHERE song_fts MATCH ?)"
        " AND coalesce(song.rating, 0) >= ? AND song.year <= ?"
    )
    assert params == ('"lumen"', 4.0, 2020.0)


# ---------- against the index ----------


def test_words_match_any_field_case_and_accents_aside(index):
    fill(index, SONGS)
    assert short(found(index, "beyonce")) == ["Beyoncé"]
    assert short(found(index, "MOTLEY crue")) == ["Mötley Crüe"]
    assert short(found(index, "electronic")) == ["Lumen Drift"]  # a genre
    assert short(found(index, "pop")) == ["Beyoncé"]  # a second genre
    assert short(found(index, "2016")) == ["Beyoncé"]  # the year
    assert short(found(index, "untitled")) == ["_Incoming"]  # the file name
    assert short(found(index, "wav")) == ["_Incoming"]
    assert short(found(index, "harbor")) == ["Comps", "Lumen Drift"]  # a title, an album
    assert found(index, "incoming") == []  # a folder's name isn't the file's


def test_the_last_word_matches_as_its_prefix_while_typed(index):
    fill(index, SONGS)
    assert short(found(index, "beyon")) == ["Beyoncé"]
    assert found(index, "beyon ") == []
    assert short(found(index, "kickstart my he")) == ["Mötley Crüe"]


def test_artist_reads_the_album_artist_too_and_album_only_the_album(index):
    fill(index, SONGS)
    assert short(found(index, "artist:lumen")) == ["Comps", "Lumen Drift"]
    assert short(found(index, "artist:iron")) == ["Comps"]
    assert short(found(index, "album:harbor")) == ["Lumen Drift"]
    assert short(found(index, 'album:"night ferry"')) == ["Comps"]
    assert found(index, "genre:lumen") == []


def test_ratings_compare_and_a_song_not_rated_is_zero(index):
    fill(index, SONGS)
    assert short(found(index, "rating:>=4")) == ["Beyoncé", "Lumen Drift"]
    assert short(found(index, "rating:0")) == ["Mötley Crüe", "_Incoming"]
    assert short(found(index, "rating:<3 harbor")) == ["Comps"]
    assert short(found(index, "year:<2000")) == ["Mötley Crüe"]
    assert short(found(index, "year:201")) == ["Beyoncé", "Lumen Drift"]
    assert found(index, "year:<2000 beyonce") == []


def test_operators_and_odd_characters_find_their_words_and_never_fail(index):
    fill(index, SONGS)
    assert short(found(index, "dr. feelgood")) == ["Mötley Crüe"]
    assert short(found(index, "harbor OR")) == []  # OR is a word: no song has it
    assert short(found(index, "-")) == short(found(index, "")) == [
        "Beyoncé", "Comps", "Lumen Drift", "Mötley Crüe", "_Incoming"
    ]  # fmt: skip
    assert found(index, '"') == found(index, "")
    assert short(found(index, "r&b")) == ["Beyoncé"]


# what users type, in pieces more likely to meet than characters drawn at random
PIECES = st.sampled_from(['"', "artist:", "Album:", "rating:", "year:", "bpm:", ">=", "<", "4",
                          "2019", " ", "-", "*", "^", ":", "(", ")", "{", "}", "NEAR(", "OR",
                          "AND", "NOT", "a", "é", "\u0301", "\x00", "'", "\\"])  # fmt: skip


@given(st.one_of(st.text(max_size=40), st.lists(PIECES, max_size=12).map("".join)))
@example('"')
@example('artist:"')
@example("rating:>=")
@example("NEAR(")
@example("a\x00b")
@example("́")  # a combining accent alone
@example("{title}: x")
def test_no_input_makes_a_query_that_fails(text):
    """A property (testing.md, "Properties"): whatever is typed, the query runs."""
    where, params = search.condition(search.parse(text))
    one_song().execute("SELECT COUNT(*) FROM song" + (f" WHERE {where}" if where else ""), params)


@functools.cache
def one_song():
    """An index in memory with one song, made once for the property's examples."""
    c = sqlite3.connect(":memory:", check_same_thread=False)
    db.migrate(c)
    c.execute("INSERT INTO song (id, path, size, mtime_ns, title) VALUES (1, 'a é.mp3', 1, 1, 'a')")
    c.execute("INSERT INTO song_fts (rowid, title, filename) VALUES (1, 'a', 'a é.mp3')")
    return c


# ---------- the index kept ----------


def fts(index):
    return sorted(index.read().execute("SELECT rowid, title, genre, filename FROM song_fts"))


def test_the_scan_keeps_song_fts_in_step_with_the_songs(index):
    fill(index, SONGS[:2])
    rows = fts(index)
    assert [(r[1], r[2], r[3]) for r in rows] == [
        ("Pray You Catch Me", "R&B Pop", "01 Pray You Catch Me.flac"),
        ("Signal Fires", "Electronic", "04 - Signal Fires.flac"),
    ]
    ids = dict(index.read().execute("SELECT path, id FROM song"))
    assert [r[0] for r in rows] == sorted(ids.values())
    fill(index, [{**SONGS[1], "title": "Signal Fire", "genres": ("Ambient",)}])  # retagged
    assert [r[1:3] for r in fts(index)][1] == ("Signal Fire", "Ambient")
    assert short(found(index, "ambient")) == ["Lumen Drift"] and found(index, "electronic") == []

    def remove(c):
        search.forget(c, [SONGS[0]["path"]])
        c.execute("DELETE FROM song WHERE path = ?", (SONGS[0]["path"],))

    index.write(remove).result()
    assert [r[1] for r in fts(index)] == ["Signal Fire"]


def test_a_scan_removing_a_file_removes_its_words(index, tmp_path):
    fill(index, SONGS[:1])
    root = tmp_path / "empty"
    root.mkdir()
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(1) as pool:
        scanner.scan(str(root), index, pool)
    assert fts(index) == [] and found(index, "beyonce") == []


def test_an_index_of_slice_3_1_gains_song_fts_filled_from_its_rows(tmp_path):
    """Version 3 (A2.5): the songs are indexed from the rows there, not read again."""
    c = db.connect(str(tmp_path / "musikata.db"))
    for step in db.MIGRATIONS[:2]:
        step(c)
    c.execute("PRAGMA user_version = 2")
    c.execute(
        "INSERT INTO song (id, path, size, mtime_ns, title, artist, year)"
        " VALUES (7, 'A/Beyoncé - Halo.mp3', 10, 5, 'Halo', 'Beyoncé', 2008)"
    )
    c.execute("INSERT INTO song_genre VALUES (7, 0, 'Pop'), (7, 1, 'Soul')")
    assert db.migrate(c) == 3
    assert c.execute("SELECT mtime_ns FROM song").fetchone()[0] == 5  # not to be read again
    assert c.execute("SELECT rowid, genre, year, filename FROM song_fts").fetchall() == [
        (7, "Pop Soul", 2008, "Beyoncé - Halo.mp3")
    ]
    where, params = search.condition(search.parse("beyonce soul"))
    assert c.execute(f"SELECT id FROM song WHERE {where}", params).fetchall() == [(7,)]
    c.close()
