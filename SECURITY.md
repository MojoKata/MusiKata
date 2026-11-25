# Security

## Reporting a problem

Report a security problem privately, through GitHub's form: the repository's **Security** tab,
**Report a vulnerability**. Please don't open a public issue for one. The report is seen only by the
maintainers until a fix is out.

## What is supported

Only the latest release. MusiKata updates itself only when asked (R1.9), so a fix ships as a new
release, and an older one is never patched.

## What matters most

The code a problem there would matter most in, read whole whenever it changes
([`docs/REVIEW.md`](docs/REVIEW.md), "Sensitive code"):

- **The updater** (R1.9): what it downloads, and its checks of the SHA-256 and the signature before
  anything is run.
- **The parsers of files from anywhere**: tags (A3), M3U playlists (R8), `.cue` sheets, LRC lyrics
  (R17) and Equalizer APO presets (R19.7). A file crafted to crash MusiKata, make it write where it
  shouldn't, or run anything, is a security problem.
- **The online client** (A7.1): the certificates it trusts, and what it sends; MusiKata sends only
  what a lookup needs, and only when asked (R16.3).
- **Writing and moving music files**: the safe write (A3.4), organizing (R12) and removing songs
  (R2.11). Damaging or losing a user's music is treated as a security problem too.

## What isn't in scope

- What someone with the user's own account can already do: change the user's files, settings or
  the app itself.
- The first start on macOS asking for **Open Anyway**: the Mac apps are ad-hoc signed, by design,
  until there is a Developer ID (A6.5.1).

## What to expect

An acknowledgement of the report, then a fix in a release, with credit in its notes if wanted.
MusiKata is free software with one maintainer, so there are no fixed times.
