# Building and releasing

How the three builds are made, what they are made from, and the steps of a release. The why of
each build is in [A6](../architecture/A6-packaging-and-platforms.md).

## Pinned inputs

Everything a build takes from outside is pinned in `packaging/versions.env`: the Python (a
python-build-standalone build, by version and SHA-256 per platform), PySide6 (Essentials and
Addons, one version), Mutagen, NumPy, the platform modules of A4.5, pytest and its dependencies,
appimagetool and its runtime, and each container image by digest.

- A pin moves only to a release at least 14 days old (the cooldown), so a bad release has time to
  be found and pulled before MusiKata ships it.
- A pin moves only by a commit to `versions.env`, and a test fails on any input named by a tag or
  branch that can move.
- Qt 6.12 is an LTS release and the last for Windows 10 (Q7); moving past it is a decision, not an
  update.

## The builds

| Platform | Script | Made where | Result |
|---|---|---|---|
| Linux | `scripts/build-appimage.sh` | Ubuntu 22.04 container | `MusiKata-<version>-x86_64.AppImage` |
| Windows | `scripts/build-windows.sh` | Wine in a container (PyInstaller, Inno Setup) | `MusiKata-<version>-setup.exe` |
| macOS | `scripts/build-macos.sh` | a macOS runner (PyInstaller) | `MusiKata-<version>-arm64.dmg` |

Each build trims Qt to `packaging/qt-modules.txt` (A6.2), adds `LICENSE.txt` and
`THIRD-PARTY-NOTICES.txt` (A6.6), and is started once by its test script, which plays a demo file
and quits.

## Signing

- **Linux**: the AppImage is signed with MusiKata's release key (OpenPGP), whose fingerprint is
  published in the README; a `.sha256` beside it.
- **Windows**: Authenticode, once a certificate is in hand; until then the README says so and
  points to the `.sha256`.
- **macOS**: a Developer ID signature, notarized by Apple and stapled; without them Gatekeeper
  refuses the app.

Signing keys never enter the repository or CI's logs; the signing step runs only for an approved
`v*` tag, in a job that needs the owner's approval.

## A release, step by step

1. `main` is green in CI, and `DEVELOP.md`'s status is current.
2. Tier 3 by hand on each platform ([`testing.md`](testing.md)): install, scan the demo library,
   infer tags, set a cover, make a playlist by drag and drop, organize, undo, play with the media
   keys, both visualizations.
3. The version is set in `musikata_core/__init__.py`, and release notes are written in
   `docs/releases/<version>.md`: what a user sees, not the commits.
4. A signed tag `v<version>` is pushed; CI builds without caches.
5. The owner approves the signing job; CI signs the builds and drafts the GitHub release with them,
   their `.sha256` files and the notes.
6. The draft is checked (each download starts on its platform) and published.
