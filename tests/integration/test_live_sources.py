from __future__ import annotations

import os
import pytest

from supermarkt.config import TIMEOUT_SECONDS
from supermarkt.http import HttpClient, PostalCodeLocator
from supermarkt.region import AldiRegionResolver
from supermarkt.sources import OfficialAldiSource, OfficialEdekaSource, OfficialKauflandSource, OfficialMarktkaufSource, OfficialReweSource

pytestmark = pytest.mark.live


def enabled() -> bool:
    return os.getenv("RUN_LIVE_TESTS") == "1"


def require_live():
    if not enabled():
        pytest.skip("set RUN_LIVE_TESTS=1")


def test_rewe_live():
    require_live()
    postal = os.getenv("TEST_REWE_POSTAL_CODE", "10117")
    source = OfficialReweSource(PostalCodeLocator(HttpClient(TIMEOUT_SECONDS)), TIMEOUT_SECONDS)
    offers = source.load(postal)
    assert len(offers) >= 20
    assert all((o.price or 0) > 0 for o in offers)


def test_edeka_live():
    require_live()
    postal = os.getenv("TEST_EDEKA_POSTAL_CODE", "10179")
    offers = OfficialEdekaSource(TIMEOUT_SECONDS).load(postal)
    assert len(offers) >= 10
    assert all((o.price or 0) > 0 for o in offers)


def test_marktkauf_live():
    require_live()
    postal = os.getenv("TEST_MARKTKAUF_POSTAL_CODE", "33719")
    offers = OfficialMarktkaufSource(TIMEOUT_SECONDS).load(postal)
    assert len(offers) >= 10


def test_aldi_sources_live():
    require_live()
    source = OfficialAldiSource(HttpClient(TIMEOUT_SECONDS))
    for retailer in ("ALDI Nord", "ALDI Süd"):
        offers = source.load(retailer).offers
        assert len(offers) >= 50
        assert sum(bool(o.image_url) for o in offers) / len(offers) >= 0.9


def test_aldi_region_live():
    require_live()
    resolver = AldiRegionResolver(HttpClient(TIMEOUT_SECONDS))
    north = os.getenv("TEST_ALDI_NORTH_POSTAL_CODE", "01067")
    south = os.getenv("TEST_ALDI_SOUTH_POSTAL_CODE", "80331")
    assert resolver.detect(north) == "nord"
    assert resolver.detect(south) == "sued"


def test_kaufland_live():
    require_live()
    postal = os.getenv("TEST_KAUFLAND_POSTAL_CODE", "44791")
    http = HttpClient(TIMEOUT_SECONDS)
    offers = OfficialKauflandSource(http, PostalCodeLocator(http), TIMEOUT_SECONDS).load(postal)
    assert len(offers) >= 100
    assert sum(bool(o.image_url) for o in offers) / len(offers) >= 0.7


def test_marktguru_images_live(tmp_path):
    require_live()
    from supermarkt.compare import OfferMapper
    from supermarkt.images import ImageService
    from supermarkt.models import AGGREGATOR_RETAILERS
    from supermarkt.service import SourceLoader
    from supermarkt.sources import MarktguruClient

    postal = os.getenv("TEST_MARKTGURU_POSTAL_CODE", "01067")
    http = HttpClient(TIMEOUT_SECONDS)
    client = MarktguruClient(http, 500, 3)
    raw, _errors = client.load_offers(postal)
    targeted, _targeted_errors = client.load_retailer_queries(postal, ["Lidl", "PENNY", "Netto Marken-Discount"])
    raw.extend(targeted)
    contexts = SourceLoader._contexts()
    aggregator_contexts = {name: contexts[name] for name in AGGREGATOR_RETAILERS if name in contexts}
    offers = OfferMapper().map_all(raw, aggregator_contexts)
    service = ImageService(cache_dir=tmp_path, timeout_seconds=min(TIMEOUT_SECONDS, 30))

    for retailer in ("Lidl", "PENNY", "Netto Marken-Discount"):
        all_retailer_offers = [offer for offer in offers if offer.retailer == retailer]
        assert len(all_retailer_offers) >= 50, f"{retailer}: nur {len(all_retailer_offers)} aktuelle Angebote"
        retailer_offers = [offer for offer in all_retailer_offers if offer.image_url]
        assert retailer_offers, f"{retailer}: keine Bild-URL aus Marktguru"
        downloaded = False
        for offer in retailer_offers[:8]:
            try:
                result = service.get(
                    source_url=offer.image_url,
                    referer="https://www.marktguru.de/",
                    product=offer.name,
                    retailer=offer.retailer,
                )
            except Exception:
                continue
            if result.data and result.content_type.startswith("image/"):
                downloaded = True
                break
        assert downloaded, f"{retailer}: kein Bild konnte geladen werden"


def test_reference_postal_code_full_source_mix_live():
    """Optional full-source regression for a caller-supplied postcode."""
    require_live()
    postal = os.getenv("TEST_REFERENCE_POSTAL_CODE")
    if not postal:
        pytest.skip("set TEST_REFERENCE_POSTAL_CODE for the full-source regression")

    from collections import Counter
    from supermarkt.service import SourceLoader

    result = SourceLoader().load(postal, "auto")
    counts = Counter(item["retailer"] for item in result["offers"])

    assert counts["Lidl"] >= 50
    assert counts["PENNY"] >= 50
    assert counts["Netto Marken-Discount"] >= 50
    assert counts["REWE"] >= 10
    assert counts["EDEKA"] >= 10
    assert counts["Kaufland"] >= 10
