"""The Album art dialog's plain logic (src/musikata_core/art.py; R5.2, R5.3, R5.5): what an image
from outside is, read from its bytes (`sniff`) and whether it can be used (`problem`); the covers
found for an album and the current one (`gather`); what each of R5.3's checkboxes writes, to which
files, and "No change" (`plan`, `footer`); cover.jpg written with the older one to the trash
(`save_image`, `writer`). In the shapes images come in (docs/process/testing.md, "Shapes": `art`):
JPEG, PNG and WebP; CMYK JPEGs, transparency; huge, tiny, not square; bytes cut short or that
aren't an image.

Why: the dialog writes every song of an album and the folder's cover.jpg at once; a plan that
writes the wrong files, misses some, or says "No change" when it would change something rewrites
an album the user didn't mean to, and an image read wrongly is embedded broken in every song."""

import os
import stat

import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core import art
from musikata_core.art import Added, FolderImage, Forms, Options, SongArt
from musikata_core.tags import Job, Picture, WriteError, Written

FRONT = art.FRONT


def jpeg(w=1200, h=1200, components=3, before=b""):
    """A JPEG's header as an encoder writes it: SOI, JFIF's APP0, `before`, then a baseline
    frame header with its size and colour components (3: YCbCr, 4: CMYK)."""
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = (b"\xff\xc0" + (8 + 3 * components).to_bytes(2, "big") + b"\x08" + h.to_bytes(2, "big")
           + w.to_bytes(2, "big") + bytes([components]) + b"\x01\x11\x00" * components)  # fmt: skip
    return b"\xff\xd8" + app0 + before + sof + b"\xff\xda rest of the scan"


def png(w=500, h=500, colour=2, trns=False):
    out = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + w.to_bytes(4, "big")
    out += h.to_bytes(4, "big") + bytes([8, colour, 0, 0, 0]) + b"CRC!"
    if trns:
        out += b"\x00\x00\x00\x02tRNS\x00\x00CRC!"
    return out + b"\x00\x00\x00\x04IDATdataCRC!"


def webp(kind, w=640, h=480, alpha=False):
    if kind == "VP8 ":
        body = b"\x00\x00\x00" + b"\x9d\x01\x2a" + w.to_bytes(2, "little") + h.to_bytes(2, "little")
    elif kind == "VP8L":
        bits = (w - 1) | (h - 1) << 14 | (1 << 28 if alpha else 0)
        body = b"\x2f" + bits.to_bytes(4, "little")
    else:
        body = bytes([0x10 if alpha else 0]) + b"\x00\x00\x00"
        body += (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    chunk = kind.encode() + len(body).to_bytes(4, "little") + body
    return b"RIFF" + (4 + len(chunk)).to_bytes(4, "little") + b"WEBP" + chunk


# ---------- an image, from its bytes ----------


@pytest.mark.parametrize(
    ("data", "want"),
    [
        (jpeg(1200, 800), art.ImageInfo("jpeg", 1200, 800)),
        (jpeg(600, 600, 4), art.ImageInfo("jpeg", 600, 600, cmyk=True)),
        (jpeg(300, 200, 1), art.ImageInfo("jpeg", 300, 200)),  # greyscale
        # an EXIF block, fill bytes and a restart marker before the frame header
        (
            jpeg(64, 64, before=b"\xff\xe1\x00\x08Exif\x00\x00\xff\xff\xff\xd0"),
            art.ImageInfo("jpeg", 64, 64),
        ),  # fmt: skip
        (png(500, 400), art.ImageInfo("png", 500, 400)),
        (png(32, 32, colour=6), art.ImageInfo("png", 32, 32, alpha=True)),
        (png(32, 32, colour=3, trns=True), art.ImageInfo("png", 32, 32, alpha=True)),
        (webp("VP8 ", 640, 480), art.ImageInfo("webp", 640, 480)),
        (webp("VP8L", 300, 301, alpha=True), art.ImageInfo("webp", 300, 301, alpha=True)),
        (webp("VP8X", 2000, 1000, alpha=True), art.ImageInfo("webp", 2000, 1000, alpha=True)),
    ],
)
def test_an_images_kind_size_cmyk_and_transparency_are_read_from_its_header(data, want):
    assert art.sniff(data) == want


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"GIF89a not one of R5.1's",
        b"%PDF-1.7 a document",
        b"\xff\xd8",  # a JPEG cut short at its start
        jpeg()[:26],  # cut short in its frame header
        b"\xff\xd8\xff\xda the scan before any frame",
        b"\xff\xd8\xff\xe0\x00\x01",  # a segment whose length can't be
        b"\xff\xd8\x00 not a marker",
        b"\xff\xd8" + b"\xff" * 10,  # nothing but fill
        jpeg(0, 100),
        png()[:20],
        png(0, 10),
        b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x00\x00\x00 no start code",
        b"RIFF\x00\x00\x00\x00WEBPALPH an unknown chunk",
        webp("VP8 ", 0, 0),
    ],
)
def test_bytes_that_arent_an_image_it_reads_or_are_cut_short_are_none(data):
    assert art.sniff(data) is None


@given(st.binary(max_size=200))
def test_any_bytes_at_all_are_read_or_none_never_an_error(data):
    for start in (b"", b"\xff\xd8", b"\x89PNG\r\n\x1a\n", b"RIFF\x00\x00\x00\x00WEBPVP8L"):
        found = art.sniff(start + data)
        assert found is None or (found.width > 0 and found.height > 0)


def test_an_image_too_large_too_small_or_unreadable_says_why_in_words_to_act_on():
    assert art.problem(jpeg(), art.sniff(jpeg())) == ""
    assert art.problem(b"x", None) == "it isn't an image MusiKata can read (JPEG, PNG or WebP)"
    huge = art.ImageInfo("png", 10_000, 9_000)
    assert art.problem(b"x", huge) == (
        "it is 10000 × 9000, too large to use: scale it down below 50 megapixels first"
    )
    assert art.problem(b"x", art.ImageInfo("png", 1, 1)) == (
        "it is only 1 × 1, too small to be a cover"
    )
    assert art.problem(b"x" * (art.MAX_BYTES + 1), None).startswith("it is 50.0 MB, too large")
    assert art.problem(b"x", art.ImageInfo("png", art.MIN_SIDE, 4000)) == ""  # not square: fine


def test_sizes_are_said_in_kilobytes_then_megabytes():
    assert [art.size_text(n) for n in (10, 318 * 1024, 2_500_000)] == ["1 KB", "318 KB", "2.4 MB"]


def test_what_is_converted_and_shrunk_before_it_is_written():
    """R5.3: larger than 1200 is shrunk to embed; a CMYK JPEG or a WebP is converted to embed, and
    anything but an RGB JPEG to be cover.jpg."""
    rgb, cmyk = art.ImageInfo("jpeg", 1200, 1200), art.ImageInfo("jpeg", 600, 600, cmyk=True)
    pic, web = art.ImageInfo("png", 1400, 900), art.ImageInfo("webp", 300, 300)
    assert [art.needs_converting(i, jpeg=False) for i in (rgb, cmyk, pic, web)] == [
        False, True, False, True]  # fmt: skip
    assert [art.needs_converting(i, jpeg=True) for i in (rgb, cmyk, pic, web)] == [
        False, True, True, True]  # fmt: skip
    assert [art.needs_shrinking(i) for i in (rgb, cmyk, pic, web)] == [False, False, True, False]
    assert art.needs_shrinking(rgb, side=1000)


# ---------- what the dialog lists for an album (R5.2) ----------

COVER = jpeg(1200, 1200)
SMALL = jpeg(500, 500) + b" an older one"
BACK_PNG = png(1400, 1400)
OLD_BACK = jpeg(500, 500) + b" a back cover"


def song(n, *pictures, typed=True):
    return SongArt(f"LD/GH/{n:02d}.flac", tuple(pictures), typed)


def front(data):
    return Picture(FRONT, "image/jpeg", data)


def glass_harbor(embedded=10, more=()):
    """T02's album: cover.jpg in the folder, embedded in `embedded` of its 10 songs (the rest
    with the smaller one), back.png beside it, and a back cover in two songs."""
    songs = [
        song(n, front(COVER if n <= embedded else SMALL),
             *([Picture(4, "image/jpeg", OLD_BACK)] if n in (3, 7) else []))
        for n in range(1, 11)
    ]  # fmt: skip
    images = [FolderImage("LD/GH", "back.png", BACK_PNG), FolderImage("LD/GH", "cover.jpg", COVER),
              *more]  # fmt: skip
    return songs, images


def listed(album):
    return [(c.title, c.detail) for c in album.candidates]


def test_t02s_album_lists_cover_jpg_same_as_embedded_first_then_the_others_with_their_notes():
    songs, images = glass_harbor(embedded=8)
    album = art.gather(songs, images)
    assert listed(album) == [
        ("cover.jpg in the folder", "1200 × 1200 · same as embedded"),
        ("back.png in the folder", "1400 × 1400 · named as a back cover"),
        ("Embedded in 2 songs", "500 × 500 · lower resolution"),
        ("Back cover embedded in 2 songs", "500 × 500 · embedded as the back cover"),
    ]
    assert album.current.line == "Current · 1200 × 1200 JPEG · 1 KB"
    assert (album.current.where, album.current.tone) == ("Embedded in 8 of 10", "warn")
    assert art.chosen_first(album) == art.key_of(COVER)
    assert album.folders == ("LD/GH",)


def test_the_current_cover_is_the_one_most_songs_have_else_the_folders_else_none():
    songs, images = glass_harbor()
    current = art.gather(songs, images).current
    assert (current.key, current.where, current.tone) == (
        art.key_of(COVER), "Embedded in 10 of 10", "ok")  # fmt: skip
    bare = [song(n) for n in range(1, 4)]
    current = art.gather(bare, images).current
    assert (current.key, current.where) == (art.key_of(COVER), "cover.jpg in the folder")
    named = [FolderImage("A", "Folder.PNG", png()), FolderImage("A", "aaa.jpg", jpeg() * 3)]
    assert art.current_of(bare, named).where == "Folder.PNG in the folder"
    none = art.gather(bare, [FolderImage("A", "notes.txt", b"text")]).current
    assert (none.key, none.line, none.where) == (None, "No album art", "")
    broken = art.current_of([song(1, front(b"\xff\xd8 broken"))], [])
    assert broken.line == "Current · unreadable · 1 KB"


def test_each_set_of_bytes_is_listed_once_the_added_first_the_latest_on_top():
    songs, images = glass_harbor()
    added = [Added("dropped", "scan.jpg", jpeg(800, 800)), Added("pasted", "", png(900, 900)),
             Added("chosen", "Front.webp", webp("VP8 ", 1000, 1000)),
             Added("dropped", "again.jpg", COVER)]  # fmt: skip
    album = art.gather(songs, images, added)
    titles = [c.title for c in album.candidates]
    assert titles[:4] == ["Dropped: again.jpg", "Chosen: Front.webp", "Pasted image",
                          "Dropped: scan.jpg"]  # fmt: skip
    assert "cover.jpg in the folder" not in titles  # its bytes are the dropped one's
    assert art.chosen_first(album) == art.key_of(COVER)
    assert album.candidate(art.key_of(COVER)).note == "same as embedded"


def test_an_image_that_cant_be_used_is_listed_with_why_and_never_chosen_first():
    songs = [song(1, front(b"\xff\xd8 cut"))]
    images = [
        FolderImage("A", "cover.jpg", b"not an image"),
        FolderImage("A", "gone.jpg", None, "x"),
        FolderImage("A", "tiny.png", png(4, 4)),
    ]
    album = art.gather(songs, images)
    assert [(c.title, c.detail) for c in album.candidates] == [
        ("cover.jpg in the folder", "It isn't an image MusiKata can read (JPEG, PNG or WebP)"),
        ("tiny.png in the folder", "It is only 4 × 4, too small to be a cover"),
        ("Embedded in 1 song", "It isn't an image MusiKata can read (JPEG, PNG or WebP)"),
    ]
    assert art.chosen_first(album) is None
    ok = art.gather(songs, [*images, FolderImage("A", "scan.png", png())])
    assert art.chosen_first(ok) == art.key_of(png())


def test_folder_images_are_listed_in_r5_1s_order_and_back_covers_named_as_such():
    images = [FolderImage("A", n, d) for n, d in (
        ("zz big.jpg", jpeg(2000, 2000) * 2), ("Front.jpg", jpeg(10 + 90, 100)),
        ("CD1.jpg", jpeg(300, 300)), ("Album.png", png(100, 100)), ("inlay-scan.png", png(64, 64)),
        ("small.jpg", jpeg(400, 300) + b"bigger file"))]  # fmt: skip
    album = art.gather([], images)
    assert [c.title.split(" in ")[0] for c in album.candidates] == [
        "Front.jpg", "Album.png", "zz big.jpg", "small.jpg", "CD1.jpg", "inlay-scan.png",
    ]  # fmt: skip
    notes = {c.title.split(" in ")[0]: c.note for c in album.candidates}
    assert notes["CD1.jpg"] == notes["inlay-scan.png"] == "named as a back cover"
    assert notes["small.jpg"] == "lower resolution" and notes["zz big.jpg"] == ""
    assert [
        art.is_back(n)
        for n in (
            "Back.jpg",
            "rear cover.png",
            "disc2.jpg",
            "Cover.jpg",
            "backdrop.jpg",
            "cdcover.png",
        )
    ] == [  # fmt: skip
        True,
        True,
        True,
        False,
        False,
        False,
    ]


def test_mp4s_untyped_pictures_and_cmyk_and_several_folders_are_named_as_they_are():
    songs = [song(1, front(COVER), Picture(None, "image/png", png(600, 600)), typed=False),
             song(2, Picture(8, "image/png", png(300, 300)))]  # fmt: skip
    images = [FolderImage("A/CD1", "cover.jpg", jpeg(900, 900, 4)),
              FolderImage("A/CD2", "cover.jpg", COVER)]  # fmt: skip
    album = art.gather(songs, images)
    assert listed(album) == [
        ("cover.jpg in CD1", "900 × 900 · CMYK: made RGB when saved"),
        ("cover.jpg in CD2", "1200 × 1200 · same as embedded"),
        ("Picture embedded in 1 song", "600 × 600 · lower resolution"),
        ("Artist embedded in 1 song", "300 × 300 · embedded as the artist"),
    ]
    assert album.folders == ("A/CD1", "A/CD2")
    assert songs[0].cover.data == COVER and songs[0].others == (songs[0].pictures[1],)
    assert songs[1].cover is None and song(3, typed=False).cover is None


# ---------- what saving does (R5.3) ----------

ROOT = "/m"


def album_of(songs, images, folders=("LD/GH",)):
    return art.gather(songs, images, folders=folders)


def changes(p):
    return [(j.path, sorted(j.changes)) for j in p.jobs]


def test_the_chosen_cover_already_everywhere_is_no_change_and_the_button_says_done():
    """T02: cover.jpg chosen, embedded in every song and the folder's: "No change", Done."""
    songs, images = glass_harbor()
    album = album_of(songs, images)
    chosen = album.candidate(art.key_of(COVER))
    p = art.plan(album, art.same_forms(COVER), Options(), ROOT)
    assert p == art.Plan()
    assert (
        art.footer(p, Options(), chosen) == "No change: the chosen cover is already on every song."
    )
    assert art.save_label(p) == "Done"


def test_embed_writes_the_cover_into_each_song_that_hasnt_it():
    songs, images = glass_harbor(embedded=8)
    album = album_of(songs, images)
    p = art.plan(album, art.same_forms(COVER), Options(), ROOT)
    assert changes(p) == [("/m/LD/GH/09.flac", ["cover"]), ("/m/LD/GH/10.flac", ["cover"])]
    assert p.jobs[0].changes["cover"] == Picture(FRONT, "image/jpeg", COVER)
    assert (p.embeds, p.removes, p.folders) == (2, 0, ())
    chosen = album.candidate(art.key_of(COVER))
    assert art.footer(p, Options(), chosen) == "Embeds the cover in 2 songs"
    assert art.save_label(p) == "Save 2 files"
    off = art.plan(album, art.same_forms(COVER), Options(embed=False), ROOT)
    assert off.jobs == ()


def test_save_as_cover_jpg_writes_each_folder_whose_cover_jpg_isnt_it_in_its_own_case():
    songs, _ = glass_harbor()
    album = album_of(songs, [FolderImage("LD/GH", "Cover.JPG", SMALL)])
    p = art.plan(album, art.same_forms(COVER), Options(), ROOT)
    assert [(j.path, j.changes) for j in p.jobs] == [("/m/LD/GH/Cover.JPG", {"image": COVER})]
    assert art.footer(p, Options(), album.candidates[0]) == "Writes cover.jpg"
    bare = album_of(songs, [], folders=("LD/GH", "LD/GH/CD2"))
    p = art.plan(bare, art.same_forms(COVER), Options(), ROOT)
    assert [j.path for j in p.jobs] == ["/m/LD/GH/cover.jpg", "/m/LD/GH/CD2/cover.jpg"]
    assert art.footer(p, Options(), bare.candidates[0]) == "Writes cover.jpg in 2 folders"
    at_root = art.plan(album_of(songs, [], folders=("",)), art.same_forms(COVER), Options(), ROOT)
    assert [j.path for j in at_root.jobs] == ["/m/cover.jpg"]
    assert art.save_label(art.Plan(at_root.jobs)) == "Save 1 file"


def test_shrink_embeds_the_shrunk_form_and_cover_jpg_keeps_the_full_size():
    songs, images = glass_harbor()
    album = album_of(songs, [])
    forms = Forms(embed=jpeg(3000, 3000), shrunk=COVER, folder=jpeg(3000, 3000))
    p = art.plan(album, forms, Options(), ROOT)  # the songs have the shrunk one already
    assert [(j.path, j.changes) for j in p.jobs] == [("/m/LD/GH/cover.jpg",
                                                      {"image": jpeg(3000, 3000)})]  # fmt: skip
    big = art.plan(album, forms, Options(shrink=False), ROOT)
    assert big.embeds == 10 and big.jobs[0].changes["cover"].data == jpeg(3000, 3000)
    png_forms = Forms(png(800, 800), None, jpeg(800, 800))
    p = art.plan(album, png_forms, Options(folder=False), ROOT)
    assert p.jobs[0].changes["cover"] == Picture(FRONT, "image/png", png(800, 800))


def test_remove_other_embedded_images_takes_them_from_each_song_that_has_any():
    songs, images = glass_harbor()
    album = album_of(songs, images)
    options = Options(remove_others=True)
    p = art.plan(album, art.same_forms(COVER), options, ROOT)
    assert changes(p) == [("/m/LD/GH/03.flac", ["others"]), ("/m/LD/GH/07.flac", ["others"])]
    assert p.jobs[0].changes["others"] == ()
    chosen = album.candidate(art.key_of(COVER))
    assert art.footer(p, options, chosen) == "Removes the other images from 2 songs"
    both = art.plan(album, art.same_forms(SMALL), options, ROOT)
    assert art.footer(both, options, chosen) == (
        "Embeds the cover in 10 songs, removes the other images from 2 songs and writes cover.jpg"
    )
    assert sorted(both.jobs[2].changes) == ["cover", "others"]


def test_the_footer_says_why_nothing_can_be_saved():
    songs, images = glass_harbor()
    album = album_of(songs, images)
    nowhere = Options(embed=False, folder=False)
    assert art.footer(art.Plan(), nowhere, album.candidates[0]) == (
        "No change: choose where the cover goes"
    )
    assert art.footer(art.Plan(), Options(), None) == (
        "Choose a cover, or drop, paste or choose an image"
    )
    bad = art.gather([], [FolderImage("A", "x.jpg", b"junk")]).candidates[0]
    assert art.footer(art.Plan(), Options(), bad) == (
        "This image can't be used: it isn't an image MusiKata can read (JPEG, PNG or WebP)"
    )
    assert art.description_of("Glass Harbor", art.Plan()) == "Album art: Glass Harbor"
    assert art.description_of("", art.Plan()) == "Album art"


def test_save_cover_to_folder_extracts_the_cover_most_songs_have_embedded():
    """R5.5: the embedded cover, as cover.jpg; none when no song has one."""
    songs, images = glass_harbor(embedded=7)
    album = album_of(songs, [])
    assert art.extract(album).key == art.key_of(COVER)
    assert art.extract(album_of([song(1), song(2)], images)) is None
    only = Options(embed=False, folder=True, shrink=False)
    p = art.plan(album, art.same_forms(COVER), only, ROOT)
    assert [(j.path, j.changes) for j in p.jobs] == [("/m/LD/GH/cover.jpg", {"image": COVER})]


# ---------- writing cover.jpg ----------


class Trash:
    def __init__(self, folder, works=True):
        self.folder, self.works, self.got = folder, works, []

    def __call__(self, path):
        if not self.works:
            return False
        with open(path, "rb") as f:
            self.got.append(f.read())
        os.remove(path)
        return True


def test_cover_jpg_is_written_and_the_older_one_goes_to_the_trash(tmp_path):
    path = str(tmp_path / "cover.jpg")
    trash = Trash(tmp_path)
    new = art.save_image(path, COVER, trash)
    assert (new.before, new.after, trash.got) == (None, COVER, [])
    assert new.size == len(COVER) and new.mtime_ns == os.stat(path).st_mtime_ns
    again = art.save_image(path, SMALL, trash)
    assert (again.before, again.after, trash.got) == (COVER, SMALL, [COVER])
    with open(path, "rb") as f:
        assert f.read() == SMALL
    same = art.save_image(path, SMALL, trash)
    assert same.before == same.after == SMALL and trash.got == [COVER]
    gone = art.save_image(path, None, trash)
    assert (gone.before, gone.after) == (SMALL, None) and not os.path.exists(path)
    assert art.save_image(path, None, trash) == art.ImageWritten(path, None, None)
    assert os.listdir(tmp_path) == []  # no copy left behind


def test_a_cover_jpg_that_cant_go_to_the_trash_or_be_written_is_left_as_it_was(tmp_path):
    path = str(tmp_path / "cover.jpg")
    with open(path, "wb") as f:
        f.write(SMALL)
    with pytest.raises(WriteError, match="it couldn't be moved to the trash, so it was left"):
        art.save_image(path, COVER, Trash(tmp_path, works=False))
    with open(path, "rb") as f:
        assert f.read() == SMALL
    assert os.listdir(tmp_path) == ["cover.jpg"]
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(WriteError, match="its folder can't be written to"):
            art.save_image(path, COVER, Trash(tmp_path))
    finally:
        os.chmod(tmp_path, stat.S_IRWXU)
    with open(path, "rb") as f:
        assert f.read() == SMALL


def test_a_failed_replace_says_the_older_one_is_in_the_trash(tmp_path, monkeypatch):
    path = str(tmp_path / "cover.jpg")
    with open(path, "wb") as f:
        f.write(SMALL)

    def refuse(src, dst):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(art.os, "replace", refuse)
    with pytest.raises(WriteError, match="the older one is in the trash"):
        art.save_image(path, COVER, Trash(tmp_path))
    assert os.listdir(tmp_path) == []


def test_a_saves_writer_writes_images_itself_and_hands_songs_on(tmp_path):
    songs = []
    write = art.writer(lambda job: songs.append(job) or "a song written", Trash(tmp_path))
    assert write(Job("/m/a.flac", {"title": "T"})) == "a song written"
    image = write(Job(str(tmp_path / "cover.jpg"), {"image": COVER}))
    assert isinstance(image, art.ImageWritten) and [j.path for j in songs] == ["/m/a.flac"]
    with pytest.raises(ValueError, match="an image is its bytes"):
        write(Job(str(tmp_path / "cover.jpg"), {"image": "not bytes"}))
    w = Written("/m/a.flac", None, None, "h", 1, 1)
    assert art.written_songs([w, image]) == [w]


def test_the_trash_is_the_systems_its_folder_made_when_it_isnt_there(tmp_path):
    """Principle 5: the older cover.jpg goes to the trash, not away; on Linux the user's trash
    folder is made when it isn't there (own_home points it into the test's folder)."""
    path = tmp_path / "Music" / "cover.jpg"
    path.parent.mkdir()
    path.write_bytes(SMALL)
    assert art.to_trash(str(path)) and not path.exists()
    assert not art.to_trash(str(path))  # gone: nothing to move
