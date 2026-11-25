"""The core package's version and repository (src/musikata_core/__init__.py): one place each, which
the release (scripts/publish.sh) and the update check (R1.9) read.

Why: a release is tagged from __version__, and CI stops a tag that doesn't match it
(docs/process/release.md); a version that isn't PEP 440, or a second copy of the repository's
address, would stop a release at its last step."""

import os
import re
import subprocess

from packaging.version import Version

import musikata_core

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def test_the_version_is_pep_440_and_the_one_the_release_reads():
    assert str(Version(musikata_core.__version__)) == musikata_core.__version__
    with open(os.path.join(ROOT, "src", "musikata_core", "__init__.py")) as f:
        read = re.search(r'^__version__ = "(.*)"', f.read(), re.M)
    assert read and read.group(1) == musikata_core.__version__


def test_the_repository_is_musikatas_as_publish_sh_reads_it():
    """publish.sh takes the repository from this file with sed, not by importing it."""
    assert musikata_core.MUSIKATA_REPO == "https://github.com/MojoKata/MusiKata"
    init = os.path.join(ROOT, "src", "musikata_core", "__init__.py")
    with open(os.path.join(ROOT, "scripts", "publish.sh")) as f:
        expr = re.search(r"REPO=\$\(sed -n '([^']+)'", f.read()).group(1)
    out = subprocess.run(["sed", "-n", expr, init], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "MojoKata/MusiKata"
