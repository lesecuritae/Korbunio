from __future__ import annotations

import html
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlsplit

from .config import BERLIN
from .images import is_rejected_image_url, normalize_image_url
from .models import Offer, RetailerContext

def validate_postal_code(value: Any) -> Optional[str]:
    postal_code = clean_text(value)
    return postal_code if re.fullmatch(r"\d{5}", postal_code) else None


def parse_deposit_text(value: Any, *, container_count: Optional[int] = None) -> Optional[float]:
    """Return the explicitly published total deposit for one sales unit.

    ``container_count`` is supplied only when the source explicitly identifies
    a multipack. Package shape alone is never used to invent a deposit.
    """
    text = clean_text(value)
    total_patterns = (
        r"\b(?:gesamtpfand|pfand\s*gesamt)\s*:?\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*€?",
        r"(?:zzgl\.?|zuz(?:ü|ue)glich|\+)\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*€?\s*pfand\s*/\s*(?:kiste|kasten)\b",
        r"\bpfand\s*/\s*(?:kiste|kasten)\s*:?\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*€?",
    )
    for pattern in total_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return parse_number(match.group(1))

    crate_patterns = (
        r"\b(?:kasten|kisten|crate)[- ]?pfand\s*:?\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*€?",
        r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€?\s*(?:kasten|kisten|crate)[- ]?pfand\b",
    )
    bottle_patterns = (
        r"\b(?:flaschen|dosen)[- ]?pfand\s*(?:je\s*)?(\d{1,4}(?:[.,]\d{1,2})?)\s*€?",
        r"\bpfand\s*(?:je\s*)?(?:flasche|dose)\s*:?\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*€?",
    )
    crate = next(
        (parse_number(match.group(1)) for pattern in crate_patterns if (match := re.search(pattern, text, flags=re.IGNORECASE))),
        None,
    )
    bottle = next(
        (parse_number(match.group(1)) for pattern in bottle_patterns if (match := re.search(pattern, text, flags=re.IGNORECASE))),
        None,
    )
    if crate is not None:
        bottles_total = (bottle or 0.0) * max(1, int(container_count or 1))
        return round(crate + bottles_total, 2)

    patterns = (
        r"(?:zzgl\.?|zuz(?:ü|ue)glich|\+)\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*€?\s*pfand\b",
        r"\bpfand(?:\s*/\s*\w+)?\s*(?:je\s*)?(\d{1,4}(?:[.,]\d{1,2})?)\s*€?",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            amount = parse_number(match.group(1))
            if amount is not None and container_count:
                return round(amount * max(1, int(container_count)), 2)
            return amount
    if bottle is not None:
        return round(bottle * max(1, int(container_count or 1)), 2)
    return None


def parse_deposit_components(value: Any, *, container_count: Optional[int] = None) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return total, per-container and packaging deposit when explicitly known."""
    text = clean_text(value)
    total = parse_deposit_text(text, container_count=container_count)
    crate_match = re.search(
        r"\b(?:kasten|kisten|crate)[- ]?pfand\s*:?\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*€?",
        text,
        flags=re.IGNORECASE,
    )
    bottle_match = re.search(
        r"\b(?:flaschen|dosen)[- ]?pfand\s*(?:je\s*)?(\d{1,4}(?:[.,]\d{1,2})?)\s*€?",
        text,
        flags=re.IGNORECASE,
    )
    packaging = parse_number(crate_match.group(1)) if crate_match else None
    per_container = parse_number(bottle_match.group(1)) if bottle_match else None
    if total is not None and container_count and packaging is None and per_container is None and not re.search(r"pfand\s*/\s*(?:kiste|kasten)", text, flags=re.IGNORECASE):
        generic = re.search(
            r"(?:zzgl\.?|zuz(?:ü|ue)glich|\+)\s*(?:pfand\s*)?(\d{1,4}(?:[.,]\d{1,2})?)\s*€?(?:\s*pfand\b)?",
            text,
            flags=re.IGNORECASE,
        )
        if generic:
            per_container = parse_number(generic.group(1))
    return total, per_container, packaging

def normalize_aldi_region(value: Any) -> str:
    normalized = clean_text(value).casefold().replace("ü", "ue")
    if normalized in {"both", "beide", "nord und sued", "nord & sued"}:
        return "both"
    if normalized in {"nord", "aldi nord", "north"}:
        return "nord"
    if normalized in {"sued", "sud", "aldi sued", "aldi sud", "south"}:
        return "sued"
    return "auto"

def normalize_view(value: Any) -> str:
    return "all" if clean_text(value).casefold() in {"all", "alle", "comparison", "vergleich"} else "best_only"

def filter_offers(offers: Iterable[Offer], filter_text: str) -> list[Offer]:
    query = clean_text(filter_text).casefold()
    if not query:
        return list(offers)
    return [
        offer
        for offer in offers
        if query
        in f"{offer.name} {offer.brand} {offer.description} {offer.category} {offer.retailer}".casefold()
    ]


def normalize_keywords(values: Iterable[Any], limit: int = 50) -> tuple[str, ...]:
    """Clean user keywords case-insensitively while preserving their spelling."""
    unique: dict[str, str] = {}
    for value in values:
        keyword = clean_text(value)[:80]
        if keyword:
            unique.setdefault(keyword.casefold(), keyword)
        if len(unique) >= limit:
            break
    return tuple(unique.values())


def filter_offers_by_keywords(offers: Iterable[Offer], keywords: Iterable[Any]) -> list[Offer]:
    """Match product names using OR semantics; no keywords means no filtering."""
    normalized = tuple(keyword.casefold() for keyword in normalize_keywords(keywords))
    if not normalized:
        return list(offers)
    return [offer for offer in offers if any(keyword in offer.name.casefold() for keyword in normalized)]

def today_berlin() -> date:
    return datetime.now(BERLIN).date()


def offer_reference_date(day: Optional[date] = None) -> date:
    """Return the weekly-offer reference date used by retailer adapters.

    On Sundays the old week has ended while the coming week's offers are
    already published by several retailers. Treat Sunday as the following
    Monday so every source consistently selects the upcoming offer week.
    """
    current = day or today_berlin()
    return current + timedelta(days=1) if current.weekday() == 6 else current


def offer_week_reference(value: Any, day: Optional[date] = None) -> date:
    reference = offer_reference_date(day)
    return reference + timedelta(days=7) if clean_text(value).casefold() == "next" else reference


def normalize_offer_week(value: Any) -> str:
    return "next" if clean_text(value).casefold() in {"next", "folge", "folgewoche"} else "current"

def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

def clean_brand(value: Any) -> str:
    """Return a usable brand name and discard source placeholder values."""
    text = clean_text(value)
    folded = re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", text.casefold()))
    folded = " ".join(folded.split())
    placeholders = {
        "this is no brand",
        "thisisnobrand",
        "no brand",
        "without brand",
        "unbranded",
        "brandless",
        "ohne marke",
        "keine marke",
        "markenlos",
    }
    compact = folded.replace(" ", "")
    if folded in placeholders or re.fullmatch(r"thisisnobrand\d*", compact):
        return ""
    return text

def strip_html(value: Any) -> str:
    return clean_text(html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))))

def clean_description(value: Any) -> str:
    return clean_text(re.sub(r"~twx[a-z0-9_]*~", " ", str(value or ""), flags=re.IGNORECASE))

def parse_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            value = value.replace("€", "").replace(" ", "").replace(",", ".")
        return float(value)
    except (TypeError, ValueError):
        return None

def format_euro(value: Any) -> str:
    number = parse_number(value)
    return "–" if number is None else f"{number:.2f} €".replace(".", ",")

def parse_iso_date(value: Any) -> Optional[date]:
    text = clean_text(value)
    if not text:
        return None
    try:
        if "T" in text:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.astimezone(BERLIN).date() if parsed.tzinfo else parsed.date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None

def offer_validity(
    raw_offer: dict[str, Any],
    reference_date: Optional[date] = None,
) -> tuple[bool, str]:
    periods = raw_offer.get("validityDates")
    if not isinstance(periods, list) or not periods:
        return False, "Gültigkeit fehlt"

    current = False
    labels: list[str] = []
    today = offer_reference_date(reference_date)
    for period in periods:
        if not isinstance(period, dict):
            continue
        start = parse_iso_date(period.get("from"))
        end = parse_iso_date(period.get("to"))
        if start and end:
            labels.append(f"{start:%d.%m.}–{end:%d.%m.%Y}")
            current = current or start <= today <= end
        elif start:
            labels.append(f"ab {start:%d.%m.%Y}")
            current = current or start <= today
        elif end:
            labels.append(f"bis {end:%d.%m.%Y}")
            current = current or today <= end
    return (current if labels else False), ", ".join(dict.fromkeys(labels)) or "Gültigkeit fehlt"

def ascii_words(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(
        r"\b(?:versch(?:iedene)?|sorten|sorte|je|packung|flasche|dose|beutel|aktion|angebot)\b",
        " ",
        normalized,
    )
    normalized = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*[-–]?\s*(?:kilogramm|milliliter|gramm|liter|"
        r"waschladungen?|portionen?|anwendungen?|kg|g|l|ml|cl|stück|stk|wl|tabs?|caps?|pods?)\b",
        " ",
        normalized,
    )
    return re.findall(r"[a-z0-9]+", normalized)

def identity_words(brand: str, name: str) -> list[str]:
    brand_words = ascii_words(brand)
    name_words = ascii_words(name)
    return name_words if brand_words and name_words[: len(brand_words)] == brand_words else brand_words + name_words

def normalize_pack(value: str) -> str:
    # Grundpreis-Angaben sind keine zweite Packungsgröße. Beispiele:
    # "0,33-l-Dose (1 l = 1.19)" oder "150-g-Becher (1 kg = 3,27 €)".
    # Die komplette Klammer fliegt vor der Packungserkennung raus.
    value = re.sub(
        r"\(\s*(?:grundpreis\s*)?(?:1\s*(?:kg|kilogramm|l|liter)|"
        r"100\s*(?:g|gramm|ml|milliliter)|1\s*(?:stk\.?|stück|portion|anwendung))"
        r"\s*=\s*[^)]*\)",
        " ",
        value,
        flags=re.IGNORECASE,
    )

    unit_pattern = (
        r"waschladungen?|wäschen?|portionen?|anwendungen?|kilogramm|milliliter|"
        r"kapseln?|gramm|liter|caps?|pods?|tabs?|kg|ml|cl|g|l|wl|stück|stk\.?|rollen?|blatt"
    )

    # A source range such as "85-100 g" is one ambiguous package choice, not
    # two packages that should be added together. Keep the range explicit so
    # no synthetic unit price is calculated from either endpoint.
    range_match = re.search(
        rf"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*[-–]?\s*({unit_pattern})\b",
        value,
        flags=re.IGNORECASE,
    )
    if range_match:
        low = float(range_match.group(1).replace(",", "."))
        high = float(range_match.group(2).replace(",", "."))
        low, low_unit = normalize_pack_unit(low, range_match.group(3))
        high, high_unit = normalize_pack_unit(high, range_match.group(3))
        if low_unit == high_unit:
            low_text = str(int(low)) if low.is_integer() else f"{low:.3f}".rstrip("0").rstrip(".")
            high_text = str(int(high)) if high.is_integer() else f"{high:.3f}".rstrip("0").rstrip(".")
            return f"{low_text}-{high_text}{low_unit}"

    pattern = re.compile(
        rf"(?:(\d+)\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*[-–]?\s*({unit_pattern})\b",
        flags=re.IGNORECASE,
    )

    entries: list[tuple[str, int, int, str]] = []
    multipack_components: set[str] = set()
    for match in pattern.finditer(value):
        multiplier_text, amount_text, unit_text = match.groups()
        multiplier = int(multiplier_text or "1")
        amount = float(amount_text.replace(",", "."))
        amount, unit = normalize_pack_unit(amount, unit_text)
        formatted = str(int(amount)) if amount.is_integer() else f"{amount:.3f}".rstrip("0").rstrip(".")
        component = f"{formatted}{unit}"
        if multiplier > 1:
            multipack_components.add(component)
            entries = [entry for entry in entries if entry[0] != component]
            label = f"{multiplier}x{component}"
        else:
            if component in multipack_components:
                continue
            label = component
        if not any(existing[0] == label for existing in entries):
            entries.append((label, match.start(), match.end(), unit))

    if not entries:
        return ""
    labels = [entry[0] for entry in entries[:4]]
    if len(labels) == 1:
        return labels[0]

    selected = entries[:4]
    separators = [
        value[selected[index][2]:selected[index + 1][1]]
        for index in range(len(selected) - 1)
    ]
    # Only preserve '+' when the source explicitly says that the package
    # components are added together. Otherwise several sizes mean alternatives.
    explicit_combo = bool(separators) and all(
        "+" in separator
        and not re.search(r"\b(?:oder|bzw\.?|bis)\b|/", separator, flags=re.IGNORECASE)
        for separator in separators
    )
    return ("+" if explicit_combo else "/").join(labels)

def normalize_pack_unit(amount: float, unit_text: str) -> tuple[float, str]:
    unit = unit_text.casefold().rstrip(".")
    if unit in {"kg", "kilogramm"}:
        return amount * 1000, "g"
    if unit in {"l", "liter"}:
        return amount * 1000, "ml"
    if unit == "milliliter":
        return amount, "ml"
    if unit == "cl":
        return amount * 10, "ml"
    if unit == "gramm":
        return amount, "g"
    if unit.startswith("stück") or unit == "stk":
        return amount, "stk"
    if unit.startswith("rolle"):
        return amount, "rollen"
    if unit == "blatt":
        return amount, "blatt"
    if unit.startswith(("tab", "cap", "pod", "kapsel", "waschladung", "wäsche", "portion", "anwendung")) or unit == "wl":
        return amount, "portion"
    return amount, unit

def build_match_key(brand: str, name: str, pack: str, unique_suffix: str) -> str:
    if not pack:
        return f"unique:{unique_suffix}"
    words = identity_words(brand, name)
    identity = " ".join(words)
    safe_identity = bool(brand) or len(set(words)) >= 2
    return f"{identity}|{pack}" if identity and safe_identity else f"unique:{unique_suffix}"

def advertiser_labels(raw_offer: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    advertisers = raw_offer.get("advertisers")
    if not isinstance(advertisers, list):
        return labels
    for advertiser in advertisers:
        if not isinstance(advertiser, dict):
            continue
        for field in ("uniqueName", "name", "slug"):
            text = clean_text(advertiser.get(field)).casefold()
            if text and text not in labels:
                labels.append(text)
    return labels

def identify_retailer(
    raw_offer: dict[str, Any],
    retailers: dict[str, RetailerContext],
) -> Optional[str]:
    labels = " | ".join(advertiser_labels(raw_offer))
    if not labels:
        return None
    for name, context in retailers.items():
        if any(alias in labels for alias in context.excluded_aliases):
            continue
        if any(alias in labels for alias in context.aliases):
            return name
    return None

def normalize_base_unit(value: str) -> str:
    unit = clean_text(value).casefold().replace(".", "")
    if unit in {"l", "liter", "ltr"}:
        return "l"
    if unit in {"kg", "kilogramm"}:
        return "kg"
    if unit in {"wl", "waschladung", "waschladungen", "portion", "portionen", "tab", "tabs", "cap", "caps", "pod", "pods", "anwendung", "anwendungen"}:
        return "portion"
    if unit in {"stk", "stück", "stueck"}:
        return "stk"
    if unit in {"rolle", "rollen"}:
        return "rollen"
    if unit in {"blatt", "blätter", "blaetter"}:
        return "blatt"
    return ""

def pack_metric(pack: str) -> Optional[tuple[float, str]]:
    if not pack or "+" in pack:
        return None
    match = re.fullmatch(r"(?:(\d+)x)?(\d+(?:\.\d+)?)(g|ml|portion|stk|rollen|blatt)", pack)
    if not match:
        return None
    multiplier = float(match.group(1) or "1")
    amount = float(match.group(2)) * multiplier
    unit = match.group(3)
    if amount <= 0:
        return None
    if unit == "ml":
        return amount / 1000, "l"
    if unit == "g":
        return amount / 1000, "kg"
    return amount, unit

def calculate_unit_price(
    offer: Offer,
    total_price: Optional[float],
) -> Optional[tuple[float, str, bool]]:
    metric = pack_metric(offer.pack_signature)
    if metric is None or total_price is None:
        return None
    quantity, unit = metric
    calculated = total_price / quantity
    api_unit = normalize_base_unit(offer.base_unit)
    uses_regular_price = offer.price is not None and abs(total_price - offer.price) < 0.005
    if uses_regular_price and offer.base_price is not None and api_unit == unit and offer.base_price > 0:
        return offer.base_price, unit, False
    return calculated, unit, True

def format_unit_price(value: Optional[float], unit: str) -> str:
    labels = {
        "l": "l",
        "kg": "kg",
        "portion": "Portion",
        "stk": "Stück",
        "rollen": "Rolle",
        "blatt": "Blatt",
    }
    return "–" if value is None else f"{format_euro(value)}/{labels.get(unit, unit)}"

def format_pack(pack: str) -> str:
    def one(value: str) -> str:
        range_match = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)(g|ml|portion|stk|rollen|blatt)", value)
        if range_match:
            low, high, unit = range_match.groups()
            unit_label = {"portion": "Portionen", "stk": "Stück", "rollen": "Rollen", "blatt": "Blatt"}.get(unit, unit)
            return f"{low.replace('.', ',')}–{high.replace('.', ',')} {unit_label}"

        match = re.fullmatch(r"(?:(\d+)x)?(\d+(?:\.\d+)?)(g|ml|portion|stk|rollen|blatt)", value)
        if not match:
            return value
        multiplier, amount_text, unit = match.groups()
        amount = float(amount_text)
        if not multiplier and unit == "ml" and amount >= 1000:
            return f"{amount / 1000:g} l".replace(".", ",")
        if not multiplier and unit == "g" and amount >= 1000:
            return f"{amount / 1000:g} kg".replace(".", ",")
        amount_label = str(int(amount)) if amount.is_integer() else str(amount).replace(".", ",")
        unit_label = {"portion": "Portionen", "stk": "Stück", "rollen": "Rollen", "blatt": "Blatt"}.get(unit, unit)
        return f"{multiplier} × {amount_label} {unit_label}" if multiplier else f"{amount_label} {unit_label}"

    if not pack:
        return ""
    if "/" in pack:
        return " / ".join(one(part) for part in pack.split("/") if part)
    if "+" in pack:
        return " + ".join(one(part) for part in pack.split("+") if part)
    return one(pack)

def date_is_current(
    start: Optional[date],
    end: Optional[date],
    reference_date: Optional[date] = None,
) -> bool:
    today = offer_reference_date(reference_date)
    if start is not None and today < start:
        return False
    if end is not None and today > end:
        return False
    return True

def format_validity(start: Optional[date], end: Optional[date]) -> str:
    if start and end:
        return f"{start:%d.%m.} – {end:%d.%m.%Y}"
    if start:
        return f"ab {start:%d.%m.%Y}"
    if end:
        return f"bis {end:%d.%m.%Y}"
    return "Aktuell"

def deduplicate_offers(offers: Iterable[Offer]) -> list[Offer]:
    unique: dict[tuple[Any, ...], Offer] = {}
    for offer in offers:
        benefits = tuple((benefit.program_id, benefit.kind, benefit.value) for benefit in offer.benefits)
        if offer.retailer == "ALDI Süd":
            try:
                source_host = (urlsplit(offer.source_url).hostname or "").casefold()
            except ValueError:
                source_host = ""
            identity = (offer.retailer, offer.offer_id, offer.price, offer.pack_signature, benefits, source_host)
            vague = offer.validity_label.casefold() in {"aktuell", "aktuelle woche", "aktuelle angebotsseite"}
            competing = [key for key in unique if key[:6] == identity]
            if competing:
                precise = next((key for key in competing if key[6] is False), None)
                if vague and precise is not None:
                    continue
                if not vague:
                    same_period = next(
                        (
                            key for key in competing
                            if key[6] is False
                            and key[7][:2] == (offer.valid_from or "", offer.valid_until or "")
                        ),
                        None,
                    )
                    if same_period is not None:
                        existing_specific = unique[same_period].validity_label.casefold().startswith("nur ")
                        incoming_specific = offer.validity_label.casefold().startswith("nur ")
                        if not incoming_specific or existing_specific:
                            continue
                        del unique[same_period]
                    for key in competing:
                        if key in unique and key[6] is True:
                            del unique[key]
            period = (offer.valid_from or "", offer.valid_until or "", offer.validity_label.casefold())
            key = identity + (vague, period)
            unique.setdefault(key, offer)
            continue
        key = (
            offer.retailer,
            offer.match_key,
            offer.price,
            benefits,
            offer.validity_label,
        )
        unique.setdefault(key, offer)
    return list(unique.values())

def _coerce_image_url(value: Any, base_url: str = "", path_hint: str = "") -> str:
    candidate = normalize_image_url(value, base_url=base_url)
    if candidate:
        return candidate
    if isinstance(value, (dict, list)):
        return ""
    text = clean_text(value)
    hint = clean_text(path_hint).casefold()
    if not base_url or not text or text.startswith(("data:", "javascript:", "#")):
        return ""
    imageish = bool(re.search(r"\.(?:avif|webp|png|jpe?g)(?:$|[?#])", text, flags=re.IGNORECASE))
    imageish = imageish or any(token in hint for token in ("image", "img", "picture", "photo", "media", "asset", "bild"))
    if not imageish:
        return ""
    return normalize_image_url(urljoin(base_url, text))

def _image_candidate_score(url: str, path_hint: str = "") -> int:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return -1000
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "").casefold()
    hint = clean_text(path_hint).casefold()
    if not host or is_rejected_image_url(url):
        return -1000

    score = 0
    if re.search(r"\.(?:avif|webp|png|jpe?g)(?:$|[?#])", url, flags=re.IGNORECASE):
        score += 100
    if any(token in host for token in ("cdn", "img", "image", "media", "asset", "static")):
        score += 65
    if any(token in path for token in ("/image", "/img", "/media", "/asset", "/content/", "/bilder", "/bild")):
        score += 45
    if any(token in hint for token in ("image", "img", "picture", "photo", "media", "asset", "bild")):
        score += 45
    if "aldi" in host:
        score += 20
    if any(token in path for token in ("/produkt/", "/product/", "/angebote", "/offers", "/filiale", "/markt")):
        score -= 100
    if path.endswith((".html", ".htm")):
        score -= 100
    return score

def _nested_image_url(value: Any, path_hint: str = "", base_url: str = "") -> str:
    candidates: list[tuple[int, str]] = []

    def visit(node: Any, hint: str) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                child_hint = f"{hint}.{key}" if hint else str(key)
                visit(item, child_hint)
            return
        if isinstance(node, list):
            for item in node:
                visit(item, hint)
            return
        candidate = _coerce_image_url(node, base_url=base_url, path_hint=hint)
        if not candidate:
            return
        score = _image_candidate_score(candidate, hint)
        if score >= 60:
            candidates.append((score, candidate))

    visit(value, path_hint)
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return candidates[0][1]

def _marktguru_offer_image_url(value: Any, base_url: str = "") -> str:
    """Resolve Marktguru offer images even when the API only returns image metadata."""
    if not isinstance(value, dict):
        return ""
    if clean_text(value.get("imageType")).casefold() != "offer":
        return ""
    images = value.get("images")
    if not isinstance(images, dict):
        return ""

    urls = images.get("urls")
    if isinstance(urls, dict):
        for size in ("large", "medium", "small"):
            candidate = _coerce_image_url(urls.get(size), base_url=base_url, path_hint=f"images.urls.{size}")
            if candidate and not is_rejected_image_url(candidate):
                return candidate

    try:
        image_count = int(images.get("count") or 0)
    except (TypeError, ValueError):
        image_count = 0
    offer_id = clean_text(value.get("id"))
    if image_count > 0 and offer_id.isdigit():
        return f"https://mg2de.b-cdn.net/api/v1/offers/{offer_id}/images/default/0/medium.jpg"
    return ""


def extract_image_url(value: Any, base_url: str = "") -> str:
    marktguru = _marktguru_offer_image_url(value, base_url=base_url)
    if marktguru:
        return marktguru

    preferred_fields = (
        "thumbnailUrl", "thumbnailURL", "thumbnail_url", "thumbnail",
        "imageUrl", "imageURL", "image_url", "productImageUrl", "productImage",
        "mainImage", "image", "images", "picture", "photo", "contentUrl",
        "bild_app", "bild_web130", "bild_web90",
    )
    if isinstance(value, dict):
        for field in preferred_fields:
            if field in value:
                candidate = _coerce_image_url(value.get(field), base_url=base_url, path_hint=field)
                if candidate and not is_rejected_image_url(candidate):
                    return candidate
        for key, item in value.items():
            key_text = str(key).casefold()
            if any(token in key_text for token in ("thumbnail", "image", "picture", "photo", "media", "asset", "bild")):
                candidate = _coerce_image_url(item, base_url=base_url, path_hint=str(key))
                if candidate and not is_rejected_image_url(candidate):
                    return candidate
        for item in value.values():
            if isinstance(item, (dict, list)):
                candidate = extract_image_url(item, base_url=base_url)
                if candidate:
                    return candidate
    elif isinstance(value, list):
        for item in value:
            candidate = extract_image_url(item, base_url=base_url)
            if candidate:
                return candidate

    # Manche Händler legen Bild-URLs in neutral benannten Asset-/Variant-Listen ab.
    # In diesem Fallback werden ausschließlich klar bildähnliche URLs akzeptiert.
    return _nested_image_url(value, base_url=base_url)

def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)

def first_text(value: dict[str, Any], fields: Iterable[str]) -> str:
    for field in fields:
        candidate = value.get(field)
        if isinstance(candidate, str) and clean_text(candidate):
            return clean_text(candidate)
    return ""

def first_number(value: dict[str, Any], fields: Iterable[str]) -> Optional[float]:
    for field in fields:
        candidate = value.get(field)
        if isinstance(candidate, dict):
            nested = first_number(candidate, ("value", "amount", "price"))
            if nested is not None:
                return nested
        else:
            parsed = parse_number(candidate)
            if parsed is not None:
                return parsed
    return None

def first_date(value: dict[str, Any], fields: Iterable[str]) -> Optional[date]:
    for field in fields:
        parsed = parse_iso_date(value.get(field))
        if parsed is not None:
            return parsed
    return None

def normalize_heading(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()

def heading_index(headers: list[str], names: Iterable[str]) -> Optional[int]:
    normalized_names = [normalize_heading(name) for name in names]
    for index, header in enumerate(headers):
        if any(name == header or name in header for name in normalized_names):
            return index
    return None

def identify_retailer_text(value: Any, retailers: dict[str, RetailerContext]) -> Optional[str]:
    label = clean_text(value).casefold()
    if not label:
        return None
    for name, context in retailers.items():
        if any(alias in label for alias in context.excluded_aliases):
            continue
        if any(alias in label for alias in context.aliases):
            return name
    return None

def parse_price_text(value: Any) -> Optional[float]:
    text = clean_text(value)
    match = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{1,2})?)\s*€", text)
    if match:
        return parse_number(match.group(1))
    return parse_number(text)

def parse_base_price_text(value: Any) -> tuple[Optional[float], str]:
    text = clean_text(value)
    match = re.search(
        r"(?:1\s*)?(kg|kilogramm|l|liter|wl|waschladungen?|stück|stueck|stk\.?)\s*=\s*(\d+(?:[.,]\d{1,2})?)"
        r"|(?<!\d)(\d+(?:[.,]\d{1,2})?)\s*(?:€\s*)?[/]\s*(?:1\s*)?(kg|kilogramm|l|liter|wl|waschladungen?|stück|stueck|stk\.?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, ""
    if match.group(1):
        unit_text, price_text = match.group(1), match.group(2)
    else:
        price_text, unit_text = match.group(3), match.group(4)
    return parse_number(price_text), normalize_base_unit(unit_text)

def flatten_json_text(value: Any, limit: int = 5000) -> str:
    parts: list[str] = []

    def walk(item: Any) -> None:
        if sum(len(part) for part in parts) >= limit:
            return
        if isinstance(item, str):
            text = clean_text(item)
            if text:
                parts.append(text)
        elif isinstance(item, dict):
            for nested in item.values():
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)

    walk(value)
    return " | ".join(parts)[:limit]

def find_marktguru_keys(value: Any) -> tuple[Optional[str], Optional[str]]:
    api_key: Optional[str] = None
    client_key: Optional[str] = None

    def walk(item: Any) -> None:
        nonlocal api_key, client_key
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = str(key).replace("-", "_").casefold()
                if normalized in {"apikey", "api_key", "x_apikey", "x_api_key"} and isinstance(nested, str):
                    api_key = nested or api_key
                if normalized in {"clientkey", "client_key", "x_clientkey", "x_client_key"} and isinstance(nested, str):
                    client_key = nested or client_key
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)

    walk(value)
    return api_key, client_key

def first_regex_group(value: str, patterns: Iterable[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, value, re.IGNORECASE)
        if match:
            return match.group(1)
    return None
