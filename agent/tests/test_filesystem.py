"""Unit tests for the filesystem tools in tools/functions.py."""

import json
from pathlib import Path

from tools.functions import (
    copy_file,
    create_directory,
    delete_directory,
    delete_file,
    get_file_info,
    list_directory_tree,
    list_files,
    move_file,
    read_file,
    write_file,
)


def assert_envelope(result):
    """Assert the result is a JSON-serializable tool envelope."""
    assert set(result) == {"success", "data", "message", "error"}
    json.dumps(result)


def test_list_files_sorted_typed(tmp_path):
    (tmp_path / "b.txt").write_text("x")
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "zdir").mkdir()
    result = list_files(str(tmp_path))
    assert_envelope(result)
    assert result["success"]
    entries = result["data"]
    assert [e["name"] for e in entries] == ["a.txt", "b.txt", "zdir"]
    assert [e["type"] for e in entries] == ["file", "file", "dir"]
    assert all(set(e) == {"name", "type"} for e in entries)


def test_list_files_invalid_dir(tmp_path):
    result = list_files(str(tmp_path / "missing"))
    assert_envelope(result)
    assert not result["success"]


def test_list_directory_tree_ignores_ignored_dirs(tmp_path):
    (tmp_path / "top.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.txt").write_text("x")
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "cached.pyc").write_text("x")
    result = list_directory_tree(str(tmp_path), depth=2)
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    paths = [Path(e["path"]) for e in data["entries"]]
    assert not any("__pycache__" in p.parts for p in paths)
    assert data["path"] == str(tmp_path)
    assert all(set(e) == {"path", "depth", "type"} for e in data["entries"])


def test_list_directory_tree_depth_respected(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.txt").write_text("x")
    shallow = list_directory_tree(str(tmp_path), depth=1)
    deep = list_directory_tree(str(tmp_path), depth=2)
    assert_envelope(shallow)
    assert_envelope(deep)
    shallow_paths = [Path(e["path"]).name for e in shallow["data"]["entries"]]
    assert "inner.txt" not in shallow_paths
    deep_paths = [Path(e["path"]).name for e in deep["data"]["entries"]]
    assert "inner.txt" in deep_paths


def test_read_file_valid(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("alpha\nbeta\ngamma\n")
    result = read_file(str(p))
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    assert data["content"] == "1: alpha\n2: beta\n3: gamma"
    assert data["start_line"] == 1
    assert data["end_line"] == 3
    assert data["total_lines"] == 3
    assert data["truncated"] is False


def test_read_file_range_inclusive(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("one\ntwo\nthree\nfour\n")
    result = read_file(str(p), start_line=2, end_line=3)
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    assert data["content"] == "2: two\n3: three"
    assert data["start_line"] == 2
    assert data["end_line"] == 3


def test_read_file_invalid_range(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("one\ntwo\n")
    for kwargs in (
        {"start_line": 0},
        {"end_line": 0},
        {"start_line": 2, "end_line": 1},
        {"start_line": 99},
        {"start_line": 1, "end_line": 99},
    ):
        result = read_file(str(p), **kwargs)
        assert_envelope(result)
        assert not result["success"]


def test_read_file_missing(tmp_path):
    result = read_file(str(tmp_path / "missing.txt"))
    assert_envelope(result)
    assert not result["success"]


def test_read_file_truncation(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text(("x" * 60 + "\n") * 3000)
    result = read_file(str(p))
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    assert data["truncated"] is True
    assert data["content"].endswith("...[truncated]")
    assert len(data["content"]) <= 50015
    assert data["total_lines"] == 3000


def test_write_file_create(tmp_path):
    p = tmp_path / "sub" / "new.txt"
    result = write_file(str(p), "hello")
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    assert data["created"] is True
    assert data["modified"] is False
    assert data["bytes_written"] == 5
    assert p.read_text() == "hello"


def test_write_file_no_overwrite(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("original")
    result = write_file(str(p), "new", overwrite=False)
    assert_envelope(result)
    assert not result["success"]
    assert p.read_text() == "original"


def test_write_file_overwrite(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("original")
    result = write_file(str(p), "new", overwrite=True)
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["created"] is False
    assert result["data"]["modified"] is True
    assert p.read_text() == "new"


def test_get_file_info(tmp_path):
    p = tmp_path / "info.txt"
    p.write_text("content")
    result = get_file_info(str(p))
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    assert data["name"] == "info.txt"
    assert data["type"] == "file"
    assert data["extension"] == ".txt"
    assert isinstance(data["size_bytes"], int)
    assert isinstance(data["modified_time"], str)
    assert isinstance(data["created_time"], str)


def test_get_file_info_missing(tmp_path):
    result = get_file_info(str(tmp_path / "missing.txt"))
    assert_envelope(result)
    assert not result["success"]


def test_create_directory(tmp_path):
    target = tmp_path / "a" / "b"
    result = create_directory(str(target))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["created"] is True
    assert target.is_dir()
    again = create_directory(str(target))
    assert again["success"]
    assert again["data"]["created"] is False


def test_delete_file(tmp_path):
    p = tmp_path / "del.txt"
    p.write_text("x")
    result = delete_file(str(p))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["deleted"] is True
    assert not p.exists()


def test_delete_file_missing(tmp_path):
    result = delete_file(str(tmp_path / "missing.txt"))
    assert_envelope(result)
    assert not result["success"]


def test_delete_directory_non_empty_without_recursive(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "file.txt").write_text("x")
    result = delete_directory(str(d))
    assert_envelope(result)
    assert not result["success"]
    assert d.exists()


def test_delete_directory_recursive(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "file.txt").write_text("x")
    result = delete_directory(str(d), recursive=True)
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["removed"] is True
    assert not d.exists()


def test_delete_directory_empty(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    result = delete_directory(str(d))
    assert_envelope(result)
    assert result["success"]
    assert not d.exists()


def test_move_file(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("move me")
    dst = tmp_path / "sub" / "dst.txt"
    result = move_file(str(src), str(dst))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["moved"] is True
    assert not src.exists()
    assert dst.read_text() == "move me"


def test_move_file_missing_source(tmp_path):
    result = move_file(str(tmp_path / "missing.txt"), str(tmp_path / "dst.txt"))
    assert_envelope(result)
    assert not result["success"]


def test_copy_file(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("copy me")
    dst = tmp_path / "sub" / "dst.txt"
    result = copy_file(str(src), str(dst))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["copied"] is True
    assert src.exists()
    assert dst.read_text() == "copy me"


def test_copy_file_missing_source(tmp_path):
    result = copy_file(str(tmp_path / "missing.txt"), str(tmp_path / "dst.txt"))
    assert_envelope(result)
    assert not result["success"]
