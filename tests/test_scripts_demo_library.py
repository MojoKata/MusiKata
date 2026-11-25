"""The demo library (scripts/demo_library.py; A6.7): the mockups' artists and albums, every kind of
R2.2, and the faults Needs attention, R3 and R12 show, planned as data and written as real files.

Why: tests, the tour and the screenshots never use real music, so the demo library is what every
view and every reader of tags is shown on. A plan that lost a fault, a kind or a shape of folder
would leave a screen with nothing to show and a reader untested on what other programs write."""

import ast
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402


def _mockup_albums():
    with open(os.path.join(ROOT, "docs", "mockups", "src", "render.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "ALBUMS"
    )
    return ast.literal_eval(node.value)


def test_its_albums_are_the_mockups():
    mine = [(a, b, y, g, s, n) for a, b, y, g, s, n, *_ in demo.ALBUMS]
    assert mine == [tuple(row) for row in _mockup_albums()]


def test_the_plan_holds_every_kind_and_the_faults_needs_attention_shows():
    lib = demo.plan()
    assert {s.kind for s in lib.songs} == set(demo.KINDS)
    assert len({s.path for s in lib.songs}) == len(lib.songs)
    tide = [s.tags for s in lib.songs if s.tags and s.tags.get("album") == "Tide Tables"]
    assert {g for t in tide for g in t["genre"]} == {"Electronic", "electronic", "Electronica"}
    assert any(t["year"] is None for t in tide) and any(t["artist"] == "lumen drift" for t in tide)
    assert [s.path for s in lib.songs if s.tags is None and s.path.startswith("_Incoming/")]
    assert any(size < 500 for _, size in lib.covers.values())  # Needs attention: a small cover
    kindling = "Mara Okafor/Kindling"
    assert kindling not in lib.covers and not any(
        s.cover for s in lib.songs if s.path.startswith(kindling)
    )
    entries = [e for e in lib.playlists["Playlists/Road Trip.m3u8"] if not e.startswith("#")]
    planned = {s.path for s in lib.songs}
    assert [e for e in entries if e.removeprefix("../") not in planned] == [
        "../Lumen Drift/Tide Tables/10 - Slack Tide.flac"
    ]


def test_the_folders_have_every_shape_of_folder_cover():
    """R5.8: artists with one, two, three and five albums, and albums a level further down."""
    folders = {os.path.dirname(s.path) for s in demo.plan().songs}

    def albums_under(top):
        return {f for f in folders if f.startswith(top + "/")}

    assert len(albums_under("Kestrel Union")) == 1
    assert len(albums_under("The Paper Lanterns")) == 2
    assert len(albums_under("Mara Okafor")) == 3
    assert len(albums_under("Soundtracks")) == 5
    assert len(albums_under("Lumen Drift/Remixes")) == 2


def test_more_fills_the_library_to_the_songs_asked_ten_to_an_album():
    lib = demo.plan()
    demo.more(lib, 400)
    assert len(lib.songs) == 400
    assert len({s.path for s in lib.songs}) == 400
    extra = [s for s in lib.songs if s.path.startswith("More/")]
    assert (
        max(
            sum(1 for s in extra if os.path.dirname(s.path) == d)
            for d in {os.path.dirname(s.path) for s in extra}
        )
        == 10
    )


@pytest.mark.slow
def test_each_kind_is_written_and_reads_back_with_its_tags(tmp_path):
    mutagen = pytest.importorskip("mutagen")
    for kind in demo.KINDS:
        song = demo.Song(
            f"x.{demo.KINDS[kind][0]}",
            kind,
            {
                "title": "Signal Fires",
                "artist": "Lumen Drift",
                "album": "Glass Harbor",
                "track": 4,
                "tracktotal": 10,
                "year": 2019,
                "genre": ["Electronic"],
                "rating": 5,
            },
            cover=(11, 64),
        )
        path = str(tmp_path / song.path)
        demo.encode(path, kind, 0.2, 440)
        demo.tag(path, song)
        if kind == "wav":
            import mutagen.wave as reader

            f = reader.WAVE(path)
        elif kind == "aiff":
            import mutagen.aiff as reader

            f = reader.AIFF(path)
        else:
            f = mutagen.File(path)
        assert f is not None and 0.15 < f.info.length < 0.3, kind
        text = str(f.tags)
        assert "Signal Fires" in text and "Lumen Drift" in text, kind
