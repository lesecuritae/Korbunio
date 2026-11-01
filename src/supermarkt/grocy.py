"""Grocy-Anbindung des Servers (optional): Artikel auf eine Grocy-Einkaufsliste legen, lesen und gezielt entfernen.

API laut Grocy 4.x (grocy.openapi.json): Header ``GROCY-API-KEY``, Einkaufsliste = Entität ``shopping_list``.
Der Schlüssel liegt nur in einer 0600-Datei im Datenordner (oder SUPERMARKT_GROCY_URL / _API_KEY / _SHOPPING_LIST_ID),
geht ausschließlich im Header über die Leitung (nie in URL, Logs oder Prozessargumenten) und wird nie wieder ausgegeben.

Bewusste Eigenschaften:
* Wiederholen ist sicher: ein Artikel, der schon offen auf der Liste steht, wird nicht noch einmal angelegt.
* Entfernen löscht nur die genannte Listenposition (Identität wird vorher geprüft, danach per API bestätigt).
  Produkte (Stammdaten) werden nie gelöscht – Grocy würde dabei alle Listenpositionen des Produkts mitlöschen.
"""
from __future__ import annotations

import json
import os
import secrets
import ssl
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from . import config

_LOCK = threading.Lock()
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class GrocyError(ValueError):
    """Fehler mit einer Meldung, die man dem Nutzer zeigen darf (enthält nie den Schlüssel)."""


class GrocyNotFound(GrocyError):
    pass


class GrocyUnknownOutcome(GrocyError):
    """Anfrage ging raus, das Ergebnis ist unbekannt (Zeitüberschreitung, Verbindungsabbruch)."""


@dataclass(frozen=True)
class Settings:
    url: str
    api_key: str
    shopping_list_id: int = 1
    timeout_seconds: int = 15


def normalize_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    parts = urlsplit(url)
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise GrocyError("Bitte die Grocy-Adresse ohne Zugangsdaten und Zusätze angeben, zum Beispiel https://grocy.example.net")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise GrocyError("Die Grocy-Adresse muss mit https:// beginnen (http nur für localhost).")
    return url


def _timeout(raw: Any) -> int:
    try:
        return max(3, min(int(raw), 60))
    except (TypeError, ValueError):
        return 15


def load() -> Settings | None:
    try:
        data = json.loads(config.GROCY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    url = str(data.get("url") or os.environ.get("SUPERMARKT_GROCY_URL", ""))
    key = str(data.get("api_key") or os.environ.get("SUPERMARKT_GROCY_API_KEY", "")).strip()
    list_id = str(data.get("shopping_list_id") or os.environ.get("SUPERMARKT_GROCY_SHOPPING_LIST_ID", "1")).strip()
    if not (url and key and list_id.isdigit() and int(list_id) > 0):
        return None
    try:
        return Settings(normalize_url(url), key, int(list_id), _timeout(data.get("timeout_seconds") or os.environ.get("SUPERMARKT_GROCY_TIMEOUT")))
    except GrocyError:
        return None


def save(settings: Settings) -> None:
    with _LOCK:
        path = config.GROCY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"url": settings.url, "api_key": settings.api_key, "shopping_list_id": settings.shopping_list_id,
                       "timeout_seconds": settings.timeout_seconds}, handle)
        os.replace(temporary, path)


def clear() -> None:
    with _LOCK:
        try:
            config.GROCY_FILE.unlink()
        except FileNotFoundError:
            pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):  # der Schlüssel darf nirgendwo anders hin
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def call(settings: Settings, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    request = urllib.request.Request(settings.url + path, method=method, headers={
        "GROCY-API-KEY": settings.api_key, "Accept": "application/json", "Content-Type": "application/json",
    }, data=json.dumps(body).encode() if body is not None else None)
    try:
        with _OPENER.open(request, timeout=settings.timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise GrocyError("Grocy hat den API-Schlüssel abgelehnt.") from exc
        if exc.code == 404:
            raise GrocyNotFound("Grocy kennt dieses Objekt nicht (HTTP 404).") from exc
        if exc.code in {301, 302, 303, 307, 308}:
            raise GrocyError("Grocy leitet um; bitte die endgültige Adresse (https) eintragen.") from exc
        raise GrocyError(f"Grocy antwortete mit HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if isinstance(getattr(exc, "reason", exc), ssl.SSLCertVerificationError):
            # Handshake failed before any request was sent: a definite failure, not an unknown outcome.
            raise GrocyError("Das TLS-Zertifikat von Grocy wird nicht als vertrauenswürdig anerkannt (Kette, Name oder Ablauf prüfen; "
                             "bei eigener CA SSL_CERT_FILE auf das CA-Bündel setzen).") from exc
        raise GrocyUnknownOutcome("Grocy ist unter dieser Adresse nicht (rechtzeitig) erreichbar.") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise GrocyError("Grocy-Antwort überschreitet das Größenlimit.")
    if not raw.strip():
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise GrocyError("Grocy lieferte keine gültige JSON-Antwort (falsche Adresse?).") from exc


def verify(settings: Settings) -> dict[str, str]:
    """Erreichbarkeit und Schlüssel prüfen; gibt Version und Listenname zurück."""
    info = call(settings, "GET", "/api/system/info")
    if not isinstance(info, dict) or "grocy_version" not in info:
        raise GrocyError("Das ist keine Grocy-Instanz.")
    lists = call(settings, "GET", "/api/objects/shopping_lists") or []
    label = next((str(entry.get("name") or "") for entry in lists if isinstance(entry, dict) and str(entry.get("id")) == str(settings.shopping_list_id)), None)
    if label is None:
        raise GrocyError("Diese Grocy-Einkaufsliste gibt es nicht.")
    return {"version": str(info["grocy_version"].get("Version", "")), "list_label": label}


def _name(value: Any) -> str:
    return " ".join(str(value or "").split())


def _rows(settings: Settings) -> list[dict[str, Any]]:
    rows = call(settings, "GET", f"/api/objects/shopping_list?query%5B%5D=shopping_list_id%3D{settings.shopping_list_id}") or []
    return [row for row in rows if isinstance(row, dict) and str(row.get("shopping_list_id")) == str(settings.shopping_list_id)]


def _products(settings: Settings) -> dict[str, dict[str, Any]]:
    """Produkte nach kleingeschriebenem Namen (Grocy erzwingt eindeutige Namen)."""
    rows = call(settings, "GET", "/api/objects/products") or []
    return {_name(row.get("name")).casefold(): row for row in rows if isinstance(row, dict) and _name(row.get("name"))}


def _defaults(settings: Settings) -> tuple[int, int]:
    """(location_id, quantity_unit_id) für neue Produkte; IDs werden nachgeschlagen, nicht angenommen."""
    locations = [row for row in call(settings, "GET", "/api/objects/locations") or [] if isinstance(row, dict) and str(row.get("id", "")).isdigit()]
    units = [row for row in call(settings, "GET", "/api/objects/quantity_units") or [] if isinstance(row, dict) and str(row.get("id", "")).isdigit()]
    if not locations or not units:
        raise GrocyError("In Grocy fehlen Standort oder Mengeneinheit; neue Artikel können nicht angelegt werden.")
    unit = next((row for row in units if str(row.get("name", "")).casefold() in {"piece", "stück", "stk"}), units[0])
    return int(locations[0]["id"]), int(unit["id"])


_ADD_LOCKS: dict[tuple[str, int], threading.Lock] = {}


def add_items(settings: Settings, items: list[tuple[str, str, float]]) -> list[dict[str, Any]]:
    """Serialised per Grocy list inside this process: Grocy has no uniqueness for list rows, so two parallel adds of the
    same article (MCP + web + retry) would otherwise both pass the "already there?" check and create two rows."""
    with _LOCK:
        lock = _ADD_LOCKS.setdefault((settings.url, settings.shopping_list_id), threading.Lock())
    with lock:
        return _add_items_locked(settings, items)


def _add_items_locked(settings: Settings, items: list[tuple[str, str, float]]) -> list[dict[str, Any]]:
    """Artikel (Name, Notiz, Menge) auf die Liste legen. Je Artikel {name, status: added|exists, row_id, product_id}.

    Unbekannte Artikel werden als Produkt angelegt (nur mit Namen). Ein Artikel, der schon offen auf der Liste steht,
    wird nicht doppelt angelegt. Bei unbekanntem Ausgang einer Anfrage wird neu gelesen statt blind wiederholt.
    """
    products = _products(settings)
    rows = _rows(settings)
    open_by_product: dict[str, dict[str, Any]] = {str(row["product_id"]): row for row in rows if row.get("product_id") not in (None, "") and not int(row.get("done") or 0)}
    defaults: tuple[int, int] | None = None
    results: list[dict[str, Any]] = []
    for raw_name, note, amount in items:
        name = _name(raw_name)[:120]
        if not name:
            raise GrocyError("Ein Artikel ohne Namen kann nicht übernommen werden.")
        product = products.get(name.casefold())
        if product is None:
            defaults = defaults or _defaults(settings)
            product_id = _create(settings, "/api/objects/products", {"name": name, "location_id": defaults[0], "qu_id_purchase": defaults[1], "qu_id_stock": defaults[1]},
                                 lambda key=name.casefold(): _products(settings).get(key, {}).get("id"))
            product = {"id": product_id, "name": name}
            products[name.casefold()] = product
        product_id = str(product["id"])
        existing = open_by_product.get(product_id)
        if existing is not None:
            results.append({"name": name, "status": "exists", "row_id": str(existing["id"]), "product_id": product_id})
            continue
        body: dict[str, Any] = {"product_id": int(product_id), "amount": max(amount, 0.0001), "shopping_list_id": settings.shopping_list_id}
        if note.strip():
            body["note"] = " ".join(note.split())[:500]
        known_ids = {str(row["id"]) for row in rows}

        def find_new_row(product_id: str = product_id, known_ids: set[str] = known_ids) -> str | None:
            fresh = [row for row in _rows(settings) if str(row.get("product_id")) == product_id and str(row["id"]) not in known_ids]
            return str(fresh[0]["id"]) if fresh else None

        row_id = _create(settings, "/api/objects/shopping_list", body, find_new_row)
        row = {"id": row_id, "product_id": product_id, "done": 0, "shopping_list_id": settings.shopping_list_id}
        rows.append(row)
        open_by_product[product_id] = row
        results.append({"name": name, "status": "added", "row_id": str(row_id), "product_id": product_id})
    return results


def _create(settings: Settings, path: str, body: dict[str, Any], recover) -> str:
    try:
        created = call(settings, "POST", path, body)
    except GrocyUnknownOutcome:
        found = recover()  # ging die Anlage trotz Fehler durch? Dann nicht noch einmal anlegen.
        if found:
            return str(found)
        raise
    new_id = created.get("created_object_id") if isinstance(created, dict) else None
    if not str(new_id or "").isdigit():
        raise GrocyError("Grocy hat keine ID für das angelegte Objekt geliefert.")
    return str(new_id)


def list_items(settings: Settings) -> list[dict[str, str]]:
    """Offene Positionen: [{row_id, name, note, amount}] (nur lesen)."""
    names = {str(row["id"]): _name(row.get("name")) for row in (call(settings, "GET", "/api/objects/products") or []) if isinstance(row, dict) and "id" in row}
    result = []
    for row in _rows(settings):
        if int(row.get("done") or 0):
            continue
        name = names.get(str(row.get("product_id")), "") or _name(row.get("note"))
        if name:
            result.append({"row_id": str(row["id"]), "name": name, "note": _name(row.get("note")), "amount": str(row.get("amount", ""))})
    return result


def remove_item(settings: Settings, row_id: str, expected_name: str) -> bool:
    """Genau diese Listenposition entfernen. Prüft Liste und Name, löscht nur die Position und bestätigt per API.

    True = entfernt und bestätigt weg; False = Position gab es schon nicht mehr (nichts gelöscht).
    """
    row_id = str(row_id or "").strip()
    if not row_id.isdigit():
        raise GrocyError("Ungültige Positions-ID.")
    path = f"/api/objects/shopping_list/{row_id}"
    try:
        row = call(settings, "GET", path)
    except GrocyNotFound:
        return False
    if not isinstance(row, dict) or str(row.get("shopping_list_id")) != str(settings.shopping_list_id):
        raise GrocyError("Diese Position gehört nicht zur eingerichteten Grocy-Liste; nichts gelöscht.")
    product_id = row.get("product_id")
    actual = ""
    if product_id not in (None, ""):
        product = call(settings, "GET", f"/api/objects/products/{quote(str(product_id), safe='')}")
        actual = _name(product.get("name") if isinstance(product, dict) else "")
    else:
        actual = _name(row.get("note"))
    if _name(expected_name).casefold() != actual.casefold():
        raise GrocyError("Die Position passt nicht zum erwarteten Artikel; nichts gelöscht.")
    call(settings, "DELETE", path)
    try:
        call(settings, "GET", path)
    except GrocyNotFound:
        return True
    raise GrocyError("Grocy meldet die Position nach dem Löschen weiterhin; Löschen nicht bestätigt.")
