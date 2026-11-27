"""Needs attention's dismissals where they are kept (src/musikata_core/rootfiles.py; R2.8, A2.8,
A2.10): the root's `ignored.json` read in whatever shape another computer, a person or a sync left
it, merged entry by entry and written again, and kept in the index's `ignored`.

Why: ignored.json is data from outside (testing.md, "Shapes": `rootfiles`), written by any
computer sharing the root; an entry dismissed on one computer must never be lost to another's
write, and a broken file must never be written over."""

import json
import os

import jsonschema
import pytest
from hypothesis import given
from hypothesis import strategies as st

from musikata_core import db, rootfiles
from musikata_core.rootfiles import Dismissal, IgnoredError

SCHEMA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "musikata_core", "schemas",
    "ignored.v1.schema.json",
)  # fmt: skip
H1, H2 = "1" * 64, "2" * 64
T1, T2, T3 = "2026-11-20T09:15:00Z", "2026-11-21T10:00:00Z", "2026-11-22T11:00:00Z"
EXAMPLE = {  # A2.10's
    "format": 1,
    "entries": [
        {"kind": "cover-small", "about": "Lumen Drift/Glass Harbor", "changed": T1},
        {"kind": "tags-from-path", "about": "_Incoming/track07.mp3",
         "hash": "0c4e6b1d3f5a7c9e2b4d6f8a1c3e5b7d9f0a2c4e6b8d1f3a3f6a9c1e5b7d2f8a",
         "modified": 1795600000.0, "changed": T2},
    ],
}  # fmt: skip


def valid(doc):
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))


def parse(doc):
    return rootfiles.parse_ignored(json.dumps(doc))


# ---------- the file, as plain data ----------


def test_a2_10s_example_reads_as_written_and_writes_back_the_same():
    got = parse(EXAMPLE)
    assert got.entries == (
        Dismissal("cover-small", "Lumen Drift/Glass Harbor", None, None, T1),
        Dismissal("tags-from-path", "_Incoming/track07.mp3", EXAMPLE["entries"][1]["hash"],
                  1795600000.0, T2),
    )  # fmt: skip
    assert not got.problems and not got.newer and not got.broken
    assert rootfiles.ignored_document(got.entries, got) == EXAMPLE
    valid(rootfiles.ignored_document(got.entries, got))


def test_a_file_that_cant_be_used_whole_gives_no_dismissals_and_says_why():
    """Shapes: empty, cut short by a sync, not JSON, not an object, entries not a list."""
    for text in ("", '{"format": 1, "entries": [{"kind": "x"', "nope", "[]", "12",
                 '{"entries": {"a": 1}}'):  # fmt: skip
        got = rootfiles.parse_ignored(text)
        assert got.broken and got.entries == () and got.problems, text


def test_shapes_of_an_entrys_fields_each_read_for_what_can_be_used():
    """Shapes: kind missing, empty or not text; about missing or empty; a hash in upper case or
    not a hash (found by its path); modified as text (a number or not), a bool, NaN, negative or
    null; changed
    missing, without its zone, in another zone; an entry not an object."""
    got = parse({"format": 1, "entries": [
        {"kind": " unreadable ", "about": "a.mp3", "hash": H1.upper(), "modified": "12.5",
         "changed": "2026-11-20T10:15:00+01:00"},
        {"kind": "unreadable", "about": "b.mp3", "hash": "nope", "modified": 3,
         "changed": "2026-11-20T09:15:00"},
        {"kind": "names-artist", "about": "Lumen Drift", "modified": None},
        {"kind": "unreadable", "about": "c.mp3", "modified": True, "changed": T1},
        {"kind": "unreadable", "about": "d.mp3", "modified": float("nan"), "changed": T1},
        {"kind": "unreadable", "about": "e.mp3", "modified": -1, "changed": T1},
        {"kind": "unreadable", "about": "e2.mp3", "modified": "yesterday", "changed": T1},
        {"kind": "", "about": "f.mp3", "changed": T1},
        {"kind": 3, "about": "g.mp3", "changed": T1},
        {"about": "h.mp3", "changed": T1},
        {"kind": "unreadable", "about": "", "changed": T1},
        {"kind": "unreadable", "changed": T1},
        "i.mp3",
    ]})  # fmt: skip
    assert got.entries == (
        Dismissal("unreadable", "a.mp3", H1, 12.5, T1),
        Dismissal("unreadable", "b.mp3", None, 3.0, rootfiles.UNKNOWN),
        Dismissal("names-artist", "Lumen Drift", None, None, rootfiles.UNKNOWN),
    )
    assert len(got.problems) == 13 and not got.broken


def test_an_entry_named_twice_is_one_the_newest_winning():
    got = parse({"format": 1, "entries": [
        {"kind": "unreadable", "about": "a.mp3", "modified": 1.0, "changed": T2},
        {"kind": "unreadable", "about": "a.mp3", "modified": 2.0, "changed": T1},
        {"kind": "cover-none", "about": "a.mp3", "changed": T1},
        {"kind": "cover-none", "about": "a.mp3", "changed": T3},
    ]})  # fmt: skip
    assert got.entries == (Dismissal("unreadable", "a.mp3", None, 1.0, T2),
                           Dismissal("cover-none", "a.mp3", None, None, T3))  # fmt: skip


def test_fields_in_another_order_or_unknown_are_kept_and_a_bom_is_read():
    doc = {"entries": [{"changed": T1, "why": "live recording", "about": "a.mp3",
                        "kind": "album-in-one-file"}],
           "format": 1, "note": "from a newer MusiKata"}  # fmt: skip
    got = rootfiles.parse_ignored("﻿" + json.dumps(doc))
    assert got.entries == (Dismissal("album-in-one-file", "a.mp3", None, None, T1),)
    assert not got.problems
    written = rootfiles.ignored_document(got.entries, got)
    assert written["note"] == "from a newer MusiKata"
    assert written["entries"] == [{"why": "live recording", "kind": "album-in-one-file",
                                   "about": "a.mp3", "changed": T1}]  # fmt: skip
    valid(written)


def test_a_newer_format_is_read_and_flagged_and_a_format_of_another_type_read_as_1():
    assert parse({**EXAMPLE, "format": 2}).newer
    got = parse({**EXAMPLE, "format": "1"})
    assert not got.newer and got.entries and got.problems
    assert parse({"entries": EXAMPLE["entries"]}).entries  # format missing: read as 1
    assert parse({"format": 1}).entries == ()  # entries missing: none


@given(st.text(max_size=300))
def test_any_text_at_all_gives_dismissals_or_none_never_an_error(text):
    got = rootfiles.parse_ignored(text)
    assert all(d.kind and d.about for d in got.entries)


dismissals = st.lists(
    st.builds(Dismissal, st.sampled_from(["unreadable", "cover-none"]),
              st.sampled_from(["a.mp3", "b.mp3", "A"]), st.sampled_from([None, H1]),
              st.sampled_from([None, 1.0, 2.5]), st.sampled_from([T1, T2, T3])),
    max_size=4,
    unique_by=lambda d: (d.kind, d.about),  # a file names an entry once (parse)
)  # fmt: skip


@given(dismissals, dismissals)
def test_merging_keeps_each_entrys_newest_dismissal_whichever_file_it_came_from(kept, mine):
    """A2.8: entry by entry, the newest `changed` winning, a tie going to this computer's."""
    merged = {(d.kind, d.about): d for d in rootfiles.merge_ignored(kept, mine)}
    for key in {(d.kind, d.about) for d in kept + mine}:
        newest = max(d.changed for d in kept + mine if (d.kind, d.about) == key)
        assert merged[key].changed == newest
        own = [d for d in mine if (d.kind, d.about) == key and d.changed == newest]
        if own:
            assert merged[key] == own[-1]


@given(dismissals, dismissals)
def test_merged_in_any_order_two_computers_files_give_the_same_entries(a, b):
    def changed(ds):
        return {(d.kind, d.about): d.changed for d in ds}

    assert changed(rootfiles.merge_ignored(a, b)) == changed(rootfiles.merge_ignored(b, a))


# ---------- the file on disk ----------


def test_saving_reads_the_file_again_so_another_computers_dismissal_is_kept(tmp_path):
    """A2.8: two computers dismissing at once lose nothing: each reads the file again before
    writing, and the newest dismissal of an entry wins."""
    path = str(tmp_path / "ignored.json")
    assert rootfiles.read_ignored(path) is None  # no file
    rootfiles.save_ignored(path, [Dismissal("unreadable", "a.mp3", H1, 1.0, T1)])
    with open(path, encoding="utf-8") as f:  # meanwhile, another computer dismissed two
        doc = json.load(f)
    doc["entries"] = [
        {"kind": "cover-none", "about": "LD/GH", "modified": 5.0, "changed": T2},
        {"kind": "unreadable", "about": "a.mp3", "modified": 2.0, "changed": T3},
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    written = rootfiles.save_ignored(path, [Dismissal("names-genre", "Electronic", None, None, T2)])
    assert written == [Dismissal("cover-none", "LD/GH", None, 5.0, T2),
                       Dismissal("names-genre", "Electronic", None, None, T2),
                       Dismissal("unreadable", "a.mp3", None, 2.0, T3)]  # fmt: skip
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    valid(doc)
    assert rootfiles.parse_ignored(json.dumps(doc)).entries == tuple(written)
    assert not os.path.exists(path + ".tmp")


def test_a_newer_or_broken_file_isnt_written_over_and_says_why(tmp_path):
    """A2.10: a newer MusiKata's file is read, never written; one that can't be read (a sync
    bringing it) isn't written over: the dismissal fails, saying why."""
    path = str(tmp_path / "ignored.json")
    mine = [Dismissal("unreadable", "a.mp3", None, 1.0, T1)]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**EXAMPLE, "format": 2}, f)
    with pytest.raises(IgnoredError, match="newer MusiKata"):
        rootfiles.save_ignored(path, mine)
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"format": 1, "entries": [')
    with pytest.raises(IgnoredError, match="can't be read"):
        rootfiles.save_ignored(path, mine)
    with open(path, encoding="utf-8") as f:
        assert f.read() == '{"format": 1, "entries": ['
    os.remove(path)
    os.mkdir(path)  # a folder where the file goes: it can't be read, nor written
    with pytest.raises(IgnoredError):
        rootfiles.save_ignored(path, mine)


def test_a_file_that_cant_be_written_says_so(tmp_path):
    folder = tmp_path / "ro"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        if os.access(folder, os.W_OK):
            pytest.skip("runs as a user who can write anywhere")  # root in a container
        with pytest.raises(IgnoredError, match="couldn't be written"):
            rootfiles.save_ignored(str(folder / "ignored.json"),
                                   [Dismissal("unreadable", "a.mp3", None, 1.0, T1)])  # fmt: skip
    finally:
        folder.chmod(0o700)


# ---------- in the index ----------


def test_the_index_keeps_each_entrys_newest_dismissal(tmp_path):
    index = db.Index(str(tmp_path / "musikata.db"))
    try:
        first = [Dismissal("unreadable", "a.mp3", H1, 1.0, T2),
                 Dismissal("cover-none", "LD/GH", None, 5.0, T1)]  # fmt: skip
        assert index.write(lambda c: rootfiles.load_ignored(c, first)).result() == 2
        later = [Dismissal("unreadable", "a.mp3", H2, 3.0, T1),  # older: kept as it was
                 Dismissal("cover-none", "LD/GH", None, 6.0, T3)]  # fmt: skip
        assert index.write(lambda c: rootfiles.load_ignored(c, later)).result() == 1
        assert rootfiles.dismissals(index.read()) == [
            Dismissal("cover-none", "LD/GH", None, 6.0, T3),
            Dismissal("unreadable", "a.mp3", H1, 1.0, T2),
        ]
        assert rootfiles.ignored_of("/music") == os.path.join("/music", ".musikata",
                                                               "ignored.json")  # fmt: skip
    finally:
        index.close()
