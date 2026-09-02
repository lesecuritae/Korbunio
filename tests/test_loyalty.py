from datetime import UTC, datetime, timedelta

import pytest
from supermarkt.compare import OfferComparator, OfferMapper
from supermarkt.loyalty import PROGRAM_BY_ID, apply_selected_programs, available_programs
from supermarkt.models import LoyaltyBenefit, Offer
from supermarkt.service import SourceLoader


def offer(*benefits):
    return Offer(
        offer_id="x", retailer="Kaufland", category="Test", name="Produkt", brand="",
        description="", price=2.29, base_price=None, base_unit="", pack_signature="500g",
        validity_label="Aktuell", match_key="produkt|500g", source_url="https://example.org/",
        benefits=tuple(benefits),
    )


def test_multiple_programs_can_be_selected_together():
    item = Offer(
        offer_id="x", retailer="EDEKA", category="Test", name="Produkt", brand="",
        description="", price=2.00, base_price=None, base_unit="", pack_signature="500g",
        validity_label="Aktuell", match_key="produkt|500g", source_url="https://example.org/",
        benefits=(
            LoyaltyBenefit("edeka_app", "direct_price", 1.80, "EDEKA App"),
            LoyaltyBenefit("payback", "cashback", 0.10, "PAYBACK"),
        ),
    )
    checkout, effective, savings, applied = apply_selected_programs(item, ("edeka_app", "payback"))
    assert checkout == 1.80
    assert effective == 1.80
    assert savings == pytest.approx(0.20)
    assert {benefit.program_id for benefit in applied} == {"edeka_app", "payback"}


def test_kaufland_xtra_changes_effective_price_only_when_selected():
    item = offer(LoyaltyBenefit("kaufland_xtra", "direct_price", 1.79, "Kaufland Card XTRA"))
    assert apply_selected_programs(item, ())[1] == 2.29
    assert apply_selected_programs(item, ("kaufland_xtra",))[1] == 1.79


def test_marktguru_app_price_is_bound_to_retailer_program():
    contexts = SourceLoader._contexts()
    now = datetime.now(UTC)
    raw = {
        "id": 1,
        "advertisers": [{"name": "Lidl"}],
        "product": {"name": "Testprodukt"},
        "description": "App-Preis 1,49",
        "price": 1.99,
        "validityDates": [{"from": (now - timedelta(days=1)).isoformat(), "to": (now + timedelta(days=1)).isoformat()}],
    }
    mapped = OfferMapper().map_one(raw, {"Lidl": contexts["Lidl"]})
    assert mapped is not None
    assert mapped.benefits == (LoyaltyBenefit("lidl_plus", "direct_price", 1.49, "App-Preis"),)


def test_program_registry_covers_supported_retailers_and_aldi_has_no_price_program():
    counts = {
        "REWE": 1, "Lidl": 1, "PENNY": 1, "Netto Marken-Discount": 1, "Kaufland": 1,
        "EDEKA": 1, "Marktkauf": 1, "Globus": 1, "ALDI Nord": 1, "ALDI Süd": 1,
    }
    ids = {item["id"] for item in available_programs(counts)}
    assert {
        "rewe_bonus", "lidl_plus", "penny_app", "netto_plus", "kaufland_xtra",
        "edeka_app", "marktkauf_app", "mein_globus", "payback",
    } <= ids
    assert not any("ALDI" in retailer for program in PROGRAM_BY_ID.values() for retailer in program.retailers)


def test_two_netto_companies_have_separate_loyalty_programs():
    counts = {"Netto Marken-Discount": 1, "Netto schwarz": 1}
    programs = {item["id"]: item for item in available_programs(counts)}

    assert programs["netto_plus"]["retailers"] == ("Netto Marken-Discount",)
    assert programs["netto_scottie_plus"]["retailers"] == ("Netto schwarz",)


def test_scottie_app_price_does_not_activate_marken_discount_program():
    from supermarkt.loyalty import parse_public_loyalty_prices

    benefits = parse_public_loyalty_prices("APP-PREIS 1,29", 1.79, "Netto schwarz")
    assert benefits == (
        LoyaltyBenefit("netto_scottie_plus", "direct_price", 1.29, "APP-PREIS"),
    )


def test_public_member_price_without_regular_price_is_not_relabelled():
    item = Offer(
        offer_id="s", retailer="Netto schwarz", category="Test", name="Mandarinen",
        brand="", description="", price=None, base_price=None, base_unit="",
        pack_signature="750g", validity_label="Aktuell", match_key="mandarinen|750g",
        source_url="https://netto.de/angebote/",
        benefits=(LoyaltyBenefit("netto_scottie_plus", "direct_price", 1.79, "Netto+ App-Preis"),),
    )

    assert apply_selected_programs(item, ())[0] is None
    assert apply_selected_programs(item, ("netto_scottie_plus",))[:3] == (1.79, 1.79, 0.0)


def test_netto_marken_discount_credit_is_not_a_direct_price():
    from supermarkt.loyalty import parse_public_loyalty_prices

    benefits = parse_public_loyalty_prices("2,49 € und 0,50 € Netto plus Vorteil", 2.49, "Netto Marken-Discount")
    assert benefits == (
        LoyaltyBenefit("netto_plus", "cashback", 0.50, "0,50 € Netto plus Vorteil"),
    )


def test_comparator_uses_selected_programs_for_winner():
    a = offer(LoyaltyBenefit("kaufland_xtra", "direct_price", 1.79, "Kaufland Card XTRA"))
    b = Offer(
        offer_id="b", retailer="Lidl", category="Test", name="Produkt", brand="", description="",
        price=1.99, base_price=None, base_unit="", pack_signature="500g", validity_label="Aktuell",
        match_key="produkt|500g", source_url="https://example.org/",
    )
    without = OfferComparator().compare([a, b], (), "all")
    with_xtra = OfferComparator().compare([a, b], ("kaufland_xtra",), "all")
    lidl_without = next(item for item in without.offers if item.retailer == "Lidl")
    kaufland_with = next(item for item in with_xtra.offers if item.retailer == "Kaufland")
    assert lidl_without.regular_comparison_state == "best"
    assert lidl_without.selected_comparison_state == "best"
    assert kaufland_with.regular_comparison_state == "expensive"
    assert kaufland_with.selected_comparison_state == "best"


def test_best_only_keeps_winner_without_bonus_and_winner_with_selection():
    kaufland = offer(
        LoyaltyBenefit(
            "kaufland_xtra",
            "direct_price",
            1.79,
            "Kaufland Card XTRA",
        )
    )
    lidl = Offer(
        offer_id="b",
        retailer="Lidl",
        category="Test",
        name="Produkt",
        brand="",
        description="",
        price=1.99,
        base_price=None,
        base_unit="",
        pack_signature="500g",
        validity_label="Aktuell",
        match_key="produkt|500g",
        source_url="https://example.org/",
    )

    result = OfferComparator().compare(
        [kaufland, lidl],
        ("kaufland_xtra",),
        "best_only",
    )

    assert {item.retailer for item in result.offers} == {"Kaufland", "Lidl"}
    assert result.hidden_count == 0


def test_generic_public_prices_map_to_edeka_and_marktkauf_apps():
    from supermarkt.loyalty import parse_public_loyalty_prices

    edeka = parse_public_loyalty_prices("EDEKA App-Preis 1,49", 1.99, "EDEKA")
    marktkauf = parse_public_loyalty_prices("MARKTKAUF App-Preis 2,49", 2.99, "Marktkauf")
    assert edeka == (LoyaltyBenefit("edeka_app", "direct_price", 1.49, "EDEKA App-Preis"),)
    assert marktkauf == (LoyaltyBenefit("marktkauf_app", "direct_price", 2.49, "MARKTKAUF App-Preis"),)


def test_payback_is_not_confused_with_retailer_app():
    from supermarkt.loyalty import parse_public_loyalty_prices

    benefit = parse_public_loyalty_prices("PAYBACK Preis 1,79", 1.99, "EDEKA")
    assert benefit == (LoyaltyBenefit("payback", "direct_price", 1.79, "PAYBACK Preis"),)


def test_regular_and_selected_unit_prices_are_kept_separate():
    from supermarkt.presentation import offer_for_response

    item = Offer(
        offer_id="u",
        retailer="REWE",
        category="Test",
        name="Joghurt",
        brand="",
        description="500 g",
        price=2.00,
        base_price=4.00,
        base_unit="kg",
        pack_signature="500g",
        validity_label="Aktuell",
        match_key="joghurt|500g",
        source_url="https://example.org/",
        benefits=(LoyaltyBenefit("rewe_bonus", "cashback", 0.20, "REWE Bonus"),),
    )
    compared = OfferComparator().compare([item], ("rewe_bonus",), "all").offers[0]
    response = offer_for_response(compared, include_image_urls=False)

    assert response["unit_price"] == "4,00 €/kg"
    assert response["selected_unit_price"] == ""
    assert response["checkout_price_text"] == "2,00 €"
    assert response["effective_price_text"] == "2,00 €"
    assert response["cashback_credit_text"] == "0,20 €"


def test_rewe_bonus_cashback_is_credit_not_a_reduced_product_price():
    from supermarkt.presentation import offer_for_response

    item = Offer(
        offer_id="rewe-cashback",
        retailer="REWE",
        category="Test",
        name="Joghurt",
        brand="",
        description="500 g",
        price=2.99,
        base_price=5.98,
        base_unit="kg",
        pack_signature="500g",
        validity_label="Aktuell",
        match_key="joghurt|500g",
        source_url="https://www.rewe.de/",
        benefits=(LoyaltyBenefit("rewe_bonus", "cashback", 0.50, "REWE Bonus"),),
    )

    compared = OfferComparator().compare([item], ("rewe_bonus",), "all").offers[0]
    response = offer_for_response(compared, include_image_urls=False)

    assert response["checkout_price"] == 2.99
    assert response["effective_price"] == 2.99
    assert response["loyalty_savings"] == 0.0
    assert response["cashback_credit"] == 0.50
    assert response["cashback_credit_text"] == "0,50 €"
    assert response["loyalty_benefit"] == "REWE Bonus: 0,50 € Guthaben"
