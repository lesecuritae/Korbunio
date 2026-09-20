"""KitchenOwl-Anbindung des Servers (optional): Einstellung speichern und Artikel anlegen.

Der Token wird nur in einer Datei im Datenordner gehalten (Rechte 0600) und nie wieder ausgegeben.
Die Einstellung kommt aus der Datei oder, ersatzweise, aus SUPERMARKT_KITCHENOWL_URL / _TOKEN / _LIST_ID.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from . import config

_LOCK = threading.Lock()


class KitchenOwlError(ValueError):
    """Fehler mit einer Meldung, die man dem Nutzer zeigen darf."""


@dataclass(frozen=True)
class Settings:
    url: str
    token: str
    list_id: str
    list_label: str = ""


def normalize_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    parts = urlsplit(url)
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path.strip("/"):
        raise KitchenOwlError("Bitte die Adresse ohne Zusätze angeben, zum Beispiel https://kitchenowl.example.net")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise KitchenOwlError("Die KitchenOwl-Adresse muss mit https:// beginnen.")
    return url


def load() -> Settings | None:
    try:
        data = json.loads(config.KITCHENOWL_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    url = str(data.get("url") or os.environ.get("SUPERMARKT_KITCHENOWL_URL", ""))
    token = str(data.get("token") or os.environ.get("SUPERMARKT_KITCHENOWL_TOKEN", "")).strip()
    list_id = str(data.get("list_id") or os.environ.get("SUPERMARKT_KITCHENOWL_LIST_ID", "")).strip()
    if not (url and token and list_id.isdigit()):
        return None
    try:
        return Settings(normalize_url(url), token, list_id, str(data.get("list_label") or ""))
    except KitchenOwlError:
        return None


def save(settings: Settings) -> None:
    with _LOCK:
        path = config.KITCHENOWL_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"url": settings.url, "token": settings.token, "list_id": settings.list_id, "list_label": settings.list_label}, handle)
        os.replace(temporary, path)


def clear() -> None:
    with _LOCK:
        try:
            config.KITCHENOWL_FILE.unlink()
        except FileNotFoundError:
            pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):  # Der Token darf nirgendwo anders hin.
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def call(url: str, token: str, path: str, body: dict[str, Any] | None = None) -> Any:
    request = urllib.request.Request(url + path, method="POST" if body is not None else "GET", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json",
    }, data=json.dumps(body).encode() if body is not None else None)
    try:
        with _OPENER.open(request, timeout=15) as response:
            return json.loads(response.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise KitchenOwlError("KitchenOwl hat den Token abgelehnt.") from exc
        raise KitchenOwlError(f"KitchenOwl antwortete mit HTTP {exc.code}.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise KitchenOwlError("KitchenOwl ist unter dieser Adresse nicht erreichbar.") from exc


def fetch_lists(url: str, token: str) -> list[dict[str, str]]:
    """Alle Einkaufslisten des Tokens: [{id, label}]."""
    url = normalize_url(url)
    result: list[dict[str, str]] = []
    for household in call(url, token, "/api/household") or []:
        if not isinstance(household, dict) or "id" not in household:
            continue
        name = str(household.get("name") or "")
        for entry in call(url, token, f"/api/household/{household['id']}/shoppinglist") or []:
            if isinstance(entry, dict) and str(entry.get("id", "")).isdigit():
                label = " · ".join(part for part in (name, str(entry.get("name") or "Einkauf")) if part)
                result.append({"id": str(entry["id"]), "label": label})
    return result


def add_items(settings: Settings, items: list[tuple[str, str]]) -> list[bool]:
    """Mehrere Artikel anlegen und die Liste dafür nur einmal abrufen. Je Artikel True (neu) oder False (stand schon da,
    auch wenn er im selben Stapel zweimal vorkommt)."""
    existing = call(settings.url, settings.token, f"/api/shoppinglist/{settings.list_id}/items") or []
    known = {str(item.get("name", "")).strip().casefold() for item in existing if isinstance(item, dict)}
    added: list[bool] = []
    for name, description in items:
        if name.casefold() in known:
            added.append(False)
            continue
        body = {"name": name, **({"description": description} if description else {})}
        call(settings.url, settings.token, f"/api/shoppinglist/{settings.list_id}/add-item-by-name", body)
        known.add(name.casefold())
        added.append(True)
    return added


def add_item(settings: Settings, name: str, description: str) -> bool:
    """True, wenn neu angelegt; False, wenn der Artikel schon auf der Liste steht."""
    return add_items(settings, [(name, description)])[0]


def list_items(settings: Settings) -> list[dict[str, str]]:
    """Artikel auf der Liste: [{name, note}] (nur lesen)."""
    items = call(settings.url, settings.token, f"/api/shoppinglist/{settings.list_id}/items") or []
    return [
        {"name": str(item["name"]).strip(), "note": str(item.get("description") or "")}
        for item in items
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
