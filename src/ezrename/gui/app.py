"""Graphical application entry point.

``EzRename.exe`` (and ``python -m ezrename``) lands here. The CLI can also call
:func:`launch` for ``ezrename gui``.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Optional, Sequence

from PySide6 import QtWidgets

from .. import APP_NAME, __version__
from ..core.settings import AppSettings
from . import theme
from .main_window import MainWindow
from .session import Session


def _install_excepthook(window_box: dict) -> None:
    """Show unexpected errors in a dialog instead of losing them silently."""

    def hook(exc_type, value, tb) -> None:  # pragma: no cover - only on real errors
        message = "".join(traceback.format_exception_only(exc_type, value)).strip()
        details = "".join(traceback.format_exception(exc_type, value, tb))
        print(details, file=sys.stderr)
        parent = window_box.get("window")
        box = QtWidgets.QMessageBox(parent)
        box.setWindowTitle(f"{APP_NAME} hit an unexpected problem")
        box.setIcon(QtWidgets.QMessageBox.Critical)
        box.setText(
            f"{message}\n\nYour files were not changed. You can keep working, or close "
            "and reopen EzRename."
        )
        box.setDetailedText(details)
        box.exec()

    sys.excepthook = hook


def build_application(argv: Optional[Sequence[str]] = None) -> QtWidgets.QApplication:
    """Create (or reuse) the QApplication with EzRename's metadata."""

    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    app = QtWidgets.QApplication(list(argv) if argv is not None else sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setDesktopFileName("ezrename")
    return app


def launch(folder: Optional[Path] = None, *, argv: Optional[Sequence[str]] = None) -> int:
    """Start the GUI and return the process exit code."""

    app = build_application(argv)
    settings = AppSettings.load()
    theme.apply_theme(app, settings.theme, settings.accent)

    if not settings.default_folder:
        settings.default_folder = str(Path.home())
        settings.save()

    session = Session(settings)
    window_box: dict = {}
    _install_excepthook(window_box)

    window = MainWindow(session)
    window_box["window"] = window
    window.show()

    if folder is not None:
        window.workspace.load_folder(Path(folder))
        window.show_page("workspace")
    elif settings.last_folder and Path(settings.last_folder).is_dir() and not settings.seen_welcome:
        window.show_page("dashboard")

    if not settings.seen_welcome:
        settings.seen_welcome = True
        settings.last_version = __version__
        settings.save()

    return app.exec()


def self_test() -> int:
    """Build the interface offscreen and exit.

    Used by the release script to prove the packaged executable can start, load
    its Qt plugins and construct every page without a display.
    """

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = build_application(["ezrename-self-test"])
    settings = AppSettings.load()
    theme.apply_theme(app, settings.theme, settings.accent)
    session = Session(settings)
    window = MainWindow(session)
    window.resize(1280, 820)
    window.show()
    for page in ("dashboard", "workspace", "tools", "history", "settings"):
        window.show_page(page)
        app.processEvents()
    window.close()
    session.close()
    print(f"{APP_NAME} {__version__}: graphical interface constructed successfully")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Console-script entry point (``ezrename-gui`` and ``EzRename.exe``)."""

    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in args:
        return self_test()
    if "--version" in args:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--help" in args or "-h" in args:
        print(
            f"{APP_NAME} {__version__} — graphical bulk file renamer\n\n"
            "Usage: EzRename.exe [FOLDER]\n\n"
            "  FOLDER        folder to load at startup\n"
            "  --self-test   build the interface and exit (used by the release script)\n"
            "  --version     print the version and exit\n\n"
            "The command line interface lives in ezrename-cli.exe (run it with --help)."
        )
        return 0

    folder = None
    for token in args:
        if token.startswith("-"):
            continue
        candidate = Path(token)
        if candidate.exists():
            folder = candidate
            break
    return launch(folder, argv=sys.argv[:1])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
