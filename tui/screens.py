"""Textual Screen subclasses for modal/full-screen views.

Each screen can be pushed/popped with F-key bindings from the
main app.  They wrap the corresponding widgets and add screen-level
key bindings.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static

from tui.widgets import (
    DiffView,
    GitPanel,
    TestPanel,
    TimelineView,
    ToolInspector,
)


class DiffScreen(Screen):
    """Full-screen diff viewer."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back"),
        Binding("q", "pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DiffView(id="diff-screen-view")
        yield Footer()


class ToolInspectorScreen(Screen):
    """Full-screen tool inspector."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back"),
        Binding("q", "pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield ToolInspector(id="tool-inspector-screen-view")
        yield Footer()


class TimelineScreen(Screen):
    """Full-screen timeline/log view."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back"),
        Binding("q", "pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield TimelineView(id="timeline-screen-view")
        yield Footer()


class TestDashboardScreen(Screen):
    """Full-screen test results dashboard."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back"),
        Binding("q", "pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield TestPanel(id="test-screen-view")
        yield Footer()


class GitScreen(Screen):
    """Full-screen git panel."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back"),
        Binding("q", "pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield GitPanel(id="git-screen-view")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#git-screen-view", GitPanel).refresh_git_info()


class ConfigModal(Screen):
    """First-time setup and runtime configuration modal."""

    DEFAULT_CSS = """
    ConfigModal {
        align: center middle;
        background: rgba(10, 10, 20, 0.85);
    }
    ConfigModal #config-dialog {
        width: 70;
        height: auto;
        border: thick #6688cc;
        background: #16162a;
        padding: 1 2;
    }
    ConfigModal .dialog-title {
        text-align: center;
        margin-bottom: 1;
    }
    ConfigModal .dialog-desc {
        color: #8888aa;
        margin-bottom: 1;
    }
    ConfigModal .field-label {
        color: #ccccff;
        margin-top: 1;
    }
    ConfigModal Input {
        border: tall #444466;
        background: #1a1a2e;
        color: #e0e0e0;
        margin-bottom: 1;
    }
    ConfigModal Input:focus {
        border: tall #6688cc;
    }
    ConfigModal #config-error {
        color: #ff5555;
        height: 1;
        margin-bottom: 1;
    }
    ConfigModal #config-buttons {
        height: 3;
        align: right middle;
    }
    ConfigModal #config-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        endpoint: str = "",
        model: str = "",
        can_cancel: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._initial_endpoint = endpoint
        self._initial_model = model or "gpt-4.1-mini"
        self._can_cancel = can_cancel

    def compose(self) -> ComposeResult:
        with Vertical(id="config-dialog"):
            yield Static(
                "[bold cyan]⚙ DRAFT CONFIGURATION[/bold cyan]",
                classes="dialog-title",
            )
            yield Static(
                "Configure your Azure AI Project Endpoint and Model Deployment.",
                classes="dialog-desc",
            )
            yield Static("Azure AI Project Endpoint:", classes="field-label")
            yield Input(
                value=self._initial_endpoint,
                placeholder="https://<resource>.services.ai.azure.com/api/projects/<Project>",
                id="config-endpoint",
            )
            yield Static("Model Deployment Name:", classes="field-label")
            yield Input(
                value=self._initial_model,
                placeholder="gpt-4.1-mini",
                id="config-model",
            )
            yield Static("", id="config-error")
            with Horizontal(id="config-buttons"):
                if self._can_cancel:
                    yield Button("Cancel", id="config-btn-cancel")
                yield Button(
                    "Save & Connect",
                    variant="success",
                    id="config-btn-save",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "config-btn-save":
            endpoint = self.query_one("#config-endpoint", Input).value.strip()
            model = self.query_one("#config-model", Input).value.strip()

            if not endpoint or not model:
                self.query_one("#config-error", Static).update(
                    "Error: Both Project Endpoint and Model Deployment are required."
                )
                return

            self.dismiss((endpoint, model))
        elif event.button.id == "config-btn-cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        if self._can_cancel:
            self.dismiss(None)
        else:
            self.query_one("#config-error", Static).update(
                "Configuration is required before starting Draft."
            )
