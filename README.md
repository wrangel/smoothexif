# smoothexif

Normalise photo and video timestamps on macOS, so that the **filename**, the
**embedded metadata** and the **Finder dates** all agree.

Requires macOS, Python 3.9+ and [exiftool](https://exiftool.org)
(`brew install exiftool`). No other dependencies, no build step.

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
Anything within `AGREEMENT_WINDOW` (24 hours, in `config.py`) counts as
agreement and is left untouched — that covers a camera writing local time into a
UTC field, and a date-only filename defaulting to 00:01 while the metadata holds
the real time of day. A camera whose clock was reset is out by months or years,
far outside it.

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

Builds a throwaway folder in `$TMPDIR` covering every bucket, runs the full
hierarchy, and asserts where each file landed, what metadata it got, that Finder
dates match the filename, that a second run renames nothing, that `-v` moves
nothing, and that a conflict is never silently overwritten without `--prefer`.
Exits non-zero on failure. It touches nothing outside its own temp directory.

`./selftest.sh --keep` leaves the folder behind for inspection.

## Notes

* **Not recursive.** One directory level, by design. Flatten first if needed.
* Large videos are slow: exiftool rewrites the container to change metadata, so
  a folder of 4 GB films means tens of GB of I/O. Stills run at roughly 500
  files in a couple of seconds.
* Nothing is ever deleted. Unresolved files are moved to `_unsuccessful/`.
