"""The same song more than once (src/musikata_core/duplicates.py; R2.12, A2.6): the key likely
copies share, the groups of exact and likely copies, the copy proposed to keep and why, the choice
of the copies checked, the plan of what moving the others to the trash gives the kept one, the
groups found through the index's indexes, and the plays moved into the kept copy and back
(rootfiles.take_plays, give_plays, take_back).

Why: a copy moved to the trash is a file the user loses from the library, so the copy kept must be
the best by R2.12's rule, and only exact copies may come checked; the kept copy must take the
plays and rating the others had, which Undo must be able to give back; and the group must be
found at 50,000 songs without a pass over every row (A2.6)."""

import time
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core import attention, db, duplicates, rootfiles, scanner
from musikata_core.duplicates import Copy, Group
from musikata_core.patterns import BARE, FIX, MATCH
from musikata_core.tags import AudioInfo, Tags

H1, H2, H3 = "1" * 64, "2" * 64, "3" * 64
WHEN = datetime(2026, 11, 25, 20, 41, tzinfo=UTC)
PLAYED = "2026-11-25T20:41:00Z"


def copy(song, path, **kw):
    kw.setdefault("key", duplicates.song_key(kw.get("artist", "Lumen Drift"),
                                             kw.get("title", "Signal Fires")))  # fmt: skip
    kw.setdefault("artist", "Lumen Drift")
    kw.setdefault("title", "Signal Fires")
    kw.setdefault("length", 258.0)
    return Copy(song, path, **kw)


# ---------- the key (A2.6) ----------


def test_likely_copies_share_a_key_with_case_accents_and_punctuation_set_aside():
    """A2.6: "the same artist and title once case, accents and punctuation are set aside"."""
    key = duplicates.song_key("Lumen Drift", "Signal Fires")
    for artist, title in (
        ("lumen drift", "SIGNAL FIRES"),
        ("Lumen-Drift", "Signal Fires!"),
        (" Lumen  Drift ", "signal_fires"),
        ("LUMEN DRIFT", "Signal, Fires."),
    ):
        assert duplicates.song_key(artist, title) == key  # fmt: skip
    assert duplicates.song_key("Beyoncé", "Déjà Vu") == duplicates.song_key("BEYONCE", "deja vu")
    assert duplicates.song_key("Straße", "x") == duplicates.song_key("STRASSE", "X")
    assert duplicates.song_key("Шансон", "Ночь") == duplicates.song_key("шансон", "НОЧЬ")
    assert duplicates.song_key("Lumen Drift", "Signal Fires (Live)") != key
    assert duplicates.song_key("Mara Okafor", "Signal Fires") != key
    # a song without an artist or a title can't be said to be another (none of marks alone)
    assert duplicates.song_key(None, "Signal Fires") is None
    assert duplicates.song_key("Lumen Drift", "  ") is None
    assert duplicates.song_key("Lumen Drift", "?!") is None


@given(st.text(max_size=30), st.text(max_size=30))
def test_any_artist_and_title_have_one_key_whatever_their_case(artist, title):
    key = duplicates.song_key(artist, title)
    assert (
        key is None
        or key == duplicates.song_key(artist.upper(), title.upper())
        or (key == duplicates.song_key(artist.lower(), title.lower()))
    )
    assert key is None or key.count("\0") == 1


# ---------- the groups ----------


def test_exact_copies_share_a_hash_and_likely_ones_a_key_within_two_seconds():
    """R2.12: exact copies by their hash, likely ones by artist and title with lengths within 2
    seconds; each a group with its copy to keep first."""
    songs = [
        copy(1, "LD/GH/04 - Signal Fires.flac", kind="flac", hash=H1),
        copy(2, "_Incoming/Signal Fires.flac", kind="flac", hash=H1, title="Other"),
        copy(3, "LD/TT/04 - Moonpull.flac", kind="flac", hash=H2, title="Moonpull",
             length=284.0),
        copy(4, "_Incoming/Moonpull (radio).m4a", kind="aac", hash=H3, title="moonpull",
             length=285.9),
        copy(5, "Live/Moonpull.flac", kind="flac", hash="4" * 64, title="Moonpull", length=290.0),
        copy(6, "Alone.flac", hash="5" * 64, title="Alone"),
    ]  # fmt: skip
    got = duplicates.group(songs)
    assert [[c.song for c in g.copies] for g in got] == [[3, 4], [1, 2]]  # by the kept's title
    assert [g.likely for g in got] == [True, False]
    assert got[1].kept.path == "LD/GH/04 - Signal Fires.flac"


def test_lengths_are_within_two_seconds_of_the_shortest_of_their_run():
    songs = [copy(i, f"{i}.mp3", hash=str(i) * 64, length=n)
             for i, n in ((1, 100.0), (2, 101.5), (3, 102.0), (4, 102.5), (5, 104.4))]  # fmt: skip
    got = duplicates.group(songs)
    assert sorted(sorted(c.song for c in g.copies) for g in got) == [[1, 2, 3], [4, 5]]
    # a song whose length isn't known is never a likely copy
    assert duplicates.group([copy(1, "a.mp3", hash=H1, length=None),
                             copy(2, "b.mp3", hash=H2, length=None)]) == []  # fmt: skip


def test_a_song_linked_both_ways_is_in_one_group_and_its_kind_is_likely():
    """An exact pair and a likely third: one group, a song in one group at most."""
    songs = [copy(1, "a.flac", kind="flac", hash=H1), copy(2, "b.flac", kind="flac", hash=H1),
             copy(3, "c.mp3", kind="mp3", hash=H2, length=259.0)]  # fmt: skip
    (g,) = duplicates.group(songs)
    assert {c.song for c in g.copies} == {1, 2, 3} and g.likely
    assert duplicates.group([copy(1, "a", hash=None, key=None), copy(2, "b", hash=None,
                                                                      key=None)]) == []  # fmt: skip


# ---------- the copy to keep ----------


def test_the_copy_kept_is_lossless_then_the_higher_bit_rate_then_the_path_that_matches():
    """R2.12's rule, in its order, each saying why it won."""
    flac = copy(1, "_Incoming/x.flac", kind="flac", bitrate=900_000, hash=H1)
    mp3 = copy(2, "Lumen Drift/Glass Harbor/04 - Signal Fires.mp3", kind="mp3", bitrate=320_000,
               hash=H2)  # fmt: skip
    assert duplicates.keep([mp3, flac]) == (flac, duplicates.LOSSLESS_WINS)
    low = copy(3, "Lumen Drift/Glass Harbor/04 - Signal Fires.m4a", kind="aac",
               bitrate=256_000, hash=H3)  # fmt: skip
    assert duplicates.keep([low, mp3]) == (mp3, duplicates.BITRATE_WINS)
    filed = copy(4, "Lumen Drift/Glass Harbor/04 - Signal Fires.mp3", kind="mp3",
                 bitrate=320_000, hash=H1, album="Glass Harbor", path_state=MATCH)  # fmt: skip
    loose = copy(5, "_Incoming/new rips/track01.mp3", kind="mp3", bitrate=320_000, hash=H2,
                 album="Glass Harbor", plays=50, path_state=FIX)  # fmt: skip
    assert duplicates.keep([loose, filed]) == (filed, duplicates.PATH_WINS)
    played = copy(6, "b.mp3", kind="mp3", hash=H1, plays=3, title="t")
    rated = copy(7, "a.mp3", kind="mp3", hash=H1, plays=3, rating=4, title="t")
    assert duplicates.keep([copy(8, "c.mp3", kind="mp3", hash=H1, title="t"), played]) == (
        played, duplicates.PLAYS_WINS
    )  # fmt: skip
    assert duplicates.keep([played, rated]) == (rated, duplicates.RATING_WINS)
    same = [copy(9, "b.mp3", hash=H1), copy(10, "a.mp3", hash=H1)]
    assert duplicates.keep(same)[0].song == 10 and duplicates.keep(same)[1] == duplicates.FIRST
    assert duplicates.keep(same[:1]) == (same[0], duplicates.FIRST)
    with pytest.raises(ValueError, match="no copies"):
        duplicates.keep([])


def test_exact_copies_bit_rates_are_one_and_r3_9s_seam_takes_another_rule():
    """Copies of one audio differ in bit rate only by their tags' size: the path decides; and the
    path rule is a parameter."""
    big_tags = copy(1, "_Incoming/x.flac", kind="flac", bitrate=905_000, hash=H1)
    filed = copy(2, "Lumen Drift/Glass Harbor/04 - Signal Fires.flac", kind="flac",
                 bitrate=900_000, hash=H1, album="Glass Harbor", path_state=MATCH)  # fmt: skip
    assert duplicates.keep([big_tags, filed]) == (filed, duplicates.PATH_WINS)
    assert duplicates.keep([big_tags, filed], lambda c: -c.song)[0] is big_tags


def test_the_path_matches_when_r3_9s_state_says_its_tags_agree_with_it():
    """R3.9's rule through the seam: a copy whose tags match its path counts; one that can be
    fixed, has no tags, or no pattern fits, doesn't."""
    assert duplicates.path_matches(copy(1, "a.flac", path_state=MATCH)) == 1
    for state in (FIX, BARE, None):
        assert duplicates.path_matches(copy(1, "a.flac", path_state=state)) == 0


# ---------- the choice and the plan ----------


def test_exact_copies_come_checked_and_likely_ones_unchecked():
    g = Group((copy(1, "a.flac", hash=H1), copy(2, "b.flac", hash=H1), copy(3, "c.m4a", hash=H2)),
              True)  # fmt: skip
    assert duplicates.initial(g) == (1, frozenset({2}))
    # keeping the likely copy: the one kept before isn't its exact copy, so stays unchecked
    assert duplicates.rechoose(g, 1, {2}, 3) == (3, frozenset({2}))
    # keeping its exact copy: the one kept before is checked
    assert duplicates.rechoose(g, 1, {2}, 2) == (2, frozenset({1}))
    assert duplicates.rechoose(g, 1, {2}, 9) == (1, frozenset({2}))  # not of the group
    assert duplicates.rechoose(g, 1, {2}, 1) == (1, frozenset({2}))


def test_the_plan_moves_the_checked_and_gives_the_kept_their_plays_and_highest_rating():
    """R2.12: the kept copy takes the removed ones' plays and their highest rating."""
    g = Group((copy(1, "a.flac", plays=52, rating=3), copy(2, "b.mp3", plays=3, rating=4),
               copy(3, "c.m4a", plays=6, rating=5)), True)  # fmt: skip
    p = duplicates.plan(g, 1, {2, 1})
    assert [c.song for c in p.gone] == [2] and p.kept.song == 1
    assert (p.stars, p.plays) == (4, 55)
    p = duplicates.plan(g, 2, {1, 3})
    assert ([c.song for c in p.gone], p.stars, p.plays) == ([1, 3], 5, 61)
    # its own rating higher: it keeps it
    assert duplicates.plan(g, 3, {1, 2}).stars is None
    assert duplicates.plan(g, 1, set()) == duplicates.Plan(g.copies[0], (), None, 52)
    with pytest.raises(ValueError, match="isn't a copy"):
        duplicates.plan(g, 9, {1})


# ---------- in the index ----------


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def put(index, songs):
    """Rows as a scan writes them: each (path, tags, kind, bit rate, length, audio hash)."""
    batch = [
        scanner.Read(scanner.Seen(path, 10, 2_000_000_000 + n), tags,
                     AudioInfo(kind, length, bitrate, 44100, 2), digest)
        for n, (path, tags, kind, bitrate, length, digest) in enumerate(songs)
    ]  # fmt: skip
    index.write(lambda c: scanner.write_batch(c, batch, {})).result()


def ids(index):
    return dict(index.read().execute("SELECT path, id FROM song"))


LD = "Lumen Drift"
SIGNAL = "Lumen Drift/Glass Harbor/04 - Signal Fires.flac"
RIP = "_Incoming/new rips/Signal Fires.flac"
MOON = "Lumen Drift/Tide Tables/04 - Moonpull.flac"
RADIO = "_Incoming/From Phone/Moonpull (radio).m4a"
SONGS = [
    (SIGNAL, Tags(title="Signal Fires", artist=LD, album="Glass Harbor", albumartist=LD, track=4,
                  rating=5), "flac", 900_000, 258.0, H1),
    (RIP, Tags(title="Signal Fires", artist=LD, rating=4), "flac", 905_000, 258.0, H1),
    (MOON, Tags(title="Moonpull", artist=LD, album="Tide Tables", rating=4), "flac", 850_000,
     284.0, H2),
    (RADIO, Tags(title="Moonpull!", artist="lumen drift"), "aac", 256_000, 285.0, H3),
    ("Lumen Drift/Tide Tables/05 - Ebb.flac", Tags(title="Ebb", artist=LD, album="Tide Tables"),
     "flac", 850_000, 200.0, "4" * 64),
]  # fmt: skip


def test_the_groups_are_found_through_the_indexes_with_their_plays_and_ratings(index):
    """A2.6: the scan keeps each song's key; the groups come from the songs whose hash or key
    another has, each copy with its format, bit rate, folder, plays and rating (R2.12)."""
    put(index, SONGS)
    song = ids(index)
    plays = {
        SIGNAL: 52,
        RIP: 3,
    }

    def play(c):
        for path, n in plays.items():
            for _ in range(n):
                rootfiles.count(c, "me", song[path], WHEN)
        rootfiles.count(c, "another", song[SIGNAL], WHEN)

    index.write(play).result()
    c = index.read()
    assert c.execute(
        "SELECT copy_key FROM song WHERE path LIKE '%Moonpull (radio)%'"
    ).fetchone() == (duplicates.song_key(LD, "Moonpull"),)
    assert sorted(duplicates.candidates(c)) == sorted(song[p] for p, *_ in SONGS[:4])
    moon, signal = duplicates.found(c)
    assert [x.path for x in signal.copies] == [
        SIGNAL,
        RIP,
    ]
    # R3.9: the kept copy's tags match its path; no pattern fits the rip's
    assert not signal.likely and signal.why == duplicates.PATH_WINS
    kept = signal.kept
    assert (kept.path_state, signal.copies[1].path_state) == (MATCH, None)
    assert (kept.kind, kept.bitrate, kept.plays, kept.rating, kept.album) == (
        "flac", 900_000, 53, 5, "Glass Harbor"
    )  # fmt: skip
    assert kept.modified == 2.0 and kept.album_id is not None
    assert moon.likely and moon.why == duplicates.LOSSLESS_WINS
    assert [x.kind for x in moon.copies] == ["flac", "aac"]
    for query in (
        "SELECT audio_hash FROM song WHERE audio_hash IS NOT NULL GROUP BY audio_hash",
        "SELECT copy_key FROM song WHERE copy_key IS NOT NULL GROUP BY copy_key",
    ):
        plan = " ".join(str(r) for r in c.execute(f"EXPLAIN QUERY PLAN {query}"))
        assert "COVERING INDEX" in plan  # fmt: skip


def test_a_group_is_a_needs_attention_entry_about_its_first_copy(index):
    """R2.8's "The same song more than once" group: an entry a group, Ignore keeping its first
    copy by path, until a copy changes."""
    put(index, SONGS)
    got = [e for e in attention.find(index.read()) if e.kind == attention.COPIES]
    assert [(e.about, e.title, e.likely) for e in got] == [
        (MOON, "Moonpull", True),
        (SIGNAL, "Signal Fires", False),
    ]
    signal = got[1]
    assert (signal.hash, signal.artist) == (H1, LD) and signal.modified == pytest.approx(
        2.0, abs=1e-6
    )
    assert len(signal.copies) == 2 and signal.why == duplicates.PATH_WINS
    d = attention.dismissal_of(signal, "2026-11-26T21:00:00Z")
    assert (d.kind, d.about, d.hash, d.modified) == ("same-song", signal.about, H1, signal.modified)
    left = attention.find(index.read(), [d])
    assert [e.about for e in left if e.kind == attention.COPIES] == [MOON]
    # a song with no modification time known still makes an entry
    assert attention.copies_entry(Group((copy(1, "b"), copy(2, "a")), True)).modified is None


@pytest.mark.slow
def test_fifty_thousand_songs_are_grouped_in_well_under_a_second_or_two(index):
    """A2.6 at R1.11's 50,000 songs: 2,000 exact pairs and 2,000 likely ones among them, found
    through the indexes; the time is in the log of the run."""
    batch = []
    for n in range(50_000):
        artist, title, digest = f"Artist {n // 10}", f"Song {n}", f"{n:064x}"
        if n < 4000:  # an exact copy of song n - 1 (n odd), or a likely one (n % 4 == 2)
            title = f"Song {n - n % 2}"
            digest = f"{n - n % 2:064x}" if n % 4 < 2 else digest
        tags = Tags(title=title, artist=artist, album=f"Album {n // 10}")
        batch.append(scanner.Read(scanner.Seen(f"A{n // 10}/{n:05d}.flac", 10, n),
                                  tags, AudioInfo("flac", 200.0 + n % 2, 900_000, 44100, 2),
                                  digest))  # fmt: skip
    for i in range(0, len(batch), 5000):
        index.write(lambda c, b=batch[i : i + 5000]: scanner.write_batch(c, b, {})).result()
    c = index.read()
    start = time.perf_counter()
    got = duplicates.found(c)
    took = time.perf_counter() - start
    print(f"duplicates.found on 50,000 songs: {took * 1000:.0f} ms, {len(got)} groups")
    assert len(got) == 2000 and sum(g.likely for g in got) == 1000
    assert took < 5.0


# ---------- the plays moved (R2.12, A2.8) ----------


def test_the_kept_copy_takes_this_computers_plays_and_undo_gives_them_back(index):
    """R2.12's plays moved into the kept copy on this computer's rows, summed, the latest time
    kept; Undo gives them back where each copy was (rootfiles.give_plays), and redo takes them
    again (take_back). Another computer's rows are its own file's: left as they are."""
    put(index, SONGS)
    song = ids(index)
    kept, likely = (
        song[MOON],
        song[RADIO],
    )
    later = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

    def play(c):
        for _ in range(18):
            rootfiles.count(c, "me", kept, WHEN)
        for _ in range(6):
            rootfiles.count(c, "me", likely, later)
        rootfiles.count(c, "another", likely, WHEN)

    index.write(play).result()
    taken = index.write(lambda c: rootfiles.take_plays(
        c, "me", kept, [likely], [RADIO])).result()  # fmt: skip
    assert taken == [rootfiles.Entry(RADIO, H3, 6,
                                     "2026-11-26T09:00:00Z")]  # fmt: skip
    c = index.read()
    assert rootfiles.totals(c, [kept, likely]) == {kept: 24, likely: 1}
    assert rootfiles.own(c, "me") == [rootfiles.Entry(MOON, H2, 24,
                                                      "2026-11-26T09:00:00Z")]  # fmt: skip
    # the copy goes (to the trash): its row taken out of the index, this computer's plays kept
    index.write(lambda c: c.execute("DELETE FROM song WHERE id = ?", (likely,))).result()
    back = index.write(lambda c: rootfiles.give_plays(c, "me", kept, taken)).result()
    assert back == taken
    c = index.read()
    assert rootfiles.totals(c, [kept]) == {kept: 18}
    assert [(e.path, e.count) for e in rootfiles.own(c, "me")] == [
        (MOON, 18), (RADIO, 6)
    ]  # fmt: skip
    again = index.write(lambda c: rootfiles.take_back(c, "me", kept, back)).result()
    assert again == taken and rootfiles.totals(index.read(), [kept]) == {kept: 24}

    # rows enough in the first: the next isn't touched
    def two(c):
        for _ in range(2):
            c.execute("INSERT INTO play (computer, song_id, path, hash, count, last)"
                      " VALUES ('me', NULL, 'x.mp3', NULL, 3, ?)", (PLAYED,))  # fmt: skip

    index.write(two).result()
    some = [rootfiles.Entry("x.mp3", None, 2, PLAYED)]
    assert index.write(lambda c: rootfiles.take_back(c, "me", kept, some)).result() == some
    assert [n for (n,) in index.read().execute("SELECT count FROM play WHERE path = 'x.mp3'")] == [
        1, 3
    ]  # fmt: skip
    # nothing left to take or give: nothing moves
    assert index.write(lambda c: rootfiles.take_back(c, "me", kept, back)).result() == []
    assert index.write(lambda c: rootfiles.give_plays(c, "nobody", kept, taken)).result() == []
    assert index.write(lambda c: rootfiles.take_plays(c, "me", kept, [], [])).result() == []


def test_an_exact_copys_plays_follow_its_twin_and_rows_a_scan_left_are_found_by_path(index):
    """A2.8: plays of a copy gone stand for its exact copy; R2.12 moves those the scan left
    standing for no song by their path, and a kept copy with no row of its own gets one."""
    put(index, SONGS)
    song = ids(index)
    kept, twin = (
        song[SIGNAL],
        song[RIP],
    )
    moon, likely = (
        song[MOON],
        song[RADIO],
    )

    def play(c):
        for _ in range(3):
            rootfiles.count(c, "me", likely, WHEN)
        rootfiles.count(c, "me", twin, WHEN)

    index.write(play).result()
    # the copy's row taken out first (a scan saw it go): its plays stand for no song
    index.write(lambda c: c.execute("DELETE FROM song WHERE id = ?", (likely,))).result()
    taken = index.write(lambda c: rootfiles.take_plays(
        c, "me", moon, [likely], [RADIO])).result()  # fmt: skip
    assert [e.count for e in taken] == [3]
    assert rootfiles.totals(index.read(), [moon]) == {moon: 3}
    # an exact copy's plays given back stand for its twin at once (A2.8)
    index.write(lambda c: rootfiles.take_plays(c, "me", kept, [twin], [])).result()
    index.write(lambda c: c.execute("DELETE FROM song WHERE id = ?", (twin,))).result()
    back = index.write(lambda c: rootfiles.give_plays(c, "me", kept, [rootfiles.Entry(
        RIP, H1, 1, "2026-11-25T20:41:00Z")])).result()  # fmt: skip
    assert [e.count for e in back] == [1]
    assert rootfiles.totals(index.read(), [kept]) == {kept: 1}


def test_this_computers_rows_are_changed_through_its_keeping_and_its_file_written(tmp_path):
    """Keeping.change: R2.12's plays moved on the keeping's thread, with this computer's key, its
    file written when due."""
    from fakes import FakeClock

    index = db.Index(str(tmp_path / "musikata.db"))
    musikata = tmp_path / "Music" / ".musikata"
    musikata.mkdir(parents=True)
    try:
        put(index, SONGS)
        song = ids(index)
        keeping = rootfiles.Keeping(index, str(musikata), FakeClock(WHEN), "me")
        told = []
        keeping.on_change = lambda: told.append(1)
        keeping.start(others=False).result()
        kept = song[MOON]
        done = keeping.change(lambda c, me: rootfiles.count(c, me, kept, WHEN)).result()
        assert done is True and told
        assert rootfiles.read(rootfiles.file_of(str(musikata), "me")).entries[0].count == 1
        keeping.close()
    finally:
        index.close()
