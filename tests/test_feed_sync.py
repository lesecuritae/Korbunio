from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from supermarkt import runtime
from supermarkt.asgi import app
from supermarkt.clawforge.feed_sync import (
    FeedAdapter,
    FeedScheduler,
    FeedSyncError,
    HTTPFeedResponse,
    IntelligenceStore,
    build_feed_registry,
    parse_feodo,
    parse_threatfox,
    parse_urlhaus,
)
from supermarkt.clawforge.intelligence import IndicatorType, ThreatIndicator, ThreatProvider, ThreatProviderRegistry


class FakeClient:
    def __init__(self, payload: bytes, content_type: str = "application/json"):
        self.payload = payload
        self.content_type = content_type
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        return HTTPFeedResponse(200, self.payload, {"content-type": self.content_type})


def test_real_provider_parsers_normalize_dates_and_types():
    url = tuple(parse_urlhaus([{"url": "https://evil.example/payload", "dateadded": "2026-09-01T00:00:00+00:00"}]))[0]
    assert url.indicator_type is IndicatorType.URL
    assert url.first_seen is not None and url.expires_at is not None

    threatfox = tuple(parse_threatfox({"data": [{"ioc": "203.0.113.5:443", "ioc_type": "ip:port", "confidence_level": 88}]}))[0]
    assert threatfox.value == "203.0.113.5"
    assert threatfox.indicator_type is IndicatorType.IP

    feodo = tuple(parse_feodo([{"ip_address": "198.51.100.10", "malware": "Dridex"}]))[0]
    assert feodo.metadata["malware"] == "Dridex"


def test_feed_adapter_download_and_duplicate_storage(tmp_path: Path):
    provider = ThreatProvider("test-feed", "Test Feed", "test", confidence=90)
    client = FakeClient(b'[{"value":"203.0.113.8","type":"ip","confidence":80}]')
    adapter = FeedAdapter(provider, "https://feed.example.test", client=client, rate_limit_seconds=0)
    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    store.register_provider(provider)
    assert adapter.sync(store) == 1
    assert adapter.sync(store) == 1
    assert len(store.indicators(provider_id="test-feed")) == 1
    assert client.calls == 2


def test_invalid_feed_and_provider_failure_are_recorded(tmp_path: Path):
    provider = ThreatProvider("broken", "Broken", "test")

    class BrokenAdapter(FeedAdapter):
        def fetch(self):
            raise FeedSyncError("bad response")

    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    store.register_provider(provider)
    scheduler = FeedScheduler(ThreatProviderRegistry([provider]), store, [BrokenAdapter(provider, "https://feed.example", rate_limit_seconds=0)], retry_base_seconds=1, retry_max_seconds=4)
    result = scheduler.run_once("broken")
    assert result.state == "error"
    status = store.provider_status()[0]
    assert status["failure_count"] == 1
    assert status["error"] == "bad response"
    scheduler.stop()


def test_scheduler_retry_backoff_and_rate_limit(tmp_path: Path):
    provider = ThreatProvider("flaky", "Flaky", "test", update_interval=timedelta(seconds=60))

    class FlakyAdapter(FeedAdapter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.attempts = 0

        def fetch(self):
            self.attempts += 1
            if self.attempts == 1:
                raise FeedSyncError("temporary")
            return [{"value": "198.51.100.20", "type": "ip"}]

    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    store.register_provider(provider)
    adapter = FlakyAdapter(provider, "https://feed.example", rate_limit_seconds=0)
    scheduler = FeedScheduler(ThreatProviderRegistry([provider]), store, [adapter], retry_base_seconds=2, retry_max_seconds=8)
    first = scheduler.run_once("flaky")
    assert first.state == "error"
    assert first.next_run is not None
    second = scheduler.run_once("flaky")
    assert second.state == "not_due"
    successful = scheduler.run_once("flaky", force=True)
    assert successful.state == "ok"
    scheduler.stop()


def test_scheduler_rate_limit_skips_without_download(tmp_path: Path):
    provider = ThreatProvider("limited", "Limited", "test")
    client = FakeClient(b'[{"value":"198.51.100.21","type":"ip"}]')
    adapter = FeedAdapter(provider, "https://feed.example", client=client, rate_limit_seconds=600)
    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    store.register_provider(provider)
    scheduler = FeedScheduler(ThreatProviderRegistry([provider]), store, [adapter])
    assert scheduler.run_once("limited").state == "ok"
    assert scheduler.run_once("limited", force=True).state == "rate_limited"
    assert client.calls == 1
    scheduler.stop()


def test_old_indicators_expire(tmp_path: Path):
    provider = ThreatProvider("expiry", "Expiry", "test")
    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    store.register_provider(provider)
    old = datetime.now(UTC) - timedelta(days=2)
    store.store_indicators(
        "expiry",
        [ThreatIndicator("203.0.113.22", "ip", source="expiry", first_seen=old, last_seen=old, expires_at=old + timedelta(seconds=1))],
    )
    assert store.expire(datetime.now(UTC)) == 1
    assert store.indicators(provider_id="expiry") == []


def test_registry_contains_phase_one_and_extension_sources(tmp_path: Path):
    registry, store, scheduler = build_feed_registry(env={"SUPERMARKT_DATA_DIR": str(tmp_path)})
    provider_ids = {provider.id for provider in registry.all()}
    assert {"abusech-threatfox", "abusech-urlhaus", "abusech-feodo", "abusech-malwarebazaar", "spamhaus-drop", "ripe-stat", "ripe-ris", "rpki-validator"} <= provider_ids
    assert provider_ids <= set(scheduler.adapters)
    assert len(store.provider_status()) == len(provider_ids)
    scheduler.stop()


def test_intelligence_and_network_routes_expose_persisted_views(monkeypatch, tmp_path: Path):
    from supermarkt.clawforge.feed_sync import IntelligenceService

    service = IntelligenceService.create(env={"SUPERMARKT_DATA_DIR": str(tmp_path)})
    monkeypatch.setattr(runtime, "get_intelligence", lambda: service)
    client = TestClient(app)
    assert client.get("/intelligence/providers").status_code == 200
    assert client.get("/intelligence/status").status_code == 200
    assert client.get("/intelligence/indicators").status_code == 200
    assert client.get("/network/asn").status_code == 200
    assert client.get("/network/bgp").status_code == 200
    assert client.get("/network/trust").status_code == 200
    service.stop()
