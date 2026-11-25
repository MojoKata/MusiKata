# MusiKata: requirements

MusiKata is a music player and organizer for Linux, Windows and macOS. It plays the music in one
folder, the **music root**, and keeps that folder tidy: it reads each file's path under the root
to work out the artist, album, track and title, fills or corrects the files' tags from it, puts
one cover on every song of an album, and keeps playlists as plain M3U files beside the music. It
edits the tags of many songs at once, rates and sorts by genre, and shows the music as it plays,
as a linear waveform or a 3D spectrum analyzer. It looks sleek, simple and modern, dark first.

These files say what MusiKata is and does. Why a part of it is built the way it is, where that
takes more than a sentence, is in the [architecture](../architecture/README.md); how the work is
done is in [`../process/`](../process/README.md). Mockups live in
[`../mockups/`](../mockups/README.md).

**How the requirements are organised.** Each section below has a file of its own, R1 to R19. A
section's items are numbered within it: `R3.4` is item 4 of the tags-from-paths section, and
`R3.6.1` item 1 under R3.6. A reference names an item by its id.

1. **Lasting ids.** Section ids (R1, R2, …) and their items (`R3.4`, `R3.6.1`) are never
   renumbered or reused: a new section or item takes the next free number, and one that is
   removed leaves its number unused.
2. **Splitting a section.** A section file that grows past 500 lines becomes a folder,
   `RNN-name/README.md`, that keeps the section's introduction and a table of its first-level items,
   each in a file of its own named by its id (`R03.04-name.md`). References do not change.
3. **A statement, not a changelog.** The requirements say what MusiKata is and does, in the
   present tense, and carry no dates, versions or status of their own; git holds their history,
   and `DEVELOP.md` says where the build stands.
4. **Questions, gaps and other issues** are the repository's GitHub issues, cited by number and
   linked: `[Q#n]` a question waiting on a decision, `[G#n]` a gap (a part not yet specified or
   built), `[#n]` any other issue. An answered question's answer goes into its section, and the
   issue is closed.
5. **Mockups in step.** A change here that touches what a user sees or does (a screen, field,
   button, dialog, setting, state or message) updates the mockups in the same change
   ([process](../process/README.md#mockups-in-step-with-the-requirements)).
6. **Names that sort.** A file or folder is named by its id with each number zero-padded to the
   width of the largest among its siblings, so a listing sorts by id:
   `R01-platform-and-architecture.md` to `R19-equalizer.md`, and inside a split section `R03.01-…`
   to `R03.12-…`. When a new sibling needs another digit, they are all renamed. Only names are
   padded: ids and references never are (`R1`, `R3.4`). `scripts/doccheck.py` checks it.

## Principles

These hold everywhere, and a section that seems to break one is wrong.

1. **The files are the truth.** What the user cares about lives in the music files and beside
   them: tags, embedded art, `cover.jpg`, `.m3u8` playlists. Another player, or MusiKata on
   another computer, sees the same library. MusiKata's database is an index of the files plus
   what has no place in a file (play counts, the change history, caches), and losing it loses
   nothing the user made.
2. **Nothing is written without a preview.** Every change to files (tags, art, moves, renames)
   is shown first, changed values marked, and is written only when the user says so. Every
   write can be undone (R4.9).
3. **Simple first.** The common case takes one action: drop a folder in, press **Infer from
   path**, press **Save**. Options exist, but their defaults are right for a tidy
   `Artist/Album/01 - Title` library.
4. **Private, and offline unless asked.** MusiKata works fully without a network and needs no
   account. It goes online only when the user asks for a lookup (R16), sends only what that
   lookup needs, and says what it sends and to whom.
5. **Never lose a file.** MusiKata never deletes a music file on its own; removing one moves it to
   the system's trash, and only when the user asks.

## Sections

| Id | Section | What it covers |
|---|---|---|
| **R1** | [Platform and architecture](R01-platform-and-architecture.md) | Platforms, Python and PySide6, one app and no service, distribution, local data, one MusiKata at a time, updates, language, size and speed |
| **R2** | [The music root and the library](R02-music-root-and-library.md) | The music root, the file kinds, scanning and watching, what a song, album and artist are, the library views, search, Needs attention, the Folders view, a missing music root, removing songs |
| **R3** | [Tags from paths](R03-tags-from-paths.md) | Patterns and their tokens, detecting the pattern, the preview, fill or correct, tidying |
| **R4** | [Tags and bulk editing](R04-tags-and-bulk-editing.md) | The tag fields, the Edit tags panel for one song or many, mixed values, saving, the change history and Undo |
| **R5** | [Album art](R05-album-art.md) | Where art is found, the Album art dialog, embedding and `cover.jpg`, what Needs attention reports, folder covers and mosaics |
| **R6** | [Main window and look](R06-main-window.md) | The layout, the sidebar, the header, the now-playing bar, the design tokens, menus, keyboard, drag and drop |
| **R7** | [Playback](R07-playback.md) | The queue, shuffle and repeat, ReplayGain, seeking, media keys and the system's now-playing |
| **R8** | [Playlists](R08-playlists.md) | M3U8 files, making and changing playlists, drag and drop, missing songs, smart playlists, export |
| **R9** | [Genres](R09-genres.md) | The Genres view, several genres per song, renaming and merging, near duplicates |
| **R10** | [Ratings](R10-ratings.md) | Stars, setting them, writing them into the files |
| **R11** | [Visualizations](R11-visualizations.md) | The linear waveform, the 3D analyzer, the Now Playing view |
| **R12** | [Organizing files](R12-organizing-files.md) | Moving and renaming files to match their tags, adding files from outside the root |
| **R13** | [Settings](R13-settings.md) | The Settings dialog and its groups |
| **R14** | [App log](R14-app-log.md) | MusiKata's own log files |
| **R15** | [Mini player](R15-mini-player.md) | The small separate window, its seven layouts, its controls |
| **R16** | [Online lookups](R16-online-lookups.md) | Covers, tags and identifying songs by sound from free online services, when asked; what is sent |
| **R17** | [Lyrics](R17-lyrics.md) | Where lyrics come from, showing them in step with the song, finding, editing and saving them |
| **R18** | [Accessibility](R18-accessibility.md) | Screen readers, the keyboard, text size, contrast and colour, motion |
| **R19** | [Equalizer](R19-equalizer.md) | Parametric and graphic presets, built in and the user's own, chosen by genre; Equalizer APO import |

## Not in MusiKata

Decided against, each closed as "no": syncing to phones and USB players
([#9](https://github.com/MojoKata/MusiKata/issues/9)); importing ratings, play counts and playlists
from other players ([#10](https://github.com/MojoKata/MusiKata/issues/10)); internet radio and
podcasts ([#11](https://github.com/MojoKata/MusiKata/issues/11)); scrobbling to Last.fm or
ListenBrainz ([#12](https://github.com/MojoKata/MusiKata/issues/12)). A feature on this list comes
in only by a decision that gives it a section.
