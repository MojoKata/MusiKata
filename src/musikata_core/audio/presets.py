"""The equalizer's presets (R19.1, R19.3.1, R19.4, R19.6, R19.7) as plain data and functions: the
built-in ones, a preset's kind changed either way, Equalizer APO's text read and written, and the
preset a song takes by its genre. No Qt, file or device (docs/process/coding.md); what is heard is
eq.py's, and what is kept the shared settings' (settings.py, R19.5).

- **A preset** (`Preset`) is parametric, 1 to 10 bands of any type, or graphic, ten sliders: ten
  one-octave bells at GRAPHIC_FREQS, so it plays as the same parametric preset would (`tone`).
- **Parametric to graphic** (R19.6, A4.4) is the least-squares fit of the ten bells to the curve,
  in dB, every twelfth of an octave from 20 Hz to 20 kHz, each slider held to ±12 dB; how close
  it comes is the largest difference between the curves there (`to_graphic`). The bands it was
  fitted from are kept (`from_bands`, A2.10) until a slider changes (`with_gains`), so switching
  back gives them exactly; else the ten sliders become ten bells (`to_parametric`).
- **Equalizer APO's text** (R19.7): `read_apo` reads peak, shelf, low-pass and high-pass filters
  in the shapes it and the AutoEq project write them (testing.md, "Shapes"), listing every other
  line, and every band past the tenth, as skipped; `write_apo` writes a preset back, a graphic one
  as its ten bells.
- **By genre** (R19.4): a song takes the preset of its first genre the table matches, else the
  preset chosen; one chosen by hand for the song playing plays for it alone (`pick`)."""

from __future__ import annotations

import codecs
import math
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from .eq import CUTS, FREQS, GAINS, QS, TYPES, Band, Tone, curve_db, headroom, response_db

KINDS = ("parametric", "graphic")  # R19.6, as A2.10 names them
GRAPHIC_FREQS = (31.0, 62.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0)
GRAPHIC_Q = math.sqrt(2)  # a bell one octave wide
SHELF_Q = 0.7  # R19.3.1's shelves
MAX_BANDS = 10  # R19.1
CURVE_RATE = 48_000  # the rate curves are drawn and fitted at, and the headroom shown at
FIT_STEPS = 12  # the fit's points to the octave (A4.4)
FIT_ROUNDS = 8  # Gauss-Newton steps of the fit: the bells' dB aren't quite linear in their gains
FLAT = "Flat"


@dataclass(frozen=True)
class Preset:
    """A preset (R19.1): its name, kind (one of KINDS) and preamp in dB; a parametric one's bands,
    a graphic one's ten slider gains, and the bands a graphic one was fitted from while no slider
    has changed (`from_bands`, R19.6)."""

    name: str
    kind: str
    preamp: float
    bands: tuple[Band, ...] = ()
    gains: tuple[float, ...] = ()
    from_bands: tuple[Band, ...] | None = None


def _bell(freq: float, gain: float, q: float) -> Band:
    return Band("bell", freq, gain, q)


def _ls(freq: float, gain: float) -> Band:
    return Band("low-shelf", freq, gain, SHELF_Q)


def _hs(freq: float, gain: float) -> Band:
    return Band("high-shelf", freq, gain, SHELF_Q)


def _parametric(name: str, preamp: float, *bands: Band) -> Preset:
    return Preset(name, "parametric", preamp, bands)


# R19.3.1's table, row for row
BUILT_IN = (
    _parametric(FLAT, 0.0, _ls(100, 0), _bell(400, 0, 1.0), _bell(1500, 0, 1.0),
                _bell(5000, 0, 1.0), _hs(10_000, 0)),
    _parametric("Bass boost", -6.0, _ls(100, 6)),
    _parametric("Treble boost", -6.0, _hs(6000, 6)),
    _parametric("Vocal", -3.5, _ls(100, -2), _bell(300, -1.5, 1.0), _bell(2500, 3, 1.0),
                _bell(5000, 2, 1.4), _hs(12_000, -1)),
    _parametric("Rock", -4.5, _ls(80, 4), _bell(400, -2, 1.0), _bell(2500, 2, 1.2),
                _hs(8000, 3.5)),
    _parametric("Pop", -3.0, _ls(80, 1.5), _bell(250, -1, 1.0), _bell(1500, 2, 0.8),
                _bell(4000, 1.5, 1.0), _hs(10_000, 1)),
    _parametric("Jazz", -3.5, _ls(100, 3), _bell(500, -1.5, 1.0), _bell(2000, 1, 1.0),
                _hs(8000, 3)),
    _parametric("Classical", -3.0, _ls(100, 2), _bell(1000, -1, 0.7), _hs(8000, 3)),
    _parametric("Electronic", -5.0, _ls(80, 5), _bell(250, -1.5, 1.0), _bell(1200, -1, 1.4),
                _bell(4000, 2.5, 1.2), _hs(9000, 3.5)),
    _parametric("Loudness", -6.0, _ls(60, 6), _hs(10_000, 4)),
)  # fmt: skip
BUILT_IN_NAMES = tuple(p.name for p in BUILT_IN)
# R19.4: the built-in genres (genres.BUILT_IN) matched to the built-in presets of the same name
GENRES = {"Classical": "Classical", "Electronic": "Electronic", "Jazz": "Jazz", "Pop": "Pop",
          "Rock": "Rock"}  # fmt: skip


def new_parametric(name: str) -> Preset:
    """A new parametric preset (R19.1): Flat's five bands, all at 0 dB."""
    return replace(BUILT_IN[0], name=name)


def graphic_bands(gains: Sequence[float]) -> tuple[Band, ...]:
    """Ten sliders as the ten one-octave bells they are (R19.1)."""
    return tuple(_bell(f, float(g), GRAPHIC_Q) for f, g in zip(GRAPHIC_FREQS, gains, strict=True))


def bands_of(preset: Preset) -> tuple[Band, ...]:
    """The bands a preset plays: a parametric one's own, a graphic one's ten bells."""
    return preset.bands if preset.kind == "parametric" else graphic_bands(preset.gains)


def tone(preset: Preset) -> Tone:
    """What the equalizer plays for `preset`: its bands and preamp."""
    return Tone(bands_of(preset), preset.preamp)


def headroom_of(preset: Preset, rate: int = CURVE_RATE) -> float:
    """How far `preset` holds the level down to keep from clipping (R19.1), in dB: what the panel
    shows under the preamp ("−2.7 dB more, to keep from clipping")."""
    return headroom(tone(preset), rate)


def find(name: str, custom: Sequence[Preset]) -> Preset | None:
    """The preset named `name`: a built-in one, else a custom one; None when there is none."""
    for preset in (*BUILT_IN, *custom):
        if preset.name == name:
            return preset
    return None


# ---------- changing a preset's kind (R19.6) ----------


def fit_points() -> np.ndarray:
    """Where the fit compares the curves: every twelfth of an octave from 20 Hz to 20 kHz."""
    steps = math.floor(FIT_STEPS * math.log2(FREQS[1] / FREQS[0]))
    return np.asarray(FREQS[0] * 2 ** (np.arange(steps + 1) / FIT_STEPS))


def _graphic_db(gains: np.ndarray, points: np.ndarray) -> np.ndarray:
    return curve_db(graphic_bands(gains.tolist()), points, CURVE_RATE)


def _slopes(gains: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Each slider's bell's dB per dB of its gain, at `gains`, at each point (points × sliders):
    the Jacobian of the Gauss-Newton step."""
    delta = 1e-4
    return np.stack([
        (response_db(_bell(f, g + delta, GRAPHIC_Q), points, CURVE_RATE)
         - response_db(_bell(f, g, GRAPHIC_Q), points, CURVE_RATE)) / delta
        for f, g in zip(GRAPHIC_FREQS, gains.tolist(), strict=True)
    ], axis=1)  # fmt: skip


def _fit_step(unit: np.ndarray, rest: np.ndarray, gains: np.ndarray) -> np.ndarray:
    """The least-squares step of the sliders towards `rest` (the dB still to go, at each point),
    `unit` each slider's dB per dB: a slider the step would take past ±12 dB is held at that limit,
    and the step taken again for the others."""
    low, high = GAINS
    step = np.zeros(len(gains))
    free = np.ones(len(gains), bool)
    while free.any():
        pinned = unit[:, ~free] @ step[~free]
        step[free] = np.linalg.lstsq(unit[:, free], rest - pinned, rcond=None)[0]
        moved = gains + step
        out = free & ((moved < low) | (moved > high))
        if not out.any():
            break
        step[out] = np.clip(moved[out], low, high) - gains[out]
        free &= ~out
    return step


def fit(bands: Sequence[Band]) -> tuple[tuple[float, ...], float]:
    """The ten slider gains that come closest to `bands`' curve (A4.4): least squares in dB at
    `fit_points`, each held to ±12 dB, by Gauss-Newton steps (a bell's dB grow a little less than
    in step with its gain) with the sliders at a limit held there; and how close they come, the
    largest difference between the curves in dB."""
    points = fit_points()
    target = curve_db(bands, points, CURVE_RATE)
    low, high = GAINS
    gains = np.zeros(len(GRAPHIC_FREQS))
    for _ in range(FIT_ROUNDS):
        slope = _slopes(gains, points)
        step = _fit_step(slope, target - _graphic_db(gains, points), gains)
        gains = np.clip(gains + step, low, high)
    closest = float(np.abs(target - _graphic_db(gains, points)).max())
    return tuple(float(g) for g in gains), closest


def to_graphic(preset: Preset, name: str | None = None) -> tuple[Preset, float]:
    """`preset` as a graphic one, and how close its curve comes to the old one, in dB (R19.6):
    a parametric one's sliders fitted to its curve (`fit`), its bands kept as `from_bands`; a
    graphic one as it is. Named `name` when given (a built-in's custom copy)."""
    named = preset.name if name is None else name
    if preset.kind == "graphic":
        return replace(preset, name=named), 0.0
    gains, closest = fit(preset.bands)
    return Preset(named, "graphic", preset.preamp, gains=gains, from_bands=preset.bands), closest


def to_parametric(preset: Preset, name: str | None = None) -> Preset:
    """`preset` as a parametric one (R19.6): a graphic one fitted from bands no slider has
    changed since gives them back exactly; else its ten sliders become ten bells, which lose
    nothing. Named `name` when given."""
    named = preset.name if name is None else name
    if preset.kind == "parametric":
        return replace(preset, name=named)
    bands = preset.from_bands if preset.from_bands is not None else graphic_bands(preset.gains)
    return Preset(named, "parametric", preset.preamp, bands)


def with_gains(preset: Preset, gains: Sequence[float]) -> Preset:
    """A graphic preset with its sliders at `gains`: the bands it was fitted from are let go once
    a slider changes (A2.10)."""
    gains = tuple(float(g) for g in gains)
    if gains == preset.gains:
        return preset
    return replace(preset, gains=gains, from_bands=None)


# ---------- by genre (R19.4) ----------


@dataclass(frozen=True)
class Pick:
    """The preset a song plays, by name, and why: "chosen" in the panel, by its "genre" (named),
    or chosen by hand for this "song" while Choose by genre is on."""

    preset: str
    why: str
    genre: str = ""


def pick(
    genres: Sequence[str],
    table: Mapping[str, str],
    chosen: str,
    known: Collection[str],
    by_genre: bool,
    for_song: str | None = None,
    key: Callable[[str], str] = str.casefold,
) -> Pick:
    """Which preset a song of `genres` (in its order, R9.2) plays (R19.4): with Choose by genre
    on (`by_genre`), the one chosen by hand for it (`for_song`), else the preset of its first
    genre the `table` matches (genre names compared by `key`) and that is still there (`known`),
    else the preset `chosen`; with it off, the one chosen. A preset chosen that isn't there is
    Flat."""
    if by_genre:
        if for_song is not None and for_song in known:
            return Pick(for_song, "song")
        matched = {key(g): (g, p) for g, p in table.items()}
        for genre in genres:
            found = matched.get(key(genre))
            if found is not None and found[1] in known:
                return Pick(found[1], "genre", genre)
    return Pick(chosen if chosen in known else FLAT, "chosen")


# ---------- Equalizer APO's text (R19.7) ----------


class PresetFileError(ValueError):
    """A file that holds no filter MusiKata can read."""


@dataclass(frozen=True)
class Imported:
    """A preset read from Equalizer APO's text: the preset, the lines it passed by (`skipped`),
    and those whose values were brought into R19.1's ranges (`changed`)."""

    preset: Preset
    skipped: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()


_NUMBER = r"([-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][-+]?\d+)?)"
_PREAMP = re.compile(rf"^preamp\s*:\s*{_NUMBER}\s*(?:db)?\s*$", re.I)
_FILTER = re.compile(r"^filter\s*\d*\s*:\s*(on|off)\s+(.*)$", re.I)
_TYPE = re.compile(r"^([a-z]+)(?:\s+(\d+(?:[.,]\d+)?)\s*db)?\b\s*(.*)$", re.I)
_FC = re.compile(rf"\bfc\s*{_NUMBER}\s*(?:hz)?", re.I)
_GAIN = re.compile(rf"\bgain\s*{_NUMBER}\s*(?:db)?", re.I)
_Q = re.compile(rf"\bq\s*{_NUMBER}", re.I)
_BW = re.compile(rf"\bbw\s*(?:oct\s*)?{_NUMBER}", re.I)
# Equalizer APO's filter types MusiKata reads (R19.7): peak, low and high shelves (by their centre
# or their corner, with or without a Q or a slope), low and high pass (with or without a Q)
APO_TYPES = {"PK": "bell", "PEQ": "bell", "LSC": "low-shelf", "LS": "low-shelf",
             "HSC": "high-shelf", "HS": "high-shelf", "LP": "high-cut", "LPQ": "high-cut",
             "HP": "low-cut", "HPQ": "low-cut"}  # fmt: skip
APO_Q = 1 / math.sqrt(2)  # a filter's Q when the line gives none: Equalizer APO's own


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def _clamped(value: float, limits: tuple[float, float]) -> float:
    return min(max(value, limits[0]), limits[1])


def _slope_q(gain: float, slope: float) -> float:
    """A shelf's Q for a slope in dB per octave (the Cookbook's S, 1 at 12 dB per octave)."""
    a = 10 ** (gain / 40)
    s = max(slope / 12, 1e-3)
    inner = (a + 1 / a) * (1 / s - 1) + 2
    return 1 / math.sqrt(inner) if inner > 0 else QS[1]


def _band(line: str) -> tuple[Band | None, bool]:
    """A filter line's band, and whether a value was brought into R19.1's ranges; None when it is
    off, of a type MusiKata doesn't read, or has no frequency."""
    m = _FILTER.match(line)
    if m is None or m.group(1).lower() == "off":
        return None, False
    t = _TYPE.match(m.group(2))
    if t is None:
        return None, False
    kind = APO_TYPES.get(t.group(1).upper())
    rest = t.group(3)
    fc = _FC.search(rest)
    if kind is None or fc is None:
        return None, False
    freq, gain_m, q_m, bw_m = _number(fc.group(1)), _GAIN.search(rest), _Q.search(rest), None
    if q_m is None:
        bw_m = _BW.search(rest)
    gain = _number(gain_m.group(1)) if gain_m is not None and kind not in CUTS else 0.0
    if q_m is not None:
        q = _number(q_m.group(1))
    elif bw_m is not None:  # a bandwidth in octaves
        n = _number(bw_m.group(1))
        q = math.sqrt(2**n) / (2**n - 1) if n > 0 else QS[1]
    elif t.group(2) is not None and kind in ("low-shelf", "high-shelf"):
        q = _slope_q(gain, _number(t.group(2)))
    else:
        q = APO_Q
    values = (freq, gain, q)
    if not all(math.isfinite(v) for v in values):
        return None, False
    band = Band(kind, _clamped(freq, FREQS), _clamped(gain, GAINS), _clamped(q, QS))
    return band, (band.freq, band.gain, band.q) != values


def read_apo(text: str, name: str) -> Imported:
    """A custom parametric preset named `name` from Equalizer APO's `text` (R19.7): its `Preamp:`
    lines added up and its first ten filters MusiKata reads, each value brought into R19.1's
    ranges; every other line that isn't blank or a comment, and every filter past the tenth,
    listed as skipped. PresetFileError when it holds no filter MusiKata reads."""
    bands: list[Band] = []
    skipped: list[str] = []
    changed: list[str] = []
    preamp = 0.0
    preamp_changed = False
    for raw in text.removeprefix("﻿").splitlines():
        line = " ".join(raw.split())
        if not line or line.startswith("#"):
            continue
        p = _PREAMP.match(line)
        if p is not None:
            value = _number(p.group(1))
            if math.isfinite(value):
                preamp += value
                continue
        band, moved = _band(line) if p is None else (None, False)
        if band is None or len(bands) >= MAX_BANDS:
            skipped.append(line)
            continue
        bands.append(band)
        if moved:
            changed.append(line)
    if not bands:
        raise PresetFileError("it holds no peak, shelf, low-pass or high-pass filter")
    if _clamped(preamp, GAINS) != preamp:
        preamp, preamp_changed = _clamped(preamp, GAINS), True
    if preamp_changed:
        changed.insert(0, f"Preamp: {_apo_number(preamp)} dB")
    return Imported(
        Preset(name, "parametric", preamp, tuple(bands)), tuple(skipped), tuple(changed)
    )


def decode_apo(data: bytes) -> str:
    """An Equalizer APO file's bytes as text: UTF-8 (with or without its BOM), UTF-16 with its
    BOM, else Windows' Western encoding, which every byte reads in."""
    for bom, encoding in ((codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            return data.decode(encoding, errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _apo_number(value: float) -> str:
    return np.format_float_positional(value, trim="-")


APO_NAMES = {"bell": "PK", "low-shelf": "LSC", "high-shelf": "HSC", "low-cut": "HPQ",
             "high-cut": "LPQ"}  # fmt: skip


def write_apo(preset: Preset) -> str:
    """`preset` in Equalizer APO's text (R19.7): its preamp and a filter line per band, a graphic
    one's ten sliders as its ten bells, each number written so it reads back the same."""
    lines = [f"Preamp: {_apo_number(preset.preamp)} dB"]
    for i, band in enumerate(bands_of(preset), 1):
        gain = "" if band.type in CUTS else f" Gain {_apo_number(band.gain)} dB"
        lines.append(
            f"Filter {i}: ON {APO_NAMES[band.type]} Fc {_apo_number(band.freq)} Hz{gain}"
            f" Q {_apo_number(band.q)}"
        )
    return "\n".join(lines) + "\n"


# ---------- as the shared settings keep them (R19.5, A2.10) ----------


def _value(value: object) -> float | None:
    """A number, or one written as text, with a decimal comma or "dB"; None when it isn't one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().removesuffix("dB").strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _in_range(
    value: object, limits: tuple[float, float], what: str, problems: list[str]
) -> float | None:
    number = _value(value)
    if number is None:
        problems.append(f"{what} isn't a number: {value!r}")
        return None
    if not limits[0] <= number <= limits[1]:
        problems.append(f"{what} is out of {limits[0]:g} to {limits[1]:g}: {value!r}; brought in")
        number = _clamped(number, limits)
    return number


def band_of(value: object, where: str, problems: list[str]) -> Band | None:
    """A band as the shared settings keep it ({"type", "freq", "gain", "q"}, A2.10): its type in
    any case, numbers as text read, values out of R19.1's ranges brought into them; None, named in
    `problems`, when it isn't a band."""
    if not isinstance(value, dict):
        problems.append(f"{where} isn't a band: {value!r}")
        return None
    kind = value.get("type")
    kind = (
        kind.strip().lower().replace("_", "-").replace(" ", "-") if isinstance(kind, str) else kind
    )
    if kind not in TYPES:
        problems.append(f"{where}.type isn't one of {', '.join(TYPES)}: {value.get('type')!r}")
        return None
    freq = _in_range(value.get("freq"), FREQS, f"{where}.freq", problems)
    q = _in_range(value.get("q", SHELF_Q), QS, f"{where}.q", problems)
    gain = 0.0
    if kind not in CUTS:
        gain = _in_range(value.get("gain", 0.0), GAINS, f"{where}.gain", problems) or 0.0
    if freq is None or q is None:
        return None
    return Band(str(kind), freq, gain, q)


def _bands_of(value: object, where: str, problems: list[str]) -> tuple[Band, ...] | None:
    if not isinstance(value, list):
        problems.append(f"{where} isn't a list of bands: {value!r}")
        return None
    bands = [band_of(b, f"{where}[{i}]", problems) for i, b in enumerate(value)]
    kept = tuple(b for b in bands if b is not None)
    if not kept:
        problems.append(f"{where} holds no band")
        return None
    if len(kept) > MAX_BANDS:
        problems.append(f"{where} has more than {MAX_BANDS} bands: the first {MAX_BANDS} kept")
    return kept[:MAX_BANDS]


def preset_of(value: object, where: str, problems: list[str]) -> Preset | None:
    """A custom preset as the shared settings keep it (A2.10): its name, kind in any case and
    preamp, and a parametric one's bands or a graphic one's ten gains, with the bands it was
    fitted from; what can't be used named in `problems`, the preset None when it can't be one."""
    if not isinstance(value, dict):
        problems.append(f"{where} isn't a preset: {value!r}")
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append(f"{where}.name isn't a name: {name!r}")
        return None
    name = name.strip()
    here = f"{where} ({name})"
    kind = value.get("kind")
    kind = kind.strip().lower() if isinstance(kind, str) else kind
    if kind not in KINDS:
        problems.append(f"{here}.kind isn't parametric or graphic: {value.get('kind')!r}")
        return None
    preamp = _in_range(value.get("preamp", 0.0), GAINS, f"{here}.preamp", problems)
    preamp = 0.0 if preamp is None else preamp
    if kind == "parametric":
        bands = _bands_of(value.get("bands"), f"{here}.bands", problems)
        return None if bands is None else Preset(name, "parametric", preamp, bands)
    gains = value.get("gains")
    if not isinstance(gains, list) or len(gains) != len(GRAPHIC_FREQS):
        problems.append(f"{here}.gains isn't ten gains: {gains!r}")
        return None
    read = [_in_range(g, GAINS, f"{here}.gains[{i}]", problems) for i, g in enumerate(gains)]
    numbers = [g for g in read if g is not None]
    if len(numbers) != len(read):
        return None
    from_bands = None
    if "from_bands" in value:
        from_bands = _bands_of(value["from_bands"], f"{here}.from_bands", problems)
    return Preset(name, "graphic", preamp, gains=tuple(numbers),
                  from_bands=from_bands)  # fmt: skip


def band_data(band: Band) -> dict[str, object]:
    """A band as the shared settings keep it (A2.10): a cut without its gain."""
    data: dict[str, object] = {"type": band.type, "freq": band.freq}
    if band.type not in CUTS:
        data["gain"] = band.gain
    data["q"] = band.q
    return data


def preset_data(preset: Preset, old: Mapping[str, object] | None = None) -> dict[str, object]:
    """A custom preset as the shared settings keep it (A2.10), the fields it doesn't know of
    `old` (the same preset as the file had it) kept."""
    data: dict[str, object] = {k: v for k, v in (old or {}).items()
                               if k not in ("name", "kind", "preamp", "bands", "gains",
                                            "from_bands")}  # fmt: skip
    data.update(name=preset.name, kind=preset.kind, preamp=preset.preamp)
    if preset.kind == "parametric":
        data["bands"] = [band_data(b) for b in preset.bands]
    else:
        data["gains"] = list(preset.gains)
        if preset.from_bands is not None:
            data["from_bands"] = [band_data(b) for b in preset.from_bands]
    return data


# ---------- what plays now (R19.1, R19.4) ----------


@dataclass
class Choice:
    """What the equalizer plays, as the user has it: on or off, the preset chosen, Choose by
    genre and its table, the custom presets; a preset's bands as set and not yet saved (`edit`,
    R19.3: heard at once, wherever that preset plays); and a preset chosen by hand for the song
    playing while Choose by genre is on (`for_song`: the song's ticket and the preset, R19.4).
    The GUI thread's own; `tone` is what the engine is told for each song."""

    on: bool = False
    chosen: str = FLAT
    by_genre: bool = False
    custom: tuple[Preset, ...] = ()
    table: Mapping[str, str] = field(default_factory=lambda: dict(GENRES))
    edit: Preset | None = None
    for_song: tuple[int, str] | None = None
    key: Callable[[str], str] = str.casefold

    def names(self) -> tuple[str, ...]:
        """Every preset's name, the built-in ones first."""
        return (*BUILT_IN_NAMES, *(p.name for p in self.custom))

    def preset(self, name: str) -> Preset:
        """The preset named `name` as it plays: with its bands as set when they are being edited;
        Flat when there is none of that name."""
        if self.edit is not None and self.edit.name == name:
            return self.edit
        return find(name, self.custom) or BUILT_IN[0]

    def pick(self, genres: Sequence[str], ticket: int) -> Pick:
        """The preset the song asked for with `ticket`, of `genres`, plays (`pick`, R19.4)."""
        for_song = self.for_song[1] if self.for_song and self.for_song[0] == ticket else None
        return pick(genres, self.table, self.chosen, self.names(), self.by_genre, for_song,
                    self.key)  # fmt: skip

    def tone(self, genres: Sequence[str], ticket: int) -> Tone | None:
        """What the equalizer plays for that song: its preset's tone, None while it is off."""
        return tone(self.preset(self.pick(genres, ticket).preset)) if self.on else None

    def choose(self, name: str, ticket: int) -> bool:
        """`name` chosen by hand, the song asked for with `ticket` playing (0: none): it is the
        preset chosen from now on, and, while Choose by genre is on, the one this song plays
        (R19.4); its bands as saved. False when there is no preset of that name."""
        if name not in self.names():
            return False
        self.chosen, self.edit = name, None
        self.for_song = (ticket, name) if self.by_genre and ticket else None
        return True

    def set_bands(self, name: str, preamp: float, bands: Sequence[Band] | None,
                  gains: Sequence[float] | None = None) -> Preset:  # fmt: skip
        """The preset `name` with its preamp and its bands (parametric) or its ten sliders
        (graphic, the bands it was fitted from let go once a slider changes) as set, heard at
        once and not yet saved (R19.3); values brought into R19.1's ranges."""
        base = self.preset(name)
        preamp = _clamped(preamp, GAINS)
        if gains is not None:
            graphic = base if base.kind == "graphic" else to_graphic(base)[0]
            edited = with_gains(replace(graphic, preamp=preamp),
                                [_clamped(g, GAINS) for g in gains])  # fmt: skip
        else:
            kept = tuple(
                Band(b.type, _clamped(b.freq, FREQS), _clamped(b.gain, GAINS), _clamped(b.q, QS))
                for b in (bands or base.bands)[:MAX_BANDS]
            )
            edited = Preset(name, "parametric", preamp, kept)
        self.edit = edited
        return edited
