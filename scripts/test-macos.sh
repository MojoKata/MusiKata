#!/bin/sh
# Starts a macOS build once (build-and-release.md, "The builds"), on the Mac that built it: the
# .dmg is mounted and MusiKata.app copied out of it, its Info.plist checked for the file kinds of R1.7
# at the Alternate rank (offered in Open With, never the default; A6.5) and the .dmg for the license
# files (A6.6); then the app plays a demo file to its end and quits, the x86_64 one under Rosetta.
# So a part of Qt trimmed by mistake (A6.2), a module PyInstaller left out, a library of the wrong
# chip or a decoder PyAV's FFmpeg lacks fails it. On a Mac with no sound device --play decodes the
# file to its end instead and ends with 3 (src/musikata/app.py): everything short of the sound,
# which this says.
#
# The demo file is made with the build's own Python and PyAV (build/macos-<arch>/python,
# scripts/demo_library.py).
#   scripts/test-macos.sh arm64|x86_64
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
"$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule): remembers MusiKata, mentions what the host lacks
ARCH=${1:-}
case $ARCH in arm64|x86_64) ;; *) echo "usage: scripts/test-macos.sh arm64|x86_64" >&2; exit 2 ;; esac
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/musikata_core/__init__.py")
DMG="$HERE/build/release/MusiKata-$VERSION-$ARCH.dmg"
PY="$HERE/build/macos-$ARCH/python/bin/python3"
[ -f "$DMG" ] && [ -x "$PY" ] || { echo "test-macos.sh: no $DMG: scripts/build-macos.sh $ARCH builds it" >&2; exit 1; }
T=$(mktemp -d)
trap 'hdiutil detach -quiet "$T/mnt" 2>/dev/null || true; rm -rf "$T"' EXIT
echo "== $(basename "$DMG") ($(du -h "$DMG" | cut -f1)), started on macOS $(sw_vers -productVersion) ($(uname -m))"
hdiutil attach -quiet -nobrowse -readonly -mountpoint "$T/mnt" "$DMG"
test -f "$T/mnt/LICENSE.txt" && test -f "$T/mnt/THIRD-PARTY-NOTICES.txt" && test -L "$T/mnt/Applications"
ditto "$T/mnt/MusiKata.app" "$T/MusiKata.app"
hdiutil detach -quiet "$T/mnt"
PLIST="$T/MusiKata.app/Contents/Info.plist"
for i in 0 1; do
    [ "$(plutil -extract "CFBundleDocumentTypes.$i.LSHandlerRank" raw "$PLIST")" = Alternate ] ||
        { echo "test-macos.sh: the bundle's document type $i isn't at the Alternate rank" >&2; exit 1; }
done
plutil -extract CFBundleDocumentTypes.0.LSItemContentTypes json -o - "$PLIST" | grep -q public.mp3
echo "the .dmg holds the license files, and the bundle offers the file kinds at the Alternate rank"
echo "sound devices: $(system_profiler SPAudioDataType 2>/dev/null | grep -c 'Output Channels' || true) with outputs"

mkdir -p "$T/Music" "$T/home"
arch "-$ARCH" "$PY" -c "import sys; sys.path.insert(0, '$HERE/scripts'); import demo_library as d; d.encode('$T/Music/demo.mp3', 'mp3', 3.0, 440)"
# a watchdog: macOS has no timeout(1)
HOME="$T/home" MUSIKATA_DATA="$T/data" arch "-$ARCH" "$T/MusiKata.app/Contents/MacOS/musikata" \
    --root "$T/Music" --play "$T/Music/demo.mp3" > "$T/play.out" 2> "$T/play.err" &
pid=$!
n=0
while kill -0 "$pid" 2>/dev/null && [ $n -lt 300 ]; do sleep 1; n=$((n + 1)); done
if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"; echo "test-macos.sh: --play still ran after 300 s; it said:" >&2; tail -n 30 "$T/play.err" >&2; exit 1
fi
wait "$pid" && st=0 || st=$?
cat "$T/play.out"
if [ "$st" != 0 ] && [ "$st" != 3 ] || ! grep -q "added=1" "$T/play.err"; then
    echo "test-macos.sh: --play ended $st, or its scan did not run; it said:" >&2; tail -n 30 "$T/play.err" >&2; exit 1
fi
if [ "$st" = 0 ]; then
    echo "test-macos.sh: MusiKata.app ($ARCH) played the demo file to its end, and scanned its root"
else
    echo "test-macos.sh: MusiKata.app ($ARCH) decoded the demo file to its end with no sound device to play it on, and scanned its root"
fi
