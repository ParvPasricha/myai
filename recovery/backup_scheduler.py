"""
Backup scheduler — runs as an asyncio background task.

Schedule:
    03:00 daily  → create_snapshot()
    Sunday 03:30 → restore_snapshot(latest, dry_run=True)  [weekly restore test]

Can also be triggered manually via POST /recovery/snapshot.
"""
import asyncio
from datetime import datetime

from observability.logger import log
from recovery.snapshot import create_snapshot, list_snapshots
from recovery.restore import restore_snapshot
from security.crypto import is_unlocked


async def _daily_snapshot():
    if not is_unlocked():
        log.warn("backup_skipped", reason="vault locked")
        return
    try:
        snap_dir = create_snapshot(label="auto")
        log.info("backup_scheduled_complete", snapshot=str(snap_dir.name))
    except Exception as e:
        log.error("backup_failed", error=str(e))


async def _weekly_restore_test():
    snaps = list_snapshots()
    if not snaps:
        log.warn("restore_test_skipped", reason="no snapshots available")
        return
    latest_name = snaps[0]["name"]
    from pathlib import Path
    snap_dir = Path(__file__).parent.parent / "backups" / latest_name
    try:
        result = restore_snapshot(snap_dir, dry_run=True)
        if result["ok"]:
            log.info("restore_test_passed", snapshot=latest_name)
        else:
            log.error("restore_test_failed", snapshot=latest_name, details=result)
    except Exception as e:
        log.error("restore_test_error", error=str(e))


def _seconds_until(hour: int, minute: int = 0) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target.replace(day=target.day + 1)
    return (target - now).total_seconds()


async def run_backup_scheduler():
    log.info("backup_scheduler_started")
    while True:
        now = datetime.now()

        # Daily snapshot at 03:00
        wait = _seconds_until(3, 0)
        await asyncio.sleep(wait)
        await _daily_snapshot()

        # Weekly restore test on Sunday (weekday 6) at 03:30
        if datetime.now().weekday() == 6:
            await asyncio.sleep(30 * 60)
            await _weekly_restore_test()
