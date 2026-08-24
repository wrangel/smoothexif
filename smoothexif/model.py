"""What smoothexif knows about one file, and which bucket that puts it in.

Classification is a pure function of an Item, and every Item lands in exactly
one bucket. Resolution order follows the buckets in sequence, so the hierarchy
is readable straight off the enum.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import ALL_PRIMARY_TAGS, FS_TAGS, PARTITION, PREFIX_FMT, VIDEO_SUFFIXES
from .macos import read_finder_dates
from .timestamps import (
    Precision,
    parse_exif_dt,
    resolve_primary,
    same_moment,
    split_prefix,
    timestamp_from_name,
)


class Bucket(enum.Enum):
    """Every file lands in exactly one of these, resolved in declaration order."""

    EXIF_ONLY = ("B1", "primary EXIF, no filename timestamp")
    AGREE = ("B2", "primary EXIF and filename agree")
    CONFLICT = ("B3", "primary EXIF and filename disagree")
    NAME_FULL = ("B4", "no primary EXIF, full filename timestamp")
    NAME_DATE = ("B5", "no primary EXIF, date-only filename")
    NAME_MONTH = ("B6", "no primary EXIF, year-month filename")
    SECONDARY = ("B7", "no primary EXIF, secondary tags only - always asks")
    NOTHING = ("B8", "nothing usable")

    def __init__(self, label: str, description: str):
        self.label = label
        self.description = description

    def __str__(self) -> str:
        return self.label


@dataclass
class Item:
    """One file, everything read about it, and what we decided to do with it."""

    path: Path
    body: str  # filename stem with any canonical prefix removed
    ext: str

    # observed
    exif_primary: datetime | None = None
    exif_primary_tag: str = ""
    secondary: list[tuple[str, datetime]] = field(default_factory=list)
    name_ts: datetime | None = None
    name_precision: Precision | None = None
    #: The name already begins with its timestamp, so the file sorts correctly
    #: as it stands and must not be renamed.
    name_leads: bool = False
    fs_create: datetime | None = None
    fs_modify: datetime | None = None

    # decided
    bucket: Bucket | None = None
    target_ts: datetime | None = None
    write_exif: bool = False
    resolved: bool = False
    renamed: bool = False
    #: Set when the user was asked and declined. Distinct from merely
    #: unresolved: a declined file stays exactly where it is, because "skip"
    #: means leave it alone, not file it away.
    skipped: bool = False

    @property
    def real_secondary(self) -> list[tuple[str, datetime]]:
        """Secondary tags minus filesystem dates, which every file always has."""
        return [pair for pair in self.secondary if pair[0] not in FS_TAGS]

    @property
    def tz_assumed(self) -> bool:
        """True when this file's time had to be guessed as resident-timezone.

        Times are kept as capture-local wall clock: DateTimeOriginal already is,
        and QuickTime CreationDate carries the capture offset. A video with
        neither has only UTC atoms and nothing recording where it was shot, so
        the instant gets rendered in the local zone. Irrelevant when the
        filename overrode the EXIF value anyway.
        """
        return (
            self.ext.lower() in VIDEO_SUFFIXES
            and self.exif_primary is not None
            and self.exif_primary_tag != "CreationDate"
            and self.target_ts == self.exif_primary
        )

    def target_name(self, normalise: bool = False) -> str:
        """Filename this item should end up with.

        The test is whether the folder sorts by date. A name that already begins
        with its timestamp is left exactly as it is - rewriting it would only
        bury the camera's own name inside a duplicate of the same date. A name
        that merely mentions a date somewhere in the middle
        ("IMG-20260621-WA0001.jpg") gets the prefix, because as it stands it
        sorts alphabetically among unrelated files. So does a name with no
        timestamp at all ("GX010001.MP4"), which takes its date from metadata.

        ``normalise`` forces the canonical form regardless, for anyone who wants
        one uniform convention across the whole library.
        """
        if self.name_leads and not normalise:
            return self.path.name
        stamp = self.target_ts.strftime(PREFIX_FMT)
        # Nothing left of the name but the timestamp itself - don't duplicate it.
        if not self.body or self.body == stamp:
            return f"{stamp}{self.ext}"
        return f"{stamp}{PARTITION}{self.body}{self.ext}"

    def needs_rename(self, normalise: bool = False) -> bool:
        return (
            self.target_ts is not None
            and self.target_name(normalise) != self.path.name
        )

    def decide(self, ts: datetime, write_exif: bool) -> None:
        self.target_ts = ts
        self.write_exif = write_exif
        self.resolved = True


def build_item(path: Path, tags: dict) -> Item:
    """Assemble everything known about one file from its path and its tags."""
    _prefix_ts, body = split_prefix(path.stem)
    item = Item(path=path, body=body, ext=path.suffix)

    primary = resolve_primary(tags, path.suffix)
    if primary:
        item.exif_primary_tag, item.exif_primary = primary

    for tag, raw in tags.items():
        if tag == "SourceFile" or tag in ALL_PRIMARY_TAGS:
            continue
        dt = parse_exif_dt(raw)
        if dt:
            item.secondary.append((tag, dt))
    item.secondary.sort(key=lambda pair: pair[1])

    item.fs_create, item.fs_modify = read_finder_dates(path)

    from_name = timestamp_from_name(path.stem)
    if from_name:
        item.name_ts = from_name.ts
        item.name_precision = from_name.precision
        item.name_leads = from_name.leads
    return item


def build_items(paths: list[Path], tags_by_path: dict[Path, dict]) -> list[Item]:
    return [build_item(path, tags_by_path.get(path, {})) for path in paths]


def classify(item: Item) -> Bucket:
    """Assign the one bucket this item belongs to.

    Zero-byte files and exiftool remnants never reach here; the pipeline
    quarantines them before any metadata is read.
    """
    if item.exif_primary and not item.name_ts:
        return Bucket.EXIF_ONLY
    if item.exif_primary and item.name_ts:
        if same_moment(item.exif_primary, item.name_ts, item.name_precision):
            return Bucket.AGREE
        return Bucket.CONFLICT
    if item.name_precision is Precision.FULL:
        return Bucket.NAME_FULL
    if item.name_precision is Precision.DATE:
        return Bucket.NAME_DATE
    if item.name_precision is Precision.MONTH:
        return Bucket.NAME_MONTH
    if item.real_secondary:
        return Bucket.SECONDARY
    return Bucket.NOTHING
