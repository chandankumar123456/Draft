"""Custom Textual widgets for the Draft Developer Cockpit.

Each major UI area is a separate Widget subclass with its own
``compose()`` method, custom messages, and reactive state.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.selection import Selection
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import (
    Button,
    DirectoryTree,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
    Tree,
)

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
    AgentPhase,
    AgentStarted,
    AgentStatus,
    ApprovalRequested,
    FileChanged,
    FileRead,
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


# ════════════════════════════════════════════════════════════════
# SELECTABLE RICH LOG
# ════════════════════════════════════════════════════════════════

class SelectableRichLog(RichLog):
    """A RichLog that supports drag-to-select text.

    Textual's ``RichLog`` does not implement the widget selection
    protocol (``get_selection`` / ``selection_updated``), so dragging
    the mouse over log content produces no selection and nothing can
    be copied. This subclass adds:

    * ``get_selection`` — extract the selected text from the log lines
      so ``Screen.get_selected_text()`` works.
    * ``selection_updated`` — repaint when the selection changes.
    * Content offset metadata and selection styling in ``_render_line``
      so precise ranges are highlighted while dragging.

    The app copies the selection to the clipboard on mouse release via
    its ``on_text_selected`` handler.
    """

    ALLOW_SELECT = True

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Get the text under the given selection.

        Args:
            selection: Selection information.

        Returns:
            Tuple of extracted text and line ending, or ``None`` if no
            text could be extracted.
        """
        text = "\n".join(strip.text.rstrip() for strip in self.lines)
        return selection.extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        """Repaint the log when the selection changes."""
        self._line_cache.clear()
        self.refresh()

    def render_line(self, y: int) -> Strip:
        """Render a line of content.

        Args:
            y: Y coordinate of the line.

        Returns:
            A rendered line with the selection highlight applied.
        """
        scroll_x, scroll_y = self.scroll_offset
        return self._render_line(
            scroll_y + y,
            scroll_x,
            self.scrollable_content_region.width,
        )

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        """Render a line with selection highlighting and offset metadata.

        Args:
            y: Y offset of the line (content coordinates).
            scroll_x: Current horizontal scroll.
            width: Width of the widget.

        Returns:
            A Strip suitable for rendering.
        """
        if y >= len(self.lines):
            return Strip.blank(width, self.rich_style)

        key = (y + self._start_line, scroll_x, width, self._widest_line_width)
        selection = self.text_selection
        if selection is None and key in self._line_cache:
            return self._line_cache[key]

        line = self.lines[y].crop_extend(
            scroll_x, scroll_x + width, self.rich_style
        )
        line = line.apply_style(self.rich_style)

        if selection is not None:
            span = selection.get_span(y)
            if span is not None:
                span_start, span_end = span
                if span_end == -1:
                    span_end = scroll_x + width
                start = max(span_start - scroll_x, 0)
                end = min(span_end - scroll_x, width)
                if end > start:
                    selection_style = self.screen.get_component_rich_style(
                        "screen--selection"
                    )
                    before = line.crop_extend(0, start, self.rich_style)
                    selected = line.crop_extend(start, end, self.rich_style)
                    selected = selected.apply_style(selection_style)
                    after = line.crop_extend(end, width, self.rich_style)
                    line = before + selected + after

        # Offset metadata lets the compositor report precise content
        # offsets when the mouse is pressed, enabling exact selections.
        line = line.apply_offsets(scroll_x, y)
        self._line_cache[key] = line
        return line


# ════════════════════════════════════════════════════════════════
# STATUS HEADER
# ════════════════════════════════════════════════════════════════

class StatusHeader(Static):
    """Top status bar showing agent status, project, branch, model."""

    status = reactive("IDLE")
    project_name = reactive("Draft")
    branch = reactive("")
    model = reactive("")

    def render(self) -> str:
        status_icon = {
            "IDLE": "[dim]○[/dim]",
            "RUNNING": "[bold green]●[/bold green]",
            "COMPLETED": "[bold cyan]●[/bold cyan]",
            "FAILED": "[bold red]●[/bold red]",
            "CANCELLED": "[bold yellow]●[/bold yellow]",
        }.get(self.status, "[dim]○[/dim]")

        parts = [
            f"[bold]DRAFT[/bold] {status_icon} [bold]{self.status}[/bold]",
        ]
        if self.project_name:
            parts.append(f"project: [cyan]{self.project_name}[/cyan]")
        if self.branch:
            parts.append(f"branch: [magenta]{self.branch}[/magenta]")
        if self.model:
            parts.append(f"model: [yellow]{self.model}[/yellow]")

        return "  │  ".join(parts)


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
    """

    class FileSelected(Message):
        """A file was selected in the explorer."""
        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

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
        yield Static("[bold]PROJECT[/bold]", classes="panel-title")
        yield DirectoryTree(self._root, id="project-tree")

    def on_mount(self) -> None:
        tree = self.query_one("#project-tree", DirectoryTree)
        tree.show_root = True
        tree.guide_depth = 3
        self._refresh_git_status()

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
# AGENT WORKSPACE
# ════════════════════════════════════════════════════════════════

class AgentWorkspace(Widget):
    """Center panel: scrollable message/event display.

    Distinguishes between USER, AGENT, TOOL, RESULT, ERROR,
    and SYSTEM messages with visual formatting.
    """

    DEFAULT_CSS = """
    AgentWorkspace {
        width: 100%;
        height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]AGENT WORKSPACE[/bold]", classes="panel-title"
        )
        yield RichLog(
            id="workspace-log",
            highlight=True,
            markup=True,
            wrap=True,
            auto_scroll=True,
        )

    @property
    def log(self) -> RichLog:
        return self.query_one("#workspace-log", RichLog)

    def write_user_message(self, content: str) -> None:
        """Display a user message."""
        self.log.write(
            f"\n[bold green]USER[/bold green]\n"
            f"[green]> {escape(content)}[/green]\n"
        )

    def write_agent_message(self, content: str) -> None:
        """Display an agent response."""
        self.log.write(
            f"\n[bold cyan]AGENT[/bold cyan]\n"
            f"{escape(content)}\n"
        )

    def write_tool_started(self, event: ToolStarted) -> None:
        """Display a tool call starting."""
        args_lines = []
        for key, value in event.arguments.items():
            val_str = str(value)
            if len(val_str) > 120:
                val_str = val_str[:117] + "..."
            args_lines.append(f"  [dim]{key}[/dim] = {escape(val_str)}")

        args_block = "\n".join(args_lines) if args_lines else "  [dim](no arguments)[/dim]"

        self.log.write(
            f"\n[bold yellow]TOOL[/bold yellow]\n"
            f"[yellow]┌──────────────────────────────────────┐[/yellow]\n"
            f"[yellow]│[/yellow] [bold]{escape(event.tool_name)}[/bold]\n"
            f"{args_block}\n"
            f"[yellow]│[/yellow] [dim]status: running ⏳[/dim]\n"
            f"[yellow]└──────────────────────────────────────┘[/yellow]"
        )

    def write_tool_completed(self, event: ToolCompleted) -> None:
        """Display a tool call result."""
        result = event.result
        success = result.get("success", False)
        icon = "[green]✓[/green]" if success else "[red]✗[/red]"

        # Build a concise result summary
        result_summary = self._summarize_result(result)

        self.log.write(
            f"[dim]RESULT[/dim] {icon} [bold]{escape(event.tool_name)}[/bold] "
            f"[dim]({event.duration_seconds:.3f}s)[/dim]\n"
            f"{result_summary}"
        )

    def write_tool_failed(self, event: ToolFailed) -> None:
        """Display a tool failure."""
        self.log.write(
            f"\n[bold red]ERROR[/bold red]\n"
            f"[red]✗ {escape(event.tool_name)}: "
            f"{escape(event.error)}[/red]\n"
            f"[dim]({event.duration_seconds:.3f}s)[/dim]"
        )

    def write_system_message(self, content: str, level: str = "info") -> None:
        """Display a system message."""
        color = {"info": "dim", "warning": "yellow", "error": "red"}.get(
            level, "dim"
        )
        self.log.write(f"[{color}]SYSTEM: {escape(content)}[/{color}]")

    def write_patch_applied(self, event: PatchApplied) -> None:
        """Display a successful patch application."""
        self.log.write(
            f"\n[bold green]PATCH APPLIED[/bold green]\n"
            f"[green]  {escape(event.path)}[/green]"
        )
        if event.diff:
            # Show truncated diff
            lines = event.diff.split("\n")
            for line in lines[:20]:
                if line.startswith("+"):
                    self.log.write(f"  [green]{escape(line)}[/green]")
                elif line.startswith("-"):
                    self.log.write(f"  [red]{escape(line)}[/red]")
                else:
                    self.log.write(f"  [dim]{escape(line)}[/dim]")
            if len(lines) > 20:
                self.log.write(f"  [dim]... ({len(lines) - 20} more lines)[/dim]")

    def write_test_completed(self, event: TestCompleted) -> None:
        """Display test results summary."""
        self.log.write(
            f"\n[bold]TESTS[/bold]  [bold]{escape(event.command)}[/bold]\n"
            f"  [green]✓ {event.passed} passed[/green]  "
            f"[red]✗ {event.failed} failed[/red]  "
            f"[yellow]⊘ {event.skipped} skipped[/yellow]  "
            f"[dim]{event.duration_seconds:.2f}s[/dim]"
        )
        # Show individual failures
        for tr in event.results:
            if tr.status == "failed":
                self.log.write(f"  [red]  ✗ {escape(tr.name)}[/red]")

    def _summarize_result(self, result: dict[str, Any]) -> str:
        """Create a concise summary of a tool result."""
        data = result.get("data")
        message = result.get("message", "")
        error = result.get("error", "")

        if error:
            return f"  [red]{escape(str(error))}[/red]"

        if message:
            return f"  [dim]{escape(str(message))}[/dim]"

        if data is None:
            return "  [dim](no data)[/dim]"

        # Truncate large data
        data_str = str(data)
        if len(data_str) > 300:
            data_str = data_str[:297] + "..."
        return f"  [dim]{escape(data_str)}[/dim]"


# ════════════════════════════════════════════════════════════════
# AGENT STATE PANEL
# ════════════════════════════════════════════════════════════════

class AgentStatePanel(Widget):
    """Right panel: live runtime state display."""

    DEFAULT_CSS = """
    AgentStatePanel {
        width: 100%;
        height: 100%;
    }
    """

    # Reactive state
    status = reactive("IDLE")
    task = reactive("")
    phase = reactive("—")
    iteration = reactive(0)
    tool_calls = reactive(0)
    files_read = reactive(0)
    files_modified = reactive(0)
    tests_passed = reactive(0)
    tests_failed = reactive(0)
    current_tool = reactive("")
    current_tool_args = reactive("")
    current_tool_status = reactive("")

    def compose(self) -> ComposeResult:
        yield Static("[bold]AGENT STATE[/bold]", classes="panel-title")
        yield Static(id="state-content")

    def watch_status(self) -> None:
        self._refresh_display()

    def watch_task(self) -> None:
        self._refresh_display()

    def watch_phase(self) -> None:
        self._refresh_display()

    def watch_iteration(self) -> None:
        self._refresh_display()

    def watch_tool_calls(self) -> None:
        self._refresh_display()

    def watch_files_read(self) -> None:
        self._refresh_display()

    def watch_files_modified(self) -> None:
        self._refresh_display()

    def watch_current_tool(self) -> None:
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Rebuild the state panel content."""
        status_icon = {
            "IDLE": "[dim]○ IDLE[/dim]",
            "RUNNING": "[bold green]● RUNNING[/bold green]",
            "COMPLETED": "[bold cyan]● COMPLETED[/bold cyan]",
            "FAILED": "[bold red]● FAILED[/bold red]",
            "CANCELLED": "[bold yellow]● CANCELLED[/bold yellow]",
        }.get(self.status, f"[dim]○ {self.status}[/dim]")

        lines = [
            f"\n  [bold]STATUS[/bold]",
            f"  {status_icon}",
            "",
        ]

        if self.task:
            task_display = self.task
            if len(task_display) > 30:
                task_display = task_display[:27] + "..."
            lines.extend([
                f"  [bold]TASK[/bold]",
                f"  [dim]{escape(task_display)}[/dim]",
                "",
            ])

        lines.extend([
            f"  [bold]PHASE[/bold]",
            f"  {self.phase}",
            "",
            f"  [bold]ITERATION[/bold]",
            f"  {self.iteration}",
            "",
            f"  [bold]STATS[/bold]",
            f"  Tool calls:     {self.tool_calls}",
            f"  Files read:     {self.files_read}",
            f"  Files modified: {self.files_modified}",
        ])

        if self.tests_passed or self.tests_failed:
            lines.extend([
                "",
                f"  [bold]TESTS[/bold]",
                f"  [green]{self.tests_passed} passed[/green]",
                f"  [red]{self.tests_failed} failed[/red]",
            ])

        if self.current_tool:
            lines.extend([
                "",
                f"  [bold]CURRENT TOOL[/bold]",
                f"  [yellow]{escape(self.current_tool)}[/yellow]",
            ])
            if self.current_tool_args:
                lines.append(f"  [dim]{escape(self.current_tool_args)}[/dim]")
            if self.current_tool_status:
                lines.append(f"  status: {self.current_tool_status}")

        try:
            content = self.query_one("#state-content", Static)
            content.update("\n".join(lines))
        except Exception:
            pass

    def update_from_event(self, event: RuntimeEvent) -> None:
        """Update state from a runtime event."""
        from events import (
            AgentIterationStarted,
            AgentPhaseChanged,
        )

        if isinstance(event, AgentStarted):
            self.status = "RUNNING"
            self.task = event.task
            self.iteration = 0
            self.tool_calls = 0
            self.files_read = 0
            self.files_modified = 0
            self.tests_passed = 0
            self.tests_failed = 0
            self.current_tool = ""
        elif isinstance(event, AgentCompleted):
            self.status = "COMPLETED"
            self.current_tool = ""
            self.current_tool_status = ""
        elif isinstance(event, AgentFailed):
            self.status = "FAILED"
            self.current_tool = ""
        elif isinstance(event, AgentPhaseChanged):
            self.phase = event.phase.value.title()
        elif isinstance(event, AgentIterationStarted):
            self.iteration = event.iteration
        elif isinstance(event, ToolStarted):
            self.tool_calls += 1
            self.current_tool = event.tool_name
            args_str = ", ".join(
                f"{k}={v!r}" for k, v in list(event.arguments.items())[:3]
            )
            if len(args_str) > 50:
                args_str = args_str[:47] + "..."
            self.current_tool_args = args_str
            self.current_tool_status = "RUNNING"
        elif isinstance(event, ToolCompleted):
            self.current_tool_status = "COMPLETED"
            if event.tool_name == "read_file":
                self.files_read += 1
            elif event.tool_name in (
                "write_file", "apply_patch", "insert_text",
                "replace_text", "delete_lines",
            ):
                self.files_modified += 1
        elif isinstance(event, ToolFailed):
            self.current_tool_status = "FAILED"
        elif isinstance(event, TestCompleted):
            self.tests_passed = event.passed
            self.tests_failed = event.failed


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
# TOOL INSPECTOR
# ════════════════════════════════════════════════════════════════

class ToolInspector(Widget):
    """Panel for detailed tool call inspection.

    Displays full arguments, result, timing, and callable info.
    """

    DEFAULT_CSS = """
    ToolInspector {
        width: 100%;
        height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]TOOL INSPECTOR[/bold]", classes="panel-title")
        yield RichLog(
            id="tool-inspector-log",
            highlight=True,
            markup=True,
            wrap=True,
        )

    @property
    def log(self) -> RichLog:
        return self.query_one("#tool-inspector-log", RichLog)

    def inspect_tool(self, event: ToolStarted | ToolCompleted | ToolFailed) -> None:
        """Display detailed information about a tool call."""
        self.log.clear()

        if isinstance(event, ToolStarted):
            self.log.write(
                f"[bold]Tool:[/bold] {escape(event.tool_name)}\n"
                f"[bold]Status:[/bold] [yellow]running[/yellow]\n"
                f"[bold]Call ID:[/bold] {escape(event.call_id)}\n"
                f"[bold]Risk:[/bold] {event.risk_level.value}\n"
                f"\n[bold]Arguments:[/bold]"
            )
            args_json = json.dumps(event.arguments, indent=2)
            self.log.write(f"[dim]{escape(args_json)}[/dim]")

        elif isinstance(event, ToolCompleted):
            self.log.write(
                f"[bold]Tool:[/bold] {escape(event.tool_name)}\n"
                f"[bold]Status:[/bold] [green]completed[/green]\n"
                f"[bold]Call ID:[/bold] {escape(event.call_id)}\n"
                f"[bold]Duration:[/bold] {event.duration_seconds:.4f}s\n"
                f"\n[bold]Result:[/bold]"
            )
            result_json = json.dumps(event.result, indent=2, default=str)
            # Truncate very long results
            if len(result_json) > 2000:
                result_json = result_json[:2000] + "\n... [truncated]"
            self.log.write(f"[dim]{escape(result_json)}[/dim]")

        elif isinstance(event, ToolFailed):
            self.log.write(
                f"[bold]Tool:[/bold] {escape(event.tool_name)}\n"
                f"[bold]Status:[/bold] [red]failed[/red]\n"
                f"[bold]Call ID:[/bold] {escape(event.call_id)}\n"
                f"[bold]Duration:[/bold] {event.duration_seconds:.4f}s\n"
                f"\n[bold]Error:[/bold]\n"
                f"[red]{escape(event.error)}[/red]"
            )


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
        yield RichLog(
            id="timeline-log",
            highlight=True,
            markup=True,
            wrap=True,
            auto_scroll=True,
        )

    @property
    def log(self) -> RichLog:
        return self.query_one("#timeline-log", RichLog)

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
        yield RichLog(
            id="diff-log",
            highlight=True,
            markup=True,
            wrap=True,
        )

    @property
    def log(self) -> RichLog:
        return self.query_one("#diff-log", RichLog)

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
        yield RichLog(
            id="test-log",
            highlight=True,
            markup=True,
            wrap=True,
        )

    @property
    def log(self) -> RichLog:
        return self.query_one("#test-log", RichLog)

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
        yield RichLog(
            id="git-log",
            highlight=True,
            markup=True,
            wrap=True,
        )

    @property
    def log(self) -> RichLog:
        return self.query_one("#git-log", RichLog)

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
