# R12. Organizing files

R3 makes the tags match the paths; this is the other way round: moving and renaming files so the
paths match the tags. Mockup: `T03-organize-files`.

R12.1. **The layout** is a pattern like R3.2's, set in Settings (R13), by default
`{albumartist}/{year} - {album}/{disc-}{track:02} - {title}`. Two forms are added for naming:

- `{track:02}`: the number padded with zeros to two digits.
- `{disc-}`: the disc number and `-`, only when the album has more than one disc.

R12.1.1. Characters a file system refuses (`/ \ : * ? " < > |`, and control characters) are
replaced with `_`, names are trimmed of spaces and dots at their ends, and each part of a path is
cut to 120 characters, so a layout gives the same path on every platform. "Various Artists"
compilations go under their album artist like any album.

R12.2. **Organize files** is in the ⋮ menu of Folders, of an album's page and of a selection (in
Folders, a selected folder brings every file beneath it, R2.9.6). It
lists every move, the old path dimmed above the new one, each with a checkbox, and the total.

R12.3. **What moves with the songs.** Images, `.cue`, `.lrc` and `.log` files beside an album's
songs move with them into the album's new folder. A folder left empty is removed. A song whose
path already matches is left alone.

R12.4. **Safety.**

- Two files that would get the same path are both listed as a conflict, and neither moves until
  one of them is changed or unchecked.
- A file is never written over: an existing file at the new path is a conflict.
- Playlists naming a moved file are updated in the same step, and the dialog says which.
- The whole move is one entry in the change history, so **Undo** puts every file, and every
  playlist, back (R4.9).

R12.5. **Adding files from outside the root.** Files or folders dropped onto MusiKata (or a
playlist) from outside the music root are not played from where they are. MusiKata asks
**Copy into the library** (the default) or **Move into the library**, then reads their tags, offers
**Infer from path** where the tags are missing, and places them by the layout of R12.1, with the
same preview. A file already in the library (same audio, found by its size and a hash of its
audio frames) is reported and not added twice.
