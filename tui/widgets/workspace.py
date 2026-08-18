"""Agent workspace widget — the center conversation/log surface."""

from __future__ import annotations

import os
import sys
from typing import Any

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
    PatchApplied,
    TestCompleted,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

from tui.widgets.common import SelectableRichLog


# ════════════════════════════════════════════════════════════════
# AGENT WORKSPACE
# ════════════════════════════════════════════════════════════════

class AgentWorkspace(Widget):
    """Center panel: scrollable message/event display.

    Distinguishes between USER, AGENT, TOOL, RESULT, ERROR,
    and SYSTEM messages with visual formatting.

    All event blocks share one header style (label + colored text) and
    are separated by a blank line. Tool calls render as indentation-
    based cards (no fixed-width borders) so long names, paths and
    arguments wrap naturally and are never clipped.
    """

    DEFAULT_CSS = """
    AgentWorkspace {
        width: 100%;
        height: 100%;
    }
    """

    _PREVIEW_LIMIT = 200
    _RESULT_LIMIT = 300
    _MULTILINE_LINES = 5

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tool_calls: dict[str, str] = {}
        """call_id → tool_name for terminal-state rendering."""

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]AGENT WORKSPACE[/bold]", classes="panel-title"
        )
        yield SelectableRichLog(
            id="workspace-log",
            highlight=True,
            markup=True,
            wrap=True,
            auto_scroll=True,
        )

    @property
    def log(self) -> SelectableRichLog:
        return self.query_one("#workspace-log", SelectableRichLog)

    # ── Conversation events ─────────────────────────────────────

    def write_user_message(self, content: str) -> None:
        """Display a user message."""
        self.log.write(
            f"\n[bold green]USER[/bold green]\n"
            f"  [green]> {escape(content)}[/green]"
        )

    def write_agent_message(self, content: str) -> None:
        """Display an agent response."""
        self.log.write(
            f"\n[bold cyan]AGENT[/bold cyan]\n"
            f"{escape(content)}"
        )

    def write_system_message(self, content: str, level: str = "info") -> None:
        """Display a system message."""
        color = {"info": "dim", "warning": "yellow", "error": "red"}.get(
            level, "dim"
        )
        self.log.write(f"\n[{color}]SYSTEM: {escape(content)}[/{color}]")

    # ── Tool events ─────────────────────────────────────────────

    def write_tool_started(self, event: ToolStarted) -> None:
        """Display a tool call starting (RUNNING card)."""
        self._tool_calls[event.call_id] = event.tool_name

        lines = [
            f"\n[bold yellow]TOOL[/bold yellow]  "
            f"[bold]{escape(event.tool_name)}[/bold]  "
            f"[yellow]RUNNING ⏳[/yellow]"
        ]
        for key, value in event.arguments.items():
            lines.append(f"  {escape(str(key))}: {self._preview_value(value)}")
        lines.append(f"  [dim]risk: {event.risk_level.value}[/dim]")

        self.log.write("\n".join(lines))

    def write_tool_completed(self, event: ToolCompleted) -> None:
        """Display a tool call result (RESULT block)."""
        result = event.result
        success = bool(result.get("success", False))
        icon, color = ("✓", "green") if success else ("✗", "red")
        word = "COMPLETED" if success else "FAILED"

        lines = [
            f"\n[dim]RESULT[/dim]  [{color}]{icon} {word}[/{color}] "
            f"{escape(event.tool_name)}  "
            f"[dim]({event.duration_seconds:.3f}s)[/dim]",
            f"  result: {self._preview_result(result)}",
        ]
        if result.get("error"):
            lines.append(
                f"  [red]error: {escape(str(result['error']))}[/red]"
            )

        self.log.write("\n".join(lines))

    def write_tool_failed(self, event: ToolFailed) -> None:
        """Display a tool failure (RESULT block)."""
        self.log.write(
            f"\n[dim]RESULT[/dim]  [red]✗ FAILED[/red] "
            f"{escape(event.tool_name)}  "
            f"[dim]({event.duration_seconds:.3f}s)[/dim]\n"
            f"  [red]error: {escape(event.error)}[/red]"
        )

    def mark_tool_cancelled(self, call_id: str) -> None:
        """Display a CANCELLED result block for a tool call.

        Unknown call ids are ignored (no card was ever started).
        """
        name = self._tool_calls.get(call_id)
        if name is None:
            return
        self.log.write(
            f"\n[dim]RESULT[/dim]  [amber]○ CANCELLED[/amber] "
            f"{escape(name)}"
        )

    # ── File / test events ──────────────────────────────────────

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

    # ── Preview helpers ─────────────────────────────────────────

    def _preview_value(self, value: Any) -> str:
        """Render an argument value as a wrap-safe preview.

        Multi-line values (file content, patches) show the first few
        lines with a ``(+n more lines — F4 full view)`` suffix;
        everything is truncated around ``_PREVIEW_LIMIT`` characters.
        """
        text = escape(str(value))

        if "\n" not in text:
            return self._truncate(text, self._PREVIEW_LIMIT)

        head_lines = text.split("\n")
        shown = head_lines[: self._MULTILINE_LINES]
        preview = "\n  ".join(shown)
        remaining_lines = len(head_lines) - len(shown)

        if len(preview) > self._PREVIEW_LIMIT:
            return self._truncate(preview, self._PREVIEW_LIMIT)

        if remaining_lines > 0:
            return f"{preview}\n  (+{remaining_lines} more lines — F4 full view)"

        return preview

    def _preview_result(self, result: dict[str, Any]) -> str:
        """Build the ``result:`` line for a tool completion."""
        message = result.get("message")
        if message:
            return f"[dim]{self._preview_value(message)}[/dim]"

        data = result.get("data")
        if data is None:
            return "[dim](no data)[/dim]"

        return f"[dim]{self._preview_value(data)}[/dim]"

    def _truncate(self, text: str, limit: int) -> str:
        """Truncate escaped text with an ellipsis and F4 hint suffix."""
        if len(text) <= limit:
            return text
        more = len(text) - limit
        return f"{text[:limit]}… (+{more} more chars — F4 full view)"