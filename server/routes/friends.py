"""
Friend token management.

Friends get a signed JWT with scope="friend" and an optional expiry.
The token is embedded in a shareable URL:
    http://your-server:3000/?token=<jwt>

Friend tokens are read-only — they can view the dashboard but not modify anything.

    POST /friends/token     — issue a new friend token (JWT required)
    GET  /friends           — list issued tokens
    DELETE /friends/{name}  — revoke a friend's token
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import hashlib
import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
from server.config import JWT_SECRET, JWT_ALGORITHM
from observability.logger import log

router = APIRouter()

_TOKENS_FILE = Path(__file__).parent.parent.parent / "memory" / "friend_tokens.json"
_TOKENS_FILE.parent.mkdir(exist_ok=True)


def _load_tokens() -> dict:
    if _TOKENS_FILE.exists():
        return json.loads(_TOKENS_FILE.read_text())
    return {}


def _save_tokens(tokens: dict):
    _TOKENS_FILE.write_text(json.dumps(tokens, indent=2))


def create_friend_token(name: str, expires_days: Optional[int] = None) -> str:
    payload = {
        "sub": f"friend:{name}",
        "scope": "friend",
        "name": name,
        "iat": time.time(),
    }
    if expires_days is not None:
        payload["exp"] = datetime.now(timezone.utc) + timedelta(days=expires_days)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_friend_token(token: str) -> Optional[dict]:
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if data.get("scope") != "friend":
            return None
        return data
    except Exception:
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

class TokenBody(BaseModel):
    name: str               # friend's name (for tracking)
    expires_days: Optional[int] = None    # None = never expires

@router.post("/friends/token")
async def issue_token(body: TokenBody, _auth: dict = Depends(require_auth)):
    token = create_friend_token(body.name, body.expires_days)

    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]  # store prefix-hash, not raw JWT
    tokens = _load_tokens()
    tokens[body.name] = {
        "token_hash": token_hash,   # only a hash — raw JWT never written to disk
        "issued_at": time.time(),
        "expires_days": body.expires_days,
        "name": body.name,
    }
    _save_tokens(tokens)

    # Build the shareable dashboard URL
    dashboard_url = f"http://localhost:3000/?token={token}"
    log.info("friend_token_issued", name=body.name, expires=body.expires_days)

    return {
        "ok": True,
        "name": body.name,
        "token": token,
        "dashboard_url": dashboard_url,
        "expires_days": body.expires_days,
    }


@router.get("/friends")
async def list_friends(_auth: dict = Depends(require_auth)):
    tokens = _load_tokens()
    # Strip the actual token from the list for safety
    friends = [
        {
            "name": v["name"],
            "issued_at": v["issued_at"],
            "expires_days": v["expires_days"],
        }
        for v in tokens.values()
    ]
    return {"friends": friends}


@router.delete("/friends/{name}")
async def revoke_token(name: str, _auth: dict = Depends(require_auth)):
    tokens = _load_tokens()
    if name not in tokens:
        raise HTTPException(status_code=404, detail=f"No token for '{name}'")
    del tokens[name]
    _save_tokens(tokens)
    log.info("friend_token_revoked", name=name)
    return {"ok": True, "revoked": name}
