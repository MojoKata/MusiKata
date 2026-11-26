"""The tests a run may skip (docs/process/testing.md, "What each run may skip").

A run that sets MUSIKATA_SKIPS=<name> runs against tests/skips/<name>.txt, the tests it may skip and
why. A skip the list doesn't name is a failure, and so is a listed test that ran, so the list only
shrinks; each counts in the run's summary line. A run by hand, without MUSIKATA_SKIPS, checks
nothing. A run without a list yet fails on each skip, and each failure gives the line the list would
need.

How a skip slips past without it: a test that skips says why and the run still passes, and a run's
result is read as counts ("128 passed, 6 skipped"), so a test that exists for one platform (MPRIS on
Linux, the media controls on Windows or macOS, A4.5) can skip on that very platform unnoticed.

And every test's own home, below: `own_home`, and the check of MusiKata's files in the real one."""

import contextlib
import functools
import os
import re
import stat

import pytest
from hypothesis import settings

# Hypothesis (docs/process/testing.md, "Properties"): tier 1 tries a fixed 50 examples a property,
# so a run is fast and never flaky; HYPOTHESIS_PROFILE=deep, weekly and before a release, thousands
settings.register_profile("tier1", max_examples=50, derandomize=True, database=None)
settings.register_profile("deep", max_examples=5000, database=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "tier1"))

# Qt draws offscreen, as in tier 1's container: the windows the tests open need no display, and
# none shows on the desktop of whoever runs them
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


collected = set()  # every test id this run collected (tests/test_skip_lists.py)


def pytest_itemcollected(item):
    collected.add(case_id(item))


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
    _home_changed.extend(home_changes(_home_before, home_state()))
    if _modules or _home_changed:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter):
    if _modules:
        terminalreporter.section(
            f"{len(_modules)} failed: modules skipped whole, against tests/skips/", red=True
        )
        for line in _modules:
            terminalreporter.line(line)
    if _home_changed:
        terminalreporter.section(
            "MusiKata's files in the real home changed while the tests ran"
            " (a test wrote there, or another process did)",
            red=True,
        )
        for line in _home_changed[:40]:
            terminalreporter.line(line)


# ---- every test's own home ----
# A test that reads or writes "~" with the run's HOME reaches, on a developer's machine, their own
# MusiKata: the shared settings, the real library's index and caches, the log (R1.5). AppKata
# found its tests cloning into the real home and leaving launchers in its menu, and nothing said
# so. So each test's home is its own, and a run fails when MusiKata's files in the real one
# changed while it ran, whoever wrote them: a fixture of a wider scope, a thread or worker process
# a test left running, a test that set HOME back, or the MusiKata installed there playing music.
# The check can't tell which, so its heading says both. What other programs keep in the menu
# folder is theirs and doesn't count.
REAL_HOME = os.path.expanduser(
    "~"
)  # read as the suite loads, before any test has a home of its own
# MusiKata's folders in a home (R1.5), on every platform: all that is in them
OWNED = (
    ".musikata",
    ".local/share/musikata",
    ".cache/musikata",
    ".local/state/musikata",
    "Library/Application Support/MusiKata",
    "Library/Caches/MusiKata",
    "Library/Logs/MusiKata",
    "AppData/Local/MusiKata",
)
# what names a home's places, and where a home has each
OWN = {
    "HOME": "",
    "USERPROFILE": "",
    "XDG_DATA_HOME": ".local/share",
    "XDG_CONFIG_HOME": ".config",
    "XDG_CACHE_HOME": ".cache",
    "XDG_STATE_HOME": ".local/state",
    "APPDATA": "AppData/Roaming",
    "LOCALAPPDATA": "AppData/Local",
    "MUSIKATA_DATA": ".local/share/musikata",
}


@pytest.fixture(autouse=True)
def own_home(monkeypatch, tmp_path):
    """Every test's home is its tmp_path: HOME, USERPROFILE, the XDG and Windows folders and
    MUSIKATA_DATA each name the place a home has for it, under tmp_path, so what the test, or a
    program or worker process it starts, writes to "~" lands in the folder pytest gives it. Nothing
    is made there until something writes. A test that needs the real home says so, by setting HOME
    to conftest.REAL_HOME. The session bus is one that isn't there, so MusiKata never shows itself
    to the desktop running the tests (A4.5); a test of MPRIS starts a bus of its own."""
    for var, place in OWN.items():
        monkeypatch.setenv(var, os.path.normpath(os.path.join(str(tmp_path), place)))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/no-session-bus")


def _menu_entry(path):
    """Whether path is the menu entry the AppImage installs for itself (R1.4, A6.3)."""
    return os.path.basename(path) == "musikata.desktop"


# the folders of a home that MusiKata shares with other programs, and which entries of each are its
SHARED = {".local/share/applications": _menu_entry}


def home_state(home=REAL_HOME):
    """{path: (kind, size, modified)} of MusiKata's files in a home: all that is in its own folders
    (OWNED), and in the folders it shares (SHARED) its menu entry, not the folders themselves or
    what else is there. A link is itself, not what it names."""
    paths = []
    for top in OWNED:
        root = os.path.normpath(os.path.join(home, top))
        paths += [root] + [
            os.path.join(d, n) for d, dirs, files in os.walk(root) for n in dirs + files
        ]
    for top, ours in SHARED.items():
        folder = os.path.normpath(os.path.join(home, top))
        with contextlib.suppress(OSError):  # no such folder
            paths += [p for p in (os.path.join(folder, n) for n in os.listdir(folder)) if ours(p)]
    out = {}
    for path in paths:
        try:
            st = os.lstat(path)
        except OSError:  # not there, or gone since it was listed
            continue
        out[path] = (stat.S_IFMT(st.st_mode), st.st_size, st.st_mtime_ns)
    return out


def home_changes(before, after):
    """What differs between two states of a home, a line each: new, gone, changed."""
    kinds = (
        ("new", after.keys() - before.keys()),
        ("gone", before.keys() - after.keys()),
        ("changed", {p for p in before.keys() & after.keys() if before[p] != after[p]}),
    )
    return [f"{kind}: {path}" for kind, paths in kinds for path in sorted(paths)]


_home_before = home_state()
_home_changed = []  # the real home's changes over the run, which fail it (pytest_sessionfinish)
