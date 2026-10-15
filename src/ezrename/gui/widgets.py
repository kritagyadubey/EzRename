"""Reusable interface building blocks.

Everything the pages are made of lives here so spacing, radii, icon sizes and
hover behaviour stay identical across the whole application.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from . import theme
from .icons import icon as _icon, logo_pixmap


def label(text: str, role: str = "body", parent: Optional[QtWidgets.QWidget] = None) -> QtWidgets.QLabel:
    """Create a styled label (``role`` maps to a stylesheet selector)."""

    widget = QtWidgets.QLabel(text, parent)
    widget.setProperty("role", role)
    if role == "section":
        font = widget.font()
        font.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 1.0)
        widget.setFont(font)
        widget.setText(text.upper())
    return widget


def badge(text: str, kind: str = "muted", parent: Optional[QtWidgets.QWidget] = None) -> QtWidgets.QLabel:
    """Small pill label. ``kind`` is ``ok``/``warn``/``bad``/``info``/``muted``."""

    widget = QtWidgets.QLabel(text, parent)
    widget.setProperty("badge", "true")
    widget.setProperty("tone", kind)
    widget.setAlignment(QtCore.Qt.AlignCenter)
    return widget


def button(
    text: str,
    *,
    variant: str = "default",
    icon_name: str = "",
    tooltip: str = "",
    shortcut: str = "",
    parent: Optional[QtWidgets.QWidget] = None,
) -> QtWidgets.QPushButton:
    """Styled push button; ``variant`` is ``primary``/``ghost``/``quiet``/``danger``."""

    tokens = theme.tokens()
    widget = QtWidgets.QPushButton(text, parent)
    widget.setProperty("variant", variant)
    widget.setCursor(QtCore.Qt.PointingHandCursor)
    if icon_name:
        tone = "#FFFFFF" if variant in ("primary", "danger") else tokens.palette.text_muted
        widget.setIcon(_icon(icon_name, tone, 17))
        widget.setIconSize(QtCore.QSize(17, 17))
    if tooltip:
        widget.setToolTip(tooltip)
    if shortcut:
        widget.setShortcut(QtGui.QKeySequence(shortcut))
    if not text:
        widget.setFixedSize(32, 32)
    return widget


def icon_button(
    icon_name: str,
    tooltip: str,
    *,
    size: int = 28,
    tone: Optional[str] = None,
    parent: Optional[QtWidgets.QWidget] = None,
) -> QtWidgets.QPushButton:
    tokens = theme.tokens()
    widget = QtWidgets.QPushButton(parent)
    widget.setObjectName("IconButton")
    widget.setIcon(_icon(icon_name, tone or tokens.palette.text_muted, 17))
    widget.setIconSize(QtCore.QSize(17, 17))
    widget.setFixedSize(size, size)
    widget.setToolTip(tooltip)
    widget.setCursor(QtCore.Qt.PointingHandCursor)
    return widget


def separator(horizontal: bool = True) -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setObjectName("Separator")
    line.setFrameShape(QtWidgets.QFrame.HLine if horizontal else QtWidgets.QFrame.VLine)
    line.setFixedHeight(1 if horizontal else 0)
    return line


class Card(QtWidgets.QFrame):
    """Rounded surface with an optional header row."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        *,
        icon_name: str = "",
        padding: int = 18,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.tokens = theme.tokens()
        self._outer = QtWidgets.QVBoxLayout(self)
        self._outer.setContentsMargins(padding, padding, padding, padding)
        self._outer.setSpacing(12)
        self.header_actions: QtWidgets.QHBoxLayout
        self.body = QtWidgets.QVBoxLayout()
        self.body.setSpacing(10)

        if title:
            header = QtWidgets.QHBoxLayout()
            header.setSpacing(10)
            if icon_name:
                glyph = QtWidgets.QLabel()
                glyph.setPixmap(_icon(icon_name, self.tokens.accent, 18).pixmap(18, 18))
                header.addWidget(glyph)
            titles = QtWidgets.QVBoxLayout()
            titles.setSpacing(1)
            titles.addWidget(label(title, "title"))
            if subtitle:
                titles.addWidget(label(subtitle, "dim"))
            header.addLayout(titles)
            header.addStretch(1)
            self.header_actions = QtWidgets.QHBoxLayout()
            self.header_actions.setSpacing(6)
            header.addLayout(self.header_actions)
            self._outer.addLayout(header)
        else:
            self.header_actions = QtWidgets.QHBoxLayout()
        self._outer.addLayout(self.body)

    def add(self, widget: QtWidgets.QWidget, stretch: int = 0) -> QtWidgets.QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout: QtWidgets.QLayout) -> QtWidgets.QLayout:
        self.body.addLayout(layout)
        return layout

    def add_header_action(self, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        self.header_actions.addWidget(widget)
        return widget


class StatCard(QtWidgets.QFrame):
    """Compact metric tile used by the dashboard."""

    def __init__(
        self,
        title: str,
        value: str = "0",
        *,
        icon_name: str = "list",
        hint: str = "",
        accent: Optional[str] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.tokens = theme.tokens()
        self._accent = accent or self.tokens.accent
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        self._glyph = QtWidgets.QLabel()
        self._glyph.setPixmap(_icon(icon_name, self._accent, 16).pixmap(16, 16))
        header.addWidget(self._glyph)
        header.addWidget(label(title, "section"))
        header.addStretch(1)
        layout.addLayout(header)

        self._value = label(value, "stat")
        layout.addWidget(self._value)

        self._hint = label(hint, "dim")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)
        layout.addStretch(1)

    def set_value(self, value: str, hint: Optional[str] = None, *, tone: str = "") -> None:
        self._value.setText(value)
        self._value.setProperty("role", tone or "stat")
        self._value.style().unpolish(self._value)
        self._value.style().polish(self._value)
        if hint is not None:
            self._hint.setText(hint)


class DropArea(QtWidgets.QFrame):
    """Dashed drop target that accepts files and folders."""

    paths_dropped = QtCore.Signal(list)

    def __init__(
        self,
        title: str = "Drop files or folders here",
        hint: str = "or use the buttons above",
        *,
        compact: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DropArea")
        self.setAcceptDrops(True)
        self.setProperty("active", "false")
        self.tokens = theme.tokens()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 24 if not compact else 16, 24, 24 if not compact else 16)
        layout.setSpacing(8 if not compact else 4)
        layout.setAlignment(QtCore.Qt.AlignCenter)

        glyph = QtWidgets.QLabel()
        glyph.setPixmap(_icon("folder_open", self.tokens.text_muted, 34 if not compact else 24).pixmap(34, 34))
        glyph.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(glyph)

        self.title = label(title, "title" if not compact else "body")
        self.title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.title)

        self.hint = label(hint, "dim")
        self.hint.setAlignment(QtCore.Qt.AlignCenter)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

    # -- drag & drop -----------------------------------------------------
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:  # noqa: N802
        self._set_active(False)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802
        self._set_active(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.paths_dropped.emit([str(path) for path in paths])
            event.acceptProposedAction()

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class EmptyState(QtWidgets.QWidget):
    """Illustrated empty state with a primary action."""

    def __init__(
        self,
        title: str,
        description: str,
        *,
        icon_name: str = "workspace",
        action: str = "",
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        tokens = theme.tokens()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignCenter)
        layout.setSpacing(12)

        tile = QtWidgets.QLabel()
        tile.setFixedSize(64, 64)
        tile.setAlignment(QtCore.Qt.AlignCenter)
        tile.setPixmap(logo_pixmap(52, tokens.accent, tokens.accent_dark))
        layout.addWidget(tile, 0, QtCore.Qt.AlignCenter)

        heading = label(title, "title")
        heading.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(heading)

        body = label(description, "muted")
        body.setAlignment(QtCore.Qt.AlignCenter)
        body.setWordWrap(True)
        layout.addWidget(body)

        self.action_button = button(action, variant="primary", icon_name="folder") if action else None
        if self.action_button is not None:
            layout.addWidget(self.action_button, 0, QtCore.Qt.AlignCenter)


class SearchField(QtWidgets.QLineEdit):
    """Search input with a leading glyph and a clear button."""

    def __init__(self, placeholder: str = "Search file names", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        tokens = theme.tokens()
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(180)
        action_icon = _icon("search", tokens.text_dim, 15)
        self.addAction(action_icon, QtWidgets.QLineEdit.LeadingPosition)
        self.setToolTip("Filter the file list by name (Ctrl+F)")


class Toast(QtWidgets.QFrame):
    """Transient message shown at the bottom of the main window."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        self.glyph = QtWidgets.QLabel()
        layout.addWidget(self.glyph)
        self.text_label = label("", "body")
        layout.addWidget(self.text_label)
        self.action = button("", variant="ghost")
        self.action.hide()
        self.action.clicked.connect(self._run_action)
        layout.addWidget(self.action)
        self._action_callback: Optional[Callable[[], None]] = None
        self.hide()

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(
        self,
        message: str,
        kind: str = "info",
        *,
        timeout: int = 4200,
        action_text: str = "",
        action: Optional[Callable[[], None]] = None,
    ) -> None:
        tokens = theme.tokens()
        tones = {
            "info": (tokens.accent, "info"),
            "success": (tokens.palette.success, "check"),
            "warning": (tokens.palette.warning, "alert"),
            "error": (tokens.palette.danger, "alert"),
        }
        colour, glyph = tones.get(kind, tones["info"])
        self.glyph.setPixmap(_icon(glyph, colour, 17).pixmap(17, 17))
        self.text_label.setText(message)
        self._action_callback = action if action_text else None
        if action_text and action is not None:
            self.action.setText(action_text)
            self.action.show()
        else:
            self.action.hide()
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start(timeout)

    def _run_action(self) -> None:
        callback = self._action_callback
        self.hide()
        if callback is not None:
            callback()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        hint = self.sizeHint()
        self.setFixedWidth(min(max(hint.width(), 280), max(320, parent.width() - 80)))
        self.adjustSize()
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 26
        self.move(max(20, x), max(20, y))


class ProgressPanel(QtWidgets.QFrame):
    """Progress bar with a label and a cancel button."""

    cancelled = QtCore.Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        row = QtWidgets.QHBoxLayout()
        self.caption = label("Working…", "body")
        row.addWidget(self.caption)
        row.addStretch(1)
        self.cancel_button = button("Cancel", variant="quiet", icon_name="close")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

    def set_progress(self, done: int, total: int, message: str = "") -> None:
        total = max(1, total)
        self.bar.setRange(0, total)
        self.bar.setValue(min(done, total))
        self.caption.setText(message or f"Renaming {done} of {total}…")


class FieldRow(QtWidgets.QWidget):
    """Label + control row with an optional hint underneath."""

    def __init__(
        self,
        title: str,
        control: QtWidgets.QWidget,
        hint: str = "",
        *,
        stacked: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self) if stacked else QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6 if stacked else 10)
        self.control = control
        text = label(title, "body")
        if stacked:
            layout.addWidget(text)
            layout.addWidget(control)
        else:
            text.setMinimumWidth(150)
            layout.addWidget(text)
            layout.addWidget(control, 1)
        if hint:
            hint_label = label(hint, "dim")
            hint_label.setWordWrap(True)
            if stacked:
                layout.addWidget(hint_label)
            else:
                hint_label.setMinimumWidth(0)
                layout.addWidget(hint_label, 1)
        if isinstance(control, (QtWidgets.QLineEdit, QtWidgets.QSpinBox, QtWidgets.QComboBox)):
            control.setMinimumWidth(160)


class ElidedLabel(QtWidgets.QLabel):
    """Label that elides long text instead of expanding the layout."""

    def __init__(self, text: str = "", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        super().setText(text)
        self.setToolTip(text)

    def full_text(self) -> str:
        return self._full

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        metrics = QtGui.QFontMetrics(self.font())
        text = metrics.elidedText(self._full, QtCore.Qt.ElideMiddle, max(10, self.width() - 2))
        painter.setPen(self.palette().color(QtGui.QPalette.WindowText))
        painter.drawText(self.rect(), int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft), text)
        painter.end()

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return QtCore.QSize(80, super().sizeHint().height())


def scroll_page(content: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
    """Wrap a page in a themed scroll area."""

    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.NoFrame)
    area.setWidget(content)
    area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    return area


def hbox(*widgets: QtWidgets.QWidget, spacing: int = 8) -> QtWidgets.QHBoxLayout:
    layout = QtWidgets.QHBoxLayout()
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    return layout


def vbox(*widgets: Optional[QtWidgets.QWidget], spacing: int = 8) -> QtWidgets.QVBoxLayout:
    layout = QtWidgets.QVBoxLayout()
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        else:
            layout.addWidget(widget)
    return layout


def clear_layout(layout: QtWidgets.QLayout) -> None:
    """Remove and delete every child of *layout*."""

    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def set_badge(widget: QtWidgets.QLabel, text: str, kind: str = "muted") -> None:
    """Update a badge's text and colour in place."""

    widget.setText(text)
    widget.setProperty("tone", kind)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def show_info(parent: QtWidgets.QWidget, title: str, message: str, *, kind: str = "info") -> None:
    """Consistent message box used for messages that need acknowledgement."""

    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(
        {
            "info": QtWidgets.QMessageBox.Information,
            "warning": QtWidgets.QMessageBox.Warning,
            "error": QtWidgets.QMessageBox.Critical,
            "question": QtWidgets.QMessageBox.Question,
        }.get(kind, QtWidgets.QMessageBox.Information)
    )
    box.setTextFormat(QtCore.Qt.PlainText)
    box.exec()


def confirm(
    parent: QtWidgets.QWidget,
    title: str,
    message: str,
    *,
    confirm_text: str = "Continue",
    danger: bool = False,
) -> bool:
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setTextFormat(QtCore.Qt.PlainText)
    box.setIcon(QtWidgets.QMessageBox.Question)
    accept = box.addButton(confirm_text, QtWidgets.QMessageBox.AcceptRole)
    box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is accept
