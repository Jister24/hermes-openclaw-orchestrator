"""
OpenClaw agent execution via CLI subprocess.
Since OpenClaw doesn't expose a spawn API via REST, we use the CLI.
"""

import asyncio
import json
import logging
import subprocess
from datetime import datetime
from typing import Any, Optional

import structlog

from shared.types import AgentInfo, SubTask, TaskStatus

logger = structlog.get_logger(__name__)


class CliExecutor:
    """Execute OpenClaw agent tasks via CLI subprocess."""

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    async def execute_subtask(
        self,
        agent_info: AgentInfo,
        subtask: SubTask,
    ) -> dict[str, Any]:
        """Execute a subtask by calling openclaw agent via CLI."""
        start_time = datetime.utcnow()

        # Build the task prompt
        task_prompt = self._build_task_prompt(subtask)

        # Escape the prompt for shell
        escaped_prompt = task_prompt.replace('"', '\\"').replace('\n', ' ')

        # Build the CLI command
        cmd = [
            "openclaw",
            "agent",
            "--agent", agent_info.agent_id,
            "--message", task_prompt,
            "--json",
        ]

        logger.info(
            "cli_executing_subtask",
            agent_id=agent_info.agent_id,
            task_id=subtask.id,
            cmd=f"openclaw agent --agent {agent_info.agent_id} --json",
        )

        try:
            # Run the CLI command
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd="/home/jister/.openclaw/workspace",
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout
            )

            duration = (datetime.utcnow() - start_time).total_seconds()

            if proc.returncode == 0:
                try:
                    result_data = json.loads(stdout.decode())
                    return {
                        "task_id": subtask.id,
                        "agent_id": agent_info.agent_id,
                        "status": TaskStatus.COMPLETED.value,
                        "result": result_data,
                        "duration_seconds": duration,
                        "error": None,
                    }
                except json.JSONDecodeError:
                    return {
                        "task_id": subtask.id,
                        "agent_id": agent_info.agent_id,
                        "status": TaskStatus.COMPLETED.value,
                        "result": {"raw": stdout.decode()},
                        "duration_seconds": duration,
                        "error": None,
                    }
            else:
                error_msg = stderr.decode() if stderr else f"Exit code {proc.returncode}"
                logger.error(
                    "cli_subtask_failed",
                    task_id=subtask.id,
                    agent_id=agent_info.agent_id,
                    error=error_msg,
                )
                return {
                    "task_id": subtask.id,
                    "agent_id": agent_info.agent_id,
                    "status": TaskStatus.FAILED.value,
                    "result": None,
                    "duration_seconds": duration,
                    "error": error_msg,
                }

        except asyncio.TimeoutError:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(
                "cli_subtask_timeout",
                task_id=subtask.id,
                agent_id=agent_info.agent_id,
                timeout=self.timeout,
            )
            return {
                "task_id": subtask.id,
                "agent_id": agent_info.agent_id,
                "status": TaskStatus.FAILED.value,
                "result": None,
                "duration_seconds": duration,
                "error": f"Timeout after {self.timeout}s",
            }

        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(
                "cli_subtask_error",
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
            "\nPlease execute this task and return the results."
        )

        return "\n".join(prompt_parts)
