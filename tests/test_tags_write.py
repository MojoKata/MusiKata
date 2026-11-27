"""Writing a song's tags (src/musikata_core/tags/write.py, through safe.save; A3.1, A3.2, R4.1,
R4.7.2): every field written to every kind and read back, on generated files and on the demo
library's, and the shapes other programs leave in files, which a write must keep.

Why: compose.py's tables are only half of it: what Mutagen keeps, drops or converts on saving (an
ID3v2.3 file saved as 2.4 loses the frames Mutagen doesn't know; ID3v2.3 loses TSOP; an ID3v1 tag
loses its comment) is the edge's, and is shown here on real files."""

import base64
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

from musikata_core import scanner, tags
from musikata_core.tags import Picture, compose, parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

tag_write = importlib.import_module("musikata_core.tags.write")

SONG = {
    "title": "Signal Fires", "artist": "Lumen Drift", "album": "Glass Harbor",
    "albumartist": "Lumen Drift", "track": 4, "tracktotal": 10, "year": 2019,
    "genre": ["Electronic", "Ambient"], "rating": 4,
}  # fmt: skip
EVERY = {
    "title": "Undertow", "artist": "Marrow Oak", "album": "Kindling", "albumartist": "Various",
    "track": 5, "tracktotal": 12, "disc": 2, "disctotal": 3, "year": "2020-03-04",
    "genres": ["Jazz", "Funk"], "composer": "Ana Reyes", "comment": "Live take",
    "compilation": True, "artistsort": "Oak, Marrow", "albumartistsort": "Various",
    "albumsort": "Kindling, The", "rating": 5,
}  # fmt: skip
NOTHING = {
    **dict.fromkeys(EVERY), "genres": [], "compilation": False, "rating": 0, "cover": None,
}  # fmt: skip
UNRATED = ("wav", "aiff")  # R10.4: their ratings are kept in ratings.json, not the file


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


def save(path, id3_version="2.4", **changes):
    return tags.save(path, changes, audio_hash=scanner.audio_hash, id3_version=id3_version)


def cover(seed=5):
    return Picture(3, "image/jpeg", demo.cover_jpeg(seed, 16))


def v1_of(path):
    with open(path, "rb") as f:
        f.seek(-128, os.SEEK_END)
        tag = f.read(128)
    return tag if tag[:3] == b"TAG" else None


@pytest.mark.slow
@pytest.mark.parametrize("version", ["2.4", "2.3"])
@pytest.mark.parametrize("kind", list(demo.KINDS))
def test_each_kind_reads_back_every_field_written_and_none_once_each_is_removed(
    audio, tmp_path, kind, version
):
    path = _copy(audio, kind, tmp_path)
    demo.tag(path, demo.Song(path, kind, dict(SONG), cover=(11, 32)))
    every = {k: v for k, v in EVERY.items() if not (kind in UNRATED and k == "rating")}
    written = save(path, version, **every, cover=cover())
    t, _ = tags.read(path)
    assert t == written.tags
    assert (t.title, t.artist, t.album, t.albumartist) == ("Undertow", "Marrow Oak", "Kindling",
                                                           "Various")  # fmt: skip
    assert (t.track, t.tracktotal, t.disc, t.disctotal) == (5, 12, 2, 3)
    assert (t.year, t.date, t.genres, t.composer, t.comment) == (
        2020, "2020-03-04", ("Jazz", "Funk"), "Ana Reyes", "Live take",
    )  # fmt: skip
    assert (t.compilation, t.artistsort, t.albumartistsort, t.albumsort) == (
        True, "Oak, Marrow", "Various", "Kindling, The",
    )  # fmt: skip
    assert t.rating == (4 if kind in UNRATED else 5)  # the demo library's POPM, left alone
    assert tags.pictures(path)[0].data == cover().data and t.has_cover
    nothing = {k: v for k, v in NOTHING.items() if not (kind in UNRATED and k == "rating")}
    save(path, version, **nothing)
    t, _ = tags.read(path)
    assert t == tags.Tags(rating=4 if kind in UNRATED else None)
    assert tags.pictures(path) == []


@pytest.mark.slow
def test_a_wav_or_aiff_is_given_no_rating_its_ratings_live_in_ratings_json(audio, tmp_path):
    path = _copy(audio, "wav", tmp_path)
    with pytest.raises(ValueError, match="R10.4"):
        save(path, rating=3)


@pytest.mark.slow
def test_the_demo_librarys_files_of_every_kind_and_shape_are_written_and_read_back(audio, tmp_path):
    """Each kind and each way the demo library writes tags (ID3v2.3, ID3v1 too, TRCK "04",
    lower-case Vorbis keys, embedded covers, compilations, Windows-1251 in Latin-1 frames): one
    song of each, retitled, its genres and track changed; the rest reads as it did."""
    seen = {}
    for song in demo.plan().songs:
        key = (song.kind, frozenset(song.shape), song.cover is not None, song.tags is None)
        seen.setdefault(key, song)
    assert len(seen) >= 12
    for n, song in enumerate(seen.values()):
        path = _copy(audio, song.kind, tmp_path, f"{n}{os.path.splitext(audio[song.kind])[1]}")
        demo.tag(path, song)
        before, _ = tags.read(path)
        pictures = tags.pictures(path)
        written = save(path, title="Retitled", genres=["Jazz", "Soul"], track=7)
        t, _ = tags.read(path)
        assert t == written.tags
        assert (t.title, t.genres, t.track) == ("Retitled", ("Jazz", "Soul"), 7), song.path
        # the title written as Unicode: no longer held as Latin-1 (A3.6, the cp1251 shape)
        latin1 = tuple(f for f in before.latin1 if f != "title")
        assert t.__dict__ == {
            **before.__dict__, "title": "Retitled", "genres": ("Jazz", "Soul"), "track": 7,
            "latin1": latin1,
        }, song.path  # fmt: skip
        assert tags.pictures(path) == pictures
        if "id3v1-too" in song.shape:
            assert v1_of(path)[3:33].rstrip(b"\0") == b"Retitled"  # R4.7.2


@pytest.mark.slow
def test_id3v24_or_id3v23_as_the_setting_says_and_v23_genres_joined(audio, tmp_path):
    path = _copy(audio, "mp3", tmp_path)
    save(path, "2.3", title="Low Orbit", genres=["Synthwave", "Electronic"], year="2022-03-15")
    f = id3.ID3(path, translate=False)
    assert f.version == (2, 3, 0)
    assert f["TCON"].text == ["Synthwave; Electronic"]  # R9.2
    assert (f["TYER"].text, f["TDAT"].text) == (["2022"], ["1503"])
    save(path, "2.4", title="Low Orbit II")
    f = id3.ID3(path, translate=False)
    assert f.version == (2, 4, 0) and f["TCON"].text == ["Synthwave", "Electronic"]
    assert str(f["TDRC"].text[0]) == "2022-03-15"


@pytest.mark.slow
def test_an_id3v1_tag_is_updated_to_match_and_none_is_added(audio, tmp_path):
    """R4.7.2, and the shapes ID3v1 alone, and v1 and v2 that disagree."""
    alone = _copy(audio, "mp3", tmp_path, "v1.mp3")
    id3.ID3().save(alone, v1=0)
    id3.delete(alone)
    with open(alone, "ab") as out:
        fields = [b"Old Title", b"Old Artist", b"Old Album"]
        out.write(b"TAG" + b"".join(f.ljust(30, b"\0") for f in fields) + b"1999"
                  + b"tape".ljust(28, b"\0") + b"\x00\x03" + bytes([17]))  # fmt: skip
    save(alone, title="New Title", comment="Remastered")
    t, _ = tags.read(alone)
    assert (t.title, t.artist, t.album, t.year, t.track, t.genres, t.comment) == (
        "New Title", "Old Artist", "Old Album", 1999, 3, ("Rock",), "Remastered",
    )  # fmt: skip
    v1 = v1_of(alone)
    assert v1[3:33].rstrip(b"\0") == b"New Title" and v1[97:107] == b"Remastered"
    assert v1[127] == 17
    with open(alone, "rb") as f:
        assert f.read(3) == b"ID3"  # an ID3v2 tag beside it now

    both = _copy(audio, "mp3", tmp_path, "both.mp3")
    f = id3.ID3()
    f.add(id3.TIT2(encoding=3, text="New Title"))
    f.save(both, v1=2)
    with open(both, "r+b") as out:  # make v1 say something else
        out.seek(-125, os.SEEK_END)
        out.write(b"Stale".ljust(30, b"\0"))
    save(both, artist="Lumen Drift")
    assert v1_of(both)[3:33].rstrip(b"\0") == b"New Title"
    assert v1_of(both)[33:63].rstrip(b"\0") == b"Lumen Drift"

    none = _copy(audio, "mp3", tmp_path, "none.mp3")
    save(none, title="Tidewater")
    assert v1_of(none) is None


def _v22(path, frames):
    with open(path, "rb") as f:
        mp3 = f.read()
    data = b""
    for fid, value in frames:
        data += fid + len(value).to_bytes(3, "big") + value
    n = len(data)
    size = bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127])
    with open(path, "wb") as f:
        f.write(b"ID3\x02\x00\x00" + size + data + mp3)


@pytest.mark.slow
def test_an_id3v22_tag_is_written_as_v24_its_unknown_frames_logged(audio, tmp_path, caplog):
    path = _copy(audio, "mp3", tmp_path)
    _v22(path, [(b"TT2", b"\x00Undertow"), (b"TP1", b"\x00Lumen Drift"), (b"TRK", b"\x005/10"),
                (b"XYZ", b"\x00secret")])  # fmt: skip
    save(path, title="Parallax")
    t, _ = tags.read(path)
    assert (t.title, t.artist, t.track, t.tracktotal) == ("Parallax", "Lumen Drift", 5, 10)
    assert id3.ID3(path).version == (2, 4, 0)
    assert "an ID3v2.2 frame 'XYZ' can't be written as ID3v2.4" in caplog.text


def _v2(path, version, frames):
    """An ID3v2.`version` tag of raw frames, (id, data), at the start of an MP3."""
    with open(path, "rb") as f:
        mp3 = f.read()
    data = b""
    for fid, value in frames:
        n = len(value)
        size = (
            bytes((n >> s) & 0x7F for s in (21, 14, 7, 0)) if version == 4 else n.to_bytes(4, "big")
        )
        data += fid + size + b"\x00\x00" + value
    n = len(data)
    with open(path, "wb") as f:
        f.write(b"ID3" + bytes([version, 0, 0]) + bytes((n >> s) & 0x7F for s in (21, 14, 7, 0)))
        f.write(data + mp3)


@pytest.mark.slow
@pytest.mark.parametrize("source, target", [(3, "2.4"), (4, "2.3")])
def test_frames_mutagen_doesnt_know_and_v24s_sort_names_survive_either_version(
    audio, tmp_path, source, target
):
    path = _copy(audio, "mp3", tmp_path)
    _v2(path, source, [(b"TIT2", b"\x00Signal Fires"), (b"TSOP", b"\x00Drift, Lumen"),
                       (b"TSOA", b"\x00Glass Harbor, The"), (b"XSOP", b"\x00Drift, Lumen"),
                       (b"NCON", b"MusicMatch's own")])  # fmt: skip
    if source == 4:
        f = id3.ID3(path)
        f.add(id3.RVA2(desc="track", channel=1, gain=-4.5, peak=0.75))
        f.save(path, v2_version=4)
    save(path, target, title="Undertow")
    f = id3.ID3(path)
    assert f.version[1] == int(target[-1])
    assert sorted(bytes(u[:4]) for u in f.unknown_frames) == [b"NCON", b"XSOP"]
    t, _ = tags.read(path)
    assert (t.title, t.artistsort, t.albumsort) == ("Undertow", "Drift, Lumen", "Glass Harbor, The")
    if source == 4:
        assert t.rg_track_gain == -4.5  # RVA2, Quod Libet's ReplayGain, kept in ID3v2.3 too


@pytest.mark.slow
def test_what_other_programs_keep_in_an_mp3_is_left_as_it_was(audio, tmp_path):
    """R4.1.1: Picard's ids, iTunes' COMM frames, other players' POPM and their play counts,
    lyrics, private frames, a back cover, ReplayGain in TXXX and in an APEv2 tag."""
    path = _copy(audio, "mp3", tmp_path)
    f = id3.ID3()
    f.add(id3.TXXX(encoding=3, desc="MusicBrainz Album Id", text="0f4d2c1e"))
    f.add(id3.UFID(owner="http://musicbrainz.org", data=b"0f4d"))
    f.add(id3.COMM(encoding=3, lang="eng", desc="iTunNORM", text=" 00000A2B"))
    f.add(id3.COMM(encoding=3, lang="eng", desc="", text="Old comment"))
    f.add(id3.POPM(email="MusicBee", rating=196, count=3))
    f.add(id3.POPM(email=parse.WMP, rating=64, count=12))
    f.add(id3.USLT(encoding=3, lang="eng", desc="", text="la la"))
    f.add(id3.PRIV(owner="WM/MediaClassPrimaryID", data=b"\x01\x02"))
    f.add(id3.APIC(encoding=3, mime="image/jpeg", type=4, desc="", data=b"back"))
    f.add(id3.TXXX(encoding=3, desc="replaygain_track_gain", text="-7.50 dB"))
    f.save(path)
    ape = mutagen.apev2.APEv2()
    ape["REPLAYGAIN_ALBUM_GAIN"] = "-6.25 dB"
    ape.save(path)
    save(path, comment=None, rating=0, cover=cover())
    f = id3.ID3(path)
    assert f["TXXX:MusicBrainz Album Id"].text == ["0f4d2c1e"] and f.getall("UFID")
    assert [c.desc for c in f.getall("COMM")] == ["iTunNORM"]
    popms = {p.email: (p.rating, p.count) for p in f.getall("POPM")}
    assert popms == {"MusicBee": (196, 3), parse.WMP: (0, 12)}  # cleared, its count kept
    assert f.getall("USLT")[0].text == "la la" and f.getall("PRIV")
    assert [(p.type, p.data) for p in f.getall("APIC")] == [(3, cover().data), (4, b"back")]
    t, _ = tags.read(path)
    assert (t.comment, t.rating, t.rg_track_gain, t.rg_album_gain) == (None, 0, -7.5, -6.25)
    save(path, comment="New comment", rating=2)
    f = id3.ID3(path)
    assert sorted(c.desc for c in f.getall("COMM")) == ["", "iTunNORM"]
    assert {p.email: p.rating for p in f.getall("POPM")}[parse.WMP] == 64
    assert tags.read(path)[0].comment == "New comment"


@pytest.mark.slow
def test_a_numbered_genre_is_written_by_its_name(audio, tmp_path):
    """R9.3, in both versions."""
    for version in ("2.4", "2.3"):
        path = _copy(audio, "mp3", tmp_path, f"{version}.mp3")
        f = id3.ID3()
        f.add(id3.TCON(encoding=0, text="(17)"))
        f.save(path, v2_version=3)
        save(path, version, title="Kindling")
        assert id3.ID3(path, translate=False)["TCON"].text == ["Rock"]


@pytest.mark.slow
@pytest.mark.parametrize("numbered", ["13", "(13)", "(13)Pop", "(13);Jazz", "13; (8)"])
def test_a_numbered_genre_shows_by_name_and_is_written_by_name_whatever_the_save(
    audio, tmp_path, numbered
):
    """R9.3: ID3's numbered genres, bare or in brackets, with their name after them or beside
    another genre, read as names; the next save writes the names, whichever field it changes,
    in ID3v2.3 (joined, R9.2) and ID3v2.4 (one value each)."""
    want = {"13": ("Pop",), "(13)": ("Pop",), "(13)Pop": ("Pop",), "(13);Jazz": ("Pop", "Jazz"),
            "13; (8)": ("Pop", "Jazz")}[numbered]  # fmt: skip
    for version in ("2.4", "2.3"):
        path = _copy(audio, "mp3", tmp_path, f"{version}.mp3")
        f = id3.ID3()
        f.add(id3.TCON(encoding=3, text=numbered))
        f.save(path, v2_version=3)
        assert tags.read(path)[0].genres == want
        save(path, version, title="Kindling")  # a save of another field
        text = id3.ID3(path, translate=False)["TCON"].text
        assert text == (["; ".join(want)] if version == "2.3" else list(want))


@pytest.mark.slow
def test_vorbis_keys_in_any_case_are_replaced_not_doubled_and_the_rest_kept_in_order(
    audio, tmp_path
):
    path = _copy(audio, "flac", tmp_path)
    f = mutagen.File(path)
    f.tags.extend([("title", "Quiet Acres"), ("MUSICBRAINZ_TRACKID", "9d2b"),
                   ("genre", "Folk"), ("Genre", "Acoustic"), ("album artist", "Cedar & Vale"),
                   ("totaltracks", "13"), ("tracknumber", "2/13"), ("lyrics", "la la"),
                   ("replaygain_track_gain", "-3 dB")])  # fmt: skip
    f.save()
    save(path, title="Low Light", genres=["Folk"], albumartist="Cedar and Vale", track=3)
    pairs = list(mutagen.File(path).tags)
    assert pairs[-8:] == [
        ("TITLE", "Low Light"), ("MUSICBRAINZ_TRACKID", "9d2b"), ("GENRE", "Folk"),
        ("TRACKNUMBER", "3"), ("lyrics", "la la"), ("replaygain_track_gain", "-3 dB"),
        ("ALBUMARTIST", "Cedar and Vale"), ("TRACKTOTAL", "13"),
    ]  # fmt: skip
    t, _ = tags.read(path)
    assert (t.title, t.albumartist, t.track, t.tracktotal) == ("Low Light", "Cedar and Vale", 3, 13)


@pytest.mark.slow
def test_mp4_freeform_atoms_are_kept_and_its_rating_replaced_in_any_case(audio, tmp_path):
    path = _copy(audio, "aac", tmp_path)
    f = mutagen.mp4.MP4(path)
    f["----:com.apple.iTunes:MusicBrainz Track Id"] = [mutagen.mp4.MP4FreeForm(b"9d2b")]
    f["----:com.apple.iTunes:iTunSMPB"] = [mutagen.mp4.MP4FreeForm(b" 00000000 00000840")]
    f["----:com.apple.iTunes:rating"] = [mutagen.mp4.MP4FreeForm(b"40")]
    f["tmpo"] = [120]
    f["pgap"] = True
    f.save()
    save(path, rating=4, title="Paper Moons")
    f = mutagen.mp4.MP4(path)
    freeform = sorted(k for k in f.tags if k.startswith("----"))
    assert freeform == [
        "----:com.apple.iTunes:MusicBrainz Track Id",
        "----:com.apple.iTunes:RATING",
        "----:com.apple.iTunes:iTunSMPB",
    ]
    assert bytes(f["----:com.apple.iTunes:RATING"][0]) == b"80"  # R10.4
    assert (f["tmpo"], f["pgap"]) == ([120], True)


@pytest.mark.slow
def test_mp4s_fmps_rating_of_another_player_is_kept_in_step_and_cleared_with_it(audio, tmp_path):
    """R10.4.2: an MP4's FMPS_Rating (Clementine, Strawberry) reads where RATING is none, so a
    rating written keeps it in step, and a rating cleared takes it out with RATING."""
    path = _copy(audio, "aac", tmp_path)
    f = mutagen.mp4.MP4(path)
    f["----:com.apple.iTunes:FMPS_Rating"] = [mutagen.mp4.MP4FreeForm(b"0.4")]
    f.save()
    assert tags.read(path)[0].rating == 2
    save(path, rating=5)
    f = mutagen.mp4.MP4(path)
    assert bytes(f["----:com.apple.iTunes:FMPS_Rating"][0]) == b"1.0"
    save(path, rating=0)
    assert not [k for k in mutagen.mp4.MP4(path).tags if "rating" in k.lower()]
    assert tags.read(path)[0].rating is None


@pytest.mark.slow
def test_musikatas_own_popm_scale_is_written_under_its_name_and_reads_back(audio, tmp_path):
    """R10.4.1's setting: the rating as MusiKata's own POPM (stars times 51) under the user
    MusiKata; Windows Media Player's, which a reader prefers, kept in step when the file has it;
    another program's left alone; cleared, MusiKata's says 0 while another's would read."""
    path = _copy(audio, "mp3", tmp_path)
    tags.save(path, {"rating": 4}, audio_hash=scanner.audio_hash, rating_scale="musikata")
    assert {p.email: p.rating for p in id3.ID3(path).getall("POPM")} == {"MusiKata": 204}
    assert tags.read(path)[0].rating == 4
    f = id3.ID3(path)
    f.add(id3.POPM(email=parse.WMP, rating=64, count=7))
    f.add(id3.POPM(email="MusicBee", rating=255))
    f.save(path)
    tags.save(path, {"rating": 3}, audio_hash=scanner.audio_hash, rating_scale="musikata")
    popms = {p.email: (p.rating, getattr(p, "count", 0)) for p in id3.ID3(path).getall("POPM")}
    assert popms == {"MusiKata": (153, 0), parse.WMP: (128, 7), "MusicBee": (255, 0)}
    assert tags.read(path)[0].rating == 3
    tags.save(path, {"rating": 0}, audio_hash=scanner.audio_hash, rating_scale="musikata")
    popms = {p.email: p.rating for p in id3.ID3(path).getall("POPM")}
    assert popms == {"MusiKata": 0, parse.WMP: 0, "MusicBee": 255}
    assert tags.read(path)[0].rating == 0


def _info_wav(path, *subs):
    with open(path, "rb") as f:
        data = bytearray(f.read())
    body = b"INFO"
    for sid, value in subs:
        n = len(value) + 1
        body += sid + n.to_bytes(4, "little") + value + b"\0" + b"\0" * (n & 1)
    data += b"LIST" + len(body).to_bytes(4, "little") + body
    data[4:8] = (len(data) - 8).to_bytes(4, "little")
    with open(path, "wb") as f:
        f.write(data)


@pytest.mark.slow
def test_a_wavs_info_chunk_is_kept_in_step_so_a_field_removed_stays_removed(audio, tmp_path):
    path = _copy(audio, "wav", tmp_path)
    _info_wav(path, (b"INAM", b"Breakwater"), (b"IART", b"Hollow Coast"), (b"ICRD", b"2023"),
              (b"ISFT", b"Lavf"))  # fmt: skip
    before_hash = scanner.audio_hash(path, "wav")
    save(path, title="Undertow", artist=None)
    t, _ = tags.read(path)
    assert (t.title, t.artist, t.year) == ("Undertow", None, 2023)
    with open(path, "rb") as f:
        info = parse.riff_info(f.read())
    assert info == {"INAM": "Undertow", "ICRD": "2023", "ISFT": "Lavf"}
    assert scanner.audio_hash(path, "wav") == before_hash
    with open(path, "rb") as f:
        head = f.read(8)
    assert int.from_bytes(head[4:], "little") == os.path.getsize(path) - 8


@pytest.mark.slow
@pytest.mark.parametrize("kind", ["flac", "vorbis", "opus", "aac"])
def test_the_cover_set_and_removed_keeps_the_other_pictures(audio, tmp_path, kind):
    path = _copy(audio, kind, tmp_path)
    back = Picture(4, "image/png", b"\x89PNG back")
    if kind == "aac":
        f = mutagen.mp4.MP4(path)
        f["covr"] = [mutagen.mp4.MP4Cover(b"\xff\xd8old"), mutagen.mp4.MP4Cover(b"\x89PNG back")]
        f.save()
    else:
        f = mutagen.File(path)
        pictures = []
        for p in (Picture(3, "image/jpeg", b"\xff\xd8old"), back):
            fp = mutagen.flac.Picture()
            fp.type, fp.mime, fp.data = p.type, p.mime, p.data
            pictures.append(fp)
        if kind == "flac":
            for fp in pictures:
                f.add_picture(fp)
        else:
            f["METADATA_BLOCK_PICTURE"] = [base64.b64encode(fp.write()).decode() for fp in pictures]
            f["COVERART"] = base64.b64encode(b"older").decode()
        f.save()
    new = cover(7)
    save(path, cover=new)
    got = tags.pictures(path)
    assert got[0].data == new.data and back.data in [p.data for p in got[1:]]
    assert b"\xff\xd8old" not in [p.data for p in got]
    if kind == "flac":
        p = mutagen.flac.FLAC(path).pictures[0]
        assert (p.width, p.height, p.depth) == (16, 16, 24)
    save(path, cover=None)
    assert new.data not in [p.data for p in tags.pictures(path)]
    assert back.data in [p.data for p in tags.pictures(path)]


def _with_pictures(path, kind, pictures, coverart=b""):
    """`pictures` embedded in the song at `path` as its kind holds them; for an Ogg file, the
    older COVERART too (`coverart`)."""
    if kind == "aac":
        f = mutagen.mp4.MP4(path)
        f["covr"] = [mutagen.mp4.MP4Cover(p.data) for p in pictures]
    elif kind in ("mp3", "wav", "aiff"):
        f = mutagen.File(path)
        if f.tags is None:
            f.add_tags()
        for n, p in enumerate(pictures):
            f.tags.add(
                id3.APIC(encoding=3, mime=p.mime, type=p.type, desc=p.desc or str(n), data=p.data)
            )
    else:
        f = mutagen.File(path)
        made = []
        for p in pictures:
            fp = mutagen.flac.Picture()
            fp.type, fp.mime, fp.data, fp.desc = p.type, p.mime, p.data, p.desc
            made.append(fp)
        if kind == "flac":
            for fp in made:
                f.add_picture(fp)
        else:
            f["METADATA_BLOCK_PICTURE"] = [base64.b64encode(fp.write()).decode() for fp in made]
        if coverart:
            f["COVERART"] = base64.b64encode(coverart).decode()
    f.save()


@pytest.mark.slow
@pytest.mark.parametrize("kind", ["mp3", "aiff", "flac", "vorbis", "opus", "aac"])
def test_the_other_pictures_removed_leave_the_cover_and_put_back_read_as_they_were(
    audio, tmp_path, kind
):
    """R5.3's Remove other embedded images, and its Undo: the back cover, the artist's photo (and
    an Ogg file's older COVERART) go, the front cover stays first; put back, each reads back with
    its type, and in ID3 and FLAC its description."""
    path = _copy(audio, kind, tmp_path)
    typed = kind != "aac"
    front = Picture(3 if typed else None, "image/jpeg", b"\xff\xd8front")
    back = Picture(4 if typed else None, "image/png", b"\x89PNG back", "Back")
    artist = Picture(8 if typed else None, "image/png", b"\x89PNG artist", "Band")
    older = b"\xff\xd8older" if kind in ("vorbis", "opus") else b""
    _with_pictures(path, kind, [back, front, artist] if typed else [front, back, artist], older)
    had = tags.pictures(path)
    others = tuple(compose.others_of(had, typed))
    written = save(path, others=())
    assert [p.data for p in tags.pictures(path)] == [front.data]
    assert written.changed == ("others",)
    assert {p.data for p in written.others_before} == {back.data, artist.data} | (
        {older} if older else set()
    )
    assert written.others_after == () and written.cover_before is None
    save(path, others=others)
    got = tags.pictures(path)
    assert got[0].data == front.data
    assert sorted((p.type or 0, p.data) for p in got[1:]) == sorted(
        (p.type or 0, p.data) for p in others
    )
    assert [p.type for p in got if p.data == older] == ([None] if older else [])
    if kind in ("mp3", "aiff", "flac"):
        assert {p.desc for p in got[1:]} >= {"Back", "Band"}


@pytest.mark.slow
def test_a_cover_and_the_others_written_at_once_leave_only_the_new_cover(audio, tmp_path):
    path = _copy(audio, "flac", tmp_path)
    _with_pictures(path, "flac", [Picture(3, "image/jpeg", b"\xff\xd8old"),
                                  Picture(4, "image/png", b"\x89PNG back")])  # fmt: skip
    written = save(path, cover=cover(), others=())
    assert [(p.type, p.data) for p in tags.pictures(path)] == [(3, cover().data)]
    assert written.cover_before.data == b"\xff\xd8old" and written.changed == ("cover", "others")


@pytest.mark.slow
def test_ogg_front_covers_in_comments_and_mp3_descriptions_never_collide(audio, tmp_path):
    """A FLAC whose cover is a comment gets it as a picture block; an MP3 whose back cover has no
    description keeps it, the new cover named apart."""
    path = _copy(audio, "flac", tmp_path)
    f = mutagen.flac.FLAC(path)
    fp = mutagen.flac.Picture()
    fp.type, fp.mime, fp.data = 3, "image/jpeg", b"\xff\xd8old"
    f["METADATA_BLOCK_PICTURE"] = [base64.b64encode(fp.write()).decode(), "not base64 at all!"]
    f.save()
    save(path, cover=cover())
    assert [(p.type, p.data) for p in tags.pictures(path)] == [(3, cover().data)]
    assert mutagen.flac.FLAC(path)["METADATA_BLOCK_PICTURE"] == ["not base64 at all!"]
    mp3 = _copy(audio, "mp3", tmp_path)
    t = id3.ID3()
    t.add(id3.APIC(encoding=3, mime="image/png", type=4, desc="", data=b"back"))
    t.save(mp3)
    save(
        mp3, others=(Picture(4, "image/png", b"back"), Picture(5, "", b"\x89PNG\r\n\x1a\nleaflet"))
    )
    descs = sorted(f.desc for f in id3.ID3(mp3).getall("APIC"))
    assert descs == ["", "Picture 2"]
    assert id3.ID3(mp3).getall("APIC")[1].mime == "image/png"  # a mime the picture lacked


@pytest.mark.slow
def test_a_back_cover_without_a_description_keeps_its_own_beside_the_new_cover(audio, tmp_path):
    path = _copy(audio, "mp3", tmp_path)
    f = id3.ID3()
    f.add(id3.APIC(encoding=3, mime="image/png", type=4, desc="", data=b"back"))
    f.save(path)
    save(path, cover=cover())
    assert [(p.type, p.data) for p in tags.pictures(path)] == [(3, cover().data), (4, b"back")]


@pytest.mark.slow
def test_replaygain_and_r128_gains_are_never_touched(audio, tmp_path):
    path = _copy(audio, "opus", tmp_path)
    f = mutagen.File(path)
    f["R128_TRACK_GAIN"], f["REPLAYGAIN_ALBUM_GAIN"] = "-3200", "-6.25 dB"
    f.save()
    save(path, title="Spore Theory", genres=["Ambient"])
    t, _ = tags.read(path)
    assert (t.rg_track_gain, t.rg_album_gain) == (-7.5, -6.25)


@pytest.mark.slow
@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    unknown=st.lists(
        st.tuples(
            st.text(
                st.characters(min_codepoint=0x41, max_codepoint=0x5A), min_size=1, max_size=8
            ).map(lambda k: f"X_{k}"),
            st.text(min_size=0, max_size=12).filter(lambda v: "\x00" not in v),
        ),
        max_size=6,
    )
)
def test_comments_a_write_doesnt_know_survive_it_in_order(audio, tmp_path, unknown):
    """A property: whatever fields MusiKata doesn't know (R4.1.1), a write keeps as they were."""
    path = _copy(audio, "vorbis", tmp_path)
    f = mutagen.File(path)
    f.tags.extend(unknown)
    f.save()
    save(path, title="Moss")
    kept = [(k, v) for k, v in mutagen.File(path).tags if k.startswith("X_")]
    assert kept == unknown


def test_the_writer_keeps_each_v24_frame_mutagens_update_to_v23_drops():
    """write.V24_ONLY holds the frames Mutagen's update_to_v23 drops, which the writer puts back."""
    texts = ("TSOP", "TSOA", "TSOT", "TSST", "TMOO", "TPRO", "TDRL", "TDTG", "TDEN")
    f = id3.ID3()
    for fid in texts:
        f.add(getattr(id3, fid)(encoding=3, text="2001"))
    f.update_to_v23()
    assert list(f.keys()) == []
    assert set(texts) <= set(tag_write.V24_ONLY)
    assert all(getattr(id3, fid, None) is not None for fid in tag_write.V24_ONLY)
