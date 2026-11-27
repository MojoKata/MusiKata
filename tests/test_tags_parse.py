"""Reading tags as plain data (src/musikata_core/tags/parse.py; A3.2, R4.1): the shapes other
programs write each field in (docs/process/testing.md, "Shapes", `tags`), without opening a file.

Why: a tag reader written for the shape of its first example breaks on the second program's. Track
numbers, dates, genres and ratings each come in several forms, and each form here is one some
player or tagger writes."""

import pytest
from hypothesis import example, given
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


def test_an_id3_tags_numbered_genres_are_names_wherever_they_stand_and_other_kinds_numbers_text():
    """R9.3: ID3's "(13)" and "13" are Pop, beside other genres too ("13; (8)", which Mutagen's
    own reading leaves as text); a Vorbis comment's "13" is the text it is."""
    assert parse.genres(["13; (8)", "Pop", " 52 "], numbered=True) == ("Pop", "Jazz", "Electronic")
    assert parse.genres(["(255)", "1999", "80s"], numbered=True) == ("(255)", "1999", "80s")
    assert parse.from_id3({"TCON": ["13; (8)"]}).genres == ("Pop", "Jazz")
    assert parse.from_vorbis({"GENRE": ["13"]}).genres == ("13",)


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
        ("INFINITY", None, None), ("nan", "0.6", 3), (None, "inf", None), ("1e999", None, None),
    ],
)  # fmt: skip
def test_vorbis_and_mp4_ratings_as_stars_hundredths_or_fmps(rating, fmps, stars):
    assert parse.vorbis_rating(rating, fmps) == stars


@pytest.mark.parametrize(
    ("rating", "fmps", "stars"),
    [
        ("5", None, 5), ("6", None, 0), ("0", "1.0", 0), ("2.5", None, 3),  # 5 or less: stars
        ("10", None, 1), ("30", None, 2), ("50", None, 3), ("70", None, 4), ("90", None, 5),
        ("150", None, 5), (None, "0.0", 0), (None, "0.5", 3), (None, "0.1", 1), (None, "2", 5),
        ("", "0.4", 2), (" 60 ", None, 3),
    ],
)  # fmt: skip
def test_ratings_edges_half_stars_round_up_and_rating_wins_over_fmps(rating, fmps, stars):
    """R10.4.2: RATING of 5 or less is stars and more hundredths (MusicBee's half stars 10 … 90
    round up), FMPS_RATING 0.0 to 1.0, RATING winning when both are there."""
    assert parse.vorbis_rating(rating, fmps) == stars


def test_mp4_reads_fmps_rating_where_it_has_no_rating():
    """R10.4.2 for MP4: the freeform FMPS_Rating Clementine and Strawberry write, in any case,
    read when there is no RATING, which wins when there is."""
    fmps = {"----:com.apple.iTunes:FMPS_Rating": ["0.6"]}
    assert parse.from_mp4(fmps).rating == 3
    both = {**fmps, "----:com.apple.itunes:rating": ["100"]}
    assert parse.from_mp4(both).rating == 5


def test_replaygain_reads_db_and_peaks_in_their_written_forms():
    assert parse.replaygain("-6.20 dB") == -6.2
    assert parse.replaygain("+1.5 dB") == 1.5
    assert parse.replaygain("0.988547") == 0.988547
    assert parse.replaygain("1,25 dB") == 1.25
    assert parse.replaygain("n/a") is None


def test_opus_r128_gains_are_whole_256ths_of_a_db_to_r128_moved_to_replaygains_level():
    assert parse.r128("-2560") == -10 + 5.0  # -10 dB to -23 LUFS is -5 dB to ReplayGain's
    assert parse.r128(" +512 ") == 7.0 and parse.r128("0") == 5.0
    assert [parse.r128(v) for v in ("-6.5", "1e3", "40000", "", None, "x")] == [None] * 6


def test_opus_r128_gains_win_over_its_replaygain_keys_and_carry_no_peak():
    raw = {"R128_TRACK_GAIN": ["-1280"], "R128_ALBUM_GAIN": ["-768"],
           "REPLAYGAIN_TRACK_GAIN": ["-3.00 dB"], "REPLAYGAIN_TRACK_PEAK": ["0.5"]}  # fmt: skip
    t = parse.from_vorbis(raw)
    assert (t.rg_track_gain, t.rg_album_gain) == (0.0, 2.0)
    assert (t.rg_track_peak, t.rg_album_peak) == (0.5, None)  # the peak of the REPLAYGAIN_ keys
    broken = parse.from_vorbis({"R128_TRACK_GAIN": ["loud"], "REPLAYGAIN_TRACK_GAIN": ["-3 dB"]})
    assert broken.rg_track_gain == -3.0


def test_id3_rva2_from_quod_libet_and_easyid3_when_there_is_no_txxx():
    rva2 = [("track", -4.5, 0.9), ("ALBUM", -5.25, 0.0), ("normalize", 2.0, 1.0)]
    t = parse.from_id3({}, rva2=rva2)
    assert (t.rg_track_gain, t.rg_track_peak, t.rg_album_gain, t.rg_album_peak) == (
        -4.5, 0.9, -5.25, None,
    )  # fmt: skip
    both = parse.from_id3({"TXXX:REPLAYGAIN_TRACK_GAIN": ["-2 dB"]}, rva2=rva2)
    assert (both.rg_track_gain, both.rg_track_peak, both.rg_album_gain) == (-2.0, None, -5.25)


def test_replaygain_from_ape_or_vorbis_keys_in_any_case():
    raw = {"replaygain_track_gain": ["+1.230000 dB"], "Replaygain_Album_Peak": ["1.042"],
           "MP3GAIN_MINMAX": ["089,201"]}  # fmt: skip
    assert parse.replaygain_of(raw) == {"rg_track_gain": 1.23, "rg_track_peak": None,
                                        "rg_album_gain": None, "rg_album_peak": 1.042}  # fmt: skip
    t = parse.with_replaygain(parse.from_id3({}), parse.replaygain_of(raw))
    assert (t.rg_track_gain, t.rg_album_gain, t.rg_album_peak) == (1.23, None, None)


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
@example("INFINITY")  # a rating no number of stars: found by Hypothesis
@example("nan")
def test_any_text_is_read_without_an_error(value):
    parse.number_pair(value)
    parse.year_and_date(value)
    parse.genres([value])
    parse.vorbis_rating(value, value)
    parse.replaygain(value)
    parse.r128(value)
    parse.from_vorbis(
        {
            "TRACKNUMBER": [value],
            "DATE": [value],
            "GENRE": [value],
            "RATING": [value],
            "R128_TRACK_GAIN": [value],
            "REPLAYGAIN_ALBUM_GAIN": [value],
        }  # fmt: skip
    )


@given(st.binary(max_size=200))
def test_any_bytes_read_as_riff_info_without_an_error(data):
    parse.riff_info(b"RIFF" + data[:4] + b"WAVE" + data[4:])


def test_the_comment_is_the_comm_without_a_description_or_id3v1s_never_another_programs():
    """iTunes keeps its own numbers in COMM frames (iTunNORM, iTunSMPB), MediaMonkey its custom
    fields (Songs-DB_Custom1): kept as they are (R4.1.1), and never shown as the comment, which
    a song without one would otherwise show, and couldn't have removed."""
    others = [("iTunNORM", " 00000A2B"), ("Songs-DB_Custom1", "vinyl rip")]
    assert parse.from_id3({}, comments=others).comment is None
    assert parse.from_id3({}, comments=[*others, (parse.V1_COMMENT, "from v1")]).comment == (
        "from v1"
    )
    assert parse.from_id3(
        {}, comments=[("", " "), (parse.V1_COMMENT, "v1"), ("", "v2")]
    ).comment == ("v1")


def test_the_tags_kept_without_showing_are_listed_by_name_and_r41s_never():
    """R4.1.1, R4.8: lyrics, MusicBrainz ids, encoder settings, private frames, … read only;
    what R4.1's fields are read from, the comment and ReplayGain aren't listed."""
    id3 = [
        ("TIT2", "Parallax"), ("TXXX:MusicBrainz Album Id", "0f4d"), ("USLT", "la la\n la"),
        ("USLT:eng", "words"), ("COMM", "a comment"), ("COMM:ID3v1 Comment", "v1"),
        ("COMM:iTunNORM", " 0000 0001"), ("TXXX:REPLAYGAIN_TRACK_GAIN", "-6 dB"),
        ("TXXX:replaygain_album_peak", "0.9"), ("PRIV:WM/MediaClassPrimaryID", "16 bytes"),
        ("UFID:http://musicbrainz.org", "4 bytes"), ("APIC:3", "front cover, 9 bytes"),
        ("APIC:4", "back cover, 12 bytes"), ("TSSE", "LAME 3.100"), ("TDRC", "2019"),
        ("POPM", "x"), ("XXXX", "?"), ("TXXX", "no description"),
    ]  # fmt: skip
    assert parse.kept("id3", id3) == [
        ("MusicBrainz Album Id", "0f4d"), ("Lyrics", "la la la"), ("Lyrics (eng)", "words"),
        ("Comment (iTunNORM)", "0000 0001"), ("Private data (WM/MediaClassPrimaryID)", "16 bytes"),
        ("File id (http://musicbrainz.org)", "4 bytes"), ("Picture", "back cover, 12 bytes"),
        ("Encoder settings", "LAME 3.100"), ("XXXX", "?"), ("TXXX", "no description"),
    ]  # fmt: skip
    vorbis = [
        ("TITLE", "x"), ("ALBUM ARTIST", "x"), ("LYRICS", "words"), ("R128_TRACK_GAIN", "1"),
        ("MUSICBRAINZ_TRACKID", "9a"), ("REPLAYGAIN_TRACK_GAIN", "1 dB"), ("ENCODER", "x"),
    ]  # fmt: skip
    assert parse.kept("vorbis", vorbis) == [
        ("Lyrics", "words"), ("MUSICBRAINZ_TRACKID", "9a"), ("Encoder", "x"),
    ]  # fmt: skip
    mp4 = [("\xa9nam", "x"), ("----:com.apple.iTunes:MusicBrainz Track Id", "9a"),
           ("----:com.apple.iTunes:RATING", "100"), ("----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN",
           "1"), ("\xa9lyr", "words"), ("tmpo", "120"), ("covr", "...")]  # fmt: skip
    assert parse.kept("mp4", mp4) == [
        ("MusicBrainz Track Id", "9a"), ("Lyrics", "words"), ("BPM", "120"),
    ]  # fmt: skip


def test_a_kept_value_too_long_is_cut_short_with_an_ellipsis():
    ((name, value),) = parse.kept("vorbis", [("LYRICS", "word " * 40)])
    assert len(value) == parse.KEPT_WIDTH and value.endswith("…")
