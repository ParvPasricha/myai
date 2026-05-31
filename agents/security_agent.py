"""Security Agent — OWASP audit, auth checks, secrets scanning."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class SecurityAgent(BaseAgent):
    name = "security"
    capabilities = ["security_review"]

    async def run(self, task: AgentTask) -> AgentResult:
        path  = task.payload.get("path", "server/")
        focus = task.payload.get("focus", "")
        code  = task.payload.get("code", "")
        try:
            from server.llm_router import llm
            from pathlib import Path
            import subprocess, re

            # Grep for common secrets patterns
            findings: list[str] = []
            try:
                result = subprocess.run(
                    ["grep", "-rn", "--include=*.py",
                     "-E", r"(api_key|secret|password|token)\s*=\s*['\"][^'\"]{8,}",
                     path],
                    capture_output=True, text=True, timeout=10,
                )
                if result.stdout:
                    for line in result.stdout.splitlines()[:5]:
                        findings.append(f"Potential hardcoded secret: {line[:100]}")
            except Exception:
                pass

            if not code and path:
                p = Path(path)
                if p.is_file():
                    code = p.read_text()[:3000]
                elif p.is_dir():
                    files = list(p.rglob("*.py"))[:4]
                    code = "\n\n".join(f"# {f}\n{f.read_text()[:600]}" for f in files)

            prompt = (
                f"Security audit of this code{' — focus: ' + focus if focus else ''}:\n\n"
                f"```python\n{code[:2000]}\n```\n\n"
                "Check for OWASP Top 10:\n"
                "1. Injection (SQL, command, path traversal)\n"
                "2. Broken auth / missing auth guards\n"
                "3. Exposed sensitive data\n"
                "4. Insecure deserialisation\n"
                "5. Missing rate limiting\n"
                "List only confirmed or high-probability issues."
            )
            r = await llm.complete(prompt=prompt,
                system="Security auditor. Flag only real vulnerabilities. Be specific about file and line.",
                max_tokens=400)
            review = r.get("text", "")

            all_findings = findings + [review]
            summary = (
                f"{len(findings)} hardcoded secret pattern{'s' if len(findings)!=1 else ''} found. " +
                "Security review complete — check dashboard for full report."
                if findings else "Security review complete — check dashboard for full report."
            )

            return self.result_ok(task, {"review": review, "grep_findings": findings}, summary)

        except Exception as e:
            log.warn("security_agent_error", error=str(e))
            return self.result_err(task, str(e))
