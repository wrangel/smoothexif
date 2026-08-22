"""Interactive questions, with sticky answers.

A conflicted import can be hundreds of files with the same underlying cause, so
every question offers a capitalised variant that pins the answer for the rest of
the run. Non-tty stdin is safe: input() raises EOFError, which is treated as a
skip rather than an error.
"""

from __future__ import annotations

import subprocess
from datetime import datetime

from . import console
from .model import Item


class Choice:
    """Answers conflict() can return."""

    EXIF = "e"
    FILENAME = "f"
    SKIP = "s"


class Prompter:
    def __init__(self, interactive: bool = True, conflict_default: str | None = None):
        self.interactive = interactive
        #: Pinned by --prefer, or by answering E/F once during a run.
        self.conflict_default = conflict_default
        self.month_default: bool | None = None
        #: Set once Preview has been opened, so the caller knows to quit it.
        self.previewed = False

    def _ask(self, prompt: str, valid: set[str]) -> str:
        while True:
            try:
                answer = input(prompt).strip()
            except EOFError:
                return Choice.SKIP
            if answer in valid:
                return answer
            print(f"  please answer one of: {', '.join(sorted(valid))}")

    def conflict(self, item: Item) -> str:
        """Ask which source to trust when EXIF and filename disagree."""
        # A pinned preference applies even to non-interactive runs.
        if self.conflict_default:
            return self.conflict_default
        if not self.interactive:
            return Choice.SKIP
        print()
        print(console.bold(f"CONFLICT  {item.path.name}"))
        print(f"    EXIF {item.exif_primary_tag:<18} {item.exif_primary}")
        print(f"    filename {'':<14} {item.name_ts}")
        answer = self._ask(
            "    [e] exif  [f] filename  [E] always exif  [F] always filename  [s] skip > ",
            {"e", "f", "E", "F", "s"},
        )
        if answer in ("E", "F"):
            self.conflict_default = answer.lower()
            return self.conflict_default
        return answer

    def month(self, item: Item) -> bool:
        """Confirm a year-month filename should become the first of that month."""
        if not self.interactive:
            return False
        if self.month_default is not None:
            return self.month_default
        print()
        print(console.bold(f"PARTIAL   {item.path.name}"))
        print(f"    filename suggests {item.name_ts:%Y-%m} -> {item.name_ts}")
        answer = self._ask(
            "    [y] accept  [n] skip  [Y] always accept  [N] never accept > ",
            {"y", "n", "Y", "N"},
        )
        if answer in ("Y", "N"):
            self.month_default = answer == "Y"
            return self.month_default
        return answer == "y"

    def preview_pick(self, item: Item) -> datetime | None:
        """Show the file in Preview and let the user choose a secondary tag."""
        candidates = item.real_secondary
        if not self.interactive or not candidates:
            return None
        subprocess.run(["open", "-a", "Preview", str(item.path)], capture_output=True)
        self.previewed = True
        print()
        print(console.bold(f"SECONDARY {item.path.name}"))
        for index, (tag, dt) in enumerate(candidates):
            print(f"    [{index}] {tag:<24} {dt}")
        valid = {str(i) for i in range(len(candidates))} | {"-"}
        answer = self._ask("    pick an index, or [-] none > ", valid)
        close_preview_window()
        return None if answer == "-" else candidates[int(answer)][1]


def close_preview_window() -> None:
    subprocess.run(
        ["osascript", "-e", 'tell application "Preview" to close first window'],
        capture_output=True,
    )


def quit_preview() -> None:
    subprocess.run(["osascript", "-e", 'quit app "Preview"'], capture_output=True)
