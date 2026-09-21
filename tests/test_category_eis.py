from supermarkt.categories import category_decision

ICE = "Tiefkühl / Eis & Dessert"

# Issue #46: `\w*eis` hielt „HINWEIS“ (Netto schreibt es in fast jede Beschreibung), „Reis“ und „Einzelpreis“ für Speiseeis.
assert category_decision("Schweinefleisch", "Netto Marken-Discount", "Schweine-Nacken", "HINWEIS: MIT NETTO PLUS APP 0.59 € oder Schweine Kamm").category == "Fleisch & Wurst"
assert category_decision("Joghurt", "Netto Marken-Discount", "Zott Monte XXL", "HINWEIS: MIT NETTO PLUS APP 0.79 €").category != ICE
assert category_decision("", "", "Hell Energy Energy Drink", "Einzelpreis: 0.89 zzgl. Pfand 0.25").category != ICE
assert category_decision("Reis", "", "Bonrisi Express-Reis", "versch. Sorten 250 g").category != ICE
assert category_decision("", "", "Basmatireis", "").category != ICE
assert category_decision("", "", "Eistee Pfirsich", "").category != ICE and category_decision("", "", "Eisbergsalat", "").category != ICE

# Echtes Eis und Desserts bleiben in der Gruppe.
for name in ("Langnese Cremissimo Vanilleeis", "Magnum Eis am Stiel", "Schoko Speiseeis", "Häagen Dazs Eiscreme", "Ehrmann Grand Dessert", "Gelato d’Italia Eisbecher"):
    assert category_decision("", "", name, "").category == ICE, name
assert category_decision("Tiefkühlgerichte", "", "Genuss Welt Fertiggerichte", "").category == ICE
print("Nur Speiseeis und Desserts landen in der Eis-Gruppe: OK")
