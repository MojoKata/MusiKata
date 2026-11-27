"""Drag and drop in the running app (src/musikata/dragging.py; R6.10, R8.5, R7.2,
P01-playlist-drag): what a drag carries from each list and grid (the songs in order, the card, the
files), where a drop lands and what it does (added to a playlist with Undo, moved within one to the
insertion line, played next, a file manager's files added or left for R12.5), MusiKata's own format
read back in the shapes it can come in, and, in the window, real drags started with the mouse and
drops delivered as the platform delivers them.

Why: a drag crosses every view and leaves the app. One that carries the wrong songs, or a row
instead of the selection, adds the wrong songs to a playlist; one dropped on the wrong target, or
one whose files a file manager is told to move, loses the user's music from the root; and a reorder
that lands a row off from its line puts a playlist in an order nobody chose."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeClock, fill
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QGuiApplication,
)
from PySide6.QtTest import QTest

from musikata import app, bridges, layout, tour
from musikata import dragging as dnd
from musikata.dragging import Carried, Dragging, drop_of
from musikata.playlists import OUTSIDE_LATER, Playlists
from musikata_core import playlists
from musikata_core.playlists import Store

WAIT = 10_000
SONGS = [
    {"path": "A/01 Alpha.flac", "title": "Alpha", "artist": "Lumen Drift", "album": "Glass",
     "track": 1, "genres": ("Jazz",)},
    {"path": "A/02 Beta.flac", "title": "Beta", "artist": "Lumen Drift", "album": "Glass",
     "track": 2, "genres": ("Jazz",)},
    {"path": "B/Gamma.mp3", "title": "Gamma", "artist": "Other", "album": "Tide", "track": 1},
]  # fmt: skip
ROAD = "#EXTM3U\n../A/01 Alpha.flac\n../B/Gamma.mp3\n../A/02 Beta.flac\n"


# ---------- what a drag carries ----------


def test_the_card_says_how_many_songs_and_names_the_first_of_them():
    """P01: "3 songs", "Breakwater, Low Orbit, …"."""
    assert dnd.head_text(3) == "3 songs" and dnd.head_text(1) == "1 song"
    assert dnd.names_text(["Breakwater", "Low Orbit", "Afterlight"]) == (
        "Breakwater, Low Orbit, Afterlight"
    )
    many = [f"S{n}" for n in range(9)]
    assert dnd.names_text(many) == "S0, S1, S2, S3, S4, S5, …"
    assert dnd.names_text(["", "B"]) == "B"


def test_musikatas_own_format_reads_back_and_another_roots_or_a_broken_one_is_none():
    """A drag's songs within MusiKata, its root in it: another MusiKata's (another root's) ids mean
    nothing here, so its files are read instead; what isn't its shape is no drag of its own."""
    carried = Carried((3, 1), ("/m/a",), "2 songs", "a, b", "", 7, (11, 12))
    text = dnd.encode(carried, "/music")
    assert dnd.decode(text, "/music") == Carried((3, 1), playlist=7, entries=(11, 12))
    assert dnd.decode(text, "/elsewhere") is None
    shapes = ["", "not json", "[]", '{"root": "/music"}',
              '{"root": "/music", "songs": [1, "2"]}', '{"root": "/music", "songs": [true]}',
              '{"root": "/music", "songs": [], "entries": 3}',
              '{"root": "/music", "songs": [1], "playlist": "x"}']  # fmt: skip
    assert [dnd.decode(t, "/music") for t in shapes] == [None] * len(shapes)
    assert dnd.decode('{"root": "/music", "songs": [4]}', "/music") == Carried((4,))


def test_a_drags_data_is_musikatas_own_and_the_files_themselves(tmp_path):
    """R6.10: a file manager is given the files (as URLs) and copies them; MusiKata reads its
    own."""
    carried = Carried((1, 2), (str(tmp_path / "a.mp3"), str(tmp_path / "b c.flac")))
    data = dnd.mime_of(carried, "/music")
    assert data.hasFormat(dnd.MIME) and json.loads(bytes(data.data(dnd.MIME)))["songs"] == [1, 2]
    assert [u.toLocalFile() for u in data.urls()] == list(carried.files)
    urls = [QUrl.fromLocalFile("/x/a.mp3"), "file:///x/b%20c.mp3", QUrl("https://example.com/a")]
    assert dnd.local_paths(urls) == ["/x/a.mp3", "/x/b c.mp3"]


# ---------- where it lands ----------


def test_what_a_drop_does_depends_on_what_is_dragged_and_where():
    """R8.5, R7.2, R6.10, R12.5: MusiKata's songs added to a playlist, a page's own entries moved
    within it, songs played next from the queue; files from outside taken as files anywhere;
    MusiKata's songs on the bare window, and nothing at all, not taken."""
    songs = Carried((1, 2))
    page = Carried((1,), playlist=5, entries=(40,))
    assert drop_of("playlist", 5, songs, []) == dnd.Drop("add", (1, 2))
    assert drop_of("playlist", 5, page, []) == dnd.Drop("add", (1,))  # onto itself: added again
    assert drop_of("page", 5, page, []) == dnd.Drop("move", (1,), (40,))
    assert drop_of("page", 6, page, []) == dnd.Drop("add", (1,))
    assert drop_of("queue", 0, songs, []) == dnd.Drop("play-next", (1, 2))
    assert drop_of("window", -1, songs, []).what == "none"
    assert drop_of("playlist", 5, Carried(()), []).what == "none"  # only missing entries
    assert drop_of("page", 5, Carried((), playlist=5, entries=(41,)), []).what == "move"
    for kind in ("playlist", "page", "queue", "window"):
        assert drop_of(kind, 1, None, ["/x.mp3"]) == dnd.Drop("files", paths=("/x.mp3",))
    assert drop_of("playlist", 1, None, []).what == "none"
    assert drop_of("elsewhere", 1, None, ["/x.mp3"]).what == "none"


def test_each_target_says_what_dropping_does():
    """P01: "Add to Evening Focus"; "Play next"; a reorder's line says it; the window nothing."""
    assert dnd.target_text("add", "playlist", "Evening Focus") == "Add to Evening Focus"
    assert dnd.target_text("files", "page", "Road Trip") == "Add to Road Trip"
    assert dnd.target_text("move", "page", "Road Trip") == ""
    assert dnd.target_text("play-next", "queue", "") == "Play next"
    assert dnd.target_text("files", "window", "") == ""
    assert dnd.window_text(2) == OUTSIDE_LATER and dnd.window_text(0) == dnd.IN_LIBRARY


# ---------- the bridge, without a window ----------


@pytest.fixture
def root(tmp_path, qapp, qtbot):
    from musikata_core import db

    music = tmp_path / "Music"
    (music / "Playlists").mkdir(parents=True)
    (music / "Playlists" / "Road Trip.m3u8").write_text(ROAD)
    (music / "Playlists" / "Evening.m3u8").write_text("../B/Gamma.mp3\n")
    index = db.Index(str(tmp_path / "musikata.db"))
    fill(index, SONGS)
    found = {"Playlists": [playlists.Found("Road Trip.m3u8", 1, 1),
                           playlists.Found("Evening.m3u8", 1, 1)]}  # fmt: skip
    playlists.refresh(str(music), index, found, lambda f: True)
    library = bridges.Library(str(music), index, str(tmp_path), ThreadPoolExecutor)
    yield str(music), index, library
    library.close()
    index.close()


class Queue:
    def __init__(self):
        self.next = []

    def play_next(self, songs):
        self.next.append(list(songs))


@pytest.fixture
def bridge(root):
    music, index, library = root
    said = []
    lists = Playlists(Store(music, index), library, index.read, say=said.append)
    queue = Queue()
    d = Dragging(music, index.read, library, lists, queue, say=said.append)
    d.said, d.queue, d.lists = said, queue, lists
    yield d
    d.close()
    lists.shut()


def song_id(index, title):
    return index.read().execute("SELECT id FROM song WHERE title = ?", (title,)).fetchone()[0]


def playlist_id(index, name):
    return index.read().execute("SELECT id FROM playlist WHERE name = ?", (name,)).fetchone()[0]


def test_a_row_carries_the_selection_when_it_is_in_it_else_its_own_song(root, bridge):
    """R6.10: as the right-click menu takes it (R7.2), in the list's order."""
    music, index, library = root
    songs = library.property("songs")
    bridge.carry(songs, 2)
    assert bridge._carried.songs == (song_id(index, "Gamma"),)
    assert bridge.property("card")["head"] == "1 song"
    assert bridge._carried.files == (os.path.join(music, "B", "Gamma.mp3"),)
    songs.click(0, False, False)
    songs.click(1, True, False)
    bridge.carry(songs, 1)
    assert bridge._carried.songs == (song_id(index, "Alpha"), song_id(index, "Beta"))
    assert bridge.property("card") == {"head": "2 songs", "names": "Alpha, Beta", "cover": ""}
    bridge.carry(library.property("albums"), 0)  # not a list of songs: nothing new carried
    assert bridge._carried.songs == (song_id(index, "Alpha"), song_id(index, "Beta"))


def test_an_album_an_artist_and_a_genre_carry_their_songs_in_order_named_on_the_card(root, bridge):
    music, index, library = root
    c = index.read()
    album = c.execute("SELECT id FROM album WHERE title = 'Glass'").fetchone()[0]
    artist = c.execute("SELECT id FROM artist WHERE name = 'Lumen Drift'").fetchone()[0]
    alpha, beta = song_id(index, "Alpha"), song_id(index, "Beta")
    bridge.carryAlbum(album)
    assert bridge._carried.songs == (alpha, beta)
    assert bridge.property("card")["names"] == "Glass · Lumen Drift"
    bridge.carryArtist(artist)
    assert bridge._carried.songs == (alpha, beta)
    assert bridge.property("card")["names"] == "Lumen Drift"
    bridge.carryGenre("Jazz")
    assert bridge._carried.songs == (alpha, beta) and bridge.property("card")["head"] == "2 songs"
    bridge.carryAlbum(999)
    assert bridge._carried.songs == () and bridge.property("card")["names"] == ""


def test_folders_carry_the_songs_beneath_them_and_give_a_file_manager_the_folders(root, bridge):
    """R2.9.6: a folder stands for every song beneath it; out of MusiKata, the folder itself."""
    music, index, library = root
    folders = library.property("folders").property("model")
    library.show("folders")
    rows = [folders.row(i)["path"] for i in range(folders.rowCount())]
    a = rows.index("A")
    bridge.carry(folders, a)
    assert bridge._carried.songs == (song_id(index, "Alpha"), song_id(index, "Beta"))
    assert bridge._carried.files == (os.path.join(music, "A"),)
    assert bridge.property("card")["names"] == "A"
    folders.click(a, False, False)
    folders.click(rows.index("B"), True, False)
    bridge.carry(folders, a)
    assert len(bridge._carried.songs) == 3
    assert bridge._carried.files == (os.path.join(music, "A"), os.path.join(music, "B"))


def test_a_playlists_entries_carry_their_songs_and_themselves_for_a_reorder(root, bridge):
    music, index, library = root
    road = playlist_id(index, "Road Trip")
    library.openPlaylist(road)
    model = library.property("playlistPage").property("songs")
    bridge.carry(model, 1)
    assert bridge._carried.songs == (song_id(index, "Gamma"),)
    assert bridge._carried.playlist == road and bridge._carried.entries == tuple(
        model.entries_at(1)
    )


def test_a_drag_over_a_playlist_names_it_and_its_drop_adds_the_songs(root, bridge, qtbot):
    """R8.5, P01: highlighted, "Add to Evening"; the songs added at its end."""
    music, index, library = root
    evening = playlist_id(index, "Evening")
    text = dnd.encode(Carried((song_id(index, "Alpha"),)), music)
    assert bridge.enter("playlist", evening, text, [])
    assert bridge.property("target") == f"playlist:{evening}"
    assert bridge.property("targetText") == "Add to Evening"
    bridge.over(3)  # not a reorder: no line
    assert bridge.property("line") == -1
    bridge.leave("playlist", 999)  # another's leaving: still this one
    assert bridge.property("target") == f"playlist:{evening}"
    bridge.leave("playlist", evening)
    assert bridge.property("target") == ""
    assert bridge.drop("playlist", evening, text, [])
    qtbot.waitUntil(lambda: bridge.said[-1:] == ["Added 1 song to Evening"], timeout=WAIT)
    assert not bridge.enter("window", -1, text, [])  # MusiKata's songs on the bare window
    assert not bridge.drop("window", -1, text, [])
    assert not bridge.enter("playlist", evening, "", [])  # nothing at all


def test_a_drag_within_a_playlist_draws_its_line_and_moves_the_entries_there(root, bridge, qtbot):
    """R8.5: the insertion line above the row the drag is over; the entries land there."""
    music, index, library = root
    road = playlist_id(index, "Road Trip")
    library.openPlaylist(road)
    model = library.property("playlistPage").property("songs")
    text = dnd.encode(Carried((song_id(index, "Alpha"),), playlist=road,
                              entries=tuple(model.entries_at(0))), music)  # fmt: skip
    assert bridge.enter("page", road, text, [])
    assert bridge.property("targetText") == ""
    bridge.over(3)
    assert bridge.property("line") == 3
    assert bridge.drop("page", road, text, [])
    qtbot.waitUntil(
        lambda: [model.row(i)["title"] for i in range(3)] == ["Gamma", "Beta", "Alpha"],
        timeout=WAIT,
    )
    assert bridge.property("line") == -1
    assert bridge.drop("page", road, text, []) is True  # no line: nothing moves


def test_songs_or_files_dropped_on_the_queue_play_next_and_files_from_outside_wait(root, bridge):
    """R7.2, R6.10, R12.5."""
    music, index, library = root
    alpha = song_id(index, "Alpha")
    text = dnd.encode(Carried((alpha,)), music)
    assert bridge.enter("queue", 1, text, []) and bridge.property("targetText") == "Play next"
    assert bridge.drop("queue", 1, text, [])
    assert bridge.queue.next == [[alpha]]
    gamma = QUrl.fromLocalFile(os.path.join(music, "B", "Gamma.mp3"))
    assert bridge.drop("queue", 0, "", [gamma, QUrl.fromLocalFile("/elsewhere/x.mp3")])
    assert bridge.queue.next[-1] == [song_id(index, "Gamma")] and bridge.said[-1] == OUTSIDE_LATER
    assert bridge.drop("queue", 0, "", [QUrl.fromLocalFile(os.path.join(music, "A", "x.jpg"))])
    assert bridge.said[-1] == "Nothing dropped is a song in your library"
    assert bridge.drop("window", -1, "", [QUrl.fromLocalFile("/elsewhere/x.mp3")])
    assert bridge.said[-1] == OUTSIDE_LATER
    assert bridge.drop("window", -1, "", [gamma])
    assert bridge.said[-1] == dnd.IN_LIBRARY


def test_a_file_managers_files_dropped_on_a_playlist_are_added(root, bridge, qtbot):
    music, index, library = root
    evening = playlist_id(index, "Evening")
    urls = [QUrl.fromLocalFile(os.path.join(music, "A"))]
    assert bridge.enter("playlist", evening, "", urls)
    assert bridge.property("targetText") == "Add to Evening"
    assert bridge.drop("playlist", evening, "", urls)
    qtbot.waitUntil(lambda: bridge.said[-1:] == ["Added 2 songs to Evening"], timeout=WAIT)


def test_a_drag_started_runs_the_platforms_drag_with_its_data_and_lets_go_after(root, qapp):
    """R6.10: with no card to show, the drag runs without a picture; copied, never moved."""
    music, index, library = root
    ran = []

    def run(drag):
        ran.append((bytes(drag.mimeData().data(dnd.MIME)), drag.mimeData().urls(), d.busy))
        return Qt.DropAction.CopyAction

    d = Dragging(music, index.read, library, run=run)
    d.start(None)  # nothing carried: no drag
    d.carry(library.property("songs"), 0)
    d.start(None)
    assert json.loads(ran[0][0])["songs"] == [song_id(index, "Alpha")]
    assert ran[0][1] == [QUrl.fromLocalFile(os.path.join(music, "A", "01 Alpha.flac"))]
    assert ran[0][2] is True and not d.property("busy") and d.property("card") == {}
    assert dnd._exec.__doc__ and "never moved" in dnd._exec.__doc__
    d.close()


def test_the_tour_holds_a_drag_still_over_a_playlist_as_p01_draws_it(root, bridge):
    music, index, library = root
    library.openPlaylist(playlist_id(index, "Road Trip"))
    bridge.go({"view": "playlist", "drag": {"rows": [1, 2], "onto": "Evening", "line": 2}})
    model = library.property("playlistPage").property("songs")
    assert model.selected_songs() == [song_id(index, "Gamma"), song_id(index, "Beta")]
    assert bridge.property("held") and bridge.property("card")["head"] == "2 songs"
    assert bridge.property("target") == f"playlist:{playlist_id(index, 'Evening')}"
    assert bridge.property("targetText") == "Add to Evening" and bridge.property("line") == 2
    bridge.leave("playlist", playlist_id(index, "Evening"))  # held: stays
    assert bridge.property("held")
    bridge.go({"view": "songs"})
    assert not bridge.property("held") and bridge.property("target") == ""
    bridge.go({"view": "songs"})
    bridge.go({"view": "playlist", "drag": {"rows": [1], "onto": "Nowhere"}})
    assert not bridge.property("held")


# ---------- in the window ----------


@pytest.fixture
def shell(tmp_path, qapp, qtbot):
    music = tmp_path / "Music"
    (music / "Playlists").mkdir(parents=True)
    (music / "Playlists" / "Road Trip.m3u8").write_text(ROAD)
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(music), env, FakeClock(datetime.now(UTC) - timedelta(minutes=1)),
                 lambda: ThreadPoolExecutor(1))  # fmt: skip
    fill(s.index, SONGS)
    found = {"Playlists": [playlists.Found("Road Trip.m3u8", 1, 1)]}
    playlists.refresh(str(music), s.index, found, lambda f: True)
    s.library.reload()
    s.window.show()
    s.music = str(music)
    yield s
    s.close()


def find(shell, name):
    found = []

    def walk(item):
        if item.objectName() == name and item.isVisible():
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    return found


def settled(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.window.grabWindow()


def middle(item, dy=0.0):
    return item.mapToScene(QPointF(item.width() / 2, item.height() / 2 + dy))


COPY, LEFT, NONE = Qt.DropAction.CopyAction, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0)


class Hand:
    """A drag delivered to the window as the platform delivers one: entered, moved, dropped or
    left, carrying MusiKata's own data or a file manager's files."""

    def __init__(self, window, text="", urls=()):
        self.window = window
        self.data = QMimeData()
        if text:
            self.data.setData(dnd.MIME, text.encode())
        if urls:
            self.data.setUrls(list(urls))
        self.entered = False

    def _send(self, event):
        QGuiApplication.sendEvent(self.window, event)
        return event

    def move(self, at):
        kind = QDragMoveEvent if self.entered else QDragEnterEvent
        self.entered = True
        return self._send(kind(at, COPY, self.data, LEFT, NONE))

    def drop(self, at):
        self.move(at)
        return self._send(QDropEvent(at, COPY, self.data, LEFT, NONE))

    def leave(self):
        return self._send(QDragLeaveEvent())


def qml_warnings(qtlog):
    return [r.message for r in qtlog.records if "qml" in r.message.lower()]


@pytest.mark.slow
def test_a_row_dragged_with_the_mouse_carries_its_songs_and_files_with_the_card_as_its_picture(
    shell, qtbot, qtlog
):
    """R6.10, P01: past the drag threshold the platform's drag runs, its picture the card."""
    ran = []

    def run(drag):
        ran.append((json.loads(bytes(drag.mimeData().data(dnd.MIME))), drag.mimeData().urls(),
                    drag.pixmap().size(), shell.dragging.property("busy")))  # fmt: skip
        return Qt.DropAction.IgnoreAction

    shell.dragging._run = run
    shell.library.show("songs")
    settled(shell, qtbot)
    rows = find(shell, "songs")[0]
    at = middle(rows, -rows.height() / 2 + 18).toPoint()  # the first row
    QTest.mousePress(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    for n in range(1, 8):
        QTest.mouseMove(shell.window, at + QPoint(n * 2, n * 6))
    qtbot.waitUntil(lambda: ran != [], timeout=WAIT)
    QTest.mouseRelease(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       at + QPoint(14, 42))  # fmt: skip
    data, urls, size, busy = ran[0]
    alpha = song_id(shell.index, "Alpha")
    assert data["songs"] == [alpha] and data["playlist"] == -1 and busy
    assert [u.fileName() for u in urls] == ["01 Alpha.flac"]
    card = find(shell, "dragCard")[0]
    assert size.width() >= card.width() and size.height() >= card.height()
    assert not shell.dragging.property("busy")
    assert qml_warnings(qtlog) == []


def drag_with_mouse(shell, qtbot, at):
    """A press at `at` (the scene's), moved past the drag threshold: what the drag carried."""
    ran = []
    shell.dragging._run = lambda drag: ran.append(json.loads(bytes(drag.mimeData().data(dnd.MIME))))
    start = at.toPoint()
    QTest.mousePress(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), start)
    for n in range(1, 8):
        QTest.mouseMove(shell.window, start + QPoint(n * 2, n * 6))
    qtbot.waitUntil(lambda: ran != [], timeout=WAIT)
    QTest.mouseRelease(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0),
                       start + QPoint(14, 42))  # fmt: skip
    return ran[0]


@pytest.mark.slow
def test_albums_artists_genres_folders_and_a_playlists_songs_are_dragged_from_their_views(
    shell, qtbot, qtlog
):
    """R6.10: from every grid and list, each carrying its songs in order; in Folders' images the
    drag of a folder drags it, where a drag elsewhere draws the selection box (R2.9.6)."""
    settled(shell, qtbot)
    alpha, beta, gamma = (song_id(shell.index, t) for t in ("Alpha", "Beta", "Gamma"))
    grids = {"albums": "albums", "artists": "artists", "genres": "genreTiles",
             "folders": "folderRows"}  # fmt: skip
    for view, grid in grids.items():  # each first tile: Glass, Lumen Drift, Jazz, the folder A
        shell.library.show(view)
        settled(shell, qtbot)
        at = find(shell, grid)[0].mapToScene(QPointF(60, 60))
        assert drag_with_mouse(shell, qtbot, at)["songs"] == [alpha, beta]
    assert shell.library.property("folders").property("selectionCount") == 0  # no box drawn
    shell.library.openPlaylist(playlist_id(shell.index, "Road Trip"))
    settled(shell, qtbot)
    rows = find(shell, "playlistSongs")[0]
    at = rows.mapToScene(QPointF(rows.width() / 2, 46 + 22 - rows.property("contentY")))
    carried = drag_with_mouse(shell, qtbot, at)
    model = shell.library.property("playlistPage").property("songs")
    assert carried["songs"] == [gamma] and carried["entries"] == model.entries_at(1)
    assert qml_warnings(qtlog) == []


@pytest.mark.slow
def test_songs_dropped_on_a_playlist_in_the_sidebar_are_added_and_the_messages_undo_takes_them_out(
    shell, qtbot, qtlog
):
    """R8.5, P01: the playlist outlined and named while the drag is over it; dropped, the songs
    added at its end, the message saying one was there already, its Undo taking them back out."""
    settled(shell, qtbot)
    road = playlist_id(shell.index, "Road Trip")
    music = shell.music
    alpha, beta = song_id(shell.index, "Alpha"), song_id(shell.index, "Beta")
    hand = Hand(shell.window, dnd.encode(Carried((alpha, beta)), music))
    side = find(shell, "side-playlist")[0]
    assert hand.move(middle(side)).isAccepted()
    qtbot.waitUntil(lambda: find(shell, "dropTarget") != [], timeout=WAIT)
    assert find(shell, "dropLabel")[0].childItems()[0].property("text") == "Add to Road Trip"
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    hand.leave()
    qtbot.waitUntil(lambda: find(shell, "dropTarget") == [], timeout=WAIT)
    hand = Hand(shell.window, dnd.encode(Carried((alpha, beta)), music))
    assert hand.drop(middle(side)).isAccepted()
    qtbot.waitUntil(
        lambda: shell.library.property("playlists").items()[0]["count"] == "5", timeout=WAIT
    )
    qtbot.waitUntil(lambda: find(shell, "messageUndo") != [], timeout=WAIT)
    assert shell.changes.property("message")["text"] == (
        "Added 2 songs to Road Trip (2 were there already)"
    )
    shell.changes.undoMessage()
    qtbot.waitUntil(
        lambda: shell.library.property("playlists").items()[0]["count"] == "3", timeout=WAIT
    )
    with open(os.path.join(music, "Playlists", "Road Trip.m3u8"), encoding="utf-8") as f:
        assert [x for x in f.read().splitlines() if not x.startswith("#")] == [
            "../A/01 Alpha.flac", "../B/Gamma.mp3", "../A/02 Beta.flac"
        ]  # fmt: skip
    assert road >= 0 and qml_warnings(qtlog) == []


@pytest.mark.slow
def test_a_playlists_song_dragged_within_it_shows_the_insertion_line_and_lands_on_it(
    shell, qtbot, qtlog
):
    """R8.5, P01: past the middle of a row, the line is under it; dropped, the song lands there."""
    settled(shell, qtbot)
    road = playlist_id(shell.index, "Road Trip")
    shell.library.openPlaylist(road)
    settled(shell, qtbot)
    model = shell.library.property("playlistPage").property("songs")
    music = shell.music
    text = dnd.encode(Carried((song_id(shell.index, "Alpha"),), playlist=road,
                              entries=tuple(model.entries_at(0))), music)  # fmt: skip
    rows = find(shell, "playlistSongs")[0]
    # the second row's lower half: rows are 44 high, 2 apart, from the content's top
    at = rows.mapToScene(QPointF(rows.width() / 2, 46 + 32 - rows.property("contentY")))
    hand = Hand(shell.window, text)
    assert hand.move(at).isAccepted()
    qtbot.waitUntil(lambda: find(shell, "insertionLine") != [], timeout=WAIT)
    assert shell.dragging.property("line") == 2
    line = find(shell, "insertionLine")[0]
    below = rows.mapToScene(QPointF(0, 46 + 44 + 1 - rows.property("contentY"))).y()
    assert abs(line.mapToScene(QPointF(0, 4)).y() - below) < 3
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    hand.drop(at)
    qtbot.waitUntil(
        lambda: [model.row(i)["title"] for i in range(3)] == ["Gamma", "Alpha", "Beta"],
        timeout=WAIT,
    )
    assert find(shell, "insertionLine") == [] and qml_warnings(qtlog) == []


@pytest.mark.slow
def test_ctrl_shift_down_moves_the_songs_selected_in_a_playlist(shell, qtbot):
    """R6.9, R18.2: the keyboard's way to reorder."""
    settled(shell, qtbot)
    shell.library.openPlaylist(playlist_id(shell.index, "Road Trip"))
    settled(shell, qtbot)
    model = shell.library.property("playlistPage").property("songs")
    page = find(shell, "playlistPage")[0]
    page.forceActiveFocus()
    model.click(0, False, False)
    mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(shell.window, Qt.Key.Key_Down, mods)
    qtbot.waitUntil(
        lambda: [model.row(i)["title"] for i in range(3)] == ["Gamma", "Alpha", "Beta"],
        timeout=WAIT,
    )


@pytest.mark.slow
def test_songs_and_files_dropped_on_up_next_or_the_queue_button_play_next(shell, qtbot, qtlog):
    """R7.2, R6.10: Up next outlined and saying "Play next"; the songs right after the current
    one; a file manager's files under the root too."""
    settled(shell, qtbot)
    music = shell.music
    alpha = song_id(shell.index, "Alpha")
    shell.player.toggleUpNext()
    settled(shell, qtbot)
    panel = find(shell, "upNextDrop")[0]
    hand = Hand(shell.window, dnd.encode(Carried((alpha,)), music))
    assert hand.move(middle(panel)).isAccepted()
    qtbot.waitUntil(lambda: find(shell, "upNextDropLabel") != [], timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    hand.drop(middle(panel))
    assert [e.song for e in shell.player.queue.order] == [alpha]
    shell.player.closeUpNext()
    settled(shell, qtbot)
    button = find(shell, "queueButton")[0]
    gamma = QUrl.fromLocalFile(os.path.join(music, "B", "Gamma.mp3"))
    Hand(shell.window, urls=[gamma]).drop(middle(button))
    assert [e.song for e in shell.player.queue.order] == [alpha, song_id(shell.index, "Gamma")]
    assert qml_warnings(qtlog) == []


@pytest.mark.slow
def test_up_nexts_own_rows_are_still_moved_by_their_handles_beside_the_songs_dropped_on_it(
    shell, qtbot
):
    """R7.2: songs dropped onto Up next (R6.10) didn't take the place of its own reordering, a
    song to come dragged by its handle to where its line shows."""
    settled(shell, qtbot)
    alpha, beta, gamma = (song_id(shell.index, t) for t in ("Alpha", "Beta", "Gamma"))
    shell.player.cue([alpha, beta, gamma], "Test")
    shell.player.toggleUpNext()
    settled(shell, qtbot)
    rows = find(shell, "upNextRows")[0]
    over = rows.mapToScene(QPointF(10, 28 + 48 + 28 + 23)).toPoint()  # Beta: the first to come
    QTest.mouseMove(shell.window, over)
    qtbot.waitUntil(lambda: find(shell, "dragHandle") != [], timeout=WAIT)
    start = middle(find(shell, "dragHandle")[0]).toPoint()
    QTest.mousePress(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), start)
    for n in range(1, 11):
        QTest.mouseMove(shell.window, start + QPoint(0, n * 8))
    QTest.mouseRelease(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0),
                       start + QPoint(0, 80))  # fmt: skip
    qtbot.waitUntil(
        lambda: [e.song for e in shell.player.queue.order] == [alpha, gamma, beta], timeout=WAIT
    )


@pytest.mark.slow
def test_files_from_outside_wait_for_a_later_version_and_images_still_set_a_cover(
    shell, qtbot, tmp_path
):
    """R8.5, R12.5: files from outside the music folder dropped onto a playlist or the window say
    they come in a later version; an image dropped on an album's cover still opens Album art
    (R5.4), and MusiKata's own songs dragged over a cover aren't taken for an image."""
    settled(shell, qtbot)
    outside = QUrl.fromLocalFile(str(tmp_path / "elsewhere.mp3"))
    side = find(shell, "side-playlist")[0]
    Hand(shell.window, urls=[outside]).drop(middle(side))
    assert shell.changes.property("message")["text"] == OUTSIDE_LATER
    shell.changes.dismiss()
    view = find(shell, "view")[0]
    Hand(shell.window, urls=[outside]).drop(middle(view))
    assert shell.changes.property("message")["text"] == OUTSIDE_LATER
    shell.library.show("albums")
    settled(shell, qtbot)
    grid = find(shell, "albums")[0]
    cover = grid.mapToScene(QPointF(60, 60))
    ours = Hand(shell.window, dnd.encode(Carried((1,)), shell.music))
    assert not ours.move(cover).isAccepted()  # not an image, nor anything the window takes
    ours.leave()
    image = tmp_path / "front.png"
    from PySide6.QtGui import QImage

    picture = QImage(64, 64, QImage.Format.Format_RGB32)
    picture.fill(0x3366AA)
    picture.save(str(image))
    Hand(shell.window, urls=[QUrl.fromLocalFile(str(image))]).drop(cover)
    qtbot.waitUntil(lambda: shell.art.property("opened"), timeout=WAIT)
