# Testing

What runs when, on which environment. R1.1 promises only what these environments test: an
environment leaves this list, and R1.1, together.

## Tiers

| Tier | When | What it's for |
|---|---|---|
| 1 | every change | the whole pytest suite in one container on the release's Python and PySide6, offscreen: the gate for every commit, run by CI on every pull request and push to `main` |
| 2 | before pushing | the tour and its layout check, the AppImage built and started, the Windows suite in its VM |
| 3 | before a release | each platform's build installed and used by hand: playback through real speakers, media keys, drag and drop with the platform's file manager, the mini player moved, resized and kept on top |

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
- **The change history** (R4.9): every kind of save undone and redone.
- **The analysis** (A5): peaks and bands of generated tones land where they should.
- **QML**: the models with a 50,000-row library; the views load with no QML warnings.

Tests never need the network or a sound card: playback tests use Qt's null audio output and check
positions and signals.

## Environments

| Environment | Tier | Runs |
|---|---|---|
| Ubuntu 24.04 container | 1, 2 | the suite (CI too); the tour and its layout check |
| Ubuntu 22.04 container | 2 | the AppImage build, on the oldest glibc it supports |
| Linux Mint 22.3, LMDE 7, Ubuntu 26.04 | 2, 3 | the AppImage started on X11 and Wayland, MPRIS seen by the desktop |
| Windows 10 22H2 and Windows 11 VMs | 2, 3 | the installer, the suite on Windows, the tour, uninstall |
| macOS 14 (CI runner, and a real Mac) | 2, 3 | the app bundle, the suite on macOS, notarization checked |

## CI

GitHub Actions, each action pinned by commit SHA: tier 1 on every pull request and push to
`main`; the tour, with its screenshots kept as the run's artifact; the three builds, unsigned,
each with its `.sha256`. A `v*` tag builds without caches and, once approved, signs the builds and
drafts a release ([`build-and-release.md`](build-and-release.md)).
