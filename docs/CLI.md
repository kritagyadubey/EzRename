# EzRename CLI reference

`ezrename` is a first-class interface, not a wrapper around the GUI: it imports
no Qt code, works over a pipe, and returns meaningful exit codes. The packaged
build is `ezrename-cli.exe`; from a source checkout use
`python -m ezrename.cli.main`.

```
ezrename [--version] [--home DIR] COMMAND [options]
```

| Command | Purpose |
|---|---|
| `list PATH` | List the files a command would work on (after filters and sorting). |
| `preview PATH [operations]` | Build and print a plan. Nothing is modified. |
| `rename PATH [operations]` | Apply a rename, with the same validation as the preview. |
| `undo [SESSION] [--last]` | Verify and restore a previous session. |
| `history [--session ID]` | Show stored sessions, optionally with per-file detail and an export. |
| `export SESSION --output FILE` | Write a JSON or CSV manifest for auditing. |
| `ops` | List the operations, their options and the template variables. |
| `config [--show] [--path]` | Show where settings and history live. |
| `gui [PATH]` | Launch the desktop application (requires PySide6). |

`--home DIR` (global, or per command) redirects settings and history to another
folder, which makes portable installs and scripted tests easy. The environment
variable `EZRENAME_HOME` does the same.

## Exit codes

| Code | Meaning |
|-----:|---------|
| 0 | Success: every planned rename succeeded, or an informational command ran. |
| 1 | At least one file failed (or a history/undo step failed). |
| 2 | Usage error: unknown option, missing folder, invalid regex, not confirmed. |
| 3 | Blocked by conflicts, duplicate targets or invalid names — nothing changed. |
| 4 | Nothing to do: no file matched, or nothing would change. |

## File selection options

These are available on `list`, `preview` and `rename`:

| Option | Description |
|---|---|
| `PATH` | Folder (or single file). Defaults to the current folder. |
| `-r`, `--recursive` | Include files in subfolders. |
| `--hidden` | Include hidden files. |
| `--follow-symlinks` | Follow symbolic links (off by default). |
| `--ext jpg,png` | Only these extensions. |
| `--glob "IMG_*"` | Only names matching this glob. |
| `--exclude "*copy*"` | Skip names matching this glob (repeatable). |
| `--contains TEXT` | Only names containing this text. |
| `--min-size BYTES`, `--max-size BYTES` | Size filters. |
| `--limit N` | Stop after N files. |
| `--sort {name,name_ci,extension,size,modified,created,path,added}` | Order used for numbering (default `name`, natural order). |
| `--reverse` | Reverse the sort order. |

## Rename operations

Every flag below enables one operation. They are combined into a pipeline in a
fixed, documented order:

```
find/replace → insert/remove text → cleanup → case → date → prefix/suffix → template → numbering → extension
```

| Flag | Notes |
|---|---|
| `--find TEXT` | Text to search for. |
| `--replace TEXT` | Replacement (default empty, i.e. delete the match). |
| `--regex` | Treat `--find` as a regular expression; `\1`, `\2` work in the replacement. |
| `--ignore-case` | Case-insensitive matching. |
| `--first-only` | Replace only the first match. |
| `--scope {stem,ext,both,full}` | Where find/replace applies (default `stem`). `full` includes the dot, so it can join or split name parts. |
| `--prefix TEXT`, `--suffix TEXT` | Add text. |
| `--suffix-after-ext` | Place the suffix after the extension (`photo.jpg` → `photo.jpg_backup`). |
| `--remove-prefix TEXT`, `--remove-suffix TEXT` | Strip text only when present. |
| `--prefix-ignore-case` | Case-insensitive prefix/suffix removal. |
| `--number` | Enable sequential numbering. |
| `--start N`, `--step N`, `--padding N` | Numbering values (defaults 1, 1, 3). |
| `--number-position {prefix,suffix,replace}` | Where the number goes (default `prefix`). |
| `--number-style {decimal,alpha_lower,alpha_upper,roman_lower,roman_upper}` | Numbering style. |
| `--number-separator TEXT` | Separator between number and name (default `_`). |
| `--number-prefix/--number-suffix TEXT` | Text printed around the number itself. |
| `--case {upper,lower,title,sentence}` | Case conversion. |
| `--case-scope {stem,ext,both}` | What the case conversion applies to. |
| `--replace-spaces CHAR` | Replace spaces with one character (e.g. `_`). |
| `--collapse-separators` | Collapse repeated separators. |
| `--dedupe-words` | Remove consecutive duplicate words. |
| `--strip-chars CHARS` | Remove every listed character. |
| `--replace-char FROM=TO` | Replace one character with another (repeatable). |
| `--no-trim` | Do not trim outer whitespace. |
| `--ext-change EXT` | Set a new extension (renames only, no conversion). |
| `--ext-case {lower,upper}` | Change only the extension's case. |
| `--remove-ext` | Remove the extension. |
| `--ext-only jpg,png` | Restrict the extension operation to these extensions. |
| `--template PATTERN` | Name pattern, e.g. `"{index:02d} - {stem}{ext}"`. |
| `--insert-date` | Insert a timestamp into the name. |
| `--date-format FMT`, `--time-format FMT` | `strftime` patterns (defaults `%Y-%m-%d`, `%H-%M-%S`). |
| `--date-source {mtime,ctime,atime}`, `--date-position {prefix,suffix}`, `--date-separator`, `--date-fallback {empty,original,error}` | Date behaviour. |
| `--insert-text TEXT`, `--insert-position {start,end,index}`, `--insert-index N` | Insert text. |
| `--remove-text TEXT`, `--remove-text-position {start,end,anywhere,first,last}`, `--remove-text-limit N`, `--remove-text-ignore-case` | Remove text. |
| `--config FILE` | Load the whole sequence from JSON (cannot be combined with the flags above). |
| `--template-variables` | Print the available template variables and exit. |

`--config` accepts either a bare list of operations or an object with an
`operations` key:

```json
{
  "operations": [
    {"type": "find_replace", "find": "IMG_", "replace": "Holiday_", "case_sensitive": true},
    {"type": "numbering", "start": 1, "step": 1, "padding": 3, "position": "prefix"},
    {"type": "extension", "case": "lower"}
  ]
}
```

Operation `type` values and every option are listed by `ezrename ops --json`.

## Applying a rename

```bash
ezrename rename ./photos --find IMG_ --replace Photo_ --yes
```

- Without `--yes`, EzRename prints the preview and asks for confirmation when it
  runs in a terminal. When the output is not a terminal (a pipe, a scheduled
  task), it refuses with exit code 2 rather than hanging — pass `--yes` (or set
  `EZRENAME_ASSUME_YES=1`).
- `-n`, `--dry-run` prints exactly what would happen and changes nothing.
- `--overwrite` allows replacing an existing destination; the existing file is
  moved to a `.ezrename-backup.<token>-<name>` file and reported, never deleted.
- `--strict` turns "some files were skipped or unchanged" into exit code 3.

## History, undo and manifests

```bash
ezrename history --limit 10                 # newest first
ezrename history --session 20261015-101500-ab12cd
ezrename history --session <id> --export session.json --format json
ezrename undo --last --dry-run              # verify only
ezrename undo --last --yes                  # restore
ezrename undo <id> --allow-partial --yes    # restore only the safe files
ezrename export <id> --output manifest.csv --format csv
```

`undo` re-verifies the filesystem first. If nothing can be restored it changes
nothing and exits 3 with the reason; if only some files can be restored it
refuses unless `--allow-partial` is given. A successful undo is recorded as its
own session, and the original session is marked as undone.

## Output formats

`--json` prints a machine-readable payload instead of tables. `preview --json`
returns the plan (`summary`, `operations`, `notes`, `entries`), and
`rename --json` returns the execution report (`summary`, `entries` with
`status`, `message` and `backup`). When a rename is blocked, the JSON payload
has `"applied": false` and the `exit_code` it returned.

Other output controls: `-q`/`--quiet` (errors and results only), `-v`/`--verbose`
(per-file detail including skipped entries), `--no-color` (also honouring the
`NO_COLOR` environment variable), `--max-rows N` and `--no-limit` for large
previews.

## Automation examples

```bash
# Rename camera files in a scheduled task, logging a manifest for auditing
ezrename rename "D:\Photos\Inbox" --find IMG_ --replace Photo_ --yes --json \
  > "D:\Photos\last-run.json"

# Fail a CI step when a folder is not already tidy
ezrename preview ./assets --case lower --dry-run --json \
  | python -c "import json,sys; sys.exit(0 if json.load(sys.stdin)['summary']['rename']==0 else 3)"

# Undo the newest session from a script when the files are unchanged
ezrename undo --last --yes --no-color
```
