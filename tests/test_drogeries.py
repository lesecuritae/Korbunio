from supermarkt.sources.drogeries import OfficialMuellerSource, OfficialRossmannSource


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
<article>
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
