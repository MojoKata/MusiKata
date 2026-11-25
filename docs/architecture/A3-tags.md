# A3. Tags

A3.1. **Mutagen.** Mutagen reads and writes ID3v1/v2.2–2.4, FLAC, Ogg Vorbis, Opus, MP4, AIFF
and WAV, in pure Python, and leaves frames it doesn't understand as they are (R4.1.1).
Alternatives weighed: TagLib through `pytaglib` (fast, but a native build per platform and
weaker handling of unknown frames) and writing our own (no).

A3.2. **The field mapping.** One table in `musikata_core/tags.py` maps each R4.1 field to each
kind; everything else reads and writes through it.

| Field | ID3v2 | Vorbis comment (FLAC, Ogg, Opus) | MP4 |
|---|---|---|---|
| Title | `TIT2` | `TITLE` | `©nam` |
| Artist | `TPE1` | `ARTIST` | `©ART` |
| Album | `TALB` | `ALBUM` | `©alb` |
| Album artist | `TPE2` | `ALBUMARTIST` | `aART` |
| Track / total | `TRCK` (`4/10`) | `TRACKNUMBER`, `TRACKTOTAL` | `trkn` |
| Disc / total | `TPOS` | `DISCNUMBER`, `DISCTOTAL` | `disk` |
| Year | `TDRC` (2.4), `TYER` (2.3) | `DATE` | `©day` |
| Genre | `TCON` | `GENRE` (one per value) | `©gen` |
| Composer | `TCOM` | `COMPOSER` | `©wrt` |
| Comment | `COMM` (lang `eng`, no description) | `COMMENT` | `©cmt` |
| Compilation | `TCMP` | `COMPILATION` | `cpil` |
| Rating | `POPM` (R10.4) | `RATING`, `FMPS_RATING` | `----:com.apple.iTunes:RATING` |
| Cover | `APIC` type 3 | `METADATA_BLOCK_PICTURE` (Ogg), picture block (FLAC) | `covr` |
| ReplayGain | `TXXX:REPLAYGAIN_*` | `REPLAYGAIN_*` | `----:com.apple.iTunes:replaygain_*` |

A3.3. **The pattern engine** (R3) compiles a pattern into a regular expression over the path
relative to the root, with `/` separators and the extension removed: each token becomes a lazy
named group (`(?P<title>.+?)`, digits for `{track}`, `{disc}` and `{year}`), literal text is
escaped with the equivalences of R3.2.1, and the whole is anchored. Detection (R3.4) runs every
pattern over every file of the selection, which for a few thousand files is milliseconds. The
same parsed pattern, run the other way, formats paths for R12.

A3.4. **Safe writes.** Mutagen writes in place, so a crash or a full disk mid-write could damage a
file. MusiKata instead:

1. copies the file to `.<name>.musikata-tmp` in the same folder;
2. writes the tags to the copy and flushes it to disk;
3. checks the copy reads back with the new tags and the same audio hash (A2.3);
4. replaces the original with it in one rename (`os.replace`), keeping the original's
   permissions, and its modification time when R4.7.1 says so.

On Windows a file open in another program can't be replaced; that is reported (R4.7) and the copy
removed. Leftover `.musikata-tmp` files from a crash are removed at the next scan.

A3.5. **The change history** keeps, for each file written, its path and the old value of each
field that changed (covers by hash, with the old image kept in the cache until the entry
expires). Undo is another write of those values, through A3.4, and is itself recorded, so it can
be redone. Entries past their age (R4.9) are deleted at start.

A3.6. **Text encodings.** Tags are read as Mutagen decodes them; ID3v2.3 frames in Latin-1 that are
really another encoding (common in old rips) are left as read (Q8).
