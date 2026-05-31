"""Project Planning Agent — structured plans with phases, milestones, dependencies."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class ProjectPlanningAgent(BaseAgent):
    name = "project_planning"
    capabilities = ["project_planning"]

    async def run(self, task: AgentTask) -> AgentResult:
        name        = task.payload.get("name", "")
        description = task.payload.get("description", "")
        constraints = task.payload.get("constraints", "")
        if not name and not description:
            return self.result_err(task, "No project name or description provided")
        try:
            from server.llm_router import llm
            from intelligence import unified_memory

            # Pull relevant existing memory
            mem = unified_memory.get_relevant_context(
                f"project {name} {description}", n_each=2
            )
            prompt = (
                f"Project: {name}\nDescription: {description}\n"
                f"{'Constraints: ' + constraints if constraints else ''}\n"
                f"Relevant context:\n{mem[:400]}\n\n"
                "Create a structured project plan:\n"
                "1. Phases (ordered, with brief description)\n"
                "2. Key milestones with target weeks\n"
                "3. Dependencies between phases\n"
                "4. Top 3 risks\n"
                "Be concrete and realistic. No padding."
            )
            r = await llm.complete(prompt=prompt,
                system="Create precise, actionable project plans. Be realistic about timelines.",
                max_tokens=500)
            plan = r.get("text", "")

            # Store in memory
            unified_memory.store_domain_knowledge(
                f"Project plan for {name}:\n{plan[:500]}",
                domain="project_management",
                metadata={"project": name, "type": "plan"},
            )

            return self.result_ok(task, {"plan": plan, "project": name},
                f"Project plan for '{name}' complete — {len(plan.splitlines())} lines, stored in memory.")

        except Exception as e:
            log.warn("project_planning_agent_error", error=str(e))
            return self.result_err(task, str(e))
