#!/bin/sh
# Builds build/release/MusiKata-<version>-<arch>.dmg and its .sha256 on a Mac (A6.5; build-and-
# release.md, "The builds"), for arm64 (Apple silicon) or x86_64 (Intel): python-build-standalone
# for that chip (PYTHON_BUILD, checked against PYTHON_MACOS_<ARCH>_SHA256), PySide6 and RUNTIME,
# with Qt trimmed to packaging/qt-modules.txt (A6.2), frozen by PyInstaller (PYINSTALLER) into
# MusiKata.app (packaging/musikata.spec), ad-hoc signed as PyInstaller signs it (A6.5.1), in a .dmg
# beside a link to /Applications and the license files (A6.6). Both run on an Apple silicon Mac, the
# x86_64 one under Rosetta (arch -x86_64), so its Python picks the x86_64 wheels. The Developer ID
# signing of a release isn't here (build-and-release.md, "Signing"). scripts/test-macos.sh starts it.
#   scripts/build-macos.sh arm64|x86_64
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
"$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule): remembers MusiKata, mentions what the host lacks
ARCH=${1:-}
case $ARCH in
    arm64) TRIPLE=aarch64-apple-darwin; PIN_VAR=PYTHON_MACOS_ARM64_SHA256 ;;
    x86_64) TRIPLE=x86_64-apple-darwin; PIN_VAR=PYTHON_MACOS_X86_64_SHA256 ;;
    *) echo "usage: scripts/build-macos.sh arm64|x86_64" >&2; exit 2 ;;
esac
[ "$(uname -s)" = Darwin ] || { echo "build-macos.sh: this builds on a Mac" >&2; exit 2; }
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/musikata_core/__init__.py")
. "$HERE/packaging/versions.env"
eval "PIN=\$$PIN_VAR"
CACHE="$HERE/build/macos-cache"
W="$HERE/build/macos-$ARCH"
OUT="$HERE/build/release/MusiKata-$VERSION-$ARCH.dmg"
mkdir -p "$CACHE" "$HERE/build/release"
rm -rf "$W" && mkdir -p "$W"
run() { arch "-$ARCH" "$@"; }      # this chip's code: natively, or under Rosetta

# --- the Python, as packaging/versions.env pins it, checked each time
NAME=cpython-$PYTHON_BUILD-$TRIPLE-install_only_stripped.tar.gz
TARBALL="$CACHE/$NAME"
if ! echo "$PIN  $TARBALL" | shasum -a 256 -c -s 2>/dev/null; then
    echo "== python-build-standalone $NAME"
    curl -fsSL -o "$TARBALL.part" "https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_BUILD#*+}/$NAME"
    echo "$PIN  $TARBALL.part" | shasum -a 256 -c -s || { echo "build-macos.sh: $NAME isn't the file packaging/versions.env pins" >&2; exit 1; }
    mv "$TARBALL.part" "$TARBALL"
fi
tar -xzf "$TARBALL" -C "$W"          # -> python/
PY="$W/python/bin/python3"
SITE=$(run "$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
echo "== Python $(run "$PY" -c 'import platform; print(platform.python_version(), platform.machine())')"
# shellcheck disable=SC2086 # PYINSTALLER and RUNTIME are lists of pip specs
run "$PY" -m pip install -q --no-deps --disable-pip-version-check --cache-dir "$CACHE/pip" \
    $PYINSTALLER "PySide6-Essentials==$PYSIDE" "PySide6-Addons==$PYSIDE" "shiboken6==$PYSIDE" $RUNTIME
# the license files, from what was just installed (A6.6), the icon, and Qt trimmed (A6.2)
run "$PY" "$HERE/scripts/third_party_notices.py" write "$W/licenses" --frozen
run "$PY" "$HERE/scripts/app_icon.py" icns "$W/musikata.icns"
run "$PY" "$HERE/scripts/qt_trim.py" apply macos "$SITE/PySide6"

echo "== PyInstaller ($ARCH)"
(cd "$W" && MUSIKATA_ICON="$W/musikata.icns" MUSIKATA_ARCH=$ARCH MUSIKATA_LICENSES="$W/licenses" \
    run "$PY" -m PyInstaller --noconfirm --clean --log-level WARN --distpath "$W/dist" --workpath "$W/work" \
    "$HERE/packaging/musikata.spec")
APP="$W/dist/MusiKata.app"
EXE="$APP/Contents/MacOS/musikata"
test -x "$EXE" || { echo "build-macos.sh: PyInstaller made no $EXE" >&2; exit 1; }
[ "$(lipo -archs "$EXE")" = "$ARCH" ] || { echo "build-macos.sh: musikata is $(lipo -archs "$EXE"), not $ARCH" >&2; exit 1; }
find "$APP" -name Main.qml -path '*musikata/qml/*' | grep -q . || { echo "build-macos.sh: the QML files are missing from the bundle" >&2; exit 1; }
find "$APP" -name 'libqcocoa.dylib' | grep -q . || { echo "build-macos.sh: the bundle lacks Qt's macOS platform plugin" >&2; exit 1; }
# anything left for the other chip: PyInstaller thins what it collects to ARCH
OTHER=$(find "$APP" -type f \( -name '*.dylib' -o -name '*.so' \) -exec lipo -archs {} \; 2>/dev/null | grep -v "^$ARCH\$" | sort | uniq -c || true)
[ -z "$OTHER" ] || echo "build-macos.sh: libraries not only $ARCH: $OTHER"
codesign --verify --deep --strict "$APP" || { echo "build-macos.sh: the bundle's ad-hoc signature doesn't verify" >&2; exit 1; }
echo "MusiKata.app: $(du -sh "$APP" | cut -f1)"

echo "== the .dmg"
STAGE="$W/dmg"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/MusiKata.app"
ln -s /Applications "$STAGE/Applications"
cp "$W/licenses/LICENSE.txt" "$W/licenses/THIRD-PARTY-NOTICES.txt" "$STAGE/"
rm -f "$OUT"
hdiutil create -quiet -volname MusiKata -srcfolder "$STAGE" -fs HFS+ -format UDZO "$OUT"
(cd "$(dirname "$OUT")" && shasum -a 256 "$(basename "$OUT")" > "$(basename "$OUT").sha256")
echo "wrote ${OUT#"$HERE/"} ($(du -h "$OUT" | cut -f1))"
