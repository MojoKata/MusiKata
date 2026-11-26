#!/usr/bin/env python3
"""Trims an installed PySide6 to the Qt that MusiKata uses (A6.2): what `packaging/qt-modules.txt`
allows stays, and the rest of the PySide6 folder goes, before a build packs it.

PySide6's wheels carry all of Qt, tools and type stubs included; MusiKata uses a few of its modules.
The allow list names them, with the plugins and QML modules they need, and a `keep` line for each
other file of PySide6 that a run needs. Each build trims the PySide6 it installed: the AppImage's
before packing it, the Windows and macOS builds' before PyInstaller collects it, so all three carry
the same Qt.

Qt loads most of what it uses only when it is first used (a QML module when a screen imports it, a
plugin when a session wants it), so a part removed by mistake shows nowhere but there. Before
removing anything, apply checks, and stops on a fault:

- each line for the platform still names something in the folder, so a Qt update that renames a
  part fails the build instead of quietly carrying it again or dropping it;
- each QML module kept has the modules its `qmldir` imports or depends on (but optional ones);
- each library kept (ELF, the Linux build's) has the libraries it links.

Each build's start test (build-and-release.md, "The builds") then plays a file in the packed app,
which loads the rest.

    scripts/qt_trim.py apply linux|windows|macos PYSIDE6_DIR [--dry-run]

The list's lines: `module NAME` (a Qt module: its library and its Python binding), `plugin
TYPE/NAME` (a plugin, by its name without `lib` and the extension), `qml PATH` (a QML module: a
folder of Qt's qml folder holding a `qmldir`, with its files but not the modules below it), `keep
PATTERN` (any other path in the PySide6 folder: a shell pattern, `*` within a part, naming the path
or a folder it is in); each may end with the platforms it is for (`linux`, `windows`, `macos`),
all three when it names none. Everything else in the PySide6 folder goes.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import struct
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, "..", "packaging", "qt-modules.txt")
PLATFORMS = ("linux", "windows", "macos")
KINDS = ("module", "plugin", "qml", "keep")


@dataclass(frozen=True)
class Line:
    kind: str
    name: str
    number: int  # in the file, for what it says about it


@dataclass
class Allowed:
    """The allow list's lines for one platform, by kind."""

    lines: list[Line] = field(default_factory=list)

    def names(self, kind: str) -> set[str]:
        return {line.name for line in self.lines if line.kind == kind}


def parse(text: str, platform: str) -> Allowed:
    """The lines of an allow list that are for `platform`. Raises ValueError on a line it can't
    read, naming it."""
    out = Allowed()
    for number, raw in enumerate(text.splitlines(), 1):
        words = raw.split("#")[0].split()
        if not words:
            continue
        if len(words) < 2 or words[0] not in KINDS or any(w not in PLATFORMS for w in words[2:]):
            raise ValueError(f"line {number}: {raw.strip()!r} isn't KIND NAME [PLATFORM ...]")
        if len(words) == 2 or platform in words[2:]:
            out.lines.append(Line(words[0], words[1], number))
    return out


# --- where PySide6 keeps each part, by platform
# --------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    lib: str  # Qt's libraries, from the PySide6 folder ("" is the folder itself)
    plugins: str
    qml: str


LAYOUTS = {
    "linux": Layout("Qt/lib", "Qt/plugins", "Qt/qml"),
    "macos": Layout("Qt/lib", "Qt/plugins", "Qt/qml"),
    "windows": Layout("", "plugins", "qml"),
}
QT_LIBRARY = {
    "linux": re.compile(r"^libQt6(\w+)\.so(\.\d+)*$"),
    "macos": re.compile(r"^Qt(\w+)\.framework$"),
    "windows": re.compile(r"^Qt6(\w+)\.dll$"),
}
BINDING = re.compile(r"^Qt(\w+)\.(abi3\.so|pyd)$")


def plugin_name(filename: str) -> str:
    """A plugin's name as the list gives it: libqxcb.so, qwindows.dll, libqcocoa.dylib -> qxcb,
    qwindows, qcocoa."""
    name = re.sub(r"\.(so|dylib|dll)$", "", filename)
    return name[3:] if name.startswith("lib") else name


def matches(pattern: str, rel: str) -> bool:
    """Whether a keep pattern names `rel` or a folder it is in; `*` stays within a part."""
    parts, pp = rel.split("/"), pattern.strip("/").split("/")
    if len(parts) < len(pp):
        return False
    return all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts, pp, strict=False))


def _under(rel: str, folder: str) -> str | None:
    """`rel` from `folder` ("" is the top), or None when it isn't under it."""
    if not folder:
        return rel
    return rel[len(folder) + 1 :] if rel.startswith(folder + "/") else None


@dataclass
class Plan:
    """What apply would do: the paths that go (the topmost of each), the lines that named nothing,
    and the faults that stop it."""

    remove: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # files kept, for the link checks
    unused: list[Line] = field(default_factory=list)
    faults: list[str] = field(default_factory=list)


def qml_modules(root: str, layout: Layout) -> set[str]:
    """The QML modules in a PySide6 folder: each folder of its qml folder with a qmldir, from it."""
    top = os.path.join(root, layout.qml)
    return {
        os.path.relpath(d, top).replace(os.sep, "/")
        for d, _dirs, files in os.walk(top)
        if "qmldir" in files
    }


def owner(rel: str, modules: set[str]) -> str | None:
    """The QML module a path in the qml folder belongs to: the deepest module folder it is in."""
    parts = rel.split("/")
    for n in range(len(parts), 0, -1):
        if "/".join(parts[:n]) in modules:
            return "/".join(parts[:n])
    return None


def plan(root: str, platform: str, allowed: Allowed) -> Plan:
    """What trimming the PySide6 folder at `root` for `platform` removes and keeps."""
    layout = LAYOUTS[platform]
    modules, plugins = allowed.names("module"), allowed.names("plugin")
    qmls, keeps = allowed.names("qml"), allowed.names("keep")
    present = qml_modules(root, layout)
    used: set[tuple[str, str]] = set()
    out = Plan()

    def decide(rel: str, is_dir: bool) -> str:
        """keep, remove, or look inside (a folder whose parts are decided one by one)."""
        for k in keeps:
            if matches(k, rel):
                used.add(("keep", k))
                return "keep"
        name = rel.rsplit("/", 1)[-1]
        if rel in {"Qt", layout.lib, layout.plugins, layout.qml} - {""}:
            return "inside"
        in_lib = _under(rel, layout.lib)
        if in_lib is not None and "/" not in in_lib:
            m = QT_LIBRARY[platform].match(name)
            if m:
                used.add(("module", m.group(1)))
                return "keep" if m.group(1) in modules else "remove"
        m = BINDING.match(name)
        if m and "/" not in rel:
            used.add(("module", m.group(1)))
            return "keep" if m.group(1) in modules else "remove"
        in_plugins = _under(rel, layout.plugins)
        if in_plugins is not None:
            if is_dir and "/" not in in_plugins:
                return "inside"
            if in_plugins.count("/") != 1:  # beside the plugins' folders, or deeper
                return "remove"
            plugin = in_plugins.split("/")[0] + "/" + plugin_name(name)
            used.add(("plugin", plugin))
            return "keep" if plugin in plugins else "remove"
        in_qml = _under(rel, layout.qml)
        if in_qml is not None:
            if is_dir:
                return "inside"
            module = owner(in_qml, present)
            if module is None:
                return "keep" if "/" not in in_qml else "remove"
            used.add(("qml", module))
            return "keep" if module in qmls else "remove"
        return "remove"

    def walk(rel: str) -> None:
        path = os.path.join(root, rel) if rel else root
        for name in sorted(os.listdir(path)):
            r = f"{rel}/{name}" if rel else name
            full = os.path.join(root, r)
            is_dir = os.path.isdir(full) and not os.path.islink(full)
            what = decide(r, is_dir)
            if what == "inside":
                walk(r)
            elif what == "remove":
                out.remove.append(r)
            elif is_dir:
                out.kept += [
                    os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/")
                    for d, _dirs, files in os.walk(full)
                    for f in files
                ]
            else:
                out.kept.append(r)

    walk("")
    for line in allowed.lines:
        if (line.kind, line.name) not in used:
            out.unused.append(line)
    out.faults += qml_faults(root, layout, present, qmls)
    return out


# --- the checks
# -----------------------------------------------------------------------------------------


IMPORT = re.compile(r"^\s*(optional\s+)?(?:default\s+)?(import|depends)\s+([\w.]+)", re.M)


def qml_needs(qmldir: str) -> list[str]:
    """The modules a qmldir's text imports or depends on, but optional ones, as folders."""
    return [m.group(3).replace(".", "/") for m in IMPORT.finditer(qmldir) if not m.group(1)]


def qml_faults(root: str, layout: Layout, present: set[str], qmls: set[str]) -> list[str]:
    """A kept QML module that needs one the list leaves out (one Qt doesn't carry, as `QML`, is
    built in)."""
    faults = []
    for module in sorted(qmls & present):
        with open(os.path.join(root, layout.qml, module, "qmldir"), encoding="utf-8") as f:
            text = f.read()
        for need in qml_needs(text):
            if need in present and need not in qmls:
                faults.append(f"the QML module {module} needs {need}, which the list leaves out")
    return faults


def elf_needed(path: str) -> list[str] | None:
    """The DT_NEEDED sonames of an ELF file, or None when it isn't one (64-bit, little-endian: the
    Linux build's)."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
            if len(head) < 64 or head[:4] != b"\x7fELF" or head[4] != 2 or head[5] != 1:
                return None
            shoff = struct.unpack_from("<Q", head, 0x28)[0]
            shentsize, shnum = struct.unpack_from("<HH", head, 0x3A)

            def section(i: int) -> tuple[int, ...]:
                f.seek(shoff + i * shentsize)
                return struct.unpack("<IIQQQQIIQQ", f.read(64))

            for i in range(shnum):
                s = section(i)
                if s[1] != 6:  # SHT_DYNAMIC
                    continue
                strings = section(s[6])[4]
                f.seek(s[4])
                dynamic = f.read(s[5])
                out = []
                for at in range(0, len(dynamic) - 15, 16):
                    tag, value = struct.unpack_from("<qQ", dynamic, at)
                    if tag == 0:
                        break
                    if tag == 1:  # DT_NEEDED
                        f.seek(strings + value)
                        out.append(f.read(256).split(b"\0")[0].decode())
                return out
            return []
    except (OSError, struct.error, UnicodeDecodeError):
        return None


def link_faults(root: str, p: Plan) -> list[str]:
    """A kept library that links one only a removed file provided."""
    gone: set[str] = set()
    for rel in p.remove:
        full = os.path.join(root, rel)
        if os.path.isdir(full) and not os.path.islink(full):
            gone.update(f for _d, _dirs, files in os.walk(full) for f in files)
        else:
            gone.add(os.path.basename(rel))
    still = {os.path.basename(rel) for rel in p.kept}
    faults = []
    for rel in p.kept:
        for need in elf_needed(os.path.join(root, rel)) or []:
            if need in gone and need not in still:
                faults.append(f"{rel} links {need}, which the list leaves out")
    return faults


# --- apply
# ----------------------------------------------------------------------------------------------


def apply(root: str, platform: str, text: str, dry_run: bool = False) -> int:
    """Trims the PySide6 folder at `root`; 1, removing nothing, on a fault."""
    try:
        allowed = parse(text, platform)
    except ValueError as e:
        print(f"packaging/qt-modules.txt: {e}", file=sys.stderr)
        return 1
    p = plan(root, platform, allowed)
    p.faults += link_faults(root, p)
    for line in p.unused:
        p.faults.append(f"line {line.number}, {line.kind} {line.name}, names nothing in {root}")
    for fault in p.faults:
        print(f"packaging/qt-modules.txt: {fault}", file=sys.stderr)
    if p.faults:
        return 1
    size = count = 0
    for rel in p.remove:
        full = os.path.join(root, rel)
        if os.path.isdir(full) and not os.path.islink(full):
            for d, _dirs, files in os.walk(full):
                count += len(files)
                size += sum(os.lstat(os.path.join(d, f)).st_size for f in files)
            if not dry_run:
                shutil.rmtree(full)
        else:
            count += 1
            size += os.lstat(full).st_size
            if not dry_run:
                os.remove(full)
        if dry_run:
            print(f"  {rel}")
    if not dry_run:
        for d, _dirs, _files in os.walk(root, topdown=False):  # folders left empty
            if d != root and not os.listdir(d):
                os.rmdir(d)
    what = "would leave out" if dry_run else "left out"
    print(
        f"qt_trim: {what} {count} files, {size / 1e6:.1f} MB of {root} (packaging/qt-modules.txt)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["apply"])
    ap.add_argument("platform", choices=PLATFORMS)
    ap.add_argument("folder", help="the installed PySide6 package's folder")
    ap.add_argument("--dry-run", action="store_true", help="say what it would remove")
    ap.add_argument("--list", default=LIST, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    with open(a.list, encoding="utf-8") as f:
        text = f.read()
    return apply(a.folder, a.platform, text, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
