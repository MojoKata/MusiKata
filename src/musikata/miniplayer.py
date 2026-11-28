"""The mini player (R15), as QML sees it: a second top-level window from the main window's engine
(A1.8, MiniPlayer.qml), bound to the same Player bridge and models, its seven layouts (R15.3) each
a component loaded into it.

Opening it (the bar's pop-out button, ⋮ › Mini player, Ctrl+Shift+M: R15.1) shows it at its
layout's place and minimizes the main window when the shared settings' `minimize_for_mini` says so
(R13.8, on by default); Show MusiKata (its menu, its MusiKata icon, Ctrl+Shift+M again), its × and
Close mini player hide it and bring the main window back as it was. Neither touches the player:
playback never stops (R15.1).

The window (R15.2) is frameless, its rounded card drawn inside a margin that holds its shadow; a
place is the card's, in the screen's pixels, and the window is the card with the margin around it
(`window_of`, `card_of`). It is moved and resized by the system (`startSystemMove`,
`startSystemResize`, in QML) within its layout's limits (`Layout.least`, `Layout.most`); once it has
stood still for SETTLE_MS it snaps to the edges of the screen it is on (`snapped`), and its place is
kept, per layout, with its layout and Stay on top, in the shared settings' `mini_player` (A2.10),
written on the thread that keeps the rest of them (Player.remember_mini). A place that is off every
screen comes back on (`on_screen`); a layout chosen takes its own kept size where the window is,
keeping the corner nearest its screen's (`switched`).

What it says of the song (R15.3) is decided here: the line under the title, the Card's track line
and its artist, year and genre, the next song in the queue, the Remote's tooltip; with no song
playing it shows the last one, paused (R15.5), and play plays it again. The scroll wheel over it
changes the volume (`volume_after`, R15.4).

Its visuals (R15.5) are the main window's items (spectrumitem, analyzeritem, waveitem, discitem),
each stopping when its window is hidden or minimized or playback is paused; `exposed` adds the
window being covered, as far as Qt can tell: it follows the window's expose events, which macOS
sends when a window is wholly covered (by a full-screen window among others); on X11, Wayland and
Windows Qt reports a window hidden or minimized, never covered, so there it draws on.

Everything decided is a plain function of plain data (docs/process/coding.md); the class is the
glue."""

from __future__ import annotations

import math
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QEvent, QObject, QRect, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QWindow

from musikata_core.settings import MINI_LAYOUT, MINI_LAYOUTS, Place
from musikata_core.settings import MiniPlayer as Kept

from .models import artist_text, time_text
from .nowplaying import SongInfo, read_songs

Rect = tuple[int, int, int, int]  # x, y, width, height
MARGIN = 14  # the window's room around its card for the card's shadow (R15.2)
SNAP = 16  # how near a screen's edge the card snaps to it, in pixels (R15.2)
GAP = 24  # a new or lost place's distance from its screen's corner
SHOWN = 40  # how much of the card a screen must show, each way, for its place to be on it
SETTLE_MS = 400  # how long the window stands still before it snaps and its place is kept
NOTCH = 120  # a wheel's notch, in Qt's eighths of a degree
VOLUME_STEP = 0.05  # the volume a notch changes (R15.4)
SLEEP_LATER = "The sleep timer comes in a later version"  # R7.10: slice 9 (#26)


@dataclass(frozen=True)
class Layout:
    """One of R15.3's layouts: its setting's name, the name the menu shows, its number, its
    default size, the smallest and largest it can be resized to, whether it shows the MusiKata
    icon in a corner (R15.4: all but Strip and Remote), whether its controls show only under the
    pointer (Cover), and its corners' radius (M01)."""

    name: str
    title: str
    number: int
    size: tuple[int, int]
    least: tuple[int, int]
    most: tuple[int, int]
    logo: bool = True
    hover: bool = False
    radius: int = 14


LAYOUTS = (
    Layout("strip", "Strip", 1, (496, 76), (400, 76), (900, 76), logo=False),
    Layout("cover", "Cover", 2, (300, 300), (200, 200), (640, 640), hover=True, radius=16),
    Layout("card", "Card", 3, (300, 582), (260, 540), (420, 720), radius=18),
    Layout("analyzer", "Analyzer", 4, (496, 170), (360, 140), (1000, 420)),
    Layout("disc", "Disc", 5, (240, 320), (240, 320), (400, 520), radius=22),
    Layout("details", "Details", 6, (300, 240), (280, 240), (520, 280), radius=18),
    Layout("remote", "Remote", 7, (246, 76), (246, 76), (400, 76), logo=False),
)
assert tuple(lay.name for lay in LAYOUTS) == MINI_LAYOUTS  # the settings' names, in R15.3's order


def layout_named(name: str) -> Layout:
    """The layout of that name; the default (Card) for a name it doesn't have."""
    for lay in LAYOUTS:
        if lay.name == name:
            return lay
    return layout_named(MINI_LAYOUT)


def fitted(layout: Layout, width: int, height: int) -> tuple[int, int]:
    """A size held within the layout's limits."""
    return (
        max(layout.least[0], min(layout.most[0], width)),
        max(layout.least[1], min(layout.most[1], height)),
    )


def window_of(card: Rect) -> Rect:
    """The window around a card: the card with the shadow's MARGIN on every side."""
    x, y, w, h = card
    return x - MARGIN, y - MARGIN, w + 2 * MARGIN, h + 2 * MARGIN


def card_of(window: Rect) -> Rect:
    """The card inside a window (`window_of` undone)."""
    x, y, w, h = window
    return x + MARGIN, y + MARGIN, w - 2 * MARGIN, h - 2 * MARGIN


def overlap(a: Rect, b: Rect) -> tuple[int, int]:
    """How much of `a` and `b` overlap, across and down (0 when they don't)."""
    across = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    down = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, across), max(0, down)


def area_of(card: Rect, areas: Sequence[Rect]) -> Rect:
    """The screen area (of `areas`, the primary first) that shows most of the card; the one
    nearest it when none does."""
    if not areas:
        return card
    shown = [overlap(card, a) for a in areas]
    best = max(range(len(areas)), key=lambda i: shown[i][0] * shown[i][1])
    if shown[best][0] * shown[best][1] > 0:
        return areas[best]
    cx, cy = card[0] + card[2] / 2, card[1] + card[3] / 2

    def distance(a: Rect) -> float:
        dx = max(a[0] - cx, 0, cx - (a[0] + a[2]))
        dy = max(a[1] - cy, 0, cy - (a[1] + a[3]))
        return dx * dx + dy * dy

    return min(areas, key=distance)


def inside(card: Rect, area: Rect) -> Rect:
    """The card moved the least that puts it wholly inside the area; one larger than it, at its
    top left."""
    x, y, w, h = card
    x = max(area[0], min(x, area[0] + area[2] - w))
    y = max(area[1], min(y, area[1] + area[3] - h))
    return x, y, w, h


def corner(size: tuple[int, int], area: Rect) -> Rect:
    """A card of `size` GAP in from the bottom right corner of the area, as M02 shows it, and
    wholly inside it."""
    w, h = size
    return inside((area[0] + area[2] - GAP - w, area[1] + area[3] - GAP - h, w, h), area)


def default_place(layout: Layout, area: Rect) -> Rect:
    """A layout's place when it has none kept: at its default size, in the area's (the primary
    screen's) bottom right corner (`corner`)."""
    return corner(layout.size, area)


def on_screen(card: Rect, areas: Sequence[Rect]) -> Rect:
    """The card where it is, when a screen shows SHOWN pixels of it each way (all of it, when it
    is smaller); otherwise (a screen unplugged, a resolution changed, a hand edit) in the primary
    screen's corner (`corner`), keeping its size."""
    for area in areas:
        across, down = overlap(card, area)
        if across >= min(SHOWN, card[2]) and down >= min(SHOWN, card[3]):
            return card
    return corner((card[2], card[3]), areas[0]) if areas else card


def snapped(card: Rect, areas: Sequence[Rect], distance: int = SNAP) -> Rect:
    """The card snapped to the edges of the screen it is on (R15.2): an edge within `distance`
    of the area's same edge is moved onto it, the left before the right and the top before the
    bottom."""
    if not areas:
        return card
    ax, ay, aw, ah = area_of(card, areas)
    x, y, w, h = card
    if abs(x - ax) <= distance:
        x = ax
    elif abs(ax + aw - (x + w)) <= distance:
        x = ax + aw - w
    if abs(y - ay) <= distance:
        y = ay
    elif abs(ay + ah - (y + h)) <= distance:
        y = ay + ah - h
    return x, y, w, h


def switched(card: Rect, size: tuple[int, int], areas: Sequence[Rect]) -> Rect:
    """Where a layout chosen goes: at `size`, where the card was, keeping the corner of it nearest
    its screen's same corner (a card snapped to the bottom right stays there as it grows), and
    wholly on that screen."""
    x, y, w, h = card
    nw, nh = size
    area = area_of(card, areas) if areas else card
    left, right = x - area[0], area[0] + area[2] - (x + w)
    top, bottom = y - area[1], area[1] + area[3] - (y + h)
    nx = x + w - nw if right < left else x
    ny = y + h - nh if bottom < top else y
    return inside((nx, ny, nw, nh), area) if areas else (nx, ny, nw, nh)


def place_for(layout: Layout, kept: Mapping[str, Place], areas: Sequence[Rect]) -> Rect:
    """Where a layout opens: its kept place, its size held within its limits, back on a screen
    when it is off every one (`on_screen`); its default place when none is kept."""
    if layout.name in kept:
        x, y, w, h = kept[layout.name]
        w, h = fitted(layout, w, h)
        return on_screen((x, y, w, h), areas)
    return default_place(layout, areas[0]) if areas else (0, 0, *layout.size)


def progress_path(width: float, height: float, radius: float, thick: float, share: float) -> str:
    """The progress line along the foot of a card `width` × `height` with corners of `radius`
    (R15.3): the band `thick` high along its foot, from its left to `share` (0 to 1) of its width,
    inside its rounded corners, as an SVG path; "" when none of it shows."""
    r = max(0.0, min(radius, width / 2, height / 2))
    to = width * max(0.0, min(1.0, share))

    def foot(x: float) -> float:  # the card's lower edge at x, round its corners
        corner = r - x if x < r else x - (width - r) if x > width - r else 0.0
        return height - r + math.sqrt(max(0.0, r * r - corner * corner)) if corner > 0 else height

    top = height - thick
    inset = r - math.sqrt(max(0.0, r * r - (r - thick) ** 2)) if r > thick else 0.0
    lo, hi = inset, min(to, width - inset)
    if hi <= lo or thick <= 0:
        return ""
    steps = [lo, *(x for x in (r * k / 8 for k in range(9)) if lo < x < hi)]
    steps += [x for x in (width - r + r * k / 8 for k in range(9)) if lo < x < hi]
    steps.append(hi)
    points = [(lo, top), (hi, top)] + [(x, foot(x)) for x in sorted(set(steps), reverse=True)]
    return "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in points) + "Z"


def volume_after(volume: float, delta: int) -> float:
    """The volume after the wheel turned `delta` eighths of a degree (Qt's angleDelta): up a
    VOLUME_STEP a notch, away from the user, and down towards them; held from 0 to 1."""
    return max(0.0, min(1.0, round(volume + delta / NOTCH * VOLUME_STEP, 4)))


def menu_layouts(current: str) -> list[dict[str, Any]]:
    """The right-click menu's layouts (M02): each its name, title, number, and whether it is the
    current one, checked."""
    return [
        {"name": lay.name, "title": lay.title, "number": lay.number, "checked": lay.name == current}
        for lay in LAYOUTS
    ]


def shortcut_text(platform: str = sys.platform) -> str:
    """Show MusiKata's shortcut as the menu shows it (M02, R6.9): ⇧⌘M on macOS."""
    return "⇧⌘M" if platform == "darwin" else "Ctrl+Shift+M"


def song_line(artist: str, album: str) -> str:
    """The line under the title (M01): Lumen Drift · Glass Harbor, each part when known."""
    return " · ".join(p for p in (artist, album) if p)


def tooltip_text(title: str, artist: str) -> str:
    """The Remote's tooltip, the song it doesn't name (M02): Signal Fires — Lumen Drift."""
    return " — ".join(p for p in (title, artist) if p)


def kicker_text(track: int | None, total: int | None, album: str) -> str:
    """The Card's line over the title (M01): Track 4 of 10 · Glass Harbor, each part when
    known."""
    where = ""
    if track:
        where = f"Track {track} of {total}" if total else f"Track {track}"
    return " · ".join(p for p in (where, album) if p)


def details_line(artist: str, year: int | None, genres: Sequence[str]) -> str:
    """The Card's line under the title (M01): Lumen Drift · 2019 · Electronic."""
    return " · ".join(p for p in (artist, str(year) if year else "", ", ".join(genres)) if p)


def card_words(c: sqlite3.Connection, song: int) -> dict[str, str]:
    """What the Card and Details say of the song with id `song` beyond the bar's words: the line
    over the title and the one under it; {} when the index no longer has it."""
    row = c.execute(
        "SELECT track, tracktotal, album, artist, year FROM song WHERE id = ?", (song,)
    ).fetchone()
    if row is None:
        return {}
    track, total, album, artist, year = row
    genres = [g for (g,) in c.execute(
        "SELECT genre FROM song_genre WHERE song_id = ? ORDER BY position", (song,)
    )]  # fmt: skip
    return {
        "kicker": kicker_text(track, total, album or ""),
        "details": details_line(artist_text(artist), year, genres),
    }


def up_next_words(info: SongInfo | None) -> dict[str, str]:
    """The Card's next song in the queue (M01): its title and artist, its length, its cover; {}
    for none."""
    if info is None:
        return {}
    return {
        "line": " · ".join(p for p in (info.title, artist_text(info.artist)) if p),
        "length": time_text(info.length),
        "cover": info.cover,
    }


def screen_areas() -> list[Rect]:
    """Each screen's available area (the taskbars and panels left out), the primary first."""
    primary = QGuiApplication.primaryScreen()
    screens = QGuiApplication.screens()
    ordered = [primary, *(s for s in screens if s is not primary)] if primary else screens
    return [_rect(s.availableGeometry()) for s in ordered]


def _rect(r: QRect) -> Rect:
    return r.x(), r.y(), r.width(), r.height()


class MiniPlayer(QObject):
    """The mini player's window as QML binds it (A1.8): open or not, its layout and Stay on top as
    `kept` (settings.MiniPlayer) and kept again by `keep` (Player.remember_mini: on its thread),
    the main window minimized as it opens when `minimize` (R13.8), and what it says of the song
    `player` (the Player bridge) shows, read through `read`. `attach` gives it the two windows;
    `areas` gives the screens' areas (`screen_areas`), `settle` the milliseconds the window stands
    still before it snaps and its place is kept."""

    changed = Signal()  # open, the layout, Stay on top, exposed, the controls shown
    songChanged = Signal()  # the song's words, the next song
    placeKept = Signal()  # the window's place snapped and kept: tests wait on it
    menuRequested = Signal()  # the tour opens its menu (M02)

    def __init__(
        self,
        player: QObject,
        read: Callable[[], sqlite3.Connection] | None = None,
        kept: Kept | None = None,
        minimize: bool = True,
        keep: Callable[..., object] | None = None,
        areas: Callable[[], list[Rect]] = screen_areas,
        settle: int = SETTLE_MS,
        platform: str = sys.platform,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        kept = kept if kept is not None else Kept()
        self._player, self._read, self._keep, self._areas = player, read, keep, areas
        self._minimize, self._platform = minimize, platform
        self._layout = layout_named(kept.layout)
        self._on_top = kept.stay_on_top
        self._places: dict[str, Place] = dict(kept.places)
        self._opened = False
        self._exposed = False
        self._controls = False  # the tour shows Cover's controls as under the pointer
        self._main: QWindow | None = None
        self._window: QWindow | None = None
        self._main_was: QWindow.Visibility | None = None
        self._placing = False
        self._words: dict[str, Any] = {}
        self._last: dict[str, Any] = {}  # the song shown last, for when none is (R15.5)
        self._next: dict[str, str] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(settle)
        self._timer.timeout.connect(self._settled)
        player.changed.connect(self._song_changed)  # type: ignore[attr-defined]
        player.queueChanged.connect(self._queue_changed)  # type: ignore[attr-defined]

    # ---------- the windows ----------

    def attach(self, main: QWindow, window: QWindow) -> None:
        """The main window, and the mini player's own (MiniPlayer.qml's), once loaded: its moves
        and resizes followed, and its expose events watched."""
        self._main, self._window = main, window
        for signal in (window.xChanged, window.yChanged, window.widthChanged,
                       window.heightChanged):  # fmt: skip
            signal.connect(self._moved)
        window.visibleChanged.connect(self._window_shown)
        main.visibleChanged.connect(self._main_shown)
        window.installEventFilter(self)

    def detach(self) -> None:
        """The windows going (a root opened in their place, MusiKata quitting): hidden, and let
        go of, nothing brought back."""
        self._timer.stop()
        window, self._window, self._main = self._window, None, None
        self._opened = False
        if window is not None:
            window.removeEventFilter(self)
            window.hide()

    def _window_shown(self, shown: bool) -> None:
        """Its window hidden by the system (Alt+F4, the window manager): as its × does."""
        if not shown and self._opened:
            self.close()

    def _main_shown(self, shown: bool) -> None:
        """The main window closed (from the taskbar, while minimized): this one goes with it, so
        MusiKata quits as its last window closes; nothing is brought back."""
        if not shown and self._opened:
            self._opened = False
            self._timer.stop()
            if self._window is not None:
                self._window.hide()
            self.changed.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._window and event.type() in (
            QEvent.Type.Expose, QEvent.Type.Show, QEvent.Type.Hide,
            QEvent.Type.WindowStateChange,
        ):  # fmt: skip
            self._update_exposed()
        return False

    def _update_exposed(self) -> None:
        w = self._window
        exposed = (
            w is not None
            and w.isVisible()
            and w.isExposed()
            and w.visibility() != QWindow.Visibility.Minimized
        )
        if exposed != self._exposed:
            self._exposed = exposed
            self.changed.emit()

    def _place(self, card: Rect) -> None:
        """Puts the window around `card`, its moves not taken for the user's."""
        if self._window is None:
            return
        self._placing = True
        try:
            self._window.setGeometry(QRect(*window_of(card)))
        finally:
            self._placing = False

    def _card(self) -> Rect | None:
        return card_of(_rect(self._window.geometry())) if self._window is not None else None

    # ---------- opening and closing (R15.1) ----------

    @Slot()
    def open(self) -> None:
        """Shows it at its layout's place, the main window minimized when the setting says so; it
        is raised when it is open already."""
        if self._window is None:
            return
        if not self._opened:
            self._opened = True
            self._song_changed()
            self._queue_changed()
            self._place(place_for(self._layout, self._places, self._areas()))
            self._window.show()
            if self._minimize and self._main is not None and self._main.isVisible():
                was = self._main.visibility()
                if was != QWindow.Visibility.Minimized:
                    self._main_was = was
                self._main.showMinimized()
            self.changed.emit()
        self._window.raise_()
        self._window.requestActivate()

    @Slot()
    def close(self) -> None:
        """Show MusiKata, ×, Close mini player (R15.1): hidden, its place kept, and the main window
        brought back as it was before it was minimized."""
        if not self._opened:
            return
        self._timer.stop()
        self._keep_place()
        self._opened = False
        if self._window is not None:
            self._window.hide()
        main = self._main
        if main is not None:
            if not main.isVisible() or main.visibility() == QWindow.Visibility.Minimized:
                main.setVisibility(self._main_was or QWindow.Visibility.Windowed)
            main.raise_()
            main.requestActivate()
        self._main_was = None
        self.changed.emit()

    @Slot()
    def toggle(self) -> None:
        """Ctrl+Shift+M (R6.9): opens it, or, open, Show MusiKata."""
        if self._opened:
            self.close()
        else:
            self.open()

    # ---------- the layout, Stay on top, the place (R15.2, R15.3) ----------

    @Slot(str)
    def setLayout(self, name: str) -> None:  # noqa: N802
        """A layout chosen from the menu: shown at its own kept size where the window is
        (`switched`), and kept."""
        if name not in MINI_LAYOUTS or name == self._layout.name:
            return
        self._keep_place()
        layout = layout_named(name)
        kept = self._places.get(name)
        size = fitted(layout, kept[2], kept[3]) if kept is not None else layout.size
        card = self._card()
        self._layout = layout
        self.changed.emit()
        if self._opened and card is not None:
            self._place(switched(card, size, self._areas()))
        self._remember(layout=name)
        if self._opened:
            self._keep_place()

    @Slot(int)
    def setLayoutNumber(self, number: int) -> None:  # noqa: N802
        """A layout by its number (M02's, the keys 1 to 7 while it has focus)."""
        if 1 <= number <= len(LAYOUTS):
            self.setLayout(LAYOUTS[number - 1].name)

    @Slot()
    def toggleStayOnTop(self) -> None:  # noqa: N802
        """The pin, and the menu's Stay on top (R15.2): flipped, and kept."""
        self._on_top = not self._on_top
        self.changed.emit()
        self._remember(stay_on_top=self._on_top)

    def _moved(self) -> None:
        if self._opened and not self._placing:
            self._timer.start()

    def _settled(self) -> None:
        """The window stood still: snapped to its screen's edges (R15.2), then kept."""
        card = self._card()
        if card is None or not self._opened:
            return
        w, h = fitted(self._layout, card[2], card[3])
        snap = snapped((card[0], card[1], w, h), self._areas())
        if snap != card:
            self._place(snap)
        self._keep_place()
        self.placeKept.emit()

    def _keep_place(self) -> None:
        """The current layout's place, as the window is now, kept when it changed."""
        card = self._card()
        if not self._opened or card is None or card[2] < 1 or card[3] < 1:
            return
        if self._places.get(self._layout.name) != card:
            self._places[self._layout.name] = card
            x, y, w, h = card
            self._remember(places={self._layout.name: {"x": x, "y": y, "w": w, "h": h}})

    def _remember(self, **fields: object) -> None:
        if self._keep is not None:
            self._keep(**fields)

    # ---------- the controls (R15.4) ----------

    @Slot(int)
    def wheel(self, delta: int) -> None:
        """The scroll wheel over it: the volume up or down (R15.4)."""
        volume = float(self._player.property("volume") or 0.0)
        self._player.setVolume(volume_after(volume, delta))  # type: ignore[attr-defined]

    @Slot(float, float, float, float, float, result=str)
    def progressPath(  # noqa: N802
        self, width: float, height: float, radius: float, thick: float, share: float
    ) -> str:
        """The progress line's outline (`progress_path`)."""
        return progress_path(width, height, radius, thick, share)

    @Slot()
    def playPause(self) -> None:  # noqa: N802
        """Play/pause: the player's; with no song shown, the last one played again (R15.5)."""
        if self._player.property("path") or "song" not in self._last:
            self._player.toggle()  # type: ignore[attr-defined]
            return
        play = getattr(self._player, "play_songs", None)
        if play is not None:
            play([self._last["song"]], self._last.get("album", ""))

    # ---------- the song (R15.3, R15.5) ----------

    def _song_changed(self) -> None:
        """The song shown changed: its words read again while open; with none, the last one's
        stay."""
        if not self._opened:
            return
        info: SongInfo | None = getattr(self._player, "shown", lambda: None)()
        song: int | None = getattr(self._player, "song_id", lambda: None)()
        if not self._player.property("path"):
            words = self._last
        else:
            title = str(self._player.property("title") or "")
            artist = info.artist if info is not None else ""
            album = info.album if info is not None else ""
            words = {
                "title": title,
                "line": song_line(artist_text(artist) if info is not None else "", album),
                "tooltip": tooltip_text(title, artist),
                "cover": info.cover if info is not None else "",
            }
            if song is not None and self._read is not None:
                words |= card_words(self._read(), song)
                words |= {"song": song, "album": album}
            self._last = words
        if words != self._words:
            self._words = words
            self.songChanged.emit()

    def _queue_changed(self) -> None:
        if not self._opened:
            return
        queue = getattr(self._player, "queue", None)
        upcoming = queue.upcoming[:1] if queue is not None else []
        info = None
        if upcoming and self._read is not None:
            info = read_songs(self._read(), [upcoming[0].song]).get(upcoming[0].song)
        words = up_next_words(info)
        if words != self._next:
            self._next = words
            self.songChanged.emit()

    # ---------- the tour ----------

    def go(self, step: Mapping[str, Any]) -> None:
        """A tour's step (A1.6): {"mini": "strip"} opens it at that layout, its place the default
        one, nothing minimized and nothing kept; "miniHover" shows Cover's controls as under the
        pointer, "miniMenu" opens its right-click menu (M02). It is closed otherwise."""
        name = step.get("mini")
        if name not in MINI_LAYOUTS:
            self.close()
            return
        keep, minimize, self._keep, self._minimize = self._keep, self._minimize, None, False
        try:
            self._layout = layout_named(str(name))
            self._places.pop(self._layout.name, None)
            self._controls = bool(step.get("miniHover"))
            self.changed.emit()
            if self._opened:
                areas = self._areas()
                self._place(default_place(self._layout, areas[0]) if areas else (0, 0, 1, 1))
            self.open()
        finally:
            self._keep, self._minimize = keep, minimize
        if step.get("miniMenu"):
            self.menuRequested.emit()

    @property
    def window(self) -> QWindow | None:
        """Its window, once attached (the tour takes its screens of it)."""
        return self._window

    # ---------- what QML reads ----------

    def _get_layouts(self) -> list[dict[str, Any]]:
        return menu_layouts(self._layout.name)

    def _get_limits(self) -> dict[str, int]:
        lay = self._layout
        return {
            "minimumWidth": lay.least[0] + 2 * MARGIN,
            "minimumHeight": lay.least[1] + 2 * MARGIN,
            "maximumWidth": lay.most[0] + 2 * MARGIN,
            "maximumHeight": lay.most[1] + 2 * MARGIN,
        }

    def _get_words(self) -> dict[str, Any]:
        return {k: v for k, v in self._words.items() if k not in ("song", "album")}

    opened = QtProperty(bool, lambda self: self._opened, notify=changed)
    layout = QtProperty(str, lambda self: self._layout.name, notify=changed)  # strip, cover, …
    layouts = QtProperty(list, _get_layouts, notify=changed)  # the menu's (M02)
    limits = QtProperty(dict, _get_limits, notify=changed)  # the window's, its margin included
    logo = QtProperty(bool, lambda self: self._layout.logo, notify=changed)
    radius = QtProperty(int, lambda self: self._layout.radius, notify=changed)
    stayOnTop = QtProperty(bool, lambda self: self._on_top, notify=changed)
    exposed = QtProperty(bool, lambda self: self._exposed, notify=changed)
    showControls = QtProperty(bool, lambda self: self._controls, notify=changed)
    margin = QtProperty(int, lambda self: MARGIN, constant=True)
    words = QtProperty(dict, _get_words, notify=songChanged)  # title, line, kicker, details, …
    upNext = QtProperty(dict, lambda self: self._next, notify=songChanged)
    hasSong = QtProperty(bool, lambda self: bool(self._words), notify=songChanged)
    shortcut = QtProperty(str, lambda self: shortcut_text(self._platform), constant=True)
    sleepLater = QtProperty(str, lambda self: SLEEP_LATER, constant=True)
