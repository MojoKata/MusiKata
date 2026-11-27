"""The Edit tags panel in the running app (src/musikata/edittags.py, EditTagsPanel.qml,
TagField.qml; R4.2 to R4.4, R4.6 to R4.8): what it says for one song and for many, opening it from
every place it opens from, following the list's selection and asking first when changes aren't
saved, suggesting the library's values, and saving through the batch and the change history, with
progress, Cancel, the files that failed and Retry, then the message with Undo.

The songs are generated files with an index that has them; tests wait on the signal or state that
says the work is done.

Why: the panel changes many files at once from the GUI thread while the reading and writing
happen on threads of their own; a field that shows the wrong value, a save that writes what the
panel didn't say, a selection change that drops the user's typing, or a failure listed without a
way to try again all cost the user their tags or their trust."""

import json
import os
import shutil
import stat
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import mutagen.id3
import pytest
from fakes import FakeClock, fill
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, edittags, layout, tour
from musikata.edittags import (
    EditTags,
    Song,
    art_chip,
    being_typed,
    change_line,
    description_of,
    details_of,
    failed_rows,
    heading_of,
    is_edit,
    labels_text,
    problem_line,
    progress_text,
    save_label,
    sorted_fields,
    unsaved_text,
    view_field,
    what_text,
    with_suggestion,
)
from musikata.history import ChangeHistory, saved_text
from musikata.models import SongsModel
from musikata_core import db, scanner, settings, tags
from musikata_core.tags import AudioInfo, Failed, Job, Outcome, Tags, Written, edit

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
NOW = datetime(2026, 11, 26, 21, 0, tzinfo=UTC)
TIDE = [  # L03's four songs: title, artist, genre, year
    ("Neap Tide", "Lumen Drift", "Electronica", 2022),
    ("Spring Tide", "Lumen Drift", "electronic", 2022),
    ("Slack Water", "Lumen Drift", "Electronic", None),
    ("Moonpull", "lumen drift", "Electronic", 2022),
]


# ---------- what the panel says ----------


def song(path="LD/TT/01 - Neap Tide.flac", **t):
    fields = {"title": "Neap Tide", "artist": "Lumen Drift", "album": "Tide Tables", **t}
    return Song(1, path, Tags(**fields), "flac", 258.4, 912_000, 44100, 31_200_000, 7, "LD/TT")


def test_what_is_edited_is_the_album_most_songs_are_on_its_artist_and_how_many():
    """R4.2: "Tide Tables · Lumen Drift · 4 songs"; L07's "Mara Okafor · 1 folder, 1 file"."""
    four = [song(), song(), song(artist="lumen drift"), song(album=None)]
    assert heading_of(four, "4 songs") == ("Tide Tables", "Lumen Drift · 4 songs")
    assert heading_of([song()], "1 song") == ("Neap Tide", "Lumen Drift · Tide Tables")
    assert heading_of([song(title=None)], "1 song")[0] == "01 - Neap Tide"
    apart = [song(album="A", artist="X"), song(album="B", artist="Y"), song(album="C")]
    assert heading_of(apart, "3 songs") == ("3 songs", "")
    assert heading_of([], "") == ("", "")
    assert what_text(1, 1) == "1 folder, 1 file" and what_text(2, 0) == "2 folders"
    assert what_text(0, 3) == "3 files" and what_text(0, 0) == "0 files"


def test_what_will_change_is_said_and_saved_in_words():
    """R4.4: "3 fields will change on 4 songs", Save to 4 files; the history's description."""
    assert change_line(3, 4) == "3 fields will change on 4 songs"
    assert change_line(1, 1) == "1 field will change on 1 song" and change_line(0, 4) == ""
    assert save_label(4) == "Save to 4 files" and save_label(1) == "Save to 1 file"
    assert save_label(0) == "Save"
    assert labels_text(["artist"]) == "Artist" and labels_text([]) == ""
    assert description_of(["artist", "genres", "year"], 4) == "Artist, Genre and Year on 4 songs"
    assert description_of(["track", "disc"], 1) == "Track and Disc on 1 song"
    assert unsaved_text(3, 4) == "Your changes to 3 fields on 4 songs aren't saved"
    assert problem_line({"track": "x", "year": "y"}) == "Year: y" and problem_line({}) == ""
    assert progress_text(12, 40) == "Saving 12 of 40 files…"
    assert sorted_fields([Job("a", {"tracktotal": 9}), Job("b", {"year": 1, "title": "x"})]) == [
        "year", "title", "track"]  # fmt: skip


def test_the_covers_chip_says_where_the_songs_art_is():
    assert art_chip(4, 4, False) == {"text": "Art in all 4", "tone": "ok"}
    assert art_chip(1, 1, True)["text"] == "Art in this song"
    assert art_chip(2, 4, True) == {"text": "Art in 2 of 4", "tone": "warn"}
    assert art_chip(0, 4, True)["text"] == "Art in folder only"
    assert art_chip(0, 11, False) == {"text": "No cover yet", "tone": "warn"}


def test_a_field_shows_what_was_typed_else_what_the_songs_share_and_mixed_in_grey():
    """R4.3: a mixed field says "Mixed: keep each song's own"; R2.13: an empty sort name."""
    mixed = edit.Field("title", "", True, (("Neap Tide", 1), ("Moonpull", 1)))
    shown = view_field(mixed, None, False, None)
    assert shown["text"] == "" and shown["placeholder"] == "Mixed: keep each song's own"
    assert shown["values"][0] == {"text": "Neap Tide", "count": 1, "line": "Neap Tide · 1 song"}
    assert not shown["suggests"] and shown["label"] == "Title"
    typed = view_field(edit.Field("artist", "Lumen Drift", False), "Lumen", True, None)
    assert typed["text"] == "Lumen" and typed["changed"] and typed["suggests"]
    sort = view_field(edit.Field("albumsort", "", False), None, False, None)
    assert sort["placeholder"] == "Empty: the name, without The, A or An"
    assert view_field(edit.Field("year", "", False), "20x2", True, "no")["problem"] == "no"
    many = edit.Field("title", "", True, tuple((f"T{n}", 1) for n in range(500)))
    assert len(view_field(many, None, False, None)["values"]) == edittags.VALUES
    assert not is_edit(mixed, "  ") and is_edit(mixed, "Ebb")
    assert not is_edit(edit.Field("album", "Tide Tables", False), "Tide Tables")


def test_genres_suggest_for_the_one_being_typed_and_a_pick_takes_its_place():
    """R4.6, R9.2: several genres, joined with ";"."""
    assert being_typed("genres", "Ambient; Elec") == " Elec"
    assert being_typed("artist", "Lumen; D") == "Lumen; D"
    assert with_suggestion("genres", "Ambient; Elec", "Electronic") == "Ambient; Electronic"
    assert with_suggestion("genres", "Elec", "Electronic") == "Electronic"
    assert with_suggestion("album", "Tide; T", "Tide Tables") == "Tide Tables"


def test_one_songs_file_is_shown_read_only():
    """R4.8: the file's path, kind, length, bit rate, sample rate and size."""
    rows = details_of(song(), "/home/u/Music", "/home/u")
    assert [(r["label"], r["value"]) for r in rows] == [
        ("Path", os.path.join("~/Music", "LD", "TT", "01 - Neap Tide.flac")),
        ("Kind", "FLAC"), ("Length", "4:18"), ("Bit rate", "912 kbps"),
        ("Sample rate", "44.1 kHz"), ("Size", "31.2 MB"),
    ]  # fmt: skip
    bare = details_of(Song(2, "x.mp3", Tags()), "/m", "")
    assert [r["value"] for r in bare][1:] == ["—", "—", "—", "—", "—"]


def test_the_files_that_failed_are_listed_by_name_and_folder_with_why():
    """R4.7: listed at the end with their reason."""
    failed = [Failed(Job("/m/LD/TT/01.flac", {}), "it is read-only"),
              Failed(Job("/elsewhere/x.mp3", {}), "it isn't there")]  # fmt: skip
    assert failed_rows(failed, "/m") == [
        {"file": "01.flac", "folder": "LD/TT", "why": "it is read-only"},
        {"file": "x.mp3", "folder": "/elsewhere", "why": "it isn't there"},
    ]
    assert edittags.failed_text(1) == "1 file wasn't saved"
    assert edittags.failed_text(3) == "3 files weren't saved"
    cancelled = Outcome(saved=[1, 2, 3], cancelled=True, left=[Job("a", {}), Job("b", {})])
    assert saved_text(cancelled) == "Saved 3 of 5 files: cancelled before the rest"


# ---------- the bridge, over real files ----------


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """L03's four songs of Tide Tables as FLAC, tagged as the demo library tags them."""
    d = tmp_path_factory.mktemp("made")
    out = []
    for n, (title, artist, genre, year) in enumerate(TIDE, 1):
        path = str(d / f"{n:02d}.flac")
        demo.encode(path, "flac", 0.2, 330 + 110 * n)
        t = {"title": title, "artist": artist, "album": "Tide Tables", "albumartist": "Lumen Drift",
             "track": n, "tracktotal": 9, "disc": 1, "disctotal": 1, "year": year,
             "genre": [genre], "rating": n % 5}  # fmt: skip
        demo.tag(path, demo.Song(path, "flac", t))
        out.append(path)
    return out


def index_of(index, music, rels):
    """The index's rows of the files at `rels` under `music`, as a scan reads them."""
    batch = []
    for rel in rels:
        full = scanner.full_path(music, rel)
        t, info = tags.read(full)
        st = os.stat(full)
        batch.append(scanner.Read(scanner.Seen(rel, st.st_size, st.st_mtime_ns), t, info, rel))
    index.write(lambda c: scanner.write_batch(c, batch, {})).result()
    return [r[0] for r in index.read().execute("SELECT id FROM song ORDER BY path")]


@pytest.fixture
def root(made, tmp_path):
    """A root of L03's four songs with an index that has them: (root, index, ids, paths)."""
    music = tmp_path / "Music"
    (music / "LD" / "TT").mkdir(parents=True)
    (music / ".musikata").mkdir()
    rels = []
    for n, src in enumerate(made, 1):
        rels.append(f"LD/TT/{n:02d}.flac")
        shutil.copyfile(src, scanner.full_path(str(music), rels[-1]))
    index = db.Index(str(tmp_path / "musikata.db"))
    ids = index_of(index, str(music), rels)
    yield str(music), index, ids, [scanner.full_path(str(music), r) for r in rels]
    index.close()


def make(root, qtbot, tags_settings=None, write=None, available=lambda: True):
    music, index, ids, paths = root
    h = ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop",
                      settings.RootTags(), executor=ThreadPoolExecutor(1), watching=False,
                      message_ms=60_000)  # fmt: skip
    saved = []
    e = EditTags(music, index.read, tags_settings or settings.RootTags(), h, saved=saved.extend,
                 write=write, executor=ThreadPoolExecutor(1), home=os.path.dirname(music),
                 available=available)  # fmt: skip
    e.history_, e.saved_ = h, saved
    return e


@pytest.fixture
def panel(root, qapp, qtbot):
    e = make(root, qtbot)
    yield e
    e.close()
    e.history_.close()


def opened(e, qtbot, ids, what=""):
    e.edit_songs(ids, what)
    qtbot.waitUntil(lambda: not e.property("loading"), timeout=WAIT)


def field(e, name):
    return e.property("fields")[name]


def test_four_songs_show_what_they_share_and_whats_mixed(root, panel, qtbot):
    """R4.2, R4.3: the cover and what is edited, a field for each tag, shared or mixed."""
    music, index, ids, paths = root
    opened(panel, qtbot, ids)
    assert panel.property("opened") and panel.property("count") == 4
    assert panel.property("heading") == "Edit tags · 4 songs"
    assert (panel.property("title"), panel.property("line")) == (
        "Tide Tables", "Lumen Drift · 4 songs")  # fmt: skip
    assert field(panel, "album")["text"] == "Tide Tables" and not field(panel, "album")["mixed"]
    assert field(panel, "disc")["text"] == ""  # the demo library's tagging writes no disc
    assert field(panel, "title")["placeholder"] == "Mixed: keep each song's own"
    assert [v["text"] for v in field(panel, "artist")["values"]] == ["Lumen Drift", "lumen drift"]
    assert field(panel, "track")["text"] == "/ 9"
    assert panel.property("rating") == {"stars": 0, "mixed": True}
    assert panel.property("artChip") == {"text": "No cover yet", "tone": "warn"}
    assert panel.property("details") == [] and panel.property("keptNote") == ""
    assert not panel.property("canSave") and panel.property("changeLine") == ""
    assert not panel.property("more")
    panel.openMore()
    panel.openMore()  # it stays open
    assert panel.property("more")
    assert [t["name"] for t in panel.property("tools")] == [
        "number", "replace", "tidy", "copy", "infer"]  # R4.5's ⋯ menu  # fmt: skip


def test_typing_marks_what_will_change_and_revert_clears_it(root, panel, qtbot):
    """R4.4: changed fields outlined, "3 fields will change on 4 songs", Revert, Save to N."""
    music, index, ids, paths = root
    opened(panel, qtbot, ids)
    panel.setText("artist", "Lumen Drift")
    panel.pick("genres", "Electronic")  # from the mixed field's ▾
    panel.setText("year", "2022")
    assert [n for n, f in panel.property("fields").items() if f["changed"]] == [
        "artist", "genres", "year"]  # fmt: skip
    assert panel.property("changeLine") == "3 fields will change on 4 songs"
    assert panel.property("saveLabel") == "Save to 4 files" and panel.property("canSave")
    panel.setText("year", "20x2")
    assert panel.property("changeLine") == "Year: “20x2” isn't a year"
    assert not panel.property("canSave") and field(panel, "year")["problem"]
    panel.setText("title", "")  # a mixed field left empty: each song's own
    assert "title" not in [n for n, f in panel.property("fields").items() if f["changed"]]
    panel.revert()
    assert panel.property("changeLine") == "" and not panel.property("canRevert")
    assert field(panel, "year")["text"] == ""
    with pytest.raises(ValueError):
        panel.setText("lyrics", "la")


def test_a_save_writes_each_file_is_one_history_entry_and_its_message_offers_undo(
    root, panel, qtbot
):
    """R4.7, R4.9: the save goes through the batch; the message that follows has Undo."""
    music, index, ids, paths = root
    opened(panel, qtbot, ids)
    for name, text in {"artist": "Lumen Drift", "genres": "Electronic", "year": "2022"}.items():
        panel.setText(name, text)
    h = panel.history_
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        panel.save()
    assert [tags.read(p)[0].genres for p in paths] == [("Electronic",)] * 4
    assert {tags.read(p)[0].artist for p in paths} == {"Lumen Drift"}
    assert tags.read(paths[2])[0].year == 2022
    assert tags.read(paths[0])[0].title == "Neap Tide"  # a mixed field left alone: kept
    message = h.property("message")
    assert message["text"] == "Saved 4 files" and message["undo"]
    assert sorted(os.path.basename(w.path) for w in panel.saved_) == [
        "01.flac", "02.flac", "03.flac", "04.flac"]  # fmt: skip
    # the panel shows the songs as they now are: nothing left to change
    assert panel.property("changeLine") == "" and not panel.property("canSave")
    assert field(panel, "artist")["text"] == "Lumen Drift" and not field(panel, "artist")["mixed"]
    assert panel.property("failed") == {} and panel.property("progress") == {}
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        h.undoMessage()
    qtbot.waitUntil(lambda: tags.read(paths[3])[0].artist == "lumen drift", timeout=WAIT)
    index.write(lambda c: scanner.wrote(c, music, [tags.save(p, {}, audio_hash=scanner.audio_hash)
                                                   for p in paths])).result()  # fmt: skip
    panel.refresh()  # the rows read again (Library.reloaded): the panel shows them
    qtbot.waitUntil(lambda: field(panel, "artist")["mixed"], timeout=WAIT)


def test_the_save_is_kept_in_the_history_with_what_it_was(root, panel, qtbot):
    music, index, ids, paths = root
    opened(panel, qtbot, ids)
    panel.setText("genres", "Electronic")
    with qtbot.waitSignal(panel.history_.messageChanged, timeout=WAIT):
        panel.save()
    folder = os.path.join(music, ".musikata", "history")
    (name,) = [n for n in os.listdir(folder) if n.endswith(".json")]
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        assert json.load(f)["description"] == "Genre on 2 songs"


def test_the_files_that_fail_are_listed_with_why_and_retry_saves_them(root, panel, qtbot):
    """R4.7: read-only files are listed at the end with their reason and a Retry."""
    music, index, ids, paths = root
    opened(panel, qtbot, ids)
    os.chmod(paths[1], stat.S_IRUSR)
    try:
        panel.setText("album", "Tide Tables (2022)")
        with qtbot.waitSignal(panel.history_.messageChanged, timeout=WAIT):
            panel.save()
        failed = panel.property("failed")
        assert failed["title"] == "1 file wasn't saved"
        assert failed["rows"][0]["file"] == "02.flac"
        assert failed["rows"][0]["why"].startswith("it is read-only")
        assert panel.history_.property("message")["text"].startswith("Saved 3 of 4 files")
        # the file that failed still differs: Save would write it again
        assert panel.property("changeLine") == "1 field will change on 1 song"
    finally:
        os.chmod(paths[1], stat.S_IRUSR | stat.S_IWUSR)
    with qtbot.waitSignal(panel.history_.messageChanged, timeout=WAIT):
        panel.retry()
    assert tags.read(paths[1])[0].album == "Tide Tables (2022)"
    assert panel.property("failed") == {} and panel.property("changeLine") == ""
    panel.retry()  # nothing failed: nothing
    panel.setText("album", "x")
    panel.dismissFailed()
    assert panel.property("failed") == {}


def test_a_bulk_tool_saves_through_the_panel_as_one_entry_named_for_it(root, panel, qtbot):
    """R4.5.1 in its preview (R3.7), saved as the panel saves (R4.7), one entry in the change
    history named for the tool, its message offering Undo (R4.9)."""
    music, index, ids, paths = root
    opened(panel, qtbot, ids[::-1])  # the list in another order: numbered in that order
    panel.runTool("number")
    tool = panel.property("tool")
    assert tool.property("opened") and tool.property("title") == "Number tracks"
    preview = tool.property("preview")
    assert preview.property("saveLabel") == "Save 4 files"
    preview.toggle(0)  # 04.flac, unchecked: left alone
    h = panel.history_
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        tool.save()
    assert not tool.property("opened")
    assert [(tags.read(p)[0].track, tags.read(p)[0].tracktotal) for p in paths] == [
        (4, 4), (3, 4), (2, 4), (4, 9)]  # fmt: skip
    assert h.property("message")["text"] == "Saved 3 files" and h.property("message")["undo"]
    folder = os.path.join(music, ".musikata", "history")
    (name,) = [n for n in os.listdir(folder) if n.endswith(".json")]
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        assert json.load(f)["description"] == "Number tracks: Track and Track total on 3 songs"
    assert field(panel, "track")["mixed"]  # the panel shows the songs as they now are
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        h.undoMessage()
    qtbot.waitUntil(lambda: tags.read(paths[0])[0].track == 1, timeout=WAIT)


def test_the_tools_wait_on_changes_not_saved_and_infer_from_path_on_r3(root, panel, qtbot):
    """R4.5: a tool plans from the files' tags, so typed changes are saved or reverted first;
    R4.5.5: Infer from path is shown, disabled, for later; a new selection closes a tool."""
    music, index, ids, paths = root
    opened(panel, qtbot, ids)
    tool = panel.property("tool")
    panel.runTool("infer")
    assert not tool.property("opened")
    panel.setText("album", "Tide Tables (2022)")
    menu = {t["name"]: t["later"] for t in panel.property("tools")}
    assert menu["number"] == "Save or revert your changes first"
    panel.runTool("number")
    assert not tool.property("opened")
    panel.revert()
    panel.runTool("copy")
    assert tool.property("opened") and tool.property("tool") == "copy"
    opened(panel, qtbot, ids[:1])  # another selection: the tool's songs are gone
    assert not tool.property("opened")
    assert {t["name"]: t["later"] for t in panel.property("tools")}["copy"] == (
        "Select two or more songs to copy between")  # fmt: skip
    panel.runTool("tidy")
    assert tool.property("opened")
    panel.hide()
    assert not tool.property("opened")


def test_a_tools_save_waits_for_the_root_and_another_save(root, qtbot, qapp):
    """R2.10: no root, no save; one save at a time (R4.7)."""
    there = [True]
    e = make(root, qtbot, available=lambda: there[0])
    try:
        music, index, ids, paths = root
        opened(e, qtbot, ids)
        e.runTool("number")
        there[0] = False
        assert {t["later"] for t in e.property("tools")} == {
            "Saving waits until the music folder is back",
            "Tags from paths come in a later version"}  # fmt: skip
        e.property("tool").save()  # it doesn't start: nothing written, the dialog left open
        assert [tags.read(p)[0].tracktotal for p in paths] == [9] * 4
        assert e.property("tool").property("opened")
    finally:
        e.close()
        e.history_.close()


def written(job):
    return Written(job.path, Tags(**{k: v for k, v in job.changes.items() if k != "genres"}),
                   AudioInfo("flac", 1, 1, 1, 1), "0" * 64, 1, 1)  # fmt: skip


def test_more_than_a_few_files_show_progress_and_cancel_stops_between_files(tmp_path, qtbot, qapp):
    """R4.7: progress for more than a few files; cancellable between files."""
    index = db.Index(str(tmp_path / "musikata.db"))
    fill(index, [{"path": f"A/{n:02d}.flac", "album": "A"} for n in range(12)])
    ids = [r[0] for r in index.read().execute("SELECT id FROM song ORDER BY path")]
    gate, began = threading.Event(), threading.Event()

    def slow(job):
        began.set()
        gate.wait(WAIT / 1000)
        return written(job)

    e = EditTags(str(tmp_path), index.read, settings.RootTags(), write=slow,
                 executor=ThreadPoolExecutor(1))  # fmt: skip
    try:
        opened(e, qtbot, ids)
        e.setText("album", "B")
        e.save()
        assert e.property("saving") and not e.property("canSave")
        assert e.property("saveNote") == "A save is going on"
        e.save()  # one at a time
        began.wait(WAIT / 1000)
        assert e.property("progress")["text"] == "Saving 0 of 12 files…"
        e.cancel()
        with qtbot.waitSignal(e.savingChanged, timeout=WAIT):
            gate.set()
        qtbot.waitUntil(lambda: not e.property("saving"), timeout=WAIT)
        assert e.property("progress") == {}
        assert e.property("changeLine") == "1 field will change on 11 songs"
    finally:
        gate.set()
        e.close()
        index.close()


def test_a_few_files_show_no_progress_and_a_root_not_there_saves_nothing(root, qtbot, qapp):
    """R4.7: "for more than a few files"; R2.10: every change to files is unavailable."""
    music, index, ids, paths = root
    there = [False]
    e = make(root, qtbot, available=lambda: there[0])
    try:
        opened(e, qtbot, ids)
        e.setText("album", "X")
        assert not e.property("canSave")
        assert e.property("saveNote") == "Saving waits until the music folder is back"
        e.save()
        assert not e.property("saving")
        there[0] = True
        with qtbot.waitSignal(e.history_.messageChanged, timeout=WAIT):
            e.save()
        assert e.property("progress") == {}
    finally:
        e.close()
        e.history_.close()


def test_the_roots_settings_give_the_id3_version_and_keep_modification_times(tmp_path, qtbot, qapp):
    """R4.7.1, R4.7.2: the panel saves as the root's settings say (settings.root_tags)."""
    music = tmp_path / "Music"
    music.mkdir()
    path = str(music / "a.mp3")
    demo.encode(path, "mp3", 0.2, 440)
    demo.tag(path, demo.Song(path, "mp3", {"title": "A", "album": "X"}))
    os.utime(path, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    index = db.Index(str(tmp_path / "musikata.db"))
    ids = index_of(index, str(music), ["a.mp3"])
    os.makedirs(os.path.dirname(settings.root_path(str(music))))
    with open(settings.root_path(str(music)), "w", encoding="utf-8") as f:
        f.write('{"format": 1, "tags": {"id3_version": "2.3", "keep_modified_times": true}}')
    e = EditTags(str(music), index.read, settings.root_tags(str(music)),
                 executor=ThreadPoolExecutor(1))  # fmt: skip
    try:
        opened(e, qtbot, ids)
        e.setText("album", "Y")
        with qtbot.waitSignal(e.savingChanged, timeout=WAIT):
            e.save()
        qtbot.waitUntil(lambda: not e.property("saving"), timeout=WAIT)
        assert tags.read(path)[0].album == "Y"
        assert mutagen.id3.ID3(path).version[:2] == (2, 3)
        assert os.stat(path).st_mtime_ns == 1_000_000_000_000_000_000
    finally:
        e.close()
        index.close()


def test_one_song_shows_its_file_and_the_tags_it_keeps(root, panel, qtbot):
    """R4.8: for a single song, its path, kind, length, bit rate, sample rate, size and the tags
    MusiKata keeps without showing, read only."""
    music, index, ids, paths = root
    f = mutagen.File(paths[0])
    f["musicbrainz_trackid"] = "9a"
    f.save()
    opened(panel, qtbot, ids[:1])
    assert panel.property("heading") == "Edit tags · 1 song"
    assert panel.property("title") == "Neap Tide"
    labels = [d["label"] for d in panel.property("details")]
    assert labels == ["Path", "Kind", "Length", "Bit rate", "Sample rate", "Size"]
    assert panel.property("details")[0]["value"].endswith(os.path.join("LD", "TT", "01.flac"))
    assert {"label": "MUSICBRAINZ_TRACKID", "value": "9a"} in panel.property("kept")
    assert field(panel, "title")["text"] == "Neap Tide" and not field(panel, "title")["mixed"]
    os.remove(paths[1])
    opened(panel, qtbot, ids[1:2])
    assert panel.property("kept") == []
    assert panel.property("keptNote").startswith("Its file couldn't be read")
    opened(panel, qtbot, [])
    assert panel.property("emptyText") == "Select songs to edit their tags"
    assert panel.property("details") == [] and panel.property("heading") == "Edit tags"


def test_a_new_selection_is_edited_after_asking_to_save_or_discard_changes(root, panel, qtbot):
    """R4.2: the list stays usable; changing the selection changes what the panel edits, after
    asking to save or discard unsaved changes."""
    music, index, ids, paths = root
    songs = SongsModel(index.read)
    songs.refresh()
    songs.select_songs(ids[:2])
    panel.editSelection(songs)
    qtbot.waitUntil(lambda: panel.property("count") == 2, timeout=WAIT)
    songs.select_songs(ids[2:])  # nothing typed: it follows at once
    qtbot.waitUntil(lambda: panel.property("title") == "Tide Tables" and
                    panel.property("count") == 2 and not panel.property("loading"),
                    timeout=WAIT)  # fmt: skip
    panel.setText("composer", "Ada")
    songs.select_songs(ids[:1])
    assert panel.property("question")["text"] == (
        "Your changes to 1 field on 2 songs aren't saved")  # fmt: skip
    assert panel.property("count") == 2  # still what it edited
    panel.answer("discard")
    qtbot.waitUntil(lambda: panel.property("count") == 1, timeout=WAIT)
    assert tags.read(paths[3])[0].composer is None
    panel.setText("composer", "Ada")
    songs.select_songs(ids[1:3])
    with qtbot.waitSignal(panel.history_.messageChanged, timeout=WAIT):
        panel.answer("save")
    qtbot.waitUntil(lambda: panel.property("count") == 2, timeout=WAIT)
    assert tags.read(paths[0])[0].composer == "Ada"
    songs.clearSelection()  # nothing selected: it keeps what it edits
    assert panel.property("count") == 2
    panel.answer("save")  # no question: nothing


def test_closing_with_changes_asks_first(root, panel, qtbot):
    music, index, ids, paths = root
    opened(panel, qtbot, ids)
    panel.setText("comment", "kept")
    panel.hide()
    assert panel.property("opened") and panel.property("question")["text"]
    panel.answer("discard")
    assert not panel.property("opened") and panel.property("question") == {}
    panel.hide()  # closed: nothing
    opened(panel, qtbot, ids)
    panel.setText("comment", "kept")
    panel.hide()
    with qtbot.waitSignal(panel.history_.messageChanged, timeout=WAIT):
        panel.answer("save")
    qtbot.waitUntil(lambda: not panel.property("opened"), timeout=WAIT)
    assert tags.read(paths[0])[0].comment == "kept"


def test_the_library_suggests_its_values_as_the_user_types(root, panel, qtbot):
    """R4.6: Artist, Album artist, Album and Genre suggest the values already in the library, read
    off the GUI thread."""
    music, index, ids, paths = root
    opened(panel, qtbot, ids)
    with qtbot.waitSignal(panel.suggestionsChanged, timeout=WAIT):
        panel.suggest("genres", "Ambient; elec")
    assert panel.property("suggestFor") == "genres"
    assert panel.property("suggestions") == ["Electronic", "electronic", "Electronica"]
    panel.setText("genres", "Ambient; elec")
    panel.pickSuggestion("genres", "Electronic")
    assert field(panel, "genres")["text"] == "Ambient; Electronic"
    assert panel.property("suggestions") == []
    panel.suggest("title", "Ne")  # Title suggests nothing
    assert panel.property("suggestFor") == ""
    with qtbot.waitSignal(panel.suggestionsChanged, timeout=WAIT):
        panel.suggest("artist", "lu")
    assert panel.property("suggestions") == ["Lumen Drift", "lumen drift"]


# ---------- the window ----------


@pytest.fixture
def shell(made, tmp_path, qapp, qtbot):
    """MusiKata over L03's four songs, scanned, and a folder of two more."""
    music = tmp_path / "Music"
    (music / "Lumen Drift" / "Tide Tables").mkdir(parents=True)
    for n, src in enumerate(made, 1):
        shutil.copyfile(src, music / "Lumen Drift" / "Tide Tables" / f"{n:02d}.flac")
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(music), env, FakeClock(datetime.now(UTC) - timedelta(minutes=1)),
                 lambda: ThreadPoolExecutor(1))  # fmt: skip
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


def click(shell, item):
    at = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


def settled(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.window.grabWindow()


@pytest.mark.slow
def test_the_panel_opens_from_ctrl_e_edits_and_saves_with_undo_and_no_qml_warning(
    shell, qtbot, qtlog
):
    """R4.2 to R4.4 in the window: Ctrl+E opens the panel on the selection, typing marks the
    field, Save writes the files and the message offers Undo; every text in its box."""
    e, lib = shell.edit, shell.library
    lib.show("songs")
    songs = lib.property("songs")
    qtbot.waitUntil(lambda: songs.rowCount() == 4, timeout=WAIT)
    songs.selectAll()
    shell.window.requestActivate()
    QTest.keyClick(shell.window, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: bool(find(shell, "editPanel")) and e.property("count") == 4,
                    timeout=WAIT)  # fmt: skip
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    assert not find(shell, "editSelection")  # the bar's Edit tags: the panel edits it already
    box = find(shell, "input-artist")[0]
    click(shell, box)
    QTest.keyClick(shell.window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for ch in "Lumen Drift":
        QTest.keyClick(shell.window, ch)
    qtbot.waitUntil(lambda: e.property("changeLine") == "1 field will change on 1 song",
                    timeout=WAIT)  # fmt: skip
    click(shell, find(shell, "moreFields")[0])
    assert e.property("more") and find(shell, "field-albumsort")
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    with qtbot.waitSignal(shell.changes.messageChanged, timeout=WAIT):
        click(shell, find(shell, "saveTags")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "messageUndo")), timeout=WAIT)
    moonpull = os.path.join(shell.music_, "Lumen Drift", "Tide Tables", "04.flac")
    assert tags.read(moonpull)[0].artist == "Lumen Drift"
    click(shell, find(shell, "closeEdit")[0])
    assert not e.property("opened")
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


@pytest.mark.slow
def test_a_bulk_tool_opens_from_the_menu_previews_and_saves_with_no_qml_warning(
    shell, qtbot, qtlog
):
    """R4.5 in the window: the ⋯ menu, a tool's dialog over the window with its options and
    R3.7's preview, Infer from path faded; Save writes the files checked; every text in its box."""
    e, lib = shell.edit, shell.library
    lib.show("songs")
    songs = lib.property("songs")
    qtbot.waitUntil(lambda: songs.rowCount() == 4, timeout=WAIT)
    songs.selectAll()
    e.editSelection(songs)
    qtbot.waitUntil(lambda: e.property("count") == 4 and not e.property("loading"), timeout=WAIT)
    settled(shell, qtbot)
    click(shell, find(shell, "editTools")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "tool-replace")), timeout=WAIT)
    assert find(shell, "tool-infer")[0].opacity() < 1  # R4.5.5: for later, saying so
    click(shell, find(shell, "tool-replace")[0])
    tool = e.property("tool")
    qtbot.waitUntil(lambda: bool(find(shell, "toolDialog")), timeout=WAIT)
    assert tool.property("tool") == "replace"
    settled(shell, qtbot)  # the chips laid out where they are clicked
    click(shell, find(shell, "toolField-artist")[0])
    click(shell, find(shell, "tool-find")[0])
    for ch in "lumen drift":
        QTest.keyClick(shell.window, ch)
    click(shell, find(shell, "tool-by")[0])
    for ch in "Lumen Drift":
        QTest.keyClick(shell.window, ch)
    preview = tool.property("preview")
    preview = tool.property("preview")
    qtbot.waitUntil(lambda: preview.property("saveLabel") == "Save 1 file", timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    assert len(find(shell, "previewCheck")) == 4
    with qtbot.waitSignal(shell.changes.messageChanged, timeout=WAIT):
        click(shell, find(shell, "saveTool")[0])
    assert not find(shell, "toolDialog")
    moonpull = os.path.join(shell.music_, "Lumen Drift", "Tide Tables", "04.flac")
    assert tags.read(moonpull)[0].artist == "Lumen Drift"
    for name in ("number", "tidy", "copy"):  # each dialog lays out in its box
        e.runTool(name)
        settled(shell, qtbot)
        assert layout.faults(shell.window) == [], name
        click(shell, find(shell, "cancelTool")[0])
        assert not tool.property("opened")
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


@pytest.mark.slow
def test_the_windows_shortcuts_do_nothing_behind_a_bulk_tools_dialog(shell, qtbot):
    """R4.5 with R6.9: while a tool's dialog is open over the window, Ctrl+Z and Space (and the
    window's other shortcuts) don't act on what is behind it; closed, they do again."""
    e, lib, p, h = shell.edit, shell.library, shell.player, shell.changes
    lib.show("songs")
    songs = lib.property("songs")
    qtbot.waitUntil(lambda: songs.rowCount() == 4, timeout=WAIT)
    p.cue(songs.queue_from(0)[0], "Songs")  # Space would start it
    songs.selectAll()
    e.editSelection(songs)
    qtbot.waitUntil(lambda: e.property("count") == 4 and not e.property("loading"), timeout=WAIT)
    e.runTool("number")
    qtbot.waitUntil(lambda: bool(find(shell, "toolDialog")), timeout=WAIT)
    shell.window.requestActivate()
    qtbot.waitUntil(lambda: shell.window.isActive(), timeout=WAIT)
    acted = []
    p.changed.connect(lambda: acted.append("space"))
    h.messageChanged.connect(lambda: acted.append("undo"))  # Ctrl+Z says "Nothing to undo"
    QTest.keyClick(shell.window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(shell.window, Qt.Key.Key_Space)
    qtbot.wait(200)  # the one fixed wait: to show nothing happens
    assert acted == [] and e.property("tool").property("opened")
    click(shell, find(shell, "cancelTool")[0])
    assert not e.property("tool").property("opened")
    with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
        QTest.keyClick(shell.window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert h.property("message")["text"] == "Nothing to undo"
    with qtbot.waitSignal(p.changed, timeout=WAIT):
        QTest.keyClick(shell.window, Qt.Key.Key_Space)


@pytest.mark.slow
def test_edit_tags_opens_from_an_album_a_songs_menu_the_selection_bar_and_folders(shell, qtbot):
    """R4.2: on an album, a song, a selection; R2.9.6: on folders, every song beneath them, from
    the selection bar and the right-click menu; R2.9.7: a folder of songs' Edit tags."""
    e, lib = shell.edit, shell.library
    c = shell.index.read()
    (album,) = c.execute("SELECT id FROM album").fetchone()
    lib.openAlbum(album)
    qtbot.waitUntil(lambda: bool(find(shell, "editAlbum")), timeout=WAIT)
    click(shell, find(shell, "editAlbum")[0])
    qtbot.waitUntil(lambda: e.property("count") == 4 and not e.property("loading"), timeout=WAIT)
    assert e.property("title") == "Tide Tables"
    e.hide()
    lib.show("songs")
    songs = lib.property("songs")
    qtbot.waitUntil(lambda: songs.rowCount() == 4, timeout=WAIT)
    songs.click(1, False, False)
    qtbot.waitUntil(lambda: bool(find(shell, "editSelection")), timeout=WAIT)
    click(shell, find(shell, "editSelection")[0])
    qtbot.waitUntil(lambda: e.property("count") == 1 and not e.property("loading"), timeout=WAIT)
    e.editRow(songs, 2)  # the menu on a row not selected: that song
    qtbot.waitUntil(lambda: e.property("title") == songs.row(2)["title"], timeout=WAIT)
    e.hide()
    lib.show("folders")
    folders = lib.property("folders")
    folders.open("Lumen Drift")
    folders.select_paths(["Lumen Drift/Tide Tables"])
    qtbot.waitUntil(lambda: bool(find(shell, "editSelection")), timeout=WAIT)
    click(shell, find(shell, "editSelection")[0])
    qtbot.waitUntil(lambda: e.property("count") == 4 and not e.property("loading"), timeout=WAIT)
    assert e.property("line") == "Lumen Drift · 1 folder"
    e.hide()
    e.editRow(folders.property("model"), 0)
    qtbot.waitUntil(lambda: e.property("count") == 4, timeout=WAIT)
    e.hide()
    folders.open("Lumen Drift/Tide Tables")  # a folder of songs (R2.9.7)
    qtbot.waitUntil(lambda: bool(find(shell, "editFolder")), timeout=WAIT)
    click(shell, find(shell, "editFolder")[0])
    qtbot.waitUntil(lambda: e.property("count") == 4 and not e.property("loading"), timeout=WAIT)
    e.hide()
    e.editCurrent(lib)  # Ctrl+E there, nothing selected: the folder
    qtbot.waitUntil(lambda: e.property("count") == 4, timeout=WAIT)
    e.hide()
    lib.openAlbum(album)
    e.editCurrent(lib)  # on an album's page: the album
    qtbot.waitUntil(lambda: e.property("count") == 4, timeout=WAIT)
    e.hide()
    lib.show("albums")
    e.editCurrent(lib)  # a view with no songs listed: the panel says to select some
    assert e.property("opened") and e.property("emptyText")
    shell.changes.show()  # Change history over it; Edit tags opened again closes it
    e.editCurrent(lib)
    assert not shell.changes.property("opened")
    e.runTool("number")  # no songs edited: no tool to open
    assert not e.property("tool").property("opened")
    lib.show("songs")
    songs.selectAll()
    e.go({"view": "songs", "edit": {"composer": "Ada"}}, lib)  # the tour's L03
    qtbot.waitUntil(lambda: e.property("changeLine") == "1 field will change on 4 songs",
                    timeout=WAIT)  # fmt: skip
    e.go({"view": "albums"}, lib)  # a step without the panel: closed, its typing dropped
    assert not e.property("opened") and e.property("changeLine") == ""


def test_a_new_selection_or_closing_while_a_save_goes_on_waits_for_it(tmp_path, qtbot, qapp):
    """R4.2, R4.7: what the panel edits changes once the save is done, never in the middle."""
    index = db.Index(str(tmp_path / "musikata.db"))
    fill(index, [{"path": f"A/{n:02d}.flac", "album": "A"} for n in range(3)])
    ids = [r[0] for r in index.read().execute("SELECT id FROM song ORDER BY path")]
    gate = threading.Event()

    def slow(job):
        gate.wait(WAIT / 1000)
        return written(job)

    e = EditTags(str(tmp_path), index.read, settings.RootTags(), write=slow,
                 executor=ThreadPoolExecutor(1))  # fmt: skip
    try:
        opened(e, qtbot, ids[:2])
        e.setText("album", "B")
        e.save()
        e.edit_songs(ids[2:])  # waits for the save
        assert e.property("count") == 2
        gate.set()
        qtbot.waitUntil(lambda: e.property("count") == 1 and not e.property("loading"),
                        timeout=WAIT)  # fmt: skip
        gate.clear()
        e.setText("album", "C")
        e.save()
        e.hide()  # closes once the save is done
        assert e.property("opened")
        gate.set()
        qtbot.waitUntil(lambda: not e.property("opened"), timeout=WAIT)
        gate.clear()
        opened(e, qtbot, ids)
        e.setText("album", "D")
        e.save()
    finally:
        gate.set()
        e.close()  # a save going on: stopped before its next file, waited for
        index.close()
