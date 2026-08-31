from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .common import clean_text

CATEGORIES = (
    "Obst & Gemüse", "Fleisch & Wurst", "Fisch & Meeresfrüchte",
    "Molkereiprodukte & Eier", "Backwaren", "Kühlprodukte",
    "Tiefkühl / Eis & Dessert", "Vorräte & Grundnahrungsmittel",
    "Konserven & Fertiggerichte", "Frühstück & Brotaufstriche", "Getränke",
    "Snacks", "Drogerie & Körperpflege",
    "Haushalt & Reinigung", "Tierbedarf", "Baby & Kind",
    "Wohnen, Freizeit & Non-Food", "Weitere Angebote",
)

# Concrete product kinds precede terms which can merely describe a flavour.
_PRODUCT_RULES = (
    ("Tiefkühl / Eis & Dessert", r"\b(?:ice cream|eiscreme|speiseeis|stieleis|wassereis|gelato|calippo|pirulo|dessert|mousse|\w*eis)\b"),
    ("Haushalt & Reinigung", r"\b(?:bodenkehrer|kehrmaschine|besen|wischmopp|staubsauger|wc reiniger|\w*reiniger|grillanzuender|grillanzünder)\b"),
    ("Tierbedarf", r"\b(?:katzenfutter|hundefutter|katzenstreu|tierzubehoer|tierzubehör|tierfutter)\b"),
    ("Snacks", r"\b(?:pom bär|pom baer|chips|flips|knabber\w*|snacks?|smarties|chocolate|schokolade)\b"),
    ("Backwaren", r"\b(?:brot|\w*broetchen|\w*brötchen|kuchen|croissant|breze\w*|pain au chocolat|gebaeck|gebäck)\b"),
    ("Getränke", r"\b(?:cola|limonade|wasser|\w*saft|bier|wein|spirituose|kaffee|tee)\b"),
    ("Obst & Gemüse", r"\b(?:obst|gemuese|gemüse|salat|rucola|kartoffel\w*|tomat\w*|apfel|banane\w*)\b"),
    ("Fleisch & Wurst", r"\b(?:fleisch|wurst|schinken|salami|gefluegel|geflügel|hackfleisch)\b"),
    ("Fisch & Meeresfrüchte", r"\b(?:fisch|lachs|thunfisch|meeresfr\w*|garnele\w*)\b"),
    ("Molkereiprodukte & Eier", r"\b(?:milch|kaese|käse|joghurt|quark|butter|eier?)\b"),
    ("Konserven & Fertiggerichte", r"\b(?:konserve|fertiggericht|instant|suppe)\b"),
    ("Frühstück & Brotaufstriche", r"\b(?:marmelade|honig|muesli|müsli|cerealien|brotaufstrich)\b"),
    ("Drogerie & Körperpflege", r"\b(?:koerperpflege|körperpflege|hygiene|kosmetik|shampoo)\b"),
    ("Baby & Kind", r"\b(?:baby|windel\w*)\b"),
    ("Vorräte & Grundnahrungsmittel", r"\b(?:nudeln?|reis|mehl|zucker|gewuerz|gewürz|backzutat)\b"),
)

_SOURCE_RULES = (
    ("Obst & Gemüse", r"obst|gemuese|gemüse|salat|(?<!meeres)frucht|(?<!meeres)fruechte|(?<!meeres)früchte|beere|zitrus|melone"),
    ("Fleisch & Wurst", r"fleisch|wurst|wuerst|würst|gefluegel|geflügel|steak|schnitzel"),
    ("Fisch & Meeresfrüchte", r"fisch|meeresfr"),
    ("Molkereiprodukte & Eier", r"molkerei|milch|kaese|käse|eier|sahne|schmand"),
    ("Tiefkühl / Eis & Dessert", r"tiefkuehl|tiefkühl|tk\b|eiscreme|speiseeis|dessert|\beis\b"),
    ("Backwaren", r"backwaren|baeck|bäck|brot"),
    ("Kühlprodukte", r"kuehl|kühl|frische convenience|feinkost"),
    ("Konserven & Fertiggerichte", r"konserve|fertiggericht|instant"),
    ("Frühstück & Brotaufstriche", r"fruehst|frühst|brotaufstrich|muesli|müsli|cerealien"),
    ("Getränke", r"getraenk|getränk|bier|wein|spirituose|wasser\b|saft|limonade|softdrink|cocktail|sekt|prosecco|likoer|likör|schnaps|whisk|aperitif"),
    ("Snacks", r"\bsnacks?\b|chips|knabber|flips"),
    ("Snacks", r"suess|süss|schokolade|keks|bonbon"),
    ("Drogerie & Körperpflege", r"drogerie|koerper|körper|pflege|hygiene|kosmetik"),
    ("Haushalt & Reinigung", r"haushalt|reinig|waschmittel|spuel|spül|papier|putz"),
    ("Tierbedarf", r"tier|hund|katze|haustier"),
    ("Baby & Kind", r"baby|kind|windel"),
    ("Wohnen, Freizeit & Non-Food", r"non.?food|wohnen|freizeit|garten|textil|mode|technik|werkzeug|spielzeug|pflanze|blume|topf|toepfe|töpfe|aufbewahr|behaelter|behälter|kuechenzubehoer|küchenzubehör|kuechengeraet|küchengerät|geschirr|dekoration|sport|filtersystem"),
    ("Vorräte & Grundnahrungsmittel", r"vorrat|grundnahr|nudel|reis|mehl|zucker|oel|öl|gewuerz|gewürz|backzutat|\bdip|mayonnaise|senf|ketchup"),
)


@dataclass(frozen=True)
class CategoryDecision:
    category: str
    source_category: str
    detected_category: str
    category_conflict: bool


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    return re.sub(r"[^\wäöüß]+", " ", value).strip()


def _first_match(value: str, rules: tuple[tuple[str, str], ...]) -> str:
    folded = _fold(value)
    if not folded:
        return ""
    for canonical, pattern in rules:
        if re.search(pattern, folded):
            return canonical
    return ""


def _source_category(value: str) -> str:
    source = _fold(value)
    if not source:
        return "Weitere Angebote"
    for canonical in CATEGORIES:
        if source == _fold(canonical):
            return canonical
    if source == _fold("Tiefkühlkost"):
        return "Tiefkühl / Eis & Dessert"
    for canonical, pattern in _SOURCE_RULES:
        if re.search(pattern, source):
            return canonical
    return "Weitere Angebote"


def category_decision(source_category: str, retailer: str = "", name: str = "", description: str = "", brand: str = "") -> CategoryDecision:
    del retailer  # Reserved for retailer-specific source mappings.
    source = _source_category(source_category)
    # Do not concatenate fields: this preserves name > brand > description.
    detected = _first_match(name, _PRODUCT_RULES) or _first_match(brand, _PRODUCT_RULES) or _first_match(description, _PRODUCT_RULES)
    category = detected or source
    conflict = bool(detected and source != "Weitere Angebote" and detected != source)
    return CategoryDecision(category, clean_text(source_category), detected, conflict)


def normalize_category(source_category: str, retailer: str = "", name: str = "", description: str = "", brand: str = "") -> str:
    return category_decision(source_category, retailer, name, description, brand).category
