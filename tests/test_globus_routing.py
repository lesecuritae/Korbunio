from dataclasses import replace
from datetime import date
from types import SimpleNamespace

from supermarkt.compare import OfferMapper
from supermarkt.models import Offer, ToolError
from supermarkt.service import SourceLoader


def official_offer():
    return Offer(offer_id="globus:official", retailer="Globus", category="Test", name="Globus offiziell",
        brand="", description="500 g", price=1.99, base_price=3.98, base_unit="kg", pack_signature="500g",
        validity_label="24.08.–29.08.2026", match_key="globus-official", source_url="https://www.globus.de/")


def raw_marktguru():
    return {"id": 9, "advertisers": [{"name": "Globus", "uniqueName": "globus"}],
        "validityDates": [{"from": "2026-08-24", "to": "2026-08-29"}],
        "product": {"name": "Globus Marktguru", "description": "500 g"}, "categories": [{"name": "Test"}], "price": 2.99}


def matching_marktguru_image():
    return {"id": 4711, "imageType": "offer", "images": {"count": 1},
        "advertisers": [{"name": "Globus", "uniqueName": "globus"}],
        "validityDates": [{"from": "2026-08-24", "to": "2026-08-29"}],
        "product": {"name": "Globus offiziell", "description": "500 g"},
        "categories": [{"name": "Test"}], "price": 1.99}


class EmptyOfficial:
    last_market_url = last_market_label = last_store_url = last_locality = ""
    def load(self, *args): return []


class AldiRegion:
    last_error = ""
    def detect(self, postal_code): return ""


class Marktguru:
    def __init__(self, targeted=None): self.queries, self.targeted = [], targeted
    def load_offers(self, postal_code): return [raw_marktguru()], []
    def load_retailer_queries(self, postal_code, names):
        self.queries.append(set(names))
        return ([self.targeted or raw_marktguru()] if "Globus" in names else []), []


def loader(globus):
    value = SourceLoader.__new__(SourceLoader)
    value.marktguru, value.mapper, value.aldi_region = Marktguru(), OfferMapper(), AldiRegion()
    value.official_rewe = value.official_edeka = value.official_marktkauf = value.official_kaufland = EmptyOfficial()
    value.official_globus = globus
    value.official_aldi = SimpleNamespace(load=lambda *args: SimpleNamespace(offers=[], request_errors=[]))
    return value


def test_official_globus_wins_and_only_an_exact_marktguru_image_is_enriched(monkeypatch):
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 27))
    globus = SimpleNamespace(load=lambda postal: [official_offer()], last_market_url="https://www.globus.de/test", last_market_label="Globus Test")
    value = loader(globus)
    value.marktguru = Marktguru(matching_marktguru_image())
    result = value.load("65185", "auto")
    offers = [item for item in result["offers"] if item["retailer"] == "Globus"]
    assert [item["name"] for item in offers] == ["Globus offiziell"]
    assert offers[0]["price"] == 1.99
    assert offers[0]["source_url"] == "https://www.globus.de/"
    assert offers[0]["image_url"] == "https://mg2de.b-cdn.net/api/v1/offers/4711/images/default/0/medium.jpg"
    assert result["source_states"]["Globus"] == "offiziell + Marktguru-Bild"
    assert any("Globus" in names for names in value.marktguru.queries)


def test_kaufda_single_offer_image_enriches_official_globus_before_marktguru(monkeypatch):
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 27))
    market = SimpleNamespace(name="Teststadt")
    globus = SimpleNamespace(load=lambda postal: [official_offer()], last_market=market,
        last_market_url="https://www.globus.de/test", last_market_label="Globus Test")
    value = loader(globus)
    kaufda_image = replace(official_offer(), offer_id="kaufda:1", image_url="https://content-media.bonial.biz/one/main.jpg?impolicy=SEO-offer-normal")
    value.kaufda_globus_images = SimpleNamespace(load=lambda locality: [kaufda_image] if locality == "Teststadt" else [])

    result = value.load("65185", "auto")
    offer = next(item for item in result["offers"] if item["retailer"] == "Globus")

    assert offer["offer_id"] == "globus:official"
    assert offer["price"] == 1.99
    assert offer["source_url"] == "https://www.globus.de/"
    assert offer["image_url"] == kaufda_image.image_url
    assert result["source_states"]["Globus"] == "offiziell + KaufDA-Bild"
    assert all("Globus" not in names for names in value.marktguru.queries)


def test_marktguru_is_globus_fallback_on_error(monkeypatch):
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 27))
    class FailedGlobus:
        last_market_url = last_market_label = ""
        def load(self, postal): raise ToolError("offline")
    value = loader(FailedGlobus())
    result = value.load("65185", "auto")
    offers = [item for item in result["offers"] if item["retailer"] == "Globus"]
    assert [item["name"] for item in offers] == ["Globus Marktguru"]
    assert result["source_states"]["Globus"] == "Marktguru-Fallback"
    assert any("Globus" in names for names in value.marktguru.queries)


def test_marktguru_is_globus_fallback_on_empty(monkeypatch):
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: date(2026, 8, 27))
    value = loader(SimpleNamespace(load=lambda postal: [], last_market_url="", last_market_label=""))
    result = value.load("65185", "auto")
    assert result["source_states"]["Globus"] == "Marktguru-Fallback"


def test_globus_image_enrichment_rejects_ambiguous_or_price_mismatched_images():
    first = replace(official_offer(), offer_id="mg:1", image_url="https://example.test/one.jpg")
    second = replace(official_offer(), offer_id="mg:2", image_url="https://example.test/two.jpg")
    enriched, count = SourceLoader._enrich_globus_images([official_offer()], [first, second])
    assert count == 0 and enriched[0].image_url == ""

    wrong_price = replace(first, price=2.49)
    enriched, count = SourceLoader._enrich_globus_images([official_offer()], [wrong_price])
    assert count == 0 and enriched[0].image_url == ""
