# MusiKata

A music player and organizer for Linux, Windows and macOS. It plays the music in one folder, the
**music root**, and keeps that folder tidy: it works out each song's artist, album, track and title
from its path, fills or corrects the files' tags from it, puts one cover on every song of an
album, and keeps playlists as plain M3U files beside the music. Everything it knows lives in the
files, so the library works with any other player and survives MusiKata. It edits the tags of many
songs at once, plays gaplessly with a parametric equalizer, and shows the music as it plays, as a
waveform or a 3D spectrum analyzer.

![MusiKata's Songs list, on its made-up demo library](https://mojokata.github.io/MusiKata/screenshots/latest/L03-songs.png)

The newest screens, taken by the tour of each push to `master`, are on the
[screenshots](https://mojokata.github.io/MusiKata/screenshots/) page.

MusiKata is being built, and has no release yet. Where the build stands is in
[`DEVELOP.md`](DEVELOP.md).

- **What it does:** the [requirements](docs/requirements/README.md), and the
  [mockups](docs/mockups/README.md) of every screen.
- **How it's built:** the [architecture](docs/architecture/README.md) and the
  [process](docs/process/README.md).
- **How well it's tested:** the [coverage](https://mojokata.github.io/MusiKata/) of every area, and
  the [hardening](https://mojokata.github.io/MusiKata/hardening.html) page of its reviews' findings.
- **Security:** [`SECURITY.md`](SECURITY.md) says how to report a problem privately.

MusiKata is free software under the GPL, version 3 or later ([`LICENSE`](LICENSE)).
