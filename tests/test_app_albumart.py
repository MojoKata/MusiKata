"""The Album art dialog in the running app (src/musikata/albumart.py, AlbumArtDialog.qml; R5.2 to
R5.5): what Qt makes of an image before it is written (a CMYK JPEG made RGB, a WebP made a JPEG
or a PNG, a large image shrunk to 1200 × 1200 as a JPEG at quality 90, cover.jpg a JPEG with
transparency laid on white); the dialog over an album's real files, its candidates, the choice and
the options, saving through the batch and the change history, with progress, Cancel, the files
that failed and Retry, and Undo; images dropped, chosen and pasted, and why one can't be used;
Save cover to folder; and the dialog in the window, opened from an album's page.

Why: saving rewrites every song of the album and its cover.jpg at once; an image converted badly
is embedded broken in all of them, an image from outside that crashes the dialog loses the user's
choice, and a save not kept in the history can't be taken back."""

import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeClock
from PySide6.QtCore import QBuffer, QMimeData, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from musikata import albumart, app, layout, tour
from musikata.albumart import AlbumArt, ArtError, ArtImages, Target, forms_of, prepare
from musikata.history import ChangeHistory
from musikata_core import art, db, history, scanner, settings, tags
from musikata_core.tags import WriteError

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

WAIT = 10_000
NOW = datetime(2026, 11, 25, 20, 45, 12, tzinfo=UTC)
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"


def image(w, h, color="#3366cc", fmt="PNG", alpha=False, cmyk=False, quality=90):
    """An image made by Qt, as the bytes of `fmt`."""
    kind = (QImage.Format.Format_CMYK8888 if cmyk else QImage.Format.Format_ARGB32 if alpha
            else QImage.Format.Format_RGB32)  # fmt: skip
    if cmyk:
        rgb = QImage(w, h, QImage.Format.Format_RGB32)
        rgb.fill(QColor(color))
        img = rgb.convertToFormat(kind)
    else:
        img = QImage(w, h, kind)
        img.fill(QColor(0, 0, 0, 0) if alpha else QColor(color))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    assert img.save(buf, fmt, quality)
    return bytes(buf.data().data())


def read(path):
    with open(path, "rb") as f:
        return f.read()


def decoded(data):
    return QImage.fromData(data)


# ---------- what an image is written as ----------


def test_an_rgb_jpeg_no_larger_than_1200_is_written_as_it_is(qapp):
    data = image(800, 800, fmt="JPEG")
    info = art.sniff(data)
    assert forms_of(data, info, decoded(data)) == art.same_forms(data)


def test_a_large_image_is_shrunk_to_1200_as_a_jpeg_and_cover_jpg_keeps_its_size(qapp):
    """R5.3: shrunk to 1200 × 1200 (keeping its shape) and saved as JPEG at quality 90 before
    it is embedded; cover.jpg keeps the full size, and is a JPEG."""
    data = image(2400, 1800)
    forms = forms_of(data, art.sniff(data), decoded(data))
    assert forms.embed == data  # a PNG embeds as it is when it isn't shrunk
    assert art.sniff(forms.shrunk) == art.ImageInfo("jpeg", 1200, 900)
    assert art.sniff(forms.folder) == art.ImageInfo("jpeg", 2400, 1800)
    smaller = forms_of(data, art.sniff(data), decoded(data), side=600)
    assert art.sniff(smaller.shrunk).width == 600


def test_a_cmyk_jpeg_is_made_rgb_wherever_it_is_written(qapp):
    data = image(600, 400, fmt="JPEG", cmyk=True)
    assert art.sniff(data).cmyk
    forms = forms_of(data, art.sniff(data), decoded(data))
    for written in (forms.embed, forms.folder):
        assert art.sniff(written) == art.ImageInfo("jpeg", 600, 400)
    assert forms.shrunk is None


def test_a_webp_embeds_as_a_jpeg_or_with_transparency_a_png(qapp):
    opaque = image(300, 300, fmt="WEBP")
    forms = forms_of(opaque, art.sniff(opaque), decoded(opaque))
    assert art.sniff(forms.embed).kind == "jpeg" and art.sniff(forms.folder).kind == "jpeg"
    clear = image(300, 300, fmt="WEBP", alpha=True)
    assert art.sniff(clear).alpha
    forms = forms_of(clear, art.sniff(clear), decoded(clear))
    assert art.sniff(forms.embed).kind == "png" and art.sniff(forms.folder).kind == "jpeg"


def test_transparency_is_laid_on_white_in_cover_jpg(qapp):
    clear = image(64, 64, alpha=True)
    forms = forms_of(clear, art.sniff(clear), decoded(clear))
    pixel = decoded(forms.folder).pixelColor(10, 10)
    assert (pixel.red(), pixel.green(), pixel.blue()) == (255, 255, 255)


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (b"just some text\n", "it isn't an image MusiKata can read (JPEG, PNG or WebP)"),
        (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR\x00\x00\x01\x00\x00\x00\x01\x00\x08\x02"
            b"\x00\x00\x00 and then nothing an image is made of",
            "it can't be decoded",
        ),
        (None, "it is only 8 × 8, too small to be a cover"),
    ],
)
def test_an_image_that_cant_be_used_is_prepared_with_why_never_an_error(qapp, data, why):
    ready = prepare(data if data is not None else image(8, 8))
    assert ready.forms is None and ready.thumb.isNull() and ready.problem.startswith(why)


# The dialog's thread decodes while a cover is decoded on another thread, as QML's pixmap reader
# does in covers.Covers: Qt's reader takes a mutex of its own to find the image's handler, so a
# decode there that called into Python (a Python-made QBuffer's methods take the GIL) waited on
# the GIL while a cover decoded with the GIL held (QImage.fromData, as covers.thumbnail once did)
# waited on that mutex, and neither ever ran again. In a process of its own, as a deadlock can't
# be ended from inside it. (test_app_covers.py has the other side: a decode that holds the GIL.)
CROSSED = """
import sys, threading
from PySide6.QtGui import QGuiApplication
from musikata import albumart, covers
app = QGuiApplication([])
data = open(sys.argv[1], "rb").read()
inside = threading.Event()
def dialog():
    inside.set()
    albumart.decode(data)
reading = threading.Thread(target=dialog)
reading.start()
inside.wait()
sum(range(4_000_000))  # the GIL held in one C call, as while the dialog's thread is inside Qt
covers.thumbnail(data, 256)
reading.join()
"""


@pytest.mark.slow
def test_an_image_decoded_while_a_cover_is_decoded_on_another_thread_never_deadlocks(tmp_path):
    path = tmp_path / "cover.png"
    path.write_bytes(image(64, 64))
    src = os.pathsep.join(p for p in (os.path.join(ROOT, "src"), os.environ.get("PYTHONPATH")) if p)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=src)
    try:
        done = subprocess.run([sys.executable, "-c", CROSSED, str(path)], env=env,
                              capture_output=True, text=True, timeout=30)  # fmt: skip
    except subprocess.TimeoutExpired:
        pytest.fail("the two decodes deadlocked")
    assert done.returncode == 0, done.stderr


def test_a_prepared_images_thumbnail_is_small_and_a_small_one_stays_as_it_is(qapp):
    ready = prepare(image(900, 600, fmt="JPEG"))
    assert (ready.thumb.width(), ready.thumb.height()) == (168, 112)
    assert prepare(image(64, 64)).thumb.width() == 64


def test_a_failed_encoding_says_so(qapp, monkeypatch):
    monkeypatch.setattr(QImage, "save", lambda *a: False)
    with pytest.raises(ArtError, match="it couldn't be made a PNG"):
        albumart.encoded(QImage(4, 4, QImage.Format.Format_RGB32), "PNG")


# ---------- an album's files, and the dialog over them ----------

COVER = demo.cover_jpeg(11, 64)  # embedded in the songs, and the folder's cover.jpg


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """Six FLACs, each with COVER embedded, made once."""
    d = tmp_path_factory.mktemp("made")
    out = []
    for n in range(1, 7):
        path = str(d / f"{n:02d}.flac")
        demo.encode(path, "flac", 0.1, 330 + 55 * n)
        t = {"title": f"Song {n}", "artist": "Lumen Drift", "album": "Glass Harbor",
             "albumartist": "Lumen Drift", "track": n}  # fmt: skip
        demo.tag(path, demo.Song(path, "flac", t, cover=(11, 64)))
        out.append(path)
    return out


def index_all(index, music):
    """The index's rows of every song and image under `music`, as a scan reads them."""
    batch, images = [], {}
    for folder, _dirs, files in os.walk(music):
        rel_folder = os.path.relpath(folder, music).replace(os.sep, "/")
        rel_folder = "" if rel_folder == "." else rel_folder
        for name in sorted(files):
            full = os.path.join(folder, name)
            st = os.stat(full)
            rel = f"{rel_folder}/{name}" if rel_folder else name
            if art.is_image(name):
                images.setdefault(rel_folder, []).append(
                    art.Image(name, st.st_size, st.st_mtime_ns)
                )
            elif name.endswith(".flac"):
                t, info = tags.read(full)
                batch.append(
                    scanner.Read(scanner.Seen(rel, st.st_size, st.st_mtime_ns), t, info, rel)
                )
    index.write(lambda c: scanner.write_batch(c, batch, {}, images)).result()


class Trash:
    def __init__(self):
        self.got = []

    def __call__(self, path):
        with open(path, "rb") as f:
            self.got.append(f.read())
        os.remove(path)
        return True


@pytest.fixture
def root(made, tmp_path):
    """Glass Harbor: six songs with COVER embedded, cover.jpg the same, and back.png: (music,
    index, album id)."""
    music = tmp_path / "Music"
    folder = music / "LD" / "GH"
    folder.mkdir(parents=True)
    (music / ".musikata").mkdir()
    for n, src in enumerate(made, 1):
        shutil.copyfile(src, folder / f"{n:02d}.flac")
    (folder / "cover.jpg").write_bytes(COVER)
    (folder / "back.png").write_bytes(image(200, 200, "#cc3366"))
    index = db.Index(str(tmp_path / "musikata.db"))
    index_all(index, str(music))
    (album_id,) = index.read().execute("SELECT id FROM album").fetchone()
    yield str(music), index, album_id
    index.close()


def write_song(job):
    return tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)


def make(root, write=write_song, available=lambda: True):
    music, index, _ = root
    h = ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop",
                      settings.RootTags(), executor=ThreadPoolExecutor(1), watching=False,
                      message_ms=60_000)  # fmt: skip
    saved, trash = [], Trash()
    a = AlbumArt(music, index.read, write, h, saved=saved.extend, trash=trash,
                 executor=ThreadPoolExecutor(1), available=available)  # fmt: skip
    a.history_, a.saved_, a.trash_ = h, saved, trash
    return a


@pytest.fixture
def dialog(root, qapp):
    a = make(root)
    yield a
    a.shut()
    a.history_.close()


def opened(a, qtbot, album_id):
    a.openAlbum(album_id)
    qtbot.waitUntil(lambda: not a.property("loading"), timeout=WAIT)


def titles(a):
    return [(c["title"], c["detail"], c["chosen"]) for c in a.property("candidates")]


def key_of(a, title):
    return next(c["key"] for c in a.property("candidates") if c["title"].startswith(title))


def saved(a, qtbot):
    with qtbot.waitSignal(a.savingChanged, timeout=WAIT, check_params_cb=lambda: True):
        a.save()
    qtbot.waitUntil(lambda: not a.property("saving"), timeout=WAIT)


def test_the_dialog_shows_the_current_cover_and_the_covers_found_and_says_no_change(
    root, dialog, qtbot
):
    """R5.2, T02: the current cover with its size, kind, file size and where it is; the covers
    found, the current one chosen; "No change" when it is already everywhere, and Done."""
    music, _, album_id = root
    dialog.close()  # not open: nothing to close, save or retry
    dialog.save()
    dialog.retry()
    assert not dialog.property("opened") and not dialog.property("saving")
    opened(dialog, qtbot, album_id)
    assert dialog.property("title") == "Album art · Glass Harbor"
    current = dialog.property("current")
    assert current["line"].startswith("Current · 64 × 64 JPEG · ")
    assert (current["where"], current["tone"]) == ("Embedded in 6 of 6", "ok")
    assert current["source"].startswith("image://albumart/large-")
    assert titles(dialog) == [
        ("cover.jpg in the folder", "64 × 64 · same as embedded", True),
        ("back.png in the folder", "200 × 200 · named as a back cover", False),
    ]
    assert dialog.property("footer") == "No change: the chosen cover is already on every song."
    assert dialog.property("saveLabel") == "Done" and dialog.property("canSave")
    assert dialog.property("options") == {
        "embed": True, "folder": True, "shrink": True, "removeOthers": False,
        "shrinkLabel": "Shrink to 1200 × 1200 before embedding"}  # fmt: skip
    key = key_of(dialog, "cover.jpg")
    assert not dialog.images.requestImage(key, None, None).isNull()
    dialog.save()  # Done: closes, writing nothing
    assert not dialog.property("opened") and dialog.saved_ == []


def test_choosing_another_cover_saves_it_everywhere_as_one_entry_and_undo_puts_it_back(
    root, dialog, qtbot
):
    """R5.3 and R4.9: the songs' covers and cover.jpg in one save, the older cover.jpg to the
    trash, the message with Undo; Undo puts every song's cover and cover.jpg back."""
    music, index, album_id = root
    folder = os.path.join(music, "LD", "GH")
    opened(dialog, qtbot, album_id)
    dialog.choose(key_of(dialog, "back.png"))
    assert dialog.property("footer") == "Embeds the cover in 6 songs and writes cover.jpg"
    assert dialog.property("saveLabel") == "Save 7 files"
    saved(dialog, qtbot)
    assert not dialog.property("opened") and dialog.property("failed") == {}
    back = read(os.path.join(folder, "back.png"))
    new_jpg = read(os.path.join(folder, "cover.jpg"))
    assert art.sniff(new_jpg) == art.ImageInfo("jpeg", 200, 200) and dialog.trash_.got == [COVER]
    for n in range(1, 7):
        pictures = tags.pictures(os.path.join(folder, f"{n:02d}.flac"))
        assert [(p.type, p.data) for p in pictures] == [(3, back)]
    assert len(dialog.saved_) == 6  # the songs' rows; cover.jpg's folder is rescanned
    message = dialog.history_.property("message")
    assert message["text"] == "Saved 7 files" and message["undo"]
    entry = history.read(history.folder_of(music), message["undo"])
    assert (entry.action, entry.description) == ("album-art", "Album art: Glass Harbor")
    with qtbot.waitSignal(dialog.history_.messageChanged, timeout=WAIT):
        dialog.history_.undoMessage()
    qtbot.waitUntil(lambda: dialog.history_.property("message").get("text", "").startswith(
        "Undone"), timeout=WAIT)  # fmt: skip
    assert read(os.path.join(folder, "cover.jpg")) == COVER
    assert tags.pictures(os.path.join(folder, "01.flac"))[0].data == COVER


def test_each_option_changes_what_saving_writes(root, dialog, qtbot):
    music, _, album_id = root
    opened(dialog, qtbot, album_id)
    dialog.choose(key_of(dialog, "back.png"))
    dialog.setOption("folder", False)
    assert dialog.property("footer") == "Embeds the cover in 6 songs"
    dialog.setOption("embed", False)
    assert dialog.property("footer") == "No change: choose where the cover goes"
    dialog.setOption("removeOthers", True)
    assert dialog.property("options")["removeOthers"] is True
    assert dialog.property("footer") == "No change: the chosen cover is already on every song."
    dialog.setOption("folder", True)
    assert [os.path.basename(j.path) for j in dialog.plan().jobs] == ["cover.jpg"]
    with pytest.raises(ValueError, match="no such option"):
        dialog.setOption("everything", True)
    dialog.choose("not a key")  # nothing
    assert dialog.plan().jobs


def test_an_image_dropped_or_chosen_is_added_and_chosen_and_one_that_cant_be_says_why(
    root, dialog, qtbot, tmp_path
):
    """R5.2.1: dropped, or chosen with Choose file…; a file that isn't an image, a web address,
    one gone or too large is refused with why, the choice kept."""
    music, _, album_id = root
    opened(dialog, qtbot, album_id)
    good = tmp_path / "scan.png"
    good.write_bytes(image(500, 500, "#33aa66"))
    with qtbot.waitSignal(dialog.changed, timeout=WAIT):
        dialog.addUrls([QUrl.fromLocalFile(str(good))])
    qtbot.waitUntil(lambda: titles(dialog)[0][0] == "Dropped: scan.png", timeout=WAIT)
    assert titles(dialog)[0] == ("Dropped: scan.png", "500 × 500", True)
    assert dialog.property("message") == ""
    text = tmp_path / "notes.txt"
    text.write_text("not an image")
    dialog.chooseFiles([QUrl.fromLocalFile(str(text)).toString()])
    qtbot.waitUntil(lambda: dialog.property("message") != "", timeout=WAIT)
    assert dialog.property("message") == (
        "notes.txt: it isn't an image MusiKata can read (JPEG, PNG or WebP)"
    )
    assert titles(dialog)[0][2]  # the dropped one still chosen
    dialog.addUrls([QUrl("https://example.com/cover.jpg")])
    assert dialog.property("message") == (
        "cover.jpg isn't a file on this computer: save the image to a file first, then drop that"
    )
    dialog.addUrls([str(tmp_path / "gone.jpg")])
    qtbot.waitUntil(lambda: "gone.jpg" in dialog.property("message"), timeout=WAIT)
    assert dialog.property("message") == "gone.jpg: it isn't there any more"
    dialog.addUrls([QUrl.fromLocalFile(str(tmp_path))])
    qtbot.waitUntil(lambda: "folder" in dialog.property("message"), timeout=WAIT)
    big = tmp_path / "huge.jpg"
    with open(big, "wb") as f:
        f.truncate(art.MAX_BYTES + 1)
    dialog.addUrls([QUrl.fromLocalFile(str(big))])
    qtbot.waitUntil(lambda: "huge.jpg" in dialog.property("message"), timeout=WAIT)
    assert "too large for a cover" in dialog.property("message")


def test_pasting_takes_the_clipboards_own_bytes_else_its_image_else_says_none(root, dialog, qtbot):
    music, _, album_id = root
    opened(dialog, qtbot, album_id)
    mime = QMimeData()
    mime.setData("image/png", image(300, 300, "#aa33cc"))
    dialog.paste_from(mime, QImage())
    qtbot.waitUntil(lambda: titles(dialog)[0][0] == "Pasted image", timeout=WAIT)
    assert titles(dialog)[0] == ("Pasted image", "300 × 300", True)
    picture = QImage(400, 400, QImage.Format.Format_RGB32)
    picture.fill(QColor("#123456"))
    dialog.paste_from(QMimeData(), picture)
    qtbot.waitUntil(lambda: titles(dialog)[0][1] == "400 × 400", timeout=WAIT)
    copied = os.path.join(music, "copied.png")  # a file copied in the file manager
    with open(copied, "wb") as f:
        f.write(image(500, 500, "#33aa66"))
    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile(copied)])
    dialog.paste_from(files, QImage())
    qtbot.waitUntil(lambda: titles(dialog)[0][0] == "Chosen: copied.png", timeout=WAIT)
    dialog.paste_from(None, QImage())
    assert dialog.property("message") == "There's no image on the clipboard to paste"
    bad = QImage(4000, 1, QImage.Format.Format_RGB32)
    bad.fill(QColor("#000000"))
    with pytest.MonkeyPatch.context() as m:
        m.setattr(QImage, "save", lambda *a: False)
        dialog.paste_from(QMimeData(), bad)
        qtbot.waitUntil(lambda: "couldn't be made" in dialog.property("message"), timeout=WAIT)
    assert dialog.property("message") == "The pasted image: it couldn't be made a PNG"
    dialog.findOnline()
    assert dialog.property("message") == "Finding covers online comes in a later version"


def test_the_files_that_fail_are_listed_with_why_and_retry_saves_them(root, qtbot, qapp):
    """R4.7: the others are saved; the failed ones listed with why, and Retry writes them."""
    music, _, album_id = root
    broken = {"on": True}

    def write(job):
        if broken["on"] and job.path.endswith("02.flac"):
            raise WriteError(job.path, "it is read-only: let it be written to, then try again")
        return write_song(job)

    a = make(root, write)
    try:
        opened(a, qtbot, album_id)
        a.choose(key_of(a, "back.png"))
        saved(a, qtbot)
        assert a.property("opened")  # it stays open for the failures
        assert a.property("failed")["title"] == "1 file wasn't saved"
        assert a.property("failed")["rows"][0]["file"] == "02.flac"
        broken["on"] = False
        with qtbot.waitSignal(a.savingChanged, timeout=WAIT):
            a.retry()
        qtbot.waitUntil(lambda: not a.property("saving"), timeout=WAIT)
        assert a.property("failed") == {} and not a.property("opened")
        a.dismissFailed()
    finally:
        a.shut()
        a.history_.close()


def test_more_than_a_few_files_show_progress_and_cancel_stops_between_files(root, qtbot, qapp):
    music, _, album_id = root
    go = threading.Event()

    def write(job):
        go.wait(WAIT / 1000)
        return write_song(job)

    a = make(root, write)
    try:
        opened(a, qtbot, album_id)
        a.choose(key_of(a, "back.png"))
        a.save()
        assert a.property("saving") and not a.property("canSave")
        assert a.property("progress") == {"text": "Saving 0 of 7 files…", "fraction": 0.0}
        a.save()  # a second save waits for the first
        a.openAlbum(album_id)  # and so does opening it again
        a.cancel()
        go.set()
        qtbot.waitUntil(lambda: not a.property("saving"), timeout=WAIT)
        assert a.property("opened") and a.history_.property("message")["text"].startswith(
            "Saved 1 of 7"
        )
        a.cancel()  # not saving: closes
        assert not a.property("opened")
    finally:
        go.set()
        a.shut()
        a.history_.close()


def test_nothing_is_saved_while_the_root_isnt_there(root, qtbot, qapp):
    music, _, album_id = root
    a = make(root, available=lambda: False)
    try:
        opened(a, qtbot, album_id)
        a.choose(key_of(a, "back.png"))
        a.save()
        assert not a.property("saving")
        assert (
            a.property("message") == "Nothing can be saved while the music folder isn't available"
        )
        a.saveToFolder(album_id)
        assert a.history_.property("message")["text"] == a.property("message")
    finally:
        a.shut()
        a.history_.close()


def test_save_cover_to_folder_writes_the_embedded_cover_as_cover_jpg(root, dialog, qtbot):
    """R5.5: without the dialog; the message says when there's nothing to do, or no cover."""
    music, index, album_id = root
    jpg = os.path.join(music, "LD", "GH", "cover.jpg")
    with qtbot.waitSignal(dialog.history_.messageChanged, timeout=WAIT):
        dialog.saveToFolder(album_id)
    assert dialog.history_.property("message")["text"] == "cover.jpg is already the embedded cover"
    os.remove(jpg)
    with qtbot.waitSignal(dialog.history_.messageChanged, timeout=WAIT):
        dialog.saveToFolder(album_id)
    assert read(jpg) == COVER and not dialog.property("opened")
    assert dialog.history_.property("message")["text"] == "Saved 1 file"
    for name in os.listdir(os.path.dirname(jpg)):
        if name.endswith(".flac"):
            tags.save(os.path.join(os.path.dirname(jpg), name), {"cover": None},
                      audio_hash=scanner.audio_hash)  # fmt: skip
    with qtbot.waitSignal(dialog.history_.messageChanged, timeout=WAIT):
        dialog.saveToFolder(album_id)
    assert (
        dialog.history_.property("message")["text"] == "Glass Harbor has no embedded cover to save"
    )
    with qtbot.waitSignal(dialog.history_.messageChanged, timeout=WAIT):
        dialog.saveToFolder(999)
    assert dialog.history_.property("message")["text"] == (
        "This album's songs aren't in the library any more"
    )


def test_an_image_dropped_on_an_albums_cover_opens_the_dialog_with_it_chosen(
    root, dialog, qtbot, tmp_path
):
    """R5.4, from an album's cover in any view and from the Edit tags panel's."""
    music, index, album_id = root
    dropped = tmp_path / "new.png"
    dropped.write_bytes(image(320, 320, "#ff8800"))
    dialog.dropOnAlbum(album_id, [QUrl.fromLocalFile(str(dropped))])
    qtbot.waitUntil(lambda: bool(titles(dialog)) and titles(dialog)[0][0] == "Dropped: new.png",
                    timeout=WAIT)  # fmt: skip
    assert titles(dialog)[0][2] and dialog.property("footer") == (
        "Embeds the cover in 6 songs and writes cover.jpg"
    )
    dialog.close()
    assert not dialog.property("opened") and dialog.property("candidates") == []
    ids = [i for (i,) in index.read().execute("SELECT id FROM song")]
    dialog.dropOnSongs(ids[:2], "2 songs", [QUrl.fromLocalFile(str(dropped)).toString()])
    qtbot.waitUntil(lambda: bool(titles(dialog)) and titles(dialog)[0][0] == "Dropped: new.png",
                    timeout=WAIT)  # fmt: skip
    assert dialog.property("title") == "Album art · Glass Harbor"


def test_songs_on_no_album_are_their_own_and_an_album_gone_says_so(root, dialog, qtbot):
    music, index, album_id = root
    c = index.read()
    assert albumart.target_of_songs(c, [], "x") is None
    index.write(lambda w: w.execute("UPDATE song SET album_id = NULL")).result()
    ids = [i for (i,) in index.read().execute("SELECT id FROM song")]
    found = albumart.target_of_songs(index.read(), ids, "6 songs")
    assert found == Target(
        "6 songs", tuple(f"LD/GH/{n:02d}.flac" for n in range(1, 7)), -1, "LD/GH"
    )
    dialog.openSongs(ids, "6 songs")
    qtbot.waitUntil(lambda: not dialog.property("loading"), timeout=WAIT)
    assert dialog.property("title") == "Album art · 6 songs"
    dialog.openAlbum(album_id)
    qtbot.waitUntil(lambda: not dialog.property("loading"), timeout=WAIT)
    assert dialog.property("message") == "This album's songs aren't in the library any more"
    assert dialog.property("footer") == "" and dialog.property("title") == "Album art"


def test_a_folder_of_songs_opens_on_the_album_most_of_them_are_on_else_on_them(root, dialog, qtbot):
    """R2.9.7's Album art: the folder's songs' album; songs on no album are their own, named as
    the folder is."""
    music, index, album_id = root
    dialog.openFolder("LD/GH", "GH")
    qtbot.waitUntil(lambda: not dialog.property("loading"), timeout=WAIT)
    assert dialog.property("title") == "Album art · Glass Harbor"
    index.write(lambda w: w.execute("UPDATE song SET album_id = NULL")).result()
    dialog.openFolder("LD/GH", "GH")
    qtbot.waitUntil(lambda: not dialog.property("loading"), timeout=WAIT)
    assert dialog.property("title") == "Album art · GH"
    assert albumart.songs_in(index.read(), "LD") == []


def test_what_cant_be_read_is_passed_by_and_logged(tmp_path, caplog):
    music = tmp_path / "Music"
    (music / "A").mkdir(parents=True)
    (music / "A" / "song.flac").write_bytes(b"not a song")
    (music / "A" / "cover.jpg").mkdir()  # a folder named as an image
    (music / "A" / "big.png").write_bytes(b"")
    os.truncate(music / "A" / "big.png", art.MAX_BYTES + 1)
    songs = albumart.read_songs(str(music), ["A/song.flac", "A/song.m4a"])
    assert [(s.path, s.typed, bool(s.error)) for s in songs] == [
        ("A/song.flac", True, True), ("A/song.m4a", False, True)]  # fmt: skip
    images = albumart.read_images(str(music), ["A", "gone"])
    assert [(i.name, i.data, i.error) for i in images] == [("big.png", None, "it is too large")]
    assert "couldn't be listed" in caplog.text


def test_the_thumbnails_are_served_by_their_key_until_cleared(qapp):
    images = ArtImages()
    picture = QImage(4, 4, QImage.Format.Format_RGB32)
    images.put("abc", picture)
    assert images.requestImage("abc?3", None, None).width() == 4
    images.clear()
    assert images.requestImage("abc", None, None).isNull()


def test_a_tours_step_opens_the_dialog_on_the_album_shown_and_closes_it(root, dialog, qtbot):
    music, index, album_id = root

    class Album:
        def property(self, name):
            return album_id

    class Library:
        def property(self, name):
            return Album()

    dialog.go({"art": True}, Library())
    qtbot.waitUntil(lambda: not dialog.property("loading"), timeout=WAIT)
    assert dialog.property("opened")
    dialog.go({"view": "songs"}, Library())
    assert not dialog.property("opened")


# ---------- in the window ----------


@pytest.fixture
def shell(made, tmp_path, qapp, qtbot):
    music = tmp_path / "Music"
    folder = music / "Lumen Drift" / "Glass Harbor"
    folder.mkdir(parents=True)
    for n, src in enumerate(made[:3], 1):
        shutil.copyfile(src, folder / f"{n:02d}.flac")
    (folder / "back.png").write_bytes(image(200, 200, "#cc3366"))
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(str(music), env, FakeClock(datetime.now(UTC) - timedelta(minutes=1)),
                 lambda: ThreadPoolExecutor(1))  # fmt: skip
    s.library.rescan()
    qtbot.waitUntil(lambda: not s.library.scanning, timeout=WAIT * 3)
    s.music_ = str(music)
    s.window.show()
    yield s
    s.close()


def find(shell, name):
    found = []

    def walk(item):
        if item.objectName() == name and item.isVisible():
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    return found


def click(shell, item, button=Qt.MouseButton.LeftButton):
    at = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(shell.window, button, Qt.KeyboardModifier(0), at)


def settled(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.window.grabWindow()


@pytest.mark.slow
def test_album_art_opens_from_an_albums_page_saves_and_closes_with_no_qml_warning(
    shell, qtbot, qtlog
):
    """R5.2 in the window: the album page's Album art opens the dialog, every text in its box;
    a candidate's click chooses it, a checkbox's click sets its option, Save writes the files and
    closes it; Esc closes it, and the window's shortcuts wait while it is open."""
    lib, a = shell.library, shell.art
    (album_id,) = shell.index.read().execute("SELECT id FROM album").fetchone()
    lib.openAlbum(album_id)
    qtbot.waitUntil(lambda: bool(find(shell, "albumArt")), timeout=WAIT)
    click(shell, find(shell, "albumArt")[0])
    qtbot.waitUntil(lambda: a.property("opened") and not a.property("loading"), timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    rows = find(shell, "artCandidate")
    assert len(rows) == 2 and a.property("footer") == "Writes cover.jpg"
    assert a.property("candidates")[1]["chosen"]  # the embedded cover, the current one
    click(shell, rows[0])  # back.png
    assert not shell.edit.property("opened")  # the click never reaches Edit tags behind it
    assert a.property("candidates")[0]["chosen"]
    click(shell, find(shell, "artOption-removeOthers")[0])
    assert a.property("options")["removeOthers"] is True
    assert not shell.edit.property("opened")
    QTest.keyClick(shell.window, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert not shell.edit.property("opened")  # Ctrl+E waits behind the dialog
    with qtbot.waitSignal(shell.changes.messageChanged, timeout=WAIT):
        click(shell, find(shell, "saveArt")[0])
    qtbot.waitUntil(lambda: not a.property("opened"), timeout=WAIT)
    back = read(os.path.join(shell.music_, "Lumen Drift", "Glass Harbor", "back.png"))
    first = os.path.join(shell.music_, "Lumen Drift", "Glass Harbor", "01.flac")
    assert tags.pictures(first)[0].data == back
    click(shell, find(shell, "albumArt")[0])
    qtbot.waitUntil(lambda: a.property("opened") and not a.property("loading"), timeout=WAIT)
    find(shell, "artDialog")[0].forceActiveFocus()
    QTest.keyClick(shell.window, Qt.Key.Key_Escape)
    assert not a.property("opened")
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


@pytest.mark.slow
def test_album_art_opens_from_folders_bar_menu_and_strip_with_no_qml_warning(shell, qtbot, qtlog):
    """R2.9.6 and R2.9.7 in the window: Folders' selection bar and a row's right-click menu offer
    Album art when the songs are one album, and a folder of songs' strip has it; each opens the
    dialog on that album."""
    lib, a = shell.library, shell.art
    folders = lib.property("folders")
    lib.show("folders")
    folders.open("Lumen Drift")
    folders.select_paths(["Lumen Drift/Glass Harbor"])
    qtbot.waitUntil(lambda: bool(find(shell, "artSelection")), timeout=WAIT)
    settled(shell, qtbot)  # the bar laid out: its actions apart, so the click is Album art's alone
    click(shell, find(shell, "artSelection")[0])
    qtbot.waitUntil(lambda: a.property("opened") and not a.property("loading"), timeout=WAIT)
    assert a.property("title") == "Album art · Glass Harbor"
    settled(shell, qtbot)
    a.close()
    folders.property("model").clearSelection()
    folders.setMode("list")

    def row():
        found = [r for r in find(shell, "folderListRow") if r.property("name") == "Glass Harbor"]
        return found[0] if found else None

    qtbot.waitUntil(lambda: row() is not None, timeout=WAIT)
    click(shell, row(), Qt.MouseButton.RightButton)
    item = shell.window.findChild(QObject, "albumArtRow")
    qtbot.waitUntil(lambda: item.property("visible") is True, timeout=WAIT)
    item.triggered.emit()
    qtbot.waitUntil(lambda: a.property("opened") and not a.property("loading"), timeout=WAIT)
    assert a.property("title") == "Album art · Glass Harbor"
    settled(shell, qtbot)
    a.close()
    folders.open("Lumen Drift/Glass Harbor")  # a folder of songs (R2.9.7)
    qtbot.waitUntil(lambda: bool(find(shell, "folderArt")), timeout=WAIT)
    click(shell, find(shell, "folderArt")[0])
    qtbot.waitUntil(lambda: a.property("opened") and not a.property("loading"), timeout=WAIT)
    assert a.property("title") == "Album art · Glass Harbor"
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    a.close()
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []


@pytest.mark.slow
def test_save_cover_to_folder_is_on_the_album_pages_menu(shell, qtbot, qtlog):
    lib = shell.library
    (album_id,) = shell.index.read().execute("SELECT id FROM album").fetchone()
    lib.openAlbum(album_id)
    qtbot.waitUntil(lambda: bool(find(shell, "albumMore")), timeout=WAIT)
    click(shell, find(shell, "albumMore")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "saveCoverToFolder")), timeout=WAIT)
    with qtbot.waitSignal(shell.changes.messageChanged, timeout=WAIT):
        click(shell, find(shell, "saveCoverToFolder")[0])
    qtbot.waitUntil(lambda: os.path.exists(os.path.join(shell.music_, "Lumen Drift",
                                                        "Glass Harbor", "cover.jpg")),
                    timeout=WAIT)  # fmt: skip
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
