import os
from pathlib import Path

import pytest

from supermarkt.clawforge.backup import BackupManager
from supermarkt.clawforge.feed_sync import IntelligenceStore
from supermarkt.clawforge.intelligence import ThreatIndicator, ThreatProvider
from supermarkt.clawforge.network_trust import TrustedNetworkRegistry
from supermarkt.clawforge.persistence import PostgreSQLBackend, SQLiteBackend, backend_from_environment
from supermarkt.intelligence_worker import run_worker


def test_migrations_create_all_intelligence_tables(tmp_path: Path):
    store = IntelligenceStore(tmp_path / "intelligence.sqlite3")
    names = {
        row[0]
        for row in store._connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "schema_migrations",
        "providers",
        "provider_status",
        "indicators",
        "asn_records",
        "bgp_events",
        "risk_history",
        "trust_history",
        "audit_events",
    } <= names
    assert [row[0] for row in store._connect().execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3, 4]


def test_sqlite_backend_restart_and_backup_restore(tmp_path: Path):
    db_path = tmp_path / "source.sqlite3"
    store = IntelligenceStore(db_path)
    provider = ThreatProvider("backup-feed", "Backup Feed", "test")
    store.register_provider(provider)
    store.store_indicators(provider.id, [ThreatIndicator("203.0.113.44", "ip", source=provider.id, confidence=70)])
    store.record_audit_event("backup-test", subject="source", details={"ok": True})
    trust = TrustedNetworkRegistry()
    network = trust.register(name="Backup VLAN", type="vlan", network="192.0.2.0/24")
    trust.verify(network.id)
    config = tmp_path / "config.env"
    secret = tmp_path / "token"
    config.write_text("CLAWFORGE_INTELLIGENCE_BACKEND=sqlite\n", encoding="utf-8")
    secret.write_text("secret-value\n", encoding="utf-8")

    bundle = BackupManager.create(store, tmp_path / "backup", config_paths=[config], secret_paths=[secret], trust_registry=trust)
    restored_trust = BackupManager.restore(bundle, tmp_path / "restored")
    restored = IntelligenceStore(tmp_path / "restored" / "intelligence.sqlite3")
    assert len(restored.indicators(provider_id=provider.id)) == 1
    assert len(restored.audit_events(event_type="backup-test")) == 1
    assert restored_trust is not None and restored_trust.list()[0].name == "Backup VLAN"
    assert (tmp_path / "restored" / "secrets" / "token").read_text(encoding="utf-8") == "secret-value\n"


def test_backend_selection_keeps_sqlite_as_fallback(tmp_path: Path):
    backend = backend_from_environment({}, tmp_path / "intelligence.sqlite3")
    assert isinstance(backend, SQLiteBackend)
    with pytest.raises(ValueError):
        backend_from_environment({"CLAWFORGE_INTELLIGENCE_BACKEND": "postgres"}, tmp_path / "x.sqlite3")


def test_worker_entrypoint_can_stop_without_leaving_scheduler_running():
    class Scheduler:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self, poll_seconds):
            self.started = poll_seconds

        def stop(self):
            self.stopped = True

    class Service:
        def __init__(self):
            self.scheduler = Scheduler()

        def stop(self):
            self.scheduler.stop()

    import threading

    service = Service()
    stop = threading.Event()
    stop.set()
    run_worker(service=service, poll_seconds=1, stop_event=stop)
    assert service.scheduler.started == 1
    assert service.scheduler.stopped is True


@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1" or not os.getenv("CLAWFORGE_POSTGRES_DSN"),
    reason="set RUN_POSTGRES_TESTS=1 and CLAWFORGE_POSTGRES_DSN for PostgreSQL testcontainer/DSN",
)
def test_postgresql_backend_persists_across_restarts():
    backend = PostgreSQLBackend(os.environ["CLAWFORGE_POSTGRES_DSN"])
    first = IntelligenceStore("/tmp/clawforge-postgres-placeholder.sqlite3", backend=backend)
    provider = ThreatProvider("postgres-feed", "Postgres Feed", "test")
    first.register_provider(provider)
    first.store_indicators(provider.id, [ThreatIndicator("198.51.100.22", "ip", source=provider.id)])
    second = IntelligenceStore("/tmp/clawforge-postgres-placeholder.sqlite3", backend=backend)
    assert len(second.indicators(provider_id=provider.id)) == 1
