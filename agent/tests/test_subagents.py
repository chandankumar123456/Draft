"""Tests for subagent events, roles, runner, and runtime integration."""

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
