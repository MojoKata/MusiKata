"""The preview of a change to many files' tags before it is saved (src/musikata/preview.py,
PreviewTable.qml; R3.7, R3.8), as the Edit tags panel's bulk tools show it (R4.5): its columns, a
row per file with its old and new values, the checkboxes, which files are listed, and the footer.

Why: the preview is the user's one look at a change to many files before it is written; a row that
shows a change the save won't make, a file unchecked that is saved anyway, or a count that doesn't
match what Save writes would make the look worthless."""

from PySide6.QtCore import Qt

from musikata.preview import (
    Preview,
    columns_of,
    file_of,
    footer_text,
    label_of,
    labels_text,
    listed,
    more_text,
    row_of,
    save_text,
)
from musikata_core.tags import Job, Tags
from musikata_core.tags.tools import Planned, Song, number_tracks, replace_in_field

ROOT = "/home/u/Music"
L03 = [  # L03's four songs, as the demo library tags them
    Tags(title="Neap Tide", genres=("Electronica",), track=1, tracktotal=9, year=2022),
    Tags(title="Spring Tide", genres=("electronic",), track=2, tracktotal=9, year=2022),
    Tags(title="Slack Water", genres=("Electronic",), track=3, tracktotal=9),
    Tags(title="Moonpull", genres=("Electronic",), track=4, tracktotal=9, year=2022),
]
NAMES = ["01 - Neap Tide.flac", "02 - Spring Tide.flac", "03 - Slack Water.flac",
         "04 - Moonpull.flac"]  # fmt: skip


def songs(tags=L03):
    return [
        Song(f"{ROOT}/Lumen Drift/Tide Tables/{n}", t) for n, t in zip(NAMES, tags, strict=True)
    ]


def test_a_value_that_changes_shows_old_above_new_and_empty_for_none():
    """R3.7: the old value (struck through in red) above the new one (green); "(empty)"."""
    planned = number_tracks(songs())
    row = row_of(planned, 0, True, ROOT)
    assert row["file"] == "01 - Neap Tide.flac" and row["folder"] == "Lumen Drift/Tide Tables"
    assert row["changed"] and row["checked"]
    assert row["cells"] == [
        {"old": "1", "new": "1", "changed": False, "oldEmpty": False, "newEmpty": False},
        {"old": "9", "new": "4", "changed": True, "oldEmpty": False, "newEmpty": False},
    ]
    gone = replace_in_field(songs(), "genres", "Electronic", "")
    cell = row_of(gone, 2, True, ROOT)["cells"][0]
    assert cell == {"old": "Electronic", "new": "(empty)", "changed": True, "oldEmpty": False,
                    "newEmpty": True}  # fmt: skip
    filled = number_tracks(songs([Tags(), *L03[1:]]))
    assert row_of(filled, 0, True, ROOT)["cells"][0]["old"] == "(empty)"


def test_a_file_with_no_change_is_never_checked():
    planned = replace_in_field(songs(), "genres", "^electronica$", "Electronic", regex=True)
    row = row_of(planned, 1, True, ROOT)
    assert not row["changed"] and not row["checked"]


def test_the_columns_are_the_fields_filled_with_t01s_headings():
    planned = number_tracks(songs())
    assert columns_of(planned) == [
        {"name": "track", "label": "#", "narrow": True},
        {"name": "tracktotal", "label": "Track total", "narrow": True},
    ]
    assert label_of("genres") == "Genre" and label_of("albumartist") == "Album artist"
    assert labels_text(["artist", "genres", "year"]) == "Artist, Genre and Year"
    assert labels_text(["title"]) == "Title" and labels_text([]) == ""


def test_a_file_outside_the_root_or_at_its_top_is_named_whole():
    assert file_of(f"{ROOT}/song.mp3", ROOT) == ("song.mp3", "")
    assert file_of("/elsewhere/a/song.mp3", ROOT) == ("song.mp3", "/elsewhere/a")


def test_the_unchanged_files_after_the_last_change_are_counted_not_listed():
    """T01-infer-from-path: rows to the last change, one more, then "+ 3 more files, unchanged"."""
    assert listed([False, True, True, True, True, False, False, False, False]) == 6
    assert listed([True, True]) == 2 and listed([True, False]) == 2
    assert listed([True, False, False]) == 3  # one file more is listed, not counted
    assert listed([False] * 3) == 1 and listed([]) == 0
    assert (
        more_text(3) == "+ 3 more files, unchanged" and more_text(1) == "+ 1 more file, unchanged"
    )
    assert more_text(0) == ""


def test_the_footer_counts_the_files_and_changes_that_will_be_saved():
    """R3.8: "4 files · 4 changes · the old tags are kept, and Undo puts them back"."""
    assert (
        footer_text(4, 4) == "4 files · 4 changes · the old tags are kept, and Undo puts them back"
    )
    assert footer_text(1, 1, undoable=False) == (
        "1 file · 1 change · the change history is off, so Undo can't put them back")  # fmt: skip
    assert footer_text(0, 0) == "Nothing will change"
    assert (
        save_text(4) == "Save 4 files" and save_text(1) == "Save 1 file" and save_text(0) == "Save"
    )


def test_the_preview_checks_every_changed_file_and_unchecking_leaves_it_out(qapp, qtbot):
    """R3.7, R3.8: each changed file checked at first; unchecked, it isn't saved or counted."""
    p = Preview(ROOT)
    planned = replace_in_field(songs(), "genres", "^electronica?$", "Electronic", regex=True)
    with qtbot.waitSignal(p.changed):
        p.show(planned)
    assert p.property("footer") == (
        "2 files · 2 changes · the old tags are kept, and Undo puts them back")  # fmt: skip
    assert p.property("saveLabel") == "Save 2 files" and p.property("canSave")
    assert p.property("total") == 4 and p.property("more") == ""
    rows = p.property("rows")
    assert rows.rowCount() == 4
    roles = {bytes(v).decode(): k for k, v in rows.roleNames().items()}
    assert rows.data(rows.index(0, 0), roles["file"]) == "01 - Neap Tide.flac"
    assert rows.data(rows.index(0, 0), roles["checked"]) is True
    assert rows.data(rows.index(2, 0), roles["checked"]) is False
    assert rows.data(rows.index(9, 0), roles["file"]) is None
    assert rows.data(rows.index(0, 0), int(Qt.ItemDataRole.DisplayRole)) is None
    with qtbot.waitSignal(rows.dataChanged):
        p.toggle(0)
    assert p.chosen() == [1] and p.counts() == (1, 1) and p.fields() == ["genres"]
    assert p.jobs() == [Job(f"{ROOT}/Lumen Drift/Tide Tables/{NAMES[1]}",
                            {"genres": ["Electronic"]})]  # fmt: skip
    p.toggle(2)  # no change: no checkbox to toggle
    p.toggle(7)
    assert p.chosen() == [1]
    p.toggle(1)
    assert not p.property("canSave") and p.property("footer") == "Nothing will change"
    p.toggle(0)
    assert p.chosen() == [0]
    p.show(number_tracks(songs()[:1]), undoable=False)  # shown anew: every change checked
    assert p.chosen() == [0] and "history is off" in p.property("footer")
    assert [c["name"] for c in p.property("columns")] == ["track", "tracktotal"]


def test_a_files_note_is_in_its_row_and_noted_files_are_listed_whatever_they_change():
    """R3.4: Infer from path's files the pattern doesn't fit are listed last, unchanged, with
    "Doesn't fit the pattern"; the plain tools note nothing."""
    song = Song(f"{ROOT}/a/b.flac", Tags())
    planned = Planned(("title",), (song, song), (Tags(title="x"), Tags()),
                      notes=("", "Doesn't fit the pattern"))  # fmt: skip
    assert row_of(planned, 1, False, ROOT)["note"] == "Doesn't fit the pattern"
    assert row_of(planned, 0, True, ROOT)["note"] == ""
    assert planned.note(5) == ""
    assert listed([True, False, False, False], noted=[False, False, False, True]) == 4
    assert listed([True, False, False, False]) == 2
