"""Finding an album's cover (R5.1), as plain data: which embedded picture is the front cover, which
image of the album's folder is its cover, and the name its thumbnail is cached under. Reading the
pictures out of a song is tags.pictures; drawing the thumbnail is the app's (musikata.covers).
Editing, fetching and fixing art (R5.2 to R5.6) come with slice 6."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .tags import Picture

IMAGES = (".jpg", ".jpeg", ".png", ".webp")  # the images a folder's cover can be (R5.1)
NAMES = ("cover", "folder", "front", "album")  # a folder's cover by name, in this order (R5.1)
FRONT = 3  # the front cover's picture type, as ID3 and FLAC number them


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
