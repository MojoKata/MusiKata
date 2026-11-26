"""The first start (R2.1, X01-first-run): with no root configured and none given for the run, the
window asks for the folder the music lives in: dropped onto the window, chosen in the platform's
folder dialog, or the platform's music folder (~/Music, %USERPROFILE%\\Music). `FirstRun` is what
that window binds to; the folder it settles on is said with `chosen`, and app.Session makes it the
configured root and opens it."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, QStandardPaths, QUrl, Signal, Slot

from .bridges import local_folder, shown_path

log = logging.getLogger(__name__)


def music_folder(home: str) -> str:
    """The platform's music folder: the system's own (the XDG user folder on Linux, the known
    folder on Windows and macOS), or the home's Music."""
    found = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
    return found or os.path.join(home, "Music")


def _text(item: object) -> str:
    """A dropped item as text: a QUrl (QML's drop.urls) or a string."""
    return item.toString() if isinstance(item, QUrl) else str(item)


def dropped_folder(items: Iterable[object]) -> str | None:
    """The first folder among what was dropped onto the window (QML's drop.urls); None when none
    is a folder."""
    for item in items:
        path = local_folder(_text(item))
        if path is not None:
            return path
    return None


NOT_A_FOLDER = "That isn't a folder. Drop the folder your music is in."


class FirstRun(QObject):
    """The first start's window, as QML sees it (X01-first-run): the music folder its second
    button offers (`musicText`, Use ~/Music), and what went wrong (`error`: a drop that held no
    folder, a music folder that can't be made). `chosen` gives the folder settled on, a whole
    path."""

    chosen = Signal(str)
    changed = Signal()

    def __init__(self, music: str, home: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._music, self._home = music, home
        self._error = ""

    def _fail(self, error: str) -> None:
        self._error = error
        self.changed.emit()

    @Slot(list, result=bool)
    def accepts(self, items: list[object]) -> bool:
        """Whether a drag over the window holds a folder: the drop box lights up for it."""
        return dropped_folder(items) is not None

    @Slot(list)
    def drop(self, items: list[object]) -> None:
        """Something dropped onto the window: its first folder is the root; else the window says
        it wants a folder."""
        path = dropped_folder(items)
        if path is None:
            log.info("dropped onto the first start's window, not a folder: %s", items)
            self._fail(NOT_A_FOLDER)
            return
        self.chosen.emit(path)

    @Slot(str)
    def choose(self, folder: str) -> None:
        """Choose folder…: the folder the platform's dialog gave (a file: URL), or a path."""
        path = local_folder(folder)
        if path is None:
            self._fail(NOT_A_FOLDER)
            return
        self.chosen.emit(path)

    @Slot()
    def useMusic(self) -> None:  # noqa: N802
        """Use ~/Music: the platform's music folder, made when it isn't there yet."""
        try:
            os.makedirs(self._music, exist_ok=True)
        except OSError as e:
            log.warning("couldn't make %s: %s", self._music, e)
            self._fail(f"{self._get_music_shown()} can't be made: {e.strerror or e}")
            return
        self.chosen.emit(os.path.abspath(self._music))

    def _get_music_shown(self) -> str:
        return shown_path(self._music, self._home)

    def _get_music_text(self) -> str:
        return f"Use {self._get_music_shown()}"

    def _get_error(self) -> str:
        return self._error

    musicText = QtProperty(str, _get_music_text, constant=True)  # Use ~/Music
    error = QtProperty(str, _get_error, notify=changed)  # "" when nothing went wrong
