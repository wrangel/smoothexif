"""Tunable constants and the naming convention smoothexif enforces.

Everything the tool considers a policy decision lives here rather than being
scattered through the code, so a convention change is a one-line edit.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# --------------------------------------------------------------------------
# Filename convention
# --------------------------------------------------------------------------

#: Separates the timestamp prefix from whatever the file was called before.
PARTITION = "__"

#: strftime pattern for the prefix itself.
PREFIX_FMT = "%Y%m%d_%H%M%S"

#: A leading timestamp counts as a prefix when it is a complete token: followed
#: by the partition, by a single separator, or by nothing at all. This keeps
#: hand-renamed files ("20240716_090000_surf.mov") and bare ones
#: ("20140718_170000.jpeg") from gaining a duplicate copy of their own
#: timestamp, while still not matching "20260614_162415000_iOS.jpg", where the
#: next character is a digit and the run is therefore something else.
PREFIX_RE = re.compile(r"^(\d{8}_\d{6})(?:" + re.escape(PARTITION) + r"|[-_. ]|$)")

_SEP = r"[-_/., ]"

#: Timestamp shapes recognised inside a filename. The longest match anywhere in
#: the name wins, so more specific shapes need not come first - but the order is
#: kept longest-first for readability.
FILENAME_PATTERNS = [
    re.compile(rf"\d{{4}}{_SEP}\d{{2}}{_SEP}\d{{2}}{_SEP}\d{{2}}{_SEP}\d{{2}}{_SEP}\d{{2}}"),
    re.compile(rf"\d{{4}}{_SEP}\d{{2}}{_SEP}\d{{2}} at \d{{2}}{_SEP}\d{{2}}{_SEP}\d{{2}}"),
    re.compile(rf"\d{{4}}{_SEP}\d{{2}}{_SEP}\d{{2}} um \d{{2}}{_SEP}\d{{2}}{_SEP}\d{{2}}"),
    re.compile(rf"\d{{4}}{_SEP}\d{{2}}{_SEP}\d{{2}}T\d{{2}}{_SEP}\d{{2}}{_SEP}\d{{2}}"),
    re.compile(rf"\d{{8}}{_SEP}\d{{6}}"),
    re.compile(r"\d{14}"),
    re.compile(rf"\d{{4}}{_SEP}\d{{2}}{_SEP}\d{{2}}"),
    re.compile(r"\d{8}"),
    re.compile(rf"\d{{4}}{_SEP}\d{{2}}"),
    re.compile(r"\d{6}"),
]

# --------------------------------------------------------------------------
# Metadata tags
# --------------------------------------------------------------------------

#: Tags trusted as the authoritative capture time, most trusted first.
#:
#: For video, QuickTime:CreationDate leads because Apple stores the real capture
#: offset in it, so its local part is the wall clock at the place of capture -
#: the same thing DateTimeOriginal means for stills. Plain QuickTime CreateDate
#: is UTC and only becomes comparable via -api QuickTimeUTC.
PRIMARY_TAGS_VIDEO = ("CreationDate", "DateTimeOriginal", "CreateDate")

#: For stills, DateTimeOriginal is the authority and CreationDate must NOT be
#: consulted. On a JPEG that name belongs to something else entirely - on GoPro
#: photos it is a maker-note field exiftool cannot write ("Sorry,
#: GoPro:CreationDate doesn't exist or isn't writable"), holding whatever the
#: camera clock said. Trusting it would fail such files forever: the tool would
#: correct DateTimeOriginal, then validation would re-read the stale maker note
#: and report the same mismatch on every run.
PRIMARY_TAGS_STILL = ("DateTimeOriginal", "CreateDate")

#: Union, for deciding what counts as a *secondary* tag.
ALL_PRIMARY_TAGS = tuple(dict.fromkeys(PRIMARY_TAGS_VIDEO + PRIMARY_TAGS_STILL))

#: QuickTime atoms store UTC. Without this, every video is read 1-2h off.
QUICKTIME_ARGS = ["-api", "QuickTimeUTC"]

#: Containers whose dates live in UTC rather than in capture-local wall clock.
VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".3gp", ".3g2", ".avi", ".mts", ".m2ts", ".mqv"}


def primary_tags_for(suffix: str) -> tuple[str, ...]:
    """Which tags to trust, given what kind of file this is."""
    return PRIMARY_TAGS_VIDEO if suffix.lower() in VIDEO_SUFFIXES else PRIMARY_TAGS_STILL

#: Filesystem pseudo-tags. Never provenance on their own, but usable as a
#: time-of-day hint when they land on a date the filename already agrees with.
FS_TAGS = ("FileModifyDate", "FileCreateDate", "FileAccessDate", "FileInodeChangeDate")

# --------------------------------------------------------------------------
# Files and folders
# --------------------------------------------------------------------------

EXCLUDED_SUFFIXES = {".txt"}
EXIFTOOL_TMP_SUFFIX = "exiftool_tmp"

UNSUCCESSFUL_DIR = "_unsuccessful"
ZEROBYTE_DIR = "_zeroByte"
TMP_DIR = "_exiftoolTmp"

# --------------------------------------------------------------------------
# Timestamp plausibility
# --------------------------------------------------------------------------

#: Substituted when a filename carries a date but no time of day. Deliberately
#: not midnight, so a defaulted time is visually distinct from a real 00:00:00.
DEFAULT_TIME = (0, 1, 0)

#: Wide enough for scanned negatives; the upper bound rejects digit runs that
#: merely look like years.
MIN_YEAR = 1900
MAX_YEAR = datetime.now().year + 1

#: How far a filename timestamp and the embedded one may drift apart while still
#: counting as the same moment. Anything inside this window is left alone; only
#: a genuinely different timestamp is worth asking about.
#:
#: 24 hours comfortably covers the two routine causes of small disagreement -
#: a camera writing local time into a UTC field (at most 14h), and a date-only
#: filename defaulting to 00:01 while the metadata holds the real time of day.
#: A camera whose clock was reset is out by months or years, far outside it.
AGREEMENT_WINDOW = timedelta(hours=24)
