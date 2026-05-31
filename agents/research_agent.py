"""Research Agent — web search + synthesis."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class ResearchAgent(BaseAgent):
    name = "research"
    capabilities = ["research"]

    async def run(self, task: AgentTask) -> AgentResult:
        query = task.payload.get("query", "")
        if not query:
            return self.result_err(task, "No query provided")
        try:
            from server.llm_router import llm
            import httpx, json as _json

            # Web search via existing web_search route logic
            from intelligence.topic_researcher import research_topic
            result = await research_topic(query)
            summary = result.get("summary", result.get("content", ""))[:500] if result else ""

            if not summary:
                # Fallback: ask LLM directly
                r = await llm.complete(
                    prompt=f"Research and summarise: {query}",
                    system="Provide a concise, factual research summary. Cite key points.",
                    max_tokens=400,
                )
                summary = r.get("text", "")

            return self.result_ok(task, {"summary": summary, "query": query},
                                  f"Research on '{query}' complete — {len(summary)} chars returned.")
        except Exception as e:
            log.warn("research_agent_error", error=str(e))
            return self.result_err(task, str(e))
