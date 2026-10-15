"""The bulk rename workspace: select files, configure, preview, apply."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtWidgets

from ...core.models import ExecutionResult
from ...core.operations import describe_operations
from .. import theme
from ..dialogs import ReportDialog
from ..filetable import FileTable
from ..opeditor import OperationStack
from ..widgets import (
    Card,
    DropArea,
    EmptyState,
    ProgressPanel,
    badge,
    button,
    confirm,
    icon_button,
    label,
    separator,
)
from ..workers import ExecuteWorker


class WorkspacePage(QtWidgets.QWidget):
    """Main working area of the application."""

    request_report = QtCore.Signal(str)

    def __init__(self, session, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.session = session
        self.tokens = theme.tokens()
        self._worker: Optional[ExecuteWorker] = None
        self._filtered_empty = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ---- header -----------------------------------------------------
        header = QtWidgets.QHBoxLayout()
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Bulk rename workspace", "display"))
        self.subtitle = label("Choose a folder or drop files to begin", "muted")
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch(1)

        self.choose_button = button("Choose folder…", icon_name="folder")
        self.choose_button.setToolTip("Pick a folder to load (Ctrl+O)")
        header.addWidget(self.choose_button)
        self.add_button = button("Add files…", icon_name="file_plus")
        self.add_button.setToolTip("Add individual files to the current list (Ctrl+Shift+O)")
        header.addWidget(self.add_button)
        self.refresh_button = icon_button("refresh", "Reload the folder from disk (Ctrl+R)")
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        # ---- toolbar ----------------------------------------------------
        toolbar = QtWidgets.QFrame()
        toolbar.setObjectName("Toolbar")
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(14, 10, 14, 10)
        toolbar_layout.setSpacing(12)

        self.recursive_check = QtWidgets.QCheckBox("Include subfolders")
        self.recursive_check.setChecked(self.session.settings.recursive)
        self.recursive_check.setToolTip("Load files from every subfolder as well")
        self.recursive_check.toggled.connect(self._on_recursive_toggled)
        toolbar_layout.addWidget(self.recursive_check)

        self.hidden_check = QtWidgets.QCheckBox("Show hidden files")
        self.hidden_check.setChecked(self.session.settings.include_hidden)
        self.hidden_check.setToolTip("Include files Windows marks as hidden")
        self.hidden_check.toggled.connect(self._on_hidden_toggled)
        toolbar_layout.addWidget(self.hidden_check)

        toolbar_layout.addStretch(1)
        self.folder_label = label("no folder selected", "dim")
        toolbar_layout.addWidget(self.folder_label)
        root.addWidget(toolbar)

        # ---- split: files | plan ---------------------------------------
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)

        files_card = Card("Files")
        self.files_body = files_card.body
        self.table = FileTable()
        self.table.remove_requested.connect(self._remove_paths)
        self.table.sort_changed.connect(self._on_sort_changed)
        self.files_body.addWidget(self.table, 1)

        self.empty_state = EmptyState(
            "No files loaded yet",
            "Choose a folder or drop files here, then configure the renaming steps "
            "on the right. Nothing on disk changes until you press Apply.",
            action="Choose folder…",
        )
        self.empty_state.action_button.clicked.connect(self.choose_button.click)
        self.files_body.addWidget(self.empty_state, 1)

        self.drop_area = DropArea(
            "Drop files or folders here",
            "They are added to the list without being moved or modified",
            compact=True,
        )
        self.drop_area.paths_dropped.connect(self.add_paths)
        self.files_body.addWidget(self.drop_area)
        self.drop_area.setVisible(False)

        self.splitter.addWidget(files_card)

        plan_card = Card("Rename plan", "steps run in order, top to bottom", icon_name="tools")
        self.plan_preview = label("", "muted")
        self.plan_preview.setWordWrap(True)
        plan_card.add(self.plan_preview)

        self.stats_row = QtWidgets.QHBoxLayout()
        self.stats_row.setSpacing(6)
        self.rename_badge = badge("0 renames", "accent")
        self.conflict_badge = badge("0 conflicts", "muted")
        self.unchanged_badge = badge("0 unchanged", "muted")
        for widget in (self.rename_badge, self.conflict_badge, self.unchanged_badge):
            self.stats_row.addWidget(widget)
        self.stats_row.addStretch(1)
        plan_card.add_layout(self.stats_row)

        plan_card.add(separator())

        self.stack = OperationStack(self.session)
        self.stack.setMinimumHeight(180)
        plan_card.add(self.stack, 1)

        self.blocker_label = label("", "danger")
        self.blocker_label.setWordWrap(True)
        self.blocker_label.hide()
        plan_card.add(self.blocker_label)

        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(8)
        self.preview_button = button("Refresh preview", variant="quiet", icon_name="refresh")
        self.preview_button.setToolTip("Recompute the preview from disk (F5)")
        actions.addWidget(self.preview_button)
        actions.addStretch(1)
        self.apply_button = button("Apply renames", variant="primary", icon_name="play")
        self.apply_button.setToolTip("Rename the files that the preview marks as ready (Ctrl+Enter)")
        actions.addWidget(self.apply_button)
        plan_card.add_layout(actions)

        self.splitter.addWidget(plan_card)
        self.splitter.setSizes([820, 420])
        root.addWidget(self.splitter, 1)

        # ---- progress overlay -----------------------------------------
        self.progress = ProgressPanel()
        self.progress.hide()
        root.addWidget(self.progress)

        # ---- wiring ----------------------------------------------------
        self.choose_button.clicked.connect(self.choose_folder)
        self.add_button.clicked.connect(self.add_files)
        self.refresh_button.clicked.connect(self.refresh)
        self.preview_button.clicked.connect(self.refresh)
        self.apply_button.clicked.connect(self.apply)
        self.progress.cancelled.connect(self.cancel)

        self.session.files_changed.connect(self._on_files_changed)
        self.session.plan_changed.connect(self._on_plan_changed)
        self.session.status_message.connect(self._on_status)

        self.table.move_sort_key(self.session.sort_key, self.session.sort_reverse)
        self._on_files_changed()
        self._on_plan_changed()

    # ------------------------------------------------------------------ #
    # File selection
    # ------------------------------------------------------------------ #

    def choose_folder(self) -> None:
        start = self.session.settings.last_folder or self.session.settings.default_folder or str(Path.home())
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose a folder to rename files in", start)
        if chosen:
            self.load_folder(Path(chosen))

    def load_folder(self, folder: Path) -> None:
        self.session.add_folder(folder)
        self.session.status_message.emit(f"loaded {len(self.session.records)} file(s) from {folder}")

    def add_files(self) -> None:
        start = self.session.settings.last_folder or str(Path.home())
        files, _filter = QtWidgets.QFileDialog.getOpenFileNames(self, "Add files", start)
        if files:
            self.add_paths(files)

    def add_paths(self, paths) -> None:
        self.session.add_paths([Path(path) for path in paths])
        self.session.status_message.emit(f"{len(self.session.records)} file(s) in the list")

    def refresh(self) -> None:
        self.session.refresh()
        self.session.status_message.emit("file list refreshed")

    def _remove_paths(self, paths) -> None:
        removed = self.session.remove_records([Path(path) for path in paths])
        if removed:
            self.session.status_message.emit(f"{removed} file(s) removed from the list (nothing deleted)")

    def _on_recursive_toggled(self, value: bool) -> None:
        self.session.settings.recursive = value
        self.session.settings.save()
        if self.session.root is not None:
            self.load_folder(self.session.root)

    def _on_hidden_toggled(self, value: bool) -> None:
        self.session.settings.include_hidden = value
        self.session.settings.save()
        if self.session.root is not None:
            self.load_folder(self.session.root)

    def _on_sort_changed(self, key: str, reverse: bool) -> None:
        self.session.set_sort(key, reverse)

    # ------------------------------------------------------------------ #
    # Preview
    # ------------------------------------------------------------------ #

    def _on_files_changed(self) -> None:
        records = self.session.records
        has_files = bool(records)
        self.empty_state.setVisible(not has_files)
        self.table.setVisible(has_files)
        self.drop_area.setVisible(not has_files)
        self.table.set_records(records, self.session.plan.entries)
        self.folder_label.setText(
            str(self.session.root) if self.session.root else f"{len(records)} individual file(s)"
        )
        self.subtitle.setText(
            f"{len(records)} file(s) loaded · nothing is changed until you apply the rename"
            if has_files
            else "Choose a folder or drop files to begin"
        )
        if has_files and not self.session.operations:
            self.session.status_message.emit("add a rename step on the right to build a preview")

    def _on_plan_changed(self) -> None:
        plan = self.session.plan
        self.table.update_entries(plan.entries)
        summary = plan.summary()

        self.rename_badge.setText(f"{summary['rename']} renames")
        self._set_badge(self.rename_badge, "accent" if summary["rename"] else "muted")
        conflicts = summary["duplicates"] + summary["existing"] + summary["invalid"] + summary["errors"]
        self.conflict_badge.setText(f"{conflicts} conflicts")
        self._set_badge(self.conflict_badge, "bad" if conflicts else "muted")
        self.unchanged_badge.setText(f"{summary['unchanged']} unchanged")
        self._set_badge(self.unchanged_badge, "muted")

        if plan.errors:
            self.plan_preview.setText("The rename steps need attention.")
        elif not self.session.operations:
            self.plan_preview.setText("No rename steps yet — add one below to see a preview.")
        elif not plan.pending:
            self.plan_preview.setText("No file would change with the current steps.")
        else:
            self.plan_preview.setText("\n".join(describe_operations(self.session.operations)))

        blocker_text = ""
        if plan.errors:
            blocker_text = plan.errors[0]
        elif plan.blockers:
            blocker_text = (
                f"{len(plan.blockers)} file(s) cannot be renamed: {self.session.blockers_summary()}"
            )
        self.blocker_label.setText(blocker_text)
        self.blocker_label.setVisible(bool(blocker_text))

        self.apply_button.setEnabled(self.session.ready and self._worker is None)
        self.drop_area.hint.setText(
            f"{len(plan.pending)} file(s) ready to rename · add or drop more files here"
        )

    def _set_badge(self, widget: QtWidgets.QLabel, tone: str) -> None:
        widget.setProperty("tone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _on_status(self, message: str) -> None:  # pragma: no cover - passthrough
        pass

    # ------------------------------------------------------------------ #
    # Applying
    # ------------------------------------------------------------------ #

    def apply(self) -> None:
        plan = self.session.plan
        if plan.errors:
            self.stack.flash_problem()
            self.session.status_message.emit("the rename steps still need attention")
            return
        if not plan.pending:
            return
        if plan.blockers:
            self.stack.flash_problem()
            return

        overwrite = False
        if plan.entries and any(entry.warnings for entry in plan.entries):
            overwrite = confirm(
                self,
                "Overwrite requested?",
                "Some target names are already used by other files.\n\n"
                "EzRename never deletes them: the existing file is moved to a "
                "'.ezrename-backup' name next to it so nothing is lost.\n\nContinue?",
                confirm_text="Rename anyway",
            )
            if not overwrite:
                return

        pending = len(plan.pending)
        if self.session.settings.confirm_before_apply:
            folder = str(self.session.root) if self.session.root else "the selected files"
            if not confirm(
                self,
                "Apply renames?",
                f"Rename {pending} file(s) in {folder}.\n\n"
                "A history entry is written for every session, so you can undo this "
                "afterwards if the files are still where the rename put them.",
                confirm_text=f"Rename {pending} file(s)",
            ):
                return

        plan_snapshot = plan
        self.progress.set_progress(0, pending, f"Renaming 0 of {pending}…")
        self.progress.show()
        self.apply_button.setEnabled(False)
        self.preview_button.setEnabled(False)

        worker = ExecuteWorker(plan_snapshot, overwrite=overwrite, parent=self)
        worker.progressed.connect(self._on_progress)
        worker.completed.connect(self._on_execution_done)
        worker.failed.connect(self._on_execution_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.progress.caption.setText("Cancelling… restoring any file already moved")

    def _on_progress(self, done: int, total: int, _outcome) -> None:
        self.progress.set_progress(done, total)

    def _on_execution_done(self, result: ExecutionResult) -> None:
        self.session.last_result = result
        if not result.dry_run:
            try:
                self.session.store.record(result)
            except Exception as exc:  # pragma: no cover - disk problems
                self.session.status_message.emit(f"history could not be written: {exc}")
        self.session.history_changed.emit()
        self.session.refresh()
        self.session.files_changed.emit()

        summary = result.summary()
        if result.failed or result.rollback_failures:
            self.session.status_message.emit(
                f"{summary['renamed']} renamed · {summary['failed']} failed — see the report"
            )
        elif result.cancelled:
            self.session.status_message.emit(
                f"cancelled · {summary['renamed']} renamed, the rest was left untouched"
            )
        else:
            self.session.status_message.emit(f"{summary['renamed']} file(s) renamed")

        dialog = ReportDialog(result, self)
        dialog.undo_requested.connect(self.request_report.emit)
        dialog.export_requested.connect(self._export_session)
        dialog.exec()

    def _export_session(self, session_id: str) -> None:
        default = str(Path(self.session.settings.last_folder or Path.home()) / f"session-{session_id}.json")
        target, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export session manifest", default, "JSON manifest (*.json);;CSV sheet (*.csv)"
        )
        if not target:
            return
        fmt = "csv" if target.lower().endswith(".csv") else "json"
        try:
            written = self.session.store.export(session_id, Path(target), fmt)
        except Exception as exc:
            self.session.status_message.emit(f"export failed: {exc}")
            return
        self.session.status_message.emit(f"manifest written to {written}")

    def _on_execution_failed(self, message: str) -> None:
        self.session.status_message.emit(f"the rename could not run: {message}")

    def _on_worker_finished(self) -> None:
        self._worker = None
        self.progress.hide()
        self.preview_button.setEnabled(True)
        self._on_plan_changed()
