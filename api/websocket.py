"""
WebSocket connection manager for the dashboard.

Handles bidirectional real-time communication with the frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Set

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = structlog.get_logger(__name__)

router = APIRouter()


class WSConnectionManager:
    """
    Manages all active WebSocket connections to the dashboard.

    Each connected browser tab gets its own WebSocket connection.
    """

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("ws_client_connected", total=len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self._connections.discard(ws)
        logger.info("ws_client_disconnected", total=len(self._connections))

    async def broadcast(self, message: str | dict) -> None:
        """
        Send a message to all connected clients.
        Silently drops clients that have disconnected.
        """
        if isinstance(message, dict):
            message = json.dumps(message, ensure_ascii=False)

        async with self._lock:
            dead = set()
            for ws in self._connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.add(ws)
            # Clean up dead connections
            self._connections -= dead

    async def send_personal(self, ws: WebSocket, message: str | dict) -> None:
        """Send a message to a specific client."""
        if isinstance(message, dict):
            message = json.dumps(message, ensure_ascii=False)
        try:
            await ws.send_text(message)
        except Exception:
            self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Singleton instance
ws_manager = WSConnectionManager()


@router.websocket("/ws/dashboard")
async def dashboard_websocket(ws: WebSocket) -> None:
    """
    Main WebSocket endpoint for the dashboard.

    Protocol:
    - Client → Server:  { "type": "subscribe", "taskId": "..." }
                       { "type": "ping" }
    - Server → Client: JSON string matching WsServerMessage schema
    """
    await ws_manager.connect(ws)
    try:
        while True:
            try:
                raw = await ws.receive_text()
                msg: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws_manager.send_personal(ws, json.dumps({"type": "pong"}))

            elif msg_type == "subscribe":
                task_id = msg.get("taskId")
                logger.debug("ws_client_subscribe", taskId=task_id)
                await ws.send_text(json.dumps({
                    "type": "subscribed",
                    "taskId": task_id,
                    "wsStatus": "connected",
                }, ensure_ascii=False))

            elif msg_type == "unsubscribe":
                logger.debug("ws_client_unsubscribe", taskId=msg.get("taskId"))

            else:
                logger.debug("ws_unknown_message_type", msgType=msg_type)

    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
        logger.info("ws_client_disconnected_graceful")
    except Exception as exc:
        logger.error("ws_unexpected_error", error=str(exc))
        ws_manager.disconnect(ws)
