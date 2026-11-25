"""Every module of src/ reaches MODULE_MIN before its code is ready (scripts/coverage_report.py;
docs/process/testing.md, "Coverage").

Why: an area's floor only stops it sliding back. A new module added to a well-covered area can
arrive half tested and hide behind its neighbours, so each module is also held to a minimum of its
own, lines and branches together as coverage.py counts them."""

import importlib.util
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location(
    "coverage_report", os.path.join(ROOT, "scripts", "coverage_report.py")
)
coverage_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coverage_report)
File = coverage_report.File


def _file(area, covered, missed, branches=0, taken=0):
    return File(area, set(range(covered)), set(range(covered, covered + missed)), branches, taken)


def test_a_module_counts_its_lines_and_branches_together():
    assert coverage_report.module_pct(_file("tags", 70, 10, 20, 10)) == 80.0
    assert coverage_report.module_pct(_file("tags", 0, 0)) is None


def test_a_module_of_src_under_the_minimum_is_named_unless_excepted():
    files = {
        "src/musikata_core/tags.py": _file("tags", 79, 21),
        "src/musikata_core/patterns.py": _file("files", 80, 20),
        "src/musikata/media/smtc.py": _file("app", 0, 50),
        "scripts/areas.py": _file("scripts", 10, 90),
    }
    excepted = {"src/musikata/media/smtc.py": "Windows only: measured in the Windows run"}
    assert coverage_report.modules_under(files, excepted) == [("src/musikata_core/tags.py", 79.0)]


def test_the_exceptions_file_lists_paths_with_their_reasons(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("# header\nsrc/musikata/media/smtc.py  # Windows only\n\n")
    assert coverage_report.exceptions(f) == {"src/musikata/media/smtc.py": "Windows only"}
    assert coverage_report.exceptions(tmp_path / "none.txt") == {}
