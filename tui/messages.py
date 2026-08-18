"""Textual message types bridging agent runtime events to the TUI.

These are Textual ``Message`` subclasses that are posted from the
event-consumer worker into the Textual widget tree.  Widgets handle
them via ``on_<message_name>`` methods or ``@on(...)`` decorators.
"""

from __future__ import annotations

from textual.message import Message

# Import the runtime event hierarchy so messages can carry typed events
import sys
import os

# Add agent directory to path for imports
_agent_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"
)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

from events import RuntimeEvent, ApprovalRequested


class RuntimeEventReceived(Message):
    """Wraps any RuntimeEvent for the Textual message bus.

    Posted by the event-consumer worker whenever a new event
    arrives from the EventBus queue.
    """

    def __init__(self, event: RuntimeEvent) -> None:
        super().__init__()
        self.event = event


class AgentStatusChanged(Message):
    """Posted when the agent's status changes."""

    def __init__(self, status: str, phase: str = "") -> None:
        super().__init__()
        self.status = status
        self.phase = phase


class ApprovalNeeded(Message):
    """Posted when a tool call requires human approval."""

    def __init__(self, event: ApprovalRequested) -> None:
        super().__init__()
        self.approval_event = event


class PromptSubmitted(Message):
    """Posted when the user submits a prompt."""

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt


class FileSelected(Message):
    """Posted when the user selects a file in the project explorer."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
