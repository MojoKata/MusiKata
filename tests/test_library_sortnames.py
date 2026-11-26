"""Sort names (src/musikata_core/sortnames.py; R2.13): the sort tag wins, a leading article is
skipped without one, and case, leading punctuation and the width of numbers don't count.

Why: the keys are stored in the index and SQL sorts by them as plain text, so a key that orders
two names wrongly lists an artist under the wrong letter in every view, and nothing at the query
would show it."""

from hypothesis import given
from hypothesis import strategies as st

from musikata_core import sortnames as sn


def ordered(names):
    return sorted(names, key=sn.sort_key)


def test_a_sort_tag_wins_over_the_name():
    assert sn.sort_name("David Bowie", "Bowie, David") == "Bowie, David"
    assert sn.sort_key("David Bowie", "Bowie, David") == "bowie, david"
    assert sn.sort_name("The Beatles", "  ") == "Beatles"  # a blank tag is no tag


def test_without_a_sort_tag_a_leading_article_is_skipped_any_case():
    assert [sn.sort_name(n) for n in ("The Beatles", "the paper lanterns", "A Tribe", "An Owl",
                                      "THE  Who")] == [  # fmt: skip
        "Beatles", "paper lanterns", "Tribe", "Owl", "Who"
    ]  # fmt: skip
    assert ordered(["The Paper Lanterns", "Mara Okafor", "Orbital Fern"]) == [
        "Mara Okafor", "Orbital Fern", "The Paper Lanterns"
    ]  # fmt: skip


def test_a_name_that_only_looks_like_an_article_is_kept():
    for name in ("The", "A", "A-ha", "Theory", "Anthem", "The "):
        assert sn.sort_name(name) == name.strip(), name


def test_the_articles_are_a_list_others_can_be_added_to():
    assert sn.ARTICLES == ("The", "A", "An")
    assert sn.sort_name("Die Ärzte") == "Die Ärzte"
    assert sn.sort_name("Die Ärzte", articles=(*sn.ARTICLES, "Die")) == "Ärzte"
    assert sn.sort_key("Le Tigre", articles=("Le",)) == "tigre"


def test_case_and_leading_punctuation_are_set_aside():
    assert sn.sort_key("...And Justice") == sn.sort_key("and justice") == "and justice"
    assert sn.sort_key("'74 Jailbreak") == "0274 jailbreak"
    assert sn.sort_name('"The Clash"') == 'Clash"'
    assert ordered(["beta", "Alpha", "(Gamma)"]) == ["Alpha", "beta", "(Gamma)"]
    assert sn.sort_key("!!!") == "!!!"  # nothing but punctuation: as written


def test_numbers_are_read_by_value():
    assert ordered(["Disc 10", "Disc 9", "Disc 1", "Disc 009b"]) == [
        "Disc 1", "Disc 9", "Disc 009b", "Disc 10"
    ]  # fmt: skip
    assert ordered(["10,000 Maniacs", "2 Unlimited", "ABBA"]) == [
        "2 Unlimited", "10,000 Maniacs", "ABBA"
    ]  # fmt: skip
    assert sn.key_of("0") == "010" and sn.key_of("000") == "010"


def test_no_name_has_no_key_so_it_sorts_last_in_sql():
    assert sn.sort_key(None) is None and sn.sort_key("  ") is None
    assert sn.sort_name(None, "Sorted anyway") == "Sorted anyway"


@given(st.lists(st.integers(min_value=0, max_value=10**30), min_size=2, max_size=6))
def test_any_numbers_sort_by_value_in_a_name(numbers):
    names = [f"Track {n}" for n in numbers]
    assert [int(n.split()[1]) for n in ordered(names)] == sorted(numbers)


@given(st.text(max_size=30), st.sampled_from(["The ", "the ", "THE "]))
def test_a_name_with_an_article_sorts_as_the_name_without_it(name, article):
    rest = name.strip()
    if rest and rest[0].isalnum() and sn.skip_article(rest) == rest:
        assert sn.sort_key(article + rest) == sn.sort_key(rest)
