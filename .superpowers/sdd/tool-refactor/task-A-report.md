# Task A Report — Foundation: result envelope, path handling, ignored dirs, subprocess helper

Status: DONE
Commit: (see commit message at end of session)

## What changed

Only `agent/tools/functions.py` was modified. All 50 tool functions are untouched (verified: `git diff` shows changes confined to the Common Helpers block at the top of the file and the `typing` import).

- Line 14: `from typing import Any, Iterator` (added `Iterator`).
- Lines 18–20: Common Helpers banner (unchanged).
- Lines 22–29: `success(data, message)` — result envelope `{"success": True, "data", "message", "error": None}`.
- Lines 31–43: `failure(error, data, message)` — `str(error)` coercion; envelope always has the exact four keys.
- Lines 45–49: `IGNORED_DIRS` frozenset as specified in the brief (10 entries).
- Lines 51–65: `_walk_files(root)` — `os.walk` with in-place pruning of `IGNORED_DIRS` at every depth before descending; root itself never filtered. Docstring documents the semantics.
- Lines 67–83: `_resolve_path(path=".")` — `"."`/`""`/omitted (and defensively `None`) resolve to the project root via `_get_project_root()` (git top-level) with CWD fallback; other relative paths resolve against CWD; absolute paths used as-is; no confinement. Docstring documents the deliberate "."→project-root behavior that fixes `list_files` misses.
- Lines 85–90: `_require_file(path)` — raises `ValueError("File not found: <path>")`.
- Lines 92–97: `_require_dir(path)` — raises `ValueError("Directory not found: <path>")`.
- Lines 99–115: `_get_project_root(start=".")` — runs `git rev-parse --show-toplevel` via `_run_subprocess` (explicit cwd, timeout 10s); returns `Path | None`, never raises. No recursion: it always passes an explicit cwd, so it never re-enters `_resolve_path(".")`.
- Lines 117–215: `_run_subprocess(command, cwd=None, timeout=30, max_output_chars=20_000)` — returns the subprocess detail dict `{success, returncode, stdout, stderr, timed_out, error}` (not the envelope); never raises. Details:
  - cwd given: resolved + validated; non-directory → failure dict `Invalid working directory: <cwd>`.
  - cwd None: project root (same resolution as `_resolve_path(".")`).
  - str command → `shell=True` (docstring documents the arbitrary-execution risk); list → no shell.
  - stdout/stderr always str, truncated to `max_output_chars` with `\n...[truncated]` marker appended on truncation.
  - TimeoutExpired → `timed_out: True`, partial output preserved, `error: "Command timed out after Ns"`.
  - FileNotFoundError → `error: "Command not found: <cmd>"`.
  - Other exceptions → failure dict with `str(exc)`.

## Final signatures

```python
def success(data: Any = None, message: str | None = None) -> dict[str, Any]
def failure(error: str | Exception, data: Any = None, message: str | None = None) -> dict[str, Any]
IGNORED_DIRS: frozenset[str] = frozenset({".git", ".venv", "venv", "draft_venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", "dist", "build"})
def _walk_files(root: Path) -> Iterator[Path]
def _resolve_path(path: str | Path = ".") -> Path
def _require_file(path: Path) -> Path
def _require_dir(path: Path) -> Path
def _get_project_root(start: str = ".") -> Path | None
def _run_subprocess(command: list[str] | str, cwd: str | Path | None = None, timeout: int | None = 30, max_output_chars: int = 20_000) -> dict[str, Any]
```

## Verification commands run (all passed)

1. `python -m py_compile agent/tools/functions.py` (venv interpreter, repo root) → `COMPILE_OK`.
2. Import smoke test from `agent/` CWD (venv interpreter) per brief → envelope asserts pass, `_resolve_path('.')` prints `E:\Microsoft Certifications\Capstore Projects\Draft` (repo root, NOT `agent/`), `_run_subprocess(['python','--version'])` returns `{'success': True, 'returncode': 0, 'stdout': 'Python 3.11.9\n', 'stderr': '', 'timed_out': False, 'error': None}`.
3. `_walk_files` over repo root → 28 files, zero from `draft_venv`/`.git` (`.gitignore` correctly included — it is a file, not the `.git` dir).
4. Truncation: `_run_subprocess(['python','-c',"print('x'*50000)"], max_output_chars=1000)` → `returncode 0`, `success True`, stdout = exactly 1000 chars + `\n...[truncated]` marker.
5. `FileNotFoundError` → `error: "Command not found: nosuchcmd_xyz"`.
6. Invalid cwd → `error: "Invalid working directory: ..."`, `returncode None`.
7. Timeout (sleep 60, timeout=1) → `timed_out: True`, `returncode None`, `error: "Command timed out after 1s"`.
8. `_require_file`/`_require_dir` raise ValueError on wrong types; envelope dicts pass `json.dumps`.
9. `import tools.tools; import tools.registry` from `agent/` → OK (all 50 tools + registry load with new helpers).

## Deviations

None from the brief. Two defensive choices beyond the letter of the spec (both backward-compatible):
- `_resolve_path` treats `None` like `"."` (no current caller passes None; guards against future misuse).
- TimeoutExpired preserves partial stdout/stderr instead of empty strings (spec allows "captured so far").

## Concerns

- Existing tools that call `_run_subprocess` without cwd (e.g. `run_command`, `run_tests`, `get_project_root`) now run with CWD = project root instead of the process CWD (`agent/`). This is the intended fix per the brief, but later tasks wrapping these tools in the envelope should confirm behavior with explicit `cwd` where a different directory was previously assumed.
- `_resolve_path(".")` now spawns `git rev-parse` per call (short timeout 10s); acceptable for a CLI agent, noted for performance-sensitive loops.
- `_walk_files` (and `os.walk`) may raise on unreadable directories; not handled here — callers/task D's search tools should decide whether to skip or propagate.