from pathlib import Path

from supermarkt.models import LoadResult, Offer
from supermarkt.sources.aldi_chain import AldiOfferChain


def offer(retailer="ALDI Süd"):
    return Offer("id", retailer, "Weitere Angebote", "Test", "", "", 1.0, None, "", "", "", "key", "https://example.invalid")


class Provider:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def load(self, retailer):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_provider_order_and_success_are_cached(tmp_path: Path):
    first = Provider(LoadResult([], ["leer"]))
    second = Provider(LoadResult([offer()], []))
    chain = AldiOfferChain(tmp_path / "cache.sqlite", (first, second))
    assert len(chain.load("ALDI Süd").offers) == 1
    assert first.calls == second.calls == 1
    assert chain.last_source["ALDI Süd"] == "official:2"


def test_region_strict_last_known_good_and_schema(tmp_path: Path):
    good = Provider(LoadResult([offer("ALDI Süd")], []))
    db = tmp_path / "cache.sqlite"
    AldiOfferChain(db, (good,)).load("ALDI Süd")
    failed = AldiOfferChain(db, (Provider(error=RuntimeError("offline")),))
    result = failed.load("ALDI Süd")
    assert len(result.offers) == 1
    assert result.offers[0].retailer == "ALDI Süd"
    assert failed.last_source["ALDI Süd"] == "last-known-good"
    assert failed.load("ALDI Nord").offers == []


def test_expired_cache_is_not_used(tmp_path: Path, monkeypatch):
    import supermarkt.sources.aldi_chain as module
    now = 2_000_000.0
    monkeypatch.setattr(module.time, "time", lambda: now)
    db = tmp_path / "cache.sqlite"
    AldiOfferChain(db, (Provider(LoadResult([offer()], [])),), ttl_seconds=3600).load("ALDI Süd")
    monkeypatch.setattr(module.time, "time", lambda: now + 3601)
    chain = AldiOfferChain(db, (Provider(error=RuntimeError("offline")),), ttl_seconds=3600)
    assert chain.load("ALDI Süd").offers == []
