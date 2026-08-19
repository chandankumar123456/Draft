"""Tests for subagent events, roles, runner, and runtime integration."""

import json
import threading

import pytest

from subagent_instructions import (
    IMPLEMENTER_INSTRUCTIONS,
    INVESTIGATOR_INSTRUCTIONS,
    VERIFIER_INSTRUCTIONS,
)

from events import (
    RuntimeEvent,
    SubagentCompleted,
    SubagentFailed,
    SubagentMessage,
    SubagentStarted,
)

from event_bus import EventBus
from dispatcher import ToolDispatcher
from tools.registry import TOOL_REGISTRY
import subagents


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


def test_role_instructions_are_substantive():
    for text in (INVESTIGATOR_INSTRUCTIONS, IMPLEMENTER_INSTRUCTIONS, VERIFIER_INSTRUCTIONS):
        assert len(text) > 200
        assert "Draft" in text


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

    @property
    def items(self):
        return self

    @property
    def responses(self):
        return self

    def create(self, **kwargs):
        if not kwargs:
            self._call_count += 1
            return _FakeConversation(f"conv-{self._call_count}")
        if "conversation_id" in kwargs:
            return None
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


def test_runner_timeout_clamps_negative(subagent_ctx):
    """Negative timeouts clamp to 1s instead of failing immediately."""
    client = _FakeOpenAI([_FakeResponse([], output_text="done")])
    subagent_ctx(client)
    result = subagents.run_subagent("verifier", "x", timeout=-1)
    assert result["success"] is True
    assert result["data"]["summary"] == "done"


def test_runner_timeout_expires_deadline(subagent_ctx, monkeypatch):
    """A run that exceeds its (clamped) budget still fails with a timeout."""
    client = _FakeOpenAI([_FakeResponse([], output_text="late")])
    subagent_ctx(client)
    real_monotonic = subagents.time.monotonic
    calls = {"base": None}

    def _fake_monotonic():
        if calls["base"] is None:
            calls["base"] = real_monotonic()
            return calls["base"]
        return calls["base"] + 5.0

    monkeypatch.setattr(subagents.time, "monotonic", _fake_monotonic)
    result = subagents.run_subagent("verifier", "x", timeout=1)
    assert result["success"] is False
    assert "timed out" in result["error"]


def test_runner_invalid_timeout_fails_cleanly(subagent_ctx):
    """Non-numeric timeouts fail cleanly instead of raising TypeError."""
    client = _FakeOpenAI([])
    _, event_bus = subagent_ctx(client)
    result = subagents.run_subagent("verifier", "x", timeout="30 seconds")
    assert result["success"] is False
    assert "Invalid timeout" in result["error"]
    emitted = [type(e).__name__ for e in event_bus.history]
    assert "SubagentStarted" in emitted
    assert "SubagentFailed" in emitted


def test_run_batch_preserves_call_order(subagent_ctx):
    slow = json.dumps({"expression": "1+1"})
    responses = {
        "conv-1": [_FakeResponse([_FakeItem("function_call", name="calculate", arguments=slow, call_id="c1")]), _FakeResponse([], output_text="first done")],
        "conv-2": [_FakeResponse([], output_text="second done")],
    }
    client = _FakeOpenAI([])

    class _PerCallClient(_FakeOpenAI):
        def __init__(self):
            super().__init__([])
            self._made = 0

        def create(self, **kwargs):
            if not kwargs:
                self._made += 1
                return _FakeConversation(f"conv-{self._made}")
            if "conversation_id" in kwargs:
                return None
            conv_id = kwargs.get("conversation", "")
            seq = responses[conv_id]
            return seq.pop(0)

    client = _PerCallClient()
    subagent_ctx(client)
    results = subagents.run_batch([("implementer", "task a", 300), ("verifier", "task b", 300)])
    assert len(results) == 2
    assert results[0]["data"]["summary"] == "first done"
    assert results[1]["data"]["summary"] == "second done"
