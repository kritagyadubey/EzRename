"""Tests for the safe executor: dry runs, swaps, rollbacks and quarantine."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from conftest import make_files, records_for

from ezrename.core.engine import EngineOptions, RenameEngine
from ezrename.core.models import EntryStatus
from ezrename.core.operations import CaseConvert, FindReplace, Numbering
from ezrename.core.pipeline import PlanOptions, build_plan, plan_from_targets


def plan_for(folder: Path, operations, **options):
    return build_plan(records_for(folder), operations, PlanOptions(**options))


def test_simple_rename_is_applied(folder: Path, names):
    make_files(folder, ["IMG_1.jpg", "IMG_2.jpg"])
    plan = plan_for(folder, [FindReplace(find="IMG_", replace="Photo_")])
    result = RenameEngine().execute(plan)
    assert result.succeeded
    assert names() == ["Photo_1.jpg", "Photo_2.jpg"]
    assert len(result.renamed) == 2


def test_dry_run_changes_nothing(folder: Path, names):
    make_files(folder, ["IMG_1.jpg"])
    plan = plan_for(folder, [FindReplace(find="IMG_", replace="Photo_")])
    result = RenameEngine().execute(plan, dry_run=True)
    assert names() == ["IMG_1.jpg"]
    assert result.dry_run
    assert not result.changed_filesystem
    assert result.outcomes[0].status is EntryStatus.PLANNED
    assert result.renamed == []


def test_swap_of_two_files_uses_intermediate_names(folder: Path, names):
    make_files(folder, ["one.txt", "two.txt"])
    plan = plan_from_targets(
        [(folder / "one.txt", "two.txt"), (folder / "two.txt", "one.txt")]
    )
    result = RenameEngine().execute(plan)
    assert result.succeeded
    assert (folder / "one.txt").read_text().endswith("two.txt")
    assert (folder / "two.txt").read_text().endswith("one.txt")
    assert sorted(path.name for path in folder.iterdir()) == ["one.txt", "two.txt"]
    assert not [path for path in folder.iterdir() if path.name.startswith(".ezrename-tmp.")]


def test_three_way_cycle_is_resolved(folder: Path):
    make_files(folder, ["a.txt", "b.txt", "c.txt"])
    plan = plan_from_targets(
        [
            (folder / "a.txt", "b.txt"),
            (folder / "b.txt", "c.txt"),
            (folder / "c.txt", "a.txt"),
        ]
    )
    result = RenameEngine().execute(plan)
    assert result.succeeded
    assert (folder / "b.txt").read_text().endswith("a.txt")
    assert (folder / "c.txt").read_text().endswith("b.txt")
    assert (folder / "a.txt").read_text().endswith("c.txt")


def test_numbering_swap_via_reverse_sort(folder: Path):
    """Reversing the order plus numbering replaces 1.txt<->2.txt."""

    make_files(folder, ["1.txt", "2.txt"])
    records = records_for(folder)[::-1]
    plan = build_plan(
        records, [Numbering(start=1, step=1, padding=1, position="replace")]
    )
    assert plan.is_valid
    result = RenameEngine().execute(plan)
    assert result.succeeded
    assert (folder / "1.txt").read_text().endswith("2.txt")
    assert (folder / "2.txt").read_text().endswith("1.txt")


def test_case_only_rename_works(folder: Path, names):
    make_files(folder, ["photo.jpg"])
    plan = plan_for(folder, [CaseConvert(mode="upper", scope="stem")])
    assert plan.entries[0].status is EntryStatus.READY
    result = RenameEngine().execute(plan)
    assert result.succeeded
    assert names() == ["PHOTO.jpg"]


def test_existing_destination_is_never_overwritten(folder: Path, names):
    make_files(folder, ["keep.txt"])
    (folder / "1.txt").write_text("source")
    plan = build_plan(
        [record for record in records_for(folder) if record.name == "1.txt"],
        [FindReplace(find="1", replace="keep", scope="full")],
    )
    assert plan.entries[0].status is EntryStatus.EXISTS
    result = RenameEngine().execute(plan)
    assert names() == ["1.txt", "keep.txt"]
    assert result.renamed == []


def test_destination_created_after_preview_blocks_safely(folder: Path, names):
    make_files(folder, ["a.txt"])
    plan = plan_for(folder, [FindReplace(find="a", replace="b", scope="full")])
    (folder / "b.txt").write_text("sneaky")
    result = RenameEngine().execute(plan)
    assert not result.renamed
    assert result.failed
    assert "appeared at the destination" in result.failed[0].message
    assert (folder / "b.txt").read_text() == "sneaky"
    assert (folder / "a.txt").exists()


def test_overwrite_mode_quarantines_instead_of_deleting(folder: Path, names):
    make_files(folder, ["a.txt"])
    (folder / "b.txt").write_text("existing content")
    plan = plan_for(
        folder, [FindReplace(find="a", replace="b", scope="full")], overwrite=True
    )
    result = RenameEngine().execute(plan, overwrite=True)
    assert result.succeeded
    backups = [name for name in names() if name.startswith(".ezrename-backup.")]
    assert len(backups) == 1
    assert (folder / backups[0]).read_text() == "existing content"
    assert (folder / "b.txt").read_text().endswith("a.txt")
    assert result.renamed[0].backup is not None


def test_failure_is_rolled_back_and_reported(folder: Path, names, monkeypatch):
    make_files(folder, ["a.txt", "b.txt"])
    plan = plan_for(folder, [Numbering(start=1, padding=1, position="replace")])
    real_rename = os.rename

    def flaky(source, target, *args, **kwargs):
        # Fail only for b.txt -> 2.txt so the test cannot be disturbed by
        # unrelated os.rename calls made by the test runner itself.
        if Path(source).name == "b.txt" and Path(target).name == "2.txt":
            raise PermissionError(13, "Access is denied")
        return real_rename(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "rename", flaky)
    try:
        result = RenameEngine().execute(plan)
    finally:
        monkeypatch.undo()

    assert result.failed, result.outcomes
    assert result.failed[0].status is EntryStatus.FAILED
    assert "1.txt" in names(), "the file that could be renamed stays renamed"
    assert "b.txt" in names(), "the failing file keeps its original name"
    assert not [name for name in names() if name.startswith(".ezrename-tmp.")]


def test_temp_file_is_restored_when_second_phase_fails(folder: Path, names, monkeypatch):
    make_files(folder, ["one.txt", "two.txt"])
    plan = plan_from_targets(
        [(folder / "one.txt", "two.txt"), (folder / "two.txt", "one.txt")]
    )
    real_rename = os.rename
    state = {"fail": True}

    def flaky(source, target, *args, **kwargs):
        # Fail the swap exactly once; the rollback that follows must succeed.
        if state["fail"] and Path(target).name == "one.txt":
            state["fail"] = False
            raise OSError(13, "Access is denied")
        return real_rename(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "rename", flaky)
    try:
        result = RenameEngine().execute(plan)
    finally:
        monkeypatch.undo()

    remaining = sorted(path.name for path in folder.iterdir())
    assert remaining == ["one.txt", "two.txt"], remaining
    assert (folder / "one.txt").read_text().endswith("one.txt")
    assert (folder / "two.txt").read_text().endswith("two.txt")
    assert result.failed, result.outcomes
    assert not result.rollback_failures
    statuses = {outcome.status for outcome in result.outcomes}
    assert EntryStatus.ROLLED_BACK in statuses or EntryStatus.FAILED in statuses


def test_cancellation_stops_and_leaves_files_consistent(folder: Path, names):
    make_files(folder, [f"file{i}.txt" for i in range(6)])
    plan = plan_for(folder, [Numbering(position="prefix", padding=2)])
    calls = {"count": 0}

    def cancel() -> bool:
        calls["count"] += 1
        return calls["count"] > 3

    result = RenameEngine().execute(plan, cancel=cancel)
    assert result.cancelled
    assert not result.rollback_failures
    assert not [name for name in names() if name.startswith(".ezrename-tmp.")]
    # Every original name must still be present in some form.
    assert len(names()) == 6


def test_progress_callback_reports_every_entry(folder: Path):
    make_files(folder, ["a.txt", "b.txt", "c.txt"])
    plan = plan_for(folder, [Numbering(position="prefix", padding=1)])
    seen: list[tuple[int, int]] = []
    RenameEngine().execute(plan, progress=lambda done, total, _outcome: seen.append((done, total)))
    assert seen[-1] == (3, 3)


def test_engine_reports_unchanged_and_skipped_entries(folder: Path):
    make_files(folder, ["a.txt"])
    plan = build_plan(records_for(folder), [FindReplace(find="nothing", replace="")])
    result = RenameEngine().execute(plan)
    assert [outcome.status for outcome in result.outcomes] == [EntryStatus.UNCHANGED]
    assert result.summary()["skipped"] == 1


@pytest.mark.skipif(os.name != "nt", reason="read-only attribute is Windows specific")
def test_read_only_file_failure_is_reported_and_rolled_back(folder: Path, names):
    make_files(folder, ["locked.txt"])
    target = folder / "locked.txt"
    os.chmod(target, stat.S_IREAD)
    try:
        plan = plan_for(folder, [FindReplace(find="locked", replace="renamed", scope="full")])
        # A rename of a read-only file is allowed on NTFS; the test documents the
        # behaviour instead of assuming a failure.
        result = RenameEngine().execute(plan)
        assert result.succeeded or result.failed
        assert names() == (["renamed.txt"] if result.succeeded else ["locked.txt"])
    finally:
        for candidate in (target, folder / "renamed.txt"):
            if candidate.exists():
                os.chmod(candidate, stat.S_IWRITE | stat.S_IREAD)


def test_execute_with_no_pending_entries(folder: Path):
    make_files(folder, ["same.txt"])
    plan = plan_for(folder, [FindReplace(find="nothing", replace="")])
    result = RenameEngine().execute(plan)
    assert result.renamed == []
    assert result.outcomes[0].status is EntryStatus.UNCHANGED


def test_engine_options_defaults_are_safe():
    options = EngineOptions()
    assert options.overwrite is False
    assert options.dry_run is False


def test_session_ids_are_unique():
    from ezrename.core.engine import new_session_id

    ids = {new_session_id() for _ in range(20)}
    assert len(ids) == 20
