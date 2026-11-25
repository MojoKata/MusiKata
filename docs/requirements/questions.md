# Open questions

Questions waiting on a decision. Each has an id that is never reused, the sections it holds up,
and a proposal. An answered question's answer goes into its section and the question is removed.

**Q1. macOS: which versions and machines?** (R1.1, R1.6) Proposal: macOS 14 Sonoma and newer, on
Apple silicon only, as a signed and notarized `.dmg`. Intel Macs would double the builds and the
testing for a shrinking share of machines.

**Q3. More than one music root?** (R2.1) Proposal: one root. A second drive or a NAS share is
added later, if wanted, as more roots under the same rules, each with its own `Playlists` folder.

**Q4. How are ratings written to FLAC, Ogg and Opus files?** (R10.4) There is no single standard.
Proposal: `RATING` as 1 to 5 stars stored as 20, 40, 60, 80, 100 (what foobar2000-style and
MusicBee-style readers most often accept), plus `FMPS_RATING` (0.0 to 1.0) for the Linux players
that read that one.

**Q5. Gapless playback.** (R7.6) Qt's media player leaves a short gap between files. Proposal:
accept the gap in the first release and file gapless playback (two players, the next one
preloaded) as a gap to close later, since live albums and DJ mixes need it.

**Q6. License.** Proposal: GPL-3.0-or-later, as for the rest of the Kata suite. Mutagen, the tag
library (A3), is GPL-2.0-or-later, which fits.

**Q7. Windows versions.** (R1.1) Proposal: Windows 10 22H2 and Windows 11, x64. Qt 6.12 LTS is
Qt's last version for Windows 10; moving past it drops Windows 10.

**Q8. Mis-encoded old tags.** (R4, A3.6) ID3v2.3 tags written as Latin-1 that are really another
encoding (Cyrillic or Japanese rips, often) show as gibberish. Proposal: a **Fix encoding…** tool
in the Edit tags panel that previews the text under the likely encodings and rewrites the chosen
one as UTF-8.

**Q9. Duplicates.** (R2.8, R2.11) Should MusiKata find the same song twice? It already knows exact
copies by their audio hash (A2.3). Proposal: yes, in the first release, as a Needs attention group
"Same song more than once": exact copies, and likely ones (same artist and title, lengths within 2
seconds). Each group shows its copies with format, bit rate, folder, plays and rating, proposes
keeping the best (lossless over lossy, then the higher bit rate, then the one whose path matches
its tags), moves the others to the trash after asking (R2.11), and points playlists naming a
removed copy at the one kept.

**Q10. Computing ReplayGain.** (R4.1, R7.5) MusiKata reads ReplayGain but can't compute it, so
songs without it play at their own loudness. Proposal: after the first release, **Calculate
loudness** on an album or a selection: EBU R128 (ReplayGain 2.0, −18 LUFS), track and album gain
and peak written into the tags through the usual preview and Undo, decoded with Qt and measured
with NumPy, so nothing new is shipped.

**Q11. CUE sheets.** (R2.2, R12.3) An album kept as one big file with a `.cue` beside it plays as
one long song. Proposal: not in the first release, where such an album is listed in Needs
attention as "Album in one file" and plays whole; later, its tracks become songs of their own,
each a span of the file, with their titles from the `.cue`.

**Q12. What is left out.** None of these is in the requirements. Proposal: leave all of them out
of the first release and say so in the requirements' README, so their absence is a choice:

- an equalizer;
- crossfading between songs (gapless playback is Q5);
- scrobbling plays to Last.fm or ListenBrainz (if wanted later, ListenBrainz first, as one more
  service of R16);
- syncing to phones and USB players, beyond exporting a playlist with its files (R8.8);
- importing ratings, play counts and playlists from iTunes or Apple Music, foobar2000 or other
  players;
- internet radio and podcasts;
- converting between formats.
