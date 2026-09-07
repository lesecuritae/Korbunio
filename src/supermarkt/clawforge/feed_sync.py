"""Production feed synchronization for Clawforge intelligence providers.

The synchronizer deliberately stops at storing normalized intelligence.  Feed
records never trigger a response directly; consumers pass them to the existing
risk and policy engines.
"""

from __future__ import annotations

import ipaddress
import json
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .intelligence import (
    ASNRecord,
    BGPRoute,
    IndicatorType,
    ThreatIndicator,
    ThreatProvider,
    ThreatProviderRegistry,
    normalize_indicator,
)
from .network_trust import NetworkObservation, TrustedNetworkRegistry
from .persistence import DatabaseBackend, Migration, MigrationRunner, SQLiteBackend, backend_from_environment
from .risk_engine import RiskEngine, RiskSignals


class FeedSyncError(RuntimeError):
    """A provider failed validation, transport, or normalization."""


class FeedTimeoutError(FeedSyncError):
    pass


class FeedRateLimitError(FeedSyncError):
    pass


@dataclass(frozen=True)
class HTTPFeedResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]


class FeedHTTPClient:
    """Small stdlib transport with bounded timeouts and injectable requests."""

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 20.0,
    ) -> HTTPFeedResponse:
        request = Request(url, data=body, headers=dict(headers or {}), method=method)
        try:
            with urlopen(request, timeout=max(1.0, float(timeout))) as response:  # nosec B310 - endpoints are configured providers
                return HTTPFeedResponse(
                    status_code=int(response.status),
                    body=response.read(50 * 1024 * 1024 + 1),
                    headers={str(key).casefold(): str(value) for key, value in response.headers.items()},
                )
        except HTTPError as exc:
            body = exc.read(4096) if exc.fp else b""
            raise FeedSyncError(f"HTTP {exc.code} from {url}: {body[:200]!r}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise FeedSyncError(f"transport error from {url}: {exc}") from exc


def _utc(value: Any, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif value:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            try:
                result = parsedate_to_datetime(text)
            except (TypeError, ValueError, OverflowError):
                result = default or datetime.now(UTC)
    else:
        result = default or datetime.now(UTC)
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def _categories(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _records(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        value = payload.get("data", payload.get("results", payload.get("urls", payload.get("iocs", ()))) )
        if isinstance(value, Mapping):
            value = tuple(value.values())
        if not isinstance(value, (list, tuple)):
            value = (value,) if value else ()
    elif isinstance(payload, (list, tuple)):
        value = payload
    else:
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _indicator(
    value: Any,
    kind: IndicatorType | str,
    *,
    source: str,
    categories: Any = (),
    confidence: Any = 50,
    first_seen: Any = None,
    last_seen: Any = None,
    expires_at: Any = None,
    metadata: Mapping[str, Any] | None = None,
    ttl_days: int = 30,
) -> ThreatIndicator:
    now = datetime.now(UTC)
    first = _utc(first_seen, now)
    last = _utc(last_seen, first)
    expiry = _utc(expires_at, last + timedelta(days=ttl_days))
    return normalize_indicator(
        ThreatIndicator(
            str(value).strip(),
            kind,
            _categories(categories),
            int(confidence or 0),
            source,
            observed_at=last,
            first_seen=first,
            last_seen=last,
            expires_at=expiry,
            metadata=dict(metadata or {}),
        )
    )


def _ioc_type(value: str) -> IndicatorType:
    value = value.casefold()
    if value in {"ip", "ip:port", "ipv4", "ipv6"}:
        return IndicatorType.IP
    if value in {"url", "uri"}:
        return IndicatorType.URL
    if value in {"sha256", "sha256_hash", "sha1", "md5", "hash"}:
        return IndicatorType.HASH
    if value in {"prefix", "cidr", "network"}:
        return IndicatorType.PREFIX
    if value in {"asn", "autonomous-system", "autonomous_system"}:
        return IndicatorType.ASN
    return IndicatorType.DOMAIN


def _strip_port(value: str) -> str:
    if value.count(":") == 1 and value.rsplit(":", 1)[1].isdigit():
        return value.rsplit(":", 1)[0]
    return value.strip("[]")


def parse_urlhaus(payload: Any, source: str = "abusech-urlhaus") -> Iterable[ThreatIndicator]:
    for item in _records(payload):
        value = item.get("url") or item.get("ioc")
        if value:
            yield _indicator(value, IndicatorType.URL, source=source, categories=("malware-url", item.get("threat")), confidence=item.get("confidence", 80), first_seen=item.get("dateadded"), last_seen=item.get("last_online"), metadata={"host": item.get("host"), "url_status": item.get("url_status")})


def parse_threatfox(payload: Any, source: str = "abusech-threatfox") -> Iterable[ThreatIndicator]:
    for item in _records(payload):
        value = item.get("ioc") or item.get("value")
        if not value:
            continue
        kind = _ioc_type(str(item.get("ioc_type") or item.get("type") or "domain"))
        yield _indicator(_strip_port(str(value)) if kind is IndicatorType.IP else value, kind, source=source, categories=("ioc", item.get("threat_type"), item.get("malware")), confidence=item.get("confidence_level", 50), first_seen=item.get("first_seen"), last_seen=item.get("last_seen"), metadata={"malware": item.get("malware"), "reference": item.get("reference")})


def parse_feodo(payload: Any, source: str = "abusech-feodo") -> Iterable[ThreatIndicator]:
    for item in _records(payload):
        value = item.get("ip_address") or item.get("ip") or item.get("ioc")
        if value:
            yield _indicator(value, IndicatorType.IP, source=source, categories=("botnet-c2", item.get("malware")), confidence=90, first_seen=item.get("first_seen_utc") or item.get("first_seen"), last_seen=item.get("last_online") or item.get("last_seen"), metadata={"malware": item.get("malware"), "port": item.get("port"), "status": item.get("status")})


def parse_malwarebazaar(payload: Any, source: str = "abusech-malwarebazaar") -> Iterable[ThreatIndicator]:
    for item in _records(payload):
        value = item.get("sha256_hash") or item.get("sha256") or item.get("md5_hash")
        if value:
            yield _indicator(value, IndicatorType.HASH, source=source, categories=("malware-hash", item.get("signature") or item.get("malware_family")), confidence=90, first_seen=item.get("first_seen"), last_seen=item.get("last_seen"), metadata={"signature": item.get("signature"), "file_type": item.get("file_type")})


def parse_text_indicators(payload: Any, source: str, category: str = "reputation") -> Iterable[ThreatIndicator]:
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload or "")
    for line in text.splitlines():
        value = line.strip().split("#", 1)[0].strip()
        if not value:
            continue
        kind: IndicatorType | str = IndicatorType.PREFIX if "/" in value else IndicatorType.IP
        try:
            ipaddress.ip_network(value, strict=False) if kind is IndicatorType.PREFIX else ipaddress.ip_address(value)
        except ValueError:
            continue
        yield _indicator(value, kind, source=source, categories=(category,), confidence=75)


def parse_openphish(payload: Any, source: str = "openphish") -> Iterable[ThreatIndicator]:
    for line in (payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload or "")).splitlines():
        value = line.strip()
        if value.startswith(("http://", "https://")):
            yield _indicator(value, IndicatorType.URL, source=source, categories=("phishing",), confidence=85)


def parse_cisa_kev(payload: Any, source: str = "cisa-kev") -> Iterable[ThreatIndicator]:
    for item in _records(payload):
        value = item.get("cveID") or item.get("cve")
        if value:
            yield _indicator(value, IndicatorType.DOMAIN, source=source, categories=("known-exploited-vulnerability",), confidence=95, first_seen=item.get("dateAdded"), last_seen=item.get("dateAdded"), metadata={"vendor": item.get("vendorProject"), "product": item.get("product")})


def parse_nvd(payload: Any, source: str = "nvd") -> Iterable[ThreatIndicator]:
    for item in (payload.get("vulnerabilities", ()) if isinstance(payload, Mapping) else ()):
        if not isinstance(item, Mapping):
            continue
        cve = item.get("cve", {})
        value = cve.get("id") if isinstance(cve, Mapping) else None
        if value:
            yield _indicator(value, IndicatorType.DOMAIN, source=source, categories=("cve",), confidence=60, metadata={"source_identifier": cve.get("sourceIdentifier") if isinstance(cve, Mapping) else ""})


_MIGRATIONS = (
    Migration(
        1,
        "initial intelligence schema",
        """
        CREATE TABLE IF NOT EXISTS providers (
            provider_id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL, confidence INTEGER NOT NULL,
            categories TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS provider_status (
            provider_id TEXT PRIMARY KEY REFERENCES providers(provider_id),
            state TEXT NOT NULL, last_attempt TEXT, last_success TEXT,
            next_run TEXT, failure_count INTEGER NOT NULL DEFAULT 0,
            error TEXT, retry_after TEXT, indicators_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS indicators (
            id INTEGER PRIMARY KEY AUTOINCREMENT, provider_id TEXT NOT NULL,
            indicator_type TEXT NOT NULL, value TEXT NOT NULL,
            categories TEXT NOT NULL, confidence INTEGER NOT NULL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, expires_at TEXT NOT NULL,
            observed_at TEXT, metadata TEXT NOT NULL,
            UNIQUE(provider_id, indicator_type, value)
        );
        CREATE INDEX IF NOT EXISTS idx_indicators_expiry ON indicators(expires_at);
        CREATE TABLE IF NOT EXISTS asn_records (
            provider_id TEXT NOT NULL, asn TEXT NOT NULL, organisation TEXT,
            provider TEXT, country TEXT, prefixes TEXT NOT NULL,
            network_type TEXT, reputation INTEGER NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(provider_id, asn)
        );
        CREATE TABLE IF NOT EXISTS bgp_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, provider_id TEXT NOT NULL,
            prefix TEXT NOT NULL, origin_asn TEXT NOT NULL, status TEXT,
            stable_days INTEGER NOT NULL, rpki_status TEXT, previous_origin_asn TEXT,
            observed_at TEXT NOT NULL,
            UNIQUE(provider_id, prefix, origin_asn, observed_at)
        );
        CREATE TABLE IF NOT EXISTS risk_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL,
            risk_score INTEGER NOT NULL, reasons TEXT NOT NULL, observed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trust_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL,
            trust_score INTEGER NOT NULL, reasons TEXT NOT NULL, observed_at TEXT NOT NULL
        );
        """,
    ),
    Migration(
        2,
        "risk and route history fields",
        """
        ALTER TABLE risk_history ADD COLUMN indicator TEXT NOT NULL DEFAULT '';
        ALTER TABLE risk_history ADD COLUMN source TEXT NOT NULL DEFAULT '';
        ALTER TABLE risk_history ADD COLUMN score_change INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE risk_history ADD COLUMN reason TEXT NOT NULL DEFAULT '';
        ALTER TABLE risk_history ADD COLUMN timestamp TEXT;
        ALTER TABLE bgp_events ADD COLUMN asn TEXT NOT NULL DEFAULT '';
        ALTER TABLE bgp_events ADD COLUMN origin TEXT NOT NULL DEFAULT '';
        ALTER TABLE bgp_events ADD COLUMN first_seen TEXT;
        ALTER TABLE bgp_events ADD COLUMN last_seen TEXT;
        ALTER TABLE bgp_events ADD COLUMN change TEXT NOT NULL DEFAULT '';
        """,
    ),
    Migration(
        3,
        "deduplicated BGP route history",
        """
        ALTER TABLE bgp_events RENAME TO bgp_events_legacy;
        CREATE TABLE bgp_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, provider_id TEXT NOT NULL,
            prefix TEXT NOT NULL, origin_asn TEXT NOT NULL,
            asn TEXT NOT NULL, origin TEXT NOT NULL, status TEXT,
            stable_days INTEGER NOT NULL, rpki_status TEXT,
            previous_origin_asn TEXT, observed_at TEXT NOT NULL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            change TEXT NOT NULL DEFAULT '',
            UNIQUE(provider_id, prefix, origin_asn)
        );
        INSERT INTO bgp_events(
            provider_id,prefix,origin_asn,asn,origin,status,stable_days,rpki_status,
            previous_origin_asn,observed_at,first_seen,last_seen,change
        )
        SELECT provider_id,prefix,origin_asn,
            CASE WHEN MAX(asn) = '' THEN origin_asn ELSE MAX(asn) END,
            CASE WHEN MAX(origin) = '' THEN origin_asn ELSE MAX(origin) END,
            MAX(status),MAX(stable_days),MAX(rpki_status),MAX(previous_origin_asn),
            MAX(observed_at),
            COALESCE(MIN(first_seen), MIN(observed_at)),
            COALESCE(MAX(last_seen), MAX(observed_at)),
            COALESCE(MAX(change), '')
        FROM bgp_events_legacy
        GROUP BY provider_id,prefix,origin_asn;
        DROP TABLE bgp_events_legacy;
        CREATE INDEX idx_bgp_events_prefix ON bgp_events(prefix);
        """,
    ),
    Migration(
        4,
        "audit event history",
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at);
        """,
    ),
)


class IntelligenceStore:
    """Persistent intelligence repository behind a small database boundary."""

    def __init__(self, path: str | os.PathLike[str], *, backend: DatabaseBackend | None = None) -> None:
        self.path = str(path)
        self.backend = backend or SQLiteBackend(self.path)
        self._lock = threading.RLock()
        self._consumer: IntelligenceConsumer | None = None
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._initialize()

    def _connect(self) -> Any:
        return self.backend.connect()

    def _initialize(self) -> None:
        with self._lock, self._connect() as db:
            MigrationRunner.run(db, _MIGRATIONS)

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat() if value else None

    def attach_consumer(self, consumer: "IntelligenceConsumer") -> None:
        """Attach the evaluator used for newly stored intelligence."""
        self._consumer = consumer

    def _ensure_consumer(self) -> "IntelligenceConsumer":
        if self._consumer is None:
            self._consumer = IntelligenceConsumer(self)
        return self._consumer

    def register_provider(self, provider: ThreatProvider) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO providers(provider_id,name,source,interval_seconds,confidence,categories,enabled)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(provider_id) DO UPDATE SET name=excluded.name,
                source=excluded.source, interval_seconds=excluded.interval_seconds,
                confidence=excluded.confidence, categories=excluded.categories, enabled=excluded.enabled""",
                (provider.id, provider.name, provider.source, int(provider.update_interval.total_seconds()), provider.confidence, json.dumps(provider.categories), int(provider.enabled)),
            )
            db.execute(
                "INSERT INTO provider_status(provider_id,state) VALUES(?,?) "
                "ON CONFLICT(provider_id) DO NOTHING",
                (provider.id, "never"),
            )

    def update_provider_status(self, provider_id: str, **values: Any) -> None:
        allowed = {"state", "last_attempt", "last_success", "next_run", "failure_count", "error", "retry_after", "indicators_count"}
        values = {key: self._iso(value) if isinstance(value, datetime) else value for key, value in values.items() if key in allowed}
        if not values:
            return
        columns = ", ".join(f"{key} = ?" for key in values)
        with self._lock, self._connect() as db:
            # Column names are selected exclusively from the allowlist above.
            db.execute(f"UPDATE provider_status SET {columns} WHERE provider_id = ?", (*values.values(), provider_id))  # nosec B608

    def provider_status(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT p.*, s.state, s.last_attempt, s.last_success, s.next_run, s.failure_count, s.error, s.retry_after, s.indicators_count FROM providers p JOIN provider_status s USING(provider_id) ORDER BY provider_id").fetchall()
        return [dict(row) for row in rows]

    def store_indicators(self, provider_id: str, indicators: Iterable[ThreatIndicator]) -> int:
        count = 0
        to_assess: list[ThreatIndicator] = []
        with self._lock, self._connect() as db:
            for item in indicators:
                now = datetime.now(UTC)
                first = item.first_seen or item.observed_at or now
                last = item.last_seen or item.observed_at or first
                expires = item.expires_at or last + timedelta(days=30)
                existing = db.execute(
                    "SELECT confidence,categories,metadata FROM indicators "
                    "WHERE provider_id = ? AND indicator_type = ? AND value = ?",
                    (provider_id, item.indicator_type.value, item.value),
                ).fetchone()
                db.execute(
                    """INSERT INTO indicators(provider_id,indicator_type,value,categories,confidence,first_seen,last_seen,expires_at,observed_at,metadata)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider_id,indicator_type,value) DO UPDATE SET
                    categories=excluded.categories, confidence=excluded.confidence,
                    first_seen=MIN(indicators.first_seen,excluded.first_seen),
                    last_seen=MAX(indicators.last_seen,excluded.last_seen), expires_at=excluded.expires_at,
                    observed_at=excluded.observed_at, metadata=excluded.metadata""",
                    (provider_id, item.indicator_type.value, item.value, json.dumps(item.categories), item.confidence, self._iso(first), self._iso(last), self._iso(expires), self._iso(item.observed_at), json.dumps(dict(item.metadata), default=str)),
                )
                if expires > now and (existing is None or (
                    int(existing["confidence"]) != item.confidence
                    or str(existing["categories"]) != json.dumps(item.categories)
                    or str(existing["metadata"]) != json.dumps(dict(item.metadata), default=str)
                )):
                    to_assess.append(item)
                count += 1
        if to_assess:
            self._ensure_consumer().consume_indicators(to_assess)
        return count

    def expire(self, now: datetime | None = None) -> int:
        value = self._iso(now or datetime.now(UTC))
        with self._lock, self._connect() as db:
            result = db.execute("DELETE FROM indicators WHERE expires_at <= ?", (value,))
            return result.rowcount

    def indicators(self, *, provider_id: str | None = None, limit: int = 1000, include_expired: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM indicators"
        params: list[Any] = []
        clauses: list[str] = []
        if provider_id:
            clauses.append("provider_id = ?")
            params.append(provider_id)
        if not include_expired:
            clauses.append("expires_at > ?")
            params.append(self._iso(datetime.now(UTC)))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY last_seen DESC LIMIT ?"
        params.append(max(1, min(10000, int(limit))))
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def indicator_objects(self, *, provider_id: str | None = None, limit: int = 1000, include_expired: bool = False) -> tuple[ThreatIndicator, ...]:
        values = [
                ThreatIndicator(
                    row["value"],
                    row["indicator_type"],
                    tuple(json.loads(row["categories"])),
                    int(row["confidence"]),
                    row["provider_id"],
                    observed_at=_utc(row.get("observed_at")),
                    first_seen=_utc(row.get("first_seen")),
                    last_seen=_utc(row.get("last_seen")),
                    expires_at=_utc(row.get("expires_at")),
                    metadata=json.loads(row["metadata"]),
                )
                for row in self.indicators(provider_id=provider_id, limit=limit, include_expired=include_expired)
        ]
        return tuple(values)

    def store_asn_records(self, provider_id: str, records: Iterable[ASNRecord]) -> int:
        count = 0
        now = self._iso(datetime.now(UTC))
        with self._lock, self._connect() as db:
            for record in records:
                db.execute("""INSERT INTO asn_records(provider_id,asn,organisation,provider,country,prefixes,network_type,reputation,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(provider_id,asn) DO UPDATE SET organisation=excluded.organisation,
                provider=excluded.provider,country=excluded.country,prefixes=excluded.prefixes,network_type=excluded.network_type,
                reputation=excluded.reputation,updated_at=excluded.updated_at""", (provider_id, record.asn, record.organisation, record.provider, record.country, json.dumps(record.prefixes), record.network_type.value, record.reputation, now))
                count += 1
        return count

    def asn_records(self, asn: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        query = "SELECT * FROM asn_records"
        params: list[Any] = []
        if asn:
            query += " WHERE asn = ?"
            params.append(str(asn).upper().removeprefix("AS"))
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(10000, int(limit))))
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def store_bgp_routes(self, provider_id: str, routes: Iterable[BGPRoute]) -> int:
        count = 0
        to_assess: list[tuple[BGPRoute, str]] = []
        with self._lock, self._connect() as db:
            for route in routes:
                observed_at = route.last_seen or datetime.now(UTC)
                first_seen = route.first_seen or observed_at
                existing = db.execute(
                    "SELECT * FROM bgp_events WHERE provider_id = ? AND prefix = ? AND origin_asn = ?",
                    (provider_id, route.prefix, route.origin_asn),
                ).fetchone()
                previous = db.execute(
                    "SELECT origin_asn FROM bgp_events WHERE provider_id = ? AND prefix = ? "
                    "ORDER BY last_seen DESC LIMIT 1",
                    (provider_id, route.prefix),
                ).fetchone()
                origin_changed = bool(previous and str(previous["origin_asn"]) != route.origin_asn)
                change = route.status if route.status in {"changed", "anomalous"} else ""
                if route.previous_origin_asn or origin_changed:
                    change = "origin_changed"
                if existing is None:
                    db.execute(
                        """INSERT INTO bgp_events(
                        provider_id,prefix,origin_asn,asn,origin,status,stable_days,rpki_status,
                        previous_origin_asn,observed_at,first_seen,last_seen,change
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (provider_id, route.prefix, route.origin_asn, route.origin_asn, route.origin_asn,
                         route.status, route.stable_days, route.rpki_status, route.previous_origin_asn,
                         self._iso(observed_at), self._iso(first_seen), self._iso(observed_at), change),
                    )
                    count += 1
                    to_assess.append((route, provider_id))
                    continue
                materially_changed = any(
                    str(existing[key]) != str(value)
                    for key, value in (
                        ("status", route.status),
                        ("stable_days", route.stable_days),
                        ("rpki_status", route.rpki_status),
                        ("previous_origin_asn", route.previous_origin_asn),
                        ("change", change),
                    )
                )
                db.execute(
                    """UPDATE bgp_events SET status=?,stable_days=?,rpki_status=?,
                    previous_origin_asn=?,observed_at=?,first_seen=MIN(first_seen,?),
                    last_seen=?,change=? WHERE id=?""",
                    (route.status, route.stable_days, route.rpki_status, route.previous_origin_asn,
                     self._iso(observed_at), self._iso(first_seen), self._iso(observed_at), change, existing["id"]),
                )
                if materially_changed:
                    count += 1
                    to_assess.append((route, provider_id))
        if to_assess:
            self._ensure_consumer().consume_bgp_routes(to_assess)
        return count

    def bgp_events(self, prefix: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        query = "SELECT * FROM bgp_events"
        params: list[Any] = []
        if prefix:
            query += " WHERE prefix = ?"
            params.append(prefix)
        query += " ORDER BY observed_at DESC LIMIT ?"
        params.append(max(1, min(10000, int(limit))))
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def record_risk(self, subject: str, risk_score: int, reasons: Iterable[str] = ()) -> None:
        values = tuple(reasons)
        with self._lock, self._connect() as db:
            now = self._iso(datetime.now(UTC))
            db.execute(
                "INSERT INTO risk_history(subject,risk_score,reasons,observed_at,indicator,source,score_change,reason,timestamp) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (subject, int(risk_score), json.dumps(values), now, subject, "", int(risk_score), "; ".join(values), now),
            )

    def record_risk_event(
        self,
        *,
        indicator: str,
        source: str,
        score_change: int,
        risk_score: int,
        trust_score: int,
        reason: str,
        timestamp: datetime | None = None,
    ) -> None:
        event_time = timestamp or datetime.now(UTC)
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO risk_history(subject,risk_score,reasons,observed_at,indicator,source,score_change,reason,timestamp) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (indicator, int(risk_score), json.dumps((reason,)), self._iso(event_time), indicator, source,
                 int(score_change), reason, self._iso(event_time)),
            )

    def risk_events(self, *, indicator: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        query = "SELECT * FROM risk_history"
        params: list[Any] = []
        if indicator:
            query += " WHERE indicator = ?"
            params.append(indicator)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(max(1, min(10000, int(limit))))
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def record_trust(self, subject: str, trust_score: int, reasons: Iterable[str] = ()) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO trust_history(subject,trust_score,reasons,observed_at) VALUES(?,?,?,?)", (subject, int(trust_score), json.dumps(tuple(reasons)), self._iso(datetime.now(UTC))))

    def record_audit_event(
        self,
        event_type: str,
        *,
        actor: str = "system",
        subject: str = "",
        details: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO audit_events(event_type,actor,subject,details,created_at) VALUES(?,?,?,?,?)",
                (event_type, actor, subject, json.dumps(dict(details or {}), default=str), self._iso(created_at or datetime.now(UTC))),
            )

    def audit_events(self, *, event_type: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_events"
        params: list[Any] = []
        if event_type:
            query += " WHERE event_type = ?"
            params.append(event_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(10000, int(limit))))
        with self._lock, self._connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]


@dataclass(frozen=True)
class RiskEvent:
    indicator: str
    source: str
    score_change: int
    risk_score: int
    trust_score: int
    reason: str
    timestamp: datetime


class IntelligenceConsumer:
    """Connect normalized intelligence to the existing risk and policy engine."""

    def __init__(
        self,
        store: IntelligenceStore,
        *,
        trusted_networks: TrustedNetworkRegistry | None = None,
        engine: RiskEngine | None = None,
    ) -> None:
        self.store = store
        self.trusted_networks = trusted_networks or TrustedNetworkRegistry()
        self.engine = engine or RiskEngine(self.trusted_networks)

    @staticmethod
    def _signals(indicator: ThreatIndicator, *, evidence_sources: Iterable[str] = ()) -> RiskSignals:
        categories = {str(value).casefold() for value in indicator.categories}
        source = indicator.source.casefold()
        reputation = min(30, max(0, round(indicator.confidence * 0.3)))
        ip_reputation = reputation if indicator.indicator_type is IndicatorType.IP else 0
        asn_reputation = reputation if indicator.indicator_type is IndicatorType.ASN or "asn" in categories or "asn" in source else 0
        domain_reputation = reputation if indicator.indicator_type in (IndicatorType.DOMAIN, IndicatorType.URL) else 0
        sources = frozenset(value for value in evidence_sources if value) or frozenset({indicator.source})
        return RiskSignals(
            ip_reputation=ip_reputation,
            asn_reputation=asn_reputation,
            domain_reputation=domain_reputation,
            evidence_sources=sources,
            reasons=(f"{indicator.source}: {', '.join(indicator.categories) or 'indicator'}",),
        )

    @staticmethod
    def _observation(indicator: ThreatIndicator, observation: NetworkObservation | None = None) -> NetworkObservation:
        if observation is not None:
            return observation
        values: dict[str, Any] = {}
        if indicator.indicator_type is IndicatorType.IP:
            values["ip"] = indicator.value
        elif indicator.indicator_type is IndicatorType.PREFIX:
            values["prefix"] = indicator.value
        elif indicator.indicator_type is IndicatorType.ASN:
            values["asn"] = indicator.value
        return NetworkObservation(**values)

    def evaluate_indicator(
        self,
        indicator: ThreatIndicator,
        *,
        observation: NetworkObservation | None = None,
        related_indicators: Iterable[ThreatIndicator] = (),
        persist: bool = True,
    ) -> tuple[RiskEvent, Any]:
        network_observation = self._observation(indicator, observation)
        related = tuple(related_indicators) or (indicator,)
        signals = self._signals(indicator, evidence_sources=(item.source for item in related))
        baseline = self.engine.evaluate(network_observation)
        assessment = self.engine.evaluate(network_observation, indicators=related, signals=signals)
        reasons = tuple(dict.fromkeys((*assessment.signals.reasons, *assessment.risk.reasons, *assessment.policy.reasons)))
        reason = "; ".join(reasons) or f"{indicator.source} indicator"
        event = RiskEvent(
            indicator=indicator.value,
            source=indicator.source,
            score_change=assessment.risk.risk_score - baseline.risk.risk_score,
            risk_score=assessment.risk.risk_score,
            trust_score=assessment.risk.trust_score,
            reason=reason,
            timestamp=datetime.now(UTC),
        )
        if persist:
            self.store.record_risk_event(
                indicator=event.indicator,
                source=event.source,
                score_change=event.score_change,
                risk_score=event.risk_score,
                trust_score=event.trust_score,
                reason=event.reason,
                timestamp=event.timestamp,
            )
            if event.trust_score:
                self.store.record_trust(event.indicator, event.trust_score, reasons=(event.reason,))
        return event, assessment

    def consume_indicators(self, indicators: Iterable[ThreatIndicator]) -> tuple[RiskEvent, ...]:
        values = tuple(indicators)
        stored = self.store.indicator_objects()
        events = []
        for indicator in values:
            related = tuple(item for item in stored if item.value == indicator.value)
            events.append(self.evaluate_indicator(indicator, related_indicators=related)[0])
        return tuple(events)

    def consume_bgp_route(
        self,
        route: BGPRoute,
        source: str,
        *,
        observation: NetworkObservation | None = None,
        persist: bool = True,
    ) -> tuple[RiskEvent, Any]:
        network_observation = observation or NetworkObservation(
            prefix=route.prefix,
            asn=route.origin_asn,
            bgp_status=route.status,
            rpki_status=route.rpki_status,
        )
        signals = RiskSignals(evidence_sources=frozenset({source}), reasons=(f"{source}: route assessment",))
        baseline = self.engine.evaluate(NetworkObservation(prefix=route.prefix, asn=route.origin_asn))
        assessment = self.engine.evaluate(network_observation, signals=signals)
        reasons = tuple(dict.fromkeys((*assessment.signals.reasons, *assessment.risk.reasons, *assessment.policy.reasons)))
        event = RiskEvent(
            indicator=route.prefix,
            source=source,
            score_change=assessment.risk.risk_score - baseline.risk.risk_score,
            risk_score=assessment.risk.risk_score,
            trust_score=assessment.risk.trust_score,
            reason="; ".join(reasons) or f"{source} route assessment",
            timestamp=datetime.now(UTC),
        )
        if persist:
            self.store.record_risk_event(
                indicator=event.indicator,
                source=event.source,
                score_change=event.score_change,
                risk_score=event.risk_score,
                trust_score=event.trust_score,
                reason=event.reason,
                timestamp=event.timestamp,
            )
            if event.trust_score:
                self.store.record_trust(event.indicator, event.trust_score, reasons=(event.reason,))
        return event, assessment

    def consume_bgp_routes(self, routes: Iterable[tuple[BGPRoute, str]]) -> tuple[RiskEvent, ...]:
        return tuple(self.consume_bgp_route(route, source)[0] for route, source in routes)


class FeedAdapter:
    """Fetch/validate/normalize/store/expire lifecycle for one provider."""

    def __init__(self, provider: ThreatProvider, endpoint: str, *, parser: Callable[[Any, str], Iterable[ThreatIndicator]] | None = None, method: str = "GET", headers: Mapping[str, str] | None = None, body: bytes | None = None, timeout_seconds: float = 20.0, rate_limit_seconds: float = 60.0, ttl_days: int = 30, client: FeedHTTPClient | None = None) -> None:
        self.provider = provider
        self.endpoint = endpoint
        self.parser = parser
        self.method = method
        self.headers = dict(headers or {})
        self.body = body
        self.timeout_seconds = timeout_seconds
        self.rate_limit_seconds = max(0.0, rate_limit_seconds)
        self.ttl_days = ttl_days
        self.client = client or FeedHTTPClient()

    def fetch(self) -> Any:
        response = self.client.request(self.endpoint, method=self.method, headers=self.headers, body=self.body, timeout=self.timeout_seconds)
        if response.status_code >= 400:
            raise FeedSyncError(f"HTTP {response.status_code} from {self.provider.id}")
        content_type = response.headers.get("content-type", "")
        if "json" in content_type or response.body[:1] in (b"{", b"["):
            try:
                return json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FeedSyncError(f"invalid JSON from {self.provider.id}") from exc
        return response.body.decode("utf-8", "replace")

    def validate(self, payload: Any) -> Any:
        if payload is None or payload == "" or payload == [] or payload == {}:
            raise FeedSyncError(f"empty feed from {self.provider.id}")
        return payload

    def normalize(self, payload: Any) -> tuple[ThreatIndicator, ...]:
        parser = self.parser or (lambda value, source: self.provider.parse(value))
        values = tuple(parser(payload, self.provider.id))
        return tuple(_with_expiry(normalize_indicator(item), self.ttl_days) for item in values)

    def store(self, store: IntelligenceStore, indicators: Iterable[ThreatIndicator]) -> int:
        return store.store_indicators(self.provider.id, indicators)

    def expire(self, store: IntelligenceStore, now: datetime | None = None) -> int:
        return store.expire(now)

    def sync(self, store: IntelligenceStore) -> int:
        payload = self.validate(self.fetch())
        indicators = self.normalize(payload)
        return self.store(store, indicators)


def _with_expiry(item: ThreatIndicator, ttl_days: int) -> ThreatIndicator:
    now = datetime.now(UTC)
    first = item.first_seen or item.observed_at or now
    last = item.last_seen or item.observed_at or first
    expiry = item.expires_at or last + timedelta(days=ttl_days)
    return ThreatIndicator(**{**item.__dict__, "first_seen": first, "last_seen": last, "expires_at": expiry})


class ASNFeedAdapter(FeedAdapter):
    def __init__(self, provider: ThreatProvider, endpoint: str, *, parser: Callable[[Any, str], Iterable[ASNRecord]], **kwargs: Any) -> None:
        super().__init__(provider, endpoint, **kwargs)
        self.asn_parser = parser

    def normalize(self, payload: Any) -> tuple[ASNRecord, ...]:
        return tuple(self.asn_parser(payload, self.provider.id))

    def store(self, store: IntelligenceStore, indicators: Iterable[ASNRecord]) -> int:
        return store.store_asn_records(self.provider.id, indicators)


class BGPFeedAdapter(FeedAdapter):
    def __init__(self, provider: ThreatProvider, endpoint: str, *, parser: Callable[[Any, str], Iterable[BGPRoute]], **kwargs: Any) -> None:
        super().__init__(provider, endpoint, **kwargs)
        self.bgp_parser = parser

    def normalize(self, payload: Any) -> tuple[BGPRoute, ...]:
        return tuple(self.bgp_parser(payload, self.provider.id))

    def store(self, store: IntelligenceStore, indicators: Iterable[BGPRoute]) -> int:
        return store.store_bgp_routes(self.provider.id, indicators)


def parse_ripe_asn(payload: Any, _source: str) -> Iterable[ASNRecord]:
    data = payload.get("data", payload) if isinstance(payload, Mapping) else {}
    asn = str(data.get("asn") or data.get("resource") or "").upper().removeprefix("AS")
    if asn.isdigit():
        yield ASNRecord(asn, organisation=str(data.get("holder") or data.get("organisation") or ""), prefixes=tuple(str(item.get("prefix")) for item in data.get("prefixes", ()) if isinstance(item, Mapping) and item.get("prefix")))


def parse_bgpview_asn(payload: Any, _source: str) -> Iterable[ASNRecord]:
    data = payload.get("data", payload) if isinstance(payload, Mapping) else {}
    asn = str(data.get("asn") or data.get("asn_number") or "").upper().removeprefix("AS")
    prefixes = data.get("prefixes", ())
    values = tuple(str(item.get("prefix") or item.get("prefix_name")) for item in prefixes if isinstance(item, Mapping) and (item.get("prefix") or item.get("prefix_name")))
    if asn.isdigit():
        yield ASNRecord(asn, organisation=str(data.get("name") or data.get("description") or ""), provider=str(data.get("name") or ""), prefixes=values)


def parse_bgp_routes(payload: Any, _source: str) -> Iterable[BGPRoute]:
    values = payload.get("data", payload) if isinstance(payload, Mapping) else payload
    if isinstance(values, Mapping):
        values = values.get("routes", values.get("prefixes", ()))
    for item in values if isinstance(values, (list, tuple)) else ():
        if not isinstance(item, Mapping):
            continue
        prefix = item.get("prefix") or item.get("prefix_name")
        origin = item.get("origin_asn") or item.get("origin") or item.get("asn")
        if prefix and origin:
            yield BGPRoute(
                str(prefix),
                str(origin),
                str(item.get("status", "stable")),
                int(item.get("stable_days", 0) or 0),
                str(item.get("rpki_status", "unknown")),
                str(item.get("previous_origin_asn", "")),
                _utc(item.get("first_seen"), None) if item.get("first_seen") else None,
                _utc(item.get("last_seen"), None) if item.get("last_seen") else None,
            )


def parse_rpki(payload: Any, _source: str) -> Iterable[BGPRoute]:
    data = payload.get("data", payload) if isinstance(payload, Mapping) else {}
    prefix = data.get("prefix") or data.get("resource")
    origin = data.get("origin") or data.get("origin_asn") or data.get("asn") or "unknown"
    status = data.get("status") or data.get("validity") or data.get("rpki_status") or "unknown"
    if prefix:
        yield BGPRoute(
            str(prefix),
            str(origin),
            status=str(status).casefold(),
            rpki_status=str(status).casefold(),
            first_seen=_utc(data.get("first_seen"), None) if data.get("first_seen") else None,
            last_seen=_utc(data.get("last_seen"), None) if data.get("last_seen") else None,
        )


@dataclass(frozen=True)
class SyncResult:
    provider_id: str
    state: str
    fetched: int = 0
    stored: int = 0
    error: str | None = None
    next_run: datetime | None = None


class FeedScheduler:
    """Central scheduler with per-provider intervals, retry and rate limits."""

    def __init__(self, registry: ThreatProviderRegistry, store: IntelligenceStore, adapters: Iterable[FeedAdapter] = (), *, max_workers: int = 4, retry_base_seconds: float = 30.0, retry_max_seconds: float = 3600.0) -> None:
        self.registry = registry
        self.store = store
        self.adapters = {adapter.provider.id: adapter for adapter in adapters}
        self.retry_base_seconds = max(1.0, retry_base_seconds)
        self.retry_max_seconds = max(self.retry_base_seconds, retry_max_seconds)
        self._pool = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="clawforge-feed")
        self._lock = threading.RLock()
        self._last_attempt: dict[str, float] = {}
        self._next_run: dict[str, datetime] = {}
        self._failures: dict[str, int] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add(self, adapter: FeedAdapter) -> None:
        self.adapters[adapter.provider.id] = adapter
        self.store.register_provider(adapter.provider)

    def run_once(self, provider_id: str, *, now: datetime | None = None, force: bool = False) -> SyncResult:
        provider = self.registry.get(provider_id)
        adapter = self.adapters.get(provider_id)
        if provider is None or adapter is None:
            raise KeyError(provider_id)
        if not provider.enabled:
            return SyncResult(provider_id, "disabled")
        now = now or datetime.now(UTC)
        current = time.monotonic()
        with self._lock:
            if not force and provider_id in self._next_run and now < self._next_run[provider_id]:
                return SyncResult(provider_id, "not_due", next_run=self._next_run[provider_id])
            previous = self._last_attempt.get(provider_id, 0.0)
            if current - previous < adapter.rate_limit_seconds:
                next_run = now + timedelta(seconds=adapter.rate_limit_seconds - (current - previous))
                self._next_run[provider_id] = next_run
                self.store.update_provider_status(provider_id, state="rate_limited", next_run=next_run, retry_after=next_run)
                return SyncResult(provider_id, "rate_limited", next_run=next_run)
            self._last_attempt[provider_id] = current
        self.store.update_provider_status(provider_id, state="running", last_attempt=now, error=None)
        future: Future[int] = self._pool.submit(adapter.sync, self.store)
        try:
            stored = future.result(timeout=adapter.timeout_seconds)
            adapter.expire(self.store, now)
        except FutureTimeout:
            future.cancel()
            return self._failure(provider_id, now, FeedTimeoutError(f"timeout after {adapter.timeout_seconds}s"))
        except Exception as exc:  # provider failure must not stop other feeds
            return self._failure(provider_id, now, exc)
        next_run = now + provider.update_interval
        with self._lock:
            self._failures[provider_id] = 0
            self._next_run[provider_id] = next_run
        provider.last_sync = now
        provider.data_age = timedelta(0)
        provider.hits = stored
        self.store.update_provider_status(provider_id, state="ok", last_success=now, next_run=next_run, failure_count=0, error=None, retry_after=None, indicators_count=stored)
        return SyncResult(provider_id, "ok", fetched=stored, stored=stored, next_run=next_run)

    def _failure(self, provider_id: str, now: datetime, error: Exception) -> SyncResult:
        with self._lock:
            failures = self._failures.get(provider_id, 0) + 1
            self._failures[provider_id] = failures
            delay = min(self.retry_max_seconds, self.retry_base_seconds * (2 ** (failures - 1)))
            next_run = now + timedelta(seconds=delay)
            self._next_run[provider_id] = next_run
        message = str(error)
        provider = self.registry.get(provider_id)
        if provider is not None:
            provider.error = message
            provider.last_sync = now
        self.store.update_provider_status(provider_id, state="error", next_run=next_run, retry_after=next_run, failure_count=failures, error=message)
        self.store.record_audit_event(
            "intelligence_provider_error",
            subject=provider_id,
            details={"error": message, "failure_count": failures},
            created_at=now,
        )
        return SyncResult(provider_id, "error", error=message, next_run=next_run)

    def run_due(self, *, now: datetime | None = None) -> tuple[SyncResult, ...]:
        now = now or datetime.now(UTC)
        results = [self.run_once(provider_id, now=now) for provider_id in tuple(self.adapters)]
        self.store.expire(now)
        return tuple(results)

    def start(self, poll_seconds: float = 5.0) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, args=(max(1.0, poll_seconds),), daemon=True, name="clawforge-feed-scheduler")
            self._thread.start()

    def _loop(self, poll_seconds: float) -> None:
        while not self._stop.is_set():
            self.run_due()
            self._stop.wait(poll_seconds)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread:
            thread.join(timeout=5)
        self._pool.shutdown(wait=False, cancel_futures=True)

    def status(self) -> list[dict[str, Any]]:
        return self.store.provider_status()


def _provider(ident: str, name: str, source: str, interval: int, categories: tuple[str, ...], confidence: int = 70) -> ThreatProvider:
    return ThreatProvider(ident, name, source, update_interval=timedelta(minutes=interval), confidence=confidence, categories=categories)


def build_feed_registry(*, env: Mapping[str, str] | None = None, client: FeedHTTPClient | None = None) -> tuple[ThreatProviderRegistry, IntelligenceStore, FeedScheduler]:
    """Build all configured source adapters; credentials remain environment-owned."""
    env = env or os.environ
    registry = ThreatProviderRegistry()
    adapters: list[FeedAdapter] = []
    def add(provider: ThreatProvider, adapter: FeedAdapter) -> None:
        registry.add(provider)
        adapters.append(adapter)

    common = {"timeout_seconds": float(env.get("CLAWFORGE_FEED_TIMEOUT_SECONDS", "20"))}
    abuse_key = env.get("CLAWFORGE_ABUSECH_AUTH_KEY", "").strip()
    auth = {"Auth-Key": abuse_key} if abuse_key else {}
    provider = _provider("abusech-urlhaus", "URLhaus", "abuse.ch", 15, ("malware-url",))
    add(provider, FeedAdapter(provider, f"https://urlhaus-api.abuse.ch/v2/files/exports/{abuse_key}/recent.json" if abuse_key else "https://urlhaus.abuse.ch/feeds/", parser=parse_urlhaus, headers=auth, rate_limit_seconds=300, client=client, **common))
    provider = _provider("abusech-threatfox", "ThreatFox", "abuse.ch", 15, ("ioc",))
    add(provider, FeedAdapter(provider, "https://threatfox-api.abuse.ch/api/v1/", parser=parse_threatfox, method="POST", headers={**auth, "Content-Type": "application/json"}, body=json.dumps({"query": "get_iocs", "days": 1}).encode(), rate_limit_seconds=60, client=client, **common))
    provider = _provider("abusech-feodo", "Feodo Tracker", "abuse.ch", 30, ("botnet-c2",))
    add(provider, FeedAdapter(provider, "https://feodotracker.abuse.ch/downloads/ipblocklist.json", parser=parse_feodo, rate_limit_seconds=300, client=client, **common))
    provider = _provider("abusech-malwarebazaar", "MalwareBazaar", "abuse.ch", 1440, ("malware-hash",))
    add(provider, FeedAdapter(provider, "https://mb-api.abuse.ch/api/v1/", parser=parse_malwarebazaar, method="POST", headers={**auth, "Content-Type": "application/x-www-form-urlencoded"}, body=urlencode({"query": "get_recent", "selector": "time"}).encode(), rate_limit_seconds=900, client=client, **common))
    for ident, name, endpoint, category in (("spamhaus-drop", "Spamhaus DROP", "https://www.spamhaus.org/drop/drop.txt", "spamhaus-drop"), ("spamhaus-edrop", "Spamhaus EDROP", "https://www.spamhaus.org/drop/edrop.txt", "spamhaus-edrop"), ("blocklist-de", "Blocklist.de", "https://lists.blocklist.de/lists/all.txt", "attack"), ("dshield", "DShield / SANS ISC", "https://feeds.dshield.org/block.txt", "scanner"), ("firehol", "FireHOL Lists", "https://raw.githubusercontent.com/firehol/blocklist-ipsets/master/firehol_level1.netset", "aggregated"), ("emerging-threats", "Emerging Threats Open", "https://rules.emergingthreats.net/open/suricata/rules/", "ids"), ("tor-exit", "Tor Exit Lists", "https://check.torproject.org/torbulkexitlist", "tor-exit")):
        provider = _provider(ident, name, endpoint, 30, (category,), 70)
        add(provider, FeedAdapter(provider, endpoint, parser=lambda payload, source, category=category: parse_text_indicators(payload, source, category), rate_limit_seconds=300, client=client, **common))
    for ident, name, endpoint, parser, category in (("openphish", "OpenPhish", "https://raw.githubusercontent.com/openphish/public_feed/main/feed.txt", parse_openphish, "phishing"), ("phishtank", "PhishTank", "https://data.phishtank.com/data/online-valid.json", parse_generic_indicator_feed, "phishing")):
        provider = _provider(ident, name, endpoint, 30, (category,), 75)
        add(provider, FeedAdapter(provider, endpoint, parser=lambda payload, source, parser=parser, category=category: parser(payload, source, category) if parser is parse_generic_indicator_feed else parser(payload, source), rate_limit_seconds=300, client=client, **common))
    provider = _provider("greynoise-community", "GreyNoise Community", "https://api.greynoise.io/v3/community/", 60, ("scanner",), 65)
    add(provider, FeedAdapter(provider, "https://api.greynoise.io/v3/community/", parser=parse_generic_indicator_feed, rate_limit_seconds=60, client=client, **common))
    provider = _provider("cisa-kev", "CISA KEV", "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json", 1440, ("known-exploited-vulnerability",), 90)
    add(provider, FeedAdapter(provider, provider.source, parser=parse_cisa_kev, rate_limit_seconds=900, client=client, **common))
    provider = _provider("nvd", "NVD", "https://services.nvd.nist.gov/rest/json/cves/2.0", 1440, ("cve",), 60)
    add(provider, FeedAdapter(provider, provider.source, parser=parse_nvd, rate_limit_seconds=30, client=client, **common))
    provider = _provider("virustotal", "VirusTotal", "https://www.virustotal.com/api/v3/", 1440, ("malware",), 65)
    add(provider, FeedAdapter(provider, provider.source, parser=parse_generic_indicator_feed, headers={"x-apikey": env.get("CLAWFORGE_VIRUSTOTAL_API_KEY", "")}, rate_limit_seconds=15, client=client, **common))
    provider = _provider("ripe-stat", "RIPEstat", "https://stat.ripe.net/data/as-overview/data.json", 360, ("asn",), 70)
    add(provider, ASNFeedAdapter(provider, provider.source, parser=parse_ripe_asn, rate_limit_seconds=60, client=client, **common))
    provider = _provider("bgpview", "BGPView", "https://api.bgpview.io/asn/", 360, ("asn",), 65)
    add(provider, ASNFeedAdapter(provider, provider.source, parser=parse_bgpview_asn, rate_limit_seconds=60, client=client, **common))
    for ident, name, endpoint in (("ripe-ris", "RIPE RIS", "https://stat.ripe.net/data/ris-prefixes/data.json"), ("routeviews", "RouteViews", "https://api.routeviews.org/"), ("bgpstream", "BGPStream", "https://bgpstream.com/"), ("caida-bgp", "CAIDA", "https://topology.eecs.umich.edu/")):
        provider = _provider(ident, name, endpoint, 60, ("bgp",), 65)
        add(provider, BGPFeedAdapter(provider, endpoint, parser=parse_bgp_routes, rate_limit_seconds=60, client=client, **common))
    provider = _provider("rpki-validator", "RPKI Validator", "https://stat.ripe.net/data/rpki-validation/data.json", 60, ("rpki",), 80)
    add(provider, BGPFeedAdapter(provider, provider.source, parser=parse_rpki, rate_limit_seconds=60, client=client, **common))
    for ident, name, endpoint in (("caida-asrank", "CAIDA AS Rank", "https://api.asrank.caida.org/v2/graphql"), ("team-cymru", "Team Cymru Community", "https://whois.cymru.com/"), ("peeringdb", "PeeringDB", "https://www.peeringdb.com/api/net"), ("spamhaus-asn", "Spamhaus ASN Reputation", "https://www.spamhaus.com/drop/asndrop.txt"), ("epss", "EPSS", "https://api.first.org/data/v1/epss")):
        provider = _provider(ident, name, endpoint, 1440, ("network-context",), 55)
        add(provider, FeedAdapter(provider, endpoint, parser=parse_generic_indicator_feed, rate_limit_seconds=300, client=client, **common))
    path = env.get("CLAWFORGE_INTELLIGENCE_DB", "") or os.path.join(env.get("SUPERMARKT_DATA_DIR", "."), "clawforge-intelligence.sqlite3")
    backend = backend_from_environment(env, path)
    store = IntelligenceStore(path, backend=backend)
    for provider in registry.all():
        store.register_provider(provider)
    store.attach_consumer(IntelligenceConsumer(store))
    scheduler = FeedScheduler(registry, store, adapters)
    return registry, store, scheduler


def parse_generic_indicator_feed(payload: Any, source: str, _category: str = "reputation") -> Iterable[ThreatIndicator]:
    values = payload if isinstance(payload, (list, tuple)) else payload.get("data", ()) if isinstance(payload, Mapping) else ()
    for item in values:
        if isinstance(item, Mapping):
            value = item.get("indicator") or item.get("ioc") or item.get("ip") or item.get("url") or item.get("domain") or item.get("value")
            if value:
                kind = item.get("type") or item.get("indicator_type") or IndicatorType.DOMAIN
                yield _indicator(value, _ioc_type(str(kind)), source=source, categories=item.get("categories", ("reputation",)), confidence=item.get("confidence", 50), first_seen=item.get("first_seen"), last_seen=item.get("last_seen"), metadata=item)


@dataclass
class IntelligenceService:
    registry: ThreatProviderRegistry
    store: IntelligenceStore
    scheduler: FeedScheduler
    trust: TrustedNetworkRegistry
    consumer: IntelligenceConsumer

    @classmethod
    def create(cls, *, env: Mapping[str, str] | None = None) -> "IntelligenceService":
        registry, store, scheduler = build_feed_registry(env=env)
        trust = TrustedNetworkRegistry()
        consumer = IntelligenceConsumer(store, trusted_networks=trust)
        store.attach_consumer(consumer)
        return cls(registry, store, scheduler, trust, consumer)

    def start(self) -> None:
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()

    def providers(self) -> list[dict[str, Any]]:
        status_by_id = {item["provider_id"]: item for item in self.store.provider_status()}
        values = []
        for provider in self.registry.dashboard():
            status = status_by_id.get(provider["id"], {})
            provider.update(
                state=status.get("state", "never"),
                last_attempt=status.get("last_attempt"),
                last_success=status.get("last_success"),
                next_run=status.get("next_run"),
                failure_count=status.get("failure_count", 0),
                indicators_count=status.get("indicators_count", 0),
                error=status.get("error"),
            )
            values.append(provider)
        return values

    def status(self) -> list[dict[str, Any]]:
        return self.scheduler.status()


@dataclass(frozen=True)
class FeedSourceRegistry:
    """Named bundle of providers and adapters used by an installation."""

    providers: ThreatProviderRegistry
    store: IntelligenceStore
    scheduler: FeedScheduler

    @classmethod
    def create(cls, *, env: Mapping[str, str] | None = None, client: FeedHTTPClient | None = None) -> "FeedSourceRegistry":
        providers, store, scheduler = build_feed_registry(env=env, client=client)
        store.attach_consumer(IntelligenceConsumer(store))
        return cls(providers, store, scheduler)


__all__ = [
    "ASNFeedAdapter",
    "BGPFeedAdapter",
    "FeedAdapter",
    "FeedHTTPClient",
    "FeedRateLimitError",
    "FeedScheduler",
    "FeedSourceRegistry",
    "FeedSyncError",
    "FeedTimeoutError",
    "HTTPFeedResponse",
    "IntelligenceConsumer",
    "IntelligenceService",
    "IntelligenceStore",
    "RiskEvent",
    "SyncResult",
    "build_feed_registry",
    "parse_bgp_routes",
    "parse_feodo",
    "parse_malwarebazaar",
    "parse_openphish",
    "parse_rpki",
    "parse_text_indicators",
    "parse_threatfox",
    "parse_urlhaus",
]
