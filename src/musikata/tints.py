"""The cover's colour (R6.2.2): the large views (an album's page, Now Playing) tint their background
with their cover's dominant colour, and so do Folders' Cards (R2.9.4). R13.8's **Tint views with the
cover's colour** comes with Settings (slice 9); until then the views are always tinted, its default.

The colour is picked from the cover's thumbnail (covers.py) on a thread of its own ("tints"), never
the GUI thread: the thumbnail read from the cache or made (`Covers.image`, as QML's image threads
make it), its pixels converted and read as an array, and the dominant colour worked out by plain
NumPy (`dominant`, `tint_of`). It is kept with the thumbnail in the cover cache, as
`<thumbnail>-colour` (covers.CACHED, so the cache's trim takes it with its thumbnail), and so is
worked out once a cover. What QML asks for (`of`) is answered at once from memory or with "" (no
tint yet); the thread's answer comes back by a queued signal, and `revision` moves so the bindings
that asked read again.

QImage's conversion keeps the GIL while Qt works, a millisecond for a thumbnail, and takes no lock
a thread waiting on the GIL can hold once Qt's image threads are there (covers.start_image_threads,
made as the covers' provider is): docs/process/coding.md, "Threads and processes"."""

from __future__ import annotations

import colorsys
import logging
import os
import queue
import tempfile
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from .covers import MOSAIC, mosaic_name
from .models import COVERS

log = logging.getLogger(__name__)

SIDE = 256  # the thumbnail the colour is picked from (covers.SIZES' smaller)
STEP = 4  # every STEP-th pixel each way: 4,096 of a 256-pixel thumbnail
HUES = 12  # the colour wheel's slices the pixels are counted in
SUFFIX = "-colour"  # a colour's file in the cache: the thumbnail's name and this
NONE = "none"  # kept for a cover with no colour to speak of (greys): no tint
TINT_LUMINANCE = 0.035  # the lightest a tint may be: muted text (#99a0b2) at 4.5:1 over it

Rgb = tuple[int, int, int]


def pixels_of(image: QImage, step: int = STEP) -> NDArray[np.uint8]:
    """Every `step`-th pixel of `image` each way, as rows of R, G, B; none for an empty image."""
    if image.isNull():
        return np.zeros((0, 3), np.uint8)
    rgb = image.convertToFormat(QImage.Format.Format_RGB32)
    width, height, line = rgb.width(), rgb.height(), rgb.bytesPerLine()
    raw = np.frombuffer(rgb.constBits(), np.uint8, count=line * height).reshape(height, line)
    bgra = raw[:, : width * 4].reshape(height, width, 4)[::step, ::step]
    return np.ascontiguousarray(bgra[..., 2::-1]).reshape(-1, 3)  # B, G, R, A as R, G, B


def dominant(pixels: NDArray[np.uint8]) -> Rgb | None:
    """The cover's dominant colour from its pixels (rows of R, G, B): the hue slice holding the
    most colour, each pixel counted by how vivid it is (its saturation, and how far from black),
    and that slice's pixels averaged, weighted the same way. None when the cover has no colour
    to speak of: greys, black and white."""
    if not len(pixels):
        return None
    rgb = pixels.astype(np.float32) / 255
    high, low = rgb.max(axis=1), rgb.min(axis=1)
    chroma = high - low
    saturation = np.where(high > 0, chroma / np.maximum(high, 1e-6), 0.0)
    weight = saturation * high
    weight[chroma < 0.08] = 0.0  # greys count for nothing
    if weight.sum() < 0.02 * len(pixels):
        return None
    hue = _hues(rgb, high, chroma)
    slices = np.minimum((hue * HUES).astype(np.intp), HUES - 1)
    totals = np.bincount(slices, weights=weight, minlength=HUES)
    chosen = slices == int(np.argmax(totals))
    mean = (rgb[chosen] * weight[chosen, None]).sum(axis=0) / weight[chosen].sum()
    r, g, b = (int(round(float(v) * 255)) for v in mean)
    return r, g, b


def _hues(rgb: NDArray[Any], high: NDArray[Any], chroma: NDArray[Any]) -> NDArray[np.float32]:
    """Each pixel's hue, 0 to 1 round the wheel (red at 0)."""
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    c = np.maximum(chroma, 1e-6)
    hue = np.where(
        high == r, ((g - b) / c) % 6, np.where(high == g, (b - r) / c + 2, (r - g) / c + 4)
    )
    out: NDArray[np.float32] = (hue / 6).astype(np.float32)
    return out


def luminance(rgb: tuple[float, float, float]) -> float:
    """A colour's relative luminance (WCAG's, as R18.4 measures contrast), its channels 0 to 1."""

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def tint_of(colour: Rgb | None) -> str:
    """The tint a view draws behind its text from the cover's colour: its hue, saturated, and dark
    enough (its luminance at most TINT_LUMINANCE) that the design tokens' muted text keeps 4.5:1
    over it (R18.4), whatever the hue; "" for none."""
    if colour is None:
        return ""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in colour))
    s, v = max(0.55, min(s, 0.85)), min(v, 0.42)
    rgb = colorsys.hsv_to_rgb(h, s, v)
    while luminance(rgb) > TINT_LUMINANCE:
        v *= 0.92
        rgb = colorsys.hsv_to_rgb(h, s, v)
    return "#{:02x}{:02x}{:02x}".format(*(int(round(c * 255)) for c in rgb))


def name_of(url: str) -> str | None:
    """The name a cover's colour is kept under, from the address QML shows it from: its
    thumbnail's, or a mosaic's (covers.mosaic_name); None for no cover."""
    if not url.startswith(COVERS) or url == COVERS:
        return None
    name = url[len(COVERS) :]
    if name.startswith(MOSAIC):
        return mosaic_name(name[len(MOSAIC) :].split("+"))
    return name


Picture = Callable[[str, int], QImage]  # (the provider's name, side): Covers.image


class Tints(QObject):
    """Covers' colours as QML asks for them (`of`, by a cover's address), picked on a thread of
    its own from `image` (Covers.image: the cover's thumbnail, cached or made) and kept in
    `cache`, the cover cache."""

    changed = Signal()  # a colour came: `revision` moved
    _found = Signal(str, str)  # (the cover's address, its tint or "")

    def __init__(self, image: Picture, cache: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._image, self._cache = image, cache
        self._known: dict[str, str] = {}  # by address; "" for no tint
        self._asked: set[str] = set()
        self._jobs: queue.SimpleQueue[str | None] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._idle = threading.Event()
        self._idle.set()
        self._pending = 0
        self._lock = threading.Lock()
        self._revision = 0
        self._found.connect(self._on_found)

    @Slot(str, result=str)
    def of(self, url: str) -> str:
        """The tint of the cover at `url` (image://covers/…): known, or "" while it is picked
        (`changed` says when it comes) or for none."""
        if url in self._known:
            return self._known[url]
        if url and url not in self._asked and not self._closed and name_of(url) is not None:
            self._asked.add(url)
            with self._lock:
                self._pending += 1
                self._idle.clear()
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="tints", daemon=True)
                self._thread.start()
            self._jobs.put(url)
        return ""

    @property
    def busy(self) -> bool:
        """A colour asked for is still being picked (the tour waits for it)."""
        return not self._idle.is_set()

    def wait(self) -> None:
        """Until the thread has picked every colour asked for (a test's, the tour's)."""
        self._idle.wait()

    def close(self) -> None:
        """Ends the thread after the colour it is picking: for closing."""
        self._closed = True
        if self._thread is not None:
            self._jobs.put(None)
            self._thread.join()
            self._thread = None

    # ---------- the thread ----------

    def _run(self) -> None:
        while True:
            url = self._jobs.get()
            if url is None or self._closed:
                return
            try:
                tint = self._pick(url)
            except Exception:  # noqa: BLE001  (logged: the view stays untinted)
                log.exception("couldn't pick the colour of %s", url)
                tint = ""
            self._found.emit(url, tint)
            with self._lock:
                self._pending -= 1
                if not self._pending:
                    self._idle.set()

    def _pick(self, url: str) -> str:
        """The cover's tint: kept in the cache, else picked from its thumbnail and kept."""
        name = name_of(url)
        assert name is not None  # `of` asks for none other
        path = os.path.join(self._cache, name + SUFFIX)
        kept = _read(path)
        if kept is not None:
            return "" if kept == NONE else kept
        image = self._image(url[len(COVERS) :], SIDE)
        if image.isNull():
            return ""  # no cover to show: nothing kept, so a cover found later is picked
        tint = tint_of(dominant(pixels_of(image)))
        _keep(path, tint or NONE)
        return tint

    # ---------- back on the GUI thread ----------

    @Slot(str, str)
    def _on_found(self, url: str, tint: str) -> None:
        self._known[url] = tint
        if tint:
            self._revision += 1
            self.changed.emit()

    def _get_revision(self) -> int:
        return self._revision

    # read in a binding beside `of`, so the binding reads `of` again when a colour comes
    revision = QtProperty(int, _get_revision, notify=changed)


def _read(path: str) -> str | None:
    """A kept colour (#rrggbb, or NONE); None when none is kept or it isn't one."""
    try:
        with open(path, encoding="ascii") as f:
            text = f.read().strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        log.warning("the cover colour %s couldn't be read: %s; picked again", path, e)
        return None
    if text == NONE or (len(text) == 7 and text[0] == "#" and _hex(text[1:])):
        return text
    log.warning("the cover colour %s isn't a colour (%r): picked again", path, text[:20])
    return None


def _hex(text: str) -> bool:
    try:
        int(text, 16)
    except ValueError:
        return False
    return True


def _keep(path: str, text: str) -> None:
    """Writes a colour beside its thumbnail, whole or not at all; a failure costs only time."""
    folder = os.path.dirname(path)
    tmp = ""
    try:
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=folder)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(text + "\n")
        os.replace(tmp, path)
    except OSError as e:
        log.warning("the cover colour %s couldn't be kept: %s", path, e)
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
