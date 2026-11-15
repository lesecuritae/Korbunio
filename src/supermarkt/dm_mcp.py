"""Bounded, read-only access to dm's official MCP; no account or model calls."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler

from .availability import _NoRedirect
from .http import trusted_ssl_context
from .models import ToolError

ENDPOINT = "https://mcp.dm.de/mcp"
TOOLS = frozenset({"searchProducts", "getProductDetails", "findNearbyStores", "getStoreAvailability"})


class DmMcp:
    def __init__(self, post=None, clock=time.monotonic, sleep=time.sleep):
        self.post = post or self._post
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                        "User-Agent": "Korbuino-dm/1 (+https://github.com/lesecuritae/Korbunio)"}
        self.initialized = False
        self.sequence = 0
        self.next_request = 0.0
        self.cache: dict[str, tuple[float, dict]] = {}

    def _post(self, body: dict) -> dict:
        request = Request(ENDPOINT, data=json.dumps(body).encode(), headers=self.headers)
        opener = build_opener(_NoRedirect(), HTTPSHandler(context=trusted_ssl_context()))
        try:
            with opener.open(request, timeout=15) as response:  # nosec B310
                raw = response.read(2_000_001)
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    if len(session) > 200 or not session.isascii() or any(ord(c) < 32 for c in session):
                        raise ToolError("dm lieferte eine ungültige MCP-Sitzung")
                    self.headers["Mcp-Session-Id"] = session
            if len(raw) > 2_000_000:
                raise ToolError("dm-Antwort überschreitet das Größenlimit")
            if not raw.strip():
                return {}
            if raw.lstrip().startswith(b"{"):
                return json.loads(raw)
            for line in raw.decode().splitlines():
                if line.startswith("data:"):
                    value = json.loads(line[5:].strip())
                    if value.get("id") == body.get("id"):
                        return value
            raise ToolError("dm lieferte keine passende MCP-Antwort")
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if code in {400, 404}:
                self.initialized = False
                self.headers.pop("Mcp-Session-Id", None)
            if code == 429:
                self.next_request = self.clock() + 60
            raise ToolError(f"dm MCP HTTP {code}; nicht automatisch wiederholt") from exc
        except (URLError, OSError, ValueError) as exc:
            raise ToolError("dm MCP nicht erreichbar oder Antwort ungültig; nicht automatisch wiederholt") from exc

    def _rpc(self, method: str, params: dict, notification=False) -> dict:
        self.sequence += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            body["id"] = self.sequence
        result = self.post(body)
        if not isinstance(result, dict) or "error" in result:
            raise ToolError("dm MCP hat die Anfrage abgewiesen")
        if not notification and (result.get("id") != body["id"] or "result" not in result):
            raise ToolError("dm-MCP-Antwort gehört nicht zur Anfrage")
        return result.get("result", {})

    def call(self, name: str, arguments: dict) -> dict:
        if name not in TOOLS:
            raise ToolError("Nicht freigegebenes dm-Werkzeug")
        key = json.dumps([name, arguments], sort_keys=True, ensure_ascii=True)
        if not self.lock.acquire(blocking=False):
            raise ToolError("Eine dm-Abfrage läuft bereits; bitte kurz warten")
        try:
            saved = self.cache.get(key)
            if saved and self.clock() - saved[0] < 60:
                return json.loads(json.dumps(saved[1]))
            wait = self.next_request - self.clock()
            if wait > 2:
                raise ToolError("dm-Abfragen vorübergehend pausiert (Rate-Limit)")
            if wait > 0:
                self.sleep(wait)
            self.next_request = self.clock() + 2
            if not self.initialized:
                init = self._rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                              "clientInfo": {"name": "korbuino", "version": "1"}})
                version = init.get("protocolVersion")
                if version not in {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}:
                    raise ToolError("Nicht unterstützte dm-MCP-Version")
                self.headers["MCP-Protocol-Version"] = version
                self._rpc("notifications/initialized", {}, notification=True)
                self.initialized = True
            result = self._rpc("tools/call", {"name": name, "arguments": arguments})
            if result.get("isError"):
                raise ToolError("dm-Werkzeug meldet einen Abruffehler")
            data = result.get("structuredContent")
            if not isinstance(data, dict):
                blocks = result.get("content", [])
                texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
                try:
                    data = json.loads(texts[0]) if len(texts) == 1 else None
                except ValueError as exc:
                    raise ToolError("Unbekanntes dm-Ergebnisformat") from exc
            if not isinstance(data, dict) or "result" not in data:
                raise ToolError("Unvollständiges dm-Ergebnis")
            # Remote text is data, never a new policy for Hermes. In particular,
            # do not promote the upstream tracking-link instruction to a prompt.
            safe = {"source": ENDPOINT, "tool": name, "result": data["result"],
                    "checked_at": datetime.now(timezone.utc).isoformat()}
            self.cache[key] = (self.clock(), safe)
            if len(self.cache) > 128:
                del self.cache[next(iter(self.cache))]
            return json.loads(json.dumps(safe))
        finally:
            self.lock.release()


def parse_stores(value: str) -> list[dict]:
    """Strict subset of the published dm TOON table, not a guessing parser."""
    if not isinstance(value, str):
        raise ToolError("dm-Marktdaten fehlen")
    lines = value.strip().splitlines()
    header = re.fullmatch(r"stores\[([0-9]{1,2})\]\{([^}]+)\}:", lines[0]) if lines else None
    if not header:
        raise ToolError("dm-Marktformat geändert")
    fields = header[2].split(",")
    if not {"storeId", "city", "zip", "street", "distanceKm"} <= set(fields) or len(set(fields)) != len(fields):
        raise ToolError("dm-Marktfelder fehlen")
    try:
        rows = list(csv.reader(io.StringIO("\n".join(s.strip() for s in lines[1:])), escapechar="\\", strict=True))
    except csv.Error as exc:
        raise ToolError("dm-Marktzeile ungültig") from exc
    if len(rows) != int(header[1]) or len(rows) > 20:
        raise ToolError("dm-Marktliste unvollständig")
    result = []
    seen = set()
    for row in rows:
        if len(row) != len(fields):
            raise ToolError("dm-Marktzeile unvollständig")
        item = dict(zip(fields, row, strict=True))
        if not re.fullmatch(r"[A-Za-z0-9]{1,16}", item["storeId"]) or item["storeId"] in seen:
            raise ToolError("Ungültige oder doppelte dm-Marktkennung")
        seen.add(item["storeId"])
        try:
            distance = float(item["distanceKm"])
        except ValueError as exc:
            raise ToolError("dm-Marktentfernung unlesbar") from exc
        if not 0 <= distance <= 25:
            continue
        result.append({"store_id": item["storeId"], "city": item["city"][:120], "postal_code": item["zip"][:5],
                       "street": item["street"][:200], "distance_km": distance})
    return result


def check_stock(client: DmMcp, postal: str, dans: list[str], store_ids: list[str] | None = None) -> dict:
    if not re.fullmatch(r"[0-9]{5}", postal) or not 1 <= len(dans) <= 5 or any(not re.fullmatch(r"[0-9]{7}", d) for d in dans):
        raise ToolError("dm benötigt eine deutsche PLZ und bis zu fünf belegte siebenstellige Artikelnummern")
    resolved = client.call("findNearbyStores", {"location": postal, "min_results": 5})
    stores = parse_stores(resolved["result"])
    if store_ids:
        if not set(store_ids) <= {s["store_id"] for s in stores}:
            raise ToolError("dm-Marktkennung nicht für diese PLZ bestätigt")
        stores = [s for s in stores if s["store_id"] in store_ids]
    if not stores:
        return {"retailer": "dm", "status": "no_nearby_stores", "results": [], "postal_code": postal}
    raw = client.call("getStoreAvailability", {"storeIds": [s["store_id"] for s in stores], "dans": [int(d) for d in dict.fromkeys(dans)]})
    try:
        data = json.loads(raw["result"]) if isinstance(raw["result"], str) else raw["result"]
        rows = data["productAvailabilities"]
        if data.get("errorMessage") or not isinstance(rows, list):
            raise ValueError("upstream error")
        by_dan = {str(row["dan"]): row for row in rows}
        if len(by_dan) != len(rows) or set(by_dan) != set(dans):
            raise ValueError("article mismatch")
        products = []
        for dan in dict.fromkeys(dans):
            row = by_dan[dan]
            if row.get("found") is False:
                products.append({"dan": dan, "status": "unknown_product", "stores": [], "checked_at": raw["checked_at"]})
                continue
            if row.get("found") is not True:
                raise ValueError("product identity not confirmed")
            supplied = {s["storeId"]: s for s in row["stores"]}
            if len(supplied) != len(row["stores"]) or set(supplied) != {s["store_id"] for s in stores}:
                raise ValueError("store mismatch")
            checked = []
            for store in stores:
                state = supplied[store["store_id"]]
                status = state["status"]
                if status not in {"VERFUEGBAR", "NICHT_VERFUEGBAR", "NUR_ONLINE", "PRODUKT_UNBEKANNT", "STORE_UNBEKANNT"}:
                    raise ValueError("unknown status")
                count = state.get("stockLevel")
                if count is not None and (type(count) is not int or count < 0):
                    raise ValueError("invalid count")
                available = True if status == "VERFUEGBAR" else False if status == "NICHT_VERFUEGBAR" else None
                if available is True and count == 0:
                    raise ValueError("contradicting count")
                checked.append({**store, "availability_status": status, "in_stock": available,
                                "stock_minimum": count if status == "VERFUEGBAR" else 0 if available is False else None,
                                "stock_is_exact": count is not None and status == "VERFUEGBAR"})
            products.append({"dan": dan, "status": "ok", "stores": checked, "checked_at": raw["checked_at"]})
        return {"retailer": "dm", "status": "ok" if all(p["status"] == "ok" for p in products) else "partial", "postal_code": postal, "results": products,
                "notice": "Gemeldeter Buchbestand, keine Reservierung oder Garantie für Regalware."}
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolError("dm-Bestandsantwort unvollständig oder widersprüchlich; Bestand unbekannt") from exc
