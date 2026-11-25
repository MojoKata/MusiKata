"""The tests a run may skip (docs/process/testing.md, "What each run may skip").

A run that sets MUSIKATA_SKIPS=<name> runs against tests/skips/<name>.txt, the tests it may skip and
why. A skip the list doesn't name is a failure, and so is a listed test that ran, so the list only
shrinks; each counts in the run's summary line. A run by hand, without MUSIKATA_SKIPS, checks
nothing. A run without a list yet fails on each skip, and each failure gives the line the list would
need.

How a skip slips past without it: a test that skips says why and the run still passes, and a run's
result is read as counts ("128 passed, 6 skipped"), so a test that exists for one platform (MPRIS on
Linux, the media controls on Windows or macOS, A4.5) can skip on that very platform unnoticed."""

import functools
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIPS = os.path.join(ROOT, "tests", "skips")


@functools.cache
def listed(name):
    """{test id: why it may skip} of a run's list: a line per test, the reason after "  # "."""
    path = os.path.join(SKIPS, name + ".txt")
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    test, _, why = line.rstrip("\n").partition("  # ")
                    out[test.strip()] = why.strip()
    return out


def case_id(item):
    """A test's id from the repository's root, whichever folder a run starts pytest from."""
    return (
        os.path.relpath(str(item.path), ROOT).replace(os.sep, "/")
        + "::"
        + item.nodeid.partition("::")[2]
    )


def allows(name, test):
    """Whether run name's list names test: by its id, by its name without the [parameters] (every
    case of a parametrized test), or as <file>::* (every test of a file the run skips whole, the
    Windows run's Linux-only ones)."""
    entries = listed(name)
    return (
        test in entries or test.split("[")[0] in entries or test.split("::")[0] + "::*" in entries
    )


def verdict(name, test, skipped, why, ran):
    """Why a test's report fails run name's list, or None: a skip it doesn't list, a listed test
    that ran."""
    if skipped and not allows(name, test):
        return f"skipped, and tests/skips/{name}.txt doesn't list it:\n{test}  # {why}"
    if ran and allows(name, test):
        return f"tests/skips/{name}.txt lists it as a skip, and it ran: take it off the list"
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    name = os.environ.get("MUSIKATA_SKIPS")
    if not name or hasattr(report, "wasxfail"):
        return
    why = ""
    if report.skipped:
        why = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        why = " ".join(re.sub(r"^Skipped: ", "", why).split())
    failed = verdict(
        name, case_id(item), report.skipped, why, report.when == "call" and report.passed
    )
    if failed:
        report.outcome, report.longrepr = "failed", failed


_modules = []  # each module skipped whole, which no test report carries, that the list doesn't name


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    report = (yield).get_result()
    name = os.environ.get("MUSIKATA_SKIPS")
    if name and report.skipped and isinstance(collector, pytest.Module):
        module = os.path.relpath(str(collector.path), ROOT).replace(os.sep, "/")
        why = " ".join(re.sub(r"^Skipped: ", "", report.longrepr[2]).split())
        failed = verdict(name, module, True, why, False)
        if failed:
            _modules.append(failed)


def pytest_sessionfinish(session, exitstatus):
    if _modules:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter):
    if _modules:
        terminalreporter.section(
            f"{len(_modules)} failed: modules skipped whole, against tests/skips/", red=True
        )
        for line in _modules:
            terminalreporter.line(line)
