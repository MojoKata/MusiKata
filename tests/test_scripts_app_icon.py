"""MusiKata's icon for each build (scripts/app_icon.py): the sidebar's tile, drawn at each size,
and the ICO and ICNS containers written around PNGs.

Why: Windows and macOS read an icon file's directory to choose a size; one that points past its
data, or names a size it doesn't hold, shows a blank icon or none, in Explorer, the Start menu or
the Dock, where no test of the app looks."""

import os
import struct
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import app_icon  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n"


def test_the_icon_is_a_png_of_the_size_asked_with_the_tile_and_its_corners_clear():
    from PySide6.QtGui import QImage

    data = app_icon.png(64)
    assert data.startswith(PNG)
    image = QImage.fromData(data)
    assert (image.width(), image.height()) == (64, 64)
    assert image.pixelColor(0, 0).alpha() == 0  # the rounded corner
    assert image.pixelColor(2, 32).alpha() == 255  # the tile's left edge
    assert image.pixelColor(29, 32).name() == "#ffffff"  # the tallest bar


def test_an_ico_lists_each_image_where_it_is_with_256_as_0():
    images = {16: PNG + b"a", 256: PNG + b"bbb"}
    data = app_icon.ico(images)
    assert struct.unpack_from("<HHH", data) == (0, 1, 2)
    entries = [struct.unpack_from("<BBBBHHII", data, 6 + 16 * i) for i in range(2)]
    assert [(e[0], e[1]) for e in entries] == [(16, 16), (0, 0)]
    for (*_, size, at), want in zip(entries, images.values(), strict=True):
        assert data[at : at + size] == want


def test_an_icns_holds_each_typed_image_with_its_length():
    data = app_icon.icns({b"ic07": PNG + b"x", b"icp4": PNG})
    assert data[:4] == b"icns" and struct.unpack_from(">I", data, 4)[0] == len(data)
    assert data[8:12] == b"ic07" and struct.unpack_from(">I", data, 12)[0] == 8 + len(PNG) + 1
    assert data[16 : 16 + len(PNG) + 1] == PNG + b"x"
    assert data[25:29] == b"icp4"


@pytest.mark.parametrize("kind, head", [("png", PNG), ("ico", b"\0\0\1\0"), ("icns", b"icns")])
def test_the_command_line_writes_each_kind(tmp_path, kind, head):
    out = tmp_path / f"musikata.{kind}"
    assert app_icon.main([kind, str(out), "32"][: 3 if kind == "png" else 2]) == 0
    assert out.read_bytes().startswith(head)


def test_the_command_line_says_how_when_asked_wrongly(capsys):
    assert app_icon.main(["svg", "x.svg"]) == 2
    assert "app_icon.py png OUT.png" in capsys.readouterr().err
