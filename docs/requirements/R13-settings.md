# R13. Settings

R13.1. **The Settings dialog** (Ctrl+, / ⌘,, or ⋮ › Settings…) has its groups down the left and
the chosen group's rows on the right (`S01-settings-tags`). Each row has a name, one line saying
what it does, and its control. Changes take effect at once; there is no Save button.

R13.2. **Library**: the music root (R2.1), with **Change…** and **Rescan**; **Watch for changes**
(R2.4, on); the folders to skip (R2.3.1, R2.11.1).

R13.3. **Tags**:

- **ID3 version for MP3**: 2.3 or 2.4 (the default) (R4.7.2).
- **Write ratings into the files** (on) (R10.3).
- **Rating scale in files**: Windows Media (the default) or MusiKata (R10.4.1).
- **Keep a history of tag changes** (on), and for how many days (90) (R4.9).
- **Genre list**: **Edit list…** (R9.6).
- **Articles skipped when sorting**: The, A, An, with **Add** and remove (R2.13).
- **Leave file modification times alone** (off) (R4.7.1).

R13.4. **Path patterns**: the user's patterns for R3, tried before the presets, with **Add**,
reorder and remove; the Organize files layout (R12.1) with a live example from the library.

R13.5. **Album art**: the cover file name (`cover.jpg`), the largest size to embed (1200 × 1200),
the JPEG quality (90) (R5.3), and the smallest size before Needs attention reports a cover
(500 × 500) (R5.6).

R13.6. **Playlists**: the playlists folder (R8.1); **Relative paths** (on); the encoding for new
playlists (`.m3u8`, UTF-8; or `.m3u` in the system's encoding for old players).

R13.7. **Playback**: the output device (R7.7); **Equalizer…** (R19); ReplayGain: Album, Track or Off
(R7.5), and the pre-amp for songs without it; **Resume where I left off** (on) (R1.8).

R13.8. **Appearance**: the theme (Match system, Dark, Light) (R6.2); the visualization's bands and
speed (R11.3.1); **Tint views with the cover's colour** (on) (R6.2.2); **Minimize MusiKata when the
mini player opens** (on) (R15.1); **Text size**, 90 % to 150 % (R18.3); **Reduce motion**: Match
system (the default), On or Off (R18.5).

R13.9. Settings are kept as `settings.json` in two places (R1.5), and Settings shows which a row
is in. Both files are readable and hand-editable; an unknown or broken value is reported in the log
and its default used.

- **The root's own,** in its `.musikata/`: the settings that decide what is written into the root's
  files, so the root is written the same way on any computer and when opened with `--root`
  (R2.1.2): Tags (R13.3), Path patterns and the Organize layout (R13.4), Album art (R13.5),
  Playlists (R13.6), Lyrics (R13.11), and the folders to skip (R13.2).
- **Shared,** in the shared settings folder: what belongs to this computer and this person: the
  configured root and **Watch for changes** (R13.2), Playback and the equalizer (R13.7, R19),
  Appearance (R13.8), Online (R13.10), and the mini player's layouts and places (R15).

R13.9.1. A root opened for the first time, without a `settings.json` of its own, starts with a
copy of the configured root's own settings, so a second root (a USB drive, say) is tagged and named
the way the first one is; with no configured root, it starts with the defaults. The copy is
written into its `.musikata/` when that can be written (R1.5.2).

R13.10. **Online**: **Allow online lookups** (off) (R16.2), and under it each service with its
own switch and what it is used for; **Save MusicBrainz ids in tags** (on) (R16.9); **Clear lookup
cache**, with its size; **Check for updates weekly** (off) (R1.9).

R13.11. **Lyrics**: where saved lyrics go: **Beside the song as .lrc** (the default), **In the
song's tags**, or **Both** (R17.4).
