from __future__ import annotations

import re
import json
from datetime import date
from urllib.parse import urlencode, urljoin

from ..common import (
    build_match_key,
    clean_text,
    format_validity,
    normalize_pack,
    parse_base_price_text,
    parse_deposit_text,
    parse_number,
)
from ..http import HttpClient
from ..loyalty import parse_public_loyalty_prices
from ..models import LoyaltyBenefit, Offer, ToolError


class NettoScottieMarketResolver:
    SEARCH_URL = "https://netto.de/marktsuche/"
    STORE_API = "https://api.sallinggroup.com/v2/stores"

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self._api_key = ""

    def _public_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        html = self.http.get_bytes(self.SEARCH_URL).decode("utf-8", errors="replace")
        scripts = re.findall(r'src=["\']([^"\']+\.js[^"\']*)', html)
        for script in scripts:
            body = self.http.get_bytes(urljoin(self.SEARCH_URL, script)).decode("utf-8", errors="replace")
            match = re.search(r'sallingGroupApiKey:["\']([^"\']+)', body)
            if match:
                self._api_key = match[1]
                return self._api_key
        raise ToolError("Netto-schwarz-Marktsuche lieferte keine öffentliche Zugriffskonfiguration")

    @staticmethod
    def _select_exact(stores: list[dict], postal_code: str) -> dict | None:
        exact = [store for store in stores if clean_text((store.get("address") or {}).get("zip")) == postal_code]
        if exact:
            return min(exact, key=lambda item: float(item.get("distance_km") or 9999))
        nearby = [store for store in stores if float(store.get("distance_km") or 9999) <= 15.0]
        return min(nearby, key=lambda item: float(item.get("distance_km") or 9999)) if nearby else None

    def resolve(self, postal_code: str) -> dict | None:
        location_url = "https://nominatim.openstreetmap.org/search?" + urlencode({
            "postalcode": postal_code, "country": "Germany", "format": "jsonv2", "limit": 1,
        })
        try:
            locations = json.loads(self.http.get_bytes(location_url, {"Accept": "application/json"}).decode("utf-8"))
            latitude, longitude = float(locations[0]["lat"]), float(locations[0]["lon"])
        except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ToolError(f"Netto schwarz konnte PLZ {postal_code} nicht geokodieren") from exc
        query = urlencode({
            "brand": "netto", "country": "DE", "geo": f"{latitude},{longitude}",
            "radius": 100, "per_page": 25,
        })
        try:
            stores = json.loads(self.http.get_bytes(
                f"{self.STORE_API}?{query}", {"Accept": "application/json", "Authorization": f"Bearer {self._public_api_key()}"},
            ).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ToolError("Netto-schwarz-Marktsuche lieferte ungültiges JSON") from exc
        if not isinstance(stores, list):
            raise ToolError("Netto-schwarz-Marktsuche lieferte eine unerwartete Antwort")
        return self._select_exact([item for item in stores if isinstance(item, dict)], postal_code)


class OfficialNettoScottieSource:
    """Public weekly offers published by Salling Group's German Netto chain."""

    BASE_URL = "https://netto.de"
    OFFERS_URL = BASE_URL + "/angebote/"
    MAX_RESPONSE = 4_000_000

    def __init__(self, http: HttpClient, market_resolver=None) -> None:
        self.http = http
        self.market_resolver = market_resolver or NettoScottieMarketResolver(http).resolve
        self.last_market_url = self.BASE_URL + "/marktsuche/"
        self.last_market_label = "Netto schwarz"

    @staticmethod
    def _dates(text: str) -> tuple[date | None, date | None]:
        match = re.search(
            r"Angebote\s+vom\s*:\s*(\d{2})-(\d{2})-(\d{4})\s+bis\s+(\d{2})-(\d{2})-(\d{4})",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None, None
        try:
            return (
                date(int(match[3]), int(match[2]), int(match[1])),
                date(int(match[6]), int(match[5]), int(match[4])),
            )
        except ValueError:
            return None, None

    @staticmethod
    def _card_price(card) -> float | None:
        node = card.select_one("h3")
        if node is None:
            return None
        parts = list(node.stripped_strings)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return parse_number(f"{parts[0]}.{parts[1]}")
        match = re.search(r"(\d+)\s*[.,]\s*(\d{2})", clean_text(node.get_text(" ", strip=True)))
        return parse_number(f"{match[1]}.{match[2]}") if match else None

    @staticmethod
    def _regular_price(text: str) -> float | None:
        matches = re.findall(
            r"(?:Nicht[- ]Mitgliederpreis|statt)\s*(?:bis\s+zu\s*)?(\d+[.,]\d{2})",
            text,
            flags=re.IGNORECASE,
        )
        values = [value for value in (parse_number(item) for item in matches) if value and value > 0]
        return max(values) if values else None

    def load(self, postal_code: str) -> list[Offer]:
        market = self.market_resolver(postal_code)
        if not market:
            return []
        address = market.get("address") or {}
        self.last_market_label = clean_text(market.get("name")) or f"Netto schwarz {postal_code}"
        self.last_market_url = self.BASE_URL + "/marktsuche/"
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:  # pragma: no cover - installation guard
            raise ToolError(f"Netto schwarz benötigt BeautifulSoup: {exc}") from exc

        payload = self.http.get_bytes(self.OFFERS_URL, {"Accept": "text/html"})
        if len(payload) > self.MAX_RESPONSE:
            raise ToolError("Netto-schwarz-Antwort überschreitet das Größenlimit")
        page = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        start, end = self._dates(page.get_text(" ", strip=True))
        offers: list[Offer] = []
        for index, card in enumerate(page.select('[aria-label^="product-"]'), 1):
            title = card.select_one("h4")
            if title is None:
                continue
            title_lines = [clean_text(item) for item in title.get_text("\n", strip=True).splitlines() if clean_text(item)]
            if not title_lines:
                continue
            name = title_lines[-1]
            brand = " ".join(title_lines[:-1])
            description_node = card.select_one("p:not([class*='bg-primary'])")
            description = clean_text(description_node.get_text(" ", strip=True) if description_node else "")
            card_text = clean_text(card.get_text(" ", strip=True))
            shown_price = self._card_price(card)
            if shown_price is None or shown_price <= 0:
                continue
            is_app = bool(re.search(r"APP[- ]?PREIS|Netto\+", card_text, flags=re.IGNORECASE))
            regular_price = self._regular_price(card_text) if is_app else shown_price
            benefits: tuple[LoyaltyBenefit, ...] = ()
            if is_app and (regular_price is None or shown_price <= regular_price):
                benefits = (
                    LoyaltyBenefit("netto_scottie_plus", "direct_price", shown_price, "Netto+ App-Preis"),
                )
            elif not is_app:
                benefits = parse_public_loyalty_prices(card_text, regular_price, "Netto schwarz")
            base_price, base_unit = parse_base_price_text(description)
            pack_text = re.sub(
                r"(?:App:\s*)?(?:1\s*(?:kg|Liter|l)|100\s*(?:g|ml))\s*=\s*\d+[.,]\d+",
                " ",
                description,
                flags=re.IGNORECASE,
            )
            pack = normalize_pack(f"{name} {pack_text}")
            image = card.select_one("img[src]")
            image_url = urljoin(self.BASE_URL, clean_text(image.get("src"))) if image else ""
            offer_id = f"netto-scottie:{index}:{re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-')}"
            offers.append(Offer(
                offer_id=offer_id,
                retailer="Netto schwarz",
                category="Aktuelle Wochenangebote",
                name=name,
                brand=brand,
                description=description,
                price=regular_price,
                base_price=base_price,
                base_unit=base_unit,
                pack_signature=pack,
                validity_label=format_validity(start, end),
                match_key=build_match_key(brand, name, pack, offer_id),
                source_url=self.OFFERS_URL,
                product_url=self.OFFERS_URL,
                retailer_url=self.last_market_url,
                image_url=image_url,
                deposit=parse_deposit_text(card_text),
                coverage_note=f"Offizielle Wochenangebote; zugeordnet zu {self.last_market_label}, {clean_text(address.get('city'))}",
                valid_from=start.isoformat() if start else None,
                valid_until=end.isoformat() if end else None,
                benefits=benefits,
            ))
        if not offers:
            raise ToolError("Netto schwarz lieferte keine lesbaren Wochenangebote")
        return offers
