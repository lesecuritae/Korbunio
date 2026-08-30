import json

import pytest

from supermarkt.models import ToolError
from supermarkt.sources.globus import GlobusMarket, GlobusMarketResolver, OfficialGlobusSource, _price


MARKET = GlobusMarket("1044", "wib", "Wiesbaden", "65203", 50.04, 8.24, "https://www.globus.de/wiesbaden/")


class FakeHttp:
    def __init__(self, markets=None, coordinates=(50.04, 8.24), flyer=None):
        self.markets = markets or {}
        self.coordinates = coordinates
        self.flyer = flyer or {"pages": []}
        self.post_calls = 0
        self.get_calls = []

    def post_form_json(self, url, fields):
        self.post_calls += 1
        assert fields == {"type": "maerkte"}
        return {"success": True, "data": self.markets}

    def get_bytes(self, url, headers=None):
        self.get_calls.append(url)
        lat, lon = self.coordinates
        return json.dumps([{"lat": str(lat), "lon": str(lon)}]).encode()

    def get_json(self, url, headers=None):
        self.get_calls.append(url)
        return self.flyer


def market_payload(market_id="1044", code="WIB", postal="65203", lat=50.04, lon=8.24):
    return {market_id: {"betriebsstaette": "SBW", "marktNummer": int(market_id), "marktNameKurz": code,
        "marktName": "Wiesbaden", "plz": postal, "breitengrad": lat, "laengengrad": lon,
        "marktUrl": "https://www.globus.de/wiesbaden/index.php"}}


def article(**overrides):
    value = {"article_id": "4711", "title": "Käse &amp; Brot", "subtitle": "1 kg = 7,98", "menge": "500 g",
        "price": "3,99 €", "begin": "2026-08-24", "end": "2026-08-29"}
    value.update(overrides)
    return value


def test_market_resolution_exact_postal_separates_id_and_code_and_caches():
    http = FakeHttp(markets=market_payload())
    resolver = GlobusMarketResolver(http)
    first = resolver.resolve("65203")
    second = resolver.resolve("65203")
    assert first == second
    assert (first.market_id, first.code) == ("1044", "wib")
    assert http.post_calls == 1
    assert http.get_calls == []


def test_market_resolution_uses_nearest_coordinates_not_arbitrary_region():
    markets = market_payload("1044", "WIB", "65203", 50.04, 8.24)
    markets.update(market_payload("1099", "FAR", "99999", 53.0, 13.0))
    resolved = GlobusMarketResolver(FakeHttp(markets=markets, coordinates=(50.05, 8.25))).resolve("65185")
    assert resolved.market_id == "1044"


def test_market_resolution_rejects_out_of_range_postal_code():
    resolver = GlobusMarketResolver(FakeHttp(markets=market_payload(), coordinates=(54.9, 14.0)))
    assert resolver.resolve("99998") is None


def test_parser_entities_prices_base_price_dates_and_deduplication():
    duplicate = article()
    payload = {"pages": [{"page": 2, "image": "https://example.test/page.jpg", "articles": [article(), duplicate]}]}
    offers = OfficialGlobusSource.parse(payload, MARKET)
    assert len(offers) == 1
    offer = offers[0]
    assert offer.name == "Käse & Brot"
    assert offer.price == 3.99
    assert (offer.base_price, offer.base_unit) == (7.98, "kg")
    assert (offer.valid_from, offer.valid_until) == ("2026-08-24", "2026-08-29")
    assert offer.offer_id.startswith("globus:1044:")
    assert offer.source_category == "Prospektseite 2"


def test_parser_never_uses_flyer_page_as_product_image_and_prefers_article_image():
    payload = {"pages": [{
        "page": 2,
        "image": "https://example.test/flyer/page-2.jpg",
        "zoom-image": "https://example.test/flyer/page-2-zoom.jpg",
        "articles": [
            article(article_id="without-image"),
            article(article_id="with-image", product_image="https://example.test/products/4711.webp"),
        ],
    }]}

    offers = OfficialGlobusSource.parse(payload, MARKET)

    assert [offer.image_url for offer in offers] == ["", "https://example.test/products/4711.webp"]
    assert all("/flyer/" not in offer.image_url for offer in offers)


@pytest.mark.parametrize(("raw", "expected"), [("1,29 €", 1.29), ("12.99 EUR", 12.99), ("ab 2 €", 2.0), ("", None)])
def test_price_formats(raw, expected):
    assert _price(raw) == expected


def test_parser_skips_missing_price_and_derives_base_price_from_quantity():
    payload = {"pages": [{"articles": [article(article_id="1", subtitle="", menge="250 ml", price="1,00 €"), article(article_id="2", price="")]}]}
    offers = OfficialGlobusSource.parse(payload, MARKET)
    assert len(offers) == 1
    assert (offers[0].base_price, offers[0].base_unit) == (4.0, "l")


def test_parser_rejects_changed_structure_and_accepts_empty_flyer():
    with pytest.raises(ToolError): OfficialGlobusSource.parse({"items": []}, MARKET)
    assert OfficialGlobusSource.parse({"pages": []}, MARKET) == []


def test_loader_uses_resolved_market_code():
    class Resolver:
        def resolve(self, postal_code):
            assert postal_code == "65185"
            return MARKET
    http = FakeHttp(flyer={"pages": [{"articles": [article()]}]})
    offers = OfficialGlobusSource(http, Resolver()).load("65185")
    assert len(offers) == 1
    assert http.get_calls == ["https://www.globus.de/faltblatt_online/aktuelle_woche/wib/pageitems.json"]
