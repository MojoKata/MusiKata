"""Reading a song's file (src/musikata_core/tags/read.py; A3.1, A3.2): every kind of R2.2 as
MusiKata's demo library and other programs write it, and the files that can't be read.

Why: parse.py's shapes are only half of it: which frames Mutagen hands on, how ID3v2.2 and v1 are
upgraded, and which file kind an .m4a is, are the edge's, and are tested here on real files."""

import contextlib
import os
import shutil
import sys

import mutagen.id3 as id3
import mutagen.mp4
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from musikata_core import tags

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

SONG = {
    "title": "Signal Fires", "artist": "Lumen Drift", "album": "Glass Harbor",
    "albumartist": "Lumen Drift", "track": 4, "tracktotal": 10, "year": 2019,
    "genre": ["Electronic", "Ambient"], "rating": 4,
}  # fmt: skip


@pytest.fixture(scope="module")
def audio(tmp_path_factory):
    """One untagged file of each kind, made once: {kind: path}."""
    d = tmp_path_factory.mktemp("audio")
    out = {}
    for kind, (ext, *_rest) in demo.KINDS.items():
        out[kind] = str(d / f"{kind}.{ext}")
        demo.encode(out[kind], kind, 0.2, 440)
    return out


def _copy(audio, kind, tmp_path, name=None):
    path = str(tmp_path / (name or os.path.basename(audio[kind])))
    shutil.copyfile(audio[kind], path)
    return path


@pytest.mark.slow
@pytest.mark.parametrize("kind", list(demo.KINDS))
def test_each_kind_reads_back_what_the_demo_library_writes(audio, tmp_path, kind):
    path = _copy(audio, kind, tmp_path)
    demo.tag(path, demo.Song(path, kind, dict(SONG), cover=(11, 32)))
    t, info = tags.read(path)
    assert info.kind == kind and 0.15 < info.length < 0.3 and info.channels == 2
    assert (t.title, t.artist, t.album, t.track, t.year) == (
        "Signal Fires", "Lumen Drift", "Glass Harbor", 4, 2019,
    )  # fmt: skip
    assert t.genres == ("Electronic", "Ambient") and t.rating == 4 and t.has_cover


@pytest.mark.slow
def test_an_m4a_is_aac_or_alac_by_its_codec(audio):
    assert tags.read(audio["aac"])[1].kind == "aac"
    assert tags.read(audio["alac"])[1].kind == "alac"


@pytest.mark.slow
def test_id3v23_with_tyer_tdat_track_04_and_genres_joined(audio, tmp_path):
    path = _copy(audio, "mp3", tmp_path)
    f = id3.ID3()
    f.add(id3.TIT2(encoding=1, text="Low Orbit"))
    f.add(id3.TRCK(encoding=1, text="04"))
    f.add(id3.TYER(encoding=1, text="2022"))
    f.add(id3.TDAT(encoding=1, text="1503"))
    f.add(id3.TCON(encoding=1, text="Synthwave; Electronic"))
    f.save(path, v2_version=3)
    t, _ = tags.read(path)
    assert (t.title, t.track, t.year, t.date) == ("Low Orbit", 4, 2022, "2022-03-15")
    assert t.genres == ("Synthwave", "Electronic")


@pytest.mark.slow
def test_id3v1_numbers_and_id3v1_alone_and_beside_a_v2_that_disagrees(audio, tmp_path):
    numbered = _copy(audio, "mp3", tmp_path, "numbered.mp3")
    f = id3.ID3()
    f.add(id3.TCON(encoding=3, text="(17)"))
    f.save(numbered)
    assert tags.read(numbered)[0].genres == ("Rock",)  # R9.3

    v1 = _copy(audio, "mp3", tmp_path, "v1.mp3")
    with open(v1, "ab") as out:  # an ID3v1 tag alone: 128 bytes at the end
        fields = [b"Old Title", b"Old Artist", b"Old Album"]
        tag = b"TAG" + b"".join(f.ljust(30, b"\0") for f in fields) + b"1999"
        out.write(tag + b"\0" * 28 + b"\x00\x03" + bytes([17]))  # v1.1: track 3, genre 17
    t, _ = tags.read(v1)
    assert (t.title, t.artist, t.year, t.track, t.genres) == (
        "Old Title",
        "Old Artist",
        1999,
        3,
        ("Rock",),
    )

    both = _copy(audio, "mp3", tmp_path, "both.mp3")
    f = id3.ID3()
    f.add(id3.TIT2(encoding=3, text="New Title"))
    f.save(both, v1=2)
    with open(both, "r+b") as out:  # make v1 say something else
        out.seek(-125, os.SEEK_END)
        out.write(b"Stale".ljust(30, b"\0"))
    assert tags.read(both)[0].title == "New Title"


@pytest.mark.slow
def test_an_id3v22_tag_is_read_by_its_upgraded_frames(audio, tmp_path):
    path = _copy(audio, "mp3", tmp_path)
    with open(path, "rb") as f:
        mp3 = f.read()
    frames = b""
    for fid, value in ((b"TT2", "Undertow"), (b"TP1", "Lumen Drift"), (b"TRK", "5/10")):
        data = b"\x00" + value.encode("latin-1")
        frames += fid + len(data).to_bytes(3, "big") + data
    size = len(frames)
    synchsafe = bytes([(size >> 21) & 127, (size >> 14) & 127, (size >> 7) & 127, size & 127])
    with open(path, "wb") as f:
        f.write(b"ID3\x02\x00\x00" + synchsafe + frames + mp3)
    t, _ = tags.read(path)
    assert (t.title, t.artist, t.track, t.tracktotal) == ("Undertow", "Lumen Drift", 5, 10)


@pytest.mark.slow
def test_repeated_and_empty_frames_and_picards_ids_are_read_around(audio, tmp_path):
    path = _copy(audio, "mp3", tmp_path)
    f = id3.ID3()
    f.add(id3.TIT2(encoding=3, text=["", "Parallax"]))
    f.add(id3.TPE1(encoding=3, text=["Lumen Drift", "Guest"]))
    f.add(
        id3.TXXX(
            encoding=3, desc="MusicBrainz Album Id", text="0f4d2c1e-0000-4000-8000-000000000000"
        )
    )
    f.add(id3.UFID(owner="http://musicbrainz.org", data=b"0f4d"))
    f.add(id3.COMM(encoding=3, lang="eng", desc="", text=""))
    f.add(id3.POPM(email="MusicBee", rating=196))
    f.save(path)
    t, _ = tags.read(path)
    assert (t.title, t.artist, t.comment, t.rating) == ("Parallax", "Lumen Drift", None, 4)


@pytest.mark.slow
def test_vorbis_keys_written_in_lower_case_and_repeated(audio, tmp_path):
    path = _copy(audio, "flac", tmp_path)
    f = mutagen.File(path)
    f["title"] = "Quiet Acres"
    f["genre"] = ["Folk", "Acoustic"]
    f["fmps_rating"] = "0.6"
    f.save()
    t, _ = tags.read(path)
    assert (t.title, t.genres, t.rating) == ("Quiet Acres", ("Folk", "Acoustic"), 3)


@pytest.mark.slow
def test_mp4_freeform_rating_and_replaygain(audio, tmp_path):
    path = _copy(audio, "aac", tmp_path)
    f = mutagen.mp4.MP4(path)
    f["\xa9nam"] = "Paper Moons"
    f["----:com.apple.iTunes:RATING"] = [mutagen.mp4.MP4FreeForm(b"100")]
    f["----:com.apple.iTunes:replaygain_track_gain"] = [mutagen.mp4.MP4FreeForm(b"-4.25 dB")]
    f.save()
    t, _ = tags.read(path)
    assert (t.title, t.rating, t.rg_track_gain) == ("Paper Moons", 5, -4.25)


@pytest.mark.slow
def test_a_wav_with_only_a_riff_info_chunk_is_read(audio, tmp_path):
    path = _copy(audio, "wav", tmp_path)
    with open(path, "rb") as f:
        data = bytearray(f.read())
    sub = b""
    for k, v in ((b"INAM", b"Breakwater"), (b"IART", b"Hollow Coast"), (b"ICRD", b"2023")):
        n = len(v) + 1
        sub += k + n.to_bytes(4, "little") + v + b"\0" + b"\0" * (n & 1)
    chunk = b"LIST" + (len(sub) + 4).to_bytes(4, "little") + b"INFO" + sub
    data += chunk
    data[4:8] = (len(data) - 8).to_bytes(4, "little")
    with open(path, "wb") as f:
        f.write(data)
    t, info = tags.read(path)
    assert (t.title, t.artist, t.year, info.kind) == ("Breakwater", "Hollow Coast", 2023, "wav")


def test_a_file_of_another_kind_or_damaged_is_a_tag_read_error(tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("not music")
    with pytest.raises(tags.TagReadError, match="not a kind"):
        tags.read(str(other))
    broken = tmp_path / "broken.flac"
    broken.write_bytes(b"fLaC" + b"\xff" * 40)
    with pytest.raises(tags.TagReadError):
        tags.read(str(broken))
    with pytest.raises(tags.TagReadError):
        tags.read(str(tmp_path / "missing.mp3"))


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.binary(max_size=400), ext=st.sampled_from(sorted(tags.EXTENSIONS)))
def test_any_bytes_of_any_kind_read_or_fail_as_a_tag_read_error(tmp_path, data, ext):
    path = tmp_path / f"any{ext}"
    path.write_bytes(data)
    with contextlib.suppress(tags.TagReadError):
        tags.read(str(path))
