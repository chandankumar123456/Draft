"""Draft Developer Cockpit widgets package.

Re-exports every widget so consumers keep using
``from tui.widgets import ...`` regardless of the module layout.
"""

from __future__ import annotations

from tui.widgets.common import SelectableRichLog
from tui.widgets.inspector import ToolInspector
from tui.widgets.panels import (
    ApprovalModal,
    DiffView,
    FooterBar,
    GitPanel,
    ProjectExplorer,
    PromptInput,
    TestPanel,
    TimelineView,
)
from tui.widgets.state import AgentStatePanel, StatusHeader
from tui.widgets.workspace import AgentWorkspace

__all__ = [
    "AgentStatePanel",
    "AgentWorkspace",
    "ApprovalModal",
    "DiffView",
    "FooterBar",
    "GitPanel",
    "ProjectExplorer",
    "PromptInput",
    "SelectableRichLog",
    "StatusHeader",
    "TestPanel",
    "TimelineView",
    "ToolInspector",
]