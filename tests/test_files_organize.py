"""Organizing files (src/musikata_core/organize.py; R12, A2.8, A3.5): the plan of the moves under
the layout, its conflicts, the files beside the songs and the folders left empty; the move itself,
one entry in the change history, followed by the index and the playlists, and its Undo; and files
brought in from outside the root (R12.5).

Why: Organize files renames a whole library at once. A plan that sends two songs to one path, a
move over a file already there, a cover left behind in a folder removed, a playlist or a play count
left naming the old path, or an Undo that can't put every file back, loses the user's music or
what they kept about it, for good."""

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes import FakeClock, wav
from hypothesis import given
from hypothesis import strategies as st

from musikata_core import db, history, organize, patterns, playlists, rootfiles, scanner, tags
from musikata_core.history import Recording
from musikata_core.organize import TAKEN, TWICE, Move, Source
from musikata_core.tags import Batch, Job, Tags

LAYOUT = patterns.parse(patterns.LAYOUT, naming=True)
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
WHEN = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
SCHEMA = os.path.join(
    os.path.dirname(__file__), "..", "src", "musikata_core", "schemas",
    "history-entry.v1.schema.json",
)  # fmt: skip


def song(path, n=1, title=None, album="Tide Tables", artist="Lumen Drift", year=2022, **kw):
    t = Tags(title=title or f"Song {n}", artist=artist, album=album, year=year, track=n, **kw)
    return Source(n, path, t)


def nothing(_path):
    return False


# ---------- the plan (R12.2 to R12.4) ----------


def test_each_song_moves_to_its_layouts_path_and_one_in_place_or_without_tags_stays():
    """R12.2, R12.3: every move listed, old path and new; a song whose path already matches is
    left alone, and one with no tags at all too (no layout can place it: Infer from path first)."""
    sources = [
        song("_Incoming/a.mp3", 1),
        song("Lumen Drift/2022 - Tide Tables/02 - Song 2.flac", 2),
        Source(3, "_Incoming/track03.mp3", Tags()),
        song("Lumen Drift/2022 - Tide Tables/03 - song 3.flac", 3),  # but for case: renamed
    ]
    p = organize.plan(sources, LAYOUT, {}, nothing, prune=False)
    assert [(m.old, m.new, m.song) for m in p.moves] == [
        ("_Incoming/a.mp3", "Lumen Drift/2022 - Tide Tables/01 - Song 1.mp3", 1),
        ("Lumen Drift/2022 - Tide Tables/03 - song 3.flac",
         "Lumen Drift/2022 - Tide Tables/03 - Song 3.flac", 3),
    ]  # fmt: skip
    assert p.in_place == 1 and p.untagged == ("_Incoming/track03.mp3",) and p.emptied == ()
    assert len(p.chosen) == 2 and p.conflicts == []
    nfd = song("Björk/Unknown album/01 - Song 1.mp3", artist="Björk", album=None,
               year=None)  # fmt: skip
    assert organize.plan([nfd], LAYOUT, {}, nothing).in_place == 1  # composed, it is there
    # the extension is the file's own, its case kept unless it is a song's kind
    upper = organize.plan([song("x/a.MP3"), song("x/b.Flac", 2)], LAYOUT, {}, nothing)
    assert [m.new.rpartition(".")[2] for m in upper.moves] == ["mp3", "flac"]


def test_two_files_to_one_path_are_both_a_conflict_until_one_is_unchecked():
    """R12.4: two files that would get the same path are both listed as a conflict, and neither
    moves until one of them is changed or unchecked; paths that differ only in case or form are
    one path on Windows and macOS, so they are one here too."""
    a, b = song("x/a.mp3", 1), song("y/b.mp3", 1)
    c = song("z/c.mp3", 1, title="SONG 1")
    p = organize.plan([a, b, c], LAYOUT, {}, nothing)
    assert [m.conflict for m in p.moves] == [TWICE, TWICE, TWICE] and p.chosen == []
    assert len(p.conflicts) == 3
    p = organize.plan([a, b, c], LAYOUT, {}, nothing, unchecked={"y/b.mp3", "z/c.mp3"})
    assert [(m.checked, m.conflict) for m in p.moves] == [(True, ""), (False, ""), (False, "")]
    assert [m.old for m in p.chosen] == ["x/a.mp3"]
    changed = Source(2, "y/b.mp3", Tags(title="Other", artist="Lumen Drift", album="Tide Tables",
                                        year=2022, track=2))  # fmt: skip
    assert [m.conflict for m in organize.plan([a, changed], LAYOUT, {}, nothing).moves] == ["", ""]


def test_a_file_already_at_the_new_path_is_a_conflict_never_written_over():
    """R12.4: a file is never written over: an existing file at the new path is a conflict; the
    file itself, renamed only in case, is not one."""
    there = "Lumen Drift/2022 - Tide Tables/01 - Song 1.mp3"
    p = organize.plan([song("x/a.mp3")], LAYOUT, {}, lambda path: path == there)
    assert p.moves[0].conflict == TAKEN and p.chosen == []
    case = song(there.lower())
    p = organize.plan([case], LAYOUT, {}, lambda path: True)
    assert p.moves[0].conflict == "" and p.moves[0].new == there


def beside_of(*paths):
    """`plan`'s beside for files at `paths`: each folder's entries, subfolders with "/"."""
    out = {}
    for path in paths:
        parts = path.split("/")
        for n in range(len(parts)):
            folder = "/".join(parts[:n])
            entry = parts[n] + ("/" if n < len(parts) - 1 else "")
            out.setdefault(folder, set()).add(entry)
    return {k: sorted(v) for k, v in out.items()}


def test_images_cues_lyrics_and_logs_move_with_their_albums_songs():
    """R12.3: images, .cue, .lrc and .log files beside an album's songs move with them into the
    album's new folder, once every song of their folder leaves it; a song's own .lrc follows it,
    renamed as it is; other files stay, and keep their folder."""
    files = ["Old/01.mp3", "Old/02.mp3", "Old/cover.jpg", "Old/Back.PNG", "Old/rip.log",
             "Old/album.cue", "Old/01.lrc", "Old/notes.nfo", "Old/Scans/", "Old/x.lrc"]  # fmt: skip
    beside = beside_of(*[f.rstrip("/") + ("/" if f.endswith("/") else "") for f in files])
    beside["Old"] = [f.split("/", 1)[1] for f in files]
    sources = [song("Old/01.mp3", 1), song("Old/02.mp3", 2)]
    p = organize.plan(sources, LAYOUT, beside, nothing)
    new = "Lumen Drift/2022 - Tide Tables"
    assert [(m.old, m.new) for m in p.moves[2:]] == [
        ("Old/01.lrc", f"{new}/01 - Song 1.lrc"),
        ("Old/Back.PNG", f"{new}/Back.PNG"),
        ("Old/album.cue", f"{new}/album.cue"),
        ("Old/cover.jpg", f"{new}/cover.jpg"),
        ("Old/rip.log", f"{new}/rip.log"),
        ("Old/x.lrc", f"{new}/x.lrc"),
    ]
    assert all(m.song is None for m in p.moves[2:])
    assert p.emptied == ()  # notes.nfo and Scans stay: the folder isn't empty
    # a song of the folder that stays (unchecked, or not chosen) keeps the cover with it
    p = organize.plan(sources, LAYOUT, beside, nothing, unchecked={"Old/02.mp3"})
    assert [m.old for m in p.moves] == ["Old/01.mp3", "Old/02.mp3", "Old/01.lrc"]
    p = organize.plan(sources[:1], LAYOUT, beside, nothing)
    assert [m.old for m in p.moves] == ["Old/01.mp3", "Old/01.lrc"]
    # the album's new folder is where most of its songs go
    split = [song("Old/01.mp3", 1), song("Old/02.mp3", 2, album="B"), song("Old/03.mp3", 3)]
    beside["Old"] = ["01.mp3", "02.mp3", "03.mp3", "cover.jpg"]
    p = organize.plan(split, LAYOUT, beside, nothing)
    assert p.moves[-1].new == f"{new}/cover.jpg"
    # a sidecar is checked and in conflict like any move
    p = organize.plan(split, LAYOUT, beside, lambda path: path.endswith("cover.jpg"))
    assert p.moves[-1].conflict == TAKEN


def test_the_folders_left_empty_are_named_deepest_first_but_the_root_and_those_moved_into():
    """R12.3: a folder left empty is removed; one holding only what a system leaves in it
    (.DS_Store, Thumbs.db, desktop.ini) is empty; its parent too when that held nothing else; never
    the root, nor a folder a file moves into."""
    beside = beside_of("_Incoming/new rips/a.mp3", "_Incoming/new rips/.DS_Store",
                       "_Incoming/Thumbs.db", "b.mp3")  # fmt: skip
    p = organize.plan([song("_Incoming/new rips/a.mp3"), song("b.mp3", 2)], LAYOUT, beside,
                      nothing)  # fmt: skip
    assert p.emptied == ("_Incoming/new rips", "_Incoming")
    beside["_Incoming"].append("keep.txt")
    assert organize.plan([song("_Incoming/new rips/a.mp3")], LAYOUT, beside,
                         nothing).emptied == ("_Incoming/new rips",)  # fmt: skip
    into = beside_of("Lumen Drift/a.mp3", "Lumen Drift/2022 - Tide Tables/x.txt")
    p = organize.plan([song("Lumen Drift/a.mp3")], LAYOUT, into, nothing)
    assert p.emptied == ()  # Lumen Drift holds the album's new folder
    p = organize.plan(
        [song("Lumen Drift/a.mp3")], LAYOUT, into, nothing, unchecked={"Lumen Drift/a.mp3"}
    )
    assert p.emptied == ()
    assert organize.plan([song("a.mp3")], LAYOUT, beside_of("a.mp3"), nothing).emptied == ()


PATHS = st.lists(
    st.tuples(st.sampled_from(["A", "B", "A/C", "", "D/E/F"]), st.sampled_from("abcdef"),
              st.integers(1, 3), st.sampled_from(["X", "Y"])),
    max_size=8,
)  # fmt: skip


@given(PATHS, st.sets(st.integers(0, 7)))
def test_a_plan_never_moves_two_files_to_one_path_nor_one_onto_a_file(found, unchecked):
    """R12.4, a property: whatever the songs and the files beside them, the moves made go to
    paths no two share and no file has, each file moves once, and a folder left empty holds
    nothing that stays."""
    sources = []
    for n, (folder, name, track, album) in enumerate(found):
        path = f"{folder}/{name}{n}.mp3" if folder else f"{name}{n}.mp3"
        sources.append(Source(n, path, Tags(title=name, artist="A", album=album, track=track)))
    existing = {s.path for s in sources}
    beside = beside_of(
        *existing, *(f"{os.path.dirname(p)}/cover.jpg".lstrip("/") for p in existing)
    )
    off = {sources[i].path for i in unchecked if i < len(sources)}
    p = organize.plan(sources, LAYOUT, beside, lambda x: x in existing, off)
    news = [organize._key(m.new) for m in p.chosen]
    assert len(news) == len(set(news))
    assert not any(organize._key(m.new) in {organize._key(e) for e in existing}
                   and not organize.same_path(m.old, m.new) for m in p.chosen)  # fmt: skip
    olds = [m.old for m in p.moves]
    assert len(olds) == len(set(olds)) and not {m.old for m in p.chosen} & off
    for folder in p.emptied:
        assert all(f"{folder}/{n.rstrip('/')}" in {m.old for m in p.chosen} or n.endswith("/")
                   for n in beside[folder])  # fmt: skip


@given(PATHS, st.lists(st.integers(0, 11), max_size=12), st.booleans())
def test_checking_recounts_what_a_checkbox_touches_as_the_whole_plan_would(found, clicks, prune):
    """R12.2 to R12.4, a property: the plan made once and each checkbox changed after it
    (organize.Checking) is, after every click, the plan made anew with those moves unchecked:
    its moves, their conflicts, the files beside the songs and the folders left empty."""
    sources = []
    for n, (folder, name, track, album) in enumerate(found):
        path = f"{folder}/{name}{n}.mp3" if folder else f"{name}{n}.mp3"
        sources.append(Source(n, path, Tags(title=name, artist="A", album=album, track=track)))
    existing = {s.path for s in sources} | {"A/A/X/01 - b.mp3"}
    beside = beside_of(*existing, *(f"{os.path.dirname(p)}/cover.jpg".lstrip("/")
                                    for p in existing), "D/E/F/x.lrc")  # fmt: skip

    def taken(x):
        return x in existing

    checking = organize.Checking(sources, LAYOUT, beside, taken, prune=prune)
    rows = checking.rows
    assert checking.plan() == organize.plan(sources, LAYOUT, beside, taken, prune=prune)
    off: set[str] = set()
    for i in clicks:
        if not rows:
            break
        old = rows[i % len(rows)].old
        off ^= {old}
        checking.toggle(old)
        want = organize.plan(sources, LAYOUT, beside, taken, off, prune=prune)
        assert checking.plan() == want
        assert checking.chosen() == want.chosen and checking.chosen_count == len(want.chosen)
        assert checking.conflict_count == len(want.conflicts)
        assert all(checking.ready(m.old) == m.ready for m in want.moves)


@pytest.mark.slow
def test_checking_a_library_of_50000_songs_answers_a_click_at_once():
    """R12.2: a checkbox recounts in well under a frame, the plan made once."""
    import time

    sources, beside = [], {"": [f"Old{a}/" for a in range(5000)]}
    for a in range(5000):
        beside[f"Old{a}"] = [f"{t}.flac" for t in range(10)] + ["cover.jpg"]
        sources += [Source(a * 10 + t, f"Old{a}/{t}.flac",
                           Tags(title=f"S{t}", artist="A", album=f"B{a}", track=t + 1))
                    for t in range(10)]  # fmt: skip
    checking = organize.Checking(sources, LAYOUT, beside, nothing)
    assert checking.chosen_count == 55_000 and len(checking.emptied()) == 5000
    start = time.perf_counter()
    for n in range(20):
        checking.toggle(f"Old{n}/0.flac")
    took = (time.perf_counter() - start) / 20
    assert took < 0.016, f"a click took {took * 1000:.1f} ms"  # a frame, measured or not
    assert checking.chosen_count == 55_000 - 40 and len(checking.emptied()) == 4980


# ---------- the move, and what follows it (R12.4, A2.8) ----------


def test_a_move_is_a_rename_its_folder_made_first_and_never_over_a_file(tmp_path):
    """R12.4: a rename within the root's file system (os.replace), the folder made first; an
    existing file at the new path is never written over; the file itself renamed in case is."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.mp3").write_bytes(b"x")
    (tmp_path / "taken.mp3").write_bytes(b"t")
    job = Job(str(tmp_path / "a" / "x.mp3"), {organize.MOVE: str(tmp_path / "n" / "m" / "x.mp3"),
                                               organize.HASH: "h"})  # fmt: skip
    moved = organize.move_file(job)
    assert moved == organize.Moved(str(tmp_path / "n" / "m" / "x.mp3"), job.path, "h")
    assert (tmp_path / "n" / "m" / "x.mp3").read_bytes() == b"x" and not os.path.exists(job.path)
    over = Job(moved.path, {organize.MOVE: str(tmp_path / "taken.mp3")})
    with pytest.raises(tags.WriteError, match="a file is at taken.mp3 already"):
        organize.move_file(over)
    assert (tmp_path / "taken.mp3").read_bytes() == b"t"
    with pytest.raises(tags.WriteError, match="isn't there any more"):
        organize.move_file(job)
    same = Job(moved.path, {organize.MOVE: moved.path})
    assert organize.move_file(same).path == moved.path  # the file itself: no conflict


def test_a_move_that_fails_says_why_and_the_file_stays(tmp_path, monkeypatch):
    (tmp_path / "x.mp3").write_bytes(b"x")
    job = Job(str(tmp_path / "x.mp3"), {organize.MOVE: str(tmp_path / "y" / "x.mp3")})

    def refused(a, b):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(os, "replace", refused)
    with pytest.raises(tags.WriteError, match="on another drive"):
        organize.move_file(job)

    def denied(a, b):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", denied)
    with pytest.raises(tags.WriteError, match="can't be written"):
        organize.move_file(job)
    assert (tmp_path / "x.mp3").exists()


def test_folders_left_empty_are_removed_with_a_systems_clutter_never_the_root(tmp_path, caplog):
    """R12.3: an empty folder holds nothing to get back, and Undo makes it again, so it is removed,
    not moved to the trash; one holding anything but a system's clutter stays."""
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / ".DS_Store").write_bytes(b"")
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "keep.txt").write_text("x")
    assert organize.prune(str(tmp_path), ["a/b", "c", "", "gone"]) == ["a/b", "a"]
    assert sorted(os.listdir(tmp_path)) == ["c"]
    (tmp_path / "d").mkdir()
    os.chmod(tmp_path, 0o500)
    try:
        assert organize.prune(str(tmp_path), ["d"]) == [] and "couldn't remove" in caplog.text
    finally:
        os.chmod(tmp_path, 0o700)


@pytest.fixture
def library(tmp_path):
    """A root of three WAVs (an album of two and a loose one, each tagged), a cover and an .lrc
    beside the album, a playlist naming two of them, its index and plays: (root, index)."""
    root = tmp_path / "Music"
    files = {"Old/a.wav": ("Neap Tide", 1), "Old/b.wav": ("Spring Tide", 2),
             "c.wav": ("Loose", None)}  # fmt: skip
    for n, (rel, (title, track)) in enumerate(files.items()):
        wav(root / rel, n + 1)
        changes = {"title": title, "artist": "Lumen Drift", "album": "Tide Tables", "year": 2022}
        if track:
            changes["track"] = track
        else:
            changes["album"] = changes["year"] = None
        tags.save(str(root / rel), changes, audio_hash=scanner.audio_hash)
    (root / "Old" / "cover.jpg").write_bytes(b"jpeg")
    (root / "Old" / "a.lrc").write_text("[00:01.00]words")
    (root / "Playlists").mkdir()
    (root / "Playlists" / "Road Trip.m3u8").write_text("#EXTM3U\n../Old/a.wav\n../c.wav\n")
    index = db.Index(str(tmp_path / "musikata.db"))
    scan(str(root), index)
    rootfiles_played(index, "Old/a.wav", 3)
    yield str(root), index
    index.close()


def scan(root, index):
    with ThreadPoolExecutor(1) as pool:
        return scanner.scan(root, index, pool, hold=False)


def rootfiles_played(index, path, n):
    def write(c):
        (song_id,) = c.execute("SELECT id FROM song WHERE path = ?", (path,)).fetchone()
        for _ in range(n):
            rootfiles.count(c, ME, song_id, WHEN)

    index.write(write).result()


def ids(index):
    return dict(index.read().execute("SELECT path, id FROM song"))


def organized(root, index, clock, unchecked=()):
    """Organize files on the whole library, as the dialog does it: the plan, the batch recorded
    as one entry, and what follows it."""
    c = index.read()
    sources = organize.sources_of(c, list(ids(index).values()))
    p = organize.plan(sources, LAYOUT, organize.listing(root, [s.path for s in sources]),
                      organize.taken_in(root), unchecked)  # fmt: skip
    store = playlists.Store(root, index, "Playlists", "cp1252")
    rec = Recording(root, lambda: ME, clock)
    jobs = organize.move_jobs(root, p.chosen)
    out = Batch(jobs, organize.move_file, record=rec, action="organize",
                description="Organize files: 3 files").run()  # fmt: skip
    followed = organize.Follower(root, lambda fn: index.write(fn).result(), store.repoint)(
        organize.pairs_of(root, out.saved)
    )
    clock.advance(seconds=1)
    return p, out, followed


def test_organize_files_moves_the_songs_their_sidecars_and_playlists_in_one_entry(library):
    """R12.2 to R12.4: the moves made, the cover and the .lrc with them, the folder left empty
    removed, the playlist naming them updated in the same step; the whole move one entry in the
    change history, each file with its old path (`from`, A2.10), held to its schema."""
    import jsonschema

    root, index = library
    before = ids(index)
    clock = FakeClock(WHEN)
    p, out, followed = organized(root, index, clock)
    album = "Lumen Drift/2022 - Tide Tables"
    assert p.emptied == ("Old",)
    assert sorted(organize.pairs_of(root, out.saved)) == [
        ("Old/a.lrc", f"{album}/01 - Neap Tide.lrc"), ("Old/a.wav", f"{album}/01 - Neap Tide.wav"),
        ("Old/b.wav", f"{album}/02 - Spring Tide.wav"), ("Old/cover.jpg", f"{album}/cover.jpg"),
        ("c.wav", "Lumen Drift/Unknown album/Loose.wav"),
    ]  # fmt: skip
    assert followed.songs == 3 and followed.removed == ["Old"] and followed.failed == []
    assert followed.playlists == ["Playlists/Road Trip.m3u8"]
    text = (Path(root) / "Playlists" / "Road Trip.m3u8").read_text(encoding="utf-8")
    assert (
        f"../{album}/01 - Neap Tide.wav" in text
        and "../Lumen Drift/Unknown album/Loose.wav" in text
    )
    # the index followed: each song kept its id, so its plays, rating and place in the queue
    after = ids(index)
    assert after[f"{album}/01 - Neap Tide.wav"] == before["Old/a.wav"]
    c = index.read()
    assert c.execute("SELECT path, count FROM play").fetchall() == [
        (f"{album}/01 - Neap Tide.wav", 3)
    ]
    assert c.execute("SELECT path FROM folder WHERE path = 'Old'").fetchall() == []
    assert c.execute("SELECT songs FROM folder WHERE path = ?", (album,)).fetchone() == (2,)
    assert c.execute("SELECT image FROM folder WHERE path = ?", (album,)).fetchone() == (
        f"{album}/cover.jpg",
    )
    assert c.execute("SELECT path FROM playlist_entry ORDER BY position").fetchall() == [
        (f"{album}/01 - Neap Tide.wav",),
        ("Lumen Drift/Unknown album/Loose.wav",),
    ]
    found = c.execute("SELECT rowid FROM song_fts WHERE song_fts MATCH 'neap'").fetchall()
    assert found == [(before["Old/a.wav"],)]
    # a scan after finds nothing to read or move: the rows are the files'
    result = scan(root, index)
    assert (result.added, result.moved, result.removed) == (0, 0, 0)
    doc = json.loads((Path(history.folder_of(root)) / out.entry).read_text(encoding="utf-8"))
    with open(SCHEMA, encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    assert doc["action"] == "organize" and len(doc["files"]) == 5
    first = next(f for f in doc["files"] if f["path"].endswith("Neap Tide.wav"))
    assert first["from"] == "Old/a.wav" and len(first["hash"]) == 64
    assert history.read(history.folder_of(root), out.entry).files[0].fields() == ["path"]


def test_undo_puts_every_file_and_playlist_back_and_redo_moves_them_again(library):
    """R12.4, R4.9: Undo puts every file, and every playlist, back, as one entry of its own, so it
    can be undone in turn; the folders the files left are removed again."""
    root, index = library
    clock = FakeClock(WHEN)
    _, out, _ = organized(root, index, clock)
    store = playlists.Store(root, index, "Playlists", "cp1252")
    follow = organize.Follower(root, lambda fn: index.write(fn).result(), store.repoint)
    folder = history.folder_of(root)

    def undo(name):
        e = history.read(folder, name)
        p = history.plan(e, root, history.finder(index.read()))
        done = history.undo(p, root, False, lambda job: None,
                            Recording(root, lambda: ME, clock, name))  # fmt: skip
        clock.advance(seconds=1)
        return p, done, follow(organize.pairs_of(root, done.saved))

    p, undone, followed = undo(out.entry)
    assert p.changed == [] and p.taken == [] and undone.failed == [] and len(undone.saved) == 5
    assert sorted(os.listdir(os.path.join(root, "Old"))) == ["a.lrc", "a.wav", "b.wav", "cover.jpg"]
    assert os.path.exists(os.path.join(root, "c.wav"))
    assert not os.path.exists(os.path.join(root, "Lumen Drift"))
    assert followed.playlists == ["Playlists/Road Trip.m3u8"] and followed.removed == [
        "Lumen Drift/2022 - Tide Tables",
        "Lumen Drift/Unknown album",
        "Lumen Drift",
    ]
    text = (Path(root) / "Playlists" / "Road Trip.m3u8").read_text(encoding="utf-8")
    assert "../Old/a.wav" in text and "../c.wav" in text
    assert index.read().execute("SELECT path FROM play").fetchall() == [("Old/a.wav",)]
    e = history.read(folder, undone.entry)
    assert e.undoes == out.entry and e.description == "Undo: Organize files: 3 files"
    assert {(f.moved_from, f.path) for f in e.files} >= {
        ("Lumen Drift/2022 - Tide Tables/01 - Neap Tide.wav", "Old/a.wav")
    }
    _, redone, _ = undo(undone.entry)
    assert len(redone.saved) == 5 and not os.path.exists(os.path.join(root, "Old"))


def test_undo_asks_for_a_file_moved_since_and_leaves_one_whose_place_is_taken(library):
    """R4.9.1, R12.4: a file moved again since is found by its audio hash, and what undoing would
    lose (where it is now) is asked about first; a file whose old place another file has taken
    since stays where it is, never written over, and says why; one gone says so."""
    root, index = library
    clock = FakeClock(WHEN)
    _, out, _ = organized(root, index, clock)
    album = os.path.join(root, "Lumen Drift", "2022 - Tide Tables")
    os.replace(os.path.join(album, "01 - Neap Tide.wav"), os.path.join(root, "elsewhere.wav"))
    index.write(lambda c: c.execute("UPDATE song SET path = 'elsewhere.wav' WHERE path LIKE"
                                    " '%Neap Tide.wav'")).result()  # fmt: skip
    os.makedirs(os.path.join(root, "Old"))
    with open(os.path.join(root, "Old", "b.wav"), "wb") as f:
        f.write(b"another")
    os.remove(os.path.join(album, "cover.jpg"))
    e = history.read(history.folder_of(root), out.entry)
    p = history.plan(e, root, history.finder(index.read()))
    (moved,) = p.changed
    assert [(x.field, x.now, x.back) for x in moved.lost] == [
        ("path", "elsewhere.wav", "Old/a.wav")
    ]
    (taken,) = p.taken
    assert taken.why == "its old place, Old/b.wav, holds another file now"
    assert [f.why for f in p.failed if not f.taken] == ["it isn't there any more"]
    done = history.undo(p, root, False, lambda job: None, None)
    assert sorted(organize.pairs_of(root, done.saved)) == [
        ("Lumen Drift/2022 - Tide Tables/01 - Neap Tide.lrc", "Old/a.lrc"),
        ("Lumen Drift/Unknown album/Loose.wav", "c.wav"),
    ]
    assert sorted(f.why for f in done.failed) == [
        "it isn't there any more",
        "its old place, Old/b.wav, holds another file now",
    ]
    assert (Path(root) / "Old" / "b.wav").read_bytes() == b"another"
    done = history.undo(p, root, True, lambda job: None, None)  # the user said so
    assert organize.pairs_of(root, done.saved) == [("elsewhere.wav", "Old/a.wav")]


def test_a_move_entrys_shapes_are_read_for_what_can_be_used(caplog):
    """A2.10, testing.md's `history` shapes: `from` as an entry names it; one outside the root or
    not a path is left out, the file with it when nothing else is left."""
    doc = {"format": 1, "time": "2026-11-27T16:00:00Z", "computer": ME, "action": "organize",
           "files": [{"path": "New/a.flac", "from": "Old/a.flac", "fields": {}, "new": {}},
                     {"path": "New/b.flac", "from": "/etc/passwd"},
                     {"path": "New/c.flac", "from": 3, "fields": {"title": "x"}}]}  # fmt: skip
    e = history.parse(f"20261127T160000000Z-{ME}.json", json.dumps(doc))
    assert [(f.path, f.moved_from) for f in e.files] == [("New/a.flac", "Old/a.flac"),
                                                          ("New/c.flac", None)]  # fmt: skip
    assert sum("from isn't a path under the root" in p for p in e.problems) == 2
    assert history.document(e)["files"][0]["from"] == "Old/a.flac"
    assert history.description_of(e, 1) == "Undo: an undo (1 of 2 files)".replace(
        "an undo", "a save")  # fmt: skip


def test_a_move_that_fails_midway_keeps_what_moved_recorded_and_says_what_didnt(library):
    """R12.4: a move that fails midway leaves what moved recorded and undoable, and says what
    didn't."""
    root, index = library
    clock = FakeClock(WHEN)
    os.chmod(os.path.join(root, "Old"), 0o500)  # its files can't leave it
    try:
        _, out, followed = organized(root, index, clock)
    finally:
        os.chmod(os.path.join(root, "Old"), 0o700)
    assert organize.pairs_of(root, out.saved) == [("c.wav", "Lumen Drift/Unknown album/Loose.wav")]
    assert len(out.failed) == 4 and all("can't be written" in f.why for f in out.failed)
    e = history.read(history.folder_of(root), out.entry)
    assert [(f.moved_from, f.path) for f in e.files] == [
        ("c.wav", "Lumen Drift/Unknown album/Loose.wav")
    ]
    assert followed.removed == [] and os.path.isdir(os.path.join(root, "Old"))


def test_the_index_follows_by_id_and_a_stale_row_at_the_new_path_goes(library, caplog):
    """A2.8: each song keeps its row; a row left at a new path (a file gone since the last scan)
    is taken out first; a move of a file the index hasn't is passed by; a step that fails is logged
    and the next still runs."""
    root, index = library
    before = ids(index)
    moves = [("Old/a.wav", "c.wav"), ("nope.wav", "x.wav")]
    n = index.write(lambda c: organize.index_moves(c, moves)).result()
    assert n == 1 and ids(index) == {"c.wav": before["Old/a.wav"], "Old/b.wav": before["Old/b.wav"]}

    def broken(fn):
        raise RuntimeError("no index")

    def refused(moves):
        raise OSError("no playlists")

    followed = organize.Follower(root, broken, refused)([("Old/b.wav", "Old/z.wav")])
    assert followed.failed == ["the library", "the playlists"] and "no index" in caplog.text
    assert organize.Follower(root, broken)([]) == organize.Followed()


def test_what_a_plan_is_made_from_the_index_and_the_disk(library):
    """The songs' tags as a layout reads them, with their albums' discs (R12.1's {disc-}); each
    folder's entries up to the root; the playlists naming the files (R12.4: the dialog says
    which)."""
    root, index = library
    c = index.read()
    index.write(lambda c: c.execute("UPDATE song SET disc = 2 WHERE path = 'Old/b.wav'")).result()
    found = {s.path: s for s in organize.sources_of(c, list(ids(index).values()) + [999])}
    assert found["Old/a.wav"].discs == 2 and found["c.wav"].discs == 1
    assert found["Old/a.wav"].tags.title == "Neap Tide" and len(found["Old/a.wav"].hash) == 64
    beside = organize.listing(root, ["Old/a.wav", "Gone/x.wav"])
    assert sorted(beside["Old"]) == ["a.lrc", "a.wav", "b.wav", "cover.jpg"]
    assert "Old/" in beside[""] and beside["Gone"] == ["?"]
    assert organize.playlists_naming(c, ["Old/a.wav", "Old/b.wav"]) == {"Old/a.wav": ["Road Trip"]}
    assert organize.taken_in(root)("c.wav") and not organize.taken_in(root)("d.wav")


# ---------- adding files from outside the root (R12.5) ----------


def test_files_dropped_from_outside_are_their_audio_files_each_once(tmp_path):
    """R12.5: a folder dropped brings every audio file beneath it, named from the folder dropped
    as Infer from path reads them; a file once, hidden ones and what isn't audio left out."""
    rips = tmp_path / "Downloads" / "Kestrel Union" / "2022 - Low Orbit"
    for name in ("01 - Low Orbit.mp3", "02 - Perihelion.mp3", "cover.jpg", ".hidden.mp3"):
        (rips / name).parent.mkdir(parents=True, exist_ok=True)
        (rips / name).write_bytes(b"x")
    (rips / ".git").mkdir()
    (rips / ".git" / "z.mp3").write_bytes(b"x")
    loose = tmp_path / "loose.flac"
    loose.write_bytes(b"x")
    found = organize.outside_songs(
        [
            str(tmp_path / "Downloads" / "Kestrel Union"),
            str(loose),
            str(rips / "01 - Low Orbit.mp3"),
            str(tmp_path / "x.txt"),
        ]
    )
    assert [n for _, n in found] == [
        "Kestrel Union/2022 - Low Orbit/01 - Low Orbit.mp3",
        "Kestrel Union/2022 - Low Orbit/02 - Perihelion.mp3", "loose.flac",
    ]  # fmt: skip


def test_a_file_from_outside_is_read_and_one_the_library_has_is_found_by_its_audio(
    library, tmp_path
):
    """R12.5: a file already in the library (the same audio, A2.3) is reported, not added twice;
    one that can't be read says why."""
    root, index = library
    copy = tmp_path / "copy.wav"
    shutil.copyfile(os.path.join(root, "Old", "a.wav"), copy)
    tags.save(str(copy), {"title": "Retagged"}, audio_hash=scanner.audio_hash)
    read = organize.read_outside(str(copy), "copy.wav")
    assert read.tags.title == "Retagged" and read.size == os.path.getsize(copy) and read.hash
    assert organize.known(index.read(), [read.hash, "f" * 64, ""]) == {read.hash: "Old/a.wav"}
    (tmp_path / "bad.mp3").write_bytes(b"not audio")
    bad = organize.read_outside(str(tmp_path / "bad.mp3"), "bad.mp3")
    assert bad.error and bad.hash is None


def test_a_file_from_outside_is_copied_or_moved_into_its_place_never_over_one(tmp_path):
    """R12.5: Copy into the library (the default) leaves the original; Move into the library
    takes it; a copy is made beside its place and renamed in, so no half a file is ever there; a
    file at its place is never written over; its tags filled from its path written then."""
    root = tmp_path / "Music"
    src = tmp_path / "in" / "a.wav"
    wav(src, 3)
    m = Move(str(src), "K/Low Orbit/01 - a.wav", hash="h")
    seen = []

    def write(job):
        seen.append((job.path, dict(job.changes)))
        return tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)

    done = organize.add_file(organize.add_job(str(root), m, {"title": "Low Orbit"}), True, write)
    assert done.path == str(root / "K" / "Low Orbit" / "01 - a.wav") and src.exists()
    assert done.written is not None and tags.read(done.path)[0].title == "Low Orbit"
    assert seen == [(done.path, {"title": "Low Orbit"})]
    assert sorted(os.listdir(root / "K" / "Low Orbit")) == ["01 - a.wav"]  # no copy left
    with pytest.raises(tags.WriteError, match="a file is at 01 - a.wav already"):
        organize.add_file(organize.add_job(str(root), m), False)
    moved = organize.add_file(organize.add_job(str(root), Move(str(src), "K/b.wav")), False)
    assert not src.exists() and os.path.exists(moved.path) and moved.written is None
    with pytest.raises(tags.WriteError, match="isn't there any more"):
        organize.add_file(organize.add_job(str(root), Move(str(src), "K/c.wav")), True)


def test_a_move_from_another_drive_is_copied_then_the_original_removed(tmp_path, monkeypatch,
                                                                     caplog):  # fmt: skip
    root = tmp_path / "Music"
    src = tmp_path / "a.wav"
    wav(src, 4)

    def other_drive(a, b):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(os, "rename", other_drive)
    done = organize.add_file(organize.add_job(str(root), Move(str(src), "a.wav"),
                                              {"title": "x"}), False, None)  # fmt: skip
    assert os.path.exists(done.path) and not src.exists()

    def broken(job):
        raise tags.WriteError(job.path, "it is read-only")

    wav(src, 4)
    done = organize.add_file(organize.add_job(str(root), Move(str(src), "b.wav"),
                                              {"title": "x"}), True, broken)  # fmt: skip
    assert os.path.exists(done.path) and done.written is None and "weren't filled" in caplog.text

    def full(a, b):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "copy2", full)
    with pytest.raises(tags.WriteError, match="the disk is full"):
        organize.add_file(organize.add_job(str(root), Move(str(src), "c.wav")), True)
    assert sorted(os.listdir(root)) == ["a.wav", "b.wav"]

    def denied(a, b):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "rename", denied)
    with pytest.raises(tags.WriteError):
        organize.add_file(organize.add_job(str(root), Move(str(src), "d.wav")), False)


def test_files_brought_in_are_indexed_as_a_scans_batch_would(library):
    root, index = library
    wav(os.path.join(root, "New", "n.wav"), 9, "New one")
    st_ = os.stat(os.path.join(root, "New", "n.wav"))
    read = scanner.read_one(root, scanner.Seen("New/n.wav", st_.st_size, st_.st_mtime_ns))
    made = index.write(lambda c: organize.index_added(c, [read], 5.0)).result()
    c = index.read()
    assert made == [c.execute("SELECT id FROM song WHERE path = 'New/n.wav'").fetchone()[0]]
    assert c.execute("SELECT title, added FROM song WHERE id = ?", made).fetchone() == (
        "New one",
        5.0,
    )


# ---------- a .cue sheet's FILE lines follow the files it names (R12.3, A2.6) ----------


@pytest.mark.parametrize(
    ("sheet", "names", "after"),
    [
        (
            b'FILE "a.wav" WAVE\r\n  TRACK 01 AUDIO\r\n',
            {"a.wav": "01 - A.wav"},
            b'FILE "01 - A.wav" WAVE\r\n  TRACK 01 AUDIO\r\n',
        ),
        (b"\xef\xbb\xbffile a.wav WAVE\n", {"a.wav": "01.wav"}, b"\xef\xbb\xbffile 01.wav WAVE\n"),
        (b"FILE a.wav WAVE\rREM x\r", {"a.wav": "01 - A.wav"}, b'FILE "01 - A.wav" WAVE\rREM x\r'),
        (b'FILE\t"A.WAV" WAVE\n', {"a.wav": "b.wav"}, b'FILE\t"b.wav" WAVE\n'),
        (
            b'FILE "C:\\Rips\\a.wav" WAVE\n',
            {"a.wav": "01 - A.wav"},
            b'FILE "C:\\Rips\\01 - A.wav" WAVE\n',
        ),
        (
            b'FILE "a.wav" WAVE\n',
            {"a.wav": "../Elsewhere/a.wav"},
            b'FILE "../Elsewhere/a.wav" WAVE\n',
        ),
        (
            b'REM COMMENT "Caf\xe9"\nFILE "a.wav" WAVE\n',
            {"a.wav": "\u00e9t\u00e9.wav"},
            b'REM COMMENT "Caf\xe9"\nFILE "\xe9t\xe9.wav" WAVE\n',
        ),
    ],
)
def test_a_cue_sheets_file_lines_name_the_files_anew_in_its_encoding_and_line_ends(
    sheet, names, after
):
    """R12.3, A2.6's shapes: quoted and not, `file` in lower case, a tab after it, a ripper's
    folder before the name (kept), the name in another case, a path to another folder; UTF-8 with
    its BOM, cp1252; CRLF, LF and CR, each kept."""
    assert organize.cue_renamed(sheet, names) == after


def test_a_cue_line_naming_a_subfolders_file_or_a_name_its_encoding_cant_hold_is_left():
    sheet = 'REM COMMENT "Caf\u00e9"\r\nFILE "CD1/a.wav" WAVE\r\nFILE "b.wav" WAVE\r\n'.encode(
        "cp1252"
    )
    assert organize.cue_renamed(sheet, {"a.wav": "x.wav"}) is None
    assert organize.cue_renamed(sheet, {"b.wav": "\u0416.wav"}) is None
    assert organize.cue_renamed(b"FILE x.wav WAVE\n", {}) is None
    assert organize.cue_encoding(b"\xff\xfe\x81") == "latin-1"


def test_a_cue_sheet_moved_with_its_album_names_its_files_anew_and_undo_puts_it_back(library):
    """R12.3, R4.9: an album's .cue moves with its songs, its FILE lines naming them by their new
    names, in the sheet's own encoding and line ends; a line naming another file is left; Undo
    puts the sheet back, byte for byte."""
    root, index = library
    sheet = (
        'REM COMMENT "Caf\u00e9"\r\nFILE "a.wav" WAVE\r\n  TRACK 01 AUDIO\r\n'
        'FILE "C:\\Rips\\b.wav" WAVE\r\nFILE "Other.wav" WAVE\r\n'
    ).encode("cp1252")
    (Path(root) / "Old" / "Tide Tables.cue").write_bytes(sheet)
    clock = FakeClock(WHEN)
    _, out, _ = organized(root, index, clock)
    moved = Path(root) / "Lumen Drift" / "2022 - Tide Tables" / "Tide Tables.cue"
    assert moved.read_bytes() == sheet.replace(b'"a.wav"', b'"01 - Neap Tide.wav"').replace(
        b"\\b.wav", b"\\02 - Spring Tide.wav")  # fmt: skip
    e = history.read(history.folder_of(root), out.entry)
    p = history.plan(e, root, history.finder(index.read()))
    done = history.undo(p, root, False, lambda job: None, None)
    assert done.failed == []
    assert (Path(root) / "Old" / "Tide Tables.cue").read_bytes() == sheet


def test_a_cue_that_cant_be_rewritten_still_moves_and_the_log_says_so(
    tmp_path, caplog, monkeypatch
):
    (tmp_path / "a.cue").write_bytes(b'FILE "a.wav" WAVE\n')
    job = organize.move_jobs(str(tmp_path), [organize.Move("a.cue", "B/a.cue"),
                                              organize.Move("a.wav", "B/01.wav")])[0]  # fmt: skip
    assert job.changes[organize.NAMES] == {"a.wav": "01.wav"}
    monkeypatch.setattr(organize, "tmp_path", lambda p: str(tmp_path / "no" / "such" / "x"))
    organize.move_file(job)
    assert (tmp_path / "B" / "a.cue").read_bytes() == b'FILE "a.wav" WAVE\n'
    assert "weren't rewritten" in caplog.text


def test_a_dismissal_about_an_albums_folder_follows_the_album_moved_and_back(library):
    """R2.8, A2.8, R12: Needs attention's Ignore of an album's folder (its songs' tags differ from
    their path, its cover small) follows the album to the folder Organize files moved it to, in
    the index and in ignored.json, the old one kept for an Undo that brings the album back; a
    dismissal about a song follows it by its hash already (A2.8), and a folder its songs stay in
    keeps its own."""
    from musikata_core import attention

    root, index = library
    old = [rootfiles.Dismissal(attention.PATH, "Old", None, 5.0, "2026-11-27T15:00:00Z"),
           rootfiles.Dismissal(attention.COVER_SMALL, "Old", None, None, "2026-11-27T15:00:00Z"),
           rootfiles.Dismissal(attention.ONE_FILE, "Old/a.wav", "a" * 64, 5.0,
                               "2026-11-27T15:00:00Z")]  # fmt: skip
    index.write(lambda c: rootfiles.load_ignored(c, old)).result()
    clock = FakeClock(WHEN)
    _, out, _ = organized(root, index, clock)
    album = "Lumen Drift/2022 - Tide Tables"
    there = {(d.kind, d.about) for d in rootfiles.dismissals(index.read())}
    assert {(attention.PATH, album), (attention.COVER_SMALL, album)} <= there
    assert (attention.ONE_FILE, album) not in there
    kept = rootfiles.read_ignored(rootfiles.ignored_of(root))
    assert {(d.kind, d.about, d.modified, d.changed) for d in kept.entries} == {
        (attention.PATH, album, 5.0, "2026-11-27T15:00:00Z"),
        (attention.COVER_SMALL, album, None, "2026-11-27T15:00:00Z"),
    }
    assert attention.followed(index.read(), [("c.wav", "c.wav")]) == []
