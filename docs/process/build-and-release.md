# Building and releasing

How the three builds are made, what they are made from, and the steps of a release. The why of
each build is in [A6](../architecture/A6-packaging-and-platforms.md).

## Pinned inputs

Everything a build takes from outside is pinned in `packaging/versions.env`: the Python (a
python-build-standalone build, by version and SHA-256 per platform), PySide6 (Essentials and Addons,
one version), Mutagen, NumPy, PyAV, the platform modules of A4.5, `truststore`, Chromaprint's
`fpcalc` (by version and SHA-256 per platform), pytest and its dependencies, ruff, mypy,
coverage.py, mutmut, Hypothesis and jsonschema ([`coding.md`](coding.md)), PyInstaller and its
dependencies, appimagetool and its runtime, and each container image by digest (the Ubuntu images,
the Wine image PyInstaller runs in, Inno Setup's, and the Debian one that compiles the `icuuc.dll`
stand-in Qt needs under Wine).

- A pin moves only to a release at least 14 days old (the cooldown), so a bad release has time to
  be found and pulled before MusiKata ships it.
- `scripts/pins-newest.py` shows each pin's age and the newest release it may move to, and fails a
  pin younger than 14 days unless the owner allowed it ([`ci.md`](ci.md), "Pins").
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

Each build trims Qt to `packaging/qt-modules.txt` (`scripts/qt_trim.py`, A6.2), adds `LICENSE.txt`
and `THIRD-PARTY-NOTICES.txt` made from the packages it installed (`scripts/third_party_notices.py`,
A6.6), registers the file kinds of R1.7 for "Open with" only, and is started once by its test
script, which makes a demo file and runs `musikata --play FILE`: MusiKata's window over a root
holding the file, the root scanned, and the file played to its end, then it quits, 0 when all went
well. Each writes `build/release/` with a `.sha256` beside the build; CI's jobs `appimage`, `windows`,
`macos-arm64` and `macos-x86_64` build, start and keep each, and `ci` needs them.

| Build | Started by | Where, and on what sound device |
|---|---|---|
| AppImage | `scripts/test-appimage.sh` | an Ubuntu 24.04 container with only what A6.3 takes from the system, on X11 (Xvfb), into PulseAudio's null sink |
| Windows | `scripts/test-windows.sh` | Wine in its container: Setup run silently, the file kinds checked in the registry; Qt finds no sound device under Wine, so `--play` decodes the file to its end instead and ends with 3 |
| macOS | `scripts/test-macos.sh arm64`, `x86_64` | the runner that built it (`macos-15`, Apple silicon; the Intel one under Rosetta), out of the mounted `.dmg`, on the runner's own sound device |

Built by hand, each in its containers (Docker) or on a Mac:

```sh
scripts/build-appimage.sh && scripts/test-appimage.sh
scripts/build-windows.sh && scripts/test-windows.sh
scripts/build-macos.sh arm64 && scripts/test-macos.sh arm64      # on a Mac; x86_64 under Rosetta
```

## Signing

- **Linux**: the AppImage is signed with MusiKata's release key (OpenPGP), whose fingerprint is
  published in the README; a `.sha256` beside it.
- **Windows**: Authenticode, once a certificate is in hand; until then the README says so and
  points to the `.sha256`.
- **macOS**: ad-hoc signatures (A6.5.1), which PyInstaller gives the bundle as it builds it, with a
  `.sha256` beside each `.dmg`; users allow the first start once with **Open Anyway**. A step for a
  Developer ID joins the release's signing once there is one; with it, the bundles are signed,
  notarized by Apple and stapled.

Signing keys never enter the repository or CI's logs; the signing step runs only for an approved
`v*` tag, in the `release` environment, whose approval is the owner's. The release key, and the
copy of its signing subkey that CI holds, are made and kept as [`genesis.md`](genesis.md), 7, says.

## Releasing

A release is walked out by [`release.md`](release.md): the release pull request the agent prepares
([`release-agent.md`](release-agent.md)), then `scripts/publish.sh release` (the tag, CI's builds,
the approved signing and the draft), the field test in each environment, `publish.sh publish`, and
`publish.sh cask` for the Homebrew tap (A6.5.2).
