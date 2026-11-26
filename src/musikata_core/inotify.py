"""Watching folders with Linux's inotify directly (A2.4, R2.4), for watch.Watcher. Qt's
QFileSystemWatcher asks inotify, for a folder, only for what changes its list of files, so a file a
tag editor (Picard, kid3, puddletag) rewrites in place was never rescanned. A folder's watch here
asks for what Qt's did and IN_CLOSE_WRITE too: a file written and closed. One watch per folder, as
Qt's, so the system's limit on watches (fs.inotify.max_user_watches) counts the same.

The system's calls are through ctypes on the C library (inotify_init1, inotify_add_watch,
inotify_rm_watch: `Libc`), and the descriptor is read when a QSocketNotifier says it can be, on the
thread the watch lives on. Reading the event records is plain logic over bytes (`parse`), and which
folder an event is in is a plain map (`Watches`); `Inotify` only carries them, with the system's
calls passed in (`System`), so a test can stand in for them. Nothing here is imported on another
platform's run but its tests; the C library is opened only when a watch is made."""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import weakref
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject, QSocketNotifier, Signal

log = logging.getLogger(__name__)

# what an event says (<sys/inotify.h>)
IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_UNMOUNT = 0x00002000
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ONLYDIR = 0x01000000
IN_NONBLOCK = 0o4000  # inotify_init1's flags: O_NONBLOCK and O_CLOEXEC, as Linux numbers them
IN_CLOEXEC = 0o2000000

# what Qt's watch on a folder asks for (qfilesystemwatcher_inotify.cpp), and a file written and
# closed: a rewrite in place, once, however many writes it took
QT_FOLDER = IN_ATTRIB | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE | IN_DELETE_SELF
FOLDER = QT_FOLDER | IN_CLOSE_WRITE | IN_ONLYDIR
HEADER = struct.Struct("=iIII")  # struct inotify_event: wd, mask, cookie, len; then the name
READ = 64 * 1024  # bytes read at a time: many events, and always at least one whole


@dataclass(frozen=True)
class Event:
    """An event the system wrote: the watch it is on, what happened, the cookie that pairs a
    rename's two ends, and the name of the file or folder in the watched folder ("" for the
    watched folder itself)."""

    wd: int
    mask: int
    cookie: int
    name: str


def parse(data: bytes) -> tuple[list[Event], bytes]:
    """The event records in `data`, in order, as inotify writes them (struct inotify_event: its
    header, then its name in `len` bytes, NUL-ended and padded with NULs), and the bytes of a
    record cut short at its end, for the next read to finish."""
    events: list[Event] = []
    at = 0
    while len(data) - at >= HEADER.size:
        wd, mask, cookie, length = HEADER.unpack_from(data, at)
        end = at + HEADER.size + length
        if end > len(data):
            break
        name = data[at + HEADER.size : end].split(b"\0", 1)[0]
        events.append(Event(wd, mask, cookie, os.fsdecode(name)))
        at = end
    return events, data[at:]


class Watches:
    """The folders each watch stands for, by the paths they were added under. Two paths to one
    folder (one of them through a link) share the system's watch, which is let go of when the
    last of them is."""

    def __init__(self) -> None:
        self._wd: dict[str, int] = {}  # path -> its watch
        self._paths: dict[int, list[str]] = {}  # a watch -> its paths, in the order added

    def add(self, path: str, wd: int) -> None:
        """`path` is watched by the watch `wd` (the system's answer to adding it)."""
        if self._wd.get(path) == wd:
            return
        self.remove(path)
        self._wd[path] = wd
        self._paths.setdefault(wd, []).append(path)

    def remove(self, path: str) -> int | None:
        """Forgets `path`: its watch, for the system to let go of, when no other path has it;
        None when another has, or `path` wasn't watched."""
        wd = self._wd.pop(path, None)
        if wd is None:
            return None
        paths = self._paths[wd]
        paths.remove(path)
        if paths:
            return None
        del self._paths[wd]
        return wd

    def paths(self, wd: int) -> list[str]:
        """The paths the watch `wd` stands for; none for a watch let go of."""
        return list(self._paths.get(wd, ()))

    def changed(self, events: Iterable[Event]) -> tuple[list[str], bool]:
        """The watched folders `events` report a change in, each once, in the order first
        reported, and whether the system's queue overflowed (changes were lost). A watch the
        system ended (IN_IGNORED: its folder removed, or its drive unmounted) is forgotten, its
        folder reported."""
        folders: list[str] = []
        overflow = False
        for event in events:
            if event.mask & IN_Q_OVERFLOW:
                overflow = True
                continue
            paths = self.paths(event.wd)
            folders += [p for p in paths if p not in folders]
            if event.mask & IN_IGNORED:
                for path in paths:
                    self._wd.pop(path, None)
                self._paths.pop(event.wd, None)
        return folders, overflow


class System(Protocol):
    """The system's calls an inotify watch makes; each raises OSError when the system refuses."""

    def init(self) -> int:
        """A new inotify instance's descriptor, read without blocking."""
        ...

    def add_watch(self, fd: int, path: str, mask: int) -> int:
        """A watch on the folder at `path` for the events of `mask`; the same one for a folder
        watched already."""
        ...

    def rm_watch(self, fd: int, wd: int) -> None: ...

    def read(self, fd: int) -> bytes:
        """What the system wrote; b"" when nothing waits."""
        ...

    def close(self, fd: int) -> None: ...


class Libc:
    """The system's calls, through ctypes on the C library."""

    def __init__(self) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        self._init1 = libc.inotify_init1
        self._init1.argtypes, self._init1.restype = [ctypes.c_int], ctypes.c_int
        self._add = libc.inotify_add_watch
        self._add.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._add.restype = ctypes.c_int
        self._rm = libc.inotify_rm_watch
        self._rm.argtypes, self._rm.restype = [ctypes.c_int, ctypes.c_int], ctypes.c_int

    @staticmethod
    def _error(path: str | None = None) -> OSError:
        n = ctypes.get_errno()
        return OSError(n, os.strerror(n), path) if path is not None else OSError(n, os.strerror(n))

    def init(self) -> int:
        fd = int(self._init1(IN_NONBLOCK | IN_CLOEXEC))
        if fd < 0:
            raise self._error()
        return fd

    def add_watch(self, fd: int, path: str, mask: int) -> int:
        wd = int(self._add(fd, os.fsencode(path), mask))
        if wd < 0:
            raise self._error(path)
        return wd

    def rm_watch(self, fd: int, wd: int) -> None:
        if self._rm(fd, wd) < 0:
            raise self._error()

    def read(self, fd: int) -> bytes:
        try:
            return os.read(fd, READ)
        except BlockingIOError:
            return b""

    def close(self, fd: int) -> None:
        os.close(fd)


class Inotify(QObject):
    """inotify on the folders added (`add`), one watch per folder asking for FOLDER's events,
    read on the thread this lives on as they come. `changed` gives each folder a change was
    reported in, by the path it was added under; `overflowed` says the system lost changes (its
    queue overflowed). `system` makes the system's calls (Libc; a test's stand-in). Raises OSError
    when the system gives no inotify instance (a user's are limited too)."""

    changed = Signal(str)
    overflowed = Signal()

    def __init__(self, parent: QObject | None = None, system: System | None = None) -> None:
        super().__init__(parent)
        self._system: System = system if system is not None else Libc()
        self._fd = self._system.init()
        # the instance is let go of by close, or else when this goes: the system's are limited
        self._release = weakref.finalize(self, self._system.close, self._fd)
        self._watches = Watches()
        self._rest = b""  # a record cut short, finished by the next read
        self._notifier = QSocketNotifier(self._fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._on_ready)

    def add(self, paths: list[str]) -> list[str]:
        """Watches each folder of `paths`; gives back those the system refused: one gone, or not
        a folder, or past the limit on watches (ENOSPC), as QFileSystemWatcher.addPaths does."""
        refused = []
        for path in paths:
            try:
                wd = self._system.add_watch(self._fd, path, FOLDER)
            except OSError as e:
                log.debug("couldn't watch %s: %s", path, e)
                refused.append(path)
                continue
            self._watches.add(path, wd)
        return refused

    def remove(self, paths: list[str]) -> None:
        """Lets go of the watches on these folders; one the system ended already is no failure."""
        for path in paths:
            wd = self._watches.remove(path)
            if wd is None:
                continue
            try:
                self._system.rm_watch(self._fd, wd)
            except OSError as e:  # its folder went, and the watch with it
                log.debug("the watch on %s had gone: %s", path, e)

    def _on_ready(self, *_: object) -> None:
        self.read()

    def read(self) -> None:
        """Reads what the system wrote, and says which folders changed."""
        data = self._rest
        try:
            while chunk := self._system.read(self._fd):
                data += chunk
        except OSError as e:
            log.warning("couldn't read what changed in the folders watched: %s", e)
        events, self._rest = parse(data)
        folders, overflow = self._watches.changed(events)
        if overflow:
            self.overflowed.emit()
        for folder in folders:
            self.changed.emit(folder)

    def close(self) -> None:
        """Lets go of every watch and of the inotify instance; nothing is reported after."""
        if self._fd < 0:
            return
        self._notifier.setEnabled(False)
        self._release()
        self._fd = -1
