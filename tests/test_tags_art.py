"""Finding an album's cover (src/musikata_core/art.py, tags.pictures; R5.1) in the shapes covers
come in (docs/process/testing.md, "Shapes": `art`, `tags.pictures`): pictures embedded by each
kind's convention, several of them or none, a front cover that isn't first, pictures that can't be
decoded, and folder images named in any case, of each kind, beside images that aren't covers.

Why: the cover shown is the first R5.1 finds, so a back cover taken for the front, or a folder's
scan of the booklet taken over its cover.jpg, is the wrong picture on every view of the album."""

import base64
import os
import shutil
import sys

import mutagen
import mutagen.id3 as id3
import pytest
from mutagen.flac import Picture as FlacPicture
from mutagen.mp4 import MP4, MP4Cover

from musikata_core import art, tags
from musikata_core.tags import Picture

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0 a jpeg"
PNG = b"\x89PNG a png"


def image(name, size=100):
    return art.Image(name, size, 1)


def test_a_folder_image_named_cover_folder_front_or_album_wins_in_that_order_any_case():
    found = [image("Back.jpg", 900), image("ALBUM.PNG"), image("Folder.jpeg"), image("x.txt")]
    assert art.folder_cover(found).name == "Folder.jpeg"
    assert art.folder_cover([*found, image("cover.webp", 1)]).name == "cover.webp"
    assert art.folder_cover([image("front.jpg"), image("album.jpg")]).name == "front.jpg"


def test_else_the_largest_other_image_and_never_what_isnt_an_image():
    found = [image("booklet 2.jpg", 300), image("scan.png", 700), image("notes.txt", 9000)]
    assert art.folder_cover(found).name == "scan.png"
    assert art.folder_cover([image("b.jpg", 5), image("a.jpg", 5)]).name == "a.jpg"
    assert art.folder_cover([image("cover.gif"), image(".cover.jpg"), image("cover")]) is None
    assert art.folder_cover([]) is None


def test_images_are_named_by_their_extension_in_any_case_and_hidden_ones_are_not():
    assert [art.is_image(n) for n in ("a.JPG", "a.jpeg", "a.Png", "a.webp", "a.bmp", ".a.jpg")] == [
        True, True, True, True, False, False
    ]  # fmt: skip


def test_the_front_cover_is_taken_over_pictures_before_it():
    back, front = Picture(4, "image/jpeg", b"back"), Picture(3, "image/jpeg", b"front")
    assert art.front([back, front]) is front
    assert art.front([back]) is back  # no front: the first
    untyped = Picture(None, "", b"covr")  # MP4's covr has no types
    assert art.front([untyped, Picture(None, "", b"second")]) is untyped
    assert art.front([Picture(3, "image/jpeg", b""), back]) is back  # an empty one is no picture
    assert art.front([]) is None


def test_a_thumbnails_name_changes_with_the_cover_and_its_file():
    a = art.thumb_id("A/cover.jpg", 100, 1)
    assert len(a) == 32 and a == art.thumb_id("A/cover.jpg", 100, 1)
    assert len({a, art.thumb_id("A/cover.jpg", 101, 1), art.thumb_id("A/cover.jpg", 100, 2),
                art.thumb_id("B/cover.jpg", 100, 1)}) == 4  # fmt: skip


# ---------- the pictures embedded in a song (tags.pictures) ----------


@pytest.fixture(scope="module")
def audio(tmp_path_factory):
    d = tmp_path_factory.mktemp("audio")
    out = {}
    for kind in ("mp3", "flac", "aac", "vorbis", "opus", "wav", "aiff"):
        out[kind] = str(d / f"{kind}.{demo.KINDS[kind][0]}")
        demo.encode(out[kind], kind, 0.1, 440)
    return out


def _copy(audio, kind, tmp_path):
    path = str(tmp_path / os.path.basename(audio[kind]))
    shutil.copyfile(audio[kind], path)
    return path


@pytest.mark.slow
@pytest.mark.parametrize("kind", ["mp3", "flac", "aac", "vorbis", "opus", "wav", "aiff"])
def test_each_kinds_embedded_cover_is_read_as_the_demo_library_writes_it(audio, tmp_path, kind):
    path = _copy(audio, kind, tmp_path)
    assert tags.pictures(path) == []
    demo.tag(path, demo.Song(path, kind, {"title": "x"}, cover=(11, 16)))
    found = tags.pictures(path)
    assert len(found) == 1 and found[0].data == demo.cover_jpeg(11, 16)
    assert found[0].mime in ("image/jpeg", "") and found[0].type in (3, None)


@pytest.mark.slow
def test_several_id3_pictures_keep_their_order_and_types(audio, tmp_path):
    path = _copy(audio, "mp3", tmp_path)
    t = id3.ID3()
    t.add(id3.APIC(encoding=3, mime="image/png", type=4, desc="back", data=PNG))
    t.add(id3.APIC(encoding=3, mime="image/jpeg", type=3, desc="front", data=JPEG))
    t.save(path)
    found = tags.pictures(path)
    assert [(p.type, p.mime) for p in found] == [(4, "image/png"), (3, "image/jpeg")]
    assert art.front(found).data == JPEG


@pytest.mark.slow
def test_vorbis_comments_pictures_old_coverart_and_a_broken_one_skipped(audio, tmp_path, caplog):
    path = _copy(audio, "flac", tmp_path)
    pic = FlacPicture()
    pic.type, pic.mime, pic.data = 3, "image/png", PNG
    f = mutagen.File(path)
    f["METADATA_BLOCK_PICTURE"] = [base64.b64encode(pic.write()).decode(), "bm90IGEgcGljdHVyZQ=="]
    f["coverart"] = base64.b64encode(JPEG).decode()  # the older convention, its key lower case
    f.save()
    found = tags.pictures(path)
    assert [(p.type, p.data) for p in found] == [(3, PNG), (None, JPEG)]
    assert "couldn't be read" in caplog.text


@pytest.mark.slow
def test_mp4_covers_say_their_format(audio, tmp_path):
    path = _copy(audio, "aac", tmp_path)
    f = MP4(path)
    f["covr"] = [MP4Cover(PNG, imageformat=MP4Cover.FORMAT_PNG), MP4Cover(JPEG)]
    f.save()
    assert [(p.type, p.mime, p.data) for p in tags.pictures(path)] == [
        (None, "image/png", PNG), (None, "image/jpeg", JPEG)
    ]  # fmt: skip


def test_a_file_that_isnt_a_song_has_no_pictures_but_says_why(tmp_path):
    (tmp_path / "x.flac").write_bytes(b"not a flac")
    with pytest.raises(tags.TagReadError):
        tags.pictures(str(tmp_path / "x.flac"))
    with pytest.raises(tags.TagReadError, match="not a kind"):
        tags.pictures(str(tmp_path / "cover.jpg"))
