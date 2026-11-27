"""Ratings in the running app (src/musikata/ratings.py, Stars.qml and the rows, the bar and the
keys that use it; R10.1, R10.2, R10.3): a star clicked or a key pressed sets a rating, or clears
it, as one save kept in the change history, shown at once and put back, saying why, when it
fails; the root's ratings.json read at start and again when another computer changes it.

The songs are generated WAVs (whose ratings ratings.json keeps, R10.4) with an index that has
them; tests wait on the signal or state that says the work is done.

Why: a rating clicked is the quickest change a user makes to their library, often to many songs
at once; one that shows but isn't kept, one kept but not shown, or one undone into the wrong place
costs them their ratings or their trust."""

import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fakes import FakeClock, wav
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, layout, tour
from musikata.history import ChangeHistory
from musikata.models import SongsModel, average_of
from musikata.ratings import (
    NONE_SELECTED,
    NOT_THERE,
    Ratings,
    description_of,
    file_writer,
    new_rating,
    rated_text,
)
from musikata_core import db, ratings, scanner, settings, tags
from musikata_core.clock import SystemClock
from musikata_core.tags import Failed, Job, Outcome, Tags, Written

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
NOW = datetime(2026, 11, 26, 21, 0, tzinfo=UTC)


# ---------- what a click does and what the message says ----------


def test_a_star_sets_its_rating_and_the_star_shown_clears_it():
    """R10.2: clicking a star sets it; clicking the current star again clears it."""
    assert [new_rating(4, shown) for shown in (0, 3, 4, 5)] == [4, 4, 0, 4]
    assert new_rating(1, 1) == 0


def test_a_ratings_save_is_named_by_its_stars_and_songs():
    assert description_of(4, 3) == "4 stars on 3 songs"
    assert description_of(1, 1) == "1 star on 1 song"
    assert description_of(0, 2) == "Rating cleared on 2 songs"


def written(path, stars):
    return Written(path, Tags(rating=stars), tags.AudioInfo("wav", 1.0, 0, 8000, 1), "h", 1, 1)


def test_the_message_says_what_was_rated_and_the_first_that_wasnt_with_why():
    """R6.7, R10.2: the save's message, and why a rating went back."""
    three = Outcome(saved=[written(f"/m/{n}.wav", 4) for n in range(3)])
    assert rated_text(three, 4) == "3 songs rated 4 stars"
    assert rated_text(Outcome(saved=[written("/m/a.wav", 1)]), 1) == "1 song rated 1 star"
    assert rated_text(Outcome(saved=[written("/m/a.wav", 0)]), 0) == "Rating cleared on 1 song"
    failed = Outcome(
        saved=[written("/m/a.wav", 5)],
        failed=[Failed(Job("/m/b.wav", {}), "it is read-only"), Failed(Job("/m/c.wav", {}), "x")],
    )
    assert rated_text(failed, 5) == "1 of 3 songs rated 5 stars: b.wav it is read-only, and 1 more"
    assert rated_text(Outcome(failed=failed.failed[:1]), 0) == (
        "Rating cleared on 0 of 1 song: b.wav it is read-only"
    )


def test_an_albums_or_artists_page_shows_the_average_of_its_rated_songs():
    """R10.1: the average of the rated songs, its stars rounded half up; none when none is."""
    assert average_of(13, 3) == {"stars": 4, "text": "4.3 average of 3 rated songs"}
    assert average_of(7, 2) == {"stars": 4, "text": "3.5 average of 2 rated songs"}
    assert average_of(1, 1) == {"stars": 1, "text": "1.0 average of 1 rated song"}
    assert average_of(None, 0) == {} and average_of(0, 0) == {}


# ---------- the bridge ----------


@pytest.fixture
def root(tmp_path):
    """A root of three WAVs, scanned: (root, index, paths)."""
    music = tmp_path / "Music"
    (music / ".musikata").mkdir(parents=True)
    paths, batch = [], []
    for n, title in enumerate(("Tidewater", "Glass Harbor", "Signal Fires")):
        path = str(music / "LD" / f"{n + 1:02d}.wav")
        wav(path, n, title)
        t, info = tags.read(path)
        st = os.stat(path)
        batch.append(scanner.Read(scanner.Seen(f"LD/{n + 1:02d}.wav", st.st_size, st.st_mtime_ns),
                                  t, info, scanner.audio_hash(path, "wav")))  # fmt: skip
        paths.append(path)
    index = db.Index(str(tmp_path / "musikata.db"))
    index.write(lambda c: scanner.write_batch(c, batch, {})).result()
    yield str(music), index, paths
    index.close()


def make(root, available=lambda: True, watching=False, clock=None):
    music, index, _paths = root
    clock = clock or FakeClock(NOW)
    h = ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop",
                      settings.RootTags(), executor=ThreadPoolExecutor(1), watching=False,
                      message_ms=60_000)  # fmt: skip
    write = ratings.Writing(music, index, file_writer(settings.RootTags()), True, clock)
    saved = []
    r = Ratings(music, index, write, h, clock, saved=saved.extend, available=available,
                executor=ThreadPoolExecutor(1), watching=watching)  # fmt: skip
    shown = []
    r.shownChanged.connect(shown.append)
    r.history_, r.saved_, r.shown_ = h, saved, shown
    return r


@pytest.fixture
def rating(root, qapp):
    r = make(root)
    yield r
    r.close()
    r.history_.close()


def ids_of(index):
    return [i for (i,) in index.read().execute("SELECT id FROM song ORDER BY path")]


def stars_of(index):
    return [s for (s,) in index.read().execute("SELECT rating FROM song ORDER BY path")]


def test_rating_several_songs_is_one_save_shown_at_once_and_kept_beside_the_files(
    root, rating, qtbot
):
    """R10.2: rating several songs at once is one undoable change (R4.9), with the save's message
    and Undo; the lists show the new rating at once, written off the GUI thread; R10.3: WAVs'
    in the root's ratings.json."""
    music, index, paths = root
    ids = ids_of(index)
    h = rating.history_
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        rating.rate(ids, 4)
        assert rating.shown() == dict.fromkeys(ids, 4)  # at once, before it is written
    assert h.property("message")["text"] == "3 songs rated 4 stars"
    entry = h.property("message")["undo"]
    assert entry and stars_of(index) == [4, 4, 4]
    assert [w.path for w in rating.saved_] == paths
    doc = ratings.read(ratings.file_of(music))
    assert [(e.path, e.stars) for e in doc.entries] == [(f"LD/0{n}.wav", 4) for n in (1, 2, 3)]
    folder = os.path.join(music, ".musikata", "history")
    with open(os.path.join(folder, entry), encoding="utf-8") as f:
        kept = json.load(f)
    assert (kept["action"], kept["description"], len(kept["files"])) == (
        "rate", "4 stars on 3 songs", 3,
    )  # fmt: skip
    assert rating.shown() == dict.fromkeys(ids, 4)  # until the rows are read again
    rating.reloaded()
    assert rating.shown() == {} and rating.shown_[-1] == {}


def test_a_rating_that_cant_be_kept_goes_back_and_the_message_says_why(root, rating, qtbot):
    """R10.2: the list goes back if the write fails, saying why."""
    music, index, _paths = root
    with open(ratings.file_of(music), "w", encoding="utf-8") as f:
        f.write('{"format": 1, "songs": [')  # a sync in the middle of bringing it
    ids = ids_of(index)
    h = rating.history_
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        rating.rate(ids[:1], 5)
    assert rating.shown() == {} and rating.shown_ == [{ids[0]: 5}, {}]
    assert h.property("message")["text"].startswith("0 of 1 song rated 5 stars: 01.wav the")
    assert "ratings.json can't be read" in h.property("message")["text"]
    assert not h.property("message")["undo"] and stars_of(index) == [None, None, None]


def test_a_star_clicked_in_a_list_rates_its_song_and_the_current_star_clears_it(
    root, rating, qtbot
):
    """R10.2: a star clicked in any song list, as the row shows it, the rating being saved
    included; a click past the rows does nothing."""
    _music, index, _paths = root
    songs = SongsModel(index.read, sort="title")
    songs.reload()
    qtbot.waitUntil(lambda: songs.rowCount() == 3, timeout=WAIT)
    rows = {songs.row(n)["title"]: n for n in range(3)}
    h = rating.history_
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        rating.rateRow(songs, rows["Signal Fires"], 3)
    songs.show_ratings(rating.shown())
    assert songs.rating_at(rows["Signal Fires"]) == 3
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        rating.rateRow(songs, rows["Signal Fires"], 3)  # the star shown: cleared
    assert h.property("message")["text"] == "Rating cleared on 1 song"
    rating.rateRow(songs, 99, 3)
    rating.rateRow(QObject(), 0, 3)  # not a list of songs
    assert stars_of(index) == [None, None, 0]


def test_the_songs_list_sorts_by_the_ratings_kept_beside_the_files(root, rating, qtbot):
    """R10.5: Songs sorted by rating, the WAVs' ratings ratings.json keeps among them."""
    _music, index, _paths = root
    ids = ids_of(index)
    with qtbot.waitSignal(rating.history_.messageChanged, timeout=WAIT):
        rating.rate(ids[1:2], 5)
    with qtbot.waitSignal(rating.history_.messageChanged, timeout=WAIT):
        rating.rate(ids[2:], 2)
    songs = SongsModel(index.read, sort="rating")
    songs.sort_by("rating", descending=True)
    qtbot.waitUntil(lambda: songs.rowCount() == 3, timeout=WAIT)
    assert [songs.row(n)["title"] for n in range(3)] == ["Glass Harbor", "Signal Fires",
                                                          "Tidewater"]  # fmt: skip


def test_a_root_that_isnt_there_rates_nothing_and_says_why(root, qapp):
    """R2.10: every change to files is unavailable while the root isn't there, saying why."""
    r = make(root, available=lambda: False)
    r.rate(ids_of(root[1]), 4)
    assert r.shown() == {} and r.history_.property("message")["text"] == NOT_THERE
    r.rate([], 4)
    r.close()
    r.history_.close()


def test_the_selection_rated_by_the_keys_is_the_open_views(root, rating, qtbot):
    """R10.2, R6.9: Ctrl+0 to Ctrl+5 rate the open view's selection; none selected, it says so."""

    class View:  # what the bridge asks of the library: the view open and its list
        def __init__(self, songs):
            self.songs = songs

        def property(self, name):
            return "songs" if name == "view" else self.songs

    _music, index, _paths = root
    songs = SongsModel(index.read, sort="title")
    songs.reload()
    qtbot.waitUntil(lambda: songs.rowCount() == 3, timeout=WAIT)
    library = View(songs)
    rating.rateSelection(library, 5)
    assert rating.history_.property("message")["text"] == NONE_SELECTED
    songs.selectAll()
    with qtbot.waitSignal(rating.history_.messageChanged, timeout=WAIT):
        rating.rateSelection(library, 5)
    assert stars_of(index) == [5, 5, 5]


@pytest.mark.slow
def test_ratings_json_is_read_at_start_and_again_when_another_computer_changes_it(root, qtbot):
    """R10.3, A2.8: the root's ratings.json is read into the index at start, and again once the
    watcher sees another computer change it; the lists then read their rows again."""
    music, index, _paths = root
    h = scanner.audio_hash(os.path.join(music, "LD", "02.wav"), "wav")

    def another(stars):
        with open(ratings.file_of(music), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "format": 1,
                    "songs": [
                        {
                            "path": "LD/02.wav",
                            "hash": h,
                            "stars": stars,
                            "changed": f"2026-11-2{stars}T10:00:00Z",
                        }
                    ],
                },
                f,
            )

    another(2)
    r = make(root, watching=True, clock=SystemClock())  # the watch gathers for a real second
    with qtbot.waitSignal(r.changed, timeout=WAIT):
        r.start()
    assert stars_of(index) == [None, 2, None]
    qtbot.waitUntil(lambda: "" in r._watcher.known(), timeout=WAIT)
    with qtbot.waitSignal(r.changed, timeout=WAIT):
        another(5)
    assert stars_of(index) == [None, 5, None]
    r.close()
    r.history_.close()


# ---------- the window ----------


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """Three songs of Glass Harbor as FLAC, rated as the demo library rates them: {name: path}."""
    d = tmp_path_factory.mktemp("made")
    out = {}
    for n, (title, rating) in enumerate(
        (("Tidewater", 4), ("Glass Harbor", 5), ("Undertow", 3)), 1
    ):
        path = str(d / f"{n:02d}.flac")
        demo.encode(path, "flac", 0.2, 330 + 110 * n)
        t = {"title": title, "artist": "Lumen Drift", "album": "Glass Harbor",
             "albumartist": "Lumen Drift", "track": n, "tracktotal": 10, "year": 2019,
             "genre": ["Electronic"], "rating": rating}  # fmt: skip
        demo.tag(path, demo.Song(path, "flac", t))
        out[f"{n:02d}.flac"] = path
    return out


@pytest.fixture
def shell(made, tmp_path, qapp, qtbot):
    """MusiKata over the three FLACs and a WAV, scanned."""
    music = tmp_path / "Music"
    album = music / "Lumen Drift" / "Glass Harbor"
    album.mkdir(parents=True)
    for name, src in made.items():
        shutil.copyfile(src, album / name)
    wav(album / "04.wav", 4, "Signal Fires")
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(music), env, FakeClock(datetime.now(UTC)), lambda: ThreadPoolExecutor(1))
    s.library.rescan()
    qtbot.waitUntil(lambda: not s.library.scanning, timeout=WAIT * 3)
    assert s.index.read().execute("SELECT COUNT(*) FROM song").fetchone()[0] == 4
    s.music_ = str(music)
    s.window.show()
    yield s
    s.close()


def find(shell, name):
    found = []

    def walk(item):
        if item.objectName() == name and item.isVisible():
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    return found


def click_star(shell, stars, star):
    """A click on star `star` (1 to 5) of a Stars row."""
    size = stars.property("size")
    x = (star - 1) * (size + stars.property("spacing")) + size / 2
    at = stars.mapToScene(QPointF(x, stars.height() / 2)).toPoint()
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


def settled(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.window.grabWindow()


def by_title(shell):
    rows = shell.index.read().execute("SELECT title, rating FROM song")
    return dict(rows.fetchall())


@pytest.mark.slow
def test_stars_clicked_and_ctrl_keys_rate_songs_in_the_window_with_undo_and_no_qml_warning(
    shell, qtbot, qtlog
):
    """R10.2 in the window: a star clicked in the Songs list and in the now-playing bar, Ctrl+2
    on the selection, Ctrl+0 clearing it, each saved where its song's rating goes (R10.4: the
    FLACs' files, the WAV's ratings.json) with its message and Undo; R10.1: the album's page
    shows the average of its rated songs; every text in its box."""
    lib, h, p = shell.library, shell.changes, shell.player
    lib.show("songs")
    songs = lib.property("songs")
    qtbot.waitUntil(lambda: songs.rowCount() == 4, timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    first = songs.row(0)["title"]
    stars = find(shell, "rowStars")[0]
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        click_star(shell, stars, 2)
    assert h.property("message")["text"] == "1 song rated 2 stars"
    qtbot.waitUntil(lambda: by_title(shell)[first] == 2, timeout=WAIT)  # its row, once written
    songs.selectAll()
    shell.window.requestActivate()
    qtbot.waitUntil(lambda: shell.window.isActive(), timeout=WAIT)
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        QTest.keyClick(shell.window, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert h.property("message")["text"] == "4 songs rated 3 stars"
    qtbot.waitUntil(lambda: set(by_title(shell).values()) == {3}, timeout=WAIT)
    album = os.path.join(shell.music_, "Lumen Drift", "Glass Harbor")
    assert tags.read(os.path.join(album, "02.flac"))[0].rating == 3  # in the file (R10.4)
    assert tags.read(os.path.join(album, "04.wav"))[0].rating is None  # beside it (R10.3)
    assert ratings.read(ratings.file_of(shell.music_)).entries[0].stars == 3
    qtbot.waitUntil(lambda: songs.rating_at(0) == 3 and not shell.ratings.shown(), timeout=WAIT)
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        QTest.keyClick(shell.window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert h.property("message")["text"] == "Undone: 3 stars on 4 songs"
    before = {"Tidewater": 4, "Glass Harbor": 5, "Undertow": 3, "Signal Fires": 0, first: 2}
    qtbot.waitUntil(lambda: {t: r or 0 for t, r in by_title(shell).items()} == before,
                    timeout=WAIT)  # fmt: skip
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        QTest.keyClick(shell.window, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    assert h.property("message")["text"] == "Rating cleared on 4 songs"
    qtbot.waitUntil(lambda: set(by_title(shell).values()) == {0, None}, timeout=WAIT)
    p.cue(songs.queue_from(0)[0], "Songs")
    qtbot.waitUntil(lambda: bool(find(shell, "barRating")), timeout=WAIT)
    settled(shell, qtbot)  # the bar laid out with its song
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        click_star(shell, find(shell, "barRating")[0], 5)
    assert p.property("rating") == 5
    qtbot.waitUntil(lambda: by_title(shell)[first] == 5, timeout=WAIT)
    e = shell.edit  # the Edit tags panel's rating, set by its stars and saved with the rest
    songs.selectAll()
    e.editSelection(songs)
    qtbot.waitUntil(lambda: e.property("count") == 4 and not e.property("loading"), timeout=WAIT)
    settled(shell, qtbot)
    click_star(shell, find(shell, "editStars")[0], 1)
    assert e.property("rating") == {"stars": 1, "mixed": False, "changed": True}
    assert layout.faults(shell.window) == []
    e.revert()
    e.hide()
    (artist_id,) = shell.index.read().execute("SELECT id FROM artist").fetchone()
    lib.openArtist(artist_id)
    qtbot.waitUntil(lambda: bool(find(shell, "artistAverage")), timeout=WAIT)
    assert lib.property("artist").property("average")["stars"] == 5
    (album_id,) = shell.index.read().execute("SELECT id FROM album").fetchone()
    lib.openAlbum(album_id)
    qtbot.waitUntil(lambda: bool(find(shell, "albumAverage")), timeout=WAIT)
    assert lib.property("album").property("average")["text"] == "5.0 average of 1 rated song"
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
