#!/bin/sh
# Builds build/release/MusiKata-<version>-x86_64.AppImage and its .sha256 (A6.3; build-and-release.md,
# "The builds"):
#
#   python-build-standalone (PYTHON_BUILD, x86_64, glibc 2.17+)  +  PySide6 and RUNTIME from PyPI
#   (packaging/versions.env, R1.2), Qt trimmed to packaging/qt-modules.txt (A6.2)
#   +  src/musikata, src/musikata_core  ->  AppDir  ->  appimagetool (APPIMAGETOOL_URL and its runtime)
#
# In an Ubuntu 22.04 container (JAMMY_IMAGE, glibc 2.35, the oldest R1.1's desktops have), as
# AppKata's AppImage is: the AppImage's Python runs PySide6 while it builds. Downloads are cached in
# build/appimage-cache, each checked against its SHA-256. scripts/test-appimage.sh starts it once.
#   scripts/build-appimage.sh
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
[ "${MUSIKATA_BUILD_IN_CONTAINER:-}" = 1 ] || "$HERE/coworker/bin/deps" register "$HERE"   # the coworker protocol (the coworker/ submodule): remembers MusiKata, mentions what the host lacks
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/musikata_core/__init__.py")
. "$HERE/packaging/versions.env"
. "$HERE/scripts/lib-python.sh"
if [ "${MUSIKATA_BUILD_IN_CONTAINER:-}" != 1 ]; then
    # with the xcb-util libraries Qt's X11 plugin needs and the AppImage carries; the image's tag
    # follows this recipe
    _df="FROM $JAMMY_IMAGE
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates file libgl1 libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libglib2.0-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 >/dev/null"
    IMG=musikata-build-jammy:$(printf '%s' "$_df" | sha256sum | cut -c1-12)
    docker image inspect "$IMG" >/dev/null 2>&1 || printf '%s\n' "$_df" | docker build -q -t "$IMG" - >/dev/null
    exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e MUSIKATA_BUILD_IN_CONTAINER=1 \
        -v "$HERE:$HERE" -w "$HERE" "$IMG" sh "$HERE/scripts/build-appimage.sh" "$@"
fi
CACHE="$HERE/build/appimage-cache"
APPDIR="$HERE/build/MusiKata.AppDir"
OUT="$HERE/build/release/MusiKata-$VERSION-x86_64.AppImage"
mkdir -p "$CACHE" "$HERE/build/release"

# --- what the build takes from outside, as packaging/versions.env pins it, checked each time
fetch_python "$PY_SERIES" "$CACHE"
pinned() {      # URL SHA256: CACHE/<the SHA-256's first 12>-<its name>, into PINNED
    PINNED="$CACHE/$(printf %s "$2" | cut -c1-12)-${1##*/}"
    echo "$2  $PINNED" | sha256sum -c --quiet >/dev/null 2>&1 && return 0
    curl -fsSL -o "$PINNED.part" "$1"
    echo "$2  $PINNED.part" | sha256sum -c --quiet || { echo "${1##*/} isn't the file packaging/versions.env pins" >&2; exit 1; }
    mv "$PINNED.part" "$PINNED"
}
pinned "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256"
APPIMAGETOOL=$PINNED
chmod +x "$APPIMAGETOOL"
pinned "$APPIMAGE_RUNTIME_URL" "$APPIMAGE_RUNTIME_SHA256"
RUNTIME_FILE=$PINNED

# --- the AppDir: Python, then what MusiKata runs on, installed into it
echo "== AppDir ($(basename "$PYTHON_TARBALL"))"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/musikata" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
tar -xzf "$PYTHON_TARBALL" -C "$APPDIR/usr"            # -> usr/python
PY="$APPDIR/usr/python/bin/python3"
SITE="$APPDIR/usr/python/lib/python$PY_SERIES/site-packages"
# shellcheck disable=SC2086 # RUNTIME is a list of pip specs
"$PY" -m pip install --quiet --no-compile --no-deps --disable-pip-version-check --cache-dir "$CACHE/pip" \
    "PySide6-Essentials==$PYSIDE" "PySide6-Addons==$PYSIDE" "shiboken6==$PYSIDE" $RUNTIME
# Qt trimmed to packaging/qt-modules.txt (A6.2)
"$PY" "$HERE/scripts/qt_trim.py" apply linux "$SITE/PySide6"
# Qt's X11 plugin needs five xcb-util libraries no Debian-family desktop installs, libxcb-cursor
# above all; taken from Ubuntu 22.04, they sit beside Qt's libraries, where Qt's RUNPATH finds them
# (A6.3), with their copyright files for the notices
XCB="$HERE/build/appimage-xcb-util.txt"
: > "$XCB"
for so in libxcb-cursor.so.0 libxcb-icccm.so.4 libxcb-keysyms.so.1 libxcb-image.so.0 libxcb-render-util.so.0; do
    cp -L "/usr/lib/x86_64-linux-gnu/$so" "$SITE/PySide6/Qt/lib/$so"
    pkg=$(dpkg -S "/usr/lib/x86_64-linux-gnu/$so" | cut -d: -f1 | head -1)
    printf -- '--- %s (%s), from Ubuntu 22.04; its source: apt-get source %s ---\n\n' "$so" "$pkg" "$pkg" >> "$XCB"
    cat "/usr/share/doc/$pkg/copyright" >> "$XCB"
    echo >> "$XCB"
done
# The license files, from what was just installed (A6.6)
"$PY" "$HERE/scripts/third_party_notices.py" write "$APPDIR/usr/share/licenses/musikata" --extra "xcb-util=$XCB"
# what the AppImage doesn't use of Python: its GUI toolkit and IDE, pip, the headers and the shared
# libpython (python3 has it built in)
L="$APPDIR/usr/python/lib"
rm -rf "$L/python$PY_SERIES/idlelib" "$L/python$PY_SERIES/tkinter" "$L/python$PY_SERIES/turtledemo" \
    "$L/python$PY_SERIES/ensurepip" "$L/python$PY_SERIES/pydoc_data" "$L/python$PY_SERIES"/config-* \
    "$L/python$PY_SERIES"/lib-dynload/_tkinter.* "$SITE"/pip "$SITE"/pip-* "$L"/libtcl* "$L"/libtk* "$L"/tcl9* "$L"/tk9* \
    "$L"/itcl* "$L"/thread* "$L"/libpython3*.so* "$L/pkgconfig" "$APPDIR/usr/python/include" \
    "$APPDIR/usr/python/bin"/idle* "$APPDIR/usr/python/bin"/pip* "$APPDIR/usr/python/bin"/pydoc* \
    "$APPDIR/usr/python/bin"/python*-config "$SITE"/bin
cp -r "$HERE/src/musikata" "$HERE/src/musikata_core" "$APPDIR/usr/lib/musikata/"
find "$APPDIR/usr/lib/musikata" -name __pycache__ -prune -exec rm -rf {} +
"$PY" -m compileall -q -j 0 "$APPDIR/usr/lib/musikata" "$APPDIR/usr/python/lib/python$PY_SERIES" >/dev/null 2>&1 || true

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
export PYTHONPATH="$HERE/usr/lib/musikata" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
exec "$HERE/usr/python/bin/python3" -s -m musikata "$@"
EOF
chmod +x "$APPDIR/AppRun"
# The file kinds of R2.2 and R8's playlists, for "Open with" only (R1.7): listed here, MusiKata is
# offered for them, and the desktop's default player stays the user's choice
cat > "$APPDIR/musikata.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MusiKata
GenericName=Music Player
Comment=Play, tag and organize your music
Exec=musikata %F
Icon=musikata
Terminal=false
Categories=AudioVideo;Audio;Player;
MimeType=audio/mpeg;audio/flac;audio/x-flac;audio/mp4;audio/x-m4a;audio/aac;audio/ogg;audio/x-vorbis+ogg;audio/vorbis;audio/opus;audio/x-opus+ogg;audio/wav;audio/x-wav;audio/vnd.wave;audio/aiff;audio/x-aiff;audio/x-mpegurl;audio/mpegurl;application/vnd.apple.mpegurl;
StartupWMClass=MusiKata
X-AppImage-Version=$VERSION
EOF
cp "$APPDIR/musikata.desktop" "$APPDIR/usr/share/applications/"
"$PY" "$HERE/scripts/app_icon.py" png "$APPDIR/musikata.png" 256
cp "$APPDIR/musikata.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/musikata.png"
ln -sf musikata.png "$APPDIR/.DirIcon"

echo "== appimagetool"
rm -f "$OUT"
ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run --runtime-file "$RUNTIME_FILE" --no-appstream "$APPDIR" "$OUT" >/dev/null 2>&1 ||
    ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run --runtime-file "$RUNTIME_FILE" --no-appstream "$APPDIR" "$OUT"
(cd "$(dirname "$OUT")" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256")
echo "wrote ${OUT#"$HERE/"} ($(du -h "$OUT" | cut -f1))"
