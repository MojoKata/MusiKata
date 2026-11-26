"""The first start (src/musikata/firstrun.py, qml/FirstRun.qml; R2.1, X01-first-run): a folder
dropped onto the window, chosen in the folder dialog, or the platform's music folder becomes the
root; what isn't a folder is refused with a word why; the window loads with its text in its boxes.

Why: the first start is the one screen every user sees, and the one no later run shows again; a
drop of a file, or a music folder that isn't there yet, must not leave the user without a root."""

import os

import pytest
from PySide6.QtCore import QUrl

from musikata import app, firstrun, layout


def url(path):
    return QUrl.fromLocalFile(str(path))


@pytest.fixture
def first(tmp_path):
    return firstrun.FirstRun(str(tmp_path / "Music"), str(tmp_path))


def chosen(first):
    got = []
    first.chosen.connect(got.append)
    return got


def test_the_music_folder_offered_is_the_platforms_shown_from_the_home(tmp_path, first):
    assert firstrun.music_folder(str(tmp_path)) == str(tmp_path / "Music")  # own_home's HOME
    assert first.property("musicText") == f"Use {os.path.join('~', 'Music')}"


def test_a_folder_dropped_is_the_root_and_the_first_of_several(tmp_path, first):
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    (tmp_path / "song.mp3").write_bytes(b"x")
    got = chosen(first)
    assert first.accepts([url(tmp_path / "song.mp3"), url(tmp_path / "A")])
    first.drop([url(tmp_path / "song.mp3"), url(tmp_path / "A"), url(tmp_path / "B")])
    assert got == [str(tmp_path / "A")] and first.property("error") == ""


def test_a_drop_that_holds_no_folder_says_it_wants_one(tmp_path, first):
    (tmp_path / "song.mp3").write_bytes(b"x")
    got = chosen(first)
    assert not first.accepts([url(tmp_path / "song.mp3"), "https://example.org/a"])
    first.drop([url(tmp_path / "song.mp3"), url(tmp_path / "gone")])
    assert got == [] and first.property("error") == firstrun.NOT_A_FOLDER


def test_the_folder_dialogs_choice_is_the_root(tmp_path, first):
    (tmp_path / "Tunes").mkdir()
    got = chosen(first)
    first.choose(url(tmp_path / "Tunes").toString())
    first.choose(str(tmp_path / "Tunes"))
    first.choose(url(tmp_path / "nowhere").toString())
    assert got == [str(tmp_path / "Tunes")] * 2
    assert first.property("error") == firstrun.NOT_A_FOLDER


def test_use_music_makes_the_music_folder_when_it_isnt_there(tmp_path, first):
    got = chosen(first)
    first.useMusic()
    assert got == [str(tmp_path / "Music")] and (tmp_path / "Music").is_dir()


def test_a_music_folder_that_cant_be_made_says_why(tmp_path):
    (tmp_path / "file").write_bytes(b"x")
    first = firstrun.FirstRun(str(tmp_path / "file" / "Music"), str(tmp_path))
    got = chosen(first)
    first.useMusic()
    assert got == [] and first.property("error").startswith(
        f"{os.path.join('~', 'file', 'Music')} can't be made:"
    )


@pytest.mark.slow
def test_the_first_starts_window_loads_with_its_text_in_its_boxes(tmp_path, qtbot, qtlog):
    shell = app.first_start({"HOME": str(tmp_path)})
    shell.window.show()
    for w, h in ((1280, 800), (1920, 1040), (960, 600)):
        shell.window.setWidth(w)
        shell.window.setHeight(h)
        item = shell.window.contentItem()
        qtbot.waitUntil(lambda w=w, h=h, item=item: (item.width(), item.height()) == (w, h))
        shell.window.grabWindow()
        assert layout.faults(shell.window) == [], (w, h)
    shell.first.drop([])  # a drop with nothing in it: the error under the box
    shell.window.grabWindow()
    assert layout.faults(shell.window) == []
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    shell.close()
