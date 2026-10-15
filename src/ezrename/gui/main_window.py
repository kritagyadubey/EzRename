"""The EzRename main window: sidebar navigation and the five pages."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import APP_NAME, __version__
from . import theme
from .dialogs import UndoDialog
from .pages import DashboardPage, HistoryPage, SettingsPage, ToolsPage, WorkspacePage
from .session import Session
from .widgets import Toast, label, separator
from .workers import UndoWorker

PAGES = (
    ("dashboard", "Dashboard", "dashboard", "Overview, folder selection and recent activity"),
    ("workspace", "Workspace", "workspace", "Files, preview and applying renames"),
    ("tools", "Rename tools", "tools", "Build and order the rename sequence"),
    ("history", "History & undo", "history", "Previous sessions and recovery"),
    ("settings", "Settings", "settings", "Appearance, defaults and storage"),
)


class MainWindow(QtWidgets.QMainWindow):
    """Application shell."""

    def __init__(self, session: Session, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.session = session
        self.tokens = theme.tokens()
        self._undo_worker: Optional[UndoWorker] = None

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setAcceptDrops(True)
        self.setMinimumSize(1040, 680)
        self.resize(
            max(1040, session.settings.window_width),
            max(680, session.settings.window_height),
        )
        self._build()
        self._wire()
        self._restore_geometry()
        theme.dark_title_bar(self, self.tokens.dark)

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- sidebar ----------------------------------------------------
        sidebar = QtWidgets.QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(224)
        side_layout = QtWidgets.QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 18, 14, 14)
        side_layout.setSpacing(6)

        brand = QtWidgets.QHBoxLayout()
        brand.setSpacing(10)
        from .icons import logo_pixmap

        mark = QtWidgets.QLabel()
        mark.setPixmap(logo_pixmap(34, self.tokens.accent, self.tokens.accent_dark))
        brand.addWidget(mark)
        brand_text = QtWidgets.QVBoxLayout()
        brand_text.setSpacing(0)
        brand_text.addWidget(label(APP_NAME, "title"))
        brand_text.addWidget(label("bulk file renamer", "dim"))
        brand.addLayout(brand_text)
        brand.addStretch(1)
        side_layout.addLayout(brand)
        side_layout.addSpacing(10)

        self.nav_buttons: dict[str, QtWidgets.QPushButton] = {}
        for index, (key, title, icon_name, tooltip) in enumerate(PAGES):
            nav = QtWidgets.QPushButton(f"  {title}")
            nav.setObjectName("NavButton")
            nav.setCheckable(True)
            nav.setAutoExclusive(True)
            nav.setCursor(QtCore.Qt.PointingHandCursor)
            nav.setToolTip(f"{tooltip}  (Ctrl+{index + 1})")
            nav.setIcon(QtGui.QIcon())
            nav.setIconSize(QtCore.QSize(18, 18))
            nav.clicked.connect(lambda _checked=False, k=key: self.show_page(k))
            nav.setShortcut(QtGui.QKeySequence(f"Ctrl+{index + 1}"))
            self.nav_buttons[key] = nav
            side_layout.addWidget(nav)

        side_layout.addStretch(1)
        side_layout.addWidget(separator())
        footer = label(f"v{__version__} · local only, no telemetry", "dim")
        footer.setWordWrap(True)
        side_layout.addWidget(footer)
        layout.addWidget(sidebar)

        # ---- pages ------------------------------------------------------
        self.stack = QtWidgets.QStackedWidget()
        self.pages: dict[str, QtWidgets.QWidget] = {}

        self.dashboard = DashboardPage(self.session)
        self.workspace = WorkspacePage(self.session)
        self.tools = ToolsPage(self.session)
        self.history = HistoryPage(self.session)
        self.settings_page = SettingsPage(self.session)

        for key, page in (
            ("dashboard", self.dashboard),
            ("workspace", self.workspace),
            ("tools", self.tools),
            ("history", self.history),
            ("settings", self.settings_page),
        ):
            self.pages[key] = page
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        # ---- status bar + toast -----------------------------------------
        self.status = QtWidgets.QStatusBar()
        self.status.setSizeGripEnabled(True)
        self.status_message = QtWidgets.QLabel("Ready")
        self.status.addWidget(self.status_message, 1)
        self.history_summary = QtWidgets.QLabel("")
        self.history_summary.setProperty("role", "dim")
        self.status.addPermanentWidget(self.history_summary)
        self.setStatusBar(self.status)

        self.toast = Toast(central)
        self._refresh_nav_icons()

    def _wire(self) -> None:
        self.session.status_message.connect(self.set_status)
        self.session.files_changed.connect(self._update_status_bar)
        self.session.plan_changed.connect(self._update_status_bar)
        self.session.history_changed.connect(self._update_status_bar)

        self.dashboard.open_folder_requested.connect(self.workspace.choose_folder)
        self.dashboard.add_files_requested.connect(self.workspace.add_files)
        self.dashboard.undo_requested.connect(lambda sid: self.request_undo(sid, False))
        self.dashboard.goto_history.connect(lambda: self.show_page("history"))
        self.dashboard.goto_workspace.connect(lambda: self.show_page("workspace"))
        self.history.undo_requested.connect(self.request_undo)
        self.workspace.request_report.connect(lambda sid: self.request_undo(sid, False))
        self.settings_page.theme_changed.connect(self.apply_theme_change)

        shortcut_folder = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+O"), self)
        shortcut_folder.activated.connect(self.workspace.choose_folder)
        shortcut_add = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Shift+O"), self)
        shortcut_add.activated.connect(self.workspace.add_files)
        shortcut_refresh = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+R"), self)
        shortcut_refresh.activated.connect(self.workspace.refresh)
        shortcut_refresh2 = QtGui.QShortcut(QtGui.QKeySequence("F5"), self)
        shortcut_refresh2.activated.connect(self.workspace.refresh)
        search = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+F"), self)
        search.activated.connect(self._focus_search)
        apply_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self)
        apply_shortcut.activated.connect(self._apply)
        apply_shortcut2 = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Enter"), self)
        apply_shortcut2.activated.connect(self._apply)
        undo_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Z"), self)
        undo_shortcut.activated.connect(lambda: self.request_undo("", True))

        self._update_status_bar()

    def _restore_geometry(self) -> None:
        settings = self.session.settings
        if settings.window_maximized:
            self.showMaximized()
        elif settings.window_x >= 0 and settings.window_y >= 0:
            self.move(settings.window_x, settings.window_y)

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #

    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        for name, nav in self.nav_buttons.items():
            nav.setChecked(name == key)
        self._refresh_nav_icons()

    def _refresh_nav_icons(self) -> None:
        """Tint the navigation icons to match the checked state."""

        for key, nav in self.nav_buttons.items():
            icon_name = next(entry[2] for entry in PAGES if entry[0] == key)
            colour = self.tokens.accent if nav.isChecked() else self.tokens.text_muted
            from .icons import icon as _icon

            nav.setIcon(_icon(icon_name, colour, 18))

    def apply_theme_change(self) -> None:
        """Re-apply the theme and rebuild the interface in place.

        Rebuilding keeps every piece of state (loaded files, rename steps,
        selected session) while guaranteeing no widget keeps a stale colour.
        """

        app = QtWidgets.QApplication.instance()
        settings = self.session.settings
        key = self._current_key()
        tokens = theme.set_tokens(
            theme.decorate_tokens(theme.resolve_tokens(settings.theme, settings.accent))
        )
        theme.apply_theme(app, settings.theme, settings.accent)
        self.tokens = tokens
        self.rebuild_ui(key)
        theme.dark_title_bar(self, tokens.dark)
        self.set_status(f"theme set to {settings.theme} ({settings.accent})")

    def rebuild_ui(self, page_key: str = "dashboard") -> None:
        """Recreate the central widget, sidebar and pages.

        The old central widget (and every page inside it) is deleted by Qt when
        the new one is installed, which also drops their signal connections.
        """

        self.toast = None  # type: ignore[assignment]
        self._build()
        self._wire()
        self.show_page(page_key)

    def _current_key(self) -> str:
        current = self.stack.currentWidget()
        for key, page in self.pages.items():
            if page is current:
                return key
        return "dashboard"

    # ------------------------------------------------------------------ #
    # Status, toasts and shortcuts
    # ------------------------------------------------------------------ #

    def set_status(self, message: str) -> None:
        self.status_message.setText(message)
        kind = "info"
        lowered = message.lower()
        if any(word in lowered for word in ("failed", "cannot", "error", "conflict")):
            kind = "error"
        elif any(word in lowered for word in ("renamed", "written", "restored", "saved", "deleted")):
            kind = "success"
        elif "cancel" in lowered:
            kind = "warning"
        self.toast.show_message(message, kind, action_text="History", action=lambda: self.show_page("history"))

    def _update_status_bar(self) -> None:
        plan = self.session.plan
        summary = plan.summary()
        conflicts = summary["duplicates"] + summary["existing"] + summary["invalid"] + summary["errors"]
        parts = [
            f"{len(self.session.records)} file(s)",
            f"{summary['rename']} ready",
        ]
        if conflicts:
            parts.append(f"{conflicts} blocked")
        self.status_message.setText("Ready · " + " · ".join(parts))
        try:
            stats = self.session.store.stats()
            self.history_summary.setText(
                f"history: {stats['renamed']:,} renamed in {stats['sessions']} session(s)"
            )
        except Exception:  # pragma: no cover
            self.history_summary.setText("")

    def _focus_search(self) -> None:
        self.show_page("workspace")
        self.workspace.table.focus_search()

    def _apply(self) -> None:
        self.show_page("workspace")
        self.workspace.apply()

    # ------------------------------------------------------------------ #
    # Undo
    # ------------------------------------------------------------------ #

    def request_undo(self, session_id: str, allow_partial: bool = False) -> None:
        store = self.session.store
        if not session_id:
            latest = store.latest_undoable()
            if latest is None:
                self.set_status("there is no rename session that can be undone")
                return
            session_id = latest.id

        summary = store.get_session(session_id)
        if summary is None:
            self.set_status(f"session {session_id} is not in the history")
            return
        if not summary.undoable:
            self.set_status(f"session {session_id} cannot be undone ({summary.status_label})")
            return

        report = store.verify(session_id)
        if self.session.settings.confirm_before_undo:
            dialog = UndoDialog(summary, report, self)
            dialog.undo_confirmed.connect(self._start_undo)
            dialog.exec()
            return
        if not report.can_undo_anything:
            self.set_status(f"nothing can be undone safely: {report.reason_summary()}")
            return
        if not report.can_undo_all and not allow_partial:
            self.set_status(
                "some files cannot be restored safely: "
                f"{report.reason_summary()} — open the undo dialog to restore the safe ones"
            )
            return
        self._start_undo(session_id, allow_partial)

    def _start_undo(self, session_id: str, allow_partial: bool) -> None:
        self.show_page("history")
        self.workspace.progress.set_progress(0, 1, "Checking the files…")
        self.history.setEnabled(False)
        worker = UndoWorker(self.session.store, session_id, allow_partial=allow_partial, parent=self)
        worker.completed.connect(self._on_undo_done)
        worker.failed.connect(lambda message: self.set_status(f"the undo could not run: {message}"))
        worker.finished.connect(self._on_undo_finished)
        self._undo_worker = worker
        worker.start()

    def _on_undo_done(self, result) -> None:
        if result.execution is not None:
            summary = result.execution.summary()
            self.set_status(
                f"undo: {summary['renamed']} restored, {summary['failed']} failed"
                + (" (partial)" if result.partial else "")
            )
        else:
            self.set_status(result.message)
        self.session.history_changed.emit()
        self.session.refresh()
        self.session.files_changed.emit()
        self.history.refresh()

    def _on_undo_finished(self) -> None:
        self._undo_worker = None
        self.history.setEnabled(True)

    # ------------------------------------------------------------------ #
    # Drag and drop anywhere in the window
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if not paths:
            return
        event.acceptProposedAction()
        folders = [path for path in paths if path.is_dir()]
        if len(folders) == 1 and len(paths) == 1:
            self.workspace.load_folder(folders[0])
        else:
            self.workspace.add_paths([str(path) for path in paths])
        self.show_page("workspace")

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        settings = self.session.settings
        settings.window_maximized = self.isMaximized()
        if not self.isMaximized():
            settings.window_width = self.width()
            settings.window_height = self.height()
            settings.window_x = self.x()
            settings.window_y = self.y()
        settings.save()
        self.session.persist_operations()
        if self._undo_worker is not None:
            self._undo_worker.cancel()
        self.session.close()
        super().closeEvent(event)
