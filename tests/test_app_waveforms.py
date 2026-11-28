"""Waveforms in the running app (src/musikata/waveforms.py, the Player bridge's next song;
R11.1.1, A5.1): the shown song's waveform a flat line until found or worked out, filling in after
each part, kept in the index by its hash; the next song's worked out ahead; failures, a dead worker
and closing.

The parts are a stand-in job's, run on a thread pool as tier 1's tests run the worker processes'
jobs (the job itself is tests/test_analysis_waveform.py's); each test waits on the bridge's signal
or its thread, never a set time.

Why: the waveform is worked out off the GUI thread and comes back later; one that lands on the
song after the one it was worked out for, never reaches the index, or is worked out again on every
play is a seek bar that lies or a core kept busy for nothing."""

import logging
import threading
from concurrent.futures import BrokenExecutor, ThreadPoolExecutor

import numpy as np
import pytest
from fakes import FakeEngine, fill

from musikata import bridges
from musikata.waveforms import Waveforms
from musikata_core import db
from musikata_core.analysis import peaks, waveform
from musikata_core.audio.decode import DecodeError

WAIT = 5_000
SONGS = [
    {"path": "a.flac", "title": "A", "album": "X", "track": 1},
    {"path": "b.flac", "title": "B", "album": "X", "track": 2},
    {"path": "c.flac", "title": "C", "album": "X", "track": 3},
]


def part(index, parts, level):
    """Part `index` of `parts`, each 2,000 fine pairs at `level`."""
    top = np.full(peaks.N, level, np.float32)
    return waveform.Part(index, parts, 1, peaks.N * parts, top, -top, peaks.N)


class Job:
    """Parts of songs by file name: `levels[name]` the level of each part; a name in `fails`
    raises its error. Each call is recorded; while `gate` is clear, a part waits for it."""

    def __init__(self, levels, fails=None):
        self.levels, self.fails = levels, fails or {}
        self.calls = []
        self.gate = threading.Event()
        self.gate.set()

    def __call__(self, path, index):
        name = path.rsplit("/", 1)[-1]
        self.calls.append((name, index))
        self.gate.wait()
        if name in self.fails:
            raise self.fails[name]
        levels = self.levels[name]
        return part(index, len(levels), levels[index])


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, SONGS)  # each song's hash is its path
    yield i
    i.close()


@pytest.fixture
def pool():
    p = ThreadPoolExecutor(1)
    yield p
    p.shutdown()


def made(tmp_path, index, pool, job, broken=None):
    w = Waveforms(str(tmp_path), index, lambda: pool, job=job, broken=broken)
    seen = []
    w.changed.connect(lambda: seen.append((w.property("loading"), w.peaks[:, 0].copy())))
    return w, seen


def test_the_shown_song_is_a_flat_line_filling_in_then_whole_and_kept(tmp_path, index, pool, qtbot):
    job = Job({"a.flac": [0.2, 0.4, 0.6]})
    w, seen = made(tmp_path, index, pool, job)
    w.show("a.flac")
    assert w.property("loading") and not w.peaks.any()  # at once: flat
    qtbot.waitUntil(lambda: seen and not seen[-1][0], timeout=WAIT)
    assert job.calls == [("a.flac", 0), ("a.flac", 1), ("a.flac", 2)]
    loading = [s for s in seen if s[0]]
    assert len(loading) == 3  # flat, then after each part but the last
    first_part = loading[1][1]
    assert np.all(first_part[: peaks.N // 3] == 0.2) and np.all(first_part[peaks.N // 3 + 1 :] == 0)
    assert np.allclose(w.peaks[-1], [0.6, -0.6])
    qtbot.waitUntil(lambda: waveform.stored(index.read(), "a.flac") is not None, timeout=WAIT)
    assert np.allclose(waveform.stored(index.read(), "a.flac")[-1], [0.6, -0.6], atol=1e-4)
    w.close()


def test_a_song_kept_is_shown_without_decoding(tmp_path, index, pool, qtbot):
    kept = np.full((peaks.N, 2), 0.5, np.float32)
    index.write(lambda c: waveform.keep(c, "b.flac", kept)).result()
    job = Job({})
    w, seen = made(tmp_path, index, pool, job)
    w.show("b.flac")
    qtbot.waitUntil(lambda: not w.property("loading"), timeout=WAIT)
    assert job.calls == [] and np.allclose(w.peaks, 0.5, atol=1e-4)
    w.show("")  # nothing shown: a flat line, nothing to wait for
    assert not w.property("loading") and not w.peaks.any()
    w.close()


def test_the_next_song_is_worked_out_ahead_and_found_at_once_when_shown(
    tmp_path, index, pool, qtbot
):
    job = Job({"a.flac": [0.3], "b.flac": [0.7, 0.8]})
    w, seen = made(tmp_path, index, pool, job)
    w.show("a.flac")
    w.ahead("b.flac")
    qtbot.waitUntil(lambda: waveform.stored(index.read(), "b.flac") is not None, timeout=WAIT)
    assert job.calls == [("a.flac", 0), ("b.flac", 0), ("b.flac", 1)]  # the shown one first
    assert np.allclose(w.peaks[:, 0], 0.3)  # the next song's never reached the bar
    w.show("b.flac")
    qtbot.waitUntil(lambda: not w.property("loading"), timeout=WAIT)
    assert len(job.calls) == 3 and w.peaks[-1, 0] == pytest.approx(0.8, abs=1e-4)
    w.close()


def test_a_song_no_longer_shown_never_reaches_the_bar(tmp_path, index, pool, qtbot):
    job = Job({"a.flac": [0.1, 0.1, 0.1], "c.flac": [0.9]})
    w, seen = made(tmp_path, index, pool, job)
    job.gate.clear()
    w.show("a.flac")
    qtbot.waitUntil(lambda: job.calls == [("a.flac", 0)], timeout=WAIT)
    w.show("c.flac")  # while a's first part is decoded
    job.gate.set()
    qtbot.waitUntil(lambda: not w.property("loading"), timeout=WAIT)
    assert np.allclose(w.peaks[:, 0], 0.9)
    assert ("a.flac", 1) not in job.calls  # a was left once no longer wanted
    w.wait()
    w.close()


def test_a_song_that_cant_be_decoded_keeps_its_flat_line_and_is_tried_once(
    tmp_path, index, pool, qtbot, caplog
):
    job = Job({}, fails={"c.flac": DecodeError("couldn't open c.flac")})
    w, seen = made(tmp_path, index, pool, job)
    with caplog.at_level(logging.WARNING, logger="musikata.waveforms"):
        w.show("c.flac")
        qtbot.waitUntil(lambda: not w.property("loading"), timeout=WAIT)
    assert not w.peaks.any()
    assert "couldn't work out the waveform of c.flac" in caplog.text
    w.ahead("c.flac")  # shown and next: still not tried again
    w.wait()
    assert job.calls == [("c.flac", 0)]
    w.show("c.flac")  # shown again: said again, from what was found
    qtbot.waitUntil(lambda: not w.property("loading"), timeout=WAIT)
    assert job.calls == [("c.flac", 0)]
    w.close()


def test_a_worker_that_died_is_reported_and_a_bug_is_logged_whole(
    tmp_path, index, pool, qtbot, caplog
):
    told = []
    job = Job({}, fails={"a.flac": BrokenExecutor("a worker died"), "b.flac": KeyError("x")})
    w, seen = made(tmp_path, index, pool, job, broken=told.append)
    w.show("a.flac")
    qtbot.waitUntil(lambda: told == [pool], timeout=WAIT)
    qtbot.waitUntil(lambda: not w.property("loading"), timeout=WAIT)
    with caplog.at_level(logging.ERROR, logger="musikata.waveforms"):
        w.show("b.flac")
        qtbot.waitUntil(lambda: not w.property("loading"), timeout=WAIT)
    assert "working out the waveform of b.flac failed" in caplog.text
    w.close()


def test_a_song_the_index_has_no_hash_for_is_worked_out_and_not_kept(tmp_path, index, pool, qtbot):
    job = Job({"elsewhere.flac": [0.4]})
    w, seen = made(tmp_path, index, pool, job)
    w.show("../elsewhere.flac")  # a file played from outside the root
    qtbot.waitUntil(lambda: not w.property("loading"), timeout=WAIT)
    assert np.allclose(w.peaks[:, 0], 0.4)
    assert index.read().execute("SELECT count(*) FROM waveform").fetchone() == (0,)
    w.close()


def test_closing_ends_the_thread_and_lets_go_of_the_library(tmp_path, index, pool, qtbot):
    job = Job({"a.flac": [0.4]})
    w, _ = made(tmp_path, index, pool, job)
    w.show("a.flac")
    qtbot.waitUntil(lambda: not w.property("loading"), timeout=WAIT)
    w.close()
    assert w._thread is None and w._broken is None
    with pytest.raises(RuntimeError, match="closed"):
        w._workers()
    w.show("b.flac")  # after its close: nothing starts
    assert w._thread is None


def test_the_player_says_which_song_comes_next_as_the_queue_changes(tmp_path, index, qtbot):
    p = bridges.Player(str(tmp_path), FakeEngine(), read=index.read)
    nexts = []
    p.nextSong.connect(nexts.append)
    assert p.timeAt(0.5) == ""  # no song: no time under the pointer
    ids = dict(index.read().execute("SELECT path, id FROM song"))
    p.play_songs([ids["a.flac"], ids["b.flac"], ids["c.flac"]], "X")
    qtbot.waitUntil(lambda: nexts == ["b.flac"], timeout=WAIT)
    p.next()
    qtbot.waitUntil(lambda: nexts == ["b.flac", "c.flac"], timeout=WAIT)
    p.next()
    qtbot.waitUntil(lambda: nexts == ["b.flac", "c.flac", ""], timeout=WAIT)  # nothing after
    p.close()
