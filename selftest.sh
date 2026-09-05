#!/bin/bash
# Exercise the whole pipeline end to end on disposable files.
#
# Builds throwaway folders containing one file per bucket, runs the full
# hierarchy, and asserts where every file ended up, what metadata it got, and
# what was deliberately left alone. Touches nothing outside its own temp
# directory.
#
#   ./selftest.sh          run and clean up
#   ./selftest.sh --keep   leave the folders behind for inspection
set -uo pipefail

SMOOTHEXIF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bin/smoothexif"
KEEP=0; [[ "${1:-}" == "--keep" ]] && KEEP=1
WORK="$(mktemp -d "${TMPDIR:-/tmp}/smoothexif-selftest.XXXXXX")"
DIR="$WORK/photos"; mkdir -p "$DIR"
PASS=0; FAIL=0

command -v exiftool >/dev/null || { echo "exiftool not found"; exit 2; }

# Smallest valid JPEG, so the fixture needs no external assets.
base64 -d > "$WORK/base.jpg" <<'B64'
/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a
HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA
AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==
B64

# The explicit returns matter: ((PASS++)) evaluates to 0 on the first call and
# so exits non-zero, which would make `ok ... || bad ...` report a false failure.
ok()   { printf '  \033[32mPASS\033[0m  %-4s %s\n' "$1" "$2"; ((PASS++)); return 0; }
bad()  { printf '  \033[31mFAIL\033[0m  %-4s %s\n' "$1" "$2"; ((FAIL++)); return 0; }

mk() { cp "$WORK/base.jpg" "$2/$1"; }
setexif() { local d="$1" f="$2"; shift 2; exiftool -q -m -overwrite_original "$@" "$d/$f"; }

exists()  { [[ -e "$2/$3" ]] && ok "$1" "$3" || bad "$1" "expected file: $3"; }
absent()  { [[ ! -e "$2/$3" ]] && ok "$1" "not renamed away: $3" || bad "$1" "should not exist: $3"; }

has_exif() { # has_exif <label> <dir> <file> <expected>
  local got; got="$(exiftool -s3 -DateTimeOriginal "$2/$3" 2>/dev/null)"
  [[ "$got" == "$4" ]] && ok "$1" "$3 exif=$4" \
                       || bad "$1" "$3 exif is \"$got\", want \"$4\""
}

finder_is() { # finder_is <label> <dir> <file> <MM/DD/YYYY HH:MM:SS>
  local got; got="$(GetFileInfo -d "$2/$3" 2>/dev/null)"
  [[ "$got" == "$4" ]] && ok "$1" "$3 finder=$4" \
                       || bad "$1" "$3 finder is \"$got\", want \"$4\""
}

# ==========================================================================
echo "=== fixture: one file per bucket ==="
: > "$DIR/empty.jpg"                                    # B0 zero byte
mk "leftover.jpg_exiftool_tmp"  "$DIR"                  # B0 exiftool remnant
mk "IMG_0001.jpg"               "$DIR"                  # B1 no date in name
mk "GX010001.jpg"               "$DIR"                  # B1 no date in name
mk "20240611_102233__already.jpg" "$DIR"                # B2 agrees
mk "20260101_120000_tzshift.jpg"  "$DIR"                # B2 within tolerance
mk "19920701_000100__scan.jpg"  "$DIR"                  # B3 conflict
mk "Screenshot 2024-03-05 at 10.11.12.jpg" "$DIR"       # B4 date mid-name
mk "threema-20260716-183755987.jpg" "$DIR"              # B4 date mid-name
mk "IMG-20260621-WA0001.jpg"    "$DIR"                  # B5 date mid-name, no time
mk "20140718_170000.jpeg"       "$DIR"                  # B4 bare canonical stem
mk "20191225_baredate.jpg"      "$DIR"                  # B5 date only
mk "202405_partial.jpg"         "$DIR"                  # B6 year-month only
mk "nothing.jpg"                "$DIR"                  # B8 nothing usable
setexif "$DIR" "IMG_0001.jpg"               -DateTimeOriginal="2023:09:14 16:45:02"
setexif "$DIR" "GX010001.jpg"               -DateTimeOriginal="2026:05:02 11:00:00"
setexif "$DIR" "20240611_102233__already.jpg" -AllDates="2024:06:11 10:22:33"
setexif "$DIR" "20260101_120000_tzshift.jpg"  -AllDates="2026:01:01 14:00:00"
setexif "$DIR" "19920701_000100__scan.jpg"    -AllDates="2019:03:04 07:00:00"
ls -1 "$DIR" | sed 's/^/  /'

echo
echo "=== full run (conflict -> filename, partial -> accept) ==="
printf 'f\ny\n' | "$SMOOTHEXIF" "$DIR"

echo
echo "=== B0: unreadable files quarantined ==="
exists B0 "$DIR" "_zeroByte/empty.jpg"
exists B0 "$DIR" "_exiftoolTmp/leftover.jpg_exiftool_tmp"

echo
echo "=== B1: no date in the name is the ONLY case that gets renamed ==="
exists B1 "$DIR" "20230914_164502__IMG_0001.jpg"
exists B1 "$DIR" "20260502_110000__GX010001.jpg"

echo
echo "=== a name that already LEADS with its date keeps it ==="
exists B2 "$DIR" "20240611_102233__already.jpg"
exists B3 "$DIR" "19920701_000100__scan.jpg"
has_exif B3 "$DIR" "19920701_000100__scan.jpg" "1992:07:01 00:01:00"
exists B4 "$DIR" "20140718_170000.jpeg"
has_exif B4 "$DIR" "20140718_170000.jpeg" "2014:07:18 17:00:00"
exists B5 "$DIR" "20191225_baredate.jpg"
has_exif B5 "$DIR" "20191225_baredate.jpg" "2019:12:25 00:01:00"
exists B6 "$DIR" "202405_partial.jpg"
has_exif B6 "$DIR" "202405_partial.jpg" "2024:05:01 00:01:00"
absent  B5 "$DIR" "20191225_000100__20191225_baredate.jpg"

echo
echo "=== a date MID-name gets prefixed, so the folder sorts ==="
exists B4 "$DIR" "20240305_101112__Screenshot 2024-03-05 at 10.11.12.jpg"
exists B4 "$DIR" "20260716_183755__threema-20260716-183755987.jpg"
exists B5 "$DIR" "20260621_000100__IMG-20260621-WA0001.jpg"
has_exif B4 "$DIR" "20260716_183755__threema-20260716-183755987.jpg" "2026:07:16 18:37:55"
absent  B4 "$DIR" "threema-20260716-183755987.jpg"

echo
echo "=== tolerance: metadata a few hours out is NOT rewritten ==="
has_exif TOL "$DIR" "20260101_120000_tzshift.jpg" "2026:01:01 14:00:00"

echo
echo "=== B8: nothing usable at all, filed away ==="
exists B8 "$DIR" "_unsuccessful/nothing.jpg"

echo
echo "=== Finder dates follow the chosen timestamp ==="
finder_is B1 "$DIR" "20230914_164502__IMG_0001.jpg"  "09/14/2023 16:45:02"
finder_is B3 "$DIR" "19920701_000100__scan.jpg"      "07/01/1992 00:01:00"
finder_is B5 "$DIR" "20191225_baredate.jpg"          "12/25/2019 00:01:00"
finder_is B6 "$DIR" "202405_partial.jpg"             "05/01/2024 00:01:00"

echo
echo "=== re-run must be idempotent ==="
RERUN="$(printf '' | "$SMOOTHEXIF" "$DIR" 2>&1)"
grep -q ", 0 renamed" <<<"$RERUN" && ok IDEM "second run renamed nothing" \
                                  || bad IDEM "second run renamed something"

echo
echo "=== -v reports and moves nothing ==="
BEFORE="$(ls "$DIR" | wc -l)"
VOUT="$("$SMOOTHEXIF" -v "$DIR" 2>&1)"; echo "$VOUT" | tail -1 | sed 's/^/  /'
if [[ "$(ls "$DIR" | wc -l)" == "$BEFORE" ]] && grep -q "0 failing" <<<"$VOUT"; then
  ok VAL "validation clean, nothing moved"
else
  bad VAL "validation moved files or reported failures"
fi

# ==========================================================================
echo
echo "=== --prefer filename: wrong camera clock, hand-renamed films ==="
GP="$WORK/gopro"; mkdir -p "$GP"
for n in "20240715_143000__dive1.jpg" "20240716_090000_surf.jpg" "20240717_120000-reef.jpg"; do
  mk "$n" "$GP"
done
exiftool -q -m -overwrite_original -AllDates="2015:01:01 00:00:00" "$GP"/*.jpg
"$SMOOTHEXIF" --prefer filename --non-interactive "$GP" >/dev/null 2>&1
has_exif PREF "$GP" "20240715_143000__dive1.jpg"  "2024:07:15 14:30:00"
has_exif PREF "$GP" "20240716_090000_surf.jpg"    "2024:07:16 09:00:00"
has_exif PREF "$GP" "20240717_120000-reef.jpg"    "2024:07:17 12:00:00"
absent   PREF "$GP" "20240716_090000__surf.jpg"

echo
echo "=== a declined conflict is left exactly where it was ==="
GP2="$WORK/declined"; mkdir -p "$GP2"
mk "20240715_143000__dive1.jpg" "$GP2"
exiftool -q -m -overwrite_original -AllDates="2015:01:01 00:00:00" "$GP2/20240715_143000__dive1.jpg"
"$SMOOTHEXIF" --non-interactive "$GP2" >/dev/null 2>&1
exists   SKIP "$GP2" "20240715_143000__dive1.jpg"
has_exif SKIP "$GP2" "20240715_143000__dive1.jpg" "2015:01:01 00:00:00"

echo
echo "=== --normalise-names still forces the canonical form ==="
NM="$WORK/normalise"; mkdir -p "$NM"
mk "20240716_090000_surf.jpg" "$NM"
setexif "$NM" "20240716_090000_surf.jpg" -AllDates="2024:07:16 09:00:00"
"$SMOOTHEXIF" --normalise-names --non-interactive "$NM" >/dev/null 2>&1
exists NORM "$NM" "20240716_090000__surf.jpg"

echo
echo "=== B7: secondary tags always ask; declining files it away ==="
# Kept out of the interactive run above so the test never opens Preview.
SEC="$WORK/secondary"; mkdir -p "$SEC"
mk "onlymodify.jpg" "$SEC"
setexif "$SEC" "onlymodify.jpg" -ModifyDate="2015:05:05 05:05:05"
"$SMOOTHEXIF" --non-interactive "$SEC" >/dev/null 2>&1
exists B7 "$SEC" "_unsuccessful/onlymodify.jpg"

echo
echo "=== B7: the picker itself (Preview stubbed out) ==="
python3 - "$(dirname "$SMOOTHEXIF")/.." <<'PY'
import sys, datetime
from pathlib import Path
from unittest import mock
sys.path.insert(0, sys.argv[1])
from smoothexif.model import Item
from smoothexif.prompts import Prompter
from smoothexif import prompts

item = Item(path=Path("/tmp/x.jpg"), body="x", ext=".jpg")
item.secondary = [("FileModifyDate", datetime.datetime(2020, 1, 1)),
                  ("ModifyDate", datetime.datetime(2015, 5, 5, 5, 5, 5))]
fails = 0
if [t for t, _ in item.real_secondary] != ["ModifyDate"]:
    print("  \033[31mFAIL\033[0m  B7   filesystem tags not filtered out"); fails += 1
else:
    print("  \033[32mPASS\033[0m  B7   filesystem tags filtered from the picker")

with mock.patch.object(prompts.subprocess, "run"), mock.patch("builtins.input", return_value="0"):
    picked = Prompter(interactive=True).preview_pick(item)
if picked != datetime.datetime(2015, 5, 5, 5, 5, 5):
    print(f"  \033[31mFAIL\033[0m  B7   picker returned {picked}"); fails += 1
else:
    print("  \033[32mPASS\033[0m  B7   picking an index returns that timestamp")

with mock.patch.object(prompts.subprocess, "run"), mock.patch("builtins.input", return_value="-"):
    declined = Prompter(interactive=True).preview_pick(item)
if declined is not None:
    print(f"  \033[31mFAIL\033[0m  B7   declining returned {declined}"); fails += 1
else:
    print("  \033[32mPASS\033[0m  B7   declining returns nothing")
sys.exit(1 if fails else 0)
PY
if [[ $? -eq 0 ]]; then ((PASS+=3)); else ((FAIL++)); fi

echo
echo "=== sleep is held off for the duration of a run ==="
python3 - "$(dirname "$SMOOTHEXIF")/.." <<'PY'
import os, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
from smoothexif.macos import prevent_sleep

fails = 0
handle = prevent_sleep()
if handle is None:
    print("  \033[31mFAIL\033[0m  CAF  caffeinate could not be started"); fails += 1
else:
    time.sleep(0.3)
    args = subprocess.run(["ps", "-p", str(handle.pid), "-o", "args="],
                          capture_output=True, text=True).stdout
    if str(os.getpid()) in args and "-w" in args:
        print("  \033[32mPASS\033[0m  CAF  caffeinate watches this process")
    else:
        print(f"  \033[31mFAIL\033[0m  CAF  unexpected args: {args.strip()}"); fails += 1
    assertions = subprocess.run(["pmset", "-g", "assertions"],
                                capture_output=True, text=True).stdout
    if f"Process ID {os.getpid()}" in assertions:
        print("  \033[32mPASS\033[0m  CAF  a real sleep assertion is registered")
    elif "caffeinate" not in assertions:
        # Headless CI runners may not report power assertions at all. That is
        # the host's behaviour, not ours - we already proved caffeinate runs.
        print("  \033[33mSKIP\033[0m  CAF  host reports no power assertions")
    else:
        print("  \033[31mFAIL\033[0m  CAF  no sleep assertion found"); fails += 1
    handle.terminate()
sys.exit(1 if fails else 0)
PY
if [[ $? -eq 0 ]]; then ((PASS+=2)); else ((FAIL++)); fi

# The watcher must not outlive the run it was started for.
LEAK_BEFORE=$(pgrep -f 'caffeinate -i -s -w' | wc -l | tr -d ' ')
"$SMOOTHEXIF" -v "$DIR" >/dev/null 2>&1
sleep 1
LEAK_AFTER=$(pgrep -f 'caffeinate -i -s -w' | wc -l | tr -d ' ')
if [[ "$LEAK_AFTER" -le "$LEAK_BEFORE" ]]; then
  ok CAF "no caffeinate process left behind"
else
  bad CAF "leaked a caffeinate process ($LEAK_BEFORE -> $LEAK_AFTER)"
fi

echo
echo "=== a wrong prefix is corrected, not preserved ==="
# Leading with *a* timestamp is not enough; it must be the one chosen. Keeping a
# disagreeing prefix left the file failing validation on every future run.
WP="$WORK/wrongprefix"; mkdir -p "$WP"
mk "20201111_101010__20241223_115548000_iOS.jpg" "$WP"
setexif "$WP" "20201111_101010__20241223_115548000_iOS.jpg" -AllDates="2024:12:23 11:55:48"
printf 'e\n' | "$SMOOTHEXIF" "$WP" >/dev/null 2>&1
# Stripping the bad prefix uncovers a name that already leads correctly.
exists WRONGPFX "$WP" "20241223_115548000_iOS.jpg"
VOUT="$("$SMOOTHEXIF" -v "$WP" 2>&1)"
grep -q "0 failing" <<<"$VOUT" && ok WRONGPFX "validates cleanly afterwards" \
                               || bad WRONGPFX "still failing: $(grep warn <<<"$VOUT" | head -1)"

echo
echo "=== tolerance: hours are noise, half a day is not ==="
TOL="$WORK/tolerance"; mkdir -p "$TOL"
mk "20260101_120000_tz.jpg" "$TOL"                       # 2h apart - timezone artefact
setexif "$TOL" "20260101_120000_tz.jpg" -AllDates="2026:01:01 14:00:00"
mk "20241222_202000__real.jpg" "$TOL"                    # 15.5h apart - a real error
setexif "$TOL" "20241222_202000__real.jpg" -AllDates="2024:12:23 11:55:48"
PLAN="$("$SMOOTHEXIF" --dry-run --non-interactive "$TOL" 2>&1)"
grep -q "B2=1" <<<"$PLAN" && ok TOL "a 2h shift is accepted silently" \
                          || bad TOL "2h shift not treated as agreement"
grep -q "B3=1" <<<"$PLAN" && ok TOL "a 15h gap is raised as a conflict" \
                          || bad TOL "15h gap was waved through"

echo
echo "=== writes stay minimal (no invented XMP) ==="
BL="$WORK/bloat"; mkdir -p "$BL"
mk "20240101_100000_nodates.jpg" "$BL"
"$SMOOTHEXIF" --non-interactive "$BL" >/dev/null 2>&1
JUNK=$(exiftool -G1 -a -s -time:all "$BL/20240101_100000_nodates.jpg" 2>/dev/null \
       | grep -cE 'DICOM|dwc|XMP-plus|prism|XMP-pur|getty|pdfx')
if [[ "$JUNK" -eq 0 ]]; then
  ok BLOAT "no unrelated date tags invented"
else
  bad BLOAT "$JUNK junk tags written (-time:all= regression)"
fi

echo
echo "=== a still must ignore CreationDate (GoPro maker-note trap) ==="
# On a JPEG, 'CreationDate' is not QuickTime's tag. GoPro photos carry an
# unwritable maker-note field of that name holding whatever the camera clock
# said; trusting it failed such files on every run, forever, because the tool
# could correct DateTimeOriginal but never that.
GT="$WORK/gopro-still"; mkdir -p "$GT"
mk "20240101_100000__GOPR0001.jpg" "$GT"
setexif "$GT" "20240101_100000__GOPR0001.jpg" -AllDates="2024:01:01 10:00:00"
exiftool -q -m -overwrite_original \
  "-XMP-pdf:CreationDate=2019:09:09 09:09:09" "$GT/20240101_100000__GOPR0001.jpg"
VOUT="$("$SMOOTHEXIF" -v "$GT" 2>&1)"
if grep -q "0 failing" <<<"$VOUT"; then
  ok STILL "CreationDate ignored on a still; DateTimeOriginal wins"
else
  bad STILL "still trusted CreationDate: $(grep warn <<<"$VOUT" | head -1)"
fi

echo
echo "=== two runs on one folder: the second refuses instead of racing ==="
LOCKDIR="$WORK/locked"; mkdir -p "$LOCKDIR"
mk "IMG_1.jpg" "$LOCKDIR"
setexif "$LOCKDIR" "IMG_1.jpg" -AllDates="2024:01:01 10:00:00"
python3 - "$(dirname "$SMOOTHEXIF")/.." "$SMOOTHEXIF" "$LOCKDIR" <<'PY'
import subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from smoothexif.files import directory_lock

exe, target = sys.argv[2], Path(sys.argv[3]).resolve()
fails = 0
with directory_lock(target):                      # stand in for a run in progress
    busy = subprocess.run([exe, "--non-interactive", str(target)],
                          capture_output=True, text=True)
    if busy.returncode == 3 and "already running" in busy.stderr:
        print("  \033[32mPASS\033[0m  LOCK a concurrent run is refused, exit 3")
    else:
        print(f"  \033[31mFAIL\033[0m  LOCK rc={busy.returncode} err={busy.stderr.strip()[:60]}")
        fails += 1
    # A read-only preview must not be blocked by someone else's run.
    dry = subprocess.run([exe, "--dry-run", "--non-interactive", str(target)],
                         capture_output=True, text=True)
    if dry.returncode == 0:
        print("  \033[32mPASS\033[0m  LOCK --dry-run is not blocked")
    else:
        print(f"  \033[31mFAIL\033[0m  LOCK --dry-run blocked (rc={dry.returncode})"); fails += 1

after = subprocess.run([exe, "--non-interactive", str(target)], capture_output=True, text=True)
if after.returncode == 0:
    print("  \033[32mPASS\033[0m  LOCK released when the holder finishes")
else:
    print(f"  \033[31mFAIL\033[0m  LOCK still held (rc={after.returncode})"); fails += 1
sys.exit(1 if fails else 0)
PY
if [[ $? -eq 0 ]]; then ((PASS+=3)); else ((FAIL++)); fi

echo
echo "======================================"
printf '  %d passed, %d failed\n' "$PASS" "$FAIL"
echo "======================================"
if [[ $KEEP -eq 1 ]]; then echo "fixtures kept at: $WORK"; else rm -rf "$WORK"; fi
exit $(( FAIL > 0 ))
