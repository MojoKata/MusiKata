"""A root's id and finding its index (src/musikata_core/roots.py; A2.9, R1.5): where this computer
keeps indexes, a root found again at another path, a copy given its own, a root that can't be
written kept by its path, and indexes not opened for 180 days removed.

Why: the index is rebuilt from the files, but at 50,000 songs that is minutes; a drive that comes
back as F: instead of E:, or a copy made for a party, must find its own index and not another's."""

import json
import os
import shutil
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeClock

from musikata_core import clock, roots


def test_where_each_platform_keeps_its_indexes_and_musikata_data_moves_them():
    env = {"HOME": "/h"}
    assert roots.roots_dir(env, "linux") == "/h/.local/share/musikata/roots"
    assert roots.roots_dir({**env, "XDG_DATA_HOME": "/x"}, "linux") == "/x/musikata/roots"
    assert roots.roots_dir(env, "darwin") == "/h/Library/Application Support/MusiKata/Roots"
    win = roots.roots_dir({"USERPROFILE": "/u", "LOCALAPPDATA": "/l"}, "win32")
    assert win == os.path.join("/l", "MusiKata", "Roots")
    assert roots.roots_dir({**env, "MUSIKATA_DATA": "/d"}, "linux") == "/d/roots"


def test_where_each_platform_keeps_its_caches_and_musikata_data_moves_them():
    env = {"HOME": "/h"}
    assert roots.caches_dir(env, "linux") == os.path.join("/h", ".cache", "musikata")
    assert roots.caches_dir({**env, "XDG_CACHE_HOME": "/x"}, "linux") == os.path.join(
        "/x", "musikata"
    )
    assert roots.caches_dir(env, "darwin") == os.path.join("/h", "Library", "Caches", "MusiKata")
    assert roots.caches_dir({"USERPROFILE": "/u"}, "win32") == os.path.join(
        "/u", "AppData", "Local", "MusiKata", "Cache"
    )
    assert roots.caches_dir({"LOCALAPPDATA": "/l"}, "win32") == os.path.join(
        "/l", "MusiKata", "Cache"
    )
    assert roots.caches_dir({**env, "MUSIKATA_DATA": "/d"}, "linux") == os.path.join("/d", "cache")


def test_decide_a_root_seen_at_its_path_moved_or_copied():
    assert roots.decide(None, "/m", False) == "use"
    assert roots.decide("/m", "/m", True) == "use"
    assert roots.decide("/old", "/new", False) == "moved"
    assert roots.decide("/old", "/new", True) == "copy"


def _root(tmp_path, name="Music"):
    r = tmp_path / name
    (r / "Artist").mkdir(parents=True)
    return str(r)


def test_a_new_root_gets_an_id_in_root_json_and_an_index_named_by_it(tmp_path):
    root, base = _root(tmp_path), str(tmp_path / "roots")
    found = roots.find_index(root, base, FakeClock())
    data = json.loads((tmp_path / "Music" / ".musikata" / "root.json").read_text())
    assert data["format"] == 1 and found.key == data["id"] and found.writable
    assert found.folder == os.path.join(base, data["id"])
    with open(os.path.join(found.folder, "index.json")) as f:
        index = json.load(f)
    assert index["path"] == os.path.realpath(root)
    again = roots.find_index(root, base, FakeClock())
    assert again == found


def test_a_root_mounted_at_another_path_keeps_its_index(tmp_path):
    root, base = _root(tmp_path), str(tmp_path / "roots")
    first = roots.find_index(root, base, FakeClock())
    moved = str(tmp_path / "Mounted")
    os.rename(root, moved)
    second = roots.find_index(moved, base, FakeClock())
    assert second.key == first.key and second.folder == first.folder
    with open(os.path.join(second.folder, "index.json")) as f:
        index = json.load(f)
    assert index["path"] == os.path.realpath(moved)


def test_a_copy_beside_its_original_gets_an_id_and_index_of_its_own(tmp_path):
    root, base = _root(tmp_path), str(tmp_path / "roots")
    first = roots.find_index(root, base, FakeClock())
    copy = str(tmp_path / "Copy")
    shutil.copytree(root, copy)
    second = roots.find_index(copy, base, FakeClock())
    assert second.key != first.key and roots.root_id(copy) == second.key
    assert roots.root_id(root) == first.key


def test_root_json_keeps_fields_a_later_version_added_when_an_id_is_written(tmp_path):
    root = _root(tmp_path)
    meta = tmp_path / "Music" / ".musikata"
    meta.mkdir()
    (meta / "root.json").write_text(json.dumps({"format": 1, "added_later": [1]}))
    roots.find_index(root, str(tmp_path / "roots"), FakeClock())
    data = json.loads((meta / "root.json").read_text())
    assert data["added_later"] == [1] and data["id"]


@pytest.mark.skipif(
    os.geteuid() == 0 if hasattr(os, "geteuid") else True, reason="root writes anyway"
)
def test_a_root_that_cant_be_written_is_kept_under_a_hash_of_its_path(tmp_path):
    root = _root(tmp_path)
    os.chmod(root, 0o555)
    try:
        found = roots.find_index(root, str(tmp_path / "roots"), FakeClock())
    finally:
        os.chmod(root, 0o755)
    assert found.key == roots.path_key(root) and not found.writable
    assert not os.path.exists(os.path.join(root, ".musikata"))


def test_indexes_not_opened_for_180_days_are_removed_and_the_log_says_so(tmp_path, caplog):
    base, clock_ = str(tmp_path / "roots"), FakeClock()
    old = roots.find_index(_root(tmp_path, "Old"), base, clock_)
    clock_.advance(days=100)
    recent = roots.find_index(_root(tmp_path, "Recent"), base, clock_)
    clock_.advance(days=81)
    caplog.set_level("INFO")
    assert roots.remove_stale(base, clock_, keep=recent.key) == [old.key]
    assert not os.path.exists(old.folder) and os.path.exists(recent.folder)
    assert old.key in caplog.text
    assert roots.remove_stale(str(tmp_path / "none"), clock_) == []


def test_stale_is_strictly_past_180_days():
    now = datetime(2026, 11, 25, tzinfo=UTC)
    opened = {"a": now - timedelta(days=180), "b": now - timedelta(days=181)}
    assert roots.stale(opened, now) == ["b"]


def test_the_system_clock_is_utc_and_monotonic():
    c = clock.SystemClock()
    assert c.now().tzinfo is not None and c.monotonic() <= c.monotonic()


def test_a_root_that_isnt_there_finds_the_index_that_last_opened_it_touching_nothing(tmp_path):
    base, music = str(tmp_path / "roots"), tmp_path / "Music"
    music.mkdir()
    first = roots.find_index(str(music), base, FakeClock())
    later = FakeClock(datetime(2026, 11, 26, tzinfo=UTC))
    copy = tmp_path / "copy"
    copy.mkdir()
    other = roots.find_index(str(copy), base, later)  # another root, opened later
    shutil.rmtree(music)  # its drive unplugged (R2.10)
    found = roots.recorded(str(music), base)
    assert found == roots.Found(first.folder, first.key, False) and found.key != other.key
    assert not music.exists()  # nothing made where the root was
    assert roots.recorded(str(tmp_path / "Never"), base) is None
    assert roots.recorded(str(music), str(tmp_path / "no-roots")) is None


def test_of_two_indexes_that_opened_one_path_the_last_opened_is_found(tmp_path):
    base = tmp_path / "roots"
    for name, when in (("old", "2026-01-01T00:00:00+00:00"), ("new", "2026-06-01T00:00:00+00:00"),
                       ("odd", None)):  # fmt: skip
        (base / name).mkdir(parents=True)
        record = {"format": 1, "path": os.path.realpath(str(tmp_path / "Music"))}
        if when:
            record["opened"] = when
        (base / name / "index.json").write_text(json.dumps(record))
    assert roots.recorded(str(tmp_path / "Music"), str(base)).key == "new"
