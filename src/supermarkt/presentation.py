from __future__ import annotations

import re
from typing import Any

from .common import (
    calculate_unit_price,
    clean_text,
    format_euro,
    format_pack,
    format_unit_price,
    normalize_base_unit,
)
from .loyalty import benefit_label
from .models import Offer, RetailerContext


def resolve_retailer_name(
    value: str,
    retailers: dict[str, RetailerContext],
) -> str:
    wanted = clean_text(value).casefold()
    if not wanted:
        return ""
    for name, context in retailers.items():
        aliases = {
            name.casefold(),
            *(clean_text(alias).casefold() for alias in context.aliases),
        }
        if wanted in aliases:
            return name
    return clean_text(value)


def offer_sort_key(offer: Offer, sort: str) -> tuple[Any, ...]:
    price = (
        offer.effective_price
        if offer.effective_price is not None
        else offer.price
    )
    normalized_price = float("inf") if price is None else float(price)

    if sort == "retailer":
        return (offer.retailer.casefold(), normalized_price, offer.name.casefold())
    if sort == "product":
        return (offer.name.casefold(), normalized_price, offer.retailer.casefold())
    if sort == "unit_price":
        unit = calculate_unit_price(offer, price)
        unit_value = unit[0] if unit is not None else float("inf")
        return (unit_value, normalized_price, offer.name.casefold())
    return (normalized_price, offer.name.casefold(), offer.retailer.casefold())


def _unit_price_label(offer: Offer, total_price: float | None) -> str:
    unit = calculate_unit_price(offer, total_price)
    if unit is not None:
        return format_unit_price(unit[0], unit[1])
    if offer.base_price is not None and total_price == offer.price:
        base_unit = normalize_base_unit(offer.base_unit)
        return (
            format_unit_price(offer.base_price, base_unit)
            if base_unit
            else format_euro(offer.base_price)
        )
    return ""


def _benefit_text(offer: Offer) -> str:
    parts: list[str] = []
    for benefit in offer.applied_benefits:
        label = benefit_label(benefit)
        if benefit.kind == "cashback":
            parts.append(f"{label}: {format_euro(benefit.value)} Guthaben")
        elif benefit.kind == "direct_price":
            parts.append(f"{label}: {format_euro(benefit.value)}")
        else:
            parts.append(label)
    return " · ".join(parts)


def _cashback_credit(offer: Offer) -> tuple[float, str]:
    benefits = [benefit for benefit in offer.applied_benefits if benefit.kind == "cashback" and benefit.value > 0]
    total = sum(benefit.value for benefit in benefits)
    labels = ", ".join(dict.fromkeys(benefit_label(benefit) for benefit in benefits))
    return total, f"+ {format_euro(total)} {labels}" if total > 0 and labels else ""


def _deposit_note(offer: Offer) -> str:
    if offer.deposit is None:
        return ""
    total = format_euro(offer.deposit)
    count_match = re.match(r"^(\d{1,3})x", offer.pack_signature, flags=re.IGNORECASE)
    if not count_match or offer.container_deposit is None:
        return f"zzgl. {total} Pfand"
    count = int(count_match.group(1))
    if count <= 1:
        return f"zzgl. {total} Pfand"
    container = "Dose" if re.search(r"\bdosen?\b|energy\s*drink", f"{offer.name} {offer.description}", re.I) else "Flasche" if re.search(r"\bflaschen?\b|\bkasten\b|\bkiste\b", f"{offer.name} {offer.description}", re.I) else "Einheit"
    breakdown = f"{format_euro(offer.container_deposit)} je {container} × {count}"
    if offer.packaging_deposit is not None:
        breakdown += f" + {format_euro(offer.packaging_deposit)} Kasten"
    return f"Pfand: {breakdown} = {total} gesamt"


def offer_for_response(
    offer: Offer,
    include_image_urls: bool,
) -> dict[str, Any]:
    regular = offer.price
    checkout = (
        offer.checkout_price
        if offer.checkout_price is not None
        else regular
    )
    effective = (
        offer.effective_price
        if offer.effective_price is not None
        else regular
    )

    cashback_credit, cashback_note = _cashback_credit(offer)
    result = {
        "offer_id": offer.offer_id,
        "retailer": offer.retailer,
        "category": offer.category,
        "source_category": offer.source_category,
        "detected_category": offer.detected_category,
        "category_conflict": offer.category_conflict,
        "product": offer.name,
        "brand": offer.brand,
        "description": offer.description,
        "regular_price": regular,
        "regular_price_text": format_euro(regular),
        "regular_comparison": offer.regular_comparison_note,
        "regular_comparison_state": offer.regular_comparison_state,
        "checkout_price": checkout,
        "checkout_price_text": format_euro(checkout),
        "effective_price": effective,
        "effective_price_text": format_euro(effective),
        "selected_comparison": offer.selected_comparison_note,
        "selected_comparison_state": offer.selected_comparison_state,
        "loyalty_savings": offer.loyalty_savings,
        "loyalty_savings_text": (
            format_euro(offer.loyalty_savings)
            if offer.loyalty_savings > 0.004
            else ""
        ),
        "loyalty_benefit": _benefit_text(offer),
        "cashback_credit": cashback_credit,
        "cashback_credit_text": format_euro(cashback_credit) if cashback_credit > 0 else "",
        "cashback_credit_note": cashback_note,
        "pack": format_pack(offer.pack_signature) if offer.pack_signature else "",
        "unit_price": _unit_price_label(offer, regular),
        "selected_unit_price": (
            _unit_price_label(offer, effective)
            if effective is not None
            and regular is not None
            and abs(effective - regular) > 0.004
            else ""
        ),
        "validity": offer.validity_label,
        "valid_from": offer.valid_from,
        "valid_until": offer.valid_until,
        "deposit": offer.deposit,
        "container_deposit": offer.container_deposit,
        "packaging_deposit": offer.packaging_deposit,
        "deposit_text": format_euro(offer.deposit) if offer.deposit is not None else "",
        "deposit_note": _deposit_note(offer),
        "minimum_quantity": offer.minimum_quantity,
        "offer_condition": offer.offer_condition,
        "coverage_note": offer.coverage_note,
        "product_link_kind": (
            "search"
            if "/q/search" in offer.product_url or "/suche/produkte" in offer.product_url
            else "market_offer"
            if offer.product_url and offer.product_url == offer.retailer_url
            else "direct"
            if offer.product_url
            else "none"
        ),
        "source_product_id": None,
        "ean": None,
    }
    if include_image_urls:
        result["image_url"] = offer.image_url
        result["source_url"] = offer.source_url
        result["product_url"] = offer.product_url
        result["retailer_url"] = offer.retailer_url
    return result
