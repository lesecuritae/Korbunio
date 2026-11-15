"""Offline contract tests. Synthetic stores; not a claim of live coverage."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import threading

from fastapi.testclient import TestClient
from mcp.client.client import Client
from pydantic import ValidationError
import pytest

from supermarkt import availability as a, runtime
from supermarkt.asgi import app
from supermarkt.models import ToolError


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent / "fixtures/availability/rossmann.json").read_text())


def service(payload, fetch=None):
    ticks = [0.0]
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        ticks[0] += seconds
    svc = a.StockService(lambda postal: (51.3, 12.3), fetch or (lambda *args: deepcopy(payload)), lambda: ticks[0], sleep)
    return svc, ticks, sleeps


def test_zero_lower_bound_and_unknown_are_different(payload):
    stores = a.parse_stores(payload, "120585")
    assert stores[0]["stock_minimum"] == 5 and stores[0]["stock_is_exact"] is False
    assert stores[1]["listed"] is True and stores[1]["in_stock"] is False
    assert stores[2]["stock_minimum"] is None and stores[2]["in_stock"] is None


def test_zero_lower_bound_does_not_prove_sold_out(payload):
    payload[0]["productInfos"][0]["stock"] = "0+"
    assert a.parse_stores(payload, "120585")[0]["in_stock"] is None


@pytest.mark.parametrize("change", ["wrong-dan", "duplicate-product", "conflicting-store", "missing-infos", "html"])
def test_schema_or_identity_errors_never_become_zero(payload, change):
    if change == "wrong-dan": payload[0]["productInfos"][0]["dan"] = "195333"
    elif change == "duplicate-product": payload[0]["productInfos"] *= 2
    elif change == "conflicting-store": payload.append({**payload[0], "street": "Andere Straße"})
    elif change == "missing-infos": del payload[0]["productInfos"]
    else: payload = "<html>challenge</html>"
    with pytest.raises(ToolError): a.parse_stores(payload, "120585")


def test_deduplicated_batch_pacing_cache_and_partial_error(payload):
    calls = []
    def fetch(lat, lon, dan):
        calls.append(dan)
        if dan == "195333": raise ToolError("HTTP 406")
        return deepcopy(payload)
    svc, ticks, sleeps = service(payload, fetch)
    request = a.StockRequest(postal_code="12345", dans=["120585", "120585", "195333"])
    result = svc.check(request)
    assert calls == ["120585", "195333"] and result["status"] == "partial"
    assert len(result["results"]) == 2 and result["results"][1]["status"] == "unavailable"
    assert result["results"][1]["stores"] == [] and sleeps == [2, 2]
    result2 = svc.check(a.StockRequest(postal_code="12345", dans=["120585"], store_ids=["102"]))
    assert result2["results"][0]["from_cache"] is True
    assert result2["results"][0]["stores"][0]["in_stock"] is False
    assert len(svc.check(a.StockRequest(postal_code="12345", dans=["120585"]))["results"][0]["stores"]) == 3
    assert calls == ["120585", "195333"]
    ticks[0] += 61
    svc.fetch = lambda *args: (_ for _ in ()).throw(ToolError("timeout"))
    failed = svc.check(a.StockRequest(postal_code="12345", dans=["120585"]))
    assert failed["status"] == "unavailable"
    assert svc._cache[(51.3, 12.3, "120585")][1]["stores"][0]["stock_minimum"] == 5


def test_concurrent_admission_returns_busy_without_duplicate_requests(payload):
    entered, release = threading.Event(), threading.Event()
    def fetch(*args):
        entered.set()
        assert release.wait(5)
        return payload
    svc, _, _ = service(payload, fetch)
    request = a.StockRequest(postal_code="12345", dans=["120585"])
    worker = threading.Thread(target=lambda: svc.check(request))
    worker.start()
    try:
        assert entered.wait(5)
        assert svc.check(request)["status"] == "busy"
    finally:
        release.set(); worker.join(5)
    assert not worker.is_alive()


@pytest.mark.parametrize("dans", [[], ["120585"] * 6, ["https://evil.invalid"], ["１２３４５６"], ["12345"], ["1234567"]])
def test_request_rejects_unbounded_and_non_article_inputs(dans):
    with pytest.raises(ValidationError): a.StockRequest(postal_code="12345", dans=dans)


def test_geocode_failure_never_queries_retailer(payload):
    svc, _, _ = service(payload)
    svc.geocode = lambda p: None
    svc.fetch = lambda *args: pytest.fail("must not query with an invented location")
    assert svc.check(a.StockRequest(postal_code="12345", dans=["120585"]))["status"] == "unavailable"


def test_api_auth_validation_and_web_entry(monkeypatch, payload):
    svc, _, _ = service(payload)
    monkeypatch.setattr(runtime, "get_stock_service", lambda: svc)
    client = TestClient(app)
    monkeypatch.setenv("SUPERMARKT_API_KEY", "test-key")
    body = {"postal_code": "12345", "dans": ["120585"]}
    assert client.post("/api/v1/availability", json=body).status_code == 401
    headers = {"Authorization": "Bearer test-key"}
    result = client.post("/api/v1/availability", json=body, headers=headers)
    assert result.status_code == 200 and result.json()["results"][0]["stores"][1]["in_stock"] is False
    assert client.post("/api/v1/availability", json={**body, "url": "http://localhost"}, headers=headers).status_code == 422
    assert client.get("/availability").status_code == 200
    assert "Filialbestand prüfen" in client.get("/").text


def test_mcp_exposes_same_typed_stock_result(monkeypatch, payload):
    from supermarkt.mcp_server import mcp
    svc, _, _ = service(payload)
    monkeypatch.setattr(runtime, "get_stock_service", lambda: svc)
    async def call():
        async with Client(mcp) as client:
            return await client.call_tool("get_store_availability", {"postal_code": "12345", "dans": ["120585"]})
    result = asyncio.run(call())
    assert not result.is_error
    assert result.structured_content["results"][0]["stores"][1]["in_stock"] is False
