"""Unit tests for the environment and web tools in tools/functions.py."""

import json
import subprocess
from pathlib import Path

from tools.functions import (
    fetch_url,
    get_current_directory,
    get_environment,
    get_project_root,
    get_python_version,
    search_web,
    which_command,
)


def assert_envelope(result):
    """Assert the result is a JSON-serializable tool envelope."""
    assert set(result) == {"success", "data", "message", "error"}
    json.dumps(result)


def test_get_current_directory():
    result = get_current_directory()
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["cwd"] == str(Path.cwd())


def test_get_project_root_in_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    result = get_project_root(str(repo))
    assert_envelope(result)
    assert result["success"]
    assert Path(result["data"]["project_root"]) == repo.resolve()


def test_get_project_root_not_repo(tmp_path):
    result = get_project_root(str(tmp_path))
    assert_envelope(result)
    assert not result["success"]


def test_get_environment():
    result = get_environment()
    assert_envelope(result)
    assert result["success"]
    data = result["data"]
    for key in (
        "platform",
        "python_version",
        "python_executable",
        "cwd",
        "path_dirs",
        "env_var_names",
        "platform_bits",
    ):
        assert key in data
    assert data["env_var_names"] == sorted(data["env_var_names"])


def test_get_python_version():
    result = get_python_version()
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["version"].startswith("3.")
    assert isinstance(result["data"]["full"], str)


def test_which_command_found():
    result = which_command("python")
    assert_envelope(result)
    assert result["success"]


def test_which_command_empty():
    result = which_command("")
    assert_envelope(result)
    assert not result["success"]


def test_search_web_placeholder():
    result = search_web("anything")
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["available"] is False


def test_search_web_empty_query():
    result = search_web("")
    assert_envelope(result)
    assert not result["success"]


def test_fetch_url_data_scheme():
    result = fetch_url("data:text/plain,hello%20world")
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["content"] == "hello world"
    assert result["data"]["truncated"] is False
    assert isinstance(result["data"]["bytes_read"], int)


def test_fetch_url_invalid():
    result = fetch_url("not a url")
    assert_envelope(result)
    assert not result["success"]
    assert result["data"] == {"url": "not a url", "status": None}
