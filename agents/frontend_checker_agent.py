"""Frontend Checker Agent — reviews React/Next.js code."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class FrontendCheckerAgent(BaseAgent):
    name = "frontend_checker"
    capabilities = ["frontend_review"]

    async def run(self, task: AgentTask) -> AgentResult:
        path  = task.payload.get("path", "dashboard/frontend/src/")
        focus = task.payload.get("focus", "")
        code  = task.payload.get("code", "")
        try:
            from server.llm_router import llm
            from pathlib import Path

            if not code and path:
                p = Path(path)
                if p.is_file():
                    code = p.read_text()[:3000]
                elif p.is_dir():
                    files = list(p.rglob("*.tsx"))[:4] + list(p.rglob("*.ts"))[:2]
                    code = "\n\n".join(
                        f"// {f}\n{f.read_text()[:500]}" for f in files[:5]
                    )

            if not code:
                return self.result_err(task, "No code to review")

            prompt = (
                f"Review this React/Next.js code{' — focus: ' + focus if focus else ''}:\n\n"
                f"```tsx\n{code[:2500]}\n```\n\n"
                "Check for:\n"
                "1. Unnecessary re-renders (missing memo/callback)\n"
                "2. useEffect with missing or wrong deps\n"
                "3. Unhandled loading/error states\n"
                "4. Accessibility issues\n"
                "5. Hardcoded values that should be config\n"
                "List only real issues with component/line if known."
            )
            r = await llm.complete(prompt=prompt,
                system="Frontend code reviewer. Specific, actionable findings only.",
                max_tokens=400)
            review = r.get("text", "")

            return self.result_ok(task, {"review": review, "path": path},
                f"Frontend review of '{path}' complete.")

        except Exception as e:
            log.warn("frontend_checker_error", error=str(e))
            return self.result_err(task, str(e))
