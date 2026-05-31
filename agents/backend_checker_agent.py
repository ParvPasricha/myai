"""Backend Checker Agent — reviews Python/FastAPI code for correctness and patterns."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class BackendCheckerAgent(BaseAgent):
    name = "backend_checker"
    capabilities = ["backend_review"]

    async def run(self, task: AgentTask) -> AgentResult:
        path    = task.payload.get("path", "server/")
        focus   = task.payload.get("focus", "")
        code    = task.payload.get("code", "")
        try:
            from server.llm_router import llm
            from pathlib import Path

            # Read code if path given and no code pasted
            if not code and path:
                p = Path(path)
                if p.is_file():
                    code = p.read_text()[:3000]
                elif p.is_dir():
                    files = list(p.rglob("*.py"))[:5]
                    code = "\n\n".join(
                        f"# {f}\n{f.read_text()[:600]}" for f in files
                    )

            if not code:
                return self.result_err(task, "No code to review — provide path or code")

            prompt = (
                f"Review this Python/FastAPI code{' — focus: ' + focus if focus else ''}:\n\n"
                f"```python\n{code[:2500]}\n```\n\n"
                "Check for:\n"
                "1. Input validation gaps\n"
                "2. Error handling coverage\n"
                "3. Async/await correctness\n"
                "4. Performance issues (N+1 queries, blocking calls)\n"
                "5. Missing auth checks\n"
                "List only real issues with file:line if known. No padding."
            )
            r = await llm.complete(prompt=prompt,
                system="Backend code reviewer. Be specific and direct. Flag real issues only.",
                max_tokens=400)
            review = r.get("text", "")

            return self.result_ok(task, {"review": review, "path": path},
                f"Backend review of '{path}' complete — {len(review.splitlines())} findings.")

        except Exception as e:
            log.warn("backend_checker_error", error=str(e))
            return self.result_err(task, str(e))
