"""The cover's colour (src/musikata/tints.py; R6.2.2): the dominant colour of a cover's thumbnail,
the tint a view draws from it, dark enough for every text over it, picked off the GUI thread and
kept beside the thumbnail in the cover cache, which the cache's trim takes with it.

Why: an album's page, Now Playing and Folders' Cards take their colour from it; a tint picked from
the wrong pixels shows another album's mood, one too light makes the text over it unreadable
(R18.4), and one picked on the GUI thread, or every time it is shown, makes scrolling stutter."""

import os
import threading

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PySide6.QtGui import QColor, QImage

from musikata import covers, tints

MUTED = (0x99 / 255, 0xA0 / 255, 0xB2 / 255)  # Theme.muted, the faintest text over a tint


def image(*bands):
    """A 64-pixel square image of horizontal bands, each (colour, rows)."""
    out = QImage(64, 64, QImage.Format.Format_RGB32)
    y = 0
    for colour, rows in bands:
        for row in range(y, y + rows):
            for x in range(64):
                out.setPixelColor(x, row, QColor(colour))
        y += rows
    return out


def contrast(a, b):
    la, lb = tints.luminance(a), tints.luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def rgb_of(text):
    return tuple(int(text[i : i + 2], 16) / 255 for i in (1, 3, 5))


def test_the_pixels_are_read_as_rows_of_red_green_and_blue_every_few_each_way():
    got = tints.pixels_of(image(("#3366cc", 32), ("#cc3311", 32)), step=4)
    assert got.shape == (256, 3) and got.dtype == np.uint8
    assert got[0].tolist() == [0x33, 0x66, 0xCC] and got[-1].tolist() == [0xCC, 0x33, 0x11]
    assert tints.pixels_of(QImage()).shape == (0, 3)


def test_the_dominant_colour_is_the_hue_holding_most_colour_not_most_pixels():
    blue_most = tints.pixels_of(image(("#2255cc", 40), ("#cc2222", 24)))
    assert tints.dominant(blue_most) == pytest.approx((0x22, 0x55, 0xCC), abs=1)
    # a few vivid pixels outweigh many dull ones of another hue
    vivid = tints.pixels_of(image(("#6b6f66", 48), ("#e02020", 16)))
    r, g, b = tints.dominant(vivid)
    assert r > 200 and g < 40 and b < 40


@pytest.mark.parametrize("colours", [("#808080",), ("#000000",), ("#ffffff", "#111111")])
def test_a_cover_of_greys_black_and_white_has_no_colour(colours):
    bands = [(c, 64 // len(colours)) for c in colours]
    assert tints.dominant(tints.pixels_of(image(*bands))) is None
    assert tints.dominant(np.zeros((0, 3), np.uint8)) is None
    assert tints.tint_of(None) == ""


@settings(max_examples=50, derandomize=True)
@given(st.tuples(*[st.integers(0, 255)] * 3))
def test_every_tint_keeps_the_faintest_text_readable_over_it(colour):
    """R18.4: muted text at 4.5:1 or more over any tint, whatever the cover's hue."""
    tint = tints.tint_of(colour)
    assert len(tint) == 7 and tint.startswith("#")
    assert contrast(MUTED, rgb_of(tint)) >= 4.5


def test_a_tint_keeps_its_covers_hue():
    tint = QColor(tints.tint_of((0x22, 0x55, 0xCC)))
    assert abs(tint.hsvHueF() - QColor("#2255cc").hsvHueF()) < 0.02 and tint.hsvSaturationF() > 0.5


def test_a_covers_colour_is_named_for_its_thumbnail_or_its_mosaic():
    assert tints.name_of("image://covers/" + "a" * 32) == "a" * 32
    mosaic = "image://covers/mosaic/" + "+".join(["b" * 32, "c" * 32])
    assert tints.name_of(mosaic) == covers.mosaic_name(["b" * 32, "c" * 32])
    assert tints.name_of("") is None and tints.name_of("image://covers/") is None
    assert tints.name_of("file:///x.png") is None


class Pictures:
    """Covers.image's stand-in: each name's image, counting the asks and their threads."""

    def __init__(self, images):
        self.images, self.asked, self.threads = images, [], set()

    def __call__(self, name, side):
        self.asked.append((name, side))
        self.threads.add(threading.current_thread().name)
        found = self.images.get(name)
        if isinstance(found, BaseException):
            raise found
        return found if found is not None else QImage()


BLUE, GREY, NONE, BROKEN = "a" * 32, "b" * 32, "c" * 32, "d" * 32


@pytest.fixture
def made(tmp_path, qapp):
    pictures = Pictures({
        BLUE: image(("#2255cc", 64)), GREY: image(("#777777", 64)),
        BROKEN: RuntimeError("a cover that breaks"),
    })  # fmt: skip
    made_ = []

    def make():
        t = tints.Tints(pictures, str(tmp_path / "cache"))
        made_.append(t)
        return t

    yield make, pictures, tmp_path / "cache"
    for t in made_:
        t.close()


def url(name):
    return "image://covers/" + name


def test_a_colour_is_picked_off_the_gui_thread_kept_in_the_cache_and_read_from_there(made, qtbot):
    make, pictures, cache = made
    t = make()
    assert t.of(url(BLUE)) == "" and t.property("revision") == 0  # being picked
    with qtbot.waitSignal(t.changed, timeout=5_000):
        pass
    tint = t.of(url(BLUE))
    assert tint == tints.tint_of((0x22, 0x55, 0xCC)) and t.property("revision") == 1
    assert pictures.asked == [(BLUE, tints.SIDE)] and pictures.threads == {"tints"}
    assert (cache / (BLUE + "-colour")).read_text().strip() == tint
    assert covers.cached_name(BLUE + "-colour") == BLUE  # the cache's trim takes it with its cover
    again = make()
    again.of(url(BLUE))
    again.wait()
    qtbot.waitUntil(lambda: again.of(url(BLUE)) == tint, timeout=5_000)
    assert pictures.asked == [(BLUE, tints.SIDE)]  # kept: not picked again
    assert not again.busy


def test_greys_are_kept_as_none_and_a_cover_not_shown_or_broken_as_nothing(made, qtbot, caplog):
    make, pictures, cache = made
    t = make()
    for name in (GREY, NONE, BROKEN):
        t.of(url(name))
    t.of("")
    t.of(url(GREY))  # asked again while it is picked: once
    t.wait()
    qtbot.waitUntil(lambda: all(url(n) in t._known for n in (GREY, NONE, BROKEN)), timeout=5_000)
    assert [t.of(url(n)) for n in (GREY, NONE, BROKEN)] == ["", "", ""]
    assert (cache / (GREY + "-colour")).read_text().strip() == "none"
    assert not (cache / (NONE + "-colour")).exists()  # no cover yet: picked when one is found
    assert "couldn't pick the colour" in caplog.text
    assert sorted(name for name, _ in pictures.asked) == sorted([GREY, NONE, BROKEN])
    assert t.property("revision") == 0  # nothing to tint: no binding read again


def test_a_kept_colour_that_isnt_one_is_picked_again(made, qtbot, caplog):
    make, pictures, cache = made
    os.makedirs(cache)
    (cache / (BLUE + "-colour")).write_text("blue\n")
    t = make()
    t.of(url(BLUE))
    with qtbot.waitSignal(t.changed, timeout=5_000):
        pass
    assert t.of(url(BLUE)).startswith("#") and "isn't a colour" in caplog.text
    assert (cache / (BLUE + "-colour")).read_text().strip() == t.of(url(BLUE))


def test_a_cache_that_cant_be_written_costs_only_time(made, qtbot, caplog, tmp_path):
    make, pictures, cache = made
    cache.write_text("a file where the folder would be")
    t = make()
    t.of(url(BLUE))
    with qtbot.waitSignal(t.changed, timeout=5_000):
        pass
    assert t.of(url(BLUE)).startswith("#") and "couldn't be kept" in caplog.text
    assert tints._read(str(cache / "x-colour")) is None  # nothing there: none kept


def test_a_kept_colour_that_cant_be_read_is_picked_again(tmp_path, caplog):
    path = tmp_path / "x-colour"
    path.write_bytes(b"\xff\xfe")
    assert tints._read(str(path)) is None and "couldn't be read" in caplog.text
    path.write_text("#12345z")
    assert tints._read(str(path)) is None


def test_once_closed_nothing_more_is_picked(made):
    make, pictures, _ = made
    t = make()
    t.close()
    assert t.of(url(BLUE)) == "" and pictures.asked == []
    t.close()  # again: nothing to stop
