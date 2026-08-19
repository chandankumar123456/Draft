"""Tests for new TUI features:
- Slash Commands (/new, /clear, /help, /status, /config, /endpoint, /model)
- Multiline Text Input (Shift+Enter vs Enter)
- First-time Configuration Modal
- Progressive Response Streaming (AgentMessageChunk)
- Visual Workspace Diff Rendering
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch
from textual.app import App, ComposeResult

from events import (
    AgentCompleted,
    AgentMessage,
    AgentMessageChunk,
    AgentStarted,
    AgentStatus,
    PatchApplied,
)
from tui.app import DraftApp
from tui.screens import ConfigModal
from tui.widgets import AgentWorkspace, DiffView, PromptInput
from tui.widgets.panels import PromptTextArea


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    import config as config_module
    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_LOADED", False)


class DummyApp(App):
    """Test app for testing PromptInput and multiline editor."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.submitted_messages = []

    def compose(self) -> ComposeResult:
        yield PromptInput(id="prompt-input")

    def on_prompt_input_submitted(self, message: PromptInput.Submitted) -> None:
        self.submitted_messages.append(message.value)


@pytest.mark.anyio
async def test_prompt_multiline_shift_enter():
    """Verify that Shift+Enter inserts a newline while Enter submits."""
    app = DummyApp()
    async with app.run_test() as pilot:
        prompt_input = app.query_one("#prompt-input", PromptInput)
        text_area = prompt_input.query_one("#prompt-input", PromptTextArea)
        text_area.focus()

        # Set text and cursor
        text_area.text = "Line 1"
        text_area.cursor_location = (0, 6)

        # Press Shift+Enter -> inserts newline
        await pilot.press("shift+enter")
        assert "\n" in text_area.text

        # Test Alt+Enter -> inserts newline
        text_area.text = "Line A"
        text_area.cursor_location = (0, 6)
        await pilot.press("alt+enter")
        assert "\n" in text_area.text

        # Test Backslash (\) line continuation
        text_area.text = "Line X\\"
        text_area.cursor_location = (0, 7)
        await pilot.press("enter")
        assert "\n" in text_area.text
        assert "Line X\n" in text_area.text

        # Test Ctrl+O multiline toggle
        await pilot.press("ctrl+o")
        assert prompt_input.is_multiline is True
        text_area.text = "Multiline Line 1"
        text_area.cursor_location = (0, 16)
        await pilot.press("enter")
        assert "\n" in text_area.text

        # In multiline mode, Ctrl+S submits
        await pilot.press("ctrl+s")
        assert len(app.submitted_messages) == 1
        assert "Multiline Line 1" in app.submitted_messages[0]

        # Reset multiline mode
        await pilot.press("ctrl+o")
        assert prompt_input.is_multiline is False

        text_area.text = "Line 1\nLine 2"

        # Press Enter in single line mode -> submits complete multiline text
        await pilot.press("enter")
        assert len(app.submitted_messages) == 2
        assert app.submitted_messages[1] == "Line 1\nLine 2"
        # Input cleared after submission
        assert text_area.text == ""


@pytest.mark.anyio
async def test_slash_command_catalog_and_backspace():
    """Verify typing '/', filtering, and backspacing dynamically restores catalog."""
    app = DummyApp()
    async with app.run_test() as pilot:
        prompt_input = app.query_one("#prompt-input", PromptInput)
        text_area = prompt_input.query_one("#prompt-input", PromptTextArea)
        text_area.focus()

        # 1. Type '/' -> shows full catalog (8 items)
        prompt_input.value = "/"
        await pilot.pause()
        assert prompt_input.is_catalog_visible is True
        assert len(prompt_input.current_suggestions) == 8

        # 2. Type 'new' -> narrows catalog to /new
        prompt_input.value = "/new"
        await pilot.pause()
        assert len(prompt_input.current_suggestions) == 1
        assert prompt_input.current_suggestions[0][0] == "/new"

        # 3. Backspace to '/' -> restores full 8 items
        prompt_input.value = "/"
        await pilot.pause()
        assert prompt_input.is_catalog_visible is True
        assert len(prompt_input.current_suggestions) == 8

        # 4. Filter with prefix '/co' -> matches /config
        prompt_input.value = "/co"
        await pilot.pause()
        assert len(prompt_input.current_suggestions) == 1
        assert prompt_input.current_suggestions[0][0] == "/config"

        # 5. Clear / non-slash text -> hides catalog
        prompt_input.value = "hello"
        await pilot.pause()
        assert prompt_input.is_catalog_visible is False


@pytest.mark.anyio
async def test_slash_command_keyboard_navigation_and_selection():
    """Verify up/down keyboard navigation and enter selection in catalog."""
    app = DummyApp()
    async with app.run_test() as pilot:
        prompt_input = app.query_one("#prompt-input", PromptInput)
        text_area = prompt_input.query_one("#prompt-input", PromptTextArea)
        text_area.focus()

        # Open catalog with '/'
        prompt_input.value = "/"
        await pilot.pause()
        assert prompt_input.is_catalog_visible is True

        catalog = prompt_input.query_one("#slash-catalog")
        assert catalog.selected_index == 0
        first_cmd = catalog.get_selected()[0]

        # Press down arrow -> moves to second command
        await pilot.press("down")
        assert catalog.selected_index == 1
        second_cmd = catalog.get_selected()[0]
        assert first_cmd != second_cmd

        # Press up arrow -> moves back to first command
        await pilot.press("up")
        assert catalog.selected_index == 0

        # Press Enter -> selects active command (/new) and submits
        await pilot.press("enter")
        assert prompt_input.is_catalog_visible is False
        assert len(app.submitted_messages) == 1
        assert app.submitted_messages[0] == first_cmd


@pytest.mark.anyio
async def test_slash_command_esc_closes_catalog():
    """Verify Esc dismisses the command catalog without clearing text."""
    app = DummyApp()
    async with app.run_test() as pilot:
        prompt_input = app.query_one("#prompt-input", PromptInput)
        text_area = prompt_input.query_one("#prompt-input", PromptTextArea)
        text_area.focus()

        prompt_input.value = "/"
        await pilot.pause()
        assert prompt_input.is_catalog_visible is True

        # Press Escape -> catalog closes
        await pilot.press("escape")
        assert prompt_input.is_catalog_visible is False


@pytest.mark.anyio
async def test_slash_commands_execution():
    """Test slash commands in DraftApp (/help, /clear, /status, /config, /new, /model, /endpoint)."""
    with patch.object(DraftApp, "_init_agent", return_value=None):
        app = DraftApp(model="gpt-4.1-mini")
        async with app.run_test() as pilot:
            workspace = app.query_one("#agent-workspace", AgentWorkspace)
            prompt_input = app.query_one("#prompt-input", PromptInput)

            # 1. /help command
            prompt_input.submit_text("/help")
            await pilot.pause()
            assert workspace.log.lines

            # 2. /status command
            prompt_input.submit_text("/status")
            await pilot.pause()

            # 3. /config command
            prompt_input.submit_text("/config")
            await pilot.pause()

            # 4. /model command with argument
            prompt_input.submit_text("/model gpt-4o")
            await pilot.pause()
            assert app._model == "gpt-4o"
            assert os.environ["MODEL_DEPLOYMENT"] == "gpt-4o"

            # 5. /model command with extra whitespace
            prompt_input.submit_text("/model    gpt-4.1-mini")
            await pilot.pause()
            assert app._model == "gpt-4.1-mini"
            assert os.environ["MODEL_DEPLOYMENT"] == "gpt-4.1-mini"

            # 6. /model without arguments (usage info)
            prompt_input.submit_text("/model")
            await pilot.pause()

            # 7. /endpoint command with argument
            prompt_input.submit_text("/endpoint https://custom.services.ai.azure.com")
            await pilot.pause()
            assert os.environ["PROJECT_ENDPOINT"] == "https://custom.services.ai.azure.com"

            # 8. /endpoint command with extra whitespace
            prompt_input.submit_text("/endpoint    https://example.com/api")
            await pilot.pause()
            assert os.environ["PROJECT_ENDPOINT"] == "https://example.com/api"

            # 9. /endpoint without arguments (usage info)
            prompt_input.submit_text("/endpoint")
            await pilot.pause()

            # 10. /new command
            prompt_input.submit_text("/new")
            await pilot.pause()

            # 11. /clear command
            prompt_input.submit_text("/clear")
            await pilot.pause()
            assert len(workspace.log.lines) == 0


@pytest.mark.anyio
async def test_slash_command_argument_enter_key_submission():
    """Verify typing /model gpt-4o and pressing Enter key executes the command end-to-end."""
    with patch.object(DraftApp, "_init_agent", return_value=None):
        app = DraftApp(model="gpt-4.1-mini")
        async with app.run_test() as pilot:
            prompt_input = app.query_one("#prompt-input", PromptInput)
            text_area = prompt_input.query_one("#prompt-input", PromptTextArea)
            text_area.focus()

            # Set text to argument-based command
            prompt_input.value = "/model gpt-4o"
            await pilot.pause()
            assert prompt_input.is_catalog_visible is False

            # Press Enter -> executes /model gpt-4o
            await pilot.press("enter")
            await pilot.pause()

            assert app._model == "gpt-4o"
            assert text_area.text == ""


@pytest.mark.anyio
async def test_config_modal():
    """Test ConfigModal form validation and dismiss."""
    modal = ConfigModal(endpoint="https://example.com/api", model="gpt-4o", can_cancel=True)

    class ModalTestApp(App):
        def on_mount(self) -> None:
            self.push_screen(modal)

    app = ModalTestApp()
    async with app.run_test() as pilot:
        endpoint_input = modal.query_one("#config-endpoint")
        model_input = modal.query_one("#config-model")
        assert endpoint_input.value == "https://example.com/api"
        assert model_input.value == "gpt-4o"

        await pilot.click("#config-btn-save")


@pytest.mark.anyio
async def test_response_streaming_progressive():
    """Verify progressive streaming of agent response chunks."""
    workspace = AgentWorkspace()

    class StreamApp(App):
        def compose(self) -> ComposeResult:
            yield workspace

    app = StreamApp()
    async with app.run_test() as pilot:
        # Start streaming chunks
        workspace.write_agent_chunk("Hello", accumulated="Hello")
        await pilot.pause()
        assert workspace._streaming_active
        assert workspace._streaming_text == "Hello"

        workspace.write_agent_chunk(" world!", accumulated="Hello world!")
        await pilot.pause()
        assert workspace._streaming_text == "Hello world!"

        # Finalize message
        workspace.write_agent_message("Hello world!")
        await pilot.pause()
        assert not workspace._streaming_active


@pytest.mark.anyio
async def test_visual_diff_rendering():
    """Test visual diff formatting with red/green highlights."""
    diff_view = DiffView()
    workspace = AgentWorkspace()
    diff_text = """--- a/test.py\n+++ b/test.py\n@@ -1,2 +1,2 @@\n-def old_func():\n+def new_func():\n     pass"""

    class DiffApp(App):
        def compose(self) -> ComposeResult:
            yield diff_view
            yield workspace

    app = DiffApp()
    async with app.run_test() as pilot:
        diff_view.add_diff("test.py", diff_text)
        await pilot.pause()
        assert diff_view.log.lines

        # Workspace patch applied
        event = PatchApplied(path="test.py", diff=diff_text)
        workspace.write_patch_applied(event)
        await pilot.pause()
        assert workspace.log.lines


@pytest.mark.anyio
async def test_tools_inspector_screen():
    """Test ToolInspectorScreen catalog, search filtering, and bottom buttons."""
    from tui.screens import ToolInspectorScreen
    from textual.widgets import OptionList, Input

    screen = ToolInspectorScreen()

    class ToolsTestApp(App):
        def on_mount(self) -> None:
            self.push_screen(screen)

    app = ToolsTestApp()
    async with app.run_test() as pilot:
        op_list = screen.query_one("#tools-option-list", OptionList)
        search_input = screen.query_one("#tools-search-input", Input)
        detail_log = screen.query_one("#tool-detail-log")

        # 1. Verify all tools are loaded
        assert op_list.option_count > 30

        # 2. Search / filter tools
        search_input.value = "git"
        await pilot.pause()
        assert op_list.option_count < 30
        assert op_list.option_count > 0

        # 3. Clear search via button
        await pilot.click("#btn-tools-clear")
        assert search_input.value == ""
        assert op_list.option_count > 30

        # 4. Focus search via button
        await pilot.click("#btn-tools-search")
        assert search_input.has_focus

        # 5. Focus detail via button
        await pilot.click("#btn-tools-detail")
        assert detail_log.has_focus

        # 6. Back button dismisses screen
        await pilot.click("#btn-tools-back")
        await pilot.pause()


@pytest.mark.anyio
async def test_workspace_full_width_rendering():
    """Verify long agent responses wrap and occupy full workspace width."""
    workspace = AgentWorkspace()

    class FullWidthApp(App):
        def compose(self) -> ComposeResult:
            yield workspace

    app = FullWidthApp()
    async with app.run_test(size=(120, 40)) as pilot:
        long_msg = "This is a comprehensive agent response that should span across the entire available horizontal space of the workspace log rather than being artificially restricted."
        workspace.write_agent_message(long_msg)
        await pilot.pause()

        assert len(workspace.log.lines) > 0
        # Check that rendered lines contain content and lines are long (wider than 30 chars)
        max_line_len = max(line.cell_length for line in workspace.log.lines)
        assert max_line_len > 30


@pytest.mark.anyio
async def test_diff_screen_interactive_buttons():
    """Test DiffScreen mounting, clear diffs, and bottom buttons."""
    from tui.screens import DiffScreen
    from tui.widgets import DiffView

    screen = DiffScreen()

    class DiffTestApp(App):
        def on_mount(self) -> None:
            self.push_screen(screen)

    app = DiffTestApp()
    async with app.run_test(size=(100, 30)) as pilot:
        diff_view = screen.query_one("#diff-screen-view", DiffView)
        diff_view.add_diff("app.py", "+new line\n-old line")
        await pilot.pause()
        assert len(diff_view.log.lines) > 0

        # Click Clear Diffs button
        await pilot.click("#btn-diff-clear")
        assert len(diff_view.log.lines) == 0

        # Click Focus button
        await pilot.click("#btn-diff-focus")
        assert diff_view.log.has_focus

        # Click Back button
        await pilot.click("#btn-diff-back")
        await pilot.pause()


@pytest.mark.anyio
async def test_git_screen_interactive_buttons():
    """Test GitScreen mounting, refresh, and bottom buttons."""
    from tui.screens import GitScreen
    from tui.widgets import GitPanel

    screen = GitScreen()

    class GitTestApp(App):
        def on_mount(self) -> None:
            self.push_screen(screen)

    app = GitTestApp()
    async with app.run_test(size=(100, 30)) as pilot:
        git_panel = screen.query_one("#git-screen-view", GitPanel)

        # Click Refresh button
        await pilot.click("#btn-git-refresh")
        assert len(git_panel.log.lines) > 0

        # Click Focus button
        await pilot.click("#btn-git-focus")
        assert git_panel.log.has_focus

        # Click Back button
        await pilot.click("#btn-git-back")
        await pilot.pause()


@pytest.mark.anyio
async def test_timeline_screen_interactive_buttons():
    """Test TimelineScreen mounting, clear logs, and bottom buttons."""
    from tui.screens import TimelineScreen
    from tui.widgets import TimelineView
    from events import SystemMessage

    screen = TimelineScreen()

    class TimelineTestApp(App):
        def on_mount(self) -> None:
            self.push_screen(screen)

    app = TimelineTestApp()
    async with app.run_test(size=(100, 30)) as pilot:
        timeline_view = screen.query_one("#timeline-screen-view", TimelineView)
        timeline_view.add_event(SystemMessage(content="Test event message", level="info"))
        await pilot.pause()
        assert len(timeline_view.log.lines) > 0

        # Click Clear button
        await pilot.click("#btn-timeline-clear")
        assert len(timeline_view.log.lines) == 0

        # Click Focus button
        await pilot.click("#btn-timeline-focus")
        assert timeline_view.log.has_focus

        # Click Back button
        await pilot.click("#btn-timeline-back")
        await pilot.pause()
