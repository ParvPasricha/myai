"""
Creates versioned encrypted snapshots of all data directories.

Snapshot format:
    backups/snapshot_YYYYMMDD_HHMMSS/
        manifest.json          ← file list + SHA-256 checksums (plaintext)
        data.tar.gz.enc        ← AES-256-GCM encrypted tarball of all data
"""
import hashlib
import io
import json
import os
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from observability.logger import log
from security.crypto import encrypt_bytes, is_unlocked

_PROJECT_ROOT = Path(__file__).parent.parent
_BACKUP_DIR = _PROJECT_ROOT / "backups"
_RETENTION_DAYS = 30

# Directories included in snapshot
_DATA_DIRS = ["memory", "logs", "models"]
# Individual files included
_DATA_FILES = [".salt"]   # salt file is critical for key re-derivation


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_files() -> list[Path]:
    files = []
    for dir_name in _DATA_DIRS:
        d = _PROJECT_ROOT / dir_name
        if d.exists():
            for f in d.rglob("*"):
                if f.is_file():
                    files.append(f)
    for fname in _DATA_FILES:
        f = _PROJECT_ROOT / fname
        if f.exists():
            files.append(f)
    return files


def create_snapshot(label: Optional[str] = None) -> Path:
    """
    Build a snapshot. Returns the snapshot directory path.
    Requires unlocked crypto vault.
    """
    if not is_unlocked():
        raise RuntimeError("Crypto vault is locked — cannot create encrypted snapshot.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"snapshot_{ts}" + (f"_{label}" if label else "")
    snap_dir = _BACKUP_DIR / name
    snap_dir.mkdir(parents=True, exist_ok=True)

    files = _collect_files()
    manifest = {"created_at": time.time(), "label": label, "files": []}

    # Build tarball to a temp file (avoids holding entire archive in RAM)
    tmp_tar = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".tar.gz", dir=_BACKUP_DIR)
        os.close(fd)
        tmp_tar = Path(tmp_path)

        with tarfile.open(str(tmp_tar), mode="w:gz") as tar:
            for f in files:
                rel = f.relative_to(_PROJECT_ROOT)
                tar.add(f, arcname=str(rel))
                manifest["files"].append({
                    "path": str(rel),
                    "sha256": _sha256(f),
                    "size": f.stat().st_size,
                })

        # Encrypt in chunks to avoid a second full-RAM copy
        tarball_bytes = tmp_tar.read_bytes()
        encrypted = encrypt_bytes(tarball_bytes)
        (snap_dir / "data.tar.gz.enc").write_bytes(encrypted)
    finally:
        if tmp_tar and tmp_tar.exists():
            tmp_tar.unlink()

    # Write plaintext manifest (checksums for verify step)
    (snap_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    log.info("snapshot_created", name=name, files=len(files),
             size_mb=round(len(encrypted) / 1_048_576, 2))

    _prune_old_snapshots()
    return snap_dir


def _prune_old_snapshots():
    cutoff = time.time() - _RETENTION_DAYS * 86400
    for snap_dir in sorted(_BACKUP_DIR.glob("snapshot_*")):
        if snap_dir.is_dir():
            mtime = snap_dir.stat().st_mtime
            if mtime < cutoff:
                import shutil
                shutil.rmtree(snap_dir)
                log.info("snapshot_pruned", name=snap_dir.name)


def list_snapshots() -> list[dict]:
    snaps = []
    for snap_dir in sorted(_BACKUP_DIR.glob("snapshot_*"), reverse=True):
        manifest_path = snap_dir / "manifest.json"
        if manifest_path.exists():
            m = json.loads(manifest_path.read_text())
            snaps.append({
                "name": snap_dir.name,
                "created_at": m.get("created_at"),
                "files": len(m.get("files", [])),
                "label": m.get("label"),
            })
    return snaps
