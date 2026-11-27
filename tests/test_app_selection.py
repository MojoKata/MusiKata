"""A song list's selection (src/musikata/selection.py; R2.6, R7.1, R6.9): clicks, Ctrl- and
Shift-clicks, the arrow keys with and without Shift, Ctrl+A and Esc, each on a list of keys, and
the selection kept by key as the list is sorted, filtered or read again.

Why: what a click or a key selects is decided here for every song list, and a selection held by
row would follow the rows, not the songs, the moment the list is sorted or paged."""

from musikata.selection import ALL, NONE, NOT_MINE, SOME, Selection, selection_text

KEYS = [10, 11, 12, 13, 14, 15]


def test_a_click_selects_one_ctrl_adds_or_takes_away_and_shift_takes_the_range():
    s = Selection()
    assert s.click(KEYS, 1)
    assert s.chosen(KEYS) == [11] and s.anchor == s.current == 11
    s.click(KEYS, 3, ctrl=True)
    assert s.chosen(KEYS) == [11, 13] and s.anchor == 13
    s.click(KEYS, 1, ctrl=True)  # taken away, and the anchor
    assert s.chosen(KEYS) == [13] and s.anchor == 11
    s.click(KEYS, 3)
    s.click(KEYS, 5, shift=True)  # from the anchor, 13, to it; what was selected before goes
    assert s.chosen(KEYS) == [13, 14, 15] and s.anchor == 13 and s.current == 15
    s.click(KEYS, 0, shift=True)  # the other way from the same anchor
    assert s.chosen(KEYS) == [10, 11, 12, 13]
    s.click(KEYS, 5, ctrl=True)
    s.click(KEYS, 3, ctrl=True, shift=True)  # Ctrl+Shift adds the range to what was selected
    assert s.chosen(KEYS) == [10, 11, 12, 13, 14, 15] and len(s) == 6 and 12 in s


def test_a_shift_click_with_no_anchor_selects_the_row_alone_and_a_click_past_the_list_nothing():
    s = Selection()
    s.click(KEYS, 2, shift=True)
    assert s.chosen(KEYS) == [12] and s.anchor == 12
    assert not s.click(KEYS, 6) and not s.click(KEYS, -1) and not s.click([], 0)
    assert s.chosen(KEYS) == [12]
    assert s.toggle(KEYS, 4) and s.chosen(KEYS) == [12, 14]  # a checkbox: as a Ctrl-click


def test_the_arrows_move_the_current_row_selecting_it_and_shift_extends_from_the_anchor():
    s = Selection()
    assert s.step(KEYS, 1) == 0  # no current row: ↓ takes the first
    assert s.chosen(KEYS) == [10] and s.current == 10
    assert s.step(KEYS, 1) == 1 and s.chosen(KEYS) == [11] and s.anchor == 11
    assert s.step(KEYS, 1, shift=True) == 2
    assert s.step(KEYS, 1, shift=True) == 3
    assert s.chosen(KEYS) == [11, 12, 13] and s.anchor == 11 and s.current == 13
    assert s.step(KEYS, -1, shift=True) == 2 and s.chosen(KEYS) == [11, 12]
    assert s.step(KEYS, -5, shift=True) == 0 and s.chosen(KEYS) == [10, 11]  # stops at the top
    assert s.step(KEYS, 99) == 5 and s.chosen(KEYS) == [15]  # and at the bottom
    assert s.step([], 1) == -1


def test_shift_and_an_arrow_with_no_anchor_extends_from_the_current_row():
    s = Selection()
    s.click(KEYS, 2)
    s.clear()  # Esc: nothing selected, no anchor, the current row kept
    assert s.current == 12 and s.anchor is None and s.chosen(KEYS) == []
    assert s.step(KEYS, 1, shift=True) == 3
    assert s.chosen(KEYS) == [12, 13] and s.anchor == 12
    t = Selection()
    assert t.step(KEYS, -1, shift=True) == 0 and t.chosen(KEYS) == [10]  # nothing current at all


def test_keys_by_name_move_select_all_and_clear_and_say_which_row_to_show():
    s = Selection()
    assert s.press(KEYS, "down") == 0 and s.press(KEYS, "down", shift=True) == 1
    assert s.chosen(KEYS) == [10, 11]
    assert s.press(KEYS, "end") == 5 and s.chosen(KEYS) == [15]
    assert s.press(KEYS, "home", shift=True) == 0 and s.chosen(KEYS) == KEYS
    assert s.press(KEYS, "pagedown", page=4) == 4 and s.press(KEYS, "pageup", page=3) == 1
    assert s.press(KEYS, "pageup", page=0) == 0  # a page is a row at least
    assert s.press(KEYS, "up") == 0
    assert s.press(KEYS, "all") == -1 and s.chosen(KEYS) == KEYS
    assert s.press(KEYS, "clear") == -1 and s.chosen(KEYS) == []
    assert s.press(KEYS, "clear") == NOT_MINE  # nothing to clear: Esc goes on to the window
    assert s.press(KEYS, "") == NOT_MINE and s.press(KEYS, "space") == NOT_MINE
    t = Selection()
    assert t.press(KEYS, "end") == 5 and t.press([], "end") == -1


def test_the_selection_stays_with_its_keys_when_the_list_is_sorted_filtered_or_read_again():
    s = Selection()
    s.click(KEYS, 1)
    s.click(KEYS, 4, shift=True)
    s.click(KEYS, 2, ctrl=True)  # 12 out; anchor and current 12
    s.click(KEYS, 2, ctrl=True)  # and back
    resorted = list(reversed(KEYS))
    assert not s.keep(resorted)
    assert s.chosen(resorted) == [14, 13, 12, 11] and s.first(resorted) == 1
    filtered = [15, 13, 11, 10]  # a search leaves these: 12 and 14 leave the selection
    assert s.keep(filtered)
    assert s.chosen(filtered) == [13, 11] and s.anchor is None and s.current is None
    s.click(filtered, 1)
    assert not s.keep([13, 99]) and s.current == s.anchor == 13
    assert s.keep([]) and s.chosen([]) == [] and s.first([]) == -1


def test_select_all_selects_the_list_and_the_headers_checkbox_says_none_some_or_all():
    s = Selection()
    assert s.state(KEYS) == NONE and s.first(KEYS) == -1
    s.click(KEYS, 3)
    assert s.state(KEYS) == SOME and s.first(KEYS) == 3
    s.select_all(KEYS[:4])  # a search leaves four rows: those
    assert s.chosen(KEYS) == [10, 11, 12, 13] and s.state(KEYS[:4]) == ALL
    s.toggle_all(KEYS)  # some or all selected: none
    assert s.state(KEYS) == NONE
    s.toggle_all(KEYS)  # none: all
    assert s.state(KEYS) == ALL


def test_select_picks_exactly_those_in_the_list_with_no_current_row():
    s = Selection()
    s.click(KEYS, 0)
    s.select(KEYS, [12, 15, 99])
    assert s.chosen(KEYS) == [12, 15] and s.anchor is None and s.current is None


def test_the_selection_bars_count():
    assert selection_text(4) == "4 selected" and selection_text(1204) == "1,204 selected"
