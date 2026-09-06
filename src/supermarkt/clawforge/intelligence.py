"""Provider, ASN, BGP, and RPKI intelligence primitives.

Network access is deliberately outside this module.  Adapters fetch a source
and hand its payload to a provider; this keeps parsers deterministic and makes
feed failures observable instead of silently changing a risk decision.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit


class IndicatorType(StrEnum):
    IP = "ip"
    PREFIX = "prefix"
    DOMAIN = "domain"
    URL = "url"
    HASH = "hash"
    ASN = "asn"


@dataclass(frozen=True)
class ThreatIndicator:
    value: str
    indicator_type: IndicatorType | str
    categories: tuple[str, ...] = ()
    confidence: int = 0
    source: str = ""
    observed_at: datetime | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    expires_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "indicator_type", IndicatorType(self.indicator_type))
        object.__setattr__(self, "categories", tuple(dict.fromkeys(str(x) for x in self.categories)))
        object.__setattr__(self, "confidence", max(0, min(100, int(self.confidence))))


@dataclass
class ThreatProvider:
    """A single independently switchable threat feed adapter."""

    id: str
    name: str
    source: str
    update_interval: timedelta = timedelta(hours=1)
    parser: Callable[[Any], Iterable[ThreatIndicator]] | None = None
    normalizer: Callable[[ThreatIndicator], ThreatIndicator] | None = None
    confidence: int = 50
    categories: tuple[str, ...] = ()
    enabled: bool = True
    data_age: timedelta | None = None
    last_sync: datetime | None = None
    error: str | None = None
    hits: int = 0

    def parse(self, payload: Any) -> tuple[ThreatIndicator, ...]:
        if not self.enabled:
            return ()
        try:
            parser = self.parser or parse_generic_feed
            values = tuple(parser(payload))
            result = []
            for indicator in values:
                if isinstance(indicator, Mapping):
                    indicator = ThreatIndicator(**indicator)
                normalized = self.normalizer(indicator) if self.normalizer else normalize_indicator(indicator)
                normalized = ThreatIndicator(**{**normalized.__dict__, "confidence": min(normalized.confidence, self.confidence)})
                if not normalized.source:
                    normalized = ThreatIndicator(**{**normalized.__dict__, "source": self.id})
                result.append(normalized)
            self.hits = len(result)
            self.last_sync = datetime.now(UTC)
            self.data_age = timedelta(0)
            self.error = None
            return tuple(result)
        except Exception as exc:  # provider errors must not take down scoring
            self.error = str(exc)
            self.last_sync = datetime.now(UTC)
            return ()

    def mark_stale(self, now: datetime | None = None) -> None:
        if self.last_sync is not None:
            self.data_age = (now or datetime.now(UTC)) - self.last_sync


def normalize_indicator(indicator: ThreatIndicator) -> ThreatIndicator:
    value = indicator.value.strip()
    if indicator.indicator_type is IndicatorType.DOMAIN:
        value = value.casefold().rstrip(".")
    elif indicator.indicator_type is IndicatorType.URL:
        parsed = urlsplit(value)
        if parsed.scheme and parsed.netloc:
            value = f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}{parsed.path}"
    elif indicator.indicator_type is IndicatorType.IP:
        try:
            value = str(ipaddress.ip_address(value))
        except ValueError:
            pass
    return ThreatIndicator(
        value=value,
        indicator_type=indicator.indicator_type,
        categories=indicator.categories,
        confidence=indicator.confidence,
        source=indicator.source,
        observed_at=indicator.observed_at,
        first_seen=indicator.first_seen,
        last_seen=indicator.last_seen,
        expires_at=indicator.expires_at,
        metadata=indicator.metadata,
    )


def _type_for(value: str) -> IndicatorType:
    try:
        ipaddress.ip_address(value)
        return IndicatorType.IP
    except ValueError:
        pass
    if re.fullmatch(r"(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{40}|[a-fA-F0-9]{64})", value):
        return IndicatorType.HASH
    if value.startswith(("http://", "https://")):
        return IndicatorType.URL
    if value.lower().startswith("as") and value[2:].isdigit():
        return IndicatorType.ASN
    return IndicatorType.DOMAIN


def parse_generic_feed(payload: Any) -> Iterable[ThreatIndicator]:
    """Parse common JSON records or newline-delimited IOC lists."""
    if isinstance(payload, str):
        records: Iterable[Any] = payload.splitlines()
    elif isinstance(payload, Mapping):
        records = payload.get("data", payload.get("results", payload.get("iocs", ())))
        if isinstance(records, (str, Mapping)):
            records = (records,)
    elif isinstance(payload, Iterable):
        records = payload
    else:
        raise TypeError("feed payload must be text, a mapping, or an iterable")
    for record in records:
        if isinstance(record, Mapping):
            value = record.get("value") or record.get("ioc") or record.get("url") or record.get("ip") or record.get("domain")
            if not value:
                continue
            kind = record.get("type") or record.get("indicator_type")
            confidence = record.get("confidence", 50)
            categories = record.get("categories", record.get("category", ()))
            if isinstance(categories, str):
                categories = (categories,)
        else:
            value = str(record).strip()
            kind, confidence, categories = None, 50, ()
        if value:
            yield ThreatIndicator(str(value), kind or _type_for(str(value)), tuple(categories), int(confidence))


class ThreatProviderRegistry:
    def __init__(self, providers: Iterable[ThreatProvider] = ()) -> None:
        self._providers = {provider.id: provider for provider in providers}

    def add(self, provider: ThreatProvider) -> ThreatProvider:
        if provider.id in self._providers:
            raise ValueError(f"provider already registered: {provider.id}")
        self._providers[provider.id] = provider
        return provider

    def get(self, provider_id: str) -> ThreatProvider | None:
        return self._providers.get(provider_id)

    def enable(self, provider_id: str) -> None:
        self._providers[provider_id].enabled = True

    def disable(self, provider_id: str) -> None:
        self._providers[provider_id].enabled = False

    def ingest(self, provider_id: str, payload: Any) -> tuple[ThreatIndicator, ...]:
        provider = self._providers[provider_id]
        return provider.parse(payload)

    def all(self) -> tuple[ThreatProvider, ...]:
        return tuple(self._providers.values())

    def dashboard(self) -> list[dict[str, Any]]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "source": p.source,
                "enabled": p.enabled,
                "last_sync": p.last_sync.isoformat() if p.last_sync else None,
                "data_age_seconds": p.data_age.total_seconds() if p.data_age else None,
                "hits": p.hits,
                "error": p.error,
            }
            for p in self.all()
        ]


def builtin_providers() -> ThreatProviderRegistry:
    """Return metadata for supported sources without enabling network access."""
    sources = (
        ("abusech-urlhaus", "URLhaus", "abuse.ch", ("malware-url",)),
        ("abusech-threatfox", "ThreatFox", "abuse.ch", ("ioc",)),
        ("abusech-feodo", "Feodo Tracker", "abuse.ch", ("botnet-c2",)),
        ("abusech-malwarebazaar", "MalwareBazaar", "abuse.ch", ("malware-hash",)),
        ("spamhaus", "Spamhaus", "spamhaus.org", ("drop", "edrop", "asn")),
        ("openphish", "OpenPhish", "openphish.com", ("phishing",)),
        ("phishtank", "PhishTank", "phishtank.org", ("phishing",)),
        ("dshield", "DShield / SANS ISC", "isc.sans.edu", ("scanner", "bruteforce")),
        ("blocklist-de", "Blocklist.de", "blocklist.de", ("attack",)),
        ("firehol", "FireHOL Lists", "firehol.org", ("aggregated",)),
        ("emerging-threats", "Emerging Threats Open", "proofpoint.com", ("ids",)),
        ("greynoise-community", "GreyNoise Community", "greynoise.io", ("scanner",)),
        ("virustotal", "VirusTotal", "virustotal.com", ("malware",)),
        ("cisa-kev", "CISA KEV", "cisa.gov", ("known-exploited",)),
        ("nvd", "NVD", "nvd.nist.gov", ("vulnerability",)),
        ("epss", "EPSS", "first.org", ("exploit-probability",)),
    )
    return ThreatProviderRegistry(
        ThreatProvider(id=ident, name=name, source=source, categories=categories)
        for ident, name, source, categories in sources
    )


class ASNNetworkType(StrEnum):
    RESIDENTIAL_ISP = "residential_isp"
    ENTERPRISE = "enterprise"
    CLOUD_PROVIDER = "cloud_provider"
    VPN_PROVIDER = "vpn_provider"
    HOSTING_PROVIDER = "hosting_provider"
    BULLETPROOF_HOSTING = "bulletproof_hosting"
    TOR_EXIT = "tor_exit"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ASNRecord:
    asn: str
    organisation: str = ""
    provider: str = ""
    country: str = ""
    prefixes: tuple[str, ...] = ()
    network_type: ASNNetworkType | str = ASNNetworkType.UNKNOWN
    reputation: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "asn", self.asn.upper().removeprefix("AS"))
        object.__setattr__(self, "network_type", ASNNetworkType(self.network_type))
        object.__setattr__(self, "reputation", max(0, min(30, int(self.reputation))))


class ASNIntelligence:
    def __init__(self, records: Iterable[ASNRecord] = ()) -> None:
        self._records = {record.asn: record for record in records}

    def add(self, record: ASNRecord) -> None:
        self._records[record.asn] = record

    def lookup(self, asn: str) -> ASNRecord | None:
        return self._records.get(str(asn).upper().removeprefix("AS"))

    def for_ip(self, ip: str) -> ASNRecord | None:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return None
        for record in self._records.values():
            for prefix in record.prefixes:
                try:
                    if address in ipaddress.ip_network(prefix, strict=False):
                        return record
                except ValueError:
                    continue
        return None


@dataclass(frozen=True)
class BGPRoute:
    prefix: str
    origin_asn: str
    status: str = "stable"
    stable_days: int = 0
    rpki_status: str = "unknown"
    previous_origin_asn: str = ""


class BGPIntelligence:
    def __init__(self, routes: Iterable[BGPRoute] = ()) -> None:
        self._routes = {route.prefix: route for route in routes}

    def add(self, route: BGPRoute) -> None:
        self._routes[route.prefix] = route

    def lookup(self, prefix: str) -> BGPRoute | None:
        return self._routes.get(prefix)

    def assess(self, prefix: str, origin_asn: str) -> dict[str, Any]:
        route = self.lookup(prefix)
        if route is None:
            return {"known": False, "anomaly": True, "reason": "new unknown route"}
        origin = str(origin_asn).upper().removeprefix("AS")
        changed = route.origin_asn.upper().removeprefix("AS") != origin
        return {
            "known": True,
            "anomaly": changed or route.status in ("changed", "anomalous"),
            "origin_changed": changed,
            "stable": route.stable_days >= 30 and not changed,
            "status": route.status,
            "rpki_status": route.rpki_status,
        }


def effective_indicator_confidence(indicator: ThreatIndicator, now: datetime | None = None) -> int:
    """Age old reports so one stale report cannot dominate current evidence."""
    if indicator.last_seen is None:
        return indicator.confidence
    age = (now or datetime.now(UTC)) - indicator.last_seen
    if age <= timedelta(days=7):
        return indicator.confidence
    if age >= timedelta(days=180):
        return indicator.confidence // 4
    return max(0, int(indicator.confidence * (1 - age.days / 240)))


__all__ = [
    "ASNIntelligence",
    "ASNNetworkType",
    "ASNRecord",
    "BGPIntelligence",
    "BGPRoute",
    "IndicatorType",
    "ThreatIndicator",
    "ThreatProvider",
    "ThreatProviderRegistry",
    "builtin_providers",
    "effective_indicator_confidence",
    "normalize_indicator",
    "parse_generic_feed",
]
