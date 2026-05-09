"""
Dead Man's Switch.

The iPhone app sends POST /security/ping every N minutes.
A background asyncio task checks the timestamp every 10 seconds.
If now - last_ping > threshold → lockdown sequence fires.

State is RAM-only. Intentional: a server crash + restart requires
manual re-authentication, which is correct security behaviour.
"""
import asyncio
import time
from typing import Callable, Optional

from observability.logger import log
from observability.metrics import deadman_seconds_remaining, alert_fires
from security.audit import log_event

# ── State (RAM only) ──────────────────────────────────────────────────────────
_last_ping: float = time.time()          # initialised to now; arm after first real ping
_threshold_minutes: int = 60             # default: 1 hour
_armed: bool = False                     # requires explicit arming via arm()
_locked: bool = False
_locked_at: Optional[float] = None
_on_lockdown_hooks: list[Callable] = []  # callables invoked during lockdown


def arm():
    """Call once after server unlocks with master password."""
    global _armed, _last_ping
    _armed = True
    _last_ping = time.time()
    log.info("deadman_armed", threshold_minutes=_threshold_minutes)
    log_event("deadman_armed", threshold_minutes=_threshold_minutes)


def ping() -> dict:
    """Record a heartbeat. Called from POST /security/ping."""
    global _last_ping
    if _locked:
        return {"ok": False, "error": "System is locked"}
    _last_ping = time.time()
    remaining = _threshold_seconds()   # full threshold from this ping
    deadman_seconds_remaining.set(remaining if _armed else 0)
    return {"ok": True, "next_deadline": _last_ping + _threshold_seconds()}


def set_threshold(minutes: int):
    global _threshold_minutes
    _threshold_minutes = max(1, minutes)
    log.info("deadman_threshold_updated", minutes=_threshold_minutes)
    log_event("deadman_threshold_updated", minutes=_threshold_minutes)


def status() -> dict:
    remaining = max(0.0, (_last_ping + _threshold_seconds()) - time.time())
    return {
        "armed": _armed,
        "locked": _locked,
        "locked_at": _locked_at,
        "threshold_minutes": _threshold_minutes,
        "last_ping": _last_ping,
        "time_remaining_seconds": round(remaining),
        "time_remaining_pct": round(remaining / _threshold_seconds() * 100, 1),
    }


def register_lockdown_hook(fn: Callable):
    """Register a coroutine or function called during lockdown (e.g., encrypt data)."""
    _on_lockdown_hooks.append(fn)


def _threshold_seconds() -> float:
    return _threshold_minutes * 60.0


async def _lockdown():
    global _locked, _locked_at
    if _locked:
        return
    _locked = True
    _locked_at = time.time()
    deadman_seconds_remaining.set(0)
    alert_fires.labels(alert_name="deadman_lockdown").inc()

    log.error("deadman_lockdown_triggered", threshold_minutes=_threshold_minutes)
    log_event("deadman_lockdown", threshold_minutes=_threshold_minutes)

    print("\n🔒  DEADMAN LOCKDOWN — encrypting data and shutting down...\n")

    # Wipe master key FIRST before any hooks run — closes the in-flight decryption window
    from security.crypto import lock
    lock()
    log_event("master_key_wiped")
    log.info("master_key_wiped")

    # Run registered hooks (encrypt databases, etc.) — key is already gone
    for hook in _on_lockdown_hooks:
        try:
            if asyncio.iscoroutinefunction(hook):
                await hook()
            else:
                hook()
        except Exception as e:
            log.error("lockdown_hook_error", error=str(e))

    print("🔒  System locked. Restart server and enter master password to unlock.\n")


async def run_deadman_loop(check_interval: int = 10):
    """Background task. Check every `check_interval` seconds."""
    log.info("deadman_loop_started", check_interval=check_interval)
    while True:
        await asyncio.sleep(check_interval)
        if not _armed or _locked:
            continue
        remaining = (_last_ping + _threshold_seconds()) - time.time()
        deadman_seconds_remaining.set(max(0.0, remaining))
        if remaining <= 0:
            await _lockdown()
