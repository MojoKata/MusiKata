"""scripts/check.sh (docs/process/development.md, "Before each commit"): it runs each check tier 1
gates that is quick, and --install-hook makes it a clone's pre-commit hook without overwriting one
that is there.

Why: a check that is run by hand is only as good as the list it runs; this holds the script to the
list development.md gives."""

import os
import shutil
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(ROOT, "scripts", "check.sh")
needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="no sh (Windows)")


def test_it_runs_each_quick_check_of_tier_1():
    with open(SCRIPT) as f:
        text = f.read()
    for check in (
        "ruff format --check",
        "ruff check",
        "mypy src",
        "scripts/doccheck.py",
        "scripts/public_text.py check",
        '-m "not slow"',
    ):
        assert check in text, check


@needs_sh
def test_install_hook_makes_the_pre_commit_hook_once(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "check.sh")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    run = [str(tmp_path / "scripts" / "check.sh"), "--install-hook"]
    first = subprocess.run(run, capture_output=True, text=True)
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    assert first.returncode == 0, first.stderr
    assert "scripts/check.sh" in hook.read_text() and os.access(hook, os.X_OK)
    again = subprocess.run(run, capture_output=True, text=True)
    assert again.returncode == 1 and "there already" in again.stderr
