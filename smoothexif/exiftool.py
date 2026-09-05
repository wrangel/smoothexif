"""The only place that talks to exiftool.

exiftool costs ~130ms to start and ~2ms per file thereafter, so the single rule
this module exists to enforce is: never once per file. Reads go through one
bulk invocation; writes go through one invocation with ``-execute`` separating
per-file argument groups, which lets N files take N different values in one
process.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from . import console
from .config import QUICKTIME_ARGS, write_tags_for

#: Where Homebrew puts it on Apple Silicon and Intel respectively.
_FALLBACK_PATHS = ("/opt/homebrew/bin/exiftool", "/usr/local/bin/exiftool")

_EXIF_STAMP_FMT = "%Y:%m:%d %H:%M:%S"


class ExifToolMissing(RuntimeError):
    pass


class ExifTool:
    """A located exiftool binary, invoked in bulk."""

    def __init__(self, executable: str):
        self.executable = executable

    @classmethod
    def locate(cls) -> "ExifTool":
        """Find exiftool on PATH, falling back to the usual Homebrew prefixes."""
        found = shutil.which("exiftool")
        if not found:
            found = next((p for p in _FALLBACK_PATHS if os.access(p, os.X_OK)), None)
        if not found:
            raise ExifToolMissing(
                "exiftool not found. Install it with:  brew install exiftool"
            )
        return cls(found)

    def _run(self, lines: list[str]) -> subprocess.CompletedProcess:
        """Invoke exiftool with an argument file, sidestepping ARG_MAX entirely.

        Note that exiftool strips leading and trailing whitespace from argument
        file lines, which is why such filenames are filtered out upstream.
        """
        with tempfile.NamedTemporaryFile(
            "w", suffix=".args", delete=False, encoding="utf-8"
        ) as handle:
            handle.write("\n".join(lines) + "\n")
            argfile = handle.name
        try:
            return subprocess.run(
                [self.executable, "-@", argfile],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        finally:
            os.unlink(argfile)

    def read_times(self, paths: list[Path]) -> dict[Path, dict]:
        """Read every date/time tag for every path in one invocation.

        FileCreateDate is deliberately not requested: it is a MacOS pseudo-tag
        that exiftool resolves per file at ~10ms each (5.7s versus 0.75s over
        500 files). See macos.read_finder_dates for the free alternative.
        """
        if not paths:
            return {}
        lines = ["-j", "-s", "-m", "-time:all"] + QUICKTIME_ARGS
        lines += [str(p) for p in paths]
        proc = self._run(lines)
        if not proc.stdout.strip():
            if proc.stderr.strip():
                console.err(f"exiftool read failed: {proc.stderr.strip()}")
            return {}
        try:
            records = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            console.err(f"could not parse exiftool JSON output: {exc}")
            return {}
        return {
            Path(record["SourceFile"]): record
            for record in records
            if record.get("SourceFile")
        }

    def _write_groups(self, groups: list[list[str]]) -> bool:
        """Run one -execute block per group, all in a single process."""
        if not groups:
            return True
        lines: list[str] = []
        for group in groups:
            lines += group + ["-execute"]
        proc = self._run(lines)
        if proc.returncode != 0:
            console.err(f"exiftool write reported errors:\n{proc.stderr.strip()}")
            return False
        return True

    def write_capture_times(self, jobs: list[tuple[Path, datetime]]) -> bool:
        """Set the capture time. One process regardless of how many files.

        Which tags get written depends on the format - see config.write_tags_for.
        """
        groups = []
        for path, ts in jobs:
            stamp = ts.strftime(_EXIF_STAMP_FMT)
            groups.append([
                "-overwrite_original", "-m", *QUICKTIME_ARGS,
                *[tag.format(stamp=stamp) for tag in write_tags_for(path.suffix)],
                str(path),
            ])
        return self._write_groups(groups)

    def write_finder_times(self, jobs: list[tuple[Path, datetime]]) -> bool:
        """Fallback for volumes where the setattrlist syscall is refused."""
        groups = []
        for path, ts in jobs:
            stamp = ts.strftime(_EXIF_STAMP_FMT)
            groups.append([
                "-overwrite_original", "-m",
                f"-FileCreateDate={stamp}", f"-FileModifyDate={stamp}",
                str(path),
            ])
        return self._write_groups(groups)
