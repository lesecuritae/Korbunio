"""Short-lived, explicit browser-session handoffs for protected retailers."""

from __future__ import annotations

import threading
import time


class MuellerSessionStore:
    """Keep one operator-provided Müller cookie only in process memory.

    The value is deliberately never persisted, logged, or returned. A
    self-hosted single-process deployment is the intended use; expiry keeps a
    copied browser session from remaining active indefinitely.
    """

    MAX_COOKIE_LENGTH = 8_192

    def __init__(self, ttl_seconds: int = 3_600) -> None:
        self.ttl_seconds = max(300, int(ttl_seconds))
        self._cookie = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def set(self, cookie: str) -> None:
        value = str(cookie or "").strip()
        if not value or len(value) > self.MAX_COOKIE_LENGTH or any(char in value for char in "\r\n"):
            raise ValueError("Ungültige Müller-Session")
        # A Cookie header consists of semicolon-separated name/value pairs.
        # Reject arbitrary pasted text so the value cannot become a header
        # injection or an accidental password/token submission.
        parts = [part.strip() for part in value.split(";") if part.strip()]
        if not parts or any("=" not in part or not part.split("=", 1)[0].strip() for part in parts):
            raise ValueError("Bitte den Cookie-Header aus der Müller-Domain einfügen")
        with self._lock:
            self._cookie = "; ".join(parts)
            self._expires_at = time.monotonic() + self.ttl_seconds

    def get(self) -> str:
        with self._lock:
            if not self._cookie or time.monotonic() >= self._expires_at:
                self._cookie = ""
                self._expires_at = 0.0
                return ""
            return self._cookie

    def clear(self) -> None:
        with self._lock:
            self._cookie = ""
            self._expires_at = 0.0


_MUELLER_SESSION = MuellerSessionStore()


def get_mueller_cookie() -> str:
    return _MUELLER_SESSION.get()


def set_mueller_cookie(value: str) -> None:
    _MUELLER_SESSION.set(value)


def clear_mueller_cookie() -> None:
    _MUELLER_SESSION.clear()
