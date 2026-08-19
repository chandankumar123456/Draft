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
from textual.events import TextSelected
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
    AgentMessageChunk,
    AgentPhaseChanged,
    AgentStarted,
    ApprovalRequested,
    FileChanged,
    GitStatusChanged,
    PatchApplied,
    PatchFailed,
    RuntimeEvent,
    SubagentCompleted,
    SubagentFailed,
    SubagentMessage,
    SubagentStarted,
    SystemMessage,
    TestCompleted,
    TestFailed,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
    UserMessage,
)
from runtime import AgentRuntime

from config import clear_config, load_config, save_config

from tui.messages import RuntimeEventReceived
from tui.screens import (
    ConfigModal,
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
        Binding("ctrl+shift+c", "copy_text", "Copy"),
        Binding("ctrl+c", "quit_app", "Quit"),
    ]

    def __init__(self, model: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._event_bus = EventBus()
        self._runtime: AgentRuntime | None = None
        self._event_queue: asyncio.Queue | None = None
        self._event_consumer_worker: Worker | None = None
        self._project_visible = True

        # Detect project info
        self._model = model or os.getenv("MODEL_DEPLOYMENT", "gpt-4.1-mini")
        self._branch = self._detect_branch()
        self._project_name = self._detect_project_name()
        self._last_esc_time: float = 0.0
        self._current_status: str = "IDLE"

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

        # Focus input field
        try:
            self.query_one("#prompt-input", PromptInput).focus_input()
        except Exception:
            pass

        # Check required configuration
        cfg = load_config()
        if not cfg.endpoint:
            self.action_show_config(mandatory=True)
        else:
            self._init_agent()

    def _init_agent(self) -> None:
        """Initialize the agent runtime in a background worker."""
        self.run_worker(self._init_agent_worker, thread=True, exclusive=True)

    async def _init_agent_worker(self) -> None:
        """Worker: create EventBus queue and initialize AgentRuntime."""
        # Bind event bus to the app's event loop
        loop = asyncio.get_event_loop()
        self._event_bus.bind_loop(loop)

        # Tear down the previous consumer and queue before re-subscribing,
        # otherwise every re-init leaves the old queue subscribed and the
        # old consumer running (events render once per consumer).
        if self._event_consumer_worker is not None:
            self._event_consumer_worker.cancel()
            self._event_consumer_worker = None
        if self._event_queue is not None:
            self._event_bus.remove_queue(self._event_queue)
            self._event_queue = None

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
        self._event_consumer_worker = self.run_worker(
            self._consume_events, exclusive=False
        )

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

    # ── Key & Control Bar Events ────────────────────────────────

    def on_key(self, event) -> None:
        """Handle global key events (e.g. double-Esc stop)."""
        if event.key == "escape":
            if len(self.screen_stack) > 1:
                return

            if self._runtime and self._runtime.is_running:
                import time
                now = time.time()
                if now - self._last_esc_time <= 1.5:
                    self._last_esc_time = 0.0
                    self.action_stop_agent()
                else:
                    self._last_esc_time = now
                    workspace = self.query_one("#agent-workspace", AgentWorkspace)
                    workspace.write_system_message(
                        "Press Esc again to STOP running agent.",
                        level="warning",
                    )
        elif event.key == "up":
            try:
                prompt_input = self.query_one("#prompt-input", PromptInput)
                inp = prompt_input.query_one("#prompt-input")
                if inp.has_focus:
                    prompt_input.navigate_history(-1)
            except Exception:
                pass
        elif event.key == "down":
            try:
                prompt_input = self.query_one("#prompt-input", PromptInput)
                inp = prompt_input.query_one("#prompt-input")
                if inp.has_focus:
                    prompt_input.navigate_history(1)
            except Exception:
                pass

    def on_footer_bar_action_requested(
        self, message: FooterBar.ActionRequested
    ) -> None:
        """Handle button clicks from the interactive footer control bar."""
        action = message.action_name
        if action == "send":
            try:
                prompt_input = self.query_one("#prompt-input", PromptInput)
                prompt_input.submit_current()
            except Exception:
                pass
        elif action == "stop":
            self.action_stop_agent()
        elif action == "history":
            try:
                prompt_input = self.query_one("#prompt-input", PromptInput)
                prompt_input.focus_input()
                prompt_input.navigate_history(-1)
            except Exception:
                pass
        elif action == "files":
            self.action_toggle_project()
        elif action == "tools":
            self.action_open_tools()
        elif action == "diff":
            self.action_open_diff()
        elif action == "git":
            self.action_open_git()
        elif action == "logs":
            self.action_open_timeline()
        elif action == "cmd":
            self.action_command_palette()
        elif action == "exit":
            self.action_quit_app()

    # ── Event Handling ────────────────────────────────────────

    def _set_app_status(self, status: str) -> None:
        """Helper to update header and footer agent status simultaneously."""
        try:
            header = self.query_one("#status-header", StatusHeader)
            header.status = status
        except Exception:
            pass
        try:
            footer = self.query_one("#footer-bar", FooterBar)
            footer.agent_status = status
        except Exception:
            pass

    def on_runtime_event_received(
        self, message: RuntimeEventReceived
    ) -> None:
        """Handle all runtime events and route to widgets."""
        event = message.event

        # Route to workspace
        workspace = self.query_one("#agent-workspace", AgentWorkspace)
        state_panel = self.query_one("#agent-state", AgentStatePanel)

        # Timeline always gets everything
        try:
            timeline = self.query_one("#timeline-view", TimelineView)
            timeline.add_event(event)
        except Exception:
            pass

        # Route by event type
        if isinstance(event, UserMessage):
            workspace.write_user_message(event.content)

        elif isinstance(event, AgentMessageChunk):
            workspace.write_agent_chunk(event.delta, event.accumulated)

        elif isinstance(event, AgentMessage):
            workspace.write_agent_message(event.content)

        elif isinstance(event, AgentStarted):
            self._set_app_status("RUNNING")
            workspace.start_thinking("Agent is thinking...")
            state_panel.update_from_event(event)

        elif isinstance(event, AgentCompleted):
            self._set_app_status("COMPLETED")
            workspace.stop_thinking()
            state_panel.update_from_event(event)
            try:
                self.query_one("#prompt-input", PromptInput).focus_input()
            except Exception:
                pass

        elif isinstance(event, AgentFailed):
            self._set_app_status("FAILED")
            workspace.stop_thinking()
            state_panel.update_from_event(event)
            workspace.write_system_message(
                f"Agent failed: {event.error}", level="error"
            )
            try:
                self.query_one("#prompt-input", PromptInput).focus_input()
            except Exception:
                pass

        elif isinstance(event, AgentCancelled):
            self._set_app_status("CANCELLED")
            workspace.stop_thinking()
            workspace.write_system_message("Agent cancelled.", level="warning")
            try:
                self.query_one("#prompt-input", PromptInput).focus_input()
            except Exception:
                pass

        elif isinstance(event, AgentPhaseChanged):
            state_panel.update_from_event(event)

        elif isinstance(event, SubagentStarted):
            workspace.write_subagent_started(event)

        elif isinstance(event, SubagentMessage):
            workspace.write_subagent_message(event)

        elif isinstance(event, SubagentFailed):
            workspace.write_subagent_failed(event)

        elif isinstance(event, SubagentCompleted):
            workspace.write_system_message(
                f"Subagent '{event.role}' completed: {event.iterations} "
                f"iterations, {event.tool_calls} tool calls.",
                level="info",
            )

        elif isinstance(event, ToolStarted):
            self._set_app_status("WAITING")
            workspace.start_thinking(f"Executing tool {event.tool_name}...")
            workspace.write_tool_started(event)
            state_panel.update_from_event(event)
            try:
                inspector = self.query_one("#tool-inspector", ToolInspector)
                inspector.inspect_tool(event)
            except Exception:
                pass

        elif isinstance(event, ToolCompleted):
            self._set_app_status("RUNNING")
            workspace.start_thinking("Agent processing tool result...")
            workspace.write_tool_completed(event)
            state_panel.update_from_event(event)
            try:
                inspector = self.query_one("#tool-inspector", ToolInspector)
                inspector.inspect_tool(event)
            except Exception:
                pass

        elif isinstance(event, ToolFailed):
            self._set_app_status("RUNNING")
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
            try:
                header = self.query_one("#status-header", StatusHeader)
                header.branch = self._branch
            except Exception:
                pass
            try:
                git_panel = self.query_one("#git-panel", GitPanel)
                git_panel.refresh_git_info()
            except Exception:
                pass

        elif isinstance(event, SystemMessage):
            workspace.write_system_message(event.content, event.level)

        elif isinstance(event, ApprovalRequested):
            self._show_approval(event)

    # ── Prompt & Slash Command Handling ────────────────────────

    def on_prompt_input_submitted(
        self, message: PromptInput.Submitted
    ) -> None:
        """Handle prompt or slash command submission."""
        prompt = message.value.strip()

        if not prompt:
            return

        if prompt.startswith("/"):
            self._handle_slash_command(prompt)
            return

        if self._runtime is None:
            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            workspace.write_system_message(
                "Agent not yet initialized. Please configure endpoint/model or wait...",
                level="warning",
            )
            return

        if self._runtime.is_running:
            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            workspace.write_system_message(
                "Agent is busy. Press Esc Esc or click Stop to cancel.",
                level="warning",
            )
            return

        # Launch agent task in a background thread
        workspace = self.query_one("#agent-workspace", AgentWorkspace)
        self._set_app_status("RUNNING")
        workspace.start_thinking("Agent is starting...")

        self.run_worker(
            lambda: self._runtime.run_task(prompt),
            thread=True,
            exclusive=True,
            group="agent-task",
        )

    def _handle_slash_command(self, cmd_line: str) -> None:
        """Execute interactive slash commands with argument parsing."""
        raw = cmd_line.strip()
        parts = raw.split(maxsplit=1)
        if not parts:
            return

        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        workspace = self.query_one("#agent-workspace", AgentWorkspace)

        if cmd == "/new":
            if self._runtime is not None:
                self._runtime.new_conversation()
            else:
                workspace.write_system_message(
                    "Started a new conversation context.", level="info"
                )

        elif cmd == "/clear":
            workspace.log.clear()

        elif cmd == "/help":
            workspace.write_slash_help()

        elif cmd == "/status":
            iter_count = self._runtime.state.iteration if self._runtime else 0
            tc_count = self._runtime.state.tool_call_count if self._runtime else 0
            fm_count = self._runtime.state.files_modified if self._runtime else 0
            workspace.write_status_summary(
                status=self._current_status,
                model=self._model,
                branch=self._branch,
                project=self._project_name,
                iterations=iter_count,
                tool_calls=tc_count,
                files_modified=fm_count,
            )

        elif cmd == "/config":
            if arg:
                workspace.write_system_message(
                    "Use /endpoint <url> or /model <name> to change settings.",
                    level="info",
                )
            else:
                workspace.write_config_summary(
                    endpoint=os.getenv("PROJECT_ENDPOINT", ""),
                    model=self._model,
                )

        elif cmd == "/endpoint":
            if arg:
                self._update_endpoint(arg)
            else:
                current_ep = os.getenv("PROJECT_ENDPOINT", "not set")
                workspace.write_system_message(
                    f"Usage: /endpoint <project_endpoint> (Current: {current_ep})",
                    level="info",
                )

        elif cmd == "/model":
            if arg:
                self._update_model(arg)
            else:
                workspace.write_system_message(
                    f"Usage: /model <model_deployment> (Current: {self._model})",
                    level="info",
                )

        elif cmd == "/config-reset":
            workspace.write_system_message(
                "Configuration cleared. Re-enter your endpoint and model.",
                level="warning",
            )
            if self._runtime is not None:
                self._runtime.cleanup()
                self._runtime = None
            clear_config()
            self.action_show_config(mandatory=True)

        elif cmd in ("/exit", "/quit"):
            self.action_quit_app()

        else:
            workspace.write_system_message(
                f"Unknown slash command '{cmd}'. Type /help for available commands.",
                level="warning",
            )

    def _update_endpoint(self, new_endpoint: str) -> None:
        """Update endpoint at runtime and reinitialize."""
        workspace = self.query_one("#agent-workspace", AgentWorkspace)
        clean_endpoint = new_endpoint.strip()
        if not clean_endpoint:
            workspace.write_system_message(
                "Error: Project endpoint cannot be empty. Usage: /endpoint <project_endpoint>",
                level="error",
            )
            return

        os.environ["PROJECT_ENDPOINT"] = clean_endpoint
        save_config(endpoint=clean_endpoint)
        if self._runtime is not None:
            self._runtime.reconfigure(endpoint=clean_endpoint)
        else:
            self._init_agent()
        workspace.write_system_message(
            f"✓ Project endpoint updated: {clean_endpoint}", level="info"
        )

    def _update_model(self, new_model: str) -> None:
        """Update model deployment at runtime and reinitialize."""
        workspace = self.query_one("#agent-workspace", AgentWorkspace)
        clean_model = new_model.strip()
        if not clean_model:
            workspace.write_system_message(
                "Error: Model name cannot be empty. Usage: /model <model_deployment>",
                level="error",
            )
            return

        self._model = clean_model
        try:
            header = self.query_one("#status-header", StatusHeader)
            header.model = clean_model
        except Exception:
            pass
        os.environ["MODEL_DEPLOYMENT"] = clean_model
        save_config(model=clean_model)
        if self._runtime is not None:
            self._runtime.reconfigure(model=clean_model)
        else:
            self._init_agent()
        workspace.write_system_message(
            f"✓ Model deployment changed to: {clean_model}", level="info"
        )

    def action_show_config(self, mandatory: bool = False) -> None:
        """Display configuration dialog modal."""
        modal = ConfigModal(
            endpoint=os.getenv("PROJECT_ENDPOINT", ""),
            model=self._model,
            can_cancel=not mandatory,
        )
        self.push_screen(modal, callback=self._on_config_modal_closed)

    def _on_config_modal_closed(self, result: tuple[str, str] | None) -> None:
        """Handle configuration modal result."""
        if result is not None:
            endpoint, model = result
            self._model = model
            try:
                header = self.query_one("#status-header", StatusHeader)
                header.model = model
            except Exception:
                pass
            os.environ["PROJECT_ENDPOINT"] = endpoint
            os.environ["MODEL_DEPLOYMENT"] = model
            save_config(endpoint=endpoint, model=model)

            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            if self._runtime is not None:
                self._runtime.reconfigure(model=model, endpoint=endpoint)
            else:
                self._init_agent()
            workspace.write_system_message(
                f"Configuration saved! Endpoint: {endpoint} | Model: {model}",
                level="info",
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
        self._mark_tool_cancelled(message.call_id)

    def _mark_tool_cancelled(self, call_id: str) -> None:
        """Mark the denied tool as CANCELLED in the UI widgets."""
        try:
            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            workspace.mark_tool_cancelled(call_id)
        except Exception:
            pass
        try:
            inspector = self.query_one("#tool-inspector", ToolInspector)
            inspector.mark_cancelled(call_id)
        except Exception:
            pass
        try:
            state_panel = self.query_one("#agent-state", AgentStatePanel)
            state_panel.mark_tool_cancelled()
        except Exception:
            pass

    # ── Text Selection & Copy ──────────────────────────────

    def on_text_selected(self, event: TextSelected) -> None:
        """Copy text to the clipboard when a drag selection ends."""
        selection = self.screen.get_selected_text()
        if selection:
            self.copy_to_clipboard(selection)

    def action_copy_text(self) -> None:
        """Copy the current text selection to the clipboard."""
        selection = self.screen.get_selected_text()
        if selection:
            self.copy_to_clipboard(selection)

    # ── Actions ───────────────────────────────────────────────

    def on_project_explorer_toggle_requested(
        self, message: ProjectExplorer.ToggleRequested
    ) -> None:
        """Toggle the project explorer when the hamburger is pressed."""
        self.action_toggle_project()

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
        self._set_app_status("CANCELLED")
        try:
            workspace = self.query_one("#agent-workspace", AgentWorkspace)
            workspace.stop_thinking()
            workspace.write_system_message(
                "Agent task stopped by user.", level="warning"
            )
        except Exception:
            pass

        if self._runtime is not None and self._runtime.is_running:
            self._runtime.cancel()

        try:
            self.query_one("#prompt-input", PromptInput).focus_input()
        except Exception:
            pass

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
