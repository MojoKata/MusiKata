# Testing

What runs when, on which environment. R1.1 promises only what these environments test: an
environment leaves this list, and R1.1, together.

## Principles

- **Most tests are unit tests** of the plain functions of [`coding.md`](coding.md) ("Built to be
  tested in isolation"), on generated data, each in milliseconds. A unit test never starts the app,
  a QML engine, a process or a device.
- **Fewer integration tests:** the scanner over the demo library, the models with a 50,000-row
  library, the worker pool, the audio chain into a null output. **The tour and tier 3** are for what
  nothing smaller can show.
- **Generated data, never real music** (A6.7), and no network or sound card (the end of "What tier 1
  covers"). Each test has a home of its own (`own_home`, `tests/conftest.py`): `HOME`, the XDG and
  Windows folders and `MUSIKATA_DATA` point into its temporary folder, and a run fails when
  MusiKata's files in the real home changed while it ran.
- **Wait for the event, never for a set time.** Logic that runs on a clock is tested by moving a
  fake clock (`coding.md`). A test that must wait on real work (a worker process, a thread, the file
  watcher, a QML view loading, the tour) waits for the signal or state that says it is done
  (pytest-qt's `waitSignal` and `waitUntil`, or polling), under a generous timeout that only a
  failure ever reaches; it never sleeps a set time and hopes the work is finished. The one fixed
  wait is to show that nothing happens (no second rescan of MusiKata's own write, no request while
  lookups are off): it waits a set time, as short as the claim allows, then checks that nothing
  changed.
- **Speed.** A unit test runs in under 100 ms, or is marked `slow`. The rest, run by
  `pytest -m "not slow"`, take under 30 seconds, so they can run on every save; the whole of tier 1
  runs in under 5 minutes. Every run lists its slowest tests.
- **A bug fix starts with its test,** seen failing because of the bug, and both land in the same
  commit. **New code comes with its tests** and its trace rows in the same change, written before or
  after it as the piece suits.
- **Test names say the behaviour,** as a sentence: `test_a_seek_lands_on_the_exact_sample`.
- **The requirements trace.** `docs/requirements/trace.md` gives each sentence of a traced section a
  row naming the tests that show it, `tier 3:` and the check when only a person can show it, `later:
  #n` when it waits on a `future` issue, or `statement` when it promises nothing a test could show.
  A test fails when a sentence has no row, a row no longer matches its sentence, or a named test
  doesn't exist. A section joins the trace when its code is built, and every section of the first
  release (`DEVELOP.md`) is in it by that release.
- **Coverage.** Tier 1 runs under coverage.py, lines and branches, the worker processes included
  (`concurrency = ["thread", "multiprocessing"]`). Each area of `scripts/areas.py` (the core's
  `library`, `tags`, `files`, `playback`, `analysis` and `online`, the `app`, the `scripts`) has a
  floor in `tests/coverage-floor.json` that may only rise: a change that drops an area below its
  floor fails tier 1, and one that raises it moves the floor up in the same change, squashed into
  one commit ([`ci.md`](ci.md), "Coverage").
- **Each module at 80 % before it is ready.** A module of `src/` isn't ready, and its pull request
  doesn't merge, until its tests reach 80 % of it, its lines and branches counted together as
  coverage.py counts them. An area's floor only stops it sliding back, and a new module could
  otherwise arrive half tested and hide behind its neighbours. `coverage_report.py --check` fails on
  a module under 80 %, unless `tests/coverage-exceptions.txt` names it with the reason (a module
  that runs only on Windows or macOS, measured in that platform's run).
- **Data from outside is tested in its real shapes.** A module that reads data it didn't write
  lists, under "Shapes" below, what varies in that data and the test that covers each
  ([`coding.md`](coding.md), "Data from outside: its shapes"), before its code is ready. Missing
  fields, fields in another order, other programs' conventions and older versions' files are where
  most bugs in such code come from, and they are cheaper to list than to find by mutation.
- **Properties, with Hypothesis.** Where a rule holds for every input, a property states it and
  Hypothesis tries inputs: the parsers of outside files never fail but with their own error,
  whatever bytes they get; round trips change nothing (a path made from tags and read back, an M3U
  written and read); invariants hold (the equalizer's output stays under full scale, play files
  merged in any order sum the same, unknown fields survive a rewrite). In tier 1 each property runs
  a fixed set of about 50 examples (`derandomize`), so it is fast and never flaky; a weekly CI run
  and one before each release try thousands of random ones. A failing case found that way becomes an
  `@example` on its test, so it is checked on every run after.
- **Mutation testing.** Once a first pass of the code is written, mutmut sweeps `musikata_core` for
  code the tests run but don't check; each survivor is killed by a new test or noted with the reason
  it isn't worth one. It isn't run as each piece is written; coverage is the measure until then
  ("Mutation testing", below).
- **Gates.** ruff and mypy ([`coding.md`](coding.md)) run in tier 1 beside the tests and the
  coverage floors.

## Shapes

What varies in the data each module reads but didn't write ([`coding.md`](coding.md), "Data from
outside: its shapes"): the list it starts from, which the module's tests cover, each shape by a test
that names it. A module adds the shapes it meets; a bug found in a shape no test had is added here
with its test.

| Module | Its shapes |
|---|---|
| `tags` (A3.2, R4) | ID3v1 only, ID3v2.2, 2.3 and 2.4, and v1 and v2 that disagree; frames repeated or empty; several genres as separate frames, as `;` or `/` in one, or as ID3v1 numbers `(17)`; track as `4`, `04` or `4/10`; years as `2003`, `2003-05-01` or `TYER` with `TDAT`; Vorbis keys in any case and repeated; MP4 freeform atoms, and atoms that are a bool (`cpil`, `pgap`) or numbers (`tmpo`); `POPM` from Windows Media Player, MusicBee and foobar2000, several users' at once (Windows Media Player's preferred, MusiKata's own scale next), at each of R10.4.1's ranges' edges; ratings (R10.4.2) as `RATING` 0 to 5 and 0 to 100, MusicBee's half stars (10 … 90, rounded up), beyond 100, `FMPS_RATING` alone, beside `RATING` and past 1.0, MP4's freeform `RATING` and `FMPS_Rating` in any case; Picard's MusicBrainz ids; the text encodings of R4.10; ReplayGain (R7.5) as `TXXX:REPLAYGAIN_*` in any case (foobar2000's lower case), as ID3v2.4's `RVA2` alone (Quod Libet, Mutagen's EasyID3), in an MP3's APEv2 tag (mp3gain, foobar2000), as Vorbis comments, as MP4 freeform atoms, and as Opus's `R128_TRACK_GAIN` and `R128_ALBUM_GAIN` (1/256 dB to -23 LUFS, no peaks), beside or without `REPLAYGAIN_*`; gains as `-6.20 dB`, `+1.5 dB`, `1,25 dB` or a bare number; an APEv2 tag that can't be read; the tags kept without showing (R4.8): `TXXX` with and without a description, `USLT` with and without one, `PRIV`, `UFID`, `PCNT`, `COMM` of another program (`iTunNORM`), pictures but the front cover, frames it has no name for, Vorbis keys FFmpeg writes (`ENCODER`), MP4 freeform atoms, `©too` and `tmpo`, values too long to show |
| `tags`, writing (A3.2, A3.4, R4.7) | every kind written and read back, every field set and removed, in ID3v2.4 and 2.3; the demo library's shapes (ID3v2.3, ID3v1 beside v2, `TRCK` as `04`, Vorbis keys in lower case, embedded covers); ID3v1 alone (a v2 tag added, the v1 kept in step), ID3v2.2 (written as 2.4, its unknown frames logged), and v1 and v2 that disagree; frames Mutagen doesn't know, and ID3v2.4's `TSOP`, `TSOA` and `RVA2`, through 2.3 and 2.4 both ways; numbered genres `(17)`; other programs' `COMM` (iTunes' `iTunNORM`), `POPM` and play counts, `TXXX`, `UFID`, `PRIV`, lyrics and back covers kept; Vorbis keys in any case and repeated, and their older names (`ALBUM ARTIST`, `TOTALTRACKS`, `DESCRIPTION`); MP4 freeform atoms in any case, `tmpo`, `pgap`; a WAV's RIFF INFO chunk; the cover set and removed beside other pictures; ReplayGain and Opus's `R128_*` untouched; comments a write doesn't know, any number, kept in order (a property); a write failing at each step, a read-only file, a full disk, a file gone or that can't be read, a file in use on Windows; a copy a crash left behind |
| `tags.case` (R3.6.1) | all lower and all upper case, small words inside and at either end, mixed case left alone (`iPhone`, `McCartney`, `k.d. lang`); no letters with a case (digits, marks, Japanese); apostrophes inside and leading (`don't`, `’`, `'til`, `rock 'n' roll`, `o'brien` with one capital); accents composed (NFC) and as a letter and its mark (NFD, as macOS names files), Cyrillic, `ß`; hyphens, slashes and initials (`jay-z`, `rock-and-roll`, `r.e.m.`, `ac/dc`); initials in a value all in capitals kept as spelled (`AC/DC LIVE`, `R.E.M.`, `P.I.L.`, accents as a letter and its mark), at their edges (parts of 3 letters and of 4) and against a lone `/` or `.` between longer words (`ROCK/POP`, `MR. BROWN`, `VOL.2`); digits in and starting words (`deadmau5`, `blink-182`, `1st`, `'80S`); Roman numerals of I, V and X (`ix`, `IV`, `xxxix`) against words of numeral letters (`mix`, `civil`, `iiii`); a part of a title after `:`, `(`, `[` or a dash; spaces, tabs, line ends, `_` and marks kept; a very long value; any text at all (a property) |
| `encodings` (A3.6, R4.10) | text of each script saved in its encoding and held in a frame marked Latin-1, generated: Cyrillic of six languages (Windows-1251), Greek (Windows-1253), Central European (Windows-1250), Japanese (Shift-JIS), Chinese simplified (GBK) and traditional (Big5); real French, German, Spanish, Portuguese, Polish, Czech, Turkish, Icelandic and others in Latin-1 and Windows' Western, never flagged, with its quotes and dashes (0x80 to 0x9F) and the five bytes Windows has nothing for; marks real text holds (`nº 9`, `1ª`, `E=mc²`, Catalan's `l·l`, `©`, `’`); Central European letters Latin-1 reads as letters a language has (`ő` as `õ`), which letters alone can't tell; mixed scripts in one title; short text (two letters, one), numbers and punctuation alone; several fields read together; frames already in Unicode, Latin-1 frames of ASCII alone, ID3v2.3's and v2.4's frames marked Latin-1, the comment's, and an ID3v1 tag alone; any bytes at all (a property); a fix written as Unicode, "as it is" written again as Unicode, Undo writing the old bytes back, and Latin-1 asked of a kind without ID3 |
| `art`, `tags.pictures` (R5.1) | pictures embedded as ID3's `APIC`, FLAC's picture blocks, Vorbis comments' `METADATA_BLOCK_PICTURE` and the older `COVERART`, MP4's `covr` (no picture types; JPEG or PNG); several pictures with the front cover not first, none, an empty one, one that can't be decoded; a folder's images named `cover`, `folder`, `front` or `album` in any case and extension, other images (the largest wins), hidden ones and files that aren't images |
| `art`, the Album art dialog (R5.2 to R5.5) | images from outside, dropped, pasted or chosen: JPEG (with EXIF, fill bytes and restart markers before its frame header; greyscale), PNG with and without transparency (an alpha channel, or a `tRNS` chunk), WebP lossy, lossless and extended, with and without transparency; a CMYK JPEG (made RGB); huge (more than 50 megapixels, or a file over 50 MB), tiny (under 16 pixels a side), larger than 1200 (shrunk to embed), not square; bytes cut short in the header, a header with no image after it, bytes that aren't an image, any bytes at all (a property); a file gone, a folder, a web address; the clipboard's own JPEG or PNG, Qt's image, nothing; the album's pictures: a front cover in some songs and another in the rest, back covers and the artist's photo, MP4's untyped `covr`, a picture that can't be decoded; its folder's images named as a cover in any case, as a back cover (`back`, `CD1`, `inlay`), the largest first, an image too large or that can't be read, `Cover.JPG` in another case; an album over several folders, songs on no album; cover.jpg that can't go to the trash, a folder that can't be written, a replace that fails |
| `covers` (R5.1) | JPEG, PNG with and without transparency, WebP; wide, tall, and smaller than a thumbnail; bytes that aren't an image, a cover file gone, a song whose pictures can't be read; a cached thumbnail cut short; a cache folder that can't be written; a folder's mosaic of one to four pieces, some or all of which can't be shown (R5.8) |
| `playlists` (R8.1.2) | absolute and relative paths, `\` and `/`, `file://` URLs (escaped, `localhost`, a share's, a drive's), Windows paths in another case and on another drive, an address on the web; `#EXTINF` and without, its length negative, a fraction, not a number or with attributes after it (`-1 tvg-id="x"`), one with no entry after it; `#EXTM3U` and without, `#PLAYLIST:` and R8.9's `#MUSIKATA-RULE:` before the first entry (kept), other programs' comments among the entries (`#EXTGRP`, `#EXTVLCOPT`); a BOM (UTF-8's, UTF-16's), CRLF and CR, spaces around a line; `.m3u` in the system's encoding, an `.m3u8` that isn't UTF-8; comments and blank lines; files missing, outside the root, or listed twice; none, one and 5,000 entries, a very long path; any bytes at all (a property); a file changed by another program since it was read, gone, or that can't be read or written; the root's `playlists.folder` absolute, with `..`, hidden, empty or not text |
| `smart` (R8.9, A2.10) | the rule after `#MUSIKATA-RULE:`: empty, not JSON, JSON cut short or nested deep, not an object; `format` missing, as text, a bool, or newer (read for what it can, never written); fields in another order, named twice, and fields it doesn't know (kept when it is written again); `rating` as text, a whole fraction, 0, 6, a fraction, a bool, `null`, too large for a float; `genre` and `artist` empty, spaces, not text, in another case; `years` the other way round, a year alone, an end `null`, both `null`, one element, not numbers, `NaN`, an object; `added`, `plays` and `limit` 0, negative, as text with a sign; `order` in another case, with spaces, unknown, not text; the rule line in lower case, twice, beside `#PLAYLIST:`; names holding line ends, a NUL and U+2028 (still one line); any text at all, and any rule written and read back (properties); a playlist's rule changed by another program since it was indexed (not refilled), and one that can't be written (logged, tried again after its pace) |
| `dragging` (R6.10, R8.5) | MusiKata's own drag format (from this MusiKata or another one): not JSON, not an object, another root's, `songs` missing, not a list or holding text or bools, `entries` not a list, `playlist` not a number; a file manager's drop: files and folders under the root and outside it, a path through `..` out of it, a Windows root in another case and a drive outside it, `file://` URLs with escapes, an address on the web, a file that isn't a song of the library (a cover, one not scanned yet), a folder and a file inside it (each song once), nothing |
| `lyrics` (A7.6, R17) | times as `[mm:ss]`, `[mm:ss.xx]` and `[mm:ss.xxx]`, several on one line; `[ar:]`, `[ti:]` and `[offset:]`; lines out of order, blank, or untimed; word times `<mm:ss.xx>`; a BOM and CRLF |
| `attention` (A2.6, R2.8) | the `.cue` sheet: `FILE` with and without quotes, in lower case, after a folder a ripper wrote (`C:\Rips\`), naming a file twice, none, several, or the file by another extension (the WAV a FLAC was made from); the sheet in UTF-8 with and without its BOM, or the system's encoding (cp1252, Latin-1); `REM` lines; `INDEX 00` and `01`; CRLF; a sheet that can't be read; any bytes at all (a property); names (R2.8): case, spaces inside, around and as tabs, accents composed and as a letter and its mark, `ß`, Cyrillic, against accents and punctuation (kept), and any name (a property); an album's names by two artists; a cover's size: a JPEG's header (the rest are `art`'s), bytes that aren't an image, a folder's image gone or known already |
| `audio` (`decode`, A4.1; `analysis.waveform`, A5.1) | the waveform's: a sine, a silence, a click, a song of one sample and of three hours, stereo folded to mono, a length the file doesn't say or gets wrong either way, a file missing or not audio, a waveform kept broken or of another size; every kind of R2.2; samples of 8, 16, 24 and 32 bits, float and double, packed and planar; mono, stereo, quad, 5.1 and 7.1, and a WAV that names no channels; rates from 8 to 192 kHz; a cover FFmpeg sees as a video stream; a damaged file, and damage FLAC's decoder hides; a file that ends early, and one cut before what it needs to open; an empty file, noise, a missing file and one with no audio; the silence encoders add (A4.2): an MP3's LAME header, CBR and VBR, behind an ID3v2 tag with a cover, and an MP3 with no LAME or Xing header (nothing says its silence); AAC in MP4 with an edit list, with only `iTunSMPB` (no edit list), and with both as iTunes writes them; Opus's pre-skip and end; a seek (A4.6) in each kind, at its start, in its first 0.2 s, in its middle, near its end and past it, at the file's rate and resampled; a seek FFmpeg can't make, or makes past the sample, or after which frames have no time; the last page of an Ogg file FFmpeg's own Vorbis encoder wrote, timed wrong after a seek |
| `audio.eq` (R19.7) | with and without `Preamp:`; filters `ON` and `OFF`; `PK`, `LSC`, `HSC`, `LP`, `HP` and types it doesn't read; `Fc` with and without `Hz`; `Q` against `BW`; comments; more than ten bands |
| `online` (A7) | fields missing, `null`, empty or added; dates as a year, a month or a day; several matching releases; answers `503` and `429`; slow answers; text in any script |
| `rootfiles` (A2.10) | each older format, and a newer one; unknown fields and groups; values broken or out of range (R13.9); two computers' entries for one song; a file cut short by a sync in progress; a sync tool's "conflicted copy" beside it. `plays.json` (R7.9, A2.8): no file; a file empty, cut short, not JSON, not an object, or its `songs` not a list, or none; a BOM, fields in another order; `format` missing, as text, a bool, or newer (read, never written); `computer` missing, not a group, its `id` empty or not text; a song not an object, its `path` missing, empty or not text, its `count` missing, `0`, negative, a fraction, a bool, `null`, `"12"` or `12.0`, its `hash` in upper case, missing, `null` or not an audio hash, its `last` missing, without its zone, in another zone, with fractions of a second, or not a time; a song named twice; fields it doesn't know, the file's and a song's, kept when it writes; one song and 5,000; any text and any shape at all (properties); songs moved (found by hash), gone (their plays to an exact copy, or kept in the file), not yet scanned, or found by hash before the song with their path was; files read in any order (a property); a file that can't be read; a computer's folder copied by a sync ("… (conflicted copy)", naming another computer), a computer's folder gone, and a file broken after it was read (what was read stays) |
| `rootfiles`, `ignored.json` (R2.8, A2.8, A2.10) | no file; a file empty, cut short by a sync in progress, not JSON, not an object, or its `entries` not a list (never written over); a BOM, fields in another order; fields it doesn't know, the file's and an entry's, kept when it writes; `format` missing, as text, or newer (read, never written); an entry not an object, its `kind` missing, empty or not text, its `about` missing or empty, its `hash` in upper case or not an audio hash (found by its path only), its `modified` as text (a number or not), a bool, `NaN`, negative or `null`, its `changed` missing, without its zone or in another zone; an entry named twice (the newest kept); another computer's entries written between a read and a write, merged in any order (properties); any text at all (a property); a song moved (found by hash) and a copy still at the old path; a `.musikata` that can't be written (the index only) |
| `ratings` (R10.3, A2.8, A2.10) | `ratings.json`: no file; a file empty, cut short by a sync in progress, not JSON, not an object, or its `songs` not a list (never written over); a BOM, fields in another order; fields it doesn't know, the file's and a song's, kept when it writes; `format` missing, as text, or newer (read, never written); a song not an object, its `path` missing or empty, its `stars` as text (`"4"`), `4.0`, out of range, a bool or `null`, its `hash` in upper case, missing or not an audio hash (found by path only), its `changed` missing, without its zone, in another zone, or not a time; a song named twice (the newest kept); `stars` 0, a rating cleared; another computer's entries written between a read and a write, merged in any order (a property); any text at all (a property); songs moved (found by hash), and an entry left at a moved song's old path beside an exact copy still there; a `.musikata` that can't be written (the index only); the root's settings' `write_ratings` not true or false, `rating_scale` in another case, with a space or `_`, or none of `windows-media` and `musikata` |
| `settings` (R13.9, A2.10) | the root's `patterns.organize` (R12.1): none, empty, not text, with spaces around it; no file (the first start); a file empty, cut short by a sync in progress, not JSON or not an object; a BOM (Notepad); fields in another order, and fields and groups it doesn't know, kept when it writes; `format` missing, as text, a bool, or newer (read, never written); `library` not a group; its `root` missing, `null`, empty, not text, relative, with `~`, or with a trailing separator; `watch` not true or false; `computer` missing, not a group, or its `id` empty or not text; `playback` not a group, its `device` not text or empty, its `replaygain` in another case or none of `album`, `track`, `off`, its `replaygain_default` as text (`-8.5 dB`), a bool, `null` or `NaN`, its `shuffle` not true or false, its `repeat` in another case or none of `off`, `all`, `one`; a sync tool's "conflicted copy" beside it; a file that can't be read or written, and one cut short or newer, which shuffle, repeat and this computer's id are never written into; the root's own `settings.json`: none, broken, its `tags` not a group, `id3_version` as a number (`2.3`), as `v2.3`, or none of `2.3` and `2.4`, `keep_modified_times` not true or false; `genres` not a list, holding what isn't text, empty names or one twice, empty (no list at all); `same_genres` not a list, a group not a list, of one name, of a name empty or not text, beside a group that holds |
| `nowplaying` (R1.8, A2.8, A2.10) | no file (the first start); a file empty, cut short by a sync in progress, not JSON, not an object, or its `songs` not a list, a song not an object or its `path` missing, empty or not text (an empty queue); a BOM, fields in another order; fields it doesn't know, the file's and a song's, kept when it writes; `format` missing, as text, a bool, or newer (read, never written); a `hash` in upper case, missing, `null` or not an audio hash; `added` not true or false; `unshuffled` places missing, repeated, out of range, a bool or text; `current` missing, `null` (played out), out of range, negative, text, a bool or a fraction; `position` missing, negative, text, `null`, a bool or `NaN`; `saved` not a time or without its zone; `source` not text; any text and any shape at all (properties); songs moved (found by hash), gone, the current one gone with songs after it or none, two copies with one hash; the root's copy and the one beside the index, either the newer, either broken or unreadable; a sync tool's "conflicted copy" beside it |
| `history` (R4.9, A3.5, A2.10) | a move's `from` (R12): outside the root, not text, beside fields or alone; a file moved since (found by hash), one whose old place another file has taken, one gone; an entry: none, empty, cut short by a sync in progress, not JSON, not an object; a BOM, fields in another order, fields it doesn't know (the entry's and a file's); `format` as text, or newer (skipped: never undone by an older MusiKata); `time` missing, without its zone or not a time (its name's), and neither; `computer` missing or not text (its name's); `action` and `description` not text; `undoes` not an entry's name; `files` not a list, empty, a file not an object, its `path` absolute, with `..`, `.`, a drive or `\` (never outside the root), named twice; `hash` in upper case, short or missing (found by path only); `fields` and `new` not groups, a field it doesn't know (`lyrics`), a value of another type (`track` as text, `genre` not a list, `rating` 9, `compilation` as text), `new` missing (an older entry: any value but the old one would be lost); `cover` not a hash, `null` (there was none), in upper case, `new_cover` missing or not a hash; R5.3's `pictures` not a list, a picture not an object, its `type` text or a bool, its `image` not a hash or in upper case, `new_pictures` holding what isn't a hash; an image file's `image` not a hash, `null` (there was none) or in upper case, `new_image` not a hash; R2.12's `plays_from` and `plays_to` not lists, `null`, a song in them not an object, its path outside the root, its `count` none or 0, its `hash` short and its `last` not a time, `trashed` not true or false, a file of plays alone or moved to the trash alone; a name not an entry's (a sync tool's "conflicted copy", a temporary file), an entry that can't be read; any text and any shape at all (properties); another computer's entries, named by its play file or not; a file moved (found by hash), gone, read-only, or changed since in a field, the cover and the other pictures included; a cover.jpg changed since, or that can't be read; an old cover gone or not the cover it is named for |
| `genres` (R9) | names that differ only in case (`Electronic`, `electronic`, `ELECTRONIC`), spacing (`Hip Hop`, `hiphop`, two spaces, spaces around), punctuation (`Hip-Hop`, `Hip.Hop`, `Hip_Hop`, `Electronic!`), accents composed and as a letter and its mark (`électronique`), `ß` and a script with case but no Latin letters (`Шансон`); "&", "and" and a lone "n" (`Drum & Bass`, `Drum and Bass`, `Drum'n'Bass`, `rock-n-roll`, `R&B`, `R'n'B`) against a word that only holds an n (`RnB`); slashes as any mark (`Rock/Pop`, `Rock / Pop`, `Rock\Pop`) and two names in another order (`Pop/Rock`); ID3's numbered genres as text, bare, in brackets, spaced, out of the list's range or not numbers alone (`13`, `(13)`, ` ( 13 ) `, `(255)`, `1999`, `Pop (13)`), and an ID3 tag's numbers after a ";" (`13; (8)`), which Mutagen leaves as text; names that differ by more (`Electronic` and `Electronica`, `Rock` and `Rocks`, `Indie` and `Indie Rock`) and the user's own sames (`same_genres`), chained through a shared name, naming genres the library hasn't, or empty; names of marks alone, empty or spaces; used as often (the capital first); a song holding two names merged into one, and the name merged into in another case; a new name empty, spaces, or holding ";" or a NUL; any text at all, and any library (properties) |
| `search` (R2.7, A2.5) | what users type: accents and case (`beyonce`, `MOTLEY crue`); the last word half typed; quotes closed, left open, empty or inside a word (`12"`); FTS5's own operators and marks as text (`OR`, `NOT`, `NEAR(`, `*`, `^`, `-`, `{}`, `:`); a lone `-` and other marks with no word in them; a known `field:` in any case, with no value yet, a word, a phrase or a comparison (`rating:>=4`, `rating:>= 4`, `=>`, `≥`, `rating:4`, `year:<2000`, `year:201`), and a comparison with no number (`rating:high`); an unknown `field:` (`bpm:120`); a NUL; nothing, and anything at all (a property); the values the Edit tags panel suggests (R4.6): accents and case, the start of a later word (`drift`), the value already typed, two spellings of one name, nothing typed |
| `media` (A4.5, R7.8) | commands from a desktop, Windows' overlay or Control Centre while a song plays, is paused, is only cued, or none is shown; a song outside the queue (no next or previous); MPRIS's Seek before the start or past the end, with and without a song after; SetPosition for a track no longer shown, before the start or past the end; a Volume outside 0 to 1; a Rate set, OpenUri; a button MusiKata doesn't enable (Windows' Record); a command from another thread; a second MusiKata on the bus; no session bus; Windows' controls without seeking (Wine's, no `ISystemMediaTransportControls2`) |
| `inotify` (A2.4) | the records the system writes: a name NUL-padded, and none (an event on the folder itself); a record cut short at the end of a read; a name not in UTF-8; a rename's two ends; the queue overflowed; a watch the system ended (`IN_IGNORED` after its folder went or its drive was unmounted); two paths to one folder sharing a watch; a folder refused (gone, not a folder, the limit on watches) |
| `organize` (R12, R12.5) | the folders beside the songs: images in any case of extension, `.cue`, `.log`, a song's own `.lrc` and another's, files that stay (`.nfo`) and subfolders, a system's clutter (`.DS_Store`, `Thumbs.db`, `desktop.ini`), a folder that can't be listed or read; paths that differ only in case or in a letter's form (NFC against NFD) as one path; files dropped from outside: folders and files, a file named twice, hidden ones, what isn't audio, a file that can't be read, the same audio retagged, files whose tags are missing; any songs and any files beside them (a property); a `.cue` sheet moved with the files it names (A2.6's shapes): `FILE` quoted and not, in lower case, with a tab after it, after a ripper's folder (kept), naming a subfolder's file (left), the name in another case; UTF-8 with its BOM, cp1252; CRLF, LF and CR, each kept; a name its encoding can't hold (left); a sheet that can't be rewritten (moved, logged); any checkboxes changed in any order over any plan (a property) |
| `patterns` (R3, A3.3) | odd characters, deep and shallow folders (an album's folder under more folders than a pattern has, a path shallower than it), numbers in names (`04`, `004`, `00`, `1-04`, a year of four digits and not), `Disc 1` and `CD1` folders, names longer than a platform allows; `/` and `\` between folders; names as macOS writes them (a letter and its mark); an extension, none, and dots inside a name (`Mr. Brown`, `Vol. 2`); runs of spaces, ` - `, ` – `, `_-_` and an em dash that isn't one; underscores for spaces; a separator inside a title (`Signal Fires - Live`); a year at a folder name's start, in brackets or after a mark at its end, a year alone, a number that isn't one (`1812`, `0999`); tags spelled with what a name can't hold (`AC/DC`, `What?`, `Live: Paris`), in mixed case (`McCartney`), in lower case as the path spells them (`ebb & flow`), all in capitals with initials; a genre among several; a folder with a stray file, a track missing, two discs; patterns half typed: empty, a brace not closed, a token R3.2 hasn't, no token; the user's patterns (`patterns.user`) not a list, holding what isn't text or blanks, named twice; any pattern on any path, and any folder of any songs (properties); the layout (R12.1): the naming forms in a pattern to read and `{*}` in a layout, tags missing (no year, track, album, artist or title; a compilation naming no album artist), the sort names with and without their tags and an article, two discs, what a file system refuses in a tag (`AC/DC`, `What?`, control characters), spaces and dots at a name's ends, names longer than 120 characters or 255 bytes (three- and four-byte characters), a letter and its mark, Windows' device names (`CON`, `nul.txt`, `COM¹`) against names that only start so (`CONSOLE`, `COM10`); any tags and any layout text (properties) |

## Tiers

| Tier | When | What it's for |
|---|---|---|
| 1 | every change | ruff, mypy and the whole pytest suite with its coverage floors, in one container on the release's Python and PySide6, offscreen: the gate for every commit, run by CI on every pull request and push to `master` |
| 2 | before pushing | the tour and its layout check at 100 % and 150 % text (R18.3), the size and speed targets of R1.11 on the demo library built at 50,000 songs, the AppImage built and started, the Windows suite in its VM |
| 3 | before a release | each platform's build installed and used by hand: playback through real speakers, media keys, drag and drop with the platform's file manager, the mini player moved, resized and kept on top, the platform's screen reader through every view (R18.1), the music root's drive unplugged and plugged back (R2.10), an update from the previous release (R1.9); the field test's checklist is `scripts/field_test.py`, run per environment before a release ([`release.md`](release.md), 4) |

### What each run may skip

Every pytest run a tier makes names its list of the tests it may skip, and why:
`tests/skips/<name>.txt`, chosen by `MUSIKATA_SKIPS=<name>` (`tests/conftest.py`). A skip the list
doesn't name is a failure, and so is a listed test that ran (take it off the list), so a run's
summary line counts both. The lists: `tier1` (CI's too), `windows` (the suite in the Windows VMs)
and `macos` (the suite on the Apple silicon runner). A test that exists for one platform, MPRIS on
Linux or the media controls on Windows and macOS (A4.5), is listed as a skip on the others, so it
can never skip unnoticed on its own. A run by hand, without `MUSIKATA_SKIPS`, checks nothing. A skip
that comes and goes with the machine (a tool missing from an image) is a fault of the run, not an
entry for the list.

## What tier 1 covers

- **Tags, per file kind.** For every kind of R2.2, a generated file is written and read back for
  every field of R4.1 (A3.2), with unknown frames, several genres, covers and ratings, and checked
  byte for byte against what other readers expect (`POPM` values, `TRCK` as `4/10`).
- **Safe writes** (A3.4): a write interrupted at each step leaves the original intact; a read-only
  file and a full disk are reported, not damaged.
- **Path patterns** (R3): a table of paths and patterns with the tags each should give, including
  the presets, the equivalences of R3.2.1, tidy case and year from folder; detection picking the
  right preset on folders of each layout.
- **Organize files** (R12): the layout's paths on Linux, Windows and macOS rules, conflicts,
  sidecar files, playlists updated, and Undo putting everything back.
- **Playlists** (R8): M3U and M3U8 read in every form R8.1.2 lists, written as R8.1 says, round
  trips that change nothing, missing entries and Find.
- **The library** (R2, A2): scans of the demo library, a second scan reading nothing, moves found by
  audio hash, search terms.
- **Folders** (R2.9, R5.8, A2.7): folder rows after scans, moves and deletes, up through the
  ancestors; the mosaic chosen for trees of every shape (1 to 5 subfolders, nested mosaics, no art
  anywhere); a selection of folders resolving to the songs beneath them.
- **The change history** (R4.9): every kind of save undone and redone, on one computer and from
  another.
- **Playback** (R7.6, R19, A4): joins between generated songs of known length are sample-exact,
  across sample rates and kinds, with MP3, AAC and Opus padding trimmed; seeking lands on the
  sample; the equalizer's measured response matches each preset's curve, for every band type;
  parametric to graphic and back gives the same bands; Equalizer APO files round-trip; nothing
  clips, and the level held down matches the preamp and the largest boost.
- **The root's own files** (A2.8, A2.9): two computers playing at once each write their own play
  file and the sums add up; `ignored.json` and `ratings.json` written at once lose nothing; a song
  moved in a file manager keeps its plays, rating and dismissal on the other computer; a read-only
  `.musikata` keeps everything in the index; a root mounted at another path finds its index, and a
  copy of a root gets its own.
- **Sort names** (R2.13): sort tags win, articles are skipped without them, and the sort tokens of
  R12.1 move the article to the end.
- **Sleep timer** (R7.10): each choice stops at its time or at the end of its song or album, the
  fade ends at silence, and the volume is back where it was.
- **Encodings** (R4.10): tags in each candidate encoding detected and fixed, and real Latin-1
  (French, German) never flagged.
- **Duplicates** (R2.12): exact and likely copies found, the best copy proposed, plays, ratings
  and playlists moved to it.
- **A missing music root** (R2.10): a root that vanishes, half vanishes or comes back, with the
  library kept and nothing removed without asking.
- **Accessibility** (R18): every QML control has an accessible name and role; every text token
  against every surface it is used on meets R18.4's contrast.
- **Online lookups** (R16, R17.4, A7): each service against recorded answers, errors and
  `Retry-After` included; release matching on albums with missing, extra and reordered songs;
  nothing requested while lookups are off; lyrics read from and written to `.lrc` files and every
  kind of tag (R17.1).
- **The analysis** (A5): peaks and bands of generated tones land where they should.
- **QML**: the models with a 50,000-row library; the views load with no QML warnings.

Tests never need the network or a sound card: playback tests play into a null output and check
positions and signals, and online lookups use recorded answers (A7.8). Qt has no null output of its
own, so tier 1's container runs PulseAudio with a null sink (`scripts/test-tier1.sh`); a run by hand
without one skips the playback tests rather than play tones through the speakers. Only
`scripts/check-services.py`, run by hand and weekly in CI, talks to the real services.

## The clock harness

MusiKata's own code takes a clock ([`coding.md`](coding.md)), so its tests move a fake one.
`scripts/test-clock.sh` finds the test, or the library call, that reads the real clock anyway: it
runs tier 1 at the start, middle and end of the UTC day, at a year's end, in the zones furthest from
UTC either way (UTC+14 and UTC−12) and in US Central with its daylight saving time, each by
`scripts/test-tier1.sh` with `MUSIKATA_CLOCK` and `MUSIKATA_TZ`. libfaketime moves every process's
clock by an offset, so the clock still runs and the processes a test starts share it. A test that
passes at one hour and fails at another is a bug like any other: its fix starts with the run that
shows it. The harness runs before a release, and whenever a change touches dates, times or their
display ("last played", the 180-day cleanup of A2.9, the sleep timer).

## Environments

| Environment | Tier | Runs |
|---|---|---|
| Ubuntu 24.04 container | 1, 2 | the suite (CI too); the tour and its layout check |
| Ubuntu 22.04 container | 2 | the AppImage build, on the oldest glibc it supports |
| Linux Mint 22.3, LMDE 7, Ubuntu 26.04 | 2, 3 | the AppImage started on X11 and Wayland, MPRIS seen by the desktop |
| Windows 10 22H2 VM | 2, 3 | the installer, the suite on Windows, the tour, uninstall |
| Windows 11 VM | 2 | the installer, the suite on Windows, the tour, uninstall: what can be automated, and never a field test |
| macOS 14 or newer, Apple silicon (CI runner, and a real Mac) | 2, 3 | the arm64 bundle, the suite on macOS |
| macOS, Intel (the owner's Mac, on the newest macOS it runs) | 3 | the x86_64 bundle installed from the tap and used by hand |

## CI

GitHub Actions, each action pinned by commit SHA: tier 1 on every pull request and push to `master`;
the tour, with its screenshots kept as the run's artifact; the four builds (`appimage`, `windows`,
`macos-arm64`, `macos-x86_64`), unsigned, each with its `.sha256`; once a week,
`scripts/check-services.py` against the real services (A7.8), failing the run when one has changed.
A `v*` tag builds without caches and, once approved, signs the builds and drafts a release
([`build-and-release.md`](build-and-release.md)). Beside tier 1, CI measures coverage by area and
publishes the Pages site, and a failed step posts why ([`ci.md`](ci.md)).

## Mutation testing

[mutmut](https://github.com/boxed/mutmut) changes MusiKata's code one change at a time (a `<` for a
`<=`, a string emptied, a call's argument dropped) and runs the tests on each change. A change some
test fails on is **killed**; one every test passes with **survives**, and shows code the tests run
but don't check. It complements coverage, which says only that a line ran. The sweep is
`musikata_core`'s areas (`library`, `tags`, `files`, `playback`, `analysis`, `online`); mutmut can't
change QML, and the app's bridge code is mostly Qt's to run. The first sweep comes once a first pass
of the code is written, never as each piece is written.

`scripts/mutate.py` holds the tools. mutmut changes the code it tests, so a run never touches the
checkout: it works in a copy (`MUSIKATA_MUTATE_WORK`, `build/mutate` unless set) with `src/`,
`scripts/` and `tests/` copied and the rest of the repository linked, so the tests read it as in
tier 1. It runs in tier 1's container, on the release's Python and PySide6
(`scripts/test-mutate.sh`, mutmut pinned as `MUTMUT` in `packaging/versions.env`), with all of tier
1's tests but those `UNFIT` names, each with its reason. mutmut runs every test once first, noting
the functions each one reaches, then runs each change against only the tests that reached its
function. Code a test reaches only in a process it starts, a worker process included, is out of
mutmut's sight: its changes count as **no tests**, so a worker's job is tested by calling it
directly ([`coding.md`](coding.md)).

mutmut stops at the first test that fails in that first pass, without naming it. A run then runs
pytest over the copy and runs each test that fails there once more on the checkout. A test that
fails on the checkout too is a real failure, and stops the run; the others are left out of the run,
each named in its export with its traceback and the kind of failure it looks like, and settled
before a baseline is kept: added to `UNFIT` with its real reason, or the test changed so it doesn't
depend on the copy, never by weakening what it checks.

### A run by hand

```sh
sh scripts/test-mutate.sh run src/musikata_core/audio/eq.py --workers 3
sh scripts/test-mutate.sh summary            # the outcomes by file, the survivors by function
sh scripts/test-mutate.sh check CHANGE tests/test_audio_eq.py   # one change against one test file
```

A run's container is capped at `MUSIKATA_MUTATE_MEMORY` (6 GB unless set), swap included. The run
watches its own memory: past `--limit` GB it stops, and a change's worker past `--worker-limit` GB
of its own is stopped, that change counted killed. `--only` runs named changes again, `--debug` puts
each of mutmut's pytest runs in its log, and `--resume DIR` goes on from an earlier run's `export`
folder.

### The baseline

The `mutate` workflow (`.github/workflows/mutate.yml`) runs the areas side by side on GitHub's
runners, started by hand (Actions, `mutate`, Run workflow):

- **`plan`** packs each area's modules (`scripts/areas.py`) into jobs of about `size` code lines
  (1000), the largest first; a larger module is a job of its own. Jobs are named by area (`tags-1`,
  `audio-2`), the same for the same tree, so `jobs` runs chosen ones again.
- **Each job** is a `run` of its modules with 4 workers, stopped before the runner's six hours so
  what finished is kept, and an `export`, kept as its `mutation-<job>` artifact for 90 days. At most
  `parallel` (14) run at once, leaving room for pull requests' checks.
- **`resume`**, an earlier run's id: each job runs only the changes its artifact there left without
  an outcome, so a job out of time goes on where it stopped.

`scripts/mutate.py gather RUN...` downloads a run's artifacts and writes each area's baseline and
survivors to `docs/hardening/mutation/` ([`../hardening/README.md`](../hardening/README.md));
`record --from DIR...` does the same from a local run's `export` folders. Runs gathered together
must be of one commit, and a later run's outcome for a change replaces an earlier one's.
`scripts/mutate.py stale` names each module whose content (its git blob) isn't what its area's
latest record mutated, and each module an area holds that no record covers; the hardening page
([`ci.md`](ci.md), "The Pages site") marks those areas "baseline, changed since".

The baseline records the survivors; it doesn't settle them. Each area settles its own by the shared
`mutation` skill (`agents/skills/mutation/SKILL.md`): a test that fails on the change, a change to
the code, or `# pragma: no mutate` on the line with the reason it can't be caught (an equivalent
change, say). An area with more than about 200 survivors is settled in a relay. A settled area runs
again (`jobs`) and its baseline is gathered again.
