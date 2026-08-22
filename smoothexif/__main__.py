"""Allows ``python3 -m smoothexif DIR`` from the project root."""

import sys

from .cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
