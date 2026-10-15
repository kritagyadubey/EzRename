# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for EzRename.

Builds two independent executables from the same source tree:

``dist/EzRename/EzRename.exe``
    The graphical application. No console window is created.
``dist/ezrename-cli/ezrename-cli.exe``
    The command line tool, with a real console so pipes and exit codes work.

Both are onedir bundles: they start quickly, keep Qt's plugin layout intact and
work from a normal extracted folder without administrator rights. Run it with::

    python -m PyInstaller packaging/ezrename.spec --noconfirm --clean

or simply ``python tools/build.py``.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
ASSETS = ROOT / "assets"
ICON = ASSETS / "ezrename.ico"

#: Qt modules EzRename never imports. Dropping them keeps the build small
#: without affecting any feature the application offers.
EXCLUDED_QT = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtQmlModels",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtXml",
]

EXCLUDED_PYTHON = [
    "tkinter",
    "unittest",
    "pydoc_data",
    "lib2to3",
    "pytest",
    "numpy",
    "PIL",
    "selenium",
    "trio",
    "anyio",
    "httpx",
    "httpcore",
    "requests",
    "bs4",
    "openpyxl",
    "pypdf",
    "pygments",
    "pip",
    "setuptools",
]

HIDDEN_IMPORTS = ["ezrename.core", "ezrename.gui"]

COMMON_EXCLUDES = EXCLUDED_QT + EXCLUDED_PYTHON


def analysis(entry_script: str, *, console: bool) -> Analysis:
    """One analysis pass per executable (each gets its own clean bundle)."""

    return Analysis(
        [str(SRC / entry_script)],
        pathex=[str(SRC)],
        binaries=[],
        datas=[],
        hiddenimports=HIDDEN_IMPORTS,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=COMMON_EXCLUDES,
        noarchive=False,
        optimize=0,
    )


# --- graphical application -------------------------------------------------
gui_analysis = analysis("ezrename/gui/app_entry.py", console=False)
gui_pyz = PYZ(gui_analysis.pure)
gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="EzRename",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    version=str(ROOT / "packaging" / "version_info.txt"),
)
gui_collect = COLLECT(
    gui_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EzRename",
)

# --- command line tool -----------------------------------------------------
cli_analysis = analysis("ezrename/cli/entry.py", console=True)
cli_pyz = PYZ(cli_analysis.pure)
cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="ezrename-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    version=str(ROOT / "packaging" / "version_info.txt"),
)
cli_collect = COLLECT(
    cli_exe,
    cli_analysis.binaries,
    cli_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ezrename-cli",
)
