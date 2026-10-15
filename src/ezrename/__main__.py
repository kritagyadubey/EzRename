"""``python -m ezrename`` opens the graphical application."""

from __future__ import annotations

import sys


def run() -> int:
    from ezrename.gui.app import main

    return main()


if __name__ == "__main__":
    sys.exit(run())
