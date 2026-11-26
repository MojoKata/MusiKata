"""Tags: R4.1's fields for every kind of R2.2 (A3.1, A3.2). Reading is read.read; what it reads
from each kind is parse.py's, as plain data. Writing goes the other way: compose.py's plain data
applied by write.py, always to a copy that safe.save checks and puts in the song's place (A3.4),
a file at a time or many in a batch (R4.7)."""

from .batch import Batch, Failed, Job, Outcome, Recorder
from .fields import AudioInfo, Picture, Tags
from .read import EXTENSIONS, TagReadError, pictures, read
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
    "pictures",
    "read",
    "save",
]
