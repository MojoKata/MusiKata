"""The Library bridge (src/musikata/bridges.py; A1.2): the root's card, the Songs list's texts, and
the scan on a thread of its own, its progress and end reaching QML's thread as signals."""

import functools
import os
import threading
from concurrent.futures import BrokenExecutor, ThreadPoolExecutor

import pytest
from fakes import FakeClock, fill, wav

from musikata import bridges
from musikata_core import db, scanner, watch
from musikata_core.clock import SystemClock


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def threads():
    return ThreadPoolExecutor(2)


def test_paths_under_home_are_shown_from_tilde(tmp_path):
    home = os.path.join(os.sep, "home", "ana")
    music = os.path.join(home, "Music")
    assert bridges.shown_path(music, home) == os.path.join("~", "Music")
    assert bridges.shown_path(music, home + os.sep) == os.path.join("~", "Music")
    assert bridges.shown_path(home, home) == "~"
    assert bridges.shown_path(home + "2" + os.sep + "Music", home).startswith(home + "2")
    assert bridges.shown_path(music, "") == music


def test_sizes_counts_and_the_cards_line():
    assert [bridges.size_text(n) for n in (0, 999, 3_000, 412_000_000, 9_840_000_000,
                                           123_000_000_000)] == [
        "0 bytes", "999 bytes", "3.0 KB", "412 MB", "9.8 GB", "123 GB"
    ]  # fmt: skip
    assert bridges.summary(0, 0, 0) == "No songs yet"
    assert bridges.summary(1, 1, 5_000_000) == "1 song · 1 album · 5.0 MB"
    assert bridges.summary(1412, 128, 9_840_000_000) == "1,412 songs · 128 albums · 9.8 GB"
    assert bridges.scanning_text(0, 0) == "Scanning…"
    assert bridges.scanning_text(200, 1412) == "Scanning… 200 of 1,412"


def test_albums_count_by_album_artist_or_artist_and_name_case_aside(index):
    fill(index, [
        {"path": "1", "artist": "A", "album": "X", "size": 10},
        {"path": "2", "artist": "a", "album": "x", "size": 10},     # the same album
        {"path": "3", "artist": "B", "album": "X", "size": 10},     # another's X
        {"path": "4", "artist": "C", "albumartist": "Various", "album": "Hits", "size": 10},
        {"path": "5", "artist": "D", "albumartist": "Various", "album": "Hits", "size": 10},
        {"path": "6", "artist": "E", "size": 10},                   # no album
    ])  # fmt: skip
    assert bridges.counts(index.read()) == (6, 3, 60)


def test_the_library_as_qml_reads_it(index, tmp_path):
    fill(index, [{"path": "a.flac", "size": 2_000_000}, {"path": "b.flac", "size": 1_000_000}])
    home = str(tmp_path)
    lib = bridges.Library(os.path.join(home, "Music"), index, home, threads)
    assert lib.property("root") == os.path.join("~", "Music")
    assert lib.property("line") == "2 songs · 0 albums · 3.0 MB"
    assert lib.property("countText") == "2 songs" and lib.property("emptyText") == ""
    assert lib.property("songs").rowCount() == 2 and lib.property("scanning") is False


def test_a_scan_reports_progress_then_fills_the_list_and_the_card(index, tmp_path, qtbot):
    root = tmp_path / "Music"
    root.mkdir()
    for name in ("Signal Fires.flac", "Undertow.mp3"):
        (root / name).write_bytes(b"not audio")  # read as unreadable: rows with their reason
    lib = bridges.Library(str(root), index, str(tmp_path), threads)
    assert lib.property("emptyText") == "No songs in " + os.path.join("~", "Music")
    lines = []
    lib.changed.connect(lambda: lines.append(lib.property("line")))
    with qtbot.waitSignal(lib.scanningChanged) as started:
        lib.rescan()
    assert started.signal_triggered and lib.property("scanning") is True
    assert lib.property("emptyText") == "Reading your music…"
    lib.rescan()  # one at a time: a second while one runs does nothing
    with qtbot.waitSignal(lib.scanningChanged, timeout=10_000):
        pass
    lib.wait()
    assert lib.property("scanning") is False
    assert lib.last.added == 2 and lib.last.unreadable == 2
    assert "Scanning… 2 of 2" in lines and lines[-1].startswith("2 songs · 0 albums")
    assert lib.property("songs").row(0)["title"] == "Signal Fires"


def test_a_scan_that_fails_is_kept_and_logged_and_the_library_goes_on(
    index, tmp_path, qtbot, caplog
):
    def broken():
        raise OSError("no worker processes today")

    lib = bridges.Library(str(tmp_path / "Music"), index, str(tmp_path), broken)
    with qtbot.waitSignal(lib.scanningChanged):
        lib.rescan()
    with qtbot.waitSignal(lib.scanningChanged, timeout=10_000):
        pass
    lib.wait()
    assert isinstance(lib.last, OSError) and "the scan of" in caplog.text
    assert lib.property("scanning") is False and lib.property("line") == "No songs yet"


def test_waiting_with_no_scan_started_returns_at_once(index, tmp_path):
    bridges.Library(str(tmp_path), index, str(tmp_path), threads).wait()


# ---------- Albums, Artists and the pages ----------


def test_an_albums_format_kicker_and_state_chips():
    assert bridges.format_text([("flac", 44100, 900_000, 10)]) == "FLAC 44.1 kHz"
    assert bridges.format_text([("flac", 96000, 0, 2), ("flac", 44100, 0, 5)]) == "FLAC 44.1 kHz"
    assert bridges.format_text([("mp3", 44100, 320_000, 2), ("mp3", 48000, 128_000, 2)]) == (
        "MP3 224 kbps"
    )
    assert bridges.format_text([("mp3", 44100, 0, 1)]) == "MP3"
    assert bridges.format_text([("alac", None, 0, 1)]) == "ALAC"
    assert bridges.format_text([("mp3", 1, 1, 1), ("flac", 1, 1, 3), (None, 0, 0, 9)]) == (
        "FLAC, MP3"
    )
    assert bridges.format_text([(None, None, None, 2)]) == ""
    assert bridges.kicker(False, 2019, "Electronic") == "Album · 2019 · Electronic"
    assert bridges.kicker(True, None, None) == "Compilation"
    assert bridges.state_chips(10, 10, "A/cover.jpg") == [
        {"text": "Art embedded in 10 of 10", "tone": "ok"},
        {"text": "cover.jpg in folder", "tone": "info"},
    ]
    assert bridges.state_chips(10, 3, None) == [{"text": "Art embedded in 3 of 10", "tone": "warn"}]
    assert bridges.state_chips(2, 0, "folder.png") == [
        {"text": "No art embedded", "tone": "info"},
        {"text": "folder.png in folder", "tone": "info"},
    ]


SONGS = [
    {"path": "LD/GH/01.flac", "title": "Tidewater", "artist": "Lumen Drift",
     "album": "Glass Harbor", "albumartist": "Lumen Drift", "track": 1, "year": 2019,
     "genres": ("Electronic",), "length": 242.0, "has_cover": True},
    {"path": "LD/GH/02.flac", "title": "Glass Harbor", "artist": "Lumen Drift",
     "album": "Glass Harbor", "albumartist": "Lumen Drift", "track": 2, "year": 2019,
     "genres": ("Electronic",), "length": 311.0},
    {"path": "LD/ebb.mp3", "title": "ebb & flow", "artist": "lumen drift"},
    {"path": "V/1.ogg", "title": "Ferry", "artist": "Lumen Drift", "album": "Night Ferry",
     "compilation": True},
    {"path": "V/2.ogg", "title": "Night", "artist": "Iron Arc", "album": "Night Ferry",
     "compilation": True, "genres": ("Soundtrack",)},
]  # fmt: skip


@pytest.fixture
def lib(index, tmp_path):
    fill(index, SONGS)
    return bridges.Library(str(tmp_path / "Music"), index, str(tmp_path), threads)


def album_id(lib, title):
    albums = lib.property("albums")
    return next(albums.row(i)["albumId"] for i in range(albums.count)
                if albums.row(i)["title"] == title)  # fmt: skip


def test_the_genre_chips_are_the_most_common_and_more_holds_the_rest(index):
    fill(index, [{"path": f"{n}.mp3", "album": f"A{n}", "artist": "X", "genres": (g,)}
                 for n, g in enumerate("aabbbcdz")])  # fmt: skip
    assert bridges.genre_chips(index.read(), 2) == (["b", "a"], ["c", "d", "z"])


def test_a_genre_chip_filters_albums_and_more_shows_the_genre_chosen_from_it(lib, qtbot):
    assert lib.property("genres") == ["Electronic", "Soundtrack"]
    assert lib.property("moreGenres") == [] and lib.property("albumCountText") == "2 albums"
    with qtbot.waitSignal(lib.changed):
        lib.setGenre("Soundtrack")
    assert lib.property("albumCountText") == "1 album" and lib.property("genre") == "Soundtrack"
    assert lib.property("moreText") == "More…" and not lib.property("moreChosen")
    lib._chips = (["Electronic"], ["Soundtrack"])
    assert lib.property("moreText") == "Soundtrack" and lib.property("moreChosen")
    lib.setGenre("")
    assert lib.property("albumCountText") == "2 albums"


def test_a_genre_that_went_with_a_scan_shows_every_album_again(lib, index):
    lib.setGenre("Soundtrack")
    index.write(lambda c: c.execute("DELETE FROM song_genre WHERE genre = 'Soundtrack'")).result()
    index.write(lambda c: c.execute("UPDATE album SET genre = NULL WHERE genre = 'Soundtrack'"))
    index.write(lambda c: None).result()
    lib.reload()
    assert lib.property("genre") == "" and lib.property("albumCountText") == "2 albums"


def test_the_albums_view_switches_between_grid_and_list(lib, qtbot):
    assert lib.property("albumsMode") == "grid"
    with qtbot.waitSignal(lib.viewChanged):
        lib.setAlbumsMode("list")
    assert lib.property("albumsMode") == "list"
    with pytest.raises(ValueError):
        lib.setAlbumsMode("cards")


def test_an_albums_page_says_what_it_holds(lib):
    lib.openAlbum(album_id(lib, "Glass Harbor"))
    page = lib.property("album")
    assert lib.property("view") == "album" and lib.property("section") == "albums"
    assert [page.property(p) for p in ("title", "artist", "kicker", "detail")] == [
        "Glass Harbor",
        "Lumen Drift",
        "Album · 2019 · Electronic",
        "2 songs · 9 min · FLAC 44.1 kHz",
    ]
    assert page.property("cover").startswith("image://covers/")
    assert page.property("chips")[0] == {"text": "Art embedded in 1 of 2", "tone": "warn"}
    songs = page.property("songs")
    assert [songs.row(i)["title"] for i in range(songs.count)] == ["Tidewater", "Glass Harbor"]
    assert songs.queue_from(0) == (songs._ids, "Glass Harbor")  # what a double click queues
    assert lib.property("backText") == "Albums"


def test_an_artists_page_lists_their_albums_then_their_other_songs(lib):
    artists = lib.property("artists")
    names = [artists.row(i)["name"] for i in range(artists.count)]
    assert names == ["Iron Arc", "Lumen Drift", "Various Artists"]
    lib.show("artists")
    lib.openArtist(artists.row(1)["artistId"])
    page = lib.property("artist")
    assert lib.property("view") == "artist" and lib.property("section") == "artists"
    assert page.property("name") == "Lumen Drift"
    assert page.property("detail") == "1 album · 4 songs"
    assert len(page.property("tiles")) == 1
    albums, others = page.property("albums"), page.property("others")
    assert [albums.row(i)["title"] for i in range(albums.count)] == ["Glass Harbor"]
    assert [others.row(i)["title"] for i in range(others.count)] == ["Ferry", "ebb & flow"]
    assert page.property("othersTitle") == "Other songs"
    lib.openArtist(artists.row(0)["artistId"])  # Iron Arc: only on a compilation
    assert page.property("othersTitle") == "Other songs" and page.property("albums").count == 0


def test_pages_go_back_the_way_they_came(lib, qtbot):
    with qtbot.waitSignal(lib.viewChanged):
        lib.show("artists")
    glass = album_id(lib, "Glass Harbor")
    lib.openAlbum(glass)
    assert lib.property("backText") == "Artists"
    lib.openArtist(lib.property("album").property("artistId"))
    assert lib.property("backText") == "Glass Harbor" and lib.property("section") == "artists"
    lib.openAlbum(glass)
    assert lib.property("backText") == "Lumen Drift"
    lib.back()
    assert lib.property("view") == "artist"
    lib.back()
    assert lib.property("view") == "album"
    lib.back()
    assert lib.property("view") == "artists"
    lib.back()  # nothing before: Albums
    assert lib.property("view") == "albums"
    lib.openAlbum(-1)
    lib.openArtist(-1)
    assert lib.property("view") == "albums"  # no such page: nothing opens
    with pytest.raises(ValueError):
        lib.show("genres")


def test_a_page_whose_album_went_with_a_scan_goes_back(lib, index):
    lib.show("songs")
    lib.openAlbum(album_id(lib, "Night Ferry"))
    index.write(lambda c: c.execute("DELETE FROM song WHERE path LIKE 'V/%'")).result()
    index.write(lambda c: c.execute("DELETE FROM album WHERE title = 'Night Ferry'")).result()
    lib.reload()
    assert lib.property("view") == "songs"


def test_going_back_to_a_page_that_went_goes_to_its_view(lib, index):
    lib.show("artists")
    lib.openArtist(lib.property("artists").row(0)["artistId"])
    lib.openAlbum(album_id(lib, "Night Ferry"))
    index.write(lambda c: c.execute("DELETE FROM artist WHERE name = 'Iron Arc'")).result()
    lib.back()
    assert lib.property("view") == "artists"
    lib.openAlbum(album_id(lib, "Glass Harbor"))
    lib.openAlbum(album_id(lib, "Night Ferry"))
    index.write(lambda c: c.execute("DELETE FROM album WHERE title = 'Glass Harbor'")).result()
    lib.back()
    assert lib.property("view") == "albums"


def test_the_tour_opens_a_view_or_a_page_by_its_name(lib):
    lib.go({"view": "album", "album": "Glass Harbor"})
    assert lib.property("view") == "album" and lib.property("album").property("title") == (
        "Glass Harbor"
    )
    lib.go({"view": "artist", "artist": "Iron Arc"})
    assert lib.property("view") == "artist" and lib.property("backText") == "Artists"
    lib.go({"view": "songs"})
    assert lib.property("view") == "songs"
    lib.go({"view": "album", "album": "Not here"})
    assert lib.property("view") == "albums"
    lib.go({"view": "artist", "artist": "Nobody"})
    assert lib.property("view") == "artists"


def test_the_song_playing_marks_its_album_and_its_rows_on_the_pages(lib):
    lib.openAlbum(album_id(lib, "Glass Harbor"))
    lib.show_playing("LD/GH/02.flac")
    albums = lib.property("albums")
    marked = [albums.data(albums.index(i), albums._role("playing")) for i in range(albums.count)]
    assert marked == [False, True] or marked == [True, False]
    assert albums.data(albums.index(marked.index(True)), albums._role("title")) == "Glass Harbor"
    songs = lib.property("album").property("songs")
    assert songs.data(songs.index(1), songs._role("playing")) is True
    lib.show_playing("")
    assert not any(albums.data(albums.index(i), albums._role("playing")) for i in range(2))


# ---------- the header (R6.4) and search (R2.7) ----------


def test_the_header_says_each_views_title_count_modes_and_sort(lib):
    assert lib.property("searchable") and lib.property("title") == "Albums"
    assert lib.property("viewCount") == "2 albums"
    assert [m["mode"] for m in lib.property("modes")] == ["grid", "list"]
    assert lib.property("mode") == "grid"
    assert [s["label"] for s in lib.property("sorts")] == ["Artist", "Title", "Year"]
    assert lib.property("sortText") == "Sort: Artist"
    assert lib.property("searchHint") == "Search the library"
    lib.show("artists")
    assert (lib.property("title"), lib.property("viewCount")) == ("Artists", "3 artists")
    assert lib.property("modes") == [] and lib.property("mode") == ""
    assert lib.property("sortText") == "Sort: Name" and lib.property("sort") == "name"
    lib.show("songs")
    assert (lib.property("title"), lib.property("viewCount")) == ("Songs", "5 songs")
    assert lib.property("sorts") == [] and lib.property("sortText") == ""
    assert [h["order"] for h in lib.property("songHeaders")][2] == "up"  # by artist
    lib.openAlbum(album_id(lib, "Glass Harbor"))
    assert not lib.property("searchable") and lib.property("title") == ""
    assert lib.property("viewCount") == "" and lib.property("sortText") == ""


def test_the_sorts_order_albums_and_a_songs_column_turns_the_other_way_on_a_second_click(lib):
    lib.setSort("title")
    assert lib.property("sort") == "title" and lib.property("sortText") == "Sort: Title"
    assert lib.property("albums").row(0)["title"] == "Glass Harbor"
    with pytest.raises(ValueError):
        lib.setSort("plays")
    lib.show("artists")
    lib.setSort("name")
    with pytest.raises(ValueError):
        lib.setSort("title")
    lib.show("songs")
    lib.sortSongs("title")
    assert lib.property("songs").order() == ("title", False)
    lib.sortSongs("title")
    assert lib.property("songs").order() == ("title", True)
    assert lib.property("songHeaders")[1]["order"] == "down"
    lib.sortSongs("year")
    assert lib.property("songs").order() == ("year", False)


def search(lib, qtbot, text):
    """Types `text` into the search box and waits for the view's rows (never a set time)."""
    with qtbot.waitSignal(lib.changed, check_params_cb=lambda: not lib.property("searching"),
                          timeout=5000):  # fmt: skip
        lib.setSearch(text)


def test_a_search_filters_only_the_view_open_and_its_count_says_of_how_many(lib, qtbot):
    search(lib, qtbot, "ferry")
    assert lib.property("search") == "ferry"
    assert lib.property("viewCount") == "1 of 2 albums"
    assert lib.property("albumCountText") == "1 of 2 albums"
    assert lib.property("artistCountText") == "3 artists"  # not the view open: whole
    assert lib.property("emptyText") == ""
    search(lib, qtbot, "zebra")
    assert lib.property("viewCount") == "0 of 2 albums"
    assert lib.property("emptyText") == "No albums match “zebra”"
    lib.show("songs")  # another view: whole, its box empty
    assert lib.property("search") == "" and lib.property("countText") == "5 songs"
    assert lib.property("albums").count == 2
    search(lib, qtbot, "rating:0 artist:lumen")
    assert lib.property("viewCount") == "4 of 5 songs"
    lib.show("artists")
    search(lib, qtbot, "iron")
    assert [lib.property("artists").row(i)["name"] for i in range(2)] == [
        "Iron Arc", "Various Artists"
    ]  # fmt: skip
    lib.setSearch("iron")  # the same again: nothing to do
    assert not lib.property("searching")


def test_a_page_opened_from_a_search_goes_back_to_it_and_the_sidebar_clears_it(lib, qtbot):
    search(lib, qtbot, "glass")
    lib.openAlbum(album_id(lib, "Glass Harbor"))
    assert lib.property("view") == "album" and lib.property("search") == ""
    lib.setSearch("tide")  # a page has no search box: nothing
    assert lib.property("album").property("songs").count == 2
    lib.back()
    assert lib.property("view") == "albums" and lib.property("search") == "glass"
    assert lib.property("viewCount") == "1 of 2 albums"
    lib.openArtist(lib.property("album").property("artistId"))
    lib.show("albums")
    assert lib.property("search") == "" and lib.property("albums").count == 2


def test_a_scan_while_searching_finds_the_search_again(lib, index, qtbot):
    search(lib, qtbot, "lumen")
    assert lib.property("viewCount") == "2 of 2 albums"
    fill(index, [{"path": "LD/new.flac", "title": "New", "artist": "Lumen Drift", "album": "Dawn"}])
    with qtbot.waitSignal(lib.property("albums").countChanged, timeout=5000):
        lib.reload()
    assert lib.property("viewCount") == "3 of 3 albums"
    lib.wait()


def test_a_page_read_again_after_a_scan_keeps_the_page_open_and_its_list_in_place(lib, index):
    lib.openAlbum(album_id(lib, "Glass Harbor"))
    songs = lib.property("album").property("songs")
    resets = []
    songs.modelReset.connect(lambda: resets.append(True))
    fill(index, [{**SONGS[0], "path": "LD/GH/03.flac", "title": "Breakwater", "track": 3}])
    lib.reload()
    assert lib.property("view") == "album" and songs.rowCount() == 3 and resets == []
    lib.openArtist(lib.property("album").property("artistId"))
    albums = lib.property("artist").property("albums")
    albums.modelReset.connect(lambda: resets.append(True))
    lib.reload()
    assert lib.property("view") == "artist" and albums.rowCount() == 1 and resets == []


# ---------- watching (A2.4, R2.4) ----------


class Held:
    """Worker processes whose reads wait until the test lets them go: a scan that runs as long as
    the test needs."""

    def __init__(self, gate):
        self._gate, self._pool = gate, ThreadPoolExecutor(1)

    def shutdown(self, wait=True, *, cancel_futures=False):
        self._pool.shutdown(wait)

    def map(self, fn, *args):
        assert self._gate.wait(10)
        return self._pool.map(fn, *args)


def scopes_of(monkeypatch):
    """The folders each scan named, in order (None: the whole root)."""
    scopes, real = [], scanner.scan

    def recording(*args, scope=None, **kw):
        scopes.append(None if scope is None else set(scope.folders))
        return real(*args, scope=scope, **kw)

    monkeypatch.setattr(scanner, "scan", recording)
    return scopes


def scanned(lib, qtbot):
    """Scans the root and waits for the scan's end."""
    with qtbot.waitSignal(lib.scanningChanged):
        lib.rescan()
    qtbot.waitUntil(lambda: not lib.property("scanning"), timeout=10_000)


def report(lib, clock, *folders):
    """Changes reported in `folders`, and a second passed: the watcher's folders are due."""
    for f in folders:
        lib.watcher.changed(f)
    clock.advance(seconds=1)
    lib.watcher.ready.emit()


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "Music"
    wav(root / "A" / "1.wav", 1, "Signal Fires")
    wav(root / "B" / "2.wav", 2, "Undertow")
    return root


def test_a_watched_change_rescans_its_folder_only_and_the_list_keeps_its_place(
    index, music, tmp_path, qtbot, monkeypatch
):
    clock = FakeClock()
    lib = bridges.Library(str(music), index, str(tmp_path), threads, clock=clock, watching=True)
    assert lib.watcher is None  # until a scan of the root walks the folders
    scopes = scopes_of(monkeypatch)
    scanned(lib, qtbot)
    assert set(lib.watcher.known()) == {"", "A", "B"}
    songs, seen, turning = lib.property("songs"), [], []
    songs.modelReset.connect(lambda: seen.append("reset"))
    songs.rowsInserted.connect(lambda *_: seen.append("inserted"))
    lib.scanningChanged.connect(lambda: turning.append(lib.property("scanning")))
    wav(music / "A" / "3.wav", 3, "Neap Tide")
    report(lib, clock, "A")
    qtbot.waitUntil(lambda: songs.rowCount() == 3, timeout=10_000)
    lib.wait()
    assert scopes == [None, {"A"}] and lib.last.added == 1 and lib.last.unchanged == 1
    assert seen == ["inserted"] and turning == []  # no reset; the card's dot didn't turn
    assert lib.property("line").startswith("3 songs")
    lib.window_active(True)  # watching: focus rescans nothing
    assert not lib.property("scanning")
    lib.close()
    assert lib.watcher.known() == {}


def test_one_scan_at_a_time_what_comes_meanwhile_waits_for_the_scan_to_end(
    index, music, tmp_path, qtbot, monkeypatch
):
    clock, gate = FakeClock(), threading.Event()
    lib = bridges.Library(str(music), index, str(tmp_path), lambda: Held(gate), clock=clock,
                          watching=True)  # fmt: skip
    scopes = scopes_of(monkeypatch)
    gate.set()
    scanned(lib, qtbot)
    gate.clear()
    wav(music / "A" / "3.wav", 3)
    report(lib, clock, "A")  # a partial scan, held reading
    qtbot.waitUntil(lambda: len(scopes) == 2)
    report(lib, clock, "")  # gathered while it runs
    with qtbot.waitSignal(lib.scanningChanged):
        lib.rescan()  # asked for while it runs: next, and the dot turns at once
    assert lib.property("scanning") and len(scopes) == 2
    gate.set()
    qtbot.waitUntil(lambda: not lib.property("scanning"), timeout=10_000)
    assert scopes == [None, {"A"}, None]  # the root's scan covers what was gathered
    gate.clear()
    wav(music / "B" / "4.wav", 4)
    with qtbot.waitSignal(lib.scanningChanged):
        lib.rescan()  # held reading B/4.wav
    qtbot.waitUntil(lambda: len(scopes) == 4)
    wav(music / "A" / "5.wav", 5)
    report(lib, clock, "A")
    gate.set()
    qtbot.waitUntil(lambda: lib.property("songs").rowCount() == 5, timeout=10_000)
    lib.wait()
    # after the root's scan, what was reported while it ran (the system's watcher saw B change too)
    assert scopes[:4] == [None, {"A"}, None, None] and "A" in scopes[4] and len(scopes) == 5
    lib.close()


class Meddling:
    """Worker processes that add a file to a folder the walk has been through while the first
    batch is read: a change made while a scan goes on."""

    def __init__(self, path):
        self._path, self._pool = path, ThreadPoolExecutor(1)

    def shutdown(self, wait=True, *, cancel_futures=False):
        self._pool.shutdown(wait)

    def map(self, fn, *args):
        if self._path is not None:
            wav(self._path, 9)
            self._path = None
        return self._pool.map(fn, *args)


def test_a_change_made_while_the_first_scan_goes_on_is_rescanned_after_it(
    index, music, tmp_path, qtbot, monkeypatch
):
    """A2.4: the folders are watched as the walk reaches them, not once the scan has ended."""
    clock, added = FakeClock(), [music / "A" / "9.wav"]
    lib = bridges.Library(str(music), index, str(tmp_path),
                          lambda: Meddling(added.pop() if added else None), clock=clock,
                          watching=True)  # fmt: skip
    scopes = scopes_of(monkeypatch)
    scanned(lib, qtbot)
    assert lib.last.added == 2
    clock.advance(seconds=1)
    lib.watcher.ready.emit()
    qtbot.waitUntil(lambda: lib.property("songs").rowCount() == 3, timeout=5000)
    lib.wait()
    assert scopes == [None, {"A"}]
    lib.close()


def test_the_worker_processes_start_once_when_first_needed_and_end_with_the_library(
    index, music, tmp_path, qtbot
):
    """A1.3: the worker processes are started when first needed and end with MusiKata, so a
    watched rescan doesn't start its own (spawning them costs up to a second)."""
    clock, made = FakeClock(), []

    def pool():
        made.append(ThreadPoolExecutor(1))
        return made[-1]

    lib = bridges.Library(str(music), index, str(tmp_path), pool, clock=clock, watching=True)
    scanned(lib, qtbot)
    first = lib.last
    wav(music / "A" / "3.wav", 3)
    report(lib, clock, "A")
    qtbot.waitUntil(lambda: lib.last is not first, timeout=10_000)
    lib.wait()
    assert lib.last.added == 1 and len(made) == 1
    lib.close()
    with pytest.raises(RuntimeError):
        made[0].submit(print)


class Broken:
    """Worker processes one of which died: every job fails."""

    down = False

    def map(self, fn, *args):
        raise BrokenExecutor("a worker process died")

    def shutdown(self, wait=True, *, cancel_futures=False):
        self.down = True


def test_worker_processes_broken_by_one_that_died_are_started_anew_for_the_next_scan(
    index, music, tmp_path, qtbot
):
    made = []

    def pool():
        made.append(Broken() if not made else ThreadPoolExecutor(1))
        return made[-1]

    lib = bridges.Library(str(music), index, str(tmp_path), pool)
    scanned(lib, qtbot)
    assert isinstance(lib.last, BrokenExecutor) and made[0].down
    scanned(lib, qtbot)
    assert lib.last.added == 2 and len(made) == 2
    lib.close()


def test_where_watching_stopped_gaining_focus_rescans_and_the_log_says_so(
    index, music, tmp_path, qtbot, monkeypatch, caplog
):
    refuse = functools.partial(watch.Watcher, add=lambda paths: paths)
    monkeypatch.setattr(watch, "Watcher", refuse)
    lib = bridges.Library(str(music), index, str(tmp_path), threads, clock=FakeClock(),
                          watching=True)  # fmt: skip
    scanned(lib, qtbot)
    assert lib.watcher.why and "rescanning when the window gains focus" in caplog.text
    lib.window_active(False)
    assert not lib.property("scanning")
    with qtbot.waitSignal(lib.scanningChanged):
        lib.window_active(True)
    qtbot.waitUntil(lambda: not lib.property("scanning"), timeout=10_000)
    lib.close()


def test_a_write_musikata_made_itself_isnt_read_again_by_the_rescan_its_change_starts(
    index, music, tmp_path, qtbot
):
    clock = FakeClock()
    lib = bridges.Library(str(music), index, str(tmp_path), threads, clock=clock, watching=True)
    scanned(lib, qtbot)
    first = lib.last
    wav(music / "A" / "1.wav", 1, "Retitled")
    st = os.stat(music / "A" / "1.wav")
    lib.wrote("A/1.wav", st.st_size, st.st_mtime_ns)
    report(lib, clock, "A")
    qtbot.waitUntil(lambda: lib.last is not first, timeout=10_000)
    lib.wait()
    assert lib.last.read == [] and lib.last.unchanged == 1
    lib.close()


def test_a_first_scan_fills_the_views_as_it_goes(index, tmp_path, qtbot, monkeypatch):
    root = tmp_path / "Music"
    for n in range(3):
        wav(root / f"{n}.wav", n)
    monkeypatch.setattr(scanner, "BATCH", 1)
    lib = bridges.Library(str(root), index, str(tmp_path), threads)
    shown = []
    lib.changed.connect(
        lambda: lib.property("scanning") and shown.append(lib.property("songs").rowCount())
    )
    scanned(lib, qtbot)
    assert sorted(set(shown) - {0}) == [1, 2, 3]


@pytest.mark.slow
def test_files_added_changed_moved_and_removed_under_the_root_appear_while_it_runs(
    index, music, tmp_path, qtbot
):
    """R2.4 with the system's own watcher, on this platform: each change shows in the library
    without a scan asked for."""
    lib = bridges.Library(str(music), index, str(tmp_path), threads, clock=SystemClock(),
                          watching=True)  # fmt: skip
    scanned(lib, qtbot)
    rows = {}

    def songs():
        rows.clear()
        rows.update(
            {p: (i, t) for p, i, t in index.read().execute("SELECT path, id, title FROM song")}
        )
        return rows

    wav(music / "A" / "3.wav", 3, "Neap Tide")  # added
    qtbot.waitUntil(lambda: "A/3.wav" in songs(), timeout=10_000)
    ids = dict(rows)
    tmp = music / "B" / ".2.wav.part"  # changed, as a safe write does: written aside, put in place
    wav(tmp, 2, "Undertow (Live)")
    os.replace(tmp, music / "B" / "2.wav")
    qtbot.waitUntil(lambda: songs().get("B/2.wav", (0, ""))[1] == "Undertow (Live)", timeout=10_000)
    os.rename(music / "A" / "3.wav", music / "B" / "3.wav")  # moved between folders
    qtbot.waitUntil(lambda: "B/3.wav" in songs() and "A/3.wav" not in rows, timeout=10_000)
    assert rows["B/3.wav"][0] == ids["A/3.wav"][0]
    (music / "C").mkdir()  # a folder made, then filled: watched once rescanned
    qtbot.waitUntil(lambda: "C" in lib.watcher.known(), timeout=10_000)
    wav(music / "C" / "4.wav", 4)
    qtbot.waitUntil(lambda: "C/4.wav" in songs(), timeout=10_000)
    os.remove(music / "A" / "1.wav")  # removed
    qtbot.waitUntil(lambda: "A/1.wav" not in songs(), timeout=10_000)
    assert lib.property("line").startswith("3 songs")
    lib.close()
