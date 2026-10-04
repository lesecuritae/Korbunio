"""Regional Combi (Bünting group) offers served by Marktguru."""

from supermarkt.compare import MARKTGURU_RETAILER_SLUGS, OfferMapper
from supermarkt.models import AGGREGATOR_RETAILERS, RETAILER_SPECS, SPEC_BY_NAME, RetailerContext


def _contexts() -> dict[str, RetailerContext]:
    return {
        spec.name: RetailerContext(
            name=spec.name,
            aliases=tuple(alias.casefold() for alias in spec.aliases),
            excluded_aliases=tuple(alias.casefold() for alias in spec.excluded_aliases),
            color=spec.color,
            market_label=spec.name,
            market_url=spec.fallback_url,
        )
        for spec in RETAILER_SPECS
    }


def _raw(advertiser: str, offer_id: int = 1) -> dict:
    return {
        "id": offer_id,
        "advertisers": [{"name": advertiser}],
        "brand": {"name": "Rama"},
        "product": {"name": "mit Butter"},
        "description": "225 g",
        "price": 1.29,
        "referencePrice": 5.73,
        "unit": {"shortName": "kg"},
        "categories": [{"name": "Molkereiprodukte"}],
        "validityDates": [{"from": "2020-01-01T00:00:00Z", "to": "2999-12-31T23:59:00Z"}],
    }


def test_combi_is_registered_as_an_optional_aggregator_retailer():
    spec = SPEC_BY_NAME["Combi"]
    assert spec.optional is True
    assert spec.name in AGGREGATOR_RETAILERS
    assert spec.name in MARKTGURU_RETAILER_SLUGS


def test_every_aggregator_retailer_has_a_marktguru_source_link():
    assert AGGREGATOR_RETAILERS <= set(MARKTGURU_RETAILER_SLUGS)


def test_combi_offer_is_mapped_with_marktguru_source_link():
    offer = OfferMapper().map_one(_raw("Combi"), _contexts())
    assert offer is not None
    assert offer.retailer == "Combi"
    assert offer.source_url == "https://www.marktguru.de/r/combi"
