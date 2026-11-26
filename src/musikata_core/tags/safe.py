"""Safe writes (A3.4, R4.7): Mutagen writes in place, so a crash or a full disk mid-write could
damage a song. MusiKata never writes the song itself:

1. it copies the file to `.<name>.musikata-tmp` in the same folder (`tmp_path`);
2. writes the tags to the copy (write.apply) and flushes it to disk;
3. reads the copy back: its tags must be the new ones and the rest as they were, its pictures as
   asked, and its audio hash (A2.3) the original's;
4. replaces the original with it in one rename (`os.replace`), keeping the original's permissions,
   and its modification time when R4.7.1's setting says so.

A file read-only, in use (on Windows, a replace refused) or failing in any way is left as it was,
the copy removed, and `WriteError` says why in words a person can act on (R4.7). A copy a crash
left behind is a hidden file, never scanned as a song, and the next scan removes it
(`is_leftover`, `stale`; scanner.walk)."""

from __future__ import annotations

import errno
import logging
import os
import stat
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from . import compose, write
from .fields import AudioInfo, Picture, Tags
from .read import EXTENSIONS, TagReadError, pictures, read

log = logging.getLogger(__name__)

TMP = ".musikata-tmp"  # the copy's suffix (A3.4)
LEFTOVER = 600.0  # seconds since a copy was last touched before a scan takes it for a crash's:
# another MusiKata, on this computer or another sharing the root, may be writing one now
AudioHash = Callable[[str, str], str]  # A2.3's hash of a file's audio, given its path and kind


class WriteError(Exception):
    """A file that wasn't written, left as it was: `why`, in words a person can act on (R4.7)."""

    def __init__(self, path: str, why: str) -> None:
        super().__init__(f"{path}: {why}")
        self.path, self.why = path, why


@dataclass(frozen=True)
class Written:
    """A file written and read back (A3.4, step 3): its path, the tags and audio it reads as now,
    its audio hash, and the size and modification time it was left with, which its row in the
    index takes without reading it again (A2.4). What the change history keeps of it (A3.5):
    the tags it read as `before`, the fields `changed` (compose.FIELDS' names; none when the
    change left every field as it was and nothing was written), and, when the cover changed, the
    cover it had (`cover_before`, None: none) and the one it has now (`cover_after`)."""

    path: str
    tags: Tags
    info: AudioInfo
    audio_hash: str
    size: int
    mtime_ns: int
    before: Tags | None = None
    changed: tuple[str, ...] = ()
    cover_before: Picture | None = None
    cover_after: Picture | None = None


def tmp_path(path: str) -> str:
    """The copy a song is written as, beside it: `.<name>.musikata-tmp` (A3.4)."""
    folder, name = os.path.split(path)
    return os.path.join(folder, f".{name}{TMP}")


def is_leftover(name: str) -> bool:
    """Whether a file's name is a safe write's copy (`tmp_path`)."""
    return name.startswith(".") and name.endswith(TMP) and len(name) > len(TMP) + 1


def stale(st: os.stat_result, now: float) -> bool:
    """Whether a copy was last touched (written, or renamed into its place) more than LEFTOVER
    seconds before `now`, a time: a crash's, not one being written."""
    return max(st.st_mtime, st.st_ctime) < now - LEFTOVER


def save(
    path: str,
    changes: Mapping[str, object],
    *,
    audio_hash: AudioHash,
    id3_version: str = "2.4",
    keep_mtime: bool = False,
    platform: str = sys.platform,
) -> Written:
    """Writes `changes` (R4.1's fields, as compose.normalize takes them) into the song at `path`
    by A3.4's steps, and says what it reads as now. MP3s are written in `id3_version` ("2.4" or
    "2.3", R4.7.2); `keep_mtime` keeps the file's modification time (R4.7.1); `audio_hash` is
    A2.3's (scanner.audio_hash). A change that leaves every field as it was writes nothing.
    Raises WriteError, the file as it was, when it can't be written; ValueError for changes that
    aren't R4.1's fields, or a rating for a WAV or AIFF file, which R10.4 keeps out of it."""
    normalized = compose.normalize(changes)
    kind = EXTENSIONS.get(os.path.splitext(path)[1].lower())
    if "rating" in normalized and kind in compose.UNRATED:
        raise ValueError(f"{path}: a {kind} file holds no rating; R10.4 keeps it in ratings.json")
    tmp = tmp_path(path)
    step = "reading"
    replaced = False
    try:
        st = os.stat(path)
        if read_only(path, st):
            raise WriteError(path, "it is read-only: let it be written to, then try again")
        before, info = read(path)
        change = compose.effective(normalized, before)
        original_hash = audio_hash(path, info.kind)
        if not change:
            return Written(path, before, info, original_hash, st.st_size, st.st_mtime_ns, before)
        typed = info.kind not in ("aac", "alac")
        wanted = old_cover = None
        if "cover" in change:
            had = pictures(path)
            old_cover = compose.cover_of(had, typed)
            wanted = compose.pictures_after(had, normalized["cover"], typed)  # type: ignore[arg-type]
        step = "copying"
        write.copy(path, tmp, change)
        step = "writing"
        write.apply(tmp, change, before, id3_version, path)
        flush(tmp)
        step = "checking"
        tags, tmp_info = read(tmp, path)
        check(path, compose.expected(before, change), tags, "cover" in change)
        if wanted is not None and not same_pictures(wanted, pictures(tmp, path), typed):
            raise WriteError(path, LEFT_AS_IT_WAS.format("its cover didn't read back as written"))
        new_hash = audio_hash(tmp, tmp_info.kind)
        if new_hash != original_hash:
            raise WriteError(path, LEFT_AS_IT_WAS.format("its audio didn't read back the same"))
        step = "replacing"
        os.chmod(tmp, stat.S_IMODE(st.st_mode))
        if keep_mtime:
            os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, path)
        replaced = True
        done = os.stat(path)
    except WriteError as e:
        log.warning("didn't write the tags of %s: %s", path, e.why)
        raise
    except Exception as e:  # noqa: BLE001  (any failure leaves the song as it was, and says why)
        why = reason(e, step, platform)
        if isinstance(e, OSError | TagReadError):
            log.warning("didn't write the tags of %s (%s): %s", path, step, e)
        else:
            log.exception("didn't write the tags of %s (%s)", path, step)
        raise WriteError(path, why) from e
    finally:
        if not replaced:
            remove(tmp)
    log.info("wrote the tags of %s: %s", path, ", ".join(sorted(change)))
    new_cover: Picture | None = normalized.get("cover")  # type: ignore[assignment]
    return Written(
        path, tags, tmp_info, new_hash, done.st_size, done.st_mtime_ns, before,
        tuple(f for f in compose.FIELDS if f in change),
        old_cover if "cover" in change else None,
        new_cover if "cover" in change else None,
    )  # fmt: skip


LEFT_AS_IT_WAS = "{}, so it was left as it was"


def read_only(path: str, st: os.stat_result) -> bool:
    """Whether the file can't be written: no one may write it (its read-only attribute, on
    Windows), or this user may not."""
    return not st.st_mode & 0o222 or not os.access(path, os.W_OK)


def flush(path: str) -> None:
    """The file's bytes on the disk, not only in the system's cache (A3.4, step 2)."""
    with open(path, "rb+") as f:
        os.fsync(f.fileno())


def check(path: str, want: Tags, got: Tags, cover: bool) -> None:
    """The copy's tags as written (A3.4, step 3); WriteError naming those that aren't."""
    wrong = compose.differences(want, got, cover)
    if wrong:
        log.warning("%s read back otherwise than written: %s", path, ", ".join(wrong))
        raise WriteError(
            path, LEFT_AS_IT_WAS.format(f"its {', '.join(wrong)} didn't read back as written")
        )


def same_pictures(want: Sequence[Picture], got: Sequence[Picture], typed: bool) -> bool:
    """Whether a song's pictures read back as `want` (compose.pictures_after): the cover first,
    the others in any order, by their bytes and, where the kind has them, their types."""

    def key(p: Picture) -> tuple[int | None, bytes]:
        return (p.type if typed else None), p.data

    if [key(p) for p in want[:1]] != [key(p) for p in got[:1]]:
        return False
    return Counter(map(key, want[1:])) == Counter(map(key, got[1:]))


def remove(tmp: str) -> None:
    """The copy gone, if it was made; logged when it can't be (the next scan tries again)."""
    try:
        os.remove(tmp)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("couldn't remove %s: %s", tmp, e)


def reason(e: BaseException, step: str, platform: str = sys.platform) -> str:
    """Why a write failed at `step` ("reading", "copying", "writing", "checking", "replacing"),
    for the person who asked for it (R4.7): what happened and what they can do."""
    windows = platform.startswith("win")
    if isinstance(e, TagReadError):
        if step == "checking":
            return LEFT_AS_IT_WAS.format(f"the copy written couldn't be read back ({e})")
        return f"it can't be read: {e}"
    if isinstance(e, FileNotFoundError) and step == "reading":
        return "it isn't there any more"
    if isinstance(e, OSError):
        code = e.errno
        if code in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)):
            return "the disk is full: make room on it, then try again"
        if code == errno.EROFS:
            return "its drive can't be written to"
        if isinstance(e, PermissionError):
            if windows and (step == "replacing" or getattr(e, "winerror", None) in (32, 33)):
                return "it is open in another program: close it there, then try again"
            if step in ("copying", "replacing"):
                return "its folder can't be written to: MusiKata writes a copy there first"
            return "it can't be opened: let it be read and written, then try again"
        return f"it couldn't be written: {e.strerror or e}"
    if step == "writing":
        return f"its tags couldn't be written: {e}"
    return f"it couldn't be written: {type(e).__name__}: {e}"


def remove_stale(path: str, now: float) -> bool:
    """Removes the leftover copy at `path` when it is `stale` (A3.4), and says so in the log;
    whether it did."""
    try:
        if not stale(os.stat(path), now):
            return False
        os.remove(path)
    except FileNotFoundError:
        return False
    except OSError as e:
        log.warning("couldn't remove %s, a copy a write left behind: %s", path, e)
        return False
    log.info("removed %s, a copy a write left behind", path)
    return True
