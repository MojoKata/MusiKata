"""Play counts as the running app keeps them (R7.9, A2.8): the plays the player counts handed to
the root's `rootfiles.Keeping`, which keeps them on a thread of its own, and the other computers'
play files watched, each read again when it changes. `changed` says, on the GUI thread, that the
counts shown may have changed, for the lists to read them again. Nothing here reads a file: the
keeping thread lists `.musikata` and reads the files, and the watch follows the folders it
listed.

The watch is the root's (watch.Watcher, A2.4) over `.musikata` and each computer's folder in it,
its changes gathered for a second: a computer's folder that changed is read again (this
computer's own is passed by: it writes it), and a change in `.musikata` itself (a computer's
folder added or gone) reads every other computer's again."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import rootfiles, watch
from musikata_core.audio.played import Play
from musikata_core.clock import Clock


class PlayCounts(QObject):
    """The root's play counts (`keeping`), the files in its own folder `musikata` watched on
    `clock` when `watching`."""

    changed = Signal()  # the counts shown may have changed
    _kept = Signal()  # from the keeping thread

    def __init__(
        self,
        keeping: rootfiles.Keeping,
        musikata: str,
        clock: Clock,
        watching: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._keeping, self._musikata, self._clock = keeping, musikata, clock
        self._watching = watching
        self._watcher: watch.Watcher | None = None
        self._kept.connect(self._on_kept)
        keeping.on_change = self.kept

    def kept(self) -> None:
        """The keeping thread changed the counts: said on the GUI thread (`changed`)."""
        self._kept.emit()

    def start(self) -> None:
        """Reads every computer's file into the index, off this thread, and watches them once
        their folders are listed."""
        if self._watching and os.path.isdir(self._musikata):
            self._watcher = watch.Watcher(self._musikata, watch.Gatherer(self._clock), parent=self)
            self._watcher.ready.connect(self._on_ready)
        self._keeping.start()

    @Slot()
    def _on_kept(self) -> None:
        """The counts changed, and maybe the computers' folders: those listed are watched."""
        if self._watcher is not None:
            folders = {"": self._musikata}
            folders.update({n: os.path.join(self._musikata, n) for n in self._keeping.seen})
            self._watcher.watch(folders)
        self.changed.emit()

    @Slot()
    def _on_ready(self) -> None:
        assert self._watcher is not None
        changed = self._watcher.take()
        if "" in changed:  # a computer's folder came or went: every one read again
            self._keeping.reread()
            return
        names = sorted(f for f in changed if f != self._keeping.me)
        if names:
            self._keeping.reread(names)

    def played(self, play: Play) -> None:
        """A play the player counted (R7.9)."""
        self._keeping.played(play.song, play.when)

    def tick(self) -> None:
        """While playing: this computer's file is written when it is due (A2.8)."""
        self._keeping.tick()

    def moved(self) -> None:
        """A scan moved songs: this computer's file names them where they are now."""
        self._keeping.moved()

    def close(self) -> None:
        """Stops watching, writes this computer's file if its plays changed, and waits for it."""
        if self._watcher is not None:
            self._watcher.close()
            self._watcher = None
        self._keeping.close()
