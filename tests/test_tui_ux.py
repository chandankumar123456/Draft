"""Tests for enhanced TUI user experience and interaction flow.

Verifies:
1. Header hamburger button toggling Project Explorer visibility.
2. Input field affordances, focus, and history navigation.
3. Thinking indicator start/stop animation behavior.
4. Double-Esc agent stop mechanism.
5. Interactive footer control bar actions and state responsiveness.
"""

from pathlib import Path
import pytest
import time
from textual.events import Key
from textual.widgets import Input, Button

from tui.app import DraftApp
from tui.widgets import (
    StatusHeader,
    ProjectExplorer,
    PromptInput,
    AgentWorkspace,
    ThinkingIndicator,
    FooterBar,
)

_TUI_STYLES = (
    Path(__file__).resolve().parent.parent / "tui" / "styles.tcss"
)


class _TestDraftApp(DraftApp):
    """DraftApp test variant without background agent runtime worker."""

    CSS_PATH = _TUI_STYLES

    def _init_agent(self) -> None:
        pass


@pytest.fixture
def app():
    return _TestDraftApp()


@pytest.mark.anyio
async def test_header_hamburger_toggles_project_explorer(app: DraftApp) -> None:
    """Clicking header hamburger button toggles ProjectExplorer visibility."""
    async with app.run_test(size=(100, 30)) as pilot:
        explorer = app.query_one("#project-explorer", ProjectExplorer)
        assert explorer.display is True

        header = app.query_one("#status-header", StatusHeader)
        header_btn = app.query_one("#header-hamburger", Button)
        header.on_button_pressed(Button.Pressed(header_btn))
        await pilot.pause()

        assert explorer.display is False

        header.on_button_pressed(Button.Pressed(header_btn))
        await pilot.pause()

        assert explorer.display is True


@pytest.mark.anyio
async def test_prompt_input_focus_and_placeholder(app: DraftApp) -> None:
    """PromptInput receives initial focus and has proper placeholder."""
    async with app.run_test(size=(100, 30)) as pilot:
        prompt_widget = app.query_one("#prompt-input", PromptInput)
        inp = prompt_widget.query_one("#prompt-input")
        assert "Message the agent..." in prompt_widget.placeholder
        assert inp.has_focus is True


@pytest.mark.anyio
async def test_prompt_history_navigation(app: DraftApp) -> None:
    """Up and Down arrow keys navigate prompt history."""
    async with app.run_test(size=(100, 30)) as pilot:
        prompt_widget = app.query_one("#prompt-input", PromptInput)

        prompt_widget.submit_text("first message")
        await pilot.pause()

        prompt_widget.submit_text("second message")
        await pilot.pause()

        assert prompt_widget.value == ""

        prompt_widget.navigate_history(-1)
        assert prompt_widget.value == "second message"

        prompt_widget.navigate_history(-1)
        assert prompt_widget.value == "first message"

        prompt_widget.navigate_history(1)
        assert prompt_widget.value == "second message"


@pytest.mark.anyio
async def test_thinking_indicator_lifecycle(app: DraftApp) -> None:
    """Thinking indicator displays during processing and hides when done."""
    async with app.run_test(size=(100, 30)) as pilot:
        workspace = app.query_one("#agent-workspace", AgentWorkspace)
        indicator = workspace.query_one("#thinking-indicator", ThinkingIndicator)

        assert indicator.display is False

        workspace.start_thinking("Processing request...")
        assert indicator.display is True

        workspace.stop_thinking()
        assert indicator.display is False


@pytest.mark.anyio
async def test_double_esc_stops_running_agent(app: DraftApp) -> None:
    """Pressing Esc twice within 1.5 seconds triggers agent stop."""
    async with app.run_test(size=(100, 30)) as pilot:
        class DummyRuntime:
            is_running = True
            def cancel(self):
                self.is_running = False

        app._runtime = DummyRuntime()
        header = app.query_one("#status-header", StatusHeader)
        footer = app.query_one("#footer-bar", FooterBar)

        app._set_app_status("RUNNING")
        assert header.status == "RUNNING"
        assert footer.agent_status == "RUNNING"

        # First Esc press
        await pilot.press("escape")
        await pilot.pause()
        assert app._last_esc_time > 0

        # Second Esc press immediately
        await pilot.press("escape")
        await pilot.pause()

        assert header.status == "CANCELLED"
        assert footer.agent_status == "CANCELLED"
        assert app._runtime.is_running is False


@pytest.mark.anyio
async def test_footer_bar_button_clicks(app: DraftApp) -> None:
    """Clicking buttons on the FooterBar triggers appropriate actions."""
    async with app.run_test(size=(100, 30)) as pilot:
        explorer = app.query_one("#project-explorer", ProjectExplorer)
        assert explorer.display is True

        footer = app.query_one("#footer-bar", FooterBar)
        btn_files = app.query_one("#btn-files", Button)
        footer.on_button_pressed(Button.Pressed(btn_files))
        await pilot.pause()

        assert explorer.display is False
