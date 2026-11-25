"""Tags: R4.1's fields for every kind of R2.2 (A3.1, A3.2). Reading is read.read; what it reads
from each kind is parse.py's, as plain data."""

from .fields import AudioInfo, Tags
from .read import EXTENSIONS, TagReadError, read

__all__ = ["EXTENSIONS", "AudioInfo", "TagReadError", "Tags", "read"]
