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


def test_the_visualization_is_read_from_appearance_waveform_by_default():
    got = parse({"format": 1, "appearance": {"theme": "dark", "visualization": "none"}})
    assert got.appearance == settings.Appearance("none") and got.problems == ()
    assert parse({"format": 1}).appearance.visualization == "waveform"


@pytest.mark.parametrize(
    "appearance, want, problem",
    [
        ({"visualization": " Analyzer "}, "analyzer", ""),
        ({"visualization": "NONE"}, "none", ""),
        ({"visualization": "3d"}, "waveform", "isn't waveform, analyzer or none"),
        ({"visualization": 2}, "waveform", "isn't waveform, analyzer or none"),
        ({"visualization": None}, "waveform", "isn't waveform, analyzer or none"),
        ([], "waveform", "appearance isn't a group"),
    ],
)
def test_the_visualization_broken_in_another_case_or_type(appearance, want, problem):
    got = parse({"format": 1, "appearance": appearance})
    assert got.appearance.visualization == want
    assert (problem in got.problems[0]) if problem else got.problems == ()


def test_the_visualization_set_keeps_the_rest_of_the_file_valid_under_its_schema(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "format": 1, "computer": {"id": "b2c4", "name": "Studio-PC"},
        "appearance": {"theme": "dark", "tint": False, "later": 1},
    }))  # fmt: skip
    assert settings.set_appearance(str(path), HOME, "Other", visualization="none")
    doc = json.loads(path.read_text())
    assert doc["appearance"] == {
        "theme": "dark",
        "tint": False,
        "later": 1,
        "visualization": "none",
    }
    assert doc["computer"] == {"id": "b2c4", "name": "Studio-PC"}
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    assert settings.load(str(path), HOME).appearance.visualization == "none"
    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps({"format": 2}))
    assert not settings.set_appearance(str(newer), HOME, "PC", visualization="none")


def test_the_analyzers_bands_and_seconds_are_read_from_appearance_96_and_3_by_default():
    got = parse({"format": 1, "appearance": {"analyzer_bands": 128, "analyzer_seconds": 6}})
    assert got.appearance == settings.Appearance("waveform", 128, 6.0) and got.problems == ()
    assert parse({"format": 1}).appearance == settings.Appearance("waveform", 96, 3.0)


@pytest.mark.parametrize(
    "appearance, bands, seconds, problem",
    [
        ({"analyzer_bands": "48", "analyzer_seconds": " 1.5 "}, 48, 1.5, ""),
        ({"analyzer_bands": 96.0, "analyzer_seconds": 4}, 96, 4.0, ""),  # a hand edit
        ({"analyzer_bands": 64}, 96, 3.0, "analyzer_bands isn't 48, 96 or 128"),
        ({"analyzer_bands": True}, 96, 3.0, "analyzer_bands isn't 48, 96 or 128"),
        ({"analyzer_bands": None}, 96, 3.0, "analyzer_bands isn't 48, 96 or 128"),
        ({"analyzer_bands": "many"}, 96, 3.0, "analyzer_bands isn't 48, 96 or 128"),
        ({"analyzer_seconds": 0}, 96, 3.0, "analyzer_seconds isn't 1 to 12 seconds"),
        ({"analyzer_seconds": 60}, 96, 3.0, "analyzer_seconds isn't 1 to 12 seconds"),
        ({"analyzer_seconds": float("nan")}, 96, 3.0, "analyzer_seconds isn't 1 to 12 seconds"),
        ({"analyzer_seconds": "3 s"}, 96, 3.0, "analyzer_seconds isn't 1 to 12 seconds"),
        ({"analyzer_seconds": False}, 96, 3.0, "analyzer_seconds isn't 1 to 12 seconds"),
    ],
)
def test_the_analyzers_bands_and_seconds_broken_out_of_range_or_as_text(
    appearance, bands, seconds, problem
):
    got = parse({"format": 1, "appearance": appearance})
    assert (got.appearance.analyzer_bands, got.appearance.analyzer_seconds) == (bands, seconds)
    assert (problem in got.problems[0]) if problem else got.problems == ()


def test_the_analyzers_bands_and_seconds_set_keep_the_file_valid_under_its_schema(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"format": 1, "appearance": {"visualization": "analyzer"}}))
    assert settings.set_appearance(str(path), HOME, "PC", analyzer_bands=128)
    assert settings.set_appearance(str(path), HOME, "PC", analyzer_seconds=1.5)
    doc = json.loads(path.read_text())
    assert doc["appearance"] == {
        "visualization": "analyzer", "analyzer_bands": 128, "analyzer_seconds": 1.5
    }  # fmt: skip
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    assert settings.load(str(path), HOME).appearance == settings.Appearance("analyzer", 128, 1.5)


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


def test_the_roots_own_settings_give_the_change_historys_switch_and_days():
    """R4.9, R13.3: Keep a history of tag changes (on), and for how many days (90)."""
    found = settings.parse_root_tags(json.dumps(ROOT_EXAMPLE))
    assert (found.history, found.history_days) == (True, 90)
    off = settings.parse_root_tags('{"format": 1, "tags": {"history": false, "history_days": 7}}')
    assert (off.history, off.history_days, off.problems) == (False, 7, ())
    assert (settings.RootTags().history, settings.RootTags().history_days) == (True, 90)


@pytest.mark.parametrize(
    "tags, want, problem",
    [
        ({"history_days": "30"}, (True, 30), None),  # as text, as a person writes it
        ({"history_days": 30.0}, (True, 30), None),
        ({"history_days": " 30 "}, (True, 30), None),
        ({"history_days": 0}, (True, 90), "isn't a number of days"),
        ({"history_days": -5}, (True, 90), "isn't a number of days"),
        ({"history_days": 2.5}, (True, 90), "isn't a number of days"),
        ({"history_days": True}, (True, 90), "isn't a number of days"),
        ({"history_days": None}, (True, 90), "isn't a number of days"),
        ({"history_days": "a month"}, (True, 90), "isn't a number of days"),
        ({"history_days": float("nan")}, (True, 90), "isn't a number of days"),
        ({"history": "off"}, (True, 90), "tags.history isn't true or false"),
        ({"history": 0}, (True, 90), "tags.history isn't true or false"),
        ({"history": None}, (True, 90), "tags.history isn't true or false"),
    ],
)
def test_the_change_historys_settings_broken_or_in_another_form(tags, want, problem):
    """R13.9: a broken value is reported in the log and its default used."""
    found = settings.parse_root_tags(json.dumps({"format": 1, "tags": tags}))
    assert (found.history, found.history_days) == want
    assert [p for p in found.problems if problem in p] if problem else not found.problems


def test_the_roots_own_settings_give_where_ratings_are_kept_and_their_scale():
    """R10.3, R10.4.1, R13.3: Write ratings into the files (on), and the rating scale in files
    (Windows Media, else MusiKata's own), as A2.10 names them."""
    found = settings.parse_root_tags(json.dumps(ROOT_EXAMPLE))
    assert (found.write_ratings, found.rating_scale) == (True, "windows-media")
    beside = settings.parse_root_tags(
        '{"format": 1, "tags": {"write_ratings": false, "rating_scale": "musikata"}}'
    )
    assert (beside.write_ratings, beside.rating_scale, beside.problems) == (False, "musikata", ())
    assert (settings.RootTags().write_ratings, settings.RootTags().rating_scale) == (
        True, "windows-media",
    )  # fmt: skip


@pytest.mark.parametrize(
    "tags, want, problem",
    [
        ({"rating_scale": "Windows Media"}, (True, "windows-media"), None),  # as a person writes it
        ({"rating_scale": "windows_media"}, (True, "windows-media"), None),
        ({"rating_scale": " MusiKata "}, (True, "musikata"), None),
        ({"rating_scale": "itunes"}, (True, "windows-media"), "isn't windows-media or musikata"),
        ({"rating_scale": 5}, (True, "windows-media"), "isn't windows-media or musikata"),
        ({"rating_scale": None}, (True, "windows-media"), "isn't windows-media or musikata"),
        ({"write_ratings": "no"}, (True, "windows-media"), "write_ratings isn't true or false"),
        ({"write_ratings": 0}, (True, "windows-media"), "write_ratings isn't true or false"),
        ({"write_ratings": None}, (True, "windows-media"), "write_ratings isn't true or false"),
    ],
)
def test_the_ratings_settings_broken_or_in_another_form(tags, want, problem):
    """R13.9: a broken value is reported in the log and its default used."""
    found = settings.parse_root_tags(json.dumps({"format": 1, "tags": tags}))
    assert (found.write_ratings, found.rating_scale) == want
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


def test_the_roots_own_settings_give_the_genre_list_and_the_genres_said_to_be_the_same():
    """R9.5, R9.6, R13.3: the Genre list (None until set: the built-in one) and the groups of
    genres the user has said are the same, as A2.10 names them."""
    assert (settings.RootTags().genres, settings.RootTags().same_genres) == (None, ())
    found = settings.parse_root_tags(json.dumps({"format": 1, "tags": {
        "genres": ["Jazz", " Soul ", "", "Jazz"],
        "same_genres": [["Electronic", "Electronica"], [" Synthwave", "Retrowave", ""]],
    }}))  # fmt: skip
    assert found.genres == ("Jazz", "Soul") and found.problems == ()
    assert found.same_genres == (("Electronic", "Electronica"), ("Synthwave", "Retrowave"))
    assert settings.parse_root_tags('{"format": 1, "tags": {"genres": []}}').genres == ()


@pytest.mark.parametrize(
    "tags, problem",
    [
        ({"genres": "Jazz"}, "tags.genres isn't a list of genres"),
        ({"genres": ["Jazz", 5]}, "tags.genres isn't a list of genres"),
        ({"same_genres": {"Electronic": "Electronica"}}, "isn't a list of groups"),
        ({"same_genres": [["Electronic"]]}, "a group that isn't two genres or more"),
        ({"same_genres": [["Electronic", " "]]}, "a group that isn't two genres or more"),
        ({"same_genres": ["Electronic", "Electronica"]}, "a group that isn't two genres or more"),
        ({"same_genres": [["Electronic", None]]}, "a group that isn't two genres or more"),
    ],
)
def test_the_genre_settings_broken_or_in_another_form(tags, problem):
    """R13.9: a broken value is reported and its default used; a broken group alone is left out."""
    found = settings.parse_root_tags(json.dumps({"format": 1, "tags": tags}))
    assert found.genres is None and found.same_genres == ()
    assert [p for p in found.problems if problem in p]
    kept = settings.parse_root_tags(json.dumps({"format": 1, "tags": {
        "same_genres": [["Electronic"], ["Hip-Hop", "Rap"]]}}))  # fmt: skip
    assert kept.same_genres == (("Hip-Hop", "Rap"),) and len(kept.problems) == 1


def test_the_roots_own_settings_give_the_users_path_patterns_tried_before_the_presets():
    """R3.3, R13.4: the `patterns` group's `user`, as A2.10 names it, each once, in order."""
    assert settings.RootTags().patterns == ()
    found = settings.parse_root_tags(json.dumps({"format": 1, "patterns": {
        "user": ["{artist}/{album}/{track} - {title}", " {artist} - {title} ",
                 "{artist}/{album}/{track} - {title}", "{not a token}"],
        "organize": "{albumartist}/{album}/{track} - {title}",
    }}))  # fmt: skip
    assert found.patterns == ("{artist}/{album}/{track} - {title}", "{artist} - {title}",
                              "{not a token}")  # fmt: skip
    assert found.problems == ()


@pytest.mark.parametrize(
    "group, problem",
    [
        ("{artist} - {title}", "patterns isn't a group"),
        ({"user": "{artist} - {title}"}, "patterns.user isn't a list of patterns"),
        ({"user": ["{title}", 5, None, "  "]}, "patterns.user holds what isn't a pattern"),
    ],
)
def test_the_users_patterns_broken_or_in_another_form(group, problem):
    found = settings.parse_root_tags(json.dumps({"format": 1, "patterns": group}))
    assert [p for p in found.problems if problem in p]
    assert found.patterns in ((), ("{title}",))


@pytest.mark.parametrize(
    ("group", "layout", "problem"),
    [
        ({}, None, ""),
        ({"organize": " {artist}/{album}/{track:02} {title} "},
         "{artist}/{album}/{track:02} {title}", ""),
        ({"organize": ""}, None, "patterns.organize isn't a layout"),
        ({"organize": 5}, None, "patterns.organize isn't a layout"),
        ("x", None, "patterns isn't a group"),
    ],
)  # fmt: skip
def test_the_roots_own_settings_give_organize_files_layout(group, layout, problem):
    """R12.1, A2.10: the `patterns` group's `organize`, Organize files' layout (R13 edits it);
    the default when it has none or it isn't text."""
    found = settings.parse_root_tags(json.dumps({"format": 1, "patterns": group}))
    assert found.layout == layout
    assert any(problem in p for p in found.problems) if problem else not found.problems


# ---------- the Lyrics switch (R17.3), and where saved lyrics go (R13.11) ----------


@pytest.mark.parametrize(
    "appearance, on, problem",
    [
        ({"lyrics": True}, True, ""),
        ({}, False, ""),
        ({"lyrics": "true"}, False, "appearance.lyrics isn't true or false"),
        ({"lyrics": 1}, False, "appearance.lyrics isn't true or false"),
        ({"lyrics": None}, False, "appearance.lyrics isn't true or false"),
    ],
)
def test_the_lyrics_switch_is_read_from_appearance_off_by_default(appearance, on, problem):
    got = parse({"format": 1, "appearance": appearance})
    assert got.appearance.lyrics is on
    assert (problem in got.problems[0]) if problem else got.problems == ()


def test_the_lyrics_switch_set_keeps_the_file_valid_under_its_schema(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"format": 1, "appearance": {"visualization": "none", "x": 1}}))
    assert settings.set_appearance(str(path), HOME, "PC", lyrics=True)
    doc = json.loads(path.read_text())
    assert doc["appearance"] == {"visualization": "none", "x": 1, "lyrics": True}
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    assert settings.load(str(path), HOME).appearance.lyrics is True


@pytest.mark.parametrize(
    "text, save, problem",
    [
        ('{"format": 1, "lyrics": {"save": "tags"}}', "tags", ""),
        ('﻿{"lyrics": {"save": " Both "}}', "both", ""),
        ('{"format": 1}', "lrc", ""),
        ('{"lyrics": {}}', "lrc", ""),
        ('{"lyrics": {"save": "id3"}}', "lrc", "lyrics.save isn't lrc, tags or both"),
        ('{"lyrics": {"save": null}}', "lrc", "lyrics.save isn't lrc, tags or both"),
        ('{"lyrics": "tags"}', "lrc", "lyrics isn't a group"),
        ("[]", "lrc", "it isn't a JSON object"),
        ('{"lyrics": {"save": "t', "lrc", "it isn't JSON"),
    ],
)
def test_where_saved_lyrics_go_is_the_roots_lyrics_save_lrc_by_default(text, save, problem):
    """R13.11, A2.10: the root's `lyrics.save`, in any case and with spaces around it."""
    got, problems = settings.parse_root_lyrics(text)
    assert got == save
    assert (problem in problems[0]) if problem else problems == ()


def test_the_roots_lyrics_setting_is_read_from_its_settings_json(tmp_path, caplog):
    root = tmp_path / "Music"
    assert settings.root_lyrics(str(root)) == "lrc"  # no file
    (root / ".musikata").mkdir(parents=True)
    path = root / ".musikata" / "settings.json"
    path.write_text('{"format": 1, "lyrics": {"save": "both"}}')
    assert settings.root_lyrics(str(root)) == "both"
    path.write_text('{"format": 1, "lyrics": {"save": 3}}')
    assert settings.root_lyrics(str(root)) == "lrc" and "lyrics.save" in caplog.text
    path.unlink()
    path.mkdir()  # can't be read
    assert settings.root_lyrics(str(root)) == "lrc"


# ---------- the mini player (R15.2, R15.3) and Minimize MusiKata when it opens (R13.8) ----------


@pytest.mark.parametrize(
    "appearance, on, problem",
    [
        ({}, True, ""),
        ({"minimize_for_mini": False}, False, ""),
        ({"minimize_for_mini": "false"}, True, "appearance.minimize_for_mini isn't true or false"),
        ({"minimize_for_mini": 0}, True, "appearance.minimize_for_mini isn't true or false"),
        ({"minimize_for_mini": None}, True, "appearance.minimize_for_mini isn't true or false"),
    ],
)
def test_minimizing_for_the_mini_player_is_read_from_appearance_on_by_default(
    appearance, on, problem
):
    got = parse({"format": 1, "appearance": appearance})
    assert got.appearance.minimize_for_mini is on
    assert (problem in got.problems[0]) if problem else got.problems == ()


def test_the_mini_player_is_read_from_its_group_card_and_on_top_by_default():
    got = parse({
        "format": 1,
        "mini_player": {"layout": "remote", "stay_on_top": False, "later": 1,
                        "places": {"remote": {"x": 1650, "y": 980, "w": 246, "h": 76},
                                   "card": {"x": -40, "y": 80, "w": 300, "h": 582}}},
    })  # fmt: skip
    assert got.problems == ()
    assert got.mini_player == settings.MiniPlayer(
        "remote", False, {"remote": (1650, 980, 246, 76), "card": (-40, 80, 300, 582)}
    )
    assert parse({"format": 1}).mini_player == settings.MiniPlayer("card", True, {})


@pytest.mark.parametrize(
    "group, layout, on_top, places, problem",
    [
        ({"layout": " Disc "}, "disc", True, {}, ""),  # as a person writes it
        ({"layout": "mini"}, "card", True, {}, "mini_player.layout isn't one of"),
        ({"layout": 3}, "card", True, {}, "mini_player.layout isn't one of"),
        ({"layout": None}, "card", True, {}, "mini_player.layout isn't one of"),
        ({"stay_on_top": "yes"}, "card", True, {}, "mini_player.stay_on_top isn't true or false"),
        ({"stay_on_top": 0}, "card", True, {}, "mini_player.stay_on_top isn't true or false"),
        ([], "card", True, {}, "mini_player isn't a group"),
        ({"places": []}, "card", True, {}, "mini_player.places isn't a group"),
        # a hand edit's numbers as text and whole fractions, a layout's name in another case
        (
            {"places": {"Cover": {"x": "10", "y": 20.0, "w": " 300 ", "h": 300}}},
            "card",
            True,
            {"cover": (10, 20, 300, 300)},
            "",
        ),
        # a newer MusiKata's layout: left in the file, not read
        ({"places": {"wall": {"x": 1, "y": 1, "w": 1, "h": 1}, "7": {}}}, "card", True, {}, ""),
        (
            {"places": {"card": {"x": 1, "y": 1, "w": 300}}},
            "card",
            True,
            {},
            "mini_player.places.card isn't a place and size",
        ),
        (
            {"places": {"card": {"x": 1, "y": 1, "w": 0, "h": 5}}},
            "card",
            True,
            {},
            "mini_player.places.card isn't a place and size",
        ),
        (
            {"places": {"card": {"x": 1.5, "y": 1, "w": 300, "h": 5}}},
            "card",
            True,
            {},
            "mini_player.places.card isn't a place and size",
        ),
        (
            {"places": {"card": {"x": True, "y": 1, "w": 300, "h": 5}}},
            "card",
            True,
            {},
            "mini_player.places.card isn't a place and size",
        ),
        (
            {"places": {"card": {"x": float("nan"), "y": 1, "w": 300, "h": 5}}},
            "card",
            True,
            {},
            "mini_player.places.card isn't a place and size",
        ),
        (
            {"places": {"card": "1600,80"}},
            "card",
            True,
            {},
            "mini_player.places.card isn't a place and size",
        ),
    ],
)
def test_the_mini_player_broken_in_another_case_type_or_shape(
    group, layout, on_top, places, problem
):
    got = parse({"format": 1, "mini_player": group})
    assert got.mini_player == settings.MiniPlayer(layout, on_top, places)
    assert (problem in got.problems[0]) if problem else got.problems == ()


def test_the_mini_player_set_keeps_its_other_places_and_the_file_valid_under_its_schema(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "format": 1,
        "mini_player": {"layout": "card", "later": 1,
                        "places": {"card": {"x": 1600, "y": 80, "w": 300, "h": 582},
                                   "wall": {"x": 0, "y": 0, "w": 9, "h": 9}}},
    }))  # fmt: skip
    assert settings.set_mini_player(str(path), HOME, "PC", layout="remote")
    assert settings.set_mini_player(str(path), HOME, "PC", stay_on_top=False)
    assert settings.set_mini_player(
        str(path), HOME, "PC", places={"remote": {"x": 1650, "y": 980, "w": 246, "h": 76}}
    )
    doc = json.loads(path.read_text())
    assert doc["mini_player"] == {
        "layout": "remote", "later": 1, "stay_on_top": False,
        "places": {"card": {"x": 1600, "y": 80, "w": 300, "h": 582},
                   "wall": {"x": 0, "y": 0, "w": 9, "h": 9},
                   "remote": {"x": 1650, "y": 980, "w": 246, "h": 76}},
    }  # fmt: skip
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    kept = settings.load(str(path), HOME).mini_player
    assert kept.layout == "remote" and not kept.stay_on_top and kept.places["card"][0] == 1600
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"format": 1, "mini_player": {"places": "none"}}))
    assert settings.set_mini_player(str(broken), HOME, "PC", places={"card": {"x": 1}})
    assert json.loads(broken.read_text())["mini_player"]["places"] == {"card": {"x": 1}}
    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps({"format": 2}))
    assert not settings.set_mini_player(str(newer), HOME, "PC", layout="disc")


# ---------- the equalizer (R19.5) ----------

EQUALIZER = {  # A2.10's example
    "on": True, "preset": "Car", "by_genre": True,
    "presets": [
        {"name": "Car", "kind": "graphic", "preamp": -2.0,
         "gains": [4.0, 3.5, 1.5, 0.0, -1.0, 0.0, 1.0, 2.0, 2.5, 2.0]},
        {"name": "Late night", "kind": "parametric", "preamp": -3.0,
         "bands": [{"type": "low-shelf", "freq": 100, "gain": 3.0, "q": 0.7},
                   {"type": "high-cut", "freq": 12000, "q": 0.7}]},
    ],
    "genres": {"Classical": "Classical", "Jazz": "Jazz", "Electronic": "Late night"},
}  # fmt: skip


def test_the_equalizer_is_read_from_its_group_as_a2_10s_example_has_it():
    from musikata_core.audio.eq import Band
    from musikata_core.audio.presets import Preset

    got = parse({"format": 1, "equalizer": EQUALIZER})
    assert got.problems == ()
    assert got.equalizer == settings.Equalizer(
        True, "Car", True,
        (Preset("Car", "graphic", -2.0, gains=(4.0, 3.5, 1.5, 0.0, -1.0, 0.0, 1.0, 2.0, 2.5, 2.0)),
         Preset("Late night", "parametric", -3.0,
                (Band("low-shelf", 100, 3.0, 0.7), Band("high-cut", 12000, 0.0, 0.7)))),
        {"Classical": "Classical", "Jazz": "Jazz", "Electronic": "Late night"},
    )  # fmt: skip


def test_the_equalizer_is_off_at_flat_by_default_with_the_built_in_genres_matched():
    got = parse({"format": 1}).equalizer
    assert got == settings.Equalizer()
    assert (got.on, got.preset, got.by_genre, got.presets) == (False, "Flat", False, ())
    assert got.genres["Classical"] == "Classical" and got.genres["Rock"] == "Rock"


def _eq_with(**changed):
    return {**EQUALIZER, **changed}


@pytest.mark.parametrize(
    "group, check, problem",
    [
        ([], lambda e: e == settings.Equalizer(), "equalizer isn't a group"),
        (_eq_with(on="yes"), lambda e: e.on is False, "equalizer.on isn't true or false"),
        (_eq_with(by_genre=1), lambda e: e.by_genre is False, "equalizer.by_genre isn't true"),
        (_eq_with(preset=" car "), lambda e: e.preset == "Car", ""),  # as a person writes it
        (_eq_with(preset="rock"), lambda e: e.preset == "Rock", ""),
        (_eq_with(preset="Gone"), lambda e: e.preset == "Flat", "equalizer.preset isn't a preset"),
        (_eq_with(preset=3), lambda e: e.preset == "Flat", "equalizer.preset isn't a preset"),
        (_eq_with(presets={}), lambda e: e.presets == () and e.preset == "Flat",
         "equalizer.presets isn't a list"),
        (_eq_with(presets=["Car"]), lambda e: e.presets == (), "isn't a preset: 'Car'"),
        (_eq_with(presets=[{"kind": "graphic"}]), lambda e: e.presets == (), ".name isn't a name"),
        (_eq_with(preset="A", genres={},
                  presets=[{"name": "A", "kind": "Graphic", "gains": [0] * 10}]),
         lambda e: e.presets[0].kind == "graphic" and e.presets[0].preamp == 0, ""),
        (_eq_with(presets=[{"name": "A", "kind": "shelf", "bands": []}]), lambda e: e.presets == (),
         ".kind isn't parametric or graphic"),
        (_eq_with(presets=[{"name": "A", "kind": "graphic", "preamp": "-3 dB",
                            "gains": ["1", 2, "3,5", 0, 0, 0, 0, 0, 0, 20]}]),
         lambda e: e.presets[0].gains[:3] == (1, 2, 3.5) and e.presets[0].gains[9] == 12
         and e.presets[0].preamp == -3, "gains[9] is out of -12 to 12"),
        (_eq_with(presets=[{"name": "A", "kind": "graphic", "gains": [0] * 9}]),
         lambda e: e.presets == (), ".gains isn't ten gains"),
        (_eq_with(presets=[{"name": "A", "kind": "graphic", "gains": [0] * 9 + [True]}]),
         lambda e: e.presets == (), "gains[9] isn't a number"),
        (_eq_with(presets=[{"name": "A", "kind": "parametric", "bands": []}]),
         lambda e: e.presets == (), ".bands holds no band"),
        (_eq_with(presets=[{"name": "A", "kind": "parametric", "bands": "LS 100"}]),
         lambda e: e.presets == (), ".bands isn't a list of bands"),
        (_eq_with(presets=[{"name": "A", "kind": "parametric",
                            "bands": [{"type": "Low Shelf", "freq": "100", "gain": 3, "q": 0.7},
                                      {"type": "notch", "freq": 100, "q": 1}, 5]}]),
         lambda e: e.presets[0].bands[0].type == "low-shelf" and len(e.presets[0].bands) == 1,
         ".type isn't one of"),
        (_eq_with(presets=[{"name": "A", "kind": "parametric",
                            "bands": [{"type": "bell", "freq": 5, "gain": -30, "q": 0}]}]),
         lambda e: (e.presets[0].bands[0].freq, e.presets[0].bands[0].gain,
                    e.presets[0].bands[0].q) == (20, -12, 0.1), ".freq is out of 20 to 20000"),
        (_eq_with(presets=[{"name": "A", "kind": "parametric",
                            "bands": [{"type": "bell", "freq": None, "gain": 1, "q": 1}]}]),
         lambda e: e.presets == (), ".freq isn't a number"),
        (_eq_with(presets=[{"name": "A", "kind": "parametric",
                            "bands": [{"type": "bell", "freq": 100 * i, "q": 1}
                                      for i in range(1, 13)]}]),
         lambda e: len(e.presets[0].bands) == 10, "more than 10 bands: the first 10 kept"),
        (_eq_with(presets=[{"name": "A", "kind": "graphic", "gains": [0] * 10,
                            "from_bands": "x"}]),
         lambda e: e.presets[0].from_bands is None, ".from_bands isn't a list of bands"),
        (_eq_with(presets=[EQUALIZER["presets"][0], EQUALIZER["presets"][0]]),
         lambda e: len(e.presets) == 1, "is named as one before it"),
        (_eq_with(presets=[{**EQUALIZER["presets"][0], "name": "rock"}]),
         lambda e: e.presets == (), "is named as one before it"),  # a built-in's name
        (_eq_with(genres=[]), lambda e: e.genres["Rock"] == "Rock",
         "equalizer.genres isn't a group of genres"),
        (_eq_with(genres={}), lambda e: e.genres == {}, ""),  # every genre taken off the table
        (_eq_with(genres={"Ambient": "Gone", "Rock": 3, " Pop ": "pop"}),
         lambda e: e.genres == {"Pop": "Pop"}, "equalizer.genres.Ambient isn't a preset"),
    ],
)  # fmt: skip
def test_the_equalizer_broken_in_another_case_type_or_shape(group, check, problem):
    got = parse({"format": 1, "equalizer": group})
    assert check(got.equalizer), got.equalizer
    assert (problem in " ".join(got.problems)) if problem else got.problems == ()


def test_the_equalizer_set_keeps_the_rest_of_the_file_and_what_it_doesnt_know(tmp_path):
    from musikata_core.audio import presets

    path = tmp_path / "settings.json"
    old = {
        **EQUALIZER,
        "later": 1,
        "presets": [{**EQUALIZER["presets"][0], "colour": "red"}, EQUALIZER["presets"][1]],
    }
    path.write_text(json.dumps({"format": 1, "equalizer": old, "appearance": {"lyrics": True}}))
    assert settings.set_equalizer(str(path), HOME, "PC", on=False)
    assert settings.set_equalizer(str(path), HOME, "PC", preset="Late night", by_genre=False)
    kept = settings.load(str(path), HOME).equalizer
    rock, _ = presets.to_graphic(presets.find("Rock", ()), "Rock (graphic)")
    assert settings.set_equalizer(str(path), HOME, "PC", presets=[*kept.presets, rock])
    doc = json.loads(path.read_text())
    assert doc["appearance"] == {"lyrics": True} and doc["equalizer"]["later"] == 1
    assert doc["equalizer"]["presets"][0]["colour"] == "red"  # a preset's unknown field kept
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    again = settings.load(str(path), HOME).equalizer
    assert (again.on, again.preset, again.by_genre) == (False, "Late night", False)
    assert again.presets == (*kept.presets, rock) and again.genres == kept.genres
    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps({"format": 2}))
    assert not settings.set_equalizer(str(newer), HOME, "PC", on=True)
