#!/usr/bin/env python3
"""MusiKata's icon for each build: the sidebar's tile (src/musikata/qml/Sidebar.qml, R6.3), a
rounded square in the accent's gradient with a waveform's bars, drawn at each size it is shown.

    scripts/app_icon.py png OUT.png [SIZE]     the AppImage's (256 by default)
    scripts/app_icon.py ico OUT.ico            the Windows build's: 16 to 256 pixels
    scripts/app_icon.py icns OUT.icns          the macOS bundle's: 16 to 1024 pixels

It draws with Qt (QtGui, which every build carries) and writes the ICO and ICNS containers
itself, each image in them a PNG, which both take, so no image tool is needed.
"""

from __future__ import annotations

import struct
import sys

# the sidebar's tile: 30 pixels square, radius 9, its gradient and its bars' heights
TILE, RADIUS = 30.0, 9.0
STOPS = ((0.0, "#22d3ee"), (0.55, "#a78bfa"), (1.0, "#f472b6"))  # Theme.cyan, accent, pink
BARS = (6, 12, 17, 10, 14, 7)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# the ICNS types that hold a PNG, by size (Apple's icns format)
ICNS_TYPES = ((b"icp4", 16), (b"icp5", 32), (b"icp6", 64), (b"ic07", 128), (b"ic08", 256),
              (b"ic09", 512), (b"ic10", 1024))  # fmt: skip


def png(size: int) -> bytes:
    """The icon, `size` pixels square, as a PNG."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter

    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / TILE, size / TILE)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(TILE, 0))
    for at, colour in STOPS:
        gradient.setColorAt(at, QColor(colour))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(QRectF(0, 0, TILE, TILE), RADIUS, RADIUS)
    p.setBrush(QColor("#ffffff"))
    for i, height in enumerate(BARS):
        p.drawRoundedRect(QRectF(5.5 + i * 3.6, 15 - height / 2, 2, height), 1, 1)
    p.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def ico(images: dict[int, bytes]) -> bytes:
    """An ICO holding each (size: PNG) image."""
    head = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(images)
    for size, data in sorted(images.items()):
        side = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return head + entries + blobs


def icns(images: dict[bytes, bytes]) -> bytes:
    """An ICNS holding each (type: PNG) image."""
    body = b"".join(kind + struct.pack(">I", 8 + len(data)) + data for kind, data in images.items())
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("png", "ico", "icns"):
        print(__doc__, file=sys.stderr)
        return 2
    kind, out = argv[0], argv[1]
    if kind == "png":
        data = png(int(argv[2]) if len(argv) > 2 else 256)
    elif kind == "ico":
        data = ico({s: png(s) for s in ICO_SIZES})
    else:
        data = icns({t: png(s) for t, s in ICNS_TYPES})
    with open(out, "wb") as f:
        f.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
