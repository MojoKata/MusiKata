#!/usr/bin/env python3
"""The license files every build carries (A6.6): MusiKata's own license as LICENSE.txt, and
THIRD-PARTY-NOTICES.txt, every part the build carries that others made, with its version, its
license, the license's text and where its source is.

    scripts/third_party_notices.py write OUT [--frozen] [--extra TITLE=FILE ...]

Run with the Python the build carries, after it installed what it carries: the notices are made
from that Python's own LICENSE.txt and from the packages installed beside it (their metadata,
their license files and the libraries their wheels bundle), so they can't fall behind a pin. The
packages are the ones packaging/versions.env pins for running MusiKata (PYSIDE's three, RUNTIME, and
the platform's media controls, MEDIA_WINDOWS or MEDIA_MACOS, A4.5), and with --frozen PyInstaller,
whose bootloader starts the Windows and macOS builds; each must be
installed at its pinned version, or nothing is written. --extra adds a part the build copies from
elsewhere (the AppImage's xcb-util libraries), with its license text from FILE.

A package whose wheel doesn't carry its license's text (PySide6 and shiboken6, whose wheels carry
only a note for Qt's commercial licensees, and most of PyObjC's) gets it from packaging/licenses/,
as does FFmpeg, which PyAV's wheels carry built.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import os
import platform
import re
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LICENSES = os.path.join(ROOT, "packaging", "licenses")
RULE = "=" * 78
LICENSE_FILE = re.compile(r"(?i)^(licen[cs]e|copying|notice|authors)[^/]*$")

# the PyObjC packages of MEDIA_MACOS whose wheels carry no license file
PYOBJC_WITHOUT_LICENSE = (
    "pyobjc-core",
    "pyobjc-framework-avfoundation",
    "pyobjc-framework-coreaudio",
    "pyobjc-framework-coremedia",
    "pyobjc-framework-mediaplayer",
)
# the platform's media controls (A4.5), by sys.platform
MEDIA = {"win32": "MEDIA_WINDOWS", "darwin": "MEDIA_MACOS"}

# what packaging/licenses/ adds to a package, and why: the license MusiKata takes it under, and
# the texts of that license
QT_SOURCE = "https://code.qt.io/cgit/ (each module's repository at the tag v{version})"
ADDED = {
    "pyside6-essentials": (
        "Qt {version} and its Python binding, the open-source edition: MusiKata takes them under "
        "the GNU Lesser General Public License, version 3 (LGPL-3.0-only; its text below, with "
        "the GNU GPL version 3 it builds on in LICENSE.txt). Source: " + QT_SOURCE + " and "
        "https://code.qt.io/cgit/pyside/pyside-setup.git/ (v{version}).",
        ["LGPL-3.txt"],
    ),
    "pyside6-addons": (
        "Qt {version}'s add-on modules (Qt Multimedia among them) and their Python binding, the "
        "open-source edition, under the LGPL-3.0-only, as PySide6-Essentials above.",
        [],
    ),
    "shiboken6": (
        "The runtime of PySide6's bindings, under the LGPL-3.0-only, as PySide6-Essentials above.",
        [],
    ),
    **{
        name: (
            "PyObjC's wheels carry its license's text in some of them only: it is under the MIT "
            "license (its text below, as pyobjc-framework-Cocoa's wheel has it). Source: "
            "https://github.com/ronaldoussoren/pyobjc (v{version}).",
            ["PyObjC.txt"],
        )
        for name in PYOBJC_WITHOUT_LICENSE
    },
    "av": (
        "PyAV's wheel carries FFmpeg's libraries, built by PyAV ({ffmpeg}), with the codec "
        "libraries listed above; FFmpeg's source and its build: "
        "https://github.com/PyAV-Org/pyav-ffmpeg. The x264 and x265 libraries are under the GNU "
        "GPL version 2 or later, and FFmpeg's under the GNU LGPL version 3 or later (both texts "
        "below).",
        ["LGPL-3.txt", "GPL-2.txt"],
    ),
}


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def assigned(text: str, var: str) -> str:
    """The value versions.env gives `var` (VAR=... or : "${VAR:=...}"); "" when none."""
    m = re.search(rf'^\s*: "\${{{var}:=([^}}"\n]*)}}"', text, re.M) or re.search(
        rf'^\s*{var}="?([^"\n]*)', text, re.M
    )
    return m.group(1).split(" #")[0].strip() if m else ""


def carried(env: str, frozen: bool = False, on: str = sys.platform) -> dict[str, str]:
    """The packages a build carries, by name (lower case, `-` for `_`), each with its pinned
    version: PySide6's three at PYSIDE, the RUNTIME specs, the media controls of the platform `on`
    (a sys.platform), and PyInstaller for a frozen build."""
    pyside = assigned(env, "PYSIDE")
    out = {n: pyside for n in ("pyside6-essentials", "pyside6-addons", "shiboken6")}
    specs = assigned(env, "RUNTIME").split()
    if on in MEDIA:
        specs += assigned(env, MEDIA[on]).split()
    if frozen:  # PyInstaller's own line, not the dependencies it builds with
        specs += [s for s in assigned(env, "PYINSTALLER").split() if s.startswith("pyinstaller==")]
    for spec in specs:
        name, _, version = spec.partition("==")
        out[name.lower().replace("_", "-")] = version
    return out


def license_of(meta: md.PackageMetadata) -> str:
    return meta.get("License-Expression") or meta.get("License") or "see its license below"


def bundled(files: list[str]) -> list[str]:
    """The libraries a wheel bundles (auditwheel's <name>.libs/, delocate's .dylibs/,
    delvewheel's <name>.libs/), by name."""
    return sorted(
        f.rsplit("/", 1)[-1] for f in files if f.split("/")[0].endswith(".libs") or "/.dylibs/" in f
    )


def license_texts(dist: md.Distribution) -> list[tuple[str, str]]:
    """(name, text) of each license file a package's .dist-info holds, but the note for Qt's
    commercial licensees."""
    out = []
    for f in sorted(dist.files or [], key=str):
        rel = str(f).replace("\\", "/")
        parts = rel.split("/")
        if not parts[0].endswith(".dist-info") or "__pycache__" in parts:
            continue
        if "licenses" in parts[1:-1] or (len(parts) == 2 and LICENSE_FILE.match(parts[1])):
            if parts[-1] == "LicenseRef-Qt-Commercial.txt" or parts[-1].endswith(".py"):
                continue
            out.append(("/".join(parts[1:]), read(str(dist.locate_file(f)))))
    return out


def ffmpeg() -> str:
    """FFmpeg's version and license, as the PyAV installed says."""
    try:
        import av
        from av import _core
    except ImportError:
        return "FFmpeg"
    lic = _core.library_meta["libavcodec"]["license"]
    return f"FFmpeg {av.ffmpeg_version_info}, {lic}"


def fill(text: str) -> str:
    return textwrap.fill(text, 98, break_long_words=False, break_on_hyphens=False)


def section(title: str, body: str) -> str:
    return f"{RULE}\n{title}\n{RULE}\n\n{body.strip()}\n\n"


def package(name: str, dist: md.Distribution) -> str:
    """A package's part of the notices."""
    meta = dist.metadata
    lines = [f"License: {license_of(meta)}"]
    urls = {
        label.strip().lower(): url.strip()
        for label, _, url in (u.partition(",") for u in meta.get_all("Project-URL") or [])
    }
    home = meta.get("Home-page") or next(
        (urls[k] for k in ("homepage", "home", "source", "repository", "source code") if k in urls),
        next(iter(urls.values()), ""),
    )
    if home:
        lines.append(f"Home: {home}")
    libs = bundled([str(f).replace("\\", "/") for f in dist.files or []])
    if libs:
        lines.append("Libraries its wheel bundles: " + ", ".join(libs))
    body = "\n".join(lines)
    note, extra = ADDED.get(name, ("", []))
    if note:
        body += "\n\n" + fill(note.format(version=dist.version, ffmpeg=ffmpeg()))
    for path, text in license_texts(dist):
        body += f"\n\n--- {path} ---\n\n{text.strip()}"
    for name_ in extra:
        body += f"\n\n--- {name_} ---\n\n{read(os.path.join(LICENSES, name_)).strip()}"
    return section(f"{meta['Name']} {dist.version}", body)


def python_license() -> str:
    """The text of the running Python's LICENSE.txt, wherever its build put it."""
    for where in (os.path.dirname(os.__file__), sys.prefix):
        path = os.path.join(where, "LICENSE.txt")
        if os.path.exists(path):
            return read(path)
    raise FileNotFoundError(f"no LICENSE.txt in {os.path.dirname(os.__file__)} or {sys.prefix}")


def notices(packages: dict[str, str], extras: list[tuple[str, str]]) -> str:
    """THIRD-PARTY-NOTICES.txt's text. Raises LookupError when a package isn't installed at its
    pinned version."""
    out = [
        fill(
            "MusiKata is free software under the GNU General Public License, version 3 or later "
            "(LICENSE.txt). It carries these parts that others made, each under its own license, "
            "given here with its text."
        )
        + "\n\n",
        section(f"Python {platform.python_version()}", python_license()),
    ]
    for name, pinned in packages.items():
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            raise LookupError(f"{name} isn't installed") from None
        if dist.version != pinned:
            raise LookupError(f"{name} is {dist.version}, packaging/versions.env pins {pinned}")
        out.append(package(name, dist))
    for title, path in extras:
        out.append(section(title, read(path)))
    return "".join(out)


def write(out: str, frozen: bool, extras: list[tuple[str, str]]) -> int:
    env = read(os.path.join(ROOT, "packaging", "versions.env"))
    try:
        text = notices(carried(env, frozen), extras)
    except LookupError as e:
        print(f"third_party_notices: {e}", file=sys.stderr)
        return 1
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "LICENSE.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(read(os.path.join(ROOT, "LICENSE")))
    with open(os.path.join(out, "THIRD-PARTY-NOTICES.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(f"third_party_notices: LICENSE.txt and THIRD-PARTY-NOTICES.txt in {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["write"])
    ap.add_argument("out", help="the folder the two files go into")
    ap.add_argument("--frozen", action="store_true", help="a PyInstaller build: PyInstaller too")
    ap.add_argument("--extra", action="append", default=[], metavar="TITLE=FILE")
    a = ap.parse_args(argv)
    extras = [tuple(e.split("=", 1)) for e in a.extra]
    if any(len(e) != 2 for e in extras):
        ap.error("--extra takes TITLE=FILE")
    return write(a.out, a.frozen, extras)  # type: ignore[arg-type]


if __name__ == "__main__":
    sys.exit(main())
