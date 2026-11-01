"""Decide whether two offer titles describe the same article, for borrowing a product image from another retailer.

A comparable picture is better than none, but a wrong brand, flavour or Zero/regular variant is not a substitute.
Titles are reduced to their distinguishing words (brand + variant); pack sizes, units and filler words are dropped.
Nothing here knows any particular brand.
"""
from __future__ import annotations

import re
import unicodedata

# Words that carry no article identity. "energy"/"drink" etc. only name the category.
_GENERIC = frozenset({
    "energy", "drink", "drinks", "getraenk", "getraenke", "erfrischungsgetraenk", "erfrischungsgetraenke", "dose", "dosen",
    "einweg", "mehrweg", "flasche", "flaschen", "pet", "pack", "packung", "stuck", "stk", "st", "oder", "und", "mit", "ohne_pfand",
    "versch", "verschiedene", "sorten", "sorte", "je", "der", "die", "das", "von", "im", "in", "aus", "zzgl", "pfand", "ca", "original_preis",
})
_UNIT = r"(?:ml|cl|l|ltr|liter|g|gr|kg|mg|stk|st|x)"
_PACK = re.compile(rf"(?:\d+(?:[.,]\d+)?\s*[–-]\s*)?(?:\d+\s*[x×]\s*)?\d+(?:[.,]\d+)?\s*{_UNIT}\b|\b\d+\s*[x×]\s*\d+(?:[.,]\d+)?", re.IGNORECASE)


def _fold(text: str) -> str:
    text = text.casefold().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


_AMOUNT = re.compile(r"(?:(\d+)\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*(ml|cl|l|ltr|liter|g|gr|kg|mg)\b")
_FACTOR = {"ml": 1, "cl": 10, "l": 1000, "ltr": 1000, "liter": 1000, "g": 1, "gr": 1, "kg": 1000, "mg": 0.001}


def pack_signature(title: str) -> str:
    """Pack size in canonical form (count x millilitres/grams, e.g. '4x250', '500'); empty when none is found."""
    found = []
    for count, amount, unit in _AMOUNT.findall(_fold(title)):
        value = round(float(amount.replace(",", ".")) * _FACTOR[unit], 3)
        found.append((f"{count}x" if count else "") + f"{value:g}")
    return "|".join(sorted(found))


def identity_tokens(title: str, brand: str = "") -> frozenset[str]:
    text = _fold(f"{brand} {title}")
    text = _PACK.sub(" ", text)
    words = re.findall(r"[a-z0-9]+", text)
    # "ohne zucker" / "zero" stay: they are exactly the variant words that must NOT be dropped.
    # Digits and single letters stay: "Vitamin C" / "Vitamin D", "7 Up", "Cola 0,0" are different articles.
    return frozenset(word for word in words if word not in _GENERIC)


def match_article(title: str, other_title: str, brand: str = "", other_brand: str = "") -> str | None:
    """'exact' (same identity and same pack), 'substitute' (same identity, other/unknown pack) or None (different article)."""
    mine, theirs = identity_tokens(title, brand), identity_tokens(other_title, other_brand)
    if not mine or not theirs or mine != theirs:
        return None
    first, second = pack_signature(title), pack_signature(other_title)
    # "exact" only when both titles state the same pack; unknown packs are never promised as identical.
    return "exact" if first and first == second else "substitute"
