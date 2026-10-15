"""Data structures shared by the engine, the CLI and the GUI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .naming import is_hidden, split_name


class EntryStatus(str, Enum):
    """State of a single file inside a plan or an execution report."""

    READY = "ready"            # will be renamed
    UNCHANGED = "unchanged"    # operations produced the same name
    SKIPPED = "skipped"        # not selected, filtered out or unreadable
    DUPLICATE = "duplicate"    # another file in the batch wants the same name
    EXISTS = "exists"          # a different file already occupies the target
    INVALID = "invalid"        # result violates filesystem naming rules
    ERROR = "error"            # operation failed for this file
    PLANNED = "planned"        # dry run: would be renamed
    RENAMED = "renamed"        # executed successfully
    UNDONE = "undone"          # an undo restored the original name
    FAILED = "failed"          # execution failed
    ROLLED_BACK = "rolled_back"  # execution failed and the original name was restored


#: Statuses that block an entry from being renamed.
BLOCKING_STATUSES = frozenset(
    {EntryStatus.DUPLICATE, EntryStatus.EXISTS, EntryStatus.INVALID, EntryStatus.ERROR}
)

#: Statuses that describe a rename that has actually been performed.
PERFORMED_STATUSES = frozenset({EntryStatus.RENAMED})

#: Statuses that mean "there is nothing to do for this file".
INERT_STATUSES = frozenset({EntryStatus.UNCHANGED, EntryStatus.SKIPPED})


@dataclass
class FileRecord:
    """A candidate file discovered on disk."""

    path: Path
    size: int = 0
    mtime: float = 0.0
    ctime: float = 0.0
    atime: float = 0.0
    is_hidden: bool = False
    is_symlink: bool = False
    error: str = ""

    @classmethod
    def from_path(cls, path: Path) -> "FileRecord":
        """Build a record, degrading gracefully when stat() fails."""

        record = cls(path=path, is_hidden=is_hidden(path), is_symlink=path.is_symlink())
        try:
            info = os.stat(path)
            record.size = info.st_size
            record.mtime = info.st_mtime
            record.ctime = info.st_ctime
            record.atime = info.st_atime
        except OSError as exc:  # pragma: no cover - depends on hostile filesystem
            record.error = f"cannot read file information: {exc.strerror or exc}"
        return record

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return split_name(self.name)[0]

    @property
    def extension(self) -> str:
        """Extension without the leading dot (``""`` when there is none)."""

        return split_name(self.name)[1]

    @property
    def parent(self) -> str:
        return self.path.parent.name

    @property
    def modified(self) -> datetime:
        return datetime.fromtimestamp(self.mtime) if self.mtime else datetime.fromtimestamp(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.name,
            "extension": self.extension,
            "size": self.size,
            "mtime": self.mtime,
            "ctime": self.ctime,
            "atime": self.atime,
            "hidden": self.is_hidden,
            "symlink": self.is_symlink,
            "error": self.error,
        }


@dataclass
class PlanEntry:
    """One file inside a rename plan: where it is now and where it would go."""

    source: Path
    target_name: str
    status: EntryStatus = EntryStatus.READY
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    size: int = 0
    mtime: float = 0.0

    @property
    def original_name(self) -> str:
        return self.source.name

    @property
    def target(self) -> Path:
        """Target path for this entry.

        Invalid results (an empty name, a name with a path separator invented
        by find/replace) must not raise, because the preview has to *show* them.
        """

        try:
            return self.source.with_name(self.target_name)
        except (ValueError, OSError):
            return self.source.parent.joinpath(self.target_name)

    @property
    def changed(self) -> bool:
        return self.target_name != self.original_name

    @property
    def blocked(self) -> bool:
        return self.status in BLOCKING_STATUSES

    @property
    def will_rename(self) -> bool:
        return self.status is EntryStatus.READY and self.changed

    @property
    def selected(self) -> bool:
        return self.status not in (EntryStatus.SKIPPED,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "original_name": self.original_name,
            "target_name": self.target_name,
            "target": str(self.target),
            "status": self.status.value,
            "changed": self.changed,
            "message": self.message,
            "warnings": list(self.warnings),
            "size": self.size,
            "mtime": self.mtime,
        }


@dataclass
class RenamePlan:
    """A fully validated, side-effect free rename proposal."""

    entries: list[PlanEntry] = field(default_factory=list)
    root: Optional[Path] = None
    operations: list[dict[str, Any]] = field(default_factory=list)
    created: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Return a status histogram used by the summary widgets."""

        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.status.value] = counts.get(entry.status.value, 0) + 1
        return counts

    def by_status(self, status: EntryStatus) -> list[PlanEntry]:
        return [entry for entry in self.entries if entry.status is status]

    @property
    def pending(self) -> list[PlanEntry]:
        """Entries that would actually be renamed."""

        return [entry for entry in self.entries if entry.will_rename]

    @property
    def blockers(self) -> list[PlanEntry]:
        return [entry for entry in self.entries if entry.blocked]

    @property
    def changed(self) -> list[PlanEntry]:
        return [entry for entry in self.entries if entry.changed]

    @property
    def is_empty(self) -> bool:
        return not self.entries

    @property
    def is_valid(self) -> bool:
        """``True`` when the plan can be applied without any file being blocked."""

        return not self.blockers and not self.errors

    def summary(self) -> dict[str, Any]:
        counts = self.counts()
        return {
            "files": len(self.entries),
            "rename": len(self.pending),
            "unchanged": counts.get(EntryStatus.UNCHANGED.value, 0),
            "skipped": counts.get(EntryStatus.SKIPPED.value, 0),
            "duplicates": counts.get(EntryStatus.DUPLICATE.value, 0),
            "existing": counts.get(EntryStatus.EXISTS.value, 0),
            "invalid": counts.get(EntryStatus.INVALID.value, 0),
            "errors": counts.get(EntryStatus.ERROR.value, 0),
            "operations": len(self.operations),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root) if self.root else None,
            "created": self.created.isoformat(),
            "summary": self.summary(),
            "operations": self.operations,
            "notes": list(self.notes),
            "errors": list(self.errors),
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass
class EntryOutcome:
    """Result of executing one plan entry."""

    source: Path
    target: Path
    status: EntryStatus
    message: str = ""
    backup: Optional[Path] = None
    size: int = 0
    mtime: float = 0.0
    original_name: str = ""

    @property
    def ok(self) -> bool:
        return self.status is EntryStatus.RENAMED

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "target": str(self.target),
            "original_name": self.original_name or self.source.name,
            "target_name": self.target.name,
            "status": self.status.value,
            "message": self.message,
            "backup": str(self.backup) if self.backup else None,
            "size": self.size,
            "mtime": self.mtime,
        }


@dataclass
class ExecutionResult:
    """Everything that happened during one rename (or undo) session."""

    session_id: str
    outcomes: list[EntryOutcome] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)
    root: Optional[Path] = None
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished: Optional[datetime] = None
    dry_run: bool = False
    cancelled: bool = False
    rollback_failures: list[str] = field(default_factory=list)
    kind: str = "rename"
    parent_id: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    @property
    def renamed(self) -> list[EntryOutcome]:
        return [outcome for outcome in self.outcomes if outcome.status is EntryStatus.RENAMED]

    @property
    def failed(self) -> list[EntryOutcome]:
        return [
            outcome
            for outcome in self.outcomes
            if outcome.status in (EntryStatus.FAILED, EntryStatus.ROLLED_BACK)
        ]

    @property
    def skipped(self) -> list[EntryOutcome]:
        return [
            outcome
            for outcome in self.outcomes
            if outcome.status in (EntryStatus.SKIPPED, EntryStatus.UNCHANGED)
        ]

    @property
    def succeeded(self) -> bool:
        return not self.failed and not self.rollback_failures

    @property
    def changed_filesystem(self) -> bool:
        return not self.dry_run and bool(self.renamed)

    @property
    def planned(self) -> list[EntryOutcome]:
        return [outcome for outcome in self.outcomes if outcome.status is EntryStatus.PLANNED]

    def summary(self) -> dict[str, Any]:
        return {
            "session": self.session_id,
            "kind": self.kind,
            "dry_run": self.dry_run,
            "cancelled": self.cancelled,
            "total": len(self.outcomes),
            "renamed": len(self.renamed),
            "planned": len(self.planned),
            "failed": len(self.failed),
            "skipped": len(self.skipped),
            "rollback_failures": len(self.rollback_failures),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session_id,
            "kind": self.kind,
            "parent": self.parent_id,
            "root": str(self.root) if self.root else None,
            "started": self.started.isoformat(),
            "finished": self.finished.isoformat() if self.finished else None,
            "dry_run": self.dry_run,
            "cancelled": self.cancelled,
            "operations": self.operations,
            "summary": self.summary(),
            "rollback_failures": list(self.rollback_failures),
            "notes": list(self.notes),
            "entries": [outcome.to_dict() for outcome in self.outcomes],
        }
