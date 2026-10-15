"""Turn a list of files plus a list of operations into a validated plan.

This module is the single source of truth for *what* a rename would do. The
GUI preview, the CLI ``preview``/``rename`` commands and the undo engine all
call into it, so every interface agrees on the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from .models import EntryStatus, FileRecord, PlanEntry, RenamePlan
from .naming import (
    fold,
    is_internal_name,
    path_length_risk,
    same_file,
    path_exists,
    validate_filename,
)
from .operations import (
    FileOperationError,
    NameContext,
    Operation,
    OperationError,
)

FileLike = Union[FileRecord, Path]


@dataclass
class PlanOptions:
    """Knobs that control how strict the plan validation is."""

    overwrite: bool = False
    max_name_length: int = 255
    warn_path_length: bool = True
    #: Treat files that already match their target as "unchanged" rather than
    #: as errors. Always ``True`` in the shipped interfaces.
    allow_unchanged: bool = True
    warn_extension_change: bool = True
    #: Extra note attached to the plan, e.g. "undo session abc123".
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "overwrite": self.overwrite,
            "max_name_length": self.max_name_length,
            "warn_path_length": self.warn_path_length,
            "warn_extension_change": self.warn_extension_change,
            "note": self.note,
        }


def _as_record(item: FileLike) -> FileRecord:
    if isinstance(item, FileRecord):
        return item
    path = Path(item)
    return FileRecord(path=path, is_hidden=path.name.startswith("."), is_symlink=path.is_symlink())


def apply_operations(
    name: str,
    operations: Sequence[Operation],
    *,
    index: int = 0,
    path: Optional[Path] = None,
    size: int = 0,
    mtime: float = 0.0,
    ctime: float = 0.0,
    atime: float = 0.0,
    prefix: str = "",
    suffix: str = "",
) -> str:
    """Return the new file name for *name* after *operations* (pure function)."""

    ctx = NameContext.from_name(
        name, index=index, path=path, size=size, mtime=mtime, ctime=ctime, atime=atime
    )
    ctx.prefix = prefix
    ctx.suffix = suffix
    for operation in operations:
        operation.apply(ctx)
    return ctx.name


def _finalise(
    candidates: list[tuple[FileRecord, str, EntryStatus, str, list[str]]],
    options: PlanOptions,
    *,
    root: Optional[Path],
    operations_payload: list[dict],
    notes: list[str],
    errors: list[str],
) -> RenamePlan:
    """Validate names, detect collisions and build the plan."""

    plan = RenamePlan(
        root=root, operations=operations_payload, notes=list(notes), errors=list(errors)
    )
    for record, name, status, message, warnings in candidates:
        plan.entries.append(
            PlanEntry(
                source=record.path,
                target_name=name,
                status=status,
                message=message,
                warnings=list(warnings),
                size=record.size,
                mtime=record.mtime,
            )
        )

    # --- collision detection ------------------------------------------------
    by_target: dict[str, list[PlanEntry]] = {}
    for entry in plan.entries:
        if entry.status in (EntryStatus.INVALID, EntryStatus.ERROR, EntryStatus.SKIPPED):
            continue
        by_target.setdefault(fold(entry.target_name), []).append(entry)

    for _key, entries in by_target.items():
        # A file that keeps its own name does not move, so it cannot collide
        # with another file's target - it is a *destination*, handled below.
        movers = [entry for entry in entries if entry.changed]
        if len(movers) < 2:
            continue
        names = ", ".join(sorted({entry.original_name for entry in movers}))[:160]
        for entry in movers:
            entry.status = EntryStatus.DUPLICATE
            entry.message = f"another file in this batch also becomes '{entry.target_name}' ({names})"

    # --- destination conflicts ---------------------------------------------
    pending_sources = {
        fold(entry.original_name): entry
        for entry in plan.entries
        if entry.will_rename and entry.status is EntryStatus.READY
    }
    for entry in plan.entries:
        if entry.status is not EntryStatus.READY or not entry.changed:
            continue
        target = entry.target
        if not path_exists(target):
            continue
        if same_file(entry.source, target):
            # Case-only rename of the very same file.
            continue
        holder = pending_sources.get(fold(entry.target_name))
        if holder is not None and holder is not entry and holder.source != entry.source:
            # The occupant is part of this batch and moves away: safe, the
            # executor resolves it with an intermediate name.
            entry.warnings.append(
                f"'{entry.target_name}' is currently used by '{holder.original_name}', "
                "which this session renames as well"
            )
            continue
        if options.overwrite:
            entry.warnings.append(
                f"'{entry.target_name}' already exists and will be moved to a backup name"
            )
            continue
        entry.status = EntryStatus.EXISTS
        entry.message = f"'{entry.target_name}' already exists in {entry.source.parent}"

    # --- lock in unchanged/blocked entries ---------------------------------
    for entry in plan.entries:
        if entry.status is EntryStatus.READY and not entry.changed and options.allow_unchanged:
            entry.status = EntryStatus.UNCHANGED
            entry.message = "the name is already what the operations produce"

    # --- informational notes ------------------------------------------------
    if options.warn_extension_change:
        extension_ops = [
            operation for operation in operations_payload
            if operation.get("type") == "extension"
        ]
        for payload in extension_ops:
            if payload.get("new_extension") or payload.get("remove"):
                plan.notes.append(
                    "Changing or removing an extension renames the file only - "
                    "it never converts the file's contents."
                )
                break
    if options.note:
        plan.notes.append(options.note)
    if options.overwrite:
        plan.notes.append(
            "Overwrite mode is on: files that already occupy a target name are moved to a "
            f"'{'.ezrename-backup.'}<token>-<name>' file next to them, never deleted."
        )
    if options.warn_path_length:
        long_paths = [
            entry for entry in plan.entries if path_length_risk(entry.target)
        ]
        if long_paths:
            plan.notes.append(
                f"{len(long_paths)} target path(s) exceed the legacy 260 character Windows "
                "limit; enable long path support or shorten names if a rename fails."
            )
    return plan


def build_plan(
    items: Iterable[FileLike],
    operations: Sequence[Operation],
    options: Optional[PlanOptions] = None,
    *,
    root: Optional[Path] = None,
    prefix: str = "",
    suffix: str = "",
) -> RenamePlan:
    """Build a validated plan for *items* using *operations*.

    The order of *items* is significant: sequential numbering follows it.
    """

    options = options or PlanOptions()
    operations = list(operations)

    problems = []
    for operation in operations:
        try:
            operation.validate()
        except OperationError as exc:
            problems.append(f"{operation.label}: {exc}")
    if problems:
        return RenamePlan(
            root=root,
            operations=[op.to_dict() for op in operations],
            errors=problems,
        )

    candidates: list[tuple[FileRecord, str, EntryStatus, str, list[str]]] = []
    records = [_as_record(item) for item in items]
    for index, record in enumerate(records):
        warnings: list[str] = []
        if record.error:
            candidates.append((record, record.name, EntryStatus.SKIPPED, record.error, warnings))
            continue
        if is_internal_name(record.name):
            candidates.append(
                (
                    record,
                    record.name,
                    EntryStatus.SKIPPED,
                    "temporary file created by an interrupted EzRename session",
                    warnings,
                )
            )
            continue
        ctx = NameContext.from_name(
            record.name,
            index=index,
            path=record.path,
            size=record.size,
            mtime=record.mtime,
            ctime=record.ctime,
            atime=getattr(record, "atime", 0.0),
        )
        ctx.prefix, ctx.suffix = prefix, suffix
        failure: Optional[FileOperationError] = None
        for operation in operations:
            try:
                operation.apply(ctx)
            except FileOperationError as exc:
                failure = exc
                break
            except OperationError as exc:  # pragma: no cover - guarded above
                failure = FileOperationError(str(exc))
                break
        if failure is not None:
            status = EntryStatus.SKIPPED if failure.skip else EntryStatus.ERROR
            candidates.append((record, record.name, status, failure.message, warnings))
            continue
        target_name = ctx.name
        problem = validate_filename(target_name, max_length=options.max_name_length)
        if problem:
            candidates.append((record, target_name, EntryStatus.INVALID, problem, warnings))
            continue
        if target_name in ("", ".", ".."):
            candidates.append(
                (record, target_name, EntryStatus.INVALID, "the result is not a valid file name", warnings)
            )
            continue
        candidates.append((record, target_name, EntryStatus.READY, "", warnings))

    return _finalise(
        candidates,
        options,
        root=root,
        operations_payload=[op.to_dict() for op in operations],
        notes=[],
        errors=[],
    )


def plan_from_targets(
    pairs: Sequence[tuple[Union[Path, FileRecord], str]],
    options: Optional[PlanOptions] = None,
    *,
    root: Optional[Path] = None,
    operations_payload: Optional[list[dict]] = None,
    notes: Optional[Sequence[str]] = None,
) -> RenamePlan:
    """Build a plan from explicit ``(current path, desired name)`` pairs.

    Used by undo, where the desired name is known directly rather than
    produced by operations.
    """

    options = options or PlanOptions()
    candidates: list[tuple[FileRecord, str, EntryStatus, str, list[str]]] = []
    for item, target_name in pairs:
        record = _as_record(item)
        problem = validate_filename(target_name, max_length=options.max_name_length)
        if problem:
            candidates.append((record, target_name, EntryStatus.INVALID, problem, []))
        else:
            candidates.append((record, target_name, EntryStatus.READY, "", []))
    return _finalise(
        candidates,
        options,
        root=root,
        operations_payload=list(operations_payload or []),
        notes=list(notes or []),
        errors=[],
    )
