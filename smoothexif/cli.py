"""Command line surface. Translates arguments into Settings and nothing more."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import console
from .config import UNSUCCESSFUL_DIR
from .exiftool import ExifTool, ExifToolMissing
from .model import Bucket
from .pipeline import Settings, run, validate

_EPILOG = "Buckets, resolved in this order:\n" + "\n".join(
    f"  {b.label}  {b.description}" for b in Bucket
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smoothexif",
        description="Normalise photo and video timestamps across metadata, "
                    "filenames and Finder dates.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("directory", type=Path,
                        help="directory to process (not recursive)")
    parser.add_argument("-v", "--validate-only", action="store_true",
                        help="only check filename prefixes against metadata; "
                             "moves nothing unless --quarantine is given")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="report planned changes without touching anything")
    parser.add_argument("--prefer", choices=("ask", "exif", "filename"), default="ask",
                        help="resolve metadata/filename conflicts without asking. "
                             "'filename' suits cameras that wrote wrong dates "
                             "(e.g. a GoPro with a reset clock) where the files "
                             "have since been renamed correctly")
    parser.add_argument("--non-interactive", action="store_true",
                        help=f"never prompt; ambiguous files go to {UNSUCCESSFUL_DIR}/")
    parser.add_argument("--quarantine", action="store_true",
                        help=f"with -v, also move failing files to {UNSUCCESSFUL_DIR}/")
    parser.add_argument("--normalise-names", action="store_true",
                        help="rewrite every filename into YYYYMMDD_HHMMSS__original "
                             "form. Off by default: a name that already carries a "
                             "timestamp is left alone")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        console.err(f"not a directory: {directory}")
        return 2

    try:
        exiftool = ExifTool.locate()
    except ExifToolMissing as exc:
        console.err(str(exc))
        return 2

    if args.validate_only:
        console.info(console.bold(f"Validating {directory}"))
        passed, failed = validate(exiftool, directory, args.dry_run, args.quarantine)
        verb = f"moved to {UNSUCCESSFUL_DIR}/" if args.quarantine else "failing"
        console.info(f"{passed} validated, {failed} {verb}")
        return 1 if failed else 0

    return run(exiftool, Settings(
        directory=directory,
        dry_run=args.dry_run,
        interactive=not args.non_interactive,
        prefer=args.prefer,
        normalise_names=args.normalise_names,
    ))
