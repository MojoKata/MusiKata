# Shared Claude configuration

The `agents/` submodule (EpiphanySoft/agents) holds the Claude configuration shared across projects:
its `CLAUDE.md`, imported here, and the hooks and status line that file names. "Adjacent" in it means
beside that file, in `agents/`.

@agents/CLAUDE.md

# Coding and testing

Code is written as [`docs/process/coding.md`](docs/process/coding.md) says, starting with its first
section: every piece built so its logic can be tested in isolation, fast. Tests keep the principles
at the top of [`docs/process/testing.md`](docs/process/testing.md).

Before each commit, run `scripts/check.sh` and fix what it reports; a pull request is ready when
every box of `.github/pull_request_template.md` is ticked or struck through as not applying.
