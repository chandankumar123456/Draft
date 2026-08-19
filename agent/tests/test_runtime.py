"""Tests for AgentRuntime sub-agent integration."""

import json

from event_bus import EventBus
from events import ToolCompleted, ToolStarted
import runtime as runtime_module
import subagents


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


class _FakeRuntimeOpenAI:
    """Scripted OpenAI client for AgentRuntime (single dispatching create)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._conversation_count = 0
        self.sent_inputs: list[list[dict]] = []

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
            self._conversation_count += 1
            return _FakeConversation(f"rt-conv-{self._conversation_count}")
        if "conversation_id" in kwargs:
            return None
        if "input" in kwargs:
            self.sent_inputs.append(kwargs.get("input"))
        assert self._responses, "unexpected responses.create call"
        return self._responses.pop(0)


def test_execute_loop_groups_spawn_subagent_calls(monkeypatch):
    fake_pc = _FakeProjectClient()
    fake_oa = _FakeRuntimeOpenAI([
        _FakeResponse([
            _FakeItem("function_call", name="spawn_subagent",
                      arguments=json.dumps({
                          "role": "investigator",
                          "task": "inspect repo",
                          "timeout": 60,
                      }),
                      call_id="fc1"),
            _FakeItem("function_call", name="spawn_subagent",
                      arguments=json.dumps({
                          "role": "implementer",
                          "task": "add flag",
                      }),
                      call_id="fc2"),
            _FakeItem("function_call", name="spawn_subagent",
                      arguments="not json", call_id="fc3"),
            _FakeItem("function_call", name="calculate",
                      arguments=json.dumps({"expression": "1+1"}),
                      call_id="fc4"),
        ]),
        _FakeResponse([], output_text="all done"),
    ])
    monkeypatch.setattr(runtime_module, "get_project_client", lambda ep: fake_pc)
    monkeypatch.setattr(runtime_module, "get_openai_client", lambda ep: fake_oa)

    batch_calls: list[tuple[str, str, int]] = []
    batch_results = [
        {"success": True, "data": {
            "role": "investigator", "summary": "investigator done",
            "iterations": 1, "tool_calls": 0, "duration_seconds": 0.1,
        }, "message": "ok", "error": None},
        {"success": True, "data": {
            "role": "implementer", "summary": "implementer done",
            "iterations": 1, "tool_calls": 0, "duration_seconds": 0.1,
        }, "message": "ok", "error": None},
    ]

    def fake_run_batch(calls):
        batch_calls.extend(calls)
        return batch_results

    monkeypatch.setattr(subagents, "run_batch", fake_run_batch)

    event_bus = EventBus()
    rt = runtime_module.AgentRuntime(event_bus=event_bus)
    rt.initialize()

    for name in ("Draft-Investigator", "Draft-Implementer", "Draft-Verifier"):
        assert name in fake_pc.created
    assert subagents.is_configured() is True

    rt._execute_loop("delegate work")

    assert batch_calls == [
        ("investigator", "inspect repo", 60),
        ("implementer", "add flag", 300),
    ]

    fed_back = fake_oa.sent_inputs[-1]
    assert [item["call_id"] for item in fed_back] == ["fc1", "fc2", "fc3", "fc4"]
    assert "investigator done" in fed_back[0]["output"]
    assert "implementer done" in fed_back[1]["output"]
    assert "Invalid JSON" in fed_back[2]["output"]
    assert '"result": 2' in fed_back[3]["output"]

    tool_events = [
        e for e in event_bus.history
        if isinstance(e, (ToolStarted, ToolCompleted))
    ]
    assert len(tool_events) == 2
    assert all(e.call_id == "fc4" for e in tool_events)

    rt.cleanup()
    for name in ("Draft-Investigator", "Draft-Implementer", "Draft-Verifier"):
        assert (name, "v1") in fake_pc.deleted


def test_execute_loop_skips_spawn_with_unparsable_timeout(monkeypatch):
    fake_pc = _FakeProjectClient()
    fake_oa = _FakeRuntimeOpenAI([
        _FakeResponse([
            _FakeItem("function_call", name="spawn_subagent",
                      arguments=json.dumps({
                          "role": "investigator",
                          "task": "inspect repo",
                          "timeout": 60,
                      }),
                      call_id="fc1"),
            _FakeItem("function_call", name="spawn_subagent",
                      arguments=json.dumps({
                          "role": "implementer",
                          "task": "add flag",
                          "timeout": "30 seconds",
                      }),
                      call_id="fc2"),
            _FakeItem("function_call", name="spawn_subagent",
                      arguments=json.dumps({
                          "role": "verifier",
                          "task": "run checks",
                      }),
                      call_id="fc3"),
        ]),
        _FakeResponse([], output_text="all done"),
    ])
    monkeypatch.setattr(runtime_module, "get_project_client", lambda ep: fake_pc)
    monkeypatch.setattr(runtime_module, "get_openai_client", lambda ep: fake_oa)

    batch_calls: list[tuple[str, str, int]] = []
    batch_results = [
        {"success": True, "data": {
            "role": "investigator", "summary": "investigator done",
            "iterations": 1, "tool_calls": 0, "duration_seconds": 0.1,
        }, "message": "ok", "error": None},
        {"success": True, "data": {
            "role": "verifier", "summary": "verifier done",
            "iterations": 1, "tool_calls": 0, "duration_seconds": 0.1,
        }, "message": "ok", "error": None},
    ]

    def fake_run_batch(calls):
        batch_calls.extend(calls)
        return batch_results

    monkeypatch.setattr(subagents, "run_batch", fake_run_batch)

    event_bus = EventBus()
    rt = runtime_module.AgentRuntime(event_bus=event_bus)
    rt.initialize()
    rt._execute_loop("delegate work")

    assert batch_calls == [
        ("investigator", "inspect repo", 60),
        ("verifier", "run checks", 300),
    ]

    fed_back = fake_oa.sent_inputs[-1]
    assert [item["call_id"] for item in fed_back] == ["fc1", "fc2", "fc3"]
    assert "investigator done" in fed_back[0]["output"]
    assert '"success": false' in fed_back[1]["output"]
    assert "verifier done" in fed_back[2]["output"]
