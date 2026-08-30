from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable, Optional
from urllib.parse import urljoin

from ..common import (
    build_match_key,
    clean_description,
    clean_text,
    deduplicate_offers,
    format_validity,
    normalize_pack,
    normalize_offer_week,
    offer_week_reference,
    parse_base_price_text,
    parse_iso_date,
    parse_number,
    date_is_current,
)
from ..config import BERLIN
from ..images import is_rejected_image_url, normalize_image_url
from ..loyalty import parse_public_loyalty_prices
from ..models import Offer, ToolError


MarketFilter = Callable[[dict[str, Any]], bool]


class OfficialEdekaSource:
    MARKET_API = "https://www.edeka.de/api/marketsearch/markets"
    OFFERS_API = "https://www.edeka.de/eh/service/eh/offers"

    def __init__(self, timeout_seconds: int = 45) -> None:
        self.timeout_seconds = max(10, min(int(timeout_seconds), 90))
        self.last_market_id = ""
        self.last_market_label = ""
        self.last_market_url = ""
        self.last_raw_count = 0
        self.last_skipped_zero_price = 0

    def _session(self):
        try:
            from curl_cffi import requests as curl_requests
        except Exception as exc:
            raise ToolError(f"EDEKA benötigt curl_cffi: {exc}") from exc
        return curl_requests.Session(impersonate="chrome")

    @staticmethod
    def _markets(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("markets", "docs", "results", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _postal(market: dict[str, Any]) -> str:
        contact = market.get("contact") if isinstance(market.get("contact"), dict) else {}
        address = contact.get("address") if isinstance(contact.get("address"), dict) else {}
        city = address.get("city") if isinstance(address.get("city"), dict) else {}
        return clean_text(
            city.get("zipCode")
            or market.get("zipCode_keyword")
            or market.get("zipCode")
        )

    @staticmethod
    def _market_id(market: dict[str, Any]) -> str:
        return clean_text(
            market.get("id")
            or market.get("marketId")
            or market.get("marketID")
            or market.get("wwIdent")
        )

    @staticmethod
    def _docs(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            docs = payload.get("docs")
            if isinstance(docs, list):
                return [item for item in docs if isinstance(item, dict)]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    @staticmethod
    def _date_value(value: Any) -> Optional[date]:
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000.0
            try:
                return datetime.fromtimestamp(timestamp, tz=BERLIN).date()
            except (OverflowError, OSError, ValueError):
                return None
        return parse_iso_date(value)

    @classmethod
    def _validity_dates(cls, doc: dict[str, Any], payload: dict[str, Any]) -> tuple[Optional[date], Optional[date]]:
        start = cls._date_value(
            doc.get("gueltig_von")
            or doc.get("validFrom")
            or payload.get("gueltig_von")
            or payload.get("validFrom")
        )
        end = cls._date_value(
            doc.get("gueltig_bis")
            or doc.get("validUntil")
            or payload.get("gueltig_bis")
            or payload.get("validUntil")
        )
        return start, end

    @classmethod
    def _validity(cls, doc: dict[str, Any], payload: dict[str, Any]) -> str:
        start, end = cls._validity_dates(doc, payload)
        return format_validity(start, end)

    @staticmethod
    def _image(doc: dict[str, Any]) -> str:
        for field in ("bild_app", "bild_web130", "bild_web90"):
            candidate = normalize_image_url(doc.get(field))
            if candidate and not is_rejected_image_url(candidate):
                return candidate
        return ""

    def _select_market(
        self,
        session: Any,
        postal_code: str,
        retailer: str,
        market_filter: MarketFilter | None,
    ) -> tuple[str, str, str]:
        response = session.get(
            self.MARKET_API,
            params={"limit": 100, "searchstring": postal_code},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise ToolError(f"{retailer} Marktsuche HTTP {response.status_code}")
        try:
            payload = response.json()
        except Exception as exc:
            raise ToolError(f"{retailer} Marktsuche lieferte kein JSON: {exc}") from exc

        markets = self._markets(payload)
        usable = [market for market in markets if self._market_id(market)]
        if market_filter is not None:
            usable = [market for market in usable if market_filter(market)]

        exact = [market for market in usable if self._postal(market) == postal_code]
        market = exact[0] if exact else usable[0] if usable else None
        if market is None:
            raise ToolError(f"{retailer} fand für PLZ {postal_code} keinen nutzbaren Markt")

        market_id = self._market_id(market)
        market_label = clean_text(
            market.get("name")
            or market.get("title")
            or market.get("displayName")
            or f"{retailer} {postal_code}"
        )
        market_url = clean_text(
            market.get("url")
            or market.get("marketUrl")
            or market.get("detailUrl")
        )
        if market_url:
            market_url = urljoin("https://www.edeka.de", market_url)
        else:
            market_url = "https://www.edeka.de/marktsuche.jsp"
        return market_id, market_label, market_url

    def _load_offers(
        self,
        session: Any,
        *,
        retailer: str,
        market_id: str,
        market_url: str,
        reference_date: Optional[date] = None,
    ) -> tuple[list[Offer], int, int]:
        response = session.get(
            self.OFFERS_API,
            params={"marketId": market_id, "limit": 99999},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            raise ToolError(
                f"{retailer} Angebote HTTP {response.status_code} für Markt {market_id}"
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise ToolError(f"{retailer} Angebote lieferten kein JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ToolError(f"{retailer} Angebote lieferten kein Objekt")

        docs = self._docs(payload)
        offers: list[Offer] = []
        skipped_zero = 0
        prefix = retailer.casefold().replace(" ", "-")

        for index, doc in enumerate(docs):
            start, end = self._validity_dates(doc, payload)
            if (start or end) and not (date_is_current(start, end, reference_date) if reference_date else date_is_current(start, end)):
                continue

            title = clean_text(doc.get("titel"))
            price = parse_number(doc.get("preis"))
            if price is None or price <= 0:
                skipped_zero += 1
                continue
            if not title:
                continue

            description = clean_description(doc.get("beschreibung"))
            basic = clean_text(doc.get("basicPrice"))
            base_price, base_unit = parse_base_price_text(basic)
            if base_price is None:
                base_price, base_unit = parse_base_price_text(description)

            category = clean_text(doc.get("warengruppe")) or "Weitere Angebote"
            pack = normalize_pack(f"{title} {description}")
            raw_id = clean_text(doc.get("angebotid") or doc.get("externeid") or index)
            offer_id = f"{prefix}:{market_id}:{raw_id}"
            benefits = parse_public_loyalty_prices(
                " ".join(part for part in (description, basic) if part),
                price,
                retailer,
            )

            offers.append(
                Offer(
                    offer_id=offer_id,
                    retailer=retailer,
                    category=category,
                    name=title,
                    brand="",
                    description=description,
                    price=price,
                    base_price=base_price,
                    base_unit=base_unit,
                    pack_signature=pack,
                    validity_label=self._validity(doc, payload),
                    match_key=build_match_key("", title, pack, offer_id),
                    source_url=market_url,
                    image_url=self._image(doc),
                    benefits=benefits,
                )
            )

        return deduplicate_offers(offers), len(docs), skipped_zero

    def _load_retailer(
        self,
        postal_code: str,
        retailer: str,
        market_filter: MarketFilter | None = None,
        offer_week: str = "current",
    ) -> list[Offer]:
        session = self._session()
        market_id, market_label, market_url = self._select_market(
            session,
            postal_code,
            retailer,
            market_filter,
        )
        offers, raw_count, skipped_zero = self._load_offers(
            session,
            retailer=retailer,
            market_id=market_id,
            market_url=market_url,
            reference_date=offer_week_reference(offer_week) if normalize_offer_week(offer_week) == "next" else None,
        )

        self.last_market_id = market_id
        self.last_market_label = market_label
        self.last_market_url = market_url
        self.last_raw_count = raw_count
        self.last_skipped_zero_price = skipped_zero

        if not offers:
            raise ToolError(
                f"{retailer} Markt {market_id} lieferte keine preislich verwertbaren Angebote"
            )
        return offers

    def load(self, postal_code: str, offer_week: str = "current") -> list[Offer]:
        return self._load_retailer(postal_code, "EDEKA", offer_week=offer_week)


class OfficialMarktkaufSource(OfficialEdekaSource):
    @staticmethod
    def _is_marktkauf(market: dict[str, Any]) -> bool:
        try:
            haystack = json.dumps(
                market,
                ensure_ascii=False,
                sort_keys=True,
            ).casefold()
        except (TypeError, ValueError):
            haystack = clean_text(market).casefold()
        return "marktkauf" in haystack

    def load(self, postal_code: str, offer_week: str = "current") -> list[Offer]:
        return self._load_retailer(
            postal_code,
            "Marktkauf",
            self._is_marktkauf,
            offer_week,
        )
