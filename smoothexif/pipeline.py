"""Scan, decide, plan, execute, verify.

The run is deliberately split so that deciding what to do and doing it are
different functions. ``build_plan`` is pure; ``execute_plan`` is the only thing
in the codebase that mutates files. A dry run is therefore not a flag threaded
through the write path - it simply never calls ``execute_plan``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import console, files
from .config import FS_TAGS, TMP_DIR, UNSUCCESSFUL_DIR, ZEROBYTE_DIR
from .exiftool import ExifTool
from .macos import set_finder_dates
from .model import Bucket, Item, build_items, classify
from .prompts import Choice, Prompter, quit_preview
from .timestamps import (
    has_embedded_tags,
    resolve_primary,
    same_moment,
    timestamp_from_name,
)


@dataclass
class Settings:
    """Everything a run needs, decoupled from argparse."""

    directory: Path
    dry_run: bool = False
    interactive: bool = True
    prefer: str = "ask"
    quarantine_failures: bool = True
    #: Force every file into the canonical prefix form, even when its name
    #: already carries a perfectly good timestamp.
    normalise_names: bool = False


@dataclass
class Plan:
    """The complete set of intended changes. Building one touches nothing."""

    actionable: list[Item] = field(default_factory=list)
    exif_writes: list[tuple[Path, datetime]] = field(default_factory=list)
    finder_writes: list[Item] = field(default_factory=list)
    renames: list[tuple[Item, Path]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.actionable


# --------------------------------------------------------------------------
# Deciding
# --------------------------------------------------------------------------


def refine_date_only(item: Item) -> datetime:
    """Borrow a time of day from any tag that agrees on the calendar day.

    Real metadata tags are preferred over filesystem ones; when nothing
    corroborates the date, the configured default time stands.
    """
    target_date = item.name_ts.date()
    ranked = [pair for pair in item.secondary if pair[0] not in FS_TAGS]
    ranked += [pair for pair in item.secondary if pair[0] in FS_TAGS]
    for _tag, dt in ranked:
        if dt.date() == target_date:
            return dt
    return item.name_ts


def resolve(items: list[Item], prompter: Prompter) -> None:
    """Give every item a target timestamp, asking where the answer is not ours."""
    for item in items:
        if item.bucket in (Bucket.EXIF_ONLY, Bucket.AGREE):
            item.decide(item.exif_primary, write_exif=False)

        elif item.bucket is Bucket.CONFLICT:
            choice = prompter.conflict(item)
            if choice == Choice.EXIF:
                item.decide(item.exif_primary, write_exif=False)
            elif choice == Choice.FILENAME:
                item.decide(item.name_ts, write_exif=True)
            else:
                item.skipped = True

        elif item.bucket is Bucket.NAME_FULL:
            item.decide(item.name_ts, write_exif=True)

        elif item.bucket is Bucket.NAME_DATE:
            item.decide(refine_date_only(item), write_exif=True)

        elif item.bucket is Bucket.NAME_MONTH:
            if prompter.month(item):
                item.decide(item.name_ts, write_exif=True)

        elif item.bucket is Bucket.SECONDARY:
            # Nothing authoritative to go on, but something to offer: show the
            # file and let the user judge. Declining leaves it unresolved.
            picked = prompter.preview_pick(item)
            if picked:
                item.decide(picked, write_exif=True)


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


def build_plan(items: list[Item], normalise_names: bool = False) -> Plan:
    """Work out the minimum set of operations. Pure - touches nothing."""
    plan = Plan()
    plan.actionable = [i for i in items if i.resolved and i.target_ts]
    for item in plan.actionable:
        if item.write_exif:
            plan.exif_writes.append((item.path, item.target_ts))
        # An EXIF rewrite bumps mtime, so those always need their dates reset.
        # Otherwise skip files already carrying the right ones, which is what
        # makes re-running over a processed folder essentially free.
        if (
            item.write_exif
            or item.fs_create != item.target_ts
            or item.fs_modify != item.target_ts
        ):
            plan.finder_writes.append(item)
        if item.needs_rename(normalise_names):
            plan.renames.append(
                (item, item.path.with_name(item.target_name(normalise_names)))
            )
    return plan


def render_plan(plan: Plan, dry_run: bool, normalise_names: bool = False) -> None:
    """Describe the plan, in the tense that matches whether it will happen."""
    would = "would " if dry_run else ""
    renaming = {id(item) for item, _ in plan.renames}
    for item in plan.actionable:
        stamp = item.target_ts.strftime("%Y-%m-%d %H:%M:%S")
        if id(item) in renaming:
            detail = f"{would}rename -> {item.target_name(normalise_names)}"
            detail += f" + {would}rewrite exif" if item.write_exif else ""
        elif item.write_exif:
            detail = f"{would}rewrite exif"
        else:
            detail = "already correct"
        console.info(f"  [{item.bucket}] {item.path.name}  ({stamp}, {detail})")


# --------------------------------------------------------------------------
# Executing - the only code here that changes anything on disk
# --------------------------------------------------------------------------


def execute_plan(plan: Plan, exiftool: ExifTool) -> int:
    """Carry out the plan. Returns how many files were actually renamed."""
    if not exiftool.write_capture_times(plan.exif_writes):
        console.warn("some EXIF writes failed; validation will catch those files")

    # Applied after the EXIF pass, which rewrites the file and so bumps mtime.
    refused = [
        item for item in plan.finder_writes
        if not set_finder_dates(item.path, item.target_ts)
    ]
    if refused:
        console.warn(
            f"setattrlist refused on {len(refused)} file(s); falling back to exiftool"
        )
        exiftool.write_finder_times([(i.path, i.target_ts) for i in refused])

    renamed = 0
    for item, destination in plan.renames:
        final = files.rename(item.path, destination)
        if final:
            item.path = final
            item.renamed = True
            renamed += 1
    return renamed


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate(
    exiftool: ExifTool,
    directory: Path,
    dry_run: bool,
    quarantine_failures: bool = True,
    exempt: set[Path] | None = None,
) -> tuple[int, int]:
    """Check every filename's timestamp against the file's primary capture tag.

    The invariant is that the folder sorts by date: every name begins with a
    timestamp, and the metadata agrees with it. Small drift is tolerated exactly
    as it is during a run; a date buried mid-name is a failure, because such a
    file sorts alphabetically among unrelated ones.

    ``quarantine_failures`` moves offenders aside. That is right at the end of a
    processing run, where a failure means the file could not be resolved. It is
    wrong for a standalone check on a folder that has simply not been processed
    yet, so that path reports instead.

    ``exempt`` names files the user was asked about and chose to leave as they
    are. They still get reported, but moving them would override a decision that
    was just made deliberately. Returns ``(passed, failed)``.
    """
    exempt = exempt or set()
    paths = [p for p in files.list_files(directory) if not files.is_exiftool_remnant(p)]
    if not paths:
        return 0, 0
    tags_by_path = exiftool.read_times(paths)

    failures: list[Path] = []
    undated: list[Path] = []
    unreadable: list[Path] = []
    fixable: list[Path] = []      # a normal run resolves these unaided
    mismatched: list[Path] = []   # these need a decision
    passed = 0
    for path in paths:
        from_name = timestamp_from_name(path.stem)
        if not from_name:
            undated.append(path)
            failures.append(path)
            continue
        if not from_name.leads:
            console.warn(f"{path.name}: date is not at the start of the name")
            fixable.append(path)
            failures.append(path)
            continue
        name_ts, precision = from_name.ts, from_name.precision
        tags = tags_by_path.get(path, {})
        primary = resolve_primary(tags, path.suffix)
        if not primary:
            failures.append(path)
            if not has_embedded_tags(tags):
                # Only filesystem dates came back, so nothing was actually read.
                console.warn(f"{path.name}: could not read any metadata from this file")
                unreadable.append(path)
            else:
                console.warn(f"{path.name}: no primary metadata timestamp")
                fixable.append(path)
            continue
        tag, dt = primary
        if not same_moment(dt, name_ts, precision):
            console.warn(f"{path.name}: filename {name_ts} != {tag} {dt}")
            mismatched.append(path)
            failures.append(path)
        else:
            passed += 1

    if undated:
        console.info(f"{len(undated)} file(s) have no timestamp in the name:")
        for path in undated[:10]:
            console.info(f"    {path.name}")
        if len(undated) > 10:
            console.info(f"    ... and {len(undated) - 10} more")
        fixable.extend(undated)

    # A folder where nothing at all carries a date has simply not been run yet.
    if passed == 0 and undated and len(undated) == len(failures):
        console.warn("nothing in this folder has been processed yet.")
        console.warn(f"run without -v to process it:  smoothexif {directory}")

    if quarantine_failures:
        files.move_into(
            [p for p in failures if p not in exempt],
            directory, UNSUCCESSFUL_DIR, dry_run,
        )
    else:
        _suggest_next_command(directory, fixable, mismatched, unreadable)
        if failures:
            console.info(
                f"(reporting only; use --quarantine to move them to {UNSUCCESSFUL_DIR}/)"
            )
    return passed, len(failures)


def _suggest_next_command(
    directory: Path,
    fixable: list[Path],
    mismatched: list[Path],
    unreadable: list[Path],
) -> None:
    """Print the command that resolves what the check just found.

    Reporting a problem without saying what to do about it is what sends people
    off copying files around to experiment.
    """
    if not (fixable or mismatched or unreadable):
        return
    # Echo the invocation as typed, so the suggestion is directly runnable.
    prog = sys.argv[0] or "smoothexif"
    target = f'"{directory}"' if " " in str(directory) else str(directory)

    console.heading("What to do")
    if fixable:
        console.info(f"  {len(fixable)} file(s) a normal run fixes by itself:")
        console.info(f"      {prog} {target}")
    if mismatched:
        console.info(
            f"  {len(mismatched)} file(s) where filename and metadata disagree "
            f"- the run asks about each:"
        )
        console.info(f"      {prog} {target}")
        console.info("    or decide once for all of them:")
        console.info(f"      {prog} --prefer filename {target}")
    if unreadable:
        console.info(
            f"  {len(unreadable)} file(s) whose metadata could not be read at all."
        )
        console.info(
            "    Not a timestamp problem - the file did not open. On a network or"
        )
        console.info(
            "    sync-on-demand volume, make sure it is downloaded, then re-check:"
        )
        console.info(f"      {prog} -v {target}")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def _quarantine_unreadable(directory: Path, paths: list[Path], dry_run: bool
                           ) -> list[Path]:
    """Set aside zero-byte files and exiftool remnants before reading metadata."""
    zero_byte = [p for p in paths if p.stat().st_size == 0]
    remnants = [p for p in paths if files.is_exiftool_remnant(p)]
    if zero_byte or remnants:
        console.heading("Quarantine")
        files.move_into(zero_byte, directory, ZEROBYTE_DIR, dry_run)
        files.move_into(remnants, directory, TMP_DIR, dry_run)
    setaside = set(zero_byte) | set(remnants)
    return [p for p in paths if p not in setaside]


def _report_bucket_counts(items: list[Item]) -> None:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.bucket.label] = counts.get(item.bucket.label, 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    console.info(f"{len(items)} files: {summary}")


def _report_timezone_guesses(plan: Plan) -> None:
    guessed = [item for item in plan.actionable if item.tz_assumed]
    if not guessed:
        return
    console.warn(
        f"{len(guessed)} video(s) carry no capture offset (UTC atoms only); "
        f"their times assume your local timezone:"
    )
    for item in guessed:
        console.info(f"    {item.path.name}  (from {item.exif_primary_tag})")


def run(exiftool: ExifTool, settings: Settings) -> int:
    """Full hierarchy, then validation."""
    prompter = Prompter(
        interactive=settings.interactive,
        conflict_default={"exif": Choice.EXIF, "filename": Choice.FILENAME}.get(
            settings.prefer
        ),
    )
    if settings.prefer != "ask":
        console.info(console.bold(f"Conflicts resolved in favour of: {settings.prefer}"))

    console.info(console.bold(f"Scanning {settings.directory}"))
    paths = files.list_files(settings.directory)
    if not paths:
        console.info("Nothing to do.")
        return 0

    paths = _quarantine_unreadable(settings.directory, paths, settings.dry_run)
    if not paths:
        return 0

    items = build_items(paths, exiftool.read_times(paths))
    for item in items:
        item.bucket = classify(item)
    _report_bucket_counts(items)

    resolve(items, prompter)
    plan = build_plan(items, settings.normalise_names)

    console.heading("Planned changes" if settings.dry_run else "Applying")
    render_plan(plan, settings.dry_run, settings.normalise_names)

    if settings.dry_run:
        console.info(
            f"would process {len(plan.actionable)} file(s), "
            f"rename {len(plan.renames)}"
        )
    else:
        renamed = execute_plan(plan, exiftool)
        console.info(f"{len(plan.actionable)} file(s) processed, {renamed} renamed")

    _report_timezone_guesses(plan)

    if prompter.previewed:
        quit_preview()

    skipped = [item for item in items if item.skipped]
    if skipped:
        console.heading("Left alone (you declined)")
        for item in skipped:
            console.info(f"  {item.path.name}")

    # Files with nothing usable to go on are filed away for later attention.
    # Ones the user actively declined are not: they stay put.
    unresolved = [item for item in items if not item.resolved and not item.skipped]
    if unresolved:
        console.heading("Unresolved")
        files.move_into(
            [i.path for i in unresolved], settings.directory,
            UNSUCCESSFUL_DIR, settings.dry_run,
        )

    if settings.dry_run:
        console.heading("Dry run: nothing was renamed, written, moved or created.")
        console.info("Re-run without --dry-run to apply.")
        return 0

    console.heading("Validating")
    passed, failed = validate(
        exiftool, settings.directory, settings.dry_run,
        exempt={item.path for item in skipped},
    )
    console.info(f"{passed} validated, {failed} failing")
    return 0
