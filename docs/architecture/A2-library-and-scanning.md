# A2. Library and scanning

A2.1. **The database** is `musikata.db` (R1.5), one per root on the computer's own disk (A2.9),
SQLite in WAL mode. It is an index: everything in it is rebuilt from the root's files and its
`.musikata` folder (A2.8). Its tables, in outline:

| Table | Holds |
|---|---|
| `song` | One row per file: path under the root (unique), size, modification time, kind, length, bit rate, sample rate, every R4.1 field, an `audio_hash` (R12.5), the path-match state (R3.9) |
| `song_genre` | Song and genre, one row per genre (R9.2) |
| `album` | Album artist and title (R2.5.2), its cover's source and thumbnail, cached counts |
| `artist` | Each artist, names that differ only in case as one (R2.5.4): the name shown, its sort key (R2.13), cached counts |
| `folder` | One row per folder under the root that has audio beneath it: path, parent, counts of subfolders and songs (direct and beneath), its own cover's source, the mosaic's sources, the worst path-match state beneath it (A2.7) |
| `playlist` | One row per playlist file: path, modification time, smart rule (R8.9) |
| `playlist_entry` | Playlist, position, the path as written, the song it resolves to (or none: missing, R8.7) |
| `play` | Play counts and last played (R7.9), loaded from and saved to `.musikata/plays/`, a file per computer (A2.8) |
| `change` / `change_file` | The change history (R4.9), indexed from `.musikata/history/` (A3.5) |
| `waveform` | Song, the audio's hash, the peaks as a blob (A5.1) |
| `ignored` | Needs attention entries the user dismissed, with the file's modification time (R2.8), from `.musikata/ignored.json` |
| `lookup` | Answers from the online services, by request, with when they were fetched (A7.7) |
| `song_fts` | FTS5 over title, artist, album, album artist, genre, year and file name (R2.7) |

The schema has a version number; migrations are numbered Python functions run in order at start,
in one transaction.

A2.2. **The scan.**

1. Walk the root with `os.scandir`, skipping what R2.3.1 skips.
2. Compare each audio file's size and modification time with its row; unchanged files cost one
   `stat`.
3. Read changed and new files with Mutagen on the worker processes (A1.3), in batches of 200, and
   write each batch in one transaction.
4. Rows whose file wasn't seen are removed at the end, unless the file reappears elsewhere with
   the same `audio_hash`, which is a move: the row's path changes and its play counts stay. None
   is removed when the root itself isn't there (R2.10); the rows beneath a link to a folder that
   can't be reached stay (R2.3.2, R2.10); and when more than a quarter of the library's songs, and
   more than 20, are gone, their removal waits on the user's answer (R2.10.1).

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
- **Mosaic images.** A mosaic is drawn on the thread pool with `QImage` and `QPainter` from its
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
  alone from the counts it keeps in the index, at most once a minute while playing and at quit; the
  count shown is the sum of the files. No two computers ever write the same file, so plays are never
  lost or counted twice, and a root kept in sync by Dropbox, OneDrive or Syncthing gets no
  "conflicted copy" files from them, nor a new upload each time a song ends. A crash loses nothing:
  the counts are in the index, and the file is written at the next start.
- Each entry of `plays/`, `ratings.json` and `ignored.json` names its song by its path under the
  root and its audio hash (A2.3), as in `{"path": "…", "hash": "…", "count": 12, "last": "…"}`. A
  reader matches an entry by path, and by hash when no song has that path, so a song moved by any
  means, by MusiKata (R12) or in a file manager, keeps its plays, rating and dismissal on every
  computer. Two exact copies (R2.12) are told apart by path while both exist. Each computer rewrites
  the paths in its own files when its scan finds a move.
- `ignored.json` and `ratings.json` change seldom and are merged entry by entry: before writing,
  MusiKata reads the file again, and the newest entry wins.
- The change history is one file per entry (A3.5), never rewritten, so there is nothing to merge.
- When `.musikata` can't be written (R1.5.2), the same data is kept in the index only, and the
  root's settings are read and never written.

A2.9. **Finding a root's index.** Each root has an id, made when it is first opened and kept in
`<root>/.musikata/root.json`, apart from the root's settings, which a new root copies (R13.9). Its
index and caches (R1.5) are kept under that id, with the path the root was last opened at, so a
drive given another letter or mount point keeps its index:

- Opened at its last path, the root uses its index.
- Opened at another path, while the last path no longer holds a root with its id, the root has
  moved: the index is used and its path updated.
- Opened at another path while the last path still holds a root with its id, the root is a copy: it
  gets a new id and an index of its own, and is scanned.
- A root whose `.musikata` can't be written (R1.5.2), so that it has no id of its own, is kept under
  a hash of its path instead.

At start, the index and caches of every root not opened for 180 days are removed, and the App log
names each. A root that comes back after that is scanned again, which loses only time (R1.5.1).

A2.10. **The formats.** The files another computer, or another version of MusiKata, reads: the
root's own files (A2.8) and the shared settings (R13.9). Each is JSON in UTF-8, and each has a JSON
Schema in `src/musikata_core/schemas/`, which the tests hold every example below to.

- **A version in each file.** Each carries `"format": 1`. Within a version a change only adds
  fields, and every MusiKata keeps the fields it doesn't know when it rewrites a file, so an older
  computer never erases what a newer one added. A change that can't be made by adding raises
  `format`: a newer MusiKata reads every older format and writes its own; an older one that meets a
  newer format reads what it can and never writes that file, and says so ("Changed by a newer
  MusiKata on Studio-PC; update to change these"), as for a `.musikata` it can't write (R1.5.2).
- **Values it can't use** are reported in the App log and replaced by their defaults (R13.9); the
  rest of the file is kept.
- **Paths** are under the root, with `/` between folders, on every platform. **Times** are UTC, in
  ISO 8601. **Hashes** are the audio hash of A2.3, as 64 hexadecimal digits.
- **Who writes it:** `plays/<id>.json` only its computer; `ratings.json` and `ignored.json` any
  computer, merged entry by entry with the newest `changed` winning (A2.8); a history entry is
  written once and never changed (A3.5); `root.json` once, when the root is first opened (A2.9).

`root.json` (`root.v1.schema.json`):

```json
{"format": 1, "id": "6f1c0a5e-2b7d-4c1e-9a43-0f2d8e5b7c11"}
```

The root's `settings.json` (`root-settings.v1.schema.json`), each group as R13 lists it; a group or
setting left out takes its default:

```json
{
  "format": 1,
  "tags": {"id3_version": "2.4", "write_ratings": true, "rating_scale": "windows-media",
           "history": true, "history_days": 90, "articles": ["The", "A", "An"],
           "keep_modified_times": false},
  "patterns": {"user": ["{albumartist}/{album}/{track} - {title}"],
               "organize": "{albumartist}/{year} - {album}/{disc-}{track:02} - {title}"},
  "album_art": {"file_name": "cover.jpg", "embed_max": 1200, "jpeg_quality": 90,
                "attention_min": 500},
  "playlists": {"folder": "Playlists", "relative": true, "encoding": "m3u8"},
  "lyrics": {"save": "lrc"},
  "skip": ["_Incoming/Unsorted"]
}
```

The shared `settings.json` (`shared-settings.v1.schema.json`). A custom preset is parametric, with
its bands, or graphic, with its ten gains (R19.1); a graphic one fitted from parametric bands keeps
them as `from_bands` until a slider changes (R19.6):

```json
{
  "format": 1,
  "computer": {"id": "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d", "name": "Studio-PC"},
  "library": {"root": "/home/ana/Music", "watch": true},
  "playback": {"device": null, "replaygain": "album", "replaygain_default": -6.0, "resume": true},
  "equalizer": {
    "on": true, "preset": "Car", "by_genre": true,
    "presets": [
      {"name": "Car", "kind": "graphic", "preamp": -2.0,
       "gains": [4.0, 3.5, 1.5, 0.0, -1.0, 0.0, 1.0, 2.0, 2.5, 2.0]},
      {"name": "Late night", "kind": "parametric", "preamp": -3.0,
       "bands": [{"type": "low-shelf", "freq": 100, "gain": 3.0, "q": 0.7},
                 {"type": "high-cut", "freq": 12000, "q": 0.7}]}
    ],
    "genres": {"Classical": "Classical", "Jazz": "Jazz", "Electronic": "Late night"}
  },
  "appearance": {"theme": "system", "analyzer_bands": 96, "analyzer_seconds": 4, "tint": true,
                 "minimize_for_mini": true, "text_size": 100, "reduce_motion": "system"},
  "online": {"allowed": false, "services": {"musicbrainz": true, "coverartarchive": true,
             "lrclib": true}, "save_mbids": true, "check_updates": false},
  "mini_player": {"layout": "card", "places": {"card": {"x": 1600, "y": 80, "w": 300, "h": 582}}}
}
```

`plays/<computer id>.json` (`plays.v1.schema.json`), only the songs this computer has played:

```json
{
  "format": 1,
  "computer": {"id": "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d", "name": "Studio-PC"},
  "songs": [
    {"path": "Lumen Drift/Glass Harbor/04 Signal Fires.flac",
     "hash": "3f6a9c1e5b7d2f8a0c4e6b1d3f5a7c9e2b4d6f8a1c3e5b7d9f0a2c4e6b8d1f3a",
     "count": 12, "last": "2026-11-25T20:41:00Z"}
  ]
}
```

`ratings.json` (`ratings.v1.schema.json`), the ratings kept beside the files (R10.3); `stars` 0 is
a rating cleared, kept so the clearing wins over an older rating from another computer:

```json
{
  "format": 1,
  "songs": [
    {"path": "Lumen Drift/Glass Harbor/04 Signal Fires.wav",
     "hash": "9d2b4f6a8c1e3a5b7d9f2c4e6a8b1d3f5a7c9e2b4d6f8a1c3e5b7d9f0a2c4e6b",
     "stars": 5, "changed": "2026-11-24T18:02:13Z"}
  ]
}
```

`ignored.json` (`ignored.v1.schema.json`), Needs attention's dismissals (R2.8). `about` is the file
or folder an entry is about, or for names that differ only in case, the name; `modified` is the
file's modification time when it was dismissed, so a change to the file brings the entry back:

```json
{
  "format": 1,
  "entries": [
    {"kind": "cover-small", "about": "Lumen Drift/Glass Harbor",
     "changed": "2026-11-20T09:15:00Z"},
    {"kind": "tags-from-path", "about": "_Incoming/track07.mp3",
     "hash": "0c4e6b1d3f5a7c9e2b4d6f8a1c3e5b7d9f0a2c4e6b8d1f3a3f6a9c1e5b7d2f8a",
     "modified": 1795600000.0, "changed": "2026-11-21T10:00:00Z"}
  ]
}
```

A history entry, `history/<time>-<computer id>.json` (`history-entry.v1.schema.json`): each file
saved, with the old value of each field that changed, its old path when it moved (`from`), and its
old cover by hash when the cover changed:

```json
{
  "format": 1,
  "time": "2026-11-25T20:45:12Z",
  "computer": "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d",
  "action": "edit-tags",
  "files": [
    {"path": "Lumen Drift/Glass Harbor/04 Signal Fires.flac",
     "fields": {"year": null, "genre": ["Electronica"]},
     "cover": "5b7d9f0a2c4e6b8d1f3a3f6a9c1e5b7d2f8a0c4e6b1d3f5a7c9e2b4d6f8a1c3e"}
  ]
}
```
