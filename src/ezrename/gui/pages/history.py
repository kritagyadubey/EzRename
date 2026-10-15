"""History: every recorded session, its detail, undo and manifest export."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.models import EntryStatus
from ...core.operations import describe_operations, operations_from_dicts
from .. import theme
from ..filetable import STATUS_TEXT
from ..widgets import Card, button, confirm, icon_button, label, separator, show_info


class HistoryPage(QtWidgets.QWidget):
    """Table of sessions with a detail pane and recovery actions."""

    undo_requested = QtCore.Signal(str, bool)  # session id, allow partial

    def __init__(self, session, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.session = session
        self.tokens = theme.tokens()
        self._sessions = []

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        header = QtWidgets.QHBoxLayout()
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("History & undo", "display"))
        titles.addWidget(
            label(
                "Every session is stored on disk, so it is still here after restarting. "
                "Undo checks the files first and never overwrites anything.",
                "muted",
            )
        )
        header.addLayout(titles)
        header.addStretch(1)
        self.refresh_button = icon_button("refresh", "Reload the history")
        header.addWidget(self.refresh_button)
        self.export_button = button("Export manifest", variant="quiet", icon_name="export")
        self.export_button.setToolTip("Write the selected session to a JSON or CSV manifest")
        header.addWidget(self.export_button)
        self.delete_button = button("Delete record", variant="quiet", icon_name="trash")
        self.delete_button.setToolTip("Remove the selected history record (files are not touched)")
        header.addWidget(self.delete_button)
        self.undo_button = button("Undo session", variant="primary", icon_name="undo")
        header.addWidget(self.undo_button)
        root.addLayout(header)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)

        table_card = Card("Sessions")
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["When", "Folder", "Renamed", "Failed", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        for column in (0, 2, 3, 4):
            header_view.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection)
        table_card.add(self.table, 1)
        self.empty_label = label("No sessions recorded yet — run a rename and it will appear here.", "dim")
        table_card.add(self.empty_label)
        splitter.addWidget(table_card)

        detail_card = Card("Session detail")
        self.detail_title = label("Select a session", "title")
        detail_card.add(self.detail_title)
        self.detail_meta = label("", "dim")
        self.detail_meta.setWordWrap(True)
        detail_card.add(self.detail_meta)

        self.detail_steps = label("", "muted")
        self.detail_steps.setWordWrap(True)
        detail_card.add(self.detail_steps)

        self.undo_hint = label("", "warning")
        self.undo_hint.setWordWrap(True)
        self.undo_hint.hide()
        detail_card.add(self.undo_hint)

        detail_card.add(separator())
        self.entries_table = QtWidgets.QTableWidget(0, 2)
        self.entries_table.setHorizontalHeaderLabels(["File", "Result"])
        self.entries_table.verticalHeader().setVisible(False)
        self.entries_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.entries_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.entries_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.entries_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        detail_card.add(self.entries_table, 1)
        self.verify_button = button("Check if it can be undone", variant="quiet", icon_name="shield")
        detail_card.add(self.verify_button)
        splitter.addWidget(detail_card)
        splitter.setSizes([620, 480])
        root.addWidget(splitter, 1)

        self.refresh_button.clicked.connect(self.refresh)
        self.undo_button.clicked.connect(self._undo_selected)
        self.verify_button.clicked.connect(self._verify_selected)
        self.export_button.clicked.connect(self._export_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.session.history_changed.connect(self.refresh)

        self.refresh()

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        try:
            self._sessions = self.session.store.list_sessions(limit=self.session.settings.history_limit or 200)
        except Exception as exc:  # pragma: no cover - unreadable history file
            self._sessions = []
            show_info(self, "History unavailable", f"The history database could not be read:\n{exc}", kind="error")

        self.table.setRowCount(0)
        for summary in self._sessions:
            row = self.table.rowCount()
            self.table.insertRow(row)
            when = summary.created_at.astimezone().strftime("%d %b %Y  %H:%M") if summary.created_at else "?"
            values = [
                when,
                summary.root or "individual files",
                str(summary.renamed),
                str(summary.failed),
                summary.status_label,
            ]
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if column == 1:
                    item.setToolTip(summary.root or "")
                if column == 4:
                    tone = {
                        "completed": self.tokens.palette.success,
                        "undone": self.tokens.text_muted,
                        "cancelled": self.tokens.palette.warning,
                    }.get(summary.status_label, self.tokens.palette.danger)
                    item.setForeground(QtGui.QBrush(QtGui.QColor(tone)))
                self.table.setItem(row, column, item)

        self.empty_label.setVisible(not self._sessions)
        self.table.setVisible(bool(self._sessions))
        if self._sessions:
            self.table.selectRow(0)
        else:
            self._show_detail(None)

    def _current_index(self) -> Optional[int]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else None

    def _current(self):
        index = self._current_index()
        return self._sessions[index] if index is not None and index < len(self._sessions) else None

    def _on_selection(self) -> None:
        self._show_detail(self._current())

    def _show_detail(self, summary) -> None:
        self.entries_table.setRowCount(0)
        self.detail_steps.setText("")
        self.undo_hint.hide()
        if summary is None:
            self.detail_title.setText("Select a session")
            self.detail_meta.setText("")
            self.undo_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.verify_button.setEnabled(False)
            return

        self.detail_title.setText(f"Session {summary.id}")
        kind = "Undo session" if summary.kind == "undo" else "Rename session"
        when = summary.created_at.astimezone().strftime("%d %b %Y at %H:%M") if summary.created_at else "?"
        self.detail_meta.setText(
            f"{kind} · {when}\n"
            f"{summary.renamed} renamed · {summary.failed} failed · {summary.skipped} skipped\n"
            f"{summary.root or 'individual files'}"
        )
        if summary.operations:
            try:
                steps = describe_operations(operations_from_dicts(summary.operations))
            except Exception:  # pragma: no cover
                steps = []
            if steps:
                self.detail_steps.setText("\n".join(f"• {step}" for step in steps))

        if not summary.undoable:
            if summary.undone_at:
                self.undo_hint.setText(
                    f"This session was already undone on {summary.undone_at.astimezone().strftime('%d %b %Y at %H:%M')}."
                )
                self.undo_hint.show()
            elif summary.kind == "undo":
                self.undo_hint.setText("Undo sessions cannot be undone again — restore the original rename instead.")
                self.undo_hint.show()
            elif summary.failed and not summary.renamed:
                self.undo_hint.setText("This session did not rename anything, so there is nothing to undo.")
                self.undo_hint.show()

        for row_data in self.session.store.session_entries(summary.id):
            row = self.entries_table.rowCount()
            self.entries_table.insertRow(row)
            name_item = QtWidgets.QTableWidgetItem(row_data["original_name"])
            name_item.setToolTip(row_data["source_path"])
            self.entries_table.setItem(row, 0, name_item)
            try:
                status = EntryStatus(row_data["status"])
            except ValueError:  # pragma: no cover
                status = EntryStatus.ERROR
            result_item = QtWidgets.QTableWidgetItem(STATUS_TEXT.get(status, status.value))
            result_item.setToolTip(row_data["message"] or row_data["target_name"])
            self.entries_table.setItem(row, 1, result_item)

        self.undo_button.setEnabled(summary.undoable)
        self.export_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.verify_button.setEnabled(summary.undoable)

    # ------------------------------------------------------------------ #
    def _undo_selected(self) -> None:
        summary = self._current()
        if summary is None:
            return
        self.undo_requested.emit(summary.id, False)

    def _verify_selected(self) -> None:
        summary = self._current()
        if summary is None:
            return
        report = self.session.store.verify(summary.id)
        if report.can_undo_all:
            message = (
                f"All {len(report.safe)} file(s) of this session are exactly where the rename "
                "left them, so the session can be restored."
            )
            kind = "info"
        elif report.can_undo_anything:
            message = (
                f"{len(report.safe)} file(s) can be restored, {len(report.unsafe)} cannot:\n\n"
                + report.reason_summary()
            )
            kind = "warning"
        else:
            message = "Nothing can be restored safely:\n\n" + report.reason_summary()
            kind = "error"
        show_info(self, f"Undo check for {summary.id}", message, kind=kind)

    def _export_selected(self) -> None:
        summary = self._current()
        if summary is None:
            return
        default = str(Path(self.session.settings.last_folder or Path.home()) / f"session-{summary.id}.json")
        target, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export session manifest", default, "JSON manifest (*.json);;CSV sheet (*.csv)"
        )
        if not target:
            return
        fmt = "csv" if target.lower().endswith(".csv") else "json"
        try:
            written = self.session.store.export(summary.id, Path(target), fmt)
        except Exception as exc:
            show_info(self, "Export failed", str(exc), kind="error")
            return
        self.session.status_message.emit(f"manifest written to {written}")

    def _delete_selected(self) -> None:
        summary = self._current()
        if summary is None:
            return
        if not confirm(
            self,
            "Delete this history record?",
            f"The record of session {summary.id} is removed from the history.\n\n"
            "The files themselves are not touched, but this session can no longer be "
            "undone from here.",
            confirm_text="Delete record",
            danger=True,
        ):
            return
        if self.session.store.delete(summary.id):
            self.session.status_message.emit(f"history record {summary.id} deleted")
            self.refresh()
