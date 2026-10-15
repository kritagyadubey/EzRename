"""EzRename command line interface.

Exit codes (also documented in ``--help`` and the README):

====  ==========================================================================
0     every planned rename succeeded (or a preview/list/info command ran fine)
1     at least one file failed or could not be rolled back
2     usage error: unknown option, missing folder, conflicting arguments
3     the operation was blocked by conflicts/invalid names - nothing was changed
4     nothing to do: no files matched, or the operations change nothing
====  ==========================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .. import APP_NAME, __version__
from ..core.discovery import (
    SORT_KEYS,
    ScanResult,
    collect_records,
    filter_records,
    scan_directory,
    sort_records,
)
from ..core.engine import RenameEngine
from ..core.history import HistoryStore
from ..core.models import EntryStatus
from ..core.operations import (
    CLI_OPERATION_ORDER,
    OPERATION_CATALOGUE,
    Operation,
    OperationError,
    TEMPLATE_VARIABLES,
    new_operation,
    operation_from_dict,
    validate_operations,
)
from ..core.pipeline import PlanOptions, build_plan
from ..core.settings import AppSettings, config_dir, data_dir
from . import render
from .render import Console

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_BLOCKED = 3
EXIT_NOTHING = 4

PROGRAM = "ezrename"

DESCRIPTION = """\
EzRename - safe, previewable bulk file renaming from the terminal.

Every command builds the same validated plan the GUI shows: conflicts,
duplicate targets and invalid names are detected before anything is renamed,
and an existing file is never overwritten unless you ask for it.
"""

EPILOG = """\
examples:
  ezrename list ./photos                                  which files would be touched
  ezrename preview ./photos --prefix "Vacation_"           see the result first
  ezrename rename ./photos --find "IMG_" --replace "Photo_"
  ezrename rename ./photos --number --start 1 --padding 3 --yes
  ezrename rename ./documents --case lower --dry-run
  ezrename rename ./photos --replace-spaces "_" --yes
  ezrename rename ./scans --date-format "%Y-%m-%d" --insert-date --yes
  ezrename rename ./music --template "{index:02d} - {stem}{ext}" --yes
  ezrename rename ./photos --config ops.json --yes
  ezrename history --limit 10
  ezrename undo --last --dry-run
  ezrename undo 20261015-101500-ab12cd --allow-partial --yes
  ezrename export 20261015-101500-ab12cd --output manifest.json

exit codes: 0 success, 1 failures, 2 usage error, 3 blocked by conflicts, 4 nothing to do
"""


# --------------------------------------------------------------------------- #
# Operation flags
# --------------------------------------------------------------------------- #


def _add_operation_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("rename operations", "combine as many as you need")
    group.add_argument("--find", metavar="TEXT", help="text to search for")
    group.add_argument("--replace", metavar="TEXT", default=None, help="replacement text (default: empty)")
    group.add_argument("--regex", action="store_true", help="treat --find as a regular expression")
    group.add_argument("--ignore-case", action="store_true", help="case-insensitive matching")
    group.add_argument("--first-only", action="store_true", help="replace only the first match")
    group.add_argument(
        "--scope",
        choices=("stem", "ext", "both", "full"),
        default="stem",
        help="where --find/--replace applies (default: stem, i.e. the name without extension)",
    )

    group.add_argument("--prefix", metavar="TEXT", help="add this prefix")
    group.add_argument("--suffix", metavar="TEXT", help="add this suffix")
    group.add_argument(
        "--suffix-after-ext",
        action="store_true",
        help="place --suffix after the extension instead of before it",
    )
    group.add_argument("--remove-prefix", metavar="TEXT", help="strip this prefix if present")
    group.add_argument("--remove-suffix", metavar="TEXT", help="strip this suffix if present")
    group.add_argument(
        "--prefix-ignore-case",
        action="store_true",
        help="match prefixes/suffixes case-insensitively",
    )

    group.add_argument("--number", action="store_true", help="enable sequential numbering")
    group.add_argument("--start", type=int, default=1, help="first number (default: 1)")
    group.add_argument("--step", type=int, default=1, help="increment between files (default: 1)")
    group.add_argument("--padding", type=int, default=3, help="zero-padding width (default: 3)")
    group.add_argument(
        "--number-position",
        choices=("prefix", "suffix", "replace"),
        default="prefix",
        help="where the number goes (default: prefix)",
    )
    group.add_argument(
        "--number-style",
        choices=("decimal", "alpha_lower", "alpha_upper", "roman_lower", "roman_upper"),
        default="decimal",
        help="numbering style (default: decimal)",
    )
    group.add_argument("--number-separator", default="_", help="separator around the number (default: _)")
    group.add_argument("--number-prefix", default="", help="text printed before each number")
    group.add_argument("--number-suffix", default="", help="text printed after each number")

    group.add_argument(
        "--case",
        choices=("upper", "lower", "title", "sentence"),
        help="convert the name to this case",
    )
    group.add_argument(
        "--case-scope",
        choices=("stem", "ext", "both"),
        default="stem",
        help="what --case applies to (default: stem)",
    )

    group.add_argument("--replace-spaces", metavar="CHAR", help="replace spaces with this character")
    group.add_argument(
        "--collapse-separators", action="store_true", help="collapse repeated separators"
    )
    group.add_argument("--dedupe-words", action="store_true", help="remove consecutive duplicate words")
    group.add_argument("--strip-chars", metavar="CHARS", help="remove these characters")
    group.add_argument(
        "--replace-char",
        metavar="FROM=TO",
        action="append",
        default=None,
        help="replace one character with another (repeatable, e.g. --replace-char '&=_')",
    )
    group.add_argument("--no-trim", action="store_true", help="do not trim outer whitespace")

    group.add_argument("--ext-change", metavar="EXT", help="set a new extension (no format conversion)")
    group.add_argument(
        "--ext-case", choices=("lower", "upper"), help="change the case of the extension"
    )
    group.add_argument("--remove-ext", action="store_true", help="remove the extension")
    group.add_argument(
        "--ext-only",
        metavar="LIST",
        help="apply the extension operation only to these extensions (e.g. jpg,png)",
    )

    group.add_argument("--insert-date", action="store_true", help="insert a file timestamp into the name")
    group.add_argument(
        "--date-format", default="%Y-%m-%d", help="date format for date/template operations"
    )
    group.add_argument("--time-format", default="%H-%M-%S", help="time format for templates")
    group.add_argument(
        "--date-source", choices=("mtime", "ctime", "atime"), default="mtime", help="which timestamp to use"
    )
    group.add_argument(
        "--date-position", choices=("prefix", "suffix"), default="prefix", help="where to insert the date"
    )
    group.add_argument("--date-separator", default="_", help="separator around the date (default: _)")
    group.add_argument(
        "--date-fallback",
        choices=("empty", "original", "error"),
        default="empty",
        help="what to do when a timestamp is unavailable",
    )

    group.add_argument("--template", metavar="PATTERN", help="name pattern, e.g. '{index:02d} - {stem}{ext}'")

    group.add_argument("--insert-text", metavar="TEXT", help="insert text into the name")
    group.add_argument(
        "--insert-position", choices=("start", "end", "index"), default="start", help="where to insert"
    )
    group.add_argument("--insert-index", type=int, default=0, help="character position for --insert-position index")
    group.add_argument("--remove-text", metavar="TEXT", help="remove this text from names")
    group.add_argument(
        "--remove-text-position",
        choices=("start", "end", "anywhere", "first", "last"),
        default="anywhere",
        help="where to remove --remove-text from",
    )
    group.add_argument(
        "--remove-text-limit", type=int, default=1, help="occurrences to remove for first/last"
    )
    group.add_argument(
        "--remove-text-ignore-case", action="store_true", help="ignore case when removing text"
    )

    group.add_argument(
        "--config",
        metavar="FILE",
        help="load the operation sequence from a JSON file (cannot be combined with operation flags)",
    )
    group.add_argument(
        "--template-variables",
        action="store_true",
        help="list the variables available to --template and exit",
    )


def _add_selection_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("file selection")
    group.add_argument("-r", "--recursive", action="store_true", help="include files in subfolders")
    group.add_argument("--hidden", action="store_true", help="include hidden files")
    group.add_argument("--follow-symlinks", action="store_true", help="follow symbolic links")
    group.add_argument(
        "--ext",
        metavar="LIST",
        help="only include these extensions (comma separated, e.g. jpg,png)",
    )
    group.add_argument("--glob", metavar="PATTERN", help="only include names matching this glob")
    group.add_argument(
        "--exclude",
        metavar="PATTERN",
        action="append",
        default=None,
        help="skip names matching this glob (repeatable)",
    )
    group.add_argument("--contains", metavar="TEXT", help="only include names containing this text")
    group.add_argument("--min-size", type=int, metavar="BYTES", help="skip files smaller than this")
    group.add_argument("--max-size", type=int, metavar="BYTES", help="skip files larger than this")
    group.add_argument("--limit", type=int, metavar="N", help="stop after N files")
    group.add_argument(
        "--sort", choices=tuple(SORT_KEYS), default="name", help="order used for numbering (default: name)"
    )
    group.add_argument("--reverse", action="store_true", help="reverse the sort order")


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("output")
    group.add_argument("--json", action="store_true", help="machine readable JSON output")
    group.add_argument("-q", "--quiet", action="store_true", help="only print errors and results")
    group.add_argument("-v", "--verbose", action="store_true", help="print extra detail")
    group.add_argument("--no-color", action="store_true", help="disable coloured output")
    group.add_argument("--no-limit", action="store_true", help="print every row of a large preview")
    group.add_argument(
        "--max-rows", type=int, default=200, metavar="N", help="rows shown per table (default: 200)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--home",
        metavar="DIR",
        help="use this folder for settings and history instead of the default location",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # -- list ---------------------------------------------------------
    p_list = subparsers.add_parser(
        "list", help="list the files a command would work on", description="List matching files."
    )
    p_list.add_argument("path", nargs="?", default=".", help="folder or file (default: current folder)")
    _add_selection_flags(p_list)
    _add_output_flags(p_list)

    # -- preview ------------------------------------------------------
    p_preview = subparsers.add_parser(
        "preview",
        help="show what a rename would do without changing anything",
        description="Build and display a rename plan. Nothing is modified.",
    )
    p_preview.add_argument("path", nargs="?", default=".", help="folder or file (default: current folder)")
    _add_selection_flags(p_preview)
    _add_output_flags(p_preview)
    _add_operation_flags(p_preview)

    # -- rename -------------------------------------------------------
    p_rename = subparsers.add_parser(
        "rename",
        help="apply a rename to the selected files",
        description="Apply a rename. A preview is shown first and confirmation is required "
        "unless --yes is given.",
    )
    p_rename.add_argument("path", nargs="?", default=".", help="folder or file (default: current folder)")
    _add_selection_flags(p_rename)
    _add_output_flags(p_rename)
    _add_operation_flags(p_rename)
    p_rename.add_argument(
        "-n", "--dry-run", action="store_true", help="report what would happen, change nothing"
    )
    p_rename.add_argument(
        "-y", "--yes", action="store_true", help="do not ask for confirmation (needed when not a TTY)"
    )
    p_rename.add_argument(
        "--overwrite",
        action="store_true",
        help="allow replacing an existing destination (the existing file is kept under a "
        ".ezrename-backup name)",
    )
    p_rename.add_argument("--strict", action="store_true", help="exit 3 if any file is blocked")

    # -- history ------------------------------------------------------
    p_history = subparsers.add_parser(
        "history", help="show previous rename sessions", description="Show stored rename sessions."
    )
    p_history.add_argument("--session", metavar="ID", help="show the details of one session")
    p_history.add_argument("--limit", type=int, default=20, metavar="N", help="how many sessions (default: 20)")
    p_history.add_argument("--export", metavar="FILE", help="write the session to a JSON/CSV manifest")
    p_history.add_argument("--format", choices=("json", "csv"), default="json", help="manifest format")
    _add_output_flags(p_history)

    # -- undo ---------------------------------------------------------
    p_undo = subparsers.add_parser(
        "undo", help="restore the names of a previous session", description="Undo a stored rename session."
    )
    p_undo.add_argument("session", nargs="?", help="session id (default: the newest undoable session)")
    p_undo.add_argument("--last", action="store_true", help="undo the newest session")
    p_undo.add_argument("--list", action="store_true", help="list candidates instead of undoing")
    p_undo.add_argument("-n", "--dry-run", action="store_true", help="verify and report, change nothing")
    p_undo.add_argument(
        "--allow-partial",
        action="store_true",
        help="restore the files that can be restored and leave the rest untouched",
    )
    p_undo.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    _add_output_flags(p_undo)

    # -- export -------------------------------------------------------
    p_export = subparsers.add_parser(
        "export", help="write a session manifest for auditing", description="Export a session manifest."
    )
    p_export.add_argument("session", help="session id")
    p_export.add_argument("--output", "-o", metavar="FILE", help="target file (default: session-<id>.json)")
    p_export.add_argument("--format", choices=("json", "csv"), default="json", help="manifest format")
    _add_output_flags(p_export)

    # -- ops ----------------------------------------------------------
    p_ops = subparsers.add_parser(
        "ops",
        help="describe the available rename operations",
        description="List every rename operation and the template variables.",
    )
    _add_output_flags(p_ops)

    # -- config -------------------------------------------------------
    p_config = subparsers.add_parser(
        "config", help="show where settings and history live", description="Show EzRename configuration."
    )
    p_config.add_argument("--show", action="store_true", help="print the current settings as JSON")
    p_config.add_argument("--path", action="store_true", help="print the settings file path")
    _add_output_flags(p_config)

    # -- gui ----------------------------------------------------------
    p_gui = subparsers.add_parser(
        "gui", help="open the graphical application", description="Launch the EzRename desktop app."
    )
    p_gui.add_argument("path", nargs="?", help="folder to open in the workspace")
    p_gui.add_argument(
        "--check", action="store_true", help="report whether the GUI can start, then exit"
    )
    _add_output_flags(p_gui)

    return parser


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _console(args: argparse.Namespace) -> Console:
    return Console(
        colour=False if getattr(args, "no_color", False) else None,
        quiet=getattr(args, "quiet", False),
        verbose=getattr(args, "verbose", False),
    )


def _max_rows(args: argparse.Namespace) -> Optional[int]:
    if getattr(args, "no_limit", False):
        return None
    return getattr(args, "max_rows", 200)


def _split_list(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]


def _scan(args: argparse.Namespace, console: Console) -> tuple[ScanResult, Optional[int]]:
    """Collect the files selected by the command line filters."""

    raw = getattr(args, "path", ".") or "."
    target = Path(raw)
    if not target.exists():
        console.error(f"'{raw}' does not exist")
        return ScanResult(), EXIT_USAGE

    if target.is_file():
        # An explicit file is always used, even when it is hidden.
        single = collect_records(
            [target],
            include_hidden=True,
            follow_symlinks=getattr(args, "follow_symlinks", False),
        )
        result = single
        result.records = filter_records(
            result.records,
            extensions=_split_list(getattr(args, "ext", None)),
            glob=(_split_list(getattr(args, "glob", None)) or [""])[0],
        )
        needle = (getattr(args, "contains", "") or "").casefold()
        if needle:
            result.records = [
                record for record in result.records if needle in record.name.casefold()
            ]
        minimum = getattr(args, "min_size", None)
        maximum = getattr(args, "max_size", None)
        result.records = [
            record
            for record in result.records
            if (minimum is None or record.size >= minimum)
            and (maximum is None or record.size <= maximum)
        ]
        if not result.records:
            result.errors.append(f"'{raw}' was filtered out")
    else:
        result = scan_directory(
            target,
            recursive=getattr(args, "recursive", False),
            include_hidden=getattr(args, "hidden", False),
            follow_symlinks=getattr(args, "follow_symlinks", False),
            extensions=_split_list(getattr(args, "ext", None)),
            include_globs=_split_list(getattr(args, "glob", None)),
            exclude_globs=getattr(args, "exclude", None),
            name_contains=getattr(args, "contains", "") or "",
            min_size=getattr(args, "min_size", None),
            max_size=getattr(args, "max_size", None),
            max_files=getattr(args, "limit", None),
        )

    result.records = sort_records(
        result.records,
        getattr(args, "sort", "name"),
        reverse=getattr(args, "reverse", False),
    )
    for problem in result.errors:
        console.warn(problem)
    return result, None


def _operations_from_args(args: argparse.Namespace, console: Console) -> tuple[list[Operation], Optional[int]]:
    """Turn command line flags into an ordered operation pipeline."""

    config_path = getattr(args, "config", None)
    if config_path:
        if _has_operation_flags(args):
            console.error("--config cannot be combined with individual operation flags")
            return [], EXIT_USAGE
        try:
            payload = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
        except OSError as exc:
            console.error(f"cannot read '{config_path}': {exc.strerror or exc}")
            return [], EXIT_USAGE
        except ValueError as exc:
            console.error(f"'{config_path}' is not valid JSON: {exc}")
            return [], EXIT_USAGE
        if isinstance(payload, dict):
            payload = payload.get("operations", payload.get("ops", []))
        if not isinstance(payload, list):
            console.error("the config file must contain a list of operations")
            return [], EXIT_USAGE
        try:
            operations = [operation_from_dict(item) for item in payload]
        except OperationError as exc:
            console.error(str(exc))
            return [], EXIT_USAGE
        problems = validate_operations(operations)
        if problems:
            for problem in problems:
                console.error(problem)
            return [], EXIT_USAGE
        return operations, None

    built: dict[str, list[Operation]] = {}

    def add(stage: str, operation: Operation) -> None:
        built.setdefault(stage, []).append(operation)

    if getattr(args, "find", None):
        add("find_replace", new_operation(
            "find_replace",
            find=args.find,
            replace=args.replace if args.replace is not None else "",
            use_regex=bool(args.regex),
            case_sensitive=not bool(args.ignore_case),
            replace_all=not bool(args.first_only),
            scope=args.scope,
        ))

    if getattr(args, "remove_text", None):
        add(
            "text_edit",
            new_operation(
                "text_edit",
                mode="remove",
                text=args.remove_text,
                position=args.remove_text_position,
                case_sensitive=not bool(args.remove_text_ignore_case),
                limit=args.remove_text_limit,
            ),
        )
    if getattr(args, "insert_text", None):
        add(
            "text_edit",
            new_operation(
                "text_edit",
                mode="insert",
                text=args.insert_text,
                position=args.insert_position,
                index=args.insert_index,
            ),
        )

    spaces = getattr(args, "replace_spaces", None)
    replace_chars = getattr(args, "replace_char", None) or []
    if spaces or args.collapse_separators or args.dedupe_words or args.strip_chars or replace_chars or args.no_trim:
        replace_from = ""
        replace_to = ""
        for pair in replace_chars:
            if "=" not in pair:
                console.error(f"--replace-char expects FROM=TO, got '{pair}'")
                return [], EXIT_USAGE
            source, _, target = pair.partition("=")
            if len(source) != 1 or len(target) != 1:
                console.error("--replace-char works on single characters, e.g. --replace-char '&=x'")
                return [], EXIT_USAGE
            replace_from += source
            replace_to += target
        add(
            "separators",
            new_operation(
                "separators",
                spaces_to=spaces or "",
                collapse_repeats=bool(args.collapse_separators),
                trim_whitespace=not bool(args.no_trim),
                dedupe_words=bool(args.dedupe_words),
                strip_chars=args.strip_chars or "",
                replace_from=replace_from,
                replace_to=replace_to,
            ),
        )

    if getattr(args, "case", None):
        add("case", new_operation("case", mode=args.case, scope=args.case_scope))

    if getattr(args, "insert_date", False):
        add(
            "date",
            new_operation(
                "date",
                format=args.date_format,
                source=args.date_source,
                position=args.date_position,
                separator=args.date_separator,
                fallback=args.date_fallback,
            ),
        )

    if getattr(args, "prefix", None) or getattr(args, "suffix", None) or getattr(
        args, "remove_prefix", None
    ) or getattr(args, "remove_suffix", None):
        add(
            "prefix_suffix",
            new_operation(
                "prefix_suffix",
                prefix=args.prefix or "",
                suffix=args.suffix or "",
                suffix_after_extension=bool(args.suffix_after_ext),
                remove_prefix=args.remove_prefix or "",
                remove_suffix=args.remove_suffix or "",
                case_sensitive=not bool(args.prefix_ignore_case),
            ),
        )

    if getattr(args, "template", None):
        add(
            "template",
            new_operation(
                "template",
                pattern=args.template,
                date_format=args.date_format,
                time_format=args.time_format,
            ),
        )

    if getattr(args, "number", False):
        add(
            "numbering",
            new_operation(
                "numbering",
                start=args.start,
                step=args.step,
                padding=args.padding,
                separator=args.number_separator,
                position=args.number_position,
                style=args.number_style,
                prefix=args.number_prefix,
                suffix=args.number_suffix,
            ),
        )

    if getattr(args, "ext_change", None) or getattr(args, "ext_case", None) or getattr(
        args, "remove_ext", False
    ):
        add(
            "extension",
            new_operation(
                "extension",
                new_extension=args.ext_change or "",
                case=args.ext_case or "keep",
                remove=bool(args.remove_ext),
                only_when=args.ext_only or "",
            ),
        )

    operations: list[Operation] = []
    for type_name in CLI_OPERATION_ORDER:
        operations.extend(built.get(type_name, ()))
    for stage, stage_operations in built.items():
        if stage not in CLI_OPERATION_ORDER:
            operations.extend(stage_operations)

    if not operations:
        console.error("no rename operation was given - see 'ezrename rename --help'")
        return [], EXIT_USAGE

    problems = validate_operations(operations)
    if problems:
        for problem in problems:
            console.error(problem)
        return [], EXIT_USAGE
    return operations, None


def _has_operation_flags(args: argparse.Namespace) -> bool:
    names = (
        "find", "regex", "ignore_case", "first_only", "prefix", "suffix", "suffix_after_ext",
        "remove_prefix", "remove_suffix", "number", "case", "replace_spaces",
        "collapse_separators", "dedupe_words", "strip_chars", "replace_char", "ext_change",
        "ext_case", "remove_ext", "insert_date", "template", "insert_text", "remove_text",
    )
    for name in names:
        value = getattr(args, name, None)
        if value not in (None, False, [], ""):
            return True
    return False


def _plan(args: argparse.Namespace, console: Console):
    scan, failure = _scan(args, console)
    if failure is not None:
        return None, None, failure
    operations, failure = _operations_from_args(args, console)
    if failure is not None:
        return None, None, failure
    root = Path(args.path) if Path(args.path).is_dir() else Path(args.path).parent
    plan = build_plan(
        scan.records,
        operations,
        PlanOptions(overwrite=getattr(args, "overwrite", False)),
        root=root,
    )
    if scan.errors:
        plan.notes.extend(f"scan: {error}" for error in scan.errors)
    return plan, operations, None


def _plan_exit_code(plan) -> Optional[int]:
    """``EXIT_BLOCKED`` when the plan cannot be applied, else ``None``."""

    if plan.errors:
        return EXIT_USAGE
    if plan.blockers:
        return EXIT_BLOCKED
    if not plan.pending:
        return EXIT_NOTHING
    return None


def _confirm(console: Console, prompt: str) -> bool:
    if os.environ.get("EZRENAME_ASSUME_YES", "").lower() in ("1", "true", "yes"):
        return True
    if not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_list(args: argparse.Namespace) -> int:
    console = _console(args)
    scan, failure = _scan(args, console)
    if failure is not None:
        return failure
    render.render_files(
        scan.records,
        console,
        as_json=args.json,
        skipped=scan.skipped,
        errors=scan.errors,
    )
    return EXIT_OK if scan.records else EXIT_NOTHING


def cmd_preview(args: argparse.Namespace) -> int:
    console = _console(args)
    plan, _operations, failure = _plan(args, console)
    if failure is not None:
        return failure
    render.render_plan(plan, console, as_json=args.json, limit=_max_rows(args))
    code = _plan_exit_code(plan)
    return EXIT_OK if code is None else code


def cmd_rename(args: argparse.Namespace) -> int:
    console = _console(args)
    plan, _operations, failure = _plan(args, console)
    if failure is not None:
        return failure

    if not args.json:
        render.render_plan(plan, console, limit=_max_rows(args))

    code = _plan_exit_code(plan)
    if code is not None:
        if args.json:
            payload = plan.to_dict()
            payload["applied"] = False
            payload["exit_code"] = code
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            if code == EXIT_BLOCKED:
                console.error(
                    f"{len(plan.blockers)} file(s) cannot be renamed safely - see the reasons above"
                )
            elif code == EXIT_NOTHING:
                console.info("nothing to do: no file would change")
        return code

    if args.dry_run:
        engine = RenameEngine()
        result = engine.execute(plan, dry_run=True, overwrite=args.overwrite)
        render.render_execution(
            result, console, as_json=args.json, show_entries=not args.json, limit=_max_rows(args)
        )
        return EXIT_OK

    if not args.yes:
        if not _confirm(console, f"Rename {len(plan.pending)} file(s)?"):
            if args.json:
                print(json.dumps({"applied": False, "reason": "not confirmed", "exit_code": 2}, indent=2))
            else:
                console.info(
                    "cancelled: pass --yes to apply without confirmation "
                    "(required when the output is not a terminal)"
                )
            return EXIT_USAGE

    engine = RenameEngine()
    result = engine.execute(plan, overwrite=args.overwrite)
    if not args.json:
        render.render_execution(
            result, console, show_entries=True, limit=_max_rows(args)
        )
    else:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    _store(result, Console(quiet=True) if args.json else console, args)

    if result.failed or result.rollback_failures:
        return EXIT_FAILED
    if args.strict and any(
        outcome.status in (EntryStatus.SKIPPED, EntryStatus.UNCHANGED) for outcome in result.outcomes
    ):
        return EXIT_BLOCKED
    return EXIT_OK


def _store(result, console: Console, args: argparse.Namespace) -> Optional[str]:
    """Persist an executed session; storage problems must not lose the report."""

    try:
        settings = AppSettings.load()
        with HistoryStore() as store:
            session_id = store.record(result)
            if settings.history_limit > 0:
                store.prune(settings.history_limit)
    except Exception as exc:  # pragma: no cover - disk/permission problems
        console.warn(f"the session could not be written to the history: {exc}")
        return None
    if session_id:
        console.detail(f"  recorded session {session_id}")
    return session_id


def cmd_history(args: argparse.Namespace) -> int:
    console = _console(args)
    try:
        with HistoryStore() as store:
            if args.session:
                summary = store.get_session(args.session)
                if summary is None:
                    console.error(f"session '{args.session}' is not in the history")
                    return EXIT_USAGE
                entries = store.session_entries(args.session)
                render.render_session_detail(summary, entries, console, as_json=args.json)
                if args.export:
                    destination = store.export(args.session, Path(args.export), args.format)
                    console.success(f"manifest written to {destination}")
                return EXIT_OK
            sessions = store.list_sessions(limit=max(1, args.limit))
    except Exception as exc:  # pragma: no cover - corrupted history file
        console.error(f"cannot open the history: {exc}")
        return EXIT_FAILED
    render.render_sessions(sessions, console, as_json=args.json)
    if not sessions:
        return EXIT_NOTHING
    return EXIT_OK


def cmd_undo(args: argparse.Namespace) -> int:
    console = _console(args)
    with HistoryStore() as store:
        if args.list:
            sessions = [item for item in store.list_sessions(limit=50) if item.undoable]
            render.render_sessions(sessions, console, as_json=args.json)
            return EXIT_OK if sessions else EXIT_NOTHING

        session_id = args.session
        if not session_id:
            latest = store.latest_undoable()
            if latest is None:
                console.error("there is no rename session that can be undone")
                return EXIT_NOTHING
            session_id = latest.id

        report = store.verify(session_id)
        if args.dry_run:
            render.render_undo_report(report, console, as_json=args.json)
            if not report.can_undo_anything:
                return EXIT_BLOCKED
            result = store.undo(session_id, dry_run=True, allow_partial=args.allow_partial)
            if result.execution is not None:
                render.render_execution(
                    result.execution, console, as_json=args.json, limit=_max_rows(args)
                )
            return EXIT_OK

        if not report.can_undo_anything:
            if args.json:
                print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            else:
                render.render_undo_report(report, console)
                console.error("nothing was changed")
            return EXIT_BLOCKED

        if not args.yes and not _confirm(
            console, f"Restore {len(report.safe)} file name(s) from session {session_id}?"
        ):
            console.info("cancelled: pass --yes to undo without confirmation")
            return EXIT_USAGE

        result = store.undo(
            session_id,
            allow_partial=args.allow_partial,
        )
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            if result.report is not None and not result.ok:
                render.render_undo_report(result.report, console)
            if result.execution is not None:
                render.render_execution(result.execution, console)
            if result.ok:
                console.success(result.message)
            else:
                console.error(result.message)
        if result.execution is not None and (result.execution.failed or result.execution.rollback_failures):
            return EXIT_FAILED
        return EXIT_OK if result.ok else EXIT_BLOCKED


def cmd_export(args: argparse.Namespace) -> int:
    console = _console(args)
    with HistoryStore() as store:
        summary = store.get_session(args.session)
        if summary is None:
            console.error(f"session '{args.session}' is not in the history")
            return EXIT_USAGE
        destination = Path(args.output) if args.output else Path(f"session-{args.session}.{args.format}")
        try:
            written = store.export(args.session, destination, args.format)
        except (OSError, ValueError) as exc:
            console.error(f"cannot write the manifest: {exc}")
            return EXIT_FAILED
    if args.json:
        print(json.dumps({"manifest": str(written), "session": args.session}, indent=2))
    else:
        console.success(f"manifest written to {written}")
    return EXIT_OK


def _print_template_variables(console: Console, *, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(TEMPLATE_VARIABLES, indent=2))
    else:
        console.heading("Template variables")
        width = max(len(name) for name in TEMPLATE_VARIABLES)
        for name, description in TEMPLATE_VARIABLES.items():
            label = "{" + name + "}"
            console.write(f"  {label:<{width + 2}}  {description}")
        console.write("")
        console.info("  example: --template \"{stem}_{date}{ext}\"")
    return EXIT_OK


def cmd_ops(args: argparse.Namespace) -> int:
    console = _console(args)
    if args.json:
        payload = [
            {
                "type": cls.type,
                "label": cls.label,
                "category": cls.category,
                "description": cls.description,
                "options": sorted(
                    info.name for info in cls.__dataclass_fields__.values()  # type: ignore[attr-defined]
                    if info.name != "type"
                ),
            }
            for cls in OPERATION_CATALOGUE
        ]
        print(json.dumps({"operations": payload, "template_variables": TEMPLATE_VARIABLES}, indent=2))
        return EXIT_OK
    console.heading("Rename operations")
    for cls in OPERATION_CATALOGUE:
        console.write(
            f"  {console.paint(cls.label, 'cyan')} ({cls.type}) — {cls.description}"
        )
    console.write("")
    return _print_template_variables(console)


def cmd_config(args: argparse.Namespace) -> int:
    console = _console(args)
    settings = AppSettings.load()
    payload = {
        "settings_file": str(config_dir() / "settings.json"),
        "data_dir": str(data_dir()),
        "history_file": str(data_dir() / "history.db"),
        "settings": settings.to_dict(),
    }
    if args.path:
        print(payload["settings_file"])
        return EXIT_OK
    if args.show or args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return EXIT_OK
    console.heading("EzRename configuration")
    console.write(f"  settings: {payload['settings_file']}")
    console.write(f"  history:  {payload['history_file']}")
    console.write(f"  theme:    {settings.theme} ({settings.accent})")
    console.detail("  use --show for every value as JSON")
    return EXIT_OK


def cmd_gui(args: argparse.Namespace) -> int:
    console = _console(args)
    try:
        from ..gui.app import launch
    except ImportError as exc:
        console.error(
            "the graphical interface needs PySide6 and is not available in this build "
            f"({exc}). Install it with: pip install PySide6"
        )
        return EXIT_FAILED
    if args.check:
        console.success("the graphical interface can start in this environment")
        return EXIT_OK
    return launch(Path(args.path) if args.path else None)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI and return a process exit code."""

    argv = list(sys.argv[1:] if argv is None else argv)
    _configure_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)

    # --home may appear before or after the subcommand.
    home = getattr(args, "home", None)
    if not home:
        for index, token in enumerate(argv):
            if token == "--home" and index + 1 < len(argv):
                home = argv[index + 1]
                break
    if home:
        os.environ["EZRENAME_HOME"] = str(Path(home).expanduser())

    if getattr(args, "template_variables", False):
        return _print_template_variables(
            Console(quiet=getattr(args, "quiet", False)), as_json=getattr(args, "json", False)
        )

    handlers = {
        "list": cmd_list,
        "preview": cmd_preview,
        "rename": cmd_rename,
        "history": cmd_history,
        "undo": cmd_undo,
        "export": cmd_export,
        "ops": cmd_ops,
        "config": cmd_config,
        "gui": cmd_gui,
    }
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    handler = handlers[args.command]
    try:
        return handler(args)
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        print("interrupted - nothing else was changed", file=sys.stderr)
        return EXIT_FAILED
    except BrokenPipeError:  # pragma: no cover - piping into head
        return EXIT_OK


def _configure_stdout() -> None:
    """Make sure Unicode names survive a legacy Windows console."""

    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:  # pragma: no cover - very old interpreters
        return
    encoding = (getattr(stream, "encoding", "") or "").lower()
    if encoding.replace("-", "") not in ("utf8", "utf8mb4", "cp65001"):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover
            pass


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
