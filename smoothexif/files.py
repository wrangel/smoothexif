"""Listing, moving and collision-safe naming on disk."""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import console
from .config import EXCLUDED_SUFFIXES, EXIFTOOL_TMP_SUFFIX


class DirectoryBusy(RuntimeError):
    """Another smoothexif is already working on this directory."""


@contextmanager
def directory_lock(directory: Path):
    """Hold an exclusive lock on ``directory`` for the length of the block.

    Two runs over one folder race: each plans against a snapshot the other is
    busy invalidating, so they trip over half-finished renames and can leave
    spurious "-1" duplicates behind. Different folders are unaffected and run
    happily in parallel.

    The lock is an flock on a file in the temp dir, keyed by the directory path
    - so nothing is written into the photo folder itself, and the kernel drops
    the lock when the process dies, however it dies. There is no stale lock to
    clean up after a crash.
    """
    key = hashlib.sha1(str(directory).encode()).hexdigest()[:16]
    lockfile = Path(tempfile.gettempdir()) / f"smoothexif-{key}.lock"
    handle = os.open(lockfile, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(handle)
        raise DirectoryBusy(directory) from None
    try:
        os.truncate(handle, 0)
        os.write(handle, str(os.getpid()).encode())
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def list_files(directory: Path) -> list[Path]:
    """Candidate files directly inside ``directory``. Never recursive.

    Subdirectories are skipped wholesale, which is what keeps the tool's own
    _unsuccessful / _zeroByte folders out of subsequent runs.
    """
    files = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        if not entry.is_file() or entry.is_symlink():
            continue
        if entry.name.startswith("."):
            continue
        if entry.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if entry.name != entry.name.strip():
            # exiftool argument files strip surrounding whitespace, so such a
            # name could not be passed through reliably.
            console.warn(
                f"skipping {entry.name!r}: leading/trailing whitespace in filename"
            )
            continue
        files.append(entry)
    return files


def is_exiftool_remnant(path: Path) -> bool:
    return path.name.endswith(EXIFTOOL_TMP_SUFFIX)


def unique_destination(destination: Path) -> Path:
    """Never clobber: append a counter if something is already there."""
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    counter = 1
    while True:
        candidate = destination.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def move_into(paths: list[Path], directory: Path, folder: str, dry_run: bool) -> None:
    """Move files into a sibling subfolder, reporting each one."""
    if not paths:
        return
    destination_dir = directory / folder
    for path in paths:
        console.info(f"  {'would move ' if dry_run else ''}{path.name} -> {folder}/")
        if dry_run:
            continue
        destination_dir.mkdir(exist_ok=True)
        try:
            os.rename(path, unique_destination(destination_dir / path.name))
        except OSError as exc:
            console.err(f"could not move {path.name}: {exc}")


def rename(path: Path, destination: Path) -> Path | None:
    """Rename, avoiding collisions. Returns the final path, or None on failure."""
    final = unique_destination(destination)
    try:
        os.rename(path, final)
        return final
    except OSError as exc:
        console.err(f"could not rename {path.name}: {exc}")
        return None
