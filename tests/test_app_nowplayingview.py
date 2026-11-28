"""Now Playing (src/musikata/nowplayingview.py, NowPlayingView.qml; R11.4 to R11.4.5, R6.2.2,
R7.4): what it says of the song playing (the line over the title, the album line, the chips, the
format, Up next, the minute marks), opening and closing it from the bar's button, its cover, ‹
Library and Esc, the picker and the choice kept, each mode drawn with no QML warning and its text
in its boxes, seeking on the large waveform, and the queue's Clear and Save as playlist….

Why: Now Playing takes over the window; one that can't be closed, a picker whose choice is lost at
the next start, chips that say another song's format, or a waveform that seeks elsewhere than it is
clicked would each strand the user in it or mislead them about what they hear."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock, FakeEngine
from PySide6.QtCore import QBuffer, QPointF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from musikata import app, layout, nowplayingview, tints, tour
from musikata_core import art, scanner, settings
from musikata_core.tags import AudioInfo, Tags

WAIT = 5_000


# ---------- what it says (plain) ----------


def test_the_line_over_the_title_names_the_track_of_its_album():
    assert nowplayingview.kicker_text(4, 10) == "Now playing · Track 4 of 10"
    assert nowplayingview.kicker_text(4, None) == "Now playing · Track 4"
    assert nowplayingview.kicker_text(None, 10) == "Now playing"


def test_the_album_line_and_the_chips_say_each_part_known():
    line = nowplayingview.album_line
    assert line("Glass Harbor", 2019, ["Electronic"]) == "Glass Harbor · 2019 · Electronic"
    assert line("", None, ["Soul", "Jazz"]) == "Soul, Jazz" and line("", None, []) == ""
    chips = nowplayingview.chips_of
    assert chips("flac", 16, 44_100, 912_000, -6.2) == [
        "FLAC", "16-bit / 44.1 kHz", "912 kbps", "ReplayGain −6.2 dB"
    ]  # fmt: skip
    assert chips("mp3", 16, 48_000, 320_000, None) == ["MP3", "48 kHz", "320 kbps"]
    assert chips("wav", None, 96_000, 0, 1.5) == ["WAV", "96 kHz", "ReplayGain +1.5 dB"]
    assert chips(None, None, None, None, 0.0) == ["ReplayGain 0.0 dB"]
    assert nowplayingview.rate_text(24, None) == "24-bit" and nowplayingview.rate_text(0, 0) == ""


def test_the_format_under_n03s_cover_is_its_depth_and_rate_or_its_bit_rate():
    fmt = nowplayingview.format_line
    assert fmt("flac", 16, 44_100, 900_000) == "FLAC 16-bit / 44.1 kHz"
    assert fmt("mp3", None, 44_100, 320_000) == "MP3 320 kbps"
    assert fmt("opus", None, 48_000, 0) == "Opus" and fmt(None, None, None, None) == ""


def test_replaygains_chip_is_the_gain_its_mode_plays_at():
    shown = nowplayingview.gain_shown
    assert shown("album", -6.2, -7.0) == -7.0 and shown("album", -6.2, None) == -6.2
    assert shown("track", -6.2, -7.0) == -6.2 and shown("off", -6.2, -7.0) is None


def test_the_analyzers_gear_says_its_bands_and_speed_and_its_back_how_long_ago():
    assert nowplayingview.analyzer_text(96, 3.0) == "Bands: 96 · Speed: 1×"  # N02's
    assert nowplayingview.analyzer_text(128, 1.5) == "Bands: 128 · Speed: 2×"
    assert nowplayingview.speed_text(6.0) == "0.5×" and nowplayingview.speed_text(4) == "0.75×"
    assert nowplayingview.speed_text(7) == "0.43×"  # a hand-edited file's
    assert nowplayingview.ago_text(3.0) == "← 3 seconds ago"
    assert nowplayingview.ago_text(1.5) == "← 1.5 seconds ago"
    assert nowplayingview.ago_text(1) == "← 1 second ago"


def test_the_minute_marks_fall_every_minute_or_every_few_on_a_long_song():
    marks = nowplayingview.minute_marks(258.0)  # 4:18
    assert [m["text"] for m in marks] == ["0:00", "1:00", "2:00", "3:00", "4:00"]
    assert marks[1]["at"] == pytest.approx(60 / 258)
    long = nowplayingview.minute_marks(3 * 3600.0)
    assert len(long) <= nowplayingview.MARKS_AT_MOST and long[1]["text"] == "20:00"
    assert [m["text"] for m in nowplayingview.minute_marks(15 * 60.0)][:3] == [
        "0:00",
        "5:00",
        "10:00",
    ]
    assert nowplayingview.minute_marks(0) == []


# ---------- in the app ----------


def png(colour):
    image = QImage(300, 300, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def songs(index, root):
    folder = root / "Lumen Drift" / "Glass Harbor"
    folder.mkdir(parents=True)
    (folder / "cover.png").write_bytes(png("#2255cc"))
    images = {"Lumen Drift/Glass Harbor": [art.Image("cover.png", 1, 1)]}
    rows = []
    for t in range(1, 6):
        tags = Tags(title=f"Song {t}", artist="Lumen Drift", album="Glass Harbor", track=t,
                    tracktotal=5, year=2019, genres=("Electronic",), rg_track_gain=-6.2,
                    rg_album_gain=-7.5, rating=t % 6)  # fmt: skip
        info = AudioInfo("flac", 200.0 + t, 912_000, 44_100, 2, 16)
        path = f"Lumen Drift/Glass Harbor/{t:02d}.flac"
        rows.append(scanner.Read(scanner.Seen(path, 10, 1), tags, info, path))
    loose = scanner.Read(scanner.Seen("Loose.mp3", 10, 1), Tags(title="Loose"),
                         AudioInfo("mp3", 61.0, 320_000, 48_000, 2), "Loose.mp3")  # fmt: skip
    rows.append(loose)
    index.write(lambda c: scanner.write_batch(c, rows, {}, images)).result()


@pytest.fixture
def shell(tmp_path, qapp):
    root = tmp_path / "Music"
    root.mkdir()
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    settings.set_appearance(settings.shared_path(env), str(tmp_path), "PC", visualization="none")
    s = app.load(str(root), env, FakeClock(), lambda: ThreadPoolExecutor(1), FakeEngine)
    songs(s.index, root)
    s.library.reload()
    s.window.show()
    s.env = env
    yield s
    s.close()


def find(shell, name):
    """The item named `name`: the one shown when there are several (Up next's queue and Now
    Playing's share their parts)."""
    found = []

    def walk(item):
        if item.objectName() == name:
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    picked = [i for i in found if i.isVisible()] or found
    assert len(picked) == 1, (name, found)
    return picked[0]


def click(shell, item, x=None, y=None):
    at = item.mapToScene(QPointF(item.width() / 2 if x is None else x,
                                 item.height() / 2 if y is None else y)).toPoint()  # fmt: skip
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


def settle(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.tints.wait()
    return shell.window.grabWindow()


@pytest.mark.slow
def test_the_song_playing_its_words_chips_and_up_next_as_the_queue_moves(shell, qtbot):
    now, p = shell.now, shell.player
    p.go({"queue": "Glass Harbor", "at": 1})
    assert now.property("details") == {}  # closed: nothing read
    now.open()
    d = now.property("details")
    assert d["kicker"] == "Now playing · Track 2 of 5" and d["title"] == "Song 2"
    assert d["artist"] == "Lumen Drift" and d["line"] == "Glass Harbor · 2019 · Electronic"
    assert d["chips"] == ["FLAC", "16-bit / 44.1 kHz", "912 kbps", "ReplayGain −7.5 dB"]
    assert d["format"] == "FLAC 16-bit / 44.1 kHz"
    assert [r["title"] for r in now.property("upNext")] == ["Song 3", "Song 4", "Song 5"]
    assert now.property("upNext")[0]["line"] == "Lumen Drift · 3:23"
    assert now.property("emptyText") == ""
    p.next()
    qtbot.waitUntil(lambda: now.property("details")["title"] == "Song 3", timeout=WAIT)
    assert [r["title"] for r in now.property("upNext")] == ["Song 4", "Song 5"]
    p.toggle()  # plays: the fake's 0:42 long
    qtbot.waitUntil(lambda: p.property("length") == 42, timeout=WAIT)
    assert [m["text"] for m in now.property("marks")] == ["0:00"]
    p.go({})
    p.clearQueue()


@pytest.mark.slow
def test_nothing_playing_says_so(shell):
    shell.now.open()
    assert shell.now.property("emptyText") == nowplayingview.NOTHING
    assert shell.now.property("details") == {} and shell.now.property("upNext") == []


@pytest.mark.slow
def test_the_picker_lists_its_three_choices_the_current_one_checked_and_kept(shell, qtbot):
    now = shell.now
    assert now.property("mode") == "none"  # as the shared settings kept it (R11.4.5)
    modes = now.property("modes")
    assert [(m["name"], m["icon"], m["checked"]) for m in modes] == [
        ("Waveform", "wave", False), ("3D analyzer", "cube", False),
        ("No visualization", "nowave", True),
    ]  # fmt: skip
    kept = []
    view = nowplayingview.NowPlayingView(shell.player, None, keep=lambda **f: kept.append(f))
    view.setMode("analyzer")
    view.setMode("analyzer")  # again: nothing more
    view.setMode("3d")  # not a choice
    assert kept == [{"visualization": "analyzer"}] and view.property("modeName") == "3D analyzer"
    assert view.property("modeIcon") == "cube" and view.property("mode") == "analyzer"
    assert (
        nowplayingview.NowPlayingView(shell.player, None, visualization="?").property("mode")
        == "waveform"
    )


@pytest.mark.slow
def test_the_choice_is_kept_in_the_shared_settings_on_the_keepers_thread(tmp_path, qapp, qtbot):
    root = tmp_path / "Music"
    root.mkdir()
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(root), env, FakeClock(), lambda: ThreadPoolExecutor(1), FakeEngine, keep=True)
    try:
        assert s.now.property("mode") == "waveform"  # nothing kept yet: the default
        s.now.setMode("none")
        s.now.setBands(128)  # the analyzer's gear (R11.3.1)
        s.now.setSeconds(6.0)
        path = settings.shared_path(env)
        qtbot.waitUntil(
            lambda: (
                settings.load(path, str(tmp_path)).appearance
                == settings.Appearance("none", 128, 6.0)
            ),
            timeout=WAIT,
        )
    finally:
        s.close()


@pytest.mark.slow
@pytest.mark.parametrize("mode", ["waveform", "none", "analyzer"])
@pytest.mark.slow
def test_each_mode_loads_with_no_warning_and_its_text_in_its_boxes(shell, qtbot, qtlog, mode):
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    shell.now.go({"nowPlaying": mode})
    assert shell.now.property("opened") and shell.now.property("mode") == mode
    settle(shell, qtbot)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    assert layout.faults(shell.window) == []
    shell.now.go({})
    assert not shell.now.property("opened")


@pytest.mark.slow
def test_the_bars_button_and_cover_open_it_and_the_button_esc_and_library_close_it(shell, qtbot):
    now = shell.now
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    shell.library.go({"view": "album", "album": "Glass Harbor"})
    view = find(shell, "nowPlaying")
    button = find(shell, "nowPlayingButton")
    settle(shell, qtbot)
    click(shell, button)
    qtbot.waitUntil(lambda: view.isVisible(), timeout=WAIT)
    assert now.property("opened") and button.property("color") != find(
        shell, "nowPlayingBar"
    ).property("color")
    click(shell, button)  # again: closed, back to the album's page
    qtbot.waitUntil(lambda: not view.isVisible(), timeout=WAIT)
    assert shell.library.property("view") == "album"
    click(shell, find(shell, "barCover"))  # the bar's cover opens it too (R11.4)
    qtbot.waitUntil(lambda: view.isVisible(), timeout=WAIT)
    qtbot.waitUntil(
        lambda: view.hasActiveFocus() or find(shell, "nowQueue").hasActiveFocus(), timeout=WAIT
    )
    QTest.keyClick(shell.window, Qt.Key.Key_Escape)  # R11.4.4
    qtbot.waitUntil(lambda: not now.property("opened"), timeout=WAIT)
    now.open()
    settle(shell, qtbot)
    click(shell, find(shell, "backToLibrary"))
    qtbot.waitUntil(lambda: not now.property("opened"), timeout=WAIT)
    assert shell.library.property("view") == "album"
    now.toggle()
    now.toggle()
    assert not now.property("opened")
    now.close()  # closed already: nothing


@pytest.mark.slow
def test_the_pickers_menu_chooses_a_visualization_and_the_later_ones_say_so(shell, qtbot):
    now = shell.now
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    now.open()
    settle(shell, qtbot)
    click(shell, find(shell, "visualizationPicker"))
    qtbot.waitUntil(lambda: find(shell, "chooseWaveform").isVisible(), timeout=WAIT)
    click(shell, find(shell, "chooseWaveform"))
    qtbot.waitUntil(lambda: now.property("mode") == "waveform", timeout=WAIT)
    assert find(shell, "waveformMode").isVisible() and not find(shell, "queueMode").isVisible()
    assert find(shell, "lyricsSwitch").property("later") == nowplayingview.LYRICS_LATER
    assert find(shell, "equalizerButton").property("later") == nowplayingview.EQUALIZER_LATER
    now.setMode("analyzer")
    settle(shell, qtbot)
    assert find(shell, "analyzer").isVisible() and not find(shell, "waveformMode").isVisible()


@pytest.mark.slow
def test_the_gear_lists_the_bands_and_speeds_the_current_ones_checked_and_kept(shell, qtbot):
    now = shell.now
    assert now.property("analyzerBands") == 96 and now.property("analyzerSeconds") == 3.0
    assert [(c["text"], c["checked"]) for c in now.property("bandChoices")] == [
        ("48 bands", False), ("96 bands", True), ("128 bands", False),
    ]  # fmt: skip
    assert [(c["text"], c["checked"]) for c in now.property("speedChoices")] == [
        ("0.5× · 6 s", False), ("1× · 3 s", True), ("2× · 1.5 s", False),
    ]  # fmt: skip
    kept = []
    view = nowplayingview.NowPlayingView(
        shell.player, None, keep=lambda **f: kept.append(f), bands=64, seconds=0
    )
    assert view.property("analyzerBands") == 96 and view.property("analyzerSeconds") == 3.0
    view.setBands(128)
    view.setBands(128)  # again: nothing more
    view.setBands(64)  # not a choice
    view.setSeconds(1.5)
    view.setSeconds(4.0)  # not the gear's
    assert kept == [{"analyzer_bands": 128}, {"analyzer_seconds": 1.5}]
    assert view.property("analyzerText") == "Bands: 128 · Speed: 2×"
    assert view.property("analyzerAgo") == "← 1.5 seconds ago"
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    now.go({"nowPlaying": "analyzer"})
    settle(shell, qtbot)
    analyzer = find(shell, "analyzer")
    assert find(shell, "analyzerCard").isVisible()  # the song's card, top left (R11.4.2)
    assert find(shell, "analyzerAgo").property("text") == "← 3 seconds ago"
    click(shell, find(shell, "analyzerGear"))
    qtbot.waitUntil(lambda: find(shell, "bands128").isVisible(), timeout=WAIT)
    click(shell, find(shell, "bands128"))
    qtbot.waitUntil(lambda: analyzer.property("bands") == 128, timeout=WAIT)
    click(shell, find(shell, "analyzerGear"))
    qtbot.waitUntil(lambda: find(shell, "speedSlow").isVisible(), timeout=WAIT)
    click(shell, find(shell, "speedSlow"))
    qtbot.waitUntil(lambda: analyzer.property("seconds") == 6.0, timeout=WAIT)
    assert now.property("analyzerText") == "Bands: 128 · Speed: 0.5×"
    now.go({})


@pytest.mark.slow
def test_clicking_and_dragging_on_the_large_waveform_seeks_there(shell, qtbot):
    """R7.4's Now Playing half (R11.4.1)."""
    p, now = shell.player, shell.now
    p.go({"queue": "Glass Harbor", "at": 1})
    now.go({"nowPlaying": "waveform"})
    p.toggle()  # plays: the fake's 0:42
    seek = find(shell, "nowSeek")
    qtbot.waitUntil(lambda: seek.property("enabled"), timeout=WAIT)
    settle(shell, qtbot)
    click(shell, seek, seek.width() / 2)
    qtbot.waitUntil(lambda: p.property("position") == pytest.approx(21.0, abs=0.2), timeout=WAIT)
    start = seek.mapToScene(QPointF(seek.width() / 4, seek.height() / 2)).toPoint()
    end = seek.mapToScene(QPointF(seek.width() * 3 / 4, seek.height() / 2)).toPoint()
    QTest.mousePress(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), start)
    QTest.mouseMove(shell.window, end)
    QTest.mouseRelease(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), end)
    qtbot.waitUntil(lambda: p.property("position") == pytest.approx(31.5, abs=0.3), timeout=WAIT)
    assert find(shell, "nowPlayTime").property("visible")


@pytest.mark.slow
def test_the_queues_clear_and_save_as_playlist_act_on_the_queue(shell, qtbot):
    p, now = shell.player, shell.now
    p.go({"queue": "Glass Harbor", "at": 1})
    now.go({"nowPlaying": "none"})
    settle(shell, qtbot)
    queue = find(shell, "nowQueue")
    assert queue.property("model") is p.property("queueList")
    click(shell, find(shell, "saveQueue"))
    qtbot.waitUntil(lambda: shell.library.property("view") == "playlist", timeout=WAIT)
    assert not now.property("opened")  # closed, so its name is edited in the sidebar (R8.3)
    assert shell.playlists.property("editing") >= 0
    now.open()
    settle(shell, qtbot)
    click(shell, find(shell, "clearQueue"))
    qtbot.waitUntil(lambda: len(p.queue) == 1, timeout=WAIT)
    assert p.property("queueList").rowCount() == 1


@pytest.mark.slow
def test_the_cover_of_now_playing_an_album_and_a_folders_card_tint_what_is_behind_them(
    shell, qtbot
):
    """R6.2.2, R2.9.4's Cards: the cover's colour behind Now Playing, an album's page and a
    folder's card; nothing for a folder without a cover."""
    blue = tints.tint_of((0x22, 0x55, 0xCC))
    shell.player.go({"queue": "Glass Harbor", "at": 1})
    shell.library.go({"view": "album", "album": "Glass Harbor"})
    settle(shell, qtbot)
    tint = find(shell, "albumTint")
    qtbot.waitUntil(lambda: tint.isVisible(), timeout=WAIT)
    assert tint.property("tint") == blue
    shell.now.open()
    settle(shell, qtbot)
    qtbot.waitUntil(lambda: find(shell, "nowPlayingTint").isVisible(), timeout=WAIT)
    shell.now.close()
    shell.library.go({"view": "folders", "folder": "Lumen Drift", "mode": "cards"})
    settle(shell, qtbot)

    def cards():
        found = {}

        def walk(item):
            if item.property("tint") is not None and item.property("pathChip") is not None:
                found[item.property("name")] = item.property("tint")
            for child in item.childItems():
                walk(child)

        walk(shell.window.contentItem())
        return found

    qtbot.waitUntil(lambda: cards().get("Glass Harbor") == blue, timeout=WAIT)
