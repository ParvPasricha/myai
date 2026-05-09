"""
Security routes:
    POST /security/ping          — heartbeat from iPhone
    GET  /security/status        — deadman status + lock state
    PATCH /security/timer        — update threshold
    POST /security/unlock        — submit master password
    GET  /security/audit         — read audit log (requires unlock)
    POST /security/encrypt       — encrypt a payload
    POST /security/decrypt       — decrypt a payload
    POST /recovery/snapshot      — manual snapshot
    GET  /recovery/snapshots     — list snapshots
    POST /recovery/restore       — restore from named snapshot
"""
import getpass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
from security import deadman, crypto, encrypter, audit
from recovery.snapshot import create_snapshot, list_snapshots
from recovery.restore import restore_snapshot
from recovery.verify import verify_snapshot
from observability.logger import log

router = APIRouter()

# ── Rate-limit state for /security/unlock ─────────────────────────────────────
import time as _time_mod
_unlock_attempts: int = 0
_unlock_lockout_until: float = 0.0
_MAX_UNLOCK_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300   # 5 min after 5 wrong attempts

# ── Auth / Unlock ─────────────────────────────────────────────────────────────

class UnlockBody(BaseModel):
    password: str

@router.post("/security/unlock")
async def unlock(body: UnlockBody):
    global _unlock_attempts, _unlock_lockout_until

    now = _time_mod.time()
    if now < _unlock_lockout_until:
        retry_in = round(_unlock_lockout_until - now)
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Retry in {retry_in}s.")

    ok = crypto.unlock(body.password)
    if not ok:
        _unlock_attempts += 1
        if _unlock_attempts >= _MAX_UNLOCK_ATTEMPTS:
            _unlock_lockout_until = now + _LOCKOUT_SECONDS
            _unlock_attempts = 0
            log.warn("unlock_lockout_triggered", lockout_seconds=_LOCKOUT_SECONDS)
        raise HTTPException(status_code=401, detail="Invalid master password")

    _unlock_attempts = 0   # reset on success
    deadman.arm()
    audit.log_event("vault_unlocked")
    log.info("vault_unlocked")
    return {"ok": True, "message": "Vault unlocked. Dead man's switch armed."}


# ── Dead Man's Switch ─────────────────────────────────────────────────────────

@router.post("/security/ping")
async def ping(_auth: dict = Depends(require_auth)):
    result = deadman.ping()
    return result


@router.get("/security/status")
async def security_status(_auth: dict = Depends(require_auth)):
    return {
        **deadman.status(),
        "vault_unlocked": crypto.is_unlocked(),
    }


class TimerBody(BaseModel):
    minutes: int

@router.patch("/security/timer")
async def update_timer(body: TimerBody, _auth: dict = Depends(require_auth)):
    deadman.set_threshold(body.minutes)
    audit.log_event("timer_updated", minutes=body.minutes)
    return {"ok": True, "threshold_minutes": body.minutes}


# ── Audit Log ─────────────────────────────────────────────────────────────────

@router.get("/security/audit")
async def get_audit(_auth: dict = Depends(require_auth)):
    if not crypto.is_unlocked():
        raise HTTPException(status_code=403, detail="Vault is locked")
    entries = audit.read_all()
    return {"count": len(entries), "entries": entries[-100:]}  # last 100


# ── Payload Encrypter ─────────────────────────────────────────────────────────

class EncryptBody(BaseModel):
    data_b64: str   # base64-encoded bytes to encrypt

class DecryptBody(BaseModel):
    payload: str    # base64-encoded encrypted blob

@router.post("/security/encrypt")
async def encrypt_payload(body: EncryptBody, _auth: dict = Depends(require_auth)):
    if not crypto.is_unlocked():
        raise HTTPException(status_code=403, detail="Vault is locked")
    import base64
    raw = base64.b64decode(body.data_b64)
    encrypted = encrypter.encrypt_payload(raw)
    audit.log_event("payload_encrypted", size_bytes=len(raw))
    return {"payload": encrypted}

@router.post("/security/decrypt")
async def decrypt_payload(body: DecryptBody, _auth: dict = Depends(require_auth)):
    if not crypto.is_unlocked():
        raise HTTPException(status_code=403, detail="Vault is locked")
    import base64
    raw = encrypter.decrypt_payload(body.payload)
    return {"data_b64": base64.b64encode(raw).decode()}


# ── Recovery ──────────────────────────────────────────────────────────────────

@router.post("/recovery/snapshot")
async def manual_snapshot(_auth: dict = Depends(require_auth)):
    if not crypto.is_unlocked():
        raise HTTPException(status_code=403, detail="Vault is locked — cannot snapshot")
    snap_dir = create_snapshot(label="manual")
    audit.log_event("manual_snapshot", name=snap_dir.name)
    return {"ok": True, "snapshot": snap_dir.name}


@router.get("/recovery/snapshots")
async def get_snapshots(_auth: dict = Depends(require_auth)):
    return {"snapshots": list_snapshots()}


class RestoreBody(BaseModel):
    snapshot_name: str
    dry_run: bool = True

@router.post("/recovery/restore")
async def restore(body: RestoreBody, _auth: dict = Depends(require_auth)):
    if not crypto.is_unlocked():
        raise HTTPException(status_code=403, detail="Vault is locked")
    backups_root = (Path(__file__).parent.parent.parent / "backups").resolve()
    snap_dir = (backups_root / body.snapshot_name).resolve()
    # Path traversal guard — resolved path must stay inside backups/
    if not str(snap_dir).startswith(str(backups_root) + "/"):
        raise HTTPException(status_code=400, detail="Invalid snapshot name")
    if not snap_dir.exists():
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {body.snapshot_name}")
    result = restore_snapshot(snap_dir, dry_run=body.dry_run)
    if result["ok"] and not body.dry_run:
        audit.log_event("restore_complete", snapshot=body.snapshot_name)
    return result


# ── Tor Hidden Service ────────────────────────────────────────────────────────

@router.post("/security/tor/start")
async def tor_start(_auth: dict = Depends(require_auth)):
    from security.tor_manager import start
    result = await start()
    if result.get("onion"):
        audit.log_event("tor_started", onion=result["onion"])
    return result


@router.post("/security/tor/stop")
async def tor_stop(_auth: dict = Depends(require_auth)):
    from security.tor_manager import stop
    result = stop()
    audit.log_event("tor_stopped")
    return result


@router.get("/security/tor/status")
async def tor_status(_auth: dict = Depends(require_auth)):
    from security.tor_manager import status
    return status()


@router.get("/security/onion")
async def get_onion(_auth: dict = Depends(require_auth)):
    """Quick endpoint to get the current .onion address for iPhone config."""
    from security.tor_manager import get_onion_address
    onion = get_onion_address()
    if not onion:
        return {"onion": None, "message": "Tor not started yet. POST /security/tor/start first."}
    return {
        "onion": onion,
        "api_url": f"http://{onion}",
        "dashboard_url": f"http://{onion}:3000",
        "socks_proxy": "127.0.0.1:9050",
        "ios_instructions": "Install Orbot from App Store. Enable VPN mode. App will route through .onion automatically.",
    }
