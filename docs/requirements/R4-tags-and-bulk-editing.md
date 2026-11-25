# R4. Tags and bulk editing

R4.1. **The fields.** MusiKata reads and writes these, under the same names for every file kind
(the mapping to ID3 frames, Vorbis comments and MP4 atoms is A3.2):

| Field | Notes |
|---|---|
| Title, Artist, Album, Album artist | Text |
| Track, Track total, Disc, Disc total | Numbers |
| Year | Four digits; a full date is kept when the file has one |
| Genre | One or more (R9.2) |
| Composer, Comment | Text |
| Compilation | Yes or no (R2.5.3) |
| Rating | R10 |
| Cover | R5 |
| ReplayGain | Read only; used by R7.5 |

R4.1.1. Fields the panel doesn't show (lyrics, which R17 handles; MusicBrainz ids, which only
R16.5 writes; encoder settings; private frames) are kept untouched when a file is written.

R4.2. **The Edit tags panel.** **Edit tags** (on an album, a song or a selection, or Ctrl+E /
⌘E; on folders, R2.9.6, it edits every song beneath them) opens a panel docked on the right
(`L03-songs-bulk-edit`). It shows the cover and what is being edited ("Tide Tables · Lumen Drift ·
4 songs"), then a field for each tag. The list beside it stays usable: changing the selection
changes what the panel edits, after asking to save or discard unsaved changes.

R4.3. **Many songs at once.** With several songs selected, a field whose value is the same on all
of them shows that value; a field whose values differ shows "Mixed: keep each song's own" in
grey. Typing in a mixed field sets that value on every selected song; leaving it alone keeps each
song's own. A mixed field's ▾ lists the values in use and how many songs have each, and picking
one sets it on all.

R4.4. **What will change.** A field changed from what the files hold is outlined in the accent
colour with a dot at its end, and a line above the buttons says "3 fields will change on 4
songs". **Revert** clears the changes; **Save to N files** writes them (R4.7).

R4.5. **Bulk tools,** in the panel's ⋯ menu, each shown in a preview like R3.7 before saving:

R4.5.1. **Number tracks**: numbers the selected songs 1, 2, 3 … in their current order, and sets
Track total.

R4.5.2. **Replace in field**: finds text (or a regular expression) in one field of the selected
songs and replaces it.

R4.5.3. **Tidy case**: as R3.6.1, on the fields chosen.

R4.5.4. **Copy from…**: copies chosen fields from one song to the others, as for a bonus track
ripped apart from its album.

R4.5.5. **Infer from path**: R3, for the selection.

R4.6. **Autocomplete.** Artist, Album artist, Album and Genre suggest the values already in the
library as the user types, so one spelling is reused instead of a new one made.

R4.7. **Writing.** Saving writes each file in turn, shows progress for more than a few files, and
can be cancelled between files. A file is never left half written: each is written in full beside
the original and then put in its place (A3.4). Read-only files, files in use and files that
fail are listed at the end with their reason and a **Retry**; the others are saved.

R4.7.1. By default a written file's modification time is updated. A setting (R13) keeps it as it
was, for backup tools that go by it.

R4.7.2. MP3s are written as ID3v2.4, or ID3v2.3 when Settings says so (R13), for older players
and car stereos. An ID3v1 tag already in a file is updated to match; none is added.

R4.8. **One song.** For a single song the panel also shows the file's path, kind, length, bit
rate, sample rate, size and the tags MusiKata keeps without showing (R4.1.1), read only.

R4.9. **The change history and Undo.** Every save (from the panel, R3, R5, R9, R10, R12) is one
entry in the change history, holding each file's old values. Ctrl+Z / ⌘Z, or **Undo** in the
message that follows a save, puts back the most recent entry; ⋮ › **Change history** lists the
entries by day, each with the files it touched, and undoes any of them file by file. Entries are
kept for 90 days, a setting (R13).

R4.9.1. Undoing a file that has changed since (by MusiKata or anything else) asks first, and
shows what would be lost.
