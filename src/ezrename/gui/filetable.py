"""The file list of the workspace.

The table shows the original name and the proposed name side by side, with the
changed characters highlighted inside the proposed name and a status chip per
row, so a preview can be read at a glance.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.models import EntryStatus, FileRecord, PlanEntry
from ..core.naming import natural_key
from . import theme
from .widgets import SearchField

COLUMNS = ("", "Original name", "New name", "Type", "Size", "Modified", "Status")
CHECK_COLUMN = 0
ORIGINAL_COLUMN = 1
TARGET_COLUMN = 2
KIND_COLUMN = 3
SIZE_COLUMN = 4
DATE_COLUMN = 5
STATUS_COLUMN = 6

STATUS_TEXT = {
    EntryStatus.READY: "will rename",
    EntryStatus.PLANNED: "would rename",
    EntryStatus.UNCHANGED: "unchanged",
    EntryStatus.SKIPPED: "skipped",
    EntryStatus.DUPLICATE: "duplicate name",
    EntryStatus.EXISTS: "already exists",
    EntryStatus.INVALID: "invalid name",
    EntryStatus.ERROR: "error",
    EntryStatus.RENAMED: "renamed",
    EntryStatus.UNDONE: "restored",
    EntryStatus.FAILED: "failed",
    EntryStatus.ROLLED_BACK: "rolled back",
}

STATUS_TONE = {
    EntryStatus.READY: "accent",
    EntryStatus.PLANNED: "accent",
    EntryStatus.UNCHANGED: "muted",
    EntryStatus.SKIPPED: "muted",
    EntryStatus.DUPLICATE: "bad",
    EntryStatus.EXISTS: "bad",
    EntryStatus.INVALID: "bad",
    EntryStatus.ERROR: "bad",
    EntryStatus.RENAMED: "ok",
    EntryStatus.UNDONE: "ok",
    EntryStatus.FAILED: "bad",
    EntryStatus.ROLLED_BACK: "warn",
}


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024.0
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}" if size < 100 else f"{size:,.0f} {unit}"
    return f"{size:.0f} B"


def diff_segments(before: str, after: str) -> list[tuple[str, bool]]:
    """Split *after* into ``(text, changed)`` runs against *before*."""

    matcher = SequenceMatcher(None, before, after, autojunk=False)
    segments: list[tuple[str, bool]] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        piece = after[j1:j2]
        if not piece:
            continue
        segments.append((piece, tag != "equal"))
    return segments


class FileTableModel(QtCore.QAbstractTableModel):
    """Table model over the session's records, with rename results folded in."""

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self.tokens = theme.tokens()
        self._records: list[FileRecord] = []
        self._entries: dict[str, PlanEntry] = {}
        self._checked: set[str] = set()

    # -- data plumbing ---------------------------------------------------
    def set_records(self, records: Sequence[FileRecord]) -> None:
        self.beginResetModel()
        keys = {self._key(record.path) for record in records}
        self._records = list(records)
        self._checked &= keys
        self._entries = {key: entry for key, entry in self._entries.items() if key in keys}
        self.endResetModel()

    def set_entries(self, entries: Sequence[PlanEntry]) -> None:
        self.beginResetModel()
        self._entries = {self._key(entry.source): entry for entry in entries}
        self.endResetModel()

    @staticmethod
    def _key(path: Path) -> str:
        return str(path).casefold()

    def entry_for(self, row: int) -> Optional[PlanEntry]:
        record = self.record_at(row)
        return self._entries.get(self._key(record.path)) if record else None

    def record_at(self, row: int) -> Optional[FileRecord]:
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def path_at(self, row: int) -> Optional[Path]:
        record = self.record_at(row)
        return record.path if record else None

    def visible_indices(self) -> list[int]:
        return list(range(len(self._records)))

    # -- selection -------------------------------------------------------
    def is_checked(self, row: int) -> bool:
        record = self.record_at(row)
        return bool(record and self._key(record.path) in self._checked)

    def set_checked(self, row: int, checked: bool) -> None:
        record = self.record_at(row)
        if record is None:
            return
        key = self._key(record.path)
        if checked:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        index = self.index(row, CHECK_COLUMN)
        self.dataChanged.emit(index, index, [QtCore.Qt.CheckStateRole])

    def set_all_checked(self, checked: bool) -> None:
        self.beginResetModel()
        if checked:
            self._checked = {self._key(record.path) for record in self._records}
        else:
            self._checked = set()
        self.endResetModel()

    def checked_records(self) -> list[FileRecord]:
        return [record for record in self._records if self._key(record.path) in self._checked]

    @property
    def checked_count(self) -> int:
        return len(self._checked)

    # -- QAbstractTableModel --------------------------------------------
    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(  # noqa: N802
        self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.DisplayRole
    ):
        if orientation != QtCore.Qt.Horizontal:
            return None
        if role == QtCore.Qt.DisplayRole:
            return COLUMNS[section]
        if role == QtCore.Qt.ToolTipRole:
            return {
                ORIGINAL_COLUMN: "The name on disk right now",
                TARGET_COLUMN: "The name EzRename would give this file (highlighted characters change)",
                STATUS_COLUMN: "Result of the preview for this file",
            }.get(section, "")
        if role == QtCore.Qt.TextAlignmentRole and section in (SIZE_COLUMN, DATE_COLUMN):
            return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        return None

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlags:
        base = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        if index.column() == CHECK_COLUMN:
            return base | QtCore.Qt.ItemIsUserCheckable
        return base

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        record = self.record_at(index.row())
        if record is None:
            return None
        entry = self._entries.get(self._key(record.path))
        column = index.column()

        if role == QtCore.Qt.CheckStateRole and column == CHECK_COLUMN:
            return QtCore.Qt.Checked if self.is_checked(index.row()) else QtCore.Qt.Unchecked
        if role == QtCore.Qt.DisplayRole:
            if column == ORIGINAL_COLUMN:
                return record.name
            if column == TARGET_COLUMN:
                return entry.target_name if entry else record.name
            if column == KIND_COLUMN:
                return record.extension.upper() if record.extension else "—"
            if column == SIZE_COLUMN:
                return human_size(record.size)
            if column == DATE_COLUMN:
                return record.modified.strftime("%d %b %Y  %H:%M")
            if column == STATUS_COLUMN:
                if entry is None:
                    return ""
                return STATUS_TEXT.get(entry.status, entry.status.value)
        if role == QtCore.Qt.TextAlignmentRole:
            if column in (SIZE_COLUMN, DATE_COLUMN):
                return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            if column in (KIND_COLUMN, STATUS_COLUMN):
                return int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        if role == QtCore.Qt.ToolTipRole:
            lines = [str(record.path)]
            if entry is not None:
                if entry.message:
                    lines.append(entry.message)
                for warning in entry.warnings:
                    lines.append(f"warning: {warning}")
            return "\n".join(lines)
        if role == QtCore.Qt.UserRole:
            return record
        if role == QtCore.Qt.UserRole + 1:
            return entry
        if role == QtCore.Qt.ForegroundRole:
            if column == STATUS_COLUMN and entry is not None:
                tone = STATUS_TONE.get(entry.status, "muted")
                mapping = {
                    "ok": self.tokens.palette.success,
                    "bad": self.tokens.palette.danger,
                    "warn": self.tokens.palette.warning,
                    "accent": self.tokens.accent,
                    "muted": self.tokens.text_muted,
                }
                return QtGui.QBrush(QtGui.QColor(mapping.get(tone, self.tokens.palette.text_muted)))
        return None

    def setData(  # noqa: N802
        self, index: QtCore.QModelIndex, value, role: int = QtCore.Qt.EditRole
    ) -> bool:
        if role == QtCore.Qt.CheckStateRole and index.column() == CHECK_COLUMN:
            self.set_checked(index.row(), value == QtCore.Qt.Checked)
            return True
        return False

    # -- sorting ---------------------------------------------------------
    def sort(self, column: int, order: QtCore.Qt.SortOrder = QtCore.Qt.AscendingOrder) -> None:
        keys = {
            ORIGINAL_COLUMN: lambda record: natural_key(record.name),
            TARGET_COLUMN: lambda record: natural_key(
                self._entries.get(self._key(record.path)).target_name
                if self._key(record.path) in self._entries
                else record.name
            ),
            KIND_COLUMN: lambda record: (record.extension.casefold(), natural_key(record.name)),
            SIZE_COLUMN: lambda record: record.size,
            DATE_COLUMN: lambda record: record.mtime,
            STATUS_COLUMN: lambda record: STATUS_TEXT.get(
                getattr(self._entries.get(self._key(record.path)), "status", EntryStatus.READY), ""
            ),
        }
        key = keys.get(column)
        if key is None:
            return
        self.beginResetModel()
        self._records.sort(key=key, reverse=order == QtCore.Qt.DescendingOrder)
        self.endResetModel()


class FileTableDelegate(QtWidgets.QStyledItemDelegate):
    """Paints the changed characters of the proposed name in the accent colour."""

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self.tokens = theme.tokens()

    def paint(  # noqa: N802
        self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex
    ) -> None:
        if index.column() != TARGET_COLUMN:
            super().paint(painter, option, index)
            return

        entry = index.data(QtCore.Qt.UserRole + 1)
        record = index.siblingAtColumn(ORIGINAL_COLUMN).data(QtCore.Qt.DisplayRole) or ""
        target = index.data(QtCore.Qt.DisplayRole) or ""

        painter.save()
        style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
        style.drawPrimitive(QtWidgets.QStyle.PE_PanelItemViewItem, option, painter, option.widget)

        rect = option.rect.adjusted(8, 0, -8, 0)
        colour = option.palette.color(QtGui.QPalette.Text)
        muted = self.tokens.palette.text_muted
        accent = self.tokens.accent
        danger = self.tokens.palette.danger

        font = option.font
        painter.setFont(font)
        metrics = QtGui.QFontMetrics(font)

        status = getattr(entry, "status", None)
        if status in (EntryStatus.DUPLICATE, EntryStatus.EXISTS, EntryStatus.INVALID, EntryStatus.ERROR):
            colour = danger
        elif status is EntryStatus.UNCHANGED:
            colour = muted

        segments = diff_segments(record, target)
        x = rect.left()
        for piece, changed in segments:
            highlight = changed and colour not in (danger, muted)
            painter.setPen(QtGui.QPen(accent if highlight else colour))
            width = metrics.horizontalAdvance(piece)
            if x + width > rect.right():
                remaining = rect.right() - x
                if remaining <= metrics.horizontalAdvance("…"):
                    break
                piece = metrics.elidedText(piece, QtCore.Qt.ElideRight, remaining)
                painter.drawText(
                    QtCore.QRect(x, rect.top(), remaining, rect.height()),
                    int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft),
                    piece,
                )
                break
            painter.drawText(
                QtCore.QRect(x, rect.top(), width, rect.height()),
                int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft),
                piece,
            )
            x += width
        if not segments:
            painter.setPen(QtGui.QPen(muted))
            painter.drawText(rect, int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft), record)
        painter.restore()


class FileTable(QtWidgets.QWidget):
    """Toolbar + table + summary footer."""

    selection_changed = QtCore.Signal()
    remove_requested = QtCore.Signal(list)
    move_requested = QtCore.Signal(object, int)
    sort_changed = QtCore.Signal(str, bool)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.tokens = theme.tokens()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # --- toolbar ---
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self.search = SearchField()
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search, 1)

        self.sort_combo = QtWidgets.QComboBox()
        for key, description in (
            ("name", "Name (natural)"),
            ("size", "Size"),
            ("modified", "Modified"),
            ("extension", "Type"),
            ("added", "Added order"),
        ):
            self.sort_combo.addItem(description, key)
        self.sort_combo.setToolTip("Order used by sequential numbering")
        self.sort_combo.currentIndexChanged.connect(self._emit_sort)
        bar.addWidget(self.sort_combo)

        self.reverse_button = QtWidgets.QPushButton("Descending")
        self.reverse_button.setCheckable(True)
        self.reverse_button.setToolTip("Reverse the order")
        self.reverse_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.reverse_button.toggled.connect(self._emit_sort)
        bar.addWidget(self.reverse_button)

        self.select_all_button = QtWidgets.QPushButton("Select all")
        self.select_all_button.setProperty("variant", "quiet")
        self.select_all_button.setToolTip("Select every file (Ctrl+A)")
        self.select_all_button.clicked.connect(lambda: self.set_all_checked(True))
        bar.addWidget(self.select_all_button)

        self.select_none_button = QtWidgets.QPushButton("Clear")
        self.select_none_button.setProperty("variant", "quiet")
        self.select_none_button.setToolTip("Clear the selection")
        self.select_none_button.clicked.connect(lambda: self.set_all_checked(False))
        bar.addWidget(self.select_none_button)

        self.remove_button = QtWidgets.QPushButton("Remove")
        self.remove_button.setProperty("variant", "quiet")
        self.remove_button.setIconSize(QtCore.QSize(17, 17))
        self.remove_button.setToolTip("Remove the selected rows from this list (files are not deleted)")
        self.remove_button.clicked.connect(self._emit_remove)
        bar.addWidget(self.remove_button)
        layout.addLayout(bar)

        # --- table ---
        self.model = FileTableModel(self)
        self.view = QtWidgets.QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setSortingEnabled(True)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(30)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.horizontalHeader().setStretchLastSection(False)
        self.view.setItemDelegate(FileTableDelegate(self.view))
        header = self.view.horizontalHeader()
        header.setSectionResizeMode(CHECK_COLUMN, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(ORIGINAL_COLUMN, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(TARGET_COLUMN, QtWidgets.QHeaderView.Stretch)
        for column in (KIND_COLUMN, SIZE_COLUMN, DATE_COLUMN, STATUS_COLUMN):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        self.view.setColumnWidth(CHECK_COLUMN, 34)
        self.view.clicked.connect(self._on_click)
        layout.addWidget(self.view, 1)

        self.footer = QtWidgets.QLabel()
        self.footer.setProperty("role", "dim")
        layout.addWidget(self.footer)

        self._filter = ""

    # -- public API ------------------------------------------------------
    def set_records(self, records: Sequence[FileRecord], entries: Sequence[PlanEntry] = ()) -> None:
        self.model.set_records(records)
        self.model.set_entries(entries)
        self._update_footer()

    def update_entries(self, entries: Sequence[PlanEntry]) -> None:
        self.model.set_entries(entries)
        self._update_footer()

    def checked_records(self) -> list[FileRecord]:
        return [record for record in self.model.checked_records() if self._matches(record)]

    def set_all_checked(self, checked: bool) -> None:
        self.model.set_all_checked(checked)
        self._update_footer()
        self.selection_changed.emit()

    def selected_paths(self) -> list[Path]:
        rows = {index.row() for index in self.view.selectionModel().selectedRows()}
        return [path for row in rows if (path := self.model.path_at(row)) is not None]

    def move_sort_key(self, key: str, reverse: bool) -> None:
        index = self.sort_combo.findData(key)
        if index >= 0:
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(index)
            self.sort_combo.blockSignals(False)
        self.reverse_button.blockSignals(True)
        self.reverse_button.setChecked(reverse)
        self.reverse_button.blockSignals(False)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # -- internals -------------------------------------------------------
    def _matches(self, record: FileRecord) -> bool:
        return not self._filter or self._filter in record.name.casefold()

    def _apply_filter(self, text: str) -> None:
        self._filter = text.strip().casefold()
        for row in range(self.model.rowCount()):
            record = self.model.record_at(row)
            hidden = record is not None and not self._matches(record)
            self.view.setRowHidden(row, hidden)
        self._update_footer()

    def _emit_sort(self, *_args: object) -> None:
        key = self.sort_combo.currentData() or "name"
        self.sort_changed.emit(key, self.reverse_button.isChecked())

    def _emit_remove(self) -> None:
        paths = self.selected_paths() or [record.path for record in self.checked_records()]
        if paths:
            self.remove_requested.emit(paths)

    def _on_click(self, index: QtCore.QModelIndex) -> None:
        self._update_footer()
        self.selection_changed.emit()

    def _update_footer(self) -> None:
        total = self.model.rowCount()
        visible = sum(1 for row in range(total) if not self.view.isRowHidden(row))
        checked = self.model.checked_count
        parts = [f"{total} file(s) loaded"]
        if visible != total:
            parts.append(f"{visible} shown by the filter")
        parts.append(f"{checked} selected")
        self.footer.setText("   ·   ".join(parts))

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        if event.key() == QtCore.Qt.Key_Delete:
            self._emit_remove()
            return
        super().keyPressEvent(event)
