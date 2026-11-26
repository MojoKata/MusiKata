"""The shared settings (R13.9, A2.10): `settings.json` in the shared settings folder (R1.5), what
belongs to this computer and this person, the configured root (R2.1) among it.

This much is what the configured root needs: where the file is, reading it in whatever shape a
person, a sync tool or another version of MusiKata left it, and writing the root back, every field
it doesn't know kept (A2.10). The rest of the shared settings and the root's own `settings.json`
come with Settings (R13).

A value it can't use is reported in the App log and its default used (R13.9); a file of a newer
format is read for what it can and never written (A2.10)."""

from __future__ import annotations

import json
import logging
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


@dataclass(frozen=True)
class Shared:
    """The shared settings as read: the configured root (None: none yet, the first start, R2.1),
    Watch for changes (R13.2), this computer's id and name (A2.8); `data`, the file as read, which
    a rewrite keeps; `newer`, a newer MusiKata's format, never written; and what couldn't be used,
    for the log."""

    root: str | None = None
    watch: bool = True
    computer_id: str | None = None
    computer_name: str | None = None
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
    return Shared(
        root=root,
        watch=watch,
        computer_id=cid if isinstance(cid, str) and cid else None,
        computer_name=name if isinstance(name, str) else None,
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
    data = dict(shared.data)
    data["format"] = FORMAT
    library = data.get("library")
    data["library"] = {**(library if isinstance(library, dict) else {}), "root": root}
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
