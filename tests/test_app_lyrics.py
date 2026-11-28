"""Lyrics in the running app (src/musikata/lyrics.py, LyricsPanel.qml, LyricsEditor.qml,
NowPlayingView.qml; R17.1 to R17.3.1, R17.5, R7.4, R4.9): the Lyrics switch and its keeping, the
song's lyrics read off the GUI thread as the song changes, the line sung followed and a line
clicked seeking there, each Now Playing mode with the switch on, and Edit… and Add… saved where
the root's setting says, through the batch and the change history, and undone.

Why: lyrics out of step with the song, a switch that forgets itself, or a save that lands where
the user didn't ask (or can't be undone) make the feature worse than none."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock, FakeEngine
from PySide6.QtCore import Property as QtProperty
from PySide6.QtCore import QObject, QPointF, Qt, Signal, Slot
from PySide6.QtTest import QTest

from musikata import app, layout, lyrics, tour
from musikata_core import lyrics as core
from musikata_core import scanner, settings, tags
from musikata_core.tags import AudioInfo, Outcome, Tags, WriteError

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

WAIT = 5_000
LRC = "[ar:Lumen Drift]\n[00:10.00]Lanterns on the water line\n[00:20.00]\n[00:30.00]counting ships"


# ---------- what it says (plain) ----------


def found(text, source=core.FILE, path="/m/04 - Signal Fires.lrc"):
    return core.Found(core.parse(text), text, source, path if source == core.FILE else None)


def test_the_lines_carry_their_time_as_n04_shows_it_and_pauses_are_gaps():
    rows = lyrics.line_rows(found(LRC))
    assert [(r["text"], r["time"], r["timeText"], r["gap"]) for r in rows] == [
        ("Lanterns on the water line", 10.0, "0:10", False), ("", 20.0, "0:20", True),
        ("counting ships", 30.0, "0:30", False),
    ]  # fmt: skip
    plain = lyrics.line_rows(found("a\n\nb", core.TAGS))
    assert [(r["time"], r["timeText"], r["gap"]) for r in plain] == [
        (-1.0, "", False), (-1.0, "", True), (-1.0, "", False)
    ]  # fmt: skip


def test_what_now_playing_shows_of_them():
    assert lyrics.state_of("", False, None) == lyrics.NONE
    assert lyrics.state_of("a.flac", True, None) == lyrics.LOADING
    assert lyrics.state_of("a.flac", False, None) == lyrics.MISSING_STATE
    assert lyrics.state_of("a.flac", False, found(LRC)) == lyrics.TIMED
    assert lyrics.state_of("a.flac", False, found("words", core.TAGS)) == lyrics.PLAIN
    assert lyrics.state_of("a.flac", False, found("[Instrumental]")) == lyrics.MARKED


def test_the_analyzer_shows_the_line_sung_and_the_next_with_words():
    rows = lyrics.line_rows(found(LRC))
    assert lyrics.sung(lyrics.TIMED, rows, -1) == ("", "Lanterns on the water line")
    assert lyrics.sung(lyrics.TIMED, rows, 0) == ("Lanterns on the water line", "counting ships")
    assert lyrics.sung(lyrics.TIMED, rows, 1) == ("", "counting ships")  # a pause
    assert lyrics.sung(lyrics.TIMED, rows, 2) == ("counting ships", "")
    assert lyrics.sung(lyrics.MARKED, [], -1) == (lyrics.INSTRUMENTAL, "")
    assert lyrics.sung(lyrics.MISSING_STATE, [], -1) == (lyrics.MISSING, "")
    assert lyrics.sung(lyrics.PLAIN, rows, 0) == ("", "")


def test_the_verse_sung_ends_at_the_next_pause():
    rows = lyrics.line_rows(found(LRC))
    assert lyrics.verse_end(rows, -1) == -1 and lyrics.verse_end(rows, 0) == 0
    assert lyrics.verse_end(rows, 1) == 2 and lyrics.verse_end(rows, 2) == 2
    rows = lyrics.line_rows(found("[00:01.00]a\n[00:02.00]b\n[00:03.00]\n[00:04.00]c"))
    assert lyrics.verse_end(rows, 0) == 1


def test_the_editor_says_what_it_edits_and_where_save_keeps_them():
    assert lyrics.edit_title("Signal Fires", False) == "Edit lyrics · Signal Fires"
    assert lyrics.edit_title("Signal Fires", True) == "Add lyrics · Signal Fires"
    assert lyrics.edit_title("", True) == "Add lyrics"
    name = "04 - Signal Fires.lrc"
    where = lyrics.where_text
    assert where(core.saving("lrc", "a", False, False), name) == (
        "Saved beside the song as 04 - Signal Fires.lrc"
    )  # fmt: skip
    assert where(core.saving("tags", "a", False, False), name) == "Saved in the song's tags"
    assert where(core.saving("both", "a", False, False), name) == (
        "Saved beside the song as 04 - Signal Fires.lrc and in its tags"
    )  # fmt: skip
    assert where(core.saving("lrc", "", True, False), name) == (
        "Saving with no text removes the lyrics"
    )  # fmt: skip
    assert where(core.saving("lrc", "", False, False), name) == ""


def test_saves_are_described_for_the_change_history_and_save_says_why_it_cant():
    assert lyrics.description_of("Signal Fires", True, "a") == "Lyrics of Signal Fires edited"
    assert lyrics.description_of("Signal Fires", False, "a") == "Lyrics added to Signal Fires"
    assert lyrics.description_of("", True, " ") == "Lyrics removed from a song"
    later = lyrics.save_later
    assert later(False, False, False, True, True) == ""
    assert later(True, True, True, True, True) == "Saving…"
    assert later(True, False, True, False, True) == lyrics.NOT_THERE
    assert later(True, False, True, True, False) == lyrics.NOT_HERE
    assert later(True, False, False, True, True) == "Nothing has changed yet"
    assert later(True, False, True, True, True) == ""


# ---------- the bridge, over a player that plays nothing ----------


class Player(QObject):
    """The Player bridge's part lyrics use: the song shown, its place, its title, seeking."""

    nowPlaying = Signal(str)
    positionChanged = Signal()
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._position, self.sought = 0.0, []

    def at(self, seconds):
        self._position = seconds
        self.positionChanged.emit()

    @Slot(float)
    def seek(self, seconds):
        self.sought.append(seconds)

    position = QtProperty(float, lambda self: self._position, notify=positionChanged)
    title = QtProperty(str, lambda self: "Signal Fires", notify=changed)


class Trash:
    def __init__(self):
        self.got = []

    def __call__(self, path):
        self.got.append(os.path.basename(path))
        os.remove(path)
        return True


def write_song(job):
    return tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)


@pytest.fixture
def music(tmp_path):
    """A root of a FLAC with timed lyrics beside it, one with plain lyrics in its tags, and one
    with none: (root, bridge's player)."""
    root = tmp_path / "Music"
    (root / "LD").mkdir(parents=True)
    for name in ("04 - Signal Fires", "05 - Plain", "06 - None"):
        demo.encode(str(root / "LD" / f"{name}.flac"), "flac", 0.1, 440)
    (root / "LD" / "04 - Signal Fires.lrc").write_bytes(("﻿" + LRC).encode())
    tags.save(str(root / "LD" / "05 - Plain.flac"), {"lyrics": "plain\n\nwords"},
              audio_hash=scanner.audio_hash)  # fmt: skip
    return str(root)


def make(root, **kw):
    player = Player()
    kept = []
    bridge = lyrics.Lyrics(
        player, root, write=write_song, keep=lambda **f: kept.append(f), trash=Trash(), **kw
    )
    return player, bridge, kept


def shown(qtbot, bridge, state):
    qtbot.waitUntil(lambda: bridge.property("state") == state, timeout=WAIT)


def test_the_switch_reads_the_songs_lyrics_and_is_kept(music, qtbot):
    """R17.3: off, nothing is read; on, the song's lyrics are, off the GUI thread, and the switch
    is kept (A2.10's appearance)."""
    player, bridge, kept = make(music)
    try:
        assert bridge.property("state") == lyrics.NONE
        player.nowPlaying.emit("LD/04 - Signal Fires.flac")
        assert bridge.property("lines") == [] and not bridge.property("on")
        bridge.toggle()
        assert kept == [{"lyrics": True}] and bridge.property("on")
        shown(qtbot, bridge, lyrics.TIMED)
        assert bridge.property("source") == "Timed · from 04 - Signal Fires.lrc"
        assert [r["text"] for r in bridge.property("lines")][0] == "Lanterns on the water line"
        player.nowPlaying.emit("LD/05 - Plain.flac")
        shown(qtbot, bridge, lyrics.PLAIN)
        assert bridge.property("source") == "Plain · from the song's tags"
        assert bridge.property("plainText") == "plain\n\nwords"
        player.nowPlaying.emit("LD/06 - None.flac")
        shown(qtbot, bridge, lyrics.MISSING_STATE)
        assert bridge.property("source") == "" and bridge.property("currentText") == lyrics.MISSING
        player.nowPlaying.emit("LD/gone.flac")  # can't be read: none, logged
        shown(qtbot, bridge, lyrics.MISSING_STATE)
        player.nowPlaying.emit("")
        assert bridge.property("state") == lyrics.NONE
        bridge.toggle()
        assert kept[-1] == {"lyrics": False}
    finally:
        bridge.close()


def test_the_line_sung_follows_the_song_and_a_line_clicked_seeks_to_it(music, qtbot):
    """R17.2, R7.4: the current line is the last one started as the song plays; clicking a line
    seeks to its time; a plain line seeks nowhere."""
    player, bridge, _ = make(music, on=True)
    try:
        player.nowPlaying.emit("LD/04 - Signal Fires.flac")
        shown(qtbot, bridge, lyrics.TIMED)
        assert bridge.property("current") == -1
        assert bridge.property("nextText") == "Lanterns on the water line"
        with qtbot.waitSignal(bridge.lineChanged):
            player.at(12.0)
        assert bridge.property("current") == 0
        assert bridge.property("currentText") == "Lanterns on the water line"
        with qtbot.assertNotEmitted(bridge.lineChanged):
            player.at(15.0)  # the same line
        player.at(31.0)
        assert bridge.property("current") == 2
        bridge.seekLine(0)
        bridge.seekLine(9)  # no such line
        assert player.sought == [10.0]
        player.nowPlaying.emit("LD/05 - Plain.flac")
        shown(qtbot, bridge, lyrics.PLAIN)
        bridge.seekLine(0)
        assert player.sought == [10.0] and bridge.property("current") == -1
    finally:
        bridge.close()


def test_add_saves_an_lrc_beside_the_song_and_edit_saves_into_the_lrc_it_has(music, qtbot):
    """R17.3.1, R17.5: Add… opens an empty text; Save writes it beside the song as its `.lrc`
    (R13.11's default) and the song shows it; Edit… opens the lyrics with their times, and Save
    writes the `.lrc` they came from, the old one to the trash."""
    player, bridge, _ = make(music, on=True)
    try:
        player.nowPlaying.emit("LD/06 - None.flac")
        shown(qtbot, bridge, lyrics.MISSING_STATE)
        assert bridge.property("canEdit") and not bridge.property("editing")
        bridge.add()
        assert bridge.property("editing") and bridge.property("adding")
        assert bridge.property("editTitle") == "Add lyrics · Signal Fires"
        assert bridge.property("editText") == "" and not bridge.property("canSave")
        assert bridge.property("saveLater") == "Nothing has changed yet"
        bridge.setText("[00:01.00]new words")
        assert bridge.property("canSave")
        assert bridge.property("editWhere") == "Saved beside the song as 06 - None.lrc"
        bridge.save()
        qtbot.waitUntil(lambda: not bridge.property("editing"), timeout=WAIT)
        shown(qtbot, bridge, lyrics.TIMED)
        with open(os.path.join(music, "LD", "06 - None.lrc"), "rb") as f:
            assert f.read() == b"[00:01.00]new words\n"
        player.nowPlaying.emit("LD/04 - Signal Fires.flac")
        shown(qtbot, bridge, lyrics.TIMED)
        bridge.edit()
        assert bridge.property("editText") == LRC and not bridge.property("adding")
        bridge.setText(LRC + "\n[00:40.00]more")
        bridge.save()
        qtbot.waitUntil(lambda: not bridge.property("editing"), timeout=WAIT)
        qtbot.waitUntil(lambda: len(bridge.property("lines")) == 4, timeout=WAIT)
        with open(os.path.join(music, "LD", "04 - Signal Fires.lrc"), encoding="utf-8") as f:
            assert f.read() == LRC + "\n[00:40.00]more\n"
        assert bridge._trash.got == ["04 - Signal Fires.lrc"]  # the old one (Principle 5)
    finally:
        bridge.close()


def test_saving_into_the_tags_as_the_setting_says_and_an_empty_text_removes_them(music, qtbot):
    """R13.11: `tags` writes the song's tags, `both` its tags and an `.lrc`; saved empty, the
    lyrics are taken out of where they are."""
    setting = ["tags"]
    player, bridge, _ = make(music, on=True, setting=lambda: setting[0])
    plain = os.path.join(music, "LD", "05 - Plain.flac")
    try:
        player.nowPlaying.emit("LD/05 - Plain.flac")
        shown(qtbot, bridge, lyrics.PLAIN)
        bridge.edit()
        assert bridge.property("editWhere") == "Saved in the song's tags"
        bridge.setText("other words")
        bridge.save()
        qtbot.waitUntil(lambda: bridge.property("plainText") == "other words", timeout=WAIT)
        assert tags.read(plain)[0].lyrics == "other words"
        assert not os.path.exists(os.path.join(music, "LD", "05 - Plain.lrc"))
        setting[0] = "both"
        bridge.edit()
        bridge.setText("[00:02.00]both")
        bridge.save()
        shown(qtbot, bridge, lyrics.TIMED)
        assert tags.read(plain)[0].lyrics == "[00:02.00]both"
        assert os.path.exists(os.path.join(music, "LD", "05 - Plain.lrc"))
        bridge.edit()
        bridge.setText("")
        assert bridge.property("editWhere") == "Saving with no text removes the lyrics"
        bridge.save()
        shown(qtbot, bridge, lyrics.MISSING_STATE)
        assert tags.read(plain)[0].lyrics is None
        assert not os.path.exists(os.path.join(music, "LD", "05 - Plain.lrc"))
    finally:
        bridge.close()


def test_a_save_that_fails_says_why_and_save_tries_again(music, qtbot):
    """R4.7: the editor stays open, saying which file wasn't saved and why."""
    failing = [True]

    def write(job):
        if failing[0]:
            raise WriteError(job.path, "it is read-only: let it be written to, then try again")
        return write_song(job)

    player, bridge, _ = make(music, on=True, setting=lambda: "tags")
    bridge._write = write
    try:
        player.nowPlaying.emit("LD/05 - Plain.flac")
        shown(qtbot, bridge, lyrics.PLAIN)
        bridge.edit()
        bridge.setText("x")
        bridge.save()
        assert bridge.property("saving") and bridge.property("saveLater") == "Saving…"
        bridge.cancel()  # nothing while it saves
        qtbot.waitUntil(lambda: not bridge.property("saving"), timeout=WAIT)
        assert bridge.property("editing")
        assert bridge.property("editProblem") == (
            "1 file wasn't saved: 05 - Plain.flac it is read-only: let it be written to, then"
            " try again"
        )  # fmt: skip
        failing[0] = False
        bridge.save()
        qtbot.waitUntil(lambda: not bridge.property("editing"), timeout=WAIT)
        assert bridge.property("editProblem") == ""
    finally:
        bridge.close()


def test_nothing_is_saved_while_the_root_isnt_there_or_for_a_song_outside_it(music, qtbot):
    """R2.10: saving waits for the root; a file played from outside the library has none saved."""
    there = [False]
    player, bridge, _ = make(music, on=True, available=lambda: there[0])
    try:
        player.nowPlaying.emit("LD/04 - Signal Fires.flac")
        shown(qtbot, bridge, lyrics.TIMED)
        bridge.edit()
        bridge.setText("x")
        assert bridge.property("saveLater") == lyrics.NOT_THERE and not bridge.property("canSave")
        bridge.save()  # nothing
        assert bridge.property("editing")
        bridge.cancel()
        assert not bridge.property("editing")
        outside = os.path.join(music, "LD", "04 - Signal Fires.flac")
        player.nowPlaying.emit(outside)  # a whole path: played from outside the root
        shown(qtbot, bridge, lyrics.TIMED)
        assert not bridge.property("canEdit")
        there[0] = True
        bridge.edit()
        bridge.setText("y")
        assert bridge.property("saveLater") == lyrics.NOT_HERE
    finally:
        bridge.close()


def test_the_tour_turns_the_switch_on_at_a_place_and_off_and_keeps_nothing(music, qtbot):
    player, bridge, kept = make(music)
    try:
        player.nowPlaying.emit("LD/04 - Signal Fires.flac")
        bridge.go({"lyrics": {"at": 31}})
        shown(qtbot, bridge, lyrics.TIMED)
        assert bridge.property("on") and bridge.property("current") == 2
        bridge.go({})
        assert not bridge.property("on") and kept == []
    finally:
        bridge.close()
    bridge.toggle()  # closed: nothing read, nothing kept
    bridge.reread()
    assert kept == []


def test_what_ends_after_the_window_closed_changes_nothing(music, qtbot):
    """A read or a save that ends once the window has closed is passed by (A1.3)."""
    player, bridge, _ = make(music, on=True)
    player.nowPlaying.emit("LD/04 - Signal Fires.flac")
    bridge.close()
    bridge._on_done(Outcome())
    bridge._on_loaded(bridge._ticket, lyrics.Loaded("x", None, None, False))
    assert bridge.property("lines") == [] and not bridge.property("editing")
    gone = lyrics.load(os.path.join(music, "LD", "gone.flac"))
    assert gone.found is None and gone.lrc is None and not gone.tagged


# ---------- in the app ----------


def songs(index, root):
    """Glass Harbor's two songs in the index (fake files: the engine plays nothing), the first
    with timed lyrics beside it."""
    folder = root / "Lumen Drift" / "Glass Harbor"
    folder.mkdir(parents=True)
    (folder / "01.lrc").write_text(LRC + "\n[00:40.00]" + "a long line " * 12, encoding="utf-8")
    rows = []
    for t in (1, 2):
        path = f"Lumen Drift/Glass Harbor/{t:02d}.flac"
        tags_ = Tags(title=f"Song {t}", artist="Lumen Drift", album="Glass Harbor", track=t)
        info = AudioInfo("flac", 200.0, 900_000, 44_100, 2, 16)
        rows.append(scanner.Read(scanner.Seen(path, 10, 1), tags_, info, path))
    index.write(lambda c: scanner.write_batch(c, rows, {}, {})).result()


@pytest.fixture
def shell(tmp_path, qapp):
    root = tmp_path / "Music"
    root.mkdir()
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    settings.set_appearance(settings.shared_path(env), str(tmp_path), "PC", visualization="none")
    s = app.load(str(root), env, FakeClock(), lambda: ThreadPoolExecutor(1), FakeEngine)
    songs(s.index, root)
    s.library.reload()
    s.window.show()
    s.root = root
    yield s
    s.close()


def find(shell, name):
    found = []

    def walk(item):
        if item.objectName() == name:
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    picked = [i for i in found if i.isVisible()] or found
    assert len(picked) == 1, (name, found)
    return picked[0]


def click(shell, item, x=None, y=None):
    at = item.mapToScene(QPointF(item.width() / 2 if x is None else x,
                                 item.height() / 2 if y is None else y)).toPoint()  # fmt: skip
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


def line_item(item, index):
    """The row of a lyrics list at `index`."""
    if item.property("past") is not None and item.property("index") == index:
        return item
    for child in item.childItems():
        found = line_item(child, index)
        if found is not None:
            return found
    return None


def settle(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.tints.wait()
    shell.window.grabWindow()


@pytest.mark.slow
@pytest.mark.parametrize("mode", ["none", "waveform", "analyzer"])
def test_the_switch_shows_the_lyrics_in_each_mode_with_no_warning_and_text_in_its_boxes(
    shell, qtbot, qtlog, mode
):
    """R17.3, N04: the lyrics in the queue's place with No visualization, in Up next's with
    Waveform, the line sung and the next over the analyzer with 3D analyzer."""
    words = shell.lyrics
    shell.player.go({"queue": "Glass Harbor"})
    shell.now.go({"nowPlaying": mode})
    settle(shell, qtbot)
    switch = find(shell, "lyricsSwitch")
    assert switch.property("later") == "" and not switch.property("open")
    click(shell, switch)
    qtbot.waitUntil(lambda: words.property("state") == lyrics.TIMED, timeout=WAIT)
    settle(shell, qtbot)
    assert switch.property("open")
    panel = {"none": "queueLyrics", "waveform": "waveLyrics"}.get(mode)
    if panel is not None:
        assert find(shell, panel).isVisible()
        hidden = "nowQueue" if mode == "none" else "nowUpNext"
        assert not find(shell, hidden).isVisible()
        assert find(shell, "findLyrics").property("later") == lyrics.FIND_LATER
    else:
        assert find(shell, "analyzerLyrics").isVisible()
        assert find(shell, "analyzerNextLine").property("text") == "Lanterns on the water line"
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []
    click(shell, switch)
    qtbot.waitUntil(lambda: not words.property("on"), timeout=WAIT)


@pytest.mark.slow
def test_a_line_clicked_seeks_the_song_and_the_switch_is_kept(shell, qtbot, tmp_path):
    words, p = shell.lyrics, shell.player
    p.go({"queue": "Glass Harbor"})
    p.toggle()  # plays: the fake's 0:42
    qtbot.waitUntil(lambda: p.property("length") == 42, timeout=WAIT)
    shell.now.go({"nowPlaying": "none"})
    words.toggle()
    qtbot.waitUntil(lambda: words.property("state") == lyrics.TIMED, timeout=WAIT)
    settle(shell, qtbot)
    row = line_item(find(shell, "lyricsLines"), 2)
    click(shell, row, 40)
    qtbot.waitUntil(lambda: p.property("position") == 30.0, timeout=WAIT)
    qtbot.waitUntil(lambda: words.property("current") == 2, timeout=WAIT)
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    path = settings.shared_path(env)
    qtbot.waitUntil(
        lambda: settings.load(path, str(tmp_path)).appearance.lyrics is True, timeout=WAIT
    )
    p.go({})
    p.clearQueue()


@pytest.mark.slow
def test_edit_saves_one_history_entry_whose_undo_puts_the_lyrics_back(shell, qtbot, qtlog):
    """R17.5, R4.9: Edit… opens the editor over the window; Save writes the `.lrc`, the message
    offers Undo, and Undo puts the old lyrics back, which Now Playing shows again."""
    words, history = shell.lyrics, shell.changes
    lrc = shell.root / "Lumen Drift" / "Glass Harbor" / "01.lrc"
    before = lrc.read_bytes()
    shell.player.go({"queue": "Glass Harbor"})
    shell.now.go({"nowPlaying": "waveform"})
    words.toggle()
    qtbot.waitUntil(lambda: words.property("state") == lyrics.TIMED, timeout=WAIT)
    settle(shell, qtbot)
    click(shell, find(shell, "editLyrics"))
    qtbot.waitUntil(lambda: find(shell, "lyricsEditor").isVisible(), timeout=WAIT)
    assert words.property("editTitle") == "Edit lyrics · Song 1"
    area = find(shell, "lyricsText")
    assert area.property("text") == before.decode().strip()
    settle(shell, qtbot)
    assert layout.faults(shell.window) == []
    area.setProperty("text", "[00:01.00]edited")
    qtbot.waitUntil(lambda: words.property("canSave"), timeout=WAIT)
    click(shell, find(shell, "saveLyrics"))
    qtbot.waitUntil(lambda: not words.property("editing"), timeout=WAIT)
    qtbot.waitUntil(lambda: bool(history.property("message").get("undo")), timeout=WAIT)
    assert lrc.read_bytes() == b"[00:01.00]edited\n"
    qtbot.waitUntil(lambda: words.property("lines")[0]["text"] == "edited", timeout=WAIT)
    history.undoMessage()
    qtbot.waitUntil(lambda: lrc.read_bytes() == before, timeout=WAIT)
    qtbot.waitUntil(lambda: words.property("lines")[0]["text"] != "edited", timeout=WAIT)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    click(shell, find(shell, "editLyrics"))
    qtbot.waitUntil(lambda: words.property("editing"), timeout=WAIT)
    QTest.keyClick(shell.window, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not words.property("editing"), timeout=WAIT)


@pytest.mark.slow
def test_a_song_without_lyrics_says_so_and_offers_add(shell, qtbot):
    """R17.3.1."""
    words = shell.lyrics
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    shell.now.go({"nowPlaying": "none"})
    words.toggle()
    qtbot.waitUntil(lambda: words.property("state") == lyrics.MISSING_STATE, timeout=WAIT)
    settle(shell, qtbot)
    said = find(shell, "lyricsSaid")
    assert said.isVisible() and said.property("text") == lyrics.MISSING
    add = find(shell, "editLyrics")
    assert add.property("label") == "Add…"
    click(shell, add)
    qtbot.waitUntil(lambda: words.property("editing") and words.property("adding"), timeout=WAIT)
    click(shell, find(shell, "cancelLyrics"))
    qtbot.waitUntil(lambda: not words.property("editing"), timeout=WAIT)
