from datetime import date
from types import SimpleNamespace
from bs4 import BeautifulSoup
import pytest

from supermarkt.models import ToolError
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


def test_trinkgut_never_guesses_a_market_when_geocoding_fails(monkeypatch):
    """A numerically close postal code can be far away; better no market than a wrong one."""
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: None)

    with pytest.raises(ToolError, match="Standort der PLZ"):
        source._find_market("41239", use_cache=False)


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
    # Celle is far outside the default radius and is not offered.
    assert [m["market_id"] for m in markets] == ["market-2", "market-1"]
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


BERLIN = (52.5200, 13.4050)  # Celle (market-3) is ~200 km away, the others further


def test_trinkgut_refuses_a_market_beyond_the_maximum_distance(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: BERLIN)

    with pytest.raises(ToolError) as error:
        source._find_market("10115", use_cache=False)
    message = str(error.value)
    assert "Umkreis von 40 km" in message
    assert "Celle" in message  # names the nearest one and how far it is
    assert "km)" in message


def test_trinkgut_distance_limit_is_configurable(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace(), max_distance_km=300)
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: BERLIN)

    _session, m_id, _url, _label, distance = source._find_market("10115", use_cache=False)
    assert m_id == "market-3"
    assert distance is not None and 150 < distance < 300


def test_trinkgut_limit_is_kept_within_sensible_bounds():
    assert OfficialTrinkgutSource(SimpleNamespace(), max_distance_km=0).max_distance_km == 5
    assert OfficialTrinkgutSource(SimpleNamespace(), max_distance_km=10_000).max_distance_km == 300


def test_trinkgut_an_old_cached_market_cannot_bypass_the_distance_limit(tmp_path, monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace(), cache_dir=tmp_path)
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: BERLIN)
    source._cache_market("10115", "market-3", "https://www.trinkgut.de/markt/isermann", "trinkgut Isermann", 200.0)

    with pytest.raises(ToolError, match="Umkreis"):
        source._find_market("10115", use_cache=True)


def test_trinkgut_market_list_is_empty_when_the_location_is_unknown(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: None)
    assert source.markets("99999") == []


def test_trinkgut_coordinates_are_asked_for_once_per_postal_code():
    calls = []

    class Http:
        def get_bytes(self, url, headers=None):
            calls.append(url)
            return b'[{"lat": "51.2", "lon": "6.7"}]'

    source = OfficialTrinkgutSource(SimpleNamespace(http=Http()))
    assert source._postal_coordinates("40213") == (51.2, 6.7)
    assert source._postal_coordinates("40213") == (51.2, 6.7)
    assert len(calls) == 1


# ---------------------------------------------------------------- foreign URLs


def test_trinkgut_only_ever_requests_its_own_host():
    ok = OfficialTrinkgutSource._is_trinkgut_url
    assert ok("https://www.trinkgut.de/angebot/x")
    assert ok("https://trinkgut.de/angebot/x")
    assert not ok("http://www.trinkgut.de/angebot/x")  # no plain http
    assert not ok("https://evil.example/angebot/x")
    assert not ok("https://www.trinkgut.de.evil.example/x")
    assert not ok("https://user@evil.example/x")
    assert not ok("file:///etc/passwd")
    assert not ok("")


def test_trinkgut_a_foreign_product_link_is_replaced_by_the_offers_page():
    source = OfficialTrinkgutSource(SimpleNamespace())
    html = """
    <div class="product-box">
      <a class="product-image-link" href="https://evil.example/steal"><img class="product-image" src="https://media.trinkgut.de/x.png"/></a>
      <p class="product-price"><span>9.99</span></p>
      <p class="product-name">Testbier</p>
      <p class="product-description">20 x 0,5 l zzgl. € 3.10 Pfand</p>
    </div>
    """
    card = BeautifulSoup(html, "html.parser").select_one(".product-box")
    offer = source._parse_card(
        card, index=1, category="Bier", market_id="m", market_url="https://www.trinkgut.de/markt/x",
        validity_label="", valid_from=None, valid_until=None,
    )
    assert offer is not None
    assert offer.product_url == OfficialTrinkgutSource.OFFERS_URL


def test_trinkgut_a_foreign_market_link_is_replaced(monkeypatch):
    markets = [dict(SAMPLE_MARKETS[0], detailURL="https://evil.example/markt")]
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: markets)
    _s, _id, url, _label, _d = source._find_market("41238", use_cache=False)
    assert url == OfficialTrinkgutSource.MARKETS_URL


# ------------------------------------------------------------- deposit lookups


def _truncated_offer(index):
    from supermarkt.models import Offer

    return Offer(
        offer_id=f"o{index}", retailer="trinkgut", category="Bier", name=f"Bier {index}", brand="",
        description="20 x 0,5 l zzgl. € 3...", price=9.99, base_price=None, base_unit="", pack_signature="",
        validity_label="", match_key=f"k{index}", source_url="https://www.trinkgut.de/angebote/",
        product_url=f"https://www.trinkgut.de/angebot/bier-{index}", minimum_quantity=2, coverage_note="keep",
    )


class _CountingSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout):
        self.urls.append(url)

        class Response:
            status_code = 200
            text = '<div itemprop="description">20 x 0,5 l zzgl. € 3.10 Pfand</div>'

        return Response()


def test_trinkgut_deposit_is_read_once_and_then_remembered():
    source = OfficialTrinkgutSource(SimpleNamespace())
    session = _CountingSession()
    offers = source._enrich_deposits([_truncated_offer(1), _truncated_offer(2)], session)
    assert [o.deposit for o in offers] == [3.10, 3.10]
    assert len(session.urls) == 2

    again = source._enrich_deposits([_truncated_offer(1), _truncated_offer(2)], session)
    assert [o.deposit for o in again] == [3.10, 3.10]
    assert len(session.urls) == 2, "remembered deposits must not be requested again"


def test_trinkgut_enriching_keeps_every_other_field_of_the_offer():
    source = OfficialTrinkgutSource(SimpleNamespace())
    (offer,) = source._enrich_deposits([_truncated_offer(1)], _CountingSession())
    assert offer.deposit == 3.10
    assert offer.minimum_quantity == 2 and offer.coverage_note == "keep"


def test_trinkgut_remembered_deposits_survive_a_restart(tmp_path):
    first = OfficialTrinkgutSource(SimpleNamespace(), cache_dir=tmp_path)
    first._enrich_deposits([_truncated_offer(1)], _CountingSession())

    second = OfficialTrinkgutSource(SimpleNamespace(), cache_dir=tmp_path)
    session = _CountingSession()
    (offer,) = second._enrich_deposits([_truncated_offer(1)], session)
    assert offer.deposit == 3.10
    assert session.urls == []


def test_trinkgut_an_expired_deposit_is_read_again(monkeypatch):
    source = OfficialTrinkgutSource(SimpleNamespace(), deposit_cache_ttl_seconds=300)
    session = _CountingSession()
    source._enrich_deposits([_truncated_offer(1)], session)
    url = _truncated_offer(1).product_url
    source._deposit_cache[url] = (source._deposit_cache[url][0] - 301, 3.10)
    source._enrich_deposits([_truncated_offer(1)], session)
    assert len(session.urls) == 2


def test_trinkgut_number_of_parallel_requests_is_configurable(monkeypatch):
    import concurrent.futures

    seen = []
    real = concurrent.futures.ThreadPoolExecutor

    class Recording(real):
        def __init__(self, max_workers=None, *args, **kwargs):
            seen.append(max_workers)
            super().__init__(*args, max_workers=max_workers, **kwargs)

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", Recording)
    source = OfficialTrinkgutSource(SimpleNamespace(), deposit_workers=2)
    source._enrich_deposits([_truncated_offer(i) for i in range(1, 8)], _CountingSession())
    assert seen == [2]
    assert OfficialTrinkgutSource(SimpleNamespace(), deposit_workers=99).deposit_workers == 12
    assert OfficialTrinkgutSource(SimpleNamespace(), deposit_workers=0).deposit_workers == 1


def test_trinkgut_never_requests_a_detail_page_on_another_host():
    source = OfficialTrinkgutSource(SimpleNamespace())
    offer = _truncated_offer(1)
    offer.product_url = "https://evil.example/steal"
    session = _CountingSession()
    source._enrich_deposits([offer], session)
    assert session.urls == []


def test_proven_no_nearby_store_is_typed_absence_while_geocode_failure_is_not(monkeypatch):
    from supermarkt.models import NoLocalMarketOffers
    source = OfficialTrinkgutSource(SimpleNamespace())
    monkeypatch.setattr(source, "_get_all_markets", lambda _session=None: SAMPLE_MARKETS)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: BERLIN)
    assert isinstance(source.load("10115"), NoLocalMarketOffers)
    monkeypatch.setattr(source, "_postal_coordinates", lambda _code: None)
    with pytest.raises(ToolError, match="Standort"):
        source.load("10115")


@pytest.mark.parametrize("description,pack", [
    ("und weitere Sorten, Kasten = 20 x 0,5 l / 24 x 0,3...", ""),
    ("Kasten = 20 x 0,5 l / 24 x…", ""),
    ("Kasten = 20 x 0,5 l / 24 x 0,33 l", "20x500ml/24x330ml"),
    ("Pack = 6 x 0,33 l (1 l = € 1.76) zzgl. € 0.48 Pfan...", "6x330ml"),
])
def test_trinkgut_truncated_quantity_alternative_never_selects_first_crate(description, pack):
    source = OfficialTrinkgutSource(SimpleNamespace())
    card = BeautifulSoup(f'<div class="product-box"><a title="Getränk"></a><h3 class="product-name">Getränk</h3><p class="product-price"><span>10.99</span></p><div class="product-description">{description}</div></div>', 'html.parser').div
    offer = source._parse_card(card, index=1, category="Getränke", market_id="test", market_url="https://www.trinkgut.de/markt/test", validity_label="Test", valid_from=date(2026,11,9), valid_until=date(2026,11,14))
    assert offer is not None
    assert offer.pack_signature == pack
    if not pack:
        assert offer.base_price is None and offer.base_unit == ""
        assert "abgeschnitten" in offer.coverage_note


def test_trinkgut_payback_points_badge_is_a_bonus_and_never_the_price():
    """Minimal real card (KW46/2026): the points badge precedes the price paragraph."""
    source = OfficialTrinkgutSource(SimpleNamespace())
    html = """
    <div class="product-box box-boxed">
      <div class="product-image-wrapper">
        <a class="product-image-link" href="https://www.trinkgut.de/aktuelle-angebote/grasovka-vodka" title="Grasovka Vodka">
          <img alt="Grasovka Vodka" class="product-image is-standard" src="https://media.trinkgut.de/media/products_md/uploads/promotions/trinkgut-grasovka-wodka-38-0-5l-national-46-2026-temp-6aea050d74e2b156694834.png"/>
        </a>
      </div>
      <div class="product-info">
        <div class="product-price-wrapper">
          <p class="product-price product-price--payback"><span><small>250 Extra °P</small></span></p>
          <p class="product-price"><span>
              8.99
          </span></p>
        </div>
        <p class="h4 product-name">Grasovka Vodka</p>
        <p class="product-description">Original oder Pure, 38% Vol., 0,5 l Flasche (1 l =...</p>
      </div>
    </div>
    """
    card = BeautifulSoup(html, "html.parser").select_one(".product-box")
    offer = source._parse_card(card, index=1, category="Spirituosen", market_id="m", market_url="https://www.trinkgut.de/markt/m", validity_label="09.11.–14.11.2026", valid_from=date(2026, 11, 9), valid_until=date(2026, 11, 14))
    assert offer is not None
    assert offer.name == "Grasovka Vodka"
    assert offer.price == 8.99
    assert offer.pack_signature == "500ml"
    assert offer.base_price is None  # truncated "(1 l =..." publishes no value
    assert offer.benefits == ()
    assert offer.offer_condition == "PAYBACK: 250 Extra °P (Punkte, kein Preisnachlass)"


def test_trinkgut_points_badge_without_a_price_stays_unknown():
    source = OfficialTrinkgutSource(SimpleNamespace())
    card = BeautifulSoup('<div class="product-box"><p class="product-price product-price--payback"><span><small>250 Extra °P</small></span></p><p class="product-name">Wodka</p></div>', "html.parser").div
    assert source._parse_card(card, index=1, category="x", market_id="m", market_url="https://www.trinkgut.de/markt/m", validity_label="", valid_from=None, valid_until=None) is None


@pytest.mark.parametrize("text,pack", [
    ("Vodka 0,5 l Flasche (1 l =...", "500ml"),
    ("Vodka 0,7 l Flasche (1 l =…", "700ml"),
    ("Pack = 6 x 0,33 l (1 l...", "6x330ml"),
    ("Vodka 0,5 l Flasche (1 l = € 17.98)", "500ml"),
    ("Kasten 20 x 0,5 l (auch als 1 l Flasche", "20x500ml/1000ml"),
])
def test_truncated_unit_price_reference_is_not_a_second_pack(text, pack):
    from supermarkt.common import normalize_pack
    assert normalize_pack(text) == pack
