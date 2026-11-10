"""Real first-party market markup, including prices omitted by the legacy API."""
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from supermarkt.common import deduplicate_offers, normalize_pack
from supermarkt.models import ToolError, offer_from_dict, offer_to_dict
from supermarkt.sources.edeka import OfficialEdekaSource
from supermarkt.sources.edeka_html import parse_market_offers

HTML = (Path(__file__).parent / "fixtures/offer_coverage/edeka_romano_offers.html").read_text()
URL = "https://www.edeka.de/maerkte/070696/angebote/"
DAY = date(2026, 11, 10)


def parse(html=HTML, target=DAY):
    return parse_market_offers(html, URL, "EDEKA", "12145", target)


def test_real_market_markup_preserves_published_checkout_and_app_prices_and_expiry():
    offers = parse()
    assert len(offers) == 9
    assert all(o.valid_from == "2026-11-09" and o.valid_until == "2026-11-14" for o in offers)
    butter = next(o for o in offers if o.name == "Meggle Feine Butter oder Streichzart")
    assert (butter.price, butter.pack_signature) == (1.29, "250g")
    assert [(b.program_id, b.value) for b in butter.benefits] == [("edeka_app", 1.11)]
    chocolate = next(o for o in offers if o.name == "Ritter Sport Bunte Vielfalt")
    assert (chocolate.price, chocolate.pack_signature, chocolate.benefits[0].value) == (1.11, "100g", .88)
    redbull = next(o for o in offers if "Red Bull" in o.name)
    assert redbull.price == .99 and redbull.deposit == .25 and not redbull.benefits
    assert parse(target=date(2026, 11, 16)) == []


def test_equal_coffee_titles_do_not_merge_distinct_source_proven_gtins():
    coffee = [o for o in parse() if o.name == "Jacobs Krönung"]
    assert len(coffee) == 2
    assert {o.product_gtins for o in coffee} == {("4000508059087",), ("8711000708651",)}
    # Even if text fields become equal, GTIN remains distinct identity evidence.
    same_text = [replace(o, description="Fixture identical description") for o in coffee]
    assert len(deduplicate_offers(same_text)) == 2
    assert offer_from_dict(json.loads(json.dumps(offer_to_dict(coffee[0])))).product_gtins == coffee[0].product_gtins


@pytest.mark.parametrize("bad", [HTML.replace("Gültig vom", "Unbekannter Zeitraum"),
    HTML.replace("Festpreis von", "Unbekannter Preis"),
    HTML.replace("09.11.2026", "31.11.2026")])
def test_schema_or_price_changes_are_errors_not_a_successful_empty_catalogue(bad):
    with pytest.raises(ToolError):
        parse(bad)


def test_modern_reader_uses_only_the_selected_markets_unique_offers_link():
    class Session:
        def __init__(self): self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(url)
            return SimpleNamespace(status_code=200, text=HTML if url == URL else
                '<a href="/maerkte/070696/angebote/">Angebote</a><a href="/maerkte/070696/angebote">Angebote</a>')
    session = Session()
    offers = OfficialEdekaSource()._load_public_market(session,
        "https://www.edeka.de/eh/fixture/index.jsp", "12145", "EDEKA", DAY)
    assert len(offers) == 9 and session.calls[-1] == URL
    assert OfficialEdekaSource()._load_public_market(session,"https://unrelated.example/", "x", "EDEKA", DAY) is None


def test_reverse_base_price_is_not_an_additional_package():
    assert normalize_pack("250 ml 23,96 € /1 l") == "250ml"
    assert normalize_pack("500 g (€ 3.98 / 1 kg)") == "500g"


def test_actual_loose_produce_bundle_keeps_single_and_group_checkout_totals():
    from supermarkt.multibuy import quantity_price
    avocado = next(o for o in parse() if o.name == "Avocados")
    assert avocado.price == .75 and avocado.minimum_quantity == 4
    assert avocado.multi_buy_total_price == 3.0 and avocado.single_price == .99
    assert quantity_price(avocado, 1)["total_cents"] == 99
    assert quantity_price(avocado, 4)["total_cents"] == 300
    assert quantity_price(avocado, 6)["total_cents"] == 498


def test_current_markup_preserves_unambiguous_legacy_ids_but_not_an_ambiguous_variant_binding():
    modern = next(o for o in parse() if o.name == "Ritter Sport Bunte Vielfalt")
    legacy = replace(modern, offer_id="edeka:12145:legacy", benefits=(), product_gtins=())
    upgraded = OfficialEdekaSource.preserve_offer_ids([legacy], [modern])
    assert upgraded[0].offer_id == legacy.offer_id and upgraded[0].benefits == modern.benefits
    other_gtin = replace(modern, offer_id="new-variant", product_gtins=("12345678",))
    ambiguous = OfficialEdekaSource.preserve_offer_ids([legacy], [modern, other_gtin])
    assert {o.offer_id for o in ambiguous} == {modern.offer_id, "new-variant"}


def test_explicit_dm_piece_quantity_is_not_dropped():
    assert normalize_pack("Seifendose, 1 St") == "1stk"
