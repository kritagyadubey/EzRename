"""Dialogs: the completion report, the undo assistant and the about box."""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import APP_NAME, APP_URL, __version__
from ..core.history import SessionSummary, UndoReport
from ..core.models import EntryStatus, ExecutionResult
from ..core.operations import describe_operations, operations_from_dicts
from . import theme
from .filetable import STATUS_TEXT, STATUS_TONE
from .widgets import Card, badge, button, label, separator


class ReportDialog(QtWidgets.QDialog):
    """Detailed result of one rename session."""

    undo_requested = QtCore.Signal(str)
    export_requested = QtCore.Signal(str)

    def __init__(self, result: ExecutionResult, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.tokens = theme.tokens()
        self.result = result
        self.setWindowTitle(f"{APP_NAME} — rename report")
        self.setMinimumSize(760, 520)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        summary = result.summary()
        failed = summary["failed"] or len(result.rollback_failures)
        headline = (
            f"{summary['renamed']} file(s) renamed"
            if result.kind == "rename"
            else f"{summary['renamed']} file name(s) restored"
        )
        if summary["skipped"]:
            headline += f" · {summary['skipped']} unchanged or skipped"
        if failed:
            headline += f" · {failed} failed"

        title_row = QtWidgets.QHBoxLayout()
        glyph = QtWidgets.QLabel()
        tone = self.tokens.palette.danger if failed else self.tokens.palette.success
        from .icons import icon as _icon

        glyph.setPixmap(_icon("alert" if failed else "check", tone, 22).pixmap(22, 22))
        title_row.addWidget(glyph)
        title_row.addWidget(label(headline, "title"))
        title_row.addStretch(1)
        if result.cancelled:
            title_row.addWidget(badge("cancelled", "warn"))
        title_row.addWidget(badge(f"session {result.session_id}", "muted"))
        layout.addLayout(title_row)

        if result.root:
            layout.addWidget(label(f"Folder: {result.root}", "dim"))

        if result.operations:
            try:
                steps = describe_operations(operations_from_dicts(result.operations))
            except Exception:  # pragma: no cover - defensive
                steps = []
            if steps:
                card = Card("Operations applied")
                for step in steps:
                    card.add(label(f"•  {step}", "muted"))
                layout.addWidget(card)

        table = QtWidgets.QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["File", "Result", "Details"])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)

        for outcome in result.outcomes:
            row = table.rowCount()
            table.insertRow(row)
            original = outcome.original_name or outcome.source.name
            name_item = QtWidgets.QTableWidgetItem(original)
            name_item.setToolTip(str(outcome.source))
            table.setItem(row, 0, name_item)

            status_item = QtWidgets.QTableWidgetItem(STATUS_TEXT.get(outcome.status, outcome.status.value))
            tone_name = STATUS_TONE.get(outcome.status, "muted")
            colours = {
                "ok": self.tokens.palette.success,
                "bad": self.tokens.palette.danger,
                "warn": self.tokens.palette.warning,
                "accent": self.tokens.accent,
                "muted": self.tokens.text_muted,
            }
            status_item.setForeground(QtGui.QBrush(QtGui.QColor(colours.get(tone_name, self.tokens.palette.text))))
            table.setItem(row, 1, status_item)

            detail = outcome.message
            if outcome.status is EntryStatus.RENAMED and outcome.target.name != original:
                detail = f"→ {outcome.target.name}"
            if outcome.backup is not None:
                detail += f"   (previous file kept as {outcome.backup.name})"
            detail_item = QtWidgets.QTableWidgetItem(detail)
            detail_item.setToolTip(str(outcome.target))
            table.setItem(row, 2, detail_item)
        layout.addWidget(table, 1)

        if result.rollback_failures:
            card = Card("Files that need attention")
            for failure in result.rollback_failures:
                card.add(label(failure, "danger"))
            layout.addWidget(card)
        if result.notes:
            notes = Card("Notes")
            for note in result.notes:
                line = label(f"•  {note}", "muted")
                line.setWordWrap(True)
                notes.add(line)
            layout.addWidget(notes)

        buttons = QtWidgets.QHBoxLayout()
        self.export_button = button("Export manifest", variant="quiet", icon_name="export")
        self.export_button.clicked.connect(lambda: self.export_requested.emit(result.session_id))
        self.export_button.setEnabled(result.kind == "rename")
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        self.undo_button = button("Undo this session", variant="primary", icon_name="undo")
        self.undo_button.clicked.connect(lambda: self.undo_requested.emit(result.session_id))
        self.undo_button.setEnabled(
            result.kind == "rename" and bool(result.renamed) and not result.dry_run
        )
        buttons.addWidget(self.undo_button)
        close_button = button("Close", variant="quiet")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)


class UndoDialog(QtWidgets.QDialog):
    """Verifies a session before undoing it and explains every problem."""

    undo_confirmed = QtCore.Signal(str, bool)  # session id, allow partial

    def __init__(
        self,
        summary: SessionSummary,
        report: UndoReport,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.tokens = theme.tokens()
        self.summary = summary
        self.report = report
        self.setWindowTitle(f"{APP_NAME} — undo session {summary.id}")
        self.setMinimumSize(700, 460)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        layout.addWidget(label(f"Restore the names from session {summary.id}", "title"))
        when = summary.created_at.astimezone().strftime("%d %b %Y at %H:%M") if summary.created_at else "unknown"
        layout.addWidget(
            label(
                f"{summary.renamed} file(s) renamed on {when}"
                + (f" in {summary.root}" if summary.root else ""),
                "dim",
            )
        )

        if report.can_undo_all:
            message = "Every file is still exactly where the rename left it, so the whole session can be restored."
            kind = "ok"
        elif report.can_undo_anything:
            message = (
                "Some files cannot be restored safely. You can restore the ones that can, "
                "and the rest will be left exactly as they are."
            )
            kind = "warn"
        else:
            message = "None of the files can be restored safely. Nothing will be changed."
            kind = "bad"
        card = Card("Check result")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(badge(f"{len(report.safe)} restorable", "ok" if report.safe else "muted"))
        if report.unsafe:
            row.addWidget(badge(f"{len(report.unsafe)} blocked", "bad"))
        row.addStretch(1)
        card.add_layout(row)
        body = label(message, {"ok": "success", "warn": "warning", "bad": "danger"}[kind])
        body.setWordWrap(True)
        card.add(body)
        layout.addWidget(card)

        if report.unsafe or report.blockers:
            problems_card = Card("Details")
            for check in report.unsafe:
                line = label(f"{check.source_path.name} — {check.reason}", "warning")
                line.setWordWrap(True)
                problems_card.add(line)
            for blocker in report.blockers:
                line = label(blocker, "warning")
                line.setWordWrap(True)
                problems_card.add(line)
            layout.addWidget(problems_card)

        if report.safe:
            preview = Card("Files that will be restored")
            for check in report.safe[:12]:
                line = label(f"{check.source_path.name}  →  {check.target_name}", "mono")
                if check.warning:
                    line.setToolTip(check.warning)
                preview.add(line)
            if len(report.safe) > 12:
                preview.add(label(f"… and {len(report.safe) - 12} more", "dim"))
            layout.addWidget(preview)

        layout.addStretch(1)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        cancel = button("Cancel", variant="quiet")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        if report.can_undo_anything and not report.can_undo_all:
            partial = button(f"Restore the {len(report.safe)} safe file(s)", variant="quiet")
            partial.clicked.connect(lambda: self._accept(True))
            buttons.addWidget(partial)

        restore = button(
            f"Restore {len(report.safe)} file(s)",
            variant="primary",
            icon_name="undo",
        )
        restore.setEnabled(bool(report.safe))
        restore.clicked.connect(lambda: self._accept(False))
        buttons.addWidget(restore)
        layout.addLayout(buttons)

    def _accept(self, partial: bool) -> None:
        self.undo_confirmed.emit(self.summary.id, partial)
        self.accept()


class AboutDialog(QtWidgets.QDialog):
    """Version, licence and links."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        tokens = theme.tokens()
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(460)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        from .icons import logo_pixmap

        logo = QtWidgets.QLabel()
        logo.setPixmap(logo_pixmap(56, tokens.accent, tokens.accent_dark))
        header = QtWidgets.QHBoxLayout()
        header.addWidget(logo)
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(APP_NAME, "title"))
        text.addWidget(label(f"Version {__version__}", "dim"))
        header.addLayout(text)
        header.addStretch(1)
        layout.addLayout(header)

        description = label(
            "A safe, previewable bulk file renamer for Windows with a graphical "
            "application and a first-class command line tool.",
            "muted",
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addWidget(separator())
        for name, value in (
            ("Licence", "MIT"),
            ("Repository", APP_URL),
            ("Renaming engine", "ezrename.core (shared by the GUI and the CLI)"),
            ("History & undo", "stored in your local app data folder"),
        ):
            row = QtWidgets.QHBoxLayout()
            caption = label(name, "muted")
            caption.setMinimumWidth(120)
            row.addWidget(caption)
            value_label = label(value, "body")
            value_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            row.addWidget(value_label, 1)
            layout.addLayout(row)

        layout.addWidget(separator())
        buttons = QtWidgets.QHBoxLayout()
        copy_button = button("Copy version info", variant="quiet", icon_name="save")
        copy_button.clicked.connect(self._copy)
        buttons.addWidget(copy_button)
        buttons.addStretch(1)
        close_button = button("Close", variant="primary")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _copy(self) -> None:
        QtWidgets.QApplication.clipboard().setText(f"{APP_NAME} {__version__} — {APP_URL}")
