# MusiKata: process

How MusiKata is worked on: the order things happen in, the rules the documents keep, and where
each step's details are. It follows the Kata suite's way of working (AppKata's in particular),
written here so this repository stands on its own.

| File | Covers |
|---|---|
| This file | The flow of a change, the documents' rules, decisions, reviews, commits and pull requests |
| [`coding.md`](coding.md) | How code is written: built to be tested in isolation, layout and imports, style and types, errors, threads, QML, dependencies, comments |
| [`development.md`](development.md) | The repository's layout, running from source, the demo library, the tour |
| [`testing.md`](testing.md) | The testing principles, the test tiers, what each environment runs, and CI |
| [`ci.md`](ci.md) | CI's measures: coverage by area and its floors, the Pages site (coverage, hardening, screenshots), failure annotations, pin ages |
| [`build-and-release.md`](build-and-release.md) | The builds, pinned inputs and signing |
| [`release.md`](release.md) | A release, step by step: the release pull request, `publish.sh`, the field test, publishing, the Homebrew cask |
| [`release-agent.md`](release-agent.md) | The agent's part of a release: prepare it, look into a stopped one, wrap it up |
| [`genesis.md`](genesis.md) | The repository's one-time setup: its settings, the release key, CI's settings, and how to check them |
| [`../REVIEW.md`](../REVIEW.md) | MusiKata's part of a code review: document groups, areas, sensitive code, commands, labels |

## The flow of a change

1. **Requirements first.** What MusiKata does is written in
   [`../requirements/`](../requirements/README.md) before it is built. A change in behaviour starts
   as a change there.
2. **Mockups with it.** If users will see it, the mockups change in the same commit
   ([below](#mockups-in-step-with-the-requirements)).
3. **Why, where it isn't obvious.** A choice between real alternatives, or one that a later reader
   would question, goes into [`../architecture/`](../architecture/README.md) with what was weighed.
4. **Decisions in a walk thru.** A batch of open choices (question issues, `[Q#n]`; review
   findings; design options) is settled one item at a time, each with its options lettered and a
   recommendation, and nothing is built until the whole batch is approved. The answers go into the
   requirements and the question issues are closed.
5. **Build on a branch,** written as [`coding.md`](coding.md) says and tested as
   [`testing.md`](testing.md) says, in a pull request. It is ready when every box of the pull
   request's checklist (`.github/pull_request_template.md`) is ticked or struck through as not
   applying.
6. **Review** before merging: the diff, against the requirements it claims, with findings fixed or
   filed.
7. **Squash merge,** then confirm the merged code matches the branch, and clean up the branch, its
   worktree and anything made only for it.

## The documents' rules

- **Lasting ids.** R and A ids are never renumbered or reused (requirements README, rule 1);
  questions, gaps and other issues are GitHub issues, cited by number (rule 4).
- **A statement, not a changelog.** Requirements and architecture say what is, in the present tense,
  with no dates, versions, "now", "no longer" or status. Status goes in the root `README.md` (the
  product and its releases) and `DEVELOP.md` (the build).
- **References are ids,** never file names or line numbers: `R3.6.1`, `A3.4`, `[Q#13]`.
- **A file past 500 lines** becomes a folder with a file per first-level item.
- **Names sort by id:** each number in a file or folder name is zero-padded to the width of the
  largest among its siblings (`R01-…` to `R19-…`); ids themselves are never padded.
- **Free standing.** The documents describe MusiKata in its own terms; another project may be
  named as where a practice comes from, never as where MusiKata's behaviour is defined.
- **Code comments** say why, cite requirement ids (`R4.7`), and never cite a review or other
  document that goes away.

## Mockups in step with the requirements

[`../mockups/`](../mockups/README.md) holds a picture of every main screen, drawn by
`docs/mockups/src/render.py` from the design tokens of R6.2. Any change to the requirements that
touches what a user sees or does (a screen, field, button, dialog, setting, state or message, or
their order) updates the mockups in the same change, and the README's table of what each shows.
A change that only touches internals needs none; the pull request says so.

The mockups are PNGs of 256 colours (quantized by Pillow), drawn at 1280 × 800 and saved at twice
the pixels, so they stay small in git and sharp on a laptop's screen. Once the app runs, the tour
(A1.6) makes screenshots of the real screens under the same names, and the mockups stay the
design reference for what isn't built yet.

## Commits, branches and pull requests

- Every commit and tag is GPG-signed, by the identity git's configuration chooses.
- Work is done on a branch, never on `master`; a branch takes `master` in with merge commits, never
  a rebase, so review comments stay attached.
- Pull requests are squash merged, so each lands on `master` as one commit with a message that says
  what changed and why.
- Nothing is committed that holds a secret (signing keys, tokens, `.env`).

## Shared configuration

As in the other Kata projects, two submodules hold what the projects share; after cloning,
`git submodule update --init` fetches them.

- `agents/` (EpiphanySoft/agents): the shared Claude configuration (hooks, walk thrus, review and
  relay skills), imported by the repository's `CLAUDE.md`.
- `coworker/` (MojoKata/coworker): the coworker protocol, which lists what a machine needs for the
  builds and tests (`.coworker/deps.json`, written once there are builds and tests to need it) and
  what waits on a human.

Each is pinned to a commit, and moves only by a commit here that says why.
