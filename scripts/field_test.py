"""What a release's field test asks, as one list: the environments it runs in and each one's
checklist, from which `publish.sh field-test` makes the release's GitHub issues
(docs/process/release.md, 4). The checks are tier 3's (docs/process/testing.md): a person, the
draft's build, a real machine with its speakers, keyboard, file manager and screen reader.

    python3 scripts/field_test.py ENVIRONMENT      the environment's sub-issue body
    python3 scripts/field_test.py --environments   the environments, one a line

Nothing here touches the machine, so it can be read without starting a field test.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# The environments, each with its platform and the words that name it in testing.md's
# "Environments" table, on a row whose tier includes 3 (tests/test_publish.py holds the two
# together)
ENVIRONMENTS = [
    ("Linux Mint 22.3", "linux", "Linux Mint 22.3"),
    ("LMDE 7", "linux", "LMDE 7"),
    ("Ubuntu 26.04 LTS", "linux", "Ubuntu 26.04"),
    ("Windows 10 22H2", "windows", "Windows 10 22H2"),
    ("macOS on Apple silicon", "macos", "Apple silicon"),
    ("macOS on Intel", "macos", "Intel"),
]

# what differs by platform, put into the checks below
PLATFORM = {
    "linux": {
        "build": "the draft's `MusiKata-<version>-x86_64.AppImage`",
        "install": "The AppImage, started once, installs itself into the app menu, and MusiKata "
        "starts from there (R1.4).",
        "files": "the file manager",
        "controls": "the desktop's sound menu (MPRIS)",
        "reader": "Orca",
    },
    "windows": {
        "build": "the draft's `MusiKata-<version>-setup.exe`",
        "install": "The installer installs for this user without a UAC prompt, and MusiKata starts "
        "from the Start menu (R1.4).",
        "files": "File Explorer",
        "controls": "the media controls of the volume flyout",
        "reader": "Narrator",
    },
    "macos": {
        "build": "the draft's `.dmg` for this Mac's chip",
        "install": "MusiKata.app, copied from the `.dmg` to Applications, starts after "
        "**Open Anyway** in System Settings › Privacy & Security, once (R1.4).",
        "files": "Finder",
        "controls": "Control Center's Now Playing",
        "reader": "VoiceOver",
    },
}

# (id, check, the platforms it is asked on: all when None)
CHECKS = [
    ("install", "{install}", None),
    ("sessions", "MusiKata runs in an X11 session and in a Wayland session.", ("linux",)),
    (
        "scan",
        "A first scan of the demo library (`scripts/demo_library.py`) fills every view, and Needs "
        "attention lists what the library gets wrong (R2.3, R2.8).",
        None,
    ),
    (
        "tags",
        "Tags inferred from paths are saved, and Undo in the change history puts them back (R3, "
        "R4.9).",
        None,
    ),
    (
        "cover",
        "A cover set on an album shows in the views and is written into its files (R5).",
        None,
    ),
    (
        "playlist",
        "A playlist made by dragging songs in from {files} plays in that order (R8).",
        None,
    ),
    (
        "organize",
        "Organize files moves the demo library into its layout, and Undo puts every file back "
        "(R12, R4.9).",
        None,
    ),
    ("open-with", "Open with MusiKata from {files} plays the file at once (R1.7).", None),
    (
        "gapless",
        "An album plays gapless through the speakers: no gap or click between its songs (R7.6).",
        None,
    ),
    (
        "equalizer",
        "The equalizer's presets change the sound as they are chosen, and turning it off "
        "brings the sound back as it was (R19).",
        None,
    ),
    (
        "media-keys",
        "The keyboard's media keys and {controls} play, pause and skip, and show the song (R7.8).",
        None,
    ),
    (
        "visuals",
        "The waveform and the 3D analyzer move in step with the sound (R11.1, R11.3).",
        None,
    ),
    (
        "mini-player",
        "The mini player moves, resizes and stays on top of other windows (R15; on "
        "Wayland, staying on top is the compositor's to allow, R15.2).",
        None,
    ),
    ("screen-reader", "{reader} reads every view's controls by name (R18.1).", None),
    (
        "drive",
        "With the music root on a USB drive: unplugging it and plugging it back keeps the "
        "library, and nothing is removed without asking (R2.10).",
        None,
    ),
    (
        "update",
        "From the previous release (not for the first): **Check for updates…** offers this "
        "one, installs it, and the library is as it was (R1.9).",
        None,
    ),
    (
        "uninstall",
        "Uninstalling leaves the music root and its `.musikata` folder as they were.",
        ("windows",),
    ),
]


def environments() -> dict:
    """{environment: its platform}, in the order the field test lists them."""
    return {name: platform for name, platform, _ in ENVIRONMENTS}


def checklist(environment: str) -> list:
    """[(id, check)] for the environment: what its sub-issue's boxes say."""
    platform = environments()[environment]
    words = PLATFORM[platform]
    return [
        (cid, text.format(**words))
        for cid, text, only in CHECKS
        if only is None or platform in only
    ]


def issue_body(environment: str) -> str:
    envs = environments()
    if environment not in envs:
        sys.exit(f"no environment {environment!r}; the field test's are: {', '.join(envs)}")
    build = PLATFORM[envs[environment]]["build"]
    return (
        f"The field test on **{environment}**, with {build}, on a real machine with a logged-in "
        "desktop (docs/process/release.md, 4).\n\n"
        "Tick each box that works. A box that doesn't is a bug: open it with the `bug` label "
        "and link it from its box, which is ticked once a later build, after the fix, works. A "
        "box that can't be tried here is left unticked with a comment saying why, and the owner "
        "defers it or not.\n\n"
        + "".join(f"- [ ] **{cid}** {text}\n" for cid, text in checklist(environment))
    )


def main(argv: list) -> int:
    if argv == ["--environments"]:
        print("\n".join(environments()))
        return 0
    if len(argv) == 1:
        sys.stdout.write(issue_body(argv[0]))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
