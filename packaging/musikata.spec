# PyInstaller's spec for the Windows and macOS builds (A6.4, A6.5): one folder, MusiKata/musikata.exe
# on Windows (scripts/build-windows.sh, under Wine), MusiKata.app on macOS (scripts/build-macos.sh).
# The PySide6 it collects is already trimmed to packaging/qt-modules.txt (A6.2).
import os
import re
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (PyInstaller's)
SRC = os.path.join(ROOT, "src")
ICON = os.environ["MUSIKATA_ICON"]  # the build's .ico or .icns (scripts/app_icon.py)
sys.path.insert(0, SRC)  # for collect_submodules
with open(os.path.join(SRC, "musikata_core", "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'^__version__ = "(.*)"', f.read(), re.M).group(1)

# every module of both packages, as some are imported inside functions (the tour); the QML and the
# schemas as data
hidden = collect_submodules("musikata") + collect_submodules("musikata_core")
# the license files, inside the macOS bundle (Windows' go beside musikata.exe, after PyInstaller)
LICENSES = os.environ.get("MUSIKATA_LICENSES", "")
licenses = [(os.path.join(LICENSES, f), ".") for f in ("LICENSE.txt", "THIRD-PARTY-NOTICES.txt")]
a = Analysis(  # noqa: F821
    [os.path.join(SRC, "musikata", "__main__.py")],
    pathex=[SRC],
    datas=[
        (os.path.join(SRC, "musikata", "qml"), "musikata/qml"),
        (os.path.join(SRC, "musikata_core", "schemas"), "musikata_core/schemas"),
        *(licenses if LICENSES else []),
    ],
    hiddenimports=hidden,
    excludes=["tkinter", "unittest", "pydoc", "pytest"],
)
exe = EXE(  # noqa: F821
    PYZ(a.pure),  # noqa: F821
    a.scripts,
    [],
    exclude_binaries=True,
    name="musikata",
    console=False,
    icon=ICON,
    target_arch=os.environ.get("MUSIKATA_ARCH"),  # macOS: the chip, to which universal2 is thinned
)
app = COLLECT(exe, a.binaries, a.datas, name="MusiKata")  # noqa: F821

if sys.platform == "darwin":
    # the file kinds of R2.2 and R8's playlists, at the Alternate rank: macOS offers MusiKata in
    # Open With and never makes it the default (R1.7, A6.5)
    KINDS = [
        ("Audio file", ["public.mp3", "org.xiph.flac", "public.mpeg-4-audio", "com.apple.m4a-audio",
                        "org.xiph.ogg-audio", "org.xiph.opus", "com.microsoft.waveform-audio",
                        "public.aiff-audio", "public.aifc-audio"]),  # fmt: skip
        ("Playlist", ["public.m3u-playlist", "public.mpeg-4-audio-playlist"]),
    ]
    BUNDLE(  # noqa: F821
        app,
        name="MusiKata.app",
        icon=ICON,
        bundle_identifier="io.github.mojokata.MusiKata",
        version=re.sub(r"[^0-9.].*", "", VERSION).rstrip("."),
        info_plist={
            "CFBundleName": "MusiKata",
            "CFBundleDisplayName": "MusiKata",
            "CFBundleShortVersionString": re.sub(r"[^0-9.].*", "", VERSION).rstrip("."),
            "LSMinimumSystemVersion": "14.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.music",
            "CFBundleDocumentTypes": [
                {"CFBundleTypeName": name, "CFBundleTypeRole": "Viewer",
                 "LSHandlerRank": "Alternate", "LSItemContentTypes": types}  # fmt: skip
                for name, types in KINDS
            ],
        },
    )
