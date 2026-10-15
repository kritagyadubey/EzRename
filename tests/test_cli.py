"""End-to-end tests for the command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_files

from ezrename.cli.main import EXIT_BLOCKED, EXIT_FAILED, EXIT_NOTHING, EXIT_OK, EXIT_USAGE, main


def run(capsys, *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


# --------------------------------------------------------------------------- #
# basics
# --------------------------------------------------------------------------- #


def test_version_and_help(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    output = capsys.readouterr().out
    assert "ezrename rename" in output
    assert "exit codes" in output


def test_subcommand_help(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["rename", "--help"])
    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "--dry-run" in output and "--overwrite" in output


def test_no_command_prints_help(capsys):
    code, output = run(capsys)
    assert code == EXIT_OK
    assert "COMMAND" in output


def test_ops_lists_operations_and_template_variables(capsys):
    code, output = run(capsys, "ops", "--no-color")
    assert code == EXIT_OK
    assert "Find and replace" in output
    assert "{stem}" in output


def test_template_variables_flag(capsys):
    code, output = run(capsys, "preview", ".", "--template-variables", "--no-color")
    assert code == EXIT_OK
    assert "index" in output


def test_config_command(capsys, isolated_home: Path):
    code, output = run(capsys, "config", "--path")
    assert code == EXIT_OK
    assert str(isolated_home) in output


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def test_list_files(capsys, folder: Path):
    make_files(folder, ["a.txt", "b.txt"])
    code, output = run(capsys, "list", str(folder), "--no-color")
    assert code == EXIT_OK
    assert "a.txt" in output and "2 file(s)" in output


def test_list_empty_folder_returns_nothing_to_do(capsys, folder: Path):
    code, output = run(capsys, "list", str(folder), "--no-color")
    assert code == EXIT_NOTHING


def test_list_json(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    code, output = run(capsys, "list", str(folder), "--json")
    assert code == EXIT_OK
    payload = json.loads(output)
    assert payload["count"] == 1
    assert payload["files"][0]["name"] == "a.txt"


def test_missing_path_is_a_usage_error(capsys, folder: Path):
    code, output = run(capsys, "list", str(folder / "nope"), "--no-color")
    assert code == EXIT_USAGE
    assert "does not exist" in output


def test_path_with_spaces_and_unicode(capsys, tmp_path: Path):
    tricky = tmp_path / "holiday photos café"
    tricky.mkdir()
    make_files(tricky, ["réunion 2026.jpg"])
    code, output = run(capsys, "list", str(tricky), "--no-color")
    assert code == EXIT_OK
    assert "réunion 2026.jpg" in output


# --------------------------------------------------------------------------- #
# preview
# --------------------------------------------------------------------------- #


def test_preview_shows_plan_without_changing_files(capsys, folder: Path):
    make_files(folder, ["IMG_1.jpg"])
    code, output = run(capsys, "preview", str(folder), "--prefix", "Vacation_", "--no-color")
    assert code == EXIT_OK
    assert "Vacation_IMG_1.jpg" in output
    assert names(folder) == ["IMG_1.jpg"]


def test_preview_without_operations_is_a_usage_error(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    code, output = run(capsys, "preview", str(folder), "--no-color")
    assert code == EXIT_USAGE
    assert "no rename operation" in output


def test_preview_json(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    code, output = run(capsys, "preview", str(folder), "--case", "upper", "--json")
    payload = json.loads(output)
    assert payload["summary"]["rename"] == 1
    assert payload["entries"][0]["target_name"] == "A.txt"


def test_preview_reports_duplicates_with_exit_code(capsys, folder: Path):
    make_files(folder, ["a1.txt", "a2.txt"])
    code, output = run(capsys, "preview", str(folder), "--find", "1", "--replace", "2", "--no-color")
    assert code == EXIT_BLOCKED
    assert "duplicate" in output.lower()


def test_preview_invalid_regex_is_a_usage_error(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    code, output = run(capsys, "preview", str(folder), "--find", "([", "--regex", "--no-color")
    assert code == EXIT_USAGE
    assert "regular expression" in output


# --------------------------------------------------------------------------- #
# rename
# --------------------------------------------------------------------------- #


def test_rename_applies_with_yes(capsys, folder: Path):
    make_files(folder, ["IMG_1.jpg", "IMG_2.jpg"])
    code, output = run(
        capsys, "rename", str(folder), "--find", "IMG_", "--replace", "Photo_", "--yes", "--no-color"
    )
    assert code == EXIT_OK
    assert names(folder) == ["Photo_1.jpg", "Photo_2.jpg"]
    assert "renamed" in output


def test_rename_without_yes_in_a_non_tty_refuses(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    code, output = run(capsys, "rename", str(folder), "--case", "upper", "--no-color")
    assert code == EXIT_USAGE
    assert names(folder) == ["a.txt"]
    assert "cancelled" in output


def test_rename_accepts_ezrename_assume_yes(capsys, folder: Path, monkeypatch):
    make_files(folder, ["a.txt"])
    monkeypatch.setenv("EZRENAME_ASSUME_YES", "1")
    code, _ = run(capsys, "rename", str(folder), "--case", "upper", "--no-color")
    assert code == EXIT_OK
    assert names(folder) == ["A.txt"]


def test_dry_run_changes_nothing(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    code, output = run(
        capsys, "rename", str(folder), "--case", "upper", "--dry-run", "--no-color"
    )
    assert code == EXIT_OK
    assert names(folder) == ["a.txt"]
    assert "would be renamed" in output


def test_rename_nothing_to_do(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    code, output = run(capsys, "rename", str(folder), "--case", "lower", "--yes", "--no-color")
    assert code == EXIT_NOTHING


def test_rename_conflicts_block_with_exit_code_3(capsys, folder: Path):
    make_files(folder, ["a1.txt", "a2.txt"])
    code, output = run(
        capsys, "rename", str(folder), "--find", "1", "--replace", "2", "--yes", "--no-color"
    )
    assert code == EXIT_BLOCKED
    assert names(folder) == ["a1.txt", "a2.txt"]


def test_rename_never_overwrites_existing_file(capsys, folder: Path):
    make_files(folder, ["1.txt"])
    (folder / "2.txt").write_text("protected")
    code, output = run(
        capsys, "rename", str(folder / "1.txt"), "--find", "1", "--replace", "2", "--yes", "--no-color"
    )
    assert code == EXIT_BLOCKED
    assert (folder / "2.txt").read_text() == "protected"


def test_rename_overwrite_mode_keeps_a_backup(capsys, folder: Path):
    make_files(folder, ["1.txt"])
    (folder / "2.txt").write_text("protected")
    code, output = run(
        capsys,
        "rename",
        str(folder / "1.txt"),
        "--find",
        "1",
        "--replace",
        "2",
        "--overwrite",
        "--yes",
        "--no-color",
    )
    assert code == EXIT_OK
    backups = [name for name in names(folder) if name.startswith(".ezrename-backup.")]
    assert len(backups) == 1
    assert (folder / backups[0]).read_text() == "protected"


def test_rename_json_output(capsys, folder: Path):
    make_files(folder, ["a.txt", "b.txt"])
    code, output = run(capsys, "rename", str(folder), "--case", "upper", "--yes", "--json")
    assert code == EXIT_OK
    payload = json.loads(output)
    assert payload["summary"]["renamed"] == 2
    assert payload["entries"][0]["status"] == "renamed"


def test_rename_recursive_and_extension_filter(capsys, folder: Path):
    make_files(folder, ["top.jpg"])
    make_files(folder / "deep", ["inner.jpg", "ignored.txt"])
    code, _ = run(
        capsys,
        "rename",
        str(folder),
        "--recursive",
        "--ext",
        "jpg",
        "--prefix",
        "p-",
        "--yes",
        "--no-color",
    )
    assert code == EXIT_OK
    assert (folder / "p-top.jpg").exists()
    assert (folder / "deep" / "p-inner.jpg").exists()
    assert (folder / "deep" / "ignored.txt").exists()


def test_rename_with_quiet_and_no_color(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    code, output = run(
        capsys, "rename", str(folder), "--case", "upper", "--yes", "--quiet", "--no-color"
    )
    assert code == EXIT_OK
    assert "\x1b[" not in output


def test_rename_sort_and_number(capsys, folder: Path):
    make_files(folder, ["b.txt", "a.txt"])
    code, _ = run(
        capsys,
        "rename",
        str(folder),
        "--number",
        "--start",
        "1",
        "--padding",
        "2",
        "--number-position",
        "prefix",
        "--yes",
        "--no-color",
    )
    assert code == EXIT_OK
    assert names(folder) == ["01_a.txt", "02_b.txt"]


def test_rename_combines_operations_in_documented_order(capsys, folder: Path):
    make_files(folder, ["IMG Summer.JPG"])
    code, _ = run(
        capsys,
        "rename",
        str(folder),
        "--find",
        "IMG",
        "--replace",
        "Photo",
        "--replace-spaces",
        "_",
        "--case",
        "lower",
        "--prefix",
        "2026-",
        "--yes",
        "--no-color",
    )
    assert code == EXIT_OK
    assert names(folder) == ["2026-photo_summer.JPG"]


def test_rename_with_template(capsys, folder: Path):
    make_files(folder, ["one.txt", "two.txt"])
    code, _ = run(
        capsys,
        "rename",
        str(folder),
        "--template",
        "{index:02d}-{stem}{ext}",
        "--yes",
        "--no-color",
    )
    assert code == EXIT_OK
    assert names(folder) == ["01-one.txt", "02-two.txt"]


def test_rename_with_config_file(capsys, folder: Path, tmp_path: Path):
    make_files(folder, ["x.txt"])
    config = tmp_path / "ops.json"
    config.write_text(
        json.dumps([{"type": "prefix_suffix", "prefix": "pre_"}]), encoding="utf-8"
    )
    code, _ = run(capsys, "rename", str(folder), "--config", str(config), "--yes", "--no-color")
    assert code == EXIT_OK
    assert names(folder) == ["pre_x.txt"]


def test_config_and_flags_conflict(capsys, folder: Path, tmp_path: Path):
    make_files(folder, ["x.txt"])
    config = tmp_path / "ops.json"
    config.write_text("[]", encoding="utf-8")
    code, output = run(
        capsys, "rename", str(folder), "--config", str(config), "--prefix", "a", "--no-color"
    )
    assert code == EXIT_USAGE
    assert "cannot be combined" in output


def test_broken_config_file_reports_a_usage_error(capsys, folder: Path, tmp_path: Path):
    make_files(folder, ["x.txt"])
    config = tmp_path / "ops.json"
    config.write_text("{ nope", encoding="utf-8")
    code, output = run(capsys, "rename", str(folder), "--config", str(config), "--no-color")
    assert code == EXIT_USAGE
    assert "not valid JSON" in output


def test_unknown_option_exits_with_usage_error(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["rename", ".", "--nonsense"])
    assert exit_info.value.code == 2


# --------------------------------------------------------------------------- #
# history / undo / export
# --------------------------------------------------------------------------- #


def test_history_and_undo_roundtrip(capsys, folder: Path):
    make_files(folder, ["a.txt", "b.txt"])
    run(capsys, "rename", str(folder), "--prefix", "x_", "--yes", "--no-color")

    code, output = run(capsys, "history", "--no-color")
    assert code == EXIT_OK
    assert "completed" in output

    code, output = run(capsys, "undo", "--last", "--dry-run", "--no-color")
    assert code == EXIT_OK
    assert "would be renamed" in output
    assert names(folder) == ["x_a.txt", "x_b.txt"]

    code, output = run(capsys, "undo", "--last", "--yes", "--no-color")
    assert code == EXIT_OK
    assert names(folder) == ["a.txt", "b.txt"]


def test_history_json(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    run(capsys, "rename", str(folder), "--prefix", "x_", "--yes", "--no-color")
    code, output = run(capsys, "history", "--json")
    payload = json.loads(output)
    assert payload[0]["renamed"] == 1
    assert payload[0]["undoable"] is True


def test_undo_with_explicit_session_id(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    _, output = run(capsys, "rename", str(folder), "--prefix", "x_", "--yes", "--json")
    session_id = json.loads(output)["session"]
    code, _ = run(capsys, "undo", session_id, "--yes", "--no-color")
    assert code == EXIT_OK
    assert names(folder) == ["a.txt"]


def test_undo_nothing_to_undo(capsys):
    code, output = run(capsys, "undo", "--last", "--no-color")
    assert code == EXIT_NOTHING
    assert "no rename session" in output


def test_undo_blocked_when_file_moved(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    run(capsys, "rename", str(folder), "--prefix", "x_", "--yes", "--no-color")
    (folder / "x_a.txt").rename(folder / "moved.txt")
    code, output = run(capsys, "undo", "--last", "--yes", "--no-color")
    assert code == EXIT_BLOCKED
    assert "no longer" in output or "cannot be restored" in output


def test_undo_allow_partial(capsys, folder: Path):
    make_files(folder, ["a.txt", "b.txt"])
    run(capsys, "rename", str(folder), "--prefix", "x_", "--yes", "--no-color")
    (folder / "x_a.txt").unlink()
    code, output = run(capsys, "undo", "--last", "--allow-partial", "--yes", "--no-color")
    assert code == EXIT_BLOCKED or code == EXIT_OK
    assert names(folder) == ["b.txt"]


def test_undo_list(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    run(capsys, "rename", str(folder), "--prefix", "x_", "--yes", "--no-color")
    code, output = run(capsys, "undo", "--list", "--no-color")
    assert code == EXIT_OK
    assert "completed" in output


def test_export_manifest(capsys, folder: Path, tmp_path: Path):
    make_files(folder, ["a.txt"])
    _, output = run(capsys, "rename", str(folder), "--prefix", "x_", "--yes", "--json")
    session_id = json.loads(output)["session"]
    destination = tmp_path / "manifest.json"
    code, _ = run(capsys, "export", session_id, "--output", str(destination), "--no-color")
    assert code == EXIT_OK
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["entries"][0]["target_name"] == "x_a.txt"


def test_history_detail_and_export(capsys, folder: Path, tmp_path: Path):
    make_files(folder, ["a.txt"])
    _, output = run(capsys, "rename", str(folder), "--prefix", "x_", "--yes", "--json")
    session_id = json.loads(output)["session"]
    destination = tmp_path / "detail.csv"
    code, output = run(
        capsys, "history", "--session", session_id, "--export", str(destination), "--format", "csv", "--no-color"
    )
    assert code == EXIT_OK
    assert destination.exists()


def test_history_unknown_session(capsys):
    code, output = run(capsys, "history", "--session", "nope", "--no-color")
    assert code == EXIT_USAGE
    assert "not in the history" in output


def test_history_is_persisted_between_runs(capsys, folder: Path):
    make_files(folder, ["a.txt"])
    run(capsys, "rename", str(folder), "--prefix", "x_", "--yes", "--no-color")
    code, output = run(capsys, "history", "--limit", "5", "--json")
    assert code == EXIT_OK
    assert len(json.loads(output)) == 1


def test_gui_command_reports_availability(capsys):
    code, output = run(capsys, "gui", "--check", "--no-color")
    assert code in (EXIT_OK, EXIT_FAILED)
    assert "graphical interface" in output or "PySide6" in output
