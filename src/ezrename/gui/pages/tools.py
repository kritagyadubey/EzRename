"""Rename tools: build, order and reuse the rename sequence."""

from __future__ import annotations

from typing import Optional

from PySide6 import QtWidgets

from ...core.operations import OPERATION_CATALOGUE, TEMPLATE_VARIABLES, new_operation
from .. import theme
from ..opeditor import OperationStack
from ..widgets import Card, button, icon_button, label


class ToolsPage(QtWidgets.QWidget):
    """Catalogue of operations plus the sequence editor and presets."""

    def __init__(self, session, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.session = session
        self.tokens = theme.tokens()

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        header = QtWidgets.QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(label("Rename tools", "display"))
        header.addWidget(
            label(
                "Build the sequence of transformations. Steps run from top to bottom, "
                "and the workspace preview updates as you change them.",
                "muted",
            )
        )
        root.addLayout(header)

        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(14)

        # ---- catalogue --------------------------------------------------
        catalogue = Card("Operations", "click to add a step", icon_name="layers")
        catalogue.setMinimumWidth(300)
        catalogue.setMaximumWidth(360)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        holder = QtWidgets.QWidget()
        holder_layout = QtWidgets.QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 6, 0)
        holder_layout.setSpacing(8)
        for cls in OPERATION_CATALOGUE:
            holder_layout.addWidget(self._catalogue_entry(cls))
        holder_layout.addStretch(1)
        scroll.setWidget(holder)
        catalogue.add(scroll, 1)

        self.variables_card = Card("Template variables")
        variables_text = "\n".join(f"{{{name}}} — {text}" for name, text in TEMPLATE_VARIABLES.items())
        variables_label = label(variables_text, "mono")
        variables_label.setWordWrap(True)
        self.variables_card.add(variables_label)
        variables_hint = label(
            "Format specifiers work too: {index:03d} pads the number to three digits.",
            "dim",
        )
        variables_hint.setWordWrap(True)
        self.variables_card.add(variables_hint)
        catalogue.add(self.variables_card)
        columns.addWidget(catalogue)

        # ---- sequence ---------------------------------------------------
        sequence = Card("Rename sequence", "applies to every selected file", icon_name="tools")
        self.stack = OperationStack(self.session)
        sequence.add(self.stack, 1)

        presets = QtWidgets.QHBoxLayout()
        presets.setSpacing(8)
        presets.addWidget(label("Presets", "section"))
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.setMinimumWidth(180)
        presets.addWidget(self.preset_combo)
        self.load_preset_button = button("Load", variant="quiet", icon_name="export")
        presets.addWidget(self.load_preset_button)
        self.delete_preset_button = icon_button("trash", "Delete the selected preset")
        presets.addWidget(self.delete_preset_button)
        presets.addStretch(1)
        sequence.add_layout(presets)
        columns.addWidget(sequence, 1)
        root.addLayout(columns, 1)

        # ---- wiring -----------------------------------------------------
        self.load_preset_button.clicked.connect(self._load_preset)
        self.delete_preset_button.clicked.connect(self._delete_preset)
        self.session.operations_changed.connect(self._refresh_presets)
        self.session.settings_changed.connect(self._refresh_presets)
        self._refresh_presets()

    def _catalogue_entry(self, cls) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setObjectName("CardFlat")
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(10)

        text = QtWidgets.QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(cls.label, "body"))
        description = label(cls.description, "dim")
        description.setWordWrap(True)
        text.addWidget(description)
        layout.addLayout(text, 1)

        add = button("Add", variant="quiet", icon_name="plus")
        add.setToolTip(f"Add '{cls.label}' to the rename sequence")
        add.clicked.connect(lambda _checked=False, name=cls.type: self._add(name))
        layout.addWidget(add)
        return frame

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
        self.session.status_message.emit(f"'{type_name}' added to the sequence")

    def _refresh_presets(self) -> None:
        current = self.preset_combo.currentText()
        self.preset_combo.clear()
        names = sorted(self.session.settings.presets)
        self.preset_combo.addItems(names)
        if current in names:
            self.preset_combo.setCurrentText(current)
        self.preset_combo.setEnabled(bool(names))
        self.load_preset_button.setEnabled(bool(names))
        self.delete_preset_button.setEnabled(bool(names))

    def _load_preset(self) -> None:
        name = self.preset_combo.currentText()
        if name and self.session.apply_preset(name):
            self.session.status_message.emit(f"preset '{name}' loaded")

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not name:
            return
        self.session.delete_preset(name)
        self._refresh_presets()
        self.session.status_message.emit(f"preset '{name}' deleted")
