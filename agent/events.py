"""Structured event model for the Draft agent runtime.

Every significant runtime action emits one of these events through the
EventBus.  Events are frozen dataclasses — immutable after creation —
so they are safe to pass across threads and async boundaries.

The same event stream can drive:
- The Textual TUI
- Logging / structured logging
- Automated test assertions
- Future alternative UIs
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ────────────────────────────────────────────────────────────────
# Enums
# ────────────────────────────────────────────────────────────────

class AgentStatus(Enum):
    """Lifecycle status of the agent runtime."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentPhase(Enum):
    """High-level phase within a single task execution."""
    UNDERSTANDING = "understanding"
    INVESTIGATION = "investigation"
    PLANNING = "planning"
    EXECUTION = "execution"
    VERIFICATION = "verification"


class ToolStatus(Enum):
    """Lifecycle status of a single tool call."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVAL_PENDING = "approval_pending"
    DENIED = "denied"


class RiskLevel(Enum):
    """Risk classification for tool calls."""
    READ_ONLY = "read_only"
    SAFE = "safe"
    REQUIRES_APPROVAL = "requires_approval"
    BLOCKED = "blocked"


class ApprovalDecision(Enum):
    """Human decision on an approval request."""
    APPROVED = "approved"
    DENIED = "denied"


# ────────────────────────────────────────────────────────────────
# Base Event
# ────────────────────────────────────────────────────────────────

def _make_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RuntimeEvent:
    """Base class for all runtime events.

    Every event carries a unique id and a UTC timestamp.
    Subclasses add event-specific fields.
    """
    event_id: str = field(default_factory=_make_id)
    timestamp: datetime = field(default_factory=_now)


# ────────────────────────────────────────────────────────────────
# Agent Lifecycle Events
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentStarted(RuntimeEvent):
    """Emitted when the agent begins processing a user prompt."""
    task: str = ""


@dataclass(frozen=True)
class AgentPhaseChanged(RuntimeEvent):
    """Emitted when the agent transitions to a new phase."""
    phase: AgentPhase = AgentPhase.UNDERSTANDING


@dataclass(frozen=True)
class AgentIterationStarted(RuntimeEvent):
    """Emitted at the start of each response→tool→result iteration."""
    iteration: int = 1


@dataclass(frozen=True)
class AgentCompleted(RuntimeEvent):
    """Emitted when the agent finishes a task successfully."""
    task: str = ""
    iterations: int = 0
    tool_calls: int = 0


@dataclass(frozen=True)
class AgentFailed(RuntimeEvent):
    """Emitted when the agent encounters an unrecoverable failure."""
    task: str = ""
    error: str = ""


@dataclass(frozen=True)
class AgentCancelled(RuntimeEvent):
    """Emitted when the user cancels a running task."""
    task: str = ""


# ────────────────────────────────────────────────────────────────
# Message Events (User / Agent / System)
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UserMessage(RuntimeEvent):
    """A message from the user."""
    content: str = ""


@dataclass(frozen=True)
class AgentMessage(RuntimeEvent):
    """A text response from the agent."""
    content: str = ""


@dataclass(frozen=True)
class SystemMessage(RuntimeEvent):
    """An internal system-level message (errors, info)."""
    content: str = ""
    level: str = "info"  # "info", "warning", "error"


# ────────────────────────────────────────────────────────────────
# Tool Lifecycle Events
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolStarted(RuntimeEvent):
    """Emitted when a tool call begins execution."""
    tool_name: str = ""
    call_id: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.SAFE


@dataclass(frozen=True)
class ToolCompleted(RuntimeEvent):
    """Emitted when a tool call completes successfully."""
    tool_name: str = ""
    call_id: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class ToolFailed(RuntimeEvent):
    """Emitted when a tool call fails."""
    tool_name: str = ""
    call_id: str = ""
    error: str = ""
    duration_seconds: float = 0.0


# ────────────────────────────────────────────────────────────────
# File Events
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FileRead(RuntimeEvent):
    """Emitted when a file is read by a tool."""
    path: str = ""
    lines: int = 0


@dataclass(frozen=True)
class FileChanged(RuntimeEvent):
    """Emitted when a file is created, modified, or deleted."""
    path: str = ""
    change_type: str = "modified"  # "created", "modified", "deleted"


# ────────────────────────────────────────────────────────────────
# Patch Events
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PatchStarted(RuntimeEvent):
    """Emitted when a patch application begins."""
    path: str = ""


@dataclass(frozen=True)
class PatchApplied(RuntimeEvent):
    """Emitted when a patch is applied successfully."""
    path: str = ""
    diff: str = ""


@dataclass(frozen=True)
class PatchFailed(RuntimeEvent):
    """Emitted when a patch application fails."""
    path: str = ""
    error: str = ""


# ────────────────────────────────────────────────────────────────
# Test Events
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TestStarted(RuntimeEvent):
    """Emitted when a test run begins."""
    command: str = "pytest"


@dataclass(frozen=True)
class TestResult:
    """A single test case result (not an event, just data)."""
    name: str = ""
    status: str = "passed"  # "passed", "failed", "skipped", "error"
    duration: float = 0.0
    message: str = ""


@dataclass(frozen=True)
class TestCompleted(RuntimeEvent):
    """Emitted when a test run finishes."""
    command: str = "pytest"
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    results: tuple[TestResult, ...] = ()
    raw_output: str = ""


@dataclass(frozen=True)
class TestFailed(RuntimeEvent):
    """Emitted when the test runner itself fails (not test failures)."""
    command: str = "pytest"
    error: str = ""


# ────────────────────────────────────────────────────────────────
# Git Events
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GitStatusChanged(RuntimeEvent):
    """Emitted after a git operation changes repository state."""
    operation: str = ""  # "commit", "branch_switch", "stash", etc.
    branch: str = ""
    modified_files: tuple[str, ...] = ()
    untracked_files: tuple[str, ...] = ()


# ────────────────────────────────────────────────────────────────
# Approval Events
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ApprovalRequested(RuntimeEvent):
    """Emitted when a tool call requires human approval."""
    tool_name: str = ""
    call_id: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.REQUIRES_APPROVAL


@dataclass(frozen=True)
class ApprovalResponse(RuntimeEvent):
    """Emitted when the human responds to an approval request."""
    call_id: str = ""
    decision: ApprovalDecision = ApprovalDecision.APPROVED
    reason: str = ""


# ────────────────────────────────────────────────────────────────
# State Snapshot (not an event, but a point-in-time view)
# ────────────────────────────────────────────────────────────────

@dataclass
class AgentState:
    """Mutable snapshot of the agent's current state.

    This is NOT an event. It's used by the runtime to track
    cumulative state, and by the TUI to render the state panel.
    """
    status: AgentStatus = AgentStatus.IDLE
    phase: AgentPhase = AgentPhase.UNDERSTANDING
    task: str = ""
    iteration: int = 0
    tool_call_count: int = 0
    files_read: int = 0
    files_modified: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    current_tool: str = ""
    current_tool_args: dict[str, Any] = field(default_factory=dict)
    current_tool_status: ToolStatus = ToolStatus.PENDING
