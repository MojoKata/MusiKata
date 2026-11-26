"""A root's id and finding its index (A2.9, R1.5): the index and caches of a root are kept under
its id, made when it's first opened and kept in <root>/.musikata/root.json, so a drive given
another letter or mount point keeps its index, and a copy of a root gets one of its own."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from .clock import Clock

log = logging.getLogger(__name__)
KEEP = timedelta(days=180)  # an index not opened for longer is removed (A2.9)
FORMAT = 1  # root.json's and index.json's format (A2.10)


def roots_dir(env: Mapping[str, str], platform: str = sys.platform) -> str:
    """Where this computer keeps each root's index (R1.5's table); MUSIKATA_DATA moves it
    (docs/process/development.md)."""
    if env.get("MUSIKATA_DATA"):
        return os.path.join(env["MUSIKATA_DATA"], "roots")
    home = env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")
    if platform.startswith("win"):
        local = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(local, "MusiKata", "Roots")
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "MusiKata", "Roots")
    data = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(data, "musikata", "roots")


def caches_dir(env: Mapping[str, str], platform: str = sys.platform) -> str:
    """Where this computer keeps each root's caches, cover thumbnails among them (R1.5's table),
    each root's under its index's key; MUSIKATA_DATA moves them beside the indexes."""
    if env.get("MUSIKATA_DATA"):
        return os.path.join(env["MUSIKATA_DATA"], "cache")
    home = env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")
    if platform.startswith("win"):
        local = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(local, "MusiKata", "Cache")
    if platform == "darwin":
        return os.path.join(home, "Library", "Caches", "MusiKata")
    return os.path.join(env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"), "musikata")


def path_key(root: str) -> str:
    """The folder name of a root that holds no id of its own (R1.5.2): a hash of its path."""
    return "path-" + hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:16]


def decide(recorded: str | None, root: str, recorded_holds_same_id: bool) -> str:
    """What opening `root` under an id whose index last opened it at `recorded` means: "use" (the
    same path, or a new index), "moved" (the old path no longer holds a root with this id) or
    "copy" (it still does, so this is a copy and needs an id of its own)."""
    if recorded is None or os.path.normcase(recorded) == os.path.normcase(root):
        return "use"
    return "copy" if recorded_holds_same_id else "moved"


def stale(last_opened: Mapping[str, datetime], now: datetime) -> list[str]:
    """The index folders not opened for 180 days."""
    return sorted(name for name, when in last_opened.items() if now - when > KEEP)


@dataclass(frozen=True)
class Found:
    """Where a root's index is, under which key, and whether the root's .musikata can be
    written."""

    folder: str
    key: str
    writable: bool


def _read_json(path: str) -> dict[str, object] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError, ValueError:
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: str, data: Mapping[str, object]) -> bool:
    """Written to a temporary file beside it and moved over (A2.8); False when it can't be."""
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def root_id(root: str) -> str | None:
    """The id in <root>/.musikata/root.json, if it has one."""
    data = _read_json(os.path.join(root, ".musikata", "root.json"))
    value = data.get("id") if data else None
    return value if isinstance(value, str) and value else None


def _new_id(root: str, data: Mapping[str, object] | None) -> str | None:
    """A new id written into root.json, keeping its other fields (A2.10); None if it can't be."""
    new = str(uuid.uuid4())
    fields = dict(data or {})
    fields.update(format=fields.get("format", FORMAT), id=new)
    return new if _write_json(os.path.join(root, ".musikata", "root.json"), fields) else None


def find_index(root: str, base: str, clock: Clock) -> Found:
    """The folder under `base` (roots_dir) that holds `root`'s index, made or moved as A2.9 says,
    with its index.json recording the path and when it was opened."""
    root = os.path.realpath(root)
    meta_path = os.path.join(root, ".musikata", "root.json")
    data = _read_json(meta_path)
    key = root_id(root) or _new_id(root, data)
    writable = key is not None and os.access(os.path.join(root, ".musikata"), os.W_OK)
    if key is not None:
        folder = os.path.join(base, key)
        recorded = (_read_json(os.path.join(folder, "index.json")) or {}).get("path")
        recorded = recorded if isinstance(recorded, str) else None
        same = recorded is not None and root_id(recorded) == key
        what = decide(recorded, root, same)
        if what == "copy":
            new = _new_id(root, _read_json(meta_path))
            log.info("%s is a copy of %s: it gets an index of its own", root, recorded)
            key = new or path_key(root)
            writable = new is not None
        elif what == "moved":
            log.info("%s was at %s: its index follows it", root, recorded)
    else:
        key = path_key(root)
    folder = os.path.join(base, key)
    os.makedirs(folder, exist_ok=True)
    record = {"format": FORMAT, "path": root, "opened": clock.now().isoformat()}
    _write_json(os.path.join(folder, "index.json"), record)
    return Found(folder, key, writable)


def remove_stale(base: str, clock: Clock, keep: str | None = None) -> list[str]:
    """Removes each index folder not opened for 180 days (A2.9), but `keep`; says which in the
    log, and returns them."""
    opened: dict[str, datetime] = {}
    try:
        names = os.listdir(base)
    except OSError:
        return []
    for name in names:
        when = (_read_json(os.path.join(base, name, "index.json")) or {}).get("opened")
        if isinstance(when, str):
            try:
                opened[name] = datetime.fromisoformat(when)
            except ValueError:
                continue
    gone = [name for name in stale(opened, clock.now()) if name != keep]
    for name in gone:
        shutil.rmtree(os.path.join(base, name), ignore_errors=True)
        log.info("removed the index of %s, not opened for 180 days", name)
    return gone
