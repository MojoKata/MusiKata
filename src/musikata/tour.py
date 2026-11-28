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

from PySide6.QtCore import QObject, QPoint, QRect, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QWindow
from PySide6.QtQuick import QQuickItem, QQuickWindow

from . import layout
from .albumart import AlbumArt
from .analyzeritem import Analyzer
from .attention import Attention
from .bridges import Library, Player
from .dragging import Dragging
from .duplicates import Duplicates
from .edittags import EditTags
from .encodings import FixEncoding
from .genres import Genres
from .history import ChangeHistory
from .infer import InferFromPath
from .lyrics import Lyrics
from .miniplayer import MiniPlayer
from .nowplayingview import NowPlayingView
from .organize import OrganizeFiles
from .removing import Removing
from .smart import SmartPlaylists
from .tints import Tints

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
# an album's page and an artist's show a search typed into the header over them, as their mockups do
# (L02, L11, R2.7); an album's page and Folders' Cards are tinted by their covers' colours (R6.2.2),
# which are waited for as the covers are. N01, N02 and N03 are Now Playing (R11.4) over Glass
# Harbor's page, cued at Signal Fires with two songs added, with Waveform (R11.4.1), 3D analyzer
# (R11.4.2) and No visualization (R11.4.3): paused, as every screen is, so the cover's spectrum has
# settled to nothing, and the analyzer shows a still landscape of generated spectra, as the mockup
# draws one (analyzeritem.generated: with nothing heard it would be flat). N04 is N03 with the
# Lyrics switch on (R17.3): Signal Fires' timed lyrics from the demo library's .lrc, followed as at
# 1:38 into the song, the place N04 draws (Lyrics.go: the demo library's songs last a second).
# T01 is Infer tags from path (R3) over L08's folder of songs, as its mockup draws it; T03 is
# Organize files (R12) over Your music folders, on the whole library, as its mockup draws it. The
# first queues Glass Harbor, paused at its first song, so every screen after it shows the
# now-playing bar (R6.5) and the playing album and song marked, with no sound to wait on
# (Player.go). X03 has no mockup: the Change history panel (R4.9) over Songs, listing the demo
# library's saves (demo_library.HISTORY). T07 has no mockup either: a bulk tool's preview (R4.5,
# R3.7), Number tracks over L03's four songs. T02 is the Album art dialog (R5.2) over Glass Harbor's
# page, as its mockup draws it. G01 is Genres (R9.1) with the banner of the demo library's near
# duplicates (R9.5) and Electronic's ⋯ menu open, as its mockup draws it. L09 is Needs attention
# (R2.8) with Same song twice chosen (R2.12), its groups of copies open and the other groups folded
# after it, as its mockup draws it. L14 has no mockup: Move to trash's question (R2.11) over
# Folders, about Mara Okafor's Kindling, drawn after L13's. L13 has no mockup: the Review… dialog
# of Signal Fires' copies
# (R2.12) over it, drawn after T01's preview. T06 is Fix encoding… (R4.10) over it, on the demo
# library's Маяк, saved as Windows-1251 in a Latin-1 frame, as its mockup draws it. P01 is Road
# Trip's page (R8.2) with the sidebar's playlists (R6.3) and a drag held still (R8.5, R6.10), as
# its mockup draws it: three of its songs selected and carried onto Evening Focus, highlighted and
# named, the drag's card under it, and the insertion line a reorder would land on (Dragging.go:
# offscreen, no platform drag can be held, so the targets' state is set directly). P02 has no
# mockup: Four stars and up's page, a smart playlist (R8.9) drawn after P01, its kicker saying so,
# its rule in words under its line, Edit rule beside Export… and its rows without drag handles; P03
# is its Edit rule dialog over it, drawn after Export…'s. M01 is the mini player's seven layouts
# (R15.3), a screen each (M01-mini-1-strip …), over Glass Harbor cued at Signal Fires as N01 is:
# Cover's controls shown as under the pointer, as the mockup draws it, and Analyzer's landscape the
# generated one N02's is; M02 is the Remote with its right-click menu open (R15.4). Each is the
# mini player's own window (and its menu's) on a plain desktop, at its layout's default size.
MINI = {"view": "album", "album": "Glass Harbor", "queue": "Glass Harbor", "at": 3,
        "added": ["Neap Tide", "Moonpull"]}  # fmt: skip
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
    (
        "T01-infer-from-path",
        {"view": "folders", "folder": "Lumen Drift/Tide Tables", "mode": "small", "infer": True},
    ),
    ("T03-organize-files", {"view": "folders", "folder": "", "mode": "small", "organize": ""}),
    (
        "L14-move-to-trash",
        {
            "view": "folders",
            "folder": "Mara Okafor",
            "mode": "small",
            "trash": "Mara Okafor/Kindling",
        },
    ),
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
    (
        "N01-now-playing-waveform",
        {
            "view": "album",
            "album": "Glass Harbor",
            "queue": "Glass Harbor",
            "at": 3,
            "added": ["Neap Tide", "Moonpull"],
            "nowPlaying": "waveform",
        },
    ),
    (
        "N02-now-playing-3d-analyzer",
        {
            "view": "album",
            "album": "Glass Harbor",
            "queue": "Glass Harbor",
            "at": 3,
            "added": ["Neap Tide", "Moonpull"],
            "nowPlaying": "analyzer",
            "landscape": True,
        },
    ),
    (
        "N03-now-playing-queue",
        {
            "view": "album",
            "album": "Glass Harbor",
            "queue": "Glass Harbor",
            "at": 3,
            "added": ["Neap Tide", "Moonpull"],
            "nowPlaying": "none",
        },
    ),
    (
        "N04-now-playing-lyrics",
        {
            "view": "album",
            "album": "Glass Harbor",
            "queue": "Glass Harbor",
            "at": 3,
            "added": ["Neap Tide", "Moonpull"],
            "nowPlaying": "none",
            "lyrics": {"at": 98},
        },
    ),
    ("M01-mini-1-strip", {**MINI, "mini": "strip"}),
    ("M01-mini-2-cover", {**MINI, "mini": "cover", "miniHover": True}),
    ("M01-mini-3-card", {**MINI, "mini": "card"}),
    ("M01-mini-4-analyzer", {**MINI, "mini": "analyzer", "landscape": True}),
    ("M01-mini-5-disc", {**MINI, "mini": "disc"}),
    ("M01-mini-6-details", {**MINI, "mini": "details"}),
    ("M01-mini-7-remote", {**MINI, "mini": "remote"}),
    ("M02-mini-player-menu", {**MINI, "mini": "remote", "miniMenu": True}),
    ("T02-album-art", {"view": "album", "album": "Glass Harbor", "art": True}),
    ("G01-genres", {"view": "genres", "genreMenu": "Electronic"}),
    ("L09-needs-attention", {"view": "attention", "attention": "copies"}),
    (
        "L13-same-song-review",
        {"view": "attention", "attention": "copies", "review": "Signal Fires"},
    ),
    ("T06-fix-encoding", {"view": "attention", "attention": "copies", "fix": "Маяк"}),
    (
        "P01-playlist-drag",
        {
            "view": "playlist",
            "playlist": "Road Trip",
            "drag": {"rows": [1, 2, 3], "onto": "Evening Focus", "line": 5},
        },
    ),
    ("P02-smart-playlist", {"view": "playlist", "playlist": "Four stars and up"}),
    ("P03-smart-rule", {"view": "playlist", "playlist": "Four stars and up", "rule": True}),
    ("X03-change-history", {"view": "songs", "select": [], "history": True}),
    ("X01-first-run", {"state": "first-run"}),
    ("X02-root-unavailable", {"state": "unavailable", "view": "albums"}),
]
POLL = 20  # ms between looks at whether the covers have loaded
DESKTOP = QColor("#12151f")  # what the mini player's screens show behind its window
ROOM = 40  # their room around it
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


def analyzers(item: QQuickItem) -> list[Analyzer]:
    """The 3D analyzers under `item`, shown or not."""
    found = [item] if isinstance(item, Analyzer) else []
    for child in item.childItems():
        found.extend(analyzers(child))
    return found


def desktop(shots: list[tuple[QRect, QImage]]) -> QImage:
    """Windows' pictures, each at its place on the screen, on a plain desktop ROOM wider than
    them all (the mini player and its menu, M01, M02)."""
    if not shots:
        return QImage()
    whole = QRect(shots[0][0])
    for place, _ in shots[1:]:
        whole = whole.united(place)
    whole.adjust(-ROOM, -ROOM, ROOM, ROOM)
    image = QImage(whole.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(DESKTOP)
    painter = QPainter(image)
    for place, shot in shots:
        painter.drawImage(place.topLeft() - whole.topLeft(), shot)
    painter.end()
    return image


def popups(skip: list[QWindow]) -> list[QQuickWindow]:
    """The windows shown but those of `skip`: a menu's or a tooltip's of its own (Popup.Window)."""
    return [
        w
        for w in QGuiApplication.topLevelWindows()
        if isinstance(w, QQuickWindow) and w.isVisible() and all(w is not s for s in skip)
    ]


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
        attention: Attention | None = None,
        copies: Duplicates | None = None,
        encodings: FixEncoding | None = None,
        infer: InferFromPath | None = None,
        dragging: Dragging | None = None,
        smart: SmartPlaylists | None = None,
        organize: OrganizeFiles | None = None,
        removing: Removing | None = None,
        now: NowPlayingView | None = None,
        tints: Tints | None = None,
        lyrics: Lyrics | None = None,
        mini: MiniPlayer | None = None,
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
        self.genres, self.attention, self.copies = genres, attention, copies
        self.encodings, self.infer, self.dragging = encodings, infer, dragging
        self.smart, self.organize, self.removing = smart, organize, removing
        self.now, self.tints, self.lyrics, self.mini = now, tints, lyrics, mini
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
        if self.attention is not None and "view" in step:
            self.attention.go(step)
        if self.copies is not None and "view" in step:
            self.copies.go(step)
        if self.encodings is not None and "view" in step:
            self.encodings.go(step)
        if self.infer is not None and "view" in step:
            self.infer.go(step)
        if self.dragging is not None and "view" in step:
            self.dragging.go(step)
        if self.smart is not None and "view" in step:
            self.smart.go(step)
        if self.organize is not None and "view" in step:
            self.organize.go(step)
        if self.removing is not None and "view" in step:
            self.removing.go(step)
        if self.lyrics is not None and "view" in step:
            self.lyrics.go(step)
        if self.now is not None and "view" in step:
            self.now.go(step)
        if self.mini is not None and "view" in step:
            self.mini.go(step)
        if "view" in step:
            for window in self._windows():
                for analyzer in analyzers(window.contentItem()):
                    analyzer.go(step)
        self._size = 0
        self._at_size()

    def _windows(self) -> list[QQuickWindow]:
        """The windows the step shows: the main window, and the mini player's when it is open."""
        found = [self.win]
        shown = self.mini.window if self.mini is not None else None
        if isinstance(shown, QQuickWindow) and shown.isVisible():
            found.append(shown)
        return found

    def _target(self) -> QQuickWindow:
        """The window the current step's screen is of: the mini player's for M01 and M02."""
        shown = self.mini.window if self.mini is not None else None
        if "mini" in self.steps[self._i][1] and isinstance(shown, QQuickWindow):
            return shown
        return self.win

    def _at_size(self) -> None:
        """The current step at its next size, once the window has taken it; the mini player at
        its layout's own."""
        if self._target() is not self.win:
            self._size = len(SIZES) - 1
            QTimer.singleShot(0, self._shot)
            return
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
        self._target().grabWindow()
        self._waited = 0
        self._settle()

    def _settle(self) -> None:
        name = self.steps[self._i][0]
        if loading(self._target().contentItem()) or (self.tints is not None and self.tints.busy):
            if self._waited < PATIENCE:
                self._waited += POLL
                QTimer.singleShot(POLL, self._settle)
                return
            self.faults.append(f"{name}: covers still loading after {PATIENCE // 1000} s")
        QTimer.singleShot(0, self._take)

    def _take(self) -> None:
        name = self.steps[self._i][0]
        target = self._target()
        w, h = SIZES[self._size] if target is self.win else (target.width(), target.height())
        shown = [target] if target is self.win else [target, *popups([self.win, target])]
        if target is self.win:
            image = target.grabWindow()
        else:
            image = desktop(
                [(QRect(QPoint(s.x(), s.y()), s.size()), s.grabWindow()) for s in shown]
            )
        if SIZES[self._size] == SHOT or target is not self.win:
            os.makedirs(self.out, exist_ok=True)
            path = os.path.join(self.out, f"{name}.png")
            image.save(path)
            self.saved.append(path)
        for window in shown:
            for fault in layout.faults(window):
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
