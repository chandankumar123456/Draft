"""Auxiliary panels: project explorer, timeline, diff, tests, git,
approval modal, prompt input, and footer bar."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DirectoryTree, Input, Static

# Add agent dir to path
_agent_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"
)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

from events import (
    AgentCompleted,
    AgentFailed,
    AgentMessage,
    AgentStarted,
    ApprovalRequested,
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

from tui.widgets.common import SelectableRichLog


# ════════════════════════════════════════════════════════════════
# PROJECT EXPLORER
# ════════════════════════════════════════════════════════════════

class ProjectExplorer(Widget):
    """Left panel: navigable project directory tree.

    Uses Textual's ``DirectoryTree`` with git status indicators.
    Emits ``FileSelected`` messages when files are clicked.
    """

    DEFAULT_CSS = """
    ProjectExplorer {
        width: 100%;
        height: 100%;
    }
    ProjectExplorer .project-header {
        height: 1;
        width: 100%;
    }
    ProjectExplorer .project-header #project-title {
        width: 1fr;
    }
    ProjectExplorer .project-header #project-toggle {
        width: 3;
        min-width: 3;
        height: 1;
        padding: 0;
        margin: 0;
        content-align: center middle;
        border: none;
        background: transparent;
        color: #8888cc;
    }
    ProjectExplorer .project-header #project-toggle:hover {
        color: #6688cc;
        background: #16213e;
        border: none;
    }
    """

    class FileSelected(Message):
        """A file was selected in the explorer."""
        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

    class ToggleRequested(Message):
        """The user requested to toggle the explorer's visibility."""

    def __init__(self, root: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root = root or self._detect_root()
        self._git_status: dict[str, str] = {}  # path → status (M, ?, A, D)

    def _detect_root(self) -> str:
        """Find the project root (git top-level or CWD)."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return os.getcwd()

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static(
                "[bold]PROJECT[/bold]",
                classes="panel-title",
                id="project-title",
            ),
            Button(
                "☰",
                id="project-toggle",
                classes="panel-toggle",
                variant="default",
            ),
            classes="project-header",
        )
        yield DirectoryTree(self._root, id="project-tree")

    def on_mount(self) -> None:
        tree = self.query_one("#project-tree", DirectoryTree)
        tree.show_root = True
        tree.guide_depth = 3
        self._refresh_git_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "project-toggle":
            self.post_message(ProjectExplorer.ToggleRequested())

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        self.post_message(ProjectExplorer.FileSelected(str(event.path)))

    def _refresh_git_status(self) -> None:
        """Load git status for modification indicators."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
                cwd=self._root,
            )
            if result.returncode == 0:
                self._git_status.clear()
                for line in result.stdout.strip().split("\n"):
                    if len(line) >= 4:
                        status = line[:2].strip()
                        filepath = line[3:]
                        self._git_status[filepath] = status
        except Exception:
            pass

    def refresh_tree(self) -> None:
        """Reload the directory tree and git status."""
        self._refresh_git_status()
        try:
            tree = self.query_one("#project-tree", DirectoryTree)
            tree.reload()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
# PROMPT INPUT
# ════════════════════════════════════════════════════════════════

class PromptInput(Widget):
    """Bottom prompt bar for user input.

    Emits ``PromptSubmitted`` when the user presses Enter.
    """

    DEFAULT_CSS = """
    PromptInput {
        height: 3;
        width: 100%;
    }
    """

    class Submitted(Message):
        """The user submitted a prompt."""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Type your prompt... (Enter to submit)",
            id="prompt-input",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if prompt:
            self.post_message(PromptInput.Submitted(prompt))
            event.input.value = ""

    def focus_input(self) -> None:
        """Focus the input field."""
        try:
            self.query_one("#prompt-input", Input).focus()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
# TIMELINE VIEW
# ════════════════════════════════════════════════════════════════

class TimelineView(Widget):
    """Chronological event timeline.

    Shows a compact log of all runtime events with timestamps.
    """

    DEFAULT_CSS = """
    TimelineView {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._start_time: datetime | None = None

    def compose(self) -> ComposeResult:
        yield Static("[bold]TIMELINE[/bold]", classes="panel-title")
        yield SelectableRichLog(
            id="timeline-log",
            highlight=True,
            markup=True,
            wrap=True,
            auto_scroll=True,
        )

    @property
    def log(self) -> SelectableRichLog:
        return self.query_one("#timeline-log", SelectableRichLog)

    def add_event(self, event: RuntimeEvent) -> None:
        """Add an event to the timeline."""
        if self._start_time is None:
            self._start_time = event.timestamp

        # Calculate relative time
        delta = (event.timestamp - self._start_time).total_seconds()
        minutes = int(delta // 60)
        seconds = int(delta % 60)
        time_str = f"{minutes:02d}:{seconds:02d}"

        # Format based on event type
        label, color = self._classify_event(event)

        self.log.write(
            f"[dim]{time_str}[/dim]  [{color}]{label}[/{color}]"
        )

    def _classify_event(
        self, event: RuntimeEvent
    ) -> tuple[str, str]:
        """Return (label, color) for an event."""
        if isinstance(event, UserMessage):
            return "USER     request received", "green"
        elif isinstance(event, AgentMessage):
            content = event.content[:50] + "..." if len(event.content) > 50 else event.content
            return f"AGENT    {content}", "cyan"
        elif isinstance(event, AgentStarted):
            return "AGENT    task started", "cyan"
        elif isinstance(event, AgentCompleted):
            return "DONE     task completed", "bold green"
        elif isinstance(event, AgentFailed):
            return f"FAILED   {event.error[:40]}", "bold red"
        elif isinstance(event, ToolStarted):
            return f"TOOL     → {event.tool_name}", "yellow"
        elif isinstance(event, ToolCompleted):
            return f"TOOL     ✓ {event.tool_name} ({event.duration_seconds:.3f}s)", "green"
        elif isinstance(event, ToolFailed):
            return f"TOOL     ✗ {event.tool_name}", "red"
        elif isinstance(event, PatchApplied):
            return f"PATCH    ✓ {event.path}", "green"
        elif isinstance(event, PatchFailed):
            return f"PATCH    ✗ {event.path}", "red"
        elif isinstance(event, TestCompleted):
            return f"TEST     {event.passed}✓ {event.failed}✗", "cyan"
        elif isinstance(event, GitStatusChanged):
            return f"GIT      {event.operation}", "magenta"
        elif isinstance(event, SystemMessage):
            return f"SYSTEM   {event.content[:40]}", "dim"
        else:
            return f"{type(event).__name__}", "dim"


# ════════════════════════════════════════════════════════════════
# DIFF VIEW
# ════════════════════════════════════════════════════════════════

class DiffView(Widget):
    """Unified diff display with syntax highlighting."""

    DEFAULT_CSS = """
    DiffView {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._diffs: list[tuple[str, str]] = []  # (path, diff_text)

    def compose(self) -> ComposeResult:
        yield Static("[bold]DIFF VIEW[/bold]", classes="panel-title")
        yield SelectableRichLog(
            id="diff-log",
            highlight=True,
            markup=True,
            wrap=True,
        )

    @property
    def log(self) -> SelectableRichLog:
        return self.query_one("#diff-log", SelectableRichLog)

    def add_diff(self, path: str, diff_text: str) -> None:
        """Add a diff to the view."""
        self._diffs.append((path, diff_text))
        self._render_diff(path, diff_text)

    def _render_diff(self, path: str, diff_text: str) -> None:
        """Render a single diff with colors."""
        self.log.write(
            f"\n[bold]{escape(path)}[/bold]\n"
            f"[dim]{'─' * 40}[/dim]"
        )
        for line in diff_text.split("\n"):
            if line.startswith("+++") or line.startswith("---"):
                self.log.write(f"[bold]{escape(line)}[/bold]")
            elif line.startswith("@@"):
                self.log.write(f"[cyan]{escape(line)}[/cyan]")
            elif line.startswith("+"):
                self.log.write(f"[green]{escape(line)}[/green]")
            elif line.startswith("-"):
                self.log.write(f"[red]{escape(line)}[/red]")
            else:
                self.log.write(f"[dim]{escape(line)}[/dim]")

    def clear_diffs(self) -> None:
        """Clear all diffs."""
        self._diffs.clear()
        self.log.clear()


# ════════════════════════════════════════════════════════════════
# TEST PANEL
# ════════════════════════════════════════════════════════════════

class TestPanel(Widget):
    """Test results dashboard."""

    DEFAULT_CSS = """
    TestPanel {
        width: 100%;
        height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]TESTS[/bold]", classes="panel-title")
        yield SelectableRichLog(
            id="test-log",
            highlight=True,
            markup=True,
            wrap=True,
        )

    @property
    def log(self) -> SelectableRichLog:
        return self.query_one("#test-log", SelectableRichLog)

    def show_results(self, event: TestCompleted) -> None:
        """Display test results."""
        self.log.clear()

        self.log.write(
            f"\n[bold]{escape(event.command)}[/bold]\n"
        )

        # Individual tests
        for tr in event.results:
            icon = {
                "passed": "[green]✓[/green]",
                "failed": "[red]✗[/red]",
                "skipped": "[yellow]⊘[/yellow]",
                "error": "[red]![/red]",
            }.get(tr.status, "[dim]?[/dim]")
            self.log.write(f"  {icon} {escape(tr.name)}")

        # Summary
        self.log.write(
            f"\n  [green]{event.passed} passed[/green]"
            f"  [red]{event.failed} failed[/red]"
            f"  [yellow]{event.skipped} skipped[/yellow]"
            f"\n  [dim]Duration: {event.duration_seconds:.2f}s[/dim]"
        )

    def show_failure(self, event: TestFailed) -> None:
        """Display a test runner failure."""
        self.log.clear()
        self.log.write(
            f"\n[bold red]TEST RUNNER FAILED[/bold red]\n"
            f"[red]{escape(event.error)}[/red]"
        )


# ════════════════════════════════════════════════════════════════
# GIT PANEL
# ════════════════════════════════════════════════════════════════

class GitPanel(Widget):
    """Git status, branches, and recent commits."""

    DEFAULT_CSS = """
    GitPanel {
        width: 100%;
        height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]GIT[/bold]", classes="panel-title")
        yield SelectableRichLog(
            id="git-log",
            highlight=True,
            markup=True,
            wrap=True,
        )

    @property
    def log(self) -> SelectableRichLog:
        return self.query_one("#git-log", SelectableRichLog)

    def refresh_git_info(self) -> None:
        """Fetch and display current git information."""
        import subprocess
        self.log.clear()

        try:
            # Branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=5,
            )
            branch = result.stdout.strip() if result.returncode == 0 else "unknown"
            self.log.write(
                f"\n  [bold]Branch[/bold]\n  [magenta]{escape(branch)}[/magenta]\n"
            )

            # Modified files
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                modified = []
                untracked = []
                for line in result.stdout.strip().split("\n"):
                    if line.startswith("??"):
                        untracked.append(line[3:])
                    elif line.strip():
                        modified.append(line)

                if modified:
                    self.log.write("  [bold]Modified[/bold]")
                    for f in modified[:20]:
                        status = f[:2].strip()
                        name = f[3:]
                        self.log.write(
                            f"  [yellow]{escape(name)}[/yellow]  "
                            f"[dim]{status}[/dim]"
                        )

                if untracked:
                    self.log.write("\n  [bold]Untracked[/bold]")
                    for f in untracked[:10]:
                        self.log.write(f"  [dim]{escape(f)}[/dim]  ?")
            else:
                self.log.write("  [dim]Working tree clean[/dim]")

            # Recent commits
            result = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                self.log.write("\n  [bold]Recent Commits[/bold]")
                for line in result.stdout.strip().split("\n"):
                    self.log.write(f"  [dim]{escape(line)}[/dim]")

        except Exception as exc:
            self.log.write(f"[red]Git error: {escape(str(exc))}[/red]")


# ════════════════════════════════════════════════════════════════
# APPROVAL MODAL
# ════════════════════════════════════════════════════════════════

class ApprovalModal(Widget):
    """Modal dialog for human-in-the-loop approval of risky actions."""

    DEFAULT_CSS = """
    ApprovalModal {
        width: 60;
        height: auto;
        max-height: 30;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    class Approved(Message):
        """The user approved the action."""
        def __init__(self, call_id: str) -> None:
            super().__init__()
            self.call_id = call_id

    class Denied(Message):
        """The user denied the action."""
        def __init__(self, call_id: str) -> None:
            super().__init__()
            self.call_id = call_id

    def __init__(self, event: ApprovalRequested, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._event = event

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold yellow]ACTION REQUIRES APPROVAL[/bold yellow]",
            classes="modal-title",
        )
        yield Static(
            f"\n[bold]Tool:[/bold] {escape(self._event.tool_name)}\n"
            f"[bold]Risk:[/bold] {self._event.risk_level.value}\n"
        )

        # Arguments
        args_text = json.dumps(self._event.arguments, indent=2, default=str)
        if len(args_text) > 500:
            args_text = args_text[:500] + "\n..."
        yield Static(
            f"[bold]Arguments:[/bold]\n[dim]{escape(args_text)}[/dim]\n"
        )

        yield Horizontal(
            Button("[A] Approve", id="approve-btn", variant="success"),
            Button("[D] Deny", id="deny-btn", variant="error"),
            classes="modal-buttons",
        )

    BINDINGS = [
        Binding("a", "approve", "Approve"),
        Binding("d", "deny", "Deny"),
        Binding("escape", "deny", "Deny"),
    ]

    def action_approve(self) -> None:
        self.post_message(ApprovalModal.Approved(self._event.call_id))
        self.remove()

    def action_deny(self) -> None:
        self.post_message(ApprovalModal.Denied(self._event.call_id))
        self.remove()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approve-btn":
            self.action_approve()
        elif event.button.id == "deny-btn":
            self.action_deny()


# ════════════════════════════════════════════════════════════════
# FOOTER BAR
# ════════════════════════════════════════════════════════════════

class FooterBar(Static):
    """Custom footer showing keyboard shortcuts."""

    def render(self) -> str:
        keys = [
            "[bold]F1[/bold] Help",
            "[bold]F2[/bold] Files",
            "[bold]F3[/bold] Agent",
            "[bold]F4[/bold] Tools",
            "[bold]F5[/bold] Diff",
            "[bold]F6[/bold] Git",
            "[bold]F7[/bold] Logs",
            "[bold]Ctrl+K[/bold] Cmd",
        ]
        return "  ".join(keys)