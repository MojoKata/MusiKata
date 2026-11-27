"""Needs attention's groups (src/musikata_core/attention.py; R2.8, R5.6, R9.5, A2.6): what each
group holds, the name-normalising rule, the `.cue` sheet of an album in one file, the covers'
sizes, Ignore's match, and the merge of an artist's or an album's names; and the columns the scan
keeps for them, so the groups are found by queries over the index, never a pass over the files.

Why: the count in the sidebar must say what is there to fix now, after every scan, at 50,000 songs;
an entry the user dismissed must stay dismissed, wherever the song was moved, until its file
changes; and a `.cue` sheet is data from outside (testing.md, "Shapes": `attention`), written by
every ripper its own way."""

import os
from concurrent.futures import ThreadPoolExecutor

import mutagen.id3
import mutagen.wave
import pytest
from fakes import wav
from hypothesis import given
from hypothesis import strategies as st

from musikata_core import art, attention, db, rootfiles, scanner
from musikata_core.attention import AlbumSong, Entry
from musikata_core.rootfiles import Dismissal
from musikata_core.tags import AudioInfo, Picture, Tags
from musikata_core.tags.tools import Song

H1, H2 = "1" * 64, "2" * 64
T1 = "2026-11-26T21:00:00Z"


def jpeg(w, h):
    """A JPEG's header (SOI, then a baseline frame header with its size): what art.sniff reads."""
    sof = b"\xff\xc0\x00\x11\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03"
    return b"\xff\xd8" + sof + b"\x01\x11\x00" * 3 + b"\xff\xda scan"


# ---------- names (R2.8, R9.5) ----------


def test_names_that_differ_only_in_case_or_spacing_share_a_key():
    """R2.8: "Lumen Drift", "lumen drift", "LUMEN  DRIFT", " LumenDrift " are one name; a letter
    and its mark (NFD, as macOS names files) are the letter; accents and punctuation stay."""
    keys = {attention.name_key(n) for n in ("Lumen Drift", "lumen drift", "LUMEN  DRIFT",
                                             " LumenDrift ", "Lumen\tDrift")}  # fmt: skip
    assert keys == {"lumendrift"}
    assert attention.name_key("Beyonce\u0301") == attention.name_key("Beyoncé") == "beyoncé"
    assert attention.name_key("Beyonce") != attention.name_key("Beyoncé")
    assert attention.name_key("Hip-Hop") != attention.name_key("Hip Hop")
    assert attention.name_key("Straße") == attention.name_key("STRASSE")
    assert attention.name_key("Шансон") == attention.name_key("шансон")
    assert attention.name_key(None) is None and attention.name_key("  ") is None


@given(st.text(max_size=40))
def test_any_name_has_one_key_whatever_its_case_and_spaces(name):
    key = attention.name_key(name)
    assert key == attention.name_key(f"  {name.upper()} ") or key == attention.name_key(
        name.lower()
    )
    assert key is None or (key and not any(ch.isspace() for ch in key))


def test_an_albums_name_is_its_album_artists_and_titles_keys_together():
    """A2.6's normalised pair: two artists' albums of one title are apart; a song with no album
    artist uses its artist (R2.5.2)."""
    pair = attention.album_pair("Glass Harbor", "Lumen Drift", "Someone")
    assert pair == attention.album_pair("glass  harbor", "LUMEN DRIFT", None)
    assert pair == attention.album_pair("GlassHarbor", None, "Lumen Drift")
    assert pair != attention.album_pair("Glass Harbor", "Mara Okafor", None)
    assert (
        attention.album_pair(None, "A", "B") is None
        and attention.album_pair(" ", "A", None) is None
    )
    assert attention.album_pair("X", None, None) == "\0x"


# ---------- an album's songs (R2.8, R5.6) ----------


def test_an_albums_songs_differ_in_each_field_or_none():
    base = AlbumSong("Glass Harbor", "Lumen Drift", 2019, ("Electronic",), True, H1)
    assert attention.differs([base]) == ()  # one song: nothing to differ
    assert attention.differs([base, base]) == ()
    assert attention.differs(
        [base, AlbumSong("glass harbor", "Lumen Drift", 2019, ("Electronic",), True, H1)]
    ) == ("album",)
    assert attention.differs([base, AlbumSong("Glass Harbor ", None, None, ("Electronica",),
                                              False, None)]) == (
        "albumartist", "year", "genre", "cover"
    )  # fmt: skip
    assert attention.differs([base, AlbumSong("Glass Harbor", "Lumen Drift", 2019,
                                              ("Electronic", "Ambient"), True, H2)]) == (
        "genre", "cover"
    )  # fmt: skip
    unknown = AlbumSong("A", None, None, (), True, None)  # covers not yet known: the same
    assert attention.differs([unknown, unknown]) == ()


def test_a_cover_under_500_a_side_is_small_and_one_of_no_known_size_isnt():
    """R5.6: smaller than 500 × 500."""
    assert attention.small(300, 300) and attention.small(1200, 499)
    assert not attention.small(500, 500) and not attention.small(None, 200)
    assert attention.small(600, 600, min_side=1000)


def test_an_embedded_covers_hash_and_size_come_from_its_front_picture():
    back, front = (
        Picture(4, "image/jpeg", jpeg(1400, 1400)),
        Picture(3, "image/jpeg", jpeg(300, 200)),
    )
    key, w, h = attention.cover_of([back, front])
    assert (key, w, h) == (art.key_of(front.data), 300, 200)
    assert attention.cover_of([Picture(3, "", b"not an image")])[1:] == (None, None)
    assert attention.cover_of([]) is None


def test_a_folders_cover_image_is_measured_once_from_its_header(tmp_path):
    """R5.6: the walk's images; one the index has the size of isn't read again; one that can't be
    read is passed by."""
    reads = []

    def head(path):
        reads.append(os.path.relpath(path, tmp_path).replace(os.sep, "/"))
        if "Gone" in path:
            raise OSError("gone")
        return jpeg(300, 300)

    images = {
        "A": [art.Image("back.png", 9, 1), art.Image("cover.jpg", 10, 2)],
        "B": [art.Image("folder.jpg", 10, 3)],
        "": [art.Image("cover.jpg", 10, 4)],
        "Gone": [art.Image("cover.jpg", 10, 5)],
        "None": [],
    }
    known = {("B/folder.jpg", 10, 3): (1200, 1200)}
    assert attention.measure(str(tmp_path), images, known, head) == 3
    assert images["A"][1] == art.Image("cover.jpg", 10, 2, 300, 300)
    assert images["A"][0].width is None  # not the cover
    assert images["B"] == [art.Image("folder.jpg", 10, 3, 1200, 1200)]
    assert images[""][0].width == 300 and images["Gone"][0].width is None
    assert sorted(reads) == ["A/cover.jpg", "Gone/cover.jpg", "cover.jpg"]
    assert attention.measure(str(tmp_path), images, {}, head) == 1  # Gone's: still unknown


# ---------- an album in one file (A2.6) ----------

CUE = """REM GENRE Soul
REM DATE 2016
PERFORMER "Mara Okafor"
TITLE "Live at the Lantern"
FILE "Live at the Lantern.mp3" MP3
  TRACK 01 AUDIO
    TITLE "Ember"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Lanternlight"
    INDEX 00 04:58:12
    INDEX 01 05:00:00
"""


def test_a_cue_sheet_names_its_file_quoted_or_not_and_passes_by_the_rest():
    """Shapes: FILE with and without quotes, REM lines, INDEX 00 and 01, a path a ripper wrote
    before the name, CRLF, lower case, a file named twice."""
    assert attention.cue_files(CUE) == ["Live at the Lantern.mp3"]
    assert attention.cue_files("FILE Live.wav WAVE\r\nTRACK 01 AUDIO\r\n") == ["Live.wav"]
    assert attention.cue_files('file "C:\\Rips\\Live.flac" WAVE') == ["Live.flac"]
    assert attention.cue_files('FILE "a/b/Live.flac" WAVE\nFILE "a/b/Live.flac" WAVE') == [
        "Live.flac"
    ]
    assert attention.cue_files('FILE "One.wav" WAVE\nFILE "Two.wav" WAVE') == ["One.wav", "Two.wav"]
    assert attention.cue_files('FILE\nFILE "" WAVE\nREM FILE x\nFILENAME y') == []
    assert attention.cue_files("FILE Live") == ["Live"]


def test_a_cue_sheet_is_read_in_utf_8_or_the_systems_encoding():
    """Shapes: UTF-8 with and without its BOM, and cp1252 as Windows' rippers write it."""
    text = 'FILE "Café Nocturne.flac" WAVE'
    assert attention.decode_cue(text.encode("utf-8")) == text
    assert attention.decode_cue(b"\xef\xbb\xbf" + text.encode("utf-8")) == text
    assert attention.decode_cue(text.encode("cp1252")) == text
    assert attention.decode_cue(b"\x81\x8d") == "\x81\x8d"  # neither: Latin-1


@given(st.binary(max_size=200))
def test_any_bytes_at_all_are_a_cue_sheets_text_and_its_files_never_an_error(data):
    names = attention.cue_files(attention.decode_cue(data))
    assert all(n and "/" not in n for n in names)


def test_a_cue_sheet_stands_for_the_one_file_it_names():
    """A2.6: by its name, in any case, else without its extension (a sheet written for the WAV a
    FLAC was made from); one naming no file is the file of its own name; one naming several is of
    tracks already apart; each file once, the first sheet's."""
    audio = ["01 Ember.mp3", "Live at the Lantern.MP3", "Studio.flac", "Other.flac"]
    sheets = {
        "Live at the Lantern.cue": CUE,
        "Studio.cue": 'FILE "Studio.wav" WAVE',
        "Other.cue": "REM only remarks",
        "Tracks.cue": 'FILE "01 Ember.mp3" MP3\nFILE "02 Glow.mp3" MP3',
        "Elsewhere.cue": 'FILE "Nowhere.wav" WAVE',
        "Again.cue": 'FILE "Studio.flac" WAVE',
    }
    assert attention.cued(sheets, audio) == {
        "Live at the Lantern.MP3": "Live at the Lantern.cue",
        "Studio.flac": "Again.cue",
        "Other.flac": "Other.cue",
    }
    assert attention.cued({"a.cue": 'FILE "x.flac" WAVE'}, ["x.flac", "X.FLAC"]) == {
        "x.flac": "a.cue"
    }


def test_the_sheets_beside_the_songs_name_them_and_one_that_cant_be_read_is_passed_by():
    texts = {"Live/Live.cue": 'FILE "Live.mp3" MP3', "Root.cue": 'FILE "Root.flac" WAVE'}

    def read(path):
        rel = path.replace(os.sep, "/").removeprefix("/music/")
        if rel not in texts:
            raise OSError("gone")
        return texts[rel]

    cues = {"Live": [art.Image("Live.cue", 1, 1), art.Image("Broken.cue", 1, 1)],
            "": [art.Image("Root.cue", 1, 1)], "None": []}  # fmt: skip
    audio = ["Live/Live.mp3", "Live/Broken.mp3", "Root.flac", "None/x.mp3", "Elsewhere/y.mp3"]
    assert attention.cued_in("/music", cues, audio, read) == {"Live/Live.mp3": "Live.cue",
                                                             "Root.flac": "Root.cue"}  # fmt: skip


# ---------- the scan keeps the columns ----------


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def scan(music, index, scope=None):
    with ThreadPoolExecutor(1) as pool:
        return scanner.scan(str(music), index, pool, scope=scope, hold=False)


def embed(path, data):
    f = mutagen.wave.WAVE(str(path))
    if f.tags is None:
        f.add_tags()
    f.tags.add(mutagen.id3.TALB(encoding=3, text="Live"))
    f.tags.add(mutagen.id3.APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=data))
    f.save()


def test_the_scan_keeps_the_names_covers_and_cue_sheets_needs_attention_finds(index, tmp_path):
    """A2.6: what the groups are found from is the scan's to keep, for the folders it walks: each
    song's names' keys, its embedded cover's hash and size, the sheet beside it; each album's
    fields that differ and its cover's size; a folder's cover image measured once."""
    music = tmp_path / "Music"
    wav(music / "Live" / "Live.wav", 1, "Live")
    embed(music / "Live" / "Live.wav", jpeg(300, 300))
    (music / "Live" / "Live.cue").write_text('FILE "Live.wav" WAVE\n', encoding="utf-8")
    wav(music / "Folder" / "a.wav", 2, "A")
    (music / "Folder" / "cover.jpg").write_bytes(jpeg(1200, 800))
    scan(music, index)
    c = index.read()
    row = c.execute("SELECT artist_nk, album_nk, cover_key, cover_width, cover_height, cue FROM"
                    " song WHERE path = 'Live/Live.wav'").fetchone()  # fmt: skip
    assert row == (None, "\0live", art.key_of(jpeg(300, 300)), 300, 300, "Live.cue")
    assert c.execute("SELECT cover_width, cover_height, differs FROM album").fetchone() == (
        300, 300, None
    )  # fmt: skip
    assert attention.known_sizes(c) == {}  # Folder's songs are on no album: no row keeps it
    (music / "Live" / "Live.cue").unlink()
    scan(music, index, scanner.Scope(frozenset({"Live"}), {"Live": str(music / "Live")}))
    assert c.execute("SELECT cue FROM song WHERE path = 'Live/Live.wav'").fetchone() == (None,)


def test_an_albums_folder_image_gives_its_cover_size_and_isnt_read_again(
    index, tmp_path, monkeypatch
):
    music = tmp_path / "Music"
    for n in (1, 2):
        wav(music / "Album" / f"{n}.wav", n, f"Song {n}")
        f = mutagen.wave.WAVE(str(music / "Album" / f"{n}.wav"))
        f.tags.add(mutagen.id3.TALB(encoding=3, text="Album"))
        f.tags.add(mutagen.id3.TYER(encoding=3, text=str(2000 + n)))
        f.save()
    (music / "Album" / "cover.jpg").write_bytes(jpeg(450, 450))
    scan(music, index)
    c = index.read()
    assert c.execute("SELECT cover_kind, cover_width, cover_height, folder_image_width, differs"
                     " FROM album").fetchone() == ("file", 450, 450, 450, "year")  # fmt: skip
    st_ = os.stat(music / "Album" / "cover.jpg")
    assert attention.known_sizes(c) == {
        ("Album/cover.jpg", st_.st_size, st_.st_mtime_ns): (450, 450)
    }
    reads = []
    monkeypatch.setattr(attention, "_read_head", lambda p: reads.append(p) or b"")
    scan(music, index)
    assert reads == []  # known: not read again
    found = attention.find(c)
    assert [(e.kind, e.about, e.width) for e in found] == [
        ("cover-small", "Album", 450), ("album-differs", "Album", None)
    ]  # fmt: skip


def test_a_save_that_changes_the_cover_keeps_its_new_hash_and_one_that_doesnt_the_old(index):
    """A2.4: the rows of MusiKata's own writes come from what was written."""
    info = AudioInfo("flac", 60.0, 900, 44100, 2)
    first = scanner.Read(scanner.Seen("A/1.flac", 1, 1), Tags(album="A", has_cover=True), info,
                         H1, cover=("k1", 300, 300))  # fmt: skip
    index.write(lambda c: scanner.write_batch(c, [first], {})).result()
    from musikata_core.tags import Written

    same = Written("/m/A/1.flac", Tags(album="A", title="T", has_cover=True), info, H1, 2, 2,
                   changed=("title",))  # fmt: skip
    index.write(lambda c: scanner.wrote(c, "/m", [same])).result()
    c = index.read()
    assert c.execute("SELECT cover_key, cover_width FROM song").fetchone() == ("k1", 300)
    new = Picture(3, "image/jpeg", jpeg(800, 800))
    changed = Written("/m/A/1.flac", Tags(album="A", has_cover=True), info, H1, 3, 3,
                      changed=("cover",), cover_after=new)  # fmt: skip
    index.write(lambda c: scanner.wrote(c, "/m", [changed])).result()
    assert c.execute("SELECT cover_key, cover_width FROM song").fetchone() == (
        art.key_of(new.data),
        800,
    )
    gone = Written("/m/A/1.flac", Tags(album="A"), info, H1, 4, 4, changed=("cover",))
    index.write(lambda c: scanner.wrote(c, "/m", [gone])).result()
    assert c.execute("SELECT cover_key, cover_width FROM song").fetchone() == (None, None)


def test_cue_sheets_set_and_unset_for_the_folders_walked_only(index):
    rows = [scanner.Read(scanner.Seen(p, 1, 1), Tags(title=p), AudioInfo("mp3", 1500.0, 1, 1, 1),
                         p) for p in ("A/x.mp3", "B/y.mp3")]  # fmt: skip
    index.write(lambda c: scanner.write_batch(c, rows, {})).result()
    assert (
        index.write(
            lambda c: attention.set_cues(c, {"A", "B"}, {"A/x.mp3": "x.cue", "B/y.mp3": "y.cue"})
        ).result()
        == 2
    )
    assert index.write(lambda c: attention.set_cues(c, {"A"}, {})).result() == 1  # B not walked
    c = index.read()
    assert c.execute("SELECT path, cue FROM song ORDER BY path").fetchall() == [
        ("A/x.mp3", None), ("B/y.mp3", "y.cue")
    ]  # fmt: skip
    assert index.write(lambda c: attention.set_cues(c, {"B"}, {"B/y.mp3": "y.cue"})).result() == 0


# ---------- the groups ----------


def put(index, songs):
    """Rows as a scan writes them: each (path, tags, cover (hash, width, height) or None, length,
    error)."""
    batch = []
    for path, tags, cover, length, error in songs:
        info = AudioInfo("flac", length, 900, 44100, 2) if error is None else None
        seen = scanner.Seen(path, 10, 2_000_000_000)
        read_ = (scanner.Read(seen, tags, info, path, None, cover) if error is None
                 else scanner.Read(seen, error=error))  # fmt: skip
        batch.append(read_)
    index.write(lambda c: scanner.write_batch(c, batch, {})).result()


LIBRARY = [
    # Glass Harbor: one song names no album artist, has another cover and another year
    ("LD/GH/01.flac", Tags(title="Tidewater", artist="Lumen Drift", albumartist="Lumen Drift",
                           album="Glass Harbor", year=2019, genres=("Electronic",),
                           has_cover=True), (H1, 1200, 1200), 200.0, None),
    ("LD/GH/02.flac", Tags(title="Glass", artist="lumen drift", album="Glass Harbor", year=2019,
                           genres=("Electronic",), has_cover=True), (H1, 1200, 1200), 200.0, None),
    ("LD/GH/03.flac", Tags(title="Small", artist="Lumen Drift", albumartist="Lumen Drift",
                           album="glass harbor", year=2020, genres=("electronic",),
                           has_cover=True), (H2, 300, 300), 200.0, None),
    # Salt & Ember: one song, a small cover; Kindling: none; its spelling with two spaces
    ("MO/SE/01.flac", Tags(title="Lanternlight", artist="Mara Okafor", album="Salt & Ember",
                           genres=("soul",), has_cover=True), (H2, 300, 300), 200.0, None),
    ("MO/K/01.flac", Tags(title="Kindling", artist="Mara Okafor", album="Kindling",
                          genres=("Soul",)), None, 200.0, None),
    ("MO/K/02.flac", Tags(title="Glow", artist="Mara Okafor", album="Kindling  ",
                          genres=("Soul",)), None, 200.0, None),
    # an album in one file, and a file that couldn't be read
    ("MO/Live/Live.flac", Tags(title="Live", artist="Mara Okafor", album="Live at the Lantern",
                               genres=("Soul",), has_cover=True), (H1, 1200, 1200), 3600.0, None),
    ("MO/broken.mp3", None, None, 0.0, "can't sync to MPEG frame"),
]  # fmt: skip


@pytest.fixture
def library(index):
    put(index, LIBRARY)
    index.write(lambda c: attention.set_cues(c, {"MO/Live"}, {"MO/Live/Live.flac": "Live.cue"}))
    index.write(
        lambda c: c.execute("UPDATE song SET cue = 'Short.cue' WHERE path = 'MO/K/01.flac'")
    ).result()
    return index


def test_every_group_holds_what_needs_attention_in_order(library):
    """R2.8, R5.6, R9.5, A2.6: each kind its group, in KINDS' order."""
    got = attention.find(library.read())
    assert [(e.kind, e.about, e.title) for e in got] == [
        ("cover-none", "MO/K", "Kindling"),
        ("cover-small", "MO/SE", "Salt & Ember"),
        ("names-artist", "Lumen Drift", "Lumen Drift"),
        ("names-album", "Glass Harbor", "Glass Harbor"),
        ("names-album", "Kindling", "Kindling"),
        ("names-genre", "Soul", "Soul"),
        ("names-genre", "Electronic", "Electronic"),
        ("album-differs", "LD/GH", "Glass Harbor"),
        ("album-in-one-file", "MO/Live/Live.flac", "Live at the Lantern"),
        ("unreadable", "MO/broken.mp3", "MO/broken.mp3"),
    ]
    by = {(e.kind, e.about): e for e in got}
    assert by[("cover-small", "MO/SE")].width == 300 and by[("cover-none", "MO/K")].thumb is None
    artist = by[("names-artist", "Lumen Drift")]
    assert artist.names == ("Lumen Drift", "lumen drift") and artist.counts == (2, 1)
    assert artist.key == "lumendrift"
    album = by[("names-album", "Glass Harbor")]
    assert album.names == ("Glass Harbor", "glass harbor") and album.artist == "Lumen Drift"
    assert by[("names-genre", "Soul")].names == ("Soul", "soul")
    differs = by[("album-differs", "LD/GH")]
    assert differs.fields == ("album", "albumartist", "year", "genre", "cover")
    assert differs.modified == 2.0 and differs.album is not None
    live = by[("album-in-one-file", "MO/Live/Live.flac")]
    assert (live.cue, live.length, live.hash, live.artist) == (
        "Live.cue", 3600.0, "MO/Live/Live.flac", "Mara Okafor"
    )  # fmt: skip
    broken = by[("unreadable", "MO/broken.mp3")]
    assert broken.error == "can't sync to MPEG frame" and broken.hash is None
    # Kindling and "Kindling  " are one album, their title stripped (R2.5.2), and their names
    # differ in spacing: Merge makes them one spelling
    assert by[("names-album", "Kindling")].names == ("Kindling", "Kindling  ")
    assert not any(e.kind == "album-differs" and e.about == "MO/K" for e in got)


def test_genres_the_user_said_are_the_same_are_a_names_entry_and_covers_take_the_setting(library):
    got = attention.find(library.read(), same=[["Electronic", "Ambient"]], min_side=200)
    assert not any(e.kind == "cover-small" for e in got)
    put(library, [("X/1.flac", Tags(title="x", genres=("Ambient",)), None, 1.0, None)])
    got = attention.find(library.read(), same=[["Electronic", "Ambient"]])
    genre = next(e for e in got if e.kind == "names-genre" and e.about == "Electronic")
    assert genre.names == ("Electronic", "Ambient", "electronic")


# ---------- Ignore (R2.8) ----------


def test_a_dismissed_entry_stays_dismissed_until_its_file_changes(library):
    """R2.8: Ignore keeps the kind, what it is about and the file's modification time; a change
    to the file brings the entry back."""
    c = library.read()
    got = attention.find(c)
    broken = next(e for e in got if e.kind == "unreadable")
    live = next(e for e in got if e.kind == "album-in-one-file")
    small = next(e for e in got if e.kind == "cover-small")
    names = next(e for e in got if e.kind == "names-artist")
    kept = [attention.dismissal_of(e, T1) for e in (broken, live, small, names)]
    assert kept[0] == Dismissal("unreadable", "MO/broken.mp3", None, 2.0, T1)
    assert kept[1].hash == "MO/Live/Live.flac" and kept[3] == Dismissal(
        "names-artist", "Lumen Drift", None, None, T1
    )
    library.write(lambda c: rootfiles.load_ignored(c, kept)).result()
    left = attention.find(c, rootfiles.dismissals(c))
    assert {(e.kind, e.about) for e in got} - {(e.kind, e.about) for e in left} == {
        (e.kind, e.about) for e in (broken, live, small, names)
    }
    library.write(lambda c: c.execute("UPDATE song SET mtime_ns = 3000000000 WHERE path IN"
                                      " ('MO/broken.mp3', 'MO/SE/01.flac')")).result()  # fmt: skip
    back = attention.find(c, rootfiles.dismissals(c))
    assert {(e.kind, e.about) for e in back} - {(e.kind, e.about) for e in left} == {
        ("unreadable", "MO/broken.mp3"), ("cover-small", "MO/SE")
    }  # fmt: skip


def test_a_songs_dismissal_follows_it_moved_by_its_hash_and_a_name_by_its_key():
    """A2.8: by path, else by audio hash when no song has that path; a name's dismissal holds
    for its spellings in any case or spacing."""
    moved = Entry("album-in-one-file", "New/Live.flac", hash=H1, modified=5.0)
    copy = Entry("album-in-one-file", "Copy/Live.flac", hash=H1, modified=5.0)
    names = Entry("names-artist", "LUMEN DRIFT", names=("LUMEN DRIFT", "lumen drift"))
    album = Entry("cover-none", "LD/GH", modified=7.0)
    kept = [Dismissal("album-in-one-file", "Old/Live.flac", H1, 5.0, T1),
            Dismissal("names-artist", "Lumen Drift", None, None, T1),
            Dismissal("cover-none", "LD/GH", None, None, T1)]  # fmt: skip
    assert attention.dismissed([moved, names, album], kept) == []
    assert attention.dismissed([moved, copy], kept, present={"Old/Live.flac"}) == [moved, copy]
    assert attention.dismissed([Entry("unreadable", "Old/Live.flac", hash=H1)], kept) == [
        Entry("unreadable", "Old/Live.flac", hash=H1)
    ]  # another kind
    assert attention.dismissed([Entry("names-artist", "Mara", names=("Mara", "mara"))], kept)


def test_the_paths_dismissals_name_that_songs_still_have(library):
    c = library.read()
    kept = [Dismissal("unreadable", "MO/broken.mp3", None, 1.0, T1),
            Dismissal("unreadable", "Gone/x.mp3", H1, 1.0, T1),
            Dismissal("names-genre", "MO/K/01.flac", None, None, T1)]  # fmt: skip
    assert attention.present_of(c, kept) == {"MO/broken.mp3"}


# ---------- Merge (R2.8) ----------


def test_the_songs_a_names_entry_names_are_read_for_its_merge(library):
    c = library.read()
    got = attention.songs_of(c, "names-artist", "lumendrift")
    assert [(p, t.artist, t.albumartist) for p, t in got] == [
        ("LD/GH/01.flac", "Lumen Drift", "Lumen Drift"), ("LD/GH/02.flac", "lumen drift", None),
        ("LD/GH/03.flac", "Lumen Drift", "Lumen Drift"),
    ]  # fmt: skip
    album = next(e for e in attention.find(c) if e.kind == "names-album")
    assert [p for p, _ in attention.songs_of(c, "names-album", album.key)] == [
        "LD/GH/01.flac", "LD/GH/02.flac", "LD/GH/03.flac"
    ]  # fmt: skip
    with pytest.raises(ValueError, match="no merge"):
        attention.songs_of(c, "names-genre", "soul")


def test_merging_names_puts_the_chosen_one_in_every_field_that_has_another_changed_first():
    """R2.8's Merge: as artist and album artist for an artist, as album for an album; the songs
    that change first (R3.7)."""
    songs = [Song("/m/1.flac", Tags(artist="Lumen Drift", albumartist="Lumen Drift")),
             Song("/m/2.flac", Tags(artist="lumen drift", albumartist=None)),
             Song("/m/3.flac", Tags(artist="Mara", albumartist="lumen drift"))]  # fmt: skip
    planned = attention.merge_names(songs, "names-artist", ["lumen drift"], "Lumen Drift")
    assert planned.columns == ("artist", "albumartist")
    assert [s.path for s in planned.songs] == ["/m/2.flac", "/m/3.flac", "/m/1.flac"]
    assert [(t.artist, t.albumartist) for t in planned.new] == [
        ("Lumen Drift", None), ("Mara", "Lumen Drift"), ("Lumen Drift", "Lumen Drift")
    ]  # fmt: skip
    assert planned.jobs({0, 1, 2})[1].changes == {"albumartist": "Lumen Drift"}
    album = attention.merge_names([Song("/m/1.flac", Tags(album="glass harbor"))], "names-album",
                                  ["glass harbor", "Glass Harbor"], "Glass Harbor")  # fmt: skip
    assert album.columns == ("album",) and album.new[0].album == "Glass Harbor"
    with pytest.raises(ValueError, match="no merge"):
        attention.merge_names(songs, "names-genre", ["x"], "y")


# ---------- tags in the wrong text encoding (R4.10, A3.6) ----------


def cp1251(text):
    """Windows-1251 read as Latin-1, as an old tagger's tags read (Ìàÿê for Маяк)."""
    return text.encode("cp1251").decode("latin-1")


def misread(title, artist="Северный Ветер", album="Тихая Гавань", track=None):
    return Tags(title=cp1251(title), artist=cp1251(artist), album=cp1251(album), track=track,
                latin1=("title", "artist", "album"))  # fmt: skip


def test_a_song_in_the_wrong_encoding_is_an_entry_named_as_it_reads(index):
    """R4.10, A2.6: a song whose Latin-1 text another encoding reads far better is an entry of
    its own, found by a query over what the scan keeps, named as that encoding reads it; a
    song in Unicode, or real French in Latin-1, isn't one. Ignore keeps it by its path and
    hash, until its file changes."""
    put(index, [
        ("SV/TG/08.mp3", misread("Маяк", track=8), None, 200.0, None),
        ("SV/TG/01.mp3", misread("Утро", track=1), None, 200.0, None),
        ("SV/U.mp3", Tags(title="Маяк", artist="Северный Ветер"), None, 200.0, None),
        ("FR/E.mp3", Tags(title="L'été indien", latin1=("title",)), None, 200.0, None),
    ])  # fmt: skip
    c = index.read()
    assert c.execute("SELECT path, latin1, encoding FROM song ORDER BY path").fetchall() == [
        ("FR/E.mp3", "title", None),
        ("SV/TG/01.mp3", "title,artist,album", "cp1251"),
        ("SV/TG/08.mp3", "title,artist,album", "cp1251"),
        ("SV/U.mp3", None, None),
    ]
    got = [e for e in attention.find(c) if e.kind == attention.ENCODING]
    assert [(e.about, e.title, e.artist, e.album_title, e.key, e.fields) for e in got] == [
        ("SV/TG/01.mp3", "Утро", "Северный Ветер", "Тихая Гавань", "cp1251",
         ("title", "artist", "album")),
        ("SV/TG/08.mp3", "Маяк", "Северный Ветер", "Тихая Гавань", "cp1251",
         ("title", "artist", "album")),
    ]  # fmt: skip
    assert got[0].album is not None and got[0].song is not None and got[0].modified == 2.0
    kept = attention.dismissal_of(got[1], T1)
    assert (kept.kind, kept.about, kept.hash, kept.modified) == (
        "wrong-encoding", "SV/TG/08.mp3", "SV/TG/08.mp3", 2.0
    )  # fmt: skip
    index.write(lambda c: rootfiles.load_ignored(c, [kept])).result()
    left = [e.about for e in attention.find(c, rootfiles.dismissals(c))
            if e.kind == attention.ENCODING]  # fmt: skip
    assert left == ["SV/TG/01.mp3"]


def test_fix_encodings_songs_are_read_with_their_latin_1_fields_and_their_albums(index):
    """What Fix encoding… plans from (R4.10): the songs asked for, in that order, with the text
    fields their tags hold and which are Latin-1; and the songs of a song's album, in its order
    (it alone when it is on none)."""
    put(index, [
        ("SV/TG/08.mp3", misread("Маяк", track=8), None, 200.0, None),
        ("SV/TG/01.mp3", misread("Утро", track=1), None, 200.0, None),
        ("Loose.mp3", Tags(title="Loose"), None, 200.0, None),
    ])  # fmt: skip
    c = index.read()
    ids = dict(c.execute("SELECT path, id FROM song"))
    found = attention.encoded_songs(c, [ids["SV/TG/08.mp3"], 999, ids["Loose.mp3"]])
    assert [(p, t.title, t.latin1) for _i, p, t in found] == [
        ("SV/TG/08.mp3", cp1251("Маяк"), ("title", "artist", "album")),
        ("Loose.mp3", "Loose", ()),
    ]
    assert attention.album_songs(c, ids["SV/TG/08.mp3"]) == [ids["SV/TG/01.mp3"],
                                                             ids["SV/TG/08.mp3"]]  # fmt: skip
    assert attention.album_songs(c, ids["Loose.mp3"]) == [ids["Loose.mp3"]]
    assert attention.album_songs(c, 999) == [999]
    assert attention.latin1_of("title,year,album") == ("title", "album")
    assert attention.latin1_of(None) == ()


def test_the_scan_keeps_latin_1_text_and_a_fix_written_takes_the_song_out(index, tmp_path):
    """A3.6: the scan reads which fields are Latin-1 and flags the song; once the fix is written
    as Unicode, the row MusiKata updates itself (scanner.wrote) has neither."""
    from musikata_core import encodings
    from musikata_core import tags as tags_core

    music = tmp_path / "Music"
    wav(music / "a.wav", 1)
    f = mutagen.wave.WAVE(str(music / "a.wav"))
    f.add_tags()
    f.tags.add(mutagen.id3.TIT2(encoding=0, text=cp1251("Маяк")))
    f.tags.add(mutagen.id3.TPE1(encoding=0, text=cp1251("Северный Ветер")))
    f.save(v2_version=3)
    scan(music, index)
    c = index.read()
    assert c.execute("SELECT latin1, encoding FROM song").fetchone() == ("title,artist", "cp1251")
    tags, _ = tags_core.read(str(music / "a.wav"))
    fixed, names = encodings.fixed(tags, "cp1251")
    w = tags_core.save(str(music / "a.wav"), {n: getattr(fixed, n) for n in names},
                       audio_hash=scanner.audio_hash)  # fmt: skip
    index.write(lambda c: scanner.wrote(c, str(music), [w])).result()
    assert c.execute("SELECT title, latin1, encoding FROM song").fetchone() == ("Маяк", None, None)


# ---------- tags that differ from the path (R3.9, R2.8) ----------


def test_a_folder_whose_tags_differ_from_its_paths_is_an_entry_about_the_folder(tmp_path):
    """R2.8's "Tags that differ from the path": an entry a folder, with how many of its files
    differ and in what; Ignore keeps it by its folder until a file changes; the root's own
    folder is "."."""
    index = db.Index(str(tmp_path / "musikata.db"))
    tide, ld = "Lumen Drift/Tide Tables", "Lumen Drift"
    songs = [
        (f"{tide}/01 - Neap Tide.flac", Tags(title="Neap Tide", albumartist=ld, album="Tide Tables",
                                              track=1)),
        (f"{tide}/02 - Spring Tide.flac", Tags(title="Spring Tide", albumartist="lumen drift",
                                                album="Tide Tables")),
        (f"{ld}/Glass Harbor/01 - Tidewater.flac", Tags(title="Tidewater", albumartist=ld,
                                                         album="Glass Harbor", track=1)),
        ("Lumen Drift - Ebb.flac", Tags(artist="lumen drift", title="Ebb")),
    ]  # fmt: skip
    try:
        batch = [
            scanner.Read(scanner.Seen(p, 10, 2_000_000_000 + n), t,
                         AudioInfo("flac", 60.0, 900, 44100, 2), f"{n}" * 64)
            for n, (p, t) in enumerate(songs, 1)
        ]  # fmt: skip
        index.write(lambda c: scanner.write_batch(c, batch, {})).result()
        got = [e for e in attention.find(index.read()) if e.kind == attention.PATH]
        assert [(e.about, e.title, e.counts, e.fields) for e in got] == [
            (".", "", (1, 1), ("artist",)),
            ("Lumen Drift/Tide Tables", "Tide Tables", (1, 2), ("albumartist", "track")),
        ]
        assert got[1].song is not None and got[1].modified == pytest.approx(2.0, abs=1e-6)
        assert attention.KINDS[0] == attention.PATH
        assert attention.folder_of(".") == "" and attention.folder_about("") == "."
        assert attention.folder_of("A/B") == "A/B"
        d = attention.dismissal_of(got[1], "2026-11-26T21:00:00Z")
        assert (d.kind, d.about, d.hash, d.modified) == ("path-differs", tide, None,
                                                         got[1].modified)  # fmt: skip
        left = attention.find(index.read(), [d])
        assert [e.about for e in left if e.kind == attention.PATH] == ["."]
    finally:
        index.close()
