"""Starting MusiKata: the options, the root (R2.1: given for the run, or the configured one, or
chosen at the first start), its index (A2.9), the window, the first scan; `--tour DIR` drives it
through the screens instead (A1.6), and `--play FILE` plays one file to its end and quits, which is
how each build is started once to test it (build-and-release.md, "The builds"). One MusiKata at a
time and opening files (R1.6, R1.7) come with the slices that need them (DEVELOP.md).

A run is a `Session`: the first start's window (firstrun.py) until a root is chosen, then the
window over the root; a root chosen again (Choose another folder…, R2.10) opens in its place. The
first root opened starts the cleanup of A2.9 on a thread of its own. Each root opens with what was
playing when it last closed, cued (R1.8), but for the tour, whose screens are the same every run."""

from __future__ import annotations

import argparse
import functools
import gc
import logging
import os
import platform
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from shiboken6 import Shiboken

from musikata_core import __version__, db, history, nowplaying, rootfiles, roots, settings, workers
from musikata_core import folders as index_folders
from musikata_core import playlists as index_playlists
from musikata_core.audio.decode import DecodeError
from musikata_core.clock import Clock, SystemClock
from musikata_core.ratings import Writing, set_everything

from . import garbage, media
from .albumart import AlbumArt, ArtImages
from .attention import Attention, NameMerge
from .bridges import Library, Player
from .covers import Covers, trim_cache
from .dragging import Dragging
from .duplicates import Duplicates, plays_back, remover
from .edittags import EditTags
from .encodings import FixEncoding
from .firstrun import FirstRun, music_folder
from .genres import Genres
from .history import ChangeHistory
from .infer import InferFromPath
from .player import FALLBACK_RATE, NO_DEVICE, DecodedSong, Engine, Opener
from .playlists import Playlists
from .plays import PlayCounts
from .ratings import Ratings, file_writer

QML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml", "Main.qml")
FIRST_QML = os.path.join(os.path.dirname(QML), "FirstRun.qml")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Options:
    root: str | None = None  # --root: the root for this run only (R2.1.2)
    tour: str | None = None
    tour_only: str = ""
    play: str | None = None


def home_of(env: Mapping[str, str]) -> str:
    return env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")


def computer_name() -> str:
    """This computer's name, for display beside its id (A2.8)."""
    return platform.node() or "this computer"


def options(argv: Sequence[str], env: Mapping[str, str]) -> Options:
    """The command line: --root, the music root for this run only (R2.1.2), else None, the
    configured root (`root_for`)."""
    ap = argparse.ArgumentParser(prog="musikata", description="A music player and organizer")
    ap.add_argument(
        "--root", help="the music root for this run only, the one configured left as it is"
    )
    ap.add_argument("--tour", metavar="DIR", help="save each screen to DIR and check its layout")
    ap.add_argument("--tour-only", metavar="NAMES", default="", help="those screens, by name")
    ap.add_argument(
        "--play",
        metavar="FILE",
        help="play FILE to its end and quit: 0 when it played and the scan went well, 3 when"
        " there was no sound device and it decoded instead",
    )
    ap.add_argument("--version", action="version", version=f"MusiKata {__version__}")
    a = ap.parse_args(list(argv))
    root = os.path.abspath(os.path.expanduser(a.root)) if a.root else None
    play = os.path.abspath(os.path.expanduser(a.play)) if a.play else None
    return Options(root, a.tour, a.tour_only, play)


def root_for(opts: Options, configured: str | None) -> tuple[str | None, bool]:
    """The root a run opens, and whether it is for this run only (R2.1.2): --root, else the
    configured root (R2.1), else for --play the file's own folder (a build's start test needs no
    first start), else None: the first start asks for one."""
    if opts.root is not None:
        return opts.root, True
    if configured is not None:
        return configured, False
    if opts.play is not None:
        return os.path.dirname(opts.play), True
    return None, False


def key_of(index: db.Index) -> str:
    """The key the root's index and caches are kept under (A2.9): its index's folder's name."""
    return os.path.basename(os.path.dirname(index.path))


def cache_of(index: db.Index, env: Mapping[str, str]) -> str:
    """Where the root's cover thumbnails are kept: its caches (R1.5), under its index's key."""
    return os.path.join(roots.caches_dir(env), key_of(index), "covers")


def remove_stale(env: Mapping[str, str], clock: Clock, keep: str) -> list[str]:
    """Removes the index and caches of every root not opened for 180 days but the one under
    `keep`, the root being opened (A2.9; roots.remove_stale, which logs each)."""
    return roots.remove_stale(roots.roots_dir(env), clock, keep, roots.caches_dir(env))


def open_index(root: str, env: Mapping[str, str], clock: Clock) -> db.Index:
    """The root's index, found or made where A2.9 says. A root that isn't there (R2.10) is shown
    from the index that last opened it, found by its path, and nothing is made in its place; one
    never opened gets an empty index under a hash of its path."""
    base = roots.roots_dir(env)
    if os.path.isdir(root):
        found = roots.find_index(root, base, clock)
    else:
        found = roots.recorded(root, base) or roots.Found(
            os.path.join(base, roots.path_key(root)), roots.path_key(root), False
        )
        os.makedirs(found.folder, exist_ok=True)
    return db.Index(os.path.join(found.folder, "musikata.db"))


@dataclass
class Shell:
    """What a running MusiKata holds: the engine, its window, the bridges and the system's media
    controls."""

    engine: QQmlApplicationEngine
    window: QQuickWindow
    library: Library
    player: Player
    index: db.Index
    controls: media.MediaControls
    counts: PlayCounts | None = None
    changes: ChangeHistory | None = None
    edit: EditTags | None = None
    ratings: Ratings | None = None
    art: AlbumArt | None = None
    genres: Genres | None = None
    attention: Attention | None = None
    names: NameMerge | None = None
    copies: Duplicates | None = None
    encodings: FixEncoding | None = None
    infer: InferFromPath | None = None
    playlists: Playlists | None = None
    dragging: Dragging | None = None

    def close(self) -> None:
        """The window and its engine first, while what they bind to is still there; then the
        system's media controls and the bridges (`close_bridges`)."""
        self.window.close()
        Shiboken.delete(self.engine)
        close_bridges(
            self.player, self.counts, self.library, self.index, self.controls, self.changes,
            self.edit, self.ratings, self.art, self.genres, self.attention, self.names,
            self.copies, self.encodings, self.infer, self.playlists, self.dragging,
        )  # fmt: skip


def close_bridges(
    player: Player,
    counts: PlayCounts | None,
    library: Library,
    index: db.Index,
    controls: media.MediaControls | None = None,
    changes: ChangeHistory | None = None,
    edit: EditTags | None = None,
    ratings: Ratings | None = None,
    art: AlbumArt | None = None,
    genres: Genres | None = None,
    attention: Attention | None = None,
    names: NameMerge | None = None,
    copies: Duplicates | None = None,
    encodings: FixEncoding | None = None,
    infer: InferFromPath | None = None,
    playlists: Playlists | None = None,
    dragging: Dragging | None = None,
) -> None:
    """Closes what a window bound to, once it has gone: the system's media controls, the
    playback thread, the Edit tags panel's, Album art's, the merges', Fix encoding…'s and Infer
    from path's saves (stopped before their next file) and threads, the playlists' changes (an
    export stopped), Needs attention's dismissals
    and watching, the ratings' save and watching, the play counts (their file written), the change
    history's thread, the watcher, the scan's thread and the worker processes, and the index; then
    deletes them (`release`)."""
    if controls is not None:
        controls.close()
    player.close()
    if edit is not None:
        edit.close()
    if art is not None:
        art.shut()
    if genres is not None:
        genres.shut()
    if names is not None:
        names.shut()
    if copies is not None:
        copies.shut()
    if encodings is not None:
        encodings.shut()
    if infer is not None:
        infer.shut()
    if playlists is not None:
        playlists.shut()
    if dragging is not None:
        dragging.close()
    if attention is not None:
        attention.close()
    if ratings is not None:
        ratings.close()
    if counts is not None:
        counts.close()
    if changes is not None:
        changes.close()
    library.close()
    index.close()
    release(
        controls, counts, edit, art, genres, names, copies, encodings, infer, playlists, dragging,
        attention, ratings, changes, player, library,
    )  # fmt: skip


def release(*objects: QObject | None) -> None:
    """Deletes a closed window's QObjects (each with its children: the models, the pages, the
    watchers and their timers) here, on the GUI thread, at once, whatever still refers to them:
    never by a garbage collection on another thread while this one delivers them an event (A1.3).
    At once, not later (deleteLater): each has closed, its threads ended, and it is deleted from
    a queued call or after the event loop has ended, never from inside its own signal."""
    for o in objects:
        if o is not None and Shiboken.isValid(o):
            Shiboken.delete(o)


def load(
    root: str,
    env: Mapping[str, str],
    clock: Clock,
    pool: Callable[[], Executor] = workers.pool,
    playback: Callable[[], Engine] = Engine,
    given: bool = False,
    controls: Callable[[Player, QQuickWindow, media.Art], media.MediaControls] = media.start,
    keep: bool = True,
) -> Shell:
    """The window over the root's index, not yet shown, the root watched once scanned (A2.4).
    `playback` makes the playback thread's engine (a test's plays generated audio on a device it
    chooses). `given`: the root is for this run only, and the window's title names it (R2.1.2).
    A root that isn't there opens with its library as it was (R2.10). `controls` starts the
    system's media controls over the player, the window and the cover cache (A4.5). `keep`: what
    was playing comes back, cued, and is kept from now on (R1.8, `keep_playing`)."""
    index = open_index(root, env, clock)
    missing = not os.path.isdir(root)
    # the root's Tags settings (R13.3): the history's, and what a save writes with (R4.7.1, R4.7.2)
    tags_settings = settings.root_tags(root) if not missing else settings.RootTags()
    # the user's own path patterns (R3.3), which tags match path is worked out with (R3.9)
    user = tags_settings.patterns
    index.write(lambda c: index_folders.set_user_patterns(c, user)).result()
    cache = cache_of(index, env)
    library = Library(
        root, index, home_of(env), pool, clock=clock, watching=True, missing=missing, given=given,
        trim=functools.partial(trim_cache, cache),
    )  # fmt: skip
    shared = settings.load(settings.shared_path(env), home_of(env))  # Playback's (R13.7)
    player = Player(
        root,
        playback(),
        refuse=library.unplayable,
        read=index.read,
        playback=shared.playback,
        clock=clock,
    )
    player.nowPlaying.connect(library.show_playing)
    library.reachChanged.connect(
        player.reach_changed
    )  # the song playing ends, nothing after (R2.10)
    library.property("folders").play.connect(player.play_songs)
    counts = None
    make = Once(
        functools.partial(
            settings.computer_id, settings.shared_path(env), home_of(env), computer_name()
        )
    )
    if keep:
        keep_playing(player, root, index, shared, env, clock, make)
        counts = count_plays(player, library, root, index, shared, clock, make)
    # where each rating goes (R10.3, R10.4): its file, or ratings.json, as the root's settings say
    index.write(lambda c: set_everything(c, not tags_settings.write_ratings))
    writing = Writing(root, index, file_writer(tags_settings), tags_settings.write_ratings, clock)
    changes = keep_history(
        library, root, index, shared, clock, make, missing, tags_settings, writing
    )
    # Fix encoding… (R4.10), from Needs attention and the Edit tags panel
    fix = FixEncoding(
        root, index.read, writing, changes, saved=library.saved, undoable=tags_settings.history,
        available=lambda: bool(library.property("available")), model=library.property("attention"),
    )  # fmt: skip
    # Infer from path (R3): from Folders, the selection bars, an album, the panel, Needs attention
    infer = InferFromPath(
        root, index.read, writing, changes, saved=library.saved, undoable=tags_settings.history,
        available=lambda: bool(library.property("available")), home=home_of(env),
    )  # fmt: skip
    edit = EditTags(
        root, index.read, tags_settings, changes, saved=library.saved, write=writing,
        home=home_of(env), available=lambda: bool(library.property("available")), encodings=fix,
        infer=infer,
    )  # fmt: skip
    library.reloaded.connect(edit.refresh)  # a scan, a save or an undo changed the rows
    rating = rate_songs(library, player, root, index, writing, changes, clock, missing)
    engine = QQmlApplicationEngine()
    covers = Covers(root, index.read, cache)
    engine.addImageProvider("covers", covers)
    thumbs = ArtImages()
    engine.addImageProvider("albumart", thumbs)
    album_art = AlbumArt(
        root, index.read, writing, changes, saved=library.saved, images=thumbs,
        available=lambda: bool(library.property("available")),
    )  # fmt: skip
    genre_tools = Genres(
        root, index.read, writing, changes, saved=library.saved, same=tags_settings.same_genres,
        undoable=tags_settings.history, available=lambda: bool(library.property("available")),
    )  # fmt: skip
    library.reloaded.connect(genre_tools.refresh)  # R9.5's banner, after a scan or a save
    genre_tools.refresh()
    changes.plays = plays_back(counts.change if counts is not None else None, make)  # R2.12
    # playlists (R8): made in the root's playlists folder (R13.6), changed through the store
    store = index_playlists.Store(
        root, index, settings.root_playlists(root) if not missing else index_playlists.FOLDER
    )
    lists = Playlists(
        store, library, index.read, say=changes.say, offer=changes.offer,
        available=lambda: bool(library.property("available")), home=home_of(env),
    )  # fmt: skip
    # drag and drop (R6.10, R8.5): onto playlists through `lists`, onto the queue through `player`
    dragging = Dragging(root, index.read, library, lists, player, say=changes.say)
    needs, names, copies = attend(
        library, root, index, clock, edit, album_art, genre_tools, writing, changes, tags_settings,
        missing, counts, fix, infer, lists, store,
    )  # fmt: skip
    engine.setInitialProperties(
        {
            "library": library,
            "player": player,
            "history": changes,
            "edit": edit,
            "ratings": rating,
            "art": album_art,
            "genres": genre_tools,
            "attention": needs,
            "names": names,
            "copies": copies,
            "encodings": fix,
            "infer": infer,
            "playlists": lists,
            "dragging": dragging,
        }  # fmt: skip
    )
    engine.load(QUrl.fromLocalFile(QML))
    objects = engine.rootObjects()
    if not objects or not isinstance(objects[0], QQuickWindow):
        Shiboken.delete(engine)
        # none left for a collection (A1.3)
        close_bridges(player, counts, library, index, changes=changes, edit=edit, ratings=rating,
                      art=album_art, genres=genre_tools, attention=needs, names=names,
                      copies=copies, encodings=fix, infer=infer, playlists=lists,
                      dragging=dragging)  # fmt: skip
        raise RuntimeError(f"{QML} didn't load")
    window = objects[0]
    # where the root can't be watched, gaining focus rescans it (R2.4)
    window.activeChanged.connect(lambda: library.window_active(window.isActive()))
    return Shell(
        engine, window, library, player, index, controls(player, window, covers.file), counts,
        changes, edit, rating, album_art, genre_tools, needs, names, copies, fix, infer, lists,
        dragging,
    )  # fmt: skip


def attend(
    library: Library,
    root: str,
    index: db.Index,
    clock: Clock,
    edit: EditTags,
    art: AlbumArt,
    genres: Genres,
    writing: Writing,
    changes: ChangeHistory,
    tags_settings: settings.RootTags,
    missing: bool = False,
    counts: PlayCounts | None = None,
    fix: FixEncoding | None = None,
    infer: InferFromPath | None = None,
    lists: Playlists | None = None,
    store: index_playlists.Store | None = None,
) -> tuple[Attention, NameMerge, Duplicates]:
    """Needs attention (R2.8): its list (Library's) told the genres the user has said are the
    same (R9.5); its actions on the Edit tags panel, Album art, the genres' merge and the merge of
    an artist's or an album's names (saved by `writing`, kept in `changes`), and Review… and Move
    the others to the trash for the same song more than once (R2.12: the kept copy's rating
    written by `writing`, its plays given on `counts`' rows, kept in `changes`), and Fix
    encoding… on `fix` (R4.10), Infer from path on `infer` (R3), and Find on `lists` (R8.7), the
    playlists naming a copy moved pointed at the copy kept through `store` (R2.12); the root's
    ignored.json read into the index, off the GUI thread, and again when another computer changes
    it (A2.8). A root that isn't there (R2.10) lists what the index has."""
    model = library.property("attention")
    model.same = [tuple(g) for g in tags_settings.same_genres]
    names = NameMerge(
        root, index.read, writing, changes, saved=library.saved, undoable=tags_settings.history,
        available=lambda: bool(library.property("available")),
    )  # fmt: skip
    copies = Duplicates(
        root, model, writing, remover(root, index), changes,
        plays=counts.change if counts is not None else None, done=library.reload,
        saved=library.saved, available=lambda: bool(library.property("available")),
        repoint=store.repoint if store is not None else None,
    )  # fmt: skip
    needs = Attention(root, index, model, clock, edit=edit, art=art, genres=genres, names=names,
                      history=changes, copies=copies, encoding=fix, infer=infer,
                      playlists=lists, watching=not missing)  # fmt: skip
    if not missing:
        needs.start()
    else:
        model.refresh()
    return needs, names, copies


def keep_playing(
    player: Player,
    root: str,
    index: db.Index,
    shared: settings.Shared,
    env: Mapping[str, str],
    clock: Clock,
    make: Callable[[], str | None] | None = None,
) -> None:
    """What was playing when the root last closed on this computer comes back in `player`,
    cued (R1.8), its songs found in the index by path or hash; and from now on it is kept in the
    root's `.musikata/<computer id>/now-playing.json`, or beside the index when that can't be
    written (R1.5.2, A2.8). Read here, before the window shows, as the shared settings are."""
    where = nowplaying.places(root, os.path.dirname(index.path), shared.computer_id)
    kept = nowplaying.load(where)
    state, dropped = nowplaying.restore(kept, nowplaying.finder(index.read()))
    if dropped:
        log.info("%d songs of the queue kept are no longer in the library", dropped)
    player.restore(state)
    path, home, name = settings.shared_path(env), home_of(env), computer_name()
    player.keep(
        nowplaying.Keeping(
            where,
            index.read,
            clock,
            kept,
            computer=make or functools.partial(settings.computer_id, path, home, name),
            set_playback=functools.partial(settings.set_playback, path, home, name),
        )
    )


class Once:
    """`make` called once, whichever thread asks first, its answer given to every other: this
    computer's id (A2.8), which what's playing and the play counts each make when they first
    need it, on threads of their own, must be the same one. An answer of None (it couldn't be
    kept) is asked for again next time."""

    def __init__(self, make: Callable[[], str | None]) -> None:
        self._make = make
        self._lock = threading.Lock()
        self._made: str | None = None

    def __call__(self) -> str | None:
        with self._lock:
            if self._made is None:
                self._made = self._make()
            return self._made


def count_plays(
    player: Player,
    library: Library,
    root: str,
    index: db.Index,
    shared: settings.Shared,
    clock: Clock,
    make: Callable[[], str | None],
) -> PlayCounts:
    """From now on the songs `player` plays are counted (R7.9) and kept in the index and the
    root's `.musikata/<computer id>/plays.json` (A2.8); every computer's plays file is read into
    the index, off the GUI thread, and the others' read again when they change. The lists show
    the counts anew each time they change, and a scan that moves songs has this computer's file
    name them where they are. `make` makes this computer's id when it has none (`Once`)."""
    keeping = rootfiles.Keeping(
        index,
        rootfiles.folder_of(root),
        clock,
        shared.computer_id,
        make=make,
        name=shared.computer_name or computer_name(),
    )
    counts = PlayCounts(keeping, rootfiles.folder_of(root), clock, watching=os.path.isdir(root))
    counts.changed.connect(library.plays_changed)
    library.songsMoved.connect(counts.moved)
    player.count(counts)
    counts.start()
    return counts


def keep_history(
    library: Library,
    root: str,
    index: db.Index,
    shared: settings.Shared,
    clock: Clock,
    make: Callable[[], str | None],
    missing: bool = False,
    tags_settings: settings.RootTags | None = None,
    writing: Writing | None = None,
) -> ChangeHistory:
    """The root's change history (R4.9, A3.5): its entries past their age removed and the rest
    read into the index, off the GUI thread, and read again when another computer adds one; the
    files an undo writes have their rows updated (Library.saved). `make` makes this computer's id
    when it has none (`Once`). A root that isn't there (R2.10) lists what the index has.
    `tags_settings`: the root's (settings.root_tags), read here when not given. `writing` writes
    an undo's files, each rating where it is kept (R10.3), and says what a rating is now."""
    changes = ChangeHistory(
        root,
        index,
        clock,
        make,
        shared.computer_id,
        shared.computer_name or computer_name(),
        tags_settings or (settings.root_tags(root) if not missing else settings.RootTags()),
        saved=library.saved,
        watching=not missing,
        write=writing,
        look=history.looking(writing.kept) if writing is not None else None,
        available=lambda: bool(library.property("available")),
    )
    if not missing:
        changes.start()
    else:
        changes.reload()
    return changes


def rate_songs(
    library: Library,
    player: Player,
    root: str,
    index: db.Index,
    writing: Writing,
    changes: ChangeHistory,
    clock: Clock,
    missing: bool = False,
) -> Ratings:
    """Rating songs (R10.2) from the lists, the bar and the keys, each save written by `writing`
    and kept in the change history; the ratings being saved shown at once in the lists and the
    bar; the root's ratings.json read into the index, off the GUI thread, and again when another
    computer changes it (R10.3, A2.8), the lists reading their rows again then. A root that isn't
    there (R2.10) rates nothing, saying why."""
    rating = Ratings(
        root, index, writing, changes, clock, saved=library.saved,
        available=lambda: bool(library.property("available")), watching=not missing,
    )  # fmt: skip
    rating.shownChanged.connect(library.show_ratings)
    rating.shownChanged.connect(player.show_ratings)
    rating.changed.connect(library.ratings_changed)
    library.reloaded.connect(rating.reloaded)
    library.reloaded.connect(player.reread)
    if not missing:
        rating.start()
    return rating


@dataclass
class FirstStart:
    """The first start's window (X01-first-run) and what it binds to."""

    engine: QQmlApplicationEngine
    window: QQuickWindow
    first: FirstRun

    def close(self) -> None:
        self.window.close()
        Shiboken.delete(self.engine)
        release(self.first)


def first_start(env: Mapping[str, str]) -> FirstStart:
    """The first start's window, not yet shown: it asks for the root (R2.1)."""
    first = FirstRun(music_folder(home_of(env)), home_of(env))
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"first": first})
    engine.load(QUrl.fromLocalFile(FIRST_QML))
    objects = engine.rootObjects()
    if not objects or not isinstance(objects[0], QQuickWindow):
        raise RuntimeError(f"{FIRST_QML} didn't load")
    return FirstStart(engine, objects[0], first)


def place_like(window: QQuickWindow, old: QQuickWindow) -> None:
    """Gives `window` the place, size and state (maximized, full screen) of `old`, which it takes
    the place of, and shows it if `old` showed."""
    window.setGeometry(old.geometry())
    if old.isVisible():
        window.setVisibility(old.visibility())


class Session(QObject):
    """A run (R2.1): the first start's window while no root is configured, then the window over
    the root. A root chosen there, or chosen again with Choose another folder… (R2.10), becomes the
    configured root, unless the run's root was given for it only (R2.1.2), and opens in the
    window's place, its library scanned; the one before closes. `opened` says a root opened.
    Once the first root is open, the roots not opened for 180 days are removed, but that one, on
    the cleanup's thread (A2.9), which closing waits for. A window closed, its objects deleted,
    `collect` collects the garbage it may have left (garbage.Collector.full, A1.3)."""

    opened = Signal()

    def __init__(
        self,
        env: Mapping[str, str],
        clock: Clock,
        given: bool = False,
        pool: Callable[[], Executor] = workers.pool,
        playback: Callable[[], Engine] = Engine,
        controls: Callable[[Player, QQuickWindow, media.Art], media.MediaControls] = media.start,
        keep: bool = True,
        collect: Callable[[], object] = gc.collect,
    ) -> None:
        super().__init__()
        self._env, self._clock, self.given = env, clock, given
        self._pool, self._playback, self._controls = pool, playback, controls
        self._keep, self._collect = keep, collect
        self.shell: Shell | None = None
        self.first: FirstStart | None = None
        self._cleanup: threading.Thread | None = None  # A2.9's, once the first root opened

    @property
    def window(self) -> QQuickWindow:
        """The window this run shows now."""
        if self.shell is not None:
            return self.shell.window
        assert self.first is not None, "the session hasn't started"
        return self.first.window

    @property
    def library(self) -> Library | None:
        """The open root's library; None at the first start, before one is chosen."""
        return self.shell.library if self.shell is not None else None

    def start(self, root: str | None) -> None:
        """Opens `root` and scans it, or, with None, asks for one (the first start)."""
        if root is None:
            self.first = first_start(self._env)
            self.first.first.chosen.connect(self.choose, Qt.ConnectionType.QueuedConnection)
            return
        self._open(root)

    def _open(self, root: str) -> Shell:
        shell = load(
            root,
            self._env,
            self._clock,
            self._pool,
            self._playback,
            self.given,
            self._controls,
            self._keep,
        )
        shell.library.rootChosen.connect(self.choose, Qt.ConnectionType.QueuedConnection)
        self.shell = shell
        shell.library.rescan()
        if self._cleanup is None:  # its index opened now, or kept as `keep` when it isn't there
            self._cleanup = threading.Thread(
                target=remove_stale,
                args=(self._env, self._clock, key_of(shell.index)),
                name="cleanup",
                daemon=True,
            )
            self._cleanup.start()
        return shell

    def choose(self, root: str) -> None:
        """A root chosen (R2.1, R2.10): kept as the configured root, unless the run's was given
        for it only, and opened in the window's place."""
        if not self.given:
            path, home = settings.shared_path(self._env), home_of(self._env)
            settings.choose_root(path, home, root, computer_name())
        old_window = self.window
        old: Shell | FirstStart | None = self.shell or self.first
        if self.shell is not None:  # the system's controls go to the new window, by MPRIS's name
            self.shell.controls.close()
        self.first = None
        shell = self._open(root)
        place_like(shell.window, old_window)
        if old is not None:
            old.close()
            del old
            self._collect()
        self.opened.emit()

    def close(self) -> None:
        if self.shell is not None:
            self.shell.close()
        if self.first is not None:
            self.first.close()
        if self._cleanup is not None:
            self._cleanup.join()
        self._collect()


NO_DEVICE_STATUS = 3  # --play's status when the file decoded to its end with no device to play on


def outcome(last: str, error: str, scan: object, decoded: float | None = None) -> tuple[int, str]:
    """What `--play` ends with: its exit status and the line saying why, from how the song stopped
    (the Player bridge's `last`: "ended", "stopped", "failed" or "" when it never began), why it
    failed, the seconds it decoded when there was no sound device (None when it didn't try), and
    the scan's outcome (a Result, the exception it raised, or None). 0 only when the song played to
    its end and the scan went well; NO_DEVICE_STATUS when, with no sound device, it decoded to its
    end instead, as on a machine with no sound card that a build's start test runs on."""
    if isinstance(scan, BaseException):
        return 1, f"the scan failed: {type(scan).__name__}: {scan}"
    if last == "ended":
        return 0, "played to its end"
    if last == "failed" and error == NO_DEVICE and decoded is not None:
        return NO_DEVICE_STATUS, f"decoded to its end ({decoded:.1f} s); {NO_DEVICE} to play it on"
    if last == "failed":
        return 1, f"couldn't play: {error}"
    return 1, "closed before the song ended"


def decode_through(path: str, opener: Opener = DecodedSong) -> float:
    """Decodes the file at `path` to its end, as playing it would, in stereo; the seconds it
    held. Raises DecodeError when it can't."""
    song = opener(path, FALLBACK_RATE, 2)
    try:
        return sum(len(block) for block in song.blocks(4096)) / song.rate
    finally:
        song.close()


class PlayOnce:
    """`--play FILE`: plays the file and calls `done` when it has stopped, played to its end or
    not. `last` and `error` then say how. With no sound device it decodes the file instead, and
    `decoded` holds the seconds it held."""

    def __init__(
        self, player: Player, path: str, done: Callable[[], None], opener: Opener = DecodedSong
    ) -> None:
        self._player, self._path, self._done, self._opener = player, path, done, opener
        self.last = self.error = ""
        self.decoded: float | None = None
        player.nowPlaying.connect(self._on_now_playing)
        player.play_file(path)

    def _on_now_playing(self, path: str) -> None:
        if path:  # it began
            return
        self.last, self.error = self._player.last, self._player.property("error")
        if self.last == "failed" and self.error == NO_DEVICE:
            try:
                self.decoded = decode_through(self._path, self._opener)
            except DecodeError as e:
                self.error = f"{NO_DEVICE}, and {e}"
        self._done()


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("MUSIKATA_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    opts = options(sys.argv[1:] if argv is None else argv, os.environ)
    app = QGuiApplication(sys.argv[:1])
    collector = garbage.start(app, SystemClock())  # before any thread starts (A1.3)
    app.setApplicationName("MusiKata")
    app.setApplicationVersion(__version__)
    configured = settings.load(settings.shared_path(os.environ), home_of(os.environ)).root
    root, given = root_for(opts, configured)
    session = Session(os.environ, SystemClock(), given, keep=not opts.tour, collect=collector.full)
    session.start(root)
    once = None
    if opts.tour:
        from .tour import Tour

        player = session.shell.player if session.shell is not None else None
        changes = session.shell.changes if session.shell is not None else None
        edit = session.shell.edit if session.shell is not None else None
        album_art = session.shell.art if session.shell is not None else None
        genre_tools = session.shell.genres if session.shell is not None else None
        needs = session.shell.attention if session.shell is not None else None
        copies = session.shell.copies if session.shell is not None else None
        fix = session.shell.encodings if session.shell is not None else None
        infer = session.shell.infer if session.shell is not None else None
        dragging = session.shell.dragging if session.shell is not None else None
        Tour(
            session.window, session.library, opts.tour, opts.tour_only, player=player,
            history=changes, edit=edit, art=album_art, genres=genre_tools, attention=needs,
            copies=copies, encodings=fix, infer=infer, dragging=dragging,
        ).start()  # fmt: skip
    else:
        session.window.show()
        if opts.play and session.shell is not None:
            once = PlayOnce(session.shell.player, opts.play, app.quit)
    code = app.exec()
    last = session.library.last if session.library is not None else None
    session.close()
    if once is not None:
        code, why = outcome(once.last, once.error, last, once.decoded)
        print(f"{opts.play}: {why}", flush=True)
    return code
