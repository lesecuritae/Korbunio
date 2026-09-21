from supermarkt.common import filter_offers
from supermarkt.models import Offer


def offer(name, category="Tiefkühl / Eis & Dessert", retailer="Netto Marken-Discount", brand="", description=""):
    return Offer(
        offer_id=name, retailer=retailer, category=category, name=name, brand=brand, description=description, price=1.0,
        base_price=None, base_unit="", pack_signature="", validity_label="", match_key=name, source_url="https://example.test",
    )


offers = [
    offer("Schweine-Nacken"),
    offer("Hell Energy Drink"),
    offer("Ehrmann Grand Dessert", retailer="Lidl", brand="Ehrmann"),
    offer("Sahnepudding", description="Dessert im Becher"),
    offer("Vanilleeis", category="Kühlregal"),
]

# Die Warengruppe zählt nicht zur Suche (Issue #46): „Dessert“/„Eis“ finden nur Angebote, die es selbst nennen.
assert [o.name for o in filter_offers(offers, "Dessert")] == ["Ehrmann Grand Dessert", "Sahnepudding"]
assert [o.name for o in filter_offers(offers, "eis")] == ["Vanilleeis"]
assert "Hell Energy Drink" not in [o.name for o in filter_offers(offers, "Eis")]
assert [o.name for o in filter_offers(offers, "Vanilleeis")] == ["Vanilleeis"]
# Händler und Marke bleiben durchsuchbar; leere Suche zeigt alles.
assert [o.name for o in filter_offers(offers, "lidl")] == ["Ehrmann Grand Dessert"]
assert [o.name for o in filter_offers(offers, "ehrmann")] == ["Ehrmann Grand Dessert"]
assert len(filter_offers(offers, "  ")) == len(offers)
print("Die Suche berücksichtigt die Warengruppe nicht: OK")
