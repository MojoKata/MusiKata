# A1. Overview

A1.1. **The stack.**

| Layer | Choice | Why |
|---|---|---|
| Language | Python, the version in `packaging/versions.env` | One language for the app, its scripts and its tests; the Kata toolchain |
| GUI | PySide6, Qt Quick (QML), `Basic` controls style | Full control of the look (R6.2), smooth lists and animation, the GPU scene graph for the analyzer (A5) |
| Playback | MusiKata's own: PyAV (FFmpeg) decodes, NumPy applies gain and the equalizer, Qt Multimedia's `QAudioSink` plays | Gapless playback (R7.6) and the equalizer (R19) need the audio in MusiKata's hands; PyAV decodes every kind of R2.2 and can seek, which Qt's `QAudioDecoder` can't (A4) |
| Tags | Mutagen | Pure Python, reads and writes every kind of R2.2, keeps frames it doesn't know (A3) |
| Library | SQLite, through Python's `sqlite3` | In Python already; FTS5 for search (A2) |
| Numbers | NumPy | The FFTs and peak reductions of A5, fast enough without native code of our own |

A1.2. **Two packages,** as in the rest of the Kata suite:

- `musikata_core`: everything that doesn't draw: the database, the scanner, tags, path patterns,
  art, playlists, organizing, the change history, the root's own files (A2.8), decoding and the
  audio chain (A4), waveform and spectrum arithmetic. It imports
  `PySide6.QtCore` at most (for signals and the file watcher), never `QtGui`, `QtQuick` or
  `QtMultimedia`, so its tests run without a display and its logic can be used from scripts.
- `musikata`: the app: QML, the models the QML lists bind to, the bridge objects (`Backend`,
  `Player`, `Library`) exposed to QML, playback, the system integrations of A4.5, and the tour
  (A1.6).

A1.3. **Threads.** The GUI thread only draws and answers clicks. Scanning, reading and writing
tags, decoding for waveforms and moving files run on a worker pool (`QThreadPool`), each job
reporting progress and results through Qt signals queued to the GUI thread. The database has one
writer connection, owned by a single writer thread, and read connections per thread (WAL mode),
so a long write never stalls a list scrolling. Playback has a thread of its own (A4.1), which
decodes a few seconds ahead of the sound device, so nothing else running can make the sound stop.

A1.4. **From a file to the screen and back.**

```
 music root ──scan/watch──▶ scanner ──▶ Mutagen read ──▶ musikata.db ──▶ list models ──▶ QML views
     ▲                                                     │  ▲
     │                                                     │  └── change history (old values)
     └──── safe write (A3.4) ◀── Mutagen write ◀── edit (panel, R3, R5, R9, R10, R12)
```

A write goes to the file first; the index is updated from the file afterwards, by the same path
a scan takes. The database is never ahead of the files, so it can always be rebuilt from them
(R1.5.1).

A1.5. **List models.** The Songs view of a 50,000-song library is a `QAbstractListModel` that
pages rows from SQLite as they scroll into view; QML never holds the whole library. Sorting and
filtering are SQL, not proxy models.

A1.6. **The tour.** `--tour DIR` drives the real app through every screen of the mockups on a demo
library and saves `DIR/<screen>.png`, offscreen, as AppKata's does. It is how the screenshots are
made and how layout regressions are caught: each screen's visible text is checked against the box
it is drawn in.

A1.8. **Two windows.** The mini player (R15) is a second top-level `Window` created from the same
QML engine, so it binds to the same `Player` and models as the main window and nothing is copied
between them; each layout is a QML component loaded into it. It is frameless
(`Qt.FramelessWindowHint`), moved and resized with `startSystemMove()` and `startSystemResize()`,
which work on Wayland as well as X11, Windows and macOS, and kept on top with
`Qt.WindowStaysOnTopHint`, which Wayland compositors may ignore (R15.2). Its visuals reuse the
items of A5.3 at a smaller size.

A1.7. **Decisions.**

A1.7.1. **QML over Qt Widgets.** Widgets would give native-looking tables for free, but the look of
R6.2 (cards, tinted backgrounds, the waveform seek bar, smooth drag feedback) is far easier in QML,
and the analyzer needs the scene graph anyway. The cost, writing a table with resizable sortable
columns in QML, is paid once.

A1.7.2. **Files first.** Keeping ratings and playlists in the files (Principle 1) costs writes on
every star clicked and a parser for M3U. It buys a library that survives MusiKata, works with
other players, and needs no backup of its own.

A1.7.3. **No plugin system; online services only when asked.** Plugins would widen what has to be
tested and trusted for features nobody has asked for. The online services of R16 are four, named,
free and open, each used only when the user asks (A7), so MusiKata stays whole without them.

A1.7.4. **Our own audio pipeline.** Qt's media player is simple to use but opens each file on its
own, so it leaves a gap between songs and offers no way to filter the sound. Taking decoding, gain,
the equalizer and the hand-over to the device into MusiKata (A4) costs what Qt did for free:
seeking, buffering and devices that come and go are MusiKata's to write and test. It buys gapless
playback, the equalizer, the analyzer's audio without a second tap, and the ground for crossfade
([#4](https://github.com/MojoKata/MusiKata/issues/4)) and computing loudness
([#2](https://github.com/MojoKata/MusiKata/issues/2)).
