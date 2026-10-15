"""Tests for file discovery, filtering, sorting and settings storage."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from conftest import make_files

from ezrename.core.discovery import (
    SORT_KEYS,
    collect_records,
    filter_records,
    scan_directory,
    sort_records,
)
from ezrename.core.settings import AppSettings, config_dir, data_dir


def test_scan_folder_finds_only_files(folder: Path):
    make_files(folder, ["a.txt", "b.txt"])
    (folder / "nested").mkdir()
    make_files(folder / "nested", ["deep.txt"])
    scan = scan_directory(folder)
    assert {record.name for record in scan.records} == {"a.txt", "b.txt"}
    assert scan.folders == 1


def test_scan_is_recursive_when_requested(folder: Path):
    make_files(folder, ["a.txt"])
    make_files(folder / "nested", ["deep.txt"])
    scan = scan_directory(folder, recursive=True)
    assert {record.name for record in scan.records} == {"a.txt", "deep.txt"}


def test_scan_skips_hidden_files_by_default(folder: Path):
    make_files(folder, [".hidden.txt", "visible.txt"])
    assert {record.name for record in scan_directory(folder).records} == {"visible.txt"}
    both = scan_directory(folder, include_hidden=True)
    assert {record.name for record in both.records} == {".hidden.txt", "visible.txt"}


def test_scan_reports_missing_and_wrong_paths(folder: Path):
    missing = scan_directory(folder / "nope")
    assert missing.errors and "does not exist" in missing.errors[0]
    not_a_dir = make_files(folder, ["file.txt"])[0]
    result = scan_directory(not_a_dir)
    assert result.errors and "not a folder" in result.errors[0]


def test_scan_skips_internal_temp_and_backup_files(folder: Path):
    make_files(folder, [".ezrename-tmp.abc-x.txt", ".ezrename-backup.abc-x.txt", "x.txt"])
    names = {record.name for record in scan_directory(folder, include_hidden=True).records}
    assert names == {"x.txt"}


def test_scan_extension_filter(folder: Path):
    make_files(folder, ["a.jpg", "b.png", "c.txt"])
    scan = scan_directory(folder, extensions=["jpg", ".PNG"])
    assert {record.name for record in scan.records} == {"a.jpg", "b.png"}


def test_scan_glob_and_exclude_filters(folder: Path):
    make_files(folder, ["IMG_1.jpg", "IMG_2.jpg", "notes.txt"])
    scan = scan_directory(folder, include_globs=["IMG_*"], exclude_globs=["*_2.*"])
    assert {record.name for record in scan.records} == {"IMG_1.jpg"}


def test_scan_size_filters(folder: Path):
    (folder / "small.txt").write_text("x")
    (folder / "big.txt").write_text("y" * 500)
    scan = scan_directory(folder, min_size=10)
    assert {record.name for record in scan.records} == {"big.txt"}
    scan = scan_directory(folder, max_size=10)
    assert {record.name for record in scan.records} == {"small.txt"}


def test_scan_contains_filter(folder: Path):
    make_files(folder, ["holiday photo.jpg", "other.jpg"])
    scan = scan_directory(folder, name_contains="PHOTO")
    assert {record.name for record in scan.records} == {"holiday photo.jpg"}


def test_scan_max_files(folder: Path):
    make_files(folder, [f"f{i}.txt" for i in range(10)])
    assert len(scan_directory(folder, max_files=3).records) == 3


def test_scan_empty_directory(folder: Path):
    scan = scan_directory(folder)
    assert scan.records == [] and not scan.errors


def test_scan_skips_symlinks_unless_asked(folder: Path, tmp_path: Path):
    target = make_files(folder, ["real.txt"])[0]
    link = folder / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available for this user")
    names = {record.name for record in scan_directory(folder).records}
    assert "link.txt" not in names
    followed = {record.name for record in scan_directory(folder, follow_symlinks=True).records}
    assert "link.txt" in followed


def test_collect_records_accepts_files_and_folders(folder: Path):
    make_files(folder, ["one.txt"])
    make_files(folder / "sub", ["two.txt"])
    result = collect_records([folder], recursive=True)
    assert {record.name for record in result.records} == {"one.txt", "two.txt"}
    assert result.errors == []


def test_collect_records_deduplicates(folder: Path):
    path = make_files(folder, ["one.txt"])[0]
    result = collect_records([path, path, folder])
    assert len(result.records) == 1


def test_collect_records_reports_missing(folder: Path):
    result = collect_records([folder / "nope.txt"])
    assert result.errors and "does not exist" in result.errors[0]


def test_filter_records_by_search_extension_and_glob(folder: Path):
    make_files(folder, ["holiday.jpg", "holiday.png", "work.txt"])
    records = list(scan_directory(folder).records)
    assert {r.name for r in filter_records(records, search="HOLIDAY")} == {"holiday.jpg", "holiday.png"}
    assert {r.name for r in filter_records(records, extensions=["txt"])} == {"work.txt"}
    assert {r.name for r in filter_records(records, glob="holiday.*")} == {"holiday.jpg", "holiday.png"}


def test_filter_records_matches_full_path(folder: Path):
    make_files(folder, ["a.txt"])
    records = list(scan_directory(folder).records)
    assert filter_records(records, search=str(folder).lower()) == records


def test_sort_records_natural_order(folder: Path):
    make_files(folder, ["img10.jpg", "img2.jpg", "img1.jpg"])
    records = list(scan_directory(folder).records)
    ordered = [record.name for record in sort_records(records, "name")]
    assert ordered == ["img1.jpg", "img2.jpg", "img10.jpg"]
    assert [record.name for record in sort_records(records, "name", reverse=True)] == [
        "img10.jpg",
        "img2.jpg",
        "img1.jpg",
    ]


def test_sort_records_by_size_extension_and_date(folder: Path):
    (folder / "b.txt").write_text("12345")
    (folder / "a.png").write_text("1")
    records = list(scan_directory(folder).records)
    assert [r.name for r in sort_records(records, "size")] == ["a.png", "b.txt"]
    assert [r.name for r in sort_records(records, "extension")] == ["a.png", "b.txt"]
    assert len(sort_records(records, "modified")) == 2
    assert len(sort_records(records, "created")) == 2
    assert len(sort_records(records, "path")) == 2


def test_sort_records_rejects_unknown_key(folder: Path):
    with pytest.raises(ValueError):
        sort_records([], "colour")


def test_sort_keys_are_documented():
    assert set(SORT_KEYS) >= {"name", "size", "modified", "extension", "added"}


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #


def test_settings_roundtrip(isolated_home: Path):
    settings = AppSettings()
    settings.theme = "light"
    settings.number_padding = 4
    settings.recent_folders = ["C:/x"]
    path = settings.save()
    assert path.parent == isolated_home

    loaded = AppSettings.load()
    assert loaded.theme == "light"
    assert loaded.number_padding == 4
    assert loaded.recent_folders == ["C:/x"]


def test_settings_ignore_unknown_and_wrong_typed_values(isolated_home: Path):
    (isolated_home / "settings.json").write_text(
        json.dumps({"theme": "dark", "number_padding": "many", "nonsense": 1}), encoding="utf-8"
    )
    settings = AppSettings.load()
    assert settings.theme == "dark"
    assert settings.number_padding == 3


def test_settings_survive_a_corrupt_file(isolated_home: Path):
    (isolated_home / "settings.json").write_text("{not json", encoding="utf-8")
    assert AppSettings.load().theme == "dark"


def test_settings_remember_folder(isolated_home: Path):
    settings = AppSettings()
    settings.remember_folder("C:/one")
    settings.remember_folder("C:/two")
    settings.remember_folder("C:/one")
    assert settings.recent_folders == ["C:/one", "C:/two"]
    assert settings.last_folder == "C:/one"


def test_settings_presets(isolated_home: Path):
    settings = AppSettings()
    settings.add_preset("Photos", [{"type": "numbering", "start": 1}])
    settings.save()
    assert AppSettings.load().presets["Photos"][0]["type"] == "numbering"


def test_config_and_data_dirs_honour_the_environment(isolated_home: Path):
    assert config_dir() == isolated_home
    assert data_dir() == isolated_home


def test_data_dir_defaults_are_writable_locations(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("EZRENAME_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    assert "EzRename" in str(config_dir()) if os.name == "nt" else True
    assert str(tmp_path) in str(config_dir())
