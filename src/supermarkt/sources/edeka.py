from __future__ import annotations

from ..request_state import RequestState

import json
import re
from collections import Counter
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Callable, Optional
from urllib.parse import quote, urljoin, urlsplit

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
from ..http import curl_cffi_session
from ..images import is_rejected_image_url, normalize_image_url
from ..loyalty import parse_public_loyalty_prices
from ..models import Offer, ToolError, PartialOffers


MarketFilter = Callable[[dict[str, Any]], bool]


class OfficialEdekaSource:
    last_market_label = RequestState("")
    last_market_url = RequestState("")

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
        return curl_cffi_session("EDEKA")

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

    # How many markets are tried before giving up. The market search already
    # returns the nearest ones first, so a handful covers the surrounding area
    # without hammering the API.
    MAX_MARKET_CANDIDATES = 6

    def _candidate_markets(
        self,
        session: Any,
        postal_code: str,
        retailer: str,
        market_filter: MarketFilter | None,
    ) -> list[tuple[str, str, str]]:
        """Markets to try, best first: exact postal code, then the nearest."""
        response = session.get(
            self.MARKET_API,
            params={"size": 100, "searchstring": postal_code},
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
        if not usable:
            raise ToolError(f"{retailer} fand für PLZ {postal_code} keinen nutzbaren Markt")

        exact = [market for market in usable if self._postal(market) == postal_code]
        rest = [market for market in usable if self._postal(market) != postal_code]
        candidates: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for market in (exact + rest)[: self.MAX_MARKET_CANDIDATES]:
            market_id = self._market_id(market)
            if market_id in seen:
                continue
            seen.add(market_id)
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
            candidates.append((market_id, market_label, market_url))
        return candidates

    def _select_market(
        self,
        session: Any,
        postal_code: str,
        retailer: str,
        market_filter: MarketFilter | None,
    ) -> tuple[str, str, str]:
        return self._candidate_markets(session, postal_code, retailer, market_filter)[0]

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
                    valid_from=start.isoformat() if start else None,
                    valid_until=end.isoformat() if end else None,
                    match_key=build_match_key("", title, pack, offer_id),
                    source_url=market_url,
                    image_url=self._image(doc),
                    benefits=benefits,
                )
            )

        return deduplicate_offers(offers), len(docs), skipped_zero

    @staticmethod
    def preserve_offer_ids(previous: list[Offer], current: list[Offer]) -> list[Offer]:
        """Preserve favorites/history identity only for unambiguous exact matches.

        No fuzzy title/price matching, and never bind two GTIN variants to one
        old row when their old public fields were indistinguishable.
        """
        def key(o):
            return (o.retailer, clean_text(o.name).casefold(), o.price, o.pack_signature,
                    clean_text(o.description).casefold(), o.valid_from, o.valid_until)
        old_counts = Counter(map(key, previous))
        new_counts = Counter(map(key, current))
        old = {key(o): o for o in previous if old_counts[key(o)] == 1}
        return [replace(o, offer_id=old[key(o)].offer_id,
                    base_price=o.base_price if o.base_price is not None else old[key(o)].base_price,
                    base_unit=o.base_unit or old[key(o)].base_unit,
                    image_url=o.image_url or old[key(o)].image_url)
                if key(o) in old and new_counts[key(o)] == 1 else o for o in current]

    def _load_public_market(self, session: Any, market_url: str, market_id: str, retailer: str, target: date) -> list[Offer] | None:
        """Follow only the selected official market's own offer link.

        External Marktkauf domains keep their existing adapter. A global EDEKA
        offer page or a different branch is not an enrichment for this market.
        """
        from bs4 import BeautifulSoup
        from .edeka_html import parse_market_offers
        parsed = urlsplit(market_url)
        if parsed.scheme != "https" or parsed.hostname != "www.edeka.de" or not parsed.path.startswith(("/eh/", "/maerkte/")):
            return None
        response = session.get(quote(market_url, safe=":/?=&%"), timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise ToolError(f"EDEKA Marktseite HTTP {response.status_code}")
        final = urlsplit(getattr(response, "url", market_url))
        if final.scheme != "https" or final.hostname != "www.edeka.de":
            raise ToolError("EDEKA: Marktseite verweist auf fremden Ursprung")
        text = getattr(response, "text", "")
        if not isinstance(text, str) or len(text) > 5_000_000:
            raise ToolError("EDEKA Marktseite nicht lesbar oder zu groß")
        page = BeautifulSoup(text, "html.parser")
        urls = {urljoin(market_url, a["href"]).rstrip("/") + "/" for a in page.select('a[href]')
                if re.fullmatch(r"/maerkte/\d+/angebote/?", urlsplit(urljoin(market_url, a["href"])).path)
                and urlsplit(urljoin(market_url, a["href"])).hostname == "www.edeka.de"
                and urlsplit(urljoin(market_url, a["href"])).scheme == "https"}
        if len(urls) != 1:
            raise ToolError("EDEKA: kein eindeutiger Angebotslink des gewählten Marktes")
        url = next(iter(urls))
        response = session.get(url, timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise ToolError(f"EDEKA Marktangebote HTTP {response.status_code}")
        final = urlsplit(getattr(response, "url", url))
        if final.scheme != "https" or final.hostname != "www.edeka.de" or final.path.rstrip("/") != urlsplit(url).path.rstrip("/"):
            raise ToolError("EDEKA: Angebotsseite verweist auf anderen Markt")
        text = getattr(response, "text", "")
        if not isinstance(text, str) or len(text) > 5_000_000:
            raise ToolError("EDEKA Marktangebote nicht lesbar oder zu groß")
        return parse_market_offers(text, url, retailer, market_id, target)

    def _load_retailer(
        self,
        postal_code: str,
        retailer: str,
        market_filter: MarketFilter | None = None,
        offer_week: str = "current",
    ) -> list[Offer]:
        session = self._session()
        candidates = self._candidate_markets(
            session,
            postal_code,
            retailer,
            market_filter,
        )
        reference_date = (
            offer_week_reference(offer_week)
            if normalize_offer_week(offer_week) == "next"
            else None
        )
        problems: list[str] = []
        for market_id, market_label, market_url in candidates:
            legacy_error = None
            try:
                offers, raw_count, skipped_zero = self._load_offers(
                    session,
                    retailer=retailer,
                    market_id=market_id,
                    market_url=market_url,
                    reference_date=reference_date,
                )
            except Exception as exc:
                # The selected public market page can still be readable when
                # the old JSON endpoint fails. No alternate market is invented.
                legacy_error = exc
                offers, raw_count, skipped_zero = [], 0, 0

            note = ""
            try:
                modern = self._load_public_market(session, market_url, market_id, retailer,
                    reference_date or offer_week_reference("current"))
                if modern:
                    offers = self.preserve_offer_ids(offers, modern)
                    raw_count, skipped_zero = len(modern), 0
            except Exception as exc:
                note = f"Öffentliche Marktanzeige nicht abgeglichen; API-Angebote beibehalten: {exc}"
            if offers and retailer == "Marktkauf":
                try:
                    offers = self._enrich_market_quantities(session, market_url, offers)
                except Exception as exc:
                    note = " · ".join(filter(None, (note, f"Markt-Packungsangaben nicht abgeglichen: {exc}")))
            if not offers:
                problems.append(f"Markt {market_id}: {legacy_error or note or 'keine preislich verwertbaren Angebote'}")
                continue
            self.last_market_id = market_id
            self.last_market_label = market_label
            self.last_market_url = market_url
            self.last_raw_count = raw_count
            self.last_skipped_zero_price = skipped_zero
            return PartialOffers(offers, note) if note else offers

        raise ToolError(
            f"{retailer}: {len(candidates)} Märkte in der Nähe von {postal_code} geprüft, "
            f"keiner lieferte Angebote mit Preisen ({'; '.join(problems[:3])})"
        )

    def load(self, postal_code: str, offer_week: str = "current") -> list[Offer]:
        return self._load_retailer(postal_code, "EDEKA", offer_week=offer_week)


class OfficialMarktkaufSource(OfficialEdekaSource):
    def _enrich_market_quantities(self, session: Any, market_url: str, offers: list[Offer]) -> list[Offer]:
        # Only independently checked first-party sites, no arbitrary upstream URL.
        parsed = urlsplit(market_url)
        if parsed.hostname not in {"www.dein-marktkauf.de", "dein-marktkauf.de", "marktkauf-frechen.de", "www.marktkauf-frechen.de"}:
            return offers
        from .marktkauf_html import enrich_quantities
        url = parsed._replace(scheme="https").geturl()
        response = session.get(quote(url, safe=":/?=&%"), timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise ToolError(f"Marktkauf Marktseite HTTP {response.status_code}")
        final = urlsplit(getattr(response, "url", url))
        if final.scheme != "https" or final.hostname not in {parsed.hostname, "www." + parsed.hostname.removeprefix("www."), parsed.hostname.removeprefix("www.")}:
            raise ToolError("Marktkauf: Marktseite verweist auf fremden Ursprung")
        text = getattr(response, "text", "")
        if not isinstance(text, str) or len(text) > 5_000_000:
            raise ToolError("Marktkauf Marktseite nicht lesbar oder zu groß")
        return enrich_quantities(offers, text)

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
