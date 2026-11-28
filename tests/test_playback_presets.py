"""The equalizer's presets (src/musikata_core/audio/presets.py; R19.1, R19.3.1, R19.4, R19.6,
R19.7): the built-in ones against R19.3.1's table, a preset's kind changed either way, the preset
a song takes by its genre, and Equalizer APO's text, read in the shapes it and AutoEq write it
and written back.

Why: a preset is data the user keeps and moves between programs. A built-in one a little off its
table, a fit that strays, bands lost on the way back from graphic, a song taking the wrong preset,
or an AutoEq file that can't be read are each a promise broken without a sound to give it away.
Equalizer APO's files are data from outside: each shape testing.md's "Shapes" lists for
`audio.presets` has its test here."""

import math
import re

import numpy as np
import pytest
import reqdocs
from hypothesis import example, given
from hypothesis import strategies as st

from musikata_core.audio import eq, presets
from musikata_core.audio.eq import Band
from musikata_core.audio.presets import Preset

# ---------- the built-in presets (R19.3.1) ----------


def _hz(text):
    value = float(text.split()[0])
    return value * 1000 if "kHz" in text else value


def table_presets():
    """R19.3.1's table, read as presets: LS and HS at Q 0.7, each bell with its Q."""
    out = []
    for row in re.findall(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \|$", reqdocs.item("R19.3.1"), re.M):
        name, bands_text, preamp = (c.strip().replace("−", "-") for c in row)
        if name in ("Preset", "---"):
            continue
        bands = []
        for part in bands_text.split(";"):
            part = part.strip()
            kind = {"LS": "low-shelf", "HS": "high-shelf"}.get(part.split()[0], "bell")
            gain = float(re.search(r"([-+]?\d+(?:\.\d+)?) dB", part).group(1))
            q = re.search(r"Q (\d+(?:\.\d+)?)", part)
            freqs = re.findall(r"(\d+(?:\.\d+)?) (k?Hz)", part)
            for number, unit in freqs:
                bands.append(Band(kind, _hz(f"{number} {unit}"), gain,
                                  float(q.group(1)) if q else 0.7))  # fmt: skip
        out.append(Preset(name, "parametric", float(preamp.split()[0]), tuple(bands)))
    return out


def test_the_built_in_presets_are_r19_3_1s_table_row_for_row():
    assert tuple(table_presets()) == presets.BUILT_IN
    assert presets.BUILT_IN_NAMES == ("Flat", "Bass boost", "Treble boost", "Vocal", "Rock", "Pop",
                                      "Jazz", "Classical", "Electronic", "Loudness")  # fmt: skip


@pytest.mark.parametrize("preset", presets.BUILT_IN, ids=lambda p: p.name)
def test_each_built_in_presets_preamp_keeps_its_loudest_boost_under_full_scale(preset):
    for rate in (44_100, 48_000, 96_000):
        assert preset.preamp + eq.largest_boost(preset.bands, rate) <= 1e-6
    assert presets.headroom_of(preset) == 0.0


def test_a_new_parametric_preset_starts_with_flats_five_bands_at_0_db():
    new = presets.new_parametric("Car")
    assert new.name == "Car" and new.kind == "parametric" and new.preamp == 0.0
    assert [b.type for b in new.bands] == ["low-shelf", "bell", "bell", "bell", "high-shelf"]
    assert all(b.gain == 0 for b in new.bands)


def test_the_built_in_genres_are_matched_to_the_built_in_presets_of_the_same_name():
    from musikata_core import genres

    assert {g: g for g in genres.BUILT_IN if g in presets.BUILT_IN_NAMES} == presets.GENRES


# ---------- graphic presets and changing a preset's kind (R19.1, R19.6) ----------


def test_a_graphic_preset_is_ten_one_octave_bells_and_plays_as_that_parametric_preset_would():
    gains = (4.0, 3.5, 1.5, 0.0, -1.0, 0.0, 1.0, 2.0, 2.5, 2.0)
    car = Preset("Car", "graphic", -2.0, gains=gains)
    bands = presets.bands_of(car)
    assert [b.freq for b in bands] == [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16_000]
    assert all(b.type == "bell" and b.q == pytest.approx(math.sqrt(2)) for b in bands)
    # one octave wide: the Cookbook's Q for a bandwidth of one octave
    assert bands[0].q == pytest.approx(math.sqrt(2**1) / (2**1 - 1))
    assert [b.gain for b in bands] == list(gains)
    same = presets.to_parametric(car)
    assert presets.tone(same) == presets.tone(car)


def test_graphic_to_parametric_loses_nothing_the_ten_sliders_become_ten_bells():
    car = Preset("Car", "graphic", -2.0, gains=tuple(float(i - 5) for i in range(10)))
    back = presets.to_parametric(car, "Car (parametric)")
    assert back.kind == "parametric" and back.name == "Car (parametric)" and back.preamp == -2.0
    assert back.bands == presets.graphic_bands(car.gains)


@pytest.mark.parametrize("name, within", [("Pop", 1.0), ("Vocal", 1.2), ("Rock", 2.5)])
def test_parametric_to_graphic_fits_the_curve_and_says_how_close_it_comes(name, within):
    """A4.4: the least-squares fit in dB every twelfth of an octave; how close it comes is the
    largest difference between the two curves there."""
    rock = presets.find(name, ())
    graphic, closest = presets.to_graphic(rock, f"{name} (graphic)")
    assert graphic.kind == "graphic" and graphic.name == f"{name} (graphic)"
    assert graphic.preamp == rock.preamp and graphic.from_bands == rock.bands
    points = presets.fit_points()
    old = eq.curve_db(rock.bands, points, presets.CURVE_RATE)
    new = eq.curve_db(presets.bands_of(graphic), points, presets.CURVE_RATE)
    assert closest == pytest.approx(np.abs(old - new).max()) and closest < within


def test_the_fit_is_compared_every_twelfth_of_an_octave_from_20_hz_to_20_khz():
    points = presets.fit_points()
    assert points[0] == 20 and points[-1] <= 20_000 < points[-1] * 2 ** (1 / 12)
    assert np.allclose(np.log2(points[1:] / points[:-1]), 1 / 12)


def test_the_fit_is_the_least_squares_one():
    """No slider moved a little either way comes closer, in squares, to the curve."""
    bands = presets.find("Electronic", ()).bands
    gains, _ = presets.fit(bands)
    points = presets.fit_points()
    target = eq.curve_db(bands, points, presets.CURVE_RATE)

    def squares(g):
        return float(((target - eq.curve_db(presets.graphic_bands(g), points, 48_000)) ** 2).sum())

    best = squares(gains)
    for i in range(10):
        for step in (-0.05, 0.05):
            moved = list(gains)
            moved[i] += step
            assert squares(moved) >= best - 1e-9


def test_a_bell_on_a_sliders_frequency_an_octave_wide_is_fitted_exactly():
    gains, closest = presets.fit([Band("bell", 1000, 5, math.sqrt(2))])
    assert gains[5] == pytest.approx(5, abs=1e-6) and closest < 1e-6


def test_sliders_are_held_to_12_db_and_the_rest_fit_around_them():
    gains, closest = presets.fit([Band("low-cut", 300, 0, 0.7), Band("bell", 4000, 12, 0.5),
                                  Band("bell", 4000, 12, 0.5)])  # fmt: skip
    assert all(-12 <= g <= 12 for g in gains)
    assert min(gains) == -12 and max(gains) == 12 and closest > 1


def test_switching_back_before_a_slider_changes_gives_the_bands_exactly():
    """R19.6, A2.10: the bands are kept as `from_bands` until a slider changes."""
    rock = presets.find("Rock", ())
    graphic, _ = presets.to_graphic(rock)
    assert presets.to_parametric(graphic) == rock
    assert presets.with_gains(graphic, graphic.gains) is graphic  # no slider changed
    moved = presets.with_gains(graphic, (1.0,) + graphic.gains[1:])
    assert moved.from_bands is None and moved.gains[0] == 1.0
    assert presets.to_parametric(moved).bands == presets.graphic_bands(moved.gains)
    assert presets.to_graphic(moved) == (moved, 0.0)


# ---------- by genre (R19.4) ----------

KNOWN = (*presets.BUILT_IN_NAMES, "Car")


@pytest.mark.parametrize(
    "genres, by_genre, for_song, want",
    [
        (["Classical"], True, None, presets.Pick("Classical", "genre", "Classical")),
        (["Ambient", "jazz", "Rock"], True, None, presets.Pick("Jazz", "genre", "jazz")),  # first
        (["Ambient"], True, None, presets.Pick("Car", "chosen")),  # none has one
        ([], True, None, presets.Pick("Car", "chosen")),
        (["Classical"], False, None, presets.Pick("Car", "chosen")),  # by genre off
        (["Classical"], True, "Pop", presets.Pick("Pop", "song")),  # chosen by hand for it
        (["Classical"], False, "Pop", presets.Pick("Car", "chosen")),
        (["Gone"], True, None, presets.Pick("Car", "chosen")),  # its preset was deleted
    ],
)
def test_a_song_takes_its_first_genres_preset_else_the_one_chosen(genres, by_genre, for_song, want):
    table = {**presets.GENRES, "Gone": "Deleted"}
    got = presets.pick(genres, table, "Car", KNOWN, by_genre, for_song)
    assert got == want


def test_genres_are_matched_by_the_key_given_and_a_chosen_preset_gone_is_flat():
    from musikata_core import genres

    table = {"Hip-Hop": "Bass boost"}
    got = presets.pick(["hip hop"], table, "Car", KNOWN, True, key=genres.key)
    assert got == presets.Pick("Bass boost", "genre", "hip hop")
    assert presets.pick([], table, "Gone", KNOWN, False) == presets.Pick("Flat", "chosen")


def test_a_preset_chosen_by_hand_while_by_genre_plays_for_that_song_and_the_next_takes_its_own():
    choice = presets.Choice(on=True, chosen="Flat", by_genre=True)
    assert choice.choose("Pop", ticket=7)
    assert choice.pick(["Classical"], 7) == presets.Pick("Pop", "song")
    assert choice.pick(["Classical"], 8) == presets.Pick("Classical", "genre", "Classical")
    assert choice.pick(["Ambient"], 8) == presets.Pick("Pop", "chosen")  # the one chosen now
    assert not choice.choose("Nothing", 7) and choice.chosen == "Pop"
    off = presets.Choice(on=True)
    off.choose("Rock", 7)
    assert off.for_song is None and off.pick(["Jazz"], 8) == presets.Pick("Rock", "chosen")


def test_the_tone_a_song_is_told_is_its_presets_and_none_while_off():
    car = Preset("Car", "graphic", -2.0, gains=(1.0,) * 10)
    choice = presets.Choice(on=False, chosen="Car", custom=(car,))
    assert choice.tone([], 1) is None
    choice.on = True
    assert choice.tone([], 1) == presets.tone(car)
    assert choice.preset("Nothing") == presets.BUILT_IN[0]


def test_bands_set_are_heard_wherever_that_preset_plays_until_another_is_chosen():
    """R19.3: changed and not yet saved; values brought into R19.1's ranges."""
    choice = presets.Choice(on=True, chosen="Rock")
    edited = choice.set_bands("Rock", -20, [Band("bell", 5, 30, 50), *(Band("bell", 1000),) * 12])
    assert edited.preamp == -12 and len(edited.bands) == 10
    assert edited.bands[0] == Band("bell", 20, 12, 10)
    assert choice.tone([], 3) == presets.tone(edited)
    assert presets.find("Rock", ()).bands != edited.bands  # the built-in is as it was
    graphic = choice.set_bands("Rock", -3, None, [2.0] * 10)
    assert graphic.kind == "graphic" and graphic.gains == (2.0,) * 10 and graphic.from_bands is None
    assert choice.set_bands("Rock", -3, None, [20.0] * 10).gains == (12.0,) * 10
    choice.choose("Pop", 0)
    assert choice.edit is None and choice.preset("Rock") == presets.find("Rock", ())


# ---------- Equalizer APO's text (R19.7) ----------

AUTOEQ = """# Sennheiser HD 600 (AutoEq)\r
Preamp: -6.2 dB\r
Filter 1: ON LSC Fc 105 Hz Gain 5.5 dB Q 0.70\r
Filter 2: ON PK Fc 2560 Hz Gain -1.4 dB Q 2.53\r
Filter 3: ON HSC Fc 10000 Hz Gain -2.4 dB Q 0.70\r
"""


def read(text, name="Phones"):
    return presets.read_apo(text, name)


def test_autoeqs_file_is_a_custom_parametric_preset_named_after_the_file():
    got = read(AUTOEQ, "HD 600")
    assert got.preset == Preset("HD 600", "parametric", -6.2, (
        Band("low-shelf", 105, 5.5, 0.7), Band("bell", 2560, -1.4, 2.53),
        Band("high-shelf", 10_000, -2.4, 0.7)))  # fmt: skip
    assert got.skipped == () and got.changed == ()


@pytest.mark.parametrize(
    "line, band",
    [
        ("Filter 1: ON PK Fc 105 Hz Gain -3.2 dB Q 0.70", Band("bell", 105, -3.2, 0.7)),
        ("Filter: ON PK Fc 105 Hz Gain -3.2 dB Q 0.70", Band("bell", 105, -3.2, 0.7)),  # no number
        ("Filter 1: ON PK Fc 105Hz Gain -3.2dB Q 0.70", Band("bell", 105, -3.2, 0.7)),  # no spaces
        ("Filter 1: ON PK Fc 105 Gain -3.2 Q 0.7", Band("bell", 105, -3.2, 0.7)),  # no units
        ("filter 1: on pk fc 105 hz gain -3.2 db q 0.70", Band("bell", 105, -3.2, 0.7)),  # case
        ("Filter  1 :\tON   PK  Fc 105 Hz  Gain -3.2 dB  Q 0.70  ", Band("bell", 105, -3.2, 0.7)),
        ("Filter 1: ON PK Fc 105 Hz Gain -3,2 dB Q 0,70", Band("bell", 105, -3.2, 0.7)),  # commas
        ("Filter 1: ON PK Fc 1000 Hz Gain 3 dB BW Oct 1", Band("bell", 1000, 3, math.sqrt(2))),
        ("Filter 1: ON PK Fc 1000 Hz Gain 3 dB", Band("bell", 1000, 3, 1 / math.sqrt(2))),
        ("Filter 1: ON LSC Fc 105 Hz Gain 5.5 dB", Band("low-shelf", 105, 5.5, 1 / math.sqrt(2))),
        ("Filter 1: ON LS Fc 105 Hz Gain 5.5 dB Q 0.9", Band("low-shelf", 105, 5.5, 0.9)),
        (
            "Filter 1: ON HSC 12dB Fc 8000 Hz Gain -2 dB",
            Band("high-shelf", 8000, -2, 1 / math.sqrt(2)),
        ),
        ("Filter 1: ON HS Fc 8000 Hz Gain -2 dB Q 1.2", Band("high-shelf", 8000, -2, 1.2)),
        ("Filter 1: ON LP Fc 12000 Hz", Band("high-cut", 12_000, 0, 1 / math.sqrt(2))),
        ("Filter 1: ON LPQ Fc 12000 Hz Q 0.5", Band("high-cut", 12_000, 0, 0.5)),
        ("Filter 1: ON HP Fc 30 Hz Gain 4 dB", Band("low-cut", 30, 0, 1 / math.sqrt(2))),
        ("Filter 1: ON HPQ Fc 30 Hz Q 1.1", Band("low-cut", 30, 0, 1.1)),
    ],
)
def test_each_filter_line_is_read_in_the_shapes_it_is_written(line, band):
    got = read(f"Preamp: -1 dB\n{line}\n").preset.bands
    assert len(got) == 1
    assert got[0].type == band.type
    assert (got[0].freq, got[0].gain, got[0].q) == pytest.approx((band.freq, band.gain, band.q))


def test_a_shelf_given_a_slope_takes_the_q_that_slope_is():
    got = read("Filter 1: ON LSC 6 dB Fc 100 Hz Gain 6 dB\n").preset.bands[0]
    a = 10 ** (6 / 40)
    assert got.q == pytest.approx(1 / math.sqrt((a + 1 / a) * (1 / 0.5 - 1) + 2))


def test_other_lines_and_filters_past_the_tenth_are_listed_as_skipped():
    text = "\n".join([
        "Device: Speakers", "Channel: L R", "GraphicEQ: 25 0; 40 -1.2", "Include: other.txt",
        "Filter 1: OFF PK Fc 1000 Hz Gain 3 dB Q 1", "Filter 2: ON NO Fc 50 Hz",
        "Filter 3: ON PK Gain 3 dB Q 1", "Preamp: loud",
        *(f"Filter {i}: ON PK Fc {100 * i} Hz Gain 1 dB Q 1" for i in range(4, 16)),
    ])  # fmt: skip
    got = read(text)
    assert len(got.preset.bands) == 10 and got.preset.bands[-1].freq == 1300
    assert got.skipped == (
        "Device: Speakers", "Channel: L R", "GraphicEQ: 25 0; 40 -1.2", "Include: other.txt",
        "Filter 1: OFF PK Fc 1000 Hz Gain 3 dB Q 1", "Filter 2: ON NO Fc 50 Hz",
        "Filter 3: ON PK Gain 3 dB Q 1", "Preamp: loud",
        "Filter 14: ON PK Fc 1400 Hz Gain 1 dB Q 1", "Filter 15: ON PK Fc 1500 Hz Gain 1 dB Q 1",
    )  # fmt: skip


def test_comments_blank_lines_crlf_and_a_bom_are_passed_by():
    got = read("﻿# made by hand\r\n\r\n   \r\nPreamp: -3 dB\r\nFilter 1: ON PK Fc 1 kHz\r\n"
               "Filter 2: ON PK Fc 1000 Hz Gain 2 dB Q 1\r\n")  # fmt: skip
    assert got.preset.preamp == -3 and len(got.preset.bands) == 2 and got.skipped == ()


def test_preamps_add_up_and_one_missing_is_0_db():
    assert read("Preamp: -3 dB\nPreamp: -2.5 dB\nFilter 1: ON PK Fc 1000 Hz Gain 2 dB Q 1\n")\
        .preset.preamp == -5.5  # fmt: skip
    assert read("Filter 1: ON PK Fc 1000 Hz Gain 2 dB Q 1\n").preset.preamp == 0.0


def test_values_out_of_r19_1s_ranges_are_brought_in_and_listed():
    got = read("Preamp: -20 dB\nFilter 1: ON PK Fc 25000 Hz Gain 15 dB Q 20\n"
               "Filter 2: ON PK Fc 1000 Hz Gain 2 dB Q 1\n")  # fmt: skip
    assert got.preset.preamp == -12
    assert got.preset.bands[0] == Band("bell", 20_000, 12, 10)
    assert got.changed == ("Preamp: -12 dB", "Filter 1: ON PK Fc 25000 Hz Gain 15 dB Q 20")


@pytest.mark.parametrize("text", ["", "# nothing\n", "Preamp: -6 dB\n", "GraphicEQ: 25 0\n"])
def test_a_file_with_no_filter_it_reads_is_its_own_error(text):
    with pytest.raises(presets.PresetFileError):
        read(text)


@pytest.mark.parametrize(
    "data",
    [
        AUTOEQ.encode("utf-8"),
        b"\xef\xbb\xbf" + AUTOEQ.encode("utf-8"),
        AUTOEQ.encode("utf-16"),  # with its BOM, as Notepad saves "Unicode"
        AUTOEQ.encode("utf-16-be").join([b"\xfe\xff", b""]),
        ("# Störung\n" + AUTOEQ).encode("cp1252"),
    ],
)
def test_a_files_bytes_are_read_in_its_encoding(data):
    assert len(read(presets.decode_apo(data)).preset.bands) == 3


def test_a_preset_written_is_equalizer_apos_text_a_graphic_one_as_its_ten_bells():
    rock = presets.find("Rock", ())
    assert presets.write_apo(rock) == (
        "Preamp: -4.5 dB\n"
        "Filter 1: ON LSC Fc 80 Hz Gain 4 dB Q 0.7\n"
        "Filter 2: ON PK Fc 400 Hz Gain -2 dB Q 1\n"
        "Filter 3: ON PK Fc 2500 Hz Gain 2 dB Q 1.2\n"
        "Filter 4: ON HSC Fc 8000 Hz Gain 3.5 dB Q 0.7\n"
    )
    cuts = Preset("Cuts", "parametric", 0, (Band("low-cut", 30, 0, 0.5), Band("high-cut", 12000)))
    assert "Filter 1: ON HPQ Fc 30 Hz Q 0.5\nFilter 2: ON LPQ Fc 12000 Hz Q 0.7\n" in (
        presets.write_apo(cuts)
    )
    car = Preset("Car", "graphic", -2, gains=(0.25,) * 10)
    written = presets.write_apo(car)
    assert written.count(" PK ") == 10 and "Fc 31 Hz Gain 0.25 dB Q 1.4142135623730951" in written
    assert read(written, "Car").preset.bands == presets.bands_of(car)


bands = st.builds(
    Band,
    st.sampled_from(eq.TYPES),
    st.floats(20, 20_000),
    st.floats(-12, 12),
    st.floats(0.1, 10),
).map(lambda b: Band(b.type, b.freq, 0.0, b.q) if b.type in eq.CUTS else b)


@given(st.lists(bands, min_size=1, max_size=10), st.floats(-12, 12))
@example([Band("bell", 20, 1e-7, 0.1)], 1e-12)
def test_any_preset_written_then_read_gives_back_its_bands_and_preamp(written, preamp):
    preset = Preset("x", "parametric", preamp, tuple(written))
    got = read(presets.write_apo(preset), "x")
    assert got.preset == preset and got.skipped == () and got.changed == ()


@given(st.text(max_size=300))
@example("Filter 1: ON PK Fc 1e400 Hz Gain 1 dB Q 1")
@example("Filter 1: ON PK Fc 100 Hz Gain nan dB Q 1")
@example("Filter 1: ON PK Fc , Hz")
@example("Preamp: 1e400 dB\nFilter 1: ON PK Fc 100 Hz")
@example("Filter 1: ON LSC 0 dB Fc 100 Hz Gain 12 dB\nFilter 2: ON PK Fc 100 Hz BW Oct 0")
def test_any_text_at_all_reads_as_a_preset_or_its_own_error(text):
    try:
        got = read(text)
    except presets.PresetFileError:
        return
    assert 1 <= len(got.preset.bands) <= 10
    assert all(eq.FREQS[0] <= b.freq <= eq.FREQS[1] and eq.QS[0] <= b.q <= eq.QS[1]
               for b in got.preset.bands)  # fmt: skip


@given(st.binary(max_size=300))
@example(b"\xff\xfe\x00")
@example(b"\xfe\xff\x00F")
def test_any_bytes_at_all_read_as_text(data):
    assert isinstance(presets.decode_apo(data), str)


# ---------- as the shared settings keep them (A2.10) ----------


def test_a_preset_kept_is_read_back_as_it_was_and_its_unknown_fields_are_kept():
    rock, _ = presets.to_graphic(presets.find("Rock", ()), "Rock (graphic)")
    data = presets.preset_data(rock, {"name": "Rock (graphic)", "colour": "red", "gains": []})
    assert data["colour"] == "red" and "from_bands" in data
    problems = []
    assert presets.preset_of(data, "p", problems) == rock and problems == []
    cut = presets.band_data(Band("high-cut", 12_000, 0, 0.7))
    assert cut == {"type": "high-cut", "freq": 12_000, "q": 0.7}
