"""The views in the window (src/musikata/qml/; R2.6, R6.3, R6.4): Albums as a grid and a list, an
album's page, Artists and an artist's page each load with no QML warning, show their covers once
loaded off the GUI thread, keep their text in its boxes, and go where a click says; the header's
search box takes `/` and Esc and filters as the user types (R2.7), becomes its icon when the header
is narrow, and its sort and ⋮ menu do what they say.

Why: a QML view is only checked by loading it; a binding to a role that isn't there, or a cover
whose provider fails, shows only as a warning in the log and an empty tile."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock
from PySide6.QtCore import QBuffer, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QAudioDevice
from PySide6.QtQml import QQmlComponent
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
        {"view": "albums", "search": "zebra"},
        {"view": "artists", "search": "tide"},
        {"view": "songs", "search": "glass harbor 1"},
        {"view": "album", "album": "Glass Harbor", "search": "rating:>=2"},
        {"view": "album", "album": "Glass Harbor", "search": "zebra"},
        {"view": "artist", "artist": "Lumen Drift", "search": "tide"},
        {"view": "artist", "artist": "Lumen Drift", "search": "zebra"},
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
    assert shot.pixelColor(232 + 28 + 110, 64 + 8 + 110).name() == "#3366cc"  # under the header
    shell.library.go({"view": "album", "album": "Kindling"})
    shot = settle(shell, qtbot)
    assert shot.pixelColor(232 + 28 + 110, 64 + 8 + 110).name() != "#3366cc"


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
    shell.player._play.connect(lambda path, ticket: played.append(path))
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


def key(shell, k):
    QTest.keyClick(shell.window, k, Qt.KeyboardModifier(0))


def type_text(shell, text):
    """Types lower-case letters, digits and ASCII marks into the window, a key each."""
    for ch in text:
        key(shell, Qt.Key(ord(ch.upper())))


def visible(item):
    return item.isVisible() and item.opacity() > 0


@pytest.mark.slow
def test_slash_opens_the_search_typing_filters_and_escape_clears_it(shell, qtbot):
    lib = shell.library
    settle(shell, qtbot)
    shell.window.requestActivate()
    qtbot.waitUntil(lambda: shell.window.isActive(), timeout=WAIT)
    field = one(shell, "search")
    key(shell, Qt.Key.Key_Slash)
    qtbot.waitUntil(lambda: field.hasActiveFocus(), timeout=WAIT)
    type_text(shell, "tide")
    qtbot.waitUntil(lambda: lib.property("viewCount") == "1 of 4 albums", timeout=WAIT)
    assert lib.property("search") == "tide" and field.property("text") == "tide"
    key(shell, Qt.Key.Key_Slash)  # in the box, a / is text
    assert field.property("text") == "tide/" and lib.property("search") == "tide/"
    key(shell, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: lib.property("viewCount") == "4 albums", timeout=WAIT)
    assert field.property("text") == "" and field.hasActiveFocus()
    key(shell, Qt.Key.Key_Escape)  # empty: Esc leaves the box
    assert not field.hasActiveFocus()
    lib.show("songs")
    key(shell, Qt.Key.Key_Slash)
    type_text(shell, "rating:>=3")
    qtbot.waitUntil(lambda: lib.property("viewCount") == "1 of 9 songs", timeout=WAIT)
    key(shell, Qt.Key.Key_Escape)
    key(shell, Qt.Key.Key_Escape)


@pytest.mark.slow
def test_on_a_page_slash_opens_the_search_typing_filters_the_page_and_escape_clears_it(
    shell, qtbot, qtlog
):
    """L02-album, L11-artist: the header over a page, its way back where a view's title is, and
    its search box filtering the page's songs and albums (R2.7)."""
    lib = shell.library
    lib.go({"view": "album", "album": "Glass Harbor"})
    settle(shell, qtbot)
    shell.window.requestActivate()
    qtbot.waitUntil(lambda: shell.window.isActive(), timeout=WAIT)
    field, songs = one(shell, "search"), one(shell, "albumSongs")
    assert visible(one(shell, "header")) and visible(one(shell, "back")) and visible(field)
    assert not visible(one(shell, "sort")) and not visible(one(shell, "modes"))
    assert field.property("placeholderText") == "Search this album"
    key(shell, Qt.Key.Key_Slash)
    qtbot.waitUntil(lambda: field.hasActiveFocus(), timeout=WAIT)
    type_text(shell, "rating:>=2")
    qtbot.waitUntil(lambda: songs.property("count") == 2, timeout=WAIT)
    assert lib.property("viewCount") == "2 of 3 songs" and visible(one(shell, "viewCount"))
    key(shell, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: songs.property("count") == 3, timeout=WAIT)
    assert field.property("text") == "" and lib.property("viewCount") == ""
    key(shell, Qt.Key.Key_Escape)
    click(shell, one(shell, "artistName"))
    qtbot.waitUntil(lambda: lib.property("view") == "artist", timeout=WAIT)
    settle(shell, qtbot)
    key(shell, Qt.Key.Key_Slash)
    qtbot.waitUntil(lambda: field.hasActiveFocus(), timeout=WAIT)
    type_text(shell, "tide")
    qtbot.waitUntil(lambda: lib.property("viewCount") == "1 of 2 albums", timeout=WAIT)
    assert field.property("text") == "tide"
    click(shell, one(shell, "back"))  # the album again, as it was left: its search empty
    qtbot.waitUntil(lambda: lib.property("view") == "album", timeout=WAIT)
    settle(shell, qtbot)
    assert field.property("text") == "" and one(shell, "albumSongs").property("count") == 3
    lib.show("albums")  # a view again: its title where the way back was
    settle(shell, qtbot)
    assert not visible(one(shell, "back")) and lib.property("viewCount") == "4 albums"
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


@pytest.mark.slow
def test_a_narrow_header_shows_the_search_as_its_icon_which_opens_it_over_the_title(
    shell, qtbot, qtlog
):
    c = QQmlComponent(
        shell.engine, QUrl.fromLocalFile(os.path.join(os.path.dirname(app.QML), "ViewHeader.qml"))
    )
    header = c.createWithInitialProperties({"library": shell.library})
    assert header is not None, c.errorString()
    header.setParentItem(shell.window.contentItem())
    header.setWidth(520)
    field = items(header, "search")[0]
    icon = items(header, "searchIcon")[0]
    count = items(header, "viewCount")[0]
    assert header.property("narrow") and not visible(field) and visible(icon)
    click(shell, icon)
    qtbot.waitUntil(lambda: field.hasActiveFocus(), timeout=WAIT)
    assert visible(field) and not visible(icon) and not visible(count)
    assert field.x() == 20 and field.width() > 200  # over the title
    key(shell, Qt.Key.Key_Escape)
    assert not visible(field) and visible(icon) and visible(count)
    header.setWidth(1040)
    assert not header.property("narrow") and visible(field) and not visible(icon)
    assert field.width() == 250
    header.setWidth(700)  # less room: the box narrows before it becomes its icon
    assert visible(field) and 180 <= field.width() < 250
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


def every_item(item):
    yield item
    for child in item.childItems():
        yield from every_item(child)


def menu_item(shell, text, qtbot):
    """The item of the menu open now that says `text`, once it shows."""

    def shown():
        menu = (i for i in every_item(shell.window.contentItem()) if i.inherits("QQuickMenuItem"))
        return [i for i in menu if i.property("text") == text and visible(i)]

    qtbot.waitUntil(lambda: bool(shown()), timeout=WAIT)
    return shown()[0]


@pytest.mark.slow
def test_the_sort_menu_orders_albums_and_the_more_menu_rescans(shell, qtbot):
    lib = shell.library
    settle(shell, qtbot)
    click(shell, one(shell, "sort"))
    click(shell, menu_item(shell, "Title", qtbot))
    qtbot.waitUntil(lambda: lib.property("sortText") == "Sort: Title", timeout=WAIT)
    assert lib.property("albums").row(0)["title"] == "Glass Harbor"
    click(shell, one(shell, "more"))
    with qtbot.waitSignal(lib.scanningChanged, timeout=WAIT):
        click(shell, menu_item(shell, "Rescan library", qtbot))
    qtbot.waitUntil(lambda: not lib.property("scanning"), timeout=WAIT)


@pytest.mark.slow
def test_a_click_on_a_songs_column_header_sorts_by_it_and_again_the_other_way(shell, qtbot):
    lib = shell.library
    lib.show("songs")
    settle(shell, qtbot)
    click(shell, one(shell, "head-title"))
    qtbot.waitUntil(lambda: lib.property("songs").order() == ("title", False), timeout=WAIT)
    click(shell, one(shell, "head-title"))
    qtbot.waitUntil(lambda: lib.property("songs").order() == ("title", True), timeout=WAIT)
    assert lib.property("songs").row(0)["title"] == "Tide Tables 2"
    click(shell, one(shell, "head-"))  # the # column: no order of its own
    assert lib.property("songs").order() == ("title", True)


@pytest.mark.slow
def test_a_list_keeps_its_place_and_its_search_when_a_scan_changes_its_rows(shell, qtbot):
    """A watched change (R2.4) rescans while the user reads a list: the rows change under them,
    but the list stays where it was scrolled to, with the search typed."""
    lib = shell.library
    batch = [scanner.Read(scanner.Seen(f"Many/{n:03d}.flac", 10, 1),
                          Tags(title=f"Many {n:03d}", artist="Many"),
                          AudioInfo("flac", 200.0, 900, 44100, 2), f"many{n}")
             for n in range(120)]  # fmt: skip
    shell.index.write(lambda c: scanner.write_batch(c, batch, {})).result()
    lib.reload()
    lib.go({"view": "songs", "search": "many"})
    settle(shell, qtbot)
    songs = one(shell, "songs")
    qtbot.waitUntil(lambda: songs.property("count") == 120, timeout=WAIT)
    songs.setProperty("contentY", 1500.0)
    settle(shell, qtbot)
    more = [scanner.Read(scanner.Seen("Many/zzz.flac", 10, 1), Tags(title="Many more"),
                         AudioInfo("flac", 200.0, 900, 44100, 2), "more")]  # fmt: skip
    shell.index.write(lambda c: scanner.write_batch(c, more, {})).result()
    lib.reload()
    qtbot.waitUntil(lambda: songs.property("count") == 121, timeout=WAIT)
    settle(shell, qtbot)
    assert songs.property("contentY") == 1500.0
    assert lib.property("search") == "many" and lib.property("view") == "songs"


# ---------- Folders (R2.9) ----------


@pytest.mark.slow
@pytest.mark.parametrize(
    "step",
    [
        {"view": "folders", "folder": "", "mode": "small"},
        {"view": "folders", "folder": "Lumen Drift", "mode": "large"},
        {"view": "folders", "folder": "", "mode": "cards", "select": ["Lumen Drift"]},
        {"view": "folders", "folder": "Lumen Drift", "mode": "list",
         "select": ["Lumen Drift/Tide Tables"]},
        {"view": "folders", "folder": "Lumen Drift/Glass Harbor"},
        {"view": "folders", "folder": "", "mode": "large", "search": "tide"},
        {"view": "folders", "folder": "", "mode": "list", "search": "tide"},
    ],
)  # fmt: skip
def test_folders_loads_in_every_mode_with_no_warning_and_its_text_in_its_boxes(
    shell, qtbot, qtlog, step
):
    shell.library.go(step)
    qtbot.waitUntil(lambda: not shell.library.property("searching"), timeout=WAIT)
    settle(shell, qtbot)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []
    shell.window.setWidth(1920)
    settle(shell, qtbot)
    assert layout.faults(shell.window) == []


def tiles(shell):
    found = [i for i in every_item(shell.window.contentItem()) if i.inherits("FolderTile_QMLTYPE")
             or (i.property("cover") is not None and i.property("line") is not None
                 and i.property("large") is not None)]  # fmt: skip
    return sorted(found, key=lambda i: (i.mapToScene(QPointF(0, 0)).y(),
                                        i.mapToScene(QPointF(0, 0)).x()))  # fmt: skip


@pytest.mark.slow
def test_a_folders_mosaic_and_cover_are_shown_and_one_with_no_art_its_dashed_tile(shell, qtbot):
    shell.library.go({"view": "folders", "folder": "", "mode": "small"})
    shot = settle(shell, qtbot)
    lumen, mara, lanterns = tiles(shell)
    for tile, x, color in ((lumen, 0.25, "#3366cc"), (lumen, 0.75, "#33aa66"),
                           (lanterns, 0.5, "#cc6633")):  # fmt: skip
        p = tile.mapToScene(QPointF(tile.width() * x, tile.width() / 2)).toPoint()
        got, want = shot.pixelColor(p), QColor(color)  # the thumbnails are JPEG: near, not exact
        assert max(abs(got.red() - want.red()), abs(got.green() - want.green()),
                   abs(got.blue() - want.blue())) <= 6, (got.name(), color)  # fmt: skip
    p = mara.mapToScene(QPointF(mara.width() / 2, mara.width() / 2)).toPoint()
    assert shot.pixelColor(p).name() not in ("#3366cc", "#33aa66", "#cc6633")


@pytest.mark.slow
def test_clicks_select_open_and_play_folders_and_the_crumbs_and_keys_go_up_and_back(shell, qtbot):
    lib = shell.library
    f = lib.property("folders")
    m = f.property("model")
    played = []  # what the player was handed, cued where there's no sound device
    shell.player.nowPlaying.connect(played.append)
    lib.go({"view": "folders", "folder": "", "mode": "small"})
    settle(shell, qtbot)
    lumen, mara, _ = tiles(shell)
    click(shell, lumen, 40, 40)
    qtbot.waitUntil(lambda: f.property("selectionCount") == 1, timeout=WAIT)
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                     mara.mapToScene(QPointF(40, 40)).toPoint())  # fmt: skip
    qtbot.waitUntil(lambda: f.property("selectionText") == "2 folders · 7 songs selected",
                    timeout=WAIT)  # fmt: skip
    settle(shell, qtbot)
    click(shell, one(shell, "playSelection"))
    qtbot.waitUntil(lambda: bool(played), timeout=WAIT)
    assert played == ["Lumen Drift/Glass Harbor/01.flac"]
    click(shell, one(shell, "clearSelection"))
    qtbot.waitUntil(lambda: f.property("selectionCount") == 0, timeout=WAIT)
    at = lumen.mapToScene(QPointF(40, 40)).toPoint()
    QTest.mouseDClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)
    qtbot.waitUntil(lambda: f.property("path") == "Lumen Drift", timeout=WAIT)
    assert lib.property("viewCount") == "2 folders · 5 songs"
    f.open("Lumen Drift/Tide Tables")
    settle(shell, qtbot)
    assert visible(one(shell, "strip"))
    crumb = [c for c in items(shell.window.contentItem(), "crumb") if c.property("text") ==
             "Lumen Drift"][0]  # fmt: skip
    click(shell, crumb)
    qtbot.waitUntil(lambda: f.property("path") == "Lumen Drift", timeout=WAIT)
    shell.window.requestActivate()
    qtbot.waitUntil(lambda: shell.window.isActive(), timeout=WAIT)
    QTest.keyClick(shell.window, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    qtbot.waitUntil(lambda: f.property("path") == "Lumen Drift/Tide Tables", timeout=WAIT)
    key(shell, Qt.Key.Key_Backspace)
    qtbot.waitUntil(lambda: f.property("path") == "Lumen Drift", timeout=WAIT)
    QTest.mouseClick(shell.window, Qt.MouseButton.BackButton, Qt.KeyboardModifier(0),
                     QPointF(700, 600).toPoint())  # the mouse's back button  # fmt: skip
    qtbot.waitUntil(lambda: f.property("path") == "Lumen Drift/Tide Tables", timeout=WAIT)
    key(shell, Qt.Key.Key_Backspace)
    qtbot.waitUntil(lambda: f.property("path") == "Lumen Drift", timeout=WAIT)
    QTest.keyClick(shell.window, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    qtbot.waitUntil(lambda: f.property("path") == "", timeout=WAIT)
    settle(shell, qtbot)
    click(shell, tiles(shell)[2], 40, 40)  # The Paper Lanterns, then Enter opens it
    qtbot.waitUntil(lambda: f.property("selectionCount") == 1, timeout=WAIT)
    key(shell, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: f.property("path") == "The Paper Lanterns", timeout=WAIT)
    key(shell, Qt.Key.Key_Right)  # the next row selected
    key(shell, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: f.property("path") == "The Paper Lanterns/Northbound Static",
                    timeout=WAIT)  # fmt: skip
    key(shell, Qt.Key.Key_Down)
    key(shell, Qt.Key.Key_Return)  # a file: played
    qtbot.waitUntil(lambda: len(played) == 2, timeout=WAIT)
    assert played[1] == "The Paper Lanterns/Northbound Static/01.flac"
    assert m.rowCount() == 2


@pytest.mark.slow
def test_a_drag_box_and_lists_checkboxes_select_and_the_selection_stays_across_modes(shell, qtbot):
    lib = shell.library
    f = lib.property("folders")
    lib.go({"view": "folders", "folder": "", "mode": "small"})
    settle(shell, qtbot)
    lumen, mara, _ = tiles(shell)
    start = lumen.mapToScene(QPointF(-2, lumen.width() + 70)).toPoint()  # under the tiles
    end = mara.mapToScene(QPointF(30, 30)).toPoint()
    QTest.mousePress(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), start)
    for n in range(1, 11):
        QTest.mouseMove(shell.window, start + (end - start) * (n / 10))
    QTest.mouseRelease(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), end)
    qtbot.waitUntil(lambda: f.property("selectionCount") == 2, timeout=WAIT)
    lib.setMode("list")
    settle(shell, qtbot)
    assert f.property("selectionCount") == 2 and f.property("selectionState") == "some"
    click(shell, one(shell, "selectAll"))  # some selected: none
    qtbot.waitUntil(lambda: f.property("selectionState") == "none", timeout=WAIT)
    click(shell, one(shell, "selectAll"))  # none: all
    qtbot.waitUntil(lambda: f.property("selectionState") == "all", timeout=WAIT)
    click(shell, one(shell, "selectAll"))
    qtbot.waitUntil(lambda: f.property("selectionState") == "none", timeout=WAIT)
    rows = one(shell, "folderRows")
    check = [i for i in every_item(rows) if i.property("mark") is not None and visible(i)][0]
    click(shell, check)
    qtbot.waitUntil(lambda: f.property("selectionCount") == 1, timeout=WAIT)


@pytest.mark.slow
def test_long_paths_fold_their_middle_crumbs_into_a_menu(shell, qtbot):
    deep = "/".join(["A rather long folder name"] * 6)
    fill_one = [scanner.Read(scanner.Seen(f"{deep}/1.flac", 10, 1), Tags(title="Deep"),
                             AudioInfo("flac", 200.0, 900, 44100, 2), "deep")]  # fmt: skip
    shell.index.write(lambda c: scanner.write_batch(c, fill_one, {})).result()
    shell.library.reload()
    shell.library.go({"view": "folders", "folder": deep})
    settle(shell, qtbot)
    shown = [c.property("text") for c in items(shell.window.contentItem(), "crumb")
             if visible(c)]  # fmt: skip
    assert shown[1] == "…" and len(shown) < 6
    assert layout.faults(shell.window) == []
    more = [c for c in items(shell.window.contentItem(), "crumb") if c.property("text") == "…"][0]
    click(shell, more)
    click(shell, menu_item(shell, "A rather long folder name", qtbot))
    qtbot.waitUntil(lambda: shell.library.property("folders").property("path").count("/") == 1,
                    timeout=WAIT)  # fmt: skip
