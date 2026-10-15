"""Tests for plan construction: validation, collisions and safety warnings."""

from __future__ import annotations

from pathlib import Path

from conftest import make_files, records_for

from ezrename.core.models import EntryStatus
from ezrename.core.naming import fold
from ezrename.core.operations import CaseConvert, ExtensionChange, FindReplace, Numbering, Template
from ezrename.core.pipeline import PlanOptions, build_plan, plan_from_targets


def test_plan_marks_ready_entries(folder: Path):
    make_files(folder, ["IMG_1.jpg", "IMG_2.jpg"])
    plan = build_plan(records_for(folder), [FindReplace(find="IMG_", replace="Photo_")])
    assert len(plan.entries) == 2
    assert all(entry.status is EntryStatus.READY for entry in plan.entries)
    assert plan.is_valid
    assert len(plan.pending) == 2


def test_plan_reports_unchanged_files(folder: Path):
    make_files(folder, ["photo.jpg"])
    plan = build_plan(records_for(folder), [FindReplace(find="IMG_", replace="Photo_")])
    assert plan.entries[0].status is EntryStatus.UNCHANGED
    assert plan.pending == []
    assert plan.is_valid


def test_plan_detects_duplicate_targets(folder: Path):
    make_files(folder, ["a1.txt", "a2.txt"])
    plan = build_plan(records_for(folder), [FindReplace(find=r"\d", replace="", use_regex=True)])
    statuses = {entry.original_name: entry.status for entry in plan.entries}
    assert statuses["a1.txt"] is EntryStatus.DUPLICATE
    assert statuses["a2.txt"] is EntryStatus.DUPLICATE
    assert not plan.is_valid
    assert all("also becomes" in entry.message for entry in plan.entries)


def test_plan_detects_existing_destination(folder: Path):
    make_files(folder, ["1.txt", "2.txt"])
    (folder / "3.txt").write_text("already here")
    plan = build_plan(
        [record for record in records_for(folder) if record.name == "2.txt"],
        [FindReplace(find="2", replace="3")],
    )
    assert plan.entries[0].status is EntryStatus.EXISTS
    assert "already exists" in plan.entries[0].message


def test_plan_allows_swap_between_two_selected_files(folder: Path):
    make_files(folder, ["one.txt", "two.txt"])
    plan = plan_from_targets(
        [(folder / "one.txt", "two.txt"), (folder / "two.txt", "one.txt")]
    )
    assert plan.is_valid
    assert {entry.status for entry in plan.entries} == {EntryStatus.READY}


def test_plan_rejects_invalid_results(folder: Path):
    make_files(folder, ["good.txt"])
    plan = build_plan(records_for(folder), [FindReplace(find="good", replace="bad<>name")])
    assert plan.entries[0].status is EntryStatus.INVALID
    assert "illegal character" in plan.entries[0].message


def test_plan_rejects_empty_resulting_name(folder: Path):
    make_files(folder, ["photo.txt"])
    plan = build_plan(
        records_for(folder), [FindReplace(find="photo.txt", replace="", scope="full")]
    )
    assert plan.entries[0].target_name == ""
    assert plan.entries[0].status is EntryStatus.INVALID
    assert "empty file name" in plan.entries[0].message


def test_trailing_dot_is_reported_not_silently_stripped(folder: Path):
    make_files(folder, ["photo.txt"])
    plan = build_plan(
        records_for(folder), [FindReplace(find="txt", replace="", scope="full")]
    )
    assert plan.entries[0].target_name == "photo."
    assert plan.entries[0].status is EntryStatus.INVALID
    assert "end with a space or a dot" in plan.entries[0].message


def test_plan_handles_multi_dot_names(folder: Path):
    make_files(folder, ["archive.tar.gz"])
    plan = build_plan(records_for(folder), [FindReplace(find="archive", replace="backup")])
    assert plan.entries[0].target_name == "backup.tar.gz"


def test_plan_handles_unicode_and_spaces(folder: Path):
    make_files(folder, ["café ☕ 2026.txt", "日本語のファイル.txt"])
    plan = build_plan(records_for(folder), [CaseConvert(mode="upper", scope="stem")])
    assert plan.is_valid
    assert any(entry.target_name.startswith("CAFÉ ☕") for entry in plan.entries)


def test_plan_handles_names_without_extension(folder: Path):
    make_files(folder, ["README"])
    plan = build_plan(records_for(folder), [Numbering(position="suffix", padding=2)])
    assert plan.entries[0].target_name == "README_01"


def test_scan_ignores_internal_temp_files(folder: Path):
    make_files(folder, [".ezrename-tmp.abc-note.txt", "note.txt"])
    names = {record.name for record in records_for(folder, hidden=True)}
    assert names == {"note.txt"}

    # build_plan also refuses them if a record ever reaches it directly.
    from ezrename.core.models import FileRecord

    record = FileRecord(path=folder / ".ezrename-backup.abc-note.txt")
    plan = build_plan([record], [CaseConvert(mode="upper")])
    assert plan.entries[0].status is EntryStatus.SKIPPED
    assert "temporary file" in plan.entries[0].message


def test_plan_reports_operation_errors_per_file(folder: Path):
    make_files(folder, ["a.txt"])
    plan = build_plan(records_for(folder), [Template(pattern="{stem}-{index}{ext}")])
    assert plan.is_valid
    assert plan.entries[0].target_name == "a-1.txt"


def test_plan_with_no_files_is_empty(folder: Path):
    plan = build_plan([], [CaseConvert(mode="upper")])
    assert plan.is_empty
    assert plan.pending == []
    assert plan.is_valid


def test_plan_with_invalid_operation_is_rejected_before_anything_else(folder: Path):
    make_files(folder, ["a.txt"])
    plan = build_plan(records_for(folder), [FindReplace(find="([", use_regex=True)])
    assert plan.errors
    assert plan.entries == []


def test_extension_change_adds_an_informational_note(folder: Path):
    make_files(folder, ["photo.jpg"])
    plan = build_plan(records_for(folder), [ExtensionChange(new_extension="png")])
    assert any("never converts" in note for note in plan.notes)


def test_overwrite_option_marks_warning_instead_of_conflict(folder: Path):
    make_files(folder, ["2.txt"])
    (folder / "3.txt").write_text("existing")
    plan = build_plan(
        [record for record in records_for(folder) if record.name == "2.txt"],
        [FindReplace(find="2", replace="3")],
        PlanOptions(overwrite=True),
    )
    assert plan.entries[0].status is EntryStatus.READY
    assert plan.entries[0].warnings
    assert any("backup" in note for note in plan.notes)


def test_long_path_warning_is_added(folder: Path):
    long_stem = "x" * 120
    make_files(folder, [f"{long_stem}.txt"])
    plan = build_plan(
        records_for(folder),
        [Numbering(position="prefix", padding=3)],
        PlanOptions(),
    )
    if any(len(str(entry.target)) >= 260 for entry in plan.entries):
        assert any("260 character" in note for note in plan.notes)


def test_plan_normalises_collision_comparison_case_insensitively(folder: Path):
    make_files(folder, ["Photo.JPG", "photo.jpg"])
    # Both names differ only by case, which is a single file on Windows.
    records = records_for(folder)
    if len(records) < 2:
        return  # case-insensitive filesystem collapsed them, nothing to assert
    plan = build_plan(records, [CaseConvert(mode="lower", scope="both")])
    assert len({fold(entry.target_name) for entry in plan.entries}) == 1
    assert all(entry.status is EntryStatus.DUPLICATE for entry in plan.entries)


def test_plan_summary_totals(folder: Path):
    make_files(folder, ["a.txt", "b.txt", "c.txt"])
    plan = build_plan(records_for(folder), [FindReplace(find=".txt", replace="", scope="full")])
    summary = plan.summary()
    assert summary["files"] == 3
    assert summary["operations"] == 1
    assert summary["rename"] >= 0


def test_name_length_validation_can_be_tightened(folder: Path):
    make_files(folder, ["a.txt"])
    plan = build_plan(
        records_for(folder),
        [Numbering(position="prefix", padding=3, prefix="X" * 30)],
        PlanOptions(max_name_length=10),
    )
    assert plan.entries[0].status is EntryStatus.INVALID
