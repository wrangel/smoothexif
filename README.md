# smoothexif

**macOS only.** Normalise photo and video timestamps so that the **filename**,
the **embedded metadata** and the **Finder dates** all agree.

Requires macOS, Python 3.9+ and [exiftool](https://exiftool.org)
(`brew install exiftool`). No other dependencies, no build step. It relies on
`setattrlist`, `st_birthtime`, `GetFileInfo`, `osascript` and `caffeinate`, so
it will not run on Linux or Windows.

## Before you point this at your photos

smoothexif **renames files and rewrites embedded metadata in place**. On
irreplaceable originals, that deserves a moment's care:

* **Always `--dry-run` first.** It writes nothing, renames nothing, moves
  nothing, and prints exactly what it would do. Verified by test.
* **Try a copy of one folder** before a whole library.
* **Nothing is ever deleted.** Files it cannot resolve are moved to
  `_unsuccessful/` in the same directory; zero-byte files to `_zeroByte/`.
* **`-v` is read-only** and safe to run on anything, at any time.
* **`--prefer filename` overwrites metadata from filenames on every conflicting
  file.** Point it only at folders where you know the camera clock was wrong.
* If the folder is watched by a sync agent (Dropbox, OneDrive, Synology Cloud
  Sync), **pause it first** — exiftool writes a temporary file and renames over
  the original, and a sync agent can upload the half-written state.

```bash
bin/smoothexif --dry-run ~/Pictures/import   # show the plan, change nothing
bin/smoothexif ~/Pictures/import             # apply it
bin/smoothexif -v ~/Pictures/import          # check only, move nothing
```

---

## How a run works

One scan, one classification, then the buckets are resolved in order. ExifTool
is invoked a **fixed number of times per run, never once per file** — one bulk
read, one batched write, one verification read.

| Bucket | Situation | Action |
| ------ | --------- | ------ |
| `B1` | primary metadata, no filename timestamp | rename from metadata |
| `B2` | metadata and filename agree | nothing (Finder dates only) |
| `B3` | metadata and filename **genuinely** disagree | **ask** (or `--prefer`) |
| `B4` | no primary metadata, full filename timestamp | write metadata |
| `B5` | no primary metadata, date-only filename | borrow a time from a same-day tag |
| `B6` | no primary metadata, year-month filename | **ask** |
| `B7` | no primary metadata, secondary tags only | **ask** — shows the file in Preview |
| `B8` | nothing usable | `_unsuccessful/` |

Zero-byte files and leftover `*_exiftool_tmp` files are moved aside before any
metadata is read. Whether a file gets renamed is a separate question from which
bucket it is in — see below.

## Renaming

The goal is a folder that **sorts by date**, with the least disturbance to names
that already work. So the test is simply where the timestamp sits:

| Name | Example | Result |
| ---- | ------- | ------ |
| starts with a date | `20260614_162415000_iOS.jpg` | **left alone** — already sorts |
| date mid-name | `IMG-20260621-WA0001.jpg` | prefixed → `20260621_000100__IMG-20260621-WA0001.jpg` |
| no date at all | `GX010001.MP4` | prefixed from metadata |

Prefixes are `YYYYMMDD_HHMMSS__`. An existing one is recognised whether written
with `__`, a single separator, or standing alone as the whole name, so re-runs
are idempotent and never duplicate it. `--normalise-names` forces every file
into the canonical form regardless.

## When metadata gets rewritten

Only when it is **genuinely different** from the filename, and only after asking.
Anything within `AGREEMENT_WINDOW` (3 hours, in `config.py`) counts as agreement
and is left untouched — that absorbs a camera writing local time into a field
defined as UTC. A camera whose clock was reset is out by months or years, far
outside it.

Date-only and year-month filenames never reach that window: they are compared by
calendar day and by month respectively, so a name defaulting to `00:01` does not
conflict with metadata holding the real time of day.

Answering `s` at a conflict leaves that file completely alone — it is not
renamed, not rewritten, and not moved aside by the validation pass.

## Options

| Flag | Meaning |
| ---- | ------- |
| `-n`, `--dry-run` | print the plan; nothing is renamed, written, moved or created |
| `-v`, `--validate-only` | check filename prefixes against metadata; **moves nothing** unless `--quarantine` |
| `--prefer exif\|filename` | resolve every conflict the same way instead of asking |
| `--non-interactive` | never prompt; ambiguous files go to `_unsuccessful/` |
| `--quarantine` | with `-v`, also move failing files aside |
| `--normalise-names` | force every name into `YYYYMMDD_HHMMSS__original` form |
| `--no-caffeinate` | allow the Mac to idle-sleep during the run |

### Wrong camera clock

A GoPro that lost its clock stamps every file with a date near its reset epoch.
If the files were renamed correctly afterwards, the filename is the only
trustworthy record:

```bash
bin/smoothexif --prefer filename ~/Pictures/gopro
```

This overwrites metadata from filenames on **every** conflicting file, so point
it at a folder where the metadata is known to be wrong. In mixed folders, use
the default and answer `F` at the first prompt once the pattern is clear.

## Timezone policy

Timestamps are kept as **capture-local wall clock** — the time the clock showed
where the shot was taken — and are never normalised to this machine's timezone.
A photo taken at 19:12 in California is named `19:12`, not the Zurich rendering
of that instant.

* `DateTimeOriginal` is already capture-local.
* QuickTime `CreationDate` carries the capture offset, so it outranks the
  UTC-based `CreateDate`. Reads and writes pass `-api QuickTimeUTC`; without it
  every video lands 1–2 hours out.
* A video with neither tag is the one unavoidable exception — nothing in the
  file records where it was shot — so the instant is rendered locally and each
  such file is **listed at the end of the run**.

## Layout

```
bin/smoothexif        executable entry point
smoothexif/
  config.py           naming convention, tags, thresholds — all policy lives here
  console.py          output
  timestamps.py       pure parsing: metadata strings and filename heuristics
  macos.py            Finder dates via the setattrlist syscall
  exiftool.py         the only module that shells out to exiftool
  files.py            listing, collision-safe moving and renaming
  model.py            Item, Bucket, classification
  prompts.py          interactive questions with sticky answers
  pipeline.py         scan -> decide -> plan -> execute -> verify
  cli.py              argument parsing
selftest.sh           end-to-end test on throwaway files
```

`build_plan()` is pure and `execute_plan()` is the only function that changes
anything on disk, so `--dry-run` is not a flag threaded through the write path —
it simply never executes.

## Testing

```bash
./selftest.sh
```

50 assertions over throwaway files in `$TMPDIR`, covering every bucket. Among
them: where each file lands, what metadata it gets, that Finder dates match the
filename, that a second run renames nothing, that `-v` moves nothing, that a
conflict is never silently resolved without `--prefer`, that a wrong prefix is
corrected rather than preserved, that a still ignores `CreationDate` (the GoPro
maker-note trap), that writes invent no unrelated XMP, that a declined conflict
stays put, that sleep is held off and released, and that two runs on one folder
refuse rather than race.

Exits non-zero on failure. It touches nothing outside its own temp directory,
and never opens Preview.

`./selftest.sh --keep` leaves the folder behind for inspection.

## Running several at once

Separate folders in parallel terminal tabs is fine and fully supported — each
run is independent, and each holds its own sleep assertion, so the Mac stays
awake until the last one finishes.

Two runs on the **same** folder is refused: each would plan against a snapshot
the other is busy invalidating, tripping over half-finished renames and leaving
spurious `-1` duplicates. The second run exits 3 with a clear message. The lock
is an `flock` in the temp dir keyed by the folder path, so nothing is written
into the photo folder and the kernel releases it however the process dies —
there is no stale lock to clean up. `--dry-run` and `-v` are read-only and are
never blocked.

## Sleep

Rewriting a video library is tens of GB of I/O over many minutes with no
keyboard activity — precisely when a Mac decides to idle-sleep. Every run
therefore holds sleep off via `caffeinate -w`, which watches the process and
exits by itself when the run ends, so nothing is left behind even if it is
killed. Closing the lid still sleeps the machine; nothing can prevent that.
`--no-caffeinate` opts out.

## Conventions are yours to change

Every naming and tolerance decision lives in `smoothexif/config.py`, in one
place, and none of it is universal — these are one photographer's choices:

| setting | default | meaning |
| ------- | ------- | ------- |
| `PREFIX_FMT` / `PARTITION` | `%Y%m%d_%H%M%S` + `__` | the prefix written for files that need one |
| `DEFAULT_TIME` | `00:01:00` | substituted when a filename has a date but no time; deliberately not midnight, so a defaulted time is recognisable |
| `AGREEMENT_WINDOW` | 3 hours | how far filename and metadata may drift before it counts as a conflict |
| `MIN_YEAR` | 1900 | lower bound for a plausible date; raise it to reject more false matches |
| `FILENAME_PATTERNS` | see file | timestamp shapes recognised in filenames, including German `um` and English `at` screenshot names |
| `PRIMARY_TAGS_*` | see file | which tags are trusted, separately for stills and video |

Change them there rather than through the command line; `./selftest.sh` will
tell you if a change breaks an assumption.

## Notes

* **Not recursive.** One directory level, by design. Flatten first if needed.
* Large videos are slow: exiftool rewrites the container to change metadata, so
  a folder of 4 GB films means tens of GB of I/O. Stills run at roughly 500
  files in a couple of seconds.
* Nothing is ever deleted. Unresolved files are moved to `_unsuccessful/`.

## License

MIT — see [LICENSE](LICENSE).

Successor to [wrangel/exifgrinder](https://github.com/wrangel/exifgrinder), a
Scala implementation of the same idea. This rewrite batches every exiftool call
instead of spawning one per file, which on stills is roughly 140× faster.
