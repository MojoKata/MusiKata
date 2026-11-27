"""Text in the wrong encoding (src/musikata_core/encodings.py, and Tags.latin1 as read.py reads it
and compose and write.py write it; R4.10, A3.6): Latin-1 text read under each candidate and scored,
a song flagged when another candidate reads it far better, the readings ranked as T06 lists them,
the plan of a fix, and the bytes a fix takes and Undo puts back.

Why: a song flagged wrongly would ask the user to "fix" real French or German, and a fix written
wrongly would lose what the tags said; the scoring is plain logic, so it is tested on generated text
of every script and on real text of the languages Latin-1 holds, and the files' bytes are checked
as they are written and put back."""

import os
import random
import sys

import mutagen.id3 as id3
import mutagen.wave
import pytest
from fakes import wav
from hypothesis import example, given
from hypothesis import strategies as st

from musikata_core import encodings, scanner
from musikata_core import tags as tags_core
from musikata_core.encodings import AS_IS, CANDIDATES, likely, readings
from musikata_core.tags import Tags, compose
from musikata_core.tags.tools import Song

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402


def latin1(text, codec):
    """Text saved in `codec` and read as Latin-1, as an old tagger's shows: Êèíî for Кино."""
    return text.encode(codec).decode("latin-1")


def keys(values):
    return [r.candidate.key for r in readings(values)]


# ---------- generated text of each script (R4.10's candidates) ----------

# words of the languages each candidate writes; a phrase starts with a word of letters Latin-1
# hasn't, as a song's title in that language would hold some
WORDS = {
    "cp1251": [
        # Russian, Ukrainian, Belarusian, Bulgarian, Serbian, Macedonian
        "кино", "группа", "крови", "звезда", "солнце", "ветер", "северный", "гавань", "тихая",
        "маяк", "дорога", "песня", "город", "ночь", "любовь", "время", "небо", "море", "память",
        "осень", "зима", "огни", "свет", "сердце", "жизнь", "пісня", "їжак", "мрія", "світло",
        "калина", "червона", "щастя", "сэрца", "вецер", "крыніца", "ўсход", "песен", "нощ",
        "сърце", "щастие", "љубав", "ноћ", "ђурђевдан", "песма", "њива", "ћуприја", "љубов",
        "ноќ", "ѕвезда", "ѓердан",
    ],
    "cp1253": [
        "καλημέρα", "αγάπη", "θάλασσα", "νύχτα", "τραγούδι", "ζωή", "ήλιος", "φεγγάρι", "καρδιά",
        "όνειρο", "δρόμος", "πόλη", "ουρανός", "μουσική", "χορός", "Ελλάδα", "αγαπώ", "Ζορμπάς",
        "Θεοδωράκης",
    ],
    "cp1250": [
        # Polish, Czech, Slovak, Hungarian, Romanian, Croatian
        "żółć", "gęślą", "jaźń", "łąka", "miłość", "pieśń", "źródło", "śnieg", "księżyc",
        "słońce", "Łódź", "příliš", "žluťoučký", "kůň", "úpěl", "ďábelské", "řeka", "hvězda",
        "město", "světlo", "Dvořák", "ľúbosť", "kňaz", "árvíztűrő", "tükörfúrógép", "őszi",
        "hűség", "ţară", "şoaptă", "noć", "čežnja", "šuma", "žena", "đurđevdan",
    ],
    "cp932": [
        "ありがとう", "東京", "事変", "宇多田", "ヒカル", "君の名は", "残酷な天使のテーゼ",
        "ポケモン", "夜明け", "さくら", "花火", "海", "空", "夢", "歌", "心", "雨", "星",
    ],
    "gbk": [
        "中文", "歌曲", "周杰伦", "月亮", "代表", "我的心", "王菲", "红豆", "青花瓷", "东风破",
        "爱", "夜曲", "稻香", "晴天", "时间", "城市", "朋友", "你好", "北京", "故事",
    ],
    "cp950": [
        "周杰倫", "月亮", "代表", "我的心", "鄧麗君", "紅豆", "青花瓷", "東風破", "愛", "夜曲",
        "稻香", "晴天", "時間", "城市", "朋友", "你好", "台北", "故事",
    ],
}  # fmt: skip
KEY = {"cp1251": "cyrillic", "cp1253": "greek", "cp1250": "central", "cp932": "japanese",
       "gbk": "chinese", "cp950": "chinese"}  # fmt: skip


# Central European letters Latin-1 holds no letter at: Windows-1250's bytes of them read as Latin-1
# are marks (ł as ³, ż as ¿, ť as a control character); the rest read as letters some language
# has (ő as õ, ř as ø), which letters alone can't tell from real Latin-1
UNLIKE_LATIN1 = frozenset("łążŁĄŻťŤŹľĽşŞ")


def phrases(codec, n=40, seed=7):
    """`n` phrases of one to four words of `codec`'s languages, as titles are: the first word one
    that holds a letter Latin-1 hasn't (Central European's: one it reads as no letter),
    capitalised now and then."""
    rng = random.Random(seed)
    words = WORDS[codec]
    if codec == "cp1250":
        marked = [w for w in words if UNLIKE_LATIN1 & set(w)]
    else:
        marked = [w for w in words if not all(ch <= "\xff" for ch in w)]
    out = []
    for _ in range(n):
        chosen = [rng.choice(marked)] + [rng.choice(words) for _ in range(rng.randrange(4))]
        if rng.random() < 0.5:
            chosen = [w[:1].upper() + w[1:] for w in chosen]
        out.append(" ".join(chosen))
    return out


@pytest.mark.parametrize("codec", list(WORDS))
def test_generated_text_of_each_script_is_flagged_and_read_its_own_way_first(codec):
    """A3.6: text of each script saved in its encoding and read as Latin-1 reads far better
    under that encoding than as it is: it is flagged, that reading the best (R4.10), and nearly
    always first; GBK's and Big5's are told apart."""
    first = 0
    for phrase in phrases(codec):
        values = [latin1(phrase, codec)]
        found = likely(values)
        assert found is not None, phrase
        mine = next(r for r in readings(values) if r.codec == codec)
        assert mine.texts == (phrase,) and mine.score == found.score, phrase
        first += (found.candidate.key, found.codec) == (KEY[codec], codec)
    # a short phrase may read as well another way (Żółć as Big5's 草單): both are offered, the
    # user chooses; most read best their own way
    assert first >= 0.9 * len(phrases(codec))


def test_central_european_read_as_letters_latin_1_has_reads_as_it_is():
    """The limit of letters alone: Windows-1250's ő, ű, ř, ě read as Latin-1's õ, û, ø, ì make
    words a language could write, so Hungarian or Czech of only those isn't flagged; either way
    both readings are offered, as it is first."""
    for word in ("Hűség", "světlo", "őszi řeka"):
        values = [latin1(word, "cp1250")]
        assert likely(values) is None
        assert keys(values)[:2] == [AS_IS, "central"]


def test_several_fields_are_read_together_as_one_program_saved_them():
    """A song's Latin-1 fields are scored together: a title alone too short to tell is flagged
    with its artist and album."""
    values = [latin1(t, "cp1251") for t in ("Северный Ветер", "Тихая Гавань", "Маяк")]
    found = likely(values)
    assert found is not None and found.texts == ("Северный Ветер", "Тихая Гавань", "Маяк")


# ---------- real text of the languages Latin-1 holds: never flagged ----------

# real titles and names, as they are written, each saved in Windows' Western (Latin-1 and its
# quotes); Polish, Czech and Turkish by the letters of theirs Latin-1 has
REAL = {
    "French": ["L'été indien", "Où êtes-vous ?", "Ça plane pour moi", "Noël", "Je ne regrette "
               "rien", "Les Misérables", "Œuvres complètes", "Naïve", "À la claire fontaine",
               "Été", "Ô Canada", "Où", "à", "Façade", "Sinéad", "Beyoncé", "Queensrÿche"],
    "German": ["Für Elise", "Größe", "Bärenstraße", "Mötley Crüe", "Hüsker Dü", "Über den "
               "Wolken", "Schön ist die Welt", "Grüße aus München", "Süß", "Fußball", "Ärzte",
               "Blue Öyster Cult", "Motörhead"],
    "Spanish": ["Señor", "¿Dónde estás?", "Mañana", "¡Olé!", "Canción", "Pájaros en la cabeza",
                "El niño", "Corazón", "Bésame mucho", "Guantanamera", "Pingüino"],
    "Portuguese": ["Coração", "Ação", "Corações", "São Paulo", "Atenção", "Garota de Ipanema",
                   "Águas de março", "Saudade", "Não", "Mãe", "Você é linda", "Irmãos"],
    "Polish": ["Kraków", "Góry", "Mazurek", "Polonez", "Bóg", "Ósma", "Król", "Jak góral"],
    "Czech": ["Má vlast", "Slovanské tance", "Rusalka", "Láska", "Bílá", "Tichý", "Ó, Praho",
              "Vánoce", "Já"],
    "Turkish": ["Gönül", "Çiçek", "Köprü", "Gül", "Üsküdar", "Kâtibim", "Gözlerin", "Söz",
                "Türkü", "Bülbül"],
    "Icelandic": ["Björk Guðmundsdóttir", "Sigur Rós – Ágætis byrjun", "Þú", "Ég", "Hjaltalín",
                  "Ísland", "Þjóð", "Æðið", "Fjölnir", "Sjálfstæðisflokkurinn", "Ölgerð",
                  "Íþróttir", "Hoppípolla", "Svefn-g-englar"],
    "Others": ["Røyksopp", "Ångström", "Smörgåsbord", "Café del Mar", "Don’t Stop", "Rock ’n’ "
               "Roll", "Live at the Lantern – 2016", "Sinfonía nº 9", "1ª parte", "E=mc²",
               "© 2003", "Col·lecció", "Live · 2003"],
}  # fmt: skip


@pytest.mark.parametrize("language", list(REAL))
def test_real_text_of_latin_1s_languages_is_never_flagged(language):
    """A3.6: real French, German, Spanish, Portuguese, Polish, Czech, Turkish and Icelandic in
    Latin-1 (Windows' Western) read as they are: no candidate reads them far better, and as it
    is comes first. Their accented letters stand alone, or in pairs their language has."""
    for title in REAL[language]:
        values = [latin1(title, "cp1252")]
        assert likely(values) is None, title
        assert keys(values)[0] == AS_IS
        assert readings(values)[0].texts == (title,)
    every = [latin1(t, "cp1252") for t in REAL[language]]
    assert likely(every) is None  # a song's fields read together


def test_the_mockups_example_and_t06s_readings():
    """R4.10's example (Êèíî for Кино), and T06's song: Cyrillic first and most likely, then as it
    is, Central European, and those that can't read it: Greek, Japanese, Chinese."""
    assert likely(["Êèíî"]).texts == ("Кино",)
    values = [latin1(t, "cp1251") for t in ("Северный Ветер", "Тихая Гавань", "Маяк")]
    found = readings(values)
    assert [(r.label, r.readable) for r in found] == [
        ("Cyrillic (Windows-1251)", True),
        ("As it is (Latin-1)", True),
        ("Central European (Windows-1250)", True),
        ("Greek (Windows-1253)", False),
        ("Japanese (Shift-JIS)", False),
        ("Chinese (GBK, Big5)", False),
    ]
    assert found[1].texts == ("Ñåâåðíûé Âåòåð", "Òèõàÿ Ãàâàíü", "Ìàÿê")
    assert found[2].texts == ("Ńĺâĺđíűé Âĺňĺđ", "Ňčőŕ˙ Ăŕâŕíü", "Ěŕ˙ę")


# ---------- shapes (docs/process/testing.md, "Shapes", `encodings`) ----------


def test_mixed_scripts_short_text_and_numbers_or_punctuation_alone():
    """A title of Latin and Cyrillic words is flagged for its Cyrillic; two letters are enough,
    one isn't (`1º` reads as `1є`, `½` as `Ѕ`); numbers and punctuation alone have no letters
    to judge by."""
    assert likely([latin1("Live in Москва", "cp1251")]).texts == ("Live in Москва",)
    assert likely([latin1("Мы", "cp1251")]) is not None
    for text in ("1º", "½", "1999", "© 2003 – ½", "…", "“”"):
        assert likely([latin1(text, "cp1252")]) is None, text
    assert encodings.score("1999 – …", AS_IS) is None


def test_windows_quotes_in_a_latin_1_frame_read_as_they_are():
    """Bytes 0x80 to 0x9F in a Latin-1 frame are Windows' quotes and dashes, as other programs
    write them; the five Windows has nothing for stay as Latin-1 has them."""
    data = "Don’t – “Stop”".encode("cp1252")
    assert encodings.as_is(data) == "Don’t – “Stop”"
    assert encodings.as_is(bytes([0x81, 0x41, 0x9D])) == "\x81A\x9d"
    assert encodings.decode(bytes([0xFF]), "cp1253") is None
    assert encodings.read_with(["Кино"], "cp1251") is None  # not Latin-1's text


def test_chinese_reads_with_gbk_or_big5_and_is_named_for_the_one():
    simplified = readings([latin1("青花瓷 周杰伦", "gbk")])[0]
    traditional = readings([latin1("青花瓷 周杰倫", "cp950")])[0]
    assert (simplified.codec, simplified.label) == ("gbk", "Chinese (GBK)")
    assert (traditional.codec, traditional.label) == ("cp950", "Chinese (Big5)")
    assert encodings.label_of("cp950") == "Chinese (Big5)"
    assert encodings.label_of("cp1251") == "Cyrillic (Windows-1251)"
    assert encodings.label_of("koi8-r") == "koi8-r"


def test_a_capital_after_a_small_letter_or_a_letter_no_language_pairs_spoils_a_word():
    def good_bad(text, codec):
        t = encodings.tally(text, codec)
        return t.good, t.bad

    for word in ("ÌàÿÊ", "Ñåâåð", "îâå", "Gr\x8fn"):
        good, bad = good_bad(word, encodings.CP1252)
        assert bad and not good, word
    assert good_bad("McCartney iPhone", encodings.CP1252) == (15, 0)
    assert good_bad("ДДТ", "cp1251") == (3, 0)  # letters said one by one
    assert good_bad("взгляд", "cp1251") == (6, 0)
    assert good_bad("бгбрфх", "cp1251") == (0, 6)
    assert good_bad("ИЬлбууб", "cp1251") == (0, 7)  # ь after a vowel: Greek's Θάλασσα
    assert good_bad("σοφός", "cp1253") == (5, 0)
    assert good_bad("ςοφόσ", "cp1253") == (0, 5)
    assert good_bad("Ga³ka", encodings.CP1252) == (0, 4 + encodings.ODD_WEIGHT)


def test_scripts_no_candidate_makes_read_as_they_are_and_wide_marks_part_words():
    assert encodings.script_of("한") == "other"
    assert encodings.tally("한국", "cp1252").good == 2
    assert encodings.tally("ﾖﾐ", "cp932").bad == 4  # halfwidth katakana: Shift-JIS misread
    assert encodings.tally("東京、大阪「夜」", "cp932").good == 10
    assert encodings.tally("Ž–•Ï", encodings.CP1252).good == 0  # 事変 as Windows' Western


@given(st.binary(max_size=40))
@example(b"\xca\xe8\xed\xee")
@example(bytes(range(128, 256)))
def test_any_bytes_are_read_by_every_candidate_or_said_unreadable(data):
    """Whatever a Latin-1 frame holds: six readings, as it is always among them, each score
    between -1 and 1 or none, and the flag one of the candidates' codecs or none."""
    text = data.decode("latin-1")
    found = readings([text])
    assert len(found) == len(CANDIDATES) and any(r.candidate.key == AS_IS for r in found)
    assert all(r.score is None or -1 <= r.score <= 1 for r in found)
    codecs = {c for k in CANDIDATES for c in k.codecs}
    flagged = encodings.flag(Tags(title=text, latin1=("title",)))
    assert flagged is None or flagged in codecs


# ---------- the plan of a fix (R4.10) ----------

T06 = ("Северный Ветер", "Тихая Гавань", "Маяк")


def song(path, title, artist="Северный Ветер", album="Тихая Гавань", codec="cp1251",
         plain=()):  # fmt: skip
    values = {"title": title, "artist": artist, "album": album}
    held = {k: (v if k in plain else latin1(v, codec)) for k, v in values.items()}
    names = tuple(f for f in compose.TEXT if f in held and f not in plain
                  and not held[f].isascii())  # fmt: skip
    return Song(path, Tags(**held, latin1=names))


def test_a_plan_reads_each_songs_latin_1_fields_and_lists_the_songs_it_writes_first():
    songs = [song("/m/01.mp3", "Утро"), Song("/m/02.mp3", Tags(title="Plain")),
             song("/m/08.mp3", "Маяк")]  # fmt: skip
    planned = encodings.plan(songs, "cp1251")
    assert planned.columns == ("artist", "album", "title")
    assert [s.path for s in planned.songs] == ["/m/01.mp3", "/m/08.mp3", "/m/02.mp3"]
    assert [planned.new[i].title for i in range(3)] == ["Утро", "Маяк", "Plain"]
    assert planned.changed(2) == ()
    job = planned.jobs({0, 1, 2})[1]
    assert job.changes == {"artist": "Северный Ветер", "album": "Тихая Гавань", "title": "Маяк"}


def test_as_it_is_writes_the_same_text_as_unicode_and_a_field_that_cant_be_read_stays():
    """Choosing as it is writes the text unchanged, as Unicode, so it needs no attention any more;
    a field the encoding chosen can't read is left as it is, out of the change."""
    planned = encodings.plan([song("/m/01.mp3", "Маяк")], encodings.CP1252)
    assert planned.changed(0) == ("artist", "album", "title")
    assert planned.new[0] == planned.songs[0].tags
    greek = encodings.plan([song("/m/01.mp3", "Νύχτα", artist="Ζορμπάς", codec="cp1253",
                                 album="Ελλάδα")], "cp1253")  # fmt: skip
    assert greek.new[0].artist == "Ζορμπάς"
    tags, names = encodings.fixed(song("/m/01.mp3", "Тихая").tags, "cp1253")  # Т: none in Greek
    assert "title" not in names and "artist" in names


# ---------- in the files: Latin-1 read, fixed and its bytes put back ----------


def tagged(path, frames, version=3, encoding=0):
    """A WAV whose ID3 tag holds `frames` (id: text) in `encoding` (0: Latin-1, the text as
    given standing for its bytes), as ID3v2.`version`."""
    wav(path, 3)
    f = mutagen.wave.WAVE(str(path))
    f.add_tags()
    for fid, text in frames.items():
        if fid == "COMM":
            f.tags.add(id3.COMM(encoding=encoding, lang="eng", desc="", text=[text]))
        else:
            f.tags.add(getattr(id3, fid)(encoding=encoding, text=text))
    f.save(v2_version=version)
    return str(path)


def frames_of(path):
    """Each text frame of the file as (encoding, its text's bytes as that encoding holds them)."""
    t = mutagen.wave.WAVE(path).tags
    out = {}
    for frame in t.values():
        if frame.FrameID in ("TIT2", "TPE1", "TALB", "COMM"):
            enc = int(frame.encoding)
            codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}[enc]
            out[frame.FrameID] = (enc, str(frame.text[0]).encode(codec))
    return out


T06_FRAMES = {
    "TIT2": latin1("Маяк", "cp1251"), "TPE1": latin1("Северный Ветер", "cp1251"),
    "TALB": latin1("Тихая Гавань", "cp1251"), "COMM": latin1("Запись 1999", "cp1251"),
}  # fmt: skip


@pytest.mark.parametrize("version", [3, 4])
def test_text_held_as_latin_1_is_said_and_flagged_in_id3v23_and_v24(tmp_path, version):
    """A3.6: an ID3 frame marked Latin-1 holds its bytes as Mutagen decodes them, a character a
    byte; read says which fields are held so (the comment's frame too), whatever the tag's
    version, and the song is flagged."""
    path = tagged(tmp_path / "a.wav", T06_FRAMES, version)
    t, _ = tags_core.read(path)
    assert t.latin1 == ("title", "artist", "album", "comment")
    assert encodings.raw(t.title) == "Маяк".encode("cp1251")
    assert encodings.flag(t) == "cp1251"


def test_unicode_frames_and_latin_1_ascii_are_never_checked(tmp_path):
    """Already-Unicode frames, and Latin-1 frames of ASCII alone, have no encoding to doubt."""
    path = tagged(tmp_path / "u.wav", {"TIT2": "Маяк", "TPE1": "Lumen Drift"}, 4, encoding=3)
    t, _ = tags_core.read(path)
    assert (t.latin1, encodings.flag(t)) == ((), None)
    path = tagged(tmp_path / "a.wav", {"TIT2": "Signal Fires", "TPE1": "Lumen Drift"})
    assert tags_core.read(path)[0].latin1 == ()
    assert Tags(title="x", latin1=("title",)) == Tags(title="x")  # not a field


def save(path, changes):
    return tags_core.save(path, changes, audio_hash=scanner.audio_hash, id3_version="2.3")


def test_a_fix_is_written_as_unicode_and_undo_writes_the_old_bytes_back(tmp_path):
    """R4.10: the reading chosen is written as Unicode; writing the old values asked as Latin-1
    (Undo's, compose.LATIN1) puts back the very bytes the file held, each frame marked Latin-1."""
    path = tagged(tmp_path / "a.wav", T06_FRAMES)
    before = frames_of(path)
    t, _ = tags_core.read(path)
    fixed, names = encodings.fixed(t, "cp1251")
    w = save(path, {n: getattr(fixed, n) for n in names})
    assert (w.tags.title, w.tags.latin1, w.before.latin1) == ("Маяк", (), t.latin1)
    assert {k: v[0] for k, v in frames_of(path).items()} == dict.fromkeys(before, 1)
    assert encodings.flag(w.tags) is None
    back = save(path, {**{n: getattr(t, n) for n in names}, "latin1": list(t.latin1)})
    assert back.tags.latin1 == t.latin1
    assert frames_of(path) == before


def test_as_it_is_rewrites_the_same_text_as_unicode_and_latin1_asked_of_ascii_is_unicode(
    tmp_path,
):
    path = tagged(tmp_path / "a.wav", {"TIT2": "Café", "TPE1": latin1("Маяк", "cp1251")})
    t, _ = tags_core.read(path)
    w = save(path, {"title": "Café"})
    assert w.changed == ("title",) and w.tags.latin1 == ("artist",)
    assert frames_of(path)["TIT2"] == (1, "Café".encode("utf-16"))
    assert save(path, {"title": "Café"}).changed == ()  # Unicode already: nothing to write
    w = save(path, {"title": "Plain", "latin1": ["title"]})
    assert w.tags.latin1 == ("artist",) and frames_of(path)["TIT2"][0] == 1


@pytest.mark.slow
def test_latin1_asked_of_a_kind_without_id3_is_passed_by(tmp_path):
    """Vorbis comments and MP4 atoms are Unicode: asking for Latin-1 there writes Unicode."""
    path = str(tmp_path / "a.flac")
    demo.encode(path, "flac", 0.1, 440)
    w = tags_core.save(path, {"title": "Café", "latin1": ["title"]}, audio_hash=scanner.audio_hash)
    assert w.tags.title == "Café" and w.tags.latin1 == ()


def test_latin1_is_a_list_of_text_fields():
    assert compose.normalize({"latin1": ["title", "comment"]}) == {"latin1": ("title", "comment")}
    for bad in ("title", ["year"], 5):
        with pytest.raises(ValueError):
            compose.normalize({"latin1": bad})
    assert compose.latin1_of(
        {"title": "Кино", "artist": "Ìàÿê", "latin1": ("title", "artist")}
    ) == ("artist",)
    assert not compose.latin1_text(None) and not compose.latin1_text("abc")


@pytest.mark.slow
def test_an_id3v1_tags_text_is_latin_1_too_and_a_fix_writes_it_as_id3v2(tmp_path):
    """An MP3 with an ID3v1 tag alone: Mutagen reads it as frames marked Latin-1, so it is
    checked as they are; a fix adds an ID3v2 tag in Unicode, the ID3v1 kept in step (R4.7.2)."""
    path = str(tmp_path / "a.mp3")
    demo.encode(path, "mp3", 0.2, 440)

    def field(text, n):
        return text.encode("cp1251").ljust(n, b"\0")

    v1 = (b"TAG" + field("Маяк", 30) + field("Северный Ветер", 30) + field("Тихая Гавань", 30)
          + b"2009" + b"\0" * 30 + b"\xff")  # fmt: skip
    with open(path, "ab") as f:
        f.write(v1)
    t, _ = tags_core.read(path)
    assert t.latin1 == ("title", "artist", "album") and encodings.flag(t) == "cp1251"
    fixed, names = encodings.fixed(t, "cp1251")
    w = tags_core.save(path, {n: getattr(fixed, n) for n in names}, audio_hash=scanner.audio_hash)
    assert (w.tags.title, w.tags.latin1) == ("Маяк", ())
