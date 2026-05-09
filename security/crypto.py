"""
AES-256-GCM encryption with PBKDF2-SHA256 key derivation.

The master key lives in RAM only — never written to disk.
Call unlock(password) once on startup; all other functions use the
derived key held in _KEY_VAULT.

Key derivation:
    password + salt (stored in .salt file) → PBKDF2-SHA256 (100k iters) → 32-byte key

Encryption format (binary):
    [ 16-byte salt ][ 12-byte nonce ][ ciphertext + 16-byte GCM tag ]
"""
import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

_SALT_FILE = Path(__file__).parent.parent / ".salt"
_VERIFY_FILE = Path(__file__).parent.parent / ".verify"   # encrypted known-plaintext to confirm password
_VERIFY_PLAINTEXT = b"PARV-AI-VERIFIED"
_ITERATIONS = 100_000
_KEY_VAULT: Optional[bytearray] = None   # 32-byte AES key as bytearray for real in-place zeroing


# ── Key management ────────────────────────────────────────────────────────────

def _load_or_create_salt() -> bytes:
    if _SALT_FILE.exists():
        return _SALT_FILE.read_bytes()
    salt = secrets.token_bytes(16)
    import os
    fd = os.open(str(_SALT_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, salt)
    finally:
        os.close(fd)
    return salt


def _derive_key(password: str, salt: bytes) -> bytearray:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return bytearray(kdf.derive(password.encode()))


def unlock(password: str) -> bool:
    """
    Derive master key from password. Verifies against stored token.
    Returns True only if the password is correct.
    On first call (no .verify file), stores a verification token for future checks.
    """
    global _KEY_VAULT
    try:
        salt = _load_or_create_salt()
        candidate = _derive_key(password, salt)

        if not _VERIFY_FILE.exists():
            # First unlock — store verification token encrypted with this key
            _KEY_VAULT = candidate
            blob = encrypt_bytes(_VERIFY_PLAINTEXT)
            import os
            fd = os.open(str(_VERIFY_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, blob)
            finally:
                os.close(fd)
            return True

        # Subsequent unlocks — verify by decrypting the stored token
        _KEY_VAULT = candidate
        try:
            plaintext = decrypt_bytes(_VERIFY_FILE.read_bytes())
            if plaintext != _VERIFY_PLAINTEXT:
                _KEY_VAULT = None
                return False
            return True
        except Exception:
            _KEY_VAULT = None
            return False
    except Exception:
        _KEY_VAULT = None
        return False


def lock():
    """Zero key bytes in-place then release the reference."""
    global _KEY_VAULT
    if _KEY_VAULT is not None:
        import ctypes
        addr = id(_KEY_VAULT)
        # bytearray is mutable — zero each byte in-place before dropping reference
        for i in range(len(_KEY_VAULT)):
            _KEY_VAULT[i] = 0
    _KEY_VAULT = None


def is_unlocked() -> bool:
    return _KEY_VAULT is not None


def _require_key() -> bytes:
    if not _KEY_VAULT:
        raise RuntimeError("Crypto vault is locked — call unlock(password) first.")
    return bytes(_KEY_VAULT)   # AESGCM requires bytes, not bytearray


# ── Encrypt / Decrypt bytes ───────────────────────────────────────────────────

def encrypt_bytes(plaintext: bytes) -> bytes:
    """Encrypt bytes → [ 16-byte salt ][ 12-byte nonce ][ ciphertext+tag ]"""
    key = _require_key()
    salt = _load_or_create_salt()
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return salt + nonce + ciphertext


def decrypt_bytes(blob: bytes) -> bytes:
    """
    Decrypt blob produced by encrypt_bytes().
    The embedded 16-byte salt is validated against the current .salt file
    to catch silent data-loss if the salt was ever rotated.
    """
    key = _require_key()
    if len(blob) < 28:
        raise ValueError("Blob too short to be valid ciphertext.")
    blob_salt = blob[:16]
    current_salt = _load_or_create_salt()
    if blob_salt != current_salt:
        raise ValueError(
            "Salt mismatch: this blob was encrypted with a different master salt. "
            "Restoring .salt from backup may be required."
        )
    nonce = blob[16:28]
    ciphertext = blob[28:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# ── Encrypt / Decrypt files ───────────────────────────────────────────────────

def encrypt_file(path: Path) -> Path:
    """Encrypt file in-place, appending .enc extension. Returns encrypted path."""
    plaintext = path.read_bytes()
    blob = encrypt_bytes(plaintext)
    enc_path = path.with_suffix(path.suffix + ".enc")
    enc_path.write_bytes(blob)
    path.unlink()
    return enc_path


def decrypt_file(enc_path: Path) -> Path:
    """Decrypt .enc file, restoring original. Returns decrypted path."""
    blob = enc_path.read_bytes()
    plaintext = decrypt_bytes(blob)
    original_path = enc_path.with_suffix("")   # strips last .enc
    original_path.write_bytes(plaintext)
    enc_path.unlink()
    return original_path


_ENCRYPTABLE_SUFFIXES = {".db", ".db-wal", ".db-shm", ".jsonl", ".json", ".pkl"}

def encrypt_dir(directory: Path) -> list[Path]:
    """
    Encrypt data files in directory using an explicit suffix allowlist.
    Skips .enc, .pyc, __pycache__, and the audit log (already encrypted per-entry).
    """
    encrypted = []
    for f in directory.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix == ".enc":
            continue
        if f.name in (".salt", ".verify"):
            continue
        if "__pycache__" in f.parts:
            continue
        if f.suffix not in _ENCRYPTABLE_SUFFIXES:
            continue
        encrypted.append(encrypt_file(f))
    return encrypted
