from __future__ import annotations

import html, json, math, re, threading
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

from ..common import build_match_key, clean_text, format_validity, normalize_pack, parse_iso_date, parse_number
from ..http import HttpClient
from ..images import is_rejected_image_url, normalize_image_url
from ..models import Offer, ToolError

@dataclass(frozen=True)
class GlobusMarket:
    market_id: str
    code: str
    name: str
    postal_code: str
    latitude: float
    longitude: float
    url: str

class GlobusMarketResolver:
    MARKETS_URL = "https://www.globus.de/api/open"
    GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
    MAX_DISTANCE_KM = 100.0

    def __init__(self, http_client: HttpClient) -> None:
        self.http = http_client
        self._markets: Optional[tuple[GlobusMarket, ...]] = None
        self._postal_cache: dict[str, Optional[GlobusMarket]] = {}
        self._lock = threading.Lock()

    def resolve(self, postal_code: str) -> Optional[GlobusMarket]:
        postal_code = clean_text(postal_code)
        if not re.fullmatch(r"\d{5}", postal_code): return None
        with self._lock:
            if postal_code in self._postal_cache: return self._postal_cache[postal_code]
        markets = self._load_markets()
        exact = sorted((m for m in markets if m.postal_code == postal_code), key=lambda m: m.market_id)
        result = exact[0] if exact else None
        if result is None:
            coordinates = self._postal_coordinates(postal_code)
            if coordinates is not None:
                ranked = sorted(((_distance_km(*coordinates, m.latitude, m.longitude), m) for m in markets), key=lambda x: (x[0], x[1].market_id))
                result = ranked[0][1] if ranked and ranked[0][0] <= self.MAX_DISTANCE_KM else None
        with self._lock: self._postal_cache[postal_code] = result
        return result

    def _load_markets(self) -> tuple[GlobusMarket, ...]:
        with self._lock: cached = self._markets
        if cached is not None: return cached
        payload = self.http.post_form_json(self.MARKETS_URL, {"type": "maerkte"})
        raw = payload.get("data") if payload.get("success") is True else None
        if not isinstance(raw, dict): raise ToolError("Globus-Marktliste hat ein unerwartetes Format")
        markets = []
        for key, item in raw.items():
            if not isinstance(item, dict) or item.get("betriebsstaette") != "SBW": continue
            market_id = clean_text(item.get("marktNummer") or item.get("nummer") or key)
            code = clean_text(item.get("marktNameKurz") or item.get("nameKurz")).lower()
            lat, lon = parse_number(item.get("breitengrad")), parse_number(item.get("laengengrad"))
            if not market_id or not re.fullmatch(r"[a-z0-9-]+", code) or lat is None or lon is None: continue
            markets.append(GlobusMarket(market_id, code, clean_text(item.get("marktName") or item.get("name")) or "Globus", clean_text(item.get("plz")), lat, lon, clean_text(item.get("marktUrl")) or "https://www.globus.de/maerkte.php"))
        if not markets: raise ToolError("Globus-Marktliste ist leer")
        result = tuple(markets)
        with self._lock: self._markets = result
        return result

    def _postal_coordinates(self, postal_code: str) -> Optional[tuple[float, float]]:
        query = urlencode({"postalcode": postal_code, "country": "Germany", "format": "jsonv2", "limit": 1})
        try:
            payload = json.loads(self.http.get_bytes(f"{self.GEOCODE_URL}?{query}", {"Accept": "application/json"}).decode())
            if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict): return None
            lat, lon = parse_number(payload[0].get("lat")), parse_number(payload[0].get("lon"))
            return (lat, lon) if lat is not None and lon is not None else None
        except (UnicodeDecodeError, json.JSONDecodeError, ToolError, IndexError, AttributeError): return None

class OfficialGlobusSource:
    FLYER_URL = "https://www.globus.de/faltblatt_online/aktuelle_woche/{code}/pageitems.json"
    def __init__(self, http_client: HttpClient, resolver: Optional[GlobusMarketResolver] = None) -> None:
        self.http, self.resolver = http_client, resolver or GlobusMarketResolver(http_client)
        self.last_market_label = self.last_market_url = ""
        self.last_market: Optional[GlobusMarket] = None

    def load(self, postal_code: str) -> list[Offer]:
        market = self.resolver.resolve(postal_code)
        if market is None: return []
        self.last_market = market
        self.last_market_label, self.last_market_url = f"Globus {market.name}", market.url
        url = self.FLYER_URL.format(code=market.code)
        return self.parse(self.http.get_json(url, {"Accept": "application/json"}), market, url)

    @classmethod
    def parse(cls, payload: dict[str, Any], market: GlobusMarket, source_url: str = "") -> list[Offer]:
        pages = payload.get("pages")
        if not isinstance(pages, list): raise ToolError("Globus-Prospekt hat ein unerwartetes Format")
        result, seen = [], set()
        for page in pages:
            if not isinstance(page, dict) or not isinstance(page.get("articles"), list): continue
            page_no = clean_text(page.get("page"))
            for item in page["articles"]:
                if not isinstance(item, dict): continue
                name, price = _text(item.get("title")), _price(item.get("price"))
                if not name or price is None or price <= 0: continue
                description = _text(f"{item.get('subtitle') or ''} {item.get('custom') or ''}")
                quantity, article_id = _text(item.get("menge")), clean_text(item.get("article_id"))
                start, end = parse_iso_date(item.get("begin")), parse_iso_date(item.get("end"))
                identity = article_id or build_match_key("Globus", name, quantity, "")
                dedupe = (identity, round(price, 2), start, end)
                if dedupe in seen: continue
                seen.add(dedupe)
                base_price, base_unit = _base_price(description, quantity, price)
                offer_id, pack = f"globus:{market.market_id}:{identity}", normalize_pack(quantity or description)
                url = source_url or cls.FLYER_URL.format(code=market.code)
                image_url = _article_image(item, url)
                result.append(Offer(offer_id=offer_id, retailer="Globus", category="Aktuelle Wochenangebote", name=name, brand="", description=description, price=price, base_price=base_price, base_unit=base_unit, pack_signature=pack, validity_label=format_validity(start, end), match_key=build_match_key("", name, pack, offer_id), source_url=url, image_url=image_url, source_category=f"Prospektseite {page_no}" if page_no else "Prospekt", product_url=url, retailer_url=market.url, coverage_note=f"Offizieller Globus-Prospekt für {market.name}", valid_from=start.isoformat() if start else None, valid_until=end.isoformat() if end else None))
        return result


def _article_image(item: dict[str, Any], base_url: str = "") -> str:
    """Return only explicitly article-scoped images, never a flyer page image."""
    for field in (
        "product_image", "productImage", "article_image", "articleImage",
        "offer_image", "offerImage", "product_media", "productMedia",
    ):
        candidate = normalize_image_url(item.get(field), base_url=base_url)
        if not candidate or is_rejected_image_url(candidate):
            continue
        folded = candidate.casefold()
        if any(token in folded for token in (
            "/ressources/img/fbs/", "/ressources/pdfs/", "faltblatt_", "flyer-page",
            "flyer_page", "page-preview", "page_preview",
        )):
            continue
        return candidate
    return ""

def _text(value: Any) -> str: return clean_text(html.unescape(clean_text(value)).replace("\x00", ""))
def _price(value: Any) -> Optional[float]:
    match = re.search(r"\d[\d. ]*(?:[,.]\d{1,2})?", _text(value))
    if not match: return None
    number = match.group(0).replace(" ", "")
    if "," in number: number = number.replace(".", "")
    return parse_number(number)
def _base_price(description: str, quantity: str, price: float) -> tuple[Optional[float], str]:
    match = re.search(r"1\s*(kg|l|100\s*g|100\s*ml)\s*(?:=|:)\s*(\d+[,.]\d{1,2})", f"{description} {quantity}", re.I)
    if match: return parse_number(match.group(2)), re.sub(r"\s+", " ", match.group(1).lower())
    amount = re.search(r"(\d+(?:[,.]\d+)?)\s*(kg|g|l|ml)\b", quantity, re.I)
    if not amount: return None, ""
    value, unit = parse_number(amount.group(1)), amount.group(2).lower()
    if not value or value <= 0: return None, ""
    factor = value if unit in {"kg", "l"} else value / 1000
    return round(price / factor, 2), "kg" if unit in {"kg", "g"} else "l"
def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dlat, dlon = map(math.radians, (lat1, lat2, lat2-lat1, lon2-lon1))
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 12742 * math.atan2(math.sqrt(a), math.sqrt(1-a))
