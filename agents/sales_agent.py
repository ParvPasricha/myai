"""Sales Agent — lead outreach drafting and follow-up tracking."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class SalesAgent(BaseAgent):
    name = "sales"
    capabilities = ["sales_outreach"]

    async def run(self, task: AgentTask) -> AgentResult:
        action = task.payload.get("action", "draft")
        try:
            from server.llm_router import llm

            if action == "draft":
                name    = task.payload.get("name", "")
                company = task.payload.get("company", "")
                context = task.payload.get("context", "")
                product = task.payload.get("product", "your solution")
                if not name:
                    return self.result_err(task, "No prospect name provided")

                prompt = (
                    f"Prospect: {name} at {company}.\n"
                    f"Context: {context}\n"
                    f"Product/service: {product}\n\n"
                    "Draft a short, personalised outreach message. "
                    "One paragraph. No generic opener. Lead with value. End with a soft CTA."
                )
                r = await llm.complete(prompt=prompt,
                    system="Write sharp B2B outreach. No filler. No 'I hope this finds you well'.",
                    max_tokens=200)
                draft = r.get("text", "")
                return self.result_ok(task, {"draft": draft, "to": name},
                    f"Outreach draft for {name} at {company} ready. Approve on your phone to send, sir.")

            if action == "follow_up_check":
                # Check unified memory for leads not followed up in N days
                days = task.payload.get("days", 5)
                from intelligence import unified_memory
                import time
                cutoff = time.time() - (days * 86400)
                results = unified_memory.search_memory("lead outreach sales prospect", n_each=5)
                stale = []
                for col_items in results.values():
                    for item in col_items:
                        if item.get("metadata", {}).get("ts", 0) < cutoff:
                            stale.append(item.get("text", "")[:80])
                if not stale:
                    return self.result_ok(task, {}, f"All leads followed up within {days} days, sir.")
                summary = f"{len(stale)} lead{'s' if len(stale)>1 else ''} not touched in {days}+ days: " \
                          + "; ".join(stale[:3])
                return self.result_ok(task, {"stale_leads": stale}, summary)

            return self.result_err(task, f"Unknown action: {action}")

        except Exception as e:
            log.warn("sales_agent_error", error=str(e))
            return self.result_err(task, str(e))
