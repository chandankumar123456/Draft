"""Tests for TUI config persistence (.draft/config.json)."""

import json
from pathlib import Path

import pytest
from textual.worker import get_current_worker

from tui.app import DraftApp
from tui.screens import ConfigModal

# tui.app adds the agent dir to sys.path, so the events module is
# importable after the tui imports above.
from events import SubagentStarted

_TUI_STYLES = (
    Path(__file__).resolve().parent.parent / "tui" / "styles.tcss"
)


class _TestDraftApp(DraftApp):
    """DraftApp without agent runtime initialization."""

    CSS_PATH = _TUI_STYLES

    def _init_agent(self) -> None:
        pass


class _FakeRuntime:
    """Stand-in AgentRuntime that skips all Azure calls."""

    def __init__(self, event_bus=None, model=None, **kwargs) -> None:
        self.event_bus = event_bus
        self.model = model

    def initialize(self) -> None:
        pass

    def cleanup(self) -> None:
        pass


class _ReinitDraftApp(DraftApp):
    """DraftApp that performs real (re)initialization against _FakeRuntime."""

    CSS_PATH = _TUI_STYLES

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.consumer_workers: list = []

    def _init_agent(self) -> None:
        self._init_worker = self.run_worker(
            self._init_agent_worker, thread=True, exclusive=True
        )

    async def _consume_events(self) -> None:
        self.consumer_workers.append(get_current_worker())
        await super()._consume_events()


async def _settle(pilot) -> None:
    for _ in range(4):
        await pilot.pause()


async def _wait_for_consumers(app, pilot, count: int) -> None:
    """Wait until at least `count` consumer workers have started."""
    for _ in range(100):
        if len(app.consumer_workers) >= count:
            await _settle(pilot)
            return
        await pilot.pause()
    raise AssertionError("event consumer worker never started")


def _workspace(app: DraftApp):
    return app.query_one("#agent-workspace")


@pytest.mark.anyio
async def test_update_endpoint_persists_to_config(tmp_path, monkeypatch) -> None:
    """/endpoint must persist even when the runtime is not yet created."""
    import config as config_module
    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_LOADED", False)

    app = _TestDraftApp()
    async with app.run_test(size=(80, 24)):
        app._update_endpoint("https://persisted.azure.com")

    from config import config_path
    data = json.loads(config_path().read_text(encoding="utf-8"))
    assert data["endpoint"] == "https://persisted.azure.com"


@pytest.mark.anyio
async def test_config_reset_clears_saved_config(tmp_path, monkeypatch) -> None:
    """/config-reset deletes the saved config file and reopens the modal."""
    import config as config_module
    from config import config_path, save_config

    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_LOADED", False)
    save_config(endpoint="https://persisted.azure.com")
    assert config_path().exists()

    app = _TestDraftApp()
    async with app.run_test(size=(80, 24)):
        app._handle_slash_command("/config-reset")
        assert isinstance(app.screen, ConfigModal)

    assert not config_path().exists()
    assert "PROJECT_ENDPOINT" not in config_module.os.environ


@pytest.mark.anyio
async def test_reinit_does_not_duplicate_event_rendering(
    tmp_path, monkeypatch
) -> None:
    """Re-initializing after /config-reset must not leave the old consumer.

    Regression: the previous consumer worker and queue stayed subscribed,
    so one emitted event rendered once per consumer (and queue growth was
    unbounded across repeated resets).
    """
    import config as config_module
    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_LOADED", False)
    monkeypatch.setattr("tui.app.AgentRuntime", _FakeRuntime)

    app = _ReinitDraftApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app._handle_slash_command("/config-reset")
        app._init_agent()
        await _wait_for_consumers(app, pilot, count=1)
        baseline = len(app.consumer_workers)

        app._init_agent()
        await _wait_for_consumers(app, pilot, count=baseline + 1)

        app._event_bus.emit_threadsafe(SubagentStarted(
            role="investigator",
            task="duplicate-render-check",
            agent_name="Draft-Investigator",
        ))
        await _settle(pilot)
        await _settle(pilot)

        ws = _workspace(app)
        text = "\n".join(strip.text for strip in ws.log.lines)
        assert text.count("duplicate-render-check") == 1
        # No queue subscription may be left behind by previous initializations.
        assert len(app._event_bus._queues) == 1
