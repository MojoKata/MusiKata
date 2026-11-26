#!/bin/sh
# Starts the Windows build once (build-and-release.md, "The builds"), under Wine in a container, as
# it is built (PYWINE_IMAGE, with PulseAudio added): the installer runs silently for the current
# user, the file kinds of R1.7 are checked in the registry for "Open with", and the installed
# musikata.exe plays a demo file to its end and quits, with an X server (Xvfb) and PulseAudio's null
# sink as the sound device, which Wine's audio driver plays into (as in tier 1,
# scripts/test-tier1.sh). So a part of Qt trimmed by mistake (A6.2), a module PyInstaller left out,
# or a decoder PyAV's FFmpeg lacks fails it.
#
# Wine stands in for Windows here: Windows itself is tier 3's (docs/process/testing.md). Qt's Windows
# audio finds no device under Wine 11 (it passes over each endpoint Wine gives, which has no
# container id), so there --play decodes the file to its end instead of playing it and ends with 3
# (src/musikata/app.py): everything short of the sound. The demo file is made with PyAV in the Wine
# image's Python (scripts/demo_library.py).
#   scripts/test-windows.sh [SETUP_EXE]      build/release/MusiKata-<version>-setup.exe by default
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
"$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule): remembers MusiKata, mentions what the host lacks
. "$HERE/packaging/versions.env"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/musikata_core/__init__.py")
SETUP=${1:-$HERE/build/release/MusiKata-$VERSION-setup.exe}
SETUP=$(cd "$(dirname "$SETUP")" && pwd)/$(basename "$SETUP")
[ -f "$SETUP" ] || { echo "test-windows.sh: no $SETUP: scripts/build-windows.sh builds it" >&2; exit 1; }
ICU="icuuc-$(sha256sum < "$HERE/packaging/windows/icuuc-stub.c" | cut -c1-12).dll"
[ -f "$HERE/build/wine-cache/$ICU" ] || { echo "test-windows.sh: no build/wine-cache/$ICU: scripts/build-windows.sh makes it" >&2; exit 1; }
# the image's tag follows this recipe
_df="FROM $PYWINE_IMAGE
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends pulseaudio >/dev/null"
IMG=musikata-wine-start:$(printf '%s' "$_df" | sha256sum | cut -c1-12)
docker image inspect "$IMG" >/dev/null 2>&1 || printf '%s\n' "$_df" | timeout 600 docker build -q -t "$IMG" - >/dev/null
echo "== $(basename "$SETUP") ($(du -h "$SETUP" | cut -f1)), installed and started under Wine"
# the container ends with its processes (PulseAudio, Xvfb, Wine's server): nothing is left running
docker run --rm -v "$SETUP:/r/setup.exe:ro" -v "$HERE/scripts:/scripts:ro" -v "$HERE/build/wine-cache:/cache:ro" \
    -e RUNTIME="$RUNTIME" -e ICU="$ICU" "$IMG" sh -c '
    set -e
    cp "/cache/$ICU" "$WINEPREFIX/drive_c/windows/system32/icuuc.dll"
    mkdir -p /tmp/music /tmp/out
    Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/tmp/out/xvfb.log 2>&1 &
    for _ in $(seq 100); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.1; done
    export DISPLAY=:99
    wine python -m pip install -q --no-deps --disable-pip-version-check --cache-dir Z:/tmp/pip $RUNTIME 2>/dev/null
    wine python -c "import sys; sys.path.insert(0, \"Z:/scripts\"); import demo_library as d; d.encode(\"Z:/tmp/music/demo.mp3\", \"mp3\", 3.0, 440)" 2>/dev/null
    wine Z:/r/setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER "/LOG=Z:\\tmp\\out\\setup.log" 2>/dev/null || true
    APP="$WINEPREFIX/drive_c/users/$(whoami)/AppData/Local/Programs/MusiKata"
    test -f "$APP/musikata.exe" || { echo "test-windows.sh: Setup installed no musikata.exe; its log:" >&2; tail -n 20 /tmp/out/setup.log >&2; exit 1; }
    test -f "$APP/LICENSE.txt" && test -f "$APP/THIRD-PARTY-NOTICES.txt"
    # each kind under OpenWithProgids, and no default taken (the value of the extension itself)
    wine python -c "
import sys, winreg
for ext, prog in ((\".mp3\", \"MusiKata.Audio\"), (\".flac\", \"MusiKata.Audio\"), (\".m3u8\", \"MusiKata.Playlist\")):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf\"Software\\Classes\\{ext}\\OpenWithProgids\") as k:
        winreg.QueryValueEx(k, prog)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf\"Software\\Classes\\{ext}\") as k:
        try:
            sys.exit(f\"Setup made MusiKata the default for {ext}\") if winreg.QueryValueEx(k, \"\")[0] else None
        except FileNotFoundError:
            pass
" 2>/dev/null || { echo "test-windows.sh: the file kinds aren'"'"'t registered for Open with as they should be" >&2; exit 1; }
    echo "installed for the current user, with the license files; .mp3, .flac and .m3u8 offered in Open with, no default taken"
    export XDG_RUNTIME_DIR=$(mktemp -d)
    pulseaudio --daemonize=yes -n --exit-idle-time=-1 --use-pid-file=no --log-level=error \
        --load=module-native-protocol-unix --load="module-null-sink sink_name=musikata_null norewinds=1" 2>/dev/null
    # Qt on Windows draws through calls Wine lacks (mscms.dll WcsCreateIccProfile, Wine 11), so it
    # draws offscreen here; Wine passes no QT_ variable from the environment, so it is set in Wine
    wine reg add "HKCU\\Environment" /v QT_QPA_PLATFORM /d offscreen /f >/dev/null 2>&1
    MUSIKATA_DATA="Z:\\tmp\\data" timeout 300 wine "$APP/musikata.exe" --root Z:/tmp/music --play Z:/tmp/music/demo.mp3 > /tmp/out/play.log 2>&1 && st=0 || st=$?
    grep -E "demo.mp3: (played|decoded) to its end" /tmp/out/play.log | tr -d "\r"
    if [ "$st" != 0 ] && [ "$st" != 3 ] || ! grep -q "added=1" /tmp/out/play.log; then
        echo "test-windows.sh: musikata.exe --play ended $st, or its scan did not run; Wine said:" >&2
        grep -vE "fixme:" /tmp/out/play.log | tail -n 30 >&2; exit 1
    fi'
echo "test-windows.sh: the installed MusiKata started under Wine, scanned its root, and played the demo"
echo "file to its end, or, where Qt finds no sound device under Wine, decoded it to its end (--play's 3)"
