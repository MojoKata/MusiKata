#!/bin/sh
# Tier 1 at the times and in the time zones where a test that reads the clock goes wrong: the
# start of the UTC day, its middle and its end, a year's end, the zones furthest from UTC either
# way, and a zone with daylight saving time (US Central's). MusiKata's own code takes a clock
# (docs/process/coding.md); this finds the test, or the library call, that reads the real one
# anyway: "last played today", a date in the locale's form, the 180-day cleanup (A2.9). Each run
# is scripts/test-tier1.sh with MUSIKATA_CLOCK and MUSIKATA_TZ; extra args go to pytest. Exits 1
# if any run fails, after all of them.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
"$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule): remembers MusiKata, mentions what the host lacks
YEAR_END="$(date -u +%Y)-12-31 23:58"
[ "$(date -u +%s)" -lt "$(date -u -d "$YEAR_END" +%s)" ] || YEAR_END="$(($(date -u +%Y) + 1))-12-31 23:58"
FAILED=
run() {     # CLOCK TZ [PYTEST ARGS]
    clock=$1 tz=$2 log=$(mktemp)
    shift 2
    MUSIKATA_CLOCK=$clock MUSIKATA_TZ=$tz sh "$HERE/scripts/test-tier1.sh" "$@" >"$log" 2>&1
    rc=$?
    printf '%-18s %-24s %s\n' "$clock" "${tz:-UTC}" "$(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed)' "$log" | tail -1 | tr -d '=')"
    [ "$rc" = 0 ] || { FAILED=1; grep -E '^(FAILED|ERROR) ' "$log" | sed 's/^/    /'; }
    rm -f "$log"
}
for t in 00:05 12:00 23:58 "$YEAR_END"; do run "$t" "" "$@"; done
run 10:05 XST-14 "$@"                     # UTC+14: 00:05 tomorrow there
run 11:58 YST12 "$@"                      # UTC-12: 23:58 yesterday there
run 06:05 CST6CDT,M3.2.0,M11.1.0 "$@"     # US Central, with daylight saving time: 00:05 there in winter, 01:05 in summer
[ -z "$FAILED" ]
