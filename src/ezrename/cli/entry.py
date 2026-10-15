"""Entry point used by the packaged ``ezrename-cli.exe``.

PyInstaller executes the script as a top-level module, so the entry point uses
absolute imports and keeps :mod:`ezrename.cli.main` importable as a package
module for tests and console scripts.
"""

from __future__ import annotations

import sys


def run() -> int:
    from ezrename.cli.main import main

    return main()


if __name__ == "__main__":
    sys.exit(run())
