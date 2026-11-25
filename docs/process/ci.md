# CI's measures and the Pages site

What CI measures beyond passing tier 1, where it publishes it, and how a failed step says why. When
each run happens is [`testing.md`](testing.md) ("CI"); the builds and their signing,
[`build-and-release.md`](build-and-release.md).

## Coverage

Tier 1 runs its tests under coverage.py (`MUSIKATA_COVERAGE=1`, `scripts/test-tier1.sh`; the pin is
`COVERAGE` in `packaging/versions.env`, the settings `[tool.coverage.*]` in `pyproject.toml`): lines
and branches of `src/` and `scripts/`, in pytest's process, in the worker processes (`concurrency =
["thread", "multiprocessing"]`, A1.3) and in every Python process the tests start that inherits its
environment (`patch = ["subprocess"]`). A process started with an environment of its own isn't
measured.

The `coverage` job combines the data and runs `scripts/coverage_report.py report --check`:

- **By area:** line and branch coverage of each area's code (`scripts/areas.py`, the same areas as
  the `area:` labels), in the job's summary and in `summary.md`.
- **A floor per area,** in `tests/coverage-floor.json`: an area below its floor in lines or branches
  fails the job. `coverage_report.py floor` raises each floor to a run's measure less **3 lines and
  3 branches**, rounded down to a tenth of a point, so run-to-run jitter doesn't fail a small area;
  it never lowers one. A floor is lowered only by hand, with the reason in the commit.
- **The changed lines:** of the lines a pull request adds or changes in `src/` and `scripts/`, how
  many tier 1 reaches, and a notice on each of the largest stretches it doesn't, which the pull
  request shows on those lines.
- **QML** isn't Python, and coverage.py can't read it: the `qml` area is listed with its file count
  and no figure, and has no floor. Its tests drive the QML offscreen against the real models, which
  count in `app`.

A floor is raised only from CI's measure of the change that raises it: the `coverage` artifact of
its run (`gh run download RUN -n coverage -D build/coverage-ci`, then `coverage_report.py floor
build/coverage-ci/totals.json`), committed to that change before it merges; never from a local run.
The artifact holds the HTML report (`html/index.html`), `totals.json`, `files.json` (each file's
counts) and coverage.py's own `coverage.json`.

## The Pages site

The repository's GitHub Pages site, https://mojokata.github.io/MusiKata/, is built by
`scripts/coverage_site.py` and published on each push to `main`. It has three pages:

- **Coverage** (`index.html`, the site's front page): the `coverage` job's figures by area against
  their floors, each area's files linked to their line-by-line report (`report/`), and each area's
  line and branch coverage over the pushes, with the sums *App* (every area but the scripts') and
  *Overall*. Beside it are `history.json`, a point per push (its commit, pull request, totals by
  area and findings by area), and `files.json`.
- **Hardening** (`hardening.html`, `scripts/hardening.py`): each sweep of the shared `review` skill,
  a label `sweep:<name>` such as `sweep:CR1`, with its anchor issue and its steps, the anchor's
  sub-issues titled "CR1.n …", each with the pull request GitHub links as closing it; each step's
  findings, the issues below it at any depth, with their severity ("severity High", "Med" or "Low"
  in the body), area (the `area:` label, else the step's) and state (open; waiting on the owner
  while it carries `refine`, `dismiss` or `question`; fixed; closed); the coverage and findings by
  area; each area's mutation testing, from its latest record in `docs/hardening/mutation/`, marked
  "baseline, changed since" when a module has changed since that record or isn't in it; and the open
  issues labelled `gap` or `question` that aren't findings. Only an issue's number, title, labels,
  state and severity reach the page; its body text doesn't.
- **Screenshots** (`screenshots/index.html`): the Linux tour (A1.6), `main`'s under
  `screenshots/main/`, replaced by each push, and each release's under `screenshots/<version>/`,
  kept; all listed in `screenshots/index.json`. `screenshots/latest/` is a copy of the newest
  release's tour, or `main`'s while there is no release, made afresh by each build.

The `site` job builds it on every run, a pull request's included, after `coverage` and the tour: it
downloads their artifacts, brings in each published release's tour the site doesn't hold yet
(`coverage_site.py release-tours DIR`, from CI's passing run of its tag, while GitHub keeps that
artifact, 90 days), reads the issues with the job's token, runs `scripts/public_text.py check` on
the pages, and keeps the site as the `site` artifact, so a pull request's site can be downloaded and
opened (`gh run download RUN -n site`). The `pages` job runs on a push to `main` only, after `ci`
and `site`: it alone may deploy, to the `github-pages` environment, which takes deployments from
`main` alone.

A deployment replaces the whole site, so what the site keeps across pushes lives on the site itself:
each build reads `history.json` and `screenshots/index.json` (and the files it lists) back from the
published site and carries them into the new one, with this commit's point added last. A site that
answers with neither file starts afresh only while there is no site at all; any other failure to
read them, or the issues, fails the job, so a bad moment never starts the history over. A run on
`main` never cancels another that is running, so each build reads what the one before it published.

Built by hand, it is a preview of what publishing a commit would show, from a `coverage` artifact:

```sh
gh run download RUN -n coverage -D build/coverage
python3 scripts/coverage_site.py build          # build/site/index.html
```

`MUSIKATA_SITE` reads the history from another address (a local server, say), and `MUSIKATA_REPO`
names another repository's issues.

## When a step fails

Each script step tees its output to `build/ci-<job>.log`, and when it fails, `scripts/ci-tail.sh`
posts its last 40 lines as one error annotation, so the reason shows on the pull request's Checks
page and through GitHub's API without opening the run's log. Steps run under `bash -eo pipefail`, so
a script's failure isn't hidden by the `tee`.

## Pins

`scripts/pins-newest.py` lists every input the builds, the tests and CI pin
(`packaging/versions.env`, the build scripts, the workflows' actions), how old each pinned release
is, and the newest release old enough to move to. It fails when a pin is younger than the 14-day
cooldown ([`build-and-release.md`](build-and-release.md), "Pinned inputs"), unless it is named with
`--allow`: an exception the owner made for a security fix that can't wait, which the commit that
pins it records. It uses the network; `GITHUB_TOKEN` raises GitHub's limit.
