"""Tool inspector widget — detailed tool call inspection."""

from __future__ import annotations

import json
import os
import sys

from rich.markup import escape
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

# Add agent dir to path
_agent_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"
)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

from events import (
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

from tui.widgets.common import SelectableRichLog


# ════════════════════════════════════════════════════════════════
# LIFECYCLE CHIP VOCABULARY
# ════════════════════════════════════════════════════════════════

_RUNNING_CHIP = "[yellow]RUNNING[/yellow]"
_COMPLETED_CHIP = "[green]✓ COMPLETED ({duration:.3f}s)[/green]"
_FAILED_CHIP = "[red]✗ FAILED ({duration:.3f}s)[/red]"
_CANCELLED_CHIP = "[amber]○ CANCELLED[/amber]"

# Very long results are truncated for the inspector view.
_RESULT_TRUNCATION_LIMIT = 2000
_TRUNCATION_SUFFIX = "\n… (truncated)"


# ════════════════════════════════════════════════════════════════
# TOOL INSPECTOR
# ════════════════════════════════════════════════════════════════

class ToolInspector(Widget):
    """Panel for detailed tool call inspection.

    Displays full arguments, result, error, timing, and a lifecycle
    status chip. Tracks the currently displayed call so a later
    cancellation can rewrite the header chip in place.
    """

    DEFAULT_CSS = """
    ToolInspector {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._current_call_id: str | None = None
        self._current_tool_name: str | None = None
        self._current_meta_lines: tuple[str, ...] = ()
        self._current_body: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("[bold]TOOL INSPECTOR[/bold]", classes="panel-title")
        yield SelectableRichLog(
            id="tool-inspector-log",
            highlight=True,
            markup=True,
            wrap=True,
        )

    @property
    def log(self) -> SelectableRichLog:
        return self.query_one("#tool-inspector-log", SelectableRichLog)

    def inspect_tool(self, event: ToolStarted | ToolCompleted | ToolFailed) -> None:
        """Display detailed information about a tool call."""
        self.log.clear()
        self._current_call_id = event.call_id
        self._current_tool_name = event.tool_name

        if isinstance(event, ToolStarted):
            chip = _RUNNING_CHIP
            self._current_meta_lines = (
                f"[bold]Call ID:[/bold] {escape(event.call_id)}",
                f"[bold]Risk:[/bold] {event.risk_level.value}",
            )
            args_json = json.dumps(event.arguments, indent=2)
            self._current_body = (
                f"[bold]Arguments:[/bold]\n"
                f"[dim]{escape(args_json)}[/dim]"
            )

        elif isinstance(event, ToolCompleted):
            chip = _COMPLETED_CHIP.format(duration=event.duration_seconds)
            self._current_meta_lines = (
                f"[bold]Call ID:[/bold] {escape(event.call_id)}",
                f"[bold]Duration:[/bold] {event.duration_seconds:.4f}s",
            )
            result_json = json.dumps(event.result, indent=2, default=str)
            # Truncate very long results
            if len(result_json) > _RESULT_TRUNCATION_LIMIT:
                result_json = (
                    result_json[:_RESULT_TRUNCATION_LIMIT] + _TRUNCATION_SUFFIX
                )
            self._current_body = (
                f"[bold]Result:[/bold]\n"
                f"[dim]{escape(result_json)}[/dim]"
            )

        else:  # ToolFailed
            chip = _FAILED_CHIP.format(duration=event.duration_seconds)
            self._current_meta_lines = (
                f"[bold]Call ID:[/bold] {escape(event.call_id)}",
                f"[bold]Duration:[/bold] {event.duration_seconds:.4f}s",
            )
            self._current_body = (
                f"[bold]Error:[/bold]\n"
                f"[red]{escape(event.error)}[/red]"
            )

        self.log.write(
            f"[bold]Tool:[/bold] {escape(event.tool_name)} {chip}\n"
            + "\n".join(self._current_meta_lines)
        )
        self.log.write(f"\n{self._current_body}")

    def mark_cancelled(self, call_id: str) -> None:
        """Rewrite the header chip to ``CANCELLED`` for the displayed call.

        Applies only when the given call is the one currently shown;
        otherwise this is a no-op. The rest of the inspection content
        is preserved.
        """
        if self._current_call_id != call_id or self._current_tool_name is None:
            return
        self.log.clear()
        self.log.write(
            f"[bold]Tool:[/bold] {escape(self._current_tool_name)} {_CANCELLED_CHIP}\n"
            + "\n".join(self._current_meta_lines)
        )
        if self._current_body is not None:
            self.log.write(f"\n{self._current_body}")