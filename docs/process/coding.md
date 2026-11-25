# Coding

How MusiKata's code is written. How it is tested is [`testing.md`](testing.md); why each part is
built as it is, [`../architecture/`](../architecture/README.md).

## Built to be tested in isolation

Every piece is shaped so its logic can be tested in milliseconds, without the app, a window, a
device or the network. A piece that can only be shown working by starting MusiKata is shaped
wrongly.

- **Plain functions over plain data.** The logic takes and returns arrays, bytes, numbers,
  strings, dicts and dataclasses, with no Qt, file, device, network or clock inside. The waveform
  is `peaks(samples: ndarray, n: int) -> ndarray`, tested on generated sine waves and noise;
  decoding a file only feeds it (A5.1). The same holds for:
  - the equalizer: bands to a filter, the filter applied to a block, the headroom and the limiter
    (A4.4);
  - joining songs: trimming encoder padding, resampling, the ramps (A4.2);
  - the spectrum's bands (A5.2) and the landscape's projection (A5.3);
  - the path pattern engine (A3.3), sort names (R2.13) and the Organize layout (R12);
  - the root's own files: merging play files, matching entries by path and then hash (A2.8), and
    finding a root's index (A2.9);
  - scoring encodings (A3.6), matching a release (A7.4), parsing LRC (A7.6), reading and writing
    M3U (R8);
  - the queue and shuffle (R7.2, R7.3) and the sleep timer's arithmetic (R7.10).
- **Thin edges, passed in.** What touches the outside world is a small interface the logic is
  given, never one it reaches for: the file walker and the tag reader (A2.2), the decoder and the
  sound device (A4.1), the HTTP client (A7.1), the database connection, and the clock. Tests give
  it fakes: a walker over a dict, a decoder that yields generated blocks, a device that collects
  what it is sent, recorded answers.
- **No test waits on real time.** Whatever depends on time takes a clock: the sleep timer and its
  fade, the minute between play-file writes (A2.8), the 180-day cleanup (A2.9), the services' pace
  (A7.2), watching's one-second gathering (A2.4). A test moves the clock instead of sleeping.
- **QML only lays out and binds.** What a view shows and what a click does are decided by a Python
  model or bridge object, tested without a window. A condition in QML that a test would want to
  check belongs in Python.
- **Jobs are plain functions.** A job for the worker processes (A1.3) is a function of picklable
  arguments, tested by calling it directly; the pool that runs jobs is tested once, not per job.

## Layout and imports

- The two packages of A1.2: `musikata_core` imports `PySide6.QtCore` at most, never `QtGui`,
  `QtQuick` or `QtMultimedia`; `musikata` imports both. A test checks it.
- Each module of `musikata_core` has one subject (`tags`, `patterns`, `scanner`, `audio.eq`, …)
  and imports only the modules below it. There are no import cycles.
- Nothing runs at import: no file opened, thread started or setting read.

## Style and types

- **ruff** lints and formats, at 100 columns, with its rules in `pyproject.toml`: pyflakes,
  pycodestyle's errors, import order, bugbear, pyupgrade and simplify. `ruff format` settles the
  layout; nothing is formatted by hand. A finding or an unformatted file fails tier 1.
- **mypy** checks types in tier 1: `--strict` on `musikata_core`. In `musikata`, every function's
  parameters and return are typed, and the looseness the Qt bridge needs (`@Property`, `@Slot`,
  `Signal`) is allowed there and nowhere else. A `# type: ignore` names its error code and says
  why.
- Both are pinned in `packaging/versions.env`, as every tool is
  ([`build-and-release.md`](build-and-release.md)).

## Errors and logging

- An error is handled where something can be done about it. At the edge where a file, device or
  service failed, it becomes a message the user sees and a line in the App log (R14), saying what
  failed, on what, and what happens next.
- No bare `except`, and no `except Exception` that doesn't log. Nothing fails silently: what is
  skipped is logged.
- Logging is Python's `logging`, a logger per module, into the App log; debug lines only with
  `MUSIKATA_DEBUG=1` (R14.5).

## Threads and processes

- What runs where is A1.3's: the GUI thread only draws and answers clicks; work that keeps a core
  busy goes to the worker processes, waits on the disk or the network to the thread pool, and
  every write to the database through the writer thread.
- Nothing blocks the GUI thread: no file read, no query that can take long, no wait on another
  thread.
- Work crosses threads by Qt signals queued to the receiver, or through the ring buffers of A4.1
  and A4.3; no object is changed from two threads.
- The sound device's callback only copies samples out of the ring buffer.

## QML

- Colours, sizes, radii and fonts come from the design tokens of R6.2, never literals.
- Every string the user sees goes through `qsTr` (R1.10).
- Every control has an accessible name and role (R18.1); a test checks them.

## Dependencies

- Nothing joins what MusiKata carries without a reason written in the architecture (R1.2.2), and
  every package and tool is pinned ([`build-and-release.md`](build-and-release.md)).
- Tools used only in development (ruff, mypy, pytest, coverage.py, mutmut) are pinned the same
  way, and no build carries them.

## Comments and names

- Names say what a thing is, in the requirements' words: `play_count`, `album_artist`,
  `sleep_timer`, never `pc` or `aa`.
- Comments say why, not what, and cite requirement and architecture ids (`R7.6`, `A4.2`), never a
  review or other document that goes away ([`README.md`](README.md)).
- Each public function of `musikata_core` has a docstring saying what it takes and gives, in a
  sentence or two.
