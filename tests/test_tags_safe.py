"""Safe writes (src/musikata_core/tags/safe.py; A3.4, R4.7, R4.7.1): the copy beside the song, the
tags written to it and flushed, the copy read back, then put in the song's place; and a write that
fails at any step, the song left as it was, the copy gone, and why said in words a person can act
on.

Why: Mutagen writes in place, so one bad moment (a crash, a full disk, a file another program
holds) could leave a song half written; each step's failure is made here on purpose, and the song
checked byte for byte after."""

import errno
import importlib
import logging
import os
import shutil
import stat
import sys
from datetime import UTC, datetime

import pytest
from fakes import FakeClock

from musikata_core import scanner, tags
from musikata_core.tags import Picture

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

safe = importlib.import_module("musikata_core.tags.safe")
write = importlib.import_module("musikata_core.tags.write")


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """A tagged FLAC and MP3, made once: {kind: path}."""
    d = tmp_path_factory.mktemp("made")
    out = {}
    for kind in ("flac", "mp3"):
        out[kind] = str(d / f"{kind}.{demo.KINDS[kind][0]}")
        demo.encode(out[kind], kind, 0.2, 440)
        demo.tag(out[kind], demo.Song(out[kind], kind, {"title": "Tidewater", "genre": ["Folk"]}))
    return out


@pytest.fixture
def song(made, tmp_path):
    path = str(tmp_path / "Tidewater.flac")
    shutil.copyfile(made["flac"], path)
    return path


def save(path, **changes):
    options = {k: changes.pop(k) for k in ("keep_mtime", "platform", "audio_hash") if k in changes}
    return tags.save(path, changes, **{"audio_hash": scanner.audio_hash, **options})


def contents(path):
    with open(path, "rb") as f:
        return f.read()


def leftovers(folder):
    return [n for n in os.listdir(folder) if tags.is_leftover(n)]


@pytest.mark.slow
def test_a_song_is_written_as_a_copy_beside_it_flushed_checked_then_put_in_its_place(
    song, monkeypatch
):
    steps = []
    apply, flush, replace = write.apply, safe.flush, os.replace

    def applying(path, *args):
        steps.append(("apply", os.path.basename(path), tags.read(song)[0].title))
        apply(path, *args)

    def flushing(path):
        steps.append(("flush", os.path.basename(path)))
        flush(path)

    def replacing(src, dst):
        steps.append(("replace", os.path.basename(src), os.path.basename(dst)))
        replace(src, dst)

    monkeypatch.setattr(write, "apply", applying)
    monkeypatch.setattr(safe, "flush", flushing)
    monkeypatch.setattr(os, "replace", replacing)
    written = save(song, title="Undertow")
    assert steps == [
        ("apply", ".Tidewater.flac.musikata-tmp", "Tidewater"),  # the song itself untouched
        ("flush", ".Tidewater.flac.musikata-tmp"),
        ("replace", ".Tidewater.flac.musikata-tmp", "Tidewater.flac"),
    ]
    st = os.stat(song)
    assert (written.path, written.size, written.mtime_ns) == (song, st.st_size, st.st_mtime_ns)
    assert written.tags.title == "Undertow" == tags.read(song)[0].title
    assert written.audio_hash == scanner.audio_hash(song, "flac") and written.info.kind == "flac"
    assert leftovers(os.path.dirname(song)) == []


def fail(error):
    def failing(*args, **kwargs):
        raise error

    return failing


@pytest.mark.slow
@pytest.mark.parametrize(
    "where, error, why",
    [
        ("copy", OSError(errno.ENOSPC, "No space left on device"), "the disk is full"),
        ("copy", PermissionError(errno.EACCES, "Permission denied"), "its folder can't be written"),
        ("apply", OSError(errno.ENOSPC, "No space left on device"), "the disk is full"),
        ("apply", RuntimeError("a frame Mutagen choked on"), "its tags couldn't be written"),
        ("flush", OSError(errno.EIO, "Input/output error"), "Input/output error"),
        ("check", tags.TagReadError("can't sync to MPEG frame"), "couldn't be read back"),
        ("replace", PermissionError(errno.EACCES, "Permission denied"), "folder can't be written"),
        ("replace", OSError(errno.EXDEV, "Invalid cross-device link"), "couldn't be written"),
    ],
)
def test_a_write_interrupted_at_any_step_leaves_the_song_as_it_was(
    song, monkeypatch, caplog, where, error, why
):
    """testing.md, "What tier 1 covers": each step failing in turn."""
    before = contents(song)
    if where == "check":
        read = safe.read
        monkeypatch.setattr(
            safe, "read", lambda p, name=None: (_ for _ in ()).throw(error) if name else read(p)
        )
    elif where == "replace":
        monkeypatch.setattr(os, "replace", fail(error))
    elif where == "flush":
        monkeypatch.setattr(safe, "flush", fail(error))
    else:
        monkeypatch.setattr(write, where, fail(error))
    with pytest.raises(tags.WriteError) as e:
        save(song, title="Undertow")
    assert why in e.value.why and e.value.path == song
    assert contents(song) == before
    assert leftovers(os.path.dirname(song)) == []
    assert "didn't write the tags of" in caplog.text


@pytest.mark.slow
def test_tags_that_dont_read_back_as_written_leave_the_song_as_it_was(song, monkeypatch):
    before = contents(song)
    apply = write.apply

    def wrong(path, change, *args):  # a writer that slips: the album, not the title
        apply(path, {"album": change["title"]}, *args)

    monkeypatch.setattr(write, "apply", wrong)
    with pytest.raises(tags.WriteError, match="title, album didn't read back as written"):
        save(song, title="Undertow")
    assert contents(song) == before and leftovers(os.path.dirname(song)) == []


@pytest.mark.slow
def test_a_cover_or_audio_that_doesnt_read_back_leaves_the_song_as_it_was(song, monkeypatch):
    before = contents(song)
    monkeypatch.setattr(write, "_flac_pictures", lambda f, cover: None)
    with pytest.raises(tags.WriteError, match="its cover didn't read back"):
        save(song, cover=Picture(3, "image/jpeg", b"\xff\xd8new"))
    monkeypatch.undo()
    hashes = iter(["one", "two"])
    with pytest.raises(tags.WriteError, match="its audio didn't read back the same"):
        save(song, title="Undertow", audio_hash=lambda path, kind: next(hashes))
    assert contents(song) == before and leftovers(os.path.dirname(song)) == []


@pytest.mark.slow
def test_a_read_only_song_is_reported_and_never_touched(song):
    os.chmod(song, 0o444)
    before = contents(song)
    try:
        with pytest.raises(tags.WriteError, match="it is read-only: let it be written to"):
            save(song, title="Undertow")
        assert contents(song) == before and leftovers(os.path.dirname(song)) == []
    finally:
        os.chmod(song, 0o644)


def test_a_song_gone_or_that_cant_be_read_says_so(tmp_path):
    with pytest.raises(tags.WriteError, match="it isn't there any more"):
        save(str(tmp_path / "gone.flac"), title="x")
    broken = tmp_path / "broken.flac"
    broken.write_bytes(b"fLaC" + b"\xff" * 40)
    with pytest.raises(tags.WriteError, match="it can't be read"):
        save(str(broken), title="x")
    assert leftovers(tmp_path) == []


@pytest.mark.slow
def test_the_songs_permissions_are_kept_and_its_modification_time_updated_or_kept(song):
    """R4.7.1: by default a written file's modification time is updated; the setting keeps it."""
    os.chmod(song, 0o640)
    old = 1_000_000_000_000_000_000  # 2001
    os.utime(song, ns=(old, old))
    save(song, title="Undertow")
    st = os.stat(song)
    assert stat.S_IMODE(st.st_mode) == 0o640 and st.st_mtime_ns > old
    os.utime(song, ns=(old, old))
    written = save(song, title="Parallax", keep_mtime=True)
    st = os.stat(song)
    assert st.st_mtime_ns == old == written.mtime_ns and tags.read(song)[0].title == "Parallax"


@pytest.mark.slow
def test_what_a_write_changed_is_said_for_the_change_history(song):
    """A3.5: the change history keeps each field's old value and the old cover, from the write."""
    old_cover = tags.pictures(song)
    written = save(song, title="Undertow", genres=["Folk"])  # the genre already as asked
    assert written.before.title == "Tidewater" and written.changed == ("title",)
    assert (written.cover_before, written.cover_after) == (None, None)
    new = Picture(3, "image/png", b"\x89PNG\r\n\x1a\nnew")
    written = save(song, cover=new)
    assert written.changed == ("cover",) and written.cover_after == new
    assert written.cover_before == (old_cover[0] if old_cover else None)
    unchanged = save(song, title="Undertow")
    assert unchanged.changed == () and unchanged.before == unchanged.tags


def test_a_change_that_leaves_every_field_as_it_was_writes_nothing(song):
    old = 1_000_000_000_000_000_000
    os.utime(song, ns=(old, old))
    written = save(song, title="Tidewater", genres=["Folk"])
    assert os.stat(song).st_mtime_ns == old == written.mtime_ns
    assert written.tags.title == "Tidewater"


def test_a_mistaken_change_is_a_value_error_not_a_write_error(song):
    with pytest.raises(ValueError, match="bpm"):
        save(song, bpm=120)
    with pytest.raises(ValueError, match="R10.4"):
        save(song.replace(".flac", ".wav"), rating=3)


@pytest.mark.parametrize(
    "error, step, platform, why",
    [
        (PermissionError(errno.EACCES, "denied"), "replacing", "win32", "open in another program"),
        (_win := PermissionError(errno.EACCES, "used"), "copying", "win32", "another program"),
        (PermissionError(errno.EACCES, "denied"), "replacing", "linux", "its folder can't be"),
        (PermissionError(errno.EACCES, "denied"), "reading", "linux", "it can't be opened"),
        (OSError(errno.EROFS, "Read-only file system"), "copying", "linux", "drive can't be"),
        (OSError(errno.EDQUOT, "Disk quota exceeded"), "writing", "linux", "the disk is full"),
        (FileNotFoundError(errno.ENOENT, "gone"), "reading", "linux", "isn't there any more"),
        (
            FileNotFoundError(errno.ENOENT, "gone"),
            "replacing",
            "linux",
            "couldn't be written: gone",
        ),
        (tags.TagReadError("bad"), "reading", "linux", "it can't be read: bad"),
        (ValueError("odd"), "checking", "linux", "couldn't be written: ValueError: odd"),
    ],
)
def test_each_failure_says_what_happened_and_what_to_do(error, step, platform, why):
    if error is _win:
        error.winerror = 32  # ERROR_SHARING_VIOLATION
    assert why in safe.reason(error, step, platform)


def test_the_copys_name_and_a_leftover_one_are_told_apart():
    assert safe.tmp_path(os.path.join("A", "01 Tidewater.flac")) == os.path.join(
        "A", ".01 Tidewater.flac.musikata-tmp"
    )
    assert tags.is_leftover(".01 Tidewater.flac.musikata-tmp")
    for name in ("01 Tidewater.flac", ".musikata-tmp", "x.musikata-tmp", ".hidden.flac"):
        assert not tags.is_leftover(name)


def test_a_leftover_copy_is_removed_once_untouched_for_a_while_never_while_being_written(
    tmp_path, caplog
):
    """A3.4: a crash's copy goes at the next scan; another MusiKata's write in progress, on this
    computer or another sharing the root, doesn't."""
    caplog.set_level(logging.INFO)
    copy = tmp_path / ".1.flac.musikata-tmp"
    copy.write_bytes(b"half")
    st = os.stat(copy)
    touched = datetime.fromtimestamp(max(st.st_mtime, st.st_ctime), UTC)
    clock = FakeClock(touched)
    clock.advance(seconds=safe.LEFTOVER - 1)
    assert not safe.remove_stale(str(copy), clock.now().timestamp()) and copy.exists()
    clock.advance(seconds=2)
    assert safe.remove_stale(str(copy), clock.now().timestamp()) and not copy.exists()
    assert "removed" in caplog.text and "a copy a write left behind" in caplog.text
    assert not safe.remove_stale(str(copy), clock.now().timestamp())  # gone already


def test_a_leftover_that_cant_be_removed_is_logged(tmp_path, monkeypatch, caplog):
    copy = tmp_path / ".1.flac.musikata-tmp"
    copy.write_bytes(b"half")
    monkeypatch.setattr(os, "remove", fail(PermissionError(errno.EACCES, "denied")))
    assert not safe.remove_stale(str(copy), os.stat(copy).st_mtime + 2 * safe.LEFTOVER)
    assert "couldn't remove" in caplog.text
    safe.remove(str(copy))
    assert "couldn't remove" in caplog.text


@pytest.mark.slow
def test_an_mp3s_copy_is_read_as_an_mp3_whatever_its_own_name(made, tmp_path):
    path = str(tmp_path / "Low Orbit.mp3")
    shutil.copyfile(made["mp3"], path)
    written = save(path, title="Low Orbit", genres=["Synthwave"])
    assert written.info.kind == "mp3" and tags.read(path)[0].genres == ("Synthwave",)
