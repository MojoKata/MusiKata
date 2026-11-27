"""The tour (A1.6): `--tour DIR` drives the real app through each screen of the mockups on the
demo library and saves DIR/<screen>.png, offscreen; every screen's visible text is checked against
the box it is drawn in (layout.py), at the mockups' size and at the design point (R6.2.1), and what
runs past its box is written to DIR/layout.txt and fails the tour.

A screen shows one of three states the app starts in, and a run takes the screens of the state it
started in: the library ("library"), the first start (R2.1, "first-run": nothing configured and no
root given), or the library of a root that isn't there (R2.10, "unavailable": a root given that
isn't there, whose index an earlier run made). scripts/test-tour.sh starts it in each; nothing is
faked to show them.

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
from .albumart import AlbumArt
from .bridges import Library, Player
from .edittags import EditTags
from .genres import Genres
from .history import ChangeHistory

# the mockups' size, the smallest the layout is checked at, and the screenshots'; the design point,
# MusiKata maximized on a 1920 x 1080 screen (R6.2.1), less what a panel or taskbar takes
SHOT = (1280, 800)
DESIGN = (1920, 1040)
SIZES = (SHOT, DESIGN)

# (screen, what the window shows, as Library.go takes it): a screen is named for its mockup
# (docs/mockups/README.md), L03 by its first word only (L03-songs, the name the README's screenshot
# of the latest release has); one with no mockup takes the next number of its area (Artists, R2.6,
# is L10; a search being typed, R2.7, is L12; Up next, R7.2, is N08). L03 and L07 show the Edit tags
# panel (R4.2) as their mockups do, open on the songs selected with fields typed into it ("edit");
# an album's page and an artist's show a search typed into the header over them, as their mockups
# do (L02, L11, R2.7); Folders' screens (R2.9) leave out what later slices draw (the state dots and
# chips of R3.9, the tint by a cover's colour). The first queues Glass Harbor, paused at its first
# song, so every screen after it shows the now-playing bar (R6.5) and the playing album and song
# marked, with no sound to wait on (Player.go). X03 has no mockup: the Change history panel (R4.9)
# over Songs, listing the demo library's saves (demo_library.HISTORY). T07 has no mockup either: a
# bulk tool's preview (R4.5, R3.7), Number tracks over L03's four songs. T02 is the Album art dialog
# (R5.2) over Glass Harbor's page, as its mockup draws it. G01 is Genres (R9.1) with the banner of
# the demo library's near duplicates (R9.5) and Electronic's ⋯ menu open, as its mockup draws it.
STEPS: list[tuple[str, dict[str, Any]]] = [
    ("L01-albums", {"view": "albums", "queue": "Glass Harbor"}),
    ("L02-album", {"view": "album", "album": "Glass Harbor", "search": "rating:>=4"}),
    ("L10-artists", {"view": "artists"}),
    ("L11-artist", {"view": "artist", "artist": "Lumen Drift", "search": "ebb"}),
    (
        "L03-songs",
        {
            "view": "songs",
            "search": "electronic",
            "select": ["Neap Tide", "Spring Tide", "Slack Water", "Moonpull"],
            "edit": {"artist": "Lumen Drift", "genres": "Electronic", "year": "2022"},
        },
    ),
    (
        "T07-number-tracks",
        {
            "view": "songs",
            "search": "electronic",
            "select": ["Neap Tide", "Spring Tide", "Slack Water", "Moonpull"],
            "edit": {},
            "tool": {"name": "number"},
        },
    ),
    ("L04-folders", {"view": "folders", "folder": "", "mode": "small"}),
    ("L05-folders-large", {"view": "folders", "folder": "Lumen Drift", "mode": "large"}),
    (
        "L06-folders-cards",
        {
            "view": "folders",
            "folder": "",
            "mode": "cards",
            "select": ["Lumen Drift", "Mara Okafor"],
        },
    ),
    (
        "L07-folders-list",
        {
            "view": "folders",
            "folder": "Mara Okafor",
            "mode": "list",
            "select": ["Mara Okafor/Kindling", "Mara Okafor/Kindling (acoustic).m4a"],
            "edit": {"album": "Kindling", "genres": "Soul"},
        },
    ),
    ("L08-folder-songs", {"view": "folders", "folder": "Lumen Drift/Tide Tables", "mode": "small"}),
    ("L12-search", {"view": "albums", "search": "lumen dri"}),
    (
        "N08-up-next",
        {
            "view": "album",
            "album": "Glass Harbor",
            "queue": "Glass Harbor",
            "at": 3,
            "added": ["Neap Tide", "Moonpull"],
            "upNext": True,
        },
    ),
    ("T02-album-art", {"view": "album", "album": "Glass Harbor", "art": True}),
    ("G01-genres", {"view": "genres", "genreMenu": "Electronic"}),
    ("X03-change-history", {"view": "songs", "select": [], "history": True}),
    ("X01-first-run", {"state": "first-run"}),
    ("X02-root-unavailable", {"state": "unavailable", "view": "albums"}),
]
POLL = 20  # ms between looks at whether the covers have loaded
PATIENCE = 30_000  # ms the covers may take before the shot is taken anyway, and the tour fails


def state_of(library: Library | None) -> str:
    """The state a run started in: "first-run" (no library yet), "unavailable" (its root isn't
    there) or "library"."""
    if library is None:
        return "first-run"
    return "library" if library.available else "unavailable"


def screens(state: str) -> list[str]:
    """The screens a run started in `state` takes."""
    return [name for name, step in STEPS if step.get("state", "library") == state]


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
        library: Library | None,
        out: str,
        only: str = "",
        done: Callable[[int], None] = _quit,
        player: Player | None = None,
        history: ChangeHistory | None = None,
        edit: EditTags | None = None,
        art: AlbumArt | None = None,
        genres: Genres | None = None,
    ) -> None:
        super().__init__(window)
        names = [n for n in only.split(",") if n]
        unknown = set(names) - {n for n, _ in STEPS}
        if unknown:
            raise ValueError(f"no such screen: {', '.join(sorted(unknown))}")
        mine = screens(state_of(library))
        self.steps = [(n, s) for n, s in STEPS if n in mine and (not names or n in names)]
        self.win, self.library, self.out, self.done = window, library, out, done
        self.player, self.history, self.edit, self.art = player, history, edit, art
        self.genres = genres
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
        if self.library is not None and self.library.scanning:
            self.library.scanningChanged.connect(self._scanned)
        else:
            QTimer.singleShot(0, self._step)

    def _scanned(self) -> None:
        if self.library is not None and not self.library.scanning:
            self.library.scanningChanged.disconnect(self._scanned)
            self._step()

    def _step(self) -> None:
        if self._i >= len(self.steps):
            self._finish()
            return
        name, step = self.steps[self._i]
        if self.library is not None and "view" in step:
            self.library.go(step)
        if self.player is not None and "view" in step:
            self.player.go(step)
        if self.history is not None and "view" in step:
            self.history.go(step)
        if self.edit is not None and self.library is not None and "view" in step:
            self.edit.go(step, self.library)
        if self.art is not None and self.library is not None and "view" in step:
            self.art.go(step, self.library)
        if self.genres is not None and "view" in step:
            self.genres.go(step)
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
        if self.library is not None and isinstance(self.library.last, BaseException):
            self.faults.append(f"the scan failed: {self.library.last!r}")
        os.makedirs(self.out, exist_ok=True)
        with open(os.path.join(self.out, "layout.txt"), "w", encoding="utf-8") as f:
            f.writelines(line + "\n" for line in self.faults)
        for line in self.faults:
            print("layout:", line, flush=True)
        print(f"the tour: {len(self.saved)} screens, {len(self.faults)} texts past their boxes")
        self.done(1 if self.faults else 0)
