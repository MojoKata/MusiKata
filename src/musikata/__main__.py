"""python -m musikata: the frozen builds start here too, so the worker processes, started with
spawn, run their job and not a second MusiKata (A1.3)."""

import multiprocessing
import sys

from musikata.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
