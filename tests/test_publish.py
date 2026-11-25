"""scripts/publish.sh, the owner's steps for the release key and releases (docs/process/genesis.md,
docs/process/release.md): what can be checked without GitHub, against stand-ins for gh."""

import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(ROOT, "scripts", "publish.sh")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import field_test as ft  # noqa: E402

needs_sh = pytest.mark.skipif(
    not shutil.which("sh"), reason="runs publish.sh, a POSIX shell script"
)
needs_git = pytest.mark.skipif(
    not (shutil.which("sh") and shutil.which("git")), reason="runs publish.sh in git"
)


def _read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


def _script():
    return _read("scripts", "publish.sh")


def test_the_usage_lists_every_command_the_script_takes():
    text = _script()
    listed = set(re.findall(r"^#     ([a-z][a-z-]+)", text, re.M))
    dispatch = text[text.index("case $CMD in") :]
    taken = set()
    for pattern in re.findall(r"^\s+([a-z|-]+)\)", dispatch, re.M):
        taken |= set(pattern.split("|"))
    assert listed == taken, (listed, taken)


@pytest.mark.skipif(not shutil.which("gpg"), reason="needs gpg")
def test_key_new_makes_a_certify_only_main_key_and_a_signing_subkey(tmp_path):
    passphrase = tmp_path / "passphrase"
    passphrase.write_text("a passphrase for the test\n")
    home = tmp_path / "key"
    env = dict(os.environ, MUSIKATA_KEY_PASSPHRASE_FILE=str(passphrase))
    try:
        subprocess.run(
            ["sh", SCRIPT, "key-new", str(home), "MusiKata test <test@example.org>"],
            env=env,
            check=True,
            capture_output=True,
            timeout=120,
        )
        out = subprocess.run(
            ["gpg", "--batch", "--with-colons", "--list-keys"],
            env=dict(env, GNUPGHOME=str(home / "gnupg")),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    finally:
        subprocess.run(
            ["gpgconf", "--kill", "all"],
            env=dict(os.environ, GNUPGHOME=str(home / "gnupg")),
            capture_output=True,
        )
    rows = [line.split(":") for line in out.splitlines()]
    pub = [r for r in rows if r[0] == "pub"]
    sub = [r for r in rows if r[0] == "sub"]
    fpr = next(r[9] for r in rows if r[0] == "fpr")
    assert len(pub) == 1 and len(sub) == 1
    assert pub[0][3] == sub[0][3] == "22", "ed25519 both"  # algorithm 22: EdDSA

    def own(r):  # upper case: the whole key's
        return "".join(c for c in r[11] if c.islower())

    def years(r):
        return (int(r[6]) - int(r[5])) / (365.25 * 86400)

    assert own(pub[0]) == "c" and own(sub[0]) == "s", (pub[0][11], sub[0][11])
    assert 4.9 < years(pub[0]) < 5.1 and 1.9 < years(sub[0]) < 2.1
    assert int(pub[0][5]) <= time.time()
    assert (home / "fingerprint").read_text().strip() == fpr
    assert "BEGIN PGP PUBLIC KEY BLOCK" in (home / "musikata-release-key.asc").read_text()
    assert "REVOCATION" in (home / "revocation.asc").read_text().upper()
    assert oct((home / "gnupg").stat().st_mode & 0o777) == "0o700"


def _checks():
    text = _script()
    return text[text.index("check() {") : text.index("\n}\n", text.index("check() {"))]


def test_every_check_genesis_names_is_one_the_script_reads_back():
    genesis = _read("docs", "process", "genesis.md")
    read_back = re.findall(r'^\s+(?:else )?is "([^"]+)"', _checks(), re.M)
    named = []
    for paragraph in re.findall(
        r"^Check: `publish\.sh check`(.*?)(?:\n\n|\Z)", genesis, re.M | re.S
    ):
        named += re.findall(r'"([^"]+)"', paragraph.replace("\n", " "))
    assert "actions pinned by SHA" in named
    missing = [name for name in named if not any(label.startswith(name) for label in read_back)]
    assert not missing, missing


REFUSING_GH = """#!/bin/sh
# gh as a member without admin rights sees GitHub: every read refused, the API's error JSON on
# stdout
printf '{"message":"Must have admin rights to Repository.","status":"403"}'
echo "gh: Must have admin rights to Repository. (HTTP 403)" >&2
exit 1
"""


@needs_sh
def test_check_says_it_cant_read_what_github_refuses_and_goes_on(tmp_path):
    """check, run by a member who can't read a setting: a refusal is never taken for the answer (gh
    prints the API's error JSON on stdout), and a refused read doesn't end the check (set -e). With
    gh refusing every read, every line check reads back says "(can't read)", through to the last."""
    gh = tmp_path / "gh"
    gh.write_text(REFUSING_GH)
    gh.chmod(0o755)
    r = subprocess.run(
        ["sh", SCRIPT, "--repo", "owner/name", "check"],
        capture_output=True,
        text=True,
        timeout=60,
        env=dict(os.environ, PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}"),
    )
    lines = r.stderr.splitlines()
    assert r.returncode == 1 and "{" not in r.stderr, r.stderr
    assert "  release key: " in lines[-1], r.stderr  # it went on to the end
    for name in dict.fromkeys(re.findall(r'\bis "([^"]+)" "\$\((?:api|gh) ', _checks())):
        if name in (
            "release environment: deploys",
            "release environment: secrets",
        ) or name.startswith(("master ruleset:", "tags ruleset:")):
            continue  # read only once the environment or the ruleset is there
        assert f"FAIL  {name}: (can't read) (want" in r.stderr, name


FAKE_GH = r"""#!/usr/bin/env python3
# gh for publish.sh field-test, without GitHub: answers what it asks and logs each call as JSON
import json, os, sys
d, a = os.environ["FAKE_GH_DIR"], sys.argv[1:]
call = {"args": a}
if a[:2] == ["issue", "create"]:
    call["body"] = sys.stdin.read()
    n = 101 + len([f for f in os.listdir(d) if f.startswith("issue-")])
    open(os.path.join(d, f"issue-{n}"), "w").close()
    print(f"https://github.com/owner/name/issues/{n}")
elif a[:2] == ["label", "list"]:
    print(os.environ.get("FAKE_GH_LABELS", "bug\nfield-test"))
elif a[:2] == ["issue", "list"]:
    print(os.environ.get("FAKE_GH_ISSUES", ""), end="")
elif a[0] == "api" and a[1].startswith("repos/owner/name/issues/") and "--jq" in a:
    print(9000 + int(a[1].rsplit("/", 1)[1]))
with open(os.path.join(d, "calls"), "a") as f:
    f.write(json.dumps(call) + "\n")
"""


def _field_test(tmp_path, **env):
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    r = subprocess.run(
        ["sh", SCRIPT, "--repo", "owner/name", "--yes", "field-test", "0.9.9"],
        capture_output=True,
        text=True,
        timeout=60,
        env=dict(
            os.environ,
            FAKE_GH_DIR=str(tmp_path),
            **env,
            PATH=f"{gh.parent}{os.pathsep}{os.environ['PATH']}",
        ),
    )
    calls = (
        [json.loads(line) for line in (tmp_path / "calls").read_text().splitlines()]
        if (tmp_path / "calls").exists()
        else []
    )
    return r, calls


@needs_sh
def test_field_test_opens_the_release_issue_and_one_under_it_per_environment(tmp_path):
    """publish.sh field-test: the release's issue, then one per environment of
    scripts/field_test.py, with its checklist, each made a sub-issue of the release's; all labelled
    field-test."""
    r, calls = _field_test(tmp_path)
    assert r.returncode == 0, r.stderr
    made = [c for c in calls if c["args"][:2] == ["issue", "create"]]

    def title(c):
        return c["args"][c["args"].index("--title") + 1]

    envs = list(ft.environments())
    assert [title(c) for c in made] == ["Field test: 0.9.9"] + [
        f"Field test: 0.9.9 on {e}" for e in envs
    ]
    assert all(c["args"][c["args"].index("--label") + 1] == "field-test" for c in made)
    assert all(f"- {e}" in made[0]["body"] for e in envs)
    assert [c["body"] for c in made[1:]] == [ft.issue_body(e) for e in envs]
    linked = [c["args"] for c in calls if "repos/owner/name/issues/101/sub_issues" in c["args"]]
    assert [a[a.index("-F") + 1] for a in linked] == [
        f"sub_issue_id={9102 + i}" for i in range(len(envs))
    ]


@needs_sh
def test_field_test_opens_nothing_without_the_label_or_twice(tmp_path):
    for case, env, says in (
        ("no-label", {"FAKE_GH_LABELS": "bug"}, "publish.sh setup makes it"),
        ("twice", {"FAKE_GH_ISSUES": "7\n"}, "already"),
    ):
        (tmp_path / case).mkdir()
        r, calls = _field_test(tmp_path / case, **env)
        assert r.returncode == 1 and says in r.stderr, (case, r.stderr)
        assert not [c for c in calls if c["args"][:2] == ["issue", "create"]], case


def test_the_field_tests_environments_are_testing_mds_tier_3_ones():
    """Each environment the field test opens an issue for is on a row of testing.md's Environments
    table whose tier includes 3, and every such row has at least one of them."""
    text = _read("docs", "process", "testing.md")
    table = text[text.index("## Environments") :]
    table = table[: table.index("\n\n", table.index("|"))]
    rows = [
        r for r in re.findall(r"^\| ([^|]+?) \| ([^|]+?) \|", table, re.M) if r[0] != "Environment"
    ]
    tier3 = [env for env, tiers in rows if "3" in tiers.split(", ")]
    words = [w for _, _, w in ft.ENVIRONMENTS]
    for w in words:
        assert any(w in env for env in tier3), w
    for env in tier3:
        assert any(w in env for w in words), env


def test_every_environment_has_a_checklist_with_each_id_once():
    for env in ft.environments():
        ids = [cid for cid, _ in ft.checklist(env)]
        assert len(ids) == len(set(ids)) and "install" in ids, env
        assert "{" not in ft.issue_body(env), env


RESUME_GH = r'''#!/usr/bin/env python3
# gh for publish.sh resume, without GitHub: run 77 of v0.9.9, built and not waiting for an approval.
# FAKE_GH_ATTEMPTS is the run's attempts; a build job carries its sha256 notice only in the attempts
# FAKE_GH_BUILT names, as when "gh run rerun --failed" carries a job over into a new attempt.
# FAKE_GH_LATE: how many times the run list comes back empty before the run shows; FAKE_GH_RUNNING:
# how many times the run is still in progress before it has finished.
import os, re, sys
a = sys.argv[1:]


def once_more(what):
    """Whether this call is still one of the first FAKE_GH_<what> (counted in a file beside gh)."""
    count = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), what + ".count")
    n = int(open(count).read()) if os.path.exists(count) else 0
    open(count, "w").write(str(n + 1))
    return n < int(os.environ.get("FAKE_GH_" + what, "0"))


attempts, built = int(os.environ["FAKE_GH_ATTEMPTS"]), os.environ["FAKE_GH_BUILT"].split()
sha = {"appimage": "a" * 64 + "  MusiKata-0.9.9-x86_64.AppImage",
       "windows": "b" * 64 + "  MusiKata-0.9.9-setup.exe",
       "macos-arm64": "c" * 64 + "  MusiKata-0.9.9-arm64.dmg",
       "macos-x86_64": "d" * 64 + "  MusiKata-0.9.9-x86_64.dmg"}
job = lambda attempt, name: f"{attempt}0{1 + list(sha).index(name)}"      # 101, 102, ..., 201, ...
q = a[a.index("--jq") + 1] if "--jq" in a else ""
name = next((n for n in sha if f'"{n}"' in q), None)
if a[:2] == ["run", "list"]:
    print("" if once_more("LATE") else 77)
elif a[:2] == ["run", "view"] and "status,conclusion" in a:
    print("in_progress " if once_more("RUNNING") else "completed success")
elif a[:2] == ["run", "view"] and "attempt" in a:
    print(attempts)
elif a[0] == "api" and a[1].endswith("/pending_deployments"):
    print(0)
elif a[0] == "api" and (m := re.search(r"/attempts/(\d+)/jobs$", a[1])):
    print(job(int(m.group(1)), name))
elif a[0] == "api" and (m := re.search(r"/check-runs/(\d)0(\d)/annotations$", a[1])):
    n = list(sha)[int(m.group(2)) - 1]
    if m.group(1) in built:
        print(sha[n])
'''

# sleep for publish.sh, which writes down how long it was asked to wait and goes on at once
SLEEP = """#!/bin/sh
echo "$*" >> "$(dirname "$0")/slept"
"""

# how often publish.sh asks GitHub, short for the tests (the defaults wait 10 and 20 seconds a time)
POLLS = {"MUSIKATA_RUN_POLL": "0", "MUSIKATA_APPROVAL_POLL": "0"}
BUILT = "".join(
    f"{c * 64}  MusiKata-0.9.9-{f}\n"
    for c, f in (
        ("a", "x86_64.AppImage"),
        ("b", "setup.exe"),
        ("c", "arm64.dmg"),
        ("d", "x86_64.dmg"),
    )
)


def _resume(tmp_path, sleep=False, polls=POLLS, **env):
    """publish.sh resume 0.9.9 against RESUME_GH (and with sleep, the SLEEP stand-in), with env."""
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(RESUME_GH)
    gh.chmod(0o755)
    if sleep:
        (gh.parent / "sleep").write_text(SLEEP)
        (gh.parent / "sleep").chmod(0o755)
    base = {k: v for k, v in os.environ.items() if k not in POLLS}
    return subprocess.run(
        [
            "sh",
            SCRIPT,
            "--repo",
            "owner/name",
            "--key",
            str(tmp_path / "no-key.asc"),
            "--yes",
            "resume",
            "0.9.9",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=dict(base, **polls, **env, PATH=f"{gh.parent}{os.pathsep}{os.environ['PATH']}"),
    )


@needs_sh
@pytest.mark.parametrize(
    "attempts, built, shown",
    [
        (1, "1", True),  # the run as it first ran
        (2, "2", True),  # run again whole: each attempt builds again
        (2, "1", True),  # gh run rerun --failed: the builds carried over from attempt 1
        (3, "1", True),
        (2, "", False),  # no attempt posted them
    ],
)
def test_resume_shows_what_ci_built_after_any_rerun(tmp_path, attempts, built, shown):
    """resume shows the SHA-256s of the four builds before the owner approves the signing. After "gh
    run rerun --failed", GitHub carries the build jobs that passed into the new attempt as new jobs
    without their annotations; resume reads each from the attempt that built it."""
    r = _resume(tmp_path, FAKE_GH_ATTEMPTS=str(attempts), FAKE_GH_BUILT=built)
    assert r.returncode == 1, r.stderr  # verify then stops: no key to check with
    if shown:
        assert BUILT in r.stderr, r.stderr
        assert "no public key to check the signature with" in r.stderr, r.stderr
    else:
        assert (
            "publish.sh: the run's build jobs didn't all post their sha256 notices" in r.stderr
        ), r.stderr


@needs_sh
@pytest.mark.parametrize(
    "polls, run, approval",
    [
        ({}, "10", "20"),  # the defaults, as a real release waits
        ({"MUSIKATA_RUN_POLL": "1", "MUSIKATA_APPROVAL_POLL": "2"}, "1", "2"),
    ],
)
def test_resume_waits_for_the_run_to_show_and_then_to_finish(tmp_path, polls, run, approval):
    """resume waits between its questions to GitHub: for the tag's run until it shows, then for the
    run until it waits for the approval or ends, 10 and 20 seconds a time unless MUSIKATA_RUN_POLL
    and MUSIKATA_APPROVAL_POLL say otherwise. A run that shows on the third question, and has
    finished on the second, is waited for, and resume goes on to what CI built."""
    r = _resume(
        tmp_path,
        sleep=True,
        polls=polls,
        FAKE_GH_ATTEMPTS="1",
        FAKE_GH_BUILT="1",
        FAKE_GH_LATE="2",
        FAKE_GH_RUNNING="1",
    )
    assert BUILT in r.stderr, r.stderr
    assert (tmp_path / "bin" / "slept").read_text().split() == [run, run, run, approval]


GATE_GH = r"""#!/usr/bin/env python3
# gh for publish.sh release's and publish's gates, without GitHub. FAKE_CI: CI's run on master at
# the commit ("completed success", "in_progress ", "completed failure" or nothing); FAKE_FT_ALL
# and FAKE_FT_OPEN: the release's field-test issues; anything about the tag's run fails, which
# ends release.
import os, sys
a = sys.argv[1:]
if a[:2] == ["run", "list"] and "master" in a:
    print(os.environ.get("FAKE_CI", ""), end="")
elif a[:2] == ["release", "view"]:
    print("true")
elif a[:2] == ["issue", "list"]:
    print(os.environ.get("FAKE_FT_" + a[a.index("--state") + 1].upper(), ""), end="")
else:
    sys.exit(1)
"""

PREPARED = ("tier1", "tier2", "pins", "version", "state", "notes")
RECORD = "## Notes\n\nWhat a user sees.\n\n## Prepared\n\n" + "".join(
    f"- [x] **{s}** done\n" for s in PREPARED
)


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _gate_repo(tmp_path, record=RECORD, state=True, status="0.9.9: Linux, Windows and macOS"):
    """A clone of a repository like this one at the commit the release pull request left, whose
    origin is a bare repository standing in for github.com/owner/name."""
    work, bare = tmp_path / "work", tmp_path / "remote" / "github.com" / "owner" / "name.git"
    for d in ("scripts", "src/musikata_core", "docs/releases", "tests/data/state", "bin"):
        (work / d).mkdir(parents=True)
    shutil.copy(SCRIPT, work / "scripts" / "publish.sh")
    (work / "src/musikata_core/__init__.py").write_text(
        '__version__ = "0.9.9"\nMUSIKATA_REPO = "https://github.com/owner/name"\n'
    )
    (work / "DEVELOP.md").write_text(f"# Developing MusiKata\n\n## Status ({status})\n")
    if record is not None:
        (work / "docs/releases/0.9.9.md").write_text("# MusiKata 0.9.9\n\n" + record)
    if state:
        (work / "tests/data/state/0.9.9").mkdir()
        (work / "tests/data/state/0.9.9/settings.json").write_text("{}\n")
    (work / ".gitignore").write_text("bin/\n")
    gh = work / "bin" / "gh"
    gh.write_text(GATE_GH)
    gh.chmod(0o755)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(bare)], check=True)
    _git("init", "-q", "-b", "master", cwd=work)
    for k, v in (
        ("user.name", "Test"),
        ("user.email", "test@example.org"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
    ):  # this throwaway repository's own, for release's tag too
        _git("config", k, v, cwd=work)
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "0.9.9", cwd=work)
    _git("remote", "add", "origin", str(bare), cwd=work)
    _git("push", "-q", "origin", "master", cwd=work)
    return work, bare


def _gate(work, *args, **env):
    return subprocess.run(
        ["sh", str(work / "scripts" / "publish.sh"), "--yes", *args],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=120,
        env=dict(
            os.environ,
            **POLLS,
            **env,
            GIT_CONFIG_GLOBAL=os.devnull,
            PATH=f"{work / 'bin'}{os.pathsep}{os.environ['PATH']}",
        ),
    )


@needs_git
@pytest.mark.parametrize(
    "case, says",
    [
        ("no record", "the release pull request isn't merged"),
        ("a step left out", "the step notes isn't ticked"),
        ("a step not done", "has steps not done: - [ ] **extra**"),
        ("no notes", "has no Notes section"),
        ("no state", "tests/data/state/0.9.9/ is missing"),
        ("DEVELOP", "DEVELOP.md's Status heading doesn't name 0.9.9"),
        ("CI not run", "CI hasn't run on master"),
        ("CI running", "CI is still running on master"),
        ("CI failed", "CI failed on master"),
    ],
)
def test_release_tags_nothing_before_the_release_pull_request_is_merged_and_ci_passed_on_it(
    tmp_path, case, says
):
    """release tags only master's tip once the release pull request is merged with every step of its
    record ticked, the notes written, the state frozen, DEVELOP.md naming the version, and CI
    passed."""
    repo = {
        "no record": dict(record=None),
        "a step left out": dict(record=RECORD.replace("**notes**", "**other**")),
        "a step not done": dict(record=RECORD + "- [ ] **extra** a step\n"),
        "no notes": dict(record=RECORD.replace("## Notes", "## Words")),
        "no state": dict(state=False),
        "DEVELOP": dict(status="0.9.8: Linux, Windows and macOS"),
    }.get(case, {})
    ci = {"CI not run": "", "CI running": "in_progress \n", "CI failed": "completed failure\n"}.get(
        case, "completed success\n"
    )
    work, bare = _gate_repo(tmp_path, **repo)
    r = _gate(work, "release", FAKE_CI=ci)
    assert r.returncode == 1 and says in r.stderr, r.stderr
    tags = subprocess.run(["git", "tag"], cwd=bare, capture_output=True, text=True).stdout
    assert tags == "", tags


@needs_git
def test_release_tags_once_the_release_pull_request_is_merged_and_ci_passed_on_it(tmp_path):
    work, bare = _gate_repo(tmp_path)
    r = _gate(work, "release", FAKE_CI="completed success\n")
    assert "CI passed on master at" in r.stderr, r.stderr
    tags = subprocess.run(["git", "tag"], cwd=bare, capture_output=True, text=True).stdout
    assert tags == "v0.9.9\n", r.stderr


@needs_git
@pytest.mark.parametrize(
    "case, all_, open_, says",
    [
        ("none", "", "", "0.9.9 has no field-test issues"),
        (
            "open",
            "#5 CLOSED Field test: 0.9.9 on A\n#4 OPEN Field test: 0.9.9\n",
            "#4 OPEN Field test: 0.9.9\n",
            "the field test of 0.9.9 isn't done: these are open (docs/process/release.md, 4):\n"
            "#4 OPEN Field test: 0.9.9",
        ),
        (
            "closed",
            "#5 CLOSED Field test: 0.9.9 on A\n#4 CLOSED Field test: 0.9.9\n",
            "",
            "Every field-test issue of 0.9.9 is closed.\npublish.sh: no public key",
        ),
    ],
)
def test_publish_waits_for_every_field_test_issue_to_close(tmp_path, case, all_, open_, says):
    """publish refuses while the release has no field-test issues or one is open; once all are
    closed it goes on (to verify, which stops here on the missing key)."""
    work, _ = _gate_repo(tmp_path)
    r = _gate(
        work, "--key", str(tmp_path / "no-key.asc"), "publish", FAKE_FT_ALL=all_, FAKE_FT_OPEN=open_
    )
    assert r.returncode == 1 and says in r.stderr, r.stderr


CASK_GH = r"""#!/usr/bin/env python3
# gh for publish.sh cask: v0.9.9 published, its .dmg.sha256 files downloaded into -D
import os, sys
a = sys.argv[1:]
if a[:2] == ["release", "view"]:
    print(os.environ.get("FAKE_DRAFT", "false"))
elif a[:2] == ["release", "download"]:
    d = a[a.index("-D") + 1]
    for c, arch in (("e", "arm64"), ("f", "x86_64")):
        name = f"MusiKata-0.9.9-{arch}.dmg"
        open(os.path.join(d, name + ".sha256"), "w").write(f"{c * 64}  {name}\n")
else:
    sys.exit(1)
"""

CASK = """cask "musikata" do
  arch arm: "arm64", intel: "x86_64"

  version "0.9.8"
  sha256 arm:   "{old}",
         intel: "{old}"

  url "https://github.com/MojoKata/MusiKata/releases/download/v#{{version}}/MusiKata-#{{version}}-#{{arch}}.dmg"
  name "MusiKata"
  app "MusiKata.app"
end
"""


@needs_git
@pytest.mark.parametrize("draft", ["false", "true"])
def test_cask_points_the_tap_at_the_published_releases_dmgs(tmp_path, draft):
    """cask sets the cask's version and its two SHA-256s from the published release's .dmg.sha256
    files, changes nothing else, and commits on the branch musikata-<version> for a pull request
    on the tap; a draft is refused, since the cask's URLs are a published release's."""
    tap, bin_ = tmp_path / "tap", tmp_path / "bin"
    (tap / "Casks").mkdir(parents=True)
    bin_.mkdir()
    before = CASK.format(old="0" * 64)
    (tap / "Casks" / "musikata.rb").write_text(before)
    (bin_ / "gh").write_text(CASK_GH)
    (bin_ / "gh").chmod(0o755)
    _git("init", "-q", "-b", "main", cwd=tap)
    for k, v in (
        ("user.name", "Test"),
        ("user.email", "test@example.org"),
        ("commit.gpgsign", "false"),
    ):
        _git("config", k, v, cwd=tap)
    _git("add", "-A", cwd=tap)
    _git("commit", "-q", "-m", "0.9.8", cwd=tap)
    r = subprocess.run(
        ["sh", SCRIPT, "--repo", "owner/name", "--yes", "cask", str(tap), "0.9.9"],
        capture_output=True,
        text=True,
        timeout=60,
        env=dict(
            os.environ,
            FAKE_DRAFT=draft,
            GIT_CONFIG_GLOBAL=os.devnull,
            PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}",
        ),
    )
    after = (tap / "Casks" / "musikata.rb").read_text()
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=tap, capture_output=True, text=True
    ).stdout.split("\n")
    if draft == "true":
        assert r.returncode == 1 and "v0.9.9 isn't published" in r.stderr, r.stderr
        assert after == before and log[0] == "0.9.8"
        return
    assert r.returncode == 0, r.stderr
    assert after == before.replace('version "0.9.8"', 'version "0.9.9"').replace(
        f'arm:   "{"0" * 64}"', f'arm:   "{"e" * 64}"'
    ).replace(f'intel: "{"0" * 64}"', f'intel: "{"f" * 64}"')
    assert log[0] == "musikata 0.9.9"
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=tap, capture_output=True, text=True
    ).stdout.strip()
    assert branch == "musikata-0.9.9"


def test_the_steps_release_requires_are_the_ones_the_agent_is_told_to_take():
    """release reads the record's ticked steps by id (PREPARED); release-agent.md's "Prepare a
    release" names each step by the same id and shows the record's template. A step added to one and
    not the other is either never checked or never done."""
    prepared = re.search(r'^PREPARED="([^"]+)"', _script(), re.M).group(1).split()
    agent = _read("docs", "process", "release-agent.md")
    section = agent[agent.index("## 1. Prepare a release") : agent.index("## 2.")]
    assert re.findall(r"^\d+\. \*\*`([a-z0-9-]+)`:\*\*", section, re.M) == prepared
    assert re.findall(r"^   - \[x\] \*\*([a-z0-9-]+)\*\*", section, re.M) == prepared
    assert tuple(prepared) == PREPARED


def test_git_keeps_every_file_the_release_reads():
    """publish.sh release reads docs/releases/<version>.md and tests/data/state/<version>/ from the
    merged pull request: no ignore rule may match them."""
    if not shutil.which("git"):
        pytest.skip("needs git")
    if not os.path.exists(os.path.join(ROOT, ".git")):  # check-ignore answers only in a repository
        pytest.skip("not a git work tree")
    for path in ("docs/releases/9.9.9.md", "tests/data/state/9.9.9/settings.json"):
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT)
        assert r.returncode == 1, f"git ignores {path}"


def test_the_field_test_templates_environments_are_the_scripts():
    template = _read(".github", "ISSUE_TEMPLATE", "field-test.yml")
    assert re.findall(r"^        - label: (.+)$", template, re.M) == list(ft.environments())
