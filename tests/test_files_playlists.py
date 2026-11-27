"""Playlists as files (src/musikata_core/playlists.py; R8.1 to R8.4, R8.6 to R8.8): M3U and M3U8
read in the shapes other programs write them (testing.md, "Shapes": absolute and relative paths,
`\\` and `/`, `file://` URLs, `#EXTINF` and without, a BOM, CRLF, an `.m3u` in the system's
encoding, comments and blank lines, files missing, outside the root or listed twice), written as
R8.1 says and read back unchanged, kept in the index by the scan, and changed by MusiKata through
the store: made, renamed, duplicated, deleted, added to, removed from, fixed, pointed at files
moved; Find's matches and Export's plan and copies.

Why: a playlist is a file other players read and write. One misread drops a user's songs; one
half written loses the list; one written in another form than it was read breaks the player that
made it; one pointing at a file that moved plays nothing."""

import os
from datetime import UTC, datetime

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from musikata_core import attention, db, playlists, scanner, settings
from musikata_core.playlists import Entry, Playlist
from musikata_core.tags import AudioInfo, Tags

# ---------- reading: the shapes (R8.1.2) ----------


def locations(p):
    return [e.location for e in p.entries]


def test_an_extended_m3u8_reads_each_entry_with_its_extinf():
    data = (
        b"#EXTM3U\n#EXTINF:253,Lumen Drift - Signal Fires\n../Lumen Drift/04 Signal Fires.flac\n"
        b"#EXTINF:-1,Unknown\n../x.mp3\n"
    )
    p = playlists.parse(data)
    assert p.entries == (
        Entry("../Lumen Drift/04 Signal Fires.flac", 253, "Lumen Drift - Signal Fires"),
        Entry("../x.mp3", None, "Unknown"),
    )
    assert p.header == () and p.encoding == "utf-8"


def test_a_plain_m3u_without_extinf_or_header_reads_its_paths():
    p = playlists.parse(b"a.mp3\nb/c.flac\n", "m3u")
    assert p.entries == (Entry("a.mp3"), Entry("b/c.flac"))


def test_a_bom_crlf_cr_blank_lines_and_spaces_around_are_read_through():
    data = b"\xef\xbb\xbf#EXTM3U\r\n\r\n  #EXTINF:12.6 , A - B \r\n  a.mp3  \r\n\rb.mp3\r"
    p = playlists.parse(data)
    assert p.entries == (Entry("a.mp3", 13, "A - B"), Entry("b.mp3"))


def test_comments_are_passed_by_and_those_before_the_first_entry_kept_as_its_header():
    data = (
        b"#EXTM3U\n#PLAYLIST:Road Trip\n#MUSIKATA-RULE: rating>=4\n# a note\na.mp3\n"
        b"#EXTGRP:Rock\n#EXTVLCOPT:start-time=10\nb.mp3\n"
    )
    p = playlists.parse(data)
    assert locations(p) == ["a.mp3", "b.mp3"]
    assert p.header == ("#PLAYLIST:Road Trip", "#MUSIKATA-RULE: rating>=4", "# a note")


def test_extinf_lengths_with_attributes_or_that_arent_lengths_are_read_for_what_they_are():
    p = playlists.parse(
        b'#EXTINF:-1 tvg-id="x",A - B\na\n#EXTINF:abc,C\nb\n#EXTINF:nan,D\nc\n#EXTINF:,E\nd\n'
        b"#EXTINF:30\ne\n"
    )
    assert [(e.seconds, e.title) for e in p.entries] == [
        (None, "A - B"), (None, "C"), (None, "D"), (None, "E"), (30, "")
    ]  # fmt: skip


def test_an_extinf_with_no_entry_after_it_is_passed_by_and_one_entry_takes_only_its_own():
    p = playlists.parse(b"#EXTINF:1,A\n#EXTINF:2,B\nb.mp3\nc.mp3\n#EXTINF:3,C\n")
    assert p.entries == (Entry("b.mp3", 2, "B"), Entry("c.mp3"))


def test_an_m3u_in_the_systems_encoding_is_read_in_it_and_an_m3u8_never():
    text = "../Beyoncé/Déjà Vu.mp3\n"
    p = playlists.parse(text.encode("cp1252"), "m3u", "cp1252")
    assert locations(p) == ["../Beyoncé/Déjà Vu.mp3"] and p.encoding == "cp1252"
    utf8 = playlists.parse(text.encode(), "m3u", "cp1252")
    assert locations(utf8) == ["../Beyoncé/Déjà Vu.mp3"] and utf8.encoding == "utf-8"
    m3u8 = playlists.parse(text.encode("cp1252"), "m3u8", "cp1252")
    assert m3u8.encoding == "utf-8" and "\ufffd" in m3u8.entries[0].location
    assert playlists.parse(text.encode("cp1252"), "m3u", "no-such-codec").encoding == "cp1252"


def test_utf16_with_its_bom_as_windows_media_player_may_write_it():
    p = playlists.parse(b"\xff\xfe" + "#EXTM3U\r\nа.mp3\r\n".encode("utf-16-le"), "m3u")
    assert locations(p) == ["а.mp3"] and p.encoding == "utf-8"


def test_the_legacy_encoding_is_the_locales_and_windows_western_where_that_is_utf8(monkeypatch):
    monkeypatch.setattr(playlists.locale, "getpreferredencoding", lambda _=False: "UTF-8")
    assert playlists.legacy_encoding() == "cp1252"
    monkeypatch.setattr(playlists.locale, "getpreferredencoding", lambda _=False: "cp1251")
    assert playlists.legacy_encoding() == "cp1251"
    monkeypatch.setattr(playlists.locale, "getpreferredencoding", lambda _=False: "x-unknown")
    assert playlists.legacy_encoding() == "cp1252"


@given(st.binary(max_size=400), st.sampled_from(["m3u", "m3u8"]))
@example(b"\x00\x00#EXTINF:\x00", "m3u")
@example(b"\xff\xfe\x00", "m3u8")
@example(b"#EXTINF:1e309,x\na", "m3u8")
def test_any_bytes_at_all_read_as_a_playlist_without_raising(data, kind):
    p = playlists.parse(data, kind)
    assert all(e.location and not e.location.startswith("#") for e in p.entries)
    for e in p.entries:
        playlists.resolve(e.location, "Playlists", "/music")


def test_none_one_and_very_many_entries_and_a_very_long_path():
    assert playlists.parse(b"").entries == ()
    assert playlists.parse(b"#EXTM3U\n").entries == ()
    many = "\n".join(f"{n}.mp3" for n in range(5000)).encode()
    assert len(playlists.parse(many).entries) == 5000
    long = "a/" * 400 + "x.mp3"
    assert locations(playlists.parse(long.encode())) == [long]


# ---------- writing, and back (R8.1, R8.1.1) ----------


def test_r8_1s_form_is_extm3u_then_extinf_and_the_path_of_each_entry():
    p = Playlist((Entry("../a/b.flac", 253, "Lumen Drift - Signal Fires"), Entry("c.mp3")))
    assert playlists.compose(p) == (
        b"#EXTM3U\n#EXTINF:253,Lumen Drift - Signal Fires\n../a/b.flac\n#EXTINF:-1,\nc.mp3\n"
    )


def test_a_header_is_kept_and_text_that_doesnt_fit_the_encoding_is_written_as_utf8():
    p = Playlist((Entry("Деревья.mp3", 1, "А - Б"),), ("#PLAYLIST:X",))
    assert playlists.compose(p).startswith(b"#EXTM3U\n#PLAYLIST:X\n")
    assert playlists.compose(p, "cp1252") == playlists.compose(p)
    latin = Playlist((Entry("Déjà.mp3", 1, "É"),))
    assert playlists.compose(latin, "cp1252") == playlists.compose(latin).decode().encode("cp1252")
    assert b"\n\n" not in playlists.compose(Playlist((Entry("a\nb.mp3", 1, "x\r\ny"),)))


entries = st.builds(
    Entry,
    st.text(st.characters(blacklist_categories=("Cs", "Cc", "Zl", "Zp")), min_size=1).map(
        str.strip
    ).filter(lambda s: s and not s.startswith("#") and s != "\ufeff" and "\x85" not in s
             and not s.startswith("\ufeff")),
    st.one_of(st.none(), st.integers(0, 10**7)),
    st.text(st.characters(blacklist_categories=("Cs", "Cc", "Zl", "Zp")), max_size=40).map(
        str.strip
    ).filter(lambda s: "\x85" not in s),
)  # fmt: skip


@given(st.lists(entries, max_size=30))
def test_a_playlist_written_then_read_gives_back_its_entries(written):
    p = Playlist(tuple(written))
    assert playlists.parse(playlists.compose(p)).entries == p.entries


def test_a_file_is_written_whole_through_a_copy_beside_it(tmp_path, monkeypatch):
    path = str(tmp_path / "A.m3u8")
    playlists.write_file(path, b"#EXTM3U\nold.mp3\n")
    real = os.replace

    def broken(a, b):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(playlists.os, "replace", broken)
    with pytest.raises(OSError):
        playlists.write_file(path, b"#EXTM3U\nnew.mp3\n")
    monkeypatch.setattr(playlists.os, "replace", real)
    with open(path, "rb") as f:
        assert f.read() == b"#EXTM3U\nold.mp3\n"
    assert os.listdir(tmp_path) == ["A.m3u8"]


# ---------- where an entry is (R8.1, R8.1.2) ----------


@pytest.mark.parametrize(
    ("location", "folder", "root", "path"),
    [
        ("../Lumen Drift/a.flac", "Playlists", "/music", "Lumen Drift/a.flac"),
        ("a.mp3", "", "/music", "a.mp3"),
        ("./sub/../a.mp3", "Playlists", "/music", "Playlists/a.mp3"),
        ("..\\Lumen Drift\\a.flac", "Playlists", "/music", "Lumen Drift/a.flac"),
        ("/music/Lumen Drift/a.flac", "Playlists", "/music", "Lumen Drift/a.flac"),
        ("/music/Lumen Drift/a.flac", "Playlists", "/music/", "Lumen Drift/a.flac"),
        ("/elsewhere/a.flac", "Playlists", "/music", None),
        ("/musical/a.flac", "Playlists", "/music", None),
        ("../../a.mp3", "Playlists", "/music", None),
        ("..", "", "/music", None),
        ("file:///music/Lumen%20Drift/a%23b.flac", "Playlists", "/music", "Lumen Drift/a#b.flac"),
        ("file://localhost/music/a.flac", "Playlists", "/music", "a.flac"),
        ("FILE:///music/a.flac", "", "/music", "a.flac"),
        ("file:///C:/Music/A/b.mp3", "", "C:\\Music", "A/b.mp3"),
        ("file://server/share/Music/a.mp3", "", "//server/share/Music", "a.mp3"),
        ("C:\\Music\\A\\b.mp3", "Playlists", "C:\\Music", "A/b.mp3"),
        ("c:\\MUSIC\\A\\b.mp3", "Playlists", "C:\\Music", "A/b.mp3"),
        ("D:\\Music\\A\\b.mp3", "Playlists", "C:\\Music", None),
        ("C:\\Music\\A\\b.mp3", "Playlists", "/home/ana/Music", None),
        ("http://radio.example/stream.mp3", "", "/music", None),
        ("", "", "/music", None),
    ],
)
def test_absolute_relative_windows_paths_and_file_urls_are_found_under_the_root(
    location, folder, root, path
):
    assert playlists.resolve(location, folder, root) == path


def test_an_entry_is_named_relative_to_its_playlists_folder_with_slashes():
    assert playlists.relative_to("Lumen Drift/a.flac", "Playlists") == "../Lumen Drift/a.flac"
    assert playlists.relative_to("Playlists/x/a.mp3", "Playlists") == "x/a.mp3"
    assert playlists.relative_to("a.mp3", "") == "a.mp3"
    assert playlists.relative_to("a.mp3", "P/Q") == "../../a.mp3"
    assert playlists.is_relative("../a.mp3") and not playlists.is_relative("/m/a.mp3")
    assert not playlists.is_relative("C:\\a.mp3") and not playlists.is_relative("file:///a")
    assert not playlists.is_relative("\\\\server\\a.mp3")


@given(st.lists(st.sampled_from(["a", "B c", "é", "..x", "d.e"]), min_size=1, max_size=4),
       st.lists(st.sampled_from(["Playlists", "x", "y z"]), max_size=3))  # fmt: skip
def test_a_path_named_relative_to_any_folder_resolves_back_to_itself(parts, folder):
    path, where = "/".join(parts), "/".join(folder)
    assert playlists.resolve(playlists.relative_to(path, where), where, "/m") == path


# ---------- names (R8.3, R8.4) ----------


def test_a_name_is_made_one_a_file_can_have_on_every_system():
    assert playlists.file_name("AC/DC: Live?") == "AC_DC_ Live_"
    assert playlists.file_name("  Road Trip.  ") == "Road Trip"
    assert playlists.file_name("...") == ""
    assert playlists.file_name("Cafe\u0301") == "Café"


def test_a_taken_name_is_numbered_case_aside_and_a_copy_is_named_so():
    assert playlists.unique("New playlist", []) == "New playlist"
    assert playlists.unique("New playlist", ["new PLAYLIST", "New playlist 2"]) == "New playlist 3"
    assert playlists.copy_name("Road Trip", ["Road Trip"]) == "Road Trip copy"
    assert playlists.copy_name("Road Trip", ["Road Trip copy"]) == "Road Trip copy 2"
    assert playlists.name_of("Playlists/Road Trip.m3u8") == "Road Trip"
    assert playlists.kind_of("A.M3U") == "m3u" and playlists.kind_of("a.txt") is None


# ---------- the plans ----------


def test_r8_1s_form_names_entries_relative_with_their_songs_extinf_and_leaves_others_as_they_are():
    p = Playlist((
        Entry("/music/A/x.flac"), Entry("..\\A\\gone.mp3", 7, "Old - Name"),
        Entry("/elsewhere/y.mp3", 3, "Y"), Entry("C:\\z.mp3"),
    ))  # fmt: skip
    known = {"A/x.flac": playlists.Song("A/x.flac", 252.6, "Lumen Drift", "Signal Fires")}
    out = playlists.normal(p, "Playlists", "/music", known)
    assert out.entries == (
        Entry("../A/x.flac", 253, "Lumen Drift - Signal Fires"),
        Entry("../A/gone.mp3", 7, "Old - Name"),
        Entry("/elsewhere/y.mp3", 3, "Y"),
        Entry("C:\\z.mp3", None, "z"),
    )


def test_extinf_is_artist_and_title_or_the_title_or_the_files_name():
    assert playlists.extinf_of(playlists.Song("a/b.mp3", 1.4, "A", "B")) == (1, "A - B")
    assert playlists.extinf_of(playlists.Song("a/b.mp3", None, None, "B")) == (None, "B")
    assert playlists.extinf_of(playlists.Song("a/04 b.mp3", -1)) == (None, "04 b")


def test_songs_are_added_at_the_end_even_twice_and_removed_by_their_places():
    p = Playlist((Entry("../a.mp3"),))
    more = playlists.added(p, ["a.mp3", "b/c.mp3"], "Playlists")
    assert locations(more) == ["../a.mp3", "../a.mp3", "../b/c.mp3"]
    assert locations(playlists.removed(more, {0, 2})) == ["../a.mp3"]
    assert playlists.removed(more, {9}) == more


def test_a_missing_entry_found_names_its_file_wherever_it_was_listed():
    p = Playlist((Entry("../gone.mp3", 3, "X"), Entry("../b.mp3"), Entry(" ../gone.mp3")))
    out = playlists.fixed(p, "../gone.mp3", "found/it.mp3", "Playlists")
    assert locations(out) == ["../found/it.mp3", "../b.mp3", "../found/it.mp3"]


def test_files_moved_are_named_anew_and_a_playlist_naming_none_of_them_is_left_alone():
    p = Playlist((Entry("/music/a.mp3"), Entry("../b.mp3", 3, "B")))
    out = playlists.repointed(p, "Playlists", "/music", {"a.mp3": "x/a.mp3"})
    assert out is not None and locations(out) == ["../x/a.mp3", "../b.mp3"]
    assert playlists.repointed(p, "Playlists", "/music", {"c.mp3": "d.mp3"}) is None


# ---------- Find (R8.7) ----------

SONGS = [  # id, path, title, artist, length, likely copies' key
    (1, "Lumen Drift/Tide Tables/04 - Slack Tide.flac", "Slack Tide", "Lumen Drift", 200.0, None),
    (2, "_Incoming/10 - slack tide.mp3", None, None, 199.0, None),
    (3, "Other/Slack Tide (live).mp3", "Slack Tide", "Somebody", 300.0, None),
    (4, "Other/x.mp3", "Something else", "Lumen Drift", 200.0, None),
]


def test_find_offers_songs_of_the_same_name_and_of_the_same_title_and_artist_both_first():
    key = playlists.duplicates.song_key("Lumen Drift", "Slack Tide")
    songs = [s if s[0] != 1 else (*s[:5], key) for s in SONGS]
    found = playlists.candidates("../Lumen Drift/Tide Tables/10 - Slack Tide.flac",
                                 "Lumen Drift - Slack Tide", 200, songs)  # fmt: skip
    assert [(c.song, c.by_name, c.by_tags) for c in found] == [
        (2, True, False), (1, False, True), (3, False, True),
    ]  # fmt: skip
    by_name = playlists.candidates("../x/10 - Slack Tide.flac", "", None, SONGS)
    assert [(c.song, c.by_name, c.by_tags) for c in by_name] == [
        (2, True, False), (1, False, True), (3, False, True),
    ]  # fmt: skip
    both = playlists.candidates("../x/04 - Slack Tide.flac", "", None, SONGS)
    assert [(c.song, c.by_name, c.by_tags) for c in both][0] == (1, True, True)
    assert playlists.candidates("../nothing.mp3", "", None, SONGS) == []


def test_what_find_looks_for_is_the_name_the_extinfs_artist_and_title_or_a_title_alone():
    assert playlists.wanted("../A/10 - Slack Tide.flac", "") == (
        "10 - slack tide", None, "slack tide"
    )  # fmt: skip
    name, key, alone = playlists.wanted("a.mp3", "Lumen Drift - Slack Tide")
    assert key == playlists.duplicates.song_key("Lumen Drift", "Slack Tide") and alone == (
        "slack tide"
    )
    assert playlists.wanted("a.mp3", "Just A Title")[1:] == (None, "just a title")


# ---------- Export (R8.8) ----------


def test_export_names_each_song_by_its_whole_path_or_copies_it_numbered_beside_a_playlist():
    songs = [playlists.Exported("/m/A/x.flac", "Lumen Drift", "Signal Fires", 253.0), None,
             playlists.Exported("/m/B/y.mp3", None, "AC/DC?", None)]  # fmt: skip
    absolute = playlists.export_plan("Road Trip", songs, playlists.ABSOLUTE)
    assert absolute.copies == () and absolute.skipped == 1 and absolute.name == "Road Trip.m3u8"
    assert absolute.playlist == (
        b"#EXTM3U\n#EXTINF:253,Lumen Drift - Signal Fires\n/m/A/x.flac\n#EXTINF:-1,AC/DC?\n"
        b"/m/B/y.mp3\n"
    )
    copies = playlists.export_plan("Road/Trip", songs, playlists.COPIES)
    assert copies.copies == (
        ("/m/A/x.flac", "01 - Lumen Drift - Signal Fires.flac"), ("/m/B/y.mp3", "02 - AC_DC_.mp3")
    )  # fmt: skip
    assert b"\n01 - Lumen Drift - Signal Fires.flac\n" in copies.playlist
    assert copies.name == "Road_Trip.m3u8"
    hundred = [playlists.Exported(f"/m/{n}.mp3", "A", str(n), 1.0) for n in range(100)]
    assert playlists.export_plan("x", hundred, playlists.COPIES).copies[0][1] == "001 - A - 0.mp3"


def test_export_copies_whole_keeps_one_there_and_never_writes_over_another(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.mp3").write_bytes(b"a" * 10)
    (src / "b.mp3").write_bytes(b"b" * 10)
    (src / "c.mp3").write_bytes(b"c" * 10)
    out = tmp_path / "usb"
    out.mkdir()
    (out / "02 - b.mp3").write_bytes(b"x" * 10)  # the same size: there already
    (out / "03 - c.mp3").write_bytes(b"other")  # another file: never written over
    plan = playlists.ExportPlan(
        ((str(src / "a.mp3"), "01 - a.mp3"), (str(src / "b.mp3"), "02 - b.mp3"),
         (str(src / "c.mp3"), "03 - c.mp3"), (str(src / "gone.mp3"), "04 - gone.mp3")),
        "Road Trip.m3u8", b"#EXTM3U\n", 0,
    )  # fmt: skip
    seen = []
    done = playlists.export(plan, str(out), lambda n, of: seen.append((n, of)))
    assert (done.copied, done.there) == (1, 1)
    assert [n for n, _ in done.failed] == ["03 - c.mp3", "04 - gone.mp3"]
    assert (out / "01 - a.mp3").read_bytes() == b"a" * 10
    assert (out / "03 - c.mp3").read_bytes() == b"other"
    assert done.playlist == str(out / "Road Trip.m3u8") and seen[-1] == (4, 4)
    assert sorted(os.listdir(out)) == ["01 - a.mp3", "02 - b.mp3", "03 - c.mp3", "Road Trip.m3u8"]


def test_export_stopped_stops_before_its_next_song_and_writes_no_playlist(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"a")
    plan = playlists.ExportPlan(((str(tmp_path / "a.mp3"), "01 - a.mp3"),), "P.m3u8", b"x", 0)
    out = tmp_path / "usb"
    out.mkdir()
    done = playlists.export(plan, str(out), stop=lambda: True)
    assert done.stopped and done.copied == 0 and os.listdir(out) == []
    calls = iter([False, True])
    done = playlists.export(plan, str(out), stop=lambda: next(calls))
    assert done.stopped and done.copied == 1 and os.listdir(out) == ["01 - a.mp3"]


def test_an_export_folder_that_cant_be_written_says_so(tmp_path):
    plan = playlists.ExportPlan((), "P.m3u8", b"x", 0)
    done = playlists.export(plan, str(tmp_path / "not-there"))
    assert done.playlist == "" and done.failed[0][0] == "P.m3u8"


# ---------- the index and the scan (A2.1, R8.1.2, R8.1.3) ----------


def song_read(path, title="T", artist="A", length=200.0):
    tags = Tags(title=title, artist=artist, album="Al", track=1)
    return scanner.Read(scanner.Seen(path, 10, 1), tags, AudioInfo("mp3", length, 900, 44100, 2),
                        path)  # fmt: skip


@pytest.fixture
def root(tmp_path):
    music = tmp_path / "Music"
    (music / "Playlists").mkdir(parents=True)
    index = db.Index(str(tmp_path / "musikata.db"))
    batch = [song_read("A/a.mp3", "Alpha"), song_read("A/b.mp3", "Beta"),
             song_read("B/c.mp3", "Gamma", "Other", 61.0)]  # fmt: skip
    for r in batch:
        (music / r.seen.path).parent.mkdir(parents=True, exist_ok=True)
        (music / r.seen.path).write_bytes(b"x")
    index.write(lambda c: scanner.write_batch(c, batch, {})).result()
    yield str(music), index
    index.close()


def entries_of(index, path):
    return (
        index.read()
        .execute(
            "SELECT e.position, e.written, e.path, e.seconds, e.title FROM playlist_entry AS e JOIN"
            " playlist ON playlist.id = e.playlist_id WHERE playlist.path = ? ORDER BY position",
            (path,),
        )
        .fetchall()
    )


def found_in(music):
    lists = {}
    list(scanner.walk(music, lists=lists))
    return lists


def test_the_walk_finds_m3u_and_m3u8_anywhere_but_hidden_and_the_scan_reads_them(root, tmp_path):
    music, index = root
    (tmp_path / "Music" / "Playlists" / "Road Trip.m3u8").write_text("#EXTM3U\n../A/a.mp3\n")
    (tmp_path / "Music" / "A" / "old.M3U").write_bytes(b"a.mp3\r\nb.mp3\r\n")
    (tmp_path / "Music" / ".hidden").mkdir()
    (tmp_path / "Music" / ".hidden" / "x.m3u8").write_text("a")
    lists = found_in(music)
    assert {k: [f.name for f in v] for k, v in lists.items() if v} == {
        "A": ["old.M3U"], "Playlists": ["Road Trip.m3u8"]
    }  # fmt: skip
    assert playlists.refresh(music, index, lists, lambda f: True, "cp1252") == (2, 0)
    assert entries_of(index, "A/old.M3U") == [(0, "a.mp3", "A/a.mp3", None, ""),
                                              (1, "b.mp3", "A/b.mp3", None, "")]  # fmt: skip
    rows = index.read().execute("SELECT path, name, kind, absolute FROM playlist ORDER BY name_key")
    assert rows.fetchall() == [("A/old.M3U", "old", "m3u", 0),
                               ("Playlists/Road Trip.m3u8", "Road Trip", "m3u8", 0)]  # fmt: skip
    assert playlists.refresh(music, index, lists, lambda f: True) == (0, 0)  # unchanged: unread


def test_a_playlist_changed_by_another_program_is_read_again_and_one_gone_taken_out(root, tmp_path):
    music, index = root
    path = tmp_path / "Music" / "Playlists" / "P.m3u8"
    path.write_text("../A/a.mp3\n")
    playlists.refresh(music, index, found_in(music), lambda f: True)
    path.write_text("#EXTM3U\n../A/b.mp3\n../A/a.mp3\n")
    os.utime(path, ns=(1, 2_000_000_000))
    assert playlists.refresh(music, index, found_in(music), lambda f: True) == (1, 0)
    assert [r[2] for r in entries_of(index, "Playlists/P.m3u8")] == ["A/b.mp3", "A/a.mp3"]
    path.unlink()
    assert playlists.refresh(music, index, found_in(music), lambda f: f == "A") == (0, 0)
    assert playlists.refresh(music, index, found_in(music), lambda f: True) == (0, 1)
    assert index.read().execute("SELECT COUNT(*) FROM playlist_entry").fetchone() == (0,)


def test_what_a_scan_reads_and_takes_out_of_the_playlists():
    found = {"P/a.m3u8": playlists.Found("a.m3u8", 1, 1), "P/b.m3u8": playlists.Found("b", 2, 2)}
    indexed = {"P/a.m3u8": (1, 1), "P/b.m3u8": (2, 9), "P/gone.m3u": (1, 1), "Q/x.m3u": (1, 1)}
    assert playlists.changes(found, indexed, {"P"}) == (["P/b.m3u8"], ["P/gone.m3u"])


def test_an_entry_missing_outside_the_root_or_listed_twice_is_kept_as_its_file_names_it(root):
    music, index = root
    data = b"../A/a.mp3\n../A/gone.mp3\n/elsewhere/x.mp3\n../A/a.mp3\n"
    index.write(lambda c: playlists.index_file(c, music, "Playlists/T.m3u8", data, 1, 1)).result()
    assert [r[2] for r in entries_of(index, "Playlists/T.m3u8")] == [
        "A/a.mp3", "A/gone.mp3", None, "A/a.mp3"
    ]  # fmt: skip
    assert index.read().execute("SELECT absolute FROM playlist").fetchone() == (1,)
    found = attention.found(index.read())
    missing = [e for e in found if e.kind == attention.MISSING]
    assert [(e.title, e.artist, e.key, e.error) for e in missing] == [
        ("gone", "T", "../A/gone.mp3", "A/gone.mp3"), ("x", "T", "/elsewhere/x.mp3", ""),
    ]  # fmt: skip
    assert attention.missing_of(missing[0].about) == ("Playlists/T.m3u8", "../A/gone.mp3")


def test_a_smart_playlists_rule_is_kept_in_its_row(root):
    music, index = root
    data = b"#EXTM3U\n#MUSIKATA-RULE: rating>=4\n../A/a.mp3\n"
    index.write(lambda c: playlists.index_file(c, music, "Playlists/S.m3u8", data, 1, 1)).result()
    assert index.read().execute("SELECT rule FROM playlist").fetchone() == ("rating>=4",)


def test_a_scan_of_the_root_reads_its_playlists_and_a_partial_one_those_in_its_folders(
    root, tmp_path
):
    from concurrent.futures import ThreadPoolExecutor

    music, index = root
    (tmp_path / "Music" / "Playlists" / "P.m3u8").write_text("../A/a.mp3\n")
    with ThreadPoolExecutor(1) as pool:
        result = scanner.scan(music, index, pool, hold=False)
        assert result.playlists == 1
        (tmp_path / "Music" / "Playlists" / "Q.m3u").write_text("../B/c.mp3\n")
        part = scanner.scan(music, index, pool, scope=scanner.Scope(frozenset({"Playlists"}), {}),
                            hold=False)  # fmt: skip
        assert part.playlists == 1
    names = index.read().execute("SELECT name FROM playlist ORDER BY name_key").fetchall()
    assert names == [("P",), ("Q",)]


# ---------- the store: MusiKata's own changes ----------


def store_of(root):
    music, index = root
    return playlists.Store(music, index, "Playlists", "cp1252")


def song_ids(index, *paths):
    c = index.read()
    return [c.execute("SELECT id FROM song WHERE path = ?", (p,)).fetchone()[0] for p in paths]


def test_a_new_playlist_is_new_playlist_numbered_when_taken_holding_the_songs_in_r8_1s_form(
    root, tmp_path
):
    music, index = root
    store = store_of(root)
    made = store.create(song_ids(index, "B/c.mp3", "A/a.mp3"))
    assert made.name == "New playlist" and made.count == 2
    data = (tmp_path / "Music" / "Playlists" / "New playlist.m3u8").read_bytes()
    assert data == (b"#EXTM3U\n#EXTINF:61,Other - Gamma\n../B/c.mp3\n#EXTINF:200,A - Alpha\n"
                    b"../A/a.mp3\n")  # fmt: skip
    again = store.create()
    assert again.name == "New playlist 2" and again.count == 0
    assert store.name(again.playlist) == "New playlist 2"


def test_the_playlists_folder_is_made_when_it_isnt_there(root, tmp_path):
    music, index = root
    store = playlists.Store(music, index, "Lists/Mine")
    store.create(name="X")
    assert (tmp_path / "Music" / "Lists" / "Mine" / "X.m3u8").is_file()
    (tmp_path / "Music" / "Blocked").write_text("a file, not a folder")
    with pytest.raises(playlists.PlaylistError, match="couldn't be made"):
        playlists.Store(music, index, "Blocked/x").create()


def test_adding_reads_the_file_again_first_and_a_playlist_from_elsewhere_is_then_in_r8_1s_form(
    root, tmp_path
):
    music, index = root
    path = tmp_path / "Music" / "Playlists" / "Win.m3u"
    path.write_bytes("\\Music\\A\\a.mp3\r\n..\\A\\Beyoncé.mp3\r\n".encode("cp1252"))
    playlists.refresh(music, index, found_in(music), lambda f: True)
    playlist = index.read().execute("SELECT id FROM playlist").fetchone()[0]
    path.write_bytes(path.read_bytes() + b"..\\A\\b.mp3\r\n")  # another program, since
    store = store_of(root)
    done = store.add(playlist, song_ids(index, "B/c.mp3"))
    assert done.count == 1 and done.name == "Win"
    assert path.read_bytes() == (
        "#EXTM3U\n#EXTINF:-1,a\n\\Music\\A\\a.mp3\n#EXTINF:-1,Beyoncé\n../A/Beyoncé.mp3\n"
        "#EXTINF:200,A - Beta\n../A/b.mp3\n#EXTINF:61,Other - Gamma\n../B/c.mp3\n"
    ).encode("cp1252")
    assert [r[2] for r in entries_of(index, "Playlists/Win.m3u")] == [
        None, "A/Beyoncé.mp3", "A/b.mp3", "B/c.mp3"
    ]  # fmt: skip


def test_entries_are_removed_by_their_place_and_one_another_program_moved_stays(root, tmp_path):
    music, index = root
    store = store_of(root)
    made = store.create(song_ids(index, "A/a.mp3", "A/b.mp3", "A/a.mp3"))
    ids = [r[0] for r in index.read().execute(
        "SELECT id FROM playlist_entry ORDER BY position")]  # fmt: skip
    done = store.remove(made.playlist, [ids[0], ids[1]])
    assert done.count == 2
    assert [r[2] for r in entries_of(index, "Playlists/New playlist.m3u8")] == ["A/a.mp3"]
    ids = [r[0] for r in index.read().execute("SELECT id FROM playlist_entry")]
    (tmp_path / "Music" / "Playlists" / "New playlist.m3u8").write_text("../B/c.mp3\n")
    store.remove(made.playlist, ids)  # its place names another song now: it stays
    assert (
        (tmp_path / "Music" / "Playlists" / "New playlist.m3u8")
        .read_text()
        .endswith("../B/c.mp3\n")
    )
    assert store.remove(made.playlist, []).count == 0


def test_find_fixes_each_entry_naming_the_missing_file(root, tmp_path):
    music, index = root
    path = tmp_path / "Music" / "Playlists" / "P.m3u8"
    path.write_text("../A/gone.mp3\n../A/a.mp3\n../A/gone.mp3\n")
    playlists.refresh(music, index, found_in(music), lambda f: True)
    playlist = index.read().execute("SELECT id FROM playlist").fetchone()[0]
    store = store_of(root)
    store.fix(playlist, "../A/gone.mp3", song_ids(index, "A/b.mp3")[0])
    assert [r[2] for r in entries_of(index, "Playlists/P.m3u8")] == [
        "A/b.mp3", "A/a.mp3", "A/b.mp3"
    ]  # fmt: skip
    with pytest.raises(playlists.PlaylistError, match="isn't in the library"):
        store.fix(playlist, "../A/a.mp3", 999)


def test_find_in_the_index_by_name_by_tags_and_by_title(root):
    music, index = root
    found = playlists.find(index.read(), "../old/b.mp3", "", None)
    assert [(c.path, c.by_name) for c in found] == [("A/b.mp3", True)]
    found = playlists.find(index.read(), "../x/1.mp3", "Other - Gamma", 61)
    assert [(c.path, c.by_tags) for c in found] == [("B/c.mp3", True)]
    found = playlists.find(index.read(), "../x/04 - alpha.mp3", "", None)
    assert [(c.path, c.by_name, c.by_tags) for c in found] == [("A/a.mp3", False, True)]


def test_renaming_renames_the_file_and_a_name_taken_or_empty_is_refused(root, tmp_path):
    music, index = root
    store = store_of(root)
    a = store.create(name="Road Trip")
    store.create(name="Evening Focus")
    assert store.rename(a.playlist, "Road Trip").name == "Road Trip"
    assert store.rename(a.playlist, "Long Drive: Part 1").name == "Long Drive_ Part 1"
    assert (tmp_path / "Music" / "Playlists" / "Long Drive_ Part 1.m3u8").is_file()
    assert not (tmp_path / "Music" / "Playlists" / "Road Trip.m3u8").exists()
    assert store.name(a.playlist) == "Long Drive_ Part 1"
    with pytest.raises(playlists.PlaylistError, match="already"):
        store.rename(a.playlist, "evening focus")
    with pytest.raises(playlists.PlaylistError, match="needs a name"):
        store.rename(a.playlist, " ... ")
    assert store.rename(a.playlist, "LONG DRIVE_ PART 1").name == "LONG DRIVE_ PART 1"


def test_duplicate_copies_it_beside_itself_as_it_is(root, tmp_path):
    music, index = root
    path = tmp_path / "Music" / "Playlists" / "Mix.m3u"
    path.write_bytes(b"..\\A\\a.mp3\r\n")
    playlists.refresh(music, index, found_in(music), lambda f: True)
    playlist = index.read().execute("SELECT id FROM playlist").fetchone()[0]
    store = store_of(root)
    copy = store.duplicate(playlist)
    assert copy.name == "Mix copy"
    assert (tmp_path / "Music" / "Playlists" / "Mix copy.m3u").read_bytes() == b"..\\A\\a.mp3\r\n"
    assert [r[2] for r in entries_of(index, "Playlists/Mix copy.m3u")] == ["A/a.mp3"]
    assert store.duplicate(playlist).name == "Mix copy 2"


def test_delete_moves_the_file_to_the_trash_and_a_file_that_wont_go_stays(root, tmp_path):
    music, index = root
    store = store_of(root)
    made = store.create(song_ids(index, "A/a.mp3"), "Gone")
    with pytest.raises(playlists.PlaylistError, match="trash"):
        store.delete(made.playlist, lambda p: False)
    assert store.name(made.playlist) == "Gone"
    trashed = []

    def trash(p):
        trashed.append(p)
        os.remove(p)
        return True

    assert store.delete(made.playlist, trash).name == "Gone"
    assert trashed == [str(tmp_path / "Music" / "Playlists" / "Gone.m3u8")]
    assert store.name(made.playlist) == "" and (tmp_path / "Music" / "A" / "a.mp3").exists()
    with pytest.raises(playlists.PlaylistError, match="isn't there"):
        store.delete(made.playlist, trash)


def test_a_playlist_that_cant_be_read_or_written_says_why(root, tmp_path, monkeypatch):
    music, index = root
    store = store_of(root)
    made = store.create(name="P")
    (tmp_path / "Music" / "Playlists" / "P.m3u8").unlink()
    with pytest.raises(playlists.PlaylistError, match="couldn't be read"):
        store.add(made.playlist, song_ids(index, "A/a.mp3"))
    with pytest.raises(playlists.PlaylistError, match="couldn't be copied"):
        store.duplicate(made.playlist)
    with pytest.raises(playlists.PlaylistError, match="couldn't be renamed"):
        store.rename(made.playlist, "Q")
    (tmp_path / "Music" / "Playlists" / "P.m3u8").write_text("")

    def full(path, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(playlists, "write_file", full)
    with pytest.raises(playlists.PlaylistError, match="No space left"):
        store.add(made.playlist, song_ids(index, "A/a.mp3"))


def test_files_moved_are_pointed_at_in_every_playlist_naming_them(root, tmp_path):
    """What Organize files calls when it moves files (R12.4, R8.7), and R2.12's Move the others to
    the trash for the copies it removed."""
    music, index = root
    store = store_of(root)
    one = store.create(song_ids(index, "A/a.mp3", "B/c.mp3"), "One")
    two = store.create(song_ids(index, "A/a.mp3"), "Two")
    store.create(song_ids(index, "B/c.mp3"), "Three")
    written = store.repoint({"A/a.mp3": "A/b.mp3"})
    assert written == ["Playlists/One.m3u8", "Playlists/Two.m3u8"]
    assert [r[2] for r in entries_of(index, "Playlists/One.m3u8")] == ["A/b.mp3", "B/c.mp3"]
    assert [r[2] for r in entries_of(index, "Playlists/Two.m3u8")] == ["A/b.mp3"]
    assert store.repoint({}) == []
    (tmp_path / "Music" / "Playlists" / "One.m3u8").unlink()
    assert store.repoint({"A/b.mp3": "A/a.mp3"}) == ["Playlists/Two.m3u8"]
    assert store.name(one.playlist) == "One" and store.name(two.playlist) == "Two"


# ---------- the root's setting (R13.6) ----------


@pytest.mark.parametrize(
    ("text", "folder", "problems"),
    [
        ("{}", "Playlists", 0),
        ('{"playlists": {"folder": "Lists/Mine/"}}', "Lists/Mine", 0),
        ('\ufeff{"playlists": {"folder": "Lists\\\\Mine"}}', "Lists/Mine", 0),
        ('{"playlists": {"folder": "/abs"}}', "Playlists", 1),
        ('{"playlists": {"folder": "C:/x"}}', "Playlists", 1),
        ('{"playlists": {"folder": "../out"}}', "Playlists", 1),
        ('{"playlists": {"folder": ".hidden"}}', "Playlists", 1),
        ('{"playlists": {"folder": ""}}', "Playlists", 1),
        ('{"playlists": {"folder": 3}}', "Playlists", 1),
        ('{"playlists": []}', "Playlists", 1),
        ("[]", "Playlists", 0),
        ("not json", "Playlists", 1),
    ],
)
def test_the_roots_playlists_folder_or_the_default_when_it_cant_be_one(text, folder, problems):
    found, said = settings.parse_root_playlists(text)
    assert found == folder and len(said) == problems


def test_the_roots_playlists_folder_is_read_from_its_settings_json(tmp_path, caplog):
    assert settings.root_playlists(str(tmp_path)) == "Playlists"
    (tmp_path / ".musikata").mkdir()
    (tmp_path / ".musikata" / "settings.json").write_text('{"playlists": {"folder": "My Lists"}}')
    assert settings.root_playlists(str(tmp_path)) == "My Lists"
    (tmp_path / ".musikata" / "settings.json").write_text('{"playlists": {"folder": 1}}')
    assert settings.root_playlists(str(tmp_path)) == "Playlists" and "folder" in caplog.text
    os.remove(tmp_path / ".musikata" / "settings.json")
    (tmp_path / ".musikata" / "settings.json").mkdir()  # can't be read
    assert settings.root_playlists(str(tmp_path)) == "Playlists"


def test_a_missing_entrys_dismissal_keeps_its_playlist_its_place_and_the_playlists_time():
    e = attention.Entry(attention.MISSING, attention.missing_about("P/a.m3u8", "x.mp3"),
                        modified=5.0)  # fmt: skip
    d = attention.dismissal_of(e, datetime(2026, 11, 27, tzinfo=UTC).isoformat())
    assert (d.kind, d.about, d.modified, d.hash) == (attention.MISSING, "P/a.m3u8\tx.mp3", 5.0,
                                                     None)  # fmt: skip
