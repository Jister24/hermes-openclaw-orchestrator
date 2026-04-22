"""
EventBus — publish-subscribe event bus for dashboard integration.

Provides a central event hub that decouples the OrchestrationEngine
from the SSE/WebSocket pushing infrastructure.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, AsyncGenerator

import structlog

logger = structlog.get_logger(__name__)


class DashboardEvent(str, Enum):
    """All event types that the dashboard frontend subscribes to."""
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"

    SUBTASK_STARTED = "subtask_started"
    SUBTASK_COMPLETED = "subtask_completed"
    SUBTASK_FAILED = "subtask_failed"

    AGENT_THINKING = "agent_thinking"
    STREAM_CHUNK = "stream_chunk"
    STREAM_DONE = "stream_done"

    HEARTBEAT = "heartbeat"


@dataclass
class DashboardEventPayload:
    """A single dashboard event with metadata."""
    event: DashboardEvent
    task_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_json(self) -> str:
        return json.dumps({
            "event": self.event.value,
            "taskId": self.task_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }, ensure_ascii=False)


class EventBus:
    """
    Publish-subscribe event bus for dashboard integration.

    OrchestrationEngine calls `event_bus.publish(payload)` to emit
    lifecycle events.  SSE endpoints and WebSocket handlers consume
    from `event_bus.listen()`.
    """

    def __init__(self) -> None:
        self._subscribers: dict[DashboardEvent, list[Callable[..., Any]]] = {}
        self._global_queue: asyncio.Queue[DashboardEventPayload] = asyncio.Queue()
        # Track connected SSE queues for broadcasting
        self._sse_queues: set[asyncio.Queue[DashboardEventPayload]] = set()
        # WebSocket manager reference (set by api/websocket.py)
        self._ws_manager: Any = None

    def set_ws_manager(self, manager: Any) -> None:
        """Inject the WebSocket connection manager."""
        self._ws_manager = manager

    def subscribe(self, event: DashboardEvent, handler: Callable[..., Any]) -> None:
        """Register a handler for a specific event type."""
        self._subscribers.setdefault(event, []).append(handler)

    def subscriber(self, event: DashboardEvent) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator-based subscription."""
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.subscribe(event, fn)
            return fn
        return decorator

    async def publish(self, payload: DashboardEventPayload) -> None:
        """
        Publish an event:
        1. Deliver to registered synchronous/asynchronous handlers
        2. Put in global queue for SSE consumers
        3. Broadcast to all WebSocket clients
        """
        # Deliver to typed subscribers
        for handler in self._subscribers.get(payload.event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    handler(payload)
            except Exception as exc:
                logger.warning(
                    "event_handler_error",
                    event=payload.event.value,
                    error=str(exc),
                )

        # Put in global queue for SSE listeners
        await self._global_queue.put(payload)

        # Broadcast to all WebSocket clients
        if self._ws_manager is not None:
            try:
                await self._ws_manager.broadcast(payload.to_json())
            except Exception as exc:
                logger.warning("ws_broadcast_error", error=str(exc))

    async def publish_nowait(self, payload: DashboardEventPayload) -> None:
        """Non-await version for fire-and-forget in sync contexts."""
        asyncio.create_task(self.publish(payload))

    def add_sse_queue(self, queue: asyncio.Queue[DashboardEventPayload]) -> None:
        """Register an SSE client's queue so it receives events."""
        self._sse_queues.add(queue)

    def remove_sse_queue(self, queue: asyncio.Queue[DashboardEventPayload]) -> None:
        """Unregister an SSE client's queue."""
        self._sse_queues.discard(queue)

    async def listen(self) -> AsyncGenerator[DashboardEventPayload, None]:
        """
        Async iterator that yields events as they arrive.
        Used by SSE endpoint to stream events to clients.
        """
        while True:
            payload = await self._global_queue.get()
            yield payload

    async def broadcast_to_sse(self, payload: DashboardEventPayload) -> None:
        """Push an event to all registered SSE queues."""
        for queue in list(self._sse_queues):
            try:
                # Non-blocking put; remove queue if full (client disconnected)
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    self._sse_queues.discard(queue)
            except Exception as exc:
                logger.warning("sse_broadcast_error", error=str(exc))
                self._sse_queues.discard(queue)

    # ── Convenience factory methods ────────────────────────────────

    async def emit_task_started(self, task_id: str, plan: list[dict[str, str]]) -> None:
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.TASK_STARTED,
            task_id=task_id,
            data={"taskId": task_id, "plan": plan},
        ))

    async def emit_subtask_started(
        self, task_id: str, subtask_id: str, agent_id: str, description: str
    ) -> None:
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.SUBTASK_STARTED,
            task_id=task_id,
            data={"subtaskId": subtask_id, "agentId": agent_id, "description": description},
        ))

    async def emit_subtask_completed(
        self, task_id: str, subtask_id: str, agent_id: str, result: Any = None
    ) -> None:
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.SUBTASK_COMPLETED,
            task_id=task_id,
            data={"subtaskId": subtask_id, "agentId": agent_id, "result": result},
        ))

    async def emit_subtask_failed(
        self, task_id: str, subtask_id: str, agent_id: str, error: str
    ) -> None:
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.SUBTASK_FAILED,
            task_id=task_id,
            data={"subtaskId": subtask_id, "agentId": agent_id, "error": error},
        ))

    async def emit_task_completed(self, task_id: str, results: Any = None) -> None:
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.TASK_COMPLETED,
            task_id=task_id,
            data={"taskId": task_id, "results": results},
        ))

    async def emit_task_failed(self, task_id: str, error: str) -> None:
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.TASK_FAILED,
            task_id=task_id,
            data={"taskId": task_id, "error": error},
        ))

    async def emit_agent_thinking(self, task_id: str, subtask_id: str) -> None:
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.AGENT_THINKING,
            task_id=task_id,
            data={"subtaskId": subtask_id},
        ))

    async def emit_stream_chunk(
        self, task_id: str, subtask_id: str, agent_id: str, chunk: str
    ) -> None:
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.STREAM_CHUNK,
            task_id=task_id,
            data={"subtaskId": subtask_id, "agentId": agent_id, "chunk": chunk},
        ))

    async def emit_stream_done(self, task_id: str, subtask_id: str) -> None:
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.STREAM_DONE,
            task_id=task_id,
            data={"subtaskId": subtask_id},
        ))

    async def emit_heartbeat(self) -> None:
        """Emit a heartbeat event for connection keep-alive."""
        await self.publish(DashboardEventPayload(
            event=DashboardEvent.HEARTBEAT,
            task_id="",
            data={},
        ))


# ── Global singleton (created in api/main.py lifespan) ────────────

_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    if _event_bus is None:
        raise RuntimeError("EventBus not initialized — call create_event_bus() first")
    return _event_bus


def create_event_bus() -> EventBus:
    global _event_bus
    _event_bus = EventBus()
    return _event_bus
