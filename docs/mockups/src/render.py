"""Draws the MusiKata design mockups as 256-colour PNGs, dark theme.

    python docs/mockups/src/render.py [name-filter ...]

Needs PySide6 (QPainter, run offscreen) and Pillow (the 256-colour quantizing). Each screen is
drawn at 1280 x 800 and saved at twice its pixels to docs/mockups/<name>.png. The colours are
the design tokens of the requirements' R6.2 (THEME below); the music, artists and albums are
made up, and the album art is drawn from a seed. What each screen shows is in
docs/mockups/README.md.
"""

import io
import math
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)

OUT = Path(__file__).resolve().parents[1]
W, H, SCALE = 1280, 800, 2
SANS, MONO = "Noto Sans", "Noto Sans Mono"

# Design tokens, dark (R6.2). Light is derived later; dark is the design target.
C = {
    "bg": "#0e1014", "side": "#12151b", "surface": "#171a21", "raised": "#1e222b", "hover": "#252a35",
    "sel": "#2a2550", "border": "#232731", "borderStrong": "#323744", "text": "#eceef4", "muted": "#99a0b2",
    "faint": "#838a9d", "accent": "#a78bfa", "accentHi": "#c4b5fd", "accentSoft": "#2b2450",
    "cyan": "#22d3ee", "pink": "#f472b6", "ok": "#34d399", "okSoft": "#123629", "warn": "#fbbf24",
    "warnSoft": "#3a2e12", "err": "#fb7185", "errSoft": "#3d1a22", "star": "#fbbf24", "input": "#0f1217",
    "progress": "#4ade80",
    "scrim": "#05060a", "primaryA": "#6d28d9", "primaryB": "#7c3aed",
}
SIDE_W, BAR_H, PANEL_W, HEAD_H = 232, 88, 344, 64

# ------------------------------------------------------------------ made-up library
ALBUMS = [
    # artist, album, year, genre, seed, tracks
    ("Lumen Drift", "Glass Harbor", 2019, "Electronic", 11, 10),
    ("The Paper Lanterns", "Northbound Static", 2021, "Indie Rock", 23, 12),
    ("Mara Okafor", "Salt & Ember", 2018, "Soul", 37, 11),
    ("Kestrel Union", "Low Orbit", 2022, "Synthwave", 41, 9),
    ("Cedar & Vale", "Quiet Acres", 2017, "Folk", 53, 13),
    ("Orbital Fern", "Spore Theory", 2020, "Ambient", 67, 8),
    ("Juniper Sixes", "Velvet Hours", 2016, "Jazz", 71, 10),
    ("Hollow Coast", "Breakwater", 2023, "Alternative", 83, 11),
    ("Nadia Reyes Trio", "Blue Hour Sessions", 2015, "Jazz", 97, 7),
    ("Static Bloom", "Neon Fieldwork", 2024, "Electronic", 101, 12),
    ("Ironwood Choir", "Hymns for Machines", 2019, "Classical", 113, 14),
    ("Ghost Meridian", "Afterlight", 2021, "Post-Rock", 127, 6),
    ("Lumen Drift", "Tide Tables", 2022, "Electronic", 131, 9),
    ("Saffron Avenue", "Paper Moons", 2014, "Pop", 139, 12),
    ("Mara Okafor", "Kindling", 2015, None, 149, 10),
]
GLASS = ["Tidewater", "Glass Harbor", "Small Hours", "Signal Fires", "Undertow", "Parallax",
         "Lowlight", "Salt in the Wires", "Breakers", "Harbor Lights (Reprise)"]
GLASS_LEN = ["4:02", "5:11", "3:47", "4:18", "6:03", "3:55", "4:40", "5:26", "3:12", "2:58"]
GLASS_RATE = [4, 5, 3, 5, 4, 3, 0, 4, 3, 4]


# ------------------------------------------------------------------ painting helpers
def col(name_or_hex, alpha=None):
    c = QColor(name_or_hex) if isinstance(name_or_hex, QColor) else QColor(C.get(name_or_hex, name_or_hex))
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def font(size, weight=400, mono=False):
    f = QFont(MONO if mono else SANS)
    f.setPixelSize(int(size))
    f.setWeight(QFont.Weight(weight))
    return f


def text(p, x, y, s, size=13, color="text", weight=400, w=2000, h=None, align="left", mono=False):
    """Text in the box (x, y, w, h), centred vertically; returns its drawn width."""
    f = font(size, weight, mono)
    p.setFont(f)
    p.setPen(col(color))
    fm = QFontMetricsF(f)
    s = fm.elidedText(s, Qt.ElideRight, w)
    h = h or size * 1.5
    a = {"left": Qt.AlignLeft, "right": Qt.AlignRight, "center": Qt.AlignHCenter}[align]
    p.drawText(QRectF(x, y, w, h), a | Qt.AlignVCenter, s)
    return fm.horizontalAdvance(s)


def tw(s, size=13, weight=400, mono=False):
    return QFontMetricsF(font(size, weight, mono)).horizontalAdvance(s)


def rect(p, x, y, w, h, r=0, fill=None, stroke=None, sw=1.0, dash=None):
    p.setBrush(QBrush(fill if isinstance(fill, (QColor, QLinearGradient, QRadialGradient)) else col(fill))
               if fill else Qt.NoBrush)
    if stroke:
        pen = QPen(col(stroke) if isinstance(stroke, str) else stroke, sw)
        if dash:
            pen.setDashPattern(dash)
        p.setPen(pen)
    else:
        p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)


def line(p, x1, y1, x2, y2, color="border", w=1.0):
    p.setPen(QPen(col(color), w))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def shadow(p, x, y, w, h, r, depth=18):
    for i in range(depth, 0, -2):
        rect(p, x - i * 0.5, y - i * 0.3 + 6, w + i, h + i, r + i * 0.5, col("#000000", 0.035))


def grad(x1, y1, x2, y2, stops):
    g = QLinearGradient(x1, y1, x2, y2)
    for o, c in stops:
        g.setColorAt(o, col(c) if isinstance(c, str) else c)
    return g


# ------------------------------------------------------------------ icons (stroked, 20-px grid)
def icon(p, name, cx, cy, size=18, color="muted", sw=1.7):
    s = size / 20.0
    pen = QPen(col(color), sw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.save()
    p.translate(cx - 10 * s, cy - 10 * s)
    p.scale(s, s)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    P = QPointF

    def poly(pts, fill=False):
        if fill:
            p.setBrush(col(color))
        p.drawPolygon(QPolygonF([P(a, b) for a, b in pts]))
        p.setBrush(Qt.NoBrush)

    def path(d):
        p.drawPath(d)

    if name == "play":
        p.setPen(Qt.NoPen)
        poly([(6, 3.5), (16.5, 10), (6, 16.5)], True)
    elif name == "pause":
        p.setPen(Qt.NoPen)
        p.setBrush(col(color))
        p.drawRoundedRect(QRectF(5, 3.5, 3.6, 13), 1, 1)
        p.drawRoundedRect(QRectF(11.4, 3.5, 3.6, 13), 1, 1)
    elif name in ("next", "prev"):
        if name == "prev":
            p.translate(20, 0)
            p.scale(-1, 1)
        p.setBrush(col(color))
        p.setPen(Qt.NoPen)
        poly([(4, 4), (13, 10), (4, 16)], True)
        p.drawRoundedRect(QRectF(13.5, 4, 2.6, 12), 1, 1)
    elif name == "shuffle":
        d = QPainterPath(P(3, 6)); d.lineTo(6, 6); d.cubicTo(11, 6, 10, 14, 15, 14); d.lineTo(17, 14); path(d)
        d = QPainterPath(P(3, 14)); d.lineTo(6, 14); d.cubicTo(11, 14, 10, 6, 15, 6); d.lineTo(17, 6); path(d)
        p.drawPolyline(QPolygonF([P(14.5, 3.5), P(17, 6), P(14.5, 8.5)]))
        p.drawPolyline(QPolygonF([P(14.5, 11.5), P(17, 14), P(14.5, 16.5)]))
    elif name == "repeat":
        d = QPainterPath(P(5, 9)); d.lineTo(5, 7.5); d.quadTo(5, 5.5, 7, 5.5); d.lineTo(16, 5.5); path(d)
        d = QPainterPath(P(15, 11)); d.lineTo(15, 12.5); d.quadTo(15, 14.5, 13, 14.5); d.lineTo(4, 14.5); path(d)
        p.drawPolyline(QPolygonF([P(13.5, 3), P(16, 5.5), P(13.5, 8)]))
        p.drawPolyline(QPolygonF([P(6.5, 12), P(4, 14.5), P(6.5, 17)]))
    elif name == "search":
        p.drawEllipse(P(8.8, 8.8), 5.3, 5.3)
        p.drawLine(P(12.8, 12.8), P(16.5, 16.5))
    elif name == "grid":
        for gx, gy in ((3.5, 3.5), (11, 3.5), (3.5, 11), (11, 11)):
            p.drawRoundedRect(QRectF(gx, gy, 5.5, 5.5), 1.4, 1.4)
    elif name == "popout":   # the mini player, in a window of its own (R15)
        p.drawPolyline(QPolygonF([P(9, 4), P(4, 4), P(4, 16), P(16, 16), P(16, 11)]))
        p.drawLine(P(10, 10), P(16.5, 3.5))
        p.drawPolyline(QPolygonF([P(11.5, 3.5), P(16.5, 3.5), P(16.5, 8.5)]))
    elif name == "pin":
        poly([(7, 2.5), (13, 2.5), (12, 8), (15, 11.5), (5, 11.5), (8, 8)])
        p.drawLine(P(10, 11.5), P(10, 17.5))
    elif name == "nowave":
        for i, hh in enumerate((4, 9, 13, 7, 11, 5)):
            xx = 3 + i * 2.8
            p.drawLine(P(xx, 10 - hh / 2), P(xx, 10 + hh / 2))
        p.drawLine(P(3, 17), P(17, 3))
    elif name == "globe":   # online lookups (R16)
        p.drawEllipse(P(10, 10), 7, 7)
        p.drawEllipse(P(10, 10), 3, 7)
        p.drawLine(P(3, 10), P(17, 10))
    elif name == "lyrics":   # a speech bubble with lines (R17)
        d = QPainterPath(P(4.5, 3)); d.lineTo(15.5, 3); d.quadTo(17.5, 3, 17.5, 5); d.lineTo(17.5, 11.5)
        d.quadTo(17.5, 13.5, 15.5, 13.5); d.lineTo(8, 13.5); d.lineTo(4.5, 17); d.lineTo(4.5, 13.5)
        d.quadTo(2.5, 13.5, 2.5, 11.5); d.lineTo(2.5, 5); d.quadTo(2.5, 3, 4.5, 3); path(d)
        p.drawLine(P(6, 6.8), P(14, 6.8)); p.drawLine(P(6, 9.8), P(11.5, 9.8))
    elif name == "eq":   # the equalizer (R19): three sliders
        for xx, yy in ((5, 7), (10, 12.5), (15, 5.5)):
            p.drawLine(P(xx, 3), P(xx, 17))
            p.setBrush(col("bg")); p.drawEllipse(P(xx, yy), 1.9, 1.9); p.setBrush(Qt.NoBrush)
    elif name == "trash":
        p.drawLine(P(3.5, 5.5), P(16.5, 5.5)); p.drawPolyline(QPolygonF([P(8, 5.5), P(8.5, 3), P(11.5, 3), P(12, 5.5)]))
        poly([(5, 5.5), (15, 5.5), (14, 17), (6, 17)])
        p.drawLine(P(8.5, 8.5), P(8.8, 14)); p.drawLine(P(11.5, 8.5), P(11.2, 14))
    elif name == "expand":   # Now Playing, full view (R6.5)
        for ax, ay, dx, dy in ((3.5, 3.5, 1, 1), (16.5, 3.5, -1, 1), (3.5, 16.5, 1, -1), (16.5, 16.5, -1, -1)):
            p.drawPolyline(QPolygonF([P(ax, ay + 4.5 * dy), P(ax, ay), P(ax + 4.5 * dx, ay)]))
    elif name == "large":
        p.drawRoundedRect(QRectF(3.5, 3.5, 13, 13), 2.2, 2.2)
    elif name == "small":
        for gx in (3, 8.2, 13.4):
            for gy in (3, 8.2, 13.4):
                p.drawRoundedRect(QRectF(gx, gy, 3.6, 3.6), 0.9, 0.9)
    elif name == "cards":
        p.drawRoundedRect(QRectF(3, 3.5, 14, 5.5), 1.6, 1.6)
        p.drawRoundedRect(QRectF(3, 11, 14, 5.5), 1.6, 1.6)
    elif name == "list":
        for yy in (5, 10, 15):
            p.drawLine(P(7, yy), P(17, yy))
            p.drawPoint(P(3.5, yy))
    elif name == "album":
        p.drawEllipse(P(10, 10), 7, 7)
        p.drawEllipse(P(10, 10), 2, 2)
    elif name == "artist":
        p.drawEllipse(P(10, 7), 3.4, 3.4)
        d = QPainterPath(P(3.8, 17)); d.cubicTo(4.5, 11.5, 15.5, 11.5, 16.2, 17); path(d)
    elif name == "song":
        p.drawLine(P(8, 14.5), P(8, 3.5)); p.drawLine(P(8, 3.5), P(15, 2.5)); p.drawLine(P(15, 2.5), P(15, 12.5))
        p.setBrush(col(color)); p.drawEllipse(P(5.8, 14.8), 2.4, 2); p.drawEllipse(P(12.8, 12.8), 2.4, 2)
    elif name == "genre":
        poly([(3, 3), (10.5, 3), (17, 9.5), (9.5, 17), (3, 10.5)])
        p.drawEllipse(P(7, 7), 1.2, 1.2)
    elif name == "folder":
        d = QPainterPath(P(2.5, 6)); d.lineTo(2.5, 15.5); d.lineTo(17.5, 15.5); d.lineTo(17.5, 7); d.lineTo(9.5, 7)
        d.lineTo(8, 4.5); d.lineTo(3.5, 4.5); d.closeSubpath(); path(d)
    elif name == "playlist":
        for yy, x2 in ((4.5, 15), (9, 15), (13.5, 9)):
            p.drawLine(P(3, yy), P(x2, yy))
        p.drawLine(P(14.5, 16), P(14.5, 10)); p.drawLine(P(14.5, 10), P(17.5, 11))
        p.setBrush(col(color)); p.drawEllipse(P(13, 16), 1.8, 1.5)
    elif name == "attention":
        poly([(10, 2.8), (17.8, 16.5), (2.2, 16.5)])
        p.drawLine(P(10, 7.5), P(10, 11.5)); p.drawPoint(P(10, 14))
    elif name == "plus":
        p.drawLine(P(10, 4), P(10, 16)); p.drawLine(P(4, 10), P(16, 10))
    elif name == "close":
        p.drawLine(P(5, 5), P(15, 15)); p.drawLine(P(15, 5), P(5, 15))
    elif name == "min":
        p.drawLine(P(5, 10), P(15, 10))
    elif name == "max":
        p.drawRoundedRect(QRectF(5, 5, 10, 10), 1.5, 1.5)
    elif name == "check":
        p.drawPolyline(QPolygonF([P(4, 10.5), P(8, 14.5), P(16, 5.5)]))
    elif name == "chev_down":
        p.drawPolyline(QPolygonF([P(5.5, 8), P(10, 12.5), P(14.5, 8)]))
    elif name == "chev_right":
        p.drawPolyline(QPolygonF([P(8, 5.5), P(12.5, 10), P(8, 14.5)]))
    elif name == "more":
        p.setBrush(col(color)); p.setPen(Qt.NoPen)
        for yy in (4.5, 10, 15.5):
            p.drawEllipse(P(10, yy), 1.6, 1.6)
    elif name == "volume":
        poly([(3, 7.5), (6.5, 7.5), (10.5, 4), (10.5, 16), (6.5, 12.5), (3, 12.5)])
        d = QPainterPath(P(13.5, 7)); d.quadTo(15.5, 10, 13.5, 13); path(d)
        d = QPainterPath(P(15.8, 4.8)); d.quadTo(19.5, 10, 15.8, 15.2); path(d)
    elif name == "wave":
        for i, hh in enumerate((4, 9, 13, 7, 11, 5)):
            xx = 3 + i * 2.8
            p.drawLine(P(xx, 10 - hh / 2), P(xx, 10 + hh / 2))
    elif name == "cube":
        poly([(10, 2.5), (17, 6.3), (17, 13.7), (10, 17.5), (3, 13.7), (3, 6.3)])
        p.drawPolyline(QPolygonF([P(3, 6.3), P(10, 10), P(17, 6.3)])); p.drawLine(P(10, 10), P(10, 17.5))
    elif name == "queue":
        for yy in (4.5, 9):
            p.drawLine(P(3, yy), P(17, yy))
        p.drawLine(P(3, 13.5), P(10, 13.5))
        p.setBrush(col(color)); p.setPen(Qt.NoPen)
        poly([(13, 11.5), (17.5, 14.5), (13, 17.5)], True)
    elif name == "gear":
        p.drawEllipse(P(10, 10), 2.6, 2.6)
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(P(10 + 5 * math.cos(a), 10 + 5 * math.sin(a)), P(10 + 7.2 * math.cos(a), 10 + 7.2 * math.sin(a)))
        p.drawEllipse(P(10, 10), 5.2, 5.2)
    elif name == "image":
        p.drawRoundedRect(QRectF(2.5, 3.5, 15, 13), 2, 2)
        p.drawPolyline(QPolygonF([P(3, 14.5), P(8, 9.5), P(11.5, 13), P(13.5, 11), P(17, 14.5)]))
        p.drawEllipse(P(13, 7.5), 1.4, 1.4)
    elif name == "drag":
        p.setBrush(col(color)); p.setPen(Qt.NoPen)
        for xx in (7.5, 12.5):
            for yy in (5, 10, 15):
                p.drawEllipse(P(xx, yy), 1.3, 1.3)
    elif name == "wand":
        p.drawLine(P(3.5, 16.5), P(12.5, 7.5))
        for a, b, c2, d2 in ((15, 2.5, 15, 6.5), (13, 4.5, 17, 4.5), (6, 3, 6, 5.5), (4.75, 4.25, 7.25, 4.25),
                             (16, 11, 16, 13.5), (14.75, 12.25, 17.25, 12.25)):
            p.drawLine(P(a, b), P(c2, d2))
    elif name == "undo":
        d = QPainterPath(P(5, 8)); d.lineTo(12.5, 8); d.cubicTo(17.5, 8, 17.5, 16, 12.5, 16); d.lineTo(8, 16); path(d)
        p.drawPolyline(QPolygonF([P(8, 4.8), P(4.8, 8), P(8, 11.2)]))
    elif name == "file":
        poly([(5, 2.5), (11.5, 2.5), (15.5, 6.5), (15.5, 17.5), (5, 17.5)])
        p.drawPolyline(QPolygonF([P(11.5, 2.5), P(11.5, 6.5), P(15.5, 6.5)]))
    elif name == "move":
        p.drawLine(P(3, 10), P(16, 10)); p.drawPolyline(QPolygonF([P(12, 6), P(16, 10), P(12, 14)]))
    elif name == "merge":
        d = QPainterPath(P(4, 3)); d.cubicTo(4, 10, 10, 9, 10, 17); path(d)
        d = QPainterPath(P(16, 3)); d.cubicTo(16, 10, 10, 9, 10, 17); path(d)
    elif name == "heart":
        d = QPainterPath(P(10, 16.5)); d.cubicTo(1, 10, 3, 2.5, 10, 6.5); d.cubicTo(17, 2.5, 19, 10, 10, 16.5); path(d)
    elif name == "moon":   # the sleep timer (R7.10)
        a = QPainterPath(); a.addEllipse(P(10, 10), 7, 7)
        b = QPainterPath(); b.addEllipse(P(13.5, 6.5), 6, 6)
        path(a.subtracted(b))
    elif name == "refresh":
        d = QPainterPath(); d.arcMoveTo(QRectF(3.5, 3.5, 13, 13), 60); d.arcTo(QRectF(3.5, 3.5, 13, 13), 60, 270); path(d)
        p.drawPolyline(QPolygonF([P(13.2, 2.5), P(13.4, 5.6), P(16.4, 5.2)]))
    p.restore()


def star(p, cx, cy, r, color, filled=True):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append(QPointF(cx + rr * math.cos(a), cy + rr * math.sin(a)))
    p.setPen(Qt.NoPen if filled else QPen(col(color), 1.1))
    p.setBrush(col(color) if filled else Qt.NoBrush)
    p.drawPolygon(QPolygonF(pts))


def stars(p, x, cy, n, r=5.2, gap=13.5, dim="faint"):
    for i in range(5):
        star(p, x + r + i * gap, cy, r, "star" if i < n else dim, filled=i < n)
    return 5 * gap


# ------------------------------------------------------------------ album art, from a seed
PALETTES = [
    ("#0f3b57", "#22d3ee", "#f472b6"), ("#2b1055", "#7597de", "#f9c74f"), ("#3d0c11", "#d4483b", "#f6bd60"),
    ("#0b3d2e", "#40916c", "#d8f3dc"), ("#1a1423", "#a78bfa", "#fb7185"), ("#14213d", "#fca311", "#e5e5e5"),
    ("#22223b", "#9a8c98", "#f2e9e4"), ("#03045e", "#00b4d8", "#caf0f8"), ("#370617", "#e85d04", "#ffba08"),
    ("#10002b", "#c77dff", "#e0aaff"), ("#283618", "#dda15e", "#fefae0"), ("#001219", "#0a9396", "#ee9b00"),
]


def art(p, x, y, sz, seed, r=10, border=True):
    rnd = random.Random(seed)
    a, b, c = PALETTES[rnd.randrange(len(PALETTES))]
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(x, y, sz, sz), r, r)
    p.setClipPath(clip, Qt.IntersectClip if p.hasClipping() else Qt.ReplaceClip)
    rect(p, x, y, sz, sz, 0, grad(x, y, x + sz, y + sz, [(0, a), (1, b)]))
    style = rnd.randrange(4)
    if style == 0:  # sun and horizon lines
        g = QRadialGradient(x + sz * 0.5, y + sz * 0.42, sz * 0.3)
        g.setColorAt(0, col(c)); g.setColorAt(1, col(c, 0.0))
        rect(p, x, y, sz, sz, 0, g)
        p.setBrush(col(c)); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(x + sz * 0.5, y + sz * 0.45), sz * 0.17, sz * 0.17)
        for i in range(7):
            yy = y + sz * (0.62 + i * 0.05)
            rect(p, x, yy, sz, sz * 0.012 * (1 + i * 0.5), 0, col(a, 0.9))
    elif style == 1:  # overlapping discs
        for _ in range(5):
            cx, cy, rr = x + rnd.random() * sz, y + rnd.random() * sz, sz * (0.15 + rnd.random() * 0.35)
            p.setBrush(col(rnd.choice([b, c, a]), 0.55)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), rr, rr)
    elif style == 2:  # diagonal bands
        p.translate(x + sz / 2, y + sz / 2); p.rotate(rnd.choice([-35, 30, 55])); p.translate(-(x + sz / 2), -(y + sz / 2))
        for i in range(-4, 9):
            rect(p, x - sz * 0.5, y + i * sz * 0.14, sz * 2, sz * 0.06 + rnd.random() * sz * 0.04, 0,
                 col(c if i % 2 else a, 0.35 + rnd.random() * 0.4))
    else:  # rings
        cx, cy = x + sz * (0.3 + rnd.random() * 0.4), y + sz * (0.3 + rnd.random() * 0.4)
        p.setBrush(Qt.NoBrush)
        for i in range(9, 0, -1):
            p.setPen(QPen(col(c if i % 2 else b, 0.7), sz * 0.025))
            p.drawEllipse(QPointF(cx, cy), sz * 0.07 * i, sz * 0.07 * i)
    p.restore()
    if border:
        rect(p, x, y, sz, sz, r, None, col("#ffffff", 0.06))


def art_colour(seed):
    """The cover's main colour, for tinting (R6.2.2)."""
    return PALETTES[random.Random(seed).randrange(len(PALETTES))][1]


def no_art(p, x, y, sz, r=10):
    rect(p, x, y, sz, sz, r, "raised", "borderStrong", 1.2, dash=[4, 3])
    icon(p, "image", x + sz / 2, y + sz / 2 - 8, sz * 0.22, "faint")
    text(p, x, y + sz / 2 + sz * 0.1, "No album art", max(10, sz * 0.07), "faint", w=sz, align="center")


# ------------------------------------------------------------------ waveform data
def wave_peaks(n, seed=3):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        t = i / n
        env = 0.35 + 0.45 * (math.sin(t * math.pi) ** 0.6) + 0.15 * math.sin(t * 23) * math.sin(t * 7)
        if 0.47 < t < 0.53:
            env *= 0.45  # a quiet bridge
        out.append(max(0.06, min(1.0, env * (0.55 + 0.45 * rnd.random()))))
    return out


def waveform(p, x, y, w, h, played, seed=3, bar=2.0, gap=1.2, dim="borderStrong"):
    n = int(w / (bar + gap))
    peaks = wave_peaks(n, seed)
    g = grad(x, 0, x + w * played, 0, [(0, "cyan"), (0.6, "accent"), (1, "pink")])
    for i, pk in enumerate(peaks):
        bx = x + i * (bar + gap)
        bh = max(2, pk * h)
        fill = g if bx < x + w * played else col(dim)
        rect(p, bx, y + (h - bh) / 2, bar, bh, bar / 2, fill)


# ------------------------------------------------------------------ window pieces
def window(p):
    rect(p, 0, 0, W, H, 0, "bg")


def window_buttons(p, x_right=W):
    for i, nm in enumerate(("close", "max", "min")):
        icon(p, nm, x_right - 22 - i * 34, 22, 14, "muted", 1.5)


def sidebar(p, active="Albums", active_pl=None, drop_on=None, root_missing=False):
    rect(p, 0, 0, SIDE_W, H - BAR_H, 0, "side")
    line(p, SIDE_W - 0.5, 0, SIDE_W - 0.5, H - BAR_H, "border")
    # logo: a soft gradient tile with a waveform glyph
    rect(p, 18, 16, 30, 30, 9, grad(18, 16, 48, 46, [(0, "cyan"), (0.55, "accent"), (1, "pink")]))
    for i, hh in enumerate((6, 12, 17, 10, 14, 7)):
        rect(p, 23.5 + i * 3.6, 31 - hh / 2, 2, hh, 1, "#ffffff")
    text(p, 58, 19, "MusiKata", 16, "text", 700)
    y = 66

    def item(label, ic, badge=None, is_active=False, indent=False, sub=None, dropping=False):
        nonlocal y
        if is_active:
            rect(p, 10, y, SIDE_W - 20, 32, 8, "accentSoft")
            rect(p, 10, y + 8, 3, 16, 1.5, "accent")
        if dropping:
            rect(p, 10, y, SIDE_W - 20, 32, 8, col("accent", 0.22), "accent", 1.4)
        icon(p, ic, 32, y + 16, 17, "accentHi" if is_active or dropping else "muted")
        text(p, 50, y + 5, label, 13.5, "text" if is_active or dropping else "#c9cdd8", 600 if is_active else 400, w=130)
        if badge:
            bw = tw(badge, 11, 600) + 14
            rect(p, SIDE_W - 22 - bw, y + 7, bw, 18, 9, badge[1] if isinstance(badge, tuple) else "raised")
            text(p, SIDE_W - 22 - bw, y + 7, badge if isinstance(badge, str) else badge[0], 11,
                 "muted", 600, w=bw, h=18, align="center")
        if sub:
            text(p, SIDE_W - 70, y + 5, sub, 11, "faint", w=50, align="right")
        y += 34

    text(p, 22, y, "LIBRARY", 10.5, "faint", 700); y += 24
    for label, ic in (("Albums", "album"), ("Artists", "artist"), ("Songs", "song"), ("Genres", "genre"),
                      ("Folders", "folder")):
        item(label, ic, is_active=(label == active))
    y += 2
    p.save()
    item("Needs attention", "attention", badge=None, is_active=(active == "Needs attention"))
    p.restore()
    bw = 30
    rect(p, SIDE_W - 22 - bw, y - 34 + 7, bw, 18, 9, "warnSoft")
    text(p, SIDE_W - 22 - bw, y - 34 + 7, "23", 11, "warn", 700, w=bw, h=18, align="center")
    y += 14
    text(p, 22, y, "PLAYLISTS", 10.5, "faint", 700)
    icon(p, "plus", SIDE_W - 32, y + 8, 15, "muted"); y += 24
    for label, n in (("Road Trip", "42"), ("Evening Focus", "18"), ("Sunday Morning", "27"), ("Workout Mix", "35"),
                     ("Rainy Day", "21"), ("Four stars and up", "212")):
        item(label, "playlist", is_active=(label == active_pl), sub=n, dropping=(label == drop_on))
    # the music root
    y0 = H - BAR_H - 76
    rect(p, 12, y0, SIDE_W - 24, 62, 10, "errSoft" if root_missing else "surface", col("err", 0.5) if root_missing else "border")
    icon(p, "folder", 32, y0 + 20, 16, "err" if root_missing else "accentHi")
    text(p, 48, y0 + 10, "~/Music", 13, "text", 600)
    text(p, 24, y0 + 34, "Not available" if root_missing else "1,412 songs · 128 albums · 9.8 GB", 11,
         "err" if root_missing else "muted", 600 if root_missing else 400, w=SIDE_W - 48)
    rect(p, SIDE_W - 40, y0 + 15, 8, 8, 4, "err" if root_missing else "ok")


def nowbar(p, playing=True, pos=0.38, title="Signal Fires", artist="Lumen Drift — Glass Harbor", seed=11,
           np_open=False, sleep=None):
    y = H - BAR_H
    rect(p, 0, y, W, BAR_H, 0, "#0b0d11")
    line(p, 0, y + 0.5, W, y + 0.5, "border")
    art(p, 16, y + 14, 60, seed, 8)
    text(p, 90, y + 18, title, 14, "text", 600, w=200)
    text(p, 90, y + 38, artist, 12, "muted", w=210)
    stars(p, 90, y + 66, 5, r=4.6, gap=12)
    # transport
    cx = W / 2
    icon(p, "shuffle", cx - 92, y + 28, 17, "accentHi")
    icon(p, "prev", cx - 46, y + 28, 17, "text")
    rect(p, cx - 18, y + 10, 36, 36, 18, "text")
    icon(p, "pause" if playing else "play", cx + (0 if playing else 1), y + 28, 16, "#0b0d11")
    icon(p, "next", cx + 46, y + 28, 17, "text")
    icon(p, "repeat", cx + 92, y + 28, 17, "muted")
    wx, ww = cx - 230, 460
    text(p, wx - 52, y + 54, "1:38", 11, "muted", w=44, align="right", mono=True)
    waveform(p, wx, y + 54, ww, 20, pos, seed=seed, bar=2, gap=1.3)
    rect(p, wx + ww * pos - 1, y + 51, 2, 26, 1, "text")
    text(p, wx + ww + 8, y + 54, "4:18", 11, "muted", w=44, mono=True)
    # right side: the queue, the volume, the mini player and, at the end, Now Playing (R6.5)
    if sleep:   # the sleep timer's moon and time left (R7.10)
        sw = tw(sleep, 11.5, 600, mono=True) + 40
        rect(p, W - 300 - sw, y + 27, sw, 28, 14, "accentSoft")
        icon(p, "moon", W - 300 - sw + 17, y + 41, 14, "accentHi")
        text(p, W - 300 - sw + 30, y + 27, sleep, 11.5, "accentHi", 600, h=28, mono=True)
    icon(p, "queue", W - 280, y + 41, 18, "muted")
    icon(p, "volume", W - 240, y + 41, 18, "muted")
    rect(p, W - 220, y + 39, 96, 4, 2, "borderStrong")
    rect(p, W - 220, y + 39, 64, 4, 2, "#c9cdd8")
    rect(p, W - 162, y + 35, 12, 12, 6, "text")
    icon(p, "popout", W - 84, y + 41, 17, "muted")
    if np_open:
        rect(p, W - 58, y + 25, 36, 32, 8, "accentSoft")
    icon(p, "expand", W - 40, y + 41, 17, "accentHi" if np_open else "muted")


def header(p, title, sub, x0=SIDE_W, x1=W, search="Search the library", toggles=True, sort="Artist",
           crumbs=None, modes=("grid", "list"), mode=0, search_w=250):
    tx = x0 + 28
    if crumbs:  # Folders: the path under the root, never the root's name (R2.9.1)
        for i, c in enumerate(crumbs):
            last = i == len(crumbs) - 1
            tx += text(p, tx, 14, c, 22, "text" if last else "muted", 700 if last else 600)
            if not last:
                tx += text(p, tx + 7, 14, "›", 22, "faint", 400) + 14
    else:
        tx += text(p, tx, 14, title, 22, "text", 700)
    text(p, tx + 14, 20, sub, 12.5, "muted")
    r = x1 - (124 if x1 == W else 16)   # leave the window buttons their corner
    icon(p, "more", r - 14, 32, 18, "muted"); r -= 40
    if sort:
        sw = tw("Sort: " + sort, 12.5) + 40
        rect(p, r - sw, 16, sw, 32, 8, "surface", "border")
        text(p, r - sw + 12, 16, "Sort: " + sort, 12.5, "#c9cdd8", h=32)
        icon(p, "chev_down", r - 16, 32, 14, "muted"); r -= sw + 10
    if toggles:
        mw = 36 * len(modes) + 4
        rect(p, r - mw, 16, mw, 32, 8, "surface", "border")
        for i, m in enumerate(modes):
            sx = r - mw + 2 + 36 * i
            if i == mode:
                rect(p, sx, 18, 36, 28, 6, "hover")
            icon(p, m, sx + 18, 32, 16, "text" if i == mode else "muted")
        r -= mw + 10
    if search and search_w <= 40:  # a narrowed header keeps search as its icon (R6.4)
        rect(p, r - 32, 16, 32, 32, 16, "input", "border")
        icon(p, "search", r - 16, 32, 15, "muted")
    elif search:
        sw = search_w
        rect(p, r - sw, 16, sw, 32, 16, "input", "border")
        icon(p, "search", r - sw + 18, 32, 15, "faint")
        text(p, r - sw + 34, 16, search, 12.5, "faint", h=32, w=sw - 70)
        rect(p, r - 34, 23, 22, 18, 5, "raised")
        text(p, r - 34, 23, "/", 11, "muted", w=22, h=18, align="center", mono=True)


def chip(p, x, y, label, fg="muted", bg="raised", h=22, ic=None, border=None, size=11.5, weight=600):
    w = tw(label, size, weight) + 18 + (16 if ic else 0)
    rect(p, x, y, w, h, h / 2, bg, border)
    if ic:
        icon(p, ic, x + 15, y + h / 2, 12, fg, 1.8)
    text(p, x + 9 + (16 if ic else 0), y, label, size, fg, weight, h=h)
    return w


def button(p, x, y, label, kind="primary", ic=None, h=34, w=None, size=13):
    pw = tw(label, size, 600) + 32 + (22 if ic else 0)
    w = w or pw
    fill, fg, stroke = {
        "primary": (grad(x, y, x + w, y + h, [(0, "#6d28d9"), (1, "#7c3aed")]), "#ffffff", None),
        "ghost": ("surface", "text", "borderStrong"),
        "quiet": (None, "accentHi", None),
        "danger": ("errSoft", "err", None),
    }[kind]
    rect(p, x, y, w, h, 9, fill, stroke)
    cx = x + (w - pw) / 2 + 16
    if ic:
        icon(p, ic, cx + 7, y + h / 2, 15, fg, 1.8)
        cx += 22
    text(p, cx, y, label, size, fg, 600, h=h)
    return w


def field(p, x, y, w, label, value, mixed=False, changed=False, h=34, mono=False, hint=None):
    text(p, x, y, label, 11.5, "muted", 600)
    rect(p, x, y + 20, w, h, 8, "input", "accent" if changed else "border", 1.3 if changed else 1)
    if mixed:
        text(p, x + 12, y + 20, value or "Mixed: keep each song's own", 13, "faint", h=h, w=w - 24)
    else:
        text(p, x + 12, y + 20, value, 13, "text", h=h, w=w - 24, mono=mono)
    if changed:
        rect(p, x + w - 10, y + 20 + h / 2 - 3, 6, 6, 3, "accent")
    if hint:
        text(p, x, y + 22 + h, hint, 11, "faint", w=w)


def dialog(p, w, h, title, sub=None):
    rect(p, 0, 0, W, H, 0, col("scrim", 0.62))
    x, y = (W - w) / 2, (H - h) / 2
    shadow(p, x, y, w, h, 16, 28)
    rect(p, x, y, w, h, 16, "surface", "borderStrong")
    text(p, x + 28, y + 22, title, 18, "text", 700, w=w - 80)
    if sub:
        text(p, x + 28, y + 50, sub, 12.5, "muted", w=w - 56)
    icon(p, "close", x + w - 30, y + 34, 15, "muted")
    return x, y


def toggle(p, x, y, on=True):
    rect(p, x, y, 36, 20, 10, "accent" if on else "borderStrong")
    rect(p, x + (18 if on else 2), y + 2, 16, 16, 8, "#ffffff")


def radio(p, x, y, on):
    rect(p, x, y, 16, 16, 8, None, "accent" if on else "borderStrong", 1.6)
    if on:
        rect(p, x + 4, y + 4, 8, 8, 4, "accent")


def checkbox(p, x, y, on, partial=False):
    rect(p, x, y, 16, 16, 4.5, "accent" if on or partial else None, None if on or partial else "borderStrong", 1.5)
    if on:
        icon(p, "check", x + 8, y + 8, 13, "#ffffff", 2.2)
    elif partial:
        rect(p, x + 4, y + 7, 8, 2, 1, "#ffffff")


def table_header(p, x, y, cols, w_total):
    rect(p, x, y, w_total, 32, 0, "bg")
    for label, cx, cw, al in cols:
        text(p, cx, y, label, 11, "faint", 700, w=cw, h=32, align=al)
    line(p, x, y + 32, x + w_total, y + 32, "border")


# ------------------------------------------------------------------ screens
def x01_first_run(p):
    window(p)
    window_buttons(p)
    g = QRadialGradient(W / 2, 250, 520)
    g.setColorAt(0, col("accent", 0.16)); g.setColorAt(1, col("accent", 0.0))
    rect(p, 0, 0, W, H, 0, g)
    rect(p, W / 2 - 34, 92, 68, 68, 20, grad(0, 92, 0, 160, [(0, "cyan"), (0.55, "accent"), (1, "pink")]))
    for i, hh in enumerate((14, 28, 40, 22, 32, 16)):
        rect(p, W / 2 - 22 + i * 8.4, 126 - hh / 2, 4.4, hh, 2.2, "#ffffff")
    text(p, 0, 182, "Welcome to MusiKata", 30, "text", 700, w=W, align="center")
    text(p, 0, 228, "Point it at the folder your music lives in. Nothing is changed until you say so.", 15,
         "muted", w=W, align="center")
    bx, by, bw, bh = W / 2 - 330, 280, 660, 190
    rect(p, bx, by, bw, bh, 18, col("accent", 0.06), "accent", 1.5, dash=[6, 4])
    icon(p, "folder", W / 2, by + 52, 40, "accentHi", 1.5)
    text(p, bx, by + 84, "Drop your music folder here", 17, "text", 600, w=bw, align="center")
    text(p, bx, by + 110, "or", 12.5, "faint", w=bw, align="center")
    button(p, W / 2 - 160, by + 136, "Choose folder…", "primary", "folder", w=150)
    button(p, W / 2 + 10, by + 136, "Use ~/Music", "ghost", w=150)
    y = 512
    for i, (ic, head, body) in enumerate((
        ("wand", "Tags from paths", "Artist/Album/01 - Title.mp3 becomes tags, shown before anything is written."),
        ("image", "Album art, sorted", "Finds folder images and embedded art, and puts the same cover on every track."),
        ("playlist", "Plain playlists", "M3U playlists with relative paths, readable by any other player."),
    )):
        x = W / 2 - 450 + i * 306
        rect(p, x, y, 288, 112, 14, "surface", "border")
        rect(p, x + 18, y + 18, 34, 34, 10, "accentSoft")
        icon(p, ic, x + 35, y + 35, 18, "accentHi")
        text(p, x + 64, y + 22, head, 14, "text", 600)
        p.setFont(font(12)); p.setPen(col("muted"))
        p.drawText(QRectF(x + 18, y + 60, 252, 44), Qt.TextWordWrap, body)
    text(p, 0, 660, "Supported: MP3, FLAC, M4A/AAC, Ogg Vorbis, Opus, WAV, AIFF", 12, "faint", w=W, align="center")


def l01_albums(p, missing=False):
    window(p)
    sidebar(p, "Albums", root_missing=missing)
    header(p, "Albums", "128 albums")
    window_buttons(p)
    x0, y0 = SIDE_W + 28, 76
    if missing:  # R2.10: the library is kept, playing and changes wait
        bw = W - x0 - 28
        rect(p, x0, 72, bw, 62, 12, "errSoft", col("err", 0.45))
        icon(p, "attention", x0 + 24, 103, 18, "err")
        text(p, x0 + 46, 80, "~/Music isn't available. Its drive may be unplugged or its share not mounted.", 13.5,
             "text", 600, w=bw - 380)
        text(p, x0 + 46, 102, "Your library is kept. Playing and changes to files wait until it's back.", 12,
             "muted", w=bw - 380)
        bx = x0 + bw - 16
        bx -= button(p, bx - 206, 86, "Choose another folder…", "quiet", "folder", w=206, h=34, size=12.5) + 8
        button(p, bx - 112, 86, "Try again", "ghost", "refresh", w=112, h=34, size=12.5)
        y0 += 74
    # genre chips
    cx = x0
    for i, g in enumerate(("All", "Electronic", "Indie Rock", "Jazz", "Soul", "Folk", "Ambient", "Synthwave",
                           "Post-Rock", "More…")):
        on = i == 0
        cx += chip(p, cx, y0, g, "text" if on else "muted", "accentSoft" if on else "surface", 28,
                   border=None if on else "border", size=12, weight=600 if on else 500) + 8
    cols, card, gap = 6, 152, 20
    y = y0 + 48
    for i, (artist, album, year, genre, seed, n) in enumerate(ALBUMS[:12]):
        r, c = divmod(i, cols)
        x = x0 + c * (card + gap)
        yy = y + r * (card + 74)
        if album == "Kindling":
            no_art(p, x, yy, card)
        else:
            art(p, x, yy, card, seed)
        if i == 0 and not missing:
            rect(p, x, yy, card, card, 10, col("#000000", 0.35))
            rect(p, x + card / 2 - 22, yy + card / 2 - 22, 44, 44, 22, "#ffffff")
            icon(p, "pause", x + card / 2, yy + card / 2, 18, "#111111")
            rect(p, x - 3, yy - 3, card + 6, card + 6, 12, None, "accent", 2)
        text(p, x, yy + card + 8, album, 13.5, "text", 600, w=card)
        text(p, x, yy + card + 28, f"{artist} · {year}", 12, "muted", w=card)
        if i == 9:
            chip(p, x + 8, yy + 8, "New", "#ffffff", col("#000000", 0.55), 20, size=10.5)
    # a third row, partly hidden by the now-playing bar
    for c in range(cols):
        x = x0 + c * (card + gap)
        a = ALBUMS[(c + 3) % len(ALBUMS)]
        yy = y + 2 * (card + 74)
        if yy < H - BAR_H:
            p.save(); p.setClipRect(QRectF(SIDE_W, 0, W, H - BAR_H)); art(p, x, yy, card, a[4] + 200); p.restore()
    nowbar(p, playing=not missing)


def x02_root_unavailable(p):
    l01_albums(p, missing=True)


def l02_album(p):
    window(p)
    sidebar(p, "Albums")
    window_buttons(p)
    x0 = SIDE_W + 28
    g = QLinearGradient(0, 0, 0, 330)
    g.setColorAt(0, col("#0f3b57", 0.9)); g.setColorAt(1, col("bg", 0.0))
    rect(p, SIDE_W, 0, W - SIDE_W, 330, 0, g)
    text(p, x0, 18, "‹  Albums", 13, "muted", 500)
    shadow(p, x0, 56, 220, 220, 12, 22)
    art(p, x0, 56, 220, 11, 12)
    tx = x0 + 248
    text(p, tx, 70, "ALBUM · 2019 · ELECTRONIC", 11, "#b9e6f2", 700)
    text(p, tx, 92, "Glass Harbor", 40, "text", 800)
    text(p, tx, 150, "Lumen Drift", 17, "text", 600)
    text(p, tx, 178, "10 songs · 44 min · FLAC 16-bit/44.1 kHz", 12.5, "muted")
    bx = tx
    bx += button(p, bx, 220, "Play", "primary", "play", w=104) + 10
    bx += button(p, bx, 220, "Shuffle", "ghost", "shuffle") + 10
    bx += button(p, bx, 220, "Edit tags", "ghost", "genre") + 10
    bx += button(p, bx, 220, "Album art", "ghost", "image") + 10
    rect(p, bx, 220, 34, 34, 9, "surface", "borderStrong")
    icon(p, "more", bx + 17, 237, 16, "muted")
    cx = tx
    cx += chip(p, cx, 268, "Art embedded in 10 of 10", "ok", "okSoft", ic="check") + 8
    cx += chip(p, cx, 268, "cover.jpg in folder", "muted", "raised", ic="image") + 8
    chip(p, cx, 268, "Tags match path", "ok", "okSoft", ic="check")
    # tracks
    ty = 316
    tw_total = W - SIDE_W - 56
    cols = [("#", x0 + 4, 26, "right"), ("TITLE", x0 + 48, 380, "left"), ("RATING", x0 + 560, 90, "left"),
            ("PLAYS", x0 + 690, 60, "right"), ("TIME", x0 + tw_total - 70, 60, "right")]
    table_header(p, x0, ty, cols, tw_total)
    for i, t in enumerate(GLASS[:9]):
        y = ty + 34 + i * 40
        if y > H - BAR_H - 36:
            break
        cur = i == 3
        if cur:
            rect(p, x0 - 8, y, tw_total + 16, 38, 8, "accentSoft")
        if i == 5:
            rect(p, x0 - 8, y, tw_total + 16, 38, 8, "hover")
            icon(p, "play", x0 + 22, y + 19, 13, "text")
        elif cur:
            for k, hh in enumerate((8, 13, 6)):
                rect(p, x0 + 15 + k * 5, y + 26 - hh, 3, hh, 1, "accentHi")
        else:
            text(p, x0 + 4, y, str(i + 1), 13, "muted", w=26, h=38, align="right")
        text(p, x0 + 48, y, t, 13.5, "accentHi" if cur else "text", 600 if cur else 400, h=38, w=380)
        stars(p, x0 + 560, y + 19, GLASS_RATE[i], r=5, gap=13)
        text(p, x0 + 690, y, str([31, 44, 18, 52, 27, 15, 9, 22, 13][i]), 12.5, "muted", w=60, h=38, align="right")
        if i == 5:
            icon(p, "more", x0 + tw_total - 92, y + 19, 15, "muted")
        text(p, x0 + tw_total - 70, y, GLASS_LEN[i], 12.5, "muted", w=60, h=38, align="right", mono=True)
    nowbar(p)


SONGS = [
    # title, artist, album, genre, year, time, rating, track
    ("Tidewater", "Lumen Drift", "Glass Harbor", "Electronic", "2019", "4:02", 4, 1),
    ("Glass Harbor", "Lumen Drift", "Glass Harbor", "Electronic", "2019", "5:11", 5, 2),
    ("Small Hours", "Lumen Drift", "Glass Harbor", "Electronic", "2019", "3:47", 3, 3),
    ("Signal Fires", "Lumen Drift", "Glass Harbor", "Electronic", "2019", "4:18", 5, 4),
    ("Neap Tide", "Lumen Drift", "Tide Tables", "Electronica", "2022", "4:31", 4, 1),
    ("Spring Tide", "Lumen Drift", "Tide Tables", "electronic", "2022", "3:58", 3, 2),
    ("Slack Water", "Lumen Drift", "Tide Tables", "Electronic", "", "5:02", 0, 3),
    ("Moonpull", "lumen drift", "Tide Tables", "Electronic", "2022", "4:44", 4, 4),
    ("Fieldwork", "Static Bloom", "Neon Fieldwork", "Electronic", "2024", "3:36", 4, 1),
    ("Pale Neon", "Static Bloom", "Neon Fieldwork", "Electronic", "2024", "4:09", 3, 2),
    ("Wire Garden", "Static Bloom", "Neon Fieldwork", "Electronic", "2024", "5:20", 5, 3),
    ("Afterimage", "Static Bloom", "Neon Fieldwork", "Electronic", "2024", "3:15", 0, 4),
    ("Overpass", "Static Bloom", "Neon Fieldwork", "Electronic", "2024", "4:47", 4, 5),
    ("Low Orbit", "Kestrel Union", "Low Orbit", "Synthwave", "2022", "4:26", 5, 1),
]


def l03_songs_bulk(p):
    window(p)
    sidebar(p, "Songs")
    xr = W - PANEL_W
    header(p, "Songs", "1,412 songs", x1=xr, toggles=False, sort=None, search="electronic")
    x0 = SIDE_W + 20
    wt = xr - x0 - 16
    cols = [("", x0 + 6, 16, "left"), ("#", x0 + 28, 20, "right"), ("TITLE", x0 + 60, 140, "left"),
            ("ARTIST", x0 + 206, 110, "left"), ("ALBUM", x0 + 322, 120, "left"), ("GENRE", x0 + 448, 90, "left"),
            ("YEAR", x0 + 540, 40, "left"), ("RATING", x0 + 586, 74, "left")]
    ty = 70
    table_header(p, x0, ty, cols, wt)
    checkbox(p, x0 + 6, ty + 8, False, partial=True)
    sel = set(range(4, 8))
    for i, s in enumerate(SONGS):
        y = ty + 34 + i * 36
        if y > H - BAR_H - 34:
            break
        if i in sel:
            rect(p, x0, y + 1, wt, 34, 6, "sel")
        checkbox(p, x0 + 6, y + 10, i in sel)
        text(p, x0 + 28, y, str(s[7]), 12.5, "muted", w=20, h=36, align="right")
        text(p, x0 + 60, y, s[0], 13, "text", 500 if i in sel else 400, w=140, h=36)
        text(p, x0 + 206, y, s[1], 12.5, "err" if s[1].islower() else "#c9cdd8", w=110, h=36)
        text(p, x0 + 322, y, s[2], 12.5, "#c9cdd8", w=120, h=36)
        text(p, x0 + 448, y, s[3], 12.5, "warn" if s[3] != "Electronic" and i in sel else "#c9cdd8", w=90, h=36)
        text(p, x0 + 540, y, s[4] or "—", 12.5, "#c9cdd8" if s[4] else "faint", w=40, h=36)
        stars(p, x0 + 586, y + 18, s[6], r=4.4, gap=11.5)
    # selection bar
    by = H - BAR_H - 52
    rect(p, x0 + 60, by, 470, 40, 12, "raised", "borderStrong")
    text(p, x0 + 78, by, "4 selected", 13, "text", 600, h=40)
    bx = x0 + 168
    for lab, ic in (("Play next", "play"), ("Add to playlist", "plus"), ("Infer from path", "wand")):
        icon(p, ic, bx + 8, by + 20, 14, "accentHi")
        bx += text(p, bx + 20, by, lab, 12.5, "accentHi", 600, h=40) + 38
    # the tag panel, editing 4 songs at once
    rect(p, xr, 0, PANEL_W, H - BAR_H, 0, "side")
    line(p, xr + 0.5, 0, xr + 0.5, H - BAR_H, "border")
    px = xr + 22
    pw = PANEL_W - 44
    text(p, px, 58, "EDIT TAGS · 4 SONGS", 11, "faint", 700)
    icon(p, "close", xr + PANEL_W - 28, 66, 14, "muted")
    art(p, px, 86, 76, 131, 8)
    text(p, px + 90, 90, "Tide Tables", 15, "text", 700, w=pw - 90)
    text(p, px + 90, 112, "Lumen Drift · 4 songs", 12, "muted", w=pw - 90)
    chip(p, px + 90, 138, "Same art on all 4", "ok", "okSoft", ic="check", size=10.5)
    y = 180
    field(p, px, y, pw, "Artist", "Lumen Drift", changed=True); y += 62
    field(p, px, y, pw, "Album", "Tide Tables"); y += 62
    field(p, px, y, pw * 0.62, "Genre", "Electronic", changed=True)
    field(p, px + pw * 0.66, y, pw * 0.34, "Year", "2022", changed=True); y += 62
    field(p, px, y, pw * 0.48, "Album artist", "Lumen Drift")
    field(p, px + pw * 0.52, y, pw * 0.48, "Disc", "1 / 1"); y += 62
    field(p, px, y, pw, "Title", None, mixed=True); y += 62
    text(p, px, y, "Rating", 11.5, "muted", 600)
    rect(p, px, y + 20, pw, 34, 8, "input", "border")
    text(p, px + 12, y + 20, "Mixed: keep each song's own", 13, "faint", h=34)
    y += 70   # More fields, closed (R4.2): composer, comment and the sort names (R2.13)
    icon(p, "chev_right", px + 6, y + 14, 13, "muted")
    tx = px + 20 + text(p, px + 20, y, "More fields", 12.5, "text", 600, h=28)
    text(p, tx + 10, y, "Composer, Comment, sort names", 11.5, "faint", h=28, w=pw - tx + px - 10)
    # changes summary and actions
    y = H - BAR_H - 92
    rect(p, px, y, pw, 30, 8, "accentSoft")
    text(p, px + 12, y, "3 fields will change on 4 songs", 12, "accentHi", 600, h=30, w=pw - 24)
    button(p, px, y + 42, "Revert", "ghost", "undo", w=pw * 0.42)
    button(p, px + pw * 0.46, y + 42, "Save to 4 files", "primary", "check", w=pw * 0.54)
    window_buttons(p)   # above the panel
    nowbar(p, seed=131, title="Neap Tide", artist="Lumen Drift — Tide Tables", pos=0.62)


FOLDER_MODES = ("large", "small", "cards", "list")   # R2.9.4, in the header's order

FOLDERS = [
    # name, what's beneath it, the pictures for its cover (R5.8; seeds, [] = none), worst state (R2.9.5)
    ("Cedar & Vale", "1 folder · 13 songs", [53], None),
    ("Compilations", "4 folders · 52 songs", [401, 409, 419, 421], ("warn", "2 to fix")),
    ("Ghost Meridian", "1 folder · 6 songs", [127], None),
    ("Hollow Coast", "1 folder · 11 songs", [83], None),
    ("_Incoming", "2 folders · 23 songs", [], ("err", "No tags")),
    ("Ironwood Choir", "1 folder · 14 songs", [113], None),
    ("Juniper Sixes", "1 folder · 10 songs", [71], None),
    ("Kestrel Union", "1 folder · 9 songs", [41], None),
    ("Lumen Drift", "3 folders · 37 songs", [11, 301, 131], ("warn", "2 to fix")),
    ("Mara Okafor", "3 folders · 31 songs", [151, 37], ("warn", "10 to fix")),
    ("Nadia Reyes Trio", "1 folder · 7 songs", [97], None),
    ("Orbital Fern", "1 folder · 8 songs", [67], None),
    ("Saffron Avenue", "1 folder · 12 songs", [139], None),
    ("Soundtracks", "5 folders · 61 songs", [431, 433, 439, 443], None),
    ("Static Bloom", "1 folder · 12 songs", [101], None),
    ("The Paper Lanterns", "2 folders · 23 songs", [23, 461], None),
    ("Wildflower Radio", "1 folder · 9 songs", [471], None),
    ("Yellow Kites", "1 folder · 10 songs", [479], None),
]


def mosaic(p, x, y, sz, seeds, r=10, gap=2):
    """A folder's picture (R5.8): its own cover, a mosaic of up to four covers beneath it, or none."""
    if not seeds:
        rect(p, x, y, sz, sz, r, "raised", "borderStrong", 1.2, dash=[4, 3])
        icon(p, "folder", x + sz / 2, y + sz / 2 - (sz * 0.07 if sz >= 100 else 0), sz * 0.26, "faint", 1.4)
        if sz >= 100:
            text(p, x, y + sz / 2 + sz * 0.1, "No art", max(10, sz * 0.075), "faint", w=sz, align="center")
        return
    if len(seeds) == 1:
        art(p, x, y, sz, seeds[0], r)
        return
    h = (sz - gap) / 2
    boxes = {
        2: [(x, y, h, sz), (x + h + gap, y, h, sz)],
        3: [(x, y, h, sz), (x + h + gap, y, h, h), (x + h + gap, y + h + gap, h, h)],
    }.get(len(seeds), [(x, y, h, h), (x + h + gap, y, h, h), (x, y + h + gap, h, h), (x + h + gap, y + h + gap, h, h)])
    p.save()
    outer = QPainterPath()
    outer.addRoundedRect(QRectF(x, y, sz, sz), r, r)
    p.setClipPath(outer, Qt.IntersectClip if p.hasClipping() else Qt.ReplaceClip)
    for (bx, by, bw, bh), seed in zip(boxes, seeds[:4]):
        p.save()
        p.setClipRect(QRectF(bx, by, bw, bh), Qt.IntersectClip)
        side = max(bw, bh)   # a centre crop of the cover
        art(p, bx + (bw - side) / 2, by + (bh - side) / 2, side, seed, 0, border=False)
        p.restore()
    p.restore()
    rect(p, x, y, sz, sz, r, None, col("#ffffff", 0.06))


def state_dot(p, x, y, st):
    if st:
        rect(p, x - 7, y - 7, 14, 14, 7, "bg")
        rect(p, x - 5, y - 5, 10, 10, 5, st[0])


def round_check(p, x, y, on):
    if on:
        rect(p, x, y, 22, 22, 11, "accent")
        icon(p, "check", x + 11, y + 11, 14, "#ffffff", 2.2)
    else:
        rect(p, x, y, 22, 22, 11, col("#000000", 0.35), col("#ffffff", 0.85), 1.6)


def folder_grid(p, folders, x0, y0, card, gap, cols, hover=None, playing=None, big=False):
    pitch = card + (70 if big else 64)
    p.save()
    p.setClipRect(QRectF(SIDE_W, 0, W - SIDE_W, H - BAR_H))
    for i, (name, sub, pics, st) in enumerate(folders):
        r_, c_ = divmod(i, cols)
        x, y = x0 + c_ * (card + gap), y0 + r_ * pitch
        if y > H - BAR_H:
            break
        mosaic(p, x, y, card, pics, 12 if big else 10)
        if name == playing:
            rect(p, x - 3, y - 3, card + 6, card + 6, 14 if big else 12, None, "accent", 2)
            for k, hh in enumerate((9, 15, 7)):
                rect(p, x + 12 + k * 5, y + card - 12 - hh, 3, hh, 1, "#ffffff")
        if name == hover:  # the pointer is on it: its checkbox and play button
            rect(p, x, y, card, card, 12 if big else 10, col("#000000", 0.30))
            round_check(p, x + 10, y + 10, False)
            rect(p, x + card - 52, y + card - 52, 42, 42, 21, "#ffffff")
            icon(p, "play", x + card - 30, y + card - 31, 18, "#111111")
        state_dot(p, x + card - 13, y + 13, st)
        text(p, x, y + card + 8, name, 15 if big else 13.5, "text", 600, w=card)
        text(p, x, y + card + (31 if big else 27), sub, 12.5 if big else 12, "muted", w=card)
    p.restore()


def selection_bar(p, cx, by, head, sub, actions):
    w = 36 + tw(head, 13, 600) + 8 + tw(sub, 12) + 12 + sum(tw(lab, 12.5, 600) + 42 for lab, _ in actions) + 30
    x = cx - w / 2
    shadow(p, x, by, w, 44, 12, 14)
    rect(p, x, by, w, 44, 12, "raised", "borderStrong")
    tx = x + 18
    tx += text(p, tx, by, head, 13, "text", 600, h=44) + 8
    tx += text(p, tx, by, sub, 12, "muted", h=44) + 24
    for lab, ic in actions:
        icon(p, ic, tx + 7, by + 22, 14, "accentHi")
        tx += text(p, tx + 20, by, lab, 12.5, "accentHi", 600, h=44) + 42
    icon(p, "close", x + w - 24, by + 22, 13, "muted")
    return w


def l04_folders(p):
    window(p)
    sidebar(p, "Folders")
    header(p, "Your music folders", "42 folders · 1,412 songs", search="Search folders", search_w=170, modes=FOLDER_MODES,
           mode=1, sort="Name")
    window_buttons(p)
    folder_grid(p, FOLDERS, SIDE_W + 28, 76, 152, 20, 6, hover="Mara Okafor", playing="Lumen Drift")
    nowbar(p)


LUMEN = [("2019 - Glass Harbor", "10 songs", [11], None), ("Remixes", "2 folders · 14 songs", [301, 311], None),
         ("Tide Tables", "9 songs", [131], ("warn", "2 to fix"))]
LUMEN_FILES = [
    # file, title, album, rating, time, path-match state (R3.9)
    ("Lumen Drift - Harbor Lights.flac", "Harbor Lights", "Harbor Lights - Single", 4, "3:58", ("ok", "Match")),
    ("Lumen Drift - Lowlight (Radio Edit).mp3", "Lowlight (Radio Edit)", "Glass Harbor", 3, "3:21", ("ok", "Match")),
    ("Lumen Drift - Northern Line.flac", "Northern Line", "Northern Line - Single", 0, "4:40", ("warn", "Year missing")),
    ("lumen drift - ebb & flow.mp3", "ebb & flow", "", 0, "5:02", ("warn", "Title case differs")),
]


def l05_folders_large(p):
    window(p)
    sidebar(p, "Folders")
    header(p, None, "3 folders · 37 songs", crumbs=["Lumen Drift"], search="Search folders", search_w=170,
           modes=FOLDER_MODES, mode=0, sort="Name")
    window_buttons(p)
    x0 = SIDE_W + 28
    wt = W - x0 - 28
    card = (wt - 3 * 24) / 4
    folder_grid(p, LUMEN, x0, 76, card, 24, 4, hover="Remixes", playing="2019 - Glass Harbor", big=True)
    y = 76 + card + 74
    text(p, x0, y, "4 songs in this folder", 14, "text", 700)
    cols = [("FILE", x0 + 34, 290, "left"), ("TITLE", x0 + 340, 170, "left"), ("ALBUM", x0 + 520, 160, "left"),
            ("RATING", x0 + 690, 70, "left"), ("TIME", x0 + 770, 44, "right"), ("FROM PATH", x0 + 836, 150, "left")]
    table_header(p, x0, y + 30, cols, wt)
    for i, (fn, title, album, rating, length, st) in enumerate(LUMEN_FILES):
        yy = y + 64 + i * 36
        icon(p, "file", x0 + 16, yy + 18, 14, "muted")
        text(p, x0 + 34, yy, fn, 12.5, "text", w=290, h=36)
        text(p, x0 + 340, yy, title, 12.5, "#c9cdd8", w=170, h=36)
        text(p, x0 + 520, yy, album or "—", 12.5, "#c9cdd8" if album else "faint", w=160, h=36)
        stars(p, x0 + 690, yy + 18, rating, r=4.4, gap=11.5)
        text(p, x0 + 770, yy, length, 12.5, "muted", w=44, h=36, align="right", mono=True)
        chip(p, x0 + 836, yy + 7, st[1], st[0], st[0] + "Soft", h=22, ic="check" if st[0] == "ok" else "attention",
             size=11)
    nowbar(p)


def l06_folders_cards(p):
    window(p)
    sidebar(p, "Folders")
    header(p, "Your music folders", "42 folders · 1,412 songs", search="Search folders", search_w=170, modes=FOLDER_MODES,
           mode=2, sort="Name")
    window_buttons(p)
    x0 = SIDE_W + 28
    wt = W - x0 - 28
    gap, ch = 16, 96
    cw = (wt - 2 * gap) / 3
    sel = {"Lumen Drift", "Mara Okafor"}
    for i, (name, sub, pics, st) in enumerate(FOLDERS):
        r_, c_ = divmod(i, 3)
        x, y = x0 + c_ * (cw + gap), 76 + r_ * (ch + 14)
        if y + ch > H - BAR_H - 60:
            break
        tint = art_colour(pics[0]) if pics else "#94a3b8"
        on = name in sel
        rect(p, x, y, cw, ch, 14, grad(x, y, x + cw, y + ch, [(0, col(tint, 0.26)), (1, col(tint, 0.05))]),
             "accent" if on else col(tint, 0.32), 1.8 if on else 1.0)
        mosaic(p, x + 12, y + 12, ch - 24, pics, 8)
        tx = x + ch + 2
        text(p, tx, y + 14, name, 15, "text", 700, w=cw - (tx - x) - 40)
        text(p, tx, y + 38, sub, 12, "muted", w=cw - (tx - x) - 16)
        if st:
            chip(p, tx, y + 62, st[1], st[0], st[0] + "Soft", 20, ic="attention", size=10.5)
        if on:
            round_check(p, x + cw - 34, y + 12, True)
    selection_bar(p, x0 + wt / 2, H - BAR_H - 58, "2 folders", "66 songs",
                  [("Play", "play"), ("Add to playlist", "plus"), ("Edit tags", "genre"),
                   ("Infer from path", "wand"), ("Organize…", "move")])
    nowbar(p)


MARA = [
    # kind, name, second line or None, pictures, state, artist, album, year, rating, time, selected
    ("folder", "Kindling", "10 songs", [], ("warn", "10 to fix"), "Mara Okafor", "Kindling", "2015", None, "41:20", True),
    ("folder", "Live at the Lantern", "8 songs", [151], None, "Mara Okafor", "Live at the Lantern", "2016", None,
     "52:08", False),
    ("folder", "Salt & Ember", "11 songs", [37], None, "Mara Okafor", "Salt & Ember", "2018", None, "46:33", False),
    ("file", "Ember (live take).mp3", None, None, None, "Mara Okafor", "", "", 3, "4:51", False),
    ("file", "Kindling (acoustic).m4a", None, None, None, "Mara Okafor", "", "2015", 4, "3:44", True),
    ("file", "untitled 03.mp3", None, None, None, "", "", "", 0, "2:57", False),
]


def l07_folders_list(p):
    window(p)
    sidebar(p, "Folders")
    xr = W - PANEL_W
    header(p, None, "3 folders · 31 songs", x1=xr, crumbs=["Mara Okafor"], search="Search", search_w=32,
           modes=FOLDER_MODES, mode=3, sort="Name")
    x0 = SIDE_W + 20
    wt = xr - x0 - 16
    cols = [("", x0 + 6, 16, "left"), ("NAME", x0 + 30, 200, "left"), ("ARTIST", x0 + 300, 100, "left"),
            ("ALBUM", x0 + 404, 100, "left"), ("YEAR", x0 + 510, 40, "left"), ("RATING", x0 + 552, 64, "left"),
            ("TIME", x0 + wt - 46, 40, "right")]
    ty = 70
    table_header(p, x0, ty, cols, wt)
    checkbox(p, x0 + 6, ty + 8, False, partial=True)
    y = ty + 34
    for kind, name, sub, pics, st, artist, album, year, rating, length, on in MARA:
        rh = 64 if kind == "folder" else 36
        if on:
            rect(p, x0, y + 1, wt, rh - 2, 8, "sel")
        checkbox(p, x0 + 6, y + rh / 2 - 8, on)
        if kind == "folder":  # two rows tall, the cover the row's full height (R2.9.4)
            mosaic(p, x0 + 30, y + 4, rh - 8, pics, 7)
            text(p, x0 + 96, y + 9, name, 13.5, "text", 600, w=196, h=24)
            sx = x0 + 96 + text(p, x0 + 96, y + 33, sub, 12, "muted", h=22) + 10
            if st:
                chip(p, sx, y + 34, st[1], st[0], st[0] + "Soft", 20, ic="attention", size=10.5)
        else:
            icon(p, "file", x0 + 58, y + 18, 14, "muted")
            text(p, x0 + 96, y, name, 13, "text", 500 if on else 400, w=196, h=36)
        text(p, x0 + 300, y, artist or "—", 12.5, "#c9cdd8" if artist else "faint", w=96, h=rh)
        text(p, x0 + 404, y, album or "—", 12.5, "#c9cdd8" if album else "faint", w=100, h=rh)
        text(p, x0 + 510, y, year or "—", 12.5, "#c9cdd8" if year else "faint", w=40, h=rh)
        if rating is not None:
            stars(p, x0 + 552, y + rh / 2, rating, r=4.4, gap=11.5)
        text(p, x0 + wt - 46, y, length, 12.5, "muted", w=40, h=rh, align="right", mono=True)
        y += rh
        line(p, x0, y - 0.5, x0 + wt, y - 0.5, "border")
    selection_bar(p, x0 + wt / 2, H - BAR_H - 58, "11 songs", "1 folder, 1 file",
                  [("Play", "play"), ("Infer from path", "wand")])
    # the Edit tags panel, on every song beneath the folder and the file
    rect(p, xr, 0, PANEL_W, H - BAR_H, 0, "side")
    line(p, xr + 0.5, 0, xr + 0.5, H - BAR_H, "border")
    px = xr + 22
    pw = PANEL_W - 44
    text(p, px, 58, "EDIT TAGS · 11 SONGS", 11, "faint", 700)
    icon(p, "close", xr + PANEL_W - 28, 66, 14, "muted")
    no_art(p, px, 86, 76, 8)
    text(p, px + 90, 90, "Kindling", 15, "text", 700, w=pw - 90)
    text(p, px + 90, 112, "Mara Okafor · 1 folder, 1 file", 12, "muted", w=pw - 90)
    chip(p, px + 90, 138, "No cover yet", "warn", "warnSoft", ic="image", size=10.5)
    y = 180
    field(p, px, y, pw, "Artist", "Mara Okafor"); y += 62
    field(p, px, y, pw, "Album", "Kindling", changed=True); y += 62
    field(p, px, y, pw * 0.62, "Genre", "Soul", changed=True)
    field(p, px + pw * 0.66, y, pw * 0.34, "Year", "2015"); y += 62
    field(p, px, y, pw * 0.48, "Album artist", "Mara Okafor")
    field(p, px + pw * 0.52, y, pw * 0.48, "Disc", "1 / 1"); y += 62
    field(p, px, y, pw, "Title", None, mixed=True); y += 62
    text(p, px, y, "Rating", 11.5, "muted", 600)
    rect(p, px, y + 20, pw, 34, 8, "input", "border")
    text(p, px + 12, y + 20, "Mixed: keep each song's own", 13, "faint", h=34)
    y = H - BAR_H - 92
    rect(p, px, y, pw, 30, 8, "accentSoft")
    text(p, px + 12, y, "2 fields will change on 11 songs", 12, "accentHi", 600, h=30, w=pw - 24)
    button(p, px, y + 42, "Revert", "ghost", "undo", w=pw * 0.42)
    button(p, px + pw * 0.46, y + 42, "Save to 11 files", "primary", "check", w=pw * 0.54)
    window_buttons(p)   # above the panel
    nowbar(p, seed=37, title="Lanternlight", artist="Mara Okafor — Salt & Ember", pos=0.55)


TIDE = [
    # file, track and title, artist, genre, year, path-match state (R3.9)
    ("01 - Neap Tide.flac", "1 · Neap Tide", "Lumen Drift", "Electronic", "2022", ("ok", "Match")),
    ("02 - Spring Tide.flac", "2 · Spring Tide", "Lumen Drift", "electronic", "2022", ("ok", "Match")),
    ("03 - Slack Water.flac", "3 · Slack Water", "Lumen Drift", "Electronic", "", ("warn", "Year missing")),
    ("04 - Moonpull.flac", "4 · Moonpull", "lumen drift", "Electronic", "2022", ("warn", "Artist case differs")),
    ("05 - Ebb.flac", "5 · Ebb", "Lumen Drift", "Electronica", "2022", ("ok", "Match")),
    ("06 - Perigee.flac", "6 · Perigee", "Lumen Drift", "Electronic", "2022", ("ok", "Match")),
    ("07 - Bore.flac", "7 · Bore", "Lumen Drift", "Electronic", "2022", ("ok", "Match")),
    ("08 - Tidal Lock.flac", "8 · Tidal Lock", "Lumen Drift", "Electronic", "2022", ("ok", "Match")),
    ("09 - High Water Mark.flac", "9 · High Water Mark", "Lumen Drift", "Electronic", "2022", ("ok", "Match")),
]


def l08_folder_songs(p):
    window(p)
    sidebar(p, "Folders")
    g = QLinearGradient(0, 0, 0, 300)
    g.setColorAt(0, col(art_colour(131), 0.30)); g.setColorAt(1, col("bg", 0.0))
    rect(p, SIDE_W, 0, W - SIDE_W, 300, 0, g)
    header(p, None, "9 songs", crumbs=["Lumen Drift", "Tide Tables"], search="Search folders", search_w=170,
           modes=FOLDER_MODES, mode=1, sort="Name")
    window_buttons(p)
    x0 = SIDE_W + 28
    cw = W - x0 - 28
    shadow(p, x0, 78, 140, 140, 12, 18)
    art(p, x0, 78, 140, 131, 12)
    tx = x0 + 164
    text(p, tx, 80, "FOLDER · 9 SONGS · 312 MB · FLAC", 11, "muted", 700)
    text(p, tx, 98, "Tide Tables", 30, "text", 800)
    text(p, tx, 142, "Cover from folder.jpg, not embedded", 12.5, "muted")
    bx = tx
    bx += button(p, bx, 174, "Infer from path", "primary", "wand") + 10
    bx += button(p, bx, 174, "Edit tags", "ghost", "genre") + 10
    bx += button(p, bx, 174, "Album art", "ghost", "image") + 10
    rect(p, bx, 174, 34, 34, 9, "surface", "borderStrong")
    icon(p, "more", bx + 17, 191, 16, "muted")
    cx = bx + 54
    cx += chip(p, cx, 180, "Art in folder only", "muted", "raised", ic="image") + 8
    chip(p, cx, 180, "Tags match path: 7 of 9", "warn", "warnSoft", ic="attention")
    rect(p, x0, 236, cw, 42, 10, "warnSoft")
    icon(p, "attention", x0 + 22, 257, 16, "warn")
    text(p, x0 + 40, 236, "The path says the album is from 2022, but 1 file has no year and 1 spells the artist in "
         "lower case.", 12.5, "warn", h=42, w=cw - 60)
    cols = [("FILE", x0 + 34, 210, "left"), ("TITLE", x0 + 256, 170, "left"), ("ARTIST", x0 + 436, 110, "left"),
            ("GENRE", x0 + 556, 100, "left"), ("YEAR", x0 + 664, 44, "left"), ("FROM PATH", x0 + 720, 160, "left")]
    table_header(p, x0, 292, cols, cw)
    for i, (fn, title, artist, genre, year, st) in enumerate(TIDE):
        y = 326 + i * 34
        if y > H - BAR_H - 34:
            break
        icon(p, "file", x0 + 16, y + 17, 14, "muted")
        text(p, x0 + 34, y, fn, 12.5, "text", h=34, w=210)
        text(p, x0 + 256, y, title, 12.5, "#c9cdd8", h=34, w=170)
        text(p, x0 + 436, y, artist, 12.5, "err" if artist.islower() else "#c9cdd8", h=34, w=110)
        text(p, x0 + 556, y, genre, 12.5, "warn" if genre != "Electronic" else "#c9cdd8", h=34, w=100)
        text(p, x0 + 664, y, year or "—", 12.5, "#c9cdd8" if year else "faint", h=34, w=44)
        chip(p, x0 + 720, y + 6, st[1], st[0], st[0] + "Soft", h=22, ic="check" if st[0] == "ok" else "attention",
             size=11)
    nowbar(p, seed=131, title="Neap Tide", artist="Lumen Drift — Tide Tables", pos=0.21)


def t01_infer(p):
    l08_folder_songs(p)
    w, h = 1040, 640
    x, y = dialog(p, w, h, "Infer tags from path",
                  "Read each file's path under ~/Music, and fill or correct its tags from it. Nothing is written until you save.")
    ix = x + 28
    iw = w - 56
    text(p, ix, y + 86, "Pattern", 11.5, "muted", 600)
    rect(p, ix, y + 106, iw - 190, 40, 9, "input", "accent", 1.3)
    tx = ix + 12
    for part in ("{artist}", "/", "{album}", "/", "{track}", " - ", "{title}"):
        if part.startswith("{"):
            ww = tw(part, 12.5, 600, mono=True) + 14
            rect(p, tx, y + 114, ww, 24, 6, "accentSoft")
            text(p, tx + 7, y + 114, part, 12.5, "accentHi", 600, h=24, mono=True)
            tx += ww + 3
        else:
            tx += text(p, tx, y + 114, part, 13, "muted", h=24, mono=True) + 3
    rect(p, ix + iw - 180, y + 106, 180, 40, 9, "surface", "border")
    text(p, ix + iw - 168, y + 106, "Detected · 9 of 9 fit", 12.5, "ok", 600, h=40)
    icon(p, "chev_down", ix + iw - 18, y + 126, 13, "muted")
    tx = ix
    text(p, tx, y + 152, "Tokens:", 11.5, "faint", h=22)
    tx += 56
    for tok in ("{artist}", "{albumartist}", "{album}", "{year}", "{disc}", "{track}", "{title}", "{genre}", "{*}"):
        tx += chip(p, tx, y + 152, tok, "muted", "raised", 22, size=11, weight=500) + 6
    # options
    oy = y + 190
    radio(p, ix, oy + 2, False); text(p, ix + 24, oy, "Only fill empty tags", 12.5, "#c9cdd8", h=20)
    radio(p, ix + 190, oy + 2, True); text(p, ix + 214, oy, "Correct tags that differ", 12.5, "text", 600, h=20)
    checkbox(p, ix + 420, oy + 2, True); text(p, ix + 444, oy, "Tidy case (lumen drift → Lumen Drift)", 12.5, "#c9cdd8", h=20)
    checkbox(p, ix + 720, oy + 2, True); text(p, ix + 744, oy, "Year from folder (2022)", 12.5, "#c9cdd8", h=20)
    # preview
    py = oy + 36
    cols = [("", ix + 8, 16, "left"), ("FILE", ix + 34, 210, "left"), ("ARTIST", ix + 254, 180, "left"),
            ("ALBUM", ix + 444, 130, "left"), ("#", ix + 584, 30, "left"), ("TITLE", ix + 624, 150, "left"),
            ("YEAR", ix + 784, 70, "left"), ("GENRE", ix + 862, 120, "left")]
    rect(p, ix, py, iw, 316, 10, "bg", "border")
    table_header(p, ix + 1, py + 1, cols, iw - 2)
    rows = [
        ("01 - Neap Tide.flac", ("Lumen Drift",), ("Tide Tables",), "1", ("Neap Tide",), ("2022",), ("Electronic",)),
        ("02 - Spring Tide.flac", ("Lumen Drift",), ("Tide Tables",), "2", ("Spring Tide",), ("2022",), ("electronic", "Electronic")),
        ("03 - Slack Water.flac", ("Lumen Drift",), ("Tide Tables",), "3", ("Slack Water",), ("", "2022"), ("Electronic",)),
        ("04 - Moonpull.flac", ("lumen drift", "Lumen Drift"), ("Tide Tables",), "4", ("Moonpull",), ("2022",), ("Electronic",)),
        ("05 - Ebb.flac", ("Lumen Drift",), ("Tide Tables",), "5", ("Ebb",), ("2022",), ("Electronica", "Electronic")),
        ("06 - Perigee.flac", ("Lumen Drift",), ("Tide Tables",), "6", ("Perigee",), ("2022",), ("Electronic",)),
    ]
    for i, r in enumerate(rows):
        yy = py + 36 + i * 37
        changed = any(len(v) == 2 for v in r[1:] if isinstance(v, tuple))
        checkbox(p, ix + 8, yy + 10, changed)
        text(p, ix + 34, yy, r[0], 12, "muted" if not changed else "text", h=36, w=210, mono=False)
        for (cx, cw), v in zip(((ix + 254, 180), (ix + 444, 130), (ix + 584, 30), (ix + 624, 150), (ix + 784, 70),
                                 (ix + 862, 120)), r[1:]):
            if isinstance(v, str):
                text(p, cx, yy, v, 12.5, "#c9cdd8", h=36, w=cw)
            elif len(v) == 1:
                text(p, cx, yy, v[0], 12.5, "#c9cdd8" if changed else "muted", h=36, w=cw)
            else:
                old, new = v
                if old:
                    ow = text(p, cx, yy + 1, old, 11, "err", h=16, w=cw)
                    line(p, cx, yy + 9.5, cx + ow, yy + 9.5, "err", 1)
                else:
                    text(p, cx, yy + 1, "(empty)", 11, "faint", h=16, w=cw)
                text(p, cx, yy + 17, new, 12.5, "ok", 600, h=18, w=cw)
        if i < len(rows) - 1:
            line(p, ix + 8, yy + 36.5, ix + iw - 8, yy + 36.5, "border")
    text(p, ix + 34, py + 316 - 34, "+ 3 more files, unchanged", 11.5, "faint", h=20)
    # footer
    fy = y + h - 62
    line(p, x, fy - 12, x + w, fy - 12, "border")
    text(p, ix, fy, "4 files · 4 changes · the old tags are kept, and Undo puts them back", 12.5, "muted", h=36)
    button(p, x + w - 28 - 170, fy, "Save 4 files", "primary", "check", w=170)
    button(p, x + w - 28 - 170 - 110, fy, "Cancel", "ghost", w=100)


def t02_album_art(p):
    l02_album(p)
    w, h = 900, 590
    x, y = dialog(p, w, h, "Album art · Glass Harbor",
                  "Choose one cover for the album. It is embedded in every song and saved beside them as cover.jpg.")
    ix = x + 28
    # current
    art(p, ix, y + 92, 250, 11, 12)
    text(p, ix, y + 352, "Current · 1200 × 1200 JPEG · 318 KB", 12, "muted", w=250)
    chip(p, ix, y + 378, "Embedded in 10 of 10", "ok", "okSoft", ic="check")
    # candidates
    cx = ix + 280
    text(p, cx, y + 92, "FOUND", 11, "faint", 700)
    cands = [(11, "cover.jpg in the folder", "1200 × 1200 · same as embedded", True),
             (211, "Embedded in 2 songs", "500 × 500 · lower resolution", False),
             (311, "back.png in the folder", "1400 × 1400 · named as a back cover", False)]
    for i, (seed, a, b, on) in enumerate(cands):
        yy = y + 116 + i * 78
        rect(p, cx, yy, w - 28 - (cx - x), 68, 10, "accentSoft" if on else "raised", "accent" if on else "border",
             1.4 if on else 1)
        art(p, cx + 10, yy + 9, 50, seed, 6)
        text(p, cx + 74, yy + 12, a, 13, "text", 600, w=360)
        text(p, cx + 74, yy + 34, b, 11.5, "muted", w=360)
        radio(p, x + w - 56, yy + 26, on)
    # drop zone
    dy = y + 116 + 3 * 78 + 6
    dw = w - 28 - (cx - x)
    rect(p, cx, dy, dw, 64, 10, col("accent", 0.05), "borderStrong", 1.2, dash=[5, 4])
    icon(p, "image", cx + 28, dy + 32, 20, "muted")
    text(p, cx + 48, dy + 12, "Drop an image here, paste it, or", 12.5, "#c9cdd8", h=20)
    fx = cx + 48 + text(p, cx + 48, dy + 32, "Choose file…", 12.5, "accentHi", 600, h=20)
    fx += text(p, fx, dy + 32, "  or  ", 12.5, "#c9cdd8", h=20)
    icon(p, "globe", fx + 8, dy + 42, 13, "accentHi")
    text(p, fx + 20, dy + 32, "Find online…", 12.5, "accentHi", 600, h=20)
    # options
    oy = y + h - 132
    checkbox(p, ix, oy + 2, True); text(p, ix + 24, oy, "Embed in every song of the album", 12.5, "text", h=20)
    checkbox(p, ix + 300, oy + 2, True); text(p, ix + 324, oy, "Save as cover.jpg in the folder", 12.5, "text", h=20)
    checkbox(p, ix, oy + 30, True); text(p, ix + 24, oy + 28, "Shrink to 1200 × 1200 before embedding", 12.5, "text", h=20)
    checkbox(p, ix + 300, oy + 30, False); text(p, ix + 324, oy + 28, "Remove other embedded images", 12.5, "#c9cdd8", h=20)
    fy = y + h - 62
    line(p, x, fy - 12, x + w, fy - 12, "border")
    text(p, ix, fy, "No change: the chosen cover is already on every song.", 12.5, "muted", h=36)
    button(p, x + w - 28 - 120, fy, "Done", "primary", w=120)


def p01_playlist_drag(p):
    window(p)
    sidebar(p, "", active_pl="Road Trip", drop_on="Evening Focus")
    window_buttons(p)
    x0 = SIDE_W + 28
    # mosaic of four covers
    for i, sd in enumerate((23, 83, 41, 127)):
        art(p, x0 + (i % 2) * 70, 24 + (i // 2) * 70, 70, sd, 0)
    rect(p, x0, 24, 140, 140, 12, None, col("#ffffff", 0.08))
    tx = x0 + 164
    text(p, tx, 34, "PLAYLIST · M3U8", 11, "muted", 700)
    text(p, tx, 54, "Road Trip", 34, "text", 800)
    text(p, tx, 104, "42 songs · 2 h 51 min · Playlists/Road Trip.m3u8 · relative paths", 12.5, "muted")
    bx = tx
    bx += button(p, bx, 130, "Play", "primary", "play", w=100) + 10
    bx += button(p, bx, 130, "Shuffle", "ghost", "shuffle") + 10
    bx += button(p, bx, 130, "Export…", "ghost", "file") + 10
    wt = W - x0 - 28
    ty = 186
    cols = [("", x0, 20, "left"), ("#", x0 + 22, 20, "right"), ("TITLE", x0 + 56, 260, "left"),
            ("ALBUM", x0 + 350, 200, "left"), ("GENRE", x0 + 570, 110, "left"), ("RATING", x0 + 700, 80, "left"),
            ("TIME", x0 + wt - 60, 50, "right")]
    table_header(p, x0, ty, cols, wt)
    rows = [("Northbound", "The Paper Lanterns", "Northbound Static", "Indie Rock", 4, "3:41", 23),
            ("Breakwater", "Hollow Coast", "Breakwater", "Alternative", 5, "4:12", 83),
            ("Low Orbit", "Kestrel Union", "Low Orbit", "Synthwave", 5, "4:26", 41),
            ("Afterlight", "Ghost Meridian", "Afterlight", "Post-Rock", 4, "7:58", 127),
            ("Signal Fires", "Lumen Drift", "Glass Harbor", "Electronic", 5, "4:18", 11),
            ("Paper Moons", "Saffron Avenue", "Paper Moons", "Pop", 3, "3:22", 139),
            ("Velvet Hours", "Juniper Sixes", "Velvet Hours", "Jazz", 4, "5:05", 71),
            ("Mile Markers", "The Paper Lanterns", "Northbound Static", "Indie Rock", 4, "3:58", 23)]
    sel = {1, 2, 3}
    for i, r in enumerate(rows):
        y = ty + 34 + i * 44
        if y > H - BAR_H - 40:
            break
        if i in sel:
            rect(p, x0 - 6, y + 1, wt + 12, 42, 7, col("sel", 0.55))
        if i == 5:  # the insertion line, where the drag would land in this list
            rect(p, x0 - 6, y - 1.5, wt + 12, 3, 1.5, "accent")
            rect(p, x0 - 10, y - 5, 10, 10, 5, "accent")
        icon(p, "drag", x0 + 8, y + 22, 13, "faint")
        text(p, x0 + 22, y, str(i + 1), 12.5, "muted", w=20, h=44, align="right")
        art(p, x0 + 56, y + 7, 30, r[6], 5)
        text(p, x0 + 96, y + 4, r[0], 13, "text", 500, w=230, h=20)
        text(p, x0 + 96, y + 22, r[1], 11.5, "muted", w=230, h=18)
        text(p, x0 + 350, y, r[2], 12.5, "#c9cdd8", w=200, h=44)
        text(p, x0 + 570, y, r[3], 12.5, "#c9cdd8", w=110, h=44)
        stars(p, x0 + 700, y + 22, r[4], r=4.6, gap=12)
        text(p, x0 + wt - 60, y, r[5], 12.5, "muted", w=50, h=44, align="right", mono=True)
    # the drag ghost: three songs on their way to Evening Focus in the sidebar
    gx, gy = 14, 404
    shadow(p, gx, gy, 220, 54, 12, 16)
    rect(p, gx + 8, gy + 8, 220, 54, 12, "raised", "borderStrong")
    rect(p, gx + 4, gy + 4, 220, 54, 12, "raised", "borderStrong")
    rect(p, gx, gy, 220, 54, 12, "hover", "accent", 1.3)
    art(p, gx + 9, gy + 9, 36, 83, 6)
    text(p, gx + 54, gy + 8, "3 songs", 13, "text", 600, h=20)
    text(p, gx + 54, gy + 27, "Breakwater, Low Orbit, …", 11.5, "muted", h=18, w=150)
    rect(p, gx + 196, gy - 9, 24, 20, 10, "accent")
    icon(p, "plus", gx + 208, gy + 1, 12, "#ffffff", 2.2)
    rect(p, gx + 24, gy + 66, 170, 26, 6, col("#000000", 0.8))
    text(p, gx + 24, gy + 66, "Add to Evening Focus", 11.5, "text", 600, w=170, h=26, align="center")
    nowbar(p, seed=23, title="Northbound", artist="The Paper Lanterns — Northbound Static", pos=0.81)


GENRES = [("Electronic", 214, 18, "accent"), ("Indie Rock", 187, 15, "cyan"), ("Jazz", 142, 13, "#f59e0b"),
          ("Alternative", 133, 11, "pink"), ("Folk", 96, 9, "#84cc16"), ("Soul", 88, 8, "#fb923c"),
          ("Ambient", 76, 7, "#38bdf8"), ("Synthwave", 64, 6, "#e879f9"), ("Post-Rock", 51, 5, "#94a3b8"),
          ("Classical", 47, 4, "#fcd34d"), ("Pop", 39, 4, "#f472b6")]


def g01_genres(p):
    window(p)
    sidebar(p, "Genres")
    header(p, "Genres", "24 genres", sort="Songs")
    window_buttons(p)
    x0 = SIDE_W + 28
    wt = W - x0 - 28
    # suggestion banner
    rect(p, x0, 74, wt, 64, 12, "accentSoft", col("accent", 0.4))
    icon(p, "merge", x0 + 26, 106, 20, "accentHi")
    text(p, x0 + 48, 82, "These look like one genre: Electronic (214), Electronica (17), electronic (6)", 13.5,
         "text", 600, w=wt - 280)
    text(p, x0 + 48, 104, "Merging rewrites the genre tag in 23 files. Undo puts them back.", 12, "muted", w=wt - 280)
    button(p, x0 + wt - 118, 89, "Review…", "primary", "merge", w=104)
    button(p, x0 + wt - 230, 89, "Not now", "quiet", w=100)
    # genre tiles
    cols, gw, gh, gap = 4, (wt - 3 * 16) / 4, 112, 16
    for i, (g, n, a, c) in enumerate(GENRES):
        r, k = divmod(i, cols)
        x = x0 + k * (gw + gap)
        y = 158 + r * (gh + gap)
        if y + gh > H - BAR_H - 4:
            break
        rect(p, x, y, gw, gh, 14, grad(x, y, x + gw, y + gh, [(0, col(c, 0.30)), (1, col(c, 0.06))]),
             col(c, 0.35) if i != 0 else "accent", 1.0 if i else 1.6)
        text(p, x + 18, y + 16, g, 17, "text", 700, w=gw - 80)
        text(p, x + 18, y + 44, f"{n} songs · {a} albums", 12, "muted", w=gw - 36)
        # three overlapping covers
        for j in range(3):
            art(p, x + 18 + j * 22, y + gh - 38, 26, (i * 7 + j * 13) % 97 + 5, 5)
        if i == 0:
            icon(p, "more", x + gw - 20, y + 22, 16, "text")
    # context menu for Electronic
    mx, my = x0 + gw - 26, 196
    shadow(p, mx, my, 220, 158, 10, 14)
    rect(p, mx, my, 220, 158, 10, "raised", "borderStrong")
    for i, (lab, ic) in enumerate((("Play all", "play"), ("Rename…", "genre"), ("Merge into…", "merge"),
                                   ("Select its songs", "check"))):
        yy = my + 8 + i * 36
        if i == 2:
            rect(p, mx + 6, yy, 208, 34, 7, "hover")
        icon(p, ic, mx + 24, yy + 17, 15, "muted")
        text(p, mx + 42, yy, lab, 13, "text", h=34)
    nowbar(p)


VIZ = (("Waveform", "wave"), ("3D analyzer", "cube"), ("No visualization", "nowave"))


DD_W, LY_W, EQ_W = 236, 100, 40
DD_X = W / 2 - (DD_W + 10 + LY_W + 10 + EQ_W) / 2   # the picker, the Lyrics switch and Equalizer, centred together


def np_top(p, on, menu=False, lyrics=False, eq=False):
    """Now Playing's own top row: back to the library, the visualization picker and the Lyrics switch (R11.4)."""
    text(p, 28, 18, "‹  Library", 13, "muted", 500)
    lab, ic = VIZ[on]
    dx, dw = DD_X, DD_W
    rect(p, dx, 16, dw, 34, 10, "accentSoft" if menu else "surface", "accent" if menu else "border")
    icon(p, ic, dx + 22, 33, 15, "accentHi")
    text(p, dx + 40, 16, lab, 13, "text", 600, h=34, w=dw - 70)
    icon(p, "chev_down", dx + dw - 20, 33, 14, "muted")
    lx = dx + dw + 10
    rect(p, lx, 16, LY_W, 34, 10, "accentSoft" if lyrics else "surface", "accent" if lyrics else "border")
    icon(p, "lyrics", lx + 22, 33, 15, "accentHi" if lyrics else "muted")
    text(p, lx + 38, 16, "Lyrics", 13, "text" if lyrics else "muted", 600, h=34)
    ex = lx + LY_W + 10   # the Equalizer button (R19.2)
    rect(p, ex, 16, EQ_W, 34, 10, "accentSoft" if eq else "surface", "accent" if eq else "border")
    icon(p, "eq", ex + EQ_W / 2, 33, 16, "accentHi" if eq else "muted")


def viz_menu(p, on):
    """The drop-down's menu, open; drawn last so it lies over the view."""
    dx, dw = DD_X, DD_W
    mh = 16 + 3 * 36
    shadow(p, dx, 56, dw, mh, 10, 14)
    rect(p, dx, 56, dw, mh, 10, "raised", "borderStrong")
    for i, (l2, i2) in enumerate(VIZ):
        yy = 64 + i * 36
        if i == 2:
            rect(p, dx + 6, yy, dw - 12, 34, 7, "hover")
        icon(p, i2, dx + 24, yy + 17, 15, "accentHi" if i == on else "muted")
        text(p, dx + 44, yy, l2, 13, "text", 600 if i == on else 400, h=34)
        if i == on:
            icon(p, "check", dx + dw - 24, yy + 17, 13, "accentHi", 2)


def n01_now_waveform(p):
    window(p)
    window_buttons(p)
    # backdrop tinted by the cover
    g = QRadialGradient(330, 300, 700)
    g.setColorAt(0, col("#0f3b57", 0.85)); g.setColorAt(0.6, col("#2b2450", 0.35)); g.setColorAt(1, col("bg", 0))
    rect(p, 0, 0, W, H - BAR_H, 0, g)
    np_top(p, 0)
    shadow(p, 96, 92, 330, 330, 16, 30)
    art(p, 96, 92, 330, 11, 16)
    tx = 476
    text(p, tx, 120, "NOW PLAYING · TRACK 4 OF 10", 11, "#b9e6f2", 700)
    text(p, tx, 142, "Signal Fires", 44, "text", 800)
    text(p, tx, 206, "Lumen Drift", 19, "text", 600)
    text(p, tx, 236, "Glass Harbor · 2019 · Electronic", 14, "muted")
    stars(p, tx, 280, 5, r=8, gap=21)
    cx = tx
    for c in ("FLAC", "16-bit / 44.1 kHz", "912 kbps", "ReplayGain −6.2 dB"):
        cx += chip(p, cx, 306, c, "muted", "raised", 24, size=11) + 8
    # up next
    qx = W - 300
    text(p, qx, 92, "UP NEXT", 11, "faint", 700)
    for i, t in enumerate(GLASS[4:9]):
        yy = 116 + i * 52
        art(p, qx, yy, 40, 11, 6)
        text(p, qx + 52, yy + 2, t, 13, "text", 500, w=210, h=18)
        text(p, qx + 52, yy + 20, "Lumen Drift · " + GLASS_LEN[i + 4], 11.5, "muted", w=210, h=18)
    # the big linear waveform
    wy, wh = 470, 150
    wx, ww = 96, W - 192
    rect(p, wx - 16, wy - 26, ww + 32, wh + 60, 16, col("surface", 0.6), "border")
    pos = 0.38
    waveform(p, wx, wy, ww, wh, pos, seed=11, bar=3, gap=1.6, dim="#2a2f3b")
    rect(p, wx + ww * pos - 1, wy - 12, 2, wh + 24, 1, "text")
    rect(p, wx + ww * pos - 26, wy - 30, 52, 20, 6, "text")
    text(p, wx + ww * pos - 26, wy - 30, "1:38", 11, "#0b0d11", 700, w=52, h=20, align="center", mono=True)
    for k, (lab, f) in enumerate((("0:00", 0.0), ("1:00", 60 / 258), ("2:00", 120 / 258), ("3:00", 180 / 258),
                                  ("4:00", 240 / 258))):
        text(p, wx + ww * f + 4, wy + wh + 8, lab, 10.5, "faint", 600, h=16)
        line(p, wx + ww * f, wy + wh + 4, wx + ww * f, wy + wh + 22, "borderStrong")
    nowbar(p, np_open=True)


def n02_now_3d(p):
    window(p)
    window_buttons(p)
    rect(p, 0, 0, W, H - BAR_H, 0, grad(0, 0, 0, H - BAR_H, [(0, "#0b0c12"), (1, "#141027")]))
    np_top(p, 1, menu=True)
    # the analyzer: spectrum slices receding in time, drawn back to front so nearer ones hide farther ones
    rnd = random.Random(5)
    rows, bins = 34, 96
    cx, base = W / 2, H - BAR_H - 70
    horizon = 150
    for r in range(rows - 1, -1, -1):
        z = r / (rows - 1)          # 0 = now (front), 1 = oldest (back)
        sc = 1.0 - 0.62 * z
        yb = base - (base - horizon) * (z ** 0.85)
        wid = (W - 140) * sc
        amp = 210 * sc
        pts = []
        for b in range(bins):
            f = b / (bins - 1)
            env = math.exp(-((f - 0.12) ** 2) / 0.006) * 0.95 + math.exp(-((f - 0.35) ** 2) / 0.01) * 0.6 \
                + math.exp(-((f - 0.62) ** 2) / 0.02) * 0.35 + 0.08
            pulse = 0.65 + 0.35 * math.sin(r * 0.55 + f * 9)
            v = env * pulse * (0.75 + 0.25 * rnd.random()) * (1 - 0.15 * f)
            pts.append(QPointF(cx - wid / 2 + f * wid, yb - v * amp))
        poly = QPolygonF([QPointF(cx - wid / 2, yb)] + pts + [QPointF(cx + wid / 2, yb)])
        c = QColor.fromHsvF((0.52 + 0.33 * z) % 1.0, 0.75, 1.0 - 0.45 * z)
        fill = QColor(c); fill.setAlphaF(0.10 + 0.12 * (1 - z))
        back = QColor("#0e0d18")
        p.setPen(Qt.NoPen); p.setBrush(back); p.drawPolygon(poly)
        p.setBrush(fill); p.drawPolygon(poly)
        p.setPen(QPen(c, 1.6 if r == 0 else 1.1)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts))
    # floor grid and axis labels
    for k, lab in enumerate(("32 Hz", "125", "500", "2 k", "8 k", "16 kHz")):
        x = cx - (W - 140) / 2 + k / 5 * (W - 140)
        text(p, x - 30, base + 10, lab, 11, "faint", w=60, align="center")
    text(p, W - 210, horizon - 26, "← 3 seconds ago", 11, "faint", w=150, align="right")
    text(p, 70, base + 34, "now", 11, "faint")
    # little overlay with the song
    rect(p, 28, 64, 300, 70, 12, col("surface", 0.75), "border")
    art(p, 40, 76, 46, 11, 6)
    text(p, 98, 78, "Signal Fires", 14, "text", 600, w=220)
    text(p, 98, 100, "Lumen Drift · Glass Harbor", 12, "muted", w=220)
    rect(p, W - 228, 64, 200, 34, 10, col("surface", 0.75), "border")
    text(p, W - 216, 64, "Bands: 96 · Speed: 1×", 12, "muted", h=34)
    icon(p, "gear", W - 46, 81, 15, "muted")
    viz_menu(p, 1)
    nowbar(p, np_open=True)


def cover_spectrum(p, x, y, sz, pos, r=16, bars=32):
    """Off mode's cover (R11.4.3): faint spectrum bars over its lower part, a thin progress line at its foot."""
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(x, y, sz, sz), r, r)
    p.setClipPath(clip)
    rect(p, x, y + sz * 0.55, sz, sz * 0.45, 0, grad(0, y + sz * 0.55, 0, y + sz, [(0, col("#000000", 0.0)),
                                                                                 (1, col("#000000", 0.35))]))
    rnd = random.Random(8)
    pad, gap = 14, 3
    bw = (sz - 2 * pad - (bars - 1) * gap) / bars
    base = y + sz - 10
    for i in range(bars):
        f = i / (bars - 1)
        env = math.exp(-((f - 0.12) ** 2) / 0.008) * 0.9 + math.exp(-((f - 0.4) ** 2) / 0.02) * 0.55 + 0.12
        v = min(1.0, env * (0.7 + 0.3 * rnd.random()) * (1 - 0.25 * f))
        bh = max(3, v * sz * 0.38)
        bx = pad + x + i * (bw + gap)
        rect(p, bx, base - bh, bw, bh, 1.5, grad(0, base - bh, 0, base, [(0, col("#ffffff", 0.16)),
                                                                          (1, col("#ffffff", 0.42))]))
    rect(p, x, y + sz - 3, sz, 3, 0, col("#000000", 0.45))
    rect(p, x, y + sz - 3, sz * pos, 3, 0, "progress")
    p.restore()
    rect(p, x, y, sz, sz, r, None, col("#ffffff", 0.06))


QUEUE = [
    # section, title, artist · album, time, cover seed
    ("PLAYED", "Small Hours", "Lumen Drift · Glass Harbor", "3:47", 11),
    ("NOW PLAYING", "Signal Fires", "Lumen Drift · Glass Harbor", "4:18", 11),
    ("NEXT · ADDED BY YOU", "Neap Tide", "Lumen Drift · Tide Tables", "4:31", 131),
    (None, "Lanternlight", "Mara Okafor · Salt & Ember", "5:06", 37),
    ("NEXT FROM GLASS HARBOR", "Undertow", "Lumen Drift · Glass Harbor", "6:03", 11),
    (None, "Parallax", "Lumen Drift · Glass Harbor", "3:55", 11),
    (None, "Lowlight", "Lumen Drift · Glass Harbor", "4:40", 11),
    (None, "Salt in the Wires", "Lumen Drift · Glass Harbor", "5:26", 11),
    (None, "Breakers", "Lumen Drift · Glass Harbor", "3:12", 11),
]


QUEUE_OUTSIDE = [
    # files opened from the system, outside the music root (R1.7.1)
    ("NOW PLAYING", "Harbor Lights", "Mara Okafor · Downloads", "4:52", 211),
    ("NEXT · OPENED WITH IT", "Tidewater", "Mara Okafor · Downloads", "3:38", 211),
    (None, "Low Beacon", "Mara Okafor · Downloads", "5:14", 211),
]


def n03_now_queue(p, outside=False):
    window(p)
    g = QRadialGradient(270, 300, 760)
    g.setColorAt(0, col("#0f3b57", 0.85)); g.setColorAt(0.6, col("#2b2450", 0.35)); g.setColorAt(1, col("bg", 0))
    rect(p, 0, 0, W, H - BAR_H, 0, g)
    window_buttons(p)
    np_top(p, 2)
    # the song: its cover with the spectrum and the progress line
    cx, cy, sz = 80, 82, 340
    shadow(p, cx, cy, sz, sz, 16, 30)
    art(p, cx, cy, sz, 211 if outside else 11, 16)
    cover_spectrum(p, cx, cy, sz, 0.38)
    if outside:   # a file opened from the system, outside the music root (R1.7.1)
        chip(p, cx, cy + sz + 18, "Not in your library", "warn", "warnSoft", 22, ic="attention", size=11)
        text(p, cx, cy + sz + 46, "Harbor Lights", 30, "text", 800, w=sz)
        text(p, cx, cy + sz + 90, "Mara Okafor", 17, "text", 600, w=sz)
        text(p, cx, cy + sz + 116, "~/Downloads/harbor-lights.flac", 12.5, "muted", w=sz, mono=True)
        button(p, cx, cy + sz + 146, "Add to library…", "ghost", "plus", w=170, h=32, size=12.5)
        chip(p, cx + 182, cy + sz + 151, "FLAC 24-bit / 48 kHz", "muted", "raised", 22, size=10.5)
    else:
        text(p, cx, cy + sz + 22, "NOW PLAYING · TRACK 4 OF 10", 11, "#b9e6f2", 700)
        text(p, cx, cy + sz + 40, "Signal Fires", 30, "text", 800, w=sz)
        text(p, cx, cy + sz + 84, "Lumen Drift", 17, "text", 600, w=sz)
        text(p, cx, cy + sz + 110, "Glass Harbor · 2019 · Electronic", 13, "muted", w=sz)
        stars(p, cx, cy + sz + 150, 5, r=7, gap=19)
        chip(p, cx + 116, cy + sz + 139, "FLAC 16-bit / 44.1 kHz", "muted", "raised", 22, size=10.5)
    # the queue, full size (R7.2)
    qx, qy = 480, 82
    qw, qh = W - qx - 40, H - BAR_H - qy - 22
    rect(p, qx, qy, qw, qh, 16, col("surface", 0.72), "border")
    ix, iw = qx + 24, qw - 48
    text(p, ix, qy + 18, "Queue", 18, "text", 700)
    text(p, ix, qy + 44, "Opened from Downloads · 2 up next · 9 min" if outside
         else "Playing from Glass Harbor · 7 up next · 33 min", 12, "muted")
    bx = qx + qw - 24
    bx -= button(p, bx - 74, qy + 22, "Clear", "quiet", w=74, h=32, size=12.5)
    button(p, bx - 168, qy + 22, "Save as playlist…", "ghost", "playlist", w=160, h=32, size=12.5)
    y = qy + 80
    for i, (sec, title, sub, length, seed) in enumerate(QUEUE_OUTSIDE if outside else QUEUE):
        if sec:
            y += 6 if i else 0
            text(p, ix, y, sec, 10.5, "faint", 700, h=20)
            y += 22
        now, played, hover = sec == "NOW PLAYING", sec == "PLAYED", title == "Lanternlight" and not outside
        if now:
            rect(p, ix - 10, y, iw + 20, 44, 10, "accentSoft")
        if hover:
            rect(p, ix - 10, y, iw + 20, 44, 10, "hover")
            icon(p, "drag", ix + 2, y + 22, 14, "muted")
        p.setOpacity(0.5 if played else 1.0)
        art(p, ix + 18, y + 5, 34, seed, 6)
        if now:
            rect(p, ix + 18, y + 5, 34, 34, 6, col("#000000", 0.45))
            for k, hh in enumerate((8, 14, 6)):
                rect(p, ix + 27 + k * 5, y + 29 - hh, 3, hh, 1, "#ffffff")
        text(p, ix + 64, y + 4, title, 13.5, "accentHi" if now else "text", 600 if now else 500, w=iw - 200, h=19)
        text(p, ix + 64, y + 23, sub, 12, "muted", w=iw - 200, h=17)
        text(p, ix + iw - 60, y, length, 12.5, "muted", w=46, h=44, align="right", mono=True)
        if hover:
            icon(p, "close", ix + iw - 2, y + 22, 13, "muted")
        p.setOpacity(1.0)
        y += 46
    if outside:
        nowbar(p, np_open=True, title="Harbor Lights", artist="Mara Okafor — not in your library", seed=211, pos=0.38)
    else:
        nowbar(p, np_open=True, sleep="23:40")


def n07_now_not_in_library(p):
    n03_now_queue(p, outside=True)


# ------------------------------------------------------------------ the mini player (R15)
def spectrum_values(n, seed=8):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        f = i / (n - 1)
        env = math.exp(-((f - 0.12) ** 2) / 0.008) * 0.9 + math.exp(-((f - 0.4) ** 2) / 0.02) * 0.55 + 0.12
        out.append(min(1.0, env * (0.7 + 0.3 * rnd.random()) * (1 - 0.25 * f)))
    return out


def theme_colour(f):
    """The visualizations' gradient (R6.2) at 0..1: cyan, violet, pink."""
    a, b = (col("cyan"), col("accent")) if f < 0.5 else (col("accent"), col("pink"))
    t = f * 2 if f < 0.5 else f * 2 - 1
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t, a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t)


def logo_tile(p, x, y, s=18):
    rect(p, x, y, s, s, s * 0.3, grad(x, y, x + s, y + s, [(0, "cyan"), (0.55, "accent"), (1, "pink")]))
    for i, hh in enumerate((0.35, 0.65, 0.45)):
        rect(p, x + s * (0.25 + i * 0.2), y + s * (0.5 - hh / 2), s * 0.1, s * hh, 1, "#ffffff")


def mini_window(p, x, y, w, h, r, fill="side"):
    shadow(p, x, y, w, h, r, 26)
    rect(p, x, y, w, h, r, fill, "borderStrong")


def mini_chrome(p, x, y, w, color="muted"):
    """Back to MusiKata on the left; stay on top and close on the right (R15.4)."""
    logo_tile(p, x + 12, y + 10, 18)
    icon(p, "pin", x + w - 46, y + 19, 14, color)
    icon(p, "close", x + w - 20, y + 19, 12, color)


def clip_round(p, x, y, w, h, r):
    c = QPainterPath()
    c.addRoundedRect(QRectF(x, y, w, h), r, r)
    p.setClipPath(c, Qt.IntersectClip if p.hasClipping() else Qt.ReplaceClip)


def mini_strip(p, x, y, w=496, h=76):
    """1 · Strip: the smallest, a single row."""
    mini_window(p, x, y, w, h, 14)
    art(p, x + 10, y + 10, 56, 11, 9)
    text(p, x + 78, y + 15, "Signal Fires", 14, "text", 600, w=168)
    text(p, x + 78, y + 37, "Lumen Drift · Glass Harbor", 12, "muted", w=168)
    for i, v in enumerate(spectrum_values(10)):
        bh = max(4, v * 24)
        rect(p, x + 262 + i * 5, y + 40 - bh, 3, bh, 1.5, theme_colour(i / 9))
    text(p, x + 262, y + 44, "1:38", 10.5, "muted", mono=True, h=16)
    icon(p, "prev", x + 352, y + 38, 15, "text")
    rect(p, x + 375, y + 21, 34, 34, 17, "text")
    icon(p, "pause", x + 392, y + 38, 15, "#0b0d11")
    icon(p, "next", x + 432, y + 38, 15, "text")
    icon(p, "close", x + w - 20, y + 20, 12, "muted")
    icon(p, "pin", x + w - 20, y + 54, 13, "accentHi")
    p.save()
    clip_round(p, x, y, w, h, 14)
    rect(p, x, y + h - 3, w, 3, 0, col("#000000", 0.4))
    rect(p, x, y + h - 3, w * 0.38, 3, 0, grad(x, 0, x + w * 0.38, 0, [(0, "cyan"), (0.6, "accent"), (1, "pink")]))
    p.restore()


def mini_cover(p, x, y, s=300):
    """2 · Cover: the art edge to edge, shown here under the pointer with its controls."""
    shadow(p, x, y, s, s, 16, 26)
    art(p, x, y, s, 11, 16)
    p.save()
    clip_round(p, x, y, s, s, 16)
    rect(p, x, y + s * 0.4, s, s * 0.6, 0, grad(0, y + s * 0.4, 0, y + s, [(0, col("#000000", 0.0)),
                                                                           (1, col("#000000", 0.82))]))
    vals = spectrum_values(28, 9)
    bw = (s - 28 - 27 * 3) / 28
    for i, v in enumerate(vals):
        bh = max(3, v * s * 0.3)
        rect(p, x + 14 + i * (bw + 3), y + s - 8 - bh, bw, bh, 1.5, col("#ffffff", 0.16))
    rect(p, x, y + s - 3, s, 3, 0, col("#000000", 0.5))
    rect(p, x, y + s - 3, s * 0.38, 3, 0, "progress")
    p.restore()
    rect(p, x, y, s, s, 16, None, col("#ffffff", 0.08))
    rect(p, x + s - 66, y + 8, 58, 24, 12, col("#000000", 0.45))
    icon(p, "pin", x + s - 50, y + 20, 13, "#ffffff")
    icon(p, "close", x + s - 24, y + 20, 11, "#ffffff")
    logo_tile(p, x + 10, y + 10, 20)
    text(p, x + 18, y + s - 84, "Signal Fires", 18, "#ffffff", 700, w=s - 140)
    text(p, x + 18, y + s - 58, "Lumen Drift · Glass Harbor", 12, col("#ffffff", 0.72), w=s - 140)
    icon(p, "prev", x + s - 100, y + s - 42, 15, "#ffffff")
    rect(p, x + s - 80, y + s - 60, 36, 36, 18, "#ffffff")
    icon(p, "pause", x + s - 62, y + s - 42, 15, "#111111")
    icon(p, "next", x + s - 24, y + s - 42, 15, "#ffffff")


def mini_card(p, x, y, w=300, cover=True, up_next=True):
    """3 · Card: everything about the song, upright. 6 · Details: the same without the cover or up next."""
    cs = w - 32
    top = y + 44 + (cs + 14 if cover else 0)
    h = top - y + 196 + (60 if up_next else 0)
    mini_window(p, x, y, w, h, 18, "surface")
    p.save()
    clip_round(p, x, y, w, h, 18)
    rect(p, x, y, w, h * 0.7, 0, grad(0, y, 0, y + h * 0.7, [(0, col(art_colour(11), 0.32)), (1, col("surface", 0.0))]))
    p.restore()
    mini_chrome(p, x, y, w)
    if cover:
        shadow(p, x + 16, y + 44, cs, cs, 12, 14)
        art(p, x + 16, y + 44, cs, 11, 12)
    yy = top
    text(p, x + 16, yy, "TRACK 4 OF 10 · GLASS HARBOR", 10.5, "#b9e6f2", 700, w=cs)
    text(p, x + 16, yy + 18, "Signal Fires", 21, "text", 800, w=cs - 80)
    stars(p, x + w - 16 - 5 * 13, yy + 34, 5, r=5, gap=13)
    text(p, x + 16, yy + 50, "Lumen Drift · 2019 · Electronic", 12.5, "muted", w=cs)
    waveform(p, x + 16, yy + 82, cs, 26, 0.38, seed=11, bar=2, gap=1.2)
    rect(p, x + 16 + cs * 0.38 - 1, yy + 78, 2, 34, 1, "text")
    text(p, x + 16, yy + 112, "1:38", 10.5, "muted", mono=True, h=14)
    text(p, x + w - 66, yy + 112, "4:18", 10.5, "muted", mono=True, h=14, w=50, align="right")
    cy, cx = yy + 152, x + w / 2
    icon(p, "shuffle", cx - 92, cy, 16, "accentHi")
    icon(p, "prev", cx - 46, cy, 17, "text")
    rect(p, cx - 20, cy - 20, 40, 40, 20, "text")
    icon(p, "pause", cx, cy, 17, "#0b0d11")
    icon(p, "next", cx + 46, cy, 17, "text")
    icon(p, "repeat", cx + 92, cy, 16, "muted")
    if up_next:
        uy = y + h - 44
        line(p, x + 16, uy - 10, x + w - 16, uy - 10, "border")
        art(p, x + 16, uy, 28, 11, 5)
        text(p, x + 54, uy, "UP NEXT", 9.5, "faint", 700, h=14)
        text(p, x + 54, uy + 13, "Undertow · Lumen Drift", 12, "#c9cdd8", w=cs - 90, h=16)
        text(p, x + w - 66, uy + 6, "6:03", 11, "muted", mono=True, w=50, align="right", h=16)
    return h


def mini_remote(p, x, y, w=246, h=76):
    """7 · Remote: the right half of the Strip, only the spectrum, time and controls."""
    mini_window(p, x, y, w, h, 14)
    for i, v in enumerate(spectrum_values(10)):
        bh = max(4, v * 24)
        rect(p, x + 16 + i * 5, y + 40 - bh, 3, bh, 1.5, theme_colour(i / 9))
    text(p, x + 16, y + 44, "1:38", 10.5, "muted", mono=True, h=16)
    icon(p, "prev", x + 102, y + 38, 15, "text")
    rect(p, x + 125, y + 21, 34, 34, 17, "text")
    icon(p, "pause", x + 142, y + 38, 15, "#0b0d11")
    icon(p, "next", x + 182, y + 38, 15, "text")
    icon(p, "close", x + w - 20, y + 20, 12, "muted")
    icon(p, "pin", x + w - 20, y + 54, 13, "accentHi")
    p.save()
    clip_round(p, x, y, w, h, 14)
    rect(p, x, y + h - 3, w, 3, 0, col("#000000", 0.4))
    rect(p, x, y + h - 3, w * 0.38, 3, 0, grad(x, 0, x + w * 0.38, 0, [(0, "cyan"), (0.6, "accent"), (1, "pink")]))
    p.restore()


def mini_analyzer(p, x, y, w=496, h=170):
    """4 · Analyzer: a small 3D analyzer (R11.3), the song over it."""
    mini_window(p, x, y, w, h, 14, "#0c0b14")
    p.save()
    clip_round(p, x, y, w, h, 14)
    rect(p, x, y, w, h, 0, grad(0, y, 0, y + h, [(0, "#0b0c12"), (1, "#16112b")]))
    rnd = random.Random(5)
    rows, bins = 16, 56
    cx, base, horizon = x + w / 2, y + h - 14, y + 34
    for r in range(rows - 1, -1, -1):
        z = r / (rows - 1)
        sc = 1.0 - 0.55 * z
        yb = base - (base - horizon) * (z ** 0.85)
        wid, amp = (w - 24) * sc, 74 * sc
        pts = []
        for b in range(bins):
            f = b / (bins - 1)
            env = math.exp(-((f - 0.12) ** 2) / 0.006) * 0.95 + math.exp(-((f - 0.35) ** 2) / 0.01) * 0.6 \
                + math.exp(-((f - 0.62) ** 2) / 0.02) * 0.35 + 0.08
            v = env * (0.65 + 0.35 * math.sin(r * 0.7 + f * 9)) * (0.75 + 0.25 * rnd.random()) * (1 - 0.15 * f)
            pts.append(QPointF(cx - wid / 2 + f * wid, yb - v * amp))
        poly = QPolygonF([QPointF(cx - wid / 2, yb)] + pts + [QPointF(cx + wid / 2, yb)])
        c = QColor.fromHsvF((0.52 + 0.33 * z) % 1.0, 0.75, 1.0 - 0.45 * z)
        fill = QColor(c); fill.setAlphaF(0.10 + 0.12 * (1 - z))
        p.setPen(Qt.NoPen); p.setBrush(QColor("#0e0d18")); p.drawPolygon(poly)
        p.setBrush(fill); p.drawPolygon(poly)
        p.setPen(QPen(c, 1.4 if r == 0 else 1.0)); p.setBrush(Qt.NoBrush); p.drawPolyline(QPolygonF(pts))
    rect(p, x, y + h - 2, w * 0.38, 2, 0, grad(x, 0, x + w * 0.38, 0, [(0, "cyan"), (0.6, "accent"), (1, "pink")]))
    p.restore()
    rect(p, x + 10, y + 10, 236, 50, 12, col("#0b0d11", 0.72), "border")
    art(p, x + 17, y + 17, 36, 11, 6)
    text(p, x + 62, y + 15, "Signal Fires", 13, "text", 600, w=176, h=20)
    text(p, x + 62, y + 34, "Lumen Drift · Glass Harbor", 11, "muted", w=176, h=18)
    icon(p, "pin", x + w - 46, y + 20, 13, "muted")
    icon(p, "close", x + w - 20, y + 20, 11, "muted")
    rect(p, x + w - 128, y + h - 52, 116, 40, 20, col("#0b0d11", 0.72), "border")
    icon(p, "prev", x + w - 104, y + h - 32, 14, "text")
    rect(p, x + w - 86, y + h - 47, 30, 30, 15, "text")
    icon(p, "pause", x + w - 71, y + h - 32, 13, "#0b0d11")
    icon(p, "next", x + w - 36, y + h - 32, 14, "text")


def mini_disc(p, x, y, w=240, h=320):
    """5 · Disc: the cover as a disc, the spectrum around it, a progress ring."""
    mini_window(p, x, y, w, h, 22, "side")
    cx, cy, R = x + w / 2, y + 116, 74
    vals = spectrum_values(72, 12)
    for i, v in enumerate(vals + vals[::-1][:0]):
        a = -math.pi / 2 + i / len(vals) * 2 * math.pi
        r0, r1 = R + 13, R + 13 + 3 + v * 16
        p.setPen(QPen(theme_colour(i / (len(vals) - 1)), 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
                   QPointF(cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(col("borderStrong"), 3))
    p.drawEllipse(QPointF(cx, cy), R + 6, R + 6)
    p.setPen(QPen(col("progress"), 3, Qt.SolidLine, Qt.RoundCap))
    p.drawArc(QRectF(cx - R - 6, cy - R - 6, 2 * R + 12, 2 * R + 12), 90 * 16, int(-0.38 * 360 * 16))
    p.save()
    disc = QPainterPath()
    disc.addEllipse(QPointF(cx, cy), R, R)
    p.setClipPath(disc)
    art(p, cx - R, cy - R, 2 * R, 11, 0, border=False)
    p.setBrush(Qt.NoBrush)
    for k in range(3):
        p.setPen(QPen(col("#000000", 0.18), 1)); p.drawEllipse(QPointF(cx, cy), R * (0.55 + k * 0.14), R * (0.55 + k * 0.14))
    p.restore()
    rect(p, cx - 15, cy - 15, 30, 30, 15, col("#000000", 0.35))
    rect(p, cx - 6, cy - 6, 12, 12, 6, "side")
    icon(p, "pin", x + w - 46, y + 20, 13, "muted")
    icon(p, "close", x + w - 20, y + 20, 11, "muted")
    logo_tile(p, x + 12, y + 11, 18)
    text(p, x, y + 220, "Signal Fires", 16, "text", 700, w=w, align="center")
    text(p, x, y + 244, "Lumen Drift · Glass Harbor", 12, "muted", w=w, align="center")
    icon(p, "prev", cx - 46, y + 288, 15, "text")
    rect(p, cx - 18, y + 270, 36, 36, 18, "text")
    icon(p, "pause", cx, y + 288, 15, "#0b0d11")
    icon(p, "next", cx + 46, y + 288, 15, "text")


def desktop(p):
    """The desktop a mini player floats on, MusiKata's own window minimized."""
    rect(p, 0, 0, W, H, 0, grad(0, 0, W, H, [(0, "#161b2b"), (1, "#0a0c12")]))
    for gx, gy, rr, c, a in ((260, 640, 560, "accent", 0.10), (1060, 140, 480, "cyan", 0.07)):
        g = QRadialGradient(gx, gy, rr); g.setColorAt(0, col(c, a)); g.setColorAt(1, col(c, 0.0))
        rect(p, 0, 0, W, H, 0, g)


MINI_LAYOUTS = ("Strip", "Cover", "Card", "Analyzer", "Disc", "Details", "Remote")


def m01_mini_players(p):
    desktop(p)

    def label(x, y, n, name, what, w):
        tx = x + text(p, x, y, f"{n}  {name}", 13, "text", 700)
        text(p, tx + 10, y + 1, what, 11.5, "muted", w=w - (tx - x) - 10)

    label(56, 34, 3, "Card", "track, rating, waveform, up next", 300)
    mini_card(p, 56, 62)
    label(392, 34, 2, "Cover", "the art edge to edge, the spectrum over it", 310)
    mini_cover(p, 392, 62)
    label(392, 392, 6, "Details", "the Card without art or up next", 310)
    mini_card(p, 392, 420, cover=False, up_next=False)
    label(728, 34, 4, "Analyzer", "a small 3D analyzer, the song over it", 496)
    mini_analyzer(p, 728, 62)
    label(728, 270, 1, "Strip", "the smallest: one row, a tiny spectrum, the progress under it", 496)
    mini_strip(p, 728, 298)
    label(728, 412, 7, "Remote", "the Strip's right half", 246)
    mini_remote(p, 728, 440)
    label(984, 412, 5, "Disc", "progress ring, spectrum rays", 240)
    mini_disc(p, 984, 440)


def m02_mini_player_menu(p):
    desktop(p)
    # someone else's windows, plain shapes, under the mini player
    for wx, wy, ww, wh in ((90, 70, 640, 430), (520, 210, 560, 360)):
        shadow(p, wx, wy, ww, wh, 10, 20)
        rect(p, wx, wy, ww, wh, 10, "#1a1d24", "#2a2e38")
        rect(p, wx, wy, ww, 34, 10, "#20242c")
        rect(p, wx, wy + 24, ww, 10, 0, "#20242c")
        for k in range(3):
            rect(p, wx + 14 + k * 18, wy + 12, 10, 10, 5, "#3a3f4b")
        for k in range(7):
            rect(p, wx + 28, wy + 62 + k * 34, (ww - 56) * (0.9 - 0.08 * (k % 4)), 10, 5, "#272b34")
    # the Remote in the screen's corner, its right-click menu open above it
    rx, ry = W - 24 - 246, H - 24 - 76
    mini_remote(p, rx, ry)
    mw = 236
    items = [("LAYOUT", None)] + [(n, n == "Remote") for n in MINI_LAYOUTS] + \
        [("-", None), ("Sleep timer", None), ("Stay on top", True), ("Show MusiKata", None), ("Close mini player", None)]
    mh = 16 + sum(22 if a == "LAYOUT" else 9 if a == "-" else 30 for a, _ in items)
    mx, my = rx + 246 - mw - 6, ry - mh - 8
    shadow(p, mx, my, mw, mh, 10, 14)
    rect(p, mx, my, mw, mh, 10, "raised", "borderStrong")
    yy = my + 8
    for lab, on in items:
        if lab == "LAYOUT":
            text(p, mx + 14, yy, lab, 10, "faint", 700, h=22); yy += 22; continue
        if lab == "-":
            line(p, mx + 8, yy + 4.5, mx + mw - 8, yy + 4.5, "borderStrong"); yy += 9; continue
        if lab == "Details":
            rect(p, mx + 6, yy, mw - 12, 30, 7, "hover")
        if on:
            icon(p, "check", mx + 22, yy + 15, 13, "accentHi", 2)
        text(p, mx + 40, yy, lab, 13, "text", h=30)
        n = MINI_LAYOUTS.index(lab) + 1 if lab in MINI_LAYOUTS else None
        if n:
            text(p, mx + mw - 40, yy, str(n), 11, "faint", h=30, w=26, align="right", mono=True)
        if lab == "Show MusiKata":
            text(p, mx + mw - 110, yy, "Ctrl+Shift+M", 11, "faint", h=30, w=98, align="right")
        if lab == "Sleep timer":   # R7.10: its time left, and its choices in a submenu
            icon(p, "moon", mx + 22, yy + 15, 13, "accentHi")
            text(p, mx + mw - 96, yy, "23:40", 11, "accentHi", 600, h=30, w=60, align="right", mono=True)
            icon(p, "chev_right", mx + mw - 22, yy + 15, 12, "faint")
        yy += 30
    # the tooltip that names the song, since the Remote doesn't
    tx, ty = rx - 236, ry + 22
    rect(p, tx, ty, 222, 34, 8, "raised", "borderStrong")
    text(p, tx + 12, ty, "Signal Fires — Lumen Drift", 12, "text", h=34, w=200)


# ------------------------------------------------------------------ online lookups (R16) and lyrics (R17)
def sends_line(p, x, y, w, what):
    """The footer line every lookup dialog has: what it sends, and to whom (R16.3)."""
    icon(p, "globe", x + 8, y + 18, 14, "faint")
    text(p, x + 22, y, what, 11.5, "faint", h=36, w=w - 22)


def t04_find_cover(p):
    l07_folders_list(p)
    w, h = 960, 586
    x, y = dialog(p, w, h, "Album art · Kindling",
                  "Mara Okafor · 10 songs. Nothing in the folder or the songs; these were found online.")
    ix = x + 28
    no_art(p, ix, y + 92, 220, 12)
    text(p, ix, y + 322, "Current · none", 12, "muted", w=220)
    chip(p, ix, y + 348, "No cover", "warn", "warnSoft", ic="image")
    cx = ix + 250
    cw = x + w - 28 - cx
    text(p, cx, y + 92, "FOUND ONLINE · MUSICBRAINZ AND THE COVER ART ARCHIVE", 11, "faint", 700, w=cw)
    cands = [(149, "Kindling", "2015 · GB · CD", "1200 × 1200", True, "Best match"),
             (157, "Kindling", "2015 · US · Digital", "3000 × 3000", False, None),
             (163, "Kindling (Deluxe)", "2016 · GB · CD", "1500 × 1500", False, "12 tracks"),
             (167, "Kindling", "2015 · DE · Vinyl", "1000 × 1000", False, None)]
    tw_ = (cw - 3 * 14) / 4
    for i, (seed, name, rel, size, on, badge) in enumerate(cands):
        tx = cx + i * (tw_ + 14)
        ty = y + 116
        if on:
            rect(p, tx - 5, ty - 5, tw_ + 10, tw_ + 10, 13, None, "accent", 2)
        art(p, tx, ty, tw_, seed, 10)
        if badge:
            chip(p, tx + 8, ty + 8, badge, "#ffffff", col("#000000", 0.6), 20, size=10.5)
        radio(p, tx + tw_ - 26, ty + tw_ - 26, on)
        text(p, tx, ty + tw_ + 10, name, 13, "text", 600, w=tw_)
        text(p, tx, ty + tw_ + 30, rel, 11.5, "muted", w=tw_)
        text(p, tx, ty + tw_ + 48, size, 11.5, "faint", w=tw_, mono=True)
    dy = y + 116 + tw_ + 84
    rect(p, cx, dy, cw, 52, 10, col("accent", 0.05), "borderStrong", 1.2, dash=[5, 4])
    icon(p, "image", cx + 26, dy + 26, 18, "muted")
    text(p, cx + 46, dy, "Drop an image here, paste it, or", 12.5, "#c9cdd8", h=52)
    text(p, cx + 46 + tw("Drop an image here, paste it, or ", 12.5), dy, "Choose file…", 12.5, "accentHi", 600, h=52)
    oy = y + h - 132
    checkbox(p, ix, oy + 2, True); text(p, ix + 24, oy, "Embed in every song of the album", 12.5, "text", h=20)
    checkbox(p, ix + 300, oy + 2, True); text(p, ix + 324, oy, "Save as cover.jpg in the folder", 12.5, "text", h=20)
    checkbox(p, ix, oy + 30, True); text(p, ix + 24, oy + 28, "Shrink to 1200 × 1200 before embedding", 12.5, "text", h=20)
    fy = y + h - 62
    line(p, x, fy - 12, x + w, fy - 12, "border")
    sends_line(p, ix, fy, 520, "Sent: the album artist and title to musicbrainz.org; the release's id to coverartarchive.org")
    button(p, x + w - 28 - 150, fy, "Save cover", "primary", "check", w=150)
    button(p, x + w - 28 - 260, fy, "Cancel", "ghost", w=100)


def t05_look_up_tags(p):
    l08_folder_songs(p)
    w, h = 1040, 640
    x, y = dialog(p, w, h, "Look up tags · Tide Tables",
                  "Releases on MusicBrainz that fit the 9 songs of this album. Nothing is written until you save.")
    ix, iw = x + 28, w - 56
    text(p, ix, y + 86, "RELEASES", 11, "faint", 700)
    rels = [("Tide Tables", "Lumen Drift · 2022 · Digital · Glasswork Records · 9 tracks", "9 of 9 songs · lengths within 2 s", "ok", True),
            ("Tide Tables (Deluxe Edition)", "Lumen Drift · 2023 · Digital · Glasswork Records · 12 tracks", "9 of 12 tracks · 3 extra", "warn", False),
            ("Tide Tables", "Lumen Drift · 2022 · GB · Vinyl · 9 tracks", "9 of 9 songs · 2 in another order", "warn", False)]
    for i, (t, sub, fit, st, on) in enumerate(rels):
        ry = y + 108 + i * 48
        rect(p, ix, ry, iw, 44, 9, "accentSoft" if on else "raised", "accent" if on else "border", 1.4 if on else 1)
        radio(p, ix + 14, ry + 14, on)
        text(p, ix + 42, ry, t, 13, "text", 600, h=44, w=230)
        text(p, ix + 280, ry, sub, 12, "muted", h=44, w=420)
        chip(p, ix + iw - 16 - tw(fit, 11, 600) - 34, ry + 11, fit, st, st + "Soft", 22, ic="check" if st == "ok" else "attention", size=11)
    oy = y + 262
    radio(p, ix, oy + 2, False); text(p, ix + 24, oy, "Only fill empty tags", 12.5, "#c9cdd8", h=20)
    radio(p, ix + 190, oy + 2, True); text(p, ix + 214, oy, "Correct tags that differ", 12.5, "text", 600, h=20)
    checkbox(p, ix + 420, oy + 2, True); text(p, ix + 444, oy, "Keep my genres", 12.5, "text", h=20)
    checkbox(p, ix + 590, oy + 2, True); text(p, ix + 614, oy, "Save MusicBrainz ids", 12.5, "text", h=20)
    ty = y + 296
    rect(p, ix, ty, iw, 268, 10, "input", "border")
    cols = [("FILE", ix + 40, 200, "left"), ("#", ix + 250, 24, "right"), ("TITLE", ix + 290, 200, "left"),
            ("ARTIST", ix + 500, 160, "left"), ("YEAR", ix + 670, 60, "left"), ("LENGTH · ON RELEASE", ix + 760, 180, "left")]
    for lab, cx_, cw_, al in cols:
        text(p, cx_, ty + 4, lab, 11, "faint", 700, w=cw_, h=28, align=al)
    line(p, ix, ty + 32, ix + iw, ty + 32, "border")
    rows = [("01 - Neap Tide.flac", "1", ("Neap Tide",), ("Lumen Drift",), ("2022",), "4:31 · 4:31", False),
            ("03 - Slack Water.flac", "3", ("Slack Water",), ("Lumen Drift",), ("(empty)", "2022"), "5:02 · 5:01", True),
            ("04 - Moonpull.flac", "4", ("Moonpull",), ("lumen drift", "Lumen Drift"), ("2022",), "4:44 · 4:44", True),
            ("07 - Bore.flac", "7", ("Bore", "Tidal Bore"), ("Lumen Drift",), ("2022",), "3:49 · 3:50", True)]
    for i, (fn, n, title, artist, year, length, on) in enumerate(rows):
        ry = ty + 34 + i * 46
        if i:
            line(p, ix + 10, ry, ix + iw - 10, ry, "border")
        checkbox(p, ix + 14, ry + 15, on)
        text(p, ix + 40, ry, fn, 12.5, "text" if on else "muted", h=46, w=200)
        text(p, ix + 250, ry, n, 12.5, "muted", h=46, w=24, align="right")
        for vals, cx_, cw_ in ((title, ix + 290, 200), (artist, ix + 500, 160), (year, ix + 670, 80)):
            if len(vals) == 1:
                text(p, cx_, ry, vals[0], 12.5, "#c9cdd8", h=46, w=cw_)
            else:
                old, new = vals
                ow = text(p, cx_, ry + 4, old, 11.5, "err" if old != "(empty)" else "faint", h=18, w=cw_)
                if old != "(empty)":
                    line(p, cx_, ry + 13.5, cx_ + ow, ry + 13.5, "err", 1.2)
                text(p, cx_, ry + 22, new, 13, "ok", 600, h=20, w=cw_)
        text(p, ix + 760, ry, length, 12, "faint", h=46, w=130, mono=True)
    text(p, ix + 40, ty + 34 + 4 * 46 + 12, "+ 5 more songs, unchanged", 12, "faint", h=24)
    fy = y + h - 62
    line(p, x, fy - 12, x + w, fy - 12, "border")
    sends_line(p, ix, fy, 420, "Sent: the album artist and title to musicbrainz.org")
    text(p, ix + 440, fy, "3 files · 3 changes · Undo puts them back", 12.5, "muted", h=36)
    button(p, x + w - 28 - 150, fy, "Save 3 files", "primary", "check", w=150)
    button(p, x + w - 28 - 260, fy, "Cancel", "ghost", w=100)


LYRICS = [  # made up for the mockup; "Signal Fires" by Lumen Drift isn't a real song
    ("1:05", "Lanterns on the water line", -2),
    ("1:11", "counting ships that never came", -2),
    ("1:18", "every harbour keeps a light", -1),
    ("1:24", "every light a different name", -1),
    ("1:31", "We were signal fires, burning on the shore", 0),
    ("1:38", "calling out to no one, calling out for more", 1),
    ("1:45", "and the tide came in to take the words away", 1),
    ("1:52", "still I kept the embers for another day", 1),
    ("2:04", "Salt across the windows", 2),
    ("2:10", "static on the line", 2),
    ("2:16", "every wave a question", 2),
]


def n04_now_lyrics(p):
    window(p)
    g = QRadialGradient(270, 300, 760)
    g.setColorAt(0, col("#0f3b57", 0.85)); g.setColorAt(0.6, col("#2b2450", 0.35)); g.setColorAt(1, col("bg", 0))
    rect(p, 0, 0, W, H - BAR_H, 0, g)
    window_buttons(p)
    np_top(p, 2, lyrics=True)
    cx, cy, sz = 80, 82, 340
    shadow(p, cx, cy, sz, sz, 16, 30)
    art(p, cx, cy, sz, 11, 16)
    cover_spectrum(p, cx, cy, sz, 0.38)
    text(p, cx, cy + sz + 22, "NOW PLAYING · TRACK 4 OF 10", 11, "#b9e6f2", 700)
    text(p, cx, cy + sz + 40, "Signal Fires", 30, "text", 800, w=sz)
    text(p, cx, cy + sz + 84, "Lumen Drift", 17, "text", 600, w=sz)
    text(p, cx, cy + sz + 110, "Glass Harbor · 2019 · Electronic", 13, "muted", w=sz)
    stars(p, cx, cy + sz + 150, 5, r=7, gap=19)
    qx, qy = 480, 82
    qw, qh = W - qx - 40, H - BAR_H - qy - 22
    rect(p, qx, qy, qw, qh, 16, col("surface", 0.55), "border")
    ix, iw = qx + 32, qw - 64
    text(p, ix, qy + 18, "Lyrics", 18, "text", 700)
    chip(p, ix, qy + 46, "Timed · from 04 - Signal Fires.lrc", "muted", "raised", 22, ic="check", size=11)
    bx = qx + qw - 24
    bx -= button(p, bx - 96, qy + 22, "Edit…", "ghost", w=96, h=32, size=12.5) + 8
    button(p, bx - 140, qy + 22, "Find online…", "quiet", "globe", w=140, h=32, size=12.5)
    p.save()
    p.setClipRect(QRectF(qx, qy + 86, qw, qh - 96))
    y = qy + 104
    for t, words, rel in LYRICS:
        if rel == 0:
            y += 8
            text(p, ix, y, words, 27, "text", 800, w=iw, h=40)
            y += 52
            continue
        if words.startswith("Salt"):
            y += 16
        hover = words.startswith("and the tide")
        if hover:
            rect(p, ix - 12, y - 2, iw + 24, 34, 8, col("hover", 0.8))
            text(p, ix + iw - 50, y, t, 11.5, "accentHi", 600, w=46, h=30, align="right", mono=True)
        colr = "faint" if rel < 0 else ("#c9cdd8" if rel == 1 else "muted")
        text(p, ix, y, words, 19, colr, 600 if rel == 1 else 500, w=iw - 60, h=30)
        y += 38
    p.restore()
    fade = grad(0, qy + qh - 70, 0, qy + qh - 2, [(0, col("#14171e", 0.0)), (1, col("#14171e", 0.95))])
    rect(p, qx + 1, qy + qh - 70, qw - 2, 68, 15, fade)
    nowbar(p, np_open=True)


# ------------------------------------------------------------------ the equalizer (R19), Needs attention (R2.8), encodings (R4.10)
EQ_BANDS = ("31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k")
EQ_CAR = (4.0, 3.5, 1.5, 0.0, -1.0, 0.0, 1.0, 2.0, 2.5, 2.0)
# The built-in Electronic preset, parametric (R19.3): type, frequency, gain, Q
EQ_PARAM = (("Low shelf", 80, 5.0, 0.7), ("Bell", 250, -1.5, 1.0), ("Bell", 1200, -1.0, 1.4),
            ("Bell", 4000, 2.5, 1.2), ("High shelf", 9000, 3.5, 0.7))


def biquad_db(kind, f0, gain, q, f, fs=48000.0):
    """The band's response in dB at f (the Audio EQ Cookbook's biquads, as A4.4 builds them)."""
    a = 10 ** (gain / 40)
    w0 = 2 * math.pi * f0 / fs
    cw, sw = math.cos(w0), math.sin(w0)
    al = sw / (2 * q)
    if kind == "Bell":
        b, aa = (1 + al * a, -2 * cw, 1 - al * a), (1 + al / a, -2 * cw, 1 - al / a)
    elif kind in ("Low shelf", "High shelf"):
        sa = 2 * math.sqrt(a) * al
        s = 1 if kind == "Low shelf" else -1
        b = (a * ((a + 1) - s * (a - 1) * cw + sa), s * 2 * a * ((a - 1) - s * (a + 1) * cw),
             a * ((a + 1) - s * (a - 1) * cw - sa))
        aa = ((a + 1) + s * (a - 1) * cw + sa, -s * 2 * ((a - 1) + s * (a + 1) * cw), (a + 1) + s * (a - 1) * cw - sa)
    w = 2 * math.pi * f / fs
    z1, z2 = complex(math.cos(-w), math.sin(-w)), complex(math.cos(-2 * w), math.sin(-2 * w))
    h = (b[0] + b[1] * z1 + b[2] * z2) / (aa[0] + aa[1] * z1 + aa[2] * z2)
    return 20 * math.log10(max(abs(h), 1e-9))


def seg_ctl(p, x, y, opts, on, h=34):
    sw = sum(tw(o, 12, 600) + 24 for o in opts) + 6
    rect(p, x, y, sw, h, 9, "input", "border")
    xx = x + 3
    for i, o in enumerate(opts):
        ow = tw(o, 12, 600) + 24
        if i == on:
            rect(p, xx, y + 3, ow, h - 6, 7, "hover")
        text(p, xx, y + 3, o, 12, "text" if i == on else "muted", 600, w=ow, h=h - 6, align="center")
        xx += ow
    return sw


def eq_panel(p, pw, ph, preset, note, note_fg, kind, actions):
    """The Equalizer panel's frame, preset row and Choose by genre (R19.2, R19.4); returns its box."""
    n01_now_waveform(p)
    rect(p, 0, 0, W, H - BAR_H, 0, col("scrim", 0.45))
    np_top(p, 0, eq=True)
    px, py = (W - pw) / 2, 56
    shadow(p, px, py, pw, ph, 16, 28)
    rect(p, px, py, pw, ph, 16, "surface", "borderStrong")
    ix = px + 28
    text(p, ix, py + 20, "Equalizer", 18, "text", 700)
    toggle(p, ix + 112, py + 24, True)
    icon(p, "close", px + pw - 28, py + 33, 14, "muted")
    rect(p, ix, py + 62, 262, 34, 10, "input", "border")
    icon(p, "eq", ix + 20, py + 79, 15, "accentHi")
    text(p, ix + 38, py + 62, preset, 13, "text", 600, h=34)
    chip(p, ix + 38 + tw(preset, 13, 600) + 8, py + 68, note, note_fg, "accentSoft", 22, size=10.5)
    icon(p, "chev_down", ix + 246, py + 79, 14, "muted")
    seg_ctl(p, ix + 274, py + 62, ["Parametric", "Graphic"], kind)
    bx = px + pw - 28
    for lab, w in reversed(actions):
        bx -= w
        button(p, bx, py + 62, lab, "ghost", w=w, h=34, size=12.5)
        bx -= 6
    fy = py + ph - 56
    line(p, px, fy - 10, px + pw, fy - 10, "border")
    toggle(p, ix, fy + 8, True)
    text(p, ix + 46, fy, "Choose by genre", 13, "text", 600, h=36)
    return px, py, ix, fy


def n05_equalizer(p):
    pw, ph = 820, 568
    px, py, ix, fy = eq_panel(p, pw, ph, "Electronic", "chosen by genre", "accentHi", 0,
                              [("Duplicate", 96), ("Import…", 88), ("Export…", 88)])
    text(p, ix + 46 + tw("Choose by genre", 13, 600) + 12, fy, "Signal Fires is Electronic, so it plays with Electronic",
         12, "muted", h=36, w=380)
    button(p, px + pw - 28 - 120, fy, "Genres…", "ghost", "genre", w=120, h=34, size=12.5)
    # the graph: 20 Hz to 20 kHz across, −12 to +12 dB up
    gx, gy, gw, gh = ix + 40, py + 112, pw - 56 - 40, 200
    rect(p, gx, gy, gw, gh, 10, "input", "border")
    def xf(f):
        return gx + 10 + (math.log10(f) - math.log10(20)) / 3 * (gw - 20)
    def yd(db):
        return gy + gh / 2 - db / 12 * (gh / 2 - 12)
    for db in (12, 6, 0, -6, -12):
        line(p, gx + 1, yd(db), gx + gw - 1, yd(db), "borderStrong" if db == 0 else "border")
        lab = ("+" if db > 0 else "−" if db < 0 else "") + str(abs(db))
        text(p, ix - 6, yd(db) - 9, lab, 10.5, "faint", w=40, h=18, align="right", mono=True)
    for f, lab in ((20, "20 Hz"), (50, "50"), (100, "100"), (200, "200"), (500, "500"), (1000, "1k"), (2000, "2k"),
                   (5000, "5k"), (10000, "10k"), (20000, "20k")):
        if 20 < f < 20000:
            line(p, xf(f), gy + 1, xf(f), gy + gh - 1, "border")
        text(p, xf(f) - 24, gy + gh + 4, lab, 10.5, "faint", w=48, align="center", mono=True)
    fs = [20 * 1000 ** (i / 240) for i in range(241)]
    # the selected band's own shape, then the sum of all of them
    sel = 3
    kind, f0, g0, q0 = EQ_PARAM[sel]
    own = QPainterPath(QPointF(xf(fs[0]), yd(biquad_db(kind, f0, g0, q0, fs[0]))))
    for f in fs[1:]:
        own.lineTo(xf(f), yd(biquad_db(kind, f0, g0, q0, f)))
    p.setPen(QPen(col("accentHi", 0.55), 1.3, Qt.DashLine)); p.setBrush(Qt.NoBrush); p.drawPath(own)
    pts = [QPointF(xf(f), yd(sum(biquad_db(k, a, g, q, f) for k, a, g, q in EQ_PARAM))) for f in fs]
    path_ = QPainterPath(pts[0])
    for pt in pts[1:]:
        path_.lineTo(pt)
    fill = QPainterPath(path_); fill.lineTo(xf(fs[-1]), yd(0)); fill.lineTo(xf(fs[0]), yd(0)); fill.closeSubpath()
    p.setPen(Qt.NoPen); p.setBrush(col("accent", 0.12)); p.drawPath(fill)
    p.setPen(QPen(grad(gx, 0, gx + gw, 0, [(0, "cyan"), (0.5, "accent"), (1, "pink")]), 2.4)); p.setBrush(Qt.NoBrush)
    p.drawPath(path_)
    for i, (k, f, g, q) in enumerate(EQ_PARAM):
        hx, hy = xf(f), yd(biquad_db(k, f, g, q, f))   # on the band's own curve: a shelf's is at half its gain
        on = i == sel
        if on:
            rect(p, hx - 15, hy - 15, 30, 30, 15, col("accent", 0.25))
        rect(p, hx - 10, hy - 10, 20, 20, 10, "accent" if on else "surface", "accentHi" if on else "text", 1.6)
        text(p, hx - 10, hy - 10, str(i + 1), 11, "#ffffff" if on else "text", 700, w=20, h=20, align="center")
    # the selected band, in four columns (R19.2): its handle and Delete; its type; frequency and preamp; gain and Q
    y0 = gy + gh + 34
    sh = 5 * 26 + 6
    rect(p, gx, y0, 32, 32, 16, "accent", "accentHi", 1.6)
    text(p, gx, y0, "4", 13, "#ffffff", 700, w=32, h=32, align="center")
    rect(p, gx, y0 + sh - 32, 32, 32, 8, "surface", "borderStrong")
    icon(p, "trash", gx + 16, y0 + sh - 16, 15, "muted")
    sx, sw_ = gx + 48, 120
    rect(p, sx, y0, sw_, sh, 9, "input", "border")
    for i, o in enumerate(("Bell", "Low shelf", "High shelf", "Low cut", "High cut")):
        oy = y0 + 3 + i * 26
        if i == 0:
            rect(p, sx + 3, oy, sw_ - 6, 26, 7, "hover")
        text(p, sx + 14, oy, o, 12, "text" if i == 0 else "muted", 600, h=26)
    c3 = sx + sw_ + 28
    cw = (px + pw - 28 - c3 - 28) / 2
    def hslider(x, y, label, frac, zero, value):
        text(p, x, y, label, 12, "muted", 600, h=28)
        rect(p, x + cw - 80, y, 80, 28, 7, "input", "border")
        text(p, x + cw - 80, y, value, 12, "text", w=80, h=28, align="center", mono=True)
        tx0, tx1 = x + 8, x + cw - 8
        ty = y + 46
        rect(p, tx0, ty - 2, tx1 - tx0, 4, 2, "borderStrong")
        a, b = sorted((tx0 + zero * (tx1 - tx0), tx0 + frac * (tx1 - tx0)))
        rect(p, a, ty - 2, max(2, b - a), 4, 2, "accent")
        if 0 < zero < 1:
            line(p, tx0 + zero * (tx1 - tx0), ty - 8, tx0 + zero * (tx1 - tx0), ty + 8, "borderStrong")
        rect(p, tx0 + frac * (tx1 - tx0) - 8, ty - 8, 16, 16, 8, "text")
    hslider(c3, y0, "Frequency", math.log10(4000 / 20) / 3, 0, "4.00 kHz")
    hslider(c3, y0 + 74, "Preamp", (12 - 5) / 24, 0.5, "−5.0 dB")
    c4 = c3 + cw + 28
    hslider(c4, y0, "Gain", (2.5 + 12) / 24, 0.5, "+2.5 dB")
    hslider(c4, y0 + 74, "Q", math.log10(1.2 / 0.1) / 2, 0, "1.20")


def n06_equalizer_graphic(p):
    pw, ph = 820, 476
    px, py, ix, fy = eq_panel(p, pw, ph, "Car", "for this song", "accentHi", 1,
                              [("Update", 80), ("Rename…", 92), ("Delete", 76)])
    text(p, ix + 46 + tw("Choose by genre", 13, 600) + 12, fy,
         "Car was chosen for this song; the next song takes its genre's preset", 12, "muted", h=36, w=420)
    button(p, px + pw - 28 - 120, fy, "Genres…", "ghost", "genre", w=120, h=34, size=12.5)
    # the sliders: preamp, then ten bands, the curve across them
    top, bot = py + 146, py + 338
    mid = (top + bot) / 2
    def yv(db):
        return mid - db / 12 * (bot - top) / 2
    for db, lab in ((12, "+12"), (0, "0 dB"), (-12, "−12")):
        text(p, ix - 4, yv(db) - 9, lab, 10.5, "faint", w=40, h=18, mono=True)
    line(p, ix + 92, top - 10, ix + 92, bot + 34, "border")
    def slider(x, db, lab, val, hi=False):
        rect(p, x - 2, top, 4, bot - top, 2, "borderStrong")
        y0, y1 = sorted((yv(0), yv(db)))
        rect(p, x - 2, y0, 4, max(2, y1 - y0), 2, "accent")
        rect(p, x - 9, yv(db) - 9, 18, 18, 9, "text", "accentHi" if hi else None, 2)
        text(p, x - 30, bot + 12, lab, 11.5, "muted", 600, w=60, align="center")
        text(p, x - 30, top - 30, val, 11, "accentHi" if hi else "faint", 600, w=60, align="center", mono=True)
    slider(ix + 60, -2.0, "Preamp", "−2.0")
    xs = [ix + 132 + i * ((pw - 56 - 150) / 9) for i in range(10)]
    pts = [QPointF(x, yv(v)) for x, v in zip(xs, EQ_CAR)]
    path_ = QPainterPath(pts[0])
    for a, b in zip(pts, pts[1:]):
        mx = (a.x() + b.x()) / 2
        path_.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
    fill = QPainterPath(path_); fill.lineTo(xs[-1], yv(0)); fill.lineTo(xs[0], yv(0)); fill.closeSubpath()
    p.setPen(Qt.NoPen); p.setBrush(col("accent", 0.10)); p.drawPath(fill)
    for x, v, lab in zip(xs, EQ_CAR, EQ_BANDS):
        slider(x, v, lab, f"{v:+.1f}".replace("-", "−"), hi=lab == "8k")
    p.setPen(QPen(grad(xs[0], 0, xs[-1], 0, [(0, "cyan"), (0.5, "accent"), (1, "pink")]), 2.4)); p.setBrush(Qt.NoBrush)
    p.drawPath(path_)
    text(p, xs[0] - 30, bot + 28, "Hz", 10.5, "faint", w=60, align="center")
    # the preamp plus Car's largest boost (+4.7 dB) passes full scale, so the level is held down (R19.1)
    text(p, ix, bot + 52, "−2.7 dB more, to keep from clipping", 11.5, "muted", w=pw - 56)


def l09_needs_attention(p):
    window(p)
    sidebar(p, "Needs attention")
    header(p, "Needs attention", "23 to look at", toggles=False, sort=None, search="Search these")
    window_buttons(p)
    x0 = SIDE_W + 28
    wt = W - x0 - 28
    cx = x0
    for i, (lab, n) in enumerate((("All", 23), ("Tags differ from path", 6), ("Same song twice", 3), ("Covers", 4),
                                  ("Names", 2), ("Wrong encoding", 2), ("Album in one file", 1), ("Other", 5))):
        on = i == 2
        lab2 = f"{lab}  {n}"
        cx += chip(p, cx, 74, lab2, "text" if on else "muted", "accentSoft" if on else "surface", 28,
                   border=None if on else "border", size=12, weight=600 if on else 500) + 8
    text(p, x0, 118, "SAME SONG MORE THAN ONCE", 11, "faint", 700)
    text(p, x0 + 220, 118, "The kept copy takes the others' plays and highest rating, and their place in playlists.",
         11.5, "muted", w=wt - 220)
    groups = [
        ("Signal Fires", "Lumen Drift · 4:18", ("ok", "Exact copies"), [
            (True, False, "FLAC · 16-bit / 44.1 kHz", "Lumen Drift/2019 - Glass Harbor/04 - Signal Fires.flac", "52", 5, "Keep: lossless"),
            (False, True, "MP3 · 320 kbps", "_Incoming/new rips/Signal Fires.mp3", "3", 4, None)]),
        ("Moonpull", "Lumen Drift · 4:44 and 4:45", ("warn", "Likely"), [
            (True, False, "FLAC · 16-bit / 44.1 kHz", "Lumen Drift/Tide Tables/04 - Moonpull.flac", "18", 4, "Keep: lossless"),
            (False, False, "AAC · 256 kbps", "_Incoming/From Phone/Moonpull (radio).m4a", "6", 0, None)]),
    ]
    y = 144
    for title, sub, (st, stl), copies in groups:
        gh = 44 + len(copies) * 46 + 10
        rect(p, x0, y, wt, gh, 12, "surface", "border")
        art(p, x0 + 16, y + 10, 26, 11 if title == "Signal Fires" else 131, 5)
        tx = x0 + 52 + text(p, x0 + 52, y + 10, title, 14, "text", 700, h=26)
        tx += text(p, tx + 10, y + 10, sub, 12, "muted", h=26) + 22
        chip(p, tx, y + 12, stl, st, st + "Soft", 22, ic="check" if st == "ok" else "attention", size=11)
        for k, (keep, trash, fmt, path, plays, rating, why) in enumerate(copies):
            ry = y + 44 + k * 46
            line(p, x0 + 12, ry, x0 + wt - 12, ry, "border")
            radio(p, x0 + 18, ry + 15, keep)
            text(p, x0 + 42, ry, "Keep" if keep else "", 12, "accentHi", 600, h=46)
            if not keep:
                checkbox(p, x0 + 92, ry + 15, trash)
                text(p, x0 + 116, ry, "Trash", 12, "err" if trash else "muted", 600, h=46)
            text(p, x0 + 180, ry, fmt, 12.5, "text", 600 if keep else 400, h=46, w=200)
            text(p, x0 + 390, ry, path, 12, "muted", h=46, w=330, mono=True)
            text(p, x0 + 730, ry, plays + " plays", 12, "muted", h=46, w=70, align="right")
            stars(p, x0 + 818, ry + 23, rating, r=4.4, gap=11.5)
            if why:
                text(p, x0 + 890, ry, why, 11.5, "ok", 600, h=46, w=wt - 900)
        y += gh + 12
    for lab, n, act in (("Wrong encoding", "2 songs · Северный Ветер, Тихая Гавань", "Fix encoding…"),
                        ("Album in one file", "1 album · Live at the Lantern (Mara Okafor), with a .cue", "Show in folder")):
        rect(p, x0, y, wt, 48, 12, "surface", "border")
        icon(p, "chev_right", x0 + 22, y + 24, 14, "muted")
        tx = x0 + 40 + text(p, x0 + 40, y, lab, 13, "text", 600, h=48)
        text(p, tx + 12, y, n, 12, "muted", h=48, w=520)
        button(p, x0 + wt - 16 - 150, y + 8, act, "ghost", w=150, h=32, size=12.5)
        y += 58
    by = H - BAR_H - 58
    selection_bar(p, x0 + wt / 2, by, "1 copy to the trash", "plays and rating go to the kept copy",
                  [("Move 1 to the trash", "trash")])
    nowbar(p)


def t06_fix_encoding(p):
    l09_needs_attention(p)
    w, h = 980, 560
    x, y = dialog(p, w, h, "Fix encoding · 08 - Ìàÿê.mp3",
                  "These tags were saved as Latin-1 but read better another way. Choose the reading that is right.")
    ix, iw = x + 28, w - 56
    cols = [("READ AS", ix + 44, 230, "left"), ("ARTIST", ix + 290, 220, "left"), ("ALBUM", ix + 520, 210, "left"),
            ("TITLE", ix + 740, 160, "left")]
    ty = y + 92
    for lab, cx_, cw_, al in cols:
        text(p, cx_, ty, lab, 11, "faint", 700, w=cw_, h=24)
    rows = [
        ("Cyrillic (Windows-1251)", "Most likely", ("Северный Ветер", "Тихая Гавань", "Маяк"), True),
        ("As it is (Latin-1)", None, ("Ñåâåðíûé Âåòåð", "Òèõàÿ Ãàâàíü", "Ìàÿê"), False),
        ("Central European (Windows-1250)", None, ("Ńĺâĺđíűé Âĺňĺđ", "Ňčőŕ˙ Ăŕâŕíü", "Ěŕ˙ę"), False),
        ("Greek (Windows-1253)", None, None, False),
        ("Japanese (Shift-JIS)", None, None, False),
        ("Chinese (GBK, Big5)", None, None, False),
    ]
    for i, (enc, badge, vals, on) in enumerate(rows):
        ry = ty + 28 + i * 50
        rect(p, ix, ry, iw, 44, 9, "accentSoft" if on else "raised", "accent" if on else "border", 1.4 if on else 1)
        radio(p, ix + 14, ry + 14, on)
        text(p, ix + 44, ry + (4 if badge else 0), enc, 13, "text", 600 if on else 400, h=22 if badge else 44, w=236)
        if badge:
            text(p, ix + 44, ry + 22, badge, 11, "ok", 600, h=18)
        if vals:
            for v, (lab, cx_, cw_, al) in zip(vals, cols[1:]):
                text(p, cx_, ry, v, 13.5, "text" if on else "muted", 600 if on else 400, h=44, w=cw_)
        else:
            text(p, ix + 290, ry, "Can't be read this way", 12.5, "faint", h=44)
    oy = ty + 28 + 6 * 50 + 6
    checkbox(p, ix, oy + 2, True)
    text(p, ix + 24, oy, "The same for every song of the album (9 songs)", 12.5, "text", h=20)
    fy = y + h - 62
    line(p, x, fy - 12, x + w, fy - 12, "border")
    text(p, ix, fy, "9 files · artist, album and title · written as Unicode; Undo puts the old bytes back", 12.5,
         "muted", h=36, w=560)
    button(p, x + w - 28 - 150, fy, "Save 9 files", "primary", "check", w=150)
    button(p, x + w - 28 - 260, fy, "Cancel", "ghost", w=100)


def s01_settings(p):
    l01_albums(p)
    w, h = 900, 620
    x, y = dialog(p, w, h, "Settings")
    # nav
    nx = x + 16
    for i, (lab, ic) in enumerate((("Library", "folder"), ("Tags", "genre"), ("Path patterns", "wand"),
                                   ("Album art", "image"), ("Playlists", "playlist"), ("Playback", "play"),
                                   ("Appearance", "gear"), ("Online", "globe"), ("Lyrics", "lyrics"))):
        yy = y + 70 + i * 38
        if i == 1:
            rect(p, nx, yy, 180, 34, 8, "accentSoft")
        icon(p, ic, nx + 20, yy + 17, 15, "accentHi" if i == 1 else "muted")
        text(p, nx + 38, yy, lab, 13, "text" if i == 1 else "#c9cdd8", 600 if i == 1 else 400, h=34)
    line(p, x + 212, y + 64, x + 212, y + h - 20, "border")
    cx = x + 236
    cw = w - 236 - 28
    text(p, cx, y + 70, "Tags", 17, "text", 700)

    def row(yy, head, sub, ctl):
        text(p, cx, yy, head, 13.5, "text", 600, w=cw - 200)
        text(p, cx, yy + 22, sub, 12, "muted", w=cw - 200)
        ctl(yy)
        line(p, cx, yy + 54, cx + cw, yy + 54, "border")

    def seg(yy, opts, on):
        sw = sum(tw(o, 12, 600) + 24 for o in opts) + 6
        sx = cx + cw - sw
        rect(p, sx, yy + 6, sw, 30, 8, "input", "border")
        xx = sx + 3
        for i, o in enumerate(opts):
            ow = tw(o, 12, 600) + 24
            if i == on:
                rect(p, xx, yy + 9, ow, 24, 6, "hover")
            text(p, xx, yy + 9, o, 12, "text" if i == on else "muted", 600, w=ow, h=24, align="center")
            xx += ow

    yy = y + 110
    row(yy, "ID3 version for MP3", "2.4 keeps UTF-8 and multiple values; 2.3 for older players and car stereos.",
        lambda v: seg(v, ["2.3", "2.4"], 1)); yy += 66
    row(yy, "Write ratings into the files", "POPM for MP3, a RATING field for FLAC and Ogg, so other players see them.",
        lambda v: toggle(p, cx + cw - 36, v + 12, True)); yy += 66
    row(yy, "Rating scale in files", "How 1–5 stars are written to POPM: the values most players read.",
        lambda v: seg(v, ["Windows Media", "MusiKata"], 0)); yy += 66
    row(yy, "Keep a history of tag changes", "Every save can be undone, file by file, for 90 days.",
        lambda v: toggle(p, cx + cw - 36, v + 12, True)); yy += 66
    row(yy, "Genre list", "Suggested while typing; merging and renaming are on the Genres page.",
        lambda v: button(p, cx + cw - 120, v + 4, "Edit list…", "ghost", h=32, w=120, size=12.5)); yy += 66
    row(yy, "Leave file modification times alone", "Some backup tools use them; the tags still change.",
        lambda v: toggle(p, cx + cw - 36, v + 12, False)); yy += 66
    text(p, cx, yy + 4, "Changes apply to the next save; files already written are not rewritten.", 12, "faint", w=cw)


def t03_organize(p):
    l04_folders(p)
    w, h = 1000, 560
    x, y = dialog(p, w, h, "Organize files",
                  "Rename and move files to match their tags. Every move is listed first, and Undo puts them back.")
    ix, iw = x + 28, w - 56
    text(p, ix, y + 86, "Layout under ~/Music", 11.5, "muted", 600)
    rect(p, ix, y + 106, iw, 40, 9, "input", "border")
    text(p, ix + 12, y + 106, "{albumartist}/{year} - {album}/{disc-}{track:02} - {title}", 13, "text", h=40, mono=True,
         w=iw - 24)
    py = y + 164
    rect(p, ix, py, iw, 250, 10, "bg", "border")
    moves = [("_Incoming/new rips/track01.mp3", "Kestrel Union/2022 - Low Orbit/01 - Low Orbit.mp3"),
             ("_Incoming/new rips/track02.mp3", "Kestrel Union/2022 - Low Orbit/02 - Perihelion.mp3"),
             ("_Incoming/new rips/track03.mp3", "Kestrel Union/2022 - Low Orbit/03 - Night Burn.mp3"),
             ("Lumen Drift/Tide Tables/01 - Neap Tide.flac", "Lumen Drift/2022 - Tide Tables/01 - Neap Tide.flac"),
             ]
    for i, (a, b) in enumerate(moves):
        yy = py + 12 + i * 46
        checkbox(p, ix + 14, yy + 14, True)
        text(p, ix + 42, yy, a, 12, "muted", h=22, w=iw - 60, mono=True)
        icon(p, "move", ix + 52, yy + 33, 12, "accentHi")
        text(p, ix + 66, yy + 22, b, 12, "text", h=22, w=iw - 80, mono=True)
    text(p, ix + 14, py + 250 - 28, "+ 10 more moves · 2 empty folders will be removed", 11.5, "faint", h=20)
    rect(p, ix, py + 262, iw, 36, 8, "warnSoft")
    icon(p, "attention", ix + 18, py + 280, 14, "warn")
    text(p, ix + 34, py + 262, "Playlists that list these files are updated too: Road Trip, Workout Mix.", 12, "warn",
         h=36, w=iw - 50)
    fy = y + h - 62
    line(p, x, fy - 12, x + w, fy - 12, "border")
    text(p, ix, fy, "14 files · no name conflicts", 12.5, "muted", h=36)
    button(p, x + w - 28 - 170, fy, "Move 14 files", "primary", "move", w=170)
    button(p, x + w - 28 - 280, fy, "Cancel", "ghost", w=100)


SCREENS = {
    "X01-first-run": x01_first_run,
    "X02-root-unavailable": x02_root_unavailable,
    "L01-albums": l01_albums,
    "L02-album": l02_album,
    "L03-songs-bulk-edit": l03_songs_bulk,
    "L04-folders": l04_folders,
    "L05-folders-large": l05_folders_large,
    "L06-folders-cards": l06_folders_cards,
    "L07-folders-list": l07_folders_list,
    "L08-folder-songs": l08_folder_songs,
    "L09-needs-attention": l09_needs_attention,
    "T01-infer-from-path": t01_infer,
    "T02-album-art": t02_album_art,
    "T03-organize-files": t03_organize,
    "T04-find-cover-online": t04_find_cover,
    "T05-look-up-tags": t05_look_up_tags,
    "T06-fix-encoding": t06_fix_encoding,
    "P01-playlist-drag": p01_playlist_drag,
    "G01-genres": g01_genres,
    "N01-now-playing-waveform": n01_now_waveform,
    "N02-now-playing-3d-analyzer": n02_now_3d,
    "N03-now-playing-queue": n03_now_queue,
    "N04-now-playing-lyrics": n04_now_lyrics,
    "N05-equalizer": n05_equalizer,
    "N06-equalizer-graphic": n06_equalizer_graphic,
    "N07-now-playing-not-in-library": n07_now_not_in_library,
    "S01-settings-tags": s01_settings,
    "M01-mini-players": m01_mini_players,
    "M02-mini-player-menu": m02_mini_player_menu,
}


def render(name, fn):
    img = QImage(W * SCALE, H * SCALE, QImage.Format_RGB32)
    img.fill(QColor(C["bg"]))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    p.scale(SCALE, SCALE)
    fn(p)
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    rgb = Image.open(io.BytesIO(bytes(buf.data()))).convert("RGB")
    # 256 colours: the design tokens exactly, so a thin line of one (the green progress line) keeps its
    # colour, and the rest of the palette chosen from the picture
    tokens = sorted({QColor(v).getRgb()[:3] for v in [*C.values(), "#c9cdd8", "#ffffff", "#0b0d11"]})
    chosen = rgb.quantize(256 - len(tokens)).getpalette()[:3 * (256 - len(tokens))]
    palette = Image.new("P", (1, 1))
    palette.putpalette(chosen + [v for t in tokens for v in t])
    rgb.quantize(palette=palette, dither=Image.Dither.NONE).save(OUT / f"{name}.png", optimize=True)


def main(filters):
    QGuiApplication(sys.argv[:1])
    for name, fn in SCREENS.items():
        if not filters or any(f in name for f in filters):
            render(name, fn)
            print(name)


if __name__ == "__main__":
    main(sys.argv[1:])
