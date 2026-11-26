"""A save of many files (R4.7): each written in turn, off the GUI thread, its progress reported
after each file, cancellable between files, and ending with the files that failed, each with why,
the others saved. A file is written by the writer the batch is given (safe.save, in MusiKata), so
the batch is plain logic, tested with a writer that writes nothing; showing it and Retry are the
Edit tags panel's.

Every save goes through a batch, so the change history (R4.9, A3.5) is kept here: a batch given a
`record` (history.Recording, in MusiKata) tells it each file written, as it is written, and at the
end what the save was (its `action` and `description`, for the list), and the save is one entry.
A batch without one, as when the history is off (R13.3), records nothing."""

from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from .safe import WriteError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    """One file to write: its path, and the R4.1 fields to set in it (safe.save's `changes`)."""

    path: str
    changes: Mapping[str, object]


@dataclass(frozen=True)
class Failed:
    """A file that wasn't written, and why, in words a person can act on (R4.7)."""

    job: Job
    why: str


@dataclass
class Outcome[T]:
    """How a batch ended: what each file written gave, the files that failed, and, when it was
    cancelled, the files it didn't come to."""

    saved: list[T] = field(default_factory=list)
    failed: list[Failed] = field(default_factory=list)
    cancelled: bool = False
    left: list[Job] = field(default_factory=list)
    entry: str | None = None  # the change history's entry it made, by name (None: none)

    def retry(self) -> list[Job]:
        """The files that failed, to be written again (R4.7's Retry)."""
        return [f.job for f in self.failed]


# told after each file: how many are done, of how many, and the file's path
Progress = Callable[[int, int, str], None]


class Recorder[T](Protocol):
    """What keeps a save in the change history (R4.9): told each file written, then, once, what
    the save was; it gives the entry it made, by name, or None when it made none."""

    def saved(self, written: T) -> None: ...

    def done(self, action: str, description: str) -> str | None: ...


class Batch[T]:
    """Writes `jobs` in turn with `write`, which gives what a file written is (safe.Written) or
    raises safe.WriteError. `run` does it, on whichever thread calls it: a pool's, never the GUI
    thread (A1.3). `cancel`, from any thread, stops it before the next file; the file being
    written is finished first, so none is left half done. `record` keeps the save in the change
    history as one entry, `action` (edit-tags, undo, …) and `description` (what the save was, in
    words, for the Change history view) saying what it was; a failure to keep it is logged and
    never fails the save."""

    def __init__(
        self,
        jobs: Sequence[Job],
        write: Callable[[Job], T],
        progress: Progress | None = None,
        *,
        record: Recorder[T] | None = None,
        action: str = "edit-tags",
        description: str = "",
    ) -> None:
        self._jobs, self._write, self._progress = list(jobs), write, progress
        self._record, self._action, self._description = record, action, description
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Stops the batch before its next file."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> Outcome[T]:
        """Writes each file in turn, until done or cancelled, and says how it went."""
        out: Outcome[T] = Outcome()
        total = len(self._jobs)
        for n, job in enumerate(self._jobs):
            if self._cancel.is_set():
                out.cancelled, out.left = True, self._jobs[n:]
                break
            try:
                written = self._write(job)
                out.saved.append(written)
            except WriteError as e:
                out.failed.append(Failed(job, e.why))
            except Exception as e:  # noqa: BLE001  (one file's fault: listed, and the rest written)
                log.exception("writing the tags of %s failed", job.path)
                out.failed.append(Failed(job, f"it couldn't be written: {type(e).__name__}: {e}"))
            else:
                if self._record is not None:
                    self._kept(functools.partial(self._record.saved, written))
            if self._progress is not None:
                self._progress(n + 1, total, job.path)
        if self._record is not None:
            out.entry = self._kept(
                functools.partial(self._record.done, self._action, self._description)
            )
        log.info(
            "saved %d of %d files%s%s",
            len(out.saved),
            total,
            f", {len(out.failed)} failed" if out.failed else "",
            f", cancelled before {len(out.left)}" if out.cancelled else "",
        )
        return out

    @staticmethod
    def _kept(step: Callable[[], object]) -> str | None:
        """A step of keeping the save in the change history; its failure logged, never the
        save's."""
        try:
            made = step()
        except Exception:  # noqa: BLE001  (the files are saved; only the history missed it)
            log.exception("keeping the save in the change history failed")
            return None
        return made if isinstance(made, str) else None
