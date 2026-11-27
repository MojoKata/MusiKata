"""Fix encoding… in the running app (src/musikata/encodings.py, FixEncodingDialog.qml, and its
group in src/musikata/attention.py and its item in the Edit tags panel's ⋯ menu; R4.10, R2.8,
T06-fix-encoding): what the dialog says, the reading chosen for a song or its album, the preview,
the save as Unicode through the batch and the change history, and Undo putting the old bytes back.

Why: the dialog is how the user turns gibberish back into their tags; a reading offered wrongly,
a save that writes the wrong songs, or an Undo that writes Unicode where the file held other bytes,
would lose what the tags said."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import mutagen.id3
import mutagen.wave
import pytest
from fakes import FakeClock, wav
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, layout, tour
from musikata.attention import GROUPS, AttentionModel, chips_of, entry_row, group_row, rows_of
from musikata.bulktools import menu_of
from musikata.encodings import (
    FixEncoding,
    columns_of,
    description_of,
    first_flagged,
    footer_text,
    reading_rows,
    title_text,
    whole_text,
)
from musikata.history import ChangeHistory
from musikata_core import attention, db, encodings, history, ratings, scanner, settings
from musikata_core import tags as tags_core
from musikata_core.attention import Entry
from musikata_core.tags import Tags

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
NOW = datetime(2026, 11, 26, 21, 0, tzinfo=UTC)
BY = {g.key: g for g in GROUPS}


def cp1251(text):
    return text.encode("cp1251").decode("latin-1")


# ---------- what it says ----------


def test_the_dialog_says_its_file_its_readings_and_what_saving_writes_as_t06_does():
    assert title_text("Ñåâåðíûé Âåòåð/Òèõàÿ Ãàâàíü/08 - Ìàÿê.mp3") == "Fix encoding · 08 - Ìàÿê.mp3"
    assert title_text("") == "Fix encoding"
    values = [cp1251(t) for t in ("Северный Ветер", "Тихая Гавань", "Маяк")]
    rows = reading_rows(encodings.readings(values), 0, True)
    assert [(r["label"], r["badge"], r["readable"], r["chosen"]) for r in rows[:2]] == [
        ("Cyrillic (Windows-1251)", "Most likely", True, True),
        ("As it is (Latin-1)", "", True, False),
    ]
    assert rows[0]["texts"] == ["Северный Ветер", "Тихая Гавань", "Маяк"]
    assert rows[-1] == {
        "label": "Chinese (GBK, Big5)", "badge": "", "texts": [], "readable": False,
        "note": "Can't be read this way", "chosen": False,
    }  # fmt: skip
    assert reading_rows(encodings.readings(values), 1, False)[0]["badge"] == ""
    assert columns_of(("artist", "album", "title")) == [
        {"name": "artist", "label": "Artist"}, {"name": "album", "label": "Album"},
        {"name": "title", "label": "Title"},
    ]  # fmt: skip
    assert whole_text(9, True) == "The same for every song of the album (9 songs)"
    assert whole_text(4, False) == "The same for every song edited (4 songs)"
    assert footer_text(9, ["artist", "album", "title"]) == (
        "9 files · artist, album and title · written as Unicode; Undo puts the old bytes back"
    )
    assert footer_text(1, ["title"], undoable=False) == (
        "1 file · title · written as Unicode; the change history is off, so Undo can't put the"
        " old bytes back"
    )
    assert footer_text(0, []) == "Nothing will change"
    assert description_of("Cyrillic (Windows-1251)", 9) == (
        "Fix encoding: Cyrillic (Windows-1251) on 9 songs"
    )
    plain = (1, "a.mp3", Tags(title="Plain"))
    held = (2, "b.mp3", Tags(title=cp1251("Маяк"), latin1=("title",)))
    assert first_flagged([plain, held]) == held and first_flagged([plain]) is None


def test_needs_attention_lists_a_song_in_the_wrong_encoding_as_read_with_fix_encoding():
    """R2.8: "Tags in the wrong text encoding", its chip Wrong encoding (L09), each entry named as
    its likely encoding reads it, with Fix encoding… and Ignore; the group's line has Fix
    encoding… too."""
    e = Entry(attention.ENCODING, "SV/TG/08.mp3", "Маяк", "Северный Ветер", 3, 8, "t",
              fields=("title", "artist", "album"), key="cp1251",
              album_title="Тихая Гавань")  # fmt: skip
    row = entry_row(e)
    assert (row["title"], row["detail"], row["icon"]) == (
        "Маяк", "Северный Ветер · Тихая Гавань · Reads as Cyrillic (Windows-1251)", "album"
    )  # fmt: skip
    assert [a["name"] for a in row["actions"]] == ["fix", "ignore"]
    assert row["actions"][0]["label"] == "Fix encoding…"
    loose = entry_row(Entry(attention.ENCODING, "x.mp3", "Маяк", key="cp1251"))
    assert loose["icon"] == "file" and loose["detail"] == "Reads as Cyrillic (Windows-1251)"
    group = group_row(BY["encoding"], [e], False)
    assert group["title"] == "Wrong encoding" and group["actions"][0]["name"] == "fix"
    assert group["summary"] == "1 song · Маяк"
    assert {c["name"]: c["label"] for c in chips_of({"encoding": 2}, "all")}["encoding"] == (
        "Wrong encoding  2"
    )
    assert rows_of([e], "encoding", ()) == [("group", "encoding", -1), ("entry", "encoding", 0)]


def test_the_panels_menu_has_fix_encoding_when_its_songs_need_it():
    """R4.10: Fix encoding… beside the bulk tools, for songs with text in the wrong encoding;
    as the tools, it waits on changes not saved and on a save going on."""
    assert "encoding" not in [t["name"] for t in menu_of(3, False, False)]
    item = menu_of(3, False, False, True)[-1]
    assert item == {"name": "encoding", "label": "Fix encoding…", "later": ""}
    assert menu_of(3, True, False, True)[-1]["later"] == "Save or revert your changes first"
    assert menu_of(3, False, True, True)[-1]["later"] == "A save is going on"


# ---------- the dialog over a root ----------


def misread(path, title, track):
    """An MP3-like WAV of Тихая Гавань, its tags Windows-1251 in Latin-1 frames (ID3v2.3)."""
    wav(path, track)
    f = mutagen.wave.WAVE(str(path))
    f.add_tags()
    for fid, text in (("TIT2", title), ("TPE1", "Северный Ветер"), ("TALB", "Тихая Гавань")):
        f.tags.add(getattr(mutagen.id3, fid)(encoding=0, text=cp1251(text)))
    f.tags.add(mutagen.id3.TRCK(encoding=0, text=str(track)))
    f.save(v2_version=3)
    return str(path)


def frames(path):
    codecs = {0: "latin-1", 1: "utf-16", 3: "utf-8"}
    t = mutagen.wave.WAVE(path).tags
    return {f.FrameID: (int(f.encoding), str(f.text[0]).encode(codecs[int(f.encoding)]))
            for f in t.values() if f.FrameID in ("TIT2", "TPE1", "TALB")}  # fmt: skip


@pytest.fixture
def root(tmp_path):
    """Тихая Гавань's three songs misread, and a song in Unicode, scanned: (root, index,
    paths)."""
    music = tmp_path / "Music"
    folder = music / "SV" / "TG"
    paths = [misread(folder / f"0{n}.wav", t, n) for n, t in ((1, "Утро"), (2, "Огни"),
                                                             (8, "Маяк"))]  # fmt: skip
    wav(music / "u.wav", 9, "Маяк")
    index = db.Index(str(tmp_path / "musikata.db"))
    with ThreadPoolExecutor(1) as pool:
        scanner.scan(str(music), index, pool, hold=False)
    yield str(music), index, paths
    index.close()


def write_file(job):
    return tags_core.save(job.path, job.changes, audio_hash=scanner.audio_hash)


def make(music, index, qtbot, **kw):
    w = ratings.Writing(music, index, write_file, True, FakeClock(NOW))
    h = ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop", settings.RootTags(),
                      executor=ThreadPoolExecutor(1), watching=False, message_ms=60_000, write=w,
                      look=history.looking(w.kept))  # fmt: skip
    model = AttentionModel(index.read)
    model.refresh()

    def saved(written):
        index.write(lambda c: scanner.wrote(c, music, written)).result()

    f = FixEncoding(music, index.read, w, h, saved=saved, executor=ThreadPoolExecutor(1),
                    model=model, **kw)  # fmt: skip
    f.model_, f.history_ = model, h
    return f


def opened(f, qtbot, open_):
    with qtbot.waitSignal(f.changed, timeout=WAIT,
                          check_params_cb=lambda: not f.property("loading")):  # fmt: skip
        open_()


def test_fix_encoding_reads_the_song_and_its_album_and_saves_the_reading_chosen(root, qtbot):
    """R4.10 through the bridge: from Needs attention's entry, the song's readings with its
    album's songs; the reading chosen and the album's checkbox change the plan; Save writes the
    album as Unicode as one entry, whose Undo puts the old bytes back."""
    music, index, paths = root
    f = make(music, index, qtbot)
    model, h = f.model_, f.history_
    try:
        before = {p: frames(p) for p in paths}
        e = model.entry_of_kind(attention.ENCODING, "Маяк")
        assert e is not None and e.about == "SV/TG/08.wav"
        assert f.property("opened") is False and f.property("readings") == []
        opened(f, qtbot, lambda: f.open(e))
        assert f.property("title") == "Fix encoding · 08.wav"
        assert f.property("about").startswith("These tags were saved as Latin-1")
        assert [c["name"] for c in f.property("columns")] == ["artist", "album", "title"]
        rows = f.property("readings")
        assert rows[0]["label"] == "Cyrillic (Windows-1251)" and rows[0]["badge"] == "Most likely"
        assert rows[0]["texts"] == ["Северный Ветер", "Тихая Гавань", "Маяк"]
        assert f.property("whole") and f.property("wholeText") == (
            "The same for every song of the album (3 songs)"
        )
        assert f.property("footer") == (
            "3 files · artist, album and title · written as Unicode; Undo puts the old bytes back"
        )
        assert f.property("saveLabel") == "Save 3 files" and f.property("saveLater") == ""
        f.choose(len(rows) - 1)  # Greek can't read it: nothing changes
        assert f.property("readings")[0]["chosen"]
        f.toggleWhole()
        assert f.property("saveLabel") == "Save 1 file" and not f.property("whole")
        f.toggleWhole()
        f.toggleFiles()
        assert f.property("showFiles")
        assert f.property("preview").property("total") == 3
        f.toggleFiles()
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            f.save()
            assert f.property("saving") and f.property("footer").startswith("Saving")
            assert f.property("saveLater") == "A save is going on"
        assert not f.property("opened") and not f.property("saving")
        assert all({k: v[0] for k, v in frames(p).items()} == dict.fromkeys(
            ("TIT2", "TPE1", "TALB"), 3) for p in paths)  # fmt: skip
        assert tags_core.read(paths[2])[0].title == "Маяк"
        c = index.read()
        assert c.execute("SELECT COUNT(*) FROM song WHERE encoding IS NOT NULL").fetchone() == (0,)
        qtbot.waitUntil(lambda: c.execute("SELECT COUNT(*) FROM change").fetchone()[0] == 1,
                        timeout=WAIT)  # fmt: skip
        (name, action, description) = c.execute(
            "SELECT name, action, description FROM change"
        ).fetchone()
        assert (action, description) == ("encoding", "Fix encoding: Cyrillic (Windows-1251) on"
                                                     " 3 songs")  # fmt: skip
        with open(os.path.join(history.folder_of(music), name), encoding="utf-8") as fh:
            doc = json.load(fh)
        assert all(x["latin1"] == ["title", "artist", "album"] for x in doc["files"])
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            h.undoMessage()
        qtbot.waitUntil(lambda: "Undone" in h.property("message").get("text", ""), timeout=WAIT)
        assert {p: frames(p) for p in paths} == before
    finally:
        f.shut()
        h.close()


def test_as_it_is_writes_the_same_text_as_unicode_and_a_song_with_nothing_to_fix_says_so(
    root, qtbot
):
    music, index, paths = root
    f = make(music, index, qtbot)
    try:
        ids = dict(index.read().execute("SELECT path, id FROM song"))
        opened(f, qtbot, lambda: f.open_songs([ids["u.wav"]]))  # Unicode: nothing to fix
        assert f.property("opened") and f.property("about") == "Nothing to fix"
        assert f.property("saveLater") == "Nothing to fix" and f.property("readings") == []
        f.save()  # nothing to save
        f.close()
        assert not f.property("opened")
        opened(f, qtbot, lambda: f.open_songs([ids["u.wav"], ids["SV/TG/02.wav"]]))
        # the songs edited are what the checkbox covers: the one in Unicode stays as it is
        assert f.property("wholeText") == "The same for every song edited (2 songs)"
        rows = f.property("readings")
        f.choose(next(n for n, r in enumerate(rows) if r["label"] == "As it is (Latin-1)"))
        assert f.property("footer").startswith("1 file · artist, album and title")
        with qtbot.waitSignal(f.changed, timeout=WAIT, check_params_cb=lambda: not f.property(
                "saving") and not f.property("opened")):  # fmt: skip
            f.save()
        t, _ = tags_core.read(paths[1])
        assert t.title == cp1251("Огни") and t.latin1 == ()
    finally:
        f.shut()
        f.history_.close()


def test_a_fix_that_fails_names_the_file_with_why_and_retry_saves_it(root, qtbot):
    music, index, paths = root
    f = make(music, index, qtbot)
    try:
        e = f.model_.entry_of_kind(attention.ENCODING, "Маяк")
        opened(f, qtbot, lambda: f.open(e))
        os.chmod(paths[0], 0o444)
        with qtbot.waitSignal(f.changed, timeout=WAIT, check_params_cb=lambda: not f.property(
                "saving") and f.property("problem") != ""):  # fmt: skip
            f.save()
        assert f.property("problem").startswith("1 file wasn't saved: 01.wav it is read-only")
        assert f.property("opened") and f.property("saveLabel") == "Retry 1 file"
        assert f.property("saveLater") == ""
        os.chmod(paths[0], 0o644)
        with qtbot.waitSignal(f.changed, timeout=WAIT, check_params_cb=lambda: not f.property(
                "opened")):  # fmt: skip
            f.save()
        assert tags_core.read(paths[0])[0].title == "Утро"
    finally:
        f.shut()
        f.history_.close()


def test_saving_waits_for_the_root_and_the_tour_opens_the_entry_named(root, qtbot):
    music, index, paths = root
    f = make(music, index, qtbot, available=lambda: False)
    try:
        f.go({"view": "attention", "fix": "Нет такой"})  # no such entry: nothing opens
        assert not f.property("opened")
        with qtbot.waitSignal(f.changed, timeout=WAIT, check_params_cb=lambda: f.property(
                "opened") and not f.property("loading")):  # fmt: skip
            f.go({"view": "attention", "fix": "Маяк"})
        assert f.property("saveLater") == "Saving waits until the music folder is back"
        f.save()
        assert not f.property("saving")
        f.go({"view": "albums"})
        assert not f.property("opened")
    finally:
        f.shut()
        f.history_.close()


def test_needs_attentions_fix_and_its_groups_open_the_dialog_and_the_panels_menu_has_it(
    root, qtbot
):
    """The actions reach the dialog: an entry's Fix encoding…, the group's (its first entry),
    and the Edit tags panel's ⋯ menu on songs that need it."""
    from musikata.attention import Attention
    from musikata.edittags import EditTags

    music, index, paths = root
    f = make(music, index, qtbot)
    model = f.model_
    needs = Attention(music, index, model, FakeClock(NOW), encoding=f, watching=False,
                      executor=ThreadPoolExecutor(1))  # fmt: skip
    edit = EditTags(music, index.read, settings.RootTags(), encodings=f)
    try:
        model.choose("encoding")
        assert model.row(0)["type"] == "group" and model.row(1)["kind"] == "wrong-encoding"
        opened(f, qtbot, lambda: needs.act(0, "fix"))  # the group's: its first entry
        assert f.property("title") == "Fix encoding · 01.wav"
        f.close()
        opened(f, qtbot, lambda: needs.act(3, "fix"))
        assert f.property("title") == "Fix encoding · 08.wav"
        f.close()
        ids = [i for (i,) in index.read().execute("SELECT id FROM song ORDER BY path")]
        edit.edit_songs(ids)
        qtbot.waitUntil(lambda: any(t["name"] == "encoding" for t in edit.property("tools")),
                        timeout=WAIT)  # fmt: skip
        opened(f, qtbot, lambda: edit.runTool("encoding"))
        assert f.property("title") == "Fix encoding · 01.wav"
        assert f.property("wholeText") == "The same for every song edited (4 songs)"
    finally:
        edit.close()
        needs.close()
        f.shut()
        f.history_.close()


# ---------- in the window ----------


@pytest.fixture
def shell(root, tmp_path, qapp, qtbot):
    music, index, _paths = root
    index.close()
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(music, env, FakeClock(datetime.now(UTC) - timedelta(minutes=1)),
                 lambda: ThreadPoolExecutor(1))  # fmt: skip
    s.library.rescan()
    qtbot.waitUntil(lambda: not s.library.scanning, timeout=WAIT * 3)
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
def test_fix_encoding_loads_from_needs_attention_with_no_qml_warning_and_its_text_in_its_boxes(
    shell, qtbot, qtlog
):
    """T06 in the window: the group's Fix encoding… opens the dialog over Needs attention, its
    readings and footer drawn whole; a reading clicked is chosen; the files shown; Cancel
    closes it."""
    lib = shell.library
    qtbot.waitUntil(lambda: lib.property("attentionCount") != "", timeout=WAIT)
    lib.show("attention")
    shell.attention.go({"view": "attention", "attention": "encoding"})
    settled(shell, qtbot)
    click(shell, find(shell, "attentionAction-fix")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "fixEncodingDialog")), timeout=WAIT)
    settled(shell, qtbot)
    assert len(find(shell, "fixReading")) == 6 and find(shell, "fixLikely")
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "fixReading")[1])  # as it is
    assert shell.encodings.property("readings")[1]["chosen"]
    click(shell, find(shell, "fixFiles")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "fixPreview")), timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "cancelFix")[0])
    qtbot.waitUntil(lambda: not find(shell, "fixEncodingDialog"), timeout=WAIT)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    json.dumps(shell.encodings.property("readings"))  # plain data
