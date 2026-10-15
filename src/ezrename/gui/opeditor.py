"""Editors for the rename operations.

The editor is generated from each operation's dataclass fields, so adding a new
operation to the core automatically produces a working, consistent editor
without duplicating UI code. Widget hints (labels, choices, tooltips, units)
come from :data:`FIELD_HINTS`.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Dict, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.models import FileRecord
from ..core.operations import (
    OPERATION_CATALOGUE,
    Operation,
    OperationError,
    new_operation,
)
from ..core.pipeline import apply_operations
from . import theme
from .widgets import ElidedLabel, badge, button, icon_button, label

#: ``(operation type, field) -> (label, kind, choices, tooltip)``
FIELD_HINTS: Dict[Tuple[str, str], Tuple[str, str, tuple, str]] = {
    ("find_replace", "find"): ("Find", "text", (), "Text to look for. Use a regular expression when enabled."),
    ("find_replace", "replace"): ("Replace with", "text", (), "Leave empty to remove the match."),
    ("find_replace", "use_regex"): ("Regular expression", "bool", (), "Treat 'find' as a pattern; \\1, \\2 work in the replacement."),
    ("find_replace", "case_sensitive"): ("Match case", "bool", (), ""),
    ("find_replace", "replace_all"): ("Replace every occurrence", "bool", (), "Uncheck to replace only the first match."),
    ("find_replace", "scope"): ("Apply to", "choice", (("stem", "Name without extension"), ("ext", "Extension only"), ("both", "Name and extension"), ("full", "Full name (can move the dot)")), ""),
    ("prefix_suffix", "prefix"): ("Add prefix", "text", (), "Placed at the very start of the name."),
    ("prefix_suffix", "suffix"): ("Add suffix", "text", (), ""),
    ("prefix_suffix", "suffix_after_extension"): ("Suffix after the extension", "bool", (), "Off: photo→photo_backup.jpg  On: photo.jpg→photo.jpg_backup"),
    ("prefix_suffix", "remove_prefix"): ("Remove prefix", "text", (), "Only removes it when the name starts with this text."),
    ("prefix_suffix", "remove_suffix"): ("Remove suffix", "text", (), "Only removes it when the name ends with this text."),
    ("prefix_suffix", "case_sensitive"): ("Match case", "bool", (), ""),
    ("numbering", "start"): ("Start at", "int", (), ""),
    ("numbering", "step"): ("Increment", "int", (), ""),
    ("numbering", "padding"): ("Digits", "int", (), "Zero padding width, e.g. 3 → 001."),
    ("numbering", "style"): ("Style", "choice", (("decimal", "1, 2, 3"), ("alpha_lower", "a, b, c"), ("alpha_upper", "A, B, C"), ("roman_lower", "i, ii, iii"), ("roman_upper", "I, II, III")), ""),
    ("numbering", "position"): ("Placement", "choice", (("prefix", "Before the name"), ("suffix", "After the name"), ("replace", "Replace the name")), ""),
    ("numbering", "separator"): ("Separator", "text", (), "Inserted between the number and the name."),
    ("numbering", "prefix"): ("Text before the number", "text", (), "For example 'IMG_' to build IMG_001.jpg"),
    ("numbering", "suffix"): ("Text after the number", "text", (), ""),
    ("case", "mode"): ("Convert to", "choice", (("upper", "UPPERCASE"), ("lower", "lowercase"), ("title", "Title Case"), ("sentence", "Sentence case")), ""),
    ("case", "scope"): ("Apply to", "choice", (("stem", "Name only"), ("ext", "Extension only"), ("both", "Name and extension")), ""),
    ("separators", "spaces_to"): ("Replace spaces with", "text", (), "One character, e.g. _ or -. Leave empty to keep spaces."),
    ("separators", "collapse_repeats"): ("Collapse repeated separators", "bool", (), "'a   b' becomes 'a_b'"),
    ("separators", "dedupe_words"): ("Remove duplicate words", "bool", (), "'summer summer trip' becomes 'summer trip'"),
    ("separators", "trim_whitespace"): ("Trim outer whitespace", "bool", (), ""),
    ("separators", "strip_chars"): ("Remove these characters", "text", (), "Every listed character is deleted from the name."),
    ("separators", "replace_from"): ("Characters to replace", "text", (), "One character per replacement, paired with the field below."),
    ("separators", "replace_to"): ("Replace characters with", "text", (), ""),
    ("extension", "new_extension"): ("New extension", "text", (), "Renaming only - the file contents are never converted."),
    ("extension", "case"): ("Extension case", "choice", (("keep", "Leave as it is"), ("lower", "lowercase"), ("upper", "UPPERCASE")), ""),
    ("extension", "remove"): ("Remove the extension", "bool", (), ""),
    ("extension", "only_when"): ("Only for these extensions", "text", (), "Comma separated, e.g. jpg,png"),
    ("date", "format"): ("Date format", "text", (), "strftime pattern, e.g. %Y-%m-%d"),
    ("date", "source"): ("Use this timestamp", "choice", (("mtime", "Modified"), ("ctime", "Created"), ("atime", "Accessed")), ""),
    ("date", "position"): ("Placement", "choice", (("prefix", "Before the name"), ("suffix", "After the name")), ""),
    ("date", "separator"): ("Separator", "text", (), ""),
    ("date", "fallback"): ("If no timestamp", "choice", (("empty", "Leave the name unchanged"), ("original", "Skip the file"), ("error", "Report an error")), ""),
    ("template", "pattern"): ("Pattern", "text", (), "Example: {stem}_{date}{ext} - see the variable list below."),
    ("template", "date_format"): ("Date format", "text", (), ""),
    ("template", "time_format"): ("Time format", "text", (), ""),
    ("template", "indexing"): ("Number from zero", "bool", (), "{index} then starts at 0 instead of 1."),
    ("text_edit", "mode"): ("Action", "choice", (("insert", "Insert text"), ("remove", "Remove text")), ""),
    ("text_edit", "text"): ("Text", "text", (), ""),
    ("text_edit", "position"): ("Position", "choice", (("start", "At the start"), ("end", "At the end"), ("index", "At a character position"), ("anywhere", "Everywhere"), ("first", "First occurrence"), ("last", "Last occurrence")), ""),
    ("text_edit", "index"): ("Character position", "int", (), "0 = before the first character."),
    ("text_edit", "case_sensitive"): ("Match case", "bool", (), ""),
    ("text_edit", "limit"): ("Occurrences", "int", (), "How many matches to remove for 'first' or 'last'."),
}


def _widget_for(operation: Operation, name: str, value: Any) -> QtWidgets.QWidget:
    hint = FIELD_HINTS.get((operation.type, name))
    kind = hint[1] if hint else None
    if kind is None:
        if isinstance(value, bool):
            kind = "bool"
        elif isinstance(value, int):
            kind = "int"
        else:
            kind = "text"
    choices = hint[2] if hint else ()

    if kind == "bool":
        widget = QtWidgets.QCheckBox()
        widget.setChecked(bool(value))
        widget.setCursor(QtCore.Qt.PointingHandCursor)
        return widget
    if kind == "int":
        widget = QtWidgets.QSpinBox()
        widget.setRange(-1_000_000, 1_000_000)
        widget.setValue(int(value))
        widget.setButtonSymbols(QtWidgets.QAbstractSpinBox.UpDownArrows)
        return widget
    if kind == "choice" and choices:
        widget = QtWidgets.QComboBox()
        for key, description in choices:
            widget.addItem(description, key)
        index = widget.findData(value)
        if index >= 0:
            widget.setCurrentIndex(index)
        return widget
    widget = QtWidgets.QLineEdit(str(value))
    if operation.type == "template" and name == "pattern":
        widget.setFont(QtGui.QFont(theme.mono_family(), 10))
        widget.setPlaceholderText("{stem}_{date}{ext}")
    return widget


def _read_widget(widget: QtWidgets.QWidget, value: Any) -> Any:
    if isinstance(widget, QtWidgets.QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QtWidgets.QSpinBox):
        return widget.value()
    if isinstance(widget, QtWidgets.QComboBox):
        return widget.currentData()
    if isinstance(widget, QtWidgets.QLineEdit):
        return widget.text()
    return value


class OperationEditor(QtWidgets.QWidget):
    """Form for one operation instance, with live validation and a sample preview."""

    changed = QtCore.Signal(object)  # emits the edited Operation

    def __init__(
        self,
        operation: Operation,
        *,
        show_sample: bool = True,
        columns: int = 2,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.operation = operation
        self._widgets: Dict[str, QtWidgets.QWidget] = {}
        self._show_sample = show_sample

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        row = 0
        column = 0
        for info in fields(operation):  # type: ignore[arg-type]
            name = info.name
            value = getattr(operation, name)
            hint = FIELD_HINTS.get((operation.type, name))
            title = hint[0] if hint else name.replace("_", " ").capitalize()
            tooltip = hint[3] if hint else ""
            widget = _widget_for(operation, name, value)
            if tooltip:
                widget.setToolTip(tooltip)
            if isinstance(widget, QtWidgets.QCheckBox):
                widget.setText(title)
                if tooltip:
                    widget.setToolTip(tooltip)
            else:
                widget.setToolTip(tooltip or title)
            self._widgets[name] = widget

            if isinstance(widget, QtWidgets.QCheckBox):
                grid.addWidget(widget, row, column * 2, 1, 2)
            else:
                caption = label(title, "body")
                if tooltip:
                    caption.setToolTip(tooltip)
                grid.addWidget(caption, row, column * 2)
                grid.addWidget(widget, row, column * 2 + 1)
            column += 1
            if column >= columns:
                column = 0
                row += 1
        outer.addLayout(grid)

        self.error_label = label("", "danger")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        outer.addWidget(self.error_label)

        self.sample_label = label("", "mono")
        self.sample_label.setProperty("role", "dim")
        self.sample_label.setWordWrap(True)
        if show_sample:
            outer.addWidget(self.sample_label)

        for widget in self._widgets.values():
            if isinstance(widget, QtWidgets.QCheckBox):
                widget.toggled.connect(self._on_changed)
            elif isinstance(widget, QtWidgets.QSpinBox):
                widget.valueChanged.connect(self._on_changed)
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.currentIndexChanged.connect(self._on_changed)
            elif isinstance(widget, QtWidgets.QLineEdit):
                widget.textChanged.connect(self._on_changed)

        self.refresh()

    # -- API -------------------------------------------------------------
    @property
    def live_error(self) -> str:
        try:
            self.operation.validate()
        except OperationError as exc:
            return str(exc)
        return ""

    def sample(self, name: str = "holiday photo.jpg", index: int = 0) -> str:
        record = FileRecord(path=QtCore.QDir.home().filePath(name), size=2048, mtime=1_700_000_000)
        try:
            return apply_operations(name, [self.operation], index=index, path=record.path,
                                    size=record.size, mtime=record.mtime, atime=record.mtime)
        except Exception:  # pragma: no cover - defensive, validation already ran
            return name

    def _on_changed(self, *_args: object) -> None:
        self.refresh()
        self.changed.emit(self.operation)

    def refresh(self) -> None:
        for info in fields(self.operation):  # type: ignore[arg-type]
            widget = self._widgets.get(info.name)
            if widget is not None:
                setattr(self.operation, info.name, _read_widget(widget, getattr(self.operation, info.name)))
        error = self.live_error
        self.error_label.setText(error)
        self.error_label.setVisible(bool(error))
        if self._show_sample:
            sample = self.sample()
            self.sample_label.setText(f"example:  holiday photo.jpg  →  {sample}")
        self.sample_label.setVisible(self._show_sample and not error)


class OperationCard(QtWidgets.QFrame):
    """One entry of the operation stack: header row plus a collapsible editor."""

    changed = QtCore.Signal(object, int)
    remove_requested = QtCore.Signal(int)
    move_requested = QtCore.Signal(int, int)
    duplicate_requested = QtCore.Signal(int)

    def __init__(
        self,
        operation: Operation,
        index: int,
        *,
        expanded: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.tokens = theme.tokens()
        self.operation = operation
        self.index = index
        self._expanded = expanded

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        self.toggle = QtWidgets.QToolButton()
        self.toggle.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        self.toggle.setAutoRaise(True)
        self.toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self.toggle.clicked.connect(self._toggle)
        header.addWidget(self.toggle)

        number = label(f"{index + 1}", "mono")
        number.setFixedWidth(18)
        number.setProperty("role", "accent")
        header.addWidget(number)

        self.title = ElidedLabel(operation.summary())
        self.title.setToolTip(operation.description)
        header.addWidget(self.title, 1)

        self.warning = badge("check settings", "warn")
        self.warning.hide()
        header.addWidget(self.warning)

        for icon_name, tooltip, signal in (
            ("chevron_up", "Move earlier (numbering follows this order)", self._move_up),
            ("chevron_down", "Move later", self._move_down),
            ("layers", "Duplicate this step", self._duplicate),
            ("trash", "Remove this step", self._remove),
        ):
            control = icon_button(icon_name, tooltip, size=26)
            control.clicked.connect(signal)
            header.addWidget(control)
        outer.addLayout(header)

        self.editor = OperationEditor(operation, show_sample=expanded)
        self.editor.changed.connect(self._on_editor_changed)
        self.editor.setVisible(expanded)
        outer.addWidget(self.editor)
        self._update_warning()

    # -- behaviour -------------------------------------------------------
    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self.editor.setVisible(self._expanded)
        self.editor._show_sample = self._expanded
        self.toggle.setArrowType(QtCore.Qt.DownArrow if self._expanded else QtCore.Qt.RightArrow)
        self.editor.refresh()

    def _on_editor_changed(self, operation: Operation) -> None:
        self.title.setText(operation.summary())
        self._update_warning()
        self.changed.emit(operation, self.index)

    def _update_warning(self) -> None:
        problem = self.editor.live_error
        self.warning.setVisible(bool(problem))
        self.warning.setText("needs attention")
        if problem:
            self.title.setToolTip(problem)
        else:
            self.title.setToolTip(self.operation.description)

    def _move_up(self) -> None:
        self.move_requested.emit(self.index, -1)

    def _move_down(self) -> None:
        self.move_requested.emit(self.index, 1)

    def _duplicate(self) -> None:
        self.duplicate_requested.emit(self.index)

    def _remove(self) -> None:
        self.remove_requested.emit(self.index)

    def flash_error(self) -> None:
        """Briefly highlight the card when the user tries to use an invalid step."""

        effect = QtWidgets.QGraphicsColorizeEffect(self)
        effect.setColor(QtGui.QColor(self.tokens.palette.danger))
        effect.setStrength(0.6)
        self.setGraphicsEffect(effect)
        QtCore.QTimer.singleShot(420, lambda: self.setGraphicsEffect(None))
        self._expanded = True
        self.editor.setVisible(True)
        self.editor.refresh()


class OperationStack(QtWidgets.QWidget):
    """Ordered list of operation cards with an add button and presets."""

    changed = QtCore.Signal()
    problems_changed = QtCore.Signal(list)

    def __init__(self, session, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.session = session
        self.tokens = theme.tokens()
        self._cards: list[OperationCard] = []

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.container = QtWidgets.QWidget()
        self.list_layout = QtWidgets.QVBoxLayout(self.container)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.container)
        outer.addWidget(self.scroll, 1)

        self.empty_hint = label(
            "No steps yet. Add an operation to start building the rename sequence.",
            "muted",
        )
        self.empty_hint.setWordWrap(True)
        self.list_layout.insertWidget(0, self.empty_hint)

        add_row = QtWidgets.QHBoxLayout()
        add_row.setSpacing(8)
        self.add_button = button("Add step", variant="primary", icon_name="plus")
        self.add_button.clicked.connect(self._show_add_menu)
        add_row.addWidget(self.add_button)
        self.clear_button = button("Clear", variant="quiet", icon_name="close")
        self.clear_button.clicked.connect(self.session.clear_operations)
        add_row.addWidget(self.clear_button)
        add_row.addStretch(1)
        self.problem_label = label("", "danger")
        add_row.addWidget(self.problem_label)
        outer.addLayout(add_row)

        self.session.operations_changed.connect(self.rebuild)
        self.session.files_changed.connect(self._refresh_samples)
        self.rebuild()

    # -- building --------------------------------------------------------
    def rebuild(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []

        operations = self.session.operations
        self.empty_hint.setVisible(not operations)
        for position, operation in enumerate(operations):
            card = OperationCard(operation, position, expanded=len(operations) == 1)
            card.changed.connect(self._on_card_changed)
            card.remove_requested.connect(self.session.remove_operation)
            card.move_requested.connect(self.session.move_operation)
            card.duplicate_requested.connect(self._duplicate)
            self._cards.append(card)
            self.list_layout.insertWidget(1 + position, card)

        problems = self.session.operation_problems()
        self.problem_label.setText(problems[0] if problems else "")
        self.problems_changed.emit(problems)
        self._refresh_samples()

    def _on_card_changed(self, operation: Operation, index: int) -> None:
        self.session.replace_operation(index, operation)
        problems = self.session.operation_problems()
        self.problem_label.setText(problems[0] if problems else "")
        self.problems_changed.emit(problems)
        self._refresh_samples()

    def _duplicate(self, index: int) -> None:
        if 0 <= index < len(self.session.operations):
            source = self.session.operations[index]
            clone = new_operation(source.type, **{
                info.name: getattr(source, info.name)
                for info in fields(source)  # type: ignore[arg-type]
            })
            operations = list(self.session.operations)
            operations.insert(index + 1, clone)
            self.session.set_operations(operations)

    def _refresh_samples(self) -> None:
        for card in self._cards:
            card.editor.refresh()

    def flash_problem(self) -> None:
        for card in self._cards:
            if card.editor.live_error:
                card.flash_error()
                return

    def _show_add_menu(self) -> None:
        menu = QtWidgets.QMenu(self)
        menu.setToolTipsVisible(True)
        for cls in OPERATION_CATALOGUE:
            action = menu.addAction(cls.label)
            action.setToolTip(cls.description)
            action.triggered.connect(lambda _checked=False, name=cls.type: self._add(name))
        menu.addSeparator()
        presets = sorted(self.session.settings.presets)
        if presets:
            preset_menu = menu.addMenu("Load preset")
            for name in presets:
                action = preset_menu.addAction(name)
                action.triggered.connect(lambda _checked=False, n=name: self.session.apply_preset(n))
        else:
            action = menu.addAction("Save the current steps as a preset…")
            action.triggered.connect(self.save_preset)
        menu.setMinimumWidth(240)
        menu.exec(self.add_button.mapToGlobal(QtCore.QPoint(0, self.add_button.height() + 4)))

    def _add(self, type_name: str) -> None:
        defaults = {
            "numbering": {
                "start": self.session.settings.number_start,
                "step": self.session.settings.number_step,
                "padding": self.session.settings.number_padding,
                "style": self.session.settings.number_style,
                "separator": self.session.settings.separator,
            }
        }.get(type_name, {})
        self.session.add_operation(new_operation(type_name, **defaults))

    def save_preset(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok and name.strip():
            self.session.save_preset(name.strip())
            self.session.status_message.emit(f"preset '{name.strip()}' saved")
