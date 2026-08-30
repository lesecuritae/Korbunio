from fastapi.testclient import TestClient

from supermarkt import runtime
from supermarkt.asgi import app


def test_health_reports_actual_source_priority(monkeypatch):
    class Store:
        def health(self): return {}
    class Engine:
        store=Store()
    class Images:
        def health(self): return {}
    monkeypatch.setattr(runtime, "get_engine", lambda: Engine())
    monkeypatch.setattr(runtime, "get_image_service", lambda: Images())
    sources=TestClient(app).get("/health").json()["sources"]
    assert sources["REWE"].startswith("official primary")
    assert sources["Lidl"] == "Marktguru regional catalogue"
    assert sources["PENNY"] == "Marktguru regional catalogue"
    assert sources["Netto Marken-Discount"] == "Marktguru regional catalogue"
    assert sources["Netto schwarz"].startswith("official")
    assert sources["Rossmann"].startswith("official")
    assert sources["Müller"].startswith("official")
