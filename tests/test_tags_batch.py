"""A save of many files (src/musikata_core/tags/batch.py; R4.7): each written in turn, progress
after each, cancellable between files, and the files that failed listed at the end with why, the
rest saved.

Why: the batch is plain logic over the writer it is given, so every way a save of a hundred files
can go (one read-only, one in use, cancelled halfway) is shown here with a writer that writes
nothing, in milliseconds."""

import threading
from concurrent.futures import ThreadPoolExecutor

from musikata_core.tags import Batch, Job, WriteError

JOBS = [Job(f"A/{n}.flac", {"title": f"Song {n}"}) for n in range(1, 6)]


def test_each_file_is_written_in_turn_with_progress_after_each():
    written, progress = [], []
    batch = Batch(JOBS, lambda job: written.append(job.path) or job.path.upper(),
                  lambda done, of, path: progress.append((done, of, path)))  # fmt: skip
    out = batch.run()
    assert written == [j.path for j in JOBS]
    assert out.saved == [j.path.upper() for j in JOBS]
    assert progress == [(n, 5, f"A/{n}.flac") for n in range(1, 6)]
    assert (out.failed, out.cancelled, out.left, out.retry()) == ([], False, [], [])


def test_the_files_that_fail_are_listed_with_why_and_the_others_saved():
    """R4.7: read-only files, files in use and files that fail, each with its reason and a Retry."""

    def write(job):
        if job.path == "A/2.flac":
            raise WriteError(job.path, "it is read-only: let it be written to, then try again")
        if job.path == "A/4.flac":
            raise RuntimeError("a bug")
        return job.path

    out = Batch(JOBS, write).run()
    assert out.saved == ["A/1.flac", "A/3.flac", "A/5.flac"]
    assert [(f.job.path, f.why) for f in out.failed] == [
        ("A/2.flac", "it is read-only: let it be written to, then try again"),
        ("A/4.flac", "it couldn't be written: RuntimeError: a bug"),
    ]
    assert out.retry() == [JOBS[1], JOBS[3]]


def test_cancelled_it_stops_before_the_next_file_never_inside_one():
    written, batches = [], []

    def write(job):
        written.append(job.path)
        if job.path == "A/2.flac":
            batches[0].cancel()  # mid-file: this one is finished first
        return job.path

    batch = Batch(JOBS, write)
    batches.append(batch)
    out = batch.run()
    assert written == ["A/1.flac", "A/2.flac"] and out.saved == written
    assert out.cancelled and batch.cancelled and out.left == JOBS[2:]


def test_it_runs_off_the_calling_thread_and_a_cancel_from_another_stops_it():
    """The GUI thread starts it on a pool and cancels it from there (A1.3, R4.7)."""
    started, go_on = threading.Event(), threading.Event()
    threads = set()

    def write(job):
        threads.add(threading.current_thread())
        if job.path == "A/1.flac":
            started.set()
            assert go_on.wait(10)
        return job.path

    batch = Batch(JOBS, write)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(batch.run)
        assert started.wait(10)
        batch.cancel()
        go_on.set()
        out = future.result(10)
    assert threading.current_thread() not in threads
    assert out.saved == ["A/1.flac"] and out.cancelled and out.left == JOBS[1:]


def test_an_empty_batch_saves_nothing():
    out = Batch([], lambda job: job).run()
    assert (out.saved, out.failed, out.cancelled) == ([], [], False)
