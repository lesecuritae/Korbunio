"""Public weekly source fields recovered with operator-authorized test DNS.

This is an offline parser contract, not a live DNS or nationwide coverage test.
"""
import json
from datetime import date
from pathlib import Path

from supermarkt.sources.aldi import OfficialAldiSource


def test_five_actual_south_brochure_products_keep_published_cash_prices_and_period():
    products = json.loads((Path(__file__).parent / "fixtures/offer_coverage/aldi_sued_published_products.json").read_text())
    period = (date(2026, 11, 9), date(2026, 11, 14))
    offers = [OfficialAldiSource._south_brochure_product_offer(
        product, "https://prospekt.aldi-sued.de/kw46-26-op-mp", period,
    ) for product in products]
    assert all(offer is not None for offer in offers)
    assert {offer.name: (offer.price, offer.pack_signature) for offer in offers} == {
        "Gurke": (0.75, ""), "Mango": (1.19, ""),
        "Äpfel Krumme Dinger": (1.99, "2000g"),
        "MEINE METZGEREI Puten-Ministeaks": (4.59, "400g"),
        "MEINE METZGEREI Hamburger": (4.39, "400g"),
    }
    assert all(offer.retailer == "ALDI Süd" for offer in offers)
    assert all((offer.valid_from, offer.valid_until) == ("2026-11-09", "2026-11-14") for offer in offers)
    # Neither produce item declares a weight: do not manufacture one.
    assert len({offer.offer_id for offer in offers}) == 5
