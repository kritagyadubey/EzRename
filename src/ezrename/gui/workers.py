"""Background work for the GUI.

Filesystem work never runs on the GUI thread: scanning a large folder, applying
a batch rename and undoing a session all happen in worker threads that report
progress through signals, and every one of them can be cancelled safely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore

from ..core.discovery import scan_directory, sort_records
from ..core.engine import RenameEngine
from ..core.history import HistoryStore
from ..core.models import RenamePlan


class ScanWorker(QtCore.QThread):
    """Read a folder off the GUI thread."""

    completed = QtCore.Signal(object)   # ScanResult
    failed = QtCore.Signal(str)

    def __init__(
        self,
        folder: Path,
        *,
        recursive: bool,
        include_hidden: bool,
        follow_symlinks: bool = False,
        sort_key: str = "name",
        reverse: bool = False,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.folder = folder
        self.recursive = recursive
        self.include_hidden = include_hidden
        self.follow_symlinks = follow_symlinks
        self.sort_key = sort_key
        self.reverse = reverse

    def run(self) -> None:  # pragma: no cover - exercised through the GUI
        try:
            result = scan_directory(
                self.folder,
                recursive=self.recursive,
                include_hidden=self.include_hidden,
                follow_symlinks=self.follow_symlinks,
            )
            result.records = sort_records(result.records, self.sort_key, reverse=self.reverse)
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)


class ExecuteWorker(QtCore.QThread):
    """Apply a rename plan, reporting progress and honouring cancellation."""

    progressed = QtCore.Signal(int, int, object)
    completed = QtCore.Signal(object)   # ExecutionResult
    failed = QtCore.Signal(str)

    def __init__(
        self,
        plan: RenamePlan,
        *,
        overwrite: bool = False,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.plan = plan
        self.overwrite = overwrite
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # pragma: no cover - exercised through the GUI
        try:
            result = RenameEngine().execute(
                self.plan,
                overwrite=self.overwrite,
                progress=lambda done, total, outcome: self.progressed.emit(done, total, outcome),
                cancel=lambda: self._cancel,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)


class UndoWorker(QtCore.QThread):
    """Verify and undo a stored session off the GUI thread.

    The worker opens its own database connection: SQLite connections belong to
    the thread that created them, and the GUI thread keeps using its own.
    """

    progressed = QtCore.Signal(int, int, object)
    completed = QtCore.Signal(object)   # UndoResult
    failed = QtCore.Signal(str)

    def __init__(
        self,
        store: HistoryStore,
        session_id: str,
        *,
        allow_partial: bool = False,
        dry_run: bool = False,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.store_path = Path(store.path)
        self.session_id = session_id
        self.allow_partial = allow_partial
        self.dry_run = dry_run
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # pragma: no cover - exercised through the GUI
        try:
            with HistoryStore(self.store_path) as store:
                result = store.undo(
                    self.session_id,
                    allow_partial=self.allow_partial,
                    dry_run=self.dry_run,
                    progress=lambda done, total, outcome: self.progressed.emit(done, total, outcome),
                    cancel=lambda: self._cancel,
                )
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)
