"""The current public, market-bound EDEKA offer HTML, without browser execution."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..common import (build_match_key, clean_text, deduplicate_offers, format_validity,
                      normalize_pack, parse_deposit_text, parse_iso_date, parse_number,
                      parse_base_price_text, date_is_current)
from ..models import LoyaltyBenefit, Offer, ToolError


PERIOD = re.compile(r"Gültig\s+vom\s+(\d{2}\.\d{2}\.\d{4})\s+bis\s+zum\s+(\d{2}\.\d{2}\.\d{4})", re.I)
CASH = re.compile(r"^(?:Festpreis|Rabattierter Preis)\s+von\s+(\d+[.,]\d{2})\s*€", re.I)
APP = re.compile(r"^App Preis\s+von\s+(\d+[.,]\d{2})\s*€", re.I)


def _offer_from_dialog(dialog, source_url: str, retailer: str, market_id: str, start: date, end: date, target: date) -> Offer | None:
    try:
        event = json.loads(dialog["data-tracking-event"])
        item = event[1]
        if event[0] != "view_promotion" or item.get("promotion_type") != "OFFER":
            return None
        identifier = clean_text(item.get("promotion_id"))
        name = clean_text(item.get("promotion_item_name"))
        until = parse_iso_date(item.get("promotion_item_expiration_date"))
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise ToolError("EDEKA: unbekannte öffentliche Angebotsmetadaten") from exc
    if not identifier or not name or not until or until < start:
        raise ToolError("EDEKA: unvollständige öffentliche Angebotsmetadaten")
    if not date_is_current(start, min(end, until), target):
        return None
    labels = [clean_text(n.get_text(" ", strip=True)) for n in dialog.select("span.sr-only")]
    cash = {parse_number(m[1]) for text in labels if (m := CASH.match(text))}
    app = {parse_number(m[1]) for text in labels if (m := APP.match(text))}
    if len(cash) != 1 or None in cash or len(app) > 1:
        raise ToolError("EDEKA: öffentlicher Kassenpreis nicht eindeutig; kein App-/UVP-Ersatz")
    price = next(iter(cash))
    if price <= 0:
        raise ToolError("EDEKA: ungültiger Kassenpreis")
    # Only the article description; legal text and prior prices are not quantities.
    description = clean_text(dialog.select_one("p.line-clmap-2").get_text(" ", strip=True)) if dialog.select_one("p.line-clmap-2") else ""
    pack = normalize_pack(description)
    benefit = next(iter(app)) if app else None
    benefits = (LoyaltyBenefit("edeka_app" if retailer == "EDEKA" else "marktkauf_app", "direct_price", benefit, "App-Preis"),) if benefit is not None and 0 < benefit < price else ()
    bundle = re.search(r"(\d{1,3})\s*Stück\s*,\s*Preis\s+beim\s+Kauf\s+von\s+1\s*Stück\s*:\s*€?\s*(\d+[.,]\d{2})", description, re.I)
    quantity = int(bundle[1]) if bundle and int(bundle[1]) > 1 else None
    bundle_total = price if quantity else None
    single = parse_number(bundle[2]) if quantity else None
    if quantity:
        if benefits:
            raise ToolError("EDEKA: Mehrkauf mit App-Preis nicht eindeutig kombiniert")
        price = bundle_total / quantity
        pack = "1stk"
    base_price, base_unit = parse_base_price_text(description)
    image = next((urljoin(source_url, img.get("src", "")) for img in dialog.select("img[src]")
                  if urlsplit(urljoin(source_url, img["src"])).hostname == "offer-images.api.edeka"
                  and "LOG_" not in img["src"]), "")
    offer_id = f"{retailer.casefold()}:html:{market_id}:{identifier}"
    return Offer(offer_id, retailer, clean_text(item.get("promotion_item_category")) or "Weitere Angebote",
        name, clean_text(item.get("promotion_item_brand")), description, price, base_price, base_unit, pack,
        format_validity(start, min(end, until)), build_match_key("", name, pack, offer_id), source_url,
        image_url=image, product_url=source_url, retailer_url=source_url,
        valid_from=start.isoformat(), valid_until=min(end, until).isoformat(),
        product_gtins=tuple(sorted({str(v) for v in item.get("promotion_item_included_products", []) if isinstance(v, str) and v.isdigit() and len(v) in {8, 12, 13, 14}})),
        deposit=parse_deposit_text(description), benefits=benefits,
        multi_buy_quantity=quantity, multi_buy_total_price=bundle_total, single_price=single,
        minimum_quantity=quantity, pack_size=pack,
        multi_buy_condition=f"{quantity} Stück für {bundle_total:.2f} €" if quantity else "",
        offer_condition=f"ab {quantity} Stück" if quantity else "", comparison_eligible=quantity is None)


def parse_market_offers(html: str, source_url: str, retailer: str, market_id: str, target: date) -> list[Offer]:
    page = BeautifulSoup(html, "html.parser")
    periods = {(m[1], m[2]) for m in PERIOD.finditer(page.get_text(" ", strip=True))}
    if len(periods) != 1:
        raise ToolError("EDEKA: moderner Marktprospekt ohne eindeutigen veröffentlichten Zeitraum")
    start_text, end_text = next(iter(periods))
    try:
        start, end = (datetime.strptime(value, "%d.%m.%Y").date() for value in (start_text, end_text))
    except ValueError as exc:
        raise ToolError("EDEKA: ungültiger öffentlicher Prospektzeitraum") from exc
    if start > end:
        raise ToolError("EDEKA: widersprüchlicher Prospektzeitraum")
    result = [
        offer
        for dialog in page.select('dialog[id^="dialog-angebot-"][data-tracking-event]')
        if (offer := _offer_from_dialog(dialog, source_url, retailer, market_id, start, end, target)) is not None
    ]
    if not result and start <= target <= end:
        raise ToolError("EDEKA: moderner Marktprospekt ohne lesbare Angebotsdialoge")
    return deduplicate_offers(result)
