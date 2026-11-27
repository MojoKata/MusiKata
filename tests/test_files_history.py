"""The change history and Undo (src/musikata_core/history.py; R4.9, R4.9.1, A3.5, A2.1, A2.10):
every save one entry in the root's `.musikata/history/`, written once by the batch every save goes
through; Undo another save of the old values, itself an entry, so it can be redone; a file changed
since reported with what undoing it would lose before it is overwritten; other computers' entries
read into the index; entries past their age removed, with the old covers no entry names.

Why: the history is the user's way back from a save that went wrong, so a save that isn't kept,
an undo that puts back the wrong value, or one that silently overwrites a change made since, loses
their tags for good. The entries are data from outside (testing.md, "Shapes": `history`): another
computer or version writes them and a sync can cut them short, so each shape is read here."""

import json
import logging
import os
import shutil
import stat
import sys
from datetime import UTC, datetime, timedelta

import jsonschema
import pytest
from fakes import FakeClock, fill, wav
from hypothesis import given
from hypothesis import strategies as st

from musikata_core import art, db, history, ratings, rootfiles, scanner, tags
from musikata_core.history import Broken, Current, Entry, FileChange, Recording
from musikata_core.tags import AudioInfo, Batch, Job, Picture, Tags, Written

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import demo_library as demo  # noqa: E402

SCHEMA = os.path.join(ROOT, "src", "musikata_core", "schemas", "history-entry.v1.schema.json")
H1, H2, H3 = "1" * 64, "2" * 64, "3" * 64
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
OTHER = "6f1c0a5e-2b7d-4c1e-9a43-0f2d8e5b7c11"
WHEN = datetime(2026, 11, 25, 20, 45, 12, 345000, tzinfo=UTC)
NAME = f"20261125T204512345Z-{ME}.json"
COVER = demo.cover_jpeg(11, 32)
INFO = AudioInfo("flac", 1.0, 900, 44100, 2)


def valid(doc):
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))


def entry_doc(**over):
    doc = {
        "format": 1,
        "time": "2026-11-25T20:45:12Z",
        "computer": ME,
        "action": "edit-tags",
        "description": "Year and Genre on 1 song",
        "files": [
            {"path": "LD/GH/04.flac", "hash": H1,
             "fields": {"year": None, "genre": ["Electronica"]},
             "new": {"year": 2019, "genre": ["Electronic"]}}
        ],
    }  # fmt: skip
    doc.update(over)
    return doc


def parse(doc, name=NAME):
    return history.parse(name, doc if isinstance(doc, str) else json.dumps(doc))


def write_entry(folder, name, doc):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        f.write(doc if isinstance(doc, str) else json.dumps(doc))


# ---------- names, values and the file's shape ----------


def test_an_entry_is_named_by_its_time_to_the_millisecond_and_its_computer():
    """A3.5: named by its time and the computer that saved it, so computers never collide."""
    assert history.name_for(WHEN, ME) == NAME
    assert history.time_of_name(NAME) == WHEN
    assert history.time_of_name(f"x-{ME}.json") is None
    assert history.time_of_name(f"20261399T204512345Z-{ME}.json") is None  # a 13th month
    assert history.time_of_name(f"{NAME} (conflicted copy)") is None


def test_a_files_values_are_kept_as_plain_json_and_compared_as_the_file_holds_them():
    t = Tags(title="Neap Tide", year=2003, date="2003-05-01", genres=("Ambient",), rating=None)
    assert history.value_of(t, "year") == "2003-05-01"
    assert history.value_of(Tags(year=2022), "year") == 2022
    assert history.value_of(t, "genres") == ["Ambient"]
    assert history.value_of(t, "rating") == 0
    assert history.value_of(t, "compilation") is False
    assert history.same("year", 2003, "2003") and history.same("title", " A ", "A")
    assert not history.same("year", 2003, 2004)
    assert not history.same("track", "x", 4)  # a value no field holds is never the same


def test_what_the_batch_records_is_valid_under_the_schema_with_a2_10s_names(tmp_path):
    """A2.10: the entry is held to history-entry.v1.schema.json, R4.1's names ("genre")."""
    change = FileChange("LD/GH/04.flac", H1, {"year": None, "genres": ["Electronica"]},
                        {"year": 2019, "genres": ["Electronic"]}, True, None, H2)  # fmt: skip
    e = Entry(NAME, WHEN, ME, "edit-tags", "Year and Genre", (change,), undoes=None)
    doc = history.document(e)
    valid(doc)
    assert doc["files"][0]["fields"] == {"year": None, "genre": ["Electronica"]}
    assert doc["files"][0]["cover"] is None and doc["files"][0]["new_cover"] == H2
    undo = Entry(NAME, WHEN, ME, "undo", "Undo: Year", (change,), undoes=NAME)
    valid(history.document(undo))
    assert history.parse(NAME, json.dumps(doc)).files == (change,)


def test_a2_10s_example_and_an_older_entry_without_new_values_or_a_hash_are_read():
    found = parse(entry_doc())
    assert isinstance(found, Entry) and found.problems == ()
    assert found.time == datetime(2026, 11, 25, 20, 45, 12, tzinfo=UTC)
    (f,) = found.files
    assert (f.path, f.hash, f.old, f.new) == (
        "LD/GH/04.flac", H1, {"year": None, "genres": ["Electronica"]},
        {"year": 2019, "genres": ["Electronic"]},
    )  # fmt: skip
    older = parse(entry_doc(files=[{"path": "a.mp3", "fields": {"title": "Old"}}]))
    assert older.files == (FileChange("a.mp3", None, {"title": "Old"}),)


BROKEN = [
    ("", "isn't JSON"),
    ('{"format": 1, "time": "2026-11-25T20:45:12Z", "files": [{"pa', "isn't JSON"),  # a sync
    ("[1, 2]", "isn't a JSON object"),
    (json.dumps(entry_doc(format=2)), "newer MusiKata"),
    (json.dumps(entry_doc(files="LD/GH/04.flac")), "files isn't a list"),
    (json.dumps(entry_doc(files=[])), "names no file"),
    (json.dumps(entry_doc(files=[{"path": "/etc/passwd", "fields": {"title": "x"}}])), "no file"),
    (json.dumps(entry_doc(files=[{"path": "a.mp3", "fields": {}}])), "names no file"),
]


@pytest.mark.parametrize(("text", "why"), BROKEN)
def test_an_entry_cut_short_not_json_of_the_wrong_shape_or_newer_is_broken(text, why):
    found = history.parse(NAME, text)
    assert isinstance(found, Broken) and why in found.why


def test_an_entry_not_named_as_one_or_with_no_time_anywhere_is_broken():
    assert isinstance(parse(entry_doc(), "notes.json"), Broken)
    no_time = history.parse("x.json", json.dumps(entry_doc(time="soon")))
    assert isinstance(no_time, Broken)


def test_shapes_of_an_entrys_fields_each_read_for_what_can_be_used(caplog):
    """testing.md's `history` shapes: what can't be used is left out and logged, the rest kept."""
    doc = entry_doc(
        format="1",
        time="2026-11-25 20:45:12",  # no zone: the name's time
        computer=None,
        action=7,
        description=["no"],
        undoes="last week",
        extra={"unknown": True},
        files=[
            "LD/GH/01.flac",  # not an object
            {"path": "../outside.mp3", "fields": {"title": "x"}},
            {"path": "C:/Music/a.mp3", "fields": {"title": "x"}},
            {"path": "a\\b.mp3", "fields": {"title": "x"}},
            {"path": "LD/./04.flac", "fields": {"title": "x"}},
            {"path": "LD/GH/04.flac", "hash": H1.upper(),
             "fields": {"year": None, "lyrics": "la", "track": "four", "genre": "Ambient",
                        "rating": 9, "compilation": "yes", "title": None},
             "new": {"year": "2019", "title": "T", "album": "not in fields"},
             "cover": "not a hash", "new_cover": H2, "unknown": 1},
            {"path": "LD/GH/04.flac", "fields": {"title": "twice"}},
            {"path": "LD/GH/05.flac", "hash": "short", "fields": "Old",
             "cover": H2.upper(), "new_cover": "nope"},
            {"path": "LD/GH/06.flac", "fields": {"title": "T"}, "new": ["T"]},
        ],
    )  # fmt: skip
    found = parse(doc)
    assert isinstance(found, Entry)
    assert found.time == WHEN and found.computer == ME and found.action == "edit-tags"
    assert (found.description, found.undoes) == ("", None)
    a, b, c = found.files
    assert (a.path, a.hash, a.old, a.new, a.cover) == (
        "LD/GH/04.flac", H1, {"year": None, "title": None}, {"year": "2019", "title": "T"}, False
    )  # fmt: skip
    assert (b.path, b.hash, b.old, b.cover, b.old_cover, b.new_cover) == (
        "LD/GH/05.flac", None, {}, True, H2, None,
    )  # fmt: skip
    assert (c.path, c.old, c.new) == ("LD/GH/06.flac", {"title": "T"}, {})
    said = "\n".join(found.problems)
    for problem in ("format isn't a number", "time isn't a UTC time", "computer isn't an id",
                    "action isn't text", "description isn't text", "undoes isn't",
                    "a file isn't an object", "../outside.mp3", "C:/Music", "LD/./04",
                    "'lyrics' isn't a field", "track isn't a value", "genre isn't a value",
                    "rating isn't a value", "compilation isn't a value", "named twice",
                    "hash isn't an audio hash", "cover isn't a cover's hash",
                    "new_cover isn't", "fields isn't a group", "new isn't a group"):  # fmt: skip
        assert problem in said, problem


def test_a_bom_and_fields_in_another_order_are_read():
    text = "\ufeff" + json.dumps(dict(reversed(list(entry_doc().items()))))
    assert isinstance(history.parse(NAME, text), Entry)


@given(st.text())
def test_any_text_at_all_is_read_or_broken_never_an_error(text):
    assert isinstance(history.parse(NAME, text), Entry | Broken)


JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda c: st.lists(c) | st.dictionaries(st.text(), c),
    max_leaves=20,
)


@given(JSON)
def test_any_shape_of_json_is_read_or_broken_never_an_error(value):
    doc = entry_doc(files=[{"path": "a.mp3", "fields": value, "new": value, "cover": value}])
    assert isinstance(parse(doc), Entry | Broken)
    assert isinstance(parse(value), Entry | Broken)


# ---------- recording a save: with what safe.save gives, and no file ----------


def written(path, before, after, changed, cover_before=None, cover_after=None):
    return Written(path, after, INFO, H1, 100, 1, before, changed, cover_before, cover_after)


def test_a_save_is_one_entry_written_once_by_its_batch(tmp_path, caplog):
    """R4.9: every save is one entry, holding each file's old values; files unchanged are none."""
    root = str(tmp_path / "Music")
    clock = FakeClock(WHEN)
    rec = Recording(root, lambda: ME, clock)
    jobs = [Job(os.path.join(root, "LD", f"{n}.flac"), {"genres": ["Ambient"]}) for n in (1, 2, 3)]

    def write(job):
        if job.path.endswith("3.flac"):
            return written(job.path, Tags(genres=("Ambient",)), Tags(genres=("Ambient",)), ())
        return written(job.path, Tags(genres=("Electronica",), year=2019),
                       Tags(genres=("Ambient",), year=2019), ("genres",))  # fmt: skip

    out = Batch(jobs, write, record=rec, description="Genre on 3 songs").run()
    assert out.entry == NAME
    folder = history.folder_of(root)
    assert history.names(folder) == [NAME]
    with open(os.path.join(folder, NAME), encoding="utf-8") as f:
        doc = json.load(f)
    valid(doc)
    assert doc["description"] == "Genre on 3 songs" and doc["action"] == "edit-tags"
    assert [f["path"] for f in doc["files"]] == ["LD/1.flac", "LD/2.flac"]
    assert doc["files"][0] == {
        "path": "LD/1.flac", "hash": H1, "fields": {"genre": ["Electronica"]},
        "new": {"genre": ["Ambient"]},
    }  # fmt: skip
    assert not [n for n in os.listdir(folder) if n.endswith(".tmp")]


def test_a_save_that_changed_nothing_or_without_a_computer_id_keeps_no_entry(tmp_path, caplog):
    root = str(tmp_path)
    rec = Recording(root, lambda: ME, FakeClock())
    assert rec.done("edit-tags", "") is None  # no file written
    rec = Recording(root, lambda: None, FakeClock())
    rec.saved(written(str(tmp_path / "a.flac"), Tags(), Tags(title="A"), ("title",)))
    with caplog.at_level(logging.WARNING):
        assert rec.done("edit-tags", "") is None
    assert "no id" in caplog.text
    rec = Recording(root, lambda: ME, FakeClock())
    rec.saved(written("/elsewhere/a.flac", Tags(), Tags(title="A"), ("title",)))  # not the root's
    rec.saved(Written(str(tmp_path / "b.flac"), Tags(), INFO, H1, 1, 1))  # an older Written
    assert rec.files == []
    assert not os.path.exists(history.folder_of(root))


def test_an_entry_that_cant_be_written_leaves_the_save_as_it_is_and_says_so(tmp_path, caplog):
    root = tmp_path / "Music"
    (root / ".musikata").mkdir(parents=True)
    (root / ".musikata" / "history").write_text("a file where the folder should be")
    rec = Recording(str(root), lambda: ME, FakeClock())
    out = Batch([Job(str(root / "a.flac"), {"title": "A"})],
                lambda job: written(job.path, Tags(), Tags(title="A"), ("title",)),
                record=rec).run()  # fmt: skip
    assert len(out.saved) == 1 and out.entry is None
    assert "couldn't keep the save in the change history" in caplog.text


def test_a_recorder_that_fails_is_logged_and_never_fails_the_save(caplog):
    class Failing:
        def saved(self, w):
            raise RuntimeError("a bug")

        def done(self, action, description):
            raise RuntimeError("another")

    out = Batch([Job("a.flac", {})], lambda job: job.path, record=Failing()).run()
    assert out.saved == ["a.flac"] and out.entry is None
    assert caplog.text.count("keeping the save in the change history failed") == 2


def test_two_saves_in_one_millisecond_are_two_entries(tmp_path):
    root = str(tmp_path)
    clock = FakeClock(WHEN)
    made = []
    for title in ("A", "B"):
        rec = Recording(root, lambda: ME, clock)
        rec.saved(written(str(tmp_path / "a.flac"), Tags(), Tags(title=title), ("title",)))
        made.append(rec.done("edit-tags", title))
    assert made == [NAME, f"20261125T204512346Z-{ME}.json"]


def test_an_old_cover_is_kept_once_by_hash_however_many_entries_name_it(tmp_path, monkeypatch):
    root = str(tmp_path)
    old, new = Picture(3, "image/jpeg", COVER), Picture(3, "image/png", b"\x89PNG\r\n\x1a\nnew")
    rec = Recording(root, lambda: ME, FakeClock())
    for n in (1, 2):
        rec.saved(written(str(tmp_path / f"{n}.flac"), Tags(has_cover=True), Tags(has_cover=True),
                          ("cover",), old, new))  # fmt: skip
    rec.saved(written(str(tmp_path / "3.flac"), Tags(), Tags(has_cover=True), ("cover",), None,
                      new))  # fmt: skip
    rec.saved(written(str(tmp_path / "4.flac"), Tags(has_cover=True), Tags(), ("cover",), old))
    folder = history.folder_of(root)
    digest = history.image_hash(COVER)
    assert os.listdir(os.path.join(folder, "images")) == [digest]
    assert [(f.cover, f.old_cover, f.new_cover) for f in rec.files] == [
        (True, digest, history.image_hash(new.data)),
        (True, digest, history.image_hash(new.data)),
        (True, None, history.image_hash(new.data)),
        (True, digest, None),
    ]
    assert history.load_image(folder, digest) == COVER
    # one that can't be kept is still named, and the log says so
    monkeypatch.setattr(history, "keep_image", lambda *a: (_ for _ in ()).throw(OSError("full")))
    rec.saved(written(str(tmp_path / "5.flac"), Tags(has_cover=True), Tags(), ("cover",), old))
    assert rec.files[-1].old_cover == digest


def test_a_kept_cover_damaged_or_gone_isnt_used(tmp_path, caplog):
    folder = str(tmp_path)
    digest = history.keep_image(folder, COVER)
    with open(history.image_path(folder, digest), "wb") as f:
        f.write(b"something else")
    assert history.load_image(folder, digest) is None
    assert history.load_image(folder, H3) is None


# ---------- the index: change and change_file (A2.1) ----------


@pytest.fixture
def index(tmp_path):
    i = db.Index(str(tmp_path / "musikata.db"))
    yield i
    i.close()


def make_entry(name, files=(("a.flac", ("title",)),), action="edit-tags", undoes=None, cover=None):
    changes = tuple(
        FileChange(p, H1, {f: None for f in fs if f != "cover"}, {}, "cover" in fs, cover)
        for p, fs in files
    )
    return Entry(name, history.time_of_name(name), name[20:-5], action, "", changes, undoes)


def n(ms, computer=ME):
    return f"20261125T2045{ms:05d}Z-{computer}.json"


def test_the_index_lists_the_folders_entries_newest_first_with_their_files(index):
    a = make_entry(n(1000), (("LD/1.flac", ("title", "genres")), ("LD/2.flac", ("cover",))),
                   cover=H2)  # fmt: skip
    b = make_entry(n(2000, OTHER))
    assert index.write(lambda c: history.sync(c, [a.name, b.name], [a, b])).result() == 2
    c = index.read()
    rows = history.rows(c, 10, 1)
    assert [r.name for r in rows] == [b.name, a.name]
    assert rows[1].files == (("LD/1.flac", ("title", "genres")),) and rows[1].file_count == 2
    assert history.rows(c, 10, 1, whole={a.name})[1].files[1] == ("LD/2.flac", ("cover",))
    assert rows[0].computer == OTHER
    assert history.covers(c) == {H2}
    # read again: nothing new; one gone from the folder goes from the index
    assert index.write(lambda c: history.sync(c, [a.name, b.name], [a])).result() == 0
    assert index.write(lambda c: history.sync(c, [b.name], [])).result() == 1
    assert history.known(index.read()) == {b.name}
    assert index.read().execute("SELECT COUNT(*) FROM change_file").fetchone()[0] == 1


def test_an_undo_undoes_its_entry_until_it_is_undone_itself_and_ctrl_z_goes_back(index):
    """R4.9: Ctrl+Z puts back the most recent entry; an undo is an entry, so it can be redone."""
    a, b = make_entry(n(1000)), make_entry(n(2000))
    u1 = make_entry(n(3000), action="undo", undoes=b.name)
    write = lambda *es: index.write(lambda c: history.sync(c, [e.name for e in es], es)).result()  # noqa: E731
    write(a)
    assert history.last(index.read()) == a.name
    write(a, b)
    assert history.last(index.read()) == b.name
    write(a, b, u1)
    assert history.undone(index.read()) == {b.name}
    assert history.last(index.read()) == a.name  # Ctrl+Z again goes further back
    u2 = make_entry(n(4000), action="undo", undoes=u1.name)  # the undo undone: a redo
    write(a, b, u1, u2)
    assert history.undone(index.read()) == {u1.name}
    assert history.last(index.read()) == b.name
    assert history.in_effect_undone({"u3": "u2", "u2": "u1", "u1": "a"}) == {"u2", "a"}


def test_nothing_to_undo_says_none(index):
    assert history.last(index.read()) is None


def test_other_computers_entries_are_read_in_and_a_broken_one_read_again_once_whole(
    tmp_path, index, caplog
):
    """R4.9: a save made on one computer can be undone on another; a sync in progress skipped."""
    folder = str(tmp_path / "history")
    write_entry(folder, n(1000, OTHER), entry_doc(computer=OTHER))
    write_entry(folder, n(2000), '{"format": 1, "time": "2026-11-25T20:45:12Z", "fi')
    write_entry(folder, "notes.txt", "a person's notes")
    write_entry(folder, n(3000) + ".tmp", "{")
    with caplog.at_level(logging.WARNING):
        assert history.refresh(index, folder) == 1
    assert "isn't JSON" in caplog.text
    assert history.known(index.read()) == {n(1000, OTHER)}
    write_entry(folder, n(2000), entry_doc())  # the sync finished
    assert history.refresh(index, folder) == 1
    assert [r.computer for r in history.rows(index.read(), 10, 3)] == [ME, OTHER]


def test_an_unreadable_or_missing_folder_lists_nothing(tmp_path, caplog, monkeypatch):
    assert history.names(str(tmp_path / "none")) == []
    monkeypatch.setattr(os, "scandir", lambda p: (_ for _ in ()).throw(PermissionError("no")))
    assert history.names(str(tmp_path)) == [] and "couldn't list" in caplog.text


def test_an_entry_that_cant_be_read_is_broken_and_logged(tmp_path, caplog):
    folder = tmp_path / "history"
    (folder / n(1000)).mkdir(parents=True)  # a folder named as an entry: can't be opened as one
    found = history.read(str(folder), n(1000))
    assert isinstance(found, Broken) and "couldn't be read" in found.why


def test_computers_are_named_as_their_play_files_name_them(tmp_path):
    """R4.9: each entry shows the computer that saved it, by name where it has one (A2.8)."""
    musikata = tmp_path / ".musikata"
    (musikata / OTHER).mkdir(parents=True)
    (musikata / OTHER / "plays.json").write_text(
        json.dumps({"format": 1, "computer": {"id": OTHER, "name": "Studio-PC"}, "songs": []})
    )
    found = history.computer_names(str(musikata), [OTHER, ME, "../x", "a/b"])
    assert found == {OTHER: "Studio-PC"}


# ---------- age (R4.9, R13.3) ----------


def test_entries_past_their_age_are_removed_with_the_covers_no_entry_names(tmp_path, index):
    """R4.9: kept for 90 days, a setting (R13); A3.5: removed by whichever computer starts first,
    the old covers with them once no entry names them."""
    folder = str(tmp_path / "history")
    now = datetime(2026, 11, 25, 12, tzinfo=UTC)
    old = history.name_for(now - timedelta(days=91), OTHER)
    young = history.name_for(now - timedelta(days=89), ME)
    keep = history.keep_image(folder, COVER)
    lose = history.keep_image(folder, b"\x89PNG\r\n\x1a\nold")
    fresh = history.keep_image(folder, b"GIF89a being written")
    ancient = (now - timedelta(days=2)).timestamp()
    for digest in (keep, lose):
        os.utime(history.image_path(folder, digest), (ancient, ancient))
    os.utime(history.image_path(folder, fresh), (now.timestamp(), now.timestamp()))
    files = [{"path": "a.flac", "fields": {"title": None}, "cover": keep}]
    write_entry(folder, old, entry_doc(files=[{"path": "a.flac", "cover": lose}]))
    write_entry(folder, young, entry_doc(files=files))
    write_entry(folder, "x.json", "{}")  # not an entry's name: left alone
    started = history.start(index, folder, now, 90)
    assert started.expired == [old] and started.pruned == [lose] and started.changed == 1
    assert sorted(os.listdir(folder)) == sorted(["images", young, "x.json"])
    assert sorted(os.listdir(os.path.join(folder, "images"))) == sorted([keep, fresh])
    assert history.start(index, folder, now, 30).expired == [young]


def test_an_entry_or_cover_that_cant_be_removed_is_kept_and_logged(tmp_path, monkeypatch, caplog):
    folder = str(tmp_path)
    now = datetime(2026, 11, 25, tzinfo=UTC)
    write_entry(folder, history.name_for(now - timedelta(days=100), ME), entry_doc())
    digest = history.keep_image(folder, COVER)
    os.utime(history.image_path(folder, digest), (0, 0))

    def refuse(path):
        raise PermissionError("read-only")

    monkeypatch.setattr(os, "remove", refuse)
    assert history.expire(folder, now, 90) == []
    assert history.prune(folder, set(), now.timestamp()) == []
    assert "couldn't remove" in caplog.text
    gone = lambda path: (_ for _ in ()).throw(FileNotFoundError(path))  # noqa: E731
    monkeypatch.setattr(os, "remove", gone)  # another computer took it first
    assert history.expire(folder, now, 90) == []
    assert history.prune(str(tmp_path / "none"), set(), now.timestamp()) == []


# ---------- Undo: planning, with fakes ----------


def change(**over):
    base = {"path": "LD/04.flac", "hash": H1, "old": {"year": 2019, "title": "Old"},
            "new": {"year": 2020, "title": "New"}}  # fmt: skip
    base.update(over)
    return FileChange(**base)


@pytest.mark.parametrize(
    ("now", "lost"),
    [
        (Tags(year=2020, title="New"), []),  # as the entry wrote it
        (Tags(year=2019, title="Old"), []),  # already put back
        (Tags(year=2021, title="New"), [("year", 2021, 2019)]),  # changed since
        (Tags(year=2020, date="2020-05-01", title="New "), [("year", "2020-05-01", 2019)]),
        (Tags(title=None), [("year", None, 2019), ("title", None, "Old")]),
    ],
)
def test_what_undoing_would_lose_is_each_value_changed_since(now, lost):
    """R4.9.1: a file changed since (by MusiKata or anything else) shows what would be lost."""
    found = history.lost(change(), Current(now))
    assert [(x.field, x.now, x.back) for x in found] == lost


def test_without_the_value_written_any_value_but_the_old_one_would_be_lost():
    found = history.lost(change(new={}), Current(Tags(year=2020, title="Old")))
    assert [(x.field, x.now) for x in found] == [("year", 2020)]


def test_a_cover_changed_since_would_be_lost_too():
    c = change(old={}, new={}, cover=True, old_cover=H2, new_cover=H3)
    assert history.lost(c, Current(Tags(), H3)) == ()
    assert history.lost(c, Current(Tags(), H2)) == ()
    (x,) = history.lost(c, Current(Tags(), None))
    assert (x.field, x.now, x.back) == ("cover", None, H2)


def test_a_plan_finds_each_file_by_path_else_by_hash_and_says_why_it_cant(tmp_path):
    root = tmp_path
    (root / "LD").mkdir()
    (root / "LD" / "04.flac").write_bytes(b"")
    (root / "Moved.flac").write_bytes(b"")
    e = Entry(NAME, WHEN, ME, "edit-tags", "", (
        change(),
        change(path="LD/05.flac", hash=H2),  # moved, found by hash
        change(path="LD/06.flac", hash=H3),  # gone
        change(path="LD/07.flac", hash=None),  # gone, no hash to find it by
        change(path="Moved.flac", hash=None),  # can't be read
    ))  # fmt: skip

    def look(path, cover):
        if path.endswith("Moved.flac"):
            raise tags.TagReadError("not audio")
        return Current(Tags(year=2021, title="New") if "LD" in path else Tags())

    p = history.plan(
        e, str(root), lambda h: {H2: ["LD/gone.flac", "LD/04.flac"]}.get(h, []), look=look
    )
    assert [(f.path, f.why) for f in p.files] == [
        ("LD/04.flac", ""), ("LD/04.flac", ""), (None, "it isn't there any more"),
        (None, "it isn't there any more"), ("Moved.flac", "it can't be read: not audio"),
    ]  # fmt: skip
    assert [f.change.path for f in p.changed] == ["LD/04.flac", "LD/05.flac"]
    assert len(p.failed) == 3
    assert [f.change.path for f in history.plan(e, str(root), lambda h: [], {0}, look).files] == [
        "LD/04.flac"
    ]
    jobs = history.jobs(p, str(root), overwrite=False)
    assert jobs == []
    jobs = history.jobs(p, str(root), overwrite=True)
    assert [j.path for j in jobs] == [str(root / "LD" / "04.flac")] * 2
    assert jobs[0].changes == {"year": 2019, "title": "Old"}


def test_an_undo_is_described_by_what_it_undoes():
    e = Entry(NAME, WHEN, ME, "edit-tags", "Year on 4 songs", (change(), change(path="b")))
    assert history.description_of(e, 2) == "Undo: Year on 4 songs"
    assert history.description_of(e, 1) == "Undo: Year on 4 songs (1 of 2 files)"
    assert history.description_of(Entry(NAME, WHEN, ME, "undo", "", (change(),)), 1) == (
        "Undo: an undo"
    )


# ---------- Undo: real files, written through A3.4 ----------


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """Two tagged FLACs of other audio, each with a cover, and an MP3, made once: {kind: path}."""
    d = tmp_path_factory.mktemp("made")
    out = {}
    for kind, tone in (("flac", 440), ("mp3", 440), ("flac2", 660)):
        out[kind] = str(d / f"{kind}.{demo.KINDS[kind[:4]][0]}")
        demo.encode(out[kind], kind[:4], 0.2, tone)
        song = {"title": "Neap Tide", "genre": ["Electronica"], "year": 2022, "artist": "LD"}
        demo.tag(out[kind], demo.Song(out[kind], kind[:4], song, cover=(11, 32)))
    return out


@pytest.fixture
def library(made, tmp_path):
    """A root of three songs, its index and a clock: (root, index, clock, paths)."""
    root = tmp_path / "Music"
    (root / "LD").mkdir(parents=True)
    paths = []
    for name, kind in (("01.flac", "flac"), ("02.mp3", "mp3"), ("03.flac", "flac2")):
        paths.append(str(root / "LD" / name))
        shutil.copyfile(made[kind], paths[-1])
    i = db.Index(str(tmp_path / "musikata.db"))
    fill(i, [{"path": f"LD/{os.path.basename(p)}"} for p in paths])
    i.write(lambda c: c.executemany("UPDATE song SET audio_hash = ? WHERE path = ?", [
        (scanner.audio_hash(p, tags.read(p)[1].kind), f"LD/{os.path.basename(p)}") for p in paths
    ])).result()  # fmt: skip
    yield str(root), i, FakeClock(WHEN), paths
    i.close()


def save(root, clock, paths, changes, description="a save", computer=ME):
    rec = Recording(root, lambda: computer, clock)
    write = lambda job: tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)  # noqa: E731
    out = Batch([Job(p, changes) for p in paths], write, record=rec, description=description).run()
    clock.advance(seconds=1)
    return out


def undo(root, i, clock, name, overwrite=False, which=None):
    folder = history.folder_of(root)
    e = history.read(folder, name)
    p = history.plan(e, root, history.finder(i.read()), which)
    write = lambda job: tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)  # noqa: E731
    out = history.undo(p, root, overwrite, write, Recording(root, lambda: ME, clock, e.name))
    clock.advance(seconds=1)
    return p, out


def read(path):
    return tags.read(path)[0]


def test_a_save_undone_puts_back_each_files_old_values_and_redone_the_new_ones(library):
    """R4.9: every save one entry; Undo writes the old values through A3.4 as another entry, so
    it can be redone; the batch every later save goes through records it (A3.5)."""
    root, i, clock, paths = library
    out = save(root, clock, paths, {"year": 2023, "genres": ["Ambient"]}, "Year and Genre")
    assert out.entry is not None and len(out.saved) == 3
    folder = history.folder_of(root)
    with open(os.path.join(folder, out.entry), encoding="utf-8") as f:
        doc = json.load(f)
    valid(doc)
    assert doc["files"][0]["fields"] == {"year": 2022, "genre": ["Electronica"]}
    assert doc["files"][0]["new"] == {"year": 2023, "genre": ["Ambient"]}
    assert doc["files"][0]["hash"] == scanner.audio_hash(paths[0], "flac")
    p, undone = undo(root, i, clock, out.entry)
    assert p.changed == [] and undone.failed == [] and len(undone.saved) == 3
    assert all((read(x).year, read(x).genres) == (2022, ("Electronica",)) for x in paths)
    with open(os.path.join(folder, undone.entry), encoding="utf-8") as f:
        u = json.load(f)
    valid(u)
    assert (u["action"], u["undoes"], u["description"]) == ("undo", out.entry,
                                                           "Undo: Year and Genre")  # fmt: skip
    _, redone = undo(root, i, clock, undone.entry)  # the undo undone: a redo
    assert all((read(x).year, read(x).genres) == (2023, ("Ambient",)) for x in paths)
    assert len(history.names(folder)) == 3 and redone.entry is not None


def test_a_file_changed_since_is_reported_and_overwritten_only_when_the_user_says(library):
    """R4.9.1: undoing a file that has changed since asks first, and shows what would be lost;
    undone file by file, the others are left alone."""
    root, i, clock, paths = library
    out = save(root, clock, paths[:2], {"title": "Spring Tide"})
    tags.save(paths[1], {"title": "Spring Tide (edit)"}, audio_hash=scanner.audio_hash)  # since
    p, kept = undo(root, i, clock, out.entry, overwrite=False)
    (changed,) = p.changed
    assert changed.change.path == "LD/02.mp3"
    assert [(x.field, x.now, x.back) for x in changed.lost] == [
        ("title", "Spring Tide (edit)", "Neap Tide")
    ]
    assert read(paths[0]).title == "Neap Tide" and read(paths[1]).title == "Spring Tide (edit)"
    assert len(kept.saved) == 1
    p, overwritten = undo(root, i, clock, out.entry, overwrite=True, which={1})
    assert [f.change.path for f in p.files] == ["LD/02.mp3"]
    assert read(paths[1]).title == "Neap Tide"
    assert overwritten.entry is not None


def test_a_moved_file_is_undone_where_it_is_and_one_gone_or_read_only_is_listed(library):
    """R4.9: a file moved is found by its audio hash (A2.8); gone or read-only, listed with why,
    as a save's failures are (R4.7)."""
    root, i, clock, paths = library
    out = save(root, clock, paths, {"album": "Tide Tables"})
    moved = os.path.join(root, "Moved.flac")
    os.replace(paths[0], moved)
    i.write(lambda c: c.execute("UPDATE song SET path = 'Moved.flac' WHERE path = 'LD/01.flac'"))
    i.write(lambda c: None).result()
    os.chmod(paths[1], stat.S_IRUSR)
    os.remove(paths[2])
    _, undone = undo(root, i, clock, out.entry)
    assert read(moved).album is None
    assert sorted((os.path.basename(f.job.path), f.why[:20]) for f in undone.failed) == [
        ("02.mp3", "it is read-only: let"), ("03.flac", "it isn't there any mo"[:20]),
    ]  # fmt: skip
    with open(os.path.join(history.folder_of(root), undone.entry), encoding="utf-8") as f:
        assert [x["path"] for x in json.load(f)["files"]] == ["Moved.flac"]


def test_a_cover_set_or_removed_is_put_back_from_the_history(library):
    root, i, clock, paths = library
    before = tags.pictures(paths[0])
    new = Picture(3, "image/png", demo.cover_jpeg(99, 16))
    out = save(root, clock, paths[:1], {"cover": new})
    removed = save(root, clock, paths[2:], {"cover": None})
    assert [p.data for p in tags.pictures(paths[0])] == [new.data]
    undo(root, i, clock, out.entry)
    undo(root, i, clock, removed.entry)
    assert [p.data for p in tags.pictures(paths[0])] == [p.data for p in before]
    assert [p.data for p in tags.pictures(paths[2])] == [p.data for p in before]
    # a cover no longer kept fails that file, with why
    shutil.rmtree(os.path.join(history.folder_of(root), "images"))
    out = save(root, clock, paths[:1], {"cover": new})
    shutil.rmtree(os.path.join(history.folder_of(root), "images"))
    _, failed = undo(root, i, clock, out.entry)
    assert [f.why for f in failed.failed] == ["its old cover isn't in the change history any more"]


def test_a_rating_kept_beside_the_files_is_undone_where_it_is_kept(tmp_path):
    """R4.9 with R10.3: a WAV's rating, kept in the root's ratings.json, is one entry like any
    field; undoing it puts the old rating back there (and in the index), and R4.9.1 sees a
    rating changed since in ratings.json, not in the file."""
    root = tmp_path / "Music"
    (root / ".musikata").mkdir(parents=True)
    path = str(root / "a.wav")
    wav(path, 3, "Tidewater")
    i = db.Index(str(tmp_path / "musikata.db"))
    try:
        t, info = tags.read(path)
        size = os.stat(path)
        read_ = scanner.Read(scanner.Seen("a.wav", size.st_size, size.st_mtime_ns), t, info,
                             scanner.audio_hash(path, "wav"))  # fmt: skip
        i.write(lambda c: scanner.write_batch(c, [read_], {})).result()
        clock = FakeClock(WHEN)

        def write_file(job):
            return tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)

        w = ratings.Writing(str(root), i, write_file, True, clock)
        rec = Recording(str(root), lambda: ME, clock)
        out = Batch([Job(path, {"rating": 4})], w, record=rec, action="rate").run()
        entry = history.read(history.folder_of(str(root)), out.entry)
        assert (entry.files[0].old, entry.files[0].new) == ({"rating": 0}, {"rating": 4})
        look = history.looking(w.kept)
        assert look(path, False).tags.rating == 4 and look(path, False).tags.title == "Tidewater"
        clock.advance(seconds=1)
        w(Job(path, {"rating": 2}))  # rated again since
        p = history.plan(entry, str(root), history.finder(i.read()), look=look)
        assert [(x.field, x.now, x.back) for x in p.changed[0].lost] == [("rating", 2, 0)]
        undone = history.undo(p, str(root), True, w, Recording(str(root), lambda: ME, clock,
                                                                 entry.name))  # fmt: skip
        assert undone.failed == [] and w.kept(path) == 0
        assert i.read().execute("SELECT rating FROM song").fetchone() == (0,)
        assert ratings.read(ratings.file_of(str(root))).entries[0].stars == 0
        assert tags.read(path)[0].rating is None  # never in the file
        assert history.looking(lambda p: None)(path, False).tags.rating is None
    finally:
        i.close()


# ---------- album art (R5.3): other pictures removed, and cover.jpg ----------


class Trash:
    """The system's trash, as a folder: what it was given, by name."""

    def __init__(self, folder):
        self.folder, self.got = str(folder), []
        os.makedirs(self.folder, exist_ok=True)

    def __call__(self, path):
        self.got.append(os.path.basename(path))
        os.replace(path, os.path.join(self.folder, f"{len(self.got)}-{os.path.basename(path)}"))
        return True


def art_save(root, clock, jobs, trash, description="Album art: Neap"):
    rec = Recording(root, lambda: ME, clock)
    write = art.writer(
        lambda job: tags.save(job.path, job.changes, audio_hash=scanner.audio_hash), trash
    )
    out = Batch(jobs, write, record=rec, action="album-art", description=description).run()
    clock.advance(seconds=1)
    return out


def art_undo(root, i, clock, name, trash, overwrite=False):
    e = history.read(history.folder_of(root), name)
    p = history.plan(e, root, history.finder(i.read()))
    write = lambda job: tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)  # noqa: E731
    rec = Recording(root, lambda: ME, clock, e.name)
    out = history.undo(p, root, overwrite, write, rec, trash=trash)
    clock.advance(seconds=1)
    return p, out


def test_an_album_art_save_is_one_entry_and_undo_puts_back_the_covers_pictures_and_cover_jpg(
    library, tmp_path
):
    """R5.3 and R4.9: the cover embedded, the other pictures removed and cover.jpg written are one
    entry, valid under its schema; the old cover.jpg goes to the trash (Principle 5) and is kept
    in history/images; Undo puts every picture and the old cover.jpg back, and Redo the new."""
    root, i, clock, paths = library
    trash = Trash(tmp_path / "trash")
    back = Picture(4, "image/png", b"\x89PNG\r\n\x1a\nback", "Back")
    tags.save(paths[0], {"others": (back,)}, audio_hash=scanner.audio_hash)
    before = [(p.type, p.data) for p in tags.pictures(paths[0])]
    jpg = os.path.join(root, "LD", "cover.jpg")
    with open(jpg, "wb") as f:
        f.write(b"\xff\xd8old cover.jpg")
    new = Picture(3, "image/jpeg", demo.cover_jpeg(99, 16))
    jobs = [Job(paths[0], {"cover": new, "others": ()}), Job(jpg, {"image": new.data})]
    out = art_save(root, clock, jobs, trash)
    assert out.failed == [] and out.entry is not None and trash.got == ["cover.jpg"]
    assert [(p.type, p.data) for p in tags.pictures(paths[0])] == [(3, new.data)]
    with open(jpg, "rb") as f:
        assert f.read() == new.data
    with open(os.path.join(history.folder_of(root), out.entry), encoding="utf-8") as f:
        doc = json.load(f)
    valid(doc)
    song, image = doc["files"]
    assert song["pictures"] == [{"type": 4, "mime": "image/png", "desc": "Back",
                                 "image": history.image_hash(back.data)}]  # fmt: skip
    assert song["new_pictures"] == []
    assert image == {"path": "LD/cover.jpg", "image": history.image_hash(b"\xff\xd8old cover.jpg"),
                     "new_image": history.image_hash(new.data)}  # fmt: skip
    assert history.load_image(history.folder_of(root), image["image"]) == b"\xff\xd8old cover.jpg"
    entry = history.read(history.folder_of(root), out.entry)
    assert [f.fields() for f in entry.files] == [["cover", "others"], ["cover"]]
    p, undone = art_undo(root, i, clock, out.entry, trash)
    assert p.changed == [] and undone.failed == []
    assert sorted((p.type, p.data) for p in tags.pictures(paths[0])) == sorted(before)
    assert [p.desc for p in tags.pictures(paths[0]) if p.type == 4] == ["Back"]
    with open(jpg, "rb") as f:
        assert f.read() == b"\xff\xd8old cover.jpg"
    art_undo(root, i, clock, undone.entry, trash)  # redone
    with open(jpg, "rb") as f:
        assert f.read() == new.data
    assert [(p.type, p.data) for p in tags.pictures(paths[0])] == [(3, new.data)]


def test_a_cover_jpg_that_wasnt_there_goes_to_the_trash_when_undone_and_one_changed_since_asks(
    library, tmp_path
):
    """Undoing a cover.jpg written where there was none moves it to the trash; one changed since
    is R4.9.1's question, as a field is."""
    root, i, clock, paths = library
    trash = Trash(tmp_path / "trash")
    jpg = os.path.join(root, "LD", "cover.jpg")
    out = art_save(root, clock, [Job(jpg, {"image": b"\xff\xd8new"})], trash)
    assert trash.got == []
    p, undone = art_undo(root, i, clock, out.entry, trash)
    assert not os.path.exists(jpg) and trash.got == ["cover.jpg"] and undone.failed == []
    out = art_save(root, clock, [Job(jpg, {"image": b"\xff\xd8new"})], trash)
    with open(jpg, "wb") as f:
        f.write(b"\xff\xd8someone else's")
    p, kept = art_undo(root, i, clock, out.entry, trash)
    (changed,) = p.changed
    assert [(x.field, x.now, x.back) for x in changed.lost] == [
        ("cover", history.image_hash(b"\xff\xd8someone else's"), None)
    ]
    assert kept.saved == [] and os.path.exists(jpg)


def test_other_pictures_changed_since_would_be_lost():
    kept = history.KeptPicture(4, "image/png", "", H1)
    c = FileChange("a.flac", None, {}, {}, others=(kept,), new_others=())
    assert history.lost(c, Current(Tags(), None, ())) == ()
    assert history.lost(c, Current(Tags(), None, (H1,))) == ()
    (lost,) = history.lost(c, Current(Tags(), None, (H2,)))
    assert (lost.field, lost.now, lost.back) == ("others", (H2,), (H1,))


def test_shapes_of_pictures_and_images_in_an_entry_each_read_for_what_can_be_used(caplog):
    """testing.md's `history` shapes for R5.3's files: `pictures` not a list, a picture not an
    object, its type text or a bool, its image not a hash; `new_pictures` with what isn't a hash;
    `image` not a hash, `null` (there was none), in upper case; `new_image` missing."""
    doc = entry_doc(files=[
        {"path": "a.flac", "pictures": [{"type": 4, "mime": 5, "desc": None, "image": H1.upper()},
                                        {"type": None, "image": H2}],
         "new_pictures": [H2, "nope", 3]},
        {"path": "b.flac", "fields": {"title": "T"}, "pictures": "back"},
        {"path": "c.flac", "pictures": [{"type": "4", "image": H1}]},
        {"path": "d.flac", "pictures": [{"type": True, "image": H1}]},
        {"path": "e.flac", "pictures": [["not", "an", "object"]]},
        {"path": "f/cover.jpg", "image": H1.upper()},
        {"path": "g/cover.jpg", "image": None, "new_image": H2},
        {"path": "h/cover.jpg", "image": "not a hash"},
        {"path": "i/cover.jpg", "image": H1, "new_image": "nope"},
    ])  # fmt: skip
    found = parse(doc)
    a, b, f, g, i = found.files
    assert a.others == (history.KeptPicture(4, "", "", H1), history.KeptPicture(None, "", "", H2))
    assert a.new_others == (H2,) and a.fields() == ["others"] and a.kept() == [H1, H2]
    assert (b.path, b.others, b.old) == ("b.flac", None, {"title": "T"})
    assert (f.image, f.old_cover, f.new_cover, f.fields(), f.kept()) == (
        True,
        H1,
        None,
        ["cover"],
        [H1],
    )
    assert (g.old_cover, g.new_cover, g.kept()) == (None, H2, [])
    assert (i.path, i.old_cover, i.new_cover) == ("i/cover.jpg", H1, None)
    said = "\n".join(found.problems)
    for problem in ("b.flac: pictures isn't a list", "c.flac: a picture isn't",
                    "d.flac: a picture isn't", "e.flac: a picture isn't",
                    "h/cover.jpg: image isn't a cover's hash", "i/cover.jpg: new_image isn't",
                    "c.flac: no field it can put back"):  # fmt: skip
        assert problem in said, problem
    again = parse(history.document(found))
    assert again.files == found.files


def test_the_old_pictures_and_images_an_entry_keeps_are_never_pruned(tmp_path, index):
    folder = str(tmp_path / "history")
    now = datetime(2026, 11, 25, 12, tzinfo=UTC)
    picture = history.keep_image(folder, b"\x89PNG\r\n\x1a\nback")
    image = history.keep_image(folder, b"\xff\xd8old cover.jpg")
    ancient = (now - timedelta(days=2)).timestamp()
    for digest in (picture, image):
        os.utime(history.image_path(folder, digest), (ancient, ancient))
    files = [{"path": "a.flac", "pictures": [{"type": 4, "image": picture}], "new_pictures": []},
             {"path": "cover.jpg", "image": image, "new_image": None}]  # fmt: skip
    write_entry(folder, history.name_for(now, ME), entry_doc(files=files))
    started = history.start(index, folder, now, 90)
    assert started.pruned == [] and history.covers(index.read()) == {picture, image}


def test_an_image_file_that_cant_be_read_isnt_undone_and_says_why(tmp_path):
    root = str(tmp_path / "Music")
    os.makedirs(os.path.join(root, "cover.jpg"))  # a folder where the image was
    entry = Entry(NAME, WHEN, ME, "album-art", "", (FileChange("cover.jpg", None, {}, {}, False,
                  None, H1, image=True),))  # fmt: skip
    (f,) = history.plan(entry, root, lambda h: []).files
    assert f.why.startswith("it can't be read")


# ---------- the same song more than once (R2.12): files to the trash, plays moved ----------

PLAYED = "2026-11-25T20:41:00Z"


def test_a_move_to_the_trash_is_one_entry_with_the_rating_plays_and_files_it_moved(tmp_path):
    """R2.12, R2.11: the kept copy's rating (a file written), the plays it took (noted) and the
    copies moved to the trash (noted) are one entry, each file named once, valid under its
    schema and read back; the index lists the plays and the trash among its fields."""
    root = str(tmp_path / "Music")
    rec = Recording(root, lambda: ME, FakeClock(WHEN))
    took = history.Plays("_Incoming/Moonpull.m4a", H2, 6, PLAYED)
    rec.note(FileChange("LD/04.flac", H1, {}, plays_from=(took,)))
    rec.note(FileChange("_Incoming/Moonpull.m4a", H2, {}, trashed=True))
    jobs = [Job(os.path.join(root, "LD", "04.flac"), {"rating": 5})]

    def write(job):
        return written(job.path, Tags(rating=4), Tags(rating=5), ("rating",))

    out = Batch(jobs, write, record=rec, action="copies", description="Moonpull").run()
    with open(os.path.join(history.folder_of(root), out.entry), encoding="utf-8") as f:
        doc = json.load(f)
    valid(doc)
    assert doc["files"] == [
        {"path": "LD/04.flac", "hash": H1, "fields": {"rating": 4}, "new": {"rating": 5},
         "plays_from": [{"path": "_Incoming/Moonpull.m4a", "hash": H2, "count": 6,
                         "last": PLAYED}]},
        {"path": "_Incoming/Moonpull.m4a", "hash": H2, "fields": {}, "new": {}, "trashed": True},
    ]  # fmt: skip
    entry = parse(doc, out.entry)
    kept, gone = entry.files
    assert kept.plays_from == (took,) and kept.fields() == ["rating", "plays"]
    assert gone.trashed and gone.fields() == ["trashed"] and not gone.tags and not gone.plays
    assert history.document(entry)["files"] == doc["files"]


def test_changes_of_one_file_are_one_file_of_the_entry():
    """history.combined: a file's fields saved and what was noted of it are one."""
    took = history.Plays("b.m4a", H2, 2, PLAYED)
    a = FileChange("a.flac", None, {"rating": 3}, {"rating": 4})
    b = FileChange("a.flac", H1, {"title": "x"}, {"title": "y"}, True, H2, H3, plays_from=(took,))
    c = FileChange("b.m4a", H2, {}, trashed=True)
    one, two = history.combined([a, c, b])
    assert (one.path, one.hash, one.old, one.new) == (
        "a.flac", H1, {"rating": 3, "title": "x"}, {"rating": 4, "title": "y"}
    )  # fmt: skip
    assert (one.cover, one.old_cover, one.new_cover, one.plays_from) == (True, H2, H3, (took,))
    assert two == c


def test_shapes_of_plays_moved_and_files_in_the_trash_each_read_for_what_can_be_used(caplog):
    """testing.md's `history` shapes for R2.12's fields."""
    good = {"path": "x.m4a", "hash": H2, "count": 6, "last": PLAYED}
    doc = entry_doc(files=[
        {"path": "a.flac", "plays_from": [good, {"path": "../out.mp3", "count": 1, "last": PLAYED},
                                          {"path": "y.mp3", "count": 0}, "z"]},
        {"path": "b.flac", "plays_to": "not a list", "trashed": "yes"},
        {"path": "c.flac", "plays_to": [dict(good, hash="short", last="today")]},
        {"path": "d.flac", "trashed": True},
        {"path": "e.flac", "plays_from": None},
    ])  # fmt: skip
    found = parse(doc)
    a, c, d = found.files
    assert a.plays_from == (history.Plays("x.m4a", H2, 6, PLAYED),)
    assert c.plays_to == (history.Plays("x.m4a", None, 6, "1970-01-01T00:00:00Z"),)
    assert d.trashed and not d.tags
    said = "\n".join(found.problems)
    for problem in (
        "'../out.mp3' isn't a path under the root",
        "count isn't a number",
        "a song isn't an object",
        "plays_to isn't a list",
        "trashed isn't true or false",
        "b.flac: no field",
        "e.flac: no field",
    ):
        assert problem in said, problem  # fmt: skip


def test_undo_gives_back_the_plays_and_leaves_the_files_in_the_trash(tmp_path):
    """R2.12, R2.11: the plan of a move to the trash finds the kept copy without reading it for
    its plays alone, lists the files in the trash apart (neither undone nor failed), and the undo
    gives back the plays (`plays`), kept in its entry so it can be redone."""
    root = tmp_path / "Music"
    (root / "LD").mkdir(parents=True)
    (root / "LD" / "04.flac").write_bytes(b"")
    took = history.Plays("_Incoming/Moonpull.m4a", H2, 6, PLAYED)
    e = Entry(NAME, WHEN, ME, "copies", "Moonpull", (
        FileChange("LD/04.flac", H1, {}, plays_from=(took,)),
        FileChange("_Incoming/Moonpull.m4a", H2, {}, trashed=True),
    ))  # fmt: skip

    def look(path, cover):
        raise AssertionError("a file's plays need no reading")

    p = history.plan(e, str(root), lambda h: [], look=look)
    assert [(f.path, f.why) for f in p.files] == [("LD/04.flac", ""), (None, "")]
    assert p.failed == [] and [f.change.path for f in p.in_trash] == ["_Incoming/Moonpull.m4a"]
    assert history.jobs(p, str(root), overwrite=False) == []
    asked = []

    def plays(computer, files):
        asked.append((computer, [f.path for f in files]))
        return [history.plays_undone(f, f.change.plays_from) for f in files]

    rec = Recording(str(root), lambda: ME, FakeClock(WHEN + timedelta(minutes=1)), NAME)
    out = history.undo(p, str(root), False, lambda j: None, rec, plays=plays)
    assert asked == [(ME, ["LD/04.flac"])] and out.failed == [] and out.saved == []
    undone = history.read(history.folder_of(str(root)), out.entry)
    assert undone.description == "Undo: Moonpull" and undone.undoes == NAME
    (f,) = undone.files
    assert (f.path, f.plays_to, f.plays_from) == ("LD/04.flac", (took,), ())
    # its own undo (a redo) takes them again
    redo = history.plan(undone, str(root), lambda h: [], look=look)
    assert history.plays_undone(redo.files[0], (took,)).plays_from == (took,)
    # without a way to give plays back (the history's caller has no play counts), nothing moves
    out = history.undo(p, str(root), False, lambda j: None, None)
    assert out.entry is None and out.failed == []
    # the kept copy gone: its plays can't go back
    os.remove(root / "LD" / "04.flac")
    assert history.plan(e, str(root), lambda h: [], look=look).files[0].why


def test_the_plays_an_entry_moved_go_back_in_the_index_and_come_again(tmp_path):
    """history.plays_back: this computer's rows, given back to the copies (a copy in the trash
    waiting for its file) and taken again by a redo; a file the index hasn't is passed by."""
    index = db.Index(str(tmp_path / "musikata.db"))
    try:
        fill(index, [{"path": "LD/04.flac", "title": "Moonpull"}])
        (song,) = index.read().execute("SELECT id FROM song").fetchone()
        when = datetime(2026, 11, 25, 20, 41, tzinfo=UTC)

        def play(c):
            for _ in range(24):
                rootfiles.count(c, "me", song, when)

        index.write(play).result()
        took = history.Plays("_Incoming/Moonpull.m4a", H2, 6, PLAYED)
        kept = history.FileUndo(FileChange("LD/04.flac", H1, {}, plays_from=(took,)), "LD/04.flac")
        gone = history.FileUndo(FileChange("X.flac", H1, {}, plays_from=(took,)), "X.flac")
        done = index.write(lambda c: history.plays_back(c, "me", [kept, gone])).result()
        assert [(f.path, f.plays_to) for f in done] == [("LD/04.flac", (took,))]
        assert rootfiles.totals(index.read(), [song]) == {song: 18}
        redo = history.FileUndo(done[0], "LD/04.flac")
        again = index.write(lambda c: history.plays_back(c, "me", [redo])).result()
        assert [f.plays_from for f in again] == [(took,)]
        assert rootfiles.totals(index.read(), [song]) == {song: 24}
        assert index.write(lambda c: history.plays_back(c, "me", [redo])).result() == []
    finally:
        index.close()


def test_an_undo_of_a_move_to_the_trash_counts_the_files_it_can_undo():
    e = Entry(NAME, WHEN, ME, "copies", "Moonpull", (
        FileChange("a.flac", H1, {"rating": 4}), FileChange("b.m4a", H2, {}, trashed=True),
        FileChange("c.m4a", H3, {}, trashed=True),
    ))  # fmt: skip
    assert history.description_of(e, 1) == "Undo: Moonpull"
