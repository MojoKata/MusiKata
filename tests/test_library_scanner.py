"""The scan (src/musikata_core/scanner.py; A2.2, A2.3, R2.3): what the walk skips, the audio hash
that retagging doesn't change, and a scan that reads only what changed, finds moves by hash, and
keeps a row for a file it couldn't read.

Why: the scan is how the index stays a copy of the files (A1.4). A scan that read every file each
time would take minutes at 50,000 songs; one that lost a move would lose the song's plays; one
that hashed the tags would call every retagged song new."""

import logging
import os
import shutil
import stat
import sys
import types
from concurrent.futures import ThreadPoolExecutor

import mutagen
import pytest
from fakes import wav

from musikata_core import albums, art, db, scanner, workers

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402


def _touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def test_the_walk_skips_hidden_ignored_and_settings_folders_and_the_roots_own(tmp_path):
    r = str(tmp_path)
    for p in ("a/1.mp3", "a/.hidden.mp3", ".hidden/2.mp3", "b/3.flac", "b/notes.txt",
              "skip/4.mp3", "ignored/5.mp3", "ignored/.musikataignore", ".musikata/6.mp3",
              "c/d/7.OPUS"):  # fmt: skip
        _touch(os.path.join(r, p))
    found = [s.path for s in scanner.walk(r, skip=["skip"])]
    assert found == ["a/1.mp3", "b/3.flac", "c/d/7.OPUS"]


@pytest.mark.skipif(not hasattr(os, "symlink") or sys.platform.startswith("win"), reason="links")
def test_links_are_followed_and_one_leading_back_is_skipped_and_logged(tmp_path, caplog):
    music, other = tmp_path / "Music", tmp_path / "Elsewhere"
    _touch(str(music / "a" / "1.mp3"))
    _touch(str(other / "2.mp3"))
    os.symlink(other, music / "linked")
    os.symlink(music / "a", music / "a" / "back")
    caplog.set_level(logging.INFO)
    assert [s.path for s in scanner.walk(str(music))] == ["a/1.mp3", "linked/2.mp3"]
    assert "leads back" in caplog.text


def test_the_walk_notes_each_folders_images_for_its_albums_covers(tmp_path):
    r = str(tmp_path)
    for p in ("a/1.mp3", "a/cover.jpg", "a/Back.PNG", "a/.hidden.jpg", "a/notes.txt", "b/2.flac",
              "c/folder.webp", "top.jpg"):  # fmt: skip
        _touch(os.path.join(r, p))
    images = {}
    found = [s.path for s in scanner.walk(r, images=images)]
    assert found == ["a/1.mp3", "b/2.flac"]
    assert {k: sorted(i.name for i in v) for k, v in images.items()} == {
        "a": ["Back.PNG", "cover.jpg"], "b": [], "c": ["folder.webp"], "": ["top.jpg"]
    }  # fmt: skip
    assert images["a"][0].size == 1


def test_the_plan_reads_only_what_changed_or_is_new_and_lists_what_went():
    seen = [scanner.Seen("a.mp3", 1, 1), scanner.Seen("b.mp3", 2, 2), scanner.Seen("c.mp3", 3, 3)]
    indexed = {"a.mp3": (1, 1), "b.mp3": (2, 9), "gone.mp3": (4, 4)}
    plan = scanner.plan(seen, indexed)
    assert [s.path for s in plan.read] == ["b.mp3", "c.mp3"] and plan.gone == ["gone.mp3"]


@pytest.fixture(scope="module")
def audio(tmp_path_factory):
    d = tmp_path_factory.mktemp("audio")
    out = {}
    for kind, (ext, *_rest) in demo.KINDS.items():
        out[kind] = str(d / f"{kind}.{ext}")
        demo.encode(out[kind], kind, 2.0, 330)
    return out


SONG = {"title": "Signal Fires", "artist": "Lumen Drift", "album": "Glass Harbor", "track": 4,
        "tracktotal": 10, "year": 2019, "genre": ["Electronic"], "rating": 3}  # fmt: skip


@pytest.mark.slow
@pytest.mark.parametrize("kind", list(demo.KINDS))
def test_the_audio_hash_stays_when_the_tags_change_and_copies_match(audio, tmp_path, kind):
    a, b = str(tmp_path / ("a" + audio[kind][-5:])), str(tmp_path / ("b" + audio[kind][-5:]))
    shutil.copyfile(audio[kind], a)
    shutil.copyfile(audio[kind], b)
    before = scanner.audio_hash(a, kind)
    demo.tag(a, demo.Song(a, kind, dict(SONG), cover=(11, 64)))
    with open(a, "rb") as fa, open(b, "rb") as fb:
        assert fa.read() != fb.read()  # FLAC may keep its size, by its padding
    assert scanner.audio_hash(a, kind) == before == scanner.audio_hash(b, kind)
    with open(a, "rb") as f:
        start, end = scanner.audio_range(f, os.path.getsize(a), kind)
    assert 0 <= start < end <= os.path.getsize(a)


def test_an_mp3s_id3v1_and_ape_tags_are_outside_its_audio(tmp_path):
    body = b"\xff\xfb" + b"\x11" * 1000
    ape = b"APETAGEX" + (2000).to_bytes(4, "little") + (64).to_bytes(4, "little") + b"\0" * 16
    v2 = b"ID3\x04\x00\x00" + bytes([0, 0, 0, 10]) + b"\0" * 10
    data = v2 + body + b"\0" * 32 + ape + b"TAG" + b"\0" * 125
    path = tmp_path / "x.mp3"
    path.write_bytes(data)
    with open(path, "rb") as f:
        start, end = scanner.audio_range(f, len(data), "mp3")
    assert (start, end) == (len(v2), len(v2) + len(body))


def test_damaged_files_give_a_range_inside_them_whatever_their_kind(tmp_path):
    for kind in ("flac", "aac", "wav", "aiff", "vorbis", "opus", "mp3"):
        path = tmp_path / f"x.{kind}"
        for data in (b"", b"fLaC\x00", b"\x00\x00\x00\x08mdat", b"OggS" + b"\x00" * 40, b"ID3\x04"):
            path.write_bytes(data)
            with open(path, "rb") as f:
                start, end = scanner.audio_range(f, len(data), kind)
            assert 0 <= start <= end <= len(data), (kind, data)


def _library(tmp_path, audio):
    music = tmp_path / "Music"
    for n, kind in enumerate(("flac", "mp3", "aac", "opus"), 1):
        path = str(
            music
            / "Lumen Drift"
            / "Glass Harbor"
            / f"{n:02d} - Song.{audio[kind][-4:].lstrip('.')}"
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(audio[kind], path)
        demo.tag(
            path, demo.Song(path, kind, {**SONG, "track": n, "genre": ["Electronic", "Ambient"]})
        )
    return str(music)


def _rows(index):
    return {r[0]: r[1:] for r in index.read().execute("SELECT path, id, title, error FROM song")}


@pytest.mark.slow
def test_a_scan_fills_the_index_and_a_second_reads_nothing(audio, tmp_path):
    music = _library(tmp_path, audio)
    index = db.Index(str(tmp_path / "musikata.db"))
    progress = []
    with ThreadPoolExecutor(2) as pool:
        first = scanner.scan(music, index, pool, progress=lambda d, n: progress.append((d, n)))
        second = scanner.scan(music, index, pool)
    assert (first.added, first.unreadable) == (4, 0) and progress == [(4, 4)]
    album = index.read().execute("SELECT artist, title, songs, genre FROM album").fetchall()
    assert album == [("Lumen Drift", "Glass Harbor", 4, "Electronic")]
    assert (second.added, second.changed, second.unchanged) == (0, 0, 4)
    genres = index.read().execute("SELECT genre FROM song_genre ORDER BY song_id, position")
    assert [g for (g,) in genres][:2] == ["Electronic", "Ambient"]
    index.close()


@pytest.mark.slow
def test_a_scan_finds_a_change_a_move_by_hash_a_removal_and_an_unreadable_file(audio, tmp_path):
    music = _library(tmp_path, audio)
    index = db.Index(str(tmp_path / "musikata.db"))
    with ThreadPoolExecutor(2) as pool:
        scanner.scan(music, index, pool)
        before = _rows(index)
        album = os.path.join(music, "Lumen Drift", "Glass Harbor")
        f = mutagen.File(os.path.join(album, "01 - Song.flac"))
        f["TITLE"] = "Retitled"
        f.save()
        os.rename(os.path.join(album, "02 - Song.mp3"), os.path.join(music, "Moved.mp3"))
        os.remove(os.path.join(album, "04 - Song.opus"))
        _touch(os.path.join(album, "05 - Broken.flac"), b"fLaC" + b"\xff" * 30)
        res = scanner.scan(music, index, pool)
    after = _rows(index)
    assert (res.changed, res.moved, res.removed, res.added, res.unreadable) == (1, 1, 1, 1, 1)
    assert after["Lumen Drift/Glass Harbor/01 - Song.flac"][1] == "Retitled"
    assert after["Moved.mp3"][0] == before["Lumen Drift/Glass Harbor/02 - Song.mp3"][0]
    assert "Lumen Drift/Glass Harbor/04 - Song.opus" not in after
    assert after["Lumen Drift/Glass Harbor/05 - Broken.flac"][2]  # its reason (R2.8)
    albums = index.read().execute("SELECT artist, title, songs FROM album").fetchall()
    assert albums == [("Lumen Drift", "Glass Harbor", 3)]  # one removed; the moved one's tags stay
    index.close()


@pytest.mark.slow
def test_the_scan_reads_on_the_worker_processes(audio, tmp_path):
    music = _library(tmp_path, audio)
    index = db.Index(str(tmp_path / "musikata.db"))
    with workers.pool(2) as pool:
        res = scanner.scan(music, index, pool)
    assert res.added == 4 and len(_rows(index)) == 4
    index.close()


def test_a_file_gone_before_its_read_is_a_row_with_the_reason(tmp_path):
    r = scanner.read_one(str(tmp_path), scanner.Seen("gone.flac", 1, 1))
    assert r.error and r.tags is None


def test_a_reader_failing_in_a_way_no_one_expected_is_a_row_not_a_failed_scan(
    tmp_path, monkeypatch, caplog
):
    """A bug in reading one file (the MP4 reader once took iTunes' cpil, a bool, for a list) costs
    that file, listed with what went wrong, and never the rest of the scan."""

    def broken(path):
        raise TypeError("'bool' object is not subscriptable")

    monkeypatch.setattr(scanner, "read_tags", broken)
    _touch(str(tmp_path / "a.m4a"))
    r = scanner.read_one(str(tmp_path), scanner.Seen("a.m4a", 1, 1))
    assert r.error == "TypeError: 'bool' object is not subscriptable" and r.tags is None
    assert "a.m4a" in caplog.text


def test_an_unreadable_file_that_goes_takes_its_row_with_it(tmp_path):
    """A file that couldn't be read has no audio hash, so nothing can be a move of it: when it
    goes, its row goes too (A2.2, step 4), and never stays in the library as a song that isn't
    there."""
    music = tmp_path / "Music"
    _touch(str(music / "Broken.flac"), b"fLaC" + b"\xff" * 30)
    index = db.Index(str(tmp_path / "musikata.db"))
    with ThreadPoolExecutor(1) as pool:
        first = scanner.scan(str(music), index, pool)
        os.remove(music / "Broken.flac")
        second = scanner.scan(str(music), index, pool, hold=False)  # all of a 1-song library
    assert first.unreadable == 1 and second.removed == 1
    assert _rows(index) == {}
    index.close()


# ---------- partial scans (A2.4) ----------


def _scan(music, index, scope=None, **kw):
    with ThreadPoolExecutor(1) as pool:
        return scanner.scan(str(music), index, pool, scope=scope, **kw)


def _scope(*folders, known=None):
    return scanner.Scope(frozenset(folders), known or {})


@pytest.fixture
def lib(tmp_path):
    music = tmp_path / "Music"
    music.mkdir()
    index = db.Index(str(tmp_path / "musikata.db"))
    yield music, index
    index.close()


def test_a_partial_scan_reads_only_the_folders_named_passing_by_the_known_ones_under_them(lib):
    music, index = lib
    wav(music / "A" / "1.wav", 1)
    wav(music / "A" / "Sub" / "2.wav", 2)
    wav(music / "B" / "3.wav", 3)
    known = _scan(music, index).folders
    assert set(known) == {"", "A", "A/Sub", "B"}
    wav(music / "A" / "4.wav", 4)
    wav(music / "A" / "Sub" / "5.wav", 5)
    wav(music / "B" / "6.wav", 6)
    os.remove(music / "B" / "3.wav")
    res = _scan(music, index, _scope("A", known=known))
    assert (res.added, res.removed, res.unchanged) == (1, 0, 1)
    assert [s.path for s in res.read] == ["A/4.wav"]
    assert set(res.folders) == {"A"} and res.gone_folders == set()
    assert set(_rows(index)) == {"A/1.wav", "A/4.wav", "A/Sub/2.wav", "B/3.wav"}


def test_a_folder_new_under_a_named_one_is_walked_whole_and_one_gone_takes_its_rows(lib):
    music, index = lib
    wav(music / "A" / "Old" / "1.wav", 1)
    wav(music / "A" / "Old" / "Deep" / "2.wav", 2)
    known = _scan(music, index).folders
    shutil.rmtree(music / "A" / "Old")
    wav(music / "A" / "New" / "Deep" / "3.wav", 3)
    # named twice: walked once; the removals, not R2.10.1's question, are the subject
    res = _scan(music, index, _scope("A", "A/New", known=known), hold=False)
    assert (res.added, res.removed) == (1, 2)
    assert set(res.folders) == {"A", "A/New", "A/New/Deep"}
    assert res.gone_folders == {"A/Old", "A/Old/Deep"}
    assert set(_rows(index)) == {"A/New/Deep/3.wav"}


def test_a_named_folder_ignored_hidden_or_gone_takes_its_rows_and_its_folders_with_it(lib):
    music, index = lib
    for n, path in enumerate(("A/1.wav", "A/Sub/2.wav", "B/3.wav", "C/4.wav", "D/5.wav")):
        wav(music / path, n)
    known = _scan(music, index).folders
    _touch(str(music / "A" / scanner.IGNORE), b"")
    os.rename(music / "B", music / ".B")
    shutil.rmtree(music / "C")
    res = _scan(music, index, _scope("", "A", "B", "C", known=known), hold=False)
    assert res.removed == 4 and set(_rows(index)) == {"D/5.wav"}
    assert res.gone_folders == {"A", "A/Sub", "B", "C"} and set(res.folders) == {""}  # D passed by


def test_what_puts_a_folder_outside_the_library_now(tmp_path):
    root = str(tmp_path)
    for p in ("a/b/x", ".hidden/x", "skip/x", "ignored/in/x"):
        _touch(os.path.join(root, p))
    _touch(os.path.join(root, "ignored", scanner.IGNORE), b"")
    assert not scanner.outside(root, "") and not scanner.outside(root, "a/b")
    assert scanner.outside(root, ".hidden") and scanner.outside(root, "skip", ["skip/"])
    assert scanner.outside(root, "ignored/in") and scanner.outside(root, "a/gone")
    assert scanner.outside(root, "a/b/x")  # a file, not a folder
    assert scanner.outside(str(tmp_path / "none"), "")


def test_the_hidden_attribute_is_windows_hidden_flag(monkeypatch):
    """R2.3.1 on Windows: the walk reads the attribute from each entry's stat; elsewhere stat has
    no attributes, and nothing is hidden by them."""
    monkeypatch.setattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2, raising=False)
    assert scanner._hidden_attribute(types.SimpleNamespace(st_file_attributes=2 | 32))
    assert not scanner._hidden_attribute(types.SimpleNamespace(st_file_attributes=32))
    assert not scanner._hidden_attribute(types.SimpleNamespace())


def test_a_move_between_two_named_folders_keeps_its_row(lib):
    music, index = lib
    wav(music / "A" / "1.wav", 1)
    (music / "B").mkdir()
    known = _scan(music, index).folders
    before = _rows(index)["A/1.wav"][0]
    os.rename(music / "A" / "1.wav", music / "B" / "1.wav")
    res = _scan(music, index, _scope("A", "B", known=known))
    assert (res.moved, res.added, res.removed) == (1, 0, 0)
    assert _rows(index) == {"B/1.wav": (before, None, None)}


def test_a_move_into_a_named_folder_from_one_not_named_keeps_its_row(lib):
    """The file's old folder may be rescanned later, or not at all: the new file takes the row
    of the song with its hash whose file is gone, wherever that was (A2.2, A2.4)."""
    music, index = lib
    wav(music / "A" / "1.wav", 1)
    wav(music / "A" / "2.wav", 2)
    wav(music / "C" / "2.wav", 2)  # a copy, still there: not taken
    (music / "B").mkdir()
    known = _scan(music, index).folders
    rows = _rows(index)
    os.rename(music / "A" / "1.wav", music / "B" / "1.wav")
    res = _scan(music, index, _scope("B", known=known))
    assert (res.moved, res.added) == (1, 0) and _rows(index)["B/1.wav"][0] == rows["A/1.wav"][0]
    res = _scan(music, index, _scope("A", known=known))  # its old folder, later: nothing gone
    assert (res.moved, res.removed, res.unchanged) == (0, 0, 1)
    assert set(_rows(index)) == {"A/2.wav", "B/1.wav", "C/2.wav"}


def test_a_copy_then_its_original_removed_is_a_move_whichever_folder_is_scanned_first(lib):
    """A move between drives (a folder joined by a link, R2.3.2) copies, then removes: the copy's
    folder is rescanned while the original is still there, and the original's later. The song
    keeps its row (A2.2) at its new path, and the copy's row goes."""
    music, index = lib
    wav(music / "A" / "1.wav", 1, "Signal Fires")
    wav(music / "A" / "2.wav", 2)
    (music / "B").mkdir()
    known = _scan(music, index).folders
    rows = _rows(index)
    shutil.copy2(music / "A" / "1.wav", music / "B" / "1.wav")
    shutil.copy2(music / "A" / "2.wav", music / "B" / "2.wav")
    res = _scan(music, index, _scope("B", known=known))
    assert res.added == 2 and set(res.copied.values()) == {"B/1.wav", "B/2.wav"}
    os.remove(music / "A" / "1.wav")
    os.remove(music / "B" / "2.wav")  # the copy goes instead: the original stays itself
    copied = res.copied
    res = _scan(music, index, _scope("A", "B", known=known), copied=copied)
    assert (res.moved, res.removed) == (1, 1) and res.copied == {}
    after = _rows(index)
    assert after == {
        "B/1.wav": (rows["A/1.wav"][0], "Signal Fires", None),
        "A/2.wav": rows["A/2.wav"],
    }
    fts = index.read().execute("SELECT rowid FROM song_fts WHERE song_fts MATCH 'signal'")
    assert [r for (r,) in fts] == [rows["A/1.wav"][0]]


def test_a_copy_whose_original_stays_stays_a_song_of_its_own(lib):
    music, index = lib
    wav(music / "A" / "1.wav", 1)
    (music / "B").mkdir()
    known = _scan(music, index).folders
    shutil.copy2(music / "A" / "1.wav", music / "B" / "1.wav")
    copied = _scan(music, index, _scope("B", known=known)).copied
    res = _scan(music, index, _scope("A", known=known), copied=copied)
    assert (res.moved, res.removed, res.unchanged) == (0, 0, 1) and res.copied == copied
    assert set(_rows(index)) == {"A/1.wav", "B/1.wav"}
    assert not scanner.take_over(index.read(), "A/none.wav", "B/1.wav", None)


def test_a_file_musikata_wrote_itself_isnt_read_again(lib):
    music, index = lib
    wav(music / "A" / "1.wav", 1)
    known = _scan(music, index).folders
    wav(music / "A" / "1.wav", 1, "Retitled")  # as a later slice's write would
    st = os.stat(music / "A" / "1.wav")
    expected = {"A/1.wav": (st.st_size, st.st_mtime_ns)}
    res = _scan(music, index, _scope("A", known=known), expected=expected)
    assert (res.changed, res.unchanged, res.read) == (0, 1, [])
    res = _scan(music, index, _scope("A", known=known))  # unknown to it: read
    assert res.changed == 1 and _rows(index)["A/1.wav"][1] == "Retitled"


def test_a_partial_scan_of_a_root_that_isnt_there_takes_nothing_for_removed(lib, caplog):
    music, index = lib
    wav(music / "A" / "1.wav", 1)
    known = _scan(music, index).folders
    shutil.rmtree(music)
    res = _scan(music, index, _scope("", "A", known=known))
    assert res.removed == 0 and set(_rows(index)) == {"A/1.wav"} and "isn't there" in caplog.text


def test_a_partial_scan_keeps_albums_search_and_the_covers_of_folders_it_didnt_walk(lib):
    music, index = lib
    wav(music / "A" / "1.wav", 1, "Undertow")
    wav(music / "B" / "2.wav", 2, "Neap Tide")
    _touch(str(music / "A" / "cover.jpg"))
    known = _scan(music, index).folders
    index.write(lambda c: c.execute("UPDATE song SET album = 'X', albumartist = 'Y'")).result()
    index.write(lambda c: [albums.place(c, i, albums.Touched()) for i in (1, 2)]).result()
    t = albums.Touched()
    t.albums.update(r for (r,) in index.read().execute("SELECT id FROM album"))
    index.write(lambda c: albums.refresh(c, t, {"A": [art.Image("cover.jpg", 1, 1)], "B": []}))
    wav(music / "B" / "2.wav", 2, "Spring Tide")
    _scan(music, index, _scope("B", known=known))
    c = index.read()
    assert c.execute("SELECT title, songs, folder_image FROM album").fetchall() == [
        ("X", 1, "A/cover.jpg")
    ]  # B/2.wav read again: its album tag gone; A's cover kept, A not walked
    found = c.execute(
        "SELECT path FROM song JOIN song_fts ON song_fts.rowid = song.id"
        " WHERE song_fts MATCH 'spring'"
    )
    assert [p for (p,) in found] == ["B/2.wav"]


@pytest.mark.skipif(not hasattr(os, "symlink") or sys.platform.startswith("win"), reason="links")
def test_a_link_new_in_a_named_folder_leading_back_to_a_known_one_is_skipped(lib, caplog):
    music, index = lib
    wav(music / "A" / "1.wav", 1)
    (music / "B").mkdir()
    known = _scan(music, index).folders
    os.symlink(music / "A", music / "B" / "back")
    os.symlink(music / "B", music / "B" / "self")
    caplog.set_level(logging.INFO)
    res = _scan(music, index, _scope("B", known=known))
    assert res.added == 0 and set(res.folders) == {"B"} and "leads back" in caplog.text


# ---------- a root that isn't there (R2.10, R2.10.1) ----------


def _songs(music, n, folder="A", start=0):
    for i in range(start, start + n):
        wav(music / folder / f"{i}.wav", i)


def test_a_root_that_isnt_there_is_scanned_without_taking_any_song_for_removed(tmp_path):
    music = tmp_path / "Music"
    _songs(music, 3)
    index = db.Index(str(tmp_path / "musikata.db"))
    known = _scan(music, index).folders
    shutil.move(music, tmp_path / "unplugged")
    whole = _scan(music, index)
    partial = _scan(music, index, _scope("A", known=known))
    assert whole.missing and partial.missing and whole.removed == partial.removed == 0
    assert set(_rows(index)) == {"A/0.wav", "A/1.wav", "A/2.wav"}
    assert not music.exists()
    index.close()


class _Unplugging:
    """A pool that unplugs the root (moves it away) as the files are read: the root goes while it
    is scanned."""

    def __init__(self, music, away):
        self.music, self.away = music, away

    def map(self, fn, *args):
        out = [fn(*a) for a in zip(*args, strict=True)]
        shutil.move(self.music, self.away)
        return out


def test_a_root_that_goes_while_it_is_scanned_loses_nothing(tmp_path):
    music = tmp_path / "Music"
    _songs(music, 4)
    index = db.Index(str(tmp_path / "musikata.db"))
    _scan(music, index)
    os.remove(music / "A" / "3.wav")  # gone, but not taken out: the root went meanwhile
    wav(music / "A" / "new.wav", 9)  # read as the root goes
    res = scanner.scan(str(music), index, _Unplugging(music, tmp_path / "away"))
    assert res.missing and res.removed == 0 and res.added == 1
    assert "A/3.wav" in _rows(index)
    index.close()


def test_a_link_that_leads_nowhere_keeps_its_songs_and_is_named(tmp_path, caplog):
    music, usb = tmp_path / "Music", tmp_path / "usb"
    _songs(music, 1)
    _songs(usb, 2, "Archive")
    os.symlink(usb / "Archive", music / "Archive")
    index = db.Index(str(tmp_path / "musikata.db"))
    known = _scan(music, index).folders
    assert set(_rows(index)) == {"A/0.wav", "Archive/0.wav", "Archive/1.wav"}
    shutil.move(usb, tmp_path / "unplugged")
    caplog.set_level(logging.WARNING)
    whole = _scan(music, index, hold=False)
    partial = _scan(music, index, _scope("Archive", known=known), hold=False)
    assert whole.unreachable == {"Archive"} == partial.unreachable
    assert whole.removed == partial.removed == 0 and len(_rows(index)) == 3
    assert "the linked folder Archive can't be reached" in caplog.text
    shutil.move(tmp_path / "unplugged", usb)
    back = _scan(music, index)
    assert back.unreachable == set() and back.removed == 0
    index.close()


def test_a_linked_folder_that_cant_be_read_keeps_its_songs(tmp_path, monkeypatch):
    music, share = tmp_path / "Music", tmp_path / "share"
    _songs(share, 2, "Live")
    music.mkdir()
    os.symlink(share / "Live", music / "Live", target_is_directory=True)
    index = db.Index(str(tmp_path / "musikata.db"))
    _scan(music, index)
    real = os.scandir

    def asleep(path="."):
        if str(path).endswith("Live"):
            raise OSError(5, "Input/output error")  # a NAS gone to sleep
        return real(path)

    monkeypatch.setattr(scanner.os, "scandir", asleep)
    res = _scan(music, index, hold=False)
    assert res.unreachable == {"Live"} and res.removed == 0 and len(_rows(index)) == 2
    index.close()


def test_a_folder_under_a_link_that_leads_nowhere_names_the_link():
    assert scanner.unreachable_link("/nowhere", "") is None
    assert scanner.under("A/1.wav", {"A"}) and scanner.under("A", {"A"})
    assert not scanner.under("AB/1.wav", {"A"}) and not scanner.under("A/1.wav", set())


def test_more_than_a_quarter_of_the_songs_gone_is_held_for_the_users_answer(tmp_path, caplog):
    music = tmp_path / "Music"
    _songs(music, 4, "A")
    _songs(music, 4, "B", start=4)
    index = db.Index(str(tmp_path / "musikata.db"))
    _scan(music, index)
    for i in range(3):  # 3 of 8: more than a quarter
        os.remove(music / "A" / f"{i}.wav")
    caplog.set_level(logging.WARNING)
    res = _scan(music, index)
    assert res.held == ["A/0.wav", "A/1.wav", "A/2.wav"] and res.songs == 8 and res.removed == 0
    assert len(_rows(index)) == 8 and "the user is asked" in caplog.text
    kept = _scan(music, index, keep=set(res.held))  # Keep them: not asked about again
    assert kept.held == [] and kept.removed == 0 and len(_rows(index)) == 8
    assert scanner.remove(str(music), index, res.held) == 3  # Remove
    assert set(_rows(index)) == {"A/3.wav", *(f"B/{i}.wav" for i in range(4, 8))}
    index.close()


def test_a_quarter_is_of_the_whole_library_whichever_scan_finds_them_gone(tmp_path):
    music = tmp_path / "Music"
    _songs(music, 4, "A")
    _songs(music, 4, "B", start=4)
    index = db.Index(str(tmp_path / "musikata.db"))
    known = _scan(music, index).folders
    for i in (0, 1):  # 2 of 8, though half of A: a quarter, not more
        os.remove(music / "A" / f"{i}.wav")
    res = _scan(music, index, _scope("A", known=known))
    assert res.held == [] and res.removed == 2
    os.remove(music / "B" / "4.wav")
    os.remove(music / "B" / "5.wav")  # 2 of the 6 left, though only B is scanned: more
    res = _scan(music, index, _scope("B", known=known))
    assert res.held == ["B/4.wav", "B/5.wav"] and res.songs == 6 and res.removed == 0
    index.close()


def test_more_than_a_quarter_means_more():
    assert not scanner.over_a_quarter(0, 0) and not scanner.over_a_quarter(1, 4)
    assert scanner.over_a_quarter(2, 7) and scanner.over_a_quarter(1, 1)


def test_songs_taken_out_on_remove_are_those_still_gone_while_the_root_is_there(tmp_path):
    music = tmp_path / "Music"
    _songs(music, 3)
    index = db.Index(str(tmp_path / "musikata.db"))
    _scan(music, index)
    os.remove(music / "A" / "0.wav")
    assert scanner.remove(str(tmp_path / "gone"), index, ["A/0.wav"]) == 0  # no root: nothing
    assert scanner.remove(str(music), index, ["A/0.wav", "A/1.wav", "A/9.wav"]) == 1
    assert set(_rows(index)) == {"A/1.wav", "A/2.wav"}  # A/1.wav is there; A/9.wav never was
    index.close()
