"""Unit tests for the project-understanding tools in tools/functions.py."""

import json
from pathlib import Path

from tools.functions import (
    detect_project_type,
    get_project_metadata,
    inspect_project,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
assert (REPO_ROOT / "agent" / "tools" / "functions.py").is_file()


def assert_envelope(result):
    """Assert the result is a JSON-serializable tool envelope."""
    assert set(result) == {"success", "data", "message", "error"}
    json.dumps(result)


def test_inspect_project_repo_root():
    result = inspect_project(str(REPO_ROOT))
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    assert isinstance(data["file_count"], int)
    assert data["file_count"] > 0
    assert data["has_git"] is True
    top_names = [entry["name"] for entry in data["top_level"]]
    assert top_names == sorted(top_names, key=str.lower)
    assert all(set(entry) == {"name", "type"} for entry in data["top_level"])


def test_detect_project_type_with_markers(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    result = detect_project_type(str(tmp_path))
    assert_envelope(result)
    assert result["success"]
    assert "Node.js" in result["data"]["project_types"]
    assert "Docker" in result["data"]["project_types"]


def test_detect_project_type_empty(tmp_path):
    result = detect_project_type(str(tmp_path))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["project_types"] == []


def test_get_project_metadata_package_json(tmp_path):
    content = json.dumps(
        {
            "name": "demo-app",
            "version": "1.2.3",
            "description": "demo application",
            "scripts": {"start": "node index.js"},
            "dependencies": {"express": "^4.18.0"},
        }
    )
    (tmp_path / "package.json").write_text(content)
    result = get_project_metadata(str(tmp_path))
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    assert data["name"] == "demo-app"
    assert data["version"] == "1.2.3"
    assert data["description"] == "demo application"
    assert data["scripts"] == {"start": "node index.js"}
    assert data["dependencies"] == ["express@^4.18.0"]
    assert data["sources"]["package.json"] is True
    assert content not in json.dumps(data)


def test_get_project_metadata_repo_root():
    result = get_project_metadata(str(REPO_ROOT))
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    assert data["dependencies"]
    assert data["sources"]["requirements.txt"] is True
    assert data["sources"]["pyproject.toml"] is False


def test_get_project_metadata_missing_path(tmp_path):
    result = get_project_metadata(str(tmp_path / "missing"))
    assert_envelope(result)
    assert not result["success"]
