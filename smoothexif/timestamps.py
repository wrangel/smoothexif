"""Reading timestamps out of metadata strings and out of filenames.

Every function here is pure and side-effect free, which is what makes the
filename heuristics cheap to test in isolation.
"""

from __future__ import annotations

import enum
import re
from datetime import datetime
from typing import NamedTuple

from .config import (
    AGREEMENT_WINDOW,
    DEFAULT_TIME,
    FILENAME_PATTERNS,
    MAX_YEAR,
    MIN_YEAR,
    PREFIX_FMT,
    PREFIX_RE,
    PRIMARY_TAGS,
)


class Precision(enum.Enum):
    """How much of a timestamp a filename actually pinned down."""

    FULL = "full"    # date and time
    DATE = "date"    # calendar day only
    MONTH = "month"  # year and month only


_TZ_RE = re.compile(r"(?:[+-]\d{2}:?\d{2}|Z)$")
_SUBSEC_RE = re.compile(r"\.\d+$")
_NON_DIGIT_RE = re.compile(r"\D")

_EXIF_FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d", "%Y-%m-%d")


def parse_exif_dt(value: object) -> datetime | None:
    """Parse an exiftool date string, tolerating timezone offsets and subseconds.

    The offset is discarded rather than applied: values reach us already
    rendered as capture-local wall clock, which is the form we want to keep.
    """
    if not isinstance(value, str):
        return None
    text = _SUBSEC_RE.sub("", _TZ_RE.sub("", value.strip()))
    for fmt in _EXIF_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        # ExifTool renders unset tags as zeros, and epoch zero is never real.
        if not MIN_YEAR <= dt.year <= MAX_YEAR:
            return None
        if (dt.year, dt.month, dt.day) == (1970, 1, 1):
            return None
        return dt
    return None


def resolve_primary(tags: dict) -> tuple[str, datetime] | None:
    """Pick the most trustworthy capture time from a file's tags.

    Returns the first PRIMARY_TAGS entry that parses, and only that one.
    Requiring all of them to agree would fail every video, where QuickTime
    CreationDate (capture-local) and CreateDate (UTC-derived) legitimately
    differ.
    """
    for tag in PRIMARY_TAGS:
        dt = parse_exif_dt(tags.get(tag))
        if dt:
            return tag, dt
    return None


def _make_dt(year: int, month: int, day: int, hour: int, minute: int, second: int
             ) -> datetime | None:
    """Build a datetime, returning None for impossible dates instead of raising.

    Delegating calendar validation to datetime is what removes the need to know
    month lengths, and is where the predecessor crashed by indexing a
    fixed-width tuple out of a shorter component list.
    """
    if not MIN_YEAR <= year <= MAX_YEAR:
        return None
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def split_prefix(stem: str) -> tuple[datetime | None, str]:
    """Split a canonical timestamp prefix off a filename stem.

    Returns ``(timestamp, remainder)``; the timestamp is None when the stem
    carries no recognisable prefix, in which case the stem is returned whole.
    """
    match = PREFIX_RE.match(stem)
    if not match:
        return None, stem
    try:
        prefix_dt = datetime.strptime(match.group(1), PREFIX_FMT)
    except ValueError:
        return None, stem
    return prefix_dt, stem[match.end():]


def find_candidate(text: str) -> tuple[str, int]:
    """Longest timestamp-like run in ``text``, as ``(digits, start offset)``.

    The offset is what distinguishes a name that already sorts chronologically
    from one that merely mentions a date somewhere in the middle.
    """
    best_text, best_start = "", -1
    for pattern in FILENAME_PATTERNS:
        match = pattern.search(text)
        if match and len(match.group(0)) > len(best_text):
            best_text, best_start = match.group(0), match.start()
    return _NON_DIGIT_RE.sub("", best_text), best_start


def extract_candidate(text: str) -> str:
    """Digits of the longest timestamp-like run found in ``text``."""
    return find_candidate(text)[0]


def candidate_to_dt(digits: str) -> tuple[datetime, Precision] | None:
    """Interpret a run of digits as a timestamp.

    Ambiguous day/month orderings are tried ISO-first and then swapped, so
    "20241305" still resolves as the 13th of May rather than being discarded.
    Trailing milliseconds (as in "20260614_162415000_iOS") are truncated.
    """
    if len(digits) >= 14:
        digits = digits[:14]
        year, a, b = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
        hour, minute, second = int(digits[8:10]), int(digits[10:12]), int(digits[12:14])
        for month, day in ((a, b), (b, a)):
            dt = _make_dt(year, month, day, hour, minute, second)
            if dt:
                return dt, Precision.FULL
        return None
    if len(digits) == 8:
        year, a, b = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
        for month, day in ((a, b), (b, a)):
            dt = _make_dt(year, month, day, *DEFAULT_TIME)
            if dt:
                return dt, Precision.DATE
        return None
    if len(digits) == 6:
        year, month = int(digits[0:4]), int(digits[4:6])
        dt = _make_dt(year, month, 1, *DEFAULT_TIME)
        if dt:
            return dt, Precision.MONTH
        return None
    return None


class NameTime(NamedTuple):
    """A timestamp read out of a filename, and whether the name leads with it."""

    ts: datetime
    precision: Precision
    #: True when the timestamp sits at the very front of the stem, so the file
    #: already sorts chronologically among its neighbours. False when the date
    #: is merely mentioned somewhere inside the name.
    leads: bool


def timestamp_from_name(stem: str) -> NameTime | None:
    """Best timestamp derivable from a filename stem.

    A canonical prefix is a deliberate assertion about the file, so it outranks
    any timestamp buried further along the name.
    """
    prefix_ts, _body = split_prefix(stem)
    if prefix_ts:
        return NameTime(prefix_ts, Precision.FULL, leads=True)
    digits, start = find_candidate(stem)
    parsed = candidate_to_dt(digits)
    if not parsed:
        return None
    return NameTime(parsed[0], parsed[1], leads=(start == 0))


def same_moment(a: datetime, b: datetime, precision: Precision) -> bool:
    """Are these close enough to be the same moment?

    Compared only as far as the coarser of the two is meaningful, and for full
    timestamps within AGREEMENT_WINDOW rather than exactly. Exact equality would
    flag every camera that writes local time into a UTC field as a conflict, so
    only a genuinely different timestamp counts as disagreement.
    """
    if precision is Precision.MONTH:
        return (a.year, a.month) == (b.year, b.month)
    if precision is Precision.DATE:
        return a.date() == b.date() or abs(a - b) <= AGREEMENT_WINDOW
    return abs(a - b) <= AGREEMENT_WINDOW
