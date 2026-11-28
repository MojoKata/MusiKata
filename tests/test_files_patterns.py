"""Path patterns (src/musikata_core/patterns.py; R3, A3.3): the pattern language and its engine,
the presets and detection, filling and correcting with the tidying steps, and tags match path
(R3.9); and the shapes paths take (docs/process/testing.md, "Shapes": `patterns`).

Why: Infer from path rewrites the tags of a folder, or a library, at once from what the paths say.
A pattern that reads a hyphen in a title as a separator, a preset tried in the wrong order, a
token that swallows a folder, or a tidying step that rewrites a name the user spelled with care,
writes wrong tags into every file it fits; and R3.9's state, kept for every song, would flag a
whole library that is fine, or pass over one that isn't."""

import unicodedata

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from musikata_core import patterns
from musikata_core.patterns import (
    BARE,
    DOESNT_FIT,
    FIX,
    MATCH,
    PRESETS,
    Difference,
    Options,
    parse,
)
from musikata_core.tags import Tags
from musikata_core.tags.tools import Song

LD = "Lumen Drift"


def read(pattern, path, **kw):
    return patterns.read(parse(pattern), path, **kw)


# ---------- the language (R3.2) ----------


def test_a_pattern_is_its_tokens_and_the_text_between_with_slashes_between_folders():
    p = parse("{albumartist}/{year} - {album}/{track} - {title}")
    assert p.problem == "" and p.regex is not None
    assert p.tokens == ("albumartist", "year", "album", "track", "title")
    assert p.fields == ("albumartist", "year", "album", "track", "title")
    assert p.depth == 3
    assert parse("{artist} - {title}").depth == 1
    assert parse("/{artist}/{title}/").depth == 2  # slashes at its ends are no folders
    assert parse("{ Artist }/{TITLE}").tokens == ("artist", "title")  # spaces and case aside
    # {*} fills nothing, and a token twice is one field
    assert parse("{*}/{artist}/{artist} - {title}").tokens == ("artist", "title")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("", "Type a pattern, such as {artist} - {title}"),
        ("  /  ", "Type a pattern, such as {artist} - {title}"),
        ("{artist} - {title", "A brace isn't closed"),
        ("artist} - {title}", "A brace isn't closed"),
        ("{artist} - {name}", "{name} isn't a token"),
        ("{*} - {*}", "Put at least one token in it, such as {title}"),
        ("just text", "Put at least one token in it, such as {title}"),
    ],
)
def test_a_pattern_that_cant_be_used_says_why_and_fits_nothing(text, problem):
    p = parse(text)
    assert p.problem == problem and p.regex is None
    assert patterns.match(p, "Lumen Drift - Signal Fires.flac") is None


@pytest.mark.parametrize(
    "token",
    ["artist", "albumartist", "album", "year", "disc", "track", "title", "genre"],
)
def test_each_token_fills_its_field(token):
    """R3.2's table: each token fills its field; {*} fills nothing."""
    value = {"year": "2019", "disc": "2", "track": "04"}.get(token, "Glass Harbor")
    got = read(f"{{{token}}}/{{*}}", f"{value}/x.flac")
    field = patterns.TOKENS[token]
    expected = {"year": 2019, "disc": 2, "track": 4, "genres": ("Glass Harbor",)}.get(
        field, "Glass Harbor")  # fmt: skip
    assert got == {field: expected}
    assert read("{*}/{title}", "anything at all/Signal Fires.flac") == {"title": "Signal Fires"}


def test_year_is_four_digits_disc_and_track_digits_with_leading_zeros_dropped():
    assert read("{year} - {album}", "2019 - Glass Harbor.flac") == {
        "year": 2019,
        "album": "Glass Harbor",
    }
    assert read("{year} - {album}", "19 - Glass Harbor.flac") is None
    assert read("{year}{album}", "20191 Glass.flac") == {"year": 2019, "album": "1 Glass"}
    assert read("{track} - {title}", "Four - Signal Fires.flac") is None
    assert read("{disc}-{track} - {title}", "02-007 - Bore.flac") == {
        "disc": 2,
        "track": 7,
        "title": "Bore",
    }
    assert read("{track} - {title}", "00 - Hidden.flac") == {"title": "Hidden"}  # no track 0


def test_the_text_between_tokens_matches_exactly_but_runs_of_spaces_and_the_three_dashes():
    """R3.2.1: runs of spaces match any run of spaces; ` - `, ` – ` and `_-_` one another."""
    for name in ("04 - Signal Fires", "04  -   Signal Fires", "04 – Signal Fires",
                 "04_-_Signal Fires", "04 –  Signal Fires"):  # fmt: skip
        assert read("{track} - {title}", f"{name}.flac", underscores=False) == {
            "track": 4, "title": "Signal Fires"}  # fmt: skip
    assert read("{track} – {title}", "04_-_Signal.flac", underscores=False)["title"] == "Signal"
    assert read("{track} - {title}", "04-Signal Fires.flac") is None  # no spaces: not the same
    assert read("{track} - {title}", "04 — Signal Fires.flac") is None  # an em dash isn't one
    assert read("{track}. {title}", "04. Signal.flac") == {"track": 4, "title": "Signal"}
    assert read("{track}. {title}", "04x Signal.flac") is None  # a mark is matched as itself
    assert read("[{track}] {title}", "[04] Signal.flac") == {"track": 4, "title": "Signal"}
    assert read("{album} ({year})", "Glass Harbor (2019).flac") == {"album": "Glass Harbor",
                                                                    "year": 2019}  # fmt: skip


def test_a_token_matches_as_little_as_it_can_while_the_rest_still_matches():
    """R3.2.2: R3's own example, and an artist and a title both holding the separator."""
    assert read("{track} - {title}", "04 - Signal Fires - Live.flac") == {
        "track": 4, "title": "Signal Fires - Live"}  # fmt: skip
    assert read("{artist} - {title}", "Jay - Z - Song - Remix.mp3") == {
        "artist": "Jay", "title": "Z - Song - Remix"}  # fmt: skip


def test_the_extension_is_never_part_of_a_pattern_and_slash_is_the_separator_everywhere():
    assert read("{artist} - {title}", "Lumen Drift - Signal Fires.flac")["title"] == "Signal Fires"
    assert read("{artist} - {title}", "Lumen Drift - Signal Fires")["title"] == "Signal Fires"
    assert read("{title}", "Mr. Brown Goes On.mp3") == {"title": "Mr. Brown Goes On"}
    assert read("{title}", "Vol. 2 Part one.mp3") == {"title": "Vol. 2 Part one"}  # not a kind
    assert read("{albumartist}/{album}/{title}", "Lumen Drift\\Glass Harbor\\Tidewater.flac") == {
        "albumartist": LD, "album": "Glass Harbor", "title": "Tidewater"}  # fmt: skip


def test_a_pattern_reads_the_last_parts_of_the_path_and_a_token_never_takes_a_slash():
    """A3.3: anchored over as many of the path's last parts as it describes, so an album's folder
    is read however deep it lies; a token holds no `/`."""
    p = "{albumartist}/{album}/{track} - {title}"
    deep = "Electronic/Favourites/Lumen Drift/Tide Tables/04 - Moonpull.flac"
    assert read(p, deep) == {"albumartist": LD, "album": "Tide Tables", "track": 4,
                             "title": "Moonpull"}  # fmt: skip
    assert read(p, "Tide Tables/04 - Moonpull.flac") is None  # too shallow
    assert read("{artist} - {title}", "Lumen Drift/x - y/Tidewater.flac") is None
    assert read("{*}/{title}", "Tidewater.flac") is None


def test_names_as_macos_writes_them_and_underscores_read_as_spaces():
    nfd = "Beyoncé/Café - Noçe.flac"
    assert read("{albumartist}/{artist} - {title}", nfd) == {
        "albumartist": "Beyoncé", "artist": "Café", "title": "Noçe"}  # fmt: skip
    assert read("{track} - {title}", "04_-_Signal_Fires.flac") == {
        "track": 4,
        "title": "Signal Fires",
    }
    assert read("{track} {title}", "04_Signal_Fires.flac") == {"track": 4, "title": "Signal Fires"}
    off = read("{track} - {title}", "04_-_Signal_Fires.flac", underscores=False)
    assert off == {"track": 4, "title": "Signal_Fires"}
    assert read("{track}_{title}", "04_Signal.flac") == {"track": 4, "title": "Signal"}


def test_values_are_trimmed_and_their_spaces_made_single():
    assert read("{artist} - {title}", "Lumen  Drift  -  Signal   Fires .flac") == {
        "artist": LD, "title": "Signal Fires"}  # fmt: skip
    assert read("{*} {title}", "x  .flac") == {}  # it fits, but leaves the title nothing


# ---------- the shapes paths take ----------

PATHS = st.lists(
    st.text(st.characters(blacklist_categories=("Cs",)), max_size=30), min_size=0, max_size=6
).map("/".join)
PATTERN_TEXT = st.lists(
    st.one_of(
        st.sampled_from(["{" + t + "}" for t in [*patterns.TOKENS, "*"]]),
        st.sampled_from([" - ", "/", " ", "_-_", " – ", "(", ")", "{", "}", "{x}", "."]),
        st.text(max_size=5),
    ),
    max_size=8,
).map("".join)


@given(PATTERN_TEXT, PATHS)
@example("{track}{title}", "04Signal.flac")
@example("{year}/{year}", "2019/2020.mp3")
def test_any_pattern_on_any_path_reads_or_doesnt_and_never_fails(text, path):
    """R3: whatever is typed and whatever the path, a pattern either reads its fields or doesn't
    fit; it never fails."""
    p = parse(text)
    got = patterns.read(p, path)
    assert got is None or set(got) <= set(patterns.TOKENS.values())
    assert patterns.folder_year(path) is None or 1000 <= patterns.folder_year(path) < 3000


@pytest.mark.parametrize(
    ("path", "found"),
    [
        ("Lumen Drift/2019 - Glass Harbor/04 - Signal Fires.flac", {"year": 2019}),  # 1
        ("Lumen Drift/Glass Harbor (2019)/04 - Signal Fires.flac", {"year": 2019}),  # 2
        ("Lumen Drift/Glass Harbor/1-04 - Signal Fires.flac", {"disc": 1}),  # 3
        ("Various/Night Ferry/04 - Kestrel Union - Low Orbit.flac", {"artist": "Kestrel Union"}),
        ("Lumen Drift/Glass Harbor/04 - Signal Fires.flac", {"track": 4}),  # 5
        ("Lumen Drift/Glass Harbor/04 Signal Fires.flac", {"title": "Signal Fires"}),  # 6
        ("Lumen Drift - Signal Fires.flac", {"artist": LD}),  # 7, loose
        ("Lumen Drift/Disc 1/04 - Signal Fires.flac", {"album": "Disc 1"}),  # a disc's folder
        ("A Very Long Artist Name " * 6 + "/X/04 - Y.flac", {"track": 4}),  # past a platform's
    ],
)
def test_each_layout_is_detected_as_its_preset_reads_it(path, found):
    """R3.3's presets, in its order, each detected on a path of its layout (R3.4)."""
    chosen = patterns.detected(patterns.detect(patterns.patterns_of(), [path]))
    assert chosen is not None
    got = patterns.read(chosen, path)
    assert all(got[k] == v for k, v in found.items())


def test_the_presets_are_r3_3s_in_its_order_and_the_users_are_tried_first():
    assert PRESETS[0] == "{albumartist}/{year} - {album}/{track} - {title}"
    assert PRESETS[-1] == "{artist} - {title}"
    assert len(PRESETS) == 7
    tried = patterns.patterns_of(["{artist}/{album}/{track} - {title}", "", "{bad}",
                                  "{artist}/{album}/{track} - {title}", PRESETS[2]])  # fmt: skip
    # each once, in the order given; those that can't be used left out
    assert [p.text for p in tried] == [
        "{artist}/{album}/{track} - {title}",
        PRESETS[2],
        *PRESETS[:2],
        *PRESETS[3:],
    ]


def test_detection_chooses_the_pattern_that_fits_most_a_tie_going_to_more_tokens():
    """R3.4: "04 - Signal Fires" fits `{track} - {title}` and `{track} {title}` (title "- Signal
    Fires"); one with " - Live" fits preset 4 too, but not the folder's others."""
    folder = [f"Lumen Drift/Tide Tables/0{n} - T{n}.flac" for n in range(1, 4)]
    folder.append("Lumen Drift/Tide Tables/04 - Ebb - Live.flac")
    fits = patterns.detect(patterns.patterns_of(), folder)
    assert fits[0].pattern.text == PRESETS[4] and fits[0].fits == 4
    assert {f.pattern.text: f.fits for f in fits}[PRESETS[3]] == 1
    assert {f.pattern.text: f.fits for f in fits}[PRESETS[5]] == 4  # a tie: the one tried first
    # a tie goes to the more specific pattern
    dated = ["Lumen Drift/2019 - Glass Harbor/01 - Tidewater.flac"]
    fits = patterns.detect(patterns.patterns_of(), dated)
    assert fits[0].pattern.text == PRESETS[0]
    assert patterns.detected(patterns.detect(patterns.patterns_of(), ["x.flac"])) is None
    assert patterns.detected([]) is None


@pytest.mark.parametrize(
    ("path", "year"),
    [
        ("Lumen Drift/2019 - Glass Harbor/04.flac", 2019),
        ("Lumen Drift/Glass Harbor (2019)/04.flac", 2019),
        ("Lumen Drift/Glass Harbor [2019]/04.flac", 2019),
        ("Lumen Drift/Glass Harbor - 2019/04.flac", 2019),
        ("Lumen Drift/2019_Glass Harbor/04.flac", 2019),
        ("Lumen Drift/Glass Harbor (2019)/Disc 2/04.flac", 2019),
        ("Lumen Drift/Glass Harbor (2019)/CD1/04.flac", 2019),
        ("Lumen Drift/Glass Harbor/04.flac", None),
        ("Lumen Drift/Symphony 1812 Live/04.flac", None),
        ("Lumen Drift/0999 - Early/04.flac", None),
        ("Lumen Drift/2019/04.flac", None),  # a year alone may be a folder of years
        ("04.flac", None),
    ],
)
def test_year_from_folder_reads_the_year_the_albums_folder_names(path, year):
    """R3.6.2: `2019 - Glass Harbor` or `Glass Harbor (2019)`, the disc's folder passed by."""
    assert patterns.folder_year(path) == year


# ---------- filling and correcting (R3.5, R3.6) ----------


def given_(pattern, path, **kw):
    return patterns.given(parse(pattern), path, Options(**kw))


def test_correct_tags_that_differ_lets_the_path_win_and_only_fill_keeps_what_has_a_value():
    """R3.5, the default and the other mode."""
    values = given_(
        "{albumartist}/{album}/{track} - {title}", "Lumen Drift/Tide Tables/04 - Moonpull.flac"
    )
    old = Tags(title="Moon Pull", album=None, albumartist="Someone", track=4, year=2022)
    new = patterns.infer(old, values)
    assert (new.title, new.album, new.albumartist, new.track, new.year) == (
        "Moonpull", "Tide Tables", LD, 4, 2022)  # fmt: skip
    filled = patterns.infer(old, values, Options(fill_only=True))
    assert (filled.title, filled.album, filled.albumartist) == ("Moon Pull", "Tide Tables",
                                                                 "Someone")  # fmt: skip
    assert patterns.infer(new, values) is new  # nothing to change: the same tags


def test_tidy_case_tidies_what_the_path_says_and_keeps_a_tags_mixed_case():
    """R3.6.1: a value all in lower or upper case becomes Title Case; a tag that already mixes
    case and differs only in case stays; one spelled as the path spells it, in lower case, is
    tidied too (L05: "ebb & flow" is Title case differs)."""
    values = given_("{artist} - {title}", "lumen drift - ebb & flow.mp3")
    assert values == {"artist": "lumen drift", "title": "ebb & flow"}
    t = patterns.infer(Tags(artist="lumen drift", title="ebb & flow"), values)
    assert (t.artist, t.title) == (LD, "Ebb & Flow")
    off = patterns.infer(Tags(), values, Options(tidy_case=False))
    assert (off.artist, off.title) == ("lumen drift", "ebb & flow")
    kept = patterns.infer(Tags(artist="McCartney", title="Ebb & Flow"),
                          given_("{artist} - {title}", "MCCARTNEY - EBB & FLOW.mp3"))  # fmt: skip
    assert (kept.artist, kept.title) == ("McCartney", "Ebb & Flow")
    assert (
        patterns.infer(Tags(artist="AC/DC LIVE"), {"artist": "AC/DC LIVE"}).artist == "AC/DC Live"
    )


def test_a_tag_spelled_with_what_a_file_name_cant_hold_is_kept():
    """A path can't hold `/`, `?`, `:` and the rest: the tag that does, and is otherwise the
    path's text, is kept as the user spelled it."""
    for tag, name in (("AC/DC", "AC_DC"), ("What?", "What"), ("Live: Paris", "Live_ Paris"),
                      ("R.E.M.", "R.E.M"), ("Who\\Me", "Who Me")):  # fmt: skip
        values = given_("{artist} - {title}", f"{name} - x.mp3")
        assert patterns.infer(Tags(artist=tag), values).artist == tag
    tidied = patterns.infer(Tags(artist="ACDC"), given_("{artist} - {title}", "AC_DC - x.mp3"))
    assert tidied.artist == "Ac Dc"  # a tag the path does spell is the path's, tidied


def test_year_from_folder_fills_year_without_a_year_token_and_drops_the_full_date():
    values = given_("{albumartist}/{album}/{track} - {title}",
                    "Lumen Drift/Glass Harbor (2019)/04 - Signal Fires.flac")  # fmt: skip
    assert values["year"] == 2019 and values["album"] == "Glass Harbor (2019)"
    t = patterns.infer(Tags(year=2018, date="2018-05-01"), values)
    assert (t.year, t.date) == (2019, None)
    kept = Tags(year=2019, date="2019-05-01")
    assert patterns.infer(kept, values).date == "2019-05-01"  # the same year: its date stays
    off = given_(
        "{albumartist}/{album}/{track} - {title}",
        "Lumen Drift/Glass Harbor (2019)/04 - Signal Fires.flac",
        year_from_folder=False,
    )
    assert "year" not in off
    # the pattern's own year wins over the folder's
    assert (
        given_("{albumartist}/{year} - {album}/{title}", "A/2019 - B (2020)/x.mp3")["year"] == 2019
    )


def test_a_genre_is_set_as_one_genre_and_kept_when_the_song_has_it_among_its_own():
    values = given_("{genre}/{artist} - {title}", "electronic/Lumen Drift - Ebb.flac")
    assert values["genres"] == ("electronic",)
    assert patterns.infer(Tags(), values).genres == ("Electronic",)
    assert patterns.infer(Tags(genres=("Ambient", "Electronic")), values).genres == (
        "Ambient", "Electronic")  # fmt: skip
    assert patterns.infer(Tags(genres=("Ambient",)), values).genres == ("Electronic",)
    assert patterns.infer(Tags(genres=("Ambient",)), values, Options(fill_only=True)).genres == (
        "Ambient",)  # fmt: skip
    assert patterns.infer(Tags(), {"genres": ()}).genres == ()


def song(path, **tags):
    return Song("/music/" + path, Tags(**tags))


def test_the_plan_lists_the_files_that_fit_then_those_that_dont_noted_with_its_columns():
    """R3.4, R3.7: the columns the pattern fills, Year when a folder gives it; the files it
    doesn't fit last, unchanged, "Doesn't fit the pattern"."""
    paths = ["LD/2019 - Glass Harbor/stray.flac", "LD/2019 - Glass Harbor/01 - Tidewater.flac",
             "LD/2019 - Glass Harbor/02 - Glass Harbor.flac"]  # fmt: skip
    songs = [song(p) for p in paths]
    planned = patterns.plan(songs, paths, parse("{albumartist}/{album}/{track} - {title}"))
    assert planned.columns == ("albumartist", "album", "track", "title", "year")
    assert [s.path for s in planned.songs] == ["/music/" + p for p in paths[1:] + paths[:1]]
    assert [planned.note(i) for i in range(3)] == ["", "", DOESNT_FIT]
    assert planned.new[0].album == "2019 - Glass Harbor" and planned.new[0].year == 2019
    assert planned.new[2] is songs[0].tags
    assert planned.changed(0) == ("albumartist", "album", "track", "title", "year")
    jobs = planned.jobs({0, 2})
    assert [j.path for j in jobs] == [songs[1].path]


def test_track_total_is_filled_when_every_track_of_a_folder_is_there():
    """R3.6.4: a folder's songs numbered 1 to n, n the files it holds; per disc; not when some of
    its files aren't among those given."""
    paths = [f"LD/TT/0{n} - T{n}.flac" for n in (1, 2, 3)]
    songs = [song(p) for p in paths]
    pattern = parse("{albumartist}/{album}/{track} - {title}")
    on = Options(track_total=True)
    planned = patterns.plan(songs, paths, pattern, on)
    assert "tracktotal" in planned.columns and [t.tracktotal for t in planned.new] == [3, 3, 3]
    assert [t.tracktotal for t in patterns.plan(songs, paths, pattern, on,
                                                {"LD/TT": 9}).new] == [None] * 3  # fmt: skip
    assert "tracktotal" not in patterns.plan(songs, paths, pattern).columns
    gap = [song(p) for p in paths[:1] + paths[2:]]
    assert [t.tracktotal for t in patterns.plan(gap, paths[:1] + paths[2:], pattern, on).new] == [
        None, None]  # fmt: skip
    discs = ["LD/TT/1-01 - A.flac", "LD/TT/1-02 - B.flac", "LD/TT/2-01 - C.flac"]
    planned = patterns.plan(
        [song(p) for p in discs], discs, parse("{albumartist}/{album}/{disc}-{track} - {title}"), on
    )
    assert [t.tracktotal for t in planned.new] == [2, 2, 1]
    had = [song(p, tracktotal=10) for p in paths]
    assert [t.tracktotal for t in patterns.plan(had, paths, pattern,
                                                Options(track_total=True, fill_only=True)).new] \
        == [10, 10, 10]  # fmt: skip
    assert patterns.track_totals([]) == {}


def test_a_pattern_that_cant_be_used_plans_every_file_unchanged():
    paths = ["a/b.flac"]
    planned = patterns.plan([song(paths[0])], paths, parse("{oops}"))
    assert planned.note(0) == DOESNT_FIT and planned.changed(0) == ()


# ---------- tags match path (R3.9) ----------


TIDE = "Lumen Drift/Tide Tables"


def tide(n, title, **kw):
    tags = {"title": title, "albumartist": LD, "album": "Tide Tables", "track": n, **kw}
    return (f"{TIDE}/0{n} - {title}.flac", Tags(**tags))


def test_each_files_tags_match_its_path_can_be_fixed_or_it_has_none():
    """R3.9: MATCH, FIX with how its tags differ (missing, only in case, otherwise), BARE for a
    file with no tags; none when no pattern fits a file with tags."""
    songs = [
        tide(1, "Neap Tide"),
        tide(2, "Spring Tide", albumartist="lumen drift"),
        tide(3, "Slack Water", album=None),
        (f"{TIDE}/04 - Moonpull.flac", tide(4, "Moon Pull")[1]),
        (f"{TIDE}/05 - Ebb.flac", Tags()),
        (f"{TIDE}/stray.flac", Tags(title="Stray")),
    ]
    got = patterns.states(songs, patterns.patterns_of())
    assert got == [
        (MATCH, ()),
        (FIX, (Difference("albumartist", "case", LD),)),
        (FIX, (Difference("album", "missing", "Tide Tables"),)),
        (FIX, (Difference("title", "differs", "Moonpull"),)),
        (BARE, (Difference("albumartist", "missing", LD), Difference("album", "missing",
                "Tide Tables"), Difference("track", "missing", "5"),
                Difference("title", "missing", "Ebb"))),
        (None, ()),
    ]  # fmt: skip
    assert got[1][1][0].old == "lumen drift" and got[2][1][0].old == ""  # the tag's own value
    assert patterns.states([], patterns.patterns_of()) == []
    assert patterns.states([("x.flac", Tags())], patterns.patterns_of()) == [(BARE, ())]


def test_the_users_own_pattern_detected_for_a_folder_reads_its_artist():
    """R3.3 and R3.9: a pattern of the user's own, tried first, wins a tie with a preset."""
    songs = [(f"{TIDE}/04 - Moonpull.flac", Tags(title="Moonpull", artist="lumen drift",
                                                 album="Tide Tables", track=4))]  # fmt: skip
    user = patterns.patterns_of(["{artist}/{album}/{track} - {title}"])
    assert patterns.states(songs, user) == [(FIX, (Difference("artist", "case", LD),))]


def test_a_year_the_folder_gives_is_part_of_the_match():
    folder = "Lumen Drift/2022 - Tide Tables"
    songs = [(f"{folder}/0{n} - T{n}.flac", Tags(albumartist=LD, album="Tide Tables", track=n,
                                               title=f"T{n}", year=year))
             for n, year in ((1, 2022), (2, None), (3, 2021))]  # fmt: skip
    got = patterns.states(songs, patterns.patterns_of())
    assert [s for s, _ in got] == [MATCH, FIX, FIX]
    assert got[1][1] == (Difference("year", "missing", "2022"),)
    assert got[2][1] == (Difference("year", "differs", "2022"),)
    assert patterns.has_tags(Tags(genres=("Rock",))) and not patterns.has_tags(Tags(rating=4))


def test_a_shorter_name_the_path_gives_of_the_album_or_an_artist_agrees():
    """R3.9: the tag starts with the path's text, before a space, or is it with a part in
    brackets; compared as the rest of R3.9 compares (spaces, the marks a name can't hold, case
    when the tag has mixed case)."""
    ferry = "Night Ferry (Original Soundtrack)"
    assert patterns.short_forms(ferry) == ["Night", "Night Ferry", "Night Ferry (Original"]
    assert "Glass Harbor Live" in patterns.short_forms("Glass Harbor (Deluxe) Live")
    for tag, raw in (
        (ferry, "Night Ferry"),
        ("Glass Harbor Remixed", "Glass Harbor"),
        ("Glass Harbor [Deluxe]", "Glass Harbor"),
        ("Glass Harbor: Remixed", "Glass Harbor"),
        ("Glass Harbor, Vol. 2", "Glass Harbor"),
        ("Glass Harbor (Deluxe) Live", "Glass Harbor Live"),
        ("Glass Harbor(Deluxe)", "Glass Harbor"),
        ("Glass Harbor Remixed", "glass  harbor"),  # tidied, its spaces single
        ("Glass Harbor Remixed", "GLASS HARBOR"),
        ("AC/DC Live", "AC DC"),  # what a file's name can't hold
    ):
        assert patterns.shortens(tag, raw), (tag, raw)
    for tag, raw in (
        ("Glassworks", "Glass"),  # not before a space
        ("Glass Harbor", "Glass Harbor Remixed"),  # the path's the longer
        ("Harbor Lights", "Glass Harbor"),
        ("glass harbor remixed", "Glass Harbor"),  # all lower case, tidied as Infer would
        ("Night Ferry (Original Soundtrack)", "Night Ferry Soundtrack"),
        ("Glass Harbor", "Glass Harbor"),  # the same isn't shorter: infer judges it
    ):
        assert not patterns.shortens(tag, raw), (tag, raw)


def test_the_album_and_its_artists_agree_when_shortened_but_the_title_year_and_track_dont():
    """R3.9: only the album, the album artist and the artist; a file's name that shortens the
    title, or a year, track or disc that differs, still differs."""
    folder = "Lumen Drift/Glass Harbor"
    songs = [
        (f"{folder}/01 - Atlas.flac", Tags(albumartist="Lumen Drift feat. Ora", album="Glass Harbor"
                                           " Remixed", track=1, title="Atlas")),
        (f"{folder}/02 - Signal.flac", Tags(albumartist=LD, album="Glass Harbor", track=2,
                                            title="Signal Fires")),
        (f"{folder}/03 - Ebb.flac", Tags(albumartist=LD, album="Glass Harbor", track=31,
                                         title="Ebb")),
    ]  # fmt: skip
    got = patterns.states(songs, patterns.patterns_of())
    assert got == [
        (MATCH, ()),
        (FIX, (Difference("title", "differs", "Signal"),)),
        (FIX, (Difference("track", "differs", "3"),)),
    ]
    artist = [("A/Kindling/01 - Embers.flac", Tags(artist="Mara Okafor & Band", album="Kindling",
                                                  track=1, title="Embers"))]  # fmt: skip
    user = patterns.patterns_of(["{artist}/{album}/{track} - {title}"])
    assert patterns.states([(p.replace("A/", "Mara Okafor/"), t) for p, t in artist], user) == [
        (MATCH, ())
    ]


def test_a_folder_that_groups_albums_is_one_with_two_or_more_none_of_whose_songs_carry_its_name():
    """R3.9: two or more album folders beneath it, and songs beneath it tagged with an album
    artist or artist, none of them its name, as R3.9 compares names, case aside; songs with
    neither tag are no evidence, so a folder of untagged albums is an artist's."""
    various = ["Various Artists", "Arc Drift", None, "Cinder Fern"]
    assert patterns.grouping("Soundtracks", 5, various)
    assert patterns.grouping("Remixes", 2, ["Lumen Drift"])
    assert not patterns.grouping("Soundtracks", 1, various)  # one album: an artist's
    assert not patterns.grouping("Lumen Drift", 4, ["Lumen Drift", None])
    assert not patterns.grouping("Lumen Drift", 2, [None, "lumen drift"])  # as the artist
    assert not patterns.grouping("Lumen_Drift", 2, ["Lumen Drift feat. Ora"])  # a shorter name
    assert not patterns.grouping("Rock", 3, [None, None, ""])  # untagged: still an artist's
    assert patterns.grouping("Rock", 3, [None, "Ada Kerr", None])
    assert patterns.carries("AC/DC", "AC_DC") and not patterns.carries("Lumen", "Lumen Drift")
    assert not patterns.carries("Lumen Drift", "")


def test_a_folder_that_groups_albums_gives_no_album_artist_or_artist_but_the_rest_is_judged():
    """R3.9: a pattern reading such a folder as the album artist (or artist) doesn't judge that
    field for the songs beneath it; the album from the album's folder, the track and title from
    the file's name still are."""

    def ost(name, n, title, **kw):
        tags = {"album": f"{name} (Original Soundtrack)", "track": n, "title": title, **kw}
        return (f"Soundtracks/{name}/0{n} - {title}.ogg", Tags(**tags))

    songs = [
        ost("Night Ferry", 1, "Tide Lantern", artist="Cinder Fern"),
        ost("Night Ferry", 2, "North Hollow", albumartist="Various Artists"),
        ost("Night Ferry", 3, "Lantern Iron", album=None),
        ost("Night Ferry", 4, "Arc Salt", track=9),
    ]
    tried = patterns.patterns_of()
    got = patterns.states(songs, tried, {"Soundtracks"})
    assert got == [
        (MATCH, ()),
        (MATCH, ()),
        (FIX, (Difference("album", "missing", "Night Ferry"),)),
        (FIX, (Difference("track", "differs", "4"),)),
    ]
    assert patterns.states(songs[:2], tried) == [
        (FIX, (Difference("albumartist", "missing", "Soundtracks"),)),
        (FIX, (Difference("albumartist", "differs", "Soundtracks"),)),
    ]  # judged when it isn't one
    user = patterns.patterns_of(["{artist}/{album}/{track} - {title}"])
    assert patterns.states(songs[:1], user, {"Soundtracks"}) == [(MATCH, ())]


def test_where_a_patterns_token_sits_and_the_folder_it_reads():
    preset = parse(PRESETS[0])
    assert [preset.place(t) for t in ("albumartist", "year", "album", "title", "genre")] == [
        0, 1, 1, 2, None
    ]  # fmt: skip
    path = "Rock/Lumen Drift/2019 - Glass Harbor/01 - Tidewater.flac"
    assert patterns.token_folder(preset, path, "albumartist") == "Rock/Lumen Drift"
    assert patterns.token_folder(preset, path, "album") == "Rock/Lumen Drift/2019 - Glass Harbor"
    assert patterns.token_folder(preset, path, "title") is None  # in the file's name
    assert patterns.token_folder(preset, path, "artist") is None  # not in the pattern
    loose = parse("{artist} - {title}")
    assert patterns.token_folder(loose, "Lumen Drift - Ebb.mp3", "artist") is None
    assert patterns.token_folder(preset, "A\\B\\01 - T.flac", "albumartist") == "A"


TAGS = st.builds(
    Tags,
    title=st.none() | st.text(max_size=12),
    artist=st.none() | st.text(max_size=12),
    album=st.none() | st.text(max_size=12),
    track=st.none() | st.integers(0, 99),
    year=st.none() | st.integers(1000, 2999),
    genres=st.lists(st.text(min_size=1, max_size=6), max_size=2).map(tuple),
)


@given(st.lists(st.tuples(PATHS, TAGS), max_size=5), st.lists(PATTERN_TEXT, max_size=2))
def test_any_folder_of_any_songs_has_a_state_for_each_and_never_fails(songs, user):
    """R3.9 over anything: a state for each song, and a song that MATCHes is one Infer from path
    wouldn't change in what R3.9 judges (`judged`: a shorter name of the album or an artist
    agrees)."""
    tried = patterns.patterns_of(user)
    got = patterns.states(songs, tried)
    assert len(got) == len(songs)
    chosen = patterns.detected(patterns.detect(tried, [p for p, _ in songs]))
    for (path, tags), (state, diffs) in zip(songs, got, strict=True):
        assert state in (None, MATCH, FIX, BARE)
        if state == MATCH:
            assert chosen is not None
            values = patterns.judged(chosen, path, tags, patterns.given(chosen, path))
            assert patterns.infer(tags, values) == tags
        assert (state == MATCH) <= (diffs == ())
        assert (state == FIX) <= bool(diffs) and (state is None) <= (diffs == ())


# ---------- the layout: paths made from tags (R12.1, R12.1.1) ----------

LAYOUT = parse(patterns.LAYOUT, naming=True)
NEAP = Tags(title="Neap Tide", artist=LD, albumartist=LD, album="Tide Tables", year=2022, track=1)


def placed(tags, name="x", ext=".flac", layout=LAYOUT, discs=1):
    return patterns.render(layout, patterns.values_for(tags, discs), name, ext)


def test_the_default_layout_makes_a_songs_path_from_its_tags():
    """R12.1: {albumartist}/{year} - {album}/{disc-}{track:02} - {title}, the track padded to two
    digits, the disc and "-" only when the album has more than one disc."""
    assert placed(NEAP) == "Lumen Drift/2022 - Tide Tables/01 - Neap Tide.flac"
    two = Tags(title="Moonpull", artist=LD, album="Tide Tables", year=2022, track=12, disc=2)
    assert placed(two) == "Lumen Drift/2022 - Tide Tables/12 - Moonpull.flac"  # one disc
    assert placed(two, discs=2) == "Lumen Drift/2022 - Tide Tables/2-12 - Moonpull.flac"
    assert placed(replace_tags(two, disctotal=2)).endswith("/2-12 - Moonpull.flac")
    assert placed(replace_tags(NEAP, track=104)).endswith("/104 - Neap Tide.flac")
    p = parse("{artist}/{track:03} {disc:02}.{track} {genre}", naming=True)
    assert placed(replace_tags(NEAP, disc=1, genres=("Electronic", "Ambient")), layout=p) == (
        "Lumen Drift/001 01.1 Electronic.flac"
    )


def replace_tags(tags, **kw):
    from dataclasses import replace

    return replace(tags, **kw)


def test_a_layout_takes_the_naming_forms_and_refuses_what_names_nothing():
    """R12.1: the naming forms are a layout's alone; Infer from path reads none of them (R3.2), and
    a layout can't hold {*}, which names nothing."""
    assert LAYOUT.problem == "" and LAYOUT.regex is None
    assert parse("{track:02} - {title}").problem == "{track:02} isn't a token"
    assert parse("{artistsort}").problem == "{artistsort} isn't a token"
    assert parse("{*}/{title}", naming=True).problem == "{*} names nothing: a layout can't use it"
    assert parse("{track:2}", naming=True).problem == "{track:2} isn't a token"
    assert parse("{disc-}", naming=True).problem == ""
    assert parse("Music", naming=True).problem == "Put at least one token in it, such as {title}"
    assert parse("{album", naming=True).problem == "A brace isn't closed"


def test_the_sort_tokens_take_the_sort_tag_else_move_the_article_to_the_end():
    """R12.1, R2.13: {artistsort}, {albumartistsort}, {albumsort}: the sort tag, or without one the
    name with its leading article moved to the end ("Beatles, The")."""
    p = parse("{albumartistsort}/{albumsort}/{artistsort} - {title}", naming=True)
    beatles = Tags(title="Help", artist="The Beatles", album="A Hard Day's Night")
    assert placed(beatles, layout=p) == "Beatles, The/Hard Day's Night, A/Beatles, The - Help.flac"
    bowie = Tags(
        title="Heroes", artist="David Bowie", artistsort="Bowie, David", albumsort="Heroes"
    )
    assert placed(bowie, layout=p) == "Bowie, David/Heroes/Bowie, David - Heroes.flac"
    assert placed(replace_tags(bowie, albumartistsort="Z"), layout=p).startswith("Z/")
    assert patterns.values_for(Tags(artist="The Who"), articles=["Die"])["artistsort"] == "The Who"


def test_a_token_with_no_value_goes_with_the_text_that_joins_it():
    """R12.1: no year leaves the album alone ("Tide Tables", not " - Tide Tables"), no track the
    title; no album artist is the artist's, a compilation naming none "Various Artists" (R2.5.3,
    under it like any album, R12.1.1), no artist "Unknown artist", no album "Unknown album", no
    title the file's own name; a folder that comes out empty is left out."""
    bare = Tags(title="Neap Tide", artist=LD, album="Tide Tables")
    assert placed(bare) == "Lumen Drift/Tide Tables/Neap Tide.flac"
    assert placed(Tags(artist="Saffron Avenue")) == "Saffron Avenue/Unknown album/x.flac"
    assert placed(Tags(title="Solo", track=3)) == "Unknown artist/Unknown album/03 - Solo.flac"
    various = Tags(title="Tide", artist="A", album="Night Ferry", compilation=True, year=2024)
    assert placed(various) == "Various Artists/2024 - Night Ferry/Tide.flac"
    named = replace_tags(various, albumartist="Various Artists")
    assert placed(named) == "Various Artists/2024 - Night Ferry/Tide.flac"
    p = parse("{genre}/{artist}/{year}{title}", naming=True)
    assert placed(Tags(title="T", artist="A"), layout=p) == "A/T.flac"
    p = parse("{year} - {title}", naming=True)
    assert placed(Tags(title="T"), layout=p) == "T.flac"
    assert placed(Tags(year=1999), layout=p, name="orig") == "1999 - orig.flac"
    p = parse("{disc-}{track:02}", naming=True)
    assert placed(Tags(artist="A"), layout=p, name="orig") == "orig.flac"


@pytest.mark.parametrize(
    ("tags", "path"),
    [
        (Tags(title="What?", artist="AC/DC", album="Live: Paris"),
         "AC_DC/Live_ Paris/What_.flac"),
        (Tags(title='a "b" <c> | d*', artist="x\\y", album="tab\there"),
         "x_y/tab_here/a _b_ _c_ _ d_.flac"),
        (Tags(title=" ...Dots and spaces... ", artist=". Hidden", album="Vol. 2."),
         "Hidden/Vol. 2/Dots and spaces.flac"),
        (Tags(title="Café", artist="Björk", album="x"),  # as macOS writes them
         "Björk/x/Café.flac"),
        (Tags(title="\x00\x1f\x7f", artist="A", album="B"), "A/B/___.flac"),
    ],
)  # fmt: skip
def test_what_a_file_system_refuses_is_replaced_and_names_trimmed(tags, path):
    """R12.1.1: `/ \\ : * ? " < > |` and control characters replaced with `_`, names trimmed of
    spaces and dots at their ends, composed, so a layout gives the same path on every platform."""
    assert placed(tags) == path


def test_each_part_is_cut_to_120_characters_and_255_bytes_with_its_extension():
    """R12.1.1: each part cut to 120 characters; and to 255 bytes, the most Linux's and macOS's
    file systems take in a name, which 120 letters of a script of three or four bytes each pass
    (testing.md, "Shapes": names longer than a platform allows)."""
    long = Tags(title="t" * 300, artist="a" * 300, album="b" * 130)
    folder, album, name = placed(long).split("/")
    assert (len(folder), len(album), len(name)) == (120, 120, 120)
    assert name.endswith("t.flac")
    wide = Tags(title="音" * 200, artist="\U0001f3b5" * 100, album="b")
    folder, _, name = placed(wide).split("/")
    assert len(folder.encode()) <= 255 and len(name.encode()) <= 255 and name.endswith(".flac")
    assert len(folder) == 63 and len(name) == 88  # whole characters, never half of one
    assert patterns.clean_part("x" * 119 + " .y") == "x" * 119


@pytest.mark.parametrize(
    ("name", "ext", "made"),
    [
        ("CON", "", "CON_"), ("con", ".flac", "con_"), ("Nul.txt", "", "Nul_.txt"),
        ("COM1", "", "COM1_"), ("lpt9 ", "", "lpt9_"), ("COM¹", "", "COM¹_"),
        ("CONSOLE", "", "CONSOLE"), ("COM10", "", "COM10"), ("AUX - Live", "", "AUX - Live"),
        ("PRN.", ".mp3", "PRN_"), ("", ".flac", ""), (" . ", "", ""),
    ],
)  # fmt: skip
def test_windows_device_names_are_given_an_underscore(name, ext, made):
    """R12.1.1: a name Windows keeps for a device (CON, PRN, AUX, NUL, COM1 to COM9, LPT1 to
    LPT9, the last digit as a superscript too), whatever follows it after a dot, can't be a file
    or a folder there; an underscore after it makes it one, the same on every platform."""
    assert patterns.clean_part(name, ext) == made


def valid_everywhere(path):
    parts = path.split("/")
    for part in parts:
        assert part and part not in (".", "..")
        assert not set(part) & set('\\:*?"<>|') and all(
            ord(ch) >= 32 and ch != "\x7f" for ch in part
        )
        assert part == part.strip(" .") or part.endswith((".flac",))
        assert len(part) <= 120 and len(part.encode()) <= 255
        assert part.split(".")[0].rstrip(" ").upper() not in patterns.RESERVED
        assert unicodedata.normalize("NFC", part) == part


TEXT = st.one_of(st.none(), st.text(max_size=300), st.sampled_from(["CON", "AC/DC", " . ", "nul"]))


@given(
    st.builds(
        Tags, title=TEXT, artist=TEXT, album=TEXT, albumartist=TEXT,
        track=st.one_of(st.none(), st.integers(0, 10**6)), disc=st.one_of(st.none(),
        st.integers(0, 99)), year=st.one_of(st.none(), st.integers(0, 9999)),
        genres=st.lists(st.text(max_size=40), max_size=2).map(tuple), compilation=st.booleans(),
        artistsort=TEXT, albumsort=TEXT,
    ),
    st.integers(1, 3),
    st.text(max_size=200),
)  # fmt: skip
@example(Tags(title="CON", artist="..", album="\x00"), 1, "")
def test_any_tags_give_a_path_every_platform_takes(tags, discs, name):
    """R12.1.1, a property: whatever the tags, the default layout and one of every token give a
    relative path every platform's file systems take: no part empty, `.` or `..`, none holding
    what one refuses, none ending in a space or a dot, none longer than 120 characters or 255
    bytes, none a Windows device's name, each composed."""
    for layout in (LAYOUT, parse("{genre}/{albumartistsort}/{albumsort} ({year})/{disc}.{track}"
                                 " {artist} {artistsort} {title}", naming=True)):  # fmt: skip
        path = placed(tags, name=name, layout=layout, discs=discs)
        valid_everywhere(path)
        assert path.endswith(".flac")


@given(st.text())
def test_any_text_as_a_layout_is_one_or_says_why(text):
    p = parse(text, naming=True)
    assert p.regex is None and isinstance(p.problem, str)
    if not p.problem:
        valid_everywhere(patterns.render(p, patterns.values_for(NEAP), "x", ".flac"))
