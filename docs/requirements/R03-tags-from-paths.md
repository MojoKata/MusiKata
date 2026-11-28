# R3. Tags from paths

Most music libraries already say what each file is in its path:
`Lumen Drift/2019 - Glass Harbor/04 - Signal Fires.flac`. MusiKata reads that path, relative to
the music root, and fills or corrects the tags from it, so a folder of badly tagged rips becomes a
tidy album in one step. Mockups: `L08-folder-songs`, `T01-infer-from-path`.

R3.1. **Where it starts.** **Infer from path** is on a folder of songs in Folders (R2.9.7), on a
selection of folders and files there (R2.9.6), on an album's page, on a selection of songs (the
selection bar, `L03-songs-bulk-edit`), and on each Needs attention entry of that kind (R2.8). It
opens the Infer tags from path dialog for those files; a selected folder brings every file beneath
it.

R3.2. **Patterns.** A pattern describes a path under the root, with `/` between folders on every
platform, and tokens in braces:

| Token | Fills | Notes |
|---|---|---|
| `{artist}` | Artist | |
| `{albumartist}` | Album artist | |
| `{album}` | Album | |
| `{year}` | Year | Four digits |
| `{disc}` | Disc number | Digits |
| `{track}` | Track number | Digits; leading zeros dropped |
| `{title}` | Title | |
| `{genre}` | Genre | |
| `{*}` | nothing | Matches anything, to skip a part of the path |

R3.2.1. The text between tokens must match exactly, except that runs of spaces match any run of
spaces, and ` - `, ` – ` and `_-_` match one another. The extension is never part of a pattern.

R3.2.2. A token matches as little as it can while the rest of the pattern still matches, so
`{track} - {title}` reads `04 - Signal Fires - Live` as track 4, title "Signal Fires - Live".

R3.3. **Presets.** MusiKata knows the common layouts, tried in this order:

1. `{albumartist}/{year} - {album}/{track} - {title}`
2. `{albumartist}/{album} ({year})/{track} - {title}`
3. `{albumartist}/{album}/{disc}-{track} - {title}`
4. `{albumartist}/{album}/{track} - {artist} - {title}`
5. `{albumartist}/{album}/{track} - {title}`
6. `{albumartist}/{album}/{track} {title}`
7. `{artist} - {title}` (loose files)

Presets the user writes are kept in Settings (R13) and tried before these.

R3.4. **Detecting the pattern.** When the dialog opens, every pattern is tried on every file, and
the one that fits the most files is chosen; a tie goes to the more specific pattern (more
tokens). The picker beside the pattern says "Detected · 9 of 9 fit", and lists the other
patterns with their counts. Files the chosen pattern doesn't fit are listed last, unchanged, with
"Doesn't fit the pattern".

R3.4.1. The pattern field can be edited; the preview follows as the user types. Tokens are shown
as chips, and clicking a token below the field inserts it.

R3.5. **Fill or correct.** Two modes, chosen by radio buttons:

- **Only fill empty tags**: a tag that has a value keeps it.
- **Correct tags that differ** (the default): the path wins wherever it gives a value.

R3.6. **Tidying,** each a checkbox:

R3.6.1. **Tidy case** (on): a value that is all lower case or all upper case becomes Title Case,
keeping the small words (a, an, and, of, the, …) lower case inside a title; a value that already
has mixed case is left alone, so "deadmau5" stays as it is only when the path spells it so.
Inside a value all in capitals, letters split by `/` or `.` with each part 1 to 3 letters ("AC/DC",
"R.E.M.", "P.I.L.") stay as spelled and the rest is tidied, so "AC/DC LIVE AT DONINGTON" becomes
"AC/DC Live at Donington".

R3.6.2. **Year from folder** (on): a four-digit year found in the album's folder name, as
`2019 - Glass Harbor` or `Glass Harbor (2019)`, fills Year even when the pattern has no `{year}`.

R3.6.3. **Underscores as spaces** (on): `Signal_Fires` reads as "Signal Fires".

R3.6.4. **Track total**: when every track of a folder is present, Track total is filled with the
count.

R3.7. **The preview** lists each file with the columns the pattern fills. A value that will change
shows the old value struck through in red above the new one in green; "(empty)" stands for no
old value. Each changed file has a checkbox, on by default; unchecking leaves the file alone.
Files with no change are listed dimmed and unchecked.

R3.8. **Saving.** The footer counts the files and changes, and **Save N files** writes them
(R4.7). The old values go into the change history, so **Undo** puts them back (R4.9).

R3.9. **Tags match path.** For each file MusiKata keeps whether its tags agree with its path under
the pattern detected for its folder. A shorter name of the album, album artist or artist agrees:
the path's "Night Ferry" agrees with a tag of "Night Ferry (Original Soundtrack)", and "Glass
Harbor" with "Glass Harbor Remixed", as the tag starts with the path's text before a space, or is
it with a part in brackets added, compared as Infer from path compares (runs of spaces, and case
where the tag already has mixed case). A folder that holds two or more album folders, whose songs
carry an album artist or artist but none its name, groups albums (`Soundtracks`,
`Lumen Drift/Remixes`) and gives the songs beneath it no album artist or artist to agree with;
their album, track and title are still judged from their own folder and file; songs with neither
tag say nothing either way, so a folder of untagged albums is still read as their artist's.
Folders shows each folder's worst state beneath it (green: match, amber: can be fixed, red: no
tags; R2.9.5) and a chip per file ("Match", "Fixable" or
"Untagged", its tooltip saying what differs, a line each, as "Genre differs: the path says Ambient,
the tags Electronic"), and the mismatches are listed in Needs attention (R2.8).
