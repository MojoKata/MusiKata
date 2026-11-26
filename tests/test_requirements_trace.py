"""Every promise a requirement makes is shown by a test, or says why not (docs/process/testing.md,
"The requirements trace").

Why: a decision written down is not a feature built. AppKata's second review found options its
requirements promised that no code had, and no test noticed, because nothing tied a sentence of the
requirements to a test. docs/requirements/trace.md does: a row per sentence (and table row) of each
traced section, naming the tests that show it, the tier 3 check that does when only a person can,
the `future` issue it waits on, or `statement` when it promises nothing a test could show. This test
splits each traced section the same way and fails when a sentence has no row, a row no longer
matches its sentence, or a row names a test, or an issue, that isn't there.
"""

import os
import re

import reqdocs

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TRACE = "docs/requirements/trace.md"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("*", "").replace("`", "")).strip()


def section_units(sec: str, number: int) -> list[tuple[str, str]]:
    """(requirement id, unit) for every sentence and table row of section `number`'s text: the
    split the trace is written against."""
    out = []
    for item in re.split(rf"\n(?=R{number}\.[0-9.]+ )", "\n" + sec)[1:]:
        rid = re.match(rf"(R{number}\.[0-9.]*[0-9])", item).group(1)
        prose, rows = [], []
        for line in item.split("\n"):
            if line.startswith("#"):  # an item file's own heading
                continue
            if line.startswith("|"):
                if not re.match(r"^\|[-|: ]+\|$", line) and not _is_header(line, item):
                    rows.append(_norm(line))
            else:
                prose.append(line)
        body = re.sub(rf"^R{number}\.[0-9.]*[0-9]\.? ", "", _norm(" ".join(prose)))
        sentences = re.split(r"(?<=[.;:])\s+(?!R\d)(?=[A-Z(*\"'])", body)
        out += [(rid, s) for s in sentences if len(s) > 20]
        out += [(rid, r) for r in rows]
    return out


def _is_header(line: str, item: str) -> bool:
    """A table's first row, the one its |---| line follows."""
    lines = item.split("\n")
    i = lines.index(line)
    return i + 1 < len(lines) and re.match(r"^\|[-|: ]+\|$", lines[i + 1]) is not None


def traced(text: str) -> list[str]:
    """The sections the trace covers: its `## N. Title` headings, and `## N.M. Title` for an item
    of a section (and the items under it) that joins before the rest of its section."""
    return re.findall(r"^## (\d+(?:\.\d+)*)\. ", text, re.M)


def traced_units(key: str) -> list[tuple[str, str]]:
    """The sentences and table rows a heading of the trace covers: a whole section's, or one
    item's and its sub-items'."""
    number = int(key.split(".")[0])
    units = section_units(reqdocs.section(number), number)
    if "." not in key:
        return units
    return [(rid, u) for rid, u in units if rid == f"R{key}" or rid.startswith(f"R{key}.")]


def trace_rows(text: str, key: int | str) -> list[tuple[str, str, list[str]]]:
    sec = text[text.index(f"\n## {key}. ") + 1 :]
    out = []
    for line in sec.split("\n")[1:]:  # after the section's own heading
        if line.startswith("## "):
            break
        m = re.match(r"^\| (R(?:\d+\.)+\d+) \| (.+?) \| (.+?) \|$", line)
        if m:
            shown = [t.strip() for t in m.group(3).split(",")]
            out.append((m.group(1), m.group(2).replace("\\|", "|"), shown))
    return out


def _test_names() -> set[str]:
    names = set()
    for f in os.listdir(os.path.join(ROOT, "tests")):
        if f.endswith(".py"):
            names |= set(re.findall(r"^def (test_\w+)", _read(os.path.join("tests", f)), re.M))
    return names


def _shown_well(tok: str, tests: set[str]) -> bool:
    return (
        tok == "statement"
        or (tok.startswith("test_") and tok in tests)
        or (tok.startswith("tier 3: ") and len(tok) > len("tier 3: "))
        or re.fullmatch(r"later: #\d+", tok) is not None
    )


def test_every_sentence_of_a_traced_section_has_a_row_and_every_row_its_sentence():
    trace = _read(TRACE)
    for number in traced(trace):
        units = traced_units(number)
        assert units, f"the trace has ## {number}., and R{number} has no sentences"
        rows = trace_rows(trace, number)
        unmatched = [
            (rid, u[:70])
            for rid, u in units
            if not any(r == rid and u.startswith(_norm(a)) for r, a, _ in rows)
        ]
        assert not unmatched, f"sentences of R{number} with no row in {TRACE}:\n" + "\n".join(
            f"  {rid}: {u}" for rid, u in unmatched
        )
        dangling = [
            (r, a)
            for r, a, _ in rows
            if not any(rid == r and u.startswith(_norm(a)) for rid, u in units)
        ]
        assert not dangling, "rows whose sentence changed or went (update them):\n" + "\n".join(
            f"  {r}: {a}" for r, a in dangling
        )


def test_every_row_names_tests_that_exist_or_says_why_not():
    trace, tests = _read(TRACE), _test_names()
    bad = [
        f"{rid} {anchor[:40]!r}: {tok}"
        for number in traced(trace)
        for rid, anchor, shown in trace_rows(trace, number)
        for tok in shown
        if not _shown_well(tok, tests)
    ]
    assert not bad, "rows naming what isn't there:\n  " + "\n  ".join(bad)


def test_a_section_splits_into_its_sentences_and_table_rows():
    sec = (
        "# R9. Genres\n\nR9.1. **Several.** Each song has one genre or several. It shows each "
        "of them, in order.\n\n"
        "R9.2. Kept as tags:\n\n| Kind | How |\n|---|---|\n| ID3 | `TCON` |\n"
    )
    assert section_units(sec, 9) == [
        ("R9.1", "Each song has one genre or several."),
        ("R9.1", "It shows each of them, in order."),
        ("R9.2", "| ID3 | TCON |"),
    ]


def test_a_rows_test_names_a_test_a_check_by_hand_or_a_later_issue():
    tests = {"test_a_song_has_genres"}
    for tok in ("test_a_song_has_genres", "statement", "tier 3: media keys", "later: #4"):
        assert _shown_well(tok, tests), tok
    for tok in ("test_missing", "tier 3: ", "later: 4", "claim"):
        assert not _shown_well(tok, tests), tok


def test_a_heading_traces_a_whole_section_or_one_item_and_those_under_it():
    text = "intro\n## 2.5. Songs\n| R2.5.1 | A song | statement |\n## 13. Sort\n## 2.13. X\n"
    assert traced(text) == ["2.5", "13", "2.13"]
    assert trace_rows(text, "2.5") == [("R2.5.1", "A song", ["statement"])]
    item = traced_units("2.5")
    assert item and {rid for rid, _ in item} <= {"R2.5", "R2.5.1", "R2.5.2", "R2.5.3", "R2.5.4"}
    assert {rid for rid, _ in traced_units("2.1")} >= {"R2.1", "R2.1.1"}
    assert not any(rid.startswith("R2.13") for rid, _ in traced_units("2.1"))
    assert len(traced_units("2")) > len(item)


def test_the_sections_are_read_whatever_their_names_padding():
    assert reqdocs._number("R01-platform-and-architecture.md") == [1]
    assert reqdocs._number("R12.04-name.md") == [12, 4]
    assert "R1.1. " in reqdocs.section(1)
    assert "R19.1. " in reqdocs.section(19) and "R1.1. " not in reqdocs.section(19)
