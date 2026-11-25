#!/bin/sh
# check.sh: what tier 1 would fail on that can be checked in seconds, before every commit
# (docs/process/development.md, "Before each commit"). Stops at the first step that fails and says
# which.
#
#   scripts/check.sh                  run the checks
#   scripts/check.sh --install-hook   make it this clone's git pre-commit hook (opt-in, per clone)
#
# The tools come from the development environment, .venv by default (development.md, "Running from
# source"); MUSIKATA_VENV names another.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
cd "$HERE"

if [ "${1-}" = --install-hook ]; then
    hook=$(git rev-parse --git-path hooks)/pre-commit
    [ ! -e "$hook" ] || { echo "check.sh: $hook is there already: look at it first" >&2; exit 1; }
    mkdir -p "$(dirname "$hook")"
    printf '#!/bin/sh\nexec "$(git rev-parse --show-toplevel)/scripts/check.sh"\n' > "$hook"
    chmod +x "$hook"
    echo "check.sh: $hook runs scripts/check.sh before each commit (git commit --no-verify skips it)"
    exit 0
fi
[ $# = 0 ] || { sed -n '2,/^set -eu/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; exit 2; }

VENV=${MUSIKATA_VENV:-$HERE/.venv}
[ -x "$VENV/bin/python" ] || { echo "check.sh: no $VENV: see docs/process/development.md" >&2; exit 2; }
PY=$VENV/bin/python

step() {        # NAME COMMAND...: run it; on failure, say which step and stop
    name=$1; shift
    printf '== %s\n' "$name" >&2
    "$@" || { echo "check.sh: $name failed" >&2; exit 1; }
}

step "ruff format" "$PY" -m ruff format --check --quiet .
step "ruff check" "$PY" -m ruff check --quiet .
if find src -name '*.py' 2>/dev/null | grep -q .; then
    step "mypy" "$PY" -m mypy src
fi
step "the documents" python3 scripts/doccheck.py --quiet
private_names() {   # every file git tracks or would add, through public_text.py
    git ls-files -z -co --exclude-standard |
        xargs -0 sh -c 'for f; do [ -f "$f" ] && printf "%s\0" "$f"; done' sh |
        xargs -0 python3 scripts/public_text.py check
}
step "private names" private_names
step "the fast tests" "$PY" -m pytest -q -m "not slow" -p no:cacheprovider
echo "check.sh: all clean" >&2
