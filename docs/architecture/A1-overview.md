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

A1.3. **Threads and processes.** The GUI thread only draws and answers clicks.

- **Worker processes** do the Python work that keeps a core busy: the scan's tag reads and audio
  hashes (A2.2) and decoding for waveforms (A5.1). Python runs one thread's Python code at a time,
  so on threads this work would gain no speed and would make the GUI thread wait behind it for every
  row a list draws. A `ProcessPoolExecutor` of one process fewer than the cores, started when first
  needed with `spawn` (forking a process whose Qt threads are running is unsafe), runs
  `musikata_core` code that imports no Qt and sends plain data back. Each process lowers its own
  priority as it starts: `nice` and the idle I/O class (`ioprio_set`) on Linux,
  `PROCESS_MODE_BACKGROUND_BEGIN` on Windows, `PRIO_DARWIN_BG` on macOS, so a first scan never slows
  the window or the sound. They are MusiKata's own children and end with it; there is no service
  (R1.3). The frozen builds call `multiprocessing.freeze_support()`.
- **A thread pool** (`QThreadPool`) does the work that waits on the disk or the network: safe writes
  (A3.4), moving files (R12), mosaics (A2.7), lookups (A7), and passing the processes' results on.
  Each job reports progress and results through Qt signals queued to the GUI thread.
- **The database** has one writer connection, owned by a single writer thread, and read connections
  per thread (WAL mode), so a long write never stalls a list scrolling.
- **Playback** has a thread of its own (A4.1), which decodes a few seconds ahead of the sound
  device, so nothing else running can make the sound stop.
- **Garbage is collected on the GUI thread only.** Python's cyclic collector starts on whichever
  thread allocates when a collection is due, and what it frees is destroyed there: a QObject made
  in Python (a closed window's bridges and models, a watcher's socket notifier) destroyed on a
  scan's thread while the GUI thread delivers it an event crashes MusiKata. So no thread but the
  GUI thread starts a collection: MusiKata turns Python's own off as it starts, before any thread
  does, and a timer on the GUI thread collects instead (`musikata.garbage`): every second, the
  youngest generation when the counts say a collection is due and the older ones as theirs do, the
  whole heap at most every ten minutes, and whenever a window closes. And a closed window's
  objects aren't left for a collection: at its close they are deleted, on the GUI thread, and
  nothing holds them in a reference cycle.

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

A1.8. **Two windows.** The mini player (R15) is a second top-level `Window` created from the same
QML engine, so it binds to the same `Player` and models as the main window and nothing is copied
between them; each layout is a QML component loaded into it. It is frameless
(`Qt.FramelessWindowHint`), moved and resized with `startSystemMove()` and `startSystemResize()`,
which work on Wayland as well as X11, Windows and macOS, and kept on top with
`Qt.WindowStaysOnTopHint`, which Wayland compositors may ignore (R15.2). Its visuals reuse the
items of A5.3 at a smaller size.

A1.9. **Modules.** Each module of the two packages, its subject and its area (`scripts/areas.py`),
by which coverage is floored, mutation runs are planned and a review is cut into steps
(`docs/process/testing.md`, `docs/REVIEW.md`). A module is a file (`tags.py`) or a package of
them (`audio/`). A new module is a row here in the same change, and `tests/test_areas.py` fails
on a module this table doesn't name, or one whose area isn't the table's.

| Module | Area | What it holds |
|---|---|---|
| `musikata_core.db` | library | The index: its schema, migrations, the writer thread and read connections (A2.1, A1.3) |
| `musikata_core.scanner` | library | Walking the root, comparing, reading in batches, moves by audio hash (A2.2, A2.3); Ignore this folder's `.musikataignore` written and its songs taken out of the index (R2.11.1) |
| `musikata_core.albums` | library | Albums, compilations and artists, kept by the scan (R2.5, A2.1) |
| `musikata_core.sortnames` | library | Sort names: sort tags, articles, case, punctuation and numbers (R2.13) |
| `musikata_core.watch` | library | Watching the root, and rescanning on focus where it can't (A2.4) |
| `musikata_core.inotify` | library | Watching folders with Linux's inotify, a file rewritten in place included (A2.4) |
| `musikata_core.search` | library | FTS5 queries and `field:` terms (A2.5, R2.7), and the values in use the Edit tags panel suggests (R4.6) |
| `musikata_core.folders` | library | The folder table and the mosaics' sources (A2.7, R2.9, R5.8) |
| `musikata_core.attention` | library | Needs attention's groups (A2.6, R2.8): the queries over what the scan keeps for them, names with case and spacing set aside, an album's songs that differ, covers' sizes, the `.cue` sheet of an album in one file, Ignore's match, and the plan of a merge of an artist's or an album's names |
| `musikata_core.duplicates` | library | Exact and likely copies, and the best copy (R2.12): the key likely copies share, the groups found through the index's indexes, the copy proposed to keep and why, the choice of the copies checked, and the plan of what moving the others to the trash gives the kept one |
| `musikata_core.rootfiles` | library | The root's own files: plays, dismissals, merged and matched, and what naming and matching songs takes for every one of them, `ratings.json` included (A2.8, A2.10) |
| `musikata_core.ratings` | library | Ratings where they are kept: into the files or the root's `ratings.json`, read, merged and written, the rating each song shows worked out in the index, and a save's writer that puts each rating where it goes (R10, A2.8, A2.10) |
| `musikata_core.roots` | library | A root's id and finding its index; removing old ones (A2.9) |
| `musikata_core.nowplaying` | library | What's playing kept across restarts: `now-playing.json` read, matched to the index and written on its rhythm (R1.8, R7.2, A2.8, A2.10) |
| `musikata_core.settings` | library | The two `settings.json`, their defaults and the split (R13, R13.9, A2.10) |
| `musikata_core.workers` | library | The worker processes, at low priority (A1.3) |
| `musikata_core.clock` | library | The clock every timed piece is given (`docs/process/coding.md`) |
| `musikata_core.tags` | tags | The field mapping, reading and writing, the safe write: `fields`, `parse` and `read` (reading), `compose` and `write` (writing), `safe` (the safe write), `batch` (a save of many files), `edit` (what the Edit tags panel shows for a set of songs and the save its edits make), `tools` (the panel's bulk tools: what each would make of the songs, R4.5), `case` (Tidy case, R3.6.1) (A3.1, A3.2, A3.4, R4) |
| `musikata_core.encodings` | tags | Scoring and fixing text in the wrong encoding (A3.6, R4.10): Latin-1 text read under each candidate and scored by the scripts and alphabets of its words, the song flagged when another reads far better, the readings ranked, and the plan of a fix for a song or its album |
| `musikata_core.art` | tags | Finding, embedding and saving covers (R5): what an image is from its bytes, the covers the Album art dialog lists, what saving writes, and cover.jpg written with the older one to the trash |
| `musikata_core.genres` | tags | Genres (R9): a genre's tile, the names that look like one genre (case, accents, spacing and punctuation aside, and the user's own), renaming and merging as plans the preview shows, the built-in genre list |
| `musikata_core.lyrics` | tags | LRC, and lyrics in files and tags (R17, A7.6): LRC read in every shape it is written in, an `.lrc`'s bytes in any encoding, the lyrics a song shows (its `.lrc`, else its tags), the line sung at a time, and what saving writes where R13.11 says; below `tags`, which reads and writes a song's lyrics through it |
| `musikata_core.patterns` | files | Path patterns, both ways (A3.3, R3, R12.1) |
| `musikata_core.playlists` | files | M3U and M3U8 (R8): read in every shape R8.1.2 names and written as R8.1 says, where an entry is, the index's playlists kept by the scan, Find's matching, Export's plan and its copies, the store that makes MusiKata's changes (a smart playlist's made, its rule edited and its songs refilled, changes by hand refused) and points playlists at files moved |
| `musikata_core.smart` | files | Smart playlists (R8.9): the rule, its `#MUSIKATA-RULE:` text read in every shape and written (A2.10), its songs' query over the index, whether its file must be written again and the pace of it, and the keeper that keeps every one current |
| `musikata_core.organize` | files | Moving and renaming files (R12): Organize files' plan of the moves under the layout, its conflicts, the files beside the songs and the folders left empty; the move, a batch's writer; what follows it in the index, the playlists and the folders; files from outside the root read and brought in (R12.5); the plan made once and checked over, a checkbox recounting only what it touches (`Checking`); a `.cue` sheet's FILE lines following the files it names; Needs attention's dismissals about an album's folder following it; and removing songs to the trash: what goes (a folder whole, the files beside an album's songs with them) and the trash as a batch's writer (R2.11) |
| `musikata_core.history` | files | The change history and Undo (A3.5, R4.9) |
| `musikata_core.audio` | playback | `decode`, `join`, `seam`, `gain`, `eq` (with the limiter), `queue`, `sleep`, `stream`, `played` (when a song counts as played, R7.9) (A4, R7, R19) |
| `musikata_core.analysis` | analysis | `peaks` (a waveform's peak pairs, a view's bars, the blob kept) and `waveform` (a song worked out a part at a time on the worker processes, and kept by its audio hash) (A5.1); `spectrum` (A5.2); `landscape` (the 3D analyzer's slices kept, projected in perspective, coloured and made one triangle strip) (A5.3) |
| `musikata_core.online` | online | `http`, `musicbrainz`, `coverart`, `lrclib` (A7) |
| `musikata_core.update` | online | Checking for, fetching and checking a release (R1.9) |
| `musikata.app` | app | Starting, one MusiKata at a time, opening files (R1.6, R1.7) |
| `musikata.bridges` | app | `Backend`, `Player` and `Library`, as QML sees them (A1.2) |
| `musikata.models` | app | The list models (A1.5) |
| `musikata.garbage` | app | Garbage collected on the GUI thread only: when to collect what, from the counts and the time, and the timer that asks (A1.3) |
| `musikata.selection` | app | A song list's selection, by song id, with its anchor and current row: clicks and keys as the lists take them, without Qt (R2.6, R7.1) |
| `musikata.firstrun` | app | The first start: the root dropped, chosen or the platform's music folder (R2.1, X01-first-run) |
| `musikata.folders` | app | The Folders view: its model, the open folder, the selection (R2.9, A2.7) |
| `musikata.covers` | app | Covers' thumbnails and folders' mosaics, made off the GUI thread and cached, as QML loads them (R5.1, R5.8, A2.1, A2.7), with their corners rounded for the mini player (R15.2), and how an image is decoded off the GUI thread (`decoded`, which the Album art dialog uses too), Qt's image threads started on the GUI thread (`start_image_threads`) |
| `musikata.player` | app | The playback thread and the sound device, its sinks made on the GUI thread (A4.1, A4.6) |
| `musikata.nowplaying` | app | The now-playing bar's words and Up next's list (R6.5, R7.2) |
| `musikata.waveforms` | app | Waveforms in the running app: the shown song's and the next one's, found in the index or worked out on the worker processes off the GUI thread, a flat line filling in as the parts come, kept once whole (R11.1.1, A5.1) |
| `musikata.waveitem` | app | The waveform's Qt Quick item: its bars as scene-graph geometry, the played part in the gradient, rectangle nodes where Qt Quick renders in software (R11.1, A5.3) |
| `musikata.analyzeritem` | app | The 3D analyzer's Qt Quick item: the landscape of the last seconds' spectra from the analyzer's ring as one scene-graph geometry node (one painted image node where Qt Quick renders in software), its frame rate (up to 60, 30 when frames come late), and when it draws and wants samples (R11.3 to R11.3.2, A5.3, A5.5) |
| `musikata.spectrumitem` | app | The cover's spectrum's Qt Quick item: 32 translucent bars over Now Playing's cover (and the mini player's ten, in the gradient, R15.3) from the analyzer's ring, 30 frames a second on the GUI thread, as scene-graph geometry (rectangle nodes where Qt Quick renders in software), and when it draws and wants samples (R11.4.3, A5.2, A5.5, A5.6) |
| `musikata.nowplayingview` | app | Now Playing over the window: opened and closed, its visualization picked and kept, and what it says of the song playing, its chips, Up next and the waveform's minute marks (R11.4) |
| `musikata.miniplayer` | app | The mini player's window (R15, A1.8): opened and closed, the main window minimized and brought back, its layouts and their places and limits, snapping to a screen's edges and coming back onto one, Stay on top, all kept; what it says of the song and the next one, the wheel's volume, its menu, and whether its window is exposed (R15.1 to R15.5) |
| `musikata.discitem` | app | The mini player's Disc: the progress ring and the spectrum's rays round the cover as one scene-graph geometry node (one painted image node where Qt Quick renders in software), their geometry plain functions (R15.3, A5.3) |
| `musikata.lyrics` | app | Lyrics in the running app: Now Playing's Lyrics switch, kept; the lyrics of the song shown read off the GUI thread, the line sung followed and a line clicked seeking there; Edit… and Add… saved where the root's setting says through the batch and the change history (R17.1 to R17.3.1, R17.5) |
| `musikata.tints` | app | The cover's colour: its dominant colour picked from its thumbnail off the GUI thread, the tint the large views and Folders' Cards draw from it, kept beside the thumbnail in the cover cache (R6.2.2) |
| `musikata.edittags` | app | The Edit tags panel in the running app: what it edits and follows, its fields, suggestions, saving through the batch with progress, Cancel and Retry, and one song's file (R4.2 to R4.4, R4.6 to R4.8) |
| `musikata.albumart` | app | The Album art dialog in the running app: the album's art read, images decoded, converted and shrunk with Qt, dropped, chosen and pasted, saving through the batch with progress, Cancel and Retry, and Save cover to folder (R5.2 to R5.5) |
| `musikata.bulktools` | app | The Edit tags panel's bulk tools: the ⋯ menu, and a tool's dialog with its options and its preview, saved through the panel (R4.5) |
| `musikata.attention` | app | Needs attention in the running app: its chips and groups, found off the GUI thread and made a row at a time, each entry's action (Edit tags, Album art, Merge, Review…, Fix encoding…, Show in folder) and Ignore kept in `ignored.json` and watched; the Merge of an artist's or an album's names through the preview, the batch and the change history (R2.8) |
| `musikata.duplicates` | app | The same song more than once in the running app: what a group of copies and its rows say, Review…'s dialog, and Move the others to the trash, asked first, the files to the system's trash, the kept copy given their plays and highest rating, one entry in the change history (R2.12, R2.11) |
| `musikata.encodings` | app | Fix encoding… in the running app: a song's readings side by side, the choice for it or its album, the preview, saving through the batch and the change history, from Needs attention and the Edit tags panel (R4.10) |
| `musikata.infer` | app | Infer from path in the running app: the Infer tags from path dialog over a folder, a selection, an album, the Edit tags panel's songs or a Needs attention entry; the pattern detected, edited and picked, fill or correct and the tidying, the preview, saving through the batch and the change history (R3) |
| `musikata.removing` | app | Removing songs in the running app: Move to trash from the right-click menus, an album's ⋯ menu, Folders' ⋮ menu and Delete in the library views, what goes read off the GUI thread, asked first, the files to the system's trash between the library's scans, one entry in the change history; and Ignore this folder (R2.11, R2.11.1) |
| `musikata.organize` | app | Organize files in the running app: the dialog over a folder, an album, a selection or a row, its moves listed with their checkboxes and conflicts, the playlists they update, the moves run through the batch and the change history and followed in the library; and files dropped from outside the root, copied or moved in, their tags filled from their paths (R12, R12.5) |
| `musikata.genres` | app | Genres in the running app: the Genres view's tiles worked out off the GUI thread, a genre's page, the ⋯ menu's Rename… and Merge into… and the near duplicates' banner with Review… and Not now, through the preview, saved through the batch and the change history (R9) |
| `musikata.preview` | app | The preview of a change to many files' tags before it is saved: each file's old and new values, its checkbox, the footer and Save (R3.7, R3.8; the bulk tools', and Infer from path's) |
| `musikata.history` | app | The change history in the running app: the entries read and watched, the Change history panel, Ctrl+Z, R4.9.1's question and the message that follows a save, with Undo (R4.9, R6.7) |
| `musikata.ratings` | app | Ratings in the running app: a star clicked in a list or the now-playing bar, and Ctrl+0 to Ctrl+5 on the selection, saved through the batch and the change history, shown at once and put back when the save fails; the root's `ratings.json` watched and read again (R10.2, R10.3) |
| `musikata.playlists` | app | Playlists in the running app: the sidebar's list, a playlist's page and its entries, + and New playlist from selection, Add to playlist with its Undo, renaming, duplicating and deleting, removing and reordering entries (by dragging and by Ctrl+Shift+↑ / ↓), a file manager's files added, Find and Export…, each through the store off the GUI thread (R8, R6.3, R18.2) |
| `musikata.smart` | app | Smart playlists in the running app: the rule in words, New smart playlist… and Edit rule's dialog with its count of songs as the rule changes and Save through the store, and the smart playlists kept current after a scan, a save, a rating and plays, off the GUI thread (R8.9) |
| `musikata.dragging` | app | Drag and drop in the running app: what a drag carries from every list and grid (its songs, its card, its files), where a drop lands and what it does (onto a playlist, within one, onto the queue, a file manager's files), MusiKata's own drag format, and the platform's drag with the card as its picture (R6.10, R8.5) |
| `musikata.plays` | app | Play counts in the running app: the player's plays kept, the other computers' play files watched and read again (R7.9, A2.8) |
| `musikata.media` | app | The system's media controls (A4.5): `MediaControls` over the Player bridge, `controls` (what the system is told and what its commands do, without Qt), and the backends `mpris`, `smtc` and `nowplaying_mac` |
| `musikata.tour` | app | The tour (A1.6) |
| `musikata.layout` | app | The tour's layout check: each text against the box it is drawn in (A1.6) |
| `musikata/qml/` | qml | The views and the mini player |
