"""Finder creation and modification dates, set without spawning a process.

exiftool can write ``-FileCreateDate``, but it resolves that MacOS pseudo-tag
per file at roughly 16ms each - 7.9s of a 12.5s run over 500 files. The
``setattrlist`` syscall does the same job for free, and reading the current
value comes straight out of ``stat()``.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import struct
import subprocess
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


def prevent_sleep() -> subprocess.Popen | None:
    """Keep the Mac awake for as long as this process lives.

    Rewriting a library of videos is tens of GB of I/O and can run for many
    minutes with no keyboard activity, which is exactly when a Mac decides to
    idle-sleep. ``caffeinate -w`` watches our PID and exits by itself when we
    do, so there is nothing to clean up even if we are killed.

    Returns the handle (unused, but kept so the child is not garbage collected)
    or None when caffeinate is unavailable. Note this cannot defeat closing the
    lid - nothing can.
    """
    binary = shutil.which("caffeinate")
    if not binary:
        return None
    try:
        return subprocess.Popen(
            # -i prevent idle sleep, -s prevent system sleep while on mains.
            [binary, "-i", "-s", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None


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
