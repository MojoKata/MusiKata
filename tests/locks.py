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

A call that first waits on a mutex with the GIL let go, and only then takes one with the GIL held,
gets past `hold`: its first wait outlasts the hold. PySide's `connect` is one: Qt connects without
the GIL, then PySide calls the sender's `connectNotify` with it, and QMediaDevices' connects it to
Qt's own list of devices there. `keep_holding` catches those too: each mutex is held over and over,
taken again as soon as it is let go, so a call waiting without the GIL gets it between two holds,
and one wanting it with the GIL held finds it held about half the time (measured), and never
returns: a test makes such a call several times. Its holds are taken the way the GUI thread took
one in a deadlock seen: a single-shot connection emitted, which Qt disconnects as it fires, under
the sender's and the receiver's mutexes (one here: the receiver is chosen to share the holder's),
calling the sender's disconnectNotify there. Emitting lets go of the GIL as it waits on a mutex;
`QObject.disconnect(connection)`, which `hold` uses, doesn't, so a holder taking its mutex again
that way would wait on the call while holding the GIL the call's own holders wait on.

`HOLD` is the Python a test's process of its own runs (a deadlock can't be ended from inside
it): `hold(seconds)` returns once every mutex is held, and each is let go `seconds` after;
`keep_holding()` returns an event and the holders' threads once every mutex is held, and they are
held until the event is set."""

import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

HOLD = """
import random, threading, time
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from shiboken6 import Shiboken

_inside = set()


class _Holder(QObject):
    held = Signal()
    seconds = 2.0

    def disconnectNotify(self, signal):  # Qt disconnects holding the lock here
        _inside.add(threading.get_ident())
        threading.Event().wait(self.seconds)  # the GIL let go, the lock held; then the GIL wanted


class _Keeper(_Holder):
    def disconnectNotify(self, signal):
        _inside.add(threading.get_ident())
        threading.Event().wait(random.uniform(0.02, 0.1))


def _bucket(o):  # Qt's pool: uint(quintptr(object)) % 131
    return (Shiboken.getCppPointer(o)[0] & 0xFFFFFFFF) % 131


def _holders(kind):
    holders, buckets, spare = [], set(), []
    while len(buckets) < 131:
        h = kind()
        bucket = _bucket(h)
        (spare if bucket in buckets else holders).append(h)
        buckets.add(bucket)
    return holders, spare


def _started(threads):
    for t in threads:
        t.start()
    while len(_inside) < len(threads):
        time.sleep(0.005)


def hold(seconds):
    _Holder.seconds = seconds
    holders, spare = _holders(_Holder)
    threads = [threading.Thread(target=QObject.disconnect, args=(h.held.connect(h.deleteLater),),
                                daemon=True) for h in holders]
    _started(threads)
    return holders + spare, threads


def _keep(holder, stop):
    # the receiver: a timer made here, so its stop, Qt's own slot, is called on this thread and
    # does nothing, and under the holder's own mutex, so the holder never waits on another's
    tried = []
    while not tried or _bucket(tried[-1]) != _bucket(holder):
        tried.append(QTimer())
    idle = tried.pop()
    del tried
    while not stop.is_set():
        holder.held.connect(idle.stop, Qt.ConnectionType.SingleShotConnection)
        holder.held.emit()


def keep_holding():
    holders, spare = _holders(_Keeper)
    stop = threading.Event()
    threads = [threading.Thread(target=_keep, args=(h, stop), daemon=True) for h in holders]
    _started(threads)
    return stop, threads
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
