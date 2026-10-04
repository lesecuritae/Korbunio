from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .config import CACHE_TTL_MINUTES, CACHE_WEEKLY
from .security import api_auth_configured
from . import runtime

router = APIRouter()


@router.get("/health/sources", include_in_schema=False)
def health_sources() -> dict[str, Any]:
    """Wann hat der Server je Händler zuletzt Angebote gesehen (aus dem Preisverlauf)."""
    from . import history
    try:
        return {"retailers": history.retailer_status()}
    except Exception:  # noqa: BLE001 - Diagnose darf nie stören
        return {"retailers": []}


@router.get("/health", include_in_schema=False)
def health() -> dict[str, Any]:
    engine = runtime.get_engine()
    return {
        "status": "ok",
        "service": "korbunio",
        "backend": "persistent-sqlite-cache",
        "cache_ttl_minutes": CACHE_TTL_MINUTES,
        "cache_weekly": CACHE_WEEKLY,
        "api_auth_configured": api_auth_configured(),
        **runtime.get_image_service().health(),
        "sources": {
            "REWE": "official primary with Marktguru fallback",
            "EDEKA": "official primary with Marktguru fallback",
            "Kaufland": "official primary with Marktguru fallback",
            "Marktkauf": "official primary with Marktguru fallback",
            "ALDI": "official primary with Marktguru fallback",
            "Lidl": "Marktguru regional catalogue",
            "PENNY": "Marktguru regional catalogue",
            "Netto Marken-Discount": "Marktguru regional catalogue",
            "Netto schwarz": "official weekly offers",
            "Rossmann": "official advertising offers",
            "Müller": "official online offers",
            "dm": "official clearance catalogue; branch availability unknown",
            "Globus": "official primary with Marktguru fallback",
            "famila Nordwest": "Marktguru regional catalogue",
            "aktiv & irma": "official weekly flyer (regional)",
            "Combi": "Marktguru regional catalogue",
            "HOL’AB!": "official regional selected offers",
        },
        **engine.store.health(),
    }
