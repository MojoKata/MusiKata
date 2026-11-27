"""The Edit tags panel's bulk tools (src/musikata_core/tags/tools.py; R4.5): Number tracks, Replace
in field, Tidy case and Copy from…, each a plain function from the songs' tags and its options to
what each song would become, and the save of the songs chosen.

Why: a bulk tool changes many files at once; one that numbers in another order than the list
shows, replaces in a field it wasn't asked to, crashes on an expression typed half way, or saves
a song the user unchecked costs the user their tags across a whole album."""

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core.tags import Job, Tags, compose
from musikata_core.tags.tools import (
    COPIED,
    WORDS,
    Planned,
    ReplaceError,
    Song,
    changes_of,
    copy_from,
    number_tracks,
    replace_in_field,
    replacer,
    text_of,
    tidy,
)

TIDE = [  # L03's four songs of Tide Tables, as the demo library tags them
    Tags(title="Neap Tide", artist="Lumen Drift", album="Tide Tables", albumartist="Lumen Drift",
         track=1, tracktotal=9, year=2022, genres=("Electronica",)),
    Tags(title="Spring Tide", artist="Lumen Drift", album="Tide Tables", albumartist="Lumen Drift",
         track=2, tracktotal=9, year=2022, genres=("electronic",)),
    Tags(title="Slack Water", artist="Lumen Drift", album="Tide Tables", albumartist="Lumen Drift",
         track=3, tracktotal=9, genres=("Electronic",)),
    Tags(title="Moonpull", artist="lumen drift", album="Tide Tables", albumartist="Lumen Drift",
         track=4, tracktotal=9, year=2022, genres=("Electronic",)),
]  # fmt: skip


def songs(tags=TIDE):
    return [Song(f"/m/LD/TT/{n:02d}.flac", t) for n, t in enumerate(tags, 1)]


def changed(planned: Planned):
    return [planned.changed(i) for i in range(len(planned.songs))]


# ---------- R4.5.1 Number tracks ----------


def test_number_tracks_numbers_in_the_order_given_and_sets_the_total():
    """R4.5.1: 1, 2, 3 … in the list's order, and Track total, the songs' count."""
    shuffled = songs([TIDE[3], TIDE[0], TIDE[2], TIDE[1]])  # the list sorted another way
    planned = number_tracks(shuffled)
    assert planned.columns == ("track", "tracktotal")
    assert [(t.title, t.track, t.tracktotal) for t in planned.new] == [
        ("Moonpull", 1, 4), ("Neap Tide", 2, 4), ("Slack Water", 3, 4),
        ("Spring Tide", 4, 4)]  # fmt: skip
    jobs = planned.jobs(range(4))
    assert jobs[0] == Job("/m/LD/TT/01.flac", {"track": 1, "tracktotal": 4})
    assert jobs[2] == Job("/m/LD/TT/03.flac", {"tracktotal": 4})  # already the third


def test_numbering_songs_numbered_so_already_changes_nothing():
    numbered = [replace(t, tracktotal=4) for t in TIDE]
    planned = number_tracks(songs(numbered))
    assert changed(planned) == [()] * 4 and planned.jobs(range(4)) == []
    assert number_tracks([]).jobs([]) == []


def test_numbering_a_song_without_a_number_or_total_gives_it_both():
    planned = number_tracks(songs([Tags(title="Loose")]))
    assert planned.jobs([0]) == [Job("/m/LD/TT/01.flac", {"track": 1, "tracktotal": 1})]


# ---------- R4.5.2 Replace in field ----------


def test_replace_finds_text_in_one_field_whatever_its_case_and_replaces_it():
    """R4.5.2: as text, case set aside unless asked; other fields untouched."""
    planned = replace_in_field(songs(), "artist", "lumen drift", "Lumen Drift")
    assert planned.columns == ("artist",)
    assert changed(planned) == [(), (), (), ("artist",)]  # the same text is no change
    assert planned.jobs(range(4)) == [Job("/m/LD/TT/04.flac", {"artist": "Lumen Drift"})]
    exact = replace_in_field(songs(), "artist", "lumen drift", "Lumen Drift", match_case=True)
    assert changed(exact) == [(), (), (), ("artist",)]
    none = replace_in_field(songs(), "artist", "LUMEN", "Glow", match_case=True)
    assert changed(none) == [()] * 4
    tide = replace_in_field(songs(), "title", "Tide", "Tides")
    assert [t.title for t in tide.new] == ["Neap Tides", "Spring Tides", "Slack Water", "Moonpull"]
    assert {t.album for t in tide.new} == {"Tide Tables"}


def test_replace_as_text_takes_marks_and_backslashes_as_they_are():
    t = [Tags(title="Song (Live) [1.0]"), Tags(title="A.B.C")]
    planned = replace_in_field(songs(t), "title", "(Live) [1.0]", r"\1 $&")
    assert planned.new[0].title == r"Song \1 $&"
    dots = replace_in_field(songs(t), "title", ".", "-")
    assert [x.title for x in dots.new] == ["Song (Live) [1-0]", "A-B-C"]


def test_replace_as_a_regular_expression_with_groups():
    """R4.5.2: a regular expression, its groups named in what replaces it."""
    t = [Tags(title="Neap Tide (feat. Mara Okafor)"), Tags(title="Ebb - Live")]
    planned = replace_in_field(songs(t), "title", r"\s*\(feat\. (.+)\)$", "", regex=True)
    assert [x.title for x in planned.new] == ["Neap Tide", "Ebb - Live"]
    live = replace_in_field(songs(t), "title", r"^(?P<song>.+) - Live$", r"\g<song> (Live)",
                            regex=True)  # fmt: skip
    assert live.new[1].title == "Ebb (Live)"
    swapped = replace_in_field(songs(t), "title", r"(\w+) - (\w+)", r"\2: \1", regex=True)
    assert swapped.new[1].title == "Live: Ebb"


@pytest.mark.parametrize(
    ("find", "by", "why"),
    [
        ("(", "", "The regular expression isn't valid: missing ), unterminated subpattern (at 0)"),
        ("a{2,1}", "", "The regular expression isn't valid: min repeat greater than max repeat"),
        ("*", "", "nothing to repeat"),
        ("[z-a]", "", "bad character range"),
        ("(a)", r"\2", "The replacement isn't valid: invalid group reference 2"),
        ("a", "\\", "The replacement isn't valid: bad escape (end of pattern)"),
        ("(?P<x>a)", r"\g<y>", "The replacement isn't valid: unknown group name 'y'"),
        ("", "x", "Type what to find"),
    ],
)
def test_an_invalid_expression_or_replacement_says_why_and_changes_nothing(find, by, why):
    """R4.5.2: what is typed half way, or wrongly, is said in words; nothing crashes."""
    with pytest.raises(ReplaceError) as e:
        replace_in_field(songs(), "title", find, by, regex=True)
    assert why in str(e.value)


def test_text_that_looks_like_an_expression_is_text():
    planned = replace_in_field(songs([Tags(title="Why (")]), "title", "(", ")")
    assert planned.new[0].title == "Why )"


def test_replace_in_genre_works_on_each_genre_alone():
    """R9.2: ^ and $ hold each genre; a genre replaced by nothing goes; ";" makes several; two
    that become one are one."""
    t = [Tags(genres=("Electronica", "Ambient")), Tags(genres=("electronic",)),
         Tags(genres=("Electronic", "Electronica"))]  # fmt: skip
    planned = replace_in_field(songs(t), "genres", "^electronica?$", "Electronic", regex=True)
    assert [x.genres for x in planned.new] == [
        ("Electronic", "Ambient"), ("Electronic",), ("Electronic",)]  # fmt: skip
    assert planned.jobs([0]) == [Job("/m/LD/TT/01.flac", {"genres": ["Electronic", "Ambient"]})]
    gone = replace_in_field(songs(t), "genres", "Ambient", "")
    assert gone.new[0].genres == ("Electronica",)
    split = replace_in_field(songs(t), "genres", "Ambient", "Ambient; Drone")
    assert split.new[0].genres == ("Electronica", "Ambient", "Drone")
    assert replace_in_field(songs([Tags()]), "genres", "x", "y").new[0] == Tags()


def test_a_text_field_replaced_by_nothing_is_removed_and_one_without_a_value_stays_so():
    t = [Tags(comment="ripped by EAC"), Tags(comment=None), Tags(comment="  keep  ")]
    planned = replace_in_field(songs(t), "comment", "ripped by EAC", "")
    assert planned.new[0].comment is None and planned.new[1].comment is None
    assert planned.new[2] == t[2]  # nothing found: the value as it was, spaces and all
    assert planned.jobs(range(3)) == [Job("/m/LD/TT/01.flac", {"comment": None})]


def test_replace_works_on_text_fields_and_genre_only():
    with pytest.raises(ValueError, match="year"):
        replace_in_field(songs(), "year", "2022", "2023")
    assert "genres" in WORDS and "title" in WORDS and "track" not in WORDS


def test_replacer_alone():
    assert replacer("a", "b")("aAa") == "bbb"
    assert replacer("a", "b", match_case=True)("aAa") == "bAb"
    assert replacer("a+", "-", regex=True)("caaab") == "c-b"


# ---------- R4.5.3 Tidy case ----------


def test_tidy_case_on_the_fields_chosen_genre_by_genre():
    """R4.5.3: R3.6.1 on the fields chosen, the others untouched."""
    t = [Tags(title="NEAP TIDE", artist="lumen drift", album="tide tables",
              genres=("electronic", "DEEP HOUSE", "Hip-Hop"))]  # fmt: skip
    planned = tidy(songs(t), ["genres", "artist"])
    assert planned.columns == ("artist", "genres")  # in the fields' order, not the choosing
    new = planned.new[0]
    assert new.artist == "Lumen Drift" and new.genres == ("Electronic", "Deep House", "Hip-Hop")
    assert new.title == "NEAP TIDE" and new.album == "tide tables"
    assert planned.jobs([0]) == [Job("/m/LD/TT/01.flac", {
        "artist": "Lumen Drift", "genres": ["Electronic", "Deep House", "Hip-Hop"]})]  # fmt: skip


def test_tidy_case_on_l03s_songs_changes_what_isnt_tidy_only():
    planned = tidy(songs(), ["title", "artist", "album", "albumartist", "genres"])
    assert changed(planned) == [(), ("genres",), (), ("artist",)]
    assert tidy(songs(), []).jobs(range(4)) == []
    with pytest.raises(ValueError, match="compilation"):
        tidy(songs(), ["compilation"])


def test_tidying_genres_that_become_the_same_keeps_one():
    planned = tidy(songs([Tags(genres=("rock", "Rock"))]), ["genres"])
    assert planned.new[0].genres == ("Rock",)


# ---------- R4.5.4 Copy from… ----------


def test_copy_from_copies_the_fields_chosen_from_one_song_to_the_others():
    """R4.5.4: a bonus track ripped apart from its album gets its album's fields."""
    bonus = Tags(title="Slack Tide (bonus)", artist="Lumen Drift", album="Tide Tables (Deluxe)",
                 track=10, genres=("Ambient",))  # fmt: skip
    model = replace(TIDE[0], date="2022-05-01", disc=1, disctotal=1, compilation=False)
    planned = copy_from(songs([model, bonus]), 0, ["genres", "album", "year", "disctotal"])
    assert planned.columns == ("album", "year", "genres", "disctotal")
    assert changed(planned) == [(), ("album", "year", "genres", "disctotal")]
    new = planned.new[1]
    assert (new.album, new.year, new.date, new.genres, new.disctotal) == (
        "Tide Tables", 2022, "2022-05-01", ("Electronica",), 1)  # fmt: skip
    assert new.title == "Slack Tide (bonus)" and new.track == 10  # what isn't chosen stays
    (job,) = planned.jobs([0, 1])
    assert job.changes == {"album": "Tide Tables", "year": "2022-05-01",
                           "genres": ["Electronica"], "disctotal": 1}  # fmt: skip
    assert compose.normalize(job.changes)["year"] == (2022, "2022-05-01")


def test_copying_an_empty_value_removes_it_and_copying_a_year_alone_drops_a_date():
    model, other = Tags(album="A"), Tags(album="B", year=2001, date="2001-02-03", comment="x")
    planned = copy_from(songs([model, other]), 0, ["year", "comment", "compilation"])
    assert planned.jobs([1]) == [Job("/m/LD/TT/02.flac", {"year": None, "comment": None})]
    yearly = copy_from(songs([Tags(year=1999), other]), 0, ["year"])
    assert yearly.jobs([1]) == [Job("/m/LD/TT/02.flac", {"year": 1999})]


def test_copy_from_checks_its_source_and_fields():
    with pytest.raises(ValueError, match="no song 4"):
        copy_from(songs(), 4, ["album"])
    with pytest.raises(ValueError, match="title"):
        copy_from(songs(), 0, ["title"])
    assert "title" not in COPIED and "track" not in COPIED


# ---------- what the preview shows, and the save ----------


def test_only_the_songs_chosen_are_saved():
    """R3.7: unchecking a file leaves it alone."""
    planned = number_tracks(songs())
    assert [j.path for j in planned.jobs({1, 3})] == ["/m/LD/TT/02.flac", "/m/LD/TT/04.flac"]
    assert planned.jobs(set()) == []


def test_each_field_shows_as_text():
    t = Tags(year=2022, date="2022-05-01", genres=("A", "B"), compilation=True, track=4)
    assert text_of("year", t) == "2022-05-01" and text_of("year", Tags(year=987)) == "0987"
    assert text_of("genres", t) == "A; B" and text_of("compilation", t) == "Yes"
    assert text_of("compilation", Tags()) == "No" and text_of("track", t) == "4"
    assert text_of("title", t) == "" and text_of("year", Tags()) == ""
    assert changes_of(["year", "genres", "compilation"], t) == {
        "year": "2022-05-01", "genres": ["A", "B"], "compilation": True}  # fmt: skip


@given(st.lists(st.text(max_size=12), max_size=6), st.text(max_size=5), st.text(max_size=5),
       st.booleans())  # fmt: skip
def test_any_replace_either_plans_or_says_why_and_its_jobs_are_writable(titles, find, by, regex):
    """A property: whatever is typed, Replace plans or raises its own error, and every job it
    makes is one compose.normalize takes."""
    tags = [Tags(title=t or None, genres=(t,) if t.strip() else ()) for t in titles]
    for name in ("title", "genres"):
        try:
            planned = replace_in_field(songs(tags), name, find, by, regex=regex)
        except ReplaceError:
            continue
        for job in planned.jobs(range(len(tags))):
            compose.normalize(job.changes)
