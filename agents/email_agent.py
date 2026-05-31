"""
Email Agent — Apple Mail via AppleScript.

Reading and drafting are automatic.
Sending requires iOS approval (queued via approval system).
"""
import asyncio
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from intelligence.mac_controller import run_applescript_async
from observability.logger import log


async def _get_unread(limit: int = 10) -> list[dict]:
    script = f"""
tell application "Mail"
    set msgs to {{}}
    set inbox to mailbox "INBOX" of first account
    set unread to (messages of inbox whose read status is false)
    set n to count of unread
    if n > {limit} then set n to {limit}
    repeat with i from 1 to n
        set m to item i of unread
        set end of msgs to (subject of m & " | from: " & sender of m)
    end repeat
    return msgs
end tell
"""
    try:
        result = await run_applescript_async(script)
        lines = [l.strip() for l in result.split(",") if l.strip()]
        out = []
        for l in lines:
            parts = l.split(" | from: ", 1)
            out.append({"subject": parts[0], "from": parts[1] if len(parts) > 1 else ""})
        return out
    except Exception as e:
        log.warn("email_get_unread_failed", error=str(e))
        return []


async def _queue_send_approval(to: str, subject: str, body: str) -> str:
    """Queue an outgoing email for iOS approval. Returns approval ID."""
    from server.routes.approval import create_approval
    approval_id = await asyncio.to_thread(
        create_approval, "email", to, f"Subject: {subject}\n\n{body}"
    )
    return approval_id


async def _draft_reply(subject: str, sender: str, context: str) -> str:
    from server.llm_router import llm
    result = await llm.complete(
        prompt=f"Email from {sender}, subject '{subject}':\n{context}\n\nDraft a professional reply from Parv.",
        system="Draft concise professional business emails. No filler. Sign off as 'Parv'.",
        max_tokens=300,
    )
    return result.get("text", "")


class EmailAgent(BaseAgent):
    name = "email"
    capabilities = ["email"]

    async def run(self, task: AgentTask) -> AgentResult:
        action = task.payload.get("action", "check")
        try:
            if action == "check":
                msgs = await _get_unread()
                if not msgs:
                    return self.result_ok(task, {"messages": []},
                        "Inbox is clear, sir. No unread messages.")
                summary = f"{len(msgs)} unread: " + "; ".join(
                    f"'{m['subject']}' from {m['from']}" for m in msgs[:3]
                ) + ("..." if len(msgs) > 3 else "") + "."
                return self.result_ok(task, {"messages": msgs}, summary)

            if action == "draft":
                subject = task.payload.get("subject", "")
                sender  = task.payload.get("from", "")
                context = task.payload.get("body", "")
                draft   = await _draft_reply(subject, sender, context)
                return self.result_ok(task, {"draft": draft},
                    f"Reply drafted for '{subject}'. Approve on your phone to send, sir.")

            if action == "send":
                to      = task.payload.get("to", "")
                subject = task.payload.get("subject", "")
                body    = task.payload.get("body", "")
                if not to or not subject:
                    return self.result_err(task, "Missing 'to' or 'subject'")
                appr_id = await _queue_send_approval(to, subject, body)
                return self.result_ok(task, {"approval_id": appr_id},
                    f"Email to {to} queued for approval — check your phone, sir.")

            return self.result_err(task, f"Unknown action: {action}")

        except Exception as e:
            log.warn("email_agent_error", error=str(e))
            return self.result_err(task, str(e))
