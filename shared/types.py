"""Shared types and data models for the orchestration layer."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEPENDENT_WAITING = "dependent_waiting"


class TaskPriority(int, Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class AgentCapability(str, Enum):
    CODE = "code"
    RESEARCH = "research"
    ANALYSIS = "analysis"
    WRITING = "writing"
    MATH = "math"
    WEB = "web"
    FILE = "file"
    MEMORY = "memory"
    CRON = "cron"
    CHAT = "chat"


# ---------------------------------------------------------------------------
# Task Models
# ---------------------------------------------------------------------------


class SubTask(BaseModel):
    """A single sub-task dispatched to a sub-agent."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str
    agent_type: str  # e.g. "engineer", "architect", "stock-analyst"
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    payload: dict[str, Any] = Field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 2
    depends_on: list[str] = Field(default_factory=list)  # list of task IDs


class OrchestrationTask(BaseModel):
    """Top-level orchestration task submitted by Hermes."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    title: str
    original_request: str
    subtasks: list[SubTask] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent Registration
# ---------------------------------------------------------------------------


class AgentInfo(BaseModel):
    """Information about a registered OpenClaw sub-agent."""

    agent_id: str
    name: str
    description: str
    capabilities: list[AgentCapability]
    model: Optional[str] = None
    workspace: Optional[str] = None
    is_available: bool = True
    current_load: int = 0  # number of running tasks


class AgentRegistry(BaseModel):
    """Registry of all available OpenClaw sub-agents."""

    agents: dict[str, AgentInfo] = Field(default_factory=dict)

    def register(self, agent: AgentInfo) -> None:
        self.agents[agent.agent_id] = agent

    def unregister(self, agent_id: str) -> None:
        if agent_id in self.agents:
            del self.agents[agent_id]

    def find_best_agent(
        self, capabilities: list[AgentCapability]
    ) -> Optional[AgentInfo]:
        """Find the least-loaded agent that matches required capabilities."""
        candidates = [
            a for a in self.agents.values()
            if a.is_available and a.current_load < 3
            and all(cap in a.capabilities for cap in capabilities)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda a: a.current_load)

    def list_agents(self) -> list[AgentInfo]:
        return list(self.agents.values())


# ---------------------------------------------------------------------------
# API Request/Response Models
# ---------------------------------------------------------------------------


class OrchestrationRequest(BaseModel):
    """Request from Hermes to start orchestration."""

    task: str = Field(..., description="Natural language task description")
    context: Optional[dict[str, Any]] = Field(default=None)
    priority: TaskPriority = TaskPriority.NORMAL
    metadata: Optional[dict[str, Any]] = Field(default=None)


class OrchestrationResponse(BaseModel):
    """Response with task ID and initial plan."""

    task_id: str
    plan: list[dict[str, str]]  # list of subtask descriptions
    message: str


class TaskStatusResponse(BaseModel):
    """Current status of an orchestration task."""

    task_id: str
    status: TaskStatus
    subtasks: list[SubTask]
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class SubAgentResponse(BaseModel):
    """Response from a sub-agent execution."""

    task_id: str
    agent_id: str
    status: TaskStatus
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    duration_seconds: Optional[float] = None
