"""Infer from path in the running app (src/musikata/infer.py, InferDialog.qml, and where it opens:
Folders' strip, the selection bars and right-click menus, an album's page, the Edit tags panel's ⋯
menu and Needs attention; R3, T01-infer-from-path): what the dialog says, the pattern detected,
edited and picked, fill or correct and the tidying, the preview, and the save through the batch
and the change history, whose Undo puts the old tags back.

Why: the dialog is where tags are rewritten from paths for a whole folder or library at once; a
pattern detected wrongly, an option that doesn't reach the plan, or a save that writes files the
user unchecked, would rewrite the tags of every file it fits."""

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
from musikata.history import ChangeHistory
from musikata.infer import (
    InferFromPath,
    about_text,
    checks_of,
    choices_of,
    description_of,
    modes_of,
    parts_of,
    picker_text,
    tidy_text,
    tokens_of,
    year_text,
)
from musikata_core import attention, db, history, patterns, ratings, scanner, settings
from musikata_core import tags as tags_core
from musikata_core.attention import Entry
from musikata_core.patterns import Fit, Options, parse
from musikata_core.tags import Tags
from musikata_core.tags.tools import Planned, Song

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
NOW = datetime(2026, 11, 26, 21, 0, tzinfo=UTC)
LD = "Lumen Drift"


# ---------- what it says ----------


def test_the_dialog_says_what_it_does_under_the_root_as_t01_does():
    assert about_text("/home/me/Music", "/home/me") == (
        "Read each file's path under ~/Music, and fill or correct its tags from it. Nothing is"
        " written until you save."
    )
    assert "under /srv/Music," in about_text("/srv/Music", "/home/me")
    assert "under /home/meme/Music," in about_text("/home/meme/Music", "/home/me")
    assert "under ~," in about_text("/home/me", "/home/me")


def test_the_picker_says_detected_and_how_many_fit_and_lists_every_pattern_with_its_count():
    """R3.4: "Detected · 9 of 9 fit"; another pattern its count; one typed that can't be used,
    why."""
    assert picker_text(9, 9, True) == "Detected · 9 of 9 fit"
    assert picker_text(7, 9, False) == "7 of 9 fit"
    assert picker_text(0, 9, False, "A brace isn't closed") == "A brace isn't closed"
    fits = [Fit(parse("{artist} - {title}"), 3), Fit(parse("{title}"), 1)]
    assert choices_of(fits, 3, "{title}") == [
        {"text": "{artist} - {title}", "label": "3 of 3 fit", "chosen": False},
        {"text": "{title}", "label": "1 of 3 fit", "chosen": True},
    ]


def test_the_field_shows_its_tokens_as_chips_and_the_tokens_below_it_are_r3_2s():
    """R3.4.1, T01: each token a chip, the text between as written; below, each token."""
    assert parts_of(parse("{artist}/{album}/{track} - {title}")) == [
        {"kind": "token", "text": "{artist}"}, {"kind": "text", "text": "/"},
        {"kind": "token", "text": "{album}"}, {"kind": "text", "text": "/"},
        {"kind": "token", "text": "{track}"}, {"kind": "text", "text": " - "},
        {"kind": "token", "text": "{title}"},
    ]  # fmt: skip
    assert parts_of(parse("{artist} - {title")) == []
    assert tokens_of() == ["{artist}", "{albumartist}", "{album}", "{year}", "{disc}", "{track}",
                           "{title}", "{genre}", "{*}"]  # fmt: skip


def test_the_options_say_what_they_do_with_an_example_as_t01_does():
    """R3.5's radio buttons, R3.6's checkboxes: Tidy case with a value it changes only in case,
    Year from folder with the year the folders name most, Underscores as spaces only when a path
    has one."""
    song = Song("/m/a.flac", Tags(artist="lumen drift", title="x"))
    planned = Planned(("artist",), (song,), (Tags(artist=LD, title="x"),))
    assert tidy_text(planned) == "Tidy case (lumen drift → Lumen Drift)"
    assert tidy_text(Planned(("title",), (song,), (Tags(artist="lumen drift", title="Y"),))) == (
        "Tidy case"
    )
    assert year_text([2022, None, 2022, 2021]) == "Year from folder (2022)"
    assert year_text([None]) == "Year from folder"
    checks = checks_of(Options(), planned, [2022], underscores=False)
    assert [(c["name"], c["on"]) for c in checks] == [
        ("tidy_case", True), ("year_from_folder", True), ("track_total", False)]  # fmt: skip
    assert checks[1]["label"] == "Year from folder (2022)"
    assert "underscores" in [c["name"] for c in checks_of(Options(), planned, [], True)]
    assert modes_of(Options()) == [
        {"name": "fill", "label": "Only fill empty tags", "chosen": False},
        {"name": "correct", "label": "Correct tags that differ", "chosen": True},
    ]
    assert modes_of(Options(fill_only=True))[0]["chosen"]
    assert description_of(["artist", "year"], 4) == "Infer from path: Artist and Year on 4 songs"


# ---------- the dialog over a root ----------


def tagged(path, seed, **frames):
    """A WAV with ID3 frames, by their ids (TPE1 the artist, TPE2 the album artist, …)."""
    wav(path, seed)
    f = mutagen.wave.WAVE(str(path))
    f.add_tags()
    for fid, text in frames.items():
        f.tags.add(getattr(mutagen.id3, fid)(encoding=3, text=str(text)))
    f.save()
    return str(path)


@pytest.fixture
def root(tmp_path):
    """Tide Tables, four songs: two whose tags match their paths, one with its album artist in
    lower case, one with no tags; and a loose file no pattern fits. (root, index, paths)."""
    music = tmp_path / "Music"
    folder = music / LD / "Tide Tables"
    paths = [
        tagged(folder / "01 - Neap Tide.wav", 1, TIT2="Neap Tide", TPE2=LD, TALB="Tide Tables",
               TRCK=1),
        tagged(folder / "02 - Spring Tide.wav", 2, TIT2="Spring Tide", TPE2=LD,
               TALB="Tide Tables", TRCK=2),
        tagged(folder / "03 - Slack Water.wav", 3, TIT2="Slack Water", TPE2="lumen drift",
               TALB="Tide Tables", TRCK=3),
        tagged(folder / "04 - Moonpull.wav", 4),
        tagged(folder / "stray.wav", 5, TIT2="Stray"),
    ]  # fmt: skip
    index = db.Index(str(tmp_path / "musikata.db"))
    with ThreadPoolExecutor(1) as pool:
        scanner.scan(str(music), index, pool, hold=False)
    yield str(music), index, paths
    index.close()


def write_file(job):
    return tags_core.save(job.path, job.changes, audio_hash=scanner.audio_hash)


def make(music, index, **kw):
    w = ratings.Writing(music, index, write_file, True, FakeClock(NOW))
    h = ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop", settings.RootTags(),
                      executor=ThreadPoolExecutor(1), watching=False, message_ms=60_000, write=w,
                      look=history.looking(w.kept))  # fmt: skip

    def saved(written):
        index.write(lambda c: scanner.wrote(c, music, written)).result()

    i = InferFromPath(music, index.read, w, h, saved=saved, executor=ThreadPoolExecutor(1), **kw)
    i.history_ = h
    return i


def opened(i, qtbot, open_):
    with qtbot.waitSignal(i.changed, timeout=WAIT,
                          check_params_cb=lambda: not i.property("loading")):  # fmt: skip
        open_()


def cells(i, row):
    preview = i.property("preview")
    r = preview.row(row)
    return r["file"], r["note"], [(c["old"], c["new"]) for c in r["cells"] if c["changed"]]


def test_infer_from_path_detects_the_pattern_previews_and_saves_one_entry_undo_puts_back(
    root, qtbot
):
    """R3 through the bridge, on a folder (R2.9.7): the pattern detected (R3.4), the preview with
    the file it doesn't fit last (R3.7), Save writes the files checked as one entry whose Undo
    puts the old tags back (R3.8, R4.9)."""
    music, index, paths = root
    i = make(music, index)
    h = i.history_
    try:
        assert i.property("opened") is False and i.property("picker") == ""
        i.close()  # nothing open: nothing to close
        opened(i, qtbot, lambda: i.open_folder("Lumen Drift/Tide Tables"))
        assert i.property("opened") and i.property("title") == "Infer tags from path"
        assert i.property("pattern") == patterns.PRESETS[4]
        assert i.property("detected") and i.property("picker") == "Detected · 4 of 5 fit"
        assert i.property("choices")[0] == {"text": patterns.PRESETS[4], "label": "4 of 5 fit",
                                            "chosen": True}  # fmt: skip
        preview = i.property("preview")
        assert [c["name"] for c in preview.property("columns")] == [
            "albumartist", "album", "track", "title"]  # fmt: skip
        assert cells(i, 2) == ("03 - Slack Water.wav", "", [("lumen drift", LD)])
        assert cells(i, 3)[2] == [("(empty)", LD), ("(empty)", "Tide Tables"), ("(empty)", "4"),
                                  ("(empty)", "Moonpull")]  # fmt: skip
        assert cells(i, 4) == ("stray.wav", "Doesn't fit the pattern", [])
        assert i.property("footer") == (
            "2 files · 5 changes · the old tags are kept, and Undo puts them back"
        )
        assert i.property("saveLabel") == "Save 2 files" and i.property("saveLater") == ""
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            i.save()
            assert i.property("saving") and i.property("footer").startswith("Saving")
            assert i.property("saveLater") == "A save is going on"
            i.setPattern("{title}")  # nothing changes while it saves
        assert not i.property("opened") and not i.property("saving")
        t, _ = tags_core.read(paths[3])
        assert (t.albumartist, t.album, t.track, t.title) == (LD, "Tide Tables", 4, "Moonpull")
        assert tags_core.read(paths[2])[0].albumartist == LD
        c = index.read()
        assert c.execute("SELECT COUNT(*) FROM song WHERE path_state = 1").fetchone() == (0,)
        qtbot.waitUntil(lambda: c.execute("SELECT COUNT(*) FROM change").fetchone()[0] == 1,
                        timeout=WAIT)  # fmt: skip
        name, action, description = c.execute(
            "SELECT name, action, description FROM change").fetchone()  # fmt: skip
        assert (action, description) == (
            "infer",
            "Infer from path: Album artist, Album, Track and Title on 2 songs",
        )
        with open(os.path.join(history.folder_of(music), name), encoding="utf-8") as fh:
            assert len(json.load(fh)["files"]) == 2
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            h.undoMessage()
        qtbot.waitUntil(lambda: "Undone" in h.property("message").get("text", ""), timeout=WAIT)
        assert tags_core.read(paths[2])[0].albumartist == "lumen drift"
        assert tags_core.read(paths[3])[0].title is None
    finally:
        i.shut()
        h.close()


def test_the_pattern_typed_or_picked_and_the_options_change_the_preview(root, qtbot):
    """R3.4.1: the preview follows the pattern as typed; R3.4: a pattern of the picker's list;
    R3.5 and R3.6: the mode and the checkboxes reach the plan."""
    music, index, paths = root
    i = make(music, index)
    try:
        ids = [r[0] for r in index.read().execute("SELECT id FROM song ORDER BY path")]
        opened(i, qtbot, lambda: i.open_songs(ids))
        i.setPattern("{albumartist}/{album}/{track} - {title")
        assert i.property("picker") == "A brace isn't closed" and not i.property("detected")
        assert i.property("saveLater") == "Nothing to save" and i.property("parts") == []
        i.setPattern("{albumartist}/{album}/{track} - {title}")
        assert i.property("detected")
        i.setPattern("{*}/{*}/{track} - {title}")
        assert not i.property("detected") and i.property("picker") == "4 of 5 fit"
        assert [c["name"] for c in i.property("preview").property("columns")] == ["track", "title"]
        i.choosePattern(0)
        assert i.property("detected")
        i.choosePattern(99)  # no such pattern: nothing
        i.setOption("mode", "fill")
        assert i.property("modes")[0]["chosen"]
        assert i.property("preview").counts() == (1, 4)  # Moonpull's, which has no tags
        i.setOption("mode", "correct")
        i.toggle("tidy_case")
        assert not i.property("checks")[0]["on"]
        assert i.property("preview").counts() == (2, 5)  # the path spells "Lumen Drift" itself
        i.toggle("tidy_case")
        i.toggle("track_total")  # the column, but a stray file in the folder: no total
        assert "tracktotal" in [c["name"] for c in i.property("preview").property("columns")]
        assert i.property("preview").counts() == (2, 5)
        i.toggle("track_total")
        i.toggle("underscores")
        i.toggle("nothing")  # no such checkbox: nothing
        with pytest.raises(ValueError, match="no such option"):
            i.setOption("nothing", True)
        assert i.property("preview").counts()[0] == 2
        i.close()
        assert not i.property("opened") and i.property("pattern") == ""
    finally:
        i.shut()
        i.history_.close()


def test_it_opens_on_an_album_a_selection_a_row_and_a_needs_attention_entry(root, qtbot):
    """R3.1: an album's songs, a selection, a right-clicked row's songs or the selection it is
    in, and an entry of Tags that differ from the path."""
    from musikata.folders import FolderModel

    music, index, paths = root
    i = make(music, index)
    try:
        c = index.read()
        album = c.execute("SELECT album_id FROM song WHERE album_id IS NOT NULL").fetchone()[0]
        opened(i, qtbot, lambda: i.openAlbum(album))
        assert i.property("preview").property("total") == 3
        model = FolderModel(index.read)
        model.open("Lumen Drift/Tide Tables")
        qtbot.waitUntil(lambda: model.rowCount() == 5, timeout=WAIT)
        model.click(0, False, False)
        model.click(1, True, False)
        opened(i, qtbot, lambda: i.openSelection(model))
        assert i.property("preview").property("total") == 2
        opened(i, qtbot, lambda: i.openRow(model, 4))
        assert i.property("preview").property("total") == 1
        opened(i, qtbot, lambda: i.openRow(model, 1))  # in the selection: the selection
        assert i.property("preview").property("total") == 2
        e = next(e for e in attention.find(c) if e.kind == attention.PATH)
        opened(i, qtbot, lambda: i.open(e))
        assert i.property("preview").property("total") == 5
        i.close()
        i.open(Entry(attention.UNREADABLE, "x"))  # another kind: nothing opens
        assert not i.property("opened")
        opened(i, qtbot, lambda: i.openFolder("nowhere"))
        assert i.property("saveLater") == "No songs to read" and i.property("picker") == ""
    finally:
        i.shut()
        i.history_.close()


def test_a_save_that_fails_names_the_file_with_why_and_retry_saves_it(root, qtbot):
    music, index, paths = root
    i = make(music, index)
    try:
        opened(i, qtbot, lambda: i.open_folder("Lumen Drift/Tide Tables"))
        os.chmod(paths[2], 0o444)
        with qtbot.waitSignal(i.changed, timeout=WAIT, check_params_cb=lambda: not i.property(
                "saving") and i.property("problem") != ""):  # fmt: skip
            i.save()
        assert i.property("problem").startswith("1 file wasn't saved: 03 - Slack Water.wav")
        assert i.property("opened") and i.property("saveLabel") == "Retry 1 file"
        assert i.property("saveLater") == ""
        os.chmod(paths[2], 0o644)
        with qtbot.waitSignal(i.changed, timeout=WAIT, check_params_cb=lambda: not i.property(
                "opened")):  # fmt: skip
            i.save()
        assert tags_core.read(paths[2])[0].albumartist == LD
    finally:
        i.shut()
        i.history_.close()


def test_saving_waits_for_the_root_and_the_tour_opens_the_folder_it_shows(root, qtbot):
    music, index, paths = root
    i = make(music, index, available=lambda: False)
    try:
        with qtbot.waitSignal(i.changed, timeout=WAIT, check_params_cb=lambda: i.property(
                "opened") and not i.property("loading")):  # fmt: skip
            i.go({"view": "folders", "folder": "Lumen Drift/Tide Tables", "infer": True})
        assert i.property("saveLater") == "Saving waits until the music folder is back"
        i.save()
        assert not i.property("saving")
        i.go({"view": "albums"})
        assert not i.property("opened")
        i.go({"view": "albums"})  # closed already
    finally:
        i.shut()
        i.history_.close()
    i.open_folder("Lumen Drift/Tide Tables")  # shut: nothing opens
    assert not i.property("opened")


def test_the_panels_menu_and_needs_attention_open_the_dialog(root, qtbot):
    """R4.5.5: the Edit tags panel's Infer from path; R2.8: an entry's and its action."""
    from musikata.attention import Attention, AttentionModel
    from musikata.edittags import EditTags

    music, index, paths = root
    i = make(music, index)
    model = AttentionModel(index.read)
    model.refresh()
    needs = Attention(music, index, model, FakeClock(NOW), infer=i, watching=False,
                      executor=ThreadPoolExecutor(1))  # fmt: skip
    edit = EditTags(music, index.read, settings.RootTags(), infer=i)
    try:
        model.choose("paths")
        assert model.row(0)["type"] == "group" and model.row(1)["kind"] == "path-differs"
        assert [a["name"] for a in model.row(1)["actions"]] == ["infer", "ignore"]
        opened(i, qtbot, lambda: needs.act(1, "infer"))
        assert i.property("preview").property("total") == 5
        i.close()
        ids = [r[0] for r in index.read().execute("SELECT id FROM song ORDER BY path")][:2]
        edit.edit_songs(ids)
        qtbot.waitUntil(lambda: edit.property("count") == 2, timeout=WAIT)
        opened(i, qtbot, lambda: edit.runTool("infer"))
        assert i.property("preview").property("total") == 2
    finally:
        edit.close()
        needs.close()
        i.shut()
        i.history_.close()


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
def test_infer_from_path_opens_from_a_folders_strip_with_no_qml_warning_and_its_text_in_its_boxes(
    shell, qtbot, qtlog
):
    """T01 in the window: the strip's Infer from path opens the dialog over the folder, its
    pattern drawn as chips, a token clicked inserted, its footer whole; the strip says how the
    files differ, each file its chip (R2.9.7, R3.9); Cancel closes it."""
    lib = shell.library
    lib.show("folders")
    folders = lib.property("folders")
    folders.open("Lumen Drift/Tide Tables")
    settled(shell, qtbot)
    assert folders.property("pathLine").startswith("The path says")
    assert find(shell, "pathLine") and find(shell, "pathChip")
    click(shell, find(shell, "inferFolder")[0])
    infer = shell.infer
    qtbot.waitUntil(lambda: infer.property("opened") and not infer.property("loading"),
                    timeout=WAIT)  # fmt: skip
    settled(shell, qtbot)
    assert find(shell, "inferDialog") and find(shell, "previewNote")
    assert layout.faults(shell.window) == []
    field = find(shell, "inferPattern")[0]
    click(shell, field)
    field.setProperty("cursorPosition", 0)
    click(shell, find(shell, "inferToken")[-1])  # {*}, inserted at the start
    qtbot.waitUntil(lambda: infer.property("pattern").startswith("{*}"), timeout=WAIT)
    click(shell, find(shell, "inferMode-fill")[0])
    assert infer.property("modes")[0]["chosen"]
    click(shell, find(shell, "cancelInfer")[0])
    qtbot.waitUntil(lambda: not infer.property("opened"), timeout=WAIT)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


def test_the_selection_bars_offer_infer_from_path():
    """R3.1, R2.9.6: Infer from path on Songs' selection bar (L03), Folders' (L06), its
    right-click menu and a folder of songs' strip (L08), first there."""
    from musikata import folders, models

    assert {"label": "Infer from path", "icon": "wand", "later": "",
            "action": "infer"} in models.SONG_LATER  # fmt: skip
    assert folders.INFER in folders.LATER and folders.STRIP[0]["action"] == "infer"
    assert folders.STRIP[0]["primary"] is True
