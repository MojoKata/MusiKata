"""Every id the documents and the code cite names something, and the indexes match their files
(scripts/doccheck.py, docs/process/README.md, "The documents' rules").

Why: an id is a promise that its item is there. AppKata's comments kept citing items after they
were renumbered and split, three of them pointing at items that had gone, and only a check that
reads every citation finds that. In MusiKata the check's first run found a wrapped line that
started with a cited id, which read as the same item numbered twice.
"""

import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import doccheck  # noqa: E402

URL = "https://github.com/MojoKata/MusiKata/issues/"


def test_every_id_cited_names_an_item_and_the_indexes_match_their_files():
    if not os.path.isdir(os.path.join(ROOT, ".git")) and not os.path.isfile(
        os.path.join(ROOT, ".git")
    ):
        pytest.skip("not a git work tree")
    found = doccheck.problems()
    assert not found, "\n".join(found)


@pytest.mark.parametrize(
    ("line", "found"),
    [
        (f"a gap ([G#81]({URL}81)).", []),
        (f"a question ([Q#82]({URL}82)).", []),
        (f"an issue ([#7]({URL}7)).", []),
        ("[Q#82] alone", ["[Q#82] links to no issue"]),
        (f"[N#5]({URL}5)", ["[N#5]: the prefix is Q, G or none"]),
        (f"[G#5]({URL}6)", [f"[G#5] links to {URL}6, not issue 5"]),
        (
            "[G#5](https://github.com/other/repo/issues/5)",
            ["[G#5] links to https://github.com/other/repo/issues/5, not issue 5"],
        ),
        ("[G#?crossfade-curve] stands in", ["[G#?crossfade-curve] waits for its issue to be made"]),
    ],
)
def test_an_issue_is_cited_by_a_link_to_that_issue(line, found):
    assert doccheck.issue_link_problems(line) == found


@pytest.mark.parametrize(
    ("text", "cited"),
    [
        ("(R17.4) and R1.1's platforms", ["R17.4", "R1.1"]),
        ("R17.1–R17.4, R17", ["R17.1", "R17.4", "R17"]),
        ("review 3, R3-21; round four, R4-3", []),  # findings, not items
        ("screen A01, mockup N05, check A1-prompt", []),  # mockups and field-test checks
        ("A3.4 and `R2.11` in code", ["A3.4", "R2.11"]),
        ("AR1.1, R1.1x, 2R1", []),
    ],
)
def test_what_counts_as_a_citation(text, cited):
    assert [m.group(1) for m in doccheck.CITED.finditer(text)] == cited


def test_a_citation_of_an_item_that_is_not_there_is_caught():
    ids = {"R1": [], "R1.1": []}
    assert doccheck.citation_problems(
        "x.md", "see R1.1 and R1.2\n```\nR9.9 in code\n```\n", ids
    ) == ["x.md:1: R1.2 is numbered by no section"]
    missing = "R" + "9.9"  # spelled in parts, so this file cites nothing that isn't there
    assert doccheck.citation_problems("x.py", f"# {missing}\n", ids) == [
        f"x.py:1: {missing} is numbered by no section"
    ]


def test_a_wrapped_line_starting_with_a_cited_id_reads_as_that_item():
    """Why R1.2.1 is worded so no line starts with "R6.2.": doccheck counts such a line as the
    item."""
    assert [m.group(1) for m in doccheck.DEFINED.finditer("its look is\nR6.2. Playback")] == [
        "R6.2"
    ]


def test_the_requirements_table_and_the_architecture_headings_are_both_read_as_indexes():
    assert doccheck.TABLE_ROW.search(
        "| **R3** | [Tags from paths](R3-tags-from-paths.md) | x |"
    ).groups() == ("R", "3", "Tags from paths", "R3-tags-from-paths.md")
    assert doccheck.SECTION_HEAD.search("# 3. Tags\n").groups() == ("3", "Tags")


def test_now_playing_is_not_read_as_a_changelog_word():
    assert not doccheck.CHANGELOG.search("the now-playing bar and Now Playing")
    assert doccheck.CHANGELOG.search("it is now saved")
