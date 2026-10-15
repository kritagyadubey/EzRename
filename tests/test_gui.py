"""GUI integration tests.

These build the real window with the real pages (offscreen) and drive them the
way a user would: load a folder, add rename steps, apply the rename, then undo
it from the history page. That way a broken signal connection or a stale
preview is caught by the test suite instead of by the user.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import make_files

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from ezrename.core.operations import new_operation  # noqa: E402
from ezrename.core.settings import AppSettings  # noqa: E402
from ezrename.gui import theme  # noqa: E402
from ezrename.gui.app import build_application  # noqa: E402
from ezrename.gui.main_window import MainWindow  # noqa: E402
from ezrename.gui.session import Session  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = build_application(["ezrename-tests"])
    theme.apply_theme(app, "dark", "blue")
    yield app


@pytest.fixture
def window(qapp, folder: Path):
    session = Session(AppSettings.load())
    win = MainWindow(session)
    win.resize(1360, 900)
    win.show()
    win.show_page("workspace")  # the page a user works in most of the time
    qapp.processEvents()
    yield win
    win.close()
    session.close()


def pump(app: QtWidgets.QApplication, condition, *, timeout_ms: int = 15000) -> bool:
    """Run the event loop until *condition* is true or the timeout expires."""

    elapsed = 0
    step = 25
    while elapsed < timeout_ms:
        app.processEvents()
        if condition():
            return True
        QtCore.QThread.msleep(step)
        app.processEvents()
        elapsed += step
    return condition()


# --------------------------------------------------------------------------- #
# construction
# --------------------------------------------------------------------------- #


def test_window_builds_every_page(window: MainWindow, qapp):
    for key in ("dashboard", "workspace", "tools", "history", "settings"):
        window.show_page(key)
        qapp.processEvents()
        assert window.stack.currentWidget() is window.pages[key]
        assert window.nav_buttons[key].isChecked()


def test_window_has_no_placeholder_pages(window: MainWindow):
    for key, page in window.pages.items():
        assert page.layout() is not None, key
        assert page.findChildren(QtWidgets.QWidget), key


def test_theme_switch_rebuilds_the_interface(window: MainWindow, qapp):
    window.session.settings.theme = "light"
    window.session.settings.accent = "teal"
    window.apply_theme_change()
    qapp.processEvents()
    assert theme.tokens().palette.dark is False
    assert window.session.settings.accent == "teal"
    # switch back for the remaining tests
    window.session.settings.theme = "dark"
    window.apply_theme_change()
    qapp.processEvents()
    assert theme.tokens().palette.dark is True


# --------------------------------------------------------------------------- #
# loading files and previewing
# --------------------------------------------------------------------------- #


def test_loading_a_folder_fills_the_table(window: MainWindow, folder: Path, qapp):
    make_files(folder, ["IMG_1.jpg", "IMG_2.jpg"])
    window.workspace.load_folder(folder)
    qapp.processEvents()
    table = window.workspace.table
    assert table.model.rowCount() == 2
    assert window.workspace.empty_state.isVisible() is False
    assert table.model.checked_count == 0


def test_preview_updates_when_operations_change(window: MainWindow, folder: Path, qapp):
    make_files(folder, ["IMG_1.jpg", "IMG_2.jpg"])
    window.workspace.load_folder(folder)
    qapp.processEvents()

    window.session.add_operation(new_operation("find_replace", find="IMG_", replace="Photo_"))
    qapp.processEvents()
    plan = window.session.plan
    assert plan.summary()["rename"] == 2
    targets = {entry.target_name for entry in plan.entries}
    assert targets == {"Photo_1.jpg", "Photo_2.jpg"}
    assert window.workspace.apply_button.isEnabled()

    window.session.add_operation(new_operation("numbering", position="prefix", padding=3))
    qapp.processEvents()
    assert window.session.plan.entries[0].target_name == "001_Photo_1.jpg"

    window.session.remove_operation(0)
    qapp.processEvents()
    assert window.session.plan.entries[0].target_name == "001_IMG_1.jpg"


def test_preview_row_highlight_data_matches_plan(window: MainWindow, folder: Path, qapp):
    make_files(folder, ["holiday photo.jpg"])
    window.workspace.load_folder(folder)
    window.session.add_operation(new_operation("separators", spaces_to="_"))
    qapp.processEvents()
    model = window.workspace.table.model
    assert model.data(model.index(0, 3), QtCore.Qt.DisplayRole) == "JPG"
    assert model.data(model.index(0, 4), QtCore.Qt.DisplayRole).endswith("B")
    assert model.data(model.index(0, 6), QtCore.Qt.DisplayRole) == "will rename"


def test_conflicting_plan_disables_apply(window: MainWindow, folder: Path, qapp):
    make_files(folder, ["a1.txt", "a2.txt"])
    window.workspace.load_folder(folder)
    window.session.add_operation(new_operation("find_replace", find="1", replace="2"))
    qapp.processEvents()
    assert not window.workspace.apply_button.isEnabled()
    assert window.workspace.blocker_label.isVisible()


def test_dashboard_counters_follow_the_session(window: MainWindow, folder: Path, qapp):
    make_files(folder, ["one.txt", "two.txt"])
    window.workspace.load_folder(folder)
    window.session.add_operation(new_operation("case", mode="upper"))
    qapp.processEvents()
    window.show_page("dashboard")
    qapp.processEvents()
    assert window.dashboard.files_card._value.text() == "2"
    assert window.dashboard.pending_card._value.text() == "2"
    assert window.dashboard.conflict_card._value.text() == "0"
    assert "one.txt" not in window.dashboard.folder_path.full_text().lower()
    assert str(folder) in window.dashboard.folder_path.full_text()


def test_empty_folder_shows_the_empty_state(window: MainWindow, folder: Path, qapp):
    window.workspace.load_folder(folder)
    qapp.processEvents()
    assert window.workspace.empty_state.isVisible()
    assert not window.workspace.apply_button.isEnabled()


def test_sorting_and_reordering_change_the_numbering_order(window: MainWindow, folder: Path, qapp):
    make_files(folder, ["b.txt", "a.txt"])
    window.workspace.load_folder(folder)
    window.session.add_operation(new_operation("numbering", position="prefix", padding=2))
    qapp.processEvents()
    assert [entry.target_name for entry in window.session.plan.entries] == ["01_a.txt", "02_b.txt"]

    window.session.set_sort("name", reverse=True)
    qapp.processEvents()
    assert [entry.target_name for entry in window.session.plan.entries] == ["01_b.txt", "02_a.txt"]

    window.session.move_record(folder / "b.txt", 1)
    qapp.processEvents()
    assert [entry.target_name for entry in window.session.plan.entries] == ["01_a.txt", "02_b.txt"]


def test_removing_rows_from_the_list_keeps_the_files(window: MainWindow, folder: Path, qapp):
    paths = make_files(folder, ["keep.txt", "drop.txt"])
    window.workspace.load_folder(folder)
    qapp.processEvents()
    window.workspace._remove_paths([str(paths[1])])
    qapp.processEvents()
    assert window.workspace.table.model.rowCount() == 1
    assert paths[1].exists(), "removing a row must never delete the file"


def test_dropping_paths_adds_files(window: MainWindow, folder: Path, qapp, tmp_path: Path):
    make_files(folder, ["a.txt"])
    extra = make_files(tmp_path / "extra", ["b.txt"])
    window.workspace.load_folder(folder)
    window.workspace.add_paths([str(path) for path in extra])
    qapp.processEvents()
    assert window.workspace.table.model.rowCount() == 2


# --------------------------------------------------------------------------- #
# applying and undoing
# --------------------------------------------------------------------------- #


def session_id_of(window: MainWindow) -> str:
    return window.session.store.list_sessions(limit=1)[0].id


class _FakeReport(QtCore.QObject):
    """Stands in for the modal completion dialog."""

    undo_requested = QtCore.Signal(str)
    export_requested = QtCore.Signal(str)
    last = None

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result
        _FakeReport.last = result

    def exec(self) -> int:
        return 0


def test_apply_renames_files_and_records_history(window: MainWindow, folder: Path, qapp, monkeypatch):
    make_files(folder, ["IMG_1.jpg", "IMG_2.jpg"])
    monkeypatch.setattr("ezrename.gui.pages.workspace.ReportDialog", _FakeReport)
    window.session.settings.confirm_before_apply = False
    window.workspace.load_folder(folder)
    window.session.add_operation(new_operation("find_replace", find="IMG_", replace="Photo_"))
    qapp.processEvents()

    window.workspace.apply()
    assert pump(qapp, lambda: window.workspace._worker is None)
    assert sorted(path.name for path in folder.iterdir()) == ["Photo_1.jpg", "Photo_2.jpg"]

    result = _FakeReport.last
    assert result is not None and result.summary()["renamed"] == 2

    sessions = window.session.store.list_sessions(limit=5)
    assert sessions and sessions[0].renamed == 2

    window.show_page("history")
    qapp.processEvents()
    assert window.history.table.rowCount() >= 1


def test_undo_from_the_history_page_restores_names(window: MainWindow, folder: Path, qapp, monkeypatch):
    make_files(folder, ["note.txt"])
    monkeypatch.setattr("ezrename.gui.pages.workspace.ReportDialog", _FakeReport)
    window.session.settings.confirm_before_apply = False
    window.session.settings.confirm_before_undo = False
    window.workspace.load_folder(folder)
    window.session.add_operation(new_operation("prefix_suffix", prefix="x_"))
    qapp.processEvents()
    window.workspace.apply()
    assert pump(qapp, lambda: window.workspace._worker is None)
    assert (folder / "x_note.txt").exists()

    session_id = window.session.store.list_sessions(limit=1)[0].id
    window.request_undo(session_id, False)
    assert pump(qapp, lambda: window._undo_worker is None)
    assert (folder / "note.txt").exists()
    assert not (folder / "x_note.txt").exists()


def test_undo_dialog_reports_blockers(window: MainWindow, folder: Path, qapp, monkeypatch):
    make_files(folder, ["note.txt"])
    monkeypatch.setattr("ezrename.gui.pages.workspace.ReportDialog", _FakeReport)
    window.session.settings.confirm_before_apply = False
    window.workspace.load_folder(folder)
    window.session.add_operation(new_operation("prefix_suffix", prefix="x_"))
    qapp.processEvents()
    window.workspace.apply()
    assert pump(qapp, lambda: window.workspace._worker is None)

    session_id = window.session.store.list_sessions(limit=1)[0].id
    (folder / "x_note.txt").unlink()
    report = window.session.store.verify(session_id)
    assert not report.can_undo_anything

    window.session.settings.confirm_before_undo = False
    window.request_undo(session_id, False)
    qapp.processEvents()
    assert "nothing can be undone safely" in window.status_message.text()
    assert window._undo_worker is None, "a blocked undo must not start any filesystem work"


def test_cancelled_apply_leaves_files_consistent(window: MainWindow, folder: Path, qapp, monkeypatch):
    make_files(folder, [f"f{i}.txt" for i in range(8)])
    monkeypatch.setattr("ezrename.gui.pages.workspace.ReportDialog", _FakeReport)
    window.session.settings.confirm_before_apply = False
    window.workspace.load_folder(folder)
    window.session.add_operation(new_operation("numbering", position="prefix", padding=2))
    qapp.processEvents()

    window.workspace.apply()
    window.workspace.cancel()
    assert pump(qapp, lambda: window.workspace._worker is None)
    remaining = sorted(path.name for path in folder.iterdir())
    assert len(remaining) == 8
    assert not [name for name in remaining if name.startswith(".ezrename-tmp.")]


# --------------------------------------------------------------------------- #
# tools, settings, history pages
# --------------------------------------------------------------------------- #


def test_tools_page_adds_and_reorders_steps(window: MainWindow, qapp):
    window.show_page("tools")
    window.tools._add("case")
    qapp.processEvents()
    window.tools._add("prefix_suffix")
    qapp.processEvents()
    assert [op.type for op in window.session.operations] == ["case", "prefix_suffix"]
    assert len(window.tools.stack._cards) == 2

    window.session.move_operation(0, 1)
    qapp.processEvents()
    assert [op.type for op in window.session.operations] == ["prefix_suffix", "case"]


def test_tools_page_presets_round_trip(window: MainWindow, qapp):
    window.tools._add("case")
    window.session.save_preset("Test preset")
    window.tools._refresh_presets()
    qapp.processEvents()
    assert window.tools.preset_combo.findText("Test preset") >= 0

    window.session.clear_operations()
    qapp.processEvents()
    assert window.session.operations == []
    assert window.session.apply_preset("Test preset")
    qapp.processEvents()
    assert [op.type for op in window.session.operations] == ["case"]

    window.session.delete_preset("Test preset")
    window.tools._refresh_presets()
    assert "Test preset" not in window.session.settings.presets


def test_settings_page_persists_changes(window: MainWindow, qapp):
    page = window.settings_page
    page.padding_spin.setValue(5)
    page.confirm_check.setChecked(False)
    page.recursive_check.setChecked(True)
    qapp.processEvents()
    assert window.session.settings.number_padding == 5
    assert window.session.settings.confirm_before_apply is False
    assert window.session.settings.recursive is True
    reloaded = AppSettings.load()
    assert reloaded.number_padding == 5
    assert reloaded.recursive is True


def test_settings_reset_restores_defaults(window: MainWindow, qapp, monkeypatch):
    window.session.settings.number_padding = 9
    monkeypatch.setattr("ezrename.gui.pages.settings.confirm", lambda *a, **k: True)
    window.settings_page._reset()
    qapp.processEvents()
    assert window.session.settings.number_padding == 3


def test_history_page_shows_session_detail(window: MainWindow, folder: Path, qapp, monkeypatch):
    make_files(folder, ["detail.txt"])
    monkeypatch.setattr("ezrename.gui.pages.workspace.ReportDialog", _FakeReport)
    window.session.settings.confirm_before_apply = False
    window.workspace.load_folder(folder)
    window.session.add_operation(new_operation("prefix_suffix", prefix="p_"))
    qapp.processEvents()
    window.workspace.apply()
    assert pump(qapp, lambda: window.workspace._worker is None)

    window.show_page("history")
    window.history.refresh()
    qapp.processEvents()
    assert window.history.table.rowCount() == 1
    assert window.history.entries_table.rowCount() == 1
    assert window.history.undo_button.isEnabled()
    assert window.history.export_button.isEnabled()

    # exporting goes through a native file dialog in the app, so exercise the
    # store directly here instead of opening a modal dialog under pytest.
    manifest = window.session.store.export(session_id_of(window), folder / "manifest.json")
    assert manifest.exists() and "p_" in manifest.read_text(encoding="utf-8")


def test_status_bar_reports_the_session(window: MainWindow, folder: Path, qapp):
    make_files(folder, ["status.txt"])
    window.workspace.load_folder(folder)
    qapp.processEvents()
    assert "1 file(s)" in window.status_message.text()


def test_keyboard_shortcuts_are_registered(window: MainWindow):
    shortcuts = {item.key().toString() for item in window.findChildren(QtGui.QShortcut)}
    for expected in ("Ctrl+O", "Ctrl+Shift+O", "Ctrl+R", "F5", "Ctrl+F", "Ctrl+Z", "Ctrl+Return"):
        assert expected in shortcuts, expected
    assert window.nav_buttons["settings"].shortcut().toString() == "Ctrl+5"
