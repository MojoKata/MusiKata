"""Smart playlists (src/musikata_core/smart.py, the store's part in playlists.py; R8.9, A2.10):
the rule and its text, read in the shapes another version or a hand edit gives it (testing.md,
"Shapes"), its songs from the index, the decision to write its file again and the pace of it, and
the store making, editing and refilling one, refusing changes by hand.

Why: the rule is in a file other computers and other versions read and write. A misread rule
rewrites a user's playlist with the wrong songs; one rewritten at every play uploads a synced
root's file at every song; one rewritten when nothing changed does the same for nothing."""

import json
import os
import time
from datetime import UTC, datetime, timedelta

import jsonschema
import pytest
from fakes import FakeClock, fill, played
from hypothesis import example, given
from hypothesis import strategies as st

from musikata_core import db, playlists, scanner, smart
from musikata_core.playlists import PlaylistError, Store
from musikata_core.smart import BROKEN, NEWER, SMART, Rule
from musikata_core.tags import AudioInfo, Tags

SCHEMAS = os.path.join(os.path.dirname(smart.__file__), "schemas")
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
LD = "Lumen Drift"

# ---------- the rule's text (A2.10) ----------


def test_a_rule_is_written_as_one_line_of_json_with_its_conditions_limit_and_order():
    rule = Rule(rating=4, genre="Jazz", years=(1990, 1999), limit=50, order="rating")
    text = smart.format_rule(rule)
    assert "\n" not in text
    assert json.loads(text) == {"format": 1, "rating": 4, "genre": "Jazz", "years": [1990, 1999],
                                "limit": 50, "order": "rating"}  # fmt: skip
    assert smart.rule_line(rule) == "#MUSIKATA-RULE:" + text
    assert smart.read_rule(text) == smart.Reading(rule)
    assert smart.parse_rule(text) == rule and rule.conditions() == 3


def test_what_musikata_writes_is_held_to_the_rules_schema():
    with open(os.path.join(SCHEMAS, "smart-rule.v1.schema.json")) as f:
        schema = json.load(f)
    every = Rule(rating=5, genre="Jazz", artist=LD, years=(None, 1999), added=30, plays=3,
                 limit=10, order="played")  # fmt: skip
    for rule in (Rule(), every):
        jsonschema.validate(json.loads(smart.format_rule(rule)), schema)
    assert schema["properties"]["order"]["enum"] == list(smart.ORDERS)


texts = st.text(min_size=1).filter(lambda t: t.strip() != "")
rules = st.builds(
    Rule,
    rating=st.none() | st.integers(1, 5),
    genre=st.none() | texts,
    artist=st.none() | texts,
    years=st.none()
    | st.tuples(st.none() | st.integers(0, 3000), st.integers(0, 3000)).map(
        lambda y: (y[0], y[1]) if y[0] is None or y[0] <= y[1] else (y[1], y[0])
    ),
    added=st.none() | st.integers(1, 10_000),
    plays=st.none() | st.integers(1, 10_000),
    limit=st.none() | st.integers(1, 100_000),
    order=st.sampled_from(list(smart.ORDERS)),
    extra=st.dictionaries(
        st.text(min_size=1).filter(lambda k: k not in smart.KNOWN),
        st.none() | st.booleans() | st.integers() | st.text(),
        max_size=3,
    ).map(lambda d: tuple(sorted((k, json.dumps(v, ensure_ascii=False)) for k, v in d.items()))),
)


@given(rules)
@example(Rule(genre="Drum\nand\r\nBass\x00  ", artist=" é "))
def test_a_rule_written_then_read_gives_back_the_same_rule(rule):
    """A property: format then parse changes nothing, the fields it doesn't know included, and
    the line stays one line however its text runs."""
    line = smart.rule_line(rule)
    assert not any(c in line for c in "\r\n")
    assert smart.parse_rule(smart.format_rule(rule)) == rule
    header = playlists.parse(playlists.compose(playlists.Playlist(header=(line,)))).header
    assert smart.parse_rule(smart.rule_text_of(header) or "") == rule


@given(st.text(max_size=300))
@example("[" * 5000)
@example('{"rating": 1e999}')
@example('{"years": [NaN, 2000]}')
def test_any_text_at_all_reads_as_a_rule_or_none_without_raising(text):
    """A property: whatever follows #MUSIKATA-RULE:, a reading, never an error."""
    reading = smart.read_rule(text)
    assert reading.kind in (SMART, NEWER, BROKEN)
    assert (smart.parse_rule(text) is not None) == (reading.kind == SMART)


@pytest.mark.parametrize(
    ("text", "kind", "why"),
    [
        ("", BROKEN, "isn't one"),
        ("rating>=4", BROKEN, "isn't one"),
        ("[4]", BROKEN, "isn't one"),
        ('"rating"', BROKEN, "isn't one"),
        ('{"rating": 4', BROKEN, "isn't one"),
        ('{"rating": 0}', BROKEN, "rating"),
        ('{"rating": 6}', BROKEN, "rating"),
        ('{"rating": true}', BROKEN, "rating"),
        ('{"rating": 4.5}', BROKEN, "rating"),
        ('{"rating": "high"}', BROKEN, "rating"),
        ('{"genre": 17}', BROKEN, "genre"),
        ('{"artist": ["a"]}', BROKEN, "artist"),
        ('{"years": [1990]}', BROKEN, "years"),
        ('{"years": ["x", 1990]}', BROKEN, "years"),
        ('{"years": {"from": 1990}}', BROKEN, "years"),
        ('{"added": 0}', BROKEN, "days"),
        ('{"plays": -2}', BROKEN, "plays"),
        ('{"limit": 0}', BROKEN, "limit"),
        ('{"order": "shuffle"}', BROKEN, "order"),
        ('{"order": 3}', BROKEN, "order"),
        ('{"format": 2, "rating": 4, "match": "any"}', NEWER, "newer"),
        ('{"format": "2", "rating": "high"}', NEWER, "newer"),
    ],
)
def test_a_broken_or_newer_rule_says_why_and_is_not_kept_current(text, kind, why):
    """Shapes: text that isn't JSON, JSON that isn't an object, a field it knows holding a value
    it can't use (out of range, a bool, a fraction, text, another type), an order it doesn't
    know: broken, the playlist a plain list; a newer format: read for what it can, never written
    (A2.10)."""
    reading = smart.read_rule(text)
    assert (reading.kind, why in reading.why) == (kind, True)
    assert not reading.kept and smart.parse_rule(text) is None
    assert reading.smart == (kind == NEWER)


def test_a_newer_rule_is_read_for_what_it_can():
    reading = smart.read_rule('{"format": 2, "rating": 4, "genre": 3, "match": "any"}')
    assert reading.rule.rating == 4 and reading.rule.genre is None and reading.rule.format == 2
    assert reading.rule.extra == (("match", '"any"'),)


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("{}", Rule()),
        ('  {"rating": "4"}  ', Rule(rating=4)),
        ('{"rating": 4.0, "rating": 5}', Rule(rating=5)),  # named twice: the last
        ('{"format": "1", "plays": "+3", "limit": 25.0}', Rule(plays=3, limit=25)),
        ('{"format": true, "added": 30}', Rule(added=30)),  # an unreadable format: the first
        ('{"order": "Rating"}', Rule(order="rating")),
        ('{"order": " PLAYS "}', Rule(order="plays")),
        ('{"order": null, "limit": null, "genre": null}', Rule()),
        ('{"genre": "", "artist": "   "}', Rule()),  # empty: no condition
        ('{"years": [1999, 1990]}', Rule(years=(1990, 1999))),  # the other way round
        ('{"years": 1999}', Rule(years=(1999, 1999))),  # a year alone
        ('{"years": [null, "2000"]}', Rule(years=(None, 2000))),
        ('{"years": [null, null]}', Rule()),
        ('{"order": "year", "rating": 3, "genre": "Jazz"}',
         Rule(rating=3, genre="Jazz", order="year")),  # another order of fields
        ('﻿{"rating": 4}'[1:], Rule(rating=4)),
    ],
)  # fmt: skip
def test_a_rules_fields_are_read_in_the_shapes_they_come_in(text, rule):
    """Shapes: a number as text or as a whole fraction, a field named twice, `format` as text or
    a bool, the order in another case or with spaces, nulls and empty text for none, years
    reversed, alone or open at an end, fields in another order."""
    assert smart.read_rule(text) == smart.Reading(rule)


def test_fields_it_doesnt_know_are_kept_when_the_rule_is_written_again():
    rule = smart.parse_rule('{"rating": 4, "colour": "blue", "nested": {"a": [1, null]}}')
    assert rule is not None
    again = json.loads(smart.format_rule(Rule(rating=5, extra=rule.extra)))
    assert again["colour"] == "blue" and again["nested"] == {"a": [1, None]}
    assert again["rating"] == 5


def test_the_rule_line_is_found_in_any_case_and_put_in_place_of_the_one_there():
    header = ("#PLAYLIST:Best", "#musikata-rule: {}", '#MUSIKATA-RULE:{"rating": 2}')
    assert smart.rule_text_of(header) == "{}"
    assert smart.rule_text_of(("#PLAYLIST:x",)) is None
    rule = Rule(rating=4)
    assert smart.with_rule(header, rule) == ("#PLAYLIST:Best", smart.rule_line(rule))
    assert smart.with_rule(("#PLAYLIST:x",), rule) == (smart.rule_line(rule), "#PLAYLIST:x")
    assert smart.reading_of(None) is None and smart.reading_of("{}") == smart.Reading(Rule())


def test_a_new_smart_playlists_name_says_its_rule():
    """The mockups' "Four stars and up" (L01, P01)."""
    assert smart.suggested_name(Rule(rating=4)) == "Four stars and up"
    assert smart.suggested_name(Rule(rating=5)) == "Five stars"
    assert smart.suggested_name(Rule(rating=1, genre=" jazz ")) == "Jazz, One star and up"
    assert smart.suggested_name(Rule(artist=LD, years=(1990, 1999))) == "Lumen Drift, 1990–1999"
    assert smart.suggested_name(Rule(years=(2000, 2000), added=30, plays=5)) == (
        "2000, Added in 30 days, Played 5+"
    )
    assert smart.suggested_name(Rule(years=(None, 1980))) == "–1980"
    assert smart.suggested_name(Rule()) == "New smart playlist"


# ---------- its songs (R8.9) ----------

SONGS = [
    {"path": "A/01 Alpha.flac", "title": "Alpha", "artist": LD, "album": "Glass",
     "albumartist": LD, "track": 1, "rating": 5, "genres": ("Electronic",), "year": 2019},
    {"path": "A/02 Beta.flac", "title": "Beta", "artist": LD, "album": "Glass",
     "albumartist": LD, "track": 2, "rating": 4, "genres": ("Jazz",), "year": 2019},
    {"path": "B/01 Gamma.flac", "title": "Gamma", "artist": "Guest", "album": "Tide",
     "albumartist": "lumen drift", "track": 1, "rating": 4, "year": 1995},
    {"path": "C/01 Delta.flac", "title": "delta", "artist": "Other", "album": "Moss",
     "track": 1, "rating": 3, "genres": ("jazz", "Soul"), "year": 1990},
    {"path": "D/01 Eps.flac", "title": "Eps", "artist": "Other", "album": "Moss", "track": 2},
]  # fmt: skip
ALPHA, BETA, GAMMA, DELTA, EPS = (s["path"] for s in SONGS)


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, SONGS)
    days = {ALPHA: 1, BETA: 10, GAMMA: 40, DELTA: 400}

    def when(c):
        for path, d in days.items():
            c.execute("UPDATE song SET added = ? WHERE path = ?",
                      ((NOW - timedelta(days=d)).timestamp(), path))  # fmt: skip

    i.write(when).result()
    yield i
    i.close()


def picked(index, rule):
    return smart.songs(index.read(), rule, NOW.timestamp())


def test_each_condition_picks_its_songs_and_every_condition_must_hold(index):
    """R8.9's "any of": a rule of any of the conditions, each one there narrowing the list."""
    assert picked(index, Rule(rating=4)) == [ALPHA, BETA, GAMMA]
    assert picked(index, Rule(genre="jazz")) == [BETA, DELTA]  # case aside
    assert picked(index, Rule(artist="LUMEN DRIFT")) == [ALPHA, BETA, GAMMA]  # its albums too
    assert picked(index, Rule(years=(1990, 1995))) == [GAMMA, DELTA]
    assert picked(index, Rule(years=(None, 1994))) == [DELTA]
    assert picked(index, Rule(years=(2000, None))) == [ALPHA, BETA]
    assert picked(index, Rule(added=30)) == [ALPHA, BETA]
    assert picked(index, Rule(rating=4, genre="Jazz")) == [BETA]
    assert picked(index, Rule(rating=4, years=(1990, 2000), artist=LD)) == [GAMMA]
    assert picked(index, Rule(genre="Blues")) == []
    assert picked(index, Rule()) == [ALPHA, BETA, GAMMA, DELTA, EPS]


def test_plays_are_every_computers_added_up(index):
    played(index, {ALPHA: 2, DELTA: 1})
    played(index, {DELTA: 2}, computer="studio")
    assert picked(index, Rule(plays=3)) == [DELTA]
    assert picked(index, Rule(plays=2)) == [ALPHA, DELTA]
    assert smart.count(index.read(), Rule(plays=1), NOW.timestamp()) == 2


def test_the_order_and_the_limit_pick_the_first_songs_the_same_way_each_time(index):
    later = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
    played(index, {GAMMA: 3, BETA: 1})
    played(index, {BETA: 1}, when=later)
    assert picked(index, Rule(order="rating")) == [ALPHA, BETA, GAMMA, DELTA, EPS]
    assert picked(index, Rule(order="plays")) == [GAMMA, BETA, ALPHA, DELTA, EPS]
    assert picked(index, Rule(order="played")) == [BETA, GAMMA, ALPHA, DELTA, EPS]
    assert picked(index, Rule(order="added")) == [ALPHA, BETA, GAMMA, DELTA, EPS]
    assert picked(index, Rule(order="year")) == [ALPHA, BETA, GAMMA, DELTA, EPS]
    assert picked(index, Rule(order="title")) == [ALPHA, BETA, DELTA, EPS, GAMMA]
    assert picked(index, Rule(order="artist")) == [ALPHA, BETA, GAMMA, DELTA, EPS]
    assert picked(index, Rule(rating=3, order="year", limit=2)) == [ALPHA, BETA]
    assert smart.count(index.read(), Rule(rating=3, limit=2), NOW.timestamp()) == 4


def test_a_song_that_couldnt_be_read_is_never_picked(index):
    index.write(lambda c: c.execute("UPDATE song SET error = 'x' WHERE path = ?", (EPS,))).result()
    assert EPS not in picked(index, Rule())


@pytest.mark.slow
def test_fifty_thousand_songs_are_picked_in_well_under_a_second(tmp_path):
    """R1.11's 50,000 songs, a tenth of them rated, played and recent: each kind of rule's query
    timed; the times are in the log of the run."""
    index = db.Index(str(tmp_path / "big.db"))
    batch = []
    for n in range(50_000):
        tags = Tags(title=f"Song {n}", artist=f"Artist {n // 100}", album=f"Album {n // 10}",
                    albumartist=f"Artist {n // 100}", track=n % 10 + 1, year=1960 + n % 60,
                    rating=n % 6, genres=(f"Genre {n % 40}",))  # fmt: skip
        batch.append(scanner.Read(scanner.Seen(f"A{n // 10}/{n:05d}.flac", 10, n), tags,
                                  AudioInfo("flac", 200.0, 900_000, 44100, 2),
                                  f"{n:064x}"))  # fmt: skip
    for i in range(0, len(batch), 5000):
        index.write(lambda c, b=batch[i : i + 5000]: scanner.write_batch(c, b, {})).result()

    def plays(c):
        for n in range(0, 50_000, 10):
            c.execute("INSERT INTO play (computer, song_id, path, count, last) VALUES"
                      " ('me', ?, '', ?, '2026-11-25T12:00:00Z')", (n + 1, n % 7 + 1))  # fmt: skip
        c.execute("UPDATE song SET added = ? WHERE id % 10 = 0", (NOW.timestamp(),))

    index.write(plays).result()
    c = index.read()
    took = {}
    for name, rule in [
        ("rating >= 4, by rating", Rule(rating=4, order="rating")),
        ("genre, by artist", Rule(genre="genre 7")),
        ("artist", Rule(artist="Artist 42")),
        ("years, 100 by year", Rule(years=(1970, 1979), limit=100, order="year")),
        ("added in 30 days, newest", Rule(added=30, order="added")),
        ("played 3+, most played", Rule(plays=3, order="plays")),
        ("every song, by title", Rule(order="title")),
        ("all six, 50 last played", Rule(rating=1, genre="Genre 0", artist="Artist 0",
                                         years=(1960, 2020), added=30, plays=1, limit=50,
                                         order="played")),
    ]:  # fmt: skip
        start = time.perf_counter()
        found = smart.songs(c, rule, NOW.timestamp())
        matching = smart.count(c, rule, NOW.timestamp())
        took[name] = time.perf_counter() - start
        print(f"smart playlist on 50,000 songs, {name}: {took[name] * 1000:.0f} ms,"
              f" {len(found)} songs of {matching}")  # fmt: skip
    index.close()
    assert max(took.values()) < 1.0


# ---------- kept current (R8.9, A2.8) ----------


def test_its_file_is_written_only_when_its_songs_or_their_order_differ():
    assert not smart.changed(["a", "b"], ["a", "b"])
    assert smart.changed(["a", "b"], ["b", "a"])
    assert smart.changed(["a"], ["a", "b"]) and smart.changed(["a", None], ["a"])
    assert not smart.changed([], [])


def test_a_change_is_written_at_once_then_at_most_each_minute_and_plays_each_ten():
    """A2.8's pace: a root kept in sync isn't uploaded at every song played."""
    assert smart.wait_for(None, 5.0, smart.PLAYED) == 0.0
    assert smart.wait_for(100.0, 130.0, smart.LIBRARY) == smart.QUICK - 30
    assert smart.wait_for(100.0, 130.0, smart.PLAYED) == smart.SLOW - 30
    assert smart.wait_for(100.0, 130.0, smart.EDITED) == 0.0
    assert smart.wait_for(100.0, 100.0 + smart.SLOW, smart.PLAYED) == 0.0
    assert smart.QUICK == 60 and smart.SLOW == 600
    assert smart.quickest(smart.PLAYED, smart.LIBRARY) == smart.LIBRARY
    assert smart.quickest(None, smart.PLAYED) == smart.PLAYED
    assert smart.quickest(smart.EDITED, smart.LIBRARY) == smart.EDITED
    assert smart.quickest(None, None) is None


@pytest.fixture
def root(tmp_path, index):
    music = tmp_path / "Music"
    (music / "Playlists").mkdir(parents=True)
    for s in SONGS:
        (music / s["path"]).parent.mkdir(parents=True, exist_ok=True)
        (music / s["path"]).write_bytes(b"x")
    return str(music), index


def file_of(music, name):
    with open(os.path.join(music, "Playlists", name + ".m3u8"), encoding="utf-8") as f:
        return f.read()


def entries(index, playlist):
    sql = "SELECT path FROM playlist_entry WHERE playlist_id = ? ORDER BY position"
    return [p for (p,) in index.read().execute(sql, (playlist,))]


def test_a_smart_playlist_is_made_as_a_file_like_any_other_with_its_rule_line(root):
    """R8.9: kept as a playlist file like any other (R8.1's form), its rule in its comment
    line, which other players pass by."""
    music, index = root
    store = Store(music, index)
    rule = Rule(rating=4, order="rating")
    made = store.create_smart(rule, picked(index, rule), smart.suggested_name(rule))
    assert (made.name, made.count) == ("Four stars and up", 3)
    text = file_of(music, "Four stars and up")
    assert text.splitlines()[:2] == ["#EXTM3U", smart.rule_line(rule)]
    assert "#EXTINF:60,Lumen Drift - Alpha\n../A/01 Alpha.flac" in text
    assert entries(index, made.playlist) == [ALPHA, BETA, GAMMA]
    other = playlists.parse(text.encode())  # another player: the rule is a comment it skips
    assert [e.location for e in other.entries] == ["../A/01 Alpha.flac", "../A/02 Beta.flac",
                                                   "../B/01 Gamma.flac"]  # fmt: skip
    row = index.read().execute("SELECT rule FROM playlist WHERE id = ?", (made.playlist,))
    assert smart.parse_rule(row.fetchone()[0]) == rule


def test_a_smart_playlist_isnt_changed_by_hand_and_a_broken_one_is_a_plain_list(root):
    """R8.9: its view has no drag handles, nothing is dropped on it, Remove from playlist isn't
    offered: the store refuses each, saying why. A broken rule leaves a plain list."""
    music, index = root
    store = Store(music, index)
    made = store.create_smart(Rule(rating=4), [ALPHA, BETA], "Best")
    song = index.read().execute("SELECT id FROM song WHERE path = ?", (DELTA,)).fetchone()[0]
    first = index.read().execute("SELECT id FROM playlist_entry WHERE playlist_id = ?",
                                 (made.playlist,)).fetchone()[0]  # fmt: skip
    for change in (lambda: store.add(made.playlist, [song]),
                   lambda: store.remove(made.playlist, [first]),
                   lambda: store.move(made.playlist, [first], 2),
                   lambda: store.nudge(made.playlist, [first], 1),
                   lambda: store.fix(made.playlist, "x", song)):  # fmt: skip
        with pytest.raises(PlaylistError, match="Best is a smart playlist: its rule chooses"):
            change()
    path = os.path.join(music, "Playlists", "Broken.m3u8")
    with open(path, "w", encoding="utf-8") as f:
        f.write('#EXTM3U\n#MUSIKATA-RULE:{"rating": 9}\n../A/01 Alpha.flac\n')
    playlists.refresh(music, index, {"Playlists": [playlists.Found("Broken.m3u8", 1, 1)]},
                      lambda f: True)  # fmt: skip
    broken = index.read().execute("SELECT id FROM playlist WHERE name = 'Broken'").fetchone()[0]
    assert store.add(broken, [song]).count == 1
    assert '#MUSIKATA-RULE:{"rating": 9}' in file_of(music, "Broken")  # kept as it was


def test_edit_rule_writes_the_new_rule_and_its_songs_and_a_newer_rule_is_refused(root):
    music, index = root
    store = Store(music, index)
    with open(os.path.join(music, "Playlists", "Mix.m3u8"), "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n#PLAYLIST:Mix\n../C/01 Delta.flac\n")
    playlists.refresh(music, index, {"Playlists": [playlists.Found("Mix.m3u8", 1, 1)]},
                      lambda f: True)  # fmt: skip
    mix = index.read().execute("SELECT id FROM playlist WHERE name = 'Mix'").fetchone()[0]
    rule = Rule(genre="Jazz")
    done = store.set_rule(mix, rule, picked(index, rule))  # a plain one becomes smart
    assert done.count == 2 and entries(index, mix) == [BETA, DELTA]
    assert file_of(music, "Mix").splitlines()[1:3] == [smart.rule_line(rule), "#PLAYLIST:Mix"]
    store.set_rule(mix, Rule(rating=5), [ALPHA])
    assert file_of(music, "Mix").count("#MUSIKATA-RULE:") == 1 and entries(index, mix) == [ALPHA]
    with open(os.path.join(music, "Playlists", "Mix.m3u8"), "w", encoding="utf-8") as f:
        f.write('#EXTM3U\n#MUSIKATA-RULE:{"format": 2, "rating": 4}\n')
    with pytest.raises(PlaylistError, match="newer MusiKata"):
        store.set_rule(mix, Rule(rating=5), [ALPHA])


def test_refill_writes_only_when_its_songs_differ_and_its_file_still_holds_its_rule(root):
    music, index = root
    store = Store(music, index)
    rule = Rule(rating=4)
    made = store.create_smart(rule, [ALPHA, BETA], "Best")
    text = smart.format_rule(rule)
    path = os.path.join(music, "Playlists", "Best.m3u8")
    before = os.stat(path).st_mtime_ns
    assert not store.refill(made.playlist, text, [ALPHA, BETA])  # nothing changed: not written
    assert os.stat(path).st_mtime_ns == before
    assert store.refill(made.playlist, text, [BETA, ALPHA, GAMMA])
    assert entries(index, made.playlist) == [BETA, ALPHA, GAMMA]
    assert not store.refill(made.playlist, smart.format_rule(Rule(rating=5)), [ALPHA])
    assert entries(index, made.playlist) == [BETA, ALPHA, GAMMA]  # its rule changed since


class Refills:
    """A store that records what it is asked to write; `fail` makes it raise."""

    def __init__(self, store=None, fail=False):
        self.store, self.fail, self.asked = store, fail, []

    def refill(self, playlist, text, paths):
        self.asked.append((playlist, list(paths)))
        if self.fail:
            raise PlaylistError("Best couldn't be written: read-only")
        return self.store.refill(playlist, text, paths) if self.store else True


def test_the_keeper_writes_a_change_at_once_then_waits_its_pace(root):
    """R8.9's "rewritten whenever its songs change", at A2.8's pace: a change the library made
    waits out a minute from the last write, one plays alone made ten; nothing changed, nothing
    written; a rule edited goes at once."""
    music, index = root
    store = Store(music, index)
    clock = FakeClock(NOW)
    made = store.create_smart(Rule(rating=4), [ALPHA], "Best")
    keeper = smart.Keeper(Refills(store), index.read, clock)
    assert [p for p, _t, _r in keeper.smart()] == [made.playlist]
    out = keeper.check(smart.LIBRARY)
    assert out.written == [made.playlist] and out.due is None
    assert entries(index, made.playlist) == [ALPHA, BETA, GAMMA]
    assert keeper.check(smart.PLAYED).written == []  # nothing changed

    def rate(stars):
        index.write(lambda c: c.execute("UPDATE song SET rating = ? WHERE path = ?",
                                        (stars, DELTA))).result()  # fmt: skip

    rate(4)
    clock.advance(seconds=10)
    out = keeper.check(smart.PLAYED)
    assert out.written == [] and out.due == smart.SLOW - 10
    out = keeper.check(smart.LIBRARY)  # the library's change is waited on a minute, not ten
    assert out.written == [] and out.due == smart.QUICK - 10
    clock.advance(seconds=50)
    out = keeper.check(smart.PLAYED)  # the waiting cause carried: the library's
    assert out.written == [made.playlist] and DELTA in entries(index, made.playlist)
    rate(1)
    clock.advance(seconds=5)
    assert keeper.check(smart.EDITED).written == [made.playlist]
    keeper.forget([made.playlist])
    assert keeper.check(smart.PLAYED).written == []


def test_a_smart_playlist_that_cant_be_written_is_logged_and_tried_after_its_pace(root, caplog):
    music, index = root
    store = Store(music, index)
    clock = FakeClock(NOW)
    made = store.create_smart(Rule(rating=4), [ALPHA], "Best")
    store.create_smart(Rule(rating=9), [], "Odd")  # never kept: refused at once (no row change)
    refills = Refills(fail=True)
    keeper = smart.Keeper(refills, index.read, clock)
    assert keeper.check().written == []
    assert "couldn't be kept current" in caplog.text
    assert keeper.check().due == smart.QUICK and len(refills.asked) == 1
    assert keeper.check(only=made.playlist + 99).written == []
    assert keeper.file_songs(made.playlist) == [ALPHA]
