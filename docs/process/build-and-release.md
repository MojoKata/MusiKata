# Building and releasing

How the three builds are made, what they are made from, and the steps of a release. The why of
each build is in [A6](../architecture/A6-packaging-and-platforms.md).

## Pinned inputs

Everything a build takes from outside is pinned in `packaging/versions.env`: the Python (a
python-build-standalone build, by version and SHA-256 per platform), PySide6 (Essentials and Addons,
one version), Mutagen, NumPy, PyAV, the platform modules of A4.5, `truststore`, Chromaprint's
`fpcalc` (by version and SHA-256 per platform), pytest and its dependencies, appimagetool and its
runtime, and each container image by digest.

- A pin moves only to a release at least 14 days old (the cooldown), so a bad release has time to
  be found and pulled before MusiKata ships it.
- A pin moves only by a commit to `versions.env`, and a test fails on any input named by a tag or
  branch that can move.
- Qt 6.12 is an LTS release and the last for Windows 10 (R1.1); moving past it is a decision, not an
  update.

## The builds

| Platform | Script | Made where | Result |
|---|---|---|---|
| Linux | `scripts/build-appimage.sh` | Ubuntu 22.04 container | `MusiKata-<version>-x86_64.AppImage` |
| Windows | `scripts/build-windows.sh` | Wine in a container (PyInstaller, Inno Setup) | `MusiKata-<version>-setup.exe` |
| macOS, Apple silicon | `scripts/build-macos.sh arm64` | an Apple silicon macOS runner (PyInstaller) | `MusiKata-<version>-arm64.dmg` |
| macOS, Intel | `scripts/build-macos.sh x86_64` | the same runner, under Rosetta (A6.5) | `MusiKata-<version>-x86_64.dmg` |

Each build trims Qt to `packaging/qt-modules.txt` (A6.2), adds `LICENSE.txt` and
`THIRD-PARTY-NOTICES.txt` (A6.6), and is started once by its test script, which plays a demo file
and quits.

## Signing

- **Linux**: the AppImage is signed with MusiKata's release key (OpenPGP), whose fingerprint is
  published in the README; a `.sha256` beside it.
- **Windows**: Authenticode, once a certificate is in hand; until then the README says so and
  points to the `.sha256`.
- **macOS**: ad-hoc signatures (A6.5.1), with a `.sha256` beside each `.dmg`; users allow the
  first start once with **Open Anyway**. The job has a step for a Developer ID that is skipped
  until there is one; with it, the bundles are signed, notarized by Apple and stapled.

Signing keys never enter the repository or CI's logs; the signing step runs only for an approved
`v*` tag, in a job that needs the owner's approval.

## A release, step by step

1. `main` is green in CI, and `DEVELOP.md`'s status is current.
2. Tier 3 by hand on each platform ([`testing.md`](testing.md)): install, scan the demo library,
   infer tags, set a cover, make a playlist by drag and drop, organize, undo, play with the media
   keys, both visualizations, an album played gapless, the equalizer. The Intel Mac app is tried
   on the owner's Intel Mac, the Apple silicon one on an Apple silicon Mac.
3. The version is set in `musikata_core/__init__.py`, and release notes are written in
   `docs/releases/<version>.md`: what a user sees, not the commits.
4. A signed tag `v<version>` is pushed; CI builds without caches.
5. The owner approves the signing job; CI signs the builds and drafts the GitHub release with them,
   their `.sha256` files and the notes.
6. The draft is checked (each download starts on its platform) and published.
7. The cask in MusiKata's Homebrew tap (A6.5.2) is pointed at the two new `.dmg`s and their
   SHA-256, by a commit to the tap.
