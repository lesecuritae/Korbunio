"""Regional supermarket offer comparison for Germany."""

from .loyalty import LoyaltyProgram, PROGRAMS
from .models import LoyaltyBenefit, Offer, RetailerContext, RetailerSpec
from .service import SupermarketEngine
from .version import __version__
from .web import router
from .clawforge import (
    ASNIntelligence,
    BGPIntelligence,
    NetworkObservation,
    RiskEngine,
    TrustedNetwork,
    TrustedNetworkRegistry,
    assess_network,
    network_intelligence,
)
from .clawforge.feed_sync import FeedScheduler, IntelligenceConsumer, IntelligenceService, IntelligenceStore

__all__ = [
    "__version__",
    "LoyaltyBenefit",
    "LoyaltyProgram",
    "Offer",
    "PROGRAMS",
    "RetailerContext",
    "RetailerSpec",
    "SupermarketEngine",
    "router",
    "ASNIntelligence",
    "BGPIntelligence",
    "NetworkObservation",
    "RiskEngine",
    "TrustedNetwork",
    "TrustedNetworkRegistry",
    "assess_network",
    "network_intelligence",
    "FeedScheduler",
    "IntelligenceConsumer",
    "IntelligenceService",
    "IntelligenceStore",
]
