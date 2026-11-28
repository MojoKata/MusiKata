"""The 3D analyzer's landscape (src/musikata_core/analysis/landscape.py; R11.3, R11.3.1, A5.3): the
slices kept and receding as the landscape's time goes on, their places and sizes at each depth,
the order they are drawn in, their colours from cyan to violet, the triangle strip of them all, the
octave labels' places, and what a frame costs.

Why: the landscape is what R11.3 promises the user sees; a slice out of its depth, drawn in the
wrong order, or in the front's colour at the back shows a landscape that isn't the music's, and a
frame that takes most of 16 ms leaves nothing for the rest of the app (A5.2, A5.3)."""

import math
import time

import numpy as np
import pytest

from musikata_core.analysis import landscape, spectrum

W, H = 1000.0, 500.0


def flat(bands, level):
    return np.full(bands, level, np.float32)


# ---------- the slices kept ----------


def test_a_slice_is_kept_every_slice_seconds_and_let_go_once_older_than_the_landscape_holds():
    land = landscape.Landscape(4, seconds=1.0, every=0.25)
    levels, depths = land.slices()
    assert depths.tolist() == [0.0] and not levels.any()  # nothing yet: the front, flat
    for i in range(1, 9):  # a second of frames, eight a second
        land.advance(flat(4, i / 10), 0.125)
    levels, depths = land.slices()
    # kept at the first frame (0.125 s), then on the beat: 0.25, 0.5, 0.75 and 1.0 s; the front
    assert depths.tolist() == pytest.approx([0.875, 0.75, 0.5, 0.25, 0.0, 0.0])
    assert levels[:, 0].tolist() == pytest.approx([0.1, 0.2, 0.4, 0.6, 0.8, 0.8])
    assert land.now == pytest.approx(1.0)
    for _ in range(4):  # half a second more: the oldest go
        land.advance(flat(4, 0.9), 0.125)
    depths = land.slices()[1]
    assert depths.tolist() == pytest.approx([1.0, 0.75, 0.5, 0.25, 0.0, 0.0])


def test_the_front_is_the_newest_levels_every_frame_and_slices_recede_as_time_goes_on():
    land = landscape.Landscape(3, seconds=2.0, every=0.5)
    land.advance(flat(3, 0.9), 0.5)
    land.advance(flat(3, 0.3), 0.1)  # no slice due: only the front moved
    levels, depths = land.slices()
    assert depths.tolist() == pytest.approx([0.05, 0.0])
    assert levels.ravel().tolist() == pytest.approx([0.9] * 3 + [0.3] * 3)
    land.advance(flat(3, 0.3), 0.0)  # no time: nothing recedes
    assert land.slices()[1].tolist() == pytest.approx([0.05, 0.0])


def test_frames_far_apart_keep_a_slice_each_without_catching_up():
    land = landscape.Landscape(2, seconds=3.0, every=0.1)
    for _ in range(5):
        land.advance(flat(2, 0.5), 0.35)  # slower than the slices: one a frame
    depths = land.slices()[1]
    assert len(depths) == 6  # five kept and the front
    assert np.diff(depths[:-1]).tolist() == pytest.approx([-0.35 / 3] * 4)


def test_a_landscape_of_no_bands_or_no_time_or_levels_of_another_count_is_refused():
    with pytest.raises(ValueError):
        landscape.Landscape(0)
    with pytest.raises(ValueError):
        landscape.Landscape(8, seconds=0)
    with pytest.raises(ValueError):
        landscape.Landscape(8, every=0)
    with pytest.raises(ValueError):
        landscape.Landscape(8).advance(flat(4, 0.5), 0.1)


# ---------- where each slice stands ----------


def test_the_front_slice_spans_the_width_on_the_bottom_a_full_band_amplitude_tall():
    levels = np.array([[0.0, 0.5, 1.0, 2.0]], np.float32)
    places = landscape.project(levels, np.zeros(1, np.float32), W, H)
    xs, ys = places.points[0, :, 0], places.points[0, :, 1]
    assert xs.tolist() == pytest.approx([0.0, W / 3, 2 * W / 3, W])  # low bands on the left
    assert places.feet.tolist() == [H]
    tall = landscape.AMPLITUDE * H
    assert ys.tolist() == pytest.approx([H, H - tall / 2, H - tall, H - tall])  # clipped at 1
    assert (places.lefts[0], places.rights[0]) == (0.0, W)


def test_depth_shrinks_a_slice_towards_the_vanishing_point_and_lifts_it_to_the_horizon():
    depths = np.array([0.0, 0.5, 1.0], np.float32)
    places = landscape.project(np.ones((3, 5), np.float32), depths, W, H)
    widths = places.rights - places.lefts
    shares = 1 - (1 - landscape.BACK_SCALE) * depths
    assert widths.tolist() == pytest.approx((W * shares).tolist())
    assert ((places.lefts + places.rights) / 2).tolist() == pytest.approx([W / 2] * 3)  # centred
    assert places.feet[0] == H and places.feet[2] == pytest.approx(landscape.HORIZON * H)
    middle = H - (H - landscape.HORIZON * H) * 0.5**landscape.RISE
    assert places.feet[1] == pytest.approx(middle)
    heights = places.feet - places.points[:, 0, 1]  # each a full band
    assert heights.tolist() == pytest.approx((landscape.AMPLITUDE * H * shares).tolist())
    assert np.all(np.diff(places.feet) < 0)  # deeper is higher up


def test_depths_past_either_end_stand_at_the_front_or_the_back():
    places = landscape.project(np.ones((2, 2), np.float32), np.array([-1.0, 2.0]), W, H)
    assert places.feet.tolist() == pytest.approx([H, landscape.HORIZON * H])
    single = landscape.project(np.ones((1, 1), np.float32), np.zeros(1), W, H)
    assert single.points[0, 0, 0] == W / 2  # one band: in the middle


def test_slices_are_drawn_back_to_front_the_front_last_of_those_at_one_depth():
    depths = np.array([0.2, 0.9, 0.0, 0.5, 0.0], np.float32)
    assert landscape.back_to_front(depths).tolist() == [1, 3, 0, 2, 4]


def test_the_octaves_along_the_front_run_from_32_hz_at_the_left_to_16_khz_at_the_right():
    places = landscape.octave_places()
    assert [t for _, t in places] == ["32 Hz", "125", "500", "2 k", "8 k", "16 kHz"]
    ats = [a for a, _ in places]
    assert ats[0] == 0.0 and ats[-1] == pytest.approx(1.0)
    assert all(b > a for a, b in zip(ats, ats[1:], strict=False))
    assert ats[3] == pytest.approx(math.log(2000 / 32) / math.log(16000 / 32))  # by octaves


# ---------- colours ----------


def test_the_colour_steps_from_cyan_at_the_front_to_violet_at_the_back_darkened_with_depth():
    depths = np.linspace(0.0, 1.0, 5, dtype=np.float32)
    line, fill = landscape.colours(depths)
    assert line[0].tolist() == [*landscape.CYAN, 255]
    back = np.array(landscape.VIOLET) + (np.array(landscape.BACKGROUND) - landscape.VIOLET) * 0.35
    assert line[-1, :3].tolist() == pytest.approx(back.tolist(), abs=1)
    assert np.all(np.diff(line[:, 1].astype(int)) < 0)  # green falls: less cyan, step by step
    assert np.all(line[:, 3] == 255) and np.all(fill[:, 3] == 255)  # opaque: a fill hides
    # the fill: the background with a little of the slice's colour, less at the back
    ground = np.array(landscape.BACKGROUND)
    gaps = np.abs(fill[:, :3].astype(int) - ground).sum(axis=1)
    assert np.all(np.diff(gaps) <= 0) and gaps[0] > gaps[-1] > 0
    assert np.all(fill[:, :3].sum(axis=1) < line[:, :3].sum(axis=1))  # darker than its line


def test_the_colours_given_are_the_ones_stepped_between():
    line, fill = landscape.colours(np.array([0.0, 1.0]), (255, 0, 0), (0, 0, 255), (0, 0, 0))
    assert line[0].tolist() == [255, 0, 0, 255]
    assert line[1].tolist() == [0, 0, round(255 * 0.65), 255]
    assert fill[0].tolist() == [round(255 * landscape.FILL_FRONT), 0, 0, 255]


def test_lines_are_thicker_at_the_front():
    widths = landscape.line_widths(np.array([0.0, 0.5, 1.0], np.float32))
    assert widths.tolist() == pytest.approx([landscape.LINE_FRONT, 1.3, landscape.LINE_BACK])


# ---------- the strip ----------


def test_each_slice_is_its_fill_from_its_foot_then_its_line_joined_by_repeated_vertices():
    levels = np.array([[0.0, 1.0, 0.0], [0.5, 0.5, 0.5]], np.float32)
    depths = np.array([1.0, 0.0], np.float32)
    places = landscape.project(levels, depths, W, H)
    line, fill = landscape.colours(depths)
    widths = np.array([2.0, 4.0], np.float32)
    xy, rgba = landscape.strip(places, widths, line, fill)
    per = landscape.vertices_per_slice(3)
    assert per == 16 and xy.shape == (2 * per, 2) and rgba.shape == (2 * per, 4)
    back, front = xy[:per], xy[per:]
    # the fill: the first vertex repeated, then foot and line by turns, then the last repeated
    foot = places.feet[1]
    assert front[0].tolist() == front[1].tolist()
    assert front[1:7:2, 1].tolist() == pytest.approx([foot] * 3)
    assert front[2:8:2, 1].tolist() == pytest.approx(places.points[1, :, 1].tolist())
    assert front[7].tolist() == front[6].tolist()
    # the line: either side of each point, its width apart (flat: straight up and down)
    sides = front[9:15]
    assert np.abs(sides[0::2, 1] - sides[1::2, 1]).tolist() == pytest.approx([4.0] * 3)
    assert sides[0::2, 0].tolist() == pytest.approx(places.points[1, :, 0].tolist())
    assert front[8].tolist() == front[9].tolist() and front[15].tolist() == front[14].tolist()
    # colours: each part in its own, the back slice first
    assert (
        rgba[:8].tolist() == [fill[0].tolist()] * 8
        and rgba[8:16].tolist() == [line[0].tolist()] * 8
    )
    assert rgba[per + 8 :].tolist() == [line[1].tolist()] * 8
    assert back[1, 1] == pytest.approx(places.feet[0])


def test_a_line_keeps_its_width_across_a_slope():
    levels = np.array([[0.0, 1.0]], np.float32)  # one steep segment
    places = landscape.project(levels, np.zeros(1, np.float32), 10.0, 100.0)
    xy, _ = landscape.strip(places, np.array([2.0], np.float32), *landscape.colours(np.zeros(1)))
    sides = xy[7:11]
    assert np.hypot(*(sides[0] - sides[1])) == pytest.approx(2.0, rel=1e-4)


def test_no_slices_or_a_slice_of_one_band_make_a_strip_or_none():
    empty = landscape.project(np.zeros((0, 4), np.float32), np.zeros(0, np.float32), W, H)
    xy, rgba = landscape.strip(empty, np.zeros(0, np.float32), *landscape.colours(np.zeros(0)))
    assert xy.shape == (0, 2) and rgba.shape == (0, 4)
    one = landscape.project(np.ones((1, 1), np.float32), np.zeros(1, np.float32), W, H)
    xy, _ = landscape.strip(one, np.ones(1, np.float32), *landscape.colours(np.zeros(1)))
    assert len(xy) == landscape.vertices_per_slice(1) and np.isfinite(xy).all()


# ---------- the cost (A5.2, A5.3) ----------


@pytest.mark.slow
def test_a_frame_of_128_bands_over_6_seconds_leaves_most_of_a_16_ms_frame():
    """The arithmetic of a frame at the most bands and the longest speed, measured: the spectrum
    of 4,096 stereo samples, the landscape moved on, every slice projected, coloured and made a
    strip. The best of three runs of 30 frames; it takes about half a millisecond, and must stay
    under 4 ms, a quarter of a frame at 60 a second."""
    rate = 48_000
    s = spectrum.Spectrum(128, rate)
    land = landscape.Landscape(128, seconds=6.0)
    noise = np.random.default_rng(1)
    block = (noise.standard_normal((spectrum.SIZE, 2)) * 0.2).astype(np.float32)
    for _ in range(int(6.0 * 60) + 10):  # full: every slice of 6 seconds held
        land.advance(s.frame(block, 1 / 60), 1 / 60)
    assert len(land.slices()[1]) >= 6.0 / landscape.SLICE

    def frames(n=30):
        start = time.perf_counter()
        for _ in range(n):
            land.advance(s.frame(block, 1 / 60), 1 / 60)
            levels, depths = land.slices()
            places = landscape.project(levels, depths, 1800.0, 760.0)
            line, fill = landscape.colours(depths)
            landscape.strip(places, landscape.line_widths(depths), line, fill)
        return (time.perf_counter() - start) / n

    best = min(frames() for _ in range(3))
    assert best < 4e-3, f"{best * 1e3:.3f} ms a frame"
