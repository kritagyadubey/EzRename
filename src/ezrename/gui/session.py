"""Shared application state for the GUI.

The session owns the loaded files, the operation stack and the live plan. Pages
observe it through Qt signals, so changing a configuration in the Tools page
immediately refreshes the workspace preview, the dashboard counters and the
apply button without any page knowing about the others.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

from PySide6 import QtCore

from ..core.discovery import ScanResult, collect_records, scan_directory, sort_records
from ..core.engine import RenameEngine
from ..core.history import HistoryStore
from ..core.models import ExecutionResult, FileRecord, RenamePlan
from ..core.operations import (
    Operation,
    OperationError,
    operations_from_dicts,
    validate_operations,
)
from ..core.pipeline import PlanOptions, build_plan
from ..core.settings import AppSettings


class Session(QtCore.QObject):
    """Observable state shared by every page."""

    files_changed = QtCore.Signal()
    operations_changed = QtCore.Signal()
    plan_changed = QtCore.Signal()
    settings_changed = QtCore.Signal()
    history_changed = QtCore.Signal()
    status_message = QtCore.Signal(str)

    def __init__(self, settings: Optional[AppSettings] = None, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self.settings = settings or AppSettings.load()
        self.records: list[FileRecord] = []
        self.root: Optional[Path] = None
        self.operations: list[Operation] = []
        self.plan: RenamePlan = RenamePlan()
        self.scan_errors: list[str] = []
        self.skipped_count = 0
        self.sort_key = self.settings.sort_key
        self.sort_reverse = self.settings.sort_reverse
        self.last_result: Optional[ExecutionResult] = None
        self._store: Optional[HistoryStore] = None

        if self.settings.keep_operation_stack and self.settings.operation_stack:
            try:
                self.operations = operations_from_dicts(self.settings.operation_stack)
            except OperationError:
                self.operations = []
        self.rebuild_plan()

    # ------------------------------------------------------------------ #
    # History
    # ------------------------------------------------------------------ #

    @property
    def store(self) -> HistoryStore:
        if self._store is None:
            self._store = HistoryStore()
        return self._store

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    # ------------------------------------------------------------------ #
    # File selection
    # ------------------------------------------------------------------ #

    def add_folder(
        self,
        folder: Path,
        *,
        recursive: Optional[bool] = None,
        include_hidden: Optional[bool] = None,
    ) -> ScanResult:
        """Load the files of *folder*, replacing the current selection."""

        scan = scan_directory(
            folder,
            recursive=self.settings.recursive if recursive is None else recursive,
            include_hidden=self.settings.include_hidden if include_hidden is None else include_hidden,
            follow_symlinks=self.settings.follow_symlinks,
        )
        self.records = sort_records(scan.records, self.sort_key, reverse=self.sort_reverse)
        self.root = Path(folder)
        self.scan_errors = list(scan.errors)
        self.skipped_count = scan.skipped
        self.settings.remember_folder(str(folder))
        self.settings.save()
        self.files_changed.emit()
        self.rebuild_plan()
        return scan

    def add_paths(self, paths: Iterable[Path], *, recursive: Optional[bool] = None) -> ScanResult:
        """Add files/folders (drag & drop, Add files) to the current selection."""

        result = collect_records(
            list(paths),
            recursive=self.settings.recursive if recursive is None else recursive,
            include_hidden=True,
            follow_symlinks=self.settings.follow_symlinks,
        )
        existing = {str(record.path).casefold() for record in self.records}
        for record in result.records:
            key = str(record.path).casefold()
            if key in existing:
                continue
            existing.add(key)
            self.records.append(record)
        if self.root is None and self.records:
            parents = {str(record.path.parent) for record in self.records}
            if len(parents) == 1:
                self.root = Path(parents.pop())
        self.records = sort_records(self.records, self.sort_key, reverse=self.sort_reverse)
        self.scan_errors.extend(result.errors)
        self.skipped_count += result.skipped
        self.files_changed.emit()
        self.rebuild_plan()
        return result

    def remove_records(self, paths: Sequence[Path]) -> int:
        """Remove files from the list only - nothing on disk is touched."""

        wanted = {str(path).casefold() for path in paths}
        before = len(self.records)
        self.records = [record for record in self.records if str(record.path).casefold() not in wanted]
        removed = before - len(self.records)
        if removed:
            self.files_changed.emit()
            self.rebuild_plan()
        return removed

    def clear(self) -> None:
        self.records = []
        self.root = None
        self.scan_errors = []
        self.skipped_count = 0
        self.files_changed.emit()
        self.rebuild_plan()

    def refresh(self) -> None:
        """Re-read the folder, keeping the current sibling selection."""

        if self.root is not None:
            selected = {str(record.path).casefold() for record in self.records}
            self.add_folder(self.root)
            if selected:
                kept = [record for record in self.records if str(record.path).casefold() in selected]
                gone = selected - {str(record.path).casefold() for record in kept}
                if kept and not gone:
                    self.records = kept
                    self.files_changed.emit()
                    self.rebuild_plan()
        elif self.records:
            paths = [record.path for record in self.records]
            self.records = []
            self.add_paths(paths)

    def set_sort(self, key: str, reverse: Optional[bool] = None) -> None:
        self.sort_key = key
        if reverse is not None:
            self.sort_reverse = reverse
        self.records = sort_records(self.records, self.sort_key, reverse=self.sort_reverse)
        self.settings.sort_key = self.sort_key
        self.settings.sort_reverse = self.sort_reverse
        self.settings.save()
        self.files_changed.emit()
        self.rebuild_plan()

    def move_record(self, path: Path, delta: int) -> bool:
        """Reorder one file (numbering follows the table order)."""

        index = next(
            (position for position, record in enumerate(self.records) if record.path == path), None
        )
        if index is None:
            return False
        target = index + delta
        if not 0 <= target < len(self.records):
            return False
        self.records.insert(target, self.records.pop(index))
        self.files_changed.emit()
        self.rebuild_plan()
        return True

    # ------------------------------------------------------------------ #
    # Operations
    # ------------------------------------------------------------------ #

    def set_operations(self, operations: Sequence[Operation]) -> None:
        self.operations = list(operations)
        self.persist_operations()
        self.operations_changed.emit()
        self.rebuild_plan()

    def add_operation(self, operation: Operation) -> None:
        self.operations.append(operation)
        self.set_operations(self.operations)

    def replace_operation(self, index: int, operation: Operation) -> None:
        if 0 <= index < len(self.operations):
            self.operations[index] = operation
            self.set_operations(self.operations)

    def remove_operation(self, index: int) -> None:
        if 0 <= index < len(self.operations):
            self.operations.pop(index)
            self.set_operations(self.operations)

    def move_operation(self, index: int, delta: int) -> None:
        target = index + delta
        if 0 <= index < len(self.operations) and 0 <= target < len(self.operations):
            self.operations.insert(target, self.operations.pop(index))
            self.set_operations(self.operations)

    def clear_operations(self) -> None:
        self.set_operations([])

    def persist_operations(self) -> None:
        if self.settings.keep_operation_stack:
            self.settings.operation_stack = [operation.to_dict() for operation in self.operations]
            self.settings.save()

    def operation_problems(self) -> list[str]:
        return validate_operations(self.operations)

    def apply_preset(self, name: str) -> bool:
        stack = self.settings.presets.get(name)
        if not stack:
            return False
        try:
            self.set_operations(operations_from_dicts(stack))
        except OperationError:
            return False
        return True

    def save_preset(self, name: str) -> None:
        self.settings.add_preset(name, [operation.to_dict() for operation in self.operations])
        self.settings.save()

    def delete_preset(self, name: str) -> None:
        if name in self.settings.presets:
            del self.settings.presets[name]
            self.settings.save()

    # ------------------------------------------------------------------ #
    # Plan
    # ------------------------------------------------------------------ #

    def plan_options(self) -> PlanOptions:
        return PlanOptions()

    def rebuild_plan(self) -> RenamePlan:
        """Recompute the preview. Never touches the filesystem."""

        self.plan = build_plan(
            self.records,
            self.operations,
            self.plan_options(),
            root=self.root,
        )
        self.plan_changed.emit()
        return self.plan

    @property
    def ready(self) -> bool:
        return bool(self.plan.pending) and self.plan.is_valid

    def blockers_summary(self) -> str:
        blockers = self.plan.blockers
        if not blockers:
            return ""
        first = blockers[0]
        detail = first.message or first.status.value
        if len(blockers) == 1:
            return detail
        return f"{detail} (and {len(blockers) - 1} more)"

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #

    def engine(self, *, overwrite: bool = False) -> RenameEngine:
        return RenameEngine()

    def settings_dirty(self) -> None:
        self.settings.save()
        self.settings_changed.emit()

    def reload_settings(self) -> None:
        self.settings = AppSettings.load()
        self.settings_changed.emit()
