"""Shared pytest fixtures.

Tests always run against disposable temporary folders and an isolated
``EZRENAME_HOME`` so no real user settings or history are ever touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ezrename.core.discovery import scan_directory, sort_records  # noqa: E402
from ezrename.core.history import HistoryStore  # noqa: E402
from ezrename.core.models import FileRecord  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Point every settings/history lookup at a throwaway folder."""

    home = tmp_path_factory.mktemp("ezrename-home")
    monkeypatch.setenv("EZRENAME_HOME", str(home))
    monkeypatch.delenv("EZRENAME_ASSUME_YES", raising=False)
    yield home


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    return work


def make_files(folder: Path, names, *, content: str = "data") -> list[Path]:
    """Create files with the given names and return their paths."""

    created = []
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{content}:{name}", encoding="utf-8")
        created.append(path)
    return created


def records_for(folder: Path, *, recursive: bool = False, hidden: bool = False) -> list[FileRecord]:
    """Scan a folder and return naturally sorted records."""

    scan = scan_directory(folder, recursive=recursive, include_hidden=hidden)
    return sort_records(scan.records, "name")


@pytest.fixture
def files(folder: Path):
    """Factory fixture: ``files(["a.txt", "b.txt"])`` -> list of paths."""

    def _factory(names, *, content: str = "data"):
        return make_files(folder, names, content=content)

    return _factory


@pytest.fixture
def history(tmp_path: Path) -> HistoryStore:
    store = HistoryStore(tmp_path / "history.db")
    yield store
    store.close()


@pytest.fixture
def names(folder: Path):
    """Return the sorted file names currently in the folder."""

    def _names() -> list[str]:
        return sorted(path.name for path in folder.iterdir())

    return _names
