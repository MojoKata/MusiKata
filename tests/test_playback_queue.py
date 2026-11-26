"""The queue (src/musikata_core/audio/queue.py; A4.2, R7.1 to R7.3): song ids with a cursor and a
shuffle order, played one after another, changed by Play next, Add to queue, Up next's drag and ×,
shuffled and repeated.

Why: the queue decides what plays next every time a song ends, and a shuffle that repeats a song
before all have played, a Play next that lands after the songs added before it, or a repeat that
stops at the end are each heard at once, and only by chance in the app."""

import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from musikata_core.audio import queue
from musikata_core.audio.queue import ALL, OFF, ONE, Queue


def songs(q):
    """The queue as song ids: played, the current one, to come."""
    return (
        [e.song for e in q.played],
        q.current.song if q.current else None,
        [e.song for e in q.upcoming],
    )


def seeded(seed=7):
    return Queue(random.Random(seed))


def test_playing_a_song_puts_the_rest_of_its_list_after_it():
    q = Queue()
    assert q.play([10, 11, 12, 13], start=1, source="Glass Harbor").song == 11
    assert songs(q) == ([], 11, [12, 13]) and q.source == "Glass Harbor" and len(q) == 3
    assert q.play([], source="nothing") is None and q.current is None and len(q) == 0


def test_play_on_an_album_plays_from_its_first_song():
    q = Queue()
    q.play([10, 11, 12])
    assert songs(q) == ([], 10, [11, 12])


def test_next_and_previous_move_through_the_queue_and_it_plays_out_at_its_end():
    q = Queue()
    q.play([1, 2, 3])
    assert q.previous().song == 1  # the first stays the first
    assert q.next().song == 2 and q.next().song == 3
    assert songs(q) == ([1, 2], 3, [])
    assert q.previous().song == 2 and q.next().song == 3
    assert q.next() is None and q.current is None and songs(q) == ([1, 2, 3], None, [])
    assert q.next() is None  # played out, it stays so
    assert q.previous().song == 3  # back to its last song


def test_an_empty_queue_has_nothing_next_previous_or_following():
    q = Queue()
    assert q.next() is None and q.previous() is None and q.ended() is None
    assert q.following() is None and q.played == [] and q.upcoming == []


def test_the_song_after_one_that_ended_starts_and_following_says_which_ahead():
    q = Queue()
    q.play([1, 2])
    assert q.following().song == 2 and q.current.song == 1  # asking doesn't move it
    assert q.ended().song == 2
    assert q.following() is None and q.ended() is None


def test_repeat_cycles_off_all_one_and_off():
    q = Queue()
    assert q.repeat == OFF
    assert [q.cycle_repeat() for _ in range(3)] == [ALL, ONE, OFF]
    q.set_repeat(ONE)
    assert q.repeat == ONE
    with pytest.raises(ValueError, match="no such repeat"):
        q.set_repeat("twice")


def test_repeat_all_plays_the_queue_again_from_its_start():
    q = Queue()
    q.play([1, 2])
    q.set_repeat(ALL)
    q.next()
    assert q.following().song == 1
    assert q.ended().song == 1 and songs(q) == ([], 1, [2])


def test_repeat_one_plays_the_song_again_when_it_ends_and_next_still_moves_on():
    q = Queue()
    q.play([1, 2])
    q.set_repeat(ONE)
    assert q.following().song == 1 and q.ended().song == 1
    assert q.next().song == 2
    assert q.next().song == 1  # past the end, round again


def test_play_next_goes_right_after_the_current_song_ahead_of_songs_added_before():
    q = Queue()
    q.play([1, 2, 3])
    q.add([20])
    q.play_next([30, 31])
    assert songs(q) == ([], 1, [30, 31, 20, 2, 3])
    assert [e.added for e in q.upcoming] == [True, True, True, False, False]


def test_add_to_queue_goes_after_the_songs_added_before_and_ahead_of_the_rest_of_the_list():
    q = Queue()
    q.play([1, 2, 3])
    q.add([20])
    q.add([21, 22])
    assert songs(q) == ([], 1, [20, 21, 22, 2, 3])
    q.next()  # 20 plays: the songs added after it are still ahead of the list
    q.add([23])
    assert songs(q) == ([1], 20, [21, 22, 23, 2, 3])
    assert q.add([]) == [] and q.play_next([]) == []


def test_songs_added_to_an_empty_or_played_out_queue_are_cued_there():
    q = Queue()
    q.add([5, 6])
    assert songs(q) == ([], 5, [6])
    q.next()
    q.next()
    assert q.current is None
    q.play_next([7])
    assert songs(q) == ([5, 6], 7, [])


def test_a_song_queued_twice_is_two_entries():
    q = Queue()
    q.play([1])
    a, b = q.add([1, 1])
    assert a.key != b.key and q.find(a.key) == a and q.find(-1) is None


def test_a_song_to_come_moves_where_it_is_dropped():
    q = Queue()
    q.play([1, 2, 3, 4])
    four = q.upcoming[-1]
    assert q.move(four.key, 0) and songs(q) == ([], 1, [4, 2, 3])
    assert q.move(four.key, 99) and songs(q) == ([], 1, [2, 3, 4])  # past the end: last
    assert not q.move(q.current.key, 1)  # the current song isn't to come
    assert not q.move(12345, 0)


def test_remove_takes_a_song_to_come_or_played_out_and_the_current_one_stays():
    q = Queue()
    q.play([1, 2, 3, 4])
    q.next()
    played, current, later = q.played[0], q.current, q.upcoming[0]
    assert q.remove(later.key) and songs(q) == ([1], 2, [4])
    assert q.remove(played.key) and songs(q) == ([], 2, [4])
    assert not q.remove(current.key) and not q.remove(12345)


def test_jump_makes_a_song_the_current_one_those_before_it_played():
    q = Queue()
    q.play([1, 2, 3, 4])
    q.jump(q.upcoming[1].key)
    assert songs(q) == ([1, 2], 3, [4])
    q.jump(q.played[0].key)
    assert songs(q) == ([], 1, [2, 3, 4])
    assert q.jump(12345).song == 1


def test_clear_empties_it_and_keeps_shuffle_and_repeat():
    q = Queue()
    q.play([1, 2], source="Songs")
    q.set_shuffle(True)
    q.set_repeat(ALL)
    q.clear()
    assert len(q) == 0 and q.current is None and q.source == ""
    assert q.shuffle and q.repeat == ALL


def test_a_seeded_shuffle_gives_the_same_order_every_time():
    a, b = seeded(3), seeded(3)
    for q in (a, b):
        q.play(list(range(20)))
        q.set_shuffle(True)
    assert songs(a) == songs(b)
    assert songs(a)[1] == 0 and songs(a)[2] != list(range(1, 20))  # the current song stays


def test_shuffle_keeps_the_songs_added_first_and_off_puts_the_rest_back_in_order():
    q = seeded()
    q.play(list(range(1, 11)))
    q.add([50])
    q.set_shuffle(True)
    q.set_shuffle(True)  # again: nothing changes
    assert q.shuffle and songs(q)[2][0] == 50
    assert sorted(songs(q)[2]) == [*range(2, 11), 50]
    q.next()  # 50
    q.next()  # a random one
    played = songs(q)[1]
    q.set_shuffle(False)
    assert songs(q)[2] == [n for n in range(2, 11) if n != played]


def test_shuffled_songs_added_go_where_shuffle_off_finds_them():
    q = seeded()
    q.play([1, 2, 3, 4])
    q.set_shuffle(True)
    q.play_next([9])
    q.set_shuffle(False)
    assert songs(q) == ([], 1, [9, 2, 3, 4])


def test_a_move_while_shuffling_leaves_the_order_shuffle_off_returns_to():
    q = seeded()
    q.play([1, 2, 3, 4, 5])
    q.set_shuffle(True)
    q.move(q.upcoming[-1].key, 0)
    q.set_shuffle(False)
    assert songs(q) == ([], 1, [2, 3, 4, 5])


def test_shuffled_play_of_a_list_starts_from_the_song_chosen_or_one_at_random():
    q = seeded()
    q.set_shuffle(True)
    q.play([1, 2, 3, 4, 5], start=2)
    assert songs(q)[1] == 3 and sorted(songs(q)[2]) == [4, 5]
    q.play([1, 2, 3, 4, 5])
    assert sorted([songs(q)[1], *songs(q)[2]]) == [1, 2, 3, 4, 5]


def test_a_shuffled_lap_with_repeat_all_never_starts_with_the_song_that_just_ended():
    for seed in range(30):
        q = seeded(seed)
        q.play([1, 2])
        q.set_shuffle(True)
        q.set_repeat(ALL)
        q.next()
        last = q.current.song
        assert q.following().song != last
        assert q.ended().song != last and len(q.upcoming) == 1


def test_songs_added_are_plain_songs_of_the_list_once_a_lap_comes_round():
    q = Queue()
    q.play([1])
    q.add([2])
    q.set_repeat(ALL)
    q.next()
    q.next()
    assert songs(q) == ([], 1, [2]) and not any(e.added for e in q.upcoming)


def test_a_lap_while_shuffling_keeps_the_order_shuffle_off_returns_to():
    q = seeded()
    q.play([1, 2, 3])
    q.set_shuffle(True)
    q.set_repeat(ALL)
    for _ in range(3):
        q.next()
    played = songs(q)[1]
    q.set_shuffle(False)
    assert songs(q)[2] == [n for n in (1, 2, 3) if n != played]
    q.add([4])  # the order shuffle off returns to still holds every entry
    assert q.remove(q.upcoming[-1].key)


@settings(max_examples=50, derandomize=True)
@given(st.integers(1, 30), st.integers(0, 2**32 - 1), st.integers(1, 3))
def test_shuffle_plays_every_song_once_before_any_plays_again(n, seed, laps):
    q = seeded(seed)
    q.set_shuffle(True)
    q.set_repeat(ALL)
    q.play(list(range(n)))
    heard = [q.current.song]
    for _ in range(n * laps - 1):
        heard.append(q.ended().song)
    for lap in range(laps):
        assert sorted(heard[lap * n : (lap + 1) * n]) == list(range(n))


def test_the_repeats_are_the_buttons_order():
    assert queue.REPEATS == ("off", "all", "one")


def test_the_song_after_the_next_is_what_the_queue_plays_then_without_moving():
    q = queue.Queue(random.Random(3))
    assert q.after_following() is None
    q.play([1, 2, 3])
    assert q.after_following().song == 3 and q.current.song == 1
    q.next()
    assert q.after_following() is None  # 3 is last
    q.set_repeat(queue.ALL)
    assert q.after_following().song == 1  # the next lap's first
    q.next()
    assert q.after_following().song == 2
    q.set_repeat(queue.ONE)
    assert q.after_following().song == 3
    q.set_repeat(queue.ALL)
    q.set_shuffle(True)
    lap = q._next_lap()
    assert q.after_following() == lap[1] and q.following() == lap[0]
    one = queue.Queue()
    one.play([9])
    one.set_repeat(queue.ALL)
    assert one.after_following().song == 9


# ---------- kept across restarts (R1.8, R7.2, R7.3) ----------


def test_a_queue_restored_is_cued_on_its_current_song_with_what_the_user_added():
    q = Queue()
    entry = q.restore([(10, False), (11, False), (20, True), (12, False)], [0, 1, 3, 2], 1, "GH")
    assert entry.song == 11 and songs(q) == ([10], 11, [20, 12]) and q.source == "GH"
    assert [e.added for e in q.order] == [False, False, True, False] and q.cursor == 1
    assert q.unshuffled == [0, 1, 2, 3]  # not shuffling: the order it plays in
    assert q.add([30])[0].song == 30 and songs(q)[2] == [20, 30, 12]  # after those added before


def test_a_shuffled_queue_restored_comes_back_in_its_order_and_shuffle_off_finds_the_one_before():
    q = seeded()
    q.set_shuffle(True)
    q.restore([(13, False), (11, False), (14, False), (10, False), (12, False)], [3, 1, 4, 0, 2], 1)
    assert songs(q) == ([13], 11, [14, 10, 12]) and q.unshuffled == [3, 1, 4, 0, 2]
    q.set_shuffle(False)
    assert songs(q) == ([13], 11, [10, 12, 14])  # the songs to come, in the order before


def test_a_kept_queue_saved_and_restored_is_the_same_queue():
    q = seeded(3)
    q.play([10, 11, 12, 13, 14], source="GH")
    q.set_shuffle(True)
    q.next()
    q.play_next([20])
    again = seeded(9)
    again.set_shuffle(True)
    again.restore([(e.song, e.added) for e in q.order], q.unshuffled, q.cursor, q.source)
    assert songs(again) == songs(q) and again.unshuffled == q.unshuffled
    assert [e.added for e in again.order] == [e.added for e in q.order]


def test_a_restored_queue_with_repeat_all_draws_its_next_lap_afresh():
    q = seeded(1)
    q.set_shuffle(True)
    q.set_repeat(ALL)
    q.restore([(12, False), (10, False), (11, False)], [2, 0, 1], 2)
    lap = q.following()
    assert lap is not None and lap.song in (10, 11)  # never the song that just ended
    assert q.next() == lap and len(q) == 3 and q.cursor == 0


@pytest.mark.parametrize("unshuffled", [[0, 0, 1], [0, 1], [1, 2, 3], [], [2, 1, 0, 3]], ids=str)
def test_restored_places_that_arent_one_each_leave_the_order_it_plays_in(unshuffled):
    q = seeded()
    q.set_shuffle(True)
    q.restore([(10, False), (11, False), (12, False)], unshuffled, 0)
    assert q.unshuffled == [0, 1, 2]
    q.set_shuffle(False)
    assert songs(q) == ([], 10, [11, 12])


@pytest.mark.parametrize("cursor, current", [(-4, 10), (0, 10), (2, 12), (3, None), (9, None)])
def test_a_restored_cursor_past_either_end_is_the_first_song_or_played_out(cursor, current):
    q = Queue()
    q.restore([(10, False), (11, False), (12, False)], [0, 1, 2], cursor)
    assert (q.current.song if q.current else None) == current
    assert Queue().restore([], [], 0) is None
