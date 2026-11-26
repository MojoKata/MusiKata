"""The tour (A1.6): `--tour DIR` drives the real app through each screen of the mockups on the
demo library and saves DIR/<screen>.png, offscreen; every screen's visible text is checked against
the box it is drawn in (layout.py), at the mockups' size and at the design point (R6.2.1), and what
runs past its box is written to DIR/layout.txt and fails the tour.

Each step waits for what it needs (the scan to end, the window to take its size, the covers to
load, a search's rows to come), never a fixed time (docs/process/testing.md, "Principles"): what
loads off the GUI thread is polled for until nothing on the screen says it is `loading`."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickWindow

from . import layout
from .bridges import Library

# the mockups' size, the smallest the layout is checked at, and the screenshots'; the design point,
# MusiKata maximized on a 1920 x 1080 screen (R6.2.1), less what a panel or taskbar takes
SHOT = (1280, 800)
DESIGN = (1920, 1040)
SIZES = (SHOT, DESIGN)

# (screen, what the window shows, as Library.go takes it): a screen is named for its mockup
# (docs/mockups/README.md); one that shows only part of its mockup yet says so (L03 without the
# Edit tags panel, which comes with slice 5); one with no mockup takes the next number of its area
# (Artists and an artist's page, R2.6, are L10 and L11; a search being typed, R2.7, is L12)
STEPS: list[tuple[str, dict[str, Any]]] = [
    ("L01-albums", {"view": "albums"}),
    ("L02-album", {"view": "album", "album": "Glass Harbor"}),
    ("L10-artists", {"view": "artists"}),
    ("L11-artist", {"view": "artist", "artist": "Lumen Drift"}),
    ("L03-songs", {"view": "songs"}),
    ("L12-search", {"view": "albums", "search": "lumen dri"}),
]
POLL = 20  # ms between looks at whether the covers have loaded
PATIENCE = 30_000  # ms the covers may take before the shot is taken anyway, and the tour fails


def loading(item: QQuickItem) -> bool:
    """Whether a visible item under `item` says it is still `loading` (a cover, Cover.qml)."""
    if not item.isVisible():
        return False
    if item.property("loading") is True:
        return True
    return any(loading(child) for child in item.childItems())


def _quit(code: int) -> None:
    QGuiApplication.exit(code)


class Tour(QObject):
    def __init__(
        self,
        window: QQuickWindow,
        library: Library,
        out: str,
        only: str = "",
        done: Callable[[int], None] = _quit,
    ) -> None:
        super().__init__(window)
        names = [n for n in only.split(",") if n]
        unknown = set(names) - {n for n, _ in STEPS}
        if unknown:
            raise ValueError(f"no such screen: {', '.join(sorted(unknown))}")
        self.steps = [(n, s) for n, s in STEPS if not names or n in names]
        self.win, self.library, self.out, self.done = window, library, out, done
        self.faults: list[str] = []
        self.saved: list[str] = []
        self._i = 0
        self._size = 0
        self._waiting: Callable[[], None] | None = None
        self._waited = 0

    def start(self) -> None:
        """Shows the window at the mockups' size, then steps through once no scan runs."""
        self.win.setWidth(SHOT[0])
        self.win.setHeight(SHOT[1])
        self.win.show()
        if self.library.scanning:
            self.library.scanningChanged.connect(self._scanned)
        else:
            QTimer.singleShot(0, self._step)

    def _scanned(self) -> None:
        if not self.library.scanning:
            self.library.scanningChanged.disconnect(self._scanned)
            self._step()

    def _step(self) -> None:
        if self._i >= len(self.steps):
            self._finish()
            return
        name, step = self.steps[self._i]
        self.library.go(step)
        self._size = 0
        self._at_size()

    def _at_size(self) -> None:
        """The current step at its next size, once the window has taken it."""
        w, h = SIZES[self._size]
        if self.win.width() == w and self.win.height() == h:
            QTimer.singleShot(0, self._shot)
            return
        self._waiting = self._resized
        self.win.widthChanged.connect(self._resized)
        self.win.heightChanged.connect(self._resized)
        self.win.setWidth(w)
        self.win.setHeight(h)

    def _resized(self) -> None:
        w, h = SIZES[self._size]
        if self.win.width() == w and self.win.height() == h and self._waiting:
            self._waiting = None
            self.win.widthChanged.disconnect(self._resized)
            self.win.heightChanged.disconnect(self._resized)
            QTimer.singleShot(0, self._shot)

    def _shot(self) -> None:
        """Renders the step once, so its views make their rows and ask for their covers, then
        waits for the covers."""
        self.win.grabWindow()
        self._waited = 0
        self._settle()

    def _settle(self) -> None:
        name = self.steps[self._i][0]
        if loading(self.win.contentItem()):
            if self._waited < PATIENCE:
                self._waited += POLL
                QTimer.singleShot(POLL, self._settle)
                return
            self.faults.append(f"{name}: covers still loading after {PATIENCE // 1000} s")
        QTimer.singleShot(0, self._take)

    def _take(self) -> None:
        name = self.steps[self._i][0]
        w, h = SIZES[self._size]
        image = self.win.grabWindow()
        if SIZES[self._size] == SHOT:
            os.makedirs(self.out, exist_ok=True)
            path = os.path.join(self.out, f"{name}.png")
            image.save(path)
            self.saved.append(path)
        for fault in layout.faults(self.win):
            self.faults.append(f"{name} at {w} x {h}: {fault['line']}")
        self._size += 1
        if self._size < len(SIZES):
            self._at_size()
        else:
            self._i += 1
            QTimer.singleShot(0, self._step)

    def _finish(self) -> None:
        if isinstance(self.library.last, BaseException):
            self.faults.append(f"the scan failed: {self.library.last!r}")
        os.makedirs(self.out, exist_ok=True)
        with open(os.path.join(self.out, "layout.txt"), "w", encoding="utf-8") as f:
            f.writelines(line + "\n" for line in self.faults)
        for line in self.faults:
            print("layout:", line, flush=True)
        print(f"the tour: {len(self.saved)} screens, {len(self.faults)} texts past their boxes")
        self.done(1 if self.faults else 0)
