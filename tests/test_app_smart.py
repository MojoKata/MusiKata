"""Smart playlists in the running app (src/musikata/smart.py, and their part in playlists.py and
dragging.py; R8.9): the rule in words on the page, the dialog of New smart playlist… and Edit
rule with its count of songs as the rule changes, Save making or editing one, the playlists kept
current after a scan, a save, a rating and plays, and a smart playlist's songs never changed by
hand: no drag handles, nothing dropped on it, no Remove from playlist.

Why: a smart playlist's songs are its rule's. A dialog that saves a rule other than the one shown,
a page that lets songs be dragged in or out by hand, or a list not kept current would each show a
user a playlist that isn't what its rule says."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeClock, fill
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, bridges, dragging, layout, tour
from musikata import smart as smart_app
from musikata.playlists import Playlists, is_smart, kicker_text, smart_text
from musikata.smart import Form, SmartPlaylists, form_of, matches_text, reading_text, rule_of
from musikata.smart import rule_text as words
from musikata_core import playlists, smart
from musikata_core.playlists import Store
from musikata_core.smart import Rule

WAIT = 10_000
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
LD = "Lumen Drift"

# ---------- what it says ----------


def test_the_rule_is_said_in_words_its_conditions_then_its_limit_and_order():
    """R8.9: its view shows the rule."""
    assert words(Rule(rating=4, order="rating")) == "Rated 4 stars and up · highest rated first"
    assert words(Rule(rating=5)) == "Rated 5 stars · by artist and album"
    assert words(Rule(rating=1, genre=" Jazz ", artist=LD, years=(1990, 1999), added=1, plays=2,
                      limit=50, order="played")) == (
        "Rated 1 star and up · genre Jazz · by Lumen Drift · from 1990 to 1999 · added in the"
        " last 1 day · played 2 times or more · the first 50 songs, last played first"
    )  # fmt: skip
    assert words(Rule(years=(1999, 1999))).startswith("From 1999 ·")
    assert words(Rule(years=(None, 1980), limit=1)) == (
        "From 1980 or before · the first 1 song, by artist and album"
    )
    assert words(Rule(years=(2000, None))).startswith("From 2000 or after")
    assert words(Rule()) == "Every song · by artist and album"


def test_a_broken_or_newer_rule_says_so_on_its_page():
    assert reading_text(smart.read_rule('{"rating": 9}')) == (
        "Its rule can't be used (its rating isn't 1 to 5 stars): it is kept as a plain list"
    )
    assert reading_text(smart.read_rule('{"format": 2, "rating": 4}')) == (
        "Rated 4 stars and up · by artist and album · a newer MusiKata's rule, kept as it is"
    )
    assert kicker_text("m3u8", True) == "Smart playlist · M3U8"
    assert smart_text("Best") == "Best is a smart playlist: its rule chooses its songs"
    assert is_smart('{"rating": 4}') and is_smart('{"format": 2}')
    assert not is_smart('{"rating": 9}') and not is_smart(None)


def test_the_count_says_how_many_match_and_how_many_the_limit_keeps():
    assert matches_text(None, None) == "Counting…"
    assert matches_text(0, None) == "No song matches it yet"
    assert matches_text(1, None) == "1 song matches"
    assert matches_text(1212, 50) == "1,212 songs match; the first 50 are kept"
    assert matches_text(12, 50) == "12 songs match"


# ---------- the dialog's values ----------


def form(**on):
    f = form_of(None)
    for name, value in on.items():
        if name == "to":
            f.to = value
        elif name == "limit":
            f.limit_on, f.limit = True, value
        else:
            f.on[name], f.value[name] = True, value
    return f


def test_the_dialogs_values_make_the_rule_and_say_why_when_they_dont():
    assert rule_of(form_of(None)) == (None, "Choose at least one condition")
    assert rule_of(form(rating="4")) == (Rule(rating=4), "")
    assert rule_of(form(genre=" Jazz ", artist=LD)) == (Rule(genre="Jazz", artist=LD), "")
    assert rule_of(form(years="1999", to="1990"))[0] == Rule(years=(1990, 1999))
    assert rule_of(form(years="", to="1990"))[0] == Rule(years=(None, 1990))
    assert rule_of(form(added="30", plays="1,000", limit="50"))[0] == Rule(added=30, plays=1000,
                                                                          limit=50)  # fmt: skip
    for bad, why in [
        (form(rating="0"), "Choose the stars"),
        (form(genre="  "), "Type the genre"),
        (form(artist=""), "Type the artist"),
        (form(years="19x9"), "Type a year, or two"),
        (form(years="", to=""), "Type a year, or two"),
        (form(added="-3"), "Type a number of days"),
        (form(plays="٣"), "Type a number of times"),
        (form(rating="4", limit="0"), "Type how many songs it keeps"),
    ]:
        assert rule_of(bad) == (None, why)
    f = form(rating="4")
    f.order = "nonsense"
    assert rule_of(f)[0] == Rule(rating=4)


def test_a_rule_opened_in_the_dialog_saves_back_the_same_rule_its_unknown_fields_kept():
    for rule in (Rule(rating=4, order="rating"),
                 Rule(genre="Jazz", artist=LD, years=(None, 1999), added=7, plays=3, limit=20,
                      order="added", extra=(("colour", '"blue"'),)),
                 Rule(years=(1990, None))):  # fmt: skip
        assert rule_of(form_of(rule)) == (rule, "")
    assert form_of(None) == Form(value=dict(smart_app.DEFAULTS), limit="50")


# ---------- the bridge ----------

SONGS = [
    {"path": "A/01 Alpha.flac", "title": "Alpha", "artist": LD, "album": "Glass", "track": 1,
     "rating": 5, "genres": ("Jazz",)},
    {"path": "A/02 Beta.flac", "title": "Beta", "artist": LD, "album": "Glass", "track": 2,
     "rating": 4},
    {"path": "B/Gamma.mp3", "title": "Gamma", "artist": "Other", "album": "Tide", "track": 1,
     "genres": ("Jazz",), "rating": 2},
]  # fmt: skip
ALPHA, BETA, GAMMA = (s["path"] for s in SONGS)


class Said(list):
    def __call__(self, text):
        self.append(text)


@pytest.fixture
def root(tmp_path, qapp):
    from musikata_core import db

    music = tmp_path / "Music"
    (music / "Playlists").mkdir(parents=True)
    (music / "Playlists" / "Road Trip.m3u8").write_text("#EXTM3U\n../A/01 Alpha.flac\n")
    index = db.Index(str(tmp_path / "musikata.db"))
    fill(index, SONGS)
    playlists.refresh(str(music), index, {"Playlists": [playlists.Found("Road Trip.m3u8", 1, 1)]},
                      lambda f: True)  # fmt: skip
    library = bridges.Library(str(music), index, str(tmp_path), ThreadPoolExecutor)
    yield str(music), index, library
    library.close()
    index.close()


@pytest.fixture
def bridge(root):
    music, index, library = root
    said, renamed = Said(), []
    s = SmartPlaylists(Store(music, index), library, index.read, FakeClock(NOW), say=said,
                       rename=renamed.append)  # fmt: skip
    s.said, s.renamed = said, renamed
    yield s
    s.shut()


def ids_of(index, name):
    return index.read().execute("SELECT id FROM playlist WHERE name = ?", (name,)).fetchone()[0]


def text_of(music, name):
    with open(os.path.join(music, "Playlists", name + ".m3u8"), encoding="utf-8") as f:
        return f.read()


def put(music, index, name, text):
    """A playlist file another program wrote, read into the index."""
    with open(os.path.join(music, "Playlists", name + ".m3u8"), "w", encoding="utf-8") as f:
        f.write(text)
    found = {"Playlists": [playlists.Found(name + ".m3u8", 1, 1)]}
    playlists.refresh(music, index, found, lambda f: True)


def counted(bridge, qtbot, text):
    qtbot.waitUntil(lambda: bridge.property("matchText") == text, timeout=WAIT)


def test_new_smart_playlist_counts_as_the_rule_changes_and_save_makes_and_opens_it(
    bridge, root, qtbot
):
    """R8.9: New smart playlist…, the dialog's count as the rule changes, Save making the file
    with its rule line, opening it and selecting its name for editing (R8.3's way)."""
    music, index, library = root
    bridge.openNew()
    assert bridge.property("opened") and bridge.property("title") == "New smart playlist"
    assert bridge.property("matchText") == "Choose at least one condition"
    assert bridge.property("saveLater") == "Choose at least one condition"
    assert [c["name"] for c in bridge.property("conditions")] == [
        "rating", "genre", "artist", "years", "added", "plays"
    ]  # fmt: skip
    bridge.setOn("rating", True)  # 4 stars offered
    counted(bridge, qtbot, "2 songs match")
    bridge.setValue("genre", "jazz")  # typing ticks its box
    counted(bridge, qtbot, "1 song matches")
    bridge.setOn("genre", False)
    bridge.setValue("limit", "1")
    counted(bridge, qtbot, "2 songs match; the first 1 are kept")
    bridge.setOn("limit", False)
    bridge.setOrder("rating")
    bridge.setOrder("nonsense")
    assert [o["order"] for o in bridge.property("orders") if o["chosen"]] == ["rating"]
    counted(bridge, qtbot, "2 songs match")
    assert bridge.property("saveLater") == "" and not bridge.property("limitOn")
    bridge.save()
    qtbot.waitUntil(lambda: len(bridge.said) > 0, timeout=WAIT)
    assert bridge.said == ["Made Four stars and up with 2 songs"]
    assert not bridge.property("opened")
    made = ids_of(index, "Four stars and up")
    assert bridge.renamed == [made] and library.property("view") == "playlist"
    text = text_of(music, "Four stars and up")
    assert text.splitlines()[1] == smart.rule_line(Rule(rating=4, order="rating"))
    page = library.property("playlistPage")
    assert page.property("smart") and page.property("rule") == (
        "Rated 4 stars and up · highest rated first"
    )
    assert page.property("kicker") == "Smart playlist · M3U8"
    assert [a["action"] for a in page.property("actions")] == ["playlist", "edit", "infer"]
    sidebar = {m["name"]: m["smart"] for m in library.property("playlists").items()}
    assert sidebar == {"Four stars and up": True, "Road Trip": False}


def test_edit_rule_opens_its_rule_and_save_writes_the_new_one_and_its_songs(bridge, root, qtbot):
    music, index, library = root
    store = Store(music, index)
    made = store.create_smart(Rule(rating=4), [ALPHA, BETA], "Best")
    library.reload()
    bridge.openEdit(made.playlist)
    assert bridge.property("title") == "Edit the rule of Best"
    counted(bridge, qtbot, "2 songs match")
    bridge.setOn("rating", False)
    bridge.setValue("genre", "Jazz")
    bridge.setValue("to", "")
    bridge.setOn("years", False)
    counted(bridge, qtbot, "2 songs match")
    bridge.save()
    qtbot.waitUntil(lambda: len(bridge.said) > 0, timeout=WAIT)
    assert bridge.said == ["Best now holds 2 songs"]
    assert smart.rule_line(Rule(genre="Jazz")) in text_of(music, "Best")
    entries = index.read().execute(
        "SELECT path FROM playlist_entry WHERE playlist_id = ? ORDER BY position",
        (made.playlist,),
    )
    assert [p for (p,) in entries] == [ALPHA, GAMMA]
    library.openPlaylist(made.playlist)
    bridge.go({"view": "playlist", "rule": True})  # the tour's P03
    assert bridge.property("title") == "Edit the rule of Best"
    bridge.go({"view": "albums"})
    assert not bridge.property("opened")
    bridge.openEdit(9999)  # gone: nothing opens
    assert not bridge.property("opened")
    bridge.openEdit(ids_of(index, "Road Trip"))  # a plain list given a rule: nothing chosen yet
    assert bridge.property("saveLater") == "Choose at least one condition"
    bridge.save()  # can't be saved yet: nothing happens
    assert bridge.property("opened")
    bridge.cancel()
    assert not bridge.property("opened") and bridge.property("matchText") == ""


def test_a_newer_rule_isnt_opened_and_nothing_is_made_while_the_root_is_gone(root, qtbot):
    music, index, library = root
    put(music, index, "New", '#EXTM3U\n#MUSIKATA-RULE:{"format": 2, "rating": 4}\n')
    library.reload()
    said = Said()
    there = [True]
    s = SmartPlaylists(Store(music, index), library, index.read, say=said,
                       available=lambda: there[0])  # fmt: skip
    newer = ids_of(index, "New")
    s.openEdit(newer)
    assert not s.property("opened") and said == [smart_app.NEWER_LATER]
    library.openPlaylist(newer)
    page = library.property("playlistPage")
    assert page.property("smart") and page.property("ruleLater") == smart_app.NEWER_LATER
    there[0] = False
    s.openNew()
    assert not s.property("opened") and said[-1] == smart_app.NOT_THERE
    with qtbot.assertNotEmitted(s.checked, wait=50):
        s.poke()
    s.shut()
    s.openNew()  # shut: nothing runs
    s.poke()


def test_a_broken_rule_shows_why_and_edit_rule_starts_from_what_could_be_read(bridge, root):
    music, index, library = root
    put(
        music, index, "Odd", '#EXTM3U\n#MUSIKATA-RULE:{"rating": 4, "plays": "x"}\n../B/Gamma.mp3\n'
    )
    library.reload()
    odd = ids_of(index, "Odd")
    library.openPlaylist(odd)
    page = library.property("playlistPage")
    assert not page.property("smart") and page.property("kicker") == "Playlist · M3U8"
    assert page.property("rule").startswith("Its rule can't be used (its plays")
    bridge.openEdit(odd)
    on = {c["name"]: c["on"] for c in bridge.property("conditions")}
    assert on["rating"] and not on["plays"]


def test_the_smart_playlists_are_kept_current_after_the_library_changes_and_plays(
    bridge, root, qtbot
):
    """R8.9: rewritten whenever its songs change, never when they don't, at A2.8's pace: a change
    the library made at once, one after it within a minute, plays' within ten."""
    music, index, library = root
    store = Store(music, index)
    made = store.create_smart(Rule(rating=4), [ALPHA], "Best")
    path = os.path.join(music, "Playlists", "Best.m3u8")
    with qtbot.waitSignal(bridge.checked, timeout=WAIT):
        bridge.poke()
    assert "../A/02 Beta.flac" in text_of(music, "Best")
    before = os.stat(path).st_mtime_ns
    with qtbot.waitSignal(bridge.checked, timeout=WAIT):
        bridge.pokePlays()
    assert os.stat(path).st_mtime_ns == before and bridge.due() is None  # nothing changed
    index.write(lambda c: c.execute("UPDATE song SET rating = 5 WHERE path = ?",
                                    (GAMMA,))).result()  # fmt: skip
    with qtbot.waitSignal(bridge.checked, timeout=WAIT):
        bridge.pokePlays()
    assert os.stat(path).st_mtime_ns == before  # its pace: plays wait ten minutes
    assert 500 < bridge.due() <= smart.SLOW
    with qtbot.waitSignal(bridge.checked, timeout=WAIT):
        bridge.poke()
    assert bridge.due() <= smart.QUICK
    bridge.go({"view": "albums"})  # the tour's other steps: nothing opens
    assert not bridge.property("opened") and made.playlist is not None


def test_a_smart_playlists_entries_arent_removed_or_moved_by_hand(root, qtbot):
    """R8.9: Remove from playlist isn't offered, and Delete or Ctrl+Shift+↑ / ↓ says why."""
    music, index, library = root
    made = Store(music, index).create_smart(Rule(rating=4), [ALPHA, BETA], "Best")
    library.reload()
    library.openPlaylist(made.playlist)
    model = library.property("playlistPage").property("songs")
    said = Said()
    lists = Playlists(Store(music, index), library, index.read, say=said)
    model.click(0, False, False)
    lists.removeSelected(model)
    lists.removeRow(model, 0)
    lists.move_entries(model, model.selected_entries(), 2)
    shift = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier).value
    assert lists.pressMove(model, int(Qt.Key.Key_Down), shift)
    assert said == [smart_text("Best")] * 4 and model.rowCount() == 2
    lists.shut()


def test_songs_or_files_dropped_on_a_smart_playlist_are_refused_saying_why(root, qtbot):
    """R8.9: dropping songs onto a smart playlist is refused with a reason; its own songs are
    neither moved within its page nor taken."""
    music, index, library = root
    made = Store(music, index).create_smart(Rule(rating=4), [ALPHA, BETA], "Best")
    song = dragging.Carried((1,))
    own = dragging.Carried((1,), playlist=made.playlist, entries=(5,))
    pl, page = dragging.PLAYLIST, dragging.PAGE
    assert dragging.drop_of(pl, made.playlist, song, [], True).what == dragging.REFUSE
    assert dragging.drop_of(page, made.playlist, song, [], True).what == dragging.REFUSE
    assert dragging.drop_of(pl, made.playlist, None, ["/x.mp3"], True).what == dragging.REFUSE
    assert dragging.drop_of(page, made.playlist, own, [], True).what == dragging.NONE
    assert dragging.drop_of(pl, made.playlist, None, [], True).what == dragging.NONE
    assert dragging.target_text(dragging.REFUSE, pl, "Best") == smart_text("Best")
    said = Said()
    d = dragging.Dragging(music, index.read, library, say=said)
    text = dragging.encode(song, music)
    assert d.enter(pl, made.playlist, text, [])
    assert d.property("refused") and d.property("targetText") == smart_text("Best")
    assert not d.drop(pl, made.playlist, text, [])
    assert said == [smart_text("Best")] and not d.property("refused")
    assert d.enter(pl, ids_of(index, "Road Trip"), text, []) and not d.property("refused")
    d.close()


# ---------- the window ----------


@pytest.fixture
def shell(tmp_path, qapp, qtbot):
    music = tmp_path / "Music"
    (music / "Playlists").mkdir(parents=True)
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(music), env, FakeClock(datetime.now(UTC) - timedelta(minutes=1)),
                 lambda: ThreadPoolExecutor(1))  # fmt: skip
    fill(s.index, SONGS)
    store = Store(str(music), s.index)
    store.create_smart(Rule(rating=4, order="rating"), [ALPHA], "Four stars and up")
    store.create([1, 2, 3], "Road Trip")
    s.library.reload()
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


def click(shell, item):
    at = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


def settled(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.window.grabWindow()


@pytest.mark.slow
def test_a_smart_playlists_page_and_its_dialog_load_with_no_qml_warning_and_text_in_boxes(
    shell, qtbot, qtlog
):
    """R8.9, P02 and P03 (after P01): the sidebar's smart playlist kept current once the library
    is read again and opened; its rule in words, Edit rule, no drag handles; Edit rule's dialog,
    whole; New smart playlist… beside + opens it too."""
    page = shell.library.property("playlistPage")
    with qtbot.waitSignal(shell.smart.checked, timeout=WAIT):
        shell.library.reload()  # as after a scan: kept current
    side = find(shell, "side-playlist")
    click(shell, side[1])  # Road Trip, then the smart one: its taller header shown whole
    qtbot.waitUntil(lambda: page.property("name") == "Road Trip", timeout=WAIT)
    settled(shell, qtbot)
    click(shell, side[0])
    qtbot.waitUntil(lambda: page.property("songs").rowCount() == 2, timeout=WAIT)
    settled(shell, qtbot)
    songs = find(shell, "playlistSongs")[0]
    qtbot.waitUntil(lambda: songs.property("contentY") == songs.property("originY"), timeout=WAIT)
    assert find(shell, "playlistRule")[0].property("text") == (
        "Rated 4 stars and up · highest rated first"
    )
    assert find(shell, "playlistExport") != [] and find(shell, "editRule") != []
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "editRule")[0])
    qtbot.waitUntil(lambda: find(shell, "smartDialog") != [], timeout=WAIT)
    qtbot.waitUntil(lambda: shell.smart.property("matchText") == "2 songs match", timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "smartOn-genre")[0])
    assert shell.smart.property("conditions")[1]["on"]
    click(shell, find(shell, "smartOrder-plays")[0])
    assert [o["order"] for o in shell.smart.property("orders") if o["chosen"]] == ["plays"]
    click(shell, find(shell, "cancelSmart")[0])
    qtbot.waitUntil(lambda: not shell.smart.property("opened"), timeout=WAIT)
    click(shell, find(shell, "newSmartPlaylist")[0])
    qtbot.waitUntil(lambda: find(shell, "smartDialog") != [], timeout=WAIT)
    assert shell.smart.property("title") == "New smart playlist"
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    shell.smart.cancel()
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
