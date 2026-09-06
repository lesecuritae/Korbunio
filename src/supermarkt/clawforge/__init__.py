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
from .feed_sync import (
    FeedAdapter,
    FeedHTTPClient,
    FeedScheduler,
    FeedSourceRegistry,
    FeedSyncError,
    IntelligenceService,
    IntelligenceStore,
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
    "FeedAdapter",
    "FeedHTTPClient",
    "FeedScheduler",
    "FeedSourceRegistry",
    "FeedSyncError",
    "IntelligenceService",
    "IntelligenceStore",
    "SyncResult",
    "build_feed_registry",
]
