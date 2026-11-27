"""Smart playlists in the running app (R8.9): their rule in words on their page, New smart
playlist… and Edit rule, and their songs kept current.

- **What it says** (`rule_text`, `reading_text`, `matches_text`): the rule in words, as the page
  shows it over its songs ("Rated 4 stars and up · highest rated first"), a newer MusiKata's
  rule or a broken one saying so, and how many songs the dialog's rule matches as it changes.
- **The dialog** (`SmartPlaylists`, `Form`): New smart playlist… beside + in the sidebar, and Edit
  rule on a smart playlist's page: each condition with its box and its value, the limit and the
  order, the count of songs matching worked out off the GUI thread as the rule changes, and Save,
  which makes the playlist (named from its rule, opened, its name selected for editing as R8.3's
  +), or writes the playlist's new rule and its songs, through musikata_core.playlists.Store.
- **Kept current** (`SmartPlaylists.poke`, `pokePlays`): after a scan, a save or a rating (the
  library read again) and after plays, musikata_core.smart.Keeper checks each smart playlist on
  a thread of its own, writing those whose songs changed at its pace, and a timer brings the
  next check when one waits; the views are read again after a write.

What the dialog's values make of a rule is decided here as plain functions (`rule_of`,
`form_of`), tested without a window; the QML only binds (SmartRuleDialog.qml)."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Mapping
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from musikata_core import smart as core
from musikata_core.clock import Clock, SystemClock
from musikata_core.playlists import Changed, PlaylistError, Store
from musikata_core.smart import Reading, Rule

from .models import plural

if TYPE_CHECKING:
    from .bridges import Library

log = logging.getLogger(__name__)

NOT_THERE = "Playlists can't be changed while the music folder isn't available"  # R2.10
# the conditions, in the dialog's order: name, label, the unit after its value
CONDITIONS = (
    ("rating", "Rating at least", "stars"),
    ("genre", "Genre is", ""),
    ("artist", "Artist is", ""),
    ("years", "Year between", "and"),
    ("added", "Added in the last", "days"),
    ("plays", "Played at least", "times"),
)
STAR_WORDS = {1: "1 star", 2: "2 stars", 3: "3 stars", 4: "4 stars", 5: "5 stars"}
NEWER_LATER = "Its rule is a newer MusiKata's: update MusiKata to change it"


# ---------- what it says ----------


def _years_text(years: tuple[int | None, int | None]) -> str:
    low, high = years
    if low == high:
        return f"from {low}"
    if low is None:
        return f"from {high} or before"
    if high is None:
        return f"from {low} or after"
    return f"from {low} to {high}"


def rule_text(rule: Rule) -> str:
    """A smart playlist's rule in words (R8.9: its view shows the rule): its conditions, then
    its limit and order. "Rated 4 stars and up · genre Jazz · the first 50, highest rated
    first"."""
    parts = []
    if rule.rating is not None:
        parts.append(f"Rated {STAR_WORDS[rule.rating]}" + (" and up" if rule.rating < 5 else ""))
    if rule.genre is not None:
        parts.append(f"genre {rule.genre.strip()}")
    if rule.artist is not None:
        parts.append(f"by {rule.artist.strip()}")
    if rule.years is not None:
        parts.append(_years_text(rule.years))
    if rule.added is not None:
        parts.append(f"added in the last {plural(rule.added, 'day')}")
    if rule.plays is not None:
        parts.append(f"played {plural(rule.plays, 'time')} or more")
    said = " · ".join(parts) or "Every song"
    said = said[:1].upper() + said[1:]
    order = core.ORDERS[rule.order][0]
    limit = f"the first {plural(rule.limit, 'song')}, " if rule.limit is not None else ""
    return f"{said} · {limit}{order}"


def reading_text(reading: Reading) -> str:
    """What a playlist's page says of its rule: the rule in words; a newer MusiKata's, kept as
    it is; or a broken one, why, and that the playlist is a plain list until it is fixed."""
    if reading.kind == core.BROKEN:
        return f"Its rule can't be used ({reading.why}): it is kept as a plain list"
    if reading.kind == core.NEWER:
        return f"{rule_text(reading.rule)} · a newer MusiKata's rule, kept as it is"
    return rule_text(reading.rule)


def matches_text(n: int | None, limit: int | None) -> str:
    """How many songs the dialog's rule matches, as it changes: "Counting…" while it is worked
    out, and how many of them the limit keeps."""
    if n is None:
        return "Counting…"
    if not n:
        return "No song matches it yet"
    said = f"{plural(n, 'song')} {'matches' if n == 1 else 'match'}"
    if limit is not None and limit < n:
        said += f"; the first {limit:,} are kept"
    return said


# ---------- the dialog's values ----------


@dataclass
class Form:
    """The dialog's values as typed: each condition on or off and its text (`years` from and
    to), the limit on or off and its text, the order; and the fields of the rule edited it
    doesn't know, kept."""

    on: dict[str, bool] = field(default_factory=dict)
    value: dict[str, str] = field(default_factory=dict)
    to: str = ""  # the year the years run to
    limit_on: bool = False
    limit: str = ""
    order: str = core.DEFAULT_ORDER
    extra: tuple[tuple[str, str], ...] = ()


DEFAULTS = {"rating": "4", "genre": "", "artist": "", "years": "", "added": "30", "plays": "5"}


def form_of(rule: Rule | None) -> Form:
    """The dialog's values for `rule` (None: a new one, nothing chosen yet; a rating of 4,
    30 days and 5 plays offered when one is ticked)."""
    f = Form(value=dict(DEFAULTS), limit="50")
    if rule is None:
        return f
    for name in ("rating", "genre", "artist", "added", "plays"):
        value = getattr(rule, name)
        f.on[name] = value is not None
        if value is not None:
            f.value[name] = str(value)
    if rule.years is not None:
        f.on["years"] = True
        low, high = rule.years
        f.value["years"] = "" if low is None else str(low)
        f.to = "" if high is None else str(high)
    f.limit_on = rule.limit is not None
    if rule.limit is not None:
        f.limit = str(rule.limit)
    f.order, f.extra = rule.order, rule.extra
    return f


def _number(text: str, low: int, high: int | None = None) -> int | None:
    text = text.strip().replace(",", "")
    if not text.isascii() or not text.isdigit():
        return None
    n = int(text)
    return n if n >= low and (high is None or n <= high) else None


WHY = {
    "rating": "Choose the stars",
    "genre": "Type the genre",
    "artist": "Type the artist",
    "years": "Type a year, or two",
    "added": "Type a number of days",
    "plays": "Type a number of times",
}


def rule_of(f: Form) -> tuple[Rule | None, str]:
    """The rule the dialog's values make, or None and why it can't be saved yet: a condition
    ticked whose value isn't one, a limit that isn't a number of songs, or no condition."""
    values: dict[str, Any] = {}
    for name, _label, _unit in CONDITIONS:
        if not f.on.get(name):
            continue
        text = f.value.get(name, "")
        if name == "rating":
            value: Any = _number(text, 1, core.STARS)
        elif name in ("genre", "artist"):
            value = text.strip() or None
        elif name == "years":
            low, high = _number(text, 1, 9999), _number(f.to, 1, 9999)
            bad = (text.strip() and low is None) or (f.to.strip() and high is None)
            value = None if bad or (low is None and high is None) else (low, high)
            if value is not None and low is not None and high is not None and low > high:
                value = (high, low)
        else:
            value = _number(text, 1)
        if value is None:
            return None, WHY[name]
        values[name] = value
    if not values:
        return None, "Choose at least one condition"
    limit = None
    if f.limit_on:
        limit = _number(f.limit, 1)
        if limit is None:
            return None, "Type how many songs it keeps"
    order = f.order if f.order in core.ORDERS else core.DEFAULT_ORDER
    return Rule(**values, limit=limit, order=order, extra=f.extra), ""


# ---------- the bridge ----------


class SmartPlaylists(QObject):
    """New smart playlist… and Edit rule (R8.9), and smart playlists kept current. Changes run
    through `store` on a thread of its own (`executor`, made when first needed), with `read` that
    thread's connection to the index and `clock` the time (the days added); then the library's
    views are read again (`library`: Library.reload), a message said (`say`), and a new one's
    name selected for editing (`rename`: Playlists.startRename). `available` says whether the
    root is there (R2.10)."""

    changed = Signal()  # the dialog: opened, its values, its count, its title
    checked = Signal()  # a check of the smart playlists done (written or not)
    _done = Signal(object)

    def __init__(
        self,
        store: Store,
        library: Library | None,
        read: Callable[[], sqlite3.Connection],
        clock: Clock | None = None,
        say: Callable[[str], object] | None = None,
        rename: Callable[[int], object] | None = None,
        available: Callable[[], bool] = lambda: True,
        executor: Executor | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store, self._library, self._read = store, library, read
        self._clock = clock if clock is not None else SystemClock()
        self._say_to, self._rename, self._available = say, rename, available
        self._executor = executor
        self._closed = False
        self._keeper = core.Keeper(store, read, self._clock)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.pokePlays)
        self._form: Form | None = None  # the dialog's values while it is open
        self._playlist = -1  # the playlist whose rule is edited; -1: a new one
        self._name = ""
        self._count: int | None = None
        self._asked = 0  # the count last asked for: an older answer is passed by
        self._done.connect(self._on_done)

    # ---------- running on the thread ----------

    def _say(self, text: str) -> None:
        if self._say_to is not None and text:
            self._say_to(text)

    def _run(self, job: Callable[[], Any], then: Callable[[Any], None]) -> None:
        """job() on the smart playlists' thread; then(its result, or the PlaylistError it
        raised) here."""
        if self._closed:
            return
        if self._executor is None:
            self._executor = ThreadPoolExecutor(1, thread_name_prefix="smart playlists")

        def guarded() -> None:
            try:
                result: Any = job()
            except PlaylistError as e:
                result = e
            except Exception as e:  # noqa: BLE001  (logged; the message says it failed)
                log.exception("a smart playlist's change failed")
                result = PlaylistError(f"It couldn't be done: {e}")
            self._done.emit((then, result))

        self._executor.submit(guarded)

    @Slot(object)
    def _on_done(self, done: tuple[Callable[[Any], None], Any]) -> None:
        then, result = done
        if self._closed:
            return
        if isinstance(result, PlaylistError):
            self._say(str(result))
            self._reload()
            return
        then(result)

    def _reload(self) -> None:
        if self._library is not None:
            self._library.reload()

    def _now(self) -> float:
        return float(self._clock.now().timestamp())

    # ---------- kept current ----------

    def _check(self, cause: str) -> None:
        if self._closed or not self._available():
            return
        keeper = self._keeper

        def then(out: core.Checked) -> None:
            if out.due is not None:
                self._timer.start(max(1, round(out.due * 1000)))
            if out.written:
                self._reload()
            self.checked.emit()

        self._run(lambda: keeper.check(cause), then)

    @Slot()
    def poke(self) -> None:
        """The library changed (a scan, a save, a rating: its views read again): each smart
        playlist checked, those whose songs changed written within a minute (core.QUICK)."""
        self._check(core.LIBRARY)

    @Slot()
    def pokePlays(self) -> None:  # noqa: N802
        """Songs were played (R7.9): each smart playlist checked, those whose songs changed by
        plays alone written at most every ten minutes (core.SLOW); a change the library made that
        waits goes at its own pace."""
        self._check(core.PLAYED)

    def due(self) -> float | None:
        """Seconds the next check waiting on a playlist's pace was set for; None when none
        waits."""
        return self._timer.interval() / 1000 if self._timer.isActive() else None

    # ---------- the dialog ----------

    @Slot()
    def openNew(self) -> None:  # noqa: N802
        """New smart playlist… (R8.9): the dialog, nothing chosen yet."""
        if not self._can():
            return
        self._form, self._playlist, self._name = form_of(None), -1, ""
        self._recount()

    @Slot(int)
    def openEdit(self, playlist: int) -> None:  # noqa: N802
        """Edit rule on a smart playlist's page (R8.9): the dialog with its rule, or what could be
        read of a broken one. A newer MusiKata's isn't changed."""
        r = self._read().execute("SELECT name, rule FROM playlist WHERE id = ?", (playlist,))
        row = r.fetchone()
        if row is None or not self._can():
            return
        reading = core.reading_of(row[1])
        if reading is not None and reading.kind == core.NEWER:
            self._say(NEWER_LATER)
            return
        self._form = form_of(reading.rule if reading is not None else None)
        self._playlist, self._name = playlist, str(row[0])
        self._recount()

    def _can(self) -> bool:
        if not self._available():
            self._say(NOT_THERE)
            return False
        return True

    def _recount(self) -> None:
        """The count of songs the dialog's rule matches, worked out again off the GUI thread."""
        self._asked += 1
        self._count = None
        self.changed.emit()
        if self._form is None:
            return
        rule, _why = rule_of(self._form)
        if rule is None:
            return
        asked, read, now = self._asked, self._read, self._now()

        def then(n: int) -> None:
            if asked == self._asked and self._form is not None:
                self._count = n
                self.changed.emit()

        self._run(lambda: core.count(read(), rule, now), then)

    @Slot(str, bool)
    def setOn(self, name: str, on: bool) -> None:  # noqa: N802
        """A condition's box, or the limit's ("limit"), ticked or not."""
        if self._form is None:
            return
        if name == "limit":
            self._form.limit_on = on
        else:
            self._form.on[name] = on
        self._recount()

    @Slot(str, str)
    def setValue(self, name: str, text: str) -> None:  # noqa: N802
        """A condition's value typed (or its stars clicked), the year it runs to ("to"), or the
        limit's ("limit"); a value typed ticks its box."""
        f = self._form
        if f is None:
            return
        if name == "limit":
            f.limit, f.limit_on = text, f.limit_on or bool(text.strip())
        elif name == "to":
            f.to = text
            f.on["years"] = f.on.get("years", False) or bool(text.strip())
        else:
            f.value[name] = text
            f.on[name] = f.on.get(name, False) or bool(text.strip())
        self._recount()

    @Slot(str)
    def setOrder(self, order: str) -> None:  # noqa: N802
        if self._form is not None and order in core.ORDERS:
            self._form.order = order
            self._recount()

    @Slot()
    def cancel(self) -> None:
        self._form, self._playlist, self._count = None, -1, None
        self._asked += 1
        self.changed.emit()

    @Slot()
    def save(self) -> None:
        """Save: a new smart playlist made, opened and its name selected for editing (R8.3's
        way), or the playlist's new rule and its songs written (R8.9)."""
        if self._form is None or not self._can():
            return
        rule, _why = rule_of(self._form)
        if rule is None:
            return
        playlist, store, read, now = self._playlist, self._store, self._read, self._now()
        self.cancel()

        def make() -> Changed:
            paths = core.songs(read(), rule, now)
            if playlist < 0:
                return store.create_smart(rule, paths, core.suggested_name(rule))
            return store.set_rule(playlist, rule, paths)

        def then(done: Changed) -> None:
            self._reload()
            if playlist < 0 and done.playlist is not None:
                self._say(f"Made {done.name} with {plural(done.count, 'song')}")
                if self._library is not None:
                    self._library.openPlaylist(done.playlist)
                if self._rename is not None:
                    self._rename(done.playlist)
            else:
                self._say(f"{done.name} now holds {plural(done.count, 'song')}")

        self._run(make, then)

    # ---------- the tour, and closing ----------

    def go(self, step: Mapping[str, Any]) -> None:
        """A tour's step (A1.6): {"rule": True} opens Edit rule on the playlist shown; any other
        step closes it."""
        if not step.get("rule"):
            if self._form is not None:
                self.cancel()
            return
        if self._library is not None:
            page = self._library.property("playlistPage")
            if page.property("id") >= 0:
                self.openEdit(int(page.property("id")))

    def shut(self) -> None:
        """For closing the window: a change or check going on finishes; nothing starts after.
        What the thread held is let go (A1.3)."""
        self._closed = True
        self._timer.stop()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._say_to = self._library = self._rename = None
        self._available = _gone

    # ---------- what QML reads ----------

    def _get_conditions(self) -> list[dict[str, Any]]:
        f = self._form or Form()
        return [
            {"name": name, "label": label, "unit": unit, "on": bool(f.on.get(name)),
             "value": f.value.get(name, ""), "to": f.to if name == "years" else ""}
            for name, label, unit in CONDITIONS
        ]  # fmt: skip

    def _get_orders(self) -> list[dict[str, Any]]:
        chosen = self._form.order if self._form is not None else core.DEFAULT_ORDER
        return [{"order": name, "label": label[:1].upper() + label[1:], "chosen": name == chosen}
                for name, (label, _sql) in core.ORDERS.items()]  # fmt: skip

    def _get_title(self) -> str:
        if self._form is None:
            return ""
        return "New smart playlist" if self._playlist < 0 else f"Edit the rule of {self._name}"

    def _get_match(self) -> str:
        if self._form is None:
            return ""
        rule, why = rule_of(self._form)
        if rule is None:
            return why
        return matches_text(self._count, rule.limit)

    def _get_later(self) -> str:
        return rule_of(self._form)[1] if self._form is not None else ""

    opened = QtProperty(bool, lambda self: self._form is not None, notify=changed)
    title = QtProperty(str, _get_title, notify=changed)
    conditions = QtProperty(list, _get_conditions, notify=changed)
    orders = QtProperty(list, _get_orders, notify=changed)
    limitOn = QtProperty(
        bool, lambda self: bool(self._form and self._form.limit_on), notify=changed
    )
    limit = QtProperty(str, lambda self: self._form.limit if self._form else "", notify=changed)
    matchText = QtProperty(str, _get_match, notify=changed)
    saveLater = QtProperty(str, _get_later, notify=changed)


def _gone() -> bool:
    return False
