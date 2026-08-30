from supermarkt.models import AGGREGATOR_RETAILERS, RETAILER_SPECS
from supermarkt.service import SourceLoader


def test_marktguru_scope_is_minimal():
    assert AGGREGATOR_RETAILERS == {"Lidl", "PENNY", "Netto Marken-Discount", "Globus", "Combi", "famila Nordwest"}
    assert not {"ALDI Nord", "ALDI Süd", "REWE", "EDEKA", "Marktkauf", "Kaufland"} & AGGREGATOR_RETAILERS


def test_all_expected_retailers_exist():
    names = {spec.name for spec in RETAILER_SPECS}
    assert {
        "REWE", "EDEKA", "Marktkauf", "ALDI Nord", "ALDI Süd", "Kaufland",
        "Lidl", "PENNY", "Netto Marken-Discount", "Globus", "Combi", "famila Nordwest",
        "Netto schwarz", "Rossmann", "Müller",
    } <= names


def test_contexts_have_no_implicit_postal_code():
    contexts = SourceLoader._contexts()
    assert contexts
    assert all(context.market_label == name for name, context in contexts.items())


def test_zero_hit_retailers_are_not_exposed_as_filter_chips():
    from dataclasses import asdict
    from supermarkt.compare import OfferComparator
    from supermarkt.models import Offer
    from supermarkt.service import SupermarketEngine

    contexts = SourceLoader._contexts()
    offer = Offer(
        offer_id="test",
        retailer="Lidl",
        category="Test",
        name="Testprodukt",
        brand="",
        description="",
        price=1.0,
        base_price=None,
        base_unit="",
        pack_signature="",
        validity_label="Aktuell",
        match_key="unique:test",
        source_url="https://www.lidl.de/",
        image_url="https://example.org/test.jpg",
    )
    engine = object.__new__(SupermarketEngine)
    engine.comparator = OfferComparator()
    snapshot = {
        "search_id": "synthetic",
        "postal_code": "01067",
        "offers": [asdict(offer)],
        "retailers": {name: asdict(value) for name, value in contexts.items()},
        "source_states": {},
        "request_errors": [],
        "store_warnings": [],
        "created_at": 0,
    }

    page = engine.page(snapshot, view="all", include_image_urls=True)
    assert page["retailer_counts"] == {"Lidl": 1}


def test_multiple_retailer_filters_keep_only_selected_retailers():
    from dataclasses import asdict
    from supermarkt.compare import OfferComparator
    from supermarkt.models import Offer
    from supermarkt.service import SupermarketEngine

    contexts = SourceLoader._contexts()
    offers = [Offer(
        offer_id=name, retailer=name, category="Test", name=f"Produkt {name}", brand="",
        description="", price=1.0, base_price=None, base_unit="", pack_signature="",
        validity_label="Aktuell", match_key=f"unique:{name}", source_url="https://example.invalid/",
    ) for name in ("Lidl", "PENNY", "REWE")]
    engine = object.__new__(SupermarketEngine)
    engine.comparator = OfferComparator()
    snapshot = {
        "search_id": "multi-retailer", "postal_code": "01067",
        "offers": [asdict(offer) for offer in offers],
        "retailers": {name: asdict(value) for name, value in contexts.items()},
        "source_states": {}, "request_errors": [], "store_warnings": [], "created_at": 0,
    }

    page = engine.page(snapshot, retailer_filters=("Lidl", "PENNY"), view="all")

    assert page["retailers"] == ["Lidl", "PENNY"]
    assert {offer["retailer"] for offer in page["offers"]} == {"Lidl", "PENNY"}
    assert page["filtered_offer_count"] == 2


def test_results_expose_selected_market_labels_for_retailers_with_offers():
    from dataclasses import asdict, replace
    from supermarkt.compare import OfferComparator
    from supermarkt.models import Offer
    from supermarkt.service import SupermarketEngine

    contexts = SourceLoader._contexts()
    contexts["REWE"] = replace(
        contexts["REWE"],
        market_label="REWE Markt – Hauptstr. 1, 12345 Teststadt",
        market_url="https://www.rewe.de/angebote/teststadt/100/rewe-markt-hauptstrasse/",
    )
    offer = Offer(
        offer_id="rewe-test", retailer="REWE", category="Test", name="Testprodukt",
        brand="", description="", price=1.0, base_price=None, base_unit="",
        pack_signature="", validity_label="Aktuell", match_key="unique:rewe",
        source_url="https://www.rewe.de/",
    )
    engine = object.__new__(SupermarketEngine)
    engine.comparator = OfferComparator()
    snapshot = {
        "search_id": "market-label", "postal_code": "12345",
        "offers": [asdict(offer)],
        "retailers": {name: asdict(value) for name, value in contexts.items()},
        "source_states": {}, "request_errors": [], "store_warnings": [], "created_at": 0,
    }

    page = engine.page(snapshot, view="all")
    assert page["retailer_markets"] == [{
        "retailer": "REWE",
        "label": "REWE Markt – Hauptstr. 1, 12345 Teststadt",
        "url": "https://www.rewe.de/angebote/teststadt/100/rewe-markt-hauptstrasse/",
    }]


def test_direct_source_failure_uses_target_week_marktguru_fallback(monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    from supermarkt.compare import OfferMapper
    from supermarkt.models import ToolError

    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 9))

    def raw(retailer, offer_id):
        return {
            "id": offer_id,
            "advertisers": [{"name": retailer, "uniqueName": retailer.casefold().replace(" ", "-")}],
            "validityDates": [{"from": "2026-08-10", "to": "2026-08-15"}],
            "product": {"name": f"Produkt {retailer}", "description": "500 g"},
            "categories": [{"name": "Test"}],
            "price": 1.99,
            "unit": {"shortName": "kg"},
        }

    raws = [
        raw("Lidl", 1),
        raw("PENNY", 2),
        raw("Netto Marken-Discount", 3),
        raw("REWE", 4),
        raw("EDEKA", 5),
        raw("Kaufland", 6),
        raw("ALDI Nord", 7),
    ]

    class Marktguru:
        def load_offers(self, postal_code):
            return raws, []

        def load_retailer_queries(self, postal_code, retailer_names):
            wanted = {name.casefold() for name in retailer_names}
            selected = []
            for item in raws:
                labels = " ".join(
                    str(advertiser.get("name") or advertiser.get("uniqueName") or "")
                    for advertiser in item.get("advertisers", [])
                    if isinstance(advertiser, dict)
                ).casefold()
                if any(name in labels for name in wanted):
                    selected.append(item)
            return selected, []


    class FailedOfficial:
        last_market_url = ""
        last_market_label = ""
        last_store_url = ""
        last_locality = ""

        def load(self, *args, **kwargs):
            raise ToolError("synthetic failure")

    class AldiRegion:
        last_error = ""
        def detect(self, postal_code):
            return "nord"

    class FailedAldi:
        def load(self, *args, **kwargs):
            return SimpleNamespace(offers=[])

    loader = SourceLoader.__new__(SourceLoader)
    loader.marktguru = Marktguru()
    loader.mapper = OfferMapper()
    loader.aldi_region = AldiRegion()
    loader.official_rewe = FailedOfficial()
    loader.official_edeka = FailedOfficial()
    loader.official_marktkauf = FailedOfficial()
    loader.official_kaufland = FailedOfficial()
    loader.official_aldi = FailedAldi()

    result = loader.load("12345", "nord")
    retailers = {offer["retailer"] for offer in result["offers"]}
    assert {"Lidl", "PENNY", "Netto Marken-Discount", "REWE", "EDEKA", "Kaufland", "ALDI Nord"} <= retailers
    assert result["source_states"]["REWE"] == "Marktguru-Fallback"
    assert result["source_states"]["Kaufland"] == "Marktguru-Fallback"


def test_partial_broad_marktguru_result_is_completed_by_retailer_queries(monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    from supermarkt.compare import OfferMapper
    from supermarkt.models import ToolError

    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 9))

    def raw(retailer, offer_id, name):
        return {
            "id": offer_id,
            "advertisers": [{"name": retailer, "uniqueName": retailer.casefold().replace(" ", "-")}],
            "validityDates": [{"from": "2026-08-10", "to": "2026-08-15"}],
            "product": {"name": name, "description": "500 g"},
            "categories": [{"name": "Test"}],
            "price": 1.99,
            "unit": {"shortName": "kg"},
        }

    broad = [raw("Lidl", 1, "Breitensuche Lidl")]
    targeted = [
        raw("Lidl", 2, "Händlerabfrage Lidl"),
        raw("PENNY", 3, "Händlerabfrage PENNY"),
        raw("Netto Marken-Discount", 4, "Händlerabfrage Netto"),
    ]

    class Marktguru:
        def __init__(self):
            self.queries = []

        def load_offers(self, postal_code):
            assert postal_code == "12345"
            return broad, []

        def load_retailer_queries(self, postal_code, retailer_names):
            self.queries.append(tuple(retailer_names))
            wanted = {name.casefold() for name in retailer_names}
            selected = []
            for item in targeted:
                labels = " ".join(
                    str(advertiser.get("name") or advertiser.get("uniqueName") or "")
                    for advertiser in item.get("advertisers", [])
                ).casefold()
                if any(name in labels for name in wanted):
                    selected.append(item)
            return selected, []

    class FailedOfficial:
        last_market_url = ""
        last_market_label = ""
        last_store_url = ""
        last_locality = ""

        def load(self, *args, **kwargs):
            raise ToolError("synthetic failure")

    class AldiRegion:
        last_error = ""

        def detect(self, postal_code):
            return ""

    marketguru = Marktguru()
    loader = SourceLoader.__new__(SourceLoader)
    loader.marktguru = marketguru
    loader.mapper = OfferMapper()
    loader.aldi_region = AldiRegion()
    loader.official_rewe = FailedOfficial()
    loader.official_edeka = FailedOfficial()
    loader.official_marktkauf = FailedOfficial()
    loader.official_kaufland = FailedOfficial()
    loader.official_aldi = SimpleNamespace(load=lambda *args, **kwargs: SimpleNamespace(offers=[]))

    result = loader.load("12345", "auto")
    counts = {}
    for offer in result["offers"]:
        counts[offer["retailer"]] = counts.get(offer["retailer"], 0) + 1

    assert counts["Lidl"] == 2
    assert counts["PENNY"] == 1
    assert counts["Netto Marken-Discount"] == 1
    assert marketguru.queries
    queried = set(marketguru.queries[0])
    assert {"Lidl", "PENNY", "Netto Marken-Discount", "REWE", "EDEKA", "Kaufland"} <= queried
    assert "Globus" not in queried


def test_official_catalogue_wins_over_marktguru_for_direct_retailer(monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    from supermarkt.compare import OfferMapper
    from supermarkt.models import Offer

    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 9))

    def raw_rewe():
        return {
            "id": 10,
            "advertisers": [{"name": "REWE", "uniqueName": "rewe"}],
            "validityDates": [{"from": "2026-08-10", "to": "2026-08-16"}],
            "product": {"name": "Marktguru REWE", "description": "500 g"},
            "categories": [{"name": "Test"}],
            "price": 9.99,
        }

    official = Offer(
        offer_id="rewe:official", retailer="REWE", category="Test",
        name="Offizielles REWE", brand="", description="", price=1.99,
        base_price=None, base_unit="", pack_signature="",
        validity_label="10.08.–16.08.2026", match_key="official:rewe",
        source_url="https://www.rewe.de/", image_url="",
    )

    class Marktguru:
        def load_offers(self, postal_code):
            return [raw_rewe()], []
        def load_retailer_queries(self, postal_code, retailer_names):
            return [raw_rewe()], []

    class Rewe:
        last_market_url = "https://www.rewe.de/angebote/test"
        last_market_label = "REWE Test"
        def load(self, postal_code):
            return [official]

    class EmptyOfficial:
        last_market_url = ""
        last_market_label = ""
        last_store_url = ""
        last_locality = ""
        def load(self, *args, **kwargs):
            return []

    class AldiRegion:
        last_error = ""
        def detect(self, postal_code):
            return ""

    loader = SourceLoader.__new__(SourceLoader)
    loader.marktguru = Marktguru()
    loader.mapper = OfferMapper()
    loader.aldi_region = AldiRegion()
    loader.official_rewe = Rewe()
    loader.official_edeka = EmptyOfficial()
    loader.official_marktkauf = EmptyOfficial()
    loader.official_kaufland = EmptyOfficial()
    loader.official_aldi = SimpleNamespace(load=lambda *args, **kwargs: SimpleNamespace(offers=[], request_errors=[]))

    result = loader.load("12345", "auto")
    rewe = [item for item in result["offers"] if item["retailer"] == "REWE"]
    assert [item["name"] for item in rewe] == ["Offizielles REWE"]
    assert result["source_states"]["REWE"] == "offiziell"


def test_marktguru_is_not_mixed_into_successful_kaufland_catalogue(monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    from supermarkt.compare import OfferMapper
    from supermarkt.models import Offer

    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 9))

    official = Offer(
        offer_id="k:1", retailer="Kaufland", category="Test", name="Kaufland offiziell",
        brand="", description="", price=1.0, base_price=None, base_unit="",
        pack_signature="", validity_label="06.08.–12.08.2026", match_key="k:official",
        source_url="https://filiale.kaufland.de/", image_url="",
    )
    raw = {
        "id": 99, "advertisers": [{"name": "Kaufland", "uniqueName": "kaufland"}],
        "validityDates": [{"from": "2026-08-06", "to": "2026-08-12"}],
        "product": {"name": "Kaufland Aggregator"}, "categories": [{"name": "Test"}],
        "price": 2.0,
    }

    class Marktguru:
        def load_offers(self, postal_code): return [raw], []
        def load_retailer_queries(self, postal_code, retailer_names): return [raw], []

    class Kaufland:
        last_store_url = "https://filiale.kaufland.de/test"
        last_locality = "Test"
        def load(self, postal_code): return [official]

    class EmptyOfficial:
        last_market_url = ""
        last_market_label = ""
        last_store_url = ""
        last_locality = ""
        def load(self, *args, **kwargs): return []

    class AldiRegion:
        last_error = ""
        def detect(self, postal_code): return ""

    loader = SourceLoader.__new__(SourceLoader)
    loader.marktguru = Marktguru()
    loader.mapper = OfferMapper()
    loader.aldi_region = AldiRegion()
    loader.official_rewe = EmptyOfficial()
    loader.official_edeka = EmptyOfficial()
    loader.official_marktkauf = EmptyOfficial()
    loader.official_kaufland = Kaufland()
    loader.official_aldi = SimpleNamespace(load=lambda *args, **kwargs: SimpleNamespace(offers=[], request_errors=[]))

    result = loader.load("12345", "auto")
    kaufland = [item for item in result["offers"] if item["retailer"] == "Kaufland"]
    assert [item["name"] for item in kaufland] == ["Kaufland offiziell"]
    assert result["source_states"]["Kaufland"] == "offiziell"


def test_hidden_duplicate_count_respects_selected_retailer_and_view():
    from dataclasses import asdict
    from supermarkt.compare import OfferComparator
    from supermarkt.models import Offer
    from supermarkt.service import SupermarketEngine

    contexts = SourceLoader._contexts()
    offers = [
        Offer(
            offer_id="lidl-expensive",
            retailer="Lidl",
            category="Test",
            name="Milch",
            brand="",
            description="1 l",
            price=1.49,
            base_price=None,
            base_unit="",
            pack_signature="1000ml",
            validity_label="Aktuell",
            match_key="milk-1l",
            source_url="https://www.lidl.de/",
        ),
        Offer(
            offer_id="penny-best",
            retailer="PENNY",
            category="Test",
            name="Milch",
            brand="",
            description="1 l",
            price=0.99,
            base_price=None,
            base_unit="",
            pack_signature="1000ml",
            validity_label="Aktuell",
            match_key="milk-1l",
            source_url="https://www.penny.de/",
        ),
    ]
    engine = object.__new__(SupermarketEngine)
    engine.comparator = OfferComparator()
    snapshot = {
        "search_id": "duplicates",
        "postal_code": "01067",
        "offers": [asdict(offer) for offer in offers],
        "retailers": {name: asdict(value) for name, value in contexts.items()},
        "source_states": {},
        "request_errors": [],
        "store_warnings": [],
        "created_at": 0,
    }

    best = engine.page(snapshot, retailer="Lidl", view="best_only")
    assert best["filtered_offer_count"] == 0
    assert best["hidden_count"] == 1
    assert best["view"] == "best_only"

    all_offers = engine.page(snapshot, retailer="Lidl", view="all")
    assert all_offers["filtered_offer_count"] == 1
    assert all_offers["hidden_count"] == 1
    assert all_offers["view"] == "all"
