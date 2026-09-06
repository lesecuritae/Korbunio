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
    IntelligenceConsumer,
    IntelligenceStore,
    build_feed_registry,
    parse_feodo,
    parse_threatfox,
    parse_urlhaus,
)
from supermarkt.clawforge.intelligence import BGPRoute, IndicatorType, ThreatIndicator, ThreatProvider, ThreatProviderRegistry
from supermarkt.clawforge.network_trust import NetworkObservation, TrustedNetworkRegistry
from supermarkt.clawforge.risk_engine import Decision


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
    assert store.audit_events(event_type="intelligence_provider_error")[0]["subject"] == "broken"
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
    store.attach_consumer(IntelligenceConsumer(store))
    old = datetime.now(UTC) - timedelta(days=2)
    store.store_indicators(
        "expiry",
        [ThreatIndicator("203.0.113.22", "ip", source="expiry", first_seen=old, last_seen=old, expires_at=old + timedelta(seconds=1))],
    )
    assert store.expire(datetime.now(UTC)) == 1
    assert store.indicators(provider_id="expiry") == []
    assert store.risk_events(indicator="203.0.113.22") == []


def test_consumer_persists_indicator_risk_event_and_survives_restart(tmp_path: Path):
    db_path = tmp_path / "intelligence.sqlite3"
    store = IntelligenceStore(db_path)
    provider = ThreatProvider("threatfox", "ThreatFox", "abuse.ch")
    store.register_provider(provider)
    store.attach_consumer(IntelligenceConsumer(store))
    indicator = ThreatIndicator(
        "203.0.113.70", "ip", categories=("botnet-c2",), confidence=90, source="threatfox"
    )
    assert store.store_indicators(provider.id, [indicator]) == 1
    events = store.risk_events(indicator=indicator.value)
    assert len(events) == 1
    assert events[0]["source"] == "threatfox"
    assert events[0]["score_change"] > 0
    assert events[0]["reason"]

    restarted = IntelligenceStore(db_path)
    assert len(restarted.indicators(provider_id=provider.id)) == 1
    assert len(restarted.risk_events(indicator=indicator.value)) == 1
    assert {row[0] for row in restarted._connect().execute("SELECT version FROM schema_migrations")} == {1, 2, 3, 4}


def test_duplicate_indicator_does_not_create_duplicate_risk_event(tmp_path: Path):
    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    provider = ThreatProvider("feed", "Feed", "test")
    store.register_provider(provider)
    store.attach_consumer(IntelligenceConsumer(store))
    indicator = ThreatIndicator("198.51.100.70", "ip", confidence=80, source="feed")
    store.store_indicators(provider.id, [indicator])
    store.store_indicators(provider.id, [indicator])
    assert len(store.risk_events(indicator=indicator.value)) == 1


def test_multiple_provider_signals_raise_correlated_indicator_risk(tmp_path: Path):
    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    first = ThreatProvider("feed-a", "Feed A", "a")
    second = ThreatProvider("feed-b", "Feed B", "b")
    store.register_provider(first)
    store.register_provider(second)
    store.attach_consumer(IntelligenceConsumer(store))
    value = "198.51.100.71"
    store.store_indicators(first.id, [ThreatIndicator(value, "ip", confidence=30, source="feed-a")])
    first_event = store.risk_events(indicator=value)[0]
    store.store_indicators(second.id, [ThreatIndicator(value, "ip", confidence=30, source="feed-b")])
    latest = store.risk_events(indicator=value)
    assert len(latest) == 2
    assert latest[0]["score_change"] > first_event["score_change"]


def test_trusted_network_reduces_indicator_risk_and_single_feed_cannot_block(tmp_path: Path):
    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    trust = TrustedNetworkRegistry()
    network = trust.register(name="Server VLAN", type="vlan", networks=("203.0.113.0/24",))
    trust.verify(network.id)
    consumer = IntelligenceConsumer(store, trusted_networks=trust)
    indicator = ThreatIndicator("203.0.113.8", "ip", confidence=100, source="one-feed")
    untrusted_event, untrusted = IntelligenceConsumer(store).evaluate_indicator(indicator, persist=False)
    trusted_event, trusted = consumer.evaluate_indicator(
        indicator, observation=NetworkObservation(ip=indicator.value), persist=False
    )
    assert trusted.risk.risk_score < untrusted.risk.risk_score
    assert trusted.risk.trust_score >= 40
    assert trusted.policy.decision is not Decision.BLOCK
    assert untrusted_event.score_change > trusted_event.score_change


def test_bgp_history_is_deduplicated_and_records_origin_changes(tmp_path: Path):
    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    store.attach_consumer(IntelligenceConsumer(store))
    route = BGPRoute("203.0.113.0/24", "AS64500", stable_days=40, rpki_status="valid")
    assert store.store_bgp_routes("ripe-ris", [route]) == 1
    assert store.store_bgp_routes("ripe-ris", [route]) == 0
    assert len(store.bgp_events(prefix=route.prefix)) == 1
    changed = BGPRoute(
        route.prefix, "AS64501", status="changed", rpki_status="invalid", previous_origin_asn="AS64500"
    )
    assert store.store_bgp_routes("ripe-ris", [changed]) == 1
    rows = store.bgp_events(prefix=route.prefix)
    assert len(rows) == 2
    current = next(row for row in rows if row["origin_asn"] == "AS64501")
    assert current["change"] == "origin_changed"
    assert current["first_seen"] and current["last_seen"]
    assert any(row["source"] == "ripe-ris" for row in store.risk_events(indicator=route.prefix))
    assert store._connect().execute("SELECT COUNT(*) FROM trust_history").fetchone()[0] >= 1


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
