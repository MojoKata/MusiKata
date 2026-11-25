#!/bin/sh
# Tier 1 -- the whole local suite (tests/) -- in a container, on the Python and the PySide6 the
# release carries (packaging/versions.env, R1.2), whatever this machine has. Extra args go to
# pytest. A skip tests/skips/tier1.txt doesn't list fails the run (tests/conftest.py), and every run
# lists its slowest tests (docs/process/testing.md, "Principles").
#
# MUSIKATA_COVERAGE=1 runs the tests under coverage.py (pyproject.toml, [tool.coverage.run]), which
# writes its data to build/tier1/coverage/, for scripts/coverage_report.py (docs/process/ci.md,
# "Coverage").
#
# When and where it runs (scripts/test-clock.sh): MUSIKATA_CLOCK=HH:MM (the next time it's that,
# UTC) or 'YYYY-MM-DD HH:MM' (in the future) moves every process's clock there (libfaketime, by an
# offset: the clock still runs, and the processes the tests start share it); MUSIKATA_TZ=a POSIX TZ
# ('XST-14' is UTC+14) sets the time zone, UTC otherwise.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
"$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule): remembers MusiKata, mentions what the host lacks
. "$HERE/scripts/lib-tier1.sh"
tier1_setup "$HERE"
CPY="/src${PYT#"$HERE"}"
FAKETIME=
if [ -n "${MUSIKATA_CLOCK:-}" ]; then
    now=$(date -u +%s)
    case $MUSIKATA_CLOCK in
        *-*) to=$(date -u -d "$MUSIKATA_CLOCK" +%s) ;;
        *) to=$(date -u -d "$(date -u +%F) $MUSIKATA_CLOCK" +%s) && { [ "$to" -gt "$now" ] || to=$((to + 86400)); } ;;
    esac || { echo "test-tier1.sh: MUSIKATA_CLOCK=$MUSIKATA_CLOCK isn't a time" >&2; exit 2; }
    # ahead only: libfaketime moves the monotonic clock too, which mustn't go below zero
    [ "$to" -gt "$now" ] || { echo "test-tier1.sh: MUSIKATA_CLOCK=$MUSIKATA_CLOCK is in the past" >&2; exit 2; }
    FAKETIME=+$((to - now))
    echo "== the clock at $(date -u -d "@$to" '+%Y-%m-%d %H:%M') UTC${MUSIKATA_TZ:+, TZ=$MUSIKATA_TZ}" >&2
fi
export FAKETIME MUSIKATA_TZ="${MUSIKATA_TZ:-}" MUSIKATA_COVERAGE="${MUSIKATA_COVERAGE:-}"
# what a measured run writes, in build/tier1/ (/out in the container)
OUT="$HERE/build/tier1"
mkdir -p "$OUT"
[ -z "$MUSIKATA_COVERAGE" ] || { rm -rf "$OUT/coverage" && mkdir "$OUT/coverage"; }
exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 \
    -e MUSIKATA_SKIPS="${MUSIKATA_SKIPS-tier1}" -e FAKETIME -e MUSIKATA_TZ -e MUSIKATA_COVERAGE \
    -v "$HERE:/src:ro" -v "$SITE:/site:ro" -v "$OUT:/out" "$IMG" sh -c \
    'if [ -n "$FAKETIME" ]; then export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1; else unset FAKETIME; fi
    if [ -n "$MUSIKATA_TZ" ]; then export TZ="$MUSIKATA_TZ"; fi
    run="-m pytest"
    if [ -n "$MUSIKATA_COVERAGE" ]; then run="-m coverage run -m pytest" && export COVERAGE_FILE=/out/coverage/.coverage; fi
    mkdir -p "$HOME" && cd /src && echo "Python $('"$CPY"' -c "import sys; print(sys.version.split()[0])"), PySide6 $(PYTHONPATH=/site '"$CPY"' -c "import PySide6; print(PySide6.__version__)")${MUSIKATA_COVERAGE:+, measured}" && PYTHONPATH=/src/src:/site exec '"$CPY"' $run -q -p no:cacheprovider --durations=15 tests/ "$@"' sh "$@"
