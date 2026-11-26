"""Writing tags as plain data (src/musikata_core/tags/compose.py; A3.2, R4.1): a save's changes as
each kind's frames, comments and atoms, through the tables the reading side reads with.

Why: what is written must read back as written (a field set empty gone, not left showing an older
key's value), and nothing a change doesn't name may move; each kind's own forms (TRCK "4/10",
TRACKTOTAL, trkn's pair) are where such slips hide, and here they are checked without a file."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core.tags import Picture, Tags, compose, parse

BEFORE = Tags(
    title="Signal Fires", artist="Lumen Drift", album="Glass Harbor", albumartist="Lumen Drift",
    track=4, tracktotal=10, disc=1, disctotal=2, year=2019, date="2019-05-01",
    genres=("Electronic",), comment="Remastered", rating=3,
)  # fmt: skip


def change(**fields):
    return compose.effective(compose.normalize(fields), BEFORE)


def test_changes_are_normalized_as_the_reading_side_reads_them():
    got = compose.normalize(
        {
            "title": "  Undertow \x00",
            "album": "",
            "track": 0,
            "disc": 2,
            "year": "2003-05-01",
            "genres": ["Jazz; Soul", "jazz", " Funk "],
            "rating": None,
            "compilation": True,
            "cover": Picture(3, "image/png", b""),
        }  # fmt: skip
    )
    assert got == {
        "title": "Undertow", "album": None, "track": None, "disc": 2,
        "year": (2003, "2003-05-01"), "genres": ("Jazz", "Soul", "Funk"), "rating": 0,
        "compilation": True, "cover": None,
    }  # fmt: skip
    assert compose.normalize({"year": 1999, "comment": None}) == {
        "year": (1999, None),
        "comment": None,
    }
    assert compose.normalize({"year": None})["year"] == (None, None)


@pytest.mark.parametrize(
    "fields",
    [
        {"bpm": 120},  # not a field MusiKata writes
        {"title": 4},
        {"track": -1},
        {"track": True},
        {"track": "4"},
        {"year": "soon"},
        {"year": 99999},
        {"year": -5},
        {"year": 2.5},
        {"genres": "Rock"},
        {"genres": [1]},
        {"compilation": "yes"},
        {"rating": 6},
        {"cover": b"jpeg"},
    ],
)
def test_a_change_that_isnt_a_field_or_of_the_wrong_kind_is_the_callers_mistake(fields):
    with pytest.raises(ValueError):
        compose.normalize(fields)


def test_only_what_differs_from_the_file_is_written_and_a_full_date_with_its_year_kept():
    assert change(title="Signal Fires", track=4, genres=["Electronic"], rating=3) == {}
    assert change(year=2019) == {}  # R4.1: the full date is kept
    assert change(year=2020) == {"year": (2020, None)}
    assert change(year="2019-05-02") == {"year": (2019, "2019-05-02")}
    assert compose.effective({"rating": 0}, Tags()) == {}  # none and cleared are one
    cover = Picture(3, "image/jpeg", b"\xff\xd8")
    assert change(cover=cover) == {"cover": cover}  # Tags doesn't hold its bytes


def test_what_should_read_back_is_the_file_with_the_change():
    want = compose.expected(BEFORE, change(title="Undertow", year=2020, rating=0, comment="Hi"))
    assert (want.title, want.year, want.date, want.rating, want.comment) == (
        "Undertow", 2020, None, None, "Hi",
    )  # fmt: skip
    assert (want.album, want.track, want.genres) == ("Glass Harbor", 4, ("Electronic",))


def test_differences_name_the_fields_that_read_back_otherwise():
    want = compose.expected(BEFORE, change(title="Undertow", rating=0))
    assert compose.differences(want, want) == []
    got = Tags(**{**want.__dict__, "title": "Signal Fires", "rating": 0, "has_cover": True})
    assert compose.differences(want, got) == ["title", "has_cover"]
    assert compose.differences(want, got, cover=True) == ["title"]


def test_vorbis_comments_for_each_field_and_the_older_keys_that_could_read_in_their_place():
    edit = compose.vorbis(
        change(title="Undertow", albumartist="", comment=None, tracktotal=12, year="2020-03-04",
               genres=["Jazz", "Funk"], compilation=True, rating=4),
        BEFORE,
    )  # fmt: skip
    assert edit == {
        "TITLE": ["Undertow"], "ALBUMARTIST": [], "ALBUM ARTIST": [], "COMMENT": [],
        "DESCRIPTION": [], "TRACKNUMBER": ["4"], "TRACKTOTAL": ["12"], "TOTALTRACKS": [],
        "DATE": ["2020-03-04"], "YEAR": [], "GENRE": ["Jazz", "Funk"], "COMPILATION": ["1"],
        "RATING": ["80"], "FMPS_RATING": ["0.8"],
    }  # fmt: skip
    cleared = compose.vorbis(change(disc=None, disctotal=None, rating=0), BEFORE)
    assert cleared == {"DISCNUMBER": [], "DISCTOTAL": [], "TOTALDISCS": [], "RATING": [],
                       "FMPS_RATING": []}  # fmt: skip
    off = compose.effective(compose.normalize({"compilation": False}), Tags(compilation=True))
    assert compose.vorbis(off, Tags()) == {"COMPILATION": []}
    assert "DESCRIPTION" not in compose.vorbis(change(comment="Live take"), BEFORE)


def test_id3_frames_for_each_field_track_and_disc_as_pairs():
    edit = compose.id3(
        change(title="Undertow", artistsort="Drift, Lumen", track=5, disc=None, year=2020,
               genres=["Jazz", "Funk"], compilation=True),
        BEFORE,
    )  # fmt: skip
    assert edit == {
        "TIT2": ["Undertow"], "TSOP": ["Drift, Lumen"], "TRCK": ["5/10"], "TPOS": ["0/2"],
        "TDRC": ["2020"], "TYER": [], "TDAT": [], "TIME": [], "TCON": ["Jazz", "Funk"],
        "TCMP": ["1"],
    }  # fmt: skip
    assert compose.id3(change(tracktotal=None), BEFORE) == {"TRCK": ["4"]}
    assert compose.id3(change(track=None, tracktotal=None, compilation=False), BEFORE) == {
        "TRCK": []
    }  # compilation was already off: nothing to write
    assert compose.id3(change(year=None), BEFORE)["TDRC"] == []
    assert parse.number_pair("0/2") == (None, 2)  # what TPOS without a number reads back as


def test_id3v23_genres_are_one_value_joined_with_semicolons():
    assert compose.id3v23_genres(["Jazz", "Funk"]) == ["Jazz; Funk"]
    assert parse.genres(compose.id3v23_genres(["Jazz", "Funk"])) == ("Jazz", "Funk")
    assert compose.id3v23_genres([]) == []
    assert [compose.popm(s) for s in range(6)] == [0, 1, 64, 128, 196, 255]  # R10.4
    assert all(parse.popm_stars(compose.popm(s)) == s for s in range(6))


def test_mp4_atoms_for_each_field():
    edit = compose.mp4(
        change(title="Undertow", album=None, track=None, disctotal=3, year="2020-03-04",
               genres=[], compilation=True, rating=5),
        BEFORE,
    )  # fmt: skip
    assert edit == {
        "\xa9nam": ["Undertow"], "\xa9alb": None, "trkn": [(0, 10)], "disk": [(1, 3)],
        "\xa9day": ["2020-03-04"], "\xa9gen": None, "cpil": True,
        compose.MP4_RATING: [b"100"],
    }  # fmt: skip
    assert compose.mp4(change(track=None, tracktotal=None, rating=0), BEFORE) == {
        "trkn": None, compose.MP4_RATING: None,
    }  # fmt: skip
    off = compose.effective(compose.normalize({"compilation": False}), Tags(compilation=True))
    assert compose.mp4(off, Tags()) == {"cpil": None}


def frame(fid, data, version, status=0, fmt=0):
    n = len(data)
    size = bytes((n >> s) & 0x7F for s in (21, 14, 7, 0)) if version == 4 else n.to_bytes(4, "big")
    return fid + size + bytes([status, fmt]) + data


def test_a_frame_mutagen_doesnt_know_is_made_the_other_versions():
    """Mutagen writes the frames it doesn't know only in the version they were read in: going
    from ID3v2.3 to 2.4 or back, they are converted, or they would be lost (R4.1.1)."""
    data = b"\x00Drift, Lumen" + b"x" * 200  # longer than 127: the sizes differ
    v23 = frame(b"XSOP", data, 3, status=0x80)  # tag alter preservation, 2.3's place
    v24 = frame(b"XSOP", data, 4, status=0x40)  # and 2.4's
    assert compose.id3_frame_to(v23, 3, 4) == v24
    assert compose.id3_frame_to(v24, 4, 3) == v23
    assert compose.id3_frame_to(v23, 3, 3) == v23


@pytest.mark.parametrize(
    "raw, source",
    [
        (b"XYZ\x00\x00\x07\x00secret", 2),  # ID3v2.2's three-letter ids
        (frame(b"XSOP", b"\x00zlib...", 3, fmt=0x80), 3),  # compressed
        (frame(b"XSOP", b"\x00Sort", 3)[:-1], 3),  # cut short
        (frame(b"xs\x00p", b"\x00Sort", 3), 3),  # not a frame id
        (b"XSOP", 3),
    ],
)
def test_a_frame_that_cant_be_converted_is_none(raw, source):
    assert compose.id3_frame_to(raw, source, 4 if source != 4 else 3) is None


@given(st.binary(min_size=0, max_size=40), st.integers(0, 0xFF))
def test_any_frame_converted_there_and_back_is_itself(data, status):
    v23 = frame(b"ABCD", data, 3, status=status & 0xE0)
    assert compose.id3_frame_to(compose.id3_frame_to(v23, 3, 4), 4, 3) == v23


def test_the_cover_set_or_removed_leaves_the_other_pictures_after_it():
    front, back = Picture(3, "image/jpeg", b"old"), Picture(4, "image/jpeg", b"back")
    new = Picture(3, "image/png", b"new")
    assert compose.pictures_after([back, front], new, typed=True) == [new, back]
    assert compose.pictures_after([back, front], None, typed=True) == [back]
    mp4 = [Picture(None, "image/jpeg", b"one"), Picture(None, "image/png", b"two")]
    assert compose.pictures_after(mp4, new, typed=False) == [new, mp4[1]]
    assert compose.pictures_after(mp4, None, typed=False) == [mp4[1]]


def test_an_images_size_is_read_from_a_png_or_a_jpeg():
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (640).to_bytes(4, "big")
           + (480).to_bytes(4, "big") + bytes([8, 2]))  # fmt: skip
    assert compose.image_size(png) == (640, 480, 24)
    app0 = b"\xff\xe0\x00\x04ab"
    sof = b"\xff\xc0\x00\x11\x08" + (300).to_bytes(2, "big") + (500).to_bytes(2, "big") + b"\x03"
    assert compose.image_size(b"\xff\xd8" + app0 + sof) == (500, 300, 24)
    assert compose.image_size(b"\xff\xd8" + app0 + b"\xff\xc0\x00") == (0, 0, 0)  # cut short
    assert compose.image_size(b"\xff\xd8" + app0) == (0, 0, 0)
    assert compose.image_size(b"GIF89a") == (0, 0, 0)


def info_chunk(*subs):
    body = b"INFO"
    for sid, value in subs:
        n = len(value)
        body += sid + n.to_bytes(4, "little") + value + b"\x00" * (n & 1)
    return body


def test_a_wavs_info_chunk_kept_in_step_never_added_to():
    values = compose.info(
        change(title="Undertow", artist=None, genres=["Jazz", "Funk"], track=7, year=2020)
    )
    assert values == {"INAM": "Undertow", "IART": None, "IGNR": "Jazz; Funk", "ITRK": "7",
                      "IPRT": "7", "ICRD": "2020"}  # fmt: skip
    body = info_chunk((b"INAM", b"Old\x00"), (b"IART", b"Someone\x00"), (b"ISFT", b"Lavf\x00"))
    edited = compose.riff_info_edit(body, values)
    assert parse.riff_info(
        b"RIFF" + (len(edited) + 12).to_bytes(4, "little") + b"WAVE"
        + b"LIST" + len(edited).to_bytes(4, "little") + edited
    ) == {"INAM": "Undertow", "ISFT": "Lavf"}  # fmt: skip
    cut = body + b"ICMT" + (50).to_bytes(4, "little") + b"short"
    assert compose.riff_info_edit(cut, {"ICMT": None}).endswith(b"short")  # left as it was
    assert compose.info(change(track=None)) == {"ITRK": None, "IPRT": None}
    assert compose.info(change(comment="Hi", genres=[])) == {"ICMT": "Hi", "IGNR": None}


def test_the_cover_a_change_replaces_is_the_front_one_or_mp4s_first():
    front, back = Picture(3, "image/jpeg", b"f"), Picture(4, "image/jpeg", b"b")
    assert compose.cover_of([back, front], typed=True) == front
    assert compose.cover_of([back], typed=True) is None
    assert compose.cover_of([back, front], typed=False) == back
    assert compose.cover_of([], typed=False) is None


@pytest.mark.parametrize(
    ("data", "mime"),
    [(b"\x89PNG\r\n\x1a\n...", "image/png"), (b"GIF89a...", "image/gif"),
     (b"RIFF\0\0\0\0WEBPVP8 ", "image/webp"), (b"\xff\xd8\xff\xe0", "image/jpeg"),
     (b"", "image/jpeg")],
)  # fmt: skip
def test_a_kept_covers_type_is_known_from_its_bytes(data, mime):
    assert compose.image_mime(data) == mime
