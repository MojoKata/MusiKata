"""Trimming Qt (scripts/qt_trim.py, packaging/qt-modules.txt; A6.2): what each build keeps of the
PySide6 it installed, and the checks that stop a build before it removes a part it needs.

Why: Qt loads most of what it uses only when first used, a QML module when a screen imports it and
a plugin when a session wants it, so a part removed by mistake fails there and nowhere else. The
build catches a kept part that links or imports a removed one, and a line that names nothing any
more; these tests hold the working of both, and catch the commonest case before any build: a module
the code or the QML imports that the list leaves out."""

import os
import re
import struct
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import qt_trim  # noqa: E402

with open(qt_trim.LIST, encoding="utf-8") as _f:
    LIST = _f.read()


def tree(base, files):
    """Files in base, each holding its own name (a dict's value, when given, instead)."""
    for rel in files:
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        content = files[rel] if isinstance(files, dict) else rel
        p.write_bytes(content if isinstance(content, bytes) else content.encode())
    return str(base)


def elf(needed):
    """A 64-bit ELF file whose dynamic section links `needed`: the header, a string table, the
    dynamic section, and their two section headers."""
    strings = b"\0" + b"".join(n.encode() + b"\0" for n in needed)
    offsets, at = [], 1
    for n in needed:
        offsets.append(at)
        at += len(n) + 1
    dynamic = b"".join(struct.pack("<qQ", 1, o) for o in offsets) + struct.pack("<qQ", 0, 0)
    str_off, dyn_off = 64, 64 + len(strings)
    sh_off = dyn_off + len(dynamic)
    head = bytearray(64)
    head[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", head, 0x28, sh_off)
    struct.pack_into("<HH", head, 0x3A, 64, 2)
    strtab = struct.pack("<IIQQQQIIQQ", 0, 3, 0, 0, str_off, len(strings), 0, 0, 1, 0)
    dynsec = struct.pack("<IIQQQQIIQQ", 0, 6, 0, 0, dyn_off, len(dynamic), 0, 0, 8, 16)
    return bytes(head) + strings + dynamic + strtab + dynsec


ALLOW = """
module Core
module Quick
plugin platforms/qxcb linux
plugin platforms/qwindows windows
qml QtQuick
qml QtQml   # what QtQuick imports
keep __init__.py
keep Qt/lib/libicu*  linux
"""


# ---------- the list ----------


def test_a_line_is_for_the_platforms_it_names_or_all_of_them():
    linux = qt_trim.parse(ALLOW, "linux")
    assert linux.names("module") == {"Core", "Quick"}
    assert linux.names("plugin") == {"platforms/qxcb"}
    assert linux.names("keep") == {"__init__.py", "Qt/lib/libicu*"}
    assert qt_trim.parse(ALLOW, "windows").names("plugin") == {"platforms/qwindows"}
    assert qt_trim.parse(ALLOW, "macos").names("plugin") == set()
    assert [line.number for line in linux.lines][:2] == [2, 3]


@pytest.mark.parametrize("bad", ["module", "lib Core", "module Core beos", "plugin x linux mac"])
def test_a_line_it_cant_read_is_named(bad):
    with pytest.raises(ValueError, match=f"line 2: {re.escape(repr(bad))}"):
        qt_trim.parse(f"# first\n{bad}\n", "linux")


def test_a_plugin_is_named_without_lib_and_its_extension():
    names = ["libqxcb.so", "qwindows.dll", "libqcocoa.dylib", "libqt-plugin-wayland-egl.so"]
    assert [qt_trim.plugin_name(n) for n in names] == [
        "qxcb",
        "qwindows",
        "qcocoa",
        "qt-plugin-wayland-egl",
    ]


def test_a_keep_pattern_names_a_path_or_a_folder_it_is_in_and_a_star_stays_within_a_part():
    assert qt_trim.matches("support", "support/deprecated.py")
    assert qt_trim.matches("Qt/lib/libicu*", "Qt/lib/libicuuc.so.73")
    assert not qt_trim.matches("Qt/lib/libicu*", "Qt/lib/x/libicuuc.so.73")
    assert not qt_trim.matches("*.dll", "plugins/x.dll")
    assert not qt_trim.matches("support/x", "support")


# ---------- what it keeps, per platform ----------

LINUX = {
    "__init__.py": "",
    "QtCore.abi3.so": "",
    "QtCore.pyi": "",
    "QtSql.abi3.so": "",
    "designer": "",
    "include/pyside.h": "",
    "Qt/lib/libQt6Core.so.6": "",
    "Qt/lib/libQt6Quick.so.6": "",
    "Qt/lib/libQt6Sql.so.6": "",
    "Qt/lib/libicuuc.so.73": "",
    "Qt/lib/libavcodec.so.63": "",
    "Qt/plugins/platforms/libqxcb.so": "",
    "Qt/plugins/platforms/libqvnc.so": "",
    "Qt/plugins/sqldrivers/libqsqlite.so": "",
    "Qt/plugins/stray.so": "",
    "Qt/qml/builtins.qmltypes": "",
    "Qt/qml/QtQml/qmldir": "module QtQml\nimport QML 1.0\n",
    "Qt/qml/QtQuick/qmldir": "module QtQuick\nimport QtQml auto\n",
    "Qt/qml/QtQuick/plugins.qmltypes": "",
    "Qt/qml/QtQuick/designer/x.metainfo": "",
    "Qt/qml/QtQuick/Particles/qmldir": "module QtQuick.Particles\n",
    "Qt/qml/QtQuick/Particles/x.qml": "",
    "Qt/qml/Qt/labs/settings/qmldir": "module Qt.labs.settings\n",
}


def test_linux_keeps_the_modules_plugins_qml_and_files_listed(tmp_path):
    root = tree(tmp_path, LINUX)
    p = qt_trim.plan(root, "linux", qt_trim.parse(ALLOW, "linux"))
    assert set(p.remove) == {
        "QtCore.pyi",
        "QtSql.abi3.so",
        "designer",
        "include",
        "Qt/lib/libQt6Sql.so.6",
        "Qt/lib/libavcodec.so.63",
        "Qt/plugins/platforms/libqvnc.so",
        "Qt/plugins/sqldrivers/libqsqlite.so",
        "Qt/plugins/stray.so",
        "Qt/qml/QtQuick/Particles/qmldir",
        "Qt/qml/QtQuick/Particles/x.qml",
        "Qt/qml/Qt/labs/settings/qmldir",
    }
    assert "Qt/qml/QtQuick/designer/x.metainfo" in p.kept  # QtQuick's, not a module of its own
    assert "Qt/qml/builtins.qmltypes" in p.kept and "Qt/lib/libicuuc.so.73" in p.kept
    assert p.unused == [] and p.faults == []


def test_windows_finds_qt_beside_the_bindings_and_macos_in_frameworks(tmp_path):
    win = tree(tmp_path / "w", ["Qt6Core.dll", "Qt6Sql.dll", "QtCore.pyd", "QtSql.pyd",
                                "avcodec-63.dll", "plugins/platforms/qwindows.dll",
                                "plugins/platforms/qdirect2d.dll"])  # fmt: skip
    p = qt_trim.plan(win, "windows", qt_trim.parse("module Core\nplugin platforms/qwindows", "w"))
    assert set(p.remove) == {"Qt6Sql.dll", "QtSql.pyd", "avcodec-63.dll",
                             "plugins/platforms/qdirect2d.dll"}  # fmt: skip
    mac = tree(tmp_path / "m", ["Qt/lib/QtCore.framework/Versions/A/QtCore",
                                "Qt/lib/QtSql.framework/Versions/A/QtSql", "QtCore.abi3.so",
                                "Qt/lib/cmake/x"])  # fmt: skip
    p = qt_trim.plan(mac, "macos", qt_trim.parse("module Core", "macos"))
    assert set(p.remove) == {"Qt/lib/QtSql.framework", "Qt/lib/cmake"}
    assert "Qt/lib/QtCore.framework/Versions/A/QtCore" in p.kept


# ---------- the checks ----------


def test_a_line_that_names_nothing_is_reported(tmp_path):
    root = tree(tmp_path, {"Qt/lib/libQt6Core.so.6": ""})
    p = qt_trim.plan(root, "linux", qt_trim.parse("module Core\nmodule Gone\nqml QtGone", "linux"))
    assert [(line.kind, line.name) for line in p.unused] == [("module", "Gone"), ("qml", "QtGone")]


def test_a_kept_qml_module_needing_one_left_out_is_a_fault(tmp_path):
    root = tree(tmp_path, {k: v for k, v in LINUX.items() if "qml" in k})
    p = qt_trim.plan(root, "linux", qt_trim.parse("qml QtQuick", "linux"))
    assert p.faults == ["the QML module QtQuick needs QtQml, which the list leaves out"]


def test_a_qmldirs_needs_are_its_imports_and_depends_but_optional_ones():
    text = (
        "module QtQuick.Controls\noptional import QtQuick.Controls.Fusion auto\n"
        "default import QtQuick.Controls.Basic auto\ndepends QtQuick auto\nimport QML 1.0\n"
    )
    assert qt_trim.qml_needs(text) == ["QtQuick/Controls/Basic", "QtQuick", "QML"]


def test_the_links_of_an_elf_library_are_read_and_anything_else_has_none(tmp_path):
    lib = tmp_path / "libQt6Quick.so.6"
    lib.write_bytes(elf(["libQt6Qml.so.6", "libc.so.6"]))
    assert qt_trim.elf_needed(str(lib)) == ["libQt6Qml.so.6", "libc.so.6"]
    lib.write_bytes(elf([]))
    assert qt_trim.elf_needed(str(lib)) == []
    (tmp_path / "x.dll").write_bytes(b"MZ" + bytes(100))
    assert qt_trim.elf_needed(str(tmp_path / "x.dll")) is None
    assert qt_trim.elf_needed(str(tmp_path / "missing")) is None


def test_a_kept_library_linking_one_left_out_is_a_fault_unless_another_copy_stays(tmp_path):
    root = tree(tmp_path, {
        "Qt/lib/libQt6Quick.so.6": elf(["libQt6Sql.so.6"]),
        "Qt/lib/libQt6Sql.so.6": elf([]),
        "Qt/plugins/sqldrivers/libqsqlite.so": elf(["libQt6Sql.so.6"]),
    })  # fmt: skip
    p = qt_trim.plan(root, "linux", qt_trim.parse("module Quick", "linux"))
    assert qt_trim.link_faults(root, p) == [
        "Qt/lib/libQt6Quick.so.6 links libQt6Sql.so.6, which the list leaves out"
    ]
    p = qt_trim.plan(root, "linux", qt_trim.parse("module Quick\nmodule Sql", "linux"))
    assert qt_trim.link_faults(root, p) == []


# ---------- apply ----------


def test_apply_removes_what_isnt_listed_and_the_folders_left_empty(tmp_path, capsys):
    root = tree(tmp_path, LINUX)
    assert qt_trim.apply(root, "linux", ALLOW, dry_run=True) == 0
    assert os.path.exists(os.path.join(root, "QtSql.abi3.so"))
    assert "  QtSql.abi3.so" in capsys.readouterr().out
    assert qt_trim.apply(root, "linux", ALLOW) == 0
    assert "left out 12 files" in capsys.readouterr().out
    assert not os.path.exists(os.path.join(root, "QtSql.abi3.so"))
    assert not os.path.exists(os.path.join(root, "Qt", "plugins", "sqldrivers"))
    assert not os.path.exists(os.path.join(root, "Qt", "qml", "Qt"))
    assert os.path.exists(os.path.join(root, "Qt", "qml", "QtQuick", "designer", "x.metainfo"))


@pytest.mark.parametrize(
    "allow, says",
    [
        ("module Core\nmodule Gone", "line 2, module Gone, names nothing"),
        ("qml QtQuick", "QtQuick needs QtQml"),
        ("mod Core", "line 1: 'mod Core' isn't KIND NAME"),
    ],
)
def test_apply_removes_nothing_on_a_fault_and_says_it(tmp_path, capsys, allow, says):
    root = tree(tmp_path, LINUX)
    assert qt_trim.apply(root, "linux", allow) == 1
    assert says in capsys.readouterr().err
    assert os.path.exists(os.path.join(root, "QtSql.abi3.so"))


def test_the_command_line_applies_the_list_it_is_given(tmp_path, capsys):
    root = tree(tmp_path / "PySide6", LINUX)
    (tmp_path / "list.txt").write_text(ALLOW)
    assert qt_trim.main(["apply", "linux", root, "--list", str(tmp_path / "list.txt")]) == 0
    assert "left out 12 files" in capsys.readouterr().out


# ---------- packaging/qt-modules.txt ----------


def _imports(pattern, paths):
    out = set()
    for path in paths:
        with open(path, encoding="utf-8") as f:
            out |= set(re.findall(pattern, f.read(), re.M))
    return out


def test_the_list_keeps_every_module_the_code_and_the_views_import_on_every_platform():
    src = os.path.join(ROOT, "src")
    py = [os.path.join(d, f) for d, _, fs in os.walk(src) for f in fs if f.endswith(".py")]
    qml_dir = os.path.join(src, "musikata", "qml")
    qml = [os.path.join(qml_dir, f) for f in os.listdir(qml_dir) if f.endswith(".qml")]
    # a backend of the system's media controls is imported only on its platform (A4.5)
    only = {os.path.join(src, "musikata", "media", "mpris.py"): "linux"}
    views = {m.replace(".", "/") for m in _imports(r"^import (Qt[\w.]+)", qml)}
    for platform in qt_trim.PLATFORMS:
        here = [f for f in py if only.get(f, platform) == platform]
        bindings = _imports(r"from PySide6\.Qt(\w+) import", here)
        assert bindings >= {"Core", "Gui", "Qml", "Quick", "Multimedia"}
        allowed = qt_trim.parse(LIST, platform)
        assert bindings <= allowed.names("module"), platform
        assert views <= allowed.names("qml"), platform
    assert "DBus" in qt_trim.parse(LIST, "linux").names("module")  # MPRIS


def test_the_list_leaves_out_qt_multimedias_ffmpeg():
    """PyAV carries the FFmpeg that decodes (A4.1, A6.2)."""
    for platform in qt_trim.PLATFORMS:
        allowed = qt_trim.parse(LIST, platform)
        assert not any("ffmpeg" in n.lower() for n in allowed.names("plugin")), platform
        assert not any(re.search(r"av(codec|format|util)", n) for n in allowed.names("keep"))


def test_the_list_fits_the_pyside6_the_tests_run_on():
    """Each line for this platform names something in the pinned PySide6, and nothing kept needs a
    part left out: what the build's trim checks, before any build (the folder isn't changed)."""
    import PySide6

    platform = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    folder = os.path.dirname(PySide6.__file__)
    p = qt_trim.plan(folder, platform, qt_trim.parse(LIST, platform))
    assert p.unused == [] and p.faults == []
    assert qt_trim.link_faults(folder, p) == []
    ffmpeg = qt_trim.LAYOUTS[platform].plugins + "/multimedia/"
    assert any(r.startswith(ffmpeg) for r in p.remove)
