"""The Edit tags panel's logic (src/musikata_core/tags/edit.py; R4.2 to R4.4): what each field shows
for a set of songs, shared or mixed with the values in use, and what the user's typing changes on
which songs, as the jobs of a save.

Why: a field that says the songs share a value they don't, or an edit that writes over a mixed
field the user left alone, changes many files at once in a way the user never asked for; and a
count of what will change that doesn't match what Save writes makes the user trust neither."""

from hypothesis import given, settings
from hypothesis import strategies as st

from musikata_core.tags import Job, Tags, edit
from musikata_core.tags.edit import Field, change_of, field_of, fields_of, plan, problem, problems

TIDE = [  # L03's four songs of Tide Tables, as the demo library tags them
    Tags(title="Neap Tide", artist="Lumen Drift", album="Tide Tables", albumartist="Lumen Drift",
         track=1, tracktotal=9, disc=1, disctotal=1, year=2022, genres=("Electronica",)),
    Tags(title="Spring Tide", artist="Lumen Drift", album="Tide Tables", albumartist="Lumen Drift",
         track=2, tracktotal=9, disc=1, disctotal=1, year=2022, genres=("electronic",)),
    Tags(title="Slack Water", artist="Lumen Drift", album="Tide Tables", albumartist="Lumen Drift",
         track=3, tracktotal=9, disc=1, disctotal=1, genres=("Electronic",)),
    Tags(title="Moonpull", artist="lumen drift", album="Tide Tables", albumartist="Lumen Drift",
         track=4, tracktotal=9, disc=1, disctotal=1, year=2022, genres=("Electronic",)),
]  # fmt: skip
PATHS = [f"/m/LD/TT/0{n}.flac" for n in range(1, 5)]


def songs():
    return list(zip(PATHS, TIDE, strict=True))


def test_a_value_every_song_has_shows_and_one_that_differs_is_mixed_with_its_values_in_use():
    """R4.3: the same value shows; differing values are mixed, the ▾ listing each with its count."""
    shown = fields_of(TIDE)
    assert shown["album"] == Field("album", "Tide Tables", False, (("Tide Tables", 4),))
    assert shown["disc"].text == "1 / 1" and not shown["disc"].mixed
    title = shown["title"]
    assert title.mixed and title.text == "" and len(title.values) == 4
    artist = shown["artist"]
    assert artist.mixed and artist.values == (("Lumen Drift", 3), ("lumen drift", 1))
    # a song without a year isn't a value in use
    assert shown["year"].mixed and shown["year"].values == (("2022", 3),)
    assert shown["genres"].values == (("Electronic", 2), ("electronic", 1), ("Electronica", 1))
    assert shown["compilation"].text == "No" and not shown["compilation"].mixed
    assert shown["composer"] == Field("composer", "", False, ())


def test_a_track_shows_the_total_the_songs_share_and_numbers_each_their_own():
    track = fields_of(TIDE)["track"]
    assert track.mixed and track.text == "/ 9" and track.parts_mixed == (True, False)
    assert field_of("track", [Tags(track=4)]).text == "4"
    assert field_of("track", []).text == ""
    assert edit.pair_text(None, None) == ""


def test_one_song_shows_each_of_its_values():
    shown = fields_of(TIDE[:1])
    assert shown["title"].text == "Neap Tide" and not shown["title"].mixed
    assert shown["track"].text == "1 / 9" and shown["year"].text == "2022"
    assert shown["genres"].text == "Electronica"


def test_typing_in_a_mixed_field_sets_it_on_every_song_and_leaving_it_empty_keeps_each_own():
    """R4.3: typing in a mixed field sets that value on every selected song; left alone, each
    song's own."""
    shown = fields_of(TIDE)
    p = plan(songs(), {"artist": "Lumen Drift"}, shown)
    assert p.fields == ("artist",)
    assert p.jobs == (Job(PATHS[3], {"artist": "Lumen Drift"}),)
    assert plan(songs(), {"title": ""}, shown).jobs == ()
    assert plan(songs(), {"title": "  "}, shown).jobs == ()


def test_l03s_three_fields_change_on_its_four_songs():
    """R4.4: "3 fields will change on 4 songs", as L03-songs-bulk-edit shows it."""
    edits = {"artist": "Lumen Drift", "genres": "Electronic", "year": "2022"}
    p = plan(songs(), edits, fields_of(TIDE))
    assert p.fields == ("artist", "genres", "year")
    assert [j.path for j in p.jobs] == PATHS
    assert p.jobs[0].changes == {"genres": ["Electronic"]}
    assert p.jobs[2].changes == {"year": 2022}
    assert p.jobs[3].changes == {"artist": "Lumen Drift"}


def test_a_shared_value_changed_or_cleared_is_set_or_removed_on_every_song():
    shown = fields_of(TIDE)
    p = plan(songs(), {"album": "Tide Tables (Remastered)"}, shown)
    assert len(p.jobs) == 4 and p.jobs[0].changes == {"album": "Tide Tables (Remastered)"}
    cleared = plan(songs(), {"albumartist": ""}, shown)
    assert all(j.changes == {"albumartist": None} for j in cleared.jobs)
    # typed as it was: nothing changes
    assert plan(songs(), {"album": "Tide Tables"}, shown).jobs == ()


def test_a_track_or_discs_parts_change_one_by_one():
    """A part the songs don't share keeps each song's own unless one is typed for it."""
    shown = fields_of(TIDE)
    total = plan(songs(), {"track": "/ 10"}, shown)
    assert [j.changes for j in total.jobs] == [{"tracktotal": 10}] * 4
    both = plan(songs(), {"track": "7 of 12"}, shown)
    assert both.jobs[0].changes == {"track": 7, "tracktotal": 12}
    none = plan(songs(), {"track": ""}, shown)  # the total they share removed, numbers kept
    assert [j.changes for j in none.jobs] == [{"tracktotal": None}] * 4
    disc = plan(songs(), {"disc": "2"}, shown)
    assert disc.jobs[0].changes == {"disc": 2, "disctotal": None}
    assert plan(songs(), {"disc": "1 / 1"}, shown).jobs == ()


def test_a_year_typed_as_a_date_or_the_year_a_songs_date_has_and_genres_and_compilation():
    dated = Tags(year=2003, date="2003-05-01")
    shown = fields_of([dated])
    assert change_of("year", "2003", shown["year"], dated) == {}
    assert change_of("year", "2003-06-01", shown["year"], dated) == {"year": "2003-06-01"}
    assert change_of("year", "", shown["year"], dated) == {"year": None}
    assert change_of("year", "", shown["year"], Tags()) == {}
    two = change_of("genres", "Ambient; Dub", shown["genres"], dated)
    assert two == {"genres": ["Ambient", "Dub"]}
    assert change_of("compilation", "Yes", shown["compilation"], dated) == {"compilation": True}
    assert change_of("compilation", "No", shown["compilation"], dated) == {}
    assert change_of("composer", "  Ada  ", shown["composer"], dated) == {"composer": "Ada"}


def test_text_that_cant_be_written_says_why_and_changes_nothing():
    shown = fields_of(TIDE)
    assert problem("year", "20x2") == "“20x2” isn't a year"
    assert problem("year", "0999") == "“0999” isn't a year"
    assert problem("track", "four") == "“four” isn't a number, or a number and its total"
    assert problem("compilation", "maybe") is not None
    assert problem("year", "") is None and problem("title", "anything") is None
    assert problem("disc", "2 / 3") is None and problem("year", "2003-05-01") is None
    assert change_of("year", "20x2", shown["year"], TIDE[2]) == {}
    assert problems({"year": "20x2", "title": "x"}) == {"year": "“20x2” isn't a year"}


@settings(max_examples=50, derandomize=True)
@given(
    st.lists(st.sampled_from(["Lumen Drift", "lumen drift", "Mara Okafor", None]), min_size=1,
             max_size=6),
    st.sampled_from(["", "Lumen Drift", "Kestrel Union", " lumen drift "]),
)  # fmt: skip
def test_each_job_changes_only_what_differs_and_a_song_that_already_has_it_has_none(names, typed):
    """A property: every job's change differs from its song, and every song without a job
    already reads as the edit asks (or keeps its own, for a mixed field left empty)."""
    tags = [Tags(artist=n) for n in names]
    shown = fields_of(tags)
    p = plan([(str(i), t) for i, t in enumerate(tags)], {"artist": typed}, shown)
    jobs = {j.path: j.changes for j in p.jobs}
    for i, t in enumerate(tags):
        want = typed.strip() or None
        if (shown["artist"].mixed and want is None) or t.artist == want:
            assert str(i) not in jobs
        else:
            assert jobs[str(i)] == {"artist": want}
    assert p.fields == (("artist",) if jobs else ())
