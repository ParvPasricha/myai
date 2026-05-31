"""
BaseAgent — all subagents inherit this.

Subagents are stateless workers. They receive a task dict, do their job,
and return a result dict. Jarvis (head_agent) dispatches and synthesises.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentTask:
    id: str
    task_type: str          # matches a capability string in registry
    payload: dict           # free-form task parameters
    parent_task_id: str = ""
    priority: int = 5       # 1=highest, 10=lowest


@dataclass
class AgentResult:
    task_id: str
    agent_name: str
    success: bool
    data: dict = field(default_factory=dict)
    summary: str = ""       # one-sentence Jarvis-ready summary
    error: str = ""


class BaseAgent(ABC):
    name: str = "base"
    capabilities: list[str] = []

    @abstractmethod
    async def run(self, task: AgentTask) -> AgentResult:
        """Execute the task and return a result."""

    def result_ok(self, task: AgentTask, data: dict, summary: str) -> AgentResult:
        return AgentResult(
            task_id=task.id, agent_name=self.name,
            success=True, data=data, summary=summary,
        )

    def result_err(self, task: AgentTask, error: str) -> AgentResult:
        return AgentResult(
            task_id=task.id, agent_name=self.name,
            success=False, error=error,
            summary=f"The {self.name} agent encountered an error: {error[:80]}",
        )
