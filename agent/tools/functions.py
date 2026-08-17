# this is a file for Draft mainly it consists of all tools
from __future__ import annotations
import ast
import json
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.request import Request, urlopen


# ============================================================
# Common Helpers
# ============================================================

def success(data: Any = None, message: str | None = None) -> dict[str, Any]:
    """Return a successful result envelope.

    The envelope always contains exactly four keys: success, data,
    message, error. The returned dict is JSON-serializable.
    """
    return {"success": True, "data": data, "message": message, "error": None}


def failure(
    error: str | Exception,
    data: Any = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Return a failed result envelope.

    error is converted with str(error). The envelope always contains
    exactly four keys: success, data, message, error. The returned
    dict is JSON-serializable.
    """
    return {"success": False, "data": data, "message": message, "error": str(error)}


IGNORED_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "draft_venv", "__pycache__",
    "node_modules", ".mypy_cache", ".pytest_cache", "dist", "build",
})


def _walk_files(root: Path) -> Iterator[Path]:
    """Yield files under root, skipping IGNORED_DIRS at any depth.

    Ignored directories are pruned before descending so their trees
    are never traversed (draft_venv alone holds tens of thousands of
    files). The root path itself is never filtered: an explicitly
    requested root is always walked even if its name is in
    IGNORED_DIRS, since filtering only applies to directories
    encountered during recursion.
    """
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for name in files:
            yield Path(current) / name


def _resolve_path(path: str | Path = ".") -> Path:
    """Resolve a path and return it as a Path object.

    Does expanduser then absolute resolution. "." (or "" or omitted)
    resolves to the project root: the git top-level when detectable,
    else CWD. This fixes "." meaning the agent process CWD (agent/)
    rather than the repo root. Other relative paths resolve against
    CWD, preserving existing semantics. Absolute paths are used
    as-is. No confinement: resolved paths may lie anywhere.
    """
    if path is None or str(path) in ("", "."):
        root = _get_project_root()
        if root is not None:
            return root
        return Path.cwd().resolve()
    return Path(path).expanduser().resolve()


def _require_file(path: Path) -> Path:
    """Return path if it exists and is a file, else raise ValueError."""
    if not path.exists() or not path.is_file():
        raise ValueError(f"File not found: {path}")
    return path


def _require_dir(path: Path) -> Path:
    """Return path if it exists and is a directory, else raise ValueError."""
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Directory not found: {path}")
    return path


def _get_project_root(start: str = ".") -> Path | None:
    """Return the git top-level containing start, or None if unavailable.

    Never raises: on any failure (no repo, git missing, timeout,
    invalid start path) it returns None per its documented contract
    "git root not available".
    """
    cwd = Path(start).expanduser().resolve()
    result = _run_subprocess(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        timeout=10,
    )
    if result["success"]:
        return Path(result["stdout"].strip())
    return None


def _run_subprocess(
    command: list[str] | str,
    cwd: str | Path | None = None,
    timeout: int | None = 30,
    max_output_chars: int = 20_000,
) -> dict[str, Any]:
    """Run a subprocess and return a structured detail dict. Never raises.

    Return keys: success (bool), returncode (int|None), stdout (str),
    stderr (str), timed_out (bool), error (str|None). stdout and
    stderr are always str, each truncated to max_output_chars with an
    explicit "...[truncated]" marker appended when truncation happens.

    A string command is executed through the shell (shell=True) to
    allow shell syntax (pipes, redirects); this is NOT safe for
    untrusted input. A list command runs without a shell.

    If cwd is None the command runs in the project root (same
    resolution as _resolve_path(".")). A given cwd is resolved and
    validated; if it is not a directory, a failure dict is returned.

    This helper returns the subprocess detail dict, not the
    success()/failure() envelope; callers (git tools, run_*) wrap it
    into the envelope themselves.
    """
    if cwd is not None:
        workdir = Path(cwd).expanduser().resolve()
        if not workdir.is_dir():
            message = f"Invalid working directory: {cwd}"
            return {
                "success": False,
                "returncode": None,
                "stdout": "",
                "stderr": message,
                "timed_out": False,
                "error": message,
            }
    else:
        workdir = _resolve_path(".")

    def truncate(stream: str | None) -> str:
        if stream is None:
            return ""
        if len(stream) <= max_output_chars:
            return stream
        return stream[:max_output_chars] + "\n...[truncated]"

    try:
        result = subprocess.run(
            command,
            cwd=str(workdir),
            shell=isinstance(command, str),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": truncate(result.stdout),
            "stderr": truncate(result.stderr),
            "timed_out": False,
            "error": None,
        }

    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "returncode": None,
            "stdout": truncate(exc.stdout),
            "stderr": truncate(exc.stderr),
            "timed_out": True,
            "error": f"Command timed out after {timeout}s",
        }

    except FileNotFoundError as exc:
        cmd = command if isinstance(command, str) else " ".join(command)
        return {
            "success": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "error": f"Command not found: {cmd}",
        }

    except Exception as exc:
        return {
            "success": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "error": str(exc),
        }


# ============================================================
# 1. FILESYSTEM
# ============================================================


def list_files(directory: str = ".") -> list[str]:
    """
    List files and directories inside the given directory.

    Args:
        directory: Directory path to inspect. Defaults to the current directory.

    Returns:
        A list containing the paths of files and directories.
    """
    path = Path(directory)
    
    if not path.exists():
        return [f"Error: directory does not exist: {directory}"]
    
    if not path.is_dir():
        return [f"Error: path is not a directory: {directory}"]
    return [str(item) for item in path.iterdir()]

def list_directory_tree(
    path: str = ".",
    depth: int = 3,
) -> list[str]:
    """
    Return a recursive directory tree up to the specified depth.
    """
    root = _resolve_path(path)

    if not root.exists():
        return [f"Error: path does not exist: {path}"]

    if not root.is_dir():
        return [f"Error: path is not a directory: {path}"]

    results: list[str] = []

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        relative = current_path.relative_to(root)

        current_depth = 0 if relative == Path(".") else len(relative.parts)

        if current_depth >= depth:
            dirs[:] = []

        dirs.sort()
        files.sort()

        indent = "  " * current_depth

        for directory in dirs:
            results.append(f"{indent}{directory}/")

        for file in files:
            results.append(f"{indent}{file}")

    return results


def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """
    Read a text file, optionally restricting the returned line range.
    """
    file_path = _resolve_path(path)

    if not file_path.exists():
        return f"Error: file does not exist: {path}"

    if not file_path.is_file():
        return f"Error: path is not a file: {path}"

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: file is not a UTF-8 text file: {path}"

    if start_line is None and end_line is None:
        return content

    lines = content.splitlines()

    start = 1 if start_line is None else max(start_line, 1)
    end = len(lines) if end_line is None else min(end_line, len(lines))

    if start > end:
        return ""

    return "\n".join(lines[start - 1:end])


def write_file(
    path: str,
    content: str,
    overwrite: bool = True,
) -> str:
    """
    Write text content to a file.
    """
    file_path = _resolve_path(path)

    if file_path.exists() and not overwrite:
        return f"Error: file already exists: {path}"

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote file: {file_path}"
    except Exception as exc:
        return f"Error writing file: {exc}"


def get_file_info(path: str) -> dict[str, Any]:
    """
    Return metadata about a file or directory.
    """
    file_path = _resolve_path(path)

    if not file_path.exists():
        return {
            "error": f"path does not exist: {path}"
        }

    stat = file_path.stat()

    return {
        "path": str(file_path),
        "name": file_path.name,
        "type": "directory" if file_path.is_dir() else "file",
        "size_bytes": stat.st_size,
        "modified_time": datetime.fromtimestamp(
            stat.st_mtime
        ).isoformat(),
        "created_time": datetime.fromtimestamp(
            stat.st_ctime
        ).isoformat(),
        "extension": file_path.suffix if file_path.is_file() else None,
    }


def create_directory(path: str) -> str:
    """
    Create a directory and any missing parent directories.
    """
    directory = _resolve_path(path)

    try:
        directory.mkdir(parents=True, exist_ok=True)
        return f"Directory created: {directory}"
    except Exception as exc:
        return f"Error creating directory: {exc}"


def delete_file(path: str) -> str:
    """
    Delete a file.
    """
    file_path = _resolve_path(path)

    if not file_path.exists():
        return f"Error: file does not exist: {path}"

    if not file_path.is_file():
        return f"Error: path is not a file: {path}"

    try:
        file_path.unlink()
        return f"Deleted file: {file_path}"
    except Exception as exc:
        return f"Error deleting file: {exc}"


def delete_directory(
    path: str,
    recursive: bool = False,
) -> str:
    """
    Delete a directory.

    recursive=False only removes an empty directory.
    """
    directory = _resolve_path(path)

    if not directory.exists():
        return f"Error: directory does not exist: {path}"

    if not directory.is_dir():
        return f"Error: path is not a directory: {path}"

    try:
        if recursive:
            shutil.rmtree(directory)
        else:
            directory.rmdir()

        return f"Deleted directory: {directory}"

    except OSError as exc:
        return f"Error deleting directory: {exc}"


def move_file(
    source: str,
    destination: str,
) -> str:
    """
    Move a file or directory.
    """
    src = _resolve_path(source)
    dst = _resolve_path(destination)

    if not src.exists():
        return f"Error: source does not exist: {source}"

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved {src} -> {dst}"
    except Exception as exc:
        return f"Error moving path: {exc}"


def copy_file(
    source: str,
    destination: str,
) -> str:
    """
    Copy a file or directory.
    """
    src = _resolve_path(source)
    dst = _resolve_path(destination)

    if not src.exists():
        return f"Error: source does not exist: {source}"

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

        return f"Copied {src} -> {dst}"
    except Exception as exc:
        return f"Error copying path: {exc}"


# ============================================================
# 2. CODE SEARCH
# ============================================================

def find_files(
    pattern: str,
    path: str = ".",
) -> list[str]:
    """
    Find files using pathlib glob patterns.

    Examples:
        *.py
        **/*.py
        test_*.py
    """
    root = _resolve_path(path)

    if not root.exists():
        return [f"Error: path does not exist: {path}"]

    try:
        return [
            str(item)
            for item in root.glob(pattern)
            if item.is_file()
        ]
    except Exception as exc:
        return [f"Error searching files: {exc}"]


def grep(
    pattern: str,
    path: str = ".",
    ignore_case: bool = False,
) -> list[dict[str, Any]]:
    """
    Search text files using a regular expression.
    """
    root = _resolve_path(path)

    if not root.exists():
        return [{"error": f"path does not exist: {path}"}]

    flags = re.IGNORECASE if ignore_case else 0

    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return [{"error": f"Invalid regex: {exc}"}]

    files = [root] if root.is_file() else root.rglob("*")

    results: list[dict[str, Any]] = []

    for file_path in files:
        if not file_path.is_file():
            continue

        # Skip common generated / binary directories.
        if any(
            part in {".git", ".venv", "venv", "__pycache__", "node_modules"}
            for part in file_path.parts
        ):
            continue

        try:
            text = file_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                results.append({
                    "file": str(file_path),
                    "line": line_number,
                    "text": line,
                })

    return results


def search_code(
    query: str,
    path: str = ".",
    extensions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Search source code for a plain-text query.
    """
    root = _resolve_path(path)

    if not root.exists():
        return [{"error": f"path does not exist: {path}"}]

    if extensions is None:
        extensions = [
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".go",
            ".rs",
            ".cs",
            ".sql",
            ".html",
            ".css",
        ]

    query_lower = query.lower()

    files = [root] if root.is_file() else root.rglob("*")

    results: list[dict[str, Any]] = []

    for file_path in files:
        if not file_path.is_file():
            continue

        if extensions and file_path.suffix.lower() not in extensions:
            continue

        if any(
            part in {".git", ".venv", "venv", "__pycache__", "node_modules"}
            for part in file_path.parts
        ):
            continue

        try:
            lines = file_path.read_text(
                encoding="utf-8",
                errors="ignore",
            ).splitlines()
        except Exception:
            continue

        for line_number, line in enumerate(lines, start=1):
            if query_lower in line.lower():
                results.append({
                    "file": str(file_path),
                    "line": line_number,
                    "text": line.strip(),
                })

    return results


def find_symbol(
    symbol: str,
    path: str = ".",
) -> list[dict[str, Any]]:
    """
    Find Python functions/classes/variables matching a symbol name.
    """
    root = _resolve_path(path)

    if not root.exists():
        return [{"error": f"path does not exist: {path}"}]

    files = [root] if root.is_file() else root.rglob("*.py")

    results: list[dict[str, Any]] = []

    for file_path in files:
        if not file_path.is_file():
            continue

        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            ) and node.name == symbol:

                results.append({
                    "file": str(file_path),
                    "line": node.lineno,
                    "type": type(node).__name__,
                    "name": node.name,
                })

    return results


def find_references(
    symbol: str,
    path: str = ".",
) -> list[dict[str, Any]]:
    """
    Find textual references to a symbol.
    """
    return grep(
        rf"\b{re.escape(symbol)}\b",
        path,
    )


def get_file_symbols(path: str) -> list[dict[str, Any]]:
    """
    Return top-level Python classes and functions in a file.
    """
    file_path = _resolve_path(path)

    if not file_path.exists():
        return [{"error": f"file does not exist: {path}"}]

    if file_path.suffix != ".py":
        return [{"error": "get_file_symbols currently supports Python files only."}]

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as exc:
        return [{"error": str(exc)}]

    results = []

    for node in tree.body:
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):
            results.append({
                "name": node.name,
                "type": type(node).__name__,
                "line": node.lineno,
            })

    return results


# ============================================================
# 3. CODE EDITING
# ============================================================

def apply_patch(
    file: str,
    patch: str,
) -> dict[str, Any]:
    """
    Apply a unified diff patch to a single file.

    The patch must contain changes for the specified file.

    Args:
        file: Path to the target file.
        patch: Unified diff text.

    Returns:
        {
            "success": bool,
            "file": str,
            "message": str,
            "error": str | None
        }
    """
    file_path = _resolve_path(file)

    if not file_path.exists():
        return {
            "success": False,
            "file": str(file_path),
            "message": "Patch failed.",
            "error": f"File does not exist: {file}",
        }

    if not file_path.is_file():
        return {
            "success": False,
            "file": str(file_path),
            "message": "Patch failed.",
            "error": f"Path is not a file: {file}",
        }

    if not patch.strip():
        return {
            "success": False,
            "file": str(file_path),
            "message": "Patch failed.",
            "error": "Patch is empty.",
        }

    try:
        original = file_path.read_text(encoding="utf-8")

        # The patch is applied through git's patch engine,
        # but only against the specified file.
        process = subprocess.run(
            ["git", "apply", "--unidiff-zero", "--whitespace=nowarn", "-"],
            cwd=file_path.parent,
            input=patch,
            capture_output=True,
            text=True,
        )

        if process.returncode != 0:
            return {
                "success": False,
                "file": str(file_path),
                "message": "Patch could not be applied.",
                "error": process.stderr.strip() or process.stdout.strip(),
            }

        modified = file_path.read_text(encoding="utf-8")

        return {
            "success": True,
            "file": str(file_path),
            "message": "Patch applied successfully.",
            "error": None,
            "changed": original != modified,
        }

    except UnicodeDecodeError:
        return {
            "success": False,
            "file": str(file_path),
            "message": "Patch failed.",
            "error": "File is not a UTF-8 text file.",
        }

    except Exception as exc:
        return {
            "success": False,
            "file": str(file_path),
            "message": "Patch failed.",
            "error": str(exc),
        }

def insert_text(
    path: str,
    line: int,
    text: str,
) -> str:
    """
    Insert text before the specified 1-based line number.
    """
    file_path = _resolve_path(path)

    if not file_path.exists():
        return f"Error: file does not exist: {path}"

    try:
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)

        index = max(0, min(line - 1, len(lines)))

        if not text.endswith("\n"):
            text += "\n"

        lines.insert(index, text)

        file_path.write_text(
            "".join(lines),
            encoding="utf-8",
        )

        return f"Inserted text at line {line}."

    except Exception as exc:
        return f"Error inserting text: {exc}"


def replace_text(
    path: str,
    old: str,
    new: str,
    count: int = -1,
) -> str:
    """
    Replace occurrences of text in a file.

    count=-1 replaces every occurrence.
    """
    file_path = _resolve_path(path)

    if not file_path.exists():
        return f"Error: file does not exist: {path}"

    try:
        content = file_path.read_text(encoding="utf-8")

        occurrences = content.count(old)

        if occurrences == 0:
            return "No matching text found."

        content = content.replace(old, new, count)

        file_path.write_text(
            content,
            encoding="utf-8",
        )

        replaced = occurrences if count == -1 else min(occurrences, count)

        return f"Replaced {replaced} occurrence(s)."

    except Exception as exc:
        return f"Error replacing text: {exc}"


def delete_lines(
    path: str,
    start_line: int,
    end_line: int,
) -> str:
    """
    Delete a range of 1-based inclusive lines.
    """
    file_path = _resolve_path(path)

    if not file_path.exists():
        return f"Error: file does not exist: {path}"

    if start_line < 1 or end_line < start_line:
        return "Error: invalid line range."

    try:
        lines = file_path.read_text(
            encoding="utf-8"
        ).splitlines(keepends=True)

        del lines[start_line - 1:end_line]

        file_path.write_text(
            "".join(lines),
            encoding="utf-8",
        )

        return f"Deleted lines {start_line}-{end_line}."

    except Exception as exc:
        return f"Error deleting lines: {exc}"


# ============================================================
# 4. EXECUTION
# ============================================================

def run_command(
    cmd: str,
    cwd: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Execute a shell command.
    """
    return _run_subprocess(
        cmd,
        cwd=cwd,
        timeout=timeout,
    )


def run_python(
    file: str,
    args: list[str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Execute a Python file using the current Python interpreter.
    """
    file_path = _resolve_path(file)

    if not file_path.exists():
        return {
            "success": False,
            "error": f"Python file does not exist: {file}",
        }

    command = [sys.executable, str(file_path)]

    if args:
        command.extend(args)

    return _run_subprocess(
        command,
        cwd=file_path.parent,
        timeout=timeout,
    )


def run_tests(
    cmd: str = "pytest",
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """
    Run the project's test command.
    """
    return _run_subprocess(
        cmd,
        cwd=cwd,
        timeout=timeout,
    )


def check_syntax(
    path: str,
) -> dict[str, Any]:
    """
    Check Python syntax without executing the file.
    """
    file_path = _resolve_path(path)

    if not file_path.exists():
        return {
            "success": False,
            "error": f"File does not exist: {path}",
        }

    try:
        source = file_path.read_text(encoding="utf-8")
        ast.parse(source)

        return {
            "success": True,
            "file": str(file_path),
        }

    except SyntaxError as exc:
        return {
            "success": False,
            "file": str(file_path),
            "error": str(exc),
            "line": exc.lineno,
            "column": exc.offset,
        }


def lint_project(
    cmd: str = "ruff check .",
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """
    Run the project's linting command.
    """
    return _run_subprocess(
        cmd,
        cwd=cwd,
        timeout=timeout,
    )


def typecheck_project(
    cmd: str = "mypy .",
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """
    Run the project's type-checking command.
    """
    return _run_subprocess(
        cmd,
        cwd=cwd,
        timeout=timeout,
    )


# ============================================================
# 5. ENVIRONMENT
# ============================================================

def get_current_directory() -> str:
    """
    Return the current working directory.
    """
    return str(Path.cwd())


def get_project_root(
    path: str = ".",
) -> str:
    """
    Try to identify the Git project root.
    Falls back to the resolved path.
    """
    result = _run_subprocess(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
    )

    if result["success"]:
        return result["stdout"].strip()

    return str(_resolve_path(path))


def get_environment() -> dict[str, str]:
    """
    Return environment variables.
    """
    return dict(os.environ)


def get_python_version() -> str:
    """
    Return the running Python version.
    """
    return sys.version


def which_command(
    command: str,
) -> str | None:
    """
    Find the executable location for a command.
    """
    return shutil.which(command)


# ============================================================
# 6. PROJECT UNDERSTANDING
# ============================================================

def inspect_project(
    path: str = ".",
) -> dict[str, Any]:
    """
    Gather useful high-level project information.
    """
    root = _resolve_path(path)

    if not root.exists():
        return {"error": f"path does not exist: {path}"}

    files = [
        item.name
        for item in root.iterdir()
        if item.is_file()
    ]

    directories = [
        item.name
        for item in root.iterdir()
        if item.is_dir()
    ]

    return {
        "project_root": str(root),
        "files": sorted(files),
        "directories": sorted(directories),
        "git_repository": (root / ".git").exists(),
        "python_project": any(
            name in files
            for name in (
                "pyproject.toml",
                "requirements.txt",
                "setup.py",
                "setup.cfg",
            )
        ),
        "node_project": "package.json" in files,
        "docker_project": (
            "Dockerfile" in files
            or "docker-compose.yml" in files
            or "compose.yml" in files
        ),
    }


def detect_project_type(
    path: str = ".",
) -> list[str]:
    """
    Detect likely project types from common project files.
    """
    root = _resolve_path(path)

    if not root.exists():
        return [f"Error: path does not exist: {path}"]

    types: list[str] = []

    markers = {
        "Python": [
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
        ],
        "Node.js": ["package.json"],
        "Rust": ["Cargo.toml"],
        "Go": ["go.mod"],
        "Java": ["pom.xml", "build.gradle"],
        "C/C++": ["CMakeLists.txt"],
        "Docker": ["Dockerfile"],
    }

    for project_type, files in markers.items():
        if any((root / filename).exists() for filename in files):
            types.append(project_type)

    return types or ["Unknown"]


def get_project_metadata(
    path: str = ".",
) -> dict[str, Any]:
    """
    Return metadata from common project configuration files.
    """
    root = _resolve_path(path)

    metadata: dict[str, Any] = {
        "root": str(root),
        "project_types": detect_project_type(path),
    }

    for filename in [
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
    ]:
        file_path = root / filename

        if file_path.exists():
            try:
                content = file_path.read_text(
                    encoding="utf-8"
                )

                metadata[filename] = content

            except Exception as exc:
                metadata[filename] = f"Error: {exc}"

    return metadata


# ============================================================
# 7. GIT
# ============================================================

def git_status(
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Return Git status information.
    """
    return _run_subprocess(
        ["git", "status", "--short", "--branch"],
        cwd=cwd,
    )


def git_diff(
    path: str | None = None,
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Show current unstaged Git diff.
    """
    command = ["git", "diff"]

    if path:
        command.append(path)

    return _run_subprocess(
        command,
        cwd=cwd,
    )


def git_log(
    n: int = 10,
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Return recent Git commits.
    """
    return _run_subprocess(
        [
            "git",
            "log",
            f"-{n}",
            "--oneline",
            "--decorate",
        ],
        cwd=cwd,
    )


def git_show(
    commit: str = "HEAD",
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Show a specific Git commit.
    """
    return _run_subprocess(
        ["git", "show", commit],
        cwd=cwd,
    )


def git_branch(
    cwd: str = ".",
) -> dict[str, Any]:
    """
    List local Git branches.
    """
    return _run_subprocess(
        ["git", "branch", "--list"],
        cwd=cwd,
    )


def git_branch_create(
    name: str,
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Create a new Git branch.
    """
    return _run_subprocess(
        ["git", "branch", name],
        cwd=cwd,
    )


def git_branch_switch(
    name: str,
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Switch to an existing Git branch.
    """
    return _run_subprocess(
        ["git", "switch", name],
        cwd=cwd,
    )


def git_add(
    paths: list[str],
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Stage files for commit.
    """
    if not paths:
        return {
            "success": False,
            "error": "No paths provided.",
        }

    return _run_subprocess(
        ["git", "add", *paths],
        cwd=cwd,
    )


def git_commit(
    message: str,
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Create a Git commit.
    """
    return _run_subprocess(
        ["git", "commit", "-m", message],
        cwd=cwd,
    )


def git_stash(
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Stash current changes.
    """
    return _run_subprocess(
        ["git", "stash"],
        cwd=cwd,
    )


def git_stash_pop(
    cwd: str = ".",
) -> dict[str, Any]:
    """
    Restore the most recent Git stash.
    """
    return _run_subprocess(
        ["git", "stash", "pop"],
        cwd=cwd,
    )


# ============================================================
# 8. WEB
# ============================================================

def search_web(
    query: str,
) -> str:
    """
    Placeholder for a web-search provider.

    This should later be connected to a real search API
    such as Bing Web Search / Azure AI Search / another provider.
    """
    return (
        "search_web is not configured yet. "
        f"Search query: {query}"
    )


def fetch_url(
    url: str,
    timeout: int = 20,
) -> str:
    """
    Fetch text content from a URL.
    """
    try:
        request = Request(
            url,
            headers={
                "User-Agent": "Draft-Coding-Agent/1.0"
            },
        )

        with urlopen(request, timeout=timeout) as response:
            data = response.read()

        return data.decode("utf-8", errors="replace")

    except Exception as exc:
        return f"Error fetching URL: {exc}"


# ============================================================
# 9. UTILITIES
# ============================================================

def get_current_time(
    utc: bool = False,
) -> str:
    """
    Return the current local or UTC time.
    """
    now = (
        datetime.now(timezone.utc)
        if utc
        else datetime.now().astimezone()
    )

    return now.isoformat()


def calculate(
    expression: str,
) -> dict[str, Any]:
    """
    Safely evaluate a mathematical expression.

    Supports arithmetic and selected math functions.
    """
    allowed_names = {
        name: getattr(math, name)
        for name in dir(math)
        if not name.startswith("_")
    }

    allowed_names.update({
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "pow": pow,
    })

    try:
        tree = ast.parse(
            expression,
            mode="eval",
        )

        for node in ast.walk(tree):
            if isinstance(
                node,
                (
                    ast.Import,
                    ast.ImportFrom,
                    ast.Attribute,
                    ast.Subscript,
                    ast.Lambda,
                ),
            ):
                return {
                    "success": False,
                    "error": "Unsupported expression.",
                }

        result = eval(
            compile(tree, "<calculator>", "eval"),
            {"__builtins__": {}},
            allowed_names,
        )

        return {
            "success": True,
            "expression": expression,
            "result": result,
        }

    except Exception as exc:
        return {
            "success": False,
            "expression": expression,
            "error": str(exc),
        }


def generate_uuid() -> str:
    """
    Generate a UUID4.
    """
    return str(uuid.uuid4())