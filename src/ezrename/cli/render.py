"""Terminal output for the CLI: colours, tables, summaries and JSON.

Everything here is plain ``print`` based on purpose: the CLI has no third party
dependency and stays usable on a bare Python install.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Iterable, Optional, Sequence, TextIO

from ..core.models import (
    EntryStatus,
    ExecutionResult,
    PlanEntry,
    RenamePlan,
)
from ..core.history import SessionSummary, UndoReport

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

FG = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "grey": "\033[90m",
    "bright_green": "\033[92m",
    "bright_yellow": "\033[93m",
    "bright_red": "\033[91m",
    "bright_cyan": "\033[96m",
}

UNICODE_SYMBOLS = {
    EntryStatus.READY: "\u2192",
    EntryStatus.PLANNED: "\u2192",
    EntryStatus.UNCHANGED: "=",
    EntryStatus.SKIPPED: "\u00b7",
    EntryStatus.DUPLICATE: "\u203c",
    EntryStatus.EXISTS: "\u203c",
    EntryStatus.INVALID: "\u203c",
    EntryStatus.ERROR: "\u203c",
    EntryStatus.RENAMED: "\u2713",
    EntryStatus.UNDONE: "\u21a9",
    EntryStatus.FAILED: "\u2717",
    EntryStatus.ROLLED_BACK: "\u21ba",
}

ASCII_SYMBOLS = {
    EntryStatus.READY: "->",
    EntryStatus.PLANNED: "->",
    EntryStatus.UNCHANGED: "==",
    EntryStatus.SKIPPED: "..",
    EntryStatus.DUPLICATE: "!!",
    EntryStatus.EXISTS: "!!",
    EntryStatus.INVALID: "!!",
    EntryStatus.ERROR: "!!",
    EntryStatus.RENAMED: "ok",
    EntryStatus.UNDONE: "<-",
    EntryStatus.FAILED: "xx",
    EntryStatus.ROLLED_BACK: "<>",
}

COLOURS = {
    EntryStatus.READY: "bright_cyan",
    EntryStatus.PLANNED: "bright_cyan",
    EntryStatus.UNCHANGED: "grey",
    EntryStatus.SKIPPED: "grey",
    EntryStatus.DUPLICATE: "bright_red",
    EntryStatus.EXISTS: "bright_red",
    EntryStatus.INVALID: "bright_red",
    EntryStatus.ERROR: "bright_red",
    EntryStatus.RENAMED: "bright_green",
    EntryStatus.UNDONE: "bright_green",
    EntryStatus.FAILED: "bright_red",
    EntryStatus.ROLLED_BACK: "bright_yellow",
}

STATUS_WORDS = {
    EntryStatus.READY: "ready",
    EntryStatus.PLANNED: "would rename",
    EntryStatus.UNCHANGED: "unchanged",
    EntryStatus.SKIPPED: "skipped",
    EntryStatus.DUPLICATE: "duplicate target",
    EntryStatus.EXISTS: "destination exists",
    EntryStatus.INVALID: "invalid name",
    EntryStatus.ERROR: "error",
    EntryStatus.RENAMED: "renamed",
    EntryStatus.UNDONE: "restored",
    EntryStatus.FAILED: "failed",
    EntryStatus.ROLLED_BACK: "rolled back",
}


class Console:
    """Colour aware writer with quiet/verbose control."""

    def __init__(
        self,
        stream: Optional[TextIO] = None,
        *,
        colour: Optional[bool] = None,
        quiet: bool = False,
        verbose: bool = False,
    ) -> None:
        self.stream = stream or sys.stdout
        self.quiet = quiet
        self.verbose = verbose
        if colour is None:
            colour = self._auto_colour(self.stream)
        self.colour = colour
        self.symbols = UNICODE_SYMBOLS if self._unicode_ok() else ASCII_SYMBOLS

    @staticmethod
    def _auto_colour(stream: TextIO) -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("EZRENAME_COLOR", "").lower() in ("1", "true", "yes"):
            return True
        try:
            return bool(stream.isatty())
        except (AttributeError, ValueError):  # pragma: no cover - closed stream
            return False

    def _unicode_ok(self) -> bool:
        encoding = getattr(self.stream, "encoding", None) or "utf-8"
        try:
            "\u2192\u2713\u2717".encode(encoding)
        except (UnicodeEncodeError, LookupError):
            return False
        return True

    def paint(self, text: str, colour: str = "", *, bold: bool = False) -> str:
        if not self.colour or (not colour and not bold):
            return text
        prefix = (FG.get(colour, "") if colour else "") + (BOLD if bold else "")
        return f"{prefix}{text}{RESET}" if prefix else text

    def write(self, text: str = "") -> None:
        print(text, file=self.stream)

    def info(self, text: str) -> None:
        if not self.quiet:
            self.write(text)

    def detail(self, text: str) -> None:
        if self.verbose and not self.quiet:
            self.write(self.paint(text, "grey"))

    def warn(self, text: str) -> None:
        if not self.quiet:
            self.write(self.paint(f"warning: {text}", "bright_yellow"))

    def error(self, text: str) -> None:
        self.write(self.paint(f"error: {text}", "bright_red"))

    def success(self, text: str) -> None:
        if not self.quiet:
            self.write(self.paint(text, "bright_green"))

    def heading(self, text: str) -> None:
        if not self.quiet:
            self.write(self.paint(text, "cyan", bold=True))

    def rule(self, width: int = 60) -> None:
        if not self.quiet:
            self.write(self.paint("-" * width, "grey"))


def truncate(text: str, width: int) -> str:
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def status_style(status: EntryStatus) -> tuple[str, str]:
    return STATUS_WORDS.get(status, status.value), COLOURS.get(status, "")


def _describe_entry(entry: PlanEntry) -> str:
    return entry.message or ""


def render_plan(
    plan: RenamePlan,
    console: Console,
    *,
    as_json: bool = False,
    show_notes: bool = True,
    limit: Optional[int] = None,
) -> None:
    """Print a plan as a table (or JSON)."""

    if as_json:
        console.write(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
        return

    summary = plan.summary()
    console.heading(f"Preview - {summary['files']} file(s), {summary['rename']} would change")
    if plan.operations:
        from ..core.operations import describe_operations, operations_from_dicts

        try:
            operations = operations_from_dicts(plan.operations)
        except Exception:  # pragma: no cover - plan was built by us
            operations = []
        for line in describe_operations(operations):
            console.detail(f"  {line}")

    entries = plan.entries
    truncated = False
    if limit is not None and len(entries) > limit:
        entries = entries[:limit]
        truncated = True

    if entries:
        name_width = min(
            48, max([len(entry.original_name) for entry in entries] + [14])
        )
        target_width = min(
            48, max([len(entry.target_name) for entry in entries] + [14])
        )
        console.write(
            f"  {'#':>4}  {'original':<{name_width}}  {'':2}  {'new name':<{target_width}}  status"
        )
        for index, entry in enumerate(entries, start=1):
            word, colour = status_style(entry.status)
            symbol = console.symbols.get(entry.status, "  ")
            original = truncate(entry.original_name, name_width)
            target = truncate(entry.target_name, target_width)
            line = (
                f"  {index:>4}  {original:<{name_width}}  {symbol}  {target:<{target_width}}"
            )
            detail = _describe_entry(entry)
            console.write(
                console.paint(line, colour if entry.status is not EntryStatus.READY else "")
                + ("  " + console.paint(word, colour))
                + (("  " + detail) if detail and entry.status not in (EntryStatus.READY,) else "")
            )
    if truncated:
        console.info(f"  ... {len(plan.entries) - len(entries)} more file(s) not shown")

    console.write("")
    counts = plan.counts()
    pieces = [f"{summary['rename']} to rename"]
    for key, label in (
        ("unchanged", "unchanged"),
        ("skipped", "skipped"),
        ("duplicates", "duplicate targets"),
        ("existing", "destination exists"),
        ("invalid", "invalid names"),
        ("errors", "errors"),
    ):
        if counts.get(key):
            pieces.append(f"{counts[key]} {label}")
    console.write("  " + console.paint(" | ".join(pieces), "white"))

    if show_notes and plan.notes:
        for note in plan.notes:
            console.warn(note)
    for problem in plan.errors:
        console.error(problem)


def render_execution(
    result: ExecutionResult,
    console: Console,
    *,
    as_json: bool = False,
    show_entries: bool = True,
    limit: Optional[int] = None,
) -> None:
    """Print the outcome of a rename or undo session."""

    if as_json:
        console.write(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    summary = result.summary()
    verb = "Dry run" if result.dry_run else ("Undo" if result.kind == "undo" else "Rename")
    if result.dry_run:
        headline = (
            f"{verb}: {summary['planned']} file(s) would be renamed, "
            f"{summary['skipped']} unchanged or skipped, {summary['failed']} blocked (of {summary['total']})"
        )
    else:
        verb_word = "restored" if result.kind == "undo" else "renamed"
        headline = (
            f"{verb}: {summary['renamed']} {verb_word}, {summary['failed']} failed, "
            f"{summary['skipped']} skipped (of {summary['total']})"
        )
    if result.cancelled:
        headline += " - cancelled"
    (console.warn(headline) if summary["failed"] else console.success(headline))

    entries = result.outcomes
    if limit is not None and len(entries) > limit:
        entries = entries[:limit]
    if show_entries and entries:
        console.write("")
        for entry in entries:
            if entry.status in (EntryStatus.UNCHANGED, EntryStatus.SKIPPED) and not console.verbose:
                continue
            word, colour = status_style(entry.status)
            symbol = console.symbols.get(entry.status, "  ")
            text = f"  {symbol} {entry.original_name} -> {entry.target.name}"
            if entry.status in (EntryStatus.FAILED, EntryStatus.ROLLED_BACK):
                text = f"  {symbol} {entry.original_name}: {entry.message}"
            console.write(console.paint(text, colour))
            if entry.backup is not None:
                console.write(
                    console.paint(
                        f"      the previous file was kept as '{entry.backup.name}'", "grey"
                    )
                )

    if result.rollback_failures:
        console.write("")
        console.error("some files could not be put back - recover them manually:")
        for failure in result.rollback_failures:
            console.write(console.paint(f"  {failure}", "bright_red"))
    for note in result.notes:
        console.detail(f"  note: {note}")
    if not result.dry_run and result.renamed:
        console.info(
            f"  session {result.session_id} is stored in the history - "
            f"'ezrename undo {result.session_id}' restores it"
        )


def render_sessions(
    sessions: Sequence[SessionSummary],
    console: Console,
    *,
    as_json: bool = False,
) -> None:
    if as_json:
        console.write(json.dumps([item.to_dict() for item in sessions], indent=2, ensure_ascii=False))
        return
    if not sessions:
        console.info("no rename sessions have been recorded yet")
        return
    console.heading(f"{len(sessions)} session(s), newest first")
    console.write(
        f"  {'session':<24}  {'when':<17}  {'renamed':>7}  {'failed':>6}  status"
    )
    for item in sessions:
        when = (
            item.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
            if item.created_at
            else "?"
        )
        colour = {
            "completed": "bright_green",
            "undone": "grey",
            "cancelled": "bright_yellow",
        }.get(item.status_label, "bright_red" if item.failed else "white")
        console.write(
            console.paint(
                f"  {item.id:<24}  {when:<17}  {item.renamed:>7}  {item.failed:>6}  "
                f"{item.status_label}",
                colour,
            )
        )


def render_session_detail(
    summary: SessionSummary,
    entries: Sequence[dict[str, Any]],
    console: Console,
    *,
    as_json: bool = False,
) -> None:
    if as_json:
        payload = summary.to_dict()
        payload["entries"] = list(entries)
        console.write(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    console.heading(f"Session {summary.id} ({summary.status_label})")
    console.write(f"  folder:     {summary.root or '-'}")
    console.write(
        f"  started:    {summary.created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S') if summary.created_at else '-'}"
    )
    console.write(
        f"  totals:     {summary.renamed} renamed, {summary.failed} failed, {summary.skipped} skipped"
    )
    from ..core.operations import describe_operations, operations_from_dicts

    if summary.operations:
        try:
            for line in describe_operations(operations_from_dicts(summary.operations)):
                console.detail(f"  operation:  {line}")
        except Exception:  # pragma: no cover
            pass
    if entries:
        console.write("")
        for row in entries:
            try:
                status = EntryStatus(row["status"])
            except ValueError:  # pragma: no cover
                status = EntryStatus.ERROR
            word, colour = status_style(status)
            console.write(
                console.paint(
                    f"  {console.symbols.get(status, '  ')} {row['original_name']} -> "
                    f"{row['target_name']}  [{word}]",
                    colour,
                )
            )


def render_undo_report(
    report: UndoReport,
    console: Console,
    *,
    as_json: bool = False,
) -> None:
    if as_json:
        console.write(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return
    console.heading(f"Undo check for session {report.session_id}")
    console.write(
        f"  {len(report.safe)} file(s) can be restored, {len(report.unsafe)} cannot"
    )
    for check in report.unsafe:
        console.write(
            console.paint(f"  ! {check.source_path.name}: {check.reason}", "bright_red")
        )
    for check in report.safe:
        if check.warning:
            console.write(
                console.paint(f"  ~ {check.source_path.name}: {check.warning}", "bright_yellow")
            )
    for blocker in report.blockers:
        console.error(blocker)


def render_files(
    records: Iterable[Any],
    console: Console,
    *,
    as_json: bool = False,
    skipped: int = 0,
    errors: Optional[Sequence[str]] = None,
) -> None:
    records = list(records)
    if as_json:
        payload = {
            "count": len(records),
            "skipped": skipped,
            "errors": list(errors or []),
            "files": [record.to_dict() for record in records],
        }
        console.write(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    console.heading(f"{len(records)} file(s)")
    if not records:
        console.info("  nothing to show")
    width = min(56, max([len(record.name) for record in records] + [10]))
    for index, record in enumerate(records, start=1):
        size = f"{record.size:>10,}"
        console.write(
            f"  {index:>4}  {truncate(record.name, width):<{width}}  {size} bytes  "
            f"{record.modified.strftime('%Y-%m-%d %H:%M')}"
        )
    if skipped:
        console.info(f"  {skipped} entr(ies) were filtered out")
    for problem in errors or []:
        console.warn(problem)


def render_summary_line(console: Console, text: str, *, colour: str = "") -> None:
    console.write(console.paint(text, colour) if colour else text)
