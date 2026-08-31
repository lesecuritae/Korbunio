from datetime import date

from supermarkt.common import build_match_key, clean_brand, date_is_current, format_pack, normalize_pack, offer_reference_date, offer_validity, parse_base_price_text, parse_number, validate_postal_code


def test_postal_code_is_required_shape():
    assert validate_postal_code("01067") == "01067"
    assert validate_postal_code("1067") is None
    assert validate_postal_code("") is None


def test_deposit_is_parsed_only_when_explicitly_published():
    from supermarkt.common import parse_deposit_text

    assert parse_deposit_text("je 0,33-l-Dose zzgl. 0.25 Pfand") == 0.25
    assert parse_deposit_text("12 x 0,75 l + 3,30 € Pfand/Kiste") == 3.3
    assert parse_deposit_text("Pfand je 0,15 €") == 0.15
    assert parse_deposit_text("Energy Drink in der Dose") is None


def test_deposit_accepts_leading_euro_sign_but_rejects_ambiguous_variants():
    from supermarkt.common import parse_deposit_text

    assert parse_deposit_text("je 1,25 l Flasche zzgl. € 0.25 Pfand") == 0.25
    assert parse_deposit_text("500 g Glas zzgl. € 0.15 Pfand") == 0.15
    assert parse_deposit_text("je Packung = 6 x 0,33 l zzgl. € 1.50 Pfand") == 1.5
    assert parse_deposit_text(
        "20 x 0,5 l / 24 x 0,33 l zzgl. € 3.10 / € 3.42 Pfand"
    ) is None


def test_crate_deposit_adds_bottles_and_returnable_crate():
    from supermarkt.common import parse_deposit_components, parse_deposit_text

    assert parse_deposit_text(
        "24 x 0,5-l-Flasche; Flaschenpfand je 0,08 €; Kastenpfand 1,50 €",
        container_count=24,
    ) == 3.42
    assert parse_deposit_components(
        "24 x 0,5-l-Flasche; Flaschenpfand je 0,08 €; Kastenpfand 1,50 €",
        container_count=24,
    ) == (3.42, 0.08, 1.50)


def test_multipack_and_single_container_deposits_are_not_double_counted():
    from supermarkt.common import parse_deposit_components, parse_deposit_text

    assert parse_deposit_text("6 x 0,33 l; zzgl. 0,25 € Pfand", container_count=6) == 1.50
    assert parse_deposit_text("0,5-l-Flasche; Pfand je 0,08 €") == 0.08
    assert parse_deposit_text("Mehrwegflasche; Pfand 0,15 €") == 0.15
    assert parse_deposit_text("12 x 0,75 l + 3,30 € Pfand/Kiste", container_count=12) == 3.30
    assert parse_deposit_components(
        "18 x 0,33 l; zzgl. Pfand 0,25", container_count=18,
    ) == (4.50, 0.25, None)


def test_black_cat_marktguru_deposit_notation_is_preserved():
    from supermarkt.common import parse_deposit_text

    assert parse_deposit_text("BLACK CAT Energy Drink 4 x 0,25 Liter zzgl. Pfand 1.–") == 1.0


def test_number_and_base_price():
    assert parse_number("1,99 €") == 1.99
    assert parse_base_price_text("1 kg = 3,98") == (3.98, "kg")


def test_pack_normalization_does_not_need_location():
    assert "500g" in normalize_pack("Produkt 500 g")
    assert build_match_key("Marke", "Produkt", "500g", "fallback")


def test_marktguru_current_image_metadata_gets_cdn_url():
    from supermarkt.common import extract_image_url

    payload = {
        "id": 24174643,
        "images": {"count": 1, "metadata": [{"aspectRatio": 1.0}]},
        "imageType": "offer",
    }
    assert extract_image_url(payload) == (
        "https://mg2de.b-cdn.net/api/v1/offers/24174643/images/default/0/medium.jpg"
    )


def test_marktguru_explicit_image_url_wins_over_cdn_fallback():
    from supermarkt.common import extract_image_url

    payload = {
        "id": 24174643,
        "images": {
            "count": 1,
            "urls": {"large": "https://cdn.example.org/real.jpg"},
        },
        "imageType": "offer",
    }
    assert extract_image_url(payload) == "https://cdn.example.org/real.jpg"


def test_reference_price_is_not_a_second_pack_size():
    assert normalize_pack("FELDSCHLÖSSCHEN 0,33-l-Dose (1 l = 1.19)") == "330ml"
    assert normalize_pack("Senf 200-ml-Becher (1 l = 1,95 €)") == "200ml"
    assert normalize_pack("Milch-Quark 150-g-Becher (1 kg = 3.27)") == "150g"
    assert normalize_pack("Cola 10 x 0,33-l-Dose (1 l = 1.69)") == "10x330ml"


def test_pack_display_keeps_reference_unit_out_of_package_size():
    from supermarkt.common import format_pack

    pack = normalize_pack("FELDSCHLÖSSCHEN 0,33-l-Dose (1 l = 1.19)")
    assert pack == "330ml"
    assert format_pack(pack) == "330 ml"



def test_brand_placeholders_are_not_displayed_as_real_brands():
    assert clean_brand("This is no brand") == ""
    assert clean_brand("ThisIsNoBrand") == ""
    assert clean_brand("thisisnobrand123") == ""
    assert clean_brand("NO BRAND") == ""
    assert clean_brand("ohne Marke") == ""
    assert clean_brand("Ehrmann") == "Ehrmann"


def test_alternative_pack_sizes_are_not_added_together():
    pack = normalize_pack("Pufuleti verschiedene Sorten, je 85 g oder 100 g")
    assert pack == "85g/100g"
    assert format_pack(pack) == "85 g / 100 g"


def test_real_combination_pack_keeps_plus_separator():
    pack = normalize_pack("Kombipack 100 g + 50 g")
    assert pack == "100g+50g"
    assert format_pack(pack) == "100 g + 50 g"


def test_pack_range_stays_ambiguous_for_unit_price_calculation():
    pack = normalize_pack("verschiedene Sorten 85-100 g")
    assert pack == "85-100g"
    assert format_pack(pack) == "85–100 g"

def test_sunday_uses_next_monday_as_weekly_offer_reference():
    sunday = date(2026, 8, 9)
    monday = date(2026, 8, 10)
    assert offer_reference_date(sunday) == monday
    assert not date_is_current(date(2026, 8, 3), date(2026, 8, 8), sunday)
    assert date_is_current(monday, date(2026, 8, 15), sunday)


def test_marktguru_sunday_selects_upcoming_week():
    old_week = {"validityDates": [{"from": "2026-08-03", "to": "2026-08-08"}]}
    next_week = {"validityDates": [{"from": "2026-08-10", "to": "2026-08-15"}]}
    old_current, _ = offer_validity(old_week, date(2026, 8, 9))
    next_current, label = offer_validity(next_week, date(2026, 8, 9))
    assert old_current is False
    assert next_current is True
    assert label == "10.08.–15.08.2026"


def test_explicit_next_week_advances_offer_reference_by_seven_days():
    from supermarkt.common import offer_week_reference

    assert offer_week_reference("current", date(2026, 8, 10)) == date(2026, 8, 10)
    assert offer_week_reference("next", date(2026, 8, 10)) == date(2026, 8, 17)


def test_monday_switches_to_new_week_normally():
    monday = date(2026, 8, 10)
    assert offer_reference_date(monday) == monday
    assert not date_is_current(date(2026, 8, 3), date(2026, 8, 8), monday)
    assert date_is_current(monday, date(2026, 8, 15), monday)


def test_marktguru_placeholder_brand_is_not_prefixed_to_product_name(monkeypatch):
    from datetime import date
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 12))
    from supermarkt.compare import OfferMapper
    from supermarkt.models import RetailerContext

    contexts = {
        "Netto": RetailerContext(
            name="Netto",
            aliases=("netto",),
            excluded_aliases=(),
            color="#000",
            market_label="Netto",
            market_url="https://example.invalid/netto",
        )
    }
    raw = {
        "id": 1,
        "advertisers": [{"name": "Netto"}],
        "product": {"name": "Quarki Kefir", "description": "mild 500 g gekühlt"},
        "brand": {"name": "This is no brand"},
        "price": 0.99,
        "validityDates": [{"from": "2026-08-10", "to": "2026-08-15"}],
    }
    offer = OfferMapper().map_one(raw, contexts)
    assert offer is not None
    assert offer.name == "Quarki Kefir"
    assert offer.brand == ""


def test_marktguru_numbered_placeholder_brand_is_not_prefixed_to_product_name(monkeypatch):
    from datetime import date
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 12))
    from supermarkt.compare import OfferMapper
    from supermarkt.models import RetailerContext

    contexts = {
        "Lidl": RetailerContext(
            name="Lidl",
            aliases=("lidl",),
            excluded_aliases=(),
            color="#000",
            market_label="Lidl",
            market_url="https://example.invalid/lidl",
        )
    }
    raw = {
        "id": 2,
        "advertisers": [{"name": "Lidl"}],
        "product": {"name": "Lauchzwiebeln", "description": "Deutsche Klasse I je Bund"},
        "brand": {"name": "thisisnobrand123"},
        "price": 0.49,
        "validityDates": [{"from": "2026-08-10", "to": "2026-08-15"}],
    }
    offer = OfferMapper().map_one(raw, contexts)
    assert offer is not None
    assert offer.name == "Lauchzwiebeln"
    assert offer.source_url == "https://www.marktguru.de/r/lidl"
    assert offer.brand == ""
