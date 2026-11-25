# A2. Library and scanning

A2.1. **The database** is `musikata.db` (R1.5), one per root on the computer's own disk, SQLite in
WAL mode. It is an index: everything in it is rebuilt from the root's files and its `.musikata`
folder (A2.8). Its tables, in outline:

| Table | Holds |
|---|---|
| `song` | One row per file: path under the root (unique), size, modification time, kind, length, bit rate, sample rate, every R4.1 field, an `audio_hash` (R12.5), the path-match state (R3.9) |
| `song_genre` | Song and genre, one row per genre (R9.2) |
| `album` | Album artist and title (R2.5.2), its cover's source and thumbnail, cached counts |
| `folder` | One row per folder under the root that has audio beneath it: path, parent, counts of subfolders and songs (direct and beneath), its own cover's source, the mosaic's sources, the worst path-match state beneath it (A2.7) |
| `playlist` | One row per playlist file: path, modification time, smart rule (R8.9) |
| `playlist_entry` | Playlist, position, the path as written, the song it resolves to (or none: missing, R8.7) |
| `play` | Play counts and last played (R7.9), loaded from and saved to `.musikata/plays/`, a file per computer (A2.8) |
| `change` / `change_file` | The change history (R4.9), indexed from `.musikata/history/` (A3.5) |
| `waveform` | Song, the audio's hash, the peaks as a blob (A5.1) |
| `ignored` | Needs attention entries the user dismissed, with the file's modification time (R2.8), from `.musikata/ignored.json` |
| `lookup` | Answers from the online services, by request, with when they were fetched (A7.7) |
| `song_fts` | FTS5 over title, artist, album, album artist, genre and file name (R2.7) |

The schema has a version number; migrations are numbered Python functions run in order at start,
in one transaction.

A2.2. **The scan.**

1. Walk the root with `os.scandir`, skipping what R2.3.1 skips.
2. Compare each audio file's size and modification time with its row; unchanged files cost one
   `stat`.
3. Read changed and new files with Mutagen on the worker pool, in batches of 200, and write each
   batch in one transaction.
4. Rows whose file wasn't seen are removed at the end, unless the file reappears elsewhere with
   the same `audio_hash`, which is a move: the row's path changes and its play counts stay.

A2.3. **The audio hash** is a hash of the first and last 64 KB of the audio frames, skipping the
tag blocks, so retagging a file doesn't change it and two copies of a song match.

A2.4. **Watching.** `QFileSystemWatcher` on every folder under the root, with changes gathered for
a second before a partial rescan of the folders named. On Linux the inotify watch limit
(`fs.inotify.max_user_watches`) can be smaller than the number of folders; when adding a watch
fails, MusiKata stops watching, logs it, and rescans on focus instead (R2.4). Writes MusiKata
makes itself are recognised by path and time and not rescanned twice.

A2.5. **Search** is an FTS5 query with the `unicode61` tokenizer and `remove_diacritics 2`, so
"beyonce" finds "Beyoncé"; prefix matching on the last word as the user types; `field:` terms
become column filters (R2.7).

A2.6. **Needs attention** (R2.8) is a set of SQL views over `song` and `album`, recomputed for the
folders a scan touched, so the count in the sidebar is always current without a full pass.

- Exact copies (R2.12) share an `audio_hash`; likely ones share the artist and title once case,
  accents and punctuation are set aside, with lengths within 2 seconds, and are found through an
  index on that normalised pair.
- An album in one file is a single audio file of 20 minutes or more with a `.cue` beside it.
- Text in the wrong encoding is flagged when it is read (A3.6).

A2.7. **Folders.** The `folder` table is what the Folders view (R2.9) lists, so opening a folder
of a large library is one indexed query on `parent`, not a walk of the disk.

- **Kept current with the scan.** When a scan or a watched change touches a folder, that folder's
  row and each of its ancestors' rows are recomputed, bottom up, in the batch's transaction:
  counts, the worst state (R2.9.5), its own cover (R5.8 step 1) and, when it has none, the
  mosaic's sources (step 2), chosen from its children's rows without reading any file.
- **Mosaic images.** A mosaic is drawn on the worker pool with `QImage` and `QPainter` from its
  sources' thumbnails, at the two sizes the views use, and kept in the cache folder (R1.5) under
  a hash of its sources' identities and modification times. A changed cover changes the hash of
  every mosaic it is in, and they are redrawn when next shown; stale ones are removed with the
  thumbnail cache's trimming.
- **The models.** Folders binds to one `FolderModel` for every mode, folders then files (R2.9.2);
  the mode is the QML delegate, not a different model, so switching modes keeps the selection
  and the scroll position.

A2.8. **The root's own files** (R1.5) are small JSON files in `<root>/.musikata/`, each written to
a temporary file beside it and moved over the old one (`os.replace`), the one step that is safe on
every filesystem and share. No file is locked; two computers sharing a root keep their changes
apart instead:

- Each computer has an id, made on its first start and kept in the shared settings, with its name
  for display.
- Play counts are a file per computer, `plays/<computer id>.json`, written whole by that computer
  alone from the counts it keeps in the index; the count shown is the sum of the files. No two
  computers ever write the same file, so plays are never lost or counted twice, and a root kept in
  sync by Dropbox, OneDrive or Syncthing gets no "conflicted copy" files from them.
- `ignored.json` and `ratings.json` change seldom and are merged entry by entry: before writing,
  MusiKata reads the file again, and the newest entry wins.
- The change history is one file per entry (A3.5), never rewritten, so there is nothing to merge.
- A move made by MusiKata (R12) is an entry in the change history. Each computer rewrites the
  moved songs' paths in its own files, and reads other computers' play files through the moves
  they haven't caught up with yet.
- When `.musikata` can't be written (R1.5.2), the same data is kept in the index only, and the
  root's settings are read and never written.
