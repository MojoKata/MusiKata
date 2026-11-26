"""MusiKata's areas, the same as the repository's `area:` labels: which code and which test files
each holds. Coverage is totalled and floored by area (scripts/coverage_report.py), mutation runs are
planned and recorded by area (scripts/mutate.py), and a review's steps are its areas
(docs/process/testing.md). tests/test_areas.py holds every module, script and test file to exactly
one area.

    area_of_code("src/musikata_core/audio/eq.py") == "playback"
    area_of_test("tests/test_tags_id3.py") == "tags"

Run as a script, it prints the areas one per line, in AREAS' order.

Paths are from the repository's root, with "/". A pattern is an fnmatch one, so `*` crosses folders.
The modules and their areas are docs/architecture/A1-overview.md's A1.9, which tests/test_areas.py
holds this file to. A test file is named for its area (tests/test_<area>_<subject>.py), so a new one
needs no line here."""

import fnmatch

# every area; docs and tooling hold tests but no code coverage.py measures
AREAS = (
    "library",
    "tags",
    "files",
    "playback",
    "analysis",
    "online",
    "app",
    "qml",
    "scripts",
    "docs",
    "tooling",
)

CORE = "src/musikata_core"


def _core(*subjects):
    """A subject of the core, as a module or a package: tags.py, or tags/ and what is in it."""
    return [p for n in subjects for p in (f"{CORE}/{n}.py", f"{CORE}/{n}/*.py")]


CODE = {
    # A2: the index, the scan and watching, search, folders, the root's own files and finding a
    # root's index, what's playing kept, settings, the worker processes; and the package's
    # __init__, read everywhere
    "library": [
        f"{CORE}/__init__.py",
        *_core(
            "db",
            "scanner",
            "albums",
            "sortnames",
            "watch",
            "inotify",
            "search",
            "folders",
            "attention",
            "duplicates",
            "rootfiles",
            "roots",
            "nowplaying",
            "settings",
            "workers",
            "clock",
        ),
    ],
    # A3, R4, R5, R17: what is written into the files: tags, encodings, covers, lyrics
    "tags": _core("tags", "encodings", "art", "genres", "lyrics"),
    # R3, R8, R12, A3.5: how files are named, listed, moved and renamed, and Undo
    "files": _core("patterns", "playlists", "organize", "history"),
    # A4: decoding, joins, gain, the equalizer and the limiter, the queue
    "playback": _core("audio"),
    # A5: waveforms and spectra
    "analysis": _core("analysis"),
    # A7: the HTTP client and each service
    "online": _core("online", "update"),
    # the app's Python: models, bridges, the sound device and media controls (A4.5), the tour
    "app": ["src/musikata/*.py"],
    # QML, which coverage.py doesn't measure: the area holds its files, without a figure
    "qml": ["src/musikata/qml/*"],
    "scripts": ["scripts/*.py"],
}

TESTS = {area: [f"tests/test_{area}_*.py"] for area in AREAS}
TESTS["docs"] += [
    "tests/test_doccheck.py",
    "tests/test_public_text.py",
    "tests/test_requirements_trace.py",
]
TESTS["scripts"] += [
    "tests/test_publish.py",
    "tests/test_pins_newest.py",
    "tests/test_coverage_*.py",
    "tests/test_hardening.py",
    "tests/test_mutate.py",
]
TESTS["tooling"] += ["tests/test_areas.py", "tests/test_skip_lists.py", "tests/test_repo_admin.py"]


def _area(table, rel):
    found = [a for a, patterns in table.items() for p in patterns if fnmatch.fnmatchcase(rel, p)]
    return found[0] if len(set(found)) == 1 else None


def area_of_code(rel):
    """The area a source file or script counts in, or None (not code an area holds, or in two)."""
    if rel.startswith("src/musikata/qml/"):
        return "qml"
    return _area(CODE, rel)


def area_of_test(rel):
    """The area a test file (or a test's id, tests/test_x.py::test_y) belongs to, or None."""
    return _area(TESTS, rel.split("::")[0])


if __name__ == "__main__":
    print("\n".join(AREAS))
