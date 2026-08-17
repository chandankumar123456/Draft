"""Unit tests for the code-search tools in tools/functions.py."""

import json
from pathlib import Path

import pytest

from tools.functions import (
    find_files,
    find_references,
    find_symbol,
    get_file_symbols,
    grep,
    search_code,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
assert (REPO_ROOT / "agent" / "tools" / "functions.py").is_file()


def assert_envelope(result):
    """Assert the result is a JSON-serializable tool envelope."""
    assert set(result) == {"success", "data", "message", "error"}
    json.dumps(result)


def test_search_code_finds_functions_py_in_repo():
    result = search_code("list_files", path=str(REPO_ROOT), extensions=["py"])
    assert_envelope(result)
    assert result["success"]
    matches = result["data"]["matches"]
    assert matches
    assert any(Path(m["file"]).name == "functions.py" for m in matches)
    for match in matches:
        assert isinstance(match["line"], int)
        assert match["line"] > 0
        assert set(match) == {"file", "line", "text"}


def test_search_code_extension_filter(tmp_path):
    (tmp_path / "code.py").write_text("needle marker\n")
    (tmp_path / "notes.md").write_text("needle marker\n")
    py = search_code("needle marker", path=str(tmp_path), extensions=["py"])
    md = search_code("needle marker", path=str(tmp_path), extensions=["md"])
    assert_envelope(py)
    assert_envelope(md)
    assert py["data"]["matches"]
    assert all(m["file"].endswith(".py") for m in py["data"]["matches"])
    assert md["data"]["matches"]
    assert all(m["file"].endswith(".md") for m in md["data"]["matches"])


def test_search_code_case_sensitivity(tmp_path):
    (tmp_path / "a.py").write_text("HelloWorld marker\n")
    insensitive = search_code("helloworld", path=str(tmp_path), extensions=["py"])
    sensitive = search_code(
        "helloworld", path=str(tmp_path), extensions=["py"], case_sensitive=True
    )
    exact = search_code(
        "HelloWorld", path=str(tmp_path), extensions=["py"], case_sensitive=True
    )
    assert_envelope(insensitive)
    assert_envelope(sensitive)
    assert_envelope(exact)
    assert insensitive["data"]["matches"]
    assert not sensitive["data"]["matches"]
    assert exact["data"]["matches"]


def test_search_code_skips_ignored_dirs(tmp_path):
    (tmp_path / "top.py").write_text("needleXYZ here\n")
    venv = tmp_path / "draft_venv"
    venv.mkdir()
    (venv / "skip.py").write_text("needleXYZ here\n")
    result = search_code("needleXYZ", path=str(tmp_path), extensions=["py"])
    assert_envelope(result)
    assert result["success"]
    files = {Path(m["file"]).name for m in result["data"]["matches"]}
    assert "top.py" in files
    assert "skip.py" not in files


def test_grep_regex(tmp_path):
    (tmp_path / "data.txt").write_text("hello world\n")
    result = grep("h.llo", path=str(tmp_path))
    assert_envelope(result)
    assert result["success"]
    matches = result["data"]["matches"]
    assert matches
    assert Path(matches[0]["file"]).name == "data.txt"


def test_grep_invalid_regex(tmp_path):
    result = grep("(", path=str(tmp_path))
    assert_envelope(result)
    assert not result["success"]


def test_find_files_pattern(tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    result = find_files("*.py", path=str(tmp_path))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["count"] == 1
    assert Path(result["data"]["files"][0]).name == "a.py"


def test_find_files_empty_pattern(tmp_path):
    result = find_files("", path=str(tmp_path))
    assert_envelope(result)
    assert not result["success"]


@pytest.mark.parametrize(
    ("source", "symbol", "expected_kind"),
    [
        ("def list_files():\n    pass\n", "list_files", "function"),
        ("async def fetch_all():\n    pass\n", "fetch_all", "async_function"),
        ("class MyClass:\n    pass\n", "MyClass", "class"),
    ],
)
def test_find_symbol_kinds(tmp_path, source, symbol, expected_kind):
    (tmp_path / "sample.py").write_text(source)
    result = find_symbol(symbol, path=str(tmp_path))
    assert_envelope(result)
    assert result["success"]
    assert any(m["kind"] == expected_kind for m in result["data"]["matches"])
    assert all(set(m) == {"file", "line", "name", "kind"} for m in result["data"]["matches"])


def test_find_references_present(tmp_path):
    (tmp_path / "ref.py").write_text("zwxq_marker = 1\nprint(zwxq_marker)\n")
    result = find_references("zwxq_marker", path=str(tmp_path))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["matches"]


def test_find_references_empty_symbol(tmp_path):
    result = find_references("", path=str(tmp_path))
    assert_envelope(result)
    assert not result["success"]


def test_get_file_symbols_py(tmp_path):
    (tmp_path / "mod.py").write_text(
        "def foo():\n"
        "    pass\n"
        "\n"
        "class Bar:\n"
        "    pass\n"
        "\n"
        "async def baz():\n"
        "    pass\n"
    )
    result = get_file_symbols(str(tmp_path / "mod.py"))
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    assert data["count"] == 3
    assert {s["name"]: s["kind"] for s in data["symbols"]} == {
        "foo": "function",
        "Bar": "class",
        "baz": "async_function",
    }
    for symbol in data["symbols"]:
        assert isinstance(symbol["line"], int)
        assert isinstance(symbol["end_line"], int)


def test_get_file_symbols_txt(tmp_path):
    (tmp_path / "notes.txt").write_text("plain text\n")
    result = get_file_symbols(str(tmp_path / "notes.txt"))
    assert_envelope(result)
    assert not result["success"]
