"""Ratings in the running app (R10.2, R10.3): a star clicked in a list of songs or the now-playing
bar sets that song's rating, the current star clearing it; Ctrl+1 to Ctrl+5 (⌘ on macOS) rate the
open view's selection and Ctrl+0 clears it. However many songs, it is one save: a batch
(tags.Batch) on a thread of its own, whose writer (ratings.Writing) puts each rating where its
song's are kept, in its file or the root's ratings.json; kept in the change history as one entry
and followed by its message with Undo (R4.9, R6.7). The lists and the bar show the new rating at
once (`shownChanged`, Library.show_ratings, Player.show_ratings) and go back to the song's own
when its file wasn't written, the message saying why; once saved, the rows are updated
(Library.saved) and show it from the index. While the root isn't there, nothing is rated, and the
message says why (R2.10).

The root's ratings.json is read into the index at start, off the GUI thread, and again whenever
the watcher sees `.musikata` change (another computer rated a song, A2.8), the lists reading
their rows again then (`changed`).

What a click does and what the message says are decided here, as plain functions
(`new_rating`, `rated_text`, `description_of`), tested without a window."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import db, ratings, rootfiles, scanner, settings, watch
from musikata_core.clock import Clock
from musikata_core.tags import Batch, Failed, Job, Outcome, Written
from musikata_core.tags import save as save_tags

from .bridges import Player
from .edittags import songs_text, target_of
from .history import RATE, ChangeHistory
from .models import PagedModel

log = logging.getLogger(__name__)

CHUNK = 500  # songs read at a time
NOT_THERE = "Ratings can't be set while the music folder isn't available"  # R2.10
NONE_SELECTED = "Select songs to rate them"


# ---------- what a click does and what the message says ----------


def new_rating(star: int, shown: int) -> int:
    """The rating a click on star `star` (1 to 5) sets on a song showing `shown` (R10.2): that
    star, or none when it is the one shown already."""
    return 0 if star == shown else star


def stars_text(stars: int) -> str:
    return "1 star" if stars == 1 else f"{stars} stars"


def description_of(stars: int, songs: int) -> str:
    """What a rating save was, for the Change history (R4.9): "4 stars on 3 songs", "Rating
    cleared on 1 song"."""
    if not stars:
        return f"Rating cleared on {songs_text(songs)}"
    return f"{stars_text(stars)} on {songs_text(songs)}"


def rated_text(outcome: Outcome[Written], stars: int) -> str:
    """The message after a rating is saved (R6.7, R10.2): what was set on how many songs, and
    the first that wasn't, with why, and how many more."""
    done, failed = len(outcome.saved), len(outcome.failed)
    many = songs_text(done + failed) if not failed else f"{done:,} of {songs_text(done + failed)}"
    text = f"{many} rated {stars_text(stars)}" if stars else f"Rating cleared on {many}"
    if not failed:
        return text
    first = outcome.failed[0]
    return f"{text}: {os.path.basename(first.job.path)} {first.why}" + (
        f", and {failed - 1:,} more" if failed > 1 else ""
    )


def paths_of(c: sqlite3.Connection, songs: Sequence[int]) -> dict[int, str]:
    """The paths under the root of the songs of `songs` the index has, by id."""
    out: dict[int, str] = {}
    for i in range(0, len(songs), CHUNK):
        chunk = list(songs[i : i + CHUNK])
        marks = ", ".join("?" * len(chunk))
        out.update(c.execute(f"SELECT id, path FROM song WHERE id IN ({marks})", chunk).fetchall())
    return out


def file_writer(root_tags: settings.RootTags) -> Callable[[Job], Written]:
    """A file's changes written with the root's settings (R4.7.1, R4.7.2, R10.4.1): safe.save."""

    def write(job: Job) -> Written:
        return save_tags(
            job.path, job.changes, audio_hash=scanner.audio_hash,
            id3_version=root_tags.id3_version, keep_mtime=root_tags.keep_modified_times,
            rating_scale=root_tags.rating_scale,
        )  # fmt: skip

    return write


# ---------- the bridge ----------


class Ratings(QObject):
    """Rating songs (R10.2) in the root `root` with the index `index`: each save written by
    `write` (ratings.Writing), kept by `history` (None: no message, no entry), its files' rows
    updated by `saved` (Library.saved). `available` says whether the root is there (R2.10). The
    saves run on `executor`, one at a time (its own thread when None); with `watching`, the
    root's `.musikata` is watched on `clock` for another computer's ratings."""

    shownChanged = Signal(object)  # the ratings being saved, by song id, for the lists and the bar
    changed = Signal()  # ratings.json was read again: the lists read their rows again
    _done = Signal(object, object, int, int)  # a save's outcome, its songs by path, ticket, stars
    _read = Signal()  # ratings.json read into the index

    def __init__(
        self,
        root: str,
        index: db.Index,
        write: Callable[[Job], Written],
        history: ChangeHistory | None,
        clock: Clock,
        saved: Callable[[Sequence[Written]], object] | None = None,
        available: Callable[[], bool] = lambda: True,
        executor: Executor | None = None,
        watching: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._root, self._index, self._write, self._history = root, index, write, history
        self._clock, self._saved, self._available = clock, saved, available
        self._executor = executor
        self._watching = watching
        self._musikata = rootfiles.folder_of(root)
        self._watcher: watch.Watcher | None = None
        self._shown: dict[int, int] = {}  # ratings being saved, by song id
        self._ticket_of: dict[int, int] = {}  # the save each shown rating is from
        self._settled: set[int] = set()  # saved: shown until the rows are read again
        self._tickets = 0
        self._closed = False
        self._done.connect(self._on_done)
        self._read.connect(self._on_read)

    def _submit(self, job: Callable[[], object]) -> None:
        if self._closed:
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="ratings")
        self._executor.submit(self._run, job)

    @staticmethod
    def _run(job: Callable[[], object]) -> None:
        try:
            job()
        except Exception:  # noqa: BLE001  (a job that breaks is logged; MusiKata goes on)
            log.exception("rating songs failed")

    # ---------- ratings.json read and watched (R10.3, A2.8) ----------

    def start(self) -> None:
        """Reads the root's ratings.json into the index, off this thread; then watches
        `.musikata` for another computer's changes."""
        if self._watching and os.path.isdir(self._musikata):
            self._watcher = watch.Watcher(self._musikata, watch.Gatherer(self._clock), parent=self)
            self._watcher.ready.connect(self._on_ready)
        self.reread()

    def reread(self) -> None:
        """ratings.json read into the index again, off this thread."""
        index, root = self._index, self._root

        def job() -> None:
            ratings.reread(index, root)
            self._read.emit()

        self._submit(job)

    @Slot()
    def _on_read(self) -> None:
        if self._watcher is not None:
            self._watcher.watch({"": self._musikata})
        self.changed.emit()

    @Slot()
    def _on_ready(self) -> None:
        assert self._watcher is not None
        if "" in self._watcher.take():
            self.reread()

    # ---------- rating (R10.2) ----------

    @Slot(QObject, int, int)
    def rateRow(self, model: QObject, row: int, star: int) -> None:  # noqa: N802
        """Star `star` clicked on row `row` of a list of songs: that song rated, or its rating
        cleared when it is the one shown."""
        song = model.song_at(row) if isinstance(model, PagedModel) else None
        if song is not None and isinstance(model, PagedModel):
            self.rate([song], new_rating(star, model.rating_at(row)))

    @Slot(QObject, int)
    def rateSelection(self, library: QObject, stars: int) -> None:  # noqa: N802
        """Ctrl+1 to Ctrl+5 (⌘ on macOS), and Ctrl+0 (R10.2, R6.9): the open view's selection
        rated, or its rating cleared."""
        view = library.property("view")
        model = {
            "songs": library.property("songs"),
            "album": library.property("album").property("songs"),
            "artist": library.property("artist").property("others"),
            "folders": library.property("folders").property("model"),
        }.get(view)
        songs = target_of(model)[0] if model is not None else []
        if not songs:
            self._say(NONE_SELECTED)
            return
        self.rate(songs, stars)

    @Slot(QObject, int)
    def ratePlaying(self, player: QObject, star: int) -> None:  # noqa: N802
        """Star `star` clicked in the now-playing bar (R6.5): the song shown rated, or cleared."""
        song = player.song_id() if isinstance(player, Player) else None
        if song is not None:
            self.rate([song], new_rating(star, int(player.property("rating"))))

    def rate(self, songs: Sequence[int], stars: int) -> None:
        """The songs of `songs` (by id) rated `stars` (0: cleared), as one save: shown at once,
        written off this thread."""
        if not songs:
            return
        if not self._available():
            self._say(NOT_THERE)
            return
        self._tickets += 1
        ticket = self._tickets
        for song in songs:
            self._shown[song] = stars
            self._ticket_of[song] = ticket
            self._settled.discard(song)
        self.shownChanged.emit(dict(self._shown))
        record = self._history.recording() if self._history is not None else None
        root, read, write = self._root, self._index.read, self._write
        wanted = list(songs)

        def job() -> None:
            paths = paths_of(read(), wanted)
            jobs = [Job(scanner.full_path(root, p), {"rating": stars}) for p in paths.values()]
            batch = Batch(
                jobs,
                write,
                record=record,
                action=RATE,
                description=description_of(stars, len(jobs)),
            )
            try:
                out = batch.run()
            except Exception as e:  # noqa: BLE001  (the batch fails its files, never itself)
                log.exception("rating %d songs failed", len(jobs))
                out = Outcome(failed=[Failed(j, f"it wasn't rated: {e}") for j in jobs])
            by_path = {scanner.full_path(root, p): s for s, p in paths.items()}
            gone = [s for s in wanted if s not in paths]
            self._done.emit(out, {**by_path, **{f"#{s}": s for s in gone}}, ticket, stars)

        self._submit(job)

    @Slot(object, object, int, int)
    def _on_done(
        self, out: Outcome[Written], songs: Mapping[str, int], ticket: int, stars: int
    ) -> None:
        saved = {songs[w.path] for w in out.saved if w.path in songs}
        for song in set(songs.values()) - saved:  # failed, or gone: back to its own
            if self._ticket_of.get(song) == ticket:
                self._shown.pop(song, None)
                self._ticket_of.pop(song, None)
        for song in saved:
            if self._ticket_of.get(song) == ticket:
                self._settled.add(song)
        self.shownChanged.emit(dict(self._shown))
        if out.saved and self._saved is not None:
            self._saved(out.saved)  # their rows; the lists read them again (`reloaded`)
        if self._history is not None:
            self._history.after_save(out, rated_text(out, stars))

    @Slot()
    def reloaded(self) -> None:
        """The rows were read again (Library.reloaded): ratings saved are shown from them now."""
        if not self._settled:
            return
        for song in self._settled:
            self._shown.pop(song, None)
            self._ticket_of.pop(song, None)
        self._settled.clear()
        self.shownChanged.emit(dict(self._shown))

    def shown(self) -> dict[int, int]:
        """The ratings being saved, by song id."""
        return dict(self._shown)

    def _say(self, text: str) -> None:
        if self._history is not None:
            self._history.say(text)

    def close(self) -> None:
        """Stops watching and waits for a save going on; nothing starts after. What the threads
        held is let go, so this object goes with its window (A1.3)."""
        self._closed = True
        if self._watcher is not None:
            self._watcher.close()
            self._watcher = None
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._history = None
        self._saved = None
        self._available = _gone


def _gone() -> bool:
    """A closed window's root: never there to rate in."""
    return False
