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
| Code, tests, builds | Not started |

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
