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
