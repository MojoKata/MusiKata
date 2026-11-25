# Testing

What runs when, on which environment. R1.1 promises only what these environments test: an
environment leaves this list, and R1.1, together.

## Principles

- **Most tests are unit tests** of the plain functions of [`coding.md`](coding.md) ("Built to be
  tested in isolation"), on generated data, each in milliseconds. A unit test never starts the app,
  a QML engine, a process or a device.
- **Fewer integration tests:** the scanner over the demo library, the models with a 50,000-row
  library, the worker pool, the audio chain into a null output. **The tour and tier 3** are for what
  nothing smaller can show.
- **Generated data, never real music** (A6.7), and no network or sound card (the end of "What tier
  1 covers").
- **Wait for the event, never for a set time.** Logic that runs on a clock is tested by moving a
  fake clock (`coding.md`). A test that must wait on real work (a worker process, a thread, the file
  watcher, a QML view loading, the tour) waits for the signal or state that says it is done
  (pytest-qt's `waitSignal` and `waitUntil`, or polling), under a generous timeout that only a
  failure ever reaches; it never sleeps a set time and hopes the work is finished. The one fixed
  wait is to show that nothing happens (no second rescan of MusiKata's own write, no request while
  lookups are off): it waits a set time, as short as the claim allows, then checks that nothing
  changed.
- **Speed.** A unit test runs in under 100 ms, or is marked `slow`. The rest, run by
  `pytest -m "not slow"`, take under 30 seconds, so they can run on every save; the whole of tier 1
  runs in under 5 minutes. Every run lists its slowest tests.
- **A bug fix starts with its test,** seen failing because of the bug, and both land in the same
  commit. **New code comes with its tests** and its trace rows in the same change, written before or
  after it as the piece suits.
- **Test names say the behaviour,** as a sentence: `test_a_seek_lands_on_the_exact_sample`.
- **The requirements trace.** `docs/requirements/trace.md` gives each sentence of a traced section a
  row naming the tests that show it, `tier 3:` and the check when only a person can show it, or
  `statement` when it promises nothing a test could show. A test fails when a sentence has no row, a
  row no longer matches its sentence, or a named test doesn't exist. A section joins the trace when
  its code is built, and every section of the first release (`DEVELOP.md`) is in it by that release.
- **Coverage.** Tier 1 runs under coverage.py, lines and branches, the worker processes included
  (`concurrency = ["thread", "multiprocessing"]`). Each area of `scripts/areas.py` (the core's
  `library`, `tags`, `audio` and `online`, the `app`, the `scripts`) has a floor in
  `tests/coverage-floor.json` that may only rise: a change that drops an area below its floor fails
  tier 1, and one that raises it moves the floor up in the same change, squashed into one commit
  ([`ci.md`](ci.md), "Coverage").
- **Mutation testing.** Once a first pass of the code is written, mutmut sweeps `musikata_core` for
  code the tests run but don't check; each survivor is killed by a new test or noted with the reason
  it isn't worth one. It isn't run as each piece is written; coverage is the measure until then
  ("Mutation testing", below).
- **Gates.** ruff and mypy ([`coding.md`](coding.md)) run in tier 1 beside the tests and the
  coverage floors.

## Tiers

| Tier | When | What it's for |
|---|---|---|
| 1 | every change | ruff, mypy and the whole pytest suite with its coverage floors, in one container on the release's Python and PySide6, offscreen: the gate for every commit, run by CI on every pull request and push to `main` |
| 2 | before pushing | the tour and its layout check at 100 % and 150 % text (R18.3), the size and speed targets of R1.11 on the demo library built at 50,000 songs, the AppImage built and started, the Windows suite in its VM |
| 3 | before a release | each platform's build installed and used by hand: playback through real speakers, media keys, drag and drop with the platform's file manager, the mini player moved, resized and kept on top, the platform's screen reader through every view (R18.1), the music root's drive unplugged and plugged back (R2.10), an update from the previous release (R1.9); the field test's checklist is `scripts/field_test.py`, run per environment before a release ([`release.md`](release.md), 4) |

### What each run may skip

Every pytest run a tier makes names its list of the tests it may skip, and why:
`tests/skips/<name>.txt`, chosen by `MUSIKATA_SKIPS=<name>` (`tests/conftest.py`). A skip the list
doesn't name is a failure, and so is a listed test that ran (take it off the list), so a run's
summary line counts both. The lists: `tier1` (CI's too), `windows` (the suite in the Windows VMs)
and `macos` (the suite on the Apple silicon runner). A test that exists for one platform, MPRIS on
Linux or the media controls on Windows and macOS (A4.5), is listed as a skip on the others, so it
can never skip unnoticed on its own. A run by hand, without `MUSIKATA_SKIPS`, checks nothing. A skip
that comes and goes with the machine (a tool missing from an image) is a fault of the run, not an
entry for the list.

## What tier 1 covers

- **Tags, per file kind.** For every kind of R2.2, a generated file is written and read back for
  every field of R4.1 (A3.2), with unknown frames, several genres, covers and ratings, and checked
  byte for byte against what other readers expect (`POPM` values, `TRCK` as `4/10`).
- **Safe writes** (A3.4): a write interrupted at each step leaves the original intact; a read-only
  file and a full disk are reported, not damaged.
- **Path patterns** (R3): a table of paths and patterns with the tags each should give, including
  the presets, the equivalences of R3.2.1, tidy case and year from folder; detection picking the
  right preset on folders of each layout.
- **Organize files** (R12): the layout's paths on Linux, Windows and macOS rules, conflicts,
  sidecar files, playlists updated, and Undo putting everything back.
- **Playlists** (R8): M3U and M3U8 read in every form R8.1.2 lists, written as R8.1 says, round
  trips that change nothing, missing entries and Find.
- **The library** (R2, A2): scans of the demo library, a second scan reading nothing, moves found by
  audio hash, search terms.
- **Folders** (R2.9, R5.8, A2.7): folder rows after scans, moves and deletes, up through the
  ancestors; the mosaic chosen for trees of every shape (1 to 5 subfolders, nested mosaics, no art
  anywhere); a selection of folders resolving to the songs beneath them.
- **The change history** (R4.9): every kind of save undone and redone, on one computer and from
  another.
- **Playback** (R7.6, R19, A4): joins between generated songs of known length are sample-exact,
  across sample rates and kinds, with MP3, AAC and Opus padding trimmed; seeking lands on the
  sample; the equalizer's measured response matches each preset's curve, for every band type;
  parametric to graphic and back gives the same bands; Equalizer APO files round-trip; nothing
  clips, and the level held down matches the preamp and the largest boost.
- **The root's own files** (A2.8, A2.9): two computers playing at once each write their own play
  file and the sums add up; `ignored.json` and `ratings.json` written at once lose nothing; a song
  moved in a file manager keeps its plays, rating and dismissal on the other computer; a read-only
  `.musikata` keeps everything in the index; a root mounted at another path finds its index, and a
  copy of a root gets its own.
- **Sort names** (R2.13): sort tags win, articles are skipped without them, and the sort tokens of
  R12.1 move the article to the end.
- **Sleep timer** (R7.10): each choice stops at its time or at the end of its song or album, the
  fade ends at silence, and the volume is back where it was.
- **Encodings** (R4.10): tags in each candidate encoding detected and fixed, and real Latin-1
  (French, German) never flagged.
- **Duplicates** (R2.12): exact and likely copies found, the best copy proposed, plays, ratings
  and playlists moved to it.
- **A missing music root** (R2.10): a root that vanishes, half vanishes or comes back, with the
  library kept and nothing removed without asking.
- **Accessibility** (R18): every QML control has an accessible name and role; every text token
  against every surface it is used on meets R18.4's contrast.
- **Online lookups** (R16, R17.4, A7): each service against recorded answers, errors and
  `Retry-After` included; release matching on albums with missing, extra and reordered songs;
  nothing requested while lookups are off; lyrics read from and written to `.lrc` files and every
  kind of tag (R17.1).
- **The analysis** (A5): peaks and bands of generated tones land where they should.
- **QML**: the models with a 50,000-row library; the views load with no QML warnings.

Tests never need the network or a sound card: playback tests use Qt's null audio output and check
positions and signals, and online lookups use recorded answers (A7.8). Only
`scripts/check-services.py`, run by hand and weekly in CI, talks to the real services.

## The clock harness

MusiKata's own code takes a clock ([`coding.md`](coding.md)), so its tests move a fake one.
`scripts/test-clock.sh` finds the test, or the library call, that reads the real clock anyway: it
runs tier 1 at the start, middle and end of the UTC day, at a year's end, in the zones furthest from
UTC either way (UTC+14 and UTC−12) and in US Central with its daylight saving time, each by
`scripts/test-tier1.sh` with `MUSIKATA_CLOCK` and `MUSIKATA_TZ`. libfaketime moves every process's
clock by an offset, so the clock still runs and the processes a test starts share it. A test that
passes at one hour and fails at another is a bug like any other: its fix starts with the run that
shows it. The harness runs before a release, and whenever a change touches dates, times or their
display ("last played", the 180-day cleanup of A2.9, the sleep timer).

## Environments

| Environment | Tier | Runs |
|---|---|---|
| Ubuntu 24.04 container | 1, 2 | the suite (CI too); the tour and its layout check |
| Ubuntu 22.04 container | 2 | the AppImage build, on the oldest glibc it supports |
| Linux Mint 22.3, LMDE 7, Ubuntu 26.04 | 2, 3 | the AppImage started on X11 and Wayland, MPRIS seen by the desktop |
| Windows 10 22H2 and Windows 11 VMs | 2, 3 | the installer, the suite on Windows, the tour, uninstall |
| macOS 14 or newer, Apple silicon (CI runner, and a real Mac) | 2, 3 | the arm64 bundle, the suite on macOS |
| macOS, Intel (the owner's Mac, on the newest macOS it runs) | 3 | the x86_64 bundle installed from the tap and used by hand |

## CI

GitHub Actions, each action pinned by commit SHA: tier 1 on every pull request and push to `main`;
the tour, with its screenshots kept as the run's artifact; the four builds (`appimage`, `windows`,
`macos-arm64`, `macos-x86_64`), unsigned, each with its `.sha256`; once a week,
`scripts/check-services.py` against the real services (A7.8), failing the run when one has changed.
A `v*` tag builds without caches and, once approved, signs the builds and drafts a release
([`build-and-release.md`](build-and-release.md)). Beside tier 1, CI measures coverage by area and
publishes the Pages site, and a failed step posts why ([`ci.md`](ci.md)).

## Mutation testing

[mutmut](https://github.com/boxed/mutmut) changes MusiKata's code one change at a time (a `<` for a
`<=`, a string emptied, a call's argument dropped) and runs the tests on each change. A change some
test fails on is **killed**; one every test passes with **survives**, and shows code the tests run
but don't check. It complements coverage, which says only that a line ran. The sweep is
`musikata_core`'s areas (`library`, `tags`, `audio`, `online`); mutmut can't change QML, and the
app's bridge code is mostly Qt's to run. The first sweep comes once a first pass of the code is
written, never as each piece is written.

`scripts/mutate.py` holds the tools. mutmut changes the code it tests, so a run never touches the
checkout: it works in a copy (`MUSIKATA_MUTATE_WORK`, `build/mutate` unless set) with `src/`,
`scripts/` and `tests/` copied and the rest of the repository linked, so the tests read it as in
tier 1. It runs in tier 1's container, on the release's Python and PySide6
(`scripts/test-mutate.sh`, mutmut pinned as `MUTMUT` in `packaging/versions.env`), with all of tier
1's tests but those `UNFIT` names, each with its reason. mutmut runs every test once first, noting
the functions each one reaches, then runs each change against only the tests that reached its
function. Code a test reaches only in a process it starts, a worker process included, is out of
mutmut's sight: its changes count as **no tests**, so a worker's job is tested by calling it
directly ([`coding.md`](coding.md)).

mutmut stops at the first test that fails in that first pass, without naming it. A run then runs
pytest over the copy and runs each test that fails there once more on the checkout. A test that
fails on the checkout too is a real failure, and stops the run; the others are left out of the run,
each named in its export with its traceback and the kind of failure it looks like, and settled
before a baseline is kept: added to `UNFIT` with its real reason, or the test changed so it doesn't
depend on the copy, never by weakening what it checks.

### A run by hand

```sh
sh scripts/test-mutate.sh run src/musikata_core/audio/eq.py --workers 3
sh scripts/test-mutate.sh summary            # the outcomes by file, the survivors by function
sh scripts/test-mutate.sh check CHANGE tests/test_audio_eq.py   # one change against one test file
```

A run's container is capped at `MUSIKATA_MUTATE_MEMORY` (6 GB unless set), swap included. The run
watches its own memory: past `--limit` GB it stops, and a change's worker past `--worker-limit` GB
of its own is stopped, that change counted killed. `--only` runs named changes again, `--debug` puts
each of mutmut's pytest runs in its log, and `--resume DIR` goes on from an earlier run's `export`
folder.

### The baseline

The `mutate` workflow (`.github/workflows/mutate.yml`) runs the areas side by side on GitHub's
runners, started by hand (Actions, `mutate`, Run workflow):

- **`plan`** packs each area's modules (`scripts/areas.py`) into jobs of about `size` code lines
  (1000), the largest first; a larger module is a job of its own. Jobs are named by area (`tags-1`,
  `audio-2`), the same for the same tree, so `jobs` runs chosen ones again.
- **Each job** is a `run` of its modules with 4 workers, stopped before the runner's six hours so
  what finished is kept, and an `export`, kept as its `mutation-<job>` artifact for 90 days. At most
  `parallel` (14) run at once, leaving room for pull requests' checks.
- **`resume`**, an earlier run's id: each job runs only the changes its artifact there left without
  an outcome, so a job out of time goes on where it stopped.

`scripts/mutate.py gather RUN...` downloads a run's artifacts and writes each area's baseline and
survivors to `docs/hardening/mutation/` ([`../hardening/README.md`](../hardening/README.md));
`record --from DIR...` does the same from a local run's `export` folders. Runs gathered together
must be of one commit, and a later run's outcome for a change replaces an earlier one's.
`scripts/mutate.py stale` names each module whose content (its git blob) isn't what its area's
latest record mutated, and each module an area holds that no record covers; the hardening page
([`ci.md`](ci.md), "The Pages site") marks those areas "baseline, changed since".

The baseline records the survivors; it doesn't settle them. Each area settles its own by the shared
`mutation` skill (`agents/skills/mutation/SKILL.md`): a test that fails on the change, a change to
the code, or `# pragma: no mutate` on the line with the reason it can't be caught (an equivalent
change, say). An area with more than about 200 survivors is settled in a relay. A settled area runs
again (`jobs`) and its baseline is gathered again.
