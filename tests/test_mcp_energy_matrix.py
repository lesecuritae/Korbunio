"""Deterministic matrix for the Energy/Monster completeness case: 20 returned out of >20 total."""
import asyncio

import pytest
from mcp.client import Client

from supermarkt import mcp_server, runtime
from supermarkt.service import SupermarketEngine
from test_mcp_completeness import _offer, _install, call  # noqa: F401  (shared builders)

RETAILERS = ["Kaufland", "REWE", "Lidl", "EDEKA", "Netto Marken-Discount", "PENNY", "Globus"]


@pytest.fixture(autouse=True)
def real_engine(monkeypatch, tmp_path):
    from supermarkt import config
    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "history.sqlite3")
    monkeypatch.setattr(runtime, "get_engine", lambda: SupermarketEngine())
    monkeypatch.setenv("SUPERMARKT_MCP_WARMUP", "0")
    for store in (mcp_server._inflight, mcp_server._load_failures, mcp_server._last_used):
        store.clear()
    mcp_server._new_postal_codes.clear()


def _catalogue(total, monster_prices):
    """`total` generic energy drinks (0,40 € + 1 ct steps, several retailers) plus Monster offers at the given prices."""
    offers = [_offer(i, RETAILERS[i % len(RETAILERS)], f"Energy Drink Sorte {i}", round(0.40 + i * 0.01, 2)) for i in range(total)]
    for n, price in enumerate(monster_prices):
        offers.append(_offer(1000 + n, RETAILERS[(n * 3 + 1) % len(RETAILERS)], f"Monster Energy Ultra {n}", price, brand="Monster"))
    return offers


@pytest.mark.parametrize("monster_prices, where", [([0.10], "cheaper: first"), ([0.55], "inside first 20"), ([1.99, 2.49], "behind: only via next page")])
@pytest.mark.parametrize("limit", [8, 20, 25])
def test_every_hit_is_reachable_by_following_pages_and_totals_never_lie(monkeypatch, monster_prices, where, limit):
    offers = _catalogue(40, monster_prices)
    _install(monkeypatch, offers)
    seen, offset, pages = [], 0, 0
    while True:
        data = call({"product": "Energy", "limit": limit, "offset": offset}).structured_content
        assert data["found"] == 40 + len(monster_prices), where
        assert data["returned"] == len(data["offers"]) <= limit
        seen += [o["product"] for o in data["offers"]]
        pages += 1
        if not data["has_more"]:
            break
        offset += data["returned"]
        assert pages < 20
    assert len(seen) == len(set(seen)) == data["found"]
    assert all(any(f"Ultra {n}" in name for name in seen) for n in range(len(monster_prices)))
    # price order is global and stable across pages
    prices = list(seen)
    assert prices == sorted(prices, key=lambda name: next(x["price"] for x in offers if x["name"] == name))


def test_exactly_20_total_with_limit_20_is_complete_not_truncated(monkeypatch):
    _install(monkeypatch, _catalogue(19, [0.99]))
    data = call({"product": "Energy", "limit": 20}).structured_content
    assert (data["found"], data["returned"], data["has_more"]) == (20, 20, False)


def test_21_total_with_limit_20_announces_the_missing_one(monkeypatch):
    _install(monkeypatch, _catalogue(20, [2.99]))
    result = call({"product": "Energy", "limit": 20})
    data = result.structured_content
    assert (data["found"], data["returned"], data["has_more"]) == (21, 20, True)
    assert "20 von 21" in result.content[0].text and "offset=20" in result.content[0].text
    assert not any("Ultra" in o["product"] for o in data["offers"])
    tail = call({"product": "Energy", "limit": 20, "offset": 20}).structured_content
    assert [o["product"] for o in tail["offers"]] == ["Monster Energy Ultra 0"]


def test_limit_above_maximum_is_capped_but_still_reports_remainder(monkeypatch):
    _install(monkeypatch, _catalogue(40, []))
    data = call({"product": "Energy", "limit": 500}).structured_content
    assert data["returned"] == 25 and data["has_more"] is True and data["found"] == 40


@pytest.mark.parametrize("query", ["Energy", "energy", "ENERGY", "  Energy  ", "Energy ", "energy"])
def test_whitespace_and_case_do_not_change_the_hits(monkeypatch, query):
    _install(monkeypatch, _catalogue(5, [1.5]))
    assert call({"product": query, "limit": 25}).structured_content["found"] == 6


def test_same_args_in_parallel_with_different_offsets_do_not_mix_pages(monkeypatch):
    _install(monkeypatch, _catalogue(40, [2.0]))

    async def run():
        async with Client(mcp_server.mcp) as client:
            jobs = [client.call_tool("find_offers", {"product": "Energy", "postal_code": "01067", "with_images": False, "limit": 10, "offset": o})
                    for o in (0, 10, 20, 30, 40, 0, 20)]
            return await asyncio.gather(*jobs)

    pages = [tuple(o["product"] for o in r.structured_content["offers"]) for r in asyncio.run(run())]
    assert pages[0] == pages[5] and pages[2] == pages[6]
    flat = [name for page in pages[:5] for name in page]
    assert len(flat) == len(set(flat)) == 41


def test_different_postal_codes_load_separately_and_keep_their_own_totals(monkeypatch):
    by_plz = {"01067": _snap(_catalogue(3, [])), "80331": _snap(_catalogue(30, [1.0]))}
    monkeypatch.setattr(mcp_server, "_load_snapshot", lambda plz, retailers, refresh=False, offer_week="current": by_plz[plz])
    one = call_plz("01067")
    two = call_plz("80331")
    assert (one["found"], two["found"]) == (3, 31)


def _snap(offers):
    return {"search_id": "t", "postal_code": "x", "offers": offers, "retailers": {}, "request_errors": []}


def call_plz(plz):
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("find_offers", {"product": "Energy", "postal_code": plz, "with_images": False, "limit": 25})
    return asyncio.run(run()).structured_content


def test_future_and_expired_offers_are_counted_consistently(monkeypatch):
    import datetime
    monkeypatch.setattr(mcp_server, "today_berlin", lambda: datetime.date(2026, 10, 30))
    monkeypatch.setattr("supermarkt.service.today_berlin", lambda: datetime.date(2026, 10, 30))
    offers = _catalogue(25, [])
    offers.append(_offer(2000, "REWE", "Energy Zukunft", 0.2, valid_from="2026-11-02", valid_until="2026-11-08"))
    offers.append(_offer(2001, "REWE", "Energy Vorbei", 0.1, valid_from="2026-10-19", valid_until="2026-10-24"))
    _install(monkeypatch, offers)
    data = call({"product": "Energy", "limit": 25}).structured_content
    assert data["found"] == 26 and "Energy Vorbei" not in [o["product"] for o in data["offers"]]
    assert data["has_more"] is True and "Energy Zukunft" in [o["product"] for o in data["offers"]]
