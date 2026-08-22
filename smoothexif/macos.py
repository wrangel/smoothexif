"""Finder creation and modification dates, set without spawning a process.

exiftool can write ``-FileCreateDate``, but it resolves that MacOS pseudo-tag
per file at roughly 16ms each - 7.9s of a 12.5s run over 500 files. The
``setattrlist`` syscall does the same job for free, and reading the current
value comes straight out of ``stat()``.
"""

from __future__ import annotations

import ctypes
import os
import struct
from datetime import datetime
from pathlib import Path

#: struct attrlist requesting only ATTR_CMN_CRTIME. See <sys/attr.h>:
#: u_short bitmapcount, u_int16 reserved, then five attrgroup_t bitmaps.
_ATTR_BIT_MAP_COUNT = 5
_ATTR_CMN_CRTIME = 0x00000200
_ATTRLIST_CRTIME = struct.pack(
    "HHIIIII", _ATTR_BIT_MAP_COUNT, 0, _ATTR_CMN_CRTIME, 0, 0, 0, 0
)

_libc = None


def _load_libc():
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL("libc.dylib", use_errno=True)
    return _libc


def set_finder_dates(path: Path, ts: datetime) -> bool:
    """Set both Finder dates on ``path``.

    Returns False if the filesystem refuses either operation - some network
    volumes do - so the caller can fall back to exiftool. Pre-1970 timestamps
    are fine: the syscall takes a signed epoch.
    """
    epoch = int(ts.timestamp())
    try:
        os.utime(path, (epoch, epoch))
    except OSError:
        return False
    try:
        buf = struct.pack("qq", epoch, 0)  # struct timespec
        rc = _load_libc().setattrlist(
            os.fsencode(str(path)), _ATTRLIST_CRTIME, buf, len(buf), 0
        )
        return rc == 0
    except OSError:
        return False


def read_finder_dates(path: Path) -> tuple[datetime | None, datetime | None]:
    """Return ``(created, modified)`` straight from stat(), or Nones on error."""
    try:
        stat = path.stat()
    except OSError:
        return None, None
    birth = getattr(stat, "st_birthtime", None)
    created = datetime.fromtimestamp(birth).replace(microsecond=0) if birth else None
    modified = datetime.fromtimestamp(stat.st_mtime).replace(microsecond=0)
    return created, modified
