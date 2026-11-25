# Open questions

Questions waiting on a decision. Each has an id that is never reused, the sections it holds up,
and a proposal. An answered question's answer goes into its section and the question is removed.

**Q1. macOS: which versions and machines?** (R1.1, R1.6) Proposal: macOS 14 Sonoma and newer, on
Apple silicon only, as a signed and notarized `.dmg`. Intel Macs would double the builds and the
testing for a shrinking share of machines.

**Q2. Online lookups.** (R2, R5) Should MusiKata ever ask an online service (MusicBrainz, the
Cover Art Archive) for tags or covers? Proposal: not in the first release, which keeps
Principle 4 (offline and private) without exceptions; a later, opt-in lookup is a separate
section if wanted.

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
