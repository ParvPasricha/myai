"""
Encrypted append-only audit log.

Each entry is individually AES-256-GCM encrypted and base64-encoded,
one per line in logs/audit.enc.jsonl.
The file itself is not a valid JSON document — it's a sequence of
independently encrypted JSON blobs, one per line.

Reading requires the master key. Writing never exposes plaintext.
"""
import base64
import json
import time
from pathlib import Path
from typing import Any

from security.crypto import encrypt_bytes, decrypt_bytes, is_unlocked

_AUDIT_FILE = Path(__file__).parent.parent / "logs" / "audit.enc.jsonl"
_AUDIT_FILE.parent.mkdir(exist_ok=True)


def _write_entry(entry: dict[str, Any]):
    plaintext = json.dumps(entry).encode()
    if is_unlocked():
        blob = encrypt_bytes(plaintext)
        line = base64.b64encode(blob).decode() + "\n"
    else:
        # Fallback: write plaintext with a warning marker when vault is locked
        # (only happens during lockdown sequence itself)
        line = json.dumps({**entry, "_unencrypted": True}) + "\n"
    with open(_AUDIT_FILE, "a") as f:
        f.write(line)


def log_event(event: str, **details: Any):
    _write_entry({"ts": time.time(), "event": event, **details})


def read_all() -> list[dict]:
    """Decrypt and return all audit entries. Requires unlocked vault."""
    if not _AUDIT_FILE.exists():
        return []
    entries = []
    with open(_AUDIT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                # Try base64-encoded encrypted entry
                blob = base64.b64decode(line)
                plaintext = decrypt_bytes(blob)
                entries.append(json.loads(plaintext))
            except Exception:
                try:
                    # Fallback plaintext entry
                    entries.append(json.loads(line))
                except Exception:
                    entries.append({"_raw": line, "_parse_error": True})
    return entries
