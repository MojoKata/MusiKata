"""Covers as the views show them (src/musikata/covers.py; R5.1, A2.1): the thumbnail made from the
cover the album's row names, kept in the cache and read from it after, in the shapes covers come in
(docs/process/testing.md, "Shapes": `covers`): JPEG, PNG with and without transparency, WebP, wide
and tall, smaller than a thumbnail, broken, missing, and a song whose picture can't be read.

Why: a cover that can't be shown must cost its tile, never the view or the thread that loads it;
and a thumbnail made again on every scroll would keep the disk busy for nothing."""

import logging
import os

import pytest
from fakes import fill
from PySide6.QtCore import QBuffer, QSize
from PySide6.QtGui import QColor, QImage

from musikata import covers
from musikata_core import albums, art, db
from musikata_core.tags import Picture, TagReadError


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
