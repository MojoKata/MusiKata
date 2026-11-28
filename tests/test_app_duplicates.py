"""The same song more than once in the running app (src/musikata/duplicates.py, and its group in
src/musikata/attention.py; R2.12, R2.11, L09-needs-attention): what a group of copies says, the
choice of the copy kept and those checked, Review…, and Move the others to the trash: asked first,
the files to the system's trash, the kept copy given their plays and highest rating, one entry in
the change history whose Undo gives back the plays and rating and says the files stay in the
trash.

Why: moving a copy to the trash takes a file out of the user's library, so it must be the copies
they checked, after they were asked, naming them; the copy kept must not lose what the others had
(plays, rating), and Undo must put back all it can and say what it can't."""

import dataclasses
import json
import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import mutagen.id3
import mutagen.wave
import pytest
from fakes import FakeClock, wav
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from musikata import app, layout, tour
from musikata import duplicates as copies_app
from musikata.attention import GROUPS, AttentionModel, chips_of, entry_row, group_row, rows_of
from musikata.duplicates import (
    Duplicates,
    bar_text,
    copy_rows,
    description_of,
    details_text,
    format_text,
    heading_text,
    lengths_text,
    move_label,
    moved_text,
    names_text,
    question_of,
)
from musikata.history import ChangeHistory, undone_text
from musikata_core import (
    attention,
    db,
    duplicates,
    history,
    playlists,
    ratings,
    rootfiles,
    scanner,
    settings,
)
from musikata_core import tags as tags_core
from musikata_core.attention import Entry
from musikata_core.duplicates import Copy, Group
from musikata_core.tags import Outcome

WAIT = 10_000
ME = "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d"
NOW = datetime(2026, 11, 26, 21, 0, tzinfo=UTC)
H1, H2 = "1" * 64, "2" * 64
BY = {g.key: g for g in GROUPS}

FLAC = Copy(1, "Lumen Drift/Glass Harbor/04 - Signal Fires.flac", "flac", 912_000, 44100, 258.4,
            H1, "k", "Signal Fires", "Lumen Drift", "Glass Harbor", 52, 5)  # fmt: skip
RIP = Copy(2, "_Incoming/new rips/Signal Fires.flac", "flac", 905_000, 44100, 258.4, H1, "k",
           "Signal Fires", "Lumen Drift", "", 3, 4)  # fmt: skip
M4A = Copy(3, "_Incoming/From Phone/Moonpull (radio).m4a", "aac", 256_000, 44100, 285.2, H2,
           "k", "Moonpull", "Lumen Drift", "", 6, 0)  # fmt: skip


def entry_of(*copies, likely=False, why=duplicates.LOSSLESS_WINS):
    return attention.copies_entry(Group(copies, likely, why))


# ---------- what a group and its copies say ----------


def test_a_copy_says_its_format_and_bit_rate_as_l09_does():
    assert format_text(FLAC) == "FLAC · 44.1 kHz"
    assert format_text(M4A) == "AAC · 256 kbps"
    assert format_text(Copy(9, "x.opus", "opus", 160_400, 48000)) == "Opus · 160 kbps"
    assert format_text(Copy(9, "x.wav", "wav")) == "WAV"
    assert format_text(Copy(9, "x")) == ""
    assert details_text(FLAC) == "912 kbps · 44.1 kHz · 4:18"
    assert details_text(Copy(9, "x")) == ""


def test_a_group_says_its_artist_lengths_and_whether_its_copies_are_exact():
    """L09: "Lumen Drift · 4:18", Exact; "Lumen Drift · 4:44 and 4:45", Likely; why, in the
    chip's tooltip (R2.12)."""
    exact = entry_of(FLAC, RIP)
    assert heading_text(exact) == "Lumen Drift · 4:18" and copies_app.badge_text(exact) == "Exact"
    assert copies_app.badge_tip(exact) == "Exact copies: the same audio"
    likely = entry_of(FLAC, M4A, likely=True)
    assert heading_text(likely) == "Lumen Drift · 4:18 and 4:45"
    assert copies_app.badge_text(likely) == "Likely"
    assert copies_app.badge_tip(likely) == (
        "Likely copies: the same artist and title, lengths within 2 seconds")  # fmt: skip
    assert lengths_text([FLAC, RIP, M4A, Copy(9, "x", length=59.0)]) == "0:59, 4:18 and 4:45"
    assert lengths_text([]) == "" and heading_text(Entry("same-song", "x")) == "Unknown artist"


def test_its_rows_put_the_copy_kept_first_with_why_and_the_checked_for_the_trash():
    """L09's rows: Keep on the copy kept (Keep: lossless while it is the one proposed), Trash
    checked on the exact copy, its format, path, plays and rating."""
    e = entry_of(FLAC, RIP, M4A, likely=True)
    rows = copy_rows(e, 1, frozenset({2}))
    assert [(r["song"], r["kept"], r["checked"], r["exact"]) for r in rows] == [
        (1, True, False, True), (2, False, True, True), (3, False, False, False)
    ]  # fmt: skip
    first = rows[0]
    assert (first["format"], first["plays"], first["rating"], first["why"]) == (
        "FLAC · 44.1 kHz", "52 plays", 5, "Keep: lossless"
    )  # fmt: skip
    assert (first["folder"], first["name"]) == ("Lumen Drift/Glass Harbor",
                                                "04 - Signal Fires.flac")  # fmt: skip
    # another kept: first, without the proposal's why; a song not of the group: the first kept
    rows = copy_rows(e, 3, frozenset({1, 3}))
    assert [(r["song"], r["checked"], r["why"]) for r in rows] == [
        (3, False, ""), (1, True, ""), (2, False, "")
    ]  # fmt: skip
    assert copy_rows(e, 99, frozenset())[0]["song"] == 1
    assert copy_rows(entry_of(RIP, M4A, why=duplicates.FIRST), 2, frozenset())[0]["why"] == ""


def test_the_bar_the_question_and_the_message_name_what_goes():
    """L09's bar, R2.11's question (R6.8) and message: what goes, what the kept copy takes, and
    that Undo can't take files out of the trash."""
    assert bar_text(1) == "1 copy to the trash" and bar_text(3) == "3 copies to the trash"
    assert move_label(2) == "Move 2 to the trash"
    one = duplicates.Plan(FLAC, (RIP,), None, 55)
    q = question_of([one])
    assert q["title"] == "Move 1 song to the trash?" and q["yes"] == "Move to trash"
    assert q["detail"].startswith("Signal Fires.flac goes to the system's trash; the copy kept")
    assert "can't take files out of the trash" in q["detail"]
    two = question_of([one, duplicates.Plan(FLAC, (M4A, RIP), 4, 61)])
    assert two["title"] == "Move 3 songs to the trash?"
    assert two["detail"].startswith(
        "Signal Fires.flac, Moonpull (radio).m4a and Signal Fires.flac go to"
    ) and "the copies kept take" in two["detail"]  # fmt: skip
    assert names_text(["a", "b", "c", "d"]) == "a, b and 2 more" and names_text([]) == ""
    assert description_of([one], 1) == "Signal Fires: 1 copy to the trash"
    assert description_of([one, one], 3) == "3 copies of 2 songs to the trash"
    assert copies_app.footer_text(duplicates.Plan(RIP, (M4A,), None, 9)) == (
        "1 copy to the trash · the kept copy will have 9 plays and 4 stars · Undo can't take"
        " files out of the trash"
    )
    assert copies_app.footer_text(duplicates.Plan(M4A, (M4A,), None, 1)).startswith(
        "1 copy to the trash · the kept copy will have 1 play · "
    )
    assert moved_text(2, []) == (
        "Moved 2 songs to the trash. The copies kept have their plays and rating; Undo can't"
        " take files out of the trash"
    )
    assert moved_text(1, [("b.mp3", "couldn't be moved to the trash"), ("c", "x")]) == (
        "Moved 1 of 3 songs to the trash: b.mp3 couldn't be moved to the trash, and 1 more."
        " The copies kept have their plays and rating; Undo can't take files out of the trash"
    )
    assert moved_text(0, [("b.mp3", "isn't there any more")]) == (
        "Moved 0 of 1 song to the trash: b.mp3 isn't there any more"
    )
    assert moved_text(0, []) == "Nothing was moved to the trash"
    # what was done after the files went, when a step of it failed
    assert moved_text(1, [], listed=True) == (
        "Moved 1 song to the trash. It stays listed until the library's next scan. The copies"
        " kept have their plays and rating; Undo can't take files out of the trash"
    )
    assert moved_text(2, [], listed=True, plays=False) == (
        "Moved 2 songs to the trash. They stay listed until the library's next scan. The copies"
        " kept have their rating, but moving their plays to them failed; Undo can't take files"
        " out of the trash"
    )
    assert moved_text(2, [], rating=False) == (
        "Moved 2 songs to the trash. The copies kept have their plays, but writing their rating"
        " failed; Undo can't take files out of the trash"
    )
    assert moved_text(1, [], plays=False, rating=False) == (
        "Moved 1 song to the trash. Moving their plays to the copies kept and writing their"
        " rating failed; Undo can't take files out of the trash"
    )
    assert undone_text(Outcome(), "Signal Fires", in_trash=1) == (
        "Undone: Signal Fires; 1 file moved to the trash stays there"
    )
    assert undone_text(Outcome(), "x", in_trash=2).endswith("2 files moved to the trash stay there")


def test_needs_attention_lists_the_groups_of_copies_first_with_their_chip():
    """L09: "Same song twice" a chip of its own, first after All, its group a section with its
    heading and note; each group an entry with Review… and Ignore."""
    e = entry_of(FLAC, RIP)
    row = entry_row(e)
    assert (row["group"], row["title"], row["badge"], row["badgeTip"], row["icon"]) == (
        "copies", "Signal Fires", "Exact", "Exact copies: the same audio", "album"
    )  # fmt: skip
    assert [a["name"] for a in row["actions"]] == ["review", "ignore"]
    assert [(c["song"], c["checked"]) for c in row["copies"]] == [(1, False), (2, True)]
    assert entry_row(e, (2, frozenset({1})))["copies"][0]["song"] == 2
    group = group_row(BY["copies"], [e], True)
    assert group["detail"] == "SAME SONG MORE THAN ONCE" and group["copies"] == []
    assert group["summary"] == "1 song · Signal Fires"
    chips = chips_of({"copies": 3, "covers": 4}, "copies")
    assert [c["label"] for c in chips] == ["All  7", "Same song twice  3", "Covers  4"]
    assert rows_of([Entry("cover-none", "a"), e], "copies", ())[:2] == [
        ("group", "copies", -1), ("entry", "copies", 1)
    ]  # fmt: skip


# ---------- the choice, in Needs attention's list ----------


def model_of(entries):
    model = AttentionModel(lambda: None)
    model._found(model._generation, list(entries))
    model.choose("copies")
    return model


def test_a_groups_choice_is_kept_changed_by_its_rows_and_cleared(qapp):
    """R2.12: the copy kept changeable, a copy checked or not, the bar's count; a group found
    again keeps its choice while its copies are there."""
    exact, likely = entry_of(FLAC, RIP), entry_of(RIP, M4A, likely=True)
    likely = dataclasses.replace(likely, about="other")
    model = model_of([exact, likely])
    assert model.property("checkedCount") == 1 and model.property("barText") == (
        "1 copy to the trash"
    )
    row = next(i for i in range(model.rowCount()) if model.entry_at(i) is not None)
    model.toggleCopy(row, 2)
    assert model.property("checkedCount") == 0 and model.property("moveLabel") == (
        "Move 0 to the trash"
    )
    model.keepCopy(row, 2)  # its exact copy kept: the one kept before checked
    assert model.choice_of(exact) == (2, frozenset({1}))
    assert model.row(row)["copies"][0]["song"] == 2
    model.toggleCopy(row, 2)  # the copy kept is never checked
    model.toggleCopy(row, 99)
    model.keepCopy(-1, 1)
    model.toggleCopy(-1, 1)
    model.keep_copy("gone", 1)
    assert model.choice_of(exact) == (2, frozenset({1}))
    entries = [model.entry_at(i) for i in range(model.rowCount())]
    other = next(i for i, e in enumerate(entries) if e is not None and e.about == "other")
    model.toggleCopy(other, 3)
    assert [(a, [c.song for c in p.gone]) for a, p in model.checked_plans()] == [
        (exact.about, [1]), ("other", [3])
    ]  # fmt: skip
    model._found(model._generation, [exact, likely])  # found again: kept
    assert model.choice_of(exact) == (2, frozenset({1}))
    model._found(model._generation, [entry_of(FLAC, M4A, likely=True), likely])  # changed: anew
    assert model.choice_of(model.entry_of(exact.about)) == (1, frozenset())
    assert model.entry_titled("Signal Fires").about == exact.about
    assert model.entry_titled("Nothing") is None and model.entry_of("nothing") is None
    model.clearChecked()
    assert model.checked() == 0


# ---------- moving the others to the trash, and Undo ----------


def tag(path, artist, title, album=None):
    """The artist and title tagged; with `album`, the album artist, the album and track 4 too, so
    the tags match the path `Lumen Drift/<album>/04 - <title>` (R3.9)."""
    f = mutagen.wave.WAVE(str(path))
    if f.tags is None:
        f.add_tags()
    f.tags.add(mutagen.id3.TPE1(encoding=3, text=artist))
    f.tags.add(mutagen.id3.TIT2(encoding=3, text=title))
    if album:
        f.tags.add(mutagen.id3.TPE2(encoding=3, text=artist))
        f.tags.add(mutagen.id3.TALB(encoding=3, text=album))
        f.tags.add(mutagen.id3.TRCK(encoding=3, text="4"))
    f.save()


@pytest.fixture
def root(tmp_path):
    """Signal Fires filed and an exact copy of it, Moonpull filed and a likely copy of it, as
    WAVs scanned, rated (in ratings.json) and played on this computer: (root, index, paths). The
    filed ones' tags match their paths (R3.9)."""
    music = tmp_path / "Music"
    (music / ".musikata").mkdir(parents=True)
    paths = {
        "signal": music / "Lumen Drift" / "Glass Harbor" / "04 - Signal Fires.wav",
        "rip": music / "_Incoming" / "Signal Fires.wav",
        "moon": music / "Lumen Drift" / "Tide Tables" / "04 - Moonpull.wav",
        "radio": music / "_Incoming" / "Moonpull (radio).wav",
    }
    for name, seed, title in (("signal", 4, "Signal Fires"), ("rip", 4, "Signal Fires"),
                              ("moon", 5, "Moonpull"), ("radio", 6, "Moonpull")):  # fmt: skip
        wav(paths[name], seed)
        album = {"signal": "Glass Harbor", "moon": "Tide Tables"}.get(name)
        tag(paths[name], "Lumen Drift", title, album)
    index = db.Index(str(tmp_path / "musikata.db"))
    with ThreadPoolExecutor(1) as pool:
        scanner.scan(str(music), index, pool, hold=False)
    clock = FakeClock(NOW)
    w = ratings.Writing(str(music), index, write_file, True, clock)
    w(tags_core.Job(str(paths["rip"]), {"rating": 5}))
    w(tags_core.Job(str(paths["moon"]), {"rating": 2}))
    w(tags_core.Job(str(paths["radio"]), {"rating": 4}))
    ids = dict(index.read().execute("SELECT path, id FROM song"))
    rel = {k: scanner.path_under(str(music), str(p)) for k, p in paths.items()}

    def play(c):
        for name, n in (("signal", 5), ("rip", 2), ("moon", 3), ("radio", 4)):
            for _ in range(n):
                rootfiles.count(c, ME, ids[rel[name]], NOW)

    index.write(play).result()
    yield str(music), index, {k: str(p) for k, p in paths.items()}, rel, ids
    index.close()


def write_file(job):
    return tags_core.save(job.path, job.changes, audio_hash=scanner.audio_hash)


class Trash:
    """The system's trash, as a folder: a file moved there, or not when `refuse` names it."""

    def __init__(self, folder, refuse=()):
        self.folder, self.refuse, self.moved = folder, set(refuse), []

    def __call__(self, path):
        if os.path.basename(path) in self.refuse:
            return False
        os.makedirs(self.folder, exist_ok=True)
        shutil.move(path, os.path.join(self.folder, os.path.basename(path)))
        self.moved.append(path)
        return True


def plays_of(index):
    """Runs a change on this computer's rows (rootfiles.Keeping.change), on the index directly."""

    def change(fn):
        return index.write(lambda c: fn(c, ME))

    return change


def history_of(music, index, w):
    h = ChangeHistory(music, index, FakeClock(NOW), lambda: ME, ME, "Laptop", settings.RootTags(),
                      executor=ThreadPoolExecutor(1), watching=False, message_ms=60_000, write=w,
                      look=history.looking(w.kept))  # fmt: skip
    h.plays = copies_app.plays_back(plays_of(index), lambda: ME)
    return h


def test_moving_the_others_gives_the_kept_copy_their_plays_and_rating_in_one_entry(root, tmp_path):
    """R2.12: the copies checked go to the trash and out of the index; the kept copy takes their
    plays (summed, this computer's) and their highest rating when higher (as ratings are
    written: here ratings.json); one entry names the rating, the plays and the files moved."""
    music, index, paths, rel, ids = root
    found = {g.kept.title: g for g in duplicates.found(index.read())}
    signal, moon = found["Signal Fires"], found["Moonpull"]
    assert [c.path for c in signal.copies] == [rel["signal"], rel["rip"]]
    assert moon.likely and [c.path for c in moon.copies] == [rel["moon"], rel["radio"]]
    trash = Trash(str(tmp_path / "Trash"))
    clock = FakeClock(NOW)
    w = ratings.Writing(music, index, write_file, True, clock)
    rec = history.Recording(music, lambda: ME, clock)
    plans = [duplicates.plan(signal, ids[rel["signal"]], {ids[rel["rip"]]}),
             duplicates.plan(moon, ids[rel["moon"]], {ids[rel["radio"]]})]  # fmt: skip
    out = copies_app.move(music, plans, trash, copies_app.remover(music, index), w, rec,
                          plays_of(index))  # fmt: skip
    assert [c.path for c in out.trashed] == [rel["rip"], rel["radio"]] and out.failed == []
    assert out.plays == 6 and not os.path.exists(paths["rip"]) and os.path.exists(paths["signal"])
    c = index.read()
    assert {p for (p,) in c.execute("SELECT path FROM song")} == {rel["signal"], rel["moon"]}
    assert rootfiles.totals(c, [ids[rel["signal"]], ids[rel["moon"]]]) == {
        ids[rel["signal"]]: 7, ids[rel["moon"]]: 7
    }  # fmt: skip
    assert w.kept(paths["signal"]) == 5 and w.kept(paths["moon"]) == 4
    entry = history.read(history.folder_of(music), out.outcome.entry)
    assert (entry.action, entry.description) == ("copies", "2 copies of 2 songs to the trash")
    assert [(f.path, f.fields()) for f in entry.files] == [
        (rel["signal"], ["rating", "plays"]), (rel["rip"], ["trashed"]),
        (rel["moon"], ["rating", "plays"]), (rel["radio"], ["trashed"]),
    ]  # fmt: skip
    # nothing to move, or the history off: nothing kept
    assert copies_app.move(music, [], trash, lambda p: None, w, None).outcome.entry is None


def test_a_copy_that_cant_go_to_the_trash_stays_with_its_plays_and_rating(root, tmp_path):
    music, index, paths, rel, ids = root
    signal = next(g for g in duplicates.found(index.read()) if not g.likely)
    trash = Trash(str(tmp_path / "Trash"), refuse={"Signal Fires.wav"})
    w = ratings.Writing(music, index, write_file, True, FakeClock(NOW))
    gone = Copy(99, "_Incoming/gone.wav")
    plan = duplicates.Plan(signal.kept, (*signal.copies[1:], gone), 5, 0)
    out = copies_app.move(music, [plan], trash, copies_app.remover(music, index), w, None,
                          plays_of(index))  # fmt: skip
    assert out.trashed == [] and out.failed == [
        ("Signal Fires.wav", "couldn't be moved to the trash"), ("gone.wav", "isn't there any more")
    ]  # fmt: skip
    assert os.path.exists(paths["rip"]) and w.kept(paths["signal"]) == 0
    assert rootfiles.totals(index.read(), [ids[rel["signal"]]]) == {ids[rel["signal"]]: 5}


def ask_and_move(d, qtbot, about=None):
    d.move() if about is None else d.moveChecked()
    assert d.property("question")["title"]
    with qtbot.waitSignal(d.changed, timeout=WAIT, check_params_cb=lambda: not d.property(
            "moving")):  # fmt: skip
        d.answer(True)


def make(music, index, tmp_path, qtbot, available=lambda: True, **kw):
    w = ratings.Writing(music, index, write_file, True, FakeClock(NOW))
    h = history_of(music, index, w)
    model = AttentionModel(index.read)
    model.refresh()
    done = []
    d = Duplicates(music, model, w, copies_app.remover(music, index), h, plays=plays_of(index),
                   trash=Trash(str(tmp_path / "Trash")), done=lambda: done.append(1),
                   executor=ThreadPoolExecutor(1), available=available, **kw)  # fmt: skip
    d.model_, d.history_, d.done_, d.w_ = model, h, done, w
    return d


def test_review_asks_first_moves_and_undo_gives_back_the_plays_and_rating(root, tmp_path, qtbot):
    """R2.12, R2.11 through the bridge: Review… opens the group, its kept copy and checks
    changeable; Move asks first (Cancel moves nothing); the move's message offers Undo and says
    the files stay in the trash; Undo gives back the plays and the rating, and says so too."""
    music, index, paths, rel, ids = root
    d = make(music, index, tmp_path, qtbot)
    model, h = d.model_, d.history_
    try:
        moon = model.entry_titled("Moonpull")
        assert d.property("opened") is False and d.property("rows") == []
        assert (d.property("title"), d.property("about"), d.property("badge"),
                d.property("badgeTip")) == ("", "", "", "")  # fmt: skip
        d.open(moon)
        assert d.property("opened") and d.property("title") == "Copies of Moonpull"
        assert d.property("likely") and d.property("badge") == "Likely"
        assert d.property("badgeTip").startswith("Likely copies: ")
        assert d.property("about").startswith("Lumen Drift · 0:00. They share artist and title")
        assert [r["checked"] for r in d.property("rows")] == [False, False]  # likely: unchecked
        assert d.property("footer") == "Check the copies to move to the trash"
        assert d.property("moveLater") == "Nothing checked to move"
        d.move()  # nothing checked: nothing asked
        assert d.property("question") == {}
        d.toggle(ids[rel["radio"]])
        assert d.property("moveLabel") == "Move 1 to the trash" and d.property("moveLater") == ""
        assert d.property("footer") == (
            "1 copy to the trash · the kept copy will have 7 plays and 4 stars · Undo can't take"
            " files out of the trash"
        )
        d.move()
        assert d.property("question")["title"] == "Move 1 song to the trash?"
        d.close()  # Esc on the question: it closes, the dialog stays
        assert d.property("question") == {} and d.property("opened")
        d.move()
        d.answer(False)
        assert os.path.exists(paths["radio"]) and d.property("opened")
        d.keep(ids[rel["radio"]])  # the likely copy kept: the filed one isn't its exact copy
        d.keep(ids[rel["moon"]])
        d.toggle(ids[rel["radio"]])
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            ask_and_move(d, qtbot)
        assert not d.property("opened") and not os.path.exists(paths["radio"])
        assert h.property("message")["text"].endswith("Undo can't take files out of the trash")
        moon_id = ids[rel["moon"]]
        assert rootfiles.totals(index.read(), [moon_id]) == {moon_id: 7}
        assert d.w_.kept(paths["moon"]) == 4
        qtbot.waitUntil(lambda: index.read().execute("SELECT COUNT(*) FROM change").fetchone()[0]
                        == 1, timeout=WAIT)  # fmt: skip
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            h.undoMessage()
        qtbot.waitUntil(lambda: "Undone" in h.property("message").get("text", ""), timeout=WAIT)
        assert h.property("message")["text"] == (
            "Undone: Moonpull: 1 copy to the trash; 1 file moved to the trash stays there"
        )
        assert rootfiles.totals(index.read(), [moon_id]) == {moon_id: 3}
        assert d.w_.kept(paths["moon"]) == 2
        mine = {e.path: e.count for e in rootfiles.own(index.read(), ME)}
        assert mine[rel["radio"]] == 4  # waiting for its file to come back from the trash
        # Undo on the file in the trash alone: nothing to undo, and the message says why
        (name,) = [
            n for (n,) in index.read().execute("SELECT name FROM change WHERE undoes IS NULL")
        ]
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            h.undoFile(name, 1)
        assert h.property("message")["text"] == "Undo can't take files out of the trash"
        assert not h.property("busy")
    finally:
        d.shut()
        h.close()


def test_the_bars_move_takes_every_groups_checked_and_waits_for_the_root(root, tmp_path, qtbot):
    music, index, paths, rel, ids = root
    there = {"on": False}
    d = make(music, index, tmp_path, qtbot, available=lambda: there["on"])
    model, h = d.model_, d.history_
    try:
        assert model.checked() == 1  # the exact copy, checked at first
        d.moveChecked()  # the root isn't there: nothing asked, the message says why
        assert d.property("question") == {}
        assert h.property("message")["text"] == copies_app.NOT_THERE
        there["on"] = True
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            ask_and_move(d, qtbot, about="all")
        assert not os.path.exists(paths["rip"]) and os.path.exists(paths["radio"])
        assert d.done_ == [1]  # no rating written: the lists read again
        assert h.property("message")["text"].startswith("Moved 1 song to the trash")
        d.answer(True)  # no question open: nothing
        d.close()
        assert not d.property("opened")
    finally:
        d.shut()
        h.close()


def test_the_tour_opens_a_groups_review_and_its_question(root, tmp_path, qtbot):
    music, index, paths, rel, ids = root
    d = make(music, index, tmp_path, qtbot)
    try:
        d.go({"view": "attention", "review": "Signal Fires"})  # the group, not its question
        assert d.property("opened") and d.property("question") == {}
        d.go({"view": "attention", "review": "Signal Fires", "ask": True})
        assert d.property("opened") and d.property("question")["title"]
        d.go({"view": "albums"})
        assert not d.property("opened") and d.property("question") == {}
        d.go({"view": "attention", "review": "Nothing"})
        assert not d.property("opened")
        d.go({"view": "albums"})
    finally:
        d.shut()
        d.history_.close()
    assert not d._available()


class Held:
    """An executor that keeps the jobs it is given until `run` runs them, here."""

    def __init__(self):
        self.jobs = []

    def submit(self, fn):
        self.jobs.append(fn)

    def run(self):
        while self.jobs:
            self.jobs.pop(0)()

    def shutdown(self, wait=True):
        pass


def test_while_a_move_goes_on_the_dialog_says_so_and_one_that_moved_nothing_stays_open(
    root, tmp_path, qtbot
):
    """R2.12: the dialog says a move is going on and asks no other until it ends; a move that
    moved nothing leaves the dialog open on its copies; one that ends after the window closed
    changes nothing."""
    music, index, paths, rel, ids = root
    held = Held()
    w = ratings.Writing(music, index, write_file, True, FakeClock(NOW))
    h = history_of(music, index, w)
    model = AttentionModel(index.read)
    model.refresh()
    trash = Trash(str(tmp_path / "Trash"), refuse={"Signal Fires.wav"})
    d = Duplicates(music, model, w, copies_app.remover(music, index), h, plays=plays_of(index),
                   trash=trash, executor=held)  # fmt: skip
    try:
        d.keep(ids[rel["rip"]])  # no group open: nothing kept, checked or asked
        d.toggle(ids[rel["rip"]])
        d.move()
        assert d.property("question") == {} and model.checked() == 1
        d.open(model.entry_titled("Signal Fires"))
        d.move()
        d.answer(True)
        assert d.property("moving") and d.property("footer") == "Moving to the trash…"
        assert d.property("moveLater") == "A move is going on"
        d.move()  # another while it goes on: not asked
        assert d.property("question") == {}
        with qtbot.waitSignal(h.messageChanged, timeout=WAIT):
            held.run()
        assert d.property("opened") and not d.property("moving") and os.path.exists(paths["rip"])
        assert h.property("message")["text"] == (
            "Moved 0 of 1 song to the trash: Signal Fires.wav couldn't be moved to the trash"
        )
        d.move()
        d.answer(True)
        d.shut()  # the window closes before the move ends
        held.run()
        assert not d.property("moving") and d.property("opened")
    finally:
        d.shut()
        h.close()


def test_a_move_whose_rows_cant_be_taken_out_says_the_files_went_and_gives_the_rest(
    root, tmp_path, qtbot, caplog
):
    """The index failing after the files went to the trash: the message says they went and stay
    listed until the next scan (scanner.scan takes out the songs whose file is gone), and the
    copy kept still takes their plays and rating, in an entry Undo can reverse."""
    music, index, paths, rel, ids = root

    def broken(paths_):
        raise OSError("the index is gone")

    d = make(music, index, tmp_path, qtbot)
    d._remove = broken
    try:
        with qtbot.waitSignal(d.history_.messageChanged, timeout=WAIT):
            ask_and_move(d, qtbot, about="all")
        message = d.history_.property("message")
        assert message["text"] == (
            "Moved 1 song to the trash. It stays listed until the library's next scan. The copies"
            " kept have their plays and rating; Undo can't take files out of the trash"
        )
        assert message["undo"]
        assert "couldn't be taken out of the library" in caplog.text
        assert not os.path.exists(paths["rip"])
        c = index.read()
        assert c.execute("SELECT 1 FROM song WHERE path = ?", (rel["rip"],)).fetchone()
        signal = ids[rel["signal"]]
        assert rootfiles.totals(c, [signal]) == {signal: 7} and d.w_.kept(paths["signal"]) == 5
    finally:
        d.shut()
        d.history_.close()


def test_a_move_whose_plays_or_rating_fail_says_so_and_the_files_still_went(root, tmp_path):
    """Giving the plays failing (a job of rootfiles.Keeping that broke gives None; another way
    raises) and the rating not written: the files went all the same, and Moved says which steps
    didn't run, for the message."""
    music, index, paths, rel, ids = root
    exact, likely = sorted(duplicates.found(index.read()), key=lambda g: g.likely)
    trash = Trash(str(tmp_path / "Trash"))

    def broke(fn):
        done = Future()
        done.set_result(None)
        return done

    def raised(fn):
        done = Future()
        done.set_exception(OSError("the play counts are closed"))
        return done

    def refused(job):
        raise tags_core.WriteError(job.path, "it is read-only")

    w = ratings.Writing(music, index, write_file, True, FakeClock(NOW))
    remove = copies_app.remover(music, index)
    plan = duplicates.plan(likely, ids[rel["moon"]], {ids[rel["radio"]]})
    out = copies_app.move(music, [plan], trash, remove, refused, None, broke)
    assert [c.path for c in out.trashed] == [rel["radio"]] and not os.path.exists(paths["radio"])
    assert out.plays_left and out.plays == 0 and len(out.outcome.failed) == 1
    mine = {e.path: e.count for e in rootfiles.own(index.read(), ME)}
    assert (mine[rel["moon"]], mine[rel["radio"]]) == (3, 4)  # the plays where they were
    assert w.kept(paths["moon"]) == 2
    plan = duplicates.plan(exact, ids[rel["signal"]], {ids[rel["rip"]]})
    out = copies_app.move(music, [plan], trash, remove, w, None, raised)
    assert out.plays_left and not out.outcome.failed and w.kept(paths["signal"]) == 5
    assert not out.listed


def test_plays_are_given_back_only_for_this_computers_entries(root):
    music, index, paths, rel, ids = root
    back = copies_app.plays_back(plays_of(index), lambda: ME)
    assert back("another", []) == []
    assert copies_app.plays_back(None, lambda: ME)(ME, []) == []
    assert back(ME, []) == []


# ---------- in the window ----------


@pytest.fixture
def shell(root, tmp_path, qapp, qtbot):
    """MusiKata over the root's copies, scanned."""
    music, index, *_ = root
    index.close()
    env = {"MUSIKATA_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    s = app.load(music, env, FakeClock(datetime.now(UTC) - timedelta(minutes=1)),
                 lambda: ThreadPoolExecutor(1))  # fmt: skip
    s.library.rescan()
    qtbot.waitUntil(lambda: not s.library.scanning, timeout=WAIT * 3)
    s.window.show()
    yield s
    s.close()


def find(shell, name):
    found = []

    def walk(item):
        if item.objectName() == name and item.isVisible():
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(shell.window.contentItem())
    return found


def click(shell, item):
    at = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(shell.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0), at)


def settled(shell, qtbot):
    shell.window.grabWindow()
    qtbot.waitUntil(lambda: not tour.loading(shell.window.contentItem()), timeout=WAIT)
    shell.window.grabWindow()


@pytest.mark.slow
def test_the_groups_review_and_question_load_with_no_qml_warning_and_text_in_their_boxes(
    shell, qtbot, qtlog
):
    """L09's Same song twice in the window: the groups drawn whole with their rows, the bar,
    Review… opening its dialog and Move asking first; every text in its box."""
    lib = shell.library
    qtbot.waitUntil(lambda: lib.property("attentionCount") != "", timeout=WAIT)
    lib.show("attention")
    shell.attention.go({"view": "attention", "attention": "copies"})
    settled(shell, qtbot)
    assert len(find(shell, "copiesBadge")) == 2 and find(shell, "trashBar")
    assert len(find(shell, "keepCopy")) == 4
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "clearChecked")[0])  # Signal Fires' exact copy unchecked
    qtbot.waitUntil(lambda: not find(shell, "trashBar"), timeout=WAIT)
    click(shell, find(shell, "trashCopy")[0])  # Moonpull's likely copy checked
    qtbot.waitUntil(lambda: bool(find(shell, "trashBar")), timeout=WAIT)
    assert lib.property("attention").checked() == 1
    click(shell, find(shell, "attentionAction-review")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "reviewDialog")), timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "moveCopies")[0])
    qtbot.waitUntil(lambda: bool(find(shell, "copiesQuestion")), timeout=WAIT)
    settled(shell, qtbot)
    assert layout.faults(shell.window) == []
    click(shell, find(shell, "cancelQuestion")[0])
    qtbot.waitUntil(lambda: not find(shell, "copiesQuestion"), timeout=WAIT)
    click(shell, find(shell, "cancelReview")[0])
    qtbot.waitUntil(lambda: not find(shell, "reviewDialog"), timeout=WAIT)
    assert [r.message for r in qtlog.records if "qml" in r.message.lower()] == []
    json.dumps(shell.copies.property("rows"))  # plain data


def test_the_play_counts_change_this_computers_rows_through_their_keeping(root, qapp):
    """R2.12's plays moved run on the play counts' own thread, with this computer's key."""
    from musikata.plays import PlayCounts

    music, index, *_ = root
    keeping = rootfiles.Keeping(index, rootfiles.folder_of(music), FakeClock(NOW), ME)
    counts = PlayCounts(keeping, rootfiles.folder_of(music), FakeClock(NOW), watching=False)
    try:
        assert counts.change(lambda c, me: me).result() == ME
    finally:
        counts.close()


def test_the_playlists_naming_a_copy_moved_to_the_trash_are_pointed_at_the_copy_kept(
    root, tmp_path
):
    """R2.12, R8: every playlist naming a copy moved names the copy kept instead, in the same
    step (playlists.Store.repoint); one that fails is logged and the move stands."""
    music, index, paths, rel, ids = root
    exact = next(g for g in duplicates.found(index.read()) if not g.likely)
    os.makedirs(os.path.join(music, "Playlists"), exist_ok=True)
    with open(os.path.join(music, "Playlists", "Mix.m3u8"), "w", encoding="utf-8") as f:
        f.write(f"../{rel['rip']}\n../{rel['moon']}\n")
    store = playlists.Store(music, index)
    found = {"Playlists": [playlists.Found("Mix.m3u8", 1, 1)]}
    playlists.refresh(music, index, found, lambda folder: True)
    w = ratings.Writing(music, index, write_file, True, FakeClock(NOW))
    plan = duplicates.plan(exact, ids[rel["signal"]], {ids[rel["rip"]]})
    remove, trash = copies_app.remover(music, index), Trash(str(tmp_path / "Trash"))
    out = copies_app.move(music, [plan], trash, remove, w, None, repoint=store.repoint)
    assert [c.path for c in out.trashed] == [rel["rip"]]
    named = [p for (p,) in index.read().execute(
        "SELECT path FROM playlist_entry ORDER BY position")]  # fmt: skip
    assert named == [rel["signal"], rel["moon"]]

    def broken(moves):
        raise OSError("the playlists folder can't be written")

    likely = next(g for g in duplicates.found(index.read()) if g.likely)
    plan = duplicates.plan(likely, ids[rel["moon"]], {ids[rel["radio"]]})
    out = copies_app.move(music, [plan], trash, remove, w, None, repoint=broken)
    assert [c.path for c in out.trashed] == [rel["radio"]]
