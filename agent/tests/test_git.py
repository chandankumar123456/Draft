"""Unit tests for the git tools in tools/functions.py.

All git tests run against a scratch repository created in tmp_path;
the real repository is never touched.
"""

import json
import subprocess

import pytest

from tools.functions import (
    git_add,
    git_branch,
    git_branch_create,
    git_branch_switch,
    git_commit,
    git_diff,
    git_log,
    git_show,
    git_stash,
    git_stash_pop,
    git_status,
    write_file,
)


def assert_envelope(result):
    """Assert the result is a JSON-serializable tool envelope."""
    assert set(result) == {"success", "data", "message", "error"}
    json.dumps(result)


@pytest.fixture()
def scratch_repo(tmp_path):
    """Create an initialized scratch git repo with local user config."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return repo


def test_git_add_and_commit(scratch_repo):
    write_file(str(scratch_repo / "f.txt"), "alpha\n")
    added = git_add(["."], cwd=str(scratch_repo))
    assert_envelope(added)
    assert added["success"]
    committed = git_commit("init", cwd=str(scratch_repo))
    assert_envelope(committed)
    assert committed["success"]
    assert committed["data"]["message"] == "init"
    status = git_status(cwd=str(scratch_repo))
    assert status["data"]["clean"] is True


def test_git_status_branch(scratch_repo):
    write_file(str(scratch_repo / "f.txt"), "alpha\n")
    git_add(["."], cwd=str(scratch_repo))
    git_commit("init", cwd=str(scratch_repo))
    result = git_status(cwd=str(scratch_repo))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["branch"] in ("main", "master")


def test_git_diff(scratch_repo):
    write_file(str(scratch_repo / "f.txt"), "alpha\n")
    git_add(["."], cwd=str(scratch_repo))
    git_commit("init", cwd=str(scratch_repo))
    write_file(str(scratch_repo / "f.txt"), "beta\n")
    result = git_diff(cwd=str(scratch_repo))
    assert_envelope(result)
    assert result["success"]
    assert "-alpha" in result["data"]["stdout"]


def test_git_log(scratch_repo):
    write_file(str(scratch_repo / "f.txt"), "alpha\n")
    git_add(["."], cwd=str(scratch_repo))
    git_commit("init", cwd=str(scratch_repo))
    result = git_log(cwd=str(scratch_repo))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["entries"]
    assert result["data"]["count"] == len(result["data"]["entries"])


def test_git_show_head(scratch_repo):
    write_file(str(scratch_repo / "f.txt"), "alpha\n")
    git_add(["."], cwd=str(scratch_repo))
    git_commit("init", cwd=str(scratch_repo))
    result = git_show("HEAD", cwd=str(scratch_repo))
    assert_envelope(result)
    assert result["success"]
    assert "init" in result["data"]["stdout"]


def test_git_branch_current(scratch_repo):
    write_file(str(scratch_repo / "f.txt"), "alpha\n")
    git_add(["."], cwd=str(scratch_repo))
    git_commit("init", cwd=str(scratch_repo))
    result = git_branch(cwd=str(scratch_repo))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["branches"]
    assert result["data"]["current"] in ("main", "master")


def test_git_branch_create_and_switch(scratch_repo):
    write_file(str(scratch_repo / "f.txt"), "alpha\n")
    git_add(["."], cwd=str(scratch_repo))
    git_commit("init", cwd=str(scratch_repo))
    created = git_branch_create("feature", cwd=str(scratch_repo))
    assert_envelope(created)
    assert created["success"]
    switched = git_branch_switch("feature", cwd=str(scratch_repo))
    assert_envelope(switched)
    assert switched["success"]
    status = git_status(cwd=str(scratch_repo))
    assert status["data"]["branch"] == "feature"


def test_git_stash_and_pop(scratch_repo):
    f = scratch_repo / "f.txt"
    write_file(str(f), "alpha\n")
    git_add(["."], cwd=str(scratch_repo))
    git_commit("init", cwd=str(scratch_repo))
    write_file(str(f), "beta\n")
    stashed = git_stash(cwd=str(scratch_repo))
    assert_envelope(stashed)
    assert stashed["success"]
    assert stashed["data"]["stashed"] is True
    assert f.read_text() == "alpha\n"
    popped = git_stash_pop(cwd=str(scratch_repo))
    assert_envelope(popped)
    assert popped["success"]
    assert popped["data"]["popped"] is True
    assert f.read_text() == "beta\n"


def test_git_commit_empty_message(scratch_repo):
    result = git_commit("", cwd=str(scratch_repo))
    assert_envelope(result)
    assert not result["success"]


def test_git_add_no_paths(scratch_repo):
    result = git_add([], cwd=str(scratch_repo))
    assert_envelope(result)
    assert not result["success"]


def test_git_show_bad_commit(scratch_repo):
    result = git_show("nonexistent-hash", cwd=str(scratch_repo))
    assert_envelope(result)
    assert not result["success"]


def test_git_status_invalid_cwd():
    result = git_status(cwd=r"C:\does-not-exist")
    assert_envelope(result)
    assert not result["success"]
    assert "Invalid working directory" in result["error"]
