"""
Screen Monitor — passive background observer.

Captures screen state every 30s using screencapture + osascript.
Detects significant changes via MD5 diff.
Asks LLM to categorize the activity, feeds into learning engine.

Requires macOS Screen Recording permission:
  System Settings → Privacy & Security → Screen Recording → enable Terminal/Python
"""
import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path

from observability.logger import log

_INTERVAL   = 30          # seconds between captures
_SCREENSHOT = Path("/tmp/parv_ai_screen.png")
_prev_hash  = ""
_running    = False

_CATEGORIZE_SYSTEM = (
    "Categorize screen activity. Return ONLY valid JSON — no other text."
)


def _screenshot() -> bytes | None:
    try:
        subprocess.run(
            ["screencapture", "-x", "-t", "png", str(_SCREENSHOT)],
            timeout=5, check=True, capture_output=True,
        )
        return _SCREENSHOT.read_bytes()
    except Exception:
        return None


def _active_context() -> dict:
    """Get frontmost app and window title via osascript."""
    app, window = "unknown", ""
    try:
        app = subprocess.check_output(
            ["osascript", "-e",
             'tell application "System Events" to get name of '
             'first application process whose frontmost is true'],
            timeout=3, text=True,
        ).strip()
    except Exception:
        pass
    try:
        window = subprocess.check_output(
            ["osascript", "-e",
             'tell application "System Events" to get title of '
             'front window of (first application process whose frontmost is true)'],
            timeout=3, text=True,
        ).strip()
    except Exception:
        pass
    return {"app": app, "window": window}


async def _categorize(ctx: dict) -> dict:
    """Ask LLM what the user is doing."""
    try:
        from server.llm_router import llm
        prompt = (
            f"Screen state:\nApp: {ctx['app']}\nWindow: {ctx.get('window', '')}\n\n"
            f"What is the user doing? "
            f'Return JSON: {{"activity":"one sentence","type":"coding|research|communication|design|reading|other","domain":"..."}}'
        )
        result = await llm.complete(
            prompt=prompt, system=_CATEGORIZE_SYSTEM, max_tokens=80
        )
        text = result.get("text", "")
        start = text.find("{")
        end   = text.rfind("}") + 1
        return json.loads(text[start:end]) if start >= 0 else {}
    except Exception:
        return {"activity": f"Using {ctx['app']}", "type": "other", "domain": "general"}


async def run_screen_monitor() -> None:
    global _prev_hash, _running
    _running = True
    log.info("screen_monitor_started", interval_s=_INTERVAL)

    while _running:
        try:
            ctx  = _active_context()
            data = _screenshot()

            changed = False
            if data:
                h = hashlib.md5(data).hexdigest()
                changed   = h != _prev_hash
                _prev_hash = h

            if changed or not _prev_hash:
                parsed = await _categorize(ctx)
                from intelligence.learning_engine import learn_from_screen
                await learn_from_screen(
                    app=ctx["app"],
                    window=ctx.get("window", ""),
                    activity=parsed.get("activity", ""),
                    activity_type=parsed.get("type", "other"),
                    changed=changed,
                )
                log.debug("screen_observed", app=ctx["app"], type=parsed.get("type"))

        except Exception as e:
            log.debug("screen_monitor_tick_error", error=str(e))

        await asyncio.sleep(_INTERVAL)


def stop() -> None:
    global _running
    _running = False
