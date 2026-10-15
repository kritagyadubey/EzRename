"""Filename rules, validation and filesystem capability probing.

EzRename targets Windows first, but the engine must not fall apart on Linux or
macOS, so every platform specific rule is expressed as an explicit policy
instead of being scattered through the code base.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Optional

#: Characters Windows forbids in a file name component.
INVALID_CHARS = '<>:"/\\|?*'

#: Windows device names that cannot be used as file names, with or without
#: an extension (``CON.txt`` is just as reserved as ``CON``).
RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

#: Maximum length of a single name component on NTFS/ext4.
MAX_COMPONENT_LENGTH = 255

#: Legacy Win32 MAX_PATH limit, still relevant for many shell operations.
MAX_PATH_LENGTH = 260

#: Prefix used for intermediate names during two-phase renames. Files matching
#: it are always excluded from scans so a crashed run can never re-rename its
#: own temporaries.
TEMP_PREFIX = ".ezrename-tmp."

#: Prefix used for quarantined destination files when the user explicitly asks
#: to overwrite an existing file.
BACKUP_PREFIX = ".ezrename-backup."


def is_windows() -> bool:
    """Return ``True`` when running on Windows."""

    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def case_insensitive_filesystem() -> bool:
    """Best effort detection of a case-insensitive filesystem.

    Windows and macOS default filesystems are case-insensitive, Linux is
    usually case-sensitive. This drives collision detection: on Windows
    ``Report.txt`` and ``report.txt`` are the same file and must be treated as
    a conflict, while on Linux they may coexist.
    """

    if is_windows() or is_macos():
        return True
    return False


def fold(name: str) -> str:
    """Return a comparison key for *name* honouring filesystem case rules."""

    return name.casefold() if case_insensitive_filesystem() else name


def is_hidden(path: Path) -> bool:
    """Return ``True`` if *path* is hidden (Windows attribute or dot prefix)."""

    name = path.name
    if name.startswith("."):
        return True
    if is_windows():
        try:
            attrs = os.stat(path).st_file_attributes  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            return False
        return bool(attrs & 0x2)  # FILE_ATTRIBUTE_HIDDEN
    return False


def split_name(name: str) -> tuple[str, str]:
    """Split *name* into ``(stem, extension)`` without the leading dot.

    Multi-dot names keep every dot but the last in the stem:
    ``archive.tar.gz`` -> ``("archive.tar", "gz")``. Dotfiles such as
    ``.gitignore`` are treated as having no extension, matching the way
    Explorer displays them.
    """

    if name in ("", ".", ".."):
        return name, ""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or not ext:
        # No extension, a leading dot (dotfile) or a trailing dot. Keeping the
        # whole name as the stem means an invalid trailing dot is never
        # silently dropped by the round trip through the name parts.
        return name, ""
    return stem, ext


def join_name(stem: str, ext: str) -> str:
    """Compose a file name from *stem* and *ext* (extension without dot)."""

    if not ext:
        return stem
    return f"{stem}.{ext}"


def strip_hidden_prefix(name: str) -> str:
    """Return *name* without a single leading dot, if any."""

    return name[1:] if name.startswith(".") else name


def sanitize_fragment(text: str, replacement: str = "_", *, allow_spaces: bool = True) -> str:
    """Replace characters that are illegal in a Windows name component.

    This is used for values injected by templates (dates, sizes) rather than
    for user supplied names: a user supplied name that becomes invalid is
    reported as an error instead of being silently mangled.
    """

    out = []
    for char in text:
        if char in INVALID_CHARS or _CONTROL_RE.match(char):
            out.append(replacement)
        elif char == " " and not allow_spaces:
            out.append(replacement)
        else:
            out.append(char)
    return "".join(out)


def validate_filename(name: str, *, max_length: int = MAX_COMPONENT_LENGTH) -> Optional[str]:
    """Return a human readable problem description, or ``None`` if valid.

    The rules mirror what Explorer itself refuses to create on NTFS so the
    preview never promises a rename the filesystem would reject.
    """

    if name == "":
        return "empty file name"
    if name in (".", ".."):
        return "'.' and '..' are reserved"
    if len(name) > max_length:
        return f"name is longer than {max_length} characters"
    found = [char for char in name if char in INVALID_CHARS]
    if found:
        rendered = " ".join(sorted({repr(char) for char in found}))
        return f"illegal character(s) {rendered}"
    for char in name:
        if _CONTROL_RE.match(char):
            return f"control character {ord(char):#04x} is not allowed"
    if name.endswith(" ") or name.endswith("."):
        return "name cannot end with a space or a dot"
    if name.startswith(" "):
        return "name cannot start with a space"
    stem = name.split(".", 1)[0].rstrip(" .")
    if stem.upper() in RESERVED_NAMES:
        return f"'{stem.upper()}' is a reserved Windows device name"
    # Windows compares case-insensitively, so a full-width or decomposed form
    # of a letter is still the same letter to the filesystem.
    normalized = unicodedata.normalize("NFC", name)
    if normalized != name and "\ufffd" in normalized:
        return "name contains an unrepresentable character"
    if not name.strip():
        return "name is only whitespace"
    return None


def is_valid_filename(name: str) -> bool:
    """Convenience boolean wrapper around :func:`validate_filename`."""

    return validate_filename(name) is None


def path_length_risk(target: Path) -> bool:
    """Return ``True`` when *target* exceeds the legacy Win32 path limit."""

    if not is_windows():
        return False
    return len(str(target)) >= MAX_PATH_LENGTH


def natural_key(text: str) -> tuple:
    """Sort key that orders ``img2`` before ``img10``."""

    parts = re.split(r"(\d+)", text.casefold())
    return tuple((1, int(part)) if part.isdigit() else (0, part) for part in parts if part != "")


def make_temp_name(original: str, token: str) -> str:
    """Build a collision-resistant intermediate name for *original*."""

    room = max(1, MAX_COMPONENT_LENGTH - len(TEMP_PREFIX) - len(token) - 1)
    return f"{TEMP_PREFIX}{token}-{original[:room]}"


def make_backup_name(original: str, token: str) -> str:
    """Build the quarantine name used when overwriting is explicitly allowed."""

    room = max(1, MAX_COMPONENT_LENGTH - len(BACKUP_PREFIX) - len(token) - 1)
    return f"{BACKUP_PREFIX}{token}-{original[:room]}"


def is_internal_name(name: str) -> bool:
    """Return ``True`` for EzRename's own temporary/quarantine files."""

    return name.startswith(TEMP_PREFIX) or name.startswith(BACKUP_PREFIX)


def same_file(first: Path, second: Path) -> bool:
    """Return ``True`` when both paths point at the same filesystem object."""

    try:
        a = os.stat(first)
        b = os.stat(second)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def path_exists(path: Path) -> bool:
    """``Path.exists`` that never raises on unusual filesystems."""

    try:
        return path.exists() or os.path.lexists(path)
    except OSError:
        return False
