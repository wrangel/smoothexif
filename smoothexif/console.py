"""Terminal output. Kept trivial and dependency-free on purpose."""

from __future__ import annotations

import os
import sys

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(text: str) -> str:
    return _paint("1", text)


def info(msg: str) -> None:
    print(msg)


def warn(msg: str) -> None:
    print(_paint("33", f"warn  {msg}"))


def err(msg: str) -> None:
    print(_paint("31", f"error {msg}"), file=sys.stderr)


def heading(text: str) -> None:
    """Section header, blank-line separated from whatever came before."""
    print(bold(f"\n{text}"))
