"""MCP find_offers weist darauf hin, dass App-only-Preise (Lidl Plus, PENNY App, Netto Plus) nicht verrechnet werden."""
import asyncio
import pytest
from mcp.client import Client
from supermarkt import mcp_server, runtime
from supermarkt.service import SupermarketEngine


def _offer(i, retailer):
    return {"offer_id": f"o{i}", "retailer": retailer, "category": "Getränke", "name": "Energy Drink", "brand": "", "description": "",
            "price": 0.5 + i, "base_price": None, "base_unit": "", "pack_signature": f"s{i}", "validity_label": "gültig", "match_key": f"m{i}",
            "source_url": "https://example.test/", "valid_from": "", "valid_until": ""}


@pytest.fixture(autouse=True)
def engine(monkeypatch, tmp_path):
    from supermarkt import config
    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "h.sqlite3")
    monkeypatch.setattr(runtime, "get_engine", lambda: SupermarketEngine())
    monkeypatch.setenv("SUPERMARKT_MCP_WARMUP", "0")


def _text(monkeypatch, retailers):
    snap = {"search_id": "t", "postal_code": "01067", "offers": [_offer(i, r) for i, r in enumerate(retailers)], "retailers": {}, "request_errors": []}
    mcp_server._inflight.clear(); mcp_server._load_failures.clear(); mcp_server._last_used.clear(); mcp_server._new_postal_codes.clear()
    monkeypatch.setattr(mcp_server, "_load_snapshot", lambda plz, retailers, refresh=False, offer_week="current": snap)
    async def run():
        async with Client(mcp_server.mcp) as c:
            return await c.call_tool("find_offers", {"postal_code": "01067", "product": "Energy", "with_images": False})
    return asyncio.run(run()).content[0].text


def test_note_names_exactly_the_app_retailers_present(monkeypatch):
    text = _text(monkeypatch, ["Lidl", "PENNY", "REWE"])
    assert "App-Preise und persönliche Coupons (Lidl Plus, PENNY App)" in text and "Netto" not in text


def test_no_note_without_app_retailers(monkeypatch):
    assert "App-Preise" not in _text(monkeypatch, ["REWE", "Kaufland"])
