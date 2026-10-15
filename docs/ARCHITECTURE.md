# EzRename architecture

EzRename is three layers over one engine. The rule that keeps the two interfaces
honest is simple: **nothing in `ezrename.gui` or `ezrename.cli` may implement
renaming logic.** They both build a plan with `ezrename.core.pipeline` and hand
it to `ezrename.core.engine`.

```
                    ┌──────────────────────────┐
                    │        ezrename.gui      │  PySide6 desktop app
                    │  pages / widgets / theme │
                    └────────────┬─────────────┘
                                 │  Session (state + signals)
                    ┌────────────▼─────────────┐
                    │        ezrename.cli      │  argparse + terminal render
                    └────────────┬─────────────┘
                                 │
        ┌────────────────────────▼─────────────────────────┐
        │                 ezrename.core                    │
        │  discovery → operations → pipeline → engine       │
        │  history (SQLite) · settings · naming rules       │
        └──────────────────────────────────────────────────┘
```

`ezrename.core` has no third-party imports at all, which is why
`ezrename-cli.exe` runs without Qt and why the engine can be tested without a
display.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `core/naming.py` | Windows filename rules (illegal characters, reserved names, trailing dot/space, length), case-folding policy, hidden-file detection, intermediate/backup name generation, natural sort keys. |
| `core/models.py` | `FileRecord`, `PlanEntry`, `RenamePlan`, `EntryOutcome`, `ExecutionResult` and the status enum shared by everything. |
| `core/operations.py` | The rename operations. Each is a dataclass with a `type`, `validate()`, `apply(NameContext)`, `summary()` and `to_dict()`, plus the registry and the documented CLI ordering. |
| `core/pipeline.py` | Turns files + operations into a validated plan (`build_plan`) or explicit targets into a plan (`plan_from_targets`, used by undo). All conflict and validity checks live here. |
| `core/engine.py` | Executes a plan. Two-phase renames, quarantine backups, per-file rollback, batch rollback, dry runs, progress and cancellation. Never deletes anything. |
| `core/discovery.py` | Folder scanning, recursion, hidden/symlink policy, extension/glob/size/text filters, sorting. |
| `core/history.py` | SQLite schema, session recording, undo verification, undo execution (through the engine), manifest export, pruning. |
| `core/settings.py` | User settings in a writable per-user location, atomic writes, `EZRENAME_HOME` override. |
| `cli/main.py` | Argument parsing, command dispatch, exit codes, confirmation policy. |
| `cli/render.py` | Tables, colours, symbols and JSON output for the terminal. |
| `gui/session.py` | Observable application state: loaded files, operation stack, live plan, settings, history handle. |
| `gui/theme.py` | Design tokens (palette, accents, radii, spacing, type scale) and the single stylesheet built from them. |
| `gui/icons.py` | Vector icons and the logo, rendered at runtime with `QSvgRenderer` — no binary icon set to keep in sync. |
| `gui/widgets.py`, `gui/filetable.py`, `gui/opeditor.py` | Reusable interface pieces: cards, badges, drop area, toasts, the diff-highlighting file table, and the operation editors generated from the operation dataclasses. |
| `gui/pages/*` | The five pages, each a plain widget that reads from the session and reacts to its signals. |
| `gui/workers.py` | `QThread` workers for scanning, executing and undoing, with progress and cancellation. |
| `gui/main_window.py` | Sidebar navigation, page stack, shortcuts, drag and drop, toasts and status bar. |

## Data flow of one rename

1. `discovery.scan_directory()` (or `collect_records()` for drag and drop)
   produces `FileRecord` objects.
2. The operation sequence (built by CLI flags, the tools page or a JSON config)
   is validated with `validate_operations()`.
3. `pipeline.build_plan()` applies every operation to every file through a
   `NameContext`, validates each result, detects duplicates and destination
   conflicts, and returns a `RenamePlan` with per-entry statuses.
4. Interfaces render the plan: the GUI table and summary bar, the CLI table or
   JSON payload. Nothing has touched the filesystem yet.
5. `engine.RenameEngine.execute()` performs the renames (or simulates them in a
   dry run) and returns an `ExecutionResult` with one outcome per file.
6. `history.HistoryStore.record()` stores the session; `undo()` can later verify
   and reverse it using the same engine.

## Adding a new rename operation

1. Add a dataclass in `core/operations.py` with a unique `type`, the field
   defaults, `validate()`, `apply(ctx)` and a human-readable `summary()`.
2. Register it in `OPERATION_CLASSES` and, if the CLI should expose it, add its
   flag and a stage in `CLI_OPERATION_ORDER`.
3. Optionally add UI hints in `gui/opeditor.py:FIELD_HINTS`; without hints the
   editor is generated from the field types.
4. Add tests: operation behaviour, validation errors, and a pipeline case.

Serialisation, presets, the plan JSON, the CLI config files and the operation
catalogue all follow automatically from the dataclass.

## Design system

`gui/theme.py` defines one `Palette` per theme and one `Tokens` object that
widgets and the stylesheet both read. The stylesheet is generated from those
tokens with property selectors (`QPushButton[variant="primary"]`,
`QLabel[badge="true"][tone="ok"]`), which is how a control changes appearance
without ad-hoc per-widget styling. The only raster files are the few 14px
check/chevron images the Qt stylesheet format requires for `::indicator` and
`::down-arrow`; they are generated from the same vector sprites at startup into
the temporary folder, so the repository stays free of binary assets.

Changing theme or accent re-applies the tokens and rebuilds the central widget
(`MainWindow.rebuild_ui`), which guarantees no widget keeps a stale colour while
the session (files, sequence, settings, history) survives untouched.

## Threading model

The GUI thread never performs filesystem work on more than a handful of files:

- `ScanWorker` reads a folder (and its subfolders) off the GUI thread.
- `ExecuteWorker` runs the engine with progress and a cancel flag.
- `UndoWorker` opens its **own** SQLite connection, because SQLite connections
  belong to the thread that created them; the GUI keeps its own connection for
  reads.

All results come back through Qt signals, so a large batch keeps the interface
responsive and cancellable.

## Error handling philosophy

- Configuration mistakes are caught before execution (`OperationError`), shown
  next to the offending field, and block the apply button.
- Per-file failures raise `FileOperationError` and mark just that entry.
- Filesystem failures are translated from `OSError`/`errno` into sentences that
  say what happened and what to do about it.
- Unexpected exceptions never leave the user without an explanation: the GUI
  installs an exception hook that reports the message, states that no files were
  changed, and offers the traceback in a details pane.
