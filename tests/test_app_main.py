"""Starting MusiKata (src/musikata/app.py, __main__.py): the command line, the root's index where
A2.9 puts it, the window loaded over it, and a whole run: `python -m musikata --tour`."""

import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock
from PySide6.QtCore import QUrl

from musikata import app, media, tour
from musikata_core import roots, settings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_root_is_given_for_the_run_or_none_for_the_configured_one(tmp_path):
    env = {"HOME": str(tmp_path)}
    assert app.options([], env) == app.Options(None)
    got = app.options(["--root", str(tmp_path / "x" / ".." / "Songs"), "--tour", "out",
                       "--tour-only", "L03-songs"], env)  # fmt: skip
    assert got == app.Options(str(tmp_path / "Songs"), "out", "L03-songs")
    got = app.options(["--play", str(tmp_path / "a" / ".." / "x.mp3")], env)
    assert got.play == str(tmp_path / "x.mp3") and got.tour is None
    assert app.home_of({"USERPROFILE": "C:\\Users\\ana"}) == "C:\\Users\\ana"
    assert app.home_of({}) == os.path.expanduser("~")


def test_the_run_opens_root_given_else_the_configured_one_else_asks_for_one():
    """R2.1, R2.1.2; --play with neither plays from its file's folder, so a build's start test
    never waits on a first start."""
    assert app.root_for(app.Options("/usb"), "/m") == ("/usb", True)
    assert app.root_for(app.Options(None), "/m") == ("/m", False)
    assert app.root_for(app.Options(None, play="/t/demo.mp3"), "/m") == ("/m", False)
    assert app.root_for(app.Options(None, play="/t/demo.mp3"), None) == ("/t", True)
    assert app.root_for(app.Options(None), None) == (None, False)


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
    assert (
        "added=1" in r.stderr
        and f"the tour: {len(tour.screens('library'))} screens, 0 texts past their boxes"
        in r.stdout
    )
    assert (tmp_path / "tour" / "L03-songs.png").exists()


@pytest.mark.slow
def test_a_whole_first_run_with_nothing_configured_asks_for_the_root(tmp_path):
    """No --root and no settings (own_home's empty home): the first start's window (X01)."""
    r = run("--tour", str(tmp_path / "tour"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "the tour: 1 screens, 0 texts past their boxes" in r.stdout
    assert (tmp_path / "tour" / "X01-first-run.png").exists()


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


def test_a_root_that_isnt_there_opens_the_index_that_last_opened_it_making_nothing(tmp_path):
    env = {"MUSIKATA_DATA": str(tmp_path / "data")}
    music = tmp_path / "Music"
    music.mkdir()
    first = app.open_index(str(music), env, FakeClock())
    first.close()
    shutil.rmtree(music)  # unplugged (R2.10)
    again = app.open_index(str(music), env, FakeClock())
    assert again.path == first.path and not music.exists()
    again.close()
    never = app.open_index(str(tmp_path / "Never"), env, FakeClock())
    assert os.path.basename(os.path.dirname(never.path)).startswith("path-")
    assert not (tmp_path / "Never").exists()
    never.close()


# ---------- a run: the first start, and a root chosen (R2.1, R2.10) ----------


def session(tmp_path, given=False, controls=media.start):
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.Session(env, FakeClock(), given, lambda: ThreadPoolExecutor(1), controls=controls)
    return s, env


def recording(events):
    """A start of the system's media controls that says when each window's start and close."""

    def start(player, window, art):
        controls, n = media.MediaControls(player, None, art, window), len(events)
        close = controls.close
        controls.close = lambda: (events.append(("closed", n)), close())
        events.append(("started", n))
        return controls

    return start


@pytest.mark.slow
def test_at_start_roots_not_opened_for_180_days_go_off_the_gui_thread_but_the_one_opened(
    tmp_path, qtbot, caplog
):
    """A2.9: the index and caches of every root not opened for 180 days are removed at start, on
    a thread of their own, and the App log names each; the root being opened keeps its own, though
    it isn't there and so isn't opened anew (R2.10)."""
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    base, caches, clock = roots.roots_dir(env), roots.caches_dir(env), FakeClock()
    music, old, recent = tmp_path / "Music", tmp_path / "Old", tmp_path / "Recent"
    for folder in (music, old, recent):
        folder.mkdir()
    long_ago = {f: roots.find_index(str(f), base, clock) for f in (music, old)}
    clock.advance(days=181)
    kept = roots.find_index(str(recent), base, clock)
    for found in (*long_ago.values(), kept):
        os.makedirs(os.path.join(caches, found.key, "covers"))
    shutil.rmtree(music)  # its drive unplugged: opened from the index that last opened it
    caplog.set_level("INFO")
    s = app.Session(env, clock, False, lambda: ThreadPoolExecutor(1), controls=media.start)
    s.start(str(music))
    gone = long_ago[old]
    qtbot.waitUntil(lambda: not os.path.exists(gone.folder), timeout=10_000)
    s.close()
    assert not os.path.exists(os.path.join(caches, gone.key))
    for found in (long_ago[music], kept):
        assert os.path.exists(found.folder) and os.path.exists(os.path.join(caches, found.key))
    said = [r for r in caplog.records if "not opened for 180 days" in r.getMessage()]
    assert len(said) == 1 and str(old) in said[0].getMessage() and gone.key in said[0].getMessage()
    assert said[0].threadName == "cleanup"


def test_the_first_start_asks_and_the_folder_chosen_becomes_the_configured_root(tmp_path, qtbot):
    s, env = session(tmp_path)
    s.start(None)
    assert s.library is None and s.first is not None and s.window is s.first.window
    s.window.setGeometry(40, 50, 1100, 700)
    s.window.show()
    music = tmp_path / "Tunes"
    music.mkdir()
    with qtbot.waitSignal(s.opened):
        s.first.first.choose(QUrl.fromLocalFile(str(music)).toString())
    assert s.first is None and s.library is not None
    assert s.library.property("root") == os.path.join("~", "Tunes")
    assert s.window.title() == "MusiKata"  # the configured root: the title doesn't name it
    assert (s.window.width(), s.window.height()) == (1100, 700) and s.window.isVisible()
    path = settings.shared_path(env)
    assert settings.load(path, str(tmp_path)).root == str(music)
    qtbot.waitUntil(lambda: not s.library.scanning, timeout=10_000)
    s.close()


def test_choose_another_folder_opens_it_in_the_windows_place_and_keeps_it(tmp_path, qtbot):
    events = []
    s, env = session(tmp_path, controls=recording(events))
    gone = tmp_path / "Music"
    s.start(str(gone))
    assert s.library.property("available") is False
    other = tmp_path / "Other"
    other.mkdir()
    old = s.shell
    with qtbot.waitSignal(s.opened):
        s.library.chooseRoot(str(other))
    assert s.shell is not old and s.library.property("root") == os.path.join("~", "Other")
    assert settings.load(settings.shared_path(env), str(tmp_path)).root == str(other)
    # the system's controls let go before the new window's take them (MPRIS has one name)
    assert events[:3] == [("started", 0), ("closed", 0), ("started", 2)]
    qtbot.waitUntil(lambda: not s.library.scanning, timeout=10_000)
    s.close()


def test_a_root_given_for_the_run_is_named_in_the_title_and_never_kept(tmp_path, qtbot):
    s, env = session(tmp_path, given=True)
    usb = tmp_path / "usb"
    usb.mkdir()
    s.start(str(usb))
    assert s.window.title() == f"MusiKata — {os.path.join('~', 'usb')}"
    other = tmp_path / "Other"
    other.mkdir()
    with qtbot.waitSignal(s.opened):
        s.library.chooseRoot(str(other))
    assert s.window.title() == f"MusiKata — {os.path.join('~', 'Other')}"
    assert not os.path.exists(settings.shared_path(env))
    qtbot.waitUntil(lambda: not s.library.scanning, timeout=10_000)
    s.close()


def test_the_first_starts_window_that_doesnt_load_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "FIRST_QML", str(tmp_path / "Missing.qml"))
    with pytest.raises(RuntimeError, match="didn't load"):
        app.first_start({"HOME": str(tmp_path)})


def test_a_session_not_started_has_no_window(tmp_path):
    s, _ = session(tmp_path)
    with pytest.raises(AssertionError, match="hasn't started"):
        s.window  # noqa: B018
    s.close()
