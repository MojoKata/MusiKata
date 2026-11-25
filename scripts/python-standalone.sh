#!/bin/sh
# The Python every release carries (packaging/versions.env), for development and the tests (R1.2):
# python-build-standalone of PY_SERIES unpacked to build/python-<series>, with the tools the tests
# and checks need (pytest, coverage.py, ruff, mypy, Hypothesis, jsonschema), fetched once, and again
# when a pin changes. Prints the path of its python3; progress goes to stderr. x86_64 Linux.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
. "$HERE/packaging/versions.env"
. "$HERE/scripts/lib-python.sh"
DEST="$HERE/build/python-$PY_SERIES"
TOOLS="$PYTEST $COVERAGE $RUFF $MYPY $HYPOTHESIS $JSONSCHEMA"
PIN="$PY_SERIES from $PYTHON_BUILD with $TOOLS"
current() { [ -x "$DEST/python/bin/python3" ] && [ "$(cat "$DEST/.pin" 2>/dev/null)" = "$PIN" ]; }
if ! current; then
    # one at a time: runs that start together each ask for it (flock, where present)
    mkdir -p "$HERE/build"
    exec 9>"$HERE/build/.python-$PY_SERIES.lock"
    command -v flock >/dev/null 2>&1 && flock 9
    if ! current; then
        fetch_python "$PY_SERIES" "$HERE/build/python-cache" >&2
        tmp=$(mktemp -d "$DEST.XXXXXX") && chmod 755 "$tmp"      # mktemp's 700 keeps containers' users out
        tar -xzf "$PYTHON_TARBALL" -C "$tmp"          # -> python/
        # shellcheck disable=SC2086 # TOOLS is a list of pip specs
        "$tmp/python/bin/python3" -m pip install -q --no-deps --disable-pip-version-check \
            --no-warn-script-location $TOOLS >&2
        echo "$PIN" > "$tmp/.pin"
        rm -rf "$DEST" && mv "$tmp" "$DEST"
    fi
fi
echo "$DEST/python/bin/python3"
