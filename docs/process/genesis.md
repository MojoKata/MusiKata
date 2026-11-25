# Genesis

How this repository, its CI's settings and its release key are set up: every one-time step, in
order, with how to check it is still in place. When something breaks, walk it again from the top.

Two scripts hold the settings as code, and read them back:

- `scripts/repo-admin.sh apply` makes steps 3 to 6 (merging, the `master` ruleset, Actions,
  security), as each MojoKata repository's own `repo-admin.sh` does, and then runs
  `scripts/publish.sh setup` for step 8. `repo-admin.sh check` reads both back. A second `apply`
  changes nothing.
- `scripts/publish.sh check` reads back every setting below and prints `ok` or `FAIL` for each.
  `publish.sh setup` makes step 8's settings where they're missing, asking first.

Both need `gh` logged in as the owner. GitHub shows some settings only to an admin: run by anyone
else, those lines say `(can't read)`, which is not a wrong value. Each release's steps are in
[`release.md`](release.md); how the files are built, in
[`build-and-release.md`](build-and-release.md).

## What the owner needs

`git`, `gpg` 2.2 or newer, `python3` and `gh`, on your own machine (not a shared one), and a USB
stick for the key. `gh` must be logged in as an admin of MojoKata, with the `repo` scope:

```sh
gpg --version | head -1        # gpg (GnuPG) 2.2 or newer
gh auth status                 # your account, its token's scopes including 'repo'
```

Work in a clone of the repository, on `master`; every command below runs from its top folder:

```sh
git clone git@github.com:MojoKata/MusiKata.git
cd MusiKata
```

## 1. The organization and the repositories

- The **MojoKata** organization, on GitHub's Free plan. Its repository **MojoKata/MusiKata** is
  public, licensed GPL-3.0-or-later ([`LICENSE`](../../LICENSE)), with `master` as its default
  branch.
- `MUSIKATA_REPO` in `src/musikata_core/__init__.py` names it. MusiKata's update check asks this
  repository's releases (R1.9), so **publishing a release offers it to every MusiKata that checks**.
- **MojoKata/homebrew-musikata** is the Homebrew tap (A6.5.2): public, holding one cask,
  `Casks/musikata.rb`, which each release points at its two `.dmg`s through a pull request
  ([`release.md`](release.md), 7).

Check: `gh api repos/MojoKata/MusiKata --jq '"\(.visibility) \(.default_branch)"'` prints
`public master`, and `gh api repos/MojoKata/homebrew-musikata --jq .visibility` prints `public`.

## 2. Who does what

- **The owner** is the repository's admin: merges pull requests, changes settings, holds the
  release key and publishes releases.
- **Contributors** work from forks and open pull requests. Claude Code works this way, from a fork,
  with read access to the repository.

Check: the organization's People page, and the repository's Settings → Collaborators and teams.

## 3. Merging

Settings → General → Pull Requests: **squash merging only** (merge commits and rebase merging off),
and a pull request's branch deleted once it's merged.

Check: `publish.sh check`, "merge methods".

## 4. The `master` ruleset

Settings → Rules → Rulesets → `master`, active, on the default branch:

- Restrict deletions; block force pushes.
- Require a pull request before merging: 0 approvals; squash the only merge method.
- Require status checks to pass: **`ci`**, from GitHub Actions. GitHub offers a check only once it
  has run, so it is added after the first green run of the pull request that adds CI;
  `publish.sh setup` adds it then.
- Bypass list: repository admins.

Check: `publish.sh check`, the "master ruleset" lines.

## 5. Actions

Settings → Actions → General:

- **Approval for running fork pull request workflows:** require approval for all external
  contributors. A pull request from anyone who isn't a member of the organization or the repository
  runs only after an admin clicks "Approve and run".
- **Workflow permissions:** read repository contents and packages. A job that needs more asks for
  it by name; only the release job does (`contents: write`). "Allow GitHub Actions to create and
  approve pull requests" is off.
- **Require actions to be pinned to a full-length commit SHA:** GitHub refuses to run a workflow
  that names an action by a tag or a branch. A tier 1 test checks the same from inside a run
  ([`build-and-release.md`](build-and-release.md), "Pinned inputs"); the setting holds whatever a
  pull request changes.

Check: `publish.sh check`, "workflow token", "fork PR runs wait for approval" and "actions pinned by
SHA".

## 6. Security

Settings → Security: **private vulnerability reporting** on, so a security problem can be reported
without making it public.

Check: `publish.sh check`, "private vulnerability reporting".

## 7. The release key

The AppImage's `.asc` is signed by the release key's signing subkey
([`build-and-release.md`](build-and-release.md), "Signing"). The main key, whose fingerprint users
check, stays offline with the owner; GitHub holds only a copy of the subkey. On the owner's own
machine (not a shared one):

1. `scripts/publish.sh key-new DIR 'NAME <ADDRESS>'` makes, in `DIR`, an ed25519 main key that only
   certifies (expires in 5 years) and an ed25519 signing subkey (2 years), and keeps `DIR/gnupg`
   (the keyring), `DIR/musikata-release-key.asc` (the public key), `DIR/fingerprint` and
   `DIR/revocation.asc`. `ADDRESS` must receive mail: keys.openpgp.org publishes the key's name
   only once its address is verified. Plug in the USB stick and make the key straight onto it.
   gpg opens a window for the passphrase, and may ask for it again for the subkey: make a strong
   one and keep it in a password manager.
   ```sh
   DIR=/media/$USER/KEYS/musikata-key          # your stick's path
   scripts/publish.sh key-new "$DIR" 'MusiKata <ADDRESS>'
   ```
   It ends by listing the key: a `pub` line marked `[C]` that expires 5 years out and a `sub` line
   marked `[S]` that expires 2 years out, both `ed25519`. The 40-character line under `pub` is the
   **fingerprint**; it's also in `$DIR/fingerprint`.
2. Keep `DIR` offline, on a USB stick with a second copy elsewhere, and the passphrase in a password
   manager. Keep `revocation.asc` apart from both, as a printout or in the password manager: it
   revokes the key without the passphrase. `ls -l "$DIR"` shows the four entries of step 1, with
   `gnupg` and `revocation.asc` readable by you alone.
3. `scripts/publish.sh key-export DIR` writes `packaging/musikata-release-key.asc` and offers to
   send the key to keys.openpgp.org (answer `y`). Commit the file in a pull request, with the
   fingerprint in `README.md`. CI doesn't need it, but `publish.sh verify` checks every release
   against it.
   ```sh
   scripts/publish.sh key-export "$DIR"
   gpg --show-keys packaging/musikata-release-key.asc          # the same key as key-new showed
   ```
   Then verify the address: open <https://keys.openpgp.org/upload> in a browser, upload
   `packaging/musikata-release-key.asc`, click **Send Verification Email** next to the address, and
   click the link in the mail that arrives.

   Once the key's pull request is merged, bring the clone up to date. Remove the exported copy
   first, or `git pull` refuses to overwrite it; `git status --short` then prints nothing:
   ```sh
   rm packaging/musikata-release-key.asc
   git pull
   git status --short
   ```
4. `scripts/publish.sh key-github DIR`, after step 8 made the `release` environment, puts the subkey
   alone in the environment's secrets: `MUSIKATA_SIGNING_KEY` and `MUSIKATA_SIGNING_PASSPHRASE`, a
   random passphrase made for that copy. `DIR` keeps its own passphrase. It asks for the main
   key's passphrase, doesn't show what you type, and ends with the signing subkey's fingerprint
   that the environment now holds. Then unplug the stick and put it away.
   ```sh
   scripts/publish.sh key-github "$DIR"
   ```

Check: `publish.sh check`, "release key" and "release environment: secrets";
`gpg --show-keys packaging/musikata-release-key.asc` shows both expiry dates.

Renewing the subkey before it expires, and replacing a leaked copy:
[`release.md`](release.md#10-the-release-key-between-releases), 10.

## 8. CI's settings

`scripts/publish.sh setup` makes each of these if it's missing, asking first (answer `y`); a
setting already in place prints `there` (or `on`, `required`) and asks nothing:

- **The `release` environment** (Settings → Environments): you are its required reviewer, and it
  deploys only for tags matching `v*`. Setup makes whoever runs it the reviewer; someone given admin
  for a time to run it for you names you instead, with `--reviewer LOGIN` (on `publish.sh`, and on
  `repo-admin.sh`, which passes it on), and `check` reads the reviewer back. Its secrets come from
  step 7.4. The signing job names it, so a release is signed only after you approve its run.
- **The `tags` ruleset:** all tags. Only admins may create, move or delete one, so starting a
  release takes an admin, and a release can't be published on a tag nobody reviewed.
- **Immutable releases** (Settings → General → Releases): a published release's files and tag can't
  be changed, and GitHub adds a release attestation (`gh release verify`).
- **Actions pinned by SHA** required (step 5).
- **`ci` required** in the `master` ruleset (step 4), once it has passed.
- **The `field-test` label**, on a release's field-test issues (`publish.sh field-test`,
  [`release.md`](release.md), 4).

```sh
scripts/publish.sh setup
```

Check: `publish.sh check`, "release environment", "tags ruleset", "immutable releases" and
"field-test label".

`publish.sh check` reads back every step above, one line each, from "visibility" to "release key".
Once step 7 is done, every line is `ok`:

```sh
scripts/publish.sh check
```

Two lines read `FAIL` until step 7 is done: `release key` until 7.3's pull request is merged, and
`release environment: secrets` until 7.4. A `FAIL` on any other line is a setting that isn't as it
should be: walk its step again.

## Each release

These steps aren't one-time, but they rely on everything above: the release's record, CI's
workflow and the commands, in [`release.md`](release.md).
