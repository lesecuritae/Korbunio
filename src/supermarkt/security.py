from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import ACCESS_TOKENS_FILE, SIGNING_SECRET_FILE

_SECRET_LOCK = threading.Lock()
_CACHED_SECRET: bytes | None = None
_TOKEN_LOCK = threading.Lock()


def api_key() -> str:
    """Return the optional bearer token used to protect the public REST endpoint."""
    return os.getenv("SUPERMARKT_API_KEY", "").strip()


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _client_token_records() -> list[dict[str, str]]:
    try:
        payload = json.loads(ACCESS_TOKENS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [
        {str(key): str(value) for key, value in item.items()}
        for item in payload
        if isinstance(item, dict) and len(str(item.get("sha256", ""))) == 64
    ]


def api_auth_configured() -> bool:
    return bool(api_key() or _client_token_records())


def valid_api_key(candidate: str, *, admin_only: bool = False) -> bool:
    candidate = candidate.strip()
    admin = api_key()
    if admin and candidate and secrets.compare_digest(candidate, admin):
        return True
    if admin_only or not candidate:
        return False
    digest = _token_digest(candidate)
    return any(secrets.compare_digest(digest, record["sha256"]) for record in _client_token_records())


def create_client_token(label: str) -> str:
    """Create a bearer token and persist only its SHA-256 digest."""
    normalized_label = " ".join(str(label or "Android").split())[:80] or "Android"
    with _TOKEN_LOCK:
        records = _client_token_records()
        if len(records) >= 64:
            raise RuntimeError("Maximale Anzahl von App-Tokens erreicht")
        raw = secrets.token_urlsafe(48)
        records.append({
            "id": secrets.token_hex(8),
            "label": normalized_label,
            "sha256": _token_digest(raw),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        ACCESS_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = ACCESS_TOKENS_FILE.with_name(
            f".{ACCESS_TOKENS_FILE.name}.{secrets.token_hex(8)}.tmp"
        )
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(records, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, ACCESS_TOKENS_FILE)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return raw


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
