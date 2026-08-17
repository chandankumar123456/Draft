"""Unit tests for the code-editing tools in tools/functions.py."""

import json

import pytest

from tools.functions import apply_patch, delete_lines, insert_text, replace_text

GOOD_PATCH = (
    "--- a/f.txt\n"
    "+++ b/f.txt\n"
    "@@ -1,3 +1,3 @@\n"
    " line one\n"
    "-line two\n"
    "+line TWO\n"
    " line three\n"
)


def assert_envelope(result):
    """Assert the result is a JSON-serializable tool envelope."""
    assert set(result) == {"success", "data", "message", "error"}
    json.dumps(result)


def test_insert_text_at_start(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("line1\nline2\nline3\n")
    result = insert_text(str(p), 1, "first")
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["inserted"] is True
    assert result["data"]["line"] == 1
    assert result["data"]["new_total_lines"] == 4
    assert p.read_text() == "first\nline1\nline2\nline3\n"


def test_insert_text_append(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("line1\nline2\nline3\n")
    result = insert_text(str(p), 4, "last")
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["new_total_lines"] == 4
    assert p.read_text() == "line1\nline2\nline3\nlast\n"


@pytest.mark.parametrize("line", [0, 5])
def test_insert_text_invalid_line(tmp_path, line):
    p = tmp_path / "f.txt"
    p.write_text("line1\nline2\nline3\n")
    result = insert_text(str(p), line, "x")
    assert_envelope(result)
    assert not result["success"]
    assert p.read_text() == "line1\nline2\nline3\n"


def test_replace_text_one_match(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("aaa bbb aaa ccc\n")
    result = replace_text(str(p), "bbb", "XXX")
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["count"] == 1
    assert result["data"]["occurrences"] == 1
    assert p.read_text() == "aaa XXX aaa ccc\n"


def test_replace_text_all_matches(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("aaa bbb aaa ccc\n")
    result = replace_text(str(p), "aaa", "XXX")
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["count"] == 2
    assert result["data"]["occurrences"] == 2
    assert p.read_text() == "XXX bbb XXX ccc\n"


def test_replace_text_count_one(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("aaa bbb aaa ccc\n")
    result = replace_text(str(p), "aaa", "XXX", count=1)
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["count"] == 1
    assert p.read_text() == "XXX bbb aaa ccc\n"


def test_replace_text_count_exceeds_occurrences(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("aaa bbb aaa ccc\n")
    result = replace_text(str(p), "aaa", "XXX", count=5)
    assert_envelope(result)
    assert not result["success"]
    assert p.read_text() == "aaa bbb aaa ccc\n"


def test_replace_text_no_match(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("aaa bbb ccc\n")
    result = replace_text(str(p), "zzz", "XXX")
    assert_envelope(result)
    assert not result["success"]


def test_replace_text_empty_old(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("aaa\n")
    result = replace_text(str(p), "", "XXX")
    assert_envelope(result)
    assert not result["success"]


def test_delete_lines_valid_range(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("1\n2\n3\n4\n5\n")
    result = delete_lines(str(p), 2, 4)
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["deleted"] == 3
    assert result["data"]["new_total_lines"] == 2
    assert p.read_text() == "1\n5\n"


@pytest.mark.parametrize(
    ("start", "end"),
    [(3, 2), (0, 2), (2, 9)],
)
def test_delete_lines_invalid_range(tmp_path, start, end):
    p = tmp_path / "f.txt"
    p.write_text("1\n2\n3\n4\n5\n")
    result = delete_lines(str(p), start, end)
    assert_envelope(result)
    assert not result["success"]
    assert p.read_text() == "1\n2\n3\n4\n5\n"


def test_apply_patch_success(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("line one\nline two\nline three\n")
    result = apply_patch(str(p), GOOD_PATCH)
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["changed"] is True
    assert result["data"]["patch_applied"] is True
    assert p.read_text() == "line one\nline TWO\nline three\n"


def test_apply_patch_malformed(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("line one\nline two\nline three\n")
    result = apply_patch(str(p), "this is not a diff at all")
    assert_envelope(result)
    assert not result["success"]
    assert p.read_text() == "line one\nline two\nline three\n"


def test_apply_patch_wrong_context(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("line one\nline two\nline three\n")
    wrong = GOOD_PATCH.replace(" line one", " line wone")
    result = apply_patch(str(p), wrong)
    assert_envelope(result)
    assert not result["success"]
    assert p.read_text() == "line one\nline two\nline three\n"


def test_apply_patch_empty(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("line one\n")
    result = apply_patch(str(p), "")
    assert_envelope(result)
    assert not result["success"]
    assert p.read_text() == "line one\n"


def test_apply_patch_missing_file(tmp_path):
    result = apply_patch(str(tmp_path / "missing.txt"), GOOD_PATCH)
    assert_envelope(result)
    assert not result["success"]
