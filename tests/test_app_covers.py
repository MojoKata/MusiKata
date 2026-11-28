"""Covers as the views show them (src/musikata/covers.py; R5.1, A2.1): the thumbnail made from the
cover the album's row names, kept in the cache and read from it after, in the shapes covers come in
(docs/process/testing.md, "Shapes": `covers`): JPEG, PNG with and without transparency, WebP, wide
and tall, smaller than a thumbnail, broken, missing, and a song whose picture can't be read.

Why: a cover that can't be shown must cost its tile, never the view or the thread that loads it;
and a thumbnail made again on every scroll would keep the disk busy for nothing."""

import logging
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes import FakeClock, fill, wav
from PySide6.QtCore import QBuffer, QSize
from PySide6.QtGui import QColor, QImage

from musikata import bridges, covers
from musikata_core import albums, art, db, scanner
from musikata_core.tags import Picture, TagReadError

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def encoded(w, h, fmt="JPEG", color="#3366cc", alpha=False):
    image = QImage(w, h, QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32)
    image.fill(QColor(0, 0, 0, 0) if alpha else QColor(color))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    assert image.save(buf, fmt)
    return bytes(buf.data())


def test_the_size_asked_for_picks_the_smallest_thumbnail_that_covers_it():
    assert [covers.side_for(QSize(w, w)) for w in (-1, 0, 100, 256, 257, 512, 2000)] == [
        256, 256, 256, 256, 512, 512, 512
    ]  # fmt: skip
    assert covers.side_for(QSize(100, 300)) == 512


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_a_large_cover_is_scaled_so_its_shorter_side_fits(qapp, fmt):
    image = covers.thumbnail(encoded(1200, 800, fmt), 256)
    assert (image.width(), image.height()) == (384, 256)


def test_a_small_cover_is_kept_at_its_size_and_a_tall_one_scaled_by_its_width(qapp):
    small = covers.thumbnail(encoded(100, 100), 256)
    assert (small.width(), small.height()) == (100, 100)
    tall = covers.thumbnail(encoded(600, 1200, "PNG"), 256)
    assert (tall.width(), tall.height()) == (256, 512)


def test_what_isnt_an_image_gives_an_empty_one(qapp):
    assert covers.thumbnail(b"", 256).isNull()
    assert covers.thumbnail(b"\xff\xd8\xff not really a jpeg", 256).isNull()


@pytest.mark.parametrize("fmt", ["BMP", "PPM"])
def test_a_cover_of_a_kind_whose_header_isnt_read_is_scaled_too(qapp, fmt):
    image = covers.thumbnail(encoded(1200, 800, fmt), 256)
    assert (image.width(), image.height()) == (384, 256)
    assert covers.thumbnail(encoded(100, 60, fmt), 256).size() == QSize(100, 60)


# A cover is decoded while another thread holds one of the locks Qt takes as it decodes and waits
# on the GIL. So it is in the app: QML's garbage collector, on the GUI thread, disconnects from a
# Python-made object holding Qt's connection lock, and PySide takes the GIL there
# (disconnectNotify); the probe that finds a PNG's handler connects a QTextStream of its own,
# under that lock. Here the lock held is the image loader's, which every decode takes, so the
# test never depends on which of the connection lock's buckets two objects fall in: a reader on a
# Python-made QBuffer holds it while it calls into Python. A decode that kept the GIL while Qt
# worked (QImage.fromData) waited on that lock holding the GIL, and neither thread ran again. In
# a process of its own, as a deadlock can't be ended from inside it.
HELD = """
import sys, threading
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QImageReader
from musikata import albumart, covers
app = QGuiApplication([])
data = open(sys.argv[1], "rb").read()
inside = threading.Event()
def holder():
    device = QBuffer()  # made in Python: each call Qt's reader makes on it takes the GIL
    device.setData(data)
    device.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(device)
    inside.set()
    reader.read()  # the GIL let go, the loader's lock held while the probes call the device
holding = threading.Thread(target=holder)
holding.start()
inside.wait()
sum(range(4_000_000))  # the GIL held in one C call, so the holder comes to wait on it
{decode}
holding.join()
"""


@pytest.mark.slow
@pytest.mark.parametrize("decode", ["covers.thumbnail(data, 256)", "albumart.decode(data)"])
def test_a_cover_decoded_while_another_thread_holds_qts_lock_and_waits_on_the_gil_never_deadlocks(
    tmp_path, decode
):
    path = tmp_path / "cover.png"
    path.write_bytes(encoded(600, 400, "PNG"))
    src = os.pathsep.join(p for p in (os.path.join(ROOT, "src"), os.environ.get("PYTHONPATH")) if p)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=src)
    script = HELD.replace("{decode}", decode)
    try:
        done = subprocess.run([sys.executable, "-c", script, str(path)], env=env,
                              capture_output=True, text=True, timeout=30)  # fmt: skip
    except subprocess.TimeoutExpired:
        pytest.fail(f"{decode} deadlocked with the thread holding Qt's lock")
    assert done.returncode == 0, done.stderr


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def with_cover(index, root, kind, path, data=None):
    """An album whose cover is the image file at `path` ("file"), or embedded in that song."""
    if kind == "file":
        os.makedirs(os.path.dirname(os.path.join(root, path)), exist_ok=True)
        with open(os.path.join(root, path), "wb") as f:
            f.write(data)
    fill(
        index, [{"path": "A/1.flac", "album": "A", "artist": "X", "has_cover": kind == "embedded"}]
    )

    def point(c):
        c.execute("UPDATE album SET cover_kind = ?, cover = ?, thumb = 'T'", (kind, path))

    index.write(point).result()


def provider(root, index, cache, pictures=None):
    return covers.Covers(str(root), index.read, str(cache), pictures or (lambda p: []))


def test_a_folder_image_is_made_a_thumbnail_once_and_read_from_the_cache_after(
    qapp, tmp_path, index
):
    root, cache = tmp_path / "Music", tmp_path / "cache"
    with_cover(index, str(root), "file", "A/cover.jpg", encoded(1000, 1000))
    p = provider(root, index, cache)
    first = p.requestImage("T", QSize(), QSize(200, 200))
    assert (first.width(), first.height()) == (256, 256)
    assert sorted(os.listdir(cache)) == ["T-256.jpg"]
    os.remove(root / "A" / "cover.jpg")  # the cache alone gives it now
    again = p.image("T", 256)
    assert (
        again.width() == 256 and again.pixelColor(10, 10).name() == first.pixelColor(10, 10).name()
    )


def test_the_mini_player_asks_for_a_cover_with_its_corners_rounded_and_it_isnt_kept(
    qapp, tmp_path, index
):
    """R15.2: a frameless window's corners have nothing behind them to hide a square cover's."""
    root, cache = tmp_path / "Music", tmp_path / "cache"
    with_cover(index, str(root), "file", "A/cover.jpg", encoded(1000, 1000))
    p = provider(root, index, cache)
    rounded = p.requestImage("T?round=0.1", QSize(), QSize(200, 200))
    assert (rounded.width(), rounded.height()) == (256, 256)
    assert rounded.pixelColor(0, 0).alpha() == 0  # its corner: transparent
    square = p.image("T", 256)
    assert rounded.pixelColor(128, 128).name() == square.pixelColor(128, 128).name()
    assert rounded.pixelColor(30, 0).alpha() == 255  # past the corner's radius
    disc = p.requestImage("T?round=0.5", QSize(), QSize(200, 200))
    assert disc.pixelColor(30, 30).alpha() == 0 and disc.pixelColor(128, 2).alpha() == 255
    assert sorted(os.listdir(cache)) == ["T-256.jpg"]  # the square one alone kept
    unrounded = p.requestImage("T?round=nonsense", QSize(), QSize(200, 200))
    assert unrounded.pixelColor(0, 0).alpha() == 255
    assert covers.share_of("round=0") is None and covers.share_of("size=3") is None
    assert covers.share_of("round=inf") is None and covers.share_of("round=0.25") == 0.25
    assert covers.rounded(QImage(), 0.5).isNull()


def test_an_embedded_front_cover_is_read_from_its_song_and_a_transparent_one_kept_as_png(
    qapp, tmp_path, index
):
    root, cache = tmp_path / "Music", tmp_path / "cache"
    with_cover(index, str(root), "embedded", "A/1.flac")
    asked = []

    def pictures(path):
        asked.append(path)
        return [Picture(4, "image/jpeg", encoded(10, 10)),
                Picture(3, "image/png", encoded(600, 600, "PNG", alpha=True))]  # fmt: skip

    image = provider(root, index, cache, pictures).image("T", 512)
    assert asked == [os.path.join(str(root), "A", "1.flac")]
    assert image.width() == 512 and image.hasAlphaChannel()
    assert os.listdir(cache) == ["T-512.png"]


def test_a_cover_that_cant_be_read_or_isnt_an_image_is_no_cover_and_logged(
    qapp, tmp_path, index, caplog
):
    root, cache = tmp_path / "Music", tmp_path / "cache"
    caplog.set_level(logging.WARNING)
    with_cover(index, str(root), "file", "A/cover.jpg", b"not an image")
    assert provider(root, index, cache).image("T", 256).isNull()
    assert "couldn't be shown" in caplog.text and not os.path.exists(cache)
    os.remove(root / "A" / "cover.jpg")
    assert provider(root, index, cache).image("T", 256).isNull()
    assert "couldn't be read" in caplog.text

    def broken(path):
        raise TagReadError("not a flac")

    index.write(lambda c: c.execute("UPDATE album SET cover_kind = 'embedded'")).result()
    assert provider(root, index, cache, broken).image("T", 256).isNull()
    assert provider(root, index, cache).image("T", 256).isNull()  # a song with no picture
    assert provider(root, index, cache).image("nothing", 256).isNull()  # no such thumbnail


def test_a_cache_that_cant_be_written_costs_only_time(qapp, tmp_path, index, caplog):
    root = tmp_path / "Music"
    with_cover(index, str(root), "file", "A/cover.jpg", encoded(300, 300))
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the cache's folder would be")
    image = provider(root, index, blocked).image("T", 256)
    assert image.width() == 256 and "couldn't be saved" in caplog.text
    assert provider(root, index, blocked).file("T") is None  # no file to show the system


def test_a_thumbnail_qt_cant_save_is_logged_and_not_left_behind(
    qapp, tmp_path, index, caplog, monkeypatch
):
    root, cache = tmp_path / "Music", tmp_path / "cache"
    with_cover(index, str(root), "file", "A/cover.jpg", encoded(300, 300))
    monkeypatch.setattr(QImage, "save", lambda *a: False)
    assert provider(root, index, cache).image("T", 256).width() == 256
    assert os.listdir(cache) == [] and "couldn't be saved" in caplog.text


def test_a_broken_cached_thumbnail_is_made_again(qapp, tmp_path, index):
    root, cache = tmp_path / "Music", tmp_path / "cache"
    with_cover(index, str(root), "file", "A/cover.jpg", encoded(300, 300, color="#ff0000"))
    cache.mkdir()
    (cache / "T-256.jpg").write_bytes(b"cut short")
    image = provider(root, index, cache).image("T", 256)
    assert image.pixelColor(5, 5).red() > 200


def test_a_thumbnails_file_is_found_or_made_for_the_systems_media_controls(qapp, tmp_path, index):
    root, cache = tmp_path / "Music", tmp_path / "cache"
    with_cover(index, str(root), "file", "A/cover.jpg", encoded(1000, 1000))
    p = provider(root, index, cache)
    made = p.file("T")
    assert made == str(cache / "T-256.jpg") and os.path.exists(made)
    assert p.file("T") == made and p.file("T", 512) == str(cache / "T-512.jpg")
    assert p.file("no such cover") is None


def test_the_scans_names_lead_to_the_covers_they_name(qapp, tmp_path, index):
    """The name an album's row gives its cover (albums.summarize) is the one served."""
    root, cache = tmp_path / "Music", tmp_path / "cache"
    (root / "A").mkdir(parents=True)
    (root / "A" / "cover.png").write_bytes(encoded(300, 300, "PNG", "#00ff00"))
    a = albums.summarize([albums.Song("A/1.flac", "X", None, "A", False, None, 1.0, 1, 1, False)],
                         [], ("A/cover.png", 1, 1))  # fmt: skip
    fill(index, [{"path": "A/1.flac", "album": "A", "artist": "X"}])
    index.write(lambda c: c.execute("UPDATE album SET cover_kind = ?, cover = ?, thumb = ?",
                                    (a.cover_kind, a.cover, a.thumb))).result()  # fmt: skip
    assert a.thumb == art.thumb_id("A/cover.png", 1, 1)
    image = provider(root, index, cache).image(a.thumb, 256)
    assert image.pixelColor(5, 5).green() > 200 and image.format() != QImage.Format.Format_Invalid


# ---------- folders' covers and mosaics (R5.8, A2.7) ----------


def mosaic_of(*colors, side=256):
    pieces = []
    for c in colors:
        image = QImage(300, 200, QImage.Format.Format_RGB32)
        image.fill(QColor(c) if c else QColor("#000000"))
        pieces.append(image if c else QImage())
    return covers.draw_mosaic(pieces, side)


def at(image, x, y):
    return image.pixelColor(int(x * image.width()), int(y * image.height())).name()


@pytest.mark.parametrize(
    "colors, where",
    [
        (["#ff0000"], [(0.5, 0.5, "#ff0000")]),
        (["#ff0000", "#00ff00"], [(0.25, 0.5, "#ff0000"), (0.75, 0.5, "#00ff00")]),
        (["#ff0000", "#00ff00", "#0000ff"],
         [(0.25, 0.9, "#ff0000"), (0.75, 0.25, "#00ff00"), (0.75, 0.75, "#0000ff")]),
        (["#ff0000", "#00ff00", "#0000ff", "#ffffff"],
         [(0.25, 0.25, "#ff0000"), (0.75, 0.25, "#00ff00"), (0.25, 0.75, "#0000ff"),
          (0.75, 0.75, "#ffffff")]),
    ],
)  # fmt: skip
def test_a_mosaic_is_drawn_in_r5_8s_layouts(qapp, colors, where):
    image = mosaic_of(*colors)
    assert (image.width(), image.height()) == (256, 256)
    for x, y, color in where:
        assert at(image, x, y) == color


def test_a_mosaics_pieces_have_a_gap_between_them_and_one_that_cant_be_shown_is_left_empty(qapp):
    image = mosaic_of("#ff0000", "#00ff00", side=512)
    assert image.pixelColor(255, 256).alpha() == 0 and covers.gap_for(512) == 6
    assert covers.gap_for(256) == 3 and covers.gap_for(100) == 2
    half = mosaic_of("#ff0000", None)
    assert at(half, 0.25, 0.5) == "#ff0000" and half.pixelColor(200, 128).alpha() == 0
    assert mosaic_of(None, None).isNull() and covers.draw_mosaic([], 256).isNull()


def test_a_mosaic_is_drawn_from_its_pieces_thumbnails_and_kept_under_a_hash_of_them(
    tmp_path, index, qapp
):
    root, cache = tmp_path / "Music", tmp_path / "cache"
    os.makedirs(root / "A")
    fill(index, [{"path": "A/1.flac"}, {"path": "B/1.flac"}])
    (root / "A" / "cover.png").write_bytes(encoded(300, 300, "PNG", "#ff0000"))
    (root / "B.png").write_bytes(encoded(300, 300, "PNG", "#0000ff"))
    index.write(lambda c: c.execute(
        "UPDATE folder SET cover_kind = 'file', cover = CASE path WHEN 'A' THEN 'A/cover.png'"
        " ELSE 'B.png' END, thumb = 'T' || path WHERE path IN ('A', 'B')"
    )).result()  # fmt: skip
    p = provider(root, index, cache)
    name = covers.mosaic_id(["TA", "TB"])
    assert name == "mosaic/TA+TB"
    image = p.requestImage(name, QSize(), QSize(256, 256))
    assert at(image, 0.25, 0.5) == "#ff0000" and at(image, 0.75, 0.5) == "#0000ff"
    kept = os.path.join(cache, covers.mosaic_name(["TA", "TB"]) + "-256.png")
    assert os.path.exists(kept) and covers.mosaic_name(["TB", "TA"]) not in os.listdir(cache)
    os.remove(root / "A" / "cover.png")
    os.remove(root / "B.png")
    assert not p.image(name, 256).isNull()  # from the cache, the covers not read again
    assert p.image(covers.mosaic_id(["gone", "nothing"]), 256).isNull()


def test_a_mosaics_piece_from_a_loose_song_on_no_album_is_found_and_drawn(tmp_path, index, qapp):
    """R5.8: a mosaic of loose songs' covers, and its parent's, whose first piece it gives."""
    root, cache = tmp_path / "Music", tmp_path / "cache"
    fill(
        index, [{"path": "P/S/a.mp3", "has_cover": True}, {"path": "P/S/b.mp3", "has_cover": True}]
    )
    mosaic = index.read().execute("SELECT mosaic FROM folder WHERE path = 'P/S'").fetchone()[0]
    first = mosaic.split()[0]
    assert index.read().execute("SELECT mosaic FROM folder WHERE path = 'P'").fetchone() == (first,)
    asked = []

    def pictures(path):
        asked.append(os.path.relpath(path, root))
        return [Picture(3, "image/png", encoded(300, 300, "PNG", color="#ff0000"))]

    image = provider(root, index, cache, pictures).image(first, 256)
    assert image.pixelColor(5, 5).red() > 200 and asked == [os.path.join("P", "S", "a.mp3")]
    assert provider(root, index, cache, pictures).image("nothing", 256).isNull()


def test_a_root_that_isnt_there_shows_its_covers_from_the_cache(qapp, tmp_path, index):
    """R2.10: browsing a library whose drive is unplugged shows the covers already made."""
    root, cache = tmp_path / "Music", tmp_path / "cache"
    with_cover(index, str(root), "file", "A/cover.jpg", encoded(600, 600))
    p = provider(root, index, cache)
    first = p.image("T", 256)
    shutil.rmtree(root)
    assert not p.image("T", 256).isNull() and p.image("T", 256).size() == first.size()


# ---------- trimming the cache (A2.7) ----------


def hexname(n):
    return f"{n:032x}"


def test_the_cache_is_trimmed_of_what_no_row_points_at_and_keeps_every_other_file(
    tmp_path, index, caplog
):
    album, own, piece, loose, alone = (hexname(n) for n in range(1, 6))
    old = "ab" * 16
    fill(index, [{"path": "A/1.flac", "album": "A", "artist": "X"}, {"path": "B/C/1.flac"},
                 {"path": "D/1.flac"}])  # fmt: skip
    index.write(lambda c: (
        c.execute("UPDATE album SET thumb = ?", (album,)),
        c.execute("UPDATE folder SET thumb = ? WHERE path = 'A'", (own,)),
        c.execute("UPDATE folder SET mosaic = ? WHERE path = 'B'", (f"{album} {piece} {loose}",)),
        c.execute("UPDATE folder SET mosaic = ? WHERE path = 'D'", (alone,)),
    )).result()  # fmt: skip
    mosaic = covers.mosaic_name([album, piece, loose])
    assert covers.live(index.read()) == {album, own, piece, loose, alone, mosaic}
    cache = tmp_path / "cache"
    live = [
        f"{album}-256.jpg",
        f"{album}-512.png",
        f"{own}-256.jpg",
        f"{piece}-256.png",
        f"{loose}-512.jpg",
        f"{alone}-256.jpg",
        f"{mosaic}-256.png",
        f"{mosaic}-512.png",
    ]
    stale = [
        f"{old}-256.jpg",
        f"{old}-512.png",
        covers.mosaic_name([album, old]) + "-256.png",
        covers.mosaic_name([alone]) + "-256.png",
    ]  # a mosaic of one piece is never drawn
    stray = ["tmpk2x_9qa.jpg", "notes.txt", f"{old}.jpg", f"{old}-256.webp", "T-256.jpg",
             f"{old.upper()}-256.jpg"]  # fmt: skip
    cache.mkdir()
    for name in live + stale + stray:
        (cache / name).write_bytes(b"x")
    (cache / f"{old}-256.dir.jpg").mkdir()
    caplog.set_level(logging.INFO)
    assert covers.trim_cache(str(cache), index.read()) == sorted(stale)
    assert sorted(os.listdir(cache)) == sorted([*live, *stray, f"{old}-256.dir.jpg"])
    assert "removed 4 stale thumbnails and mosaics" in caplog.text
    assert covers.trim(str(cache), set()) == sorted(live)  # nothing left in the index
    assert covers.trim(str(tmp_path / "none"), set()) == []  # no cache yet


def test_a_cache_that_cant_be_trimmed_costs_only_room_and_says_so(tmp_path, caplog, monkeypatch):
    stale = [f"{hexname(1)}-256.jpg", f"{hexname(2)}-256.jpg", f"{hexname(3)}-256.jpg"]
    for name in stale:
        (tmp_path / name).write_bytes(b"x")
    real = os.remove

    def remove(path):
        if path.endswith(stale[0]):
            raise PermissionError(13, "Permission denied", path)
        if path.endswith(stale[1]):
            real(path)  # gone meanwhile: another trim, or the user
            raise FileNotFoundError(2, "No such file or directory", path)
        real(path)

    monkeypatch.setattr(covers.os, "remove", remove)
    assert covers.trim(str(tmp_path), set()) == [stale[2]]
    assert f"{stale[0]} couldn't be removed" in caplog.text
    (tmp_path / "file").write_bytes(b"")
    assert covers.trim(str(tmp_path / "file"), set()) == []  # not a folder
    assert "couldn't be trimmed" in caplog.text


def test_after_each_scan_the_cache_is_trimmed_on_the_scans_thread(tmp_path, index, qtbot, caplog):
    music, cache = tmp_path / "Music", tmp_path / "cache"
    wav(music / "A" / "1.wav", 1)
    (music / "A" / "cover.png").write_bytes(encoded(300, 300, "PNG"))
    stale = f"{hexname(9)}-256.jpg"
    trimmed = []

    def trim(c):
        trimmed.append(threading.current_thread().name)
        return covers.trim_cache(str(cache), c)

    def scanned(lib):
        with qtbot.waitSignal(lib.scanningChanged):
            lib.rescan()
        qtbot.waitUntil(lambda: not lib.property("scanning"), timeout=10_000)

    lib = bridges.Library(str(music), index, str(tmp_path), lambda: ThreadPoolExecutor(1),
                          clock=FakeClock(), trim=trim)  # fmt: skip
    scanned(lib)
    thumb = index.read().execute("SELECT thumb FROM folder WHERE path = 'A'").fetchone()[0]
    cache.mkdir()
    for name in (f"{thumb}-256.png", stale):
        (cache / name).write_bytes(b"x")
    scanned(lib)
    assert os.listdir(cache) == [f"{thumb}-256.png"] and trimmed == ["scan", "scan"]
    os.remove(music / "A" / "1.wav")  # the folder goes, and its thumbnail with it
    scanned(lib)
    assert os.listdir(cache) == []
    shutil.rmtree(music)  # a root that isn't there: nothing is trimmed
    (cache / stale).write_bytes(b"x")
    scanned(lib)
    assert os.listdir(cache) == [stale] and len(trimmed) == 3
    lib.close()

    def broken(c):
        raise OSError(5, "Input/output error")

    music.mkdir()
    lib = bridges.Library(str(music), index, str(tmp_path), lambda: ThreadPoolExecutor(1),
                          clock=FakeClock(), trim=broken)  # fmt: skip
    scanned(lib)
    assert isinstance(lib.last, scanner.Result) and "trimming the cover cache" in caplog.text
    lib.close()


# Qt's GUI thread pool, which QImage's smooth scaling and its conversions share their work with,
# is made at its first use; made by a cover's thread, which holds the GIL, its making takes Qt's
# connection locks, and the GUI thread may hold one of those while it waits on the GIL
# (tests/locks.py). So the window makes it (covers.start_image_threads); here, after it, a cover's
# thread scales and converts while every lock is held, and returns once they are let go.
POOL = """
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage
from musikata import covers
app = QGuiApplication([])
if "{start}" == "yes":
    covers.start_image_threads()
image = QImage(1200, 1200, QImage.Format.Format_ARGB32_Premultiplied)
image.fill(0)
kept, threads = hold(1.0)
done = []
def cover():
    image.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio,
                 Qt.TransformationMode.SmoothTransformation)
    image.convertToFormat(QImage.Format.Format_RGB32)
    done.append(True)
t = threading.Thread(target=cover)
t.start()
t.join()
for h in threads:
    h.join()
print("done" if done else "not done")
"""


@pytest.mark.slow
def test_qts_image_threads_are_made_on_the_gui_thread_so_a_covers_scaling_never_deadlocks():
    import locks

    done = locks.run(POOL.replace("{start}", "yes"))
    assert done is not None, "a cover's smooth scaling deadlocked with a thread holding Qt's lock"
    assert done.returncode == 0 and done.stdout.strip() == "done", done.stderr
