# Releasing: the agent's part

The owner walks a release through by [`release.md`](release.md), and at three points hands a step
to the agent by name ("Prepare release 0.2.0"). Each of those is a section here. The agent is
Claude Code, working from its fork with read access ([`genesis.md`](genesis.md), 2). It does every
step of the section, in order, and ends by telling the owner what to do next.

`scripts/publish.sh release` refuses to tag until the release pull request of section 1 is merged
with every step of its record ticked, so none of them can be skipped.

## 1. Prepare a release

The owner says: **"Prepare release `<version>`"**. `<last>` is the version released before it.

1. **A branch** from `MojoKata/MusiKata`'s `main`, up to date: `prepare-<version>`. It is only the
   pull request's branch, gone once it merges; `main` stays the only line.
2. **`tier1`:** `scripts/test-tier1.sh` passes, and `scripts/test-clock.sh` too (tier 1 at several
   times of day and time zones, [`testing.md`](testing.md)). CI runs tier 1 again on the pull
   request.
3. **`tier2`:** tier 2 of [`testing.md`](testing.md) passes: the tour and its layout check at 100 %
   and 150 % text, the size and speed targets of R1.11 on the demo library built at 50,000 songs,
   the AppImage built and started, and the suite on Windows in its VM. Look at the tour's screens
   against the mockups. The record gives each part's result.
4. **`pins`:** `scripts/pins-newest.py` exits 0: no pin is younger than 14 days, the pin cooldown
   ([`build-and-release.md`](build-and-release.md#pinned-inputs)), or the owner allowed it
   (`--allow`, with the commit that pinned it saying why). Its table also shows the pins that could
   move. Moving one is a change of its own, proven like any other, so say in the record which
   could, and leave them unless the owner asks.
5. **`version`:** `__version__` in `src/musikata_core/__init__.py` and `DEVELOP.md`'s Status heading
   (`## Status (<version>: …)`) say `<version>`. `publish.sh release` tags `v<version>`, and CI's
   `version` job stops a tag that doesn't match `__version__`.
6. **`state`:** freeze the release's on-disk state for the upgrade tests:
   ```sh
   UPDATE_STATE=<version> .venv/bin/python -m pytest tests/test_upgrade_state.py
   ```
   It writes `tests/data/state/<version>/`: the index (`musikata.db`) and the root's `.musikata`
   folder (R1.5) that this release makes from the demo library. The test brings every snapshot
   there into the current code on every run, so a later MusiKata is shown to migrate the index
   (A2.1) and to read the root's own files (A2.8) that an earlier one left. A snapshot is dropped
   only when its release is no longer one MusiKata updates from.
7. **`notes`:** the record's Notes section: what a user sees in this release, not the commits,
   since `v<last>`. CI's draft release takes them as its text.
8. **The record**, `docs/releases/<version>.md`: the notes, then one ticked line per step above,
   each with its result. `publish.sh release` reads it, and refuses while the notes or a step are
   missing or a step is unticked.
   ```markdown
   # MusiKata <version>

   ## Notes

   What a user sees: what's new, what changed, what was fixed.

   ## Prepared

   On <date>, in pull request #<n>, at <commit>.

   - [x] **tier1** test-tier1.sh: <n> passed, <n> skipped (its list); test-clock.sh: all passed
   - [x] **tier2** tour: no text past its box; R1.11 met (<figures>); AppImage ran; Windows ok
   - [x] **pins** pins-newest.py: none younger than 14 days; could move: <pin> <from> → <to>
   - [x] **version** `__version__` and DEVELOP.md's Status heading say <version>
   - [x] **state** tests/data/state/<version>/
   - [x] **notes** written above
   ```
9. **The pull request**, "Prepare for `<version>`": the version, `DEVELOP.md`, the snapshot and
   the record, with a body that links the record. Run the public-text check
   (`scripts/public_text.py`) first, since the repository is public. Wait for its CI to pass.

Then tell the owner: "Pull request #`<n>` is ready. Merge it, then [`release.md`](release.md), 3:
`scripts/publish.sh release`."

## 2. Look into a stopped release

The owner says: **"Release `<version>` stopped"**, with what `publish.sh` printed.

1. Read the run's failed jobs: `gh run view <run> --repo MojoKata/MusiKata --log-failed`.
2. If the failure isn't the code's (a runner, the network, GitHub answering 5xx), tell the owner
   to run the failed jobs again and resume:
   ```sh
   gh run rerun <run> --failed --repo MojoKata/MusiKata
   scripts/publish.sh resume
   ```
3. If it is the code's, open an issue for it, with the log. Fix it in a pull request, then tell the
   owner it needs a new version (section 1 again). A tag isn't moved or deleted to fix a release:
   the tags ruleset leaves that to an admin, and the owner decides.
4. If `release` refused before tagging, its message says why: CI failed on `main`, a step isn't
   ticked, the notes or the snapshot are missing. Fix that in a pull request.

## 3. Wrap up a release

The owner says: **"Wrap up release `<version>`"**, after `publish.sh publish` and `publish.sh cask`.

1. **Check the published release** from your own clone. Anyone can, once it's published:
   ```sh
   scripts/publish.sh verify <version>
   ```
   It must say `(published)` and the release key's fingerprint.
2. **Check the cask:** the tap's `Casks/musikata.rb` names `<version>` and the two `.dmg`s'
   SHA-256s that `verify` printed:
   ```sh
   gh api repos/MojoKata/homebrew-musikata/contents/Casks/musikata.rb --jq .content | base64 -d
   ```
3. **Add a "Released" section to the record**, `docs/releases/<version>.md`:
   - the date it was published, and the tag's commit;
   - CI's run of the tag;
   - the four SHA-256s, from `verify`'s output;
   - the field test: the release's issue, and how each environment's closed. A waived environment
     or box says why;
   - the cask's commit in the tap;
   - anything that went wrong, and the issue that has it.
4. **A pull request** with the record, "Release `<version>`: the record".

Then tell the owner the release is recorded, with the pull request's link.
