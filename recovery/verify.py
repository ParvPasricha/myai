"""
Verifies snapshot integrity before restore.

Checks:
1. manifest.json is readable and complete
2. data.tar.gz.enc exists and is decryptable
3. Every file in manifest matches its stored SHA-256
"""
import hashlib
import io
import json
import tarfile
from pathlib import Path

from observability.logger import log
from security.crypto import decrypt_bytes


def verify_snapshot(snap_dir: Path) -> dict:
    """
    Verify a snapshot directory. Returns:
        {"ok": True, "files_checked": N}
        {"ok": False, "errors": [...]}
    """
    errors = []
    snap_dir = Path(snap_dir)

    manifest_path = snap_dir / "manifest.json"
    enc_path = snap_dir / "data.tar.gz.enc"

    if not manifest_path.exists():
        return {"ok": False, "errors": ["manifest.json missing"]}
    if not enc_path.exists():
        return {"ok": False, "errors": ["data.tar.gz.enc missing"]}

    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as e:
        return {"ok": False, "errors": [f"manifest parse error: {e}"]}

    # Decrypt and open tarball
    try:
        blob = enc_path.read_bytes()
        tarball = decrypt_bytes(blob)
    except Exception as e:
        return {"ok": False, "errors": [f"decryption failed: {e}"]}

    try:
        buf = io.BytesIO(tarball)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            members = {m.name: m for m in tar.getmembers()}
    except Exception as e:
        return {"ok": False, "errors": [f"tarball open failed: {e}"]}

    # Verify each file's checksum
    for entry in manifest.get("files", []):
        path = entry["path"]
        expected_sha = entry["sha256"]
        if path not in members:
            errors.append(f"missing in archive: {path}")
            continue
        member = members[path]
        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            f = tar.extractfile(member)
            if f is None:
                errors.append(f"cannot extract: {path}")
                continue
            actual_sha = hashlib.sha256(f.read()).hexdigest()
            if actual_sha != expected_sha:
                errors.append(f"checksum mismatch: {path}")

    ok = len(errors) == 0
    result = {"ok": ok, "files_checked": len(manifest.get("files", []))}
    if errors:
        result["errors"] = errors
    log.info("snapshot_verified", snapshot=snap_dir.name, ok=ok, errors=len(errors))
    return result
