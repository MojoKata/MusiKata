"""Lyrics in the running app (R17.1 to R17.3, R17.5, N04-now-playing-lyrics): Now Playing's Lyrics
switch, kept in the shared settings' `appearance` (A2.10); the lyrics of the song shown, read off
the GUI thread on a thread of its own as the song changes (its `.lrc` beside it, else its tags:
musikata_core.lyrics.choose); the line sung followed as the song plays, and a line clicked seeking
there (R7.4); and Edit… and Add…, the lyrics as text saved where R13.11's setting says (the root's
`lyrics.save`, read at start as the root's other settings are), through the batch and the change
history, so Undo puts them back (R4.9: an `.lrc` is a file of the entry, as cover.jpg is,
history.FileChange.image).

What Now Playing shows of them is decided here as plain data and text (`line_rows`, `where_text`,
…), tested without a window; the QML lays it out: with Waveform in Up next's place, with No
visualization in the queue's, and with 3D analyzer the line sung and the next over the analyzer's
lower part (R17.3). Find online… is R17.4's, slice 10's: shown, faded, saying so; and R17.5's Set
time, timing plain lyrics by tapping along, is a later version's (#7, DEVELOP.md's Later)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, Signal, Slot

from musikata_core import art, lyrics, scanner
from musikata_core.lyrics import Found
from musikata_core.tags import Batch, Failed, Job, Outcome, TagReadError, Written
from musikata_core.tags import read as read_tags

from .history import LYRICS, ChangeHistory
from .models import time_text
from .preview import failed_text

log = logging.getLogger(__name__)

MISSING = "No lyrics for this song"  # R17.3.1
INSTRUMENTAL = "Instrumental"  # R17.2
FIND_LATER = "Finding lyrics online comes in a later version"  # R17.4: slice 10 (#27)
NOT_THERE = "Saving waits until the music folder is back"  # R2.10
NOT_HERE = "Only a song of the library can have lyrics saved"  # a file played from outside it

# what Now Playing shows of them: nothing playing, being read, none, or the lyrics as they are
NONE, LOADING, MISSING_STATE, TIMED, PLAIN, MARKED = (
    "none", "loading", "missing", "timed", "plain", "instrumental"
)  # fmt: skip


# ---------- what it says ----------


def line_rows(found: Found) -> list[dict[str, Any]]:
    """The lines as Now Playing lists them: each its text, its time in seconds (-1: plain) and as
    the line under the pointer shows it (N04's 1:45), and whether it is a pause between verses
    (a timed line with no text, or a blank line between plain ones)."""
    return [
        {
            "text": line.text,
            "time": line.time if line.time is not None else -1.0,
            "timeText": time_text(line.time) if line.time is not None else "",
            "gap": not line.text,
        }
        for line in found.lyrics.lines
    ]


def state_of(path: str, loading: bool, found: Found | None) -> str:
    """What Now Playing shows: NONE with no song, LOADING while its lyrics are read, MISSING_STATE
    when it has none (R17.3.1), MARKED for lyrics marked instrumental, else TIMED or PLAIN."""
    if not path:
        return NONE
    if loading:
        return LOADING
    if found is None:
        return MISSING_STATE
    if found.lyrics.instrumental:
        return MARKED
    return TIMED if found.lyrics.timed else PLAIN


def sung(state: str, rows: Sequence[dict[str, Any]], current: int) -> tuple[str, str]:
    """What the 3D analyzer shows over its lower part (R17.3): of timed lyrics, the line sung at
    `current` and the next with words (before the first line, none and the first; in a pause,
    none and the line after it); "Instrumental"; "No lyrics for this song"; nothing of plain
    lyrics, which have no line sung."""
    if state == MARKED:
        return INSTRUMENTAL, ""
    if state == MISSING_STATE:
        return MISSING, ""
    if state != TIMED:
        return "", ""
    texts = [r["text"] for r in rows]
    now = texts[current] if 0 <= current < len(texts) else ""
    after = next((t for t in texts[max(current + 1, 0) :] if t), "")
    return now, after


def verse_end(rows: Sequence[dict[str, Any]], current: int) -> int:
    """The last line of the verse sung, by its place: the line before the next pause after
    `current` (the last line when none follows). The lines after it are muted more than the
    verse's own (N04); before the first line, -1."""
    if current < 0:
        return -1
    for n in range(current + 1, len(rows)):
        if rows[n]["gap"]:
            return n - 1
    return len(rows) - 1


def save_later(editing: bool, saving: bool, changed: bool, available: bool, here: bool) -> str:
    """Why Save can't save now, as its tooltip says ("": it can): a save going on, the root not
    there (R2.10), a song from outside the library, or nothing changed."""
    if not editing:
        return ""
    if saving:
        return "Saving…"
    if not available:
        return NOT_THERE
    if not here:
        return NOT_HERE
    return "" if changed else "Nothing has changed yet"


def edit_title(title: str, adding: bool) -> str:
    """The editor's title: Edit lyrics · Signal Fires; Add lyrics · Signal Fires."""
    what = "Add lyrics" if adding else "Edit lyrics"
    return f"{what} · {title}" if title else what


def where_text(plan: lyrics.Saving, name: str) -> str:
    """Where Save keeps them (R13.11), under the text: Saved beside the song as 04 - Signal
    Fires.lrc; in the song's tags; or both; removed when the text is empty."""
    if plan.text is None:
        return "Saving with no text removes the lyrics" if plan.file or plan.tags else ""
    if plan.file and plan.tags:
        return f"Saved beside the song as {name} and in its tags"
    return f"Saved beside the song as {name}" if plan.file else "Saved in the song's tags"


def description_of(title: str, had: bool, text: str) -> str:
    """What the save was, for the change history: Lyrics of Signal Fires edited; Lyrics added to
    Signal Fires; Lyrics removed from Signal Fires."""
    song = title or "a song"
    if lyrics.tag_text(text) is None:
        return f"Lyrics removed from {song}"
    return f"Lyrics of {song} edited" if had else f"Lyrics added to {song}"


# ---------- reading them, off the GUI thread ----------


@dataclass(frozen=True)
class Loaded:
    """A song's lyrics as read: the song's whole path, the lyrics it shows (None: none), the path
    of its `.lrc` (None: it has none) and whether its tags hold lyrics."""

    path: str
    found: Found | None
    lrc: str | None
    tagged: bool


def load(path: str, legacy: str = "cp1252") -> Loaded:
    """The lyrics of the song at `path` (R17.1): its `.lrc`'s, else its tags', `legacy` being the
    system's encoding an `.lrc` that isn't UTF-8 is read in. A file that can't be read gives none,
    logged."""
    lrc_path = lyrics.find_lrc(path)
    data = lyrics.read_lrc(lrc_path) if lrc_path is not None else None
    tag = None
    try:
        tag = read_tags(path)[0].lyrics
    except (TagReadError, OSError) as e:
        log.warning("couldn't read the lyrics in the tags of %s: %s", path, e)
    found = lyrics.choose((lrc_path, data) if lrc_path and data is not None else None, tag, legacy)
    return Loaded(path, found, lrc_path, tag is not None)


def _gone() -> bool:
    return False


class Lyrics(QObject):
    """The lyrics of the song `player` (the Player bridge) shows, under `root`: the switch (`on`,
    kept by `keep`, the appearance group's fields, Player.remember_appearance), the lines and the
    one sung, and the editor, whose Save writes through `write` (ratings.Writing: safe.save) and
    `trash` (an `.lrc` replaced or removed goes there), kept in `history`'s change history, the
    rows of the songs written updated by `saved` (Library.saved); `setting` says where saved
    lyrics go (settings.root_lyrics), `available` whether the root is there (R2.10), `legacy` the
    system's encoding an `.lrc` that isn't UTF-8 is read in, `read` how a song's are read
    (`load`)."""

    changed = Signal()  # the switch, what is shown, the editor
    lineChanged = Signal()  # the line sung
    _read_done = Signal(int, object)  # (ticket, Loaded)
    _done = Signal(object)  # a save's Outcome

    def __init__(
        self,
        player: QObject,
        root: str,
        write: Callable[[Job], Written] | None = None,
        history: ChangeHistory | None = None,
        saved: Callable[[list[Written]], object] | None = None,
        on: bool = False,
        keep: Callable[..., object] | None = None,
        setting: Callable[[], str] | None = None,
        available: Callable[[], bool] = lambda: True,
        legacy: str = "cp1252",
        trash: art.Trash = art.to_trash,
        read: Callable[[str, str], Loaded] = load,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._player, self._root, self._write, self._history = player, root, write, history
        self._saved, self._keep, self._available = saved, keep, available
        self._setting = setting or (lambda: lyrics.SAVE[0])
        self._legacy, self._trash, self._read = legacy, trash, read
        self._on = on
        self._path = ""  # the song shown, by its path under the root ("" none)
        self._ticket = 0
        self._loading = False
        self._loaded: Loaded | None = None
        self._rows: list[dict[str, Any]] = []
        self._times: list[float] = []
        self._current = -1
        self._at: float | None = None  # a tour's place in the song (`go`), else the player's
        self._editing = self._adding = self._saving = False
        self._text = self._original = ""
        self._problem = ""
        self._executor: Executor | None = None
        self._closed = False
        self._read_done.connect(self._on_loaded)
        self._done.connect(self._on_done)
        player.nowPlaying.connect(self.show)  # type: ignore[attr-defined]
        player.positionChanged.connect(self._follow)  # type: ignore[attr-defined]
        if history is not None:  # a save's message, or an undo's: read again (R4.9)
            history.messageChanged.connect(self.reread)

    # ---------- the switch (R17.3) ----------

    @Slot()
    def toggle(self) -> None:
        """The Lyrics switch: on shows the song's lyrics, read now when they weren't; kept."""
        self._on = not self._on
        if self._keep is not None:
            self._keep(lyrics=self._on)
        if self._on and self._loaded is None and not self._loading:
            self._start()
        self.changed.emit()

    # ---------- the song shown ----------

    @Slot(str)
    def show(self, path: str) -> None:
        """The song shown is the one at `path` under the root ("" none): its lyrics read while
        the switch is on, else when it is turned on."""
        if path == self._path:
            return
        self._path, self._loaded, self._editing = path, None, False
        self._rows, self._times, self._current = [], [], -1
        self._ticket += 1
        self._loading = False
        if self._on:
            self._start()
        self.changed.emit()
        self.lineChanged.emit()

    @Slot()
    def reread(self) -> None:
        """Reads the song's lyrics again (a save of them, an undo), while shown."""
        if self._on and self._path and not self._closed:
            self._start()

    def _full(self) -> str:
        return (
            self._path if os.path.isabs(self._path) else scanner.full_path(self._root, self._path)
        )

    def _start(self) -> None:
        if not self._path or self._closed:
            return
        self._ticket += 1
        ticket, path, legacy, read = self._ticket, self._full(), self._legacy, self._read
        self._loading = self._loaded is None
        self._submit(lambda: self._read_done.emit(ticket, read(path, legacy)))

    def _submit(self, job: Callable[[], None]) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="lyrics")

        def run() -> None:
            try:
                job()
            except Exception:  # noqa: BLE001  (logged: the lyrics stay as they were)
                log.exception("reading or saving lyrics failed")

        self._executor.submit(run)

    @Slot(int, object)
    def _on_loaded(self, ticket: int, loaded: Loaded) -> None:
        if ticket != self._ticket or self._closed:
            return
        self._loading, self._loaded = False, loaded
        found = loaded.found
        self._rows = line_rows(found) if found is not None else []
        timed = found is not None and found.lyrics.timed and not found.lyrics.instrumental
        self._times = [r["time"] for r in self._rows] if timed else []
        self._current = -2  # told again, whatever it is
        self.changed.emit()
        self._follow()

    @Slot()
    def _follow(self) -> None:
        """The line sung, as the song plays: the last one started (R17.2)."""
        position = self._at if self._at is not None else self._player.property("position")
        line = lyrics.current(self._times, float(position or 0.0)) if self._times else -1
        if line != self._current:
            self._current = line
            self.lineChanged.emit()

    @Slot(int)
    def seekLine(self, row: int) -> None:  # noqa: N802
        """A line clicked: the song sought to its time (R7.4); a plain line does nothing."""
        if self._times and 0 <= row < len(self._rows):
            self._player.seek(float(self._rows[row]["time"]))  # type: ignore[attr-defined]

    # ---------- Edit… and Add… (R17.5) ----------

    @Slot()
    def edit(self) -> None:
        """Edit…: the lyrics shown as text, timed ones with their [mm:ss.xx] times."""
        found = self._loaded.found if self._loaded is not None else None
        self._open(found.text if found is not None else "", found is None)

    @Slot()
    def add(self) -> None:
        """Add…: an empty text, for a song with none (R17.3.1)."""
        self._open("", True)

    def _open(self, text: str, adding: bool) -> None:
        if self._loaded is None or self._saving:
            return
        self._editing, self._adding = True, adding
        self._text = self._original = text
        self._problem = ""
        self.changed.emit()

    @Slot(str)
    def setText(self, text: str) -> None:  # noqa: N802
        if self._editing and text != self._text:
            self._text = text
            self.changed.emit()

    @Slot()
    def cancel(self) -> None:
        """Cancel, ×, or Esc: nothing saved; while a save goes on, nothing (it is one song)."""
        if self._editing and not self._saving:
            self._editing, self._problem = False, ""
            self.changed.emit()

    def _plan(self) -> lyrics.Saving | None:
        if self._loaded is None:
            return None
        had_file, had_tags = self._loaded.lrc is not None, self._loaded.tagged
        return lyrics.saving(self._setting(), self._text, had_file, had_tags)

    @Slot()
    def save(self) -> None:
        """Save: the text written where R13.11's setting says, through the batch, one entry in
        the change history whose Undo puts the lyrics back (R4.9); the editor closes once done,
        or says what failed, Save trying again."""
        if not self._can_save() or self._loaded is None or self._write is None:
            return
        plan = self._plan()
        assert plan is not None
        song, lrc_path = self._loaded.path, self._loaded.lrc or lyrics.lrc_path(self._loaded.path)
        jobs = []
        if plan.file:
            jobs.append(Job(lrc_path, {"image": plan.data}))
        if plan.tags:
            jobs.append(Job(song, {"lyrics": plan.text}))
        if not jobs:
            self.cancel()
            return
        found = self._loaded.found
        what = description_of(self._title(), found is not None, self._text)
        record = self._history.recording() if self._history is not None else None
        batch: Batch[Written | art.ImageWritten] = Batch(
            jobs, art.writer(self._write, self._trash), record=record, action=LYRICS,
            description=what,
        )  # fmt: skip
        self._saving, self._problem = True, ""
        self.changed.emit()

        def run() -> None:
            try:
                out = batch.run()
            except Exception as e:  # noqa: BLE001  (the batch fails its files, never itself)
                log.exception("saving the lyrics of %s failed", song)
                out = Outcome(failed=[Failed(j, f"it wasn't saved: {e}") for j in jobs])
            self._done.emit(out)

        self._submit(run)

    @Slot(object)
    def _on_done(self, out: Outcome[Written | art.ImageWritten]) -> None:
        self._saving = False
        if self._closed:
            return
        written = art.written_songs(out.saved)
        if written and self._saved is not None:
            self._saved(written)
        if self._history is not None:  # its message reads them again (`reread`)
            self._history.after_save(out)  # type: ignore[arg-type]
        if out.failed:
            first = out.failed[0]
            name = os.path.basename(first.job.path)
            self._problem = f"{failed_text(len(out.failed))}: {name} {first.why}"
        else:
            self._editing = False
        self.changed.emit()
        if self._history is None:
            self.reread()

    def _title(self) -> str:
        return str(self._player.property("title") or "")

    def _can_edit(self) -> bool:
        return bool(self._path) and not os.path.isabs(self._path) and self._loaded is not None

    def _save_later(self) -> str:
        here = bool(self._path) and not os.path.isabs(self._path)
        return save_later(self._editing, self._saving, self._text != self._original,
                          self._available(), here)  # fmt: skip

    def _can_save(self) -> bool:
        return self._editing and self._loaded is not None and not self._save_later()

    # ---------- the tour, and closing ----------

    def go(self, step: dict[str, Any]) -> None:
        """A tour's step (A1.6): {"lyrics": {"at": 98}} turns the switch on (not kept: the tour
        keeps nothing) and follows the lyrics as at 98 seconds into the song, the place N04 shows
        (the demo library's songs last a second); off otherwise."""
        wanted = step.get("lyrics")
        self._at = float(wanted.get("at", 0.0)) if isinstance(wanted, dict) else None
        if bool(wanted) != self._on:
            keep, self._keep = self._keep, None
            self.toggle()
            self._keep = keep
        self._follow()

    def close(self) -> None:
        """For closing the window: a read or a save going on is waited for; nothing starts
        after. What the thread held is let go (A1.3)."""
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        if self._history is not None:
            self._history.messageChanged.disconnect(self.reread)
        self._write = self._saved = self._keep = None
        self._history = None
        self._available = _gone

    # ---------- what QML reads ----------

    def _get_state(self) -> str:
        return state_of(self._path, self._loading or (self._on and self._loaded is None),
                        self._loaded.found if self._loaded is not None else None)  # fmt: skip

    def _get_source(self) -> str:
        found = self._loaded.found if self._loaded is not None else None
        return lyrics.source_text(found) if found is not None else ""

    def _get_plain(self) -> str:
        return "\n".join(r["text"] for r in self._rows)

    def _get_where(self) -> str:
        plan = self._plan()
        if plan is None or self._loaded is None:
            return ""
        lrc_path = self._loaded.lrc or lyrics.lrc_path(self._loaded.path)
        return where_text(plan, os.path.basename(lrc_path))

    def _sung(self) -> tuple[str, str]:
        return sung(self._get_state(), self._rows, self._current)

    on = QtProperty(bool, lambda self: self._on, notify=changed)
    state = QtProperty(str, _get_state, notify=changed)  # none, loading, missing, timed, …
    source = QtProperty(str, _get_source, notify=changed)  # Timed · from 04 - Signal Fires.lrc
    lines = QtProperty(list, lambda self: self._rows, notify=changed)  # line_rows
    plainText = QtProperty(str, _get_plain, notify=changed)
    current = QtProperty(int, lambda self: max(self._current, -1), notify=lineChanged)
    near = QtProperty(int, lambda self: verse_end(self._rows, self._current), notify=lineChanged)
    currentText = QtProperty(str, lambda self: self._sung()[0], notify=lineChanged)
    nextText = QtProperty(str, lambda self: self._sung()[1], notify=lineChanged)
    canEdit = QtProperty(bool, _can_edit, notify=changed)
    editing = QtProperty(bool, lambda self: self._editing, notify=changed)
    adding = QtProperty(bool, lambda self: self._adding, notify=changed)
    editTitle = QtProperty(
        str, lambda self: edit_title(self._title(), self._adding), notify=changed
    )
    editText = QtProperty(str, lambda self: self._text, notify=changed)
    editWhere = QtProperty(str, _get_where, notify=changed)
    editProblem = QtProperty(str, lambda self: self._problem, notify=changed)  # a save's failure
    canSave = QtProperty(bool, _can_save, notify=changed)
    saveLater = QtProperty(str, _save_later, notify=changed)  # why Save can't, as its tooltip
    saving = QtProperty(bool, lambda self: self._saving, notify=changed)
    missingText = QtProperty(str, lambda self: MISSING, constant=True)
    instrumentalText = QtProperty(str, lambda self: INSTRUMENTAL, constant=True)
    findLater = QtProperty(str, lambda self: FIND_LATER, constant=True)
