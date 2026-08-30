from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .models import LoyaltyBenefit, Offer


@dataclass(frozen=True)
class LoyaltyProgram:
    id: str
    label: str
    retailers: tuple[str, ...]
    note: str


PROGRAMS: tuple[LoyaltyProgram, ...] = (
    LoyaltyProgram(
        "rewe_bonus",
        "REWE Bonus",
        ("REWE",),
        "Öffentlich ausgewiesenes Bonus-Guthaben wird als Euro-Vorteil berücksichtigt.",
    ),
    LoyaltyProgram(
        "lidl_plus",
        "Lidl Plus",
        ("Lidl",),
        "Öffentlich ausgewiesene Lidl-Plus- oder App-Preise werden berücksichtigt. Punkte und persönliche Coupons werden nicht geschätzt.",
    ),
    LoyaltyProgram(
        "penny_app",
        "PENNY App",
        ("PENNY",),
        "Öffentlich ausgewiesene App-Preise werden berücksichtigt. Persönliche Coupons zählen nur mit konkretem öffentlich sichtbarem Preis.",
    ),
    LoyaltyProgram(
        "netto_plus",
        "Netto plus App",
        ("Netto Marken-Discount",),
        "Öffentlich ausgewiesene App-Preise werden berücksichtigt. PAYBACK wird getrennt ausgewählt.",
    ),
    LoyaltyProgram(
        "netto_scottie_plus",
        "Netto+ (Netto schwarz)",
        ("Netto schwarz",),
        "Nur öffentlich ausgewiesene Netto+-Mitgliederpreise werden berücksichtigt; persönliche Coupons werden nicht geschätzt.",
    ),
    LoyaltyProgram(
        "kaufland_xtra",
        "Kaufland Card XTRA",
        ("Kaufland",),
        "Öffentlich ausgewiesene XTRA-Preise werden berücksichtigt. Treuepunkte werden nicht pauschal in Euro umgerechnet.",
    ),
    LoyaltyProgram(
        "edeka_app",
        "EDEKA App",
        ("EDEKA",),
        "Öffentliche App-Preise werden berücksichtigt, wenn die Angebotsquelle einen konkreten Preis nennt. Genuss+-Statusvorteile ohne konkreten Produktwert werden nicht geschätzt.",
    ),
    LoyaltyProgram(
        "marktkauf_app",
        "MARKTKAUF App",
        ("Marktkauf",),
        "Öffentliche App-Deals werden berücksichtigt, wenn die Angebotsquelle einen konkreten Preis nennt.",
    ),
    LoyaltyProgram(
        "mein_globus",
        "mein GLOBUS",
        ("Globus",),
        "Öffentlich ausgewiesene mein-GLOBUS-Preise werden berücksichtigt.",
    ),
    LoyaltyProgram(
        "payback",
        "PAYBACK",
        ("EDEKA", "Marktkauf", "Netto Marken-Discount", "Globus"),
        "Punkte und persönliche PAYBACK-Coupons werden nicht pauschal in Euro umgerechnet. Nur konkret ausgewiesene Preisvorteile zählen.",
    ),
    LoyaltyProgram(
        "rossmann_app",
        "ROSSMANN-App",
        ("Rossmann",),
        "Prozent- und persönliche Coupons werden angezeigt, aber ohne konkreten resultierenden Produktpreis nicht in den Preisvergleich eingerechnet.",
    ),
    LoyaltyProgram(
        "mueller_blueten",
        "Müller Blüten",
        ("Müller",),
        "Blüten und persönliche Coupons werden nicht pauschal auf einzelne Online-Angebote umgelegt.",
    ),
)

PROGRAM_BY_ID = {program.id: program for program in PROGRAMS}
VALID_PROGRAM_IDS = frozenset(PROGRAM_BY_ID)

_RETAILER_DEFAULT_PROGRAM = {
    "Lidl": "lidl_plus",
    "PENNY": "penny_app",
    "Netto Marken-Discount": "netto_plus",
    "Netto schwarz": "netto_scottie_plus",
    "Kaufland": "kaufland_xtra",
    "EDEKA": "edeka_app",
    "Marktkauf": "marktkauf_app",
    "Globus": "mein_globus",
    "Rossmann": "rossmann_app",
    "Müller": "mueller_blueten",
}


def normalize_program_ids(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        program_id = str(value or "").strip().casefold()
        if not program_id or program_id not in VALID_PROGRAM_IDS or program_id in normalized:
            continue
        normalized.append(program_id)
    return tuple(normalized)


def program_for_condition(retailer: str, condition: str) -> str:
    folded = str(condition or "").casefold()
    if "payback" in folded:
        return "payback"
    if "kaufland" in folded or "xtra" in folded:
        return "kaufland_xtra"
    if "lidl" in folded:
        return "lidl_plus"
    if "penny" in folded:
        return "penny_app"
    if "netto" in folded:
        return _RETAILER_DEFAULT_PROGRAM.get(retailer, "")
    if "globus" in folded:
        return "mein_globus"
    if "edeka" in folded or "genuss" in folded:
        return "edeka_app"
    if "marktkauf" in folded:
        return "marktkauf_app"
    return _RETAILER_DEFAULT_PROGRAM.get(retailer, "")


def available_programs(
    retailer_counts: dict[str, int],
    offers: Iterable[Offer] = (),
) -> list[dict[str, object]]:
    active_retailers = {
        name for name, count in retailer_counts.items()
        if int(count or 0) > 0
    }
    priced_counts = {program.id: 0 for program in PROGRAMS}
    for offer in offers:
        for benefit in offer.benefits:
            if benefit.program_id in priced_counts:
                priced_counts[benefit.program_id] += 1

    result: list[dict[str, object]] = []
    for program in PROGRAMS:
        if not active_retailers.intersection(program.retailers):
            continue
        item = asdict(program)
        item["priced_offer_count"] = priced_counts[program.id]
        result.append(item)
    return result


def apply_selected_programs(
    offer: Offer,
    selected_programs: Iterable[str],
) -> tuple[float | None, float | None, float, tuple[LoyaltyBenefit, ...]]:
    selected = set(normalize_program_ids(selected_programs))
    regular = offer.price
    applicable = tuple(
        benefit for benefit in offer.benefits
        if benefit.program_id in selected
    )
    direct_prices = [
        benefit.value
        for benefit in applicable
        if benefit.kind == "direct_price" and benefit.value > 0
    ]
    if regular is None:
        # A published membership price may exist without a safely identifiable
        # regular price. Show it only when selected, without inventing savings.
        checkout = min(direct_prices) if direct_prices else None
        return checkout, checkout, 0.0, applicable
    checkout = min([regular, *direct_prices]) if direct_prices else regular

    # Cashback is credited to an account after checkout. It is not a lower
    # product price and must not participate in price or unit-price ranking.
    effective = checkout
    savings = max(0.0, regular - effective)
    return checkout, effective, savings, applicable


def parse_public_loyalty_prices(
    description: str,
    regular_price: float | None,
    retailer: str,
) -> tuple[LoyaltyBenefit, ...]:
    """Extract concrete public loyalty prices from offer text.

    This parser deliberately ignores point balances, percentage coupons without a
    concrete resulting price, and personalized offers. REWE cashback is parsed by
    the REWE source because its Euro badge is a reward, not a checkout price.
    """
    import re

    from .common import clean_text, parse_number

    conditions = (
        r"lidl\s*plus(?:[- ]?preis)?",
        r"penny\s*app(?:[- ]?preis)?",
        r"netto\s*plus(?:[- ]?preis)?",
        r"kaufland\s*card(?:\s*xtra)?",
        r"xtra[- ]?preis",
        r"mein\s*globus(?:[- ]?preis)?",
        r"edeka\s*app(?:[- ]?preis)?",
        r"marktkauf\s*app(?:[- ]?preis)?",
        r"payback(?:[- ]?preis)?",
        r"app[- ]?preis",
        r"club[- ]?preis",
        r"bonus[- ]?preis",
    )
    condition_pattern = "(?:" + "|".join(conditions) + ")"
    patterns = (
        rf"(\d+[,.]\d{{2}})\s*€?\s*({condition_pattern})",
        rf"({condition_pattern})[^\d]{{0,24}}(\d+[,.]\d{{2}})",
    )

    found: dict[tuple[str, str], LoyaltyBenefit] = {}
    if retailer == "Netto Marken-Discount":
        advantage = re.search(
            r"(\d+[,.]\d{2})\s*€\s*netto\s*plus\s*(?:vorteil|guthaben|gutschrift)",
            description,
            flags=re.IGNORECASE,
        )
        if advantage:
            value = parse_number(advantage.group(1))
            if value and value > 0:
                found[("netto_plus", "cashback")] = LoyaltyBenefit(
                    "netto_plus", "cashback", float(value), clean_text(advantage.group(0))
                )
    for index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, description, flags=re.IGNORECASE):
            price_text, condition = (
                (match.group(1), match.group(2))
                if index == 0
                else (match.group(2), match.group(1))
            )
            price = parse_number(price_text)
            if price is None or price <= 0:
                continue
            if regular_price is not None and price > regular_price:
                continue
            program_id = program_for_condition(retailer, condition)
            if not program_id:
                continue
            nearby = description[max(0, match.start() - 10):match.end() + 20]
            if program_id == "netto_plus" and re.search(r"vorteil|guthaben|gutschrift", nearby, re.I):
                continue
            key = (program_id, "direct_price")
            benefit = LoyaltyBenefit(
                program_id=program_id,
                kind="direct_price",
                value=float(price),
                condition=clean_text(condition),
            )
            previous = found.get(key)
            if previous is None or benefit.value < previous.value:
                found[key] = benefit
    return tuple(found.values())


def benefit_label(benefit: LoyaltyBenefit) -> str:
    program = PROGRAM_BY_ID.get(benefit.program_id)
    return program.label if program else benefit.program_id
