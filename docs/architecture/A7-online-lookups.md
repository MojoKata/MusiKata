# A7. Online lookups

How MusiKata talks to the services of R16 and R17.4, politely and only when asked.

A7.1. **The client.** Lookups live in `musikata_core.online`, one module per service over one small
HTTP client built on Python's `urllib.request`, run on the worker pool (A1.3). Not Qt's
`QNetworkAccessManager`: the core imports `QtCore` at most (A1.2), and a plain client is easy to
replace with recorded answers in tests (A7.8). HTTPS only. Certificates are checked against the
operating system's own trust store through `truststore`, the same way on all three platforms;
the OpenSSL inside python-build-standalone finds no certificates of its own on macOS.

A7.2. **Politeness.**

- Every request carries `User-Agent: MusiKata/<version> ( https://github.com/MojoKata/MusiKata )`,
  as MusicBrainz requires: the application and where to reach its maintainers, nothing about the
  user (R16.3).
- One limiter per host keeps to each service's pace: musicbrainz.org one request a second, as its
  rules say; api.acoustid.org three a second, as its rules say; coverartarchive.org and lrclib.net
  one request at a time. A `503` or `429` waits as long as `Retry-After` says, or doubles the wait
  up to a minute, then gives up with R16.7's message.
- Lookups of many albums (R16.4.1) run one album after another, never in parallel, and stop at
  once when cancelled.

A7.3. **Fingerprints** (R16.6) are made by Chromaprint's `fpcalc`, the command-line tool from
Chromaprint's own releases (LGPL-2.1, FFmpeg built in), pinned by version and SHA-256 per platform
and carried by each build (A6.1). It reads the first 120 seconds of a file and prints the
fingerprint and length MusiKata sends to AcoustID. Its lookups use MusiKata's application key,
kept in the source as AcoustID intends application keys to be; it identifies the application,
not the user.

A7.4. **Matching a release** (R16.5). MusicBrainz's search finds up to ten releases by the album
artist and title. Each is fetched with its recordings, and scored against the album's songs: the
same number of tracks, each song's length within 3 seconds of its track's, titles equal once case,
accents and punctuation are set aside, and in the same order. The score is what the dialog shows
("10 of 10 songs · lengths within 2 s"). MusicBrainz's fields map to those of R4.1 as Picard maps
them, and the ids go in the frames Picard writes (`TXXX:MusicBrainz Album Id`, `UFID` for the
recording, and their Vorbis and MP4 equivalents), so the two agree.

A7.5. **Covers** (R16.4). The Cover Art Archive gives each release's front cover at 250, 500 and
1200 pixels, and the original. Candidates are shown from the 500-pixel copy; the chosen one is
fetched at its full size, then saved as R5.3 says, shrunk for embedding if larger than the setting.

A7.6. **Lyrics** (R17.4). LRCLIB's `get` is asked first with artist, title, album and length,
which finds the exact song; when it has nothing, its `search` lists near matches. Timed lyrics
come as LRC text, parsed into times and lines. Saved lyrics are written as a UTF-8 `.lrc` beside
the song, or into its tags (ID3 `SYLT` and `USLT`; Vorbis `LYRICS` holding the LRC text; MP4
`©lyr`), through the safe write of A3.4.

A7.7. **The cache.** Answers are kept in the `lookup` table (A2.1), keyed by the request, for 30
days (R16.8), and fetched images in the cache folder beside the thumbnails. Nothing in the cache
is ever sent anywhere.

A7.8. **Tests.** Tier 1 never touches the network (`testing.md`): each service is tested against
recorded answers, played back through the client of A7.1, including errors, slow answers and
`Retry-After`, and a test checks that nothing is requested at all while lookups are off.
`scripts/check-services.py` makes one real request to each service, by hand and once a week in
CI, so a changed API is noticed before a user notices it.

A7.9. **Terms.** MusicBrainz and AcoustID are free for non-commercial use, which MusiKata is (free
software, given away; Q6). Selling it would need their commercial plans. MusicBrainz's data is
CC0; covers and lyrics stay their owners', and MusiKata only writes them into the user's own files
(R16.10).
