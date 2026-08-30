from bs4 import BeautifulSoup
import pytest
from types import SimpleNamespace

from supermarkt.sources.rewe import OfficialReweSource
from supermarkt.models import ToolError


def test_rewe_market_search_counts_unique_selectable_market_ids(monkeypatch):
    html = """
    <main>
      <article><span>REWE Markt 12345 Teststadt</span>
        <a href="/angebote/teststadt/100/rewe-markt-hauptstrasse/">Angebote</a>
      </article>
      <article><span>REWE Markt 12345 Teststadt</span>
        <a href="/angebote/teststadt/100/rewe-markt-hauptstrasse-neu/">Angebote</a>
      </article>
      <article><span>REWE Center 12345 Teststadt</span>
        <a href="/angebote/teststadt/200/rewe-center-marktplatz/">Angebote</a>
      </article>
    </main>
    """

    class Response:
        status_code = 200
        text = html

    class Session:
        def get(self, _url, timeout):
            assert timeout > 0
            return Response()

    source = OfficialReweSource(SimpleNamespace(locality=lambda postal_code: "Teststadt"))
    monkeypatch.setattr(source, "_session", lambda: Session())

    markets = source.markets("12345")
    assert [market["market_id"] for market in markets] == ["200", "100"]


def test_rewe_card_keeps_explicit_deposit():
    card = BeautifulSoup(
        '''
        <article>
          <h3 class="cor-offer-information__title">Energy Drink</h3>
          <span class="cor-offer-price__tag-price">0,79 €</span>
          <div class="cor-offer-information__additional">0,5-l-Dose zzgl. 0,25 € Pfand</div>
        </article>
        ''',
        "html.parser",
    ).article
    offer, bonus_only = OfficialReweSource(object())._parse_card(
        card,
        nan="123",
        category="Getränke",
        market_id="456",
        market_url="https://www.rewe.de/angebote/test/456/rewe-markt-test/",
    )
    assert bonus_only is False
    assert offer is not None and offer.deposit == 0.25


def test_rewe_bonus_in_additional_text_is_applied_as_cashback():
    from supermarkt.compare import OfferComparator
    from supermarkt.models import LoyaltyBenefit

    card = BeautifulSoup(
        '''
        <article>
          <h3 class="cor-offer-information__title">Joghurt</h3>
          <span class="cor-offer-price__tag-price">0,99 €</span>
          <div class="cor-offer-information__additional">HINWEIS: MIT APP 0,10 € REWE BONUS</div>
        </article>
        ''',
        "html.parser",
    ).article
    offer, bonus_only = OfficialReweSource(object())._parse_card(
        card, nan="bonus", category="Molkereiprodukte & Eier", market_id="456",
        market_url="https://www.rewe.de/angebote/test/456/rewe-markt-test/",
    )
    assert bonus_only is False
    assert offer is not None
    assert offer.benefits == (LoyaltyBenefit("rewe_bonus", "cashback", 0.10, "REWE Bonus"),)
    compared = OfferComparator().compare([offer], ("rewe_bonus",), "all").offers[0]
    assert compared.checkout_price == 0.99
    assert compared.effective_price == 0.99
    assert compared.loyalty_savings == 0.0
    assert compared.applied_benefits == (LoyaltyBenefit("rewe_bonus", "cashback", 0.10, "REWE Bonus"),)


def test_rewe_bonus_parser_does_not_invent_value_from_points_or_percentages():
    source = OfficialReweSource(object())
    empty = BeautifulSoup("<article></article>", "html.parser").article
    assert source._bonus_amount(empty, "10 % REWE Bonus") is None
    assert source._bonus_amount(empty, "100 REWE Bonus-Punkte") is None


def test_rewe_current_container_accepts_current_class_layout():
    soup = BeautifulSoup(
        """
        <div class="sos-categories-current sos-categories"
             data-controller="categories"
             data-categories-week-value="current"
             data-categories-offer-outlet="#sos-categories-current [data-controller='offer']"
             data-testid="sos-categories">
          <div data-controller="offer" data-offer-nan="123" data-offer-wwident="456"></div>
        </div>
        """,
        "html.parser",
    )
    root = OfficialReweSource._offer_root(soup, "current")
    assert root is not None
    wrappers = OfficialReweSource._offer_wrappers(root)
    assert len(wrappers) == 1
    assert wrappers[0]["data-offer-nan"] == "123"


def test_rewe_current_container_accepts_id_layout():
    soup = BeautifulSoup(
        '<div id="sos-categories-current"><div class="sos-offer" data-offer-nan="123"></div></div>',
        "html.parser",
    )
    root = OfficialReweSource._offer_root(soup, "current")
    assert root is not None
    assert len(OfficialReweSource._offer_wrappers(root)) == 1


def test_rewe_offer_wrapper_does_not_require_wwident_attribute():
    soup = BeautifulSoup(
        '<div data-categories-week-value="current"><div data-controller="offer" data-offer-nan="789"></div></div>',
        "html.parser",
    )
    root = OfficialReweSource._offer_root(soup, "current")
    wrappers = OfficialReweSource._offer_wrappers(root)
    assert [node.get("data-offer-nan") for node in wrappers] == ["789"]


def test_rewe_sunday_targets_next_week():
    from datetime import date
    assert OfficialReweSource._target_week(date(2026, 8, 9)) == "next"
    assert OfficialReweSource._target_week(date(2026, 8, 10)) == "current"


def test_rewe_next_container_is_selected_independently_from_current():
    soup = BeautifulSoup(
        """
        <div class="sos-categories-current" data-categories-week-value="current">
          <div data-controller="offer" data-offer-nan="old"></div>
        </div>
        <div class="sos-categories-next" data-categories-week-value="next">
          <div data-controller="offer" data-offer-nan="new"></div>
        </div>
        """,
        "html.parser",
    )
    root = OfficialReweSource._offer_root(soup, "next")
    assert root is not None
    assert [node.get("data-offer-nan") for node in OfficialReweSource._offer_wrappers(root)] == ["new"]


def test_rewe_next_category_marker_walks_up_to_week_root():
    soup = BeautifulSoup(
        """
        <div data-controller="categories" data-categories-week-value="next">
          <section data-testid="sos-category-getraenke-week-next">
            <div data-controller="offer" data-offer-nan="42"></div>
          </section>
        </div>
        """,
        "html.parser",
    )
    root = OfficialReweSource._offer_root(soup, "next")
    assert root is not None
    assert root.get("data-categories-week-value") == "next"


def test_rewe_can_use_rendered_cards_without_nan_wrapper():
    soup = BeautifulSoup(
        """
        <div data-categories-week-value="next">
          <section data-category-id="alkoholfreie-getraenke">
            <article class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Cola</div>
              <div class="cor-offer-price__tag-price">1,49 €</div>
            </article>
          </section>
        </div>
        """,
        "html.parser",
    )
    root = OfficialReweSource._offer_root(soup, "next")
    unique, rendered = OfficialReweSource._collect_offer_cards(root, "1766160")
    assert list(unique) == ["dom-1"]
    assert unique["dom-1"]["category"] == "alkoholfreie getraenke"
    assert "dom-1" in rendered


def test_rewe_sunday_week_label_points_to_upcoming_week():
    from datetime import date
    assert OfficialReweSource._week_label(date(2026, 8, 9)) == "10.08.–16.08.2026"


def test_rewe_uses_week_next_query_on_sunday():
    from datetime import date
    from supermarkt.sources.rewe import OfficialReweSource

    url = "https://www.rewe.de/angebote/dresden/1763556/rewe-markt-schweriner-str-12/"
    assert OfficialReweSource._market_week_url(url, date(2026, 8, 9)).endswith("?week=next")
    assert OfficialReweSource._market_week_url(url, date(2026, 8, 10)) == url


def test_rewe_offer_root_marker_fallback_has_normal_class_set():
    from bs4 import BeautifulSoup
    from supermarkt.sources.rewe import OfficialReweSource

    soup = BeautifulSoup('''
      <div class="sos-categories-next" data-categories-week-value="next">
        <div data-testid="sos-category-test-week-next"></div>
      </div>
    ''', "html.parser")
    root = OfficialReweSource._offer_root(soup, "next")
    assert root is not None
    assert root.get("data-categories-week-value") == "next"


def test_rewe_explicit_next_url_can_use_active_generic_container():
    soup = BeautifulSoup(
        '''
        <div class="sos-categories-current sos-categories" data-controller="categories">
          <div data-controller="offer" data-offer-nan="new" data-offer-wwident="different"></div>
        </div>
        ''',
        "html.parser",
    )
    root = OfficialReweSource._best_offer_root(
        soup,
        "next",
        "https://www.rewe.de/angebote/musterstadt/222/rewe-center/?week=next",
    )
    assert root is not None
    unique, _ = OfficialReweSource._collect_offer_cards(root, "222")
    assert unique["new"]["wwident"] == "different"



def test_rewe_same_postcode_prefers_center_over_page_order():
    candidates = [
        ("111", "https://example/rewe-markt-hauptstr-1/", "Hauptstr. 1 12345 Musterstadt"),
        ("222", "https://example/rewe-center-marktplatz-2/", "Marktplatz 2 12345 Musterstadt"),
    ]
    chosen = min(candidates, key=OfficialReweSource._market_rank)
    assert chosen[0] == "222"


def test_rewe_find_market_prefers_center_for_same_postcode(monkeypatch):
    class Locator:
        def locality(self, postal_code):
            assert postal_code == "12345"
            return "Musterstadt"

    class Response:
        status_code = 200
        text = """
        <div><a href="/angebote/musterstadt/111/rewe-markt-hauptstr-1/">
          Angebote zu REWE Markt - Hauptstr. 1, 12345 Musterstadt
        </a></div>
        <div><a href="/angebote/musterstadt/222/rewe-center-marktplatz-2/">
          Angebote zu REWE Center - Marktplatz 2, 12345 Musterstadt
        </a></div>
        """

    class Session:
        def get(self, url, timeout):
            return Response()

    source = OfficialReweSource(Locator())
    monkeypatch.setattr(source, "_session", lambda: Session())
    _session, market_id, market_url, label = source._find_market("12345")
    assert market_id == "222"
    assert "marktplatz-2" in market_url
    assert "REWE Center" in label


def test_rewe_lists_all_exact_postcode_markets_and_honours_manual_choice(monkeypatch):
    class Locator:
        def locality(self, postal_code):
            assert postal_code == "12345"
            return "Musterstadt"

    class Response:
        status_code = 200
        text = """
        <div><a href="/angebote/musterstadt/111/rewe-markt-hauptstr-1/">
          Angebote zu REWE Markt - Hauptstr. 1, 12345 Musterstadt
        </a></div>
        <div><a href="/angebote/musterstadt/222/rewe-center-marktplatz-2/">
          Angebote zu REWE Center - Marktplatz 2, 12345 Musterstadt
        </a></div>
        <div><a href="/angebote/anderswo/999/rewe-markt-falsch/">
          Angebote zu REWE Markt - Falsch 1, 54321 Anderswo
        </a></div>
        """

    class Session:
        def get(self, url, timeout):
            return Response()

    source = OfficialReweSource(Locator())
    monkeypatch.setattr(source, "_session", lambda: Session())

    markets = source.markets("12345")
    assert [market["market_id"] for market in markets] == ["222", "111"]
    _session, market_id, market_url, label = source._find_market("12345", market_id="111")
    assert market_id == "111"
    assert "hauptstr-1" in market_url
    assert "REWE Markt" in label

    with pytest.raises(ToolError, match="gehört nicht zur PLZ"):
        source._find_market("12345", market_id="999")


def test_rewe_merges_exact_markets_from_city_and_state_pages(monkeypatch):
    """A suburb market may only be listed on REWE's state overview."""
    postal = "042" + "09"
    class Locator:
        def locality(self, postal_code):
            assert postal_code == postal
            return "Leipzig"

        def state(self, postal_code):
            assert postal_code == postal
            return "Sachsen"

    city = f"""
      <article><a href="/angebote/leipzig/1931419/rewe-center-ludwigsburger-str-9/">
        REWE Center - Ludwigsburger Str. 9, {postal} Leipzig
      </a></article>
    """
    state = f"""
      <article><a href="/angebote/leipzig-ot-gruenau-ost/1931089/rewe-markt-gruenauer-allee-38/">
        REWE Markt - Grünauer Allee 38, {postal} Leipzig OT Grünau-Ost
      </a></article>
    """

    class Response:
        status_code = 200

        def __init__(self, text):
            self.text = text

    class Session:
        def get(self, url, timeout):
            assert timeout > 0
            return Response(state if "/marktsuche/sachsen/" in url else city)

    source = OfficialReweSource(Locator())
    monkeypatch.setattr(source, "_session", lambda: Session())

    markets = source.markets(postal)
    assert {market["market_id"] for market in markets} == {"1931419", "1931089"}


def test_rewe_market_mapping_is_cached_for_24_hours(tmp_path, monkeypatch):
    class Locator:
        def __init__(self):
            self.calls = 0

        def locality(self, postal_code):
            self.calls += 1
            assert postal_code == "12345"
            return "Musterstadt"

    class Response:
        status_code = 200
        text = """
        <div><a href="/angebote/musterstadt/222/rewe-center-marktplatz-2/">
          Angebote zu REWE Center - Marktplatz 2, 12345 Musterstadt
        </a></div>
        """

    class Session:
        def get(self, url, timeout):
            assert "/marktsuche/musterstadt/" in url
            return Response()

    locator = Locator()
    source = OfficialReweSource(locator, cache_dir=tmp_path, store_cache_ttl_seconds=86400)
    monkeypatch.setattr(source, "_session", lambda: Session())

    _session, market_id, market_url, label = source._find_market("12345")
    assert market_id == "222"
    assert source.last_discovery == "REWE Marktsuche"
    assert locator.calls == 1
    assert (tmp_path / "stores.json").exists()

    class CachedSession:
        pass

    monkeypatch.setattr(source, "_session", lambda: CachedSession())
    _session, cached_id, cached_url, cached_label = source._find_market("12345")
    assert isinstance(_session, CachedSession)
    assert (cached_id, cached_url, cached_label) == (market_id, market_url, label)
    assert source.last_discovery == "24h-Marktcache"
    assert locator.calls == 1


def test_rewe_expired_market_cache_is_re_resolved(tmp_path, monkeypatch):
    import json
    import time

    class Locator:
        def __init__(self):
            self.calls = 0

        def locality(self, postal_code):
            self.calls += 1
            return "Musterstadt"

    class Response:
        status_code = 200
        text = """
        <a href="/angebote/musterstadt/222/rewe-center-marktplatz-2/">
          REWE Center - Marktplatz 2, 12345 Musterstadt
        </a>
        """

    class Session:
        def get(self, url, timeout):
            return Response()

    cache = {
        "12345": {
            "market_id": "111",
            "market_url": "https://www.rewe.de/angebote/alt/111/rewe-markt-alt/",
            "label": "Alt",
            "created_at": time.time() - 90000,
            "expires_at": time.time() - 1,
        }
    }
    (tmp_path / "stores.json").write_text(json.dumps(cache), encoding="utf-8")

    locator = Locator()
    source = OfficialReweSource(locator, cache_dir=tmp_path, store_cache_ttl_seconds=86400)
    monkeypatch.setattr(source, "_session", lambda: Session())

    _session, market_id, market_url, label = source._find_market("12345")
    assert market_id == "222"
    assert "marktplatz-2" in market_url
    assert source.last_discovery == "REWE Marktsuche"
    assert locator.calls == 1


def test_rewe_offer_title_drops_backstation_footnote_number():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        '<div class="cor-offer-information__title">Bueno oder Lemon Croissant <sup>2</sup></div>',
        "html.parser",
    )
    title_node = soup.select_one(".cor-offer-information__title")
    assert OfficialReweSource._offer_title(title_node) == "Bueno oder Lemon Croissant"


def test_rewe_offer_title_keeps_real_plain_number():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        '<div class="cor-offer-information__title">Produkt Generation 2</div>',
        "html.parser",
    )
    title_node = soup.select_one(".cor-offer-information__title")
    assert OfficialReweSource._offer_title(title_node) == "Produkt Generation 2"
