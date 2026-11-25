# Developing MusiKata

Where the build stands, and what the first release holds. What MusiKata does is in the
[requirements](docs/requirements/README.md), why it is built so in the
[architecture](docs/architecture/README.md), and how the work is done (running from source, the
demo library, the tour, tests, releases) in [`docs/process/`](docs/process/README.md). MusiKata is
free software under the GPL, version 3 or later ([`LICENSE`](LICENSE)).

## Status

| Area | State |
|---|---|
| Requirements R1 to R19, architecture A1 to A7, process | Written; no open questions |
| Mockups of every screen of the first release | Drawn ([`docs/mockups/`](docs/mockups/README.md)) |
| Tooling, from AppKata: the documents and private-names checks, areas, skip lists, the clock harness, coverage floors, the Pages site, mutation testing, releases | Written; runs once `packaging/versions.env` and the first code exist |
| Code and its tests, builds | Slice 1, tooling, done; slice 2, the skeleton, underway ([#19](https://github.com/MojoKata/MusiKata/issues/19)) |

## The build order

A walking skeleton first, then slices that deepen it: the thinnest MusiKata that runs end to end on
all three platforms comes first, so what each platform does differently (PyAV's wheels, trimming Qt,
Wayland, the two Mac bundles) shows at the start, not at the release. Each slice is one or more pull
requests, and is done when its requirements' sections are in the trace (`docs/process/testing.md`),
its screens are in the tour, and each of its modules reaches the coverage of `testing.md`.

| Slice | | What it builds |
|---|---|---|
| 1 | Tooling | `packaging/versions.env` and its pins, `pyproject.toml`, `scripts/python-standalone.sh`, CI's tier 1, the requirements trace and its checker, the demo library generator (A6.7) |
| 2 | Skeleton | the index, a scan with tag reads, a window with the Songs list, and a double-click playing through the PyAV pipeline; built as the AppImage, the installer and both `.dmg`s, with the tour's first screenshot |
| 3 | The library | albums, artists, search, watching, the Folders view, finding a root's index (R2, A2) |
| 4 | Playback | gapless joins, the queue, shuffle and repeat, ReplayGain, seeking, devices, the system's media controls, the now-playing bar (R7) |
| 5 | Editing | the Edit tags panel, safe writes, the change history and Undo, ratings, plays and the root's own files (R4, R10, A2.8) |
| 6 | Tidying | album art, Needs attention, duplicates, encodings, genres (R5, R9, R2.8, R2.12) |
| 7 | Files | tags from paths, organizing, playlists, removing songs (R3, R12, R8, R2.11) |
| 8 | Now Playing | the waveform, the analyzer, lyrics, the mini player (R11, R17, R15) |
| 9 | Sound and settings | the equalizer, the sleep timer, the Settings dialog (R19, R7.10, R13) |
| 10 | Online | looking up covers, tags and lyrics (R16, R17.4) |
| 11 | Release | updates (R1.9), accessibility (R18), the size and speed targets (R1.11), signing, the first field test |

## The first release

Everything in the requirements, except what is listed under **Later**. Requirements change by
commits to `docs/requirements/`; this list changes with them.

| | |
|---|---|
| **Platforms** | Linux (AppImage), Windows 10 22H2 and 11 x64 (installer), macOS 14 and newer as two apps, Apple silicon and Intel, ad-hoc signed, from MusiKata's Homebrew tap and as `.dmg`s (R1) |
| **In** | R1 to R15, R18 and R19 whole: gapless playback through MusiKata's own audio pipeline, the parametric and graphic equalizer with presets, presets by genre and Equalizer APO import, duplicates, **Fix encoding…**, updates when asked, a root per run |
| **In** | R16 Online lookups: covers and tags, off until turned on |
| **In** | R17 Lyrics: from `.lrc` files and tags, found online, edited as text |

## Later

| Issue | What |
|---|---|
| [#2](https://github.com/MojoKata/MusiKata/issues/2) | Computing loudness (ReplayGain 2.0) |
| [#3](https://github.com/MojoKata/MusiKata/issues/3) | Splitting albums kept as one file with a CUE sheet into tracks |
| [#4](https://github.com/MojoKata/MusiKata/issues/4) | Crossfade |
| [#5](https://github.com/MojoKata/MusiKata/issues/5) | Converting between formats |
| [#6](https://github.com/MojoKata/MusiKata/issues/6) | Identify by sound (R16.6) |
| [#7](https://github.com/MojoKata/MusiKata/issues/7) | Timing plain lyrics by tapping along (R17.5's **Set time**) |
| [#8](https://github.com/MojoKata/MusiKata/issues/8) | The light theme |
| | Translations other than English (R1.10) |

Signing and notarizing the Mac apps, and moving them to Homebrew's own casks, follow a Developer ID
(A6.5.1). What MusiKata won't do is listed in the requirements' README.
