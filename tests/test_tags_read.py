"""Reading a song's file (src/musikata_core/tags/read.py; A3.1, A3.2): every kind of R2.2 as
MusiKata's demo library and other programs write it, and the files that can't be read.

Why: parse.py's shapes are only half of it: which frames Mutagen hands on, how ID3v2.2 and v1 are
upgraded, and which file kind an .m4a is, are the edge's, and are tested here on real files."""

import contextlib
import importlib
import os
import shutil
import sys

import mutagen
import mutagen.apev2
import mutagen.flac
import mutagen.id3 as id3
import mutagen.mp4
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from musikata_core import tags

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

tag_read = importlib.import_module("musikata_core.tags.read")  # the module, not tags.read

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


def _replaygain_as_written(path, kind):
    """ReplayGain written into `path` as the common programs write it for its kind (A3.2): TXXX
    frames (foobar2000's lower case), Vorbis comments, MP4 freeform atoms, Opus's R128_* gains."""
    gains = {"track_gain": "-7.50 dB", "track_peak": "0.812", "album_gain": "-6.25 dB",
             "album_peak": "0.977"}  # fmt: skip
    if kind in ("mp3", "wav", "aiff"):
        f = mutagen.File(path)
        if f.tags is None:
            f.add_tags()
        for k, v in gains.items():
            f.tags.add(id3.TXXX(encoding=3, desc=f"replaygain_{k}", text=[v]))
        f.save()
    elif kind in ("aac", "alac"):
        f = mutagen.mp4.MP4(path)
        for k, v in gains.items():
            f[f"----:com.apple.iTunes:replaygain_{k}"] = [mutagen.mp4.MP4FreeForm(v.encode())]
        f.save()
    else:
        f = mutagen.File(path)
        if kind == "opus":  # RFC 7845: -12.5 and -11.25 dB to -23 LUFS, no peaks
            f["R128_TRACK_GAIN"], f["R128_ALBUM_GAIN"] = "-3200", "-2880"
        else:
            for k, v in gains.items():
                f[f"REPLAYGAIN_{k.upper()}"] = v
        f.save()


@pytest.mark.slow
@pytest.mark.parametrize("kind", list(demo.KINDS))
def test_each_kind_gives_its_replaygain_as_its_taggers_write_it(audio, tmp_path, kind):
    path = _copy(audio, kind, tmp_path)
    _replaygain_as_written(path, kind)
    t, _ = tags.read(path)
    peaks = (None, None) if kind == "opus" else (0.812, 0.977)
    assert (t.rg_track_gain, t.rg_album_gain) == (-7.5, -6.25)
    assert (t.rg_track_peak, t.rg_album_peak) == peaks


@pytest.mark.slow
def test_an_mp3s_replaygain_in_rva2_frames_or_an_apev2_tag(audio, tmp_path):
    """Quod Libet and Mutagen's EasyID3 write RVA2 frames; mp3gain an APEv2 tag at the end."""
    path = _copy(audio, "mp3", tmp_path, "rva2.mp3")
    f = mutagen.File(path)
    if f.tags is None:
        f.add_tags()
    f.tags.add(id3.RVA2(desc="track", channel=1, gain=-4.5, peak=0.75))
    f.tags.add(id3.RVA2(desc="album", channel=2, gain=9.0, peak=1.0))  # not the master volume
    f.save()
    t, _ = tags.read(path)
    assert (t.rg_track_gain, t.rg_track_peak, t.rg_album_gain) == (-4.5, pytest.approx(0.75), None)
    path = _copy(audio, "mp3", tmp_path, "mp3gain.mp3")
    ape = mutagen.apev2.APEv2()
    ape["REPLAYGAIN_TRACK_GAIN"] = "+1.230000 dB"
    ape["REPLAYGAIN_TRACK_PEAK"] = "0.501000"
    ape["MP3GAIN_MINMAX"] = "089,201"
    ape.save(path)
    t, _ = tags.read(path)
    assert (t.rg_track_gain, t.rg_track_peak, t.rg_album_gain) == (1.23, 0.501, None)


def test_an_apev2_tag_that_cant_be_read_is_logged_and_passed_over(tmp_path, caplog):
    path = tmp_path / "cut.mp3"
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 200 + b"APETAGEX" + b"\xd0\x07" + b"\x00" * 22)
    assert tag_read._ape_replaygain(str(path)) == {}
    assert tag_read._ape_replaygain(str(tmp_path / "gone.mp3")) == {}
    assert "couldn't read the APEv2 tag" in caplog.text


@pytest.mark.slow
def test_mp4_atoms_that_are_not_lists_compilation_gapless_and_tempo(audio, tmp_path):
    """iTunes' cpil and pgap are a bool, not a list; tmpo a list of numbers (the demo library's
    Compilations stopped the whole scan on cpil)."""
    path = _copy(audio, "alac", tmp_path)
    f = mutagen.mp4.MP4(path)
    f["\xa9nam"] = "Harbor Lights"
    f["cpil"] = True
    f["pgap"] = False
    f["tmpo"] = [120]
    f.save()
    t, info = tags.read(path)
    assert (t.title, t.compilation, info.kind) == ("Harbor Lights", True, "alac")


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


def test_the_tags_a_song_keeps_without_showing_are_read_from_each_kind(audio, tmp_path):
    """R4.1.1, R4.8: what the panel lists read only for one song, from the file."""
    mp3 = _copy(audio, "mp3", tmp_path)
    f = id3.ID3()
    f.add(id3.TIT2(encoding=3, text=["Parallax"]))
    f.add(id3.TXXX(encoding=3, desc="MusicBrainz Album Id", text="0f4d"))
    f.add(id3.USLT(encoding=3, lang="eng", desc="", text="la la"))
    f.add(id3.PRIV(owner="WM/Provider", data=b"\x00" * 16))
    f.add(id3.PCNT(count=7))
    f.add(id3.ETCO(format=2, events=[(3, 1000)]))  # a frame of neither text nor data
    f.add(id3.APIC(encoding=3, mime="image/png", type=4, desc="", data=b"png" * 4))
    f.add(id3.APIC(encoding=3, mime="image/png", type=3, desc="front", data=b"png"))
    f.save(mp3)
    assert sorted(tags.kept(mp3))[0][0] == "ETCO"  # a frame it has no name for, by its id
    assert sorted(tags.kept(mp3))[1:] == [  # in the order Mutagen saved them
        ("Lyrics", "la la"), ("MusicBrainz Album Id", "0f4d"),
        ("Picture", "back cover, 12 bytes"), ("Play count", "7"),
        ("Private data (WM/Provider)", "16 bytes"),
    ]  # fmt: skip
    flac = _copy(audio, "flac", tmp_path)
    g = mutagen.File(flac)
    g["title"] = "x"
    g["lyrics"] = "words"
    back = mutagen.flac.Picture()
    back.type, back.data = 4, b"back"
    g.add_picture(back)
    g.save()
    kept = tags.kept(flac)  # the encoder FFmpeg names, the lyrics, the back cover
    assert [n for n, _ in kept] == ["Encoder", "Lyrics", "Picture"]
    assert kept[1:] == [("Lyrics", "words"), ("Picture", "back cover, 4 bytes")]
    m4a = _copy(audio, "aac", tmp_path)
    h = mutagen.mp4.MP4(m4a)
    h["\xa9nam"] = "x"
    h["----:com.apple.iTunes:MusicBrainz Track Id"] = [mutagen.mp4.MP4FreeForm(b"9a")]
    h["trkn"] = [(4, 10)]
    h["tmpo"] = [120]
    h.save()
    found = dict(tags.kept(m4a))  # beside the encoder FFmpeg names
    assert (found["MusicBrainz Track Id"], found["BPM"]) == ("9a", "120")
    assert set(found) == {"MusicBrainz Track Id", "BPM", "Encoder"}
    bare = _copy(audio, "wav", tmp_path)
    assert tags.kept(bare) == []
    with pytest.raises(tags.TagReadError):
        tags.kept(str(tmp_path / "gone.flac"))
