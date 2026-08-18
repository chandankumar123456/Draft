"""Textual Screen subclasses for modal/full-screen views.

Each screen can be pushed/popped with F-key bindings from the
main app.  They wrap the corresponding widgets and add screen-level
key bindings.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

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
