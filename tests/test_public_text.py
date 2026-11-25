"""No private name in the public repository (scripts/public_text.py): not the private projects that
share the machine MusiKata is developed on, nor private accounts and domains.

Why: the documents, scripts and mockups are written on a machine shared with private work, and a
name that belongs to the machine, not to MusiKata, can slip into a file. AppKata found its shared
VM named after another project and its scripts logging in as a private account. This reads every
file git tracks or would add."""

import os
import subprocess
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import public_text  # noqa: E402


def _tracked():
    """The files git tracks, and those it would add (untracked, not ignored): a file is checked
    before its first commit."""
    try:
        out = subprocess.run(
            ["git", "-C", ROOT, "ls-files", "-z", "-co", "--exclude-standard"],
            capture_output=True,
            check=True,
        ).stdout
    except OSError, subprocess.CalledProcessError:
        pytest.skip("not a git work tree")
    return [p for p in out.decode().split("\0") if p]


def test_no_private_name_in_any_tracked_file():
    hits = {}
    for rel in _tracked():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        if b"\0" in data[:8192]:
            continue  # binary: the mockups' text is render.py's
        found = public_text.found(data.decode("utf-8", errors="replace"))
        if found:
            hits[rel] = found
    assert not hits, f"private names in files git tracks or would add: {hits}"


def test_the_check_finds_a_name_however_it_is_written(monkeypatch):
    monkeypatch.setattr(
        public_text, "PRIVATE", {public_text.digest("examplecorp"), public_text.digest("lab-vm")}
    )
    for text in (
        "ExampleCorp's VM",
        "~/examplecorp/scripts",
        "user examplecorp@127.0.0.1",
        "C:\\Users\\examplecorp",
        "examplecorp-vm2",
        "the-examplecorp_tools.sh",
        "~/lab-vm/README.md",
        "container lab-vm",
    ):
        assert public_text.found(text), text
    for text in ("examplecorporation", "myexamplecorp", "lab vm", "lab-vmware"):
        assert not public_text.found(text), text
