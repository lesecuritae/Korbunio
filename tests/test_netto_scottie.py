from datetime import date

from supermarkt.models import LoyaltyBenefit
from supermarkt.sources.netto_scottie import NettoScottieMarketResolver, OfficialNettoScottieSource


HTML = """
<html><body>
<h2>Angebote vom: 24-08-2026 bis 29-08-2026</h2>
<div aria-label="product-0">
  <span>500 g</span>
  <img src="https://media.example/product.webp" alt="">
  <h4>MEINE FLEISCHEREI\nFrisches Schweinehackfleisch</h4>
  <p>500 g\n1 kg = 4.98</p>
  <h3>2<!-- -->.<span>49</span></h3>
</div>
<div aria-label="product-1">
  <span>APP-PREIS</span>
  <h4>Kingsway Kirsch-Banane</h4>
  <p>1 Liter</p>
  <h3>0<!-- -->.<span>59</span></h3>
  <p>Nicht-Mitgliederpreis bis zu 1.29</p>
</div>
</body></html>
"""


class FakeHttp:
    def get_bytes(self, url, headers=None):
        return HTML.encode()


def test_scottie_parser_maps_regular_and_public_app_prices():
    source = OfficialNettoScottieSource(FakeHttp(), market_resolver=lambda _postal: {"name": "Netto Berlin", "address": {"city": "Berlin", "zip": "10115"}})
    offers = source.load("10115")

    assert len(offers) == 2
    assert offers[0].retailer == "Netto schwarz"
    assert offers[0].price == 2.49
    assert offers[0].base_price == 4.98
    assert offers[0].valid_from == date(2026, 8, 24).isoformat()
    assert offers[0].valid_until == date(2026, 8, 29).isoformat()
    assert offers[1].price == 1.29
    assert offers[1].benefits == (
        LoyaltyBenefit("netto_scottie_plus", "direct_price", 0.59, "Netto+ App-Preis"),
    )


def test_scottie_market_selection_prefers_exact_postal_code_and_bounds_nearest_fallback():
    stores = [
        {"id": "near", "distance_km": 1.0, "address": {"zip": "10117"}},
        {"id": "exact-far", "distance_km": 3.0, "address": {"zip": "10115"}},
        {"id": "exact-near", "distance_km": 2.0, "address": {"zip": "10115"}},
    ]
    assert NettoScottieMarketResolver._select_exact(stores, "10115")["id"] == "exact-near"
    assert NettoScottieMarketResolver._select_exact(stores, "93073")["id"] == "near"
    assert NettoScottieMarketResolver._select_exact([{"distance_km": 15.1, "address": {"zip": "93074"}}], "93073") is None


def test_scottie_market_selection_lists_and_honours_the_requested_branch(monkeypatch):
    stores = [
        {"id": "first", "name": "Netto Markt A", "distance_km": 2.0, "address": {"zip": "10115"}},
        {"id": "second", "name": "Netto Markt B", "distance_km": 1.0, "address": {"zip": "10115"}},
    ]
    resolver = NettoScottieMarketResolver(object())
    monkeypatch.setattr(resolver, "_stores", lambda _postal: stores)

    assert [market["market_id"] for market in resolver.markets("10115")] == ["second", "first"]
    assert resolver.resolve("10115", "first")["name"] == "Netto Markt A"


def test_public_flight_store_data_replaces_removed_script_api_key_without_executing_code():
    import json
    stores = [{"id": "fixture-berlin", "name": "Fixture market", "brand": "netto",
               "address": {"zip": "10115", "city": "Berlin", "country": "DE"}, "coordinates": [13.38, 52.53]}]
    flight = "1:" + json.dumps(["$", "component", None, {"stores": stores}]) + "\n"
    html = '<script>self.__next_f.push(' + json.dumps([1, flight]) + ')</script>'
    assert NettoScottieMarketResolver.embedded_stores(html) == stores
    assert NettoScottieMarketResolver.embedded_stores("<script>throw new Error('not executed')</script>") == []
    class Http:
        def get_bytes(self, url, headers=None):
            if "nominatim" in url:
                return b'[{"lat":"52.53","lon":"13.38"}]'
            assert url == NettoScottieMarketResolver.SEARCH_URL
            return html.encode()
    resolver = NettoScottieMarketResolver(Http())
    selected = resolver.resolve("10115")
    assert selected["id"] == "fixture-berlin" and selected["distance_km"] == 0
    assert resolver.resolve("80331") is not None  # The stub coordinates deliberately remain Berlin.


def test_unknown_flight_format_cannot_be_reported_as_confirmed_market_absence():
    import pytest
    from supermarkt.models import ToolError
    class Http:
        def get_bytes(self, url, headers=None):
            return b'[{"lat":"52.53","lon":"13.38"}]' if "nominatim" in url else b'<html>changed</html>'
    with pytest.raises(ToolError, match="Zugriffskonfiguration"):
        NettoScottieMarketResolver(Http()).resolve("10115")
