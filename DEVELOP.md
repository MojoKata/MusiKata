# Developing MusiKata

Where the build stands, and what the first release holds. What MusiKata does is in the
[requirements](docs/requirements/README.md), why it is built so in the
[architecture](docs/architecture/README.md), and how the work is done (running from source, the
demo library, the tour, tests, releases) in [`docs/process/`](docs/process/README.md).

## Status

| Area | State |
|---|---|
| Requirements R1 to R18, architecture A1 to A7, process | Written; open questions in [`questions.md`](docs/requirements/questions.md) |
| Mockups of every screen of the first release | Drawn ([`docs/mockups/`](docs/mockups/README.md)) |
| Code, tests, builds | Not started |

## The first release

The first release is everything in the requirements except what is listed under **Later**.
Requirements change by commits to `docs/requirements/`; this list changes with them.

| | Requirements |
|---|---|
| **In** | R1 to R15 and R18, whole, with gapless playback as Q5 decides |
| **In** | R16 Online lookups: covers (R16.4, R16.4.1) and tags (R16.5), off until turned on |
| **In** | R17 Lyrics: from `.lrc` files and tags (R17.1 to R17.3), found online (R17.4), edited as text (R17.5) |
| **In** | R1.9 updates when asked; Q9's duplicates, if answered as proposed |
| **Later** | R16.6 Identify by sound: it needs Chromaprint's `fpcalc` built and signed for three platforms (A7.3) |
| **Later** | R17.5's **Set time**, timing plain lyrics by tapping along |
| **Later** | The light theme's mockups and its own check of R18.4 (dark is the design target, R6.2) |
| **Later** | Translations other than English (R1.10 makes them a file added) |
| **Later** | Q10 computing loudness, Q11 CUE sheets as songs |
| **Out** | What Q12 lists, if answered as proposed |

## Waiting on decisions

The first release can't be finished before these are answered: Q1 (macOS versions), Q3 (one
music root), Q4 (ratings in Vorbis and MP4), Q5 (gapless playback), Q6 (the license), Q7 (Windows
versions), Q8 (mis-encoded tags), Q9 to Q12. Each has a proposal in
[`questions.md`](docs/requirements/questions.md).
