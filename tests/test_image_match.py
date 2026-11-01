import pytest

from supermarkt.image_match import match_article, pack_signature


@pytest.mark.parametrize("a, b, expected", [
    ("Monster Energy Drink 500 ml", "Monster Energy Energy Drink 500 ml", "exact"),
    ("RED BULL Energy Drink oder Erfrischungsgetränk 250–330 ml", "RED BULL Energy Drink 250 ml", "substitute"),
    ("Booster Energy Drink 330 ml", "Booster Energy Drink 2 × 330 ml", "substitute"),
    ("Coca-Cola 4 x 0,25 l", "Coca Cola 0,5 l", "substitute"),
    ("Hell Energy 250 ml", "HELL ENERGY Dose 250 ml", "exact"),
    ("Rockstar Energy-Drink 500 ml", "Rockstar Energy Drink 0,5 l", "exact"),
])
def test_same_article_other_pack_or_wording_is_accepted(a, b, expected):
    assert match_article(a, b) == expected


@pytest.mark.parametrize("a, b", [
    ("Monster Energy Drink 500 ml", "Monster Energy Ultra Zero 500 ml"),       # Zero vs regular
    ("Coca-Cola 1 l", "Coca-Cola Zero 1 l"),
    ("Coca-Cola 1 l", "Coca-Cola ohne Zucker 1 l"),
    ("Red Bull Energy Drink 250 ml", "Red Bull Energy Drink Sugarfree 250 ml"),
    ("Monster Energy Drink 500 ml", "Rockstar Energy Drink 500 ml"),            # other brand
    ("Booster Energy Drink 330 ml", "Booster Energy Mango 330 ml"),             # other flavour
    ("Lorenz Monster Munch Original 75 g", "Monster Energy Drink 500 ml"),     # foreign article sharing a word
    ("Energy Drink 250 ml", "Hell Energy 250 ml"),                              # generic vs brand
    ("", "Monster Energy Drink"),
])
def test_different_brand_flavour_or_variant_is_never_a_substitute(a, b):
    assert match_article(a, b) is None


def test_brand_field_is_part_of_the_identity():
    assert match_article("Ultra Zero 0,5 l", "Monster Ultra Zero 0,5 l", brand="Monster") == "exact"
    assert match_article("Ultra Zero 0,5 l", "Ultra Zero 0,5 l", brand="Monster", other_brand="Rockstar") is None


def test_pack_signature_normalises_notation():
    assert pack_signature("Cola 0,5 l") == pack_signature("Cola 0.5l") == pack_signature("Cola 500 ml") == "500"
    assert pack_signature("Cola 4 x 0,25 l") == "4x250"
    assert pack_signature("Cola") == ""


@pytest.mark.parametrize("a, b", [
    ("Becks 0,5 l", "Becks 0,0 0,5 l"),
    ("Coca-Cola 1 l", "Coca-Cola 0,0 1 l"),
    ("Vitamin C Brause 20 St", "Vitamin D Brause 20 St"),
    ("7 Up 1 l", "Up 1 l"),
    ("Hohes C 1 l", "Hohes 1 l"),
])
def test_reviewer_false_positives_are_rejected(a, b):
    assert match_article(a, b) is None


def test_unknown_pack_is_never_exact_and_umlaut_spellings_agree():
    assert match_article("Hell Energy", "HELL Energy Dose") == "substitute"
    assert match_article("Müller Milch 1 l", "Mueller Milch 1 l") == "exact"
