"""Capture real screenshots of the running EzRename application.

The script drives the actual window (not a mock-up): it creates a demo folder,
performs a couple of real rename sessions so the dashboard and history pages
have data, then grabs every page and writes PNG files into ``assets/screenshots``.
It also runs layout and pixel sanity checks so a blank or clipped render is
reported instead of being published.

Usage::

    python tools/make_screenshots.py [--keep-demo]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEMO_FILES = {
    "photos": [
        "IMG_2043.jpg",
        "IMG_2044.jpg",
        "IMG_2045.jpg",
        "IMG_2046.jpg",
        "IMG_2047.jpg",
        "Summer trip 2026.jpg",
        "sunset over the lake.JPG",
        "family dinner.jpg",
        "DSC_0091.png",
        "DSC_0092.png",
        "beach - copy.jpg",
        "beach - copy (2).jpg",
    ],
    "documents": [
        "Quarterly Report FINAL.pdf",
        "Quarterly Report FINAL v2.pdf",
        "invoice 2026-01.pdf",
        "invoice 2026-02.pdf",
        "meeting notes.txt",
    ],
}


def demo_root() -> Path:
    """Prefer the user's Pictures folder for a natural-looking path."""

    override = os.environ.get("EZRENAME_DEMO_DIR")
    if override:
        return Path(override)
    pictures = Path.home() / "Pictures"
    base = pictures if pictures.is_dir() else Path(tempfile.gettempdir())
    return base / "EzRename Demo"


def build_demo(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    for folder, files in DEMO_FILES.items():
        target = root / folder
        target.mkdir(parents=True)
        for index, name in enumerate(files):
            path = target / name
            # realistic sizes so the size column and templates show real values
            path.write_bytes(b"\xff\xd8\xff\xe0" + bytes(1024 * (12 + index * 7)))


def seed_history(root: Path) -> None:
    """Run real renames so history, undo and the dashboard show real data."""

    from ezrename.core.discovery import scan_directory, sort_records
    from ezrename.core.engine import RenameEngine
    from ezrename.core.history import HistoryStore
    from ezrename.core.operations import new_operation
    from ezrename.core.pipeline import build_plan

    store = HistoryStore()
    photos = root / "photos"
    documents = root / "documents"

    # 1. strip the camera prefixes from the photos
    records = sort_records(scan_directory(photos).records, "name")
    plan = build_plan(records, [new_operation("find_replace", find="IMG_", replace="Holiday_")])
    result = RenameEngine().execute(plan)
    store.record(result)

    # 2. tidy the document names
    records = sort_records(scan_directory(documents).records, "name")
    plan = build_plan(
        records,
        [
            new_operation("find_replace", find=" FINAL", replace=""),
            new_operation("separators", spaces_to="_"),
        ],
    )
    result = RenameEngine().execute(plan)
    store.record(result)

    # 3. number the remaining photos in shooting order
    records = sort_records(scan_directory(photos).records, "name")
    plan = build_plan(
        records,
        [new_operation("numbering", start=1, padding=3, position="prefix")],
    )
    store.record(RenameEngine().execute(plan))

    # leave one session undone so the history page shows both states
    sessions = store.list_sessions(limit=3)
    if sessions:
        store.undo(sessions[0].id)
    store.close()


def pump(app, rounds: int = 6, pause_ms: int = 60) -> None:
    from PySide6 import QtCore

    for _ in range(rounds):
        app.processEvents()
        QtCore.QThread.msleep(pause_ms)
        app.processEvents()


def check_layout(window, page_name: str) -> list[str]:
    """Return a list of layout problems for the captured page."""

    from PySide6 import QtWidgets

    problems: list[str] = []
    widgets = [window] + window.findChildren(QtWidgets.QWidget)
    for widget in widgets:
        if not widget.isVisible():
            continue
        if widget.width() <= 0 or widget.height() <= 0:
            problems.append(f"{type(widget).__name__} has zero size")
            continue
        parent = widget.parentWidget()
        if parent is not None and isinstance(widget, QtWidgets.QAbstractButton):
            if widget.width() < 20 or widget.height() < 18:
                problems.append(
                    f"button '{widget.text()}' is only {widget.width()}x{widget.height()}px"
                )
    return problems


def check_pixels(pixmap, window, expected_background: str) -> list[str]:
    """Verify the render is not blank and the expected theme colours are present."""

    from PySide6 import QtGui

    problems: list[str] = []
    image = pixmap.toImage()
    if image.isNull():
        return ["the capture is empty"]
    colours = {image.pixelColor(x, y).name() for x in range(0, image.width(), 40)
               for y in range(0, image.height(), 40)}
    if len(colours) < 8:
        problems.append(f"the page looks blank or flat ({len(colours)} distinct colours sampled)")
    if QtGui.QColor(expected_background).name() not in colours:
        problems.append(
            f"the expected window background {expected_background} was not found in the capture "
            f"(sampled {len(colours)} colours)"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture EzRename screenshots")
    parser.add_argument("--keep-demo", action="store_true", help="keep the demo folder afterwards")
    parser.add_argument(
        "--output",
        default=str(ROOT / "assets" / "screenshots"),
        help="where the PNG files are written",
    )
    args = parser.parse_args()

    home = Path(tempfile.mkdtemp(prefix="ezrename-shots-home-"))
    os.environ["EZRENAME_HOME"] = str(home)

    root = demo_root()
    build_demo(root)
    seed_history(root)

    from ezrename.core.operations import new_operation
    from ezrename.core.settings import AppSettings
    from ezrename.gui import theme
    from ezrename.gui.app import build_application
    from ezrename.gui.main_window import MainWindow
    from ezrename.gui.session import Session

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    app = build_application(["ezrename-screenshots"])
    settings = AppSettings.load()
    settings.theme = "dark"
    settings.accent = "blue"
    settings.confirm_before_apply = True
    settings.save()
    theme.apply_theme(app, settings.theme, settings.accent)

    session = Session(settings)
    window = MainWindow(session)
    window.resize(1500, 940)
    window.show()
    pump(app)

    results: list[str] = []

    def capture(name: str, *, page: str, prepare=None) -> None:
        from ezrename.gui import theme as theme_module

        if prepare is not None:
            prepare()
        window.show_page(page)
        pump(app, rounds=8)
        current = theme_module.tokens()
        problems = check_layout(window, name) + check_pixels(
            window.grab(), window, current.palette.base
        )
        target = output / f"{name}.png"
        window.grab().save(str(target), "PNG")
        label = f"{name}.png ({target.stat().st_size // 1024} KB)"
        if problems:
            results.append(f"  ! {label} - " + "; ".join(problems[:4]))
        else:
            results.append(f"  ok {label}")

    # --- dashboard (empty state, first launch) --------------------------
    capture("01-dashboard", page="dashboard")

    # --- workspace with a real preview ---------------------------------
    def prepare_workspace() -> None:
        session.add_folder(root / "photos")
        session.set_operations(
            [
                new_operation("find_replace", find="Holiday_", replace="Holiday 2026 - "),
                new_operation("numbering", start=1, padding=2, position="prefix"),
            ]
        )

    capture("02-workspace-preview", page="workspace", prepare=prepare_workspace)

    # --- workspace showing a conflict ----------------------------------
    def prepare_conflict() -> None:
        session.set_operations(
            [new_operation("find_replace", find=r"\d", replace="", use_regex=True)]
        )

    capture("03-workspace-conflicts", page="workspace", prepare=prepare_conflict)

    # --- tools page ----------------------------------------------------
    def prepare_tools() -> None:
        session.set_operations(
            [
                new_operation("separators", spaces_to="_", collapse_repeats=True),
                new_operation("case", mode="title", scope="stem"),
                new_operation("numbering", start=1, padding=3, position="prefix"),
            ]
        )
        session.save_preset("Photo tidy-up")

    capture("04-tools", page="tools", prepare=prepare_tools)

    # --- history -------------------------------------------------------
    capture("05-history", page="history")

    # --- settings ------------------------------------------------------
    capture("06-settings", page="settings")

    # --- light theme ---------------------------------------------------
    from ezrename.gui import theme as theme_module

    def prepare_light() -> None:
        settings.theme = "light"
        settings.accent = "teal"
        theme_module.apply_theme(app, "light", "teal")
        window.apply_theme_change()

    capture("07-light-theme", page="workspace", prepare=prepare_light)

    # --- back to dark for a final shot with a populated file list ------
    def prepare_documents() -> None:
        settings.theme = "dark"
        settings.accent = "blue"
        theme_module.apply_theme(app, "dark", "blue")
        window.apply_theme_change()
        session.add_folder(root / "documents", recursive=False)
        session.set_operations(
            [
                new_operation("separators", spaces_to="_"),
                new_operation("extension", case="lower"),
                new_operation("date", format="%Y-%m-%d", position="prefix"),
            ]
        )

    capture("08-documents", page="workspace", prepare=prepare_documents)

    window.close()
    session.close()

    print("Screenshots written to", output)
    for line in results:
        print(line)
    if not args.keep_demo and not os.environ.get("EZRENAME_DEMO_DIR"):
        shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)
    return 0 if all(" ok " in line for line in results) else 1


if __name__ == "__main__":
    sys.exit(main())
