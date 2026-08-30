from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
from pathlib import Path

from .config import SIGNING_SECRET_FILE

_SECRET_LOCK = threading.Lock()
_CACHED_SECRET: bytes | None = None


def api_key() -> str:
    """Return the optional bearer token used to protect the public REST endpoint."""
    return os.getenv("SUPERMARKT_API_KEY", "").strip()


def _validate_secret(value: str) -> bytes:
    secret = value.strip().encode("utf-8")
    if len(secret) < 32:
        raise RuntimeError("SUPERMARKT_SIGNING_SECRET muss mindestens 32 Zeichen lang sein")
    return secret


def _read_or_create_secret_file(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _validate_secret(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass

    generated = secrets.token_urlsafe(48)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _validate_secret(path.read_text(encoding="utf-8"))

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(generated + "\n")
    return generated.encode("utf-8")


def signing_secret() -> bytes:
    """Return a stable HMAC key, generated once in the persistent data directory if needed."""
    global _CACHED_SECRET
    if _CACHED_SECRET is not None:
        return _CACHED_SECRET
    with _SECRET_LOCK:
        if _CACHED_SECRET is not None:
            return _CACHED_SECRET
        configured = os.getenv("SUPERMARKT_SIGNING_SECRET", "").strip()
        _CACHED_SECRET = _validate_secret(configured) if configured else _read_or_create_secret_file(SIGNING_SECRET_FILE)
        return _CACHED_SECRET


def signature(*parts: str, namespace: str) -> str:
    payload = "\n".join((namespace, *parts)).encode("utf-8")
    return hmac.new(signing_secret(), payload, hashlib.sha256).hexdigest()[:32]


def valid_signature(candidate: str, *parts: str, namespace: str) -> bool:
    if not candidate:
        return False
    return hmac.compare_digest(candidate, signature(*parts, namespace=namespace))
