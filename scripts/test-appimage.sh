#!/bin/sh
# Starts the AppImage once (build-and-release.md, "The builds"): in an Ubuntu 24.04 container that
# holds what A6.3 says the AppImage takes from the system and nothing more of a desktop (glibc,
# OpenGL, X11's and XCB's client libraries, xkbcommon, PulseAudio, D-Bus, GLib, fonts) but an X
# server, it plays a demo file to its end on X11 (Xvfb) and quits, so a part of Qt trimmed by mistake (A6.2), a library the AppImage
# lacks, or a decoder PyAV's FFmpeg lacks fails it. The sound device is PulseAudio's null sink, as
# in tier 1 (scripts/test-tier1.sh). Also checks --version, the .desktop file's file kinds (R1.7)
# and the license files (A6.6).
#
# The demo file is made with the AppImage's own Python and PyAV (scripts/demo_library.py).
#   scripts/test-appimage.sh [APPIMAGE]      build/release/MusiKata-<version>-x86_64.AppImage by default
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
"$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule): remembers MusiKata, mentions what the host lacks
. "$HERE/packaging/versions.env"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/musikata_core/__init__.py")
APPIMAGE=$(cd "$(dirname "${1:-$HERE/build/release/MusiKata-$VERSION-x86_64.AppImage}")" && pwd)/$(basename "${1:-MusiKata-$VERSION-x86_64.AppImage}")
[ -f "$APPIMAGE" ] || { echo "test-appimage.sh: no $APPIMAGE: scripts/build-appimage.sh builds it" >&2; exit 1; }
# the image's tag follows this recipe
_df="FROM $NOBLE_IMAGE
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends libgl1 libegl1 libgl1-mesa-dri libxkbcommon0 libxkbcommon-x11-0 libxcb-shape0 libxcb-util1 libxcb-xkb1 libfontconfig1 fonts-noto-core libdbus-1-3 libglib2.0-0t64 libpulse0 pulseaudio xvfb >/dev/null"
IMG=musikata-appimage-start:$(printf '%s' "$_df" | sha256sum | cut -c1-12)
docker image inspect "$IMG" >/dev/null 2>&1 || printf '%s\n' "$_df" | timeout 600 docker build -q -t "$IMG" - >/dev/null
echo "== $(basename "$APPIMAGE") ($(du -h "$APPIMAGE" | cut -f1)), started in Ubuntu 24.04"
# the container ends with its processes (PulseAudio, Xvfb): nothing is left running
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home -v "$APPIMAGE:/r/MusiKata.AppImage:ro" \
    -v "$HERE/scripts:/scripts:ro" "$IMG" sh -c '
    set -e
    mkdir -p "$HOME" /tmp/music && cd /tmp
    cp /r/MusiKata.AppImage /tmp/MusiKata.AppImage
    ./MusiKata.AppImage --appimage-extract >/dev/null
    ./MusiKata.AppImage --appimage-extract-and-run --version
    grep -q "^MimeType=audio/mpeg;audio/flac;.*audio/x-mpegurl;" squashfs-root/musikata.desktop
    grep -q "^PySide6_Essentials" squashfs-root/usr/share/licenses/musikata/THIRD-PARTY-NOTICES.txt
    grep -q "GNU GENERAL PUBLIC LICENSE" squashfs-root/usr/share/licenses/musikata/LICENSE.txt
    echo "the .desktop file lists the file kinds, and the license files are there"
    squashfs-root/usr/python/bin/python3 -c "import sys; sys.path.insert(0, \"/scripts\"); import demo_library as d; d.encode(\"/tmp/music/demo.mp3\", \"mp3\", 3.0, 440)"
    export XDG_RUNTIME_DIR=$(mktemp -d)
    pulseaudio --daemonize=yes -n --exit-idle-time=-1 --use-pid-file=no --log-level=error \
        --load=module-native-protocol-unix --load="module-null-sink sink_name=musikata_null norewinds=1"
    Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
    for _ in $(seq 100); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.1; done
    DISPLAY=:99 MUSIKATA_DATA=/tmp/data timeout 120 ./MusiKata.AppImage --appimage-extract-and-run \
        --root /tmp/music --play /tmp/music/demo.mp3 > /tmp/play.out 2> /tmp/play.err && st=0 || st=$?
    cat /tmp/play.out
    if [ "$st" != 0 ] || ! grep -q "demo.mp3: played to its end" /tmp/play.out; then
        echo "test-appimage.sh: the play ended $st; it said:" >&2; tail -n 30 /tmp/play.err >&2; exit 1
    fi
    grep -q "added=1" /tmp/play.err || { echo "test-appimage.sh: the scan of the root didn'"'"'t run" >&2; exit 1; }'
echo "test-appimage.sh: the AppImage played the demo file to its end on X11, and scanned its root"
