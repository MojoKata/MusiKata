"""Reading tags as plain data (src/musikata_core/tags/parse.py; A3.2, R4.1): the shapes other
programs write each field in (docs/process/testing.md, "Shapes", `tags`), without opening a file.

Why: a tag reader written for the shape of its first example breaks on the second program's. Track
numbers, dates, genres and ratings each come in several forms, and each form here is one some
player or tagger writes."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core.tags import parse


@pytest.mark.parametrize(
    ("value", "pair"),
    [
        ("4", (4, None)), ("04", (4, None)), ("4/10", (4, 10)), (" 4 / 10 ", (4, 10)),
        ("4 of 10", (4, 10)), ("/10", (None, 10)), ("0", (None, None)), ("", (None, None)),
        (None, (None, None)), ("A4", (None, None)), ("4/x", (4, None)),
    ],
)  # fmt: skip
def test_a_track_number_is_read_as_4_04_4_of_10_or_4_slash_10(value, pair):
    assert parse.number_pair(value) == pair


@pytest.mark.parametrize(
    ("value", "year", "date"),
    [
        ("2003", 2003, None), ("2003-05-01", 2003, "2003-05-01"), ("2003-05", 2003, "2003-05"),
        ("2003-05-01T10:00:00", 2003, "2003-05-01"), ("20030501", 2003, "2003-05-01"),
        ("2003/05/01", 2003, "2003-05-01"), (" 2003 ", 2003, None), ("03", None, None),
        ("0000", None, None), ("unknown", None, None), (None, None, None),
    ],
)  # fmt: skip
def test_a_year_is_read_from_a_year_or_any_form_of_date(value, year, date):
    assert parse.year_and_date(value) == (year, date)


def test_an_id3v23_date_is_tyer_with_tdat_day_and_month():
    assert parse.id3v23_date("2003", "0105") == (2003, "2003-05-01")
    assert parse.id3v23_date("2003", None) == (2003, None)
    assert parse.id3v23_date("2003", "3213") == (2003, None)  # no 13th month


def test_genres_come_as_separate_values_or_joined_with_semicolons_and_slash_is_left_alone():
    assert parse.genres(["Electronic", "Ambient"]) == ("Electronic", "Ambient")
    assert parse.genres(["Electronic; Ambient"]) == ("Electronic", "Ambient")
    assert parse.genres(["Electronic;Ambient\x00Jazz"]) == ("Electronic", "Ambient", "Jazz")
    assert parse.genres(["R&B/Soul"]) == ("R&B/Soul",)
    assert parse.genres(["Rock", "rock", " ", ""]) == ("Rock",)


@pytest.mark.parametrize(
    ("popms", "stars"),
    [
        ([("Windows Media Player 9 Series", 196)], 4),
        ([("MusicBee", 255), ("Windows Media Player 9 Series", 64)], 2),  # WMP's wins (R10.4.1)
        ([("MusicBee", 196)], 4), ([("foobar2000", 128)], 3), ([("no@email", 1)], 1),
        ([("MusiKata", 204)], 4), ([("x", 0)], 0), ([], None),
    ],
)  # fmt: skip
def test_popm_from_windows_media_player_musicbee_and_foobar2000(popms, stars):
    assert parse.popm_rating(popms) == stars


def test_popm_ranges_are_the_common_players():
    assert [parse.popm_stars(v) for v in (1, 31, 32, 95, 96, 159, 160, 223, 224, 255)] == [
        1, 1, 2, 2, 3, 3, 4, 4, 5, 5,
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("rating", "fmps", "stars"),
    [
        ("4", None, 4), ("80", None, 4), ("100", None, 5), ("20", None, 1), (None, "0.8", 4),
        ("3", "1.0", 3), ("4,0", None, 4), ("x", "0.6", 3), ("-1", None, None), (None, None, None),
    ],
)  # fmt: skip
def test_vorbis_and_mp4_ratings_as_stars_hundredths_or_fmps(rating, fmps, stars):
    assert parse.vorbis_rating(rating, fmps) == stars


def test_replaygain_reads_db_and_peaks_in_their_written_forms():
    assert parse.replaygain("-6.20 dB") == -6.2
    assert parse.replaygain("+1.5 dB") == 1.5
    assert parse.replaygain("0.988547") == 0.988547
    assert parse.replaygain("1,25 dB") == 1.25
    assert parse.replaygain("n/a") is None


def test_vorbis_keys_in_any_case_repeated_and_their_older_names():
    raw = {
        "TITLE": ["", "Moonpull"], "ARTIST": ["lumen drift"], "ALBUM ARTIST": ["Lumen Drift"],
        "TRACKNUMBER": ["4/9"], "TOTALTRACKS": ["9"], "DATE": ["2022-03-04"],
        "GENRE": ["Electronic", "Ambient"], "DESCRIPTION": ["Remastered"], "RATING": ["80"],
        "COMPILATION": ["1"], "REPLAYGAIN_TRACK_GAIN": ["-7.10 dB"],
    }  # fmt: skip
    t = parse.from_vorbis(raw, has_cover=True)
    assert (t.title, t.artist, t.albumartist) == ("Moonpull", "lumen drift", "Lumen Drift")
    assert (t.track, t.tracktotal, t.year, t.date) == (4, 9, 2022, "2022-03-04")
    assert t.genres == ("Electronic", "Ambient") and t.comment == "Remastered"
    assert (t.rating, t.compilation, t.rg_track_gain, t.has_cover) == (4, True, -7.1, True)


def test_id3_frames_with_v23_dates_txxx_replaygain_and_comments():
    raw = {
        "TIT2": ["Signal Fires"], "TPE1": ["Lumen Drift", "Guest"], "TRCK": ["04"],
        "TPOS": ["1/2"], "TYER": ["2019"], "TDAT": ["0105"], "TCON": ["Electronic"],
        "TCMP": ["1"], "TSOP": ["Drift, Lumen"], "TXXX:replaygain_album_gain": ["-6.5 dB"],
        "TXXX:MusicBrainz Album Id": ["0f4d…"],  # Picard's: kept, not read
    }  # fmt: skip
    t = parse.from_id3(raw, [("Windows Media Player 9 Series", 255)],
                       [("iTunNORM", "0000"), ("", "Live take")])  # fmt: skip
    assert (t.title, t.artist, t.track, t.disc, t.disctotal) == (
        "Signal Fires",
        "Lumen Drift",
        4,
        1,
        2,
    )
    assert (t.year, t.date, t.compilation, t.artistsort) == (
        2019,
        "2019-05-01",
        True,
        "Drift, Lumen",
    )
    assert (t.rating, t.comment, t.rg_album_gain) == (5, "Live take", -6.5)


def test_mp4_atoms_with_freeform_rating_and_replaygain_in_any_case():
    raw = {
        "\xa9nam": ["Velvet Hours"], "\xa9day": ["2016"], "\xa9gen": ["Jazz"],
        "----:com.apple.iTunes:RATING": ["60"],
        "----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN": ["-3 dB"],
    }  # fmt: skip
    t = parse.from_mp4(raw, track=(1, 10), disc=(0, 0), compilation=True)
    assert (t.title, t.track, t.tracktotal, t.disc, t.year) == ("Velvet Hours", 1, 10, None, 2016)
    assert (t.genres, t.rating, t.rg_track_gain, t.compilation) == (("Jazz",), 3, -3.0, True)


def _riff(*chunks):
    body = b"".join(cid + len(data).to_bytes(4, "little") + data + b"\x00" * (len(data) & 1)
                    for cid, data in chunks)  # fmt: skip
    return b"RIFF" + (len(body) + 4).to_bytes(4, "little") + b"WAVE" + body


def _info(**items):
    sub = b""
    for k, v in items.items():
        n = len(v) + 1
        sub += k.encode() + n.to_bytes(4, "little") + v + b"\x00" + b"\x00" * (n & 1)
    return (b"LIST", b"INFO" + sub)


def test_a_wav_files_riff_info_chunk_is_read_where_id3_has_nothing():
    info_chunk = _info(
        INAM=b"Breakwater", IART=b"Hollow Coast", ICRD=b"2023-01-02", IGNR=b"Alternative",
        ITRK=b"3", ICMT="Caf\xe9".encode("latin-1"),
    )  # fmt: skip
    data = _riff((b"fmt ", b"\x00" * 16), info_chunk, (b"data", b"\x00" * 7))
    info = parse.riff_info(data)
    assert info["INAM"] == "Breakwater" and info["ICMT"] == "Café"
    t = parse.merge_info(parse.Tags(title="From ID3"), info)
    assert (t.title, t.artist, t.year, t.track, t.genres) == (
        "From ID3",
        "Hollow Coast",
        2023,
        3,
        ("Alternative",),
    )


def test_a_riff_chunk_cut_short_or_not_a_wave_reads_as_nothing():
    assert parse.riff_info(b"RIFF\x10\x00\x00\x00WAVELIST\xff\xff\x00\x00INFOIN") == {}
    assert parse.riff_info(b"OggS" + b"\x00" * 20) == {}


@given(st.text())
def test_any_text_is_read_without_an_error(value):
    parse.number_pair(value)
    parse.year_and_date(value)
    parse.genres([value])
    parse.vorbis_rating(value, value)
    parse.replaygain(value)
    parse.from_vorbis(
        {"TRACKNUMBER": [value], "DATE": [value], "GENRE": [value], "RATING": [value]}
    )


@given(st.binary(max_size=200))
def test_any_bytes_read_as_riff_info_without_an_error(data):
    parse.riff_info(b"RIFF" + data[:4] + b"WAVE" + data[4:])
