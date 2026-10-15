# Data safety in EzRename

Renaming files is easy; renaming thousands of files without losing one is not.
This document describes exactly what EzRename guarantees, in the order the
guarantees are applied.

## 1. Planning never touches the filesystem

`build_plan()` is the only place that decides what would happen, and it is a
pure function over the selected file records plus the operation sequence. The
GUI preview, `ezrename preview`, `ezrename rename --dry-run` and the undo
planner all call it. A plan contains, per file:

- the original name and the proposed name,
- a status (`ready`, `unchanged`, `skipped`, `duplicate`, `exists`, `invalid`,
  `error`),
- the reason for any status other than `ready`,
- warnings such as "the destination is currently used by another file that this
  session renames as well".

Reading the plan has no side effects: no rename, no move, no delete, and no
temporary file.

## 2. Nothing is renamed when anything is blocked

A plan is applicable only when it has no blocking entries. Blocking happens when:

| Situation | Status | What you see |
|---|---|---|
| Two files would end up with the same name (case-insensitively on Windows) | `duplicate` | Both rows turn red and name the other file. |
| A file that is *not* part of the batch already uses the target name | `exists` | The message names the existing file. |
| The result is not a legal Windows name | `invalid` | Empty, too long, illegal characters, reserved device name (`CON`, `NUL`, `LPT1`, …), trailing dot or space, or "only whitespace". |
| An operation failed for that file (for example a missing timestamp with `--date-fallback error`) | `error` | The reason is shown per file. |
| The file was skipped by an operation (`fallback: original`, internal temp file) | `skipped` | The row explains why. |

The apply button in the GUI stays disabled and the CLI exits with code 3. A
target name that is currently used by another file *of the batch* is not a
conflict — the executor resolves it with an intermediate name.

## 3. Dry runs really do nothing

`dry_run` short-circuits the executor before any filesystem call: it emits one
`planned` outcome per file and returns. In a dry run the report shows zero
renamed files and `changed_filesystem` is false, so no tooling can mistake a
simulation for a result.

## 4. Two-phase renames for swaps, cycles and case-only changes

A naive rename loop destroys data on `a.txt ⇄ b.txt`: the second move would
overwrite the first. EzRename therefore first moves every file whose target name
is currently owned by *another file in the batch* — plus case-only changes on a
case-insensitive filesystem — to a unique intermediate name
(`.ezrename-tmp.<token>-<name>`), and only then renames everything to its final
name. Intermediate names are generated with a random token, checked for
existence, and kept inside the file's own folder.

Files matching the `.ezrename-tmp.` or `.ezrename-backup.` prefixes are ignored
by every scan, so an interrupted session cannot be re-processed accidentally.

## 5. Failure handling: per file, then per batch

If a rename fails — the file is locked by another program, read-only, on a
full disk, or the name is rejected by the filesystem — EzRename:

1. reports the failure with the operating system's reason translated into plain
   language ("the file is locked, read-only or owned by another process"),
2. puts the file back under its original name when it had already been moved
   aside (status `rolled_back`),
3. and, if that file cannot be restored on its own because its original name is
   now occupied by a file this session created (a half-completed swap), rolls
   back the entire batch: every file the batch renamed is parked again and then
   every original name is restored. The folder returns to its pre-session state.

Anything that cannot be restored is listed in the report with the exact name it
is stored under (`rollback_failures`), so no file is ever left unaccounted for.
Cancellation follows the same path: files not yet renamed are reported as
skipped, and parked files are put back before the report is shown.

## 6. Overwriting is opt-in and never destructive

By default an existing destination blocks the operation. If you explicitly ask
to replace it (`--overwrite`, or confirming the warning in the GUI), the
existing file is **moved** to `.ezrename-backup.<token>-<name>` next to it
before the rename, and the backup path is recorded in the report and in the
history. Undo restores both the renamed file and the backup. No file is ever
deleted to make a rename succeed.

## 7. Filesystem edge cases handled explicitly

- **Case-insensitive collisions.** On Windows and macOS, `Report.txt` and
  `report.txt` are the same file; collision detection uses a case-folded key so
  the preview cannot promise two files the same name.
- **Case-only renames.** `photo.jpg` → `PHOTO.jpg` is performed through an
  intermediate name, which works reliably on NTFS.
- **Unicode and spaces.** Names are handled as text throughout, output is
  written as UTF-8 (the console is reconfigured if needed), and no locale
  assumptions are made.
- **Multiple dots and missing extensions.** `archive.tar.gz` keeps
  `archive.tar` as its stem; `README` is a name without extension; `.gitignore`
  is treated as a name, not as an extension.
- **Symbolic links.** Skipped by default (never renamed through the link) and
  only followed when `--follow-symlinks` / the settings toggle is used.
- **Hidden files.** Excluded unless requested.
- **Directories.** Only regular files are ever selected as rename targets.
- **Read-only and locked files.** The failure is reported per file and rolled
  back; the rest of the batch is unaffected.
- **Long paths.** Targets that would exceed the legacy 260-character limit get
  an explicit note in the plan instead of a silent failure.

## 8. History and undo

Every executed session (including a failed or cancelled one) is written to
`history.db` next to your settings, with one row per file: original path, target
path, original name, target name, status, message, backup path, size and
modification time.

Undo is a two-step operation:

1. **Verification.** For every file the session renamed, EzRename checks that
   the file is still at the path the rename left it at, that restoring the
   original name would not overwrite an unrelated file, and that the session was
   not already undone. Missing files, occupied original names and files that no
   longer match their recorded size/modification time are reported with reasons;
   a file that merely changed content is flagged as a warning, because renaming
   does not depend on content.
2. **Restoration.** The undo then runs through the *same* engine, so it inherits
   two-phase moves, per-file rollback and honest reporting. It is recorded as
   its own session and the original session is marked as undone.

If nothing can be restored, nothing is changed and you get the reasons. If only
some files can be restored, EzRename refuses by default and offers a partial
restore (`--allow-partial`, or "Restore the safe file(s)" in the undo dialog).

Manifests (`--export`, or *Export manifest* in the GUI) contain the full session
record as JSON or CSV for auditing and manual recovery.

## 9. Where EzRename stores things

| What | Location |
|---|---|
| Settings | `%APPDATA%\EzRename\settings.json` |
| History | `%LOCALAPPDATA%\EzRename\history.db` |
| Linux/macOS equivalents | `~/.config/ezrename`, `~/.local/share/ezrename` |
| Override for tests or portable installs | `EZRENAME_HOME` |

Nothing is written next to the executable, so a copy in `C:\Program Files` works
for standard users, and no credentials, tokens or personal data are stored.

## 10. What EzRename deliberately does not do

- It never deletes files, including "duplicates" or backups.
- It never moves files between folders.
- It never converts file formats, even when the extension changes.
- It never claims a rename succeeded unless the rename call returned success and
  the file is at its target name.
- It never hides a failure: any file that ended up somewhere unexpected is named
  in the report.
