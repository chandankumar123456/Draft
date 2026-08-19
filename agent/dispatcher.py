"""Tool dispatcher with structured event emission.

Wraps the existing ``TOOL_REGISTRY`` dictionary from
``tools/registry.py`` without modifying any tool function.  For every
tool call, the dispatcher:

1. Classifies the tool by risk level.
2. If the tool requires approval and approval mode is enabled,
   emits ``ApprovalRequested`` and waits for a response.
3. Emits ``ToolStarted``.
4. Calls the underlying function.
5. Emits ``ToolCompleted`` or ``ToolFailed``.
6. Emits derived events (``FileRead``, ``FileChanged``,
   ``PatchApplied``, ``TestCompleted``, ``GitStatusChanged``, etc.)
   based on the tool name and its result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from events import (
    ApprovalDecision,
    ApprovalRequested,
    ApprovalResponse,
    FileChanged,
    FileRead,
    GitStatusChanged,
    PatchApplied,
    PatchFailed,
    PatchStarted,
    RiskLevel,
    TestCompleted,
    TestFailed,
    TestResult,
    TestStarted,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)
from event_bus import EventBus
from tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
# Risk Classification
# ────────────────────────────────────────────────────────────────

RISK_CLASSIFICATION: dict[RiskLevel, frozenset[str]] = {
    RiskLevel.READ_ONLY: frozenset({
        "list_files",
        "list_directory_tree",
        "read_file",
        "get_file_info",
        "search_code",
        "grep",
        "find_files",
        "find_symbol",
        "find_references",
        "get_file_symbols",
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_branch",
        "get_current_directory",
        "get_project_root",
        "get_environment",
        "get_python_version",
        "which_command",
        "inspect_project",
        "detect_project_type",
        "get_project_metadata",
    }),
    RiskLevel.SAFE: frozenset({
        "check_syntax",
        "get_current_time",
        "calculate",
        "generate_uuid",
        "search_web",
        "fetch_url",
        "spawn_subagent",
    }),
    RiskLevel.REQUIRES_APPROVAL: frozenset({
        "write_file",
        "create_directory",
        "delete_file",
        "delete_directory",
        "move_file",
        "copy_file",
        "apply_patch",
        "insert_text",
        "replace_text",
        "delete_lines",
        "run_command",
        "run_python",
        "run_tests",
        "lint_project",
        "typecheck_project",
        "git_add",
        "git_commit",
        "git_branch_create",
        "git_branch_switch",
        "git_stash",
        "git_stash_pop",
    }),
    RiskLevel.BLOCKED: frozenset(),
}

# Inverted lookup: tool_name → RiskLevel
_TOOL_RISK: dict[str, RiskLevel] = {}
for _level, _tools in RISK_CLASSIFICATION.items():
    for _tool in _tools:
        _TOOL_RISK[_tool] = _level


def classify_tool(name: str) -> RiskLevel:
    """Return the risk level for a tool name."""
    return _TOOL_RISK.get(name, RiskLevel.SAFE)


# ────────────────────────────────────────────────────────────────
# Tool Dispatcher
# ────────────────────────────────────────────────────────────────

class ToolDispatcher:
    """Dispatches tool calls with event emission and optional approval.

    Parameters
    ----------
    event_bus : EventBus
        The bus to emit events on.
    approval_enabled : bool
        When True, REQUIRES_APPROVAL tools block until the human
        approves or denies via the TUI.  Defaults to False.
    """

    def __init__(
        self,
        event_bus: EventBus,
        approval_enabled: bool = False,
    ) -> None:
        self.event_bus = event_bus
        self.approval_enabled = approval_enabled

        # Pending approvals: call_id → asyncio.Event
        self._pending_approvals: dict[str, asyncio.Event] = {}
        self._approval_decisions: dict[str, ApprovalDecision] = {}

    # ── Public API ────────────────────────────────────────────

    def dispatch_sync(
        self,
        tool_name: str,
        call_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a tool call synchronously (for thread context).

        This is the primary method called by the AgentRuntime which
        runs in a worker thread.  Events are emitted via
        ``emit_threadsafe``.
        """
        risk = classify_tool(tool_name)

        # Emit ToolStarted
        self.event_bus.emit_threadsafe(ToolStarted(
            tool_name=tool_name,
            call_id=call_id,
            arguments=arguments,
            risk_level=risk,
        ))

        # Look up function
        function = TOOL_REGISTRY.get(tool_name)
        if function is None:
            error_msg = f"Unknown tool: {tool_name}"
            self.event_bus.emit_threadsafe(ToolFailed(
                tool_name=tool_name,
                call_id=call_id,
                error=error_msg,
                duration_seconds=0.0,
            ))
            return {
                "success": False,
                "data": None,
                "message": None,
                "error": error_msg,
            }

        # Execute
        start_time = time.monotonic()
        try:
            result = function(**arguments)
        except Exception as exc:
            duration = time.monotonic() - start_time
            error_msg = f"Tool '{tool_name}' failed: {exc}"
            self.event_bus.emit_threadsafe(ToolFailed(
                tool_name=tool_name,
                call_id=call_id,
                error=error_msg,
                duration_seconds=duration,
            ))
            return {
                "success": False,
                "data": None,
                "message": None,
                "error": error_msg,
            }

        duration = time.monotonic() - start_time

        # Emit ToolCompleted
        self.event_bus.emit_threadsafe(ToolCompleted(
            tool_name=tool_name,
            call_id=call_id,
            result=result if isinstance(result, dict) else {"value": result},
            duration_seconds=duration,
        ))

        # Emit derived events
        self._emit_derived_events(tool_name, arguments, result)

        return result

    # ── Approval ──────────────────────────────────────────────

    async def request_approval(
        self,
        tool_name: str,
        call_id: str,
        arguments: dict[str, Any],
    ) -> ApprovalDecision:
        """Request human approval for a tool call.

        Emits ``ApprovalRequested`` and blocks until a matching
        ``resolve_approval`` is called (from the TUI).
        """
        risk = classify_tool(tool_name)
        await self.event_bus.emit(ApprovalRequested(
            tool_name=tool_name,
            call_id=call_id,
            arguments=arguments,
            risk_level=risk,
        ))

        # Create a wait event
        wait = asyncio.Event()
        self._pending_approvals[call_id] = wait
        await wait.wait()

        # Retrieve decision
        decision = self._approval_decisions.pop(call_id, ApprovalDecision.DENIED)
        del self._pending_approvals[call_id]
        return decision

    def resolve_approval(
        self,
        call_id: str,
        decision: ApprovalDecision,
    ) -> None:
        """Resolve a pending approval request (called from TUI)."""
        self._approval_decisions[call_id] = decision
        wait = self._pending_approvals.get(call_id)
        if wait is not None:
            wait.set()

    # ── Derived Events ────────────────────────────────────────

    def _emit_derived_events(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
    ) -> None:
        """Emit higher-level events based on tool results."""
        if not isinstance(result, dict):
            return

        success = result.get("success", False)

        # File reads
        if tool_name == "read_file" and success:
            data = result.get("data", {}) or {}
            line_count = data.get("line_count", 0) if isinstance(data, dict) else 0
            self.event_bus.emit_threadsafe(FileRead(
                path=arguments.get("path", ""),
                lines=line_count,
            ))

        # File modifications
        FILE_MODIFY_TOOLS = {
            "write_file", "insert_text", "replace_text",
            "delete_lines", "move_file", "copy_file",
        }
        if tool_name in FILE_MODIFY_TOOLS and success:
            path = arguments.get("path", arguments.get("source", ""))
            change_type = "modified"
            if tool_name == "write_file":
                change_type = "created"
            self.event_bus.emit_threadsafe(FileChanged(
                path=str(path),
                change_type=change_type,
            ))

        # File creation
        if tool_name == "create_directory" and success:
            self.event_bus.emit_threadsafe(FileChanged(
                path=arguments.get("path", ""),
                change_type="created",
            ))

        # File deletion
        if tool_name in ("delete_file", "delete_directory") and success:
            self.event_bus.emit_threadsafe(FileChanged(
                path=arguments.get("path", ""),
                change_type="deleted",
            ))

        # Patches
        if tool_name == "apply_patch":
            path = arguments.get("file", "")
            if success:
                self.event_bus.emit_threadsafe(PatchApplied(
                    path=path,
                    diff=arguments.get("patch", ""),
                ))
                self.event_bus.emit_threadsafe(FileChanged(
                    path=path,
                    change_type="modified",
                ))
            elif not success:
                self.event_bus.emit_threadsafe(PatchFailed(
                    path=path,
                    error=result.get("error", "Unknown error"),
                ))

        # Tests
        if tool_name == "run_tests":
            if success:
                self._emit_test_events(arguments, result)
            else:
                self.event_bus.emit_threadsafe(TestFailed(
                    command=arguments.get("cmd", "pytest"),
                    error=result.get("error", "Test run failed"),
                ))

        # Git operations
        GIT_STATE_TOOLS = {
            "git_add", "git_commit", "git_branch_create",
            "git_branch_switch", "git_stash", "git_stash_pop",
        }
        if tool_name in GIT_STATE_TOOLS and success:
            self.event_bus.emit_threadsafe(GitStatusChanged(
                operation=tool_name.replace("git_", ""),
            ))

    def _emit_test_events(
        self,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """Parse test output and emit structured TestCompleted."""
        data = result.get("data", {}) or {}
        stdout = ""
        if isinstance(data, dict):
            stdout = data.get("stdout", "")
        elif isinstance(data, str):
            stdout = data

        # Try to parse pytest summary line
        passed = failed = skipped = errors = 0
        duration = 0.0

        # Match patterns like "18 passed, 1 failed, 2 skipped in 4.73s"
        summary_match = re.search(
            r"(?:(\d+)\s+passed)?"
            r"(?:,?\s*(\d+)\s+failed)?"
            r"(?:,?\s*(\d+)\s+skipped)?"
            r"(?:,?\s*(\d+)\s+error)?"
            r"(?:\s+in\s+([\d.]+)s)?",
            stdout,
        )
        if summary_match:
            passed = int(summary_match.group(1) or 0)
            failed = int(summary_match.group(2) or 0)
            skipped = int(summary_match.group(3) or 0)
            errors = int(summary_match.group(4) or 0)
            duration = float(summary_match.group(5) or 0)

        # Parse individual test results
        test_results: list[TestResult] = []
        for match in re.finditer(
            r"(PASSED|FAILED|SKIPPED|ERROR)\s+(\S+)", stdout
        ):
            status_str = match.group(1).lower()
            name = match.group(2)
            test_results.append(TestResult(
                name=name,
                status=status_str,
            ))

        self.event_bus.emit_threadsafe(TestCompleted(
            command=arguments.get("cmd", "pytest"),
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration_seconds=duration,
            results=tuple(test_results),
            raw_output=stdout,
        ))
