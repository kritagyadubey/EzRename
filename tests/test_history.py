"""Tests for persistent history, undo verification and manifest export."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest
from conftest import make_files, records_for

from ezrename.core.engine import RenameEngine
from ezrename.core.history import HistoryStore
from ezrename.core.models import EntryStatus
from ezrename.core.operations import CaseConvert, Numbering, PrefixSuffix
from ezrename.core.pipeline import PlanOptions, build_plan


def rename(folder: Path, operations, store: HistoryStore | None = None, **options):
    plan = build_plan(records_for(folder), operations, PlanOptions(**options))
    result = RenameEngine().execute(plan)
    if store is not None:
        store.record(result)
    return result


def test_session_is_recorded_and_listed(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt", "b.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    sessions = history.list_sessions()
    assert [session.id for session in sessions] == [result.session_id]
    session = sessions[0]
    assert session.renamed == 2
    assert session.undoable
    assert session.status_label == "completed"
    assert session.operations[0]["type"] == "prefix_suffix"


def test_dry_runs_are_not_recorded(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt"])
    plan = build_plan(records_for(folder), [PrefixSuffix(prefix="x_")])
    result = RenameEngine().execute(plan, dry_run=True)
    assert history.record(result) is None
    assert history.list_sessions() == []


def test_history_survives_a_restart(folder: Path, history: HistoryStore, tmp_path: Path):
    make_files(folder, ["a.txt"])
    rename(folder, [PrefixSuffix(prefix="x_")], history)
    path = history.path
    history.close()

    reopened = HistoryStore(path)
    try:
        sessions = reopened.list_sessions()
        assert len(sessions) == 1
        assert reopened.session_entries(sessions[0].id)[0]["target_name"] == "x_a.txt"
    finally:
        reopened.close()


def test_undo_restores_names(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt", "b.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    assert sorted(path.name for path in folder.iterdir()) == ["x_a.txt", "x_b.txt"]

    report = history.verify(result.session_id)
    assert report.can_undo_all
    assert len(report.safe) == 2

    undo = history.undo(result.session_id)
    assert undo.ok, undo.message
    assert sorted(path.name for path in folder.iterdir()) == ["a.txt", "b.txt"]
    assert history.get_session(result.session_id).undone_at is not None


def test_undo_of_a_case_only_rename(folder: Path, history: HistoryStore):
    make_files(folder, ["Photo.JPG"])
    result = rename(folder, [CaseConvert(mode="lower", scope="stem")], history)
    assert sorted(path.name for path in folder.iterdir()) == ["photo.JPG"]
    undo = history.undo(result.session_id)
    assert undo.ok
    assert sorted(path.name for path in folder.iterdir()) == ["Photo.JPG"]


def test_undo_refuses_when_a_file_moved_away(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt", "b.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    (folder / "x_a.txt").rename(folder / "somewhere-else.txt")

    report = history.verify(result.session_id)
    assert not report.can_undo_all
    assert len(report.unsafe) == 1
    assert "no longer at this location" in report.unsafe[0].reason

    undo = history.undo(result.session_id)
    assert not undo.ok
    assert "nothing was changed" in undo.message.lower()
    assert (folder / "x_b.txt").exists()


def test_undo_partial_requires_permission(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt", "b.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    (folder / "x_a.txt").rename(folder / "gone.txt")

    refused = history.undo(result.session_id)
    assert not refused.ok and refused.partial

    allowed = history.undo(result.session_id, allow_partial=True)
    assert allowed.ok and allowed.partial
    assert (folder / "b.txt").exists()
    assert (folder / "x_b.txt").exists() is False


def test_undo_is_blocked_when_original_name_is_occupied(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    (folder / "a.txt").write_text("a different file")

    report = history.verify(result.session_id)
    assert not report.can_undo_anything
    undo = history.undo(result.session_id)
    assert not undo.ok
    assert (folder / "a.txt").read_text() == "a different file"
    assert (folder / "x_a.txt").exists()


def test_undo_twice_is_refused(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    assert history.undo(result.session_id).ok
    again = history.undo(result.session_id)
    assert not again.ok
    assert "already undone" in again.message


def test_undo_dry_run_changes_nothing(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    dry = history.undo(result.session_id, dry_run=True)
    assert dry.ok and dry.execution.dry_run
    assert (folder / "x_a.txt").exists()


def test_undo_records_its_own_session(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    history.undo(result.session_id)
    sessions = history.list_sessions()
    kinds = {session.kind for session in sessions}
    assert kinds == {"rename", "undo"}
    assert all(session.renamed == 1 for session in sessions)


def test_verification_warns_when_a_file_changed(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt"], content="short")
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    (folder / "x_a.txt").write_text("much longer content than before")
    report = history.verify(result.session_id)
    assert report.can_undo_all
    assert any(check.warning for check in report.safe)


def test_verify_unknown_session_is_reported(history: HistoryStore):
    report = history.verify("does-not-exist")
    assert report.blockers and not report.can_undo_all


def test_latest_undoable_skips_undone_sessions(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt"])
    first = rename(folder, [PrefixSuffix(prefix="x_")], history)
    second = rename(folder, [PrefixSuffix(prefix="y_")], history)
    history.undo(second.session_id)
    latest = history.latest_undoable()
    assert latest.id == first.session_id


def test_stats(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt", "b.txt"])
    rename(folder, [PrefixSuffix(prefix="x_")], history)
    stats = history.stats()
    assert stats["sessions"] == 1
    assert stats["renamed"] == 2
    assert stats["last_session"]


def test_export_json_and_csv(folder: Path, history: HistoryStore, tmp_path: Path):
    make_files(folder, ["a.txt", "b.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)

    manifest = history.export(result.session_id, tmp_path / "session.json", "json")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["id"] == result.session_id
    assert len(payload["entries"]) == 2
    assert payload["entries"][0]["target_name"] == "x_a.txt"

    sheet = history.export(result.session_id, tmp_path / "session.csv", "csv")
    with sheet.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["target_name"] == "x_a.txt"
    assert rows[0]["status"] == "renamed"


def test_export_rejects_unknown_format(folder: Path, history: HistoryStore, tmp_path: Path):
    make_files(folder, ["a.txt"])
    result = rename(folder, [PrefixSuffix(prefix="x_")], history)
    with pytest.raises(ValueError):
        history.export(result.session_id, tmp_path / "x.yml", "yml")


def test_delete_and_prune(folder: Path, history: HistoryStore):
    make_files(folder, ["a.txt"])
    for index in range(4):
        rename(folder, [PrefixSuffix(prefix=f"{index}_")], history)
    assert len(history.list_sessions()) == 4
    assert history.prune(keep=2) == 2
    remaining = history.list_sessions()
    assert len(remaining) == 2
    assert history.delete(remaining[0].id)
    assert len(history.list_sessions()) == 1


def test_partial_failure_is_recorded_with_real_state(folder: Path, history: HistoryStore, monkeypatch):
    make_files(folder, ["a.txt", "b.txt"])
    plan = build_plan(records_for(folder), [Numbering(position="replace", padding=1)])
    real_rename = os.rename

    def flaky(source, target, *args, **kwargs):
        if Path(source).name == "b.txt":
            raise PermissionError(13, "Access is denied")
        return real_rename(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "rename", flaky)
    try:
        result = RenameEngine().execute(plan)
    finally:
        monkeypatch.undo()
    history.record(result)

    session = history.get_session(result.session_id)
    assert session.failed == 1
    assert session.renamed == 1
    assert session.status_label == "completed with errors"
    entries = {row["original_name"]: row["status"] for row in history.session_entries(result.session_id)}
    assert entries["a.txt"] == EntryStatus.RENAMED.value
    assert entries["b.txt"] == EntryStatus.FAILED.value

    report = history.verify(result.session_id)
    assert len(report.safe) == 1  # only the file that really moved can be undone
