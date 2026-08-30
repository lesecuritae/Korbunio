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
