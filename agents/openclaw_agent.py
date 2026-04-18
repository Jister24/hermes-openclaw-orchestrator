"""OpenClaw sub-agent integration via Gateway API."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from shared.types import AgentInfo, SubTask, TaskStatus

logger = structlog.get_logger(__name__)


class OpenClawAgentClient:
    """Client for interacting with OpenClaw sub-agents via Gateway API."""

    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:18789",
        auth_token: Optional[str] = None,
        timeout: int = 300,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "OpenClawAgentClient":
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(self.timeout),
            base_url=self.gateway_url,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    # -------------------------------------------------------------------------
    # Gateway Health & Info
    # -------------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if OpenClaw Gateway is reachable."""
        try:
            resp = await self._client.get("/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents from OpenClaw."""
        try:
            resp = await self._client.get("/api/agents")
            if resp.status_code == 200:
                return resp.json().get("agents", [])
            return []
        except Exception as e:
            logger.warning("list_agents_failed", error=str(e))
            return []

    async def close(self) -> None:
        """Close the client connection."""
        if self._client:
            await self._client.aclose()

    # -------------------------------------------------------------------------
    # Session Management
    # -------------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
    )
    async def spawn_subagent(
        self,
        agent_id: str,
        message: str,
        context: Optional[dict[str, Any]] = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """
        Spawn a subagent task via OpenClaw sessions_spawn API.
        Returns the session key and initial response.
        """
        payload = {
            "agentId": agent_id,
            "task": message,
            "runtime": "subagent",
            "mode": "run",
            "timeoutSeconds": timeout,
        }
        if context:
            payload["context"] = context

        logger.info(
            "spawning_subagent",
            agent_id=agent_id,
            task_preview=message[:100],
        )

        resp = await self._client.post(
            "/api/sessions/spawn",
            json=payload,
        )

        if resp.status_code not in (200, 201):
            error_text = resp.text
            logger.error(
                "spawn_failed",
                agent_id=agent_id,
                status=resp.status_code,
                error=error_text,
            )
            raise RuntimeError(
                f"Failed to spawn agent {agent_id}: {resp.status_code} {error_text}"
            )

        result = resp.json()
        session_key = result.get("sessionKey")
        logger.info("subagent_spawned", agent_id=agent_id, session_key=session_key)
        return result

    async def send_to_session(
        self,
        session_key: str,
        message: str,
    ) -> dict[str, Any]:
        """Send a follow-up message to an existing session."""
        resp = await self._client.post(
            f"/api/sessions/{session_key}/send",
            json={"message": message},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Session send failed: {resp.status_code} {resp.text}")
        return resp.json()

    async def get_session_history(
        self,
        session_key: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get recent messages from a session."""
        resp = await self._client.get(
            f"/api/sessions/{session_key}/history",
            params={"limit": limit},
        )
        if resp.status_code == 200:
            return resp.json().get("messages", [])
        return []

    async def get_session_status(self, session_key: str) -> dict[str, Any]:
        """Get current session status."""
        resp = await self._client.get(f"/api/sessions/{session_key}/status")
        if resp.status_code == 200:
            return resp.json()
        return {"status": "unknown"}

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
            # Build the task prompt
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
        """Lazily create the underlying HTTP client."""
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
