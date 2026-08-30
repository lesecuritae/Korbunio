import pytest

from supermarkt import runtime, security


class FakeEngine:
    snapshot_data = {"search_id": "synthetic-link-test", "postal_code": "01067", "created_at": 0}

    def snapshot(self, postal_code, aldi_region, refresh, retailers=(), rewe_market_id="", netto_market_id=""):
        assert postal_code == "01067"
        return dict(self.snapshot_data), True

    def by_id(self, search_id):
        assert search_id == "synthetic-link-test"
        return dict(self.snapshot_data)

    def page(self, snapshot, **kwargs):
        return {"search_id": snapshot["search_id"], "postal_code": "01067", "offers": [], "page": 1, "page_count": 1, "has_next": False, "retailer_counts": {}, "available_loyalty_programs": []}


@pytest.fixture(autouse=True)
def fixed_runtime(monkeypatch):
    monkeypatch.setattr(security, "_CACHED_SECRET", b"test-signing-secret-0123456789-abcdef")
    monkeypatch.setattr(runtime, "get_engine", lambda: FakeEngine())
    monkeypatch.delenv("SUPERMARKT_API_KEY", raising=False)
