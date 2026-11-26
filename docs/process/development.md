# Development

## The repository's layout

```
src/musikata_core/   no GUI: the modules of A1.9 (db, scanner, tags, patterns, audio, …), schemas/ (A2.10)
src/musikata/        the app (A1.9): QML (qml/), models, bridges, the player, media controls, the tour
tests/               pytest: unit tests per core module, QML tests, the tour's layout checks
scripts/             build, test and demo scripts (shell and Python)
packaging/           versions.env, qt-modules.txt, the Windows installer script, macOS bundle files, icons
docs/requirements/   what MusiKata does (R1 …)
docs/architecture/   why it is built so (A1 …)
docs/process/        how it is worked on (this folder)
docs/mockups/        the design mockups, and src/render.py that draws them
DEVELOP.md           where the build stands, and the short version of running from source
```

## Running from source

For development only; MusiKata is installed from its release (R1.4). It runs on the Python its
release carries, which a script fetches, with every package at its pin (`packaging/versions.env`;
`--no-deps`, so nothing unpinned comes with them):

```sh
"$(scripts/python-standalone.sh)" -m venv .venv
(. packaging/versions.env && .venv/bin/pip install --no-deps -e . \
    "PySide6-Essentials==$PYSIDE" "PySide6-Addons==$PYSIDE" "shiboken6==$PYSIDE" $RUNTIME \
    $PYTEST $COVERAGE $RUFF $MYPY $HYPOTHESIS $JSONSCHEMA)
.venv/bin/musikata                     # or: .venv/bin/python -m musikata
.venv/bin/python -m pytest -m "not slow"   # the fast set, under 30 seconds: on every save
.venv/bin/ruff format && .venv/bin/ruff check && .venv/bin/mypy
.venv/bin/python -m pytest             # all of tier 1's tests
```

`MUSIKATA_DATA` points the database and caches at another folder, so a development copy never
touches the real library's index; `MUSIKATA_DEBUG=1` adds debug lines to the log (R14.5).

## Before each commit

```sh
scripts/check.sh                  # under a minute; stops at the first step that fails
scripts/check.sh --install-hook   # once per clone, if you want git to run it before each commit
```

It runs what tier 1 would fail on that can be checked in seconds: `ruff format --check` and `ruff
check` (their settings are `pyproject.toml`'s), mypy on `src/`, `scripts/doccheck.py`, the
private-names check over every file git tracks or would add, and the fast tests (`pytest -m "not
slow"`). It uses `.venv`, or the environment `MUSIKATA_VENV` names. The hook is opt-in, per clone;
`git commit --no-verify` skips it.

## The demo library

Real music is never committed, used in tests or shown in screenshots. `scripts/demo_library.py`
makes one (A6.7):

```sh
.venv/bin/python scripts/demo_library.py build build/demo      # every kind of R2.2, tagged
.venv/bin/python scripts/demo_library.py build build/big --songs 50000   # at R1.11's size
MUSIKATA_DATA=build/demo/data .venv/bin/musikata --root build/demo/Music
```

Its artists and albums are the mockups' (made up), and some of its files are wrong on purpose:
missing years, lower-case artists, "Electronica" beside "Electronic", an album without a cover,
loose files in `_Incoming`, a playlist naming a file that isn't there. Needs attention, R3 and R12
always have work to show on it. Its folders are deep enough for every kind of folder cover (R5.8):
an artist with one album, artists with two, three and five, and a `Remixes` folder of albums inside
an artist's folder, whose mosaic takes its pieces from a level further down.

## The tour

```sh
MUSIKATA_DATA=build/demo/data .venv/bin/musikata --root build/demo/Music --tour build/tour
scripts/test-tour.sh       # the same in tier 1's container, as CI runs it; makes build/demo first
```

drives the real app through each screen of the mockups and saves `build/tour/<screen>.png` at the
mockups' 1280 × 800, offscreen, so it runs over SSH and in containers (A1.6). It checks every
visible text against the box it is drawn in, at that size and at the design point (R6.2.1), and
fails on text that runs past it, naming each in `build/tour/layout.txt`. `--tour-only L03-songs`
takes the screens named. In the container the demo library is the home's `Music`, so the screens
show `~/Music`, as CI's and the site's do.

## Redrawing the mockups

```sh
python docs/mockups/src/render.py            # every screen
python docs/mockups/src/render.py L01 T01    # those whose names contain L01 or T01
```

It needs PySide6 and Pillow, and draws with the fonts installed (the committed ones use Noto
Sans). Look at each changed PNG before committing it.
