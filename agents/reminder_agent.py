"""Reminder Agent — Apple Reminders via AppleScript."""
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from intelligence.mac_controller import run_applescript_async
from observability.logger import log


async def _create_reminder(title: str, due: str = "", notes: str = "") -> bool:
    due_line = f'\nset due date of newReminder to date "{due}"' if due else ""
    notes_line = f'\nset body of newReminder to "{notes}"' if notes else ""
    script = f"""
tell application "Reminders"
    set newReminder to make new reminder at end of default list
    set name of newReminder to "{title}"{due_line}{notes_line}
end tell
"""
    try:
        await run_applescript_async(script)
        return True
    except Exception as e:
        log.warn("reminder_create_failed", error=str(e))
        return False


async def _list_due_today() -> list[str]:
    script = """
tell application "Reminders"
    set todayReminders to {}
    set today to current date
    repeat with r in (reminders whose completed is false)
        try
            if due date of r is not missing value then
                if (due date of r) - today < 86400 then
                    set end of todayReminders to name of r
                end if
            end if
        end try
    end repeat
    return todayReminders
end tell
"""
    try:
        result = await run_applescript_async(script)
        return [r.strip() for r in result.split(",") if r.strip()]
    except Exception:
        return []


class ReminderAgent(BaseAgent):
    name = "reminder"
    capabilities = ["reminder"]

    async def run(self, task: AgentTask) -> AgentResult:
        action = task.payload.get("action", "list")
        try:
            if action == "create":
                title = task.payload.get("title", "")
                if not title:
                    return self.result_err(task, "No reminder title provided")
                due   = task.payload.get("due", "")
                notes = task.payload.get("notes", "")
                ok = await _create_reminder(title, due, notes)
                msg = f"Reminder '{title}' created{' for ' + due if due else ''}, sir."
                return self.result_ok(task, {"title": title, "due": due}, msg) if ok \
                    else self.result_err(task, "Failed to create reminder")

            # Default: list due today
            items = await _list_due_today()
            if not items:
                return self.result_ok(task, {"reminders": []},
                    "No reminders due today, sir.")
            summary = f"{len(items)} reminder{'s' if len(items) > 1 else ''} due today: " \
                      + ", ".join(items[:5]) + ("..." if len(items) > 5 else "") + "."
            return self.result_ok(task, {"reminders": items}, summary)

        except Exception as e:
            log.warn("reminder_agent_error", error=str(e))
            return self.result_err(task, str(e))
