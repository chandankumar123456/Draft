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
    except OSError as exc:
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