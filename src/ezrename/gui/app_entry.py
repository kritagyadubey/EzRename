"""Entry point used by the packaged ``EzRename.exe``.

Kept separate from :mod:`ezrename.gui.app` so PyInstaller has a real script to
run (a console-less executable cannot use ``-m``), while ``python -m ezrename``
and the CLI keep importing :mod:`ezrename.gui.app` normally.
"""

from __future__ import annotations

import multiprocessing
import sys


def run() -> int:
    from ezrename.gui.app import main

    return main()


if __name__ == "__main__":
    #: Frozen windowed builds must never try to spawn a console process.
    multiprocessing.freeze_support()
    sys.exit(run())
