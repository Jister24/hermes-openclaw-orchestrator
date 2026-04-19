"""OpenClaw sub-agent integration via Gateway WebSocket RPC."""

from __future__ import annotations

import asyncio
import json
import platform
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
import websockets

from shared.types import AgentInfo, SubTask, TaskStatus

logger = structlog.get_logger(__name__)


class GatewayError(Exception):
    """Gateway RPC error."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.code = code


class GatewayWsClient:
    """
    WebSocket RPC client for OpenClaw Gateway.

    Protocol:
    - Server sends event: {"type": "event", "event": "connect.challenge", "payload": {"nonce": "..."}}
    - Client sends: {"type": "req", "id": "<uuid>", "method": "connect", "params": {...}}
    - Server sends: {"type": "res", "id": "<uuid>", "ok": true, "payload": {...}}
      OR as an event: {"type": "event", "event": "<method>", "payload": {...}}
    - Subsequent RPC calls may receive responses as events with method name as event type
    """

    # Valid client IDs (from gateway protocol)
    VALID_CLIENT_IDS = frozenset([
        "webchat-ui", "openclaw-control-ui", "openclaw-tui", "webchat", "cli",
        "gateway-client", "openclaw-macos", "openclaw-ios", "openclaw-android",
        "node-host", "test", "fingerprint", "openclaw-probe",
    ])

    def __init__(
        self,
        gateway_url: str = "ws://127.0.0.1:18789",
        auth_token: Optional[str] = None,
        request_timeout: float = 300.0,
        client_id: str = "gateway-client",
        client_role: str = "operator",
    ):
        # Convert HTTP URL to WebSocket URL
        if gateway_url.startswith("http://"):
            ws_url = gateway_url.replace("http://", "ws://")
        elif gateway_url.startswith("https://"):
            ws_url = gateway_url.replace("https://", "wss://")
        else:
            ws_url = gateway_url
        if not ws_url.startswith("ws"):
            ws_url = f"ws://{ws_url}"
        self.gateway_url = ws_url.rstrip("/")
        self.auth_token = auth_token
        self.request_timeout = request_timeout
        self.client_id = client_id if client_id in self.VALID_CLIENT_IDS else "gateway-client"
        self.client_role = client_role
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending: dict[str, asyncio.Future] = {}
        self._nonce: Optional[str] = None
        self._connected = False
        self._auth_completed = False
        self._auth_future: Optional[asyncio.Future] = None
        self._connect_req_id: Optional[str] = None
        self._protocol: int = 3

    async def connect(self) -> None:
        """Establish WebSocket connection (no auth — auth is done separately in connect_auth)."""
        self._ws = await websockets.connect(
            self.gateway_url,
            open_timeout=10,
            close_timeout=5,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        self._connected = True
        logger.info("websocket_connected", gateway=self.gateway_url)

    async def connect_auth(self) -> None:
        """
        Wait for and respond to the connect.challenge from the gateway.
        Call this after connect(). The reader loop handles the challenge
        and sets _auth_completed when done.
        """
        # Create a future for auth completion
        loop = asyncio.get_event_loop()
        self._auth_future = loop.create_future()
        
        try:
            # Wait for auth future with timeout
            await asyncio.wait_for(self._auth_future, timeout=10)
            self._auth_completed = True
        except asyncio.TimeoutError:
            raise GatewayError("Auth timeout")
        finally:
            self._auth_future = None

    async def _read_loop(self) -> None:
        """Read messages from WebSocket and dispatch to waiting futures."""
        if not self._ws:
            return
        try:
            async for msg in self._ws:
                try:
                    data = json.loads(msg)
                except json.JSONDecodeError:
                    logger.warning("invalid_json_from_gateway", raw=msg[:200])
                    continue

                msg_type = data.get("type")
                msg_id = data.get("id")
                event_name = data.get("event")

                # ── connect.challenge ────────────────────────────────────────
                if msg_type == "event" and event_name == "connect.challenge":
                    self._nonce = data.get("payload", {}).get("nonce")
                    logger.debug("received_connect_challenge", nonce=self._nonce)
                    await self._send_connect_request()
                    continue

                # ── Direct response (id-based) ─────────────────────────────
                if msg_type == "res" and msg_id:
                    # Handle connect response specially
                    if hasattr(self, '_connect_req_id') and msg_id == self._connect_req_id:
                        logger.info("connect_response_received", req_id=msg_id, ok=data.get("ok"), error=data.get("error"))
                        if data.get("ok"):
                            self._auth_completed = True
                            logger.info("gateway_auth_completed", protocol=data.get("payload", {}).get("protocol"))
                            if self._auth_future and not self._auth_future.done():
                                self._auth_future.set_result(True)
                        else:
                            error = data.get("error", {})
                            err_msg = GatewayError(
                                error.get("message", "Connect failed"),
                                error.get("code"),
                            )
                            if self._auth_future and not self._auth_future.done():
                                self._auth_future.set_exception(err_msg)
                        continue
                    
                    # Handle other pending responses
                    if msg_id in self._pending:
                        future = self._pending.pop(msg_id)
                        if data.get("ok"):
                            future.set_result(data.get("payload", {}))
                        else:
                            error = data.get("error", {})
                            future.set_exception(
                                GatewayError(
                                    error.get("message", "Unknown error"),
                                    error.get("code"),
                                )
                            )
                        continue

                # ── Method-result event (server pushes result as event) ────
                # Many methods return their result as an event with the method
                # name as the event type. We check pending by method name.
                if msg_type == "event" and event_name:
                    # Find a pending future waiting for this method
                    for key, future in list(self._pending.items()):
                        # Key format: "method:<name>" for event-based responses
                        if key == f"method:{event_name}":
                            self._pending.pop(key)
                            # Some event payloads wrap the result directly
                            payload = data.get("payload", {})
                            # If payload contains method-specific fields, use it directly
                            if payload or isinstance(payload, dict):
                                future.set_result(payload)
                            else:
                                future.set_result(data)
                            break
                    continue

                # ── Other events ─────────────────────────────────────────────
                if msg_type == "event":
                    logger.debug(
                        "gateway_event",
                        event_name=event_name,
                        event_data=data.get("payload"),
                    )
                    continue

                # ── Unknown ─────────────────────────────────────────────────
                logger.debug("unhandled_ws_message", msg_type=msg_type, msg_id=msg_id)

        except websockets.exceptions.ConnectionClosed:
            logger.info("websocket_connection_closed")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("ws_read_error", error=str(e))

    async def _send_connect_request(self) -> None:
        """Send the connect request after receiving the challenge."""
        if not self._ws or not self._nonce:
            raise GatewayError("Cannot send connect: not connected or no nonce")

        req_id = str(uuid.uuid4())
        connect_params = {
            "minProtocol": 1,
            "maxProtocol": self._protocol,
            "client": {
                "id": self.client_id,
                "displayName": "hermes-orchestrator",
                "version": "1.0.0",
                "platform": platform.system().lower(),
                "mode": "backend",
            },
            "role": self.client_role,
            "scopes": ["operator.read", "operator.write"],
        }

        if self.auth_token:
            connect_params["auth"] = {"password": self.auth_token}

        # Store the request ID for matching the response
        self._connect_req_id = req_id

        await self._ws.send(json.dumps({
            "type": "req",
            "id": req_id,
            "method": "connect",
            "params": connect_params,
        }))

        logger.debug("connect_request_sent", req_id=req_id)

    async def _send_raw(self, data: dict) -> None:
        """Send a raw JSON message."""
        if not self._ws:
            raise GatewayError("Not connected")
        await self._ws.send(json.dumps(data))

    async def rpc(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """
        Send an RPC request and wait for response.

        Handles two response patterns:
        1. Direct:  {"type": "res", "id": "<uuid>", "ok": true, "payload": {...}}
        2. Event:   {"type": "event", "event": "<method>", "payload": {...}}

        Args:
            method: RPC method name (e.g., "sessions.create")
            params: Method parameters
            timeout: Request timeout in seconds

        Returns:
            Response payload

        Raises:
            GatewayError: On RPC error or timeout
        """
        if not self._ws or not self._connected:
            raise GatewayError("Not connected to gateway")

        if not self._auth_completed:
            raise GatewayError("Gateway auth not completed")

        req_id = str(uuid.uuid4())
        id_future: asyncio.Future = asyncio.get_event_loop().create_future()
        # Also register by method name for event-based responses
        method_future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = id_future
        self._pending[f"method:{method}"] = method_future

        request = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": params or {},
        }

        try:
            await self._send_raw(request)

            # Wait for whichever comes first
            done, pending = await asyncio.wait(
                [id_future, method_future],
                timeout=timeout or self.request_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel the other
            for t in pending:
                t.cancel()
                self._pending.pop(req_id, None)
                self._pending.pop(f"method:{method}", None)

            if id_future in done:
                return id_future.result()
            elif method_future in done:
                return method_future.result()
            else:
                raise GatewayError(f"Gateway request timeout for {method}")

        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            self._pending.pop(f"method:{method}", None)
            raise GatewayError(f"Gateway request timeout for {method}")
        except GatewayError:
            self._pending.pop(req_id, None)
            self._pending.pop(f"method:{method}", None)
            raise
        except Exception as e:
            self._pending.pop(req_id, None)
            self._pending.pop(f"method:{method}", None)
            raise GatewayError(f"Gateway request failed for {method}: {e}")

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._connected = False
        self._auth_completed = False
        for future in self._pending.values():
            future.cancel()
        self._pending.clear()
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None


class OpenClawAgentClient:
    """
    Client for interacting with OpenClaw sub-agents via Gateway WebSocket RPC.

    Note: OpenClaw Gateway does NOT expose a sessions/spawn REST endpoint.
    Sub-agents are spawned internally via the sessions_spawn tool (called by
    the main agent's LLM). This client uses sessions.create + sessions.send
    to create sessions for sub-agents and communicate with them.
    """

    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:18789",
        auth_token: Optional[str] = None,
        timeout: int = 300,
    ):
        self.gateway_url = gateway_url
        self.auth_token = auth_token
        self.timeout = timeout
        self._ws_client: Optional[GatewayWsClient] = None

    async def __aenter__(self) -> "OpenClawAgentClient":
        self._ws_client = GatewayWsClient(
            gateway_url=self.gateway_url,
            auth_token=self.auth_token,
            request_timeout=float(self.timeout),
        )
        await self._ws_client.connect()
        await self._ws_client.connect_auth()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._ws_client:
            await self._ws_client.close()
            self._ws_client = None

    # -------------------------------------------------------------------------
    # Gateway Health & Info
    # -------------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if OpenClaw Gateway is reachable."""
        try:
            await self._ws_client.rpc("health", {}, timeout=5)
            return True
        except Exception:
            return False

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents from OpenClaw."""
        try:
            result = await self._ws_client.rpc("agents.list", {})
            agents = result.get("agents", []) if result else []
            return agents
        except Exception as e:
            logger.warning("list_agents_failed", error=str(e))
            return []

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions."""
        try:
            result = await self._ws_client.rpc("sessions.list", {})
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.warning("list_sessions_failed", error=str(e))
            return []

    async def close(self) -> None:
        """Close the client connection."""
        if self._ws_client:
            await self._ws_client.close()
            self._ws_client = None

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    async def spawn_subagent(
        self,
        agent_id: str,
        message: str,
        context: Optional[dict[str, Any]] = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """
        Spawn a subagent task via OpenClaw Gateway RPC.

        Creates a session for the target agent and sends the task message.
        The session is created with the agent_id, and the message is sent
        via sessions.send to trigger the subagent's response.

        Returns dict with sessionKey and response.
        """
        logger.info(
            "spawning_subagent",
            agent_id=agent_id,
            task_preview=message[:100],
        )

        extra_context: dict[str, Any] = {}
        if context:
            extra_context["context"] = context

        try:
            create_params: dict[str, Any] = {
                "agentId": agent_id,
                "message": message,
                **extra_context,
            }

            create_result = await self._ws_client.rpc(
                "sessions.create",
                create_params,
                timeout=min(timeout, self.timeout),
            )

            session_key = create_result.get("key")
            if not session_key:
                raise GatewayError(f"sessions.create returned no session key: {create_result}")

            run_started = create_result.get("runStarted", False)
            if not run_started:
                send_result = await self._ws_client.rpc(
                    "sessions.send",
                    {
                        "key": session_key,
                        "message": message,
                    },
                    timeout=min(timeout, self.timeout),
                )
                return {
                    "sessionKey": session_key,
                    "runStarted": True,
                    "response": send_result,
                }

            logger.info(
                "subagent_spawned",
                agent_id=agent_id,
                session_key=session_key,
            )

            return {
                "sessionKey": session_key,
                "runStarted": create_result.get("runStarted", True),
                "response": create_result,
            }

        except GatewayError as e:
            logger.error(
                "spawn_failed",
                agent_id=agent_id,
                error=str(e),
            )
            raise RuntimeError(f"Failed to spawn agent {agent_id}: {e}")

    async def send_to_session(
        self,
        session_key: str,
        message: str,
    ) -> dict[str, Any]:
        """Send a follow-up message to an existing session."""
        try:
            result = await self._ws_client.rpc(
                "sessions.send",
                {
                    "key": session_key,
                    "message": message,
                },
                timeout=float(self.timeout),
            )
            return result
        except GatewayError as e:
            raise RuntimeError(f"Session send failed: {e}")

    async def get_session_history(
        self,
        session_key: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get recent messages from a session."""
        try:
            result = await self._ws_client.rpc(
                "sessions.get",
                {
                    "key": session_key,
                    "limit": limit,
                },
                timeout=10,
            )
            return result.get("messages", []) if result else []
        except Exception:
            return []

    async def get_session_status(self, session_key: str) -> dict[str, Any]:
        """Get current session status."""
        try:
            result = await self._ws_client.rpc(
                "sessions.get",
                {"key": session_key},
                timeout=10,
            )
            return result or {"status": "unknown"}
        except Exception:
            return {"status": "unknown"}

    async def patch_session(
        self,
        session_key: str,
        **kwargs,
    ) -> dict[str, Any]:
        """Patch session metadata."""
        kwargs["key"] = session_key
        return await self._ws_client.rpc("sessions.patch", kwargs, timeout=10)

    async def delete_session(self, session_key: str) -> bool:
        """Delete a session."""
        try:
            await self._ws_client.rpc(
                "sessions.delete",
                {"key": session_key},
                timeout=10,
            )
            return True
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Task Execution Wrapper
    # -------------------------------------------------------------------------

    async def execute_subtask(
        self,
        agent_info: AgentInfo,
        subtask: SubTask,
    ) -> dict[str, Any]:
        """Execute a single subtask via the appropriate OpenClaw sub-agent."""
        start_time = datetime.utcnow()

        try:
            task_prompt = self._build_task_prompt(subtask)

            result = await self.spawn_subagent(
                agent_id=agent_info.agent_id,
                message=task_prompt,
                context=subtask.payload,
                timeout=min(subtask.max_retries * 150, self.timeout),
            )

            duration = (datetime.utcnow() - start_time).total_seconds()

            return {
                "task_id": subtask.id,
                "agent_id": agent_info.agent_id,
                "status": TaskStatus.COMPLETED.value,
                "session_key": result.get("sessionKey"),
                "result": result,
                "duration_seconds": duration,
                "error": None,
            }

        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(
                "subtask_failed",
                task_id=subtask.id,
                agent_id=agent_info.agent_id,
                error=str(e),
            )
            return {
                "task_id": subtask.id,
                "agent_id": agent_info.agent_id,
                "status": TaskStatus.FAILED.value,
                "result": None,
                "duration_seconds": duration,
                "error": str(e),
            }

    @staticmethod
    def _build_task_prompt(subtask: SubTask) -> str:
        """Build a detailed task prompt from a SubTask."""
        prompt_parts = [
            f"# Sub-Task: {subtask.description}",
            f"Task ID: {subtask.id}",
        ]

        if subtask.payload:
            prompt_parts.append("\n## Context:")
            for k, v in subtask.payload.items():
                prompt_parts.append(f"- **{k}**: {v}")

        prompt_parts.append(
            "\nPlease execute this task and return the results. "
            "Include: (1) what you did, (2) key findings, (3) any artifacts produced."
        )

        return "\n".join(prompt_parts)


class OpenClawConnector:
    """
    High-level connector that manages the connection to OpenClaw Gateway
    and provides agent registry integration.
    """

    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:18789",
        auth_token: Optional[str] = None,
    ):
        self.gateway_url = gateway_url
        self.auth_token = auth_token
        self._client: Optional[OpenClawAgentClient] = None

    async def _ensure_client(self) -> None:
        """Lazily create the underlying WebSocket client."""
        if self._client is None:
            inner = OpenClawAgentClient(self.gateway_url, self.auth_token)
            await inner.__aenter__()
            self._client = inner

    async def initialize(self) -> bool:
        """Initialize connection (call at startup)."""
        try:
            await self._ensure_client()
            health = await self._client.health_check() if self._client else False
            if health:
                logger.info("connected_to_openclaw", gateway=self.gateway_url)
            return health
        except Exception as e:
            logger.error("openclaw_connection_failed", error=str(e))
            return False

    async def close(self) -> None:
        """Close the connection (call at shutdown)."""
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def execute_subtask(
        self, agent_info: AgentInfo, subtask: SubTask
    ) -> dict[str, Any]:
        """Execute a subtask using the registered agent info."""
        await self._ensure_client()
        return await self._client.execute_subtask(agent_info, subtask)

    async def health_check(self) -> bool:
        """Check gateway health."""
        if not self._client:
            return False
        return await self._client.health_check()

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents from OpenClaw."""
        await self._ensure_client()
        if not self._client:
            return []
        return await self._client.list_agents()
