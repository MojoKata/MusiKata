"""The license files every build carries (scripts/third_party_notices.py, A6.6): LICENSE.txt, and
THIRD-PARTY-NOTICES.txt made from the Python and the packages a build installed.

Why: the notices are made from what is installed, so they can't fall behind a pin; that holds only
while every package versions.env pins for running MusiKata is in them, at its pinned version, with
its license's text, and a package whose wheel lacks that text (PySide6) gets it from
packaging/licenses/."""

import importlib.metadata as md
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import third_party_notices as tpn  # noqa: E402

ENV = """
: "${PYSIDE:=6.12.0}"
RUNTIME="mutagen==1.48.1 av==19.0.2"   # what runs
PYINSTALLER="pyinstaller==6.22.3 altgraph==0.17.5"
MEDIA_WINDOWS="winrt-runtime==4.1.0 winrt-Windows.Media==4!10.0.28000.2957"
MEDIA_MACOS="pyobjc-core==13.0 pyobjc-framework-MediaPlayer==13.0"
"""


def dist(tmp_path, name, version, files, meta=""):
    """A package's .dist-info in tmp_path, with `files` (relative to it: text) and RECORD."""
    info = tmp_path / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n{meta}"
    )
    record = [f"{info.name}/METADATA,,"]
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        record.append(f"{rel},,")
    (info / "RECORD").write_text("\n".join(record) + "\n")
    return md.PathDistribution(info)


def test_the_packages_carried_are_pysides_runtimes_and_pyinstaller_when_frozen():
    assert tpn.carried(ENV, on="linux") == {
        "pyside6-essentials": "6.12.0",
        "pyside6-addons": "6.12.0",
        "shiboken6": "6.12.0",
        "mutagen": "1.48.1",
        "av": "19.0.2",
    }
    assert tpn.carried(ENV, frozen=True)["pyinstaller"] == "6.22.3"
    assert "altgraph" not in tpn.carried(ENV, frozen=True)  # it builds, isn't carried
    assert tpn.assigned(ENV, "MISSING") == ""


def test_windows_and_macos_carry_their_media_controls_and_linux_none():
    """A4.5: PyWinRT on Windows, PyObjC on macOS; MPRIS is PySide6's own QtDBus."""
    assert tpn.carried(ENV, on="win32") == {
        **tpn.carried(ENV, on="linux"),
        "winrt-runtime": "4.1.0", "winrt-windows.media": "4!10.0.28000.2957",
    }  # fmt: skip
    assert tpn.carried(ENV, on="darwin") == {
        **tpn.carried(ENV, on="linux"),
        "pyobjc-core": "13.0", "pyobjc-framework-mediaplayer": "13.0",
    }  # fmt: skip


def test_pyobjc_without_its_license_in_its_wheel_gets_the_mit_text(tmp_path):
    d = dist(tmp_path, "pyobjc-framework-MediaPlayer", "13.0", {}, "License: MIT\n")
    text = tpn.package("pyobjc-framework-mediaplayer", d)
    assert "License: MIT" in text and "--- PyObjC.txt ---" in text
    assert "Permission is hereby granted" in text and "pyobjc (v13.0)" in text


def test_the_libraries_a_wheel_bundles_are_named():
    files = ["av.libs/libx264-1.so.165", "av/_core.so", "PIL/.dylibs/libjpeg.dylib", "a/b.libs/x"]
    assert tpn.bundled(files) == ["libjpeg.dylib", "libx264-1.so.165"]


def test_a_package_gives_its_license_its_home_its_libraries_and_its_license_texts(tmp_path):
    d = dist(tmp_path, "mutagen", "1.48.1", {
        "mutagen-1.48.1.dist-info/licenses/COPYING": "GPL text",
        "mutagen-1.48.1.dist-info/licenses/__pycache__/x.pyc": "",
        "mutagen-1.48.1.dist-info/AUTHORS": "them",
        "mutagen.libs/libz.so.1": "",
    }, "License-Expression: GPL-2.0-or-later\nProject-URL: Issues, https://x/issues\n"
       "Project-URL: Source, https://x/src\n")  # fmt: skip
    text = tpn.package("mutagen", d)
    assert text.startswith(f"{tpn.RULE}\nmutagen 1.48.1\n{tpn.RULE}\n")
    for line in ("License: GPL-2.0-or-later", "Home: https://x/src",
                 "Libraries its wheel bundles: libz.so.1", "--- licenses/COPYING ---\n\nGPL text",
                 "--- AUTHORS ---\n\nthem"):  # fmt: skip
        assert line in text
    assert ".pyc" not in text


def test_pyside_gets_the_lgpl_and_not_the_note_for_commercial_licensees(tmp_path):
    d = dist(tmp_path, "PySide6_Essentials", "6.12.0",
             {"PySide6_Essentials-6.12.0.dist-info/licenses/LicenseRef-Qt-Commercial.txt": "buy"},
             "License: LGPL-3.0-only\nHome-page: https://pyside.org\n")  # fmt: skip
    text = tpn.package("pyside6-essentials", d)
    assert "Qt 6.12.0 and its Python binding" in text and "Home: https://pyside.org" in text
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text and "buy" not in text
    bare = dist(tmp_path / "b", "bare", "1.0", {})
    assert "License: see its license below" in tpn.package("bare", bare)


def test_pyavs_ffmpeg_is_named_with_its_version_and_license():
    text = tpn.ffmpeg()
    import av

    assert (
        text == f"FFmpeg {av.ffmpeg_version_info}, {av._core.library_meta['libavcodec']['license']}"
    )
    assert "GPL" in text


def test_the_notices_hold_python_and_each_package_at_its_pinned_version():
    av = md.version("av")
    text = tpn.notices({"av": av}, [])
    assert "Python " in text and "PYTHON SOFTWARE FOUNDATION LICENSE" in text.upper()
    assert f"av {av}" in text and "FFmpeg" in text
    with pytest.raises(LookupError, match="av is .*, packaging/versions.env pins 0.1"):
        tpn.notices({"av": "0.1"}, [])
    with pytest.raises(LookupError, match="not-a-package isn't installed"):
        tpn.notices({"not-a-package": "1"}, [])


def test_write_puts_both_files_in_the_folder_with_the_extras(tmp_path, capsys, monkeypatch):
    """What the AppImage's build does (here with two of its packages)."""
    pins = {"av": md.version("av"), "numpy": md.version("numpy")}
    monkeypatch.setattr(tpn, "carried", lambda env, frozen=False: pins)
    extra = tmp_path / "xcb.txt"
    extra.write_text("xcb's copyright")
    out = tmp_path / "licenses"
    assert tpn.main(["write", str(out), "--extra", f"xcb-util={extra}"]) == 0
    with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as f:
        assert (out / "LICENSE.txt").read_text(encoding="utf-8") == f.read()
    text = (out / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
    for part in ("av ", "numpy ", "xcb-util"):
        assert part in text
    assert "xcb's copyright" in text and "LICENSE.txt and THIRD-PARTY" in capsys.readouterr().out


def test_write_writes_nothing_when_a_package_is_missing_and_says_which(tmp_path, capsys):
    """PyInstaller, which a frozen build carries, isn't where the tests run."""
    assert tpn.main(["write", str(tmp_path / "out"), "--frozen"]) == 1
    assert "isn't installed" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_an_extra_needs_a_title_and_a_file(tmp_path):
    with pytest.raises(SystemExit):
        tpn.main(["write", str(tmp_path), "--extra", "no-file"])
