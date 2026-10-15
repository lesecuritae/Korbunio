"""Quantity totals preserve unknown single prices and incomplete bundles."""
from __future__ import annotations

import re

from .models import Offer


def quantity_price(offer: Offer, quantity: int) -> dict:
    if quantity < 1:
        raise ValueError("Die Menge muss mindestens 1 sein.")
    minimum = offer.multi_buy_quantity
    total = offer.multi_buy_total_price
    if minimum and total is not None:
        # This helper has no verified membership/coupon selection context.
        if re.search(r"card|karte|coupon|kupon|aktivier|mitglied|xtra|\bapp\b", offer.multi_buy_condition, re.IGNORECASE):
            return {"total_cents": None, "known_subtotal_cents": 0, "unknown_quantity": quantity}
        bundles, remainder = divmod(quantity, minimum)
        subtotal = bundles * round(total * 100)
        unknown = remainder if offer.single_price is None else 0
        if offer.single_price is not None:
            subtotal += remainder * round(offer.single_price * 100)
    else:
        unknown = quantity if offer.price is None else 0
        subtotal = 0 if offer.price is None else quantity * round(offer.price * 100)
    return {"total_cents": None if unknown else subtotal, "known_subtotal_cents": subtotal,
            "unknown_quantity": unknown}
