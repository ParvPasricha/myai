"""DB Agent — schema review, migration safety, query optimisation."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class DbAgent(BaseAgent):
    name = "db"
    capabilities = ["db_review"]

    async def run(self, task: AgentTask) -> AgentResult:
        schema = task.payload.get("schema", "")
        query  = task.payload.get("query", "")
        path   = task.payload.get("path", "")
        focus  = task.payload.get("focus", "")
        try:
            from server.llm_router import llm
            from pathlib import Path

            # Auto-extract schema from SQLite if path given
            if not schema and path:
                import sqlite3
                try:
                    conn = sqlite3.connect(path)
                    rows = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                    schema = "\n".join(r[0] for r in rows if r[0])
                    conn.close()
                except Exception:
                    pass

            if not schema and not query:
                # Default to reading the main intelligence DB
                try:
                    import sqlite3
                    conn = sqlite3.connect("memory/intelligence.db")
                    rows = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                    schema = "\n".join(r[0] for r in rows if r[0])
                    conn.close()
                except Exception:
                    pass

            prompt_parts = [f"DB review{' — focus: ' + focus if focus else ''}:\n"]
            if schema:
                prompt_parts.append(f"Schema:\n```sql\n{schema[:1500]}\n```\n")
            if query:
                prompt_parts.append(f"Query to review:\n```sql\n{query}\n```\n")
            prompt_parts.append(
                "Check:\n"
                "1. Missing indexes on frequently queried columns\n"
                "2. N+1 query risks\n"
                "3. Missing foreign key constraints\n"
                "4. Migration safety (data loss risk)\n"
                "5. Type mismatches or nullable columns that should be NOT NULL\n"
                "List only real issues."
            )

            r = await llm.complete(
                prompt="\n".join(prompt_parts),
                system="Database reviewer. Flag concrete schema and query issues only.",
                max_tokens=400,
            )
            review = r.get("text", "")

            return self.result_ok(task, {"review": review},
                "Database review complete — check dashboard for findings, sir.")

        except Exception as e:
            log.warn("db_agent_error", error=str(e))
            return self.result_err(task, str(e))
