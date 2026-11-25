# R8. Playlists

R8.1. **Playlists are files.** Each playlist is an extended M3U file, UTF-8, named
`<name>.m3u8`, in the playlists folder: `Playlists` under the music root by default, a setting
(R13). Paths in it are relative to the playlist's own folder, with `/` between folders on every
platform, so the music root can move, or be copied to another computer or a USB stick, and the
playlists still work. The playlist view shows its file and its kind (`P01-playlist-drag`).

R8.1.1. The file starts with `#EXTM3U`, and each entry has an `#EXTINF:<seconds>,<artist> -
<title>` line before its path, so other players show names without reading the songs.

R8.1.2. **Reading.** MusiKata reads `.m3u` and `.m3u8` files anywhere under the root: UTF-8 first,
then the system's legacy encoding for an `.m3u` that isn't valid UTF-8. Absolute paths, Windows
paths (`\`) and `file://` URLs are understood. A playlist read from elsewhere is listed and played
but not rewritten until it is changed in MusiKata; then it is written in the form of R8.1.

R8.1.3. A playlist changed by another program while MusiKata runs is read again (R2.4).

R8.2. **The playlist view.** A mosaic of four of its covers, the name, number of songs, length,
file, and **Play**, **Shuffle** and **Export…**; then its songs with a drag handle, number,
cover, title and artist, album, genre, rating and length.

R8.3. **Making one.** **+** beside Playlists in the sidebar makes "New playlist" and selects its
name for editing; **New playlist from selection** in a song list's context menu makes one holding
the selection.

R8.4. **Renaming and removing.** Renaming a playlist renames its file. **Delete playlist** moves
the file to the trash after asking (R6.8); the songs are untouched. **Duplicate** copies it.

R8.5. **Drag and drop** (R6.10):

- Songs dragged onto a playlist in the sidebar are added at its end; the playlist is highlighted
  and the drag says "Add to Evening Focus".
- Within a playlist, songs are reordered by dragging, several at once, with an insertion line
  where they will land.
- Files dropped from a file manager onto a playlist are added: files under the root directly;
  files outside it as R12.5 says.
- Songs dragged out of a playlist onto a file manager are copied there.

A song may be in a playlist more than once; adding one that is already there says so in the
message and adds it anyway, and **Undo** takes it back out.

R8.6. **Removing songs.** Delete, or **Remove from playlist**, removes the selected entries; the
files are untouched, so it doesn't ask.

R8.7. **Missing songs.** An entry whose file is missing is shown dimmed with "Missing" and the
path it names. **Find** looks for the file by name and by tags under the root and offers what it
finds; choosing one fixes the entry. Missing entries are listed in Needs attention (R2.8). When
MusiKata moves a file (R12), every playlist naming it is updated in the same step.

R8.8. **Export.** **Export…** writes the playlist to a folder of the user's choosing, either as
an `.m3u8` with absolute paths, or as a copy of its songs numbered in order (`01 - Artist -
Title.mp3`) beside an `.m3u8` naming them, for a car's USB stick or a phone.

R8.9. **Smart playlists.** A smart playlist is a rule instead of a list: any of rating at least
N, genre is, artist is, year between, added in the last N days, played at least N times; and a
limit and order. It is kept as a playlist file like any other, rewritten whenever its songs
change, with its rule in a `#MUSIKATA-RULE:` comment line that other players ignore. Its view
shows the rule and **Edit rule** instead of drag handles.
