"""The root's card and a root that isn't there (src/musikata/bridges.py; R2.1.1, R2.1.2, R2.10,
R2.10.1): the card's line and dot, the banner, playing held back with a word why, the root looked
for and rescanned when it comes back, linked folders out of reach, and the question before songs
gone are taken out.

Why: an unplugged drive looks to a scan like every song deleted. A library that took it for that
would lose its plays, ratings and playlists' entries the moment a USB cable came loose."""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock, wav

from musikata import bridges
from musikata_core import db


def threads():
    return ThreadPoolExecutor(2)


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "Music"
    for n in range(4):
        wav(root / "A" / f"{n}.wav", n, f"Song {n}")
    return root


def library(index, music, tmp_path, **kw):
    return bridges.Library(str(music), index, str(tmp_path), threads, clock=FakeClock(), **kw)


def scanned(lib, qtbot):
    with qtbot.waitSignal(lib.scanningChanged):
        lib.rescan()
    qtbot.waitUntil(lambda: not lib.property("scanning"), timeout=10_000)


def songs(index):
    return {p for (p,) in index.read().execute("SELECT path FROM song")}


def many(music, n=24):
    """`n` songs more, in B: enough for more than 20 to go (R2.10.1)."""
    for i in range(n):
        wav(music / "B" / f"{i}.wav", 100 + i)


def gone(music, n):
    """B's first `n` songs removed."""
    for i in range(n):
        os.remove(music / "B" / f"{i}.wav")


MUSIC = os.path.join("~", "Music")


# ---------- the texts ----------


def test_the_title_names_a_root_given_for_the_run_only():
    assert bridges.window_title("/media/usb/Music", True) == "MusiKata — /media/usb/Music"
    assert bridges.window_title("~/Music", False) == "MusiKata"


def test_the_banner_names_the_root_or_the_linked_folders_out_of_reach():
    assert bridges.banner("~/Music", False, []) == {}
    root = bridges.banner("~/Music", True, ["~/Music/Live"])
    assert root == {
        "title": "~/Music isn't available. Its drive may be unplugged or its share not mounted.",
        "detail": "Your library is kept. Playing and changes to files wait until it's back.",
        "choose": True,
    }
    one = bridges.banner("~/Music", False, ["~/Music/Live"])
    assert one["title"].startswith("~/Music/Live isn't available.") and one["choose"] is False
    assert one["detail"] == "Its songs are kept. Playing them waits until it's back."
    two = bridges.banner("~/Music", False, ["~/Music/Live", "~/Music/Old"])
    assert two["title"].startswith("~/Music/Live and 1 other linked folder aren't available.")
    assert two["detail"] == "Their songs are kept. Playing them waits until they're back."


def test_the_question_counts_the_songs_gone():
    assert bridges.question("~/Music", 0) == {}
    assert bridges.question("~/Music", 1) == {
        "text": "1 song is missing from ~/Music. Remove it from the library?",
        "keep": "Keep it",
        "remove": "Remove",
    }
    assert bridges.question("~/Music", 12040)["text"] == (
        "12,040 songs are missing from ~/Music. Remove them from the library?"
    )
    assert bridges.question("~/Music", 2)["keep"] == "Keep them"


def test_the_dot_and_its_tooltip():
    assert bridges.dot(True, True, 3, 1) == "missing"
    assert bridges.dot(False, True, 3, 1) == "scanning"
    assert bridges.dot(False, False, 3, 0) == "warn" == bridges.dot(False, False, 0, 1)
    assert bridges.dot(False, False, 0, 0) == "ok"
    assert bridges.dot_tip("ok", "~/Music", 0, [], []) == "Up to date"
    assert bridges.dot_tip("missing", "~/Music", 0, [], []) == "~/Music isn't available"
    assert bridges.dot_tip("scanning", "~/Music", 0, [], []) == "Scanning ~/Music"
    names = [("a.flac", "not a FLAC file"), ("b.mp3", "empty"), ("c.ogg", "cut short")]
    assert bridges.dot_tip("warn", "~/Music", 5, names, ["~/Music/Live"]).split("\n") == [
        "5 files couldn't be read:", "a.flac: not a FLAC file", "b.mp3: empty",
        "c.ogg: cut short", "and 2 more", "~/Music/Live can't be reached",
    ]  # fmt: skip
    assert bridges.dot_tip("warn", "~", 1, names[:1], []) == (
        "1 file couldn't be read:\na.flac: not a FLAC file"
    )


def test_a_folder_chosen_is_a_path_or_a_file_url_of_a_folder(tmp_path):
    from PySide6.QtCore import QUrl

    assert bridges.local_folder(QUrl.fromLocalFile(str(tmp_path)).toString()) == str(tmp_path)
    assert bridges.local_folder(str(tmp_path)) == str(tmp_path)
    (tmp_path / "f.mp3").write_bytes(b"x")
    assert bridges.local_folder(str(tmp_path / "f.mp3")) is None
    assert bridges.local_folder("") is None


# ---------- the card (R2.1.1) ----------


def test_the_card_is_green_when_up_to_date_and_amber_naming_what_couldnt_be_read(
    index, music, tmp_path, qtbot
):
    lib = library(index, music, tmp_path)
    assert lib.property("dot") == "ok"
    scanned(lib, qtbot)
    assert lib.property("dot") == "ok" and lib.property("dotTip") == "Up to date"
    assert lib.property("line").startswith("4 songs · 0 albums · ")
    (music / "A" / "Broken.flac").write_bytes(b"not audio")
    scanned(lib, qtbot)
    assert lib.property("dot") == "warn"
    assert lib.property("dotTip").startswith("1 file couldn't be read:\nA/Broken.flac: ")
    lib.close()


def test_the_dot_turns_while_the_root_is_scanned(index, music, tmp_path, qtbot):
    lib = library(index, music, tmp_path)
    dots = []
    lib.changed.connect(lambda: dots.append(lib.property("dot")))
    scanned(lib, qtbot)
    assert dots[0] == "scanning" and dots[-1] == "ok"
    lib.close()


# ---------- a root that isn't there (R2.10) ----------


def test_a_root_not_there_at_start_keeps_its_library_and_says_so(index, music, tmp_path, qtbot):
    lib = library(index, music, tmp_path)
    scanned(lib, qtbot)
    lib.close()
    shutil.move(music, tmp_path / "unplugged")
    lib = library(
        index, music, tmp_path, missing=True, looking=lambda root, links: (False, frozenset())
    )
    scanned(lib, qtbot)
    assert lib.last.missing and len(songs(index)) == 4
    assert lib.property("available") is False and lib.property("line") == "Not available"
    assert lib.property("dot") == "missing" and lib.property("dotTip") == f"{MUSIC} isn't available"
    assert lib.property("banner")["title"].startswith(f"{MUSIC} isn't available.")
    assert lib.property("playNote") == f"Playing waits until {MUSIC} is back"
    assert lib.unplayable("A/1.wav") == lib.property("playNote")
    lib.show("songs")
    lib.setSearch("song 2")  # browsing and search still work
    qtbot.waitUntil(lambda: lib.property("songs").rowCount() == 1, timeout=10_000)
    lib.close()


def test_a_root_that_goes_while_it_runs_is_found_gone_kept_and_rescanned_when_back(
    index, music, tmp_path, qtbot
):
    lib = library(index, music, tmp_path, watching=True, look_every=0.001)
    reach = []
    lib.reachChanged.connect(lambda: reach.append(lib.property("available")))
    scanned(lib, qtbot)
    assert lib.watcher.known() and reach == []
    shutil.copytree(music, tmp_path / "copy")
    shutil.rmtree(music)  # unplugged: to a scan, as if every file had gone
    scanned(lib, qtbot)  # what a watched change or a focus gained starts
    assert lib.property("available") is False and len(songs(index)) == 4
    assert reach == [False]  # the player hears it: the song playing is the last (R2.10)
    shutil.copytree(tmp_path / "copy", music)  # plugged back: a look finds it, and rescans
    qtbot.waitUntil(lambda: lib.property("available"), timeout=10_000)
    qtbot.waitUntil(lambda: not lib.property("scanning"), timeout=10_000)
    assert lib.property("banner") == {} and lib.property("dot") == "ok"
    assert lib.watcher.known() and lib.unplayable("A/1.wav") == ""
    assert len(songs(index)) == 4 and reach == [False, True]
    lib.close()


def test_try_again_looks_now_and_a_root_still_gone_keeps_the_banner(index, music, tmp_path, qtbot):
    answers = []

    def looking(root, links):
        answers.append(links)
        return False, frozenset()

    lib = library(index, music, tmp_path, missing=True, looking=looking)
    with qtbot.waitSignal(lib._presence.found):
        lib.retry()
    assert answers and lib.property("available") is False and lib.property("banner")
    lib.close()


def test_a_look_that_finds_the_root_gone_while_it_runs_keeps_the_library(
    index, music, tmp_path, qtbot
):
    there = [True]
    lib = library(index, music, tmp_path, looking=lambda root, links: (there[0], frozenset()))
    scanned(lib, qtbot)
    with qtbot.waitSignal(lib._presence.found):
        lib.window_active(True)  # gaining focus looks: still there
    assert lib.property("available") is True
    there[0] = False
    with qtbot.waitSignal(lib._presence.found):
        lib.window_active(True)
    assert lib.property("available") is False and len(songs(index)) == 4
    lib.window_active(False)
    lib.close()


def test_a_linked_folder_out_of_reach_makes_only_its_songs_unavailable(
    index, music, tmp_path, qtbot
):
    usb = tmp_path / "usb"
    wav(usb / "Live" / "1.wav", 11)
    os.symlink(usb / "Live", music / "Live")
    lib = library(index, music, tmp_path, look_every=0.001)
    reach = []
    lib.reachChanged.connect(lambda: reach.append(lib.unplayable("Live/1.wav") == ""))
    scanned(lib, qtbot)
    shutil.move(usb, tmp_path / "unplugged")
    scanned(lib, qtbot)
    assert reach == [False]
    live = os.path.join(MUSIC, "Live")
    assert lib.property("available") is True and "Live/1.wav" in songs(index)
    assert lib.property("banner")["title"].startswith(f"{live} isn't available")
    assert lib.property("dot") == "warn" and lib.property("dotTip") == f"{live} can't be reached"
    assert lib.unplayable("Live/1.wav") == f"{live} isn't available, so its songs can't play"
    assert lib.unplayable("A/1.wav") == "" and lib.property("playNote") == ""
    shutil.move(tmp_path / "unplugged", usb)  # back: a look finds it, and rescans
    qtbot.waitUntil(lambda: lib.property("banner") == {}, timeout=10_000)
    qtbot.waitUntil(lambda: not lib.property("scanning"), timeout=10_000)
    assert lib.property("dot") == "ok" and reach == [False, True]
    lib.close()


def test_choose_another_folder_says_which_when_it_is_a_folder(index, music, tmp_path, qtbot):
    lib = library(index, music, tmp_path, missing=True)
    got = []
    lib.rootChosen.connect(got.append)
    lib.chooseRoot(str(tmp_path / "nowhere"))
    lib.chooseRoot(str(tmp_path))
    assert got == [str(tmp_path)]
    lib.close()


def test_a_song_whose_root_isnt_there_doesnt_play_and_says_why(tmp_path):
    from musikata.player import Engine

    p = bridges.Player(str(tmp_path), Engine(), refuse=lambda path: "Playing waits")
    p.play("A/1.wav")
    assert p.property("error") == "Playing waits" and p.property("path") == ""
    p.play("")  # nothing at all: no word
    p.close()


# ---------- many songs gone (R2.10.1) ----------


def test_more_than_a_quarter_and_20_gone_asks_and_keep_them_keeps_them_unasked_after(
    index, music, tmp_path, qtbot
):
    many(music)
    lib = library(index, music, tmp_path)
    scanned(lib, qtbot)
    gone(music, 22)  # 22 of 28
    scanned(lib, qtbot)
    assert lib.property("question")["text"] == (
        f"22 songs are missing from {MUSIC}. Remove them from the library?"
    )
    assert len(songs(index)) == 28
    lib.keepMissing()
    assert lib.property("question") == {}
    scanned(lib, qtbot)
    assert lib.property("question") == {} and len(songs(index)) == 28
    lib.close()


def test_a_few_songs_gone_are_taken_out_without_asking(index, music, tmp_path, qtbot):
    lib = library(index, music, tmp_path)
    scanned(lib, qtbot)
    for n in (0, 1, 2):  # 3 of 4: more than a quarter, but not more than 20
        os.remove(music / "A" / f"{n}.wav")
    scanned(lib, qtbot)
    assert lib.property("question") == {} and songs(index) == {"A/3.wav"}
    lib.close()


def test_remove_takes_the_songs_gone_out(index, music, tmp_path, qtbot):
    many(music, 21)
    lib = library(index, music, tmp_path)
    scanned(lib, qtbot)
    gone(music, 21)
    scanned(lib, qtbot)
    assert lib.property("question")["text"].startswith("21 songs are missing")
    lib.removeMissing()
    assert lib.property("question") == {}
    qtbot.waitUntil(lambda: len(songs(index)) == 4, timeout=10_000)
    qtbot.waitUntil(lambda: lib.property("line").startswith("4 songs"), timeout=10_000)
    lib.close()


def test_a_remove_asked_for_while_a_scan_runs_waits_its_turn(index, music, tmp_path, qtbot):
    many(music, 21)
    lib = library(index, music, tmp_path)
    scanned(lib, qtbot)
    gone(music, 21)
    scanned(lib, qtbot)
    lib.rescan()
    lib.removeMissing()  # while the scan runs: after it
    qtbot.waitUntil(lambda: len(songs(index)) == 4, timeout=10_000)
    lib.close()


# ---------- in the window ----------


def find(window, name):
    found = []

    def walk(item):
        if item.objectName() == name:
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(window.contentItem())
    assert len(found) == 1, name
    return found[0]


def click(window, item):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    at = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


@pytest.mark.slow
def test_the_window_of_a_root_not_there_shows_its_banner_and_red_card(tmp_path, qtbot, qtlog):
    from musikata import app, layout

    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    music = tmp_path / "Music"
    wav(music / "A" / "1.wav", 1, "Signal Fires")
    s = app.load(str(music), env, FakeClock(), threads)
    scanned(s.library, qtbot)
    s.close()
    shutil.rmtree(music)
    s = app.load(str(music), env, FakeClock(), threads)
    s.window.show()
    banner, card = find(s.window, "rootBanner"), find(s.window, "rootCard")
    assert banner.isVisible() and find(s.window, "chooseAnother").isVisible()
    assert card.property("missing") is True and not find(s.window, "question").isVisible()
    for w, h in ((1280, 800), (1920, 1040)):
        s.window.setWidth(w)
        s.window.setHeight(h)
        item = s.window.contentItem()
        qtbot.waitUntil(lambda w=w, h=h, item=item: (item.width(), item.height()) == (w, h))
        s.window.grabWindow()
        assert layout.faults(s.window) == [], (w, h)
    with qtbot.waitSignal(s.library._presence.found):
        click(s.window, find(s.window, "tryAgain"))
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    s.close()


@pytest.mark.slow
def test_the_question_of_songs_gone_is_answered_in_the_window(tmp_path, qtbot):
    from musikata import app

    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    music = tmp_path / "Music"
    for n in range(4):
        wav(music / "A" / f"{n}.wav", n)
    many(music, 21)
    s = app.load(str(music), env, FakeClock(), threads)
    s.window.show()
    scanned(s.library, qtbot)
    gone(music, 21)
    scanned(s.library, qtbot)
    question = find(s.window, "question")
    assert question.isVisible() and not find(s.window, "rootBanner").isVisible()
    s.window.grabWindow()
    click(s.window, find(s.window, "removeMissing"))
    qtbot.waitUntil(lambda: len(songs(s.index)) == 4, timeout=10_000)
    assert not question.isVisible()
    s.close()
