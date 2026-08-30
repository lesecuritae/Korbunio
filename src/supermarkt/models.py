from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class RetailerSpec:
    name: str
    aliases: tuple[str, ...]
    color: str
    fallback_url: str
    optional: bool = False
    excluded_aliases: tuple[str, ...] = ()


RETAILER_SPECS: tuple[RetailerSpec, ...] = (
    RetailerSpec("REWE", ("rewe center", "rewe"), "#cc071e", "https://www.rewe.de/marktsuche"),
    RetailerSpec("ALDI Nord", ("aldi nord", "aldi-nord"), "#0095d9", "https://www.aldi-nord.de/angebote.html"),
    RetailerSpec("ALDI Süd", ("aldi süd", "aldi sued", "aldi-sued"), "#0050aa", "https://www.aldi-sued.de/angebote"),
    RetailerSpec("Lidl", ("lidl",), "#0050aa", "https://www.lidl.de/c/angebote/s10007591"),
    RetailerSpec("PENNY", ("penny",), "#cc001c", "https://www.penny.de/angebote"),
    RetailerSpec(
        "Netto Marken-Discount",
        ("netto marken-discount", "netto markendiscount", "netto-online", "netto"),
        "#f4c300",
        "https://www.netto-online.de/angebote/",
    ),
    RetailerSpec(
        "Netto schwarz",
        ("netto scottie", "netto mit scottie", "netto mit hund", "netto salling", "netto schwarz"),
        "#ffd500",
        "https://netto.de/marktsuche/",
        True,
        ("netto marken-discount", "netto markendiscount", "netto-online"),
    ),
    RetailerSpec("Kaufland", ("kaufland",), "#e10915", "https://filiale.kaufland.de/"),
    RetailerSpec("EDEKA", ("edeka",), "#f7c600", "https://www.edeka.de/marktsuche.jsp"),
    RetailerSpec("Marktkauf", ("marktkauf",), "#008c3a", "https://www.edeka.de/marktsuche.jsp", True),
    RetailerSpec(
        "Globus",
        ("globus markthalle", "globus"),
        "#0b7a3e",
        "https://www.globus.de/maerkte.php",
        True,
        ("globus baumarkt",),
    ),
    # Bünting group, regional in north-western Germany. Both are optional
    # because most German postal codes are outside their sales area.
    RetailerSpec("Combi", ("combi",), "#e2001a", "https://www.combi.de/kontakt/markt", True),
    RetailerSpec(
        "famila Nordwest",
        ("famila-nordwest", "famila nordwest"),
        "#004494",
        "https://www.famila-nordwest.de/unsere-maerkte/marktsuche",
        True,
        # famila Nordost is a different, unrelated retail group.
        ("famila-nordost", "famila nordost"),
    ),
    RetailerSpec("HOL’AB!", ("hol'ab", "hol’ab", "holab"), "#e30613", "https://holab.de/angebote", True),
    RetailerSpec("Rossmann", ("rossmann",), "#cf003d", "https://www.rossmann.de/de/filialen/index.html", True),
    RetailerSpec("Müller", ("mueller", "müller drogerie", "mueller drogerie"), "#e30613", "https://www.mueller.de/storefinder/", True),
)

SPEC_BY_NAME = {spec.name: spec for spec in RETAILER_SPECS}
AGGREGATOR_RETAILERS = frozenset({"Lidl", "PENNY", "Netto Marken-Discount", "Globus", "Combi", "famila Nordwest"})


def resolve_retailer_names(values: list[str] | tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return canonical retailer names and unknown inputs, preserving user order."""
    aliases = {
        alias.casefold(): spec.name
        for spec in RETAILER_SPECS
        for alias in (spec.name, *spec.aliases)
    }
    resolved: list[str] = []
    unknown: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        canonical = aliases.get(raw.casefold())
        if canonical is None:
            if raw not in unknown:
                unknown.append(raw)
        elif canonical not in resolved:
            resolved.append(canonical)
    return tuple(resolved), tuple(unknown)


@dataclass(frozen=True)
class RetailerContext:
    name: str
    aliases: tuple[str, ...]
    excluded_aliases: tuple[str, ...]
    color: str
    market_label: str
    market_url: str


@dataclass(frozen=True)
class LoyaltyBenefit:
    """A concrete monetary benefit exposed by a public offer source."""

    program_id: str
    kind: str  # direct_price or cashback
    value: float
    condition: str = ""


@dataclass
class Offer:
    offer_id: str
    retailer: str
    category: str
    name: str
    brand: str
    description: str
    price: Optional[float]
    base_price: Optional[float]
    base_unit: str
    pack_signature: str
    validity_label: str
    match_key: str
    source_url: str
    image_url: str = ""
    source_category: str = ""
    detected_category: str = ""
    category_conflict: bool = False
    product_url: str = ""
    retailer_url: str = ""
    deposit: Optional[float] = None
    container_deposit: Optional[float] = None
    packaging_deposit: Optional[float] = None
    minimum_quantity: Optional[int] = None
    offer_condition: str = ""
    comparison_eligible: bool = True
    coverage_note: str = ""
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    benefits: tuple[LoyaltyBenefit, ...] = ()

    # These fields are calculated for a request and are not part of source parsing.
    effective_price: Optional[float] = None
    checkout_price: Optional[float] = None
    loyalty_savings: float = 0.0
    applied_benefits: tuple[LoyaltyBenefit, ...] = ()
    regular_comparison_note: str = ""
    regular_comparison_state: str = "none"
    selected_comparison_note: str = ""
    selected_comparison_state: str = "none"


@dataclass(frozen=True)
class LoadResult:
    offers: list[Offer]
    request_errors: list[str]


@dataclass(frozen=True)
class ComparisonResult:
    offers: list[Offer]
    hidden_count: int


class ToolError(RuntimeError):
    pass


def offer_to_dict(offer: Offer) -> dict[str, Any]:
    return asdict(offer)


def _benefits_from_dict(value: Any) -> tuple[LoyaltyBenefit, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        item if isinstance(item, LoyaltyBenefit) else LoyaltyBenefit(**item)
        for item in value
        if isinstance(item, (dict, LoyaltyBenefit))
    )


def offer_from_dict(value: dict[str, Any]) -> Offer:
    fields = Offer.__dataclass_fields__
    payload = {name: value[name] for name in fields if name in value}
    payload["benefits"] = _benefits_from_dict(payload.get("benefits"))
    payload["applied_benefits"] = _benefits_from_dict(payload.get("applied_benefits"))
    return Offer(**payload)
