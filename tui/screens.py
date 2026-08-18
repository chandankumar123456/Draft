"""Textual Screen subclasses for modal/full-screen views.

Each screen can be pushed/popped with F-key bindings from the
main app.  They wrap the corresponding widgets and add screen-level
key bindings.
"""

from __future__ import annotations

from typing import Any

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
    """Full-screen interactive diff viewer."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back to Cockpit"),
        Binding("q", "pop_screen", "Back to Cockpit"),
        Binding("c", "clear_diffs", "Clear Diffs"),
    ]

    DEFAULT_CSS = """
    DiffScreen {
        layout: vertical;
        background: #0f0f1a;
    }
    #diff-screen-header {
        height: 1;
        width: 100%;
        background: #1a1a2e;
        color: #6688cc;
        content-align: center middle;
        text-style: bold;
    }
    #diff-screen-container {
        height: 1fr;
        width: 100%;
        padding: 0 1;
    }
    #diff-screen-view {
        height: 100%;
        width: 100%;
    }
    #diff-footer-bar {
        height: 3;
        width: 100%;
        background: #1a1a2e;
        align: center middle;
        padding: 0 1;
    }
    #diff-footer-bar Button {
        height: 1;
        min-width: 10;
        margin: 0 1;
        padding: 0 1;
        border: none;
        background: #22223b;
        color: #aaaaee;
    }
    #diff-footer-bar Button:hover {
        background: #3b3b66;
        color: #ffffff;
    }
    #diff-footer-bar Button:focus {
        border: tall #6688cc;
        background: #2563eb;
        color: #ffffff;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("📑 DRAFT UNIFIED DIFF VIEWER", id="diff-screen-header")
        with Vertical(id="diff-screen-container"):
            yield DiffView(id="diff-screen-view")
        yield Horizontal(
            Button("[ Esc ] Back", id="btn-diff-back"),
            Button("[ C ] Clear Diffs", id="btn-diff-clear"),
            Button("[ Tab ] Focus Log", id="btn-diff-focus", variant="primary"),
            Button("[ Q ] Close", id="btn-diff-close"),
            id="diff-footer-bar",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id in ("btn-diff-back", "btn-diff-close"):
            self.action_pop_screen()
        elif btn_id == "btn-diff-clear":
            self.action_clear_diffs()
        elif btn_id == "btn-diff-focus":
            try:
                self.query_one("#diff-screen-view", DiffView).log.focus()
            except Exception:
                pass

    def action_pop_screen(self) -> None:
        self.dismiss()

    def action_clear_diffs(self) -> None:
        try:
            self.query_one("#diff-screen-view", DiffView).clear_diffs()
        except Exception:
            pass


from rich.markup import escape
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from tui.widgets.common import SelectableRichLog


TOOL_METADATA: dict[str, dict[str, Any]] = {
    # 📁 File System
    "list_files": {
        "category": "📁 File System",
        "desc": "List files in a directory path with relative paths and sizes.",
        "params": {"directory_path": "Directory path (default: current directory)"},
        "risk": "LOW",
    },
    "list_directory_tree": {
        "category": "📁 File System",
        "desc": "Generate recursive tree structure of directories and files.",
        "params": {"directory_path": "Directory root path", "max_depth": "Max recursion depth (default: 3)"},
        "risk": "LOW",
    },
    "read_file": {
        "category": "📁 File System",
        "desc": "Read content of a file from workspace, optionally by line slice.",
        "params": {"file_path": "Target file path", "start_line": "Starting line number (optional)", "end_line": "Ending line number (optional)"},
        "risk": "LOW",
    },
    "write_file": {
        "category": "📁 File System",
        "desc": "Write or overwrite content to a file in workspace.",
        "params": {"file_path": "Target file path", "content": "File content to write"},
        "risk": "MEDIUM",
    },
    "get_file_info": {
        "category": "📁 File System",
        "desc": "Retrieve file metadata (size, lines, modified time, permissions).",
        "params": {"file_path": "Target file path"},
        "risk": "LOW",
    },
    "create_directory": {
        "category": "📁 File System",
        "desc": "Create a new directory and any missing parent directories.",
        "params": {"directory_path": "Directory path to create"},
        "risk": "LOW",
    },
    "delete_file": {
        "category": "📁 File System",
        "desc": "Delete a file from the workspace.",
        "params": {"file_path": "File path to delete"},
        "risk": "HIGH",
    },
    "delete_directory": {
        "category": "📁 File System",
        "desc": "Delete a directory from the workspace.",
        "params": {"directory_path": "Directory path to delete", "recursive": "Whether to delete recursively"},
        "risk": "HIGH",
    },
    "move_file": {
        "category": "📁 File System",
        "desc": "Move or rename a file from source to destination.",
        "params": {"source_path": "Source file path", "destination_path": "Destination file path"},
        "risk": "MEDIUM",
    },
    "copy_file": {
        "category": "📁 File System",
        "desc": "Copy a file from source to destination.",
        "params": {"source_path": "Source file path", "destination_path": "Destination file path"},
        "risk": "LOW",
    },

    # 🔍 Search & Code
    "search_code": {
        "category": "🔍 Search & Code",
        "desc": "Search for code patterns, regex, or symbols across repository files.",
        "params": {"pattern": "Search string or regex pattern", "directory_path": "Search root path (default: .)"},
        "risk": "LOW",
    },
    "grep": {
        "category": "🔍 Search & Code",
        "desc": "Ripgrep search with line numbers and context matches.",
        "params": {"query": "Text query or regex", "path": "Target file or directory", "case_sensitive": "Case sensitive flag"},
        "risk": "LOW",
    },
    "find_files": {
        "category": "🔍 Search & Code",
        "desc": "Find files matching glob pattern (e.g. *.py, test_*.ts).",
        "params": {"pattern": "File glob pattern", "directory_path": "Search root path"},
        "risk": "LOW",
    },
    "find_symbol": {
        "category": "🔍 Search & Code",
        "desc": "Locate symbol definitions (classes, functions, methods).",
        "params": {"symbol_name": "Name of symbol to find"},
        "risk": "LOW",
    },
    "find_references": {
        "category": "🔍 Search & Code",
        "desc": "Find all references and usages of a symbol across the project.",
        "params": {"symbol_name": "Name of symbol to reference-search"},
        "risk": "LOW",
    },
    "get_file_symbols": {
        "category": "🔍 Search & Code",
        "desc": "Extract all functions, classes, and top-level symbols in a file.",
        "params": {"file_path": "Target file path"},
        "risk": "LOW",
    },

    # ✏️ Editing & Patching
    "apply_patch": {
        "category": "✏️ Editing & Patching",
        "desc": "Apply unified diff patch directly to workspace files.",
        "params": {"patch_content": "Unified diff patch content", "file_path": "Target file path"},
        "risk": "MEDIUM",
    },
    "insert_text": {
        "category": "✏️ Editing & Patching",
        "desc": "Insert text at specific line number in a file.",
        "params": {"file_path": "Target file path", "line_number": "Line number to insert at", "text": "Text to insert"},
        "risk": "MEDIUM",
    },
    "replace_text": {
        "category": "✏️ Editing & Patching",
        "desc": "Replace exact target string with replacement text in a file.",
        "params": {"file_path": "Target file path", "target": "Exact string to replace", "replacement": "New string"},
        "risk": "MEDIUM",
    },
    "delete_lines": {
        "category": "✏️ Editing & Patching",
        "desc": "Delete a range of lines from a file.",
        "params": {"file_path": "Target file path", "start_line": "Start line number", "end_line": "End line number"},
        "risk": "HIGH",
    },

    # ⚙️ Execution & Diagnostics
    "run_command": {
        "category": "⚙️ Execution & Diagnostics",
        "desc": "Execute shell command in project directory with timeout.",
        "params": {"command": "Command line string", "timeout": "Timeout in seconds (default: 30)"},
        "risk": "HIGH",
    },
    "run_python": {
        "category": "⚙️ Execution & Diagnostics",
        "desc": "Execute inline Python snippet in isolated environment.",
        "params": {"code": "Python code snippet"},
        "risk": "HIGH",
    },
    "run_tests": {
        "category": "⚙️ Execution & Diagnostics",
        "desc": "Run project test suite (pytest, npm test, unittest) and parse results.",
        "params": {"test_path": "Optional test file or test path filter"},
        "risk": "MEDIUM",
    },
    "check_syntax": {
        "category": "⚙️ Execution & Diagnostics",
        "desc": "Validate Python syntax without executing the code.",
        "params": {"file_path": "Target Python file path"},
        "risk": "LOW",
    },
    "lint_project": {
        "category": "⚙️ Execution & Diagnostics",
        "desc": "Run code linter (flake8, ruff, eslint) and report diagnostic issues.",
        "params": {"path": "Optional path to lint"},
        "risk": "LOW",
    },
    "typecheck_project": {
        "category": "⚙️ Execution & Diagnostics",
        "desc": "Run static type checker (mypy, tsc) and report type errors.",
        "params": {"path": "Optional path to typecheck"},
        "risk": "LOW",
    },

    # 🐙 Git Version Control
    "git_status": {
        "category": "🐙 Git Version Control",
        "desc": "Inspect working tree status, modified, staged, and untracked files.",
        "params": {},
        "risk": "LOW",
    },
    "git_diff": {
        "category": "🐙 Git Version Control",
        "desc": "Show git diff against working tree or specific commit/branch.",
        "params": {"staged": "Show staged diff flag", "file_path": "Optional file path filter"},
        "risk": "LOW",
    },
    "git_log": {
        "category": "🐙 Git Version Control",
        "desc": "View commit history and recent commit logs.",
        "params": {"max_count": "Number of commits (default: 10)"},
        "risk": "LOW",
    },
    "git_show": {
        "category": "🐙 Git Version Control",
        "desc": "Show commit details and unified diff for a commit hash.",
        "params": {"commit": "Commit hash or ref (default: HEAD)"},
        "risk": "LOW",
    },
    "git_branch": {
        "category": "🐙 Git Version Control",
        "desc": "List local and remote branches.",
        "params": {},
        "risk": "LOW",
    },
    "git_branch_create": {
        "category": "🐙 Git Version Control",
        "desc": "Create a new git branch from current HEAD.",
        "params": {"branch_name": "Name of branch to create"},
        "risk": "MEDIUM",
    },
    "git_branch_switch": {
        "category": "🐙 Git Version Control",
        "desc": "Switch active branch to existing git branch.",
        "params": {"branch_name": "Name of branch to checkout"},
        "risk": "MEDIUM",
    },
    "git_add": {
        "category": "🐙 Git Version Control",
        "desc": "Stage files or changes for commit.",
        "params": {"file_path": "File path to stage (or . for all)"},
        "risk": "LOW",
    },
    "git_commit": {
        "category": "🐙 Git Version Control",
        "desc": "Commit staged changes with descriptive message.",
        "params": {"message": "Commit message"},
        "risk": "MEDIUM",
    },
    "git_stash": {
        "category": "🐙 Git Version Control",
        "desc": "Stash current working tree changes.",
        "params": {"message": "Optional stash label message"},
        "risk": "LOW",
    },
    "git_stash_pop": {
        "category": "🐙 Git Version Control",
        "desc": "Restore most recently stashed changes.",
        "params": {},
        "risk": "MEDIUM",
    },

    # 🌐 Web & Utilities
    "search_web": {
        "category": "🌐 Web & Utilities",
        "desc": "Perform web search for documentation, packages, or error diagnostics.",
        "params": {"query": "Search query text"},
        "risk": "LOW",
    },
    "fetch_url": {
        "category": "🌐 Web & Utilities",
        "desc": "Fetch public web page or API endpoint contents as markdown/text.",
        "params": {"url": "Target URL to fetch"},
        "risk": "LOW",
    },
    "inspect_project": {
        "category": "🌐 Web & Utilities",
        "desc": "Analyze project type, structure, dependencies, and environment.",
        "params": {},
        "risk": "LOW",
    },
    "get_current_time": {
        "category": "🌐 Web & Utilities",
        "desc": "Get current timestamp in ISO 8601 format and local timezone.",
        "params": {},
        "risk": "LOW",
    },
    "calculate": {
        "category": "🌐 Web & Utilities",
        "desc": "Evaluate safe mathematical expression.",
        "params": {"expression": "Math expression string"},
        "risk": "LOW",
    },
    "generate_uuid": {
        "category": "🌐 Web & Utilities",
        "desc": "Generate random UUID v4 identifier.",
        "params": {},
        "risk": "LOW",
    },
}


class ToolInspectorScreen(Screen):
    """Full-screen interactive tool catalog and inspector."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back to Cockpit"),
        Binding("q", "pop_screen", "Back to Cockpit"),
        Binding("slash", "focus_search", "Search"),
        Binding("c", "clear_search", "Clear"),
    ]

    DEFAULT_CSS = """
    ToolInspectorScreen {
        layout: vertical;
        background: #0f0f1a;
    }
    #tools-header {
        height: 1;
        width: 100%;
        background: #1a1a2e;
        color: #6688cc;
        content-align: center middle;
        text-style: bold;
    }
    #tools-search-bar {
        height: 3;
        width: 100%;
        padding: 0 1;
        background: #141428;
    }
    #tools-search-input {
        width: 100%;
        border: tall #444466;
        background: #1a1a2e;
        color: #ffffff;
    }
    #tools-search-input:focus {
        border: tall #6688cc;
    }
    #tools-main-container {
        height: 1fr;
        width: 100%;
    }
    #tools-list-container {
        width: 32%;
        min-width: 28;
        max-width: 44;
        height: 100%;
        border-right: tall #333344;
        background: #0d0d1a;
    }
    #tools-option-list {
        height: 1fr;
        background: transparent;
        scrollbar-size: 1 1;
    }
    #tools-option-list:focus {
        border: tall #6688cc;
    }
    #tools-detail-container {
        width: 1fr;
        height: 100%;
        background: #0f0f1a;
        padding: 0 1;
    }
    #tool-detail-header {
        height: auto;
        min-height: 2;
        width: 100%;
        padding: 0 1;
        background: #16213e;
        color: #ffffff;
    }
    #tool-detail-log {
        height: 1fr;
        width: 100%;
        background: #0d0d1a;
        border: round #333344;
        padding: 0 1;
    }
    #tools-footer-bar {
        height: 3;
        width: 100%;
        background: #1a1a2e;
        align: center middle;
        padding: 0 1;
    }
    #tools-footer-bar Button {
        height: 1;
        min-width: 10;
        margin: 0 1;
        padding: 0 1;
        border: none;
        background: #22223b;
        color: #aaaaee;
    }
    #tools-footer-bar Button:hover {
        background: #3b3b66;
        color: #ffffff;
    }
    #tools-footer-bar Button:focus {
        border: tall #6688cc;
        background: #2563eb;
        color: #ffffff;
    }
    #tools-footer-bar Button.-active {
        background: #2563eb;
        color: #ffffff;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._filtered_tools: list[str] = list(TOOL_METADATA.keys())

    def compose(self) -> ComposeResult:
        yield Static("🛠️  DRAFT TOOLS CATALOG & INSPECTOR", id="tools-header")
        yield Horizontal(
            Input(
                placeholder="🔍 Search tools by name, description, or category (press / to focus)...",
                id="tools-search-input",
            ),
            id="tools-search-bar",
        )
        yield Horizontal(
            Vertical(
                Static("[bold cyan]AVAILABLE TOOLS[/bold cyan]", classes="panel-title"),
                OptionList(id="tools-option-list"),
                id="tools-list-container",
            ),
            Vertical(
                Static("", id="tool-detail-header"),
                SelectableRichLog(
                    id="tool-detail-log",
                    highlight=True,
                    markup=True,
                    wrap=True,
                    auto_scroll=False,
                ),
                id="tools-detail-container",
            ),
            id="tools-main-container",
        )
        yield Horizontal(
            Button("[ Esc ] Back", id="btn-tools-back"),
            Button("[ / ] Search", id="btn-tools-search"),
            Button("[ C ] Clear Search", id="btn-tools-clear"),
            Button("[ Tab ] Next Control", id="btn-tools-tab"),
            Button("[ Enter ] Focus Detail", id="btn-tools-detail", variant="primary"),
            id="tools-footer-bar",
        )

    def on_mount(self) -> None:
        """Populate initial tool list on mount."""
        self._populate_tool_list()
        try:
            op_list = self.query_one("#tools-option-list", OptionList)
            op_list.focus()
        except Exception:
            pass

    def _populate_tool_list(self, filter_query: str = "") -> None:
        """Filter and populate the tool option list."""
        query = filter_query.strip().lower()
        self._filtered_tools = []
        op_list = self.query_one("#tools-option-list", OptionList)
        op_list.clear_options()

        for name, meta in TOOL_METADATA.items():
            if not query or (
                query in name.lower()
                or query in meta["category"].lower()
                or query in meta["desc"].lower()
            ):
                self._filtered_tools.append(name)
                risk_badge = {
                    "LOW": "[green]L[/green]",
                    "MEDIUM": "[yellow]M[/yellow]",
                    "HIGH": "[red]H[/red]",
                }.get(meta["risk"], "")
                op_list.add_option(
                    Option(f"{risk_badge} [bold]{name}[/bold] [dim]({meta['category'].split()[-1]})[/dim]", id=name)
                )

        if self._filtered_tools:
            op_list.highlighted = 0
            self._render_tool_detail(self._filtered_tools[0])
        else:
            header_widget = self.query_one("#tool-detail-header", Static)
            header_widget.update("[yellow]No tools matching filter[/yellow]")
            log = self.query_one("#tool-detail-log", SelectableRichLog)
            log.clear()
            log.write("\n[dim]Try clearing the search query to see all available tools.[/dim]")

    def _render_tool_detail(self, tool_name: str) -> None:
        """Render tool description, parameters, and risk level."""
        meta = TOOL_METADATA.get(tool_name, {
            "category": "🛠️ General",
            "desc": f"Agent tool: {tool_name}",
            "params": {},
            "risk": "LOW",
        })

        header_widget = self.query_one("#tool-detail-header", Static)
        risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}.get(meta["risk"], "green")
        header_widget.update(
            f"[bold cyan]Tool:[/bold cyan] [bold white]{tool_name}[/bold white]  "
            f"[dim]|[/dim]  [bold]Category:[/bold] {meta['category']}  "
            f"[dim]|[/dim]  [bold]Risk:[/bold] [{risk_color} bold][{meta['risk']}][/ {risk_color} bold]"
        )

        log = self.query_one("#tool-detail-log", SelectableRichLog)
        log.clear()

        log.write(f"\n[bold]Description:[/bold]\n  [white]{escape(meta['desc'])}[/white]\n")
        log.write(f"[bold]Parameters & Arguments:[/bold]")
        if meta["params"]:
            for param, p_desc in meta["params"].items():
                log.write(f"  [bold yellow]• {param:<22}[/bold yellow] [dim]{escape(p_desc)}[/dim]")
        else:
            log.write("  [dim](No parameters required)[/dim]")

        log.write(f"\n[bold]Execution & Safety Policy:[/bold]")
        if meta["risk"] == "HIGH":
            log.write("  [bold red]⚠️  Requires explicit user approval before execution in standard mode.[/bold red]")
        elif meta["risk"] == "MEDIUM":
            log.write("  [yellow]⚡ Modifies workspace state; logged and tracked in timeline.[/yellow]")
        else:
            log.write("  [green]✓ Read-only inspection / query operation; safe to auto-execute.[/green]")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle real-time search input changes."""
        if event.input.id == "tools-search-input":
            self._populate_tool_list(event.value)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Handle option highlighted."""
        if event.option_id and event.option_id in TOOL_METADATA:
            self._render_tool_detail(str(event.option_id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selected."""
        if event.option_id and event.option_id in TOOL_METADATA:
            self._render_tool_detail(str(event.option_id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle bottom control buttons."""
        button_id = event.button.id
        if button_id == "btn-tools-back":
            self.action_pop_screen()
        elif button_id == "btn-tools-search":
            self.action_focus_search()
        elif button_id == "btn-tools-clear":
            self.action_clear_search()
        elif button_id == "btn-tools-tab":
            self.app.action_focus_next()
        elif button_id == "btn-tools-detail":
            try:
                self.query_one("#tool-detail-log", SelectableRichLog).focus()
            except Exception:
                pass

    def action_pop_screen(self) -> None:
        """Pop screen and return to main cockpit."""
        self.dismiss()

    def action_focus_search(self) -> None:
        """Focus the search input."""
        try:
            self.query_one("#tools-search-input", Input).focus()
        except Exception:
            pass

    def action_clear_search(self) -> None:
        """Clear search filter."""
        try:
            inp = self.query_one("#tools-search-input", Input)
            inp.value = ""
            self._populate_tool_list("")
            self.query_one("#tools-option-list", OptionList).focus()
        except Exception:
            pass


class TimelineScreen(Screen):
    """Full-screen interactive event timeline."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back to Cockpit"),
        Binding("q", "pop_screen", "Back to Cockpit"),
        Binding("c", "clear_timeline", "Clear"),
    ]

    DEFAULT_CSS = """
    TimelineScreen {
        layout: vertical;
        background: #0f0f1a;
    }
    #timeline-screen-header {
        height: 1;
        width: 100%;
        background: #1a1a2e;
        color: #6688cc;
        content-align: center middle;
        text-style: bold;
    }
    #timeline-screen-container {
        height: 1fr;
        width: 100%;
        padding: 0 1;
    }
    #timeline-screen-view {
        height: 100%;
        width: 100%;
    }
    #timeline-footer-bar {
        height: 3;
        width: 100%;
        background: #1a1a2e;
        align: center middle;
        padding: 0 1;
    }
    #timeline-footer-bar Button {
        height: 1;
        min-width: 10;
        margin: 0 1;
        padding: 0 1;
        border: none;
        background: #22223b;
        color: #aaaaee;
    }
    #timeline-footer-bar Button:hover {
        background: #3b3b66;
        color: #ffffff;
    }
    #timeline-footer-bar Button:focus {
        border: tall #6688cc;
        background: #2563eb;
        color: #ffffff;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("📜 DRAFT EVENT TIMELINE & LOGS", id="timeline-screen-header")
        with Vertical(id="timeline-screen-container"):
            yield TimelineView(id="timeline-screen-view")
        yield Horizontal(
            Button("[ Esc ] Back", id="btn-timeline-back"),
            Button("[ C ] Clear Logs", id="btn-timeline-clear"),
            Button("[ Tab ] Focus Log", id="btn-timeline-focus", variant="primary"),
            Button("[ Q ] Close", id="btn-timeline-close"),
            id="timeline-footer-bar",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id in ("btn-timeline-back", "btn-timeline-close"):
            self.action_pop_screen()
        elif btn_id == "btn-timeline-clear":
            self.action_clear_timeline()
        elif btn_id == "btn-timeline-focus":
            try:
                self.query_one("#timeline-screen-view", TimelineView).log.focus()
            except Exception:
                pass

    def action_pop_screen(self) -> None:
        self.dismiss()

    def action_clear_timeline(self) -> None:
        try:
            self.query_one("#timeline-screen-view", TimelineView).log.clear()
        except Exception:
            pass


class TestDashboardScreen(Screen):
    """Full-screen interactive test results dashboard."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back to Cockpit"),
        Binding("q", "pop_screen", "Back to Cockpit"),
    ]

    DEFAULT_CSS = """
    TestDashboardScreen {
        layout: vertical;
        background: #0f0f1a;
    }
    #test-screen-header {
        height: 1;
        width: 100%;
        background: #1a1a2e;
        color: #6688cc;
        content-align: center middle;
        text-style: bold;
    }
    #test-screen-container {
        height: 1fr;
        width: 100%;
        padding: 0 1;
    }
    #test-screen-view {
        height: 100%;
        width: 100%;
    }
    #test-footer-bar {
        height: 3;
        width: 100%;
        background: #1a1a2e;
        align: center middle;
        padding: 0 1;
    }
    #test-footer-bar Button {
        height: 1;
        min-width: 10;
        margin: 0 1;
        padding: 0 1;
        border: none;
        background: #22223b;
        color: #aaaaee;
    }
    #test-footer-bar Button:hover {
        background: #3b3b66;
        color: #ffffff;
    }
    #test-footer-bar Button:focus {
        border: tall #6688cc;
        background: #2563eb;
        color: #ffffff;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("🧪 DRAFT TEST RESULTS DASHBOARD", id="test-screen-header")
        with Vertical(id="test-screen-container"):
            yield TestPanel(id="test-screen-view")
        yield Horizontal(
            Button("[ Esc ] Back", id="btn-test-back"),
            Button("[ Tab ] Focus Log", id="btn-test-focus", variant="primary"),
            Button("[ Q ] Close", id="btn-test-close"),
            id="test-footer-bar",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id in ("btn-test-back", "btn-test-close"):
            self.action_pop_screen()
        elif btn_id == "btn-test-focus":
            try:
                self.query_one("#test-screen-view", TestPanel).log.focus()
            except Exception:
                pass

    def action_pop_screen(self) -> None:
        self.dismiss()


class GitScreen(Screen):
    """Full-screen interactive git workspace panel."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back to Cockpit"),
        Binding("q", "pop_screen", "Back to Cockpit"),
        Binding("r", "refresh_git", "Refresh"),
    ]

    DEFAULT_CSS = """
    GitScreen {
        layout: vertical;
        background: #0f0f1a;
    }
    #git-screen-header {
        height: 1;
        width: 100%;
        background: #1a1a2e;
        color: #6688cc;
        content-align: center middle;
        text-style: bold;
    }
    #git-screen-container {
        height: 1fr;
        width: 100%;
        padding: 0 1;
    }
    #git-screen-view {
        height: 100%;
        width: 100%;
    }
    #git-footer-bar {
        height: 3;
        width: 100%;
        background: #1a1a2e;
        align: center middle;
        padding: 0 1;
    }
    #git-footer-bar Button {
        height: 1;
        min-width: 10;
        margin: 0 1;
        padding: 0 1;
        border: none;
        background: #22223b;
        color: #aaaaee;
    }
    #git-footer-bar Button:hover {
        background: #3b3b66;
        color: #ffffff;
    }
    #git-footer-bar Button:focus {
        border: tall #6688cc;
        background: #2563eb;
        color: #ffffff;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("🐙 DRAFT GIT WORKSPACE & STATUS", id="git-screen-header")
        with Vertical(id="git-screen-container"):
            yield GitPanel(id="git-screen-view")
        yield Horizontal(
            Button("[ Esc ] Back", id="btn-git-back"),
            Button("[ R ] Refresh Status", id="btn-git-refresh", variant="primary"),
            Button("[ Tab ] Focus Log", id="btn-git-focus"),
            Button("[ Q ] Close", id="btn-git-close"),
            id="git-footer-bar",
        )

    def on_mount(self) -> None:
        self.action_refresh_git()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id in ("btn-git-back", "btn-git-close"):
            self.action_pop_screen()
        elif btn_id == "btn-git-refresh":
            self.action_refresh_git()
        elif btn_id == "btn-git-focus":
            try:
                self.query_one("#git-screen-view", GitPanel).log.focus()
            except Exception:
                pass

    def action_pop_screen(self) -> None:
        self.dismiss()

    def action_refresh_git(self) -> None:
        try:
            self.query_one("#git-screen-view", GitPanel).refresh_git_info()
        except Exception:
            pass


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
