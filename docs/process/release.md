# Releasing

How the owner walks a version of MusiKata out: seven steps, two of them handed to the agent by
name. The agent's side of those is in [`release-agent.md`](release-agent.md). The one-time setup
they rely on (the repository's settings, the release key) is in [`genesis.md`](genesis.md); how the
files are built and signed, in [`build-and-release.md`](build-and-release.md).

**Publishing a release offers it to every MusiKata that checks for updates** (R1.9), and with
immutable releases on, a published release's files and tag can never change. A bad release is
fixed by a new version, never in place.

## The flow

```
 1. You → agent   "Prepare release 0.2.0"       the release pull request: tests, pins, version,
                                                 state, notes, record      (release-agent.md, 1)
 2. You           merge it; wait for CI on main
 3. You           scripts/publish.sh release     tag → CI builds → you approve the signing →
                                                 the draft, checked → the field-test issues
 4. You           the field test, each environment: its sub-issue's checklist; close it
 5. You           scripts/publish.sh publish     the release is published
 6. You → agent   "Wrap up release 0.2.0"       the cask's pull request on the tap, and the
                                                 release's record          (release-agent.md, 3)
 7. You           merge both                     the Homebrew tap points at the release
```

Each command checks that the step before it is done, and refuses otherwise, saying what's missing:

| Command | Refuses until |
|---|---|
| `publish.sh release` | you're on `main`, up to date, with nothing changed; `v<version>` isn't tagged yet; the release pull request is merged: `docs/releases/<version>.md` has its notes and every step ticked, the state snapshot is there, and `DEVELOP.md`'s Status heading names the version; CI has passed on `main` at that commit |
| `publish.sh publish` | the draft is there, and verifies; the release's field-test issues are there, and every one is closed |
| `publish.sh cask` | the release is published, and the tap's clone has no changes of its own |

If anything stops, see [8](#8-when-a-step-stops).

## 1. Ask the agent to prepare the release

Tell the agent: **"Prepare release 0.2.0"**, with the version to release.

It runs tiers 1 and 2, checks that no pin is younger than the 14-day cooldown, sets the version,
freezes the release's on-disk state for the upgrade tests, writes the release's record
(`docs/releases/0.2.0.md`: the notes, what a user sees, and a ticked line per step) and opens one
pull request with all of it ([`release-agent.md`](release-agent.md), 1). It tells you when the pull
request's CI has passed.

## 2. Merge the release pull request

Read the record in the pull request, then squash-merge it as usual. Merging starts CI on `main`;
`release` refuses until that run has passed. To see it:

```sh
gh run list --repo MojoKata/MusiKata --branch main --limit 1      # "completed  success"
```

## 3. Tag, build and sign: `publish.sh release`

You need, once: `git`, `gpg` 2.2 or newer, `python3`, and `gh` logged in as an admin of MojoKata
([`genesis.md`](genesis.md#what-the-owner-needs)), and a clone of the repository. You don't need
the release key: CI signs with its own copy of the signing subkey.

```sh
git checkout main && git pull
scripts/publish.sh release
```

It asks three times: answer `y` to each.

1. **"Tag … as v0.2.0 and push it?"**, once it has checked what steps 1 and 2 leave. GitHub then
   prints "Bypassed rule violations" for the tag: expected, since the tags ruleset lets only admins
   create tags, and you are one.
2. **"Sign the builds and make the draft release?"**, once CI's run of the tag has built the four
   files and waits for your approval. Above the question are the SHA-256s of the four builds, from
   the build jobs' own notices; the draft must hold exactly those.
3. **"Open the field-test issues?"**, once the draft is made and checked: one for the release, and
   one under it for each environment of step 4.

Between the second and the third it downloads the draft into `build/publish/v0.2.0/` and checks it
(`publish.sh verify`): exactly nine files, each build against its `.sha256`, and the AppImage's
signature by the release key. What to check:

- The fingerprint in the `(draft)` line is the release key's, the one the README publishes.
- The four SHA-256s it prints last are the four shown before you approved the signing; it checks
  that too, and says so.

## 4. The field test

Tier 3 of [`testing.md`](testing.md) needs a person at a real machine: the sound through its
speakers, its media keys, its file manager and its screen reader. Each environment has a
sub-issue from step 3, titled "Field test: 0.2.0 on <environment>", holding its checklist
(`scripts/field_test.py`, the one list of what the field test asks). Each can have its own tester
and machine.

The draft's files are visible only to the owner, who downloads them for each tester:

```sh
V=0.2.0                                     # the version being released
gh release download v$V --repo MojoKata/MusiKata --pattern '*.AppImage'   # or *.exe, *.dmg
```

The checks use the demo library, made from a clone of the repository at the tag
([`development.md`](development.md), "The demo library"); never real music in what is posted.

Every environment's sub-issue is made each release, so the whole list is in front of the owner;
Windows 11 has none, and is tested only by what tier 2 automates in its VM. Go through the
sub-issue's checklist and tick each box that works. A box that doesn't is a bug: open an issue
labelled `bug`, link it from the box it leaves unticked, and tell the agent. A box that can't be
tried there (no USB drive to hand; the update, on a first release) is left unticked with a comment
saying why. Close the sub-issue when its checklist is done. Any environment, or any box, can be
deferred: close its issue as not planned, with a comment saying why. The release's issue closes once
every environment's has.

## 5. Publish: `publish.sh publish`

**This offers the release to every MusiKata that checks for updates**, and its files and tag can
never change after.

```sh
scripts/publish.sh publish
```

It checks that every field-test issue is closed, verifies the draft again, asks "Publish v0.2.0?",
publishes it as the latest release and verifies it once more. What to check:

- The second check says `(published)`.
- The SHA-256s are the ones `release` showed in step 3.
- Between the `(published)` line and the SHA-256s, `gh release verify` prints GitHub's release
  attestation.

## 6. Ask the agent to wrap up

Tell the agent: **"Wrap up release 0.2.0"**. It checks the published release from its own clone,
updates the Homebrew cask in a pull request on the tap, and adds what was released to the record
(the run, the SHA-256s, the field test and anything deferred, the tap's pull request) in a pull
request here ([`release-agent.md`](release-agent.md), 3).

## 7. Merge the cask and the record

The tap's cask names both `.dmg`s with their SHA-256 (A6.5.2), so it can point only at a published
release; `publish.sh cask` sets its `version` and its `arm:` and `intel:` SHA-256s from the
published release's `.dmg.sha256` files and changes nothing else. Check the pull request's SHA-256s
against those `release` showed in step 3, and merge it. Then, on a Mac, `brew update && brew upgrade
--cask musikata`, or `brew install --cask mojokata/musikata/musikata`, installs the new version: the
Intel Mac's environment in [`testing.md`](testing.md) is installed from the tap. Merge the record's
pull request too.

## 8. When a step stops

- **`release`, `publish` or `cask` refused:** its message says what's missing and where. Do that,
  then run it again. A refusal changes nothing.
- **`release` stopped after the tag** (`publish.sh: the run ended without signing`, or you pressed
  Ctrl-C): tell the agent **"Release 0.2.0 stopped"**, with the output
  ([`release-agent.md`](release-agent.md), 2). If it was the runner's fault, the agent tells you to
  run the failed jobs again and resume. `resume` does what `release` does from "waiting for CI's
  run" on:
  ```sh
  gh run rerun <run> --failed --repo MojoKata/MusiKata     # the run's number, from its "run …" line
  scripts/publish.sh resume
  ```
- **The run's `release` job failed** (its last job, after the signing): it can leave a draft that
  holds only some of the files, since `gh release create --draft` keeps a draft whose upload failed,
  and a later run of the job doesn't replace it. See whether it did, and delete that draft by hand
  before the job is run again; the tag stays:
  ```sh
  gh release view v0.2.0 --repo MojoKata/MusiKata     # "release not found": no draft to delete
  gh release delete v0.2.0 --repo MojoKata/MusiKata   # the draft alone; the tag stays
  ```
- **You answered `n`** to a question: nothing after it happened. Run the same command again.

## 9. What `publish.sh` does

`scripts/publish.sh`, with `gh` logged in as an admin. `VERSION` is `__version__` in
`src/musikata_core/__init__.py` unless given; the script's header lists its options. The one-time
commands, `setup`, `check` and the `key-` ones, are in [`genesis.md`](genesis.md).

| Command | What it does |
|---|---|
| `release` | Checks what steps 1 and 2 leave (the table under "The flow"), tags `main`'s tip `v<version>` and pushes it, waits for CI's run of the tag, shows the SHA-256s of the four builds, approves the signing, waits for the draft release and verifies it, checks that the draft holds the builds whose SHA-256s you approved, and opens the field-test issues. It asks before the tag, the signing and the issues. |
| `resume [VERSION]` | The same from "waits for CI's run", for a tag already pushed: after an interruption, or after a failed run is run again. |
| `verify [VERSION]` | Downloads the release, or its draft, into `build/publish/v<version>/` and checks it: exactly nine files (the four builds, a `.sha256` for each, the AppImage's `.asc`), each build against its `.sha256`, and the AppImage's signature by the release key (`packaging/musikata-release-key.asc`, matched by fingerprint). |
| `field-test [VERSION]` | Opens the release's field-test issue and, under it, one for each environment with its checklist (`scripts/field_test.py`). `release` does this itself; on its own it's for when you answered `n` there. |
| `publish [VERSION]` | Checks that every field-test issue is closed, verifies the draft again, asks, publishes it as the latest release, and verifies the published one. |
| `cask TAP [VERSION]` | In `TAP`, a clone of the tap, sets `Casks/musikata.rb`'s version and its two SHA-256s from the published release, and commits it on the branch `musikata-<version>` after asking, for the agent's pull request on the tap. |

`.github/workflows/ci.yml` runs tier 1 and the four builds on every pull request and every push to
`main`. On a `v*` tag it also signs the builds (after your approval, in the `release` environment)
and makes a draft release with the nine files and the record's notes. Its build jobs are named
`appimage`, `windows`, `macos-arm64` and `macos-x86_64`, and each posts the SHA-256 of what it built
as a notice titled `sha256`, which `release` shows before the signing. What it downloads is pinned
in `packaging/versions.env`, and its actions by commit SHA ([`genesis.md`](genesis.md), 5).

## 10. The release key between releases

The key itself stays offline, in `DIR` on a USB stick ([`genesis.md`](genesis.md), 7). Plug it in
for these.

**Before the subkey expires** (every 2 years): `publish.sh key-extend DIR` moves both dates on and
exports the key again; commit the new `packaging/musikata-release-key.asc` in a pull request, then
run `publish.sh key-github DIR`. The copy in GitHub carries the old date and stops signing when it
passes.

**If the copy in GitHub leaks:** `GNUPGHOME=DIR/gnupg gpg --edit-key $(cat DIR/fingerprint)`, then
`key 1`, `revkey`, `save`. Then `gpg --quick-add-key $(cat DIR/fingerprint) ed25519 sign 2y`,
`publish.sh key-export DIR` and `publish.sh key-github DIR`. The fingerprint users check stays the
same.
