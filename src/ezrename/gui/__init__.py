"""PySide6 desktop application.

Importing this package does not import Qt at all: the CLI can stay completely
headless, and ``ezrename gui`` pulls the toolkit in only when it is asked for.
"""

from __future__ import annotations

__all__ = ["launch", "main"]


def launch(folder=None, **kwargs):  # pragma: no cover - thin re-export
    from .app import launch as _launch

    return _launch(folder, **kwargs)


def main(argv=None) -> int:  # pragma: no cover - thin re-export
    from .app import main as _main

    return _main(argv)
