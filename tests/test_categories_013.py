from supermarkt.categories import category_decision, normalize_category

import pytest


def test_product_name_overrides_wrong_pet_source_category():
    assert normalize_category(
        "Tierbedarf", name="CLEANMAXX Bodenkehrer"
    ) == "Haushalt & Reinigung"


def test_ice_cream_overrides_bakery_flavour_source_category():
    assert normalize_category(
        "Backwaren",
        name="MÄLZER&FU Ice Cream",
        description="Franzbrötchen Geschmack",
    ) == "Tiefkühl / Eis & Dessert"


def test_pom_baer_is_a_snack():
    assert normalize_category(
        "Weitere Angebote", name="FUNNY-FRISCH Pom-Bär"
    ) == "Snacks"


def test_real_bread_remains_bakery():
    assert normalize_category("Weitere Angebote", name="Brot") == "Backwaren"


def test_cat_food_is_pet_supplies():
    assert normalize_category("Weitere Angebote", name="Katzenfutter") == "Tierbedarf"


def test_cleaner_and_firelighter_do_not_inherit_food_categories():
    assert normalize_category("Getränke", name="WC-Reiniger") == "Haushalt & Reinigung"
    assert normalize_category("Lebensmittel", name="Grillanzünder") == "Haushalt & Reinigung"


def test_food_does_not_inherit_non_food_source_category():
    assert normalize_category("Drogerie", name="Cola") == "Getränke"
    assert normalize_category("Lebensmittel", name="Katzenstreu") == "Tierbedarf"


def test_category_conflict_is_structured():
    decision = category_decision("Backwaren", name="Ice Cream")
    assert decision.category == "Tiefkühl / Eis & Dessert"
    assert decision.source_category == "Backwaren"
    assert decision.detected_category == "Tiefkühl / Eis & Dessert"
    assert decision.category_conflict is True


def test_audited_cross_domain_products_are_normalized():
    assert normalize_category("Kaufland Filialangebote", name="Ital. Bio-Rucola") == "Obst & Gemüse"
    assert normalize_category("Knabbern & Naschen", name="Smarties Riesenrolle") == "Snacks"
    assert normalize_category("Grundnahrung", name="Pain au chocolat") == "Backwaren"
    assert normalize_category("Rabatt-Monat", name="LANGNESE Calippo Cola", description="Wassereis") == "Tiefkühl / Eis & Dessert"
    assert normalize_category("Tiefkühlpizza & -flammkuchen", name="Dr. Oetker Ristorante Pizza") == "Tiefkühl / Eis & Dessert"
    assert normalize_category("Rabatt-Monat", name="WERA NOVA Sahneeis") == "Tiefkühl / Eis & Dessert"
    assert normalize_category("Drogerie, Tiernahrung", name="AJAX Allzweckreiniger") == "Haushalt & Reinigung"
    assert normalize_category("Feinkost, Konserven", name="TYMBARK Frucht-Mischsaft") == "Getränke"
    assert normalize_category("Grundnahrungsmittel", name="Franzbrötchen") == "Backwaren"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Softdrinks", "Getränke"),
        ("Cocktails", "Getränke"),
        ("Würste", "Fleisch & Wurst"),
        ("Reinigen", "Haushalt & Reinigung"),
        ("Exotische Früchte", "Obst & Gemüse"),
        ("Melonen", "Obst & Gemüse"),
        ("Pflanzen", "Wohnen, Freizeit & Non-Food"),
        ("Töpfe", "Wohnen, Freizeit & Non-Food"),
        ("Küchenzubehör", "Wohnen, Freizeit & Non-Food"),
        ("Aufbewahrungsbehälter", "Wohnen, Freizeit & Non-Food"),
        ("Wassersport", "Wohnen, Freizeit & Non-Food"),
        ("Eis", "Tiefkühl / Eis & Dessert"),
        ("Desserts", "Tiefkühl / Eis & Dessert"),
        ("Sahne, Schmand und Crème fraîche", "Molkereiprodukte & Eier"),
    ],
)
def test_real_source_categories_do_not_fall_through(source, expected):
    assert normalize_category(source) == expected


def test_source_category_substrings_do_not_hijack_unrelated_categories():
    assert normalize_category("Meeresfrüchte", name="Garnelen") == "Fisch & Meeresfrüchte"
    assert normalize_category("Wassersport") == "Wohnen, Freizeit & Non-Food"
    assert normalize_category("Spirituosen", name="Eierlikör") == "Getränke"
