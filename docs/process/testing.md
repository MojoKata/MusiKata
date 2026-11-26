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
- **Generated data, never real music** (A6.7), and no network or sound card (the end of "What tier 1
  covers"). Each test has a home of its own (`own_home`, `tests/conftest.py`): `HOME`, the XDG and
  Windows folders and `MUSIKATA_DATA` point into its temporary folder, and a run fails when
  MusiKata's files in the real home changed while it ran.
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
  row naming the tests that show it, `tier 3:` and the check when only a person can show it, `later:
  #n` when it waits on a `future` issue, or `statement` when it promises nothing a test could show.
  A test fails when a sentence has no row, a row no longer matches its sentence, or a named test
  doesn't exist. A section joins the trace when its code is built, and every section of the first
  release (`DEVELOP.md`) is in it by that release.
- **Coverage.** Tier 1 runs under coverage.py, lines and branches, the worker processes included
  (`concurrency = ["thread", "multiprocessing"]`). Each area of `scripts/areas.py` (the core's
  `library`, `tags`, `files`, `playback`, `analysis` and `online`, the `app`, the `scripts`) has a
  floor in `tests/coverage-floor.json` that may only rise: a change that drops an area below its
  floor fails tier 1, and one that raises it moves the floor up in the same change, squashed into
  one commit ([`ci.md`](ci.md), "Coverage").
- **Each module at 80 % before it is ready.** A module of `src/` isn't ready, and its pull request
  doesn't merge, until its tests reach 80 % of it, its lines and branches counted together as
  coverage.py counts them. An area's floor only stops it sliding back, and a new module could
  otherwise arrive half tested and hide behind its neighbours. `coverage_report.py --check` fails on
  a module under 80 %, unless `tests/coverage-exceptions.txt` names it with the reason (a module
  that runs only on Windows or macOS, measured in that platform's run).
- **Data from outside is tested in its real shapes.** A module that reads data it didn't write
  lists, under "Shapes" below, what varies in that data and the test that covers each
  ([`coding.md`](coding.md), "Data from outside: its shapes"), before its code is ready. Missing
  fields, fields in another order, other programs' conventions and older versions' files are where
  most bugs in such code come from, and they are cheaper to list than to find by mutation.
- **Properties, with Hypothesis.** Where a rule holds for every input, a property states it and
  Hypothesis tries inputs: the parsers of outside files never fail but with their own error,
  whatever bytes they get; round trips change nothing (a path made from tags and read back, an M3U
  written and read); invariants hold (the equalizer's output stays under full scale, play files
  merged in any order sum the same, unknown fields survive a rewrite). In tier 1 each property runs
  a fixed set of about 50 examples (`derandomize`), so it is fast and never flaky; a weekly CI run
  and one before each release try thousands of random ones. A failing case found that way becomes an
  `@example` on its test, so it is checked on every run after.
- **Mutation testing.** Once a first pass of the code is written, mutmut sweeps `musikata_core` for
  code the tests run but don't check; each survivor is killed by a new test or noted with the reason
  it isn't worth one. It isn't run as each piece is written; coverage is the measure until then
  ("Mutation testing", below).
- **Gates.** ruff and mypy ([`coding.md`](coding.md)) run in tier 1 beside the tests and the
  coverage floors.

## Shapes

What varies in the data each module reads but didn't write ([`coding.md`](coding.md), "Data from
outside: its shapes"): the list it starts from, which the module's tests cover, each shape by a test
that names it. A module adds the shapes it meets; a bug found in a shape no test had is added here
with its test.

| Module | Its shapes |
|---|---|
| `tags` (A3.2, R4) | ID3v1 only, ID3v2.2, 2.3 and 2.4, and v1 and v2 that disagree; frames repeated or empty; several genres as separate frames, as `;` or `/` in one, or as ID3v1 numbers `(17)`; track as `4`, `04` or `4/10`; years as `2003`, `2003-05-01` or `TYER` with `TDAT`; Vorbis keys in any case and repeated; MP4 freeform atoms, and atoms that are a bool (`cpil`, `pgap`) or numbers (`tmpo`); `POPM` from Windows Media Player, MusicBee and foobar2000; Picard's MusicBrainz ids; the text encodings of R4.10 |
| `art`, `tags.pictures` (R5.1) | pictures embedded as ID3's `APIC`, FLAC's picture blocks, Vorbis comments' `METADATA_BLOCK_PICTURE` and the older `COVERART`, MP4's `covr` (no picture types; JPEG or PNG); several pictures with the front cover not first, none, an empty one, one that can't be decoded; a folder's images named `cover`, `folder`, `front` or `album` in any case and extension, other images (the largest wins), hidden ones and files that aren't images |
| `covers` (R5.1) | JPEG, PNG with and without transparency, WebP; wide, tall, and smaller than a thumbnail; bytes that aren't an image, a cover file gone, a song whose pictures can't be read; a cached thumbnail cut short; a cache folder that can't be written |
| `playlists` (R8.1.2) | absolute and relative paths, `\` and `/`, `file://` URLs; `#EXTINF` and without; a BOM, CRLF, `.m3u` in the system's encoding; comments and blank lines; files missing, outside the root, or listed twice |
| `lyrics` (A7.6, R17) | times as `[mm:ss]`, `[mm:ss.xx]` and `[mm:ss.xxx]`, several on one line; `[ar:]`, `[ti:]` and `[offset:]`; lines out of order, blank, or untimed; word times `<mm:ss.xx>`; a BOM and CRLF |
| `attention` (`.cue`) | `FILE` with and without quotes; the sheet in UTF-8 or the system's encoding; `REM` lines; `INDEX 00` and `01` |
| `audio` (`decode`, A4.1) | every kind of R2.2; samples of 8, 16, 24 and 32 bits, float and double, packed and planar; mono, stereo, quad, 5.1 and 7.1, and a WAV that names no channels; rates from 8 to 192 kHz; a cover FFmpeg sees as a video stream; a damaged file, and damage FLAC's decoder hides; a file that ends early, and one cut before what it needs to open; an empty file, noise, a missing file and one with no audio |
| `audio.eq` (R19.7) | with and without `Preamp:`; filters `ON` and `OFF`; `PK`, `LSC`, `HSC`, `LP`, `HP` and types it doesn't read; `Fc` with and without `Hz`; `Q` against `BW`; comments; more than ten bands |
| `online` (A7) | fields missing, `null`, empty or added; dates as a year, a month or a day; several matching releases; answers `503` and `429`; slow answers; text in any script |
| `rootfiles`, `settings` (A2.10) | each older format, and a newer one; unknown fields and groups; values broken or out of range (R13.9); two computers' entries for one song; a file cut short by a sync in progress; a sync tool's "conflicted copy" beside it |
| `search` (R2.7, A2.5) | what users type: accents and case (`beyonce`, `MOTLEY crue`); the last word half typed; quotes closed, left open, empty or inside a word (`12"`); FTS5's own operators and marks as text (`OR`, `NOT`, `NEAR(`, `*`, `^`, `-`, `{}`, `:`); a lone `-` and other marks with no word in them; a known `field:` in any case, with no value yet, a word, a phrase or a comparison (`rating:>=4`, `rating:>= 4`, `=>`, `≥`, `rating:4`, `year:<2000`, `year:201`), and a comparison with no number (`rating:high`); an unknown `field:` (`bpm:120`); a NUL; nothing, and anything at all (a property) |
| `patterns` (R3) | odd characters, deep and shallow folders, numbers in names, `Disc 1` folders, names longer than a platform allows |

## Tiers

| Tier | When | What it's for |
|---|---|---|
| 1 | every change | ruff, mypy and the whole pytest suite with its coverage floors, in one container on the release's Python and PySide6, offscreen: the gate for every commit, run by CI on every pull request and push to `master` |
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

Tests never need the network or a sound card: playback tests play into a null output and check
positions and signals, and online lookups use recorded answers (A7.8). Qt has no null output of its
own, so tier 1's container runs PulseAudio with a null sink (`scripts/test-tier1.sh`); a run by hand
without one skips the playback tests rather than play tones through the speakers. Only
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
| Windows 10 22H2 VM | 2, 3 | the installer, the suite on Windows, the tour, uninstall |
| Windows 11 VM | 2 | the installer, the suite on Windows, the tour, uninstall: what can be automated, and never a field test |
| macOS 14 or newer, Apple silicon (CI runner, and a real Mac) | 2, 3 | the arm64 bundle, the suite on macOS |
| macOS, Intel (the owner's Mac, on the newest macOS it runs) | 3 | the x86_64 bundle installed from the tap and used by hand |

## CI

GitHub Actions, each action pinned by commit SHA: tier 1 on every pull request and push to `master`;
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
`musikata_core`'s areas (`library`, `tags`, `files`, `playback`, `analysis`, `online`); mutmut can't
change QML, and the app's bridge code is mostly Qt's to run. The first sweep comes once a first pass
of the code is written, never as each piece is written.

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
