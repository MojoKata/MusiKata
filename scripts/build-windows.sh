#!/bin/sh
# Builds build/release/MusiKata-<version>-setup.exe and its .sha256 (A6.4; build-and-release.md,
# "The builds") on Linux, as AppKata's installer is built: PyInstaller under Wine (PYWINE_IMAGE,
# whose Python is PYTHON_BUILD's version, R1.2) freezes MusiKata with PySide6 trimmed to
# packaging/qt-modules.txt (A6.2), RUNTIME and MEDIA_WINDOWS (A4.5), then Inno Setup under Wine
# (INNOSETUP_IMAGE) makes the installer (packaging/windows/musikata.iss); every image and package
# as packaging/versions.env pins it. scripts/test-windows.sh starts it once.
#   scripts/build-windows.sh
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
"$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule): remembers MusiKata, mentions what the host lacks
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/musikata_core/__init__.py")
. "$HERE/packaging/versions.env"
W="$HERE/build/windows"
mkdir -p "$HERE/build/release" "$HERE/build/wine-cache"
rm -rf "$W" && mkdir -p "$W"

# Wine has no ICU, and Qt 6.10 and later import Windows' icuuc.dll: a stand-in, for Wine only
# (packaging/windows/icuuc-stub.c), compiled once
ICU="icuuc-$(sha256sum < "$HERE/packaging/windows/icuuc-stub.c" | cut -c1-12).dll"
test -f "$HERE/build/wine-cache/$ICU" || docker run --rm -v "$HERE:/src" "$MINGW_IMAGE" sh -c "
  apt-get -qq update && apt-get -qq install -y --no-install-recommends gcc-mingw-w64-x86-64-win32 >/dev/null 2>&1
  x86_64-w64-mingw32-gcc -shared -s -nostdlib -Wl,--entry,0 -o /src/build/wine-cache/$ICU /src/packaging/windows/icuuc-stub.c
  chown $(id -u):$(id -g) /src/build/wine-cache/$ICU"
test -f "$HERE/build/wine-cache/$ICU" || { echo "build-windows.sh: couldn't build the icuuc.dll stand-in" >&2; exit 1; }

# the installer carries the AppImage's Python (R1.2): the Wine image's must be the same version
PYV=${PYTHON_BUILD%%+*}
V=$(docker run --rm "$PYWINE_IMAGE" sh -c "wine python -c 'import platform; print(platform.python_version())'" 2>/dev/null | tr -d '\r' | tail -1)
[ "$V" = "$PYV" ] || { echo "build-windows.sh: $PYWINE_IMAGE carries Python $V, the release $PYV (packaging/versions.env)" >&2; exit 1; }

echo "== PyInstaller (Wine)"
# Wine's own chatter (fixme, err) is left out of what's shown; the log keeps it
LOG="$W/pyinstaller.log"
# shellcheck disable=SC2086 # PYINSTALLER, RUNTIME and MEDIA_WINDOWS are lists of pip specs
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -e MUSIKATA_ICON='Z:\src\build\windows\musikata.ico' \
    -v "$HERE:/src" -v "$HERE/build/wine-cache:/cache" -w /src "$PYWINE_IMAGE" sh -c "
  set -e
  cp /cache/$ICU \$WINEPREFIX/drive_c/windows/system32/icuuc.dll
  wine python -m pip install -q --no-deps --disable-pip-version-check --cache-dir Z:/cache/pip \
      $PYINSTALLER PySide6-Essentials==$PYSIDE PySide6-Addons==$PYSIDE shiboken6==$PYSIDE $RUNTIME $MEDIA_WINDOWS
  wine python scripts/app_icon.py ico build/windows/musikata.ico
  wine python scripts/qt_trim.py apply windows C:/Python/Lib/site-packages/PySide6
  wine python -m PyInstaller --noconfirm --clean --log-level WARN --distpath Z:/src/build/windows/dist \
      --workpath Z:/src/build/windows/work packaging/musikata.spec
  wine python scripts/third_party_notices.py write build/windows/dist/MusiKata --frozen
" > "$LOG" 2>&1 && st=0 || st=$?
grep -vE "^(wine|[0-9a-f]{4}:(fixme|err|warn|trace))|^$" "$LOG" | tr -d '\r' || true
# the container runs as root: the outputs go back to the user who runs this
docker run --rm -v "$HERE:/src" "$PYWINE_IMAGE" sh -c "chown -R $(id -u):$(id -g) /src/build; find /src/src /src/scripts /src/packaging -name __pycache__ -prune -exec rm -rf {} +" >/dev/null 2>&1 || true
[ "$st" = 0 ] || { echo "build-windows.sh: PyInstaller's step failed ($st); its log: ${LOG#"$HERE/"}" >&2; exit 1; }
DIST="$W/dist/MusiKata"
test -f "$DIST/musikata.exe" || { echo "build-windows.sh: PyInstaller made no musikata.exe" >&2; exit 1; }
test -f "$DIST/_internal/musikata/qml/Main.qml" || { echo "build-windows.sh: the QML files are missing from the build" >&2; exit 1; }
test -f "$DIST/LICENSE.txt" && test -f "$DIST/THIRD-PARTY-NOTICES.txt" || { echo "build-windows.sh: the license files are missing" >&2; exit 1; }
# PyInstaller's Qt hook leaves out Qt's plugins and QML, with only a warning, when Qt won't load
# under Wine
for f in plugins/platforms/qwindows.dll qml/QtQuick/Controls/Basic Qt6Multimedia.dll; do
    test -e "$DIST/_internal/PySide6/$f" || { echo "build-windows.sh: the build lacks PySide6/$f: did Qt load under Wine? (${LOG#"$HERE/"})" >&2; exit 1; }
done
# and it carries no ICU: Windows' own serves Qt, and the stand-in, which does nothing, never ships
ICUS=$(find "$DIST" -iname 'icu*.dll')
test -z "$ICUS" || { echo "build-windows.sh: the build carries ICU, where Windows' own must serve: $ICUS" >&2; exit 1; }
echo "build/windows/dist/MusiKata: $(du -sh "$DIST" | cut -f1)"

echo "== Inno Setup (Wine)"
# The image's Wine runs as its own user, uid 1000, which can write only where anyone may: Setup is
# written into a folder of its own, then moved
mkdir -p "$W/setup" && chmod 777 "$W/setup" && chmod -R a+rX "$W"
docker run --rm -v "$HERE:/work" -w /work/packaging/windows "$INNOSETUP_IMAGE" "/DAppVersion=$VERSION" \
    "/O..\\..\\build\\windows\\setup" musikata.iss 2>&1 | tail -3
docker run --rm -v "$HERE:/src" "$PYWINE_IMAGE" chown -R "$(id -u):$(id -g)" /src/build/windows/setup >/dev/null 2>&1 || true
OUT="MusiKata-$VERSION-setup.exe"
test -f "$W/setup/$OUT" || { echo "build-windows.sh: Inno Setup wrote no $OUT" >&2; exit 1; }
mv -f "$W/setup/$OUT" "$HERE/build/release/$OUT"
(cd "$HERE/build/release" && sha256sum "$OUT" > "$OUT.sha256")
echo "wrote build/release/$OUT ($(du -h "$HERE/build/release/$OUT" | cut -f1))"
