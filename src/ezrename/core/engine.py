"""The executor: performs a validated plan with maximum data safety.

Design rules enforced here:

* Nothing is ever deleted. When overwriting is explicitly enabled, the
  existing destination is *quarantined* under a backup name instead.
* Names involved in cycles/swaps (and case-only renames) are first moved to
  unique intermediate names, then to their final names, so ``A <-> B`` works.
* If a rename fails, the file is put back under its original name. If the
  batch is left in an inconsistent state by a swap, the whole batch is rolled
  back so the folder returns to exactly what it looked like before.
* Every failure is reported with the real on-disk state, including the name a
  file is stored under if it could not be restored.
* A dry run never touches the filesystem.
"""

from __future__ import annotations

import errno
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

from .models import EntryOutcome, EntryStatus, ExecutionResult, PlanEntry, RenamePlan
from .naming import fold, make_backup_name, make_temp_name, path_exists, same_file

ProgressCallback = Callable[[int, int, EntryOutcome], None]
CancelCallback = Callable[[], bool]


@dataclass
class EngineOptions:
    """Runtime switches for :class:`RenameEngine`."""

    #: Explicitly allow replacing an existing destination (quarantined, not deleted).
    overwrite: bool = False
    dry_run: bool = False


def _describe_error(exc: OSError) -> str:
    """Turn an OSError into a message that tells the user what to do."""

    reason = exc.strerror or str(exc)
    mapping = {
        errno.EACCES: "the file is locked, read-only or owned by another process",
        errno.EPERM: "permission denied",
        errno.ENOENT: "the file no longer exists",
        errno.ENOTEMPTY: "the destination is a non-empty folder",
        errno.EEXIST: "a file with that name already exists",
        errno.EBUSY: "the file is in use by another program",
        errno.EINVAL: "the name is not accepted by the filesystem",
        errno.ENAMETOOLONG: "the resulting path is too long",
        errno.ENOSPC: "the destination drive is full",
    }
    friendly = mapping.get(exc.errno)
    if friendly:
        return f"{reason} ({friendly})"
    if reason != str(exc):
        return f"{reason}"
    return f"{type(exc).__name__}: {exc}"


def new_session_id() -> str:
    """Short, sortable, unique session identifier."""

    return f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


class RenameEngine:
    """Execute :class:`~ezrename.core.models.RenamePlan` objects safely."""

    def __init__(self, options: Optional[EngineOptions] = None) -> None:
        self.options = options or EngineOptions()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def execute(
        self,
        plan: RenamePlan,
        *,
        dry_run: Optional[bool] = None,
        overwrite: Optional[bool] = None,
        progress: Optional[ProgressCallback] = None,
        cancel: Optional[CancelCallback] = None,
        kind: str = "rename",
        parent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        operations: Optional[Sequence[dict]] = None,
        notes: Optional[Sequence[str]] = None,
    ) -> ExecutionResult:
        """Apply *plan* and return a complete report of what happened."""

        dry = self.options.dry_run if dry_run is None else dry_run
        allow_overwrite = self.options.overwrite if overwrite is None else overwrite

        result = ExecutionResult(
            session_id=session_id or new_session_id(),
            operations=list(operations if operations is not None else plan.operations),
            root=plan.root,
            dry_run=dry,
            kind=kind,
            parent_id=parent_id,
            notes=list(plan.notes) + list(notes or []),
        )

        entries = list(plan.entries)
        total = len(entries)
        outcomes: dict[int, EntryOutcome] = {}
        state = {"done": 0}

        def record(index: int, outcome: EntryOutcome, *, replace: bool = False) -> None:
            if index in outcomes and not replace:
                return
            first_time = index not in outcomes
            outcomes[index] = outcome
            if first_time:
                state["done"] += 1
            if progress is not None:
                progress(min(state["done"], total), total, outcome)

        for index, entry in enumerate(entries):
            if not entry.will_rename:
                record(index, self._outcome(entry, entry.status, entry.message))

        if dry:
            for index, entry in enumerate(entries):
                if entry.will_rename:
                    record(
                        index,
                        self._outcome(
                            entry,
                            EntryStatus.PLANNED,
                            "dry run: nothing was changed on disk",
                            target=entry.target,
                        ),
                    )
        else:
            self._run(entries, outcomes, record, result, allow_overwrite, cancel)

        result.outcomes = [outcomes[index] for index in range(total) if index in outcomes]
        result.finished = datetime.now(timezone.utc)
        return result

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _outcome(
        entry: PlanEntry,
        status: EntryStatus,
        message: str,
        *,
        target: Optional[Path] = None,
        backup: Optional[Path] = None,
    ) -> EntryOutcome:
        return EntryOutcome(
            source=entry.source,
            target=target or entry.target,
            status=status,
            message=message,
            backup=backup,
            original_name=entry.original_name,
            size=entry.size,
            mtime=entry.mtime,
        )

    def _temp_path_for(self, source: Path) -> Path:
        for _attempt in range(64):
            candidate = source.with_name(make_temp_name(source.name, uuid.uuid4().hex[:8]))
            if not path_exists(candidate):
                return candidate
        raise RuntimeError(f"no free temporary name next to {source}")  # pragma: no cover

    def _backup_path_for(self, target: Path) -> Path:
        for _attempt in range(64):
            candidate = target.with_name(make_backup_name(target.name, uuid.uuid4().hex[:8]))
            if not path_exists(candidate):
                return candidate
        raise RuntimeError(f"no free backup name next to {target}")  # pragma: no cover

    def _needs_temp(self, entries: Sequence[tuple[int, PlanEntry]]) -> dict[int, bool]:
        """Which entries must be moved aside before their final rename."""

        sources = {fold(entry.original_name): entry.source for _index, entry in entries}
        needs: dict[int, bool] = {}
        for index, entry in entries:
            owner = sources.get(fold(entry.target_name))
            case_only = fold(entry.target_name) == fold(entry.original_name)
            needs[index] = case_only or (owner is not None and owner != entry.source)
        return needs

    def _run(
        self,
        entries: list[PlanEntry],
        outcomes: dict[int, EntryOutcome],
        record: Callable[..., None],
        result: ExecutionResult,
        overwrite: bool,
        cancel: Optional[CancelCallback],
    ) -> None:
        pending = [(index, entry) for index, entry in enumerate(entries) if entry.will_rename]
        if not pending:
            return

        needs = self._needs_temp(pending)
        current: dict[int, Path] = {index: entry.source for index, entry in pending}
        parked: dict[int, Path] = {}
        committed: list[int] = []
        failed: set[int] = set()
        abort_message = ""

        # ---- phase 1: park the names that would collide -------------------
        for index, entry in pending:
            if not needs[index]:
                continue
            if cancel is not None and cancel():
                result.cancelled = True
                abort_message = "the session was cancelled"
                break
            temp = self._temp_path_for(entry.source)
            try:
                os.rename(entry.source, temp)
            except OSError as exc:
                failed.add(index)
                record(
                    index,
                    self._outcome(
                        entry,
                        EntryStatus.FAILED,
                        f"could not move the file aside: {_describe_error(exc)}",
                        target=entry.source,
                    ),
                )
            else:
                parked[index] = temp
                current[index] = temp

        # ---- phase 2: rename everything to its final name -----------------
        if not abort_message:
            for index, entry in pending:
                if index in failed:
                    continue
                if cancel is not None and cancel():
                    result.cancelled = True
                    abort_message = "the session was cancelled"
                    break
                outcome, ok, escalate = self._commit(
                    entry, current[index], overwrite, result
                )
                if ok:
                    current[index] = entry.target
                    committed.append(index)
                    record(index, outcome)
                    continue
                failed.add(index)
                record(index, outcome)
                if escalate:
                    # A swap went wrong and a parked file could not be put
                    # back on its own, so restore the whole batch.
                    abort_message = "an earlier failure left the batch half-applied"
                    result.notes.append(
                        "the batch was rolled back to avoid leaving files with "
                        "inconsistent names"
                    )
                    self._rollback_batch(pending, committed, current, outcomes, record, result)
                    committed = []
                    result.cancelled = True
                    break

        # ---- anything left over is reported honestly ----------------------
        for index, entry in pending:
            if index in outcomes:
                continue
            if current[index] != entry.source:
                self._restore_parked(index, entry, current, outcomes, record, result)
            else:
                record(
                    index,
                    self._outcome(
                        entry,
                        EntryStatus.SKIPPED,
                        f"{abort_message or 'the session stopped'} before this file was renamed",
                        target=entry.source,
                    ),
                )

    def _commit(
        self, entry: PlanEntry, current: Path, overwrite: bool, result: ExecutionResult
    ) -> tuple[EntryOutcome, bool, bool]:
        """Rename one file to its target.

        Returns ``(outcome, success, escalate)`` where *escalate* means the
        batch must be rolled back because a parked file could not be restored.
        """

        target = entry.target
        backup: Optional[Path] = None

        if path_exists(target) and not same_file(target, current):
            if not overwrite:
                return (
                    self._outcome(
                        entry,
                        EntryStatus.FAILED,
                        f"'{target.name}' appeared at the destination after the preview; "
                        "nothing was renamed to avoid overwriting it",
                    ),
                    False,
                    False,
                )
            try:
                backup = self._backup_path_for(target)
                os.rename(target, backup)
            except OSError as exc:
                return (
                    self._outcome(
                        entry,
                        EntryStatus.FAILED,
                        f"could not move the existing file aside: {_describe_error(exc)}",
                    ),
                    False,
                    False,
                )

        try:
            os.rename(current, target)
        except OSError as exc:
            detail = _describe_error(exc)
            if backup is not None:
                try:
                    os.rename(backup, target)
                except OSError as restore_exc:  # pragma: no cover - hostile filesystem
                    result.rollback_failures.append(
                        f"{target}: the file that was replaced is stored as '{backup}' "
                        f"({_describe_error(restore_exc)})"
                    )
                else:
                    backup = None
            if current == entry.source:
                return (
                    self._outcome(entry, EntryStatus.FAILED, f"the rename failed: {detail}"),
                    False,
                    False,
                )
            try:
                os.rename(current, entry.source)
            except OSError:
                message = (
                    f"the rename failed ({detail}) and the original name '"
                    f"{entry.original_name}' could not be restored"
                )
                return (
                    self._outcome(
                        entry, EntryStatus.FAILED, message, target=entry.source
                    ),
                    False,
                    True,
                )
            return (
                self._outcome(
                    entry,
                    EntryStatus.ROLLED_BACK,
                    f"the rename failed ({detail}); the original name was restored",
                    target=entry.source,
                ),
                False,
                False,
            )

        return (
            self._outcome(
                entry,
                EntryStatus.RENAMED,
                f"'{entry.original_name}' -> '{target.name}'",
                backup=backup,
            ),
            True,
            False,
        )

    def _rollback_batch(
        self,
        pending: Sequence[tuple[int, PlanEntry]],
        committed: Sequence[int],
        current: dict[int, Path],
        outcomes: dict[int, EntryOutcome],
        record: Callable[..., None],
        result: ExecutionResult,
    ) -> None:
        """Put every file of the batch back under its original name.

        Targets are parked first so all original names become free, which makes
        this safe for swaps and longer rename cycles.
        """

        for index in committed:
            path = current[index]
            if not path_exists(path):  # pragma: no cover - defensive
                continue
            try:
                temp = self._temp_path_for(path)
                os.rename(path, temp)
                current[index] = temp
            except OSError as exc:  # pragma: no cover - hostile filesystem
                result.rollback_failures.append(
                    f"{path}: {_describe_error(exc)} - the file keeps its new name"
                )

        for index, entry in pending:
            if current[index] == entry.source:
                continue
            self._restore_parked(index, entry, current, outcomes, record, result)

    def _restore_parked(
        self,
        index: int,
        entry: PlanEntry,
        current: dict[int, Path],
        outcomes: dict[int, EntryOutcome],
        record: Callable[..., None],
        result: ExecutionResult,
    ) -> None:
        """Give one file its original name back, reporting the real outcome."""

        source = entry.source
        stored = current[index]
        was_committed = outcomes.get(index) is not None and outcomes[index].status is EntryStatus.RENAMED
        try:
            os.rename(stored, source)
        except OSError as exc:
            result.rollback_failures.append(
                f"{source}: still stored as '{stored.name}' - {_describe_error(exc)}"
            )
            record(
                index,
                self._outcome(
                    entry,
                    EntryStatus.FAILED,
                    f"the original name could not be restored; the file is stored as "
                    f"'{stored.name}' ({_describe_error(exc)})",
                    target=source,
                ),
                replace=True,
            )
            return
        current[index] = source
        if was_committed:
            message = "the rename was undone because the batch had to be rolled back"
            status = EntryStatus.ROLLED_BACK
        else:
            message = "the file was left untouched after an earlier failure"
            status = EntryStatus.SKIPPED
        record(index, self._outcome(entry, status, message, target=source), replace=True)
