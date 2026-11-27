"""Tidy case (src/musikata_core/tags/case.py; R3.6.1, used by R4.5.3 and R3): all lower or all
upper case becomes Title Case, small words lower inside, mixed case left alone; and the shapes
names and titles take (docs/process/testing.md, "Shapes": `tags.case`).

Why: Tidy case rewrites many files' names at once; a rule that capitalizes after an apostrophe
("Don'T"), splits an accent typed as its own character, turns a name the user spelled with care
("iPhone", "McCartney") into another, or drops a space, changes tags the user never asked to
change, on every song selected."""

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core.tags.case import has_mixed_case, tidy_case


@pytest.mark.parametrize(
    ("value", "tidied"),
    [
        ("lumen drift", "Lumen Drift"),
        ("LUMEN DRIFT", "Lumen Drift"),
        ("electronic", "Electronic"),
        ("the best of the beatles", "The Best of the Beatles"),
        ("THE END OF THE WORLD", "The End of the World"),
        ("a day in the life", "A Day in the Life"),
        ("songs to play on", "Songs to Play On"),  # the last word, even a small one
    ],
)
def test_all_lower_or_all_upper_becomes_title_case_with_small_words_lower_inside(value, tidied):
    assert tidy_case(value) == tidied


@pytest.mark.parametrize(
    "value", ["Lumen Drift", "deadmau5 Live", "iPhone", "McCartney", "The xx", "k.d. lang Live"]
)
def test_a_value_with_mixed_case_is_left_as_it_is(value):
    """R3.6.1: mixed case already says how the name is spelled."""
    assert tidy_case(value) == value and has_mixed_case(value)


def test_shapes_with_no_case_are_left_as_they_are():
    """Nothing, spaces, digits, marks, and scripts without case (Japanese, Chinese)."""
    for value in ("", "   ", "1999", "…", "#!@", "東京事変", "いきものがかり"):
        assert tidy_case(value) == value and not has_mixed_case(value)


def test_apostrophes_never_start_a_word():
    """Contractions and a leading apostrophe; the typographic one (’) as the plain one."""
    assert tidy_case("don't stop me now") == "Don't Stop Me Now"
    assert tidy_case("DON’T STOP") == "Don’t Stop"
    assert tidy_case("'til tuesday") == "'Til Tuesday"
    assert tidy_case("rock 'n' roll") == "Rock 'n' Roll"
    assert tidy_case("o'brien") == "O'brien"  # one capital per word: the Irish name isn't known


def test_accents_whether_one_character_or_a_letter_and_its_mark():
    """Accented capitals and lower case, composed (NFC, as most programs write) or not (NFD, as
    macOS names files)."""
    assert tidy_case("édith piaf") == "Édith Piaf"
    assert tidy_case("ÉDITH PIAF") == "Édith Piaf"
    nfd = unicodedata.normalize("NFD", "édith piaf")
    assert tidy_case(nfd) == unicodedata.normalize("NFD", "Édith Piaf")
    assert tidy_case("sigur rós") == "Sigur Rós"
    assert tidy_case("МУМИЙ ТРОЛЛЬ") == "Мумий Тролль"
    assert tidy_case("straße") == "Straße"  # "ß" has no one-letter capital
    assert tidy_case("ßtadt") == "ßtadt"


def test_hyphens_slashes_and_dots_part_words():
    """Each part of a hyphenated or slashed name, and each letter of initials, is a word."""
    assert tidy_case("jay-z") == "Jay-Z"
    assert tidy_case("rock-and-roll hall") == "Rock-and-Roll Hall"
    assert tidy_case("r.e.m.") == "R.E.M."
    assert tidy_case("ac/dc") == "Ac/Dc"
    # all capitals is how a shout and an acronym are typed alike: AC/DC is tidied too, and the
    # preview (R3.7) is where its file is unchecked
    assert tidy_case("AC/DC") == "Ac/Dc"


def test_digits_inside_and_at_the_start_of_words():
    assert tidy_case("deadmau5") == "Deadmau5"
    assert tidy_case("blink-182") == "Blink-182"
    assert tidy_case("1st of the month") == "1st of the Month"
    assert tidy_case("80s hits") == "80s Hits"
    assert tidy_case("'80S HITS") == "'80s Hits"


def test_roman_numerals_of_i_v_and_x_are_capitals_and_other_words_are_words():
    assert tidy_case("symphony no. ix") == "Symphony No. IX"
    assert tidy_case("part ii") == "Part II"
    assert tidy_case("ROCKY IV") == "Rocky IV"
    assert tidy_case("chapter xxxix") == "Chapter XXXIX"
    assert tidy_case("i want you") == "I Want You"
    assert tidy_case("club mix") == "Club Mix"  # M, D, C and L make words, not numerals
    assert tidy_case("civil dim lid") == "Civil Dim Lid"
    assert tidy_case("vix iiii") == "Vix Iiii"  # not numerals at all


def test_a_part_of_a_title_starts_with_a_capital():
    """After ":", "(", "[", "/" or a dash between spaces, a small word starts a part."""
    assert tidy_case("live: the best of") == "Live: The Best Of"
    assert tidy_case("song (the remix)") == "Song (The Remix)"
    assert tidy_case("song [a cappella]") == "Song [A Cappella]"
    assert tidy_case("the end - a live take") == "The End - A Live Take"
    assert tidy_case("song (feat. x)") == "Song (Feat. X)"


def test_spaces_and_marks_are_kept_as_they_are():
    assert tidy_case("  spaced  out  ") == "  Spaced  Out  "
    assert tidy_case("tab\tand\nline") == "Tab\tand\nLine"
    assert tidy_case("under_score words") == "Under_Score Words"  # R3.6.3 reads "_" as a space
    assert tidy_case("what?! no...") == "What?! No..."


def test_a_very_long_value_is_tidied_whole():
    value = "lumen drift " * 2000
    assert tidy_case(value) == "Lumen Drift " * 2000


@given(st.text(max_size=60))
def test_any_text_keeps_its_length_in_letters_and_its_marks_and_tidies_once(value):
    """A property: tidying changes only the case of letters, and tidying again changes nothing."""
    tidied = tidy_case(value)
    assert tidied.casefold() == value.casefold() or tidied.lower() == value.lower()
    assert tidy_case(tidied) == tidied
    if has_mixed_case(value):
        assert tidied == value
