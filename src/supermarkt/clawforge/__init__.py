"""Trusted infrastructure and network intelligence primitives for Clawforge.

The package deliberately does not infer trust from the technology in use.  A
Tailnet, NetBird network, VLAN, VPN, IP range, ASN, or BGP prefix becomes
trusted only after an administrator registers and verifies it.
"""

from .network_trust import (
    BGPStatus,
    NetworkObservation,
    NetworkType,
    RPKIStatus,
    RiskAssessment,
    TrustedNetwork,
    TrustedNetworkRegistry,
    VerificationStatus,
    assess_network,
    network_intelligence,
)
from .intelligence import (
    ASNIntelligence,
    ASNNetworkType,
    ASNRecord,
    BGPIntelligence,
    BGPRoute,
    IndicatorType,
    ThreatIndicator,
    ThreatProvider,
    ThreatProviderRegistry,
    builtin_providers,
    effective_indicator_confidence,
)
from .risk_engine import CompositeAssessment, Decision, PolicyEngine, RiskEngine, RiskSignals
from .persistence import DatabaseBackend, Migration, MigrationRunner, PostgreSQLBackend, SQLiteBackend, backend_from_environment
from .backup import BackupManager, BackupManifest
from .feed_sync import (
    FeedAdapter,
    FeedHTTPClient,
    FeedScheduler,
    FeedSourceRegistry,
    FeedSyncError,
    IntelligenceConsumer,
    IntelligenceService,
    IntelligenceStore,
    RiskEvent,
    SyncResult,
    build_feed_registry,
)

__all__ = [
    "BGPStatus",
    "NetworkObservation",
    "NetworkType",
    "RPKIStatus",
    "RiskAssessment",
    "TrustedNetwork",
    "TrustedNetworkRegistry",
    "VerificationStatus",
    "assess_network",
    "network_intelligence",
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
    "CompositeAssessment",
    "Decision",
    "PolicyEngine",
    "RiskEngine",
    "RiskSignals",
    "DatabaseBackend",
    "BackupManager",
    "BackupManifest",
    "Migration",
    "MigrationRunner",
    "PostgreSQLBackend",
    "SQLiteBackend",
    "backend_from_environment",
    "FeedAdapter",
    "FeedHTTPClient",
    "FeedScheduler",
    "FeedSourceRegistry",
    "FeedSyncError",
    "IntelligenceConsumer",
    "IntelligenceService",
    "IntelligenceStore",
    "RiskEvent",
    "SyncResult",
    "build_feed_registry",
]
