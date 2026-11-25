# Code review

MusiKata's own part of a code review: its commands, names and cases. The method (the stages, the
pieces and their briefs, the claim kinds, confirmation, the owner's questions and the filing) is the
shared `review` skill, [`agents/skills/review/SKILL.md`](../agents/skills/review/SKILL.md), and
nothing here restates it. The filing script's config is [`review.json`](review.json). Both files
live here, at `docs/`, because the skill looks for them there.

## Requirements and their ids

Requirement ids are R… ([`requirements/`](requirements/README.md)), architecture ids A…
([`architecture/`](architecture/README.md)). Code cites the item it builds in a comment or a string,
as "(R4.7)", and [`scripts/doccheck.py`](../scripts/doccheck.py) checks that every id cited names an
item.

## Document groups

| Group | Documents |
|---|---|
| `docs-1-library` | [`requirements/README.md`](requirements/README.md), R1 to R5, R8 to R10, R12 and R13 |
| `docs-2-player` | R6, R7, R11 and R14 to R19, [`mockups/README.md`](mockups/README.md) (what each screen shows) |
| `docs-3-architecture` | [`architecture/`](architecture/README.md), A1 to A7 |
| `docs-4-process` | [`README.md`](../README.md), [`DEVELOP.md`](../DEVELOP.md), [`process/`](process/README.md), this file |

Each group also reads the open `gap` and `question` issues on its sections. `docs/reviews/` and
`docs/releases/` are records of their day, and no group reads them.

MusiKata has no glossary. Terms are checked against the requirements' own definitions: a term is set
in bold where it is defined, most of them in R2. A term used without a definition is a Doc Review
claim.

## Areas

The areas are those of [`scripts/areas.py`](../scripts/areas.py), the same as the `area:` labels, in
its order; `python3 scripts/areas.py` prints them. A finding on a document is in `docs`, and one on
the tooling in `tooling`: `.github/`, `packaging/`, `.coworker/` and the test tooling
(`tests/conftest.py`, `tests/skips/`), read against [`process/testing.md`](process/testing.md),
[`process/ci.md`](process/ci.md) and [`process/build-and-release.md`](process/build-and-release.md).

## Sensitive code

Read whole whenever any of it changed:

| Code | What depends on it |
|---|---|
| The safe write of tags and art (A3.4) | the user's music files: a bad write damages a song (Principle 1) |
| Organizing and removing files (R12, R2.11) | files moved, renamed or sent to the trash (Principle 5) |
| The change history and the root's own files (A3.5, A2.8, A2.9) | Undo, and the plays, ratings and dismissals that computers sharing a root keep together |
| The updater (R1.9) | what is downloaded, checked and run; MusiKata replacing itself |
| The online client (A7.1, A7.2) | what leaves the computer (R16.3), and the certificates it trusts |
| The parsers of files from anywhere: tags (A3), M3U (R8), `.cue`, LRC (R17), Equalizer APO (R19.7) | input MusiKata didn't write |
| `scripts/publish.sh`, `scripts/build-*.sh` | the release signing and what a release holds |
| `.github/workflows/` | CI's secrets and the signing environment |

## The mechanical check

```
python3 scripts/doccheck.py > review/<N>/checks.txt
```

It reports ids cited that name nothing, issue links that aren't their issue, each index's sections
against the files, section files too long or ids numbered twice, and words and dates a statement
doesn't carry; its header says which of those fail the run.

## Commands

A claim may reproduce with:

- one test: `.venv/bin/python -m pytest tests/<file>::<test>`;
- the fast set: `.venv/bin/python -m pytest -m "not slow"` (under 30 seconds);
- tier 1 in its container, the release's Python and PySide6: `scripts/test-tier1.sh -k <test name>`,
  which takes minutes, so an attended review asks first;
- CI's artifacts of the latest `master` run: the coverage report, the tour and the mutation
  baseline.

A review never starts the Windows or desktop VMs' runs, `scripts/test-clock.sh`,
`scripts/test-mutate.sh` or `scripts/mutate.py`, the builds (`scripts/build-*.sh`),
`scripts/publish.sh` or `scripts/repo-admin.sh`.

An unattended run of a command over a minute is capped at 10 minutes.

## Earlier reviews

A review by this method with none before it has no delta and no earlier findings.

## Settled records

- The requirements README's "Not in MusiKata", and the issues closed as `no`.
- The open `gap`, `question` and `future` issues.

Won't do is `no`, later is `future` (agreed, with no time set) and a gap is `gap`. MusiKata keeps no
rejected-ideas file.

## Claim kinds and severity

MusiKata adds no claim kinds. A music file damaged, moved, renamed or removed when the user didn't
ask for it, or a play count, rating or past save lost, is at least Med (Principles 1 and 5).

## Branch and labels

The target branch is `master`. The labels are the skills' defaults: `question` is a question issue,
`refine` a finding that waits on the owner's decision, and `dismiss` a finding the work showed to be
no defect. `review.json` sets no `labels` and no `kind_prefix`: an issue carries only the labels the
skill gives it, and a finding's kind is in its body only.

## After a review

What follows a review is the shared `review-triage` skill's,
[`agents/skills/review-triage/SKILL.md`](../agents/skills/review-triage/SKILL.md): the findings
sorted, batched into work units and scheduled, and the schedule run. `review.json` sets none of its
fields, so its defaults hold: a sweep's schedule is `docs/remediation/<sweep>-schedule.json`, a unit
holds at most 20 findings, at most 3 units are open at once, and a file that 3 or more units change
is listed in the schedule as shared. The hardening page ([`process/ci.md`](process/ci.md)) shows a
finding that waits on the owner (`refine`, `dismiss`, or a question issue below a step) apart from
the open ones.
