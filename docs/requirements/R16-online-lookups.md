# R16. Online lookups

MusiKata works without a network (Principle 4). When the user asks, it looks up what the files
can't say for themselves (a cover, an album's track list, what an unnamed file is, a song's
lyrics) in free, open services. It looks nothing up in the background, and what it finds goes
into files only through a preview, as everything else does (Principle 2). Mockups:
`T04-find-cover-online`, `T05-look-up-tags`.

R16.1. **The services.** These, and no others; none needs an account.

| Service | Used for | What MusiKata sends it |
|---|---|---|
| **MusicBrainz** (musicbrainz.org) | Albums, artists, track lists, dates, ids (R16.5) | Album artist and album title; then the id of the release chosen |
| **Cover Art Archive** (coverartarchive.org) | Covers (R16.4) | The MusicBrainz id of a release |
| **AcoustID** (acoustid.org) | Naming a file by its sound (R16.6) | The file's audio fingerprint (A7.3) and its length |
| **LRCLIB** (lrclib.net) | Lyrics (R17.4) | Artist, title, album and length of one song |

R16.2. **Off until the user turns it on.** **Allow online lookups** in Settings (R13.10) is off
when MusiKata is installed. The **Find online…** and **Look up…** buttons are always there; the
first one pressed while lookups are off asks once, naming the service and what will be sent,
with **Allow online lookups** and **Not now**. Each service can be turned off on its own.

R16.3. **What is sent, and what never is.** Only what the lookup needs, as the table in R16.1
says. File paths, the rest of the library, play counts and ratings, and anything about the user
or the computer are never sent; requests name MusiKata and its version, not the user (A7.2).
Every dialog that looks something up says in its footer what it sends and to whom ("Sends the
album artist and title to musicbrainz.org").

R16.4. **Covers** (`T04-find-cover-online`). **Find online…** in the Album art dialog (R5.2) finds
the MusicBrainz releases that match the album's artist, title and number of songs, and adds their
front covers from the Cover Art Archive to the dialog's candidates, each with the release it
belongs to (year, country, format) and its size, best match first. Choosing one and saving does
what R5.3 says.

R16.4.1. **Many albums at once.** Needs attention's **Find covers online** (R2.8) looks up every
album listed with no cover or a small one, and shows one row per album: the album, its current
cover or none, the best cover found with its size, and a checkbox, on for albums with a clear
match and off where the match is doubtful. **Save** does R5.3 for the checked rows, in one
undoable change (R4.9).

R16.5. **Tags** (`T05-look-up-tags`). **Look up tags…** on an album's page, in the Edit tags panel
when it edits one album, and on Needs attention's album entries, finds the MusicBrainz releases
that fit the album and lists them with how well each fits: how many songs it has, how many of the
album's songs it matches by title and length ("10 of 10 songs · lengths within 2 s"), its year,
country, label and format. The best is chosen; choosing another changes the preview.

R16.5.1. **The preview** is Infer from path's (R3.7): one row per song, each changed value with
the old one struck through above the new, unchanged songs unchecked, songs the release doesn't
match listed apart and left alone. **Only fill empty tags** or **Correct tags that differ** (the
default) as in R3.5; **Keep my genres** (on), since MusicBrainz's genres are coarser than most
people's; **Save MusicBrainz ids** (on, R16.9). **Save N files** writes them as R3.8 does.

R16.6. **Identify by sound.** For files whose tags and path say nothing of what they are (Needs
attention, R2.8, and on any selection of songs), **Identify by sound** fingerprints each file on
the computer (A7.3), asks AcoustID which recording it is, and shows the tags of the best match in
the preview of R16.5.1, with how sure the match is. Files with no match are listed as "Not
recognised" and left alone; it doesn't guess.

R16.7. **When a lookup fails.** With no network, a service that doesn't answer, or nothing found,
the dialog says which ("Couldn't reach musicbrainz.org. Check the connection and try again.",
"No release matches Tide Tables by Lumen Drift"), and nothing changes. Lookups are kept to each
service's pace (A7.2), so a long one shows its progress and can be cancelled; what was saved
before cancelling stays.

R16.8. **Asking again.** Answers are kept in the cache (R1.5) for 30 days, so reopening a dialog
doesn't ask again; **Clear lookup cache** (R13.10) empties it.

R16.9. **MusicBrainz ids.** With **Save MusicBrainz ids in tags** (on), saving a lookup also writes
the release's and each recording's MusicBrainz ids, in the frames MusicBrainz Picard uses, so
Picard and later lookups go straight to the same release.

R16.10. **Use of what is found.** Covers and lyrics stay their owners' work; MusiKata only writes
them into the user's own files and never shares them. MusicBrainz's data is in the public domain
(CC0).
