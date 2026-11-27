"""Album art (R5), as plain data. Finding an album's cover (R5.1): which embedded picture is the
front cover, which image of the album's folder is its cover, and the name its thumbnail is cached
under; reading the pictures out of a song is tags.pictures, drawing the thumbnail the app's
(musikata.covers).

The Album art dialog's logic (R5.2, R5.3, R5.5): what an image is, read from its first bytes
(`sniff`) and whether it can be used (`problem`); the covers found for an album and the current
one (`gather`), each with where it is and a note; and what saving would write for the options
chosen (`plan`): the front cover of each song that hasn't it, the other pictures removed, and
cover.jpg in each of the album's folders, or "No change". Decoding, shrinking and converting an
image are the app's (musikata.albumart, with Qt): what it makes of the chosen image is given here
as `Forms`. A cover.jpg is written beside the songs, the older one moved to the trash
(`save_image`, Principle 5), in the same batch as the songs (`writer`), so the change history
keeps the save as one entry and Undo puts the old cover.jpg back (A3.5)."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QFile, QStandardPaths

from .tags import Job, Picture, WriteError, Written
from .tags.read import PICTURE_TYPES
from .tags.safe import LEFT_AS_IT_WAS, flush, reason, remove, tmp_path

log = logging.getLogger(__name__)

IMAGES = (".jpg", ".jpeg", ".png", ".webp")  # the images a folder's cover can be (R5.1)
NAMES = ("cover", "folder", "front", "album")  # a folder's cover by name, in this order (R5.1)
FRONT = 3  # the front cover's picture type, as ID3 and FLAC number them
COVER_JPG = "cover.jpg"  # R5.3: the folder's cover MusiKata writes
SHRINK = 1200  # R5.3: the side a larger image is shrunk to before it is embedded (R13's setting)
QUALITY = 90  # R5.3: the JPEG quality a shrunk or converted image is saved at
MAX_BYTES = 50 * 1024 * 1024  # an image from outside larger than this isn't read
MAX_PIXELS = 50_000_000  # nor one with more pixels than this: decoding it would take too much
MIN_SIDE = 16  # nor one this small: a web page's tracking pixel, not a cover
# a folder image named as one of these is another part of the release, not its front (R5.2)
NOT_FRONT = ("back", "rear", "inlay", "inside", "tray", "booklet", "cd", "disc", "disk", "label")
MIME = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
KIND_TEXT = {"jpeg": "JPEG", "png": "PNG", "webp": "WebP"}
CAN_READ = "JPEG, PNG or WebP"


@dataclass(frozen=True)
class Image:
    """An image file the walk found in a folder: its name, size and modification time."""

    name: str
    size: int
    mtime_ns: int


def is_image(name: str) -> bool:
    """Whether a file's name is one of R5.1's images (any case), not a hidden file."""
    return not name.startswith(".") and os.path.splitext(name)[1].lower() in IMAGES


def folder_cover(images: Iterable[Image]) -> Image | None:
    """A folder's cover (R5.1, steps 2 and 3): an image named cover, folder, front or album (any
    case, in that order), else the largest other image; None when it holds no image."""
    found = sorted((i for i in images if is_image(i.name)), key=lambda i: i.name)
    named = [i for i in found if os.path.splitext(i.name)[0].casefold() in NAMES]
    if named:
        return min(named, key=lambda i: NAMES.index(os.path.splitext(i.name)[0].casefold()))
    return max(found, key=lambda i: i.size, default=None)


def front(pictures: Sequence[Picture]) -> Picture | None:
    """The picture a song's cover is (R5.1, step 1): its front cover, else its first picture with
    any bytes; None when it has none."""
    usable = [p for p in pictures if p.data]
    return next((p for p in usable if p.type == FRONT), usable[0] if usable else None)


def thumb_id(source: str, size: int, mtime_ns: int) -> str:
    """The name a cover's thumbnails are cached under (R5.1, A2.1): a hash of where the cover is
    and the file's size and modification time, so a changed cover gets new thumbnails."""
    return hashlib.sha256(f"{source}\0{size}\0{mtime_ns}".encode()).hexdigest()[:32]


def key_of(data: bytes) -> str:
    """An image's identity: the SHA-256 of its bytes, as the change history names covers."""
    return hashlib.sha256(data).hexdigest()


# ---------- an image, from its bytes ----------


@dataclass(frozen=True)
class ImageInfo:
    """What an image is, read from its header: its kind ("jpeg", "png" or "webp"), its size in
    pixels, and whether it is a CMYK JPEG (which many players show wrongly) or has transparency."""

    kind: str
    width: int
    height: int
    cmyk: bool = False
    alpha: bool = False

    @property
    def mime(self) -> str:
        return MIME[self.kind]

    @property
    def pixels(self) -> int:
        return self.width * self.height


def sniff(data: bytes) -> ImageInfo | None:
    """What the image in `data` is, from its first bytes, without decoding it: a JPEG's, a PNG's
    or a WebP's kind and size; None for anything else, or a header cut short or broken. Never
    raises, whatever the bytes."""
    if data[:2] == b"\xff\xd8":
        return _jpeg(data)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _png(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp(data)
    return None


SOF = {*range(0xC0, 0xD0)} - {0xC4, 0xC8, 0xCC}  # a JPEG's frame headers, which give its size


def _jpeg(data: bytes) -> ImageInfo | None:
    pos, n = 2, len(data)
    while pos < n:
        if data[pos] != 0xFF:
            return None
        while pos < n and data[pos] == 0xFF:  # fill bytes
            pos += 1
        if pos >= n:
            return None
        marker = data[pos]
        pos += 1
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # markers without a length
            continue
        if marker in (0xD9, 0xDA) or pos + 2 > n:  # the end, or the scan, before a frame
            return None
        length = int.from_bytes(data[pos : pos + 2], "big")
        if length < 2:
            return None
        if marker in SOF:
            if pos + 8 > n:
                return None
            height = int.from_bytes(data[pos + 3 : pos + 5], "big")
            width = int.from_bytes(data[pos + 5 : pos + 7], "big")
            if not width or not height:
                return None
            return ImageInfo("jpeg", width, height, cmyk=data[pos + 7] == 4)
        pos += length
    return None


def _png(data: bytes) -> ImageInfo | None:
    if len(data) < 26 or data[12:16] != b"IHDR":
        return None
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if not width or not height:
        return None
    alpha = data[25] in (4, 6)
    pos = 33  # after IHDR: a tRNS chunk before the image data makes a colour transparent
    while not alpha and pos + 8 <= len(data):
        size, chunk = int.from_bytes(data[pos : pos + 4], "big"), data[pos + 4 : pos + 8]
        if chunk in (b"IDAT", b"IEND"):
            break
        alpha = chunk == b"tRNS"
        pos += 12 + size
    return ImageInfo("png", width, height, alpha=alpha)


def _webp(data: bytes) -> ImageInfo | None:
    chunk = data[12:16]
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        alpha = False
    elif chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        width, height = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        alpha = bool(bits >> 28 & 1)
    elif chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        alpha = bool(data[20] & 0x10)
    else:
        return None
    if not width or not height:
        return None
    return ImageInfo("webp", width, height, alpha=alpha)


def problem(data: bytes, info: ImageInfo | None) -> str:
    """Why an image can't be used as a cover, in words a person can act on; "" when it can. An
    image MusiKata can't read, one too large to decode, or too small to be a cover."""
    if len(data) > MAX_BYTES:
        return f"it is {size_text(len(data))}, too large for a cover: save a smaller copy first"
    if info is None:
        return f"it isn't an image MusiKata can read ({CAN_READ})"
    if info.pixels > MAX_PIXELS:
        return (
            f"it is {info.width} × {info.height}, too large to use: scale it down below "
            f"{MAX_PIXELS // 1_000_000} megapixels first"
        )
    if min(info.width, info.height) < MIN_SIDE:
        return f"it is only {info.width} × {info.height}, too small to be a cover"
    return ""


def size_text(n: int) -> str:
    """A file's size as the dialog says it: 318 KB, 2.4 MB."""
    if n < 1024 * 1024:
        return f"{max(1, round(n / 1024)):,} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def needs_converting(info: ImageInfo, jpeg: bool) -> bool:
    """Whether an image is written otherwise than as it is: a CMYK JPEG (which players show
    wrongly) always, a WebP when embedded (MP4 and most players can't show it), and, when it is
    to be a JPEG (`jpeg`, cover.jpg), anything but an RGB JPEG."""
    if info.cmyk or info.kind == "webp":
        return True
    return jpeg and info.kind != "jpeg"


def needs_shrinking(info: ImageInfo, side: int = SHRINK) -> bool:
    """Whether an image is larger than R5.3's size, and is shrunk to it before it is embedded."""
    return max(info.width, info.height) > side


# ---------- what the dialog lists for an album (R5.2) ----------


@dataclass(frozen=True)
class SongArt:
    """A song of the album as the dialog reads it: its path under the root, its pictures as its
    file holds them, whether its kind numbers them (not MP4), and why they couldn't be read ("":
    they could)."""

    path: str
    pictures: tuple[Picture, ...] = ()
    typed: bool = True
    error: str = ""

    @property
    def cover(self) -> Picture | None:
        """Its front cover (R5.1): where the kind numbers its pictures, its first front cover;
        in MP4, its first picture."""
        if self.typed:
            return next((p for p in self.pictures if p.type == FRONT and p.data), None)
        return self.pictures[0] if self.pictures and self.pictures[0].data else None

    @property
    def others(self) -> tuple[Picture, ...]:
        """Its pictures but its front cover (R5.3's "other embedded images")."""
        if self.typed:
            return tuple(p for p in self.pictures if p.type != FRONT)
        return self.pictures[1:]


@dataclass(frozen=True)
class FolderImage:
    """An image in one of the album's folders: the folder (under the root, with /), its name, and
    its bytes (None: it couldn't be read, `error` saying why)."""

    folder: str
    name: str
    data: bytes | None
    error: str = ""


@dataclass(frozen=True)
class Added:
    """An image from outside (R5.2.1, R5.4): how it came ("dropped", "pasted" or "chosen"), its
    file's name ("" when it had none, as a pasted picture), and its bytes."""

    origin: str
    name: str
    data: bytes


@dataclass(frozen=True)
class Candidate:
    """A cover the dialog offers: its identity (`key_of` its bytes), the bytes, what they are
    (None: not an image it can read), where it is (`title`), a `note` beside its size, why it
    can't be chosen (`problem`, "" when it can), and where it came from ("added", "folder" or
    "embedded")."""

    key: str
    data: bytes
    info: ImageInfo | None
    title: str
    note: str = ""
    problem: str = ""
    origin: str = "folder"

    @property
    def detail(self) -> str:
        """Its line under the title: 1200 × 1200 · same as embedded."""
        if self.problem:
            return self.problem[0].upper() + self.problem[1:]
        size = f"{self.info.width} × {self.info.height}" if self.info is not None else ""
        return " · ".join(p for p in (size, self.note) if p)


@dataclass(frozen=True)
class Current:
    """The album's cover now (R5.1's first found): its identity, bytes and what they are (all
    None for none), its line ("Current · 1200 × 1200 JPEG · 318 KB") and where it is ("Embedded
    in 10 of 10", "cover.jpg in the folder"), with that chip's tone ("ok" when every song has
    it embedded, else "warn")."""

    key: str | None = None
    data: bytes | None = None
    info: ImageInfo | None = None
    line: str = "No album art"
    where: str = ""
    tone: str = "warn"


@dataclass(frozen=True)
class Album:
    """What the dialog shows for an album: its songs' and folders' art as read, the current
    cover, and the candidates, in the order listed."""

    songs: tuple[SongArt, ...]
    folders: tuple[str, ...]
    images: tuple[FolderImage, ...]
    current: Current
    candidates: tuple[Candidate, ...]

    def candidate(self, key: str) -> Candidate | None:
        return next((c for c in self.candidates if c.key == key), None)


def songs_text(n: int) -> str:
    return f"{n:,} song" if n == 1 else f"{n:,} songs"


def _type_text(kind: int | None) -> str:
    return PICTURE_TYPES.get(kind, "picture") if kind is not None else "picture"


def is_back(name: str) -> bool:
    """Whether a folder image's name says it isn't the front cover (back.png, CD.jpg, inlay)."""
    stem = os.path.splitext(name)[0].casefold()
    words = "".join(ch if ch.isalnum() else " " for ch in stem).split()
    return any(w.rstrip("0123456789") in NOT_FRONT for w in words)


def _ordered_images(images: Sequence[FolderImage]) -> list[FolderImage]:
    """A folder's images in R5.1's order: named as a cover (cover, folder, front, album), then
    the others, largest first."""

    def rank(i: FolderImage) -> tuple[int, int, str]:
        stem = os.path.splitext(i.name)[0].casefold()
        named = NAMES.index(stem) if stem in NAMES else len(NAMES)
        return named, -len(i.data or b""), i.name

    return sorted(images, key=rank)


def current_of(songs: Sequence[SongArt], images: Sequence[FolderImage]) -> Current:
    """The album's cover now (R5.1): the front cover most of its songs have embedded (the first
    song's among equals), else its folder's cover, else none."""
    covers = [s.cover for s in songs]
    counts = Counter(key_of(c.data) for c in covers if c is not None)
    if counts:
        best = max(counts.values())
        picture = next(c for c in covers if c is not None and counts[key_of(c.data)] == best)
        n, total = best, len(songs)
        where, tone = f"Embedded in {n:,} of {total:,}", "ok" if n == total else "warn"
        data = picture.data
    else:
        usable = [i for i in _ordered_images(images) if i.data and is_image(i.name)]
        if not usable:
            return Current()
        image = usable[0]
        data = image.data or b""
        where, tone = f"{image.name} in the folder", "warn"
    info = sniff(data)
    what = f"{info.width} × {info.height} {KIND_TEXT[info.kind]}" if info else "unreadable"
    return Current(key_of(data), data, info, f"Current · {what} · {size_text(len(data))}", where,
                   tone)  # fmt: skip


def gather(
    songs: Sequence[SongArt],
    images: Sequence[FolderImage],
    added: Sequence[Added] = (),
    folders: Sequence[str] = (),
) -> Album:
    """What the dialog shows for an album (R5.2): the current cover and every candidate, each set
    of bytes once: the images added (dropped, pasted, chosen; the latest first), the images of
    its folders in R5.1's order, then the pictures embedded in its songs, front covers first,
    the most used first. Each says where it is and a note ("same as embedded", "named as a back
    cover", "lower resolution"), or why it can't be used."""
    folders = tuple(folders) or tuple(sorted({i.folder for i in images}))
    current = current_of(songs, images)
    many = len(set(folders)) > 1
    found: dict[str, Candidate] = {}

    def offer(data: bytes, title: str, origin: str, note: str = "") -> None:
        key = key_of(data)
        if key in found:
            return
        info = sniff(data)
        found[key] = Candidate(key, data, info, title, note, problem(data, info), origin)

    for a in reversed(added):
        title = {"dropped": "Dropped", "pasted": "Pasted image", "chosen": "Chosen"}[a.origin]
        offer(a.data, f"{title}: {a.name}" if a.name and a.origin != "pasted" else title, "added")
    for image in _ordered_images(images):
        where = f"{image.name} in {image.folder.rpartition('/')[2]}" if many else (
            f"{image.name} in the folder")  # fmt: skip
        if image.data is None:
            log.info("the image %s/%s couldn't be read: %s", image.folder, image.name, image.error)
            continue
        offer(image.data, where, "folder", "named as a back cover" if is_back(image.name) else "")
    embedded: dict[tuple[str, int | None], tuple[Picture, int]] = {}
    for s in songs:
        cover = s.cover
        for p in s.pictures:
            if not p.data:
                continue
            kind = FRONT if p is cover else (p.type if s.typed else None)
            k = (key_of(p.data), kind)
            had = embedded.get(k)
            embedded[k] = (p, (had[1] if had else 0) + 1)
    ordered = sorted(embedded.items(), key=lambda e: (e[0][1] != FRONT, -e[1][1]))
    for (_key, kind), (p, n) in ordered:
        many_songs = f"all {len(songs):,} songs" if n == len(songs) > 1 else songs_text(n)
        if kind == FRONT:
            offer(p.data, f"Embedded in {many_songs}", "embedded")
        else:
            label = _type_text(kind)
            offer(p.data, f"{label[0].upper()}{label[1:]} embedded in {many_songs}", "embedded",
                  f"embedded as the {label}" if kind not in (0, None) else "")  # fmt: skip
    candidates = _noted(list(found.values()), current, songs)
    return Album(tuple(songs), folders, tuple(images), current, tuple(candidates))


def _noted(
    candidates: list[Candidate], current: Current, songs: Sequence[SongArt]
) -> list[Candidate]:
    """Each candidate with its note: its own (a back cover's), else "same as embedded" for an
    image other than the embedded ones whose bytes are the cover the songs have, else that a CMYK
    JPEG is made RGB, else "lower resolution" for fewer pixels than the largest found."""
    largest = max((c.info.pixels for c in candidates if c.info and not c.problem), default=0)
    embedded = {key_of(p.data) for s in songs if (p := s.cover) is not None}
    out = []
    for c in candidates:
        note = c.note
        if not note and c.origin != "embedded" and c.key in embedded:
            note = "same as embedded"
        elif not note and c.info is not None and c.info.cmyk:
            note = "CMYK: made RGB when saved"
        elif not note and c.info is not None and c.info.pixels < largest:
            note = "lower resolution"
        out.append(Candidate(c.key, c.data, c.info, c.title, note, c.problem, c.origin))
    return out


def chosen_first(album: Album) -> str | None:
    """The candidate chosen when the dialog opens: the one added last, else the current cover,
    else the first usable one; None when there is none."""
    usable = [c for c in album.candidates if not c.problem]
    added = [c for c in usable if c.origin == "added"]
    if added:
        return added[0].key
    current = album.candidate(album.current.key) if album.current.key is not None else None
    if current is not None and not current.problem:
        return current.key
    return usable[0].key if usable else None


# ---------- what saving does (R5.3) ----------


@dataclass(frozen=True)
class Options:
    """R5.3's checkboxes: embed in every song, save as cover.jpg in the folder, shrink to `side`
    before embedding, remove other embedded images."""

    embed: bool = True
    folder: bool = True
    shrink: bool = True
    remove_others: bool = False
    side: int = SHRINK


@dataclass(frozen=True)
class Forms:
    """What the chosen image is written as (the app's decoding, A1.2): `embed`, as embedded at its
    own size (its bytes, or converted: a CMYK JPEG or a WebP, `needs_converting`); `shrunk`, as
    embedded once shrunk to R5.3's size (None: it is no larger); `folder`, as cover.jpg, a JPEG at
    its full size."""

    embed: bytes
    shrunk: bytes | None
    folder: bytes

    def embedded(self, options: Options) -> bytes:
        return self.shrunk if options.shrink and self.shrunk is not None else self.embed


def same_forms(data: bytes) -> Forms:
    """The forms of an image written as it is: an RGB JPEG no larger than R5.3's size, or a test's
    bytes."""
    return Forms(data, None, data)


@dataclass(frozen=True)
class Plan:
    """What saving writes (R5.3): the jobs, songs first, then each folder's cover.jpg; the songs
    whose front cover is set (`embeds`), those whose other pictures go (`removes`), and the
    folders whose cover.jpg is written."""

    jobs: tuple[Job, ...] = ()
    embeds: int = 0
    removes: int = 0
    folders: tuple[str, ...] = ()


def full_path(root: str, rel: str) -> str:
    return os.path.join(root, *rel.split("/")) if rel else root


def cover_jpg_of(images: Iterable[FolderImage], folder: str) -> FolderImage | None:
    """A folder's cover.jpg as it is named there (Cover.JPG, any case), when it has one."""
    return next((i for i in images if i.folder == folder and i.name.casefold() == COVER_JPG), None)


def plan(album: Album, forms: Forms, options: Options, root: str) -> Plan:
    """The jobs saving writes for `album` with the chosen image's `forms` (R5.3): its front cover
    set in each song whose cover isn't already those bytes (Embed), the other pictures of each
    song that has any removed (Remove), and cover.jpg written in each of its folders where it
    isn't those bytes, replacing one of any case (Save as cover.jpg). None: "No change"."""
    jobs: list[Job] = []
    embeds = removes = 0
    picture_data = forms.embedded(options)
    info = sniff(picture_data)
    picture = Picture(FRONT, info.mime if info else "image/jpeg", picture_data)
    for s in album.songs:
        changes: dict[str, object] = {}
        cover = s.cover
        if options.embed and (cover is None or cover.data != picture_data):
            changes["cover"] = picture
            embeds += 1
        if options.remove_others and s.others:
            changes["others"] = ()
            removes += 1
        if changes:
            jobs.append(Job(full_path(root, s.path), changes))
    written = []
    if options.folder:
        for folder in album.folders:
            had = cover_jpg_of(album.images, folder)
            if had is not None and had.data == forms.folder:
                continue
            name = had.name if had is not None else COVER_JPG
            jobs.append(Job(full_path(root, f"{folder}/{name}" if folder else name),
                            {"image": forms.folder}))  # fmt: skip
            written.append(folder)
    return Plan(tuple(jobs), embeds, removes, tuple(written))


def _and(parts: Sequence[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def footer(p: Plan, options: Options, chosen: Candidate | None) -> str:
    """The dialog's footer (R5.3, T02): what saving will change ("Embeds the cover in 2 songs and
    writes cover.jpg"), or "No change" when the chosen cover is already everywhere it goes; why
    the chosen image can't be used, or that none is chosen."""
    if chosen is None:
        return "Choose a cover, or drop, paste or choose an image"
    if chosen.problem:
        return f"This image can't be used: {chosen.problem}"
    if not (options.embed or options.folder or options.remove_others):
        return "No change: choose where the cover goes"
    parts = []
    if p.embeds:
        parts.append(f"embeds the cover in {songs_text(p.embeds)}")
    if p.removes:
        parts.append(f"removes the other images from {songs_text(p.removes)}")
    if p.folders:
        many = len(p.folders)
        parts.append(f"writes {COVER_JPG}" + (f" in {many:,} folders" if many > 1 else ""))
    if not parts:
        return "No change: the chosen cover is already on every song."
    text = _and(parts)
    return text[0].upper() + text[1:]


def save_label(p: Plan) -> str:
    """The footer's button: Save N files, or Done when nothing changes (T02)."""
    n = len(p.jobs)
    return "Done" if not n else "Save 1 file" if n == 1 else f"Save {n:,} files"


def description_of(title: str, p: Plan) -> str:
    """What the save was, for the change history (R4.9): Album art: Glass Harbor."""
    return f"Album art: {title}" if title else "Album art"


def extract(album: Album) -> Candidate | None:
    """R5.5's Save cover to folder: the embedded cover (the one most of the album's songs have);
    None when no song has one."""
    covers = [s.cover for s in album.songs if s.cover is not None]
    if not covers:
        return None
    counts = Counter(key_of(c.data) for c in covers)
    return album.candidate(counts.most_common(1)[0][0])


# ---------- writing cover.jpg (R5.3) ----------


@dataclass(frozen=True)
class ImageWritten:
    """An image file a save wrote (cover.jpg): its path, the bytes it had (None: none) and has now
    (None: removed), and the size and modification time it was left with."""

    path: str
    before: bytes | None
    after: bytes | None
    size: int = 0
    mtime_ns: int = 0


Trash = Callable[[str], bool]  # moves a file to the system's trash: whether it did


def to_trash(path: str) -> bool:
    """Moves the file at `path` to the system's trash (Qt's, A1.2). On Linux the user's own trash
    folder is made first when it isn't there, as the freedesktop.org trash asks, since Qt gives up
    without it."""
    if sys.platform.startswith("linux"):
        data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
        try:
            os.makedirs(os.path.join(data, "Trash"), exist_ok=True)
        except OSError as e:
            log.warning("the trash folder in %s couldn't be made: %s", data, e)
    return bool(QFile.moveToTrash(path))


def _read_file(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def save_image(path: str, data: bytes | None, trash: Trash = to_trash) -> ImageWritten:
    """Writes `data` as the image file at `path` (cover.jpg, R5.3): to a copy beside it first,
    then the file there moved to the trash (Principle 5) and the copy put in its place. None
    moves the file to the trash (an undo of a cover.jpg that wasn't there). Raises WriteError,
    the file as it was, when it can't be done."""
    tmp = tmp_path(path)
    step = "reading"
    replaced = False
    try:
        before = _read_file(path)
        if before == data:
            st = os.stat(path) if data is not None else None
            return ImageWritten(path, before, data, st.st_size if st else 0,
                                st.st_mtime_ns if st else 0)  # fmt: skip
        if data is not None:
            step = "copying"
            with open(tmp, "wb") as f:
                f.write(data)
            flush(tmp)
        if before is not None and not trash(path):
            raise WriteError(path, LEFT_AS_IT_WAS.format("it couldn't be moved to the trash"))
        if data is None:
            log.info("moved %s to the trash", path)
            return ImageWritten(path, before, None)
        step = "replacing"
        os.replace(tmp, path)
        replaced = True
        st = os.stat(path)
    except WriteError as e:
        log.warning("didn't write %s: %s", path, e.why)
        raise
    except OSError as e:
        log.warning("didn't write %s (%s): %s", path, step, e)
        why = reason(e, step)
        if before is not None and step == "replacing":
            why += "; the older one is in the trash"
        raise WriteError(path, why) from e
    finally:
        if not replaced:
            remove(tmp)
    log.info("wrote %s (%s)", path, size_text(len(data)))
    return ImageWritten(path, before, data, st.st_size, st.st_mtime_ns)


def writer(
    write: Callable[[Job], Written], trash: Trash = to_trash
) -> Callable[[Job], Written | ImageWritten]:
    """A save's writer (tags.Batch's) for songs and image files both: a job whose changes are an
    `image` (bytes, or None to remove it) writes that file (`save_image`); any other is a song's,
    written by `write` (safe.save, or ratings.Writing)."""

    def write_one(job: Job) -> Written | ImageWritten:
        if "image" in job.changes:
            data = job.changes["image"]
            if data is not None and not isinstance(data, bytes):
                raise ValueError(f"an image is its bytes, not {data!r}")
            return save_image(job.path, data, trash)
        return write(job)

    return write_one


def written_songs(saved: Iterable[object]) -> list[Written]:
    """The songs of a save's outcome (what the index is told of), its image files left out."""
    return [w for w in saved if isinstance(w, Written)]
