"""Regional supermarket offer comparison for Germany."""

from .loyalty import LoyaltyProgram, PROGRAMS
from .models import LoyaltyBenefit, Offer, RetailerContext, RetailerSpec
from .service import SupermarketEngine
from .version import __version__
from .web import router

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
]
