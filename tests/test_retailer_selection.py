from supermarkt.service import SupermarketEngine
from supermarkt.models import Offer
from supermarkt.service import SourceLoader
import pytest


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


@pytest.mark.parametrize("postal_code,regions,expected", [
    ("80331", ("sued",), {"ALDI Süd"}),
    ("04205", ("nord",), {"ALDI Nord"}),
    ("51643", ("nord", "sued"), {"ALDI Nord", "ALDI Süd"}),
])
def test_selecting_aldi_retailers_still_respects_the_postal_region(postal_code, regions, expected):
    from supermarkt.models import LoadResult

    calls = []
    class Region:
        last_error = ""
        last_regions = regions
        def detect(self, code):
            assert code == postal_code
            return regions[0] if len(regions) == 1 else "auto"
    class Aldi:
        def load(self, retailer):
            calls.append(retailer)
            return LoadResult([_offer(retailer)], [])
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = Region()
    loader.official_aldi = Aldi()
    result = loader.load(postal_code, "auto", retailers=("ALDI Nord", "ALDI Süd"))
    assert set(result["unavailable_retailers"]) == {"ALDI Nord", "ALDI Süd"} - expected
    assert set(calls) == expected
    assert {item["retailer"] for item in result["offers"]} == expected


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


@pytest.mark.parametrize("selected,regions,missing", [
    (("ALDI Nord",), ("sued",), ["ALDI Nord"]),
    (("ALDI Nord",), ("nord", "sued"), []),
])
def test_aldi_absence_is_based_on_verified_region_not_selection(selected, regions, missing):
    from supermarkt.models import LoadResult

    class Region:
        last_error = ""
        last_regions = regions
        def detect(self, _code):
            return regions[0] if len(regions) == 1 else "auto"
    class Aldi:
        def load(self, name):
            return LoadResult([_offer(name)], [])
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = Region()
    loader.official_aldi = Aldi()
    result = loader.load("80331", "auto", retailers=selected)
    assert result["unavailable_retailers"] == missing


def test_confirmed_irma_absence_is_not_a_failed_source_or_aggregator_fallback():
    from supermarkt.sources.aktiv_irma import NoLocalMarketOffers

    class Irma:
        def load(self, _code):
            return NoLocalMarketOffers()
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = type("Region", (), {"last_error": ""})()
    loader.official_aktiv_irma = Irma()
    result = loader.load("80331", "auto", retailers=("aktiv & irma",))
    assert result["offers"] == []
    assert result["unavailable_retailers"] == ["aktiv & irma"]
    assert result["source_states"]["aktiv & irma"] == "kein Markt"
    assert not result["request_errors"]


def test_unresolved_aldi_region_does_not_claim_confirmed_absence():
    from supermarkt.models import ToolError
    class Region:
        last_error = "lookup failed"
        last_regions = ()
        def detect(self, _code):
            return "auto"
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = Region()
    with pytest.raises(ToolError, match="Keine Supermarktangebote"):
        loader.load("80331", "auto", retailers=("ALDI Süd",))


@pytest.mark.parametrize("retailer", ["famila Nordwest", "Combi"])
def test_successful_empty_regional_catalogue_is_not_a_load_failure(retailer):
    from supermarkt.compare import OfferMapper
    from types import SimpleNamespace
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = SimpleNamespace(last_error="")
    loader.marktguru = SimpleNamespace(load_offers=lambda _code: ([], []), load_retailer_queries=lambda _code, _names: ([], []))
    loader.mapper = OfferMapper()
    result = loader.load("80331", "auto", retailers=(retailer,))
    assert result["offers"] == []
    assert result["request_errors"] == []
    assert result["unavailable_retailers"] == []  # No store absence was proven.


def test_failed_optional_source_keeps_its_diagnostic_and_is_not_market_absence():
    from supermarkt.compare import OfferMapper
    from supermarkt.models import ToolError
    from types import SimpleNamespace

    def failed(_code):
        raise ToolError("Marktkauf HTTP 503")
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = SimpleNamespace(last_error="")
    loader.official_marktkauf = SimpleNamespace(load=failed)
    loader.marktguru = SimpleNamespace(load_offers=lambda _code: ([], []), load_retailer_queries=lambda _code, _names: ([], []))
    loader.mapper = OfferMapper()
    with pytest.raises(ToolError, match="Marktkauf.*HTTP 503"):
        loader.load("80331", "auto", retailers=("Marktkauf",))
