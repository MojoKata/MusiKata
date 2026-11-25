"""Every module, script and test file is in exactly one area (scripts/areas.py), so each counts in
one area's coverage and one area's mutation record, and the areas are the repository's `area:`
labels.

How it would slip past: a new module or test file in no area's list is left out of every area's
total, with nothing to say so."""

import glob
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location(
    "musikata_areas", os.path.join(ROOT, "scripts", "areas.py")
)
areas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(areas)


def _files(*patterns):
    out = []
    for p in patterns:
        out += [
            os.path.relpath(f, ROOT).replace(os.sep, "/")
            for f in glob.glob(os.path.join(ROOT, p), recursive=True)
        ]
    return sorted(
        f for f in out if os.path.isfile(os.path.join(ROOT, f)) and "__pycache__" not in f
    )


def test_every_module_and_script_is_in_one_area():
    code = _files("src/**/*.py", "src/musikata/qml/**/*", "scripts/*.py")
    assert "scripts/areas.py" in code
    assert [f for f in code if areas.area_of_code(f) is None] == []


def test_every_test_file_is_in_one_area():
    tests = _files("tests/test_*.py")
    assert [f for f in tests if areas.area_of_test(f) is None] == []
    assert areas.area_of_test("tests/test_tags_id3.py::test_x[1]") == "tags"


def test_each_pattern_is_under_the_code_or_the_tests_and_the_areas_are_the_area_values():
    # The core's subjects (A1.2) are named before their code is written, as a module or a package,
    # so a pattern may match nothing yet; what each file is in is checked above.
    for table, tops in ((areas.CODE, ("src/", "scripts/")), (areas.TESTS, ("tests/test_",))):
        assert set(table) <= set(areas.AREAS)
        for area, patterns in table.items():
            assert all(p.startswith(tops) for p in patterns), area
    assert len(areas.AREAS) == len(set(areas.AREAS))


def test_a_file_in_two_areas_is_in_none():
    assert areas._area({"a": ["x/*.py"], "b": ["x/y.py"]}, "x/y.py") is None
    assert areas._area({"a": ["x/*.py", "x/y.py"]}, "x/y.py") == "a"


def test_a_core_subject_is_a_module_or_a_package():
    assert areas.area_of_code("src/musikata_core/tags.py") == "tags"
    assert areas.area_of_code("src/musikata_core/audio/eq.py") == "playback"
    assert areas.area_of_code("src/musikata_core/organize.py") == "files"
    assert areas.area_of_code("src/musikata_core/analysis/peaks.py") == "analysis"
    assert areas.area_of_code("src/musikata/qml/NowPlaying.qml") == "qml"
    assert areas.area_of_code("src/musikata_core/unheard_of.py") is None


def test_run_it_prints_the_areas_one_per_line():
    out = subprocess.run(
        [sys.executable, "-B", os.path.join(ROOT, "scripts", "areas.py")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out == "".join(f"{a}\n" for a in areas.AREAS)
