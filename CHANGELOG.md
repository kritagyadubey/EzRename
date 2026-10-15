# Changelog

All notable changes to EzRename are documented here.
This project follows [semantic versioning](https://semver.org/) and
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

## [1.0.0] — 2026-10-15

First public release. EzRename 1.0.0 ships both interfaces on one shared
renaming engine, with data safety as the primary design constraint.

### Added

**Renaming toolkit**

- Find and replace with literal or regular-expression matching, case
  sensitivity, "first occurrence only" and four scopes (name, extension, both,
  full name including the dot).
- Prefix and suffix operations that can add or strip text, before or after the
  extension, case sensitively or not.
- Sequential numbering with configurable start, step, zero padding, separator,
  placement (before, after, replace) and five styles (decimal, `a,b,c`,
  `A,B,C`, `i,ii,iii`, `I,II,III`).
- Case conversion (UPPER, lower, Title, Sentence) on the name, the extension or
  both.
- Separator and cleanup operation: spaces to any single character, collapsed
  repeated separators, duplicate word removal, whitespace trimming, character
  stripping and character replacement.
- Extension management: set, re-case, remove, or restrict to a list of
  extensions, with an explicit warning that no format conversion happens.
- Date and time insertion from the modified, created or accessed timestamp with
  any `strftime` pattern and a configurable fallback when metadata is missing.
- Template operation with 14 documented variables and format-specifier support
  (`{index:03d}`), validated before use.
- Insert/remove text operation with position control and occurrence limits.
- Ordered operation sequences, saved as presets in the GUI and loadable from
  JSON with `--config` in the CLI.

**Safety and reliability**

- Side-effect free plan building: conflicts, duplicate targets, invalid names and
  skipped files are all detected before anything is renamed.
- Windows-aware validation (illegal characters, reserved device names, trailing
  dots/spaces, length limits) plus case-insensitive collision detection.
- Two-phase renames with unique intermediate names for swaps, rename cycles and
  case-only changes.
- Per-file rollback on failure and whole-batch rollback when a swap cannot be
  completed, always reporting the real resulting name of every file.
- Overwrite mode that quarantines the existing destination as a
  `.ezrename-backup.<token>-<name>` file instead of deleting it.
- Dry-run mode in the CLI and an always-safe preview in the GUI.
- Symbolic links skipped by default, hidden files opt-in, EzRename's own
  temporary files ignored by every scan.

**History and recovery**

- SQLite session history stored per user, surviving restarts.
- Undo that re-verifies the current filesystem state, explains why a file cannot
  be restored, and supports full, partial (`--allow-partial`) or refused undo.
- Manifest export per session as JSON or CSV, from both interfaces.
- Session records that can be deleted without touching any file.

**Graphical application (PySide6)**

- Dark and light themes, five accent colours, a single token-based design system
  and a native dark title bar on Windows.
- Dashboard with real counters (files loaded, pending renames, conflicts,
  renames in history) and recent sessions with one-click undo.
- Workspace with a filterable, sortable file table, highlighted character-level
  name diffing, per-row status, and a live preview summary.
- Rename tools page with the operation catalogue, per-step editors that show a
  live example, step reordering/duplication, presets and a template variable
  reference.
- History page with session detail, verification, undo, export and record
  deletion.
- Settings page for theme, accent, selection defaults, numbering defaults,
  confirmation preferences, history retention and storage locations.
- Drag and drop anywhere in the window, native folder/file pickers, an empty
  state, toasts, a cancellable progress panel and a detailed completion report.
- Background threads for scanning, renaming and undo, so the interface stays
  responsive; high-DPI aware and resizable down to 1040×680.

**Command line interface**

- Commands: `list`, `preview`, `rename`, `undo`, `history`, `export`, `ops`,
  `config` and `gui`.
- Documented exit codes (0 success, 1 failures, 2 usage, 3 blocked, 4 nothing to
  do), JSON output for automation, quiet/verbose modes and `NO_COLOR` support.
- Paths with spaces and unicode, filters (extension, glob, text, size,
  recursion, hidden files), sorting that drives numbering, and confirmation
  rules that never hang a script.

**Packaging and documentation**

- PyInstaller spec producing `EzRename.exe` (windowed) and `ezrename-cli.exe`
  (console) as reproducible onedir bundles with icons and version resources.
- `tools/build.py` which builds and then smoke-tests both packaged executables
  from their final `dist` locations.
- MIT licence, README with real screenshots, CLI reference, safety model,
  architecture notes and build guide.
- 260 automated tests plus one conditionally skipped test.

[1.0.0]: https://github.com/kritagyadubey/EzRename/releases/tag/v1.0.0
