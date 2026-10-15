"""Dashboard: the first thing the user sees, with real information."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtWidgets

from .. import theme
from ..widgets import Card, DropArea, ElidedLabel, StatCard, button, label


class DashboardPage(QtWidgets.QWidget):
    """Landing page with folder actions, live counters and recent sessions."""

    open_folder_requested = QtCore.Signal()
    add_files_requested = QtCore.Signal()
    undo_requested = QtCore.Signal(str)
    goto_history = QtCore.Signal()
    goto_workspace = QtCore.Signal()

    def __init__(self, session, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.session = session
        self.tokens = theme.tokens()

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

        # ---- hero -------------------------------------------------------
        hero = QtWidgets.QFrame()
        hero.setObjectName("Card")
        hero_layout = QtWidgets.QHBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(18)

        from ..icons import logo_pixmap

        mark = QtWidgets.QLabel()
        mark.setPixmap(logo_pixmap(58, self.tokens.accent, self.tokens.accent_dark))
        hero_layout.addWidget(mark, 0, QtCore.Qt.AlignTop)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(label("Rename hundreds of files without fear", "display"))
        subtitle = label(
            "EzRename previews every change before it happens, refuses to overwrite "
            "existing files, and records each session so you can undo it.",
            "muted",
        )
        subtitle.setWordWrap(True)
        left.addWidget(subtitle)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(8)
        self.choose_button = button("Choose folder…", variant="primary", icon_name="folder")
        self.choose_button.setToolTip("Pick the folder that holds the files to rename (Ctrl+O)")
        buttons.addWidget(self.choose_button)
        self.add_button = button("Add files…", icon_name="file_plus")
        self.add_button.setToolTip("Add individual files instead of a whole folder")
        buttons.addWidget(self.add_button)
        self.workspace_button = button("Open workspace", variant="quiet", icon_name="workspace")
        buttons.addWidget(self.workspace_button)
        buttons.addStretch(1)
        left.addSpacing(6)
        left.addLayout(buttons)
        hero_layout.addLayout(left, 1)
        layout.addWidget(hero)

        # ---- drop target ------------------------------------------------
        self.drop_area = DropArea(
            "Drop a folder or files here",
            "Everything stays read-only until you press Apply in the workspace",
        )
        self.drop_area.paths_dropped.connect(self._on_paths_dropped)
        layout.addWidget(self.drop_area)

        # ---- metrics ----------------------------------------------------
        metrics = QtWidgets.QHBoxLayout()
        metrics.setSpacing(12)
        self.files_card = StatCard("Files loaded", "0", icon_name="list", hint="selected for renaming")
        self.pending_card = StatCard("Pending renames", "0", icon_name="play", hint="would change")
        self.conflict_card = StatCard("Conflicts", "0", icon_name="alert", hint="need attention")
        self.history_card = StatCard("Renamed in history", "0", icon_name="history", hint="across all sessions")
        for card in (self.files_card, self.pending_card, self.conflict_card, self.history_card):
            metrics.addWidget(card, 1)
        layout.addLayout(metrics)

        # ---- lower area -------------------------------------------------
        lower = QtWidgets.QHBoxLayout()
        lower.setSpacing(14)

        self.folder_card = Card("Current folder", "where the next rename will happen", icon_name="folder")
        self.folder_path = ElidedLabel("no folder selected")
        self.folder_path.setProperty("role", "body")
        self.folder_card.add(self.folder_path)
        self.folder_meta = label("", "dim")
        self.folder_card.add(self.folder_meta)
        self.drop_hint = label(
            "Drag and drop works everywhere in the window, including folders.",
            "dim",
        )
        self.drop_hint.setWordWrap(True)
        self.folder_card.add(self.drop_hint)

        self.recent_card = Card("Recent sessions", "click a row to see the detail", icon_name="clock")
        self.recent_card.add_header_action(
            self._link_button("Open history", self.goto_history.emit, "external")
        )
        self.recent_list = QtWidgets.QVBoxLayout()
        self.recent_list.setSpacing(6)
        self.recent_card.add_layout(self.recent_list)
        self.no_history = label("No rename session has been recorded yet.", "dim")
        self.recent_card.add(self.no_history)

        lower.addWidget(self.folder_card, 1)
        lower.addWidget(self.recent_card, 1)
        layout.addLayout(lower)
        layout.addStretch(1)

        # ---- wiring -----------------------------------------------------
        self.choose_button.clicked.connect(self.open_folder_requested.emit)
        self.add_button.clicked.connect(self.add_files_requested.emit)
        self.workspace_button.clicked.connect(self.goto_workspace.emit)
        self.session.files_changed.connect(self.refresh)
        self.session.plan_changed.connect(self.refresh)
        self.session.history_changed.connect(self.refresh)
        self.session.settings_changed.connect(self.refresh)
        self.refresh()

    def _link_button(self, text: str, slot, icon_name: str) -> QtWidgets.QPushButton:
        widget = button(text, variant="ghost", icon_name=icon_name)
        widget.clicked.connect(slot)
        return widget

    # ------------------------------------------------------------------ #
    def _on_paths_dropped(self, paths) -> None:
        self.session.add_paths([Path(path) for path in paths])
        self.session.status_message.emit(f"{len(self.session.records)} file(s) loaded")
        self.goto_workspace.emit()

    def refresh(self) -> None:
        plan = self.session.plan
        summary = plan.summary()
        conflicts = summary["duplicates"] + summary["existing"] + summary["invalid"] + summary["errors"]

        self.files_card.set_value(str(len(self.session.records)))
        self.pending_card.set_value(str(summary["rename"]))
        self.conflict_card.set_value(
            str(conflicts), tone="danger" if conflicts else ""
        )
        try:
            stats = self.session.store.stats()
        except Exception:  # pragma: no cover - unreadable history
            stats = {"renamed": 0, "sessions": 0}
        self.history_card.set_value(
            f"{stats['renamed']:,}",
            hint=f"across {stats['sessions']} session(s)",
        )

        if self.session.root:
            self.folder_path.setText(str(self.session.root))
            self.folder_meta.setText(
                f"{len(self.session.records)} file(s) loaded · "
                f"{summary['rename']} ready to rename"
            )
        elif self.session.records:
            self.folder_path.setText(f"{len(self.session.records)} individual file(s)")
            self.folder_meta.setText("added manually or by drag and drop")
        else:
            self.folder_path.setText("no folder selected")
            self.folder_meta.setText("choose a folder to get started")

        self._rebuild_recent()

    def _rebuild_recent(self) -> None:
        while self.recent_list.count():
            item = self.recent_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        try:
            sessions = self.session.store.list_sessions(limit=5)
        except Exception:  # pragma: no cover
            sessions = []
        self.no_history.setVisible(not sessions)
        for summary in sessions:
            self.recent_list.addWidget(self._session_row(summary))

    def _session_row(self, summary) -> QtWidgets.QWidget:
        row = QtWidgets.QFrame()
        row.setObjectName("CardFlat")
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)

        when = summary.created_at.astimezone().strftime("%d %b · %H:%M") if summary.created_at else "?"
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(1)
        heading = ElidedLabel(summary.root or "individual files")
        heading.setProperty("role", "body")
        text.addWidget(heading)
        text.addWidget(label(f"{when} · {summary.renamed} renamed · {summary.status_label}", "dim"))
        layout.addLayout(text, 1)

        if summary.undoable:
            undo = button("Undo", variant="quiet", icon_name="undo")
            undo.setToolTip(f"Restore the names from session {summary.id}")
            undo.clicked.connect(lambda _checked=False, sid=summary.id: self.undo_requested.emit(sid))
            layout.addWidget(undo)
        return row
