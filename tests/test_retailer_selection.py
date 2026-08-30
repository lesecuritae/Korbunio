from supermarkt.service import SupermarketEngine
from supermarkt.models import Offer
from supermarkt.service import SourceLoader


def test_retailer_selection_has_separate_deterministic_cache_keys():
    all_key = SupermarketEngine.cache_key("50677", "auto", ())
    one_key = SupermarketEngine.cache_key("50677", "auto", ("REWE",))
    several_a = SupermarketEngine.cache_key("50677", "auto", ("Globus", "REWE"))
    several_b = SupermarketEngine.cache_key("50677", "auto", ("REWE", "Globus"))
    assert all_key != one_key
    assert one_key != several_a
    assert several_a == several_b
    assert SupermarketEngine.cache_key("50677", "auto", ("REWE",), "123") != one_key
    assert SupermarketEngine.cache_key("50677", "auto", ("Netto Marken-Discount",), "", "5303") != SupermarketEngine.cache_key("50677", "auto", ("Netto Marken-Discount",))
    assert SupermarketEngine.cache_key("50677", "auto", offer_week="current") != SupermarketEngine.cache_key("50677", "auto", offer_week="next")


def _offer(retailer: str) -> Offer:
    return Offer(f"{retailer}:1", retailer, "Test", f"{retailer} Produkt", "", "", 1.0, None, "", "", "Aktuell", f"{retailer}:key", "https://example.invalid")


def test_source_loader_executes_only_selected_retailers():
    calls = []
    progress_events = []
    class Source:
        last_market_url = last_market_label = ""
        def __init__(self, retailer): self.retailer = retailer
        def load(self, postal):
            calls.append(self.retailer)
            return [_offer(self.retailer)]
    loader = SourceLoader.__new__(SourceLoader)
    loader.official_rewe = Source("REWE")
    loader.official_globus = Source("Globus")
    loader.aldi_region = type("Region", (), {"last_error": ""})()

    result = loader.load(
        "50677", "auto", retailers=("REWE", "Globus"),
        progress=lambda **event: progress_events.append(event),
    )

    assert set(calls) == {"REWE", "Globus"}
    assert {item["retailer"] for item in result["offers"]} == {"REWE", "Globus"}
    assert set(result["retailers"]) == {"REWE", "Globus"}
    totals = [event for event in progress_events if "total_sources" in event]
    assert totals[0]["total_sources"] == 2
    # Globus can add one image-only aggregator pass after its official
    # catalogue has been inspected.
    assert totals[-1]["total_sources"] == 3
    assert all(
        event.get("processed_sources", 0) <= totals[-1]["total_sources"]
        for event in progress_events
    )


def test_source_loader_keeps_selected_netto_branch_with_regional_catalogue(monkeypatch):
    from datetime import date
    from supermarkt.compare import OfferMapper

    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 29))

    class Markets:
        selected = ""
        def resolve(self, postal_code, market_id=""):
            assert postal_code == "12345"
            self.selected = market_id
            return {"store_id": market_id or "10", "post_code": postal_code, "street": "Hauptstr. 1", "city": "Teststadt"}
        def _option(self, store, match_type):
            return {"market_id": store["store_id"], "label": "Netto – Hauptstr. 1, 12345 Teststadt", "market_url": "https://www.netto-online.de/filialen/test/20", "match_type": match_type}

    class Marktguru:
        def load_offers(self, _postal): return [], []
        def load_retailer_queries(self, _postal, _names):
            return [{
                "id": "n1", "advertisers": [{"name": "Netto Marken-Discount", "uniqueName": "netto-marken-discount"}],
                "validityDates": [{"from": "2026-08-24", "to": "2026-08-29"}],
                "product": {"name": "Testprodukt", "description": "500 g"},
                "categories": [{"name": "Test"}], "price": 1.99,
            }], []

    resolver = Markets()
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = type("Region", (), {"last_error": ""})()
    loader.netto_marken_markets = resolver
    loader.marktguru = Marktguru()
    loader.mapper = OfferMapper()

    result = loader.load("12345", "auto", retailers=("Netto Marken-Discount",), netto_market_id="20")
    assert resolver.selected == "20"
    assert result["retailers"]["Netto Marken-Discount"]["market_label"] == "Netto – Hauptstr. 1, 12345 Teststadt"
    assert any("regional und nicht filialgenau" in warning for warning in result["store_warnings"])


def test_next_week_without_marktguru_preview_falls_back_to_current_offers(monkeypatch):
    from datetime import date
    from supermarkt.compare import OfferMapper

    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 26))
    monkeypatch.setattr("supermarkt.service.offer_week_reference", lambda week: date(2026, 9, 2) if week == "next" else date(2026, 8, 26))

    class Marktguru:
        def load_offers(self, _postal):
            return [{
                "id": "lidl-current",
                "advertisers": [{"name": "Lidl"}],
                "validityDates": [{"from": "2026-08-24", "to": "2026-08-29"}],
                "product": {"name": "Aktuelles Produkt", "description": "500 g"},
                "categories": [{"name": "Test"}],
                "price": 1.99,
            }], []

        def load_retailer_queries(self, _postal, _names):
            return [], []

    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = type("Region", (), {"last_error": ""})()
    loader.marktguru = Marktguru()
    loader.mapper = OfferMapper()

    result = loader.load("50677", "auto", retailers=("Lidl",), offer_week="next")

    assert [offer["name"] for offer in result["offers"]] == ["Aktuelles Produkt"]
    assert result["offer_week"] == "next"
    assert any(
        "Lidl: Noch keine Angebote der Folgewoche verfügbar" in warning
        for warning in result["store_warnings"]
    )
