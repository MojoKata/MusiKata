# MusiKata: architecture

The [requirements](../requirements/README.md) say what MusiKata does. These files say why a part of
it is built the way it is, where that takes more than a sentence: the design, the choices weighed
and the evidence behind them.

They are laid out as the requirements are, with A in place of R: each section has a file of its
own, `AN-name.md`, or a folder, `AN-name/README.md`, once it passes 500 lines, with a file per
first-level item named by its id. `A3.4` is item 4 of the tags design. Ids are never renumbered
or reused. Like the requirements, they are written in the present tense and carry no dates or
status; git holds the history.

# 1. Overview

[A1](A1-overview.md): the stack, the two packages and what may import what, threads and processes,
the data flow from a file to the screen and back, and the decisions that shape everything else.

# 2. Library and scanning

[A2](A2-library-and-scanning.md): the database, the scan, watching the root, search, how the index
stays a copy of the files, and finding a root's index.

# 3. Tags

[A3](A3-tags.md): Mutagen, the field mapping per file kind, the path pattern engine, safe writes,
and the change history.

# 4. Playback

[A4](A4-playback.md): decoding with PyAV, gapless joins between songs, ReplayGain, the equalizer and
never clipping, the analyzer's audio, the system's media controls on each platform, and devices.

# 5. Visualizations

[A5](A5-visualizations.md): computing waveforms, the analyzer's spectrum, and drawing both on the
Qt Quick scene graph.

# 6. Packaging and platforms

[A6](A6-packaging-and-platforms.md): the AppImage, the Windows installer and the macOS app, the
pinned inputs, and the licenses carried.

# 7. Online lookups

[A7](A7-online-lookups.md): the HTTP client and its certificates, keeping to each service's pace,
fingerprints, matching a release, covers, lyrics, the cache, and testing without a network.
