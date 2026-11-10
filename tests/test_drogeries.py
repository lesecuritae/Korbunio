import pytest

from supermarkt.models import ToolError
from supermarkt.sources.drogeries import OfficialDmSource, OfficialMuellerSource, OfficialRossmannSource


ROSSMANN_HTML = """
<h2>Gültig ab Montag: 24.08. - 28.08.2026</h2>
<div data-testid="product-card">
 <span>Aus der Werbung</span>
 <a href="/de/pflege/testprodukt/p/123"><img src="https://img.example/r.jpg" alt="Testprodukt"></a>
 <a href="/de/pflege/testprodukt/p/123" data-testid="product-brandAndName">Marke Testprodukt</a>
 <span data-testid="product-baseprice">250 ml (1L = 7,96 €)</span><span data-testid="product-price">1 . 99 € Price 1,99 €</span>
</div>
"""

MUELLER_HTML = """
<article><span class="product-badges__text">Sale</span>
 <a data-product-id="2998372" href="/p/testprodukt-IPN2998372/"><img src="https://img.example/m.jpg" alt="Testprodukt"></a>
 <span class="product-tile__product-name">Marke Testprodukt 250 ml</span>
 <span data-testid="plp-currentPrice-label">2,49 €</span>
 <span class="product-price__capacity">/ 250 ml</span>
 <div class="product-price__base-price"><span>9,96 € / 1 l</span></div>
 <span>Online verfügbar</span>
</article>
"""


class FakeHttp:
    def get_bytes(self, url, headers=None):
        return MUELLER_HTML.encode()


class FakeDmHttp:
    calls = 0

    def get_json(self, url, headers=None):
        self.calls += 1
        assert url.startswith(OfficialDmSource.SEARCH_API)
        assert headers["Referer"] == OfficialDmSource.OFFERS_URL
        return {
            "count": 2,
            "products": [
                {
                    "dan": 3061034,
                    "brandName": "ebelin",
                    "title": "Seifendose stapelbar, 1 St",
                    "tileData": {
                        "dan": 3061034,
                        "self": "/p/d/3061034/ebelin-seifendose-stapelbar",
                        "eyecatchers": [{"alt": "Ausverkauf Grafik"}],
                        "images": [{"tileSrc": "https://products.dm-static.com/item.jpg"}],
                        "price": {
                            "price": {
                                "current": {"value": "1,95 €"},
                                "previous": {"value": "2,55 €"},
                            },
                            "tileInfos": ["1 St (1,95 € je 1 St)"],
                        },
                        "trackingData": {"categories": ["Seifenspender & Zahnputzbecher"]},
                    },
                },
                {
                    "dan": 1,
                    "title": "Reguläres Produkt",
                    "tileData": {"eyecatchers": [], "price": {"price": {"current": {"value": "3,00 €"}}}},
                },
            ],
        }


class MuellerChallengeHttp:
    def get_bytes(self, url, headers=None):
        raise ToolError("HTTP 403 bei www.mueller.de")




def test_rossmann_official_advertising_card_mapping():
    offers = OfficialRossmannSource(lambda _url: ROSSMANN_HTML).load("10115")
    assert len(offers) == 1
    offer = offers[0]
    assert (offer.retailer, offer.price, offer.base_price, offer.pack_signature) == (
        "Rossmann", 1.99, 7.96, "250ml",
    )
    assert offer.valid_from == "2026-08-24"
    assert offer.valid_until == "2026-08-28"
    assert offer.product_url.endswith("/de/pflege/testprodukt/p/123")


def test_rossmann_browser_disables_crashpad_for_alpine(monkeypatch):
    captured = {}

    class Result:
        returncode = 133
        stdout = "<html>" + (" " * 20_000) + "</html>"

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return Result()

    monkeypatch.setattr("supermarkt.sources.drogeries.subprocess.run", fake_run)
    OfficialRossmannSource()._render(OfficialRossmannSource.OFFERS_URL)
    assert "--disable-crashpad-for-testing" in captured["command"]
    assert "--single-process" in captured["command"]


def test_mueller_online_offer_mapping_is_labelled_as_online():
    offers = OfficialMuellerSource(FakeHttp()).load("10115")
    assert len(offers) == 1
    offer = offers[0]
    assert (offer.retailer, offer.price, offer.base_price, offer.pack_signature) == (
        "Müller", 2.49, 9.96, "250ml",
    )
    assert "Online" in offer.coverage_note
    assert offer.product_url.endswith("/p/testprodukt-IPN2998372/")


def test_mueller_403_is_reported_as_manual_browser_challenge():
    with pytest.raises(ToolError, match="Browser-Prüfung"):
        OfficialMuellerSource(MuellerChallengeHttp()).load("10115")




def test_dm_maps_only_official_clearance_products_and_caches_catalogue():
    http = FakeDmHttp()
    source = OfficialDmSource(http, cache_ttl_seconds=3600)
    offers = source.load("10115")
    again = source.load("50667")
    assert http.calls == 1
    assert again == offers
    assert len(offers) == 1
    offer = offers[0]
    # The published title explicitly says "1 St"; it is a real quantity.
    assert (offer.retailer, offer.price, offer.pack_signature) == ("dm", 1.95, "1stk")
    assert offer.category == "Haushalt & Reinigung"
    assert offer.description == "Vorher 2,55 €"
    assert "Filialverfügbarkeit unbekannt" in offer.coverage_note
    assert offer.product_url == "https://www.dm.de/p/d/3061034/ebelin-seifendose-stapelbar"


def test_mueller_uses_department_pages_and_survives_one_failing_page():
    calls = []

    class Http(FakeHttp):
        def get_bytes(self, url, headers=None):
            calls.append(url)
            if "schreibwaren" in url:
                raise ToolError("HTTP 404 bei www.mueller.de")
            return super().get_bytes(url, headers)

    offers = OfficialMuellerSource(Http()).load("10115")
    assert len(calls) == len(OfficialMuellerSource.OFFERS_URLS) and all("/aktionen/" in url for url in calls)
    assert len(offers) == 1  # identical tile on every page is de-duplicated
    assert "online-angebote" not in OfficialMuellerSource.OFFERS_URL


def test_mueller_follows_numbered_pages_and_never_silently_calls_partial_complete(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    monkeypatch.setattr(OfficialMuellerSource, "OFFERS_URLS", (OfficialMuellerSource.OFFERS_URL,))
    class Http(FakeHttp):
        def __init__(self, fail=False, repeat=False):
            self.calls = []
            self.fail = fail
            self.repeat = repeat
        def get_bytes(self, url, headers=None):
            self.calls.append(url)
            page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
            if page == 2 and self.fail:
                raise ToolError("HTTP 503")
            html = super().get_bytes(url, headers).decode()
            if page == 1:
                return (html + '<a href="?page=2">2</a>').encode()
            return html.encode()
    # Fixture IDs are discovered from the existing public-page fixture instead of replacing its expected name/price.
    first = FakeHttp().get_bytes(OfficialMuellerSource.OFFERS_URL).decode()
    import re
    identifier = re.search(r'data-product-id="([^"]+)"', first)[1]
    class Pages(Http):
        def get_bytes(self, url, headers=None):
            body = super().get_bytes(url, headers)
            if "page=2" in url and not self.repeat:
                body = body.replace(f'data-product-id="{identifier}"'.encode(), b'data-product-id="fixture-second-page"')
            return body
    complete = OfficialMuellerSource(Pages()).load("10115")
    assert len(complete) == 2 and not complete.note
    partial = OfficialMuellerSource(Pages(fail=True)).load("10115")
    assert len(partial) == 1 and "503" in partial.note
    repeated = OfficialMuellerSource(Pages(repeat=True)).load("10115")
    assert len(repeated) == 1 and "wiederholt" in repeated.note


def test_dm_follows_declared_pages_even_when_a_page_is_short_and_rejects_a_missing_page():
    import copy
    from urllib.parse import parse_qs, urlsplit
    class Pages(FakeDmHttp):
        def __init__(self, fail=False):
            super().__init__()
            self.fail = fail
        def get_json(self, url, headers=None):
            page = int(parse_qs(urlsplit(url).query)["currentPage"][0])
            if page == 1 and self.fail:
                raise ToolError("dm fixture timeout")
            data = copy.deepcopy(super().get_json(url, headers))
            data.update(totalPages=2, currentPage=page, count=4)  # API count is global, not per-page.
            for product in data["products"]:
                if page:
                    product["dan"] = "fixture-second-page"
                    product["tileData"]["dan"] = "fixture-second-page"
            return data
    source = OfficialDmSource(Pages())
    assert len(source.load("10115")) == 2
    import pytest
    with pytest.raises(ToolError, match="timeout"):
        OfficialDmSource(Pages(fail=True)).load("10115")


def test_mueller_action_category_is_not_offer_evidence_without_explicit_sale():
    from pathlib import Path
    from bs4 import BeautifulSoup
    payload = (Path(__file__).parent / "fixtures/offer_coverage/mueller_mixed_listing.html").read_bytes()
    source = OfficialMuellerSource(FakeHttp())
    offers = source._parse(BeautifulSoup, source.OFFERS_URL, payload)
    assert {o.name: o.price for o in offers} == {
        "fashy Wärmflasche 2l mit Fleecebezug": 8.99,
        "fashy Wärmflasche 2l Halblamelle": 6.99,
        "L'Oréal Men Expert Deo Roll-on Invincible Sport": 2.35,
    }
    assert len(source._listing_ids(BeautifulSoup(payload, "html.parser"))) == 5
    # A comparison to UVP alone is not a published Sale designation.
    assert source._parse(BeautifulSoup, source.OFFERS_URL, payload.replace(b">Sale<", b">Neu<")) == []


def test_mueller_regular_only_pages_do_not_hide_sale_articles_on_later_pages(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    monkeypatch.setattr(OfficialMuellerSource, "OFFERS_URLS", (OfficialMuellerSource.OFFERS_URL,))
    class Pages:
        def get_bytes(self, url, headers=None):
            page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
            html = MUELLER_HTML.replace("2998372", f"fixture-{page}")
            if page < 3:
                html = html.replace(">Sale<", ">Müller Eigenmarke<") + f'<a href="?page={page+1}">{page+1}</a>'
            return html.encode()
    offers = OfficialMuellerSource(Pages()).load("04109")
    assert [o.offer_id for o in offers] == ["mueller:fixture-3"]
    assert not offers.note


def test_dm_rejects_a_syntactically_valid_but_truncated_catalogue():
    class Truncated(FakeDmHttp):
        def get_json(self, url, headers=None):
            data = super().get_json(url, headers)
            return {**data, "count": 3, "totalPages": 1}
    with pytest.raises(ToolError, match="Teilantwort"):
        OfficialDmSource(Truncated()).load("04109")


def test_dm_empty_final_page_is_not_a_complete_catalogue_even_without_a_count():
    class Pages(FakeDmHttp):
        def get_json(self, url, headers=None):
            data = super().get_json(url, headers)
            data.pop("count")
            return {**data, "products": [] if "currentPage=1" in url else data["products"], "totalPages": 2}
    with pytest.raises(ToolError, match="Folgeseite"):
        OfficialDmSource(Pages()).load("04109")
