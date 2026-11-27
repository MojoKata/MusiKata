"""The Edit tags panel's bulk tools in the running app (src/musikata/bulktools.py, ToolDialog.qml;
R4.5): the ⋯ menu, each tool's dialog with its options planned again as they change, the
preview's Save handing the files checked on with the tool's name for the change history, and
Infer from path shown for later.

Why: the dialog is where the user sets a tool up before it writes many files; an option that
doesn't reach the plan, an expression that crashes instead of saying why, or a save that names
the wrong tool in the history leaves the user unable to trust or find what was done."""

import pytest

from musikata.bulktools import (
    INFER_LATER,
    SAVING,
    TWO,
    UNSAVED,
    BulkTool,
    description_of,
    field_choices,
    menu_of,
    source_choices,
)
from musikata_core.tags import Job, Tags
from musikata_core.tags.tools import Song

ROOT = "/home/u/Music"
L03 = [
    Tags(title="Neap Tide", artist="Lumen Drift", album="Tide Tables", genres=("Electronica",),
         track=1, tracktotal=9, year=2022),
    Tags(title="Spring Tide", artist="Lumen Drift", album="Tide Tables", genres=("electronic",),
         track=2, tracktotal=9, year=2022),
    Tags(title="Slack Water", artist="Lumen Drift", album="Tide Tables", genres=("Electronic",),
         track=3, tracktotal=9),
    Tags(title=None, artist="lumen drift", album="Tide Tables", genres=("Electronic",), track=4,
         tracktotal=9, year=2022),
]  # fmt: skip


def songs():
    return [Song(f"{ROOT}/LD/TT/{n:02d}.flac", t) for n, t in enumerate(L03, 1)]


def test_the_menu_lists_r45s_tools_and_says_why_one_cant_be_used_now():
    """R4.5's ⋯ menu; R4.5.5: Infer from path comes with R3, shown disabled saying so."""
    menu = menu_of(4, unsaved=False, saving=False)
    assert [(t["name"], t["label"]) for t in menu] == [
        ("number", "Number tracks"), ("replace", "Replace in field"), ("tidy", "Tidy case"),
        ("copy", "Copy from…"), ("infer", "Infer from path")]  # fmt: skip
    assert [t["later"] for t in menu] == ["", "", "", "", INFER_LATER]
    assert INFER_LATER == "Tags from paths come in a later version"
    assert {t["later"] for t in menu_of(4, True, False)} == {UNSAVED, INFER_LATER}
    assert {t["later"] for t in menu_of(4, True, True)} == {SAVING, INFER_LATER}
    assert menu_of(1, False, False)[3]["later"] == TWO


def test_a_tools_save_is_named_for_it_in_the_change_history():
    """R4.9: the entry's description names the tool and what it changed."""
    assert description_of("number", ["track", "tracktotal"], 4) == (
        "Number tracks: Track and Track total on 4 songs")  # fmt: skip
    assert (
        description_of("tidy", ["artist", "genres"], 1) == "Tidy case: Artist and Genre on 1 song"
    )
    assert description_of("copy", ["album"], 2) == "Copy from…: Album on 2 songs"


def test_the_fields_and_songs_offered_are_named_as_the_user_knows_them():
    assert field_choices(["title", "genres"], ["genres"]) == [
        {"name": "title", "label": "Title", "chosen": False},
        {"name": "genres", "label": "Genre", "chosen": True},
    ]
    titles = [t.title for t in L03]
    assert source_choices(songs(), titles, ROOT) == [
        "Neap Tide · 01.flac", "Spring Tide · 02.flac", "Slack Water · 03.flac",
        "04 · 04.flac"]  # fmt: skip


def opened(qtbot, tool, options=None, undoable=True):
    b = BulkTool(ROOT)
    with qtbot.waitSignal(b.changed):
        b.open(tool, songs(), options, undoable)
    return b


def test_number_tracks_opens_on_its_preview(qapp, qtbot):
    """R4.5.1 in a preview like R3.7: every file checked, Save 4 files."""
    b = opened(qtbot, "number")
    assert b.property("opened") and b.property("tool") == "number"
    assert b.property("title") == "Number tracks" and "1, 2, 3" in b.property("about")
    assert b.property("count") == 4 and b.property("options") == {} and b.property("problem") == ""
    p = b.property("preview")
    assert p.property("saveLabel") == "Save 4 files"
    assert p.property("footer").startswith("4 files · 4 changes")
    with qtbot.waitSignal(b.saved) as sent:
        b.save()
    jobs, description = sent.args
    assert description == "Number tracks: Track total on 4 songs"
    assert jobs[0] == Job(f"{ROOT}/LD/TT/01.flac", {"tracktotal": 4})
    assert b.property("opened")  # the panel closes it once its save has started


def test_replace_plans_again_as_its_options_change_and_an_invalid_expression_says_why(qapp, qtbot):
    """R4.5.2: the field, what to find and what replaces it, as text or an expression."""
    b = opened(qtbot, "replace", {"field": "genres"})
    p = b.property("preview")
    assert b.property("problem") == "" and not p.property("canSave")  # nothing to find yet
    options = b.property("options")
    assert options["field"] == "genres" and options["find"] == "" and not options["regex"]
    assert [f["name"] for f in options["fields"] if f["chosen"]] == ["genres"]
    b.setOption("find", "^electronica?$")
    b.setOption("by", "Electronic")
    assert not p.property("canSave")  # as text, "^" is a "^"
    b.setOption("regex", True)
    assert p.property("saveLabel") == "Save 2 files"
    b.setOption("match_case", True)
    assert p.property("saveLabel") == "Save 1 file"
    b.setOption("find", "(electronic")
    assert b.property("problem").startswith("The regular expression isn't valid")
    assert not p.property("canSave")
    b.save()  # nothing is saved while the expression is wrong
    assert b.property("opened")
    b.setOption("find", "lumen drift")
    b.setOption("by", "Lumen Drift")
    b.setOption("field", "artist")
    assert b.property("problem") == "" and p.property("saveLabel") == "Save 1 file"
    with qtbot.waitSignal(b.saved) as sent:
        b.save()
    assert sent.args == [[Job(f"{ROOT}/LD/TT/04.flac", {"artist": "Lumen Drift"})],
                         "Replace in field: Artist on 1 song"]  # fmt: skip
    with pytest.raises(ValueError, match="year"):
        b.open("replace", songs(), {"field": "year"})


def test_tidy_case_tidies_the_fields_chosen(qapp, qtbot):
    """R4.5.3: Title, Artist, Album, Album artist and Genre at first; a field's chip toggles it."""
    b = opened(qtbot, "tidy")
    chosen = [f["name"] for f in b.property("options")["fields"] if f["chosen"]]
    assert chosen == ["title", "artist", "album", "albumartist", "genres"]
    p = b.property("preview")
    assert p.property("footer").startswith("2 files · 2 changes")
    b.toggleField("genres")
    assert p.property("footer").startswith("1 file · 1 change")
    b.toggleField("genres")
    b.toggleField("year")  # not a field Tidy case works on: nothing
    b.toggleField("comment")
    assert "comment" in [f["name"] for f in b.property("options")["fields"] if f["chosen"]]
    with qtbot.waitSignal(b.saved) as sent:
        b.save()
    assert sent.args[1] == "Tidy case: Artist and Genre on 2 songs"
    b.open("tidy", songs(), {"tidied": ["genres"]})  # opened with its fields chosen (a tour's)
    assert [f["name"] for f in b.property("options")["fields"] if f["chosen"]] == ["genres"]


def test_copy_from_copies_from_the_song_chosen(qapp, qtbot):
    """R4.5.4: the first song at first; the fields chosen copied to the others."""
    b = opened(qtbot, "copy")
    options = b.property("options")
    assert options["source"] == 0 and options["sources"][0] == "Neap Tide · 01.flac"
    assert [f["name"] for f in options["fields"] if f["chosen"]] == [
        "album", "albumartist", "year", "genres"]  # fmt: skip
    p = b.property("preview")
    assert p.property("footer").startswith("3 files · 4 changes")  # Genre ×3, Slack Water's Year
    b.setOption("source", 2)  # Slack Water, without a year
    assert b.property("options")["source"] == 2
    b.setOption("source", 99)  # past the list: its last song
    assert b.property("options")["source"] == 3
    b.toggleField("title")  # not a field Copy from… copies: nothing
    b.toggleField("year")
    b.setOption("source", 0)
    with qtbot.waitSignal(b.saved) as sent:
        b.save()
    assert sent.args[1] == "Copy from…: Genre on 3 songs"


def test_closing_saves_nothing_and_options_or_tools_that_dont_exist_are_refused(qapp, qtbot):
    b = opened(qtbot, "number", undoable=False)
    assert "history is off" in b.property("preview").property("footer")
    with qtbot.waitSignal(b.changed):
        b.close()
    assert not b.property("opened") and b.property("preview").property("total") == 0
    b.close()  # closed already: nothing
    b.save()
    b.setOption("find", "x")  # no tool open: nothing
    b.toggleField("title")
    assert not b.property("opened")
    with pytest.raises(ValueError, match="infer"):
        b.open("infer", songs())
    with pytest.raises(ValueError, match="no such option"):
        b.open("number", songs(), {"colour": "red"})
