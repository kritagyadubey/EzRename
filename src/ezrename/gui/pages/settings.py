"""Settings: appearance, defaults and storage locations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtWidgets

from ... import APP_URL, __version__
from ...core.settings import config_dir, data_dir
from .. import theme
from ..dialogs import AboutDialog
from ..widgets import Card, button, confirm, label, show_info


class SettingsPage(QtWidgets.QWidget):
    """Preferences that genuinely change behaviour."""

    theme_changed = QtCore.Signal()

    def __init__(self, session, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.session = session
        self.tokens = theme.tokens()
        self._loading = True

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        container = QtWidgets.QWidget()
        scroll.setWidget(container)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        layout.addWidget(label("Settings", "display"))
        layout.addWidget(
            label(
                "Preferences are stored outside the application folder so EzRename keeps "
                "working when it is installed in a protected location.",
                "muted",
            )
        )

        settings = self.session.settings

        # ---- appearance --------------------------------------------------
        appearance = Card("Appearance", "applies immediately", icon_name="palette")
        self.theme_combo = QtWidgets.QComboBox()
        for key, description in (("dark", "Dark (recommended)"), ("light", "Light"), ("system", "Follow Windows")):
            self.theme_combo.addItem(description, key)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.theme)))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        self.accent_combo = QtWidgets.QComboBox()
        for key, (accent, _dark) in theme.ACCENTS.items():
            self.accent_combo.addItem(key.capitalize(), key)
            self.accent_combo.setItemData(
                self.accent_combo.count() - 1,
                QtWidgets.QWidget().palette().color(QtWidgets.QWidget().backgroundRole()),
                QtCore.Qt.DecorationRole,
            )
        self.accent_combo.setCurrentIndex(max(0, self.accent_combo.findData(settings.accent)))
        self.accent_combo.currentIndexChanged.connect(self._on_theme_changed)

        appearance.add(self._row("Theme", self.theme_combo))
        appearance.add(self._row("Accent colour", self.accent_combo))
        layout.addWidget(appearance)

        # ---- file selection ---------------------------------------------
        selection = Card("File selection defaults", icon_name="folder")
        self.recursive_check = QtWidgets.QCheckBox("Include subfolders when loading a folder")
        self.recursive_check.setChecked(settings.recursive)
        self.recursive_check.toggled.connect(lambda v: self._set("recursive", v))
        selection.add(self.recursive_check)

        self.hidden_check = QtWidgets.QCheckBox("Include hidden files")
        self.hidden_check.setChecked(settings.include_hidden)
        self.hidden_check.toggled.connect(lambda v: self._set("include_hidden", v))
        selection.add(self.hidden_check)

        self.follow_check = QtWidgets.QCheckBox("Follow symbolic links")
        self.follow_check.setChecked(settings.follow_symlinks)
        self.follow_check.setToolTip(
            "Off by default: following links can rename files outside the chosen folder."
        )
        self.follow_check.toggled.connect(lambda v: self._set("follow_symlinks", v))
        selection.add(self.follow_check)

        self.sort_combo = QtWidgets.QComboBox()
        for key, description in (
            ("name", "Name (natural order)"),
            ("size", "Size"),
            ("modified", "Modified date"),
            ("extension", "Type"),
            ("added", "Order they were added"),
        ):
            self.sort_combo.addItem(description, key)
        self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(settings.sort_key)))
        self.sort_combo.currentIndexChanged.connect(
            lambda: self._set("sort_key", self.sort_combo.currentData())
        )
        selection.add(self._row("Default sort order", self.sort_combo))
        layout.addWidget(selection)

        # ---- rename defaults ---------------------------------------------
        defaults = Card("Rename defaults", "used when a new numbering step is added", icon_name="tools")
        self.start_spin = QtWidgets.QSpinBox()
        self.start_spin.setRange(-9999, 9999)
        self.start_spin.setValue(settings.number_start)
        self.start_spin.valueChanged.connect(lambda v: self._set("number_start", v))
        self.step_spin = QtWidgets.QSpinBox()
        self.step_spin.setRange(1, 1000)
        self.step_spin.setValue(settings.number_step)
        self.step_spin.valueChanged.connect(lambda v: self._set("number_step", v))
        self.padding_spin = QtWidgets.QSpinBox()
        self.padding_spin.setRange(0, 12)
        self.padding_spin.setValue(settings.number_padding)
        self.padding_spin.valueChanged.connect(lambda v: self._set("number_padding", v))
        self.style_combo = QtWidgets.QComboBox()
        for key, description in (
            ("decimal", "1, 2, 3"),
            ("alpha_lower", "a, b, c"),
            ("alpha_upper", "A, B, C"),
            ("roman_lower", "i, ii, iii"),
            ("roman_upper", "I, II, III"),
        ):
            self.style_combo.addItem(description, key)
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(settings.number_style)))
        self.style_combo.currentIndexChanged.connect(
            lambda: self._set("number_style", self.style_combo.currentData())
        )
        self.separator_edit = QtWidgets.QLineEdit(settings.separator)
        self.separator_edit.setMaxLength(4)
        self.separator_edit.textChanged.connect(lambda v: self._set("separator", v))

        defaults.add(self._row("Start at", self.start_spin))
        defaults.add(self._row("Increment", self.step_spin))
        defaults.add(self._row("Digits", self.padding_spin))
        defaults.add(self._row("Numbering style", self.style_combo))
        defaults.add(self._row("Separator", self.separator_edit))

        self.confirm_check = QtWidgets.QCheckBox("Ask for confirmation before applying a rename")
        self.confirm_check.setChecked(settings.confirm_before_apply)
        self.confirm_check.toggled.connect(lambda v: self._set("confirm_before_apply", v))
        defaults.add(self.confirm_check)

        self.keep_stack_check = QtWidgets.QCheckBox("Remember the rename steps between sessions")
        self.keep_stack_check.setChecked(settings.keep_operation_stack)
        self.keep_stack_check.toggled.connect(self._on_keep_stack)
        defaults.add(self.keep_stack_check)
        layout.addWidget(defaults)

        # ---- history ------------------------------------------------------
        history = Card("History", "sessions are stored in a small local database", icon_name="history")
        self.limit_spin = QtWidgets.QSpinBox()
        self.limit_spin.setRange(10, 10000)
        self.limit_spin.setSingleStep(50)
        self.limit_spin.setValue(settings.history_limit)
        self.limit_spin.setToolTip("Older records are removed automatically once this many sessions exist")
        self.limit_spin.valueChanged.connect(lambda v: self._set("history_limit", v))
        history.add(self._row("Keep this many sessions", self.limit_spin))

        paths = QtWidgets.QLabel(
            f"Settings: {config_dir()}\nHistory:  {data_dir()}"
        )
        paths.setProperty("role", "mono")
        paths.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        history.add(paths)

        storage_buttons = QtWidgets.QHBoxLayout()
        open_config = button("Open settings folder", variant="quiet", icon_name="external")
        open_config.clicked.connect(lambda: self._open_folder(config_dir()))
        storage_buttons.addWidget(open_config)
        open_data = button("Open history folder", variant="quiet", icon_name="external")
        open_data.clicked.connect(lambda: self._open_folder(data_dir()))
        storage_buttons.addWidget(open_data)
        storage_buttons.addStretch(1)
        history.add_layout(storage_buttons)
        layout.addWidget(history)

        # ---- about --------------------------------------------------------
        about = Card("About EzRename", icon_name="info")
        about.add(label(f"Version {__version__} · MIT licence · {APP_URL}", "muted"))
        hints = QtWidgets.QLabel(
            "Keyboard shortcuts\n"
            "  Ctrl+O          choose a folder\n"
            "  Ctrl+Shift+O    add files\n"
            "  Ctrl+R / F5     refresh the file list and preview\n"
            "  Ctrl+F          focus the search box\n"
            "  Ctrl+A          select all files\n"
            "  Delete          remove the selected rows from the list\n"
            "  Ctrl+Enter      apply the renames\n"
            "  Ctrl+Z          undo the newest session\n"
            "  Ctrl+1…5        switch pages"
        )
        hints.setProperty("role", "muted")
        hints.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        about.add(hints)

        about_buttons = QtWidgets.QHBoxLayout()
        about_button = button("About dialog", variant="quiet", icon_name="info")
        about_button.clicked.connect(lambda: AboutDialog(self).exec())
        about_buttons.addWidget(about_button)
        reset_button = button("Reset all settings", variant="quiet", icon_name="refresh")
        reset_button.clicked.connect(self._reset)
        about_buttons.addWidget(reset_button)
        about_buttons.addStretch(1)
        about.add_layout(about_buttons)
        layout.addWidget(about)
        layout.addStretch(1)

        self._loading = False

    # ------------------------------------------------------------------ #
    def _row(self, title: str, control: QtWidgets.QWidget) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        caption = label(title, "body")
        caption.setMinimumWidth(210)
        layout.addWidget(caption)
        layout.addWidget(control, 1)
        if isinstance(control, (QtWidgets.QSpinBox, QtWidgets.QComboBox, QtWidgets.QLineEdit)):
            control.setMaximumWidth(260)
        return row

    def _set(self, name: str, value) -> None:
        if self._loading:
            return
        setattr(self.session.settings, name, value)
        self.session.settings.save()
        self.session.settings_changed.emit()

    def _on_theme_changed(self) -> None:
        if self._loading:
            return
        self.session.settings.theme = self.theme_combo.currentData()
        self.session.settings.accent = self.accent_combo.currentData()
        self.session.settings.save()
        self.theme_changed.emit()

    def _on_keep_stack(self, value: bool) -> None:
        self._set("keep_operation_stack", value)
        if value:
            self.session.persist_operations()

    def _open_folder(self, folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(folder))  # noqa: S606 - opening a folder is intended
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:  # pragma: no cover - platform specific
            show_info(self, "Cannot open the folder", str(exc), kind="error")

    def _reset(self) -> None:
        if not confirm(
            self,
            "Reset all settings?",
            "Every preference returns to its default value.\n\n"
            "Your rename history is not deleted and no file is touched.",
            confirm_text="Reset settings",
            danger=True,
        ):
            return
        from ...core.settings import AppSettings

        self.session.settings = AppSettings()
        self.session.settings.save()
        self.session.settings_changed.emit()
        self.theme_changed.emit()
        self.session.status_message.emit("settings reset to their defaults")
