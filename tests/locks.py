"""Every one of Qt's connection locks held by a thread that waits on the GIL, for the tests that
force the deadlock docs/process/coding.md's "Threads and processes" names.

Qt guards each object's connections with one of a pool of 131 mutexes, chosen by the object's
address (qobject.cpp's signalSlotLock). The GUI thread takes one and then waits on the GIL when
QML's garbage collector disconnects from a Python-made object (PySide's disconnectNotify). A call
on another thread that holds the GIL and takes one of those mutexes then waits forever, and so
does the GUI thread. Which mutex two objects share is the luck of their addresses, so a test
holds them all: a sender per mutex, each disconnected on a thread of its own, whose
disconnectNotify (made in Python) lets go of the GIL and waits, the mutex held, then needs the
GIL back. A call that takes one of them with the GIL held never returns; one that lets go of the
GIL first waits until they are let go, and returns.

`HOLD` is the Python a test's process of its own runs (a deadlock can't be ended from inside
it): `hold(seconds)` returns once every mutex is held, and each is let go `seconds` after."""

import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

HOLD = """
import threading, time
from PySide6.QtCore import QObject, Signal
from shiboken6 import Shiboken

_inside = set()


class _Holder(QObject):
    held = Signal()
    seconds = 2.0

    def disconnectNotify(self, signal):  # QObject::disconnect(Connection) holds the lock here
        _inside.add(threading.get_ident())
        threading.Event().wait(self.seconds)  # the GIL let go, the lock held; then the GIL wanted


def hold(seconds):
    _Holder.seconds = seconds
    holders, buckets, spare = [], set(), []
    while len(buckets) < 131:  # Qt's pool: uint(quintptr(object)) % 131
        h = _Holder()
        bucket = (Shiboken.getCppPointer(h)[0] & 0xFFFFFFFF) % 131
        (spare if bucket in buckets else holders).append(h)
        buckets.add(bucket)
    threads = [threading.Thread(target=QObject.disconnect, args=(h.held.connect(h.deleteLater),),
                                daemon=True) for h in holders]
    for t in threads:
        t.start()
    while len(_inside) < len(threads):
        time.sleep(0.005)
    return holders + spare, threads
"""


def run(script: str, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[str] | None:
    """`script` run in a process of its own, offscreen, with `HOLD` before it; None when it didn't
    end in `timeout` seconds (a deadlock)."""
    src = os.pathsep.join(p for p in (os.path.join(ROOT, "src"), os.environ.get("PYTHONPATH")) if p)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=src)
    try:
        return subprocess.run([sys.executable, "-c", HOLD + script, *args], env=env,
                              capture_output=True, text=True, timeout=timeout)  # fmt: skip
    except subprocess.TimeoutExpired:
        return None
