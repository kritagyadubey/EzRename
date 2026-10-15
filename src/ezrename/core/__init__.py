"""Platform aware, GUI-free core of EzRename."""

from __future__ import annotations

from .naming import (
    INVALID_CHARS,
    validate_filename,
    is_valid_filename,
)
from .models import (
    EntryStatus,
    FileRecord,
    PlanEntry,
    RenamePlan,
    ExecutionResult,
    EntryOutcome,
)
from .operations import (
    OPERATION_TYPES,
    Operation,
    OperationError,
    operation_from_dict,
    describe_operations,
    new_operation,
)
from .pipeline import PlanOptions, build_plan, apply_operations
from .engine import RenameEngine
from .discovery import scan_directory, sort_records, SORT_KEYS
from .history import HistoryStore, UndoReport
from .settings import AppSettings, config_dir, data_dir

__all__ = [
    "INVALID_CHARS",
    "validate_filename",
    "is_valid_filename",
    "EntryStatus",
    "FileRecord",
    "PlanEntry",
    "RenamePlan",
    "ExecutionResult",
    "EntryOutcome",
    "OPERATION_TYPES",
    "Operation",
    "OperationError",
    "operation_from_dict",
    "describe_operations",
    "new_operation",
    "PlanOptions",
    "build_plan",
    "apply_operations",
    "RenameEngine",
    "scan_directory",
    "sort_records",
    "SORT_KEYS",
    "HistoryStore",
    "UndoReport",
    "AppSettings",
    "config_dir",
    "data_dir",
]
