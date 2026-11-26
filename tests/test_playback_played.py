"""When a song counts as played (src/musikata_core/audio/played.py; R7.9): 50 % of it, or 4
minutes, heard, on a clock and the places the device reports, with seeks, pauses and new plays.

Why: a count is kept for good, in every computer's sum (A2.8). A seek past the middle mustn't count
a song never listened to, a pause mustn't lose what was heard, and a song played again, by repeat
One or Previous, must count again."""

from fakes import FakeClock

from musikata_core.audio.played import MOST, SLACK, Listening, Play, mark

STEP = 0.25  # seconds between the device's reports, exact in binary


def heard(listening, clock, start, end, step=STEP):
    """The device plays from `start` to `end` seconds, reporting every `step` as the clock moves
    on: the plays counted on the way."""
    plays = []
    place = start
    while place < end:
        place = min(end, place + step)
        clock.advance(seconds=step)
        play = listening.moved(place)
        if play is not None:
            plays.append((place, play))
    return plays


def test_the_mark_is_half_the_song_and_never_more_than_4_minutes():
    assert mark(200.0) == 100.0
    assert mark(480.0) == MOST == 240.0
    assert mark(900.0) == 240.0
    assert mark(3.0) == 1.5
    assert mark(0.0) == mark(-1.0) == 240.0  # a length not known


def test_a_song_counts_once_half_of_it_is_heard_and_only_once():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(7, 200.0)
    plays = heard(listening, clock, 0.0, 200.0)
    assert [place for place, _ in plays] == [100.0]
    assert isinstance(plays[0][1], Play)
    assert plays[0][1].song == 7 and listening.counted


def test_the_time_counted_is_when_the_mark_was_reached():
    clock = FakeClock()
    start = clock.now()
    listening = Listening(clock)
    listening.begin(7, 20.0)
    ((_, play),) = heard(listening, clock, 0.0, 20.0)
    assert (play.when - start).total_seconds() == 10.0


def test_a_long_song_counts_at_4_minutes():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(3, 600.0)
    assert [place for place, _ in heard(listening, clock, 0.0, 600.0)] == [240.0]


def test_a_song_whose_length_isnt_known_counts_at_4_minutes():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(3, 0.0)
    assert [place for place, _ in heard(listening, clock, 0.0, 300.0)] == [240.0]


def test_a_seek_forward_past_the_mark_doesnt_count_it():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(1, 200.0)
    assert heard(listening, clock, 0.0, 10.0) == []
    listening.sought(150.0)
    assert heard(listening, clock, 150.0, 200.0) == []  # 60 s heard of the 100 asked
    assert listening.heard == 60.0 and not listening.counted


def test_what_a_seek_passes_over_is_not_heard_but_what_follows_it_is():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(1, 300.0)  # 150 s to hear
    heard(listening, clock, 0.0, 10.0)
    listening.sought(120.0)
    assert [place for place, _ in heard(listening, clock, 120.0, 300.0)] == [260.0]


def test_a_seek_back_hears_again_what_it_goes_back_over_and_that_counts():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(1, 100.0)
    heard(listening, clock, 0.0, 30.0)
    listening.sought(0.0)
    assert [place for place, _ in heard(listening, clock, 0.0, 30.0)] == [20.0]


def test_a_pause_adds_nothing_while_it_lasts_and_keeps_what_was_heard():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(1, 100.0)
    heard(listening, clock, 0.0, 30.0)
    for _ in range(10):  # paused for ten minutes: the place stays put
        clock.advance(minutes=1)
        assert listening.moved(30.0) is None
    assert listening.heard == 30.0
    assert [place for place, _ in heard(listening, clock, 30.0, 100.0)] == [50.0]


def test_a_jump_of_the_place_the_clock_didnt_allow_isnt_heard():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(1, 200.0)
    clock.advance(seconds=STEP)
    assert listening.moved(150.0) is None  # a seek nobody said: no more than the slack
    assert listening.heard == STEP + SLACK
    assert listening.moved(140.0) is None  # backwards: nothing heard
    assert listening.heard == STEP + SLACK


def test_reports_in_a_burst_after_a_stall_are_each_heard():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(1, 200.0)
    clock.advance(seconds=1)
    for i in range(1, 11):  # ten reports of a tenth of a second at once
        listening.moved(i / 10)
    assert round(listening.heard, 6) == 1.0


def test_a_new_play_of_the_same_song_counts_again_and_starts_from_nothing():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(5, 20.0)
    assert len(heard(listening, clock, 0.0, 20.0)) == 1
    listening.begin(5, 20.0)  # repeat One, a gapless join to itself
    assert listening.heard == 0.0 and not listening.counted
    assert len(heard(listening, clock, 0.0, 20.0)) == 1


def test_a_play_from_a_place_kept_counts_only_what_is_heard_from_there():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(5, 200.0, at=150.0)
    assert heard(listening, clock, 150.0, 200.0) == []


def test_a_song_stopped_before_the_mark_or_outside_the_library_isnt_counted():
    clock = FakeClock()
    listening = Listening(clock)
    listening.begin(5, 20.0)
    heard(listening, clock, 0.0, 5.0)
    listening.stop()
    assert heard(listening, clock, 5.0, 20.0) == []
    listening.begin(None, 20.0)  # a file played outside the library (R1.7)
    assert heard(listening, clock, 0.0, 20.0) == [] and listening.heard == 20.0
