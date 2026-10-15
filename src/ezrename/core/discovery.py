"""Discovering, filtering and ordering the files a session will work on.

Scanning is deliberately conservative: directories are never included as
targets, symbolic links are skipped unless explicitly requested, and
EzRename's own temporary files are ignored.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from .models import FileRecord
from .naming import is_internal_name, natural_key, split_name

#: Sort keys accepted by the CLI ``--sort`` option and the GUI table.
SORT_KEYS = {
    "name": "file name (natural order: img2 before img10)",
    "name_ci": "file name, case-insensitive",
    "extension": "extension",
    "size": "file size",
    "modified": "modification date",
    "created": "creation date",
    "path": "full path",
    "added": "order the files were added",
}


@dataclass
class ScanResult:
    """Files found by a scan plus anything that went wrong."""

    records: list[FileRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    folders: int = 0
    skipped: int = 0

    def __len__(self) -> int:
        return len(self.records)


def _is_hidden_path(path: Path) -> bool:
    name = path.name
    if name.startswith("."):
        return True
    if os.name == "nt":
        try:
            attrs = os.stat(path).st_file_attributes  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            return False
        return bool(attrs & 0x2)
    return False


def scan_directory(
    root: Union[str, Path],
    *,
    recursive: bool = False,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
    extensions: Optional[Iterable[str]] = None,
    include_globs: Optional[Iterable[str]] = None,
    exclude_globs: Optional[Iterable[str]] = None,
    name_contains: str = "",
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    max_files: Optional[int] = None,
) -> ScanResult:
    """Collect the files under *root* that match every supplied filter."""

    root = Path(root)
    result = ScanResult()
    if not root.exists():
        result.errors.append(f"'{root}' does not exist")
        return result
    if not root.is_dir():
        result.errors.append(f"'{root}' is not a folder")
        return result

    wanted_ext = {ext.strip().lstrip(".").casefold() for ext in (extensions or []) if ext.strip()}
    includes = [pattern for pattern in (include_globs or []) if pattern]
    excludes = [pattern for pattern in (exclude_globs or []) if pattern]
    needle = name_contains.casefold()

    def accept(path: Path) -> bool:
        name = path.name
        if is_internal_name(name):
            return False
        if wanted_ext:
            extension = split_name(name)[1].casefold()
            if extension not in wanted_ext:
                return False
        if includes and not any(fnmatch.fnmatch(name, pattern) for pattern in includes):
            return False
        if excludes and any(fnmatch.fnmatch(name, pattern) for pattern in excludes):
            return False
        if needle and needle not in name.casefold():
            return False
        return True

    def walk(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: natural_key(item.name))
        except PermissionError:
            result.errors.append(f"access denied: '{directory}'")
            return
        except OSError as exc:
            result.errors.append(f"cannot read '{directory}': {exc.strerror or exc}")
            return
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.is_symlink():
                    if not follow_symlinks:
                        result.skipped += 1
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        result.skipped += 1
                        continue
                if entry.is_dir(follow_symlinks=False):
                    result.folders += 1
                    if recursive:
                        walk(path)
                    continue
                if not entry.is_file(follow_symlinks=follow_symlinks):
                    result.skipped += 1
                    continue
            except OSError as exc:
                result.errors.append(f"cannot inspect '{path}': {exc.strerror or exc}")
                continue
            if _is_hidden_path(path) and not include_hidden:
                result.skipped += 1
                continue
            if not accept(path):
                result.skipped += 1
                continue
            record = FileRecord.from_path(path)
            if min_size is not None and record.size < min_size:
                result.skipped += 1
                continue
            if max_size is not None and record.size > max_size:
                result.skipped += 1
                continue
            result.records.append(record)
            if max_files is not None and len(result.records) >= max_files:
                return

    walk(root)
    return result


def collect_records(
    paths: Iterable[Union[str, Path]],
    *,
    recursive: bool = False,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
) -> ScanResult:
    """Build records from a mixed list of files and folders (drag & drop)."""

    result = ScanResult()
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            scan = scan_directory(
                path,
                recursive=recursive,
                include_hidden=include_hidden,
                follow_symlinks=follow_symlinks,
            )
            result.errors.extend(scan.errors)
            result.folders += 1
            candidates = scan.records
        elif path.exists():
            if path.is_symlink() and not follow_symlinks:
                result.skipped += 1
                continue
            if is_internal_name(path.name):
                result.skipped += 1
                continue
            candidates = [FileRecord.from_path(path)]
        else:
            result.errors.append(f"'{path}' does not exist")
            continue
        for record in candidates:
            key = os.path.normcase(str(record.path))
            if key in seen:
                continue
            seen.add(key)
            result.records.append(record)
    return result


def filter_records(
    records: Sequence[FileRecord],
    *,
    search: str = "",
    extensions: Optional[Iterable[str]] = None,
    glob: str = "",
) -> list[FileRecord]:
    """Quick, in-memory filtering used by the GUI's search box."""

    wanted_ext = {ext.strip().lstrip(".").casefold() for ext in (extensions or []) if ext.strip()}
    needle = search.casefold().strip()
    out: list[FileRecord] = []
    for record in records:
        if wanted_ext and record.extension.casefold() not in wanted_ext:
            continue
        if glob and not fnmatch.fnmatch(record.name, glob):
            continue
        if needle and needle not in record.name.casefold() and needle not in str(record.path).casefold():
            continue
        out.append(record)
    return out


def sort_records(
    records: Sequence[FileRecord],
    key: str = "name",
    *,
    reverse: bool = False,
) -> list[FileRecord]:
    """Return *records* ordered by *key* (see :data:`SORT_KEYS`)."""

    if key not in SORT_KEYS:
        raise ValueError(f"unknown sort key '{key}' - choose from {', '.join(SORT_KEYS)}")
    if key == "added":
        return list(reversed(records)) if reverse else list(records)
    if key == "name":
        ordered = sorted(records, key=lambda record: natural_key(record.name), reverse=reverse)
    elif key == "name_ci":
        ordered = sorted(records, key=lambda record: record.name.casefold(), reverse=reverse)
    elif key == "extension":
        ordered = sorted(
            records,
            key=lambda record: (record.extension.casefold(), natural_key(record.name)),
            reverse=reverse,
        )
    elif key == "size":
        ordered = sorted(records, key=lambda record: (record.size, natural_key(record.name)), reverse=reverse)
    elif key == "modified":
        ordered = sorted(records, key=lambda record: (record.mtime, natural_key(record.name)), reverse=reverse)
    elif key == "created":
        ordered = sorted(records, key=lambda record: (record.ctime, natural_key(record.name)), reverse=reverse)
    else:  # path
        ordered = sorted(records, key=lambda record: natural_key(str(record.path)), reverse=reverse)
    return ordered
