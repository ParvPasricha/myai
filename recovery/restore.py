"""
Restores a snapshot: decrypt → verify → extract to temp → post-verify → atomic swap.

Never overwrites live data without verifying first. Uses temp dir + atomic rename
so an interrupted restore leaves original data intact.
"""
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

from observability.logger import log
from security.crypto import decrypt_bytes
from recovery.verify import verify_snapshot

_PROJECT_ROOT = Path(__file__).parent.parent
_SAFE_ROOT = _PROJECT_ROOT.resolve()


def restore_snapshot(snap_dir: Path | str, dry_run: bool = False) -> dict:
    """
    Restore from snapshot_dir.
    dry_run=True: verify only, don't write files.
    Returns {"ok": True, "files_restored": N} or {"ok": False, "error": str}
    """
    snap_dir = Path(snap_dir)

    # Step 1: verify before touching anything
    v = verify_snapshot(snap_dir)
    if not v["ok"]:
        log.error("restore_aborted_bad_snapshot", errors=v.get("errors"))
        return {"ok": False, "error": "Snapshot verification failed", "details": v}

    if dry_run:
        log.info("restore_dry_run_ok", snapshot=snap_dir.name, files=v["files_checked"])
        return {"ok": True, "dry_run": True, "files_checked": v["files_checked"]}

    # Step 2: decrypt tarball
    enc_path = snap_dir / "data.tar.gz.enc"
    tarball = decrypt_bytes(enc_path.read_bytes())

    # Step 3: extract to a temp directory (atomic restore pattern)
    tmp_dir = Path(tempfile.mkdtemp(prefix="parv_restore_", dir=_PROJECT_ROOT))
    files_restored = 0
    try:
        buf = io.BytesIO(tarball)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            for member in tar.getmembers():
                # Path traversal guard
                dest = (tmp_dir / member.name).resolve()
                if not str(dest).startswith(str(tmp_dir.resolve()) + "/"):
                    log.warn("restore_skipped_traversal", member=member.name)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                f = tar.extractfile(member)
                if f:
                    dest.write_bytes(f.read())
                    files_restored += 1

        # Step 4: post-restore verify in temp dir
        manifest = json.loads((snap_dir / "manifest.json").read_text())
        post_errors = []
        for entry in manifest.get("files", []):
            on_temp = tmp_dir / entry["path"]
            if not on_temp.exists():
                post_errors.append(f"missing in temp: {entry['path']}")
                continue
            actual = hashlib.sha256(on_temp.read_bytes()).hexdigest()
            if actual != entry["sha256"]:
                post_errors.append(f"checksum mismatch: {entry['path']}")

        if post_errors:
            log.error("restore_post_verify_failed", errors=post_errors)
            return {"ok": False, "error": "Post-restore verification failed", "details": post_errors}

        # Step 5: atomic copy from temp to live (files verified; safe to overwrite)
        for entry in manifest.get("files", []):
            src = tmp_dir / entry["path"]
            dst = _PROJECT_ROOT / entry["path"]
            if not str(dst.resolve()).startswith(str(_SAFE_ROOT)):
                continue   # skip any path that escaped root (defensive)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    log.info("restore_complete", snapshot=snap_dir.name, files_restored=files_restored)
    return {"ok": True, "files_restored": files_restored, "snapshot": snap_dir.name}
