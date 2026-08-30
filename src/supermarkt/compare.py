from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any, Iterable
from datetime import date
from urllib.parse import quote_plus
import re

from .common import (
    build_match_key,
    calculate_unit_price,
    clean_brand,
    clean_description,
    clean_text,
    extract_image_url,
    format_euro,
    format_unit_price,
    identify_retailer,
    normalize_pack,
    offer_validity,
    parse_deposit_text,
    parse_number,
)
from .loyalty import apply_selected_programs, parse_public_loyalty_prices
from .models import AGGREGATOR_RETAILERS, ComparisonResult, Offer, RetailerContext


# Public Marktguru retailer landing pages used as the source link for offers
# that come from the regional aggregator catalogue.
MARKTGURU_RETAILER_SLUGS = {
    "Lidl": "lidl",
    "PENNY": "penny",
    "Netto Marken-Discount": "netto-marken-discount",
    "Globus": "globus",
    "Combi": "combi",
    "famila Nordwest": "famila-nordwest",
}


class OfferMapper:
    def map_all(
        self,
        raw_offers: Iterable[dict[str, Any]],
        retailers: dict[str, RetailerContext],
        reference_date: date | None = None,
    ) -> list[Offer]:
        unique: dict[tuple[Any, ...], Offer] = {}
        for raw in raw_offers:
            offer = self.map_one(raw, retailers, reference_date)
            if offer is None:
                continue
            benefit_key = tuple(
                (item.program_id, item.kind, item.value)
                for item in offer.benefits
            )
            key = (
                offer.retailer,
                offer.match_key,
                offer.price,
                benefit_key,
                offer.validity_label,
            )
            unique.setdefault(key, offer)
        return list(unique.values())

    def map_one(
        self,
        raw: dict[str, Any],
        retailers: dict[str, RetailerContext],
        reference_date: date | None = None,
    ) -> Offer | None:
        retailer = identify_retailer(raw, retailers)
        is_current, validity_label = offer_validity(raw, reference_date)
        if retailer is None or not is_current:
            return None

        product = raw.get("product") if isinstance(raw.get("product"), dict) else {}
        brand_data = raw.get("brand") if isinstance(raw.get("brand"), dict) else {}
        name = clean_text(product.get("name")) or clean_text(raw.get("name"))
        brand = clean_brand(brand_data.get("name"))
        description = " · ".join(
            dict.fromkeys(
                text
                for text in (
                    clean_description(product.get("description")),
                    clean_description(raw.get("description")),
                )
                if text
            )
        )
        if not name:
            name = description or "Unbenanntes Angebot"
        display_name = (
            name
            if not brand or brand.casefold() in name.casefold()
            else f"{brand} {name}"
        )

        price = parse_number(raw.get("price"))
        benefits = parse_public_loyalty_prices(description, price, retailer)
        unit_data = raw.get("unit") if isinstance(raw.get("unit"), dict) else {}
        categories = raw.get("categories") if isinstance(raw.get("categories"), list) else []
        category = next(
            (
                clean_text(item.get("name"))
                for item in categories
                if isinstance(item, dict) and clean_text(item.get("name"))
            ),
            "Weitere Angebote",
        )
        pack_signature = normalize_pack(f"{name} {description}")
        offer_id = str(raw.get("id") or "")
        match_key = build_match_key(
            brand,
            name,
            pack_signature,
            f"{retailer}:{offer_id}",
        )
        context = retailers[retailer]
        source_url = context.market_url
        product_url = ""
        retailer_slug = MARKTGURU_RETAILER_SLUGS.get(retailer)
        if retailer in AGGREGATOR_RETAILERS and retailer_slug:
            source_url = f"https://www.marktguru.de/r/{retailer_slug}"
        if retailer == "Lidl":
            # Lidl redirects some over-specific catalogue names (own brand +
            # marketing suffix) to its home page. Prefer a conservative,
            # deterministic product-type term when one is explicit in the
            # source name. This remains a search fallback, never an identity
            # claim or a guessed product detail link.
            search_term = display_name
            for pattern, label in (
                (r"\benergy[- ]?drink\b", "Energy-Drink"),
                (r"\bjoghurt\b", "Joghurt"),
                (r"\bkaffee\b", "Kaffee"),
                (r"\bbutter\b", "Butter"),
                (r"\bmilch\b", "Milch"),
                (r"\bmineralwasser\b", "Mineralwasser"),
            ):
                if re.search(pattern, display_name, flags=re.IGNORECASE):
                    search_term = label
                    break
            product_url = f"https://www.lidl.de/q/search?q={quote_plus(search_term)}"

        return Offer(
            offer_id=offer_id or f"{retailer}:{match_key}:{price}",
            retailer=retailer,
            category=category,
            name=display_name,
            brand=brand,
            description=description,
            price=price,
            base_price=parse_number(raw.get("referencePrice")),
            base_unit=clean_text(unit_data.get("shortName") or unit_data.get("name")),
            pack_signature=pack_signature,
            validity_label=validity_label,
            match_key=match_key,
            source_url=source_url,
            product_url=product_url,
            retailer_url=context.market_url,
            image_url=extract_image_url(product) or extract_image_url(raw),
            deposit=parse_deposit_text(description),
            benefits=benefits,
        )


class OfferComparator:
    """Compare identical offers both without and with selected loyalty programs."""

    def compare(
        self,
        offers: list[Offer],
        loyalty_programs: Iterable[str],
        view: str,
    ) -> ComparisonResult:
        selected_programs = tuple(loyalty_programs)
        prepared = [replace(offer) for offer in offers]

        for offer in prepared:
            checkout, effective, savings, applied = apply_selected_programs(
                offer,
                selected_programs,
            )
            offer.checkout_price = checkout
            offer.effective_price = effective
            offer.loyalty_savings = savings
            offer.applied_benefits = applied
            offer.regular_comparison_note = ""
            offer.regular_comparison_state = "none"
            offer.selected_comparison_note = ""
            offer.selected_comparison_state = "none"

        groups: dict[str, list[Offer]] = defaultdict(list)
        for offer in prepared:
            groups[offer.match_key].append(offer)

        visible: list[Offer] = []
        hidden_count = 0
        for group in groups.values():
            self._compare_group(
                group,
                price_attr="price",
                state_attr="regular_comparison_state",
                note_attr="regular_comparison_note",
            )
            self._compare_group(
                group,
                price_attr="effective_price",
                state_attr="selected_comparison_state",
                note_attr="selected_comparison_note",
            )

            if view == "best_only" and len(group) > 1:
                winners = [
                    offer
                    for offer in group
                    if offer.selected_comparison_state == "best"
                    or (
                        selected_programs
                        and offer.regular_comparison_state == "best"
                    )
                ]
                if winners:
                    visible.extend(winners)
                    hidden_count += len(group) - len(winners)
                    continue
            visible.extend(group)

        visible.sort(
            key=lambda offer: (
                offer.category.casefold(),
                offer.name.casefold(),
                offer.effective_price
                if offer.effective_price is not None
                else float("inf"),
                offer.retailer,
            )
        )
        return ComparisonResult(offers=visible, hidden_count=hidden_count)

    def _compare_group(
        self,
        group: list[Offer],
        *,
        price_attr: str,
        state_attr: str,
        note_attr: str,
    ) -> None:
        if len(group) < 2 or group[0].match_key.startswith("unique:"):
            return

        values, comparison_unit = self._comparison_values(group, price_attr)
        comparable = [offer for offer in group if id(offer) in values]
        if len(comparable) < 2:
            return

        minimum = min(values[id(offer)] for offer in comparable)
        winners = [
            offer
            for offer in comparable
            if abs(values[id(offer)] - minimum) < 0.005
        ]
        winner_names = ", ".join(
            dict.fromkeys(offer.retailer for offer in winners)
        )

        for offer in comparable:
            own_value = values[id(offer)]
            if abs(own_value - minimum) < 0.005:
                setattr(offer, state_attr, "best")
                setattr(
                    offer,
                    note_attr,
                    self._winner_note(
                        offer,
                        comparable,
                        values,
                        comparison_unit,
                    ),
                )
            else:
                setattr(offer, state_attr, "expensive")
                setattr(
                    offer,
                    note_attr,
                    self._loser_note(
                        own_value,
                        minimum,
                        winner_names,
                        comparison_unit,
                    ),
                )

    @staticmethod
    def _comparison_values(
        group: list[Offer],
        price_attr: str,
    ) -> tuple[dict[int, float], str]:
        unit_values: dict[int, tuple[float, str]] = {}
        common_unit = ""
        for offer in group:
            price = getattr(offer, price_attr)
            unit_price = calculate_unit_price(offer, price)
            if unit_price is None:
                unit_values = {}
                break
            value, unit, _calculated = unit_price
            if common_unit and unit != common_unit:
                unit_values = {}
                break
            common_unit = unit
            unit_values[id(offer)] = (value, unit)

        if len(unit_values) == len(group):
            return (
                {
                    offer_id: value
                    for offer_id, (value, _unit) in unit_values.items()
                },
                common_unit,
            )

        if len({offer.pack_signature for offer in group}) == 1:
            values = {
                id(offer): float(getattr(offer, price_attr))
                for offer in group
                if getattr(offer, price_attr) is not None
            }
            return values, ""

        return {}, ""

    @staticmethod
    def _winner_note(
        offer: Offer,
        group: list[Offer],
        values: dict[int, float],
        unit: str,
    ) -> str:
        more_expensive = [
            item
            for item in group
            if values[id(item)] > values[id(offer)] + 0.005
        ]
        if not more_expensive:
            others = ", ".join(
                item.retailer for item in group if item is not offer
            )
            return f"Gleich günstig wie {others}" if others else "Günstigster Preis"

        closest = min(more_expensive, key=lambda item: values[id(item)])
        difference = values[id(closest)] - values[id(offer)]
        label = (
            format_unit_price(difference, unit)
            if unit
            else format_euro(difference)
        )
        return f"{label} günstiger als {closest.retailer}"

    @staticmethod
    def _loser_note(
        own: float,
        minimum: float,
        winners: str,
        unit: str,
    ) -> str:
        own_label = format_unit_price(own, unit) if unit else format_euro(own)
        minimum_label = (
            format_unit_price(minimum, unit)
            if unit
            else format_euro(minimum)
        )
        difference_label = (
            format_unit_price(own - minimum, unit)
            if unit
            else format_euro(own - minimum)
        )
        qualifier = " beim Grundpreis" if unit else ""
        return (
            f"{winners} ist{qualifier} günstiger: {minimum_label} statt "
            f"{own_label} ({difference_label} weniger)"
        )
