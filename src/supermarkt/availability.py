"""On-demand Rossmann book stock, independent of the retailer's app/account.

This is separate from offers: neither a brochure nor `available=true` proves stock.
No cookies, app keys, device identifiers or tracking SDKs are used.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import threading
import time
from typing import Annotated, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field

from .http import trusted_ssl_context
from .models import ToolError

USER_AGENT = "Korbuino-Availability/1 (+https://github.com/lesecuritae/Korbunio)"
ENDPOINT = "https://api-ocm-de-prod.rossmann.net/storefinder/.rest/rsmnapp/stores"
DISCLAIMER = "Gemeldeter Buchbestand, keine Reservierung oder Garantie für Regalware. 5+ bedeutet mindestens fünf."
Dan = Annotated[str, Field(pattern=r"^[0-9]{6}$")]


class StockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    postal_code: str = Field(pattern=r"^[0-9]{5}$")
    dans: list[Dan] = Field(min_length=1, max_length=5)
    store_ids: list[Annotated[str, Field(pattern=r"^[0-9]{1,12}$")]] = Field(default_factory=list, max_length=20)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_stores(latitude: float, longitude: float, dan: str) -> Any:
    # The host/path are fixed; models and clients cannot select a URL or headers.
    url = ENDPOINT + "?" + urlencode({"latitude": latitude, "longitude": longitude, "dan": dan})
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=trusted_ssl_context()))
    try:
        with opener.open(request, timeout=8) as response:  # nosec B310
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ToolError("Rossmann-Antwort überschreitet das Größenlimit")
        return json.loads(data)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        raise ToolError(f"Rossmann HTTP {code}: Bestand nicht abrufbar, nicht als ausverkauft werten") from exc
    except (URLError, OSError, ValueError) as exc:
        raise ToolError("Rossmann-Bestandsabfrage fehlgeschlagen") from exc


def parse_stores(payload: Any, dan: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or len(payload) > 200:
        raise ToolError("Unbekanntes Rossmann-Filialformat")
    stores: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict) or not isinstance(row.get("productInfos"), list):
            raise ToolError("Rossmann-Filialdaten unvollständig")
        identity = str(row.get("id", ""))
        if not re.fullmatch(r"[0-9]{1,12}", identity):
            raise ToolError("Rossmann-Filialkennung fehlt")
        matches = [item for item in row["productInfos"] if isinstance(item, dict) and str(item.get("dan")) == dan]
        if len(matches) != 1:
            raise ToolError("Rossmann-Artikelzuordnung fehlt oder ist widersprüchlich")
        item = matches[0]
        raw = str(item.get("stock", ""))
        count = re.fullmatch(r"([0-9]{1,6})(\+?)", raw)
        minimum = int(count[1]) if count else None
        exact = bool(count and not count[2])
        in_stock = minimum > 0 if minimum is not None else None
        if minimum == 0 and not exact:
            in_stock = None
        store = {
            "store_id": identity, "city": str(row.get("city", ""))[:120],
            "street": str(row.get("street", ""))[:200], "postal_code": str(row.get("zipCode", ""))[:5],
            "stock_raw": raw[:30], "stock_minimum": minimum,
            "stock_is_exact": exact, "in_stock": in_stock,
            # This flag can be true with stock=0; keep it separate.
            "listed": item.get("available") if isinstance(item.get("available"), bool) else None,
        }
        if identity in stores and stores[identity] != store:
            raise ToolError("Widersprüchliche Bestände derselben Filiale")
        stores[identity] = store
    return list(stores.values())


class StockService:
    """One admitted batch, at least two seconds between upstream requests.

    Cache is bounded and ephemeral. Errors never become zero stock or replace a
    successful cached response. No background polling or automatic HTTP replay.
    """
    def __init__(self, geocode, fetch=fetch_stores, clock=time.monotonic, sleep=time.sleep):
        self.geocode, self.fetch, self.clock, self.sleep = geocode, fetch, clock, sleep
        self._admission = threading.Lock()
        self._next_request = 0.0
        self._cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
        self._origins: OrderedDict[str, tuple] = OrderedDict()

    def check(self, request: StockRequest) -> dict:
        result = {"retailer": "Rossmann", "postal_code": request.postal_code, "notice": DISCLAIMER, "results": []}
        if not self._admission.acquire(blocking=False):
            return {**result, "status": "busy", "retry_after_seconds": 5}
        try:
            origin = self._origins.get(request.postal_code)
            if origin is None or self.clock() - origin[0] >= 86400:
                self._pace()
                point = self.geocode(request.postal_code)
                if not point or len(point) != 2 or not (-90 <= point[0] <= 90 and -180 <= point[1] <= 180):
                    raise ToolError("PLZ konnte nicht eindeutig aufgelöst werden")
                self._origins[request.postal_code] = (self.clock(), point)
                if len(self._origins) > 128:
                    self._origins.popitem(last=False)
            else:
                point = origin[1]
            for dan in dict.fromkeys(request.dans):
                key = (*point, dan)
                cached = self._cache.get(key)
                if cached and self.clock() - cached[0] < 60:
                    item = {**deepcopy(cached[1]), "from_cache": True}
                else:
                    self._pace()
                    try:
                        stores = parse_stores(self.fetch(*point, dan), dan)
                        item = {"dan": dan, "status": "ok", "stores": stores, "from_cache": False,
                                "checked_at": datetime.now(timezone.utc).isoformat()}
                        self._cache[key] = (self.clock(), deepcopy(item))
                        if len(self._cache) > 128:
                            self._cache.popitem(last=False)
                    except ToolError as exc:
                        item = {"dan": dan, "status": "unavailable", "stores": [], "error": str(exc)}
                if request.store_ids:
                    item["stores"] = [s for s in item["stores"] if s["store_id"] in request.store_ids]
                result["results"].append(item)
            successes = sum(item["status"] == "ok" for item in result["results"])
            result["status"] = "ok" if successes == len(result["results"]) else "partial" if successes else "unavailable"
            return result
        except ToolError as exc:
            return {**result, "status": "unavailable", "error": str(exc)}
        finally:
            self._admission.release()

    def _pace(self):
        wait = self._next_request - self.clock()
        if wait > 0:
            self.sleep(wait)
        self._next_request = self.clock() + 2
