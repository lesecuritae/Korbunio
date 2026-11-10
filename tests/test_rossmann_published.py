"""Five actual advertised products, not the separate toy-assortment leaflet."""
from datetime import date
from pathlib import Path

import pytest

from supermarkt.models import ToolError
from supermarkt.sources.drogeries import OfficialRossmannSource

HTML = (Path(__file__).parent / "fixtures/offer_coverage/rossmann_published_cards.html").read_text()


def test_five_published_cards_keep_actual_cash_prices_primary_pack_and_week():
    offers = OfficialRossmannSource(lambda _url: HTML).load("50939")
    assert {o.name: (o.price, o.pack_signature) for o in offers} == {
        "Melitta Kaffee Auslese Klassisch gemahlen": (5.49, "500g"),
        "Wella Wellaflex Schaumfestiger Volumen Fülle & Style 5": (2.49, "200ml"),
        "Zewa Haushaltstücher Wisch & Weg Reinweiß": (2.49, "4stk"),
        "Pampers Feuchttücher 99% Wasser": (6.25, "180stk"),
        "L’Oréal Paris Excellence Crème Coloration 5 Hellbraun": (5.99, "1stk"),
    }
    assert all((o.valid_from, o.valid_until) == ("2026-11-09", "2026-11-13") for o in offers)
    assert "3 x 60" in next(o.description for o in offers if "Pampers" in o.name)
    with pytest.raises(ToolError, match="keine lesbaren Werbeangebote"):
        OfficialRossmannSource(lambda _url: HTML.replace("Aus der Werbung", "Reguläres Sortiment")).load("50939")


@pytest.mark.parametrize("header", ["Unbekanntes Schema", "Gültig ab Montag: 31.11. - 13.11.2026", "Gültig ab Montag: 14.11. - 13.11.2026"])
def test_missing_invalid_or_reversed_week_is_not_imported_as_undated_offers(header):
    html = HTML.replace("Gültig ab Montag: 09.11. - 13.11.2026", header)
    with pytest.raises(ToolError, match="(?i)gültigkeit"):
        OfficialRossmannSource(lambda _url: html).load("50939")


def test_published_year_boundary_uses_the_previous_year_for_december():
    assert OfficialRossmannSource._validity("Gültig ab Montag: 28.12. - 01.01.2027") == (date(2026, 12, 28), date(2027, 1, 1))
