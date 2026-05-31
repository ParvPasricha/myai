"""
Agent Registry — maps capability strings to agent instances.
dispatch() runs a task on the matching agent and writes the result to the queue.
"""
import asyncio
from typing import Optional

from agents.base_agent import BaseAgent, AgentTask
from agents import task_queue
from observability.logger import log

# Lazy-imported agent instances (singletons)
_agents: dict[str, BaseAgent] = {}


def _get_agent(capability: str) -> Optional[BaseAgent]:
    if capability in _agents:
        return _agents[capability]

    mapping = {
        "research":          ("agents.research_agent",          "ResearchAgent"),
        "music":             ("agents.music_agent",              "MusicAgent"),
        "reminder":          ("agents.reminder_agent",           "ReminderAgent"),
        "email":             ("agents.email_agent",              "EmailAgent"),
        "message":           ("agents.message_agent",            "MessageAgent"),
        "sales_outreach":    ("agents.sales_agent",              "SalesAgent"),
        "business_update":   ("agents.business_update_agent",    "BusinessUpdateAgent"),
        "project_planning":  ("agents.project_planning_agent",   "ProjectPlanningAgent"),
        "project_oversight": ("agents.project_oversight_agent",  "ProjectOversightAgent"),
        "backend_review":    ("agents.backend_checker_agent",    "BackendCheckerAgent"),
        "frontend_review":   ("agents.frontend_checker_agent",   "FrontendCheckerAgent"),
        "security_review":   ("agents.security_agent",           "SecurityAgent"),
        "db_review":         ("agents.db_agent",                 "DbAgent"),
        "integration_check": ("agents.integration_checker_agent","IntegrationCheckerAgent"),
        "browser":           ("agents.browser_agent",            "BrowserAgent"),
    }

    if capability not in mapping:
        return None

    module_path, class_name = mapping[capability]
    try:
        import importlib
        mod   = importlib.import_module(module_path)
        cls   = getattr(mod, class_name)
        agent = cls()
        _agents[capability] = agent
        return agent
    except Exception as e:
        log.warn("registry_import_failed", capability=capability, error=str(e))
        return None


async def dispatch(
    capability: str,
    task_id: str,
    payload: dict,
    broadcast_fn=None,
) -> None:
    """Run a task on the matching agent. Writes result to task_queue."""
    agent = _get_agent(capability)
    if not agent:
        await asyncio.to_thread(
            task_queue.complete, task_id, "unknown", False, {},
            f"No agent registered for capability '{capability}'",
            f"Unknown capability: {capability}",
        )
        return

    task = AgentTask(id=task_id, task_type=capability, payload=payload)

    if broadcast_fn:
        await broadcast_fn({
            "type":       "agent_started",
            "task_id":    task_id,
            "agent":      agent.name,
            "capability": capability,
        })

    try:
        result = await agent.run(task)
        await asyncio.to_thread(
            task_queue.complete,
            task_id, agent.name, result.success,
            result.data, result.summary, result.error,
        )
        log.info("agent_done", agent=agent.name, task=task_id, ok=result.success)
    except Exception as e:
        log.warn("agent_dispatch_error", agent=agent.name, error=str(e))
        await asyncio.to_thread(
            task_queue.complete, task_id, agent.name, False, {}, str(e), str(e)
        )

    if broadcast_fn:
        await broadcast_fn({
            "type":    "agent_done",
            "task_id": task_id,
            "agent":   agent.name,
            "success": result.success if 'result' in dir() else False,
        })


def list_capabilities() -> list[str]:
    return [
        "research", "music", "reminder", "email", "message",
        "sales_outreach", "business_update", "project_planning",
        "project_oversight", "backend_review", "frontend_review",
        "security_review", "db_review", "integration_check", "browser",
    ]
