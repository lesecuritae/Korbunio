from datetime import date
import json

from supermarkt.sources.kaufland import OfficialKauflandSource


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
