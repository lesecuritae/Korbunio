"""Combi and famila Nordwest, the two Bünting brands served by Marktguru."""

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
        "brand": {"name": "Kerrygold"},
        "product": {"name": "Original Irische Butter"},
        "description": "250 g",
        "price": 1.59,
        "referencePrice": 6.36,
        "unit": {"shortName": "kg"},
        "categories": [{"name": "Molkereiprodukte"}],
        "validityDates": [{"from": "2020-01-01T00:00:00Z", "to": "2999-12-31T23:59:00Z"}],
    }


def test_buenting_brands_are_registered_as_optional_aggregator_retailers():
    for name in ("Combi", "famila Nordwest"):
        spec = SPEC_BY_NAME[name]
        # Bünting only sells in north-western Germany, so most postal codes
        # legitimately return nothing and must not raise a source error.
        assert spec.optional is True
        assert name in AGGREGATOR_RETAILERS
        assert name in MARKTGURU_RETAILER_SLUGS


def test_every_aggregator_retailer_has_a_marktguru_source_link():
    assert AGGREGATOR_RETAILERS <= set(MARKTGURU_RETAILER_SLUGS)


def test_combi_offer_is_mapped_with_marktguru_source_link():
    offer = OfferMapper().map_one(_raw("Combi"), _contexts())
    assert offer is not None
    assert offer.retailer == "Combi"
    assert offer.price == 1.59
    assert offer.source_url == "https://www.marktguru.de/r/combi"


def test_famila_nordwest_offer_is_mapped_with_marktguru_source_link():
    offer = OfferMapper().map_one(_raw("famila-Nordwest"), _contexts())
    assert offer is not None
    assert offer.retailer == "famila Nordwest"
    assert offer.source_url == "https://www.marktguru.de/r/famila-nordwest"


def test_famila_nordost_is_not_treated_as_the_buenting_brand():
    # famila Nordost belongs to a different, unrelated retail group.
    assert OfferMapper().map_one(_raw("famila Nordost"), _contexts()) is None


def test_buenting_offers_do_not_claim_loyalty_benefits():
    contexts = _contexts()
    for advertiser in ("Combi", "famila-Nordwest"):
        offer = OfferMapper().map_one(_raw(advertiser), contexts)
        assert offer is not None
        assert offer.benefits == ()


def test_marktguru_explicit_deposit_reaches_the_offer_model():
    raw = _raw("Netto")
    raw["description"] = "je 0,33-l-Dose zzgl. 0.25 Pfand"
    offer = OfferMapper().map_one(raw, _contexts())
    assert offer is not None
    assert offer.deposit == 0.25
