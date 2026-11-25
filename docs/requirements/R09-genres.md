# R9. Genres

R9.1. **The Genres view** (`G01-genres`) shows each genre as a tile with its name, the number of
songs and albums, and three of its covers, sorted by number of songs or by name. A tile opens the
genre's albums and songs. The Albums view's chips (R2.6) filter by the most common genres.

R9.2. **Several genres per song.** A song can have more than one genre. They are stored as
separate values where the file kind allows it (ID3v2.4, Vorbis comments, MP4) and joined with
`; ` in ID3v2.3, and shown as chips in the Edit tags panel. A song counts towards each of its
genres.

R9.3. **Old ID3 genres.** Numeric genres from ID3v1 and early ID3v2 (`(13)`, `13`) are shown by
name ("Pop"), and written by name the next time the file is saved.

R9.4. **Renaming and merging.** A genre's ⋯ menu has **Play all**, **Rename…**, **Merge into…**
and **Select its songs**. Renaming and merging rewrite the genre in every song that has it, after
a preview of the files that change, and are undoable (R4.9).

R9.5. **Near duplicates.** Genres whose names differ only in case, spacing or punctuation
("Hip-Hop", "Hip Hop", "hiphop"), and genres the user has said are the same, are offered for a
merge in a banner at the top of the view: "These look like one genre: Electronic (214),
Electronica (17), electronic (6)", with **Review…** and **Not now**. **Review…** opens the merge's
preview with the most used name chosen. The same entries are in Needs attention (R2.8).

R9.6. **The genre list.** The names suggested while typing (R4.6) are those in the library plus a
short built-in list; Settings (R13) edits the built-in part.
