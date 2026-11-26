"""The scan (src/musikata_core/scanner.py; A2.2, A2.3, R2.3): what the walk skips, the audio hash
that retagging doesn't change, and a scan that reads only what changed, finds moves by hash, and
keeps a row for a file it couldn't read.

Why: the scan is how the index stays a copy of the files (A1.4). A scan that read every file each
time would take minutes at 50,000 songs; one that lost a move would lose the song's plays; one
that hashed the tags would call every retagged song new."""

import logging
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

import mutagen
import pytest

from musikata_core import db, scanner, workers

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
        "a": ["Back.PNG", "cover.jpg"], "c": ["folder.webp"], "": ["top.jpg"]
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
