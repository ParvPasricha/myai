"""Project Oversight Agent — monitors ongoing projects, flags blockers."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class ProjectOversightAgent(BaseAgent):
    name = "project_oversight"
    capabilities = ["project_oversight"]

    async def run(self, task: AgentTask) -> AgentResult:
        project = task.payload.get("project", "")
        try:
            from server.llm_router import llm
            from intelligence import unified_memory
            import time

            # Pull project memory
            query = f"project {project} status milestone blocker" if project else "project status milestone blocker overdue"
            mem   = unified_memory.get_relevant_context(query, n_each=4)

            # Recent decisions in this domain
            db = unified_memory._get_sqlite()
            recent = db.execute(
                "SELECT content FROM decisions WHERE domain='project_management' "
                "ORDER BY ts DESC LIMIT 5"
            ).fetchall()
            decisions = "\n".join(f"- {r['content'][:100]}" for r in recent) or "None."

            prompt = (
                f"{'Project: ' + project if project else 'All projects'}\n\n"
                f"Memory context:\n{mem[:600]}\n\n"
                f"Recent decisions:\n{decisions}\n\n"
                "Assess current project status:\n"
                "1. What's on track\n"
                "2. What's behind or at risk\n"
                "3. Specific blockers identified\n"
                "4. Recommended next action\n"
                "Be direct. Flag anything overdue prominently."
            )
            r = await llm.complete(prompt=prompt,
                system="Project oversight: identify risks and blockers clearly. No sugar-coating.",
                max_tokens=400)
            assessment = r.get("text", "")

            return self.result_ok(task, {"assessment": assessment, "project": project},
                f"Project oversight complete{' for ' + project if project else ''}. Check dashboard for full report.")

        except Exception as e:
            log.warn("project_oversight_agent_error", error=str(e))
            return self.result_err(task, str(e))
