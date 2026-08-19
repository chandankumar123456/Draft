# Design — Config Persistence + Subagents

- **Date:** 2026-08-19
- **Status:** Approved (pending spec review)
- **Scope:** (1) Persist Azure endpoint + model config so first-run entry happens once; (2) introduce role-based subagents (orchestrator pattern) into the Draft agent.

## 1. Problem Statement

### 1.1 Config is forgotten between sessions

On first use, the TUI shows a mandatory config modal asking for the Azure project endpoint and model deployment. When the user submits, `_on_config_modal_closed` (`tui/app.py`) only sets `os.environ` if the runtime is `None` (which is exactly the first-run case), so `save_config()` is never called and the values are lost on exit. The same gap exists in `_update_endpoint` / `_update_model` when the runtime has not been initialized. Result: the user re-enters endpoint/model on every launch.

### 1.2 No subagents

Draft is a single agent (`Draft-Main-Agent`) running one response → tool → result loop. There is no delegation: the same model performs investigation, implementation, and verification with a 50-tool surface. The project's own phases (understanding → investigation → planning → execution → verification) map naturally onto specialist roles.

## 2. Research Summary

Subagent research (Aug 2026) surfaced two viable directions:

- **Native multi-agent orchestration** (Azure OpenAI Responses API preview): `multi_agent={"enabled": true}` lets the root agent spawn parallel subagents via hosted `multi_agent_call` items. Requires GPT-5.6 + preview API version on an Azure OpenAI resource, not AI Foundry `agent_reference` agents; no per-role instructions or curated tool subsets; no visibility into subagent tool calls for the approval gate. **Not viable for the current stack** (gpt-4.1-mini, AI Foundry agents). Documented as a future path.
- **Orchestrator + subagents via delegation tool** (Magentic pattern): the main agent gets a `spawn_subagent(role, task)` tool; role-specific agents are registered as `PromptAgentDefinition` versions and run through the same Responses API with the same dispatcher. Works with the existing stack, keeps the framework-free philosophy, gives per-role instructions + curated tools, and keeps tool calls under the same risk classification. **Chosen.**

## 3. Config Persistence (`.draft/config.json`)

### 3.1 New module `agent/config.py`

- `Config` dataclass: `endpoint: str = ""`, `model: str = "gpt-4.1-mini"`.
- `config_path() -> Path`: project root `.draft/config.json`. Project root = parent of the `agent/` package dir (same resolution used by `credential.py` for `.env`).
- `load_config() -> Config`: precedence **`.draft/config.json` → env vars / `.env` → defaults**. Read-only; never writes.
- `save_config(endpoint=None, model=None) -> None`: updates `os.environ` and writes JSON `{"endpoint": ..., "model": ...}` to `.draft/config.json` (creates `.draft/` if missing; file must never contain secrets — endpoint/model are not credentials).
- `clear_config() -> None`: deletes the file (for `/config-reset`).
- `save_config` currently in `agent/credential.py` is removed; `credential.py` keeps only client construction (`get_project_client`, `get_openai_client`). `runtime.reconfigure()` and TUI/CLI callers use `config.save_config`.

### 3.2 Entry-point wiring

- `tui/app.py on_mount`: read config via `load_config()`; missing endpoint → mandatory `ConfigModal` (unchanged UX).
- `_on_config_modal_closed`: **always** call `save_config(endpoint, model)` before initializing the runtime — fixes the first-run loss.
- `_update_endpoint` / `_update_model`: call `save_config(...)` in all paths (runtime exists or not).
- `agent/agent.py` (CLI): on start, `load_config()`; if endpoint missing → interactive `input()` prompts for endpoint + model, then `save_config`. No more silent exit-1.
- `.gitignore`: add `.draft/`.
- README: document the config file, precedence, first-run prompts.

## 4. Subagents

### 4.1 New module `agent/subagents.py`

**Role definitions** — `SUBAGENT_ROLES: dict[str, SubAgentRole]` (frozen dataclass: `agent_name`, `instructions`, `tools: list[str]`):

| Role | Azure agent | Tool subset | Notes |
|---|---|---|---|
| `investigator` | `Draft-Investigator` | read/search/project-understanding/git-status/read-only + safe web tools | no write/execution tools |
| `implementer` | `Draft-Implementer` | filesystem write/edit, code search, `apply_patch`, `run_python`, `check_syntax`, git add/commit/branch | no `run_command`, no delete tools |
| `verifier` | `Draft-Verifier` | `run_tests`, `lint_project`, `typecheck_project`, `run_command` (scoped), `read_file`, git diff/status | no write tools |

- No role receives `spawn_subagent` (recursion guard).
- Role instructions are ~300–500 words each, defined in a new `agent/subagent_instructions.py`.

**Runner** — `SubAgentRunner` executes one sub-agent loop:
1. Fresh conversation via `conversations.create`.
2. Inject task message.
3. `responses.create(conversation=..., input=..., extra_body={"agent_reference": {"name": <role agent>, "type": "agent_reference"}})`.
4. Parse `function_call` items; dispatch through the **shared `ToolDispatcher`** (same risk classification, events, approval flow).
5. Chain with the `input=` list; repeat until text-only reply or **25-iteration budget** (hard cap).
6. Check the shared `_cancel_event` between iterations; cooperative cancel.
7. Return envelope: `{"success", "data": {"summary", "iterations", "tool_calls"}, "message", "error"}`; final report text capped at 20,000 chars.

**Parallelism** — `ThreadPoolExecutor(max_workers=3)`. The runtime collects all `spawn_subagent` calls in one response batch and runs them concurrently; results merged back in call order. Shared dispatcher is thread-safe for event emission (`emit_threadsafe`).

**Context injection** — `configure_subagents(openai_client, endpoint, dispatcher, event_bus)` sets module-level context (mirrors the framework-free style of `TOOL_REGISTRY`). The tool function `spawn_subagent(role, task, timeout=300)` is registered in `TOOL_REGISTRY` and `ALL_TOOLS` (strict schema: `role` enum of the 3 names, `task` string, optional nullable `timeout` int). Risk: `SAFE`.

**Failure semantics** — sub-agent init/loop crash/timeout → `failure()` envelope; the main agent can retry or report. Failure to register a sub-agent version during `initialize()` is non-fatal (warning emitted; `spawn_subagent` returns an error envelope).

### 4.2 `runtime.py` changes

- `initialize()`: also `create_version` the 3 sub-agent definitions (model, role instructions, role `FunctionTool` schemas from `ALL_TOOLS` filtered by role subset).
- `cleanup()`: delete sub-agent versions too (idempotent, warnings on failure).
- `_execute_loop`: within each response batch, group `spawn_subagent` calls and run them concurrently via the pool; all other tools dispatch as today; results in call order.

### 4.3 Events (`agent/events.py`)

Four new frozen events:

- `SubagentStarted(role, task, agent_name)`
- `SubagentMessage(role, content)` — final report text
- `SubagentCompleted(role, task, iterations, tool_calls, duration_seconds, result)`
- `SubagentFailed(role, task, error)`

Sub-agent tool activity already surfaces via existing `ToolStarted/Completed/Failed` events (no role marker — accepted simplification).

### 4.4 TUI / CLI

- `tui/widgets/workspace.py`: log rendering for the 4 events (`[SUBAGENT] investigator → task…`, report text indented, failures).
- `TimelineView`: generic `RuntimeEvent` rendering — no change.
- `agent/agent.py` `_print_event`: prefixed handlers for the 4 events.
- `agent/instructions.py`: short delegation note in the main operating loop (delegate to matching role when the task is large or parallelizable; verify before reporting).

### 4.5 README

Tool catalog entry for `spawn_subagent`; architecture note (orchestrator → 3 subagents); security note (subagents inherit the same risk gate and event stream); test counts.

## 5. Testing

- `agent/tests/test_config.py` — save/load round-trip; precedence file > env > default; missing file → defaults; `clear_config`.
- `agent/tests/test_subagents.py` — role defs valid (non-empty instructions, every tool name exists in `TOOL_REGISTRY`); unconfigured spawn → failure envelope; runner loop with mocked `conversations.create` / `responses.create` (text-only completes; function_call dispatched + chained; budget hit → failure); batch parallel execution preserves call order; cancellation respected.
- Runtime init/cleanup with mocked client — sub-agent versions created and deleted.
- Existing suites (`cd agent && python -m pytest tests -q`, `python -m pytest tests -q` at root) stay green.

## 6. Out of Scope / Future

- Native `multi_agent.enabled` orchestration (requires GPT-5.6 + preview API) — revisit on model upgrade.
- Nested subagents (sub-subagents) — deliberately blocked.
- Per-role models/config — all roles use the configured deployment.
- Approval-gate hard enforcement stays as-is (currently advisory in default config).
