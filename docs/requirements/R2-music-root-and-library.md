# R2. The music root and the library

R2.1. **The music root.** MusiKata's library is one folder and everything under it (Q3). On the
first start (mockup `X01-first-run`) the user drops a folder onto the window, chooses one, or
takes the platform's music folder (`~/Music`, `%USERPROFILE%\Music`). It can be changed in
Settings (R13); changing it rescans and keeps nothing of the old root but the change history.

R2.1.1. The root's card at the bottom of the sidebar shows its path, the number of songs and
albums, the space they take and a dot: green when the library is up to date, turning while a
scan runs, amber when something couldn't be read (its tooltip says what, and links to R14).

R2.2. **File kinds.** MusiKata plays and tags MP3, FLAC, M4A (AAC and ALAC), Ogg Vorbis, Opus,
WAV and AIFF. WAV files are played but their tags are limited to what their RIFF `INFO` and ID3
chunks hold. Other files under the root are ignored, except images (R5) and playlists (R8).

R2.3. **Scanning.** On start, and when asked (⋮ › **Rescan library**), MusiKata walks the root.
It reads a file's tags only when its size or modification time changed since the last scan, so
a scan of an unchanged library of 10,000 songs takes seconds. A first scan shows its progress in
the root's card and fills the views as it goes.

R2.3.1. Hidden files and folders (a leading `.` on Linux and macOS, the hidden attribute on
Windows) are skipped, and so is any folder holding a file named `.musikataignore`.

R2.4. **Watching.** While MusiKata runs, files added, changed, moved or removed under the root, by
MusiKata or anything else, appear in the library within seconds. When the platform can't watch
that many folders, MusiKata rescans when its window gains focus instead, and says so in the log.

R2.5. **Songs, albums and artists.**

R2.5.1. A **song** is one audio file. Its identity in the database is its path under the root,
and a song moved by MusiKata (R12) keeps its play count and history.

R2.5.2. An **album** is the songs that share an album artist and an album title. A song without an
album artist uses its artist. Songs with the same album title in different folders are one album
only when their album artist matches; otherwise they are two albums of the same name.

R2.5.3. A **compilation** is an album whose songs have different artists and the compilation flag
(`TCMP`, `COMPILATION`, `cpil`), or whose album artist is "Various Artists". It is listed once,
under its album artist.

R2.5.4. An **artist** is anyone named as a song's artist or album artist. Names that differ only
in case are shown as one and reported in Needs attention (R2.8).

R2.6. **The library views,** chosen in the sidebar (R6.3):

- **Albums** (`L01-albums`): a grid of covers with the title, artist and year under each, filter
  chips for the most common genres, and a list mode. Clicking an album opens its page
  (`L02-album`): the cover, title, artist, year, genre, number of songs, length and format; Play,
  Shuffle, Edit tags, Album art; chips for the album's state (art embedded in all songs,
  `cover.jpg` present, tags match the path); and its songs.
- **Artists**: a grid of artists with a mosaic of their covers; an artist's page lists their
  albums, then songs on others' albums.
- **Songs** (`L03-songs-bulk-edit`): every song in a table: track, title, artist, album, genre,
  year, rating, length; columns can be shown, hidden, resized and sorted. Rows are selected with
  a click, Ctrl/⌘-click, Shift-click and their checkboxes.
- **Genres**: R9.
- **Folders** (`L04-folders` to `L08-folder-songs`): the folders under the music root, shown with
  their covers the way Albums shows albums, and the files in them with their tags and whether
  they match their path (R3). It is the view for working on files as files: R2.9.
- **Needs attention**: R2.8.

R2.7. **Search.** The header's search box (`/` to focus it) filters the current view as the user
types, matching title, artist, album, album artist, genre, year and file name, ignoring case and
accents. `artist:`, `album:`, `genre:`, `year:` and `rating:` (`rating:>=4`) narrow a term to one
field.

R2.8. **Needs attention.** A view of what MusiKata can help fix, with the count in the sidebar.
Each kind is a group, and each entry has the action that fixes it:

- Tags that differ from the path, or are missing where the path gives them (R3): **Infer from
  path**.
- An album whose songs differ in album, album artist, year, genre or cover: **Edit tags** or
  **Album art**.
- No cover, or a cover smaller than 500 × 500 (R5.6): **Album art**.
- Names that differ only in case or spacing (artists, albums, genres, R9.5): **Merge**.
- Playlist entries whose file is missing (R8.7): **Find**.
- Files that couldn't be read: **Show in folder**, and the error.

An entry the user dismisses (**Ignore**) stays dismissed until the file changes.

R2.9. **The Folders view.** Folders browses the music root one folder at a time, and looks and
works like Albums: covers first, names under them, the same header.

R2.9.1. **Where you are.** The header is the one Albums has (R6.4): search, view mode, sort and
⋮. In place of the view's title it shows the open folder's path under the root, one crumb per
folder (`Lumen Drift › Remixes`), the last in the title's weight and the rest muted; each crumb
opens its folder. The root's own name, and any stand-in for it ("Music", a home icon), is never
shown: at the root the title is **Your music folders**. Beside the title is the open folder's
count, "3 folders · 34 songs".

- **Going up**: a crumb, Alt+↑ (⌘↑ on macOS), or Backspace; Alt+← / the mouse's back button go
  back to the folder opened before. Clicking **Folders** in the sidebar returns to the root.
- **Long paths**: when the crumbs don't fit, the middle ones become **…**, which opens a menu of
  them.
- MusiKata remembers the open folder and the view mode, and opens Folders there next time.

R2.9.2. **What is listed.** The open folder's subfolders, then its own audio files. A folder with
no audio file anywhere beneath it (a `Playlists` folder, a folder of scans) is not listed; hidden
and ignored folders never are (R2.3.1). Names sort as people read them (case and leading
punctuation ignored, numbers by value), so `_Incoming` sorts under I and `Disc 10` after `Disc 9`.
Double-click or Enter opens a folder or plays a file. Search (R2.7) filters the open folder and
everything beneath it, listing the matching folders and files with the path under the open folder
beside each.

R2.9.3. **Covers.** Each folder shows its own cover or a mosaic of the covers beneath it
(R5.8), so an artist's folder looks like the artist and a folder of albums looks like an album.

R2.9.4. **View modes,** chosen in the header's view switch, the same for every folder:

| Mode | Folders | Mockup |
|---|---|---|
| **Large images** | Covers about 220 px wide, name and count under each | `L05-folders-large` |
| **Small images** (default) | Covers the size of Albums' (R2.6), name and count under each | `L04-folders` |
| **Cards** | Wide cards like the Genres view's (R9.1): tinted by the cover's colour, the cover at the left, the name, "2 folders · 21 songs", and the folder's state | `L06-folders-cards` |
| **List** | One table with Songs' columns (R2.6); a folder's row is two rows tall, its cover the row's full height, the name on the first line and "2 folders · 43 songs" on the second; its other columns show the value its songs share (artist, album, year) or stay empty, and its time is their total | `L07-folders-list` |

In the three image modes the folder's own files follow the folders as a song list under "4 songs in
this folder" (`L05-folders-large`), with the file name, title, album, rating, time and path-match
chip; in List they are one-row entries of the same table, after the folders.

R2.9.5. **State.** Each folder carries the worst path-match state of the files beneath it
(R3.9): a dot on its cover in the image modes, and a chip ("3 to fix", "No tags") on cards and
in List. A folder whose files all match shows nothing.

R2.9.6. **Acting on a selection.** Folders and files are selected together, with a click,
Ctrl/⌘-click, Shift-click, a drag box in the image modes, or the checkbox that appears on a cover
under the pointer and on every row in List. A selected folder stands for every song beneath it.
The selection bar counts both ("2 folders · 21 songs selected") and offers:

- **Play** and **Add to playlist** (R8.5);
- **Edit tags**: the Edit tags panel (R4.2) for every song selected or beneath a selected folder,
  with mixed values as R4.3 says (`L07-folders-list`);
- **Infer from path**: the Infer tags from path dialog (R3) for the same songs, each read against
  its own path;
- **Album art** (R5.2), when the songs are one album;
- **Organize files** (R12.2).

The same actions are in the right-click menu of a folder or file, with **Show in file manager**.
Folders and files are dragged as R6.10 says.

R2.9.7. **A folder of songs.** When the open folder holds audio files and no subfolders (an
album's folder, most often), a strip like an album's page (R2.6) heads them: its cover, its name,
its files' count, size and where its art comes from; chips for its state (art, tags match path);
**Edit tags**, **Album art** and **Infer from path**; and, when files differ from their path, one
line saying how ("The path says the album is from 2022, but 1 file has no year"). Its files follow
as a table: file name, track and title from the tags, artist, genre and year, values that differ
from the rest of the folder marked, and a chip for each file's path-match state (R3.9)
(`L08-folder-songs`). The view switch stays, and applies again on leaving the folder.
