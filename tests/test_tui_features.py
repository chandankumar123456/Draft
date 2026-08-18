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

        text_area.text = "Line 1\nLine 2"

        # Press Enter without Shift -> submits complete multiline text
        await pilot.press("enter")
        assert len(app.submitted_messages) == 1
        assert app.submitted_messages[0] == "Line 1\nLine 2"
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
    """Test slash commands in DraftApp (/help, /clear, /status, /config, /new)."""
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

            # 4. /new command
            prompt_input.submit_text("/new")
            await pilot.pause()

            # 5. /clear command
            prompt_input.submit_text("/clear")
            await pilot.pause()
            assert len(workspace.log.lines) == 0


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
