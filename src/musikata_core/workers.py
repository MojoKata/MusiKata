"""The worker processes (A1.3): the Python work that keeps a core busy (tag reads, audio hashes,
waveforms) runs in processes, one fewer than the cores, at low CPU and I/O priority, so the window
and the sound never wait behind a scan. They are MusiKata's own children and end with it."""

from __future__ import annotations

import ctypes
import logging
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor

log = logging.getLogger(__name__)

IOPRIO_WHO_PROCESS, IOPRIO_CLASS_IDLE = 1, 3  # linux/ioprio.h
SYS_IOPRIO_SET = {"x86_64": 251, "aarch64": 30}  # the syscall's number, by machine


def lower_priority() -> None:
    """Lowers this process's CPU and I/O priority, as far as the platform allows; a step that
    fails is logged and the rest go on."""
    if sys.platform.startswith("win"):
        _windows()
    elif sys.platform == "darwin":
        _macos()
    else:
        _linux()


def _linux() -> None:
    os.nice(10)
    number = SYS_IOPRIO_SET.get(os.uname().machine)
    if number is None:
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.syscall(number, IOPRIO_WHO_PROCESS, 0, IOPRIO_CLASS_IDLE << 13) != 0:
        log.info("idle I/O priority refused: errno %s", ctypes.get_errno())


def _windows() -> None:  # pragma: no cover - measured in the Windows run
    process_mode_background_begin = 0x00100000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), process_mode_background_begin)


def _macos() -> None:  # pragma: no cover - measured in the macOS run
    which, bg = getattr(os, "PRIO_DARWIN_PROCESS", 4), getattr(os, "PRIO_DARWIN_BG", 0x1000)
    os.setpriority(which, 0, bg)


def pool(workers: int | None = None) -> ProcessPoolExecutor:
    """The worker processes, started with spawn (forking a process whose Qt threads run is
    unsafe), each lowering its own priority as it starts."""
    n = workers or max(1, (os.cpu_count() or 2) - 1)
    return ProcessPoolExecutor(
        max_workers=n, mp_context=multiprocessing.get_context("spawn"), initializer=lower_priority
    )
