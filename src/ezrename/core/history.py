"""Persistent rename history, verification and undo.

Every executed session is written to a SQLite database so history survives
restarts. An undo is only ever attempted after re-validating the current state
of the filesystem, and it runs through the same safe executor as a normal
rename.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .engine import RenameEngine
from .models import EntryOutcome, EntryStatus, ExecutionResult
from .pipeline import PlanOptions, plan_from_targets

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL DEFAULT 'rename',
    parent_id     TEXT,
    created_at    TEXT NOT NULL,
    finished_at   TEXT,
    root          TEXT,
    operations    TEXT NOT NULL DEFAULT '[]',
    notes         TEXT NOT NULL DEFAULT '[]',
    total         INTEGER NOT NULL DEFAULT 0,
    renamed       INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    skipped       INTEGER NOT NULL DEFAULT 0,
    cancelled     INTEGER NOT NULL DEFAULT 0,
    dry_run       INTEGER NOT NULL DEFAULT 0,
    undone_at     TEXT,
    rollback_failures TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS entries (
    session_id    TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    source_path   TEXT NOT NULL,
    target_path   TEXT NOT NULL,
    original_name TEXT NOT NULL,
    target_name   TEXT NOT NULL,
    status        TEXT NOT NULL,
    message       TEXT NOT NULL DEFAULT '',
    backup_path   TEXT,
    size          INTEGER NOT NULL DEFAULT 0,
    mtime         REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_entries_session ON entries(session_id);
"""


def _iso(when: Optional[datetime]) -> Optional[str]:
    return when.isoformat() if when else None


def _parse(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:  # pragma: no cover - defensive
        return None


@dataclass
class SessionSummary:
    """Row-level view of a stored session."""

    id: str
    kind: str
    parent_id: Optional[str]
    created_at: Optional[datetime]
    finished_at: Optional[datetime]
    root: Optional[str]
    operations: list[dict]
    notes: list[str]
    total: int
    renamed: int
    failed: int
    skipped: int
    cancelled: bool
    dry_run: bool
    undone_at: Optional[datetime]
    rollback_failures: list[str]

    @property
    def undoable(self) -> bool:
        return (
            self.kind == "rename"
            and self.renamed > 0
            and self.undone_at is None
            and not self.dry_run
        )

    @property
    def status_label(self) -> str:
        if self.dry_run:
            return "dry run"
        if self.undone_at:
            return "undone"
        if self.cancelled:
            return "cancelled"
        if self.failed:
            return "completed with errors"
        return "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "parent_id": self.parent_id,
            "created_at": _iso(self.created_at),
            "finished_at": _iso(self.finished_at),
            "root": self.root,
            "operations": self.operations,
            "notes": self.notes,
            "total": self.total,
            "renamed": self.renamed,
            "failed": self.failed,
            "skipped": self.skipped,
            "cancelled": self.cancelled,
            "dry_run": self.dry_run,
            "undone_at": _iso(self.undone_at),
            "rollback_failures": self.rollback_failures,
            "undoable": self.undoable,
            "status": self.status_label,
        }


@dataclass
class UndoCheck:
    """Whether one entry of a session can be reversed right now."""

    source_path: Path
    target_name: str
    ok: bool
    reason: str = ""
    warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_path": str(self.source_path),
            "restore_to": self.target_name,
            "ok": self.ok,
            "reason": self.reason,
            "warning": self.warning,
        }


@dataclass
class UndoReport:
    """Result of verifying a session before undoing it."""

    session_id: str
    checks: list[UndoCheck] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def safe(self) -> list[UndoCheck]:
        return [check for check in self.checks if check.ok]

    @property
    def unsafe(self) -> list[UndoCheck]:
        return [check for check in self.checks if not check.ok]

    @property
    def can_undo_all(self) -> bool:
        return bool(self.checks) and not self.unsafe and not self.blockers

    @property
    def can_undo_anything(self) -> bool:
        return bool(self.safe)

    def reason_summary(self) -> str:
        parts = list(self.blockers)
        for check in self.unsafe[:5]:
            parts.append(f"{check.source_path.name}: {check.reason}")
        if len(self.unsafe) > 5:
            parts.append(f"... and {len(self.unsafe) - 5} more")
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session_id,
            "can_undo_all": self.can_undo_all,
            "safe": len(self.safe),
            "unsafe": len(self.unsafe),
            "blockers": list(self.blockers),
            "notes": list(self.notes),
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass
class UndoResult:
    """Outcome of an undo attempt (or a refusal to attempt one)."""

    session_id: str
    ok: bool
    message: str
    report: Optional[UndoReport] = None
    execution: Optional[ExecutionResult] = None
    partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session_id,
            "ok": self.ok,
            "message": self.message,
            "partial": self.partial,
            "report": self.report.to_dict() if self.report else None,
            "execution": self.execution.to_dict() if self.execution else None,
        }


class HistoryStore:
    """SQLite backed session history."""

    def __init__(self, path: Optional[Path] = None, *, timeout: float = 10.0) -> None:
        self.path = Path(path) if path else (self._default_path())
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self.path), timeout=timeout)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    @staticmethod
    def _default_path() -> Path:
        from .settings import data_dir

        return data_dir() / "history.db"

    # ------------------------------------------------------------------ #
    # Writing
    # ------------------------------------------------------------------ #

    def record(self, result: ExecutionResult) -> Optional[str]:
        """Store an executed session; dry runs are not recorded."""

        if result.dry_run:
            return None
        summary = result.summary()
        with self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO sessions (
                    id, kind, parent_id, created_at, finished_at, root, operations, notes,
                    total, renamed, failed, skipped, cancelled, dry_run, undone_at,
                    rollback_failures
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    result.session_id,
                    result.kind,
                    result.parent_id,
                    _iso(result.started),
                    _iso(result.finished),
                    str(result.root) if result.root else None,
                    json.dumps(result.operations, ensure_ascii=False),
                    json.dumps(result.notes, ensure_ascii=False),
                    summary["total"],
                    summary["renamed"],
                    summary["failed"],
                    summary["skipped"],
                    int(result.cancelled),
                    int(result.dry_run),
                    None,
                    json.dumps(result.rollback_failures, ensure_ascii=False),
                ),
            )
            self._connection.executemany(
                """
                INSERT OR REPLACE INTO entries (
                    session_id, seq, source_path, target_path, original_name, target_name,
                    status, message, backup_path, size, mtime
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        result.session_id,
                        index,
                        str(outcome.source),
                        str(outcome.target),
                        outcome.original_name or outcome.source.name,
                        outcome.target.name,
                        outcome.status.value,
                        outcome.message,
                        str(outcome.backup) if outcome.backup else None,
                        outcome.size,
                        outcome.mtime,
                    )
                    for index, outcome in enumerate(result.outcomes)
                ],
            )
        return result.session_id

    def mark_undone(self, session_id: str, when: Optional[datetime] = None) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE sessions SET undone_at = ? WHERE id = ?",
                (_iso(when or datetime.now(timezone.utc)), session_id),
            )

    def delete(self, session_id: str) -> bool:
        """Remove one history record (never touches the files themselves)."""

        with self._connection:
            cursor = self._connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._connection.execute("DELETE FROM entries WHERE session_id = ?", (session_id,))
        return cursor.rowcount > 0

    def clear(self) -> int:
        with self._connection:
            cursor = self._connection.execute("DELETE FROM sessions")
            self._connection.execute("DELETE FROM entries")
        return cursor.rowcount

    def prune(self, keep: int = 1000) -> int:
        """Delete the oldest records beyond *keep*."""

        if keep <= 0:
            return 0
        with self._connection:
            rows = self._connection.execute(
                "SELECT id FROM sessions ORDER BY created_at DESC LIMIT -1 OFFSET ?", (keep,)
            ).fetchall()
            for row in rows:
                self._connection.execute("DELETE FROM entries WHERE session_id = ?", (row["id"],))
                self._connection.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
        return len(rows)

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #

    def _row_to_summary(self, row: sqlite3.Row) -> SessionSummary:
        return SessionSummary(
            id=row["id"],
            kind=row["kind"],
            parent_id=row["parent_id"],
            created_at=_parse(row["created_at"]),
            finished_at=_parse(row["finished_at"]),
            root=row["root"],
            operations=json.loads(row["operations"] or "[]"),
            notes=json.loads(row["notes"] or "[]"),
            total=row["total"],
            renamed=row["renamed"],
            failed=row["failed"],
            skipped=row["skipped"],
            cancelled=bool(row["cancelled"]),
            dry_run=bool(row["dry_run"]),
            undone_at=_parse(row["undone_at"]),
            rollback_failures=json.loads(row["rollback_failures"] or "[]"),
        )

    def list_sessions(self, limit: int = 50, *, offset: int = 0) -> list[SessionSummary]:
        rows = self._connection.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_summary(row) for row in rows]

    def latest_undoable(self) -> Optional[SessionSummary]:
        for summary in self.list_sessions(limit=50):
            if summary.undoable:
                return summary
        return None

    def get_session(self, session_id: str) -> Optional[SessionSummary]:
        row = self._connection.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return self._row_to_summary(row) if row else None

    def session_entries(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM entries WHERE session_id = ? ORDER BY seq", (session_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT COUNT(*) AS sessions, COALESCE(SUM(renamed),0) AS renamed,"
            " COALESCE(SUM(failed),0) AS failed, MAX(created_at) AS last"
            " FROM sessions WHERE dry_run = 0"
        ).fetchone()
        last = _parse(row["last"]) if row else None
        return {
            "sessions": row["sessions"] if row else 0,
            "renamed": row["renamed"] if row else 0,
            "failed": row["failed"] if row else 0,
            "last_session": _iso(last),
        }

    # ------------------------------------------------------------------ #
    # Verification & undo
    # ------------------------------------------------------------------ #

    def verify(self, session_id: str) -> UndoReport:
        """Check whether a stored session can still be reversed safely."""

        report = UndoReport(session_id=session_id)
        summary = self.get_session(session_id)
        if summary is None:
            report.blockers.append(f"session '{session_id}' is not in the history")
            return report
        if summary.kind != "rename":
            report.blockers.append("only rename sessions can be undone")
            return report
        if summary.undone_at is not None:
            report.blockers.append(
                f"this session was already undone on {summary.undone_at.astimezone().strftime('%Y-%m-%d %H:%M')}"
            )
            return report

        rows = [
            row
            for row in self.session_entries(session_id)
            if row["status"] == EntryStatus.RENAMED.value
        ]
        if not rows:
            report.blockers.append("this session did not rename any file")
            return report

        pairs: list[tuple[Path, str]] = []
        for row in rows:
            current = Path(row["target_path"])
            original_name = row["original_name"]
            check = UndoCheck(source_path=current, target_name=original_name, ok=True)
            if not current.exists():
                check.ok = False
                check.reason = "the renamed file is no longer at this location"
            else:
                try:
                    info = current.stat()
                except OSError as exc:  # pragma: no cover - hostile filesystem
                    check.ok = False
                    check.reason = f"cannot read the file: {exc.strerror or exc}"
                else:
                    if row["size"] and info.st_size != row["size"]:
                        check.warning = "the file changed size since it was renamed"
                    elif row["mtime"] and abs(info.st_mtime - row["mtime"]) > 2:
                        check.warning = "the file was modified after it was renamed"
            if row["backup_path"]:
                backup = Path(row["backup_path"])
                if not backup.exists():
                    check.warning = (
                        check.warning + "; " if check.warning else ""
                    ) + "the file that was replaced by this rename is gone, so it cannot be restored"
            report.checks.append(check)
            if check.ok:
                pairs.append((current, original_name))

        if pairs:
            plan = plan_from_targets(
                pairs,
                PlanOptions(
                    note=f"undo of session {session_id}",
                    warn_extension_change=False,
                ),
                root=Path(summary.root) if summary.root else None,
            )
            for entry in plan.blockers:
                message = f"'{entry.target_name}' cannot be restored - {entry.message}"
                report.blockers.append(message)
                for check in report.checks:
                    if check.source_path == entry.source:
                        check.ok = False
                        check.reason = entry.message
            for entry in plan.entries:
                if entry.status is EntryStatus.UNCHANGED:
                    for check in report.checks:
                        if check.source_path == entry.source:
                            check.ok = False
                            check.reason = "the file already has its original name"
        return report

    def undo(
        self,
        session_id: str,
        *,
        dry_run: bool = False,
        allow_partial: bool = False,
        overwrite: bool = False,
        engine: Optional[RenameEngine] = None,
        progress: Optional[Callable[[int, int, EntryOutcome], None]] = None,
        cancel: Optional[Callable[[], bool]] = None,
    ) -> UndoResult:
        """Restore the original names of a previous session."""

        report = self.verify(session_id)
        if report.blockers and not report.checks:
            return UndoResult(session_id, False, report.reason_summary(), report=report)
        if not report.can_undo_anything:
            return UndoResult(
                session_id,
                False,
                f"nothing can be undone safely: {report.reason_summary()}",
                report=report,
            )
        partial = not report.can_undo_all
        if partial and not allow_partial:
            return UndoResult(
                session_id,
                False,
                "some files cannot be restored safely: "
                + report.reason_summary()
                + ". Nothing was changed.",
                report=report,
                partial=True,
            )

        stored = self.get_session(session_id)
        root = Path(stored.root) if stored and stored.root else None
        pairs = [(check.source_path, check.target_name) for check in report.safe]
        plan = plan_from_targets(
            pairs,
            PlanOptions(overwrite=overwrite, warn_extension_change=False),
            root=root,
            operations_payload=[{"type": "undo", "of": session_id}],
            notes=[f"undo of session {session_id}"],
        )
        executor = engine or RenameEngine()
        execution = executor.execute(
            plan,
            dry_run=dry_run,
            overwrite=overwrite,
            progress=progress,
            cancel=cancel,
            kind="undo",
            parent_id=session_id,
        )

        if dry_run:
            return UndoResult(
                session_id,
                True,
                f"dry run: {len(plan.pending)} file(s) would be restored",
                report=report,
                execution=execution,
                partial=partial,
            )

        self.record(execution)
        failures = len(execution.failed) + len(execution.rollback_failures)
        # A session counts as undone only when every rename of it was reversed.
        if not failures and not partial:
            self.mark_undone(session_id)
        message = (
            f"restored {len(execution.renamed)} file name(s)"
            if not failures
            else f"restored {len(execution.renamed)} file name(s), {failures} failed"
        )
        if partial:
            message += f"; {len(report.unsafe)} file(s) were left as they are"
        return UndoResult(
            session_id,
            not failures,
            message,
            report=report,
            execution=execution,
            partial=partial,
        )

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #

    def export(self, session_id: str, destination: Path, fmt: str = "json") -> Path:
        """Write a session manifest that can be used for auditing or recovery."""

        summary = self.get_session(session_id)
        if summary is None:
            raise KeyError(f"session '{session_id}' is not in the history")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        entries = self.session_entries(session_id)
        if fmt == "csv":
            with destination.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "session",
                        "status",
                        "source_path",
                        "target_path",
                        "original_name",
                        "target_name",
                        "backup_path",
                        "message",
                    ]
                )
                for row in entries:
                    writer.writerow(
                        [
                            row["session_id"],
                            row["status"],
                            row["source_path"],
                            row["target_path"],
                            row["original_name"],
                            row["target_name"],
                            row["backup_path"] or "",
                            row["message"],
                        ]
                    )
        elif fmt == "json":
            payload = summary.to_dict()
            payload["entries"] = entries
            destination.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        else:
            raise ValueError("format must be 'json' or 'csv'")
        return destination

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
