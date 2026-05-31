"""
Message Agent — iMessage via Apple Messages.app.
ALL sends require iOS approval before execution.
"""
import asyncio
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from intelligence.mac_controller import run_applescript_async
from observability.logger import log


async def _send_imessage(to: str, body: str) -> bool:
    script = f"""
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "{to}" of targetService
    send "{body}" to targetBuddy
end tell
"""
    try:
        await run_applescript_async(script)
        return True
    except Exception as e:
        log.warn("imessage_send_failed", error=str(e))
        return False


class MessageAgent(BaseAgent):
    name = "message"
    capabilities = ["message"]

    async def run(self, task: AgentTask) -> AgentResult:
        to   = task.payload.get("to", "")
        body = task.payload.get("body", "")
        approved = task.payload.get("approved", False)   # set True only by approval callback

        if not to or not body:
            return self.result_err(task, "Missing 'to' or 'body'")

        try:
            if not approved:
                # Queue for iOS approval
                from server.routes.approval import create_approval
                appr_id = await asyncio.to_thread(create_approval, "message", to, body)
                return self.result_ok(task, {"approval_id": appr_id},
                    f"Message to {to} pending your approval on the phone, sir.")

            # Approved — send now
            ok = await _send_imessage(to, body)
            return self.result_ok(task, {"to": to, "sent": ok},
                f"Message sent to {to}, sir.") if ok \
                else self.result_err(task, "iMessage send failed — check Messages.app permissions.")

        except Exception as e:
            log.warn("message_agent_error", error=str(e))
            return self.result_err(task, str(e))
