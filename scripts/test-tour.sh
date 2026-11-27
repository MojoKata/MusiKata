#!/bin/sh
# The tour (docs/architecture/A1-overview.md, A1.6) in tier 1's container, on the demo library: each
# screen of the mockups saved to build/tour/<screen>.png, and every screen's text checked against
# the box it is drawn in (src/musikata/layout.py); a text past its box fails it, and
# build/tour/layout.txt says which. CI's tour job runs it, and the site publishes master's screens
# (docs/process/ci.md, "The Pages site"). Extra args go to the tour (--tour-only L03-songs).
#
# The demo library (scripts/demo_library.py) is made in build/demo when it isn't there, or has no
# change history (R4.9) or root's settings (R9.5's same genres) yet. It is the
# home's Music folder in the container, so the screens show ~/Music, as on a new user's computer.
# The tour runs three times, once in each state it has screens for (src/musikata/tour.py): the
# library; the same root unmounted (X02, R2.10); a first start with nothing configured (X01, R2.1).
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
if [ ! -d "$DEMO/Music/.musikata/history" ] || [ ! -f "$DEMO/Music/.musikata/settings.json" ]; then
    # made before it had its history or its settings: anew
    echo "== the demo library, in $DEMO" >&2
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home -e PYTHONDONTWRITEBYTECODE=1 \
        -v "$HERE:/src:ro" -v "$SITE:/site:ro" -v "$DEMO:/demo" "$IMG" sh -c \
        'cd /src && PYTHONPATH=/site exec "$1" scripts/demo_library.py build /demo' sh "$CPY"
fi
DATA="$HERE/build/tour-data"
rm -rf "$OUT" "$DATA" && mkdir -p "$OUT/x02" "$OUT/x01" "$DATA/library" "$DATA/first"
tour() {   # MUSIC DATA OUT ARGS...: one run, the demo library at MUSIC, DATA as MUSIKATA_DATA
    music=$1 data=$2 out=$3
    shift 3
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home -e MUSIKATA_DATA=/tmp/data \
        -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 \
        -v "$HERE:/src:ro" -v "$SITE:/site:ro" -v "$DEMO/Music:$music:ro" -v "$data:/tmp/data" \
        -v "$out:/out" "$IMG" sh -c \
        'cd /src && PYTHONPATH=/src/src:/site exec "$@"' sh "$CPY" -m musikata --tour /out "$@"
}
status=0
# the library: the demo library is ~/Music, given for the run; its index kept in $DATA/library
tour /tmp/home/Music "$DATA/library" "$OUT" --root /tmp/home/Music "$@" || status=1
# X02: the same root, its folder not there (R2.10), shown from the index the first run made
tour /tmp/elsewhere "$DATA/library" "$OUT/x02" --root /tmp/home/Music "$@" || status=1
# X01: a first start (R2.1): no root given, and an empty data folder, so nothing configured
tour /tmp/elsewhere "$DATA/first" "$OUT/x01" "$@" || status=1
for run in x02 x01; do
    for png in "$OUT/$run"/*.png; do
        if [ -e "$png" ]; then mv "$png" "$OUT/"; fi
    done
    if [ -e "$OUT/$run/layout.txt" ]; then cat "$OUT/$run/layout.txt" >> "$OUT/layout.txt"; fi
    rm -rf "${OUT:?}/$run"
done
rm -rf "$DATA"
exit $status
