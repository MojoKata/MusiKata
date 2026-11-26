"""The views in the window (src/musikata/qml/; R2.6, R6.3): Albums as a grid and a list, an album's
page, Artists and an artist's page each load with no QML warning, show their covers once loaded off
the GUI thread, keep their text in its boxes, and go where a click says.

Why: a QML view is only checked by loading it; a binding to a role that isn't there, or a cover
whose provider fails, shows only as a warning in the log and an empty tile."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock
from PySide6.QtCore import QBuffer, QPointF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QAudioDevice
from PySide6.QtTest import QTest

from musikata import app, layout, player, tour
from musikata_core import art, scanner
from musikata_core.tags import AudioInfo, Tags

WAIT = 10_000


def png(color):
    image = QImage(300, 300, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


ALBUMS = [  # artist, album, year, genre, songs, cover's colour (None: no cover)
    ("Lumen Drift", "Glass Harbor", 2019, "Electronic", 3, "#3366cc"),
    ("Lumen Drift", "Tide Tables", 2022, "Electronic", 2, "#33aa66"),
    ("Mara Okafor", "Kindling", None, None, 2, None),
    ("The Paper Lanterns", "Northbound Static", 2021, "Indie Rock", 2, "#cc6633"),
]


@pytest.fixture
def shell(tmp_path, qapp):
    root = tmp_path / "Music"
    root.mkdir()
    s = app.load(str(root), {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)},
                 FakeClock(), lambda: ThreadPoolExecutor(1),
                 lambda: player.Engine(output=QAudioDevice))  # fmt: skip
    images, batch = {}, []
    for artist, album, year, genre, n, color in ALBUMS:
        folder = f"{artist}/{album}"
        if color:
            os.makedirs(root / folder)
            (root / folder / "cover.png").write_bytes(png(color))
            images[folder] = [art.Image("cover.png", 1, 1)]
        for t in range(1, n + 1):
            tags = Tags(title=f"{album} {t}", artist=artist, album=album, track=t, year=year,
                        genres=(genre,) if genre else (), rating=t % 6)  # fmt: skip
            path = f"{folder}/{t:02d}.flac"
            info = AudioInfo("flac", 200.0, 900, 44100, 2)
            batch.append(scanner.Read(scanner.Seen(path, 10, 1), tags, info, path))
    s.index.write(lambda c: scanner.write_batch(c, batch, {}, images)).result()
    s.library.reload()
    s.window.show()
    yield s
    s.close()


def settle(shell, qtbot):
    """Renders the window, then waits for every cover it asked for."""
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    return shell.window.grabWindow()


def items(root, name):
    found = []

    def walk(item):
        if item.objectName() == name:
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(root)
    return found


def one(shell, name):
    found = items(shell.window.contentItem(), name)
    assert len(found) == 1, (name, found)
    return found[0]


def click(shell, item, x=None, y=None):
    at = item.mapToScene(QPointF(item.width() / 2 if x is None else x,
                                 item.height() / 2 if y is None else y)).toPoint()  # fmt: skip
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


@pytest.mark.slow
@pytest.mark.parametrize(
    "step",
    [
        {"view": "albums"},
        {"view": "album", "album": "Glass Harbor"},
        {"view": "album", "album": "Kindling"},
        {"view": "artists"},
        {"view": "artist", "artist": "Lumen Drift"},
        {"view": "artist", "artist": "Mara Okafor"},
        {"view": "songs"},
    ],
)
def test_each_view_loads_with_no_warning_and_its_text_in_its_boxes(shell, qtbot, qtlog, step):
    shell.library.go(step)
    settle(shell, qtbot)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []


@pytest.mark.slow
def test_albums_in_list_mode_load_too(shell, qtbot, qtlog):
    shell.library.setAlbumsMode("list")
    settle(shell, qtbot)
    rows = items(shell.window.contentItem(), "albumRows")[0]
    qtbot.waitUntil(lambda: rows.property("count") == 4, timeout=WAIT)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []


@pytest.mark.slow
def test_a_cover_is_shown_and_an_album_without_one_shows_the_dashed_tile(shell, qtbot):
    shell.library.go({"view": "album", "album": "Glass Harbor"})
    shot = settle(shell, qtbot)
    assert shot.pixelColor(232 + 28 + 110, 52 + 110).name() == "#3366cc"
    shell.library.go({"view": "album", "album": "Kindling"})
    shot = settle(shell, qtbot)
    assert shot.pixelColor(232 + 28 + 110, 52 + 110).name() != "#3366cc"


@pytest.mark.slow
def test_clicks_open_a_view_an_album_its_artist_and_go_back(shell, qtbot):
    lib = shell.library
    settle(shell, qtbot)
    grid = items(shell.window.contentItem(), "albums")[0]
    qtbot.waitUntil(lambda: grid.property("count") == 4, timeout=WAIT)
    first = grid.property("contentItem").childItems()[0]
    click(shell, first, 40, 40)  # its cover: Glass Harbor, the first by artist and title
    qtbot.waitUntil(lambda: lib.property("view") == "album", timeout=WAIT)
    assert lib.property("album").property("title") == "Glass Harbor"
    settle(shell, qtbot)
    played = []
    shell.player._play.connect(played.append)
    click(shell, one(shell, "play"))
    qtbot.waitUntil(lambda: bool(played), timeout=WAIT)
    assert played[0].endswith(os.path.join("Lumen Drift", "Glass Harbor", "01.flac"))
    click(shell, one(shell, "artistName"))
    qtbot.waitUntil(lambda: lib.property("view") == "artist", timeout=WAIT)
    assert lib.property("artist").property("name") == "Lumen Drift"
    click(shell, one(shell, "back"))
    qtbot.waitUntil(lambda: lib.property("view") == "album", timeout=WAIT)
    click(shell, one(shell, "side-artists"))
    qtbot.waitUntil(lambda: lib.property("view") == "artists", timeout=WAIT)
    click(shell, one(shell, "side-songs"))
    qtbot.waitUntil(lambda: lib.property("view") == "songs", timeout=WAIT)
