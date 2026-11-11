"""Public response regression and fallback mapping contracts, not live completeness."""
import copy
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from supermarkt.common import deduplicate_offers, filter_offers, supplement_offers
from supermarkt.compare import OfferMapper
from supermarkt.models import RETAILER_SPECS, ToolError
from supermarkt.service import SourceLoader
from supermarkt.sources.kaufda import KaufdaRetailerSource
from supermarkt.sources.marktguru import MarktguruClient

FIXTURES = Path(__file__).parent / "fixtures/offer_coverage"
DAY = date(2026, 11, 9)


def raw_kania():
    return json.loads((FIXTURES / "marktguru_kania.json").read_text())


def kania():
    return OfferMapper().map_one(raw_kania(), SourceLoader._contexts(), DAY)


def viewer():
    return json.loads((FIXTURES / "kaufda_kania.json").read_text())


def secondary(data=None, day=DAY):
    return KaufdaRetailerSource(None, "Lidl", "Lidl", "Lidl").parse_viewer(data or viewer(), "2501324792", day)


def test_observed_kania_price_pack_and_local_calendar():
    offer = kania()
    assert (offer.name, offer.price, offer.pack_signature) == ("Kania Wildgerichte", 3.99, "400g")
    assert (offer.valid_from, offer.valid_until) == ("2026-11-09", "2026-11-14")
    assert raw_kania()["validityDates"][0]["from"] == "2026-11-08T23:00:00Z"
    assert offer.description == "Versch. Sorten. Je 400 g"


@pytest.mark.parametrize("query,found", [("Kania", True), ("Wildgerichte", True), ("Wildschwein", False),
    ("Wildschweingulasch", False), ("Wildgulasch", False), ("Hirschgulasch", False), ("Gulasch", False)])
def test_search_only_claims_words_present_in_primary_evidence(query, found):
    assert bool(filter_offers([kania()], query)) is found


def test_filled_primary_is_complemented_without_replacement_or_invented_species():
    primary = [replace(kania(), offer_id=str(i), name=f"Fixture article {i}", match_key=f"fixture:{i}") for i in range(150)]
    extra = secondary()
    combined = supplement_offers(primary, extra)
    assert combined[:150] == primary
    assert len(combined) == 151
    assert filter_offers(combined, "Wildschwein") == extra
    assert filter_offers(combined, "Hirschgulasch") == []
    assert extra[0].price == 3.99 and extra[0].pack_signature == "400g"
    assert "Müller" not in extra[0].coverage_note


def test_exact_identity_deduplicates_but_variants_packs_dates_prices_and_conditions_survive():
    offer = kania()
    duplicate = replace(offer, offer_id="other-source", source_url="https://www.kaufda.de/")
    assert supplement_offers([offer], [duplicate]) == [offer]
    variants = [replace(offer, name="Kania Wildschwein"), replace(offer, pack_signature="800g"),
        replace(offer, description="Andere ausdrücklich benannte Sorte"), replace(offer, price=4.99),
        replace(offer, valid_from="2026-11-12")]
    assert len(supplement_offers([offer], variants)) == 6
    assert len(deduplicate_offers([offer, replace(offer, description="Explizit andere Sorte")])) == 2


@pytest.mark.parametrize("day,count", [(date(2026, 11, 8), 1), (DAY, 1), (date(2026, 11, 14), 1),
    (date(2026, 11, 15), 0), (date(2026, 11, 16), 0)])
def test_sunday_monday_and_expiry(day, count):
    assert len(secondary(day=day)) == count


def test_thursday_preview_and_next_week_are_not_artificially_redated():
    data = viewer()
    validity = data["contents"][0]["offers"][0]["content"]["publicationProfiles"][0]["validity"]
    validity["startDate"] = "2026-11-11T23:00:00.000+0000"
    offer = secondary(data)[0]
    assert offer.valid_from == "2026-11-12"
    validity["startDate"] = "2026-11-15T23:00:00.000+0000"
    validity["endDate"] = "2026-11-21T22:59:00.000+0000"
    assert secondary(data) == []
    assert secondary(data, date(2026, 11, 16))[0].valid_from == "2026-11-16"


@pytest.mark.parametrize("payload", [{}, {"results": {}}, [], {"results": [None]}])
def test_changed_marktguru_schema_is_not_a_successful_empty_catalogue(payload):
    class HTTP:
        def get_json(self, *_args):
            return payload
    with pytest.raises(ToolError, match="Format"):
        MarktguruClient(HTTP(), 100, 1)._fetch_page("04109", "Lidl", 0, {})


@pytest.mark.parametrize("spec", RETAILER_SPECS, ids=lambda s: s.name)
def test_registered_retailer_fallback_mapping_price_pack_date_and_search_contract(spec):
    # Synthetic contract: no claim that this retailer publishes the Kania item.
    raw = copy.deepcopy(raw_kania())
    raw["advertisers"] = [{"name": spec.aliases[0]}]
    offer = OfferMapper().map_one(raw, SourceLoader._contexts(), DAY)
    assert offer is not None and offer.retailer == spec.name
    assert offer.price == 3.99 and offer.pack_signature == "400g"
    assert filter_offers([offer], "Kania") == [offer]
    assert offer.valid_until == "2026-11-14"
    assert OfferMapper().map_one(raw, SourceLoader._contexts(), date(2026, 11, 16)) is None
    raw["price"] = None
    assert OfferMapper().map_one(raw, SourceLoader._contexts(), DAY).price is None


def test_regional_supplement_never_falls_back_to_unverified_national_brochure():
    class HTTP:
        def get_bytes(self, *_args):
            return b'<a href="https://www.kaufda.de/Leipzig/Lidl/p-r74">Lidl</a>'
    source = KaufdaRetailerSource(HTTP(), "Lidl", "Lidl", "Lidl", True)
    with pytest.raises(ToolError, match="Ortslink"):
        source.load_regional("Koeln", DAY)


def test_offline_recovery_keeps_only_still_valid_missing_records_for_failed_retailers(monkeypatch):
    from supermarkt.models import offer_to_dict
    from supermarkt.service import SupermarketEngine
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: DAY)
    old = offer_to_dict(kania())
    old_expired = {**old, "offer_id": "expired", "valid_until": "2026-11-07"}
    fresh_item = {**old, "offer_id": "new", "name": "Different product"}
    previous = {"offers": [old, old_expired]}
    fresh = {"offers": [fresh_item], "incomplete_retailers": ["Lidl"], "request_errors": ["Lidl page timeout"]}
    result = SupermarketEngine.retain_valid_offline_offers(previous, fresh, "current")
    assert [o["offer_id"] for o in result["offers"]] == ["new", old["offer_id"]]
    assert "nicht erneut bestätigt" in result["offers"][-1]["coverage_note"]
    assert result["store_warnings"] and result["request_errors"]
    # Confirmed absence and a successful complete refresh both forbid resurrection.
    assert SupermarketEngine.retain_valid_offline_offers(previous, {**fresh, "unavailable_retailers": ["Lidl"]}, "current")["offers"] == [fresh_item]
    assert SupermarketEngine.retain_valid_offline_offers(previous, {**fresh, "incomplete_retailers": []}, "current")["offers"] == [fresh_item]
    changed_price = {**old, "price": 4.49}
    assert SupermarketEngine.retain_valid_offline_offers(previous, {**fresh, "offers": [changed_price]}, "current")["offers"] == [changed_price]


def test_partial_refresh_preserves_retained_sqlite_evidence_after_freshness_expiry(monkeypatch, tmp_path):
    from supermarkt.models import offer_to_dict
    from test_engine_concurrency import make_engine
    from supermarkt import cache
    now = [1_000_000.0]
    monkeypatch.setattr(cache.time, "time", lambda: now[0])
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: DAY)
    old = offer_to_dict(kania())
    state = {"postal_code": "04109", "offers": [old]}
    engine = make_engine(monkeypatch, tmp_path, lambda *_a, **_k: state.copy())
    engine.snapshot("04109", "auto", retailers=("Lidl",))
    # Weekly caching is irrelevant here: explicitly expire freshness, retain the result.
    with engine.store._connect() as db:
        db.execute("UPDATE supermarket_snapshots SET fresh_until = ?", (now[0] + 1800,))
    now[0] += 31 * 60
    state.update(offers=[], incomplete_retailers=["Lidl"], request_errors=["timeout"])
    result, cached = engine.snapshot("04109", "auto", retailers=("Lidl",))
    assert not cached and result["offers"][0]["offer_id"] == old["offer_id"]
    # Another region/store selection has a different key and must receive no evidence from this one.
    other, _ = engine.snapshot("50939", "auto", retailers=("Lidl",))
    assert other["offers"] == []


@pytest.mark.parametrize("alias", ["Netto mit dem Scottie", "Netto scottie", "Netto schwarz"])
def test_black_netto_is_not_relabelled_as_marken_discount_even_with_a_retailer_filter(alias):
    raw = raw_kania()
    raw["advertisers"] = [{"name": alias}]
    contexts = SourceLoader._contexts()
    assert OfferMapper().map_one(raw, contexts, DAY).retailer == "Netto schwarz"
    assert OfferMapper().map_one(raw, {"Netto Marken-Discount": contexts["Netto Marken-Discount"]}, DAY) is None


@pytest.mark.parametrize("condition", ["Mit Lidl Plus", "mit Kundenkarte", "ab 3 Stück", "mit Gutschein"])
def test_conditional_viewer_price_is_never_reported_as_unconditional(condition):
    data = viewer()
    content = data["contents"][0]["offers"][0]["content"]
    content["deals"][0]["conditions"] = [{"other": condition}]
    offers = secondary(data)
    if condition == "Mit Lidl Plus":
        assert offers[0].price == 4.99  # Explicit REGULAR_PRICE, not a calculated discount.
        assert offers[0].benefits[0].value == 3.99
    else:
        assert offers == []  # Unknown conditions do not establish a normal price.


def test_viewer_preserves_explicit_lidl_plus_benefit_separately_from_regular_price():
    data = viewer()
    content = data["contents"][0]["offers"][0]["content"]
    content["deals"].append({"type": "SALES_PRICE", "min": 2.99, "max": 2.99, "conditions": [{"other": "Mit Lidl Plus"}]})
    offer = secondary(data)[0]
    assert offer.price == 3.99
    assert any(b.program_id == "lidl_plus" and b.value == 2.99 for b in offer.benefits)


@pytest.mark.parametrize("filename,regular,member,pack", [
    ("marktguru_mayonnaise.json", 1.69, 1.29, "500ml"),
    ("marktguru_gulaschsuppe.json", 1.79, 1.39, "400ml"),
])
def test_actual_lidl_plus_response_exposes_both_stated_prices(filename, regular, member, pack):
    raw = json.loads((FIXTURES / filename).read_text())
    offer = OfferMapper().map_one(raw, SourceLoader._contexts(), DAY)
    assert offer.price == regular and offer.pack_signature == pack
    assert any(b.program_id == "lidl_plus" and b.kind == "direct_price" and b.value == member for b in offer.benefits)
    from supermarkt.loyalty import apply_selected_programs
    assert apply_selected_programs(offer, ())[0] == regular
    assert apply_selected_programs(offer, ("lidl_plus",))[0] == member


def test_holab_minimum_quantity_is_not_presented_as_a_single_crate_price():
    from supermarkt.sources.holab import OfficialHolabSource
    from supermarkt.multibuy import quantity_price
    class HTTP:
        def get_bytes(self, url, *_args):
            if "/maerkte" in url:
                return b'<li class="store">26135 <a href="/maerkte/fixture">Fixture</a></li>'
            return (FIXTURES / "holab_selected.html").read_bytes()
    offers = OfficialHolabSource(HTTP()).load("26135")
    assert len(offers) == 5
    alternative = next(o for o in offers if "Hemelinger" in o.name)
    assert alternative.pack_signature == "24x330ml/20x500ml"
    assert alternative.deposit is None and alternative.base_price is None
    assert not alternative.comparison_eligible
    juice = next(o for o in offers if o.name == "Rauch Happy Day")
    assert (juice.price, juice.single_price, juice.multi_buy_quantity, juice.multi_buy_total_price) == (1.99, 1.99, 6, 10.0)
    assert "6er-Karton" in juice.description
    assert quantity_price(juice, 1)["total_cents"] == 199
    assert quantity_price(juice, 6)["total_cents"] == 1000
    assert quantity_price(juice, 7)["total_cents"] == 1199
    water = next(o for o in offers if o.name == "Vilsa Mineralwasser Glas")
    assert water.price == 4.49 and water.minimum_quantity == 2
    assert water.multi_buy_total_price == 8.98 and water.single_price == 4.99
    assert quantity_price(water, 1)["total_cents"] == 499
    assert quantity_price(water, 2)["total_cents"] == 898
    assert water.valid_from == "2026-11-09" and water.valid_until == "2026-11-14"


@pytest.mark.parametrize("replacement", ["6er-Karton 10.00€ nur mit App", "6er-Karton 10.00€ 12er-Karton 18.00€", "1er-Karton 1.00€"])
def test_carton_prices_with_unverified_membership_ambiguous_totals_or_invalid_quantities_are_not_inferred(replacement):
    from supermarkt.sources.holab import OfficialHolabSource
    class HTTP:
        def get_bytes(self, url, *_args):
            if "/maerkte" in url:
                return b'<li class="store">26135 <a href="/maerkte/fixture">Fixture</a></li>'
            return (FIXTURES / "holab_selected.html").read_text().replace("6er-Karton 10.00€", replacement).encode()
    juice = next(o for o in OfficialHolabSource(HTTP()).load("26135") if o.name == "Rauch Happy Day")
    assert juice.price == 1.99 and juice.multi_buy_quantity is None
    assert replacement in juice.description


def test_published_specific_breadcrumb_is_searchable_without_inventing_another_species():
    offers = secondary()
    assert "Quellkategorie: Wildschweingulasch" in offers[0].description
    assert filter_offers(offers, "Wildschweingulasch") == offers
    assert filter_offers(offers, "Gulasch") == offers
    assert filter_offers(offers, "Hirschgulasch") == []
    data = viewer()
    data["contents"][0]["offers"][0]["content"]["products"][0]["categoryPaths"] = [{"name": "Hirschgulasch"}]
    assert filter_offers(secondary(data), "Hirschgulasch") == []


def test_actual_multi_product_viewer_never_assigns_the_cheapest_variant_price_to_all():
    data = json.loads((FIXTURES / "kaufda_variants.json").read_text())
    offers = secondary(data)
    bedding = {o.name: o.price for o in offers if "Bettdecke" in o.name}
    assert bedding == {"Livarno Kochfeste Bettdecke ca. 135 x 200 cm": 11.99, "Livarno Kochfeste Bettdecke ca. 155 x 220 cm": 14.99}
    assert len([o for o in offers if "Backform" in o.name]) == 3
    assert len({o.offer_id for o in offers}) == len(offers)


def test_five_published_berlin_aldi_articles_complement_a_filled_official_catalogue():
    data = json.loads((FIXTURES / "kaufda_aldi_regional.json").read_text())
    extra = KaufdaRetailerSource(None, "ALDI Nord", "ALDI Nord", "Aldi-Nord").parse_viewer(data, "2501318401", DAY)
    expected = {"MÜHLHÄUSER Pflaumenmus": (1.69, "450g"), "Riesa Nudeln": (0.79, "500g"),
        "Viba Nougatspezialität": (2.49, "100g"), "Eberswalder Würstchen XXL": (1.99, "333g"), "Ileburger Ilis Brause": (0.59, "1500ml")}
    assert {o.name: (o.price, o.pack_signature) for o in extra} == expected
    primary = [replace(kania(), retailer="ALDI Nord", name=f"Fixture official {i}", match_key=str(i)) for i in range(173)]
    combined = supplement_offers(primary, extra)
    assert len(combined) == 178 and combined[:173] == primary
    assert all(not o.benefits for o in extra)  # ALDI has no invented app-price program.


@pytest.mark.parametrize("text,expected", [("je 1.000 g", "1000g"), ("1.000-g-Becher", "1000g"),
    ("1.5 l", "1500ml"), ("0.500 l", "500ml"), ("2 x 1.000 g", "2x1000g"), ("1,5 l", "1500ml")])
def test_published_quantity_thousands_separator_is_not_one_gram(text, expected):
    from supermarkt.common import normalize_pack
    assert normalize_pack(text) == expected


def test_explicit_penny_without_app_price_is_separate_from_member_price():
    from supermarkt.loyalty import marktguru_public_prices
    regular, benefits = marktguru_public_prices("MIT PENNY APP 1.79 €; ohne Penny App 2.99 €", 1.79, "PENNY")
    assert regular == 2.99
    assert [(b.program_id, b.value) for b in benefits] == [("penny_app", 1.79)]
    # Another retailer's program is never evidence for this retailer's public price.
    assert marktguru_public_prices("MIT PENNY APP 1.79 €; ohne Lidl Plus 2.99 €", 1.79, "PENNY")[0] == 1.79


@pytest.mark.parametrize("filename,program,member", [("marktguru_moin_contract.json", "moin_card", 1.88),
    ("marktguru_netto_app_contract.json", "netto_plus", 5.99)])
def test_published_loyalty_wording_contract(filename, program, member):
    from supermarkt.loyalty import marktguru_public_prices
    data = json.loads((FIXTURES / filename).read_text())
    regular, benefits = marktguru_public_prices(data["description"], data["price"], data["retailer"])
    assert regular == data["price"]
    assert any(b.program_id == program and b.kind == "direct_price" and b.value == member for b in benefits)


def test_undated_online_recovery_expires_without_extending_original_evidence_age(monkeypatch):
    from supermarkt.service import SupermarketEngine
    import supermarkt.service as service
    now = [1_000_000.0]
    monkeypatch.setattr(service.time, "time", lambda: now[0])
    offer = {"retailer": "Müller", "offer_id": "fixture", "valid_from": None, "valid_until": None}
    previous = {"created_at": now[0], "offers": [offer]}
    fresh = {"offers": [], "incomplete_retailers": ["Müller"]}
    now[0] += 3600
    retained = SupermarketEngine.retain_valid_offline_offers(previous, fresh, "current")
    assert retained["offers"][0]["offline_verified_at"] == 1_000_000.0
    # A retry stores a newer snapshot, but cannot renew missing-product evidence.
    retained["created_at"] = now[0]
    now[0] += 24 * 3600
    assert SupermarketEngine.retain_valid_offline_offers(retained, fresh, "current")["offers"] == []


def test_actual_aktiv_weekend_marker_overrides_only_its_product_start():
    from supermarkt.sources.aktiv_irma import OfficialAktivIrmaSource
    offers = OfficialAktivIrmaSource(None).parse((FIXTURES / "aktiv_selected.html").read_text())
    vegetable = next(o for o in offers if "iglo" in o.name)
    assert (vegetable.valid_from, vegetable.valid_until) == ("2026-11-12", "2026-11-14")
    assert all(o.valid_from == "2026-11-09" for o in offers if o is not vegetable)


def test_broad_game_stew_query_matches_only_a_published_specific_stew_not_an_invented_species():
    extra = secondary()
    assert filter_offers(extra, "Wildgulasch") == extra
    assert filter_offers(extra, "Kania Wildgulasch") == extra
    assert filter_offers(extra, "Wildgulasch Kania") == extra
    assert filter_offers([kania()], "Wildgulasch") == []  # Generic Wildgerichte has no published stew subtype.
    assert filter_offers(extra, "Hirschgulasch") == []
    soup = replace(extra[0], name="Wildschweingulaschsuppe", brand="", description="")
    assert filter_offers([soup], "Wildgulasch") == []


def test_search_word_order_accents_and_punctuation_match_native_search():
    offer = replace(kania(), name="Deluxe Crème Brûlée", brand="Deluxe", description="2 x 100 g")
    assert filter_offers([offer], "brulee deluxe") == [offer]
    assert filter_offers([offer], "creme brulee") == [offer]


@pytest.mark.parametrize("published_location,accepted", [({"lat": 53.1367, "lng": 8.21653}, True),
    ({"lat": 54.294, "lng": 10.886}, False), ({}, False)])
def test_published_city_suffix_requires_its_own_nearby_coordinates(published_location, accepted):
    class Http:
        def __init__(self): self.calls = []
        def get_bytes(self, url, headers=None):
            self.calls.append(url)
            if "/Geschaefte/" in url:
                return b'<a href="/Berlin/Lidl/p-r74">Berlin</a>'  # popular-city list omits Oldenburg
            if "/Oldenburg-Oldb/" in url:
                data = {"props": {"pageProps": {"pageInformation": {"location": published_location,
                    "brochures": {"viewer": [{"id": "2501324792", "publisher": {"name": "Lidl", "type": "RETAILER"}}]}}}}}
                return f'<script id="__NEXT_DATA__">{json.dumps(data)}</script>'.encode()
            return json.dumps(viewer()).encode()
    http = Http()
    source = KaufdaRetailerSource(http, "Lidl", "Lidl", "Lidl", use_viewer=True)
    if accepted:
        result = source.load_regional("Oldenburg", DAY, (53.1367, 8.21653))
        assert result and "/Oldenburg-Oldb/" in result[0].source_url
    else:
        with pytest.raises(ToolError, match="Ortsnachweis"):
            source.load_regional("Oldenburg", DAY, (53.1367, 8.21653))
        assert not any("/pages?" in url for url in http.calls)


@pytest.mark.parametrize("published,pack", [
    ("12 x 0,7 Ltr. (1 Ltr. = 0,53)", "12x700ml"),
    ("50 Stück (10 Stück = 3,79 €)", "50stk"),
    ("20 WL (1 WL = 0,25 €)", "20portion"),
    ("250 ml 23,96 € / 1 Ltr.", "250ml"),
])
def test_public_quantity_reference_units_are_not_additional_packages(published, pack):
    from supermarkt.common import normalize_pack
    assert normalize_pack(published) == pack


def test_current_publisher_brochure_is_not_hidden_by_next_week_viewer():
    payload = json.loads((FIXTURES / "kaufda_week_selection.json").read_text())
    page = f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'
    source = KaufdaRetailerSource(None, "Lidl", "Lidl", "Lidl", use_viewer=True)
    assert source._brochure_ids(page, True, date(2026, 11, 10)) == ["2501324792"]
    assert source._brochure_ids(page, True, date(2026, 11, 16)) == ["2501324813"]
    # Earlier publication of the preview never makes its future validity current.
    payload['props']['pageProps']['pageInformation']['brochures']['publisher'] = []
    page = f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'
    assert source._brochure_ids(page, True, date(2026, 11, 10)) == []


def test_actual_next_week_dessert_is_not_imported_as_current_week():
    raw = json.loads((FIXTURES / "kaufda_lidl_next_week.json").read_text())
    source = KaufdaRetailerSource(None, "Lidl", "Lidl", "Lidl", use_viewer=True)
    assert source.parse_viewer(raw, "2501324813", date(2026, 11, 10)) == []
    offer, = source.parse_viewer(raw, "2501324813", date(2026, 11, 16))
    assert (offer.price, offer.benefits[0].value, offer.pack_signature) == (2.49, 1.99, "125g")
    assert (offer.valid_from, offer.valid_until) == ("2026-11-16", "2026-11-21")
