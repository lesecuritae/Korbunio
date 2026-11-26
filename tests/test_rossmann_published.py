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


@pytest.mark.parametrize("header", ["Gültig ab Montag: 31.11. - 13.11.2026", "Gültig ab Montag: 14.11. - 13.11.2026"])
def test_missing_invalid_or_reversed_week_is_not_imported_as_undated_offers(header):
    html = HTML.replace("Gültig ab Montag: 09.11. - 13.11.2026", header)
    with pytest.raises(ToolError, match="(?i)gültigkeit"):
        OfficialRossmannSource(lambda _url: html).load("50939")


def test_published_year_boundary_uses_the_previous_year_for_december():
    assert OfficialRossmannSource._validity("Gültig ab Montag: 28.12. - 01.01.2027") == (date(2026, 12, 28), date(2027, 1, 1))


def test_published_daily_wording_with_en_dash_is_also_understood():
    """Rossmann reworded the flyer-wide header in November 2026 ("Täglich gültig
    vom DD.MM. – DD.MM.YYYY", en dash) without dropping the older wording elsewhere."""
    assert OfficialRossmannSource._validity("Täglich gültig vom 09.11. – 13.11.2026") == (date(2026, 11, 9), date(2026, 11, 13))
    # A per-product footnote period in the same page text must not be mistaken for it.
    assert OfficialRossmannSource._validity("Gültig vom 19.10.2026 bis 23.10.2026") == (None, None)


def test_five_published_cards_with_the_november_2026_daily_wording():
    html = HTML.replace("Gültig ab Montag: 09.11. - 13.11.2026", "Täglich gültig vom 09.11. – 13.11.2026")
    offers = OfficialRossmannSource(lambda _url: html).load("50939")
    assert all((o.valid_from, o.valid_until) == ("2026-11-09", "2026-11-13") for o in offers)


def test_a_render_without_the_validity_banner_yet_is_retried_once():
    """The banner can occasionally still be missing right after a fresh render
    (a client-side timing gap, not a wording problem); one retried render that
    does have it must still succeed instead of failing the whole page."""
    calls = []

    def renderer(_url):
        calls.append(1)
        return HTML.replace("Gültig ab Montag: 09.11. - 13.11.2026", "") if len(calls) == 1 else HTML

    offers = OfficialRossmannSource(renderer).load("50939")
    assert len(calls) == 2
    assert all((o.valid_from, o.valid_until) == ("2026-11-09", "2026-11-13") for o in offers)


def test_a_failed_banner_retry_preserves_readable_undated_offers():
    undated = HTML.replace("Gültig ab Montag: 09.11. - 13.11.2026", "")
    calls = []

    def renderer(_url):
        calls.append(1)
        if len(calls) == 2:
            raise ToolError("Rossmann-Browserabruf fehlgeschlagen")
        return undated

    offers = OfficialRossmannSource(renderer).load("50939")
    assert len(calls) == 2
    assert len(offers) == 5
    assert all(o.valid_from is None and o.valid_until is None for o in offers)


def test_cards_without_the_product_card_testid_are_still_found_by_item_id():
    """Rossmann dropped data-testid="product-card" from the tiles when it moved this
    page onto its generic search-results template; data-item-id stayed on the same
    element, so the selector must still find the cards through that attribute alone."""
    html = HTML.replace('data-testid="product-card"', "")
    offers = OfficialRossmannSource(lambda _url: html).load("50939")
    assert {o.name for o in offers} == {
        "Melitta Kaffee Auslese Klassisch gemahlen",
        "Wella Wellaflex Schaumfestiger Volumen Fülle & Style 5",
        "Zewa Haushaltstücher Wisch & Weg Reinweiß",
        "Pampers Feuchttücher 99% Wasser",
        "L’Oréal Paris Excellence Crème Coloration 5 Hellbraun",
    }


def test_missing_period_keeps_only_advertised_cards_with_explicit_unknown_validity():
    calls = []
    html = HTML.replace("Gültig ab Montag: 09.11. - 13.11.2026", "")
    # A coupon footnote must never become the period for all advertised cards.
    html += "<footer>Gültig vom 16.11.2026 bis 20.11.2026. Gültig bis zum 31.12.2026.</footer>"

    def renderer(_url):
        calls.append(1)
        return html

    offers = OfficialRossmannSource(renderer).load("50939")
    assert len(calls) == 2
    assert len(offers) == 5
    assert all(o.valid_from is None and o.valid_until is None for o in offers)
    assert all("unbestätigt" in o.validity_label and "unbestätigt" in o.coverage_note for o in offers)
    assert offers[0].price == 5.49
    assert offers[0].article_number == "712569"
    with pytest.raises(ToolError, match="keine lesbaren Werbeangebote"):
        OfficialRossmannSource(lambda _: html.replace("Aus der Werbung", "Sortiment")).load("50939")


def test_missing_period_does_not_hide_a_broken_render():
    with pytest.raises(ToolError, match="keine lesbaren Werbeangebote"):
        OfficialRossmannSource(lambda _: "<html>Access denied</html>").load("50939")


def test_missing_period_survives_response_and_mcp_search(monkeypatch, tmp_path):
    from dataclasses import asdict
    from supermarkt import config, mcp_server, runtime
    from supermarkt.service import SupermarketEngine

    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "history.sqlite3")
    monkeypatch.setattr(runtime, "get_engine", lambda: SupermarketEngine())
    html = HTML.replace("Gültig ab Montag: 09.11. - 13.11.2026", "")
    offers = OfficialRossmannSource(lambda _: html).load("50939")
    snapshot = {"search_id": "rossmann-93", "postal_code": "50939", "offers": [asdict(o) for o in offers], "retailers": {}, "request_errors": []}
    result = mcp_server._offers_from(snapshot, "Melitta", None, ("Rossmann",))
    assert len(result) == 1
    assert result[0].price_without_bonus == "5,49 €"
    assert result[0].valid_from == result[0].valid_until == ""
    assert "Gültigkeit unbestätigt" in result[0].valid
    assert "Gültigkeit unbestätigt" in mcp_server._valid_text(result[0])
