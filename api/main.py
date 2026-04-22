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
from orchestrator.events import EventBus, DashboardEventPayload, get_event_bus, create_event_bus
from shared.types import (
    AgentCapability,
    AgentInfo,
    AgentRegistry,
    OrchestrationRequest,
    OrchestrationResponse,
    OrchestrationTask,
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
_event_bus: EventBus | None = None
_sse_queues: set[asyncio.Queue] = set()  # SSE client queues


async def _sse_broadcaster(event_bus: EventBus) -> None:
    """Consume EventBus global queue and broadcast to all SSE clients."""
    async for payload in event_bus.listen():
        for queue in list(_sse_queues):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                _sse_queues.discard(queue)


async def _heartbeat_loop(event_bus: EventBus) -> None:
    """Periodically emit heartbeat events."""
    while True:
        await asyncio.sleep(30)
        try:
            await event_bus.emit_heartbeat()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None, None]:
    global _agent_registry, _connector, _engine, _event_bus

    # Load config from environment
    import os
    from dotenv import load_dotenv

    # Load environment variables from .env file
    load_dotenv()

    gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
    auth_token = os.getenv("OPENCLAW_AUTH_TOKEN", "")

    # Initialize EventBus and inject into orchestrator
    _event_bus = create_event_bus()

    # Initialize OpenClaw connector
    _connector = OpenClawConnector(gateway_url=gateway_url, auth_token=auth_token or None)
    await _connector.initialize()

    # Build agent registry from OpenClaw's known agents
    _agent_registry = AgentRegistry()
    await _discover_agents(_agent_registry)

    # Create orchestration engine with EventBus injection
    _engine = OrchestrationEngine(
        connector=_connector,
        registry=_agent_registry,
        max_parallel=3,
        event_bus=_event_bus,
    )

    # Start SSE broadcaster background task
    heartbeat_task = asyncio.create_task(_heartbeat_loop(_event_bus))
    broadcaster_task = asyncio.create_task(_sse_broadcaster(_event_bus))

    # Inject WS manager into EventBus
    from api.websocket import ws_manager
    _event_bus.set_ws_manager(ws_manager)

    logger.info("orchestrator_started", gateway=gateway_url, agents=len(_agent_registry.list_agents()))

    yield

    # Shutdown
    heartbeat_task.cancel()
    broadcaster_task.cancel()
    try:
        await asyncio.gather(heartbeat_task, broadcaster_task, return_exceptions=True)
    except Exception:
        pass
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

            # Handle model field that may be a dict like {"primary": "minimax/..."} or a string
            model_raw = agent_data.get("model")
            if isinstance(model_raw, dict):
                model = model_raw.get("primary") or list(model_raw.values())[0] if model_raw else None
            elif isinstance(model_raw, str):
                model = model_raw
            else:
                model = None

            registry.register(AgentInfo(
                agent_id=agent_id,
                name=agent_data.get("name", agent_id),
                description=agent_data.get("description", ""),
                capabilities=capabilities,
                model=model,
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

# WebSocket endpoint for dashboard real-time updates
from api.websocket import router as ws_router
app.include_router(ws_router)

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
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "capabilities": [c.value for c in a.capabilities],
                "model": a.model,
            }
            for a in (_agent_registry.list_agents() if _agent_registry else [])
        ],
    }


@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    """
    Return available models from the OpenClaw config file.
    Reads ~/.openclaw/openclaw.json to extract:
      - All unique model IDs across providers
      - Per-agent model overrides
    """
    import os
    import json

    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    defaults = {"primary": "minimax/MiniMax-M2.7", "fallbacks": []}
    all_models: list[str] = []
    agent_models: dict[str, str] = {}

    try:
        with open(config_path) as f:
            cfg = json.load(f)

        # Collect all model IDs from all providers
        models_cfg = cfg.get("models", {})
        providers = models_cfg.get("providers", {})
        for provider_name, provider_data in providers.items():
            for model_entry in provider_data.get("models", []):
                model_id = model_entry.get("id")
                if model_id:
                    all_models.append(model_id)

        # Per-agent model overrides
        agents_cfg = cfg.get("agents", {}).get("list", [])
        for agent in agents_cfg:
            agent_id = agent.get("id")
            model_override = agent.get("model", {})
            if agent_id and isinstance(model_override, dict):
                primary = model_override.get("primary")
                if primary:
                    agent_models[agent_id] = primary

        # System defaults
        system_defaults = models_cfg.get("defaults", {}).get("model", {})
        if isinstance(system_defaults, dict):
            defaults = {
                "primary": system_defaults.get("primary", "minimax/MiniMax-M2.7"),
                "fallbacks": system_defaults.get("fallbacks", []),
            }

    except Exception as e:
        logger.warning("failed_to_read_openclaw_config", error=str(e))

    # Deduplicate, preserve order
    unique_models = list(dict.fromkeys(all_models))

    return {
        "models": unique_models,
        "default": defaults["primary"],
        "fallbacks": defaults["fallbacks"],
        "agentModels": agent_models,
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

    Returns immediately with task_id - execution happens in background.
    """
    if not _engine:
        raise HTTPException(status_code=503, detail="Orchestration engine not initialized")

    logger.info("orchestration_request", task=request.task[:100])

    # Decompose task to get plan immediately
    subtasks = _engine.decomposer.decompose(request, _engine.registry)
    # Build an OrchestrationTask to get a unique task_id
    orchestration_task = OrchestrationTask(
        title=request.task[:100],
        original_request=request.task,
        subtasks=subtasks,
    )
    task_id = orchestration_task.id  # unique UUID-based id
    plan = [{"id": st.id, "description": st.description, "agent": st.agent_type} for st in subtasks]

    response = OrchestrationResponse(
        task_id=task_id,
        plan=plan,
        message=f"Orchestration started with {len(subtasks)} subtasks",
    )

    # Store for later status queries
    _active_tasks[task_id] = {
        "response": response,
        "request": request,
        "plan": plan,  # stored for history API
        "submitted_at": datetime.utcnow(),
        "subtasks": subtasks,
        "status": "pending",
    }

    # Execute in background - don't wait
    asyncio.create_task(_execute_orchestration(task_id, request, subtasks))

    return response


async def _emit_safe(coro):
    """Fire-and-forget EventBus emit with graceful error suppression."""
    try:
        await coro
    except Exception as exc:
        logger.warning("eventbus_emit_failed", error=str(exc))


async def _execute_orchestration(task_id: str, request: OrchestrationRequest, subtasks: list[SubTask]) -> None:
    """Background task to execute orchestration."""
    # Emit task started event
    if _event_bus:
        plan_for_event = [
            {"id": st.id, "description": st.description, "agent": st.agent_type}
            for st in subtasks
        ]
        asyncio.create_task(_emit_safe(_event_bus.emit_task_started(task_id, plan_for_event)))

    try:
        if task_id in _active_tasks:
            _active_tasks[task_id]["status"] = "running"

        connector = _connector
        registry = _agent_registry

        from shared.types import AgentCapability, TaskStatus

        for subtask in subtasks:
            subtask.status = TaskStatus.RUNNING
            subtask.started_at = datetime.utcnow()

            # Emit subtask started event
            if _event_bus:
                asyncio.create_task(_emit_safe(_event_bus.emit_subtask_started(
                    task_id, subtask.id, subtask.agent_type, subtask.description
                )))

            # Find agent info
            agent_info = registry.find_best_agent([AgentCapability.RESEARCH]) if registry else None
            if not agent_info:
                agent_info = registry.agents.get(subtask.agent_type) if registry else None

            if not agent_info:
                subtask.status = TaskStatus.FAILED
                subtask.error = f"Agent {subtask.agent_type} not found"
                if _event_bus:
                    asyncio.create_task(_emit_safe(_event_bus.emit_subtask_failed(
                        task_id, subtask.id, subtask.agent_type, subtask.error
                    )))
                continue

            agent_info.current_load += 1

            try:
                result = await connector.execute_subtask(agent_info, subtask)
                subtask.result = result.get("result")
                subtask.status = TaskStatus.COMPLETED if result.get("status") == "completed" else TaskStatus.FAILED
                subtask.error = result.get("error")

                # Emit subtask completed/failed event
                if _event_bus:
                    if subtask.status == TaskStatus.COMPLETED:
                        asyncio.create_task(_emit_safe(_event_bus.emit_subtask_completed(
                            task_id, subtask.id, agent_info.agent_id, subtask.result
                        )))
                        asyncio.create_task(_emit_safe(_event_bus.emit_stream_done(task_id, subtask.id)))
                    else:
                        asyncio.create_task(_emit_safe(_event_bus.emit_subtask_failed(
                            task_id, subtask.id, agent_info.agent_id, subtask.error or "unknown error"
                        )))
            except Exception as ex:
                subtask.status = TaskStatus.FAILED
                subtask.error = str(ex)
                if _event_bus:
                    asyncio.create_task(_emit_safe(_event_bus.emit_subtask_failed(
                        task_id, subtask.id, agent_info.agent_id, str(ex)
                    )))

            subtask.completed_at = datetime.utcnow()
            agent_info.current_load = max(0, agent_info.current_load - 1)

        if task_id in _active_tasks:
            _active_tasks[task_id]["status"] = "completed"
            _active_tasks[task_id]["completed_at"] = datetime.utcnow()

        # Emit task completed event
        if _event_bus:
            asyncio.create_task(_emit_safe(_event_bus.emit_task_completed(task_id, None)))

    except Exception as e:
        logger.error("orchestration_failed", task_id=task_id, error=str(e))
        if task_id in _active_tasks:
            _active_tasks[task_id]["status"] = "failed"
            _active_tasks[task_id]["error"] = str(e)
        if _event_bus:
            asyncio.create_task(_emit_safe(_event_bus.emit_task_failed(task_id, str(e))))


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
# Dashboard API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/tasks/{task_id}/dag")
async def get_task_dag(task_id: str) -> dict[str, Any]:
    """
    Get the DAG structure for a task (nodes + edges).
    Used by the frontend to initialize the React Flow canvas.
    """
    if task_id not in _active_tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    stored = _active_tasks[task_id]
    subtasks = stored.get("subtasks", [])
    plan = stored.get("plan", [])

    # Build Hermes root node
    nodes = [{
        "id": f"hermes-{task_id}",
        "type": "hermes",
        "position": {"x": 400, "y": 50},
        "data": {
            "label": "Hermes",
            "status": stored.get("status", "pending"),
            "taskId": task_id,
            "description": stored.get("request", {}).task if hasattr(stored.get("request", {}), 'task') else str(stored.get("original_task", "")),
        }
    }]

    # Build agent nodes
    centerX = 400
    startY = 200
    for i, p in enumerate(plan):
        offsetX = (i - (len(plan) - 1) / 2) * 220
        nodes.append({
            "id": f"agent-{p['id']}",
            "type": "openclaw",
            "position": {"x": centerX + offsetX - 110, "y": startY},
            "data": {
                "label": p["agent"],
                "agentId": p["agent"],
                "status": "pending",
                "isThinking": False,
                "description": p["description"],
                "taskId": task_id,
            }
        })

    # Build edges
    edges = []
    for p in plan:
        edges.append({
            "id": f"edge-hermes-{p['id']}",
            "source": f"hermes-{task_id}",
            "target": f"agent-{p['id']}",
            "animated": False,
            "data": {"status": "pending"}
        })

    return {"taskId": task_id, "nodes": nodes, "edges": edges}


@app.get("/api/tasks/{task_id}/history")
async def get_task_history(task_id: str) -> dict[str, Any]:
    """Get full history for a task including all conversation logs."""
    if task_id not in _active_tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    stored = _active_tasks[task_id]
    return {
        "taskId": task_id,
        "status": stored.get("status", "unknown"),
        "plan": stored.get("plan", []),
        "subtasks": stored.get("subtasks", []),
        "results": stored.get("results", []),
        "error": stored.get("error"),
        "createdAt": stored.get("submitted_at", "").isoformat() if stored.get("submitted_at") else None,
        "completedAt": stored.get("completed_at", "").isoformat() if stored.get("completed_at") else None,
    }


@app.get("/api/agents/{agent_id}/context")
async def get_agent_context(agent_id: str) -> dict[str, Any]:
    """Get the recent context/conversation log for a specific agent."""
    if not _agent_registry:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    agent_info = _agent_registry.agents.get(agent_id)
    if not agent_info:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    return {
        "agentId": agent_id,
        "name": agent_info.name,
        "description": agent_info.description,
        "capabilities": [c.value for c in agent_info.capabilities],
        "isAvailable": agent_info.is_available,
        "currentLoad": agent_info.current_load,
    }


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, str]:
    """Cancel a running task."""
    if task_id not in _active_tasks:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    stored = _active_tasks[task_id]
    stored["status"] = "cancelled"

    logger.info("task_cancelled", task_id=task_id)
    return {"status": "cancelled", "taskId": task_id}


@app.get("/api/dashboard/history")
async def list_task_history() -> dict[str, Any]:
    """List all recent tasks (for history sidebar)."""
    tasks = []
    for task_id, stored in _active_tasks.items():
        request_data = stored.get("request", {})
        title = getattr(request_data, 'task', str(stored.get("original_request", "")))[:80]
        tasks.append({
            "taskId": task_id,
            "title": title,
            "status": stored.get("status", "unknown"),
            "createdAt": stored.get("submitted_at", "").isoformat() if stored.get("submitted_at") else None,
            "numSubtasks": len(stored.get("plan", [])),
            "plan": stored.get("plan", []),
        })

    # Sort by createdAt descending
    tasks.sort(key=lambda t: t.get("createdAt") or "", reverse=True)
    return {"tasks": tasks[:50]}  # Last 50


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
