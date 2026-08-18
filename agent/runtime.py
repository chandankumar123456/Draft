"""Agent runtime for Draft.

Encapsulates the Azure agent lifecycle, conversation management, and
the response → tool-call → result loop.  The runtime emits structured
events through the ``EventBus`` instead of printing to stdout, making
it possible to drive the TUI, logging, or automated tests from the
same execution path.

The runtime is designed to run in a background thread (via Textual
workers) while the TUI remains responsive on the main thread.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from azure.ai.projects.models import PromptAgentDefinition, WebSearchTool
from openai.types.responses.response_input_param import (
    FunctionCallOutput,
    ResponseInputParam,
)

from credential import get_openai_client, get_project_client, save_config
from dispatcher import ToolDispatcher
from event_bus import EventBus
from events import (
    AgentCancelled,
    AgentCompleted,
    AgentFailed,
    AgentIterationStarted,
    AgentMessage,
    AgentMessageChunk,
    AgentPhase,
    AgentPhaseChanged,
    AgentStarted,
    AgentState,
    AgentStatus,
    SystemMessage,
    UserMessage,
)
from instructions import instructions
from tools.tools import ALL_TOOLS

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Draft agent runtime.

    Parameters
    ----------
    event_bus : EventBus
        The event bus to emit events on.
    model : str | None
        Model deployment name.  Read from ``MODEL_DEPLOYMENT``
        environment variable if not provided.
    endpoint : str | None
        Project endpoint URL. Read from ``PROJECT_ENDPOINT``
        environment variable if not provided.
    approval_enabled : bool
        Whether risky tools require human approval.
    """

    def __init__(
        self,
        event_bus: EventBus,
        model: str | None = None,
        endpoint: str | None = None,
        approval_enabled: bool = False,
    ) -> None:
        self.event_bus = event_bus
        self.model = model or os.getenv("MODEL_DEPLOYMENT", "gpt-4.1-mini")
        self.endpoint = endpoint or os.getenv("PROJECT_ENDPOINT", "")
        self.dispatcher = ToolDispatcher(
            event_bus=event_bus,
            approval_enabled=approval_enabled,
        )

        # State
        self.state = AgentState()
        self._cancel_event = threading.Event()
        self._agent: Any = None
        self._conversation: Any = None
        self._input_list: ResponseInputParam = []

    # ── Lifecycle ─────────────────────────────────────────────

    def initialize(self) -> None:
        """Create the Azure agent and conversation.

        Must be called before ``run_task``.  Separated from
        ``__init__`` so the TUI can show a loading state.
        """
        p_client = get_project_client(self.endpoint)
        o_client = get_openai_client(self.endpoint)

        if p_client is None or o_client is None:
            self.event_bus.emit_threadsafe(SystemMessage(
                content="Azure AI project endpoint is not configured.",
                level="warning",
            ))
            return

        self.event_bus.emit_threadsafe(SystemMessage(
            content=f"Initializing Draft agent (model: {self.model})...",
            level="info",
        ))

        try:
            self._agent = p_client.agents.create_version(
                agent_name="Draft-Main-Agent",
                definition=PromptAgentDefinition(
                    model=self.model,
                    instructions=instructions,
                    tools=[WebSearchTool(), *ALL_TOOLS],
                ),
            )

            self._conversation = o_client.conversations.create()
            self._input_list = []

            self.event_bus.emit_threadsafe(SystemMessage(
                content="Draft agent initialized and ready.",
                level="info",
            ))
        except Exception as exc:
            self.event_bus.emit_threadsafe(SystemMessage(
                content=f"Failed to initialize agent: {exc}",
                level="error",
            ))
            raise

    def new_conversation(self) -> None:
        """Create a fresh conversation context."""
        o_client = get_openai_client(self.endpoint)
        if o_client is not None:
            try:
                self._conversation = o_client.conversations.create()
            except Exception:
                pass
        self._input_list = []
        self.state = AgentState()
        self.event_bus.emit_threadsafe(SystemMessage(
            content="Started a new conversation context.",
            level="info",
        ))

    def reconfigure(
        self, model: str | None = None, endpoint: str | None = None
    ) -> None:
        """Update model or endpoint at runtime and reinitialize."""
        if model:
            self.model = model
        if endpoint:
            self.endpoint = endpoint

        save_config(endpoint=self.endpoint, model=self.model)
        self.cleanup()
        self.initialize()

    def cleanup(self) -> None:
        """Delete the Azure agent.  Safe to call multiple times."""
        p_client = get_project_client(self.endpoint)
        if self._agent is not None and p_client is not None:
            try:
                p_client.agents.delete_version(
                    agent_name=self._agent.name,
                    agent_version=self._agent.version,
                )
                self.event_bus.emit_threadsafe(SystemMessage(
                    content="Agent cleaned up.",
                    level="info",
                ))
            except Exception as exc:
                logger.warning("Failed to cleanup agent: %s", exc)
            finally:
                self._agent = None

    def cancel(self) -> None:
        """Signal the runtime to stop the current task."""
        self._cancel_event.set()

    @property
    def is_running(self) -> bool:
        return self.state.status == AgentStatus.RUNNING

    # ── Main Execution Loop ───────────────────────────────────

    def run_task(self, prompt: str) -> None:
        """Execute a user prompt through the agent.

        This method is designed to be called from a worker thread.
        It blocks until the agent completes, fails, or is cancelled.
        Events are emitted via ``emit_threadsafe``.
        """
        if self._agent is None:
            self.event_bus.emit_threadsafe(AgentFailed(
                task=prompt,
                error="Agent not initialized. Call initialize() first.",
            ))
            return

        self._cancel_event.clear()

        # Update state
        self.state.status = AgentStatus.RUNNING
        self.state.task = prompt
        self.state.iteration = 0
        self.state.tool_call_count = 0
        self.state.files_read = 0
        self.state.files_modified = 0
        self.state.current_tool = ""
        self.state.phase = AgentPhase.UNDERSTANDING

        # Emit events
        self.event_bus.emit_threadsafe(UserMessage(content=prompt))
        self.event_bus.emit_threadsafe(AgentStarted(task=prompt))
        self.event_bus.emit_threadsafe(AgentPhaseChanged(
            phase=AgentPhase.UNDERSTANDING,
        ))

        try:
            self._execute_loop(prompt)
        except Exception as exc:
            self.state.status = AgentStatus.FAILED
            self.event_bus.emit_threadsafe(AgentFailed(
                task=prompt,
                error=str(exc),
            ))
            return

        if self._cancel_event.is_set():
            self.state.status = AgentStatus.CANCELLED
            self.event_bus.emit_threadsafe(AgentCancelled(task=prompt))
        else:
            self.state.status = AgentStatus.COMPLETED
            self.event_bus.emit_threadsafe(AgentCompleted(
                task=prompt,
                iterations=self.state.iteration,
                tool_calls=self.state.tool_call_count,
            ))

    def _emit_response_text(self, text: str) -> None:
        """Emit progressive chunks and the final AgentMessage."""
        if not text:
            return
        chunk_size = max(1, min(len(text), 24))
        accumulated = ""
        for i in range(0, len(text), chunk_size):
            if self._cancel_event.is_set():
                return
            delta = text[i : i + chunk_size]
            accumulated += delta
            self.event_bus.emit_threadsafe(
                AgentMessageChunk(delta=delta, accumulated=accumulated)
            )
        self.event_bus.emit_threadsafe(AgentMessage(content=text))

    def _execute_loop(self, prompt: str) -> None:
        """The core response → tool-call → result loop."""
        o_client = get_openai_client(self.endpoint)
        if o_client is None:
            raise RuntimeError("OpenAI client not initialized.")

        # Send user message to conversation
        o_client.conversations.items.create(
            conversation_id=self._conversation.id,
            items=[{
                "type": "message",
                "role": "user",
                "content": prompt,
            }],
        )

        # Get initial response
        response = o_client.responses.create(
            conversation=self._conversation.id,
            extra_body={
                "agent_reference": {
                    "name": self._agent.name,
                    "type": "agent_reference",
                },
            },
            input=self._input_list,
        )

        if getattr(response, "status", "") == "failed":
            raise RuntimeError(f"Response failed: {getattr(response, 'error', 'Unknown error')}")

        # Tool call loop — keep iterating while there are function calls
        max_iterations = 50  # Safety limit
        iteration = 0

        while iteration < max_iterations:
            if self._cancel_event.is_set():
                return

            iteration += 1
            self.state.iteration = iteration
            self.event_bus.emit_threadsafe(AgentIterationStarted(
                iteration=iteration,
            ))

            # Update phase based on iteration count
            if iteration == 1:
                self.event_bus.emit_threadsafe(AgentPhaseChanged(
                    phase=AgentPhase.INVESTIGATION,
                ))
                self.state.phase = AgentPhase.INVESTIGATION

            # Process function calls in this response
            tool_outputs: list[FunctionCallOutput] = []
            has_function_calls = False

            output_items = getattr(response, "output", []) or []
            for item in output_items:
                if self._cancel_event.is_set():
                    return

                if getattr(item, "type", "") != "function_call":
                    continue

                has_function_calls = True
                self.state.tool_call_count += 1

                # Parse arguments
                try:
                    arguments = json.loads(item.arguments)
                except (json.JSONDecodeError, AttributeError) as exc:
                    result = {
                        "success": False,
                        "data": None,
                        "message": None,
                        "error": f"Invalid JSON arguments for tool: {str(exc)}",
                    }
                    arguments = {}
                else:
                    # Update current tool state
                    self.state.current_tool = item.name
                    self.state.current_tool_args = arguments

                    # Dispatch through the event-emitting dispatcher
                    result = self.dispatcher.dispatch_sync(
                        tool_name=item.name,
                        call_id=item.call_id,
                        arguments=arguments,
                    )

                    # Update file counters
                    if isinstance(result, dict) and result.get("success"):
                        if item.name == "read_file":
                            self.state.files_read += 1
                        elif item.name in (
                            "write_file", "apply_patch", "insert_text",
                            "replace_text", "delete_lines",
                        ):
                            self.state.files_modified += 1

                # Serialize result
                try:
                    serialized = json.dumps(result)
                except (TypeError, ValueError):
                    result = {
                        "success": False,
                        "data": None,
                        "message": None,
                        "error": f"Tool '{getattr(item, 'name', '')}' produced a "
                                 f"non-serializable result",
                    }
                    serialized = json.dumps(result)

                tool_outputs.append(FunctionCallOutput(
                    type="function_call_output",
                    call_id=item.call_id,
                    output=serialized,
                ))

            # If no function calls, we're done
            if not has_function_calls:
                # Extract and emit the agent's text response
                if hasattr(response, "output_text") and response.output_text:
                    self._emit_response_text(response.output_text)
                break

            # Send tool results back and get next response
            self._input_list = tool_outputs
            self.state.current_tool = ""

            self.event_bus.emit_threadsafe(AgentPhaseChanged(
                phase=AgentPhase.EXECUTION,
            ))
            self.state.phase = AgentPhase.EXECUTION

            response = o_client.responses.create(
                input=self._input_list,
                conversation=self._conversation.id,
                extra_body={
                    "agent_reference": {
                        "name": self._agent.name,
                        "type": "agent_reference",
                    },
                },
            )

            if getattr(response, "status", "") == "failed":
                raise RuntimeError(f"Response failed: {getattr(response, 'error', 'Unknown error')}")

            # Check if this response is text-only (no more tool calls)
            output_items = getattr(response, "output", []) or []
            has_more_calls = any(
                getattr(item, "type", "") == "function_call" for item in output_items
            )
            if not has_more_calls:
                if hasattr(response, "output_text") and response.output_text:
                    self._emit_response_text(response.output_text)
                break

        # Clear input list for next task
        self._input_list = []
        self.state.current_tool = ""
