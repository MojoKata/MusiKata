"""The shared settings (R13.9, A2.10): `settings.json` in the shared settings folder (R1.5), what
belongs to this computer and this person, the configured root (R2.1) among it.

This much is what the configured root and playing need: where the file is, reading it in whatever
shape a person, a sync tool or another version of MusiKata left it, and writing the root back,
every field it doesn't know kept (A2.10); this computer's id (A2.8), made when it has none;
Playback's output device and ReplayGain (R13.7), read only, until Settings (R13) writes them; and
shuffle and repeat (R7.3), written when the user changes them. Of the root's own `settings.json`,
the Tags settings that writing tags needs (R13.3: R4.7.1, R4.7.2, and the change history's, R4.9)
are read (`root_tags`). The rest of both files comes with Settings.

A value it can't use is reported in the App log and its default used (R13.9); a file of a newer
format is read for what it can and never written (A2.10)."""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

log = logging.getLogger(__name__)
FORMAT = 1  # the shared settings.json's format (A2.10)
NAME = "settings.json"


def shared_dir(env: Mapping[str, str], platform: str = sys.platform) -> str:
    """The shared settings folder (R1.5): ~/.musikata on Linux, %USERPROFILE%\\.musikata on
    Windows, ~/Library/Application Support/MusiKata on macOS. MUSIKATA_DATA moves it beside the
    indexes, so a development copy never changes the real configured root
    (docs/process/development.md)."""
    if env.get("MUSIKATA_DATA"):
        return os.path.join(env["MUSIKATA_DATA"], "settings")
    home = env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")
    if platform.startswith("win"):
        return os.path.join(env.get("USERPROFILE") or home, ".musikata")
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "MusiKata")
    return os.path.join(home, ".musikata")


def shared_path(env: Mapping[str, str], platform: str = sys.platform) -> str:
    """The shared settings.json."""
    return os.path.join(shared_dir(env, platform), NAME)


REPLAYGAIN_MODES = ("album", "track", "off")  # R7.5, R13.7: Album the default
REPEATS = ("off", "all", "one")  # R7.3: the queue's (musikata_core.audio.queue.REPEATS)


@dataclass(frozen=True)
class Playback:
    """R13.7's Playback as read: the output device chosen, by its id (None: the system's default,
    R7.7); ReplayGain's mode, one of REPLAYGAIN_MODES (R7.5); and the pre-amp in dB for songs
    without ReplayGain tags (R7.5's -6 dB); and the queue's shuffle and repeat, one of REPEATS,
    kept across restarts (R7.3)."""

    device: str | None = None
    replaygain: str = "album"
    replaygain_default: float = -6.0
    shuffle: bool = False
    repeat: str = "off"


@dataclass(frozen=True)
class Shared:
    """The shared settings as read: the configured root (None: none yet, the first start, R2.1),
    Watch for changes (R13.2), this computer's id and name (A2.8); `data`, the file as read, which
    a rewrite keeps; `newer`, a newer MusiKata's format, never written; and what couldn't be used,
    for the log. `playback` is R13.7's (`Playback`)."""

    root: str | None = None
    watch: bool = True
    computer_id: str | None = None
    computer_name: str | None = None
    playback: Playback = field(default_factory=Playback)
    data: Mapping[str, object] = field(default_factory=dict)
    newer: bool = False
    problems: tuple[str, ...] = ()


def _root(value: object, home: str, problems: list[str]) -> str | None:
    """library.root: a whole path, `~` taken as the home (a person writes it so); None when there is
    none, or it can't be used."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        problems.append(f"library.root isn't a path: {value!r}")
        return None
    if value == "~" or value.startswith(("~/", "~\\")):
        value = home + value[1:]
    if not os.path.isabs(value):
        problems.append(f"library.root isn't a whole path: {value!r}")
        return None
    return os.path.normpath(value)


def _playback(value: object, problems: list[str]) -> Playback:
    """playback: what of it can be used, the rest its defaults (R13.9)."""
    if not isinstance(value, dict):
        problems.append(f"playback isn't a group: {value!r}")
        return Playback()
    default = Playback()
    device = value.get("device")
    if device is not None and not (isinstance(device, str) and device):
        problems.append(f"playback.device isn't a device's id: {device!r}; the system's default")
        device = None
    mode = value.get("replaygain", default.replaygain)
    if isinstance(mode, str) and mode.strip().lower() in REPLAYGAIN_MODES:
        mode = mode.strip().lower()  # "Album", as a person writes it
    else:
        problems.append(f"playback.replaygain isn't album, track or off: {mode!r}; album")
        mode = default.replaygain
    shuffle = value.get("shuffle", default.shuffle)
    if not isinstance(shuffle, bool):
        problems.append(f"playback.shuffle isn't true or false: {shuffle!r}; off")
        shuffle = default.shuffle
    repeat = value.get("repeat", default.repeat)
    if isinstance(repeat, str) and repeat.strip().lower() in REPEATS:
        repeat = repeat.strip().lower()  # "All", as a person writes it
    else:
        problems.append(f"playback.repeat isn't off, all or one: {repeat!r}; off")
        repeat = default.repeat
    return Playback(device, mode, _decibels(value, "replaygain_default", problems), shuffle, repeat)


def _decibels(group: Mapping[str, object], key: str, problems: list[str]) -> float:
    """A number of dB, or a number written as text ("-6", "-6 dB"); its default when it is
    neither."""
    value = group.get(key, getattr(Playback, key))
    number: float | None = None
    if isinstance(value, int | float) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().removesuffix("dB").strip())
        except ValueError:
            number = None
    if number is None or not math.isfinite(number):
        default: float = getattr(Playback, key)
        problems.append(f"playback.{key} isn't a number of dB: {value!r}; {default:g}")
        return default
    return number


def parse(text: str, home: str) -> Shared:
    """The shared settings in `text`, settings.json's content, whatever was written there: what
    can't be used is named in `problems` and takes its default (R13.9). `home` is what `~` in a
    path stands for."""
    problems: list[str] = []
    try:
        data = json.loads(text.removeprefix("﻿"))  # a BOM: Notepad writes one
    except ValueError as e:
        return Shared(problems=(f"it isn't JSON ({e}): its settings take their defaults",))
    if not isinstance(data, dict):
        return Shared(problems=("it isn't a JSON object: its settings take their defaults",))
    fmt = data.get("format")
    newer = False
    if isinstance(fmt, int) and not isinstance(fmt, bool):
        newer = fmt > FORMAT
        if newer:
            problems.append(f"it is format {fmt}, from a newer MusiKata: it is read, not written")
    elif fmt is not None:
        problems.append(f"format isn't a number: {fmt!r}; read as format {FORMAT}")
    library = data.get("library", {})
    if not isinstance(library, dict):
        problems.append(f"library isn't a group: {library!r}")
        library = {}
    root = _root(library.get("root"), home, problems)
    watch = library.get("watch", True)
    if not isinstance(watch, bool):
        problems.append(f"library.watch isn't true or false: {watch!r}; on")
        watch = True
    computer = data.get("computer", {})
    if not isinstance(computer, dict):
        problems.append(f"computer isn't a group: {computer!r}")
        computer = {}
    cid, name = computer.get("id"), computer.get("name")
    if cid is not None and not (isinstance(cid, str) and cid):
        problems.append(f"computer.id isn't an id: {cid!r}; a new one is made")
    playback = _playback(data.get("playback", {}), problems)
    return Shared(
        root=root,
        watch=watch,
        computer_id=cid if isinstance(cid, str) and cid else None,
        computer_name=name if isinstance(name, str) else None,
        playback=playback,
        data=data,
        newer=newer,
        problems=tuple(problems),
    )


def load(path: str, home: str) -> Shared:
    """The shared settings in the file at `path` (none there: the defaults, the first start), each
    problem logged."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return Shared()
    except OSError as e:
        log.warning("couldn't read %s: %s; the settings take their defaults", path, e)
        return Shared(problems=(f"couldn't be read: {e}",))
    shared = parse(text, home)
    for problem in shared.problems:
        log.warning("%s: %s", path, problem)
    return shared


def _new_id() -> str:
    return str(uuid.uuid4())


def with_root(
    shared: Shared, root: str, computer_name: str, new_id: Callable[[], str] = _new_id
) -> dict[str, object]:
    """The file's content with `root` as the configured root: the rest as it was read, fields it
    doesn't know included (A2.10), and this computer's id made when it has none (A2.8)."""
    data = _with_computer(shared, computer_name, new_id)
    library = data.get("library")
    data["library"] = {**(library if isinstance(library, dict) else {}), "root": root}
    return data


def with_playback(
    shared: Shared,
    computer_name: str,
    fields: Mapping[str, object],
    new_id: Callable[[], str] = _new_id,
) -> dict[str, object]:
    """The file's content with `fields` set in its `playback` group (shuffle and repeat, R7.3):
    the rest as it was read, fields it doesn't know included (A2.10), and this computer's id made
    when it has none (A2.8)."""
    data = _with_computer(shared, computer_name, new_id)
    playback = data.get("playback")
    data["playback"] = {**(playback if isinstance(playback, dict) else {}), **fields}
    return data


def _with_computer(
    shared: Shared, computer_name: str, new_id: Callable[[], str]
) -> dict[str, object]:
    """The file's content as read, at this format, with this computer's id made when it has none
    and its name when it has none."""
    data = dict(shared.data)
    data["format"] = FORMAT
    computer = data.get("computer")
    computer = dict(computer) if isinstance(computer, dict) else {}
    if shared.computer_id is None:
        computer["id"] = new_id()
    if not isinstance(computer.get("name"), str):
        computer["name"] = computer_name
    data["computer"] = computer
    return data


def save(path: str, data: Mapping[str, object]) -> bool:
    """Writes `data` to the file at `path`, to a temporary file beside it and moved over the old one
    (A2.8), so a crash or a sync never leaves half a file; False, logged, when it can't be."""
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as e:
        log.warning("couldn't write %s: %s", path, e)
        return False
    return True


def _writable(path: str, home: str, what: str) -> Shared | None:
    """The shared settings at `path`, read again to be changed and written back; None, logged,
    when they mustn't be: a newer MusiKata's (A2.10), or a file there that can't be read, which
    writing would empty (a sync in progress, a hand edit gone wrong)."""
    shared = load(path, home)
    if shared.newer:
        log.warning("didn't keep %s: %s is a newer MusiKata's", what, path)
        return None
    if shared.problems and not shared.data and os.path.exists(path):
        log.warning("didn't keep %s: %s couldn't be read, and is left as it is", what, path)
        return None
    return shared


def set_playback(path: str, home: str, computer_name: str, **fields: object) -> bool:
    """Keeps `fields` (shuffle, repeat: R7.3) in the playback group of the shared settings at
    `path`, the rest as it was; False, logged, when they can't be written (`_writable`)."""
    what = ", ".join(f"{k} {v}" for k, v in fields.items())
    shared = _writable(path, home, what)
    return shared is not None and save(path, with_playback(shared, computer_name, fields))


def computer_id(path: str, home: str, computer_name: str) -> str | None:
    """This computer's id (A2.8), from the shared settings at `path`, made and written there when
    they have none; None, logged, when it has none and one can't be written."""
    found = load(path, home)
    if found.computer_id is not None:
        return found.computer_id
    shared = _writable(path, home, "this computer's id")
    if shared is None:
        return None
    data = _with_computer(shared, computer_name, _new_id)
    made = data["computer"]
    assert isinstance(made, dict)
    return str(made["id"]) if save(path, data) else None


def choose_root(path: str, home: str, root: str, computer_name: str) -> bool:
    """Makes `root` the configured root (R2.1) in the shared settings at `path`; False, logged,
    when it can't be written, or was written by a newer MusiKata (A2.10)."""
    shared = load(path, home)
    if shared.newer:
        log.warning("didn't keep %s as the music root: %s is a newer MusiKata's", root, path)
        return False
    if shared.problems and not shared.data and os.path.exists(path):
        log.warning("%s couldn't be read: it is written anew", path)
    if save(path, with_root(shared, root, computer_name)):
        log.info("the music root is %s from now on", root)
        return True
    return False


# ---------- the root's own settings.json (R13.9): what writing tags needs ----------

ID3_VERSIONS = ("2.4", "2.3")  # R13.3: 2.4 the default (R4.7.2)
ROOT_DIR = ".musikata"  # the root's own folder (R1.5)


HISTORY_DAYS = 90  # R4.9, R13.3: how long the change history keeps an entry, by default
RATING_SCALES = ("windows-media", "musikata")  # R10.4.1, R13.3: Windows Media the default


@dataclass(frozen=True)
class RootTags:
    """The root's Tags settings (R13.3) that writing tags needs: the ID3 version MP3s are written
    as (R4.7.2), whether a written file keeps its modification time (R4.7.1's "Leave file
    modification times alone", off), and the change history's "Keep a history of tag changes"
    (`history`, on) and for how many days (`history_days`, 90) (R4.9); "Write ratings into the
    files" (`write_ratings`, on: off keeps every rating in ratings.json, R10.3) and "Rating scale
    in files" (`rating_scale`, Windows Media's, or MusiKata's own POPM scale, R10.4.1); what
    couldn't be used, for the log."""

    id3_version: str = "2.4"
    keep_modified_times: bool = False
    history: bool = True
    history_days: int = HISTORY_DAYS
    write_ratings: bool = True
    rating_scale: str = "windows-media"
    problems: tuple[str, ...] = ()


def _days(value: object) -> int | None:
    """A number of days from `value`: a whole number of 1 or more, also as 90.0 or "90", as a
    person may write it; None when it isn't one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and value >= 1 else None


def root_path(root: str) -> str:
    """The root's own settings.json (R13.9), in its .musikata."""
    return os.path.join(root, ROOT_DIR, NAME)


def parse_root_tags(text: str) -> RootTags:
    """The `tags` group's id3_version, keep_modified_times, history, history_days, write_ratings
    and rating_scale in the root's settings.json, `text`, whatever was written there (A2.10): what
    can't be used is named in `problems` and takes its default (R13.9). A version written as a
    number (2.3) or with a "v" ("v2.3"), days written as text ("90") or 90.0, and a scale in
    another case or with a space or "_" ("Windows Media", "MUSIKATA") are read as meant; a newer
    format is read for what it can."""
    try:
        data = json.loads(text.removeprefix("\ufeff"))
    except ValueError as e:
        return RootTags(problems=(f"it isn't JSON ({e}): its settings take their defaults",))
    if not isinstance(data, dict):
        return RootTags(problems=("it isn't a JSON object: its settings take their defaults",))
    problems: list[str] = []
    group = data.get("tags", {})
    if not isinstance(group, dict):
        problems.append(f"tags isn't a group: {group!r}")
        group = {}
    default = RootTags()
    version = group.get("id3_version", default.id3_version)
    if isinstance(version, float | int) and not isinstance(version, bool):
        version = f"{version:.1f}"
    if isinstance(version, str):
        version = version.strip().lower().removeprefix("id3").removeprefix("v")
    if version not in ID3_VERSIONS:
        problems.append(f"tags.id3_version isn't 2.3 or 2.4: {group.get('id3_version')!r}; 2.4")
        version = default.id3_version
    keep = group.get("keep_modified_times", default.keep_modified_times)
    if not isinstance(keep, bool):
        problems.append(f"tags.keep_modified_times isn't true or false: {keep!r}; off")
        keep = default.keep_modified_times
    history = group.get("history", default.history)
    if not isinstance(history, bool):
        problems.append(f"tags.history isn't true or false: {history!r}; on")
        history = default.history
    days = _days(group.get("history_days", default.history_days))
    if days is None:
        problems.append(
            f"tags.history_days isn't a number of days: {group.get('history_days')!r};"
            f" {default.history_days}"
        )
        days = default.history_days
    write_ratings = group.get("write_ratings", default.write_ratings)
    if not isinstance(write_ratings, bool):
        problems.append(f"tags.write_ratings isn't true or false: {write_ratings!r}; on")
        write_ratings = default.write_ratings
    scale = group.get("rating_scale", default.rating_scale)
    if isinstance(scale, str):
        scale = "-".join(scale.strip().lower().replace("_", " ").split())
    if scale not in RATING_SCALES:
        problems.append(
            f"tags.rating_scale isn't windows-media or musikata: {group.get('rating_scale')!r};"
            " windows-media"
        )
        scale = default.rating_scale
    return RootTags(str(version), keep, history, days, write_ratings, str(scale), tuple(problems))


def root_tags(root: str) -> RootTags:
    """The root's Tags settings for writing (`parse_root_tags`) from its settings.json; the
    defaults when it has none, or it can't be read, each problem logged. A root without its own
    file takes the configured root's when Settings comes (R13.9.1); until then, the defaults."""
    path = root_path(root)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return RootTags()
    except OSError as e:
        log.warning("couldn't read %s: %s; writing tags takes the defaults", path, e)
        return RootTags(problems=(f"couldn't be read: {e}",))
    found = parse_root_tags(text)
    for problem in found.problems:
        log.warning("%s: %s", path, problem)
    return found
