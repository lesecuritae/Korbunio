from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from supermarkt.asgi import app
from supermarkt.api_models import SupermarketRequest
from supermarkt import runtime
from supermarkt import security


def test_api_returns_one_absolute_result_url():
    client = TestClient(app, base_url="https://offers.example.test")
    result = client.post("/api/v1/compare", json={"postal_code": "01067"}).json()
    assert result["result_url"].startswith("https://offers.example.test/results/synthetic-link-test?token=")
    assert "full_offer_list_url" not in result and "ui_url" not in result


def test_api_preserves_loyalty_programs_and_optional_auth(monkeypatch):
    client = TestClient(app, base_url="https://offers.example.test")
    response = client.post("/api/v1/compare", json={"postal_code": "01067", "loyalty_programs": ["lidl_plus", "kaufland_xtra", "payback"]})
    assert parse_qs(urlsplit(response.json()["result_url"]).query)["loyalty"] == ["lidl_plus,kaufland_xtra,payback"]
    monkeypatch.setenv("SUPERMARKT_API_KEY", "correct-key")
    assert client.post("/api/v1/compare", json={"postal_code": "01067"}).status_code == 401
    assert client.post("/api/v1/compare", json={"postal_code": "01067"}, headers={"Authorization": "Bearer correct-key"}).status_code == 200


def test_admin_key_issues_separate_hashed_app_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERMARKT_API_KEY", "admin-key")
    monkeypatch.setattr(security, "ACCESS_TOKENS_FILE", tmp_path / "access-tokens.json")
    client = TestClient(app)
    assert client.get("/api/v1/client").status_code == 401
    issued = client.post(
        "/api/v1/access-tokens",
        json={"label": "Testtelefon"},
        headers={"Authorization": "Bearer admin-key"},
    )
    assert issued.status_code == 200
    token = issued.json()["token"]
    assert len(token) >= 48
    stored = security.ACCESS_TOKENS_FILE.read_text(encoding="utf-8")
    assert token not in stored
    assert "Testtelefon" in stored
    assert client.get(
        "/api/v1/client", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200
    assert client.post(
        "/api/v1/access-tokens",
        json={"label": "Nicht erlaubt"},
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 401


def test_result_endpoint_passes_multiple_retailer_filters(monkeypatch):
    from conftest import FakeEngine
    engine = FakeEngine()
    captured = {}
    original_page = engine.page
    def page(snapshot, **kwargs):
        captured.update(kwargs)
        return original_page(snapshot, **kwargs)
    engine.page = page
    monkeypatch.setattr(runtime, "get_engine", lambda: engine)
    client = TestClient(app, base_url="https://offers.example.test")
    result_url = client.post("/api/v1/compare", json={"postal_code": "01067"}).json()["result_url"]
    parsed = urlsplit(result_url)
    response = client.get(
        f"/api/results/{parsed.path.rsplit('/', 1)[-1]}",
        params={**{key: value[0] for key, value in parse_qs(parsed.query).items()}, "retailers": ["Lidl", "PENNY"]},
    )

    assert response.status_code == 200
    assert captured["retailer_filters"] == ("Lidl", "PENNY")


def test_request_rejects_unknown_loyalty_program():
    with pytest.raises(ValidationError):
        SupermarketRequest(postal_code="01067", loyalty_programs=["nicht_echt"])


def test_request_accepts_one_or_multiple_known_retailers():
    one = SupermarketRequest(postal_code="01067", retailers=["REWE"])
    several = SupermarketRequest(postal_code="01067", retailers=["rewe", "Kaufland", "Globus"])
    all_retailers = SupermarketRequest(postal_code="01067")
    assert one.retailers == ["REWE"]
    assert several.retailers == ["REWE", "Kaufland", "Globus"]
    assert all_retailers.retailers == []
    assert SupermarketRequest(postal_code="01067", rewe_market_id="123456").rewe_market_id == "123456"
    assert SupermarketRequest(postal_code="01067", netto_market_id="5303").netto_market_id == "5303"


def test_request_rejects_unknown_retailer():
    with pytest.raises(ValidationError, match="Unbekannte Händler"):
        SupermarketRequest(postal_code="01067", retailers=["REWE", "Nicht Echt"])


def test_request_normalizes_persistent_product_keywords():
    request = SupermarketRequest(postal_code="01067", keywords=[" Milka ", "milka", "", "Butter"])
    assert request.keywords == ["Milka", "Butter"]


def test_request_defaults_to_current_week_and_accepts_preview():
    assert SupermarketRequest(postal_code="01067").offer_week == "current"
    assert SupermarketRequest(postal_code="01067", offer_week="next").offer_week == "next"


def test_openapi_exposes_only_compare_operation():
    operations=[]
    for path, methods in app.openapi()["paths"].items():
        for method, operation in methods.items():
            if method.lower() in {"get", "post", "put", "patch", "delete"}:
                operations.append((method.lower(), path, operation.get("operationId")))
    assert operations == [("post", "/api/v1/compare", "supermarkt_preisvergleich")]
