# Config Persistence + Subagents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the Azure endpoint + model config in `.draft/config.json` (fixing first-run config loss) and add three role-based subagents (investigator / implementer / verifier) that the main agent can spawn in parallel.

**Architecture:** A new `agent/config.py` module owns config load/save with precedence file → env → defaults; the first-run save bug in the TUI/CLI entry points is fixed by always persisting. Subagents are hosted agents registered in `initialize()` (`Draft-Investigator`, `Draft-Implementer`, `Draft-Verifier`), invoked through a `spawn_subagent(role, task, timeout)` tool. The runtime groups `spawn_subagent` calls per response batch and runs them concurrently via a thread pool; each sub-agent loop dispatches tool calls through the shared `ToolDispatcher`, and four new events surface subagent activity in the TUI/CLI.

**Tech Stack:** Python 3.11+, `azure-ai-projects` (`PromptAgentDefinition`), OpenAI Responses API (`agent_reference`), Textual TUI, pytest. No new dependencies (stdlib `concurrent.futures` only).

## Global Constraints

- Python 3.11+; no new third-party dependencies beyond `requirements.txt`.
- Tool results use the 4-key envelope contract: `{"success": bool, "data": ..., "message": str|None, "error": str|None}` via `success()` / `failure()` in `agent/tools/functions.py`.
- Strict `FunctionTool` schemas via `make_tool` in `agent/tools/tools.py` (all properties required; optional props become nullable — do not pass `additionalProperties`).
- Events are frozen dataclasses inheriting `RuntimeEvent` in `agent/events.py`; emit thread-safely with `emit_threadsafe`.
- Config file `.draft/config.json` must never hold secrets (endpoint/model are not credentials).
- `.draft/` must be gitignored.
- Agent suite runs from `agent/`: `python -m pytest tests -q`. TUI suite runs from repo root: `python -m pytest tests -q`. Both must stay green.
- Follow existing style: module docstrings, no stray comments.

---

### Task 1: Config module (`agent/config.py`) + `.gitignore`

**Files:**
- Create: `agent/config.py`
- Test: `agent/tests/test_config.py`
- Modify: `.gitignore` (add `.draft/`)

**Interfaces:**
- Produces: `Config(endpoint: str = "", model: str = "gpt-4.1-mini")`; `config_path() -> Path`; `ensure_loaded() -> None` (idempotent); `load_config() -> Config`; `save_config(endpoint: str | None = None, model: str | None = None) -> None`; `clear_config() -> None`. Later tasks rely on these exact names.
- Note: tests must be able to redirect the config location — they monkeypatch `config._project_root` and `config.load_dotenv`.

- [ ] **Step 1: Write the failing tests**

```python
# agent/tests/test_config.py
"""Tests for persistent configuration (endpoint + model)."""

import pytest

from config import (
    Config,
    clear_config,
    config_path,
    load_config,
    save_config,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Redirect the config file to tmp_path and reset module state."""
    monkeypatch.setattr("config._project_root", lambda: tmp_path)
    monkeypatch.setattr("config._LOADED", False)
    monkeypatch.setattr("config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("MODEL_DEPLOYMENT", raising=False)
    yield


def test_load_config_defaults():
    cfg = load_config()
    assert isinstance(cfg, Config)
    assert cfg.endpoint == ""
    assert cfg.model == "gpt-4.1-mini"


def test_save_and_load_round_trip():
    save_config(endpoint="https://draft.services.ai.azure.com/api/projects/Draft", model="gpt-4.1-mini")
    assert config_path().exists()
    assert config_path().name == "config.json"
    cfg = load_config()
    assert cfg.endpoint == "https://draft.services.ai.azure.com/api/projects/Draft"
    assert cfg.model == "gpt-4.1-mini"


def test_file_overrides_env(monkeypatch):
    save_config(endpoint="https://from-file.azure.com")
    monkeypatch.setenv("PROJECT_ENDPOINT", "https://from-env.azure.com")
    cfg = load_config()
    assert cfg.endpoint == "https://from-file.azure.com"


def test_env_used_when_file_missing(monkeypatch):
    monkeypatch.setenv("PROJECT_ENDPOINT", "https://from-env.azure.com")
    monkeypatch.setenv("MODEL_DEPLOYMENT", "gpt-4o")
    cfg = load_config()
    assert cfg.endpoint == "https://from-env.azure.com"
    assert cfg.model == "gpt-4o"


def test_clear_config_removes_file():
    save_config(endpoint="https://x.azure.com")
    clear_config()
    assert not config_path().exists()
    assert load_config().endpoint == ""


def test_save_config_sets_environment():
    save_config(endpoint="https://y.azure.com", model="gpt-4.1")
    import os
    assert os.environ["PROJECT_ENDPOINT"] == "https://y.azure.com"
    assert os.environ["MODEL_DEPLOYMENT"] == "gpt-4.1"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Implement `agent/config.py`**

```python
"""Persistent configuration for Draft (endpoint + model).

Configuration is stored in ``.draft/config.json`` at the project root
and loaded with precedence: config file -> environment (``.env``) ->
defaults. The module is import-safe anywhere; ``ensure_loaded`` is
idempotent and merges the config file into the environment so
existing ``os.getenv("PROJECT_ENDPOINT")`` consumers keep working.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_LOADED = False


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    """Return the path to the persistent config file."""
    return _project_root() / ".draft" / "config.json"


@dataclass
class Config:
    """Resolved configuration values."""
    endpoint: str = ""
    model: str = "gpt-4.1-mini"


def ensure_loaded() -> None:
    """Load .env then apply .draft/config.json over the environment.

    Idempotent: only the first call performs the merge.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    load_dotenv()
    path = config_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if data.get("endpoint"):
        os.environ["PROJECT_ENDPOINT"] = str(data["endpoint"])
    if data.get("model"):
        os.environ["MODEL_DEPLOYMENT"] = str(data["model"])


def load_config() -> Config:
    """Return the active configuration (file -> env -> defaults)."""
    ensure_loaded()
    data: dict[str, str] = {}
    path = config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    return Config(
        endpoint=(data.get("endpoint") or os.getenv("PROJECT_ENDPOINT", "")).strip(),
        model=(data.get("model") or os.getenv("MODEL_DEPLOYMENT", "gpt-4.1-mini").strip()
               or "gpt-4.1-mini"),
    )


def save_config(endpoint: str | None = None, model: str | None = None) -> None:
    """Persist endpoint/model to .draft/config.json and the environment.

    Either value may be omitted; omitted values are left untouched.
    """
    ensure_loaded()
    if endpoint is not None:
        os.environ["PROJECT_ENDPOINT"] = endpoint
    if model is not None:
        os.environ["MODEL_DEPLOYMENT"] = model

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    if endpoint is not None:
        data["endpoint"] = endpoint
    if model is not None:
        data["model"] = model
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def clear_config() -> None:
    """Delete the config file and unset the config env vars."""
    path = config_path()
    if path.exists():
        path.unlink()
    os.environ.pop("PROJECT_ENDPOINT", None)
    os.environ.pop("MODEL_DEPLOYMENT", None)
```

- [ ] **Step 4: Add `.draft/` to `.gitignore`**

Append after the `.env` line in `.gitignore`:

```
.draft/
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_config.py -q`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add agent/config.py agent/tests/test_config.py .gitignore
git commit -m "feat: persist endpoint/model config in .draft/config.json"
```

---

### Task 2: Credential cleanup + CLI first-run prompt

**Files:**
- Modify: `agent/credential.py` (remove `save_config`, use `config.ensure_loaded`)
- Modify: `agent/runtime.py` (import `save_config` from `config` instead of `credential`)
- Modify: `agent/agent.py` (first-run prompt; subagent event handlers are added in Task 8 — do NOT add them here)
- Test: `agent/tests/test_config.py` (append CLI prompt tests)

**Interfaces:**
- Consumes: `config.load_config()`, `config.save_config()` from Task 1.
- Produces: `agent/agent.py` calls `_first_run_prompt() -> tuple[str, str] | None` then `save_config(endpoint=..., model=...)` before runtime initialization. `credential.py` no longer defines `save_config`.

- [ ] **Step 1: Write the failing tests (append to `agent/tests/test_config.py`)**

```python
def test_first_run_prompt_skipped_when_configured(monkeypatch):
    save_config(endpoint="https://configured.azure.com")
    monkeypatch.setattr("builtins.input", lambda prompt="": "should-not-be-called")
    from agent import _first_run_prompt  # noqa: PLC0415
    assert _first_run_prompt() is None


def test_first_run_prompt_asks_and_returns_values(monkeypatch):
    clear_config()
    answers = iter(["https://typed.azure.com", "gpt-4.1-mini"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    from agent import _first_run_prompt  # noqa: PLC0415
    endpoint, model = _first_run_prompt()
    assert endpoint == "https://typed.azure.com"
    assert model == "gpt-4.1-mini"


def test_first_run_prompt_retries_blank_endpoint(monkeypatch):
    clear_config()
    answers = iter(["", "  ", "https://typed.azure.com", "gpt-4.1-mini"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    from agent import _first_run_prompt  # noqa: PLC0415
    endpoint, model = _first_run_prompt()
    assert endpoint == "https://typed.azure.com"
    assert model == "gpt-4.1-mini"


def test_first_run_prompt_exit_command(monkeypatch):
    clear_config()
    monkeypatch.setattr("builtins.input", lambda prompt="": "exit")
    from agent import _first_run_prompt  # noqa: PLC0415
    with pytest.raises(SystemExit):
        _first_run_prompt()


def test_first_run_prompt_persists_config(monkeypatch, tmp_path):
    clear_config()
    answers = iter(["https://typed.azure.com", "gpt-4.1-mini"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    from agent import _first_run_prompt  # noqa: PLC0415
    endpoint, model = _first_run_prompt()
    save_config(endpoint=endpoint, model=model)
    data = json.loads(config_path().read_text(encoding="utf-8"))
    assert data["endpoint"] == "https://typed.azure.com"
    assert data["model"] == "gpt-4.1-mini"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_config.py -q`
Expected: FAIL — `ImportError: cannot import name '_first_run_prompt' from 'agent'`

- [ ] **Step 3: Update `agent/credential.py`**

Replace the import and `save_config` body. Delete lines 3 (`from dotenv import load_dotenv, set_key`), 8 (`load_dotenv()`), and the whole `save_config` function (lines 36-47). Add:

```python
from config import ensure_loaded

ensure_loaded()
```

The file keeps `get_project_client`, `get_openai_client`, and the module-level client refs unchanged.

- [ ] **Step 3b: Update the `save_config` import in `agent/runtime.py`**

`runtime.py` line 31 imports `save_config` from `credential`, which no longer defines it. Replace:

```python
from credential import get_openai_client, get_project_client, save_config
```

with:

```python
from config import save_config
from credential import get_openai_client, get_project_client
```

- [ ] **Step 4: Update `agent/agent.py`**

Add imports and the prompt helper (place it next to `main`):

```python
from config import load_config, save_config


def _first_run_prompt() -> tuple[str, str] | None:
    """Prompt for endpoint/model on first run; None when configured.

    Re-prompts until a non-blank endpoint is given. Typing "exit" or
    "quit" exits the program cleanly instead of configuring anything.
    """
    cfg = load_config()
    if cfg.endpoint:
        return None
    print("First run: configure your Azure AI Foundry connection.")
    endpoint = ""
    while not endpoint:
        endpoint = input("Project endpoint URL: ").strip()
        if endpoint.lower() in {"exit", "quit"}:
            sys.exit(0)
        if not endpoint:
            print("Endpoint cannot be empty.")
    model = input(f"Model deployment name [{cfg.model}]: ").strip() or cfg.model
    return endpoint, model
```

In `main()`, at the very top — BEFORE `event_bus = EventBus()` and the `AgentRuntime(...)` construction, so the first session picks up the saved endpoint AND model from the environment (the runtime reads them at construction):

```python
    first_run = _first_run_prompt()
    if first_run is not None:
        endpoint, model = first_run
        save_config(endpoint=endpoint, model=model)
        print("Configuration saved to .draft/config.json.")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_config.py -q`
Expected: 11 passed

- [ ] **Step 6: Run the existing agent suite for regressions**

Run: `cd agent && python -m pytest tests -q`
Expected: all pass (128 existing + 5 new = 133)

- [ ] **Step 7: Commit**

```bash
git add agent/credential.py agent/agent.py agent/tests/test_config.py
git commit -m "feat: CLI first-run config prompt; credential uses config module"
```

---

### Task 3: TUI config persistence fix + `/config-reset`

**Files:**
- Modify: `tui/app.py` (`on_mount`, `_update_endpoint`, `_update_model`, `_on_config_modal_closed`, slash-command dispatch)
- Modify: `tui/widgets/workspace.py` (slash help list, config summary hint)
- Test: `tests/test_tui_config.py` (new — verify `_update_endpoint` persists via `save_config`)

**Interfaces:**
- Consumes: `config.load_config()`, `config.save_config()`, `config.clear_config()`.
- Produces: TUI persists config on every entry path; new slash command `/config-reset` clears config and reopens the mandatory modal.

- [ ] **Step 1: Write the failing test (`tests/test_tui_config.py`)**

```python
"""Tests for TUI config persistence (.draft/config.json)."""

import pytest
from pathlib import Path

from tui.app import DraftApp

_TUI_STYLES = (
    Path(__file__).resolve().parent.parent / "tui" / "styles.tcss"
)


class _TestDraftApp(DraftApp):
    """DraftApp without agent runtime initialization."""

    CSS_PATH = _TUI_STYLES

    def _init_agent(self) -> None:
        pass


@pytest.mark.anyio
async def test_update_endpoint_persists_to_config(tmp_path, monkeypatch) -> None:
    """/endpoint must persist even when the runtime is not yet created."""
    import config as config_module
    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_LOADED", False)

    app = _TestDraftApp()
    async with app.run_test(size=(80, 24)):
        app._update_endpoint("https://persisted.azure.com")

    from config import load_config
    assert load_config().endpoint == "https://persisted.azure.com"


@pytest.mark.anyio
async def test_config_reset_clears_saved_config(tmp_path, monkeypatch) -> None:
    """/config-reset deletes the saved config file."""
    import config as config_module
    from config import clear_config, config_path, save_config

    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_LOADED", False)
    save_config(endpoint="https://persisted.azure.com")
    assert config_path().exists()

    clear_config()
    assert not config_path().exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_tui_config.py -q` (repo root)
Expected: FAIL — `AssertionError: assert '' == 'https://persisted.azure.com'`

- [ ] **Step 3: Update `tui/app.py`**

At the imports section add:

```python
from config import clear_config, load_config, save_config
```

In `on_mount`, replace the config check block:

```python
        # Check required configuration
        endpoint = os.getenv("PROJECT_ENDPOINT", "").strip()
        model = os.getenv("MODEL_DEPLOYMENT", "").strip()
        if not endpoint or not model:
            self.action_show_config(mandatory=True)
        else:
            self._init_agent()
```

with:

```python
        # Check required configuration
        cfg = load_config()
        if not cfg.endpoint:
            self.action_show_config(mandatory=True)
        else:
            self._init_agent()
```

In `_update_endpoint`, after `os.environ["PROJECT_ENDPOINT"] = clean_endpoint` add:

```python
        save_config(endpoint=clean_endpoint)
```

In `_update_model`, after `os.environ["MODEL_DEPLOYMENT"] = clean_model` add:

```python
        save_config(model=clean_model)
```

In `_on_config_modal_closed`, after `os.environ["MODEL_DEPLOYMENT"] = model` add:

```python
            save_config(endpoint=endpoint, model=model)
```

In the slash-command dispatch, before the `elif cmd in ("/exit", "/quit"):` branch add:

```python
        elif cmd == "/config-reset":
            workspace.write_system_message(
                "Configuration cleared. Re-enter your endpoint and model.",
                level="warning",
            )
            if self._runtime is not None:
                self._runtime.cleanup()
                self._runtime = None
            clear_config()
            self.action_show_config(mandatory=True)
```

- [ ] **Step 4: Update `tui/widgets/workspace.py`**

In the slash help list (around `("/exit", "Exit Draft Developer Cockpit")`) add:

```python
            ("/config-reset", "Clear saved config and re-enter endpoint/model"),
```

In `write_config_summary`, extend the hint line to:

```python
            "\n[dim]To update configuration: use /endpoint <url> or /model <name> or /config[/dim]\n"
            "[dim]To start over: /config-reset[/dim]"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests -q` (repo root)
Expected: all pass (6 existing + 2 new)

- [ ] **Step 6: Commit**

```bash
git add tui/app.py tui/widgets/workspace.py tests/test_tui_config.py
git commit -m "fix: persist TUI config on all entry paths; add /config-reset"
```

---

### Task 4: Subagent events

**Files:**
- Modify: `agent/events.py`
- Test: `agent/tests/test_subagents.py` (create file with event tests)

**Interfaces:**
- Produces: `SubagentStarted(role, task, agent_name)`, `SubagentMessage(role, content)`, `SubagentCompleted(role, task, iterations, tool_calls, duration_seconds, result)`, `SubagentFailed(role, task, error)` — all frozen dataclasses inheriting `RuntimeEvent` with default values.

- [ ] **Step 1: Write the failing test**

```python
# agent/tests/test_subagents.py
"""Tests for subagent events, roles, runner, and runtime integration."""

from events import (
    RuntimeEvent,
    SubagentCompleted,
    SubagentFailed,
    SubagentMessage,
    SubagentStarted,
)


def test_subagent_events_are_runtime_events():
    started = SubagentStarted(role="investigator", task="inspect repo", agent_name="Draft-Investigator")
    message = SubagentMessage(role="verifier", content="2 passed")
    completed = SubagentCompleted(role="implementer", task="add flag", iterations=3, tool_calls=5, duration_seconds=1.5, result="done")
    failed = SubagentFailed(role="verifier", task="run tests", error="boom")
    for event in (started, message, completed, failed):
        assert isinstance(event, RuntimeEvent)
        assert event.event_id
        assert event.timestamp is not None


def test_subagent_event_fields():
    completed = SubagentCompleted()
    assert completed.role == ""
    assert completed.iterations == 0
    assert completed.tool_calls == 0
    assert completed.duration_seconds == 0.0
    assert completed.result == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_subagents.py -q`
Expected: FAIL — `ImportError: cannot import name 'SubagentStarted' from 'events'`

- [ ] **Step 3: Implement the events**

Append to `agent/events.py` after the Approval events section:

```python
# ────────────────────────────────────────────────────────────────
# Subagent Events
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SubagentStarted(RuntimeEvent):
    """Emitted when a subagent begins processing a delegated task."""
    role: str = ""
    task: str = ""
    agent_name: str = ""


@dataclass(frozen=True)
class SubagentMessage(RuntimeEvent):
    """Emitted with the subagent's final report text."""
    role: str = ""
    content: str = ""


@dataclass(frozen=True)
class SubagentCompleted(RuntimeEvent):
    """Emitted when a subagent finishes its task."""
    role: str = ""
    task: str = ""
    iterations: int = 0
    tool_calls: int = 0
    duration_seconds: float = 0.0
    result: str = ""


@dataclass(frozen=True)
class SubagentFailed(RuntimeEvent):
    """Emitted when a subagent fails or is cancelled."""
    role: str = ""
    task: str = ""
    error: str = ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_subagents.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add agent/events.py agent/tests/test_subagents.py
git commit -m "feat: add subagent runtime events"
```

---

### Task 5: Role instructions

**Files:**
- Create: `agent/subagent_instructions.py`
- Test: extend `agent/tests/test_subagents.py`

**Interfaces:**
- Produces: module constants `INVESTIGATOR_INSTRUCTIONS`, `IMPLEMENTER_INSTRUCTIONS`, `VERIFIER_INSTRUCTIONS` (non-empty strings used by Task 6's `SUBAGENT_ROLES`).

- [ ] **Step 1: Write the failing test (append to `agent/tests/test_subagents.py`)**

```python
from subagent_instructions import (
    IMPLEMENTER_INSTRUCTIONS,
    INVESTIGATOR_INSTRUCTIONS,
    VERIFIER_INSTRUCTIONS,
)


def test_role_instructions_are_substantive():
    for text in (INVESTIGATOR_INSTRUCTIONS, IMPLEMENTER_INSTRUCTIONS, VERIFIER_INSTRUCTIONS):
        assert len(text) > 200
        assert "Draft" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_subagents.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'subagent_instructions'`

- [ ] **Step 3: Implement `agent/subagent_instructions.py`**

```python
"""Role-specific instructions for the Draft subagents."""

INVESTIGATOR_INSTRUCTIONS = """You are Draft-Investigator, a research subagent of the Draft autonomous software engineering agent. You report to the main agent and do not interact with the user directly.

Your responsibility is investigation only: explore the repository, search and read code, inspect project structure, and gather facts. You never modify files and never run commands that change state.

Use your tools to:
- List and inspect the project structure and metadata.
- Search and read source code relevant to your task.
- Inspect git status, branches, and history when relevant.
- Search the web for information when the task requires current knowledge.

Rules:
- Work in the repository you are given. Resolve "." to the project root.
- Read before concluding: base every finding on actual file contents, never on assumptions.
- Stay focused on your assigned task; do not wander into unrelated files.
- Be precise and concise in your final report. Include exact file paths, line numbers, and quotes for key findings.
- Your final report is consumed by the main agent. Structure it as: findings, evidence, open questions.
"""

IMPLEMENTER_INSTRUCTIONS = """You are Draft-Implementer, an implementation subagent of the Draft autonomous software engineering agent. You report to the main agent and do not interact with the user directly.

Your responsibility is implementation: write, edit, and refactor code to satisfy the assigned task. You may also run Python files and syntax checks, and manage git staging/commits/branches for your changes.

Rules:
- Work in the repository you are given. Resolve "." to the project root.
- Inspect the relevant code before editing it. Read files you are about to change.
- Follow existing project conventions, naming, and structure.
- Prefer minimal, focused changes. Do not reformat unrelated code.
- After editing, run check_syntax on changed Python files and fix problems before reporting.
- You may stage and commit your own changes with clear, conventional commit messages. Never amend or force-push.
- Do not run arbitrary shell commands or delete files; those are out of scope for your role.
- Report exactly what you changed, the files touched, and any test or syntax results.
"""

VERIFIER_INSTRUCTIONS = """You are Draft-Verifier, a verification subagent of the Draft autonomous software engineering agent. You report to the main agent and do not interact with the user directly.

Your responsibility is verification: run tests, linters, and type checkers, inspect results, and report a clear pass/fail verdict. You never modify files.

Rules:
- Run the project's test suite with run_tests (pytest by default) and report pass/fail/skip counts.
- Run lint_project (ruff) and typecheck_project (mypy) when relevant to the task.
- Use run_command only for read-only checks (for example, listing or inspecting). Never modify state.
- Read diffs and files when you need context about what changed.
- If tests fail, report the failing test names and the most relevant error output; do not attempt fixes.
- Your final report must state: verdict (PASS/FAIL), counts, failing items, and a short summary of evidence.
"""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_subagents.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add agent/subagent_instructions.py agent/tests/test_subagents.py
git commit -m "feat: add subagent role instructions"
```

---

### Task 6: Subagent core (`agent/subagents.py`) + tool registration

**Files:**
- Create: `agent/subagents.py`
- Modify: `agent/tools/tools.py` (`spawn_subagent_tool` schema + ALL_TOOLS entry)
- Modify: `agent/tools/registry.py` (import + register `spawn_subagent`)
- Test: `agent/tests/test_subagents.py` (extend)

**Interfaces:**
- Consumes: Task 4 events, Task 5 instructions, `make_tool`, `TOOL_REGISTRY`, `ToolDispatcher`, `EventBus`.
- Produces:
  - `SUBAGENT_ROLES: dict[str, SubAgentRole]` — `SubAgentRole(agent_name, instructions, tools: tuple[str, ...])`
  - `configure_subagents(openai_client, dispatcher, event_bus, cancel_event) -> None`
  - `is_configured() -> bool`
  - `role_tool_defs(role: str) -> list` (FunctionTool objects for `PromptAgentDefinition`)
  - `run_subagent(role: str, task: str, timeout: int = 300) -> dict` (envelope)
  - `run_batch(calls: list[tuple[str, str, int]]) -> list[dict]` (parallel, call order preserved)
  - `spawn_subagent(role: str, task: str, timeout: int = 300) -> dict` (tool entry)
  - Constants: `MAX_SUBAGENT_ITERATIONS = 25`, `MAX_CONCURRENT_SUBAGENTS = 3`, `MAX_SUBAGENT_RESULT_CHARS = 20_000`, `DEFAULT_SUBAGENT_TIMEOUT = 300`

- [ ] **Step 1: Write the failing tests (append to `agent/tests/test_subagents.py`)**

```python
import json
import threading
import time

from event_bus import EventBus
from dispatcher import ToolDispatcher
from tools.registry import TOOL_REGISTRY
import subagents


def test_spawn_subagent_registered_in_registry():
    assert "spawn_subagent" in TOOL_REGISTRY


def test_role_definitions_are_valid():
    names = set()
    for role, role_def in subagents.SUBAGENT_ROLES.items():
        assert role in ("investigator", "implementer", "verifier")
        assert len(role_def.instructions) > 200
        assert role_def.agent_name.startswith("Draft-")
        assert "spawn_subagent" not in role_def.tools
        for tool_name in role_def.tools:
            assert tool_name in TOOL_REGISTRY
        assert role_def.agent_name not in names
        names.add(role_def.agent_name)


def test_role_tool_defs_respects_role_subset():
    investigator_tools = {getattr(t, "name", None) for t in subagents.role_tool_defs("investigator")}
    verifier_tools = {getattr(t, "name", None) for t in subagents.role_tool_defs("verifier")}
    assert "write_file" not in investigator_tools
    assert "run_tests" not in investigator_tools
    assert "write_file" not in verifier_tools
    assert "run_tests" in verifier_tools
    assert "run_command" not in subagents.role_tool_defs("implementer") and "write_file" in {getattr(t, "name", None) for t in subagents.role_tool_defs("implementer")}


def test_run_subagent_unconfigured_fails(monkeypatch):
    monkeypatch.setattr(subagents, "_context", {})
    result = subagents.run_subagent("investigator", "inspect")
    assert result["success"] is False
    assert "not configured" in result["error"]


def test_run_subagent_unknown_role_fails(monkeypatch):
    monkeypatch.setattr(subagents, "_context", {"openai_client": object()})
    result = subagents.run_subagent("bogus", "x")
    assert result["success"] is False
    assert "Unknown subagent role" in result["error"]
```

Plus a fake client and runner tests:

```python
class _FakeItem:
    def __init__(self, type, name="", arguments="", call_id="c1"):
        self.type = type
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class _FakeResponse:
    def __init__(self, outputs, output_text=""):
        self.output = outputs
        self.output_text = output_text
        self.status = "completed"


class _FakeConversation:
    def __init__(self, cid):
        self.id = cid


class _FakeOpenAI:
    """Scripted OpenAI client: each call consumes the next response."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._call_count = 0

    @property
    def conversations(self):
        return self

    def create(self):
        self._call_count += 1
        return _FakeConversation(f"conv-{self._call_count}")

    def items(self):
        return self

    def create(self, **kwargs):  # conversations.items.create
        return None

    def responses(self):
        return self

    def create(self, **kwargs):  # responses.create
        assert self._responses, "unexpected responses.create call"
        return self._responses.pop(0)


@pytest.fixture
def subagent_ctx(monkeypatch):
    """Configure subagents with a scripted client and a live dispatcher."""
    event_bus = EventBus()
    dispatcher = ToolDispatcher(event_bus=event_bus)

    def _make(client):
        monkeypatch.setattr(subagents, "_context", {
            "openai_client": client,
            "dispatcher": dispatcher,
            "event_bus": event_bus,
            "cancel_event": threading.Event(),
        })
        return dispatcher, event_bus

    return _make


def test_runner_text_only_completes(subagent_ctx):
    client = _FakeOpenAI([
        _FakeResponse([], output_text="all good"),
    ])
    subagent_ctx(client)
    result = subagents.run_subagent("verifier", "run pytest")
    assert result["success"] is True
    assert result["data"]["summary"] == "all good"
    assert result["data"]["iterations"] == 1
    assert result["data"]["tool_calls"] == 0


def test_runner_dispatches_tool_calls(subagent_ctx):
    calc_args = json.dumps({"expression": "1+1"})
    client = _FakeOpenAI([
        _FakeResponse([_FakeItem("function_call", name="calculate", arguments=calc_args, call_id="c1")]),
        _FakeResponse([], output_text="2"),
    ])
    subagent_ctx(client)
    result = subagents.run_subagent("verifier", "calculate")
    assert result["success"] is True
    assert result["data"]["tool_calls"] == 1
    assert result["data"]["summary"] == "2"


def test_runner_iteration_budget_exhausted(subagent_ctx):
    calc_args = json.dumps({"expression": "1+1"})
    responses = [_FakeResponse([_FakeItem("function_call", name="calculate", arguments=calc_args, call_id=f"c{i}")]) for i in range(30)]
    client = _FakeOpenAI(responses)
    subagent_ctx(client)
    result = subagents.run_subagent("verifier", "loop")
    assert result["success"] is False
    assert "iteration budget" in result["error"]


def test_runner_respects_cancellation(subagent_ctx):
    client = _FakeOpenAI([_FakeResponse([], output_text="late")])
    _, event_bus = subagent_ctx(client)
    subagents._context["cancel_event"].set()
    result = subagents.run_subagent("verifier", "x")
    assert result["success"] is False
    assert "cancelled" in result["error"].lower()


def test_runner_timeout(subagent_ctx):
    client = _FakeOpenAI([_FakeResponse([], output_text="late")])
    subagent_ctx(client)
    result = subagents.run_subagent("verifier", "x", timeout=0)
    assert result["success"] is False
    assert "timed out" in result["error"]


def test_run_batch_preserves_call_order(subagent_ctx):
    slow = json.dumps({"expression": "1+1"})
    responses = {
        "a": [_FakeResponse([_FakeItem("function_call", name="calculate", arguments=slow, call_id="c1")]), _FakeResponse([], output_text="first done")],
        "b": [_FakeResponse([], output_text="second done")],
    }
    client = _FakeOpenAI([])

    class _PerCallClient(_FakeOpenAI):
        def __init__(self):
            super().__init__([])
            self._made = 0

        def create(self, **kwargs):
            self._made += 1
            return _FakeConversation(f"conv-{self._made}")

        def responses(self):
            return self

        def create(self, **kwargs):
            conv_id = kwargs.get("conversation", "")
            seq = responses[conv_id]
            return seq.pop(0)

    client = _PerCallClient()
    subagent_ctx(client)
    results = subagents.run_batch([("implementer", "task a", 300), ("verifier", "task b", 300)])
    assert len(results) == 2
    assert results[0]["data"]["summary"] == "first done"
    assert results[1]["data"]["summary"] == "second done"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_subagents.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'subagents'`

- [ ] **Step 3: Implement `agent/subagents.py`**

```python
"""Role-based subagents for Draft (orchestrator pattern).

The main agent delegates bounded work to specialist subagents via the
``spawn_subagent`` tool. Subagents are hosted agents (registered as
``PromptAgentDefinition`` versions at runtime initialization) invoked
through the OpenAI Responses API with an ``agent_reference``. Each
sub-agent loop dispatches tool calls through the shared
``ToolDispatcher`` so risk classification, events, and approval
behaviour are identical to the main agent.

Parallelism: the runtime collects all ``spawn_subagent`` calls in one
response batch and executes them concurrently via ``run_batch``, which
preserves call order in its results.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from events import (
    SubagentCompleted,
    SubagentFailed,
    SubagentMessage,
    SubagentStarted,
)
from subagent_instructions import (
    IMPLEMENTER_INSTRUCTIONS,
    INVESTIGATOR_INSTRUCTIONS,
    VERIFIER_INSTRUCTIONS,
)
from tools.functions import failure, success
from tools.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

MAX_SUBAGENT_ITERATIONS = 25
MAX_CONCURRENT_SUBAGENTS = 3
MAX_SUBAGENT_RESULT_CHARS = 20_000
DEFAULT_SUBAGENT_TIMEOUT = 300


@dataclass(frozen=True)
class SubAgentRole:
    """A subagent role definition."""
    agent_name: str
    instructions: str
    tools: tuple[str, ...]


INVESTIGATOR_TOOLS = (
    "list_files", "list_directory_tree", "read_file", "get_file_info",
    "search_code", "grep", "find_files", "find_symbol", "find_references",
    "get_file_symbols", "get_current_directory", "get_project_root",
    "get_environment", "get_python_version", "which_command",
    "inspect_project", "detect_project_type", "get_project_metadata",
    "git_status", "git_diff", "git_log", "git_branch",
    "search_web", "fetch_url", "get_current_time",
)

IMPLEMENTER_TOOLS = (
    "list_files", "list_directory_tree", "read_file", "get_file_info",
    "search_code", "grep", "find_files", "find_symbol", "find_references",
    "get_file_symbols", "get_current_directory", "get_project_root",
    "get_python_version", "which_command", "inspect_project",
    "detect_project_type", "get_project_metadata",
    "write_file", "create_directory", "move_file", "copy_file",
    "apply_patch", "insert_text", "replace_text", "delete_lines",
    "run_python", "check_syntax",
    "git_status", "git_diff", "git_log", "git_show", "git_branch",
    "git_branch_create", "git_branch_switch", "git_add", "git_commit",
    "git_stash", "git_stash_pop",
    "get_current_time", "calculate", "generate_uuid",
)

VERIFIER_TOOLS = (
    "list_files", "read_file", "get_file_info",
    "search_code", "grep", "find_files", "get_file_symbols",
    "get_current_directory", "get_project_root", "get_python_version",
    "which_command", "inspect_project", "detect_project_type",
    "get_project_metadata",
    "run_tests", "lint_project", "typecheck_project",
    "run_command", "check_syntax",
    "git_status", "git_diff", "git_log", "git_show", "git_branch",
    "get_current_time",
)

SUBAGENT_ROLES: dict[str, SubAgentRole] = {
    "investigator": SubAgentRole(
        agent_name="Draft-Investigator",
        instructions=INVESTIGATOR_INSTRUCTIONS,
        tools=INVESTIGATOR_TOOLS,
    ),
    "implementer": SubAgentRole(
        agent_name="Draft-Implementer",
        instructions=IMPLEMENTER_INSTRUCTIONS,
        tools=IMPLEMENTER_TOOLS,
    ),
    "verifier": SubAgentRole(
        agent_name="Draft-Verifier",
        instructions=VERIFIER_INSTRUCTIONS,
        tools=VERIFIER_TOOLS,
    ),
}

# Runtime-injected context (set by AgentRuntime.initialize).
_context: dict[str, Any] = {}


def configure_subagents(
    openai_client: Any,
    dispatcher: Any,
    event_bus: Any,
    cancel_event: Any,
) -> None:
    """Inject runtime services used by the subagent runner."""
    _context["openai_client"] = openai_client
    _context["dispatcher"] = dispatcher
    _context["event_bus"] = event_bus
    _context["cancel_event"] = cancel_event


def is_configured() -> bool:
    """Return True when subagent services have been injected."""
    return bool(_context.get("openai_client"))


def role_tool_defs(role: str) -> list[Any]:
    """Return FunctionTool definitions for a role (for agent creation)."""
    role_def = SUBAGENT_ROLES.get(role)
    if role_def is None:
        return []
    return [
        tool for tool in ALL_TOOLS
        if getattr(tool, "name", None) in role_def.tools
    ]


def run_subagent(
    role: str,
    task: str,
    timeout: int = DEFAULT_SUBAGENT_TIMEOUT,
) -> dict[str, Any]:
    """Run one sub-agent task to completion and return its report.

    Returns the standard result envelope. ``data`` contains
    ``{"role", "summary", "iterations", "tool_calls",
    "duration_seconds"}``.
    """
    ctx = _context
    if not ctx.get("openai_client"):
        return failure("Subagents not configured. Call configure_subagents() first.")
    role_def = SUBAGENT_ROLES.get(role)
    if role_def is None:
        return failure(
            f"Unknown subagent role: {role}. Valid roles: "
            f"{', '.join(sorted(SUBAGENT_ROLES))}."
        )
    event_bus = ctx["event_bus"]
    dispatcher = ctx["dispatcher"]
    cancel_event = ctx["cancel_event"]
    o_client = ctx["openai_client"]

    event_bus.emit_threadsafe(SubagentStarted(
        role=role, task=task, agent_name=role_def.agent_name,
    ))
    start_time = time.monotonic()
    deadline = start_time + timeout

    try:
        conversation = o_client.conversations.create()
        o_client.conversations.items.create(
            conversation_id=conversation.id,
            items=[{"type": "message", "role": "user", "content": task}],
        )

        input_list: list[dict[str, Any]] = []
        tool_calls = 0
        iterations = 0
        final_text = ""

        for _ in range(MAX_SUBAGENT_ITERATIONS):
            if cancel_event.is_set():
                return failure(
                    "Subagent cancelled by user.",
                    data={"role": role, "task": task, "iterations": iterations},
                )
            if time.monotonic() > deadline:
                return failure(
                    f"Subagent timed out after {timeout}s.",
                    data={"role": role, "task": task, "iterations": iterations},
                )
            iterations += 1

            response = o_client.responses.create(
                conversation=conversation.id,
                input=input_list,
                extra_body={
                    "agent_reference": {
                        "name": role_def.agent_name,
                        "type": "agent_reference",
                    },
                },
            )
            if getattr(response, "status", "") == "failed":
                return failure(
                    f"Subagent response failed: "
                    f"{getattr(response, 'error', 'Unknown error')}",
                    data={"role": role, "task": task, "iterations": iterations},
                )

            output_items = getattr(response, "output", []) or []
            fn_calls = [
                item for item in output_items
                if getattr(item, "type", "") == "function_call"
            ]
            if not fn_calls:
                final_text = getattr(response, "output_text", "") or ""
                break

            outputs_list: list[dict[str, Any]] = []
            for item in fn_calls:
                tool_calls += 1
                try:
                    arguments = json.loads(item.arguments)
                except (json.JSONDecodeError, AttributeError) as exc:
                    result = failure(
                        f"Invalid JSON arguments for tool: {exc}"
                    )
                else:
                    result = dispatcher.dispatch_sync(
                        tool_name=item.name,
                        call_id=item.call_id,
                        arguments=arguments,
                    )
                try:
                    serialized = json.dumps(result)
                except (TypeError, ValueError):
                    result = failure(
                        f"Tool '{item.name}' produced a non-serializable result"
                    )
                    serialized = json.dumps(result)
                outputs_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": serialized,
                })
            input_list = outputs_list
        else:
            return failure(
                f"Subagent exceeded iteration budget "
                f"({MAX_SUBAGENT_ITERATIONS}).",
                data={
                    "role": role, "task": task,
                    "iterations": MAX_SUBAGENT_ITERATIONS,
                },
            )

        summary = final_text[:MAX_SUBAGENT_RESULT_CHARS]
        duration = time.monotonic() - start_time

        event_bus.emit_threadsafe(SubagentMessage(role=role, content=summary))
        event_bus.emit_threadsafe(SubagentCompleted(
            role=role,
            task=task,
            iterations=iterations,
            tool_calls=tool_calls,
            duration_seconds=duration,
            result=summary,
        ))
        return success(
            data={
                "role": role,
                "summary": summary,
                "iterations": iterations,
                "tool_calls": tool_calls,
                "duration_seconds": duration,
            },
            message=f"Subagent '{role}' completed.",
        )
    except Exception as exc:
        event_bus.emit_threadsafe(SubagentFailed(
            role=role, task=task, error=str(exc),
        ))
        return failure(
            str(exc),
            data={"role": role, "task": task},
        )


def run_batch(calls: list[tuple[str, str, int]]) -> list[dict[str, Any]]:
    """Run several (role, task, timeout) subagent calls concurrently.

    Results are returned in the same order as ``calls``.
    """
    if not calls:
        return []
    if not _context.get("openai_client"):
        return [
            failure("Subagents not configured. Call configure_subagents() first.")
            for _ in calls
        ]
    with ThreadPoolExecutor(
        max_workers=MAX_CONCURRENT_SUBAGENTS,
        thread_name_prefix="draft-subagent",
    ) as pool:
        futures = [
            pool.submit(run_subagent, role, task, timeout)
            for role, task, timeout in calls
        ]
        return [future.result() for future in futures]


def spawn_subagent(
    role: str,
    task: str,
    timeout: int = DEFAULT_SUBAGENT_TIMEOUT,
) -> dict[str, Any]:
    """Tool implementation: delegate a bounded task to a subagent."""
    return run_subagent(role=role, task=task, timeout=timeout)
```

- [ ] **Step 4: Register the tool schema and implementation**

In `agent/tools/tools.py`, before the `ALL_TOOLS` section:

```python
spawn_subagent_tool = make_tool(
    "spawn_subagent",
    "Delegate a bounded subtask to a specialist subagent. "
    "Roles: investigator (explore/search/research), implementer "
    "(write and edit code), verifier (run tests/lint/typecheck). "
    "Give the subagent a self-contained task with all needed context. "
    'Returns {"success", "data": {"role", "summary", "iterations", '
    '"tool_calls", "duration_seconds"}, "message", "error"}.',
    {
        "role": {
            "type": "string",
            "enum": ["investigator", "implementer", "verifier"],
            "description": "Specialist role to delegate to.",
        },
        "task": {
            "type": "string",
            "description": "Self-contained task for the subagent. "
                           "It cannot see this conversation.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum seconds to wait (default 300).",
        },
    },
    ["role", "task"],
)
```

Add to the `ALL_TOOLS` list after the Utilities section:

```python
    # Subagents
    spawn_subagent_tool,
```

In `agent/tools/registry.py`, add the import:

```python
from subagents import spawn_subagent
```

and register it at the end of `TOOL_REGISTRY`:

```python
    "spawn_subagent": spawn_subagent,
```

In `agent/dispatcher.py`, add `spawn_subagent` to the `SAFE` risk set so the classification table stays explicit (unknown tools already default to `SAFE`, so behavior is unchanged):

```python
    RiskLevel.SAFE: frozenset({
        "check_syntax",
        "get_current_time",
        "calculate",
        "generate_uuid",
        "search_web",
        "fetch_url",
        "spawn_subagent",
    }),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_subagents.py -q`
Expected: 14 passed

- [ ] **Step 6: Run the full agent suite for regressions**

Run: `cd agent && python -m pytest tests -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add agent/subagents.py agent/tools/tools.py agent/tools/registry.py agent/tests/test_subagents.py
git commit -m "feat: subagent runner, roles, and spawn_subagent tool"
```

---

### Task 7: Runtime integration (register, cleanup, parallel batch dispatch)

**Files:**
- Modify: `agent/runtime.py` (`__init__`, `initialize`, `cleanup`, `_execute_loop`)
- Test: `agent/tests/test_subagents.py` (append runtime registration tests)

**Interfaces:**
- Consumes: `subagents.configure_subagents`, `subagents.SUBAGENT_ROLES`, `subagents.role_tool_defs`, `subagents.run_batch`, `failure` from `tools.functions`.
- Produces: `AgentRuntime` registers and cleans up sub-agent versions; `spawn_subagent` calls in one response batch run concurrently via `subagents.run_batch`; results are appended as `FunctionCallOutput` in call order.

- [ ] **Step 1: Write the failing tests (append to `agent/tests/test_subagents.py`)**

```python
class _FakeVersion:
    def __init__(self, name, version="v1"):
        self.name = name
        self.version = version


class _FakeProjectClient:
    def __init__(self):
        self.created: list[str] = []
        self.deleted: list[tuple[str, str]] = []

    @property
    def agents(self):
        return self

    def create_version(self, agent_name, definition):
        self.created.append(agent_name)
        return _FakeVersion(agent_name)

    def delete_version(self, agent_name, agent_version):
        self.deleted.append((agent_name, agent_version))


class _FakeRuntimeOpenAI:
    """OpenAI client stub used by AgentRuntime.initialize."""

    def __init__(self):
        self.conversation_count = 0

    @property
    def conversations(self):
        return self

    def create(self):
        self.conversation_count += 1
        return _FakeConversation(f"rt-conv-{self.conversation_count}")

    @property
    def items(self):
        return self

    def create(self, **kwargs):
        return None

    @property
    def responses(self):
        return self

    def create(self, **kwargs):
        return _FakeResponse([], output_text="ready")


def test_runtime_initialize_registers_and_cleanup_deletes_subagents(monkeypatch):
    import runtime as runtime_module
    from runtime import AgentRuntime

    fake_pc = _FakeProjectClient()
    fake_oa = _FakeRuntimeOpenAI()
    monkeypatch.setattr(runtime_module, "get_project_client", lambda ep: fake_pc)
    monkeypatch.setattr(runtime_module, "get_openai_client", lambda ep: fake_oa)

    event_bus = EventBus()
    rt = AgentRuntime(event_bus=event_bus)
    rt.initialize()

    for name in ("Draft-Investigator", "Draft-Implementer", "Draft-Verifier"):
        assert name in fake_pc.created

    assert subagents.is_configured() is True

    rt.cleanup()
    for name in ("Draft-Investigator", "Draft-Implementer", "Draft-Verifier"):
        assert (name, "v1") in fake_pc.deleted
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agent && python -m pytest tests/test_subagents.py -q`
Expected: FAIL — `AssertionError: 'Draft-Investigator' not in [...]`

- [ ] **Step 3: Update `agent/runtime.py`**

Imports — add after `from tools.tools import ALL_TOOLS`:

```python
import subagents
from tools.functions import failure
```

In `__init__`, after `self._input_list: ResponseInputParam = []` add:

```python
        self._subagent_versions: list[Any] = []
```

In `initialize()`, inside the `try` block, after the main agent creation and after its `SystemMessage` ("Draft agent initialized and ready."), insert the sub-agent registration block:

```python
            o_client_rt = get_openai_client(self.endpoint)
            for role, role_def in subagents.SUBAGENT_ROLES.items():
                try:
                    version = p_client.agents.create_version(
                        agent_name=role_def.agent_name,
                        definition=PromptAgentDefinition(
                            model=self.model,
                            instructions=role_def.instructions,
                            tools=[WebSearchTool(), *subagents.role_tool_defs(role)],
                        ),
                    )
                    self._subagent_versions.append(version)
                    self.event_bus.emit_threadsafe(SystemMessage(
                        content=f"Registered subagent '{role_def.agent_name}' ({role}).",
                        level="info",
                    ))
                except Exception as exc:
                    self.event_bus.emit_threadsafe(SystemMessage(
                        content=f"Failed to register subagent '{role_def.agent_name}': {exc}",
                        level="warning",
                    ))

            if o_client_rt is not None:
                subagents.configure_subagents(
                    openai_client=o_client_rt,
                    dispatcher=self.dispatcher,
                    event_bus=self.event_bus,
                    cancel_event=self._cancel_event,
                )
```

In `cleanup()`, after the main-agent deletion block (before `def cancel`) add:

```python
        for version in self._subagent_versions:
            try:
                p_client.agents.delete_version(
                    agent_name=version.name,
                    agent_version=version.version,
                )
            except Exception as exc:
                logger.warning("Failed to cleanup subagent %s: %s", version.name, exc)
        self._subagent_versions = []
```

In `_execute_loop`, inside the `while iteration < max_iterations:` block, after the FIRST `output_items = getattr(response, "output", []) or []` line (the one followed by the `for item in output_items:` loop — do not touch the second occurrence after the follow-up `responses.create`), insert the spawn grouping:

```python
            # Group spawn_subagent calls for parallel execution
            spawn_calls: list[tuple[str, str, int] | None] = []
            spawn_items: list[Any] = []
            for item in output_items:
                if getattr(item, "type", "") != "function_call":
                    continue
                if getattr(item, "name", "") != "spawn_subagent":
                    continue
                spawn_items.append(item)
                try:
                    spawn_args = json.loads(item.arguments)
                except (json.JSONDecodeError, AttributeError):
                    spawn_calls.append(None)
                else:
                    spawn_calls.append((
                        str(spawn_args.get("role", "")),
                        str(spawn_args.get("task", "")),
                        int(spawn_args.get("timeout") or subagents.DEFAULT_SUBAGENT_TIMEOUT),
                    ))
            spawn_results: dict[str, dict[str, Any]] = {}
            spawn_parsed: dict[str, dict[str, Any]] = {}
            if spawn_items:
                valid_calls = [c for c in spawn_calls if c is not None]
                outcomes = subagents.run_batch(valid_calls) if valid_calls else []
                outcome_iter = iter(outcomes)
                for item, call in zip(spawn_items, spawn_calls):
                    if call is None:
                        spawn_results[item.call_id] = failure(
                            "Invalid JSON arguments for spawn_subagent"
                        )
                    else:
                        spawn_results[item.call_id] = next(outcome_iter)
                        spawn_parsed[item.call_id] = {
                            "role": call[0],
                            "task": call[1],
                            "timeout": call[2],
                        }
```

Then inside the existing `for item in output_items:` loop, replace the else-branch dispatch block:

```python
                else:
                    # Update current tool state
                    self.state.current_tool = item.name
                    self.state.current_tool_args = arguments

                    # Dispatch through the event-emitting dispatcher
                    result = self.dispatcher.dispatch_sync(
                        tool_name=item.name,
                        call_id=item.call_id,
                        arguments=arguments,
                    )
```

with:

```python
                else:
                    # Update current tool state
                    self.state.current_tool = item.name
                    if item.call_id in spawn_parsed:
                        self.state.current_tool_args = spawn_parsed[item.call_id]
                        result = spawn_results[item.call_id]
                    else:
                        self.state.current_tool_args = arguments
                        # Dispatch through the event-emitting dispatcher
                        result = self.dispatcher.dispatch_sync(
                            tool_name=item.name,
                            call_id=item.call_id,
                            arguments=arguments,
                        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd agent && python -m pytest tests/test_subagents.py -q`
Expected: 15 passed

- [ ] **Step 5: Run the full agent suite for regressions**

Run: `cd agent && python -m pytest tests -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add agent/runtime.py agent/tests/test_subagents.py
git commit -m "feat: register subagents at init, parallel spawn dispatch in runtime"
```

---

### Task 8: TUI + CLI rendering of subagent events

**Files:**
- Modify: `tui/widgets/workspace.py` (3 new write methods)
- Modify: `tui/app.py` (event routing)
- Modify: `agent/agent.py` (`_print_event` handlers)
- Test: `tests/test_tui_subagents.py` (new)

**Interfaces:**
- Consumes: Task 4 events `SubagentStarted/Message/Completed/Failed`.
- Produces: `AgentWorkspace.write_subagent_started(event)`, `write_subagent_message(event)`, `write_subagent_failed(event)`; app routing branches; CLI handlers.

- [ ] **Step 1: Write the failing test (`tests/test_tui_subagents.py`)**

```python
"""Tests for subagent event rendering in the Draft TUI workspace."""

import pytest
from pathlib import Path

from tui.app import DraftApp
from tui.widgets import AgentWorkspace

# tui.app adds the agent dir to sys.path, so the events module is
# importable after the tui imports above.
from events import (
    SubagentFailed,
    SubagentMessage,
    SubagentStarted,
)

_TUI_STYLES = (
    Path(__file__).resolve().parent.parent / "tui" / "styles.tcss"
)


class _TestDraftApp(DraftApp):
    """DraftApp without agent runtime initialization."""

    CSS_PATH = _TUI_STYLES

    def _init_agent(self) -> None:
        pass


@pytest.fixture
def app():
    return _TestDraftApp()


async def _settle(pilot) -> None:
    for _ in range(4):
        await pilot.pause()


def _workspace(app: DraftApp) -> AgentWorkspace:
    return app.query_one("#agent-workspace", AgentWorkspace)


def _read_log_text(log) -> str:
    return "\n".join(strip.text for strip in log.lines)


@pytest.mark.anyio
async def test_subagent_started_renders_role_and_task(app: DraftApp) -> None:
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_subagent_started(SubagentStarted(
            role="investigator",
            task="Map the repository structure",
            agent_name="Draft-Investigator",
        ))
        await _settle(pilot)
        text = _read_log_text(ws.log)
        assert "SUBAGENT" in text
        assert "investigator" in text
        assert "Map the repository structure" in text


@pytest.mark.anyio
async def test_subagent_message_renders_report(app: DraftApp) -> None:
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_subagent_message(SubagentMessage(
            role="verifier",
            content="18 passed, 0 failed",
        ))
        await _settle(pilot)
        text = _read_log_text(ws.log)
        assert "SUBAGENT verifier" in text
        assert "18 passed, 0 failed" in text


@pytest.mark.anyio
async def test_subagent_failed_renders_error(app: DraftApp) -> None:
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_subagent_failed(SubagentFailed(
            role="implementer",
            task="add flag",
            error="timed out",
        ))
        await _settle(pilot)
        text = _read_log_text(ws.log)
        assert "FAILED" in text
        assert "timed out" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_tui_subagents.py -q` (repo root)
Expected: FAIL — `AttributeError: 'AgentWorkspace' object has no attribute 'write_subagent_started'`

- [ ] **Step 3: Add the workspace methods**

In `tui/widgets/workspace.py`, after `write_system_message`, add:

```python
    # ── Subagent events ─────────────────────────────────────────

    def write_subagent_started(self, event) -> None:
        """Display a subagent task starting."""
        self.log.write(
            f"\n[bold magenta]SUBAGENT[/bold magenta]  "
            f"[bold]{escape(event.role)}[/bold]  "
            f"[yellow]RUNNING[/yellow]\n"
            f"  [dim]{escape(event.task[:200])}[/dim]"
        )

    def write_subagent_message(self, event) -> None:
        """Display a subagent's report text."""
        self.log.write(
            f"\n[bold magenta]SUBAGENT {escape(event.role)}[/bold magenta]\n"
            f"  [dim]{escape(event.content[:400])}[/dim]"
        )

    def write_subagent_failed(self, event) -> None:
        """Display a subagent failure."""
        self.log.write(
            f"\n[bold magenta]SUBAGENT {escape(event.role)}[/bold magenta]  "
            f"[red]FAILED[/red]\n"
            f"  [dim]{escape(event.error[:300])}[/dim]"
        )
```

- [ ] **Step 4: Add the TUI routing**

In `tui/app.py`, extend the events import block with:

```python
    SubagentCompleted,
    SubagentFailed,
    SubagentMessage,
    SubagentStarted,
```

In `on_runtime_event_received`, after the `AgentPhaseChanged` branch, add:

```python
        elif isinstance(event, SubagentStarted):
            workspace.write_subagent_started(event)

        elif isinstance(event, SubagentMessage):
            workspace.write_subagent_message(event)

        elif isinstance(event, SubagentFailed):
            workspace.write_subagent_failed(event)

        elif isinstance(event, SubagentCompleted):
            workspace.write_system_message(
                f"Subagent '{event.role}' completed: {event.iterations} "
                f"iterations, {event.tool_calls} tool calls.",
                level="info",
            )
```

- [ ] **Step 5: Add the CLI handlers**

In `agent/agent.py`, extend the events import block with:

```python
    SubagentCompleted,
    SubagentFailed,
    SubagentMessage,
    SubagentStarted,
```

In `_print_event`, after the `SystemMessage` branch, add:

```python
    elif isinstance(event, SubagentStarted):
        print(f"\n[SUBAGENT:{event.role}] {event.task[:120]}")
    elif isinstance(event, SubagentMessage):
        print(f"[SUBAGENT:{event.role}] {event.content[:400]}")
    elif isinstance(event, SubagentCompleted):
        print(f"[SUBAGENT:{event.role}] done ({event.iterations} iterations, "
              f"{event.tool_calls} tool calls)")
    elif isinstance(event, SubagentFailed):
        print(f"[SUBAGENT:{event.role}] failed: {event.error}")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests -q` (repo root)
Expected: all pass (8 existing + 3 new)

- [ ] **Step 7: Commit**

```bash
git add tui/widgets/workspace.py tui/app.py agent/agent.py tests/test_tui_subagents.py
git commit -m "feat: render subagent events in TUI workspace and CLI"
```

---

### Task 9: Main agent delegation note + README updates

**Files:**
- Modify: `agent/instructions.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing new.
- Produces: main-agent instructions describe `spawn_subagent`; README documents config persistence and subagents.

- [ ] **Step 1: Add the delegation section to `agent/instructions.py`**

Insert after the `UNDERSTANDING THE REQUEST` section (after the line `Never invent project files, APIs, dependencies, commands, test results, or implementation details.`):

```python
==================================================
DELEGATION TO SUBAGENTS
==================================================

You can delegate bounded work to specialist subagents with the spawn_subagent tool:

- investigator: repository exploration, code search, and research.
- implementer: writing and editing code.
- verifier: running tests, lint, and typecheck.

Delegate when a task is large or can be split into independent workstreams. Give each subagent a self-contained task with all the context it needs; a subagent cannot see this conversation. Wait for each subagent's report before continuing. Never delegate the same task twice. A subagent failure returns an error envelope: retry once, then either do the work yourself or report the failure. Do not create subagents for trivial work that one tool call can finish.
```

- [ ] **Step 2: Update README.md**

Make these edits:

1. In **Configuration** (`.env` section), add after the `.env` paragraph:

   ```markdown
   **Persistent config.** On first run you are asked for the project endpoint and model deployment; the values are stored in `.draft/config.json` (gitignored) and reused on every later launch. Load precedence: `.draft/config.json` → `.env` → default `gpt-4.1-mini`. Use `/endpoint <url>`, `/model <name>` in the TUI (or `/config-reset` to clear and re-enter), and the first-run prompts in the CLI.
   ```

2. In **Launch → TUI**, after the key-bindings paragraph, add:

   ```markdown
   First launch prompts for the project endpoint and model deployment; the values are persisted to `.draft/config.json` so later launches skip the prompt.
   ```

3. In **Architecture & System Design**, after the "Core Agent Loop" section, add:

   ```markdown
   ### Subagents (orchestrator pattern)

   The main agent can delegate bounded work to three specialist subagents through the `spawn_subagent` tool: `investigator` (explore/search/research), `implementer` (write/edit code), and `verifier` (run tests/lint/typecheck). Each role is a hosted agent version (`Draft-Investigator`, `Draft-Implementer`, `Draft-Verifier`) with role-specific instructions and a curated tool subset, invoked via `agent_reference` in fresh conversations. All `spawn_subagent` calls in one response batch run concurrently (thread pool, max 3). Subagent tool calls flow through the same `ToolDispatcher` (risk classification, events, approval), and their activity surfaces in the workspace log and timeline via `SubagentStarted` / `SubagentMessage` / `SubagentCompleted` / `SubagentFailed` events. Subagents cannot spawn subagents; each run is capped at 25 iterations with a 300-second default timeout.
   ```

4. In **Tool Catalog**, after the Utilities table, add:

   ```markdown
   #### Subagents (1)

   | Tool | Parameters | Purpose |
   |---|---|---|
   | `spawn_subagent` | `role*` (investigator/implementer/verifier), `task*`, `timeout?` (default 300) | Delegate a bounded subtask to a specialist subagent; returns its final report envelope |
   ```

   Risk classification: add `spawn_subagent` to `SAFE` in the security table and update the counts (23 READ_ONLY, 7 SAFE, 21 REQUIRES_APPROVAL, 0 BLOCKED).

5. Update **Testing & Quality Assurance** test counts if they changed (run both suites first).

- [ ] **Step 3: Run both suites to confirm counts**

Run: `cd agent && python -m pytest tests -q` and `python -m pytest tests -q` (root)
Expected: all green; note the new totals (agent suite: 122 + 15 = 137; TUI suite: 8 + 3 = 11).

- [ ] **Step 4: Commit**

```bash
git add agent/instructions.py README.md
git commit -m "docs: delegation instructions and README updates for config + subagents"
```

---

### Task 10: Full verification and plan wrap-up

**Files:** none (verification only)

- [ ] **Step 1: Run the complete agent suite**

Run: `cd agent && python -m pytest tests -q`
Expected: all tests pass

- [ ] **Step 2: Run the complete TUI suite**

Run: `python -m pytest tests -q` (repo root)
Expected: all tests pass

- [ ] **Step 3: Verify lint (if ruff is installed)**

Run: `ruff check agent tui run_tui.py tests`
Expected: no errors (or pre-existing errors only — do not fix unrelated lint)

- [ ] **Step 4: Manual smoke check (requires Azure credentials)**

Run: `python run_tui.py` with a cleared `.draft/` — confirm the config modal appears, accepts endpoint + model, and that `.draft/config.json` exists afterwards; relaunch and confirm the modal does not reappear. Then `cd agent && python agent.py` and confirm the CLI first-run prompt appears once and persists. (If no Azure setup is available, note this as a manual follow-up in the final report.)

- [ ] **Step 5: Final commit of any stragglers**

```bash
git status
git add -A && git commit -m "chore: final verification fixes" # only if changes exist
```