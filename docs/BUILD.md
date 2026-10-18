# Building, testing and releasing EzRename

## Requirements

| Tool | Version | Why |
|---|---|---|
| Python | 3.9 or newer (developed and tested on 3.14.7) | runtime |
| pip | current | dependency installation |
| Inno Setup / NSIS | optional | only if you want a real installer; the release folder works on its own |

Windows is the supported build target because the packaged executables, the icon
resource and the dark title bar integration are Windows-specific. The source and
the CLI run on Linux and macOS as well.

## Development setup

```bash
git clone https://github.com/kritagyadubey/EzRename.git
cd EzRename
python -m venv .venv
.venv\Scripts\activate                 # Windows
source .venv/bin/activate              # Linux / macOS
python -m pip install -r requirements-dev.txt
python -m pip install -e .             # installs the package itself (it lives under src/)
```

`requirements.txt` holds the runtime dependency (PySide6); the CLI, the engine
and the history database need nothing beyond the standard library.
`requirements-dev.txt` adds pytest and PyInstaller. `pip install -e .` is what
makes `ezrename` importable — the package lives under `src/`, so without it
`python -m ezrename` raises `ModuleNotFoundError`.

## Running the source version

```bash
python -m ezrename                    # graphical application
python -m ezrename.gui.app            # same thing, explicit module
python -m ezrename.cli.main --help    # command line interface
python -m ezrename.cli.main list .    # quick smoke check
```

Or install the package so the console scripts are on `PATH`:

```bash
python -m pip install -e .
ezrename --help
ezrename-gui
```

### Redirecting settings and history

Point `EZRENAME_HOME` at any folder to keep tests, demos and portable copies away
from your real settings:

```bash
set EZRENAME_HOME=%TEMP%\ezrename-dev
ezrename config --show
```

## Running the tests

```bash
python -m pytest                       # everything
python -m pytest tests/test_engine.py -v
python -m pytest -k "undo or rollback" # focused runs
python -m pyflakes src tests tools     # static check (pyflakes is optional)
```

The suite uses only temporary folders and an isolated `EZRENAME_HOME`, so it
never touches real files, real settings or real history.

| Suite | Focus |
|---|---|
| `tests/test_operations.py` | Individual operations, validation, templates, numbering styles, name composition |
| `tests/test_pipeline.py` | Plan building, conflict detection, invalid names, unicode, sizing |
| `tests/test_engine.py` | Dry runs, swaps, cycles, quarantine, rollback, batch rollback, cancellation |
| `tests/test_history.py` | Persistence, verification, undo variants, export, pruning |
| `tests/test_discovery.py` | Scanning, filters, sorting, settings round-trip |
| `tests/test_cli.py` | Commands, exit codes, JSON, confirmation rules, config files |
| `tests/test_gui.py` | The real window offscreen: navigation, preview, apply, undo, presets, settings |

## Building the executables

```bash
python tools/build.py              # build + smoke-test both executables
python tools/build.py --no-test    # build only
python tools/build.py --only-test  # test an existing build
```

The build:

1. regenerates `assets/ezrename.ico` from the vector mark
   (`tools/make_icons.py`),
2. runs PyInstaller against [`packaging/ezrename.spec`](../packaging/ezrename.spec)
   with `--noconfirm --clean`,
3. verifies both outputs exist and prints their sizes,
4. runs a smoke test on the packaged binaries: `--version`, `--help`, `list`,
   `preview --json`, `--dry-run`, a real rename, `history`, `undo`, invalid
   arguments, the GUI `--self-test`, and a normal GUI launch that must stay
   alive for six seconds.

Each executable gets its own onedir bundle:

```
dist/EzRename/EzRename.exe             # windowed, no console
dist/ezrename-cli/ezrename-cli.exe     # console, accepts arguments
```

Both bundles are self-contained: copy the folder anywhere and run the `.exe`
inside it. Roughly 126 MB per bundle, most of which is the Qt runtime; the
spec excludes the Qt modules EzRename never imports (WebEngine, Quick, Qml, 3D,
Multimedia, Sql, Test, Designer, Help, Multimedia, …) to keep it that small.

### Reproducing the icon and screenshots

```bash
python tools/make_icons.py         # assets/ezrename.ico + assets/ezrename-logo.png
python tools/make_screenshots.py   # assets/screenshots/*.png (drives the real window)
```

`make_screenshots.py` creates a demo folder (in `Pictures` when available),
runs three real rename sessions so the dashboard and history have data, captures
every page, verifies that the capture is not blank and that the expected theme
colours are present, then removes the demo folder again. Set
`EZRENAME_DEMO_DIR` to control where it works, or pass `--keep-demo`.

## Shipping a release

1. `python tools/build.py`
2. Zip the two folders so each archive contains one top-level folder that also
   carries a `README.txt` and the `LICENSE` (this is exactly what the GitHub
   release ships):
   ```
   dist/EzRename/      -> EzRename-1.0.0-win64-gui.zip
   dist/ezrename-cli/  -> EzRename-1.0.0-win64-cli.zip
   ```
3. Tag the version and attach the archives to the GitHub release:
   ```bash
   git tag -a v1.0.0 -m "EzRename 1.0.0"
   git push origin main --tags
   gh release create v1.0.0 dist/EzRename-1.0.0-win64-gui.zip dist/EzRename-1.0.0-win64-cli.zip \
     --title "EzRename 1.0.0" --notes-file build/release-notes.md
   ```
   Include the SHA-256 of each archive in the release notes so users can
   verify what they downloaded (`certutil -hashfile <file> SHA256`).
4. Update `CHANGELOG.md` and the version in `pyproject.toml` /
   `src/ezrename/__init__.py` for the next release.

Nothing in the build depends on the developer machine: no absolute paths are
embedded (the spec uses `SPECPATH`), settings and history live in the user
profile, and PyInstaller's `runtime_tmpdir` and temporary icon files are handled
by the bootloader.

## Project conventions

- Layer boundaries are strict: `ezrename.core` must never import Qt, and
  `ezrename.gui` must never reimplement renaming logic. Both interfaces call the
  same `build_plan()` and `RenameEngine`.
- Operations are dataclasses with a `type` class attribute; the GUI builds their
  editors from the dataclass fields, so a new operation needs no UI code.
- Every user-visible string is plain English, no jargon: "the file is locked,
  read-only or owned by another process" rather than an `errno` dump.
- Tests are written against disposable folders only; destructive tests against
  real user folders are never acceptable.
