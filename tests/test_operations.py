"""Tests for the rename operations and the naming helpers."""

from __future__ import annotations

import pytest

from ezrename.core.naming import (
    is_valid_filename,
    join_name,
    split_name,
    validate_filename,
)
from ezrename.core.operations import (
    DateInsert,
    ExtensionChange,
    FileOperationError,
    FindReplace,
    NameContext,
    Numbering,
    OperationError,
    Separators,
    Template,
    TextEdit,
    CaseConvert,
    PrefixSuffix,
    describe_operations,
    new_operation,
    operation_from_dict,
    validate_operations,
)
from ezrename.core.pipeline import apply_operations


def run(operations, name="photo.jpg", **kwargs):
    return apply_operations(name, operations, **kwargs)


# --------------------------------------------------------------------------- #
# naming
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name,expected",
    [
        ("photo.jpg", ("photo", "jpg")),
        ("archive.tar.gz", ("archive.tar", "gz")),
        ("noextension", ("noextension", "")),
        (".gitignore", (".gitignore", "")),
        ("multi.dot.name.txt", ("multi.dot.name", "txt")),
        ("trailing.", ("trailing.", "")),  # an empty extension means "no extension"
        ("", ("", "")),
    ],
)
def test_split_name(name, expected):
    assert split_name(name) == expected


def test_join_name_roundtrip():
    assert join_name("photo", "jpg") == "photo.jpg"
    assert join_name("photo", "") == "photo"


@pytest.mark.parametrize(
    "name,problem",
    [
        ("photo.jpg", None),
        ("", "empty file name"),
        ("..", "'.' and '..' are reserved"),
        ("a<b.txt", "illegal character"),
        ('quote".txt', "illegal character"),
        ("ends with space .txt", None),
        ("bad .txt", None),
        ("trailing .txt.", "end with a space or a dot"),
        ("CON.txt", "reserved Windows device name"),
        ("com1", "reserved Windows device name"),
        ("nul.log", "reserved Windows device name"),
        (" leading.txt", "start with a space"),
        ("tab\tname.txt", "control character"),
        ("x" * 300 + ".txt", "longer than"),
    ],
)
def test_validate_filename(name, problem):
    result = validate_filename(name)
    if problem is None:
        assert result is None, result
    else:
        assert result is not None and problem in result


def test_is_valid_filename():
    assert is_valid_filename("ok.txt")
    assert not is_valid_filename("bad/name.txt")


# --------------------------------------------------------------------------- #
# find and replace
# --------------------------------------------------------------------------- #


def test_find_replace_literal():
    op = FindReplace(find="IMG_", replace="Photo_")
    assert run([op], "IMG_1234.jpg") == "Photo_1234.jpg"


def test_find_replace_empty_replacement_removes_text():
    op = FindReplace(find=" ", replace="")
    assert run([op], "my holiday photo.jpg") == "myholidayphoto.jpg"


def test_find_replace_case_insensitive():
    op = FindReplace(find="img", replace="photo", case_sensitive=False)
    assert run([op], "IMG_1.jpg") == "photo_1.jpg"


def test_find_replace_first_only():
    op = FindReplace(find="a", replace="A", replace_all=False)
    assert run([op], "banana.txt") == "bAnana.txt"


def test_find_replace_all_occurrences_by_default():
    op = FindReplace(find="a", replace="A")
    assert run([op], "banana.txt") == "bAnAnA.txt"


def test_find_replace_regex_with_backreference():
    op = FindReplace(find=r"(\d+)-(\d+)", replace=r"\2-\1", use_regex=True)
    assert run([op], "file 12-34.txt") == "file 34-12.txt"


def test_find_replace_regex_ignore_case():
    op = FindReplace(find=r"ep(\d+)", replace=r"e\1", use_regex=True, case_sensitive=False)
    assert run([op], "EP05 pilot.txt") == "e05 pilot.txt"


def test_find_replace_invalid_regex_is_reported_not_crashing():
    op = FindReplace(find="([", use_regex=True)
    with pytest.raises(OperationError):
        op.validate()
    problems = validate_operations([op])
    assert problems and "regular expression" in problems[0]


def test_find_replace_scope_extension():
    op = FindReplace(find="jpg", replace="jpeg", scope="ext")
    assert run([op], "photo.jpg") == "photo.jpeg"


def test_find_replace_scope_both():
    op = FindReplace(find="p", replace="P", scope="both")
    assert run([op], "photo.jpg") == "Photo.jPg"


def test_find_replace_scope_full_replaces_across_extension():
    op = FindReplace(find=".jpg", replace="", scope="full")
    assert run([op], "photo.jpg") == "photo"


def test_find_replace_with_empty_find_is_a_no_op():
    assert run([FindReplace(find="", replace="x")], "photo.jpg") == "photo.jpg"


def test_find_replace_scope_can_be_validated():
    with pytest.raises(OperationError):
        FindReplace(find="a", scope="nope").validate()


# --------------------------------------------------------------------------- #
# prefix / suffix
# --------------------------------------------------------------------------- #


def test_prefix_added():
    assert run([PrefixSuffix(prefix="Vacation_")], "photo.jpg") == "Vacation_photo.jpg"


def test_suffix_before_extension():
    assert run([PrefixSuffix(suffix="_2026")], "photo.jpg") == "photo_2026.jpg"


def test_suffix_after_extension():
    assert run([PrefixSuffix(suffix="_backup", suffix_after_extension=True)], "photo.jpg") == "photo.jpg_backup"


def test_remove_prefix():
    assert run([PrefixSuffix(remove_prefix="IMG_")], "IMG_0001.jpg") == "0001.jpg"


def test_remove_prefix_does_not_touch_other_text():
    assert run([PrefixSuffix(remove_prefix="IMG_")], "my_IMG_0001.jpg") == "my_IMG_0001.jpg"


def test_remove_suffix_keeps_extension():
    assert run([PrefixSuffix(remove_suffix="_final")], "report_final.pdf") == "report.pdf"


def test_remove_prefix_only_when_present():
    assert run([PrefixSuffix(remove_prefix="XX")], "photo.jpg") == "photo.jpg"


def test_prefix_case_insensitive_removal():
    op = PrefixSuffix(remove_prefix="img_", case_sensitive=False)
    assert run([op], "IMG_0001.jpg") == "0001.jpg"


def test_prefix_and_suffix_together():
    op = PrefixSuffix(prefix="pre_", suffix="_post")
    assert run([op], "name.txt") == "pre_name_post.txt"


def test_prefix_validation_rejects_path_separators():
    with pytest.raises(OperationError):
        PrefixSuffix(prefix="bad/prefix").validate()


# --------------------------------------------------------------------------- #
# numbering
# --------------------------------------------------------------------------- #


def test_numbering_prefix_default():
    op = Numbering(start=1, padding=3, position="prefix")
    assert run([op], "photo.jpg", index=0) == "001_photo.jpg"
    assert run([op], "photo.jpg", index=4) == "005_photo.jpg"


def test_numbering_suffix_preserves_extension():
    op = Numbering(start=1, padding=2, position="suffix")
    assert run([op], "photo.jpg", index=1) == "photo_02.jpg"


def test_numbering_replace_with_literal_text():
    op = Numbering(start=1, padding=3, position="replace", prefix="Photo_")
    assert run([op], "photo.jpg", index=0) == "Photo_001.jpg"
    assert run([op], "photo.jpg", index=1) == "Photo_002.jpg"


def test_numbering_step_and_start():
    op = Numbering(start=10, step=5, padding=4, position="suffix")
    assert run([op], "a.txt", index=0) == "a_0010.txt"
    assert run([op], "a.txt", index=2) == "a_0020.txt"


def test_numbering_custom_separator_and_padding():
    op = Numbering(start=1, padding=1, separator="-", position="suffix")
    assert run([op], "a.txt", index=0) == "a-1.txt"


def test_numbering_alpha_style():
    op = Numbering(style="alpha_lower", padding=0, position="suffix")
    assert run([op], "page.txt", index=0) == "page_a.txt"
    assert run([op], "page.txt", index=25) == "page_z.txt"
    assert run([op], "page.txt", index=26) == "page_aa.txt"


def test_numbering_roman_style():
    op = Numbering(style="roman_upper", padding=0, position="suffix")
    assert run([op], "chapter.txt", index=3) == "chapter_IV.txt"


def test_numbering_roman_out_of_range_reports_error():
    op = Numbering(style="roman_lower", start=4000, padding=0)
    with pytest.raises(FileOperationError):
        run([op], "x.txt", index=0)


def test_numbering_number_suffix_text():
    op = Numbering(start=1, padding=2, position="replace", suffix=")")
    assert run([op], "x.txt", index=0) == "01).txt"


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"style": "nope"}, "unknown numbering style"),
        ({"position": "middle"}, "unknown number position"),
        ({"padding": -1}, "padding cannot be negative"),
        ({"padding": 40}, "padding above 20"),
    ],
)
def test_numbering_validation(kwargs, expected):
    with pytest.raises(OperationError) as excinfo:
        Numbering(**kwargs).validate()
    assert expected in str(excinfo.value)


# --------------------------------------------------------------------------- #
# case conversion
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mode,name,expected",
    [
        ("upper", "report final.pdf", "REPORT FINAL.pdf"),
        ("lower", "REPORT Final.PDF", "report final.PDF"),
        ("title", "report-final_notes.txt", "Report-Final_Notes.txt"),
        ("sentence", "REPORT FINAL.TXT", "Report final.TXT"),
    ],
)
def test_case_modes(mode, name, expected):
    assert run([CaseConvert(mode=mode)], name) == expected


def test_case_scope_extension():
    assert run([CaseConvert(mode="upper", scope="ext")], "photo.jpg") == "photo.JPG"


def test_case_scope_both():
    assert run([CaseConvert(mode="lower", scope="both")], "PHOTO.JPG") == "photo.jpg"


def test_case_validation():
    with pytest.raises(OperationError):
        CaseConvert(mode="crazy").validate()
    with pytest.raises(OperationError):
        CaseConvert(scope="everything").validate()


# --------------------------------------------------------------------------- #
# separators / cleanup
# --------------------------------------------------------------------------- #


def test_spaces_to_underscore():
    assert run([Separators(spaces_to="_")], "my holiday photo.jpg") == "my_holiday_photo.jpg"


def test_spaces_to_custom_character():
    assert run([Separators(spaces_to="-")], "a b c.txt") == "a-b-c.txt"


def test_collapse_repeats():
    op = Separators(spaces_to="_", collapse_repeats=True)
    assert run([op], "a   b.txt") == "a_b.txt"


def test_trim_whitespace():
    assert run([Separators()], "  padded name  .txt") == "padded name.txt"


def test_dedupe_words():
    op = Separators(dedupe_words=True, trim_whitespace=False)
    assert run([op], "summer_summer_trip.txt") == "summer_trip.txt"


def test_strip_chars():
    assert run([Separators(strip_chars="#!")], "draft#1!.txt") == "draft1.txt"


def test_replace_characters():
    op = Separators(replace_from="&", replace_to="+")
    assert run([op], "rock & roll.txt") == "rock + roll.txt"


def test_separators_validation():
    with pytest.raises(OperationError):
        Separators(replace_from="ab", replace_to="c").validate()
    with pytest.raises(OperationError):
        Separators(spaces_to="--").validate()


# --------------------------------------------------------------------------- #
# extension management
# --------------------------------------------------------------------------- #


def test_extension_change():
    assert run([ExtensionChange(new_extension="txt")], "notes.md") == "notes.txt"


def test_extension_change_accepts_dot_prefix():
    assert run([ExtensionChange(new_extension=".jpeg")], "photo.jpg") == "photo.jpeg"


def test_extension_case():
    assert run([ExtensionChange(case="upper")], "photo.jpg") == "photo.JPG"
    assert run([ExtensionChange(case="lower")], "PHOTO.JPG") == "PHOTO.jpg"


def test_extension_remove():
    assert run([ExtensionChange(remove=True)], "photo.jpg") == "photo"


def test_extension_only_when_filter_matches():
    op = ExtensionChange(case="upper", only_when="jpg,png")
    assert run([op], "photo.jpg") == "photo.JPG"
    assert run([op], "notes.txt") == "notes.txt"


def test_extension_validation():
    with pytest.raises(OperationError):
        ExtensionChange(case="title").validate()
    with pytest.raises(OperationError):
        ExtensionChange(new_extension="bad/ext").validate()


# --------------------------------------------------------------------------- #
# date and time
# --------------------------------------------------------------------------- #


def test_insert_date_prefix():
    op = DateInsert(format="%Y-%m-%d", source="mtime", position="prefix")
    # 2026-10-15 12:00:00 UTC expressed as a local timestamp
    import datetime as dt

    stamp = dt.datetime(2026, 10, 15, 12, 0, 0).timestamp()
    assert run([op], "report.pdf", mtime=stamp) == "2026-10-15_report.pdf"


def test_insert_date_suffix():
    op = DateInsert(format="%Y%m%d", position="suffix", separator="-")
    import datetime as dt

    stamp = dt.datetime(2024, 1, 2, 3, 4, 5).timestamp()
    assert run([op], "photo.jpg", mtime=stamp) == "photo-20240102.jpg"


def test_missing_timestamp_uses_fallback():
    empty = DateInsert(fallback="empty")
    assert run([empty], "photo.jpg", mtime=0) == "photo.jpg"
    original = DateInsert(position="prefix", fallback="original")
    assert run([original], "photo.jpg", mtime=0) == "photo.jpg"
    error = DateInsert(fallback="error")
    with pytest.raises(FileOperationError):
        run([error], "photo.jpg", mtime=0)


def test_date_validation():
    with pytest.raises(OperationError):
        DateInsert(source="birthday").validate()
    with pytest.raises(OperationError):
        DateInsert(fallback="explode").validate()


# --------------------------------------------------------------------------- #
# templates
# --------------------------------------------------------------------------- #


def test_template_basic_variables():
    op = Template(pattern="{stem}_{index:02d}{ext}")
    assert run([op], "photo.jpg", index=0) == "photo_01.jpg"
    assert run([op], "photo.jpg", index=9) == "photo_10.jpg"


def test_template_includes_date_and_extension():
    import datetime as dt

    op = Template(pattern="{date}_{name}")
    stamp = dt.datetime(2026, 10, 15, 8, 30, 0).timestamp()
    assert run([op], "report.pdf", mtime=stamp) == "2026-10-15_report.pdf"


def test_template_size_and_parent():
    op = Template(pattern="{stem}-{size}{ext}")
    assert run([op], "a.bin", size=2048) == "a-2048.bin"


def test_template_unknown_variable_is_rejected():
    with pytest.raises(OperationError) as excinfo:
        Template(pattern="{nope}{ext}").validate()
    assert "unknown template variable" in str(excinfo.value)


def test_template_empty_pattern_is_rejected():
    with pytest.raises(OperationError):
        Template(pattern="   ").validate()


def test_template_invalid_format_spec_is_rejected():
    with pytest.raises(OperationError):
        Template(pattern="{index:!!!}").validate()


def test_template_without_extension_drops_it():
    assert run([Template(pattern="{stem}_{index}")], "photo.jpg", index=0) == "photo_1"


# --------------------------------------------------------------------------- #
# insert / remove text
# --------------------------------------------------------------------------- #


def test_insert_text_at_start():
    assert run([TextEdit(mode="insert", text="pre-", position="start")], "a.txt") == "pre-a.txt"


def test_insert_text_at_end():
    assert run([TextEdit(mode="insert", text="-v2", position="end")], "a.txt") == "a-v2.txt"


def test_insert_text_at_index():
    op = TextEdit(mode="insert", text="X", position="index", index=2)
    assert run([op], "abcdef.txt") == "abXcdef.txt"


def test_remove_text_anywhere():
    assert run([TextEdit(mode="remove", text="x", position="anywhere")], "axbxc.txt") == "abc.txt"


def test_remove_text_from_start_only():
    op = TextEdit(mode="remove", text="a", position="start")
    assert run([op], "aab.txt") == "ab.txt"


def test_remove_text_from_end_only():
    op = TextEdit(mode="remove", text="z", position="end")
    assert run([op], "azz.txt") == "az.txt"


def test_remove_text_first_and_last():
    first = TextEdit(mode="remove", text="a", position="first")
    assert run([first], "aaaa.txt") == "aaa.txt"
    last = TextEdit(mode="remove", text="a", position="last")
    assert run([last], "aaaa.txt") == "aaa.txt"


def test_remove_text_ignore_case():
    op = TextEdit(mode="remove", text="draft", position="anywhere", case_sensitive=False)
    assert run([op], "DRAFT notes.txt") == " notes.txt"


def test_text_edit_validation():
    with pytest.raises(OperationError):
        TextEdit(mode="insert", text="", position="start").validate()
    with pytest.raises(OperationError):
        TextEdit(mode="insert", text="x", position="anywhere").validate()
    with pytest.raises(OperationError):
        TextEdit(mode="remove", text="x", position="middle").validate()


# --------------------------------------------------------------------------- #
# pipeline composition and serialisation
# --------------------------------------------------------------------------- #


def test_operations_combine_in_order():
    operations = [
        FindReplace(find="IMG_", replace="Photo_"),
        CaseConvert(mode="lower"),
        PrefixSuffix(prefix="2026_"),
    ]
    assert run(operations, "IMG_Summer.JPG") == "2026_photo_summer.JPG"


def test_operation_roundtrip_through_dict():
    operation = FindReplace(find="a", replace="b", case_sensitive=False, scope="ext")
    payload = operation.to_dict()
    assert payload["type"] == "find_replace"
    restored = operation_from_dict(payload)
    assert restored == operation


def test_new_operation_rejects_unknown_type_and_options():
    with pytest.raises(OperationError):
        new_operation("does_not_exist")
    with pytest.raises(OperationError):
        new_operation("case", nonsense=1)


def test_describe_operations_is_human_readable():
    lines = describe_operations(
        [FindReplace(find="a", replace="b"), Numbering(position="suffix")]
    )
    assert lines[0].startswith("1. Replace 'a' with 'b'")
    assert "Numbering" in lines[1]


def test_name_context_clone_is_independent():
    ctx = NameContext.from_name("a.txt", index=3)
    clone = ctx.clone()
    clone.stem = "b"
    assert ctx.stem == "a"


def test_all_operations_are_validated_by_validate_operations():
    assert validate_operations([Numbering(), CaseConvert(), Separators()]) == []
