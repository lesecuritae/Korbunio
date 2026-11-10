"""Actual public Lidl price evidence through the MCP contract, without live requests."""
import json

import pytest

from supermarkt.compare import OfferMapper
from supermarkt.models import offer_to_dict
from supermarkt.service import SourceLoader
from test_offer_coverage import FIXTURES, DAY, kania, secondary
from test_mcp_completeness import _install, call, real_engine  # noqa: F401


@pytest.fixture(autouse=True)
def published_week(monkeypatch):
    # Historical captured offers must not expire when CI runs next week.
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: DAY)
    monkeypatch.setattr("supermarkt.mcp_server.today_berlin", lambda: DAY)


def test_mcp_returns_regular_and_member_prices_without_species_fabrication(monkeypatch):
    raw = json.loads((FIXTURES / "marktguru_mayonnaise.json").read_text())
    member_offer = OfferMapper().map_one(raw, SourceLoader._contexts(), DAY)
    _install(monkeypatch, [offer_to_dict(o) for o in [kania(), *secondary(), member_offer]])
    result = call({"product": "Mayonnaise", "retailers": ["Lidl"]}).structured_content
    offer = result["offers"][0]
    assert offer["price_without_bonus"] == "1,69 €"
    assert offer["price_with_bonus"] == "1,29 €"
    assert "Lidl Plus" in offer["bonus_program"]
    result = call({"product": "Wildschwein", "retailers": ["Lidl"]}).structured_content
    assert result["offers"][0]["product"] == "Kania Wildschwein"
    assert result["offers"][0]["price_without_bonus"] == "3,99 €"
    assert call({"product": "Hirschgulasch", "retailers": ["Lidl"]}).structured_content["found"] == 0


@pytest.mark.parametrize("retailer", ["dm", "Müller"])
def test_lidl_wildschwein_never_leaks_into_a_drogerie_search(monkeypatch, retailer):
    _install(monkeypatch, [offer_to_dict(o) for o in [kania(), *secondary()]])
    result = call({"product": "Wildschwein", "retailers": [retailer]}).structured_content
    assert result["found"] == 0 and result["offers"] == []
