"""CLI entry point for the Draft agent.

This preserves the ability to run Draft from a plain terminal without
the TUI.  It uses the same ``AgentRuntime`` and ``EventBus`` that the
TUI uses, but subscribes a simple print-based handler.

Usage::

    cd agent
    python agent.py
"""

from __future__ import annotations

import asyncio
import sys

from event_bus import EventBus
from events import (
    AgentCompleted,
    AgentFailed,
    AgentMessage,
    RuntimeEvent,
    SystemMessage,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
    UserMessage,
)
from runtime import AgentRuntime


def _print_event(event: RuntimeEvent) -> None:
    """Print a runtime event to the terminal."""
    if isinstance(event, UserMessage):
        print(f"\n[USER] {event.content}")
    elif isinstance(event, AgentMessage):
        print(f"\n[AGENT] {event.content}")
    elif isinstance(event, ToolStarted):
        args_str = ", ".join(
            f"{k}={v!r}" for k, v in event.arguments.items()
        )
        print(f"  → {event.tool_name}({args_str})")
    elif isinstance(event, ToolCompleted):
        success = event.result.get("success", "?")
        print(f"  ✓ {event.tool_name} ({event.duration_seconds:.3f}s) "
              f"success={success}")
    elif isinstance(event, ToolFailed):
        print(f"  ✗ {event.tool_name}: {event.error}")
    elif isinstance(event, AgentCompleted):
        print(f"\n[DONE] Task completed ({event.iterations} iterations, "
              f"{event.tool_calls} tool calls)")
    elif isinstance(event, AgentFailed):
        print(f"\n[FAILED] {event.error}")
    elif isinstance(event, SystemMessage):
        print(f"[SYSTEM] {event.content}")


def main() -> None:
    """Run the Draft agent in CLI mode."""
    # Create event bus and runtime
    event_bus = EventBus()
    runtime = AgentRuntime(event_bus=event_bus)

    # Subscribe the print handler
    # (Using emit_threadsafe, events go to queues; we'll use a queue)
    queue = event_bus.create_queue()

    # Initialize the agent
    print("Initializing Draft agent...")
    try:
        runtime.initialize()
    except Exception as exc:
        print(f"Failed to initialize: {exc}")
        sys.exit(1)

    # Drain any initialization events
    while not queue.empty():
        try:
            event = queue.get_nowait()
            _print_event(event)
        except Exception:
            break

    print("\nDraft is ready. Type 'quit' to exit.\n")

    try:
        while True:
            user_input = input("User: ").strip()
            if user_input.lower() == "quit":
                break
            if not user_input:
                continue

            # Run the task (blocking, in current thread)
            runtime.run_task(user_input)

            # Drain and print all events
            while not queue.empty():
                try:
                    event = queue.get_nowait()
                    _print_event(event)
                except Exception:
                    break

    except KeyboardInterrupt:
        print("\n\nInterrupted.")
    finally:
        runtime.cleanup()
        print("Agent deleted. Goodbye.")


if __name__ == "__main__":
    main()