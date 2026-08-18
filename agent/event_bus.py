"""Async event bus for the Draft agent runtime.

Provides a simple publish/subscribe mechanism using asyncio.  The bus
supports two subscription styles:

1. **Callback subscriptions** — an async callable invoked for every
   event.  Good for logging or side-effects.

2. **Queue subscriptions** — returns an ``asyncio.Queue`` that
   receives events.  Good for the TUI's background worker which needs
   to pull events at its own pace.

Thread safety
─────────────
The ``emit`` method is safe to call from any thread.  When called from
a non-asyncio thread (e.g. the AgentRuntime worker thread), it uses
``call_soon_threadsafe`` to schedule delivery on the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

from events import RuntimeEvent

logger = logging.getLogger(__name__)

# Type alias for async event handlers
EventHandler = Callable[[RuntimeEvent], Awaitable[None]]


class EventBus:
    """Async pub/sub event bus.

    Usage::

        bus = EventBus()

        # Callback subscription
        async def on_event(event):
            print(event)
        bus.subscribe(on_event)

        # Queue subscription (for TUI workers)
        queue = bus.create_queue()

        # Emit from any thread
        await bus.emit(ToolStarted(tool_name="read_file"))

        # Or from a sync/thread context
        bus.emit_threadsafe(ToolStarted(tool_name="read_file"))
    """

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []
        self._queues: list[asyncio.Queue[RuntimeEvent]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._history: list[RuntimeEvent] = []

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind to an asyncio event loop for thread-safe emission."""
        self._loop = loop

    # ── Subscriptions ─────────────────────────────────────────

    def subscribe(self, handler: EventHandler) -> None:
        """Register an async callback for all events."""
        self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        try:
            self._handlers.remove(handler)
        except ValueError:
            pass

    def create_queue(self, maxsize: int = 1000) -> asyncio.Queue[RuntimeEvent]:
        """Create and register a queue subscription.

        Returns an ``asyncio.Queue`` that will receive all future
        events.  The TUI event-consumer worker reads from this queue.
        """
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=maxsize)
        self._queues.append(queue)
        return queue

    def remove_queue(self, queue: asyncio.Queue[RuntimeEvent]) -> None:
        """Remove a queue subscription."""
        try:
            self._queues.remove(queue)
        except ValueError:
            pass

    # ── Emission ──────────────────────────────────────────────

    async def emit(self, event: RuntimeEvent) -> None:
        """Emit an event to all subscribers (async context)."""
        self._history.append(event)

        # Deliver to queues (non-blocking put)
        for queue in self._queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Event queue full, dropping event: %s", type(event).__name__
                )

        # Deliver to handlers
        for handler in self._handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "Event handler %s failed for %s",
                    handler.__name__,
                    type(event).__name__,
                )

    def emit_threadsafe(self, event: RuntimeEvent) -> None:
        """Emit an event from a non-asyncio thread.

        Uses ``call_soon_threadsafe`` to schedule ``emit`` on the
        bound event loop.  Falls back to synchronous queue delivery
        if no loop is bound.
        """
        self._history.append(event)

        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                self._loop.create_task, self._deliver(event)
            )
        else:
            # Fallback: deliver to queues synchronously (handlers skipped)
            for queue in self._queues:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "Event queue full (threadsafe), dropping: %s",
                        type(event).__name__,
                    )

    async def _deliver(self, event: RuntimeEvent) -> None:
        """Internal: deliver event to queues and handlers."""
        for queue in self._queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Event queue full, dropping event: %s", type(event).__name__
                )

        for handler in self._handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "Event handler %s failed for %s",
                    handler.__name__,
                    type(event).__name__,
                )

    # ── History ───────────────────────────────────────────────

    @property
    def history(self) -> list[RuntimeEvent]:
        """All events emitted since creation (for timeline view)."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clear the event history."""
        self._history.clear()
