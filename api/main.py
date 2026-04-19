"""FastAPI application — orchestration API with SSE progress streaming."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sse_starlette import EventSourceResponse

from agents.cli_executor import CliExecutor
from agents.openclaw_agent import OpenClawConnector
from orchestrator.engine import OrchestrationEngine
from shared.types import (
    AgentCapability,
    AgentInfo,
    AgentRegistry,
    OrchestrationRequest,
    OrchestrationResponse,
    TaskStatus,
    TaskStatusResponse,
)

import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Globals (in-process; use Redis in production)
# ---------------------------------------------------------------------------

_agent_registry: AgentRegistry | None = None
_connector: OpenClawConnector | None = None
_engine: OrchestrationEngine | None = None
_active_tasks: dict[str, Any] = {}  # task_id → OrchestrationTask
_progress_queues: dict[str, asyncio.Queue] = {}  # task_id → progress queue


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None, None]:
    global _agent_registry, _connector, _engine

    # Load config from environment
    import os
    from dotenv import load_dotenv
    
    # Load environment variables from .env file
    load_dotenv()
    
    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    auth_token = os.getenv("OPENCLAW_AUTH_TOKEN", "")

    # Initialize OpenClaw connector
    _connector = OpenClawConnector(gateway_url=gateway_url, auth_token=auth_token or None)
    await _connector.initialize()

    # Build agent registry from OpenClaw's known agents
    _agent_registry = AgentRegistry()
    await _discover_agents(_agent_registry)

    # Create orchestration engine
    _engine = OrchestrationEngine(
        connector=_connector,
        registry=_agent_registry,
        max_parallel=3,
    )

    logger.info("orchestrator_started", gateway=gateway_url, agents=len(_agent_registry.list_agents()))

    yield

    # Shutdown
    await _connector.close()
    logger.info("orchestrator_shutdown")


async def _discover_agents(registry: AgentRegistry) -> None:
    """Auto-discover agents from OpenClaw and register them."""
    if not _connector:
        return

    try:
        agents_data = await _connector.list_agents()
        for agent_data in agents_data:
            agent_id = agent_data.get("id") or agent_data.get("agent_id", "unknown")
            capabilities = _infer_capabilities(agent_id)
            registry.register(AgentInfo(
                agent_id=agent_id,
                name=agent_data.get("name", agent_id),
                description=agent_data.get("description", ""),
                capabilities=capabilities,
                model=agent_data.get("model"),
                workspace=agent_data.get("workspace"),
            ))
    except Exception as e:
        logger.warning("agent_discovery_failed", error=str(e))


def _infer_capabilities(agent_id: str) -> list[AgentCapability]:
    """Infer agent capabilities from agent_id."""
    mapping = {
        "engineer": [AgentCapability.CODE, AgentCapability.FILE],
        "architect": [AgentCapability.RESEARCH, AgentCapability.ANALYSIS, AgentCapability.WRITING],
        "stock-analyst": [AgentCapability.ANALYSIS, AgentCapability.MATH, AgentCapability.RESEARCH],
        "researcher": [AgentCapability.RESEARCH],
        "writer": [AgentCapability.WRITING],
    }
    return mapping.get(agent_id, [AgentCapability.RESEARCH])


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Hermes-OpenClaw Orchestrator",
    description="Orchestration layer: Hermes as master, OpenClaw sub-agents as workers",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health & Info
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    """Overall orchestrator health."""
    connector_healthy = await _connector.health_check() if _connector else False
    return {
        "status": "ok" if connector_healthy else "degraded",
        "connector": connector_healthy,
        "gateway": _connector.gateway_url if _connector else None,
        "registered_agents": len(_agent_registry.list_agents()) if _agent_registry else 0,
        "active_tasks": len(_active_tasks),
    }


@app.get("/api/info")
async def info() -> dict[str, Any]:
    """Orchestrator information."""
    return {
        "version": "0.1.0",
        "gateway_url": _connector.gateway_url if _connector else None,
        "agents": [
            {"agent_id": a.agent_id, "name": a.name, "capabilities": [c.value for c in a.capabilities]}
            for a in (_agent_registry.list_agents() if _agent_registry else [])
        ],
    }


# ---------------------------------------------------------------------------
# Agent Registry
# ---------------------------------------------------------------------------


@app.get("/api/agents")
async def list_agents() -> dict[str, Any]:
    """List all registered OpenClaw sub-agents."""
    if not _agent_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")
    return {
        "agents": [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "description": a.description,
                "capabilities": [c.value for c in a.capabilities],
                "model": a.model,
                "is_available": a.is_available,
                "current_load": a.current_load,
            }
            for a in _agent_registry.list_agents()
        ]
    }


@app.post("/api/agents/register")
async def register_agent(agent: AgentInfo) -> dict[str, str]:
    """Manually register an OpenClaw sub-agent."""
    if not _agent_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")
    _agent_registry.register(agent)
    logger.info("agent_registered", agent_id=agent.agent_id, capabilities=[c.value for c in agent.capabilities])
    return {"status": "registered", "agent_id": agent.agent_id}


@app.delete("/api/agents/{agent_id}")
async def unregister_agent(agent_id: str) -> dict[str, str]:
    """Unregister an agent."""
    if not _agent_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")
    _agent_registry.unregister(agent_id)
    return {"status": "unregistered", "agent_id": agent_id}


# ---------------------------------------------------------------------------
# Orchestration Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/orchestrate", response_model=OrchestrationResponse)
async def orchestrate(request: OrchestrationRequest) -> OrchestrationResponse:
    """
    Submit a task for orchestration.
    Hermes sends the task here; the orchestrator decomposes it
    and dispatches subtasks to OpenClaw sub-agents.
    """
    if not _engine:
        raise HTTPException(status_code=503, detail="Orchestration engine not initialized")

    logger.info("orchestration_request", task=request.task[:100])

    response = await _engine.execute(request)

    # Store for later status queries
    _active_tasks[response.task_id] = {
        "response": response,
        "request": request,
        "submitted_at": datetime.utcnow(),
    }

    return response


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """Get current status of an orchestration task."""
    if task_id not in _active_tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    stored = _active_tasks[task_id]

    # Map string status to TaskStatus enum
    status_map = {
        "pending": TaskStatus.PENDING,
        "ready_for_execution": TaskStatus.PENDING,
        "running": TaskStatus.RUNNING,
        "completed": TaskStatus.COMPLETED,
        "failed": TaskStatus.FAILED,
    }
    status = status_map.get(stored.get("status", "pending"), TaskStatus.PENDING)

    return TaskStatusResponse(
        task_id=task_id,
        status=status,
        subtasks=stored.get("subtasks", []),
        result=stored.get("results", []) if isinstance(stored.get("results"), list) else stored.get("results"),
        error=stored.get("error"),
        created_at=stored["submitted_at"],
        completed_at=stored.get("completed_at"),
    )


@app.get("/api/tasks/{task_id}/stream")
async def stream_task_progress(task_id: str):
    """SSE stream for real-time task progress updates."""

    async def event_generator():
        queue: asyncio.Queue[TaskStatusResponse] = asyncio.Queue()
        _progress_queues[task_id] = queue

        try:
            while True:
                update = await queue.get()
                yield {
                    "event": "progress",
                    "data": update.model_dump_json(),
                }
                if update.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    break
        finally:
            _progress_queues.pop(task_id, None)

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Direct Agent Execution
# ---------------------------------------------------------------------------


@app.post("/api/agents/{agent_id}/execute")
async def execute_direct(
    agent_id: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    """
    Directly execute a task on a specific agent (bypassing orchestration).
    Useful for quick one-off tasks.
    """
    if not _connector:
        raise HTTPException(status_code=503, detail="Connector not initialized")

    from shared.types import SubTask, AgentInfo

    agent_info = _agent_registry.agents.get(agent_id) if _agent_registry else None
    subtask = SubTask(
        id="direct-1",
        description=request.get("task", ""),
        agent_type=agent_id,
        payload=request.get("context", {}),
    )

    result = await _connector.execute_subtask(
        agent_info or AgentInfo(agent_id=agent_id, name=agent_id, description="", capabilities=[]),
        subtask,
    )
    return result


# ---------------------------------------------------------------------------
# Hermes Proxy (OpenAI-compatible /chat/completions)
# ---------------------------------------------------------------------------


@app.post("/v1/chat/completions")
async def chat_completions(request: dict[str, Any]) -> dict[str, Any]:
    """
    OpenAI-compatible /chat/completions endpoint.
    Hermes can call this like a standard LLM API.
    The orchestrator intercepts task-related messages and routes them
    to OpenClaw sub-agents.
    
    Non-blocking: decomposes task and returns plan immediately,
    then executes subtasks in background.
    """
    messages = request.get("messages", [])
    last_message = messages[-1]["content"] if messages else ""

    # Check if this looks like a task request (English + Chinese keywords)
    task_keywords = [
        "analyze", "analysis", "research", "implement", "build", "create",
        "write", "develop", "stock", "report", "generate", "研究", "分析",
        "实现", "开发", "编写", "生成", "报告", "股票", "投资",
    ]
    text_lower = last_message.lower()
    is_task = any(kw in text_lower for kw in task_keywords)

    if is_task and _engine and _agent_registry:
        # Decompose task into subtasks (non-blocking, just planning)
        from orchestrator.engine import TaskDecomposer
        from shared.types import OrchestrationRequest

        orch_req = OrchestrationRequest(task=last_message)
        decomposer = TaskDecomposer()
        subtasks = decomposer.decompose(orch_req, _agent_registry)
        plan = [
            {"id": st.id, "description": st.description, "agent": st.agent_type}
            for st in subtasks
        ]

        # Store plan for Hermes to execute via sessions_spawn
        task_id = f"orch-{subtasks[0].id}" if subtasks else "orch-none"
        _active_tasks[task_id] = {
            "plan": plan,
            "subtasks": subtasks,
            "submitted_at": datetime.utcnow(),
            "status": "ready_for_execution",
        }

        # Dispatch execution in background (non-blocking)
        asyncio.create_task(_execute_plan_background(task_id, subtasks))

        # Build execution instructions for Hermes (who has sessions_spawn tool)
        exec_instructions = f"""✅ Task decomposed into {len(plan)} subtasks.

📋 **Execution Plan:**
"""
        for i, p in enumerate(plan):
            exec_instructions += f"{i+1}. **[{p['agent']}]** {p['description']}\n"

        exec_instructions += f"""
---
📌 **To execute:** Use `sessions_spawn` tool for each subtask with:
- agentId: `{p['agent']}`
- task: `{p['description']}`

Task ID: `{task_id}`
Poll status: GET /api/tasks/{task_id}"""

        return {
            "id": task_id,
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": exec_instructions,
                },
                "finish_reason": "stop",
            }],
            "model": request.get("model", "orchestrator"),
        }

    # Otherwise, return a redirect message
    return {
        "id": "orch-no-op",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "This is a general query. For task orchestration, please include action words like 'analyze', 'research', or 'implement'.",
            },
            "finish_reason": "stop",
        }],
        "model": request.get("model", "orchestrator"),
    }


async def _execute_plan_background(task_id: str, subtasks: list) -> None:
    """Execute subtasks in background using OpenClaw CLI."""
    if not _agent_registry:
        return
    try:
        _active_tasks[task_id]["status"] = "running"
        cli = CliExecutor(timeout=300)
        results = []
        for st in subtasks:
            agent_info = _agent_registry.agents.get(st.agent_type) if _agent_registry else None
            if agent_info:
                result = await cli.execute_subtask(agent_info, st)
                results.append(result)
                _active_tasks[task_id]["results"] = results
        _active_tasks[task_id]["status"] = "completed"
    except Exception as e:
        _active_tasks[task_id]["status"] = "failed"
        _active_tasks[task_id]["error"] = str(e)


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal orchestration error"})
