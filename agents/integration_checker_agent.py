"""Integration Checker Agent — verifies services connect end-to-end."""
import asyncio
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


_DEFAULT_CHECKS = [
    {"name": "FastAPI server",    "url": "http://localhost:8000/health"},
    {"name": "GDLE WebSocket",    "url": "http://localhost:8000/gdle/status"},
    {"name": "Dream status",      "url": "http://localhost:8000/dream/status"},
    {"name": "Intelligence",      "url": "http://localhost:8000/intelligence/status"},
    {"name": "Next.js dashboard", "url": "http://localhost:3001"},
]


async def _check_endpoint(name: str, url: str, token: str = "") -> dict:
    import httpx
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers=headers)
            return {"name": name, "url": url, "status": r.status_code, "ok": r.status_code < 400}
    except Exception as e:
        return {"name": name, "url": url, "status": 0, "ok": False, "error": str(e)[:60]}


class IntegrationCheckerAgent(BaseAgent):
    name = "integration_checker"
    capabilities = ["integration_check"]

    async def run(self, task: AgentTask) -> AgentResult:
        checks   = task.payload.get("checks", _DEFAULT_CHECKS)
        token    = task.payload.get("token", "")
        try:
            results = await asyncio.gather(
                *[_check_endpoint(c["name"], c["url"], token) for c in checks]
            )
            failed  = [r for r in results if not r["ok"]]
            passing = [r for r in results if r["ok"]]

            if failed:
                summary = (
                    f"{len(failed)} service{'s' if len(failed)>1 else ''} down: "
                    + ", ".join(r["name"] for r in failed) + ". "
                    + f"{len(passing)} passing."
                )
            else:
                summary = f"All {len(passing)} services connected and responding, sir."

            return self.result_ok(task, {"results": list(results), "failed": failed}, summary)

        except Exception as e:
            log.warn("integration_checker_error", error=str(e))
            return self.result_err(task, str(e))
