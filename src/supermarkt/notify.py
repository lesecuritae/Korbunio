"""Benachrichtigungsweg für Beobachtungen: eine Adresse, die eine Textnachricht per POST annimmt.

Funktioniert mit ntfy (https://ntfy.sh/dein-thema oder eigener Server) und mit einfachen Webhooks.
Wie beim KitchenOwl-Token liegt die Adresse nur auf dem Server (Rechte 0600) und wird nie wieder angezeigt,
denn bei ntfy ist der Themenname das Geheimnis.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import config

_LOCK = threading.Lock()


class NotifyError(ValueError):
    """Fehler mit einer Meldung, die man dem Nutzer zeigen darf."""


def normalize_url(value: str) -> str:
    url = str(value or "").strip()
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        raise NotifyError("Bitte eine gültige Benachrichtigungsadresse angeben.") from None
    if any(ord(char) < 33 or ord(char) == 127 for char in url):
        raise NotifyError("Die Adresse darf keine Leer- oder Steuerzeichen enthalten.")
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parts.hostname or parts.username or parts.password or parts.fragment:
        raise NotifyError("Bitte eine Adresse ohne Zugangsdaten angeben, zum Beispiel https://ntfy.sh/mein-thema")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise NotifyError("Die Adresse muss mit https:// beginnen.")
    return url


def load() -> str | None:
    try:
        data = json.loads(config.NOTIFY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        data = {}
    value = (data.get("url") if isinstance(data, dict) else "") or os.environ.get("SUPERMARKT_NOTIFY_URL", "")
    try:
        return normalize_url(value) if value else None
    except NotifyError:
        return None


def save(url: str) -> None:
    with _LOCK:
        path = config.NOTIFY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"url": normalize_url(url)}, handle)
        os.replace(temporary, path)


def clear() -> None:
    with _LOCK:
        try:
            config.NOTIFY_FILE.unlink()
        except FileNotFoundError:
            pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _header(value: str) -> str:
    """HTTP-Header sind ASCII; Umlaute gehen als RFC-2047-Wort (ntfy versteht das)."""
    try:
        value.encode("ascii")
        return value or "Korbuino"
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="


def send(title: str, text: str, url: str | None = None) -> None:
    target = url or load()
    if not target:
        raise NotifyError("Es ist keine Benachrichtigungsadresse eingerichtet.")
    target = normalize_url(target)
    request = urllib.request.Request(target, data=text.encode("utf-8"), method="POST", headers={
        "Title": _header(title),
        "Content-Type": "text/plain; charset=utf-8",
    })
    try:
        with _OPENER.open(request, timeout=15):
            return
    except urllib.error.HTTPError as exc:
        raise NotifyError(f"Die Benachrichtigungsadresse antwortete mit HTTP {exc.code}.") from None
    except (urllib.error.URLError, OSError):
        raise NotifyError("Die Benachrichtigungsadresse ist nicht erreichbar.") from None
