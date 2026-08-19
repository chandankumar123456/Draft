# Draft — Autonomous Software Engineering Agent

> A framework-free autonomous coding agent built on Azure AI Foundry and the OpenAI Responses API, delivered through the "Draft Developer Cockpit" (Textual TUI) and a plain terminal CLI.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Azure AI Foundry](https://img.shields.io/badge/Azure-AI%20Foundry-blue)](https://learn.microsoft.com/azure/ai-foundry/)
[![Responses API](https://img.shields.io/badge/LLM-OpenAI%20Responses%20API-black)](https://platform.openai.com/)
[![TUI](https://img.shields.io/badge/TUI-Textual-purple)](https://textual.textualize.io/)
[![Status](https://img.shields.io/badge/Status-Active%20Development-orange)]()
[![Tests](https://img.shields.io/badge/Tests-192%20cases-brightgreen)]()

---

## Table of Contents

1. [Document Metadata](#document-metadata)
2. [Executive Summary](#executive-summary)
3. [Architecture & System Design](#architecture--system-design)
4. [Getting Started Guide](#getting-started-guide)
5. [API & Integration Reference](#api--integration-reference)
6. [Operations & Maintenance](#operations--maintenance)
7. [Repository Structure](#repository-structure)
8. [Testing & Quality Assurance](#testing--quality-assurance)
9. [Glossary](#glossary)

---

## Document Metadata

| Field | Value |
| --- | --- |
| Document Title | Draft — Technical Documentation |
| Owner/Maintainer | Draft Engineering Team |
| Status | Active Development |
| Version | 1.0.0 |
| Last Updated | 2026-08-18 |
| Document Type | Technical Documentation / README |
| Audience | Engineering, DevOps, QA |
| Repository | https://github.com/chandankumar123456/Draft |
| Contact | Raise issues via the GitHub repository issue tracker |

This document establishes the technical context, capabilities, dependencies, and design principles of the Draft autonomous software-engineering agent, and serves as the entry point for the project documentation set.

---

## Executive Summary

### System Overview

Draft is an autonomous software-engineering agent that closes the loop between code generation and code verification. Given a software task, Draft understands the goal, explores the repository, reads and searches code, edits files, runs commands and tests, iterates on failures, verifies results, and reports its work. Draft is built on Azure AI Foundry, using the `azure-ai-projects` SDK (`AIProjectClient`, `PromptAgentDefinition`, `WebSearchTool`, `FunctionTool`) and the OpenAI Python SDK Responses API, with the agent registered as "Draft-Main-Agent".

The core agent loop is implemented directly in Python and is not assembled from an orchestration framework (no LangChain, LangGraph, CrewAI, AutoGen, or AGNO). This framework-free philosophy means the agent is built from the loop up: model inference, tool dispatch, event handling, and verification are all first-party code, so behavior remains explicit and auditable.

```
LLM → Decision → Tool Call → Execution → Tool Result → LLM Observes → Next Decision → Repeat
```

At every step the model observes the outcome of its previous action, so each decision is grounded in the actual state of the workspace rather than in assumption.

### Target Audience

- Software engineers who want an agent that edits and verifies code in real repositories.
- Agent-systems engineers evaluating or extending a hand-built agent loop.
- QA engineers interested in automated test execution and verification workflows.
- Researchers of agent architectures who want a minimal, readable reference implementation.
- DevOps teams evaluating autonomous tooling with human approval controls.

### Key Capabilities

- **Repository exploration** — understands project structure and goals before acting.
- **Code search** — reads and searches source code across the workspace.
- **File editing** — including patch-based edits with tracked application.
- **Command and test execution** — runs commands and tests inside the project workspace.
- **Git workflows** — commit, status, diff inspection, and related repository operations.
- **Web search** — via the Azure WebSearchTool.
- **Safe arithmetic calculator** — numeric computation without shell execution.
- **Human approval gate** — tools are risk-classified as READ_ONLY, SAFE, REQUIRES_APPROVAL, or BLOCKED, with an approval modal for human-in-the-loop control.
- **Live TUI cockpit** — the "Draft Developer Cockpit" (`python run_tui.py`) provides timeline, diff, git, and test dashboards plus drag-to-select log text; a plain terminal CLI (`agent/agent.py`) is also available.
- **Tooling surface** — 51 custom tools (filesystem, code search, code editing, execution, environment, project understanding, git, web, utilities, subagents) plus the Azure WebSearchTool.
- **Event-driven architecture** — an EventBus pub/sub system with frozen dataclass runtime events (AgentStarted, ToolStarted, ToolCompleted, PatchApplied, TestCompleted, ApprovalRequested, and others).

### Key Dependencies

| Direction | Dependency | Notes |
| --- | --- | --- |
| Upstream | Azure AI Foundry project and model deployment | Exposes an OpenAI-compatible Responses API; model selected via `MODEL_DEPLOYMENT` (default `gpt-4.1-mini`) |
| Upstream | Azure identity | `DefaultAzureCredential` for authentication |
| Upstream | git | Required for repository workflows |
| Downstream | Local filesystem and shell | Access within the project workspace, subject to tool risk classification |

### Design Principles

- **Framework-free agent core** — the loop is first-party Python, not an abstraction over an orchestration framework.
- **Tool-driven reasoning** — all meaningful actions are mediated by tools with defined contracts.
- **Closed-loop execution** — the model observes tool results before making the next decision.
- **Verification over assumption** — results are checked against the real workspace state; tests are run, not assumed to pass.
- **Least privilege** — tools are risk-classified, and destructive operations require approval.
- **Deterministic execution layer** — execution and event handling are explicit and observable.
- **Extensibility** — new tools and runtime events can be added without altering the core loop.

---

## Architecture & System Design

Draft is a framework-free autonomous software-engineering agent built directly on Azure AI Foundry primitives: the `azure-ai-projects` SDK and the OpenAI Responses API. It does not use orchestration frameworks (no LangChain, LangGraph, CrewAI, or equivalents). The agent loop, tool dispatch, event bus, terminal UI, and CLI are implemented entirely in this repository, giving full control over the execution model, observability, and safety gates.

### High-Level Architecture

```
┌──────────────┐
│    User      │   prompts, keystrokes, approval decisions
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                DraftApp (TUI)  /  CLI REPL (agent/agent.py)          │
│  StatusHeader · ProjectExplorer (DirectoryTree + git status)         │
│  AgentWorkspace (SelectableRichLog) · PromptInput                    │
│  AgentStatePanel · ToolInspector · ApprovalModal                     │
│  F-key panels: Timeline · Diff · Tests · Git                         │
└───────────┬──────────────────────────────────────┬───────────────────┘
            │  user message                        │  event consumer worker
            │  (async worker)                      │  (RuntimeEventReceived)
            ▼                                      │
┌───────────────────────────┐                      │
│       AgentRuntime        │                      │
│  _execute_loop()          │──emit (threadsafe)──▶│
│  AgentState · iteration   │                      ▼
│  counter · cancellation   │           ┌───────────────────────────────┐
└───────────┬───────────────┘           │           EventBus             │
            │                           │  async pub/sub · callbacks +   │
            │                           │  asyncio.Queue (maxsize 1000)  │
            │                           │  emit_threadsafe · history     │
            │                           └───────────────────────────────┘
            │  conversations.items.create
            │  responses.create(conversation=..., agent_reference=...)
            ▼
┌─────────────────────────────────────────────┐
│   Azure AI Foundry — Draft-Main-Agent       │
│   PromptAgentDefinition (gpt-4.1-mini,      │
│   ~3700-word instructions, 51 FunctionTools │
│   + WebSearchTool), OpenAI Responses API    │
└──────────────────┬──────────────────────────┘
                   │  response items: function_call
                   ▼
┌─────────────────────────────────────────────┐
│              ToolDispatcher                 │
│  risk classification · approval gate        │
│  (asyncio.Event + ApprovalModal) ·          │
│  dispatch_sync · ToolStarted/Completed/     │
│  Failed events · derived events             │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│           TOOL_REGISTRY (51 tools)          │
│  name → callable · strict schemas           │
│  (additionalProperties=False)               │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│        Execution environment                │
│  filesystem · shell · git · web · Python    │
│  interpreter · test runners                 │
└─────────────────────────────────────────────┘
```

**Control flow.** The user submits a prompt from the TUI or CLI. `AgentRuntime._execute_loop` injects it into a persistent Azure conversation as a message item, then calls the Responses API with an `agent_reference` to `Draft-Main-Agent` plus the full conversation history. The model decides which of its 51 tools to invoke and returns `function_call` response items. The runtime parses each call's JSON arguments, routes it through `ToolDispatcher.dispatch_sync` into the registry, and collects the result envelope. Tool results are serialized with `json.dumps` and appended as `FunctionCallOutput` entries, then submitted back to the model with `previous_response_id` for the next turn. This request–dispatch–observe cycle repeats until the model produces a text-only response. The TUI runs the loop on a worker thread and consumes events asynchronously; the CLI prints prefixed event lines to the console.

### Core Agent Loop

The agent loop is a strict decision–execution–observation cycle, implemented in `agent/runtime.py`:

1. **Inject user message.** The user's prompt is written to an Azure conversation via `conversations.items.create`, establishing a persistent session that survives multiple turns and tool calls.
2. **Invoke the agent.** `openai_client.responses.create(conversation=..., input=..., extra_body={"agent_reference": {"type": "agent_reference", ...}})` asks the hosted `Draft-Main-Agent` to continue the conversation. The model's system instructions (a ~3700-word operating loop) govern its behavior.
3. **Parse tool calls.** Response items of type `function_call` are parsed with `json.loads`; malformed arguments produce a failure envelope and are fed back to the model.
4. **Dispatch and execute.** Each call is dispatched synchronously through `ToolDispatcher.dispatch_sync` into `TOOL_REGISTRY`, which wraps the call with start/completion/failure events, risk classification, and the approval gate.
5. **Return results.** Results are serialized (`json.dumps`) and appended to `tool_outputs` as `FunctionCallOutput` items.
6. **Chain turns.** Results are submitted with `previous_response_id=response.id`, so the conversation continues without resending earlier items.
7. **Terminate.** The loop ends when a response contains no `function_call` items (a text-only reply is the agent's final report). A safety limit of 50 iterations aborts runaway sessions, and cooperative cancellation via a `threading.Event` allows the user to stop execution cleanly.

The operating loop encoded in the instructions, and enforced by the runtime, is:

```
Generate ─▶ Execute ─▶ Observe ─▶ Detect failure ─▶ Analyze ─▶ Modify ─▶ Execute again ─▶ Verify
```

Each failed tool result is observed, analyzed for cause, and repaired by a follow-up tool call (edit, patch, or test rerun); success is only reported after the verify step (tests, lint, or typecheck) passes.

### Subagents (orchestrator pattern)

The main agent can delegate bounded work to three specialist subagents through the `spawn_subagent` tool: `investigator` (explore/search/research), `implementer` (write/edit code), and `verifier` (run tests/lint/typecheck). Each role is a hosted agent version (`Draft-Investigator`, `Draft-Implementer`, `Draft-Verifier`) with role-specific instructions and a curated tool subset, invoked via `agent_reference` in fresh conversations. All `spawn_subagent` calls in one response batch run concurrently (thread pool, max 3). Subagent tool calls flow through the same `ToolDispatcher` (risk classification, events, approval), and their activity surfaces in the workspace log and timeline via `SubagentStarted` / `SubagentMessage` / `SubagentCompleted` / `SubagentFailed` events. Subagents cannot spawn subagents; each run is capped at 25 iterations with a 300-second default timeout.

### Component Breakdown

| Component | Module | Responsibility | Key Interfaces |
|---|---|---|---|
| AgentRuntime | `agent/runtime.py` | Orchestrates the agent loop: conversation injection, `agent_reference` calls, `function_call` parsing, `previous_response_id` chaining, 50-iteration limit, cancellation | `AgentRuntime._execute_loop()`, `AgentState`, `threading.Event` |
| ToolDispatcher | `agent/dispatcher.py` | Routes tool calls, classifies risk, enforces the approval gate, emits tool and derived events, wraps results in envelopes | `dispatch_sync()`, `request_approval()`, `resolve_approval()`, `classify_tool()`, `asyncio.Event` |
| Tool Registry | `agent/tools/registry.py` | Maps 51 tool names to callable implementations | `TOOL_REGISTRY: dict[str, Callable]` |
| Tool Schemas | `agent/tools/tools.py` | 51 `FunctionTool` schemas with `strict=True`, `additionalProperties=False` | `ALL_TOOLS: list[FunctionTool]` |
| Tool Implementations | `agent/tools/functions.py` | Actual filesystem, shell, git, web, Python, and test operations | `success()`, `failure()` envelope helpers |
| Event Bus | `agent/event_bus.py` | Async pub/sub: callback subscriptions, bounded `asyncio.Queue` subscriptions (maxsize 1000, drop-and-warn), thread-safe emission, event history | `subscribe()`, `emit()`, `emit_threadsafe()`, `history` |
| Event Model | `agent/events.py` | Frozen dataclass event definitions, status/phase/risk enums, mutable `AgentState` | `RuntimeEvent`, `AgentState`, `AgentStatus`, `AgentPhase`, `RiskLevel` |
| Agent Instructions | `agent/instructions.py` | ~3700-word system prompt defining the operating loop and guardrails | `instructions: str` |
| Credential Layer | `agent/credential.py` | `DefaultAzureCredential` chain, `AIProjectClient` construction, model name resolution | `project_client`, `openai_client`, `MODEL_DEPLOYMENT` |
| TUI | `tui/` | Textual 3-column cockpit: workspace log, project explorer, state panel, tool inspector, F-key views, approval modal, command palette, drag-to-select | `DraftApp`, `ApprovalModal`, worker threads, `RuntimeEventReceived` messages |
| CLI | `agent/agent.py` | `input()` REPL printing prefixed event lines | `main()` |

### Event Model

All events are frozen dataclasses inheriting `RuntimeEvent` (12-hex `event_id`, UTC `timestamp`). The bus emits them thread-safely (`loop.call_soon_threadsafe`) so the async TUI worker and synchronous agent thread stay decoupled; queue saturation drops and logs rather than blocking.

| Event | Payload highlights | Consumers |
|---|---|---|
| `AgentStarted` / `AgentCompleted` / `AgentFailed` / `AgentCancelled` | run status, result | StatusHeader, state panel, CLI |
| `AgentPhaseChanged` | `AgentPhase` (understanding/investigation/planning/execution/verification) | StatusHeader, state panel |
| `AgentIterationStarted` | iteration number | state panel, timeline |
| `UserMessage` / `AgentMessage` / `SystemMessage` | content, level | AgentWorkspace log, CLI |
| `ToolStarted` / `ToolCompleted` / `ToolFailed` | tool name, args, result envelope, duration | ToolInspector, log, state panel |
| `FileRead` / `FileChanged` | path | counters (`files_read`, `files_modified`), log |
| `PatchStarted` / `PatchApplied` / `PatchFailed` | patch metadata | DiffView |
| `TestStarted` / `TestCompleted` / `TestFailed` | pytest output parsed into pass/fail counts | TestPanel, counters |
| `GitStatusChanged` | git status snapshot | ProjectExplorer |
| `ApprovalRequested` / `ApprovalResponse` | tool name, risk level, decision | ApprovalModal, ToolInspector |

**Enums**

| Enum | Values |
|---|---|
| `AgentStatus` | `IDLE`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED` |
| `AgentPhase` | `UNDERSTANDING`, `INVESTIGATION`, `PLANNING`, `EXECUTION`, `VERIFICATION` |
| `ToolStatus` | per-tool lifecycle status |
| `RiskLevel` | `READ_ONLY`, `SAFE`, `REQUIRES_APPROVAL`, `BLOCKED` |
| `ApprovalDecision` | approval outcomes for the gate |

### Data Models & Storage

**AgentState.** A mutable dataclass tracking counters and status: `iteration`, `tool_call_count`, `files_read`, `files_modified`, `tests_passed`, `tests_failed`, `current_tool`, plus status and phase. It is updated as derived events fire and rendered live in the AgentStatePanel.

**Tool result envelope.** Every tool returns the same contract, enforced by `success()`/`failure()` helpers and verified by tests:

```json
{"success": true, "data": {...}, "message": "human-readable", "error": null}
```

Failures set `success: false` and populate `error`; `data` is always attached, even on timeout, so callers can inspect partial state.

**Azure conversation persistence.** The run's context lives in an Azure conversation (`conversations.create`, items appended via `items.create`). Each model call passes the conversation plus `agent_reference`; turns are chained with `previous_response_id`, so the conversation history accumulates across iterations while each request remains compact. A fresh `_input_list` is built per task turn, and the same conversation can carry multiple user tasks, with the model's instructions defining task boundaries.

**EventBus history.** Every emitted event is appended to the bus's history list, which drives the timeline view and enables post-hoc reconstruction of a session; queue-based subscribers receive the same events for live rendering.

### Security & Compliance

**Authentication.** Credentials come exclusively from `DefaultAzureCredential` (Azure CLI, managed identity, environment chain) via `azure-identity`; optional broker support exists for interactive flows. No API keys are stored in code; secrets live in `.env`, which is gitignored.

**Risk classification.** Every tool carries a risk level used by the dispatcher's gate:

| Risk level | Tools (51) | Example tools | Gate |
|---|---|---|---|
| `READ_ONLY` | 23 | `read_file`, `grep`, `search_code`, `git_diff`, `git_log`, `inspect_project` | none |
| `SAFE` | 7 | `check_syntax`, `calculate`, `generate_uuid`, `search_web`, `fetch_url`, `get_current_time`, `spawn_subagent` | none |
| `REQUIRES_APPROVAL` | 21 | `write_file`, `apply_patch`, `delete_file`, `run_command`, `run_python`, `run_tests`, `git_commit`, `git_stash` | approval modal |
| `BLOCKED` | 0 | — | hard block |

Approval-gated tools pause the loop (`asyncio.Event`) until the user responds through the TUI `ApprovalModal`; the tool, its arguments, and its risk level are displayed before the decision is bound. See [Operations & Maintenance](#operations--maintenance) for the current enforcement status of the approval gate.

**Command safety.** `run_command` is documented as inherently unsafe and is approval-gated. Subprocesses use a 30-second default timeout, kill on expiry, and stdout/stderr capped at 20,000 characters; the same cap applies to edit operations. The agent never inherits an interactive shell.

**Calculator sandbox.** `calculate` parses input into an AST and interprets it with a whitelist of math operations and `math` module functions. No `eval`/`exec` is ever invoked; expressions are capped at 500 characters and 30 nesting depth.

**Web fetch restrictions.** `fetch_url` caps response bodies at 200 KB and returns only whitelisted headers (`content-type`, `server`, `date`), preventing response smuggling of sensitive metadata.

**Environment disclosure.** `get_environment` returns environment variable names only — never values — so credential material cannot leak into the model context.

**Git restrictions.** Git tooling prohibits destructive operations: no `force-push`, no `--amend`; `git_commit` does not stage files (staging is a separate approval-gated `git_add`).

**Secrets policy.** The agent instructions state that API keys, tokens, and credentials must never be exposed; all secrets handling is delegated to the credential layer. **Workspace boundary.** Instructions direct the agent to operate inside the project root; `run_tui.py` changes to the project root at startup, and read/write tools resolve paths relative to that root.

---

## Getting Started Guide

This guide walks through everything required to run Draft locally: installing dependencies, configuring a connection to your Azure AI Foundry project, and verifying that the agent and its test suite work end to end.

### Prerequisites

| Requirement | Details |
| --- | --- |
| Python 3.11+ | Developed and verified on 3.11.9 |
| Azure AI Foundry project | Must contain at least one OpenAI-compatible model deployment (`gpt-4.1-mini` recommended) |
| Azure CLI or managed identity | Required for `az login` and `DefaultAzureCredential` authentication |
| git | Required to clone the repository and for the agent's git tooling |
| UTF-8-capable terminal | Required for correct TUI rendering (for example, Windows Terminal) |

The lint and typecheck tools are optional but recommended for development. `lint_project` defaults to `ruff check .` and `typecheck_project` defaults to `mypy .`, so both ruff and mypy must be installed for the agent's lint/typecheck tools to run.

### Installation

1. Clone the repository and enter the project root:

   ```bash
   git clone https://github.com/chandankumar123456/Draft.git
   cd Draft
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

   On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead of `source .venv/bin/activate`.

3. Install the runtime dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. To run the test suites (both the agent tests and the TUI selection tests), install the test dependencies:

   ```bash
   pip install pytest anyio
   ```

   `anyio` provides the pytest plugin registered in the root `conftest.py` (`pytest_plugins = ["anyio"]`), which the TUI selection tests require.

### Configuration

Create a `.env` file in the project root (it is loaded automatically via `python-dotenv`). Copy the pattern below and fill in your values:

```bash
PROJECT_ENDPOINT=<your-ai-foundry-project-endpoint>
MODEL_DEPLOYMENT=<your-model-deployment>
```

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `PROJECT_ENDPOINT` | Yes | None | The endpoint URL of your Azure AI Foundry project. There is no default; initialization of the `AIProjectClient` fails without it. Format example: `https://draft-resource.services.ai.azure.com/api/projects/Draft` |
| `MODEL_DEPLOYMENT` | No | `gpt-4.1-mini` | The name of an existing model deployment in your AI Foundry project that the agent uses |

`.env` is listed in `.gitignore`, so secrets are never committed. Treat the endpoint and deployment names as environment configuration, not credentials, and never commit environment files to the repository.

**Persistent config.** On first run you are asked for the project endpoint and model deployment; the values are stored in `.draft/config.json` (gitignored) and reused on every later launch. Load precedence: `.draft/config.json` → `.env` → default `gpt-4.1-mini`. Use `/endpoint <url>`, `/model <name>` in the TUI (or `/config-reset` to clear and re-enter), and the first-run prompts in the CLI.

Authentication uses `DefaultAzureCredential` (via `azure-identity`) and does not require any API keys in code. For local development, sign in once with the Azure CLI:

```bash
az login
```

`DefaultAzureCredential` also supports managed identity (when running on Azure-hosted compute) and environment credential flows. See the Azure Identity documentation for the full set of supported credential sources and environment variables.

### Launch

Run Draft from the project root. The agent operates on the repository you run it in: `run_tui.py` changes into the project root, and the agent's tools resolve `.` to the git top-level.

#### Running the TUI

```bash
python run_tui.py
```

`python -m tui.app` is an equivalent entry point.

On first run you will see the Draft Developer Cockpit: a status header, a workspace log, and a prompt input at the bottom. The agent initializes against your configured project endpoint and model deployment; initialization failures (for example, an invalid endpoint or bad credentials) are emitted as `SystemMessage` errors and displayed in the TUI. Type a prompt at the bottom and press Enter to submit, for example:

```
Inspect this repository and report its structure
```

Key bindings: F2 toggles the project explorer, F3 focuses the prompt, F4 opens the tool inspector, F5 shows the diff view, F6 shows the git view, F7 shows the timeline/logs, Ctrl+K opens the command palette, Ctrl+Shift+C copies the selection, and Ctrl+C quits with cleanup. Drag to select log text, which auto-copies on release. Approvals are confirmed with A (approve), D (deny), or Escape (deny).

First launch prompts for the project endpoint and model deployment; the values are persisted to `.draft/config.json` so later launches skip the prompt.

#### Running the CLI

```bash
cd agent
python agent.py
```

The CLI is a plain `input()`-based REPL over the same agent, with no TUI. It shares the same `.env` configuration and initialization path; on initialization failure it prints the `SystemMessage` error and exits with code 1.

### Verification

Complete the following steps to confirm the installation is correct.

1. Run the agent test suite (from the `agent` directory):

   ```bash
   cd agent
   python -m pytest tests -q
   ```

   149 test cases are collected and all pass.

2. Run the TUI selection tests (from the project root):

   ```bash
   python -m pytest tests -q
   ```

   43 tests are collected and all pass. These tests require the `anyio` plugin registered in the root `conftest.py`.

3. Launch the TUI and confirm that the status header shows `IDLE` together with the project, branch, and model information:

   ```bash
   python run_tui.py
   ```

4. Submit a trivial prompt such as `Run get_python_version` and confirm that the tool execution appears in the workspace log.

---

## API & Integration Reference

### Overview

Draft is not a web service. It is a local, autonomous coding agent that runs as a desktop process, and its integration surface is therefore not an HTTP API. For engineers extending the agent or embedding it in another application, the contract surface consists of four layers:

1. **Tool-calling contract** — the JSON envelope exchanged between the LLM (the Azure-hosted agent) and the Python tool implementations. This is the primary integration point for adding capabilities.
2. **Event model** — a stream of immutable, timestamped dataclasses emitted by the runtime and consumed by UI and integration layers. This is the primary integration point for observing the agent.
3. **Agent definition** — the Azure Agent (`Draft-Main-Agent`) that hosts the model, instructions, and tool schemas.
4. **Environment configuration** — the Azure endpoint and model deployment settings required at startup.

### Authentication & Agent Identity

Draft authenticates to Azure Foundry using the standard `DefaultAzureCredential` chain (environment variables, managed identity, Visual Studio / Azure CLI credentials, and similar), so no API keys are embedded in the repository. Set the required environment variables before launching the agent:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `PROJECT_ENDPOINT` | Yes | — | Azure AI Foundry project endpoint for the agent and model connection |
| `MODEL_DEPLOYMENT` | No | `gpt-4.1-mini` | Name of the deployed model used for the agent |

The agent itself is created as an Azure Agent version named **`Draft-Main-Agent`**, built with the `PromptAgentDefinition` and registered with the model deployment, the system prompt from `agent/instructions.py`, and the complete tool schema list (`ALL_TOOLS` from `agent/tools/tools.py`, which includes `WebSearchTool()` alongside the custom tools):

```python
from azure.ai.projects.models import PromptAgentDefinition, WebSearchTool

project_client.agents.create_version(
    agent_name="Draft-Main-Agent",
    definition=PromptAgentDefinition(
        model=MODEL_DEPLOYMENT,
        instructions=<system prompt>,
        tools=[WebSearchTool(), *ALL_TOOLS],
    ),
)
```

Each conversation turn is then invoked through the Responses API by reference — the caller does not manage the agent's system prompt or tool schemas per call:

```python
openai_client.responses.create(
    conversation=conversation,
    input=...,
    extra_body={
        "agent_reference": {
            "name": "Draft-Main-Agent",
            "type": "agent_reference",
        }
    },
)
```

Embedding code that wants to drive the agent should call the agent by reference exactly as above, or use `AgentRuntime` (see [Integration Examples](#integration-examples)), which handles this invocation internally.

### Tool Contract

Every custom tool returns a JSON-serializable dict with exactly four keys — `success`, `data`, `message`, `error` — produced by the `success()` / `failure()` helpers in `agent/tools/functions.py`:

```json
{
  "success": true,
  "data": { "files": ["main.py", "agent.py"], "count": 2 },
  "message": null,
  "error": null
}
```

```json
{
  "success": false,
  "data": null,
  "message": null,
  "error": "File not found: missing.py"
}
```

Contract rules:

- **`success`** (`bool`): whether the operation completed as intended. A well-formed failure is still a successful *dispatch* — the tool returns `success: false` rather than raising.
- **`data`** (`any`): the result payload, JSON-serializable. Tools returning a non-dict result (e.g. a bare string) are wrapped as `{"value": <result>}`.
- **`message`** (`str | null`): optional human-readable confirmation.
- **`error`** (`str | null`): machine- and LLM-readable failure detail; `null` on success.

**Argument handling.** LLM tool-call arguments arrive as JSON strings and are parsed with `json.loads` before dispatch. Tool schemas are declared with `FunctionTool`, `strict=True`, and `additionalProperties=False`, so the model must produce exactly the declared parameters. A parse failure produces an error envelope and the tool is **not** dispatched; an unhandled exception inside a tool is caught by the dispatcher and converted to an error envelope, and any non-serializable result is replaced with an error envelope. In all cases the envelope is fed back to the LLM as the tool output.

**Extension procedure.** Adding a capability is a three-step change, and tools are independent of the agent loop — the runtime looks them up in `TOOL_REGISTRY` by name:

1. `agent/tools/functions.py` — implement the function returning a `success(...)` / `failure(...)` envelope.
2. `agent/tools/tools.py` — add its `FunctionTool` schema (strict, `additionalProperties=False`) to `ALL_TOOLS`.
3. `agent/tools/registry.py` — register the function name in `TOOL_REGISTRY`.

### Tool Catalog

The 51 custom tools in `TOOL_REGISTRY` fall into ten categories. All parameters are optional unless marked with an asterisk (`*`). Defaults: paths resolve relative to the current working directory, timeouts are in seconds.

#### Filesystem (10)

| Tool | Parameters | Purpose |
|---|---|---|
| `list_files` | `directory="."` | List file names in a directory |
| `list_directory_tree` | `path="."`, `depth=3` | Recursive directory tree, pruned of ignored dirs |
| `read_file` | `path*`, `start_line?`, `end_line?` | Read a file, optionally a line range |
| `write_file` | `path*`, `content*`, `overwrite=True` | Create or overwrite a file |
| `get_file_info` | `path*` | File metadata (size, timestamps) |
| `create_directory` | `path*` | Create a directory |
| `delete_file` | `path*` | Delete a file |
| `delete_directory` | `path*`, `recursive=False` | Delete a directory |
| `move_file` | `source*`, `destination*` | Move / rename a file |
| `copy_file` | `source*`, `destination*` | Copy a file |

#### Code Search (6)

| Tool | Parameters | Purpose |
|---|---|---|
| `search_code` | `query*`, `path="."`, `extensions?`, `case_sensitive=False`, `max_results=200` | AST-aware search across source files |
| `grep` | `pattern*`, `path="."`, `ignore_case=False`, `max_results=200` | Regex line search |
| `find_files` | `pattern*`, `path="."` | Find files by name glob |
| `find_symbol` | `symbol*`, `path="."` | Locate a Python function/class definition |
| `find_references` | `symbol*`, `path="."` | Find references to a symbol |
| `get_file_symbols` | `path*` | List symbols defined in a file |

#### Code Editing (4)

| Tool | Parameters | Purpose |
|---|---|---|
| `apply_patch` | `file*`, `patch*` | Apply a unified diff via `git apply` with dry-run check |
| `insert_text` | `path*`, `line*`, `text*` | Insert lines at a line number |
| `replace_text` | `path*`, `old*`, `new*`, `count=-1` | Replace occurrences of a string |
| `delete_lines` | `path*`, `start_line*`, `end_line*` | Delete a line range |

#### Execution (6)

| Tool | Parameters | Purpose |
|---|---|---|
| `run_command` | `cmd*`, `cwd?`, `timeout=30` | Run a shell command (`shell=True`; documented as unsafe) |
| `run_python` | `file*`, `args?`, `timeout=30` | Run a Python script |
| `run_tests` | `cmd="pytest"`, `cwd?`, `timeout=120` | Run the test suite |
| `check_syntax` | `path*` | Syntax-check a Python file |
| `lint_project` | `cmd="ruff check ."`, `cwd?`, `timeout=120` | Lint the project |
| `typecheck_project` | `cmd="mypy ."`, `cwd?`, `timeout=120` | Static type check |

#### Environment (5)

| Tool | Parameters | Purpose |
|---|---|---|
| `get_current_directory` | — | Current working directory |
| `get_project_root` | `path="."` | Git repository root; fails outside a repo |
| `get_environment` | — | Environment variable **names** only; never values |
| `get_python_version` | — | Interpreter version |
| `which_command` | `command*` | Locate an executable on `PATH` |

#### Project Understanding (3)

| Tool | Parameters | Purpose |
|---|---|---|
| `inspect_project` | `path="."` | High-level project inventory |
| `detect_project_type` | `path="."` | Detect framework / project type |
| `get_project_metadata` | `path="."` | Project metadata (name, dependencies, etc.) |

#### Git (11)

| Tool | Parameters | Purpose |
|---|---|---|
| `git_status` | `cwd="."` | Working tree status |
| `git_diff` | `path?`, `cwd="."` | Uncommitted diff |
| `git_log` | `n=10`, `cwd="."` | Recent commit history |
| `git_show` | `commit="HEAD"`, `cwd="."` | Show a commit |
| `git_branch` | `cwd="."` | List branches |
| `git_branch_create` | `name*`, `cwd="."` | Create a branch |
| `git_branch_switch` | `name*`, `cwd="."` | Switch branches |
| `git_add` | `paths*`, `cwd="."` | Stage paths |
| `git_commit` | `message*`, `cwd="."` | Commit staged changes |
| `git_stash` | `cwd="."` | Stash working tree |
| `git_stash_pop` | `cwd="."` | Restore the latest stash |

#### Web (2)

| Tool | Parameters | Purpose |
|---|---|---|
| `search_web` | `query*` | Placeholder; reports `available: false` (use the Azure `WebSearchTool`) |
| `fetch_url` | `url*`, `timeout=20` | Fetch a URL; 200 KB cap, response-header whitelist |

#### Utilities (3)

| Tool | Parameters | Purpose |
|---|---|---|
| `get_current_time` | `utc=False` | Current date/time |
| `calculate` | `expression*` | Arithmetic via AST-whitelist sandbox; never `eval` |
| `generate_uuid` | — | Generate a UUID v4 |

#### Subagents (1)

| Tool | Parameters | Purpose |
|---|---|---|
| `spawn_subagent` | `role*` (investigator/implementer/verifier), `task*`, `timeout?` (default 300) | Delegate a bounded subtask to a specialist subagent; returns its final report envelope |

### Result Semantics & Error Handling

Tools validate their inputs and return `success: false` envelopes rather than raising. Notable behaviors:

| Tool / condition | Behavior |
|---|---|
| `replace_text` — `count` exceeds actual occurrences | Fails; no changes applied |
| `delete_lines` — invalid range (start > end, out of bounds) | Fails; no changes applied |
| `apply_patch` — no-op patch (content unchanged) or malformed diff | Fails |
| `run_command` — empty command | Fails |
| `run_command` / `run_python` — timeout exceeded | Fails |
| `read_file` — bad line range | Fails |
| `get_project_root` — path not inside a Git repository | Fails |
| `which_command` — executable not found | **Succeeds** with `data: {"path": null}` |
| `calculate` — expression outside the AST whitelist | Fails |
| `fetch_url` — HTTP error, oversized body, blocked header | Fails |
| `search_web` — placeholder tool | Succeeds with `available: false` |

Generic fallbacks applied by the dispatcher, all returned to the LLM as error envelopes:

- **JSON parse failure** of tool-call arguments → error envelope; the tool is **not** dispatched.
- **Unknown tool name** → `Unknown tool: <name>` error envelope.
- **Non-serializable result** (e.g. an object that cannot round-trip through JSON) → replaced with an error envelope.

### Event & State Interfaces

The runtime exposes a structured event stream defined in `agent/events.py`. All events are **frozen dataclasses** — immutable after creation, safe across threads and async boundaries — and inherit `event_id` (12-hex-char `uuid4` prefix) and `timestamp` (UTC) from `RuntimeEvent`.

**Event types:**

| Event | Payload | Emitted when |
|---|---|---|
| `AgentStarted` | `task` | Agent begins processing a prompt |
| `AgentPhaseChanged` | `phase` | Agent transitions phases |
| `AgentIterationStarted` | `iteration` | A response→tool→result iteration begins |
| `AgentCompleted` | `task`, `iterations`, `tool_calls` | Task finishes successfully |
| `AgentFailed` | `task`, `error` | Unrecoverable failure |
| `AgentCancelled` | `task` | Task cancelled by user |
| `UserMessage` / `AgentMessage` | `content` | Message exchanged with the user |
| `SystemMessage` | `content`, `level` | Internal system message (`info`/`warning`/`error`) |
| `ToolStarted` | `tool_name`, `call_id`, `arguments`, `risk_level` | Tool call begins |
| `ToolCompleted` | `tool_name`, `call_id`, `result`, `duration_seconds` | Tool call succeeds |
| `ToolFailed` | `tool_name`, `call_id`, `error`, `duration_seconds` | Tool call fails |
| `FileRead` | `path`, `lines` | A file is read by a tool |
| `FileChanged` | `path`, `change_type` | File created / modified / deleted |
| `PatchApplied` | `path`, `diff` | A patch applies successfully |
| `PatchFailed` | `path`, `error` | A patch application fails |
| `TestStarted` | `command` | Test run begins |
| `TestCompleted` | `command`, `passed`, `failed`, `skipped`, `errors`, `duration_seconds`, `results`, `raw_output` | Test run finishes (per-case `results` as `TestResult` tuples) |
| `TestFailed` | `command`, `error` | Test runner itself fails |
| `GitStatusChanged` | `operation`, `branch`, `modified_files`, `untracked_files` | A Git operation changes repo state |
| `ApprovalRequested` | `tool_name`, `call_id`, `arguments`, `risk_level` | A tool requires human approval |
| `ApprovalResponse` | `call_id`, `decision`, `reason` | Human resolves an approval request |

**Enums:**

| Enum | Members |
|---|---|
| `AgentStatus` | `IDLE`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED` |
| `AgentPhase` | `UNDERSTANDING`, `INVESTIGATION`, `PLANNING`, `EXECUTION`, `VERIFICATION` |
| `ToolStatus` | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `APPROVAL_PENDING`, `DENIED` |
| `RiskLevel` | `READ_ONLY`, `SAFE`, `REQUIRES_APPROVAL`, `BLOCKED` |
| `ApprovalDecision` | `APPROVED`, `DENIED` |

**EventBus API** (`agent/event_bus.py`) — async pub/sub with two subscription styles (callbacks and queues), thread-safe emission, and a built-in timeline:

| Member | Description |
|---|---|
| `subscribe(handler)` / `unsubscribe(handler)` | Register/remove an async callback receiving every event |
| `create_queue(maxsize=1000)` / `remove_queue(queue)` | Register/remove an `asyncio.Queue` receiving every event |
| `await emit(event)` | Emit from async context; delivers to queues and handlers |
| `emit_threadsafe(event)` | Emit from a non-asyncio thread; schedules delivery on the bound loop (falls back to sync queue delivery) |
| `history` | All events emitted since creation (timeline view); `clear_history()` resets |

**AgentState** — a mutable, point-in-time snapshot (not an event) used by the runtime and TUI: `status`, `phase`, `task`, `iteration`, `tool_call_count`, `files_read`, `files_modified`, `tests_passed`, `tests_failed`, `current_tool`, `current_tool_args`, `current_tool_status`.

### Integration Examples

**Observing tool activity via the EventBus** — subscribe a handler, or drain a queue, and filter on event type:

```python
from event_bus import EventBus
from events import ToolCompleted

bus = EventBus()

async def on_event(event):
    if isinstance(event, ToolCompleted):
        print(f"{event.tool_name} -> success={event.result.get('success')} "
              f"({event.duration_seconds:.3f}s)")

bus.subscribe(on_event)
```

**Driving the agent with `AgentRuntime`** — the runtime owns the agent lifecycle, the event bus, and the response loop (pattern from `agent/agent.py`):

```python
from event_bus import EventBus
from runtime import AgentRuntime

event_bus = EventBus()
runtime = AgentRuntime(event_bus=event_bus)
queue = event_bus.create_queue()

try:
    runtime.initialize()          # create Azure agent version, bind loop
    runtime.run_task("Add a --dry-run flag to the CLI")
    while not queue.empty():      # drain events at your own pace
        event = queue.get_nowait()
        print(event)
finally:
    runtime.cleanup()             # delete the agent version, close clients
```

`run_task` executes in a worker thread; all events are delivered through the bus, so `emit_threadsafe` is safe from any thread. Cancel with `runtime.cancel()` and poll completion with `runtime.is_running()`.

---

## Operations & Maintenance

### Deployment & Release Process

Draft is a local autonomous coding agent. There is no server deployment, no daemon, no remote service: "deployment" means running the application in a terminal on the engineer's machine.

**Pre-launch runbook**

1. Confirm the Python environment meets project requirements (`python --version`; install dependencies with `pip install -r requirements.txt`).
2. Authenticate against Azure: run `az login` (or confirm the DefaultAzureCredential chain resolves via managed identity or environment credentials).
3. Verify `.env` exists in the project root with a valid `PROJECT_ENDPOINT` and `MODEL_DEPLOYMENT` matching an existing deployment. The file is gitignored; recreate per machine.
4. Launch the interface:
   - TUI (recommended): `python run_tui.py`
   - Plain CLI: `python agent/agent.py`

**Session lifecycle**

- On launch, `AgentRuntime.initialize()` creates the Azure agent `Draft-Main-Agent` and a conversation. Verify initialization completed before issuing prompts (TUI state panel shows readiness; CLI prints an initialization banner).
- Submit a prompt; the agent loop executes tool calls until the task completes or the iteration budget is exhausted.
- Terminate with `Ctrl+C` in the TUI (invokes `action_quit_app`, which calls `runtime.cleanup()`), or via the CLI's `KeyboardInterrupt` handler ("Agent deleted. Goodbye.").
- `cleanup()` deletes the session's agent version; idempotent, with failures logged as warnings.

**Release notes.** Maintain notes in the commit history using the repository's conventional prefixes (`feat:`, `refactor:`, `chore:`, `test:`, `style:`); tag releases in git. There is no release artifact to publish.

### Monitoring & Observability

Draft has no external metrics or logging system. Observability is built into the TUI, backed by the in-memory EventBus:

| Surface | Key | Purpose |
|---|---|---|
| TimelineView | `F7` | Every event with timestamps; the primary session audit log |
| ToolInspector | `F4` | Raw tool call JSON and results |
| DiffView | `F5` | File diffs from editing tools |
| GitScreen | `F6` | Git operation history and status |
| State panel | - | Iteration/tool counters |
| Workspace log | - | Chronological activity feed; drag-select to copy |

**EventBus as audit log.** The EventBus records all agent, tool, and system events; `TimelineView` renders this history for the session. The queue is bounded (maxsize 1000) and drops events with a warning when full (rare, as the TUI consumes events continuously); history grows unbounded in memory for the life of the process.

**Recommendation.** No events persist after process exit. For long-running or high-value sessions, capture the timeline output before quitting (drag-select-to-copy; no built-in export).

### Session Controls

| Control | Behavior |
|---|---|
| Iteration budget | Hard-coded `max_iterations = 50` in `runtime.py`; the loop terminates with a budget-exceeded event when exhausted. |
| Cooperative cancellation | TUI "Stop Agent" calls `runtime.cancel()`, setting a `threading.Event` the loop checks between iterations; cooperative, not preemptive. |
| Clean exit | `Ctrl+C` in the TUI triggers the quit action and `runtime.cleanup()`; the CLI exits with "Agent deleted. Goodbye." |
| Approval workflow | `REQUIRES_APPROVAL` tools surface a TUI modal: `A` approve, `D` deny, `Escape` cancel. |

**Known limitation (approval gate).** The approval modal (`request_approval` / `resolve_approval`) is implemented and wired to the TUI, and `dispatch_sync` classifies every tool call and emits its `RiskLevel` in the event stream. However, `approval_enabled` defaults to `False` and dispatch does not currently block on the approval result, so in the default configuration approval is advisory: treat the emitted risk level as the authoritative signal and monitor `REQUIRES_APPROVAL` events for tools such as `write_file`, `delete_*`, `apply_patch`, `run_command`, and `git_commit`. Enable the gate deliberately if hard enforcement is required.

**Output truncation limits.** Tool results are capped to bound memory and context:

| Tool / surface | Limit |
|---|---|
| subprocess output (`run_command`, `run_python`, `run_tests`) | 20,000 chars; default timeout 30s (tests 120s, web fetch 20s) |
| `read_file` | 50,000 chars |
| `list_directory_tree` | 500 entries |
| `search_code` (`max_results`) | 200 |
| `fetch_url` | 200,000 bytes |
| `git_*` commands | 30s timeout |

Truncated results carry `truncated` flags in the result data.

### Troubleshooting

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `SystemMessage` error at startup; CLI exits 1 | Missing or invalid `PROJECT_ENDPOINT`; `AIProjectClient` init fails | Set a valid `PROJECT_ENDPOINT` in `.env` and relaunch |
| Authentication failure at startup | No `az login`; credential chain does not match | Run `az login`, or configure managed identity / environment credentials |
| `RuntimeError: Response failed: {error}` | `MODEL_DEPLOYMENT` does not match an existing deployment | Correct `MODEL_DEPLOYMENT` to an existing deployment name |
| Tool returns an error envelope | Tool arguments failed JSON parse; tool skipped | By design; inspect arguments in ToolInspector (`F4`) |
| Command hangs or reports `timed_out=True` | Subprocess exceeded the timeout | Increase the tool's timeout parameter |
| Large output truncated at 20,000 chars | Output cap enforced | Expected; check the `truncated` flag and re-run with narrower scope |
| `run_command` executes arbitrary shell input | Shell execution by design | Do not feed untrusted input; `run_command` is `shell=True` and documented unsafe |
| Git tools fail with "Invalid working directory" | `git` missing from `PATH`, or running outside a repository | Install git; run within a git working tree |
| Events missing from timeline | EventBus queue full (maxsize 1000); dropped with warning | Rare with the TUI consumer; capture the timeline sooner |
| `ModuleNotFoundError: pytest` / `anyio` | Test-only dependencies not in `requirements.txt` | `pip install pytest anyio`, then run the suites below |

### Backup & Recovery

- **Code state.** Git is the source of recovery. Commit with the repository's conventional prefixes and check `git status` before/after agent sessions. The scratch git repo used by the test suite never touches the real repo.
- **Configuration.** `.env` is gitignored by design and must be recreated per machine (endpoint; secrets never committed). On a new machine: copy values from a trusted source, then verify startup per the Deployment runbook.
- **Azure state.** Sessions create conversations in the AI Foundry project. `cleanup()` deletes the agent version but not conversations, which persist until removed; delete stale conversations via the AI Foundry portal periodically. If `cleanup()` fails (logged as a warning), delete the surviving agent version manually.
- **Session output.** For long-running tasks, snapshot terminal output (timeline, tool results) before quitting; the EventBus is memory-only and lost on exit.

### Maintenance & Contribution Notes

**Adding a tool** touches three files:

1. `agent/tools/functions.py` — implement the tool function (validation, truncation limits, timeout policy).
2. `agent/tools/registry.py` — import and register the function in `TOOL_REGISTRY`.
3. `agent/dispatcher.py` — classify the tool in the risk registry (`READ_ONLY`, `SAFE`, or `REQUIRES_APPROVAL`; `BLOCKED` is unused, 0 tools).

Current risk profile: 23 `READ_ONLY`, 7 `SAFE`, 21 `REQUIRES_APPROVAL`, 0 `BLOCKED`.

**Testing.** The agent suite requires `pytest` and `anyio` (not in `requirements.txt`; install explicitly). Git tests run against a scratch repository fixture and never touch the real repo. Run both suites before committing:

```bash
cd agent && python -m pytest tests -q    # agent suite (149 tests)
cd .. && python -m pytest tests -q       # TUI suite (43 tests)
```

**Commit conventions.** Use the observed conventional prefixes (`feat:`, `refactor:`, `chore:`, `test:`, `style:`). Keep commits scoped; history (72 commits on `main` plus `wave-*`/`feature-*` integration branches) uses short, descriptive subjects. Push to `github.com/chandankumar123456/Draft`.

---

## Repository Structure

Draft is a small monorepo: a framework-free agent package, a Textual-based terminal cockpit, and a root test suite. The layout below reflects the repository at this revision.

```
Draft/
├── run_tui.py                 # Launcher: path fix, chdir root, DraftApp().run()
├── requirements.txt           # 6 unpinned deps: python-dotenv, httpx, azure-ai-projects,
│                              #   azure-identity, azure-identity-broker, textual
├── conftest.py                # pytest_plugins = ["anyio"]
├── __init__.py                # Package marker
├── .env                       # Gitignored: PROJECT_ENDPOINT, MODEL_DEPLOYMENT
├── .gitignore
├── agent/                     # Agent runtime package
│   ├── agent.py               # CLI entry: REPL, event printing
│   ├── main.py                # Empty placeholder (0 bytes; not an entry point)
│   ├── prompts.py             # Empty placeholder; instructions in instructions.py
│   ├── instructions.py        # System prompt (~3,700 words)
│   ├── runtime.py             # AgentRuntime, core loop (370 lines)
│   ├── dispatcher.py          # ToolDispatcher, risk classification, derived events (418 lines)
│   ├── events.py              # Event dataclasses, enums, AgentState (326 lines)
│   ├── event_bus.py           # EventBus pub/sub (175 lines)
│   ├── credential.py          # DefaultAzureCredential, AIProjectClient, openai_client (19 lines)
│   ├── tools/
│   │   ├── functions.py       # 50 tool implementations (3,345 lines)
│   │   ├── registry.py        # TOOL_REGISTRY dict (126 lines)
│   │   └── tools.py           # 51 FunctionTool schemas, ALL_TOOLS (1,080 lines)
│   └── tests/                 # 11 files, 149 test cases
├── tui/                       # Textual interface, "Draft Developer Cockpit"
│   ├── app.py                 # DraftApp, 3-column cockpit (616 lines)
│   ├── screens.py             # Diff, Tool Inspector, Timeline, Test Dashboard (unused), Git
│   ├── widgets.py             # 13 custom widgets (1,133 lines)
│   ├── messages.py            # Textual messages (RuntimeEventReceived used; 4 unused)
│   └── styles.tcss            # Dark navy theme (284 lines)
├── tests/                     # 6 TUI suites (workspace, features, ux, selection, config, subagents)
│                              #   43 async tests (anyio, Textual run_test pilot)
└── Plan/                      # Gitignored design assets: 14 PNG slides,
                               #   Draft Architecture.pdf, Plan.pdf (image-based)
```

| Directory / File | Purpose |
|---|---|
| `run_tui.py` | Entry point for the cockpit; path setup, launches `DraftApp`. |
| `agent/` | Core agent: runtime loop, tool dispatch, event model, Azure credentials, 51 tools. |
| `agent/tools/` | Tool implementations, JSON-schema definitions, lookup registry. |
| `agent/tests/` | Eleven agent test suites (149 cases). |
| `tui/` | "Draft Developer Cockpit": 3-column layout, panels, screens, styling. |
| `tests/` | Six root TUI suites (43 cases) exercising TUI behavior via Textual's `run_test` pilot. |
| `Plan/` | Design deliverables (slides and PDFs), gitignored. |

Two honesty notes. `agent/main.py` is an empty placeholder (0 bytes) and not an entry point; the CLI entry lives in `agent/agent.py`. `agent/prompts.py` is likewise empty; the system prompt is maintained in `agent/instructions.py`.

---

## Testing & Quality Assurance

### Test Overview

Draft ships 192 test cases across 17 suites (173 test functions): 149 agent tests plus 43 TUI tests. All suites share `assert_envelope`, which verifies the `{success, data, message, error}` contract every tool response must honor.

| Suite | Location | Cases | Focus |
|---|---|---|---|
| Filesystem | `agent/tests/test_filesystem.py` | 24 | File read/write/list operations |
| Git | `agent/tests/test_git.py` | 12 | Git operations on isolated scratch repos |
| Editing | `agent/tests/test_editing.py` | 19 (16 fns) | Apply/edit operations and constraints |
| Environment & Web | `agent/tests/test_environment_web.py` | 11 | Environment queries, web fetches |
| Execution | `agent/tests/test_execution.py` | 18 (15 fns) | Execution, truncation, timeouts |
| Project | `agent/tests/test_project.py` | 6 | Project introspection |
| Search | `agent/tests/test_search.py` | 15 (13 fns) | Search and result shaping |
| Utilities | `agent/tests/test_utilities.py` | 17 (6 fns) | Shared helpers |
| Config | `agent/tests/test_config.py` | 11 | Persistent config (`.draft/config.json`) load/save and precedence |
| Runtime | `agent/tests/test_runtime.py` | 2 | AgentRuntime subagent integration (spawn grouping, concurrency) |
| Subagents | `agent/tests/test_subagents.py` | 14 | Subagent events, roles, runner, runtime integration |
| TUI Selection | `tests/test_tui_selection.py` | 6 | Drag-selection protocol in the cockpit |
| TUI Workspace | `tests/test_tui_workspace.py` | 12 | Tool cards, smart auto-scroll, selection stability |
| TUI Features | `tests/test_tui_features.py` | 14 | Slash commands, multiline input, config modal, streaming, diff rendering |
| TUI UX | `tests/test_tui_ux.py` | 6 | Header toggle, input affordances, thinking indicator, stop mechanism, footer bar |
| TUI Config | `tests/test_tui_config.py` | 2 | TUI config persistence (`.draft/config.json`) |
| TUI Subagents | `tests/test_tui_subagents.py` | 3 | Subagent event rendering in the workspace |

### Running the Test Suites

```bash
cd agent && python -m pytest tests -q    # agent suites (149 cases)
python -m pytest tests -q                # root suites (43 cases)
```

Python 3.11+ is required. Both suites depend on `pytest` (9.1.1) and `anyio` (4.14.2), installed in the project virtual environment (`draft_venv`) but not declared in `requirements.txt`; see Known Quality Gaps.

### Test Coverage Highlights

- **Envelope contract enforcement.** Every suite validates the unified `{success, data, message, error}` shape, ensuring tools never leak unstructured payloads to the runtime.
- **Scratch-repo Git isolation.** Git tests use a `scratch_repo` fixture on `tmp_path`, exercising history, remotes, and working trees without touching developer repositories.
- **Calculator sandbox security tests.** The sandbox rejects 9 dangerous expressions, covering the security boundary of the calculator tool.
- **Truncation and timeout edge cases.** Execution tests cover output truncation and command timeouts, the most failure-prone paths in the sandboxed runner.
- **TUI drag-selection protocol.** `test_tui_selection.py` drives the cockpit via Textual's `run_test` pilot (with `_init_agent` stubbed) to verify selection behavior end-to-end.

### Known Quality Gaps

The following are tracked as an improvement backlog rather than resolved issues:

- **No CI pipeline.** No continuous integration configuration exists; test execution depends on local runs.
- **No linting or typechecking configuration.** No linter, formatter, or type-checker settings are committed.
- **Unpinned dependencies.** `requirements.txt` declares versions unpinned, allowing environment drift across installs.
- **Testing dependencies undeclared.** `pytest` and `anyio` are required by the suites but absent from `requirements.txt`; anyio is wired through `conftest.py` rather than a packaging file. There is also no `pyproject.toml`.

---

## Glossary

| Term | Definition |
|---|---|
| Agent | The "Draft-Main-Agent" Azure agent definition registered in Azure AI Foundry, which Draft's runtime connects to for turn execution. |
| Agent Loop | The iterate-execute cycle in `AgentRuntime`: submit the conversation to the model, receive tool calls, dispatch them, append results, repeat until a final answer. |
| AgentRuntime | Class implementing the agent loop and orchestrating credential, client, dispatcher, event bus, and tools (`agent/runtime.py`). |
| AgentState | Mutable dataclass (in `agent/events.py`) tracking the run's live counters and status — iteration, tool calls, files read/modified, tests passed/failed, current tool. Not an event. |
| Approval Gate | Control point where a tool call classified `REQUIRES_APPROVAL` pauses for operator consent before execution; surfaced in the TUI as the Approval Modal. |
| BLOCKED | `RiskLevel` value for tools that must never execute without intervention; currently no tool is classified `BLOCKED`. |
| Conversation | The ordered transcript of user messages, assistant messages, and tool results maintained by Azure across turns of a session. |
| DefaultAzureCredential | Azure Identity credential chain used by `credential.py` to authenticate against Azure AI Foundry endpoints without hard-coded secrets. |
| Envelope | The uniform response container `{success, data, message, error}` returned by every tool and asserted by `assert_envelope` in tests. |
| EventBus | Pub/sub component (`agent/event_bus.py`) decoupling runtime internals from UI and logging consumers. |
| FunctionTool | A tool exposed to the model as a callable function with a JSON schema; Draft defines 51 via the Azure AI Foundry SDK. |
| Human-in-the-Loop | Design principle by which risky operations pause for operator review through approval gates rather than executing autonomously. |
| MCP | Model Context Protocol; a standardization context for tool and agent interoperability (referenced in Draft's design materials). |
| PromptAgentDefinition | Azure AI Foundry construct describing an agent's instructions and tool configuration; the basis of the Draft-Main-Agent definition. |
| READ_ONLY | Risk classification for tools that only read state and never mutate it; executed without approval. |
| REQUIRES_APPROVAL | Risk classification for tools that mutate state or execute commands; gated behind the Approval Gate. |
| Responses API | The OpenAI Responses API, Draft's model interface layer alongside Azure AI Foundry projects. |
| Risk Level | Classification assigned per tool call (`SAFE`, `READ_ONLY`, `REQUIRES_APPROVAL`, `BLOCKED`) by the `ToolDispatcher`. |
| SAFE | Risk classification for tools with no meaningful side effects; executed without approval. |
| Tool Dispatcher | `ToolDispatcher` (`agent/dispatcher.py`); validates, risk-classifies, and routes tool calls to implementations, emitting derived events. |
| Tool Registry | `TOOL_REGISTRY` dictionary (`agent/tools/registry.py`) mapping tool names to implementations. |
| Tool Schema | A FunctionTool's JSON-schema definition of inputs and outputs, declared in `agent/tools/tools.py`. |
| Textual | The Python terminal UI framework used to build the "Draft Developer Cockpit" TUI layer. |

---

*Document revision 1.0.0 — maintained by the Draft Engineering Team. For issues or changes, open a ticket in the [repository issue tracker](https://github.com/chandankumar123456/Draft/issues).*
