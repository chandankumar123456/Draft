"""Unit tests for the execution tools in tools/functions.py."""

import json
import sys

import pytest

from tools.functions import (
    check_syntax,
    lint_project,
    run_command,
    run_python,
    run_tests,
    typecheck_project,
)

PY = f'"{sys.executable}"'


def assert_envelope(result):
    """Assert the result is a JSON-serializable tool envelope."""
    assert set(result) == {"success", "data", "message", "error"}
    json.dumps(result)


def test_run_command_success():
    result = run_command(f"{PY} --version")
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["returncode"] == 0
    assert "Python" in result["data"]["stdout"]
    assert result["data"]["truncated_stdout"] is False


def test_run_command_failure():
    result = run_command(f'{PY} -c "import sys; sys.exit(3)"')
    assert_envelope(result)
    assert not result["success"]
    assert result["data"]["returncode"] == 3


def test_run_command_timeout():
    result = run_command("ping -n 6 127.0.0.1 >nul", timeout=1)
    assert_envelope(result)
    assert not result["success"]
    assert result["data"]["timed_out"] is True
    assert result["data"]["returncode"] is None


def test_run_command_truncation():
    result = run_command(f'{PY} -c "print(chr(120)*100000)"')
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["truncated_stdout"] is True
    assert len(result["data"]["stdout"]) <= 20100


def test_run_command_empty():
    result = run_command("")
    assert_envelope(result)
    assert not result["success"]


def test_run_python_success(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("print('hello from script')\n")
    result = run_python(str(script))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["returncode"] == 0
    assert "hello from script" in result["data"]["stdout"]
    assert result["data"]["file"] == str(script)


def test_run_python_exit_code(tmp_path):
    script = tmp_path / "fail.py"
    script.write_text("import sys; sys.exit(2)\n")
    result = run_python(str(script))
    assert_envelope(result)
    assert not result["success"]
    assert result["data"]["returncode"] == 2


def test_run_python_args_passthrough(tmp_path):
    script = tmp_path / "args.py"
    script.write_text("import sys; print(sys.argv[1:])\n")
    result = run_python(str(script), args=["--flag", "value"])
    assert_envelope(result)
    assert result["success"]
    assert "--flag" in result["data"]["stdout"]
    assert "value" in result["data"]["stdout"]
    assert result["data"]["args"] == ["--flag", "value"]


def test_run_python_missing_file(tmp_path):
    result = run_python(str(tmp_path / "missing.py"))
    assert_envelope(result)
    assert not result["success"]


def test_run_tests_passed():
    result = run_tests(cmd=f'{PY} -c "import sys; sys.exit(0)"')
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["passed"] is True


def test_run_tests_failed():
    result = run_tests(cmd=f'{PY} -c "import sys; sys.exit(1)"')
    assert_envelope(result)
    assert not result["success"]
    assert result["data"]["passed"] is False
    assert result["data"]["returncode"] == 1


def test_check_syntax_valid(tmp_path):
    p = tmp_path / "ok.py"
    p.write_text("x = 1\nprint(x)\n")
    result = check_syntax(str(p))
    assert_envelope(result)
    assert result["success"]
    assert result["data"]["valid"] is True
    assert isinstance(result["data"]["line_count"], int)
    assert result["data"]["line_count"] >= 1


def test_check_syntax_invalid(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("def broken(:\n")
    result = check_syntax(str(p))
    assert_envelope(result)
    assert not result["success"]
    assert result["data"]["valid"] is False
    assert isinstance(result["data"]["line"], int)
    assert isinstance(result["data"]["column"], int)


def test_check_syntax_missing(tmp_path):
    result = check_syntax(str(tmp_path / "missing.py"))
    assert_envelope(result)
    assert not result["success"]


@pytest.mark.parametrize(
    "tool",
    [lint_project, typecheck_project],
)
@pytest.mark.parametrize("exit_code", [0, 3])
def test_project_tool_command_override(tool, exit_code):
    result = tool(cmd=f'{PY} -c "import sys; sys.exit({exit_code})"')
    assert_envelope(result)
    if exit_code == 0:
        assert result["success"]
    else:
        assert not result["success"]
    assert result["data"]["returncode"] == exit_code
