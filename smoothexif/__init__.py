"""smoothexif - normalise photo and video timestamps on macOS.

Metadata, filename and Finder date are made to agree, using whichever source is
most trustworthy for each file. See ``pipeline.run`` for the sequence and
``model.Bucket`` for the classification hierarchy.

Timezone policy: timestamps are kept as capture-local wall clock - the time the
clock showed where the shot was taken - and are never normalised to the
machine's resident timezone. A photo taken at 19:12 in California is named
19:12, not the Zurich rendering of that instant. EXIF DateTimeOriginal is
already capture-local; QuickTime CreationDate carries the capture offset, so it
outranks the UTC-based CreateDate. Videos with neither are the one unavoidable
exception - nothing in the file records where they were shot - and each is
listed at the end of a run so the guess is visible rather than silent.
"""

__version__ = "1.0.0"
