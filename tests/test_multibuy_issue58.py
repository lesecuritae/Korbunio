from dataclasses import replace

import pytest

from supermarkt.common import filter_offers
from supermarkt.compare import OfferComparator
from supermarkt.models import Offer, offer_from_dict, offer_to_dict
from supermarkt.multibuy import quantity_price
from supermarkt.presentation import offer_for_response


def bundle():
    return Offer(offer_id="kaufland:emeukal", retailer="Kaufland", category="Bonbons", name="Em-eukal",
                 brand="", description="", price=3.0, base_price=None, base_unit="", pack_signature="75g",
                 validity_label="08.–14.10.2026", match_key="emeukal", source_url="https://example.invalid",
                 multi_buy_quantity=3, multi_buy_total_price=3.0, pack_size="75g",
                 multi_buy_condition="3 Stück für 3 €", minimum_quantity=3,
                 offer_condition="3 Stück für 3 €", comparison_eligible=False)


@pytest.mark.parametrize("quantity,total,known,unknown", [(1,None,0,1),(2,None,0,2),(3,300,300,0),(4,None,300,1),(6,600,600,0)])
def test_conditional_bundle_quantity_totals(quantity, total, known, unknown):
    assert quantity_price(bundle(), quantity) == {"total_cents": total, "known_subtotal_cents": known, "unknown_quantity": unknown}


def test_no_single_price_is_invented_or_unconditional_unit_ranking():
    row = offer_for_response(bundle(), False)
    assert row["regular_price"] == 3.0
    assert row["single_price"] is None
    assert row["conditional_unit_price"] == 1.0
    assert row["unit_price"] == ""
    assert row["multi_buy_quantity"] == 3 and row["minimum_quantity"] == 3
    assert offer_from_dict(offer_to_dict(bundle())).multi_buy_total_price == 3.0
    single = replace(bundle(), offer_id="single", retailer="REWE", price=1.19, multi_buy_quantity=None,
                     multi_buy_total_price=None, comparison_eligible=True)
    result = OfferComparator().compare([bundle(), single], (), "best_only")
    assert len(result.offers) == 2
    assert all(row.regular_comparison_state == "none" for row in result.offers)


@pytest.mark.parametrize("query", ["Em-eukal", "EmEukal", "Emeukal"])
def test_brand_spelling_does_not_add_competitor_aliases(query):
    competitor = replace(bundle(), name="Ricola", brand="Ricola")
    assert filter_offers([bundle(), competitor], query) == [bundle()]


@pytest.mark.parametrize("store", ["DE5220", "DE1680"])
def test_authentic_konstanz_bundle_parser_and_sales_validity(monkeypatch, store):
    import json
    from datetime import date
    from pathlib import Path
    from supermarkt.sources.kaufland import OfficialKauflandSource
    raw = json.loads((Path(__file__).parent / "fixtures" / "kaufland" / f"{store}-20261015-bundles.json").read_text())
    # The historical minimum-completeness guard needs a full catalogue: repeat
    # unrelated fixture offers with unique IDs, preserving the real tested rows.
    rows = list(raw["offers"])
    baseline = next(row for row in rows if row.get("formattedPrice") and not row.get("bbyMessage"))
    rows.extend({**baseline, "offerId": f"synthetic-completeness-{index}", "klNr": f"padding-{index}"} for index in range(110))
    availability = raw["availability"] + [{"klNr": f"padding-{i}", "dateFrom": "2026-10-12", "dateTo": "2026-10-17"} for i in range(110)]
    payload = {"component": "OfferTemplate", "props": {"offerData": {"cycles": [{"categories": [{"offers": rows}]}]}}}
    class Http:
        def get_bytes(self, url, _headers=None):
            return json.dumps(availability if ".kloffers." in url else payload, separators=(",", ":")).encode()
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026,10,15))
    source = OfficialKauflandSource(Http(), locator=None)
    offers = source._load_structured_offers(f"https://filiale.kaufland.de/service/filiale/test-{store[2:]}.html")
    snack = next(row for row in offers if "ART.882910_" in row.offer_id)
    assert snack.price == 4 and snack.multi_buy_quantity == 4 and snack.multi_buy_total_price == 4
    assert snack.single_price is None and snack.multi_buy_mix_group is None
    assert snack.pack_size == "80g"
    response = offer_for_response(snack, False)
    assert response["unit_price"] == "12,50 €/kg (nur Mehrkauf)"
    assert snack.valid_from == "2026-10-12" and snack.valid_until == "2026-10-17"
    cheese = next(row for row in offers if "ART.734426_" in row.offer_id)
    assert cheese.multi_buy_quantity == 2 and cheese.multi_buy_total_price == 5
    ordinary = next(row for row in offers if "ART.61801_" in row.offer_id)
    assert ordinary.multi_buy_quantity is None  # bonusbuy true alone means no bundle.

    three = next(row for row in offers if "ART.483431_" in row.offer_id)
    assert three.multi_buy_quantity == 3 and three.multi_buy_total_price == 3
    assert quantity_price(three, 4) == {"total_cents": None, "known_subtotal_cents": 300, "unknown_quantity": 1}


def test_next_week_uses_real_preview_and_never_redates_current(monkeypatch):
    import json
    from datetime import date
    from supermarkt.sources.kaufland import OfficialKauflandSource
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 10, 15))
    calls = []
    rows = [{"offerId": "real-next", "klNr": "1", "title": "Preview", "formattedPrice": "3.00",
             "dateFrom": "2026-10-19", "dateTo": "2026-10-21", "salesFrom": "2026-10-20"}]
    availability = [{"klNr": "1", "dateFrom": "2026-10-19", "dateTo": "2026-10-21"}]
    class Http:
        def get_bytes(self, url, _headers=None):
            calls.append(url)
            payload = availability if ".kloffers." in url else {"component":"OfferTemplate", "props":{"offerData":{"cycles":[{"categories":[{"offers":rows}]}]}}}
            return json.dumps(payload, separators=(",", ":")).encode()
    source = OfficialKauflandSource(Http(), locator=None)
    result = source._load_structured_offers("https://filiale.kaufland.de/service/filiale/test-5220.html", "next")
    assert len(result) == 1  # Includes early next week even though the reference day is Thursday.
    assert result[0].valid_from == "2026-10-20" and result[0].valid_until == "2026-10-21"
    assert calls[-1] == source.NEXT_OVERVIEW_URL
    rows[0].update(dateFrom="2026-10-12", dateTo="2026-10-17", salesFrom="2026-10-12")
    assert source._load_structured_offers("https://filiale.kaufland.de/service/filiale/test-5220.html", "next") == []
    # Regional and catalogue ranges must overlap each other, not only the requested week.
    rows[0].update(dateFrom="2026-10-23", dateTo="2026-10-24", salesFrom="2026-10-23")
    assert source._load_structured_offers("https://filiale.kaufland.de/service/filiale/test-5220.html", "next") == []


def test_card_or_coupon_bundle_without_confirmed_selection_has_no_unconditional_total():
    for condition in ("3 Stück mit Kaufland Card", "3 Stück mit aktiviertem Coupon"):
        quote = quantity_price(replace(bundle(),multi_buy_condition=condition),3)
        assert quote["total_cents"] is None and quote["unknown_quantity"] == 3


def test_source_bundle_preserves_card_condition_from_detail_title():
    from supermarkt.sources.kaufland import OfficialKauflandSource
    fields=OfficialKauflandSource._multi_buy_fields({"bbyMessage":["3 Stück"],"detailTitle":"Mit Kaufland Card"},3.0,"75g")
    assert "Mit Kaufland Card" in fields["multi_buy_condition"]
