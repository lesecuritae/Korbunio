"""Expired offers must not reach the web/API page() (proof tests). Run:
cd <repo>; /tmp/kb-energy-venv/bin/python -m pytest -o addopts="" /tmp/kb-expiry-audit/test_page_expiry.py -q
"""
import sys
from datetime import date

import pytest

sys.path.insert(0, "/home/production/codex/Korbunio-energy-mcp-audit-20261030/src")
from supermarkt import common, service  # noqa: E402
from supermarkt.service import SupermarketEngine  # noqa: E402

TODAY = date(2026, 10, 30)


def _offer(i, retailer, price, valid_until, valid_from="2026-10-26", match_key=None, category="Getränke", name=None):
    return {
        "offer_id": f"o{i}", "retailer": retailer, "category": category, "name": name or f"Energy {i}", "brand": "",
        "description": "", "price": price, "base_price": None, "base_unit": "", "pack_signature": "s",
        "validity_label": "", "match_key": match_key or f"mk{i}", "source_url": "https://example.test/",
        "valid_from": valid_from, "valid_until": valid_until,
    }


def _snap(offers, week="current"):
    return {"search_id": "t", "postal_code": "01067", "offers": offers, "retailers": {}, "request_errors": [], "offer_week": week}


def _freeze(monkeypatch, day=TODAY):
    monkeypatch.setattr(common, "today_berlin", lambda: day)
    monkeypatch.setattr(service, "today_berlin", lambda: day)


def _page(snap, **kw):
    return SupermarketEngine().page(snap, **kw)


def test_expired_offers_listed_with_counts(monkeypatch):
    _freeze(monkeypatch)
    snap = _snap([
        _offer(1, "REWE", 1.0, "2026-10-29"),                      # yesterday -> hidden
        _offer(2, "REWE", 1.0, "2026-10-30"),                      # last day -> shown
        _offer(3, "Lidl", 1.0, "2026-10-31", category="Snacks"),   # shown
        _offer(4, "Lidl", 1.0, "2026-10-01", category="Snacks"),   # expired
        _offer(5, "Aldi", 1.0, "", ),                              # blank -> shown
        _offer(6, "Aldi", 1.0, "unparseable"),                     # unparseable -> shown (same as MCP)
    ])
    r = _page(snap, view="all")
    names = {o["product"] for o in r["offers"]}
    assert "Energy 1" not in names and "Energy 4" not in names
    assert r["filtered_offer_count"] == 4
    assert r["compared_offer_count"] == 4
    assert r["retailer_counts"] == {"REWE": 1, "Lidl": 1, "Aldi": 2}
    assert r["category_counts"] == {"Getränke": 3, "Snacks": 1}


def test_page_count_after_filter(monkeypatch):
    _freeze(monkeypatch)
    offers = [_offer(i, "REWE", 1.0, "2026-10-29") for i in range(150)] + [_offer(1000 + i, "REWE", 1.0, "2026-10-30") for i in range(5)]
    r = _page(_snap(offers), view="all", page_size=100)
    assert r["filtered_offer_count"] == 5 and r["page_count"] == 1 and r["has_next"] is False


def test_best_is_not_an_expired_offer(monkeypatch):
    _freeze(monkeypatch)
    # Same product (match_key): cheaper one expired yesterday, dearer one still valid.
    snap = _snap([
        _offer(1, "REWE", 0.49, "2026-10-29", match_key="same"),
        _offer(2, "Lidl", 0.79, "2026-10-31", match_key="same"),
    ])
    best = _page(snap, view="best_only")
    assert [o["retailer"] for o in best["offers"]] == ["Lidl"]
    assert best["hidden_count"] == 0  # the only hidden candidate was expired, not "dominated"
    allv = _page(snap, view="all")
    assert len(allv["offers"]) == 1


def test_hidden_count_consistent(monkeypatch):
    _freeze(monkeypatch)
    snap = _snap([
        _offer(1, "REWE", 0.49, "2026-10-31", match_key="same"),
        _offer(2, "Lidl", 0.79, "2026-10-31", match_key="same"),
        _offer(3, "Aldi", 0.99, "2026-10-01", match_key="same"),
    ])
    r = _page(snap, view="best_only")
    assert len(r["offers"]) == 1 and r["hidden_count"] == 1


@pytest.mark.parametrize("sort", ["price", "retailer", "name"])
def test_sort_does_not_resurrect_expired(monkeypatch, sort):
    _freeze(monkeypatch)
    snap = _snap([_offer(1, "REWE", 0.01, "2026-10-29"), _offer(2, "Lidl", 5.0, "2026-10-30")])
    r = _page(snap, view="all", sort=sort)
    assert [o["retailer"] for o in r["offers"]] == ["Lidl"]


def test_berlin_midnight_vs_utc(monkeypatch):
    # 2026-10-30 23:30 UTC is already 2026-10-31 00:30 CET? (DST ended 2026-10-25 -> UTC+1) -> Berlin date 31.
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    instant = datetime(2026, 10, 30, 23, 30, tzinfo=timezone.utc)
    assert instant.astimezone(ZoneInfo("Europe/Berlin")).date() == date(2026, 10, 31)
    assert instant.date() == date(2026, 10, 30)  # naive UTC date would be wrong
    _freeze(monkeypatch, date(2026, 10, 31))  # what today_berlin() returns at that instant
    snap = _snap([_offer(1, "REWE", 1.0, "2026-10-30"), _offer(2, "REWE", 1.0, "2026-10-31")])
    r = _page(snap, view="all")
    assert [o["product"] for o in r["offers"]] == ["Energy 2"]


def test_next_week_not_filtered_by_today(monkeypatch):
    _freeze(monkeypatch)
    snap = _snap([_offer(1, "REWE", 1.0, "2026-11-07", valid_from="2026-11-02")], week="next")
    r = _page(snap, view="all")
    assert len(r["offers"]) == 1 and r["offer_week"] == "next"


def test_source_offer_count_semantics(monkeypatch):
    _freeze(monkeypatch)
    snap = _snap([_offer(1, "REWE", 1.0, "2026-10-29"), _offer(2, "REWE", 1.0, "2026-10-30")])
    r = _page(snap, view="all")
    # Decision: either keep raw snapshot size (2) and expose expired_filtered_count, or use 1. Never show the expired offer.
    assert len(r["offers"]) == 1
