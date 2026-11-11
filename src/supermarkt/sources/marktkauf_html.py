"""Fill missing quantities from matching first-party Marktkauf weekly cards."""
import re
from dataclasses import replace
from datetime import date, timedelta

from bs4 import BeautifulSoup

from ..common import build_match_key, clean_text, normalize_pack, parse_number, today_berlin
from ..models import Offer


def enrich_quantities(offers: list[Offer], html: str, reference: date | None = None) -> list[Offer]:
    reference = reference or today_berlin()
    page = BeautifulSoup(html, "html.parser")
    week = re.search(r"Woche\s+vom\s+(\d{2})\.(\d{2})\.\s*[–-]\s*(\d{2})\.(\d{2})\.", page.get_text(" ", strip=True), re.I)
    if not week:
        return offers
    def name(value):
        return clean_text(re.sub(r"[\u200b-\u200f\u2060-\u206f\ufeff]", "", value)).casefold()
    cards = {}
    for card in page.select(".card"):
        title = card.select_one(".product-name")
        price = card.select_one(".special-price")
        description = card.select_one(".product-describtion")
        if title is None or price is None or description is None:
            continue
        amount = parse_number(price.get_text("", strip=True))
        pack = normalize_pack(description.get_text(" ", strip=True))
        if amount and pack:
            cards.setdefault((name(title.get_text(" ", strip=True)), amount), set()).add(pack)
    result = []
    for offer in offers:
        sizes = cards.get((name(offer.name), offer.price), set())
        if offer.pack_signature or len(sizes) != 1 or not offer.valid_from or not offer.valid_until:
            result.append(offer)
            continue
        start, end = date.fromisoformat(offer.valid_from), date.fromisoformat(offer.valid_until)
        if end < reference or start > reference + timedelta(days=7) or (start.day, start.month, end.day, end.month) != tuple(map(int, week.groups())):
            result.append(offer)
            continue
        pack = next(iter(sizes))
        result.append(replace(offer, pack_signature=pack,
            match_key=build_match_key(offer.brand, offer.name, pack, offer.offer_id),
            coverage_note=" · ".join(filter(None, [offer.coverage_note,
                "Fehlende Packungsangabe aus identischem Artikel/Preis der aktuellen Markt-Wochenseite ergänzt"]))))
    return result
