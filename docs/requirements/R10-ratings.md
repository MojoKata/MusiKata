# R10. Ratings

R10.1. A song's rating is 0 to 5 stars; 0 means not rated and shows five empty stars. Albums and
artists have no rating of their own; their pages show the average of their rated songs.

R10.2. **Setting a rating.** Clicking a star in any song list, the Edit tags panel or the
now-playing bar sets it; clicking the current star again clears it. Ctrl+1 to Ctrl+5 (⌘ on macOS)
rate the selection and Ctrl+0 clears it. Rating several songs at once is one undoable change
(R4.9).

R10.3. **Kept in the files.** Ratings are written into the songs (Principle 1), so another
player, or MusiKata after a fresh scan, sees them. A setting (R13) keeps them in the database
only, for libraries that must not be written to.

R10.4. **How they are written:**

| Kind | Where | 1 to 5 stars |
|---|---|---|
| MP3 | `POPM`, user `Windows Media Player 9 Series` | 1, 64, 128, 196, 255 |
| FLAC, Ogg, Opus | `RATING` and `FMPS_RATING` (Q4) | 20 … 100, and 0.2 … 1.0 |
| M4A | `----:com.apple.iTunes:RATING` | 20 … 100 |
| WAV, AIFF | the database only | |

R10.4.1. Reading, MusiKata accepts a `POPM` from any user, preferring the one above, and maps its
0–255 value to stars by the ranges the common players use (1–31: 1, 32–95: 2, 96–159: 3,
160–223: 4, 224–255: 5). A setting (R13) chooses MusiKata's own scale for `POPM` instead, written
under the user `MusiKata`.

R10.5. **Using ratings.** Every song list can sort by rating; search takes `rating:>=4` (R2.7);
smart playlists take a minimum rating (R8.9).
