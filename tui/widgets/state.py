"""Status header and agent state panel widgets."""

from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.markup import escape, render as render_markup
from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

# Add agent dir to path
_agent_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"
)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

from events import (
    AgentCompleted,
    AgentFailed,
    AgentPhase,
    AgentStarted,
    RuntimeEvent,
    TestCompleted,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

# Wrapping engine used for value/row wrapping.
_WRAP_CONSOLE = Console(width=200, force_terminal=False)

# Row layout: 2-cell left margin + fixed 10-cell label column.
_LABEL_WIDTH = 10
_MARGIN = "  "
_CONTINUATION_INDENT = " " * (len(_MARGIN) + _LABEL_WIDTH)
_FALLBACK_WIDTH = 36


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
# AGENT STATE PANEL
# ════════════════════════════════════════════════════════════════

# Status → (icon, markup open tag) for the STATUS row value.
_STATUS_ICONS = {
    "IDLE": ("○", "[dim]"),
    "RUNNING": ("●", "[bold green]"),
    "COMPLETED": ("●", "[bold cyan]"),
    "FAILED": ("●", "[bold red]"),
    "CANCELLED": ("●", "[bold yellow]"),
}

# Tool status → colored chip for the TOOL row.
_TOOL_CHIPS = {
    "RUNNING": "[bold yellow]●[/bold yellow]",
    "COMPLETED": "[bold green]●[/bold green]",
    "FAILED": "[bold red]●[/bold red]",
    "CANCELLED": "[bold #ffbf00]●[/bold #ffbf00]",
}


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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._content_width = _FALLBACK_WIDTH

    def compose(self) -> ComposeResult:
        yield Static("[bold]AGENT STATE[/bold]", classes="panel-title")
        yield Static(id="state-content")

    def on_mount(self) -> None:
        self._update_content_width()
        self._refresh_display()

    def on_resize(self) -> None:
        self._update_content_width()
        self._refresh_display()

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

    def watch_current_tool_args(self) -> None:
        self._refresh_display()

    def watch_current_tool_status(self) -> None:
        self._refresh_display()

    # ── Rendering helpers ────────────────────────────────────────

    def _update_content_width(self) -> None:
        """Cache the usable content width (CSS padding accounted for)."""
        try:
            styles = self.styles
            base = getattr(styles.width, "value", None) or self.size.width
            if not base:
                base = _FALLBACK_WIDTH
            border = (
                (styles.border_top.width if styles.border_top else 0)
                + (styles.border_bottom.width if styles.border_bottom else 0)
            )
            padding = (
                (styles.padding_left if styles.padding_left else 0)
                + (styles.padding_right if styles.padding_right else 0)
            )
            width = base - border - padding
            self._content_width = max(16, width)
        except Exception:
            self._content_width = _FALLBACK_WIDTH

    def _wrap_text(self, text: Text) -> Text:
        """Wrap a styled Text to the panel width, indenting continuations."""
        width = self._content_width
        lines = text.wrap(_WRAP_CONSOLE, width=width)
        parts: list[Text] = []
        for i, line in enumerate(lines):
            if i > 0:
                line = Text(_CONTINUATION_INDENT) + line
            parts.append(line)
        return Text("\n").join(parts)

    def _row(self, label: str, value: Text) -> Text:
        """A single aligned label + value row, wrapped to the panel."""
        row = Text(f"{_MARGIN}{label:<{_LABEL_WIDTH}}", style="bold #8888cc")
        row.append_text(value)
        return self._wrap_text(row)

    def _scalar_row(self, label: str, value) -> Text:
        return self._row(label, Text(str(value)))

    def _markup_value(self, markup: str) -> Text:
        return render_markup(markup)

    # ── Display ──────────────────────────────────────────────────

    def _refresh_display(self) -> None:
        """Rebuild the state panel content."""
        parts: list[Text] = []

        # STATUS row: colored icon + text.
        icon, open_span = _STATUS_ICONS.get(self.status, ("○", "[dim]"))
        status_value = f"{open_span}{icon} {self.status}[/]"
        parts.append(self._row("STATUS", self._markup_value(status_value)))

        # TASK row (omitted entirely when empty).
        if self.task:
            task_value = Text(escape(self.task), style="dim")
            parts.append(self._row("TASK", task_value))

        # PHASE row.
        parts.append(
            self._row(
                "PHASE",
                self._markup_value(f"[cyan]{escape(self.phase)}[/cyan]"),
            )
        )

        # TOOL row (only when a current tool exists).
        if self.current_tool:
            tool_markup = f"[yellow]{escape(self.current_tool)}[/yellow]"
            chip = _TOOL_CHIPS.get(self.current_tool_status, "")
            if chip:
                tool_markup = f"{tool_markup}  {chip}"
            parts.append(self._row("TOOL", self._markup_value(tool_markup)))

        # Counter rows.
        parts.append(self._scalar_row("ITERATION", self.iteration))
        parts.append(self._scalar_row("CALLS", self.tool_calls))
        parts.append(self._scalar_row("READ", self.files_read))
        parts.append(self._scalar_row("MODIFIED", self.files_modified))

        # TESTS row (only when any tests have run).
        if self.tests_passed or self.tests_failed:
            tests_value = Text()
            tests_value.append(
                f"{self.tests_passed} passed", style="green"
            )
            tests_value.append("  ")
            tests_value.append(
                f"{self.tests_failed} failed", style="red"
            )
            parts.append(self._row("TESTS", tests_value))

        try:
            content = self.query_one("#state-content", Static)
            content.update(Text("\n\n").join(parts))
        except Exception:
            pass

    # ── Public API ───────────────────────────────────────────────

    def mark_tool_cancelled(self) -> None:
        """Mark the current tool as cancelled (e.g. approval denied)."""
        self.current_tool_status = "CANCELLED"

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