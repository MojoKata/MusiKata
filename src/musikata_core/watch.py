"""Watching the root (A2.4, R2.4): while MusiKata runs, a watch on every folder under the root that
the scan walks, each watched as the walk reaches it, the changes it reports gathered for a second
before a partial rescan of the folders they were in (scanner.Scope), and folders added and removed
as the tree changes. On Linux the watch is inotify's own (inotify.Inotify), which also reports a
file rewritten in place; elsewhere it is QFileSystemWatcher, whose watch on a folder does.
When the system refuses a watch (Linux's fs.inotify.max_user_watches), watching stops, the log says
so, and MusiKata rescans when its window gains focus instead.

What to rescan and when is worked out by plain objects over the clock (`Gatherer`, `OwnWrites`),
tested by moving a fake one; `Watcher` carries the system's reports to them.

A root that isn't there can't be watched (R2.10): `Presence` looks for it, and for the linked
folders that couldn't be reached, every few seconds while one is missing, so that MusiKata rescans
when it comes back.

A folder's watch reports what changes in its list of files: a file added, removed, renamed or
given other attributes, and a file written and closed (a tag editor's rewrite in place). A copy
still being written is reported when it is closed; one read before then is looked at again until it
settles (`Gatherer.scanned`), as on a platform whose watch said nothing more."""

from __future__ import annotations

import logging
import math
import os
import sys
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_for

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, Signal

from . import inotify
from .clock import Clock
from .scanner import Seen, full_path

log = logging.getLogger(__name__)

GATHER = 1.0  # seconds a change waits for others before its rescan (A2.4)
SETTLE = 2.0  # a file modified this recently may still be being written: looked at again
OWN = 30.0  # seconds a write MusiKata made itself is recognised for (A2.4)
LIMIT = "/proc/sys/fs/inotify/max_user_watches"  # Linux's limit on the folders a user watches
CLOSING = 2.0  # seconds closing waits for a look that runs (Presence.close)
LOOK = 5.0  # seconds between looks for a root, or a linked folder, that isn't there (R2.10)


class Gatherer:
    """The folders changes were reported in, each a path under the root, gathered from the first
    change for `wait` seconds and then due together (A2.4): a burst of changes, an album copied in
    or a folder moved, is one rescan. Changes reported while a rescan runs are gathered for the
    next."""

    def __init__(self, clock: Clock, wait: float = GATHER, settle: float = SETTLE) -> None:
        self._clock, self._wait, self._settle = clock, wait, settle
        self._folders: set[str] = set()
        self._since: float | None = None

    def changed(self, folder: str) -> None:
        """A change reported in `folder`."""
        if self._since is None:
            self._since = self._clock.monotonic()
        self._folders.add(folder)

    def due_in(self) -> float | None:
        """Seconds until the folders gathered are due, 0 when they are; None when none are."""
        if self._since is None:
            return None
        return max(0.0, self._since + self._wait - self._clock.monotonic())

    def take(self) -> frozenset[str]:
        """The folders gathered, once due, starting a new gathering; none before."""
        if self.due_in() != 0.0:
            return frozenset()
        folders = frozenset(self._folders)
        self.clear()
        return folders

    def clear(self) -> None:
        """Forgets the folders gathered: a scan of the whole root covers them."""
        self._folders.clear()
        self._since = None

    def scanned(self, read: Iterable[Seen]) -> None:
        """After a scan, the files it read: one modified less than `settle` seconds ago may still
        be being written (a copy in progress, which a folder's watch doesn't report again), so its
        folder is gathered again. Once its modification time stays put, a rescan reads nothing."""
        now = self._clock.now().timestamp()
        for s in read:
            if abs(now - s.mtime_ns / 1e9) < self._settle:
                self.changed(s.path.rpartition("/")[0])


class OwnWrites:
    """The files MusiKata wrote itself (A2.4), each by its path under the root and the size and
    modification time the write left it with, for `keep` seconds: a rescan a watched change
    starts doesn't read them again, as the write updates their rows itself (A1.4). A3.4's safe
    write calls `wrote`."""

    def __init__(self, clock: Clock, keep: float = OWN) -> None:
        self._clock, self._keep = clock, keep
        self._written: dict[str, tuple[int, int, float]] = {}

    def wrote(self, path: str, size: int, mtime_ns: int) -> None:
        """MusiKata wrote the file at `path`, leaving it `size` bytes, modified at `mtime_ns`."""
        self._written[path] = (size, mtime_ns, self._clock.monotonic())

    def expected(self) -> dict[str, tuple[int, int]]:
        """The files written in the last `keep` seconds: path -> (size, modification time)."""
        now = self._clock.monotonic()
        self._written = {p: w for p, w in self._written.items() if now - w[2] < self._keep}
        return {p: (size, mtime) for p, (size, mtime, _when) in self._written.items()}


def refused_text(folders: int, platform: str, limit: int | None) -> str:
    """Why the system refused to watch the root's folders, for the log (R2.4, R14)."""
    if platform.startswith("linux") and limit is not None:
        return (
            f"the system lets a user watch {limit:,} folders (fs.inotify.max_user_watches),"
            f" and the root has {folders:,}"
        )
    return f"the system refused to watch all {folders:,} of the root's folders"


def folders_watch(
    parent: QObject, platform: str = sys.platform
) -> inotify.Inotify | QFileSystemWatcher:
    """What watches the root's folders on `platform` (A2.4): inotify's own on Linux, so that a
    file rewritten in place is reported, else QFileSystemWatcher; Qt's on Linux too when the
    system gives no inotify instance, and the log says so."""
    if platform.startswith("linux"):
        try:
            return inotify.Inotify(parent)
        except OSError as e:
            log.warning(
                "couldn't watch with inotify (%s): watching through Qt, which misses a file"
                " rewritten in place",
                e,
            )
    return QFileSystemWatcher(parent)


def inotify_limit(path: str = LIMIT) -> int | None:
    """Linux's limit on the folders a user watches; None where there is none to read."""
    try:
        with open(path, encoding="ascii") as f:
            return int(f.read().strip())
    except OSError, ValueError:
        return None


class Watcher(QObject):
    """A watch on the root's folders (A2.4; `folders_watch`), each known by its path under the
    root and its real path, as the scans walk them. A change it reports gathers its folder
    (`Gatherer`), and `ready` says when the folders gathered are due; changes the system lost
    (inotify's queue overflowed) gather every folder watched. When the system refuses a watch on a
    folder that is there, it stops watching altogether, logs why, and says so with `stopped`;
    MusiKata rescans on focus instead (R2.4). `add` stands in for the watch's own in tests: it
    takes paths, and gives those it couldn't watch."""

    ready = Signal()
    stopped = Signal(str)

    def __init__(
        self,
        root: str,
        gatherer: Gatherer,
        add: Callable[[list[str]], list[str]] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._gatherer = root, gatherer
        self._folders = folders_watch(self)
        own_add: Callable[[list[str]], list[str]]
        self._remove: Callable[[list[str]], object]
        if isinstance(self._folders, inotify.Inotify):
            self._folders.changed.connect(self._on_changed)
            self._folders.overflowed.connect(self._on_overflowed)
            own_add, self._remove = self._folders.add, self._folders.remove
        else:
            self._folders.directoryChanged.connect(self._on_changed)
            own_add, self._remove = self._folders.addPaths, self._folders.removePaths
        self._add = add if add is not None else own_add
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_timer)
        self._known: dict[str, str] = {}  # path under the root -> real path
        self._watched: dict[str, str] = {}  # the system's path watched -> path under the root
        self.why = ""  # why watching stopped; "" while it goes on

    def watch(self, folders: Mapping[str, str]) -> None:
        """Watches exactly these folders (path under the root -> real path): after a scan of the
        whole root."""
        self.update(folders, set(self._known) - set(folders))

    def update(self, walked: Mapping[str, str], gone: Iterable[str]) -> None:
        """After a partial scan: the folders it walked are watched, those it found gone no
        longer. Nothing once watching has stopped."""
        if self.why:
            return
        drop = [os.path.normpath(full_path(self._root, f)) for f in gone if f in self._known]
        if drop:  # before adding: a folder renamed keeps its watch, under its old name
            self._remove(drop)
        for path in drop:
            del self._known[self._watched.pop(path)]
        new = {f: real for f, real in walked.items() if f not in self._known}
        paths = {os.path.normpath(full_path(self._root, f)): f for f in new}
        refused = self._add(list(paths)) if paths else []
        if any(os.path.isdir(p) for p in refused):  # one that is gone is no refusal
            self.stop(refused_text(len(self._known) + len(new), sys.platform, inotify_limit()))
            return
        for path, f in paths.items():
            if path not in refused:
                self._known[f], self._watched[path] = new[f], f

    def reached(self, folder: str, real: str, listed: int) -> None:
        """A scan's walk listed `folder` (path under the root, and its real path), modified at
        `listed` just before: watched from now on, so a change made while the scan goes on is
        gathered for the rescan after it. Its watch comes after the listing, so a folder whose
        modification time has moved since (or that has gone) is gathered too. Nothing for a folder
        watched already, or once watching has stopped."""
        if self.why or folder in self._known:
            return
        self.update({folder: real}, ())
        if self.why:
            return
        try:
            now: int | None = os.stat(full_path(self._root, folder)).st_mtime_ns
        except OSError:
            now = None
        if now != listed:
            self.changed(folder)

    def stop(self, why: str) -> None:
        """Stops watching for good, logs why, and says so with `stopped`."""
        self.close()
        self.why = why
        log.warning(
            "stopped watching %s: %s; rescanning when the window gains focus instead",
            self._root,
            why,
        )
        self.stopped.emit(why)

    def close(self) -> None:
        """Lets go of every watch and what was gathered, for good: no folder is watched after."""
        if self._watched:
            self._remove(list(self._watched))
        if isinstance(self._folders, inotify.Inotify):
            self._folders.close()
        self._known.clear()
        self._watched.clear()
        self.forget()

    def forget(self) -> None:
        """Forgets what was gathered: a scan of the whole root covers it."""
        self._timer.stop()
        self._gatherer.clear()

    def known(self) -> dict[str, str]:
        """The folders watched: path under the root -> real path."""
        return dict(self._known)

    def changed(self, folder: str) -> None:
        """A change in `folder` (path under the root), gathered for its rescan."""
        if self.why:
            return
        self._gatherer.changed(folder)
        if not self._timer.isActive():
            self._arm()

    def scanned(self, read: Iterable[Seen]) -> None:
        """The files a scan read: those maybe still being written are looked at again."""
        if not self.why:
            self._gatherer.scanned(read)
            self._arm()

    def due(self) -> bool:
        return self._gatherer.due_in() == 0.0

    def take(self) -> frozenset[str]:
        """The folders gathered, once due (`Gatherer.take`)."""
        return self._gatherer.take()

    def _arm(self) -> None:
        wait = self._gatherer.due_in()
        if wait is None:
            return
        self._timer.start(math.ceil(wait * 1000))

    def _on_changed(self, path: str) -> None:
        folder = self._watched.get(os.path.normpath(path))
        if folder is not None:
            self.changed(folder)

    def _on_overflowed(self) -> None:
        """The system lost changes (A2.4): every folder watched is rescanned."""
        log.warning("changes under %s were lost: rescanning every folder watched", self._root)
        for folder in list(self._known):
            self.changed(folder)

    def _on_timer(self) -> None:
        wait = self._gatherer.due_in()
        if wait is None:
            return
        if wait > 0:
            self._arm()
        else:
            self.ready.emit()


def there(root: str, links: Iterable[str]) -> tuple[bool, frozenset[str]]:
    """What a look finds (R2.10): whether the root is there, and which of the linked folders
    `links` (paths under the root, R2.3.2) still can't be reached."""
    if not os.path.isdir(root):
        return False, frozenset(links)
    return True, frozenset(f for f in links if not os.path.isdir(full_path(root, f)))


class Presence(QObject):
    """Looks for the root and the linked folders that couldn't be reached (R2.10), every `every`
    seconds while it runs, and when asked (`look`, Try again). A look runs on a thread of its own,
    the same one each time, since one at a share gone to sleep can take a minute, and `found`
    gives its answer on the GUI thread: whether the root is there, and the linked folders that
    still can't be reached. `links` are those to look for; `looking` is the look itself, given the
    root and them (`there`; a test's stand-in); a look asked for while one runs is that one. It
    holds nothing of what owns it, so its owner is freed when let go of, on its own thread, never
    by the garbage collector on another."""

    found = Signal(bool, object)
    _looked = Signal(object)

    def __init__(
        self,
        root: str,
        looking: Callable[[str, frozenset[str]], tuple[bool, frozenset[str]]] = there,
        every: float = LOOK,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._looking = root, looking
        self.links: frozenset[str] = frozenset()
        self._pool: ThreadPoolExecutor | None = None
        self._looked_for: Future[None] | None = None
        self._looking_now = False  # a look runs, its answer not yet given
        self._timer = QTimer(self)
        self._timer.setInterval(math.ceil(every * 1000))
        self._timer.timeout.connect(self.look)
        self._looked.connect(self._on_looked)

    def start(self) -> None:
        """Looks every `every` seconds from now on."""
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def running(self) -> bool:
        return self._timer.isActive()

    def look(self) -> None:
        """Looks now, unless a look runs already."""
        if self._looking_now:
            return
        self._looking_now = True
        if self._pool is None:
            self._pool = ThreadPoolExecutor(1, thread_name_prefix="presence")
        self._looked_for = self._pool.submit(self._look, self.links)

    def _look(self, links: frozenset[str]) -> None:
        try:
            self._looked.emit(self._looking(self._root, links))
        except OSError as e:  # what can't be looked at isn't there
            log.warning("couldn't look for the music root: %s", e)
            self._looked.emit((False, frozenset()))

    def _on_looked(self, answer: tuple[bool, frozenset[str]]) -> None:
        self._looking_now = False
        self.found.emit(*answer)

    def close(self) -> None:
        """Stops looking, and waits a moment for a look that runs; one held up by a share asleep
        is left to end on its own, so that quitting never waits on it."""
        self._timer.stop()
        if self._looked_for is not None:
            wait_for([self._looked_for], CLOSING)
        if self._pool is not None:
            self._pool.shutdown(wait=False)
