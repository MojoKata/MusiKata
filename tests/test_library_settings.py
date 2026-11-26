"""The shared settings (src/musikata_core/settings.py; R13.9, A2.10, R1.5): where they are on each
platform, the configured root read from whatever a person, a sync tool or another version left in
settings.json, and written back keeping everything it doesn't know; this computer's id, made when
it has none; shuffle and repeat (R7.3), read and written the same way.

Why: settings.json is hand-editable (R13.9) and outlives the version that wrote it (A2.10), so it is
data from outside: each shape testing.md's "Shapes" lists for `settings` has its test here."""

import json
import logging
import os

import jsonschema
import pytest

from musikata_core import settings

HOME = os.path.join(os.sep, "home", "ana")
SCHEMA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "musikata_core", "schemas",
    "shared-settings.v1.schema.json",
)  # fmt: skip


def parse(doc):
    return settings.parse(doc if isinstance(doc, str) else json.dumps(doc), HOME)


def test_the_shared_settings_folder_is_r1_5s_on_each_platform():
    env = {"HOME": "/home/ana", "USERPROFILE": "C:\\Users\\ana"}
    assert settings.shared_dir(env, "linux") == os.path.join("/home/ana", ".musikata")
    assert settings.shared_dir(env, "win32") == os.path.join("C:\\Users\\ana", ".musikata")
    assert settings.shared_dir(env, "darwin") == os.path.join(
        "/home/ana", "Library", "Application Support", "MusiKata"
    )
    assert settings.shared_dir({**env, "MUSIKATA_DATA": "/d"}, "linux") == os.path.join(
        "/d", "settings"
    )
    assert settings.shared_path(env, "linux").endswith(os.path.join(".musikata", "settings.json"))


def test_no_file_is_the_first_start_with_nothing_configured(tmp_path):
    got = settings.load(str(tmp_path / "settings.json"), HOME)
    assert got == settings.Shared() and got.root is None and got.watch is True


def test_a2_10s_example_gives_its_root_watch_and_computer():
    got = parse({"format": 1, "computer": {"id": "b2c4", "name": "Studio-PC"},
                 "library": {"root": "/home/ana/Music", "watch": False}})  # fmt: skip
    assert (got.root, got.watch, got.computer_id, got.computer_name) == (
        os.path.normpath("/home/ana/Music"), False, "b2c4", "Studio-PC"
    )  # fmt: skip
    assert got.problems == () and got.newer is False


@pytest.mark.parametrize("text", ["", "{", '{"format": 1, "library": {"root": "/ho', "\x00\x00"])
def test_a_file_empty_or_cut_short_by_a_sync_takes_the_defaults_and_says_so(text):
    got = parse(text)
    assert got.root is None and got.data == {} and "isn't JSON" in got.problems[0]


@pytest.mark.parametrize("doc", [[], '"Music"', 1, None])
def test_a_file_that_isnt_an_object_takes_the_defaults(doc):
    got = parse(doc)
    assert got.root is None and "isn't a JSON object" in got.problems[0]


def test_a_bom_from_notepad_is_read_past():
    got = parse("\ufeff" + json.dumps({"format": 1, "library": {"root": "/m"}}))
    assert got.root == os.path.normpath("/m") and got.problems == ()


def test_fields_in_another_order_and_unknown_ones_are_read_and_kept():
    doc = {"online": {"allowed": True}, "library": {"skip_me": 1, "root": "/m"}, "format": 1,
           "later_group": {"x": [1]}}  # fmt: skip
    got = parse(doc)
    assert got.root == os.path.normpath("/m") and got.data == doc


def test_a_newer_format_is_read_for_what_it_can_and_marked_never_to_be_written():
    got = parse({"format": 2, "library": {"root": "/m"}})
    assert got.newer and got.root == os.path.normpath("/m")
    assert "newer MusiKata" in got.problems[0]


@pytest.mark.parametrize("fmt", ["1", 1.0, True, None])
def test_a_format_missing_or_not_a_number_is_read_as_this_one(fmt):
    doc = {"library": {"root": "/m"}} if fmt is None else {"format": fmt, "library": {"root": "/m"}}
    got = parse(doc)
    assert got.root == os.path.normpath("/m") and not got.newer
    assert (got.problems == ()) == (fmt is None)


@pytest.mark.parametrize(
    "library, root, problem",
    [
        ({}, None, ""),
        ({"root": None}, None, ""),
        ({"root": ""}, None, ""),
        ({"root": 42}, None, "isn't a path"),
        ({"root": ["/m"]}, None, "isn't a path"),
        ({"root": "Music"}, None, "isn't a whole path"),
        ({"root": "~/Music"}, os.path.join(HOME, "Music"), ""),
        ({"root": "~"}, HOME, ""),
        ({"root": "/media/usb/Music/"}, os.path.normpath("/media/usb/Music"), ""),
        ("Music", None, "library isn't a group"),
    ],
)
def test_the_root_missing_null_empty_not_text_relative_or_with_a_tilde(library, root, problem):
    got = parse({"format": 1, "library": library})
    assert got.root == root
    assert (problem in got.problems[0]) if problem else got.problems == ()


@pytest.mark.parametrize("watch, problems", [(True, 0), (False, 0), ("yes", 1), (1, 1), (None, 1)])
def test_watch_that_isnt_true_or_false_is_on(watch, problems):
    got = parse({"format": 1, "library": {"watch": watch}})
    assert got.watch is (watch if isinstance(watch, bool) else True)
    assert len(got.problems) == problems


def test_a2_10s_playback_gives_the_device_replaygain_and_its_pre_amp():
    example = {"device": None, "replaygain": "album", "replaygain_default": -6.0, "resume": True,
               "shuffle": False, "repeat": "off"}  # fmt: skip
    got = parse({"format": 1, "playback": example})
    assert got.playback == settings.Playback(None, "album", -6.0) == settings.Shared().playback
    dac = "alsa_output.usb-DAC.analog-stereo"
    chosen = parse({"format": 1, "playback": {"device": dac, "replaygain": "track",
                                              "replaygain_default": -9}})  # fmt: skip
    assert chosen.playback == settings.Playback(dac, "track", -9.0)
    assert chosen.problems == () and parse({"format": 1}).playback == settings.Playback()


@pytest.mark.parametrize(
    "playback, want, problem",
    [
        ("loud", settings.Playback(), "playback isn't a group"),
        ({"device": 3}, settings.Playback(), "isn't a device's id"),
        ({"device": ""}, settings.Playback(), "isn't a device's id"),
        ({"replaygain": " Track "}, settings.Playback(replaygain="track"), ""),
        ({"replaygain": "OFF"}, settings.Playback(replaygain="off"), ""),
        ({"replaygain": "smart"}, settings.Playback(), "isn't album, track or off"),
        ({"replaygain": None}, settings.Playback(), "isn't album, track or off"),
        ({"replaygain_default": "-8.5 dB"}, settings.Playback(replaygain_default=-8.5), ""),
        ({"replaygain_default": "-3"}, settings.Playback(replaygain_default=-3.0), ""),
        ({"replaygain_default": "quiet"}, settings.Playback(), "isn't a number of dB"),
        ({"replaygain_default": True}, settings.Playback(), "isn't a number of dB"),
        ({"replaygain_default": None}, settings.Playback(), "isn't a number of dB"),
    ],
)
def test_playback_values_broken_in_another_case_or_as_text(playback, want, problem):
    got = parse({"format": 1, "playback": playback})
    assert got.playback == want
    assert (problem in got.problems[0]) if problem else got.problems == ()


def test_a_pre_amp_that_isnt_finite_takes_its_default():
    got = parse('{"format": 1, "playback": {"replaygain_default": NaN}}')  # Python's json reads it
    assert got.playback.replaygain_default == -6.0 and "isn't a number of dB" in got.problems[0]


@pytest.mark.parametrize("computer, cid", [({"id": "x"}, "x"), ({"id": ""}, None),
                                           ({"id": 7}, None), ("x", None), ({}, None)])  # fmt: skip
def test_a_computer_missing_or_with_a_broken_id_has_none(computer, cid):
    assert parse({"format": 1, "computer": computer}).computer_id == cid


def test_choosing_a_root_writes_a_file_valid_under_its_schema_with_a_new_computer_id(tmp_path):
    path = str(tmp_path / "s" / "settings.json")
    assert settings.choose_root(path, HOME, "/home/ana/Music", "Studio-PC")
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    assert doc["library"] == {"root": "/home/ana/Music"} and doc["format"] == 1
    assert doc["computer"]["name"] == "Studio-PC" and len(doc["computer"]["id"]) == 36
    assert settings.load(path, HOME).root == os.path.normpath("/home/ana/Music")
    assert os.listdir(tmp_path / "s") == ["settings.json"]  # no temporary file left


def test_choosing_a_root_keeps_what_it_doesnt_know_and_the_computers_id():
    read = parse({"format": 1, "computer": {"id": "b2c4", "name": "Studio-PC", "x": 1},
                  "library": {"root": "/old", "watch": False, "later": [1]},
                  "appearance": {"theme": "light"}, "later_group": {"y": 2}})  # fmt: skip
    doc = settings.with_root(read, "/new", "Other", lambda: "never")
    assert doc == {"format": 1, "computer": {"id": "b2c4", "name": "Studio-PC", "x": 1},
                   "library": {"root": "/new", "watch": False, "later": [1]},
                   "appearance": {"theme": "light"}, "later_group": {"y": 2}}  # fmt: skip


def test_a_broken_computer_or_library_is_replaced_when_the_root_is_written():
    read = parse({"format": "1", "computer": {"id": 7}, "library": "Music"})
    doc = settings.with_root(read, "/new", "Studio-PC", lambda: "made")
    assert doc["format"] == 1 and doc["library"] == {"root": "/new"}
    assert doc["computer"] == {"id": "made", "name": "Studio-PC"}


def test_a_newer_formats_file_is_never_written(tmp_path, caplog):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"format": 2, "library": {"root": "/m"}}))
    with caplog.at_level(logging.WARNING):
        assert not settings.choose_root(str(path), HOME, "/other", "PC")
    assert json.loads(path.read_text())["format"] == 2
    assert "newer MusiKata" in caplog.text


def test_a_broken_file_is_logged_and_written_anew(tmp_path, caplog):
    path = tmp_path / "settings.json"
    path.write_text('{"format": 1, "libr')
    with caplog.at_level(logging.WARNING):
        assert settings.choose_root(str(path), HOME, "/m", "PC")
    assert "isn't JSON" in caplog.text and "written anew" in caplog.text
    assert settings.load(str(path), HOME).root == os.path.normpath("/m")


def test_a_sync_tools_conflicted_copy_beside_it_is_not_read(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"format": 1, "library": {"root": "/a"}}))
    (tmp_path / "settings (Studio-PC's conflicted copy).json").write_text(
        json.dumps({"format": 1, "library": {"root": "/b"}})
    )
    assert settings.load(str(tmp_path / "settings.json"), HOME).root == os.path.normpath("/a")


def test_a_file_that_cant_be_read_or_written_is_logged(tmp_path, caplog):
    folder = tmp_path / "settings.json"
    folder.mkdir()  # a folder where the file should be: neither read nor replaced
    with caplog.at_level(logging.WARNING):
        got = settings.load(str(folder), HOME)
        assert not settings.save(str(folder), {"format": 1})
    assert got.root is None and "couldn't be read" in got.problems[0]
    assert "couldn't read" in caplog.text and "couldn't write" in caplog.text


# ---------- shuffle and repeat (R7.3), and this computer's id (A2.8) ----------


def test_shuffle_and_repeat_are_read_from_playback():
    got = parse({"format": 1, "playback": {"shuffle": True, "repeat": "all"}})
    assert got.playback == settings.Playback(shuffle=True, repeat="all") and got.problems == ()
    assert (settings.Playback().shuffle, settings.Playback().repeat) == (False, "off")


@pytest.mark.parametrize(
    "playback, want, problem",
    [
        ({"shuffle": "yes"}, settings.Playback(), "playback.shuffle isn't true or false"),
        ({"shuffle": 1}, settings.Playback(), "playback.shuffle isn't true or false"),
        ({"shuffle": None}, settings.Playback(), "playback.shuffle isn't true or false"),
        ({"repeat": " One "}, settings.Playback(repeat="one"), ""),
        ({"repeat": "ALL"}, settings.Playback(repeat="all"), ""),
        ({"repeat": "twice"}, settings.Playback(), "isn't off, all or one"),
        ({"repeat": True}, settings.Playback(), "isn't off, all or one"),
        ({"repeat": None}, settings.Playback(), "isn't off, all or one"),
    ],
)
def test_shuffle_and_repeat_broken_in_another_case_or_type(playback, want, problem):
    got = parse({"format": 1, "playback": playback})
    assert got.playback == want
    assert (problem in got.problems[0]) if problem else got.problems == ()


def test_shuffle_or_repeat_set_keeps_the_rest_of_the_file_valid_under_its_schema(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "format": 1, "computer": {"id": "b2c4", "name": "Studio-PC"},
        "library": {"root": "/home/ana/Music"}, "later_group": {"y": 2},
        "playback": {"device": "dac", "replaygain": "track", "later": [1]},
    }))  # fmt: skip
    assert settings.set_playback(str(path), HOME, "Other", shuffle=True)
    assert settings.set_playback(str(path), HOME, "Other", repeat="one")
    doc = json.loads(path.read_text())
    assert doc == {
        "format": 1, "computer": {"id": "b2c4", "name": "Studio-PC"},
        "library": {"root": "/home/ana/Music"}, "later_group": {"y": 2},
        "playback": {"device": "dac", "replaygain": "track", "later": [1], "shuffle": True,
                     "repeat": "one"},
    }  # fmt: skip
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    assert settings.load(str(path), HOME).playback == settings.Playback(
        "dac", "track", shuffle=True, repeat="one"
    )


def test_shuffle_set_with_no_file_makes_one_with_this_computers_id(tmp_path):
    path = str(tmp_path / "s" / "settings.json")
    assert settings.set_playback(path, HOME, "Studio-PC", shuffle=True)
    got = settings.load(path, HOME)
    assert got.playback.shuffle and got.computer_name == "Studio-PC" and got.computer_id


def test_shuffle_and_repeat_never_go_into_a_newer_or_unreadable_file(tmp_path, caplog):
    newer, cut = tmp_path / "newer.json", tmp_path / "cut.json"
    newer.write_text(json.dumps({"format": 2, "library": {"root": "/m"}}))
    cut.write_text('{"format": 1, "library": {"root": "/home/ana/Mus')  # a sync in progress
    with caplog.at_level(logging.WARNING):
        assert not settings.set_playback(str(newer), HOME, "PC", shuffle=True)
        assert not settings.set_playback(str(cut), HOME, "PC", repeat="all")
    assert json.loads(newer.read_text())["format"] == 2
    assert cut.read_text() == '{"format": 1, "library": {"root": "/home/ana/Mus'
    assert "newer MusiKata" in caplog.text and "left as it is" in caplog.text


def test_this_computers_id_is_the_files_else_made_once_and_kept(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"format": 1, "library": {"root": "/m"}, "later": 1}))
    made = settings.computer_id(str(path), HOME, "Studio-PC")
    assert made and settings.computer_id(str(path), HOME, "Other") == made
    doc = json.loads(path.read_text())
    assert doc["computer"] == {"id": made, "name": "Studio-PC"} and doc["later"] == 1
    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps({"format": 2}))
    assert settings.computer_id(str(newer), HOME, "PC") is None
    assert json.loads(newer.read_text()) == {"format": 2}


# ---------- the root's own settings.json: what writing tags needs (R13.3, R4.7.1, R4.7.2) ---

ROOT_EXAMPLE = {
    "format": 1,
    "tags": {"id3_version": "2.3", "write_ratings": True, "rating_scale": "windows-media",
             "history": True, "history_days": 90, "articles": ["The", "A", "An"],
             "keep_modified_times": True},
    "skip": ["_Incoming/Unsorted"],
}  # fmt: skip


def test_the_roots_own_settings_give_the_id3_version_and_whether_times_are_kept(tmp_path):
    """A2.10's example, held to its schema, read; and a root without the file, or the file
    without the group, writes ID3v2.4 and updates modification times (R4.7.1, R4.7.2)."""
    schema = SCHEMA.replace("shared-settings", "root-settings")
    with open(schema, encoding="utf-8") as f:
        jsonschema.validate(ROOT_EXAMPLE, json.load(f))
    root = tmp_path / "Music"
    assert settings.root_tags(str(root)) == settings.RootTags("2.4", False)
    (root / ".musikata").mkdir(parents=True)
    with open(settings.root_path(str(root)), "w", encoding="utf-8") as f:
        json.dump(ROOT_EXAMPLE, f)
    assert settings.root_tags(str(root)) == settings.RootTags("2.3", True)
    assert settings.parse_root_tags('{"format": 1}') == settings.RootTags()
    assert settings.parse_root_tags('{"format": 3, "tags": {"id3_version": "2.3"}}') == (
        settings.RootTags("2.3")
    )  # a newer format: read for what it can


@pytest.mark.parametrize(
    "tags, want, problem",
    [
        ({"id3_version": 2.3}, ("2.3", False), None),  # a number, as a person writes it
        ({"id3_version": "v2.3"}, ("2.3", False), None),
        ({"id3_version": "ID3v2.4 "}, ("2.4", False), None),
        ({"id3_version": "2.2"}, ("2.4", False), "isn't 2.3 or 2.4"),
        ({"id3_version": True}, ("2.4", False), "isn't 2.3 or 2.4"),
        ({"id3_version": None}, ("2.4", False), "isn't 2.3 or 2.4"),
        ({"keep_modified_times": "yes"}, ("2.4", False), "isn't true or false"),
        ("2.3", ("2.4", False), "tags isn't a group"),
    ],
)
def test_the_roots_tags_values_broken_or_in_another_form(tags, want, problem):
    found = settings.parse_root_tags(json.dumps({"format": 1, "tags": tags}))
    assert (found.id3_version, found.keep_modified_times) == want
    assert [p for p in found.problems if problem in p] if problem else not found.problems


@pytest.mark.parametrize("text", ["", '{"format": 1, "tags": {', "[1, 2]", '﻿{"tags": 5}'])
def test_a_roots_file_empty_cut_short_or_not_an_object_writes_with_the_defaults(text):
    found = settings.parse_root_tags(text)
    assert (found.id3_version, found.keep_modified_times) == ("2.4", False) and found.problems


def test_a_roots_file_that_cant_be_read_or_with_problems_is_logged(tmp_path, caplog):
    folder = tmp_path / ".musikata"
    folder.mkdir()
    (folder / "settings.json").write_text('{"tags": {"id3_version": "3"}}', encoding="utf-8")
    assert settings.root_tags(str(tmp_path)).id3_version == "2.4"
    assert "isn't 2.3 or 2.4" in caplog.text
    (folder / "settings.json").unlink()
    (folder / "settings.json").mkdir()  # a folder where the file should be: it can't be read
    found = settings.root_tags(str(tmp_path))
    assert (found.id3_version, found.keep_modified_times) == ("2.4", False) and found.problems
    assert "writing tags takes the defaults" in caplog.text
