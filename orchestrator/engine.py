"""
Core orchestration engine — task decomposition, scheduling, and execution.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Optional

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from agents.openclaw_agent import OpenClawConnector
from shared.types import (
    AgentCapability,
    AgentInfo,
    AgentRegistry,
    OrchestrationRequest,
    OrchestrationResponse,
    SubTask,
    TaskStatus,
    OrchestrationTask,
    TaskStatusResponse,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Task Decomposer
# ---------------------------------------------------------------------------


class TaskDecomposer:
    """
    Decomposes a natural-language task from Hermes into a list of SubTasks
    matched to OpenClaw agent capabilities.
    """

    # Mapping of keywords → AgentCapabilities
    CAPABILITY_KEYWORDS: dict[AgentCapability, list[str]] = {
        AgentCapability.CODE: [
            "code", "implement", "develop", "build", "programming",
            "python", "javascript", "refactor", "debug", "function",
            "script", "api", "backend", "frontend",
        ],
        AgentCapability.RESEARCH: [
            "research", "search", "find", "lookup", "investigate",
            "explore", "discover", "browse", "web", "information",
        ],
        AgentCapability.ANALYSIS: [
            "analyze", "analysis", "evaluate", "assess", "review",
            "stock", "financial", "data", "report", "metrics",
        ],
        AgentCapability.WRITING: [
            "write", "document", "draft", "compose", "summary",
            "report", "article", "content", "blog",
        ],
        AgentCapability.MATH: [
            "calculate", "compute", "math", "formula", "equation",
            "numerical", "statistic",
        ],
        AgentCapability.FILE: [
            "file", "read", "write", "edit", "folder", "directory",
        ],
        AgentCapability.MEMORY: [
            "remember", "memory", "context", "history", "past",
        ],
        AgentCapability.CRON: [
            "schedule", "cron", "periodic", "recurring", "remind",
        ],
    }

    # Which OpenClaw agent_id to use for which capability
    AGENT_FOR_CAPABILITY: dict[AgentCapability, str] = {
        AgentCapability.CODE: "engineer",
        AgentCapability.RESEARCH: "architect",
        AgentCapability.ANALYSIS: "stock-analyst",
        AgentCapability.WRITING: "architect",
        AgentCapability.MATH: "stock-analyst",
        AgentCapability.FILE: "engineer",
        AgentCapability.MEMORY: "architect",
        AgentCapability.CRON: "architect",
    }

    def decompose(
        self, request: OrchestrationRequest, registry: AgentRegistry
    ) -> list[SubTask]:
        """
        Decompose a task description into subtasks.
        Simple keyword-based decomposition (can be replaced with LLM-based).
        """
        text = request.task.lower()
        subtasks: list[SubTask] = []

        # Detect required capabilities
        required_caps: list[AgentCapability] = []
        for cap, keywords in self.CAPABILITY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                required_caps.append(cap)

        # If no specific capability detected, treat as general research/analysis
        if not required_caps:
            required_caps = [AgentCapability.RESEARCH, AgentCapability.ANALYSIS]

        # Split by sentence delimiters that suggest parallel or sequential work
        segments = self._split_into_segments(request.task)

        for i, segment in enumerate(segments):
            segment_caps = self._detect_capabilities(segment)

            # Find best matching agent
            best_agent = registry.find_best_agent(segment_caps)
            agent_id = (
                best_agent.agent_id
                if best_agent
                else self._default_agent_for_caps(segment_caps)
            )

            subtask = SubTask(
                id=f"st-{i+1:02d}",
                description=segment.strip(),
                agent_type=agent_id,
                priority=request.priority,
                payload={
                    "original_task": request.task,
                    "segment_index": i,
                    "total_segments": len(segments),
                    **(request.context or {}),
                },
            )
            subtasks.append(subtask)

        logger.info(
            "task_decomposed",
            original_task=request.task[:80],
            num_subtasks=len(subtasks),
            capabilities=[c.value for c in required_caps],
        )
        return subtasks

    def _split_into_segments(self, text: str) -> list[str]:
        """Split task text into logical segments."""
        import re
        # Split on numbered lists, bullet points, "first/then/finally"
        segments = re.split(r"(?:\n(?:\d+[.)]\s|\*[*-]\s|-\s)|(?:\b(first|then|next|finally|also)\b[:,.\s]))", text)
        segments = [s.strip() for s in segments if s and s.strip()]
        if len(segments) <= 1:
            # Split on sentence boundaries
            segments = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
            segments = [s.strip() for s in segments if s.strip()]
        return segments or [text]

    def _detect_capabilities(self, text: str) -> list[AgentCapability]:
        """Detect capabilities needed for a text segment."""
        text_lower = text.lower()
        detected = []
        for cap, keywords in self.CAPABILITY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                detected.append(cap)
        return detected or [AgentCapability.RESEARCH]

    def _default_agent_for_caps(
        self, capabilities: list[AgentCapability]
    ) -> str:
        """Get the default agent for a list of capabilities."""
        for cap in capabilities:
            if cap in self.AGENT_FOR_CAPABILITY:
                return self.AGENT_FOR_CAPABILITY[cap]
        return "architect"


# ---------------------------------------------------------------------------
# Task Scheduler
# ---------------------------------------------------------------------------


class TaskScheduler:
    """
    Schedules subtasks based on dependencies and available agents.
    Handles both parallel and sequential execution.
    """

    def __init__(self, max_parallel: int = 3):
        self.max_parallel = max_parallel

    def get_ready_tasks(
        self, subtasks: list[SubTask], completed_ids: set[str]
    ) -> list[SubTask]:
        """Return subtasks that are ready to execute (dependencies met)."""
        ready = []
        for st in subtasks:
            if st.status != TaskStatus.PENDING:
                continue
            deps_met = all(dep in completed_ids for dep in st.depends_on)
            if deps_met:
                ready.append(st)
        return ready

    def schedule(
        self,
        subtasks: list[SubTask],
        running: set[str],
        completed_ids: set[str],
    ) -> list[SubTask]:
        """
        Given current running and completed task IDs, return the next batch
        of tasks to dispatch (respecting max_parallel).
        """
        ready = self.get_ready_tasks(subtasks, completed_ids)
        available_slots = self.max_parallel - len(running)
        return ready[:available_slots]


# ---------------------------------------------------------------------------
# Orchestration Engine
# ---------------------------------------------------------------------------


class OrchestrationEngine:
    """
    Main orchestration engine. Coordinates task decomposition, scheduling,
    execution, and result aggregation.
    """

    def __init__(
        self,
        connector: OpenClawConnector,
        registry: AgentRegistry,
        max_parallel: int = 3,
        progress_callback: Optional[Callable[[TaskStatusResponse], None]] = None,
    ):
        self.connector = connector
        self.registry = registry
        self.decomposer = TaskDecomposer()
        self.scheduler = TaskScheduler(max_parallel=max_parallel)
        self.max_parallel = max_parallel
        self.progress_callback = progress_callback

        # In-flight tracking
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._completed_ids: set[str] = set()
        self._failed_ids: set[str] = set()

    async def execute(self, request: OrchestrationRequest) -> OrchestrationResponse:
        """Execute a full orchestration task."""
        # Step 1: Decompose
        subtasks = self.decomposer.decompose(request, self.registry)
        orchestration_task = OrchestrationTask(
            title=request.task[:100],
            original_request=request.task,
            subtasks=subtasks,
        )

        logger.info(
            "orchestration_started",
            task_id=orchestration_task.id,
            num_subtasks=len(subtasks),
        )

        # Step 2: Execute subtasks
        await self._execute_subtasks(orchestration_task)

        # Step 3: Return response
        plan = [{"id": st.id, "description": st.description, "agent": st.agent_type} for st in subtasks]
        return OrchestrationResponse(
            task_id=orchestration_task.id,
            plan=plan,
            message=f"Orchestration started with {len(subtasks)} subtasks",
        )

    async def _execute_subtasks(self, task: OrchestrationTask) -> None:
        """Execute subtasks with dependency awareness and parallel scheduling."""
        running_ids: set[str] = set()
        completed_ids: set[str] = set()
        failed_ids: set[str] = set()

        while True:
            # Check for completed tasks
            done = [tid for tid in running_ids if tid not in self._running_tasks]
            for tid in done:
                if tid in self._running_tasks:
                    del self._running_tasks[tid]

            # Get next batch of ready tasks
            ready = self.scheduler.get_ready_tasks(task.subtasks, completed_ids)
            slots = self.max_parallel - len(running_ids)

            for subtask in ready[:slots]:
                subtask.status = TaskStatus.RUNNING
                subtask.started_at = datetime.utcnow()

                # Find agent info
                agent_info = self.registry.find_best_agent(
                    [AgentCapability.RESEARCH]  # simplified
                )
                if not agent_info:
                    # Fallback: find by agent_id
                    agent_info = self.registry.agents.get(subtask.agent_type)

                if not agent_info:
                    subtask.status = TaskStatus.FAILED
                    subtask.error = f"Agent {subtask.agent_type} not found in registry"
                    failed_ids.add(subtask.id)
                    continue

                # Increment load
                agent_info.current_load += 1
                running_ids.add(subtask.id)

                # Spawn execution task
                coro = self._run_subtask(subtask, agent_info, task)
                asyncio_task = asyncio.create_task(coro)
                self._running_tasks[subtask.id] = asyncio_task

            # Check if done
            if not running_ids and not ready:
                break

            # Wait for something to complete
            if running_ids:
                done_pending, _ = await asyncio.wait(
                    self._running_tasks.values(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for pending in done_pending:
                    result = pending.result()
                    task_id = result["task_id"]
                    if result["status"] == TaskStatus.COMPLETED.value:
                        completed_ids.add(task_id)
                    else:
                        failed_ids.add(task_id)
                    # Decrement load
                    for agent in self.registry.agents.values():
                        if agent.agent_id == result.get("agent_id"):
                            agent.current_load = max(0, agent.current_load - 1)

            # Small yield
            await asyncio.sleep(0.1)

        # Update final task status
        task.completed_at = datetime.utcnow()
        if failed_ids:
            task.status = TaskStatus.FAILED if not completed_ids else TaskStatus.COMPLETED
        else:
            task.status = TaskStatus.COMPLETED

        logger.info(
            "orchestration_completed",
            task_id=task.id,
            completed=len(completed_ids),
            failed=len(failed_ids),
        )

    async def _run_subtask(
        self,
        subtask: SubTask,
        agent_info: AgentInfo,
        orchestration_task: OrchestrationTask,
    ) -> dict[str, Any]:
        """Run a single subtask and update its status."""
        try:
            result = await self.connector.execute_subtask(agent_info, subtask)

            # Update subtask
            subtask.result = result.get("result")
            subtask.status = TaskStatus.COMPLETED if result.get("status") == "completed" else TaskStatus.FAILED
            subtask.error = result.get("error")
            subtask.completed_at = datetime.utcnow()

            # Aggregate results into orchestration task
            if subtask.result:
                orchestration_task.metadata.setdefault("subtask_results", {})[subtask.id] = subtask.result

            # Progress callback
            if self.progress_callback:
                self.progress_callback(self.get_task_status(orchestration_task))

            return result

        except Exception as e:
            subtask.status = TaskStatus.FAILED
            subtask.error = str(e)
            subtask.completed_at = datetime.utcnow()
            logger.error("subtask_execution_error", task_id=subtask.id, error=str(e))
            return {
                "task_id": subtask.id,
                "agent_id": agent_info.agent_id,
                "status": TaskStatus.FAILED.value,
                "error": str(e),
            }

    def get_task_status(self, task: OrchestrationTask) -> TaskStatusResponse:
        """Get current status of an orchestration task."""
        return TaskStatusResponse(
            task_id=task.id,
            status=task.status,
            subtasks=task.subtasks,
            result=task.metadata.get("subtask_results"),
            created_at=task.created_at,
            completed_at=task.completed_at,
        )
