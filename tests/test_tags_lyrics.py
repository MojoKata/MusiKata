"""Lyrics (src/musikata_core/lyrics.py; the lyrics a song's tags hold, tags/parse.py, compose.py,
write.py; R17.1, R17.2, R17.5, R4.1.1, A7.6): LRC read in every shape it is written in, an `.lrc`'s
bytes in every encoding, where a song's lyrics come from, the line sung at a time, what saving
writes where R13.11's setting says, and the lyrics of every kind's tags read, written and kept.

Why: an `.lrc` is data from outside (testing.md, "Shapes": `lyrics`), written by a dozen editors,
players and sites, each its own way; one shape misread shows a song's lyrics out of step or not at
all, and a save that drops another program's lyrics loses them for good (R4.1.1)."""

import codecs
import os
import shutil
import sys

import mutagen
import mutagen.id3 as id3
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from musikata_core import lyrics, scanner, tags
from musikata_core.lyrics import Line
from musikata_core.tags import compose, parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

LRC = """[ar:Lumen Drift]
[ti:Signal Fires]
[00:12.00]Lanterns on the water line
[00:17.20]counting ships that never came
"""


def texts(found):
    return [(line.time, line.text) for line in found.lines]


# ---------- LRC (testing.md's `lyrics` shapes) ----------


def test_times_of_every_form_and_lrcs_own_tags_kept_apart_from_the_lines():
    found = lyrics.parse(
        "[ar: Lumen Drift ]\n[ti:Signal Fires]\n[al:Glass Harbor]\n[by:someone]\n"
        "[length: 04:18]\n[re:a player]\n[ve:1.0]\n[#:a comment]\n"
        "[00:12]whole seconds\n[00:13.5]a tenth\n[00:14.25]hundredths\n[00:15.125]thousandths\n"
        "[00:16:50]a colon before the hundredths\n[ 01 : 02 . 30 ]spaces inside\n"
        "[75:00.00]past an hour"
    )
    assert found.timed and not found.instrumental
    assert texts(found) == [
        (12.0, "whole seconds"), (13.5, "a tenth"), (14.25, "hundredths"),
        (15.125, "thousandths"), (16.5, "a colon before the hundredths"),
        (62.3, "spaces inside"), (4500.0, "past an hour"),
    ]  # fmt: skip
    assert dict(found.meta) == {
        "ar": "Lumen Drift", "ti": "Signal Fires", "al": "Glass Harbor", "by": "someone",
        "length": "04:18", "re": "a player", "ve": "1.0", "#": "a comment",
    }  # fmt: skip


def test_several_times_on_one_line_sing_it_at_each_and_lines_out_of_order_are_sorted():
    found = lyrics.parse("[00:40.00][01:20.00]chorus\n[00:30.00]verse\n[00:50.00]bridge")
    assert texts(found) == [(30.0, "verse"), (40.0, "chorus"), (50.0, "bridge"), (80.0, "chorus")]
    assert found.times() == [30.0, 40.0, 50.0, 80.0]


def test_an_offset_moves_every_line_sooner_or_later_and_one_that_isnt_a_number_nothing():
    assert lyrics.parse("[offset:+500]\n[00:10.00]a").lines == (Line("a", 9.5),)
    assert lyrics.parse("[offset: -250 ]\n[00:10.00]a").lines == (Line("a", 10.25),)
    assert lyrics.parse("[offset:soon]\n[00:10.00]a").lines == (Line("a", 10.0),)
    assert lyrics.parse("[offset:20000]\n[00:10.00]a").lines == (Line("a", 0.0),)  # not before 0
    assert dict(lyrics.parse("[offset:soon]\n[00:10.00]a").meta) == {"offset": "soon"}


def test_word_times_are_read_and_taken_out_of_the_line_shown_whole():
    found = lyrics.parse("[00:01.00]<00:01.00>every <00:01.60>shore<00:02.00> a  <00:02.40>sign")
    assert texts(found) == [(1.0, "every shore a sign")]
    assert texts(lyrics.parse("[00:01.00]words<00:03.00>")) == [(1.0, "words")]  # its end time


def test_blank_untimed_and_empty_timed_lines_in_timed_lyrics():
    """A blank line is passed by, a line with no time (a credit) left out, and a time with no
    text a pause between verses."""
    found = lyrics.parse("\n[00:01.00]one\n\nLyrics by somebody\n[00:05.00]\n[00:09.00]two\n\n")
    assert texts(found) == [(1.0, "one"), (5.0, ""), (9.0, "two")]
    assert not found.empty


def test_a_bom_crlf_and_cr_line_ends_read_as_lines():
    assert texts(lyrics.parse("﻿[00:01.00]a\r\n[00:02.00]b\r[00:03.00]c")) == [
        (1.0, "a"), (2.0, "b"), (3.0, "c")
    ]  # fmt: skip


def test_plain_lyrics_keep_their_verses_and_headings_that_arent_lrcs_tags():
    found = lyrics.parse(
        "\n\n[Verse 1: Ana]\nLanterns on the water line  \n\n\n\n[Chorus]\nWe were signal fires\n\n"
    )
    assert not found.timed and found.times() == []
    assert [line.text for line in found.lines] == [
        "[Verse 1: Ana]", "Lanterns on the water line", "", "[Chorus]", "We were signal fires"
    ]  # fmt: skip
    assert all(line.time is None for line in found.lines)


def test_lrcs_own_tags_alone_are_no_lyrics():
    for text in ("", "   \n\n", "[ar:Lumen Drift]\n[ti:Signal Fires]", "[00:01.00]\n[00:02.00]"):
        assert lyrics.parse(text).empty


@pytest.mark.parametrize(
    "text",
    ["Instrumental", "[Instrumental]", "(instrumental)", "*Instrumental*", "♪ Instrumental ♪",
     "♪", "[00:00.00]Instrumental", "[00:00.00]♪\n[01:00.00]♫ ♫"],
)  # fmt: skip
def test_lyrics_that_only_say_instrumental_mark_the_song_so(text):
    assert lyrics.parse(text).instrumental


def test_a_line_saying_instrumental_among_others_or_dots_alone_dont():
    assert not lyrics.parse("[00:01.00]Instrumental\n[00:20.00]then words").instrumental
    assert not lyrics.parse("...").instrumental and not lyrics.is_mark("Instrumentals")


def test_very_many_lines_read_in_their_order():
    text = "\n".join(f"{lyrics.time_tag(n * 0.5)}line {n}" for n in reversed(range(5000)))
    found = lyrics.parse(text)
    assert len(found.lines) == 5000 and found.lines[0].text == "line 0"
    assert found.lines[-1] == Line("line 4999", 2499.5)


@given(st.text())
@example("[")
@example("[00:")
@example("[offset:]\n[00:00.00]")
@example("[99999999:00.00]x")
def test_any_text_parses_and_never_raises(text):
    found = lyrics.parse(text)
    assert all(isinstance(line.text, str) for line in found.lines)
    if found.timed:
        assert found.times() == sorted(found.times()) and all(t >= 0 for t in found.times())


@given(st.lists(st.tuples(st.floats(0, 5999, allow_nan=False), st.text("ab ,'", min_size=1))))
@example(
    [(1.055, "a")]
)  # 105.50000000000001 hundredths: written as 1.06, though round(t, 2) is 1.05
def test_timed_lines_written_as_lrc_read_back_at_their_times(entries):
    entries = [(t, " ".join(words.split())) for t, words in entries if words.split()]
    found = lyrics.parse(lyrics.lrc_of(entries))
    assert [(round(t * 100) / 100, w) for t, w in sorted(entries, key=lambda e: e[0])] == [
        (pytest.approx(line.time, abs=0.006), line.text) for line in found.lines
    ]


# ---------- the line sung, and times ----------


def test_the_line_sung_is_the_last_one_started_and_none_before_the_first():
    times = [10.0, 20.0, 20.0, 30.0]
    assert lyrics.current(times, 0.0) == -1 and lyrics.current(times, 9.99) == -1
    assert lyrics.current(times, 10.0) == 0 and lyrics.current(times, 25.0) == 2
    assert lyrics.current(times, 999.0) == 3 and lyrics.current([], 5.0) == -1


def test_a_time_is_written_as_lrc_writes_it_to_the_hundredth():
    assert lyrics.time_tag(105.2) == "[01:45.20]" and lyrics.time_tag(0) == "[00:00.00]"
    assert lyrics.time_tag(59.999) == "[01:00.00]" and lyrics.time_tag(-3) == "[00:00.00]"
    assert lyrics.time_tag(6000.0) == "[100:00.00]"


def test_sylt_lines_are_lrc_texts_times_in_milliseconds_and_plain_lyrics_have_none():
    assert lyrics.sylt_of("[00:01.50]a\n[00:00.25]b\n[00:02.00]") == [("b", 250), ("a", 1500),
                                                                       ("", 2000)]  # fmt: skip
    assert lyrics.sylt_of("plain words") is None and lyrics.sylt_of(None) is None


def test_lyrics_as_a_tag_holds_them_line_ends_and_blanks_made_one_way():
    assert lyrics.tag_text("  a\r\nb\rc\x00\n\n") == "a\nb\nc"
    assert lyrics.tag_text(" \n ") is None and lyrics.tag_text(None) is None
    assert lyrics.tag_text(5) is None


# ---------- an .lrc's bytes ----------


@pytest.mark.parametrize(
    "data",
    [
        codecs.BOM_UTF8 + "[00:01.00]Маяк".encode(),
        codecs.BOM_UTF16_LE + "[00:01.00]Маяк".encode("utf-16-le"),
        codecs.BOM_UTF16_BE + "[00:01.00]Маяк".encode("utf-16-be"),
        codecs.BOM_UTF32_LE + "[00:01.00]Маяк".encode("utf-32-le"),
        "[00:01.00]Маяк".encode("utf-16-le"),  # no BOM: a NUL beside every other byte
        "[00:01.00]Маяк".encode("utf-16-be"),
        "[00:01.00]Маяк".encode(),
    ],
)
def test_an_lrcs_bytes_read_by_their_bom_as_utf_16_without_one_and_as_utf_8(data):
    assert lyrics.decode(data) == "[00:01.00]Маяк"


def test_an_lrc_that_isnt_utf_8_is_read_in_the_systems_legacy_encoding():
    assert lyrics.decode("[00:01.00]Déjà vu – “là”".encode("cp1252")) == "[00:01.00]Déjà vu – “là”"
    assert lyrics.decode("[00:01.00]Маяк".encode("cp1251"), "cp1251") == "[00:01.00]Маяк"
    assert lyrics.decode(b"\x81\x8d", "cp1252") == "\x81\x8d"  # what cp1252 hasn't: Latin-1
    assert lyrics.decode(b"\xe9", "no such encoding") == "é"


@given(st.binary())
def test_any_bytes_decode_and_never_raise(data):
    assert isinstance(lyrics.decode(data), str)


def test_an_lrc_is_written_as_utf_8_with_lf_line_ends():
    assert (
        lyrics.lrc_bytes("[00:01.00]Маяк\r\n[00:02.00]b\r\n")
        == "[00:01.00]Маяк\n[00:02.00]b\n".encode()
    )


# ---------- where they come from (R17.1) ----------


def test_the_lrc_beside_a_song_is_named_as_it_is_its_extension_in_any_case(tmp_path):
    song = tmp_path / "04 - Signal Fires.flac"
    song.write_bytes(b"")
    assert lyrics.lrc_path(str(song)) == str(tmp_path / "04 - Signal Fires.lrc")
    assert lyrics.find_lrc(str(song)) is None
    (tmp_path / "04 - Signal Fires (live).lrc").write_text("x")  # another song's
    (tmp_path / "04 - signal fires.lrc").write_text("x")  # another name, in this case
    assert lyrics.find_lrc(str(song)) is None
    (tmp_path / "04 - Signal Fires.LRC").write_text("x")
    assert lyrics.find_lrc(str(song)) == str(tmp_path / "04 - Signal Fires.LRC")
    (tmp_path / "04 - Signal Fires.lrc").write_text("x")
    assert lyrics.find_lrc(str(song)) == str(tmp_path / "04 - Signal Fires.lrc")
    assert lyrics.find_lrc(str(tmp_path / "gone" / "song.mp3")) is None  # can't be listed


def test_an_lrc_that_cant_be_read_is_none(tmp_path):
    assert lyrics.read_lrc(str(tmp_path / "gone.lrc")) is None
    (tmp_path / "a.lrc").write_bytes(b"words")
    assert lyrics.read_lrc(str(tmp_path / "a.lrc")) == b"words"


def test_the_lrc_comes_first_then_the_tags_and_one_holding_nothing_is_none():
    """R17.1: the `.lrc` beside the song, then its tags; an `.lrc` of blanks or LRC's own tags
    alone gives way to the tags."""
    found = lyrics.choose(("/m/04.lrc", codecs.BOM_UTF8 + LRC.encode()), "plain words")
    assert found is not None and found.source == lyrics.FILE and found.name == "04.lrc"
    assert found.lyrics.timed and found.text == LRC.strip()
    assert lyrics.source_text(found) == "Timed · from 04.lrc"
    found = lyrics.choose(("/m/04.lrc", b"[ar:x]\r\n\r\n"), "plain words")
    assert found is not None and found.source == lyrics.TAGS and found.name == ""
    assert lyrics.source_text(found) == "Plain · from the song's tags"
    found = lyrics.choose(None, "[00:01.00]LRC in a plain tag")
    assert found is not None and found.lyrics.timed  # counts as timed
    assert lyrics.choose(None, None) is None and lyrics.choose(("/m/a.lrc", b""), " ") is None


# ---------- what saving writes (R17.4, R17.5, R13.11) ----------


def test_saving_writes_where_the_setting_says_and_into_an_lrc_the_song_has():
    data = b"[00:01.00]a\n"
    assert lyrics.saving("lrc", "[00:01.00]a", False, True) == lyrics.Saving(
        True, False, data, "[00:01.00]a"
    )  # fmt: skip
    assert lyrics.saving("tags", "[00:01.00]a", False, False) == lyrics.Saving(
        False, True, data, "[00:01.00]a"
    )  # fmt: skip
    assert lyrics.saving("tags", "a", True, False) == lyrics.Saving(True, True, b"a\n", "a")
    assert lyrics.saving("both", "a", False, False) == lyrics.Saving(True, True, b"a\n", "a")
    assert lyrics.saving("?", "a", False, False).file  # a setting not known: the default's place


def test_saving_no_text_removes_them_from_where_they_are():
    assert lyrics.saving("lrc", " \n", True, True) == lyrics.Saving(True, True, None, None)
    assert lyrics.saving("both", "", False, True) == lyrics.Saving(False, True, None, None)
    assert lyrics.saving("lrc", "", False, False) == lyrics.Saving(False, False, None, None)


# ---------- in the tags (R17.1, A7.6) ----------


def test_id3s_timed_uslt_wins_then_a_sylt_in_milliseconds_then_a_plain_uslt():
    assert parse.id3_lyrics(["plain", "[00:01.00]timed"]) == "[00:01.00]timed"
    sylt = [(1, [("in frames", 400)]), (2, [("\nb", 2500), ("a", 1000), (" ", 3000)])]
    assert parse.id3_lyrics(["plain"], sylt) == "[00:01.00]a\n[00:02.50]b"
    assert parse.id3_lyrics([" ", "plain", "other"], [(1, [("in frames", 400)])]) == "plain"
    assert parse.id3_lyrics([], []) is None


def test_vorbis_lyrics_under_each_name_a_timed_one_first_and_mp4s_lyr():
    assert parse.from_vorbis({"LYRICS": ["plain"]}).lyrics == "plain"
    assert parse.from_vorbis({"UNSYNCEDLYRICS": ["words\r\nmore"]}).lyrics == "words\nmore"
    found = parse.from_vorbis({"LYRICS": ["plain"], "SYNCEDLYRICS": ["[00:01.00]a"]})
    assert found.lyrics == "[00:01.00]a"
    assert parse.from_vorbis({}).lyrics is None
    assert parse.from_mp4({"\xa9lyr": ["[00:01.00]a"]}).lyrics == "[00:01.00]a"


def test_a_change_of_lyrics_is_text_or_none_to_remove_them():
    assert compose.normalize({"lyrics": " a\r\nb "}) == {"lyrics": "a\nb"}
    assert compose.normalize({"lyrics": ""}) == {"lyrics": None}
    with pytest.raises(ValueError):
        compose.normalize({"lyrics": ["a"]})
    assert compose.vorbis({"lyrics": "a"}, tags.Tags()) == {
        "LYRICS": ["a"], "SYNCEDLYRICS": [], "UNSYNCEDLYRICS": []
    }  # fmt: skip
    assert compose.mp4({"lyrics": None}, tags.Tags()) == {"\xa9lyr": None}
    assert compose.id3_lyrics({"lyrics": "[00:01.00]a"}) == ("[00:01.00]a", [("a", 1000)])
    assert compose.id3_lyrics({"lyrics": None}) == (None, None)


@pytest.fixture(scope="module")
def audio(tmp_path_factory):
    """One untagged file of each kind, made once: {kind: path}."""
    d = tmp_path_factory.mktemp("audio")
    out = {}
    for kind, (ext, *_rest) in demo.KINDS.items():
        out[kind] = str(d / f"{kind}.{ext}")
        demo.encode(out[kind], kind, 0.2, 440)
    return out


def copy(audio, kind, tmp_path):
    path = str(tmp_path / os.path.basename(audio[kind]))
    shutil.copyfile(audio[kind], path)
    return path


def save(path, version="2.4", **changes):
    return tags.save(path, changes, audio_hash=scanner.audio_hash, id3_version=version)


@pytest.mark.parametrize("kind", list(demo.KINDS))
def test_each_kind_holds_lyrics_written_timed_or_plain_and_none_once_removed(audio, kind, tmp_path):
    """A7.6: ID3's USLT with SYLT for timed lyrics, in ID3v2.4 and 2.3; Vorbis' LYRICS; MP4's
    ©lyr; read back as written, and removed."""
    path = copy(audio, kind, tmp_path)
    for version in ("2.4", "2.3"):
        timed = "[00:01.00]Lanterns on the water line\n[00:02.50]counting ships\n[00:04.00]"
        assert save(path, version, lyrics=timed).changed == ("lyrics",)
        assert tags.read(path)[0].lyrics == timed
        if kind in compose.ID3_KINDS:
            f = mutagen.File(path)
            (sylt,) = f.tags.getall("SYLT")
            assert [(t, ms) for t, ms in sylt.text][:2] == [("Lanterns on the water line", 1000),
                                                            ("counting ships", 2500)]  # fmt: skip
        assert save(path, version, lyrics="plain\n\nwords").changed == ("lyrics",)
        assert tags.read(path)[0].lyrics == "plain\n\nwords"
        if kind in compose.ID3_KINDS:
            assert mutagen.File(path).tags.getall("SYLT") == []
        assert save(path, version, lyrics=None).changed == ("lyrics",)
        assert tags.read(path)[0].lyrics is None
        assert save(path, version, lyrics=None).changed == ()  # nothing to write


def test_other_programs_lyrics_are_read_and_a_write_of_other_fields_keeps_them(audio, tmp_path):
    """R17.1 and R4.1.1: an MP3's SYLT alone (another program's), several USLTs, a FLAC's
    UNSYNCEDLYRICS in lower case and an M4A's ©lyr are read, and a save of the title keeps every
    one of them as it was."""
    mp3 = copy(audio, "mp3", tmp_path)
    f = mutagen.File(mp3)
    f.tags.add(id3.SYLT(encoding=3, lang="eng", format=2, type=1, desc="",
                        text=[("Lanterns", 1000), ("ships", 2500)]))  # fmt: skip
    f.tags.add(id3.USLT(encoding=1, lang="deu", desc="de", text="Laternen"))
    f.save()
    assert tags.read(mp3)[0].lyrics == "[00:01.00]Lanterns\n[00:02.50]ships"
    flac = copy(audio, "flac", tmp_path)
    f = mutagen.File(flac)
    f["unsyncedlyrics"] = "plain words"
    f.save()
    assert tags.read(flac)[0].lyrics == "plain words"
    m4a = copy(audio, "aac", tmp_path)
    f = mutagen.File(m4a)
    f["\xa9lyr"] = ["[00:01.00]a"]
    f.save()
    assert tags.read(m4a)[0].lyrics == "[00:01.00]a"
    for path in (mp3, flac, m4a):
        save(path, "2.3", title="Signal Fires")
    f = mutagen.File(mp3)
    assert [(t, ms) for t, ms in f.tags.getall("SYLT")[0].text] == [("Lanterns", 1000),
                                                                    ("ships", 2500)]  # fmt: skip
    assert [str(u) for u in f.tags.getall("USLT")] == ["Laternen"]
    assert mutagen.File(flac)["unsyncedlyrics"] == ["plain words"]
    assert mutagen.File(m4a)["\xa9lyr"] == ["[00:01.00]a"]
    assert tags.read(mp3)[0].lyrics == "[00:01.00]Lanterns\n[00:02.50]ships"
