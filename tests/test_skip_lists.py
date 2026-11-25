"""The tests each run may skip (tests/conftest.py, tests/skips/; docs/process/testing.md, "What each
run may skip"): the verdict on a test's report, that each run's script runs against a list, and that
each list names tests that exist, each with its reason.

Why: the lists only work while their check does. If the verdict broke, an unlisted skip would pass
again, and a test that exists for one platform (MPRIS on Linux, the media controls on Windows or
macOS, A4.5) could skip on that very platform unnoticed, which is what the lists are for."""

import glob
import os
import re

import conftest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LISTS = sorted(
    os.path.basename(p)[:-4] for p in glob.glob(os.path.join(ROOT, "tests", "skips", "*.txt"))
)


def test_a_skip_the_list_doesnt_name_fails_and_so_does_a_listed_test_that_ran(
    monkeypatch, tmp_path
):
    (tmp_path / "t.txt").write_text(
        "# a run\ntests/test_a.py::test_listed  # needs Windows\ntests/test_b.py  # no PySide6\n"
    )
    monkeypatch.setattr(conftest, "SKIPS", str(tmp_path))
    conftest.listed.cache_clear()
    try:
        v = conftest.verdict
        assert v("t", "tests/test_a.py::test_listed", True, "needs Windows", False) is None
        assert v("t", "tests/test_a.py::test_other", False, "", True) is None
        assert v("t", "tests/test_b.py", True, "no PySide6", False) is None
        assert v("t", "tests/test_a.py::test_other", True, "no network", False) == (
            "skipped, and tests/skips/t.txt doesn't list it:\n"
            "tests/test_a.py::test_other  # no network"
        )
        assert v("t", "tests/test_a.py::test_listed", False, "", True) == (
            "tests/skips/t.txt lists it as a skip, and it ran: take it off the list"
        )
        assert v("none", "tests/test_a.py::test_listed", True, "x", False).startswith("skipped")
    finally:
        conftest.listed.cache_clear()


def test_tier_1_runs_against_its_list_and_every_run_has_one():
    with open(os.path.join(ROOT, "scripts", "test-tier1.sh")) as f:
        text = f.read()
    assert "pytest" in text and "MUSIKATA_SKIPS" in text, "test-tier1.sh runs without a list"
    assert {"tier1", "windows", "macos"} <= set(LISTS)


def test_each_listed_test_exists_and_says_why_it_may_skip():
    for name in LISTS:
        conftest.listed.cache_clear()
        for test, why in conftest.listed(name).items():
            path, _, rest = test.partition("::")
            assert os.path.isfile(os.path.join(ROOT, path)), f"{name}: {test}: no such file"
            func = re.sub(r"\[.*\]$", "", rest.split("::")[-1]) if rest else ""
            if func and func != "*":
                with open(os.path.join(ROOT, path)) as f:
                    source = f.read()
                assert re.search(rf"^\s*(async )?def {re.escape(func)}\(", source, re.M), (
                    f"{name}: {test}: no such test"
                )
            assert why, f"{name}: {test} says no reason"
    conftest.listed.cache_clear()


def test_each_listed_case_is_one_pytest_collects():
    # A case's id after the test's name, [...], is pytest's making, and a pytest update can rename
    # it; the check above drops the [...]. Every file pytest collected this run is held to it.
    have = conftest.collected
    assert "tests/test_skip_lists.py::test_each_listed_case_is_one_pytest_collects" in have
    files = {t.split("::")[0] for t in have}
    for name in LISTS:
        conftest.listed.cache_clear()
        for test in conftest.listed(name):
            if test.endswith("]") and test.split("::")[0] in files:
                assert test in have, f"tests/skips/{name}.txt: {test}: pytest collects no such case"
    conftest.listed.cache_clear()


def test_every_test_one_run_skips_another_runs():
    """Each run takes tests/ whole, so a test every list names is one no run ever runs."""
    conftest.listed.cache_clear()
    every = {t for n in LISTS for t in conftest.listed(n)}
    never = sorted(t for t in every if all(conftest.allows(n, t) for n in LISTS))
    conftest.listed.cache_clear()
    assert never == [], "skipped by every run"


def test_a_listed_name_covers_each_case_of_a_parametrized_test(monkeypatch):
    """A parametrized test's cases have ids with their parameters ("…[1-1-True]"), which a list
    line naming the test doesn't spell out: the test's name alone covers its cases, and no other
    test."""
    monkeypatch.setattr(conftest, "listed", lambda name: {"tests/test_a.py::test_x": "why"})
    assert conftest.allows("windows", "tests/test_a.py::test_x[1-1-True]")
    assert conftest.allows("windows", "tests/test_a.py::test_x")
    assert not conftest.allows("windows", "tests/test_a.py::test_x_more[1]")
    assert not conftest.allows("windows", "tests/test_b.py::test_x[1]")


def test_every_test_has_a_home_of_its_own(tmp_path):
    """own_home (tests/conftest.py): "~" is this test's folder, not the real home."""
    assert os.path.expanduser("~") == str(tmp_path)
    assert os.environ["MUSIKATA_DATA"].startswith(str(tmp_path))
    assert os.path.expanduser("~") != conftest.REAL_HOME


def test_a_change_to_musikatas_files_in_a_home_is_seen(tmp_path):
    before = conftest.home_state(str(tmp_path))
    (tmp_path / ".musikata").mkdir()
    (tmp_path / ".musikata" / "settings.json").write_text("{}")
    apps = tmp_path / ".local" / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / "musikata.desktop").write_text("[Desktop Entry]\n")
    (apps / "other.desktop").write_text("[Desktop Entry]\n")
    changes = conftest.home_changes(before, conftest.home_state(str(tmp_path)))
    assert f"new: {tmp_path}/.musikata/settings.json" in changes
    assert f"new: {apps}/musikata.desktop" in changes
    assert not [c for c in changes if c.endswith("other.desktop")]
