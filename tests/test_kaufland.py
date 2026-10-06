from datetime import date
import json
import pytest

from supermarkt.models import ToolError

from supermarkt.sources.kaufland import OfficialKauflandSource


@pytest.mark.parametrize("count", [629, 800, 801])
@pytest.mark.parametrize("browser_fallback", [False, True])
def test_store_limit_preserves_valid_week_start_and_checks_browser_fallback(monkeypatch, count, browser_fallback):
    raw = [{
        "offerId": f"ART.{i}", "klNr": str(i), "dateFrom": "2026-10-05",
        "dateTo": "2026-10-07", "title": f"Produkt {i}", "formattedPrice": "1.11",
    } for i in range(count)]
    payload = {"component": "OfferTemplate", "props": {"offerData": {"cycles": [{
        "categories": [{"displayName": "Angebote zum Wochenstart", "offers": raw}],
    }]}}}

    class Http:
        def get_bytes(self, url, headers=None):
            if ".kloffers." in url:
                return json.dumps(raw).encode()
            return json.dumps(payload, separators=(",", ":")).encode()

    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 10, 6))
    source = OfficialKauflandSource(Http(), locator=None)
    store = "https://filiale.kaufland.de/service/filiale/konstanz-industriegebiet-1680.html"
    monkeypatch.setattr(source, "_resolve_store_page", lambda *_args: (store, "", "Konstanz", "78467"))
    if browser_fallback:
        parsed = source._load_structured_offers(store)
        def fail_structured(*_args):
            raise ToolError("Structured source unavailable")
        monkeypatch.setattr(source, "_load_structured_offers", fail_structured)
        monkeypatch.setattr(source, "_load_full_overview", lambda *_args: ("fallback HTML", store))
        monkeypatch.setattr(source, "_parse_page", lambda *_args: parsed)
    if count > 800:
        with pytest.raises(ToolError, match="Filialgrenze 800"):
            source.load("78467")
    else:
        assert len(source.load("78467")) == count


def test_kaufland_store_page_uses_complete_direct_html_before_browser(monkeypatch):
    class Http:
        def get_bytes(self, _url, headers=None):
            return b"<html>Aktuelle Angebote und Prospekte deiner Filiale</html>"

    source = OfficialKauflandSource(Http(), locator=None)
    monkeypatch.setattr(
        "supermarkt.sources.kaufland.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser must not run")),
    )
    page = source._get_html(
        "https://filiale.kaufland.de/service/filiale/test-1.html",
        required_any=("aktuelle angebote und prospekte deiner filiale",),
    )
    assert "Aktuelle Angebote" in page


def test_kaufland_structured_xtra_price_stays_separate_from_regular_price(monkeypatch):
    raw_offers = [{
        "offerId": f"ART.{index}", "klNr": str(index), "dateFrom": "2026-08-27",
        "dateTo": "2026-09-02", "title": f"Produkt {index}", "price": 1.49,
        "formattedPrice": "1.49", "loyaltyFormattedPrice": "1.29*",
        "unit": "je 100-g-Packg.", "formattedBasePrice": "(1 kg = 14.90)",
    } for index in range(100)]
    structured = {"component": "OfferTemplate", "props": {"offerData": {"cycles": [{
        "categories": [{"displayName": "Test", "offers": raw_offers}],
    }]}}}

    class Http:
        def get_bytes(self, url, headers=None):
            if ".kloffers." in url:
                return json.dumps([{
                    "klNr": str(index), "dateFrom": "2026-08-27", "dateTo": "2026-09-02",
                } for index in range(100)]).encode()
            return ("<script>window.SSR = " + json.dumps(structured, separators=(",", ":")) + ";</script>").encode()

    monkeypatch.setattr("supermarkt.sources.kaufland.today_berlin", lambda: date(2026, 8, 28))
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 28))
    offers = OfficialKauflandSource(Http(), locator=None)._load_structured_offers(
        "https://filiale.kaufland.de/service/filiale/test-8870.html"
    )
    assert offers[0].price == 1.49
    assert offers[0].benefits[0].program_id == "kaufland_xtra"
    assert offers[0].benefits[0].value == 1.29


def test_kaufland_keeps_current_thursday_week_on_sunday():
    assert 'kloffer-week=current' in OfficialKauflandSource._overview_url(date(2026, 8, 9))
    assert 'kloffer-week=current' in OfficialKauflandSource._overview_url(date(2026, 8, 10))


def test_kaufland_parser_stops_before_xtra_duplicate_section():
    page = '''
    <html><body>
      <h2>Aktuelle Angebote</h2>
      <div>
        <a href="/a"><img src="https://img.example/a.jpg">KNÜLLER TEST Kaffee je 500-g-Packg. nur 4,99</a>
        <a href="/b"><img src="https://img.example/b.jpg">TEST Milch je 1-l-Packg. nur 0,99</a>
        <a href="#more">Weitere Angebote anzeigen</a>
      </div>
      <h2>Aktuelle Angebote im Prospekt zum Blättern</h2>
      <a href="/prospekt">Prospekt ansehen</a>
      <h2>Aktuelle Kaufland Card XTRA Angebote</h2>
      <a href="/a-xtra"><img src="https://img.example/a.jpg">KNÜLLER TEST Kaffee je 500-g-Packg. nur 4,99 Mit Kaufland Card XTRA nur 4,49</a>
    </body></html>
    '''
    source = OfficialKauflandSource.__new__(OfficialKauflandSource)
    offers = source._parse_page(page, OfficialKauflandSource.CURRENT_OVERVIEW_URL)
    assert [offer.name for offer in offers] == ['TEST Kaffee', 'TEST Milch']
    assert all(not offer.benefits for offer in offers)


def test_kaufland_primary_section_excludes_later_offer_anchors():
    page = '''
    <h2>Aktuelle Angebote</h2>
    <section><a href="/weekly">Produkt nur 1,99</a></section>
    <h2>Aktuelle Kaufland Card XTRA Angebote</h2>
    <section><a href="/duplicate">Produkt nur 1,99</a></section>
    '''
    section = OfficialKauflandSource._offer_section_html(page)
    assert '/weekly' in section
    assert '/duplicate' not in section


def test_kaufland_category_headings_do_not_truncate_weekly_grid():
    page = '''
    <h2>Aktuelle Angebote</h2>
    <a href="/a">Produkt A nur 1,99</a>
    <h2>Obst und Gemüse</h2>
    <a href="/b">Produkt B nur 2,99</a>
    <h2>Aktuelle Kaufland Card XTRA Angebote</h2>
    <a href="/duplicate">Produkt A nur 1,99</a>
    '''
    section = OfficialKauflandSource._offer_section_html(page)
    assert '/a' in section
    assert '/b' in section
    assert '/duplicate' not in section


def test_kaufland_prices_follow_the_store_region_through_the_variant_cookie(monkeypatch):
    """Kaufland shows regional prices: the same article costs 1.59 in one store and 1.79 in another."""
    def structured_for(price):
        raw_offers = [{
            "offerId": f"ART.{index}_KAV.{price}", "klNr": str(index), "dateFrom": "2026-09-17",
            "dateTo": "2026-09-23", "title": f"Produkt {index}", "price": price,
            "formattedPrice": f"{price:.2f}", "unit": "je 100-g-Packg.", "formattedBasePrice": "(1 kg = 14.90)",
        } for index in range(100)]
        return {"component": "OfferTemplate", "props": {"offerData": {"cycles": [{
            "categories": [{"displayName": "Test", "offers": raw_offers}],
        }]}}}

    regional_prices = {"DE4330": 1.59, "DE2543": 1.79}
    sent_cookies = []

    class Http:
        def get_bytes(self, url, headers=None):
            if ".kloffers." in url:
                return json.dumps([{"klNr": str(i), "dateFrom": "2026-09-17", "dateTo": "2026-09-23"} for i in range(100)]).encode()
            cookie = (headers or {}).get("Cookie", "")
            sent_cookies.append(cookie)
            variant = cookie.split("x-aem-variant=", 1)[-1] if "x-aem-variant=" in cookie else ""
            price = regional_prices.get(variant, 1.79)
            return ("<script>window.SSR = " + json.dumps(structured_for(price), separators=(",", ":")) + ";</script>").encode()

    monkeypatch.setattr("supermarkt.sources.kaufland.today_berlin", lambda: date(2026, 9, 19))
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 9, 19))
    source = OfficialKauflandSource(Http(), locator=None)

    kamenz = source._load_structured_offers("https://filiale.kaufland.de/service/filiale/kamenz-4330.html")
    essen = source._load_structured_offers("https://filiale.kaufland.de/service/filiale/essen-nordviertel-2543.html")

    assert sent_cookies == ["x-aem-variant=DE4330", "x-aem-variant=DE2543"]
    assert {offer.price for offer in kamenz} == {1.59}
    assert {offer.price for offer in essen} == {1.79}
