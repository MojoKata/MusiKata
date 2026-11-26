"""Starting MusiKata: the options, the root's index (A2.9), the window, the first scan; `--tour DIR`
drives it through the screens instead (A1.6). One MusiKata at a time and opening files (R1.6, R1.7)
come with the slices that need them (DEVELOP.md)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from shiboken6 import Shiboken

from musikata_core import __version__, db, roots, workers
from musikata_core.clock import Clock, SystemClock

from .bridges import Library

QML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml", "Main.qml")


@dataclass(frozen=True)
class Options:
    root: str
    tour: str | None = None
    tour_only: str = ""


def home_of(env: Mapping[str, str]) -> str:
    return env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")


def options(argv: Sequence[str], env: Mapping[str, str]) -> Options:
    """The command line. The root is --root, else the home's Music folder: choosing one at the
    first start (R2.1) comes with slice 3."""
    ap = argparse.ArgumentParser(prog="musikata", description="A music player and organizer")
    ap.add_argument("--root", help="the music root (~/Music)")
    ap.add_argument("--tour", metavar="DIR", help="save each screen to DIR and check its layout")
    ap.add_argument("--tour-only", metavar="NAMES", default="", help="those screens, by name")
    ap.add_argument("--version", action="version", version=f"MusiKata {__version__}")
    a = ap.parse_args(list(argv))
    root = os.path.expanduser(a.root) if a.root else os.path.join(home_of(env), "Music")
    return Options(os.path.abspath(root), a.tour, a.tour_only)


def open_index(root: str, env: Mapping[str, str], clock: Clock) -> db.Index:
    """The root's index, found or made where A2.9 says."""
    found = roots.find_index(root, roots.roots_dir(env), clock)
    return db.Index(os.path.join(found.folder, "musikata.db"))


@dataclass
class Shell:
    """What a running MusiKata holds: the engine, its window and the bridges."""

    engine: QQmlApplicationEngine
    window: QQuickWindow
    library: Library
    index: db.Index

    def close(self) -> None:
        """The window and its engine first, while what they bind to is still there; then the
        scan's thread and the index."""
        self.window.close()
        Shiboken.delete(self.engine)
        self.library.wait()
        self.index.close()


def load(
    root: str,
    env: Mapping[str, str],
    clock: Clock,
    pool: Callable[[], Executor] = workers.pool,
) -> Shell:
    """The window over the root's index, not yet shown."""
    index = open_index(root, env, clock)
    library = Library(root, index, home_of(env), pool)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"library": library})
    engine.load(QUrl.fromLocalFile(QML))
    objects = engine.rootObjects()
    if not objects or not isinstance(objects[0], QQuickWindow):
        raise RuntimeError(f"{QML} didn't load")
    return Shell(engine, objects[0], library, index)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("MUSIKATA_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    opts = options(sys.argv[1:] if argv is None else argv, os.environ)
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("MusiKata")
    app.setApplicationVersion(__version__)
    shell = load(opts.root, os.environ, SystemClock())
    shell.library.rescan()
    if opts.tour:
        from .tour import Tour

        Tour(shell.window, shell.library, opts.tour, opts.tour_only).start()
    else:
        shell.window.show()
    code = app.exec()
    shell.close()
    return code
