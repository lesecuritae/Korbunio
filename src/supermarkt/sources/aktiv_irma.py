from __future__ import annotations

import copy
import re
from datetime import date, datetime
from urllib.parse import urljoin

from ..common import (
    build_match_key,
    clean_text,
    format_validity,
    normalize_pack,
    parse_base_price_text,
    parse_number,
)
from ..http import HttpClient
from ..models import Offer, ToolError

_VALIDITY = re.compile(
    r"^(?P<category>.+?):\s*(?P<vendor>.+?)\s+g[uü]ltig\s+vom\s+"
    r"(?P<start>\d{2}\.\d{2}\.\d{4})\s+bis\s+zum\s+(?P<end>\d{2}\.\d{2}\.\d{4})",
    re.IGNORECASE,
)
# Price nodes live inside the product card and must not bleed into the
# description text; they are read on their own and stripped from the copy.
_PRICE_NODES = (".fr-price-box", ".fr-price-angebot", ".fr-price-statt", ".fr-price-app", ".fr-produktButton")


def _german_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(clean_text(value), "%d.%m.%Y").date()
    except (ValueError, TypeError):
        return None


class OfficialAktivIrmaSource:
    """aktiv & irma weekly offers, parsed from the retailer's own HTML page.

    aktiv & irma (regional around Oldenburg/Hude/Wardenburg) publishes its full
    weekly flyer as server-rendered product cards grouped into category tabs,
    each tab carrying its own validity window. Marktguru carries no aktiv & irma
    offer feed, so this first-party page is the source. Some tabs (e.g. the
    Kramerhof butcher) carry a different supplier; that is kept in the note.
    """

    BASE = "https://www.aktiv-irma.de"
    OFFERS_URL = BASE + "/angebote/"
    MAX_RESPONSE = 4_000_000

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def _html(self, url: str) -> str:
        data = self.http.get_bytes(url, {"Accept": "text/html", "Accept-Language": "de-DE,de;q=0.9"})
        if len(data) > self.MAX_RESPONSE:
            raise ToolError("aktiv-&-irma-Antwort überschreitet das Größenlimit")
        return data.decode("utf-8", errors="replace")

    def load(self, postal_code: str = "") -> list[Offer]:
        # The weekly flyer is identical across all aktiv & irma stores; the
        # postal code is accepted for a uniform source interface but unused.
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:  # pragma: no cover - dependency guard
            raise ToolError(f"aktiv & irma benötigt BeautifulSoup: {exc}") from exc
        return self.parse(self._html(self.OFFERS_URL))

    def parse(self, html: str) -> list[Offer]:
        from bs4 import BeautifulSoup

        page = BeautifulSoup(html, "html.parser")
        result: list[Offer] = []
        for panel in page.select("li.js-tabs-content"):
            label_node = panel.find(
                lambda tag: tag.name in ("h2", "h3", "h4", "div", "span", "a")
                and "ltig vom" in clean_text(tag.get_text(" ", strip=True))
            )
            match = _VALIDITY.match(clean_text(label_node.get_text(" ", strip=True))) if label_node else None
            category = clean_text(match.group("category")) if match else ""
            vendor = clean_text(match.group("vendor")) if match else ""
            start = _german_date(match.group("start")) if match else None
            end = _german_date(match.group("end")) if match else None
            for card in panel.select(".fr-product-card"):
                offer = self._offer(card, category, vendor, start, end, len(result) + 1)
                if offer is not None:
                    result.append(offer)
        if not result:
            raise ToolError("aktiv & irma lieferte keine lesbaren Wochenangebote")
        return result

    def _offer(self, card, category, vendor, start, end, index) -> Offer | None:
        name = clean_text(card.select_one("h3.uk-card-title").get_text(" ", strip=True)) if card.select_one("h3.uk-card-title") else ""
        price_node = card.select_one(".fr-price-angebot")
        price = parse_number(clean_text(price_node.get_text(" ", strip=True)) if price_node else None)
        if not name or price is None or price <= 0:
            return None
        statt_node = card.select_one(".fr-price-statt")
        statt = clean_text(statt_node.get_text(" ", strip=True)) if statt_node else ""

        # Description without the price nodes, which otherwise bleed into the text.
        description = ""
        container = card.select_one(".product-description-container")
        if container is not None:
            trimmed = copy.copy(container)
            for selector in _PRICE_NODES:
                for node in trimmed.select(selector):
                    node.decompose()
            description = clean_text(trimmed.get_text(" ", strip=True))

        base_price, base_unit = parse_base_price_text(description)
        pack = normalize_pack(description)
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        offer_id = f"aktiv-irma:{index}:{slug}"
        image_url = ""
        image = card.select_one("img[data-srcset], img[src]")
        if image is not None:
            image_url = urljoin(self.BASE, clean_text(image.get("data-srcset") or image.get("src")))
        is_partner = bool(vendor) and vendor.casefold().replace(" ", "") not in {"aktiv&irma"}
        note = "Wochenprospekt aktiv & irma" + (f"; Lieferant {vendor}" if is_partner else "")
        return Offer(
            offer_id=offer_id,
            retailer="aktiv & irma",
            category=category or "Sonstiges",
            name=name,
            brand="",
            description=description,
            price=price,
            base_price=base_price,
            base_unit=base_unit,
            pack_signature=pack,
            validity_label=format_validity(start, end),
            match_key=build_match_key("", name, pack, offer_id),
            source_url=self.OFFERS_URL,
            product_url=self.OFFERS_URL,
            retailer_url=self.OFFERS_URL,
            image_url=image_url,
            source_category=category,
            offer_condition=statt,
            coverage_note=note,
            valid_from=start.isoformat() if start else None,
            valid_until=end.isoformat() if end else None,
        )
