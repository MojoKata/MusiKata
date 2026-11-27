"""A song list's selection (R2.6, R7.1, R6.9): which rows are selected, the anchor a Shift-click or
Shift+↑/↓ extends a range from, and the current row the arrow keys move and the focus ring marks.
Each is held by the row's key (a song's id in the library's lists, a queue entry's key in Up next),
never its row number, so the selection stays with its songs however the list is scrolled, paged,
sorted or read again after a scan, and a song that leaves the list leaves the selection (`keep`).

Plain Python, without Qt: a list model hands it the list's keys in their order with each click or
key, and asks it which rows are selected. What a key does is decided here, by its name
(`KEYS`, `press`), so QML only forwards it."""

from __future__ import annotations

from collections.abc import Hashable, Sequence

NOT_MINE = -2  # what `press` says of a key the list doesn't use: it goes on to whatever holds it
NONE, SOME, ALL = "none", "some", "all"  # a header checkbox's states

# the keys a list moves its current row with (R6.9, R18.2), and by how many rows: a page's worth is
# `page`, which the view knows; Home and End go as far as the list goes
STEPS = {"up": -1, "down": 1, "pageup": -1, "pagedown": 1, "home": -1, "end": 1}
KEYS = (*STEPS, "all", "clear")


class Selection[K: Hashable]:
    """The keys selected, the anchor and the current row, each None when there is none."""

    def __init__(self) -> None:
        self._chosen: set[K] = set()
        self.anchor: K | None = None
        self.current: K | None = None

    def __contains__(self, key: object) -> bool:
        return key in self._chosen

    def __len__(self) -> int:
        return len(self._chosen)

    @staticmethod
    def _row(keys: Sequence[K], key: K | None) -> int:
        if key is None:
            return -1
        try:
            return keys.index(key)
        except ValueError:
            return -1

    def click(self, keys: Sequence[K], row: int, ctrl: bool = False, shift: bool = False) -> bool:
        """A click on row `row` of the list `keys`: it alone selected; with Ctrl (⌘ on macOS) it
        added or taken away; with Shift the rows from the anchor to it, those selected before kept
        too with Ctrl as well. It becomes the current row, and the anchor but for a Shift-click.
        False, and nothing changed, for a row past the list."""
        if not 0 <= row < len(keys):
            return False
        key = keys[row]
        anchor = self._row(keys, self.anchor)
        if shift and anchor >= 0:
            low, high = sorted((anchor, row))
            self._chosen = (self._chosen if ctrl else set()) | set(keys[low : high + 1])
        elif ctrl:
            self._chosen ^= {key}
            self.anchor = key
        else:
            self._chosen = {key}
            self.anchor = key
        self.current = key
        return True

    def toggle(self, keys: Sequence[K], row: int) -> bool:
        """Row `row`'s checkbox: it added to the selection or taken away, as a Ctrl-click."""
        return self.click(keys, row, ctrl=True)

    def step(self, keys: Sequence[K], by: int, shift: bool = False) -> int:
        """↑ and ↓ (by -1 and 1, or a page's rows): the current row moves `by` rows, stopping at
        the list's ends, and is selected alone; with Shift the rows from the anchor to it are. With
        no current row it starts from above the first, so ↓ (and ↑) take the first row. Returns
        the new current row, -1 for an empty list."""
        if not keys:
            return -1
        at = self._row(keys, self.current)
        row = max(0, min(len(keys) - 1, (by - 1 if by > 0 else 0) if at < 0 else at + by))
        if shift:
            if self._row(keys, self.anchor) < 0:
                self.anchor = keys[at if at >= 0 else row]
            self.click(keys, row, shift=True)
        else:
            self.click(keys, row)
        return row

    def press(self, keys: Sequence[K], name: str, shift: bool = False, page: int = 1) -> int:
        """A key on the list, by its name in KEYS: those of STEPS move the current row (`step`),
        a page's being `page` rows; "all" (Ctrl+A, ⌘A) selects every row; "clear" (Esc) clears
        the selection, and isn't the list's when nothing is selected, so Esc goes on to close what
        holds it. Returns the row to bring into view, -1 for none, or NOT_MINE for a key the list
        doesn't use."""
        if name in STEPS:
            rows = {"up": 1, "down": 1, "home": len(keys), "end": len(keys)}.get(name, page)
            return self.step(keys, STEPS[name] * max(1, rows), shift)
        if name == "all":
            self.select_all(keys)
            return -1
        if name == "clear" and self._chosen:
            self.clear()
            return -1
        return NOT_MINE

    def select_all(self, keys: Sequence[K]) -> None:
        """Every row of the list: the rows a search leaves, while one filters it."""
        self._chosen = set(keys)

    def select(self, keys: Sequence[K], chosen: Sequence[K]) -> None:
        """Exactly the rows of `chosen` that are in the list, with no anchor or current row: as
        the tour shows a selection."""
        self._chosen = set(chosen) & set(keys)
        self.anchor = self.current = None

    def toggle_all(self, keys: Sequence[K]) -> None:
        """The header's checkbox: every row selected when none is, none when any is."""
        if self._chosen:
            self.clear()
        else:
            self.select_all(keys)

    def clear(self) -> None:
        """Nothing selected, and no anchor; the current row stays, for the arrow keys."""
        self._chosen = set()
        self.anchor = None

    def keep(self, keys: Sequence[K]) -> bool:
        """The list is now `keys` (another order, a search, a scan read in): what is selected
        stays selected where it now is, and a song gone from the list leaves the selection, the
        anchor and the current row. Whether the selection changed."""
        there = set(keys)
        kept = self._chosen & there
        changed = kept != self._chosen
        self._chosen = kept
        if self.anchor not in there:
            self.anchor = None
        if self.current not in there:
            self.current = None
        return changed

    def chosen(self, keys: Sequence[K]) -> list[K]:
        """The keys selected, in the list's order."""
        return [k for k in keys if k in self._chosen] if self._chosen else []

    def first(self, keys: Sequence[K]) -> int:
        """The row of the first key selected, in the list's order; -1 for none."""
        if self._chosen:
            for row, key in enumerate(keys):
                if key in self._chosen:
                    return row
        return -1

    def state(self, keys: Sequence[K]) -> str:
        """The header's checkbox: NONE, SOME or ALL of the list selected."""
        if not self._chosen:
            return NONE
        return ALL if len(self._chosen) >= len(keys) else SOME


def selection_text(n: int) -> str:
    """The selection bar's count (L03-songs-bulk-edit): 4 selected."""
    return f"{n:,} selected"
