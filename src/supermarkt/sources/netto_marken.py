from __future__ import annotations

import json
import re
import threading
import unicodedata
from typing import Any
from urllib.parse import urlencode

from ..common import clean_text, parse_number
from ..http import HttpClient
from ..models import ToolError


class NettoMarkenMarketResolver:
    """Resolve official Netto Marken-Discount stores without claiming catalogue precision."""

    STORE_API = "https://www.netto-online.de/INTERSHOP/web/WFS/Plus-NettoDE-Site/de_DE/-/EUR/ViewMMPStoreFinder-GetStoreItems"
    FINDER_URL = "https://www.netto-online.de/filialfinder"
    GEOCODE_URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _slug(value: Any) -> str:
        text = unicodedata.normalize("NFKD", clean_text(value).casefold())
        text = "".join(char for char in text if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]+", "-", text).strip("-")

    @classmethod
    def _option(cls, store: dict[str, Any], match_type: str) -> dict[str, str]:
        market_id = clean_text(store.get("store_id"))
        postal = clean_text(store.get("post_code"))
        city = clean_text(store.get("city"))
        street = clean_text(store.get("street"))
        path = "/".join(filter(None, (cls._slug(city), cls._slug(street), market_id)))
        return {
            "market_id": market_id,
            "label": clean_text(f"Netto Marken-Discount – {street}, {postal} {city}"),
            "market_url": f"https://www.netto-online.de/filialen/{path}" if path else cls.FINDER_URL,
            "match_type": match_type,
        }

    @staticmethod
    def _usable(store: Any) -> bool:
        if not isinstance(store, dict) or store.get("is_closed") is True:
            return False
        if clean_text(store.get("store_name")) != "Netto Marken-Discount":
            return False
        market_id = clean_text(store.get("store_id"))
        city = clean_text(store.get("city")).casefold()
        return bool(market_id and market_id != "9999" and city != "teststadt")

    def _coordinates(self, postal_code: str) -> tuple[float, float]:
        query = urlencode({"postalcode": postal_code, "country": "Germany", "format": "jsonv2", "limit": 1})
        try:
            payload = json.loads(self.http.get_bytes(
                f"{self.GEOCODE_URL}?{query}", {"Accept": "application/json"}
            ).decode("utf-8"))
            latitude = parse_number(payload[0].get("lat"))
            longitude = parse_number(payload[0].get("lon"))
        except (ToolError, ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ToolError(f"Netto konnte PLZ {postal_code} nicht geokodieren") from exc
        if latitude is None or longitude is None:
            raise ToolError(f"Netto konnte PLZ {postal_code} nicht geokodieren")
        return latitude, longitude

    def _stores_near(self, postal_code: str) -> list[dict[str, Any]]:
        with self._lock:
            cached = self._cache.get(postal_code)
        if cached is not None:
            return list(cached)
        latitude, longitude = self._coordinates(postal_code)
        delta = 0.30
        fields = {
            "s": str(latitude - delta), "n": str(latitude + delta),
            "w": str(longitude - delta), "e": str(longitude + delta),
            "netto": "true", "city": "true", "service": "true",
            "beverage": "true", "nonfood": "true",
        }
        try:
            from curl_cffi import requests as curl_requests
            response = curl_requests.post(
                self.STORE_API, data=fields, impersonate="chrome", timeout=self.http.timeout_seconds,
                headers={"Referer": self.FINDER_URL, "X-Requested-With": "XMLHttpRequest"},
            )
            if response.status_code != 200:
                raise ToolError(f"Netto Filialsuche HTTP {response.status_code}")
            payload = response.json()
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Netto Filialsuche fehlgeschlagen: {exc}") from exc
        stores = payload.get("store_items") if isinstance(payload, dict) else None
        if not isinstance(stores, list):
            raise ToolError("Netto Filialsuche lieferte ein unerwartetes Format")
        result = [store for store in stores if self._usable(store)]
        with self._lock:
            self._cache[postal_code] = result
        return list(result)

    def markets(self, postal_code: str) -> list[dict[str, str]]:
        stores = self._stores_near(postal_code)
        exact = [store for store in stores if clean_text(store.get("post_code")) == postal_code]
        selected = exact or stores
        match_type = "exact" if exact else "nearby"
        unique = {clean_text(store.get("store_id")): store for store in selected if self._usable(store)}
        return sorted(
            (self._option(store, match_type) for store in unique.values()),
            key=lambda item: (item["label"].casefold(), item["market_id"]),
        )

    def resolve(self, postal_code: str, market_id: str = "") -> dict[str, Any] | None:
        stores = self._stores_near(postal_code)
        exact = [store for store in stores if clean_text(store.get("post_code")) == postal_code]
        candidates = exact or stores
        requested = clean_text(market_id)
        if requested:
            selected = next((store for store in candidates if clean_text(store.get("store_id")) == requested), None)
            if selected is None:
                raise ToolError(f"Die gewählte Netto-Filiale gehört nicht zur PLZ {postal_code}")
            return selected
        return sorted(candidates, key=lambda store: (clean_text(store.get("street")).casefold(), clean_text(store.get("store_id"))))[0] if candidates else None
