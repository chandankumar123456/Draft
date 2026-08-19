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
