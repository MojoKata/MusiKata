"""The 3D analyzer's landscape (R11.3, A5.3): the last few seconds of spectra (A5.2), each a slice,
projected into a perspective landscape. Depth scales a slice's width and height towards a vanishing
point at the middle of the horizon and moves it up towards the horizon; the newest slice is at the
front, the oldest at the back. Slices are drawn back to front, each a filled strip in the
background colour (which hides what is behind it) under a line strip in its colour, the colour
stepping from cyan at the front to violet at the back.

`Landscape` keeps the slices: the newest levels at the front each frame, and a slice kept every
SLICE seconds, which recedes as the landscape's time goes on and is let go once older than the
seconds the landscape holds (the speed of R11.3.1). `project` places them, `colours` colours them
and `strip` makes them one triangle strip, the vertices of the scene graph's one geometry node
(A5.3). The projection is the mockup N02's (docs/mockups/src/render.py, `n02_now_3d`).

Plain NumPy, no Qt: the levels come from musikata_core.analysis.spectrum, the size from the view."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .spectrum import HIGH, LOW

SLICE = 1 / 12  # seconds between the slices kept: N02's 34 over its 3 seconds, a few more
SECONDS = 3.0  # the seconds the landscape holds by default: N02's "3 seconds ago", speed 1×
BACK_SCALE = 0.38  # the back slice's width and height, as a share of the front's
RISE = 0.85  # how a slice's foot climbs to the horizon with depth: depth ** RISE of the way
AMPLITUDE = 0.367  # a full band's height at the front, as a share of the landscape's height
HORIZON = 0.14  # the back slice's foot, as a share of the landscape's height from its top
DIM = 0.35  # how far the back slice's line is darkened towards the background
FILL_FRONT, FILL_BACK = 0.22, 0.10  # how much of its colour a slice's fill takes, front and back
LINE_FRONT, LINE_BACK = 1.6, 1.0  # a slice's line width in pixels, front and back

Rgb = tuple[int, int, int]
CYAN: Rgb = (0x22, 0xD3, 0xEE)  # R6.2's `cyan`, the front
VIOLET: Rgb = (0xA7, 0x8B, 0xFA)  # R6.2's `accent`, the back
BACKGROUND: Rgb = (0x0E, 0x0D, 0x18)  # N02's, behind the landscape

# the octave labels along the front (R11.3.1): every other octave, as N02 names them
OCTAVES = ((32.0, "32 Hz"), (125.0, "125"), (500.0, "500"), (2000.0, "2 k"), (8000.0, "8 k"),
           (16000.0, "16 kHz"))  # fmt: skip


class Landscape:
    """The slices of the last `seconds` (R11.3.1's speed), each `bands` levels: `advance` moves
    the landscape's time on by a frame and puts the frame's levels at the front, keeping a slice
    every `every` seconds; `slices` gives them back to front with their depths."""

    def __init__(self, bands: int, seconds: float = SECONDS, every: float = SLICE) -> None:
        if bands < 1 or seconds <= 0 or every <= 0:
            raise ValueError(f"{bands} bands over {seconds} s, a slice every {every} s")
        self.bands, self.seconds, self.every = bands, seconds, every
        capacity = math.ceil(seconds / every) + 2
        self._kept = np.zeros((capacity, bands), np.float32)
        self._times = np.full(capacity, -math.inf)
        self._next = 0  # where the next slice kept goes
        self._due = 0.0  # when the next slice is kept
        self.now = 0.0  # the landscape's time: it runs only while frames are drawn
        self.front = np.zeros(bands, np.float32)

    def advance(self, levels: NDArray[np.float32], seconds: float) -> None:
        """A frame `seconds` after the last: `levels` (one a band, 0 to 1) at the front, and kept
        as a slice when one is due."""
        if len(levels) != self.bands:
            raise ValueError(f"{len(levels)} levels for {self.bands} bands")
        self.now += max(0.0, seconds)
        self.front = np.asarray(levels, np.float32).copy()
        if self.now + 1e-9 >= self._due:
            self._kept[self._next] = self.front
            self._times[self._next] = self.now
            self._next = (self._next + 1) % len(self._times)
            # on the beat of `every`, unless frames came too far apart to keep it
            self._due = max(self._due + self.every, self.now + self.every / 2)

    def slices(self) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        """The slices to draw, back to front: their levels (slices × bands) and their depths, 0
        at the front to 1 at the back, the front's levels last."""
        ages = self.now - self._times
        held = np.flatnonzero(ages <= self.seconds + 1e-9)
        depths = np.concatenate([ages[held] / self.seconds, [0.0]]).astype(np.float32)
        levels = np.concatenate([self._kept[held], self.front[None, :]])
        order = back_to_front(depths)
        return levels[order], depths[order]


def back_to_front(depths: NDArray[np.float32]) -> NDArray[np.intp]:
    """The order to draw slices at `depths` in: the deepest first, so nearer ones hide farther
    ones; of slices at one depth, the later one last."""
    return np.argsort(-np.asarray(depths, np.float32), kind="stable")


@dataclass(frozen=True)
class Places:
    """Where slices stand in a landscape: each one's points (slices × bands × 2, x and y), its
    foot (y), and its left and right ends (x)."""

    points: NDArray[np.float32]
    feet: NDArray[np.float32]
    lefts: NDArray[np.float32]
    rights: NDArray[np.float32]


def scale(depths: NDArray[np.float32]) -> NDArray[np.float32]:
    """A slice's width and height at each depth, as a share of the front's: 1 at the front to
    BACK_SCALE at the back."""
    return (1.0 - (1.0 - BACK_SCALE) * np.clip(depths, 0.0, 1.0)).astype(np.float32)


def feet(depths: NDArray[np.float32], height: float) -> NDArray[np.float32]:
    """A slice's foot (y) at each depth in a landscape `height` tall: the bottom at the front,
    rising to the horizon (HORIZON of the height from the top) at the back."""
    z = np.clip(np.asarray(depths, np.float32), 0.0, 1.0)
    return (height - (height - HORIZON * height) * z**RISE).astype(np.float32)


def project(
    levels: NDArray[np.float32], depths: NDArray[np.float32], width: float, height: float
) -> Places:
    """Slices of `levels` (slices × bands, 0 to 1) at `depths` placed in a landscape `width` ×
    `height`: the front slice across the whole width standing on the bottom, a full band
    AMPLITUDE of the height tall; deeper ones narrower and lower by `scale`, centred on the
    vanishing point, their feet risen towards the horizon (`feet`). Low bands on the left."""
    levels = np.clip(np.asarray(levels, np.float32), 0.0, 1.0)
    count, bands = levels.shape
    shares = scale(depths)
    foot = feet(depths, height)
    across = np.linspace(-0.5, 0.5, bands, dtype=np.float32) if bands > 1 else np.zeros(1)
    points = np.empty((count, bands, 2), np.float32)
    points[:, :, 0] = width / 2 + across[None, :] * width * shares[:, None]
    points[:, :, 1] = foot[:, None] - levels * (AMPLITUDE * height) * shares[:, None]
    half = width * shares / 2
    lefts, rights = (width / 2 - half).astype(np.float32), (width / 2 + half).astype(np.float32)
    return Places(points, foot, lefts, rights)


def octave_places() -> list[tuple[float, str]]:
    """The octave labels along the front (R11.3.1): each one's place across it (0 at the left, 1
    at the right, as the bands are spaced, logarithmically) and its text."""
    span = math.log(HIGH / LOW)
    return [(math.log(hz / LOW) / span, text) for hz, text in OCTAVES]


def _mix(
    a: NDArray[np.float32], b: NDArray[np.float32], share: NDArray[np.float32]
) -> NDArray[np.float32]:
    return (a + (b - a) * share[:, None]).astype(np.float32)


def colours(
    depths: NDArray[np.float32],
    front: Rgb = CYAN,
    back: Rgb = VIOLET,
    background: Rgb = BACKGROUND,
) -> tuple[NDArray[np.uint8], NDArray[np.uint8]]:
    """Each slice's line and fill colours, RGBA bytes, all opaque: the line stepping from `front`
    at depth 0 to `back` at depth 1, darkened towards `background` with depth (DIM at the back);
    the fill the background with a little of the line's colour (FILL_FRONT at the front to
    FILL_BACK at the back), so it hides what is behind it."""
    z = np.clip(np.asarray(depths, np.float32), 0.0, 1.0)
    near, far, ground = (np.array(c, np.float32)[None, :] for c in (front, back, background))
    hue = _mix(near, far, z)
    line = _mix(hue, ground, DIM * z)
    fill = _mix(ground, hue, FILL_FRONT + (FILL_BACK - FILL_FRONT) * z)
    out = []
    for rgb in (line, fill):
        rgba = np.full((len(z), 4), 255, np.uint8)
        rgba[:, :3] = np.round(np.broadcast_to(rgb, (len(z), 3)))
        out.append(rgba)
    return out[0], out[1]


def line_widths(depths: NDArray[np.float32]) -> NDArray[np.float32]:
    """Each slice's line width in pixels: LINE_FRONT at the front to LINE_BACK at the back."""
    z = np.clip(np.asarray(depths, np.float32), 0.0, 1.0)
    return (LINE_FRONT + (LINE_BACK - LINE_FRONT) * z).astype(np.float32)


def vertices_per_slice(bands: int) -> int:
    """The strip's vertices for one slice of `bands`: its fill's and its line's, two a band each,
    and the two repeated vertices joining each to what comes next."""
    return 4 * bands + 4


def strip(
    places: Places,
    widths: NDArray[np.float32],
    line: NDArray[np.uint8],
    fill: NDArray[np.uint8],
) -> tuple[NDArray[np.float32], NDArray[np.uint8]]:
    """The slices at `places`, in their order, as one triangle strip: each slice's fill (from
    its foot up to its line, in `fill`) then its line (`widths` thick about its points, in
    `line`), each joined to the next by its last vertex and the next's first repeated (triangles
    of no area). The points (rows of x, y) and their RGBA colours, `vertices_per_slice` a slice."""
    points = places.points
    count, bands, _ = points.shape
    if not count or not bands:
        return np.zeros((0, 2), np.float32), np.zeros((0, 4), np.uint8)
    xs, ys = points[:, :, 0], points[:, :, 1]
    # the fill: down to the foot and up to the line, band by band
    fill_xy = np.empty((count, 2 * bands, 2), np.float32)
    fill_xy[:, 0::2, 0], fill_xy[:, 1::2, 0] = xs, xs
    fill_xy[:, 0::2, 1] = places.feet[:, None]
    fill_xy[:, 1::2, 1] = ys
    # the line: either side of each point, along the normal of the line there
    if bands > 1:
        dx = np.gradient(xs, axis=1)
        dy = np.gradient(ys, axis=1)
    else:
        dx, dy = np.ones_like(xs), np.zeros_like(ys)
    length = np.maximum(np.hypot(dx, dy), 1e-6)
    half = widths[:, None] / 2
    nx, ny = -dy / length * half, dx / length * half
    line_xy = np.empty((count, 2 * bands, 2), np.float32)
    line_xy[:, 0::2, 0], line_xy[:, 1::2, 0] = xs + nx, xs - nx
    line_xy[:, 0::2, 1], line_xy[:, 1::2, 1] = ys + ny, ys - ny
    # each part with its first vertex before it and its last after it, repeated: the joins
    parts = []
    for xy in (fill_xy, line_xy):
        parts.append(np.concatenate([xy[:, :1], xy, xy[:, -1:]], axis=1))
    per = 2 * bands + 2
    joined = np.concatenate(parts, axis=1).reshape(-1, 2)
    rgba = np.empty((count, 2 * per, 4), np.uint8)
    rgba[:, :per] = fill[:, None, :]
    rgba[:, per:] = line[:, None, :]
    return joined, rgba.reshape(-1, 4)
