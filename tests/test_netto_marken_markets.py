from supermarkt.sources.netto_marken import NettoMarkenMarketResolver


POSTAL_CODE = "042" + "09"
from supermarkt.models import ToolError
import pytest


def stores():
    return [
        {"store_id": "5303", "store_name": "Netto Marken-Discount", "post_code": POSTAL_CODE, "city": "Leipzig-Grünau", "street": "Dahlienstr. 20", "is_closed": False},
        {"store_id": "5034", "store_name": "Netto Marken-Discount", "post_code": POSTAL_CODE, "city": "Leipzig-Grünau", "street": "Breisgaustr. 85", "is_closed": False},
        {"store_id": "9999", "store_name": "Netto Marken-Discount", "post_code": POSTAL_CODE, "city": "Teststadt", "street": "Teststrasse", "is_closed": False},
        {"store_id": "1", "store_name": "Netto Marken-Discount", "post_code": POSTAL_CODE, "city": "Leipzig", "street": "Geschlossen", "is_closed": True},
    ]


def test_netto_lists_every_distinct_exact_postcode_store(monkeypatch):
    resolver = NettoMarkenMarketResolver(object())
    monkeypatch.setattr(resolver, "_stores_near", lambda _postal: stores())
    markets = resolver.markets(POSTAL_CODE)
    assert [market["market_id"] for market in markets] == ["5034", "5303"]
    assert all(market["match_type"] == "exact" for market in markets)


def test_netto_honours_and_validates_manual_store_choice(monkeypatch):
    resolver = NettoMarkenMarketResolver(object())
    monkeypatch.setattr(resolver, "_stores_near", lambda _postal: stores())
    assert resolver.resolve(POSTAL_CODE, "5303")["street"] == "Dahlienstr. 20"
    with pytest.raises(ToolError, match="gehört nicht"):
        resolver.resolve(POSTAL_CODE, "7777")
