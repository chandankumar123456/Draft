# this is a file for Draft mainly it consists of all tools
from __future__ import annotations
import ast
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
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
# ============================================================
# 1. FILESYSTEM
# ============================================================

MAX_TREE_ENTRIES = 500
MAX_READ_CHARS = 50_000


def list_files(directory: str = ".") -> dict[str, Any]:
    """List files and directories inside the given directory.

    Args:
        directory: Directory path to inspect. Defaults to the current
            directory.

    Returns:
        A success/failure envelope. On success, data is a sorted list
        of {"name": str, "type": "file"|"dir"} entries, sorted
        case-insensitively by name for deterministic ordering.
    """
    path = _resolve_path(directory)

    try:
        path = _require_dir(path)
    except ValueError as exc:
        return failure(str(exc))

    try:
        entries = [
            {
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            }
            for item in path.iterdir()
        ]
    except OSError as exc:
        return failure(f"Failed to list directory: {exc}")

    entries.sort(key=lambda entry: entry["name"].lower())

    return success(
        entries,
        message=f"Listed {len(entries)} entries in {path}",
    )


def list_directory_tree(
    path: str = ".",
    depth: int = 3,
) -> dict[str, Any]:
    """Return a recursive directory tree up to the specified depth.

    Ignored directories (IGNORED_DIRS) are pruned at any depth; the
    requested root itself is never filtered. Entries are sorted
    case-insensitively at each level. depth=0 returns only the root.

    Args:
        path: Directory to walk. Defaults to the current directory.
        depth: Maximum depth below the root to include. Must be >= 0.

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "entries": [{"path": str, "depth": int,
        "type": "file"|"dir"}, ...], "truncated": bool}. Entries are
        capped at MAX_TREE_ENTRIES; when the cap is hit truncated is
        True and the message notes the truncation. Unreadable
        subdirectories are skipped (their subtrees are omitted).
    """
    root = _resolve_path(path)

    try:
        root = _require_dir(root)
    except ValueError as exc:
        return failure(str(exc))

    if depth < 0:
        return failure(f"depth must be >= 0, got {depth}")

    entries: list[dict[str, Any]] = [
        {"path": str(root), "depth": 0, "type": "dir"}
    ]
    truncated = False

    def walk(current: Path, current_depth: int) -> None:
        nonlocal truncated
        if truncated or current_depth >= depth:
            return
        try:
            children = sorted(
                current.iterdir(),
                key=lambda child: child.name.lower(),
            )
        except OSError:
            return
        for child in children:
            if truncated:
                return
            if child.name in IGNORED_DIRS and child.is_dir():
                continue
            is_dir = child.is_dir()
            entries.append(
                {
                    "path": str(child),
                    "depth": current_depth + 1,
                    "type": "dir" if is_dir else "file",
                }
            )
            if len(entries) >= MAX_TREE_ENTRIES:
                truncated = True
                return
            if is_dir:
                walk(child, current_depth + 1)

    walk(root, 0)

    return success(
        {
            "path": str(root),
            "entries": entries,
            "truncated": truncated,
        },
        message=(
            f"Tree truncated at {MAX_TREE_ENTRIES} entries"
            if truncated
            else f"Listed {len(entries)} entries"
        ),
    )


def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    """Read a text file, optionally restricting the returned line range.

    The returned content is prefixed with 1-based line numbers in the
    form "<n>: <text>" per line. Ranges are inclusive; start_line and
    end_line must be >= 1, end_line >= start_line when both given, and
    within the file (out-of-range values fail rather than being
    clamped). Content is capped at MAX_READ_CHARS characters; when the
    cap is hit truncated is True and the message notes it.

    Args:
        path: Path to the file to read.
        start_line: First 1-based line to include.
        end_line: Last 1-based line to include (inclusive).

    Returns:
        A success/failure envelope. On success, data is
        {"content": str, "start_line": int, "end_line": int|None,
        "total_lines": int, "truncated": bool, "path": str}.
    """
    file_path = _resolve_path(path)

    try:
        file_path = _require_file(file_path)
    except ValueError as exc:
        return failure(str(exc))

    if start_line is not None and start_line < 1:
        return failure(f"start_line must be >= 1, got {start_line}")

    if end_line is not None and end_line < 1:
        return failure(f"end_line must be >= 1, got {end_line}")

    if (
        start_line is not None
        and end_line is not None
        and end_line < start_line
    ):
        return failure(
            f"end_line ({end_line}) must be >= start_line ({start_line})"
        )

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return failure(f"File is not a UTF-8 text file: {file_path}")
    except OSError as exc:
        return failure(f"Failed to read file: {exc}")

    total_lines = content.count("\n")
    if content and not content.endswith("\n"):
        total_lines += 1

    if start_line is not None and start_line > total_lines:
        return failure(
            f"start_line ({start_line}) is beyond the end of the "
            f"file ({total_lines} lines): {file_path}"
        )

    if end_line is not None and end_line > total_lines:
        return failure(
            f"end_line ({end_line}) is beyond the end of the "
            f"file ({total_lines} lines): {file_path}"
        )

    effective_start = 1 if start_line is None else start_line
    effective_end = total_lines if end_line is None else end_line

    lines = content.splitlines()
    numbered = "\n".join(
        f"{number}: {line}"
        for number, line in enumerate(
            lines[effective_start - 1:effective_end],
            start=effective_start,
        )
    )

    truncated = False
    if len(numbered) > MAX_READ_CHARS:
        numbered = numbered[:MAX_READ_CHARS] + "\n...[truncated]"
        truncated = True

    return success(
        {
            "content": numbered,
            "start_line": effective_start,
            "end_line": effective_end,
            "total_lines": total_lines,
            "truncated": truncated,
            "path": str(file_path),
        },
        message=(
            f"Truncated at {MAX_READ_CHARS} characters"
            if truncated
            else f"Read {effective_end - effective_start + 1} lines"
        ),
    )


def write_file(
    path: str,
    content: str,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Write text content to a file, creating parent directories.

    Args:
        path: Path of the file to write.
        content: Text content to write (encoded as UTF-8).
        overwrite: Whether to replace an existing file. When False and
            the file already exists, the call fails and nothing is
            written.

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "created": bool, "modified": bool,
        "bytes_written": int} where created means the file did not
        exist before and modified means an existing file was replaced.
    """
    file_path = _resolve_path(path)

    existed = file_path.exists()

    if existed and not overwrite:
        return failure(
            f"File already exists and overwrite is False: {file_path}"
        )

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")
        file_path.write_bytes(encoded)
    except (OSError, ValueError) as exc:
        return failure(f"Failed to write file: {exc}")

    return success(
        {
            "path": str(file_path),
            "created": not existed,
            "modified": existed,
            "bytes_written": len(encoded),
        },
        message="File created" if not existed else "File written",
    )


def get_file_info(path: str) -> dict[str, Any]:
    """Return metadata about a file or directory.

    Args:
        path: Path to the file or directory to inspect.

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "name": str, "type": "file"|"dir",
        "size_bytes": int, "modified_time": str, "created_time": str,
        "extension": str|None}.
    """
    file_path = _resolve_path(path)

    if not file_path.exists():
        return failure(f"Path not found: {file_path}")

    try:
        stat = file_path.stat()
    except OSError as exc:
        return failure(f"Failed to stat path: {exc}")

    is_dir = file_path.is_dir()

    return success(
        {
            "path": str(file_path),
            "name": file_path.name,
            "type": "dir" if is_dir else "file",
            "size_bytes": stat.st_size,
            "modified_time": datetime.fromtimestamp(
                stat.st_mtime
            ).isoformat(),
            "created_time": datetime.fromtimestamp(
                stat.st_ctime
            ).isoformat(),
            "extension": file_path.suffix if not is_dir else None,
        }
    )


def create_directory(path: str) -> dict[str, Any]:
    """Create a directory and any missing parent directories.

    Args:
        path: Path of the directory to create.

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "created": bool}; created is False when the
        directory already existed (still a success).
    """
    directory = _resolve_path(path)

    existed = directory.exists()

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return failure(f"Failed to create directory: {exc}")

    return success(
        {"path": str(directory), "created": not existed},
        message=(
            "Directory already exists"
            if existed
            else "Directory created"
        ),
    )


def delete_file(path: str) -> dict[str, Any]:
    """Delete a file. Directories are never deleted.

    Args:
        path: Path of the file to delete.

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "deleted": True}.
    """
    file_path = _resolve_path(path)

    try:
        file_path = _require_file(file_path)
    except ValueError as exc:
        return failure(str(exc))

    try:
        file_path.unlink()
    except OSError as exc:
        return failure(f"Failed to delete file: {exc}")

    return success(
        {"path": str(file_path), "deleted": True},
        message="File deleted",
    )


def delete_directory(
    path: str,
    recursive: bool = False,
) -> dict[str, Any]:
    """Delete a directory.

    recursive=False only removes an empty directory; a non-empty
    directory fails with a clear message and is never auto-removed.
    recursive=True removes the whole tree with shutil.rmtree.

    Args:
        path: Path of the directory to delete.
        recursive: Whether to remove non-empty directories.

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "recursive": bool, "removed": True}.
    """
    directory = _resolve_path(path)

    try:
        directory = _require_dir(directory)
    except ValueError as exc:
        return failure(str(exc))

    if not recursive:
        try:
            if any(directory.iterdir()):
                return failure(
                    "Directory is not empty and recursive is False: "
                    f"{directory}"
                )
        except OSError as exc:
            return failure(f"Failed to inspect directory: {exc}")

    try:
        if recursive:
            shutil.rmtree(directory)
        else:
            directory.rmdir()
    except OSError as exc:
        return failure(f"Failed to delete directory: {exc}")

    return success(
        {
            "path": str(directory),
            "recursive": recursive,
            "removed": True,
        },
        message="Directory removed",
    )


def move_file(
    source: str,
    destination: str,
) -> dict[str, Any]:
    """Move a file or directory to a new location.

    The destination's parent directory is created if missing; the
    destination is the new path (shutil.move semantics).

    Args:
        source: Path to move.
        destination: Target path.

    Returns:
        A success/failure envelope. On success, data is
        {"source": str, "destination": str, "moved": True}.
    """
    src = _resolve_path(source)

    if not src.exists():
        return failure(f"Source not found: {src}")

    dst = _resolve_path(destination)

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    except OSError as exc:
        return failure(f"Failed to move: {exc}")

    return success(
        {
            "source": str(src),
            "destination": str(dst),
            "moved": True,
        },
        message="Moved successfully",
    )


def copy_file(
    source: str,
    destination: str,
) -> dict[str, Any]:
    """Copy a file or directory to a new location.

    Directories are copied recursively (dirs_exist_ok=True); files use
    copy2. The destination's parent directory is created if missing.

    Args:
        source: Path to copy.
        destination: Target path.

    Returns:
        A success/failure envelope. On success, data is
        {"source": str, "destination": str, "copied": True}.
    """
    src = _resolve_path(source)

    if not src.exists():
        return failure(f"Source not found: {src}")

    dst = _resolve_path(destination)

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    except OSError as exc:
        return failure(f"Failed to copy: {exc}")

    return success(
        {
            "source": str(src),
            "destination": str(dst),
            "copied": True,
        },
        message="Copied successfully",
    )

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

EDIT_TIMEOUT = 30
EDIT_MAX_OUTPUT_CHARS = 20_000


def _run_process_with_input(
    command: list[str],
    cwd: str | Path,
    input_text: str,
    timeout: int = EDIT_TIMEOUT,
    max_output_chars: int = EDIT_MAX_OUTPUT_CHARS,
) -> dict[str, Any]:
    """Run a subprocess with stdin input; return a structured dict. Never raises.

    Mirrors _run_subprocess's return contract: {success, returncode,
    stdout, stderr, timed_out, error}, but additionally feeds
    input_text to the process's stdin, which _run_subprocess cannot
    do. Used by apply_patch to pipe a unified diff into git apply.
    stdout and stderr are truncated to max_output_chars with an
    explicit "...[truncated]" marker appended when truncation happens.
    A string command is never used here; command must be a list run
    without a shell.

    Args:
        command: Executable and arguments (list form, no shell).
        cwd: Working directory for the process (must be a directory).
        input_text: Text written to the process's stdin.
        timeout: Timeout in seconds; the process is killed on expiry.
        max_output_chars: Maximum characters kept from stdout/stderr.

    Returns:
        The subprocess detail dict (not the success()/failure()
        envelope; callers wrap it into the envelope themselves).
    """

    def truncate(stream: str | None) -> str:
        if stream is None:
            return ""
        if len(stream) <= max_output_chars:
            return stream
        return stream[:max_output_chars] + "\n...[truncated]"

    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            input=input_text,
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
        return {
            "success": False,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "error": f"Command not found: {' '.join(command)}",
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


def _git_apply_failure(
    result: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    """Convert a failed git apply result into a failure envelope.

    git-not-available detection: a missing git executable surfaces as
    FileNotFoundError from _run_process_with_input (error starts with
    "Command not found"); a non-zero returncode whose stderr contains
    "not recognized" or "command not found" is also treated as git
    being unavailable. Otherwise the failure detail is the git stderr
    (or stdout when stderr is empty), truncated by the helper.
    """
    error = result["error"] or ""
    stderr = result["stderr"] or ""
    stdout = result["stdout"] or ""
    combined = error + " " + stderr

    if (
        "Command not found" in error
        or "not recognized" in stderr
        or "command not found" in stderr.lower()
    ):
        return failure(
            "git apply is required for apply_patch; git not available"
        )

    if result["timed_out"]:
        return failure(f"{message} (timed out after {EDIT_TIMEOUT}s)")

    detail = stderr.strip() or stdout.strip() or error
    return failure(f"{message}: {detail}")


def apply_patch(
    file: str,
    patch: str,
) -> dict[str, Any]:
    """Apply a unified diff patch to a single file via git apply.

    The patch is first validated with a dry run (`git apply --check`)
    and only applied if that check passes; a malformed patch or one
    that does not match the file content fails with the git stderr and
    the file is left untouched. After a successful apply the file is
    re-read and the result is reported as a failure if the content did
    not change, so a no-op patch is never reported as a success.

    Requires git to be available; if it is not, the call fails rather
    than falling back to a different patch engine.

    Args:
        file: Path to the target file (must exist).
        patch: Unified diff text, fed to git apply on stdin.

    Returns:
        A success/failure envelope. On success, data is
        {"file": str, "changed": bool, "patch_applied": bool}.
    """
    file_path = _resolve_path(file)

    try:
        file_path = _require_file(file_path)
    except ValueError as exc:
        return failure(str(exc))

    if not patch.strip():
        return failure("Empty patch")

    apply_command = [
        "git", "apply", "--unidiff-zero", "--whitespace=nowarn", "-",
    ]

    check = _run_process_with_input(
        ["git", "apply", "--check", "--unidiff-zero", "--whitespace=nowarn", "-"],
        cwd=file_path.parent,
        input_text=patch,
    )
    if not check["success"]:
        return _git_apply_failure(check, "Patch check failed")

    try:
        original = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return failure(f"File is not a UTF-8 text file: {file_path}")
    except OSError as exc:
        return failure(f"Failed to read file: {exc}")

    applied = _run_process_with_input(
        apply_command,
        cwd=file_path.parent,
        input_text=patch,
    )
    if not applied["success"]:
        return _git_apply_failure(applied, "Patch could not be applied")

    try:
        modified = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return failure(f"File is not a UTF-8 text file: {file_path}")
    except OSError as exc:
        return failure(f"Failed to read file: {exc}")

    changed = original != modified
    if not changed:
        return failure("Patch reported success but file unchanged")

    return success(
        {"file": str(file_path), "changed": changed, "patch_applied": True},
        message=f"Patch applied to {file_path}",
    )

def insert_text(
    path: str,
    line: int,
    text: str,
) -> dict[str, Any]:
    """Insert text before the specified 1-based line number.

    The text is inserted BEFORE the given 1-based line; line =
    total_lines + 1 appends the text at the end of the file. line must
    be in 1..total_lines+1 — out-of-range values fail rather than
    being clamped. If text does not end with a newline, one is added
    so the insertion does not merge with the following line.

    Args:
        path: Path to the file to edit.
        line: 1-based line before which the text is inserted
            (total_lines + 1 appends at the end).
        text: Text to insert (a trailing newline is added if missing).

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "line": int, "inserted": bool,
        "new_total_lines": int} where line is the insertion line.
    """
    file_path = _resolve_path(path)

    if not isinstance(line, int) or isinstance(line, bool):
        return failure(f"line must be an integer, got {line!r}")

    try:
        file_path = _require_file(file_path)
    except ValueError as exc:
        return failure(str(exc))

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return failure(f"File is not a UTF-8 text file: {file_path}")
    except OSError as exc:
        return failure(f"Failed to read file: {exc}")

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if line < 1 or line > total_lines + 1:
        return failure(
            f"line ({line}) must be between 1 and {total_lines + 1} "
            f"(total_lines + 1) for {file_path}"
        )

    if not text.endswith("\n"):
        text = text + "\n"

    lines.insert(line - 1, text)

    try:
        file_path.write_text("".join(lines), encoding="utf-8")
    except OSError as exc:
        return failure(f"Failed to write file: {exc}")

    return success(
        {
            "path": str(file_path),
            "line": line,
            "inserted": True,
            "new_total_lines": total_lines + 1,
        },
        message=f"Inserted {len(text)} characters before line {line}",
    )


def replace_text(
    path: str,
    old: str,
    new: str,
    count: int = -1,
) -> dict[str, Any]:
    """Replace occurrences of old with new in a file.

    Replacement is an exact literal string match — no fuzzy matching.
    count=-1 (the default) replaces ALL occurrences; count >= 1
    replaces exactly the first count occurrences and fails if the
    requested count exceeds the occurrences actually found (never a
    silent partial replacement). When count=-1 and more than one
    occurrence exists, data reports "occurrences" so the caller can
    see how many edits happened.

    Args:
        path: Path to the file to edit.
        old: Literal text to search for. Must be non-empty.
        new: Replacement text.
        count: -1 to replace all occurrences, or a positive integer
            for the number of leading occurrences to replace.

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "old": str, "new": str, "count": int,
        "occurrences": int} where count is the number of replacements
        actually made and occurrences the number found in the file.
    """
    file_path = _resolve_path(path)

    if not isinstance(count, int) or isinstance(count, bool):
        return failure(f"count must be an integer, got {count!r}")

    if not old:
        return failure("Empty old string")

    try:
        file_path = _require_file(file_path)
    except ValueError as exc:
        return failure(str(exc))

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return failure(f"File is not a UTF-8 text file: {file_path}")
    except OSError as exc:
        return failure(f"Failed to read file: {exc}")

    occurrences = content.count(old)

    if occurrences == 0:
        return failure(f"No matching text found: {old}")

    if count == -1:
        replaced = occurrences
    elif count >= 1:
        if count > occurrences:
            return failure(
                f"Requested count {count} exceeds occurrences {occurrences}"
            )
        replaced = count
    else:
        return failure(f"count must be -1 or >= 1, got {count}")

    content = content.replace(old, new, replaced)

    try:
        file_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return failure(f"Failed to write file: {exc}")

    return success(
        {
            "path": str(file_path),
            "old": old,
            "new": new,
            "count": replaced,
            "occurrences": occurrences,
        },
        message=f"Replaced {replaced} occurrence(s)",
    )


def delete_lines(
    path: str,
    start_line: int,
    end_line: int,
) -> dict[str, Any]:
    """Delete a range of 1-based inclusive lines.

    The range must satisfy 1 <= start_line <= end_line <= total_lines;
    out-of-range or reversed ranges fail rather than being clamped.

    Args:
        path: Path to the file to edit.
        start_line: First 1-based line to delete (inclusive).
        end_line: Last 1-based line to delete (inclusive).

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "start_line": int, "end_line": int,
        "deleted": int, "new_total_lines": int}.
    """
    file_path = _resolve_path(path)

    if not isinstance(start_line, int) or isinstance(start_line, bool):
        return failure(f"start_line must be an integer, got {start_line!r}")

    if not isinstance(end_line, int) or isinstance(end_line, bool):
        return failure(f"end_line must be an integer, got {end_line!r}")

    if start_line < 1:
        return failure(f"start_line must be >= 1, got {start_line}")

    if end_line < start_line:
        return failure(
            f"end_line ({end_line}) must be >= start_line ({start_line})"
        )

    try:
        file_path = _require_file(file_path)
    except ValueError as exc:
        return failure(str(exc))

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return failure(f"File is not a UTF-8 text file: {file_path}")
    except OSError as exc:
        return failure(f"Failed to read file: {exc}")

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if end_line > total_lines:
        return failure(
            f"end_line ({end_line}) is beyond the end of the file "
            f"({total_lines} lines): {file_path}"
        )

    deleted = end_line - start_line + 1
    del lines[start_line - 1:end_line]

    try:
        file_path.write_text("".join(lines), encoding="utf-8")
    except OSError as exc:
        return failure(f"Failed to write file: {exc}")

    return success(
        {
            "path": str(file_path),
            "start_line": start_line,
            "end_line": end_line,
            "deleted": deleted,
            "new_total_lines": total_lines - deleted,
        },
        message=f"Deleted {deleted} lines {start_line}-{end_line}",
    )


# ============================================================
# 4. EXECUTION
# ============================================================

EXEC_MAX_OUTPUT_CHARS = 20_000
EXEC_TRUNCATION_MARKER = "\n...[truncated]"


def _is_truncated(stream: str) -> bool:
    """Return True if stream carries the truncation marker."""
    return stream.endswith(EXEC_TRUNCATION_MARKER)


def _resolved_cwd(cwd: str | None) -> str:
    """Resolve cwd exactly as _run_subprocess does, for reporting.

    None resolves to the project root; other values are expanded and
    made absolute. The result is only informational; _run_subprocess
    performs the authoritative validation.
    """
    if cwd is None:
        return str(_resolve_path("."))
    return str(Path(cwd).expanduser().resolve())


def _execution_envelope(
    result: dict[str, Any],
    data: dict[str, Any],
    success_message: str,
    failed_message: str,
    timeout_message: str,
) -> dict[str, Any]:
    """Wrap a _run_subprocess result dict into the result envelope.

    A completed run with a non-zero exit code produces the message
    "{failed_message} (exit code N)". Command-level errors (invalid
    working directory, command not found) surface the error detail as
    both the error and the message. On timeout, success is False and
    timeout_message is used. data is always attached to the envelope.
    """
    if result["success"]:
        return success(data, message=success_message)

    if result["timed_out"]:
        return failure(timeout_message, data=data, message=timeout_message)

    if result["error"]:
        return failure(result["error"], data=data, message=result["error"])

    message = f"{failed_message} (exit code {result['returncode']})"
    return failure(message, data=data, message=message)


def run_command(
    cmd: str,
    cwd: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Executes an arbitrary shell command. Shell execution is inherently
    unsafe and should only be used when the command is trusted and
    necessary.

    Args:
        cmd: The shell command string to execute (shell=True).
        cwd: Working directory; None means the project root.
        timeout: Maximum seconds to wait before killing the process.

    Returns:
        A success/failure envelope. On success, data is {"command",
        "cwd" (resolved), "returncode", "stdout", "stderr",
        "timed_out", "truncated_stdout", "truncated_stderr"}; stdout
        and stderr are capped at EXEC_MAX_OUTPUT_CHARS characters and
        the truncated flags report whether the cap was hit. success is
        True only when the command ran and exited with code 0; timeout
        and failures still return the envelope with success False and
        everything captured in data.
    """
    if not cmd or not cmd.strip():
        return failure("Command must not be empty")

    result = _run_subprocess(
        cmd,
        cwd=cwd,
        timeout=timeout,
        max_output_chars=EXEC_MAX_OUTPUT_CHARS,
    )

    data = {
        "command": cmd,
        "cwd": _resolved_cwd(cwd),
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "timed_out": result["timed_out"],
        "truncated_stdout": _is_truncated(result["stdout"]),
        "truncated_stderr": _is_truncated(result["stderr"]),
    }

    return _execution_envelope(
        result,
        data,
        success_message="Command completed successfully",
        failed_message="Command failed",
        timeout_message=f"Command timed out after {timeout}s",
    )


def run_python(
    file: str,
    args: list[str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Execute a Python file using the current Python interpreter.

    Args:
        file: Path to the Python script to run.
        args: Optional command-line arguments passed to the script.
        timeout: Maximum seconds to wait before killing the process.

    Returns:
        A success/failure envelope. On success, data is {"file",
        "args", "returncode", "stdout", "stderr", "timed_out",
        "truncated_stdout", "truncated_stderr", "python"} (the
        interpreter path). success is True only when the script ran
        and exited with code 0; the file must exist.
    """
    file_path = _resolve_path(file)

    try:
        file_path = _require_file(file_path)
    except ValueError as exc:
        return failure(str(exc))

    command = [sys.executable, str(file_path)]

    if args:
        command.extend(args)

    result = _run_subprocess(
        command,
        cwd=file_path.parent,
        timeout=timeout,
        max_output_chars=EXEC_MAX_OUTPUT_CHARS,
    )

    data = {
        "file": str(file_path),
        "args": list(args) if args else [],
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "timed_out": result["timed_out"],
        "truncated_stdout": _is_truncated(result["stdout"]),
        "truncated_stderr": _is_truncated(result["stderr"]),
        "python": sys.executable,
    }

    return _execution_envelope(
        result,
        data,
        success_message="Python script completed successfully",
        failed_message="Python script failed",
        timeout_message=f"Python script timed out after {timeout}s",
    )


def run_tests(
    cmd: str = "pytest",
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run the project's test command.

    The command is a full shell string (shell=True), so custom
    invocations such as "pytest -q tests/" work.

    Args:
        cmd: The test command to execute.
        cwd: Working directory; None means the project root.
        timeout: Maximum seconds to wait before killing the process.

    Returns:
        A success/failure envelope. On success, data is {"command",
        "cwd", "returncode", "stdout", "stderr", "timed_out",
        "truncated_stdout", "truncated_stderr", "passed"}. The message
        is "Tests passed", "Tests failed (exit code N)" or "Tests
        timed out" accordingly.
    """
    result = _run_subprocess(
        cmd,
        cwd=cwd,
        timeout=timeout,
        max_output_chars=EXEC_MAX_OUTPUT_CHARS,
    )

    data = {
        "command": cmd,
        "cwd": _resolved_cwd(cwd),
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "timed_out": result["timed_out"],
        "truncated_stdout": _is_truncated(result["stdout"]),
        "truncated_stderr": _is_truncated(result["stderr"]),
        "passed": result["returncode"] == 0,
    }

    return _execution_envelope(
        result,
        data,
        success_message="Tests passed",
        failed_message="Tests failed",
        timeout_message="Tests timed out",
    )


def check_syntax(
    path: str,
) -> dict[str, Any]:
    """Check Python syntax without executing the file.

    The file is parsed with ast.parse directly; no subprocess is
    involved.

    Args:
        path: Path to the Python file to check.

    Returns:
        A success/failure envelope. On valid syntax, data is
        {"path", "valid": True, "line_count": int}. On a SyntaxError,
        success is False and data is {"path", "valid": False, "error":
        str(e.msg), "error_text": str(e)} plus "line" and "column"
        when available.
    """
    file_path = _resolve_path(path)

    try:
        file_path = _require_file(file_path)
    except ValueError as exc:
        return failure(str(exc))

    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return failure(f"Failed to read file: {exc}")

    try:
        ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        data: dict[str, Any] = {
            "path": str(file_path),
            "valid": False,
            "error": str(exc.msg),
            "error_text": str(exc),
        }
        if exc.lineno is not None:
            data["line"] = exc.lineno
        if exc.offset is not None:
            data["column"] = exc.offset
        message = f"Syntax error: {exc.msg}"
        if exc.lineno is not None:
            message += f" (line {exc.lineno}"
            if exc.offset is not None:
                message += f", column {exc.offset}"
            message += ")"
        return failure(str(exc.msg), data=data, message=message)
    except Exception as exc:
        return failure(f"Failed to check syntax: {exc}")

    return success(
        {
            "path": str(file_path),
            "valid": True,
            "line_count": len(source.splitlines()),
        },
        message="Syntax OK",
    )


def lint_project(
    cmd: str = "ruff check .",
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run the project's linting command.

    The command is a full shell string (shell=True), so custom
    invocations such as "ruff check . --fix" work.

    Args:
        cmd: The lint command to execute.
        cwd: Working directory; None means the project root.
        timeout: Maximum seconds to wait before killing the process.

    Returns:
        A success/failure envelope. On success, data is {"command",
        "cwd", "returncode", "stdout", "stderr", "timed_out",
        "truncated_stdout", "truncated_stderr"}. success is True only
        when lint exited with code 0. The message is "Lint passed",
        "Lint issues found (exit code N)" or "Lint timed out".
    """
    result = _run_subprocess(
        cmd,
        cwd=cwd,
        timeout=timeout,
        max_output_chars=EXEC_MAX_OUTPUT_CHARS,
    )

    data = {
        "command": cmd,
        "cwd": _resolved_cwd(cwd),
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "timed_out": result["timed_out"],
        "truncated_stdout": _is_truncated(result["stdout"]),
        "truncated_stderr": _is_truncated(result["stderr"]),
    }

    return _execution_envelope(
        result,
        data,
        success_message="Lint passed",
        failed_message="Lint issues found",
        timeout_message="Lint timed out",
    )


def typecheck_project(
    cmd: str = "mypy .",
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run the project's type-checking command.

    The command is a full shell string (shell=True), so custom
    invocations such as "mypy src/" work.

    Args:
        cmd: The type-check command to execute.
        cwd: Working directory; None means the project root.
        timeout: Maximum seconds to wait before killing the process.

    Returns:
        A success/failure envelope. On success, data is {"command",
        "cwd", "returncode", "stdout", "stderr", "timed_out",
        "truncated_stdout", "truncated_stderr"}. success is True only
        when type checking exited with code 0. The message is
        "Typecheck passed", "Typecheck issues found (exit code N)" or
        "Typecheck timed out".
    """
    result = _run_subprocess(
        cmd,
        cwd=cwd,
        timeout=timeout,
        max_output_chars=EXEC_MAX_OUTPUT_CHARS,
    )

    data = {
        "command": cmd,
        "cwd": _resolved_cwd(cwd),
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "timed_out": result["timed_out"],
        "truncated_stdout": _is_truncated(result["stdout"]),
        "truncated_stderr": _is_truncated(result["stderr"]),
    }

    return _execution_envelope(
        result,
        data,
        success_message="Typecheck passed",
        failed_message="Typecheck issues found",
        timeout_message="Typecheck timed out",
    )


# ============================================================
# 5. ENVIRONMENT
# ============================================================

def get_current_directory() -> dict[str, Any]:
    """Return the current working directory.

    Returns:
        A success envelope. data is {"cwd": str}.
    """
    cwd = str(Path.cwd())
    return success(
        {"cwd": cwd},
        message=f"Current working directory: {cwd}",
    )


def get_project_root(path: str = ".") -> dict[str, Any]:
    """Resolve the Git project root for a given path.

    Args:
        path: Path to start the search from. Defaults to the current
            directory.

    Returns:
        A success/failure envelope. On success, data is
        {"project_root": str}. Fails when the path is not inside a Git
        repository.
    """
    start = _resolve_path(path)
    root = _get_project_root(start)

    if root is None:
        return failure(
            "Could not determine project root (not a git repository?)"
        )

    return success(
        {"project_root": str(root)},
        message=f"Project root: {root}",
    )


def get_environment() -> dict[str, Any]:
    """Return safe runtime metadata about the environment.

    Returns safe runtime metadata only. Environment variable VALUES
    are never exposed (they may contain secrets). The only
    environment-derived values included are the directory list of
    PATH (conventionally public) and the sorted set of environment
    variable NAMES (names only, never values).

    Returns:
        A success envelope. data is {"platform": str, "python_version":
        str, "python_executable": str, "cwd": str, "project_root":
        str|None, "shell": str|None, "path_dirs": [str...],
        "env_var_names": [str...], "platform_bits": str}.
    """
    root = _get_project_root()

    if os.name == "nt":
        shell = f"Windows ({os.name})"
    else:
        shell = os.environ.get("SHELL")

    path_value = os.environ.get("PATH")
    path_dirs = [
        entry
        for entry in (path_value.split(os.pathsep) if path_value else [])
        if entry
    ]

    return success(
        {
            "platform": f"{platform.system()}/{platform.release()}",
            "python_version": sys.version.split()[0],
            "python_executable": sys.executable,
            "cwd": str(Path.cwd()),
            "project_root": str(root) if root is not None else None,
            "shell": shell,
            "path_dirs": path_dirs,
            "env_var_names": sorted(os.environ.keys()),
            "platform_bits": platform.architecture()[0],
        },
        message="Environment metadata (no environment variable values)",
    )


def get_python_version() -> dict[str, Any]:
    """Return the running Python version.

    Returns:
        A success envelope. data is {"version": str, "full": str}.
    """
    return success(
        {
            "version": sys.version.split()[0],
            "full": sys.version.split("\n")[0],
        }
    )


def which_command(command: str) -> dict[str, Any]:
    """Locate an executable on the system PATH.

    Args:
        command: Name of the command to locate.

    Returns:
        A success/failure envelope. On success, data is
        {"command": str, "path": str|None}; path is None when the
        command is not found (a valid answer, not an error). An empty
        command fails.
    """
    if not command or not command.strip():
        return failure("Command must not be empty")

    path = shutil.which(command)
    data = {"command": command, "path": path}

    if path is None:
        return success(data, message="Not found in PATH")

    return success(data, message=f"Found: {path}")


# ============================================================
# 6. PROJECT UNDERSTANDING
# ============================================================

PROJECT_MAX_TOP_LEVEL = 50
PROJECT_MAX_DEPENDENCIES = 50

PROJECT_TYPE_MARKERS: dict[str, tuple[str, ...]] = {
    "Python": ("pyproject.toml", "requirements.txt", "setup.py"),
    "Node.js": ("package.json",),
    "Rust": ("Cargo.toml",),
    "Go": ("go.mod",),
    "Java": ("pom.xml", "build.gradle"),
    "C/C++": ("CMakeLists.txt",),
    "Docker": ("Dockerfile",),
}

PROJECT_MARKERS: tuple[str, ...] = tuple(
    marker
    for markers in PROJECT_TYPE_MARKERS.values()
    for marker in markers
)


def inspect_project(path: str = ".") -> dict[str, Any]:
    """Gather a compact high-level summary of a project.

    File/directory counts come from _walk_files, so IGNORED_DIRS
    (virtualenvs, node_modules, ...) are excluded. top_level is sorted
    case-insensitively and capped at PROJECT_MAX_TOP_LEVEL entries;
    when the cap is hit truncated is True.

    Args:
        path: Directory to inspect. Defaults to the current directory.

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "name": str, "file_count": int, "dir_count": int,
        "total_size_bytes": int, "top_level": [{"name": str, "type":
        "file"|"dir"}...], "truncated": bool, "has_git": bool,
        "has_dockerfile": bool, "python_files": int,
        "has_requirements_txt": bool, "has_pyproject_toml": bool,
        "has_package_json": bool, "project_types": [str...]}.
    """
    root = _resolve_path(path)

    try:
        root = _require_dir(root)
    except ValueError as exc:
        return failure(str(exc))

    file_count = 0
    python_files = 0
    total_size_bytes = 0

    for file_path in _walk_files(root):
        file_count += 1
        if file_path.suffix == ".py":
            python_files += 1
        try:
            total_size_bytes += file_path.stat().st_size
        except OSError:
            continue

    dir_count = 0
    for current, dirs, _ in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        dir_count += 1

    try:
        top_level = [
            {
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            }
            for item in root.iterdir()
        ]
    except OSError as exc:
        return failure(f"Failed to inspect directory: {exc}")

    top_level.sort(key=lambda entry: entry["name"].lower())

    truncated = len(top_level) > PROJECT_MAX_TOP_LEVEL
    if truncated:
        top_level = top_level[:PROJECT_MAX_TOP_LEVEL]

    project_types = detect_project_type(str(root))["data"]["project_types"]

    return success(
        {
            "path": str(root),
            "name": root.name,
            "file_count": file_count,
            "dir_count": dir_count,
            "total_size_bytes": total_size_bytes,
            "top_level": top_level,
            "truncated": truncated,
            "has_git": (root / ".git").exists(),
            "has_dockerfile": (root / "Dockerfile").exists(),
            "python_files": python_files,
            "has_requirements_txt": (root / "requirements.txt").exists(),
            "has_pyproject_toml": (root / "pyproject.toml").exists(),
            "has_package_json": (root / "package.json").exists(),
            "project_types": project_types,
        },
        message=(
            f"Tree truncated at {PROJECT_MAX_TOP_LEVEL} top-level entries"
            if truncated
            else f"Found {file_count} files in {root}"
        ),
    )


def detect_project_type(path: str = ".") -> dict[str, Any]:
    """Detect likely project types from common project files.

    Args:
        path: Directory to inspect. Defaults to the current directory.

    Returns:
        A success/failure envelope. On success, data is
        {"project_types": [str...], "markers": [{"marker": str,
        "present": bool}...]}. project_types is empty when no
        recognizable markers are found (a valid result).
    """
    root = _resolve_path(path)

    try:
        root = _require_dir(root)
    except ValueError as exc:
        return failure(str(exc))

    markers = [
        {"marker": marker, "present": (root / marker).exists()}
        for marker in PROJECT_MARKERS
    ]

    present_names = {
        marker["marker"]
        for marker in markers
        if marker["present"]
    }

    project_types = [
        project_type
        for project_type, marker_names in PROJECT_TYPE_MARKERS.items()
        if any(marker in present_names for marker in marker_names)
    ]

    if not project_types:
        return success(
            {"project_types": [], "markers": markers},
            message="No recognizable project markers found",
        )

    return success(
        {"project_types": project_types, "markers": markers},
        message="Detected project types: " + ", ".join(project_types),
    )


def get_project_metadata(path: str = ".") -> dict[str, Any]:
    """Extract compact metadata from common project configuration files.

    Only selected fields are extracted; full configuration file
    contents are never included. A single corrupt or partial config
    file is skipped and noted in the message — it never fails the
    call. The call only fails when the path itself is invalid.

    Args:
        path: Directory to inspect. Defaults to the current directory.

    Returns:
        A success/failure envelope. On success, data is
        {"path": str, "name": str|None, "version": str|None,
        "description": str|None, "dependencies": [str...],
        "dev_dependencies": [str...], "scripts": dict|None,
        "requires_python": str|None, "go_version": str|None,
        "project_types": [str...], "sources": {str: bool},
        "truncated": bool}. sources reports which config files were
        found; dependencies and dev_dependencies are capped at
        PROJECT_MAX_DEPENDENCIES entries with truncated set when cut.
    """
    root = _resolve_path(path)

    try:
        root = _require_dir(root)
    except ValueError as exc:
        return failure(str(exc))

    metadata: dict[str, Any] = {
        "path": str(root),
        "name": None,
        "version": None,
        "description": None,
        "dependencies": [],
        "dev_dependencies": [],
        "scripts": None,
        "requires_python": None,
        "go_version": None,
        "project_types": detect_project_type(str(root))["data"]["project_types"],
        "sources": {
            "pyproject.toml": False,
            "package.json": False,
            "requirements.txt": False,
            "Cargo.toml": False,
            "go.mod": False,
        },
        "truncated": False,
    }

    notes: list[str] = []

    pyproject = root / "pyproject.toml"
    metadata["sources"]["pyproject.toml"] = pyproject.exists()
    if pyproject.exists():
        try:
            with pyproject.open("rb") as handle:
                config = tomllib.load(handle)
            project = config.get("project", {})
            metadata["name"] = metadata["name"] or project.get("name")
            metadata["version"] = metadata["version"] or project.get("version")
            metadata["description"] = (
                metadata["description"] or project.get("description")
            )
            metadata["requires_python"] = (
                metadata["requires_python"] or project.get("requires-python")
            )
            if metadata["scripts"] is None:
                scripts = project.get("scripts")
                if isinstance(scripts, dict):
                    metadata["scripts"] = dict(scripts)
                else:
                    poetry_scripts = (
                        config.get("tool", {})
                        .get("poetry", {})
                        .get("scripts")
                    )
                    if isinstance(poetry_scripts, dict):
                        metadata["scripts"] = dict(poetry_scripts)
            deps = project.get("dependencies")
            if isinstance(deps, list) and not metadata["dependencies"]:
                metadata["dependencies"] = list(deps)
            if not metadata["dev_dependencies"]:
                dev_deps: list[str] = []
                optional = project.get("optional-dependencies")
                if isinstance(optional, dict):
                    dev_deps.extend(optional.get("dev", []) or [])
                groups = config.get("dependency-groups")
                if isinstance(groups, dict):
                    dev_deps.extend(groups.get("dev", []) or [])
                metadata["dev_dependencies"] = dev_deps
        except (OSError, ValueError) as exc:
            notes.append(f"pyproject.toml: {exc}")

    package_json = root / "package.json"
    metadata["sources"]["package.json"] = package_json.exists()
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            metadata["name"] = metadata["name"] or package.get("name")
            metadata["version"] = metadata["version"] or package.get("version")
            metadata["description"] = (
                metadata["description"] or package.get("description")
            )
            if not metadata["dependencies"]:
                deps = package.get("dependencies")
                if isinstance(deps, dict):
                    metadata["dependencies"] = [
                        f"{name}@{version}"
                        for name, version in deps.items()
                    ]
            if not metadata["dev_dependencies"]:
                dev_deps = package.get("devDependencies")
                if isinstance(dev_deps, dict):
                    metadata["dev_dependencies"] = [
                        f"{name}@{version}"
                        for name, version in dev_deps.items()
                    ]
            if metadata["scripts"] is None:
                scripts = package.get("scripts")
                if isinstance(scripts, dict):
                    metadata["scripts"] = dict(scripts)
        except (OSError, ValueError) as exc:
            notes.append(f"package.json: {exc}")

    requirements_txt = root / "requirements.txt"
    metadata["sources"]["requirements.txt"] = requirements_txt.exists()
    if requirements_txt.exists():
        try:
            lines = [
                line.strip()
                for line in requirements_txt.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            lines = [
                line for line in lines
                if line and not line.startswith("#")
            ]
            if not metadata["dependencies"]:
                metadata["dependencies"] = lines
        except (OSError, ValueError) as exc:
            notes.append(f"requirements.txt: {exc}")

    cargo_toml = root / "Cargo.toml"
    metadata["sources"]["Cargo.toml"] = cargo_toml.exists()
    if cargo_toml.exists():
        try:
            with cargo_toml.open("rb") as handle:
                cargo_config = tomllib.load(handle)
            package = cargo_config.get("package", {})
            metadata["name"] = metadata["name"] or package.get("name")
            metadata["version"] = metadata["version"] or package.get("version")
        except (OSError, ValueError) as exc:
            notes.append(f"Cargo.toml: {exc}")

    go_mod = root / "go.mod"
    metadata["sources"]["go.mod"] = go_mod.exists()
    if go_mod.exists():
        try:
            for line in go_mod.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("module ") and metadata["name"] is None:
                    metadata["name"] = stripped[len("module "):].strip()
                elif stripped.startswith("go ") and metadata["go_version"] is None:
                    metadata["go_version"] = stripped[len("go "):].strip()
        except (OSError, ValueError) as exc:
            notes.append(f"go.mod: {exc}")

    for key in ("dependencies", "dev_dependencies"):
        if len(metadata[key]) > PROJECT_MAX_DEPENDENCIES:
            metadata[key] = metadata[key][:PROJECT_MAX_DEPENDENCIES]
            metadata["truncated"] = True

    message = (
        f"Extracted metadata from "
        f"{sum(metadata['sources'].values())} source file(s)"
    )
    if notes:
        message += " (skipped: " + "; ".join(notes) + ")"

    return success(metadata, message=message)
# ============================================================
# 7. GIT
# ============================================================

GIT_TIMEOUT = 30
GIT_BINARY = "git"


def _git_envelope(
    result: dict[str, Any],
    command: list[str] | str,
    cwd: str,
    **extra: Any,
) -> dict[str, Any]:
    """Wrap a _run_subprocess detail dict into a git tool result envelope.

    data always contains the common subprocess block — command, cwd
    (resolved), returncode, stdout, stderr, timed_out,
    truncated_stdout, truncated_stderr — plus any tool-specific extra
    fields, so every git tool exposes the same core data. success is
    True iff git ran and exited 0; informational stderr from an
    otherwise successful run (e.g. git switch progress messages) is
    never treated as failure. On failure error is the trimmed stderr
    or "git exited with code <returncode>" and message is None.
    """
    data: dict[str, Any] = {
        "command": command,
        "cwd": cwd,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "timed_out": result["timed_out"],
        "truncated_stdout": result["stdout"].endswith("\n...[truncated]"),
        "truncated_stderr": result["stderr"].endswith("\n...[truncated]"),
        **extra,
    }
    if result["success"]:
        return success(data)
    return failure(
        result["stderr"].strip()
        or f"git exited with code {result['returncode']}",
        data=data,
        message=None,
    )


def git_status(
    cwd: str = ".",
) -> dict[str, Any]:
    """Return Git status for the working tree.

    Runs ["git", "status", "--short", "--branch"]. With cwd="." (the
    default) the command runs at the repository root. Read-only: never
    modifies the repository. data adds {"branch": str|None, "clean":
    bool}; branch is parsed from the "## <branch>" summary line
    ("HEAD (no branch)" when detached) and clean is True when no
    change lines are present.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    command = [GIT_BINARY, "status", "--short", "--branch"]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    branch: str | None = None
    clean = True
    for line in result["stdout"].splitlines():
        if line.startswith("## "):
            branch = line[3:].strip()
        else:
            clean = False

    return _git_envelope(
        result,
        command,
        cwd_resolved,
        branch=branch,
        clean=clean,
    )


def git_diff(
    path: str | None = None,
    cwd: str = ".",
) -> dict[str, Any]:
    """Show the current unstaged diff.

    Runs ["git", "diff"] with ["--", path] appended when a path is
    given. With cwd="." (the default) the command runs at the
    repository root. Read-only: never modifies the repository. data
    adds {"path": str|None} — the path argument as passed.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    command = [GIT_BINARY, "diff"]
    if path:
        command += ["--", path]

    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    return _git_envelope(result, command, cwd_resolved, path=path)


def git_log(
    n: int = 10,
    cwd: str = ".",
) -> dict[str, Any]:
    """Show recent commit history.

    Runs ["git", "log", "-n", <n>, "--oneline", "--decorate"]. With
    cwd="." (the default) the command runs at the repository root.
    Read-only: never modifies the repository. data adds {"entries":
    [commit line, ...], "count": int}; entries are the non-empty
    stdout lines and count is their number.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    command = [
        GIT_BINARY,
        "log",
        "-n",
        str(n),
        "--oneline",
        "--decorate",
    ]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    entries = [
        line
        for line in result["stdout"].splitlines()
        if line.strip()
    ]

    return _git_envelope(
        result,
        command,
        cwd_resolved,
        entries=entries,
        count=len(entries),
    )


def git_show(
    commit: str = "HEAD",
    cwd: str = ".",
) -> dict[str, Any]:
    """Show a specific commit.

    Runs ["git", "show", <commit>]. With cwd="." (the default) the
    command runs at the repository root. Read-only: never modifies the
    repository. Unknown commit references fail with git's error. data
    adds {"commit": str} — the commit reference as passed.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    command = [GIT_BINARY, "show", commit]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    return _git_envelope(result, command, cwd_resolved, commit=commit)


def git_branch(
    cwd: str = ".",
) -> dict[str, Any]:
    """List local branches.

    Runs ["git", "branch", "--list"]. With cwd="." (the default) the
    command runs at the repository root. Read-only: never modifies the
    repository. data adds {"branches": [name, ...], "current":
    str|None}; branches are the non-empty stdout lines stripped (the
    current branch's entry keeps git's "* " marker) and current is the
    branch marked with "*", or None when detached.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    command = [GIT_BINARY, "branch", "--list"]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    branches = [
        line.strip()
        for line in result["stdout"].splitlines()
        if line.strip()
    ]
    current: str | None = None
    for line in branches:
        if line.startswith("*"):
            current = line.lstrip("*").strip()
            break

    return _git_envelope(
        result,
        command,
        cwd_resolved,
        branches=branches,
        current=current,
    )


def git_branch_create(
    name: str,
    cwd: str = ".",
) -> dict[str, Any]:
    """Create a new branch at the current HEAD. Does not switch to it.

    Runs ["git", "branch", <name>] — plain branch creation, no force,
    so an existing branch name fails with git's error. With cwd="."
    (the default) the command runs at the repository root. A blank
    name fails with "Branch name must not be empty" before any
    subprocess runs. data adds {"branch": str} — the name as passed.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    if not name.strip():
        return failure("Branch name must not be empty")

    command = [GIT_BINARY, "branch", name]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    return _git_envelope(result, command, cwd_resolved, branch=name)


def git_branch_switch(
    name: str,
    cwd: str = ".",
) -> dict[str, Any]:
    """Switch to an existing branch.

    Runs plain ["git", "switch", <name>] — never with -f, so
    uncommitted changes that would be overwritten make git refuse.
    With cwd="." (the default) the command runs at the repository
    root. A blank name fails with "Branch name must not be empty".
    git switch reports progress on stderr even when it succeeds; a
    successful run (exit 0) is still a success. data adds {"branch":
    str} — the name as passed.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    if not name.strip():
        return failure("Branch name must not be empty")

    command = [GIT_BINARY, "switch", name]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    return _git_envelope(result, command, cwd_resolved, branch=name)


def git_add(
    paths: list[str],
    cwd: str = ".",
) -> dict[str, Any]:
    """Stage the given paths for commit.

    Runs ["git", "add", <paths...>]. With cwd="." (the default) the
    command runs at the repository root. Only the given paths are
    staged; nothing else. An empty paths list fails with "No paths
    given" before any subprocess runs. data adds {"paths":
    list[str]} — the paths as passed.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    if not paths:
        return failure("No paths given")

    command = [GIT_BINARY, "add", *paths]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    return _git_envelope(result, command, cwd_resolved, paths=paths)


def git_commit(
    message: str,
    cwd: str = ".",
) -> dict[str, Any]:
    """Create a commit with the given message.

    Runs git commit -m with the given message. Does NOT stage changes
    (run git_add first). Does not amend or force. With cwd="." (the
    default) the command runs at the repository root. A blank message
    fails with "Commit message must not be empty" before any
    subprocess runs. data adds {"message": str} — the message as
    passed.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    if not message.strip():
        return failure("Commit message must not be empty")

    command = [GIT_BINARY, "commit", "-m", message]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    return _git_envelope(result, command, cwd_resolved, message=message)


def git_stash(
    cwd: str = ".",
) -> dict[str, Any]:
    """Stash uncommitted changes.

    Runs ["git", "stash"] (tracked changes; untracked files are not
    stashed by default). With cwd="." (the default) the command runs
    at the repository root. Does not pop, apply, or drop anything on
    its own. data adds {"stashed": bool} — True iff git ran and
    exited 0.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    command = [GIT_BINARY, "stash"]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    return _git_envelope(
        result,
        command,
        cwd_resolved,
        stashed=result["success"],
    )


def git_stash_pop(
    cwd: str = ".",
) -> dict[str, Any]:
    """Restore the most recent stash.

    Runs ["git", "stash", "pop"] — applies the most recent stash entry
    and drops it. With cwd="." (the default) the command runs at the
    repository root. With no stash to pop git exits non-zero and the
    call fails with git's error. data adds {"popped": bool} — True iff
    git ran and exited 0.

    Returns:
        A success/failure envelope; success is True iff git ran and
        exited 0.
    """
    command = [GIT_BINARY, "stash", "pop"]
    cwd_resolved = str(_resolve_path(cwd))
    result = _run_subprocess(
        command,
        cwd=cwd_resolved,
        timeout=GIT_TIMEOUT,
    )

    return _git_envelope(
        result,
        command,
        cwd_resolved,
        popped=result["success"],
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
