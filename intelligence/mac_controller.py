"""
Mac Controller — safe AppleScript + shell executor.

All actions are logged to unified memory. Sensitive ops (send message,
send email) must go through the approval gate before execution.
"""
import asyncio
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from observability.logger import log

# Allowlisted AppleScript verbs — prevents arbitrary code injection
_ALLOWED_PREFIXES = (
    "tell application \"Music\"",
    "tell application \"Mail\"",
    "tell application \"Messages\"",
    "tell application \"Reminders\"",
    "tell application \"Safari\"",
    "tell application \"System Events\"",
    "tell application \"Finder\"",
    "return POSIX path",
    "set volume",
    "display notification",
)


def _is_safe(script: str) -> bool:
    stripped = script.strip()
    return any(stripped.startswith(p) for p in _ALLOWED_PREFIXES)


def run_applescript(script: str, unsafe: bool = False) -> str:
    """
    Run AppleScript synchronously. Raises ValueError if script is not allowlisted.
    Returns stdout string or raises on error.
    """
    if not unsafe and not _is_safe(script):
        raise ValueError(f"AppleScript not in allowlist: {script[:80]}")

    with tempfile.NamedTemporaryFile(suffix=".applescript", mode="w", delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        result = subprocess.run(
            ["osascript", script_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")
        output = result.stdout.strip()
        log.info("applescript_ok", script_preview=script[:60])
        return output
    finally:
        Path(script_path).unlink(missing_ok=True)


async def run_applescript_async(script: str, unsafe: bool = False) -> str:
    return await asyncio.to_thread(run_applescript, script, unsafe)


def run_shell(command: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a shell command. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    log.debug("shell_run", cmd=command[0], rc=result.returncode)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


async def run_shell_async(command: list[str], timeout: int = 30) -> tuple[int, str, str]:
    return await asyncio.to_thread(run_shell, command, timeout)


def notify(title: str, message: str, subtitle: str = "") -> None:
    """Show a macOS notification."""
    sub = f', subtitle:"{subtitle}"' if subtitle else ""
    script = f'display notification "{message}" with title "{title}"{sub}'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception as e:
        log.warn("notify_failed", error=str(e))


async def notify_async(title: str, message: str, subtitle: str = "") -> None:
    await asyncio.to_thread(notify, title, message, subtitle)
