from dataclasses import replace
from pathlib import Path
from datetime import date

from supermarkt.models import Offer
from supermarkt.sources.marktkauf_html import enrich_quantities

HTML = (Path(__file__).parent / "fixtures/offer_coverage/marktkauf_quantity.html").read_text()


def offer(**kwargs):
    value = Offer("fixture", "Marktkauf", "Käse", "Philadelphia Frischkäse oder -zubereitung", "", "verschiedene Sorten und Fettstufen", .99, None, "", "", "09.–14.11.", "fixture", "https://www.dein-marktkauf.de/markkleeberg/", valid_from="2026-11-09", valid_until="2026-11-14")
    return replace(value, **kwargs)


def test_exact_current_first_party_card_fills_only_the_missing_published_quantity():
    old = offer()
    new = enrich_quantities([old], HTML, date(2026, 11, 10))[0]
    assert new.pack_signature == "100-195g"
    assert new.match_key.endswith("|100-195g") and new.match_key != old.match_key
    assert new.offer_id == old.offer_id and new.price == old.price
    assert (new.valid_from, new.valid_until) == (old.valid_from, old.valid_until)


def test_another_price_week_existing_quantity_or_similar_product_cannot_supply_a_pack():
    for old in [offer(price=1.99), offer(valid_from="2026-11-02", valid_until="2026-11-07"),
                offer(name="Philadelphia anderer Artikel"), offer(pack_signature="200g")]:
        assert enrich_quantities([old], HTML, date(2026, 11, 10))[0] == old
    assert enrich_quantities([offer()], HTML.replace("Woche vom", "Unbekannter Zeitraum"), date(2026, 11, 10))[0].pack_signature == ""


def test_expired_same_calendar_day_in_another_year_is_not_enriched():
    old = offer(valid_from="2025-11-09", valid_until="2025-11-14")
    assert enrich_quantities([old], HTML, date(2026, 11, 10))[0].pack_signature == ""
