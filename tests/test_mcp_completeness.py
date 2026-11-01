"""find_offers must not look complete when it is truncated (Energy/Monster audit 2026-10-30)."""
import asyncio

import pytest
from mcp.client import Client

from supermarkt import mcp_server, runtime
from supermarkt.service import SupermarketEngine


def _offer(index, retailer, name, price, brand="", description="", valid_from="2026-10-26", valid_until="2026-11-01"):
    return {
        "offer_id": f"o{index}", "retailer": retailer, "category": "Getränke", "name": name, "brand": brand,
        "description": description, "price": price, "base_price": None, "base_unit": "", "pack_signature": f"sig{index}",
        "validity_label": f"gültig {valid_from} bis {valid_until}", "match_key": f"mk{index}", "source_url": "https://example.test/",
        "valid_from": valid_from, "valid_until": valid_until,
    }


def _snapshot(offers):
    return {"search_id": "t", "postal_code": "01067", "offers": offers, "retailers": {}, "request_errors": []}


@pytest.fixture(autouse=True)
def real_engine(monkeypatch, tmp_path):
    from supermarkt import config
    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "history.sqlite3")
    monkeypatch.setattr(runtime, "get_engine", lambda: SupermarketEngine())
    monkeypatch.setenv("SUPERMARKT_MCP_WARMUP", "0")
    mcp_server._inflight.clear()
    mcp_server._load_failures.clear()
    mcp_server._last_used.clear()
    mcp_server._new_postal_codes.clear()


def _install(monkeypatch, offers, errors=()):
    snapshot = _snapshot(offers)
    snapshot["request_errors"] = list(errors)
    monkeypatch.setattr(mcp_server, "_load_snapshot", lambda plz, retailers, refresh=False, offer_week="current": snapshot)


def call(arguments):
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("find_offers", {"postal_code": "01067", "with_images": False, **arguments})
    return asyncio.run(run())


def _many_energy(count=30):
    retailers = ["Kaufland", "REWE", "Lidl", "EDEKA", "Netto Marken-Discount"]
    offers = [_offer(i, retailers[i % 5], f"Energy Drink Sorte {i}", 0.49 + i * 0.01) for i in range(count)]
    # Brand offer without the generic word in the title, pricier than all generics.
    offers.append(_offer(900, "REWE", "Ultra Zero 0,5 l", 1.29, brand="Monster Energy"))
    offers.append(_offer(901, "Kaufland", "Monster Ultra Paradise", 1.19, brand="Monster"))
    return offers


def test_truncation_is_reported_and_monster_reachable_via_offset(monkeypatch):
    _install(monkeypatch, _many_energy())
    first = call({"product": "Energy", "limit": 20})
    data = first.structured_content
    assert data["found"] == 31
    assert data["returned"] == 20 and len(data["offers"]) == 20
    assert data["has_more"] is True and data["offset"] == 0
    text = first.content[0].text
    assert "20 von 31" in text and "offset=20" in text
    assert not any("Monster" in o["product"] or "Ultra" in o["product"] for o in data["offers"])
    second = call({"product": "Energy", "limit": 20, "offset": 20}).structured_content
    assert second["returned"] == 11 and second["has_more"] is False and second["offset"] == 20
    names = [o["product"] for o in data["offers"] + second["offers"]]
    assert len(names) == len(set(names)) == 31  # stable, no overlap, nothing lost
    assert any("Ultra Zero" in n for n in names)


def test_complete_result_is_not_marked_truncated(monkeypatch):
    _install(monkeypatch, _many_energy(5))
    data = call({"product": "Energy", "limit": 25}).structured_content
    assert data["found"] == data["returned"] == 6 and data["has_more"] is False


def test_offset_beyond_end_is_explicit_not_empty_search(monkeypatch):
    _install(monkeypatch, _many_energy(5))
    result = call({"product": "Energy", "offset": 50})
    assert result.structured_content["found"] == 6 and result.structured_content["returned"] == 0
    assert "6" in result.content[0].text and "Treffer" in result.content[0].text
    assert "Keine Angebote" not in result.content[0].text  # matches exist; only the page is empty


def test_negative_offset_is_clamped(monkeypatch):
    _install(monkeypatch, _many_energy(5))
    assert call({"product": "Energy", "offset": -3}).structured_content["offset"] == 0


def test_brand_search_finds_brand_without_generic_word(monkeypatch):
    _install(monkeypatch, _many_energy())
    data = call({"product": "Monster", "limit": 25}).structured_content
    assert data["found"] == 2 and data["has_more"] is False
    assert {o["retailer"] for o in data["offers"]} == {"REWE", "Kaufland"}


def test_brand_not_found_by_generic_word_is_a_search_limit_not_absence(monkeypatch):
    # "Energy" matches name+brand+description only. A brand offer that has none of
    # these words is invisible to it; also_search must find it.
    offers = _many_energy(3) + [_offer(777, "Lidl", "Dose 0,5 l", 0.99, brand="Monster")]
    _install(monkeypatch, offers)
    assert call({"product": "Energy", "limit": 25}).structured_content["found"] == 4  # 3 generic + REWE Monster Energy; Kaufland/Lidl Monster lack the word
    assert call({"product": "Energy", "also_search": ["Monster"], "limit": 25}).structured_content["found"] == 6  # + Kaufland and Lidl Monster via also_search


@pytest.mark.parametrize("title", ["Energydrink Classic", "Energy-Drink Classic", "Energy Drink Classic", "ENERGY DRINK Classic"])
def test_energy_drink_spelling_variants_match(monkeypatch, title):
    _install(monkeypatch, [_offer(1, "REWE", title, 0.99)])
    assert call({"product": "Energy Drink"}).structured_content["found"] == 1
    assert call({"product": "energydrink"}).structured_content["found"] == 1


def test_unicode_and_case_in_brand(monkeypatch):
    _install(monkeypatch, [_offer(1, "REWE", "Dose", 0.99, brand="MONSTER ENERGY®")])
    assert call({"product": "monster"}).structured_content["found"] == 1


def test_partial_failure_is_reported_even_with_truncation(monkeypatch):
    _install(monkeypatch, _many_energy(), errors=["Lidl: Zeitüberschreitung"])
    result = call({"product": "Energy", "limit": 5})
    assert result.structured_content["status"] == "partial" and result.structured_content["has_more"] is True
    assert "Lidl: Zeitüberschreitung" in result.content[0].text and "5 von" in result.content[0].text


def test_retailer_filter_counts_only_selected(monkeypatch):
    _install(monkeypatch, _many_energy())
    data = call({"product": "Energy", "retailers": ["REWE"], "limit": 25}).structured_content
    assert {o["retailer"] for o in data["offers"]} == {"REWE"} and data["found"] == data["returned"]


def test_expired_offers_are_hidden_but_today_future_and_undated_stay(monkeypatch):
    import datetime
    from supermarkt import service
    monkeypatch.setattr(mcp_server, "today_berlin", lambda: datetime.date(2026, 10, 30))
    monkeypatch.setattr(service, "today_berlin", lambda: datetime.date(2026, 10, 30))
    _install(monkeypatch, [
        _offer(1, "REWE", "Energy alt", 0.10, valid_from="2026-10-20", valid_until="2026-10-29"),
        _offer(2, "REWE", "Energy heute letzter Tag", 0.20, valid_from="2026-10-26", valid_until="2026-10-30"),
        _offer(3, "Lidl", "Energy ab morgen", 0.30, valid_from="2026-10-31", valid_until="2026-11-07"),
        _offer(4, "EDEKA", "Energy ohne Datum", 0.40, valid_from="", valid_until=""),
    ])
    names = [o["product"] for o in call({"product": "Energy"}).structured_content["offers"]]
    assert names == ["Energy heute letzter Tag", "Energy ab morgen", "Energy ohne Datum"]


def test_parallel_calls_share_one_load_per_key_and_agree(monkeypatch):
    import threading
    import time
    calls = []
    lock = threading.Lock()
    snapshot = _snapshot(_many_energy())

    def slow_load(plz, retailers, refresh=False, offer_week="current"):
        with lock:
            calls.append((plz, tuple(sorted(retailers))))
        time.sleep(0.3)
        return snapshot

    monkeypatch.setattr(mcp_server, "_load_snapshot", slow_load)

    async def run():
        async with Client(mcp_server.mcp) as client:
            jobs = []
            for i in range(24):
                args = {"product": "Energy", "postal_code": "01067", "with_images": False, "limit": 25, "offset": (i % 2) * 25}
                if i % 3 == 0:
                    args["retailers"] = ["REWE"]
                jobs.append(client.call_tool("find_offers", args))
            return await asyncio.gather(*jobs)

    results = asyncio.run(run())
    assert all(not r.is_error for r in results)
    by_key = {}
    for i, r in enumerate(results):
        by_key.setdefault((i % 2, i % 3 == 0), set()).add(tuple(o["product"] for o in r.structured_content["offers"]))
    assert all(len(v) == 1 for v in by_key.values())  # identical answers for identical questions
    assert len(calls) == 2  # one shared load for all retailers, one for the REWE selection


def test_fallback_notes_are_visible_next_to_errors(monkeypatch):
    snapshot = _snapshot([_offer(1, "Müller", "Red Bull Energy", 1.59)])
    snapshot["request_errors"] = ["Müller offiziell: ToolError: keine lesbaren Online-Angebote"]
    snapshot["store_warnings"] = ["Müller: offizielle Seite war nicht lesbar; KaufDA wurde als Fallback verwendet (nur ein Ausschnitt)"]
    monkeypatch.setattr(mcp_server, "_load_snapshot", lambda plz, retailers, refresh=False, offer_week="current": snapshot)
    data = call({"product": "Energy"}).structured_content
    assert any("KaufDA" in note for note in data["diagnostics"]) and data["status"] == "partial"



def _preseed_finished(monkeypatch, outcome):
    """A load that has finished but whose done-callback has not run yet (deterministic: no callback registered)."""
    calls = []
    monkeypatch.setattr(mcp_server, "_load_snapshot", lambda *a, **k: calls.append(1) or _snapshot([]))

    async def run():
        loop = asyncio.get_running_loop()
        done = loop.create_future()
        if isinstance(outcome, Exception):
            done.set_exception(outcome)
        else:
            done.set_result(outcome)
        mcp_server._inflight[("01067", ())] = done
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("find_offers", {"product": "Energy", "postal_code": "01067", "with_images": False})

    return asyncio.run(run()), calls


def test_finished_load_before_callback_is_reused_not_reloaded(monkeypatch):
    result, calls = _preseed_finished(monkeypatch, _snapshot([_offer(1, "REWE", "Energy Test", 0.99)]))
    assert result.structured_content["found"] == 1 and calls == []


def test_finished_failed_load_before_callback_is_reported_not_reloaded(monkeypatch):
    from supermarkt.models import ToolError
    result, calls = _preseed_finished(monkeypatch, ToolError("Quelle weg"))
    assert result.structured_content["status"] == "unavailable" and "Quelle weg" in result.structured_content["diagnostics"][0]
    assert calls == []
