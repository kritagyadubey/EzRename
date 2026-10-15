"""EzRename command line interface (standard library only)."""

from __future__ import annotations

__all__ = ["main"]


def main(argv=None) -> int:  # pragma: no cover - thin re-export
    from .main import main as _main

    return _main(argv)
