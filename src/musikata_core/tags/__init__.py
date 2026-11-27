"""Tags: R4.1's fields for every kind of R2.2 (A3.1, A3.2). Reading is read.read; what it reads
from each kind is parse.py's, as plain data. Writing goes the other way: compose.py's plain data
applied by write.py, always to a copy that safe.save checks and puts in the song's place (A3.4),
a file at a time or many in a batch (R4.7). What the Edit tags panel shows for a set of songs, and
the save its edits make, is edit.py's (R4.2 to R4.4), and what its bulk tools would make of the
songs, tools.py's (R4.5), Tidy case among them (case.py, R3.6.1); what a song keeps without
showing, read.kept (R4.1.1, R4.8)."""

from .batch import Batch, Failed, Job, Outcome, Recorder
from .fields import AudioInfo, Picture, Tags
from .read import EXTENSIONS, TagReadError, kept, pictures, read
from .safe import WriteError, Written, is_leftover, save

__all__ = [
    "EXTENSIONS",
    "AudioInfo",
    "Batch",
    "Failed",
    "Job",
    "Outcome",
    "Picture",
    "Recorder",
    "TagReadError",
    "Tags",
    "WriteError",
    "Written",
    "is_leftover",
    "kept",
    "pictures",
    "read",
    "save",
]
