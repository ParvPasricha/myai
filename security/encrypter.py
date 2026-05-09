"""
Payload encrypter — encrypt/decrypt arbitrary files or bytes using the active master key.

CLI usage:
    python -m security.encrypter encrypt path/to/file.db
    python -m security.encrypter decrypt path/to/file.db.enc
    python -m security.encrypter status

API: routes added to FastAPI in server/routes/security.py
"""
import base64
import sys
from pathlib import Path

from security.crypto import encrypt_bytes, decrypt_bytes, encrypt_file, decrypt_file, is_unlocked


def encrypt_payload(data: bytes) -> str:
    """Encrypt raw bytes, return base64-encoded string safe for JSON transport."""
    return base64.b64encode(encrypt_bytes(data)).decode()


def decrypt_payload(b64: str) -> bytes:
    """Decrypt base64-encoded string back to raw bytes."""
    return decrypt_bytes(base64.b64decode(b64))


def encrypt_file_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if p.suffix == ".enc":
        raise ValueError("File is already encrypted (.enc)")
    result = encrypt_file(p)
    print(f"✓  Encrypted → {result}")
    return result


def decrypt_file_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if p.suffix != ".enc":
        raise ValueError("Expected a .enc file")
    result = decrypt_file(p)
    print(f"✓  Decrypted → {result}")
    return result


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def _cli():
    import getpass

    if len(sys.argv) < 2 or sys.argv[1] not in ("encrypt", "decrypt", "status"):
        print("Usage: python -m security.encrypter <encrypt|decrypt|status> [file]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        print("Vault unlocked" if is_unlocked() else "Vault locked")
        return

    if not is_unlocked():
        password = getpass.getpass("Master password: ")
        from security.crypto import unlock
        if not unlock(password):
            print("Failed to unlock vault.")
            sys.exit(1)

    if len(sys.argv) < 3:
        print(f"Usage: python -m security.encrypter {cmd} <file>")
        sys.exit(1)

    target = sys.argv[2]
    if cmd == "encrypt":
        encrypt_file_path(target)
    else:
        decrypt_file_path(target)


if __name__ == "__main__":
    _cli()
