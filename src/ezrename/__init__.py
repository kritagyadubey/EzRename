"""EzRename - safe, previewable bulk file renaming.

The package is split into three layers:

``ezrename.core``
    Platform aware renaming engine, validation, history and settings. Pure
    standard library, no GUI toolkit import, so it runs anywhere Python runs.
``ezrename.cli``
    The command line interface built on :mod:`argparse`.
``ezrename.gui``
    The PySide6 desktop application (imported lazily so the CLI stays headless).
"""

from __future__ import annotations

__all__ = ["__version__", "APP_NAME", "APP_URL", "VERSION_TUPLE"]

APP_NAME = "EzRename"
APP_URL = "https://github.com/kritagyadubey/EzRename"

__version__ = "1.0.0"

VERSION_TUPLE = tuple(int(part) for part in __version__.split(".") if part.isdigit())
