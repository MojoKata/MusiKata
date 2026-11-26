"""MPRIS 2 on a session bus (R7.8, A4.5; src/musikata/media/mpris.py), as a desktop sees it: a
private bus started for each test (`dbus-daemon --session`, killed by its PID), MusiKata's player
(the Player bridge over an index, its engine a stand-in that plays nothing) on it, and the desktop
played by D-Bus's own client, `dbus-send`, which prints each value with its D-Bus type, and
`dbus-monitor`, which prints the signals. A test waits on the client's answer or the signal it
looks for, never a set time.

Why: a desktop reads MPRIS by D-Bus's types (a GLib client looks the length up as an int64 and finds
nothing in an int32), so a value of the wrong type is a song without a length, or a sound menu that
can't seek, on a desktop the tests don't run; and the methods are called by the desktop, never by
MusiKata's own code."""

import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading

import pytest
from fakes import FakeEngine, fill
from PySide6.QtDBus import QDBusConnection
from PySide6.QtGui import QWindow

from musikata import bridges, media
from musikata.media import controls, mpris
from musikata_core import db

pytestmark = [
    pytest.mark.slow,  # each starts a bus and asks it as a desktop does
    pytest.mark.skipif(
        not sys.platform.startswith("linux") or shutil.which("dbus-daemon") is None,
        reason="MPRIS is Linux's (A4.5), on a D-Bus daemon",
    ),
]

WAIT = 10_000
SONGS = [
    {"path": "LD/GH/01.flac", "title": "Tidewater", "artist": "Lumen Drift",
     "album": "Glass Harbor", "track": 1, "length": 200.0},
    {"path": "LD/GH/02.flac", "title": "Glass Harbor", "artist": "Lumen Drift",
     "album": "Glass Harbor", "track": 2, "length": 100.0},
]  # fmt: skip


@pytest.fixture
def bus():
    """A session bus of the test's own: its address. The daemon is killed by its PID."""
    out = subprocess.run(
        ["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout.split()  # fmt: skip
    address, pid = out[0], int(out[1])
    yield address
    os.kill(pid, signal.SIGTERM)


class Desktop:
    """The desktop's side: asks MusiKata's player with dbus-send, and hears its signals with
    dbus-monitor, started at once."""

    def __init__(self, address, qtbot):
        self.address, self.qtbot = address, qtbot
        self.dest = mpris.SERVICE
        self._heard = []
        self._monitor = subprocess.Popen(
            ["dbus-monitor", "--address", address, f"type='signal',path='{mpris.PATH}'"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )  # fmt: skip
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        # the monitor is listening once the bus has told it its name
        qtbot.waitUntil(lambda: "NameAcquired" in self.heard(), timeout=WAIT)

    def _read(self):
        for line in self._monitor.stdout:
            self._heard.append(line)

    def heard(self):
        """What the monitor printed, its lines joined and its spaces made single."""
        return " ".join(" ".join(self._heard).split())

    def ask(self, method, *args, path=mpris.PATH, ok=True):
        """dbus-send's reply to `method` (interface.Member), its words joined by single spaces,
        after the line that says it is a reply; the Qt event loop runs while it waits, so MusiKata
        answers."""
        p = subprocess.Popen(
            ["dbus-send", f"--bus={self.address}", "--print-reply", f"--dest={self.dest}", path,
             method, *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )  # fmt: skip
        self.qtbot.waitUntil(lambda: p.poll() is not None, timeout=WAIT)
        out = p.stdout.read()
        assert (p.returncode == 0) == ok, out
        return " ".join(out.split("\n", 1)[-1].split())

    def get(self, interface, name):
        return self.ask(f"{mpris.PROPERTIES}.Get", f"string:{interface}", f"string:{name}")

    def close(self):
        self._monitor.terminate()
        self._monitor.wait(timeout=10)


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, SONGS)
    yield i
    i.close()


@pytest.fixture
def playing(bus, tmp_path, index, qtbot):
    """MusiKata on the bus: (player, engine, controls, desktop, left), `left` counting Quit; the
    cover of the album is tmp_path/cache/T-256.jpg."""
    connection = QDBusConnection.connectToBus(bus, f"musikata-{id(tmp_path)}")
    engine = FakeEngine()
    p = bridges.Player(str(tmp_path), engine, read=index.read, rng=random.Random(5))
    left = []
    window = QWindow()
    index.write(lambda c: c.execute("UPDATE album SET thumb = 'T'")).result()

    def opener(send, position, window):
        return mpris.Mpris(connection, send, position)

    mc = media.MediaControls(
        p, opener, lambda thumb: str(tmp_path / "cache" / f"{thumb}-256.jpg"), window,
        lambda: left.append(1),
    )  # fmt: skip
    desktop = Desktop(bus, qtbot)
    yield p, engine, mc, desktop, left
    desktop.close()
    mc.close()
    p.close()
    QDBusConnection.disconnectFromBus(f"musikata-{id(tmp_path)}")


def song_ids(index):
    return [r[0] for r in index.read().execute("SELECT id FROM song ORDER BY path")]


def test_the_desktop_finds_musikata_on_the_bus_and_what_it_can_do(playing):
    p, engine, mc, desktop, left = playing
    desktop.dest = "org.freedesktop.DBus"
    names = desktop.ask("org.freedesktop.DBus.ListNames", path="/org/freedesktop/DBus")
    assert 'string "org.mpris.MediaPlayer2.musikata"' in names
    desktop.dest = mpris.SERVICE
    root = desktop.ask(f"{mpris.PROPERTIES}.GetAll", f"string:{mpris.ROOT}")
    for entry in (
        '"Identity" variant string "MusiKata"', '"DesktopEntry" variant string "musikata"',
        '"CanRaise" variant boolean true', '"CanQuit" variant boolean true',
        '"HasTrackList" variant boolean false', '"SupportedUriSchemes" variant array [ ]',
    ):  # fmt: skip
        assert entry in root, entry
    xml = desktop.ask("org.freedesktop.DBus.Introspectable.Introspect")
    assert '<property name="Metadata" type="a{sv}" access="read">' in xml
    assert '<property name="Position" type="x" access="read"/>' in xml
    assert '<method name="SetPosition">' in xml and 'name="Seeked"' in xml
    nothing = desktop.get(mpris.PLAYER, "Metadata")
    assert nothing == (
        'variant array [ dict entry( string "mpris:trackid" variant object path '
        '"/org/mpris/MediaPlayer2/TrackList/NoTrack" ) ]'
    )
    assert desktop.get(mpris.PLAYER, "PlaybackStatus") == 'variant string "Stopped"'


def test_the_desktop_sees_the_song_its_cover_and_where_it_is_in_d_buss_types(
    playing, index, tmp_path, qtbot
):
    p, engine, mc, desktop, left = playing
    p.play_songs(song_ids(index), "Glass Harbor")
    qtbot.waitUntil(lambda: bool(p.property("playing")), timeout=WAIT)
    art = (tmp_path / "cache" / "T-256.jpg").as_uri()
    qtbot.waitUntil(lambda: art in desktop.get(mpris.PLAYER, "Metadata"), timeout=WAIT)
    player = desktop.ask(f"{mpris.PROPERTIES}.GetAll", f"string:{mpris.PLAYER}")
    for entry in (
        '"PlaybackStatus" variant string "Playing"',
        f'"mpris:trackid" variant object path "{controls.TRACKS}1"',
        '"mpris:length" variant int64 42000000',  # the engine's length (the fake's 0:42)
        f'"mpris:artUrl" variant string "{art}"',
        '"xesam:title" variant string "Tidewater"',
        '"xesam:artist" variant array [ string "Lumen Drift" ]',
        '"xesam:album" variant string "Glass Harbor"',
        '"Position" variant int64 0', '"Volume" variant double 1',
        '"CanGoNext" variant boolean true', '"CanSeek" variant boolean true',
        '"CanControl" variant boolean true', '"Rate" variant double 1',
        '"MinimumRate" variant double 1', '"MaximumRate" variant double 1',
    ):  # fmt: skip
        assert entry in player, entry
    p.seek(30.5)
    assert desktop.get(mpris.PLAYER, "Position") == "variant int64 30500000"


def test_the_desktop_hears_each_change_and_each_seek(playing, index, qtbot):
    p, engine, mc, desktop, left = playing
    p.play_songs(song_ids(index), "Glass Harbor")
    changes = r"member=PropertiesChanged string \"org.mpris.MediaPlayer2.Player\" array \[ (.*?) \] array \[ \]"  # noqa: E501
    qtbot.waitUntil(lambda: '"PlaybackStatus" variant string "Playing"' in desktop.heard(),
                    timeout=WAIT)  # fmt: skip
    assert f'"mpris:trackid" variant object path "{controls.TRACKS}1"' in desktop.heard()
    qtbot.waitUntil(lambda: '"mpris:length" variant int64 42000000' in desktop.heard(),
                    timeout=WAIT)  # fmt: skip
    p.toggle()
    qtbot.waitUntil(lambda: '"PlaybackStatus" variant string "Paused"' in desktop.heard(),
                    timeout=WAIT)  # fmt: skip
    p.seek(12.0)
    qtbot.waitUntil(lambda: "member=Seeked int64 12000000" in desktop.heard(), timeout=WAIT)
    p.next()
    qtbot.waitUntil(lambda: '"xesam:title" variant string "Glass Harbor"' in desktop.heard(),
                    timeout=WAIT)  # fmt: skip
    # each signal carries only what changed, and the invalidated list is an empty `as`
    sent = re.findall(changes, desktop.heard())
    assert sent and all("Position" not in s for s in sent)
    assert not any(s.count('"PlaybackStatus"') > 1 for s in sent)


def test_the_desktops_commands_are_obeyed(playing, index, qtbot):
    p, engine, mc, desktop, left = playing
    p.cue(song_ids(index), "Glass Harbor")
    desktop.ask(f"{mpris.PLAYER}.Play")
    qtbot.waitUntil(lambda: bool(p.property("playing")), timeout=WAIT)
    desktop.ask(f"{mpris.PLAYER}.Pause")
    qtbot.waitUntil(lambda: bool(p.property("paused")), timeout=WAIT)
    desktop.ask(f"{mpris.PLAYER}.PlayPause")
    qtbot.waitUntil(lambda: bool(p.property("playing")), timeout=WAIT)
    desktop.ask(f"{mpris.PLAYER}.Seek", "int64:10000000")
    track = f"{controls.TRACKS}1"
    desktop.ask(f"{mpris.PLAYER}.SetPosition", f"objpath:{track}", "int64:25000000")
    desktop.ask(f"{mpris.PLAYER}.SetPosition", "objpath:/elsewhere/7", "int64:5000000")
    qtbot.waitUntil(lambda: engine.seeks() == [10.0, 25.0], timeout=WAIT)
    desktop.ask(f"{mpris.PLAYER}.Next")
    qtbot.waitUntil(lambda: p.property("title") == "Glass Harbor", timeout=WAIT)
    desktop.ask(f"{mpris.PLAYER}.Previous")
    qtbot.waitUntil(lambda: p.property("title") == "Tidewater", timeout=WAIT)
    desktop.ask(f"{mpris.PROPERTIES}.Set", f"string:{mpris.PLAYER}", "string:Volume",
                "variant:double:0.25")  # fmt: skip
    qtbot.waitUntil(lambda: p.property("volume") == 0.25, timeout=WAIT)
    desktop.ask(f"{mpris.PROPERTIES}.Set", f"string:{mpris.PLAYER}", "string:Rate",
                "variant:double:2")  # fmt: skip
    desktop.ask(f"{mpris.PLAYER}.OpenUri", "string:file:///elsewhere.flac")
    desktop.ask(f"{mpris.PLAYER}.Stop")
    qtbot.waitUntil(lambda: not p.property("playing") and ("stop",) in engine.asked,
                    timeout=WAIT)  # fmt: skip
    desktop.ask(f"{mpris.ROOT}.Raise")
    qtbot.waitUntil(lambda: mc._window.isVisible(), timeout=WAIT)
    desktop.ask(f"{mpris.ROOT}.Quit")
    qtbot.waitUntil(lambda: left == [1], timeout=WAIT)
    assert desktop.get(mpris.PLAYER, "Rate") == "variant double 1"


def test_a_second_musikata_takes_a_name_of_its_own_and_each_gives_its_up(bus, qapp):
    first = QDBusConnection.connectToBus(bus, "first")
    second = QDBusConnection.connectToBus(bus, "second")
    one = mpris.Mpris(first, print, lambda: 0.0)
    two = mpris.Mpris(second, print, lambda: 0.0)
    assert one.service == mpris.SERVICE
    assert two.service == f"{mpris.SERVICE}.instance{os.getpid()}"
    with pytest.raises(RuntimeError, match="is taken on this connection"):
        mpris.Mpris(first, print, lambda: 0.0)  # the first's objects stay
    assert first.objectRegisteredAt(mpris.PATH) is not None
    assert first.objectRegisteredAt(mpris.INT64_PATH) is not None
    one.close()
    two.close()
    names = first.interface().registeredServiceNames().value()
    assert not [n for n in names if n.startswith(mpris.SERVICE)]
    QDBusConnection.disconnectFromBus("first")
    QDBusConnection.disconnectFromBus("second")


def test_without_a_session_bus_it_doesnt_start_and_says_why(tmp_path, qapp):
    nowhere = QDBusConnection.connectToBus(f"unix:path={tmp_path}/no-bus", "nowhere")
    with pytest.raises(RuntimeError, match="no session bus"):
        mpris.Mpris(nowhere, print, lambda: 0.0)
    QDBusConnection.disconnectFromBus("nowhere")
