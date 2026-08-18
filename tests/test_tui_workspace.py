"""Tests for the agent workspace: tool cards, smart auto-scroll, and
selection stability in the Draft TUI.

These tests exercise the workspace log (``SelectableRichLog``) as the
agent runtime drives it:

* tool lifecycle events render RUNNING / COMPLETED / FAILED /
  CANCELLED markers,
* writes only follow the newest content when the user is at the
  bottom of the log (smart auto-scroll),
* text selection still extracts the exact text after the user has
  scrolled up to read older output,
* the state panel reflects the agent/tool lifecycle.
"""

import pytest
from pathlib import Path
from textual.geometry import Offset
from textual.selection import Selection
from textual.widgets import Static

from tui.app import DraftApp
from tui.widgets import AgentStatePanel, AgentWorkspace, SelectableRichLog

# tui.app adds the agent dir to sys.path, so the events module is
# importable after the tui imports above.
from events import (
    AgentStarted,
    RiskLevel,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
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
    """Pump frames until deferred layout/scroll callbacks have run.

    ``RichLog.write`` schedules its auto-scroll after the next
    refresh, so a single ``pilot.pause()`` is not enough for the
    scroll position to settle. A fixed number of pauses drains those
    callbacks without any wall-clock sleeping.
    """
    for _ in range(4):
        await pilot.pause()


def _read_log_text(log: SelectableRichLog) -> str:
    """Join the log's rendered strips into plain text."""
    return "\n".join(strip.text for strip in log.lines)


def _state_content(panel: AgentStatePanel) -> str:
    """Plain text of the rendered #state-content Static."""
    static = panel.query_one("#state-content", Static)
    content = static.content
    return content.plain if hasattr(content, "plain") else str(content)


def _workspace(app: DraftApp) -> AgentWorkspace:
    return app.query_one("#agent-workspace", AgentWorkspace)


# ════════════════════════════════════════════════════════════════
# Smart auto-scroll (SelectableRichLog)
# ════════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_write_follows_to_bottom_when_at_end(app: DraftApp) -> None:
    """While the user is at the bottom, writes follow the new content."""
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#workspace-log", SelectableRichLog)
        log.write("\n".join(f"line {i}" for i in range(30)))
        await _settle(pilot)
        assert log.max_scroll_y > 0

        log.scroll_to(y=log.max_scroll_y, animate=False, immediate=True)
        await _settle(pilot)
        assert log.scroll_offset.y == log.max_scroll_y

        log.write("newest line")
        await _settle(pilot)

        assert log.scroll_offset.y == log.max_scroll_y


@pytest.mark.anyio
async def test_scrolled_away_write_preserves_scroll_position(
    app: DraftApp,
) -> None:
    """A write must not move the scroll position when the user has
    scrolled away from the bottom (smart auto-scroll)."""
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#workspace-log", SelectableRichLog)
        log.write("\n".join(f"line {i}" for i in range(30)))
        await _settle(pilot)
        assert log.max_scroll_y > 0

        # User scrolls up to read older output.
        log.scroll_to(y=0, animate=False, immediate=True)
        await _settle(pilot)
        assert log.scroll_offset.y == 0

        log.write("newest line")
        await _settle(pilot)

        assert log.scroll_offset.y == 0


@pytest.mark.anyio
async def test_set_follow_toggle_controls_auto_scroll(
    app: DraftApp,
) -> None:
    """set_follow(False) holds the position; set_follow(True) resumes
    following the newest content."""
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#workspace-log", SelectableRichLog)
        log.write("\n".join(f"line {i}" for i in range(30)))
        await _settle(pilot)

        log.scroll_to(y=0, animate=False, immediate=True)
        await _settle(pilot)
        assert log.scroll_offset.y == 0

        log.set_follow(False)
        log.write("held line")
        await _settle(pilot)
        assert log.scroll_offset.y == 0

        log.set_follow(True)
        log.write("follow line")
        await _settle(pilot)
        assert log.scroll_offset.y == log.max_scroll_y


# ════════════════════════════════════════════════════════════════
# Tool cards (AgentWorkspace)
# ════════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_tool_started_renders_running_marker(
    app: DraftApp,
) -> None:
    """A started tool call renders a RUNNING marker with its name and
    arguments."""
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_tool_started(ToolStarted(
            tool_name="read_file",
            call_id="abc123",
            arguments={"path": "src/main.py", "start_line": 1},
            risk_level=RiskLevel.READ_ONLY,
        ))
        await _settle(pilot)

        text = _read_log_text(ws.log)
        assert "RUNNING" in text
        assert "read_file" in text
        assert "src/main.py" in text


@pytest.mark.anyio
async def test_tool_completed_renders_completed_and_duration(
    app: DraftApp,
) -> None:
    """A completed tool call renders a COMPLETED marker and the
    duration."""
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_tool_completed(ToolCompleted(
            tool_name="read_file",
            call_id="abc123",
            result={"success": True, "data": {"content": "..."}},
            duration_seconds=0.123,
        ))
        await _settle(pilot)

        text = _read_log_text(ws.log)
        assert "COMPLETED" in text
        assert "0.123" in text


@pytest.mark.anyio
async def test_tool_failed_renders_failed_marker(app: DraftApp) -> None:
    """A failed tool call renders a FAILED marker and the error."""
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_tool_failed(ToolFailed(
            tool_name="grep",
            call_id="def456",
            error="no matches found",
            duration_seconds=0.05,
        ))
        await _settle(pilot)

        text = _read_log_text(ws.log)
        assert "FAILED" in text
        assert "no matches found" in text


@pytest.mark.anyio
async def test_mark_tool_cancelled_renders_cancelled(
    app: DraftApp,
) -> None:
    """mark_tool_cancelled renders a CANCELLED marker for the call."""
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_tool_started(ToolStarted(
            tool_name="write_file",
            call_id="abc123",
            arguments={"path": "out.txt"},
            risk_level=RiskLevel.SAFE,
        ))
        await _settle(pilot)

        ws.mark_tool_cancelled("abc123")
        await _settle(pilot)

        text = _read_log_text(ws.log)
        assert "CANCELLED" in text


@pytest.mark.anyio
async def test_mark_tool_cancelled_only_matches_call_id(
    app: DraftApp,
) -> None:
    """mark_tool_cancelled only marks the card for the matching call."""
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_tool_started(ToolStarted(
            tool_name="read_file",
            call_id="abc123",
            arguments={"path": "src/main.py"},
            risk_level=RiskLevel.READ_ONLY,
        ))
        await _settle(pilot)

        ws.mark_tool_cancelled("does-not-exist")
        await _settle(pilot)
        text = _read_log_text(ws.log)
        assert "CANCELLED" not in text
        assert "RUNNING" in text

        ws.mark_tool_cancelled("abc123")
        await _settle(pilot)
        text = _read_log_text(ws.log)
        assert "CANCELLED" in text


# ════════════════════════════════════════════════════════════════
# State panel (AgentStatePanel)
# ════════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_state_panel_agent_started_shows_running(
    app: DraftApp,
) -> None:
    """AgentStarted flips the panel status to RUNNING."""
    async with app.run_test(size=(80, 24)) as pilot:
        panel = app.query_one("#agent-state", AgentStatePanel)
        panel.update_from_event(AgentStarted(task="Fix the login bug"))
        await pilot.pause()

        content = _state_content(panel)
        assert "STATUS" in content
        assert "RUNNING" in content
        assert "Fix the login bug" in content
        assert panel.status == "RUNNING"


@pytest.mark.anyio
async def test_state_panel_tool_sequence_updates_status_and_counts(
    app: DraftApp,
) -> None:
    """ToolStarted / ToolCompleted update the current tool, status, and
    call/read counters in the rendered panel."""
    async with app.run_test(size=(80, 24)) as pilot:
        panel = app.query_one("#agent-state", AgentStatePanel)
        panel.update_from_event(AgentStarted(task="Fix the login bug"))
        panel.update_from_event(ToolStarted(
            tool_name="read_file",
            call_id="abc123",
            arguments={"path": "src/main.py"},
            risk_level=RiskLevel.READ_ONLY,
        ))
        await pilot.pause()

        content = _state_content(panel)
        assert "RUNNING" in content
        assert "TOOL" in content
        assert "read_file" in content
        assert "CALLS" in content
        assert panel.tool_calls == 1

        panel.update_from_event(ToolCompleted(
            tool_name="read_file",
            call_id="abc123",
            result={"success": True, "data": {}},
            duration_seconds=0.123,
        ))
        await pilot.pause()

        content = _state_content(panel)
        assert "CALLS" in content
        assert panel.current_tool_status == "COMPLETED"
        assert panel.files_read == 1


# ════════════════════════════════════════════════════════════════
# Selection regression
# ════════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_selection_extracts_text_after_scrolling_up(
    app: DraftApp,
) -> None:
    """A drag selection still extracts the exact text after the user
    scrolled up to read older output."""
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_user_message("first user note")
        ws.write_agent_message("agent reply one")
        ws.write_agent_message("agent reply two")
        await _settle(pilot)

        log = ws.log
        log.scroll_to(y=0, animate=False, immediate=True)
        await _settle(pilot)

        text = _read_log_text(log)
        lines = text.split("\n")
        line = next(l for l in lines if "agent reply one" in l)
        idx = lines.index(line)
        start = line.index("agent reply one")
        end = start + len("agent reply one")

        app.screen.selections = {
            log: Selection.from_offsets(
                Offset(start, idx), Offset(end, idx)
            )
        }
        await pilot.pause()

        assert app.screen.get_selected_text() == "agent reply one"


@pytest.mark.anyio
async def test_write_after_scroll_up_keeps_position_and_selection(
    app: DraftApp,
) -> None:
    """Writing new blocks after the user scrolled up keeps the scroll
    position, and selection still extracts the exact text."""
    async with app.run_test(size=(80, 24)) as pilot:
        ws = _workspace(app)
        ws.write_user_message("first user note")
        ws.write_agent_message("agent reply one")
        await _settle(pilot)

        log = ws.log
        log.scroll_to(y=0, animate=False, immediate=True)
        await _settle(pilot)
        assert log.scroll_offset.y == 0
        pos = log.scroll_offset.y

        ws.write_agent_message("agent reply two")
        await _settle(pilot)
        assert log.scroll_offset.y == pos

        text = _read_log_text(log)
        lines = text.split("\n")
        line = next(l for l in lines if "agent reply one" in l)
        idx = lines.index(line)
        start = line.index("agent reply one")
        end = start + len("agent reply one")

        app.screen.selections = {
            log: Selection.from_offsets(
                Offset(start, idx), Offset(end, idx)
            )
        }
        await pilot.pause()

        assert app.screen.get_selected_text() == "agent reply one"