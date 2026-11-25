"""The worker processes (src/musikata_core/workers.py; A1.3): spawned, each at low priority.

Why: the scan's tag reads keep a core busy; in the app's own process they would make the window
wait for every row it draws, and at normal priority they would compete with the sound."""

import os
import sys

import pytest

from musikata_core import workers


def _niceness():
    return os.nice(0)


@pytest.mark.slow
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux's niceness")
def test_a_worker_runs_at_a_lower_priority_than_the_app():
    with workers.pool(1) as p:
        theirs = p.submit(_niceness).result(timeout=60)
    assert theirs >= min(19, _niceness() + 10)


@pytest.mark.slow
def test_the_pool_is_spawned_and_one_fewer_than_the_cores():
    with workers.pool() as p:
        assert p._mp_context.get_start_method() == "spawn"
        assert p._max_workers == max(1, (os.cpu_count() or 2) - 1)


def test_each_platform_lowers_its_own_way(monkeypatch):
    called = []
    monkeypatch.setattr(workers, "_windows", lambda: called.append("windows"))
    monkeypatch.setattr(workers, "_macos", lambda: called.append("macos"))
    monkeypatch.setattr(workers, "_linux", lambda: called.append("linux"))
    for platform in ("win32", "darwin", "linux"):
        monkeypatch.setattr(workers.sys, "platform", platform)
        workers.lower_priority()
    assert called == ["windows", "macos", "linux"]


class _Libc:
    def __init__(self, result):
        self.result, self.calls = result, []

    def syscall(self, *args):
        self.calls.append(args)
        return self.result


def test_linux_lowers_cpu_and_asks_for_idle_io_and_logs_a_refusal(monkeypatch, caplog):
    nices, libc = [], _Libc(-1)
    monkeypatch.setattr(workers.os, "nice", nices.append)
    monkeypatch.setattr(workers.ctypes, "CDLL", lambda *a, **k: libc)
    monkeypatch.setattr(workers.ctypes, "get_errno", lambda: 1)
    caplog.set_level("INFO")
    workers._linux()
    machine = os.uname().machine
    if machine in workers.SYS_IOPRIO_SET:
        assert libc.calls == [(workers.SYS_IOPRIO_SET[machine], 1, 0, 3 << 13)]
        assert "refused" in caplog.text
    assert nices == [10]


def test_linux_on_a_machine_without_a_known_syscall_number_only_lowers_cpu(monkeypatch):
    nices = []
    monkeypatch.setattr(workers.os, "nice", nices.append)
    monkeypatch.setattr(workers.os, "uname", lambda: type("U", (), {"machine": "mips"})())
    workers._linux()
    assert nices == [10]
