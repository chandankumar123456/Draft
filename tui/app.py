"""Draft Developer Cockpit — Textual TUI Application.

This is the main application class that orchestrates the 3-column
layout, keyboard bindings, worker-based event consumption, and the
connection between the Textual UI and the AgentRuntime.

Architecture::

    Textual App (main thread / async)
        ├── StatusHeader
        ├── Horizontal
        │   ├── ProjectExplorer (left)
        │   ├── Vertical (center)
        │   │   ├── AgentWorkspace
        │   │   └── PromptInput
        │   ├── AgentStatePanel (right)
        │   └── ToolInspector / Timeline / etc. (toggled)
        └── FooterBar

    Worker thread:
        AgentRuntime.run_task()
            → emits events via EventBus
                → EventBus.Queue
                    → event_consumer worker (reads queue, posts Messages)
                        → Textual message handlers update widgets
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Provider, Hits
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header
from textual.worker import Worker, get_current_worker

# Add agent directory to path
_agent_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"
)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

from event_bus import EventBus
from events import (
    AgentCancelled,
    AgentCompleted,
    AgentFailed,
    AgentMessage,
    AgentPhaseChanged,
    AgentStarted,
    ApprovalRequested,
    FileChanged,
    GitStatusChanged,
    PatchApplied,
    PatchFailed,
    RuntimeEvent,
    SystemMessage,
    TestCompleted,
    TestFailed,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
    UserMessage,
)
from runtime import AgentRuntime

from tui.messages import RuntimeEventReceived
from tui.screens import (
    DiffScreen,
    GitScreen,
    TestDashboardScreen,
    TimelineScreen,
    ToolInspectorScreen,
)
from tui.widgets import (
    AgentStatePanel,
    AgentWorkspace,
    ApprovalModal,
    DiffView,
    FooterBar,
    GitPanel,
    ProjectExplorer,
    PromptInput,
    StatusHeader,
    TestPanel,
    TimelineView,
    ToolInspector,
)


# ────────────────────────────────────────────────────────────────
# Command Palette Provider
# ────────────────────────────────────────────────────────────────

class DraftCommands(Provider):
    """Command palette provider for the Draft TUI."""

    async def search(self, query: str) -> Hits:
        app: DraftApp = self.app  # type: ignore

        commands = [
            ("Toggle Project Explorer", "Toggle the left file panel",
             app.action_toggle_project),
            ("Focus Agent Workspace", "Focus the main agent area",
             app.action_focus_workspace),
            ("Open Tool Inspector", "Full-screen tool inspector",
             app.action_open_tools),
            ("Open Diff View", "Full-screen diff viewer",
             app.action_open_diff),
            ("Open Git Panel", "Full-screen git status",
             app.action_open_git),
            ("Open Timeline", "Full-screen event timeline",
             app.action_open_timeline),
            ("Clear Workspace", "Clear the agent workspace log",
             app.action_clear_workspace),
            ("Stop Agent", "Cancel the current agent task",
             app.action_stop_agent),
            ("Refresh Project", "Reload the project explorer",
             app.action_refresh_project),
        ]

        for name, help_text, callback in commands:
            if query.lower() in name.lower():
                yield Hit(
                    score=1,
                    match_display=name,
                    command=callback,
                    help=help_text,
                )


# ────────────────────────────────────────────────────────────────
# Main Application
# ────────────────────────────────────────────────────────────────

class DraftApp(App):
    """Draft Developer Cockpit."""

    TITLE = "Draft"
    SUB_TITLE = "Developer Cockpit"
    CSS_PATH = "styles.tcss"
    COMMANDS = {DraftCommands}

    BINDINGS = [
        Binding("ctrl+k", "command_palette", "Command Palette"),
        Binding("f2", "toggle_project", "Files"),
        Binding("f3", "focus_workspace", "Agent"),
        Binding("f4", "open_tools", "Tools"),
        Binding("f5", "open_diff", "Diff"),
        Binding("f6", "open_git", "Git"),
        Binding("f7", "open_timeline", "Logs"),
        Binding("ctrl+c", "quit_app", "Quit"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._event_bus = EventBus()
        self._runtime: AgentRuntime | None = None
        self._event_queue: asyncio.Queue | None = None
        self._project_visible = True

        # Detect project info
        self._model = os.getenv("MODEL_DEPLOYMENT", "gpt-4.1-mini")
        self._branch = self._detect_branch()
        self._project_name = self._detect_project_name()

    def _detect_branch(self) -> str:
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def _detect_project_name(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return os.path.basename(result.stdout.strip())
        except Exception:
            pass
        return os.path.basename(os.getcwd())

    # ── Layout ────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield StatusHeader(id="status-header")

        yield Horizontal(
            ProjectExplorer(id="project-explorer"),
            Vertical(
                AgentWorkspace(id="agent-workspace"),
                PromptInput(id="prompt-input"),
                id="center-panel",
            ),
            Vertical(
                AgentStatePanel(id="agent-state"),
                ToolInspector(id="tool-inspector"),
                id="right-panel",
            ),
            id="main-area",
        )

        # Hidden panels (toggled)
        yield TimelineView(id="timeline-view")
        yield DiffView(id="diff-view")
        yield TestPanel(id="test-panel")
        yield GitPanel(id="git-panel")

        yield FooterBar(id="footer-bar")

    # ── Startup ───────────────────────────────────────────────

    def on_mount(self) -> None:
        """Initialize the app after mount."""
        # Set header info
        header = self.query_one("#status-header", StatusHeader)
        header.project_name = self._project_name
        header.branch = self._branch
        header.model = self._model

        # Hide secondary panels
        for panel_id in (
            "#timeline-view", "#diff-view", "#test-panel", "#git-panel"
        ):
            try:
                self.query_one(panel_id).display = False
            except Exception:
                pass

        # Welcome message
        workspace = self.query_one("#agent-workspace", AgentWorkspace)
        workspace.write_system_message(
            "Draft Developer Cockpit ready. Type a prompt below.",
            level="info",
        )

        # Initialize agent in background
        self._init_agent()

    def _init_agent(self) -> None:
        """Initialize the agent runtime in a background worker."""
        self.run_worker(self._init_agent_worker, thread=True, exclusive=True)

    async def _init_agent_worker(self) -> None:
        """Worker: create EventBus queue and initialize AgentRuntime."""
        # Bind event bus to the app's event loop
        loop = asyncio.get_event_loop()
        self._event_bus.bind_loop(loop)

        # Create queue for event consumption
        self._event_queue = self._event_bus.create_queue()

        # Create and initialize runtime
        self._runtime = AgentRuntime(
            event_bus=self._event_bus,
            model=self._model,
        )

        try:
            self._runtime.initialize()
        except Exception as exc:
            self.call_from_thread(
                self._post_system_message,
                f"Failed to initialize agent: {exc}",
                "error",
            )
            return

        # Start the event consumer
        self.call_from_thread(self._start_event_consumer)

    def _start_event_consumer(self) -> None:
        """Start the async event consumer worker."""
        self.run_worker(self._consume_events, exclusive=False)

    async def _consume_events(self) -> None:
        """Async worker: read events from the queue and post messages."""
        if self._event_queue is None:
            return

        worker = get_current_worker()

        while not worker.is_cancelled:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(), timeout=0.5
                )
                self.post_message(RuntimeEventReceived(event))
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue

    # ── Event Handling ────────────────────────────────────────

    def on_runtime_event_received(
        self, message: RuntimeEventReceived
    ) -> None:
        """Handle all runtime events and route to widgets."""
        event = message.event

        # Route to workspace
        workspace = self.query_one("#agent-workspace", AgentWorkspace)
        state_panel = self.query_one("#agent-state", AgentStatePanel)
        header = self.query_one("#status-header", StatusHeader)

        # Timeline always gets everything
        try:
            timeline = self.query_one("#timeline-view", TimelineView)
            timeline.add_event(event)
        except Exception:
            pass

        # Route by event type
        if isinstance(event, UserMessage):
            workspace.write_user_message(event.content)

        elif isinstance(event, AgentMessage):
            workspace.write_agent_message(event.content)

        elif isinstance(event, AgentStarted):
            header.status = "RUNNING"
            state_panel.update_from_event(event)

        elif isinstance(event, AgentCompleted):
            header.status = "COMPLETED"
            state_panel.update_from_event(event)

        elif isinstance(event, AgentFailed):
            header.status = "FAILED"
            state_panel.update_from_event(event)
            workspace.write_system_message(
                f"Agent failed: {event.error}", level="error"
            )

        elif isinstance(event, AgentCancelled):
            header.status = "CANCELLED"
            workspace.write_system_message("Agent cancelled.", level="warning")

        elif isinstance(event, AgentPhaseChanged):
            state_panel.update_from_event(event)

        elif isinstance(event, ToolStarted):
            workspace.write_tool_started(event)
            state_panel.update_from_event(event)
            # Update tool inspector
            try:
                inspector = self.query_one("#tool-inspector", ToolInspector)
                inspector.inspect_tool(event)
            except Exception:
                pass

        elif isinstance(event, ToolCompleted):
            workspace.write_tool_completed(event)
            state_panel.update_from_event(event)
            try:
                inspector = self.query_one("#tool-inspector", ToolInspector)
                inspector.inspect_tool(event)
            except Exception:
                pass

        elif isinstance(event, ToolFailed):
            workspace.write_tool_failed(event)
            state_panel.update_from_event(event)

        elif isinstance(event, PatchApplied):
            workspace.write_patch_applied(event)
            try:
                diff_view = self.query_one("#diff-view", DiffView)
                diff_view.add_diff(event.path, event.diff)
            except Exception:
                pass

        elif isinstance(event, TestCompleted):
            workspace.write_test_completed(event)
            state_panel.update_from_event(event)
            try:
                test_panel = self.query_one("#test-panel", TestPanel)
                test_panel.show_results(event)
            except Exception:
                pass

        elif isinstance(event, TestFailed):
            try:
                test_panel = self.query_one("#test-panel", TestPanel)
                test_panel.show_failure(event)
            except Exception:
                pass

        elif isinstance(event, FileChanged):
            try:
                explorer = self.query_one(
                    "#project-explorer", ProjectExplorer
                )
                explorer.refresh_tree()
            except Exception:
                pass

        elif isinstance(event, GitStatusChanged):
            self._branch = self._detect_branch()
            header.branch = self._branch
            try:
                git_panel = self.query_one("#git-panel", GitPanel)
                git_panel.refresh_git_info()
            except Exception:
                pass

        elif isinstance(event, SystemMessage):
            workspace.write_system_message(event.content, event.level)

        elif isinstance(event, ApprovalRequested):
            self._show_approval(event)

    # ── Prompt Handling ───────────────────────────────────────

    def on_prompt_input_submitted(
        self, message: PromptInput.Submitted
    ) -> None:
        """Handle prompt submission."""
        prompt = message.value

        if not prompt:
            return

        if self._runtime is None:
            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            workspace.write_system_message(
                "Agent not yet initialized. Please wait...",
                level="warning",
            )
            return

        if self._runtime.is_running:
            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            workspace.write_system_message(
                "Agent is busy. Wait for it to finish or press Ctrl+C.",
                level="warning",
            )
            return

        # Launch agent task in a background thread
        self.run_worker(
            lambda: self._runtime.run_task(prompt),
            thread=True,
            exclusive=True,
            group="agent-task",
        )

    # ── Approval ──────────────────────────────────────────────

    def _show_approval(self, event: ApprovalRequested) -> None:
        """Show the approval modal."""
        modal = ApprovalModal(event, id="approval-modal")
        self.mount(modal)

    def on_approval_modal_approved(
        self, message: ApprovalModal.Approved
    ) -> None:
        """Handle approval."""
        if self._runtime is not None:
            from events import ApprovalDecision
            self._runtime.dispatcher.resolve_approval(
                message.call_id, ApprovalDecision.APPROVED
            )

    def on_approval_modal_denied(
        self, message: ApprovalModal.Denied
    ) -> None:
        """Handle denial."""
        if self._runtime is not None:
            from events import ApprovalDecision
            self._runtime.dispatcher.resolve_approval(
                message.call_id, ApprovalDecision.DENIED
            )

    # ── Actions ───────────────────────────────────────────────

    def action_toggle_project(self) -> None:
        """Toggle the project explorer panel."""
        try:
            explorer = self.query_one("#project-explorer", ProjectExplorer)
            explorer.display = not explorer.display
            self._project_visible = explorer.display
        except Exception:
            pass

    def action_focus_workspace(self) -> None:
        """Focus the agent workspace."""
        try:
            self.query_one("#prompt-input", PromptInput).focus_input()
        except Exception:
            pass

    def action_open_tools(self) -> None:
        """Push the tool inspector screen."""
        self.push_screen(ToolInspectorScreen())

    def action_open_diff(self) -> None:
        """Push the diff view screen."""
        screen = DiffScreen()
        self.push_screen(screen)
        # Copy accumulated diffs
        try:
            src = self.query_one("#diff-view", DiffView)
            for path, diff_text in src._diffs:
                screen.query_one("#diff-screen-view", DiffView).add_diff(
                    path, diff_text
                )
        except Exception:
            pass

    def action_open_git(self) -> None:
        """Push the git screen."""
        self.push_screen(GitScreen())

    def action_open_timeline(self) -> None:
        """Push the timeline screen."""
        screen = TimelineScreen()
        self.push_screen(screen)
        # Copy event history
        try:
            timeline = screen.query_one(
                "#timeline-screen-view", TimelineView
            )
            for event in self._event_bus.history:
                timeline.add_event(event)
        except Exception:
            pass

    def action_clear_workspace(self) -> None:
        """Clear the workspace log."""
        try:
            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            workspace.log.clear()
        except Exception:
            pass

    def action_stop_agent(self) -> None:
        """Cancel the current agent task."""
        if self._runtime is not None:
            self._runtime.cancel()
            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            workspace.write_system_message(
                "Cancellation requested.", level="warning"
            )

    def action_refresh_project(self) -> None:
        """Refresh the project explorer."""
        try:
            explorer = self.query_one(
                "#project-explorer", ProjectExplorer
            )
            explorer.refresh_tree()
        except Exception:
            pass

    def action_quit_app(self) -> None:
        """Clean up and quit."""
        if self._runtime is not None:
            try:
                self._runtime.cleanup()
            except Exception:
                pass
        self.exit()

    def _post_system_message(
        self, content: str, level: str = "info"
    ) -> None:
        """Post a system message to the workspace (thread-safe)."""
        try:
            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            workspace.write_system_message(content, level)
        except Exception:
            pass


# ── Entry Point ───────────────────────────────────────────────

def main() -> None:
    """Launch the Draft Developer Cockpit."""
    # Ensure we're in the project root or agent dir
    app = DraftApp()
    app.run()


if __name__ == "__main__":
    main()