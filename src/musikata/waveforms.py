"""Waveforms in the running app (R11.1.1, A5.1): the waveform of the song the now-playing bar
shows, playing or cued, and ahead of time the one of the song after it, as soon as it becomes next
(before the join of A4.2 opens it, ten seconds before the end). Each is looked for in the index by
its audio hash; one not kept there is worked out on the worker processes (A1.3, low priority, so
never at the sound's or the window's cost), a part of 30 seconds of audio at a time
(musikata_core.analysis.waveform), and kept there once whole.

Until it is ready the bar draws a flat line (`peaks` all 0, `loading`), filled in after each part
with what is decoded so far. The song shown comes first: a part of the next song being decoded
when the shown one changes is the last before the shown one's turn.

One thread of its own ("waveforms") does the looking and the waiting on the worker processes, so
the GUI thread never reads the index for it, nor waits; what it finds comes back by a queued
signal. A song that can't be decoded (gone, damaged, not audio) keeps its flat line and is logged,
and isn't tried again while it stays the song shown or next."""

from __future__ import annotations

import functools
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import BrokenExecutor, Executor, Future
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import db
from musikata_core.analysis import peaks as peak_pairs
from musikata_core.analysis import waveform
from musikata_core.analysis.peaks import Peaks
from musikata_core.audio.decode import DecodeError

log = logging.getLogger(__name__)

Job = Callable[[str, int], waveform.Part]  # (the file's whole path, the part): a worker's job


def _logged(path: str, kept: Future[None]) -> None:
    """A waveform's write to the index ended: logged when it failed (it is worked out again the
    next time the song plays)."""
    error = kept.exception()
    if error is not None:
        log.warning("couldn't keep the waveform of %s in the index: %s", path, error)


def _closed_pool() -> Executor:
    raise RuntimeError("the waveforms have closed")


def flat() -> Peaks:
    """The waveform of a song not worked out yet: a flat line."""
    return np.zeros((peak_pairs.N, 2), np.float32)


@dataclass
class Work:
    """A song's waveform as the thread has it: its audio hash (None: the index has none, so it
    isn't kept), its parts so far, and once done or failed, the waveform (None when it failed)."""

    hash: str | None
    assembly: waveform.Assembly = field(default_factory=waveform.Assembly)
    done: bool = False
    peaks: Peaks | None = None


class Waveforms(QObject):
    """The shown song's waveform (`peaks`, `loading`), worked out as `show` and `ahead` say: the
    song the bar shows and the one after it, each by its path under `root` ("" for none). `index`
    finds and keeps them; `workers` gives the worker processes (Library.workers), and `broken` is
    told of a pool one of whose processes died; `job` decodes a part (a test's runs in the pool's
    threads)."""

    changed = Signal()
    _found = Signal(object)  # (path, the waveform or None, whether more is to come)

    def __init__(
        self,
        root: str,
        index: db.Index,
        workers: Callable[[], Executor],
        parent: QObject | None = None,
        job: Job = waveform.decode_part,
        broken: Callable[[Executor], object] | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._index, self._workers, self._job = root, index, workers, job
        self._broken = broken
        self._shown = ""  # the song the bar shows, by its path under the root
        self._peaks = flat()
        self._loading = False
        # the thread's, under the condition: the songs wanted (shown, next), the ones the GUI waits
        # to hear about again, and whether it is closing
        self._cond = threading.Condition()
        self._wanted: tuple[str, str] = ("", "")
        self._answer: set[str] = set()
        self._closed = False
        self._busy = False  # the thread has something to do
        self._thread: threading.Thread | None = None
        self._work: dict[str, Work] = {}  # the thread's alone
        self._found.connect(self._on_found)

    # ---------- what the player says ----------

    @Slot(str)
    def show(self, path: str) -> None:
        """The bar shows the song at `path` ("" none): a flat line until its waveform is found or
        worked out."""
        self._shown = path
        self._peaks = flat()
        self._loading = bool(path)
        self.changed.emit()
        with self._cond:
            self._wanted = (path, self._wanted[1])
            if path:
                self._answer.add(path)
            self._wake()

    @Slot(str)
    def ahead(self, path: str) -> None:
        """The song at `path` comes next ("" none): its waveform is worked out ahead (R11.1.1)."""
        with self._cond:
            self._wanted = (self._wanted[0], path)
            self._wake()

    def close(self) -> None:
        """Stops the thread, after the part it waits on: for closing, before the worker
        processes end."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        # the Library's methods let go with its window, so nothing holds it past its close (A1.3)
        self._workers = _closed_pool
        self._broken = None
        self._work = {}

    def wait(self) -> None:
        """Until the thread has nothing left to do (a test's)."""
        with self._cond:
            while self._thread is not None and self._busy and not self._closed:
                self._cond.wait()

    # ---------- the thread ----------

    def _wake(self) -> None:
        """Under the condition: the thread started, or told there is something to do."""
        if self._closed:
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="waveforms", daemon=True)
            self._thread.start()
        self._busy = True
        self._cond.notify_all()

    def _pending(self) -> bool:
        """Under the condition: whether a song wanted waits on the thread."""
        for path in self._wanted:
            if not path:
                continue
            work = self._work.get(path)
            if work is None or not work.done or path in self._answer:
                return True
        return False

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._closed and not self._pending():
                    self._busy = False
                    self._cond.notify_all()
                    self._cond.wait()
                if self._closed:
                    self._busy = False
                    self._cond.notify_all()
                    return
                shown, following = self._wanted
                answer = set(self._answer)
                self._answer.clear()
                wanted = [p for p in (shown, following) if p]
                self._work = {p: w for p, w in self._work.items() if p in wanted}
            self._turn(wanted, shown, answer)

    def _turn(self, wanted: list[str], shown: str, answer: set[str]) -> None:
        """One turn: each song wanted looked for, the GUI told what it waits on, and one part of
        the first one still to work out decoded."""
        for path in wanted:
            work = self._work.get(path)
            if work is None:
                work = self._work[path] = self._look(path)
            if work.done and path in answer and path == shown:
                self._found.emit((path, work.peaks, False))
        for path in wanted:
            work = self._work[path]
            if not work.done:
                self._decode(path, work, path == shown)
                return

    def _look(self, path: str) -> Work:
        """The song's hash and, when the index keeps it, its waveform."""
        try:
            c = self._index.read()
            audio_hash = waveform.hash_of(c, path)
            kept = waveform.stored(c, audio_hash) if audio_hash is not None else None
        except Exception:  # noqa: BLE001  (logged; it is worked out instead)
            log.exception("couldn't look for the waveform of %s in the index", path)
            audio_hash, kept = None, None
        if kept is not None:
            return Work(audio_hash, done=True, peaks=kept)
        return Work(audio_hash)

    def _decode(self, path: str, work: Work, shown: bool) -> None:
        """The song's next part, on a worker process; its waveform kept once whole."""
        whole = os.path.join(self._root, *path.split("/"))
        pool: Executor | None = None
        try:
            pool = self._workers()
            part = pool.submit(self._job, whole, work.assembly.next).result()
        except Exception as e:  # noqa: BLE001  (logged: the song keeps its flat line)
            if isinstance(e, BrokenExecutor) and pool is not None and self._broken is not None:
                self._broken(pool)  # made anew for the next song
            if isinstance(e, DecodeError | OSError):
                log.warning("couldn't work out the waveform of %s: %s", path, e)
            else:
                log.exception("working out the waveform of %s failed", path)
            work.done = True
            if shown:
                self._found.emit((path, None, False))
            return
        work.assembly.add(part)
        if not work.assembly.complete:
            if shown:
                self._found.emit((path, work.assembly.peaks(), True))
            return
        work.done, work.peaks = True, work.assembly.peaks()
        if work.hash is not None:
            audio_hash, found = work.hash, work.peaks
            kept = self._index.write(lambda c: waveform.keep(c, audio_hash, found))
            kept.add_done_callback(functools.partial(_logged, path))
        if shown:
            self._found.emit((path, work.peaks, False))

    # ---------- back on the GUI thread ----------

    @Slot(object)
    def _on_found(self, found: tuple[str, Peaks | None, bool]) -> None:
        path, got, more = found
        if path != self._shown:
            return  # a song no longer shown
        self._peaks = got if got is not None else flat()
        self._loading = more
        self.changed.emit()

    # ---------- what the bar reads ----------

    @property
    def peaks(self) -> Peaks:
        """The shown song's waveform so far: `peaks.N` pairs, 0 where not yet decoded."""
        return self._peaks

    def _get_loading(self) -> bool:
        return self._loading

    def _get_shown(self) -> str:
        return self._shown

    loading = QtProperty(bool, _get_loading, notify=changed)  # worked out still (the tour waits)
    shown = QtProperty(str, _get_shown, notify=changed)
