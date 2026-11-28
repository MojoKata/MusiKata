"""The equalizer's sound (src/musikata_core/audio/eq.py; A4.4, R19.1, R7.6.1): each band's response
against the Audio EQ Cookbook's, the filter against the curve it is built from, the filter applied
block by block against one convolution, its crossfades, its limiter and its headroom, shown by
numbers on generated blocks.

Why: an equalizer is heard as one filter. A response a little off, a block boundary that clicks,
a crossfade that steps, a filter that delays the sound, or a sample past full scale are each
heard, and each shows only in the numbers."""

import math

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from musikata_core.audio import eq, presets

RATE = 48_000
LOOK = eq.frames_of(eq.LOOK_AHEAD, RATE)
RAMP = eq.frames_of(eq.RAMP_SECONDS, RATE)
_made: dict = {}


def built(preset_name: str, rate: int = RATE) -> eq.Design:
    """A built-in preset's filter, built once for the whole run."""
    key = (preset_name, rate)
    if key not in _made:
        _made[key] = eq.design(presets.tone(presets.find(preset_name, ())), rate)
    return _made[key]


def noise(frames, level=0.1, seed=1, channels=2):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((frames, channels)) * level).astype(np.float32)


def through(e, x, step=1000):
    """`x` pushed through `e` in blocks of `step`, and flushed: every frame out."""
    out = [e.push(x[i : i + step]) for i in range(0, len(x), step)]
    return np.concatenate([*out, e.flush()])


def filtered(design, x):
    """`x` through `design`'s taps as one convolution: what the equalizer must give."""
    n = 1 << math.ceil(math.log2(len(x) + len(design.taps)))
    spectrum = np.fft.rfft(x.astype(np.float64), n, axis=0) * np.fft.rfft(design.taps, n)[:, None]
    return np.fft.irfft(spectrum, n, axis=0)[: len(x)]


def cookbook_db(kind, f0, gain, q, freqs, rate):
    """The Cookbook's transfer function written out again, evaluated as complex numbers."""
    w0 = 2 * math.pi * f0 / rate
    alpha, cos, a = math.sin(w0) / (2 * q), math.cos(w0), 10 ** (gain / 40)
    if kind == "bell":
        b, den = [1 + alpha * a, -2 * cos, 1 - alpha * a], [1 + alpha / a, -2 * cos, 1 - alpha / a]
    elif kind == "low-shelf":
        r = 2 * math.sqrt(a) * alpha
        b = [a * ((a + 1) - (a - 1) * cos + r), 2 * a * ((a - 1) - (a + 1) * cos),
             a * ((a + 1) - (a - 1) * cos - r)]  # fmt: skip
        den = [(a + 1) + (a - 1) * cos + r, -2 * ((a - 1) + (a + 1) * cos),
               (a + 1) + (a - 1) * cos - r]  # fmt: skip
    elif kind == "high-shelf":
        r = 2 * math.sqrt(a) * alpha
        b = [a * ((a + 1) + (a - 1) * cos + r), -2 * a * ((a - 1) + (a + 1) * cos),
             a * ((a + 1) + (a - 1) * cos - r)]  # fmt: skip
        den = [(a + 1) - (a - 1) * cos + r, 2 * ((a - 1) - (a + 1) * cos),
               (a + 1) - (a - 1) * cos - r]  # fmt: skip
    elif kind == "high-cut":
        b, den = [(1 - cos) / 2, 1 - cos, (1 - cos) / 2], [1 + alpha, -2 * cos, 1 - alpha]
    else:
        b, den = [(1 + cos) / 2, -(1 + cos), (1 + cos) / 2], [1 + alpha, -2 * cos, 1 - alpha]
    z = np.exp(-1j * 2 * np.pi * np.asarray(freqs) / rate)
    h = (b[0] + b[1] * z + b[2] * z * z) / (den[0] + den[1] * z + den[2] * z * z)
    return 20 * np.log10(np.abs(h))


def db_at(band, *freqs, rate=RATE):
    return eq.response_db(band, np.array(freqs, float), rate)


# ---------- the bands (R19.1) ----------


def test_each_band_types_response_is_the_cookbooks_at_known_points():
    bell = eq.Band("bell", 1000, 6, 2)
    assert db_at(bell, 1000)[0] == pytest.approx(6, abs=1e-6)  # its gain at its frequency
    assert abs(db_at(bell, 0)[0]) < 1e-6 and abs(db_at(bell, RATE / 2)[0]) < 1e-6
    low = eq.Band("low-shelf", 200, -8, 0.7)
    assert db_at(low, 0)[0] == pytest.approx(-8, abs=1e-6)  # its gain below it
    assert db_at(low, 200)[0] == pytest.approx(-4, abs=1e-6)  # half its gain at its middle
    assert abs(db_at(low, RATE / 2)[0]) < 1e-6
    high = eq.Band("high-shelf", 6000, 6, 0.7)
    assert db_at(high, RATE / 2)[0] == pytest.approx(6, abs=1e-6)
    assert db_at(high, 6000)[0] == pytest.approx(3, abs=1e-6)
    assert abs(db_at(high, 0)[0]) < 1e-6
    # the cuts: no gain; 0 dB where they pass, 20 log Q at their frequency, and falling past it
    lp = eq.Band("high-cut", 8000, 5, 2.0)
    assert abs(db_at(lp, 0)[0]) < 1e-6 and db_at(lp, 8000)[0] == pytest.approx(20 * math.log10(2))
    assert db_at(lp, 16000)[0] < -18
    hp = eq.Band("low-cut", 80, -3, 0.5)
    assert abs(db_at(hp, RATE / 2)[0]) < 1e-6 and db_at(hp, 80)[0] == pytest.approx(-6.0206, 1e-4)
    assert db_at(hp, 20)[0] < -20 and db_at(hp, 0)[0] == eq.FLOOR_DB


@pytest.mark.parametrize("kind", eq.TYPES)
@pytest.mark.parametrize(
    "f0, gain, q, rate",
    [(20, 12, 10, 44_100), (100, -12, 0.1, 48_000), (1000, 4.5, 0.7, 48_000),
     (12_000, -6, 1.4, 44_100), (20_000, 9, 3, 96_000)],
)  # fmt: skip
def test_each_band_types_response_is_the_cookbooks_transfer_function_everywhere(
    kind, f0, gain, q, rate
):
    freqs = np.geomspace(10, rate / 2 * 0.999, 300)
    want = np.maximum(cookbook_db(kind, f0, gain, q, freqs, rate), eq.FLOOR_DB)
    got = db_at(eq.Band(kind, f0, gain, q), *freqs, rate=rate)
    assert np.allclose(got, want, atol=1e-6)


def test_a_band_past_the_nyquist_frequency_is_held_under_it():
    """A 20 kHz band at 32 kHz plays as one just under 16 kHz, not as nonsense."""
    band = eq.Band("bell", 20_000, 6, 1)
    assert db_at(band, 0.49 * 32_000, rate=32_000)[0] == pytest.approx(6)


def test_a_curve_is_its_bands_responses_summed_and_none_is_flat():
    bands = [eq.Band("low-shelf", 100, 4), eq.Band("bell", 1000, -3, 1), eq.Band("high-cut", 9000)]
    freqs = np.geomspace(20, 20_000, 50)
    assert np.allclose(
        eq.curve_db(bands, freqs, RATE), sum(eq.response_db(b, freqs, RATE) for b in bands)
    )
    assert not eq.curve_db([], freqs, RATE).any()


def test_the_largest_boost_is_a_bells_peak_a_shelfs_plateau_or_where_bells_add_up():
    assert eq.largest_boost([eq.Band("bell", 1234, 7, 10)], RATE) == pytest.approx(7)
    assert eq.largest_boost([eq.Band("low-shelf", 100, 5, 0.7)], RATE) == pytest.approx(5)
    assert eq.largest_boost([eq.Band("high-shelf", 9000, -5, 0.7)], RATE) == pytest.approx(
        0, abs=1e-6
    )
    two = [eq.Band("bell", 1000, 6, 1), eq.Band("bell", 1500, 6, 1)]
    between = eq.curve_db(two, np.geomspace(1000, 1500, 2000), RATE).max()
    assert eq.largest_boost(two, RATE) == pytest.approx(between, abs=0.01) and between > 6
    # a cut's resonance is a boost too: Q 10 rings 20 dB over its frequency
    assert eq.largest_boost([eq.Band("low-cut", 30, 0, 10)], RATE) == pytest.approx(20, abs=0.01)
    assert eq.largest_boost([], RATE) == 0.0


def test_the_level_held_down_is_the_preamp_plus_the_largest_boost_when_over_0_db():
    """R19.1: "−2.7 dB more, to keep from clipping"."""
    boost = eq.Tone((eq.Band("bell", 1000, 8, 1),), -5.3)
    assert eq.headroom(boost, RATE) == pytest.approx(2.7)
    assert eq.headroom(eq.Tone((eq.Band("bell", 1000, 8, 1),), -8), RATE) == 0.0
    assert eq.headroom(eq.Tone((eq.Band("bell", 1000, -8, 1),), 3), RATE) == pytest.approx(3)
    assert eq.headroom(eq.Tone((), 0), RATE) == 0.0


# ---------- the filter ----------


def test_the_filter_is_16384_taps_at_44_1_and_48_khz_and_lasts_as_long_at_higher_rates():
    assert [eq.taps_for(r) for r in (8000, 44_100, 48_000)] == [16_384] * 3
    assert [eq.taps_for(r) for r in (88_200, 96_000, 176_400, 192_000, 384_000)] == [
        32_768, 32_768, 65_536, 65_536, 131_072
    ]  # fmt: skip


def magnitude_db(design, freqs):
    n = 1 << 20
    spectrum = np.abs(np.fft.rfft(design.taps, n))
    bins = np.round(np.asarray(freqs) * n / design.rate).astype(int)
    return 20 * np.log10(spectrum[bins])


@pytest.mark.parametrize("name", presets.BUILT_IN_NAMES)
def test_each_built_in_presets_filter_has_its_curve_with_its_preamp(name):
    """A4.4: the FIR's magnitude is the summed curve, the preamp added, from 20 Hz to 20 kHz."""
    preset = presets.find(name, ())
    design = built(name)
    freqs = np.geomspace(20, 20_000, 400)
    want = eq.curve_db(preset.bands, freqs, RATE) + preset.preamp
    assert np.abs(magnitude_db(design, freqs) - want).max() < 0.1
    assert design.headroom == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize(
    "band",
    [eq.Band("bell", 62, 12, 4), eq.Band("bell", 16_000, -12, 0.1), eq.Band("low-shelf", 20, 12),
     eq.Band("high-shelf", 20_000, -12, 4), eq.Band("low-cut", 200, 0, 0.5),
     eq.Band("high-cut", 5000, 0, 3)],
)  # fmt: skip
def test_a_filter_of_each_band_type_at_its_extremes_has_its_curve(band):
    """A narrow, low band is still right at 16,384 taps (A4.4); the level held down by
    its boost (R19.1) is in the filter, so its loudest is full scale."""
    tone = eq.Tone((band,), 0.0)
    design = eq.design(tone, RATE)
    freqs = np.concatenate([np.geomspace(20, 20_000, 300), [min(band.freq, 20_000)]])
    want = np.maximum(eq.curve_db([band], freqs, RATE) - design.headroom, -60)
    got = np.maximum(magnitude_db(design, freqs), -60)
    assert np.abs(got - want).max() < 0.5
    assert design.headroom == pytest.approx(max(0.0, eq.largest_boost([band], RATE)))
    assert magnitude_db(design, freqs).max() < 0.05


def test_the_filter_measured_with_sines_through_the_equalizer_gives_each_presets_curve():
    """testing.md, "What tier 1 covers": the equalizer's measured response matches the curve."""
    design = built("Electronic")
    e = eq.Equalizer(RATE, 1)
    e.schedule(0, design, ramped=False)
    for freq in (40.0, 250.0, 1200.0, 4000.0, 9000.0, 15_000.0):
        t = np.arange(RATE // 2) / RATE
        x = (0.1 * np.sin(2 * np.pi * freq * t)).astype(np.float32)[:, None]
        e.rewind(0)
        y = through(e, x, 4800)[-RATE // 8 :, 0]
        ts = t[-RATE // 8 :]
        fit = np.linalg.lstsq(
            np.stack([np.sin(2 * np.pi * freq * ts), np.cos(2 * np.pi * freq * ts)], 1),
            y,
            rcond=None,
        )[0]
        heard = 20 * math.log10(math.hypot(*fit) / 0.1)
        want = eq.curve_db(design.tone.bands, np.array([freq]), RATE)[0] + design.tone.preamp
        assert heard == pytest.approx(want, abs=0.1), freq


def test_the_filter_is_minimum_phase_and_adds_no_delay():
    """Its energy comes as early as any filter of its magnitude can bring it (the
    minimum-phase one's), and a click comes out where it went in."""
    design = built("Rock")
    taps = design.taps
    spectrum = np.abs(np.fft.rfft(taps))
    linear = np.roll(np.fft.irfft(spectrum, len(taps)), len(taps) // 2)  # the same magnitude, late
    early, later = np.cumsum(taps**2), np.cumsum(linear**2)
    assert np.all(early >= later - 1e-9 * later[-1])
    assert early[48] > 0.9 * early[-1]  # nine tenths of it in the first millisecond
    click = np.zeros((4000, 1), np.float32)
    click[1000] = 0.5
    e = eq.Equalizer(RATE, 1)
    e.schedule(0, design, ramped=False)
    y = through(e, click)
    assert not y[:1000].any() and int(np.abs(y).argmax()) - 1000 < 5


def test_flat_is_transparent_to_within_float_rounding():
    x = noise(RATE // 2, 0.15)
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, built("Flat"), ramped=False)
    y = through(e, x, 777)
    assert len(y) == len(x) and np.abs(y - x).max() < 1e-7


@pytest.mark.slow
@given(st.lists(st.integers(1, 3000), min_size=1, max_size=40))
@example([1] * 40)
@example([16_384 // eq.PARTS])
def test_blocks_of_any_length_filter_exactly_as_one_convolution(sizes):
    """The parts of the filter applied a block at a time, a block cut anywhere, give what one
    long convolution gives (A4.4's overlap-add)."""
    x = noise(sum(sizes) + 300, seed=len(sizes))
    design = built("Vocal")
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, design, ramped=False)
    out, at = [], 0
    for n in sizes:
        out.append(e.push(x[at : at + n]))
        at += n
    out += [e.push(x[at:]), e.flush()]
    y = np.concatenate(out)
    assert len(y) == len(x)
    assert np.abs(y - filtered(design, x)).max() < 1e-6


# ---------- on and off ----------


def test_off_gives_back_what_it_is_given_untouched_and_holds_nothing():
    """R19.1: the equalizer on or off as a whole; off, the samples pass untouched."""
    e = eq.Equalizer(RATE, 2)
    x = noise(5000, 3.0)  # even past full scale: off, nothing touches it
    assert e.push(x[:1234]) is not None and np.array_equal(e.push(x[1234:]), x[1234:])
    assert e.held == 0 and e.design is None and len(e.flush()) == 0
    e.schedule(9000, None)
    assert np.array_equal(e.push(x), x)


def test_on_the_limiters_look_ahead_is_held_back_and_given_out_when_the_stream_ends():
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, built("Rock"), ramped=False)
    x = noise(10_000)
    first = e.push(x[:5000])
    assert len(first) == 5000 - LOOK + 1 and e.held == LOOK - 1
    assert len(e.push(x[5000:])) == 5000 and e.held == LOOK - 1
    assert len(e.flush()) == LOOK - 1 and e.held == 0


def test_turned_on_and_off_it_crossfades_in_and_out_and_off_again_holds_nothing():
    x = noise(RATE * 2)
    design = built("Bass boost")
    e = eq.Equalizer(RATE, 2)
    e.schedule(10_000, design)
    e.schedule(50_000, None)
    y = through(e, x, 777)
    assert np.array_equal(y[:10_000], x[:10_000]) and np.array_equal(
        y[50_000 + RAMP :], x[50_000 + RAMP :]
    )
    wet = filtered(design, x)
    assert np.abs(y[10_000 + RAMP : 50_000] - wet[10_000 + RAMP : 50_000]).max() < 1e-6
    t = np.clip((np.arange(10_000, 10_000 + RAMP) - 10_000 + 1) / RAMP, 0, 1)[:, None]
    fade = (1 - t) * x[10_000 : 10_000 + RAMP] + t * wet[10_000 : 10_000 + RAMP]
    assert np.abs(y[10_000 : 10_000 + RAMP] - fade).max() < 1e-6
    assert e.held == 0 and np.array_equal(e.push(x[:100]), x[:100])


# ---------- changes: crossfaded, heard at once ----------


class Out:
    """What came out of an equalizer, by place, cut back as the stream is."""

    def __init__(self):
        self.frames = []

    def add(self, block):
        self.frames.extend(block)

    def cut(self, place):
        del self.frames[place:]

    def array(self):
        return np.array(self.frames)


def scheduled(x, *steps):
    """`x` through an equalizer with `steps` (place, design, ramped) set from the start."""
    e = eq.Equalizer(RATE, 2)
    for place, design, ramped in steps:
        e.schedule(place, design, ramped)
    return through(e, x)


@pytest.mark.parametrize("at", [30_000, 31_234, 30_000 + 1024])
def test_a_change_heard_at_once_filters_again_from_where_the_device_has_got_to(at):
    """A4.4: the stream taken back to place `at`, what was given from there filtered again with
    the new filter crossfaded in, as if the change had been there all along."""
    x = noise(RATE * 2)
    old, new = built("Bass boost"), built("Rock")
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, old, ramped=False)
    out = Out()
    for i in range(0, 45_000, 900):
        out.add(e.push(x[i : i + 900]))
    out.cut(at)
    e.retune(at, at, new)
    assert e.redoing
    with pytest.raises(RuntimeError):
        e.push(x[45_000:])
    while e.redoing:
        out.add(e.redo(960))
    out.add(e.push(x[45_000:]))
    out.add(e.flush())
    want = scheduled(x, (0, old, False), (at, new, True))
    assert np.array_equal(out.array(), want)


def test_a_change_is_crossfaded_over_50_ms_with_each_filter_whole_on_either_side():
    x = noise(RATE)
    old, new = built("Treble boost"), built("Loudness")
    y = scheduled(x, (0, old, False), (20_000, new, True))
    a, b = filtered(old, x), filtered(new, x)
    assert np.abs(y[:20_000] - a[:20_000]).max() < 1e-6
    assert np.abs(y[20_000 + RAMP :] - b[20_000 + RAMP :]).max() < 1e-6
    t = (np.arange(RAMP) + 1)[:, None] / RAMP
    cross = (1 - t) * a[20_000 : 20_000 + RAMP] + t * b[20_000 : 20_000 + RAMP]
    assert np.abs(y[20_000 : 20_000 + RAMP] - cross).max() < 1e-6
    assert round(0.05 * RATE) == RAMP


def test_a_change_made_again_before_the_last_crossfade_ends_goes_on_from_where_it_was():
    """A slider dragged: each change starts before the last one's crossfade has ended, and the
    sound moves on from the mix it had reached, never stepping back to a filter whole."""
    x = noise(RATE, seed=3)
    designs = [built(n) for n in ("Bass boost", "Treble boost", "Rock")]
    y = scheduled(
        x,
        (0, designs[0], False),
        (10_000, designs[1], True),
        (10_000 + RAMP // 3, designs[2], True),
    )
    a, b, c = (filtered(d, x) for d in designs)
    i = np.arange(10_000, 10_000 + 2 * RAMP)
    t1 = np.clip((i - 10_000 + 1) / RAMP, 0, 1)[:, None]
    t2 = np.clip((i - 10_000 - RAMP // 3 + 1) / RAMP, 0, 1)[:, None]
    first = (1 - t1) * a[i] + t1 * b[i]
    assert np.abs(y[i] - ((1 - t2) * first + t2 * c[i])).max() < 1e-6


def test_a_change_for_one_song_leaves_the_next_songs_filter_from_its_join():
    x = noise(RATE)
    one, two, mine = built("Jazz"), built("Classical"), built("Pop")
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, one, ramped=False)
    e.schedule(30_000, two)
    out = Out()
    for i in range(0, 40_000, 1000):
        out.add(e.push(x[i : i + 1000]))
    out.cut(12_000)
    e.retune(12_000, 12_000, mine, until=30_000)
    while e.redoing:
        out.add(e.redo(1000))
    out.add(e.push(x[40_000:]))
    out.add(e.flush())
    want = scheduled(x, (0, one, False), (12_000, mine, True), (30_000, two, True))
    assert np.array_equal(out.array(), want)


def test_a_change_for_a_song_not_reached_yet_is_filtered_again_from_its_first_frame():
    """The device at 5,000 and the next song from 20,000: what was given before its join stays,
    and from its join on is filtered again."""
    x = noise(RATE)
    one, two = built("Jazz"), built("Electronic")
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, one, ramped=False)
    e.schedule(20_000, one)
    out = Out()
    out.add(e.push(x[:30_000]))
    out.cut(20_000)
    e.retune(20_000, 20_000, two)
    while e.redoing:
        out.add(e.redo(1000))
    out.add(e.push(x[30_000:]))
    out.add(e.flush())
    assert np.array_equal(out.array(), scheduled(x, (0, one, False), (20_000, two, True)))


def test_taken_back_to_be_decoded_again_it_takes_up_as_if_it_had_run_through():
    """A seek, or a song to follow changed (A4.6): the frames given again from a place come out
    as they would have, the filter's memory of what came before kept, and the filters scheduled
    after it let go."""
    x = noise(RATE, seed=5)
    design = built("Vocal")
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, design, ramped=False)
    e.schedule(35_000, built("Rock"))
    out = Out()
    for i in range(0, 40_000, 1000):
        out.add(e.push(x[i : i + 1000]))
    out.cut(25_000)
    e.rewind(25_000)
    assert e.given == 25_000 and e.design is design
    for i in range(25_000, len(x), 1000):
        out.add(e.push(x[i : i + 1000]))
    out.add(e.flush())
    assert np.array_equal(out.array(), scheduled(x, (0, design, False)))


def test_a_filter_scheduled_that_is_the_one_in_use_changes_nothing():
    design = built("Rock")
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, design, ramped=False)
    e.schedule(500, design)
    assert len(e._steps) == 1
    e.schedule(600, None)
    e.schedule(600, design)  # in place of the one there
    assert len(e._steps) == 1


def test_filters_no_longer_heard_nor_reached_are_let_go():
    e = eq.Equalizer(RATE, 2, keep=2000)
    names = ["Rock", "Pop", "Jazz", "Rock", "Pop"]
    x = noise(20_000)
    for i, name in enumerate(names):
        e.schedule(i * 4000, built(name), ramped=i > 0)
        e.push(x[i * 4000 : (i + 1) * 4000])
    assert len(e._steps) < len(names)


# ---------- never clipping (R19.1) ----------


@pytest.mark.slow
@given(
    st.sampled_from(presets.BUILT_IN_NAMES),
    st.floats(0.5, 8.0),
    st.integers(0, 2**16),
)
@example("Loudness", 8.0, 0)
def test_nothing_comes_out_past_full_scale_whatever_goes_in(name, level, seed):
    """testing.md's property: the equalizer's output stays under full scale."""
    x = np.clip(noise(6000, level, seed), -level, level)
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, built(name), ramped=False)
    y = through(e, x, 1500)
    assert len(y) == len(x) and np.abs(y).max() <= eq.CEILING


def test_the_limiter_leaves_alone_what_is_under_full_scale():
    x = noise(20_000, 0.05)
    design = built("Rock")
    e = eq.Equalizer(RATE, 2)
    e.schedule(0, design, ramped=False)
    assert np.abs(through(e, x) - filtered(design, x)).max() < 1e-6


def test_the_limiters_gain_comes_down_before_a_peak_and_back_up_after_without_a_step():
    x = np.full((4000, 1), 0.5, np.float32)
    x[2000] = 2.0  # one sample twice past full scale, after the filter too (Flat)
    e = eq.Equalizer(RATE, 1)
    e.schedule(0, built("Flat"), ramped=False)
    y = through(e, x)[:, 0]
    gain = y / x[:, 0]
    assert y[2000] == pytest.approx(1.0) and np.abs(y).max() <= 1.0
    assert gain[2000 - LOOK] == pytest.approx(1.0, abs=1e-6)  # it starts LOOK frames before
    assert gain[2000 - LOOK // 2] < 1.0
    assert np.abs(np.diff(gain)).max() <= 0.5 / LOOK + 1e-6  # a ramp, never a step
    assert gain[2000 + LOOK + eq.frames_of(eq.HOLD, RATE)] == pytest.approx(1.0, abs=1e-6)


def test_the_level_held_down_follows_the_preamp_and_the_largest_boost():
    """testing.md: nothing clips, and the level held down matches the preamp and the boost."""
    tone = eq.Tone((eq.Band("bell", 1000, 9, 2),), -4.0)
    design = eq.design(tone, RATE)
    assert design.headroom == pytest.approx(5.0)
    peak = magnitude_db(design, [1000])[0]
    assert peak == pytest.approx(9 - 4 - 5, abs=0.01)


# ---------- the filters built ----------


def test_a_filter_is_built_once_for_its_tone_and_rate_and_the_last_few_kept():
    designs = eq.Designs(kept=2)
    rock, pop = (presets.tone(presets.find(n, ())) for n in ("Rock", "Pop"))
    a = designs(rock, 8000)
    assert designs(rock, 8000) is a and designs.built == 1
    assert designs(rock, 16_000) is not a and designs.built == 2
    designs(pop, 8000)
    assert designs(rock, 8000) is not a and designs.built == 4  # the oldest went
