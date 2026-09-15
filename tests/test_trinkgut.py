from datetime import date
from pathlib import Path
from types import SimpleNamespace
from bs4 import BeautifulSoup
import pytest

from supermarkt.models import Offer, ToolError
from supermarkt.sources.trinkgut import OfficialTrinkgutSource


SAMPLE_MARKETS = [
    {
        "id": "market-1",
        "name": "Endt",
        "street": "Mülforter Str. 49",
        "zipCode": "41238",
        "city": "Mönchengladbach",
        "latitude": 51.15301,
        "longitude": 6.49525,
        "detailURL": "https://www.trinkgut.de/markt/endt",
    },
    {
        "id": "market-2",
        "name": "Friedrichstadt",
        "street": "Am Wehrhahn 1",
        "zipCode": "40223",
        "city": "Düsseldorf",
        "latitude": 51.2150,
        "longitude": 6.7850,
        "detailURL": "https://www.trinkgut.de/markt/duesseldorf-friedrichstadt",
    },
    {
        "id": "market-3",
        "name": "Isermann",
        "street": "Celler Str. 10",
        "zipCode": "29221",
        "city": "Celle",
        "latitude": 52.6250,
        "longitude": 10.0800,
        "detailURL": "https://www.trinkgut.de/markt/isermann",
    },
]


def test_trinkgut_exact_postal_code_match(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)

    _session, m_id, url, label, dist = source._find_market("41238", use_cache=False)
    assert m_id == "market-1"
    assert url == "https://www.trinkgut.de/markt/endt"
    assert "Endt" in label
    assert dist == 0.0
    assert "exakt" in source.last_discovery


def test_trinkgut_nearest_market_selected_when_no_exact_match(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)

    # 40213 has no exact market. Coordinates: Düsseldorf center (51.2217, 6.7762)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: (51.2217, 6.7762))

    _session, m_id, url, label, dist = source._find_market("40213", use_cache=False)
    # Nearest is Düsseldorf Friedrichstadt (market-2) ~ 1 km away
    assert m_id == "market-2"
    assert url == "https://www.trinkgut.de/markt/duesseldorf-friedrichstadt"
    assert "Friedrichstadt" in label
    assert dist is not None
    assert dist < 5.0
    assert "Nächstsuche" in source.last_discovery


def test_trinkgut_fallback_numeric_zip_when_geocoding_fails(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: None)

    # 41239 is closest numerically to 41238 (difference 1)
    _session, m_id, url, label, dist = source._find_market("41239", use_cache=False)
    assert m_id == "market-1"
    assert "Endt" in label
    assert "PLZ-Annäherung" in source.last_discovery


def test_trinkgut_manual_market_id_selection(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)

    _session, m_id, url, label, dist = source._find_market("10115", market_id="market-3")
    assert m_id == "market-3"
    assert "Isermann" in label
    assert dist is None
    assert source.last_discovery == "Manuelle Auswahl"


def test_trinkgut_manual_market_id_invalid(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)

    with pytest.raises(ToolError, match="existiert nicht"):
        source._find_market("10115", market_id="nonexistent-id")


def test_trinkgut_store_cache_and_expiration(tmp_path, monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace(), cache_dir=tmp_path, store_cache_ttl_seconds=3600)
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)

    # First lookup caches market
    _session, m_id, url, label, dist = source._find_market("41238", use_cache=True)
    assert source.last_discovery == "trinkgut Marktsuche (exakt)"

    # Second lookup should hit cache
    _session2, m_id2, url2, label2, dist2 = source._find_market("41238", use_cache=True)
    assert m_id2 == m_id
    assert source.last_discovery == "24h-Marktcache"

    # Drop cached market
    source._drop_cached_market("41238")
    assert source._cached_market("41238") is None


def test_trinkgut_markets_method_returns_distance(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: (51.2217, 6.7762))

    markets = source.markets("40213")
    assert len(markets) == 3
    # First should be closest
    assert markets[0]["market_id"] == "market-2"
    assert "distance_km" in markets[0]
    assert markets[0]["distance_km"] < 5.0


def test_trinkgut_parse_card():
    source = OfficialTrinkgutSource(SimpleNamespace())
    html = """
    <div class="product-box box-boxed">
      <div class="product-image-wrapper">
        <a class="product-image-link" href="https://www.trinkgut.de/aktuelle-angebote/diebels-alt" title="Diebels Alt">
          <img alt="Diebels Alt" class="product-image" src="https://media.trinkgut.de/media/products/diebels.png" />
        </a>
      </div>
      <div class="product-info">
        <div class="product-price-wrapper">
          <p class="product-price"><span>22.00</span></p>
        </div>
        <p class="h4 product-name">Diebels Alt</p>
        <p class="product-description">2 Kästen à 20 x 0,5 l (1 l = € 1.10) zzgl. € 3.10 Pfand</p>
      </div>
    </div>
    """
    card = BeautifulSoup(html, "html.parser").select_one(".product-box")
    offer = source._parse_card(
        card,
        index=1,
        category="Bier",
        market_id="market-1",
        market_url="https://www.trinkgut.de/markt/endt",
        validity_label="14.09.–19.09.2026",
        valid_from=date(2026, 9, 14),
        valid_until=date(2026, 9, 19),
    )
    assert offer is not None
    assert offer.retailer == "trinkgut"
    assert offer.name == "Diebels Alt"
    assert offer.price == 22.00
    assert offer.deposit == 3.10
    assert offer.base_price == 1.10
    assert offer.base_unit == "l"
    assert offer.category == "Bier"
    assert offer.image_url == "https://media.trinkgut.de/media/products/diebels.png"
    assert offer.product_url == "https://www.trinkgut.de/aktuelle-angebote/diebels-alt"
    assert offer.valid_from == "2026-09-14"
    assert offer.valid_until == "2026-09-19"


def test_trinkgut_parse_validity():
    soup = BeautifulSoup(
        "<p class='intro'>Gültig vom 14.09.2026 bis 19.09.2026 | Nur solange der Vorrat reicht.</p>",
        "html.parser",
    )
    start, end, label = OfficialTrinkgutSource._parse_validity(soup)
    assert start == date(2026, 9, 14)
    assert end == date(2026, 9, 19)
    assert "14.09." in label and "19.09.2026" in label


def test_trinkgut_load_with_mock_session(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)

    page_html = """
    <html>
      <body>
        <p class="intro">Gültig vom 14.09.2026 bis 19.09.2026</p>
        <div class="cms-listing-row">
          <div class="col-12 listing-divider"><h2>Bier</h2></div>
          <div class="cms-listing-col">
            <div class="product-box">
              <a class="product-image-link" href="/angebot/bier1"><img class="product-image" src="https://media.trinkgut.de/b1.png"/></a>
              <p class="product-name">Test Bier</p>
              <p class="product-price"><span>14.99</span></p>
              <p class="product-description">20 x 0,5 l (1 l = € 1.50) zzgl. € 3.10 Pfand</p>
            </div>
          </div>
          <div class="col-12 listing-divider"><h2>Wasser</h2></div>
          <div class="cms-listing-col">
            <div class="product-box">
              <a class="product-image-link" href="/angebot/wasser1"><img class="product-image" src="https://media.trinkgut.de/w1.png"/></a>
              <p class="product-name">Test Mineralwasser</p>
              <p class="product-price"><span>4.99</span></p>
              <p class="product-description">12 x 1,0 l (1 l = € 0.42) zzgl. € 3.30 Pfand</p>
            </div>
          </div>
        </div>
      </body>
    </html>
    """

    class MockResponse:
        status_code = 200
        text = page_html

    class MockCookies:
        def __init__(self):
            self._cookies = {}

        def set(self, name, value, **kwargs):
            self._cookies[name] = value

    class MockSession:
        def __init__(self):
            self.cookies = MockCookies()

        def get(self, url, timeout):
            return MockResponse()

    session = MockSession()
    monkeypatch.setattr(source, "_session", lambda: session)

    offers = source.load("41238")
    assert len(offers) == 2
    assert session.cookies._cookies.get("market") == "market-1"

    bier = next(o for o in offers if o.name == "Test Bier")
    assert bier.category == "Bier"
    assert bier.price == 14.99
    assert bier.deposit == 3.10

    wasser = next(o for o in offers if o.name == "Test Mineralwasser")
    assert wasser.category == "Wasser"
    assert wasser.price == 4.99
    assert wasser.deposit == 3.30
