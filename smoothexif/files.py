"""Listing, moving and collision-safe naming on disk."""

from __future__ import annotations

import os
from pathlib import Path

from . import console
from .config import EXCLUDED_SUFFIXES, EXIFTOOL_TMP_SUFFIX


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
