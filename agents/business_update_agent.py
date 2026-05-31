"""Business Update Agent — generates status digests and weekly summaries."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class BusinessUpdateAgent(BaseAgent):
    name = "business_update"
    capabilities = ["business_update"]

    async def run(self, task: AgentTask) -> AgentResult:
        period = task.payload.get("period", "daily")   # daily | weekly
        focus  = task.payload.get("focus", "")
        try:
            from server.llm_router import llm
            from intelligence import unified_memory
            import time

            cutoff = time.time() - (7 * 86400 if period == "weekly" else 86400)

            # Pull recent decisions, goals, work patterns
            db = unified_memory._get_sqlite()
            decisions = db.execute(
                "SELECT content, domain FROM decisions WHERE ts > ? ORDER BY ts DESC LIMIT 10",
                (cutoff,)
            ).fetchall()
            dec_text = "\n".join(f"- {r['content'][:100]} ({r['domain']})" for r in decisions) or "None."

            mem_ctx = unified_memory.get_relevant_context(
                focus or "business project status progress", n_each=3
            )

            prompt = (
                f"Generate a concise {period} business update for Parv.\n\n"
                f"Recent decisions:\n{dec_text}\n\n"
                f"Memory context:\n{mem_ctx[:600]}\n\n"
                f"{'Focus area: ' + focus if focus else ''}\n\n"
                "Format: 3-5 bullet points. Factual. Flag anything overdue or at risk."
            )
            r = await llm.complete(prompt=prompt,
                system="Generate precise business status updates. Flag risks and blockers clearly.",
                max_tokens=350)
            update = r.get("text", "")

            return self.result_ok(task, {"update": update, "period": period},
                f"{period.capitalize()} business update ready — {len(decisions)} decisions in period.")

        except Exception as e:
            log.warn("business_update_agent_error", error=str(e))
            return self.result_err(task, str(e))
