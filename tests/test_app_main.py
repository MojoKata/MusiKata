"""Starting MusiKata (src/musikata/app.py, __main__.py): the command line, the root's index where
A2.9 puts it, the window loaded over it, and a whole run: `python -m musikata --tour`."""

import os
import subprocess
import sys

import pytest
from fakes import FakeClock

from musikata import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_root_is_given_or_the_homes_music_folder(tmp_path):
    env = {"HOME": str(tmp_path)}
    assert app.options([], env) == app.Options(str(tmp_path / "Music"))
    got = app.options(["--root", str(tmp_path / "x" / ".." / "Songs"), "--tour", "out",
                       "--tour-only", "L03-songs"], env)  # fmt: skip
    assert got == app.Options(str(tmp_path / "Songs"), "out", "L03-songs")
    got = app.options(["--play", str(tmp_path / "a" / ".." / "x.mp3")], env)
    assert got.play == str(tmp_path / "x.mp3") and got.tour is None
    assert app.home_of({"USERPROFILE": "C:\\Users\\ana"}) == "C:\\Users\\ana"
    assert app.home_of({}) == os.path.expanduser("~")


def test_the_index_is_made_under_the_data_folder_and_found_again(tmp_path):
    env = {"MUSIKATA_DATA": str(tmp_path / "data")}
    (tmp_path / "Music").mkdir()
    first = app.open_index(str(tmp_path / "Music"), env, FakeClock())
    first.close()
    again = app.open_index(str(tmp_path / "Music"), env, FakeClock())
    assert again.path == first.path and again.path.startswith(str(tmp_path / "data" / "roots"))
    assert os.path.basename(again.path) == "musikata.db"
    again.close()


def test_the_covers_are_cached_under_the_roots_key_beside_the_other_roots(tmp_path):
    env = {"MUSIKATA_DATA": str(tmp_path / "data")}
    (tmp_path / "Music").mkdir()
    index = app.open_index(str(tmp_path / "Music"), env, FakeClock())
    key = os.path.basename(os.path.dirname(index.path))
    assert app.cache_of(index, env) == str(tmp_path / "data" / "cache" / key / "covers")
    index.close()


def test_a_window_that_doesnt_load_says_so(tmp_path, monkeypatch, qtbot):
    monkeypatch.setattr(app, "QML", str(tmp_path / "Missing.qml"))
    with pytest.raises(RuntimeError, match="didn't load"):
        app.load(str(tmp_path), {"MUSIKATA_DATA": str(tmp_path / "d")}, FakeClock())


def run(*args):
    path = os.pathsep.join(
        p for p in (os.path.join(ROOT, "src"), os.environ.get("PYTHONPATH")) if p
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=path)
    return subprocess.run([sys.executable, "-m", "musikata", *args], env=env, cwd=ROOT,
                          capture_output=True, text=True, timeout=120)  # fmt: skip


def test_the_version():
    from musikata_core import __version__

    r = run("--version")
    assert r.returncode == 0 and r.stdout.strip() == f"MusiKata {__version__}"


@pytest.mark.slow
def test_a_whole_run_scans_the_root_and_tours_it(tmp_path):
    (tmp_path / "Music").mkdir()
    (tmp_path / "Music" / "Undertow.flac").write_bytes(b"not audio")
    r = run("--root", str(tmp_path / "Music"), "--tour", str(tmp_path / "tour"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "added=1" in r.stderr and "the tour: 5 screens, 0 texts past their boxes" in r.stdout
    assert (tmp_path / "tour" / "L03-songs.png").exists()


def test_play_ends_with_0_only_when_the_song_played_to_its_end_and_the_scan_went_well():
    ok = object()  # a scan's Result
    assert app.outcome("ended", "", ok) == (0, "played to its end")
    assert app.outcome("ended", "", None) == (0, "played to its end")
    assert app.outcome("failed", "there is no sound device", ok) == (
        1,
        "couldn't play: there is no sound device",
    )
    assert app.outcome("stopped", "", ok) == (1, "closed before the song ended")
    assert app.outcome("", "", ok) == (1, "closed before the song ended")
    assert app.outcome("ended", "", OSError("gone")) == (1, "the scan failed: OSError: gone")


def test_play_with_no_sound_device_ends_with_3_when_the_file_decoded_to_its_end():
    nothing = "there is no sound device"
    assert app.outcome("failed", nothing, None, 3.04) == (
        3,
        "decoded to its end (3.0 s); there is no sound device to play it on",
    )
    assert app.outcome("failed", nothing, None) == (1, f"couldn't play: {nothing}")
    assert app.outcome("failed", nothing, OSError("gone"), 3.0)[0] == 1
