#!/bin/sh
# The tour (docs/architecture/A1-overview.md, A1.6) in tier 1's container, on the demo library: each
# screen of the mockups saved to build/tour/<screen>.png, and every screen's text checked against
# the box it is drawn in (src/musikata/layout.py); a text past its box fails it, and
# build/tour/layout.txt says which. CI's tour job runs it, and the site publishes master's screens
# (docs/process/ci.md, "The Pages site"). Extra args go to the tour (--tour-only L03-songs).
#
# The demo library (scripts/demo_library.py) is made in build/demo when it isn't there. It is the
# home's Music folder in the container, so the screens show ~/Music, as on a new user's computer.
#   scripts/test-tour.sh [--tour-only NAMES]
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
"$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule): remembers MusiKata, mentions what the host lacks
. "$HERE/scripts/lib-tier1.sh"
tier1_setup "$HERE"
CPY="/src${PYT#"$HERE"}"
DEMO="$HERE/build/demo"
OUT="$HERE/build/tour"
mkdir -p "$DEMO"
if [ ! -d "$DEMO/Music" ]; then
    echo "== the demo library, in $DEMO" >&2
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home -e PYTHONDONTWRITEBYTECODE=1 \
        -v "$HERE:/src:ro" -v "$SITE:/site:ro" -v "$DEMO:/demo" "$IMG" sh -c \
        'cd /src && PYTHONPATH=/site exec "$1" scripts/demo_library.py build /demo' sh "$CPY"
fi
rm -rf "$OUT" && mkdir -p "$OUT"
exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home -e MUSIKATA_DATA=/tmp/data \
    -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$HERE:/src:ro" -v "$SITE:/site:ro" -v "$DEMO/Music:/tmp/home/Music:ro" -v "$OUT:/out" "$IMG" sh -c \
    'cd /src && PYTHONPATH=/src/src:/site exec "$@"' sh "$CPY" -m musikata --root /tmp/home/Music --tour /out "$@"
